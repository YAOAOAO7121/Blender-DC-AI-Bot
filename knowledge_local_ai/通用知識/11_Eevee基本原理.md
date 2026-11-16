# Eevee 基本原理
<!--
product: Blender
language: zh-Hant
applicable_versions: 4.2, 5.0（僅核對這兩個版本）
status: source-checked-summary; 尚未經教師課堂實測
source_ids: blender-4.2-eevee, blender-5.0-eevee
retrieved_date: 2026-11-02 Asia/Taipei
attribution: Blender Documentation Team
license: CC-BY-SA-4.0-or-later
license_url: https://creativecommons.org/licenses/by-sa/4.0/
modifications: 依官方英文文件自行摘述為繁體中文；未轉存圖像；不得推廣為所有 4.x/5.x 均適用
https://projects.blender.org/blender/blender-manual/raw/branch/blender-v4.2-release/manual/render/eevee/introduction.rst
https://projects.blender.org/blender/blender-manual/raw/branch/blender-v5.0-release/manual/render/eevee/introduction.rst
-->

## Eevee 是什麼（Realtime Rendering）
Eevee 著重即時互動與速度，可用於 3D 視窗預覽，也能輸出成品。

## Eevee 與 Cycles 的差異（Rasterization）
Eevee 採用光柵化，並非路徑追蹤器。它與 Cycles 可使用相同著色器節點，但不代表兩者渲染結果完全相同；比較物理精確度時需考慮 Eevee 的限制。


<!-- kb: {"id": "existing-11_Eevee基本原理-4.2", "versions": ["4.2", "5.0"], "topic": "11_渲染", "status": "source_checked", "urls": ["https://creativecommons.org/licenses/by-sa/4.0/", "https://projects.blender.org/blender/blender-manual/raw/branch/blender-v4.2-release/manual/render/eevee/introduction.rst", "https://projects.blender.org/blender/blender-manual/raw/branch/blender-v5.0-release/manual/render/eevee/introduction.rst"], "license": "CC-BY-SA-4.0-or-later", "source_ids": [], "language": "zh-Hant", "attribution": "Blender Documentation Team"} -->
