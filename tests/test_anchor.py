from poh_howtodemo import anchor, model

BODY_FORM = """Надо починить расчёт.

## HowToDemo

1. Отправить `GET /healthz`.
2. Увидеть 200 и поле `status`.

Прочее.
"""

LETTER_FORM = """## 📋 БФТ (быстрый проход)

**Цель:** что-то.

**How to demo:**
1. Открыть страницу.
2. Нажать кнопку.

**Открытые вопросы:**
- нет
"""


def test_finds_section_in_issue_body():
    steps = anchor.parse_steps(anchor.extract_block(BODY_FORM))
    assert steps == ["Отправить `GET /healthz`.", "Увидеть 200 и поле `status`."]


def test_finds_bold_block_in_bft_letter():
    steps = anchor.parse_steps(anchor.extract_block(LETTER_FORM))
    assert steps == ["Открыть страницу.", "Нажать кнопку."]


def test_body_wins_over_letter():
    got = anchor.fix(12, BODY_FORM, [(7, LETTER_FORM)])
    assert got is not None
    a, steps = got
    assert a.source == model.BODY and a.comment_id == 0
    assert steps[0].startswith("Отправить")


def test_first_letter_edition_wins_over_later():
    later = LETTER_FORM.replace(
        "**Цель:**",
        "_Редакция 2 — с учётом замечаний из обсуждения._\n\n**Цель:**")
    got = anchor.fix(12, "нет сценария", [(7, LETTER_FORM), (9, later)])
    assert got is not None
    a, _ = got
    assert a.source == model.COMMENT and a.comment_id == 7


def test_no_scenario_anywhere():
    assert anchor.fix(12, "просто текст", [(7, "и тут ничего")]) is None


def test_reread_reports_change():
    a, _ = anchor.fix(12, BODY_FORM, [])
    changed_body = BODY_FORM.replace("200", "204")
    steps, changed = anchor.reread(a, changed_body, [])
    assert changed is True
    assert "204" in steps[1]
