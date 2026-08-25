---
name: agile-bim-model-governance
description: "管理 Revit 的示意、規格與細部模型，先讀取房間／牆／門關係，產生規則化參數與類型變更預覽，經人工確認後寫入並完成視覺化、明細表與 QA 驗證。觸發條件：Agile BIM、規格模型、示意模型、細部模型、房間牆門關係、批次參數、性能分類、model governance、specification model、room-wall-door audit、rule-based Revit workflow。"
---

# Agile BIM 模型治理

把 PDF 的三階段模型方法轉成 RevitMCP 的受控工作流：

`live state → 關係盤點 → 規則建議 → dry-run → 人工確認 → 寫入 → 視覺／明細表 QA`

本 Skill 負責編排，不把特定地區法規、某一專案的房間名稱、Excel 路徑或族群名稱寫死在流程中。

## Operating Contract

1. **Live state first**：每次執行都重新查詢目前 Revit 專案、版本、文件、視圖與範圍；不可沿用上一輪的 ElementId、房間清單或計算結果。
2. **Read before write**：先取得欄位／參數實際名稱，再查詢目標元素；找不到欄位、參數或唯一範圍時停止，不猜名稱。
3. **Preview before apply**：先輸出提案、未分類、衝突、缺參數與預計影響數量；未經使用者明確確認，不修改模型。
4. **Keep decisions reversible**：參數批次採用 `preview`、`fill blank`、`overwrite` 三態。刪除、重建、解除 join、宿主重建與類型替換一律視為高風險操作，需另外確認。
5. **Verify after write**：寫入後重新讀取同一範圍，並用色彩覆寫、明細表或報告驗證；不能只以工具回傳成功表示完成。
6. **Separate rules from results**：Excel／JSON／專案設定承載規則與對照表；Revit 只保存穩定鍵與核准後的結果。

## Workflow

### 1. 定義範圍與模式

先確認：

- 目標文件、Revit 版本、Phase、樓層、視圖或明確 ElementId 範圍。
- 執行模式：`preview`、`fill_blank` 或 `overwrite`。
- 規則來源：使用者提供的 Excel／CSV／JSON、專案設定，或只做模型盤點。
- 目標是示意、規格或細部階段；若仍在方案變動，優先保持低細節與實例屬性。

若使用者只說「套用 PDF 規則」但沒有提供適用地區、專案規則或目標參數，先停在規則缺口報告，不把外部案例當成目前專案法規。

### 2. 建立 live snapshot

依需要使用：

1. `get_project_info`、`get_active_view`、`get_all_levels`、`get_all_views`。
2. `get_active_schema`、`get_category_fields`、`get_field_values`，確認目前視圖與類別的實際欄位。
3. `get_selected_elements` 或使用者指定範圍；沒有明確範圍時不得默默擴大到全專案。

輸出 snapshot：文件／版本／Phase／視圖／樓層、元素數量、範圍來源、未解析的範圍條件。

### 3. 盤點房間、牆與門窗關係

優先順序：

1. `audit_room_wall_door_relations` 先建立唯讀關係總表，確認 Room 邊界牆、門窗 From／To 房間、Host Wall 與未分配元素。
2. `get_rooms_by_level` 或 `query_elements` 取得需要深入處理的房間集合。
3. `get_room_info` 取得房間中心、邊界、面積與可用空間資料。
4. `get_wall_info`、`query_walls_by_location` 取得牆的幾何、類型與位置。
5. `get_room_door_counts`、`get_room_window_counts` 取得開口數量與明細；需要逐門判斷時再查詢門元素與其參數。
6. `get_room_surface_areas` 取得牆面、地坪、天花與開口扣除結果；凡工具標示 `EstimatedSurfaces`，報告中必須保留「估算」標記。

將每筆關係標成 `confirmed`、`inferred` 或 `unresolved`。房間名稱、From／To 房間、Room Bounding、Phase 或連結模型造成的不確定性不得靜默轉成確定規則。

### 4. 產生規則提案

先呼叫 `get_room_parameter_dictionary`，只使用回傳的實際參數 `Name`、`StorageType` 與 `IsReadOnly`；不要把 PDF、聊天或其他專案的參數名稱直接套用到目前模型。

將規則拆成：

- `input_key`：房間鍵、門窗符號、類型標記或其他穩定識別值。
- `conditions`：房間用途、相鄰房間、外部邊界、面積、高度、既有類型等。
- `proposed_value`：需求性能、finish code、房間分類、門規格草案或目標類型。
- `reason`：命中的規則、例外與資料來源。
- `confidence`：`confirmed`、`review` 或 `blocked`。

房間分類先用 `preview_room_classification` 產生逐房間的既有值、建議值、命中規則、衝突與未命中清單。只有使用者確認 preview 後，才可呼叫 `apply_room_classification`，並明確選擇 `fill_blank` 或 `overwrite`。

門規格使用 `preview_door_specifications` → `apply_door_specifications`；規則可依族群、類型、註記、From／To Room 名稱、宿主牆型或實際參數比對，`targetScope=type` 時必須回報同類型影響樘數。門窗編號使用 `preview_door_window_numbering` → `apply_door_window_numbering`，可依流水號、類型註記、類型名稱、來源參數或固定文字產生值，並阻擋既有／本次產生的編號衝突。牆性能分類使用 `preview_wall_performance_classification` → `apply_wall_performance_classification`，只寫入需求性能 String 參數，不自動換牆型；牆型替換仍需另行核准。

規則判斷可重現 PDF 第 7 章的房間分類、牆性能、門規格與編號思路，但法規內容與專案例外必須由使用者提供或由適用的 Domain SOP 定義。

### 5. Dry-run 與人工閘門

Dry-run 必須列出：

- 目標元素總數、可處理數、未分類數、衝突數。
- 參數不存在、唯讀、資料型別不符與找不到外部鍵的 ElementId。
- 既有值、建議值、命中規則、是否會被覆寫。
- 會建立、刪除、換型、解除 join 或改變宿主關係的元素。

工具參數名稱與 dry-run 行為可能因版本不同；呼叫前先讀取實際 schema，不得假設所有工具都支援相同的 `apply` 或 `dryRun` 參數。

### 6. 受控寫入

依風險選擇工具：

- 房間編號：優先 `renumber_rooms_by_level`，先 preview，再正式寫入。
- 房間 finish：優先 `sync_room_ceiling_finish_from_ceilings` 或 `remap_room_finish_codes`，確認範圍、代碼 token 與 overwrite 規則。
- 房高／樣板／材質：使用對應的批次工具，不把大量元素拆成逐筆 `modify_element_parameter`。
- 一般文字參數：只有在參數名稱、元素範圍與資料型別已確認時才使用 `modify_element_parameter`。
- 詳細類型：先用 `get_wall_types` 或類別型別查詢建立「需求性能 → 實際類型」映射，再以 `change_element_type` 作用於已核准的 ElementId 清單。

若需要任意型別（文字、整數、數值、ElementId）的全域批次寫入，而現有工具無法提供單一 Transaction、型別檢查與完整回報，停止並提出新增 MCP 工具的需求，不用逐筆猜測寫入。

### 7. 驗證與回報

寫入後：

1. 重新查詢原範圍，核對實際值與預期值。
2. 使用 `override_element_graphics` 顯示通過、未分類、衝突與估算結果；完成後以 `clear_element_override` 清理臨時覆寫，除非使用者要求保留。
3. 可建立 `create_view_schedule` 或使用既有明細表輸出逐元素驗證資料。
4. 若任務涉及修訂或差異，使用適用的 revision／Excel 輸出工具；不要把工具不存在時的報告欄位補成推測值。

回報固定包含：`scope`、`source`、`assumptions`、`proposals`、`blocked`、`writes`、`verification`、`tool/version notes`。

## PDF-to-RevitMCP Parity

| PDF／Dynamo 思路 | RevitMCP 編排 | 邊界 |
|---|---|---|
| 圖表 1：房間分類 | 房間查詢 → 外部鍵對照 → 預覽／回寫房間參數 | 不把房間名稱字串當成唯一真相；需正規化與例外報告 |
| 圖表 2／3：室內牆／天花生成 | 先取房間邊界與裝修資料；必要時使用 `create_wall`／`create_floor` | 目前沒有可靠的通用房間輪廓→天花板工具；幾何建立需明確輸入與小範圍試做 |
| 圖表 4：排煙分類 | 讀取房間資料與專案規則，產生分類提案與 QA | 外部法規案例不可直接移植；專案規則應引用適用 Domain |
| 圖表 5：內牆分割 | 先做拓撲影響評估 | 刪除／重建牆會影響門等宿主；沒有明確 split/rehost 工具時不得自動執行 |
| 圖表 6／7：牆與區劃性能 | 房間－牆關係 → 需求性能參數 → 視覺／明細表驗證 | 先保存「需求性能」，後續才映射詳細牆型 |
| 圖表 8／9：門規格與編號 | 房間／牆／門查詢 → 規格草案 → 人工核准 → 編號或參數治理 | From／To 不等於設計意圖；門方向與 Phase 要列入假設 |

本專案目前沒有明確的 Dynamo Player／`.dyn` 執行工具。Dynamo Primer 的節點與清單思路可作為規則設計參考，但不能宣稱已執行 Dynamo graph。若要直接執行 `.dyn`，應另行設計具版本、路徑、輸入與回復策略的 MCP bridge。

## Stop Conditions

停止並回報，不要自行補值的情況：

- Revit、MCP 或目標文件未連線，無法取得 live state。
- 目標樓層、視圖、房間鍵或外部資料表不唯一。
- 參數名稱、資料型別、族群類型或版本相依性未確認。
- 規則只描述外部法規，但沒有目前專案適用法規。
- 操作會刪除／重建元素、改變牆宿主或解除 join，且使用者尚未確認。
- 工具在目前 `MCP_PROFILE`、Revit 版本或 fork gate 中未註冊；不可因 README 的總數而假定工具存在。

## Reference

方法與背景 SOP：

- `domain/agile-bim-model-governance.md`
- `domain/element-query-workflow.md`
- `domain/element-coloring-workflow.md`
- `domain/room-boundary.md`
- `domain/room-surface-area-review.md`
- `domain/finish-schedule-governance.md`
- `domain/room-numbering-workflow.md`
- `domain/tool-capability-boundary.md`
- `domain/user-specified-runtime-parameters.md`

參考資料摘要：`E:\GitHub Library\cangjie-skill\agile-bim-pdf-distillation-zh-tw.md`。

## Tools

| Tool group | Tools |
|---|---|
| Live state and schema | `get_project_info`, `get_active_view`, `get_all_levels`, `get_all_views`, `get_active_schema`, `get_category_fields`, `get_field_values` |
| Rooms and relations | `audit_room_wall_door_relations`, `get_rooms_by_level`, `get_room_info`, `get_wall_info`, `query_walls_by_location`, `get_room_door_counts`, `get_room_window_counts`, `get_room_surface_areas` |
| Parameter dictionary and classification | `get_room_parameter_dictionary`, `preview_room_classification`, `apply_room_classification` |
| Door specification and numbering | `preview_door_specifications`, `apply_door_specifications`, `preview_door_window_numbering`, `apply_door_window_numbering` |
| Wall performance requirements | `preview_wall_performance_classification`, `apply_wall_performance_classification` |
| Query and write | `query_elements`, `query_elements_with_filter`, `modify_element_parameter`, `renumber_rooms_by_level`, `remap_room_finish_codes`, `sync_room_ceiling_finish_from_ceilings`, `batch_set_room_height` |
| Views and verification | `override_element_graphics`, `clear_element_override`, `create_view_schedule` |
| Detail transition | `get_wall_types`, `change_element_type` |

Always verify the currently registered tool list and input schema before calling a tool. Tool descriptions and source registration are more authoritative than memory or a previous session.
