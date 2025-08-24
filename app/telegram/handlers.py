import asyncio
import contextlib
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from app.config import logger
from app.services.chat import ChatService
from app.telegram.registry import TelegramRegistry
from app.telegram.utils import chunk_message, typing_pulse


class TelegramHandlers:
    def __init__(self, chat_service: ChatService, registry: TelegramRegistry, new_conv_id_factory: Callable[[], str]):
        self.chat_service = chat_service
        self.registry = registry
        self.new_conv_id_factory = new_conv_id_factory

    async def start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        conv_id = self.registry.get_or_create_active_conversation(user_id, new_conv_id_factory=self.new_conv_id_factory)
        await ctx.bot.send_message(update.effective_chat.id, "Привет! Готов помогать. Команды: /newdialog, /help")
        logger.info(f"/start user_id={user_id} conversation_id={conv_id}")

    async def newdialog(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        conv_id = self.registry.start_new_conversation(user_id, new_conv_id_factory=self.new_conv_id_factory)
        await ctx.bot.send_message(
            update.effective_chat.id,
            "Начинаем новый диалог. Предыдущий контекст сохранён и свёрнут. Сформулируй заново, с чего начнём.",
        )
        logger.info(f"/newdialog user_id={user_id} conversation_id={conv_id}")

    async def text_message(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return
        user_id = update.effective_user.id
        conv_id = self.registry.get_or_create_active_conversation(user_id, new_conv_id_factory=self.new_conv_id_factory)

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


