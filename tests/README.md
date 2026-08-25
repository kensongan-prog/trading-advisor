# tests/ — pytest suite

Pure-logic tests for the trading-advisor codebase. The suite is deliberately
small and fast (~0.1s total) — it covers the functions where silent regressions
would actually corrupt trading decisions:

| Module | What it tests | Why |
|---|---|---|
| `test_r_math.py` | `compute_r` single-leg, partial fills, invariants | Drives every closed-trade calibration metric |
| `test_btfd_str.py` | `_classify_btfd_str_shared` tier table | v2.0.3 found rail/panel drift; this pins the thresholds |
| `test_us_status.py` | Phase 1 status gating | The dashboard's actionable signal — wrong here either misses setups or surfaces bad ones |
| `test_llm_pcts.py` | Relevance-weighted aggregation | v2.0.4 added relevance; this pins the weights (primary 1.0, mention 0.5, none 0.0) |
| `test_company_label.py` | TICKER→company resolution | v2.0.1/2.0.4 fix: KLSE Chinese form + asset_class normalization |
| `test_data_join.py` | Symbol-keyed joins (zip regression) | The naïve-zip bug appeared twice in production — this pins the correct pattern |

## Running

From the project root:

```bash
# All tests
python3 -m pytest

# One file
python3 -m pytest tests/test_btfd_str.py -v

# Name filter (e.g. only relevance-related)
python3 -m pytest -k "relevance"

# Verbose, with short tracebacks on failure
python3 -m pytest -v --tb=short
```

If pytest isn't installed system-wide, use the project's Playwright venv:

```bash
.venv-playwright/bin/python3 -m pytest
```

## What's intentionally NOT tested

- **Network-dependent code** (Algolia, Finnhub, OpenAI/Codex, yfinance, CoinGecko). Those need integration tests / VCR — separate concern.
- **HTML rendering**. Covered by Playwright snapshots in `.claude/skills/dashboard/snap.py`; not unit-test material.
- **CLI argparse plumbing**. Test the underlying functions, not the argument-parser.
- **Anything that requires LLM responses**. Deterministic only.

## Adding tests

When you fix a bug, add a regression test that fails on the OLD code and
passes on the NEW. The four bugs found during v2.0.x patches were exactly
the kind this suite is meant to prevent recurrence of — every future bug
should leave one of these behind.

Pattern: one `test_*.py` per module-being-tested, with `Test*` classes
grouping related cases. Keep tests pure and fast — no fixtures with side
effects, no API calls, no file I/O beyond reading project data caches.
