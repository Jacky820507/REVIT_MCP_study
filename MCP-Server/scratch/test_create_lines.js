import WebSocket from 'ws';

// 直接用之前 trace 結果中的前 5 條線測試 create_detail_lines
const STYLE_ID = 63367; // 隱藏線
const testLines = [
    { startX: 230731.3, startY: 14222.3, startZ: 0, endX: 230731.3, endY: 14122.3, endZ: 0 },
    { startX: 230731.3, startY: 14122.3, startZ: 0, endX: 230981.3, endY: 14122.3, endZ: 0 },
    { startX: 230981.3, startY: 14122.3, startZ: 0, endX: 231081.3, endY: 14222.3, endZ: 0 },
    { startX: 231081.3, startY: 14222.3, startZ: 0, endX: 231081.3, endY: 14322.3, endZ: 0 },
    { startX: 231081.3, startY: 14322.3, startZ: 0, endX: 230731.3, endY: 14322.3, endZ: 0 },
];

const ws = new WebSocket('ws://localhost:8964');

ws.on('open', () => {
    console.log(`Connected. Creating ${testLines.length} detail lines with style ${STYLE_ID}...`);
    ws.send(JSON.stringify({
        CommandName: 'create_detail_lines',
        Parameters: { lines: testLines, styleId: STYLE_ID },
        RequestId: 'create_test'
    }));
});

ws.on('message', (data) => {
    const r = JSON.parse(data.toString());
    if (r.RequestId === 'create_test') {
        if (!r.Success) {
            console.log('❌ Error:', r.Error);
        } else {
            console.log(`✅ Created ${r.Data.Count} detail lines!`);
            console.log(`Element IDs: ${JSON.stringify(r.Data.ElementIds)}`);
        }
        ws.close();
        process.exit(0);
    }
});

ws.on('error', (e) => { console.error('WS Error:', e.message); process.exit(1); });
setTimeout(() => { console.log('Timeout'); process.exit(1); }, 30000);
