from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import services


class MentraStatusTest(TestCase):
    def test_iris_server_shows_ready_message_without_nested_status(self) -> None:
        spec = services.ServiceSpec(
            name="iris-server",
            label="Iris MiniApp Server",
            cmd=[],
            cwd=Path("."),
            log_path=Path("log"),
            pid_path=Path("pid"),
            port=6789,
        )
        with (
            patch.object(services, "_runtime_state", return_value=services.RuntimeState(running=True)),
            patch.object(services, "_read_channels_config", return_value={}),
            patch.object(
                services,
                "_read_mentra_status",
                return_value={"state": "ready", "detail": "Ready for phone connection"},
            ),
        ):
            result = services.status(spec)

        self.assertEqual(result["status_label"], "Ready for phone connection")
        self.assertEqual(result["children"], [])

    def test_iris_server_projects_phone_status_directly(self) -> None:
        spec = services.ServiceSpec(
            name="iris-server",
            label="Iris MiniApp Server",
            cmd=[],
            cwd=Path("."),
            log_path=Path("log"),
            pid_path=Path("pid"),
            port=6789,
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

        self.assertEqual(result["state"], "transcript_gap")
        self.assertEqual(result["status_label"], "Transcript durability gap")
        self.assertEqual(result["children"], [])

    def test_iris_server_omits_unavailable_phone_status(self) -> None:
        spec = services.ServiceSpec(
            name="iris-server",
            label="Iris MiniApp Server",
            cmd=[],
            cwd=Path("."),
            log_path=Path("log"),
            pid_path=Path("pid"),
            port=6789,
        )
        with (
            patch.object(services, "_runtime_state", return_value=services.RuntimeState(running=True)),
            patch.object(services, "_read_channels_config", return_value={}),
            patch.object(services, "_read_mentra_status", return_value={}),
        ):
            result = services.status(spec)

        self.assertEqual(result["children"], [])
