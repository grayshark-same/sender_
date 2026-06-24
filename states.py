from aiogram.fsm.state import State, StatesGroup


class AuthStates(StatesGroup):
    waiting_for_api_id = State()
    waiting_for_api_hash = State()
    waiting_for_qr = State()
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_password = State()  # 2FA


class SearchStates(StatesGroup):
    waiting_for_query = State()
    selecting_results = State()
    waiting_for_group_query = State()
    waiting_for_min_members = State()
    selecting_groups = State()


class TelemetrStates(StatesGroup):
    waiting_for_query = State()
    selecting_results = State()


class GroupStates(StatesGroup):
    waiting_for_chat_id = State()
    waiting_for_remove_id = State()


class ComposeStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_photo = State()
    waiting_for_buttons = State()


class BroadcastStates(StatesGroup):
    waiting_for_delay = State()
