"""Отчёт приёмки: что готово, что не соответствует.

Две секции, а не одна таблица: человек читает отчёт, чтобы решить, брать ли
работу, и «не соответствует» должно быть видно раньше, чем он устанет.

Маркер-строка в конце — чтобы соседний агент нашёл вердикт в треде, как
Delivery находит вердикт круга правок.

Модуль чистый.
"""

from poh_howtodemo.model import (BLOCKED, FAILED, PASSED, SKIPPED, RunReport,
                                 StepResult, V_FAILED, V_PARTIAL, V_PASSED)

MARKER = "<!-- howtodemo:verdict -->"

_ICON = {PASSED: "✅", FAILED: "❌", SKIPPED: "⚠️", BLOCKED: "⏸"}
_WORD = {V_PASSED: "сценарий пройден", V_FAILED: "сценарий не пройден",
         V_PARTIAL: "пройден частично"}


def _line(res: StepResult) -> str:
    head = f"{_ICON.get(res.outcome, '·')} {res.n}. {res.text}"
    if res.on_step:
        # Утверждение проверено по чужому ответу — читатель должен видеть, по
        # чьему именно, иначе улика под шагом выглядит подложенной.
        head += f"\n      проверено по ответу шага {res.on_step}"
    if res.detail:
        head += f"\n      {res.detail}"
    if res.source:
        head += f"\n      Источник требования: {res.source}"
    for ev in res.evidence:
        head += f"\n      [{ev.name}]({ev.path})"
    return head


def report_md(rep: RunReport) -> str:
    where = f"PR #{rep.pr_number}" if rep.pr_number else "прогон"
    title = f"## HowToDemo — {where} ({rep.ref})" if rep.ref else f"## HowToDemo — {where}"
    origin = ("тело Issue" if rep.anchor.comment_id == 0
              else f"комментарий {rep.anchor.comment_id}")
    out = [title,
           "",
           f"Сценарий зафиксирован {rep.anchor.taken_at}: {origin} "
           f"#{rep.anchor.issue}, sha256 `{rep.anchor.sha256[:8]}…`",
           f"Вердикт: **{_WORD.get(rep.verdict, rep.verdict)}** (`{rep.verdict}`)"]
    if not rep.anchor.numbered:
        out += ["",
                "> Сценарий записан свободной формой, без нумерованного списка — "
                "шаги плана выделены из него автоматически. Сверьте, что ничего "
                "не потеряно."]
    if rep.stand_detail:
        out += ["", f"> Окружение поднять не удалось: {rep.stand_detail}. "
                    "Шаги, которым оно нужно, не запускались."]
    if rep.scenario_changed:
        out += ["",
                "> ⚠️ Сценарий **менялся после фиксации**. Прогон шёл по "
                "зафиксированной редакции — сверьте расхождение вручную."]

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
