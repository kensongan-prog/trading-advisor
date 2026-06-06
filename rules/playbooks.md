# Playbooks

Pre-approved, named setups the agent is allowed to trade. Anything outside this list is, by default, a no-trade — write a new playbook first if it earns its keep over time.

Each playbook is a contract: **conditions to enter, where the stop lives, where TP lives, what kills it.** No improvisation on a live setup; improvise in research, then formalize here.

---

## Phase gating (read first)

These playbooks are restricted by the **PHASED RAMP** block at the bottom of CLAUDE.md. Current state:

- **Phase 1 (now)**: only **P1 SPOT** is live. P2 and P3 are DARK until the phase gate clears.
- Re-read the ramp block before promoting yourself.

---

## P1 — Trend Pullback (Equity / ETF, Swing)

**Thesis:** In an established uptrend, a controlled pullback to dynamic support is a buyable spot.

**Conditions (all must hold):**
- Price > 50-day SMA > 200-day SMA (trend filter).
- Pullback of 3–8% from recent swing high, OR tag of 20-EMA on daily.
- RSI(14) daily between 35 and 50 (cooled but not broken).
- Volume on the pullback ≤ average; ideally declining.
- No earnings inside 7 trading days; no FOMC/CPI inside 3 trading days.

**Entry trigger:** First daily close back above the prior day's high after the pullback.

**Stop:** Just below the lowest low of the pullback, OR entry − 1.5 × ATR(14), whichever is wider.

**TP1:** Prior swing high (≥ 1.5R minimum, retire setup if not).
**TP2:** Trail behind 20-EMA after TP1 fills.

**Invalidation:** Daily close below 50-day SMA → exit full.

**Structure:**
- **Phase 1 (current):** SPOT LONG ONLY. No options of any kind, regardless of IV. This is the only setup live during the paper/spot ramp.
- **Phase 2+:** Debit call spread also acceptable if IV is in the bottom third of 1Y range.

**Status:** _Untested in this account. Phase 1 = paper trade until 20 closed trades logged with ≥0R cumulative expectancy. See ramp block in CLAUDE.md._

---

## P2 — Defined-Risk Premium Sale (US Equity Options Only, Swing)

> **PHASE 3 ONLY.** This playbook is DARK in Phase 1 and Phase 2. Do not recommend a P2 setup under any circumstances until the Phase 3 gate clears (≥50 trades + positive expectancy + no doctrine violations in last 20). Acknowledge if a candidate matches the criteria but record it in the journal as "Phase-3-eligible, not live" — do not enter.
>
> **Scope: US equities only.** Malaysian options are not tradable from this account — do NOT apply this playbook to any KLSE name.


**Thesis:** When IV is elevated relative to its own history and the underlying is range-bound at a known support, sell premium with capped wings.

**Conditions:**
- IV rank ≥ 60 on the underlying.
- Price within 2% of a horizontal support that has held ≥ 3 prior tests.
- No binary event (earnings, FDA, etc.) inside the trade duration.
- 30–45 DTE.

**Structure:** Bull put credit spread, short strike ≈ 20-30 delta, long wing 5-10 strikes below.

**Sizing:** Max loss = (width − credit). Size so max loss ≤ per-trade risk %.

**Profit target:** 50% of max credit, GTC.
**Stop:** Loss = 2× credit received OR short strike breached on a daily close.

**Invalidation:** Daily close below the support level we're leaning on.

**Status:** _Untested in this account._

---

## P3 — Convex Tail Bet (Lottery Sleeve)

> **PHASE 3 ONLY.** Lottery sleeve is sized at **$0** in Phase 1 and Phase 2. Catalog interesting candidates in the journal as "Phase-3-eligible, not live" — but no premium gets spent until Phase 3 unlocks.


**Thesis:** Cheap optionality on a low-probability, high-payoff catalyst (regulatory, technical breakout, vol crush reversal). Treated as written-off expense.

**Conditions:**
- Defined-risk only — long call, long put, or debit spread.
- Max premium ≤ 1% of account equity per ticket.
- Total open lottery exposure ≤ lottery-sleeve cap.
- Thesis has a *specific* catalyst date or condition (not "vibes").

**Stop:** None — premium is the stop. Position is sized so going to zero is acceptable.

**Profit target:** Scale out at 2×, 4×, let runner ride.

**Invalidation:** Catalyst date passes without movement → exit remaining.

**Status:** _Allowed but unscaled. Capped sleeve only._

---

## Retired playbooks

_When a playbook's expectancy goes negative over a meaningful sample (≥15 trades) or a market regime change invalidates its edge, retire it here with a post-mortem. Don't delete — calibration depends on knowing what stopped working._

(none yet)

---

## Playbook proposal template

When a recurring setup emerges from journal entries that isn't covered here, draft it in this format. It is not a live playbook until reviewed and added above.

```
NAME:
THESIS:
CONDITIONS:
ENTRY TRIGGER:
STOP:
TP1 / TP2:
INVALIDATION:
STRUCTURE:
WHY ASYMMETRIC: (max loss vs max gain shape)
EVIDENCE: (links to journal entries that suggested this setup)
```
