const net = require('net');

const client = new net.Socket();
const PORT = 8964;
const HOST = '127.0.0.1';

client.connect(PORT, HOST, () => {
    console.log('Connected to MCP Socket Server');
    const command = {
        type: 'tool_call',
        name: 'create_wall',
        arguments: {
            startX: 0,
            startY: 0,
            endX: 1000,
            endY: 0,
            height: 3000
        }
    };
    client.write(JSON.stringify(command) + '\n');
});

client.on('data', (data) => {
    console.log('Response from server:', data.toString());
    client.destroy();
});

client.on('close', () => {
    console.log('Connection closed');
});

client.on('error', (err) => {
    console.error('Socket error:', err.message);
});
