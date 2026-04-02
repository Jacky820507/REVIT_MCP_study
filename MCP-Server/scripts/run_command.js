import WebSocket from 'ws';

const PORT = 8964;
const cmdName = process.argv[2];
let cmdParams = {};
try {
    if (process.argv[3]) {
        cmdParams = JSON.parse(process.argv[3]);
    }
} catch (e) {
    console.error('JSON Parse Error:', e.message);
    process.exit(1);
}

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
        const res = await sendCommand(ws, cmdName, cmdParams);
        console.log(JSON.stringify(res, null, 2));
    } catch (err) {
        console.error(err);
    } finally {
        ws.close();
        process.exit(0);
    }
});
