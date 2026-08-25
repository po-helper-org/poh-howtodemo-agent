"""Прогон приёмки целиком: якорь → план → шаги → вердикт → отчёт.

Всё внешнее приходит параметрами, поэтому прогон целиком проверяется без сети,
без докера и без Temporal. Активности только подставляют настоящие реализации.
"""

import json

from poh_howtodemo import anchor, plan, publish, verdict
from poh_howtodemo.collectors import cli as cli_collector
from poh_howtodemo.collectors import http as http_collector
from poh_howtodemo.model import (BROWSER, CLI, HTTP, UNMAPPED, Anchor, Evidence,
                                 Observation, RunReport, Step, V_NO_SCENARIO)


def _observe(step: Step, base_url: str, root: str, send,
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
