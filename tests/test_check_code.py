from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import check_code


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "check_code.py"


class CheckCodeTests(unittest.TestCase):
    def test_project_config_and_exclude_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "generated").mkdir()
            (root / "sample.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "generated" / "output.py").write_text("print('generated')\n", encoding="utf-8")
            (root / ".check-code.toml").write_text(
                """[check-code]
strict = true
run_tests = false
exclude = ["generated/**"]
required_tools = ["definitely-missing-tool"]

[check-code.commands]
smoke = ["python", "-c", "print('configured')"]
""",
                encoding="utf-8",
            )

            config = check_code.load_project_config(root)
            self.assertTrue(config.strict)
            self.assertFalse(config.run_tests)
            self.assertEqual(config.exclude, ["generated/**"])
            self.assertEqual(config.commands["smoke"][-1], "print('configured')")
            files = check_code.relative_files(root, check_code.iter_project_files(root, config.exclude), config.exclude)
            self.assertIn("sample.py", files)
            self.assertNotIn("generated/output.py", files)

    def test_baseline_round_trip_suppresses_known_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = check_code.CheckResult(
                name="JSON 语法检查：bad.json",
                status="FAIL",
                reason="语法解析失败",
                output="line 1 column 2",
                files=["bad.json"],
            )
            baseline_path = root / "baseline.json"
            check_code.write_baseline(baseline_path, [result], root)
            baseline = check_code.load_baseline(baseline_path)
            current = check_code.CheckResult(
                name=result.name,
                status="FAIL",
                reason=result.reason,
                output=result.output,
                files=result.files,
            )
            self.assertEqual(check_code.apply_baseline([current], baseline, root), 1)
            self.assertEqual(current.status, "BASELINE")

    def test_cli_write_and_apply_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "bad.json").write_text('{"enabled":\n', encoding="utf-8")
            baseline = root / "baseline.json"

            first = self.run_checker(root, "--all", "--write-baseline", str(baseline))
            self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
            self.assertTrue(baseline.is_file())

            second = self.run_checker(
                root,
                "--all",
                "--baseline",
                "baseline.json",
                "--report",
                "reports/latest.md",
            )
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("基线 1", second.stdout)
            report_text = (root / "reports" / "latest.md").read_text(encoding="utf-8")
            self.assertIn("基线文件", report_text)
            self.assertIn("BASELINE", report_text)

    def test_config_required_tool_fails_in_configured_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "sample.py").write_text("print('ok')\n", encoding="utf-8")
            (root / ".check-code.toml").write_text(
                """[check-code]
strict = true
required_tools = ["definitely-missing-tool"]
""",
                encoding="utf-8",
            )
            result = self.run_checker(root, "--all")
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("必需工具：definitely-missing-tool", result.stdout)

    def test_missing_tool_has_explicit_install_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = check_code.missing_tool_result(root, "Ruff", "ruff", ["sample.py"])
            self.assertEqual(result.status, "SKIP")
            self.assertIn("pip install ruff", result.install_command)

    def test_long_file_list_is_split_into_safe_batches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            files = [f"file_{index}_{'x' * 80}.py" for index in range(20)]
            results = check_code.run_batched_command(
                "batch test",
                [sys.executable, "-c", "print('ok')"],
                files,
                root,
                max_command_chars=300,
            )
            self.assertGreater(len(results), 1)
            self.assertTrue(all(result.status == "PASS" for result in results))
            self.assertTrue(all(len(result.command) <= 300 for result in results))

    def test_full_python_check_uses_project_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            python_file = root / "sample.py"
            python_file.write_text("print('ok')\n", encoding="utf-8")
            captured: list[list[str]] = []

            def fake_run(name, command, command_root, files=(), timeout=300):
                captured.append(list(command))
                return check_code.CheckResult(name=name, status="PASS", command=check_code.command_text(command))

            with patch.object(check_code, "which_in_project", return_value="ruff.exe"):
                with patch.object(check_code, "run_command", side_effect=fake_run):
                    check_code.add_python_checks(root, ["sample.py"], [python_file], all_mode=True)

            self.assertEqual(captured[0][1:3], ["check", "."])
            self.assertEqual(captured[1][1:4], ["format", "--check", "."])

    def test_cli_reports_pending_install_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "README.md").write_text("# fixture\n", encoding="utf-8")
            (root / ".check-code.toml").write_text(
                """[check-code]
required_tools = ["definitely-missing-tool"]
""",
                encoding="utf-8",
            )
            result = self.run_checker(root, "--all")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("待确认安装", result.stdout)
            self.assertIn("definitely-missing-tool", result.stdout)

    @staticmethod
    def run_checker(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(root), *arguments],
            cwd=SKILL_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
