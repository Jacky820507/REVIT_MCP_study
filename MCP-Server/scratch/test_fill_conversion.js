import WebSocket from 'ws';

async function main() {
    console.log('Connecting to Revit Socket at ws://localhost:8964...');
    const ws = new WebSocket('ws://localhost:8964');

    ws.on('open', () => {
        console.log('Connected to Revit Socket.');
        
        const cmd = {
            CommandName: 'convert_drafting_to_model_pattern',
            Parameters: {},
            RequestId: 'test_req_' + Date.now()
        };
        
        console.log('Sending command: convert_drafting_to_model_pattern');
        ws.send(JSON.stringify(cmd));
    });

    ws.on('message', (data) => {
        const response = JSON.parse(data.toString());
        console.log('Response Detail:', JSON.stringify(response, null, 2));

        if (response.success) {
            console.log('SUCCESS: ' + response.data.Message);
        } else {
            console.error('FAILED: ' + response.error);
        }
        process.exit(0);
    });

    ws.on('error', (err) => {
        console.error('Socket Error:', err);
        process.exit(1);
    });

    // Timeout safety
    setTimeout(() => {
        console.log('Timeout waiting for Revit response (30s)');
        process.exit(1);
    }, 30000);
}

main();
