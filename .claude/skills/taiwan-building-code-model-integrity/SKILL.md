---
name: taiwan-building-code-model-integrity
description: "此 Skill 執行台灣建築法規 BIM 模型資料完整性盤點，將專案欄位、Area、樓層、構件與圖面輸入整理成可追溯的檢查報告；當使用者提及 REVIT_112、BIM 法規檢討、模型 preflight、model integrity、Law_* 欄位或要求在 Revit 進行法規資料 QA 時使用。"
---

# 台灣建築法規模型資料完整性檢查器

## 目的

在任何法規數值檢討或模型回寫前，先確認目前開啟的 Revit 文件具備可被檢討的資料。這個 Skill 編排檢查流程；實際模型狀態以當次 Revit 讀取結果為準。若使用者另外提供專案資料，先由輸入審查角色整理成可追溯的欄位 Manifest，再與 live Revit 模型比對。

本流程的 `PASS` 只表示輸入資料存在，絕不等同於「符合現行法規」。`REVIT_112.pdf` 是模型欄位與圖面操作契約，ArkiTeki 是檢索與交叉查證入口；現行法規仍以官方法規資料庫及案件適用 jurisdiction 為準。

## 使用時機

- 要開始台灣建築法規 BIM 檢討前。
- 收到使用 REVIT_112 模板的 Revit 模型，需先確認是否可進入計算階段。
- 模型要交付 IFC、審查或交由其他人接手前，需要留下資料完整性基線。
- 發現法規檢討結果可疑，需區分「模型資料缺漏」與「規則／法規判定錯誤」時。
- 使用者提供基地面積、建蔽率、容積率、停車或防火條件，要求協助填入模型欄位或說明填入理由時。

## 專案資料輸入模式

本模式處理「使用者提供的專案資料」，不把聊天內容直接當成已核准的法規值。欄位名稱、別名、模型作用域（`ProjectInformation`／`Areas`）、單位、來源要求與禁止推論寫在 `references/project-input-field-map.json`；資料結構寫在 `references/project-input-manifest.schema.json`。Area 欄位至少包含 `Law_建管-用途類組` 與 `Law_技規-法定名稱`，必須和 AreaPlan 覆蓋結果一起解讀。

### 輸入審查角色

若執行環境支援 subagent delegation，使用 `taiwan-building-code-input-reviewer` 契約處理資料整理；若不支援，主 agent 依同一契約 inline 執行。該角色只負責：

1. 將使用者文字、表格或文件資料映射到 `Law_*` 參數。
2. 正規化單位與布林／文字格式，保留原始值。
3. 依來源、適用範圍、法規版本與資料完整度標記 `ACCEPT`、`NORMALIZED`、`DERIVED`、`REVIEW`、`CONFLICT`、`MISSING` 或 `REJECT`。
4. 列出每筆填入判定邏輯與證據位置。

它不得自行從地址、用途、建築量體或其他欄位推定法定建蔽率、容積率、開挖率、停車數或防火條件；也不得直接修改 Revit。沒有來源或適用範圍不明時，維持 `REVIEW`／`MISSING`。

### Live model reviewer

若執行環境支援第二個唯讀角色，於初次稽核、工具結果可疑或進入計算前使用 `references/live-model-reviewer-subagent.md` 的契約。它不接受主 agent 摘要自證，應重新呼叫 `audit_code_inputs` 並針對佔位值、AreaPlan 的 Area 數量、類別數量、StorageType 與唯讀狀態做抽樣重讀。它只回報 `VERIFIED`、`CONTRADICTED` 或 `INCONCLUSIVE`，不判定法規合規、不寫模型。

### 與模型的關係

- Manifest 是「期望輸入／證據整理結果」，不是法律裁定，也不是已寫入模型的證明。
- `audit_code_inputs` 是「目前模型實測結果」；呼叫後以參數名稱、值、儲存型別、唯讀狀態及完整性 finding 與 Manifest 逐項比對。
- 「資料可填入」與「現行法規已確認」是兩個不同狀態；前者通過，不代表後者成立。
- 目前沒有受控回寫工具時，只產生待填入清單與差異報告；不得改用任意寫入工具代替確認流程。

## 工作流程

### 1. 建立當次來源與範圍

記錄目前文件標題、Revit 版本、規則包識別碼與呼叫時間。不得沿用上一輪的樓層、元素 ID、參數樣本或檢查結果。若沒有連線中的 Revit 文件，停止並回報，不以 PDF 或猜測代替 live state。

若使用者有提供專案資料，先建立輸入 Manifest：保留原始文字、映射後的參數名稱、標準化值、單位、來源、日期／版本、判定狀態與理由。若資料來自附件，記錄檔名與頁碼；若只有口述，來源標記為 `user-provided`，不得提升成官方證據。

### 2. 執行唯讀資料盤點

優先使用 `audit_code_inputs`，並把 `references/revit-112-model-integrity.rules.json` 的 `defaultAuditInputs` 傳入，包含 `requiredAreaParameters` 與 `checkAreaPlanContent: true`。必要時依案件調整樓層、類別或視圖名稱；調整內容要在報告的「規則包與假設」列出。第一次呼叫建議不開啟元素樣本；只有需要人工定位時才傳 `includeElementSamples: true`。

此步驟不得啟動 Transaction，也不得呼叫修改參數、建立、刪除、換型或匯出模型的工具。`includeElementSamples` 只在需要人工定位時開啟，避免大型模型回傳過多資料。

### 3. 解讀結果與停止條件

| 狀態 | 意義 | 後續行為 |
|---|---|---|
| `PASS` | 讀取到所要求的模型輸入 | 可把該項交給下一階段，但仍不能宣稱法規合規 |
| `FAIL` | 必要輸入不存在或必要類別沒有元素 | 阻止依賴該輸入的數值檢討，列出修模建議 |
| `WARNING` | 欄位存在但空白、建議樓層缺漏或非必要項目未完成 | 可在人工同意下繼續，但報告必須保留警告 |
| `UNKNOWN` | API 未檢查、名稱無法解析或外部設定尚未驗證 | 不得轉成 PASS/FAIL，也不得用推測補值 |

工具回傳的 `Gate.Status` 是機器可讀的流程閘門：

- `BLOCKED`：至少一筆 `FAIL`；不得把依賴該輸入的數值檢討送入 calculator。
- `CONDITIONAL`：沒有 `FAIL`，但仍有 `WARNING`／`UNKNOWN`；只有記錄人工決策（範圍、決策人、時間、carry-forward finding）後才能繼續。
- `READY`：本次已要求的完整性項目沒有 `FAIL`、`WARNING` 或 `UNKNOWN`；仍不代表現行法規合規。

面積圖要分兩層判斷：`NamedViews` 的關鍵字／AreaPlan 存在，只能證明圖面容器存在；`AreaPlanCoverage.AreaCount > 0` 才能證明該圖面有可交給面積計算的 Area 實例。若只有視圖沒有 Area，至少標記為 `WARNING`，不得在下游報告寫成面積已完成。

必要輸入的阻斷要依檢討項目拆開：基地面積／建蔽率／容積率／開挖率缺漏，阻斷相應比率計算；AreaPlan 無 Area，阻斷對應面積計算；IFC `UNKNOWN` 只阻斷 IFC 交付聲明，不必阻斷其他法規資料盤點。

若有任一必要項目 `FAIL`，先回報「模型尚未具備法規檢討輸入」，不要直接查條文或輸出合規結論。若只有 `WARNING`，可進入下一階段，但要把警告傳遞到最終報告。

### 4. 接續法規檢討

只有資料完整性門檻通過後，才針對明確的檢討項目查現行法規：

1. 先確認案件地區、用途、規模、申請時點與適用版本。
2. 以官方法規原文作為 SSOT。
3. 用 ArkiTeki 進行條文、關聯條次與解釋函的快速定位，保留連結與查詢日期。
4. 以 HJPLUS_Taiwan_Architect_KB 作為整理過的輔助脈絡，不把 KB 摘要取代官方原文。
5. 將條文數字拆成帶條號、單位、比較方向與適用條件的規則，才交給計算流程。

不得把 `REVIT_112.pdf` 內的欄位名稱、畫面或舊版數字直接當成現行法規。不得把 ArkiTeki 的搜尋摘要、AI 回答或使用者上傳內容當成唯一法律依據；私有模型未經同意不得上傳外部服務。

### 5. 回報格式

固定輸出：

1. `讀取來源`：文件標題、Revit 版本、規則包 ID、時間。
2. `專案輸入判定`：每個輸入欄位的原始值、目標參數、標準化值、單位、來源、決策、判定邏輯及是否與模型一致。
3. `範圍與假設`：使用的參數、樓層、類別、視圖清單及是否含樣本。
4. `完整性摘要`：PASS/FAIL/WARNING/UNKNOWN 計數、`Gate.Status`、`CanProceedToRuleReview`。
5. `阻斷矩陣`：每筆含 finding ID、阻斷的後續檢討、訊息、實測 evidence 與來源頁碼；另列可人工帶警告繼續的項目。
6. `AreaPlan 覆蓋`：每個關鍵字的 AreaPlan 數量、Area 實例數量、空內容或無法讀取的視圖。
7. `人工決策`：若帶 `WARNING`／`UNKNOWN` 繼續，記錄 `hitlDecision`、決策人、時間、範圍與 carry-forward finding；不可只寫「已確認」。
8. `法規後續`：可進入的檢討、仍需查證的官方來源、未檢查的 IFC/幾何項目。
9. `版本備註`：現行法規與工具版本必須在下一次執行重新確認。

## 工具

| 工具名稱 | 用途 |
|---|---|
| `audit_code_inputs` | 唯讀盤點專案法規參數、樓層、構件類別、指定面積/圖面視圖與 IFC 未檢查提醒 |
| `get_project_info` | 補讀 Revit 專案基本資訊 |
| `get_all_levels` | 在客製化規則包下補讀完整樓層清單 |
| `get_active_schema` | 確認目前視圖可見的類別，協助定位資料缺漏 |
| `get_category_fields` | 讀取指定類別實際參數名稱，禁止猜本地化欄位 |
| `query_elements` | 在已確認類別與範圍後取樣元素，不作法規判定 |

Live model reviewer 可使用的唯讀工具白名單與固定回報格式，見 `references/live-model-reviewer-subagent.md`。

## Reference

- `domain/taiwan-building-code-model-integrity.md`：本流程的資料完整性邊界、證據層級與結果語意。
- `references/revit-112-model-integrity.rules.json`：REVIT_112 操作契約的可版本化預設輸入。
- `references/project-input-field-map.json`：使用者專案資料到 `Law_*` 參數的欄位映射、單位與證據要求。
- `references/project-input-manifest.schema.json`：專案輸入／判定 Manifest 的資料結構。
- `references/project-input-subagent.md`：`taiwan-building-code-input-reviewer` 的角色、輸入、輸出與停止條件。
- `references/live-model-reviewer-subagent.md`：獨立重讀模型完整性的角色契約、證據欄位與矛盾處理。
