import WebSocket from 'ws';

const PORT = 8964;
const ws = new WebSocket(`ws://localhost:${PORT}`);

ws.on('open', async () => {
    console.log('Connected.');
    const reqId = 'test_' + Date.now();
    const cmd = {
        method: 'get_active_view',
        params: {},
        id: reqId
    };
    
    ws.on('message', (data) => {
        const msg = JSON.parse(data.toString());
        if (msg.RequestId === reqId) {
            console.log('Response:', JSON.stringify(msg, null, 2));
            ws.close();
            process.exit(0);
        }
    });
    
    console.log('Sending get_active_view...');
    ws.send(JSON.stringify(cmd));
});

ws.on('error', (err) => {
    console.error('Error:', err);
    process.exit(1);
});

setTimeout(() => {
    console.error('Timeout');
    process.exit(1);
}, 10000);
