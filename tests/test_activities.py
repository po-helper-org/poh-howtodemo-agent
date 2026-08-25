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
