# last30days shadow assessment - 2026-08-20

## Decision summary

Do not replace Trading Advisor's current research/data pulls with
`last30days` v3.16.0. Keep it as an analyst-invoked, shadow-only supplement for
widely discussed assets and breaking community narratives. It is useful for a
fresh Reddit pulse on a major crypto asset, but it is not a safe canonical feed
for sparse US tickers or opaque KLSE identifiers.

No dashboard cache, runtime configuration, recommendation input, source
precedence, broker setting, order, or execution control changed during this
assessment.

## Scope and method

The bounded no-cookie probe used three watchlist entities selected to stress
different mapping and coverage conditions:

- `AUPH` - Aurinia Pharmaceuticals, a sparse US small-cap ticker
- `SOL` - Solana, a major crypto asset with a dedicated community
- `9431.KL` - Seni Jaya Corporation Berhad / `SJC`, an opaque Bursa code

All runs used `FROM_BROWSER=off`, browser-store reads remained disabled, and no
paid research-provider credential was active. Host-native web search supplied
first-party supplements. The engine ran in `--quick` mode with explicit JSON
plans, resolved communities, and separate output files outside dashboard
caches. A process-local `SSL_CERT_FILE` pointed Python 3.12 at its installed
Certifi bundle after the initial doctor probe exposed a missing default CA
chain. No global TLS or skill configuration changed.

## Results by entity

| Entity | last30days result | Current Trading Advisor artifact comparison | Assessment |
|---|---|---|---|
| AUPH | Three Reddit items, all unrelated tickers, all score `0`, all explicitly marked `entity-miss demotion`; no usable AUPH evidence | StockTwits cache has 30 messages classified as 27 primary and 3 mention; Finnhub cache has 3 news items and 51 rating rows; Reddit cache honestly records four HTTP 429 failures | Replacement-blocking precision failure. A no-coverage result would have been safer than returning score-zero false positives. |
| SOL | Three fresh `r/solana` threads dated through 2026-08-18, with 174 upvotes and 100 comments; correct entity mapping and useful tokenomics debate | StockTwits cache has 30 messages, classified as 5 primary and 25 mention; professional crypto-news cache has 8 items; Reddit cache records HTTP 429 failures | Useful additive community pulse. Coverage remained one-source on the first run and did not replace professional news, market, technical, or flow data. |
| 9431.KL | Zero Reddit/YouTube results, with an honest no-candidate warning | KLSE comments cache has 25 messages, classified as 9 primary and 16 mention; KLSE-news cache has 11 mapped items; project mapping explicitly knows `9431`, `SJC`, Seni Jaya, and the Chinese company name | Correct degraded behavior, but substantially worse coverage than the current KLSE-specific paths. |

At probe time, the compared Trading Advisor caches were fetched on 2026-07-29,
roughly 22 days old. `last30days` therefore won the freshness comparison for
SOL by finding discussion through 2026-08-18. That is evidence that it can help
during a stale-cache incident, not evidence that its source design is better:
the existing adapters support source-specific refresh and typed TTL/error
artifacts, while the dashboard refresh path was simply not current.

## Dimension assessment

| Dimension | Better choice | Evidence |
|---|---|---|
| Freshness during current stale-cache state | last30days for active communities | SOL evidence reached 2026-08-18 versus Trading Advisor cache fetches on 2026-07-29. |
| Breadth of decision-grade data | Trading Advisor | Current skills separate professional news, retail forums, prediction markets, prices, technicals, fundamentals, events, and asset-specific sources. `last30days` returned only Reddit in two of three first runs. |
| Provenance | Tie, with different strengths | `last30days` saves raw URLs, dates, engagement, scores, and source coverage. Trading Advisor saves typed per-source caches with fetch times, exact queries, rate-limit errors, relevance classes, and downstream aggregation fields. |
| Precision and fail-closed behavior | Trading Advisor | AUPH's score-zero entity misses survived into the final `last30days` result. Trading Advisor has explicit ticker aliases and per-item primary/mention/off-topic classification. |
| Opaque ticker and alternate-language mapping | Trading Advisor | The `9431` path maps Bursa code, `SJC`, English company name, and Chinese name; `last30days` found nothing despite an explicit full-name plan. |
| Direct monetary cost | last30days in this configuration | No paid provider key was active, so the direct provider cost was zero. Host web search and agent reasoning still consume usage. |
| Latency and scalable refresh cost | Trading Advisor | The four engine passes reported 8.5s, 12.9s, 15.6s, and 13.1s of research time. A normal repeated SOL run re-fetched Reddit and YouTube rather than reusing immutable per-item retrieval. |
| Cache reuse | Trading Advisor | Repeating the identical SOL query took 13.1s after 15.6s, repeated the network lanes, and changed YouTube coverage from zero to one item. The saved-library context was reused, but retrieval was not. |
| Failure observability | Trading Advisor overall | Trading Advisor retains HTTP 429s and no-coverage states per source. `last30days` has good doctor/source-status surfaces, but diagnostics advertised X through `xurl` while every actual run omitted X and printed an unlock message. |

## Failure categories observed

- Transient/environmental: Python 3.12's default CA path was incomplete, causing
  free HTTP probes to fail certificate verification. A process-local Certifi
  path made GitHub, HN, Polymarket, and Reddit probes healthy.
- Configuration/contract mismatch: diagnostics listed X as available through
  stored `xurl` OAuth, but topic runs did not activate X and instead requested
  new X authentication.
- Optional no-coverage: TikTok and Instagram were unavailable without a
  ScrapeCreators key; arXiv, Digg, Techmeme, and Trustpilot CLIs were absent.
- Honest no-coverage: 9431.KL returned zero usable evidence and preserved that
  fact.
- Permanent precision defect for replacement use: AUPH returned three unrelated
  score-zero posts instead of filtering them all out.
- Reproducibility/cache behavior: identical SOL runs produced different YouTube
  coverage and repeated retrieval work. That is acceptable for an interactive
  dossier, not for a deterministic dashboard cache builder without an
  additional normalization and persistence layer.

## Cost and operational fit

The tested configuration has zero direct provider spend because it uses public
Reddit, YouTube, HN, Polymarket, GitHub, and host-native web search. That makes
it attractive for occasional analyst research. It is not automatically cheaper
as a dashboard replacement: each ticker needs planning, network retrieval,
ranking, and synthesis, and the identical repeat showed no per-item retrieval
reuse. Scaling the measured quick-run latency across the watchlist would add
minutes of work and more failure surfaces before any typed cache adapter,
relevance gate, or deterministic aggregation was built.

Trading Advisor's current adapters also use mostly free/public data and cache
source artifacts by ticker. Its incremental LLM work is performed only where
classification or news relevance is needed, and its immutable news scores are
designed for reuse. The current stale-cache incident should be repaired in that
pipeline rather than addressed by replacing the pipeline with query-time
research.

## Recommended future use

Use `last30days` only when an analyst wants a fresh narrative dossier or a
second-source community check, especially for crypto and heavily discussed US
names. Do not feed its output directly into recommendations or the dashboard.

Before reconsidering even a shadow dashboard adapter, require all of the
following:

1. Drop every candidate with entity-miss or non-positive relevance before
   rendering or scoring.
2. Make actual X activation agree with diagnostics under no-cookie `xurl`.
3. Add a typed per-ticker result contract with explicit `success`,
   `no_coverage`, `partial`, `transient_error`, and `permanent_error` states.
4. Persist immutable item IDs and reuse retrieved/scored items across runs.
5. Enforce explicit ticker aliases and asset-class mapping, including KLSE code,
   short name, English name, and alternate-language names.
6. Validate a larger fixed fixture set before any operator cutover decision.

Any source cutover remains a separate operator decision.

## Evidence artifacts

Raw probe artifacts were deliberately kept outside dashboard caches at
`/private/tmp/ta-last30days-shadow-20260820/`:

- AUPH SHA-256: `006b66d5b36d554efcc07356bafbe042db6c06d2a5edbefd8b398a0ca7d56811`
- SOL first-run SHA-256: `c09a21e452202bedbba90bde1b71732987ce5c86f20818d9ff96481e0c18b4ee`
- SOL repeat SHA-256: `8a9b4cd9ea1066b3fff018626609c6e75a210cb62c615536d045b1ca6de38933`
- 9431.KL SHA-256: `617b7799fa24ee73b9656461e4d6c4155452f37e81ebf9902b0b9de2155bcf88`

The raw files contain untrusted public internet text and supplemental source
descriptions. They were never consumed by Trading Advisor runtime code.
