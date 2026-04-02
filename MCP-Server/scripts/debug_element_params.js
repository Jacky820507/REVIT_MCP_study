import WebSocket from 'ws';

const PORT = 8964;
const ELEMENT_ID = 6299089;

async function sendCommand(ws, name, params) {
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
    try {
        const res = await sendCommand(ws, 'get_element_info', { elementId: ELEMENT_ID });
        console.log(JSON.stringify(res, null, 2));
    } catch (err) {
        console.error(err);
    } finally {
        ws.close();
        process.exit(0);
    }
});
