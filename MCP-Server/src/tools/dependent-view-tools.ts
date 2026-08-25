import { Tool } from "@modelcontextprotocol/sdk/types.js";

export const dependentViewTools: Tool[] = [
    {
        name: "calculate_grid_bounds",
        description: "計算給定 X 與 Y 網格範圍的邊界 BoundingBox 座標。可指定外擴偏移量 (offset_mm)。",
        inputSchema: {
            type: "object",
            properties: {
                xGrids: { type: "array", items: { type: "string" }, description: "X 軸網格名稱清單 (例如 ['B23', 'B27'])" },
                yGrids: { type: "array", items: { type: "string" }, description: "Y 軸網格名稱清單 (例如 ['BE'])" },
                offset_mm: { type: "number", description: "邊界向外偏移距離 (公釐)，預設 0", default: 0 },
            },
        },
    },
    {
        name: "create_dependent_views",
        description: "依據指定的母視圖 ID 與 BoundingBox 邊界，批次建立並裁切從屬視圖 (Dependent View)。",
        inputSchema: {
            type: "object",
            properties: {
                parentViewIds: { type: "array", items: { type: "number" }, description: "母視圖的 Element ID 清單" },
                min: {
                    type: "object",
                    description: "裁切框最小座標點；未指定 sourceCropViewId 時必填。",
                    properties: { x: { type: "number" }, y: { type: "number" }, z: { type: "number" } },
                    required: ["x", "y", "z"],
                },
                max: {
                    type: "object",
                    description: "裁切框最大座標點；未指定 sourceCropViewId 時必填。",
                    properties: { x: { type: "number" }, y: { type: "number" }, z: { type: "number" } },
                    required: ["x", "y", "z"],
                },
                suffixName: { type: "string", description: "視圖命名後綴 (例如 '-1')。若不指定則自動編號流水號。" },
                sourceCropViewId: {
                    type: "number",
                    description: "Optional source view ElementId. When supplied, copy that view's CropBox to each new dependent view instead of using min/max.",
                },
                scopeBoxId: {
                    type: "number",
                    description: "Optional existing Scope Box ElementId to assign to each new dependent view. Revit does not expose public API creation of a new Scope Box.",
                },
                copyCropShape: {
                    type: "boolean",
                    description: "Copy the source view's non-rectangular crop shape when sourceCropViewId is supplied.",
                    default: true,
                },
                copyCropVisibility: {
                    type: "boolean",
                    description: "Copy CropBoxActive/CropBoxVisible from the source view when sourceCropViewId is supplied.",
                    default: true,
                },
                copySourceDependents: {
                    type: "boolean",
                    description: "When true and sourceCropViewId has dependent views, copy every source dependent's crop and naming suffix to every target parent instead of creating only one dependent per target.",
                    default: false,
                },
                replaceExistingDependentViews: {
                    type: "boolean",
                    description: "Before creating, delete all existing dependent views under each selected parent view and recreate them. Use only when replacement is intended.",
                    default: false,
                },
            },
            required: ["parentViewIds"],
        },
    },
    {
        name: "create_dependent_view_matchlines",
        description:
            "在母視圖上逐一檢查所有從屬視圖的 CropBox 四邊，找出真正位於左／右或上／下的最近相鄰視圖，" +
            "先把各邊界切成區段，再以雙向最近鄰排除只在四角重疊的對角視圖與跨過中間視圖的配對。每一條有效交界都繪製詳圖線，" +
            "並固定在線段中點兩側各放一個「銜接線 <相鄰圖號>」文字（垂直交界時文字旋轉 90 度）；" +
            "文字不會因網格、交會或擁擠而省略，也不會離開該線段的幾何中點。" +
            "圖號取自該從屬視圖被放置的圖紙；尚未上圖紙的從屬視圖會退回使用視圖名稱。" +
            "注意：此命令沒有 dry-run；它會先完成 CropBox 候選計算，找不到候選時保留所有既有標註，" +
            "找到候選後才刪除本視圖既有的銜接線與含「銜接線」的文字再重畫，因此可安全重複執行。" +
            "必須在母視圖執行（見 domain/matchline-automation.md）。",
        inputSchema: {
            type: "object",
            properties: {
                primaryViewId: {
                    type: "number",
                    description: "母視圖的 Element ID。省略時使用目前作用中的視圖。",
                },
                lineStyleName: {
                    type: "string",
                    description: "銜接線線型名稱，以「包含」比對。預設 粗虛線。",
                    default: "粗虛線",
                },
                textStyleName: {
                    type: "string",
                    description: "銜接線文字型式名稱，以「包含」比對。預設 微軟正黑體 3.5 mm。",
                    default: "微軟正黑體 3.5 mm",
                },
            },
        },
    },
    {
        name: "detect_sheet_matchlines",
        description:
            "掃描指定圖紙上既有的銜接線標註，用於佈署前的預檢與佈署後的驗收。" +
            "會列出每張圖紙上放置的視圖（含是否為從屬視圖與其母視圖），" +
            "並同時掃描視圖本身、其母視圖與圖紙空間中的銜接線條與含「銜接線」的文字，" +
            "以 ElementId 在同一張圖紙內去重，避免母視圖與從屬視圖重複計數。唯讀，不修改模型。",
        inputSchema: {
            type: "object",
            properties: {
                sheetNumbers: {
                    type: "array",
                    items: { type: "string" },
                    description: "要偵測的圖紙編號清單（例如 ['ARB-D02002','ARB-D02003']）。",
                },
                lineStyleName: {
                    type: "string",
                    description: "要比對的線型名稱，以「包含」比對。預設 粗虛線。",
                    default: "粗虛線",
                },
            },
            required: ["sheetNumbers"],
        },
    },
];
