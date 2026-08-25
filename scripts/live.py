#!/usr/bin/env python3
"""Живой прогон приёмки с ноутбука — без Temporal и без стенда контура.

Зачем: круг отладки через контур стоит тридцать с лишним минут — мерж, пин,
сборка образа, ожидание окна между прогонами агента разработки, `up -d`,
запуск, чтение логов. Отлаживать так значит терять день на три гипотезы.

Здесь тот же самый `run.verify` с теми же реализациями: настоящий GitHub по
токену `gh`, настоящий докер, настоящая модель. Не участвуют только Temporal и
воркер контура — а они и не то, что мы отлаживаем.

По умолчанию скрипт НИЧЕГО не пишет наружу: ни комментария, ни меток, ни ветки
с уликами. Отчёт печатается в stdout, улики лежат локально.

    scripts/live.py --repo po-helper-org/poh-demo-checkout --issue 100
    scripts/live.py --repo o/n --issue 12 --plan plan.json --no-stand
    scripts/live.py --repo o/n --issue 12 --push        # улики уедут в ветку

Модель: `--plan FILE` подставляет готовый план и не зовёт её вовсе — так
отлаживается всё, что после трансляции. Без `--plan` нужны `ZAI_API_KEY` и
`ZAI_BASE_URL` в окружении.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

from poh_howtodemo import env, plan, render, run  # noqa: E402
from poh_howtodemo.github import RestGitHub  # noqa: E402


def gh_token() -> str:
    out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit("нет токена: авторизуйтесь через `gh auth login`")
    return out.stdout.strip()


def docker(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(args, capture_output=True, text=True, timeout=300)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def shell(command: str, cwd: str) -> tuple[int, str]:
    p = subprocess.run(command, shell=True, cwd=cwd, capture_output=True,
                       text=True, timeout=600)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def send(method: str, url: str, body: dict | None) -> tuple[int, str]:
    r = requests.request(method, url, json=body, timeout=30)
    return r.status_code, r.text


def probe(url: str) -> int:
    return requests.get(url, timeout=5).status_code


def zai_translate(scenario: list[str]) -> str:
    """Трансляция настоящей моделью, тем же промптом, что и в контуре."""
    key, base = os.environ.get("ZAI_API_KEY"), os.environ.get("ZAI_BASE_URL")
    if not key or not base:
        sys.exit("нужны ZAI_API_KEY и ZAI_BASE_URL — либо подставьте план "
                 "через --plan FILE")
    numbered = "\n".join(f"{i + 1}. {step}" for i, step in enumerate(scenario))
    r = requests.post(f"{base.rstrip('/')}/chat/completions",
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": os.environ.get("MODEL_CLASSIFY", "glm-5.2"),
                            "messages": [
                                {"role": "system", "content": plan.system_prompt()},
                                {"role": "user", "content": numbered}],
                            "max_tokens": 8000, "temperature": 0.2},
                      timeout=180)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"] or ""


def refuse_git(args: list[str], cwd: str) -> tuple[int, str]:
    """Заглушка вместо пуша: отладочный прогон не пишет в чужой репозиторий."""
    return 1, "публикация улик выключена (добавьте --push)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="owner/name целевого репозитория")
    ap.add_argument("--issue", required=True, type=int)
    ap.add_argument("--pr", type=int, default=0,
                    help="номер PR; по умолчанию агент найдёт его сам")
    ap.add_argument("--plan", help="готовый план JSON вместо вызова модели")
    ap.add_argument("--no-stand", action="store_true",
                    help="не поднимать окружение — шаги уйдут в blocked")
    ap.add_argument("--push", action="store_true",
                    help="запушить улики в ветку howtodemo/issue-<n>")
    ap.add_argument("--root", default=".live",
                    help="каталог прогона; он же том стенда (по умолчанию .live)")
    args = ap.parse_args()

    token = gh_token()
    gh = RestGitHub(lambda repo: token)

    if args.plan:
        canned = Path(args.plan).read_text(encoding="utf-8")
        translate = lambda _scenario: canned  # noqa: E731
    else:
        translate = zai_translate

    root = str(Path(args.root).resolve())
    Path(root).mkdir(parents=True, exist_ok=True)

    pr_number = args.pr
    if not pr_number:
        pr_number = gh.linked_pull(args.repo, args.issue)
        print(f"[live] PR задачи: {pr_number or 'не найден'}", file=sys.stderr)

    sha = ""
    service: dict = {}
    if pr_number:
        _ref, sha = gh.pull_head(args.repo, pr_number)
        from poh_howtodemo import checks
        service = checks.read(gh, args.repo, sha)
        print(f"[live] SHA {sha[:7]}, контракт: "
              f"{service.get('start') or 'нет service.start'}", file=sys.stderr)

    stand = None
    if not args.no_stand:
        # Том и точка монтирования — один и тот же локальный каталог: bind-mount
        # вместо именованного тома контура, иначе путь `-w` внутри контейнера
        # не совпал бы с тем, куда скрипт разложил клон.
        stand = env.EphemeralStand(run_cmd=docker, probe=probe,
                                   token_provider=lambda repo: token,
                                   volume=root, mount=root, publish_port=True)

    report = run.verify(
        repo=args.repo, issue=args.issue, pr_number=pr_number, base_url="",
        root=root, gh=gh, translate=translate, send=send, exec_=shell,
        run_git=(lambda a, c: (0, "")) if args.push else refuse_git,
        token=token, stand=stand, sha=sha, service=service, run_docker=docker)

    print(render.report_md(report))
    print(f"\n[live] вердикт: {report.verdict}", file=sys.stderr)
    print(f"[live] улики: {root}/evidence", file=sys.stderr)
    for result in report.results:
        print(f"[live]   {result.n}. {result.outcome:8} {result.detail[:70]}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
