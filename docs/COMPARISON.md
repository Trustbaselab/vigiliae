# Comparison

We compared Vigiliae with the closest open-source projects and with Grok Bots.
The goal is not to "win" a feature table. It is to state precisely where this
project is useful and where it is not.

**Method**: every GitHub number below was read from the GitHub REST API on
**2026-10-27** (`https://api.github.com/repos/<owner>/<repo>`). Star counts move;
treat them as a snapshot. Feature cells marked **not documented** mean we read
the public repository description/README on that date and did not find the
feature. It does not prove the feature is absent.

## Snapshot

| Project | Repository | Stars | Forks | License | Last push | Language |
|---|---|---:|---:|---|---|---|
| rome | [rome-os/rome](https://github.com/rome-os/rome) | **875** | 64 | MIT | 2026-10-27 | TypeScript |
| guilds | [CigaleAI/guilds](https://github.com/CigaleAI/guilds) | **65** | 7 | **AGPL-3.0** | 2026-10-26 | TypeScript |
| agenhood | [appssemble/agenhood](https://github.com/appssemble/agenhood) | **8** | 1 | MIT | 2026-10-07 | Python |
| Vigiliae | this repository | — | — | MIT | 2026-10-27 | Python |

Competitor descriptions (quoted from their repositories on 2026-10-27):

- **rome** — "A compounding agent OS for recursive agents. Also an open source
  alternative to Grok Bot and Meta's Muse."
- **guilds** — "An open-sourced alternative to Grok bots."
- **agenhood** — "Self-hosted, open-source platform for running autonomous AI
  agents 24/7 with sandboxed Docker containers, persistent memory & workspaces,
  task scheduling, workflows, and live streaming. Pluggable brains: Claude Code,
  Codex, opencode. Your server, your data."

Grok Bots (xAI) is closed source, so it has no GitHub star count. Public
reporting in October 2026 put it around **$120–300 per seat per month**;
pricing can change. Vendor page: `https://x.ai/bot` (may be geo-restricted).

## Feature matrix

| Capability | Vigiliae | Grok Bots | rome | guilds | agenhood |
|---|:---:|:---:|:---:|:---:|:---:|
| Self-hosted on your own VPS | ✅ | ❌ (vendor cloud) | ✅ | ✅ | ✅ |
| Runs after your laptop shuts down | ✅ | ✅ | ✅ | ✅ | ✅ |
| Local ↔ cloud handoff with heartbeat | ✅ | ❌ | not documented | not documented | not documented |
| Defers heavy jobs to off-peak API pricing | ✅ | ❌ | not documented | not documented | not documented |
| Boundaries in config, enforced by runtime | ✅ | ❌ | not documented | not documented | not documented |
| Zero-token rule engine for simple commands | ✅ | ❌ | not documented | not documented | not documented |
| Pluggable thinking kernel (CLI) | ✅ | ❌ | not documented | not documented | ✅ (Claude Code / Codex / opencode) |
| Sandboxed execution | ❌ | ✅ (vendor VM) | not documented | not documented | ✅ (Docker) |
| Mobile-friendly chat UI | ✅ | ✅ | not documented | not documented | not documented |
| License | MIT | proprietary | MIT | **AGPL-3.0** | MIT |

Two license notes:

- **guilds is AGPL-3.0.** If you modify it and expose it as a network service,
  the AGPL's network clause applies. That is fine for internal use but matters
  if you plan to build a closed product on top.
- **agenhood is MIT** but its execution model is Docker-per-agent; that is
  heavier than Vigiliae's single-process model, and arguably safer.

## Where Vigiliae is genuinely different

1. **Handoff is the core primitive.** Other projects assume the agent always
   lives in one place. Vigiliae treats "laptop primary / VPS takeover" as a
   first-class state machine (`/api/handover`, `exec_pref`).
2. **Cost is a scheduling input.** `heavy: true` plus a peak/off-peak clock is a
   five-line idea that most agent platforms do not model at all.
3. **The task row is the security boundary.** `write_perm`, `need_approve`, and
   `deny` are enforced outside the prompt. Prompt-only guardrails fail silently
   when the model is creative.
4. **The cheapest tier is free.** `status`, `tasks`, `runs`, `price`, `agents`,
   `inspect` never touch a model. This matters for a bot that runs 24/7.
5. **It is small on purpose.** Two external dependencies (Flask, PyYAML);
   everything else is the Python standard library. You can read it in an
   afternoon.

## Where Vigiliae is weaker

- **Maturity.** rome (875★) and guilds (65★) have more contributors and more
  time in public. Vigiliae is a single-maintainer extraction.
- **Sandbox.** agenhood runs agents in Docker containers; Vigiliae does not.
  If you run untrusted prompts or tools, use agenhood or wrap tasks yourself.
- **Agent capabilities.** rome/guilds are full agent OSes; Vigiliae deliberately
  has no planner, no tool registry, and no browser. It delegates that to the
  thinking kernel.
- **Community.** No Discord, no roadmap votes, no plugin ecosystem.
- **Breadth.** No Windows installer, no managed hosting, no team accounts.

## When to use which

| If you need… | Use |
|---|---|
| A laptop + VPS pair that hands off automatically | **Vigiliae** |
| To cut API spend on scheduled heavy jobs | **Vigiliae** |
| A config-auditable boundary model for a small team | **Vigiliae** |
| A full agent OS with UI, tools and a community | rome |
| Docker-isolated autonomous agents 24/7 | agenhood |
| A zero-cost, vendor-hosted "just works" experience | Grok Bots (paid) |

## Sources

- GitHub REST API, fetched 2026-10-27:
  - `https://api.github.com/repos/rome-os/rome` → 875 stars, 64 forks, MIT, pushed 2026-10-27
  - `https://api.github.com/repos/CigaleAI/guilds` → 65 stars, 7 forks, AGPL-3.0, pushed 2026-10-26
  - `https://api.github.com/repos/appssemble/agenhood` → 8 stars, 1 fork, MIT, pushed 2026-10-07
- Repository descriptions/READMEs, 2026-10-27.
- Grok Bots vendor page: `https://x.ai/bot` (closed source; may be geo-restricted).
