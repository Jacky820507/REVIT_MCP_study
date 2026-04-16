const WebSocket = require('ws');

const ws = new WebSocket('ws://localhost:8964');

ws.on('open', function open() {
    console.log('Connected to WebSocket server');
    const command = {
        CommandName: 'create_wall',
        Parameters: {
            startX: 0,
            startY: 0,
            endX: 1000,
            endY: 0,
            height: 3000
        },
        RequestId: 'req_' + Date.now()
    };
    ws.send(JSON.stringify(command));
});

ws.on('message', function incoming(data) {
    console.log('Response from server:', data.toString());
    ws.close();
});

ws.on('error', function error(err) {
    console.error('WebSocket error:', err.message);
});

ws.on('close', function close() {
    console.log('Connection closed');
});
