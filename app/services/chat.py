import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.integration.chatgpt import OpenAIClient
from app.services.conversation_store import ConversationStore
from app.utils.prompt_loader import PromptLoader
from app.config import logger, settings


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ChatResult:
    conversation_id: str
    assistant_text: str
    response_id: Optional[str]


_SUMMARY_INSTRUCTION = (
    "Сверни диалог в короткую, полезную выжимку для продолжения разговора.\n"
    "Оставь только устойчивые факты, цели пользователя, ограничения, принятые решения, "
    "важные определения и договорённости по стилю/тону, незакрытые вопросы и TODO. "
    "Не включай формальный мусор и вежливости. Пиши компактно, в виде обычного текста. "
    "Лимит — примерно {limit} символов."
)


class ChatService:
    """Сервис диалогов: строит сообщения, вызывает модель и логирует историю.
       Добавлена свёртка контекста (summary) и скользящее окно последних реплик.
    """

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
        self.summary_model = settings.summary_model_name or self.model_name

    # ---------- summary pipeline ----------

    def _need_summarize(self, history: List[Dict[str, Any]], keep_last: int, turns_gap: int) -> bool:
        # считаем «живые» сообщения (user/assistant), которые пойдут в окно
        live = [m for m in history if m.get("role") in {"user", "assistant"}]
        if len(live) <= keep_last:
            return False
        # пересвёртка каждые N ответов ассистента
        last_summary_turn = 0
        for i, m in enumerate(live, start=1):
            if m.get("role") == "assistant" and m.get("kind") == "summary":
                last_summary_turn = i
        assistant_turns = sum(1 for m in live if m.get("role") == "assistant")
        return (assistant_turns - last_summary_turn) >= turns_gap

    def _build_history_text(self, msgs: List[Dict[str, Any]]) -> str:
        # Превращаем сообщения в «плоский» текст для свёртки
        lines = []
        for m in msgs:
            role = m.get("role")
            if role not in {"user", "assistant"}:
                continue
            text = str(m.get("content", "")).strip()
            if not text:
                continue
            prefix = "User" if role == "user" else "Assistant"
            lines.append(f"{prefix}: {text}")
        return "\n".join(lines)

    def _summarize(self, conversation_id: str, history: List[Dict[str, Any]]) -> Optional[str]:
        """Создаёт/обновляет summary и сохраняет его в сторе."""
        keep_last = settings.summary_keep_last_messages
        limit = settings.summary_max_chars
        turns_gap = settings.summary_update_every_n_turns

        # Уже есть свежий summary, и нет необходимости пересвёртки?
        if not self._need_summarize(history, keep_last, turns_gap):
            summ = self.store.latest_summary(conversation_id)
            return summ.get("content") if summ else None

        # К свёртке идёт «старый хвост» до последних keep_last реплик
        linear = [m for m in history if m.get("role") in {"user", "assistant"}]
        head = linear[:-keep_last] if len(linear) > keep_last else []
        if not head:
            return None

        text = self._build_history_text(head)
        if len(text) > limit * 2:
            text = text[-limit * 2 :]  # грубая отсечка

        sys = _SUMMARY_INSTRUCTION.format(limit=limit)
        try:
            resp = self.client.create(
                [
                    {"role": "system", "content": [{"type": "input_text", "text": sys}]},
                    {"role": "user", "content": [{"type": "input_text", "text": text}]},
                ],
                model=self.summary_model,
            )
            summary_text = (resp.output_text or "").strip()
            if not summary_text:
                return None

            rec = {
                "id": str(uuid.uuid4()),
                "conversation_id": conversation_id,
                "role": "system",
                "kind": "summary",
                "content": summary_text[: limit + 500],  # небольшой запас
                "ts": utcnow_iso(),
                "model": self.summary_model,
                "response_id": getattr(resp, "id", None),
                "meta": {"keep_last": keep_last},
            }
            self.store.append(conversation_id, rec)
            logger.debug("Summary appended")
            return rec["content"]

        except Exception:
            logger.exception("Summary generation failed")
            return None

    # ---------- building request messages ----------

    def _build_messages(
        self,
        system_prompt: str,
        summary_text: Optional[str],
        history: List[Dict[str, Any]],
        new_user_text: str,
    ):
        msgs: List[Dict[str, Any]] = []
        # Якорный системный промпт — всегда первым
        msgs.append({"role": "system", "content": [{"type": "input_text", "text": system_prompt}]})

        # Если есть summary — добавляем вторым системным блоком
        if summary_text:
            msgs.append(
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": f"[summary]\n{summary_text}"}],
                }
            )

        # Живое окно последних сообщений
        window: List[Dict[str, Any]] = []
        for m in history:
            if m.get("role") in {"user", "assistant"}:
                window.append(m)
        keep = settings.summary_keep_last_messages
        if len(window) > keep:
            window = window[-keep:]

        for m in window:
            content_type = "input_text" if m["role"] == "user" else "output_text"
            msgs.append(
                {
                    "role": m["role"],
                    "content": [{"type": content_type, "text": str(m.get("content", ""))}],
                }
            )

        # Новое сообщение пользователя
        msgs.append({"role": "user", "content": [{"type": "input_text", "text": new_user_text}]})
        return msgs

    # ---------- public API ----------

    def chat(self, user_text: str, conversation_id: Optional[str] = None) -> ChatResult:
        conv_id = conversation_id or str(uuid.uuid4())
        logger.info(f"ChatService.chat conversation_id={conv_id}")

        # 1) загрузили якорь и историю
        system_prompt = self.prompt_loader.load()
        history = self.store.load(conv_id)
        logger.debug(f"Loaded history messages: {len(history)}")

        # 2) при необходимости обновили/получили summary
        summary_text = None
        if settings.summary_enabled:
            summary_text = self._summarize(conv_id, history)

        # 3) собрали финальные сообщения: якорь + summary + окно последних реплик + новое
        msgs = self._build_messages(system_prompt, summary_text, history, user_text)
        logger.debug(f"Built messages: {len(msgs)}")

        # 4) вызвали модель (по желанию можно включить store=True / previous_response_id)
        try:
            resp = self.client.create(msgs, store=True)
        except Exception:
            logger.exception("OpenAI call failed")
            raise

        assistant_text = resp.output_text
        response_id = getattr(resp, "id", None)
        logger.info(f"OpenAI response id={response_id} (len={len(assistant_text or '')})")

        # 5) сохранили обе реплики
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

        return ChatResult(
            conversation_id=conv_id,
            assistant_text=assistant_text,
            response_id=response_id,
        )
