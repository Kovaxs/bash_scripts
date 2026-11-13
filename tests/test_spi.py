"""spi integration tests; fake process/tmux snapshots never touch live sessions."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STARTED = "Fri Nov 13 23:59:29 2026"


@unittest.skipUnless(shutil.which("jq") and shutil.which("column"), "jq and column required")
class SpiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        self.cache = self.root / "cache" / "spi"
        self.cache.mkdir(parents=True)
        self.snapshot = self.root / "ps"
        self.snapshot.write_text(
            f" 10 1 ttys001 {STARTED} /bin/bash\n"
            f"101 10 ttys001 {STARTED} pi\n"
            f"102 10 ?? {STARTED} /custom/bin/pi --resume\n"
            f"103 10 ?? {STARTED} node /pkg/pi-coding-agent/dist/cli.js\n"
            f"104 1 ?? {STARTED} bash -c echo pi\n"
            f"105 1 ?? {STARTED} node unrelated.js\n"
        )
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.bind(str(self.root / "tmux.sock"))
        self.addCleanup(self.sock.close)
        self.env = {
            **os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "XDG_CACHE_HOME": str(self.root / "cache"),
            "TMUX": f"{self.root / 'tmux.sock'},123,0",
            "TMUX_TMPDIR": str(self.root / "absent"),
            "SPI_PS": str(self.snapshot),
        }
        for name, content in {
            "ps": '#!/bin/bash\nwhile IFS= read -r line; do printf "%s\\n" "$line"; done < "$SPI_PS"\n',
            "tmux": '#!/bin/bash\nif [[ $1 == display-message ]]; then exit 1; fi\nprintf "dev\\t2:π:my window\\t%%7\\t10\\t/dev/ttys001\\t/project directory\\n"\n',
            "lsof": '#!/bin/bash\nprintf "p101\\nn/project directory\\n"\n',
        }.items():
            path = fake_bin / name
            path.write_text(content)
            path.chmod(0o755)

    def run_spi(self, *args):
        return subprocess.run([str(ROOT / "bin" / "spi"), *args], env=self.env,
                              text=True, capture_output=True, timeout=10)

    def register(self, pid=101, **overrides):
        data = {"pid": pid, "started": STARTED, "state": "idle", "cwd": "/actual cwd",
                "session_name": "Fix login", "session_id": "abcdefgh-1234-5678"}
        data.update(overrides)
        (self.cache / f"{pid}.json").write_text(json.dumps(data))

    def test_finds_pi_without_matching_shells_or_other_node_processes(self):
        result = self.run_spi()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line.split()[0] for line in result.stdout.splitlines()[1:]],
                         ["101", "102", "103"])
        self.assertIn("2:π:my window", result.stdout)
        self.assertIn("/project directory", result.stdout)
        self.assertIn("/reload", result.stderr)

    def test_exact_session_metadata_and_ancestry_for_headless_child(self):
        self.register()
        self.register(102, session_name="Headless child")
        result = self.run_spi()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Fix login", result.stdout)
        self.assertIn("abcdefgh", result.stdout)
        self.assertIn("/actual cwd", result.stdout)
        headless = next(line for line in result.stdout.splitlines() if line.startswith("102"))
        self.assertIn("%7", headless)
        self.assertIn("Headless child", headless)

    def test_stale_recycled_and_malformed_registry_entries_are_ignored(self):
        self.register(999)
        self.register(104, started="wrong start time")
        self.register(101, started="wrong start time", session_name="STALE NAME")
        (self.cache / "broken.json").write_text("{not json")
        result = self.run_spi()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("STALE NAME", result.stdout)
        self.assertNotIn("999", result.stdout)
        self.assertNotIn("104", result.stdout)
        self.assertIn("reload-needed", result.stdout)

    def test_registered_sdk_process_and_unnamed_session(self):
        self.register(105, session_name=None)
        result = self.run_spi()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("105", result.stdout)
        self.assertIn("(unnamed)", result.stdout)

    def test_no_instances(self):
        self.snapshot.write_text("")
        result = self.run_spi()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "No running Pi instances found.\n")

    def test_no_tmux_server(self):
        self.sock.close()
        self.env.pop("TMUX")
        result = self.run_spi()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("101", result.stdout)
        self.assertNotIn("%7", result.stdout)

    def test_session_control_characters_are_sanitized(self):
        self.register(session_name="Hello\nworld\t\x1b[31m")
        result = self.run_spi()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 4)
        self.assertNotIn("\x1b", result.stdout)
        self.assertIn("Hello world", result.stdout)

    def test_help_and_bad_arguments(self):
        self.assertIn("Usage: spi", self.run_spi("--help").stdout)
        self.assertEqual(self.run_spi("--bogus").returncode, 2)


@unittest.skipUnless(shutil.which("node"), "node required")
class SpiExtensionTests(unittest.TestCase):
    def test_lifecycle_rename_session_switch_permissions_and_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            script = r'''
import assert from "node:assert/strict";
import { readFileSync, statSync, existsSync } from "node:fs";
const source = readFileSync(process.env.SPI_EXTENSION, "utf8");
const { default: extension } = await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"));
const handlers = {};
extension({ on(event, fn) { handlers[event] = fn; } });
const file = `${process.env.XDG_CACHE_HOME}/spi/${process.pid}.json`;
assert.equal(existsSync(file), false); // Factories must not publish/start resources.
let name;
let id = "session-one";
let idle = true;
const ctx = { cwd: "/example", isIdle: () => idle, sessionManager: {
    getSessionId: () => id, getSessionName: () => name, getSessionFile: () => undefined,
} };
const emit = event => handlers[event]({}, ctx);
const data = () => JSON.parse(readFileSync(file, "utf8"));
emit("session_start");
assert.equal(data().session_id, "session-one");
assert.equal(data().state, "idle");
assert.equal(statSync(file).mode & 0o777, 0o600);
assert.equal(statSync(`${process.env.XDG_CACHE_HOME}/spi`).mode & 0o777, 0o700);
name = "Renamed session";
emit("session_info_changed");
assert.equal(data().session_name, name);
idle = false;
emit("agent_start");
assert.equal(data().state, "running");
emit("ui_prompt_start");
assert.equal(data().state, "waiting");
emit("ui_prompt_end");
assert.equal(data().state, "running");
idle = true;
emit("agent_settled");
assert.equal(data().state, "idle");
emit("session_shutdown");
assert.equal(existsSync(file), false);
id = "session-two";
emit("session_start");
assert.equal(data().session_id, id);
emit("session_shutdown");
emit("session_shutdown"); // Idempotent.
'''
            result = subprocess.run(["node", "--input-type=module"], input=script,
                                    text=True, capture_output=True, timeout=15,
                                    env={**os.environ, "XDG_CACHE_HOME": directory,
                                         "SPI_EXTENSION": str(ROOT / "pi-extensions" / "spi.js")})
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
