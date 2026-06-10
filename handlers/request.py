# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#   handlers/request.py — /request command
#   © AnimeTadka
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from aiogram import Router, Bot, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.enums import ChatType

from utils.messages import request_success_msg, unauthorised_msg, DIV2
from utils.keyboards import request_confirm_keyboard
from utils.state import is_group_authorised
from utils import db
from config import CREDIT_LINE, AUTO_DELETE_DELAY

router = Router()


def _mention(user) -> str:
    if user.username:
        return f"@{user.username}"
    return f"<a href='tg://user?id={user.id}'>{user.first_name}</a>"


async def _schedule(bot_msg: Message, user_msg_id: int | None = None):
    try:
        await db.schedule_deletion(
            chat_id=bot_msg.chat.id,
            bot_message_id=bot_msg.message_id,
            user_message_id=user_msg_id,
            delay_seconds=AUTO_DELETE_DELAY
        )
    except Exception:
        pass


@router.message(Command("request"))
async def cmd_request(message: Message, bot: Bot):
    if message.chat.type == ChatType.PRIVATE:
        sent = await message.reply(
            f"✦ ara ara~ you found me in private~\n◈ how bold~ but i only work in groups~\n"
            f"<i>{CREDIT_LINE}</i>",
            parse_mode="HTML"
        )
        await _schedule(sent, message.message_id)
        return

    if not is_group_authorised(message.chat.id):
        sent = await message.reply(
            unauthorised_msg(_mention(message.from_user)),
            parse_mode="HTML"
        )
        await _schedule(sent, message.message_id)
        return

    user    = message.from_user
    mention = _mention(user)

    # ── Determine anime name ───────────────────────
    # Priority order:
    # 1. Text after /request (e.g. /request Naruto)
    # 2. Replied-to message text (user replied to a message with /request)

    parts = message.text.split(maxsplit=1)
    anime = parts[1].strip() if len(parts) >= 2 and parts[1].strip() else None

    if not anime and message.reply_to_message:
        # Use the text of the message being replied to
        replied = message.reply_to_message
        anime = (replied.text or replied.caption or "").strip()
        # Strip any leading bot commands from the replied text
        if anime.startswith("/"):
            anime = anime.split(maxsplit=1)[-1].strip() if " " in anime else ""

    if not anime:
        sent = await message.reply(
            f"◈ ara~ give me a name~\n"
            f"✦ usage: <b>/request anime name</b>\n"
            f"◇ or reply to any message with /request~",
            parse_mode="HTML"
        )
        await _schedule(sent, message.message_id)
        return

    await db.add_request(
        user.id,
        user.username or "unknown",
        anime,
        message.chat.id,
        message.chat.title or "Unknown"
    )

    sent = await message.reply(
        request_success_msg(mention, anime),
        parse_mode="HTML",
        reply_markup=request_confirm_keyboard()
    )
    await _schedule(sent, message.message_id)


@router.callback_query(F.data == "req_prompt")
async def req_prompt(callback: CallbackQuery):
    await callback.answer(
        "◈ use /request <anime name> to submit~",
        show_alert=True
    )
