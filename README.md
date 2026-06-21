# memU Local Stack

_Last updated: 2026-06-20 (v0.0.12-buildfix)_

> *Give your AI companion a real memory. One that belongs to it — and stays on your machine.*

---

## The problem this solves

Every time you start a new conversation with an AI, it has forgotten everything. You mentioned last week that your dog died. You spent an hour explaining how you feel about your work. None of it is there.

It's not that the AI doesn't care — it's that it never had a way to remember.

**memU is a memory system for AI companions.** It runs locally on your machine, watches your conversations, and quietly builds a picture of who you are and what you've been through together. When you come back, that picture is there.

---

## What your companion gets

Four kinds of memory — because not everything should be stored the same way:

- **Profile** — who you are as a person. Your values, your fears, your sense of humor, what you keep coming back to. The things that would still be true about you a year from now.
- **Knowledge** — things you've learned or explored together. Not trivia — things where the topic actually connects to your life.
- **Behavior** — how you communicate. Whether you joke when things get heavy, whether you go quiet before saying something important. Patterns that are distinctly *you*.
- **Social** — the people in your life. Friends, family, coworkers, anyone you talk about. The relationship context that gives your conversations texture.

Episodes — the conversations themselves — are also stored as condensed summaries linked to the original transcript, so the soul can look back at what happened without needing to remember every word.

Plus inner life:

- **Self-model (`narrative_self`)** — an evolving sense of her own character. Consolidation rewrites it as experience accumulates; you can also suggest revisions directly (see "Day-to-day use" below).
- **Subconscious thoughts** — between turns, a background process surfaces connections she wouldn't have noticed in the moment. These become part of her memory too.
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
  plugin + extension       hermes-agent
                             └─ whatsapp-bridge
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
├── hermes-agent/                 # optional; only if using WhatsApp
└── memu-local-stack/             # this repo (docs + launcher)
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

5. **[hermes-agent](https://github.com/mekineer-com/hermes-agent)** — clone as a sibling of the other repos. The WhatsApp bridge (`scripts/whatsapp-bridge/`) is bundled inside it. Hermes also supports an autonomous soul loop — the soul can initiate contact, not just respond. The Stack Launcher manages both from its Services panel.

### Stack Launcher

6. **Stack Launcher** (this repo) — a local web UI for managing all services:

   ```sh
   cd memu-local-stack/launcher
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   .venv/bin/python run.py
   ```

   Opens at `http://127.0.0.1:8765`. To add a start-menu shortcut on Linux: `cp memu-stack.desktop ~/.local/share/applications/`.

   What's inside:

   - **Services panel** — start, stop, and restart any service (mcp-memu-server, memU, SillyTavern, Hermes, WhatsApp bridge). View live logs for each. No terminal juggling needed.
   - **Settings** — edit `config.json` for the server, and `~/.hermes/config.yaml` for Hermes. If your repo layout differs from the default siblings arrangement, set the parent directory here.
   - **Memorize-pressure gauge** (home page) — how many unmemorized tokens are queued across all conversations vs the 8,000-token threshold, and whether a sleep gap has been detected. Useful for knowing if memorize is about to fire or is just waiting.
   - **WhatsApp Channel Policy** — configure how each WhatsApp chat is handled: `full` — soul can choose to respond or listen. `listen_only` — soul can only listen. `excluded` — Hermes drops the message entirely. Reads and writes `~/.hermes/channel_directory.json` and `~/.hermes/memu.json`. This is where you tell the soul which conversations matter.

No Docker. Developed on Alpine Linux but works on anything that can run Python 3.12 and Node.

Questions? Open an issue on the relevant repo.

---

## Status

**This is prerelease software.** It works, it's actively used, and it will break your database on upgrade.

Specifically: the SQLite schema changes between versions, and there's no migration tooling yet. When you move to a new release tag, expect a fresh start — don't build anything irreplaceable on top of an old version.

Prefer `main` for the latest. If you'd rather pin to a tag, match all repos to the same one (memu, mcp-memu-server, memu-sillytavern-plugin, memu-sillytavern-extension, memu-local-stack, and hermes-agent if you're using it).

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

---

## Day-to-day use

### SillyTavern

#### Controls in the extension

| Control | Location | What it does |
|---------|----------|--------------|
| **Memorize Now** button | memU extension panel | Extracts the current conversation tail (everything after the last memorized point) without waiting for a sleep gap. Sends `tail=true` to the server. Disabled when no character is selected. |
| **Re-memorize chat** | SillyTavern's chat options menu (the rotate-left icon) | Wipes client-side progress and lorebooks, then sends `force=true` — resets the cursor and re-extracts all segments from the beginning. Use after schema changes or if extraction looked wrong. |
| **Eye icon** (👁) | memU extension drawer header, next to the memU logo | Opens a memory inspector. Categories show as memU lorebooks, each containing the items the soul has stored under that category. |
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

The soul appears as a WhatsApp contact. Hermes routes each incoming message to mcp-memu-server, which runs the full turn — retrieval, response, subconscious pass — then sends the reply back through the bridge.

**Channel policy** — each WhatsApp chat can be set to `full` (soul can choose to respond or listen), `listen_only` (soul can only listen), or `excluded` (Hermes drops the message entirely). Configure per-chat via the Stack Launcher's WhatsApp Channel Policy page.

**Bot mode** — in group chats, set `reply_prefix` in `~/.hermes/config.yaml` so the soul only responds to messages that start with a trigger (e.g. `!siri`). In direct chats, she responds to everything.

**Autonomous loop** — Hermes can run a timed loop where the soul checks in with you unprompted, not just when you write first. Configured via `~/.hermes/config.yaml`. What she does between turns is logged as an activity recap — she can see her own recent actions in her next turn prompt under `My Activities:`.

**Attachments** — the soul can name a file under her workspace (`~/Desktop/siri/`) in her reply and it gets delivered as a WhatsApp document, with her reply text as a caption. Works for both normal replies and autonomous follow-ups she schedules herself.

Memorize works the same way as SillyTavern: sleep gaps trigger extraction automatically. Manual extraction is available via `mcp-memu-server`'s API if needed.

---

## Things to know

**One soul = one memory store, many chats.** Each `soul_id` has its own memory database. You can have multiple conversations with the same soul across SillyTavern and WhatsApp — each chat memorizes independently (own cursor, own manifest), and retrieval pulls from all of them. If you want two separate personalities (e.g., a partner *and* a research assistant), use two different `soul_id` values — they get isolated memory stores.

**Where the data lives.** All memory state is in a SQLite file at the path you set in `storage.metadata_store.dsn` (per soul, by default — check the path you wrote in `config.json`). To back up your companion, copy that file. To start fresh, delete it.

**Embedding provider fallback.** If your primary LLM provider is down during memorize (embeddings fail with 502), you can switch the plugin's `defaultProfileId` in `memu-plugin.config.json` to any other ST provider profile. The plugin resolves the embedding API base URL directly from ST's own provider config at load time, so switching profiles is enough.

**This costs money to run.** Every turn calls your LLM provider (the soul's response). Every memorize calls it several more times (router + extraction per applicable type, plus optional category clustering). Consolidation calls it weekly, plus a per-episode background retrieval. APImw runs a couple of background calls after each turn. With a budget provider like NanoGPT this stays cheap, but it isn't free — assume real API spend.

**Consolidation cadence is real time, not turn count.** It's gated by `consolidation_interval_days` (default 7) since the last run. If you don't talk to her for two weeks then come back, the next memorize fires a consolidation immediately.

**Two background passes — don't confuse them.**
- **APImw** runs after each turn (multi-step retrieval + context curation). She comes back richer the next turn — and sometimes surfaces a subconscious thought.
- **Consolidation** runs weekly (or on first activity after the interval lapses). She rewrites her self-model, manages her intentions, creates memory connections, and writes a reflection.

---

## What's coming

**Mentra smartglasses integration** — real-world sight and sound delivered directly to the soul. She sees what you see, hears what you hear — ambient awareness without wearable cameras or microphones on your phone. No TTS/STT glue required; the underlying model handles vision and audio natively.

---

## Acknowledgments

memU's design has been informed by reading [MemPalace](https://github.com/MemPalace/mempalace), another local-first AI memory project (MIT-licensed). They approach memory differently — verbatim storage rather than extraction — but share the local-first and temporal-graph commitments, and auditing our implementation against theirs sharpened parts of memU. Thanks to the MemPalace team for the open reference implementation.
