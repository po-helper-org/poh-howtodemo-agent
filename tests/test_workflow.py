from poh_howtodemo import integration, model
from poh_howtodemo.workflow import HowToDemoVerify


class _Recorder:
    """Подделка активностей: воркфлоу зовёт их через self._call."""

    def __init__(self, report, explode=False):
        self.report = report
        self.explode = explode
        self.calls = []

    async def __call__(self, name, *args, result_type=None):
        self.calls.append({"name": name, "args": args, "result_type": result_type})
        if name == "howtodemo_verify":
            if self.explode:
                raise RuntimeError("прогон сорвался")
            return self.report
        return None

    def names(self):
        return [c["name"] for c in self.calls]

    def by_name(self, name):
        return next(c for c in self.calls if c["name"] == name)


def _report(verdict):
    return model.RunReport(anchor=model.Anchor(issue=12), verdict=verdict)


async def _drive(verdict, explode=False):
    wf = HowToDemoVerify()
    wf._call = _Recorder(_report(verdict), explode=explode)
    try:
        await wf.run({"repo": "o/r", "issue": 12, "pr_number": 45})
    except RuntimeError:
        pass
    return wf._call


async def test_labels_are_finished_on_success():
    assert (await _drive(model.V_PASSED)).names()[-1] == "howtodemo_finish_labels"


async def test_labels_are_finished_when_there_is_no_scenario():
    """Метка команды обязана сниматься и на пустом исходе — иначе висит вечно."""
    assert "howtodemo_finish_labels" in (await _drive(model.V_NO_SCENARIO)).names()


async def test_report_is_published_before_labels():
    names = (await _drive(model.V_FAILED)).names()
    assert names.index("howtodemo_publish") < names.index("howtodemo_finish_labels")


async def test_verify_declares_its_result_type():
    """Активность зовётся строкой — без result_type конвертер отдаёт голый dict.

    Живой прогон 2026-08-25 упал именно так: `report.verdict` →
    `'dict' object has no attribute 'verdict'`, воркфлоу зациклился на
    повторной активации. Подделка `_call` этого не показывала.
    """
    call = (await _drive(model.V_PASSED)).by_name("howtodemo_verify")
    assert call["result_type"] is model.RunReport


async def test_crashed_run_does_not_claim_the_scenario_failed():
    """Упавший агент — не проваленная приёмка. Вердикта нет, метки demo:* нет."""
    recorder = await _drive(model.V_PASSED, explode=True)
    finish = recorder.by_name("howtodemo_finish_labels")
    assert finish["args"][2] == ""
    assert "howtodemo_publish" not in recorder.names()


def test_integration_exposes_queue_and_lists():
    assert integration.TASK_QUEUE == "howtodemo"
    assert integration.WORKFLOWS and integration.ACTIVITIES
