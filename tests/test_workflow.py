from poh_howtodemo import integration, model
from poh_howtodemo.workflow import HowToDemoVerify


class _Recorder:
    """Подделка активностей: воркфлоу зовёт их через self._call."""

    def __init__(self, report):
        self.report = report
        self.calls = []

    async def __call__(self, name, *args):
        self.calls.append((name, args))
        if name == "howtodemo_verify":
            return self.report
        return None


def _report(verdict):
    return model.RunReport(anchor=model.Anchor(issue=12), verdict=verdict)


async def _drive(verdict):
    wf = HowToDemoVerify()
    wf._call = _Recorder(_report(verdict))
    await wf.run({"repo": "o/r", "issue": 12, "pr_number": 45})
    return [name for name, _ in wf._call.calls]


async def test_labels_are_finished_on_success():
    names = await _drive(model.V_PASSED)
    assert names[-1] == "howtodemo_finish_labels"


async def test_labels_are_finished_when_there_is_no_scenario():
    """Метка команды обязана сниматься и на пустом исходе — иначе висит вечно."""
    names = await _drive(model.V_NO_SCENARIO)
    assert "howtodemo_finish_labels" in names


async def test_report_is_published_before_labels():
    names = await _drive(model.V_FAILED)
    assert names.index("howtodemo_publish") < names.index("howtodemo_finish_labels")


def test_integration_exposes_queue_and_lists():
    assert integration.TASK_QUEUE == "howtodemo"
    assert integration.WORKFLOWS and integration.ACTIVITIES
