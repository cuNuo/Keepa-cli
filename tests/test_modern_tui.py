"""
tests/test_modern_tui.py
文件说明：验证 prompt_toolkit 现代 TUI 的入口、补全与降级路径。
主要职责：确保现代 TUI 保持官方 CLI 风格的 REPL 交互，并复用 command service。
依赖边界：测试不启动真实终端应用，不访问真实 Keepa API。
"""

import unittest
import re
import builtins
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from keepa_cli.ui import modern_tui
from keepa_cli.ui.tui import _slash_to_command


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(value: str) -> str:
    return ANSI_RE.sub("", value)


class FakePromptSession:
    def __init__(self, lines):
        self.lines = list(lines)
        self.prompts = []

    def prompt(self, message, **kwargs):
        self.prompts.append((message, kwargs))
        if not self.lines:
            raise EOFError
        value = self.lines.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


class ModernTuiTests(unittest.TestCase):
    def test_command_catalog_groups_agent_safe_workflows(self):
        catalog = modern_tui.build_command_catalog()

        labels = {item.label for item in catalog}
        commands = {item.slash for item in catalog}
        groups = {item.group for item in catalog}

        self.assertIn("Product", labels)
        self.assertIn("Login", labels)
        self.assertIn("/product B001GZ6QEC --fixture product_B001GZ6QEC.json", commands)
        self.assertIn("/batch asins.txt --domain US --dry-run --out batch.json", commands)
        self.assertIn("/report --input batch.json --format markdown --out report.md", commands)
        self.assertIn("/token <64-char Keepa key>", commands)
        self.assertIn("Inspect", groups)
        self.assertIn("Config", groups)
        self.assertIn("Local", groups)
        self.assertIn("Operate", groups)
        self.assertTrue(all(item.service_command for item in catalog))

    def test_command_catalog_defaults_to_english_and_can_switch_to_chinese(self):
        english = modern_tui.build_command_catalog(language="en")
        chinese = modern_tui.build_command_catalog(language="zh")

        self.assertEqual(english[0].label, "Doctor")
        self.assertEqual(chinese[0].label, "诊断")

    def test_metadata_prefers_prompt_toolkit(self):
        with patch("keepa_cli.ui.modern_tui.is_prompt_tui_available", return_value=True):
            metadata = modern_tui.build_tui_metadata()

        self.assertEqual(metadata["preferred_runtime"], "prompt_toolkit")
        self.assertEqual(metadata["fallback_runtime"], "classic")
        self.assertEqual(metadata["selected_runtime"], "prompt_toolkit")
        self.assertTrue(metadata["prompt_toolkit_available"])

    def test_completion_candidates_follow_slash_prefixes(self):
        slash = modern_tui._iter_completion_candidates("/", language="en")
        product = modern_tui._iter_completion_candidates("/pro", language="en")
        fuzzy = modern_tui._iter_completion_candidates("/prd", language="en")
        config = modern_tui._iter_completion_candidates("/max", language="en")
        report = modern_tui._iter_completion_candidates("/rep", language="en")

        self.assertIn("/doctor", {item.slash for item in slash})
        self.assertIn("/capabilities", {item.slash for item in slash})
        self.assertEqual([item.service_command for item in product], ["products.get"])
        self.assertEqual([item.service_command for item in fuzzy], ["products.get"])
        self.assertEqual([item.service_command for item in config], ["config.set-max-tokens"])
        self.assertEqual([item.service_command for item in report], ["reports.build"])

    def test_completion_ignores_non_slash_text(self):
        self.assertEqual(modern_tui._iter_completion_candidates("doctor", language="en"), ())

    def test_slash_parser_supports_config_shortcuts(self):
        token_command, token_params = _slash_to_command("/token " + "A" * 64)
        login_command, login_params = _slash_to_command("/login " + "B" * 64)
        budget_command, budget_params = _slash_to_command("/max-tokens 250")
        language_command, language_params = _slash_to_command("/language zh")

        self.assertEqual(token_command, "config.set-token")
        self.assertEqual(token_params["token"], "A" * 64)
        self.assertEqual(login_command, "config.set-token")
        self.assertEqual(login_params["token"], "B" * 64)
        self.assertEqual(budget_command, "config.set-max-tokens")
        self.assertEqual(budget_params["max_tokens"], "250")
        self.assertEqual(language_command, "config.set-language")
        self.assertEqual(language_params["language"], "zh")
        self.assertEqual(modern_tui._redact_transcript_command("/login " + "B" * 64), "/login [REDACTED]")

    def test_slash_parser_supports_workflow_shortcuts(self):
        batch_command, batch_params = _slash_to_command("/batch asins.txt --domain US --dry-run")
        report_command, report_params = _slash_to_command("/report --input batch.json --format markdown")
        cache_command, cache_params = _slash_to_command("/cache --input response.json --command products.get")
        cost_command, cost_params = _slash_to_command("/cost products.get")

        self.assertEqual(batch_command, "batch.asins")
        self.assertEqual(batch_params["asin_file"], "asins.txt")
        self.assertEqual(batch_params["dry-run"], True)
        self.assertEqual(report_command, "reports.build")
        self.assertEqual(report_params["input"], "batch.json")
        self.assertEqual(cache_command, "cache.explain")
        self.assertEqual(cache_params["command"], "products.get")
        self.assertEqual(cost_command, "audit.cost")
        self.assertEqual(cost_params["target_command"], "products.get")

    def test_format_result_contains_summary_and_error_details(self):
        ok_payload = {"ok": True, "command": "doctor", "data": {"auth": {}, "offline": {}}}
        workflow_payload = {
            "ok": True,
            "command": "batch.asins",
            "data": {"task_count": 2, "estimated_tokens": 2, "dry_run": True},
        }
        error_payload = {
            "ok": False,
            "command": "config.set-token",
            "error": {"kind": "invalid_argument", "message": "token must be 64 visible ASCII characters"},
        }

        self.assertIn("[doctor] OK", modern_tui._format_result(ok_payload))
        self.assertIn("Batch   tasks=2 tokens=2", modern_tui._format_result(workflow_payload))
        self.assertIn("token must be 64", modern_tui._format_result(error_payload))

    def test_semantic_color_helpers_keep_json_clean(self):
        ok = modern_tui._colorize_summary("[doctor] OK\nAuth    missing")
        error = modern_tui._colorize_summary("[doctor] ERROR\nMessage failed")
        startup = modern_tui._colorize_startup(["Keepa CLI", "Type /", "No token. Run /login"])

        self.assertIn("\033[32m[doctor] OK", ok)
        self.assertIn("\033[31m[doctor] ERROR", error)
        self.assertIn("\033[36mKeepa CLI", startup[0])
        self.assertIn("\033[33mNo token", startup[2])

        payload = {"ok": True, "command": "doctor"}
        rendered_json = modern_tui.json.dumps(payload, ensure_ascii=False, indent=2)
        self.assertNotIn("\033[", rendered_json)

    def test_status_bar_marks_missing_auth_without_escaping_markup(self):
        rendered = modern_tui._status_bar({})

        self.assertIn("bg='#111315'", rendered)
        self.assertIn("fg='ansiyellow'", rendered)
        self.assertIn("auth:missing", rendered)

    def test_run_modern_tui_falls_back_when_prompt_toolkit_is_missing(self):
        with (
            patch("keepa_cli.ui.modern_tui.is_prompt_tui_available", return_value=False),
            patch("keepa_cli.ui.modern_tui.run_interactive_tui", return_value=0) as fallback,
        ):
            exit_code = modern_tui.run_modern_tui(env={})

        self.assertEqual(exit_code, 0)
        fallback.assert_called_once_with(env={})

    def test_prompt_loop_runs_command_without_dumping_json_by_default(self):
        session = FakePromptSession(["/doctor", "/quit"])

        with patch("builtins.print") as fake_print:
            exit_code = modern_tui._run_prompt_loop(env={}, session=session)

        rendered = "\n".join(str(call.args[0]) for call in fake_print.call_args_list if call.args)
        plain = strip_ansi(rendered)
        self.assertEqual(exit_code, 0)
        self.assertIn("kc › ", session.prompts[0][0][0][1])
        self.assertIn("$ kc /doctor", plain)
        self.assertIn("[doctor] OK", plain)
        self.assertIn("\033[32m[doctor] OK", rendered)
        self.assertIn("json: /json", plain)
        self.assertNotIn('"command": "doctor"', plain)

    def test_prompt_loop_prints_last_json_on_demand(self):
        session = FakePromptSession(["/doctor", "/json", "/quit"])

        with patch("builtins.print") as fake_print:
            exit_code = modern_tui._run_prompt_loop(env={}, session=session)

        rendered = "\n".join(str(call.args[0]) for call in fake_print.call_args_list if call.args)
        self.assertEqual(exit_code, 0)
        self.assertIn("Last JSON:", rendered)
        self.assertIn('"command": "doctor"', rendered)

    def test_prompt_loop_handles_json_before_first_command(self):
        session = FakePromptSession(["/json", "/quit"])

        with patch("builtins.print") as fake_print:
            exit_code = modern_tui._run_prompt_loop(env={}, session=session)

        rendered = "\n".join(str(call.args[0]) for call in fake_print.call_args_list if call.args)
        self.assertEqual(exit_code, 0)
        self.assertIn("No command response yet.", rendered)

    def test_prompt_loop_with_injected_session_does_not_require_prompt_toolkit(self):
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name.startswith("prompt_toolkit"):
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        session = FakePromptSession(["/doctor", "/quit"])
        with patch("builtins.__import__", side_effect=fake_import), patch("builtins.print") as fake_print:
            exit_code = modern_tui._run_prompt_loop(env={}, session=session)

        rendered = "\n".join(str(call.args[0]) for call in fake_print.call_args_list if call.args)
        self.assertEqual(exit_code, 0)
        self.assertIn("[doctor] OK", rendered)

    def test_prompt_loop_prints_help_without_running_service(self):
        session = FakePromptSession(["/help", "/quit"])

        with patch("builtins.print") as fake_print:
            exit_code = modern_tui._run_prompt_loop(env={}, session=session)

        rendered = "\n".join(str(call.args[0]) for call in fake_print.call_args_list if call.args)
        self.assertEqual(exit_code, 0)
        self.assertIn("Commands", rendered)
        self.assertIn("/product", rendered)
        self.assertIn("/max-tokens", rendered)

    def test_prompt_loop_saves_token_without_printing_secret(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            token = "A" * 64
            session = FakePromptSession([f"/token {token}", "/quit"])

            with patch("builtins.print") as fake_print:
                exit_code = modern_tui._run_prompt_loop(env={"KEEPA_CLI_CONFIG": str(config_path)}, session=session)

            rendered = "\n".join(str(call.args[0]) for call in fake_print.call_args_list if call.args)
            content = config_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn(f'api_key = "{token}"', content)
        self.assertIn("[config.set-token] OK", rendered)
        self.assertNotIn(token, rendered)

    def test_prompt_loop_saves_budget_setting(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            session = FakePromptSession(["/max-tokens 250", "/quit"])

            with patch("builtins.print") as fake_print:
                exit_code = modern_tui._run_prompt_loop(env={"KEEPA_CLI_CONFIG": str(config_path)}, session=session)

            rendered = "\n".join(str(call.args[0]) for call in fake_print.call_args_list if call.args)
            content = config_path.read_text(encoding="utf-8")

        self.assertEqual(exit_code, 0)
        self.assertIn("max_tokens_per_request = 250", content)
        self.assertIn("[config.set-max-tokens] OK", rendered)

    def test_startup_lines_hide_setup_noise_after_config(self):
        with TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                f'api_key = "{"A" * 64}"\nmax_tokens_per_request = 250\n',
                encoding="utf-8",
            )
            lines = modern_tui._startup_lines({"KEEPA_CLI_CONFIG": str(config_path)})

        rendered = "\n".join(lines)
        self.assertNotIn("/token", rendered)
        self.assertNotIn("/max-tokens", rendered)
        self.assertIn("Type / for commands", rendered)
        self.assertNotIn("/json for the last response", rendered)


if __name__ == "__main__":
    unittest.main()
