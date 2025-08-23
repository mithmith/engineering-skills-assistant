from fastapi import FastAPI
from app.config import logger, settings

from app.api.routes import router
from app.config import settings
from app.integration.chatgpt import OpenAIClient
from app.integration.http_clients import close_http_clients
from app.services.chat import ChatService
from app.services.conversation_store import ConversationStore
from app.utils.prompt_loader import PromptLoader


def create_app() -> FastAPI:
    app = FastAPI(title="GPT-5 Chat Service", version="1.0.0")

    @app.on_event("startup")
    def _startup():
        logger.info("Starting up application")
        client = OpenAIClient(api_key=settings.openai_api_key, model_name=settings.model_name)
        prompt_loader = PromptLoader(settings.system_prompt_path)
        store = ConversationStore(settings.conversations_dir)
        logger.debug(
            "ChatService init with model=%s, system_prompt_path=%s, conversations_dir=%s, max_history=%s",
            settings.model_name,
            settings.system_prompt_path,
            settings.conversations_dir,
            settings.max_history_messages,
        )
        chat_service = ChatService(
            client=client,
            prompt_loader=prompt_loader,
            store=store,
            max_history_messages=settings.max_history_messages,
        )
        app.state.chat_service = chat_service
        logger.info("ChatService initialized")

    app.include_router(router, prefix="/api")
    app.add_event_handler("shutdown", close_http_clients)
    logger.info("Router mounted at /api and shutdown handler registered")
    return app


app = create_app()
