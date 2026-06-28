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
def hex_polygon(cx, cy, size, flat_top=False):
    """Return 6 points of a hexagon centered at (cx, cy)."""
    offset = 0 if flat_top else 30
    return [
        (cx + size * math.cos(math.radians(60 * i - offset)),
         cy + size * math.sin(math.radians(60 * i - offset)))
        for i in range(6)
    ]

def build_poster(anime: dict, photo_bytes: bytes, brand: str, color: str = "color_green") -> bytes:
    title    = anime.get("title_english") or anime.get("title", "UNKNOWN")
    genres   = [g["name"].upper() for g in anime.get("genres", [])][:5]
    synopsis = anime.get("synopsis") or "No synopsis available."

    # ── Theme colors ──
    theme  = THEMES.get(color, THEMES["color_green"])
    bg     = theme["bg"]
    accent = theme["accent"]
    hfill  = theme["hex_fill"]
    ovlay  = theme["overlay"]

    # ── Step 1: Dark background ──
    base = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(base)

    # ── Step 2: Draw background hex grid (left side subtle) ──
    hex_size = 62
    hex_h = math.sqrt(3) * hex_size
    col_w = hex_size * 1.5
    cols = int(W / col_w) + 2
    rows = int(H / hex_h) + 2
    for col in range(cols):
        for row in range(rows):
            cx = col * col_w
            cy = row * hex_h + (hex_h / 2 if col % 2 else 0)
            pts = hex_polygon(cx, cy, hex_size - 3)
            # Left side darker, right side brighter
            brightness = min(1.0, cx / W * 2)
            fill_r = int(hfill[0] + (accent[0] - hfill[0]) * brightness * 0.15)
            fill_g = int(hfill[1] + (accent[1] - hfill[1]) * brightness * 0.15)
            fill_b = int(hfill[2] + (accent[2] - hfill[2]) * brightness * 0.15)
            draw.polygon(pts, outline=(*accent, 60), fill=(fill_r, fill_g, fill_b))

    # ── Step 3: Load and prepare character image ──
    char_img = Image.open(io.BytesIO(photo_bytes)).convert("RGBA")
    # Scale to cover right 65% of poster
    target_h = H
    scale = target_h / char_img.height
    new_w = int(char_img.width * scale)
    char_img = char_img.resize((new_w, target_h), Image.LANCZOS)

    # ── Step 4: Place character image in hexagonal mosaic on right side ──
    # Define hex cells for the mosaic (right portion of poster)
    mosaic_cx_start = int(W * 0.42)
    hex_m = 95  # mosaic hex size
    hex_mh = math.sqrt(3) * hex_m
    col_mw = hex_m * 1.5

    # Generate mosaic hex positions
    mosaic_positions = []
    m_cols = int((W - mosaic_cx_start) / col_mw) + 2
    m_rows = int(H / hex_mh) + 2
    for col in range(m_cols):
        for row in range(m_rows):
            cx = mosaic_cx_start + col * col_mw
            cy = row * hex_mh + (hex_mh / 2 if col % 2 else 0)
            if cx - hex_m < W and cy - hex_m < H + hex_m:
                mosaic_positions.append((cx, cy))

    # For each hex cell, clip the character image into it
    base_rgba = base.convert("RGBA")
    for (cx, cy) in mosaic_positions:
        pts = hex_polygon(cx, cy, hex_m - 4)
        # Create hex mask
        hex_mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(hex_mask).polygon(pts, fill=255)

        # Sample from character image at this position
        # Map poster coords to char_img coords
        char_x_offset = W - new_w  # char starts here
        src_x = int(cx - char_x_offset)
        src_y = int(cy - H // 2 + char_img.height // 2)

        if 0 <= src_x < char_img.width and 0 <= src_y < char_img.height:
            # Paste char image clipped to hex
            char_rgba = char_img.convert("RGBA")
            paste_x = char_x_offset
            paste_y = 0
            temp = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            temp.paste(char_rgba, (paste_x, paste_y))
            # Apply hex mask
            r2, g2, b2, a2 = temp.split()
            a2 = Image.composite(a2, Image.new("L", (W, H), 0), hex_mask)
            temp = Image.merge("RGBA", (r2, g2, b2, a2))
            base_rgba = Image.alpha_composite(base_rgba, temp)

            # Draw hex border with accent color
            border_draw = ImageDraw.Draw(base_rgba)
            border_draw.polygon(pts, outline=(*accent, 180))

    base = base_rgba.convert("RGB")
    draw = ImageDraw.Draw(base)

    # ── Step 5: Left gradient overlay for text readability ──
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    fade_w = int(W * 0.58)
    for x in range(fade_w):
        alpha = int(220 * (1 - x / fade_w) ** 1.2)
        gd.line([(x, 0), (x, H)], fill=(*bg, alpha))
    base = Image.alpha_composite(base.convert("RGBA"), grad).convert("RGB")
    draw = ImageDraw.Draw(base)

    # ── Step 6: Brand logo top-left ──
    logo_cx, logo_cy, logo_r = 32, 32, 22
    hex_pts = hex_polygon(logo_cx, logo_cy, logo_r)
    draw.polygon(hex_pts, outline=accent, fill=bg)
    draw.text((logo_cx, logo_cy), "A", font=load_font(18, bold=True), fill=accent, anchor="mm")
    draw.text((62, 20), brand.upper(), font=load_font(17, bold=True), fill=WHITE)

    # ── Step 7: Title ──
    title_upper = title.upper()
    import re as _re
    # Detect season
    season_match = _re.search(r'season\s*(\d+)', title_upper, flags=_re.IGNORECASE)
    if not season_match:
        season_match = _re.search(r'\s+(\d+)$', title_upper)
    season_text = None
    if season_match:
        season_num = season_match.group(1)
        season_text = f"SEASON {season_num}"
        title_upper = _re.sub(r'\s*season\s*\d+|\s*\b' + season_num + r'\b', '', title_upper, flags=_re.IGNORECASE).strip()

    f_title = load_font(96, bold=True)
    max_w = int(W * 0.46)
    while f_title.size > 40:
        bbox = draw.textbbox((0, 0), title_upper, font=f_title)
        if (bbox[2] - bbox[0]) <= max_w:
            break
        f_title = load_font(f_title.size - 6, bold=True)

    ty = int(H * 0.30)
    draw.text((38, ty), title_upper, font=f_title, fill=WHITE)
    title_bottom = draw.textbbox((38, ty), title_upper, font=f_title)[3]

    # Season line in accent
    if season_text:
        f_season = load_font(int(f_title.size * 0.65), bold=True)
        draw.text((38, title_bottom + 4), season_text, font=f_season, fill=accent)
        title_bottom = draw.textbbox((38, title_bottom + 4), season_text, font=f_season)[3]

    # ── Step 8: Genre tags ──
    gy = title_bottom + 18
    gx = 38
    f_genre = load_font(15, bold=True)
    genre_colors = [GOLD, accent, WHITE, (255, 100, 100), (100, 255, 200)]
    for idx, g in enumerate(genres):
        draw.text((gx, gy), g, font=f_genre, fill=genre_colors[idx % len(genre_colors)])
        gx += draw.textbbox((0, 0), g, font=f_genre)[2] + 24

    # ── Step 9: Synopsis ──
    f_syn = load_font(14)
    syn_clean = re.sub(r'<[^>]+>', '', synopsis)
    syn_clean = re.sub(r'\[.*?\]|\(.*?\)', '', syn_clean).strip()
    # italic style with slightly slanted look using regular font
    wrapped = textwrap.wrap(syn_clean, width=50)
    sy = gy + 34
    max_lines = 6
    for i, line in enumerate(wrapped[:max_lines]):
        draw.text((38, sy), line, font=f_syn, fill=GRAY)
        sy += 22
    if len(wrapped) > max_lines:
        draw.text((38, sy), "...read more", font=f_syn, fill=accent)
        sy += 22

    # ── Step 10: CTA buttons ──
    btn_y = sy + 16
    f_btn = load_font(15, bold=True)
    for i, label in enumerate(["DOWNLOAD", "JOIN NOW"]):
        bx = 38 + i * 210
        bw, bh = 190, 46
        # Button with accent fill and slight border effect
        draw.rounded_rectangle([bx - 2, btn_y - 2, bx + bw + 2, btn_y + bh + 2],
                                radius=4, fill=(*accent[:3],))
        draw.rounded_rectangle([bx, btn_y, bx + bw, btn_y + bh],
                                radius=3, fill=accent)
        tw = draw.textbbox((0, 0), label, font=f_btn)[2]
        draw.text((bx + (bw - tw) // 2, btn_y + 14), label, font=f_btn, fill=BLACK)

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
