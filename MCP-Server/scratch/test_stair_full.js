import WebSocket from 'ws';

const STYLE_ID = 63367; // 隱藏線
const MAX_LINES = 100;  // Cap at 100 lines for this test
const ws = new WebSocket('ws://localhost:8964');

ws.on('open', () => {
    console.log('Connected. Step 1: trace_stair_geometry');
    ws.send(JSON.stringify({ CommandName: 'trace_stair_geometry', Parameters: {}, RequestId: 'step1' }));
});

ws.on('message', (data) => {
    const r = JSON.parse(data.toString());
    
    if (r.RequestId === 'step1') {
        if (!r.Success) { console.log('Trace Error:', r.Error); ws.close(); process.exit(1); }
        
        const stairs = r.Data;
        console.log(`Found ${stairs.length} stairs`);
        
        // Only take first stair's hidden lines
        const firstStair = stairs[0];
        const lines = firstStair.HiddenLines || [];
        console.log(`First stair ${firstStair.StairId}: ${lines.length} hidden lines`);
        
        const testLines = lines.slice(0, MAX_LINES);
        console.log(`Creating ${testLines.length} detail lines (style=${STYLE_ID})...`);
        
        ws.send(JSON.stringify({
            CommandName: 'create_detail_lines',
            Parameters: { lines: testLines, styleId: STYLE_ID },
            RequestId: 'step2'
        }));
    }
    
    if (r.RequestId === 'step2') {
        if (!r.Success) { console.log('❌ Create Error:', r.Error); }
        else { 
            console.log(`\n✅ SUCCESS!`);
            console.log(`Created: ${r.Data.Count} detail lines`);
            console.log(`Skipped: ${r.Data.Skipped}`);
            console.log(`First 5 IDs: ${r.Data.ElementIds.slice(0, 5).join(', ')}`);
        }
        ws.close();
        process.exit(0);
    }
});

ws.on('error', (e) => { console.error('WS Error:', e.message); process.exit(1); });
setTimeout(() => { console.log('Timeout after 120s'); process.exit(1); }, 120000);
