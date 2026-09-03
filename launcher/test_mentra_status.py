from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import services


class MentraStatusTest(TestCase):
    def test_memu_server_shows_ready_iris_child(self) -> None:
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
            patch.object(
                services,
                "_read_mentra_status",
                return_value={"state": "ready", "detail": "Ready for phone connection", "active": False},
            ),
        ):
            result = services.status(spec)

        self.assertEqual(result["status_label"], "● running")
        self.assertEqual(result["children"], [{
            "name": "Mentra Iris",
            "state": "ready",
            "detail": "Ready for phone connection",
        }])
        self.assertTrue(result["stoppable"])

    def test_active_iris_lease_blocks_memu_stop(self) -> None:
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
            "active": True,
        }
        with (
            patch.object(services, "_runtime_state", return_value=services.RuntimeState(running=True)),
            patch.object(services, "_read_channels_config", return_value={}),
            patch.object(services, "_read_mentra_status", return_value=payload),
        ):
            result = services.status(spec)

        self.assertEqual(result["state"], "running")
        self.assertEqual(result["children"][0]["state"], "transcript_gap")
        self.assertFalse(result["stoppable"])
        self.assertTrue(result["stop_blocked"])

    def test_iris_installer_does_not_project_phone_status(self) -> None:
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
            patch.object(services, "_read_mentra_status") as read_status,
        ):
            result = services.status(spec)

        read_status.assert_not_called()
        self.assertEqual(result["status_label"], "● running")
        self.assertEqual(result["children"], [])
