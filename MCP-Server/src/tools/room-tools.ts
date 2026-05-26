/**
 * 房間/法規檢討工具 — architect, fire-safety Profile
 */

import { Tool } from "@modelcontextprotocol/sdk/types.js";

export const roomTools: Tool[] = [
    {
        name: "get_room_info",
        description: "取得房間詳細資訊，包含中心點座標和邊界範圍。",
        inputSchema: {
            type: "object",
            properties: {
                roomId: { type: "number", description: "房間 Element ID（選填）" },
                roomName: { type: "string", description: "房間名稱（選填）" },
            },
        },
    },
    {
        name: "get_rooms_by_level",
        description: "取得指定樓層的所有房間清單，包含名稱、編號、面積、用途等。可用於容積檢討。",
        inputSchema: {
            type: "object",
            properties: {
                level: { type: "string", description: "樓層名稱（如：1F、Level 1）" },
                includeUnnamed: { type: "boolean", description: "是否包含未命名的房間", default: true },
            },
            required: ["level"],
        },
    },
    {
        name: "sync_room_ceiling_finish_from_ceilings",
        description: "依房間範圍偵測同樓層天花板，讀取天花板類型標記，預覽或寫回房間參數（預設：天花板塗層）以更新粉刷明細表。",
        inputSchema: {
            type: "object",
            properties: {
                level: { type: "string", description: "樓層名稱篩選（選填）。" },
                roomName: { type: "string", description: "房間名稱或房間編號部分匹配（選填）。" },
                roomIds: {
                    type: "array",
                    items: { type: "number" },
                    description: "指定房間 ElementId 清單（選填，優先於 level/roomName）。",
                },
                targetParameter: {
                    type: "string",
                    description: "要寫入的房間參數名稱。粉刷明細表的天花板欄位預設為「天花板塗層」。",
                    default: "天花板塗層",
                },
                apply: {
                    type: "boolean",
                    description: "false 只預覽，true 實際寫回房間參數。",
                    default: false,
                },
                overwrite: {
                    type: "boolean",
                    description: "是否覆寫已有值的房間參數。",
                    default: false,
                },
                sampleGrid: {
                    type: "number",
                    description: "在天花板與房間 BoundingBox 重疊區內取樣確認是否位於房間內，範圍 1-7，預設 3。",
                    default: 3,
                },
                multiMatchStrategy: {
                    type: "string",
                    enum: ["largestOverlap", "join"],
                    description: "多個天花板類型命中同一房間時，取最大重疊類型標記或用 + 合併。",
                    default: "largestOverlap",
                },
            },
        },
    },
    {
        name: "check_sanitary_fixture_requirements",
        description: "Calculate sanitary fixture requirements by detecting the building type and applying the matching rule. This rule package currently supports C-1 factory/warehouse only; future building types should be added as separate rules. Output maps to the code table columns: building type, water closets, urinals, lavatories, and bathtubs/showers. Net area excludes stairs, elevators, air-raid shelter/refuge rooms, and parking spaces. This tool does not create or write Revit parameters.",
        inputSchema: {
            type: "object",
            properties: {
                level: {
                    type: "string",
                    description: "Optional level name. If omitted, roomIds or all placed rooms matching filters are used.",
                },
                roomNameContains: {
                    type: "string",
                    description: "Optional Room name filter, useful for factory/building scopes such as C-1.",
                },
                roomNumberContains: {
                    type: "string",
                    description: "Optional Room number filter.",
                },
                buildingType: {
                    type: "string",
                    description: "Optional building type / occupancy group hint, such as C-1, C-1 factory, factory, or warehouse. If omitted, the tool detects from level/view/project/room context and defaults to C-1 because this package currently supports C-1 only.",
                },
                roomIds: {
                    type: "array",
                    items: { type: "number" },
                    description: "Optional explicit Room ElementId list. Overrides level/name/number filters.",
                },
                areaPerPersonM2: {
                    type: "number",
                    description: "Occupancy density in square meters per person.",
                    default: 10,
                },
                maleRatio: {
                    type: "number",
                    description: "Male side of male:female ratio. Default 1.",
                    default: 1,
                },
                femaleRatio: {
                    type: "number",
                    description: "Female side of male:female ratio. Default 1.",
                    default: 1,
                },
                excludeKeywords: {
                    type: "array",
                    items: { type: "string" },
                    description: "Optional extra Room name/number keywords to exclude from occupancy area in addition to stairs, elevators, refuge/shelter, and parking defaults.",
                },
            },
        },
    },
    {
        name: "get_room_daylight_info",
        description: "取得房間的採光資訊，包含居室面積、外牆開口面積、採光比例。用於建築技術規則居室採光檢討。",
        inputSchema: {
            type: "object",
            properties: {
                level: { type: "string", description: "樓層名稱（選填）" },
            },
        },
    },
    {
        name: "check_exterior_wall_openings",
        description: "依據台灣建築技術規則第45條及第110條檢討外牆開口。自動讀取地界線計算距離，以顏色標示違規。",
        inputSchema: {
            type: "object",
            properties: {
                checkArticle45: { type: "boolean", description: "檢查第45條", default: true },
                checkArticle110: { type: "boolean", description: "檢查第110條", default: true },
                colorizeViolations: { type: "boolean", description: "以顏色標示", default: true },
                exportReport: { type: "boolean", description: "匯出 JSON 報表", default: false },
                reportPath: { type: "string", description: "報表輸出路徑" },
            },
        },
    },
];
