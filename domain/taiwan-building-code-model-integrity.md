---
name: taiwan-building-code-model-integrity
description: "台灣建築法規 BIM 模型資料完整性 SOP：檢查法規輸入欄位、樓層、構件與圖面資料是否可追溯，並把 REVIT_112、ArkiTeki、HJPLUS 與官方法規分成不同證據層級。"
metadata:
  version: "0.2"
  updated: "2026-08-19"
  created: "2026-08-18"
  contributors:
    - "Codex"
  references:
    - "E:\\設計資料\\REVIT_112.pdf"
    - "https://arkiteki.com/"
    - "https://github.com/Jacky820507/HJPLUS_Taiwan_Architect_KB"
    - "https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode=D0070115"
  related: []
  referenced_by:
    - taiwan-building-code-model-integrity
  tags: [Taiwan, building-code, BIM, Revit, model-integrity, preflight, QA]
---

# 台灣建築法規模型資料完整性

## 核心邊界

這份 domain 只定義「能不能開始檢討」的資料治理，不定義某一年度、某一縣市或某一用途的現行法規數字。它把模型輸入完整性與法規合規判定分成兩個 gate：

1. `Model integrity gate`：確認模型中有可讀的欄位、樓層、構件與圖面證據。
2. `Current rule gate`：在案件 jurisdiction、用途、規模與申請時點明確後，重新查官方現行法規並計算。

前一 gate 通過，不代表後一 gate 通過。

## 證據層級

| 層級 | 來源 | 可以做什麼 | 不可以做什麼 |
|---|---|---|---|
| A | 官方法規與主管機關資料 | 作為現行條文、版本與法律適用的主要依據 | 不可省略案件適用條件 |
| B | ArkiTeki | 快速定位條文、關聯條次、解釋函與引用線索 | 不可把摘要或 AI 回答當唯一法源 |
| C | HJPLUS_Taiwan_Architect_KB | 提供整理脈絡、關鍵字與維護線索 | 不可取代 A 層原文 |
| D | REVIT_112.pdf | 定義模型欄位、樓層、視圖與交付操作契約 | 不可把舊版畫面或數字當現行法規 |

## 完整性檢查輸入

- 使用者專案資料先依 `project-input-field-map.json` 映射成輸入 Manifest；每筆要保留原始值、標準化值、單位、來源、日期／版本與判定理由。
- Project Information 的 `Law_*` 參數：檢查存在與是否有值，不解讀數值適法性。
- Level：檢查必要／建議名稱是否存在，保留實際名稱與標高。
- Model categories：檢查必要構件類別是否有實例，不以數量多寡推定設計合規。
- Named views：檢查 REVIT_112 約定的地籍、綠化、開挖、防火區劃與樓地板面積視圖關鍵字。
- IFC：沒有實際讀取或執行匯出設定時，一律 `UNKNOWN`。

## 專案資料填入判定

輸入資料的 `ACCEPT`／`NORMALIZED` 只表示「可列入待填入清單」；`DERIVED` 必須標明公式，`REVIEW`、`CONFLICT`、`MISSING`、`REJECT` 不得直接回寫。沒有受控回寫 API 時，流程只產出 Manifest 與 live model 差異報告，不修改 Revit。

`taiwan-building-code-input-reviewer` 只負責欄位映射、來源與差異整理，不推定法定建蔽率、容積率、開挖率、停車或防火條件，也不宣稱現行法規合規。

## 結果語意

| 結果 | 定義 |
|---|---|
| `PASS` | 當次 live model 讀到要求的資料 |
| `FAIL` | 必要資料不存在，依賴該資料的後續檢討應阻斷 |
| `WARNING` | 資料存在但空白，或建議資料缺漏；需保留人工決策 |
| `UNKNOWN` | 工具未檢查、外部設定未讀取或名稱無法解析；禁止推測 |

`(無)`、`（無）`、`<空白>`、`<無>` 與單獨 `-` 是語意佔位值，不算有效法規輸入。AreaPlan 的名稱匹配也不等於面積資料完成；只有 `AreaPlanCoverage.AreaCount > 0` 才能交給面積計算。

工具閘門另外輸出：`BLOCKED` 代表有必要 `FAIL`；`CONDITIONAL` 代表沒有 `FAIL` 但仍有 `WARNING`／`UNKNOWN`，必須記錄人工決策；`READY` 只代表本次要求的完整性檢查沒有待處理 finding，仍不代表現行法規合規。

高風險或進入計算前，應由獨立 live-model reviewer 重新讀取模型並回報 `VERIFIED`、`CONTRADICTED` 或 `INCONCLUSIVE`。主 agent 不得把自己的摘要當成第二意見。

## 維護規則

任何法規更新都應優先更新版本化 rule pack 的來源與適用條件，再由 Skill 傳入檢查器；不要為了配合新年度直接改寫 API 的法律判定。若只是模型欄位或模板改版，更新操作契約版本，並保留舊版 hash 與報告可追溯性。
