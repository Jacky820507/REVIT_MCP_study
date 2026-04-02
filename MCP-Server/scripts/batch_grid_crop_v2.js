/**
 * 【批次產生網格分區視圖】 - 驗證腳本 v2
 * ========================================
 * 針對 "一層平面圖-TEST" 與 "三層平面圖-TEST"
 * 根據網格 B28, B23, B18, B13, B8 與 CB, BE, BA 的交集建立 8 個分區視圖。
 */
import WebSocket from 'ws';

const config = {
    parentViews: ["一層平面圖-TEST", "三層平面圖-TEST"],
    xGridSeq: ["B28", "B23", "B18", "B13", "B8"],
    yGridSeq: ["CB", "BE", "BA"],
    offset_mm: 1000
};

const ws = new WebSocket('ws://localhost:8964');

async function sendCommand(command, params) {
    return new Promise((resolve, reject) => {
        const requestId = Math.random().toString(36).substring(7);
        const payload = JSON.stringify({ CommandName: command, Parameters: params, RequestId: requestId });
        
        const handler = (data) => {
            const res = JSON.parse(data.toString());
            if (res.RequestId === requestId) {
                ws.off('message', handler);
                if (res.Success) resolve(res.Data);
                else reject(new Error(res.Error));
            }
        };
        
        ws.on('message', handler);
        ws.send(payload);
    });
}

ws.on('open', async () => {
    try {
        console.log("=== 開始執行網格分區視圖建立 ===");

        // 1. 取得所有視圖以獲取 ID
        console.log("正在搜尋母視圖...");
        const viewRes = await sendCommand('get_all_views', { viewType: "FloorPlan" });
        const allViews = viewRes.Views || [];
        
        const targetParentIds = config.parentViews.map(name => {
            const v = allViews.find(view => view.Name === name);
            if (!v) console.warn(`⚠️ 找不到母視圖: ${name}`);
            return v ? v.ElementId : null;
        }).filter(id => id !== null);

        if (targetParentIds.length === 0) {
            throw new Error("找不到任何目標母視圖");
        }

        // 2. 迴圈處理網格對
        for (let i = 0; i < config.xGridSeq.length - 1; i++) {
            for (let j = 0; j < config.yGridSeq.length - 1; j++) {
                const x1 = config.xGridSeq[i];
                const x2 = config.xGridSeq[i+1];
                const y1 = config.yGridSeq[j];
                const y2 = config.yGridSeq[j+1];
                
                const suffix = `${x1}-${x2}_${y1}-${y2}`;
                console.log(`\n正在處理分區: ${suffix}`);

                // 計算邊界
                const bounds = await sendCommand('calculate_grid_bounds', {
                    x_grids: [x1, x2],
                    y_grids: [y1, y2],
                    offset_mm: config.offset_mm
                });

                // 建立視圖
                const createRes = await sendCommand('create_dependent_views', {
                    parentViewIds: targetParentIds,
                    min: bounds.min,
                    max: bounds.max,
                    suffixName: suffix
                });

                console.log(`✅ 成功建立 ${createRes.Count} 個視圖`);
            }
        }

        console.log("\n=== 所有作業執行完畢 ===");
    } catch (err) {
        console.error("❌ 執行失敗:", err.message);
    } finally {
        ws.close();
    }
});

ws.on('error', (e) => console.error('❌ Socket Error:', e.message));
ws.on('close', () => process.exit(0));
