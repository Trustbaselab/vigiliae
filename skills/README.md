# Skills

Vigiliae ships with six reusable Agent Skills that encode what we learned
building and operating a multi-agent fleet.

These are plain `SKILL.md` files following the open Agent Skills convention.
They contain **method and judgement rules only — no data**. Anything that needs
data goes through an MCP server or your own tooling.

| Skill | What it solves |
|---|---|
| [`decision-loop`](decision-loop/SKILL.md) | Your product delivers conclusions but not action. Six-stage loop (semantic layer → data → models → **action** → compliance → reuse) that shows which stage you are stuck at, and how to close the loop. |
| [`domain-master`](domain-master/SKILL.md) | You want one agent a user can talk to and finish a real professional task — not another background worker. Covers business objects, relations, trusted sources, judgement rules, and evaluation sets. |
| [`verifiable-data`](verifiable-data/SKILL.md) | Someone asked "why should anyone trust your data". Covers A–E confidence, `source_url` + verbatim `quote` dual proof, the A1/A2 split, and fingerprint anchoring. |
| [`agent-fleet-ops`](agent-fleet-ops/SKILL.md) | Your agents have been running for a few days and something is off: runs stuck in `running`, counters that disagree with the database, quota exhausted but recorded as failures, agents that run constantly yet produce nothing. |
| [`agent-cost-accounting`](agent-cost-accounting/SKILL.md) | You pay for API calls but cannot see who spent what. Balance-delta accounting when the framework exposes no token counts, plus per-agent allocation, cost normalisation, and budget guards. |
| [`agent-efficiency-audit`](agent-efficiency-audit/SKILL.md) | An agent spent 10x what it should have. Or: which of these agents is actually worth its cost. Expected-vs-actual cost, cost per unit of output, idle-agent detection, and keep/kill decisions. |

## The three layers

They answer three different questions, in order:

```
Is it running?      → agent-fleet-ops          (status, stuck runs, counters)
What does it cost?  → agent-cost-accounting    (balance delta, allocation)
Is it worth it?     → agent-efficiency-audit   (unit cost, idle, ROI)
```

`agent-fleet-ops` alone is not enough. An agent can be perfectly healthy —
`status: ok`, no stuck runs, counters correct — and still be a waste of money
because its output is an empty shell. You need all three.

## Why these six

They are not generic prompt packs. Each one is the compressed output of a
specific failure we hit in production:

- `agent-fleet-ops` came from finding nine runs stuck in `running` for up to
  36 hours because a watchdog existed but was never called.
- `verifiable-data` came from discovering that 86% of our "A-grade" records were
  free public macro statistics, and having to disclose that honestly.
- `decision-loop` came from realising we were a data supplier, not a decision
  service — our conclusions never became actions.
- `domain-master` came from noticing all twelve of our agents were back-office
  workers that no user could talk to.
- `agent-cost-accounting` came from having no token metering at all, and having
  to reconstruct real spend from the account balance alone.
- `agent-efficiency-audit` came from the question our own operator asked:
  *"if a task should cost 10 and it costs 100, something is wrong — how do we
  catch that?"*

## Using them

Copy any directory into your agent's skills folder:

```
cp -r skills/agent-fleet-ops ~/.your-agent/skills/
```

Or read `SKILL.md` directly and paste the rules into your system prompt — they
are written to be readable on their own.

## Honest limits

- These are methods, not implementations. They will not run anything for you.
- `verifiable-data`, `agent-fleet-ops` and `agent-cost-accounting` contain no
  data and no thresholds that depend on a specific system; calibrate the numbers
  against your own measurements. A baseline must be measured, never guessed.
- `domain-master` requires a real domain expert to confirm the evaluation set.
  A model cannot grade itself.
- Cost figures from balance-delta accounting are approximations. Do not use them
  as financial records.
- Nothing here is legal or regulatory advice.
