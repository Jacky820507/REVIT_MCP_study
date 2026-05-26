---
name: building-compliance
description: "建築法規與設計初期快速檢討。當使用者需要採光、容積/樓地板面積、停車、樓梯，或 C-1 廠房/工廠/倉庫衛浴設備數量檢核時使用；觸發語包含 C-1 廠房衛浴設備、大便器、小便器、洗面盆、廠房、倉庫、配置調整、法規檢討、regulatory review。可用工具包含 get_room_daylight_info、get_rooms_by_level、query_elements_with_filter、check_sanitary_fixture_requirements。"
---

# 建築法規檢討

本 Skill 用於建築設計初期的快速法規檢核。設計仍在變動時，優先從 Revit 模型讀取房間、樓層與元素資料，快速回覆檢核結果；除非使用者明確要求，不要寫入參數或修改模型。

## 基本流程

1. 確認使用者要檢討的範圍，例如目前視圖、樓層、房間或指定建築物種類。
2. 透過 RevitMCP 工具讀取 Room 或元素資料，不要求使用者手動整理面積。
3. 套用對應的 Domain 規則。
4. 回覆簡潔表格，包含假設、扣除面積、計算方式與應設數量。
5. 未經使用者要求，不建立 shared parameters、不寫入 Revit 參數、不修改模型。

## 衛浴設備數量檢核

當使用者詢問 C-1 廠房、工廠、倉庫的衛浴設備數量，或提到大便器、小便器、洗面盆、配置調整、廁所數量是否足夠時，使用 `check_sanitary_fixture_requirements`。

此功能主要用於建築設計初期。當廠房配置、作業區、倉儲區、廁所核心、樓梯、電梯或停車空間仍在反覆調整時，Agent 可直接依 Revit Room 面積快速重算衛浴設備需求，協助設計者判斷配置是否大致足夠，而不需要每次手動重建試算表。

目前支援的規則：

- 規則 ID：`C-1_FACTORY_WAREHOUSE_SANITARY_FIXTURES`
- 建築物種類：`C-1 工廠、倉庫`
- 人數基準：當層作業廠房樓地板淨面積除以 `10 m2/person`
- 淨面積扣除：樓梯間、電梯間、防空避難室、停車空間；如模型命名不同，可透過 `excludeKeywords` 增加扣除關鍵字。
- 男女比例：預設 `1:1`，如業主或使用者提供實際比例，則以實際比例計算。

C-1 工廠、倉庫超過 100 人時，使用下列公式：

- 男用大便器：`1 + ceil((malePopulation - 100) / 120)`
- 女用大便器：`3 + ceil((femalePopulation - 100) / 30)`
- 男用小便器：`2 + ceil((malePopulation - 100) / 60)`
- 洗面盆：`ceil(totalPopulation / 15)`

輸出需對應法規表欄位：

- `建築物種類`
- `大便器`，需保留男用、女用與合計
- `小便器`
- `洗面盆`
- `浴缸或淋浴`

未來新增其他建築物種類時，應新增一條獨立規則，不要覆寫 C-1 公式。工具應先偵測或接受 `buildingType`，再套用對應規則，並回傳 `BuildingTypeCode`、`RuleId` 與偵測原因。

## 其他檢討

採光檢討使用 `get_room_daylight_info`。

容積與樓地板面積檢討使用 `get_rooms_by_level`，並參考 `domain/floor-area-review.md`。

停車數量與淨空檢討參考停車相關 Domain 與 parking tools。

樓梯寬度、級高級深與淨高檢討參考 `domain/stair-compliance-check.md`。

## 參考文件

- `domain/sanitary-fixture-review.md`
- `domain/floor-area-review.md`
- `domain/daylight-area-check.md`
- `domain/parking-space-review.md`
- `domain/parking-clearance-check.md`
- `domain/stair-compliance-check.md`
- `domain/lessons.md`
