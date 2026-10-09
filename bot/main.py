import asyncio
import logging
import shutil
import signal
import sys
import tempfile
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat

from . import config
from .db import db
from .handlers import admin, user
from .middleware import Gate

log = logging.getLogger("main")


def build_bot():
    session = None
    if config.LOCAL_API_URL:
        session = AiohttpSession(api=TelegramAPIServer.from_base(config.LOCAL_API_URL, is_local=True))
    return Bot(config.BOT_TOKEN, session=session,
               default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def build_dp():
    dp = Dispatcher(storage=MemoryStorage())
    dp.message.outer_middleware(Gate())
    dp.callback_query.outer_middleware(Gate())
    dp.include_router(admin.router)
    dp.include_router(user.router)

    @dp.error()
    async def on_error(event):
        log.error("handler error: %s", event.exception, exc_info=event.exception)
        try:
            upd = event.update
            msg = upd.message or (upd.callback_query.message if upd.callback_query else None)
            if msg and msg.chat.type == "private":
                await msg.answer("😔 ببخشید ارباب، خطایی پیش اومد. دوباره امتحان کنین.")
        except Exception:
            pass
        return True

    return dp


async def setup_commands(bot):
    try:
        await bot.set_my_commands([BotCommand(command="start", description="شروع"),
                                   BotCommand(command="help", description="راهنما"),
                                   BotCommand(command="dl", description="دانلود لینک (ریپلای)")])
        for aid in config.ADMIN_IDS:
            try:
                await bot.set_my_commands(
                    [BotCommand(command="start", description="شروع"),
                     BotCommand(command="admin", description="پنل مدیریت"),
                     BotCommand(command="help", description="راهنما")],
                    scope=BotCommandScopeChat(chat_id=aid))
            except Exception:
                pass
    except Exception as e:
        log.warning("set commands failed: %s", e)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.BOT_TOKEN:
        log.error("BOT_TOKEN تنظیم نشده")
        sys.exit(1)
    # پاکسازی فایل‌های موقت مانده از اجراهای قبلی
    for p in Path(tempfile.gettempdir()).glob("dl_*"):
        shutil.rmtree(p, ignore_errors=True)

    await db.connect()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    asyncio.create_task(user.cleanup_loop())
    log.info("data dir: %s | upload limit: %s MB", config.DATA_DIR, config.UPLOAD_LIMIT // 1048576)

    while not stop.is_set():
        bot, dp = build_bot(), build_dp()
        poll = None
        try:
            await bot.delete_webhook(drop_pending_updates=False)
            await setup_commands(bot)
            log.info("bot started")
            poll = asyncio.create_task(dp.start_polling(
                bot, handle_signals=False, allowed_updates=["message", "callback_query"]))
            waiter = asyncio.create_task(stop.wait())
            await asyncio.wait({poll, waiter}, return_when=asyncio.FIRST_COMPLETED)
            waiter.cancel()
            if poll.done() and not stop.is_set():
                exc = poll.exception()
                log.error("polling stopped: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.error("crash in main loop: %s", e, exc_info=True)
        finally:
            if poll and not poll.done():
                try:
                    await dp.stop_polling()
                except Exception:
                    pass
                poll.cancel()
            try:
                await bot.session.close()
            except Exception:
                pass
        if not stop.is_set():
            await asyncio.sleep(5)  # restart خودکار؛ مثلا هنگام deploy با Conflict موقت
    for t in list(user.TASKS):
        t.cancel()
    await db.close()
    log.info("bye")


if __name__ == "__main__":
    asyncio.run(main())
