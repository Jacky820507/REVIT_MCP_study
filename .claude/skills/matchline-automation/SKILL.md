---
name: matchline-automation
description: "切圖界線自動化：在母視圖中自動識別從屬視圖裁切邊界，繪製銜接線並標註相鄰圖紙號碼。觸發條件：使用者提到銜接線、matchline、切圖界線、分區交界、接續圖號、從屬視圖邊界標註、大圖拆分。工具：create_dependent_view_matchlines、detect_sheet_matchlines、get_active_view、get_line_styles。"
metadata:
  references:
    - domain/matchline-automation.md
    - domain/dependent-view-crop-workflow.md
---

# 切圖界線自動化

執行前讀取 `domain/matchline-automation.md`。domain 與本檔衝突時以 domain 為準。

## 使用場景

- 大型平面圖拆成多張從屬視圖（A、B、C 區）分別放上不同圖紙
- 需要在母視圖標示各區交界，並標註「銜接線 接 ARA-D01010」這類文字
- 裁切框範圍變動後，要快速更新所有銜接線位置與圖號標註

## 可用工具

| 工具 | 用途 |
|------|------|
| `create_dependent_view_matchlines` | 核心指令，在目前開啟的母視圖上繪製銜接線與圖號標註 |
| `detect_sheet_matchlines` | 掃描圖紙上既有的銜接線，用於部署前定位與部署後驗證 |

`create_dependent_view_matchlines` 參數：

- `lineStyleName`：銜接線線型樣式名稱（推薦 `粗虛線`；先用 `get_line_styles` 確認實際存在）
- `textStyleName`：文字標註類型名稱（推薦 `微軟正黑體 3.5 mm`）

## 核心技術要點

1. **裁切幾何拓撲計算**：提取從屬視圖 `CropBox`，計算兩兩之間的相鄰邊界中點與方向；水平或垂直交界會自動旋轉文字以符合閱讀方向。
2. **跨版本相容**：Revit 2020 的 `TextNote` 不支援 `Comments` 參數，清理改用「文字內容關鍵字（銜接線）」比對；`DetailCurve` 在舊版可能缺少標記屬性，清理改用線型名稱比對。
3. **視覺平衡**：`VerticalAlignment.Middle` + `HorizontalTextAlignment.Center`，偏移量 1.2 ft（約 36 cm），不遮擋圖面又保持易讀。
4. **自我清理**：每次執行前先掃描並移除帶關鍵字或特定樣式的舊標註，確保無重疊、無遺留。

## 實務建議

1. **不要硬編碼 ViewId**：大型專案的元素 ID 會隨中心檔案同步變動。部署前先用 `get_active_view` 或 `detect_sheet_matchlines` 動態取得母視圖 ID。
2. **先做輕量預檢**：大規模繪製前先送一個 `get_active_view` 確認連線通暢。這個指令是 O(n²) 配對，13 個從屬視圖約 20 秒，`executeRevitTool` 已為它放寬到 120 秒 timeout。
3. **部署後驗證**：緊接著執行 `detect_sheet_matchlines` 掃描相關圖紙。某張圖紙標註數為 0，通常代表該視圖與母視圖的從屬關係尚未建立，或 CropBox 根本沒有重疊。
