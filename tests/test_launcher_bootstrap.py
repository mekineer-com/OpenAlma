"""Exercise bootstrap without importing the launcher or its user settings."""
import ast
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class BootstrapTest(unittest.TestCase):
    def test_first_run_reuse_and_failed_install(self):
        source = Path(__file__).parents[1] / "launcher" / "run.py"
        function = next(node for node in ast.parse(source.read_text()).body
                        if isinstance(node, ast.FunctionDef) and node.name == "_bootstrap")
        with tempfile.TemporaryDirectory() as directory:
            launcher = Path(directory)
            environment = launcher / ".venv"
            requirements = launcher / "requirements.txt"
            requirements.write_text("first-package==1\n")
            namespace = dict(Path=Path, sys=sys, os=os, subprocess=subprocess, hashlib=hashlib,
                             __file__=str(launcher / "run.py"))
            exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
            bootstrap = namespace["_bootstrap"]
            with patch.object(sys, "version_info", (3, 12)), \
                 patch("venv.EnvBuilder.create", side_effect=lambda path: path.mkdir(exist_ok=True)), \
                 patch.object(subprocess, "run") as install, patch.object(os, "execv") as reexec:
                install.side_effect = [None, subprocess.CalledProcessError(1, "pip")]
                with self.assertRaises(subprocess.CalledProcessError):
                    bootstrap()
                self.assertFalse((environment / ".openalma-ready").exists())
                reexec.assert_not_called()
                (environment / "bin").mkdir()
                (environment / "bin" / "python").touch()
                (environment / ".openalma-ready").touch()
                install.side_effect = None
                bootstrap()
                self.assertTrue((environment / ".openalma-ready").exists())
                self.assertEqual(install.call_args_list[-2].args[0][1:], ["-m", "ensurepip", "--upgrade"])
                self.assertEqual(install.call_args_list[-1].args[0][1:4], ["-m", "pip", "install"])
                self.assertEqual(reexec.call_args.args[1][2:], sys.argv[1:])
                install.reset_mock()
                with patch.object(sys, "prefix", str(environment)):
                    reexec.reset_mock()
                    bootstrap()
                    install.assert_not_called()
                    reexec.assert_not_called()
                    previous = (environment / ".openalma-ready").read_text()
                    requirements.write_text("second-package==2\n")
                    install.side_effect = [None, subprocess.CalledProcessError(1, "pip")]
                    with self.assertRaises(subprocess.CalledProcessError):
                        bootstrap()
                    self.assertEqual((environment / ".openalma-ready").read_text(), previous)
                    reexec.assert_not_called()
                    install.side_effect = None
                    bootstrap()
                    self.assertEqual((environment / ".openalma-ready").read_text(),
                                     hashlib.sha256(requirements.read_bytes()).hexdigest())
                    install.reset_mock()
                    bootstrap()
                    install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
