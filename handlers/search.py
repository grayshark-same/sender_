import asyncio
import logging

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions
from aiogram.fsm.context import FSMContext
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import UpdateDialogFilterRequest, GetDialogFiltersRequest
from telethon.tl.types import Channel, DialogFilter, InputPeerChannel

from states import SearchStates
from keyboards import back_kb, main_menu_kb
import database as db
import session_manager as sm

router = Router()

MAX_RESULTS = 20
MAX_GROUP_RESULTS = 50  # собираем больше через несколько запросов


def _channels_kb(results: list[dict], selected: set[int]) -> InlineKeyboardMarkup:
    rows = []
    for i, ch in enumerate(results):
        check = "✅" if i in selected else "☑️"
        rows.append([InlineKeyboardButton(
            text=f"{check} {ch['title'][:35]}",
            callback_data=f"sch_toggle:{i}",
        )])
    rows.append([
        InlineKeyboardButton(text="💾 Добавить выбранные", callback_data="sch_save"),
        InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _groups_kb(results: list[dict], selected: set[int]) -> InlineKeyboardMarkup:
    rows = []
    for i, g in enumerate(results):
        check = "✅" if i in selected else "☑️"
        members = f"{g['members']:,}".replace(",", " ")
        writable = "✍️" if g["can_write"] else "🔒"
        rows.append([InlineKeyboardButton(
            text=f"{check} {writable} {g['title'][:24]} · {members}",
            callback_data=f"grp_toggle:{i}",
        )])
    rows.append([
        InlineKeyboardButton(text="✅ Выбрать все", callback_data="grp_all"),
        InlineKeyboardButton(text="❌ Сбросить", callback_data="grp_none"),
    ])
    rows.append([
        InlineKeyboardButton(text="🚀 Вступить и добавить", callback_data="grp_join"),
        InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Поиск каналов ─────────────────────────────────────────────────────────────

@router.callback_query(F.data == "search_channels")
async def cb_search_channels(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SearchStates.waiting_for_query)
    await callback.message.edit_text(
        "🔍 <b>Поиск каналов</b>\n\nОтправь ключевое слово или тематику:",
        reply_markup=back_kb("main_menu"),
        parse_mode="HTML",
    )


@router.message(SearchStates.waiting_for_query)
async def receive_channel_query(message: Message, state: FSMContext):
    await _do_search(message, state, groups_only=False)


# ── Поиск групп для рекламы ───────────────────────────────────────────────────

@router.callback_query(F.data == "search_groups")
async def cb_search_groups(callback: CallbackQuery, state: FSMContext):
    await state.set_state(SearchStates.waiting_for_group_query)
    await callback.message.edit_text(
        "📢 <b>Поиск групп для рекламы</b>\n\n"
        "Отправь тематику (например: <code>бизнес</code>, <code>крипто</code>, <code>мемы</code>):",
        reply_markup=back_kb("main_menu"),
        parse_mode="HTML",
    )


@router.message(SearchStates.waiting_for_group_query)
async def receive_group_query(message: Message, state: FSMContext):
    await state.update_data(group_query=message.text.strip())
    await state.set_state(SearchStates.waiting_for_min_members)
    await message.answer(
        "👥 Минимальное количество участников?\n\n"
        "Отправь число или <b>0</b> для без ограничений:",
        parse_mode="HTML",
    )


@router.message(SearchStates.waiting_for_min_members)
async def receive_min_members(message: Message, state: FSMContext):
    try:
        min_members = int(message.text.strip().replace(" ", ""))
    except ValueError:
        await message.answer("❌ Введи число, например <code>1000</code>", parse_mode="HTML")
        return

    data = await state.get_data()
    await state.update_data(min_members=min_members)
    await _do_search(message, state, groups_only=True, query=data["group_query"], min_members=min_members)


def _query_variants(q: str) -> list[str]:
    """Генерирует вариации запроса для расширенного поиска групп."""
    variants = [q]
    words = q.split()
    # Добавляем отдельные слова если запрос составной
    if len(words) > 1:
        variants.extend(words)
    # Добавляем популярные суффиксы/префиксы
    variants += [f"{q} чат", f"{q} группа", f"чат {q}"]
    # Убираем дубли, сохраняем порядок
    seen = set()
    result = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            result.append(v)
    return result[:6]  # максимум 6 запросов


async def _multi_search_groups(client, query: str, min_members: int) -> list[Channel]:
    """Параллельный поиск групп по нескольким вариациям запроса."""
    variants = _query_variants(query)

    async def fetch(q: str) -> list[Channel]:
        try:
            result = await client(SearchRequest(q=q, limit=MAX_RESULTS))
            return [
                ch for ch in result.chats
                if isinstance(ch, Channel)
                and ch.megagroup
                and (min_members == 0 or (getattr(ch, "participants_count", 0) or 0) >= min_members)
            ]
        except Exception:
            return []

    results = await asyncio.gather(*[fetch(v) for v in variants])

    # Объединяем, убираем дубли по id
    seen_ids: set[int] = set()
    merged: list[Channel] = []
    for batch in results:
        for ch in batch:
            if ch.id not in seen_ids:
                seen_ids.add(ch.id)
                merged.append(ch)

    # Сортируем по числу участников (больше — выше)
    merged.sort(key=lambda ch: getattr(ch, "participants_count", 0) or 0, reverse=True)
    return merged[:MAX_GROUP_RESULTS]


async def _do_search(
    message: Message,
    state: FSMContext,
    groups_only: bool,
    query: str = None,
    min_members: int = 0,
):
    user_id = message.from_user.id
    client = await sm.get_client(user_id)
    if not client:
        await message.answer("❌ Аккаунт не авторизован. /start")
        await state.clear()
        return

    q = query or message.text.strip()
    wait_msg = await message.answer("⏳ Ищу...")

    try:
        if groups_only:
            chats = await _multi_search_groups(client, q, min_members)
        else:
            result = await client(SearchRequest(q=q, limit=MAX_RESULTS))
            chats = [ch for ch in result.chats if isinstance(ch, Channel) and not ch.megagroup]

        if not chats:
            await wait_msg.edit_text(
                "😔 Ничего не найдено. Попробуй другой запрос или снизь минимум участников.",
                reply_markup=back_kb("main_menu"),
            )
            await state.clear()
            return

        if groups_only:
            groups = []
            for ch in chats:
                members = getattr(ch, "participants_count", 0) or 0
                # Проверяем можно ли писать
                banned = getattr(ch, "default_banned_rights", None)
                can_write = not (banned and getattr(banned, "send_messages", False))
                chat_id = f"@{ch.username}" if ch.username else f"-100{ch.id}"
                groups.append({
                    "title": ch.title,
                    "chat_id": chat_id,
                    "members": members,
                    "can_write": can_write,
                })

            await state.update_data(groups=groups, selected=[])
            await state.set_state(SearchStates.selecting_groups)

            writable = sum(1 for g in groups if g["can_write"])
            lines = [
                f"📢 <b>Найдено групп: {len(groups)}</b>",
                f"✍️ Можно писать: {writable} | 🔒 Закрыты: {len(groups) - writable}",
                "",
            ]
            for i, g in enumerate(groups):
                writable_icon = "✍️" if g["can_write"] else "🔒"
                members = f"{g['members']:,}".replace(",", " ")
                chat_id = g["chat_id"]
                if chat_id.startswith("@"):
                    link = f'<a href="https://t.me/{chat_id[1:]}">{g["title"]}</a>'
                else:
                    link = g["title"]
                lines.append(f"{i+1}. {writable_icon} {link} · {members}")
            lines.append("\nВыбери группы для вступления:")
            text = "\n".join(lines)
            await wait_msg.edit_text(text, reply_markup=_groups_kb(groups, set()), parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))

        else:
            results = []
            for ch in chats:
                chat_id = f"@{ch.username}" if ch.username else f"-100{ch.id}"
                results.append({"title": ch.title, "chat_id": chat_id})

            await state.update_data(results=results, selected=[])
            await state.set_state(SearchStates.selecting_results)
            await wait_msg.edit_text(
                f"🔍 <b>Найдено каналов: {len(results)}</b>\n\nВыбери для добавления в рассылку:",
                reply_markup=_channels_kb(results, set()),
                parse_mode="HTML",
            )

    except Exception as e:
        await wait_msg.edit_text(f"❌ Ошибка: <code>{e}</code>", parse_mode="HTML")
        await state.clear()


# ── Выбор каналов ─────────────────────────────────────────────────────────────

@router.callback_query(SearchStates.selecting_results, F.data.startswith("sch_toggle:"))
async def cb_toggle_channel(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    selected = set(data.get("selected", []))
    selected.discard(idx) if idx in selected else selected.add(idx)
    await state.update_data(selected=list(selected))
    await callback.message.edit_reply_markup(reply_markup=_channels_kb(data["results"], selected))
    await callback.answer()


@router.callback_query(SearchStates.selecting_results, F.data == "sch_save")
async def cb_save_channels(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = set(data.get("selected", []))
    if not selected:
        await callback.answer("Ничего не выбрано!", show_alert=True)
        return
    added = skipped = 0
    for i in selected:
        ch = data["results"][i]
        ok = await db.add_group(callback.from_user.id, ch["chat_id"], ch["title"])
        added += ok
        skipped += not ok
    await state.clear()
    text = f"✅ Добавлено: <b>{added}</b>"
    if skipped:
        text += f"\n⚠️ Уже в списке: {skipped}"
    await callback.message.edit_text(text, reply_markup=main_menu_kb(), parse_mode="HTML")


# ── Выбор групп ───────────────────────────────────────────────────────────────

@router.callback_query(SearchStates.selecting_groups, F.data.startswith("grp_toggle:"))
async def cb_toggle_group(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    selected = set(data.get("selected", []))
    selected.discard(idx) if idx in selected else selected.add(idx)
    await state.update_data(selected=list(selected))
    await callback.message.edit_reply_markup(reply_markup=_groups_kb(data["groups"], selected))
    await callback.answer()


@router.callback_query(SearchStates.selecting_groups, F.data == "grp_all")
async def cb_select_all(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = set(range(len(data["groups"])))
    await state.update_data(selected=list(selected))
    await callback.message.edit_reply_markup(reply_markup=_groups_kb(data["groups"], selected))
    await callback.answer()


@router.callback_query(SearchStates.selecting_groups, F.data == "grp_none")
async def cb_select_none(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(selected=[])
    await callback.message.edit_reply_markup(reply_markup=_groups_kb(data["groups"], set()))
    await callback.answer()


@router.callback_query(SearchStates.selecting_groups, F.data == "grp_join")
async def cb_join_groups(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = set(data.get("selected", []))
    if not selected:
        await callback.answer("Ничего не выбрано!", show_alert=True)
        return

    user_id = callback.from_user.id
    client = await sm.get_client(user_id)
    groups = data["groups"]

    status = await callback.message.edit_text(f"⏳ Вступаю в группы (0/{len(selected)})...")

    joined = failed = added = 0
    errors = []
    joined_peers = []

    for i in selected:
        g = groups[i]
        try:
            entity = await client(JoinChannelRequest(g["chat_id"]))
            joined += 1
            ok = await db.add_group(user_id, g["chat_id"], g["title"])
            if ok:
                added += 1
            # Сохраняем InputPeer для папки
            chats = getattr(entity, "chats", [])
            if chats:
                ch = chats[0]
                joined_peers.append(InputPeerChannel(
                    channel_id=ch.id,
                    access_hash=ch.access_hash,
                ))
        except Exception as e:
            failed += 1
            errors.append(f"• {g['title']}: {e}")

        try:
            await status.edit_text(f"⏳ Вступаю... {joined + failed}/{len(selected)}")
        except Exception:
            pass

    # Добавляем группы в папку "For Sender"
    folder_updated = False
    if joined_peers:
        try:
            existing = await client(GetDialogFiltersRequest())
            FOLDER_TITLE = "For Sender"

            # Ищем существующую папку
            sender_folder = next(
                (f for f in existing.filters if hasattr(f, "title") and f.title == FOLDER_TITLE),
                None,
            )

            if sender_folder:
                # Добавляем новые чаты к существующим
                existing_ids = {p.channel_id for p in sender_folder.include_peers if hasattr(p, "channel_id")}
                for p in joined_peers:
                    if p.channel_id not in existing_ids:
                        sender_folder.include_peers.append(p)
                folder = sender_folder
            else:
                # Создаём новую папку
                used_ids = {f.id for f in existing.filters if hasattr(f, "id")}
                folder_id = next(i for i in range(2, 256) if i not in used_ids)
                folder = DialogFilter(
                    id=folder_id,
                    title=FOLDER_TITLE,
                    pinned_peers=[],
                    include_peers=joined_peers,
                    exclude_peers=[],
                    contacts=False,
                    non_contacts=False,
                    groups=False,
                    broadcasts=False,
                    bots=False,
                    exclude_muted=False,
                    exclude_read=False,
                    exclude_archived=False,
                )

            await client(UpdateDialogFilterRequest(id=folder.id, filter=folder))
            folder_updated = True
        except Exception as fe:
            logging.error("Folder error: %s", fe, exc_info=fe)

    await state.clear()
    result = (
        f"<b>✅ Готово!</b>\n\n"
        f"Вступил: {joined}\n"
        f"Добавлено в рассылку: {added}\n"
        f"Ошибок: {failed}"
    )
    if folder_updated:
        result += "\n📁 Группы добавлены в папку <b>«For Sender»</b>"
    if errors:
        result += "\n\n<b>Ошибки:</b>\n" + "\n".join(errors[:5])

    await status.edit_text(result, reply_markup=main_menu_kb(), parse_mode="HTML")
