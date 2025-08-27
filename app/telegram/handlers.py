import asyncio
import contextlib
from typing import Any, Callable, Dict
import uuid

from telegram import Update
from telegram.ext import ContextTypes

from app.config import logger, settings
from app.services.chat import ChatService
from app.telegram.registry import TelegramRegistry
from app.telegram.utils import chunk_message, typing_pulse, escape_markdown, download_photo_as_data_url


class TelegramHandlers:
    def __init__(self, chat_service: ChatService, registry: TelegramRegistry, new_conv_id_factory: Callable[[], str]):
        self.chat_service = chat_service
        self.registry = registry
        self.new_conv_id_factory = new_conv_id_factory

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
        parts = [header, "\n" + "\n".join(bullets), escape_markdown("\n*Минимальный шаблон промпта:*"),]
        tmpl_code = (
            "Цель: …\n"
            "Контекст: … (язык/версия/платформа)\n"
            "Данные/код: …\n"
            "Формат ответа: … (коротко/пошагово/пример кода)"
        )
        tmpl_safe = (
            tmpl_code.replace("(", "\\(").replace(")", "\\)").replace(".", "\\.")
        )
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

        stop = asyncio.Event()
        pulse = asyncio.create_task(typing_pulse(update.effective_chat.id, ctx.bot, stop))

        try:
            # record usage before processing to deter abuse; safe even if fails later
            self.registry.consume_message(user_id)
            user_text = update.message.text or ""
            # If a photo is attached, prefer the largest size
            image_part = None
            if update.message.photo:
                photo_sizes = update.message.photo
                largest = max(photo_sizes, key=lambda p: p.width * p.height)
                data_url, _ = await download_photo_as_data_url(largest.file_id, ctx.bot)
                image_part = {"type": "input_image", "image_url": data_url}

            if image_part:
                # Build full-context messages using ChatService internals (system + summary + window)
                system_prompt = self.chat_service.prompt_loader.load()
                history = self.chat_service.store.load(conv_id)
                summary_text = None
                if settings.summary_enabled:
                    summary_text = self.chat_service._summarize(conv_id, history)
                msgs = self.chat_service._build_messages(system_prompt, summary_text, history, user_text or "")
                # Replace the last user message with multimodal content (image + optional caption)
                if msgs and msgs[-1].get("role") == "user":
                    msgs[-1] = {
                        "role": "user",
                        "content": [image_part]
                        + ([{"type": "input_text", "text": user_text}] if user_text else []),
                    }
                prev_id = self.chat_service.store.last_assistant_response_id(conv_id)
                kwargs: Dict[str, Any] = {"store": True}
                if prev_id is not None:
                    kwargs["previous_response_id"] = str(prev_id)
                # Call OpenAI with full context
                resp = await asyncio.to_thread(self.chat_service.client.create, msgs, **kwargs)
                assistant_text = self.chat_service._extract_text(resp)
                response_id = getattr(resp, "id", None)

                # Log and store records with masked image marker
                caption = (user_text or "").strip().replace("\n", " ")
                logger.info(
                    f"Telegram multimodal: conversation_id={conv_id} response_id={response_id} caption=\"{caption}\" [IMAGE]"
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
                # Wrap minimal result
                class _R:
                    def __init__(self, conv_id, text, rid):
                        self.conversation_id = conv_id
                        self.assistant_text = text
                        self.response_id = rid
                result = _R(conv_id, assistant_text, response_id)
            else:
                result = await asyncio.to_thread(self.chat_service.chat, user_text, conv_id)
            stop.set()
            with contextlib.suppress(Exception):
                await ctx.bot.delete_message(update.effective_chat.id, status_msg.message_id)
            for chunk in chunk_message(result.assistant_text):
                await ctx.bot.send_message(update.effective_chat.id, chunk)
        except Exception as e:
            stop.set()
            logger.exception("Telegram text_message error")
            with contextlib.suppress(Exception):
                await ctx.bot.edit_message_text(
                    "⚠️ что-то пошло не так. Попробуем ещё раз?",
                    chat_id=update.effective_chat.id,
                    message_id=status_msg.message_id,
                )
                await asyncio.sleep(6)
                await ctx.bot.delete_message(update.effective_chat.id, status_msg.message_id)
        finally:
            self.registry.clear_status(user_id)
