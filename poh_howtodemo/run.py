"""Прогон приёмки целиком: стенд → якорь → план → шаги → вердикт → отчёт.

Всё внешнее приходит параметрами, поэтому прогон целиком проверяется без сети,
без докера и без Temporal. Активности только подставляют настоящие реализации.

Стенд необязателен: без него HTTP-шаги дают `blocked` и уходят в «Требует
человека». Это честный результат, а не отказ прогона.
"""

import json

from poh_howtodemo import anchor, plan, publish, verdict
from poh_howtodemo.collectors import cli as cli_collector
from poh_howtodemo.collectors import http as http_collector
from poh_howtodemo.collectors import logs as log_collector
from poh_howtodemo.model import (BROWSER, CLI, HTTP, UNMAPPED, Anchor, Evidence,
                                 Observation, RunReport, Step, V_NO_SCENARIO)


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


def _walk(steps: list[Step], base_url: str, workdir: str, root: str, send, exec_,
          container: str, run_docker) -> list:
    """Пройти шаги, приложив к каждому логи сервиса за окно этого шага."""
    results = []
    for step in steps:
        since = log_collector.stamp()
        obs, evidence = _observe(step, base_url, workdir, root, send, exec_)
        if container and run_docker is not None and obs is not None:
            text = log_collector.window(run_docker, container, since,
                                        log_collector.stamp())
            evidence.append(publish.write_evidence(
                root, step.n, "service_log.txt", text.encode("utf-8")))
        results.append(verdict.judge(step, obs, evidence))
    return results


def verify(repo: str, issue: int, pr_number: int, base_url: str, root: str,
           gh, translate, send, exec_, run_git, token: str,
           stand=None, sha: str = "", service: dict | None = None,
           run_docker=None) -> RunReport:
    body = gh.issue_body(repo, issue)
    comments = gh.comments(repo, issue)

    fixed = anchor.fix(issue, body, comments)
    if fixed is None:
        return RunReport(anchor=Anchor(issue=issue), verdict=V_NO_SCENARIO)
    a, scenario = fixed
    _, changed = anchor.reread(a, body, comments)

    steps = plan.build(scenario, translate, issue, strict=a.numbered)

    container = ""
    workdir = ""
    stand_detail = ""
    try:
        if stand is not None:
            up = stand.up(repo, issue, sha, service or {})
            if up.ok:
                base_url, container, workdir = up.url, up.container, up.workdir
            else:
                stand_detail = up.detail
        results = _walk(steps, base_url, workdir, root, send, exec_, container,
                        run_docker)
    finally:
        # Стенд гасится при любом исходе: осиротевший контейнер держит порт и
        # память на хосте, где свободного меньше гигабайта.
        if stand is not None:
            stand.down(repo, issue)

    branch = publish.branch_name(issue)
    published = publish.push(root, repo, branch, token, run_git)

    ref = ""
    if pr_number:
        head_ref, head_sha = gh.pull_head(repo, pr_number)
        ref = f"{head_ref}@{head_sha[:7]}"

    return RunReport(anchor=a, results=results, verdict=verdict.overall(results),
                     scenario_changed=changed, ref=ref, pr_number=pr_number,
                     evidence_branch=branch if published else "")
