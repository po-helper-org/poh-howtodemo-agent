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
import socket
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


def own_network(run_cmd) -> str:
    """Сеть, в которой стоит сам воркер, — в неё же ставится стенд.

    Иначе проверка до сервиса не дотянется: стенд адресуется по имени
    контейнера, а имена резолвятся только внутри общей сети. Публиковать порт
    на хост ради собственной же проверки значит открыть стенд наружу без нужды.

    Полагаться на переменную окружения нельзя: она доезжает до контейнера
    только если её пробросил compose, а он этого не делает. Delivery-Agent
    решает это тем же способом — спрашивает докер.
    """
    code, out = run_cmd(["docker", "inspect", socket.gethostname(), "--format",
                         "{{range $name, $_ := .NetworkSettings.Networks}}"
                         "{{$name}} {{end}}"])
    if code != 0:
        return ""
    networks = out.split()
    return networks[0] if networks else ""


class EphemeralStand:
    def __init__(self, run_cmd, probe, token_provider, network: str = "",
                 volume: str = VOLUME, mount: str = MOUNT,
                 publish_port: bool = False):
        self._run = run_cmd
        self._probe = probe
        self._token_for = token_provider
        # Пусто — спросим докер при первом подъёме и запомним. None здесь не
        # используем: пустая строка и есть «ещё не выяснили».
        self._network = network
        self._volume = volume
        self._mount = mount
        # Внутри контура стенд адресуется по имени контейнера и наружу не
        # публикуется — открывать порт ради собственной же проверки незачем.
        # Локальному прогону с ноутбука имя не резолвится, и порт нужен.
        self._publish_port = publish_port
        self.ready_timeout = READY_TIMEOUT
        self.poll_seconds = POLL_SECONDS

    def _resolved_network(self) -> str:
        if not self._network:
            self._network = own_network(self._run) or "-"
        return "" if self._network == "-" else self._network

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
        network = self._resolved_network()
        if network:
            command += ["--network", network]
        if self._publish_port:
            command += ["-p", f"{port}:{port}"]
        command += ["-v", f"{self._volume}:{self._mount}", "-w", target,
                    "-e", f"PORT={port}", image, "sh", "-c", start]
        code, output = self._run(command)
        if code != 0:
            return Stand(ok=False, container=name,
                         detail=f"docker run: {output[-300:]}")

        url = (f"http://127.0.0.1:{port}" if self._publish_port
               else f"http://{name}:{port}")
        ready, detail = self._wait_ready(url, service, name)
        if not ready:
            self.down(repo, issue)
            return Stand(ok=False, container=name, detail=detail)
        return Stand(ok=True, url=url, container=name, workdir=target,
                     detail=detail)

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
