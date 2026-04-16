/**
 * 探索「機車停車格模型線」群組內的成員與幾何
 */
import WebSocket from 'ws';

const PORT = parseInt(process.env.REVIT_MCP_PORT || '8964', 10);
const GROUP_ID = 7850527;

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
        console.log('已連線');

        // 查詢所有 Lines
        const lines = await sendCommand(ws, 'query_elements', { category: 'Lines', maxCount: 500 });
        const els = lines.Data?.Elements || lines.Elements || [];
        console.log(`共 ${els.length} 條線`);

        // 篩選模型線
        const modelLines = els.filter(l => (l.Name || '').includes('模型線'));
        console.log(`模型線: ${modelLines.length} 條`);

        // 逐條取座標
        if (modelLines.length > 0) {
            console.log('\n=== 模型線座標 ===');
            for (const line of modelLines) {
                const locData = await sendCommand(ws, 'get_element_location', { elementId: line.ElementId });
                const d = locData.Data || locData;
                const locStr = d?.Location ? JSON.stringify(d.Location) : 'N/A';
                const bboxStr = d?.BoundingBox?.Center ? JSON.stringify(d.BoundingBox.Center) : 'N/A';
                console.log(`ID:${line.ElementId}  Loc:${locStr}  Center:${bboxStr}`);
            }
        } else {
            // 沒有名為"模型線"的，列出所有線的名稱統計
            const nameCounts = {};
            els.forEach(l => { nameCounts[l.Name || '?'] = (nameCounts[l.Name || '?'] || 0) + 1; });
            console.log('線名稱統計:', nameCounts);
        }

        ws.close();
    });
}

main();
