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
