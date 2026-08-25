# HowToDemo-Agent, срез 2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Агент поднимает эфемерный стенд из произвольного SHA, гоняет по нему HTTP-шаги сценария и прикладывает к каждому шагу логи сервиса за окно этого шага.

**Architecture:** `checks.py` читает контракт окружения из целевого репозитория, `env.py` поднимает и гасит контейнер, `collectors/logs.py` снимает `docker logs` за временное окно. Всё внешнее по-прежнему приходит вызываемыми объектами — прогон целиком тестируется без докера. `run.verify` получает необязательный стенд: без него поведение среза 1 сохраняется дословно.

**Tech Stack:** Python 3.11+, `temporalio>=1.9`, `requests>=2.31`, pytest. Новых зависимостей нет.

## Global Constraints

- Все ограничения среза 1 в силе (см. `2026-08-25-howtodemo-slice-1.md`).
- **Имя контейнера стенда никогда не совпадает с прод-контуром Delivery.** У Delivery имя зафиксировано модульной константой `poh-delivery-prod`, а подъём начинается с `docker rm -f` — совпадение имени снесло бы живой прод.
- **Стенд эфемерный:** `--rm`, без `--restart`, гашение в `finally` при любом исходе.
- **Отсутствие контракта окружения не роняет прогон.** Нет `.delivery/checks.json` или нет `service.start` → стенд не поднимается, HTTP-шаги дают `blocked`, отчёт говорит об этом прямо. Это осознанное отличие от Delivery, где та же ситуация откатывает каждый PR.
- Ветка одна на срез: `feature/slice-2-ephemeral-stand`, вливается PR'ом.

---

### Task 1: Контракт окружения + починка контракта токена

**Files:**
- Create: `poh_howtodemo/checks.py`
- Modify: `poh_howtodemo/ports.py` (добавить `get_file` в `GitHubPort`), `poh_howtodemo/github.py` (реализация + починка провайдера токена)
- Test: `tests/test_checks.py`, `tests/test_github.py`

**Interfaces:**
- Consumes: `ports.GitHubPort`.
- Produces: `checks.PATH = ".delivery/checks.json"`, `checks.service_of(raw) -> dict`, `checks.read(gh, repo, ref) -> dict`.
  `GitHubPort.get_file(repo, path, ref) -> str | None` — `None`, если файла нет.
  `RestGitHub(token_provider: Callable[[str], str])` — провайдер принимает **репозиторий**.

**Дефект среза 1.** `RestGitHub` звал `self._token()` без аргументов, а в Harness
провайдер объявлен как `github_client.auth_token(repo: str) -> str` (то же и у
Delivery: `poh_delivery/github.py:34`, `env_token_provider(repo: str)`). При
подключении к воркеру это упало бы на первом же вызове — тестами не поймано,
потому что подделка принимала что угодно. Чиним здесь.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_github.py
from poh_howtodemo.github import RestGitHub


def test_token_provider_receives_the_repository():
    """Harness объявляет auth_token(repo: str) — зовём его так же."""
    seen = []
    gh = RestGitHub(lambda repo: seen.append(repo) or "ghs_x")
    headers = gh._headers("po-helper-org/poh-demo-checkout")
    assert seen == ["po-helper-org/poh-demo-checkout"]
    assert headers["Authorization"] == "Bearer ghs_x"
```

```python
# tests/test_checks.py
import json

from poh_howtodemo import checks


class _GH:
    def __init__(self, content):
        self.content = content
        self.asked = []

    def get_file(self, repo, path, ref):
        self.asked.append((repo, path, ref))
        return self.content


def test_reads_service_from_target_repository():
    gh = _GH(json.dumps({"service": {"port": 3000, "start": "node src/server.mjs",
                                     "health_path": "/healthz"}}))
    service = checks.read(gh, "o/r", "abc123")
    assert service["port"] == 3000 and service["start"] == "node src/server.mjs"
    assert gh.asked == [("o/r", ".delivery/checks.json", "abc123")]


def test_absent_file_is_empty_contract_not_an_error():
    assert checks.read(_GH(None), "o/r", "abc123") == {}


def test_broken_json_is_empty_contract():
    assert checks.read(_GH("{не json"), "o/r", "abc123") == {}


def test_checks_array_is_ignored():
    """Проверки Delivery нас не касаются: шаги приходят из сценария."""
    raw = json.dumps({"service": {"start": "x"}, "checks": [{"name": "quote"}]})
    assert checks.service_of(json.loads(raw)) == {"start": "x"}
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `.venv/bin/pytest tests/test_checks.py -q`
Expected: FAIL, `ImportError: cannot import name 'checks'`

- [ ] **Step 3: Написать модуль и расширить порт**

```python
# poh_howtodemo/checks.py
"""Контракт окружения — чем поднимать проверяемый сервис.

Формат берём у Delivery-Agent (`.delivery/checks.json`) и не заводим второй:
целевой репозиторий уже описывает там, как его сервис запускается. Массив
`checks` нас не касается — это регрессионные ассерты от кода, а наши шаги
приходят из сценария приёмки.

Отсутствие файла — не отказ. У Delivery та же ситуация откатывает каждый PR
(документация обещает обратное), у нас она просто оставляет шаги без окружения
и говорит об этом в отчёте.
"""

import json

PATH = ".delivery/checks.json"


def service_of(raw: dict) -> dict:
    service = raw.get("service")
    return service if isinstance(service, dict) else {}


def read(gh, repo: str, ref: str) -> dict:
    """Секция `service` контракта. Пустой словарь — контракта нет."""
    text = gh.get_file(repo, PATH, ref)
    if not text:
        return {}
    try:
        return service_of(json.loads(text))
    except (json.JSONDecodeError, AttributeError):
        return {}
```

В `poh_howtodemo/ports.py` добавить в `GitHubPort` строку после `pull_head`:

```python
    def get_file(self, repo: str, path: str, ref: str) -> str | None: ...
```

В `poh_howtodemo/github.py`: переименовать `self._token` в `self._token_for`,
типизировать провайдер как `Callable[[str], str]`, дать `_headers` параметр
`repo` и передать его во всех вызовах, добавить метод чтения файла:

```python
class RestGitHub:
    def __init__(self, token_provider: Callable[[str], str]):
        self._token_for = token_provider

    def _headers(self, repo: str) -> dict:
        return {"Authorization": f"Bearer {self._token_for(repo)}",
                "Accept": "application/vnd.github+json"}

    def get_file(self, repo: str, path: str, ref: str) -> str | None:
        r = requests.get(f"{API}/repos/{repo}/contents/{path}",
                         headers={**self._headers(repo),
                                  "Accept": "application/vnd.github.raw"},
                         params={"ref": ref}, timeout=TIMEOUT)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text
```

Остальные шесть методов получают `self._headers(repo)` вместо `self._headers()`.

- [ ] **Step 4: Запустить тесты, убедиться, что проходят**

Run: `.venv/bin/pytest tests/test_checks.py tests/test_github.py -q`
Expected: PASS, 5 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/checks.py poh_howtodemo/ports.py poh_howtodemo/github.py tests/test_checks.py tests/test_github.py
git commit -m "feat(checks): контракт окружения из целевого репозитория; fix: провайдер токена принимает репозиторий"
```

---

### Task 2: Эфемерный стенд

**Files:**
- Create: `poh_howtodemo/env.py`
- Modify: `poh_howtodemo/model.py` (добавить `Stand`)
- Test: `tests/test_env.py`

**Interfaces:**
- Consumes: `model.Stand`.
- Produces: `env.container_name(repo, issue) -> str`, класс `EphemeralStand(run_cmd, probe, token_provider, network="", volume=..., mount=...)` с методами `up(repo, issue, sha, service) -> Stand` и `down(repo, issue) -> None`.
  `run_cmd` — `(args: list[str]) -> tuple[int, str]`; `probe` — `(url: str) -> int`, возвращает HTTP-статус, бросает при недоступности.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_env.py
import pytest

from poh_howtodemo import env

SERVICE = {"port": 3000, "start": "node src/server.mjs", "health_path": "/healthz",
           "image": "node:22-slim"}


class _Docker:
    def __init__(self, fail_on=""):
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, args):
        self.calls.append(args)
        if self.fail_on and self.fail_on in " ".join(args):
            return 1, "не вышло"
        return 0, "ok"

    def flat(self):
        return [" ".join(a) for a in self.calls]


def _stand(docker, statuses):
    it = iter(statuses)

    def probe(url):
        value = next(it)
        if isinstance(value, Exception):
            raise value
        return value

    return env.EphemeralStand(run_cmd=docker, probe=probe,
                              token_provider=lambda repo: "ghs_x", network="net")


def test_container_name_never_collides_with_delivery_prod():
    name = env.container_name("po-helper-org/poh-demo-checkout", 12)
    assert name != "poh-delivery-prod"
    assert "poh-demo-checkout" in name and name.endswith("-12")


def test_up_starts_container_and_reports_url():
    docker = _Docker()
    stand = _stand(docker, [200])
    got = stand.up("o/r", 12, "abc123", SERVICE)
    assert got.ok is True
    assert got.url == f"http://{env.container_name('o/r', 12)}:3000"


def test_container_is_ephemeral_not_restarting():
    docker = _Docker()
    _stand(docker, [200]).up("o/r", 12, "abc123", SERVICE)
    run_line = next(c for c in docker.flat() if "docker run" in c)
    assert "--rm" in run_line
    assert "--restart" not in run_line


def test_stale_container_is_reaped_before_start():
    docker = _Docker()
    _stand(docker, [200]).up("o/r", 12, "abc123", SERVICE)
    flat = docker.flat()
    rm_index = next(i for i, c in enumerate(flat) if "docker rm -f" in c)
    run_index = next(i for i, c in enumerate(flat) if "docker run" in c)
    assert rm_index < run_index


def test_no_start_command_means_no_container_at_all():
    docker = _Docker()
    got = _stand(docker, []).up("o/r", 12, "abc123", {"port": 3000})
    assert got.ok is False and "service.start" in got.detail
    assert not any("docker run" in c for c in docker.flat())


def test_probe_retries_until_ready():
    docker = _Docker()
    got = _stand(docker, [OSError("отказ"), 503, 204]).up("o/r", 12, "abc123", SERVICE)
    assert got.ok is True


def test_failed_readiness_carries_container_logs():
    docker = _Docker()
    stand = _stand(docker, [OSError("отказ")] * 50)
    stand.ready_timeout = 0.05
    got = stand.up("o/r", 12, "abc123", SERVICE)
    assert got.ok is False
    assert any("docker logs" in c for c in docker.flat())


def test_down_removes_container():
    docker = _Docker()
    _stand(docker, []).down("o/r", 12)
    assert any("docker rm -f" in c and env.container_name("o/r", 12) in c
               for c in docker.flat())


def test_token_is_only_in_the_remote_url():
    docker = _Docker()
    _stand(docker, [200]).up("o/r", 12, "abc123", SERVICE)
    carrying = [c for c in docker.flat() if "ghs_x" in c]
    assert len(carrying) == 1 and "remote add" in carrying[0]
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `.venv/bin/pytest tests/test_env.py -q`
Expected: FAIL, `ImportError: cannot import name 'env'`

- [ ] **Step 3: Написать стенд**

В `poh_howtodemo/model.py` добавить после `Evidence`:

```python
@dataclass
class Stand:
    """Эфемерное окружение прогона. `ok=False` — шаги пойдут как blocked."""

    ok: bool = False
    url: str = ""
    container: str = ""
    detail: str = ""
```

```python
# poh_howtodemo/env.py
"""Эфемерный стенд: поднять проверяемое состояние из произвольного SHA.

Логика раскладки заимствована у `poh_delivery.prod` — она к «после мержа» не
привязана и берёт head-SHA открытой ветки так же, как влитый. Три отличия
обязательны и не косметические:

1. **Своё имя контейнера.** У Delivery имя зафиксировано константой
   `poh-delivery-prod`, а подъём начинается с `docker rm -f`. Стенд с тем же
   именем снёс бы живой прод соседнего агента.
2. **`--rm` вместо `--restart unless-stopped`.** Прод обязан пережить рестарт
   демона, стенд обязан умереть. Метода гашения в `ProdPort` нет вовсе.
3. **Отсутствие контракта не роняет прогон.** У Delivery пустой `service.start`
   уводит релиз в откат; здесь он просто означает «окружения не будет».

Всё внешнее приходит вызываемыми объектами: модуль тестируется без докера.
"""

import os
import time

from poh_howtodemo.model import Stand

VOLUME = os.environ.get("HOWTODEMO_WORKSPACE_VOLUME", "poh-dev-workspace")
MOUNT = os.environ.get("HOWTODEMO_WORKSPACE_MOUNT", "/workspaces")
RUNTIME_IMAGE = os.environ.get("HOWTODEMO_RUNTIME_IMAGE", "node:22-slim")
READY_TIMEOUT = float(os.environ.get("HOWTODEMO_READY_TIMEOUT", "90"))
POLL_SECONDS = float(os.environ.get("HOWTODEMO_POLL_SECONDS", "2"))


def container_name(repo: str, issue: int) -> str:
    """Имя стенда. Уникально по репозиторию и Issue — и никогда не прод."""
    return f"poh-howtodemo-{repo.replace('/', '__')}-{issue}"


class EphemeralStand:
    def __init__(self, run_cmd, probe, token_provider, network: str = "",
                 volume: str = VOLUME, mount: str = MOUNT):
        self._run = run_cmd
        self._probe = probe
        self._token_for = token_provider
        self._network = network
        self._volume = volume
        self._mount = mount
        self.ready_timeout = READY_TIMEOUT
        self.poll_seconds = POLL_SECONDS

    def _workdir(self, repo: str, issue: int, sha: str) -> str:
        return f"{self._mount}/howtodemo/{repo.replace('/', '__')}-{issue}/{sha}"

    def _materialize(self, repo: str, issue: int, sha: str) -> tuple[bool, str]:
        target = self._workdir(repo, issue, sha)
        url = f"https://x-access-token:{self._token_for(repo)}@github.com/{repo}.git"
        for args in (["git", "init", "--quiet", target],
                     ["git", "-C", target, "remote", "add", "origin", url],
                     ["git", "-C", target, "fetch", "--quiet", "--depth", "1",
                      "origin", sha],
                     ["git", "-C", target, "checkout", "--quiet", "FETCH_HEAD"]):
            code, output = self._run(args)
            if code != 0:
                # Первые три слова команды: имя токена в них не попадает.
                return False, f"{' '.join(args[:3])} → {code}: {output[-300:]}"
        return True, target

    def up(self, repo: str, issue: int, sha: str, service: dict) -> Stand:
        name = container_name(repo, issue)
        start = (service or {}).get("start", "")
        if not start:
            return Stand(ok=False, container=name,
                         detail="в .delivery/checks.json нет service.start — "
                                "окружение поднять нечем")

        ok, target = self._materialize(repo, issue, sha)
        if not ok:
            return Stand(ok=False, container=name, detail=target)

        port = int(service.get("port", 8080))
        image = service.get("image", RUNTIME_IMAGE)

        self._run(["docker", "rm", "-f", name])
        command = ["docker", "run", "-d", "--rm", "--name", name]
        if self._network:
            command += ["--network", self._network]
        command += ["-v", f"{self._volume}:{self._mount}", "-w", target,
                    "-e", f"PORT={port}", image, "sh", "-c", start]
        code, output = self._run(command)
        if code != 0:
            return Stand(ok=False, container=name,
                         detail=f"docker run: {output[-300:]}")

        url = f"http://{name}:{port}"
        ready, detail = self._wait_ready(url, service, name)
        if not ready:
            self.down(repo, issue)
            return Stand(ok=False, container=name, detail=detail)
        return Stand(ok=True, url=url, container=name, detail=detail)

    def _wait_ready(self, url: str, service: dict, name: str) -> tuple[bool, str]:
        health = service.get("health_path", "/")
        deadline = time.monotonic() + self.ready_timeout
        last = ""
        while time.monotonic() < deadline:
            try:
                status = self._probe(url + health)
                # Любой ответ означает, что процесс слушает порт: 404 на корне
                # у сервиса без корневого маршрута — норма, а не незапуск.
                if status < 500:
                    return True, f"ответ {status} на {health}"
                last = f"HTTP {status}"
            except Exception as error:
                last = str(error)[:200]
            time.sleep(self.poll_seconds)
        _code, logs = self._run(["docker", "logs", "--tail", "40", name])
        return False, (f"сервис не ответил за {self.ready_timeout:g}s ({last}); "
                       f"логи: {logs[-500:]}")

    def down(self, repo: str, issue: int) -> None:
        self._run(["docker", "rm", "-f", container_name(repo, issue)])
```

- [ ] **Step 4: Запустить тест, убедиться, что проходит**

Run: `.venv/bin/pytest tests/test_env.py -q`
Expected: PASS, 9 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/env.py poh_howtodemo/model.py tests/test_env.py
git commit -m "feat(env): эфемерный стенд из произвольного SHA, своё имя контейнера"
```

---

### Task 3: Логи сервиса за окно шага

**Files:**
- Create: `poh_howtodemo/collectors/logs.py`
- Test: `tests/test_logs.py`

**Interfaces:**
- Consumes: ничего из ядра.
- Produces: `logs.window(run_cmd, container, since, until) -> str`, `logs.stamp() -> str`.
  `since`/`until` — строки RFC3339, как их понимает `docker logs`.

Обёртки над `docker logs` в контуре нет ни одной — эта первая. Возможность подтверждена живьём: воркер работает от root с прокинутым `/var/run/docker.sock`.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_logs.py
from poh_howtodemo.collectors import logs


def test_window_asks_docker_for_the_step_interval():
    seen = []

    def run_cmd(args):
        seen.append(args)
        return 0, "checkout слушает :3000"

    text = logs.window(run_cmd, "poh-howtodemo-o__r-12",
                       since="2026-08-25T10:00:00Z", until="2026-08-25T10:00:05Z")
    assert "слушает" in text
    args = seen[0]
    assert args[:2] == ["docker", "logs"]
    assert "--since" in args and "2026-08-25T10:00:00Z" in args
    assert "--until" in args and "2026-08-25T10:00:05Z" in args
    assert "--timestamps" in args


def test_failure_becomes_readable_text_not_exception():
    text = logs.window(lambda a: (1, "No such container"), "gone",
                       since="a", until="b")
    assert "No such container" in text


def test_stamp_is_rfc3339_utc():
    value = logs.stamp()
    assert value.endswith("Z") and "T" in value and len(value) == 20
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `.venv/bin/pytest tests/test_logs.py -q`
Expected: FAIL, `ImportError: cannot import name 'logs'`

- [ ] **Step 3: Написать сборщик**

```python
# poh_howtodemo/collectors/logs.py
"""Логи сервиса за окно одного шага.

Обёртки над `docker logs` в контуре нет ни одной — эта первая. Окно берём по
времени, а не хвостом: хвост фиксированной длины на шумном сервисе покажет
чужие строки и спрячет свои.

Отказ команды возвращается текстом: улика «логи снять не удалось, вот почему»
полезнее, чем упавший прогон.
"""

from datetime import datetime, timezone


def stamp() -> str:
    """Отметка времени в том виде, в каком её понимает `docker logs`."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def window(run_cmd, container: str, since: str, until: str) -> str:
    args = ["docker", "logs", "--timestamps",
            "--since", since, "--until", until, container]
    try:
        code, output = run_cmd(args)
    except Exception as exc:
        return f"логи снять не удалось: {type(exc).__name__}: {exc}"
    if code != 0:
        return f"логи снять не удалось (код {code}): {output[-500:]}"
    return output
```

- [ ] **Step 4: Запустить тест, убедиться, что проходит**

Run: `.venv/bin/pytest tests/test_logs.py -q`
Expected: PASS, 3 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/collectors/logs.py tests/test_logs.py
git commit -m "feat(logs): логи сервиса за временное окно шага"
```

---

### Task 4: Проводка стенда в прогон

**Files:**
- Modify: `poh_howtodemo/run.py`
- Test: `tests/test_run_with_stand.py`

**Interfaces:**
- Consumes: `env.EphemeralStand`, `collectors.logs`, `model.Stand`.
- Produces: `run.verify(..., stand=None, sha="", service=None)` — три новых необязательных параметра. Без них поведение среза 1 сохраняется дословно; существующие тесты не меняются.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_run_with_stand.py
import json

from poh_howtodemo import model, run

BODY = """## HowToDemo

1. Отправить `GET /healthz`, увидеть 200 и `status=ok`.
"""

PLAN = json.dumps({"steps": [
    {"n": 1, "text": "GET /healthz", "action": {"kind": "http", "path": "/healthz"},
     "expect": {"status": 200, "json_subset": {"status": "ok"}},
     "evidence": ["response", "service_log"], "source": "Issue #12, шаг 1"},
]})


class _GH:
    def issue_body(self, repo, number): return BODY
    def comments(self, repo, number): return []
    def comment(self, repo, number, body): pass
    def add_label(self, repo, number, label): pass
    def remove_labels(self, repo, number, labels): pass
    def pull_head(self, repo, number): return ("feature/12", "3a1f0c2")
    def get_file(self, repo, path, ref): return None


class _Stand:
    def __init__(self, ok=True):
        self.ok = ok
        self.upped = []
        self.downed = []

    def up(self, repo, issue, sha, service):
        self.upped.append((repo, issue, sha))
        return (model.Stand(ok=True, url="http://stand:3000", container="poh-howtodemo-o__r-12")
                if self.ok else model.Stand(ok=False, detail="нечем поднимать"))

    def down(self, repo, issue):
        self.downed.append((repo, issue))


def _run(stand, tmp_path, send, docker=lambda a: (0, "лог сервиса")):
    return run.verify(repo="o/r", issue=12, pr_number=45, base_url="",
                      root=str(tmp_path), gh=_GH(), translate=lambda s: PLAN,
                      send=send, exec_=lambda c, cwd: (0, ""),
                      run_git=lambda a, c: (0, ""), token="t",
                      stand=stand, sha="3a1f0c2", service={"start": "node x"},
                      run_docker=docker)


def test_stand_supplies_base_url_and_step_runs(tmp_path):
    stand = _Stand()
    rep = _run(stand, tmp_path, send=lambda m, u, j: (200, '{"status": "ok"}'))
    assert stand.upped == [("o/r", 12, "3a1f0c2")]
    assert rep.results[0].outcome == model.PASSED


def test_service_log_is_attached_to_the_step(tmp_path):
    rep = _run(_Stand(), tmp_path, send=lambda m, u, j: (200, '{"status": "ok"}'))
    names = [ev.name for ev in rep.results[0].evidence]
    assert "service_log.txt" in names
    log_ev = next(ev for ev in rep.results[0].evidence if ev.name == "service_log.txt")
    assert (tmp_path / log_ev.path).read_text().strip() == "лог сервиса"


def test_stand_is_always_torn_down(tmp_path):
    stand = _Stand()
    _run(stand, tmp_path, send=lambda m, u, j: (200, '{"status": "ok"}'))
    assert stand.downed == [("o/r", 12)]


def test_stand_is_torn_down_even_when_a_step_explodes(tmp_path):
    stand = _Stand()

    def boom(*_a, **_kw):
        raise OSError("сеть легла")

    rep = _run(stand, tmp_path, send=boom)
    assert stand.downed == [("o/r", 12)]
    assert rep.results[0].outcome == model.FAILED


def test_stand_that_did_not_come_up_blocks_steps_but_not_the_run(tmp_path):
    stand = _Stand(ok=False)
    rep = _run(stand, tmp_path, send=lambda m, u, j: (200, "{}"))
    assert rep.results[0].outcome == model.BLOCKED
    assert rep.verdict == model.V_PARTIAL
    assert stand.downed == [("o/r", 12)]
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `.venv/bin/pytest tests/test_run_with_stand.py -q`
Expected: FAIL, `TypeError: verify() got an unexpected keyword argument 'stand'`

- [ ] **Step 3: Переписать `run.py`**

```python
# poh_howtodemo/run.py
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


def _walk(steps: list[Step], base_url: str, root: str, send, exec_,
          container: str, run_docker):
    """Пройти шаги, приложив к каждому логи сервиса за окно этого шага."""
    results = []
    for step in steps:
        since = log_collector.stamp()
        obs, evidence = _observe(step, base_url, root, send, exec_)
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

    steps = plan.build(scenario, translate)

    container = ""
    try:
        if stand is not None:
            up = stand.up(repo, issue, sha, service or {})
            if up.ok:
                base_url, container = up.url, up.container
        results = _walk(steps, base_url, root, send, exec_, container, run_docker)
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
```

- [ ] **Step 4: Запустить оба набора тестов прогона**

Run: `.venv/bin/pytest tests/test_run.py tests/test_run_with_stand.py -q`
Expected: PASS, 10 passed — старые пять тестов среза 1 не меняются.

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/run.py tests/test_run_with_stand.py
git commit -m "feat(run): стенд в прогоне, логи сервиса на шаг, гашение в finally"
```

---

### Task 5: Активности поднимают настоящий стенд

**Files:**
- Modify: `poh_howtodemo/activities.py`
- Test: `tests/test_activities.py`

**Interfaces:**
- Consumes: `env.EphemeralStand`, `checks.read`, `ports`.
- Produces: `activities.build_stand() -> EphemeralStand`, `activities._docker(args) -> tuple[int, str]`, `activities._probe(url) -> int`; `verify` теперь читает контракт и head-SHA PR.

- [ ] **Step 1: Написать падающий тест**

```python
# tests/test_activities.py
from poh_howtodemo import activities, model


def test_run_root_is_per_repository_and_issue():
    root = activities.run_root("po-helper-org/poh-demo-checkout", 12)
    assert root.endswith("po-helper-org__poh-demo-checkout-12")
    assert root.startswith(activities.WORKSPACE)


def test_stand_is_built_with_own_container_name():
    stand = activities.build_stand(lambda repo: "ghs_x")
    from poh_howtodemo import env
    assert env.container_name("o/r", 12) != "poh-delivery-prod"
    assert stand.ready_timeout > 0


def test_verdict_labels_cover_every_outcome():
    assert set(activities.ALL_VERDICT_LABELS) == {
        model.V_PASSED, model.V_FAILED, model.V_PARTIAL, model.V_NO_SCENARIO}
```

- [ ] **Step 2: Запустить тест, убедиться, что падает**

Run: `.venv/bin/pytest tests/test_activities.py -q`
Expected: FAIL, `AttributeError: module 'poh_howtodemo.activities' has no attribute 'build_stand'`

- [ ] **Step 3: Дописать активности**

В `poh_howtodemo/activities.py` добавить импорты `checks`, `env` и заменить функцию `verify`:

```python
def _docker(args: list[str]) -> tuple[int, str]:
    p = subprocess.run(args, capture_output=True, text=True, timeout=300)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _probe(url: str) -> int:
    return requests.get(url, timeout=5).status_code


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
    service = checks.read(gh, repo, sha) if sha else {}
    return run.verify(repo=repo, issue=issue, pr_number=pr_number, base_url="",
                      root=run_root(repo, issue), gh=gh,
                      translate=ports.llm().translate, send=_send,
                      exec_=_exec, run_git=_git,
                      token=_token_provider(repo) if _token_provider else "",
                      stand=None if _dry_run else build_stand(_token_provider),
                      sha=sha, service=service, run_docker=_docker)
```

Добавить `import os` в начало файла, если его там нет.

Провайдер токена теперь принимает репозиторий (`_token_provider(repo)`) — это тот же контракт, что у `poh_delivery.prod`, где `self._token_for(repo)` вызывается с репозиторием.

- [ ] **Step 4: Запустить весь набор**

Run: `.venv/bin/pytest -q`
Expected: PASS, 70 passed

- [ ] **Step 5: Коммит**

```bash
git add poh_howtodemo/activities.py tests/test_activities.py
git commit -m "feat(activities): настоящий стенд, контракт из целевого репозитория, head-SHA PR"
```

---

## Что срез 2 намеренно не делает

- **Браузера нет** — срез 3, и только после замера RSS headless-Chromium на стенде.
- **Инфра-логов нет.** Состояние Temporal программно не читает никто, `SENTRY_TOKEN` на стенде не задан и без него чтение возвращает пустой список неотличимо от «ошибок нет».
- **Врезки в фазу `testing` нет** — она живёт в `poh-issue-agents` (регистрация `/howtodemo` в `shared/commands._COMMANDS`, ветки вебхука, вызов из `_phase_park`) и уезжает отдельным PR туда.
- **Сборки зависимостей перед стартом нет.** `service.start` исполняется сразу; репозиторию с зависимостями придётся склеить `npm ci && node …` в самой команде, и тогда установка съест часть `READY_TIMEOUT`.
