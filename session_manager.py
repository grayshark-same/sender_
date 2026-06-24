"""Manages per-user Telethon clients."""
from telethon import TelegramClient
from telethon.sessions import StringSession
import database as db

# user_id → authorized TelegramClient
_clients: dict[int, TelegramClient] = {}

# user_id → TelegramClient in the middle of auth (not yet authorized)
_pending: dict[int, TelegramClient] = {}


async def get_client(user_id: int) -> TelegramClient | None:
    """Return authorized client or None."""
    if user_id in _clients:
        client = _clients[user_id]
        if client.is_connected():
            return client
        del _clients[user_id]

    user = await db.get_user(user_id)
    if not user or not user.get("session_string"):
        return None

    client = TelegramClient(
        StringSession(user["session_string"]),
        user["api_id"],
        user["api_hash"],
    )
    await client.connect()
    if await client.is_user_authorized():
        _clients[user_id] = client
        return client
    return None


async def create_pending(user_id: int, api_id: int, api_hash: str) -> TelegramClient:
    """Create an unauthenticated client for the login flow."""
    if user_id in _pending:
        try:
            await _pending[user_id].disconnect()
        except Exception:
            pass

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    _pending[user_id] = client
    return client


def get_pending(user_id: int) -> TelegramClient | None:
    return _pending.get(user_id)


async def finalize(user_id: int):
    """Move pending client → authorized pool and save session."""
    client = _pending.pop(user_id, None)
    if not client:
        return
    session_string = client.session.save()
    await db.save_session(user_id, session_string)
    _clients[user_id] = client


async def logout(user_id: int):
    for pool in (_clients, _pending):
        client = pool.pop(user_id, None)
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
    await db.logout_user(user_id)


async def send_to_chat(
    user_id: int,
    chat_id: str,
    text: str | None = None,
    photo_path: str | None = None,
    buttons=None,
):
    from telethon import Button

    client = await get_client(user_id)
    if not client:
        raise RuntimeError("Аккаунт не авторизован")

    tl_buttons = None
    if buttons:
        tl_buttons = [
            [Button.url(btn["text"], btn["url"]) for btn in row]
            for row in buttons
        ]

    # Числовые ID передаём как int, юзернеймы — как строку
    peer = int(chat_id) if chat_id.lstrip("-").isdigit() else chat_id

    if photo_path:
        await client.send_file(
            peer, photo_path,
            caption=text, parse_mode="html", buttons=tl_buttons,
        )
    else:
        await client.send_message(
            peer, text or "",
            parse_mode="html", buttons=tl_buttons, link_preview=False,
        )
