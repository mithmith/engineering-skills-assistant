import uuid

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from telegram.request import HTTPXRequest

from app.api import app as fastapi_app  # FastAPI app is importable without running uvicorn
from app.config import logger, settings
from app.integration.chatgpt import OpenAIClient
from app.services.chat import ChatService
from app.services.conversation_store import ConversationStore
from app.telegram.handlers import TelegramHandlers
from app.telegram.registry import TelegramRegistry
from app.utils.prompt_loader import PromptLoader


def _new_conv_id() -> str:
    return str(uuid.uuid4())


def _get_chat_service() -> ChatService:
    svc = getattr(fastapi_app.state, "chat_service", None)
    if svc is not None:
        return svc
    # Fallback: initialize ChatService the same way FastAPI startup does
    logger.info("Initializing ChatService for Telegram bot (fallback path)")
    client = OpenAIClient(api_key=settings.openai_api_key, model_name=settings.model_name)
    prompt_loader = PromptLoader(settings.system_prompt_path)
    store = ConversationStore(settings.conversations_dir)
    chat_service = ChatService(
        client=client,
        prompt_loader=prompt_loader,
        store=store,
        max_history_messages=settings.max_history_messages,
    )
    fastapi_app.state.chat_service = chat_service
    logger.info("ChatService initialized (telegram)")
    return chat_service


def run_polling() -> None:
    token = settings.telegram_token
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN is not configured")

    registry = TelegramRegistry(settings.conversations_dir / "telegram_registry.json")
    chat_service = _get_chat_service()
    handlers = TelegramHandlers(chat_service, registry, _new_conv_id)

    # Configure HTTPX client with optional proxy and timeouts
    request = HTTPXRequest(
        connect_timeout=settings.telegram_connect_timeout_s,
        read_timeout=settings.telegram_read_timeout_s,
        pool_timeout=settings.telegram_connect_timeout_s,
        proxy_url=settings.telegram_proxy_url,
    )

    application = ApplicationBuilder().token(token).request(request).concurrent_updates(False).build()
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.help))
    application.add_handler(CommandHandler("newdialog", handlers.newdialog))
    application.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, handlers.text_message))

    logger.info("Starting Telegram polling bot")
    application.run_polling()


if __name__ == "__main__":
    run_polling()
