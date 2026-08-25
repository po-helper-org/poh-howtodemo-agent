"""Логи сервиса за окно одного шага.

Обёртки над `docker logs` в контуре нет ни одной — эта первая. Возможность
подтверждена живьём: воркер работает от root с прокинутым `/var/run/docker.sock`
и видит все контейнеры хоста.

Окно берём по времени, а не хвостом: хвост фиксированной длины на шумном сервисе
покажет чужие строки и спрячет свои.

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
