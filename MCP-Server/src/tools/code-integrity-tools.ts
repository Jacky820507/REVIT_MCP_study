import { Tool } from "@modelcontextprotocol/sdk/types.js";

/**
 * Taiwan building-code model integrity tools.
 * These tools inspect the active Revit document only; they do not change the model
 * and they do not decide whether a current legal numeric requirement is satisfied.
 */
export const codeIntegrityTools: Tool[] = [
    {
        name: "audit_code_inputs",
        description:
            "唯讀檢查目前開啟的 Revit 模型是否具備台灣建築法規 BIM 檢討所需的資料輸入：專案法規參數、Area 欄位、樓層、必要構件類別、指定圖面視圖及 AreaPlan 是否有可用 Area 實例。結果只代表模型資料完整性，不代表現行法規合規；不開啟 Transaction、不修改模型。回傳會區分 BLOCKED、CONDITIONAL、READY gate，並保留 finding 證據。可傳入專案規則包覆寫預設檢查項目。",
        inputSchema: {
            type: "object",
            properties: {
                rulePackId: {
                    type: "string",
                    description: "規則包識別碼，供報告追蹤；不會把規則包當成現行法規。",
                    default: "taiwan-building-code-model-integrity",
                },
                requiredProjectParameters: {
                    type: "array",
                    items: { type: "string" },
                    description:
                        "要在 Project Information 找到的實際參數名稱。省略時使用 REVIT_112 操作契約中的 Law_* 欄位。",
                },
                requiredAreaParameters: {
                    type: "array",
                    items: { type: "string" },
                    description:
                        "要在 Area 元素上找到的法規檢討欄位。省略時檢查 REVIT_112 面積圖流程中的 Law_建管-用途類組、Law_技規-法定名稱。",
                },
                requiredLevelNames: {
                    type: "array",
                    items: { type: "string" },
                    description:
                        "必要樓層名稱，採不分大小寫的完整名稱比對；例如 ['1FL','RFL']。",
                },
                recommendedLevelNames: {
                    type: "array",
                    items: { type: "string" },
                    description: "建議但非必要的樓層名稱；缺少時產生 WARNING。",
                },
                requiredCategories: {
                    type: "array",
                    items: { type: "string" },
                    description:
                        "必要模型類別名稱，可用 Walls/Floors/Doors/Windows/Columns/StructuralFraming/Stairs 或中文別名。",
                },
                checkNamedViews: {
                    type: "boolean",
                    description: "是否檢查指定圖面/面積視圖名稱關鍵字；預設 true。",
                    default: true,
                },
                checkAreaPlanContent: {
                    type: "boolean",
                    description:
                        "是否進一步檢查匹配到的 AreaPlan 是否含 Area 實例；視圖存在但沒有 Area 時產生 WARNING；預設 true。",
                    default: true,
                },
                requiredViewNameKeywords: {
                    type: "array",
                    items: { type: "string" },
                    description:
                        "必要視圖或視圖類型名稱關鍵字，採不分大小寫的包含比對；省略時使用 REVIT_112 面積圖面名稱契約。",
                },
                includeElementSamples: {
                    type: "boolean",
                    description: "是否在類別結果中附少量元素 ID/名稱樣本；預設 false。",
                    default: false,
                },
                maxElementSamples: {
                    type: "integer",
                    minimum: 1,
                    maximum: 50,
                    description: "每個類別最多回傳的元素樣本數；預設 10。",
                    default: 10,
                },
            },
        },
    },
];
