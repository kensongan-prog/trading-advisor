"""
test_cache_atomic.py — cache_set writes atomically (Phase 4 hardening).

cache_set now writes a temp file then os.replace()s it into place, so a concurrent
reader (the parallel-fetch ThreadPool, or a separate process) never observes a
half-written JSON file. Pins the round-trip and that no temp files leak.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / ".claude" / "skills" / "dashboard"))
import dashboard  # noqa: E402


def test_cache_set_roundtrip_and_stamp(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "CACHE_DIR", tmp_path)
    dashboard.cache_set("foo_bar", {"x": 1})
    p = tmp_path / "foo_bar.json"
    assert p.is_file()
    d = json.loads(p.read_text())          # parses cleanly => not torn
    assert d["x"] == 1
    assert "_fetched_at" in d              # stamped in place


def test_cache_set_leaves_no_temp_files(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "CACHE_DIR", tmp_path)
    dashboard.cache_set("baz", {"y": 2})
    # the temp file must have been renamed away, not left behind
    assert [pp.name for pp in tmp_path.iterdir()] == ["baz.json"]
