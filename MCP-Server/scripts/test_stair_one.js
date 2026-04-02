import WebSocket from 'ws';

const STYLE_ID = 11911982; 
const ws = new WebSocket('ws://localhost:8964');

ws.on('open', () => {
    console.log('Connected. Testing ONE stair only.');
    ws.send(JSON.stringify({ CommandName: 'trace_stair_geometry', Parameters: {}, RequestId: 'step1' }));
});

ws.on('message', (data) => {
    const r = JSON.parse(data.toString());
    
    if (r.RequestId === 'step1') {
        const stairs = r.Data;
        console.log(`Found ${stairs.length} stairs. Using only the first one.`);
        
        let allLines = stairs[0].HiddenLines || [];
        console.log(`Stair ${stairs[0].StairId}: ${allLines.length} lines.`);

        ws.send(JSON.stringify({
            CommandName: 'create_detail_lines',
            Parameters: { lines: allLines, styleId: STYLE_ID },
            RequestId: 'step2'
        }));
    }
    
    if (r.RequestId === 'step2') {
        console.log('Result:', JSON.stringify(r, null, 2));
        ws.close();
        process.exit(0);
    }
});

ws.on('error', (e) => { console.error('WS Error:', e); });
setTimeout(() => { console.log('Timeout'); process.exit(1); }, 30000);
