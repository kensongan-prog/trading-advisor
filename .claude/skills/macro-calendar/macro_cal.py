#!/usr/bin/env python3
"""
calendar.py — US macro release calendar for the §5 halt-window check.

Reads a maintained JSON schedule (schedule.json) of FOMC / CPI / NFP / PCE
release dates and computes "hours until next event" + halt-window status.

Subcommands:
    next      Next event of each type (FOMC/CPI/NFP/PCE) with hours-until and halt-window flag.
    list      All events in the next N days (default 30).
    check     Is RIGHT NOW (or a specified entry time) inside any halt window? Returns YES/NO + which event.

Times in schedule.json are US Eastern (America/New_York); script normalizes to UTC for math.

Per AGENTS.md §5: 12-hour halt window before any FOMC / CPI / NFP scheduled event.
This script ALSO treats PCE the same way (Fed's preferred inflation gauge).

Usage:
    python3 calendar.py next
    python3 calendar.py list --days 14
    python3 calendar.py check
    python3 calendar.py check --at "2026-06-09 15:00 ET"
    python3 calendar.py check --window-hours 24
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except ImportError:
    # macOS system Python 3.9 may lack zoneinfo data; fall back to fixed UTC-4 with DST caveat
    # (acceptable for halt-window math — error is ≤1 hour around DST changes)
    ET = timezone(timedelta(hours=-4))


DEFAULT_HALT_WINDOW_HOURS = 12  # AGENTS.md §5 default
EXTENDED_HALT_WINDOW_HOURS = 24  # for Conservative aggression profile or high-conviction trades


def load_schedule():
    p = Path(__file__).resolve().parent / "schedule.json"
    if not p.is_file():
        raise SystemExit(f"ERROR: schedule.json not found at {p}")
    data = json.loads(p.read_text())
    # Sanity-check NFP weekday (catches catalog entry errors)
    for ev in data.get("events", []):
        if ev.get("type") == "NFP":
            try:
                d = datetime.strptime(ev["date"], "%Y-%m-%d")
                if d.weekday() != 4:  # 4 = Friday
                    print(f"⚠ schedule.json WARNING: NFP entry {ev['date']} is a "
                          f"{d.strftime('%A')}, expected Friday. Verify against BLS.",
                          file=sys.stderr)
            except ValueError:
                pass
    return data


def parse_event_dt(event):
    """Parse event date+time (ET) into a UTC-aware datetime."""
    d = event["date"]
    t = event.get("time_et", "08:30")
    dt_et = datetime.strptime(f"{d} {t}", "%Y-%m-%d %H:%M").replace(tzinfo=ET)
    return dt_et.astimezone(timezone.utc)


def parse_user_time(s):
    """Parse user-provided time. Accepts:
      - 'now' (default)
      - 'YYYY-MM-DD HH:MM' (interpreted as ET)
      - 'YYYY-MM-DD HH:MM ET'
      - 'YYYY-MM-DD HH:MM UTC' / 'Z'
    """
    s = s.strip()
    if s.lower() == "now":
        return datetime.now(timezone.utc)
    if s.endswith(" ET"):
        s = s[:-3]
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=ET)
        return dt.astimezone(timezone.utc)
    if s.endswith(" UTC"):
        s = s[:-4]
        return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    if s.endswith("Z"):
        s = s[:-1]
        return datetime.strptime(s, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    # Default: interpret as ET
    dt = datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=ET)
    return dt.astimezone(timezone.utc)


def fmt_hours(h):
    if h < 0:
        return f"{abs(h):.1f}h AGO"
    if h < 24:
        return f"{h:.1f}h FROM NOW"
    days = h / 24
    return f"{days:.1f} days from now"


def cmd_next(args):
    sched = load_schedule()
    now = datetime.now(timezone.utc)
    verified_through = sched["_meta"].get("verified_through", "unknown")
    print("MACRO CALENDAR — NEXT EVENT OF EACH TYPE")
    print(f"Source:        maintained schedule.json (verified through {verified_through})")
    print(f"Fetched (UTC): {now.isoformat(timespec='seconds')}")
    print(f"Halt window:   {args.window_hours}h before event (per §5)")
    print()

    next_of = {}
    for ev in sched["events"]:
        dt = parse_event_dt(ev)
        if dt < now:
            continue
        if ev["type"] not in next_of or dt < next_of[ev["type"]][0]:
            next_of[ev["type"]] = (dt, ev)

    if not next_of:
        print("⚠ No upcoming events in schedule. RE-VERIFY catalog against official sources.")
        return 1

    print(f"{'event':6}  {'date (ET)':20}  {'time (ET)':10}  {'in':>20}  {'halt?':8}  note")
    for typ in ("FOMC", "CPI", "PCE", "NFP"):
        if typ not in next_of:
            print(f"{typ:6}  ⚠ no upcoming entry — schedule may need refresh")
            continue
        dt, ev = next_of[typ]
        dt_et = dt.astimezone(ET)
        hrs = (dt - now).total_seconds() / 3600
        in_halt = 0 <= hrs <= args.window_hours
        halt_str = "🛑 YES" if in_halt else "ok"
        print(f"{typ:6}  {dt_et.strftime('%Y-%m-%d (%a)'):20}  {ev.get('time_et','—'):10}  {fmt_hours(hrs):>20}  {halt_str:8}  {ev.get('note','')}")
    print()
    # Schedule freshness warning
    try:
        vt = datetime.strptime(verified_through, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if (vt - now).days < 60:
            print(f"⚠ Schedule verified through {verified_through} — < 60d remaining. Refresh catalog.")
    except Exception:
        pass
    return 0


def cmd_list(args):
    sched = load_schedule()
    now = datetime.now(timezone.utc)
    cutoff = now + timedelta(days=args.days)
    rows = []
    for ev in sched["events"]:
        dt = parse_event_dt(ev)
        if now <= dt <= cutoff:
            rows.append((dt, ev))
    rows.sort(key=lambda r: r[0])
    print(f"MACRO CALENDAR — NEXT {args.days} DAYS")
    print(f"Fetched (UTC): {now.isoformat(timespec='seconds')}")
    print(f"Halt window:   {args.window_hours}h before each event")
    print(f"Events found:  {len(rows)}")
    print()
    if not rows:
        print("(no events in window)")
        return 0
    print(f"{'date (ET)':20}  {'time (ET)':10}  {'type':6}  {'in':>20}  {'halt?':8}  note")
    for dt, ev in rows:
        dt_et = dt.astimezone(ET)
        hrs = (dt - now).total_seconds() / 3600
        in_halt = 0 <= hrs <= args.window_hours
        print(f"{dt_et.strftime('%Y-%m-%d (%a)'):20}  {ev.get('time_et','—'):10}  {ev['type']:6}  {fmt_hours(hrs):>20}  {'🛑 YES' if in_halt else 'ok':8}  {ev.get('note','')}")
    return 0


def cmd_check(args):
    sched = load_schedule()
    at = parse_user_time(args.at) if args.at else datetime.now(timezone.utc)
    at_et = at.astimezone(ET)
    print(f"HALT-WINDOW CHECK")
    print(f"Source:        maintained schedule.json")
    print(f"Entry time:    {at.isoformat(timespec='seconds')}  ({at_et.strftime('%Y-%m-%d %H:%M ET')})")
    print(f"Halt window:   {args.window_hours}h before event (per §5)")
    print()

    in_halts = []
    for ev in sched["events"]:
        dt = parse_event_dt(ev)
        if dt < at:
            continue  # event already passed
        hrs_until = (dt - at).total_seconds() / 3600
        if hrs_until <= args.window_hours:
            in_halts.append((hrs_until, ev, dt))

    if not in_halts:
        # Find next event of any type
        upcoming = []
        for ev in sched["events"]:
            dt = parse_event_dt(ev)
            if dt > at:
                upcoming.append((dt, ev))
        if upcoming:
            upcoming.sort()
            dt_next, ev_next = upcoming[0]
            hrs = (dt_next - at).total_seconds() / 3600
            print(f"✓ NOT in halt window. Next event: {ev_next['type']} on {dt_next.astimezone(ET).strftime('%Y-%m-%d %H:%M ET')} ({fmt_hours(hrs)}).")
            print(f"  Doctrine: entry permitted at this time.")
        else:
            print("⚠ No upcoming events found — schedule may be exhausted. Re-verify catalog.")
        return 0

    print(f"🛑 IN HALT WINDOW — {len(in_halts)} event(s) within {args.window_hours}h:")
    for hrs, ev, dt in sorted(in_halts):
        print(f"  - {ev['type']} on {dt.astimezone(ET).strftime('%Y-%m-%d %H:%M ET')}  ({fmt_hours(hrs)})  {ev.get('note','')}")
    print()
    print("Doctrine action (per AGENTS.md §5):")
    print("  - NO new directional exposure on US single-name equity within this window.")
    print("  - Defined-risk options structures only IF the event IS the thesis (currently DARK in Phase 1).")
    print("  - Existing positions: review and consider trim/hedge before event.")
    return 1


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    pn = sub.add_parser("next", help="Next event of each type")
    pn.add_argument("--window-hours", type=int, default=DEFAULT_HALT_WINDOW_HOURS)
    pn.set_defaults(func=cmd_next)

    pl = sub.add_parser("list", help="Events in the next N days")
    pl.add_argument("--days", type=int, default=30)
    pl.add_argument("--window-hours", type=int, default=DEFAULT_HALT_WINDOW_HOURS)
    pl.set_defaults(func=cmd_list)

    pc = sub.add_parser("check", help="Is given time in any halt window?")
    pc.add_argument("--at", default=None,
                    help="Time to check (default: now). Format: 'YYYY-MM-DD HH:MM' (ET default), "
                         "or append ' ET' / ' UTC' / 'Z'.")
    pc.add_argument("--window-hours", type=int, default=DEFAULT_HALT_WINDOW_HOURS)
    pc.set_defaults(func=cmd_check)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
