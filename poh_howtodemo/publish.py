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
        code, _output = run_git(args, root)
        if code != 0:
            # Токен в тексте отказа не оставляем — он уедет в лог и в Sentry.
            return False
    return True
