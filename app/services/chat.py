import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.integration.chatgpt import OpenAIClient
from app.services.conversation_store import ConversationStore
from app.utils.prompt_loader import PromptLoader
from app.config import logger


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ChatResult:
    conversation_id: str
    assistant_text: str
    response_id: Optional[str]


class ChatService:
    """Сервис диалогов: строит сообщения, вызывает модель и логирует историю."""

    def __init__(
        self,
        client: OpenAIClient,
        prompt_loader: PromptLoader,
        store: ConversationStore,
        max_history_messages: Optional[int] = None,
    ):
        logger.debug(f"ChatService.__init__ model={client.model_name} max_history={max_history_messages}")
        self.client = client
        self.prompt_loader = prompt_loader
        self.store = store
        self.max_history_messages = max_history_messages
        self.model_name = client.model_name

    def _build_messages(self, system_prompt: str, history: List[Dict[str, Any]], new_user_text: str):
        msgs: List[Dict[str, Any]] = []
        msgs.append(
            {
                "role": "system",
                "content": [{"type": "input_text", "text": system_prompt}],
            }
        )
        hist = history
        if self.max_history_messages is not None and len(history) > self.max_history_messages:
            hist = history[-self.max_history_messages :]

        for m in hist:
            if m.get("role") in {"user", "assistant"}:
                content_type = "input_text" if m["role"] == "user" else "output_text"
                msgs.append(
                    {
                        "role": m["role"],
                        "content": [{"type": content_type, "text": str(m.get("content", ""))}],
                    }
                )

        msgs.append(
            {
                "role": "user",
                "content": [{"type": "input_text", "text": new_user_text}],
            }
        )
        return msgs

    def chat(self, user_text: str, conversation_id: Optional[str] = None) -> ChatResult:
        conv_id = conversation_id or str(uuid.uuid4())
        logger.info(f"ChatService.chat conversation_id={conv_id}")
        system_prompt = self.prompt_loader.load()
        logger.debug(f"System prompt loaded ({len(system_prompt)} chars)")
        history = self.store.load(conv_id)
        logger.debug(f"Loaded history messages: {len(history)}")

        msgs = self._build_messages(system_prompt, history, user_text)
        logger.debug(f"Built messages: {len(msgs)}")

        resp = self.client.create(msgs)
        assistant_text = resp.output_text
        response_id = getattr(resp, "id", None)
        logger.info(f"OpenAI response id={response_id} (len={len(assistant_text or '')})")

        user_msg = {
            "id": str(uuid.uuid4()),
            "conversation_id": conv_id,
            "role": "user",
            "content": user_text,
            "ts": utcnow_iso(),
            "model": None,
            "response_id": None,
        }
        self.store.append(conv_id, user_msg)
        logger.debug("Appended user message to store")

        assistant_msg = {
            "id": str(uuid.uuid4()),
            "conversation_id": conv_id,
            "role": "assistant",
            "content": assistant_text,
            "ts": utcnow_iso(),
            "model": self.model_name,
            "response_id": response_id,
        }
        self.store.append(conv_id, assistant_msg)
        logger.debug("Appended assistant message to store")

        return ChatResult(
            conversation_id=conv_id,
            assistant_text=assistant_text,
            response_id=response_id,
        )
