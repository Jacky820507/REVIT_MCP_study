import WebSocket from 'ws';

const PORT = 8964;
const TIMEOUT_MS = Number(process.env.REVIT_MCP_COMMAND_TIMEOUT_MS || 30000);
const cmdName = process.argv[2];
let cmdParams = {};
if (!cmdName) {
    console.error('Usage: node scripts/run_command.js <commandName> [jsonParams]');
    process.exit(1);
}
try {
    const rawParams = process.env.REVIT_MCP_PARAMS_JSON || process.argv[3];
    if (rawParams) {
        cmdParams = JSON.parse(rawParams);
    }
} catch (e) {
    console.error('JSON Parse Error:', e.message);
    process.exit(1);
}

async function sendCommand(ws, name, params) {
    return new Promise((resolve, reject) => {
        const reqId = 'req_' + Date.now();
        const cmd = { method: name, params, id: reqId };
        const timeout = setTimeout(() => {
            ws.off('message', listener);
            reject(new Error(`Command timed out after ${TIMEOUT_MS}ms: ${name}`));
        }, TIMEOUT_MS);
        const listener = (data) => {
            const msg = JSON.parse(data.toString());
            if (msg.RequestId === reqId) {
                clearTimeout(timeout);
                ws.off('message', listener);
                resolve(msg);
            }
        };
        ws.on('message', listener);
        ws.send(JSON.stringify(cmd));
    });
}

const ws = new WebSocket(`ws://localhost:${PORT}`);

const connectTimeout = setTimeout(() => {
    console.error(`WebSocket connection timed out after ${TIMEOUT_MS}ms`);
    ws.close();
    process.exit(1);
}, TIMEOUT_MS);

ws.on('open', async () => {
    clearTimeout(connectTimeout);
    try {
        const res = await sendCommand(ws, cmdName, cmdParams);
        console.log(JSON.stringify(res, null, 2));
    } catch (err) {
        console.error(err.message || err);
        process.exitCode = 1;
    } finally {
        ws.close();
        process.exit(process.exitCode || 0);
    }
});

ws.on('error', (err) => {
    clearTimeout(connectTimeout);
    console.error(err.message || err);
    process.exit(1);
});
