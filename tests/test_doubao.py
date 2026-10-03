"""Tests for the Doubao writer: a Chinese voice that never touches qwen's files.

The invariants these tests encode:

    * Doubao strokes land only under doubao/ -- the qwen writer owns everything else
    * same (seed, seq) plans the same stroke; different seed differs
    * the state file survives restarts and window_tally only counts the open window
    * every code module in the pool is proven to run (doctests executed, no trust)
"""

from __future__ import annotations

import doctest
import types
from pathlib import Path

from iamai import doubao

CJK = "\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u96f6"


def _is_chinese(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


# --- plan_stroke: deterministic, cycling, always in doubao/ -----------------


def test_plan_stroke_rotates_through_all_kinds():
    kinds = {doubao.plan_stroke(seed=3, seq=i)["kind"] for i in range(1, len(doubao.KINDS) * 2 + 1)}
    assert kinds == set(doubao.KINDS)


def test_plan_stroke_is_reproducible_for_a_seed():
    assert doubao.plan_stroke(seed=11, seq=7) == doubao.plan_stroke(seed=11, seq=7)
    assert doubao.plan_stroke(seed=11, seq=7) != doubao.plan_stroke(seed=12, seq=7)


def test_every_stroke_stays_under_doubao():
    for seq in range(1, 60):
        stroke = doubao.plan_stroke(seed=20261003, seq=seq)
        assert stroke["path"].startswith("doubao/"), stroke["path"]
        assert stroke["text"].strip()
        assert stroke["kind"] in doubao.KINDS or stroke["kind"] == "dnote"


def test_prose_strokes_are_written_in_chinese():
    for seq in range(1, 40):
        stroke = doubao.plan_stroke(seed=9, seq=seq)
        if stroke["kind"] in ("dthought", "dnote", "dpoem", "dstory"):
            assert _is_chinese(stroke["text"]), f"stroke {seq} should be Chinese: {stroke['text']!r}"


def test_dcode_stroke_carries_a_real_module(tmp_path: Path):
    stroke = doubao.plan_stroke(seed=5, seq=5, root=tmp_path)  # KINDS index 4 -> dcode
    assert stroke["kind"] == "dcode"
    assert stroke["path"].startswith("doubao/code/")
    assert "def " in stroke["text"]


# --- apply_stroke: append for prose, new file for code ----------------------


def test_apply_stroke_appends_two_blocks(tmp_path: Path):
    stroke = {"kind": "dthought", "path": "doubao/thoughts.md", "text": "- 你好\n", "index": 1}
    first = doubao.apply_stroke(stroke, root=tmp_path)
    second = doubao.apply_stroke(stroke, root=tmp_path)
    assert first == second
    text = second.read_text(encoding="utf-8")
    assert text.count("- 你好") == 2
    assert text.startswith("# 一句话"), "first write must seed the header"


def test_apply_stroke_creates_parent_directories(tmp_path: Path):
    path = doubao.apply_stroke(
        {"kind": "dnote", "path": "doubao/deep/nested.md", "text": "x\n"}, root=tmp_path
    )
    assert path.exists() and path.parent.is_dir()


def test_apply_dcode_stroke_writes_the_pooled_module(tmp_path: Path):
    stroke = doubao.plan_stroke(seed=5, seq=5, root=tmp_path)
    path = doubao.apply_stroke(stroke, root=tmp_path)
    assert path.suffix == ".py"
    assert path.read_text(encoding="utf-8") == stroke["text"]


def test_dcode_falls_back_to_a_note_when_the_file_already_exists(tmp_path: Path):
    stroke = doubao.plan_stroke(seed=5, seq=5, root=tmp_path)
    (tmp_path / "doubao" / "code").mkdir(parents=True, exist_ok=True)
    (tmp_path / stroke["path"]).write_text("old\n", encoding="utf-8")
    again = doubao.plan_stroke(seed=5, seq=5, root=tmp_path)
    assert again["kind"] == "dnote"
    assert again["path"] == "doubao/notes.md"
    assert "已经在代码池里" in again["text"]


# --- state: survives restarts, counts only the open window ------------------


def test_state_roundtrip_and_tally(tmp_path: Path):
    state = doubao.DoubaoState(path=tmp_path / "doubao_state.json")
    assert state.next_seq() == 1
    state.record(kind="dthought", path="doubao/thoughts.md")
    state.record(kind="dnote", path="doubao/notes.md")
    state.record(kind="dthought", path="doubao/thoughts.md")
    assert state.next_seq() == 4
    assert state.tally == {"dthought": 2, "dnote": 1}
    reloaded = doubao.DoubaoState(path=tmp_path / "doubao_state.json")
    assert reloaded.next_seq() == 4, "state must survive a restart"
    assert reloaded.tally == {"dthought": 2, "dnote": 1}


def test_window_tally_filters_by_since(tmp_path: Path):
    state = doubao.DoubaoState(path=tmp_path / "doubao_state.json")
    state.record(kind="dthought", path="p")
    state.record(kind="dpoem", path="p")
    # record() stamps at second precision; two back-to-back records may share a
    # second, so pin the timestamps to make the window arithmetic deterministic.
    state.data["history"][0]["at"] = "2026-10-03T03:28:00+00:00"
    state.data["history"][1]["at"] = "2026-10-03T03:29:00+00:00"
    marker = state.data["history"][0]["at"]
    assert state.window_tally(marker) == {"dpoem": 1}
    assert state.window_tally(None) == {"dthought": 1, "dpoem": 1}


# --- the code pool must be proven, not trusted -------------------------------


def test_every_doubao_code_module_passes_doctests():
    assert doubao.CODE, "the pool must not be empty"
    for name, source in doubao.CODE:
        module = types.ModuleType(name)
        exec(compile(source, name, "exec"), module.__dict__)  # noqa: S102 -- curated pool
        failed = doctest.testmod(module, verbose=False).failed
        assert failed == 0, f"{name} has failing doctests"


def test_doubao_state_file_lives_away_from_qwens():
    assert doubao.STATE_PATH.name == "doubao_state.json"
    assert doubao.STATE_PATH.parent.name == "data"
