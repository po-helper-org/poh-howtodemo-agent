"""GitHub поверх REST. Токен приходит функцией-провайдером от Harness.

Токен берётся на каждый вызов, а не один раз на прогон: installation-токен
живёт час, а приёмка вместе с подъёмом окружения занимает минуты — кэш,
считающий токен годным при остатке в секунды, уже ронял ревью на
`401 Bad credentials` посреди работы.
"""

from typing import Callable

import requests

API = "https://api.github.com"
TIMEOUT = 30


class RestGitHub:
    def __init__(self, token_provider: Callable[[], str]):
        self._token = token_provider

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}",
                "Accept": "application/vnd.github+json"}

    def issue_body(self, repo: str, number: int) -> str:
        r = requests.get(f"{API}/repos/{repo}/issues/{number}",
                         headers=self._headers(), timeout=TIMEOUT)
        r.raise_for_status()
        return r.json().get("body") or ""

    def comments(self, repo: str, number: int) -> list[tuple[int, str]]:
        out: list[tuple[int, str]] = []
        page = 1
        while True:
            r = requests.get(f"{API}/repos/{repo}/issues/{number}/comments",
                             headers=self._headers(), timeout=TIMEOUT,
                             params={"per_page": 100, "page": page})
            r.raise_for_status()
            batch = r.json()
            out += [(c["id"], c.get("body") or "") for c in batch]
            if len(batch) < 100:
                return out
            page += 1

    def comment(self, repo: str, number: int, body: str) -> None:
        r = requests.post(f"{API}/repos/{repo}/issues/{number}/comments",
                          headers=self._headers(), timeout=TIMEOUT, json={"body": body})
        r.raise_for_status()

    def add_label(self, repo: str, number: int, label: str) -> None:
        r = requests.post(f"{API}/repos/{repo}/issues/{number}/labels",
                          headers=self._headers(), timeout=TIMEOUT,
                          json={"labels": [label]})
        r.raise_for_status()

    def remove_labels(self, repo: str, number: int, labels: list[str]) -> None:
        for label in labels:
            # 404 = метки и не было. Снятие несуществующей метки — не отказ.
            requests.delete(f"{API}/repos/{repo}/issues/{number}/labels/{label}",
                            headers=self._headers(), timeout=TIMEOUT)

    def pull_head(self, repo: str, number: int) -> tuple[str, str]:
        r = requests.get(f"{API}/repos/{repo}/pulls/{number}",
                         headers=self._headers(), timeout=TIMEOUT)
        r.raise_for_status()
        head = r.json()["head"]
        return head["ref"], head["sha"]
