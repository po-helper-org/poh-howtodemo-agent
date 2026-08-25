from dataclasses import asdict

from poh_howtodemo import model


def test_anchor_is_pointer_not_copy():
    """Якорь хранит адрес и хэш источника, а не текст сценария."""
    a = model.Anchor(issue=12, source=model.BODY, sha256="a1b2", taken_at="2026-08-25T10:00:00Z")
    assert asdict(a)["sha256"] == "a1b2"
    assert not hasattr(a, "text")


def test_step_defaults_to_unmapped():
    """Шаг без разобранного действия по умолчанию неисполним, а не 'GET /'."""
    s = model.Step(n=1, text="проверяю письмо")
    assert s.action.kind == model.UNMAPPED
