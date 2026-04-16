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
        setTimeout(() => { ws.off('message', listener); resolve({ Success: false }); }, 30000);
    });
}

function extractLocation(element) {
    if (element.LocationX != null && element.LocationY != null) return { x: parseFloat(element.LocationX), y: parseFloat(element.LocationY) };
    if (element.Location) {
        const loc = element.Location;
        if (loc.X != null && loc.Y != null) return { x: parseFloat(loc.X), y: parseFloat(loc.Y) };
        if (typeof loc === 'string') {
            const m = loc.match(/[\(（]?\s*([-\d.]+)\s*[,，]\s*([-\d.]+)/);
            if (m) return { x: parseFloat(m[1]), y: parseFloat(m[2]) };
        }
    }
    if (element.BoundingBox) {
        const bb = element.BoundingBox;
        if (bb.Min && bb.Max) {
            return { x: (parseFloat(bb.Min.X||bb.Min.x||0) + parseFloat(bb.Max.X||bb.Max.x||0))/2, y: (parseFloat(bb.Min.Y||bb.Min.y||0) + parseFloat(bb.Max.Y||bb.Max.y||0))/2 };
        }
    }
    return null;
}

function sortParkingBays(bays, tolerance) {
    if (bays.length === 0) return bays;
    bays.sort((a, b) => a.x - b.x);
    let currentGroupX = bays[0].x;
    let groupIndex = 0;
    for (const bay of bays) {
        if (Math.abs(bay.x - currentGroupX) > tolerance) {
            groupIndex++;
            currentGroupX = bay.x;
        }
        bay._group = groupIndex;
    }
    bays.sort((a, b) => {
        if (a._group !== b._group) return a._group - b._group;
        const isEvenGroup = a._group % 2 === 1;
        return isEvenGroup ? (a.y - b.y) : (b.y - a.y);
    });
    for (const bay of bays) delete bay._group;
    return bays;
}

async function main() {
    console.log("連線至 Revit MCP Server...");
    const ws = new WebSocket(`ws://localhost:${PORT}`);
    
    ws.on('open', async () => {
        const res = await sendCommand(ws, 'query_elements', { category: 'Parking', maxCount: 1000 });
        const allParking = res.Data?.Elements || [];
        const motorcycles = allParking.filter(e => (e.Name || '').includes('機車'));
        
        const data = [];
        for (let i = 0; i < motorcycles.length; i++) {
            const m = motorcycles[i];
            const infoRes = await sendCommand(ws, 'get_element_info', { elementId: m.ElementId });
            const params = infoRes.Data?.Parameters || [];
            const remarkParam = params.find(p => p.Name === '備註' || p.Name === 'Comments');
            const manualRemark = (remarkParam && remarkParam.Value) ? parseInt(remarkParam.Value, 10) : null;
            
            let loc = extractLocation(m);
            if (!loc) {
                const locRes = await sendCommand(ws, 'get_element_location', { elementId: m.ElementId });
                const d = locRes.Data || locRes;
                const center = d?.BoundingBox?.Center || d?.Location;
                if (center) {
                    loc = { x: center.X, y: center.Y };
                }
            }
            if (loc) {
                data.push({ id: m.ElementId, manual: manualRemark, x: loc.x, y: loc.y });
            }
        }

        // 以我的 xy 演算法排序
        sortParkingBays(data, 1500);

        console.log("\n=== 差異分析 (預期演算法 vs 手動輸入) ===");
        let diffCount = 0;
        let nullCount = 0;
        for (let i = 0; i < data.length; i++) {
            const expected = 578 + i;
            const manual = data[i].manual;
            if (manual === null || isNaN(manual)) {
                nullCount++;
            } else if (expected !== manual) {
                console.log(`[差異] Index: ${i}, X:${Math.round(data[i].x)} Y:${Math.round(data[i].y)} | 演算法應為: ${expected}, 手動值為: ${manual}`);
                diffCount++;
            }
        }
        console.log(`\n比對完成。共 ${data.length} 個停車格。`);
        console.log(`手動未填寫數量: ${nullCount}`);
        console.log(`邏輯不一致數量: ${diffCount}`);

        if (diffCount === 0 && nullCount === 0) {
            console.log("\n🎉 結果：當前的編號與我的 `xy` 蛇形演算法完全一致！");
        } else if (diffCount > 0) {
            console.log("\n⚠️ 結果：使用者的手動編號與我的 `xy` 演算法有不同之處。");
        }

        ws.close();
    });
}
main();
