import asyncio
import re
from typing import List


def chunk_message(text: str, limit: int = 4096) -> List[str]:
    """Split text into Telegram-sized chunks, preferring paragraph boundaries and preserving code blocks."""
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    buf = ""
    code_open = False

    def flush():
        nonlocal buf
        if buf:
            chunks.append(buf)
            buf = ""

    for para in re.split(r"(\n\n+)", text):
        if para.startswith("\n\n"):
            if len(buf) + len(para) <= limit:
                buf += para
            else:
                flush()
                buf = para.lstrip("\n")
            continue

        # track triple-backtick blocks
        ticks = para.count("```")
        if ticks % 2 == 1:
            code_open = not code_open

        if len(buf) + len(para) <= limit:
            buf += para
        else:
            if len(para) > limit:
                # hard split large paragraph
                start = 0
                while start < len(para):
                    rem = limit - len(buf)
                    if rem <= 0:
                        flush()
                        rem = limit
                    buf += para[start : start + rem]
                    start += rem
                    if len(buf) >= limit:
                        flush()
                continue
            flush()
            buf = para

    flush()
    # If we ended inside a code block, close it on the last chunk
    if code_open and chunks:
        chunks[-1] += "\n```"
    return chunks


def escape_markdown(text: str) -> str:
    """Escape Telegram MarkdownV2 special characters in plain text.
    Uses a callable replacer to insert a single backslash before each special.
    """
    specials = r"_[]()~`>#+-=|{}.!"
    pattern = re.compile(f"([\\{specials}])")
    return pattern.sub(lambda m: "\\" + m.group(1), text)


async def typing_pulse(chat_id: int, bot, stop_event: asyncio.Event, interval: float = 3.0) -> None:
    try:
        while not stop_event.is_set():
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
    except Exception:
        return
