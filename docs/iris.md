---
layout: default
title: Iris Video Chat
---

# Iris Video Chat

Iris is her vision and hearing — voice through Mentra, with photos from your phone's camera or gallery, and a live camera view in Video calls.

> Included in the OpenAlma Beta.

## Talking to her out loud

Everything else here happens through typing. Iris gives her your voice through Mentra, with optional smartglasses, and photos from your phone — and it counts as the same relationship rather than a separate voice assistant that forgets you.

That last part is the whole point. What you say out loud goes into the same memory as everything else. She recalls it later in a text conversation; she recalls a text conversation while you're out walking.

## Starting a call

Choose a Soul, then start an **Audio** call (talk out loud) or a **Video** call (she also watches through the phone's camera). The **Thinking** switch above the call buttons picks her voice model: Gemini 3.8 Live, or its extended-thinking variant. Your choice is saved on your OpenAlma server and stays fixed for the whole call.

## Two ways to talk

**Continuous** is a conversation. You talk, she answers, you talk again. She works out when you've stopped speaking on her own.

**Manual** is one take at a time, up to two minutes. Tap Talk, then Done, then choose Send or Redo. There's no playback; nothing goes to her until you choose Send. It's the better mode when the surroundings are loud, or when what you want to say takes a couple of tries to get right.

## Photos

You can take a photo with your phone or choose one from its gallery during a sitting. She looks at it and quietly describes what she wants to remember. Turn on **Speak photo descriptions** in Iris settings if you want to hear her describe it.

Each photo is remembered two ways: a description of what it shows, and a stored impression of the image itself that search can match against directly. Ask about something you saw and she searches both — a photo can surface even when its description never used the words you asked with.

Expand **Photo captions** to see the last five captions she wrote. A green check means your server accepted that caption for filing as a memory. If a photo never reached her, it stays on the phone rather than disappearing; start Iris again to retry or discard it. If filing fails on the server, Iris lists it with **Retry** and **Discard**, even after you reopen the app.

## Video calls

In a Video call she sees the phone camera's current view every couple of seconds while you talk, so she can talk about what is in front of you. Every so often she is offered a few recent frames and may keep some as photo memories. **Maximum memorized photos** in Iris settings caps how many she keeps: one to five in the first five minutes, then the allowance grows more slowly (twice that by 15 minutes, three times by 45); photos you take on purpose don't count against it. The camera only runs while Iris is on screen.

## Looking things up mid-conversation

While you're speaking she can go search her own memory and come back with what she found, without the conversation stopping to wait. You keep talking; the answer arrives when it arrives. She can also check her working thoughts and intentions mid-sitting, save a thought, or close out an intention that's done.

## A sitting

One stretch of talking is a sitting. Voice connects from your phone to Gemini Live; your server keeps the transcript. Iris can reconnect after a short drop, while the server's 90-second lease remains valid. A reply in progress may be cut off, and longer outages end the sitting.

With **Closing thoughts** checked (it is by default), pressing Stop after at least two completed exchanges gives her a moment to say one or two sentences about how the conversation felt, and that is saved too. A short countdown shows while she finishes. A disconnect or stopping mid-turn skips this reflection.

If Iris can't reach your server, it asks "Is memU running?" and offers **Retry Connection** and **Edit Connection**, so you can fix the address without losing your Soul choice.

## Honest limitations

Voice and photos go to Google's Gemini Live, so Iris needs internet access and `mentra.gemini_api_key` configured on the server. Photo memory also needs the embedding key in `llm.embedding.api_key`. Recognition is imperfect in noise. And it's the newest part of the system by a wide margin — expect rough edges that the typed paths don't have. For the private phone-to-server connection, see [Mentra setup](mentra.md#connection).
