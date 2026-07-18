"""`memory._wiki.add_note` — `tk wiki add`'s file writer (DESIGN §11). REAL
this batch (declarative front-matter write — see `_wiki.py`'s own
docstring for the "cheap" precedent); every test below is GREEN.
"""

from __future__ import annotations

import pytest

from tradekit.memory import _wiki


def test_add_note_writes_front_matter_and_body(tmp_path) -> None:
    path = _wiki.add_note(
        str(tmp_path / "wiki"),
        "R-009 Drawdown Breaker Tuning",
        "Trailing 30d drawdown at 10% trips reliably; no false positives observed.",
        status="candidate",
        salience=4,
        provenance="research-loop:scout-2",
    )

    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "status: candidate" in text
    assert "salience: 4" in text
    assert "provenance: research-loop:scout-2" in text
    assert "# R-009 Drawdown Breaker Tuning" in text
    assert "Trailing 30d drawdown at 10% trips reliably" in text


def test_add_note_slugifies_the_title_for_the_filename(tmp_path) -> None:
    path = _wiki.add_note(str(tmp_path / "wiki"), "Weird  Title! With Punct.", "body", salience=1)
    assert path.name == "weird-title-with-punct.md"


def test_add_note_rejects_invalid_status(tmp_path) -> None:
    with pytest.raises(_wiki.InvalidWikiStatus):
        _wiki.add_note(str(tmp_path / "wiki"), "T", "body", status="bogus", salience=1)


def test_add_note_rejects_out_of_range_salience(tmp_path) -> None:
    with pytest.raises(ValueError):
        _wiki.add_note(str(tmp_path / "wiki"), "T", "body", salience=6)


def test_add_note_creates_the_wiki_dir_if_missing(tmp_path) -> None:
    wiki_dir = tmp_path / "does" / "not" / "exist"
    path = _wiki.add_note(str(wiki_dir), "Note", "body", salience=1)
    assert path.parent == wiki_dir
