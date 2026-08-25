"""GitHub поверх REST. Токен приходит функцией-провайдером от Harness.

Провайдер принимает репозиторий: в Harness он объявлен как
`github_client.auth_token(repo: str) -> str`, и у Delivery-Agent тот же контракт
(`env_token_provider(repo: str)`). Звать его без аргумента — падение на первом
же вызове в бою при зелёных тестах на подделке.

Токен берётся на каждый вызов, а не один раз на прогон: installation-токен
живёт час, а приёмка вместе с подъёмом окружения занимает минуты — кэш,
считающий токен годным при остатке в секунды, уже ронял ревью на
`401 Bad credentials` посреди работы.
"""

import re
from typing import Callable

import requests

API = "https://api.github.com"
TIMEOUT = 30

_CLOSING = re.compile(r"\b(?:clos(?:e|es|ed)|fix(?:e[sd])?|resolv(?:e|es|ed))\s+#(\d+)",
                      re.IGNORECASE)


def pick_pull(events: list[dict], issue: int) -> int:
    """Выбрать PR задачи из событий Timeline. 0 — не нашли.

    Кросс-ссылка означает любое упоминание, а не «этот PR делает эту задачу».
    Поэтому сначала ищем закрывающее ключевое слово на НАШ номер в теле PR, и
    только если его нет — берём самый свежий открытый. Закрытые не берём
    вовсе: приёмка идёт по живому PR.
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


class RestGitHub:
    def __init__(self, token_provider: Callable[[str], str]):
        self._token_for = token_provider

    def _headers(self, repo: str) -> dict:
        return {"Authorization": f"Bearer {self._token_for(repo)}",
                "Accept": "application/vnd.github+json"}

    def issue_body(self, repo: str, number: int) -> str:
        r = requests.get(f"{API}/repos/{repo}/issues/{number}",
                         headers=self._headers(repo), timeout=TIMEOUT)
        r.raise_for_status()
        return r.json().get("body") or ""

    def comments(self, repo: str, number: int) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        page = 1
        while True:
            r = requests.get(f"{API}/repos/{repo}/issues/{number}/comments",
                             headers=self._headers(repo), timeout=TIMEOUT,
                             params={"per_page": 100, "page": page})
            r.raise_for_status()
            batch = r.json()
            out += [(c["id"], c.get("body") or "") for c in batch]
            if len(batch) < 100:
                return out
            page += 1

    def comment(self, repo: str, number: int, body: str) -> None:
        r = requests.post(f"{API}/repos/{repo}/issues/{number}/comments",
                          headers=self._headers(repo), timeout=TIMEOUT,
                          json={"body": body})
        r.raise_for_status()

    def add_label(self, repo: str, number: int, label: str) -> None:
        r = requests.post(f"{API}/repos/{repo}/issues/{number}/labels",
                          headers=self._headers(repo), timeout=TIMEOUT,
                          json={"labels": [label]})
        r.raise_for_status()

    def remove_labels(self, repo: str, number: int, labels: list[str]) -> None:
        for label in labels:
            # 404 = метки и не было. Снятие несуществующей метки — не отказ.
            requests.delete(f"{API}/repos/{repo}/issues/{number}/labels/{label}",
                            headers=self._headers(repo), timeout=TIMEOUT)

    def pull_head(self, repo: str, number: int) -> tuple[str, str]:
        r = requests.get(f"{API}/repos/{repo}/pulls/{number}",
                         headers=self._headers(repo), timeout=TIMEOUT)
        r.raise_for_status()
        head = r.json()["head"]
        return head["ref"], head["sha"]

    def linked_pull(self, repo: str, issue: int) -> int:
        r = requests.get(f"{API}/repos/{repo}/issues/{issue}/timeline",
                         headers=self._headers(repo),
                         params={"per_page": 100}, timeout=TIMEOUT)
        r.raise_for_status()
        return pick_pull(r.json(), issue)

    def get_file(self, repo: str, path: str, ref: str) -> str | None:
        r = requests.get(f"{API}/repos/{repo}/contents/{path}",
                         headers={**self._headers(repo),
                                  "Accept": "application/vnd.github.raw"},
                         params={"ref": ref}, timeout=TIMEOUT)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text
