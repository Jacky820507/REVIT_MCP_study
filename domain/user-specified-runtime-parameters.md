---
name: user-specified-runtime-parameters
description: "使用者指定參數與避免硬編碼 SOP：當 Skill、Domain、Lessons/Lessions 文件涉及圖紙名稱、圖層名稱、Excel/CSV/PDF 名稱、校準數值、門檻值、偏移量、比例、目標類型等情境參數時觸發；這些值應由使用者指定、工具查詢或流程輸入提供，不應在 .md 規則中寫死。"
metadata:
  version: "1.0"
  updated: "2026-05-26"
  created: "2026-05-26"
  contributors:
    - "Codex"
  references: []
  related:
    - traditional-chinese-md-translation.md
    - skill-authoring-standard.md
    - frontmatter-standard.md
    - tool-capability-boundary.md
  referenced_by: []
  tags: [runtime-parameters, user-input, hardcoded, sheet-name, layer-name, excel-name, csv-name, pdf-name, calibration, 使用者指定, 避免寫死]
---

# 使用者指定參數與避免硬編碼 SOP

## 目的

當新增或修改 Skill、Domain、Lessons/Lessions 的 `.md` 文件時，若流程中出現圖紙名稱、圖層名稱、Excel/CSV/PDF 名稱、校準數值、比例、門檻值、偏移量或其他專案情境值，文件應描述「如何取得或使用該值」，而不是把單一專案的值寫死。

這類值通常會因模型、圖紙、視圖、業主標準、匯入來源或使用者當下目標而改變。把它們寫死在知識文件中，會讓 AI 在下一個專案套用錯誤假設，造成誤標註、誤上色、誤判斷或寫入錯誤資料。

## 觸發語與適用情境

看到下列語意時，先讀本 SOP 再編輯相關 `.md` 檔：

- 「指定圖紙名稱」
- 「指定圖層名稱」
- 「Excel 名稱」或「CSV 名稱」
- 「PDF 名稱」
- 「校準數值」
- 「這些東西不要寫死」
- 「由使用者指定」
- 「依據不同情況」
- `sheet name`, `layer name`, `Excel name`, `CSV name`, `PDF name`, `file name`, `calibration value`
- `threshold`, `tolerance`, `offset`, `scale`, `target type`
- 要把某次功能或經驗新增至 Skill、Domain、Lessons/Lessions，且內容含專案特定名稱或數值。

`Lessions` 視為 `Lessons` 的拼字變體，不另行詢問。

## 不應寫死的值

以下值預設視為 runtime parameters，除非它們是正式法規、公開標準或程式 API 的固定名稱：

- 圖紙名稱、圖紙編號、視圖名稱、圖層名稱。
- Excel/CSV 檔名、PDF 檔名、外部檔案名稱與匯入資料來源名稱。
- Revit 專案中的族群、類型、參數值、工作集、樓層名稱、房間名稱。
- CAD 匯入圖層、PDF 圖層、圖框名稱、標題欄名稱。
- 校準數值、比例、偏移量、容許誤差、門檻值、排序起點、目標顏色。
- 匯入來源路徑、輸出檔名、暫存資料夾、外部資料表欄位對照。
- 使用者當下選擇的範圍，例如「只處理某張圖紙」或「只上色某些元素」。

## 可以固定寫入的值

以下內容可以保留在 `.md` 規則中：

- 法規條號、官方公式、專案已確認的 SOP 步驟。
- 工具名稱、command name、API 名稱、檔案路徑、frontmatter key。
- 參數取得方式，例如「先呼叫 `get_all_sheets` 讓使用者選擇圖紙」。
- 安全預設值，但必須標示為 fallback，且允許使用者覆寫。
- 以 placeholder 表示的範例，例如 `{sheetName}`, `{layerName}`, `{excelFileName}`, `{csvFileName}`, `{pdfFileName}`, `{calibrationValue}`。

## 寫法規則

### 用 placeholder，不用專案實值

不要寫：

```markdown
使用 `A-101 平面圖` 作為目標圖紙，校準值固定為 `1.02`。
```

改寫為：

```markdown
目標圖紙由使用者指定為 `{sheetName}`；外部檔案由使用者指定為 `{sourceFileName}`；校準值由使用者指定或由校準流程產生為 `{calibrationValue}`。
```

### 寫取得流程，不寫單一答案

如果值可由模型查詢，文件應描述查詢與確認流程：

1. 先用對應工具列出候選項。
2. 將候選圖紙、圖層或類型呈現給使用者確認。
3. 使用者指定後再寫入或執行。
4. 若候選項只有一個，仍要在輸出中說明這是本次查詢結果，不是規則寫死值。

### 區分固定規則與情境參數

固定規則回答「流程怎麼做」，情境參數回答「這次用哪個值」。

| 類型 | 可以寫在 `.md` 嗎 | 寫法 |
|------|------------------|------|
| 法規公式 | 可以 | 直接記錄公式與條件 |
| 工具呼叫順序 | 可以 | 描述工具與驗證步驟 |
| 圖紙名稱 | 不應寫死 | `{sheetName}`，由使用者指定或查詢後確認 |
| 圖層名稱 | 不應寫死 | `{layerName}`，由使用者指定或查詢後確認 |
| Excel/CSV 名稱 | 不應寫死 | `{excelFileName}` / `{csvFileName}`，由使用者指定、上傳或流程輸入 |
| PDF 名稱 | 不應寫死 | `{pdfFileName}`，由使用者指定、上傳或流程輸入 |
| 校準數值 | 不應寫死 | `{calibrationValue}`，由使用者輸入或校準流程輸出 |
| 容許誤差 | 通常不寫死 | `{tolerance}`，若有安全預設需可覆寫 |

## Skill / Domain / Lessons 特別規則

### Skill

- `description` 可以提到「使用者指定圖紙、圖層、Excel/CSV/PDF 名稱、校準值」這類觸發語。
- Body 應列出需要的 input parameters，而不是填入單一專案的實際值。
- 若缺少必要 runtime parameter，Skill 應先詢問使用者或呼叫查詢工具，不應猜測。

### Domain

- Domain 應記錄 SOP 與決策規則，不應記錄某次專案的圖紙名、圖層名、Excel/CSV/PDF 名稱或校準值作為永久規則。
- 可加入「輸入參數」段落，列出 `{sheetName}`、`{layerName}`、`{excelFileName}`、`{csvFileName}`、`{pdfFileName}`、`{calibrationValue}` 等欄位。
- 若某個數值是法規常數或經審核的專案標準，需明確寫出來源與適用範圍。

### Lessons

- Lessons 可以記錄「某次因為寫死圖紙名、圖層名或外部檔名而失敗」的經驗，但避坑規則應抽象成「這些情境值由使用者指定或流程輸入」。
- 若需要保留實例，必須標示為「案例」，避免被當作下一次流程的固定輸入。
- 新 lesson 應包含：哪個值被誤寫死、造成什麼風險、未來如何改成 runtime parameter。

## 執行前檢查

在送出任何 Skill、Domain、Lessons/Lessions 的 `.md` 修改前，檢查：

- 是否出現具體圖紙名稱、圖層名稱、Excel/CSV/PDF 名稱、外部檔案名稱、類型名稱、校準值或門檻值。
- 這些值是否真的屬於法規、API 或專案固定標準。
- 若不是固定標準，是否已改成 `{placeholder}` 或「由使用者指定」。
- 是否說明值的取得方式：使用者輸入、工具查詢、校準流程、或安全 fallback。
- 是否保留必要英文觸發關鍵字，例如 `sheet name`, `layer name`, `Excel name`, `CSV name`, `PDF name`, `file name`, `calibration value`。

## 驗收標準

- `.md` 中沒有把使用者情境值誤寫成永久規則。
- 必要參數以 placeholder 或 input parameters 呈現。
- Skill 或 Domain 仍能清楚知道何時詢問使用者、何時查詢工具、何時使用 fallback。
- 範例不會被誤解為固定專案設定。
- 不影響 frontmatter、工具名稱、路徑、程式碼區塊與英文觸發關鍵字。
