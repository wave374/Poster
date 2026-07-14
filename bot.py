import os
import io
import time
import asyncio
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

from posters import (
    THEMES,
    build_poster_hex,
    build_poster_cinematic,
    build_poster_modern,
    build_poster_banner,
)
from fsub import check_fsub, fsub_retry_callback, set_on_verified
from image_fetch import fetch_official_images, download_image

# ── Dummy HTTP server ──────────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot is running!")
    def log_message(self, *args): pass

_port = int(os.environ.get("PORT", 10000))
_server = HTTPServer(("0.0.0.0", _port), _Handler)
threading.Thread(target=_server.serve_forever, daemon=True).start()
print(f"Dummy server listening on port {_port}")

# ─── CONFIG ───────────────────────────────────────────────────────────────────
BOT_TOKEN  = "8955163269:AAGDXtElSgN1Z-fjSfHopJ7GuNLUmnoWEls"
OWNER_ID   = 7115720502
BRAND_NAME = "ANIMEFLIO"
JIKAN_API  = "https://api.jikan.moe/v4"

(ASK_ANIME, ASK_CONFIRM, ASK_PHOTO_CHOICE, ASK_PHOTO, ASK_STYLE,
 ASK_COLOR, ASK_NEXT_IMAGE, ASK_BRAND, ASK_BROADCAST) = range(9)

_users: set[int] = set()

# ─── SMALL CAPS BOLD HELPER ───────────────────────────────────────────────────
_SC = {
    'a':'ᴀ','b':'ʙ','c':'ᴄ','d':'ᴅ','e':'ᴇ','f':'ғ','g':'ɢ','h':'ʜ',
    'i':'ɪ','j':'ᴊ','k':'ᴋ','l':'ʟ','m':'ᴍ','n':'ɴ','o':'ᴏ','p':'ᴘ',
    'q':'ǫ','r':'ʀ','s':'s','t':'ᴛ','u':'ᴜ','v':'ᴠ','w':'ᴡ','x':'x',
    'y':'ʏ','z':'ᴢ',
    'A':'ᴀ','B':'ʙ','C':'ᴄ','D':'ᴅ','E':'ᴇ','F':'ғ','G':'ɢ','H':'ʜ',
    'I':'ɪ','J':'ᴊ','K':'ᴋ','L':'ʟ','M':'ᴍ','N':'ɴ','O':'ᴏ','P':'ᴘ',
    'Q':'ǫ','R':'ʀ','S':'s','T':'ᴛ','U':'ᴜ','V':'ᴠ','W':'ᴡ','X':'x',
    'Y':'ʏ','Z':'ᴢ',
}

def sc(text: str) -> str:
    """Convert text to small caps."""
    return "".join(_SC.get(c, c) for c in text)

def bold_sc(text: str) -> str:
    """Wrap small-caps text in Markdown bold."""
    return f"*{sc(text)}*"

def _esc(text: str) -> str:
    """Escape MarkdownV2 reserved characters."""
    reserved = r"\_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in reserved else c for c in str(text))

# ─── USER TRACKING ────────────────────────────────────────────────────────────
def track_user(update: Update):
    if update.effective_user:
        _users.add(update.effective_user.id)

# ─── BRAND HELPERS ────────────────────────────────────────────────────────────
def get_user_brand(ctx: ContextTypes.DEFAULT_TYPE, user_id: int) -> str:
    return ctx.bot_data.get(f"brand_{user_id}", BRAND_NAME)

def set_user_brand(ctx: ContextTypes.DEFAULT_TYPE, user_id: int, brand: str):
    ctx.bot_data[f"brand_{user_id}"] = brand

# ─── ANIME FETCH ──────────────────────────────────────────────────────────────
def fetch_anime(name: str) -> list[dict]:
    try:
        query = """
        query ($search: String) {
          Page(perPage: 10) {
            media(search: $search, type: ANIME) {
              id
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
                    "anilist_id": item.get("id"),
                    "title_english": item["title"].get("english") or item["title"].get("romaji"),
                    "title": item["title"].get("romaji") or item["title"].get("english"),
                    "genres": [{"name": g} for g in (item.get("genres") or [])],
                    "score": item.get("averageScore") if item.get("averageScore") is not None else "N/A",
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
                if data:
                    results = []
                    for item in data:
                        studios = item.get("studios") or []
                        jikan_score = item.get("score")
                        results.append({
                            "mal_id": item.get("mal_id"),
                            "title_english": item.get("title_english") or item.get("title"),
                            "title": item.get("title") or item.get("title_english"),
                            "genres": [{"name": g.get("name")} for g in (item.get("genres") or [])],
                            # Jikan scores are 0-10; scale to 0-100 so posters show a correct percent
                            "score": round(jikan_score * 10) if isinstance(jikan_score, (int, float)) else "N/A",
                            "episodes": item.get("episodes") or "?",
                            "synopsis": item.get("synopsis") or "No synopsis available.",
                            "year": item.get("year"),
                            "studio": studios[0]["name"] if studios else "Unknown",
                        })
                    return results
        except Exception:
            time.sleep(3)
    return []

# ─── POSTER BUILDER ───────────────────────────────────────────────────────────
POSTER_STYLES = [
    ("hex",       "Classic Hex",    "🎴"),
    ("cinematic", "Cinematic",      "🎬"),
    ("modern",    "Modern UI",      "🖥️"),
    ("banner",    "Channel Banner", "📺"),
]
STYLE_ORIENTATION: dict[str, str] = {
    "hex": "any", "cinematic": "portrait",
    "modern": "portrait", "banner": "landscape",
}
PREVIEW_THEME = "cyan" if "cyan" in THEMES else next(iter(THEMES))

def _build_poster(anime, photo_bytes, brand, style, theme_name) -> bytes:
    if style == "cinematic":  return build_poster_cinematic(anime, photo_bytes, brand, theme_name)
    elif style == "modern":   return build_poster_modern(anime, photo_bytes, brand, theme_name)
    elif style == "banner":   return build_poster_banner(anime, photo_bytes, brand, theme_name)
    return build_poster_hex(anime, photo_bytes, brand, theme_name)

def _render_style_preview(anime, photo_bytes, brand, style_key) -> bytes:
    return _build_poster(anime, photo_bytes, brand, style_key, PREVIEW_THEME)

def _build_preview_caption(style_label, style_emoji, idx, total) -> str:
    return (
        f"{style_emoji} *{sc(f'Style {idx+1}/{total}')} — {sc(style_label)}*\n\n"
        f"◇ {sc('Preview rendered with default colors')}\n"
        f"◇ {sc('Final color theme is chosen after you select a style')}\n\n"
        f"{sc('Use')} *« {sc('Prev')}* / *{sc('Next')} »* {sc('to browse, or tap')} *✦ {sc('Select')}* {sc('to use this style')}"
    )

def _build_preview_keyboard(idx, total) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("« ᴘʀᴇᴠ",   callback_data="style_prev"),
            InlineKeyboardButton("sᴇʟᴇᴄᴛ",   callback_data="style_pick"),
            InlineKeyboardButton("ɴᴇxᴛ »",   callback_data="style_next"),
        ],
        [InlineKeyboardButton("• ᴄᴀɴᴄᴇʟ •", callback_data="style_cancel_preview")],
    ])

def _build_next_image_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔁 ɴᴇxᴛ ɪᴍᴀɢᴇ", callback_data="next_image"),
        InlineKeyboardButton("⏭ sᴋɪᴘ",        callback_data="skip_next_image"),
    ]])

def _poster_caption(anime: dict, theme_name: str) -> str:
    import re as _re
    raw_title  = anime.get("title_english") or anime.get("title", "Unknown")
    raw_genres = ", ".join(g["name"] for g in anime.get("genres", [])[:3]) or "N/A"
    raw_eps    = str(anime.get("episodes") or "?")
    raw_year   = str(anime.get("year") or "N/A")
    raw_studio = str(anime.get("studio") or "Unknown")
    raw_score  = str(anime.get("score") or "N/A")
    raw_syn    = _re.sub(r'<[^>]+>', '', anime.get("synopsis") or "").strip()[:500]
    sm = _re.search(r'[Ss]eason\s*(\d+)', raw_title)
    season_val = sm.group(1) if sm else "1"
    return "\n".join([
        sc(raw_title), "",
        f"🎯 {sc('Season:')} {season_val}",
        f"📺 {sc('Episodes:')} {raw_eps}",
        f"🎭 {sc('Genre:')} {raw_genres}",
        f"📅 {sc('Year:')} {raw_year}",
        f"🏢 {sc('Studio:')} {raw_studio}",
        f"⭐ {sc('Score:')} {raw_score}",
        "", sc("Synopsis:"), sc(raw_syn),
    ])

async def _pick_official_image(images, current_idx, orientation):
    n = len(images)
    if n == 0: return current_idx, None
    for i in range(1, n + 1):
        idx = (current_idx + i) % n
        img = images[idx]
        img_orient = img.get("orientation", "portrait")
        if orientation == "any" or img_orient == orientation:
            data = await asyncio.to_thread(download_image, img["url"])
            if data: return idx, data
    for i in range(1, n + 1):
        idx = (current_idx + i) % n
        data = await asyncio.to_thread(download_image, images[idx]["url"])
        if data: return idx, data
    return current_idx, None

async def _send_style_preview(chat_id, ctx) -> int:
    anime = ctx.user_data["anime"]
    style_key, style_label, style_emoji = POSTER_STYLES[0]
    brand = get_user_brand(ctx, chat_id)
    wait_msg = await ctx.bot.send_message(
        chat_id=chat_id,
        text=f"*{sc('Rendering style preview, please wait')}*",
        parse_mode="Markdown"
    )
    try:
        preview_bytes = _render_style_preview(anime, ctx.user_data["photo_bytes"], brand, style_key)
    except Exception as e:
        await wait_msg.edit_text(f"*{sc('Failed to render preview:')}* {e}", parse_mode="Markdown")
        return ConversationHandler.END
    try: await wait_msg.delete()
    except Exception: pass
    await ctx.bot.send_photo(
        chat_id=chat_id,
        photo=io.BytesIO(preview_bytes),
        caption=_build_preview_caption(style_label, style_emoji, 0, len(POSTER_STYLES)),
        parse_mode="Markdown",
        reply_markup=_build_preview_keyboard(0, len(POSTER_STYLES)),
    )
    return ASK_STYLE

# ─── HANDLERS ─────────────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    track_user(update)
    if not await check_fsub(update, ctx): return
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
    await ctx.bot.send_photo(
        chat_id=update.effective_chat.id,
        photo="https://i.postimg.cc/RF6b28py/e25348fdc52abcafa9e951f6a3d1a51a.jpg",
        caption=welcome_text, parse_mode="MarkdownV2", reply_markup=keyboard,
        message_effect_id="5104841245755180586"
    )

async def cmd_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    track_user(update)
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text(f"*{sc('This command is only for the bot owner')}* ⛔", parse_mode="Markdown")
        return
    await update.message.reply_text(
        f"👥 *{sc('Total Users')}*\n\n"
        f"*{len(_users)}* {sc('unique user(s) have interacted with this bot since last restart')}",
        parse_mode="Markdown"
    )

async def cmd_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    track_user(update)
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text(f"*{sc('This command is only for the bot owner')}* ⛔", parse_mode="Markdown")
        return ConversationHandler.END
    if not _users:
        await update.message.reply_text(f"⚠️ *{sc('No users to broadcast to yet')}*", parse_mode="Markdown")
        return ConversationHandler.END
    await update.message.reply_text(
        f"📢 *{sc('Broadcast Mode')}*\n\n"
        f"{sc('Send the text, photo, or video you want to broadcast to all')} *{len(_users)}* {sc('user(s)')}\n\n"
        f"{sc('Send')} /cancel {sc('to abort')}",
        parse_mode="Markdown"
    )
    return ASK_BROADCAST

async def received_broadcast(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_ids = list(_users)
    total = len(user_ids); sent = 0; failed = 0
    status_msg = await msg.reply_text(f"📤 *{sc(f'Broadcasting to {total} user(s)')}*", parse_mode="Markdown")
    for uid in user_ids:
        try:
            if msg.photo:
                await ctx.bot.send_photo(chat_id=uid, photo=msg.photo[-1].file_id, caption=msg.caption or "")
            elif msg.video:
                await ctx.bot.send_video(chat_id=uid, video=msg.video.file_id, caption=msg.caption or "")
            elif msg.document:
                await ctx.bot.send_document(chat_id=uid, document=msg.document.file_id, caption=msg.caption or "")
            elif msg.text:
                await ctx.bot.send_message(chat_id=uid, text=msg.text)
            else: continue
            sent += 1
        except Exception: failed += 1
        await asyncio.sleep(0.05)
    await status_msg.edit_text(
        f"✅ *{sc('Broadcast Complete')}*\n\n"
        f"📨 {sc('Sent:')} *{sent}*\n"
        f"❌ {sc('Failed:')} *{failed}*\n"
        f"👥 {sc('Total targeted:')} *{total}*",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

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
    query = update.callback_query; await query.answer()
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
    query = update.callback_query; await query.answer()
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
    if not await check_fsub(update, ctx): return ConversationHandler.END
    query = update.callback_query; await query.answer()
    ctx.user_data.clear()
    await query.message.reply_text(
        f"🔍 *{sc('Enter the anime name you want to create a poster for:')}*",
        parse_mode="Markdown"
    )
    return ASK_ANIME

async def cmd_anime(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    track_user(update)
    if not await check_fsub(update, ctx): return ConversationHandler.END
    ctx.user_data.clear()
    await update.message.reply_text(
        f"🔍 *{sc('Enter the anime name you want to create a poster for:')}*",
        parse_mode="Markdown"
    )
    return ASK_ANIME

async def received_anime_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    track_user(update)
    name = update.message.text.strip()
    await update.message.reply_text(
        f"⏳ *{sc(f'Searching for')}* *{name}*{sc('...')}",
        parse_mode="Markdown"
    )
    try:
        results = fetch_anime(name)
    except Exception:
        await update.message.reply_text(
            f"⏳ *{sc('API is slow. Please wait and try /anime again.')}*",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    if not results:
        await update.message.reply_text(
            f"❌ *{sc('No anime found. Try a different name.')}*",
            parse_mode="Markdown"
        )
        return ASK_ANIME
    ctx.user_data["results"] = results
    buttons = [
        [InlineKeyboardButton(
            f"{a.get('title_english') or a['title']} ({a.get('year') or '?'})",
            callback_data=str(i)
        )]
        for i, a in enumerate(results[:10])
    ]
    buttons.append([InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", callback_data="cancel")])
    await update.message.reply_text(
        f"📋 *{sc('Select the correct anime:')}*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return ASK_CONFIRM

async def anime_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "cancel":
        await query.edit_message_text(f"❌ *{sc('Cancelled.')}*", parse_mode="Markdown")
        return ConversationHandler.END
    anime = ctx.user_data["results"][int(query.data)]
    ctx.user_data["anime"] = anime
    ctx.user_data.pop("official_images", None)
    ctx.user_data.pop("official_index", None)
    title  = anime.get("title_english") or anime["title"]
    genres = ", ".join(g["name"] for g in anime.get("genres", [])[:3]) or "N/A"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 ᴜᴘʟᴏᴀᴅ", callback_data="photo_upload"),
         InlineKeyboardButton("🌐 ᴜsᴇ ᴏғғɪᴄɪᴀʟ", callback_data="photo_official")],
        [InlineKeyboardButton("❌ ᴄᴀɴᴄᴇʟ", callback_data="cancel")],
    ])
    await query.edit_message_text(
        f"✅ *{title}*\n🎭 {sc('Genres:')} {genres}\n\n"
        f"📸 *{sc('Send me the photo dear!')}*\n\n"
        f"*{sc('Choose how to get the background / character image:')}*",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )
    return ASK_PHOTO_CHOICE

async def photo_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    if query.data == "cancel":
        await query.edit_message_text(f"❌ *{sc('Cancelled.')}*", parse_mode="Markdown")
        return ConversationHandler.END
    if query.data == "photo_upload":
        await query.edit_message_text(
            f"📸 *{sc('Now send the background / character image for the poster:')}*",
            parse_mode="Markdown",
        )
        return ASK_PHOTO
    anime = ctx.user_data["anime"]
    title      = anime.get("title_english") or anime["title"]
    anilist_id = anime.get("anilist_id")
    mal_id     = anime.get("mal_id")
    await query.edit_message_text(
        f"🌐 *{sc(f'Fetching official art for')} {title}...*",
        parse_mode="Markdown"
    )
    images = await asyncio.to_thread(fetch_official_images, title, anilist_id, mal_id)
    ctx.user_data["official_images"] = images
    ctx.user_data["official_index"] = -1
    if not images:
        await query.message.reply_text(
            f"⚠️ *{sc('No official images found for this anime.')}*\n"
            f"*{sc('Please send the background / character image manually:')}*",
            parse_mode="Markdown",
        )
        return ASK_PHOTO
    orientation = STYLE_ORIENTATION.get(POSTER_STYLES[0][0], "any")
    idx, photo_bytes = await _pick_official_image(images, -1, orientation)
    if not photo_bytes:
        await query.message.reply_text(
            f"⚠️ *{sc('Failed to download official images.')}*\n"
            f"*{sc('Please send the background / character image manually:')}*",
            parse_mode="Markdown",
        )
        return ASK_PHOTO
    ctx.user_data["official_index"] = idx
    ctx.user_data["photo_bytes"] = photo_bytes
    ctx.user_data["style_index"] = 0
    try: await query.message.delete()
    except Exception: pass
    return await _send_style_preview(update.effective_chat.id, ctx)

async def received_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    track_user(update)
    photo = update.message.photo[-1] if update.message.photo else None
    doc   = update.message.document
    if not photo and not doc:
        await update.message.reply_text(
            f"⚠️ *{sc('Please send a photo or image file.')}*",
            parse_mode="Markdown"
        )
        return ASK_PHOTO
    file        = await ctx.bot.get_file(photo.file_id if photo else doc.file_id)
    photo_bytes = await file.download_as_bytearray()
    ctx.user_data["photo_bytes"] = bytes(photo_bytes)
    ctx.user_data["style_index"] = 0
    return await _send_style_preview(update.effective_chat.id, ctx)

async def style_navigate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    idx = ctx.user_data.get("style_index", 0)
    if query.data == "style_next": idx = (idx + 1) % len(POSTER_STYLES)
    elif query.data == "style_prev": idx = (idx - 1) % len(POSTER_STYLES)
    ctx.user_data["style_index"] = idx
    style_key, style_label, style_emoji = POSTER_STYLES[idx]
    anime = ctx.user_data["anime"]
    brand = get_user_brand(ctx, query.from_user.id)
    official_images = ctx.user_data.get("official_images")
    if official_images:
        orientation = STYLE_ORIENTATION.get(style_key, "any")
        cur_idx = ctx.user_data.get("official_index", -1)
        new_idx, new_bytes = await _pick_official_image(official_images, cur_idx, orientation)
        if new_bytes:
            ctx.user_data["official_index"] = new_idx
            ctx.user_data["photo_bytes"] = new_bytes
    photo_bytes = ctx.user_data["photo_bytes"]
    try:
        preview_bytes = _render_style_preview(anime, photo_bytes, brand, style_key)
    except Exception as e:
        await query.answer(f"{sc('Render failed:')} {e}", show_alert=True)
        return ASK_STYLE
    media = InputMediaPhoto(
        media=io.BytesIO(preview_bytes),
        caption=_build_preview_caption(style_label, style_emoji, idx, len(POSTER_STYLES)),
        parse_mode="Markdown",
    )
    try:
        await query.edit_message_media(media=media, reply_markup=_build_preview_keyboard(idx, len(POSTER_STYLES)))
    except Exception:
        await query.message.reply_photo(
            photo=io.BytesIO(preview_bytes),
            caption=_build_preview_caption(style_label, style_emoji, idx, len(POSTER_STYLES)),
            parse_mode="Markdown",
            reply_markup=_build_preview_keyboard(idx, len(POSTER_STYLES)),
        )
    return ASK_STYLE

async def style_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    idx = ctx.user_data.get("style_index", 0)
    style_key, style_label, style_emoji = POSTER_STYLES[idx]
    ctx.user_data["style"] = style_key
    buttons = [
        [
            InlineKeyboardButton(f"{THEMES[c]['emoji']} {sc(c.capitalize())}", callback_data=f"color_{c}")
            for c in list(THEMES.keys())[i:i+2]
        ]
        for i in range(0, len(THEMES), 2)
    ]
    try:
        await query.edit_message_caption(
            caption=f"{style_emoji} *{sc(style_label)}* {sc('selected!')}\n\n🎨 *{sc('Choose your poster color theme:')}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    except Exception:
        await query.message.reply_text(
            f"{style_emoji} *{sc(style_label)}* {sc('selected!')}\n\n🎨 *{sc('Choose your poster color theme:')}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    return ASK_COLOR

async def style_cancel_preview(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    try: await query.message.delete()
    except Exception: pass
    await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"❌ *{sc('Cancelled.')}*",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def color_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    theme_name = query.data.replace("color_", "")
    style      = ctx.user_data.get("style", "hex")
    ctx.user_data["theme"] = theme_name
    try: await query.message.delete()
    except Exception: pass
    status_msg = await ctx.bot.send_message(
        chat_id=query.message.chat_id,
        text=f"🎨 *{sc(f'Creating your {theme_name} poster, please wait...')}*",
        parse_mode="Markdown"
    )
    try:
        anime        = ctx.user_data["anime"]
        photo_bytes  = ctx.user_data["photo_bytes"]
        brand        = get_user_brand(ctx, query.from_user.id)
        poster_bytes = _build_poster(anime, photo_bytes, brand, style, theme_name)
        try: await status_msg.delete()
        except Exception: pass
        await ctx.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=io.BytesIO(poster_bytes),
            caption=_poster_caption(anime, theme_name),
            reply_markup=_build_next_image_keyboard(),
        )
    except Exception as e:
        try: await status_msg.edit_text(f"❌ *{sc('Failed to create poster:')}* {e}", parse_mode="Markdown")
        except Exception: await ctx.bot.send_message(chat_id=query.message.chat_id, text=f"❌ {sc('Failed:')} {e}")
        return ConversationHandler.END
    return ASK_NEXT_IMAGE

async def next_image(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    anime = ctx.user_data.get("anime")
    if not anime:
        await query.answer(sc("Session expired, please start again with /anime"), show_alert=True)
        return ConversationHandler.END
    title      = anime.get("title_english") or anime["title"]
    anilist_id = anime.get("anilist_id")
    mal_id     = anime.get("mal_id")
    style      = ctx.user_data.get("style", "hex")
    theme_name = ctx.user_data.get("theme", PREVIEW_THEME)
    brand      = get_user_brand(ctx, query.from_user.id)
    orientation = STYLE_ORIENTATION.get(style, "any")
    images = ctx.user_data.get("official_images")
    if images is None:
        images = await asyncio.to_thread(fetch_official_images, title, anilist_id, mal_id)
        ctx.user_data["official_images"] = images
    if not images:
        await query.answer(sc("No official images available for this anime."), show_alert=True)
        return ASK_NEXT_IMAGE
    cur_idx = ctx.user_data.get("official_index", -1)
    new_idx, photo_bytes = await _pick_official_image(images, cur_idx, orientation)
    if not photo_bytes:
        await query.answer(sc("No more images available for this anime."), show_alert=True)
        return ASK_NEXT_IMAGE
    if new_idx == cur_idx:
        await query.answer(sc("No other images available — this is the only one."), show_alert=True)
        return ASK_NEXT_IMAGE
    ctx.user_data["official_index"] = new_idx
    ctx.user_data["photo_bytes"] = photo_bytes
    try:
        poster_bytes = _build_poster(anime, photo_bytes, brand, style, theme_name)
    except Exception as e:
        await query.answer(f"{sc('Render failed:')} {e}", show_alert=True)
        return ASK_NEXT_IMAGE
    media = InputMediaPhoto(media=io.BytesIO(poster_bytes), caption=_poster_caption(anime, theme_name))
    try:
        await query.edit_message_media(media=media, reply_markup=_build_next_image_keyboard())
    except Exception:
        await query.message.reply_photo(
            photo=io.BytesIO(poster_bytes),
            caption=_poster_caption(anime, theme_name),
            reply_markup=_build_next_image_keyboard(),
        )
    return ASK_NEXT_IMAGE

async def skip_next_image(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    try: await query.edit_message_reply_markup(reply_markup=None)
    except Exception: pass
    return ConversationHandler.END

async def cmd_brand(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    track_user(update)
    if not await check_fsub(update, ctx): return ConversationHandler.END
    current = get_user_brand(ctx, update.effective_user.id)
    await update.message.reply_text(
        f"🏷️ *{sc('Current brand:')}* {current}\n\n*{sc('Send the new brand name:')}*",
        parse_mode="Markdown"
    )
    return ASK_BRAND

async def cmd_brand_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    track_user(update)
    if not await check_fsub(update, ctx): return ConversationHandler.END
    await update.callback_query.answer()
    current = get_user_brand(ctx, update.effective_user.id)
    await update.callback_query.message.reply_text(
        f"🏷️ *{sc('Current brand:')}* {current}\n\n*{sc('Send the new brand name:')}*",
        parse_mode="Markdown"
    )
    return ASK_BRAND

async def received_brand(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    new_brand = update.message.text.strip().upper()
    set_user_brand(ctx, update.effective_user.id, new_brand)
    await update.message.reply_text(
        f"✅ *{sc('Brand set to:')}* {new_brand}\n\n*{sc('This will be used in all your future posters.')}*",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"❌ *{sc('Cancelled.')}*", parse_mode="Markdown")
    return ConversationHandler.END

# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    set_on_verified(cmd_start)

    anime_conv = ConversationHandler(
        entry_points=[
            CommandHandler("anime", cmd_anime),
            CallbackQueryHandler(cmd_anime_callback, pattern="^cmd_anime$"),
        ],
        states={
            ASK_ANIME:        [MessageHandler(filters.TEXT & ~filters.COMMAND, received_anime_name)],
            ASK_CONFIRM:      [CallbackQueryHandler(anime_selected, pattern=r"^(cancel|\d+)$")],
            ASK_PHOTO_CHOICE: [CallbackQueryHandler(photo_choice, pattern="^(photo_upload|photo_official|cancel)$")],
            ASK_PHOTO:        [MessageHandler(filters.PHOTO | filters.Document.IMAGE, received_photo)],
            ASK_STYLE: [
                CallbackQueryHandler(style_navigate,      pattern="^style_(prev|next)$"),
                CallbackQueryHandler(style_pick,          pattern="^style_pick$"),
                CallbackQueryHandler(style_cancel_preview,pattern="^style_cancel_preview$"),
            ],
            ASK_COLOR:      [CallbackQueryHandler(color_selected, pattern="^color_")],
            ASK_NEXT_IMAGE: [
                CallbackQueryHandler(next_image,      pattern="^next_image$"),
                CallbackQueryHandler(skip_next_image, pattern="^skip_next_image$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False, per_chat=True, allow_reentry=True,
    )

    brand_conv = ConversationHandler(
        entry_points=[
            CommandHandler("brand", cmd_brand),
            CallbackQueryHandler(cmd_brand_callback, pattern="^cmd_brand$"),
        ],
        states={ASK_BRAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_brand)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False, per_chat=True,
    )

    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", cmd_broadcast)],
        states={
            ASK_BROADCAST: [
                MessageHandler(
                    (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL)
                    & ~filters.COMMAND,
                    received_broadcast,
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False, per_chat=True,
    )

    app.add_handler(anime_conv)
    app.add_handler(brand_conv)
    app.add_handler(broadcast_conv)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CallbackQueryHandler(fsub_retry_callback,    pattern="^fsub_check$"))
    app.add_handler(CallbackQueryHandler(show_commands_callback, pattern="^show_commands$"))
    app.add_handler(CallbackQueryHandler(cmd_cancel_callback,    pattern="^cmd_cancel$"))
    app.add_handler(CallbackQueryHandler(developer_callback,     pattern="^developer$"))
    app.add_handler(CallbackQueryHandler(back_start_callback,    pattern="^back_start$"))

    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
