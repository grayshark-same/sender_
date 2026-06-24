import html
from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardRemove, LinkPreviewOptions,
)
from aiogram.fsm.context import FSMContext
from states import GroupStates
from keyboards import groups_menu_kb, back_kb, REQUEST_CHAT_KB
import database as db
import session_manager as sm

router = Router()


async def _show_groups(target, user_id: int, edit: bool = False):
    groups = await db.get_groups(user_id)
    if groups:
        lines = []
        for g in groups:
            chat_id = g[1]
            title = g[2]
            if chat_id.startswith("@"):
                link = f'<a href="https://t.me/{chat_id[1:]}">{html.escape(title)}</a>'
            else:
                link = html.escape(title)
            lines.append(f"<code>{g[0]}</code>. {link} {chat_id}")
        text = f"<b>📋 Список групп ({len(groups)}):</b>\n\n" + "\n".join(lines)
    else:
        text = "<b>📋 Список групп пуст.</b>"

    no_preview = LinkPreviewOptions(is_disabled=True)
    if edit:
        await target.edit_text(text, reply_markup=groups_menu_kb(), parse_mode="HTML", link_preview_options=no_preview)
    else:
        await target.answer(text, reply_markup=groups_menu_kb(), parse_mode="HTML", link_preview_options=no_preview)


@router.callback_query(F.data == "groups")
async def cb_groups(callback: CallbackQuery):
    await _show_groups(callback.message, callback.from_user.id, edit=True)


@router.callback_query(F.data == "group_add")
async def cb_group_add(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GroupStates.waiting_for_chat_id)
    await callback.message.answer(
        "Выбери группу/канал кнопкой ниже или отправь <b>@username</b> / числовой <b>ID</b> вручную.\n\n"
        "<i>Твой аккаунт должен быть там участником.</i>",
        reply_markup=REQUEST_CHAT_KB,
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(GroupStates.waiting_for_chat_id, F.chat_shared)
async def receive_chat_shared(message: Message, state: FSMContext):
    chat = message.chat_shared
    user_id = message.from_user.id
    title = chat.title or str(chat.chat_id)
    chat_id_str = f"@{chat.username}" if chat.username else f"-100{abs(chat.chat_id)}"

    added = await db.add_group(user_id, chat_id_str, title)
    result = f"✅ <b>{title}</b> добавлена." if added else "⚠️ Эта группа уже в списке."

    await state.clear()
    await message.answer(result, reply_markup=ReplyKeyboardRemove(), parse_mode="HTML")
    await _show_groups(message, user_id)


@router.message(GroupStates.waiting_for_chat_id)
async def receive_group_id(message: Message, state: FSMContext):
    raw = message.text.strip()
    user_id = message.from_user.id
    client = await sm.get_client(user_id)

    if not client:
        await message.answer("❌ Аккаунт не авторизован. Напиши /start")
        await state.clear()
        return

    try:
        entity = await client.get_entity(raw)
        title = getattr(entity, "title", None) or getattr(entity, "first_name", raw)
        chat_id_str = f"@{entity.username}" if getattr(entity, "username", None) else f"-100{abs(entity.id)}"
        added = await db.add_group(user_id, chat_id_str, title)
        result = f"✅ <b>{title}</b> добавлена." if added else "⚠️ Эта группа уже в списке."
        await message.answer(result, parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Не удалось найти: <code>{html.escape(str(e))}</code>", parse_mode="HTML")

    await state.clear()
    await _show_groups(message, user_id)


@router.callback_query(F.data == "group_remove")
async def cb_group_remove(callback: CallbackQuery, state: FSMContext):
    groups = await db.get_groups(callback.from_user.id)
    if not groups:
        await callback.answer("Список групп пуст.", show_alert=True)
        return

    lines = "\n".join(f"<code>{g[0]}</code>. {g[2]}" for g in groups)
    await state.set_state(GroupStates.waiting_for_remove_id)
    await callback.message.edit_text(
        f"<b>Какую группу удалить?</b>\n\n{lines}\n\nОтправь номер (<code>ID</code>):",
        reply_markup=back_kb("groups"),
        parse_mode="HTML",
    )


@router.message(GroupStates.waiting_for_remove_id)
async def receive_remove_id(message: Message, state: FSMContext):
    user_id = message.from_user.id
    try:
        group_id = int(message.text.strip())
        removed = await db.remove_group(user_id, group_id)
        await message.answer("✅ Группа удалена." if removed else "❌ Группа с таким ID не найдена.")
    except ValueError:
        await message.answer("❌ Введи числовой ID.")

    await state.clear()
    await _show_groups(message, user_id)
