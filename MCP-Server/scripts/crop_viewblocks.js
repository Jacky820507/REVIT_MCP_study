/**
 * 【8 區塊網格矩陣裁切腳本】
 * ========================================
 * 針對「物流中心三層平面圖(分圖)-1」依照 X 軸 5 條線與 Y 軸 3 條線組合成的 8 個區間進行批次裁切。
 */
import WebSocket from 'ws';

const config = {
    parentViewName: "物流中心三層平面圖(分圖)-1",
    xGrids: ["B28", "B23", "B18", "B13", "B8"],
    yGrids: ["CB", "BE", "BA"],
    offset_mm: 500
};

const ws = new WebSocket('ws://localhost:8964');

ws.on('open', async () => {
    console.log("=== 開始執行 8 區塊矩陣裁切 ===");
    console.log(`母視圖: ${config.parentViewName}`);

    // 1. 產生所有網格區間組合
    const xSegments = [];
    for (let i = 0; i < config.xGrids.length - 1; i++) {
        xSegments.push([config.xGrids[i], config.xGrids[i + 1]]);
    }

    const ySegments = [];
    for (let j = 0; j < config.yGrids.length - 1; j++) {
        ySegments.push([config.yGrids[j], config.yGrids[j + 1]]);
    }

    const tasks = [];
    for (const ySeg of ySegments) {
        for (const xSeg of xSegments) {
            tasks.push({ x: xSeg, y: ySeg });
        }
    }

    console.log(`預計產生交叉區域: ${tasks.length} 個`);

    // 2. 先抓取母視圖 ID
    ws.send(JSON.stringify({
        CommandName: 'get_all_views',
        Parameters: { viewType: "FloorPlan" },
        RequestId: 'get_parent'
    }));

    let parentViewId = null;
    let taskQueue = [...tasks];
    let currentTask = null;
    let cachedBounds = null;

    ws.on('message', (data) => {
        const res = JSON.parse(data.toString());
        if (!res.Success) {
            console.error("❌ 錯誤:", res.Error);
            ws.close();
            return;
        }

        if (res.RequestId === 'get_parent') {
            const found = res.Data.Views.find(v => v.Name === config.parentViewName);
            if (!found) {
                console.error(`❌ 找不到母視圖: ${config.parentViewName}`);
                ws.close();
                return;
            }
            parentViewId = found.ElementId;
            console.log(`> 找到母視圖 ID: ${parentViewId}`);
            processNextTask();
        }
        else if (res.RequestId === 'calc_bounds') {
            cachedBounds = res.Data;
            const xLabel = currentTask.x.join("-");
            const yLabel = currentTask.y.join("-");

            console.log(`> 建立視圖區塊 [${xLabel}, ${yLabel}]...`);
            ws.send(JSON.stringify({
                CommandName: 'create_dependent_views',
                Parameters: {
                    parentViewIds: [parentViewId],
                    min: cachedBounds.min,
                    max: cachedBounds.max,
                    suffixName: `${xLabel}_${yLabel}`
                },
                RequestId: 'create_view'
            }));
        }
        else if (res.RequestId === 'create_view') {
            console.log(`  ✅ 已建立: ${res.Data.Views[0].NewViewName}`);
            processNextTask();
        }
    });

    function processNextTask() {
        if (taskQueue.length === 0) {
            console.log("========================================");
            console.log("✅ 所有 8 個區塊處理完畢！");
            ws.close();
            return;
        }
        currentTask = taskQueue.shift();
        ws.send(JSON.stringify({
            CommandName: 'calculate_grid_bounds',
            Parameters: {
                xGrids: currentTask.x,
                yGrids: currentTask.y,
                offset_mm: config.offset_mm
            },
            RequestId: 'calc_bounds'
        }));
    }
});

ws.on('error', (e) => console.error('❌ Socket Error:', e.message));
ws.on('close', () => process.exit(0));
