"""Шаг-запрос: что отправили и что вернулось.

`ok` здесь означает «действие исполнилось», а не «результат правильный».
Правильность считает verdict.py — 404 это исправно исполненный шаг с
неправильным ответом, и различать это обязательно.
"""

import json
from typing import Callable

from poh_howtodemo.model import Action, Observation

Send = Callable[[str, str, dict | None], tuple[int, str]]


def run(action: Action, base_url: str, send: Send) -> Observation:
    url = base_url.rstrip("/") + "/" + action.path.lstrip("/")
    try:
        status, text = send(action.method, url, action.body)
    except Exception as exc:  # сеть, таймаут, отказ — это данные, не авария
        return Observation(ok=False, error=f"{type(exc).__name__}: {exc}")
    try:
        body = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        body = {}
    return Observation(ok=True, status=status, text=text,
                       json_body=body if isinstance(body, dict) else {})
