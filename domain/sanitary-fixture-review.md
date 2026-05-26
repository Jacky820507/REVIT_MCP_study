---
name: sanitary-fixture-review
description: "C-1 廠房、工廠、倉庫衛浴設備數量快速檢核流程。適用於建築設計初期配置反覆調整時，以 Revit Room 面積快速估算大便器、小便器與洗面盆需求。"
metadata:
  version: "1.0"
  updated: "2026-05-15"
  created: "2026-05-15"
  contributors:
    - "Codex"
  references: []
  related:
    - floor-area-review
    - building-compliance
  referenced_by:
    - building-compliance
  tags: [sanitary, fixtures, C-1, factory, warehouse, bathroom, regulatory-review]
---

# C-1 廠房衛浴設備快速檢核

## 目的

此流程主要用於建築設計初期。當廠房配置、作業區、倉儲區、廁所核心、樓梯、電梯、停車空間與支援空間仍在頻繁調整時，Agent 可直接依 Revit Room 面積快速回答「目前需要多少衛浴設備？」。

此功能只回覆需求數量與計算依據，不寫入 shared parameters，也不要求設計者每次配置調整後重新建立試算表。

## 適用範圍

目前規則包：

- 建築物種類：`C-1 工廠、倉庫`
- 工具：`check_sanitary_fixture_requirements`
- 規則 ID：`C-1_FACTORY_WAREHOUSE_SANITARY_FIXTURES`
- 輸出方式：只回傳計算結果，不建立或寫入 Revit shared parameters，除非使用者另行要求。

未來若要支援其他建築物種類，應新增獨立規則。不要為了其他用途覆寫 C-1 公式。

## 面積與人數基準

以當層作業廠房樓地板淨面積計算人數：

```text
totalPopulation = ceil(netFactoryAreaM2 / 10)
```

淨面積必須扣除：

- 樓梯間與梯廳，依專案判定是否納入扣除
- 電梯間
- 防空避難室或避難空間
- 停車空間、車道與停車相關房間

第一版可用 Room 名稱或編號關鍵字判斷扣除空間。若專案使用特殊命名，應透過 `excludeKeywords` 補充扣除關鍵字。

## 建築物種類偵測

套用公式前，工具應先偵測或接受建築物種類。

可使用的判斷來源：

- 明確傳入的 `buildingType`
- 目前視圖名稱
- 樓層名稱
- 專案資訊
- 取樣的 Room 名稱

目前支援的關鍵字：

- `C-1`
- `C1`
- `工廠`
- `廠房`
- `倉庫`
- `factory`
- `warehouse`

若使用者明確提供不支援的建築物種類，應清楚回報目前規則包只支援 C-1，不要默默套用 C-1 公式。

## C-1 衛浴設備規則

男女比例預設為 `1:1`。若業主或使用者提供實際比例，應依實際比例計算。

以 C-1 廠房 `844` 人為例：

```text
malePopulation = 422
femalePopulation = 422
```

超過 100 人時：

| 設備類別 | 公式 | 844 人範例 |
|---|---:|---:|
| 男用大便器 | `1 + ceil((malePopulation - 100) / 120)` | `4` |
| 女用大便器 | `3 + ceil((femalePopulation - 100) / 30)` | `14` |
| 男用小便器 | `2 + ceil((malePopulation - 100) / 60)` | `8` |
| 洗面盆 | `ceil(totalPopulation / 15)` | `57` |

100 人以下使用 C-1 基本表：

| 總人數 | 男用大便器 | 女用大便器 | 男用小便器 |
|---:|---:|---:|---:|
| 1-24 | 1 | 1 | 1 |
| 25-49 | 1 | 2 | 1 |
| 50-100 | 1 | 3 | 2 |

100 人以下洗面盆：`ceil(totalPopulation / 10)`。

## 建議輸出格式

優先使用簡潔表格：

| 設備類別 | 計算方式 | 應設數量 |
|---|---|---:|
| 男用大便器 | `1 + ceil((male - 100) / 120)` | N |
| 女用大便器 | `3 + ceil((female - 100) / 30)` | N |
| 男用小便器 | `2 + ceil((male - 100) / 60)` | N |
| 洗面盆 | `ceil(total / 15)` | N |

同時回報：

- 使用的目前視圖或樓層
- 總面積
- 扣除面積
- 作業廠房淨面積
- 總人數
- 男女拆分
- 偵測到的建築物種類與 RuleId

## 實作注意事項

Revit tool 應回傳 `TableRow`，對應法規表欄位：

- `建築物種類`
- `大便器`
- `小便器`
- `洗面盆`
- `浴缸或淋浴`

這樣 Agent 的最終回答可直接對齊法規表，同時保留詳細計算欄位，方便設計者或審查者追溯。 
