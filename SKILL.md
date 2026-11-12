---
name: osda-draw
description: OSDA 科学绘图：用毫米坐标生成可编辑的 SVG 示意图并导出 PDF/PNG，需要 3D 时调用 Blender 渲染桥接。不负责数据分析和论文写作。
---

# OSDA 科学绘图技能

三条链路，优先用 Scene Spec：

- **Scene Spec（首选）**：写 JSON → `osda_scene` 统一渲染/布局/导出/校验。
- **2D 直接调用**：`osda_vector` 生成 SVG → Inkscape 导出。
- **3D 独立调用**：`osda_render` 调 Blender 渲染 PNG。

## 何时使用

- 器件截面、能带示意、工艺流程、装置框图：Scene Spec 或 2D。
- 3D 器件透视、立体结构：`blender_asset` 元素或独立调用 3D。
- 数据图 + 示意图 + 3D 混排：Scene Spec 的 `composite` + `grid`。
- 需要在组会/答辩演示绘制过程：`progressive`；需要多光标动画：`swarm`。

**不要**用它做位图描摹、LaTeX 公式、从截图还原原始数据。

## 环境检查（每次开工先做）

```bash
python -m osda_scene --version
python -m osda_render --version
which inkscape            # Scene Spec 默认要导出 PDF/PNG，没它就用 --formats svg 只产矢量
```

- 没有 Blender / GPU / 内网时：3D 加 `--renderer mock`，流程能跑通，但产物是占位图；
- 服务器模式需要 `OSDA_SERVER_HOST` / `OSDA_SERVER_USER`，以及密码或 SSH key；
- Inkscape 不在 PATH 时可以用 `OSDA_INKSCAPE=/path/to/inkscape` 指定。

## Scene Spec 标准流程

1. 写 `scene.json`：`version: "1.0"` + `canvas` + `elements`；只写需要的字段，其余有默认值。
2. 选布局：`free`（每个元素给 `x_mm/y_mm`）或 `grid`（给 `cell: [row, col]`）。
3. 渲染：

```bash
# 有 Inkscape：PDF + PNG + SVG 全出
python -m osda_scene --spec scene.json --outdir outputs/fig
# 没 Inkscape：只出矢量 SVG
python -m osda_scene --spec scene.json --outdir outputs/fig --formats svg
```

4. 读 `summary.json`：
   - `degraded` 是否为 true / `assets[].renderer` 是否有 `"mock"`（mock 即占位图，不能当真实渲染交付）；
   - `report.errors` 是否为空、`report.warnings` 是否需要注意；
   - 文本缺失在 `checks.text_missing`，不在顶层。
5. 需要构建动画：spec 里 `progressive.enabled = true`；需要多光标演示：`swarm.enabled = true`。
6. 交付前确认：字号 ≥ 期刊下限、线宽 ≥ 0.5 pt、PNG DPI 达标、PDF 字体已嵌入。

## 2D 直接调用（Spec 表达不了时）

1. 选画布：单栏 85 mm（本仓库示例用 80 mm）、双栏 180 mm；高度按内容定。
2. 用 `Canvas` 画：坐标单位 mm，字号/线宽用 pt；化学式用 `runs` 写下标。
3. `save()` → `export()` 出 PDF + PNG；`verify_svg()` 自检字号、线宽、文本、画布。
4. 多面板：子图按**最终物理尺寸**出图，合并时给嵌入 SVG 的 `id` 加前缀。

## 3D 标准流程

1. **写构建脚本**：以 `templates/build_3d.py` 为模板，必须满足四条约定（保存 `scene.blend`、正交相机、`film_transparent`、写 `meta.json`）。
2. **先 mock 联调排版**（可选，推荐）：`--renderer mock` 确认下游能读到图和 meta。
3. **正式渲染**：

```bash
python -m osda_render --script assets/fet3d/build.py --outdir assets/fet3d/render --resolution 2008x1417 --samples 256
```

4. **读 `summary.json`**：确认 `renderer_used` 是 `server` 还是 `local`，不要向用户谎称用了 GPU。
5. **审核（可选，需用户明确同意）**：

```bash
python -m osda_render --script ... --reviewer glm
```

默认不审核。审核不通过只代表"观感有硬伤"，不代表图片不能用；要如实转述 issues，不要自行美化。

6. **回填矢量图**：按 `meta.json` 的 `target_width_mm` 定宽，高度由像素宽高比推导。

## 硬性约束

- 不要在仓库或脚本里写任何真实密钥、内网地址；
- 不要把 `--renderer mock` 的产物当真实渲染交付；
- 不要用审核结论代替期刊合规检查（字号、线宽、DPI 另做）；
- 不要修改 `meta.json` 契约字段名，下游依赖它；
- `swarm` 是构建回放演示，不是渲染方式，也不影响静态产物——向用户说明时不要混淆。
