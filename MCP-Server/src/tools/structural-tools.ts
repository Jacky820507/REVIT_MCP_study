import { Tool } from "@modelcontextprotocol/sdk/types.js";

export const structuralTools: Tool[] = [
    {
        name: "get_structural_framing_types",
        description: "Get available StructuralFraming family symbols in the current project.",
        inputSchema: {
            type: "object",
            properties: {
                search: {
                    type: "string",
                    description: "Optional type/family/section keyword filter.",
                },
            },
        },
    },
    {
        name: "create_structural_framing",
        description:
            "Create one or more native StructuralFraming line members from start/end coordinates in millimeters. Supports sloped members with startZ/endZ.",
        inputSchema: {
            type: "object",
            properties: {
                items: {
                    type: "array",
                    description: "Optional batch items. If omitted, top-level start/end parameters create one member.",
                    items: {
                        type: "object",
                        properties: {
                            startX: { type: "number", description: "Start X coordinate in millimeters." },
                            startY: { type: "number", description: "Start Y coordinate in millimeters." },
                            startZ: { type: "number", description: "Start Z coordinate in millimeters." },
                            endX: { type: "number", description: "End X coordinate in millimeters." },
                            endY: { type: "number", description: "End Y coordinate in millimeters." },
                            endZ: { type: "number", description: "End Z coordinate in millimeters." },
                            z: { type: "number", description: "Flat member Z coordinate in millimeters when startZ/endZ are omitted." },
                            zOffsetMm: { type: "number", description: "Offset from level elevation when z/startZ/endZ are omitted." },
                            levelName: { type: "string", description: "Reference level name." },
                            framingType: { type: "string", description: "Optional StructuralFraming type/family name." },
                            mark: { type: "string", description: "Optional instance mark." },
                            comments: { type: "string", description: "Optional instance comments." },
                            startOffsetMm: { type: "number", description: "Optional start level offset parameter in millimeters." },
                            endOffsetMm: { type: "number", description: "Optional end level offset parameter in millimeters." },
                            yOffsetMm: { type: "number", description: "Optional Y offset parameter in millimeters." },
                            rotationDegrees: { type: "number", description: "Optional cross-section rotation in degrees." },
                        },
                        required: ["startX", "startY", "endX", "endY"],
                    },
                },
                startX: { type: "number", description: "Start X coordinate in millimeters." },
                startY: { type: "number", description: "Start Y coordinate in millimeters." },
                startZ: { type: "number", description: "Start Z coordinate in millimeters." },
                endX: { type: "number", description: "End X coordinate in millimeters." },
                endY: { type: "number", description: "End Y coordinate in millimeters." },
                endZ: { type: "number", description: "End Z coordinate in millimeters." },
                z: { type: "number", description: "Flat member Z coordinate in millimeters when startZ/endZ are omitted." },
                zOffsetMm: { type: "number", description: "Offset from level elevation when z/startZ/endZ are omitted." },
                levelName: { type: "string", description: "Reference level name.", default: "RF" },
                framingType: { type: "string", description: "Optional StructuralFraming type/family name." },
                mark: { type: "string", description: "Optional instance mark." },
                comments: { type: "string", description: "Optional instance comments." },
                startOffsetMm: { type: "number", description: "Optional start level offset parameter in millimeters." },
                endOffsetMm: { type: "number", description: "Optional end level offset parameter in millimeters." },
                yOffsetMm: { type: "number", description: "Optional Y offset parameter in millimeters." },
                rotationDegrees: { type: "number", description: "Optional cross-section rotation in degrees." },
            },
        },
    },
    {
        name: "align_beams_top_to_floor_bottom",
        description:
            "Align StructuralFraming beam top elevations to the underside of floors by updating instance parameters '起始樓層偏移' and '結束樓層偏移'. Defaults to dryRun.",
        inputSchema: {
            type: "object",
            properties: {
                beamIds: {
                    type: "array",
                    items: { type: "number" },
                    description: "Optional beam ElementIds. If omitted, beams are collected from the view/project.",
                },
                floorIds: {
                    type: "array",
                    items: { type: "number" },
                    description: "Optional floor ElementIds to restrict target slabs.",
                },
                selectedOnly: {
                    type: "boolean",
                    description: "Use currently selected StructuralFraming elements only.",
                    default: false,
                },
                viewId: {
                    type: "number",
                    description: "Optional view ElementId used only for beam collection.",
                },
                levelName: {
                    type: "string",
                    description: "Optional reference level name filter for beams.",
                },
                dryRun: {
                    type: "boolean",
                    description: "Preview changes without writing parameters. Defaults to true unless apply is true.",
                    default: true,
                },
                apply: {
                    type: "boolean",
                    description: "Set true to apply the planned offset changes.",
                    default: false,
                },
                toleranceMm: {
                    type: "number",
                    description: "Skip an endpoint when the required adjustment is within this tolerance.",
                    default: 5,
                },
                maxDeltaMm: {
                    type: "number",
                    description: "Safety cap. Skip a beam when either endpoint needs more movement than this.",
                    default: 1000,
                },
                floorSelectionMode: {
                    type: "string",
                    enum: ["auto_by_beam", "dominant_area_by_beam", "lowest_by_level", "nearest_at_beam"],
                    description: "Target floor selection rule. auto_by_beam keeps dominant slab selection, then automatically uses endpoint-specific underside heights when the slab is sloped and a horizontal shared target when it is flat.",
                    default: "auto_by_beam",
                },
                slopeDetectionToleranceMm: {
                    type: "number",
                    description: "In auto_by_beam mode, treat the target slab as sloped when start/end underside heights differ by more than this value.",
                    default: 20,
                },
                alignWhenTopAboveFloorBottom: {
                    type: "boolean",
                    description:
                        "When true, lower a beam whenever its top is above the target floor underside, even if it is still below the floor top. This is the preferred mode for real beam-top-to-slab-bottom attachment.",
                    default: true,
                },
                disallowJoinsBeforeAlign: {
                    type: "boolean",
                    description:
                        "When applying changes, first disallow StructuralFraming joins at both ends so Revit end joins/cutbacks do not keep the visible beam geometry above the slab.",
                    default: true,
                },
                postAlignGeometryCorrection: {
                    type: "boolean",
                    description:
                        "After applying offsets, re-sample actual beam geometry against the target slab underside and apply a final downward correction when residual protrusion remains.",
                    default: true,
                },
                maxGeometryCorrectionMm: {
                    type: "number",
                    description:
                        "Safety cap for the post-apply residual geometry correction. Defaults to maxDeltaMm when omitted.",
                },
                maxSearchDistanceMm: {
                    type: "number",
                    description: "Vertical search range for floor detection.",
                    default: 3000,
                },
                endSampleDistanceMm: {
                    type: "number",
                    description: "Distance inset from each beam end used for raycast samples.",
                    default: 300,
                },
                beamSampleCount: {
                    type: "number",
                    description: "Number of samples along each beam for dominant_area_by_beam coverage detection.",
                    default: 9,
                },
                requireBothEnds: {
                    type: "boolean",
                    description: "Skip a beam unless both start and end floor undersides are found.",
                    default: true,
                },
                preserveVerticalStacks: {
                    type: "boolean",
                    description: "When true, beams sharing the same plan line and target floor move by the topmost beam's slab-alignment delta, preserving vertical spacing within stacked beams.",
                    default: false,
                },
                maxCount: {
                    type: "number",
                    description: "Maximum number of beams to process when beamIds are omitted.",
                    default: 500,
                },
                startOffsetParameterNames: {
                    type: "array",
                    items: { type: "string" },
                    description: "Optional fallback names for the start offset parameter.",
                },
                endOffsetParameterNames: {
                    type: "array",
                    items: { type: "string" },
                    description: "Optional fallback names for the end offset parameter.",
                },
            },
        },
    },
    {
        name: "sync_ifc_structural_to_native",
        description:
            "Preview or create native StructuralFraming and StructuralColumns from a linked IFC/Revit model. Uses linked geometry centroid/bounding data, creates reusable types by inferred section size, writes Link|Kind|Source tracking comments, and skips existing synced sources.",
        inputSchema: {
            type: "object",
            properties: {
                linkInstanceId: {
                    type: "number",
                    description: "Linked model instance ElementId from get_linked_models.",
                },
                dryRun: {
                    type: "boolean",
                    description: "Preview without creating native elements. Defaults to true unless apply is true.",
                    default: true,
                },
                apply: {
                    type: "boolean",
                    description: "Create native elements when true.",
                    default: false,
                },
                replaceExisting: {
                    type: "boolean",
                    description: "When true, delete existing native elements with the same IFC sync Link/Kind/Source tracking keys before recreating them. Use for correcting the base family or regenerated geometry.",
                    default: false,
                },
                includeFraming: {
                    type: "boolean",
                    description: "Include linked StructuralFraming elements.",
                    default: true,
                },
                includeColumns: {
                    type: "boolean",
                    description: "Include linked column elements.",
                    default: true,
                },
                framingCategory: {
                    type: "string",
                    description: "Linked source category for beams/framing.",
                    default: "StructuralFraming",
                },
                columnCategory: {
                    type: "string",
                    description: "Linked source category for columns. IFC imports often use Columns rather than StructuralColumns.",
                    default: "Columns",
                },
                baseFramingType: {
                    type: "string",
                    description: "Optional host StructuralFraming type/family used as the duplication base.",
                },
                baseColumnType: {
                    type: "string",
                    description: "Optional host StructuralColumns type/family used as the duplication base.",
                },
                autoColumnBaseType: {
                    type: "boolean",
                    description: "Automatically choose the native column base family from inferred IFC column geometry. Square hollow/large square columns use SHS; other steel sections use AE-Steel column.",
                    default: true,
                },
                baseSteelColumnType: {
                    type: "string",
                    description: "Optional host StructuralColumns type/family used as the steel column duplication base.",
                },
                baseShsColumnType: {
                    type: "string",
                    description: "Optional host StructuralColumns type/family used as the SHS square hollow column duplication base.",
                    default: "SHS",
                },
                baseRcColumnType: {
                    type: "string",
                    description: "Optional host StructuralColumns type/family used as the solid RC square column duplication base.",
                    default: "AE-RC方柱",
                },
                shsColumnMinSizeMm: {
                    type: "number",
                    description: "Minimum smaller side for automatic SHS classification when a column is nearly square.",
                    default: 350,
                },
                shsSquareToleranceMm: {
                    type: "number",
                    description: "Maximum width/depth difference for automatic SHS square classification.",
                    default: 25,
                },
                alignColumnTopsToFloorBottom: {
                    type: "boolean",
                    description: "When creating StructuralColumns from IFC, set the column top level/offset to the nearest host floor underside at the column center.",
                    default: true,
                },
                maxColumnTopSearchDistanceMm: {
                    type: "number",
                    description: "Maximum vertical distance used to find a host floor underside for column top alignment.",
                    default: 6000,
                },
                maxFraming: {
                    type: "number",
                    description: "Maximum linked framing elements to process.",
                    default: 5000,
                },
                maxColumns: {
                    type: "number",
                    description: "Maximum linked column elements to process.",
                    default: 5000,
                },
                batchSize: {
                    type: "number",
                    description: "Maximum native elements to create per Revit transaction. Capped at 100.",
                    default: 100,
                },
                minLengthMm: {
                    type: "number",
                    description: "Skip framing shorter than this inferred centerline length.",
                    default: 100,
                },
                sizeRoundMm: {
                    type: "number",
                    description: "Round inferred section dimensions to this increment.",
                    default: 5,
                },
                sourceTagPrefix: {
                    type: "string",
                    description: "Tracking prefix written to comments for idempotent re-runs.",
                    default: "IFC_STRUCT_SYNC",
                },
            },
            required: ["linkInstanceId"],
        },
    },
    {
        name: "align_columns_top_to_floor_bottom",
        description:
            "Align StructuralColumns so their actual geometry top reaches the underside of target floors. Can set column top attachment parameters and then apply a geometry residual correction.",
        inputSchema: {
            type: "object",
            properties: {
                columnIds: {
                    type: "array",
                    items: { type: "number" },
                    description: "Optional StructuralColumn ElementIds. If omitted, synced columns matching sourceTagPrefix are processed.",
                },
                floorIds: {
                    type: "array",
                    items: { type: "number" },
                    description: "Optional Floor ElementIds to restrict target slab undersides.",
                },
                sourceTagPrefix: {
                    type: "string",
                    description: "When columnIds are omitted, process only columns whose Comments contain this prefix. Use an empty string to process all StructuralColumns.",
                    default: "IFC_STRUCT_SYNC",
                },
                dryRun: {
                    type: "boolean",
                    description: "Preview without writing parameters. Defaults to true unless apply is true.",
                    default: true,
                },
                apply: {
                    type: "boolean",
                    description: "Set true to apply top level/offset, attachment, and residual geometry correction.",
                    default: false,
                },
                setTopAttachment: {
                    type: "boolean",
                    description: "Try to enable the Revit column top attachment parameters and set attachment offset to zero.",
                    default: true,
                },
                postGeometryCorrection: {
                    type: "boolean",
                    description: "After setting the target top reference, re-check actual column geometry and correct any remaining residual.",
                    default: true,
                },
                toleranceMm: {
                    type: "number",
                    description: "Residual tolerance for final geometry correction.",
                    default: 5,
                },
                maxDeltaMm: {
                    type: "number",
                    description: "Safety cap for any geometry correction.",
                    default: 6000,
                },
                maxSearchDistanceMm: {
                    type: "number",
                    description: "Vertical search range for floor underside detection.",
                    default: 6000,
                },
                maxCount: {
                    type: "number",
                    description: "Maximum number of columns to process when columnIds are omitted.",
                    default: 500,
                },
            },
        },
    },
];
