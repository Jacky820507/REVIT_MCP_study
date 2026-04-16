import WebSocket from 'ws';

async function main() {
    const ws = new WebSocket('ws://localhost:8964');

    ws.on('open', () => {
        console.log('Connected to Revit Socket');
        
        const listCmd = {
            CommandName: 'list_family_symbols',
            Parameters: {
                filter: 'TEST-圖號詳圖編號'
            }
        };
        console.log('Sending command:', JSON.stringify(listCmd, null, 2));
        ws.send(JSON.stringify(listCmd));
    });

    ws.on('message', (data) => {
        const response = JSON.parse(data.toString());
        console.log('Response:', JSON.stringify(response, null, 2));
        process.exit(0);
    });

    ws.on('error', (err) => {
        console.error('Socket Error:', err);
        process.exit(1);
    });

    setTimeout(() => {
        console.log('Timeout waiting for response');
        process.exit(1);
    }, 10000);
}

main();
