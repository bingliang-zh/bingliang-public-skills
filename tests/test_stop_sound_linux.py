"""Hermetic Linux notifier tests: python3 -m unittest discover -s tests -v."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "hooks/stop-sound/stop-sound.sh"


class StopSoundLinuxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "timeout").symlink_to("/usr/bin/timeout")
        (self.bin / "bash").symlink_to("/bin/bash")
        self.sound = self.root / 'sound with spaces "quoted".mp3'
        self.sound.write_bytes(b"fake mp3")
        self.log = self.root / "calls"
        self.env = dict(os.environ, PATH=str(self.bin), CALLS=str(self.log))

    def player(self, name, body='printf "%s\\n" "$@" >> "$CALLS"\nexit 0'):
        path = self.bin / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)

    def run_hook(self, *args):
        result = subprocess.run(
            ["/bin/bash", str(SCRIPT), *args],
            env=self.env, capture_output=True, text=True, timeout=12,
            input='{"hook_event_name":"Stop"}',
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        return result

    def test_requires_trigger(self):
        self.player("pw-play")
        self.run_hook("--sound", str(self.sound))
        self.assertFalse(self.log.exists())

    def test_each_backend_and_path_quoting(self):
        for name in ("pw-play", "ffplay", "mpv", "mpg123", "gst-play-1.0"):
            with self.subTest(player=name):
                self.player(name)
                self.run_hook("--trigger", "--sound", str(self.sound), "--extra")
                self.assertEqual(self.log.read_text().splitlines()[-1], str(self.sound))
                (self.bin / name).unlink()

    def test_failed_player_falls_back(self):
        self.player("pw-play", "exit 1")
        self.player("ffplay")
        self.run_hook("--trigger", "--sound", str(self.sound))
        self.assertIn("-autoexit", self.log.read_text())

    def test_missing_file_and_argument_fail_open(self):
        for args in (("--trigger", "--sound"), ("--trigger", "--sound", "/missing")):
            self.assertIn("stop-sound:", self.run_hook(*args).stderr)

    def test_no_player_fails_open(self):
        result = self.run_hook("--trigger", "--sound", str(self.sound))
        self.assertIn("no player succeeded", result.stderr)

    def test_missing_timeout_fails_open(self):
        (self.bin / "timeout").unlink()
        self.player("pw-play")
        self.assertIn("timeout is required", self.run_hook("--trigger", "--sound", str(self.sound)).stderr)
        self.assertFalse(self.log.exists())

    def test_hanging_player_is_bounded(self):
        self.player("pw-play", "exec /bin/sleep 30")
        self.assertIn("no player succeeded", self.run_hook("--trigger", "--sound", str(self.sound)).stderr)

    def test_relative_option_like_path(self):
        self.player("pw-play")
        relative = os.path.relpath(self.sound)
        self.run_hook("--trigger", "--sound", relative)
        self.assertEqual(self.log.read_text().strip(), os.getcwd() + "/" + relative)

    def test_default_asset(self):
        (self.bin / "dirname").symlink_to("/usr/bin/dirname")
        self.player("pw-play")
        self.run_hook("--trigger")
        self.assertEqual(self.log.read_text().strip(), str(SCRIPT.parent / "sounds/mambo.mp3"))

    def test_spec_assets_and_template(self):
        spec = json.loads((SCRIPT.parent / "spec.json").read_text())
        linux = spec["platforms"]["linux"]
        self.assertEqual(linux["params"]["timeout_seconds"], 10)
        self.assertTrue((SCRIPT.parent / linux["install_assets"][0]["source"]).is_file())
        command = linux["action"]["command_template"].format(
            codex_root=SCRIPT.parent, asset_path=SCRIPT.parent / spec["params"]["sound_asset"])
        self.player("pw-play")
        result = subprocess.run(command, shell=True, env=self.env, capture_output=True, timeout=12)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b"")


if __name__ == "__main__":
    unittest.main()
