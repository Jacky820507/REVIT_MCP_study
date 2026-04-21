import WebSocket from 'ws';

const PORT = 8964;
const ws = new WebSocket(`ws://localhost:${PORT}`);

ws.on('open', async () => {
    console.log('Connected.');
    
    // Get active view first
    const viewRes = await sendCommand(ws, 'get_active_view', {});
    const viewId = viewRes.Data.ElementId;
    
    console.log('Testing get_element_info for ID 6147619...');
    const infoRes = await sendCommand(ws, 'get_element_info', {
        elementId: 6147619
    });
    
    console.log('Info Response:', JSON.stringify(infoRes, null, 2));
    ws.close();
});

function sendCommand(ws, name, params) {
    return new Promise((resolve) => {
        const id = 'test_' + Date.now();
        ws.once('message', (data) => resolve(JSON.parse(data.toString())));
        ws.send(JSON.stringify({ method: name, params, id }));
    });
}
