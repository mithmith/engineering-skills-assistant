import asyncio
import contextlib
import uuid
from typing import Any, Callable, Dict

from telegram import Update
from telegram.ext import ContextTypes

from app.config import logger, settings
from app.services.chat import ChatService
from app.telegram.registry import TelegramRegistry
from app.telegram.utils import chunk_message, download_photo_as_data_url, escape_markdown, typing_pulse


class TelegramHandlers:
    def __init__(self, chat_service: ChatService, registry: TelegramRegistry, new_conv_id_factory: Callable[[], str]):
        self.chat_service = chat_service
        self.registry = registry
        self.new_conv_id_factory = new_conv_id_factory
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None

    async def start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.effective_chat:
            return
        user_id = update.effective_user.id
        # update profile fields
        self.registry.update_profile(
            user_id,
            full_name=update.effective_user.full_name,
            username=update.effective_user.username,
        )
        conv_id = self.registry.get_or_create_active_conversation(user_id, new_conv_id_factory=self.new_conv_id_factory)
        await ctx.bot.send_message(update.effective_chat.id, "Привет! Готов помогать. Команды: /newdialog, /help")
        logger.info(f"/start user_id={user_id} conversation_id={conv_id}")

    async def newdialog(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.effective_chat:
            return
        user_id = update.effective_user.id
        self.registry.update_profile(
            user_id,
            full_name=update.effective_user.full_name,
            username=update.effective_user.username,
        )
        conv_id = self.registry.start_new_conversation(user_id, new_conv_id_factory=self.new_conv_id_factory)
        await ctx.bot.send_message(
            update.effective_chat.id,
            "Начинаем новый диалог. Предыдущий контекст сохранён и свёрнут. Сформулируй заново, с чего начнём.",
        )
        logger.info(f"/newdialog user_id={user_id} conversation_id={conv_id}")

    async def help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or not update.effective_chat:
            return
        user_id = update.effective_user.id
        self.registry.update_profile(
            user_id,
            full_name=update.effective_user.full_name,
            username=update.effective_user.username,
        )
        # MarkdownV2-formatted help (avoid raw '.' or special chars issues by escaping)
        header = escape_markdown("*Как спрашивать, чтобы было полезнее?* 🤝")
        bullets = [
            escape_markdown("— Коротко опиши цель: что хочешь получить в итоге"),
            escape_markdown("— Дай контекст: платформа, язык, версия, ограничения по времени/ресурсам"),
            escape_markdown("— Покажи пример входных данных или текущий код — если есть"),
            escape_markdown("— Укажи желаемый формат ответа: шаги, код, чеклист"),
        ]
        parts = [
            header,
            "\n" + "\n".join(bullets),
            escape_markdown("\n*Минимальный шаблон промпта:*"),
        ]
        tmpl_code = (
            "Цель: …\n"
            "Контекст: … (язык/версия/платформа)\n"
            "Данные/код: …\n"
            "Формат ответа: … (коротко/пошагово/пример кода)"
        )
        tmpl_safe = tmpl_code.replace("(", "\\(").replace(")", "\\)").replace(".", "\\.")
        parts.append("```\n" + tmpl_safe + "\n```")
        parts.append(escape_markdown("\n*Примеры:*"))
        ex1_code = (
            "Цель: отладить схему драйвера MOSFET.\n"
            "Контекст: STM32, 12 В, N-MOSFET, PWM 20 кГц.\n"
            "Данные/код: фрагмент схемы (gate/driver/Rg/диод), осциллограммы, симптомы (перегрев, звон).\n"
            "Формат ответа: список проверок, расчёт Rg/Cgate, рекомендации по разводке."
        )
        ex2_code = (
            "Цель: оценить прогиб консольного бруса в CAE.\n"
            "Контекст: FreeCAD + CalculiX, Al 6061-T6, нагрузка 150 Н на конце, L=200 мм, сечение 20x5 мм.\n"
            "Формат ответа: пошагово — КУ/сетку/материал, и проверка аналитикой (δ = F*L^3/(3*E*I))."
        )
        ex1_safe = ex1_code.replace("(", "\\(").replace(")", "\\)").replace(".", "\\.")
        ex2_safe = ex2_code.replace("(", "\\(").replace(")", "\\)").replace(".", "\\.")
        parts.append("```\n" + ex1_safe + "\n```")
        parts.append("```\n" + ex2_safe + "\n```")
        parts.append(escape_markdown("Если что — пингуй, разберёмся вместе ✨"))
        text = "\n".join(parts)
        await ctx.bot.send_message(update.effective_chat.id, text, parse_mode="MarkdownV2")

    async def text_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.effective_user or not update.effective_chat:
            return
        user_id = update.effective_user.id
        self.registry.update_profile(
            user_id,
            full_name=update.effective_user.full_name,
            username=update.effective_user.username,
        )
        conv_id = self.registry.get_or_create_active_conversation(user_id, new_conv_id_factory=self.new_conv_id_factory)

        # rate-limit per user
        if not self.registry.can_consume_message(user_id, settings.telegram_daily_message_limit):
            await ctx.bot.send_message(
                update.effective_chat.id,
                f"Дневной лимит сообщений исчерпан (до {settings.telegram_daily_message_limit} в сутки). Попробуем завтра.",
            )
            return

        if self.registry.in_flight(user_id):
            await ctx.bot.send_message(
                update.effective_chat.id,
                "Я ещё думаю над прошлым вопросом — сейчас отвечу и продолжим.",
            )
            return

        status_msg = await ctx.bot.send_message(update.effective_chat.id, "⏳ думаю над ответом…")
        self.registry.set_status(user_id, status_msg.message_id, in_flight=True)

        # ensure worker is running
        if not self._worker_task or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker(ctx))

        # record usage before processing to deter abuse
        self.registry.consume_message(user_id)

        # Prepare job payload (prefer largest photo if present)
        photo_id = None
        if update.message.photo:
            largest = max(update.message.photo, key=lambda p: p.width * p.height)
            photo_id = largest.file_id
        job = {
            "chat_id": update.effective_chat.id,
            "user_id": user_id,
            "conversation_id": conv_id,
            "text": update.message.text or "",
            "photo_id": photo_id,
            "status_message_id": status_msg.message_id,
        }
        await self._queue.put(job)
        # return immediately; worker will process and reply

    async def _worker(self, ctx: ContextTypes.DEFAULT_TYPE):
        while True:
            job = await self._queue.get()
            try:
                await self._process_job(job, ctx)
            except Exception:
                logger.exception("Telegram text_message error")
            finally:
                self._queue.task_done()

    async def _process_job(self, job: Dict[str, Any], ctx: ContextTypes.DEFAULT_TYPE):
        chat_id = job["chat_id"]
        user_id = job["user_id"]
        conv_id = job["conversation_id"]
        user_text = job.get("text") or ""
        status_message_id = job.get("status_message_id")

        stop = asyncio.Event()
        pulse = asyncio.create_task(typing_pulse(chat_id, ctx.bot, stop))
        try:
            image_part = None
            if job.get("photo_id"):
                data_url, _ = await download_photo_as_data_url(job["photo_id"], ctx.bot)
                image_part = {"type": "input_image", "image_url": data_url}

            if image_part:
                system_prompt = self.chat_service.prompt_loader.load()
                history = self.chat_service.store.load(conv_id)
                summary_text = None
                if settings.summary_enabled:
                    summary_text = self.chat_service._summarize(conv_id, history)
                msgs = self.chat_service._build_messages(system_prompt, summary_text, history, user_text or "")
                if msgs and msgs[-1].get("role") == "user":
                    msgs[-1] = {
                        "role": "user",
                        "content": [image_part] + ([{"type": "input_text", "text": user_text}] if user_text else []),
                    }
                prev_id = self.chat_service.store.last_assistant_response_id(conv_id)
                kwargs: Dict[str, Any] = {"store": True}
                if prev_id is not None:
                    kwargs["previous_response_id"] = str(prev_id)
                resp = await asyncio.to_thread(self.chat_service.client.create, msgs, **kwargs)
                assistant_text = self.chat_service._extract_text(resp)
                response_id = getattr(resp, "id", None)

                caption = (user_text or "").strip().replace("\n", " ")
                logger.info(
                    f'Telegram multimodal: conversation_id={conv_id} response_id={response_id} caption="{caption}" [IMAGE]'
                )
                from datetime import datetime, timezone
                iso = datetime.now(timezone.utc).isoformat()
                user_record = {
                    "id": str(uuid.uuid4()),
                    "conversation_id": conv_id,
                    "role": "user",
                    "content": ((user_text or "").strip() + ("\n[IMAGE]" if image_part else "")).strip(),
                    "ts": iso,
                    "model": None,
                    "response_id": None,
                }
                self.chat_service.store.append(conv_id, user_record)
                assistant_record = {
                    "id": str(uuid.uuid4()),
                    "conversation_id": conv_id,
                    "role": "assistant",
                    "content": assistant_text,
                    "ts": iso,
                    "model": self.chat_service.model_name,
                    "response_id": response_id,
                }
                self.chat_service.store.append(conv_id, assistant_record)

                for chunk in chunk_message(assistant_text):
                    await ctx.bot.send_message(chat_id, chunk)
            else:
                result = await asyncio.to_thread(self.chat_service.chat, user_text, conv_id)
                for chunk in chunk_message(result.assistant_text):
                    await ctx.bot.send_message(chat_id, chunk)
        finally:
            stop.set()
            with contextlib.suppress(Exception):
                if status_message_id:
                    await ctx.bot.delete_message(chat_id, status_message_id)
            self.registry.clear_status(user_id)
