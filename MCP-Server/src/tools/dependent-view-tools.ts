import { Tool } from "@modelcontextprotocol/sdk/types.js";

const bboxSchema = {
    type: "object",
    properties: {
        x: { type: "number" },
        y: { type: "number" },
        z: { type: "number" },
    },
    required: ["x", "y", "z"],
};

export const dependentViewTools: Tool[] = [
    {
        name: "calculate_grid_bounds",
        description: "Calculate a crop BoundingBox from named X/Y grid lines. Coordinates are returned in millimeters.",
        inputSchema: {
            type: "object",
            properties: {
                xGrids: { type: "array", items: { type: "string" }, description: "X-axis grid names, e.g. ['C1', 'C5']." },
                yGrids: { type: "array", items: { type: "string" }, description: "Y-axis grid names, e.g. ['CA', 'CE']." },
                x_grids: { type: "array", items: { type: "string" }, description: "Alias for xGrids." },
                y_grids: { type: "array", items: { type: "string" }, description: "Alias for yGrids." },
                offset_mm: { type: "number", description: "Outward crop offset in millimeters.", default: 0 },
            },
        },
    },
    {
        name: "get_view_crop_box",
        description: "Read a view's crop box, crop visibility flags, crop transform, and assigned scope box.",
        inputSchema: {
            type: "object",
            properties: {
                viewId: { type: "number", description: "View ElementId. Defaults to the active view when omitted." },
            },
        },
    },
    {
        name: "copy_view_crop_box",
        description: "Copy the crop box from one view to one or more target views, preserving transform and optionally crop shape or scope box.",
        inputSchema: {
            type: "object",
            properties: {
                sourceViewId: { type: "number", description: "Source view ElementId." },
                targetViewIds: { type: "array", items: { type: "number" }, description: "Target view ElementIds." },
                viewIds: { type: "array", items: { type: "number" }, description: "Alias for targetViewIds." },
                copyCropVisibility: { type: "boolean", description: "Copy CropBoxActive and CropBoxVisible from the source view.", default: true },
                copyCropShape: { type: "boolean", description: "Copy non-rectangular crop shape when supported.", default: true },
                copyScopeBox: { type: "boolean", description: "Also copy the source view's assigned scope box when it has one.", default: false },
                dryRun: { type: "boolean", description: "Preview the operation without modifying Revit.", default: false },
            },
            required: ["sourceViewId"],
        },
    },
    {
        name: "get_view_grid_details",
        description: "Read grid datum display details in a view, including 2D/3D extent modes, curve endpoints, and bubble visibility.",
        inputSchema: {
            type: "object",
            properties: {
                viewId: { type: "number", description: "View ElementId. Defaults to the active view when omitted." },
                gridNames: { type: "array", items: { type: "string" }, description: "Optional grid names to include." },
                grids: { type: "array", items: { type: "string" }, description: "Alias for gridNames." },
            },
        },
    },
    {
        name: "sync_grid_extents_between_views",
        description: "Copy grid datum display extents and bubble visibility from source views to matching target views.",
        inputSchema: {
            type: "object",
            properties: {
                pairs: {
                    type: "array",
                    description: "View pairs to sync.",
                    items: {
                        type: "object",
                        properties: {
                            sourceViewId: { type: "number", description: "Reference/source view ElementId." },
                            targetViewId: { type: "number", description: "Target view ElementId to modify." },
                        },
                        required: ["sourceViewId", "targetViewId"],
                    },
                },
                items: { type: "array", description: "Alias for pairs." },
                gridNames: { type: "array", items: { type: "string" }, description: "Optional grid names to sync. Defaults to grids visible in each source view." },
                grids: { type: "array", items: { type: "string" }, description: "Alias for gridNames." },
                copyCurves: { type: "boolean", description: "Copy view-specific datum curve endpoints.", default: true },
                copyExtentTypes: { type: "boolean", description: "Copy 2D/3D datum extent type for each grid end.", default: true },
                copyBubbles: { type: "boolean", description: "Copy grid bubble visibility for each grid end.", default: true },
                forceViewSpecific: { type: "boolean", description: "Force target grid ends to 2D view-specific extents.", default: false },
                dryRun: { type: "boolean", description: "Preview without modifying Revit.", default: false },
            },
            required: ["pairs"],
        },
    },
    {
        name: "list_scope_boxes",
        description: "List existing Revit scope boxes (OST_VolumeOfInterest) with ElementIds and bounding boxes.",
        inputSchema: {
            type: "object",
            properties: {},
        },
    },
    {
        name: "assign_scope_box_to_views",
        description: "Assign an existing scope box to multiple views, or clear the scope box assignment.",
        inputSchema: {
            type: "object",
            properties: {
                scopeBoxId: { type: "number", description: "Scope Box ElementId. Use 0 with clearScopeBox=true to clear." },
                viewIds: { type: "array", items: { type: "number" }, description: "Target view ElementIds." },
                targetViewIds: { type: "array", items: { type: "number" }, description: "Alias for viewIds." },
                clearScopeBox: { type: "boolean", description: "Clear the view's scope box assignment.", default: false },
                dryRun: { type: "boolean", description: "Preview the operation without modifying Revit.", default: false },
            },
            required: ["viewIds"],
        },
    },
    {
        name: "create_dependent_views",
        description: "Create dependent views from parent views and crop them by explicit BoundingBox or by copying a source view crop.",
        inputSchema: {
            type: "object",
            properties: {
                parentViewIds: { type: "array", items: { type: "number" }, description: "Parent view ElementIds." },
                min: { ...bboxSchema, description: "Minimum crop point in millimeters. Required when sourceCropViewId is not provided." },
                max: { ...bboxSchema, description: "Maximum crop point in millimeters. Required when sourceCropViewId is not provided." },
                sourceCropViewId: { type: "number", description: "Optional source view whose CropBox is copied to the new dependent view." },
                copyCropFromViewId: { type: "number", description: "Alias for sourceCropViewId." },
                copyCropVisibility: { type: "boolean", description: "Copy crop visibility flags from sourceCropViewId.", default: true },
                copyCropShape: { type: "boolean", description: "Copy crop shape from sourceCropViewId when supported.", default: true },
                scopeBoxId: { type: "number", description: "Optional existing scope box ElementId to assign to the new dependent view." },
                suffixName: { type: "string", description: "Suffix appended to the parent view name." },
            },
            required: ["parentViewIds"],
        },
    },
];
