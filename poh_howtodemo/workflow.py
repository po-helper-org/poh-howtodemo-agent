"""HowToDemoVerify — приёмка от команды до отчёта.

Три шага, и последний обязан выполниться при любом исходе: метка запуска,
которую никто не снял, остаётся на Issue навсегда.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from poh_howtodemo.model import RunReport

# Потолок попыток ОДИН: повтор дорогой недетерминированной работы означает
# повтор всей работы, а не починку сбоя.
_ONCE = RetryPolicy(maximum_attempts=1)

_TIMEOUTS = {"howtodemo_verify": timedelta(minutes=40)}


@workflow.defn(name="HowToDemoVerify")
class HowToDemoVerify:
    async def _call(self, name: str, *args, result_type=None):
        """Активность по имени-строкой.

        `result_type` обязателен для всего, что возвращает не-примитив: имя
        строкой не несёт аннотации, и без него конвертер Temporal отдаёт голый
        `dict`. Найдено живым прогоном — `report.verdict` падал с
        `'dict' object has no attribute 'verdict'`, а тест на подделке `_call`
        этого не видел, потому что подделка возвращала уже готовый dataclass.
        """
        return await workflow.execute_activity(
            name, args=list(args), retry_policy=_ONCE, result_type=result_type,
            start_to_close_timeout=_TIMEOUTS.get(name, timedelta(minutes=5)))

    @workflow.run
    async def run(self, params: dict) -> str:
        repo, issue = params["repo"], params["issue"]
        pr_number = params.get("pr_number", 0)
        # Пусто — прогон не дошёл до вердикта. Это НЕ «сценарий не пройден»:
        # метку demo:* в таком случае не ставим вовсе, иначе упавший агент
        # выглядит как проваленная приёмка продукта.
        verdict_label = ""
        try:
            report: RunReport = await self._call("howtodemo_verify", repo, issue,
                                                 pr_number, result_type=RunReport)
            verdict_label = report.verdict
            await self._call("howtodemo_publish", repo, issue, pr_number, report)
        finally:
            await self._call("howtodemo_finish_labels", repo, issue, verdict_label)
        return verdict_label
