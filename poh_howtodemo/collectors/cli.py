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
