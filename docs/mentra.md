---
layout: default
title: Install OpenAlma Mentra
permalink: /mentra
---

# Install OpenAlma Mentra

Mentra is the Android phone app. Iris runs inside it to connect voice and photos
to your OpenAlma Soul. No glasses or Mentra Store are required.

1. Connect your phone and server through WireGuard or another trusted private connection.
2. [Download the OpenAlma Mentra APK](https://github.com/mekineer-com/MentraOS/releases/latest). Open the downloaded file and allow installation when Android asks. If no release is available, no public APK is published yet.
3. Open OpenAlma Mentra and sign in. If it cannot connect, enter your OpenAlma server address in Mentra Settings.
4. In the launcher's Services section, click **Install** beside your phone app. Keep Mentra in the foreground; Iris installs automatically.
5. Open Iris, allow microphone access, choose or create a Soul, then tap **Start**.

For [stock Mentra](https://play.google.com/store/apps/details?id=com.mentra.mentra),
use **Setup → Stock Mentra Installation** in the launcher instead.

## Connection

The private connection must reach the server's Mentra-only proxy and the Iris
installer on port `6789`. The proxy forwards `/integration/mentra/*` to memU
Server, which stays on loopback; unrelated routes must not be exposed.
The launcher checks this under **memU Server readiness**. A VPN alone does not
configure the proxy or firewall. Keep these endpoints off the public internet.
