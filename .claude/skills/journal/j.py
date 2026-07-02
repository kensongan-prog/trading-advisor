#!/usr/bin/env python3
"""
j.py — Journal CLI: lifecycle writeback for journal entries.

Source of truth: journal/YYYY-MM-DD_TICKER.md files.
Backups:        .claude/cache/journal_backups/{name}_{timestamp}.md (rotating 10/file).

Subcommands:
    list     — show all journal entries with current status
    show     — print the Status + Updates + Exit sections of one entry
    live     — flip Status to LIVE — paper / LIVE — real; append Updates entry
    update   — append a timestamped note to Updates without changing Status
    close    — flip Status to CLOSED; fill in Exit section with realized R
    dead     — flip Status to DEAD (setup missed / expired)

Usage:
    python3 .claude/skills/journal/j.py list
    python3 .claude/skills/journal/j.py show AUPH
    python3 .claude/skills/journal/j.py live AUPH --paper
    python3 .claude/skills/journal/j.py live AUPH --real --fill 15.65 --shares 287 --time "2026-06-04 09:35 ET"
    python3 .claude/skills/journal/j.py update AUPH --notes "Scaled half at TP1 17.65, trailing remainder behind 20-EMA"
    python3 .claude/skills/journal/j.py close AUPH --result win --r 2.05 --price 17.65 --notes "TP1 hit clean"
    python3 .claude/skills/journal/j.py dead AUPH --reason "Trigger never fired by 2-week expiry"

File lookup: pass a ticker (AUPH) or stem (2026-06-03_AUPH). Multiple matches → error.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILLS_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = SKILLS_DIR.parent.parent
JOURNAL_DIR = PROJECT_ROOT / "journal"
BACKUP_DIR = PROJECT_ROOT / ".claude" / "cache" / "journal_backups"


# ── File location ─────────────────────────────────────────────────────────
def list_entries():
    if not JOURNAL_DIR.is_dir():
        return []
    out = []
    for p in sorted(JOURNAL_DIR.glob("*.md"), reverse=True):
        if p.name.startswith("_") or p.name.lower() == "readme.md":
            continue
        out.append(p)
    return out


def resolve_file(arg):
    """Find a journal file from a ticker (AUPH) or stem (2026-06-03_AUPH) or filename."""
    arg = arg.strip()
    if not arg:
        sys.exit("ERROR: missing identifier")
    # Strip .md if present
    target = arg[:-3] if arg.endswith(".md") else arg
    candidates = list_entries()
    matches = []
    for p in candidates:
        stem = p.stem
        if stem == target:
            return p  # exact stem match wins
        # Ticker tail match: 2026-06-03_AUPH → AUPH
        m = re.match(r"\d{4}-\d{2}-\d{2}_(.+)", stem)
        ticker = m.group(1) if m else stem
        if ticker.upper() == target.upper():
            matches.append(p)
    if not matches:
        sys.exit(f"ERROR: no journal entry matches '{arg}'. Run `j.py list` to see options.")
    if len(matches) > 1:
        print(f"ERROR: '{arg}' matches multiple entries:", file=sys.stderr)
        for m in matches:
            print(f"  {m.name}", file=sys.stderr)
        print("Pass the full stem (e.g. 2026-06-03_AUPH) to disambiguate.", file=sys.stderr)
        sys.exit(1)
    return matches[0]


# ── Status parsing + editing ──────────────────────────────────────────────
STATUS_RE = re.compile(r"^\*\*Status:\*\*\s*(.+?)\s*$", re.MULTILINE)


def read_status(text):
    m = STATUS_RE.search(text)
    return m.group(1).strip() if m else None


def replace_status(text, new_status):
    """Replace the first **Status:** line, or insert near the top if absent."""
    if STATUS_RE.search(text):
        return STATUS_RE.sub(f"**Status:** {new_status}", text, count=1)
    # Insert after first heading
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            lines.insert(i + 1, "")
            lines.insert(i + 2, f"**Status:** {new_status}")
            return "\n".join(lines)
    return text + f"\n\n**Status:** {new_status}\n"


# ── Updates section append ────────────────────────────────────────────────
UPDATES_HEADER_RE = re.compile(r"^##\s+Updates\s*$", re.MULTILINE)


def append_update(text, line):
    """Append a bullet under the ## Updates heading. Creates the section if absent."""
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    bullet = f"- {timestamp} — {line}"
    if not UPDATES_HEADER_RE.search(text):
        # Append the section at end
        if not text.endswith("\n"):
            text += "\n"
        return text + f"\n## Updates\n\n{bullet}\n"
    # Find Updates section bounds: from header to next "## " or EOF
    lines = text.splitlines()
    start = None
    for i, l in enumerate(lines):
        if UPDATES_HEADER_RE.match(l):
            start = i
            break
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    # Insert after last non-blank line within section
    insert_idx = end
    for j in range(end - 1, start, -1):
        if lines[j].strip():
            insert_idx = j + 1
            break
    lines.insert(insert_idx, bullet)
    return "\n".join(lines)


# ── Exit section fill (used on close) ─────────────────────────────────────
EXIT_HEADER_RE = re.compile(r"^##\s+Exit\s*$", re.MULTILINE)


def fill_exit(text, result, r_multiple, price=None, notes=None):
    """Populate the ## Exit section's six lines. Creates section if absent."""
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    exit_block = [
        "## Exit",
        "",
        f"- Date / price / reason: {today} — " + (f"${price}, " if price else "") + f"{result} ({notes or 'see Updates above for context'})",
        f"- Realized R-multiple: {r_multiple:+.2f}R",
        "- Time in trade: (compute from entry → exit; see prior Updates)",
        "- Process correct? (was the gate-clean entry executed per plan? did stops hold?)",
        "- Outcome lucky? (would the same process have failed on a slightly different tape?)",
        "- Lesson (one line): (TODO — fill in)",
    ]
    if not EXIT_HEADER_RE.search(text):
        if not text.endswith("\n"):
            text += "\n"
        return text + "\n" + "\n".join(exit_block) + "\n"
    # Replace the Exit section body
    lines = text.splitlines()
    start = None
    for i, l in enumerate(lines):
        if EXIT_HEADER_RE.match(l):
            start = i
            break
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    new_lines = lines[:start] + exit_block + lines[end:]
    return "\n".join(new_lines)


# ── Atomic write with backup ──────────────────────────────────────────────
def backup_file(path):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    # Microsecond precision so back-to-back commands don't overwrite each other's backups
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S_%f")
    bk = BACKUP_DIR / f"{path.stem}_{ts}.md"
    shutil.copy2(str(path), str(bk))
    # Rotate: keep 10 per file
    siblings = sorted(BACKUP_DIR.glob(f"{path.stem}_*.md"), reverse=True)
    for old in siblings[10:]:
        try:
            old.unlink()
        except Exception:
            pass
    return bk


def atomic_write(path, content):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content if content.endswith("\n") else content + "\n")
    os.replace(str(tmp), str(path))


# ── Dashboard cache invalidation ──────────────────────────────────────────
def invalidate_dashboard_cache():
    """Journal entries are re-read each dashboard build, so nothing per-file to do.
    But we can touch a marker so caching layers (if any) re-evaluate."""
    pass  # no-op for now — dashboard always re-reads journal/


def sync_portfolio():
    """Regenerate portfolio.md from the journal after a status change.
    Best-effort: a sync failure must never block the journal write itself."""
    try:
        sys.path.insert(0, str(SKILLS_DIR / "dashboard"))
        import portfolio
        portfolio.write_portfolio_md()
        print("  ↻ portfolio.md synced from journal")
    except Exception as e:
        print(f"  ⚠ portfolio.md sync skipped ({type(e).__name__}: {e})", file=sys.stderr)


def _render_quality_flags_section(quality_flags_arg):
    """Render the prospectus's '### Structural risk flags' section from a
    comma-separated flag-key string (see dashboard/quality_flags.py — same
    cross-skill import as sync_portfolio above). Records what the operator saw
    in the Risk Simulator at the moment they created this prospectus. Returns
    '' when no flags were passed, so the section is invisible for clean names."""
    keys = [k.strip() for k in (quality_flags_arg or "").split(",") if k.strip()]
    if not keys:
        return ""
    try:
        sys.path.insert(0, str(SKILLS_DIR / "dashboard"))
        import quality_flags as qf
        labels = qf.FLAG_LABELS
    except Exception:
        labels = {}
    lines = [f"- {labels.get(k, ('⚠️', k, k))[0]} **{labels.get(k, ('⚠️', k, k))[1]}:** {labels.get(k, ('⚠️', k, k))[2]}"
             for k in keys]
    return (
        "\n### Structural risk flags\n\n"
        "_Flagged by the Risk Simulator at prospectus creation — warn-loudly-never-block; "
        "this trade was entered with these known:_\n\n"
        + "\n".join(lines) + "\n"
    )


# ── Confirmation ──────────────────────────────────────────────────────────
def confirm(prompt, default_no=True):
    suffix = "[y/N]" if default_no else "[Y/n]"
    try:
        ans = input(f"{prompt} {suffix} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if not ans:
        return not default_no
    return ans in ("y", "yes")


# ── Commands ──────────────────────────────────────────────────────────────
def cmd_list(args):
    entries = list_entries()
    if not entries:
        print("No journal entries.")
        return 0
    print(f"{'file':40}  {'status':50}")
    print(f"{'-'*40}  {'-'*50}")
    for p in entries:
        text = p.read_text()
        st = (read_status(text) or "(no Status field)").split(".")[0][:48]
        if args.status and args.status.lower() not in st.lower():
            continue
        print(f"{p.name:40}  {st:50}")
    return 0


def cmd_show(args):
    p = resolve_file(args.id)
    text = p.read_text()
    print(f"=== {p.name} ===\n")
    status = read_status(text) or "(no Status field)"
    print(f"Status: {status}\n")
    # Print Updates section
    m = UPDATES_HEADER_RE.search(text)
    if m:
        # find section
        s = m.start()
        e = text.find("\n## ", s + 1)
        block = text[s:] if e < 0 else text[s:e]
        print(block.rstrip())
        print()
    # Print Exit section
    m = EXIT_HEADER_RE.search(text)
    if m:
        s = m.start()
        e = text.find("\n## ", s + 1)
        block = text[s:] if e < 0 else text[s:e]
        print(block.rstrip())
    return 0


def cmd_live(args):
    p = resolve_file(args.id)
    text = p.read_text()
    cur = read_status(text)
    if args.paper:
        new_status = "LIVE — paper"
    elif args.real:
        new_status = "LIVE — real"
    else:
        print("ERROR: pass --paper or --real", file=sys.stderr)
        return 2

    # Build the Updates line
    parts = []
    if args.fill is not None:
        parts.append(f"Filled @ ${args.fill}")
    if args.shares is not None:
        parts.append(f"{args.shares} sh")
    if args.time:
        parts.append(f"at {args.time}")
    if args.notes:
        parts.append(args.notes)
    update_line = f"Status → {new_status}." + ((" " + " · ".join(parts) + ".") if parts else "")

    print(f"File:    {p.name}")
    print(f"  OLD status: {cur}")
    print(f"  NEW status: {new_status}")
    print(f"  + Updates:  {update_line}")
    print()
    if not args.yes and not confirm("Proceed?"):
        print("Aborted.")
        return 0

    new_text = replace_status(text, new_status)
    new_text = append_update(new_text, update_line)
    backup_file(p)
    atomic_write(p, new_text)
    invalidate_dashboard_cache()
    sync_portfolio()
    print(f"✓ Updated {p.name}")
    return 0


def cmd_update(args):
    p = resolve_file(args.id)
    if not args.notes:
        print("ERROR: --notes required", file=sys.stderr)
        return 2
    text = p.read_text()
    new_text = append_update(text, args.notes)
    print(f"File:    {p.name}")
    print(f"  + Updates:  {args.notes}")
    print()
    if not args.yes and not confirm("Proceed?"):
        print("Aborted.")
        return 0
    backup_file(p)
    atomic_write(p, new_text)
    print(f"✓ Updated {p.name}")
    return 0


def cmd_close(args):
    p = resolve_file(args.id)
    if args.result not in ("win", "loss", "scratch", "timeout"):
        print("ERROR: --result must be one of: win, loss, scratch, timeout", file=sys.stderr)
        return 2

    # Resolve R: prefer explicit --r; else compute from --entry --stop --exit (+ optional --shares)
    r_value = args.r
    auto_r_note = ""
    record_price = args.price
    if r_value is None:
        if args.entry is None or args.stop is None or args.exit is None:
            print("ERROR: pass --r OR (--entry --stop --exit) so R can be computed.", file=sys.stderr)
            print("Tip: run `j.py r --entry X --stop Y --exit Z` first to see the math.", file=sys.stderr)
            return 2
        exits = parse_csv_floats(args.exit, "exit")
        if args.shares:
            shares = parse_csv_floats(args.shares, "shares")
            if len(shares) != len(exits):
                sys.exit(f"ERROR: --shares has {len(shares)} value(s) but --exit has {len(exits)}.")
        else:
            shares = [1.0] * len(exits)
        per_leg, r_value, total_pl, total_risk = compute_r(args.entry, args.stop, exits, shares)
        # Record price = final exit if --price not explicitly given
        if record_price is None:
            record_price = exits[-1]
        if len(per_leg) > 1:
            leg_summary = " · ".join(f"{leg['shares']:.0f}@${leg['price']:.4f}({leg['r']:+.2f}R)" for leg in per_leg)
            auto_r_note = f" Computed R: entry ${args.entry} · stop ${args.stop} · {leg_summary} → blended {r_value:+.2f}R."
        else:
            auto_r_note = f" Computed R: ({exits[0]:.4f} − {args.entry}) / ({args.entry} − {args.stop}) = {r_value:+.2f}R."

    text = p.read_text()
    cur = read_status(text)
    new_status = f"CLOSED — {args.result} ({r_value:+.2f}R)"
    update_line = (
        f"Status → {new_status}." +
        (f" Exit @ ${record_price}." if record_price else "") +
        auto_r_note +
        (f" Notes: {args.notes}" if args.notes else "")
    )
    args.r = r_value  # keep downstream code happy
    args.price = record_price

    print(f"File:    {p.name}")
    print(f"  OLD status: {cur}")
    print(f"  NEW status: {new_status}")
    print(f"  + Updates:  {update_line}")
    print(f"  + Exit section will be filled (result={args.result}, R={args.r:+.2f})")
    print()
    if not args.yes and not confirm("Proceed?"):
        print("Aborted.")
        return 0
    new_text = replace_status(text, new_status)
    new_text = append_update(new_text, update_line)
    new_text = fill_exit(new_text, args.result, args.r, price=args.price, notes=args.notes)
    backup_file(p)
    atomic_write(p, new_text)
    sync_portfolio()
    print(f"✓ Closed {p.name}  ({args.result} {args.r:+.2f}R)")
    return 0


def parse_csv_floats(s, name):
    try:
        return [float(x.strip()) for x in s.split(",") if x.strip()]
    except ValueError:
        sys.exit(f"ERROR: --{name} must be numbers (e.g. '17.65' or '17.65,17.20')")


def compute_r(entry, stop, exits, shares):
    """Return (per_leg_R [list], blended_R, total_pl, total_risk)."""
    risk_per_share = entry - stop
    if risk_per_share <= 0:
        sys.exit("ERROR: entry must be > stop for a long (shorts not supported in Phase 1).")
    per_leg = []
    total_pl = 0.0
    total_risk = 0.0
    for px, sh in zip(exits, shares):
        leg_pl_per_share = px - entry
        leg_pl = leg_pl_per_share * sh
        leg_risk = risk_per_share * sh
        leg_r = leg_pl_per_share / risk_per_share
        per_leg.append({"price": px, "shares": sh, "pl": leg_pl, "risk": leg_risk, "r": leg_r})
        total_pl += leg_pl
        total_risk += leg_risk
    blended = (total_pl / total_risk) if total_risk else 0.0
    return per_leg, blended, total_pl, total_risk


def cmd_r(args):
    if args.entry <= args.stop:
        sys.exit("ERROR: entry must be > stop for a long (shorts not supported in Phase 1).")
    exits = parse_csv_floats(args.exit, "exit")
    if args.shares:
        shares = parse_csv_floats(args.shares, "shares")
        if len(shares) != len(exits):
            sys.exit(f"ERROR: --shares has {len(shares)} value(s) but --exit has {len(exits)}.")
    else:
        # Equal weight if no quantities provided
        shares = [1.0] * len(exits)

    per_leg, blended, total_pl, total_risk = compute_r(args.entry, args.stop, exits, shares)
    risk_per_share = args.entry - args.stop

    print(f"Entry:        ${args.entry:.4f}")
    print(f"Stop:         ${args.stop:.4f}")
    print(f"Risk / share: ${risk_per_share:.4f}")
    print()

    if len(per_leg) > 1:
        print("Per-leg P/L:")
        for i, leg in enumerate(per_leg, 1):
            print(f"  Leg {i}: {leg['shares']:.0f} sh @ ${leg['price']:.4f}  → ${leg['pl']:+,.2f}  ({leg['r']:+.2f}R)")
        print()
        print(f"  Total P/L:    ${total_pl:+,.2f}")
        print(f"  Total risk:   ${total_risk:,.2f}")
        print(f"  Blended R:    {blended:+.2f}R")
    else:
        print(f"P/L per share:  ${exits[0] - args.entry:+,.4f}")
        print(f"R-multiple:     {blended:+.2f}R")

    # Suggest result classification
    if blended >= 0.1:
        result = "win"
    elif blended <= -0.1:
        result = "loss"
    else:
        result = "scratch"
    # Use final exit price as the "exit price" to record in journal
    record_price = exits[-1]
    print()
    print("Suggested close command (replace TICKER with your ticker/stem):")
    print(f"  python3 .claude/skills/journal/j.py close TICKER \\")
    print(f"      --result {result} --r {blended:+.2f} --price {record_price} \\")
    print(f'      --notes "(your exit notes here)"')

    # Optional: append a note to a journal entry
    if args.append:
        p = resolve_file(args.append)
        leg_summary = " · ".join(f"{leg['shares']:.0f}@${leg['price']:.4f}" for leg in per_leg)
        note = f"R calc: entry ${args.entry} · stop ${args.stop} · exits {leg_summary} → {blended:+.2f}R"
        text = p.read_text()
        new_text = append_update(text, note)
        backup_file(p)
        atomic_write(p, new_text)
        print(f"\n✓ Appended R calc to {p.name}")
    return 0


PROSPECTUS_TEMPLATE = """# {date} — {ticker} ({name})

**Status:** {status_line}

---

## Recommendation (at entry)

- **Action / structure:** {structure}
- **Conviction:** {conviction}{conviction_note}
- **Playbook:** {playbook}
- **Phase tag:** Phase {phase} ({phase_mode})
- **Timeframe:** {timeframe}

### Entry / Stop / TP1 / TP2

| | Value | Logic |
|---|---|---|
| Entry trigger | {entry_logic} | {entry_note} |
| Stop-loss | **{currency}{stop:.{dp}f}** | {stop_logic} |
| TP1 | **{currency}{tp1:.{dp}f}** ({rr1:.2f}R) | {tp1_logic} |
{tp2_row}

### Sizing math

```
Account equity:          ${account:,.0f}
Max risk per trade ({risk_pct:.0%}): ${max_risk:,.0f}
Reference entry:         {currency}{entry:.{dp}f}
Stop:                    {currency}{stop:.{dp}f}
Risk per {unit}:         {currency}{entry:.{dp}f} − {currency}{stop:.{dp}f} = {currency}{risk_per:.{dp}f}
Position size:           {shares_str} {unit_plural}
Notional at entry:       {notional_str}
$ at risk:               ${actual_risk:.2f}  ({actual_risk_pct:.2f}% of equity)
```

- **Max loss:** ${actual_risk:.0f} ({actual_risk_pct:.2f}% of ${account:,.0f}) — hard, finite, known before entry
- **Max gain to TP1:** ~${gain1:.0f} ({rr1:.2f}R)
- **R:R to TP1:** {rr1:.2f}R{rr_floor_note}
- **Portfolio heat after entry:** ${heat_after:.0f} of ${heat_max:.0f} ceiling (headroom ${heat_headroom:.0f})

### Thesis (the confluence)

{thesis}

### Case against (the strongest reason this fails)

{case_against}

### Event risk

{event_risk}
{quality_flags_section}
### Data snapshot

| Field | Value | Source | Fetched (UTC) |
|---|---|---|---|
| Price (reference) | {currency}{entry:.{dp}f} | dashboard sim | {now_utc} |
| RSI(14) daily | {rsi_str} | dashboard cache | {now_utc} |
| ATR(14) % of price | {atr_pct_str} | dashboard cache | {now_utc} |
| Market regime | {regime} (R:R floor {rr_floor_str}) | macro-rates / dashboard | {now_utc} |
| Sector | {sector_str} | dashboard cache | {now_utc} |
| Sentiment flag | {sentiment_flag_str} | dashboard sentiment composite | {now_utc} |
| RS vs SPY (1m) | {rs_1m_str} | dashboard rel_strength cache | {now_utc} |

---

## Updates

_(append timestamped entries via `python3 .claude/skills/journal/j.py update {stem} --notes "..."`)_

- {today} — Prospectus drafted from Risk Simulator. Awaiting trigger / entry decision.

---

## Exit

_(fill in on close via `python3 .claude/skills/journal/j.py close {stem} --result win|loss|scratch --entry X --stop Y --exit Z --shares N`)_

- Date / price / reason:
- Realized R-multiple:
- Time in trade:
- Process correct?
- Outcome lucky?
- Lesson (one line):

---

## File metadata

- **Created:** {today}
- **Source:** generated by `j.py new` (Risk Simulator → prospectus stub)
- **Account size at draft:** ${account:,.0f}
- **Phase at draft:** Phase {phase} ({phase_mode})

> ℹ This stub captures the minimum doctrine fields. For high-conviction trades, enrich the **Thesis**, **Case against**, **Event risk**, and add an **Execution protocol** section before going live. The agent can do this on request.
"""


def cmd_new(args):
    """Create a new prospectus stub from CLI args (typically called from the Risk Simulator)."""
    ticker = args.ticker.strip().upper()
    market = (args.market or "us").lower()
    entry = float(args.entry)
    stop  = float(args.stop)
    tp1   = float(args.tp1)
    tp2   = float(args.tp2) if args.tp2 else None
    shares = float(args.shares) if args.shares else None
    if entry <= stop:
        print(f"❌ entry ({entry}) must be > stop ({stop}) for a long.", file=sys.stderr)
        return 2
    if tp1 <= entry:
        print(f"❌ TP1 ({tp1}) must be > entry ({entry}).", file=sys.stderr)
        return 2

    currency = {"us": "$", "klse": "MYR ", "crypto": "$"}.get(market, "$")
    unit = "share" if market in ("us", "klse") else "unit"
    unit_plural = "shares" if market in ("us", "klse") else "units"
    dp = 4 if entry < 5 else 2

    account  = float(args.account or 20000)
    risk_pct = float(args.risk_pct or 0.02)
    max_risk = account * risk_pct
    heat_used = float(args.heat_used or 0)
    heat_max  = float(args.heat_max or 1200)

    risk_per = entry - stop
    if shares is None:
        shares = (max_risk / risk_per)
        if market in ("us", "klse"):
            # Round to lot
            lot = 100 if market == "klse" else 1
            shares = (shares // lot) * lot
        else:
            shares = round(shares, 6)  # fractional crypto
    actual_risk = shares * risk_per
    actual_risk_pct = actual_risk / account * 100
    notional = shares * entry
    gain1 = (tp1 - entry) * shares
    rr1 = (tp1 - entry) / risk_per
    rr2 = ((tp2 - entry) / risk_per) if tp2 else None
    heat_after = heat_used + actual_risk
    heat_headroom = heat_max - heat_after

    shares_str = f"{shares:,.0f}" if market != "crypto" else f"{shares:.6f}"
    notional_str = (f"{currency}{notional:,.2f}" if market in ("us", "crypto")
                    else f"MYR {notional:,.2f}")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    stem = f"{today}_{ticker.replace('.', '_')}"
    file_path = JOURNAL_DIR / f"{stem}.md"

    if file_path.exists() and not args.overwrite:
        print(f"❌ {file_path.name} already exists. Pass --overwrite to replace it.", file=sys.stderr)
        return 1

    # Compose template variables
    name = args.name or ticker
    phase = args.phase or 1
    phase_mode = args.phase_mode or "paper"
    structure = args.structure or ("BUY — SPOT LONG (Phase 1)" if phase == 1 else "BUY — spot long")
    conviction = (args.conviction or "Medium").title()
    conviction_note = f" — {args.conviction_note}" if args.conviction_note else ""
    playbook = args.playbook or ("P1 — Trend Pullback" if phase == 1 else "—")
    timeframe = args.timeframe or "Swing, 4–8 weeks"
    status_line = args.status_line or f"PROSPECTUS — pending entry trigger. Convert to LIVE — {phase_mode} once trigger fires (see ENTRY section)."
    entry_logic = args.entry_logic or f"Limit at {currency}{entry:.{dp}f} (sim reference)"
    entry_note = args.entry_note or "Per Risk Simulator output"
    stop_logic = args.stop_logic or f"Sim default (1.5× ATR or 5% below entry, whichever is tighter)"
    tp1_logic = args.tp1_logic or f"2R above entry per doctrine R:R floor"
    tp2_row = (f"| TP2 | **{currency}{tp2:.{dp}f}** ({rr2:.2f}R) | {args.tp2_logic or 'Trail behind structure after TP1'} |"
               if tp2 else "")
    thesis = args.thesis or "_(To be filled in. Sim verdict was GO/GO-WITH-CAVEATS; document the confluence — trend + RSI zone + sector/macro context + any sentiment/fundamental edge.)_"
    case_against = args.case_against or "_(To be filled in. The strongest specific reason this trade fails — single-name catalyst risk, sector exposure, gap risk on overnight news.)_"
    event_risk = args.event_risk or "_(To be filled in. Pull next earnings via us-fundamentals; check macro-calendar halt windows; for crypto: verify unlocks via crypto-unlocks.)_"
    regime = args.regime or "—"
    rr_floor_note = f" (regime floor {args.rr_floor})" if args.rr_floor else ""
    rr_floor_str = args.rr_floor or "—"
    rsi_str = args.rsi or "—"
    atr_pct_str = (f"{args.atr_pct}" if args.atr_pct else "—")
    sector_str = args.sector or "—"
    sentiment_flag_str = args.sentiment_flag or "—"
    rs_1m_str = args.rs_1m or "—"
    quality_flags_section = _render_quality_flags_section(args.quality_flags)

    body = PROSPECTUS_TEMPLATE.format(
        date=today, today=today, now_utc=now_utc,
        ticker=ticker, name=name, status_line=status_line,
        structure=structure, conviction=conviction, conviction_note=conviction_note,
        playbook=playbook, phase=phase, phase_mode=phase_mode, timeframe=timeframe,
        entry_logic=entry_logic, entry_note=entry_note,
        stop_logic=stop_logic, tp1_logic=tp1_logic, tp2_row=tp2_row,
        currency=currency, dp=dp,
        entry=entry, stop=stop, tp1=tp1,
        risk_per=risk_per, rr1=rr1, account=account, risk_pct=risk_pct,
        max_risk=max_risk, actual_risk=actual_risk, actual_risk_pct=actual_risk_pct,
        shares_str=shares_str, notional_str=notional_str,
        unit=unit, unit_plural=unit_plural,
        gain1=gain1, heat_after=heat_after, heat_max=heat_max, heat_headroom=heat_headroom,
        rr_floor_note=rr_floor_note, rr_floor_str=rr_floor_str,
        regime=regime, rsi_str=rsi_str, atr_pct_str=atr_pct_str,
        sector_str=sector_str, sentiment_flag_str=sentiment_flag_str, rs_1m_str=rs_1m_str,
        stem=stem,
        thesis=thesis, case_against=case_against, event_risk=event_risk,
        quality_flags_section=quality_flags_section,
    )

    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    file_path.write_text(body)
    print(f"✓ Created prospectus: journal/{file_path.name}")
    print(f"  Stem (for j.py update/close): {stem}")
    print(f"  Status: PROSPECTUS (use `j.py live {stem}` when entry fires)")
    print()
    print(f"  Sizing summary: {shares_str} {unit_plural} @ {currency}{entry:.{dp}f}")
    print(f"  $ at risk: ${actual_risk:.2f} ({actual_risk_pct:.2f}% of ${account:,.0f})")
    print(f"  R:R to TP1: {rr1:.2f}R" + (f" · R:R to TP2: {rr2:.2f}R" if rr2 else ""))
    print(f"  Heat after entry: ${heat_after:.0f} of ${heat_max:.0f} (headroom ${heat_headroom:.0f})")
    print()
    print(f"  → Open the file to flesh out Thesis / Case against / Event risk:")
    print(f"    open journal/{file_path.name}")
    return 0


def cmd_dead(args):
    p = resolve_file(args.id)
    text = p.read_text()
    cur = read_status(text)
    new_status = "DEAD — setup expired"
    if args.reason:
        new_status = f"DEAD — {args.reason}"[:80]
    update_line = f"Status → {new_status}." + (f" Reason: {args.reason}" if args.reason else "")
    print(f"File:    {p.name}")
    print(f"  OLD status: {cur}")
    print(f"  NEW status: {new_status}")
    print()
    if not args.yes and not confirm("Proceed?"):
        print("Aborted.")
        return 0
    new_text = replace_status(text, new_status)
    new_text = append_update(new_text, update_line)
    backup_file(p)
    atomic_write(p, new_text)
    print(f"✓ Marked dead: {p.name}")
    return 0


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="Journal CLI — status writeback + Updates/Exit fills")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="Show all journal entries with status")
    pl.add_argument("--status", help="Filter to entries whose status contains this substring")
    pl.set_defaults(func=cmd_list)

    ps = sub.add_parser("show", help="Print Status + Updates + Exit sections of one entry")
    ps.add_argument("id", help="Ticker or stem (e.g. AUPH or 2026-06-03_AUPH)")
    ps.set_defaults(func=cmd_show)

    plive = sub.add_parser("live", help="Flip Status → LIVE (paper or real)")
    plive.add_argument("id")
    grp = plive.add_mutually_exclusive_group(required=False)
    grp.add_argument("--paper", action="store_true")
    grp.add_argument("--real", action="store_true")
    plive.add_argument("--fill", type=float, help="Actual fill price")
    plive.add_argument("--shares", type=int, help="Shares filled")
    plive.add_argument("--time", help="Fill time (free-form, e.g. '2026-06-04 09:35 ET')")
    plive.add_argument("--notes", help="Extra context for the Updates entry")
    plive.add_argument("--yes", "-y", action="store_true")
    plive.set_defaults(func=cmd_live)

    pu = sub.add_parser("update", help="Append a timestamped Updates entry (no status change)")
    pu.add_argument("id")
    pu.add_argument("--notes", required=True)
    pu.add_argument("--yes", "-y", action="store_true")
    pu.set_defaults(func=cmd_update)

    pc = sub.add_parser("close", help="Flip Status → CLOSED + fill Exit section (R can be auto-computed)")
    pc.add_argument("id")
    pc.add_argument("--result", required=True, choices=["win", "loss", "scratch", "timeout"])
    pc.add_argument("--r", type=float, help="Realized R-multiple (e.g. 2.05 or -1.0). If omitted, pass --entry --stop --exit to auto-compute.")
    pc.add_argument("--entry", type=float, help="Entry price (for auto R-compute)")
    pc.add_argument("--stop", type=float, help="Stop price (for auto R-compute)")
    pc.add_argument("--exit", help="Exit price(s) — single ('17.65') or comma-list ('17.65,17.20') for partial fills")
    pc.add_argument("--shares", help="Share counts per exit leg, comma-list matching --exit ('177,177'). Omit for equal-weight blend.")
    pc.add_argument("--price", type=float, help="Price to record in journal (defaults to last value in --exit)")
    pc.add_argument("--notes", help="Exit context")
    pc.add_argument("--yes", "-y", action="store_true")
    pc.set_defaults(func=cmd_close)

    pr = sub.add_parser("r", help="Calculate R-multiple from entry/stop/exit (supports partial fills)")
    pr.add_argument("--entry", type=float, required=True)
    pr.add_argument("--stop", type=float, required=True)
    pr.add_argument("--exit", required=True, help="Exit price(s) — single ('17.65') or comma-list ('17.65,17.20')")
    pr.add_argument("--shares", help="Share counts per exit leg, comma-list matching --exit. Omit for equal-weight blend.")
    pr.add_argument("--append", help="Also append the calc as an Updates note in this journal entry (ticker or stem)")
    pr.set_defaults(func=cmd_r)

    pd = sub.add_parser("dead", help="Mark a prospectus as DEAD (trigger missed / setup expired)")
    pd.add_argument("id")
    pd.add_argument("--reason", help="Short reason")
    pd.add_argument("--yes", "-y", action="store_true")
    pd.set_defaults(func=cmd_dead)

    pn = sub.add_parser("new", help="Create a new prospectus stub from sim output (the Risk Sim's 'Create prospectus' button generates this command)")
    pn.add_argument("ticker", help="Ticker symbol (e.g. KO, 9431.KL, BTC)")
    pn.add_argument("--entry", type=float, required=True)
    pn.add_argument("--stop",  type=float, required=True)
    pn.add_argument("--tp1",   type=float, required=True)
    pn.add_argument("--tp2",   type=float)
    pn.add_argument("--shares", help="Position size (passed as float for crypto fractional); if omitted, computed from --risk-pct + --account")
    pn.add_argument("--market", choices=["us", "klse", "crypto"], help="Default us")
    pn.add_argument("--name", help="Full company / asset name")
    pn.add_argument("--account", type=float, help="Account equity (default 20000)")
    pn.add_argument("--risk-pct", type=float, help="Max risk per trade (default 0.02)")
    pn.add_argument("--heat-used", type=float, help="Current open-position heat in USD (default 0)")
    pn.add_argument("--heat-max", type=float, help="Heat ceiling in USD (default 1200)")
    pn.add_argument("--phase", type=int, choices=[1,2,3], help="Phase tag (default 1)")
    pn.add_argument("--phase-mode", choices=["paper", "real"], help="Default paper")
    pn.add_argument("--conviction", choices=["Low","Medium","High"], help="Default Medium")
    pn.add_argument("--conviction-note", help="One-line conviction qualifier")
    pn.add_argument("--structure", help="Trade structure description")
    pn.add_argument("--playbook", help="Playbook reference")
    pn.add_argument("--timeframe", help="Hold-period expectation")
    pn.add_argument("--status-line", help="Override the Status field")
    pn.add_argument("--entry-logic", help="Entry trigger description (Logic column)")
    pn.add_argument("--entry-note", help="Entry note")
    pn.add_argument("--stop-logic", help="Stop-loss reasoning")
    pn.add_argument("--tp1-logic", help="TP1 reasoning")
    pn.add_argument("--tp2-logic", help="TP2 reasoning")
    pn.add_argument("--thesis", help="One-paragraph thesis (the confluence)")
    pn.add_argument("--case-against", help="Strongest reason this fails")
    pn.add_argument("--event-risk", help="Earnings / macro / unlock notes")
    pn.add_argument("--regime", help="Current macro regime label (e.g. CAUTIOUS)")
    pn.add_argument("--rr-floor", help="Active R:R floor (e.g. 2.0R)")
    pn.add_argument("--rsi", help="RSI(14) for snapshot table")
    pn.add_argument("--atr-pct", help="ATR%% for snapshot table")
    pn.add_argument("--quality-flags", help="Comma-separated structural-quality flag keys from the Risk Simulator (e.g. PENNY,LOW_MC) — records what was known at entry")
    pn.add_argument("--sector", help="Sector at entry, for calibration-report bucketing")
    pn.add_argument("--sentiment-flag", help="Retail-sentiment contrarian flag at entry (FADE/BUY), for calibration-report bucketing")
    pn.add_argument("--rs-1m", help="1-month relative strength vs SPY at entry (e.g. +3.2%%), for calibration-report bucketing")
    pn.add_argument("--overwrite", action="store_true", help="Replace if file already exists today")
    pn.set_defaults(func=cmd_new)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
