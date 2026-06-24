import asyncio
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from states import BroadcastStates
from keyboards import confirm_broadcast_kb, main_menu_kb, back_kb
import database as db
import session_manager as sm

router = Router()


@router.callback_query(F.data == "broadcast")
async def cb_broadcast(callback: CallbackQuery):
    user_id = callback.from_user.id
    msg = await db.get_message(user_id)
    groups = await db.get_groups(user_id)
    delay = await db.get_setting(user_id, "delay", "2")

    if not (msg.get("text") or msg.get("photo_path")):
        await callback.answer("❌ Нет сохранённого сообщения.", show_alert=True)
        return
    if not groups:
        await callback.answer("❌ Список групп пуст.", show_alert=True)
        return

    preview = (msg.get("text") or "")[:150]
    photo_str = "🖼 Фото: да\n" if msg.get("photo_path") else ""
    btn_count = sum(len(r) for r in msg["buttons"]) if msg.get("buttons") else 0
    btn_str = f"🔘 Кнопок: {btn_count}\n" if btn_count else ""

    await callback.message.edit_text(
        f"<b>📤 Рассылка</b>\n\n"
        f"<b>Групп:</b> {len(groups)}\n"
        f"<b>Задержка:</b> {delay} сек.\n"
        f"{photo_str}{btn_str}\n"
        f"<b>Текст:</b>\n{preview}{'…' if len(msg.get('text') or '') > 150 else ''}",
        reply_markup=confirm_broadcast_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "broadcast_start")
async def cb_broadcast_start(callback: CallbackQuery):
    user_id = callback.from_user.id
    groups = await db.get_groups(user_id)
    msg = await db.get_message(user_id)
    delay = float(await db.get_setting(user_id, "delay", "2"))

    status = await callback.message.edit_text(f"⏳ Начинаю рассылку в {len(groups)} групп...")

    ok, fail = 0, 0
    errors = []

    for i, (gid, chat_id, title) in enumerate(groups, 1):
        try:
            await sm.send_to_chat(
                user_id=user_id,
                chat_id=chat_id,
                text=msg.get("text"),
                photo_path=msg.get("photo_path"),
                buttons=msg.get("buttons"),
            )
            ok += 1
        except Exception as e:
            fail += 1
            errors.append(f"• {title}: {e}")

        try:
            await status.edit_text(f"⏳ {i}/{len(groups)} — ✅ {ok} ❌ {fail}")
        except Exception:
            pass

        if i < len(groups):
            await asyncio.sleep(delay)

    result = f"<b>✅ Рассылка завершена!</b>\n\nУспешно: {ok}\nОшибок: {fail}"
    if errors:
        result += "\n\n<b>Ошибки:</b>\n" + "\n".join(errors[:10])

    await status.edit_text(result, reply_markup=main_menu_kb(), parse_mode="HTML")


@router.callback_query(F.data == "settings_delay")
async def cb_settings_delay(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    delay = await db.get_setting(user_id, "delay", "2")
    await state.set_state(BroadcastStates.waiting_for_delay)
    await callback.message.edit_text(
        f"⚙️ <b>Задержка между отправками</b>\n\nТекущая: <b>{delay} сек.</b>\n\n"
        "Отправь новое значение (например <code>3</code> или <code>0.5</code>):",
        reply_markup=back_kb("main_menu"),
        parse_mode="HTML",
    )


@router.message(BroadcastStates.waiting_for_delay)
async def receive_delay(message: Message, state: FSMContext):
    try:
        value = float(message.text.strip().replace(",", "."))
        if value < 0:
            raise ValueError
        await db.set_setting(message.from_user.id, "delay", str(value))
        await state.clear()
        await message.answer(
            f"✅ Задержка: <b>{value} сек.</b>",
            reply_markup=main_menu_kb(), parse_mode="HTML",
        )
    except ValueError:
        await message.answer("❌ Введи положительное число, например <code>2</code>", parse_mode="HTML")
