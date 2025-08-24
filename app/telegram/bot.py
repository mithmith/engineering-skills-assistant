import asyncio
import uuid

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from app.api import app as fastapi_app  # ensure FastAPI app initializes ChatService on startup
from app.config import logger, settings
from app.services.chat import ChatService
from app.telegram.handlers import TelegramHandlers
from app.telegram.registry import TelegramRegistry


def _new_conv_id() -> str:
    return str(uuid.uuid4())


def _get_chat_service() -> ChatService:
    svc = getattr(fastapi_app.state, "chat_service", None)
    if svc is None:
        raise RuntimeError("ChatService is not initialized. Start FastAPI app or import app.api first.")
    return svc


async def run_polling() -> None:
    token = settings.telegram_token
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN is not configured")

    registry = TelegramRegistry(settings.conversations_dir / "telegram_registry.json")
    chat_service = _get_chat_service()
    handlers = TelegramHandlers(chat_service, registry, _new_conv_id)

    application = ApplicationBuilder().token(token).concurrent_updates(False).build()
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("newdialog", handlers.newdialog))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.text_message))

    logger.info("Starting Telegram polling bot")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopping Telegram polling bot")
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    asyncio.run(run_polling())


