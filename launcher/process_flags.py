"""Platform flags shared by launcher-owned subprocesses."""
from __future__ import annotations

import os
import subprocess


def hidden_process_kwargs() -> dict[str, int]:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
