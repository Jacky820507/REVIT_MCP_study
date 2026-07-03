---
name: traditional-chinese-md-translation
description: "Markdown 知識文件繁體中文化 SOP：當使用者要求把功能或經驗新增至 SKILL、Domain、Lessons/Lessions，或要求翻譯 .md 文件時觸發；在不影響 frontmatter、工具名稱、路徑、程式碼區塊、指令與觸發關鍵字的前提下，把可讀說明內容翻成繁體中文。"
metadata:
  version: "1.0"
  updated: "2026-05-26"
  created: "2026-05-26"
  contributors:
    - "Codex"
  references: []
  related:
    - skill-authoring-standard.md
    - frontmatter-standard.md
    - lessons.md
  referenced_by: []
  tags: [translation, markdown, 繁體中文, skill, domain, lessons, localization]
---

# Markdown 知識文件繁體中文化 SOP

## 目的

當使用者要求把某個功能、流程、避坑經驗或實作心得新增到 Skill、Domain、Lessons/Lessions，或明確要求翻譯 `.md` 檔時，新增或修改的 Markdown 知識文件應預設使用繁體中文撰寫。

此規則的目標是讓專案知識可被台灣建築、BIM 與 Revit 使用者直接閱讀，同時保留 AI Skill、Domain frontmatter、工具呼叫與程式碼範例的機器可讀性。

## 觸發語

看到下列語意時，先讀本 SOP 再編輯相關 `.md` 檔：

- 「幫我把這個功能及經驗新增至 SKILL」
- 「幫我把這個功能及經驗新增至 /Domain」
- 「幫我把這個功能及經驗新增至 /Lessons」
- 「幫我把這個功能及經驗新增至 /Lessions」
- 「把這次經驗寫進 Skill / Domain / Lessons」
- 「請將這些 `.md` 檔翻譯為繁體中文」
- 「知識文件繁中化」或「Markdown 翻繁中」

`Lessions` 視為 `Lessons` 的拼字變體，不另行詢問。

## 翻譯範圍

### 應翻譯為繁體中文

- 標題、段落、註解性說明、操作步驟。
- 表格中給人閱讀的描述欄位。
- Skill 或 Domain 的 `description` 值，但必須保留必要英文關鍵字。
- 新增的 Lessons 條目、避坑經驗、原因分析與實踐規則。
- README、Domain SOP、Skill body 中的教學或流程敘述。

### 應保留原文或原格式

- YAML frontmatter 的 key，例如 `name`, `description`, `metadata`, `version`, `updated`, `tags`。
- 檔案路徑、資料夾名稱、skill name、domain filename、工具名稱、command name。
- 程式碼區塊、inline code、API 名稱、class/method/property 名稱、環境變數。
- URL、regex、JSON key、CLI 參數、錯誤訊息原文。
- 法規條號、版本號、ElementId、GUID、commit sha、數值與單位。
- Markdown link 的 target，例如 `[文字](domain/xxx.md)` 中的 `domain/xxx.md`。

若某個英文詞本身是觸發關鍵字，例如 `fire rating`, `parking`, `clash`, `daylight`, `viewport`，可以在繁體中文後保留英文並列，避免降低 Skill 或搜尋觸發率。

## 編輯流程

1. 先確認這次任務會新增或修改哪些 `.md` 檔。
2. 先讀取相關規範：新增 Skill 時讀 `domain/skill-authoring-standard.md`，新增 Domain 時讀 `domain/frontmatter-standard.md`。
3. 可讀內容以繁體中文撰寫；必要英文術語以括號並列，例如「視埠 (viewport)」。
4. 修改完成後檢查 diff，確認沒有誤改：
   - YAML key 與檔名。
   - 工具名稱、command name、程式碼區塊。
   - Markdown link target。
   - 既有英文觸發關鍵字。
5. 若「翻譯完整性」與「功能不受影響」衝突，功能性 token 優先保留原文，並在旁邊補繁體中文說明。

## Skill / Domain / Lessons 特別規則

### Skill

- `description` 必須保留中英文觸發關鍵字。
- 不翻譯 `name`、資料夾名稱、工具名稱。
- Body 中的工作流程、限制、驗證步驟應使用繁體中文。
- 若引用 Domain，路徑保持原樣，例如 `domain/auto-dimension-workflow.md`。

### Domain

- 遵守 `domain/frontmatter-standard.md`。
- `name` 必須與檔名一致，不翻譯。
- SOP 內容、規則、例外、輸出原則使用繁體中文。
- `tags` 可加入繁體中文 tag，但不要刪掉既有英文搜尋 tag。

### Lessons

- 新條目採 append-only，不改寫或刪除既有條目。
- 條目標題與內容使用繁體中文，必要時保留英文術語。
- 每條 lesson 要包含問題情境、原因或風險、可執行的避坑規則。

## 驗收標準

- `.md` 的人讀內容已繁體中文化。
- Skill、Domain、Lessons 的觸發關鍵字仍可搜尋。
- Frontmatter、工具名稱、路徑、程式碼、連結 target 沒有被翻壞。
- diff 中沒有不相關重排或格式 churn。
