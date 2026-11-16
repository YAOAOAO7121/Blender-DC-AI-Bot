# AgX、曝光與顯示轉換
<!-- kb: {"id": "color50", "versions": ["5.0"], "topic": "12_影音知識與色彩管理", "status": "source_checked", "source_ids": ["color50-source"], "language": "zh-Hant", "license": "CC-BY-SA-4.0-or-later", "urls": ["https://docs.blender.org/manual/en/5.0/render/color_management/displays_views.html"], "attribution": "Blender Documentation Team", "review": "文字依來源核對；未執行 Blender GUI 實測"} -->

## AgX 為什麼讓亮部顏色變淡（View Transform）
AgX 用於將高動態範圍映射到顯示結果，高曝光色彩會降低飽和度，以模擬底片對光的反應。不要只因亮部變淡就判定貼圖遺失。

## Exposure 跟 Gamma 差在哪裡
Exposure 在色彩轉換前調整亮度，以檔位計算；Gamma 在色彩轉換後額外調整。比較兩張渲染時應一併核對這些設定與 Look。
