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
        name: "get_detail_components",
        description: "取得詳圖元件實例（可依族群名稱篩選）。",
        inputSchema: {
            type: "object",
            properties: {
                familyName: { type: "string", description: "族群名稱篩選" },
            },
        },
    },
    {
        name: "sync_detail_component_numbers",
        description: "自動同步詳圖元件的編號與名稱至所屬圖紙。",
        inputSchema: { type: "object", properties: {} },
    },
    {
        name: "create_detail_component_type",
        description: "建立新的詳圖元件類型（自動帶入圖紙編號與名稱）。",
        inputSchema: {
            type: "object",
            properties: {
                sheetNumber: { type: "string", description: "圖紙編號" },
                detailName: { type: "string", description: "詳圖名稱" },
                familyName: { type: "string", description: "族群名稱", default: "AE-圖號" },
            },
            required: ["sheetNumber", "detailName"],
        },
    },
];
