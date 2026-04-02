import WebSocket from 'ws';

const PORT = 8964;

function sendCommand(ws, name, params) {
    return new Promise((resolve) => {
        const reqId = 'req_' + Date.now();
        const cmd = { CommandName: name, Parameters: params, RequestId: reqId };
        const listener = (data) => {
            const msg = JSON.parse(data.toString());
            if (msg.RequestId === reqId) {
                ws.off('message', listener);
                resolve(msg);
            }
        };
        ws.on('message', listener);
        ws.send(JSON.stringify(cmd));
    });
}

const ws = new WebSocket(`ws://localhost:${PORT}`);
ws.on('open', async () => {
    console.log('Connected.');
    
    console.log('\n--- Active View ---');
    const view = await sendCommand(ws, 'get_active_view', {});
    console.log(JSON.stringify(view, null, 2));

    const vId = view.Data?.Id || view.Data?.id || view.Data?.ElementId;
    
    console.log('\n--- Active Schema ---');
    const schema = await sendCommand(ws, 'get_active_schema', { viewId: vId });
    console.log(JSON.stringify(schema, null, 2));

    ws.close();
});
