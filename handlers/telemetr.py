import aiohttp
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from states import TelemetrStates
from keyboards import back_kb, main_menu_kb
import database as db
from config import TELEMETR_SESSION

router = Router()

TELEMETR_SEARCH_URL = "https://telemetr.me/api/v1/catalog/channels/search"
MAX_RESULTS = 20


def _results_kb(results: list[dict], selected: set[int]) -> InlineKeyboardMarkup:
    rows = []
    for i, ch in enumerate(results):
        check = "✅" if i in selected else "☑️"
        members = f"{ch['members']:,}".replace(",", " ") if ch["members"] else "?"
        rows.append([InlineKeyboardButton(
            text=f"{check} {ch['title'][:30]} · {members}",
            callback_data=f"tlm_toggle:{i}",
        )])
    rows.append([
        InlineKeyboardButton(text="✅ Все", callback_data="tlm_all"),
        InlineKeyboardButton(text="❌ Сброс", callback_data="tlm_none"),
        InlineKeyboardButton(text="💾 Добавить", callback_data="tlm_save"),
    ])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _search_telemetr(query: str, min_subs: int = 100) -> list[dict]:
    params = {"query": query, "limit": MAX_RESULTS, "subscribers_from": min_subs}
    headers = {
        "Cookie": f"PHPSESSID={TELEMETR_SESSION}",
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://telemetr.me/",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(TELEMETR_SEARCH_URL, params=params, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()
    items = data.get("items", []) if isinstance(data, dict) else data
    results = []
    for ch in items:
        peer_id = ch.get("peer_id") or ""
        username = ch.get("username") or peer_id
        chat_id = f"@{username}" if username and not str(username).lstrip("-").isdigit() else str(username)
        results.append({
            "title": ch.get("title", ""),
            "chat_id": chat_id,
            "members": ch.get("subscribers_count") or ch.get("subscribers") or 0,
        })
    return results


@router.callback_query(F.data == "search_telemetr")
async def cb_search_telemetr(callback: CallbackQuery, state: FSMContext):
    if not TELEMETR_SESSION:
        await callback.answer("TELEMETR_SESSION не настроен.", show_alert=True)
        return
    await state.set_state(TelemetrStates.waiting_for_query)
    await callback.message.edit_text(
        "📊 <b>Поиск каналов через Telemetr.me</b>\n\n"
        "Введи ключевое слово или тематику:",
        reply_markup=back_kb("main_menu"),
        parse_mode="HTML",
    )


@router.message(TelemetrStates.waiting_for_query)
async def receive_telemetr_query(message: Message, state: FSMContext):
    wait = await message.answer("⏳ Ищу в Telemetr.me...")
    try:
        results = await _search_telemetr(message.text.strip())
    except Exception as e:
        await wait.edit_text(f"❌ Ошибка Telemetr: <code>{e}</code>", parse_mode="HTML")
        await state.clear()
        return

    if not results:
        await wait.edit_text(
            "😔 Ничего не найдено. Попробуй другой запрос.",
            reply_markup=back_kb("main_menu"),
        )
        await state.clear()
        return

    await state.update_data(results=results, selected=[])
    await state.set_state(TelemetrStates.selecting_results)
    await wait.edit_text(
        f"📊 <b>Найдено каналов: {len(results)}</b>\n\nВыбери для добавления в рассылку:",
        reply_markup=_results_kb(results, set()),
        parse_mode="HTML",
    )


@router.callback_query(TelemetrStates.selecting_results, F.data.startswith("tlm_toggle:"))
async def cb_toggle(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[1])
    data = await state.get_data()
    selected = set(data.get("selected", []))
    selected.discard(idx) if idx in selected else selected.add(idx)
    await state.update_data(selected=list(selected))
    await callback.message.edit_reply_markup(reply_markup=_results_kb(data["results"], selected))
    await callback.answer()


@router.callback_query(TelemetrStates.selecting_results, F.data == "tlm_all")
async def cb_all(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = set(range(len(data["results"])))
    await state.update_data(selected=list(selected))
    await callback.message.edit_reply_markup(reply_markup=_results_kb(data["results"], selected))
    await callback.answer()


@router.callback_query(TelemetrStates.selecting_results, F.data == "tlm_none")
async def cb_none(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(selected=[])
    await callback.message.edit_reply_markup(reply_markup=_results_kb(data["results"], set()))
    await callback.answer()


@router.callback_query(TelemetrStates.selecting_results, F.data == "tlm_save")
async def cb_save(callback: CallbackQuery, state: FSMContext):
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
