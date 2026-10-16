---
layout: default
title: Iris Video Chat
---

# Iris Video Chat

Iris is her vision and hearing — voice through Mentra, with photos from your phone's camera or gallery.

> Included in the OpenAlma Beta.

## Talking to her out loud

Everything else here happens through typing. Iris gives her your voice through Mentra, with optional smartglasses, and photos from your phone — and it counts as the same relationship rather than a separate voice assistant that forgets you.

That last part is the whole point. What you say out loud goes into the same memory as everything else. She recalls it later in a text conversation; she recalls a text conversation while you're out walking.

## Two ways to talk

**Continuous** is a conversation. You talk, she answers, you talk again. She works out when you've stopped speaking on her own.

**Manual** is one take at a time, up to two minutes. Tap Talk, then Done, then choose Send or Redo. There's no playback; nothing goes to her until you choose Send. It's the better mode when the surroundings are loud, or when what you want to say takes a couple of tries to get right.

## Photos

You can take a photo with your phone or choose one from its gallery during a sitting. She looks at it and quietly describes what she wants to remember. Turn on **Speak photo descriptions** in Iris settings if you want to hear her describe it.

Each photo is remembered two ways: a description of what it shows, and a stored impression of the image itself that search can match against directly. Ask about something you saw and she searches both — a photo can surface even when its description never used the words you asked with. If a photo fails to reach her, it stays pending rather than disappearing; during a sitting you can retry or discard it.

Camera images are where Iris starts; live video is where she's heading.

## Looking things up mid-conversation

While you're speaking she can go search her own memory and come back with what she found, without the conversation stopping to wait. You keep talking; the answer arrives when it arrives. She can also check her working thoughts and intentions mid-sitting, save a thought, or close out an intention that's done.

## A sitting

One stretch of talking is a sitting. Voice connects from your phone to Gemini Live; your server keeps the transcript. Iris can reconnect after a short drop, while the server's 90-second lease remains valid. A reply in progress may be cut off, and longer outages end the sitting.

When you press Stop after at least two completed exchanges, she may say one or two sentences about how the conversation felt, and that is saved too. A disconnect or stopping mid-turn skips this reflection.

## Honest limitations

Voice and photos go to Google's Gemini Live, so Iris needs internet access and `mentra.gemini_api_key` configured on the server. Photo memory also needs the embedding key in `llm.embedding.api_key`. Recognition is imperfect in noise. And it's the newest part of the system by a wide margin — expect rough edges that the typed paths don't have. For the private phone-to-server connection, see [Mentra setup](mentra.md#connection).
