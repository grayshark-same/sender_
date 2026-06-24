import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from database import init_db
from handlers import auth, menu, groups, compose, broadcast, admin, search, telemetr

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def main():
    await init_db()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    @dp.errors()
    async def error_handler(event, exception: Exception):
        logging.error("Unhandled error: %s", exception, exc_info=exception)

    dp.include_router(admin.router)   # первым — чтобы /grant и /revoke не перехватывались
    dp.include_router(auth.router)
    dp.include_router(menu.router)
    dp.include_router(groups.router)
    dp.include_router(compose.router)
    dp.include_router(broadcast.router)
    dp.include_router(search.router)
    dp.include_router(telemetr.router)

    logging.info("Бот запущен.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
