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
BOT_TOKEN  = "8620146968:AAFxWlpBGb0BS8ODMUrB_IOwbtoWR2-7mpA"
BRAND_NAME = "ANIMEFLIO"
JIKAN_API  = "https://api.jikan.moe/v4"

ASK_ANIME, ASK_CONFIRM, ASK_PHOTO, ASK_BRAND, ASK_COLOR = range(5)

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

from PIL import ImageFilter as _ImageFilter

# ─── POSTER BUILDER ───────────────────────────────────────────────────────────
def build_poster(anime: dict, photo_bytes: bytes, brand: str, theme_name: str = "cyan") -> bytes:
    from PIL import ImageFilter
    theme  = THEMES.get(theme_name, THEMES["cyan"])
    ACCENT = theme["accent"]
    BG     = theme["bg"]

    title    = anime.get("title_english") or anime.get("title", "UNKNOWN")
    genres   = [g["name"] for g in anime.get("genres", [])][:4]
    synopsis = anime.get("synopsis") or "No synopsis available."
    score    = anime.get("score") or "N/A"
    episodes = str(anime.get("episodes") or "?")
    year     = str(anime.get("year") or "N/A")

    syn_clean = re.sub(r'<[^>]+>', '', synopsis)
    syn_clean = re.sub(r'\[.*?\]|\(.*?\)', '', syn_clean).strip()

    # Season detection
    season_match = re.search(r'\b(season\s*\d+|\d+(?:st|nd|rd|th)\s*season)\b',
                             title, flags=re.IGNORECASE)
    season_text = None
    clean_title = title
    if season_match:
        num = re.search(r'\d+', season_match.group(0)).group(0)
        season_text = f"SEASON {num}"
        clean_title = re.sub(r'\s*\b(season\s*\d+|\d+(?:st|nd|rd|th)\s*season)\b',
                             '', title, flags=re.IGNORECASE).strip()

    # ── LAYER 1: Heavy blurred background ──
    bg_src = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    bg_src = bg_src.resize((W, H), Image.LANCZOS)
    bg_blurred = bg_src.filter(ImageFilter.GaussianBlur(32))

    # ── LAYER 2: Dark gradient overlay ──
    dark_overlay = Image.new("RGB", (W, H), (8, 9, 14))
    base = Image.blend(bg_blurred, dark_overlay, 0.78)

    # ── LAYER 3: Vignette (darker edges) ──
    vignette = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    for i in range(120):
        alpha = int(160 * (i / 120) ** 2)
        vd.rectangle([i, i, W - i, H - i], outline=(0, 0, 0, 255 - alpha))
    base = Image.alpha_composite(base.convert("RGBA"), vignette).convert("RGB")

    draw = ImageDraw.Draw(base)

    # ── SPACING SYSTEM (8px base) ──
    LEFT = 72       # left margin
    TOP  = 48       # top margin

    # ── BRAND BADGE ──
    badge_text = f"◆  {brand.upper()}"
    f_badge = load_font(13, bold=True)
    btw = draw.textbbox((0, 0), badge_text, font=f_badge)[2]
    bh = 36
    bx1, by1 = LEFT, TOP
    bx2, by2 = bx1 + btw + 32, by1 + bh
    # Badge outline pill
    draw.rounded_rectangle([bx1, by1, bx2, by2], radius=18, outline=ACCENT, width=2)
    draw.text((bx1 + 16, by1 + bh // 2), badge_text, font=f_badge, fill=WHITE, anchor="lm")

    # ── TITLE (large, word-wrapped, cinematic) ──
    title_upper = clean_title.upper()
    ty = by2 + 32  # Badge → Title = 32px

    f_title = load_font(108, bold=True)
    max_title_w = int(W * 0.52)
    while f_title.size > 32:
        bbox = draw.textbbox((0, 0), title_upper, font=f_title)
        if (bbox[2] - bbox[0]) <= max_title_w:
            break
        f_title = load_font(f_title.size - 4, bold=True)

    # Word wrap into lines
    words = title_upper.split()
    lines = []
    current = []
    for word in words:
        test = " ".join(current + [word])
        if draw.textbbox((0, 0), test, font=f_title)[2] <= max_title_w:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))

    line_h = int(f_title.size * 1.15)

    # Draw title with white glow effect
    glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    glow_ty = ty
    for line in lines[:3]:
        gd.text((LEFT, glow_ty), line, font=f_title, fill=(255, 255, 255, 90))
        glow_ty += line_h
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(7))
    base = Image.alpha_composite(base.convert("RGBA"), glow_layer).convert("RGB")
    draw = ImageDraw.Draw(base)

    for line in lines[:3]:
        draw.text((LEFT, ty), line, font=f_title, fill=WHITE)
        ty += line_h

    if season_text:
        f_s = load_font(int(f_title.size * 0.42), bold=True)
        draw.text((LEFT, ty + 4), season_text, font=f_s, fill=ACCENT)
        ty += int(f_s.size * 1.4) + 4

    title_bottom = ty

    # ── GENRE PILLS ── (Title → Genres = 24px)
    gy = title_bottom + 24
    gx = LEFT
    f_genre = load_font(12, bold=True)
    pill_h = 32
    for g in genres:
        gtw = draw.textbbox((0, 0), g.upper(), font=f_genre)[2]
        pw = gtw + 22
        # Very subtle fill
        pill_bg = Image.new("RGBA", (pw, pill_h), (0, 0, 0, 0))
        pmask = Image.new("L", (pw, pill_h), 0)
        ImageDraw.Draw(pmask).rounded_rectangle([0, 0, pw, pill_h], radius=16, fill=255)
        pill_color = tuple(max(0, c - 200) for c in ACCENT) + (80,)
        ImageDraw.Draw(pill_bg).rounded_rectangle([0, 0, pw, pill_h], radius=16, fill=pill_color[:3])
        base.paste(pill_bg.convert("RGB"), (gx, gy), pmask)
        draw = ImageDraw.Draw(base)
        draw.rounded_rectangle([gx, gy, gx + pw, gy + pill_h], radius=16, outline=ACCENT, width=1)
        draw.text((gx + pw // 2, gy + pill_h // 2), g.upper(), font=f_genre, fill=WHITE, anchor="mm")
        gx += pw + 10

    # ── GLASSMORPHISM DESCRIPTION CARD ──
    card_x = LEFT
    card_y = gy + pill_h + 30
    card_w = int(W * 0.54)
    card_h = 148

    # Step 1: Blur the background behind the card
    region = base.crop((card_x, card_y, card_x + card_w, card_y + card_h))
    blurred_r = region.filter(ImageFilter.GaussianBlur(16))

    # Step 2: Rounded mask
    cmask = Image.new("L", (card_w, card_h), 0)
    ImageDraw.Draw(cmask).rounded_rectangle([0, 0, card_w, card_h], radius=16, fill=255)

    # Step 3: Paste blurred region
    base.paste(blurred_r, (card_x, card_y), cmask)

    # Step 4: Dark accent-tinted overlay
    tint_r = max(0, min(255, ACCENT[0] // 6))
    tint_g = max(0, min(255, ACCENT[1] // 6))
    tint_b = max(0, min(255, ACCENT[2] // 6))
    tint_layer = Image.new("RGB", (card_w, card_h), (tint_r, tint_g, tint_b))
    tint_alpha = Image.new("L", (card_w, card_h), 120)
    base.paste(tint_layer, (card_x, card_y),
               Image.composite(tint_alpha, Image.new("L", (card_w, card_h), 0), cmask))

    draw = ImageDraw.Draw(base)
    # Thin accent-colored border
    draw.rounded_rectangle([card_x, card_y, card_x + card_w, card_y + card_h],
                           radius=16, outline=ACCENT, width=1)

    # Step 5: Bright accent-tinted synopsis text
    f_syn = load_font(14)
    wrapped = textwrap.wrap(syn_clean, width=66)
    sy = card_y + 20
    text_color = tuple(min(255, 180 + c // 4) for c in ACCENT)
    for line in wrapped[:5]:
        draw.text((card_x + 20, sy), line, font=f_syn, fill=text_color)
        sy += 22
    if len(wrapped) > 5:
        draw.text((card_x + 20, sy), "...read more", font=f_syn, fill=ACCENT)


    # ── METADATA ROW ── (Description → Metadata = 48px)
    meta_y = H - 72
    meta_items = [
        ("STUDIO", "Unknown"),
        ("EPISODES/RUNTIME", episodes),
        ("RELEASED", year),
        ("FORMAT", "TV"),
        ("SCORE", f"{score}%"),
    ]
    col_w_m = card_w // len(meta_items)
    f_mlabel = load_font(10, bold=True)
    f_mval   = load_font(17, bold=True)
    for idx, (label, val) in enumerate(meta_items):
        mx = card_x + idx * col_w_m
        draw.text((mx, meta_y), label, font=f_mlabel, fill=(110, 110, 120))
        val_color = ACCENT if label == "SCORE" else WHITE
        draw.text((mx, meta_y + 16), val, font=f_mval, fill=val_color)

    # ── RIGHT SIDE: VERTICAL PORTRAIT POSTER ──
    poster_x = int(W * 0.615)
    poster_y = 40
    poster_w = int(W * 0.285)   # slightly smaller (~10% less)
    poster_h = H - 90

    # Crop image to portrait ratio
    p_img = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    target_ratio = poster_w / poster_h
    img_ratio = p_img.width / p_img.height
    if img_ratio > target_ratio:
        nw = int(p_img.height * target_ratio)
        left = (p_img.width - nw) // 2
        p_img = p_img.crop((left, 0, left + nw, p_img.height))
    else:
        nh = int(p_img.width / target_ratio)
        top = (p_img.height - nh) // 2
        p_img = p_img.crop((0, top, p_img.width, top + nh))
    p_img = p_img.resize((poster_w, poster_h), Image.LANCZOS)

    # Rounded mask
    pmask2 = Image.new("L", (poster_w, poster_h), 0)
    ImageDraw.Draw(pmask2).rounded_rectangle([0, 0, poster_w, poster_h], radius=20, fill=255)

    # Soft drop shadow
    shadow_size = 20
    shadow = Image.new("RGBA", (poster_w + shadow_size*2, poster_h + shadow_size*2), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [shadow_size, shadow_size, poster_w + shadow_size, poster_h + shadow_size],
        radius=22, fill=(0, 0, 0, 100)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    shadow_arr = shadow.split()[3]
    base.paste(Image.new("RGB", shadow.size, (0,0,0)),
               (poster_x - shadow_size, poster_y - shadow_size), shadow_arr)

    # Paste poster
    base.paste(p_img, (poster_x, poster_y), pmask2)
    draw = ImageDraw.Draw(base)

    # Thin elegant border (1px, low opacity simulation)
    draw.rounded_rectangle([poster_x, poster_y, poster_x + poster_w, poster_y + poster_h],
                           radius=20, outline=(180, 180, 195), width=1)

    # ── DECORATIVE CORNER BRACKETS (larger, farther out) ──
    offset = 18   # distance from poster edge
    cl = 36       # bracket arm length
    cw = 2
    ax = ACCENT

    # Top-left bracket
    tlx, tly = poster_x - offset, poster_y - offset
    draw.line([(tlx, tly), (tlx + cl, tly)], fill=ax, width=cw)
    draw.line([(tlx, tly), (tlx, tly + cl)], fill=ax, width=cw)

    # Top-right bracket
    trx, try_ = poster_x + poster_w + offset, poster_y - offset
    draw.line([(trx - cl, try_), (trx, try_)], fill=ax, width=cw)
    draw.line([(trx, try_), (trx, try_ + cl)], fill=ax, width=cw)

    # Bottom-left bracket
    blx, bly = poster_x - offset, poster_y + poster_h + offset
    draw.line([(blx, bly - cl), (blx, bly)], fill=ax, width=cw)
    draw.line([(blx, bly), (blx + cl, bly)], fill=ax, width=cw)

    # Bottom-right bracket
    brx, bry = poster_x + poster_w + offset, poster_y + poster_h + offset
    draw.line([(brx, bry - cl), (brx, bry)], fill=ax, width=cw)
    draw.line([(brx - cl, bry), (brx, bry)], fill=ax, width=cw)

    out = io.BytesIO()
    base.save(out, format="JPEG", quality=95)
    out.seek(0)
    return out.read()

# ─── ANIME FETCH ──────────────────────────────────────────────────────────────
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

    # Ask color
    buttons = [
        [
            InlineKeyboardButton(f"{THEMES[c]['emoji']} {c.capitalize()}", callback_data=f"color_{c}")
            for c in list(THEMES.keys())[i:i+2]
        ]
        for i in range(0, len(THEMES), 2)
    ]
    await update.message.reply_text(
        "🎨 Choose your *poster color theme*:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ASK_COLOR

async def color_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    theme_name = query.data.replace("color_", "")
    await query.edit_message_text(f"🎨 Creating your *{theme_name}* poster, please wait...",
                                  parse_mode="Markdown")
    try:
        anime        = ctx.user_data["anime"]
        photo_bytes  = ctx.user_data["photo_bytes"]
        brand        = ctx.user_data.get("brand", BRAND_NAME)
        poster_bytes = build_poster(anime, photo_bytes, brand, theme_name)
        title        = anime.get("title_english") or anime["title"]

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
