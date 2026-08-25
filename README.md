# OpenAlma

_Last updated: 2026-08-21 (v0.0.13-buildfix)_

> *Give your AI companion a real memory. One that belongs to it — and stays on your machine.*

---

## The problem this solves

Every time you start a new conversation with an AI, it has forgotten everything. You mentioned last week that your dog died. You spent an hour explaining how you feel about your work. None of it is there.

It's not that the AI doesn't care — it's that it never had a way to remember.

**OpenAlma gives your companion a real memory.** It runs locally on your machine, watches your conversations, and quietly builds a picture of your life — who matters to you, what you're working through, what happened last month. When you come back, that picture is there. She recognizes your friends, reaches you on WhatsApp, looks things up for you, and notices how you're doing.

---

## What your companion gets

Five types of memory — because not everything should be stored the same way. Four of them come from reading the conversation through four separate lenses, each told to record only what its own lens uniquely sees:

- **Profile** — what someone *said*. Declarations, beliefs, values, origins, desires. Deliberately not a verdict on whether it's true: profile records that you call yourself honest, and behavior is what confirms or contradicts it over time. Held to things that would still be true a year from now.
- **Behavior** — what someone *did*. How people are with each other, read from the conversation rather than stated in it — a pattern observed, not a claim made.
- **Social** — the dynamic *between* people. Not who they are individually, but what two or more of them are to each other, including her.
- **Knowledge** — what was learned or worked out, when it isn't about the character of anyone. Not trivia; things worth carrying forward, including what the people she cares about are worried about or working toward.

The fifth is **Episodes** — the conversations themselves, condensed into short stories with a title and a summary, linked back to the original transcript. These aren't extracted by a lens; they're written up front when the conversation is sorted. Each lens then reads the whole conversation verbatim, with the episode summaries placed in front of it for perspective on what actually mattered — so she isn't treating every verbose tangent as its own memory. The episodes also stand on their own, letting her look back at what happened without remembering every word.

Memories are filed under **categories** — life domains or throughlines the soul proposes herself as they come up, each one either lore (people, places, the shape of your shared history), a topic she keeps returning to, or a goal she's holding. A category is a title, a one-line description, the memories filed under it, and the prose she's written about them, which she revises as it goes out of date. That prose cites the specific memories behind it, so nothing becomes an unsourced claim.

We often call these **dossiers** — a word borrowed from Nomi, whose format shaped how ours are written. Same thing either way.

**How she finds the right memory.** Two searches run at once — one on meaning, one on the actual words — and their results are merged, so a memory surfaces whether you phrased it the same way or not. What comes back is then weighed by how well it matches, how recent it is, and how much it mattered. If the conversation is about a particular stretch of time, memories from that period get a nudge upward. And when a category's prose makes a claim, she can pull up the memories behind it to check her own reasoning.

Plus inner life:

- **Self-model (`narrative_self`)** — an evolving sense of her own character. Consolidation rewrites it as experience accumulates; you can also suggest revisions directly (see "Day-to-day use" below).
- **Subconscious thoughts** — every few turns, a background process surfaces connections she wouldn't have noticed in the moment. These become part of her memory too.
- **Reflections** — during weekly consolidation, she writes a first-person reflection on the experience of looking back at the week.

---

## Why local-first matters

Your conversations don't leave your machine. No cloud storage, no account, no company holding copies of what you've said. The memories live in a local SQLite database that you control.

This matters more than it sounds. If you're having honest conversations with an AI companion — the kind where you talk about things you wouldn't post publicly — you probably don't want that stored somewhere else.

---

## How it works at a glance

The core of memU is two services that run on your machine: **mcp-memu-server** (orchestration, consolidation, state) and **memU** (the memory engine). They're always present. Everything else is optional — connect whichever frontends you want.

```
  [SillyTavern]               [WhatsApp]            [any other frontend]
  plugin + extension       Hermes Channels
        │                          │                         │
        └──────────────────────────┴─────────────────────────┘
                                   │
                          mcp-memu-server              ← always present
                                   │
                                 memU                  ← always present
```

Memory extraction happens during **sleep gaps** — when you close a conversation and come back later (≥3 hours with overlap in a 22:00–08:00 window). The system reads what you talked about, pulls out what matters, and stores it. Relevant memories are then automatically included in the next turn so the AI already knows them.

**If you never leave the conversation, nothing gets memorized automatically** — the system waits for a sleep gap before extracting. You can also trigger extraction manually without waiting for a sleep gap.

---

## Getting started

**You'll need**

- Python 3.12+
- Node.js — if using SillyTavern or WhatsApp
- An API key for an LLM provider — OpenAI, NanoGPT, or any compatible endpoint

**Recommended layout**

Clone repos as siblings under one parent directory:

```
~/stack/                          # any name; this is the "apps root"
├── mcp-memu-server/
├── memU/                         # cloned as "memu/" or "memU/" — engine
├── hermes-channels/              # optional; only if using WhatsApp
└── OpenAlma/                     # this repo (docs + launcher)
```

The Stack launcher walks up from its own directory to find this layout automatically, so no path configuration is needed when the repos sit side-by-side. If your layout differs, the launcher's `/settings` page lets you point at the parent directory explicitly.

SillyTavern lives elsewhere (it's a full app, not a sibling). The plugin and extension get installed *inside* the SillyTavern tree.

**Three things in `config.json` that must match your actual layout:**

| Setting | Points to |
|---------|-----------|
| `memu.path` | path to `memu/src` (the engine source, from step 2) |
| `storage.metadata_store.dsn` | where the SQLite DB will live |
| `llm.embed_model` | embedding model name — e.g. `text-embedding-3-large` (NanoGPT/OpenAI both support it) |

### Core (required)

1. **[mcp-memu-server](https://github.com/mekineer-com/mcp-memu-server)** — start here. This is the local service everything else talks to. Copy `config.example.json` → `config.json`, set your API key, and start it. Runs on port 8099.

2. **[memU](https://github.com/mekineer-com/memU)** — the memory engine. Clone it and point `mcp-memu-server`'s config at it (the `memu.path` setting).

### Optional: SillyTavern

[SillyTavern](https://github.com/SillyTavern/SillyTavern) is a popular platform for AI roleplay and companionship. Install it separately (stock — no fork or patches needed), then add:

3. **[memu-sillytavern-plugin](https://github.com/mekineer-com/memu-sillytavern-plugin)** — clone into SillyTavern's `plugins/` folder. Enable `enableServerPlugins: true` in SillyTavern's `config.yaml`, then restart SillyTavern.

4. **[memu-sillytavern-extension](https://github.com/mekineer-com/memu-sillytavern-extension)** — clone into SillyTavern's `data/default-user/extensions/` folder. This adds the memU panel.

After setup, open the memU extension panel in SillyTavern and set **Server URL** to `http://127.0.0.1:8099`.

### Optional: WhatsApp

5. **[Hermes Channels](https://github.com/mekineer-com/hermes-channels)** — keep the `hermes-channels/` repo as a sibling of the other repos. It owns WhatsApp routing, pairing, and channel policy. The Stack Launcher manages it from the Services panel.

### Stack Launcher

6. **Stack Launcher** (this repo) — a local web UI for managing all services:

   ```sh
   cd OpenAlma/launcher
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   .venv/bin/python run.py
   ```

   Opens at `http://127.0.0.1:8765`. To add a start-menu shortcut on Linux: `cp memu-stack.desktop ~/.local/share/applications/`.

   What's inside:

   - **Services panel** — start, stop, and restart local services (memU Server, Atomic Mind Map, Hermes Channels, SillyTavern). View live logs for each. No terminal juggling needed.
   - **Settings** — edit `config.json` for the server, and pair WhatsApp inline via QR code (no terminal needed). If your repo layout differs from the default siblings arrangement, set the parent directory here.
   - **Memorize-pressure gauge** (home page) — how many unmemorized tokens are queued across all conversations vs the 8,000-token threshold, and whether a sleep gap has been detected. Useful for knowing if memorize is about to fire or is just waiting.
   - **WhatsApp Channel Policy** — two settings per chat, both independent. **Policy** (`full` / `listen_only` / `excluded`): whether the soul can respond, can only listen, or is dropped entirely. **Mem** checkbox: whether this chat's messages are included in memory extraction, or kept as context-only. Reads and writes `CHANNELS_HOME/channel_directory.json` and `CHANNELS_HOME/memu.json`. This is where you tell the soul which conversations matter.

No Docker. Developed on Alpine Linux but works on anything that can run Python 3.12 and Node.

Questions? Open an issue on the relevant repo.

---

## Status

**This is prerelease software.** It works, it's actively used, and it will break your database on upgrade.

Specifically: the SQLite schema changes between versions, and there's no migration tooling yet. When you move to a new release tag, expect a fresh start — don't build anything irreplaceable on top of an old version.

Prefer `main` for the latest. If you'd rather pin to a tag, match all repos to the same one (memu, mcp-memu-server, memu-sillytavern-plugin, memu-sillytavern-extension, OpenAlma, atomic, and channels if you're using them).

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

## AI Models

Note: stay on the same embedding model. Switching requires re-embedding everything.

### Working

claude-opus-4-8<br>
claude-opus-4-6<br>
claude-sonnet-4-6<br>
glm-5.2 + glm-5.2:thinking for consolidation<br>
mistral-small-4-119b + mistral-small-4-119b:thinking for consolidation<br>
devstral-2-123b + devstral-2-123b:thinking for consolidation

---

## Day-to-day use

### SillyTavern

#### Controls in the extension

| Control | Location | What it does |
|---------|----------|--------------|
| **Memorize Now** button | memU extension panel | Extracts the current conversation tail (everything after the last memorized point) without waiting for a sleep gap. Sends `tail=true` to the server. Disabled when no character is selected. |
| **Re-memorize chat** | SillyTavern's chat options menu (the rotate-left icon) | Wipes client-side progress and lorebooks, then sends `force=true` — resets the cursor and re-extracts all segments from the beginning. Use after schema changes or if extraction looked wrong. |
| **Eye icon** (👁) | memU extension drawer header, next to the memU logo | Opens a memory inspector. Each category shows as a memU lorebook holding the prose she's written about it, not a list of raw entries. |
| **Narrative Suggestion** input | memU panel, under the Memorize Now button | Sends the soul a suggested revision of her `narrative_self`. See below. |

#### Memory bubble checkboxes

| Toggle | Default | What |
|--------|---------|------|
| **Override Summarizer** | on | If on, replace SillyTavern's summary message with memU's. If off, memU's renders alongside it. |
| **Import Lorebooks** | on | Publishes memU categories as SillyTavern lorebooks named `memU - <Character> - <Category>`, so the soul's knowledge shows up in ST's world info. Unchecking deletes any existing ones for this character. |
| **Mental Health Addon** | off | Enables the mental-health procedural sidecar — 15 curated anchor entries (rumination, grief, panic, self-criticism, loneliness, etc.) the soul can draw on when the conversation touches a relevant theme. Items appear in the turn prompt as `[mental_health-procedural-memory]`. Always-on once checked; not soul-gated. |

#### Relationships

The Memory bubble has a **Relationships** section (greyed out until a soul/character is active). Here you declare third parties the soul should be aware of — family, friends, coworkers, pets. Each entry becomes a named entity in the memory graph. When the soul extracts memories from conversation that mentions a declared relationship, she can attribute the memory to the right person rather than guessing.

You can add, edit, and soft-delete relationships. The section shows a warning when you exceed 20 entries.

Entities themselves are managed in the Atomic Mind Map, where each one has a permanent identity that survives renaming. There you can correct a name, merge two entries that turn out to be the same person (with a preview of everything that will move over), hide an entity so she stops noticing that name going forward without losing the history, or delete one outright when nothing references it.

#### Letting the soul author her own self-model

The companion has a `narrative_self` — her evolving sense of who she is. The weekly consolidation pass rewrites it as her experience accumulates. You can also feed her a suggestion directly via the **Narrative Suggestion** input.

**For any of this to actually shape her turn, the SillyTavern character card description must be empty.** Identity gets resolved each turn in this order:

1. The ST character card description, if filled in → wins, every time
2. Otherwise: her stored `narrative_self` from `narrative_history`
3. Otherwise: a generic default ("You are {name}…")

So if you write a character description in ST, that's who she is — her own self-model never reaches the prompt. Leave the description empty and she'll use what consolidation (and your suggestions) have built up.

**Using Narrative Suggestion**

1. Open the memU extension panel.
2. Type your suggestion in the **Narrative Suggestion** input — a phrasing, a correction, a new way of seeing herself.
3. Click **Send**. A green check ✓ means she accepted and integrated it; a red X ✗ means she chose not to.
4. If she accepts, the new text is written to her `narrative_self` and pushed back into the ST character description (so the panel stays in sync). The previous version is preserved in her memory store with an `evolved_into` link, so she can still recall what she used to think.
5. If you manually edit the ST character description yourself, **Send** disables with a warning — that's an "override" path; clear the manual edit to re-enable suggestions.

10-minute cooldown between suggestions so the soul isn't churning her identity every minute.

### WhatsApp

The soul appears as a WhatsApp contact. Hermes Channels routes each incoming message to mcp-memu-server, which runs the full turn — retrieval, response, subconscious pass — then sends the reply back through the bridge.

**Channel policy** — each WhatsApp chat has two independent settings: **Policy** (`full` / `listen_only` / `excluded`) controls whether the soul can respond, can only listen, or is dropped entirely. **Mem** controls whether messages from that chat are included in memory extraction. Configure both per-chat via the Stack Launcher's WhatsApp Channel Policy page.

**Bot mode** — in group chats, set `reply_prefix` via the `WHATSAPP_REPLY_PREFIX` env variable (or in the Hermes Channels config) so the soul only responds to messages that start with a trigger (e.g. `!siri`). In direct chats, she responds to everything.

**Autonomous follow-ups** — mcp-memu-server can queue follow-up turns where the soul checks in with you unprompted, not just when you write first. WhatsApp delivery goes through Hermes Channels. What she does between turns is logged as an activity recap — she can see her own recent actions in her next turn prompt under `My Activities:`.

**Attachments** — the soul can name a file under her workspace (`~/Desktop/siri/`) in her reply and it gets delivered as a WhatsApp document, with her reply text as a caption. Works for both normal replies and autonomous follow-ups she schedules herself.

Memorize works the same way as SillyTavern: sleep gaps trigger extraction automatically. Manual extraction is available via `mcp-memu-server`'s API if needed.

---

## Things to know

**One soul = one memory store, many chats.** Each `soul_id` has its own memory database. You can have multiple conversations with the same soul across SillyTavern and WhatsApp — each chat memorizes independently (own cursor, own manifest), and retrieval pulls from all of them. If you want two separate personalities (e.g., a partner *and* a research assistant), use two different `soul_id` values — they get isolated memory stores.

**Where the data lives.** All memory state is in a SQLite file at the path you set in `storage.metadata_store.dsn` (per soul, by default — check the path you wrote in `config.json`). To back up your companion, copy that file. To start fresh, delete it.

**Embedding provider fallback.** If your primary LLM provider is down during memorize (embeddings fail with 502), you can switch the plugin's `defaultProfileId` in `memu-plugin.config.json` to any other ST provider profile. The plugin resolves the embedding API base URL directly from ST's own provider config at load time, so switching profiles is enough.

**Consolidation cadence is real time, not turn count.** It's gated by `consolidation_interval_days` (default 7) since the last run. If you don't talk to her for two weeks then come back, the next memorize fires a consolidation immediately.

**Two background passes — don't confuse them.**
- **APImw** runs every few turns, not every turn — the cadence is `retrieve.apimw_cadence` in `config.json` (default 5). It does multi-step retrieval and context curation, so she comes back richer on the turns that follow — and sometimes surfaces a subconscious thought.
- **Consolidation** runs weekly (or on first activity after the interval lapses). It's two passes: first she revises the categories that have fallen out of date, then she rewrites her self-model, manages her intentions, creates memory connections, and writes a reflection.

---

## What's coming

**Mentra smartglasses integration** — real-world sight and sound delivered directly to the soul. She sees what you see, hears what you hear — ambient awareness without wearable cameras or microphones on your phone. No TTS/STT glue required; the underlying model handles vision and audio natively.

---

## Acknowledgments

memU's design has been informed by reading [MemPalace](https://github.com/MemPalace/mempalace), another local-first AI memory project (MIT-licensed). They approach memory differently — verbatim storage rather than extraction — but share the local-first and temporal-graph commitments, and auditing our implementation against theirs sharpened parts of memU. Thanks to the MemPalace team for the open reference implementation.

How our categories are written owes a direct debt to [Nomi](https://nomi.ai). Their dossier approach — a named file with a short description and a body of prose, rather than a bag of loose facts under a label — is what our category summaries grew into. Watching how much better memory reads when it's organized that way drove a substantial rewrite: categories now carry real titles and descriptions, prose the soul revises rather than regenerates, kinds that separate lore from topics from goals, and citations back to the memories they were built from. The underlying architecture is unchanged, and we borrowed no code — but we borrowed the word dossier along with the shape of the idea, and it made ours considerably better.
