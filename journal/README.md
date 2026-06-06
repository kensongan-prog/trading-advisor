# Journal

One file per trade: `YYYY-MM-DD_TICKER.md` (entry date in filename).

Write the entry **at the moment of recommendation**, not after the fact. Update on exit. Outcomes without a pre-committed thesis are noise.

## Template

```
# YYYY-MM-DD — TICKER

## Recommendation (at entry)
- Action / structure:
- Conviction:
- Playbook: (P1 / P2 / P3 / off-book)
- Entry / Stop / TP1 / TP2:
- Max loss ($, % of equity):
- Max gain ($ or "uncapped") / Skew:
- R:R:
- Thesis (3–5 sentences, the confluence):
- Case against:
- Event risk:
- Data snapshot (price, indicators, IV/Greeks if option) with source + timestamp:

## Updates
- YYYY-MM-DD HH:MM — what happened / what I did

## Exit
- Date / price / reason (stop hit / TP hit / thesis broke / time stop):
- Realized R:
- Time in trade:
- Process correct? (was the recommendation gate-clean, did we follow stops?)
- Outcome lucky? (would the same process have failed on a slightly different tape?)
- Lesson (one line):
```

## Calibration cadence

- **Weekly:** scan new entries; flag any that broke gates and shouldn't have shipped.
- **Monthly:** win rate, avg R, distribution of R, hit rate by playbook. Retire playbooks whose expectancy < 0 over ≥15 trades.
- **Quarterly:** revisit risk doctrine numbers (per-trade %, heat ceiling, circuit-breaker) against realized vol of the account.
