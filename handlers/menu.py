from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from keyboards import main_menu_kb
import database as db
import session_manager as sm
from config import ADMIN_IDS
from handlers.auth import start_auth

router = Router()


async def _check_and_route(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if not await db.has_subscription(user_id) and user_id not in ADMIN_IDS:
        await message.answer(
            "🔒 <b>Доступ не предоставлен.</b>\n\n"
            f"Свяжитесь с администратором для получения доступа.",
            parse_mode="HTML",
        )
        return

    client = await sm.get_client(user_id)
    if not client:
        await start_auth(message, state)
        return

    me = await client.get_me()
    name = f"{me.first_name or ''} {me.last_name or ''}".strip()
    await message.answer(
        f"👋 <b>Привет, {name}!</b>\n\nВыбери действие:",
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await _check_and_route(message, state)


@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "Главное меню:", reply_markup=main_menu_kb()
    )
