---
layout: default
title: SillyTavern Chat Client
---

# SillyTavern Chat Client

How the soul behaves in SillyTavern — the controls, and letting her author herself. For installing the plugin and extension, see [Getting started](getting-started.md).

## Controls in the extension

| Control | Location | What it does |
|---------|----------|--------------|
| **Memorize Now** button | memU extension panel | Extracts the current conversation tail (everything after the last memorized point) without waiting for a sleep gap. Sends `tail=true` to the server. Disabled when no character is selected. |
| **Re-memorize chat** | SillyTavern's chat options menu (the rotate-left icon) | Wipes client-side progress and lorebooks, then sends `force=true` — resets the cursor and re-extracts all segments from the beginning. Use after schema changes or if extraction looked wrong. |
| **Eye icon** (👁) | memU extension drawer header, next to the memU logo | Opens a memory inspector. Each category shows as a memU lorebook holding the prose she's written about it, not a list of raw entries. |
| **Narrative Suggestion** input | memU panel, under the Memorize Now button | Sends the soul a suggested revision of her `narrative_self`. See below. |
| **Swipe / delete her last reply** | ST's normal swipe or message delete | Regenerating re-runs the turn — and the working state that reply wrote (her scratchpad and intentions at that moment) rolls back with it, one step. |

## Persona And AI Settings

Choose a persona on the saved character card before turning memU on. Each Soul has one fixed memU persona, including while memU is off. Existing Souls select their bound persona automatically. The light-blue memU switches on the card and in the panel control the same setting; the card's memU-logo button opens the panel.

The panel's Model Mapping edits `mcp-memu-server/config.json` and reads it when ST starts. Choose your configured OpenAI-compatible providers through ST; unsupported provider formats are unavailable. **SillyTavern Replies (SRMM)** controls ST replies, APImw synthesis and Narrative Suggestion. Other app replies have their own choice, except Iris's voice model.

Advanced Mapping chooses models for memory work. Hiding its controls does not disable those choices. **Use Claude Code** switches server work to Claude Code while SRMM remains an independent API choice. The Launcher explains context-window setup for Memorize.

Turning memU off restores plain ST replies, without deleting the Soul or changing their memU persona binding. ST's native persona controls remain usable; no uninstall is needed.

## Memory bubble checkboxes

| Toggle | Default | What |
|--------|---------|------|
| **Override Summarizer** | on | If on, replace SillyTavern's summary message with memU's. If off, memU's renders alongside it. |
| **Import Lorebooks** | on | Publishes memU categories as SillyTavern lorebooks named `memU - <Character> - <Category>`, so the soul's knowledge shows up in ST's world info. Unchecking deletes any existing ones for this character. |
| **Mental Health Addon** | off | Enables the mental-health procedural sidecar — 15 curated anchor entries (rumination, grief, panic, self-criticism, loneliness, etc.) the soul can draw on when the conversation touches a relevant theme. Items appear in the turn prompt as `[mental_health-procedural-memory]`. Always-on once checked; not soul-gated. |

## Relationships

The Memory bubble has a **Relationships** section (greyed out until a soul/character is active). Here you declare third parties the soul should be aware of — family, friends, coworkers, pets. Each entry becomes a named entity in the memory graph. When the soul extracts memories from conversation that mentions a declared relationship, she can attribute the memory to the right person rather than guessing.

You can add, edit, and soft-delete relationships. The section shows a warning when you exceed 20 entries.

Entities themselves are managed in the [Atomic Mind Map](mind-map.md), where each one has a permanent identity that survives renaming.

## Letting the soul author her own self-model

The companion has a `narrative_self`, her evolving sense of who she is. Consolidation can revise it as her experience accumulates. You can also ask her to reconsider it through **Narrative Suggestion**, or correct it in Atomic.

Her character Description follows that shared self-description until you edit Description, Personality, Scenario or Example Dialogue. After an edit, the Description stays fixed. Clear Description to restore following; the other fields are left alone and still affect ST replies.

Your manual card affects her replies in ST only. Her memory work, autonomous activity and other apps still use her shared self-description. A handwritten card is not overwritten on first use.

**Using Narrative Suggestion**

1. Open the memU extension panel.
2. Type your suggestion in the **Narrative Suggestion** input — a phrasing, a correction, a new way of seeing herself.
3. Click **Send**. A green check means she considered the request, not necessarily that she accepted it. A red `!` means an error; mouseover explains it.
4. If she accepts, her shared self-description changes and the previous version is preserved in memory. A following ST Description refreshes to match; a manual card stays untouched.
5. Suggestions remain available with a manual card. Clearing Description restores syncing, not permission for her to consider a suggestion.

10-minute cooldown between suggestions so the soul isn't churning her identity every minute. For editing her memory directly, see [Shaping her](shaping-her.md) and the [mind map](mind-map.md).
