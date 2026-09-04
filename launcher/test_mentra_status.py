from pathlib import Path
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from unittest import TestCase
from unittest.mock import patch

import services


class MentraStatusTest(TestCase):
    def tearDown(self) -> None:
        services._MENTRA_READINESS_CACHE.clear()

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
            (services.RuntimeState(running=True, port_pid=41), installed, "◐ waiting for phone installation", "stop"),
            (services.RuntimeState(running=True), installed, "◐ building installer", "stop"),
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

    def test_disabled_mentra_skips_all_live_probes(self) -> None:
        root = Path(self._testMethodName)
        config = root / "mcp-memu-server" / "config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"mentra": {"enabled": False}}))
        try:
            with (
                patch.object(services, "all_services", side_effect=AssertionError("service probe")),
                patch.object(services.subprocess, "check_output", side_effect=AssertionError("network probe")),
            ):
                result = services.mentra_readiness(root)
            self.assertFalse(result["enabled"])
            self.assertEqual(result["step"], "disabled")
            product = services._iris_product_status(
                services.RuntimeState(),
                {"state": "disabled"},
                "com.openalma.mentra",
                "0.1.0",
                result,
            )
            self.assertEqual(product["state"], "disabled")
            self.assertIsNone(product["action_kind"])
        finally:
            config.unlink()
            config.parent.rmdir()
            root.rmdir()

    def test_readiness_checks_private_ingress_once_per_cache_window(self) -> None:
        root = Path(self._testMethodName)
        config = root / "mcp-memu-server" / "config.json"
        env_path = root / "mentra-os" / "miniapps" / "openalma" / ".env.local"
        config.parent.mkdir(parents=True)
        env_path.parent.mkdir(parents=True)
        config.write_text(json.dumps({
            "mentra": {
                "enabled": True,
                "integration_bearer_token": "fictional",
                "gemini_api_key": "fictional",
                "model": "fictional-model",
                "voice": "fictional-voice",
            }
        }))
        env_path.write_text(
            "MENTRA_PUBLIC_OPENALMA_BASE_URL=http://10.77.0.1\n"
            "MENTRA_PUBLIC_OPENALMA_BEARER=fictional\n"
            "MENTRA_PUBLIC_OPENALMA_USER_ID=Fictional User\n"
            "MENTRA_PUBLIC_OPENALMA_SOUL_ID=Fictional Soul\n"
            "MENTRA_PUBLIC_OPENALMA_DEVICE_SESSION_ID=fictional-phone\n"
        )
        memu = services.ServiceSpec("memu-server", "memU", [], root, root / "log", root / "pid")

        def command_output(command: list[str], **_kwargs) -> str:
            if command[:2] == ["ip", "-j"]:
                return json.dumps([{"addr_info": [{"local": "10.77.0.1"}]}])
            return "LISTEN 0 4096 10.77.0.1:80 0.0.0.0:*\n"

        try:
            with (
                patch.object(services, "all_services", return_value=[memu]),
                patch.object(services, "_runtime_state", return_value=services.RuntimeState(running=True)),
                patch.object(services.subprocess, "check_output", side_effect=command_output) as probe,
                patch.object(services, "_mentra_http_status", side_effect=[200, 404]) as http,
            ):
                first = services.mentra_readiness(root)
                second = services.mentra_readiness(root)
            self.assertTrue(first["ready"])
            self.assertIs(first, second)
            self.assertEqual(probe.call_count, 2)
            self.assertEqual(http.call_count, 2)
            self.assertEqual(http.call_args_list[1].args, ("http://10.77.0.1/health",))
            self.assertEqual(len(first["rows"]), 5)

            services._MENTRA_READINESS_CACHE.clear()
            with (
                patch.object(services, "all_services", return_value=[memu]),
                patch.object(services, "_runtime_state", return_value=services.RuntimeState(running=True)),
                patch.object(
                    services.subprocess,
                    "check_output",
                    side_effect=[
                        json.dumps([{"addr_info": [{"local": "10.77.0.1"}]}]),
                        "LISTEN 0 4096 10.77.0.1:80 0.0.0.0:*\n"
                        "LISTEN 0 4096 0.0.0.0:80 0.0.0.0:*\n",
                    ],
                ),
                patch.object(services, "_mentra_http_status", side_effect=AssertionError("HTTP probe")),
            ):
                exposed = services.mentra_readiness(root)
            self.assertFalse(exposed["ready"])
            self.assertEqual(exposed["step"], "ingress")
        finally:
            for path in (env_path, config):
                path.unlink()
            for path in (env_path.parent, env_path.parent.parent, env_path.parent.parent.parent, config.parent, root):
                path.rmdir()

    def test_active_sitting_outranks_setup_failure(self) -> None:
        result = services._iris_product_status(
            services.RuntimeState(),
            {"active": True, "state": "active"},
            "com.openalma.mentra",
            "0.1.0",
            {"enabled": True, "ready": False, "reason": "fictional failure"},
        )
        self.assertEqual(result["state"], "active")
        self.assertIsNone(result["action_kind"])

    def test_iris_release_status_verifies_wrapper_independently_of_parent_pid(self) -> None:
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
            with (
                patch.object(services, "_is_alive", return_value=True),
                patch.object(services, "_proc_cwd", return_value=root),
                patch.object(services, "_proc_cmdline", return_value="node unrelated.mjs"),
            ):
                self.assertEqual(
                    services._read_iris_release_status(spec, services.RuntimeState(running=True)), {}
                )
            with (
                patch.object(services, "_is_alive", return_value=True),
                patch.object(services, "_proc_cwd", return_value=root),
                patch.object(services, "_proc_cmdline", return_value="node scripts/release-private.mjs"),
            ):
                self.assertEqual(
                    services._read_iris_release_status(
                        spec, services.RuntimeState(running=True, verified_pids=(41,))
                    )["release_uri"],
                    "miniapp://fictional",
                )
            with patch.object(services, "_is_alive", return_value=False):
                self.assertEqual(
                    services._read_iris_release_status(spec, services.RuntimeState(running=True)), {}
                )
        finally:
            path.unlink()
            path.parent.rmdir()
            root.rmdir()

    def test_live_installer_build_outlasts_service_startup_grace(self) -> None:
        spec = services.ServiceSpec("iris-server", "Iris", [], Path("."), Path("log"), Path("pid"), port=6789)
        with (
            patch.object(services, "_verified_pid_candidates", return_value=[41]),
            patch.object(services, "_matches_service_process", return_value=True),
            patch.object(services, "_port_listener_pid", return_value=None),
            patch.object(services, "_remember_verified_pid"),
            patch.object(services, "_within_startup_grace", return_value=False),
        ):
            runtime = services._runtime_state(spec)
        self.assertTrue(runtime.running)
        self.assertFalse(runtime.stuck)

    def test_http_probe_sends_bearer_and_preserves_rejection_status(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                authorized = self.headers.get("Authorization") == "Bearer fictional-secret"
                code = 404 if self.path == "/unrelated" else 200 if authorized else 401
                self.send_response(code)
                self.end_headers()

            def log_message(self, *_args):
                pass

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f"http://127.0.0.1:{server.server_port}"
            try:
                self.assertEqual(services._mentra_http_status(url, "fictional-secret"), 200)
                self.assertEqual(services._mentra_http_status(url, "wrong"), 401)
                self.assertEqual(services._mentra_http_status(url + "/unrelated"), 404)
            finally:
                server.shutdown()
                thread.join()

    def test_missing_build_inputs_do_not_nag_installed_iris(self) -> None:
        readiness = {"enabled": True, "ready": False, "step": "iris_config", "reason": "Missing build inputs"}
        installed = {"state": "ready", "installed_package": "com.openalma.mentra", "installed_version": "0.1.0"}
        for mentra, expected in ((installed, "ready"), ({"state": "ready"}, "setup")):
            result = services._iris_product_status(
                services.RuntimeState(), mentra, "com.openalma.mentra", "0.1.0", readiness
            )
            self.assertEqual(result["state"], expected)
            self.assertEqual(bool(result["setup_issue"]), expected == "setup")
        self.assertFalse(readiness["ready"])

    def test_installed_soul_status_ignores_next_build_identity(self) -> None:
        spec = services.ServiceSpec("iris-server", "Iris", [], Path("."), Path("log"), Path("pid"))
        installed = {"installed_soul": "Installed Soul", "installed_package": "com.openalma.mentra", "installed_version": "0.1.0"}
        with (
            patch.object(services, "mentra_readiness", return_value={"enabled": True, "ready": True, "soul_id": "Next Build", "device_session_id": "other-phone"}),
            patch.object(services, "_runtime_state", return_value=services.RuntimeState()),
            patch.object(services, "_read_channels_config", return_value={"user_id": "Fictional User", "soul_id": "Selected Soul"}),
            patch.object(services, "_iris_release_identity", return_value=("com.openalma.mentra", "0.1.0")),
            patch.object(services, "_read_mentra_status", side_effect=[installed, {**installed, "active": True, "state": "active"}]) as status,
        ):
            result = services.status(spec)
        self.assertTrue(result["active"])
        self.assertEqual(status.call_args_list[0].args, (8099, "Selected Soul", "Fictional User"))
        self.assertEqual(status.call_args_list[1].args, (8099, "Installed Soul", "Fictional User"))
