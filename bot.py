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
ASK_ANIME, ASK_CONFIRM, ASK_PHOTO, ASK_BRAND = range(4)

# ─── COLORS ───────────────────────────────────────────────────────────────────
BG_DARK = (13, 26, 13)
GREEN   = (34, 197, 94)
GOLD    = (212, 168, 85)
WHITE   = (255, 255, 255)
GRAY    = (180, 180, 180)
BLACK   = (0, 0, 0)

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
def build_poster(anime: dict, photo_bytes: bytes, brand: str) -> bytes:
    title    = anime.get("title_english") or anime.get("title", "UNKNOWN")
    title_jp = anime.get("title", "")
    genres   = [g["name"].upper() for g in anime.get("genres", [])][:3]
    synopsis = anime.get("synopsis") or "No synopsis available."

    # ── Step 1: Full dark hex grid background ──
    base = Image.new("RGB", (W, H), BG_DARK)
    draw_hex_grid(ImageDraw.Draw(base), W, H)

    # ── Step 2: Place photo on RIGHT half with strong diagonal fade ──
    char_img = Image.open(io.BytesIO(photo_bytes)).convert("RGBA")
    # Resize to fill right 60% of poster height
    char_w = int(W * 0.62)
    scale  = H / char_img.height
    new_w  = int(char_img.width * scale)
    char_img = char_img.resize((new_w, H), Image.LANCZOS)
    # Crop to fit
    if new_w > char_w:
        char_img = char_img.crop(((new_w - char_w) // 2, 0,
                                   (new_w - char_w) // 2 + char_w, H))
    elif new_w < char_w:
        # pad if too narrow
        padded = Image.new("RGBA", (char_w, H), (0, 0, 0, 0))
        padded.paste(char_img, ((char_w - new_w) // 2, 0))
        char_img = padded

    # Apply strong left-to-right fade mask on the photo itself
    fade_mask = Image.new("L", (char_w, H), 0)
    fm_draw   = ImageDraw.Draw(fade_mask)
    fade_zone = int(char_w * 0.55)
    for x in range(char_w):
        if x < fade_zone:
            alpha = int(255 * ((x / fade_zone) ** 2.2))
        else:
            alpha = 255
        fm_draw.line([(x, 0), (x, H)], fill=alpha)
    char_rgba = char_img.copy().convert("RGBA")
    r, g, b, a = char_rgba.split()
    a = Image.composite(a, Image.new("L", a.size, 0), fade_mask)
    char_rgba = Image.merge("RGBA", (r, g, b, a))

    base_rgba = base.convert("RGBA")
    base_rgba.paste(char_rgba, (W - char_w, 0), char_rgba)
    base = base_rgba.convert("RGB")

    draw = ImageDraw.Draw(base)

    # ── Step 3: Dark overlay on left 45% to ensure text contrast ──
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov_draw  = ImageDraw.Draw(overlay)
    for x in range(int(W * 0.52)):
        alpha = int(180 * (1 - x / (W * 0.52)) ** 0.5)
        ov_draw.line([(x, 0), (x, H)], fill=(10, 20, 10, alpha))
    base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(base)

    # ── Step 4: Brand logo top-left ──
    logo_cx, logo_cy, logo_r = 30, 30, 20
    hex_pts = [
        (logo_cx + logo_r * math.cos(math.radians(60 * i - 30)),
         logo_cy + logo_r * math.sin(math.radians(60 * i - 30)))
        for i in range(6)
    ]
    draw.polygon(hex_pts, outline=GREEN, fill=(13, 26, 13))
    draw.text((logo_cx, logo_cy), "A", font=load_font(20, bold=True),
              fill=GREEN, anchor="mm")
    draw.text((58, 18), brand.upper(), font=load_font(17, bold=True), fill=WHITE)

    # ── Step 5: Title (white, large) ──
    title_upper = title.upper()
    f_title = load_font(96, bold=True)
    max_w   = int(W * 0.48)
    while f_title.size > 40:
        bbox = draw.textbbox((0, 0), title_upper, font=f_title)
        if (bbox[2] - bbox[0]) <= max_w:
            break
        f_title = load_font(f_title.size - 6, bold=True)

    ty = int(H * 0.28)
    draw.text((38, ty), title_upper, font=f_title, fill=WHITE)
    title_bottom = draw.textbbox((38, ty), title_upper, font=f_title)[3]

   # ── Step 6: Season number in green ──
    import re as _re
    season_match = _re.search(r'season\s*(\d+)', title_upper, flags=_re.IGNORECASE)
    if not season_match:
        season_match = _re.search(r'\s+(\d+)$', title_upper)
    if season_match:
        season_num = season_match.group(1)
        season_text = f"SEASON {season_num}"
        title_upper = _re.sub(r'\s*season\s*\d+|\s*\b' + season_num + r'\b', '', title_upper, flags=_re.IGNORECASE).strip()
        draw.text((38, title_bottom + 2), season_text, font=load_font(int(f_title.size * 0.6), bold=True), fill=GREEN)
        title_bottom = draw.textbbox((38, title_bottom + 2), season_text, font=load_font(int(f_title.size * 0.6), bold=True))[3]

    # ── Step 7: Genre tags ──
    gy = title_bottom + 20
    gx = 38
    f_genre = load_font(16, bold=True)
    for g in genres:
        draw.text((gx, gy), g, font=f_genre, fill=GOLD)
        gx += draw.textbbox((0, 0), g, font=f_genre)[2] + 28

    # ── Step 8: Synopsis (italic style, wrap tight) ──
    f_syn     = load_font(15)
    syn_clean = re.sub(r'\[.*?\]|\(.*?\)', '', synopsis).strip()
    wrapped   = textwrap.wrap(syn_clean, width=48)
    sy = gy + 36
    max_lines = 6
    for i, line in enumerate(wrapped[:max_lines]):
        draw.text((38, sy), line, font=f_syn, fill=GRAY)
        sy += 24
    if len(wrapped) > max_lines:
        draw.text((38, sy), "...read more", font=f_syn, fill=GREEN)
        sy += 24

    # ── Step 9: CTA buttons ──
    btn_y = sy + 18
    f_btn = load_font(16, bold=True)
    for i, label in enumerate(["DOWNLOAD", "JOIN NOW"]):
        bx = 38 + i * 220
        bw, bh = 195, 48
        draw.rounded_rectangle([bx, btn_y, bx + bw, btn_y + bh],
                                radius=5, fill=GREEN)
        tw = draw.textbbox((0, 0), label, font=f_btn)[2]
        draw.text((bx + (bw - tw) // 2, btn_y + 14),
                  label, font=f_btn, fill=BLACK)

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
        "👨‍💻 *ᴅᴇᴠᴇʟᴏᴘᴇʀ ɪɴғᴏ*\n\n"
        "» ᴄʀᴇᴀᴛᴏʀ: [WAVE](https://t.me/Wave_189)\n"
        "» ʙᴏᴛ: [ᴀɴɪᴍᴇғʟɪᴏ ʙᴏᴛ](https://t.me/)\n"
        "» sᴜᴘᴘᴏʀᴛ: [ᴀɴɪᴍᴇғʟɪᴏ ᴄʜᴀᴛ](https://t.me/YOUR_GROUP)"
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
        file         = await ctx.bot.get_file(photo.file_id if photo else doc.file_id)
        photo_bytes  = await file.download_as_bytearray()
        anime        = ctx.user_data["anime"]
        brand        = ctx.user_data.get("brand", BRAND_NAME)
        poster_bytes = build_poster(anime, bytes(photo_bytes), brand)
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
