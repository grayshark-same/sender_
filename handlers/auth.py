import html
import asyncio
from io import BytesIO

import qrcode
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile, InputMediaPhoto
from aiogram.fsm.context import FSMContext
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    PhoneCodeExpiredError, PasswordHashInvalidError,
)

from states import AuthStates
from keyboards import main_menu_kb, auth_method_kb, refresh_qr_kb
import database as db
import session_manager as sm

router = Router()

# user_id → asyncio.Task (ожидание скана QR)
_qr_tasks: dict[int, asyncio.Task] = {}


# ── Вход / начало ─────────────────────────────────────────────────────────────

async def start_auth(target: Message, state: FSMContext):
    await state.set_state(AuthStates.waiting_for_api_id)
    await target.answer(
        "🔐 <b>Авторизация аккаунта</b>\n\n"
        "Шаг 1/2 — Отправь свой <b>API ID</b>\n\n"
        'Получить на <a href="https://my.telegram.org">my.telegram.org</a> → API development tools',
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(AuthStates.waiting_for_api_id)
async def receive_api_id(message: Message, state: FSMContext):
    try:
        api_id = int(message.text.strip())
        if not (1 <= api_id <= 2147483647):
            raise ValueError
    except ValueError:
        await message.answer("❌ API ID — это число (7-8 цифр). Проверь на my.telegram.org:")
        return
    await state.update_data(api_id=api_id)
    await state.set_state(AuthStates.waiting_for_api_hash)
    await message.answer("Шаг 2/2 — Отправь свой <b>API Hash</b>:", parse_mode="HTML")


@router.message(AuthStates.waiting_for_api_hash)
async def receive_api_hash(message: Message, state: FSMContext):
    api_hash = message.text.strip()
    if len(api_hash) != 32:
        await message.answer("❌ API Hash — 32 символа. Проверь и попробуй ещё раз:")
        return
    await state.update_data(api_hash=api_hash)
    await state.set_state(AuthStates.waiting_for_qr)
    await message.answer(
        "Выбери способ входа:",
        reply_markup=auth_method_kb(),
    )


# ── QR авторизация ────────────────────────────────────────────────────────────

def _make_qr_bytes(url: str) -> bytes:
    buf = BytesIO()
    qrcode.make(url).save(buf, format="PNG")
    return buf.getvalue()


async def _send_qr(target: Message, client, state: FSMContext, user_id: int):
    data = await state.get_data()
    qr_login = await client.qr_login()

    img = _make_qr_bytes(qr_login.url)
    sent = await target.answer_photo(
        BufferedInputFile(img, "qr.png"),
        caption=(
            "📱 <b>Отсканируй QR-код в Telegram:</b>\n\n"
            "Настройки → Устройства → Подключить устройство\n\n"
            "<i>Действителен ~30 секунд. Если истёк — нажми Обновить.</i>"
        ),
        parse_mode="HTML",
        reply_markup=refresh_qr_kb(),
    )

    # Отмена предыдущей задачи если была
    if user_id in _qr_tasks:
        _qr_tasks[user_id].cancel()

    async def _wait():
        try:
            await asyncio.wait_for(qr_login.wait(), timeout=28)
            # Успешно отсканировали
            await db.upsert_user(user_id, data["api_id"], data["api_hash"], phone=None)
            await sm.finalize(user_id)
            await state.clear()
            _qr_tasks.pop(user_id, None)
            await sent.answer("✅ <b>Аккаунт подключён!</b>", parse_mode="HTML", reply_markup=main_menu_kb())
        except SessionPasswordNeededError:
            _qr_tasks.pop(user_id, None)
            await state.set_state(AuthStates.waiting_for_password)
            await sent.answer("🔒 Включён 2FA. Отправь <b>пароль</b>:", parse_mode="HTML")
        except asyncio.TimeoutError:
            _qr_tasks.pop(user_id, None)
            try:
                await sent.edit_caption(
                    "❌ QR истёк. Нажми <b>Обновить</b> для нового.",
                    parse_mode="HTML",
                    reply_markup=refresh_qr_kb(),
                )
            except Exception:
                pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _qr_tasks.pop(user_id, None)
            await sent.answer(f"❌ Ошибка: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
            await state.clear()

    _qr_tasks[user_id] = asyncio.create_task(_wait())


@router.callback_query(F.data == "auth_qr")
async def cb_auth_qr(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    await state.set_state(AuthStates.waiting_for_qr)
    try:
        client = await sm.create_pending(user_id, data["api_id"], data["api_hash"])
        await callback.message.delete()
        await _send_qr(callback.message, client, state, user_id)
    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
        await state.clear()
    await callback.answer()


@router.callback_query(F.data == "auth_refresh_qr", AuthStates.waiting_for_qr)
async def cb_refresh_qr(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    client = sm.get_pending(user_id)
    if not client:
        await callback.message.edit_caption("❌ Сессия истекла. Напиши /start")
        await state.clear()
        await callback.answer()
        return

    data = await state.get_data()
    try:
        qr_login = await client.qr_login()
        img = _make_qr_bytes(qr_login.url)

        await callback.message.edit_media(
            InputMediaPhoto(
                media=BufferedInputFile(img, "qr.png"),
                caption=(
                    "📱 <b>Новый QR-код:</b>\n\n"
                    "Настройки → Устройства → Подключить устройство\n\n"
                    "<i>Действителен ~30 секунд.</i>"
                ),
                parse_mode="HTML",
            ),
            reply_markup=refresh_qr_kb(),
        )

        if user_id in _qr_tasks:
            _qr_tasks[user_id].cancel()

        sent = callback.message

        async def _wait():
            try:
                await asyncio.wait_for(qr_login.wait(), timeout=28)
                await db.upsert_user(user_id, data["api_id"], data["api_hash"], phone=None)
                await sm.finalize(user_id)
                await state.clear()
                _qr_tasks.pop(user_id, None)
                await sent.answer("✅ <b>Аккаунт подключён!</b>", parse_mode="HTML", reply_markup=main_menu_kb())
            except SessionPasswordNeededError:
                _qr_tasks.pop(user_id, None)
                await state.set_state(AuthStates.waiting_for_password)
                await sent.answer("🔒 Включён 2FA. Отправь <b>пароль</b>:", parse_mode="HTML")
            except asyncio.TimeoutError:
                _qr_tasks.pop(user_id, None)
                try:
                    await sent.edit_caption(
                        "❌ QR истёк. Нажми <b>Обновить</b>.",
                        parse_mode="HTML",
                        reply_markup=refresh_qr_kb(),
                    )
                except Exception:
                    pass
            except asyncio.CancelledError:
                pass
            except Exception as e:
                _qr_tasks.pop(user_id, None)
                await sent.answer(f"❌ Ошибка: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
                await state.clear()

        _qr_tasks[user_id] = asyncio.create_task(_wait())

    except Exception as e:
        await callback.message.answer(f"❌ Ошибка: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
    await callback.answer()


# ── Телефон (запасной вариант) ─────────────────────────────────────────────────

@router.callback_query(F.data == "auth_phone")
async def cb_auth_phone(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id in _qr_tasks:
        _qr_tasks.pop(user_id).cancel()
    await state.set_state(AuthStates.waiting_for_phone)
    await callback.message.answer(
        "📞 Отправь <b>номер телефона</b> (с кодом страны):\n"
        "Пример: <code>+79001234567</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AuthStates.waiting_for_phone)
async def receive_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    data = await state.get_data()
    user_id = message.from_user.id
    try:
        client = sm.get_pending(user_id) or await sm.create_pending(user_id, data["api_id"], data["api_hash"])
        result = await client.send_code_request(phone)
        await state.update_data(phone=phone, phone_code_hash=result.phone_code_hash)
        await state.set_state(AuthStates.waiting_for_code)
        await message.answer(
            "Отправь <b>код</b> из Telegram:\n"
            "<i>Введи без пробелов, например: </i><code>12345</code>\n\n"
            "Не пришёл? Напиши /sms",
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: <code>{html.escape(str(e))}</code>\n\nПопробуй /start", parse_mode="HTML")
        await state.clear()


@router.message(AuthStates.waiting_for_code, F.text == "/sms")
async def resend_sms(message: Message, state: FSMContext):
    data = await state.get_data()
    client = sm.get_pending(message.from_user.id)
    if not client:
        await message.answer("❌ Сессия истекла. /start")
        await state.clear()
        return
    try:
        result = await client.send_code_request(data["phone"], force_sms=True)
        await state.update_data(phone_code_hash=result.phone_code_hash)
        await message.answer("💬 Код отправлен <b>по SMS</b>:", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ Ошибка: <code>{html.escape(str(e))}</code>", parse_mode="HTML")


@router.message(AuthStates.waiting_for_code)
async def receive_code(message: Message, state: FSMContext):
    code = message.text.strip().replace(" ", "")
    data = await state.get_data()
    user_id = message.from_user.id
    client = sm.get_pending(user_id)
    if not client:
        await message.answer("❌ Сессия истекла. /start")
        await state.clear()
        return
    try:
        await client.sign_in(data["phone"], code, phone_code_hash=data["phone_code_hash"])
        await db.upsert_user(user_id, data["api_id"], data["api_hash"], data["phone"])
        await sm.finalize(user_id)
        await state.clear()
        await message.answer("✅ <b>Аккаунт подключён!</b>", parse_mode="HTML", reply_markup=main_menu_kb())
    except SessionPasswordNeededError:
        await state.set_state(AuthStates.waiting_for_password)
        await message.answer("🔒 Включён 2FA. Отправь <b>пароль</b>:", parse_mode="HTML")
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        await message.answer("❌ Неверный или просроченный код. Попробуй ещё раз:")
    except Exception as e:
        await message.answer(f"❌ Ошибка: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
        await state.clear()


@router.message(AuthStates.waiting_for_password)
async def receive_password(message: Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    client = sm.get_pending(user_id)
    if not client:
        await message.answer("❌ Сессия истекла. /start")
        await state.clear()
        return
    try:
        await client.sign_in(password=message.text.strip())
        await db.upsert_user(user_id, data["api_id"], data["api_hash"], data.get("phone"))
        await sm.finalize(user_id)
        await state.clear()
        await message.answer("✅ <b>Аккаунт подключён!</b>", parse_mode="HTML", reply_markup=main_menu_kb())
    except PasswordHashInvalidError:
        await message.answer("❌ Неверный пароль. Попробуй ещё раз:")
    except Exception as e:
        await message.answer(f"❌ Ошибка: <code>{html.escape(str(e))}</code>", parse_mode="HTML")
        await state.clear()


# ── Выход ─────────────────────────────────────────────────────────────────────

@router.callback_query(F.data == "logout")
async def cb_logout(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if user_id in _qr_tasks:
        _qr_tasks.pop(user_id).cancel()
    await state.clear()
    await sm.logout(user_id)
    await callback.message.edit_text("🚪 Аккаунт отключён. /start чтобы войти снова.")
