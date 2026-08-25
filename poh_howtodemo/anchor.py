"""Поиск и фиксация сценария приёмки.

Единого имени блока в контуре нет: письмо БФТ печатает `**How to demo:**`,
правила репозитория требуют `## HowToDemo`, документ БФТ — `### How to demo`,
канон скилла — `How to demo:` без разметки. Константы-маркера, доступной
потребителям, тоже нет. Поэтому парсер знает все четыре формы и нормализует.

Копию сценария не храним: тело Issue код контура не переписывает нигде, а
комментарии append-only — источник неизменяем. Храним указатель и хэш.

Модуль чистый: ни сети, ни GitHub.
"""

import hashlib
import re
from datetime import datetime, timezone

from poh_howtodemo.model import BODY, COMMENT, Anchor

# Заголовок блока в любой из четырёх встречающихся форм.
_HEADING = re.compile(
    r"^\s*(?:#{2,4}\s*|\*\*)?how\s*to\s*demo\s*:?\s*(?:\*\*)?\s*$",
    re.IGNORECASE,
)
# Следующий заголовок любого вида — граница блока.
_NEXT = re.compile(r"^\s*(?:#{1,6}\s+\S|\*\*[^*]+:?\*\*\s*$)")
_NUMBERED = re.compile(r"^\s*\d+[.)]\s+(.*\S)\s*$")
# Пометка переработанной редакции письма БФТ.
_REVISION = re.compile(r"^\s*_Редакция\s+\d+", re.MULTILINE)


def extract_block(text: str) -> str | None:
    """Вернуть тело блока HowToDemo либо None, если его нет."""
    if not text:
        return None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not _HEADING.match(line):
            continue
        body: list[str] = []
        for nxt in lines[i + 1:]:
            if _NEXT.match(nxt) and body:
                break
            body.append(nxt)
        block = "\n".join(body).strip()
        return block or None
    return None


def parse_steps(block: str | None) -> list[str]:
    """Нумерованные строки блока. Ненумерованное (код, пояснения) отбрасываем."""
    if not block:
        return []
    return [m.group(1) for m in (_NUMBERED.match(ln) for ln in block.splitlines()) if m]


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _is_first_edition(comment: str) -> bool:
    return not _REVISION.search(comment)


def fix(issue: int, body: str,
        comments: list[tuple[int, str]]) -> tuple[Anchor, list[str]] | None:
    """Зафиксировать сценарий.

    Приоритет: раздел в теле Issue → блок первой редакции письма БФТ → ничего.
    Первая редакция, а не последняя: приёмку фиксируем по тому, о чём
    договорились, а не по тому, что переписали ближе к сдаче.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    block = extract_block(body)
    if block:
        return (Anchor(issue=issue, source=BODY, sha256=digest(block), taken_at=now),
                parse_steps(block))
    for comment_id, text in comments:
        if not _is_first_edition(text):
            continue
        block = extract_block(text)
        if block:
            return (Anchor(issue=issue, source=COMMENT, comment_id=comment_id,
                           sha256=digest(block), taken_at=now),
                    parse_steps(block))
    return None


def reread(a: Anchor, body: str,
           comments: list[tuple[int, str]]) -> tuple[list[str], bool]:
    """Перечитать сценарий по указателю. Второе значение — «текст менялся»."""
    if a.source == BODY:
        source_text = body
    else:
        source_text = next((t for cid, t in comments if cid == a.comment_id), "")
    block = extract_block(source_text)
    return parse_steps(block), digest(block or "") != a.sha256
