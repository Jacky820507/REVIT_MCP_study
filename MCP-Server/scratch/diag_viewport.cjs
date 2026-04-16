const WebSocket = require('ws');

function diagnostic() {
    const ws = new WebSocket('ws://localhost:8964');
    ws.on('open', () => {
        // Viewport on ARB-D04011 is 8718975
        const cmd = {
            CommandName: 'get_element_info',
            Parameters: { elementId: 8718975 },
            RequestId: 'diag_' + Date.now()
        };
        ws.send(JSON.stringify(cmd));
    });

    ws.on('message', (data) => {
        console.log(data.toString());
        ws.close();
    });
}
diagnostic();
