from __future__ import annotations

import base64
import html
import re
from email import policy
from email.message import Message
from email.parser import BytesParser


def html_to_text(value: str) -> str:
    try:
        from bs4 import BeautifulSoup
        text = BeautifulSoup(value, "html.parser").get_text("\n")
    except ImportError:
        text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def message_text(message: Message) -> str:
    plain: list[str] = []
    rich: list[str] = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        disposition = (part.get_content_disposition() or "").lower()
        if disposition == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        try:
            content = part.get_content()
        except Exception:
            payload = part.get_payload(decode=True) or b""
            content = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        (plain if content_type == "text/plain" else rich).append(str(content))
    return "\n\n".join(plain).strip() or html_to_text("\n\n".join(rich))


def parse_rfc822(content: bytes) -> Message:
    return BytesParser(policy=policy.default).parsebytes(content)


def gmail_body(payload: dict) -> str:
    texts: list[str] = []

    def visit(part: dict) -> None:
        mime_type = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data and mime_type in {"text/plain", "text/html"}:
            decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
            texts.append(decoded if mime_type == "text/plain" else html_to_text(decoded))
        for child in part.get("parts", []):
            visit(child)

    visit(payload)
    return "\n\n".join(texts).strip()

