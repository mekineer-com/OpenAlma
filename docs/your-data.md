---
layout: default
title: Your data
---

# Your data

## On your machine, not in a cloud

Every memory, every reflection, every intention lives in a single SQLite database file on your computer — one file per companion, named `<Soul name>.db`. The folder is set by `storage.sqlite_dir` in the server configuration; launcher installs use `memu/sqlite/` under your apps root.

A few things live outside it: extracted segments and saved media in `storage.resources_dir` (normally `memu/resources/`), plus the original conversation sources. WhatsApp keeps its history in `hermes-channels/data/`, Iris in `openalma/mentra/`, imported chats in `openalma/imports/`, and SillyTavern in its own data folder.

There's no OpenAlma cloud sync or account. Replies and memory work send conversation text and relevant memories to your configured AI providers. Google Gemini handles embeddings; Iris also sends voice and photos to Gemini Live. Those providers' account and data policies still apply.

## What you can do with it

**Back it up**: stop the services in the launcher, then copy the whole SQLite folder somewhere safe, including `owner.txt` and any SQLite sidecar files. The owner identity belongs with the Soul databases. Copy the source folders above too if you want the conversations and media. Back up before upgrading versions — updates can change the database format.

**Start fresh**: create a new Soul in the launcher for a separate, empty memory. Deleting an existing Soul's database removes that Soul; the server will not recreate it on next use. Keep a backup rather than deleting the original to try things out.

**Move it**: with services stopped, move the SQLite folder, including its unchanged `owner.txt`, to a compatible installation and point `storage.sqlite_dir` at it. Keep the source folders too if you want the conversations and media. Don't overwrite another installation's owner or Soul databases.

## Why this matters

If you're having real conversations with an AI companion — the kind where you talk about things you wouldn't post publicly — you probably want control over that history. With OpenAlma, you control the local memory store and choose the providers that process it. Local storage doesn't mean the conversation never leaves your machine.

The tradeoff is that there's no automatic cloud backup. If your machine fails and you didn't make a backup, that history is gone. Treat it like any other important local data.
