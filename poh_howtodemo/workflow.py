"""HowToDemoVerify — приёмка от команды до отчёта.

Три шага, и последний обязан выполниться при любом исходе: метка запуска,
которую никто не снял, остаётся на Issue навсегда.
"""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from poh_howtodemo.model import RunReport, V_FAILED

# Потолок попыток ОДИН: повтор дорогой недетерминированной работы означает
# повтор всей работы, а не починку сбоя.
_ONCE = RetryPolicy(maximum_attempts=1)

_TIMEOUTS = {"howtodemo_verify": timedelta(minutes=40)}


@workflow.defn(name="HowToDemoVerify")
class HowToDemoVerify:
    async def _call(self, name: str, *args):
        return await workflow.execute_activity(
            name, args=list(args), retry_policy=_ONCE,
            start_to_close_timeout=_TIMEOUTS.get(name, timedelta(minutes=5)))

    @workflow.run
    async def run(self, params: dict) -> str:
        repo, issue = params["repo"], params["issue"]
        pr_number = params.get("pr_number", 0)
        verdict_label = V_FAILED
        try:
            report: RunReport = await self._call("howtodemo_verify", repo, issue,
                                                 pr_number)
            verdict_label = report.verdict
            await self._call("howtodemo_publish", repo, issue, pr_number, report)
        finally:
            await self._call("howtodemo_finish_labels", repo, issue, verdict_label)
        return verdict_label
