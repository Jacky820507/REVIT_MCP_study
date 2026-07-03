# domain/ 領域知識目錄

此目錄存放 BIM 工作流程 SOP、法規檢討標準和設計規範。
每個 Domain 文件是 AI 的「專業知識」，搭配 Skill 觸發機制使用。

---

## Domain ↔ Skill 對照表

### 已有對應 Skill 的 Domain（23 個）

| Domain 文件 | 對應 Skill | 觸發關鍵字 |
|------------|-----------|-----------|
| `fire-rating-check.md` | fire-safety-check | 防火、耐燃、fire rating |
| `corridor-analysis-protocol.md` | fire-safety-check | 走廊、逃生、corridor |
| `exterior-wall-opening-check.md` | fire-safety-check | 外牆開口、鄰地距離、Article 45 |
| `daylight-area-check.md` | building-compliance | 採光、daylight、§41 |
| `floor-area-review.md` | building-compliance | 容積、FAR、樓地板面積、大底防水、底板防水、地下室底版防水、地下室外牆防水毯、地下外牆防水、水平投影、FN、筏基 |
| `sanitary-fixture-review.md` | building-compliance | C-1 廠房衛浴設備、大便器、小便器、洗面盆 |
| `element-query-workflow.md` | element-query | 查詢元素、filter、上色 |
| `element-coloring-workflow.md` | element-coloring | 上色、顏色標示、color code |
| `curtain-wall-pattern.md` | curtain-wall | 帷幕牆、面板排列 |
| `facade-generation.md` | facade-generation | 立面、facade、弧形面板 |
| `smoke-exhaust-review.md` | smoke-exhaust | 排煙、排煙窗、§101、§188 |
| `auto-dimension-workflow.md` | auto-dimension | 自動標註、尺寸標註 |
| `detail-component-sync.md` | detail-component-sync | 詳圖同步、detail header |
| `sheet-viewport-management.md` | sheet-management | 圖紙、viewport、編號 |
| `stair-hidden-line-workflow.md` | stair-hidden-line | 樓梯、隱藏線、stair |
| `stair-compliance-check.md` | building-compliance | 樓梯法規、淨高、級高級深 |
| `qa-checklist.md` | qa-review | QA、驗證、檢查 |
| `parking-clearance-check.md` | parking-check | 停車場、車位淨空、parking |
| `parking-space-review.md` | parking-check | 停車位、數量、法定車位 |
| `wall-check.md` | wall-orientation-check | 牆壁方向、內外側 |
| `dependent-view-crop-workflow.md` | dependent-view-crop | 從屬視圖、分區出圖 |
| `beam-slab-alignment.md` | beam-slab-alignment | 降樑、樓板底、起始樓層偏移、結束樓層偏移 |
| `ifc-structural-native-sync.md` | ifc-structural-sync | IFC 結構同步、原生結構構架、結構柱、b/h、貼樓板底 |

### 不需要成為 Skill 的 Domain（13 個，含 README）

| Domain 文件 | 類型 | 不成為 Skill 的原因 |
|------------|------|-------------------|
| `lessons.md` | 經驗規則庫 | 知識參考文件，由 `/lessons` 指令維護，供其他 Skill 引用，不直接觸發 |
| `room-boundary.md` | 技術概念文件 | 說明 Room 邊界處理的兩種方案（Area Scheme / Offset），是 `building-compliance` Skill 的背景知識，非獨立工作流程 |
| `session-context-guard.md` | AI 內部守衛 | 定義 AI 互動安全等級（L1-L3），是所有 Skill 的通用行為規範，不由使用者觸發 |
| `tool-capability-boundary.md` | 工具邊界定義 | 定義 MCP 工具「不能做的事」（L1-L5 能力等級），防止 AI 嘗試超出能力的操作，是 meta-reference |
| `path-maintenance-qa.md` | 內部維護指南 | 目錄重構後的路徑交叉參照檢查清單，是開發者維護用文件 |
| `skill-authoring-standard.md` | Skill 品質規範 | 定義 Skill 編寫標準與品質要求，是 meta-reference |
| `traditional-chinese-md-translation.md` | Markdown 繁中化規範 | 定義知識捕捉時的 `.md` 翻譯規則，保護 frontmatter、工具名稱、路徑與英文觸發關鍵字，是 meta-reference |
| `user-specified-runtime-parameters.md` | 使用者指定參數規範 | 定義圖紙名稱、圖層名稱、Excel/CSV/PDF 名稱、校準值等情境參數不可寫死，需由使用者指定、工具查詢、上傳檔案或校準流程提供，是 meta-reference |
| `parking-auto-numbering.md` | 輔助工作流程 | 停車位自動編號邏輯，被 `parking-check` Skill 引用 |
| `revit-fill-pattern-conversion.md` | 技術參考 | 填充圖案轉換規則，被多個 Skill 引用 |
| `room-numbering-workflow.md` | room-numbering | 房間重新排序編號與批次自動編號 SOP |
| `room-surface-area-review.md` | 輔助工作流程 | 房間表面積與粉刷檢討，可被 `building-compliance` Skill 引用 |
| `README.md` | 目錄導航 | 本檔案，不是工作流程 |

---

## 貢獻新 Domain

1. 建立 `domain/你的-workflow.md`
2. 建立對應 Skill：`.agents/skills/你的-skill/SKILL.md`
3. 提 PR，格式參考現有檔案

詳見 `CONTRIBUTING.md` 和 `docs/architecture-v2-module-system.md`

## 近期 Domain 新增項目

| Domain file | Related Skill | Purpose |
|------------|---------------|---------|
| `viewport-type-scale-sync.md` | `sheet-management` | 依圖紙上已放置視圖的比例同步視埠標題類型，包含 dry-run 驗證與圖例/標題關鍵字排除。 |
| `ifc-structural-native-sync.md` | `ifc-structural-sync` | 依 IFC linked model 建立原生 StructuralFraming / StructuralColumns，含 b/h 規則、貼樓板底與 replaceExisting 驗證流程。 |
| `scaffold-takeoff.md` | `scaffold-takeoff` | 施工架數量計算規則：室外採手框周長，室內一般房間用周長乘高，樓梯/電梯類用長乘寬乘高；室外外周長可作地下室外牆防水毯周長來源，但高度需改用樓高或圖說指定防水高度。 |
