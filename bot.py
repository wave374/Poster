import os
import io
import time
import threading
import re
import math
import textwrap
import requests
from PIL import Image, ImageDraw, ImageFont
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
BOT_TOKEN  = "8620146968:AAF3VOvjFFqgWCWIYS5Od_keB3BMZbJbk_w"
BRAND_NAME = "ANIMEFLIO"
JIKAN_API  = "https://api.jikan.moe/v4"

# Conversation states
ASK_ANIME, ASK_CONFIRM, ASK_COLOR, ASK_PHOTO, ASK_BRAND = range(5)

# ─── COLORS ───────────────────────────────────────────────────────────────────
BG_DARK = (13, 26, 13)
GREEN   = (34, 197, 94)
GOLD    = (212, 168, 85)
WHITE   = (255, 255, 255)
GRAY    = (180, 180, 180)
BLACK   = (0, 0, 0)

# ─── THEMES ───────────────────────────────────────────────────────────────────
THEMES = {
    "color_green":  {"bg": (13, 26, 13),  "accent": (34, 197, 94),  "hex_fill": (13, 22, 13),  "overlay": (10, 20, 10)},
    "color_cyan":   {"bg": (10, 22, 26),  "accent": (0, 210, 255),  "hex_fill": (10, 18, 22),  "overlay": (8, 16, 20)},
    "color_red":    {"bg": (26, 10, 10),  "accent": (255, 60, 60),  "hex_fill": (22, 8, 8),    "overlay": (20, 8, 8)},
    "color_orange": {"bg": (26, 18, 8),   "accent": (255, 140, 0),  "hex_fill": (22, 14, 6),   "overlay": (20, 12, 5)},
}

W, H = 1280, 720  # 16:9

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
def draw_hex_grid(draw, width, height):
    hex_size = 55
    hex_w = hex_size * 2
    hex_h = math.sqrt(3) * hex_size
    col_w = hex_w * 0.75
    cols = int(width / col_w) + 2
    rows = int(height / hex_h) + 2
    for col in range(cols):
        for row in range(rows):
            cx = col * col_w - hex_size
            cy = row * hex_h + (hex_h / 2 if col % 2 else 0) - hex_h / 2
            points = [
                (cx + hex_size * math.cos(math.radians(60 * i)),
                 cy + hex_size * math.sin(math.radians(60 * i)))
                for i in range(6)
            ]
            draw.polygon(points, outline=(30, 55, 30), fill=(13, 22, 13))

# ─── GRADIENT OVERLAY ─────────────────────────────────────────────────────────
def apply_left_gradient(img):
    grad = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(grad)
    fade_w = int(W * 0.62)
    for x in range(fade_w):
        alpha = int(255 * (1 - x / fade_w) ** 1.4)
        draw.line([(x, 0), (x, H)], fill=(13, 26, 13, alpha))
    img = img.convert("RGBA")
    img.alpha_composite(grad)
    return img.convert("RGB")

# ─── POSTER BUILDER ───────────────────────────────────────────────────────────
def flat_hex_pts(cx, cy, size):
    """Flat-top hexagon points."""
    return [
        (cx + size * math.cos(math.radians(60 * i)),
         cy + size * math.sin(math.radians(60 * i)))
        for i in range(6)
    ]

def build_poster(anime: dict, photo_bytes: bytes, brand: str, color: str = "color_green") -> bytes:
    title    = anime.get("title_english") or anime.get("title", "UNKNOWN")
    genres   = [g["name"].upper() for g in anime.get("genres", [])][:5]
    synopsis = anime.get("synopsis") or "No synopsis available."

    theme  = THEMES.get(color, THEMES["color_green"])
    bg     = theme["bg"]
    accent = theme["accent"]
    hfill  = theme["hex_fill"]

    # ── Canvas ──
    base = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(base)

    # ── STEP 1: Background hex grid (flat-top, dark, full canvas) ──
    HS = 70  # hex radius
    HW = HS * 2
    HH = math.sqrt(3) * HS
    COL_W = HW * 0.75

    cols = int(W / COL_W) + 3
    rows = int(H / HH) + 3
    for col in range(-1, cols):
        for row in range(-1, rows):
            cx = col * COL_W
            cy = row * HH + (HH / 2 if col % 2 else 0)
            pts = flat_hex_pts(cx, cy, HS - 3)
            # Very dark fill, subtle accent border
            draw.polygon(pts, fill=hfill, outline=(*accent, 40))

    # ── STEP 2: Load & scale character image to full poster height ──
    char_img = Image.open(io.BytesIO(photo_bytes)).convert("RGBA")
    scale = H / char_img.height
    new_w = int(char_img.width * scale)
    char_img = char_img.resize((new_w, H), Image.LANCZOS)
    # Center horizontally if wider than poster
    if new_w > W:
        char_img = char_img.crop(((new_w - W) // 2, 0, (new_w - W) // 2 + W, H))
        char_x = 0
    else:
        char_x = W - new_w  # align to right

    # ── STEP 3: Large hex mosaic on RIGHT side — clip image into hex cells ──
    MHS = 110  # large mosaic hex radius
    MHH = math.sqrt(3) * MHS
    MCOLW = MHS * 2 * 0.75

    # Mosaic covers right ~65% of poster, with some overlap left
    start_col_x = int(W * 0.33)

    m_cols = int((W - start_col_x) / MCOLW) + 3
    m_rows = int(H / MHH) + 3

    base_rgba = base.convert("RGBA")

    for col in range(-1, m_cols + 1):
        for row in range(-1, m_rows + 1):
            cx = start_col_x + col * MCOLW
            cy = row * MHH + (MHH / 2 if col % 2 else 0)

            # Skip hexes completely outside canvas
            if cx + MHS < 0 or cx - MHS > W:
                continue
            if cy + MHS < 0 or cy - MHS > H:
                continue

            pts = flat_hex_pts(cx, cy, MHS - 5)

            # Create hex mask
            mask = Image.new("L", (W, H), 0)
            ImageDraw.Draw(mask).polygon(pts, fill=255)

            # Check if this hex overlaps the character image area
            hex_left = cx - MHS
            if hex_left > char_x - MHS:
                # Paste char image into this hex cell
                char_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                char_layer.paste(char_img, (char_x, 0), char_img)

                # Apply hex mask to char layer
                r2, g2, b2, a2 = char_layer.split()
                a2 = Image.composite(a2, Image.new("L", (W, H), 0), mask)
                char_layer = Image.merge("RGBA", (r2, g2, b2, a2))
                base_rgba = Image.alpha_composite(base_rgba, char_layer)
            else:
                # Left hexes: fill with very dark color for 3D depth effect
                dark_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                dark_fill = (max(0, hfill[0] - 5), max(0, hfill[1] - 5), max(0, hfill[2] - 5), 200)
                ImageDraw.Draw(dark_layer).polygon(pts, fill=dark_fill)
                base_rgba = Image.alpha_composite(base_rgba, dark_layer)

            # Draw accent hex border (glowing edge effect)
            border_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            bd = ImageDraw.Draw(border_layer)
            # Outer glow
            bd.polygon(flat_hex_pts(cx, cy, MHS - 2), outline=(*accent, 120))
            bd.polygon(flat_hex_pts(cx, cy, MHS - 4), outline=(*accent, 200))
            bd.polygon(pts, outline=(*accent, 255))
            base_rgba = Image.alpha_composite(base_rgba, border_layer)

    base = base_rgba.convert("RGB")
    draw = ImageDraw.Draw(base)

    # ── STEP 4: Left gradient — make text area readable ──
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    fade_w = int(W * 0.55)
    for x in range(fade_w):
        t = 1 - x / fade_w
        alpha = int(230 * (t ** 1.1))
        gd.line([(x, 0), (x, H)], fill=(*bg, alpha))
    base = Image.alpha_composite(base.convert("RGBA"), grad).convert("RGB")
    draw = ImageDraw.Draw(base)

    # ── STEP 5: Brand logo top-left ──
    logo_cx, logo_cy, logo_r = 32, 32, 22
    logo_pts = flat_hex_pts(logo_cx, logo_cy, logo_r)
    draw.polygon(logo_pts, fill=bg, outline=accent)
    draw.text((logo_cx, logo_cy), "A", font=load_font(18, bold=True), fill=accent, anchor="mm")
    draw.text((64, 20), brand.upper(), font=load_font(17, bold=True), fill=WHITE)

    # ── STEP 6: Title ──
    title_upper = title.upper()
    import re as _re
    season_match = _re.search(r'season\s*(\d+)', title_upper, flags=_re.IGNORECASE)
    if not season_match:
        season_match = _re.search(r'\s+(\d+)$', title_upper)
    season_text = None
    if season_match:
        season_num = season_match.group(1)
        season_text = f"SEASON {season_num}"
        title_upper = _re.sub(r'\s*season\s*\d+|\s*\b' + season_num + r'\b', '', title_upper, flags=_re.IGNORECASE).strip()

    # Split long title into two lines if needed
    f_title = load_font(90, bold=True)
    max_title_w = int(W * 0.44)
    while f_title.size > 36:
        bbox = draw.textbbox((0, 0), title_upper, font=f_title)
        if (bbox[2] - bbox[0]) <= max_title_w:
            break
        f_title = load_font(f_title.size - 4, bold=True)

    # Check if title needs word wrap (like "REINCARNATED / AS A SLIME")
    words = title_upper.split()
    line1, line2 = title_upper, ""
    for i in range(1, len(words)):
        candidate = " ".join(words[:i])
        rest = " ".join(words[i:])
        b1 = draw.textbbox((0, 0), candidate, font=f_title)
        b2 = draw.textbbox((0, 0), rest, font=f_title)
        if (b1[2] - b1[0]) <= max_title_w and (b2[2] - b2[0]) <= max_title_w:
            line1 = candidate
            line2 = rest
            break

    ty = int(H * 0.28)
    draw.text((38, ty), line1, font=f_title, fill=WHITE)
    title_bottom = draw.textbbox((38, ty), line1, font=f_title)[3]
    if line2:
        draw.text((38, title_bottom + 2), line2, font=f_title, fill=accent)
        title_bottom = draw.textbbox((38, title_bottom + 2), line2, font=f_title)[3]

    # Season
    if season_text:
        f_season = load_font(int(f_title.size * 0.55), bold=True)
        draw.text((38, title_bottom + 4), season_text, font=f_season, fill=accent)
        title_bottom = draw.textbbox((38, title_bottom + 4), season_text, font=f_season)[3]

    # ── STEP 7: Genre tags ──
    gy = title_bottom + 14
    gx = 38
    f_genre = load_font(14, bold=True)
    genre_colors = [GOLD, accent, WHITE, (255, 100, 100), (100, 220, 180)]
    for idx, g in enumerate(genres):
        draw.text((gx, gy), g, font=f_genre, fill=genre_colors[idx % len(genre_colors)])
        gx += draw.textbbox((0, 0), g, font=f_genre)[2] + 22

    # ── STEP 8: Synopsis ──
    f_syn = load_font(13)
    syn_clean = re.sub(r'<[^>]+>', '', synopsis)
    syn_clean = re.sub(r'\[.*?\]|\(.*?\)', '', syn_clean).strip()
    wrapped = textwrap.wrap(syn_clean, width=52)
    sy = gy + 30
    max_lines = 7
    for line in wrapped[:max_lines]:
        draw.text((38, sy), line, font=f_syn, fill=GRAY)
        sy += 20
    if len(wrapped) > max_lines:
        draw.text((38, sy), "...read more", font=f_syn, fill=accent)
        sy += 20

    # ── STEP 9: CTA Buttons with 3D bevel look ──
    btn_y = sy + 14
    f_btn = load_font(14, bold=True)
    for i, label in enumerate(["DOWNLOAD", "JOIN NOW"]):
        bx = 38 + i * 205
        bw, bh = 188, 44
        # Dark shadow
        draw.rounded_rectangle([bx + 3, btn_y + 3, bx + bw + 3, btn_y + bh + 3],
                                radius=3, fill=(0, 0, 0, 120))
        # Main button
        draw.rounded_rectangle([bx, btn_y, bx + bw, btn_y + bh], radius=3, fill=accent)
        # Top highlight (3D effect)
        draw.rounded_rectangle([bx, btn_y, bx + bw, btn_y + 4], radius=3,
                                fill=tuple(min(255, c + 60) for c in accent))
        tw = draw.textbbox((0, 0), label, font=f_btn)[2]
        draw.text((bx + (bw - tw) // 2, btn_y + 13), label, font=f_btn, fill=BLACK)

    out = io.BytesIO()
    base.save(out, format="JPEG", quality=95)
    out.seek(0)
    return out.read()

# ─── JIKAN FETCH WITH RETRY + FALLBACK ───────────────────────────────────────
# ─── ANILIST FETCH WITH JIKAN FALLBACK ───────────────────────────────────────
def fetch_anime(name: str) -> list[dict]:
    # Try AniList first
    try:
        query = """
        query ($search: String) {
          Page(perPage: 10) {
            media(search: $search, type: ANIME) {
              title { english romaji }
              genres
              averageScore
              episodes
              description(asHtml: false)
              startDate { year }
            }
          }
        }
        """
        r = requests.post(
            "https://graphql.anilist.co",
            json={"query": query, "variables": {"search": name}},
            timeout=20
        )
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

    # Fallback: Jikan API
    for attempt in range(3):
        try:
            r = requests.get(
                f"{JIKAN_API}/anime",
                params={"q": name, "limit": 10},
                timeout=30,
                headers={"User-Agent": "AnimePosterBot/1.0"}
            )
            if r.status_code in (429, 503, 504):
                time.sleep(4)
                continue
            if r.status_code == 200:
                data = r.json().get("data", [])
                if data:
                    return data
        except Exception:
            time.sleep(3)

    return []
# ─── BOT HANDLERS ─────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    first = update.effective_user.first_name
    welcome_text = (
        f"*ʜᴇʟʟᴏ, {first}*\n\n"
        ">ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴀɴɪᴍᴇғʟɪᴏ ᴘᴏsᴛᴇʀ ʙᴏᴛ\n\n"
        ">ɪ'ᴍ ʏᴏᴜʀ ᴀᴜᴛᴏ ᴛʜᴜᴍʙɴᴀɪʟ ᴍᴀᴋᴇʀ, ʀᴇᴀᴅʏ ᴛᴏ ᴄʀᴇᴀᴛᴇ sᴛᴜɴɴɪɴɢ ᴀɴɪᴍᴇ ᴅᴇsɪɢɴs ғᴏʀ ʏᴏᴜ\\."
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("• ᴍʏ ᴀʟʟ ᴄᴏᴍᴍᴀɴᴅꜱ •", callback_data="show_commands")],
        [InlineKeyboardButton("• ᴅᴇᴠᴇʟᴏᴘᴇʀ", callback_data="developer"), InlineKeyboardButton("ᴄʟᴏꜱᴇ •", callback_data="cmd_cancel")],
    ])
    await update.message.reply_photo(
        photo="https://i.postimg.cc/RF6b28py/e25348fdc52abcafa9e951f6a3d1a51a.jpg",
        caption=welcome_text,
        parse_mode="MarkdownV2",
        reply_markup=keyboard
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
    
async def cmd_anime_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    await query.message.reply_text("🔍 Eɴᴛᴇʀ ᴛʜᴇ *ᴀɴɪᴍᴇ ɴᴀᴍᴇ* ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ ᴘᴏsᴛᴇʀ ғᴏʀ", parse_mode="Markdown")
    return ASK_ANIME

async def cmd_brand_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    current = ctx.user_data.get("brand", BRAND_NAME)
    await query.message.reply_text(f"🏷️ Cᴜʀʀᴇɴᴛ ʙʀᴀɴᴅ: *{current}*\n\nSᴇɴᴅ ᴛʜᴇ ɴᴇᴡ ʙʀᴀɴᴅ ɴᴀᴍᴇ:", parse_mode="Markdown")
    return ASK_BRAND
    
async def cmd_cancel_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.delete()
    
async def developer_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    dev_text = (
        "*ᴅᴇᴠᴇʟᴏᴘᴇʀ ɪɴғᴏ...*\n\n"
        "**» ᴄʀᴇᴀᴛᴏʀ: [WAVE](https://t.me/wave_189)\n"
        "» ʙᴏᴛ: [Aᴜɢᴜsᴛᴀ](https://t.me/Roxy_x_bot)\n"
        "» sᴜᴘᴘᴏʀᴛ: [Sᴜᴘᴘᴏʀᴛ ᴄʜᴀᴛ](https://t.me/wave_domain)**"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("ʙᴀᴄᴋ", callback_data="back_start"), InlineKeyboardButton("ᴄʟᴏꜱᴇ", callback_data="cmd_cancel")],
    ])
    await query.edit_message_caption(caption=dev_text, parse_mode="Markdown", reply_markup=keyboard)

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
        [InlineKeyboardButton("• ᴅᴇᴠᴇʟᴏᴘᴇʀ", callback_data="developer"), InlineKeyboardButton("ᴄʟᴏꜱᴇ •", callback_data="cmd_cancel")],
    ])
    await query.edit_message_caption(caption=welcome_text, parse_mode="MarkdownV2", reply_markup=keyboard)    
async def cmd_anime(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "🔍 Eɴᴛᴇʀ ᴛʜᴇ *ᴀɴɪᴍᴇ ɴᴀᴍᴇ* ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ ᴘᴏsᴛᴇʀ ғᴏʀ",
        parse_mode="Markdown"
    )
    return ASK_ANIME

async def received_anime_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    await update.message.reply_text(f"⏳ Searching for *{name}*...", parse_mode="Markdown")
    try:
        results = fetch_anime(name)
    except Exception:
        await update.message.reply_text(
            "⏳ Jikan API is slow right now. Please wait 10 seconds and try /anime again."
        )
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
    await update.message.reply_text(
        "📋 Select the correct anime:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
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
    score  = anime.get("score") or "N/A"

    await query.edit_message_text(
        f"✅ *{title}*\n🎭 Genres: {genres}\n⭐ Score: {score}\n\n"
        f"🎨 Choose a *color theme* for your poster:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🟢 ɢʀᴇᴇɴ", callback_data="color_green"), InlineKeyboardButton("🔵 ᴄʏᴀɴ", callback_data="color_cyan")],
            [InlineKeyboardButton("🔴 ʀᴇᴅ", callback_data="color_red"), InlineKeyboardButton("🟠 ᴏʀᴀɴɢᴇ", callback_data="color_orange")],
        ])
    )
    return ASK_COLOR

async def color_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["color"] = query.data
    await query.edit_message_text("📸 Now send the *background / character image* for the poster:", parse_mode="Markdown")
    return ASK_PHOTO

async def received_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    photo = update.message.photo[-1] if update.message.photo else None
    doc   = update.message.document

    if not photo and not doc:
        await update.message.reply_text("⚠️ Please send a photo or image file.")
        return ASK_PHOTO

    await update.message.reply_text("🎨 Creating your poster, please wait...")
    try:
        file         = await ctx.bot.get_file(photo.file_id if photo else doc.file_id)
        photo_bytes  = await file.download_as_bytearray()
        anime        = ctx.user_data["anime"]
        brand        = ctx.user_data.get("brand", BRAND_NAME)
        color        = ctx.user_data.get("color", "color_green")
        poster_bytes = build_poster(anime, bytes(photo_bytes), brand, color)
        title        = anime.get("title_english") or anime["title"]

        await update.message.reply_photo(
            photo=io.BytesIO(poster_bytes),
            caption=f"🎌 *{title}* poster ready!\n\nSend /anime to make another.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to create poster: {e}")

    return ConversationHandler.END

async def cmd_brand(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    current = ctx.user_data.get("brand", BRAND_NAME)
    await update.message.reply_text(
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
            ASK_COLOR:   [CallbackQueryHandler(color_selected)],
            ASK_PHOTO:   [MessageHandler(filters.PHOTO | filters.Document.IMAGE, received_photo)],
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
    app.add_handler(CallbackQueryHandler(cmd_cancel_callback, pattern="^cmd_cancel$"))
    app.add_handler(CallbackQueryHandler(developer_callback, pattern="^developer$"))
    app.add_handler(CallbackQueryHandler(back_start_callback, pattern="^back_start$"))

    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
