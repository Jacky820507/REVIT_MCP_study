/**
 * 第二次提取：找汽車群組 + 取得全部停車格座標
 */
import WebSocket from 'ws';
import { writeFileSync, readFileSync } from 'fs';

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
    const ws = new WebSocket(`ws://localhost:${PORT}`);
    ws.on('error', (err) => { console.error('連線錯誤:', err.message); process.exit(1); });

    ws.on('open', async () => {
        console.log('✅ 已連線\n');

        // 載入已有資料
        const existing = JSON.parse(readFileSync('e:/RevitMCP/MCP-Server/scratch/parking_analysis.json', 'utf-8'));

        // === 1. 查所有 GenericModel 元素名稱，找汽車群組 ===
        console.log('=== 查 GenericModel 找汽車群組 ===');
        const gm = await sendCommand(ws, 'query_elements', { category: 'GenericModel', maxCount: 200 });
        const gmEls = gm.Data?.Elements || [];
        
        // 看看有無 "汽車" 相關的
        for (const el of gmEls) {
            if ((el.Name || '').includes('停車') || (el.Name || '').includes('汽車')) {
                console.log(`  ID: ${el.ElementId}, Name: ${el.Name}`);
            }
        }

        // 嘗試取得 element_info 來看是不是群組
        // 先看所有不重複的名稱
        const names = [...new Set(gmEls.map(e => e.Name))];
        console.log(`不重複名稱 (${names.length}):`, names.join(', '));
        
        // === 2. 搜尋含 "模型線" 的非機車群組 ===
        const modelLineGroups = gmEls.filter(e => (e.Name || '').includes('模型線'));
        console.log(`\n含「模型線」的元素: ${modelLineGroups.length}`);
        for (const g of modelLineGroups) {
            console.log(`  ID: ${g.ElementId}, Name: ${g.Name}`);
            // 嘗試 get_group_members
            const r = await sendCommand(ws, 'get_group_members', { groupId: g.ElementId });
            if (r.Success) {
                const d = r.Data;
                console.log(`  → 群組: ${d.GroupName}, 成員: ${d.MemberCount}`);
                if (!existing[`group_${g.ElementId}`]) {
                    existing[`group_${g.ElementId}`] = d;
                }
                for (const m of d.Members) {
                    const loc = m.Location;
                    if (loc?.Type === 'Curve') {
                        console.log(`    線段 ID:${m.ElementId} | (${loc.StartX}, ${loc.StartY}) → (${loc.EndX}, ${loc.EndY})`);
                    } else {
                        console.log(`    ID:${m.ElementId} Cat:${m.Category} Name:${m.Name}`);
                    }
                }
            } else {
                console.log(`  → 非群組: ${r.Error}`);
            }
        }

        // === 3. 取得所有停車格座標 (分批) ===
        console.log('\n=== 取得全部停車格座標 ===');
        const parking1 = await sendCommand(ws, 'query_elements', { category: 'Parking', maxCount: 500 });
        const allParking = parking1.Data?.Elements || [];
        console.log(`總停車格: ${allParking.length}`);

        const motorcycles = allParking.filter(e => (e.Name || '').includes('機車'));
        const cars = allParking.filter(e => !(e.Name || '').includes('機車') && !(e.Name || '').includes('大客車'));
        console.log(`機車: ${motorcycles.length}, 汽車: ${cars.length}`);

        // 取所有機車座標
        console.log('\n取得全部機車座標...');
        const allMotoLocs = [];
        for (let i = 0; i < motorcycles.length; i++) {
            const loc = await sendCommand(ws, 'get_element_location', { elementId: motorcycles[i].ElementId });
            const d = loc.Data || loc;
            const center = d?.BoundingBox?.Center || d?.Location;
            if (center) {
                allMotoLocs.push({ id: motorcycles[i].ElementId, x: center.X, y: center.Y, name: motorcycles[i].Name });
            }
            if ((i+1) % 50 === 0) console.log(`  已處理 ${i+1}/${motorcycles.length}`);
        }
        existing.all_motorcycle_locations = allMotoLocs;
        console.log(`機車座標: ${allMotoLocs.length} 個`);

        // 取汽車座標 (前 50 個)
        console.log('\n取得汽車座標 (前50)...');
        const carLocs = [];
        for (let i = 0; i < Math.min(cars.length, 50); i++) {
            const loc = await sendCommand(ws, 'get_element_location', { elementId: cars[i].ElementId });
            const d = loc.Data || loc;
            const center = d?.BoundingBox?.Center || d?.Location;
            if (center) {
                carLocs.push({ id: cars[i].ElementId, x: center.X, y: center.Y, name: cars[i].Name });
            }
        }
        existing.car_samples = carLocs;
        console.log(`汽車座標: ${carLocs.length} 個`);

        // 儲存完整結果
        writeFileSync('e:/RevitMCP/MCP-Server/scratch/parking_analysis.json',
            JSON.stringify(existing, null, 2), 'utf-8');
        console.log('\n✅ 完整資料已儲存');

        ws.close();
    });
}

main();
