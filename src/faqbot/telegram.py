"""Telegram adapter built on aiogram 3.

The adapter is split in two parts:

* :func:`handle` turns one text message into a :class:`Reply` and is pure
  Python, so it is covered by tests without a network or a bot token.
* :func:`run` wires that logic to aiogram's long polling.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from .engine import Bot, ChatSession
from .kb import QuickReply

MAX_MESSAGE = 4000


@dataclass
class Reply:
    text: str
    buttons: tuple[QuickReply, ...] = ()


@dataclass
class ChatStore:
    sessions: dict[int, ChatSession] = field(default_factory=dict)
    last_buttons: dict[int, tuple[QuickReply, ...]] = field(default_factory=dict)

    def session(self, chat_id: int) -> ChatSession:
        return self.sessions.setdefault(chat_id, ChatSession())

    def remember_buttons(self, chat_id: int, buttons: tuple[QuickReply, ...]) -> None:
        self.last_buttons[chat_id] = buttons

    def button(self, chat_id: int, index: int) -> QuickReply | None:
        buttons = self.last_buttons.get(chat_id, ())
        return buttons[index] if 0 <= index < len(buttons) else None


def _chunk(text: str) -> list[str]:
    text = text.strip()
    if len(text) <= MAX_MESSAGE:
        return [text]
    return [text[i : i + MAX_MESSAGE] for i in range(0, len(text), MAX_MESSAGE)]


def handle(bot: Bot, store: ChatStore, chat_id: int, text: str) -> list[Reply]:
    """Answer one Telegram message (possibly split into several replies)."""
    question = (text or "").strip()
    if question.startswith("/"):
        command = question.split()[0].lower().split("@")[0]
        if command in {"/start", "/help"}:
            return _help(bot, store, chat_id)
        if command == "/reset":
            store.sessions[chat_id] = ChatSession()
            return [Reply("Started a new dialogue. Ask me anything.")]

    answer = bot.respond(store.session(chat_id), question)
    buttons: tuple[QuickReply, ...] = answer.quick
    store.remember_buttons(chat_id, buttons)
    return [Reply(chunk, buttons) for chunk in _chunk(answer.text)]


def _help(bot: Bot, store: ChatStore, chat_id: int) -> list[Reply]:
    from .engine import Answer

    text = bot.settings.help_text or (
        f"{bot.settings.greeting}\n\n"
        "Commands: /start — restart, /help — this message, /reset — new dialogue."
    )
    quick = bot._limit(
        [
            *_question_chips(bot.kb.popular(3)),
            bot._operator_chip(),
        ]
    )
    answer = Answer(intent="help", text=text, matched=False, quick=quick)
    store.remember_buttons(chat_id, answer.quick)
    return [Reply(chunk, answer.quick) for chunk in _chunk(answer.text)]


def _question_chips(items, limit: int = 3) -> list[QuickReply]:
    return [QuickReply(label=item.question, query=item.question) for item in items[:limit]]


def run(kb_path: str, token: str | None = None) -> None:
    """Start long polling. Requires the ``telegram`` extra: pip install faqbot[telegram]."""
    try:
        from aiogram import Bot as TgBot
        from aiogram import Dispatcher, F
        from aiogram.filters import Command
        from aiogram.types import (
            CallbackQuery,
            InlineKeyboardButton,
            InlineKeyboardMarkup,
            Message,
        )
    except ImportError:  # pragma: no cover - depends on optional extra
        sys.exit("Install the Telegram extra first: pip install 'faqbot[telegram]'")

    from .kb import load_kb

    token = token or os.environ.get("FAQBOT_TELEGRAM_TOKEN", "")
    if not token:
        sys.exit("Set FAQBOT_TELEGRAM_TOKEN or pass --token")

    engine = Bot(load_kb(kb_path))
    store = ChatStore()
    dp = Dispatcher()
    tg = TgBot(token)

    def keyboard(buttons: tuple[QuickReply, ...]) -> InlineKeyboardMarkup | None:
        rows = []
        for index, chip in enumerate(buttons):
            if chip.url:
                rows.append([InlineKeyboardButton(text=chip.label, url=chip.url)])
            else:
                rows.append(
                    [InlineKeyboardButton(text=chip.label, callback_data=f"q:{index}")]
                )
        return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None

    @dp.message(Command("start", "help"))
    async def on_help(message: Message) -> None:
        chat_id = message.chat.id
        for reply in handle(engine, store, chat_id, "/help"):
            await message.answer(reply.text, reply_markup=keyboard(reply.buttons))

    @dp.message(Command("reset"))
    async def on_reset(message: Message) -> None:
        chat_id = message.chat.id
        for reply in handle(engine, store, chat_id, "/reset"):
            await message.answer(reply.text)

    @dp.message(F.text)
    async def on_text(message: Message) -> None:
        chat_id = message.chat.id
        for reply in handle(engine, store, chat_id, message.text or ""):
            await message.answer(reply.text, reply_markup=keyboard(reply.buttons))

    @dp.callback_query(F.data.startswith("q:"))
    async def on_click(callback: CallbackQuery) -> None:
        chat_id = callback.message.chat.id if callback.message else 0
        try:
            index = int((callback.data or "q:0").split(":", 1)[1])
        except (IndexError, ValueError):
            await callback.answer()
            return
        chip = store.button(chat_id, index)
        await callback.answer()
        if chip is None:
            return
        if chip.url:
            return
        for reply in handle(engine, store, chat_id, chip.query or chip.label):
            if callback.message:
                await callback.message.answer(
                    reply.text, reply_markup=keyboard(reply.buttons)
                )

    print(f"Bot @{engine.settings.bot_name} is polling. Press Ctrl+C to stop.")
    dp.run_polling(tg)
