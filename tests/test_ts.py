"""Run with: python3 -m unittest discover -s tests -v

Uses real jj repositories and a fake tmux; never touches live tmux sessions.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


TS = Path(__file__).resolve().parents[1] / "bin" / "ts"
JJ = shutil.which("jj")


@unittest.skipUnless(JJ, "jj is required")
class WorkspaceLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve()
        self.repo = root / "repo"
        self.workspace = root / "repo.worktrees" / "feat-ui"
        self.log = root / "tmux.jsonl"
        fake_bin = root / "bin"
        fake_bin.mkdir()
        self.env = {
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "JJ_CONFIG": "",
            "JJ_USER": "Test",
            "JJ_EMAIL": "test@example.com",
            "TMUX": "test-client",
            "TMUX_LOG": str(self.log),
            "TEST_SESSION_EXISTS": "0",
            "TEST_WINDOWS": "",
        }
        for name, content in {
            "tmux": '''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["TMUX_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[0] == "has-session":
    sys.exit(0 if os.environ["TEST_SESSION_EXISTS"] == "1" else 1)
if args[0] == "list-windows":
    print(os.environ["TEST_WINDOWS"])
''',
            "pgrep": "#!/bin/sh\necho 123\n",
        }.items():
            path = fake_bin / name
            path.write_text(content)
            path.chmod(0o755)
        self.jj("git", "init", str(self.repo), cwd=root)
        self.workspace.parent.mkdir()
        self.jj("workspace", "add", "--name", "feat-ui", str(self.workspace))
        (self.workspace / "work.txt").write_text("unfinished work\n")
        self.jj("status", cwd=self.workspace)
        self.before = self.jj("workspace", "list").stdout

    def jj(self, *args, cwd=None):
        return subprocess.run(
            [JJ, *args], cwd=cwd or self.repo, env=self.env,
            text=True, capture_output=True, check=True,
        )

    def run_ts(self, *args, **env):
        return subprocess.run(
            ["bash", str(TS), *args], cwd=self.repo,
            env={**self.env, **env}, text=True, capture_output=True,
        )

    def ts(self, *args, **env):
        result = self.run_ts(*args, **env)
        self.assertEqual((self.workspace / "work.txt").read_text(), "unfinished work\n")
        self.assertEqual(self.jj("workspace", "list").stdout, self.before)
        return result

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_session_switches_to_existing(self):
        self.assert_ok(self.ts("--session", "--reattach", "feat-ui", TEST_SESSION_EXISTS="1"))
        self.assertIn(["switch-client", "-t", "feat-ui"], self.calls())
        self.assertFalse(any(call[0] == "new-session" for call in self.calls()))

    def test_session_attaches_outside_tmux(self):
        self.assert_ok(self.ts("--session", "--reattach", "feat-ui", TMUX="", TEST_SESSION_EXISTS="1"))
        self.assertIn(["attach-session", "-t", "feat-ui"], self.calls())

    def test_session_creates_missing_target(self):
        self.assert_ok(self.ts("--session", "--reattach", "feat-ui"))
        self.assertIn(["new-session", "-ds", "feat-ui", "-c", str(self.workspace)], self.calls())

    def test_session_starts_without_tmux_server(self):
        pgrep = Path(self.env["PATH"].split(":")[0]) / "pgrep"
        pgrep.write_text("#!/bin/sh\nexit 1\n")
        self.assert_ok(self.ts("--session", "--reattach", "feat-ui", TMUX=""))
        self.assertEqual(self.calls(), [["new-session", "-s", "feat-ui", "-c", str(self.workspace)]])

    def test_window_selects_exact_name(self):
        self.assert_ok(self.ts("--window", "--reattach", "feat-ui", TEST_WINDOWS="@1 feat-ui-other\n@2 feat-ui"))
        self.assertIn(["select-window", "-t", "@2"], self.calls())
        self.assertFalse(any(call[0] == "new-window" for call in self.calls()))

    def test_window_creates_missing_target(self):
        self.assert_ok(self.ts("--window", "--reattach", "feat-ui"))
        self.assertIn(["new-window", "-n", "feat-ui", "-c", str(self.workspace), ";", "set-window-option", "automatic-rename", "off"], self.calls())

    def test_session_accepts_tool_without_separator(self):
        self.assert_ok(self.ts("--session", "--reattach", "feat-ui", "jjui"))
        self.assertIn(["new-session", "-ds", "feat-ui", "-c", str(self.workspace), "jjui"], self.calls())

    def test_window_passes_command_arguments_unchanged(self):
        args = ["printf", "%s\\n", "two words", "*.py", "$HOME", "", "--from"]
        self.assert_ok(self.ts("--window", "--reattach", "feat-ui", "--", *args))
        self.assertIn(
            ["new-window", "-n", "feat-ui", "-c", str(self.workspace), *args,
             ";", "set-window-option", "automatic-rename", "off"], self.calls(),
        )

    def test_command_options_do_not_require_separator(self):
        self.assert_ok(self.ts("--window", "--reattach", "feat-ui", "ls", "-la"))
        call = next(call for call in self.calls() if call[0] == "new-window")
        self.assertEqual(call[5:7], ["ls", "-la"])

    def test_existing_session_does_not_restart_command(self):
        self.assert_ok(self.ts("--session", "--reattach", "feat-ui", "btop", TEST_SESSION_EXISTS="1"))
        self.assertEqual(self.calls(), [["has-session", "-t=feat-ui"], ["switch-client", "-t", "feat-ui"]])

    def test_existing_window_does_not_restart_command(self):
        self.assert_ok(self.ts("--window", "--reattach", "feat-ui", "top", TEST_WINDOWS="@2 feat-ui"))
        self.assertEqual(self.calls(), [["list-windows", "-F", "#{window_id} #{window_name}"], ["select-window", "-t", "@2"]])

    def test_fresh_server_accepts_command(self):
        pgrep = Path(self.env["PATH"].split(":")[0]) / "pgrep"
        pgrep.write_text("#!/bin/sh\nexit 1\n")
        self.assert_ok(self.ts("--session", "--reattach", "feat-ui", "--", "ls", "-la", TMUX=""))
        self.assertEqual(self.calls(), [["new-session", "-s", "feat-ui", "-c", str(self.workspace), "ls", "-la"]])

    def test_empty_separator_opens_shell(self):
        self.assert_ok(self.ts("--session", "--reattach", "feat-ui", "--"))
        self.assertIn(["new-session", "-ds", "feat-ui", "-c", str(self.workspace)], self.calls())

    def test_command_requires_workspace_before_separator(self):
        result = self.ts("--window", "--reattach", "--", "ls")
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires a workspace name", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_new_workspaces_default_to_shell(self):
        self.jj("config", "set", "--repo", 'revset-aliases."trunk()"', "root()")
        for mode in ("--session", "--window"):
            with self.subTest(mode=mode):
                name = f"new-{mode[2:]}"
                directory = self.workspace.parent / name
                self.assert_ok(self.run_ts(mode, name))
                self.assertTrue(directory.is_dir())
                if mode == "--session":
                    expected = ["new-session", "-ds", name, "-c", str(directory)]
                else:
                    expected = ["new-window", "-n", name, "-c", str(directory),
                                ";", "set-window-option", "automatic-rename", "off"]
                self.assertIn(expected, self.calls())

    def test_from_with_command_in_both_modes(self):
        self.jj("bookmark", "create", "base", "-r", "@")
        base = self.jj("log", "--no-graph", "-r", "base", "-T", "commit_id").stdout
        for mode in ("--session", "--window"):
            with self.subTest(mode=mode):
                name = f"new-{mode[2:]}"
                directory = self.workspace.parent / name
                self.assert_ok(self.run_ts(mode, name, "--from", "base", "--", "ls", "-la"))
                self.assertTrue(directory.is_dir())
                parent = self.jj("log", "--no-graph", "-r", f"{name}@-", "-T", "commit_id").stdout
                self.assertEqual(parent, base)
                if mode == "--session":
                    expected = ["new-session", "-ds", name, "-c", str(directory), "ls", "-la"]
                else:
                    expected = ["new-window", "-n", name, "-c", str(directory), "ls", "-la",
                                ";", "set-window-option", "automatic-rename", "off"]
                self.assertIn(expected, self.calls())

    def test_flag_can_follow_name(self):
        self.assert_ok(self.ts("--session", "feat-ui", "--reattach"))
        self.assertIn(["switch-client", "-t", "feat-ui"], self.calls())

    def test_from_is_incompatible(self):
        result = self.ts("--session", "--reattach", "feat-ui", "--from", "root()")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--reattach cannot be combined with --from", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_requires_existing_workspace(self):
        result = self.ts("--session", "--reattach", "missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("jj workspace not found: missing", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_requires_existing_directory(self):
        shutil.rmtree(self.workspace)
        result = subprocess.run(
            ["bash", str(TS), "--session", "--reattach", "feat-ui"],
            cwd=self.repo, env=self.env, text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("workspace directory not found:", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_window_requires_tmux(self):
        result = self.ts("--window", "--reattach", "feat-ui", TMUX="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--window must be run from inside a tmux session", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_creation_still_refuses_existing_workspace(self):
        result = self.ts("--session", "feat-ui")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("use --reattach to reopen it", result.stderr)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
