import html
import os
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from states import ComposeStates
from keyboards import compose_menu_kb, back_kb, preview_buttons_kb
import database as db

router = Router()

BUTTONS_HELP = (
    "<b>Формат кнопок</b> — каждая строка = одна строка кнопок:\n\n"
    "<code>Текст | https://url.com</code>\n"
    "<code>Кнопка 1 | https://a.com ; Кнопка 2 | https://b.com</code>\n\n"
    "Несколько кнопок в строке — разделяй <b>;</b>"
)


def _parse_buttons(raw: str) -> list | None:
    result = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        row = []
        for part in line.split(";"):
            part = part.strip()
            if "|" not in part:
                return None
            text, url = part.split("|", 1)
            text, url = text.strip(), url.strip()
            if not text or not url.startswith("http"):
                return None
            row.append({"text": text, "url": url})
        if row:
            result.append(row)
    return result or None


def _photo_path(user_id: int) -> str:
    return f"media/{user_id}/last_photo.jpg"


async def _show_compose(target, state: FSMContext, edit: bool = True):
    data = await state.get_data()
    has_text = bool(data.get("text"))
    photo_path = data.get("photo_path")
    has_photo = bool(photo_path and os.path.exists(photo_path))
    has_buttons = bool(data.get("buttons"))

    text = "✉️ <b>Составить сообщение</b>\n\n"
    if has_text:
        preview = data["text"][:200] + ("…" if len(data["text"]) > 200 else "")
        text += f"<b>Текст:</b>\n{preview}\n\n"
    if has_photo:
        text += "🖼 <b>Фото:</b> прикреплено\n\n"
    if has_buttons:
        count = sum(len(r) for r in data["buttons"])
        text += f"🔘 <b>Кнопок:</b> {count}\n\n"
    if not (has_text or has_photo or has_buttons):
        text += "<i>Ничего не добавлено.</i>"

    kb = compose_menu_kb(has_text, has_photo, has_buttons)
    if edit:
        await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "compose")
async def cb_compose(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data:
        saved = await db.get_message(callback.from_user.id)
        if any(saved.get(k) for k in ("text", "photo_path", "buttons")):
            await state.update_data(**saved)
    await _show_compose(callback.message, state, edit=True)


# ── Текст ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "compose_text")
async def cb_compose_text(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ComposeStates.waiting_for_text)
    await callback.message.edit_text(
        "✏️ Отправь текст сообщения. Поддерживается <b>HTML</b>:\n"
        "<code>&lt;b&gt;жирный&lt;/b&gt;</code>, <code>&lt;i&gt;курсив&lt;/i&gt;</code>, "
        "<code>&lt;a href='url'&gt;ссылка&lt;/a&gt;</code>",
        reply_markup=back_kb("compose"), parse_mode="HTML",
    )


@router.message(ComposeStates.waiting_for_text)
async def receive_text(message: Message, state: FSMContext):
    await state.update_data(text=message.html_text)
    await state.set_state(None)
    await _show_compose(message, state, edit=False)


# ── Фото ──────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "compose_photo")
async def cb_compose_photo(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ComposeStates.waiting_for_photo)
    await callback.message.edit_text(
        "🖼 Отправь фото:", reply_markup=back_kb("compose"),
    )


@router.message(ComposeStates.waiting_for_photo, F.photo)
async def receive_photo(message: Message, state: FSMContext, bot: Bot):
    path = _photo_path(message.from_user.id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    await bot.download(message.photo[-1], destination=path)
    await state.update_data(photo_path=path)
    await state.set_state(None)
    await _show_compose(message, state, edit=False)


@router.message(ComposeStates.waiting_for_photo)
async def receive_photo_wrong(message: Message):
    await message.answer("❌ Пришли именно фото (не файл).")


@router.callback_query(F.data == "compose_clear_photo")
async def cb_clear_photo(callback: CallbackQuery, state: FSMContext):
    await state.update_data(photo_path=None)
    await _show_compose(callback.message, state, edit=True)


# ── Кнопки ────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "compose_buttons")
async def cb_compose_buttons(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ComposeStates.waiting_for_buttons)
    await callback.message.edit_text(
        BUTTONS_HELP, reply_markup=back_kb("compose"), parse_mode="HTML",
    )


@router.message(ComposeStates.waiting_for_buttons)
async def receive_buttons(message: Message, state: FSMContext):
    buttons = _parse_buttons(message.text or "")
    if buttons is None:
        await message.answer(f"❌ Неверный формат.\n\n{BUTTONS_HELP}", parse_mode="HTML")
        return
    await state.update_data(buttons=buttons)
    await state.set_state(None)
    await _show_compose(message, state, edit=False)


@router.callback_query(F.data == "compose_clear_buttons")
async def cb_clear_buttons(callback: CallbackQuery, state: FSMContext):
    await state.update_data(buttons=None)
    await _show_compose(callback.message, state, edit=True)


# ── Предпросмотр ──────────────────────────────────────────────────────────────

@router.callback_query(F.data == "compose_preview")
async def cb_preview(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = data.get("text") or ""
    photo_path = data.get("photo_path")
    buttons = data.get("buttons")
    kb = preview_buttons_kb(buttons) if buttons else None

    try:
        if photo_path and os.path.exists(photo_path):
            await callback.message.answer_photo(
                FSInputFile(photo_path), caption=text or None,
                parse_mode="HTML", reply_markup=kb,
            )
        else:
            await callback.message.answer(
                text or "<i>(пусто)</i>", parse_mode="HTML",
                reply_markup=kb, disable_web_page_preview=True,
            )
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка предпросмотра: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
    await callback.answer()


# ── Сохранить ─────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "compose_save")
async def cb_save(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await db.save_message(
        callback.from_user.id,
        text=data.get("text"),
        photo_path=data.get("photo_path"),
        buttons=data.get("buttons"),
    )
    await callback.answer("✅ Сохранено!", show_alert=True)
    await _show_compose(callback.message, state, edit=True)
