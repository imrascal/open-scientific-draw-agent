# SPDX-License-Identifier: GPL-3.0-or-later
"""3D 素材构建模板：在 Blender 内运行（不是普通 Python）。

用法（由 osda_render 调用，不要直接 python 执行）：
    blender --background --python templates/build_3d.py -- <输出目录>

必须遵守的四条约定（否则渲染桥接层无法把图贴回矢量版面）：
1. 把 scene.blend 保存到 <输出目录>/scene.blend；
2. 使用正交相机，并在 meta.json 里写清 ortho_scale_mm；
3. 打开 film_transparent，PNG 用 RGBA；
4. 在 <输出目录>/meta.json 写资产元数据。

本文件使用 GPL-3.0-or-later：它 import bpy，属于 Blender 官方定义的
"使用 Blender Python API 的脚本"，发布时必须采用 GPL 兼容许可。
"""

import json
import sys
from math import radians
from pathlib import Path

import bpy
from mathutils import Vector

# 1 个 Blender 单位 = 1 mm，方便直接按毫米建模
MM = 0.001

RESOLUTION = (1600, 1200)      # 像素
ORTHO_SCALE_MM = 46.0          # 正交相机视野宽度（mm）
TARGET_WIDTH_MM = 40.0         # 希望最终在版面上占的物理宽度


def _reset_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def _material(name: str, color: tuple[float, float, float],
              metallic: float = 0.0, roughness: float = 0.5) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def _box(name: str, size_mm: tuple[float, float, float],
         location_mm: tuple[float, float, float],
         mat: bpy.types.Material) -> bpy.types.Object:
    """按毫米尺寸建盒子。primitive_cube_add(size=2) 的半边长就是 scale。"""
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=location_mm)
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (size_mm[0] / 2, size_mm[1] / 2, size_mm[2] / 2)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if mat:
        obj.data.materials.append(mat)
    return obj


def _look_at(obj: bpy.types.Object, target: Vector) -> None:
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def build(out_dir: Path) -> None:
    _reset_scene()
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = MM

    scene.render.engine = "CYCLES"
    scene.cycles.samples = 128
    scene.render.resolution_x, scene.render.resolution_y = RESOLUTION
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    # 固定色彩变换，避免不同机器默认 AgX/Filmic 导致颜色不可复现
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"

    # --- 示例器件：衬底 / 沟道 / 两端电极，尺寸均为毫米 ---
    substrate = _material("Substrate", (0.72, 0.72, 0.74), roughness=0.55)
    channel = _material("Channel", (0.25, 0.46, 0.80), roughness=0.35)
    metal = _material("Metal", (0.95, 0.78, 0.25), metallic=1.0, roughness=0.18)

    _box("substrate", (40, 24, 2), (0, 0, -1), substrate)
    _box("channel", (20, 10, 0.6), (0, 0, 0.3), channel)
    # 电极向沟道内重叠 1 mm（中心 ±12、宽 6），保证接触而不是刚好贴面/留缝
    _box("source", (6, 10, 1.2), (-12, 0, 0.6), metal)
    _box("drain", (6, 10, 1.2), (12, 0, 0.6), metal)

    # --- 相机：正交 3/4 视角，保证尺度可换算且能看出厚度 ---
    bpy.ops.object.camera_add(location=(95, -110, 80))
    cam = bpy.context.active_object
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = ORTHO_SCALE_MM
    _look_at(cam, Vector((0, 0, 0)))
    scene.camera = cam

    # --- 灯光：太阳光 + 环境光，避免面积光在毫米尺度下能量难调 ---
    bpy.ops.object.light_add(type="SUN", location=(-40, -60, 90))
    key = bpy.context.active_object
    key.data.energy = 2.0
    key.data.angle = radians(12)
    _look_at(key, Vector((0, 0, 0)))

    bpy.ops.object.light_add(type="SUN", location=(60, 40, 60))
    fill = bpy.context.active_object
    fill.data.energy = 0.8
    fill.data.angle = radians(25)
    _look_at(fill, Vector((0, 0, 0)))

    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.9, 0.9, 0.9, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.25
    scene.world = world

    out_dir.mkdir(parents=True, exist_ok=True)
    blend_path = out_dir / "scene.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    meta = {
        "asset_id": out_dir.name,
        "resolution": list(RESOLUTION),
        "ortho_scale_mm": ORTHO_SCALE_MM,
        "transparent": True,
        "target_width_mm": TARGET_WIDTH_MM,
        "blender_version": bpy.app.version_string,
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[BUILD] written: {blend_path}")
    print(f"[BUILD] meta: {out_dir / 'meta.json'}")


def main() -> int:
    argv = sys.argv
    if "--" not in argv:
        print("[BUILD] 缺少输出目录参数：blender --background --python build_3d.py -- <out_dir>")
        return 2
    out_dir = Path(argv[argv.index("--") + 1]).resolve()
    build(out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
