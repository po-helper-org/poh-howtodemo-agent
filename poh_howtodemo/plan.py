"""Сценарий → машиночитаемый план.

Модель зовётся здесь ровно один раз и только для трансляции текста в действия.
Решать, сошлось ли ожидание, она не будет нигде: вердикт считает verdict.py.

План — артефакт. Повторный прогон переиспользует его, и провал читается как
«шаг 3 не исполнился», а не как молчание.

Модуль чистый: вызов модели приходит параметром.
"""

import json
from dataclasses import asdict
from typing import Callable

from poh_howtodemo.model import BROWSER, CLI, HTTP, UNMAPPED, Action, Expect, Step

KINDS = {HTTP, CLI, BROWSER, UNMAPPED}


class PlanError(Exception):
    """План не годится к исполнению."""


def _action(raw: dict) -> Action:
    kind = raw.get("kind", UNMAPPED)
    if kind not in KINDS:
        raise PlanError(f"неизвестный вид действия: {kind}")
    return Action(kind=kind, method=raw.get("method", "GET"), path=raw.get("path", "/"),
                  body=raw.get("body"), command=raw.get("command", ""))


def _expect(raw: dict) -> Expect:
    return Expect(status=raw.get("status"), json_subset=raw.get("json_subset", {}),
                  contains=raw.get("contains", ""), exit_code=raw.get("exit_code"))


def from_json(raw: str) -> list[Step]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlanError(f"план не разобрался как JSON: {exc}") from exc
    items = data.get("steps")
    if not isinstance(items, list) or not items:
        raise PlanError("в плане нет ни одного шага")
    return [Step(n=item.get("n", i + 1), text=item.get("text", ""),
                 action=_action(item.get("action", {})),
                 expect=_expect(item.get("expect", {})),
                 evidence=list(item.get("evidence", [])),
                 source=item.get("source", ""))
            for i, item in enumerate(items)]


def to_json(steps: list[Step]) -> str:
    return json.dumps({"steps": [asdict(s) for s in steps]}, ensure_ascii=False, indent=2)


def build(scenario: list[str], translate: Callable[[list[str]], str], issue: int,
          strict: bool = True) -> list[Step]:
    """Собрать план по сценарию.

    `strict` — сценарий пришёл нумерованным списком, и тогда число шагов
    обязано совпасть: молча потерянный шаг это молча непроверенное требование,
    самый дорогой класс отказов в контуре.

    Свободная форма (`strict=False`) приезжает одним элементом — блоком `curl`
    с «Ожидаемо: …», как люди пишут HowToDemo в теле Issue. Такой блок
    законно разворачивается в несколько шагов, и требовать совпадения один к
    одному значило бы отвергать нормальный план. Требование остаётся одно:
    хотя бы один шаг.

    `source` перезаписывается кодом. Модель на живом прогоне написала туда
    `Issue #1` вместо `#100`, списав номер из примера промпта, — а ссылка на
    источник требования это часть вердикта, и вердикт модель не пишет.
    """
    steps = from_json(translate(scenario))
    if strict and len(steps) != len(scenario):
        raise PlanError(
            f"в сценарии {len(scenario)} шагов, в плане {len(steps)} — план неполон")
    for step in steps:
        step.source = f"Issue #{issue}, шаг {step.n}"
    return steps
