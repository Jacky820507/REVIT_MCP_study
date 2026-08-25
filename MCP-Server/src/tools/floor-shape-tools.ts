import { Tool } from "@modelcontextprotocol/sdk/types.js";

/**
 * 樓板子元素（SlabShapeEditor）高程控制工具。
 *
 * 對應 C# 端 handler: MCP/Core/Commands/CommandExecutor.FloorShapePoints.cs
 * 對應 CommandExecutor.cs cases: get_floor_shape_points / set_floor_shape_points
 *
 * 適用情境：車道洩水、排水溝找坡、露台高低差——凡是「同一片樓板上不同位置要有不同高程」，
 * 都靠形狀編輯控制點處理，而不是拆成多片平板。
 */
export const floorShapeTools: Tool[] = [
    {
        name: "get_floor_shape_points",
        description:
            "讀取指定樓板目前的形狀編輯控制點（子元素），回傳每個頂點的 X/Y/Z（公釐，Revit 專案座標）、" +
            "是否已啟用形狀編輯、控制點與摺線數量，以及樓板範圍盒。" +
            "這是 set_floor_shape_points 的前置查詢：先看清楚現況有哪些控制點，再決定要改哪幾個。" +
            "此工具不修改模型。",
        inputSchema: {
            type: "object",
            properties: {
                floorId: {
                    type: "integer",
                    description: "樓板元素 ID（必須是 Floor，不是 Toposolid 或地形）",
                },
            },
            required: ["floorId"],
        },
    },
    {
        name: "set_floor_shape_points",
        description:
            "依 (x, y, z) 清單設定樓板子元素高程，用來把 CAD 標高值落實到 Revit 樓板上。" +
            "每個請求點會以 XY 距離比對既有控制點：容差內找得到就改該點高程；" +
            "找不到時預設新增控制點（addIfMissing=true）。" +
            "寫入採兩段式校準（先歸零讀基準、再寫差值），確保最終為絕對高程而非相對偏移；" +
            "任一點超出 acceptToleranceMm 即整批回滾，不會留下半套結果。" +
            "強烈建議先用 dryRun=true 確認比對結果與高差再實際執行。" +
            "此操作會修改 Revit 模型。",
        inputSchema: {
            type: "object",
            properties: {
                floorId: {
                    type: "integer",
                    description: "樓板元素 ID（必須是 Floor）",
                },
                points: {
                    type: "array",
                    minItems: 1,
                    description:
                        "控制點清單。x / y / z 皆為公釐，且為 Revit 專案座標（不是 CAD 的 TWD97 座標，" +
                        "來自 CAD 的座標必須先換算對位）。z 是要達成的絕對高程。",
                    items: {
                        type: "object",
                        properties: {
                            x: { type: "number", description: "X 座標（公釐）" },
                            y: { type: "number", description: "Y 座標（公釐）" },
                            z: { type: "number", description: "目標絕對高程（公釐）" },
                        },
                        required: ["x", "y", "z"],
                    },
                },
                matchToleranceMm: {
                    type: "number",
                    default: 10,
                    description:
                        "比對既有控制點的 XY 容差（公釐）。放太大會誤抓鄰近點，放太小會一直補新點。",
                },
                acceptToleranceMm: {
                    type: "number",
                    default: 2,
                    description: "驗收容差（公釐）。最終高程與目標值的偏差超過此值即整批回滾。",
                },
                addIfMissing: {
                    type: "boolean",
                    default: true,
                    description:
                        "true=比對不到既有控制點時新增控制點；false=略過該點並列入 skipped。" +
                        "XY 落在樓板範圍外的點無法新增，一律進 skipped。",
                },
                dryRun: {
                    type: "boolean",
                    default: false,
                    description:
                        "true=只回報每個點會被 modify / add / skip、目前高程與高差，完全不修改模型。",
                },
            },
            required: ["floorId", "points"],
        },
    },
    {
        name: "align_floor_shape_line_to_cad",
        description:
            "互動式將樓板形狀編輯中的子元素直線對齊到底下的 CAD 線。" +
            "呼叫後請依序在 Revit 視窗點選： (1) 樓板子元素直線，(2) CAD 目標線。" +
            "工具會刪除原 split line，依 CAD 線端點重建新的 split line；原本端點的相對高程會盡量保留。" +
            "僅支援 Revit 2024+、直線型且可刪除的 split line；自動折線請先在 Revit 轉成 split line。" +
            "整個替換在單一 Transaction 中執行，驗收失敗會自動回滾。",
        inputSchema: {
            type: "object",
            properties: {},
        },
    },
];
