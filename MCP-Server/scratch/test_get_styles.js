import WebSocket from 'ws';

const ws = new WebSocket('ws://localhost:8964');

ws.on('open', () => {
    console.log('Connected');
    ws.send(JSON.stringify({ CommandName: 'get_line_styles', Parameters: {}, RequestId: 'test_styles_1' }));
});

ws.on('message', (data) => {
    const r = JSON.parse(data.toString());
    if (r.RequestId === 'test_styles_1') {
        if (r.Success) {
            console.log('=== Line Styles ===');
            r.Data.forEach(s => console.log(`  [${s.Id}] ${s.Name}`));
            console.log(`Total: ${r.Data.length}`);
        } else {
            console.log('Error:', r.Error);
        }
        ws.close();
        process.exit(0);
    }
});

ws.on('error', (e) => { console.error('WS Error:', e.message); process.exit(1); });
setTimeout(() => { console.log('Timeout'); process.exit(1); }, 15000);
