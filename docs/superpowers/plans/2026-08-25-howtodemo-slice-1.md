# HowToDemo-Agent, срез 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Агент фиксирует сценарий HowToDemo указателем с хэшем, проходит его шагами `http`/`cli`, считает вердикт кодом и публикует отчёт «Что готово / Что не соответствует» с уликами.

**Architecture:** Чистое ядро (`model`, `anchor`, `plan`, `execute`, `verdict`, `render`) без ввода-вывода, тестируется без сети и докера. Всё касание внешнего мира — в `collectors`, `github`, `publish`, вызывается только из `activities`. Воркфлоу Temporal на своей очереди `howtodemo`, подключается в Harness модулем.

**Tech Stack:** Python 3.11+, `temporalio>=1.9`, `requests>=2.31`, pytest. Никаких других зависимостей.

## Global Constraints

- Пакет ставится ВНУТРЬ образа воркера Harness — в `pyproject.toml` только нижние границы версий, без пинов.
- `poh_howtodemo` не импортирует из Harness ничего. Связь — только через `Protocol`-порты и вызов активностей по имени-строке.
- Модули `model`, `anchor`, `plan`, `execute`, `verdict`, `render` — чистые: ни сети, ни Temporal, ни GitHub, ни `subprocess`.
- Вердикт считает код. Модель не участвует в решении `passed`/`failed` ни в одном месте.
- Комментарии и docstring'и — по-русски, как в `poh-delivery-agent`.
- Каждая задача завершается коммитом. Ветка одна на срез: `feature/slice-1-anchor-and-verdict`, вливается PR'ом.
- Тесты гоняются `pytest -q` из корня репозитория.

---

### Task 1: Модель фактов

**Files:**
- Create: `poh_howtodemo/model.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Consumes: ничего.
- Produces: `Anchor`, `Action`, `Expect`, `Step`, `Observation`, `Evidence`, `StepResult`, `RunReport`; константы `BODY`, `COMMENT`, `HTTP`, `CLI`, `BROWSER`, `UNMAPPED`, `PASSED`, `FAILED`, `SKIPPED`, `BLOCKED`, `V_PASSED`, `V_FAILED`, `V_PARTIAL`, `V_NO_SCENARIO`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_model.py
from dataclasses import asdict

from poh_howtodemo import model


def test_anchor_is_pointer_not_copy():
    """Якорь хранит адрес и хэш источника, а не текст сценария."""
    a = model.Anchor(issue=12, source=model.BODY, sha256="a1b2", taken_at="2026-08-25T10:00:00Z")
    assert asdict(a)["sha256"] == "a1b2"
    assert not hasattr(a, "text")


def test_step_defaults_to_unmapped():
    """Шаг без разобранного действия по умолчанию неисполним, а не 'GET /'."""
    s = model.Step(n=1, text="проверяю письмо")
    assert s.action.kind == model.UNMAPPED
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `pytest tests/test_model.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'poh_howtodemo.model'`

- [ ] **Step 3: Написать модель**

```python
# poh_howtodemo/model.py
"""Факты и решения приёмки — плоские dataclass'ы, ездят через Temporal.

Почему dataclass, а не dict: вход воркфлоу и результаты активностей уезжают в
историю Temporal и живут там дольше кода. Словарь не расскажет, какое поле
пропало при переименовании, — типизированный payload расскажет на первой же
десериализации.

Модуль чистый: ни сети, ни Temporal, ни GitHub.
"""

from dataclasses import dataclass, field

# --- Откуда взят сценарий ---

BODY = "body"        # раздел в теле Issue
COMMENT = "comment"  # блок в письме БФТ

# --- Что шаг делает ---

HTTP = "http"
CLI = "cli"
BROWSER = "browser"      # срез 3, здесь только объявлен
UNMAPPED = "unmapped"    # в действие не превращается — нужен человек

# --- Чем кончился шаг ---

PASSED = "passed"
FAILED = "failed"
SKIPPED = "skipped"    # unmapped: проверять нечем
BLOCKED = "blocked"    # окружения не было

# --- Вердикт прогона (он же метка Issue) ---

V_PASSED = "demo:passed"
V_FAILED = "demo:failed"
V_PARTIAL = "demo:partial"
V_NO_SCENARIO = "demo:no-scenario"


@dataclass
class Anchor:
    """Указатель на сценарий, а не его копия.

    Тело Issue код контура не переписывает, комментарии append-only — источник
    неизменяем, и хранить копию незачем. Хэш нужен ровно для одного: заметить,
    что человек поправил сценарий после фиксации, и сказать об этом вслух.
    """

    issue: int
    source: str = BODY
    comment_id: int = 0
    sha256: str = ""
    taken_at: str = ""


@dataclass
class Action:
    kind: str = UNMAPPED
    method: str = "GET"
    path: str = "/"
    body: dict | None = None
    command: str = ""


@dataclass
class Expect:
    """Ожидание шага. Пустое ожидание — не 'всё сошлось', а 'проверять нечем'."""

    status: int | None = None
    json_subset: dict = field(default_factory=dict)
    contains: str = ""
    exit_code: int | None = None

    def is_empty(self) -> bool:
        return (self.status is None and not self.json_subset
                and not self.contains and self.exit_code is None)


@dataclass
class Step:
    n: int
    text: str
    action: Action = field(default_factory=Action)
    expect: Expect = field(default_factory=Expect)
    evidence: list[str] = field(default_factory=list)
    source: str = ""


@dataclass
class Observation:
    """Что вернулось наружу. Факты, без интерпретации."""

    ok: bool = False
    status: int | None = None
    json_body: dict = field(default_factory=dict)
    text: str = ""
    exit_code: int | None = None
    error: str = ""


@dataclass
class Evidence:
    name: str = ""   # response | command | service_log
    path: str = ""   # относительный путь в каталоге прогона


@dataclass
class StepResult:
    n: int
    text: str
    outcome: str = FAILED
    detail: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    source: str = ""


@dataclass
class RunReport:
    anchor: Anchor
    results: list[StepResult] = field(default_factory=list)
    verdict: str = V_FAILED
    scenario_changed: bool = False
    ref: str = ""
    pr_number: int = 0
    evidence_branch: str = ""
```

- [ ] **Step 4: Запустить тест, убедиться, что проходит**

Run: `pytest tests/test_model.py -q`
Expected: PASS, 2 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/model.py tests/test_model.py
git commit -m "feat(model): факты приёмки — якорь-указатель, шаг, наблюдение, вердикт"
```

---

### Task 2: Якорь — фиксация сценария

**Files:**
- Create: `poh_howtodemo/anchor.py`
- Test: `tests/test_anchor.py`

**Interfaces:**
- Consumes: `model.Anchor`, `model.BODY`, `model.COMMENT`.
- Produces: `extract_block(text) -> str | None`, `parse_steps(block) -> list[str]`, `digest(text) -> str`, `fix(issue, body, comments) -> tuple[Anchor, list[str]] | None`, `reread(anchor, body, comments) -> tuple[list[str], bool]`.
  `comments` везде — `list[tuple[int, str]]` (id, тело), в порядке публикации.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_anchor.py
from poh_howtodemo import anchor, model

BODY_FORM = """Надо починить расчёт.

## HowToDemo

1. Отправить `GET /healthz`.
2. Увидеть 200 и поле `status`.

Прочее.
"""

LETTER_FORM = """## 📋 БФТ (быстрый проход)

**Цель:** что-то.

**How to demo:**
1. Открыть страницу.
2. Нажать кнопку.

**Открытые вопросы:**
- нет
"""


def test_finds_section_in_issue_body():
    steps = anchor.parse_steps(anchor.extract_block(BODY_FORM))
    assert steps == ["Отправить `GET /healthz`.", "Увидеть 200 и поле `status`."]


def test_finds_bold_block_in_bft_letter():
    steps = anchor.parse_steps(anchor.extract_block(LETTER_FORM))
    assert steps == ["Открыть страницу.", "Нажать кнопку."]


def test_body_wins_over_letter():
    got = anchor.fix(12, BODY_FORM, [(7, LETTER_FORM)])
    assert got is not None
    a, steps = got
    assert a.source == model.BODY and a.comment_id == 0
    assert steps[0].startswith("Отправить")


def test_first_letter_edition_wins_over_later():
    later = LETTER_FORM.replace("**Цель:**", "_Редакция 2 — с учётом замечаний из обсуждения._\n\n**Цель:**")
    got = anchor.fix(12, "нет сценария", [(7, LETTER_FORM), (9, later)])
    assert got is not None
    a, _ = got
    assert a.source == model.COMMENT and a.comment_id == 7


def test_no_scenario_anywhere():
    assert anchor.fix(12, "просто текст", [(7, "и тут ничего")]) is None


def test_reread_reports_change():
    a, _ = anchor.fix(12, BODY_FORM, [])
    changed_body = BODY_FORM.replace("200", "204")
    steps, changed = anchor.reread(a, changed_body, [])
    assert changed is True
    assert "204" in steps[1]
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `pytest tests/test_anchor.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'poh_howtodemo.anchor'`

- [ ] **Step 3: Написать якорь**

```python
# poh_howtodemo/anchor.py
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
        return Anchor(issue=issue, source=BODY, sha256=digest(block), taken_at=now), parse_steps(block)
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
```

- [ ] **Step 4: Запустить тест, убедиться, что проходит**

Run: `pytest tests/test_anchor.py -q`
Expected: PASS, 6 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/anchor.py tests/test_anchor.py
git commit -m "feat(anchor): фиксация сценария указателем с хэшем, четыре формы блока"
```

---

### Task 3: План — сценарий в действия

**Files:**
- Create: `poh_howtodemo/plan.py`
- Test: `tests/test_plan.py`

**Interfaces:**
- Consumes: `model.Step`, `model.Action`, `model.Expect`, константы видов.
- Produces: `build(steps, translate) -> list[Step]`, `from_json(raw) -> list[Step]`, `to_json(steps) -> str`, исключение `PlanError`.
  `translate` — вызываемое `(list[str]) -> str`, возвращает JSON-текст плана. В тестах подделка, в бою — порт LLM.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_plan.py
import json

import pytest

from poh_howtodemo import model, plan

RAW = json.dumps({"steps": [
    {"n": 1, "text": "GET /healthz", "action": {"kind": "http", "method": "GET", "path": "/healthz"},
     "expect": {"status": 200, "json_subset": {"status": "ok"}}, "evidence": ["response"],
     "source": "Issue #12, шаг 1"},
    {"n": 2, "text": "проверяю письмо", "action": {"kind": "unmapped"},
     "expect": {}, "evidence": [], "source": "Issue #12, шаг 2"},
]})


def test_unmapped_step_survives_and_is_not_an_error():
    """Неисполнимый шаг — штатный исход. План с ним валиден."""
    steps = plan.from_json(RAW)
    assert steps[1].action.kind == model.UNMAPPED
    assert steps[1].expect.is_empty()


def test_http_step_carries_expectation():
    steps = plan.from_json(RAW)
    assert steps[0].action.path == "/healthz"
    assert steps[0].expect.json_subset == {"status": "ok"}


def test_unknown_kind_is_rejected():
    bad = json.dumps({"steps": [{"n": 1, "text": "x", "action": {"kind": "telepathy"}}]})
    with pytest.raises(plan.PlanError, match="telepathy"):
        plan.from_json(bad)


def test_plan_must_cover_every_step():
    """Модель обязана вернуть столько же шагов, сколько в сценарии."""
    def translate(_steps):
        return json.dumps({"steps": [{"n": 1, "text": "a", "action": {"kind": "unmapped"}}]})

    with pytest.raises(plan.PlanError, match="2"):
        plan.build(["a", "b"], translate)


def test_roundtrip_is_stable():
    steps = plan.from_json(RAW)
    assert plan.from_json(plan.to_json(steps)) == steps
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `pytest tests/test_plan.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'poh_howtodemo.plan'`

- [ ] **Step 3: Написать план**

```python
# poh_howtodemo/plan.py
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


def build(scenario: list[str], translate: Callable[[list[str]], str]) -> list[Step]:
    """Собрать план по сценарию.

    Число шагов обязано совпасть: молча потерянный шаг — это молча
    непроверенное требование, самый дорогой класс отказов в контуре.
    """
    steps = from_json(translate(scenario))
    if len(steps) != len(scenario):
        raise PlanError(
            f"в сценарии {len(scenario)} шагов, в плане {len(steps)} — план неполон")
    return steps
```

- [ ] **Step 4: Запустить тест, убедиться, что проходит**

Run: `pytest tests/test_plan.py -q`
Expected: PASS, 5 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/plan.py tests/test_plan.py
git commit -m "feat(plan): трансляция сценария в действия, unmapped как штатный исход"
```

---

### Task 4: Сборщики улик — HTTP и CLI

**Files:**
- Create: `poh_howtodemo/collectors/http.py`, `poh_howtodemo/collectors/cli.py`
- Test: `tests/test_collectors.py`

**Interfaces:**
- Consumes: `model.Action`, `model.Observation`.
- Produces: `http.run(action, base_url, send) -> Observation`, `cli.run(action, cwd, exec_) -> Observation`.
  `send` — `(method, url, json) -> tuple[int, str]`; `exec_` — `(command, cwd) -> tuple[int, str]`. Оба подставляются: в бою `requests`/`subprocess`, в тестах подделки. Ни один сборщик не роняет исключение наружу — отказ едет в `Observation.error`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_collectors.py
from poh_howtodemo import model
from poh_howtodemo.collectors import cli, http


def test_http_parses_json_body():
    obs = http.run(model.Action(kind=model.HTTP, method="GET", path="/healthz"),
                   "http://svc:8080",
                   send=lambda m, u, j: (200, '{"status": "ok"}'))
    assert obs.ok and obs.status == 200 and obs.json_body == {"status": "ok"}


def test_http_failure_is_data_not_exception():
    def boom(*_args, **_kw):
        raise OSError("connection refused")

    obs = http.run(model.Action(kind=model.HTTP, path="/x"), "http://svc:8080", send=boom)
    assert obs.ok is False and "connection refused" in obs.error


def test_http_keeps_text_when_body_is_not_json():
    obs = http.run(model.Action(kind=model.HTTP, path="/"), "http://svc:8080",
                   send=lambda m, u, j: (404, "не найдено"))
    assert obs.ok is True and obs.status == 404 and obs.json_body == {}
    assert obs.text == "не найдено"


def test_cli_captures_exit_code_and_output():
    obs = cli.run(model.Action(kind=model.CLI, command="node --test"), "/w",
                  exec_=lambda c, cwd: (1, "1 failing"))
    assert obs.ok is True and obs.exit_code == 1 and "1 failing" in obs.text
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `pytest tests/test_collectors.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'poh_howtodemo.collectors.http'`

- [ ] **Step 3: Написать сборщики**

```python
# poh_howtodemo/collectors/http.py
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
```

```python
# poh_howtodemo/collectors/cli.py
"""Шаг-команда: код возврата и вывод.

Ненулевой код возврата — это исполненный шаг с плохим результатом, а не
несостоявшийся шаг. Различие то же, что у HTTP: `ok` про исполнение.
"""

from typing import Callable

from poh_howtodemo.model import Action, Observation

Exec = Callable[[str, str], tuple[int, str]]


def run(action: Action, cwd: str, exec_: Exec) -> Observation:
    if not action.command.strip():
        return Observation(ok=False, error="в шаге нет команды")
    try:
        code, output = exec_(action.command, cwd)
    except Exception as exc:
        return Observation(ok=False, error=f"{type(exc).__name__}: {exc}")
    return Observation(ok=True, exit_code=code, text=output)
```

- [ ] **Step 4: Запустить тест, убедиться, что проходит**

Run: `pytest tests/test_collectors.py -q`
Expected: PASS, 4 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/collectors tests/test_collectors.py
git commit -m "feat(collectors): сбор улик по HTTP и CLI, отказ едет данными"
```

---

### Task 5: Вердикт — считает код

**Files:**
- Create: `poh_howtodemo/verdict.py`
- Test: `tests/test_verdict.py`

**Interfaces:**
- Consumes: `model.Step`, `model.Observation`, `model.Evidence`, `model.StepResult`, константы исходов.
- Produces: `judge(step, obs, evidence) -> StepResult`, `overall(results) -> str`.
  `obs=None` означает «действие не запускалось» (нет окружения) → `BLOCKED`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_verdict.py
from poh_howtodemo import model, verdict

EV = [model.Evidence(name="response", path="evidence/step-1/response.json")]


def _step(**kw):
    base = dict(n=1, text="GET /healthz",
                action=model.Action(kind=model.HTTP, path="/healthz"),
                expect=model.Expect(status=200, json_subset={"status": "ok"}))
    base.update(kw)
    return model.Step(**base)


def test_passed_needs_action_expectation_and_evidence():
    obs = model.Observation(ok=True, status=200, json_body={"status": "ok", "uptime_sec": 5})
    assert verdict.judge(_step(), obs, EV).outcome == model.PASSED


def test_missing_evidence_is_not_passed():
    """Совпавшее ожидание без улик — не зачёт: доказать нечем."""
    obs = model.Observation(ok=True, status=200, json_body={"status": "ok"})
    res = verdict.judge(_step(), obs, [])
    assert res.outcome == model.FAILED and "улик" in res.detail


def test_wrong_field_names_expected_and_actual():
    obs = model.Observation(ok=True, status=200, json_body={"ok": True})
    res = verdict.judge(_step(), obs, EV)
    assert res.outcome == model.FAILED
    assert "status" in res.detail and "ok" in res.detail


def test_unmapped_is_skipped_not_failed():
    step = _step(action=model.Action(kind=model.UNMAPPED), expect=model.Expect())
    assert verdict.judge(step, None, []).outcome == model.SKIPPED


def test_no_environment_is_blocked():
    assert verdict.judge(_step(), None, []).outcome == model.BLOCKED


def test_empty_expectation_never_passes():
    """Шаг без ожидания нечем проверить — молча зачесть его нельзя."""
    step = _step(expect=model.Expect())
    obs = model.Observation(ok=True, status=200)
    assert verdict.judge(step, obs, EV).outcome == model.BLOCKED


def test_overall_partial_when_something_skipped():
    ok = model.StepResult(n=1, text="a", outcome=model.PASSED)
    skipped = model.StepResult(n=2, text="b", outcome=model.SKIPPED)
    assert verdict.overall([ok, skipped]) == model.V_PARTIAL


def test_overall_failed_beats_partial():
    bad = model.StepResult(n=1, text="a", outcome=model.FAILED)
    skipped = model.StepResult(n=2, text="b", outcome=model.SKIPPED)
    assert verdict.overall([bad, skipped]) == model.V_FAILED
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `pytest tests/test_verdict.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'poh_howtodemo.verdict'`

- [ ] **Step 3: Написать вердикт**

```python
# poh_howtodemo/verdict.py
"""Вердикт приёмки. Считает код, не модель.

В контуре уже есть ровно этот дефект: пайплайн БФТ проверяет артефакт на
существование, а вердикт стадии пишет сама же модель. Итог — успех, доложенный
на пустом месте. Здесь модель не участвует в решении нигде.

Зачёт требует трёх вещей сразу: действие исполнилось, ожидание совпало, улики
собраны. Ослабление любого из трёх делает провал неотличимым от успеха.

Модуль чистый.
"""

from poh_howtodemo.model import (BLOCKED, FAILED, PASSED, SKIPPED, UNMAPPED,
                                 V_FAILED, V_NO_SCENARIO, V_PARTIAL, V_PASSED,
                                 Evidence, Observation, Step, StepResult)


def _mismatch(step: Step, obs: Observation) -> str:
    """Первое расхождение ожидания с фактом, словами. Пусто — сошлось."""
    exp = step.expect
    if exp.status is not None and obs.status != exp.status:
        return f"код ответа: ожидался {exp.status}, пришёл {obs.status}"
    for key, want in exp.json_subset.items():
        got = obs.json_body.get(key)
        if got != want:
            return f"поле `{key}`: ожидалось {want!r}, пришло {got!r}"
    if exp.contains and exp.contains not in obs.text:
        return f"в ответе нет подстроки {exp.contains!r}"
    if exp.exit_code is not None and obs.exit_code != exp.exit_code:
        return f"код возврата: ожидался {exp.exit_code}, пришёл {obs.exit_code}"
    return ""


def judge(step: Step, obs: Observation | None,
          evidence: list[Evidence]) -> StepResult:
    out = StepResult(n=step.n, text=step.text, source=step.source, evidence=list(evidence))
    if step.action.kind == UNMAPPED:
        out.outcome = SKIPPED
        out.detail = "шаг не превращается в действие — нужен человек"
        return out
    if obs is None:
        out.outcome = BLOCKED
        out.detail = "шаг не запускался: окружения не было"
        return out
    if not obs.ok:
        out.outcome = FAILED
        out.detail = obs.error or "действие не исполнилось"
        return out
    if step.expect.is_empty():
        out.outcome = BLOCKED
        out.detail = "у шага нет ожидания — проверять нечем"
        return out
    detail = _mismatch(step, obs)
    if detail:
        out.outcome = FAILED
        out.detail = detail
        return out
    if not evidence:
        out.outcome = FAILED
        out.detail = "ожидание сошлось, но улик не собрано — подтвердить нечем"
        return out
    out.outcome = PASSED
    return out


def overall(results: list[StepResult]) -> str:
    if not results:
        return V_NO_SCENARIO
    outcomes = {r.outcome for r in results}
    if FAILED in outcomes:
        return V_FAILED
    if SKIPPED in outcomes or BLOCKED in outcomes:
        return V_PARTIAL
    return V_PASSED
```

- [ ] **Step 4: Запустить тест, убедиться, что проходит**

Run: `pytest tests/test_verdict.py -q`
Expected: PASS, 8 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/verdict.py tests/test_verdict.py
git commit -m "feat(verdict): зачёт только при исполнении, совпадении и уликах"
```

---

### Task 6: Отчёт

**Files:**
- Create: `poh_howtodemo/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `model.RunReport`, `model.StepResult`, константы исходов и вердиктов.
- Produces: `report_md(report) -> str`, `no_scenario_md(issue) -> str`, константа `MARKER = "<!-- howtodemo:verdict -->"`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_render.py
from poh_howtodemo import model, render


def _report():
    a = model.Anchor(issue=12, source=model.BODY, sha256="a1b2c3d4", taken_at="2026-08-25T10:00:00Z")
    return model.RunReport(
        anchor=a, pr_number=45, ref="feature/12-cart@3a1f0c2",
        evidence_branch="howtodemo/issue-12",
        verdict=model.V_FAILED,
        results=[
            model.StepResult(n=1, text="GET /healthz", outcome=model.PASSED,
                             evidence=[model.Evidence(name="response", path="evidence/step-1/response.json")]),
            model.StepResult(n=2, text="итог 2300", outcome=model.FAILED,
                             detail="поле `total`: ожидалось 2300, пришло 2000",
                             source="Issue #12, шаг 2"),
            model.StepResult(n=3, text="проверяю письмо", outcome=model.SKIPPED,
                             detail="шаг не превращается в действие — нужен человек"),
        ])


def test_report_splits_ready_from_mismatched():
    body = render.report_md(_report())
    ready, rest = body.split("### Что не соответствует")
    assert "GET /healthz" in ready and "GET /healthz" not in rest
    assert "итог 2300" in rest


def test_mismatch_carries_detail_and_source():
    body = render.report_md(_report())
    assert "ожидалось 2300, пришло 2000" in body
    assert "Issue #12, шаг 2" in body


def test_skipped_is_separated_from_failure():
    body = render.report_md(_report())
    assert "⚠️" in body and "нужен человек" in body


def test_report_names_anchor_and_evidence():
    body = render.report_md(_report())
    assert "a1b2c3d4"[:8] in body and "howtodemo/issue-12" in body
    assert render.MARKER in body


def test_changed_scenario_is_said_out_loud():
    rep = _report()
    rep.scenario_changed = True
    assert "менялся после фиксации" in render.report_md(rep)
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `pytest tests/test_render.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'poh_howtodemo.render'`

- [ ] **Step 3: Написать отчёт**

```python
# poh_howtodemo/render.py
"""Отчёт приёмки: что готово, что не соответствует.

Две секции, а не одна таблица: человек читает отчёт, чтобы решить, брать ли
работу, и «не соответствует» должно быть видно раньше, чем он устанет.

Маркер-строка в конце — чтобы соседний агент нашёл вердикт в треде, как
Delivery находит вердикт круга правок.

Модуль чистый.
"""

from poh_howtodemo.model import (BLOCKED, FAILED, PASSED, SKIPPED, RunReport,
                                 V_FAILED, V_PARTIAL, V_PASSED)

MARKER = "<!-- howtodemo:verdict -->"

_ICON = {PASSED: "✅", FAILED: "❌", SKIPPED: "⚠️", BLOCKED: "⏸"}
_WORD = {V_PASSED: "сценарий пройден", V_FAILED: "сценарий не пройден",
         V_PARTIAL: "пройден частично"}


def _line(res) -> str:
    head = f"{_ICON.get(res.outcome, '·')} {res.n}. {res.text}"
    if res.detail:
        head += f"\n      {res.detail}"
    if res.source:
        head += f"\n      Источник требования: {res.source}"
    for ev in res.evidence:
        head += f"\n      [{ev.name}]({ev.path})"
    return head


def report_md(rep: RunReport) -> str:
    where = f"PR #{rep.pr_number}" if rep.pr_number else "прогон"
    out = [f"## HowToDemo — {where} ({rep.ref})" if rep.ref else f"## HowToDemo — {where}",
           "",
           f"Сценарий зафиксирован {rep.anchor.taken_at}: "
           f"{'тело Issue' if rep.anchor.comment_id == 0 else f'комментарий {rep.anchor.comment_id}'} "
           f"#{rep.anchor.issue}, sha256 `{rep.anchor.sha256[:8]}…`",
           f"Вердикт: **{_WORD.get(rep.verdict, rep.verdict)}** (`{rep.verdict}`)"]
    if rep.scenario_changed:
        out.append("")
        out.append("> ⚠️ Сценарий **менялся после фиксации**. Прогон шёл по "
                   "зафиксированной редакции — сверьте расхождение вручную.")

    ready = [r for r in rep.results if r.outcome == PASSED]
    broken = [r for r in rep.results if r.outcome == FAILED]
    aside = [r for r in rep.results if r.outcome in (SKIPPED, BLOCKED)]

    out += ["", "### Что готово", ""]
    out += [_line(r) for r in ready] or ["Ни один шаг не зачтён."]
    out += ["", "### Что не соответствует", ""]
    out += [_line(r) for r in broken] or ["Расхождений нет."]
    if aside:
        out += ["", "### Требует человека", ""]
        out += [_line(r) for r in aside]
    if rep.evidence_branch:
        out += ["", "### Улики", "",
                f"Ветка `{rep.evidence_branch}`, каталог `evidence/`."]
    out += ["", MARKER]
    return "\n".join(out)


def no_scenario_md(issue: int) -> str:
    return "\n".join([
        "## HowToDemo — критерия готовности нет",
        "",
        f"В Issue #{issue} нет раздела HowToDemo, и в письме БФТ блока "
        "`How to demo` тоже нет. Проверять приёмку нечем.",
        "",
        "Добавьте раздел `## HowToDemo` в тело Issue и позовите `/howtodemo` заново.",
        "",
        MARKER,
    ])
```

- [ ] **Step 4: Запустить тест, убедиться, что проходит**

Run: `pytest tests/test_render.py -q`
Expected: PASS, 5 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/render.py tests/test_render.py
git commit -m "feat(render): отчёт «Что готово / Что не соответствует» с маркером вердикта"
```

---

### Task 7: Порты и реализация GitHub

**Files:**
- Create: `poh_howtodemo/ports.py`, `poh_howtodemo/github.py`
- Test: `tests/test_ports.py`

**Interfaces:**
- Consumes: ничего из ядра, кроме типов.
- Produces: протоколы `GitHubPort` (`issue_body`, `comments`, `comment`, `add_label`, `remove_labels`, `pull_head`), `LlmPort` (`translate`), `ShellPort` (`run`); функции `configure(github=None, llm=None, shell=None)`, `github()`, `llm()`, `shell()`; класс `RestGitHub(token_provider)`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_ports.py
import pytest

from poh_howtodemo import ports


class _Fake:
    def issue_body(self, repo, number): return "тело"
    def comments(self, repo, number): return [(1, "текст")]
    def comment(self, repo, number, body): return None
    def add_label(self, repo, number, label): return None
    def remove_labels(self, repo, number, labels): return None
    def pull_head(self, repo, number): return ("feature/x", "abc123")


def test_ports_must_be_configured_before_use():
    ports.configure(github=None, llm=None, shell=None)
    with pytest.raises(RuntimeError, match="не подставлен"):
        ports.github()


def test_configure_supplies_implementation():
    ports.configure(github=_Fake())
    assert ports.github().issue_body("o/r", 1) == "тело"
    ports.configure(github=None)
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `pytest tests/test_ports.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'poh_howtodemo.ports'`

- [ ] **Step 3: Написать порты**

```python
# poh_howtodemo/ports.py
"""Порты: чем агент разговаривает с GitHub, моделью и оболочкой.

Порт, а не прямой вызов клиента Harness, — потому что агент живёт в своём
репозитории и обязан собираться и тестироваться без него. Harness подставляет
реализации на старте воркера, тесты — свои заглушки.
"""

from typing import Protocol


class GitHubPort(Protocol):
    def issue_body(self, repo: str, number: int) -> str: ...
    def comments(self, repo: str, number: int) -> list[tuple[int, str]]: ...
    def comment(self, repo: str, number: int, body: str) -> None: ...
    def add_label(self, repo: str, number: int, label: str) -> None: ...
    def remove_labels(self, repo: str, number: int, labels: list[str]) -> None: ...
    def pull_head(self, repo: str, number: int) -> tuple[str, str]: ...


class LlmPort(Protocol):
    def translate(self, scenario: list[str]) -> str: ...


class ShellPort(Protocol):
    def run(self, command: str, cwd: str) -> tuple[int, str]: ...


_github: GitHubPort | None = None
_llm: LlmPort | None = None
_shell: ShellPort | None = None


def configure(github: GitHubPort | None = None, llm: LlmPort | None = None,
              shell: ShellPort | None = None) -> None:
    """Подставить реализации. Зовётся один раз на старте воркера."""
    global _github, _llm, _shell
    _github, _llm, _shell = github, llm, shell


def github() -> GitHubPort:
    if _github is None:
        raise RuntimeError("порт GitHub не подставлен — зовите ports.configure()")
    return _github


def llm() -> LlmPort:
    if _llm is None:
        raise RuntimeError("порт модели не подставлен — зовите ports.configure()")
    return _llm


def shell() -> ShellPort:
    if _shell is None:
        raise RuntimeError("порт оболочки не подставлен — зовите ports.configure()")
    return _shell
```

```python
# poh_howtodemo/github.py
"""GitHub поверх REST. Токен приходит функцией-провайдером от Harness.

Токен берётся на каждый вызов, а не один раз на прогон: installation-токен
живёт час, а приёмка вместе с подъёмом окружения занимает минуты — кэш,
считающий токен годным при остатке в секунды, уже ронял ревью на
`401 Bad credentials` посреди работы.
"""

from typing import Callable

import requests

API = "https://api.github.com"
TIMEOUT = 30


class RestGitHub:
    def __init__(self, token_provider: Callable[[], str]):
        self._token = token_provider

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}",
                "Accept": "application/vnd.github+json"}

    def issue_body(self, repo: str, number: int) -> str:
        r = requests.get(f"{API}/repos/{repo}/issues/{number}",
                         headers=self._headers(), timeout=TIMEOUT)
        r.raise_for_status()
        return r.json().get("body") or ""

    def comments(self, repo: str, number: int) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        page = 1
        while True:
            r = requests.get(f"{API}/repos/{repo}/issues/{number}/comments",
                             headers=self._headers(), timeout=TIMEOUT,
                             params={"per_page": 100, "page": page})
            r.raise_for_status()
            batch = r.json()
            out += [(c["id"], c.get("body") or "") for c in batch]
            if len(batch) < 100:
                return out
            page += 1

    def comment(self, repo: str, number: int, body: str) -> None:
        r = requests.post(f"{API}/repos/{repo}/issues/{number}/comments",
                          headers=self._headers(), timeout=TIMEOUT, json={"body": body})
        r.raise_for_status()

    def add_label(self, repo: str, number: int, label: str) -> None:
        r = requests.post(f"{API}/repos/{repo}/issues/{number}/labels",
                          headers=self._headers(), timeout=TIMEOUT, json={"labels": [label]})
        r.raise_for_status()

    def remove_labels(self, repo: str, number: int, labels: list[str]) -> None:
        for label in labels:
            # 404 = метки и не было. Снятие несуществующей метки — не отказ.
            requests.delete(f"{API}/repos/{repo}/issues/{number}/labels/{label}",
                            headers=self._headers(), timeout=TIMEOUT)

    def pull_head(self, repo: str, number: int) -> tuple[str, str]:
        r = requests.get(f"{API}/repos/{repo}/pulls/{number}",
                         headers=self._headers(), timeout=TIMEOUT)
        r.raise_for_status()
        head = r.json()["head"]
        return head["ref"], head["sha"]
```

- [ ] **Step 4: Запустить тест, убедиться, что проходит**

Run: `pytest tests/test_ports.py -q`
Expected: PASS, 2 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/ports.py poh_howtodemo/github.py tests/test_ports.py
git commit -m "feat(ports): протоколы GitHub/модели/оболочки и реализация поверх REST"
```

---

### Task 8: Публикация улик git-пушем

**Files:**
- Create: `poh_howtodemo/publish.py`
- Test: `tests/test_publish.py`

**Interfaces:**
- Consumes: `model.Evidence`.
- Produces: `branch_name(issue) -> str`, `write_evidence(root, step_n, name, data) -> Evidence`, `push(root, repo, branch, token, run_git) -> bool`.
  `run_git` — `(args: list[str], cwd: str) -> tuple[int, str]`, подставляется.

Contents API здесь не используется намеренно: `put_file` в Harness типизирован `content: str` и делает `content.encode("utf-8")` — PNG через него не проходит.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_publish.py
from pathlib import Path

from poh_howtodemo import publish


def test_branch_is_one_per_issue():
    assert publish.branch_name(12) == "howtodemo/issue-12"


def test_evidence_lands_in_step_directory(tmp_path):
    ev = publish.write_evidence(str(tmp_path), 3, "response.json", b'{"a": 1}')
    assert ev.path == "evidence/step-3/response.json"
    assert (tmp_path / ev.path).read_bytes() == b'{"a": 1}'


def test_token_appears_only_in_the_push_call(tmp_path):
    """Токен живёт в одном аргументе одной команды и больше нигде."""
    calls = []

    def run_git(args, cwd):
        calls.append(args)
        return 0, "ok"

    ok = publish.push(str(tmp_path), "o/r", "howtodemo/issue-12", "ghs_secret", run_git)
    assert ok is True
    carrying = [args for args in calls if any("ghs_secret" in a for a in args)]
    assert len(carrying) == 1 and carrying[0][0] == "push"


def test_push_reports_failure_instead_of_raising(tmp_path):
    ok = publish.push(str(tmp_path), "o/r", "b", "t", lambda a, c: (1, "rejected"))
    assert ok is False
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `pytest tests/test_publish.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'poh_howtodemo.publish'`

- [ ] **Step 3: Написать публикацию**

```python
# poh_howtodemo/publish.py
"""Улики уезжают в ветку своим git-пушем.

Contents API этот путь не закрывает: `put_file` в Harness типизирован
`content: str` и кодирует его в UTF-8 — PNG через него не пройдёт вовсе.
Функции с `bytes` в клиенте нет, загрузки вложений нет. Поэтому пишем файлы в
рабочий каталог и пушим git'ом, которому бинарники безразличны.

Ветка одна на Issue: повторный прогон перезаписывает предыдущий. Скриншоты
растут, а места на стенде мало.
"""

import os
from typing import Callable

from poh_howtodemo.model import Evidence

Git = Callable[[list[str], str], tuple[int, str]]


def branch_name(issue: int) -> str:
    return f"howtodemo/issue-{issue}"


def write_evidence(root: str, step_n: int, name: str, data: bytes) -> Evidence:
    rel = os.path.join("evidence", f"step-{step_n}", name)
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(data)
    return Evidence(name=name, path=rel)


def push(root: str, repo: str, branch: str, token: str, run_git: Git) -> bool:
    """Запушить каталог улик в ветку. Отказ возвращается, а не бросается.

    Провал публикации не должен ронять прогон: вердикт уже посчитан, и потерять
    его из-за недоступного remote было бы хуже, чем остаться без картинок.
    """
    remote = f"https://x-access-token:{token}@github.com/{repo}.git"
    steps = [
        ["init", "-q", "-b", branch],
        ["add", "-A", "evidence"],
        ["-c", "user.name=howtodemo-agent",
         "-c", "user.email=howtodemo-agent@users.noreply.github.com",
         "commit", "-q", "-m", f"evidence: прогон HowToDemo ({branch})"],
        ["push", "-q", "--force", remote, f"HEAD:refs/heads/{branch}"],
    ]
    for args in steps:
        code, output = run_git(args, root)
        if code != 0:
            # Токен в тексте отказа не оставляем — он уедет в лог и в Sentry.
            return False
    return True
```

- [ ] **Step 4: Запустить тест, убедиться, что проходит**

Run: `pytest tests/test_publish.py -q`
Expected: PASS, 4 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/publish.py tests/test_publish.py
git commit -m "feat(publish): улики в ветку git-пушем, Contents API бинарники не умеет"
```

---

### Task 9: Прогон целиком

**Files:**
- Create: `poh_howtodemo/run.py`
- Test: `tests/test_run.py`

**Interfaces:**
- Consumes: `anchor`, `plan`, `verdict`, `render`, `publish`, `collectors.http`, `collectors.cli`, `model.*`.
- Produces: `verify(repo, issue, pr_number, base_url, root, gh, translate, send, exec_, run_git, token) -> RunReport`.
  Все внешние взаимодействия приходят параметрами — функция остаётся тестируемой без сети. `base_url=""` означает «окружения нет»: HTTP-шаги получают `obs=None` и станут `BLOCKED`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_run.py
import json

from poh_howtodemo import model, run

BODY = """## HowToDemo

1. Отправить `GET /healthz`, увидеть 200 и `status=ok`.
2. Проверить входящее письмо.
"""

PLAN = json.dumps({"steps": [
    {"n": 1, "text": "GET /healthz", "action": {"kind": "http", "path": "/healthz"},
     "expect": {"status": 200, "json_subset": {"status": "ok"}}, "evidence": ["response"],
     "source": "Issue #12, шаг 1"},
    {"n": 2, "text": "проверяю письмо", "action": {"kind": "unmapped"}, "expect": {},
     "source": "Issue #12, шаг 2"},
]})


class _GH:
    def __init__(self): self.comments_posted = []; self.labels = []
    def issue_body(self, repo, number): return BODY
    def comments(self, repo, number): return []
    def comment(self, repo, number, body): self.comments_posted.append(body)
    def add_label(self, repo, number, label): self.labels.append(label)
    def remove_labels(self, repo, number, labels): pass
    def pull_head(self, repo, number): return ("feature/12", "3a1f0c2")


def _run(gh, tmp_path, send):
    return run.verify(repo="o/r", issue=12, pr_number=45, base_url="http://svc:8080",
                      root=str(tmp_path), gh=gh, translate=lambda s: PLAN, send=send,
                      exec_=lambda c, cwd: (0, ""), run_git=lambda a, c: (0, ""),
                      token="t")


def test_green_http_step_and_unmapped_give_partial(tmp_path):
    gh = _GH()
    rep = _run(gh, tmp_path, send=lambda m, u, j: (200, '{"status": "ok"}'))
    assert rep.verdict == model.V_PARTIAL
    assert rep.results[0].outcome == model.PASSED
    assert rep.results[1].outcome == model.SKIPPED


def test_evidence_is_written_for_executed_step(tmp_path):
    rep = _run(_GH(), tmp_path, send=lambda m, u, j: (200, '{"status": "ok"}'))
    assert rep.results[0].evidence
    assert (tmp_path / rep.results[0].evidence[0].path).exists()


def test_mismatch_gives_failed_verdict(tmp_path):
    rep = _run(_GH(), tmp_path, send=lambda m, u, j: (200, '{"status": "degraded"}'))
    assert rep.verdict == model.V_FAILED
    assert "degraded" in rep.results[0].detail


def test_no_environment_blocks_http_steps(tmp_path):
    rep = run.verify(repo="o/r", issue=12, pr_number=0, base_url="", root=str(tmp_path),
                     gh=_GH(), translate=lambda s: PLAN, send=None,
                     exec_=lambda c, cwd: (0, ""), run_git=lambda a, c: (0, ""), token="t")
    assert rep.results[0].outcome == model.BLOCKED
    assert rep.verdict == model.V_PARTIAL


def test_missing_scenario_returns_no_scenario(tmp_path):
    class _Empty(_GH):
        def issue_body(self, repo, number): return "просто текст"

    rep = _run(_Empty(), tmp_path, send=lambda m, u, j: (200, "{}"))
    assert rep.verdict == model.V_NO_SCENARIO
    assert rep.results == []
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `pytest tests/test_run.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'poh_howtodemo.run'`

- [ ] **Step 3: Написать прогон**

```python
# poh_howtodemo/run.py
"""Прогон приёмки целиком: якорь → план → шаги → вердикт → отчёт.

Всё внешнее приходит параметрами, поэтому прогон целиком проверяется без сети,
без докера и без Temporal. Активности только подставляют настоящие реализации.
"""

import json

from poh_howtodemo import anchor, plan, publish, render, verdict
from poh_howtodemo.collectors import cli as cli_collector
from poh_howtodemo.collectors import http as http_collector
from poh_howtodemo.model import (BROWSER, CLI, HTTP, UNMAPPED, Anchor, RunReport,
                                 V_NO_SCENARIO)


def _observe(step, base_url, root, send, exec_):
    """Исполнить шаг и вернуть (наблюдение, улики). None — шаг не запускался."""
    kind = step.action.kind
    if kind == UNMAPPED or kind == BROWSER:
        return None, []
    if kind == HTTP:
        if not base_url or send is None:
            return None, []
        obs = http_collector.run(step.action, base_url, send)
        payload = json.dumps({"request": {"method": step.action.method,
                                          "path": step.action.path,
                                          "body": step.action.body},
                              "status": obs.status, "body": obs.text,
                              "error": obs.error},
                             ensure_ascii=False, indent=2).encode("utf-8")
        return obs, [publish.write_evidence(root, step.n, "response.json", payload)]
    if kind == CLI:
        obs = cli_collector.run(step.action, root, exec_)
        payload = (f"$ {step.action.command}\n"
                   f"код возврата: {obs.exit_code}\n\n{obs.text}").encode("utf-8")
        return obs, [publish.write_evidence(root, step.n, "command.txt", payload)]
    return None, []


def verify(repo: str, issue: int, pr_number: int, base_url: str, root: str,
           gh, translate, send, exec_, run_git, token: str) -> RunReport:
    body = gh.issue_body(repo, issue)
    comments = gh.comments(repo, issue)

    fixed = anchor.fix(issue, body, comments)
    if fixed is None:
        return RunReport(anchor=Anchor(issue=issue), verdict=V_NO_SCENARIO)
    a, scenario = fixed
    _, changed = anchor.reread(a, body, comments)

    steps = plan.build(scenario, translate)
    results = []
    for step in steps:
        obs, evidence = _observe(step, base_url, root, send, exec_)
        results.append(verdict.judge(step, obs, evidence))

    branch = publish.branch_name(issue)
    published = publish.push(root, repo, branch, token, run_git)

    ref = ""
    if pr_number:
        head_ref, head_sha = gh.pull_head(repo, pr_number)
        ref = f"{head_ref}@{head_sha[:7]}"

    return RunReport(anchor=a, results=results, verdict=verdict.overall(results),
                     scenario_changed=changed, ref=ref, pr_number=pr_number,
                     evidence_branch=branch if published else "")
```

- [ ] **Step 4: Запустить тест, убедиться, что проходит**

Run: `pytest tests/test_run.py -q`
Expected: PASS, 5 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/run.py tests/test_run.py
git commit -m "feat(run): прогон приёмки целиком — якорь, план, шаги, вердикт, отчёт"
```

---

### Task 10: Активности, воркфлоу, точка подключения

**Files:**
- Create: `poh_howtodemo/activities.py`, `poh_howtodemo/workflow.py`, `poh_howtodemo/integration.py`
- Test: `tests/test_workflow.py`

**Interfaces:**
- Consumes: всё предыдущее.
- Produces: активности `howtodemo_verify(repo, issue, pr_number) -> RunReport`, `howtodemo_publish(repo, issue, pr_number, report) -> None`, `howtodemo_finish_labels(repo, issue, verdict) -> None`; воркфлоу `HowToDemoVerify`; `TASK_QUEUE = "howtodemo"`, `WORKFLOWS`, `ACTIVITIES`, `install(token_provider, dry_run=False)`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_workflow.py
from poh_howtodemo import integration, model
from poh_howtodemo.workflow import HowToDemoVerify


class _Recorder:
    """Подделка активностей: воркфлоу зовёт их через self._call."""

    def __init__(self, report):
        self.report = report
        self.calls = []

    async def __call__(self, name, *args):
        self.calls.append((name, args))
        if name == "howtodemo_verify":
            return self.report
        return None


def _report(verdict):
    return model.RunReport(anchor=model.Anchor(issue=12), verdict=verdict)


async def _drive(verdict):
    wf = HowToDemoVerify()
    wf._call = _Recorder(_report(verdict))
    await wf.run({"repo": "o/r", "issue": 12, "pr_number": 45})
    return [name for name, _ in wf._call.calls]


async def test_labels_are_finished_on_success():
    names = await _drive(model.V_PASSED)
    assert names[-1] == "howtodemo_finish_labels"


async def test_labels_are_finished_when_there_is_no_scenario():
    """Метка команды обязана сниматься и на пустом исходе — иначе висит вечно."""
    names = await _drive(model.V_NO_SCENARIO)
    assert "howtodemo_finish_labels" in names


async def test_report_is_published_before_labels():
    names = await _drive(model.V_FAILED)
    assert names.index("howtodemo_publish") < names.index("howtodemo_finish_labels")


def test_integration_exposes_queue_and_lists():
    assert integration.TASK_QUEUE == "howtodemo"
    assert integration.WORKFLOWS and integration.ACTIVITIES
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `pytest tests/test_workflow.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'poh_howtodemo.workflow'`

- [ ] **Step 3: Написать активности, воркфлоу и точку подключения**

```python
# poh_howtodemo/activities.py
"""Активности Temporal — весь ввод-вывод агента.

Потолок попыток у прогона ОДИН. Приёмка поднимает окружение, ходит по шагам и
зовёт модель; повтор такой активности означает повтор всей работы, а не
починку сетевого сбоя. Повтор инициирует человек.
"""

import subprocess

import requests
from temporalio import activity

from poh_howtodemo import ports, render, run
from poh_howtodemo.model import RunReport, V_FAILED, V_NO_SCENARIO, V_PARTIAL, V_PASSED

ALL_VERDICT_LABELS = [V_PASSED, V_FAILED, V_PARTIAL, V_NO_SCENARIO]
RUN_LABEL = "run:howtodemo"
DONE_LABEL = "done:howtodemo"
FAILED_LABEL = "failed:howtodemo"

_token_provider = None
_dry_run = False


def _send(method: str, url: str, body: dict | None) -> tuple[int, str]:
    r = requests.request(method, url, json=body, timeout=30)
    return r.status_code, r.text


def _exec(command: str, cwd: str) -> tuple[int, str]:
    p = subprocess.run(command, shell=True, cwd=cwd, capture_output=True,
                       text=True, timeout=600)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _git(args: list[str], cwd: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=300)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


@activity.defn(name="howtodemo_verify")
async def verify(repo: str, issue: int, pr_number: int) -> RunReport:
    gh = ports.github()
    # base_url пуст: срез 1 гоняет только шаги, не требующие окружения.
    # Эфемерный стенд приезжает срезом 2.
    return run.verify(repo=repo, issue=issue, pr_number=pr_number, base_url="",
                      root=f"/workspaces/howtodemo/{repo.replace('/', '__')}-{issue}",
                      gh=gh, translate=ports.llm().translate, send=_send,
                      exec_=_exec, run_git=_git, token=_token_provider())


@activity.defn(name="howtodemo_publish")
async def publish_report(repo: str, issue: int, pr_number: int, report: RunReport) -> None:
    body = (render.no_scenario_md(issue) if report.verdict == V_NO_SCENARIO
            else render.report_md(report))
    if _dry_run:
        activity.logger.info("[DRY_RUN] отчёт приёмки:\n%s", body)
        return
    gh = ports.github()
    gh.comment(repo, issue, body)
    if pr_number:
        gh.comment(repo, pr_number, body)


@activity.defn(name="howtodemo_finish_labels")
async def finish_labels(repo: str, issue: int, verdict_label: str) -> None:
    """Снять метку запуска и поставить вердикт.

    Зовётся во ВСЕХ ветках выхода, включая пустой сценарий и падение.
    Прецедент: `run:release` заводится каталогом и не снимается никем — метка,
    поставленная человеком, висит вечно.
    """
    if _dry_run:
        return
    gh = ports.github()
    stale = [label for label in ALL_VERDICT_LABELS if label != verdict_label]
    gh.remove_labels(repo, issue, [RUN_LABEL, *stale])
    gh.add_label(repo, issue, verdict_label)
    gh.add_label(repo, issue,
                 FAILED_LABEL if verdict_label == V_FAILED else DONE_LABEL)


def configure(token_provider, dry_run: bool = False) -> None:
    global _token_provider, _dry_run
    _token_provider, _dry_run = token_provider, dry_run
```

```python
# poh_howtodemo/workflow.py
"""HowToDemoVerify — приёмка от команды до отчёта.

Три шага, и последний обязан выполниться при любом исходе: метка запуска,
которую никто не снял, остаётся на Issue навсегда.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from poh_howtodemo.model import RunReport, V_FAILED

# Потолок попыток ОДИН: повтор дорогой недетерминированной работы означает
# повтор всей работы, а не починку сбоя.
_ONCE = RetryPolicy(maximum_attempts=1)


@workflow.defn(name="HowToDemoVerify")
class HowToDemoVerify:
    async def _call(self, name: str, *args):
        timeouts = {"howtodemo_verify": timedelta(minutes=40)}
        return await workflow.execute_activity(
            name, args=list(args), retry_policy=_ONCE,
            start_to_close_timeout=timeouts.get(name, timedelta(minutes=5)))

    @workflow.run
    async def run(self, params: dict) -> str:
        repo, issue = params["repo"], params["issue"]
        pr_number = params.get("pr_number", 0)
        verdict_label = V_FAILED
        try:
            report: RunReport = await self._call("howtodemo_verify", repo, issue, pr_number)
            verdict_label = report.verdict
            await self._call("howtodemo_publish", repo, issue, pr_number, report)
        finally:
            await self._call("howtodemo_finish_labels", repo, issue, verdict_label)
        return verdict_label
```

```python
# poh_howtodemo/integration.py
"""Точка подключения к Harness.

Harness отдаёт агенту ровно одно — функцию выдачи токена GitHub. Всё остальное
агент конструирует сам. Обратной зависимости нет: этот пакет не импортирует из
Harness ничего.

    from poh_howtodemo import integration as howtodemo

    howtodemo.install(github_client.auth_token, dry_run=DRY_RUN)
    Worker(client, task_queue=howtodemo.TASK_QUEUE,
           workflows=howtodemo.WORKFLOWS, activities=howtodemo.ACTIVITIES, ...)
"""

from poh_howtodemo import activities, ports
from poh_howtodemo.github import RestGitHub
from poh_howtodemo.workflow import HowToDemoVerify

TASK_QUEUE = "howtodemo"
WORKFLOWS = [HowToDemoVerify]
ACTIVITIES = [activities.verify, activities.publish_report, activities.finish_labels]


def install(token_provider, dry_run: bool = False, llm=None, shell=None) -> None:
    ports.configure(github=RestGitHub(token_provider), llm=llm, shell=shell)
    activities.configure(token_provider, dry_run=dry_run)
```

- [ ] **Step 4: Запустить тест, убедиться, что проходит**

Run: `pytest tests/test_workflow.py -q`
Expected: PASS, 4 passed

- [ ] **Step 5: Прогнать все тесты и закоммитить**

Run: `pytest -q`
Expected: PASS, 45 passed

```bash
git add poh_howtodemo/activities.py poh_howtodemo/workflow.py poh_howtodemo/integration.py tests/test_workflow.py
git commit -m "feat(workflow): HowToDemoVerify, активности и точка подключения к Harness"
```

---

## Что срез 1 намеренно не делает

- **Эфемерного стенда нет** — `base_url` пуст, HTTP-шаги получают `BLOCKED` и попадают в секцию «требует человека». Стенд приезжает срезом 2 вместе с врезкой в фазу `testing`.
- **Браузера нет** — `BROWSER` объявлен в модели и отбивается в `_observe`. До реализации обязателен замер RSS headless-Chromium на стенде: свободной памяти там 975 МБ и нет свопа.
- **Логов сервиса нет** — снимать нечего, пока нет стенда.
- **Возврата в доработку, SubIssue и блокировки релиза нет** — срез 4.
- **Правок в Harness нет.** Регистрация `/howtodemo` в `shared/commands._COMMANDS`, ветки в `webhook/main.py` и врезка в `_phase_park` — отдельный PR в `poh-issue-agents`, после того как этот срез зелёный.
