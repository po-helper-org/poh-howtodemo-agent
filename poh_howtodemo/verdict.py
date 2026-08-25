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
