import os
import io
import time
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

# ─── Import all poster builders & shared data from posters.py ─────────────────
from posters import (
    THEMES,
    build_poster_hex,
    build_poster_cinematic,
    build_poster_modern,
    build_poster_banner,
)

# ── Dummy HTTP server ──────────────────────────────────────────────────────────
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
OWNER_ID   = 0          # <- Set your Telegram user ID here (integer)
BRAND_NAME = "ANIMEFLIO"
JIKAN_API  = "https://api.jikan.moe/v4"

ASK_ANIME, ASK_CONFIRM, ASK_PHOTO, ASK_STYLE, ASK_COLOR, ASK_BRAND = range(6)

# ─── User tracking (in-memory) ────────────────────────────────────────────────
_users: set[int] = set()

def track_user(update: Update):
    """Call at the start of any handler to record the user."""
    if update.effective_user:
        _users.add(update.effective_user.id)

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
              studios(isMain: true) { nodes { name } }
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
                studios = item.get("studios", {}).get("nodes", [])
                results.append({
                    "title_english": item["title"].get("english") or item["title"].get("romaji"),
                    "title": item["title"].get("romaji") or item["title"].get("english"),
                    "genres": [{"name": g} for g in (item.get("genres") or [])],
                    "score": round((item.get("averageScore") or 0) / 10, 1) or "N/A",
                    "episodes": item.get("episodes") or "?",
                    "synopsis": item.get("description") or "No synopsis available.",
                    "year": (item.get("startDate") or {}).get("year"),
                    "studio": studios[0]["name"] if studios else "Unknown",
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
    track_user(update)
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
        caption=welcome_text, parse_mode="MarkdownV2", reply_markup=keyboard,
        message_effect_id="5104841245755180586"
    )

async def cmd_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Owner-only: shows total unique bot users."""
    track_user(update)
    user = update.effective_user
    if user.id != OWNER_ID:
        await update.message.reply_text("⛔ This command is only for the bot owner.")
        return
    count = len(_users)
    await update.message.reply_text(
        f"👥 *Total Users*\n\n"
        f"*{count}* unique user\\(s\\) have interacted with this bot since last restart\\.",
        parse_mode="MarkdownV2"
    )

async def show_commands_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    track_user(update)
    await update.callback_query.answer()
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("• ᴄʀᴇᴀᴛᴇ ᴘᴏꜱᴛᴇʀ •", callback_data="cmd_anime")],
        [InlineKeyboardButton("• ᴄʜᴀɴɢᴇ ʙʀᴀɴᴅ •", callback_data="cmd_brand")],
        [InlineKeyboardButton("ᴄʟᴏꜱᴇ", callback_data="cmd_cancel")],
    ])
    await update.callback_query.edit_message_reply_markup(reply_markup=keyboard)

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

async def cmd_anime_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    track_user(update)
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    await query.message.reply_text(
        "🔍 Eɴᴛᴇʀ ᴛʜᴇ *ᴀɴɪᴍᴇ ɴᴀᴍᴇ* ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ ᴘᴏsᴛᴇʀ ғᴏʀ:",
        parse_mode="Markdown"
    )
    return ASK_ANIME

async def cmd_anime(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    track_user(update)
    ctx.user_data.clear()
    await update.message.reply_text(
        "🔍 Eɴᴛᴇʀ ᴛʜᴇ *ᴀɴɪᴍᴇ ɴᴀᴍᴇ* ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ ᴘᴏsᴛᴇʀ ғᴏʀ:",
        parse_mode="Markdown"
    )
    return ASK_ANIME

async def received_anime_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    track_user(update)
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
    track_user(update)
    photo = update.message.photo[-1] if update.message.photo else None
    doc   = update.message.document
    if not photo and not doc:
        await update.message.reply_text("⚠️ Please send a photo or image file.")
        return ASK_PHOTO
    file        = await ctx.bot.get_file(photo.file_id if photo else doc.file_id)
    photo_bytes = await file.download_as_bytearray()
    ctx.user_data["photo_bytes"] = bytes(photo_bytes)

    await update.message.reply_text(
        "🖼️ Choose your *poster style*:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎴 Style 1 — Classic Hex",    callback_data="style_hex")],
            [InlineKeyboardButton("🎬 Style 2 — Cinematic",      callback_data="style_cinematic")],
            [InlineKeyboardButton("🖥️ Style 3 — Modern UI",     callback_data="style_modern")],
            [InlineKeyboardButton("📺 Style 4 — Channel Banner", callback_data="style_banner")],
        ])
    )
    return ASK_STYLE

async def style_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    ctx.user_data["style"] = query.data.replace("style_", "")
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
    style      = ctx.user_data.get("style", "hex")
    await query.edit_message_text(
        f"🎨 Creating your *{theme_name}* poster, please wait...",
        parse_mode="Markdown"
    )
    try:
        anime       = ctx.user_data["anime"]
        photo_bytes = ctx.user_data["photo_bytes"]
        brand       = get_user_brand(ctx, query.from_user.id)

        if style == "cinematic":
            poster_bytes = build_poster_cinematic(anime, photo_bytes, brand, theme_name)
        elif style == "modern":
            poster_bytes = build_poster_modern(anime, photo_bytes, brand, theme_name)
        elif style == "banner":
            poster_bytes = build_poster_banner(anime, photo_bytes, brand, theme_name)
        else:
            poster_bytes = build_poster_hex(anime, photo_bytes, brand, theme_name)

        title = anime.get("title_english") or anime["title"]
        await query.message.reply_photo(
            photo=io.BytesIO(poster_bytes),
            caption=f"🎌 *{title}* — {THEMES[theme_name]['emoji']} {theme_name.capitalize()} poster ready!\n\nSend /anime to make another.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await query.message.reply_text(f"❌ Failed to create poster: {e}")
    return ConversationHandler.END

def get_user_brand(ctx: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    """Retrieve the brand set by this user, falling back to default."""
    return ctx.bot_data.get(f"brand_{user_id}", BRAND_NAME)

def set_user_brand(ctx: ContextTypes.DEFAULT_TYPE, user_id: int, brand: str):
    """Save brand globally per user so all conversations share it."""
    ctx.bot_data[f"brand_{user_id}"] = brand

async def cmd_brand(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    track_user(update)
    current = get_user_brand(ctx, update.effective_user.id)
    await update.message.reply_text(
        f"🏷️ Current brand: *{current}*\n\nSend the new brand name:",
        parse_mode="Markdown"
    )
    return ASK_BRAND

async def cmd_brand_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    track_user(update)
    await update.callback_query.answer()
    current = get_user_brand(ctx, update.effective_user.id)
    await update.callback_query.message.reply_text(
        f"🏷️ Current brand: *{current}*\n\nSend the new brand name:",
        parse_mode="Markdown"
    )
    return ASK_BRAND

async def received_brand(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    new_brand = update.message.text.strip().upper()
    set_user_brand(ctx, update.effective_user.id, new_brand)
    await update.message.reply_text(
        f"✅ Brand set to: *{new_brand}*\n\nThis will be used in all your future posters.",
        parse_mode="Markdown"
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
            ASK_CONFIRM: [CallbackQueryHandler(anime_selected, pattern="^(cancel|\d+)$")],
            ASK_PHOTO:   [MessageHandler(filters.PHOTO | filters.Document.IMAGE, received_photo)],
            ASK_STYLE:   [CallbackQueryHandler(style_selected, pattern="^style_")],
            ASK_COLOR:   [CallbackQueryHandler(color_selected, pattern="^color_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
        per_chat=True,
        allow_reentry=True,
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
        per_message=False,
        per_chat=True,
    )

    app.add_handler(anime_conv)
    app.add_handler(brand_conv)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CallbackQueryHandler(show_commands_callback, pattern="^show_commands$"))
    app.add_handler(CallbackQueryHandler(cmd_cancel_callback,    pattern="^cmd_cancel$"))
    app.add_handler(CallbackQueryHandler(developer_callback,     pattern="^developer$"))
    app.add_handler(CallbackQueryHandler(back_start_callback,    pattern="^back_start$"))

    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
