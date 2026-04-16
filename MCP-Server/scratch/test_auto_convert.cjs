const WebSocket = require('ws');

function testAutoConvert() {
    console.log('Connecting to Revit Socket at ws://localhost:8964...');
    const ws = new WebSocket('ws://localhost:8964');

    ws.on('open', () => {
        console.log('Connected to Revit Socket.');
        
        const cmd = {
            CommandName: 'auto_convert_rotated_viewport_patterns',
            Parameters: {},
            RequestId: 'test_req_' + Date.now()
        };
        
        console.log('Sending command: auto_convert_rotated_viewport_patterns');
        ws.send(JSON.stringify(cmd));
    });

    ws.on('message', (data) => {
        const responseText = data.toString();
        try {
            const resp = JSON.parse(responseText);
            console.log('Response Detail:', JSON.stringify(resp, null, 2));
            if (resp.Success) {
                console.log('SUCCESS:', resp.Data?.Message);
            } else {
                console.log('FAILED:', resp.Error);
            }
        } catch (e) {
            console.log('Raw Response:', responseText);
        }
        ws.close();
    });

    ws.on('error', (err) => {
        console.error('WebSocket Error:', err.message);
    });

    ws.on('close', () => {
        console.log('WebSocket connection closed.');
    });
}

testAutoConvert();
