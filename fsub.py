"""
fsub.py — Force-Subscribe module for AnimeFlio Poster Bot
────────────────────────────────────────────────────────────────────────────
Handles checking whether a user has joined the required channel(s) before
they can use the bot, and shows a "Join Channel" prompt with a retry button
when they haven't.

USAGE in bot.py:

    from fsub import check_fsub, fsub_retry_callback, set_on_verified, FSUB_CHANNELS

    # In every entry-point handler (cmd_start, cmd_anime, etc.):
    async def cmd_start(update, ctx):
        if not await check_fsub(update, ctx):
            return          # fsub.py already sent the "join channel" message

        ... rest of your normal handler code ...

    # Tell fsub.py which function to call after a successful "Try Again" press
    # so it shows your real /start message instead of a generic "joined" text:
    set_on_verified(cmd_start)

    # Register the retry-button handler once in main():
    app.add_handler(CallbackQueryHandler(fsub_retry_callback, pattern="^fsub_check$"))

SETUP:
    1. Add your channel(s) to FSUB_CHANNELS below.
    2. Make sure your bot is an ADMIN in every channel listed (required for
       Telegram's getChatMember API to work).
    3. Set FSUB_IMAGE to any banner image URL, or leave it as None to send a
       text-only message instead of a photo.
    4. Call set_on_verified(cmd_start) once during setup so the retry button
       shows your real /start message instead of a plain "you can now /start" text.
"""

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import TelegramError

# ─── CONFIG ───────────────────────────────────────────────────────────────────
# Add one or more channels the user must join.
# - "id"       : the channel's @username (without @) OR numeric chat id (e.g. -1001234567890)
# - "name"     : display name shown in the message
# - "url"      : the invite link / public link shown on the button
# - "is_private": set True if it's a private channel needing an invite link
FSUB_CHANNELS = [
    {
        "id": "-1004395497747",          # ← replace with your channel username (no @)
        "name": "ᴀɴɪᴘᴏsᴛᴇʀ sᴜᴘᴘᴏʀᴛ",
        "url": "https://t.me/+1evoB5RTqhBmNDQ1",
        "is_private": True,
    },
    # ── Example: PRIVATE channel ──────────────────────────────────────────
    # Private channels have no public @username, so:
    #   • "id"  must be the numeric chat ID (starts with -100...)
    #   • "url" must be an invite link (Channel → Manage → Invite Links)
    # {
    #     "id": "-1001234567890",
    #     "name": "VIP Channel",
    #     "url": "https://t.me/+AbCdEfGhIjKlMnOp",   # invite link, NOT t.me/username
    #     "is_private": True,
    # },
]

# Optional banner image shown above the join message. Set to None to disable.
FSUB_IMAGE = "https://i.postimg.cc/zv2rXqgy/IMG-20260630-160350-583.jpg"

FSUB_TEXT = (
    ">» ᴘʟᴇᴀsᴇ ᴊᴏɪɴ {channels} ᴛᴏ ᴄᴏɴᴛɪɴᴜᴇ:\n\n"
    "ᴀғᴛᴇʀ ᴊᴏɪɴɪɴɢ, ᴄʟɪᴄᴋ *• Tʀʏ ᴀɢᴀɪɴ •* ʙᴜᴛᴛᴏɴ ᴀʙᴏᴠᴇ\\."
)

# ─── ON-VERIFIED HOOK ─────────────────────────────────────────────────────────
# Holds a reference to the handler (e.g. cmd_start) that should run right
# after the user successfully passes the fsub check via the retry button.
# Set this once from bot.py with set_on_verified(cmd_start) — avoids a
# circular import between bot.py and fsub.py.
_on_verified_handler = None

def set_on_verified(handler):
    """Register the function to call immediately after a successful join-check
    (e.g. your cmd_start), so the retry button shows the real welcome message
    instead of a generic 'you can now /start' text."""
    global _on_verified_handler
    _on_verified_handler = handler


# ─── INTERNAL HELPERS ─────────────────────────────────────────────────────────
async def _is_member(ctx: ContextTypes.DEFAULT_TYPE, channel_id: str, user_id: int) -> bool:
    """Check membership of a single channel. Returns True if joined."""
    try:
        chat_id = channel_id if str(channel_id).startswith("-") else f"@{channel_id}"
        member = await ctx.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in ("member", "administrator", "creator")
    except TelegramError:
        # If the bot isn't an admin in the channel, or the channel id is wrong,
        # Telegram raises an error. We fail "open" (treat as not joined) so the
        # admin notices the misconfiguration via the join prompt still showing.
        return False
    except Exception:
        return False


def _build_join_keyboard() -> InlineKeyboardMarkup:
    """Builds the inline keyboard with one button per channel + a retry button."""
    buttons = []
    for ch in FSUB_CHANNELS:
        buttons.append([InlineKeyboardButton(f"{ch['name']}", url=ch["url"])])
    buttons.append([InlineKeyboardButton("• Tʀʏ ᴀɢᴀɪɴ •", callback_data="fsub_check")])
    return InlineKeyboardMarkup(buttons)


def _build_join_text() -> str:
    names = ", ".join(f"*{ch['name']}*" for ch in FSUB_CHANNELS)
    return FSUB_TEXT.format(channels=names)


async def _send_join_prompt(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Sends the 'please join our channel' message, with photo if configured."""
    keyboard = _build_join_keyboard()
    text = _build_join_text()

    # Figure out the right chat/message to reply to, whether this came from
    # a normal message or a callback query (e.g. retry button).
    if update.callback_query:
        target_chat_id = update.callback_query.message.chat_id
    else:
        target_chat_id = update.effective_chat.id

    try:
        if FSUB_IMAGE:
            await ctx.bot.send_photo(
                chat_id=target_chat_id,
                photo=FSUB_IMAGE,
                caption=text,
                parse_mode="MarkdownV2",
                reply_markup=keyboard,
            )
        else:
            await ctx.bot.send_message(
                chat_id=target_chat_id,
                text=text,
                parse_mode="MarkdownV2",
                reply_markup=keyboard,
            )
    except TelegramError:
        # Fallback to plain text with no markdown if formatting/photo fails
        await ctx.bot.send_message(
            chat_id=target_chat_id,
            text="🔒 You must join our channel(s) to use this bot. Tap below to join.",
            reply_markup=keyboard,
        )


# ─── PUBLIC API ───────────────────────────────────────────────────────────────
async def check_fsub(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Call this at the top of any handler that should be gated.

    Returns:
        True  -> user has joined all required channels, handler should continue
        False -> user is missing membership; a join prompt has already been
                  sent, the calling handler should `return` immediately.
    """
    if not FSUB_CHANNELS:
        return True  # fsub disabled if no channels configured

    user = update.effective_user
    if user is None:
        return True  # safety: no user context (shouldn't normally happen)

    for ch in FSUB_CHANNELS:
        joined = await _is_member(ctx, ch["id"], user.id)
        if not joined:
            await _send_join_prompt(update, ctx)
            return False

    return True


async def fsub_retry_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    Handles the "🔄 I've Joined — Try Again" button.
    Re-checks membership; on success, deletes the join prompt and immediately
    runs the registered on-verified handler (e.g. cmd_start) so the user sees
    the real welcome message right away — no extra "you can now /start" text.
    """
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    still_missing = []
    for ch in FSUB_CHANNELS:
        joined = await _is_member(ctx, ch["id"], user.id)
        if not joined:
            still_missing.append(ch["name"])

    if not still_missing:
        try:
            await query.message.delete()
        except TelegramError:
            pass

        if _on_verified_handler is not None:
            try:
                # Run the real /start handler so the user sees the actual
                # welcome message immediately, instead of a generic text.
                await _on_verified_handler(update, ctx)
            except AttributeError:
                # Most common cause: the on_verified handler (e.g. cmd_start)
                # internally calls update.message.reply_xxx(...), but `update`
                # here comes from a callback query — update.message is None
                # in that context, so reply_xxx() raises AttributeError.
                # Fall back to a plain confirmation instead of crashing silently.
                await ctx.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="✅ *Thanks for joining!* You can now use the bot.\n\nSend /start to begin.",
                    parse_mode="Markdown",
                )
            except Exception:
                # Catch-all so a bug in the verified handler never leaves the
                # user stuck with no response at all.
                await ctx.bot.send_message(
                    chat_id=query.message.chat_id,
                    text="✅ *Thanks for joining!* You can now use the bot.\n\nSend /start to begin.",
                    parse_mode="Markdown",
                )
        else:
            # Fallback if bot.py never called set_on_verified()
            await ctx.bot.send_message(
                chat_id=query.message.chat_id,
                text="✅ *Thanks for joining!* You can now use the bot.\n\nSend /start to begin.",
                parse_mode="Markdown",
            )
    else:
        await query.answer("❌ You haven't joined all required channels yet.", show_alert=True)
