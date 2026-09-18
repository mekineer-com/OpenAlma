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

10-minute cooldown between suggestions so the soul isn't churning her identity every minute. For editing her memory directly, see [Shaping her](shaping-her.md) and the [mind map](mind-map.md).
