from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from config import ADMIN_IDS
import database as db

router = Router()
router.message.filter(F.from_user.id.in_(ADMIN_IDS))


@router.message(Command("grant"))
async def cmd_grant(message: Message):
    """
    /grant USER_ID        — бессрочный доступ
    /grant USER_ID 30     — доступ на 30 дней
    """
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /grant USER_ID [дней]")
        return
    try:
        user_id = int(parts[1])
        days = int(parts[2]) if len(parts) >= 3 else None
    except ValueError:
        await message.answer("❌ Неверный формат. /grant USER_ID [дней]")
        return

    await db.grant_subscription(user_id, days)
    label = f"на {days} дн." if days else "бессрочно"
    await message.answer(f"✅ Доступ выдан пользователю <code>{user_id}</code> ({label})", parse_mode="HTML")


@router.message(Command("revoke"))
async def cmd_revoke(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /revoke USER_ID")
        return
    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный USER_ID")
        return

    await db.revoke_subscription(user_id)
    await message.answer(f"✅ Доступ отозван у <code>{user_id}</code>", parse_mode="HTML")


@router.message(Command("users"))
async def cmd_users(message: Message):
    users = await db.get_all_users()
    if not users:
        await message.answer("Нет пользователей.")
        return

    lines = []
    for user_id, phone, is_auth, expires_at in users:
        status = "✅" if is_auth else "⛔"
        if expires_at == "no_sub":
            sub = "нет доступа"
        elif expires_at == "permanent":
            sub = "бессрочно"
        else:
            sub = expires_at[:10]  # только дата YYYY-MM-DD
        lines.append(f"{status} <code>{user_id}</code> {phone or '?'} | {sub}")

    await message.answer(
        f"<b>Пользователи ({len(users)}):</b>\n\n" + "\n".join(lines),
        parse_mode="HTML",
    )
