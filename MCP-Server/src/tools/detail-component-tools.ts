import { Tool } from "@modelcontextprotocol/sdk/types.js";

export const detailComponentTools: Tool[] = [
    {
        name: "get_detail_components",
        description: "查詢專案中的詳圖元件（Detail Components）實例。可依族群名稱篩選，回傳每個實例的 ID、族群名稱、類型名稱、所屬視圖及參數。",
        inputSchema: {
            type: "object",
            properties: {
                familyName: { type: "string", description: "族群名稱篩選（選填，模糊比對）" },
            },
        },
    },
    {
        name: "create_detail_component_type",
        description: "指定詳圖項目族群，複製並設定新名稱（圖紙編號-圖紙名稱-詳圖名稱），同時自動填寫 詳圖圖號、圖說名稱、詳圖名稱、詳圖編號 等類型參數。",
        inputSchema: {
            type: "object",
            properties: {
                sheetNumber: { type: "string", description: "目標圖紙編號（如 A101）" },
                detailName: { type: "string", description: "詳圖名稱（使用者輸入的新詳圖名稱）" },
                familyName: { type: "string", description: "要複製的基礎詳圖項目族群名稱（選填，若未提供則預設尋找 'AE-圖號'）" },
                detailNumber: { type: "string", description: "詳圖編號（選填，預設為 '1'）" },
            },
            required: ["sheetNumber", "detailName"],
        },
    },
    {
        name: "sync_detail_component_numbers",
        description: "自動同步所有 AE-圖號詳圖元件的類型參數（詳圖圖號、圖說名稱）與其所在圖紙的編號和名稱。安全模式保留兩種作法：1) 類型名稱以該圖紙編號開頭；2) 圖紙編號以類型名稱中的圖紙前綴開頭。未匹配者跳過，避免影響共用標準詳圖。",
        inputSchema: { type: "object", properties: {} },
    },
    {
        name: "create_detail_component_types_from_sheet_viewports",
        description: "指定圖紙號碼，偵測該圖紙所有視埠（Viewport），以視埠詳圖編號與視圖名稱批次建立 AE-圖號詳圖編號標頭-3.5mm 詳圖項目類型。類型名稱規則為 詳圖圖號-圖說名稱-詳圖用途；詳圖用途等於視埠視圖名稱。預設 dryRun=true 僅預覽。",
        inputSchema: {
            type: "object",
            properties: {
                sheetNumber: { type: "string", description: "圖紙號碼，例如 A101 或 ARB-D0921" },
                familyName: { type: "string", description: "詳圖項目族群名稱", default: "AE-圖號詳圖編號標頭-3.5mm" },
                dryRun: { type: "boolean", description: "true 時只回傳將建立/更新的類型清單，不寫入 Revit", default: true },
                overwriteExisting: { type: "boolean", description: "既有同名類型存在時是否更新其類型參數；false 時跳過", default: false },
            },
            required: ["sheetNumber"],
        },
    },
    {
        name: "create_detail_component_types_from_metadata",
        description: "依外部來源（例如 PDF OCR/人工校正表）的 metadata 批次建立或更新詳圖項目類型，不需要 Revit 內已有對應圖紙。類型名稱規則為 詳圖圖號-圖說名稱-詳圖名稱，並寫入 詳圖圖號、圖說名稱、詳圖編號、詳圖名稱。預設 dryRun=true。",
        inputSchema: {
            type: "object",
            properties: {
                familyName: { type: "string", description: "詳圖項目族群名稱", default: "AE-圖號詳圖編號標頭-3.5mm" },
                dryRun: { type: "boolean", description: "true 時只預覽，不寫入 Revit", default: true },
                overwriteExisting: { type: "boolean", description: "同名類型已存在時是否更新類型參數；false 時跳過", default: false },
                items: {
                    type: "array",
                    description: "要建立或更新的詳圖類型資料",
                    items: {
                        type: "object",
                        properties: {
                            sheetNumber: { type: "string", description: "詳圖圖號 / 圖紙號碼，例如 ARB-D09001" },
                            sheetName: { type: "string", description: "圖說名稱，例如 施工大樣詳圖(一)" },
                            detailNumber: { type: "string", description: "詳圖編號，例如 1" },
                            detailName: { type: "string", description: "詳圖名稱，例如 面磚地坪詳圖" },
                            typeName: { type: "string", description: "可選，自訂類型名稱；未提供時使用 詳圖圖號-圖說名稱-詳圖名稱" },
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
    {
        name: "list_family_symbols",
        description: "列出專案中的 FamilySymbol（族群類型）。可依名稱篩選，回傳 ID、類型名稱、族群名稱、類別。用於查詢可用的詳圖項目族群。",
        inputSchema: {
            type: "object",
            properties: {
                filter: { type: "string", description: "名稱篩選關鍵字（選填，模糊比對族群名稱或類型名稱）" },
            },
        },
    },
];
