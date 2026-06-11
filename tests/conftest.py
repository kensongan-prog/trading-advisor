"""
conftest.py — pytest setup for the trading-advisor project.

The project's skills are not packaged (no setup.py, no __init__.py); they're
loose Python modules under .claude/skills/<skill-name>/. This conftest adds
each skill dir to sys.path so tests can `import news_glyph`, `import j` etc.
directly.

Run from project root:
    python3 -m pytest                 # all tests
    python3 -m pytest tests/test_btfd.py -v   # one file
    python3 -m pytest -k "relevance"  # name filter
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = PROJECT_ROOT / ".claude" / "skills"

# Add every skill directory to sys.path so module imports work
for skill in SKILLS_DIR.iterdir():
    if skill.is_dir() and not skill.name.startswith("."):
        sys.path.insert(0, str(skill))
