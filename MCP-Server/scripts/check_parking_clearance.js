import WebSocket from 'ws';

const PORT = 8964;
const CLEARANCE_LIMIT = 2100; // mm

async function sendCommand(ws, name, params) {
    return new Promise((resolve) => {
        const reqId = 'req_' + Date.now() + Math.random();
        const cmd = { CommandName: name, Parameters: params, RequestId: reqId };
        const listener = (data) => {
            const msg = JSON.parse(data.toString());
            if (msg.RequestId === reqId) {
                ws.off('message', listener);
                resolve(msg);
            }
        };
        ws.on('message', listener);
        ws.send(JSON.stringify(cmd));
    });
}

const ws = new WebSocket(`ws://localhost:${PORT}`);

ws.on('open', async () => {
    console.log('🚀 開始執行 B1F 停車位淨空高度檢查...');

    try {
        // 1. 取得當前視圖
        const viewRes = await sendCommand(ws, 'get_active_view', {});
        if (!viewRes.Success) throw new Error('無法取得當前視圖');
        const view = viewRes.Data;
        const viewId = view.Id || view.ElementId;
        const targetLevel = "C-B1F";
        console.log(`📍 目前視圖: ${view.Name}, 目標樓層: ${targetLevel}`);

        // 2. 搜尋所有停車位元素 (不限樓層，帶入 "樓層" 欄位)
        console.log('🔍 正在搜尋所有停車位 (包含 "樓層" 資訊)...');
        let parkingRes = await sendCommand(ws, 'query_elements', {
            category: 'Parking',
            maxCount: 1000,
            returnFields: ["樓層", "標註"]
        });

        if (!parkingRes.Success || !parkingRes.Data || parkingRes.Data.Elements.length === 0) {
            console.log('⚠️  未找到 "Parking" 類別，嘗試 "停車場"...');
            parkingRes = await sendCommand(ws, 'query_elements', {
                category: '停車場',
                maxCount: 1000,
                returnFields: ["樓層", "標註"]
            });
        }

        if (!parkingRes.Success) throw new Error('查詢停車位失敗');
        const allParking = parkingRes.Data.Elements || [];
        console.log(`✅ 找到 ${allParking.length} 個停車位 (全專案)。`);

        // 3. 過濾目標樓層 (比對 "樓層" 參數)
        const parkingSpaces = allParking.filter(p => {
            const level = p["樓層"] || "";
            return level.includes("B1F");
        });

        console.log(`✅ 在目標樓層找到 ${parkingSpaces.length} 個停車位。`);
        if (parkingSpaces.length === 0) {
            if (allParking.length > 0) {
                console.log('📝 範例 "樓層" 參數值:', allParking[0]["樓層"]);
                console.log('📝 全部 "樓層" 參數值:', Array.from(new Set(allParking.map(p => p["樓層"]))));
            }
            console.log('⚠️  目標樓層無停車位，結束。');
            return;
        }

        let failCount = 0;
        let passCount = 0;
        const failIds = [];

        // 4. 逐一檢核
        for (let i = 0; i < parkingSpaces.length; i++) {
            const ps = parkingSpaces[i];
            const name = ps.Name || '未知';
            const id = ps.ElementId;
            
            // 取得中心點
            const locRes = await sendCommand(ws, 'get_element_location', { elementId: id });
            
            if (i === 0) console.log('🔍 [DEBUG] First locRes:', JSON.stringify(locRes, null, 2));

            if (!locRes.Success || !locRes.Data) {
                continue;
            }
            
            // 優先使用 LocationPoint，若無則使用 BoundingBox 中心
            const rawCenter = locRes.Data.Location || (locRes.Data.BoundingBox ? locRes.Data.BoundingBox.Center : null);
            if (!rawCenter) {
                console.log(`⚠️  無座標 ID: ${id}`);
                continue;
            }

            // 轉為小寫座標，並處理 0 值為真值 (以免 falsy fallback)
            const center = {
                x: (rawCenter.X !== undefined) ? rawCenter.X : (rawCenter.x || 0),
                y: (rawCenter.Y !== undefined) ? rawCenter.Y : (rawCenter.y || 0),
                z: (rawCenter.Z !== undefined) ? rawCenter.Z : (rawCenter.z || 0)
            };
            
            // 執行淨空高度偵測 (向 Z 軸正上方)
            const clearanceRes = await sendCommand(ws, 'measure_clearance', {
                origin: center,
                direction: { x: 0, y: 0, z: 1 }
            });

            if (i === 0) console.log('🔍 [DEBUG] First clearanceRes:', JSON.stringify(clearanceRes, null, 2));

            if (!clearanceRes.Success) {
                console.log(`⚠️  偵測錯誤 ID: ${id} - ${clearanceRes.Error}`);
                continue;
            }

            if (clearanceRes.Data.Hit) {
                const distance = clearanceRes.Data.Distance;
                if (distance <= CLEARANCE_LIMIT) {
                    console.log(`❌ [FAIL] ID: ${id} (${name}) - 淨空高度: ${distance.toFixed(1)} mm (<= 2100mm)`);
                    failCount++;
                    failIds.push(id);
                } else {
                    passCount++;
                }
            } else {
                // 未擊中任何障礙物，視為通過（或高度無限大）
                passCount++;
            }

            if ((i + 1) % 50 === 0) {
                console.log(`... 已處理 ${i + 1}/${parkingSpaces.length}`);
            }
        }

        // 5. 圖形覆寫 (不合格變紅)
        if (failIds.length > 0) {
            console.log(`\n🎨 正在為 ${failIds.length} 個不合格車位標記紅色...`);
            for (const id of failIds) {
                await sendCommand(ws, 'override_element_graphics', {
                    elementId: id,
                    viewId: viewId,
                    surfaceFillColor: { r: 255, g: 0, b: 0 }, // 紅色
                    surfacePatternId: -1, // 實心
                    transparency: 30
                });
            }
            console.log('✅ 標記完成。');
        }

        // 6. 總結報告
        console.log('\n--- 檢核結果總則 ---');
        console.log(`✅ 通過數量: ${passCount}`);
        console.log(`❌ 不合格數量: ${failCount}`);
        if (parkingSpaces.length > 0) {
            console.log(`📊 合格率: ${((passCount / parkingSpaces.length) * 100).toFixed(1)}%`);
        }
        console.log('------------------');

    } catch (err) {
        console.error('❌ 執行出錯:', err.message);
    } finally {
        ws.close();
        process.exit(0);
    }
});

ws.on('error', (err) => {
    console.error('❌ WebSocket 連線失敗:', err.message);
    console.log('請確保 Revit 中的 MCP 服務已啟動。');
});
