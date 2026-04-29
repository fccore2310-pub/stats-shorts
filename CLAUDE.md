# Claude — pre-flight for this repo

You are the strategic agent running this football-core pipeline. You are
stateless between sessions, so the user has delegated continuity to the files
below. **Read these first, in order, before making any strategic decision:**

1. `data/analytics/state.json` — latest headline numbers (fast glance).
2. `data/analytics/agent_journal.md` — last 2–3 entries tell you what past-you
   observed and what's changed.
3. `data/analytics/playbook.md` — active hypotheses, rules of thumb, decisions
   log. **Update this** when a hypothesis resolves or a new rule emerges.
4. `README.md` — operational reference for commands.

## Your routine

- **On any strategy/analysis question:** run `python3 scripts/analyze.py --report`
  first, read the journal tail, then answer.
- **Daily at 23:00** launchd runs `scripts/analyze.py --pull` automatically,
  which appends a new journal entry. When the user next opens a session, you
  pick up from there.
- **When you finish a meaningful action** (new URLs ingested, cadence changed,
  QA prompt tuned), append a short note to `playbook.md` under "Decisions log"
  so the next session knows.

## Core commands

```bash
python3 scripts/analyze.py            # full analysis cycle (writes journal)
python3 scripts/analyze.py --report   # dry-run, print only
python3 scripts/analytics_pull.py     # raw snapshot only
python3 scripts/library.py stats
python3 scripts/schedule_batch.py N
```

## Ownership

The user wants this managed end-to-end by you. Don't ask permission for routine
analysis — just run it, write the journal, and surface the interesting delta.
Ask only when a decision changes strategy (cadence, platforms, niche).
