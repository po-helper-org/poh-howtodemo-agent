# HowToDemo-Agent, срез 3 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Отчёт приёмки перестаёт врать: агент сам находит PR задачи и поднимает по нему стенд, источник требования считает код, а команда без рабочей копии честно помечается `blocked`.

**Architecture:** Три независимые правки в существующих модулях. `env` отдаёт каталог рабочей копии вместе со стендом, `plan` перестаёт доверять модели поле `source`, `github` учится находить PR по Issue через Timeline API. Ядро остаётся чистым, всё внешнее по-прежнему приходит вызываемыми объектами.

**Tech Stack:** Python 3.11+, `temporalio>=1.9`, `requests>=2.31`, pytest. Новых зависимостей нет.

## Global Constraints

- Ограничения срезов 1–2 в силе.
- **Модель не пишет ничего, что попадает в вердикт или в ссылку на источник.** Живой прогон на `poh-demo-checkout#100` показал: модель написала `Issue #1` вместо `#100`, списав номер из примера в промпте.
- **Шаг не исполняется без того, что ему нужно.** Нет стенда — нет HTTP. Нет рабочей копии — нет команды. Исполнить и отчитаться о провале хуже, чем честно сказать «не запускался».
- Ветка одна на срез: `feature/slice-3-pr-and-truthful-report`, вливается PR'ом.

---

### Task 1: Рабочая копия приезжает вместе со стендом

**Files:**
- Modify: `poh_howtodemo/model.py` (поле `Stand.workdir`), `poh_howtodemo/env.py`, `poh_howtodemo/run.py`
- Test: `tests/test_env.py`, `tests/test_run_with_stand.py`

**Interfaces:**
- Produces: `Stand.workdir: str` — каталог клона на томе; пусто, если стенда нет.
  `run._observe(step, base_url, workdir, root, send, exec_)` — `workdir` пуст ⇒ CLI-шаг не запускается.

**Дефект живого прогона.** Шаг «Запустить тесты в `tests/`» исполнился без рабочей копии
и вернул `npm error enoent Could not read package.json`, код 254. Отчёт сказал
«тесты продукта не проходят» и выдал `demo:failed`. Рабочая копия приезжает со
стендом — значит без стенда команда обязана быть `blocked`, как и HTTP.

- [ ] **Step 1: Написать падающие тесты**

```python
# в tests/test_env.py — добавить
def test_stand_reports_the_working_copy():
    docker = _Docker()
    got = _stand(docker, [200]).up("o/r", 12, "abc123", SERVICE)
    assert got.workdir.endswith("/howtodemo/o__r-12/abc123")


def test_failed_stand_has_no_working_copy():
    docker = _Docker()
    got = _stand(docker, []).up("o/r", 12, "abc123", {"port": 3000})
    assert got.workdir == ""
```

```python
# в tests/test_run_with_stand.py — добавить
CLI_PLAN = json.dumps({"steps": [
    {"n": 1, "text": "Запустить тесты", "action": {"kind": "cli", "command": "npm test"},
     "expect": {"exit_code": 0}, "evidence": ["command"], "source": "x"},
]})


def _run_cli(stand, tmp_path, exec_):
    return run.verify(repo="o/r", issue=12, pr_number=45, base_url="",
                      root=str(tmp_path), gh=_GH(), translate=lambda s: CLI_PLAN,
                      send=None, exec_=exec_, run_git=lambda a, c: (0, ""),
                      token="t", stand=stand, sha="3a1f0c2",
                      service={"start": "node x"}, run_docker=lambda a: (0, ""))


def test_command_does_not_run_without_a_working_copy(tmp_path):
    """Без стенда нет и рабочей копии — команда не запускается, а не падает."""
    def must_not_run(command, cwd):
        raise AssertionError("команда не должна запускаться без рабочей копии")

    rep = _run_cli(_Stand(ok=False), tmp_path, must_not_run)
    assert rep.results[0].outcome == model.BLOCKED
    assert "не запускался" in rep.results[0].detail


def test_command_runs_in_the_working_copy(tmp_path):
    seen = {}

    def exec_(command, cwd):
        seen.update(command=command, cwd=cwd)
        return 0, "ok"

    rep = _run_cli(_Stand(), tmp_path, exec_)
    assert seen["cwd"] == "/workspaces/howtodemo/o__r-12/3a1f0c2"
    assert rep.results[0].outcome == model.PASSED
```

Подделку `_Stand.up` в `tests/test_run_with_stand.py` дополнить полем:

```python
        return model.Stand(ok=True, url="http://stand:3000",
                           container="poh-howtodemo-o__r-12",
                           workdir="/workspaces/howtodemo/o__r-12/3a1f0c2")
```

- [ ] **Step 2: Запустить тесты, убедиться, что падают**

Run: `.venv/bin/pytest tests/test_env.py tests/test_run_with_stand.py -q`
Expected: FAIL, `AttributeError: 'Stand' object has no attribute 'workdir'`

- [ ] **Step 3: Внести правки**

В `poh_howtodemo/model.py`, в `Stand`, после `container`:

```python
    # Каталог клона на томе. Пусто — рабочей копии нет, и команду выполнять
    # негде: она бы отработала в пустоте и соврала про продукт.
    workdir: str = ""
```

В `poh_howtodemo/env.py`, в `up`, вернуть каталог на успехе:

```python
        return Stand(ok=True, url=url, container=name, workdir=target, detail=detail)
```

В `poh_howtodemo/run.py` — `_observe` получает `workdir`, CLI без него не идёт:

```python
def _observe(step: Step, base_url: str, workdir: str, root: str, send,
             exec_) -> tuple[Observation | None, list[Evidence]]:
    """Исполнить шаг и вернуть (наблюдение, улики). None — шаг не запускался."""
    kind = step.action.kind
    if kind in (UNMAPPED, BROWSER):
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
        # Рабочая копия приезжает со стендом. Без неё команда отработала бы в
        # пустом каталоге и соврала про продукт: живой прогон дал
        # `npm error enoent Could not read package.json` и вердикт
        # «тесты не проходят».
        if not workdir:
            return None, []
        obs = cli_collector.run(step.action, workdir, exec_)
        payload = (f"$ {step.action.command}\n"
                   f"код возврата: {obs.exit_code}\n\n{obs.text}").encode("utf-8")
        return obs, [publish.write_evidence(root, step.n, "command.txt", payload)]
    return None, []
```

`_walk` и `verify` пробрасывают `workdir`: в `_walk` добавить параметр после
`base_url`, в `verify` — `workdir = ""` рядом с `container` и присвоение
`base_url, container, workdir = up.url, up.container, up.workdir`.

- [ ] **Step 4: Запустить тесты, убедиться, что проходят**

Run: `.venv/bin/pytest tests/test_env.py tests/test_run_with_stand.py -q`
Expected: PASS, 15 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/model.py poh_howtodemo/env.py poh_howtodemo/run.py tests/test_env.py tests/test_run_with_stand.py
git commit -m "fix(run): команда не исполняется без рабочей копии"
```

---

### Task 2: Источник требования считает код

**Files:**
- Modify: `poh_howtodemo/plan.py`, `poh_howtodemo/run.py`
- Test: `tests/test_plan.py`

**Interfaces:**
- Produces: `plan.build(scenario, translate, issue, strict=True)` — новый обязательный параметр `issue`. Поле `source` каждого шага перезаписывается кодом.

**Дефект живого прогона.** В отчёте по `poh-demo-checkout#100` стояло
`Источник требования: Issue #1, шаг 5`. Модель списала номер из примера промпта.
Ссылка на источник — часть вердикта, а вердикт модель не пишет.

- [ ] **Step 1: Написать падающий тест**

```python
# в tests/test_plan.py — добавить
def test_source_is_computed_by_code_not_taken_from_the_model():
    """Живой прогон: модель написала «Issue #1» на Issue #100."""
    raw = json.dumps({"steps": [
        {"n": 1, "text": "шаг", "action": {"kind": "unmapped"},
         "source": "Issue #1, шаг 1"},
    ]})
    steps = plan.build(["шаг"], lambda s: raw, issue=100)
    assert steps[0].source == "Issue #100, шаг 1"


def test_source_follows_the_plan_step_number():
    raw = json.dumps({"steps": [
        {"n": 1, "text": "a", "action": {"kind": "unmapped"}},
        {"n": 2, "text": "b", "action": {"kind": "unmapped"}},
    ]})
    steps = plan.build(["блок"], lambda s: raw, issue=7, strict=False)
    assert [s.source for s in steps] == ["Issue #7, шаг 1", "Issue #7, шаг 2"]
```

Существующие вызовы `plan.build` в тестах дополнить `issue=12`.

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `.venv/bin/pytest tests/test_plan.py -q`
Expected: FAIL, `TypeError: build() got an unexpected keyword argument 'issue'`

- [ ] **Step 3: Внести правку**

В `poh_howtodemo/plan.py`:

```python
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
```

В `poh_howtodemo/run.py` вызов становится:

```python
    steps = plan.build(scenario, translate, issue, strict=a.numbered)
```

- [ ] **Step 4: Запустить тесты, убедиться, что проходят**

Run: `.venv/bin/pytest tests/test_plan.py tests/test_run.py tests/test_run_with_stand.py -q`
Expected: PASS, 19 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/plan.py poh_howtodemo/run.py tests/test_plan.py
git commit -m "fix(plan): источник требования считает код, а не модель"
```

---

### Task 3: Агент сам находит PR задачи

**Files:**
- Modify: `poh_howtodemo/ports.py`, `poh_howtodemo/github.py`, `poh_howtodemo/activities.py`
- Test: `tests/test_github.py`, `tests/test_activities.py`

**Interfaces:**
- Produces: `GitHubPort.linked_pull(repo, issue) -> int` — номер открытого PR задачи, `0` если нет.
  `github.pick_pull(events) -> int` — чистый выбор из событий Timeline, тестируется без сети.

**Почему это узкое место.** Вебхук событий `pull_request` не слушает вовсе, и
`pr_number` в прогоне всегда `0`. Без номера PR нет SHA, без SHA нет стенда, без
стенда не исполняется ни один HTTP-шаг. Половина механизма выложена и ни разу не
работала.

Приём тот же, что у Harness (`github_client.list_linked_prs`): Timeline API,
события `cross-referenced`. Кросс-ссылка — это любое упоминание, поэтому
предпочитаем PR с закрывающим ключевым словом в теле, а из остальных берём
самый свежий открытый.

- [ ] **Step 1: Написать падающий тест**

```python
# в tests/test_github.py — добавить
from poh_howtodemo import github


def _event(number, state="open", body="", pull=True):
    src = {"number": number, "state": state, "body": body}
    if pull:
        src["pull_request"] = {}
    return {"event": "cross-referenced", "source": {"issue": src}}


def test_closing_keyword_wins_over_a_mere_mention():
    events = [_event(10, body="упоминаю #12 в обсуждении"),
              _event(11, body="Closes #12")]
    assert github.pick_pull(events, 12) == 11


def test_newest_open_pull_when_nobody_closes():
    events = [_event(10), _event(11)]
    assert github.pick_pull(events, 12) == 11


def test_closed_pulls_are_ignored():
    assert github.pick_pull([_event(10, state="closed", body="Closes #12")], 12) == 0


def test_cross_referenced_issues_are_not_pulls():
    assert github.pick_pull([_event(10, pull=False, body="Closes #12")], 12) == 0


def test_no_events_means_no_pull():
    assert github.pick_pull([], 12) == 0
```

```python
# в tests/test_activities.py — добавить
class _GHPull:
    def __init__(self, linked):
        self.linked = linked
        self.asked = []

    def linked_pull(self, repo, issue):
        self.asked.append((repo, issue))
        return self.linked


def test_pull_is_resolved_when_the_trigger_did_not_carry_it():
    gh = _GHPull(77)
    assert activities.resolve_pull(gh, "o/r", 12, 0) == 77
    assert gh.asked == [("o/r", 12)]


def test_explicit_pull_number_is_not_second_guessed():
    gh = _GHPull(77)
    assert activities.resolve_pull(gh, "o/r", 12, 45) == 45
    assert gh.asked == []
```

- [ ] **Step 2: Запустить тесты, убедиться, что падают**

Run: `.venv/bin/pytest tests/test_github.py tests/test_activities.py -q`
Expected: FAIL, `AttributeError: module 'poh_howtodemo.github' has no attribute 'pick_pull'`

- [ ] **Step 3: Внести правки**

В `poh_howtodemo/ports.py`, в `GitHubPort`, после `get_file`:

```python
    def linked_pull(self, repo: str, issue: int) -> int: ...
```

В `poh_howtodemo/github.py` — чистый выбор и метод порта:

```python
import re

_CLOSING = re.compile(r"\b(?:clos(?:e|es|ed)|fix(?:e[sd])?|resolv(?:e|es|ed))\s+#(\d+)",
                      re.IGNORECASE)


def pick_pull(events: list[dict], issue: int) -> int:
    """Выбрать PR задачи из событий Timeline. 0 — не нашли.

    Кросс-ссылка означает любое упоминание, а не «этот PR делает эту задачу».
    Поэтому сначала ищем закрывающее ключевое слово в теле PR, и только если
    его нет — берём самый свежий открытый. Закрытые не берём вовсе: приёмка
    идёт по живому PR.
    """
    open_pulls: list[int] = []
    closing: list[int] = []
    for event in events:
        if event.get("event") != "cross-referenced":
            continue
        src = (event.get("source") or {}).get("issue") or {}
        if "pull_request" not in src or src.get("state") != "open":
            continue
        number = src.get("number")
        if number is None:
            continue
        open_pulls.append(number)
        if any(int(m) == issue for m in _CLOSING.findall(src.get("body") or "")):
            closing.append(number)
    if closing:
        return closing[-1]
    return open_pulls[-1] if open_pulls else 0
```

и метод класса `RestGitHub`:

```python
    def linked_pull(self, repo: str, issue: int) -> int:
        r = requests.get(f"{API}/repos/{repo}/issues/{issue}/timeline",
                         headers={**self._headers(repo),
                                  "Accept": "application/vnd.github+json"},
                         params={"per_page": 100}, timeout=TIMEOUT)
        r.raise_for_status()
        return pick_pull(r.json(), issue)
```

В `poh_howtodemo/activities.py` — резолв и его использование:

```python
def resolve_pull(gh, repo: str, issue: int, pr_number: int) -> int:
    """Номер PR задачи.

    Вебхук событий `pull_request` не слушает, поэтому триггер приносит ноль
    почти всегда. Спрашиваем GitHub сами: без PR нет SHA, без SHA нет стенда,
    без стенда не исполняется ни один шаг сценария.

    Явно переданный номер не перепроверяем — он пришёл от того, кто знает
    больше нас.
    """
    if pr_number:
        return pr_number
    return gh.linked_pull(repo, issue)
```

и в `verify` первой строкой после `gh = ports.github()`:

```python
    pr_number = resolve_pull(gh, repo, issue, pr_number)
```

- [ ] **Step 4: Запустить тесты, убедиться, что проходят**

Run: `.venv/bin/pytest tests/test_github.py tests/test_activities.py -q`
Expected: PASS, 12 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/ports.py poh_howtodemo/github.py poh_howtodemo/activities.py tests/test_github.py tests/test_activities.py
git commit -m "feat(github): агент сам находит PR задачи — иначе стенд не поднимается никогда"
```

---

### Task 4: Отчёт объясняет, почему шаги не пошли

**Files:**
- Modify: `poh_howtodemo/model.py` (`RunReport.stand_detail`), `poh_howtodemo/run.py`, `poh_howtodemo/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Produces: `RunReport.stand_detail: str` — почему окружения не было; пусто, если стенд поднялся.

Сегодня отчёт говорит «шаг не запускался: окружения не было» и молчит о причине.
Причина у стенда есть всегда (`Stand.detail`) и её надо доносить: «PR не найден»
и «в `.delivery/checks.json` нет `service.start`» лечатся по-разному.

- [ ] **Step 1: Написать падающий тест**

```python
# в tests/test_render.py — добавить
def test_report_explains_why_there_was_no_environment():
    rep = _report()
    rep.stand_detail = "в .delivery/checks.json нет service.start"
    body = render.report_md(rep)
    assert "service.start" in body


def test_report_says_nothing_about_environment_when_it_came_up():
    assert "Окружение" not in render.report_md(_report())
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `.venv/bin/pytest tests/test_render.py -q`
Expected: FAIL, `AttributeError: 'RunReport' object has no attribute 'stand_detail'`

- [ ] **Step 3: Внести правки**

В `poh_howtodemo/model.py`, в `RunReport`, после `evidence_branch`:

```python
    # Почему окружения не было. Пусто — стенд поднялся. «PR не найден» и
    # «в контракте нет service.start» лечатся по-разному, и молчать о разнице
    # значит отправлять человека гадать.
    stand_detail: str = ""
```

В `poh_howtodemo/run.py`, в `verify`: завести `stand_detail = ""`, заполнять из
`up.detail` когда `not up.ok`, и передать в `RunReport`.

В `poh_howtodemo/render.py`, после блока про свободную форму:

```python
    if rep.stand_detail:
        out += ["", f"> Окружение поднять не удалось: {rep.stand_detail}. "
                    "Шаги, которым оно нужно, не запускались."]
```

- [ ] **Step 4: Прогнать весь набор**

Run: `.venv/bin/pytest -q`
Expected: PASS, 97 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/model.py poh_howtodemo/run.py poh_howtodemo/render.py tests/test_render.py
git commit -m "feat(render): отчёт называет причину, по которой окружения не было"
```

---

## Что срез 3 намеренно не делает

- **Цепочных шагов нет.** «Проверить, что код ответа 200» после «Отправить `GET /healthz`» — утверждение о наблюдении предыдущего шага, а не действие. Модель честно помечает такие `unmapped`; на живом прогоне так ушло 2 шага из 5. Нужен выбор между `assert_on: <n>` в плане и схлопыванием цепочки в один шаг с несколькими ожиданиями — отдельная работа.
- **Браузера нет** — ждёт замера RSS headless-Chromium на стенде.
- **Врезки в фазу нет** — живёт в `poh-issue-agents`, после того как приёмка даст осмысленный вердикт хотя бы раз.
- **Промпт в Harness не меняется в этом срезе.** Поле `source` он по-прежнему просит, но код его перезаписывает — вреда нет. Убрать из промпта стоит вместе со следующей правкой Harness, чтобы не гонять лишний круг выкладки.
