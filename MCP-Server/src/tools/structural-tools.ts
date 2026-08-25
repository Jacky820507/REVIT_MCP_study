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
    // NOTE 2026-08-03: the duplicate "sync_ifc_structural_to_native" definition that used to sit here
    // was removed — ifc-structural-sync-tools.ts owns that tool (identical 24-key schema).
    // Two definitions of one tool name meant registerRevitTools() silently kept whichever module
    // came last in PROFILE_MODULES. One tool name = one definition.
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
