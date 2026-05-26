/**
 * Schedule tools for architect and MEP profiles.
 */

import { Tool } from "@modelcontextprotocol/sdk/types.js";

export const scheduleTools: Tool[] = [
    {
        name: "create_view_schedule",
        description: "Create a Revit ViewSchedule with an optional category and field list.",
        inputSchema: {
            type: "object",
            properties: {
                name: { type: "string", description: "Schedule name." },
                category: { type: "string", description: "Revit category name, such as Walls, Rooms, or Pipes." },
                fields: { type: "array", items: { type: "string" }, description: "Field names to add to the schedule." },
            },
            required: ["name"],
        },
    },
    {
        name: "query_schedule_data",
        description: "Read columns and body rows from a Revit schedule. Prefer scheduleId; scheduleName may be exact or a unique partial match.",
        inputSchema: {
            type: "object",
            properties: {
                scheduleId: { type: "number", description: "Schedule ElementId." },
                scheduleName: { type: "string", description: "Schedule name. Used when scheduleId is not supplied." },
                maxRows: { type: "number", description: "Maximum rows to return. Defaults to 500." },
                includeEmptyRows: { type: "boolean", description: "Include completely empty body rows. Defaults to false." },
            },
        },
    },
    {
        name: "get_detail_components",
        description: "Get detail component instances, optionally filtered by family name.",
        inputSchema: {
            type: "object",
            properties: {
                familyName: { type: "string", description: "Optional family name filter." },
            },
        },
    },
    {
        name: "sync_detail_component_numbers",
        description: "Synchronize AE detail component type parameters with owning sheets. Safeguard keeps two matching modes: type name starts with sheet number, or sheet number starts with the sheet-number prefix parsed from the type name.",
        inputSchema: { type: "object", properties: {} },
    },
    {
        name: "create_detail_component_type",
        description: "Create a detail component type with sheet number and detail name metadata.",
        inputSchema: {
            type: "object",
            properties: {
                sheetNumber: { type: "string", description: "Sheet number." },
                detailName: { type: "string", description: "Detail name." },
                familyName: { type: "string", description: "Family name.", default: "AE-numbering" },
            },
            required: ["sheetNumber", "detailName"],
        },
    },
    {
        name: "create_detail_component_types_from_sheet_viewports",
        description: "Create or preview AE-圖號詳圖編號標頭-3.5mm detail component types from all viewports on a target sheet. Type name rule: 詳圖圖號-圖說名稱-詳圖用途; 詳圖用途 equals viewport view name. Defaults to dryRun=true.",
        inputSchema: {
            type: "object",
            properties: {
                sheetNumber: { type: "string", description: "Target sheet number, such as A101 or ARB-D05001." },
                familyName: { type: "string", description: "Detail component family name.", default: "AE-圖號詳圖編號標頭-3.5mm" },
                dryRun: { type: "boolean", description: "When true, preview planned create/update/skip actions without writing to Revit.", default: true },
                overwriteExisting: { type: "boolean", description: "When true, update matching existing type parameters; otherwise existing types are skipped.", default: false },
            },
            required: ["sheetNumber"],
        },
    },
    {
        name: "create_detail_component_types_from_metadata",
        description: "Create or update detail component types from external metadata such as PDF/OCR results. Does not require matching Revit sheets. Type name rule: 詳圖圖號-圖說名稱-詳圖名稱. Defaults to dryRun=true.",
        inputSchema: {
            type: "object",
            properties: {
                familyName: { type: "string", description: "Detail component family name.", default: "AE-圖號詳圖編號標頭-3.5mm" },
                dryRun: { type: "boolean", description: "When true, preview planned create/update/skip actions without writing to Revit.", default: true },
                overwriteExisting: { type: "boolean", description: "When true, update existing type parameters; otherwise existing types are skipped.", default: false },
                items: {
                    type: "array",
                    description: "Detail component type metadata items.",
                    items: {
                        type: "object",
                        properties: {
                            sheetNumber: { type: "string", description: "Detail sheet number / sheet number, such as ARB-D09001." },
                            sheetName: { type: "string", description: "Sheet title / drawing name." },
                            detailNumber: { type: "string", description: "Detail number." },
                            detailName: { type: "string", description: "Detail name." },
                            typeName: { type: "string", description: "Optional explicit type name." },
                        },
                        required: ["sheetNumber", "sheetName", "detailName"],
                    },
                },
            },
            required: ["items"],
        },
    },
    {
        name: "sync_detail_component_sheet_numbers_by_type_parameters",
        description: "Preview or update detail component type parameter 詳圖圖號 by matching existing type parameters 圖說名稱 + 詳圖名稱 against sheet viewports. Matches both Title on Sheet and View Name. Defaults to dryRun=true.",
        inputSchema: {
            type: "object",
            properties: {
                familyName: { type: "string", description: "Detail component family name.", default: "AE-矩形框詳圖元件" },
                sheetNumber: { type: "string", description: "Optional single sheet number filter." },
                sheetNumbers: { type: "array", items: { type: "string" }, description: "Optional sheet number filters." },
                dryRun: { type: "boolean", description: "When true, preview updates without writing to Revit.", default: true },
            },
        },
    },
    {
        name: "list_detail_component_type_parameters",
        description: "List detail component FamilySymbol type parameters, including 詳圖圖號, 圖說名稱, 詳圖編號, and 詳圖名稱. Useful for reading user-corrected reference types before OCR synchronization.",
        inputSchema: {
            type: "object",
            properties: {
                familyName: { type: "string", description: "Detail component family name, such as AE-圖號詳圖編號標頭-3.5mm." },
                sheetNumber: { type: "string", description: "Optional single sheet number filter." },
                sheetNumbers: { type: "array", items: { type: "string" }, description: "Optional sheet number filters." },
            },
        },
    },
];
