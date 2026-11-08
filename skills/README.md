# Skills

Vigiliae ships with four reusable Agent Skills that encode what we learned
building and operating a multi-agent fleet.

These are plain `SKILL.md` files following the open Agent Skills convention.
They contain **method and judgement rules only — no data**. Anything that needs
data goes through an MCP server or your own tooling.

| Skill | What it solves |
|---|---|
| [`decision-loop`](decision-loop/SKILL.md) | Your product delivers conclusions but not action. Six-stage loop (semantic layer → data → models → **action** → compliance → reuse) that shows which stage you are stuck at, and how to close the loop. |
| [`agent-fleet-ops`](agent-fleet-ops/SKILL.md) | Your agents have been running for a few days and something is off: runs stuck in `running`, counters that disagree with the database, quota exhausted but recorded as failures, agents that run constantly yet produce nothing. |
| [`domain-master`](domain-master/SKILL.md) | You want one agent a user can talk to and finish a real professional task — not another background worker. Covers business objects, relations, trusted sources, judgement rules, and evaluation sets. |
| [`verifiable-data`](verifiable-data/SKILL.md) | Someone asked "why should anyone trust your data". Covers A–E confidence, `source_url` + verbatim `quote` dual proof, the A1/A2 split, and fingerprint anchoring. |

## Why these four

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

## Using them

Copy any directory into your agent's skills folder:

```
cp -r skills/agent-fleet-ops ~/.your-agent/skills/
```

Or read `SKILL.md` directly and paste the rules into your system prompt — they
are written to be readable on their own.

## Honest limits

- These are methods, not implementations. They will not run anything for you.
- `verifiable-data` and `agent-fleet-ops` contain no data and no thresholds that
  depend on a specific system; adapt the numbers to yours.
- `domain-master` requires a real domain expert to confirm the evaluation set.
  A model cannot grade itself.
- Nothing here is legal or regulatory advice.
