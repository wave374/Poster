import os
import io
import time
import threading
import re
import math
import textwrap
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

# ── Dummy HTTP server so Render detects an open port ──
class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")
    def log_message(self, *args):
        pass

_port = int(os.environ.get("PORT", 10000))
_server = HTTPServer(("0.0.0.0", _port), _Handler)
threading.Thread(target=_server.serve_forever, daemon=True).start()
print(f"Dummy server listening on port {_port}")

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN  = "YOUR_BOT_TOKEN_HERE"
BRAND_NAME = "ANIMEFLIO"
JIKAN_API  = "https://api.jikan.moe/v4"

ASK_ANIME, ASK_CONFIRM, ASK_PHOTO, ASK_BRAND, ASK_COLOR, ASK_STYLE = range(6)

# ─── COLOR THEMES ─────────────────────────────────────────────────────────────
THEMES = {
    "green":  {"accent": (34, 197, 94),  "bg": (13, 26, 13),   "hex_out": (30, 55, 30),  "hex_fill": (13, 22, 13),  "emoji": "🟢"},
    "orange": {"accent": (251, 146, 60),  "bg": (26, 16, 8),    "hex_out": (55, 30, 10),  "hex_fill": (22, 13, 6),   "emoji": "🟠"},
    "cyan":   {"accent": (34, 211, 238),  "bg": (8, 22, 26),    "hex_out": (10, 45, 55),  "hex_fill": (6, 18, 22),   "emoji": "🔵"},
    "red":    {"accent": (239, 68, 68),   "bg": (26, 10, 10),   "hex_out": (55, 15, 15),  "hex_fill": (22, 8, 8),    "emoji": "🔴"},
    "purple": {"accent": (168, 85, 247),  "bg": (18, 10, 26),   "hex_out": (40, 20, 55),  "hex_fill": (15, 8, 22),   "emoji": "🟣"},
    "blue":   {"accent": (59, 130, 246),  "bg": (8, 14, 26),    "hex_out": (15, 30, 55),  "hex_fill": (6, 12, 22),   "emoji": "💙"},
    "pink":   {"accent": (236, 72, 153),  "bg": (26, 8, 18),    "hex_out": (55, 15, 40),  "hex_fill": (22, 6, 16),   "emoji": "🩷"},
    "yellow": {"accent": (234, 179, 8),   "bg": (26, 22, 5),    "hex_out": (55, 48, 10),  "hex_fill": (22, 19, 4),   "emoji": "🟡"},
}

GOLD  = (212, 168, 85)
WHITE = (255, 255, 255)
GRAY  = (180, 180, 180)
BLACK = (0, 0, 0)
W, H  = 1280, 720

# ─── FONT LOADER ──────────────────────────────────────────────────────────────
def load_font(size, bold=False):
    candidates = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
         "C:/Windows/Fonts/arialbd.ttf"]
        if bold else
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "C:/Windows/Fonts/arial.ttf"]
    )
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

# ─── HEX GRID ─────────────────────────────────────────────────────────────────
def draw_hex_grid(draw, width, height, hex_out, hex_fill):
    hex_size = 55
    hex_h    = math.sqrt(3) * hex_size
    col_w    = hex_size * 2 * 0.75
    cols = int(width / col_w) + 2
    rows = int(height / hex_h) + 2
    for col in range(cols):
        for row in range(rows):
            cx = col * col_w - hex_size
            cy = row * hex_h + (hex_h / 2 if col % 2 else 0) - hex_h / 2
            pts = [
                (cx + hex_size * math.cos(math.radians(60 * i)),
                 cy + hex_size * math.sin(math.radians(60 * i)))
                for i in range(6)
            ]
            draw.polygon(pts, outline=hex_out, fill=hex_fill)

# ─── POSTER BUILDER ───────────────────────────────────────────────────────────
def build_poster(anime: dict, photo_bytes: bytes, brand: str, theme_name: str = "green") -> bytes:
    theme   = THEMES.get(theme_name, THEMES["green"])
    ACCENT  = theme["accent"]
    BG_DARK = theme["bg"]

    title    = anime.get("title_english") or anime.get("title", "UNKNOWN")
    title_jp = anime.get("title", "")
    genres   = [g["name"].upper() for g in anime.get("genres", [])][:3]
    synopsis = anime.get("synopsis") or "No synopsis available."

    # Step 1: hex grid background
    base = Image.new("RGB", (W, H), BG_DARK)
    draw_hex_grid(ImageDraw.Draw(base), W, H, theme["hex_out"], theme["hex_fill"])

    # Step 2: photo right side with fade
    char_img = Image.open(io.BytesIO(photo_bytes)).convert("RGBA")
    char_w   = int(W * 0.62)
    scale    = H / char_img.height
    new_w    = int(char_img.width * scale)
    char_img = char_img.resize((new_w, H), Image.LANCZOS)
    if new_w > char_w:
        char_img = char_img.crop(((new_w - char_w) // 2, 0,
                                   (new_w - char_w) // 2 + char_w, H))
    elif new_w < char_w:
        padded = Image.new("RGBA", (char_w, H), (0, 0, 0, 0))
        padded.paste(char_img, ((char_w - new_w) // 2, 0))
        char_img = padded

    fade_mask = Image.new("L", (char_w, H), 0)
    fm_draw   = ImageDraw.Draw(fade_mask)
    fade_zone = int(char_w * 0.55)
    for x in range(char_w):
        alpha = int(255 * ((x / fade_zone) ** 2.2)) if x < fade_zone else 255
        fm_draw.line([(x, 0), (x, H)], fill=alpha)

    char_rgba = char_img.convert("RGBA")
    r, g, b, a = char_rgba.split()
    a = Image.composite(a, Image.new("L", a.size, 0), fade_mask)
    char_rgba = Image.merge("RGBA", (r, g, b, a))
    base_rgba = base.convert("RGBA")
    base_rgba.paste(char_rgba, (W - char_w, 0), char_rgba)
    base = base_rgba.convert("RGB")

    # Step 3: dark left overlay
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov_draw = ImageDraw.Draw(overlay)
    for x in range(int(W * 0.52)):
        alpha = int(180 * (1 - x / (W * 0.52)) ** 0.5)
        ov_draw.line([(x, 0), (x, H)], fill=(BG_DARK[0], BG_DARK[1], BG_DARK[2], alpha))
    base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(base)

    # Step 4: brand logo
    logo_cx, logo_cy, logo_r = 30, 30, 20
    hex_pts = [
        (logo_cx + logo_r * math.cos(math.radians(60 * i - 30)),
         logo_cy + logo_r * math.sin(math.radians(60 * i - 30)))
        for i in range(6)
    ]
    draw.polygon(hex_pts, outline=ACCENT, fill=BG_DARK)
    draw.text((logo_cx, logo_cy), brand[0].upper(),
              font=load_font(20, bold=True), fill=ACCENT, anchor="mm")
    draw.text((58, 18), brand.upper(), font=load_font(17, bold=True), fill=WHITE)

    # Step 5: Extract season number and clean title
    season_match = re.search(r'\b(season\s*\d+|\d+(?:st|nd|rd|th)\s*season)\b',
                             title, flags=re.IGNORECASE)
    season_text = None
    clean_title = title
    if season_match:
        raw = season_match.group(0)
        num = re.search(r'\d+', raw).group(0)
        season_text = f"SEASON {num}"
        clean_title = re.sub(r'\s*\b(season\s*\d+|\d+(?:st|nd|rd|th)\s*season)\b', '',
                             title, flags=re.IGNORECASE).strip()

    title_upper = clean_title.upper()
    max_w = int(W * 0.48)

    # Big white main title
    f_title = load_font(96, bold=True)
    while f_title.size > 40:
        bbox = draw.textbbox((0, 0), title_upper, font=f_title)
        if (bbox[2] - bbox[0]) <= max_w:
            break
        f_title = load_font(f_title.size - 6, bold=True)

    ty = int(H * 0.28)
    draw.text((38, ty), title_upper, font=f_title, fill=WHITE)
    title_bottom = draw.textbbox((38, ty), title_upper, font=f_title)[3]

    # Step 6: Season line in accent color (smaller than title, bigger than genres)
    if season_text:
        f_season = load_font(int(f_title.size * 0.55), bold=True)
        draw.text((38, title_bottom + 6), season_text, font=f_season, fill=ACCENT)
        title_bottom = draw.textbbox((38, title_bottom + 6), season_text, font=f_season)[3]

    # Step 7: genres gold
    gy, gx = title_bottom + 20, 38
    f_genre = load_font(16, bold=True)
    for gen in genres:
        draw.text((gx, gy), gen, font=f_genre, fill=GOLD)
        gx += draw.textbbox((0, 0), gen, font=f_genre)[2] + 28

    # Step 8: synopsis
    f_syn     = load_font(15)
    syn_clean = re.sub(r'\[.*?\]|\(.*?\)', '', synopsis).strip()
    wrapped   = textwrap.wrap(syn_clean, width=48)
    sy = gy + 36
    for line in wrapped[:6]:
        draw.text((38, sy), line, font=f_syn, fill=GRAY)
        sy += 24
    if len(wrapped) > 6:
        draw.text((38, sy), "...read more", font=f_syn, fill=ACCENT)
        sy += 24

    # Step 9: CTA buttons
    btn_y = sy + 18
    f_btn = load_font(16, bold=True)
    for i, label in enumerate(["DOWNLOAD", "JOIN NOW"]):
        bx = 38 + i * 220
        bw, bh = 195, 48
        draw.rounded_rectangle([bx, btn_y, bx + bw, btn_y + bh], radius=5, fill=ACCENT)
        tw = draw.textbbox((0, 0), label, font=f_btn)[2]
        draw.text((bx + (bw - tw) // 2, btn_y + 14), label, font=f_btn, fill=BLACK)

    out = io.BytesIO()
    base.save(out, format="JPEG", quality=95)
    out.seek(0)
    return out.read()

# ─── POSTER STYLE 2: DASHBOARD UI ────────────────────────────────────────────
def build_poster_ui(anime: dict, photo_bytes: bytes, brand: str, theme_name: str = "cyan") -> bytes:
    theme  = THEMES.get(theme_name, THEMES["cyan"])
    ACCENT = theme["accent"]
    BG     = theme["bg"]

    title    = anime.get("title_english") or anime.get("title", "UNKNOWN")
    genres   = [g["name"].upper() for g in anime.get("genres", [])][:4]
    synopsis = anime.get("synopsis") or "No synopsis available."
    score    = str(anime.get("score") or "N/A")
    episodes = str(anime.get("episodes") or "?")

    syn_clean = re.sub(r'\[.*?\]|\(.*?\)', '', synopsis).strip()

    # Clean title / season
    season_match = re.search(r'\b(season\s*\d+|\d+(?:st|nd|rd|th)\s*season)\b',
                             title, flags=re.IGNORECASE)
    season_text = None
    clean_title = title
    if season_match:
        num = re.search(r'\d+', season_match.group(0)).group(0)
        season_text = f"SEASON {num}"
        clean_title = re.sub(r'\s*\b(season\s*\d+|\d+(?:st|nd|rd|th)\s*season)\b',
                             '', title, flags=re.IGNORECASE).strip()

    base = Image.new("RGB", (W, H), BG)

    # blurred bg from photo
    char_img = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    char_img = char_img.resize((W, H), Image.LANCZOS)
    char_img = char_img.filter(ImageFilter.GaussianBlur(18))
    # dark tint overlay
    tint = Image.new("RGB", (W, H), BG)
    base = Image.blend(char_img, tint, 0.65)

    draw = ImageDraw.Draw(base)

    # ── sidebar ──
    sb_w = 90
    sidebar = Image.new("RGBA", (sb_w, H), (0, 0, 0, 160))
    base.paste(Image.new("RGB", (sb_w, H), (15, 20, 20)), (0, 0))
    draw = ImageDraw.Draw(base)

    # sidebar icons (text placeholders)
    f_icon = load_font(11, bold=True)
    for idx, (icon, label) in enumerate([("≡", brand[:4].upper()),
                                          ("⌂", "HOME"), ("🔍", "SEARCH"),
                                          ("☰", "CATEGORY"), ("★", "RATING")]):
        iy = 20 + idx * 100
        if idx == 0:
            draw.text((sb_w // 2, iy), icon, font=load_font(22, bold=True),
                      fill=WHITE, anchor="mm")
            draw.text((sb_w // 2, iy + 26), label, font=load_font(10, bold=True),
                      fill=WHITE, anchor="mm")
        else:
            col = ACCENT if idx == 1 else (150, 150, 150)
            draw.text((sb_w // 2, iy), icon, font=load_font(20, bold=True),
                      fill=col, anchor="mm")
            draw.text((sb_w // 2, iy + 22), label, font=load_font(9, bold=True),
                      fill=col, anchor="mm")

    # ── top genre pills ──
    gx, gy = sb_w + 30, 28
    f_genre = load_font(14, bold=True)
    for g in genres:
        tw = draw.textbbox((0, 0), g, font=f_genre)[2]
        pw = tw + 28
        draw.rounded_rectangle([gx, gy, gx + pw, gy + 36],
                                radius=18, fill=(255, 255, 255, 0),
                                outline=WHITE)
        # white pill bg semi
        pill = Image.new("RGBA", (pw, 36), (255, 255, 255, 30))
        base.paste(Image.new("RGB", (pw, 36), (200, 200, 210)),
                   (gx, gy), pill)
        draw = ImageDraw.Draw(base)
        draw.rounded_rectangle([gx, gy, gx + pw, gy + 36],
                                radius=18, outline=WHITE)
        draw.text((gx + pw // 2, gy + 18), g, font=f_genre,
                  fill=WHITE, anchor="mm")
        gx += pw + 14

    # ── main title card ──
    card1_x, card1_y = sb_w + 30, 80
    card1_w, card1_h = int(W * 0.47), 160
    _draw_card(base, card1_x, card1_y, card1_w, card1_h, ACCENT)
    draw = ImageDraw.Draw(base)

    f_big = load_font(90, bold=True)
    while f_big.size > 36:
        bbox = draw.textbbox((0, 0), clean_title.upper(), font=f_big)
        if (bbox[2] - bbox[0]) < card1_w - 20:
            break
        f_big = load_font(f_big.size - 6, bold=True)
    draw.text((card1_x + 20, card1_y + card1_h // 2),
              clean_title.upper(), font=f_big, fill=WHITE, anchor="lm")
    if season_text:
        draw.text((card1_x + 20, card1_y + card1_h // 2 + f_big.size // 2 + 6),
                  season_text, font=load_font(int(f_big.size * 0.4), bold=True),
                  fill=ACCENT)

    # ── info card ──
    card2_x, card2_y = sb_w + 30, card1_y + card1_h + 18
    card2_w, card2_h = card1_w, H - card2_y - 30
    _draw_card(base, card2_x, card2_y, card2_w, card2_h, ACCENT)
    draw = ImageDraw.Draw(base)

    f_info_h = load_font(16, bold=True)
    f_info   = load_font(15)
    draw.text((card2_x + 20, card2_y + 18), "INFORMATION",
              font=f_info_h, fill=WHITE)
    info_items = [
        f"STUDIO : Unknown",
        f"STATUS : TV ({episodes} EPS)",
        f"RATINGS : {score}",
    ]
    for ii, item in enumerate(info_items):
        draw.text((card2_x + 20, card2_y + 52 + ii * 36),
                  f"• {item}", font=f_info, fill=WHITE)

    # ── right side: featured image card ──
    rcard_x = sb_w + card1_w + 54
    rcard_w = W - rcard_x - 20
    rimg_h  = int(H * 0.42)

    feat_img = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    feat_img = feat_img.resize((rcard_w, rimg_h), Image.LANCZOS)
    mask = Image.new("L", (rcard_w, rimg_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, rcard_w, rimg_h], radius=14, fill=255)
    base.paste(feat_img, (rcard_x, 80), mask)
    draw = ImageDraw.Draw(base)
    draw.rounded_rectangle([rcard_x, 80, rcard_x + rcard_w, 80 + rimg_h],
                           radius=14, outline=ACCENT, width=2)

    # featured label
    draw.text((rcard_x, 80 + rimg_h + 14), "FEATURED",
              font=load_font(17, bold=True), fill=WHITE)
    feat_syn = textwrap.wrap(syn_clean, width=42)
    for ii, line in enumerate(feat_syn[:3]):
        draw.text((rcard_x, 80 + rimg_h + 38 + ii * 22),
                  line, font=load_font(13), fill=GRAY)

    # overview card
    ov_y = 80 + rimg_h + 38 + 3 * 22 + 18
    ov_h = H - ov_y - 20
    if ov_h > 60:
        _draw_card(base, rcard_x, ov_y, rcard_w, ov_h, ACCENT)
        draw = ImageDraw.Draw(base)
        draw.text((rcard_x + 14, ov_y + 12), "OVERVIEW",
                  font=load_font(15, bold=True), fill=WHITE)
        ov_words = textwrap.wrap(syn_clean[120:], width=38)
        for ii, line in enumerate(ov_words[:3]):
            draw.text((rcard_x + 14, ov_y + 36 + ii * 22),
                      line, font=load_font(12), fill=GRAY)

    out = io.BytesIO()
    base.save(out, format="JPEG", quality=95)
    out.seek(0)
    return out.read()

def _draw_card(img, x, y, w, h, accent):
    """Draw a semi-transparent frosted card."""
    from PIL import ImageFilter as _IF
    card = Image.new("RGBA", (w, h), (20, 30, 30, 180))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w, h], radius=14, fill=255)
    region = img.crop((x, y, x + w, y + h)).convert("RGBA")
    blended = Image.alpha_composite(region, card)
    img.paste(blended.convert("RGB"), (x, y), mask)
    ImageDraw.Draw(img).rounded_rectangle([x, y, x + w, y + h],
                                          radius=14, outline=accent, width=2)


def fetch_anime(name: str) -> list[dict]:
    try:
        query = """
        query ($search: String) {
          Page(perPage: 10) {
            media(search: $search, type: ANIME) {
              title { english romaji }
              genres averageScore episodes
              description(asHtml: false)
              startDate { year }
            }
          }
        }
        """
        r = requests.post("https://graphql.anilist.co",
                          json={"query": query, "variables": {"search": name}},
                          timeout=20)
        if r.status_code == 200:
            items = r.json()["data"]["Page"]["media"]
            results = []
            for item in items:
                results.append({
                    "title_english": item["title"].get("english") or item["title"].get("romaji"),
                    "title": item["title"].get("romaji") or item["title"].get("english"),
                    "genres": [{"name": g} for g in (item.get("genres") or [])],
                    "score": round((item.get("averageScore") or 0) / 10, 1) or "N/A",
                    "episodes": item.get("episodes") or "?",
                    "synopsis": item.get("description") or "No synopsis available.",
                    "year": (item.get("startDate") or {}).get("year"),
                })
            if results:
                return results
    except Exception:
        pass

    for attempt in range(3):
        try:
            r = requests.get(f"{JIKAN_API}/anime",
                             params={"q": name, "limit": 10}, timeout=30,
                             headers={"User-Agent": "AnimePosterBot/1.0"})
            if r.status_code in (429, 503, 504):
                time.sleep(4); continue
            if r.status_code == 200:
                data = r.json().get("data", [])
                if data: return data
        except Exception:
            time.sleep(3)
    return []

# ─── HANDLERS ─────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    first = update.effective_user.first_name
    welcome_text = (
        f"*ʜᴇʟʟᴏ, {first}*\n\n"
        ">ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴀɴɪᴍᴇғʟɪᴏ ᴘᴏsᴛᴇʀ ʙᴏᴛ\n\n"
        ">ɪ'ᴍ ʏᴏᴜʀ ᴀᴜᴛᴏ ᴛʜᴜᴍʙɴᴀɪʟ ᴍᴀᴋᴇʀ, ʀᴇᴀᴅʏ ᴛᴏ ᴄʀᴇᴀᴛᴇ sᴛᴜɴɴɪɴɢ ᴀɴɪᴍᴇ ᴅᴇsɪɢɴs ғᴏʀ ʏᴏᴜ\\."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("• ᴍʏ ᴀʟʟ ᴄᴏᴍᴍᴀɴᴅꜱ •", callback_data="show_commands")],
        [InlineKeyboardButton("• ᴅᴇᴠᴇʟᴏᴘᴇʀ", callback_data="developer"),
         InlineKeyboardButton("ᴄʟᴏꜱᴇ •", callback_data="cmd_cancel")],
    ])
    await update.message.reply_photo(
        photo="https://i.postimg.cc/RF6b28py/e25348fdc52abcafa9e951f6a3d1a51a.jpg",
        caption=welcome_text, parse_mode="MarkdownV2", reply_markup=keyboard
    )

async def show_commands_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("• ᴄʀᴇᴀᴛᴇ ᴘᴏꜱᴛᴇʀ •", callback_data="cmd_anime")],
        [InlineKeyboardButton("• ᴄʜᴀɴɢᴇ ʙʀᴀɴᴅ •", callback_data="cmd_brand")],
        [InlineKeyboardButton("ᴄʟᴏꜱᴇ", callback_data="cmd_cancel")],
    ])
    await query.edit_message_reply_markup(reply_markup=keyboard)

async def cmd_cancel_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.delete()

async def developer_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dev_text = (
        "*ᴅᴇᴠᴇʟᴏᴘᴇʀ ɪɴғᴏ\\.\\.\\.*\n\n"
        "» ᴄʀᴇᴀᴛᴏʀ: [WAVE](https://t.me/wave_189)\n"
        "» ʙᴏᴛ: [Aᴜɢᴜsᴛᴀ](https://t.me/Roxy_x_bot)\n"
        "» sᴜᴘᴘᴏʀᴛ: [Sᴜᴘᴘᴏʀᴛ ᴄʜᴀᴛ](https://t.me/wave_domain)"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("ʙᴀᴄᴋ", callback_data="back_start"),
         InlineKeyboardButton("ᴄʟᴏꜱᴇ", callback_data="cmd_cancel")],
    ])
    await query.edit_message_caption(caption=dev_text, parse_mode="MarkdownV2", reply_markup=keyboard)

async def back_start_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    first = update.effective_user.first_name
    welcome_text = (
        f"*ʜᴇʟʟᴏ, {first}*\n\n"
        ">ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴀɴɪᴍᴇғʟɪᴏ ᴘᴏsᴛᴇʀ ʙᴏᴛ\n\n"
        ">ɪ'ᴍ ʏᴏᴜʀ ᴀᴜᴛᴏ ᴛʜᴜᴍʙɴᴀɪʟ ᴍᴀᴋᴇʀ, ʀᴇᴀᴅʏ ᴛᴏ ᴄʀᴇᴀᴛᴇ sᴛᴜɴɴɪɴɢ ᴀɴɪᴍᴇ ᴅᴇsɪɢɴs ғᴏʀ ʏᴏᴜ\\."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("• ᴍʏ ᴀʟʟ ᴄᴏᴍᴍᴀɴᴅꜱ •", callback_data="show_commands")],
        [InlineKeyboardButton("• ᴅᴇᴠᴇʟᴏᴘᴇʀ", callback_data="developer"),
         InlineKeyboardButton("ᴄʟᴏꜱᴇ •", callback_data="cmd_cancel")],
    ])
    await query.edit_message_caption(caption=welcome_text, parse_mode="MarkdownV2", reply_markup=keyboard)

async def cmd_anime(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "🔍 Eɴᴛᴇʀ ᴛʜᴇ *ᴀɴɪᴍᴇ ɴᴀᴍᴇ* ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ ᴘᴏsᴛᴇʀ ғᴏʀ:",
        parse_mode="Markdown"
    )
    return ASK_ANIME

async def cmd_anime_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    ctx.user_data.clear()
    await update.callback_query.message.reply_text(
        "🔍 Eɴᴛᴇʀ ᴛʜᴇ *ᴀɴɪᴍᴇ ɴᴀᴍᴇ* ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ ᴘᴏsᴛᴇʀ ғᴏʀ:",
        parse_mode="Markdown"
    )
    return ASK_ANIME

async def received_anime_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    await update.message.reply_text(f"⏳ Searching for *{name}*...", parse_mode="Markdown")
    try:
        results = fetch_anime(name)
    except Exception:
        await update.message.reply_text("⏳ API is slow. Please wait and try /anime again.")
        return ConversationHandler.END

    if not results:
        await update.message.reply_text("❌ No anime found. Try a different name.")
        return ASK_ANIME

    ctx.user_data["results"] = results
    buttons = [
        [InlineKeyboardButton(
            f"{a.get('title_english') or a['title']} ({a.get('year') or '?'})",
            callback_data=str(i)
        )]
        for i, a in enumerate(results[:10])
    ]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel")])
    await update.message.reply_text("📋 Select the correct anime:",
                                    reply_markup=InlineKeyboardMarkup(buttons))
    return ASK_CONFIRM

async def anime_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel":
        await query.edit_message_text("❌ Cancelled.")
        return ConversationHandler.END

    anime = ctx.user_data["results"][int(query.data)]
    ctx.user_data["anime"] = anime
    title  = anime.get("title_english") or anime["title"]
    genres = ", ".join(g["name"] for g in anime.get("genres", [])[:3]) or "N/A"

    await query.edit_message_text(
        f"✅ *{title}*\n🎭 Genres: {genres}\n\n"
        f"📸 Now send the *background / character image* for the poster:",
        parse_mode="Markdown"
    )
    return ASK_PHOTO

async def received_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1] if update.message.photo else None
    doc   = update.message.document
    if not photo and not doc:
        await update.message.reply_text("⚠️ Please send a photo or image file.")
        return ASK_PHOTO

    file        = await ctx.bot.get_file(photo.file_id if photo else doc.file_id)
    photo_bytes = await file.download_as_bytearray()
    ctx.user_data["photo_bytes"] = bytes(photo_bytes)

    # Ask poster style
    buttons = [
        [InlineKeyboardButton("🎴 Style 1 — Classic Hex", callback_data="style_classic")],
        [InlineKeyboardButton("🖥️ Style 2 — Dashboard UI", callback_data="style_ui")],
    ]
    await update.message.reply_text(
        "🖼️ Choose your *poster style*:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ASK_STYLE

async def style_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["style"] = query.data.replace("style_", "")

    # Ask color
    buttons = [
        [
            InlineKeyboardButton(f"{THEMES[c]['emoji']} {c.capitalize()}", callback_data=f"color_{c}")
            for c in list(THEMES.keys())[i:i+2]
        ]
        for i in range(0, len(THEMES), 2)
    ]
    await query.edit_message_text(
        "🎨 Choose your *poster color theme*:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ASK_COLOR

async def color_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    theme_name = query.data.replace("color_", "")
    style      = ctx.user_data.get("style", "classic")
    await query.edit_message_text(
        f"🎨 Creating your *{theme_name}* poster, please wait...",
        parse_mode="Markdown"
    )
    try:
        anime       = ctx.user_data["anime"]
        photo_bytes = ctx.user_data["photo_bytes"]
        brand       = ctx.user_data.get("brand", BRAND_NAME)

        if style == "ui":
            poster_bytes = build_poster_ui(anime, photo_bytes, brand, theme_name)
        else:
            poster_bytes = build_poster(anime, photo_bytes, brand, theme_name)

        title = anime.get("title_english") or anime["title"]
        await query.message.reply_photo(
            photo=io.BytesIO(poster_bytes),
            caption=f"🎌 *{title}* — {THEMES[theme_name]['emoji']} {theme_name.capitalize()} poster ready!\n\nSend /anime to make another.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await query.message.reply_text(f"❌ Failed to create poster: {e}")
    return ConversationHandler.END

async def cmd_brand(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    current = ctx.user_data.get("brand", BRAND_NAME)
    await update.message.reply_text(
        f"🏷️ Current brand: *{current}*\n\nSend the new brand name:",
        parse_mode="Markdown"
    )
    return ASK_BRAND

async def cmd_brand_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    current = ctx.user_data.get("brand", BRAND_NAME)
    await update.callback_query.message.reply_text(
        f"🏷️ Current brand: *{current}*\n\nSend the new brand name:",
        parse_mode="Markdown"
    )
    return ASK_BRAND

async def received_brand(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["brand"] = update.message.text.strip().upper()
    await update.message.reply_text(
        f"✅ Brand set to: *{ctx.user_data['brand']}*", parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    anime_conv = ConversationHandler(
        entry_points=[
            CommandHandler("anime", cmd_anime),
            CallbackQueryHandler(cmd_anime_callback, pattern="^cmd_anime$"),
        ],
        states={
            ASK_ANIME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, received_anime_name)],
            ASK_CONFIRM: [CallbackQueryHandler(anime_selected)],
            ASK_PHOTO:   [MessageHandler(filters.PHOTO | filters.Document.IMAGE, received_photo)],
            ASK_STYLE:   [CallbackQueryHandler(style_selected, pattern="^style_")],
            ASK_COLOR:   [CallbackQueryHandler(color_selected, pattern="^color_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        per_chat=True,
    )

    brand_conv = ConversationHandler(
        entry_points=[
            CommandHandler("brand", cmd_brand),
            CallbackQueryHandler(cmd_brand_callback, pattern="^cmd_brand$"),
        ],
        states={
            ASK_BRAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_brand)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(anime_conv)
    app.add_handler(brand_conv)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(show_commands_callback, pattern="^show_commands$"))
    app.add_handler(CallbackQueryHandler(cmd_cancel_callback,    pattern="^cmd_cancel$"))
    app.add_handler(CallbackQueryHandler(developer_callback,     pattern="^developer$"))
    app.add_handler(CallbackQueryHandler(back_start_callback,    pattern="^back_start$"))

    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
