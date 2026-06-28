"""
Telegram Anime Poster Bot
Requirements:
    pip install python-telegram-bot==20.7 Pillow requests aiohttp jikanpy-v4

Setup:
    1. Create a bot via @BotFather on Telegram → get TOKEN
    2. Replace BOT_TOKEN below with your token
    3. Put your brand name in BRAND_NAME
    4. Run: python bot.py
"""

import os
import io
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

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
import re
import math
import textwrap
import asyncio
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN   = "YOUR_BOT_TOKEN_HERE"
BRAND_NAME  = "HELLFIRE ACADEMY"
JIKAN_API   = "https://api.jikan.moe/v4"

# Conversation states
ASK_ANIME, ASK_CONFIRM, ASK_PHOTO, ASK_BRAND = range(4)

# ─── COLORS ───────────────────────────────────────────────────────────────────
BG_DARK   = (13, 26, 13)
GREEN     = (34, 197, 94)
GREEN_DIM = (20, 82, 20)
GOLD      = (212, 168, 85)
WHITE     = (255, 255, 255)
GRAY      = (180, 180, 180)
BLACK     = (0, 0, 0)

W, H = 1280, 720   # 16:9

# ─── FONT LOADER ──────────────────────────────────────────────────────────────
def load_font(size, bold=False):
    """Try system fonts, fall back to default."""
    candidates = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
         "C:/Windows/Fonts/arialbd.ttf", "/System/Library/Fonts/Helvetica.ttc"]
        if bold else
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
         "C:/Windows/Fonts/arial.ttf", "/System/Library/Fonts/Helvetica.ttc"]
    )
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()

# ─── HEX GRID ─────────────────────────────────────────────────────────────────
def draw_hex_grid(draw, width, height):
    """Draw dark green hexagon grid background."""
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
    """Fade left side to dark so text stays readable."""
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
def build_poster(anime: dict, photo_bytes: bytes, brand: str) -> bytes:
    title    = anime.get("title_english") or anime.get("title", "UNKNOWN")
    title_jp = anime.get("title", "")
    genres   = [g["name"].upper() for g in anime.get("genres", [])][:3]
    synopsis = anime.get("synopsis") or "No synopsis available."
    score    = anime.get("score") or "N/A"
    episodes = anime.get("episodes") or "?"

    # ── base: hex grid ──
    base = Image.new("RGB", (W, H), BG_DARK)
    draw_hex_grid(ImageDraw.Draw(base), W, H)

    # ── right-side character photo ──
    char_img = Image.open(io.BytesIO(photo_bytes)).convert("RGBA")
    char_w   = int(W * 0.60)
    char_h   = H
    char_img = char_img.resize(
        (char_w, char_h), Image.LANCZOS
    )
    base.paste(char_img.convert("RGB"), (W - char_w, 0))

    # ── gradient fade left over photo ──
    base = apply_left_gradient(base)

    # ── green right-edge glow ──
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd   = ImageDraw.Draw(glow)
    for i in range(120):
        alpha = int(60 * (1 - i / 120))
        gd.line([(W - char_w + i, 0), (W - char_w + i, H)],
                fill=(34, 197, 94, alpha))
    base = Image.alpha_composite(base.convert("RGBA"), glow).convert("RGB")

    draw = ImageDraw.Draw(base)

    # ── brand / logo top-left ──
    f_brand = load_font(16, bold=True)
    # hexagon logo
    logo_cx, logo_cy, logo_r = 28, 28, 18
    hex_pts = [
        (logo_cx + logo_r * math.cos(math.radians(60 * i - 30)),
         logo_cy + logo_r * math.sin(math.radians(60 * i - 30)))
        for i in range(6)
    ]
    draw.polygon(hex_pts, outline=GREEN, fill=None)
    draw.text((logo_cx, logo_cy), "H", font=load_font(18, bold=True),
              fill=GREEN, anchor="mm")
    draw.text((52, 20), brand.upper(), font=f_brand, fill=WHITE)

    # ── title ──
    title_upper = title.upper()
    f_title = load_font(80, bold=True)
    # shrink if too long
    while f_title.size > 36:
        bbox = draw.textbbox((0, 0), title_upper, font=f_title)
        if (bbox[2] - bbox[0]) < int(W * 0.52):
            break
        f_title = load_font(f_title.size - 4, bold=True)

    draw.text((38, 180), title_upper, font=f_title, fill=WHITE)
    t_bbox = draw.textbbox((38, 180), title_upper, font=f_title)
    title_bottom = t_bbox[3]

    # ── subtitle (japanese / romaji) ──
    if title_jp and title_jp != title:
        f_sub = load_font(int(f_title.size * 0.88), bold=True)
        draw.text((38, title_bottom + 4), title_jp.upper(),
                  font=f_sub, fill=GREEN)
        title_bottom = draw.textbbox(
            (38, title_bottom + 4), title_jp.upper(), font=f_sub)[3]

    # ── genres ──
    gy = title_bottom + 18
    gx = 38
    f_genre = load_font(15, bold=True)
    for g in genres:
        draw.text((gx, gy), g, font=f_genre, fill=GOLD)
        gx += draw.textbbox((0, 0), g, font=f_genre)[2] + 24

    # ── score & episodes badge ──
    badge_x = 38
    badge_y = gy + 32
    for label, val in [("★", str(score)), ("EP", str(episodes))]:
        txt = f"{label} {val}"
        draw.text((badge_x, badge_y), txt,
                  font=load_font(13, bold=True), fill=GREEN)
        badge_x += draw.textbbox((0, 0), txt, font=load_font(13, bold=True))[2] + 26

    # ── synopsis ──
    f_syn = load_font(14)
    syn_clean = re.sub(r'\[.*?\]', '', synopsis).strip()
    wrapped   = textwrap.wrap(syn_clean, width=52)[:6]
    sy = badge_y + 32
    for line in wrapped:
        draw.text((38, sy), line, font=f_syn, fill=GRAY)
        sy += 22
    if len(textwrap.wrap(syn_clean, 52)) > 6:
        draw.text((38, sy), "...read more", font=f_syn, fill=GREEN)
        sy += 22

    # ── CTA buttons ──
    btn_y = sy + 20
    for i, label in enumerate(["DOWNLOAD", "JOIN NOW"]):
        bx = 38 + i * 210
        bw, bh = 185, 44
        draw.rounded_rectangle([bx, btn_y, bx + bw, btn_y + bh],
                                radius=4, fill=GREEN)
        f_btn = load_font(15, bold=True)
        tw = draw.textbbox((0, 0), label, font=f_btn)[2]
        draw.text((bx + (bw - tw) // 2, btn_y + 12),
                  label, font=f_btn, fill=BLACK)

    # ── encode to bytes ──
    out = io.BytesIO()
    base.save(out, format="JPEG", quality=95)
    out.seek(0)
    return out.read()

# ─── JIKAN FETCH ──────────────────────────────────────────────────────────────
def fetch_anime(name: str) -> list[dict]:
    r = requests.get(f"{JIKAN_API}/anime", params={"q": name, "limit": 5}, timeout=10)
    r.raise_for_status()
    return r.json().get("data", [])

# ─── BOT HANDLERS ─────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎌 *Anime Poster Bot*\n\nSend /anime to create a custom 16:9 poster!\n"
        "Send /brand to change the brand name.",
        parse_mode="Markdown"
    )

async def cmd_anime(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text(
        "🔍 Enter the *anime name* you want to create a poster for:",
        parse_mode="Markdown"
    )
    return ASK_ANIME

async def received_anime_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    await update.message.reply_text(f"⏳ Searching for *{name}*...", parse_mode="Markdown")

    try:
        results = fetch_anime(name)
    except Exception as e:
        await update.message.reply_text(f"❌ Error fetching anime: {e}")
        return ConversationHandler.END

    if not results:
        await update.message.reply_text("❌ No anime found. Try a different name.")
        return ASK_ANIME

    ctx.user_data["results"] = results
    # Show selection keyboard
    buttons = [
        [InlineKeyboardButton(
            f"{a.get('title_english') or a['title']} ({a.get('year') or '?'})",
            callback_data=str(i)
        )]
        for i, a in enumerate(results[:5])
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

    idx   = int(query.data)
    anime = ctx.user_data["results"][idx]
    ctx.user_data["anime"] = anime

    title = anime.get("title_english") or anime["title"]
    genres = ", ".join(g["name"] for g in anime.get("genres", [])[:3]) or "N/A"
    score  = anime.get("score") or "N/A"

    await query.edit_message_text(
        f"✅ *{title}*\n"
        f"🎭 Genres: {genres}\n"
        f"⭐ Score: {score}\n\n"
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

    await update.message.reply_text("🎨 Creating your poster, please wait...")

    try:
        if photo:
            file = await ctx.bot.get_file(photo.file_id)
        else:
            file = await ctx.bot.get_file(doc.file_id)

        photo_bytes = await file.download_as_bytearray()
        anime       = ctx.user_data["anime"]
        brand       = ctx.user_data.get("brand", BRAND_NAME)

        poster_bytes = build_poster(anime, bytes(photo_bytes), brand)

        title = anime.get("title_english") or anime["title"]
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
    brand = update.message.text.strip().upper()
    ctx.user_data["brand"] = brand
    await update.message.reply_text(f"✅ Brand set to: *{brand}*", parse_mode="Markdown")
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    anime_conv = ConversationHandler(
        entry_points=[CommandHandler("anime", cmd_anime)],
        states={
            ASK_ANIME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, received_anime_name)],
            ASK_CONFIRM: [CallbackQueryHandler(anime_selected)],
            ASK_PHOTO:   [MessageHandler(filters.PHOTO | filters.Document.IMAGE, received_photo)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        per_chat=True,
    )

    brand_conv = ConversationHandler(
        entry_points=[CommandHandler("brand", cmd_brand)],
        states={
            ASK_BRAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_brand)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(anime_conv)
    app.add_handler(brand_conv)

    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()