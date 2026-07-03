import { Tool } from "@modelcontextprotocol/sdk/types.js";

export const sheetTools: Tool[] = [
    {
        name: "get_all_sheets",
        description: "List all sheets in the current Revit project, including ElementId, sheet number, and sheet name.",
        inputSchema: { type: "object", properties: {} },
    },
    {
        name: "get_titleblocks",
        description: "List available title block family symbols.",
        inputSchema: { type: "object", properties: {} },
    },
    {
        name: "create_sheets",
        description: "Create sheets from a title block type and sheet number/name pairs.",
        inputSchema: {
            type: "object",
            properties: {
                titleBlockId: { type: "number", description: "Title block ElementId." },
                sheets: {
                    type: "array",
                    items: {
                        type: "object",
                        properties: {
                            number: { type: "string", description: "Sheet number, e.g. A101." },
                            name: { type: "string", description: "Sheet name." },
                        },
                        required: ["number", "name"],
                    },
                    description: "Sheets to create.",
                },
            },
            required: ["titleBlockId", "sheets"],
        },
    },
    {
        name: "auto_renumber_sheets",
        description: "Automatically repair sheet-number insertion conflicts such as -1/-2 suffixes.",
        inputSchema: { type: "object", properties: {} },
    },
    {
        name: "get_viewport_map",
        description: "List all viewport-to-sheet mappings.",
        inputSchema: { type: "object", properties: {} },
    },
    {
        name: "get_sheet_viewport_details",
        description: "Read viewport placement details on one or more sheets, including box center, outline, detail number, rotation, viewport type, and label geometry.",
        inputSchema: {
            type: "object",
            properties: {
                sheetNumber: { type: "string", description: "Single sheet number filter." },
                sheetNumbers: { type: "array", items: { type: "string" }, description: "Sheet number filters." },
                sheetName: { type: "string", description: "Single sheet name filter." },
                sheetNames: { type: "array", items: { type: "string" }, description: "Sheet name filters." },
                sheetId: { type: "number", description: "Optional sheet ElementId filter." },
            },
        },
    },
    {
        name: "copy_sheet_viewports",
        description: "Copy viewport placement from source sheets to target sheets. The target viewport box center is set to exactly match the source viewport center.",
        inputSchema: {
            type: "object",
            properties: {
                items: {
                    type: "array",
                    items: {
                        type: "object",
                        properties: {
                            sourceSheetNumber: { type: "string", description: "Source sheet number containing the reference viewport." },
                            targetSheetNumber: { type: "string", description: "Target sheet number where targetViewId should be placed." },
                            sourceSheetName: { type: "string", description: "Source sheet name containing the reference viewport. Used when sheet numbers may change." },
                            targetSheetName: { type: "string", description: "Target sheet name where targetViewId should be placed. Used when sheet numbers may change." },
                            sourceViewId: { type: "number", description: "Optional source viewport view ElementId. If omitted, the first FloorPlan viewport on the source sheet is used." },
                            targetViewId: { type: "number", description: "Target view ElementId to place or move on the target sheet." },
                        },
                        required: ["targetViewId"],
                    },
                },
                dryRun: { type: "boolean", description: "Preview without modifying the model.", default: false },
                copyViewportType: { type: "boolean", description: "Copy viewport type from source viewport.", default: true },
                copyRotation: { type: "boolean", description: "Copy viewport rotation from source viewport.", default: true },
                copyDetailNumber: { type: "boolean", description: "Copy viewport detail number.", default: true },
                copyLabel: { type: "boolean", description: "Copy viewport label offset and label line length.", default: true },
                moveExisting: { type: "boolean", description: "Move existing target viewport if target view is already on the target sheet.", default: true },
            },
            required: ["items"],
        },
    },
    {
        name: "get_viewport_types",
        description: "List viewport title types in the project, optionally filtered by type name.",
        inputSchema: {
            type: "object",
            properties: {
                nameContains: { type: "string", description: "Optional substring filter for viewport type names." },
            },
        },
    },
    {
        name: "sync_viewport_types_by_view_scale",
        description: "For viewports on sheets, detect the placed view scale and switch FloorPlan/Elevation/Section viewport types to the matching scale title type. Falls back to a line-title type when no exact scale title exists.",
        inputSchema: {
            type: "object",
            properties: {
                sheetNumber: { type: "string", description: "Optional single sheet number filter." },
                sheetNumbers: { type: "array", items: { type: "string" }, description: "Optional sheet number filters." },
                sheetName: { type: "string", description: "Optional single sheet name filter." },
                sheetNames: { type: "array", items: { type: "string" }, description: "Optional sheet name filters." },
                viewTypes: {
                    type: "array",
                    items: { type: "string" },
                    description: "Placed view types to process. Defaults to ['FloorPlan', 'Elevation', 'Section'].",
                },
                exactPattern: {
                    type: "string",
                    description: "Exact viewport type naming pattern. Supports {scale} and {doubleScale}.",
                    default: "附圖號的有比例標題_A1({scale})A3({doubleScale})",
                },
                fallbackNameContains: {
                    type: "string",
                    description: "Fallback viewport type substring when no exact scale type is found.",
                    default: "有線條的標題",
                },
                excludeViewTitleContains: {
                    oneOf: [
                        { type: "string" },
                        { type: "array", items: { type: "string" } },
                    ],
                    description: "Skip viewports when the placed view name or Title on Sheet contains these keywords. Defaults to ['圖例'].",
                    default: ["圖例"],
                },
                dryRun: { type: "boolean", description: "Preview without modifying viewport types.", default: false },
            },
        },
    },
];
