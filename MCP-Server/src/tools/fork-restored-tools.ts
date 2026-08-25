/**
 * Fork-restored tools
 *
 * 這些 command 在 MCP/Core/CommandExecutor.cs 裡一直都有 case 與實作，
 * 但 MCP 工具層從來沒有對應的 Tool 定義——也就是「Revit 做得到，AI 叫不到」。
 * 2026-08-03 的工具鏈盤點把這個反向缺口補起來。
 *
 * 每個 inputSchema 的欄位都是照 C# handler 實際讀取的 parameters[...] 逐一對過的，
 * 不是照文件或印象推的。改動這裡之前請先回去看對應的 handler。
 *
 * scripts/verify-qaqc.ps1 Phase 9 會確保這裡的每個工具都真的有 C# case 可以接。
 */

import { Tool } from "@modelcontextprotocol/sdk/types.js";

export const forkRestoredTools: Tool[] = [
    {
        // handler: CommandExecutor.Automation.cs GetElementLocation
        name: "get_element_location",
        description:
            "Get the representative location of a single element, in millimetres. Uses LocationPoint if present, otherwise the midpoint of LocationCurve, otherwise the bounding-box centre. Returns {x, y, z}.",
        inputSchema: {
            type: "object",
            properties: {
                elementId: {
                    type: "number",
                    description: "ElementId of the element to locate.",
                },
            },
            required: ["elementId"],
        },
    },
    {
        // handler: CommandExecutor.Automation.cs MeasureClearance
        name: "measure_clearance",
        description:
            "Cast a ray from a point in a direction and return the distance to the nearest obstacle, in millimetres. Obstacles considered: walls, structural and architectural columns, structural framing, ceilings, floors, ducts, pipes, stairs. Requires at least one non-template 3D view in the document. Returns {hit: false, distance: -1} when nothing is hit.",
        inputSchema: {
            type: "object",
            properties: {
                origin: {
                    type: "object",
                    description: "Ray origin in millimetres.",
                    properties: {
                        x: { type: "number" },
                        y: { type: "number" },
                        z: { type: "number" },
                    },
                    required: ["x", "y", "z"],
                },
                direction: {
                    type: "object",
                    description: "Ray direction vector; normalised on the Revit side, so magnitude does not matter.",
                    properties: {
                        x: { type: "number" },
                        y: { type: "number" },
                        z: { type: "number" },
                    },
                    required: ["x", "y", "z"],
                },
            },
            required: ["origin", "direction"],
        },
    },
    {
        // handler: CommandExecutor.Automation.cs RenameElement
        name: "rename_element",
        description:
            "Rename a single element. Renaming resolves to the correct target automatically: for an instance whose name lives on its type, the type is renamed. Runs in its own transaction. Fails if newName is empty or the element does not exist.",
        inputSchema: {
            type: "object",
            properties: {
                elementId: {
                    type: "number",
                    description: "ElementId of the element to rename.",
                },
                newName: {
                    type: "string",
                    description: "The new name. Must be non-empty and unique among siblings, or Revit throws.",
                },
            },
            required: ["elementId", "newName"],
        },
    },
    {
        // handler: CommandExecutor.GridDatum.cs GetViewGridDetails
        name: "get_view_grid_details",
        description:
            "List the grids visible in a view together with their per-view extents and bubble states. Use this before sync_grid_extents_between_views or any grid-based cropping decision.",
        inputSchema: {
            type: "object",
            properties: {
                viewId: {
                    type: "number",
                    description: "View ElementId. Omit or pass 0 to use the active view.",
                },
                gridNames: {
                    type: "array",
                    items: { type: "string" },
                    description: "Optional grid-name filter. Alias: 'grids'.",
                },
                grids: {
                    type: "array",
                    items: { type: "string" },
                    description: "Alias of gridNames.",
                },
            },
        },
    },
    {
        // handler: CommandExecutor.DependentView.cs GetViewCropBox
        name: "get_view_crop_box",
        description:
            "Read a view's crop box state: CropBoxActive, CropBoxVisible, the crop bounding box, and the assigned scope box (id and name) if any.",
        inputSchema: {
            type: "object",
            properties: {
                viewId: {
                    type: "number",
                    description: "View ElementId. Omit or pass 0 to use the active view.",
                },
            },
        },
    },
    {
        // handler: CommandExecutor.DependentView.cs ListScopeBoxes
        name: "list_scope_boxes",
        description:
            "List every scope box (OST_VolumeOfInterest) in the document with its ElementId, name and bounding box, sorted by name.",
        inputSchema: {
            type: "object",
            properties: {},
        },
    },
    {
        // handler: CommandExecutor.Sheet.cs GetViewportTypes
        name: "get_viewport_types",
        description:
            "List the viewport (view title) types available in the document. Use this to discover the exact type names before calling sync_viewport_types_by_view_scale.",
        inputSchema: {
            type: "object",
            properties: {
                nameContains: {
                    type: "string",
                    description: "Case-insensitive substring filter on the viewport type name.",
                },
            },
        },
    },
    {
        // handler: CommandExecutor.Sheet.cs SyncViewportTypesByViewScale
        name: "sync_viewport_types_by_view_scale",
        description:
            "Set each viewport's type according to its view scale, using a scale-templated type name and falling back to a generic titled type when the exact one does not exist. Always call once with dryRun true and review the plan before applying.",
        inputSchema: {
            type: "object",
            properties: {
                dryRun: {
                    type: "boolean",
                    description: "Preview only, change nothing. Default false — pass true first.",
                },
                exactPattern: {
                    type: "string",
                    description:
                        "Viewport type name template. {scale} and {doubleScale} are substituted from the view scale. Default: 附圖號的有比例標題_A1({scale})A3({doubleScale})",
                },
                fallbackNameContains: {
                    type: "string",
                    description:
                        "Substring identifying the fallback viewport type used when the exact name is absent. Default: 有線條的標題. The command fails if no type matches.",
                },
                sheetNumber: { type: "string", description: "Restrict to one sheet number." },
                sheetNumbers: {
                    type: "array",
                    items: { type: "string" },
                    description: "Restrict to these sheet numbers.",
                },
                sheetName: { type: "string", description: "Restrict to one sheet name." },
                sheetNames: {
                    type: "array",
                    items: { type: "string" },
                    description: "Restrict to these sheet names.",
                },
                viewTypes: {
                    type: "array",
                    items: { type: "string" },
                    description: "View types to touch. Default: FloorPlan, Elevation, Section.",
                },
                excludeViewTitleContains: {
                    type: "array",
                    items: { type: "string" },
                    description: "Skip viewports whose view title contains any of these. Default: 圖例.",
                },
            },
        },
    },
    {
        // handler: CommandExecutor.Schedule.cs QueryScheduleData
        name: "query_schedule_data",
        description:
            "Read the body rows of a view schedule as structured data, keyed by column name. Requires scheduleId or scheduleName — pass the exact schedule name as shown in the Revit project browser. (Do not suggest list_schedules for discovery: it has no Revit-side implementation on this fork and is not registered.)",
        inputSchema: {
            type: "object",
            properties: {
                scheduleId: {
                    type: "number",
                    description: "ViewSchedule ElementId. Either this or scheduleName is required.",
                },
                scheduleName: {
                    type: "string",
                    description: "ViewSchedule name. Either this or scheduleId is required.",
                },
                maxRows: {
                    type: "number",
                    description: "Maximum body rows to return. Default 500; values <= 0 fall back to 500.",
                },
                includeEmptyRows: {
                    type: "boolean",
                    description: "Include rows where every cell is empty. Default false.",
                },
            },
        },
    },
];
