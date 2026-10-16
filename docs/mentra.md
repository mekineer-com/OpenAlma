---
layout: default
title: Install OpenAlma Mentra
permalink: /mentra
---

# Install OpenAlma Mentra

Mentra is the Android phone app. Iris runs inside it to connect voice and photos
to your OpenAlma Soul. No glasses or Mentra Store are required.

1. Connect your phone and server through WireGuard or another trusted private connection, then configure the [proxy and server settings](#connection) below.
2. [Download the OpenAlma Mentra APK](https://github.com/mekineer-com/MentraOS/releases/latest). Open the downloaded file and allow installation when Android asks. If no release is available, no public APK is published yet.
3. Open OpenAlma Mentra and sign in. If it cannot connect, enter your OpenAlma server address in Mentra Settings.
4. In the launcher's Services section, click **Install** beside your phone app. Keep Mentra in the foreground; Iris installs automatically.
5. Open Iris, allow microphone access, choose or create a Soul, then tap **Start**.

For [stock Mentra](https://play.google.com/store/apps/details?id=com.mentra.mentra),
use **Setup → Stock Mentra installation** in the launcher instead.

## Connection

OpenAlma does not create the proxy or VPN. Set up a web proxy yourself on the
computer's private-network address, forwarding only `/integration/mentra/*` to
memU Server at `http://127.0.0.1:8099` and returning `404` for other paths. Keep
memU Server on loopback. Use that private address in the launcher's Iris Setup
and Mentra Settings; an `http://` address without a port uses port `80`.

The phone must also reach the Iris installer on the same computer at port
`6789`. Configure `mentra.gemini_api_key`, `mentra.model`, and `mentra.voice`
in the server settings before starting Iris. The launcher checks the server and
proxy under **memU Server readiness**; a VPN alone does not configure either
the proxy or firewall. Devices allowed through can access the Soul's Iris data,
so allow only trusted devices and keep these endpoints off the public internet.
