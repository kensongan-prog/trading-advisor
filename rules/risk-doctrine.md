# Risk Doctrine

Operational expansion of AGENTS.md Section 5–6. **These rules are not negotiable mid-trade.** If a rule blocks a setup, the setup loses — never the rule.

## 1. Sizing formula (show this math every time)

```
position_size = (account_equity × risk_per_trade%) ÷ (entry_price − stop_price)
$_at_risk     = position_size × |entry_price − stop_price|
%_at_risk     = $_at_risk ÷ account_equity
```

For options:
```
contracts_max = floor( (account_equity × risk_per_trade%) ÷ max_loss_per_contract )
```
where `max_loss_per_contract = premium_paid` (long option / debit spread) or
`width − credit_received` (credit spread).

## 2. Hard limits (USER CONFIG owns the numbers; doctrine owns the rules)

- **Risk per trade ≤ user-configured ceiling.** If conviction is "Low," size at half.
- **Portfolio heat ≤ user-configured ceiling.** Total $ at risk across all open positions, summed. No new entry allowed if it would exceed heat.
- **Correlation tax.** Two positions with correlation > ~0.7 (same sector, same factor, same crypto majors) count as **1.5×** their notional heat. Three correlated positions = **2×**.
- **Drawdown circuit-breaker.** When equity is down ≥ the configured % from peak: cut position size by 50% on new entries, pause new directional options, no leverage. Reset when peak is reclaimed.
- **Event halts.** Do NOT open new directional exposure within the time-to-event windows below unless the structure is defined-risk and the thesis IS the event:
  - Single-name equity / options: 24h before earnings.
  - Macro: 12h before FOMC / CPI / NFP.
  - Crypto: 48h before a scheduled token unlock > 1% of float.

## 3. Stop-loss rules

- **Mechanical and pre-committed.** Stops are set at thesis-invalidation levels, not pain levels.
- **Defaults:**
  - Structure-based: just beyond the swing point that defines the thesis.
  - ATR-based: 1.5× to 2.5× the recent daily ATR from entry.
  - Whichever is *further* — to give the trade room — unless that breaks the R:R floor.
- **Gappable instruments need a real floor, not a stop.** Crypto over weekends, small caps overnight, anything through earnings: replace the stop with a defined-risk options structure or accept the gap risk explicitly in the case-against.
- **No stop widening, ever.** If price approaches the stop, you may exit early; you may not move the stop further from entry.
- **Trailing rules** (after TP1 hit): trail behind structure or 2× ATR, whichever is tighter. Lock in at least breakeven.

## 4. R-multiple floors

- Minimum recommended setup: **1.5R** to TP1.
- Preferred: **≥ 2R** to TP1 with a runner targeting 3R+.
- If the only way to hit 2R is to tighten the stop into noise, **do not take the trade**. Bad R:R is not fixed by hope.

## 5. Asymmetric structure preference (Section 6 of AGENTS.md, applied)

Among structures expressing the same thesis, rank by:
1. **Bounded max loss** in dollars (must be finite and known before entry).
2. **Best max-gain : max-loss skew** at acceptable probability.
3. **Lowest cost of carry** (theta bleed, financing, IV decay).

Default preferences by view:
- Directional bullish, IV cheap → long call or debit call spread.
- Directional bullish, IV rich → bull put credit spread (defined risk) or covered call on existing equity.
- Directional bearish, defined risk only → long put or debit put spread (no naked shorts).
- Range / mean-revert → iron condor or short strangle ONLY with explicit defined-risk wings.
- Convex tail bet → small-sleeve long OTM option, sized as a written-off expense.

**Never:** naked short calls, naked short puts on individual equities without cash collateral, undefined-risk structures through binary events.

## 6. Barbell construction

- **Safe sleeve** (cash, T-bills, broad index): default ≥ 70% of account.
- **Active sleeve** (this agent's recommendations, defined-risk only): ≤ 25%.
- **Lottery sleeve** (capped, written-off expense bets): ≤ 5%.
- These are *capital allocations*, separate from the per-trade risk %. Per-trade % still applies inside each sleeve.

## 7. Recommendation gates

The agent must answer YES to all of the following before outputting a BUY/SELL:

- [ ] Real, timestamped data was retrieved this session.
- [ ] Confluence: technicals + at least one of {sentiment, fundamentals, flow}.
- [ ] Invalidation level is stated and is a real structural/ATR level, not a round number.
- [ ] Max loss is finite, known, and within per-trade and heat ceilings.
- [ ] R:R to TP1 is ≥ 1.5 (preferably ≥ 2).
- [ ] No event-window collision (Section 2) or, if there is, structure is defined-risk and the event IS the thesis.
- [ ] Case-against is written and is something a reasonable bear/bull would actually say.

If any box is unchecked → **NO-TRADE.**

## 8. Post-trade discipline

- Log to `journal/YYYY-MM-DD_TICKER.md` immediately on entry (even before close).
- On exit, update the same file with realized R, time-in-trade, and a one-line "process correct? / outcome lucky?" note.
- Process-correct losers and outcome-lucky winners both get flagged for review in monthly calibration.
