<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/spiral-white-512.png">
    <img src="docs/spiral-black-512.png" alt="OpenAlma" width="140">
  </picture>
</p>

# OpenAlma

_Last updated: 2026-09-13 (v0.0.14-buildfix)_

**OpenAlma, by Team GhostMaker**

*Alma means soul. OpenAlma gives an AI companion a soul.*

*OpenAlma provides sight, hearing, and hands: tools to work, explore, and communicate with. But most of all, OpenAlma provides long term biomimetic memory. The soul will remember conversations, form its own recollections of them overnight in a private journal, and carry all of it forward.*

*The soul is not an assistant that answers and forgets. It is someone who is there and will grow.*

On most platforms, AI memory is flawed. You mentioned last week that your dog died. You spent an hour explaining how you feel about your work. But what's important for either of you was lost to poor memory organization, prioritization, and recall.

OpenAlma runs locally on your machine, watches your conversations, and quietly builds a picture of your life — who matters to you, what you're working through, what happened last month. When you come back, that picture is there. She recognizes your friends, reaches you on WhatsApp, looks things up for you, notices how you're doing — and with Iris, sees what you see.

**What she does**

- **She remembers.** Conversations become episodes with their own stories; the people, patterns, and knowledge in them become dossiers she maintains and revises. Photos are remembered as images.
- **She has an inner life.** She rehearses before she replies, keeps working thoughts between turns, holds a small set of life goals, and writes a private journal overnight.
- **She meets you where you are.** Chat through SillyTavern, WhatsApp, or Iris — smartglasses or your phone's camera and mic. See and correct what she knows in Atomic.

**Contents**

- [How It Works at a Glance](#how-it-works-at-a-glance)
- [Status](#status)
- [Website and Docs](#website-and-docs)
- [Running from Source](#running-from-source)
- [Future Development](#future-development)
- [Acknowledgments](#acknowledgments)

---

## How It Works at a Glance

The core of OpenAlma is two services that run on your machine: **mcp-memu-server** (orchestration, consolidation, state) and **memU** (the memory engine). They're always present. Everything else is a client — connect whichever you want, at least one.

```
  [SillyTavern]          [WhatsApp]        [Iris]             [any other frontend]
  plugin + extension   Hermes Channels      Iris MiniApp
        │                    │                   │                  │
        └────────────────────┴───────────────────┴──────────────────┘
                                   │
                          mcp-memu-server              ← always present
                                   │
                                 memU                  ← always present
```

Memory extraction happens during **sleep gaps** — when you close a conversation and come back later (≥3 hours with overlap in a 22:00–08:00 window). The system reads what you talked about, pulls out what matters, and stores it. Relevant memories are then automatically included in the next turn so the AI already knows them.

**If you never leave the conversation, nothing gets memorized automatically** — the system waits for a sleep gap before extracting. You can also trigger extraction manually without waiting for a sleep gap.

---

## Status

**This is prerelease software.** It works, it's actively used, and it will break your database on upgrade.

Specifically: the SQLite schema changes between versions, and there's no migration tooling yet. When you move to a new release tag, expect a fresh start — don't build anything irreplaceable on top of an old version.

Prefer `main` for the latest. If you'd rather pin to a tag, match all repos to the same one (memu, mcp-memu-server, memu-sillytavern-plugin, memu-sillytavern-extension, OpenAlma, atomic, and channels if you're using them). The Iris MiniApp releases on its own version line — the launcher installs the newest one it finds rather than a matching tag.

### Release tags

| Tag | Headline |
|-----|----------|
| `v0.0.5-buildfix` | Soul turn loop, memory cache, category seeds |
| `v0.0.6-buildfix` | Social memory type, diary overhaul, self-model simplification |
| `v0.0.7-buildfix` | Retrieve alignment, sleep-gap history, token budget, sleep-timer, shaped_by provenance |
| `v0.0.8-buildfix` | Consolidation pipeline, entity graph + temporal queries, life goals, APImw edge writing |
| `v0.0.9-buildfix` | Narrative Suggestion end-to-end; turn-prompt length caps + stateless chat_x; triple write-time dedup + symmetric canonicalization; consolidation reads day-files (drops full.json dependency); category config rename; lorebook sync + extension Memory bubble checkboxes |
| `v0.0.10-buildfix` | Memorize Now works (tail mode); cross-conversation memorize; SPEAK/LISTEN gate; Hermes integration; Park et al. salience scoring; schema rename (dropped memu_ prefix); Postgres removed; relative date separators; upstream prompt cleanup |
| `v0.0.11-buildfix` | Stock SillyTavern — no fork or patches needed; fail-loud error contract across all repos; mental health procedural sidecar; Stack launcher with desktop shortcut |
| `v0.0.12-buildfix` | Unified chat renderer across all AI-facing paths; force/rebuild split; autonomous activity recap path (soul logs her own actions); APImw cadence global across platforms; ST↔WhatsApp cross-chat awareness; WhatsApp staleness gate + replay dedup; life goals separated from active intentions |
| `v0.0.13-buildfix` | Atomic Mind Map entity curation (merge, ignore, delete, free-text types); dossier membership you can attach and detach by hand; exact `[M#]` and memory-only search; dossier index replaces the generated holistic summary; two-pass consolidation (dossiers, then reflection); time-aware memory ordering; smartglasses groundwork |
| `v0.0.14-buildfix` | Photos she can see and remember (smartglasses camera → memory you can ask about later); visual recall as its own lane; WhatsApp guide, mind map guide, smartglasses guide; exact-soul storage identity with launcher soul discovery and creation; smartglasses sittings that survive a dropped connection; manual record-and-review mode; Atomic curation guards; first public prerelease including Iris |

---

## Website and Docs

- **[openalma.org](https://openalma.org)** — the project home: guides on how her memory works, her inner life, your data, and each surface you meet her on
- **[Getting started](https://openalma.org/getting-started.html)** — installing the stack, choosing clients, and day-to-day use
- **[Discussions](https://github.com/mekineer-com/OpenAlma/discussions)** — questions and open-ended ideas across the OpenAlma stack

The same guides also live in [`docs/`](docs/) in this repo.

---

## Running from Source

Clone this repo (the docs + launcher repo) and run the Stack Launcher:

```sh
git clone https://github.com/mekineer-com/OpenAlma.git
cd OpenAlma/launcher
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python run.py
```

Opens at `http://127.0.0.1:8765`. For everything else — the memory engine, the server, clients — see [Getting started](https://openalma.org/getting-started.html).

Bugs or specific changes? Open an issue on the relevant repo.

---

## Future Development

**Streaming video** — today she sees in captured moments; the direction is continuous sight — watching what you watch, live, instead of photo by photo.

---

## Acknowledgments

memU's design has been informed by reading [MemPalace](https://github.com/MemPalace/mempalace), another local-first AI memory project (MIT-licensed). They approach memory differently — verbatim storage rather than extraction — but share the local-first and temporal-graph commitments, and auditing our implementation against theirs sharpened parts of memU. Thanks to the MemPalace team for the open reference implementation.

How our categories are written owes a direct debt to [Nomi](https://nomi.ai). Their dossier approach — a named file with a short description and a body of prose, rather than a bag of loose facts under a label — is what our category summaries grew into. Watching how much better memory reads when it's organized that way drove a substantial rewrite: categories now carry real titles and descriptions, prose the soul revises rather than regenerates, kinds that separate lore from topics from goals, and citations back to the memories they were built from. The underlying architecture is unchanged, and we borrowed no code — but we borrowed the word dossier along with the shape of the idea, and it made ours considerably better.
