from io import BytesIO
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile

import services


class MentraStatusTest(TestCase):
    def setUp(self) -> None:
        services._IRIS_RELEASE_CACHE = (services.time.monotonic(), None, "none")

    def tearDown(self) -> None:
        services._MENTRA_READINESS_CACHE.clear()
        services._IRIS_RELEASE_CACHE = None

    def test_iris_candidate_uses_highest_numeric_version(self) -> None:
        spec = services.ServiceSpec("iris-server", "Iris", [], Path("."), Path("log"), Path("pid"))
        with (
            patch.object(services, "_iris_release_identity", return_value=(services.IRIS_PACKAGE, "0.1.10")),
            patch.object(
                services,
                "_github_iris_release",
                return_value=((services.IRIS_PACKAGE, "0.1.9", "https://example.invalid/old.zip"), "available"),
            ),
        ):
            self.assertEqual(services._iris_release_candidate(spec)[:3], (services.IRIS_PACKAGE, "0.1.10", None))
        with patch.object(
            services,
            "_github_iris_release",
            return_value=((services.IRIS_PACKAGE, "0.1.11", "https://example.invalid/new.zip"), "available"),
        ):
            self.assertEqual(services._iris_release_candidate(spec)[1:3], ("0.1.11", "https://example.invalid/new.zip"))

        status = services._iris_product_status(
            services.RuntimeState(),
            {"state": "ready", "installed_package": services.IRIS_PACKAGE, "installed_version": "0.1.12"},
            services.IRIS_PACKAGE,
            "0.1.11",
        )
        self.assertEqual(status["state"], "ready")

    def test_github_bundle_manifest_must_match_release(self) -> None:
        archive = BytesIO()
        with ZipFile(archive, "w") as bundle:
            bundle.writestr("miniapp.json", json.dumps({"packageName": services.IRIS_PACKAGE, "version": "0.1.11"}))
        with (
            TemporaryDirectory() as directory,
            patch.object(services, "STATE_DIR", Path(directory)),
            patch.object(
                services.urllib.request,
                "urlopen",
                side_effect=lambda *_args, **_kwargs: BytesIO(archive.getvalue()),
            ),
        ):
            path = services._download_iris_release("https://example.invalid/iris.zip", services.IRIS_PACKAGE, "0.1.11")
            self.assertEqual(path.read_bytes(), archive.getvalue())
            with self.assertRaisesRegex(ValueError, "does not match"):
                services._download_iris_release(
                    "https://example.invalid/iris.zip", services.IRIS_PACKAGE, "0.1.12"
                )

    def test_host_prerequisites_report_only_runtime_tools(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for path in (
                "openalma/launcher/run.py",
                "mcp-memu-server/run.py",
                "memu/pyproject.toml",
                "mentra-os/miniapps/openalma/miniapp.json",
            ):
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).touch()
            for path in (
                "mentra-os/miniapps/openalma/node_modules",
            ):
                (root / path).mkdir()
            python = root / "mcp-memu-server/.venv/bin/python3"
            python.parent.mkdir(parents=True)
            python.symlink_to(services.sys.executable)
            os_release = root / "os-release"
            os_release.write_text('ID=alpine\nVERSION_ID="3.23.2"\n')
            checked = []
            def which(command):
                checked.append(command)
                return None if command == "ip" else str(command)
            with patch.object(services.shutil, "which", side_effect=which):
                result = services.host_prerequisites(root, os_release)

        self.assertFalse(result["ready"])
        self.assertEqual(result["rows"][0]["state"], "ready")
        self.assertEqual(result["rows"][1]["state"], "ready")
        self.assertEqual(result["rows"][2]["detail"], "Missing: ip")
        self.assertTrue({"node", "bun", "ip"}.issubset(checked))
        self.assertTrue({"npm", "sh", "bash", "wg", "nginx"}.isdisjoint(checked))

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
                return_value={"state": "ready", "detail": "Ready for phone connection", "active": False, "busy": False},
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
            "busy": True,
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
            (services.RuntimeState(), {"state": "unavailable", "detail": "Cannot read mcp config.json"}, "▲ status unavailable", None),
            (services.RuntimeState(running=True), {"state": "unavailable", "detail": "Status unreachable"}, "▲ status unavailable", "stop"),
            (services.RuntimeState(), {}, "▲ setup needed", "settings"),
            (services.RuntimeState(running=True, port_pid=41), installed, "◐ waiting for phone installation", "stop"),
            (services.RuntimeState(running=True), installed, "◐ building installer", "stop"),
            (services.RuntimeState(), {"state": "ready"}, "○ not installed", "settings"),
            (
                services.RuntimeState(),
                {**installed, "installed_version": "0.0.9"},
                "▲ update available",
                "start",
            ),
            (services.RuntimeState(), installed, "● Host ready", None),
            (
                services.RuntimeState(),
                {**installed, "state": "transcript_gap", "detail": "Transcript durability gap"},
                "▲ transcript gap",
                None,
            ),
            (
                services.RuntimeState(running=True),
                {**installed, "state": "active", "active": True},
                "● Connected",
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

        openalma = services._iris_product_status(
            services.RuntimeState(),
            {
                **installed,
                "host": {
                    "host_package": "com.mentra.mentra.openalma",
                    "capabilities": ["iris_install_ack"],
                    "seen_at": services.time.time(),
                },
            },
            "com.openalma.mentra",
            "0.1.0",
        )
        self.assertTrue(openalma["repair_available"])
        self.assertEqual(openalma["action_label"], "Repair")

        stale = services._iris_product_status(
            services.RuntimeState(),
            {**installed, "installed_seen_at": 1000.0, "host": {
                "host_package": "com.mentra.mentra.openalma",
                "capabilities": ["iris_install_ack"],
                "seen_at": 1.0,
            }},
            "com.openalma.mentra",
            "0.1.0",
        )
        self.assertFalse(stale["repair_available"])

    def test_running_offer_reads_exact_phone_host(self) -> None:
        spec = services.ServiceSpec("iris-server", "Iris", [], Path("."), Path("log"), Path("pid"))
        release = {"pid": 1, "device_session_id": "offered-phone", "started_at": 100.0}
        host = {
            "host_package": "com.mentra.mentra.openalma",
            "capabilities": ["iris_install_ack"],
            "seen_at": 101.0,
        }
        with (
            patch.object(services, "mentra_readiness", return_value={"enabled": True, "ready": True}),
            patch.object(services, "_runtime_state", return_value=services.RuntimeState(running=True, port_pid=1)),
            patch.object(services, "_read_iris_release_status", return_value=release),
            patch.object(services, "_read_mentra_status", return_value={"state": "ready", "host": host}) as read,
            patch.object(services, "_iris_release_candidate", return_value=(services.IRIS_PACKAGE, "0.1.0", None, "available")),
            patch.object(services.time, "time", return_value=101.0),
        ):
            result = services.status(spec)

        read.assert_called_once_with(services.MEMU_SERVER_PORT, device_session_id="offered-phone")
        self.assertTrue(result["automatic_offer"])

    def test_disabled_mentra_skips_all_live_probes(self) -> None:
        root = Path(self._testMethodName)
        config = root / "mcp-memu-server" / "config.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"mentra": {"enabled": False}}))
        try:
            with (
                patch.object(services, "all_services", side_effect=AssertionError("service probe")),
                patch.object(services, "_mentra_http_status", side_effect=AssertionError("network probe")),
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
            product = services._iris_product_status(
                services.RuntimeState(running=True), {"state": "disabled"},
                "com.openalma.mentra", "0.1.0", result,
            )
            self.assertEqual(product["action_label"], "Cancel")
            from app import templates
            template = templates.get_template("settings.html")
            page = template.render(
                iris_setup=result,
                iris=product,
                host_prerequisites={"rows": [{"label": "Fictional host check", "state": "ready", "detail": "Ready"}]},
            )
            self.assertIn("irisAction('stop')", page)
            self.assertLess(page.index("Fictional host check"), page.index("Iris &amp; Phone Setup"))
        finally:
            config.unlink()
            config.parent.rmdir()
            root.rmdir()

    def test_missing_private_release_tool_blocks_iris_install(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "mcp-memu-server" / "config.json"
            config.parent.mkdir()
            config.write_text(json.dumps({"mentra": {
                "enabled": True,
                "public_base_url": "http://10.77.0.1",
                "integration_bearer_token": "fictional",
                "gemini_api_key": "fictional",
                "model": "fictional-model",
                "voice": "fictional-voice",
            }}))
            with patch.object(services.shutil, "which", side_effect=lambda command: None if command == "ip" else command):
                result = services._mentra_readiness_uncached(root)

        self.assertEqual(result["step"], "release")
        self.assertEqual(result["reason"], "Private release unavailable; install: ip")

    def test_running_installer_shows_stock_steps_and_exact_phone_id(self) -> None:
        from app import templates

        page = templates.get_template("settings.html").render(
            iris_setup={"enabled": True, "ready": True, "rows": []},
            iris={
                "running": True,
                "release_uri": "miniapp://fictional",
                "release_device_session_id": "test-phone",
                "automatic_offer": True,
            },
            iris_connection={"base_url": "http://10.77.0.1", "bearer": "fictional-key"},
            host_prerequisites={"rows": []},
        )

        self.assertIn("test-phone", page)
        self.assertIn("tap the release number ten times", page)
        self.assertIn("Scan Miniapp QR Code", page)
        self.assertIn("http://10.77.0.1", page)
        self.assertIn("fictional-key", page)
        self.assertIn("OpenAlma Mentra detected", page)

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
                "public_base_url": "http://10.77.0.1",
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
        runtime_tools = patch.object(services.shutil, "which", return_value="/fictional/tool")
        runtime_tools.start()

        try:
            with (
                patch.object(services, "all_services", return_value=[memu]),
                patch.object(services, "_runtime_state", return_value=services.RuntimeState(running=True)),
                patch.object(services, "_mentra_http_status", side_effect=[200, 401, 404]) as http,
            ):
                first = services.mentra_readiness(root)
                second = services.mentra_readiness(root)
            self.assertTrue(first["ready"])
            self.assertIs(first, second)
            self.assertEqual(http.call_count, 3)
            self.assertEqual(http.call_args_list[2].args, ("http://10.77.0.1/health",))
            self.assertEqual(len(first["rows"]), 5)

            for responses, detail in (([0], "Cannot reach"), ([401], "rejected the bearer"), ([502], "HTTP 502"),
                                      ([200, 200], "accepts missing credentials"), ([200, 401, 200], "exposes an unrelated path"),
                                      ([200, 401, 0], "no connection")):
                with (
                    patch.object(services, "all_services", return_value=[memu]),
                    patch.object(services, "_runtime_state", return_value=services.RuntimeState(running=True)),
                    patch.object(services, "_mentra_http_status", side_effect=responses),
                ):
                    self.assertIn(detail, services._mentra_readiness_uncached(root)["reason"])

            for content in ("MENTRA_PUBLIC_OPENALMA_BASE_URL=http://wrong\nMENTRA_PUBLIC_OPENALMA_BEARER=wrong\n", None):
                if content is None:
                    env_path.unlink()
                else:
                    env_path.write_text(content)
                services._MENTRA_READINESS_CACHE.clear()
                with (
                    patch.object(services, "all_services", return_value=[memu]),
                    patch.object(services, "_runtime_state", return_value=services.RuntimeState(running=True)),
                    patch.object(services, "_mentra_http_status", side_effect=[200, 401, 404]),
                ):
                    self.assertTrue(services.mentra_readiness(root)["ready"])
        finally:
            runtime_tools.stop()
            for path in (env_path, config):
                path.unlink(missing_ok=True)
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

    def test_stopped_memu_does_not_direct_user_to_settings(self) -> None:
        result = services._iris_product_status(
            services.RuntimeState(), {"state": "unavailable", "detail": "Mentra status unreachable or invalid"}, "com.openalma.mentra", "0.1.0",
            {"enabled": True, "ready": False, "step": "server", "reason": "Start memU Server"},
        )
        self.assertEqual(result["setup_issue"], "")
        self.assertIsNone(result["action_kind"])
        self.assertEqual(result["detail"], "Start memU Server in Services")

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
                if code == 200:
                    self.wfile.write(b'{"state":"ready","busy":false}')

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
                with TemporaryDirectory() as directory:
                    root = Path(directory)
                    config = root / "mcp-memu-server" / "config.json"
                    config.parent.mkdir()
                    config.write_text(json.dumps({"mentra": {"enabled": True, "integration_bearer_token": "fictional-secret"}}))
                    with patch.object(services, "_resolve_apps_root", return_value=root):
                        self.assertIs(services._read_mentra_status(server.server_port)["busy"], False)
                        config.write_text(json.dumps({"mentra": {"enabled": False, "integration_bearer_token": "fictional-secret"}}))
                        self.assertEqual(services._read_mentra_status(server.server_port)["state"], "ready")
                        config.write_text(json.dumps({"mentra": {"enabled": True, "integration_bearer_token": "wrong"}}))
                        rejected = services._read_mentra_status(server.server_port)
                        self.assertEqual(rejected["state"], "unavailable")
                        self.assertIn("credential", rejected["detail"])
                        with patch.object(services.urllib.request, "urlopen", side_effect=TimeoutError):
                            self.assertNotIn("busy", services._read_mentra_status(server.server_port))
            finally:
                server.shutdown()
                thread.join()

    def test_installed_soul_status_ignores_next_build_identity(self) -> None:
        spec = services.ServiceSpec("iris-server", "Iris", [], Path("."), Path("log"), Path("pid"))
        installed = {"installed_soul": "Installed Soul", "installed_package": "com.openalma.mentra", "installed_version": "0.1.0"}
        with (
            patch.object(services, "mentra_readiness", return_value={"enabled": True, "ready": True, "soul_id": "Next Build", "device_session_id": "other-phone"}),
            patch.object(services, "_runtime_state", return_value=services.RuntimeState()),
            patch.object(services, "_read_channels_config", side_effect=AssertionError("Channels must not be consulted")),
            patch.object(services, "_iris_release_identity", return_value=("com.openalma.mentra", "0.1.0")),
            patch.object(services, "_read_mentra_status", return_value={**installed, "active": True, "state": "active"}) as status,
        ):
            result = services.status(spec)
        self.assertTrue(result["active"])
        status.assert_called_once_with(8099, device_session_id="")

    def test_soul_api_uses_authoritative_server_contract(self) -> None:
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(("GET", self.path))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"souls":["Codexia","Echo"]}')

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append(("POST", payload))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"soul_id":"Codexia","created":false}')

            def log_message(self, *_args):
                pass

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch.object(services, "MEMU_SERVER_PORT", server.server_port):
                    self.assertEqual(services.list_souls(), ["Codexia", "Echo"])
                    self.assertEqual(services.resolve_soul("Codexia", True), "Codexia")
                    with self.assertRaisesRegex(services.SoulServiceUnavailable, "different soul"):
                        services.resolve_soul("Echo", True)
            finally:
                server.shutdown()
                thread.join()
        self.assertEqual(requests, [
            ("GET", "/souls"),
            ("POST", {"soul_id": "Codexia", "use_existing": True}),
            ("POST", {"soul_id": "Echo", "use_existing": True}),
        ])

    def test_soul_errors_preserve_server_guidance(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(422 if payload["soul_id"] == "Invalid Soul" else 409)
                self.end_headers()
                if payload["soul_id"] == "Invalid Soul":
                    self.wfile.write(b'{"detail":"Fictional validation failure"}')
                else:
                    self.wfile.write(b'{"detail":{"reason":"existing_exact","message":"Fictional existing soul"}}')

            def log_message(self, *_args):
                pass

        with HTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch.object(services, "MEMU_SERVER_PORT", server.server_port):
                    with self.assertRaisesRegex(ValueError, "Fictional existing soul"):
                        services.resolve_soul("Codexia", False)
                    with self.assertRaisesRegex(ValueError, "Fictional validation failure"):
                        services.resolve_soul("Invalid Soul", False)
            finally:
                server.shutdown()
                thread.join()

    def test_soul_selector_requires_server_before_updating_channels_config(self) -> None:
        from fastapi.testclient import TestClient
        import app

        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "config.json"
            state_db = root / "state.db"
            config.write_text(json.dumps({
                "user_id": "Fictional User",
                "soul_id": "Old Soul",
                "souls": ["Wrong Source"],
                "reply_prefix_template": "*{soul}*: ",
            }))
            with (
                patch.object(app.soul, "CHANNELS_CONFIG_PATH", config),
                patch.object(app.soul, "HERMES_STATE_DB_PATH", state_db),
                patch.object(app.policy, "list_whatsapp_chats", return_value=[]),
                patch.object(app.policy, "read_channel_settings", return_value={}),
                patch.object(app.settings, "apps_root", return_value=None),
                patch.object(services, "all_services", return_value=[]),
                patch.object(app, "_find_service", return_value=services.ServiceSpec(
                    "channels-daemon", "Hermes Channels", [], root, root / "log", root / "pid",
                )),
                patch.object(services, "status", return_value={"state": "stopped"}),
                patch.object(services, "memorize_pending", return_value={}),
                patch.object(services, "list_souls", return_value=["Codexia"]),
                patch.object(services, "read_owner", return_value="Fictional User"),
            ):
                client = TestClient(app.app)
                page = client.get("/").text
                self.assertIn('const knownSouls = new Set(["Codexia"])', page)
                self.assertNotIn('const knownSouls = new Set(["Wrong Source"])', page)
                with patch.object(services, "list_souls", side_effect=services.SoulServiceUnavailable("Soul service unavailable")):
                    unavailable = client.get("/")
                    self.assertEqual(unavailable.status_code, 200)
                    self.assertIn("Souls unavailable", unavailable.text)
                    self.assertNotIn('<form method="post" action="/soul">', unavailable.text)
                    self.assertEqual(json.loads(config.read_text())["soul_id"], "Old Soul")
                self.assertEqual(client.get("/souls").json(), {"souls": ["Codexia"]})
                with patch.object(services, "resolve_soul", side_effect=services.SoulServiceUnavailable("Soul service unavailable")):
                    self.assertEqual(client.post("/soul", data={"soul_id": "New Soul"}).status_code, 503)
                self.assertEqual(json.loads(config.read_text())["soul_id"], "Old Soul")
                with patch.object(services, "resolve_soul", return_value="Codexia") as resolve:
                    self.assertEqual(client.post("/soul", data={"soul_id": "Codexia", "use_existing": "true"}, follow_redirects=False).status_code, 303)
                resolve.assert_called_once_with("Codexia", True)
                with (
                    patch.object(services, "status", return_value={"state": "healthy", "running": True}),
                    patch.object(services, "resolve_soul") as blocked_resolve,
                ):
                    response = client.post("/soul", data={"soul_id": "New Soul"})
                    self.assertEqual(response.status_code, 409)
                    blocked_resolve.assert_not_called()
                with (
                    patch.object(services, "status", return_value={"state": "stopping", "running": False}),
                    patch.object(services, "resolve_soul") as blocked_resolve,
                ):
                    self.assertEqual(client.post("/soul", data={"soul_id": "New Soul"}).status_code, 409)
                    blocked_resolve.assert_not_called()
            saved = json.loads(config.read_text())
            self.assertEqual(saved["soul_id"], "Codexia")
            self.assertEqual(saved["reply_prefix"], "*Codexia*: ")
            self.assertTrue(state_db.exists())

    def test_channels_free_pages_and_stop_action_guard(self) -> None:
        from fastapi.testclient import TestClient
        import app
        with (
            TemporaryDirectory() as directory,
            patch.object(app.soul, "CHANNELS_CONFIG_PATH", Path(directory) / "absent.json"),
            patch.object(app.policy, "list_whatsapp_chats", return_value=[]),
            patch.object(app.policy, "read_channel_settings", return_value={}),
            patch.object(app.settings, "apps_root", return_value=None),
            patch.object(app.settings, "read_paths", return_value={}),
            patch.object(services, "all_services", return_value=[]),
            patch.object(services, "read_owner", return_value="Fictional User"),
            patch.object(services, "list_souls", return_value=[]),
        ):
            client = TestClient(app.app)
            self.assertIn("Welcome back, <strong>Fictional User</strong>", client.get("/").text)
            with (
                patch.object(services, "read_owner", return_value=None),
                patch.object(services, "create_owner", return_value="Fictional User") as create_owner,
                patch.object(
                    services,
                    "resolve_soul",
                    side_effect=services.SoulServiceUnavailable("Soul service unavailable"),
                ) as resolve_soul,
            ):
                page = client.get("/").text
                self.assertIn('name="user_id"', page)
                self.assertIn('name="soul_id"', page)
                self.assertEqual(client.post("/owner", data={"user_id": "Fictional User"}).status_code, 400)
                response = client.post(
                    "/owner",
                    data={"user_id": "Fictional User", "soul_id": "Codexia", "confirmed": "true"},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 503)
                create_owner.assert_called_once_with("Fictional User")
                resolve_soul.assert_called_once_with("Codexia", False)
            recovery_page = client.get("/").text
            self.assertIn("Your identity is saved", recovery_page)
            self.assertIn('action="/first-soul"', recovery_page)
            with (
                patch.object(services, "create_owner") as create_owner,
                patch.object(services, "resolve_soul", return_value="Codexia") as resolve_soul,
            ):
                response = client.post(
                    "/first-soul",
                    data={"soul_id": "Codexia", "confirmed": "true"},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 303)
                create_owner.assert_not_called()
                resolve_soul.assert_called_once_with("Codexia", False)
            with patch.object(services, "list_souls", return_value=["Codexia"]):
                self.assertNotIn("Your identity is saved", client.get("/").text)
            self.assertEqual(client.get("/memorize/status").json(), {})
            iris = services.ServiceSpec("iris-server", "Iris", [], Path(directory), Path("log"), Path("pid"))
            app.settings.apps_root.return_value = Path(directory)
            start_issue_patch = patch.object(app.setup_install, "start_issue", return_value="")
            start_issue_patch.start()
            self.addCleanup(start_issue_patch.stop)
            with (
                patch.object(services, "all_services", return_value=[iris]),
                patch.object(services, "mentra_readiness", return_value={"enabled": True, "ready": True, "rows": []}),
                patch.object(services, "_read_mentra_status", return_value={"state": "ready", "busy": False}),
                patch.object(services, "_runtime_state", return_value=services.RuntimeState()),
                patch.object(services, "_iris_release_identity", return_value=("com.openalma.mentra", "0.1.0")),
                patch.object(services, "resolve_soul", return_value="Fictional Soul"),
                patch.object(services, "read_owner", return_value="Fictional User"),
                patch.object(services, "iris_install_env", return_value={}),
                patch.object(services, "start") as start,
            ):
                home = client.get("/").text
                self.assertIn("Not installed (1)", home)
                self.assertIn("Iris", home)
                with patch.object(
                    services, "_runtime_state", return_value=services.RuntimeState(running=True, port_pid=41)
                ):
                    running_home = client.get("/").text
                self.assertIn("waiting for phone installation", running_home)
                self.assertIn(">Cancel<", running_home)
                self.assertNotIn("Not installed (1)", running_home)
                self.assertIn('action="/iris/install"', client.get("/settings").text)
                with (
                    patch.object(services, "_read_mentra_status", return_value={
                        "state": "ready",
                        "installed_package": "com.openalma.mentra",
                        "installed_version": "0.1.0",
                        "installed_soul": "Fictional Soul",
                        "installed_device": "test-phone",
                    }),
                    patch.object(app.setup_install, "optional_setup_status", return_value={
                        "ready": True, "guidance": "",
                    }),
                ):
                    installed_home = client.get("/").text
                self.assertIn('data-soul="Fictional Soul"', installed_home)
                self.assertIn('data-device="test-phone"', installed_home)
                target = {"soul_id": "Fictional Soul", "device_session_id": "test-phone"}
                self.assertEqual(client.post("/iris/install", data=target, follow_redirects=False).status_code, 303)
                start.assert_called_once_with(iris, install_target=target)
                start.reset_mock()
                response = client.post(
                    "/service/iris-server/start",
                    params={"soul_id": "Fictional Soul", "device_session_id": "other-phone"},
                )
                self.assertEqual(response.status_code, 200)
                start.assert_called_once_with(iris, install_target={
                    "soul_id": "Fictional Soul", "device_session_id": "other-phone",
                })
                with (
                    patch.object(services, "iris_install_env", side_effect=ValueError("Invalid install target")),
                    patch.object(services, "resolve_soul") as resolve,
                ):
                    self.assertEqual(client.post("/iris/install", data=target).status_code, 400)
                    resolve.assert_not_called()
                    self.assertEqual(start.call_count, 1)
                with services._STOP_LOCK:
                    services._STOP_THREADS[iris.name] = services.threading.current_thread()
                try:
                    with (
                        patch.object(services, "iris_install_env") as install_env,
                        patch.object(services, "resolve_soul") as resolve,
                    ):
                        self.assertEqual(client.post("/iris/install", data=target).status_code, 409)
                        install_env.assert_not_called()
                        resolve.assert_not_called()
                        self.assertEqual(start.call_count, 1)
                finally:
                    with services._STOP_LOCK:
                        services._STOP_THREADS.pop(iris.name, None)
            spec = services.ServiceSpec("memu-server", "memU", [], Path(directory), Path("log"), Path(directory) / "pid")
            with (
                patch.object(app, "_find_service", return_value=spec),
                patch.object(
                    services,
                    "_runtime_state",
                    return_value=services.RuntimeState(
                        verified_pids=(123,), service_pids=(123,), stuck=True,
                    ),
                ),
                patch.object(services, "_verified_pid_candidates", side_effect=([123], [])),
                patch.object(services, "_request_memu_shutdown", return_value=True),
                patch.object(services, "_kill_process_tree") as force_kill,
            ):
                with patch.object(services, "_read_mentra_status", return_value={"busy": True}):
                    self.assertEqual(client.post("/service/memu-server/stop?confirm_unknown=true").status_code, 409)
                with patch.object(services, "_read_mentra_status", return_value={"state": "unavailable"}):
                    self.assertTrue(services.status(spec)["stoppable"])
                    self.assertEqual(client.post("/service/memu-server/stop").status_code, 428)
                    force_kill.assert_not_called()
                    self.assertEqual(client.post("/service/memu-server/stop?confirm_unknown=true").status_code, 200)
                    force_kill.assert_not_called()
                    with services._STOP_LOCK:
                        stop_thread = services._STOP_THREADS[spec.name]
                    stop_thread.join(timeout=2)
                with patch.object(services, "stop", side_effect=ValueError("unexpected failure")):
                    response = TestClient(app.app, raise_server_exceptions=False).post("/service/memu-server/stop")
                    self.assertEqual(response.status_code, 500)
                with patch.object(services, "stop", side_effect=RuntimeError("shutdown rejected")):
                    response = client.post("/service/memu-server/stop")
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.json()["detail"], "shutdown rejected")
            with (
                patch.object(app, "_find_service", return_value=spec),
                patch.object(services, "force_stop") as force_stop,
            ):
                self.assertEqual(client.post("/service/memu-server/force-stop").status_code, 428)
                self.assertEqual(client.post("/service/memu-server/force-stop?confirmed=true").status_code, 200)
                force_stop.assert_called_once_with(spec)

    def test_generated_build_uses_host_and_recorded_phone_not_ambient_env(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "mcp-memu-server").mkdir()
            (root / "mcp-memu-server" / "config.json").write_text(json.dumps({"mentra": {
                "enabled": True, "public_base_url": "http://10.77.0.1", "integration_bearer_token": "new-key",
            }}))
            spec = services.ServiceSpec("iris-server", "Iris", [], root, root / "log", root / "pid")
            env_path = root / ".env.local"
            env_path.write_text("MENTRA_PUBLIC_OPENALMA_BEARER=old-key\n")
            with (
                patch.object(services, "_resolve_apps_root", return_value=root),
                patch.object(services, "_read_mentra_status", return_value={
                    "installed_user": "Wrong User", "installed_soul": 'Fictional "Soul"', "installed_device": "test-phone",
                }),
                patch.object(services, "read_owner", return_value="Fictional User"),
                patch.dict(services.os.environ, {"MENTRA_PUBLIC_OPENALMA_BEARER": "stale-ambient-key"}),
                patch.object(services, "_runtime_state", return_value=services.RuntimeState()),
                patch.object(services, "_iris_release_candidate", return_value=(services.IRIS_PACKAGE, "0.1.11", "https://example.invalid/iris.zip", "available")),
                patch.object(services, "_download_iris_release", return_value=root / "iris.zip"),
                patch.object(services, "_spawn_background") as spawn,
                patch.object(services, "STATE_DIR", root),
            ):
                spawn.return_value.pid = 123
                services.start(spec)
                built = spawn.call_args.args[1]
                self.assertEqual(built["MENTRA_PUBLIC_OPENALMA_BEARER"], "new-key")
                self.assertEqual(built["MENTRA_PUBLIC_OPENALMA_USER_ID"], "Fictional%20User")
                self.assertEqual(built["MENTRA_PUBLIC_OPENALMA_DEVICE_SESSION_ID"], "test-phone")
                self.assertEqual(built["MENTRA_PUBLIC_OPENALMA_SOUL_ID"], "Fictional%20%22Soul%22")
                self.assertEqual(built["MENTRA_PUBLIC_OPENALMA_PREVIOUS_VERSION"], "")
                self.assertEqual(built["MENTRA_RELEASE_BUNDLE"], str(root / "iris.zip"))
                self.assertIn('BEARER="new-key"', env_path.read_text())
                self.assertIn('SOUL_ID="Fictional%20%22Soul%22"', env_path.read_text())
                self.assertIn("old-key", (root / ".env.local.orig").read_text())
                self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)
                self.assertEqual((root / ".env.local.orig").stat().st_mode & 0o777, 0o600)
                (root / "mcp-memu-server" / "config.json").write_text("{}")
                with self.assertRaisesRegex(ValueError, "Enable Mentra"):
                    services._iris_build_env(spec, None)
