from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    KeyboardButton, ReplyKeyboardMarkup,
    KeyboardButtonRequestChat,
)


def _kb(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t, callback_data=c) for t, c in row]
            for row in rows
        ]
    )


def main_menu_kb() -> InlineKeyboardMarkup:
    return _kb(
        [("📋 Группы", "groups")],
        [("🔍 Найти каналы", "search_channels"), ("📢 Найти группы", "search_groups")],
        [("📊 Поиск Telemetr", "search_telemetr")],
        [("✉️ Составить сообщение", "compose")],
        [("📤 Рассылка", "broadcast")],
        [("⚙️ Задержка", "settings_delay")],
        [("🚪 Выйти из аккаунта", "logout")],
    )


def groups_menu_kb() -> InlineKeyboardMarkup:
    return _kb(
        [("➕ Добавить", "group_add"), ("❌ Удалить", "group_remove")],
        [("◀️ Назад", "main_menu")],
    )


def compose_menu_kb(has_text: bool, has_photo: bool, has_buttons: bool) -> InlineKeyboardMarkup:
    rows = []
    rows.append([(f"✏️ Текст {'✅' if has_text else ''}".strip(), "compose_text")])

    if has_photo:
        rows.append([("🖼 Фото ✅", "compose_photo"), ("🗑 Удалить фото", "compose_clear_photo")])
    else:
        rows.append([("🖼 Добавить фото", "compose_photo")])

    if has_buttons:
        rows.append([("🔘 Кнопки ✅", "compose_buttons"), ("🗑 Удалить кнопки", "compose_clear_buttons")])
    else:
        rows.append([("🔘 Добавить кнопки", "compose_buttons")])

    if has_text or has_photo:
        rows.append([("👁 Предпросмотр", "compose_preview"), ("💾 Сохранить", "compose_save")])

    rows.append([("◀️ Назад", "main_menu")])
    return _kb(*rows)


def back_kb(callback: str = "main_menu") -> InlineKeyboardMarkup:
    return _kb([(("◀️ Назад", callback))])


def confirm_broadcast_kb() -> InlineKeyboardMarkup:
    return _kb(
        [("✅ Начать рассылку", "broadcast_start"), ("❌ Отмена", "main_menu")],
    )


def preview_buttons_kb(buttons: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=btn["text"], url=btn["url"]) for btn in row]
            for row in buttons
        ]
    )


def auth_method_kb() -> InlineKeyboardMarkup:
    return _kb(
        [("📱 Войти по QR-коду", "auth_qr")],
        [("📞 Войти по номеру телефона", "auth_phone")],
    )


def refresh_qr_kb() -> InlineKeyboardMarkup:
    return _kb(
        [("🔄 Обновить QR", "auth_refresh_qr")],
        [("📞 Войти по номеру", "auth_phone")],
    )


REQUEST_CHAT_KB = ReplyKeyboardMarkup(
    keyboard=[[
        KeyboardButton(
            text="📋 Выбрать группу/супергруппу",
            request_chat=KeyboardButtonRequestChat(
                request_id=1, chat_is_channel=False,
                request_title=True, request_username=True,
            ),
        ),
        KeyboardButton(
            text="📢 Выбрать канал",
            request_chat=KeyboardButtonRequestChat(
                request_id=2, chat_is_channel=True,
                request_title=True, request_username=True,
            ),
        ),
    ]],
    resize_keyboard=True,
    one_time_keyboard=True,
)
