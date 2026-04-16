/**
 * 解析使用者手動編號的停車格，學習其排序邏輯
 */
import WebSocket from 'ws';

const PORT = parseInt(process.env.REVIT_MCP_PORT || '8964', 10);

function sendCommand(ws, name, params) {
    return new Promise((resolve) => {
        const reqId = 'req_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        const cmd = { CommandName: name, Parameters: params, RequestId: reqId };
        const listener = (data) => {
            try {
                const msg = JSON.parse(data.toString());
                if (msg.RequestId === reqId) { ws.off('message', listener); resolve(msg); }
            } catch (e) { /* ignore */ }
        };
        ws.on('message', listener);
        ws.send(JSON.stringify(cmd));
        setTimeout(() => { ws.off('message', listener); resolve({ Success: false, Message: 'Timeout' }); }, 30000);
    });
}

async function main() {
    console.log("連線至 Revit MCP Server...");
    const ws = new WebSocket(`ws://localhost:${PORT}`);
    
    ws.on('error', (err) => { console.error('連線錯誤:', err.message); process.exit(1); });

    ws.on('open', async () => {
        console.log('✅ 已連線\n');

        console.log("1. 取得所有停車格...");
        const res = await sendCommand(ws, 'query_elements', { category: 'Parking', maxCount: 1000 });
        const allParking = res.Data?.Elements || [];
        
        const motorcycles = allParking.filter(e => (e.Name || '').includes('機車'));
        console.log(`> 找到 ${motorcycles.length} 個機車停車格\n`);

        console.log("2. 讀取座標與手動編號...");
        const data = [];
        for (let i = 0; i < motorcycles.length; i++) {
            const m = motorcycles[i];
            
            // 讀取備註
            const infoRes = await sendCommand(ws, 'get_element_info', { elementId: m.ElementId });
            const params = infoRes.Data?.Parameters || [];
            const remarkParam = params.find(p => p.Name === '備註' || p.Name === 'Comments');
            
            if (remarkParam && remarkParam.Value) {
                const remark = parseInt(remarkParam.Value, 10);
                if (!isNaN(remark) && remark >= 578) {
                    // 取座標
                    const locRes = await sendCommand(ws, 'get_element_location', { elementId: m.ElementId });
                    const d = locRes.Data || locRes;
                    const center = d?.BoundingBox?.Center || d?.Location;
                    if (center) {
                        data.push({
                            id: m.ElementId,
                            remark: remark,
                            x: center.X,
                            y: center.Y
                        });
                    }
                }
            }
            if ((i + 1) % 50 === 0) console.log(`  進度 ${i + 1} / ${motorcycles.length}`);
        }

        console.log(`\n> 成功讀取 ${data.length} 個帶有手動編號的機車格\n`);

        if (data.length > 0) {
            // 依手動編號排序
            data.sort((a, b) => a.remark - b.remark);

            console.log("=== 手動編號路徑分析 ===");
            let currentXGroup = -1;
            let currentYGroup = -1;
            
            for (let i = 0; i < data.length; i++) {
                const d = data[i];
                // 第一筆或是 X/Y 有大幅變動時印出分隔線，方便觀察路徑轉折
                if (i > 0) {
                    const prev = data[i-1];
                    const dx = Math.abs(d.x - prev.x);
                    const dy = Math.abs(d.y - prev.y);
                    if (dx > 2000 || dy > 2000) {
                        console.log('  ------------------------ (路徑轉折)');
                    }
                }
                console.log(`[${d.remark}] ID:${d.id} | X:${Math.round(d.x)} , Y:${Math.round(d.y)}`);
                
                // 只印前 50 個避免洗版
                if (i >= 50) {
                    console.log("  ... (省略後續)");
                    break;
                }
            }
        }

        ws.close();
    });
}
main();
