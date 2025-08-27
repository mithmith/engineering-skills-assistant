import asyncio
import contextlib
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from app.config import logger, settings
from app.services.chat import ChatService
from app.telegram.registry import TelegramRegistry
from app.telegram.utils import chunk_message, typing_pulse, escape_markdown


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
        if not update.message or not update.message.text or not update.effective_user or not update.effective_chat:
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
            result = await asyncio.to_thread(self.chat_service.chat, update.message.text, conv_id)
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
