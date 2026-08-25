/**
 * 工具註冊中心 — 根據 MCP_PROFILE 篩選載入的工具模組
 *
 * Profile 設定方式（AI Client config）：
 *   "env": { "MCP_PROFILE": "architect" }
 *
 * 可用 Profile：full（預設）, architect, mep, structural, fire-safety
 */

import { Tool } from "@modelcontextprotocol/sdk/types.js";
import { baseTools } from "./base-tools.js";
import { wallTools } from "./wall-tools.js";
import { roomTools } from "./room-tools.js";
import { corridorAnalysisTools } from "./corridor-analysis-tools.js";
import { visualizationTools } from "./visualization-tools.js";
import { scheduleTools } from "./schedule-tools.js";
import { mepTools } from "./mep-tools.js";

import { curtainWallTools } from "./curtain-wall-tools.js";
import { smokeExhaustTools } from "./smoke-exhaust-tools.js";
import { STAIR_COMPLIANCE_TOOLS } from "./stair-compliance-tools.js";
import { sheetTools } from "./sheet-tools.js";
import { detailComponentTools } from "./detail-component-tools.js";
import { dimensionTools } from "./dimension-tools.js";
import { dependentViewTools } from "./dependent-view-tools.js";
import { clashTools } from "./clash-tools.js";
import { doorWindowLegendTools } from "./door-window-legend-tools.js";
import { listSeedsTools } from "./list-seeds-tools.js";
import { structuralTools } from "./structural-tools.js";
import { scaffoldTools } from "./scaffold-tools.js";
import { dimensionTypeTools } from "./dimension-type-tools.js";
import { legendViewTools } from "./legend-view-tools.js";
import { dwgColumnTools } from "./dwg-column-tools.js";
import { dwgBeamTools } from "./dwg-beam-tools.js";
import { cadLinkTools } from "./cad-link-tools.js";
import { structureTools } from "./structure-tools.js";
import { parallelSectionTools } from "./parallel-section-tools.js";
import { smokeDetectorTools } from "./smoke-detector-tools.js";
import { gradingTools } from "./grading-tools.js";
import { detailCopyTools } from "./detail-copy-tools.js";
import { scopeBoxTools } from "./scope-box-tools.js";
import { viewCropBoxTools } from "./view-cropbox-tools.js";
import { textNoteTools } from "./text-note-tools.js";
import { titleblockAlignTools } from "./titleblock-align-tools.js";
import { viewCreationTools } from "./view-creation-tools.js";
import { viewportPositionTools } from "./viewport-position-tools.js";
import { crossDocumentTools } from "./cross-document-tools.js";
import { legendTools } from "./legend-tools.js";
import { revisionCloudTools } from "./revision-cloud-tools.js";
import { viewDuplicateTools } from "./view-duplicate-tools.js";
import { fillRegionTools } from "./fill-region-tools.js";
import { ifcStructuralSyncTools } from "./ifc-structural-sync-tools.js";
import { floorShapeTools } from "./floor-shape-tools.js";
import { forkRestoredTools } from "./fork-restored-tools.js";
import { codeIntegrityTools } from "./code-integrity-tools.js";

/**
 * Profile 對照表：每個 profile 包含哪些模組
 */
const PROFILE_MODULES: Record<string, Tool[][]> = {
    full: [baseTools, codeIntegrityTools, wallTools, roomTools, corridorAnalysisTools, visualizationTools, scheduleTools, mepTools, curtainWallTools, smokeExhaustTools, smokeDetectorTools, parallelSectionTools, STAIR_COMPLIANCE_TOOLS, sheetTools, detailComponentTools, dimensionTools, dependentViewTools, dwgColumnTools, dwgBeamTools, cadLinkTools, clashTools, doorWindowLegendTools, listSeedsTools, dimensionTypeTools, legendViewTools, structuralTools, structureTools, scaffoldTools, gradingTools, detailCopyTools, scopeBoxTools, viewCropBoxTools, textNoteTools, titleblockAlignTools, viewCreationTools, viewportPositionTools, crossDocumentTools, legendTools, revisionCloudTools, viewDuplicateTools, fillRegionTools, ifcStructuralSyncTools, floorShapeTools, forkRestoredTools],
    architect: [baseTools, codeIntegrityTools, wallTools, roomTools, corridorAnalysisTools, visualizationTools, scheduleTools, curtainWallTools, parallelSectionTools, STAIR_COMPLIANCE_TOOLS, sheetTools, detailComponentTools, dimensionTools, dependentViewTools, dwgColumnTools, dwgBeamTools, cadLinkTools, doorWindowLegendTools, listSeedsTools, dimensionTypeTools, legendViewTools, scaffoldTools, gradingTools, detailCopyTools, scopeBoxTools, viewCropBoxTools, textNoteTools, titleblockAlignTools, viewCreationTools, viewportPositionTools, crossDocumentTools, legendTools, revisionCloudTools, viewDuplicateTools, fillRegionTools, floorShapeTools, forkRestoredTools],
    mep: [baseTools, codeIntegrityTools, mepTools, scheduleTools, visualizationTools, smokeExhaustTools, smokeDetectorTools, parallelSectionTools, clashTools],
    structural: [baseTools, codeIntegrityTools, wallTools, visualizationTools, dwgColumnTools, dwgBeamTools, clashTools, structuralTools, structureTools, gradingTools, ifcStructuralSyncTools, floorShapeTools],
    "fire-safety": [baseTools, codeIntegrityTools, roomTools, corridorAnalysisTools, visualizationTools, smokeExhaustTools, smokeDetectorTools],
};

/**
 * 這個 fork 的 Revit 端（MCP/Core/CommandExecutor.cs）沒有對應的 command case，
 * 呼叫下去只會撞上 `default: throw new NotImplementedException`。
 *
 * 對 AI 而言，「工具存在但一定失敗」比「工具不存在」危險得多——看得到就會去呼叫，
 * 拿到例外之後就有可能改用臆測的數字把答案補完。所以這裡直接不註冊，
 * 讓它在工具清單裡就是不存在。
 *
 * 解除條件：等對應的 C# 實作進來（case 標籤出現在 CommandExecutor.cs）就把它從這裡移除。
 * scripts/verify-qaqc.ps1 的 Phase 9 會雙向檢查這份清單，多寫少寫都會被擋下來。
 */
const UNIMPLEMENTED_ON_THIS_FORK = new Set<string>([
    "adjust_section_datums",
    "analyze_corridor_width",
    "analyze_floor_slopes",
    "arrange_viewports_on_sheet",
    "create_columns_from_dwg",
    "create_curtain_wall_elevations",
    "create_level",
    "diagnose_curtain_wall_elevation_direction",
    "diagnose_curtain_wall_elevation_directions",
    "door-window-legend-tools",
    "get_dwg_column_layers",
    "list_dimension_types",
    "list_legend_views",
    "list_schedules",
    "preview_dwg_columns",
    "read_schedule",
    "rename_view",
    "scale_drafting_view_height",
    "scale_drafting_view_width",
]);

/**
 * 有些 command 的 case 被 `#if REVIT20xx_OR_GREATER` 包住（因為它用到該版本才有的 Revit API），
 * 在較舊的組態編譯時會整段被拿掉——工具還是註冊了，但那個 Revit 版本上呼叫下去一樣拋例外。
 *
 * MCP server 在註冊工具的當下還沒連上 Revit，不知道對面是哪一版，所以只能由使用者告知：
 * 設定環境變數 `REVIT_VERSION=2020`（或你實際部署的年份），低於門檻的工具就不會出現在清單裡。
 * 不設定時維持全部註冊（與舊行為相同）。
 *
 * 這份對照表必須與 C# 那邊的 `#if` 守衛一致；verify-qaqc.ps1 的 Phase 9-1b 會從 C# 源碼反推
 * 真實守衛並比對這裡，寫錯或漏寫都會被抓出來。
 */
const VERSION_GATED_TOOLS: Record<string, number> = {
    grade_toposolid_to_floors: 2024, // Toposolid 是 Revit 2024+ 的 API 型別
    align_floor_shape_line_to_cad: 2024, // Subelement / DeleteSubelement API
};

/**
 * 根據 MCP_PROFILE 環境變數註冊工具
 */
export function registerRevitTools(): Tool[] {
    const profile = process.env.MCP_PROFILE || "full";
    const modules = PROFILE_MODULES[profile] ?? PROFILE_MODULES.full;

    if (!PROFILE_MODULES[profile]) {
        console.error(`[Tools] Unknown MCP_PROFILE="${profile}", falling back to "full"`);
    }

    const rawTools = modules.flat();
    const toolMap = new Map<string, Tool>();
    for (const tool of rawTools) {
        toolMap.set(tool.name, tool);
    }

    const beforeGate = toolMap.size;
    for (const name of UNIMPLEMENTED_ON_THIS_FORK) {
        toolMap.delete(name);
    }
    const afterForkGate = toolMap.size;

    // 版本守衛：只有在使用者明講 REVIT_VERSION 時才生效，避免誤砍別人用得到的工具。
    const revitVersionRaw = process.env.REVIT_VERSION;
    const revitVersion = revitVersionRaw ? parseInt(revitVersionRaw, 10) : NaN;
    if (revitVersionRaw && Number.isNaN(revitVersion)) {
        console.error(`[Tools] Invalid REVIT_VERSION="${revitVersionRaw}", ignoring version gate`);
    }
    if (!Number.isNaN(revitVersion)) {
        for (const [name, minVersion] of Object.entries(VERSION_GATED_TOOLS)) {
            if (revitVersion < minVersion) {
                toolMap.delete(name);
            }
        }
    }

    const tools = Array.from(toolMap.values());
    const duplicateCount = rawTools.length - beforeGate;
    const forkGatedCount = beforeGate - afterForkGate;
    const versionGatedCount = afterForkGate - tools.length;
    console.error(
        `[Tools] Profile="${profile}", loaded ${tools.length} tools` +
        `${duplicateCount > 0 ? ` (${duplicateCount} duplicate definitions overridden)` : ""}` +
        `${forkGatedCount > 0 ? ` (${forkGatedCount} withheld: no Revit-side implementation on this fork)` : ""}` +
        `${versionGatedCount > 0 ? ` (${versionGatedCount} withheld:需要較新的 Revit，REVIT_VERSION=${revitVersion})` : ""}`
    );
    return tools;
}
