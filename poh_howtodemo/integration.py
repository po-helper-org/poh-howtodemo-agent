"""Точка подключения к Harness.

Harness отдаёт агенту ровно одно — функцию выдачи токена GitHub. Всё остальное
агент конструирует сам. Обратной зависимости нет: этот пакет не импортирует из
Harness ничего.

    from poh_howtodemo import integration as howtodemo

    howtodemo.install(github_client.auth_token, dry_run=DRY_RUN, llm=...)
    Worker(client, task_queue=howtodemo.TASK_QUEUE,
           workflows=howtodemo.WORKFLOWS, activities=howtodemo.ACTIVITIES, ...)
"""

from poh_howtodemo import activities, ports
from poh_howtodemo.github import RestGitHub
from poh_howtodemo.workflow import HowToDemoVerify

TASK_QUEUE = "howtodemo"
WORKFLOWS = [HowToDemoVerify]
ACTIVITIES = [activities.verify, activities.publish_report, activities.finish_labels]


def install(token_provider, dry_run: bool = False, llm=None, shell=None) -> None:
    ports.configure(github=RestGitHub(token_provider), llm=llm, shell=shell)
    activities.configure(token_provider, dry_run=dry_run)
