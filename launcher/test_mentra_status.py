from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import services


class MentraStatusTest(TestCase):
    def test_memu_server_projects_iris_as_display_only_child(self) -> None:
        spec = services.ServiceSpec(
            name="memu-server",
            label="memU Server",
            cmd=[],
            cwd=Path("."),
            log_path=Path("log"),
            pid_path=Path("pid"),
            port=8099,
        )
        payload = {
            "state": "transcript_gap",
            "detail": "Transcript durability gap",
            "mode": "continuous",
        }
        with (
            patch.object(services, "_runtime_state", return_value=services.RuntimeState(running=True)),
            patch.object(services, "_read_channels_config", return_value={}),
            patch.object(services, "_read_mentra_status", return_value=payload),
        ):
            result = services.status(spec)

        self.assertEqual(result["state"], "running")
        self.assertEqual(
            result["children"],
            [
                {
                    "name": "Iris",
                    "state": "transcript_gap",
                    "detail": "Transcript durability gap; mode continuous",
                }
            ],
        )

    def test_memu_server_omits_unavailable_iris_status(self) -> None:
        spec = services.ServiceSpec(
            name="memu-server",
            label="memU Server",
            cmd=[],
            cwd=Path("."),
            log_path=Path("log"),
            pid_path=Path("pid"),
            port=8099,
        )
        with (
            patch.object(services, "_runtime_state", return_value=services.RuntimeState(running=True)),
            patch.object(services, "_read_channels_config", return_value={}),
            patch.object(services, "_read_mentra_status", return_value={}),
        ):
            result = services.status(spec)

        self.assertEqual(result["children"], [])
