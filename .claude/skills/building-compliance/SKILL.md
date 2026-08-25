---
name: building-compliance
description: "建築法規與設計初期快速檢討：居室採光比（第 41 條）、容積率與樓地板面積、停車位尺寸與數量、樓梯，以及 C-1 廠房/工廠/倉庫衛浴設備數量檢核。觸發條件：使用者提到採光、daylight、容積率、FAR、樓地板面積、建蔽率、停車、parking、樓梯、C-1 廠房衛浴設備、大便器、小便器、洗面盆、廠房、倉庫、配置調整、法規檢討、送審、regulatory review。工具：get_room_daylight_info、get_rooms_by_level、query_elements_with_filter、check_sanitary_fixture_requirements。"
metadata:
  references:
    - domain/daylight-area-check.md
    - domain/floor-area-review.md
    - domain/parking-clearance-check.md
    - domain/parking-space-review.md
    - domain/sanitary-fixture-review.md
    - domain/stair-compliance-check.md
    - domain/references/building-code-tw.md
---

# 建築法規檢討

本 Skill 用於建築設計初期的快速法規檢核。設計仍在變動時，優先從 Revit 模型讀取房間、樓層與元素資料，快速回覆檢核結果。

## 基本原則

1. 先確認要檢討的範圍：目前視圖、樓層、房間，或指定的建築物種類。
2. 透過 MCP 工具讀取 Room 或元素資料，不要求使用者手動整理面積。
3. 套用對應的 domain 規則——domain 檔定義方法，模型的一般知識不算數。
4. 回覆簡潔表格，包含假設、扣除面積、計算方式與應設數量。
5. **未經使用者明確要求，不建立 shared parameters、不寫入 Revit 參數、不修改模型。**

## Sub-Workflows

### 1. 居室採光檢討（第 41 條）

執行前讀取 `domain/daylight-area-check.md`。

1. `get_room_daylight_info` → 回傳窗戶面積與居室面積
2. 計算：有效採光面積 ÷ 居室面積 ≥ 法定比例
3. 標示不合規的房間
4. 以顏色覆寫視覺化結果

**關鍵規則：**
- 住宅居室：採光面積 ≥ 居室面積的 1/8
- 只計算面向戶外的窗戶（不含室內窗）
- 有效開口從窗台到天花板量測

### 2. 容積率檢討

執行前讀取 `domain/floor-area-review.md`。

1. `get_rooms_by_level` → 逐層收集所有房間
2. 計算每層的總/淨樓地板面積
3. 與都市計畫允許容積率比對
4. 產出檢討摘要

**計算注意：**
- 免計項目：機械室、樓梯、電梯（依法規排除）
- 陽台：封閉式以 50% 計入
- 地下層：適用不同計算規則

### 3. 停車位檢討

執行前讀取 `domain/parking-space-review.md` 與 `domain/parking-clearance-check.md`。
細部流程（含自動編號）在 `parking-check` skill。

1. 查詢停車相關元素
2. 檢查標準尺寸（小型車最小 2.5m × 5.5m）
3. 檢查柱邊與牆邊淨空
4. 確認無障礙車位是否符合規定

**尺寸標準：**
- 標準車位：2500mm × 5500mm
- 無障礙車位：3500mm × 5500mm
- 車道寬度：雙向 5500mm

### 4. 衛浴設備數量檢核（C-1 廠房／工廠／倉庫）

當使用者詢問 C-1 廠房、工廠、倉庫的衛浴設備數量，或提到大便器、小便器、洗面盆、配置調整、廁所數量是否足夠時，使用 `check_sanitary_fixture_requirements`。執行前讀取 `domain/sanitary-fixture-review.md`。

此功能主要用於設計初期：當廠房配置、作業區、倉儲區、廁所核心、樓梯、電梯或停車空間仍在反覆調整時，可直接依 Revit Room 面積快速重算需求，不需要每次手動重建試算表。

目前支援的規則：

- 規則 ID：`C-1_FACTORY_WAREHOUSE_SANITARY_FIXTURES`
- 建築物種類：`C-1 工廠、倉庫`
- 人數基準：當層作業廠房樓地板淨面積除以 `10 m2/person`
- 淨面積扣除：樓梯間、電梯間、防空避難室、停車空間；如模型命名不同，可透過 `excludeKeywords` 增加扣除關鍵字
- 男女比例：預設 `1:1`，如業主或使用者提供實際比例，則以實際比例計算

C-1 工廠、倉庫超過 100 人時，使用下列公式：

- 男用大便器：`1 + ceil((malePopulation - 100) / 120)`
- 女用大便器：`3 + ceil((femalePopulation - 100) / 30)`
- 男用小便器：`2 + ceil((malePopulation - 100) / 60)`
- 洗面盆：`ceil(totalPopulation / 15)`

輸出需對應法規表欄位：`建築物種類`、`大便器`（保留男用／女用／合計）、`小便器`、`洗面盆`、`浴缸或淋浴`。

未來新增其他建築物種類時，應新增一條獨立規則，不要覆寫 C-1 公式。工具應先偵測或接受 `buildingType`，再套用對應規則，並回傳 `BuildingTypeCode`、`RuleId` 與偵測原因。

### 5. 樓梯檢討

樓梯寬度、級高級深與淨高檢討參考 `domain/stair-compliance-check.md`。

## Reference

詳見 metadata.references 所列的 domain 檔。domain 與本 skill 衝突時，**以 domain 為準**。
