from pathlib import Path
import json
from unittest import TestCase
from unittest.mock import patch

import services


class MentraStatusTest(TestCase):
    def test_memu_server_keeps_only_iris_stop_guard(self) -> None:
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
        self.assertEqual(result["children"], [])
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
        self.assertEqual(result["children"], [])
        self.assertFalse(result["stoppable"])
        self.assertTrue(result["stop_blocked"])

    def test_iris_product_row_states_and_actions(self) -> None:
        installed = {
            "state": "ready",
            "installed_package": "com.openalma.mentra",
            "installed_version": "0.1.0",
            "installed_seen_at": 100.0,
        }
        cases = [
            (services.RuntimeState(), {}, "▲ setup needed", "settings"),
            (services.RuntimeState(running=True), installed, "◐ waiting for phone installation", "stop"),
            (services.RuntimeState(), {"state": "ready"}, "○ not installed", "start"),
            (
                services.RuntimeState(),
                {**installed, "installed_version": "0.0.9"},
                "▲ update available",
                "start",
            ),
            (services.RuntimeState(), installed, "● ready", None),
            (
                services.RuntimeState(),
                {**installed, "state": "transcript_gap", "detail": "Transcript durability gap"},
                "▲ transcript gap",
                None,
            ),
            (
                services.RuntimeState(running=True),
                {**installed, "state": "active", "active": True},
                "● active",
                None,
            ),
            (
                services.RuntimeState(running=True),
                {**installed, "state": "degraded", "active": True},
                "▲ degraded",
                None,
            ),
        ]
        with patch.object(services.time, "time", return_value=200.0):
            for runtime, mentra, label, action in cases:
                with self.subTest(label=label):
                    result = services._iris_product_status(
                        runtime, mentra, "com.openalma.mentra", "0.1.0"
                    )
                    self.assertEqual(result["status_label"], label)
                    self.assertEqual(result["action_kind"], action)

    def test_iris_release_status_requires_its_verified_live_pid(self) -> None:
        root = Path(self._testMethodName)
        spec = services.ServiceSpec(
            name="iris-server",
            label="Mentra Iris",
            cmd=[],
            cwd=root,
            log_path=Path("log"),
            pid_path=Path("pid"),
        )
        path = root / "build" / "release-private-status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pid": 42, "release_uri": "miniapp://fictional"}))
        try:
            self.assertEqual(services._read_iris_release_status(spec, services.RuntimeState()), {})
            self.assertEqual(
                services._read_iris_release_status(
                    spec, services.RuntimeState(running=True, verified_pids=(41,))
                ),
                {},
            )
            self.assertEqual(
                services._read_iris_release_status(
                    spec, services.RuntimeState(running=True, verified_pids=(42,))
                )["release_uri"],
                "miniapp://fictional",
            )
        finally:
            path.unlink()
            path.parent.rmdir()
            root.rmdir()
