/**
 * 【批次產生從屬視圖並設定網格裁剪框】
 * ========================================
 * 執行前請確認已開啟目標母視圖所在的 Revit 模型（Revit 2020）。
 */
import WebSocket from 'ws';

// ----------------------------------------
// 參數設定區 (可依專案需求修改)
// ----------------------------------------
const config = {
    // 1. 網格範圍 (輸入名稱)
    xGrids: ["B8", "B1"],
    yGrids: ["CA", "BA"],

    // 2. 邊界向外偏移容差 (單位：公釐 mm)
    offset_mm: 500, // 縮小一點避免超出範圍太遠

    // 3. 母視圖名稱特徵
    // 根據 list_sheets 結果，您的模型視圖名稱可能包含 "一層平面圖"、"二層平面圖" 等
    targetParentViewNames: [
        "物流中心三層平面圖(分圖)-1"
    ]
};

const ws = new WebSocket('ws://localhost:8964');

ws.on('open', () => {
    console.log("=== 開始執行批次從屬視圖裁剪 ===");
    console.log(`- 網格 X 軸: ${config.xGrids.join(", ")}`);
    console.log(`- 網格 Y 軸: ${config.yGrids.join(", ")}`);

    // 第一步：計算邊界
    console.log("正在計算網格邊界 (BoundingBox)...");
    ws.send(JSON.stringify({
        CommandName: 'calculate_grid_bounds',
        Parameters: {
            xGrids: config.xGrids,
            yGrids: config.yGrids,
            offset_mm: config.offset_mm
        },
        RequestId: 'step1_bounds'
    }));
});

let stage = 'get_bounds';
let cachedBounds = null;

ws.on('message', (data) => {
    const res = JSON.parse(data.toString());
    if (!res.Success) {
        console.error("❌ 錯誤:", res.Error);
        ws.close();
        return;
    }

    if (stage === 'get_bounds') {
        cachedBounds = res.Data;
        console.log(`> 計算完成，Min X: ${cachedBounds.min.x.toFixed(1)}, Y: ${cachedBounds.min.y.toFixed(1)}`);

        stage = 'get_views';
        console.log("正在尋找目標母視圖...");
        ws.send(JSON.stringify({
            CommandName: 'get_all_views',
            Parameters: { viewType: "FloorPlan" },
            RequestId: 'step2_views'
        }));
    }
    else if (stage === 'get_views') {
        const allViews = res.Data.Views || [];
        let parentViewIds = [];

        for (const targetName of config.targetParentViewNames) {
            const foundView = allViews.find(v => v.Name.includes(targetName));
            if (foundView) {
                parentViewIds.push(foundView.ElementId);
                console.log(`> 找到母視圖: ${foundView.Name} (ID: ${foundView.ElementId})`);
            }
        }

        if (parentViewIds.length === 0) {
            console.error("❌ 找不到任何目標母視圖，腳本終止。");
            ws.close();
            return;
        }

        stage = 'create_views';
        console.log(`正在處理 ${parentViewIds.length} 個母視圖的裁切作業...`);
        ws.send(JSON.stringify({
            CommandName: 'create_dependent_views',
            Parameters: {
                parentViewIds: parentViewIds,
                min: cachedBounds.min,
                max: cachedBounds.max,
                suffixName: ""
            },
            RequestId: 'step3_create'
        }));
    }
    else {
        console.log("========================================");
        console.log(`✅ 執行完成！共成功建立 ${res.Data.CreatedCount} 個從屬視圖`);

        if (res.Data.Views && res.Data.Views.length > 0) {
            res.Data.Views.forEach(v => {
                console.log(`  - 母圖: ${v.ParentName} \t -> 新建: ${v.NewViewName}`);
            });
        }
        ws.close();
    }
});

ws.on('error', (e) => console.error('❌ Socket Error:', e.message));
ws.on('close', () => process.exit(0));
setTimeout(() => { ws.close(); }, 60000); // 延長至 1 分鐘避免大專案超時
