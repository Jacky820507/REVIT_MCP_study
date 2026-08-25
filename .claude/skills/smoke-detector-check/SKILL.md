---
name: smoke-detector-check
description: "消防偵煙探測器設置法規檢討：出風口距離、壁樑距、天花板貼附、區格涵蓋、探測面積五項規定檢核並於 Revit 圖面上色標示。觸發條件：使用者提到偵煙探測器、偵煙設置、探測器違規、smoke detector check、消防探測器。工具：analyze_smoke_detectors、visualize_detector_results、get_active_view。"
metadata:
  references:
    - domain/smoke-detector-check.md
---

# 消防偵煙探測器設置法規檢討

## Purpose

自動執行偵煙探測器的五項法規檢核，並在 Revit 圖面以顏色標示結果。

## Trigger

當使用者說：
- "檢查偵煙探測器"
- "偵煙設置檢討"
- "探測器有沒有違規"
- "smoke detector check"

## Workflow

1. **確認視圖** — 呼叫 `get_active_view`，確認目前為平面視圖。

2. **執行檢核** — 呼叫 `analyze_smoke_detectors`。回傳每個探測器對五條規則的判定。

3. **視覺化** — 把步驟 2 的回傳原封不動交給 `visualize_detector_results` 的 `results` 參數上色。

4. **讀取並回報**
   - 直接依步驟 2 的回傳彙整 PASS / FAIL / WARN 數量摘要
   - 提醒使用者查看 Revit 中的顏色標示（綠=通過、紅=違規、橙=缺資料警告）
   - 使用者要書面報告時再另外寫檔，路徑由使用者指定

## 五條法規（依 domain/smoke-detector-check.md）

| # | 條件 | 規範值 |
|---|------|--------|
| 1 | 距出風口（FCU/冷風機） | ≥ 1,500 mm |
| 2 | 距牆壁或樑 | ≥ 600 mm |
| 3 | 探測器下端距天花板 | ≤ 600 mm |
| 4 | 每個樑區格內探測器數 | ≥ 1 個 |
| 5 | 每個探測器負責面積 | < 4m 天花板 ≤ 150㎡；≥ 4m ≤ 75㎡ |

## 自訂關鍵字

若出風口或探測器的 Family 名稱不含預設關鍵字，用 `analyze_smoke_detectors` 的兩個參數覆蓋：

```json
{ "outletKeywords": ["冷風機", "FCU"], "detectorKeywords": ["偵煙"] }
```

## Notes

- 出風口無法找到時，條件1 標為 WARN（橙色）而非 FAIL，需人工確認。
- 區格涵蓋（條件4）是以房間為單位統計，樑高度判定閾值為 600mm。
- 2026-08-03 起 `checkSmokeDetector.js` 已移除——它只是 `analyze_smoke_detectors` + `visualize_detector_results` 兩個已註冊工具的串接加寫檔。
