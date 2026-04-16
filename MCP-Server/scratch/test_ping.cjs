const WebSocket = require('ws');
const ws = new WebSocket('ws://localhost:8964');

console.log("Connecting to Revit MCP (Ping Test)...");

ws.on('open', () => {
    console.log('✅ Connected.');
    ws.send(JSON.stringify({
        jsonrpc: '2.0',
        method: 'ping',
        params: {},
        id: Date.now()
    }));
});

ws.on('message', (data) => {
    const response = JSON.parse(data.toString());
    console.log('\n📥 Response (Pong):');
    console.log(JSON.stringify(response, null, 2));
    process.exit(0);
});

ws.on('error', (err) => {
    console.error('❌ Error:', err.message);
    process.exit(1);
});

setTimeout(() => {
    console.log('⏳ Timeout.');
    process.exit(1);
}, 10000);
