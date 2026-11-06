# 名字的故事 · The Name> 更柝 / Vigiliae 的名字不是随便起的。> 两个文明，相隔万里，从未交流，却各自独立发明了同一种制度。---
### Vigiliae · the Roman night watch

In the Roman Empire, the night was not a single stretch of darkness. It was
**divided into four watches** — *vigiliae* — each roughly three hours long.
Every watch was held by a different cohort of the **vigiles**, the night
watchmen of Rome. At the end of each shift the outgoing watch formally handed
the city over to the incoming one. No hour of the night was ever unwatched.

The institution was not informal. Augustus established the *vigiles* as a
standing corps of seven cohorts around 6 BC, tasked with firefighting and
night policing across the fourteen regions of Rome. Their duties, their
subordination, and their liability were codified in law: **book 1, title 15 of
the *Digesta***, *De officio praefecti vigilum* — "On the office of the prefect
of the watch." A Roman jurist could tell you, 2,000 years ago, exactly who was
responsible for the city between the third and fourth watch.

The word survives in modern languages: *vigil*, *vigilance*, *vigilante*, the
Spanish *vigilia*, the Italian *veglia*. All of them mean the same thing —
**someone is staying awake so that you can sleep.**

### 更柝 · the Chinese watch of the fifth night

Classical China solved the same problem with the same architecture, without
ever seeing Rome.

The night was divided into **five watches** — *更* — beginning at dusk and
ending at dawn. At each watch a watchman walked the streets striking a wooden
clapper called a **柝**. The sound was the signal: *the watch is being kept, the
hour has turned, all is well.* The practice gave Chinese its most common idiom
for the middle of the night — **三更半夜**, "the third watch, the middle of the
night."

The image is old enough to appear in the **I Ching** (系辞下), in a passage
about how a ruler secures a city:

> **重门击柝，以待暴客**
> *Double gates and the clapper, to await the night intruder.*

It returns in the **Ballad of Mulan**, in the famous couplet describing a
soldier's night on campaign:

> **朔气传金柝，寒光照铁衣**
> *The northern air carries the brazen clapper; the cold light falls on
> iron armour.*

And the administrative machinery appears in the **Rites of Zhou** (周礼·夏官),
where an officer called the *Qi Hu Shi* kept the water-clock and ordered the
clapper to be struck, and later in the **Tang Code** (唐六典), which recorded
the terms **上直** ("taking up the watch") and **下直** ("coming off the
watch") for officials on night duty. The handoff was a matter of law, not
courtesy.

### Two civilisations, one invention

Neither tradition borrowed from the other. Rome and China were separated by
thousands of miles and had no contact. Yet both arrived at the identical
solution:

> **Divide the night into shifts, and hand each shift to the next,
> so that someone is always awake.**

That is the entire mechanism of this project. A local agent and a cloud agent
hold the watch in turn. When the laptop closes, the cloud takes over. When it
opens again, the cloud hands back. Between them, the work never stops.

We did not name it after a robot. We named it after the watch.

### Why this matters for what we build

The *vigiles* were not merely people who stayed up. They were a **system** —
with divisions, schedules, handoff procedures, jurisdictions, equipment
standards, and legal accountability. The value was never that one person was
awake. The value was that the *institution* guaranteed continuity regardless of
which individual was on duty.

That is exactly the design problem we are solving. The hard part of an AI agent
is not making it run once. The hard part is making it run **tomorrow at 3 a.m.,
after you have gone home, with the same boundaries, the same audit trail, and
the same standards** — and then handing control back to you cleanly when you
return.

Vigiliae is that institution, written as software. The name is a reminder of
what we are actually building: not a chatbot, not a model — a **watch that does
not break.**

---

> **Honest status**: early stage, used in production by Trustbase Lab on a single
> 4-core / 7.5 GB VPS since October 2026. One maintainer. Not a hardened
> multi-tenant platform. No formal test suite yet. If you need a polished agent
> OS, look at the projects in the [comparison](docs/COMPARISON.md) first.

```
 local agent (laptop)  ──heartbeat──▶  Vigiliae (VPS)  ──▶  scheduled agents
        ▲                                   │
        └────────── chat / task bus ◀───────┘
```

---
