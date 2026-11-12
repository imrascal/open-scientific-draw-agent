# SPDX-License-Identifier: GPL-3.0-or-later
"""防止两份 schema 副本漂移。

仓库根目录的 schema/scene.schema.json 供阅读与外部引用；
osda_scene/schema/scene.schema.json 随包安装，是运行时实际加载的那份。
手工维护两份副本，必须强制保持一致。
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "schema" / "scene.schema.json"
PACKAGED = ROOT / "osda_scene" / "schema" / "scene.schema.json"


class TestSchemaSync(unittest.TestCase):
    def test_both_copies_exist(self):
        self.assertTrue(PUBLIC.is_file(), f"缺少 {PUBLIC}")
        self.assertTrue(PACKAGED.is_file(), f"缺少 {PACKAGED}")

    def test_copies_identical(self):
        if not (PUBLIC.is_file() and PACKAGED.is_file()):
            self.skipTest("副本缺失，见上一个用例")
        self.assertEqual(
            PUBLIC.read_bytes(),
            PACKAGED.read_bytes(),
            "两份 schema 不一致：请把 schema/scene.schema.json 同步到 "
            "osda_scene/schema/scene.schema.json（或反过来）",
        )

    def test_copies_are_valid_json(self):
        for path in (PUBLIC, PACKAGED):
            if not path.is_file():
                self.skipTest("副本缺失")
            with self.subTest(path=path.name):
                json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    sys.exit(unittest.main())
