"""
test_journal_cli.py — j.py argparse help integrity.

Regression for the v2.3.0 sweep finding: `j.py new --help` crashed with
"TypeError: must be real number, not dict" because the --atr-pct help string
contained a literal '%' ("ATR% for snapshot table") that argparse tried to
%-format. A bare '%' in any argparse help= must be escaped as '%%'. This guards
every subcommand's --help against that whole class of bug.
"""
import subprocess
import sys
from pathlib import Path
import pytest

J_PY = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "journal" / "j.py"


@pytest.mark.parametrize("subcmd", ["new", "update", "live", "close", "list"])
def test_subcommand_help_does_not_crash(subcmd):
    """--help must exit 0 and print usage, not raise on help formatting."""
    r = subprocess.run([sys.executable, str(J_PY), subcmd, "--help"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"j.py {subcmd} --help exited {r.returncode}:\n{r.stderr}"
    assert "usage:" in r.stdout.lower()
    assert "Traceback" not in r.stderr


def test_top_level_help_does_not_crash():
    r = subprocess.run([sys.executable, str(J_PY), "--help"],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0
    assert "usage:" in r.stdout.lower()
