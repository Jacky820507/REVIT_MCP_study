---
name: fill-pattern-conversion
description: "填滿圖案轉換：將製圖樣式（Drafting）填滿範圍轉換為模型樣式（Model），解決圖紙旋轉時紋理方向不跟著轉的問題。觸發條件：使用者提到填滿圖案、fill pattern、製圖樣式、模型樣式、drafting to model、旋轉視圖紋理方向、剖面線方向不對、視埠旋轉。工具：convert_drafting_to_model_pattern、auto_convert_rotated_viewport_patterns。"
metadata:
  references:
    - domain/revit-fill-pattern-conversion.md
---

# 填滿圖案轉換（Drafting → Model）

執行前讀取 `domain/revit-fill-pattern-conversion.md`。domain 與本檔衝突時以 domain 為準。

## 問題

Revit 的製圖樣式（Drafting）填滿圖案，在視圖旋轉放上圖紙時方向不會跟著旋轉，導致剖面線／地坪紋理方向錯誤。轉成模型樣式（Model）後方向會跟著視圖走，但間距要依視圖比例換算才能維持視覺尺寸一致。

## 可用工具

| 工具 | 用途 |
|------|------|
| `convert_drafting_to_model_pattern` | 轉換指定的填滿圖案 |
| `auto_convert_rotated_viewport_patterns` | 掃描專案中所有旋轉的視埠，批次轉換 |

## 邏輯要點

1. **視圖比例偵測**：工具自動讀取視圖比例。
2. **間距換算**：`FillGrid.Offset` 與 `Shift` 乘以比例尺數值，維持視覺尺寸一致。
3. **旋轉屬性偵測**：除了 `Viewport.Rotation` 列舉，額外核對 `VIEWPORT_ATTR_ORIENTATION_ON_SHEET` 參數——Revit 內部這兩個屬性的回報並不一致。
4. **群組保護**：偵測到 `GroupId` 時主動略過，避免為了轉換而強制解除群組破壞模型結構。
5. **合規命名**：名稱禁止包含冒號 `:`，自動替換為 `_`，否則 API 會擲例外。

## 注意

先在少量視埠上確認轉換結果，再對全案批次執行——轉換會建立新的模型填滿樣式，大量產生後不易回頭清理。
