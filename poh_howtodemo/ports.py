"""Порты: чем агент разговаривает с GitHub, моделью и оболочкой.

Порт, а не прямой вызов клиента Harness, — потому что агент живёт в своём
репозитории и обязан собираться и тестироваться без него. Harness подставляет
реализации на старте воркера, тесты — свои заглушки.
"""

from typing import Protocol


class GitHubPort(Protocol):
    def issue_body(self, repo: str, number: int) -> str: ...
    def comments(self, repo: str, number: int) -> list[tuple[int, str]]: ...
    def comment(self, repo: str, number: int, body: str) -> None: ...
    def add_label(self, repo: str, number: int, label: str) -> None: ...
    def remove_labels(self, repo: str, number: int, labels: list[str]) -> None: ...
    def pull_head(self, repo: str, number: int) -> tuple[str, str]: ...


class LlmPort(Protocol):
    def translate(self, scenario: list[str]) -> str: ...


class ShellPort(Protocol):
    def run(self, command: str, cwd: str) -> tuple[int, str]: ...


_github: GitHubPort | None = None
_llm: LlmPort | None = None
_shell: ShellPort | None = None


def configure(github: GitHubPort | None = None, llm: LlmPort | None = None,
              shell: ShellPort | None = None) -> None:
    """Подставить реализации. Зовётся один раз на старте воркера."""
    global _github, _llm, _shell
    _github, _llm, _shell = github, llm, shell


def github() -> GitHubPort:
    if _github is None:
        raise RuntimeError("порт GitHub не подставлен — зовите ports.configure()")
    return _github


def llm() -> LlmPort:
    if _llm is None:
        raise RuntimeError("порт модели не подставлен — зовите ports.configure()")
    return _llm


def shell() -> ShellPort:
    if _shell is None:
        raise RuntimeError("порт оболочки не подставлен — зовите ports.configure()")
    return _shell
