/**
 * 明細表工具 — architect, mep Profile
 */

import { Tool } from "@modelcontextprotocol/sdk/types.js";

export const scheduleTools: Tool[] = [
    {
        name: "create_view_schedule",
        description: "在 Revit 中建立一個新的視圖明細表（Schedule/Quantities）。可以指定名稱、品類以及要包含的欄位。",
        inputSchema: {
            type: "object",
            properties: {
                name: { type: "string", description: "明細表名稱" },
                category: { type: "string", description: "品類名稱（如：'Walls', 'Rooms', 'Pipes'）" },
                fields: { type: "array", items: { type: "string" }, description: "欄位名稱列表" },
            },
            required: ["name"],
        },
    },
    {
        name: "list_schedules",
        description: "列出目前專案中的明細表（排除樣板、圖框修訂表）。回傳每張表的 ElementId、名稱、品類與欄位數。可用 keyword（空白分隔、每個詞都要出現在名稱，不分大小寫）與 category（品類名稱，完整比對）篩選。",
        inputSchema: {
            type: "object",
            properties: {
                keyword: { type: "string", description: "名稱關鍵字，空白分隔多個詞（且）；省略則不依名稱篩選" },
                category: { type: "string", description: "只列出這個品類的明細表（如：'牆'、'Walls'，依 Revit 介面語言）" },
            },
        },
    },
    {
        name: "batch_create_view_schedules",
        description:
            "批量建立明細表（單一 Transaction）。兩種指定方式可並用：(1) categories＋共用 fields＋nameTemplate，一次為多個品類各建一張；(2) schedules 逐張指定 name/category/fields。品類用 Revit 介面語言的名稱（如 '牆'）或 BuiltInCategory 名稱（如 'OST_Walls'）。fields 依欄位名稱比對（不分大小寫，同名時實例參數優先），對不到的列在 MissingFields。建議先 dryRun=true 預覽。",
        inputSchema: {
            type: "object",
            properties: {
                categories: { type: "array", items: { type: "string" }, description: "要各建一張明細表的品類名稱清單" },
                fields: { type: "array", items: { type: "string" }, description: "共用的欄位名稱清單（適用 categories，以及 schedules 中沒有自己 fields 的項目）" },
                nameTemplate: { type: "string", description: "名稱樣板，{category} 會換成品類名稱；預設 '{category}明細表'" },
                schedules: {
                    type: "array",
                    description: "逐張指定的明細表",
                    items: {
                        type: "object",
                        properties: {
                            category: { type: "string", description: "品類名稱" },
                            name: { type: "string", description: "明細表名稱；省略則用 nameTemplate" },
                            fields: { type: "array", items: { type: "string" }, description: "此張的欄位名稱；省略則用共用 fields" },
                        },
                        required: ["category"],
                    },
                },
                onNameConflict: { type: "string", enum: ["skip", "suffix"], description: "名稱已存在時：skip 略過（預設）、suffix 自動加 ' (2)'" },
                dryRun: { type: "boolean", description: "true 只預覽（會在回復的交易裡試建以檢查欄位），不留下任何明細表" },
            },
        },
    },
    {
        name: "add_schedule_fields",
        description:
            "批量把參數欄位加到既有明細表（附加在最後；明細表上已有的欄位不重複加）。目標明細表用 scheduleIds、scheduleNames（完整名稱）或 keyword/category 篩選指定，可並用。fields 依欄位名稱比對（不分大小寫，同名時實例參數優先），該明細表品類沒有的欄位列在 MissingFields。建議先 dryRun=true 預覽。",
        inputSchema: {
            type: "object",
            properties: {
                fields: { type: "array", items: { type: "string" }, description: "要加入的欄位名稱清單（必填）" },
                scheduleIds: { type: "array", items: { type: "number" }, description: "目標明細表 ElementId 清單" },
                scheduleNames: { type: "array", items: { type: "string" }, description: "目標明細表名稱清單（完整名稱）" },
                keyword: { type: "string", description: "依名稱關鍵字選出目標（同 list_schedules 的 keyword）" },
                category: { type: "string", description: "依品類選出目標；可與 keyword 並用（兩者皆符合才選）" },
                dryRun: { type: "boolean", description: "true 只預覽，不改明細表" },
            },
            required: ["fields"],
        },
    },
    {
        name: "set_schedule_grand_total_title",
        description:
            "批量設定明細表「排序/組成群組 → 總計 → 自訂總計標題」。title 支援佔位符：{n} = 該明細表實際列出的元素數（已套用篩選）；{first} = 逐項列「第一個欄位」第一列的編號，{first+1}、{first+2} 依此類推；{last} = 該欄最後一列的編號。例如第一欄從 45 開始、共 6 筆，'{first}+{first+1}+{first+2}+...+{last} = ' 變成 '45+46+47+...+50 = '。第一欄讀不到純整數編號時該張不寫入並回報 failed；編號不連續會在 Note 提示。目標明細表用 scheduleIds、scheduleNames（完整名稱）或 keyword/category 篩選指定，可並用。回傳每張表的舊標題與新標題；標題相同者標 unchanged。建議先 dryRun=true 預覽。",
        inputSchema: {
            type: "object",
            properties: {
                title: { type: "string", description: "自訂總計標題（必填）；可用 {n}（筆數）、{first}/{first+k}（第一欄第一列編號）、{last}（第一欄最後一列編號）" },
                scheduleIds: { type: "array", items: { type: "number" }, description: "目標明細表 ElementId 清單" },
                scheduleNames: { type: "array", items: { type: "string" }, description: "目標明細表名稱清單（完整名稱）" },
                keyword: { type: "string", description: "依名稱關鍵字選出目標（同 list_schedules 的 keyword）" },
                category: { type: "string", description: "依品類選出目標；可與 keyword 並用（兩者皆符合才選）" },
                dryRun: { type: "boolean", description: "true 只預覽，不改明細表" },
            },
            required: ["title"],
        },
    },
    {
        name: "read_schedule",
        description: "讀取單一明細表的完整表格內容（欄位標頭 + 逐格 body 資料，忠實呈現 Revit 畫面顯示的文字）。用 scheduleId 或 scheduleName 指定。",
        inputSchema: {
            type: "object",
            properties: {
                scheduleId: { type: "number", description: "明細表 ElementId（建議；由 list_schedules 取得）" },
                scheduleName: { type: "string", description: "明細表名稱（scheduleId 未提供時使用，支援部分比對）" },
                maxRows: { type: "number", description: "最多回傳的資料列數（預設 2000，避免回應過大）" },
            },
        },
    },
];
