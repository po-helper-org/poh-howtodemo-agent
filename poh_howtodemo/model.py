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
    # Сценарий был нумерованным списком. Свободная форма (блок `curl` с
    # «Ожидаемо:», как пишут люди) разбирается иначе и не требует
    # пошагового совпадения с планом — см. plan.build(strict=...).
    numbered: bool = True


@dataclass
class Action:
    kind: str = UNMAPPED
    method: str = "GET"
    path: str = "/"
    body: dict | None = None
    command: str = ""


@dataclass
class Expect:
    """Ожидание шага. Пустое ожидание — не «всё сошлось», а «проверять нечем»."""

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
class Stand:
    """Эфемерное окружение прогона. `ok=False` — шаги пойдут как blocked."""

    ok: bool = False
    url: str = ""
    container: str = ""
    detail: str = ""


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
