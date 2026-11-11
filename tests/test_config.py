# SPDX-License-Identifier: GPL-3.0-or-later
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from osda_render.config import (ConfigError, load_config, require_review_credentials,
                                require_server_credentials)


class TestConfig(unittest.TestCase):
    def _write(self, tmp: str, text: str) -> Path:
        p = Path(tmp) / "render.toml"
        p.write_text(text, encoding="utf-8")
        return p

    def test_defaults_without_file(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_config()
        self.assertFalse(cfg.server.enabled)
        self.assertEqual(cfg.review.provider, "none")
        self.assertEqual(cfg.server.host, "")
        self.assertEqual(cfg.render.build_timeout_s, 300)

    def test_missing_explicit_file_raises(self):
        with self.assertRaises(ConfigError):
            load_config("definitely/not/here.toml")

    def test_file_values_and_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, """
[server]
enabled = true
host = "from-file"
gpu_idle_max_util = 12.5

[render]
samples_local = 8
""")
            env = {"OSDA_SERVER_HOST": "from-env"}
            with patch.dict(os.environ, env, clear=True):
                cfg = load_config(path)
            self.assertTrue(cfg.server.enabled)
            self.assertEqual(cfg.server.host, "from-env")
            self.assertEqual(cfg.server.gpu_idle_max_util, 12.5)
            self.assertEqual(cfg.render.samples_local, 8)

    def test_unknown_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "[server]\nnot_a_key = 1\n")
            with patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(ConfigError):
                    load_config(path)

    def test_server_credentials_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "[server]\nenabled = true\n")
            with patch.dict(os.environ, {}, clear=True):
                cfg = load_config(path)
        with self.assertRaises(ConfigError) as ctx:
            require_server_credentials(cfg)
        self.assertIn("host", str(ctx.exception))

    def test_review_key_has_no_default(self):
        with patch.dict(os.environ, {"OSDA_REVIEWER": "glm"}, clear=True):
            cfg = load_config()
        with self.assertRaises(ConfigError):
            require_review_credentials(cfg)


if __name__ == "__main__":
    unittest.main()
