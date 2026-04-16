/**
 * 視覺化工具 — 圖形覆寫、視圖樣版
 * 所有 Profile 都可選用
 */

import { Tool } from "@modelcontextprotocol/sdk/types.js";

export const visualizationTools: Tool[] = [
    {
        name: "override_element_graphics",
        description: "在指定視圖中覆寫元素的圖形顯示（填滿顏色、圖樣、線條顏色等）。",
        inputSchema: {
            type: "object",
            properties: {
                elementId: { type: "number", description: "要覆寫的元素 ID" },
                viewId: { type: "number", description: "視圖 ID（若不指定則使用當前視圖）" },
                surfaceFillColor: {
                    type: "object",
                    description: "表面填滿顏色 RGB (0-255)",
                    properties: {
                        r: { type: "number", minimum: 0, maximum: 255 },
                        g: { type: "number", minimum: 0, maximum: 255 },
                        b: { type: "number", minimum: 0, maximum: 255 },
                    },
                },
                surfacePatternId: { type: "number", description: "表面填充圖樣 ID（-1 = 實心填滿）", default: -1 },
                lineColor: {
                    type: "object",
                    description: "線條顏色 RGB（可選）",
                    properties: {
                        r: { type: "number", minimum: 0, maximum: 255 },
                        g: { type: "number", minimum: 0, maximum: 255 },
                        b: { type: "number", minimum: 0, maximum: 255 },
                    },
                },
                transparency: { type: "number", description: "透明度 (0-100)", minimum: 0, maximum: 100, default: 0 },
            },
            required: ["elementId"],
        },
    },
    {
        name: "clear_element_override",
        description: "清除元素在指定視圖中的圖形覆寫。",
        inputSchema: {
            type: "object",
            properties: {
                elementId: { type: "number", description: "要清除覆寫的元素 ID" },
                elementIds: { type: "array", items: { type: "number" }, description: "批次操作" },
                viewId: { type: "number", description: "視圖 ID" },
            },
        },
    },
    {
        name: "get_view_templates",
        description: "取得專案中所有視圖樣版的完整設定。可用於視圖樣版比對與整併分析。",
        inputSchema: {
            type: "object",
            properties: {
                includeDetails: { type: "boolean", description: "是否包含詳細設定", default: true },
            },
        },
    },
    {
        name: "calculate_grid_bounds",
        description: "根據網格名稱與偏移量計算邊界框 (Bounding Box)。常用於自動化視圖裁剪。",
        inputSchema: {
            type: "object",
            properties: {
                x_grids: { type: "array", items: { type: "string" }, description: "X 軸網格名稱清單" },
                y_grids: { type: "array", items: { type: "string" }, description: "Y 軸網格名稱清單" },
                offset_mm: { type: "number", description: "邊界偏移量 (mm)", default: 1000 },
            },
        },
    },
    {
        name: "create_dependent_views",
        description: "依據指定的母視圖與 BoundingBox 建立並裁切從屬視圖 (Dependent View)。",
        inputSchema: {
            type: "object",
            properties: {
                parentViewIds: { type: "array", items: { type: "number" }, description: "母視圖 ID 清單" },
                min: {
                    type: "object",
                    properties: {
                        x: { type: "number" },
                        y: { type: "number" },
                        z: { type: "number" },
                    },
                    required: ["x", "y", "z"],
                },
                max: {
                    type: "object",
                    properties: {
                        x: { type: "number" },
                        y: { type: "number" },
                        z: { type: "number" },
                    },
                    required: ["x", "y", "z"],
                },
                suffixName: { type: "string", description: "視圖名稱後綴 (如 '-1')。若不指定則自動流水號。" },
            },
            required: ["parentViewIds", "min", "max"],
        },
    },
    {
        name: "create_grid_cropped_views_batch",
        description: "批次視圖裁剪工具 — 一次性根據多個網格交點建立並裁剪多個母視圖的從屬視圖。",
        inputSchema: {
            type: "object",
            properties: {
                parentViewIds: { type: "array", items: { type: "number" }, description: "母視圖 ID 清單" },
                x_grid_names: { type: "array", items: { type: "string" }, description: "X 軸網格名稱清單（如 ['B8', 'B13']）" },
                y_grid_names: { type: "array", items: { type: "string" }, description: "Y 軸網格名稱清單（如 ['BA', 'BE']）" },
                offset_mm: { type: "number", description: "邊界偏移量 (mm)", default: 1000 },
            },
            required: ["parentViewIds", "x_grid_names", "y_grid_names"],
        },
    },
    {
        name: "create_dimension_by_ray",
        description: "在 3D 視圖中透過射線偵測自動建立尺寸標註。",
        inputSchema: {
            type: "object",
            properties: {
                faceIndex: { type: "number", description: "面索引", default: 1 },
                offset_mm: { type: "number", description: "標註偏移量 (mm)", default: 500 },
            },
        },
    },
    {
        name: "create_dimension_by_bounding_box",
        description: "根據房間的邊界框建立對齊的尺寸標註。",
        inputSchema: {
            type: "object",
            properties: {
                roomId: { type: "number", description: "房間 Element ID" },
            },
            required: ["roomId"],
        },
    },
    {
        name: "create_detail_lines",
        description: "在目前視圖中批次建立詳圖線段。",
        inputSchema: {
            type: "object",
            properties: {
                lines: {
                    type: "array",
                    items: {
                        type: "object",
                        properties: {
                            startX: { type: "number" },
                            startY: { type: "number" },
                            startZ: { type: "number" },
                            endX: { type: "number" },
                            endY: { type: "number" },
                            endZ: { type: "number" },
                        },
                        required: ["startX", "startY", "startZ", "endX", "endY", "endZ"],
                    },
                },
                styleId: { type: "number", description: "線型樣式 ID (選填)" },
            },
            required: ["lines"],
        },
    },
    {
        name: "trace_stair_geometry",
        description: "追蹤樓梯幾何，並自動偵測被遮擋的踏步邊緣（用於剖面圖隱藏線視覺化）。",
        inputSchema: { type: "object", properties: {} },
    },
    {
        name: "convert_drafting_to_model_pattern",
        description: "將使用者在目前的 Revit 視圖中「選取」的填滿範圍 (Filled Region)，從「製圖樣式」安全地轉換為「模型樣式」。會自動依據視圖比例尺放大/縮小線段間距。",
        inputSchema: { type: "object", properties: {} },
    },
    {
        name: "auto_convert_rotated_viewport_patterns",
        description: "自動掃描全專案中「圖紙上有旋轉過」的剖面圖，並將其中的製圖樣式填滿範圍全部轉換為模型樣式。",
        inputSchema: { type: "object", properties: {} },
    },
    {
        name: "measure_clearance",
        description: "測量指定起點向特定方向的淨空高度（射線偵測）。可以用於檢查停車位、走道等的淨空高度。",
        inputSchema: {
            type: "object",
            properties: {
                origin: {
                    type: "object",
                    properties: {
                        x: { type: "number", description: "起點 X (mm)" },
                        y: { type: "number", description: "起點 Y (mm)" },
                        z: { type: "number", description: "起點 Z (mm)" },
                    },
                    required: ["x", "y", "z"],
                },
                direction: {
                    type: "object",
                    properties: {
                        x: { type: "number", description: "方向 X" },
                        y: { type: "number", description: "方向 Y" },
                        z: { type: "number", description: "方向 Z" },
                    },
                    required: ["x", "y", "z"],
                },
            },
            required: ["origin", "direction"],
        },
    },
    {
        name: "create_rc_filled_region",
        description: "在指定的 2D 視圖中，自動找尋被剖斷或投影的 RC(系統牆、結構柱、樓板)，產生對應的 Filled Region 貼紙以作為單一視覺塗黑/塗灰表現。",
        inputSchema: {
            type: "object",
            properties: {
                filledRegionTypeName: { 
                    type: "string", 
                    description: "欲套用的 FilledRegionType 名稱", 
                    default: "深灰色" 
                },
            },
        },
    },
    {
        name: "create_dependent_view_matchlines",
        description: "在母視圖上自動根據其從屬視圖的裁切邊界繪製分模界線（Matchlines）並標註相鄰圖紙號碼。具備 MATCHLINE_AUTO 標記自動更新/清除舊線功能。",
        inputSchema: {
            type: "object",
            properties: {
                primaryViewId: { 
                    type: "number", 
                    description: "母視圖的 Element ID。若不填則預設為目前 Active View。" 
                },
                lineStyleName: { 
                    type: "string", 
                    description: "欲套用的線型名稱", 
                    default: "粗虛線" 
                },
                textStyleName: { 
                    type: "string", 
                    description: "標記使用的文字樣式名稱", 
                    default: "微軟正黑體 3.5 mm" 
                },
            },
        },
    },
    {
        name: "detect_sheet_matchlines",
        description: "偵測指定圖紙上已存在的銜接線與銜接文字，並回傳該圖紙上放置視圖與檢測到的元素清單。",
        inputSchema: {
            type: "object",
            properties: {
                sheetNumbers: {
                    type: "array",
                    items: { type: "string" },
                    description: "要偵測的圖紙號碼列表。"
                },
                lineStyleName: { 
                    type: "string", 
                    description: "偵測銜接線使用的線型名稱", 
                    default: "粗虛線" 
                },
                textStyleName: { 
                    type: "string", 
                    description: "偵測銜接文字使用的文字樣式名稱", 
                    default: "微軟正黑體 3.5 mm" 
                },
            },
            required: ["sheetNumbers"],
        },
    },
];
