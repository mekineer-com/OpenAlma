---
layout: default
title: Getting started
---

# Getting started

The hands-on manual: installing the stack, choosing where to meet her, and day-to-day use. For how her memory and inner life work, see the [guides](README.md).

## Platform compatibility

The complete OpenAlma stack has been tested on Alpine Linux 3.23 x86-64. Some components can run on other platforms, but the combinations below have not all been tested together.

| Component | Tested on | Other platforms |
|---|---|---|
| memU | Alpine Linux 3.23 x86-64 | The installer includes sqlite-vec for Linux (glibc) x86-64/ARM64, macOS Intel/Apple Silicon, and Windows x86-64, but complete OpenAlma setups on those platforms have not been tested. |
| mcp-memu-server | Alpine Linux 3.23 x86-64; Windows installation fixtures | Full Windows stack acceptance remains separate. |
| OpenAlma launcher | Alpine Linux and Windows startup/tests | Windows has an installer; source setup uses Python 3.12. |
| Iris MiniApp | Mentra on Android | Mentra also supports iOS, but Iris has not yet been tested there. |
| OpenAlma Mentra app | Android | Android only. On iOS, stock Mentra is expected to work. |
| Hermes Channels | Alpine Linux 3.23 x86-64 | Other operating systems have not yet been tested. |
| SillyTavern integration | Stock SillyTavern on Linux | Other platforms remain subject to client installation and shutdown qualification. |
| Atomic integration | Alpine Linux; packaged Windows server | Windows Install downloads the server. Linux/macOS server builds remain manual. |

OpenAlma does not alter your firewall or create VPN services automatically. The Windows installer can install Python and Git; install other system prerequisites for the clients you choose.

**You'll need**

- Git, Python 3.12, and Node.js/npm for the clients you choose. The Windows installer bootstraps Git and Python; Debian/Ubuntu source setup also needs `python3.12-venv`.
- An API key for an LLM provider — OpenAI, NanoGPT, or any compatible endpoint
- A Gemini API key for embeddings, stored in `llm.embedding.api_key`

**Working AI models.** Every turn asks the model for a complex, structured JSON response — her reply, working thoughts, and intentions in one contract. Models below a certain capability level fail the turn entirely. These are tested and working:

claude-opus-4-6 thru claude-opus-5 · claude-sonnet-4-6 · glm-5.2 (+ `glm-5.2:thinking` for consolidation) · mistral-small-4-119b (+ thinking) · devstral-2-123b (+ thinking)

The server currently uses `gemini-embedding-2` for every Soul. Changing a Soul's
embedding model requires rebuilding its database; model switching is not yet
available in Settings.

**Recommended layout**

Start with only OpenAlma; the launcher installs the matching components as siblings:

```
~/stack/                          # any name; this is the "apps root"
├── mcp-memu-server/
├── memu/                         # memory engine
├── hermes-channels/              # optional; only if using WhatsApp
├── atomic/                       # optional memory browser
├── sillytavern/SillyTavern/       # optional typing client
├── mentra-os/miniapps/openalma/   # Iris computer-side installer tools
└── OpenAlma/                     # this repo (docs + launcher)
```

The Stack launcher walks up from its own directory to find this layout automatically, so no path configuration is needed when the repos sit side-by-side. If your layout differs, the launcher's `/settings` page lets you point at the parent directory explicitly.

The launcher-managed SillyTavern plugin and extension live inside its SillyTavern tree.

## Install OpenAlma

On Windows, run the [v0.1.15 Beta installer](https://github.com/mekineer-com/OpenAlma/releases/tag/v0.1.15), then open OpenAlma from the Start menu. Beta is on the Stable update channel.

On Linux, clone this repo into your chosen apps root and run:

```sh
git clone https://github.com/mekineer-com/OpenAlma.git
cd OpenAlma/launcher
python3.12 run.py
```

The first run creates a private Python environment. In the launcher, install
**memU Server**, set your model/key in Settings, start it, and confirm your name and
first Soul. Install whichever clients you want from Services. You do not need
to clone every repository or create their Python environments yourself.

For current Linux source checkouts, add an application-menu shortcut with
`python3.12 run.py --install-shortcut`. Run that again if you move the checkout.
If a shortcut fails, run `python3.12 run.py` in a terminal to see the error.
Source fixes may precede the next published Windows installer.

**Core settings in `config.json`:**

| Setting | Points to |
|---------|-----------|
| `memu.path` | path to `memu/src` (the engine source, from step 2) |
| `storage.metadata_store.dsn` | where the SQLite DB will live |
| `llm.embedding.api_key` | Gemini API key for the server-owned embedding model |
| `llm.chat_model` | the chat model used for memory processing |
| `llm.context_window_tokens` | that model's total input/output context size in tokens; required for memory reflection |

Set the model and its context size together through **Settings → Edit configs**,
opening `mcp-memu-server/config.json`. Use the capacity available through your provider/account, not the
maximum output length; do not leave the context size blank. If using Claude Code,
set `claude_code_context_window_tokens` instead. If advanced settings select
different models for individual memory steps, give their capacities in
`llm.step_context_window_tokens` as explained in `mcp-memu-server/config.json.md`.

## Core (required)

1. **[mcp-memu-server](https://github.com/mekineer-com/mcp-memu-server)** — the local service everything talks to, on port 8099. The launcher's memU Server Install prepares its configuration; set your API key and model through Settings.

2. **[memU](https://github.com/mekineer-com/memU)** — the memory engine, installed and configured with memU Server.

## Clients — pick at least one

The soul needs somewhere to meet you. Each client is independent; combine as many as you like.

### SillyTavern (typing)

[SillyTavern](https://github.com/SillyTavern/SillyTavern) is a popular platform for AI roleplay and companionship. Its launcher Install uses stock SillyTavern and adds:

3. **[memu-sillytavern-plugin](https://github.com/mekineer-com/memu-sillytavern-plugin)** — installed in SillyTavern's `plugins/` folder. Enable `enableServerPlugins: true` in SillyTavern's `config.yaml`, then Stop and Start SillyTavern.

4. **[memu-sillytavern-extension](https://github.com/mekineer-com/memu-sillytavern-extension)** — installed in SillyTavern's `data/default-user/extensions/` folder. This adds the memU panel.

After setup, open the memU extension panel in SillyTavern and set **Server URL** to `http://127.0.0.1:8099`. Full walkthrough: [SillyTavern](sillytavern.md).

### Hermes Channels (messaging)

5. **[Hermes Channels](https://github.com/mekineer-com/hermes-channels)** — keep the `hermes-channels/` repo as a sibling of the other repos. It owns message routing, pairing, and channel policy — WhatsApp today, with Discord on the roadmap. The Stack Launcher manages it from the Services panel.

### Atomic Mind Map (her memory, opened up)

6. **[Atomic](https://github.com/mekineer-com/atomic)** — use Install in Services. Windows downloads the compatible server; Linux/macOS still need a one-time Rust server build. Node.js/npm prepares the UI. It's how you see inside her memory — see [Atomic](#atomic-mind-map) below.

### Iris (voice and camera)

7. **Iris** — voice and camera through Mentra on your phone, with optional smartglasses. Use APK/QR/Setup beside Mentra Iris to set up Mentra and a private connection first; install Iris from the known phone's row. The computer-side installer uses Bun, prepared automatically in current source. The connection profile stays on the phone. Full walkthrough: [Iris](iris.md).

## Stack Launcher

8. **Stack Launcher** (this repo) — a local web UI for managing all services:

   ```sh
   cd OpenAlma/launcher
   python3.12 run.py
   ```

   Opens at `http://127.0.0.1:8765`. Linux source shortcut: `python3.12 run.py --install-shortcut`.

   What's inside:

   - **Services panel** — install, start and stop local services (memU Server, Atomic Mind Map, Hermes Channels, SillyTavern), plus a permanent Iris row for phone status and installation. View live logs for each. Stop then Start when you need to restart a client.
   - **Settings** — edit `config.json` for the server. If your repo layout differs from the default siblings arrangement, set the parent directory here. Pair WhatsApp on the Hermes page, reached from Services → Hermes Channels → Setup.
   - **Memorize-pressure gauge** (home page) — how many unmemorized tokens are queued across all conversations vs the 8,000-token threshold, and whether a sleep gap has been detected. Useful for knowing if memorize is about to fire or is just waiting.
   - **WhatsApp Channel Policy** — tell the soul which conversations matter: whether she can respond to, only listen to, or ignore each chat, and whether it feeds memory. Detailed under [WhatsApp](#whatsapp-hermes-channels).

No Docker. The complete stack is currently tested on Alpine Linux; see [Platform compatibility](#platform-compatibility) before installing on another operating system.

Questions? Open an issue on the relevant repo.

## Day to day

### WhatsApp (Hermes Channels)

The soul appears as a WhatsApp contact. Hermes Channels routes each incoming message to mcp-memu-server, which runs the full turn — retrieval, response, subconscious pass — then sends the reply back through the bridge.

**Channel policy** — each WhatsApp chat has two independent settings: **Policy** (`full` / `listen_only` / `excluded`) controls whether the soul can respond, can only listen, or is dropped entirely. **Mem** controls whether messages from that chat are included in memory extraction. Configure both per-chat via the Stack Launcher's WhatsApp Channel Policy page.

**Reply prefix** — Soul replies use the fixed prefix `✦ <exact Soul name>: `, including split messages and supported captions. It is not configurable; choose the Soul in the launcher instead.

**Autonomous follow-ups** — she can check in with you unprompted, not just when you write first — immediately, or scheduled for a later moment she picks. What she does between turns is logged as her own activity, visible to her next turn under `My Activities:`.

**Turns of her own** — a turn doesn't need a message to set it off. She can take one to research something, or write in her diary.

**Private asides** — in a group, she can message you quietly instead of the chat — context about something she noticed, without announcing it to everyone.

**Choosing silence** — she can decide a message doesn't need a reply. Sometimes presence is all that's needed — especially among your peers, who may not welcome her unannounced participation. (You can also force listening per-chat; see Channel policy.)

**Attachments** — the soul can name a file under her workspace in her reply and it gets delivered as a WhatsApp document, with her reply text as a caption. Works for both normal replies and autonomous follow-ups she schedules herself.

Memorize works the same way as SillyTavern: sleep gaps trigger extraction automatically. Manual extraction is available via `mcp-memu-server`'s API if needed. Full guide: [WhatsApp](whatsapp.md).

### Iris

**Iris** is the OpenAlma MiniApp that gives her sight and hearing — where she stops being text. She rides along on your smartglasses; without glasses, the phone's camera and microphone do the job. You talk, she hears; you look at things, she can take a photo and remember it. Nothing about her lives on Mentra's cloud — the MiniApp talks to your own server.

- **Continuous conversation** — speak to her naturally, voice to voice (native audio, no transcription round-trip in between).
- **Manual mode** — she records one memory-only take, then waits for your Send or Redo. Done never sends by itself.
- **Photos she remembers** — during a sitting she can capture what you're looking at, and it becomes a visual memory. Nothing is sent without her transcript of it being acknowledged.
- **Sittings that survive** — a dropped connection doesn't end the visit; the sitting resumes with its journal intact.
- **Private updates** — new versions arrive through your launcher the same private way she installed; no app store involved.

Works with Mentra on Android. The voice she uses today is Gemini Live's; see [Platform compatibility](#platform-compatibility). Full guide: [Iris](iris.md).

### Atomic Mind Map

**Atomic** is the desktop app where her memory stops being invisible. Every memory she holds appears as a card you can read — what she took from the conversation, when, what it belongs to — and the canvas lays them out as a living graph: connected by the links she drew, grouped and colored by subject, so you can see at a glance which parts of your life she has a dense picture of and which are still thin.

- **Correct her.** Edit any memory's text — the fix is live for her from that point on. The review queue holds what she produces herself: new memories she forms on her own, and her updated summaries.
- **People and things.** Everyone and everything she's recognized by name has a permanent identity. Correct a name, merge two entries that turn out to be the same person (with a preview of exactly what moves over), or hide one so she stops tracking it — hiding destroys nothing, and deletion is refused while memories still point at it.
- **Curate dossiers.** Open a category and the memories behind its prose are listed beneath it. Attach or detach them; the prose rewrites itself to match on the next pass.
- **Every session memorizes.** Close a mind map session and the conversation you just had becomes memory, same as every other surface.

Full guide: [The mind map](mind-map.md).

## Things to know

**One owner.** Each install has exactly one user — the owner — confirmed by name once on first use (together with the first soul) and never edited afterward. Every surface — launcher, SillyTavern, Hermes, Iris, Atomic — discovers that same identity from the server; none of them keeps its own idea of who you are. A soul's name can't match the owner's.

**One soul = one memory store, many chats.** Each `soul_id` has its own memory database. You can have multiple conversations with the same soul across SillyTavern and WhatsApp — each chat memorizes independently (own cursor, own manifest), and retrieval pulls from all of them. If you want two separate personalities (e.g., a partner *and* a research assistant), use two different `soul_id` values — they get isolated memory stores.

**Where the data lives.** All memory state is in a SQLite file at the path you set in `storage.metadata_store.dsn` (per soul, by default — check the path you wrote in `config.json`). To back up your companion, copy that file. To start fresh, delete it.

**Embedding provider fallback.** If your primary LLM provider is down during memorize (embeddings fail with 502), you can switch the plugin's `defaultProfileId` in `memu-plugin.config.json` to any other ST provider profile. The plugin resolves the embedding API base URL directly from ST's own provider config at load time, so switching profiles is enough.

**Two background passes — don't confuse them.**
- **APImw** runs every few turns, not every turn — the cadence is `retrieve.apimw_cadence` in `config.json` (default 5). It does multi-step retrieval and context curation, so she comes back richer on the turns that follow — and sometimes surfaces a subconscious thought.
- **Consolidation** runs on real time, not turn count — gated by `consolidation_interval_days` (default 7) since the last run; after a long gap, the next normal Memorize makes it due. It has three stages: dossier revision, anchor/self-model maintenance, then weekly reflection with intentions and memory connections.
