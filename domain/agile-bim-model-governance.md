---
name: agile-bim-model-governance
description: "Agile BIM 模型治理 SOP：把 Revit 模型分成示意、規格與細部三種決策狀態，依房間／牆／門關係產生需求性能與規格提案，經 dry-run、人工確認、批次回寫及視覺／明細表 QA 後，再轉換成詳細類型。適用於 Agile BIM、規格模型、房間牆門關係、性能分類、批次參數、model governance、specification model。"
metadata:
  version: "1.0"
  updated: "2026-08-17"
  created: "2026-08-17"
  contributors:
    - "Codex"
  references:
    - "E:\\GitHub Library\\cangjie-skill\\agile-bim-pdf-distillation-zh-tw.md"
    - "https://www.revitapidocs.com/2024/263cf06b-98be-6f91-c4da-fb47d01688f3.htm"
    - "https://primer2.dynamobim.org/7_dynamo_for_revit/3-editing"
  related:
    - element-query-workflow.md
    - element-coloring-workflow.md
    - room-boundary.md
    - room-surface-area-review.md
    - finish-schedule-governance.md
    - room-numbering-workflow.md
    - tool-capability-boundary.md
    - user-specified-runtime-parameters.md
  referenced_by:
    - agile-bim-model-governance
  tags: [agile-bim, model-governance, specification-model, room-wall-door, performance, parameter-governance, QA]
---

# Agile BIM 模型治理 SOP

## 目的

本 SOP 將參考資料中的模型治理方法轉成 RevitMCP 可編排的工作流：設計初期先保留模型可變性，方案逐步確定後把需求性能寫入模型，最後才映射到詳細族群類型。

三個階段是三種決策狀態，不是必然要拆成三個 Revit 檔案：

| 狀態 | 主要決策 | 模型策略 | 主要輸出 |
|---|---|---|---|
| 示意模型 | 位置、形狀、空間是否合理 | 低細節、可變的實例參數；避免過早選定完整構造 | 平面、面積、初步 3D |
| 規格模型 | 元素必須滿足什麼性能 | 以參數保存防火、防煙、隔音、隔熱、施工面等需求；用規則批次整理 | 色彩圖、明細表、規格草案、估價基礎 |
| 細部模型 | 如何建造與表達 | 依需求性能換成高細節類型；由類型參數維持一致性 | 施工意圖、詳圖、材料與構造文件 |

參考案例使用 Revit 2024.3.x／Dynamo 2.19.x；這些版本與外部案例只能作為方法參考。規則、族群、參數與法規必須由目前專案重新定義。

## 不可變的治理原則

1. **Live state first**：本 turn 重新讀取文件、版本、Phase、視圖、樓層與目標元素；不可沿用上一輪的 ElementId 或房間清單。
2. **Read before write**：先查實際欄位、參數、族群類型與工具 schema；不可猜測本地化參數名稱。
3. **Preview before apply**：先列出提案、未分類、衝突、唯讀參數與預計影響數量。
4. **Three-state operation**：批次工作應能區分只預覽、只填空白、全面覆寫；現有工具不支援時不得假裝支援。
5. **Verify after write**：寫入後重新查詢，並用色彩覆寫、明細表或報告確認結果。
6. **Rules and results are separate**：外部 Excel／CSV／JSON 或受控設定表保存規則；Revit 保存穩定鍵與核准結果。
7. **Human owns the final decision**：自動化提供規格建議與一致性，法規適用性、設計意圖與例外仍由專業人員確認。

## 輸入參數

以下值必須由使用者指定、上傳檔案、專案設定或本 turn 的 Revit 查詢取得，不可寫死：

| 參數 | 說明 |
|---|---|
| `{documentScope}` | 目前文件、跨文件來源／目標或明確文件識別 |
| `{viewOrLevelScope}` | 視圖、樓層、選取元素或明確 ElementId 範圍 |
| `{executionMode}` | `preview`、`fill_blank`、`overwrite`；不同工具可能對應 `dryRun`／`apply` |
| `{ruleSource}` | Excel、CSV、JSON、專案資訊、既有 Domain 或使用者口述規則 |
| `{parameterMap}` | 元素類別、參數名稱、資料型別、實例／類型 scope |
| `{keyNormalization}` | 房間鍵、房間名稱、門窗符號或類型標記的正規化規則 |
| `{performanceMap}` | 需求性能集合到實際牆／門／窗類型的映射 |
| `{jurisdiction}` | 法規適用地區與版本；沒有此值時不可執行法規判定 |

若只收到「依 PDF 做一次」，先回報缺少的範圍、規則來源與目標參數，不把參考案例值當成專案標準。

## 標準工作流

### 1. 建立 live snapshot

1. 讀取專案、Revit 版本、Phase、目前視圖、樓層與文件狀態。
2. 確認 `MCP_PROFILE`、`REVIT_VERSION` 與 fork gate 允許的實際 tool 清單。
3. 取得選取元素或使用者指定範圍；沒有範圍不得默默掃描全專案。
4. 輸出 snapshot：來源、範圍、元素數量、未解析條件與版本備註。

### 2. 查詢元素與欄位

依 RevitMCP 的查詢協議：

1. `get_active_schema`：確認目前視圖有哪些類別。
2. `get_category_fields`：取得指定類別實際可查詢的欄位名稱。
3. `get_field_values`：需要值分佈時先取樣。
4. `query_elements_with_filter`：使用已確認的欄位與運算子查詢。

簡單的類別／樓層查詢可使用 `query_elements`；但任何依參數篩選的工作都必須先對齊欄位，不能自行翻譯或猜測欄位名稱。

### 3. 建立房間－牆－門關係

最小關係表應包含：

| 關係 | 建議來源 | 必須保留的欄位 |
|---|---|---|
| 關係總表 | `audit_room_wall_door_relations` | Room、邊界牆、門窗、From／To、Host Wall、`confirmed`／`inferred`／`unresolved`、未分配清單 |
| 房間 | `get_rooms_by_level`、`get_room_info` | Room Id、名稱、編號、樓層、面積、中心、邊界狀態 |
| 房間－牆 | `get_room_info`、`get_wall_info`、`query_walls_by_location` | Room Id、Wall Id、牆類型、位置、邊界或推導狀態 |
| 房間－門 | `get_room_door_counts`、門元素查詢 | Door Id、Host Wall、兩側房間、Phase、方向、房間判定來源 |
| 房間－窗 | `get_room_window_counts`、窗元素查詢 | Window Id、Host Wall、主要房間、開口面積、判定來源 |
| 房間－表面 | `get_room_surface_areas` | 牆面、地坪、天花、開口扣除、估算標記、finish layers |

每筆關係使用 `confirmed`、`inferred`、`unresolved` 三種狀態。From／To 房間不是設計意圖本身；方向、族群房間計算點、Phase 與連結模型都要列入假設。

第一輪盤點優先呼叫 `audit_room_wall_door_relations`。它是唯讀工具，將 Room 邊界牆視為幾何證據；門窗的 From／To 房間視為 Revit 關係證據；只有依 Host Wall 對應到房間時標為 `inferred`。工具回傳的未分配門窗與 `unresolved` 項目必須留在報告中，不能為了產生完整表格而補猜房間。

### 4. 產生需求性能提案

需求性能是細部類型之前的中間語意層。建議以以下結構保存：

若要把房間用途或名稱轉成分類參數，先呼叫 `get_room_parameter_dictionary` 盤點實際參數，再呼叫 `preview_room_classification`。Preview 必須保留既有值、命中規則、未命中、衝突、唯讀與缺參數項目；確認後才可用 `apply_room_classification`，並選擇 `fill_blank` 或 `overwrite`。

規則檔可參考 `templates/agile-bim-room-classification.rules.example.json`；其中 `targetParameter`、`match` 與 `value` 都只是範例，必須依目前專案的參數字典與核准規則替換。

```json
{
  "input_key": "RoomKey-or-ElementId",
  "conditions": ["室內相鄰", "外牆", "高濕空間"],
  "required_performance": ["隔音", "雙面施工"],
  "proposed_value": "專案性能代碼",
  "rule_id": "project-rule-001",
  "source": "Excel / Domain / user",
  "status": "confirmed|review|blocked"
}
```

規則輸出至少要能回答：命中哪條規則、哪些資料不完整、是否有例外、是否會覆寫人工值、最後要由誰核准。

### 5. Dry-run 與三態寫入

所有批次工作都應先產出：

- 目標總數、可處理數、未分類數、衝突數。
- 缺參數、唯讀參數、型別不符、外部鍵找不到的 ElementId。
- 既有值、建議值、命中規則、填空白／覆寫判定。
- 建立、刪除、換型、解除 join 或宿主重建的高風險清單。

三態定義：

| 模式 | 行為 | 預設安全性 |
|---|---|---|
| `preview` | 只計算與報告，不寫入 | 預設模式 |
| `fill_blank` | 只寫入空白值，保留人工修改 | 方案變更後補新元素 |
| `overwrite` | 覆寫所有目標值 | 需明確確認 |

工具 schema 可能使用 `dryRun`、`apply`、`overwrite` 或其他名稱；執行前讀取實際 schema，不可將參數名稱跨工具硬套。

### 6. 寫入與細部轉換

依工作類型選擇既有工具：

- 房間編號：`renumber_rooms_by_level`，先預覽排序與衝突，再正式寫入。
- 房間 finish：`sync_room_ceiling_finish_from_ceilings`、`remap_room_finish_codes`，驗證代碼 token，禁止把 `F1` 誤改成 `F11`。
- 房高／材質／視圖樣板：優先使用對應的批次工具，保留單一交易與完整摘要。
- 一般文字參數：`modify_element_parameter` 只在元素、參數 scope 與型別已確認時使用。
- 門規格：先以 `preview_door_specifications` 依門的族群／類型／房間關係提出需求值，再由 `apply_door_specifications` 以 `fill_blank` 或 `overwrite` 寫入已確認的 String 參數；`targetScope=type` 時要把影響樘數列入人工核准。
- 門窗編號：以 `preview_door_window_numbering` 產生可重現的流水號或帶入值，確認全域／樓層／類別範圍與既有衝突後，才用 `apply_door_window_numbering` 寫入；帷幕牆門窗預設排除，不能默默混入一般門窗編號。
- 牆性能：以 `preview_wall_performance_classification` 依牆型、`WallFunction`、`WallKind`、邊界房間或實際參數產生需求性能值，再由 `apply_wall_performance_classification` 寫入 String 參數；這一層不等同詳細牆型替換。
- 詳細類型：先以 `preview_door_type_candidates` 依房間/門型證據建立「需求性能 → 實際門 FamilySymbol」候選；同一門型若影響多樘門，必須確認影響樘數與所有房間配對一致，再以 `change_element_type` 作用於核准的元素。該 preview 只讀取，不會改寫門型或參數。

任意型別的大量參數寫入若沒有單一 Transaction、型別檢查、dry-run 與完整回報，應提出新增 RevitMCP 批次工具，不以逐筆呼叫取代治理。

### 7. QA 與回報

寫入後重新查詢原範圍，並：

1. 以 `override_element_graphics` 標示通過、未分類、衝突與估算結果。
2. 用 `clear_element_override` 清理臨時覆寫，除非使用者要求保留。
3. 建立或讀取明細表，逐列核對關鍵欄位。
4. 如有 Excel／CSV 交付，輸出來源、版本、欄位映射、筆數、差異與未處理項目。

一般報告固定分成：`讀取來源`、`範圍與假設`、`規則提案`、`未分類／衝突`、`寫入結果`、`驗證結果`、`版本與工具備註`。

## PDF／Dynamo 方法對照

| 參考資料／Dynamo 概念 | RevitMCP 落地方式 | 不可超越的邊界 |
|---|---|---|
| 房間－牆－門窗關係盤點 | `audit_room_wall_door_relations` → `get_room_info`／細部查詢 | 只讀取與標記證據；不把 Host Wall 推定當成設計意圖，也不修改模型 |
| 房間分類 | 房間查詢、外部鍵對照、參數預覽／回寫 | 名稱需正規化；未知名稱不可默判 |
| 室內牆／天花生成 | 取房間邊界與裝修規則，必要時使用元素建立工具 | 沒有可靠的通用房間輪廓→天花板工具時，不自動生成 |
| 排煙分類 | 房間資料＋適用法規／專案規則，輸出分類提案 | 外部法規不可直接套用到目前專案 |
| 內牆分割 | 先做牆、門等宿主拓撲影響分析 | 沒有 split/rehost 安全工具時，不刪除重建牆 |
| 牆／區劃性能 | 房間關係→需求性能參數→色彩／明細表 QA | 需求性能先於詳細牆型 |
| 門規格與編號 | 房間、牆、門資料→規格草案→人工核准→編號治理 | From／To 不等同目的室或避難意圖 |
| 門規格工具 | `preview_door_specifications` → `apply_door_specifications` | 只寫入已確認參數；不把 From／To 自動解讀成設計意圖 |
| 門窗編號工具 | `preview_door_window_numbering` → `apply_door_window_numbering` | 先保留既有／未選取編號並阻擋碰撞；type scope 會影響同型多樘 |
| 牆性能工具 | `preview_wall_performance_classification` → `apply_wall_performance_classification` | 只保存需求性能，不自動換型、拆牆或重建宿主 |

本專案目前沒有明確的 Dynamo Player／`.dyn` 執行工具。Dynamo Primer 可作為節點、清單、參數與文件化的設計參考，但回報中不得宣稱已執行 Dynamo graph。若要加入 `.dyn` 執行，需另設計版本鎖定、輸入白名單、輸出驗證與回復策略。

## 高風險操作

以下操作不屬於一般參數治理，必須另立測試模型、備份與人工閘門：

- `delete_element`、解除／恢復 wall join。
- 連續牆分割、刪除重建牆、門等宿主重新掛接。
- 變更牆／門／窗類型，尤其是類型參數會影響多個實例時。
- 跨文件、Phase、Design Option、Group、Linked Model 的關係推導。
- 任何會改變正式圖紙、明細表、材質或視圖樣板的批次操作。

## 驗收門檻

Skill 可交接前至少要能回答：

1. 本次操作的 live snapshot 來自哪一個文件、版本、Phase、視圖與範圍？
2. 哪些結果是 Revit 實測、哪些是幾何估算、哪些是規則推導？
3. 未分類、衝突、唯讀與找不到外部鍵的元素是否完整列出？
4. 使用者確認的是填空白還是覆寫？實際寫入數是否與預覽一致？
5. 寫入後是否重新查詢並以圖、表或報告驗證？
6. 若工具不存在、版本不支援或沒有 Dynamo bridge，是否誠實停止而非改用臆測？

## 相關 SOP

- `domain/element-query-workflow.md`
- `domain/element-coloring-workflow.md`
- `domain/room-boundary.md`
- `domain/room-surface-area-review.md`
- `domain/finish-schedule-governance.md`
- `domain/room-numbering-workflow.md`
- `domain/tool-capability-boundary.md`
- `domain/user-specified-runtime-parameters.md`
