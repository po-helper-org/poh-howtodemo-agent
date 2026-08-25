"""Активности Temporal — весь ввод-вывод агента.

Потолок попыток у прогона ОДИН. Приёмка поднимает окружение, ходит по шагам и
зовёт модель; повтор такой активности означает повтор всей работы, а не
починку сетевого сбоя. Повтор инициирует человек.
"""

import os
import subprocess

import requests
from temporalio import activity

from poh_howtodemo import checks, env, ports, render, run
from poh_howtodemo.model import (RunReport, V_FAILED, V_NO_SCENARIO, V_PARTIAL,
                                 V_PASSED)

ALL_VERDICT_LABELS = [V_PASSED, V_FAILED, V_PARTIAL, V_NO_SCENARIO]
RUN_LABEL = "run:howtodemo"
DONE_LABEL = "done:howtodemo"
FAILED_LABEL = "failed:howtodemo"

WORKSPACE = "/workspaces/howtodemo"

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
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                       text=True, timeout=300)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _docker(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(args, capture_output=True, text=True, timeout=300)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _probe(url: str) -> int:
    return requests.get(url, timeout=5).status_code


def run_root(repo: str, issue: int) -> str:
    return f"{WORKSPACE}/{repo.replace('/', '__')}-{issue}"


def build_stand(token_provider) -> env.EphemeralStand:
    return env.EphemeralStand(run_cmd=_docker, probe=_probe,
                              token_provider=token_provider,
                              network=os.environ.get("HOWTODEMO_NETWORK", ""))


@activity.defn(name="howtodemo_verify")
async def verify(repo: str, issue: int, pr_number: int) -> RunReport:
    gh = ports.github()
    sha = ""
    if pr_number:
        _ref, sha = gh.pull_head(repo, pr_number)
    # Контракт читается из ТОГО ЖЕ SHA, что проверяем: файл мог измениться в
    # этой же ветке, и брать его с базовой значило бы поднимать сервис по
    # позавчерашнему описанию.
    service = checks.read(gh, repo, sha) if sha else {}
    token = _token_provider(repo) if _token_provider else ""
    return run.verify(repo=repo, issue=issue, pr_number=pr_number, base_url="",
                      root=run_root(repo, issue), gh=gh,
                      translate=ports.llm().translate, send=_send,
                      exec_=_exec, run_git=_git, token=token,
                      stand=None if _dry_run else build_stand(_token_provider),
                      sha=sha, service=service, run_docker=_docker)


@activity.defn(name="howtodemo_publish")
async def publish_report(repo: str, issue: int, pr_number: int,
                         report: RunReport) -> None:
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
