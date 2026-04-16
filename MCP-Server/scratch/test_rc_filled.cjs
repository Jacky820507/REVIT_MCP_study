const WebSocket = require('ws');
const ws = new WebSocket('ws://localhost:8964');

console.log("Connecting to Revit MCP Server...");

ws.on('open', () => {
    console.log('✅ Connected successfully!');
    const request = {
        jsonrpc: '2.0',
        method: 'create_rc_filled_region',
        params: { filledRegionTypeName: '深灰色' },
        id: Date.now()
    };
    console.log("Sending request:", JSON.stringify(request));
    ws.send(JSON.stringify(request));
});

ws.on('message', (data) => {
    const response = JSON.parse(data.toString());
    console.log('\n📥 Response from Revit:');
    console.log(JSON.stringify(response, null, 2));
    process.exit(response.Success === false ? 1 : 0);
});

ws.on('error', (err) => {
    console.error('❌ WebSocket Error:', err.message);
    process.exit(1);
});

setTimeout(() => {
    console.log('⏳ Timeout (15s) - Revit did not respond');
    process.exit(1);
}, 15000);
