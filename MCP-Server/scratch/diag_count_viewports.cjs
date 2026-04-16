const WebSocket = require('ws');
const ws = new WebSocket('ws://localhost:8964');

ws.on('open', async () => {
    const id = Date.now();
    ws.send(JSON.stringify({
        jsonrpc: '2.0',
        method: 'query_elements',
        params: { category: 'OST_Viewports', returnFields: ['Id'] },
        id
    }));

    ws.on('message', (data) => {
        const response = JSON.parse(data);
        if (response.id === id) {
            console.log(`📊 Total Viewports: ${response.data.length}`);
            ws.close();
        }
    });
});
