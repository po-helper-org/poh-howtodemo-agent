from poh_howtodemo import activities, env, model


def test_run_root_is_per_repository_and_issue():
    root = activities.run_root("po-helper-org/poh-demo-checkout", 12)
    assert root.endswith("po-helper-org__poh-demo-checkout-12")
    assert root.startswith(activities.WORKSPACE)


def test_stand_is_built_with_own_container_name():
    stand = activities.build_stand(lambda repo: "ghs_x")
    assert env.container_name("o/r", 12) != "poh-delivery-prod"
    assert stand.ready_timeout > 0


def test_verdict_labels_cover_every_outcome():
    assert set(activities.ALL_VERDICT_LABELS) == {
        model.V_PASSED, model.V_FAILED, model.V_PARTIAL, model.V_NO_SCENARIO}


class _GH:
    def __init__(self):
        self.added = []
        self.removed = []

    def add_label(self, repo, number, label): self.added.append(label)
    def remove_labels(self, repo, number, labels): self.removed.extend(labels)


async def _finish(monkeypatch, verdict_label):
    from poh_howtodemo import ports

    gh = _GH()
    ports.configure(github=gh)
    monkeypatch.setattr(activities, "_dry_run", False)
    await activities.finish_labels("o/r", 12, verdict_label)
    ports.configure(github=None)
    return gh


async def test_crash_marks_only_the_run_as_failed(monkeypatch):
    """Пустой вердикт = прогон сорвался. Метки demo:* быть не должно."""
    gh = await _finish(monkeypatch, "")
    assert gh.added == [activities.FAILED_LABEL]
    assert not [label for label in gh.added if label.startswith("demo:")]
    assert gh.removed == [activities.RUN_LABEL]


async def test_real_verdict_sets_demo_label(monkeypatch):
    gh = await _finish(monkeypatch, model.V_PARTIAL)
    assert model.V_PARTIAL in gh.added
    assert activities.DONE_LABEL in gh.added
    assert activities.RUN_LABEL in gh.removed
