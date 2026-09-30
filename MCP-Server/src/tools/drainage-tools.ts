import { Tool } from "@modelcontextprotocol/sdk/types.js";
const id = { type: "integer", minimum: 1 };
const number = { type: "number" };
const text = { type: "string", minLength: 1 };
export const drainageTools: Tool[] = [
    {
        name: "scan_drainage_cad",
        description: "唯讀盤點指定圖紙/平面視圖的 CAD 來源、母視圖、樓層、轉換。選擇 includeCircles 時擷取指定圖層完整圓與互補半圓；圓半徑只供出圖，不當實際管徑。不自動判讀文字或符號。裁剪外包框僅粗篩。最多30視圖，超量直接拒絕，不回傳假完整結果。",
        inputSchema: { type: "object", properties: {
            sheetNumbers: { type: "array", items: text, minItems: 1 },
            viewIds: { type: "array", items: id, minItems: 1, maxItems: 30 },
            includeCircles: { type: "boolean", default: false },
            layers: { type: "array", items: text, minItems: 1 },
            maxCircles: { type: "integer", minimum: 1, maximum: 10000, default: 2000 },
        } },
    },
    {
        name: "preview_drainage_review",
        description: "唯讀排水候選檢核：重新讀 CAD 圓心，區分已核對的落水頭/落水管與 up/down/both/unknown 方向，以實際外徑及明確高度建立碰撞包絡。公稱吋數不換算外徑。跨層僅回傳最近已提供標高的候選，非確認接續；落水頭出水路徑、天溝與符號複製列待確認。目前不提供寫入 receipt 或出圖。",
        inputSchema: { type: "object", properties: {
            points: { type: "array", minItems: 1, maxItems: 50, items: { type: "object", properties: {
                viewId: id, cadId: id, circleKey: text, label: text,
                kind: { type: "string", enum: ["pipe", "head"] },
                direction: { type: "string", enum: ["up", "down", "both", "unknown"] },
                directionEvidence: text, system: text, evidence: text, verified: { type: "boolean" },
                physicalDiameterMm: { type: "number", exclusiveMinimum: 0 }, dimensionEvidence: text,
                zMinMm: number, zMaxMm: number, requiresGutter: { type: "boolean", default: false },
            }, required: ["viewId", "cadId", "circleKey", "label", "kind", "direction", "system", "verified"] } },
            clearanceMm: { type: "number", minimum: 0 },
            matchRadiusMm: { type: "number", exclusiveMinimum: 0 },
            alignmentToleranceMm: { type: "number", minimum: 0 },
            obstacleCategories: { type: "array", minItems: 1, items: text, description: "明確 BuiltInCategory 名稱；所有階段/設計選項均保守納入" },
            linkInstanceIds: { type: "array", items: id, description: "指定建築/結構連結；主模型一律檢查" },
        }, required: ["points", "clearanceMm", "matchRadiusMm", "alignmentToleranceMm", "obstacleCategories"] },
    },
];
