import WebSocket from 'ws';

const STYLE_ID = 11911982; // 虛線(極密) - The correct style for section views
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
        console.log(`Found ${stairs.length} stairs in view`);
        
        let allLines = [];
        stairs.forEach(stair => {
            console.log(`- Stair ${stair.StairId}: ${stair.TotalEdges} total edges -> ${stair.FirstRunEdgesCount} first-run hidden edges`);
            if (stair.HiddenLines) {
                allLines.push(...stair.HiddenLines);
            }
        });
        
        if (allLines.length === 0) {
            console.log('No hidden lines found. Exiting.');
            ws.close(); process.exit(0);
        }

        console.log(`\nStep 2: Creating ${allLines.length} detail lines with style 虛線(極密) (${STYLE_ID})...`);
        ws.send(JSON.stringify({
            CommandName: 'create_detail_lines',
            Parameters: { lines: allLines, styleId: STYLE_ID },
            RequestId: 'step2'
        }));
    }
    
    if (r.RequestId === 'step2') {
        if (!r.Success) { console.log('❌ Create Error:', r.Error); }
        else { 
            console.log(`\n✅ SUCCESS!`);
            console.log(`Created: ${r.Data.Count} detail lines`);
            console.log(`Skipped (zero length): ${r.Data.Skipped}`);
        }
        ws.close();
        process.exit(0);
    }
});

ws.on('error', (e) => { console.error('WS Error:', e.message); process.exit(1); });
setTimeout(() => { console.log('Timeout after 120s'); process.exit(1); }, 120000);
