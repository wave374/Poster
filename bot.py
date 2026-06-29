import os
import io
import time
import threading
import re
import math
import textwrap
import json
import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

# ── Dummy HTTP server ──
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

# ─── CONFIG ───────────────────────────────────────────────────────────[...]
BOT_TOKEN  = "8955163269:AAHuq5mCGQZlPaoDdiTJAtBSFeelgz74sAU"
BRAND_NAME = "ANIMEFLIO"
JIKAN_API  = "https://api.jikan.moe/v4"
OWNER_ID   = 7115720502  # Replace with your Telegram user ID
USERS_FILE = "users.json"

ASK_ANIME, ASK_CONFIRM, ASK_PHOTO, ASK_STYLE, ASK_COLOR, ASK_BRAND = range(6)

# ─── COLOR THEMES ─────────────────────────────────────────────────────────[...]
THEMES = {
    "green":  {"accent": (34, 197, 94),  "bg": (13, 26, 13),  "hex_out": (30, 55, 30),  "hex_fill": (13, 22, 13), "emoji": "🟢"},
    "orange": {"accent": (251, 146, 60), "bg": (26, 16, 8),   "hex_out": (55, 30, 10),  "hex_fill": (22, 13, 6),  "emoji": "🟠"},
    "cyan":   {"accent": (34, 211, 238), "bg": (8, 22, 26),   "hex_out": (10, 45, 55),  "hex_fill": (6, 18, 22),  "emoji": "🔵"},
    "red":    {"accent": (239, 68, 68),  "bg": (26, 10, 10),  "hex_out": (55, 15, 15),  "hex_fill": (22, 8, 8),   "emoji": "🔴"},
    "purple": {"accent": (168, 85, 247), "bg": (18, 10, 26),  "hex_out": (40, 20, 55),  "hex_fill": (15, 8, 22),  "emoji": "🟣"},
    "blue":   {"accent": (59, 130, 246), "bg": (8, 14, 26),   "hex_out": (15, 30, 55),  "hex_fill": (6, 12, 22),  "emoji": "💙"},
    "pink":   {"accent": (236, 72, 153), "bg": (26, 8, 18),   "hex_out": (55, 15, 40),  "hex_fill": (22, 6, 16),  "emoji": "🩷"},
    "yellow": {"accent": (234, 179, 8),  "bg": (26, 22, 5),   "hex_out": (55, 48, 10),  "hex_fill": (22, 19, 4),  "emoji": "🟡"},
    "white":  {"accent": (255, 255, 255),"bg": (20, 20, 20),  "hex_out": (180,180,180), "hex_fill": (35, 35, 35), "emoji": "⚪"},
}

GOLD  = (212, 168, 85)
WHITE = (255, 255, 255)
GRAY  = (180, 180, 180)
BLACK = (0, 0, 0)
W, H  = 1280, 720

# ─── USER TRACKING ────────────────────────────────────────────────────────[...]
def load_users():
    """Load users from JSON file."""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_users(users):
    """Save users to JSON file."""
    try:
        with open(USERS_FILE, 'w') as f:
            json.dump(users, f, indent=2)
    except Exception as e:
        print(f"Error saving users: {e}")

def track_user(user_id, user_name):
    """Track a new or existing user."""
    users = load_users()
    user_id_str = str(user_id)
    if user_id_str not in users:
        users[user_id_str] = {
            "user_id": user_id,
            "username": user_name,
            "first_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
            "last_seen": time.strftime("%Y-%m-%d %H:%M:%S"),
            "interaction_count": 1
        }
    else:
        users[user_id_str]["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S")
        users[user_id_str]["interaction_count"] += 1
    save_users(users)

# ─── FONT LOADER ──────────────────────────────────────────────────────────[...]
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

# ─── SEASON EXTRACTOR ─────────────────────────────────────────────────────────
def extract_season(title):
    match = re.search(r'\b(season\s*\d+|\d+(?:st|nd|rd|th)\s*season)\b',
                      title, flags=re.IGNORECASE)
    if match:
        num = re.search(r'\d+', match.group(0)).group(0)
        clean = re.sub(r'\s*\b(season\s*\d+|\d+(?:st|nd|rd|th)\s*season)\b',
                       '', title, flags=re.IGNORECASE).strip()
        return clean, f"SEASON {num}"
    return title, None

# ─── HEX GRID ───────────────────────────────────────────────────────────[...]
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

# ══════════════════════════════════════════════════════════════════[...]
# STYLE 1 — Classic Hex
# ══════════════════════════════════════════════════════════════════[...]
def build_poster_hex(anime, photo_bytes, brand, theme_name="green"):
    theme   = THEMES.get(theme_name, THEMES["green"])
    ACCENT  = theme["accent"]
    BG_DARK = theme["bg"]

    title    = anime.get("title_english") or anime.get("title", "UNKNOWN")
    genres   = [g["name"].upper() for g in anime.get("genres", [])][:3]
    synopsis = anime.get("synopsis") or "No synopsis available."
    clean_title, season_text = extract_season(title)

    base = Image.new("RGB", (W, H), BG_DARK)
    draw_hex_grid(ImageDraw.Draw(base), W, H, theme["hex_out"], theme["hex_fill"])

    char_img = Image.open(io.BytesIO(photo_bytes)).convert("RGBA")
    char_w   = int(W * 0.62)
    scale    = H / char_img.height
    new_w    = int(char_img.width * scale)
    char_img = char_img.resize((new_w, H), Image.LANCZOS)
    if new_w > char_w:
        char_img = char_img.crop(((new_w-char_w)//2, 0, (new_w-char_w)//2+char_w, H))
    elif new_w < char_w:
        padded = Image.new("RGBA", (char_w, H), (0,0,0,0))
        padded.paste(char_img, ((char_w-new_w)//2, 0))
        char_img = padded

    fade_mask = Image.new("L", (char_w, H), 0)
    fade_zone = int(char_w * 0.55)
    for x in range(char_w):
        alpha = int(255 * ((x/fade_zone)**2.2)) if x < fade_zone else 255
        ImageDraw.Draw(fade_mask).line([(x,0),(x,H)], fill=alpha)

    char_rgba = char_img.convert("RGBA")
    r, g, b, a = char_rgba.split()
    a = Image.composite(a, Image.new("L", a.size, 0), fade_mask)
    char_rgba = Image.merge("RGBA", (r, g, b, a))
    base_rgba = base.convert("RGBA")
    base_rgba.paste(char_rgba, (W-char_w, 0), char_rgba)
    base = base_rgba.convert("RGB")

    overlay = Image.new("RGBA", (W, H), (0,0,0,0))
    ov_draw = ImageDraw.Draw(overlay)
    for x in range(int(W*0.52)):
        alpha = int(180*(1-x/(W*0.52))**0.5)
        ov_draw.line([(x,0),(x,H)], fill=(BG_DARK[0],BG_DARK[1],BG_DARK[2],alpha))
    base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(base)

    logo_cx, logo_cy, logo_r = 30, 30, 20
    hex_pts = [(logo_cx+logo_r*math.cos(math.radians(60*i-30)),
                logo_cy+logo_r*math.sin(math.radians(60*i-30))) for i in range(6)]
    draw.polygon(hex_pts, outline=ACCENT, fill=BG_DARK)
    draw.text((logo_cx, logo_cy), brand[0].upper(), font=load_font(20,True), fill=ACCENT, anchor="mm")
    draw.text((58, 18), brand.upper(), font=load_font(17,True), fill=WHITE)

    title_upper = clean_title.upper()
    f_title = load_font(96, True)
    max_w = int(W*0.48)
    while f_title.size > 40:
        if draw.textbbox((0,0), title_upper, font=f_title)[2] <= max_w: break
        f_title = load_font(f_title.size-6, True)
    ty = int(H*0.28)
    draw.text((38, ty), title_upper, font=f_title, fill=WHITE)
    title_bottom = draw.textbbox((38, ty), title_upper, font=f_title)[3]

    if season_text:
        f_season = load_font(int(f_title.size*0.55), True)
        draw.text((38, title_bottom+6), season_text, font=f_season, fill=ACCENT)
        title_bottom = draw.textbbox((38, title_bottom+6), season_text, font=f_season)[3]

    gy, gx = title_bottom+20, 38
    f_genre = load_font(16, True)
    for gen in genres:
        draw.text((gx, gy), gen, font=f_genre, fill=GOLD)
        gx += draw.textbbox((0,0), gen, font=f_genre)[2]+28

    f_syn = load_font(15)
    syn_clean = re.sub(r'\[.*?\]|\(.*?\)', '', synopsis).strip()
    wrapped = textwrap.wrap(syn_clean, width=48)
    sy = gy+36
    for line in wrapped[:6]:
        draw.text((38, sy), line, font=f_syn, fill=GRAY)
        sy += 24
    if len(wrapped) > 6:
        draw.text((38, sy), "...read more", font=f_syn, fill=ACCENT)
        sy += 24

    btn_y = sy+18
    f_btn = load_font(16, True)
    for i, label in enumerate(["DOWNLOAD", "JOIN NOW"]):
        bx = 38+i*220
        bw, bh = 195, 48
        draw.rounded_rectangle([bx,btn_y,bx+bw,btn_y+bh], radius=5, fill=ACCENT)
        tw = draw.textbbox((0,0), label, font=f_btn)[2]
        draw.text((bx+(bw-tw)//2, btn_y+14), label, font=f_btn, fill=BLACK)

    out = io.BytesIO()
    base.save(out, format="JPEG", quality=95)
    out.seek(0)
    return out.read()               

# ─── HANDLERS ──────────────────────────────────────────────────────────[...]
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.username or update.effective_user.first_name
    track_user(user_id, user_name)
    
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
    """Show bot users statistics (owner only)."""
    user_id = update.effective_user.id
    
    # DEBUG: Print IDs to console for troubleshooting
    print(f"DEBUG: User ID = {user_id} (type: {type(user_id)}), Owner ID = {OWNER_ID} (type: {type(OWNER_ID)})")
    
    # Check if user is owner
    if int(user_id) != int(OWNER_ID):
        await update.message.reply_text(
            "❌ *Access Denied*\n\nThis command is only available to the bot owner.",
            parse_mode="Markdown"
        )
        return
    
    users = load_users()
    total_users = len(users)
    
    if total_users == 0:
        await update.message.reply_text(
            "📊 *No users tracked yet.*\n\nUsers will appear after they use the /anime command.",
            parse_mode="Markdown"
        )
        return
    
    # Calculate statistics
    total_interactions = sum(user.get("interaction_count", 0) for user in users.values())
    
    # Build user list (limited to first 20 to avoid message being too long)
    user_list = list(users.values())[:20]
    user_details = ""
    for i, user in enumerate(user_list, 1):
        username = user.get("username", "Unknown")
        interactions = user.get("interaction_count", 0)
        first_seen = user.get("first_seen", "N/A")
        user_details += f"{i}. @{username} — {interactions} interaction(s) (Since {first_seen})\n"
    
    if len(users) > 20:
        user_details += f"\n... and {len(users) - 20} more users"
    
    stats_text = (
        f"📊 *Bot Usage Statistics*\n\n"
        f"👥 *Total Users:* {total_users}\n"
        f"💬 *Total Interactions:* {total_interactions}\n"
        f"📈 *Avg per User:* {total_interactions // total_users if total_users > 0 else 0}\n\n"
        f"*Recent Users:*\n{user_details}"
    )
    
    await update.message.reply_text(stats_text, parse_mode="Markdown")

async def show_commands_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    query = update.callback_query
    await query.answer()
    ctx.user_data.clear()
    await query.message.reply_text(
        "🔍 Eɴᴛᴇʀ ᴛʜᴇ *ᴀɴɪᴍᴇ ɴᴀᴍᴇ* ʏᴏᴜ ᴡᴀɴᴛ ᴛᴏ ᴄʀᴇᴀᴛᴇ ᴀ ᴘᴏsᴛᴇʀ ғᴏʀ:",
        parse_mode="Markdown"
    )
    return ASK_ANIME

async def cmd_anime(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.username or update.effective_user.first_name
    track_user(user_id, user_name)
    
    ctx.user_data.clear()
    await update.message.reply_text(
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
        brand       = ctx.user_data.get("brand", BRAND_NAME)

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

# ─── MAIN ─────────────────────────────────────────────────────────────[...]
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    anime_conv = ConversationHandler(
        entry_points=[
            CommandHandler("anime", cmd_anime),
            # FIX: cmd_anime_callback is an entry point so it can start conversation
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
    # These must be registered AFTER conversation handlers
    app.add_handler(CallbackQueryHandler(show_commands_callback, pattern="^show_commands$"))
    app.add_handler(CallbackQueryHandler(cmd_cancel_callback,    pattern="^cmd_cancel$"))
    app.add_handler(CallbackQueryHandler(developer_callback,     pattern="^developer$"))
    app.add_handler(CallbackQueryHandler(back_start_callback,    pattern="^back_start$"))

    print("🤖 Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
