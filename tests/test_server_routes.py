"""
test_server_routes.py — server Job semantics + refresh wiring.

The "one job at a time" contract is the root of the v2.2.0 silent-no-op fix: a
second refresh while one is running must be rejected (ok:false), not silently
swallowed. Pins the Job busy semantics, status shape, and the Quick/Full flag
contract. Avoids spinning a real HTTP socket — tests the Job class + module
constants directly.
"""
import sys
import time
import pytest
import server


SHORT_JOB = [sys.executable, "-c", "import time; time.sleep(1.0)"]


class TestRefreshFlags:
    def test_quick_is_stale_driven(self):
        # v2.2.0 contract: Quick refreshes exactly what Data Health flags stale
        assert server.QUICK_FLAGS == ["--refresh-stale"]

    def test_full_force_rebuilds_everything(self):
        assert "--force" in server.FULL_FLAGS
        assert "--refresh-sentiment" in server.FULL_FLAGS
        assert "--with-discovery" in server.FULL_FLAGS


class TestJobSemantics:
    def test_fresh_job_is_idle(self):
        j = server.Job()
        s = j.status()
        assert s["state"] == "idle"
        assert s["label"] == ""

    def test_start_returns_true_then_false_while_running(self):
        j = server.Job()
        assert j.start("first", SHORT_JOB) is True
        # second start while the first is alive must be refused — the no-op fix
        assert j.start("second", SHORT_JOB) is False
        assert j.status()["label"] == "first"   # label unchanged by refused start

    def test_status_shape(self):
        j = server.Job()
        j.start("labeltest", SHORT_JOB)
        s = j.status()
        assert set(s.keys()) == {"state", "label", "log_tail", "finished_at"}
        assert s["state"] == "running"
        assert isinstance(s["log_tail"], list)

    def test_job_completes_and_frees_slot(self):
        j = server.Job()
        j.start("done-test", SHORT_JOB)
        # wait for the short subprocess to finish (generous bound)
        for _ in range(50):
            if j.status()["state"] in ("done", "error"):
                break
            time.sleep(0.1)
        assert j.status()["state"] == "done"
        # slot is free again → a new job can start
        assert j.start("next", SHORT_JOB) is True


class TestRefreshSourceWiring:
    def test_health_module_loaded(self):
        # /api/refresh-source depends on the health module being importable
        assert server._health_mod is not None

    def test_validate_rejects_agent_only(self):
        ok, msg = server._health_mod.validate_refresh_source("crypto_unlocks")
        assert ok is False
        assert "agent" in msg.lower()

    def test_validate_accepts_server_source(self):
        ok, via = server._health_mod.validate_refresh_source("polymarket")
        assert ok is True
        assert via[0] == "flag"
