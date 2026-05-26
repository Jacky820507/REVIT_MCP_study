/**
 * Wall, opening, structure, and annotation tools for architect and structural profiles.
 */

import { Tool } from "@modelcontextprotocol/sdk/types.js";

export const wallTools: Tool[] = [
    {
        name: "create_wall",
        description: "Create a wall in Revit from start/end coordinates and height.",
        inputSchema: {
            type: "object",
            properties: {
                startX: { type: "number", description: "Start X coordinate in millimeters." },
                startY: { type: "number", description: "Start Y coordinate in millimeters." },
                endX: { type: "number", description: "End X coordinate in millimeters." },
                endY: { type: "number", description: "End Y coordinate in millimeters." },
                height: { type: "number", description: "Wall height in millimeters.", default: 3000 },
                wallType: { type: "string", description: "Optional wall type name." },
            },
            required: ["startX", "startY", "endX", "endY"],
        },
    },
    {
        name: "create_floor",
        description: "Create a floor in Revit from boundary points.",
        inputSchema: {
            type: "object",
            properties: {
                points: {
                    type: "array",
                    description: "Floor boundary points.",
                    items: {
                        type: "object",
                        properties: {
                            x: { type: "number" },
                            y: { type: "number" },
                        },
                    },
                },
                levelName: { type: "string", description: "Level name.", default: "Level 1" },
                floorType: { type: "string", description: "Optional floor type name." },
            },
            required: ["points"],
        },
    },
    {
        name: "create_door",
        description: "在指定的牆上建立門。可指定 sourceElementId 來複製現有門的類型、instance 參數與 facing/hand 朝向。",
        inputSchema: {
            type: "object",
            properties: {
                wallId: { type: "number", description: "要放置門的牆 ID" },
                locationX: { type: "number", description: "門在牆上的位置 X 座標（公釐）" },
                locationY: { type: "number", description: "門在牆上的位置 Y 座標（公釐）" },
                doorType: { type: "string", description: "門類型名稱（選填）" },
                sourceElementId: { type: "number", description: "來源門 ID（選填，用於複製其類型、參數與朝向）" },
            },
            required: ["wallId", "locationX", "locationY"],
        },
    },
    {
        name: "create_window",
        description: "在指定的牆上建立窗。可指定 sourceElementId 來複製現有窗的類型、instance 參數與 facing/hand 朝向。",
        inputSchema: {
            type: "object",
            properties: {
                wallId: { type: "number", description: "要放置窗的牆 ID" },
                locationX: { type: "number", description: "窗在牆上的位置 X 座標（公釐）" },
                locationY: { type: "number", description: "窗在牆上的位置 Y 座標（公釐）" },
                windowType: { type: "string", description: "窗類型名稱（選填）" },
                sourceElementId: { type: "number", description: "來源窗 ID（選填，用於複製其類型、參數與朝向）" },
            },
            required: ["wallId", "locationX", "locationY"],
        },
    },
    {
        name: "get_wall_info",
        description: "Get wall details, including thickness, length, height, and location line coordinates.",
        inputSchema: {
            type: "object",
            properties: {
                wallId: { type: "number", description: "Wall ElementId." },
            },
            required: ["wallId"],
        },
    },
    {
        name: "create_dimension",
        description: "Create a dimension annotation in a specified view.",
        inputSchema: {
            type: "object",
            properties: {
                viewId: { type: "number", description: "Target view ElementId." },
                startX: { type: "number", description: "Start X coordinate in millimeters." },
                startY: { type: "number", description: "Start Y coordinate in millimeters." },
                endX: { type: "number", description: "End X coordinate in millimeters." },
                endY: { type: "number", description: "End Y coordinate in millimeters." },
                offset: { type: "number", description: "Dimension line offset in millimeters.", default: 500 },
            },
            required: ["viewId", "startX", "startY", "endX", "endY"],
        },
    },
    {
        name: "create_corridor_dimension",
        description: "Create wall-to-wall corridor width dimensions from room boundary geometry.",
        inputSchema: {
            type: "object",
            properties: {
                roomId: { type: "number", description: "Corridor room ElementId." },
                viewId: { type: "number", description: "Plan view ElementId." },
            },
            required: ["roomId", "viewId"],
        },
    },
    {
        name: "query_walls_by_location",
        description: "Find walls near a coordinate and return wall thickness, location line, and face coordinates.",
        inputSchema: {
            type: "object",
            properties: {
                x: { type: "number", description: "Search center X coordinate." },
                y: { type: "number", description: "Search center Y coordinate." },
                searchRadius: { type: "number", description: "Search radius in millimeters." },
                level: { type: "string", description: "Optional level name." },
            },
            required: ["x", "y", "searchRadius"],
        },
    },
    {
        name: "unjoin_wall_joins",
        description: "Unjoin wall geometry from joined elements, commonly before graphics overrides.",
        inputSchema: {
            type: "object",
            properties: {
                wallIds: { type: "array", items: { type: "number" }, description: "Wall ElementIds to unjoin." },
                viewId: { type: "number", description: "View ElementId." },
            },
        },
    },
    {
        name: "rejoin_wall_joins",
        description: "Restore wall joins previously changed by unjoin_wall_joins.",
        inputSchema: { type: "object", properties: {} },
    },
    {
        name: "get_all_grids",
        description: "Get all grid lines in the project.",
        inputSchema: { type: "object", properties: {} },
    },
    {
        name: "get_column_types",
        description: "Get available column types in the project.",
        inputSchema: {
            type: "object",
            properties: {
                material: { type: "string", description: "Optional material filter." },
            },
        },
    },
    {
        name: "create_column",
        description: "Create a column at a specified location.",
        inputSchema: {
            type: "object",
            properties: {
                x: { type: "number", description: "X coordinate in millimeters." },
                y: { type: "number", description: "Y coordinate in millimeters." },
                bottomLevel: { type: "string", description: "Base level name.", default: "Level 1" },
                topLevel: { type: "string", description: "Optional top level name." },
                columnType: { type: "string", description: "Optional column type name." },
            },
            required: ["x", "y"],
        },
    },
    {
        name: "get_furniture_types",
        description: "Get loaded furniture types in the project.",
        inputSchema: {
            type: "object",
            properties: {
                category: { type: "string", description: "Optional furniture category filter." },
            },
        },
    },
    {
        name: "place_furniture",
        description: "Place a furniture instance at a specified location.",
        inputSchema: {
            type: "object",
            properties: {
                x: { type: "number", description: "X coordinate in millimeters." },
                y: { type: "number", description: "Y coordinate in millimeters." },
                furnitureType: { type: "string", description: "Furniture type name." },
                level: { type: "string", description: "Level name.", default: "Level 1" },
                rotation: { type: "number", description: "Rotation angle in degrees.", default: 0 },
            },
            required: ["x", "y", "furnitureType"],
        },
    },
    {
        name: "get_wall_types",
        description: "Get available wall types in the project, including names and ElementIds.",
        inputSchema: {
            type: "object",
            properties: {
                search: { type: "string", description: "Optional keyword filter." },
            },
        },
    },
    {
        name: "change_element_type",
        description: "Change one or more Revit elements to a target type.",
        inputSchema: {
            type: "object",
            properties: {
                elementId: { type: "number", description: "Single element ElementId." },
                elementIds: { type: "array", items: { type: "number" }, description: "ElementIds for batch changes." },
                typeId: { type: "number", description: "Target type ElementId." },
            },
            required: ["typeId"],
        },
    },
    {
        name: "get_line_styles",
        description: "Get available line styles in the current project.",
        inputSchema: { type: "object", properties: {} },
    },
    {
        name: "trace_stair_geometry",
        description: "Analyze stair geometry in the active view and return hidden edge line coordinates for later drafting.",
        inputSchema: { type: "object", properties: {} },
    },
];
