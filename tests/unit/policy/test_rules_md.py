"""`rules/RULES.md` generation (DESIGN §7.1) — SPRINT P3 batch A extension:
R-017/R-018 rows + the accepted-but-unenforced AccountConfig slots footer
(TD-24). No pre-existing test file covered `render_rules_md` before this
batch; these assertions are new, not a migration of prior coverage.
"""

from __future__ import annotations

from tradekit.policy._rules import RULES
from tradekit.policy._rules_md import render_rules_md


def test_render_includes_a_row_for_every_registered_rule_id() -> None:
    rendered = render_rules_md()
    for rule in RULES:
        assert f"| {rule.id} |" in rendered, f"{rule.id} missing from rendered RULES.md"


def test_render_includes_r017_and_r018() -> None:
    rendered = render_rules_md()
    assert "| R-017 |" in rendered
    assert "| R-018 |" in rendered


def test_render_footer_names_the_accepted_but_unenforced_slots() -> None:
    rendered = render_rules_md()
    assert "max_daily_profit" in rendered
    assert "consistency_rule" in rendered
    assert "no enforcing rule" in rendered.lower() or "unenforced" in rendered.lower()


def test_write_rules_md_round_trips_through_the_committed_path(tmp_path, monkeypatch) -> None:
    from tradekit.policy import _rules_md

    target = tmp_path / "RULES.md"
    monkeypatch.setattr(_rules_md, "RULES_MD_PATH", target)
    written = _rules_md.write_rules_md()
    assert written == target
    assert target.read_text(encoding="utf-8") == render_rules_md()
