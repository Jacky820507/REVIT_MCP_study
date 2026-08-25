# MCP-Server/scripts

> **這個目錄是例外，不是常態。**
>
> CLAUDE.md 的 AI Guard Rails 明訂：不要寫直接對 `ws://localhost:8964` 送 JSON 的腳本，
> 因為那會繞過 MCP 工具層——沒有工具 schema、沒有權限提示、沒有「工具呼叫資料誠實性」的約束，
> AI 也就少了一層自我檢查。

2026-08-03 的盤點結果：這個目錄原本有 59 個檔案，**其中 54 個呼叫的每一個指令都已經是註冊的 MCP 工具**，
腳本只是預先寫死的編排，AI 現在可以直接串工具做到同樣的事。那 54 個已經移除，引用它們的 domain／skill
文件也一併改成工具呼叫。

## 留下來的 5 個，以及為什麼

| 檔案 | 留下的理由 |
|---|---|
| `curtain_preview_server.js` | 本機 HTTP 伺服器，服務下面那個 HTML 給瀏覽器。它不是 Revit 指令的包裝，是給人看的 UI，工具層無法取代。 |
| `curtain_wall_preview_v3.html` | 帷幕牆排列模式的視覺化設計介面，由使用者在瀏覽器裡操作後產出設定 JSON。 |
| `run_command.js` | 通用逃生口：當 Revit DLL 已含某個 command、但 MCP 用戶端的工具清單還沒刷新時，用它送單一指令。**這是最後手段**，不是預設路徑；工具清單刷新後就該改回工具呼叫。 |
| `number_parking.js` | **真正的能力缺口**：停車位蛇形自動編號在 C# 端沒有對應 command，也沒有 MCP 工具。詳見下方待辦。 |
| `export_partition_takeoff_current.cjs` | **真正的能力缺口**：輕隔間數量 Excel 匯出在 C# 端沒有對應 command。詳見下方待辦。 |

## 待辦：把最後兩個缺口收編成正式工具

這兩支是唯一「不能只靠現有工具串起來」的腳本——它們各自帶著一段不存在於 C# 的演算法。
收編之後這個目錄就只剩瀏覽器 UI 與逃生口。

### 1. `renumber_parking_by_view`（取代 `number_parking.js`）

- **現況**：排序演算法有三份實作——`number_parking.js`、`pyRevit_Tools/.../lib/parking_numbering.py`（純 Python，74 行，可測試），以及 `ParkingNumbering.pushbutton` 的 UI 流程。C# 沒有。
- **參考實作**：`MCP/Core/Commands/CommandExecutor.RoomNumbering.cs` 的 `RenumberRoomsByLevel`（已註冊為 `renumber_rooms_by_level`）是同型別的問題，可比照其交易處理與回傳格式。
- **規格來源**：`domain/parking-auto-numbering.md`，以及 `domain/lessons.md` L-021。
- **建議參數**：`viewId`、`category`（car/motorcycle/bus）、`order`（yx/xy）、`linear`、`startNumber`、`startElementId`、`targetParameter`（預設「備註」）、`dryRun`。
- **注意**：寫入時需處理「已在群組編輯模式之外變更群組」警告，Revit 端要掛 `DismissWarningsPreprocessor`。

### 2. `export_partition_takeoff`（取代 `export_partition_takeoff_current.cjs`）

- **現況**：659 行的 Node 腳本，串 `query_elements` / `get_wall_info` / `get_wall_types` / `get_room_info` 後在 Node 端算量並寫 Excel。C# 沒有對應 command。
- **參考實作**：專案已有 C# 端 Excel 匯出的先例（`export_smoke_review_excel`、`export_revision_excel`、`export_clash_report`），且 `MCP/RevitMCP.csproj` 已引用 ClosedXML。
- **規格來源**：`domain/revit-partition-takeoff.md`（2.70 m 全高門檻、0.35 m 容差、開口扣除規則、TYPE 欄與 SUM footer）。
- **注意**：`domain/quantity-takeoff-excel.md` 定義了可稽核 Excel 的共同格式，收編時要與既有的天花／地坪／踢腳匯出保持同一套版面約定。

## 新增腳本前先想清楚

要新增檔案到這裡之前，先確認它**不是**「已註冊工具的串接」。如果是，那就不要寫腳本——直接呼叫工具。
`scripts/verify-qaqc.ps1` Phase 10 會盯著這個目錄：出現新的 WebSocket 直連腳本會跳 WARN 並要求說明理由。
