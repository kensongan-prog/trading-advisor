# notes/

Append-only logs for things that don't belong in CHANGELOG.md (release entries), PROJECT_LOG.md (architecture/setup), or git commits (specific code changes).

**Three files, three purposes:**

| File | What goes here |
|---|---|
| `ideas.md` | Future features, "wouldn't it be nice if" thoughts, half-formed concepts. Don't act on these — they're a parking lot. |
| `decisions.md` | Rationale for non-obvious architectural choices. The "why" behind decisions whose answer is hard to reverse-engineer later. |
| `learned.md` | Gotchas, surprises, system quirks. Things you wish you'd known before. The agent reads this at session start to avoid re-discovering known landmines. |

**Format:** flat append-only log. Each entry: `### YYYY-MM-DD — <short heading>` followed by 1-5 sentences. Newest entries at the top so recent context is fastest to scan.

**Read at session start:** the agent's bootstrap prompt includes `notes/learned.md` so known gotchas don't need re-discovering. `ideas.md` and `decisions.md` are read on demand.
