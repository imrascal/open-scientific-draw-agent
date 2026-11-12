# SPDX-License-Identifier: GPL-3.0-or-later
"""示例资产入口：直接复用 templates/build_3d.py，避免两份脚本漂移。

Blender 调用方式不变：
    blender --background --python examples/assets/fet3d/build.py -- <输出目录>

真正的建模/相机/灯光/meta.json 逻辑都在 templates/build_3d.py。
这里只做路径定位，再以 __main__ 方式执行它。
"""

import runpy
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[3] / "templates" / "build_3d.py"

if not TEMPLATE.is_file():
    print(f"[BUILD] 找不到模板: {TEMPLATE}", file=sys.stderr)
    raise SystemExit(2)

runpy.run_path(str(TEMPLATE), run_name="__main__")
