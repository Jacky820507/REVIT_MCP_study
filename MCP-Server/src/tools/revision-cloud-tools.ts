import { Tool } from "@modelcontextprotocol/sdk/types.js";

export const revisionCloudTools: Tool[] = [
    {
        name: "scan_revision_clouds",
        description: "Scan all revision clouds in the model and report their revision info (sequence/description/date), owning view, and containing sheet (if already placed). Set writeBack=true to also write a stable markPrefix-based reply number into each cloud's Mark parameter and a location string into Comments — this modifies the model.",
        inputSchema: {
            type: "object",
            properties: {
                writeBack: {
                    type: "boolean",
                    description: "true writes Mark/Comments back to the model (modifies the model). Clouds already numbered with markPrefix keep their number; unnumbered clouds continue from the current max. Default false (read-only scan).",
                    default: false,
                },
                markPrefix: {
                    type: "string",
                    description: "Prefix used for the reply number written to Mark, e.g. '釋疑' -> '釋疑7'.",
                    default: "釋疑",
                },
            },
        },
    },
    {
        name: "add_cloud_views_to_sheets",
        description: "Create new sheets for every view that has a revision cloud but is not yet placed on any sheet, and add that view as a viewport on the new sheet. Views already on a sheet, or that fail Viewport.CanAddViewToSheet, are skipped with a reason. Set dryRun=true to preview the planned sheets/viewports without modifying the model.",
        inputSchema: {
            type: "object",
            properties: {
                titleBlockId: {
                    type: "number",
                    description: "Title block family symbol ElementId for the new sheets. Optional; if omitted, the project's first title block type is used (reported back as TitleBlockUsed).",
                },
                sheetNumberPrefix: {
                    type: "string",
                    description: "Prefix for auto-generated sheet numbers.",
                    default: "RQ-",
                },
                startNumber: {
                    type: "number",
                    description: "Starting number for auto-generated sheet numbers; advances automatically past any number already in use.",
                    default: 1,
                },
                dryRun: {
                    type: "boolean",
                    description: "true previews which sheets/viewports would be created and which views would be skipped (and why), without modifying the model. Recommended before a real run.",
                    default: false,
                },
            },
        },
    },
    {
        name: "export_revision_excel",
        description: "Export a single-sheet Excel checklist ('釋疑清單') listing every revision cloud with its reply number, revision info, owning view/sheet, and blank reply/reply-by/reply-date columns for other disciplines to fill in.",
        inputSchema: {
            type: "object",
            properties: {
                outputPath: {
                    type: "string",
                    description: "Output .xlsx path. Optional; defaults to the project directory with a timestamped filename.",
                },
            },
        },
    },
];
