const { spawn } = require('child_process');

const updates = [
    {id: 12002114, current: 'ARS-D09032-1', target: 'ARS-D09033'},
    {id: 12002120, current: 'ARS-D09032-2', target: 'ARS-D09034'},
    {id: 12002126, current: 'ARS-D09032-3', target: 'ARS-D09035'},
    {id: 12002132, current: 'ARS-D09032-4', target: 'ARS-D09036'},
    {id: 12002138, current: 'ARS-D09032-5', target: 'ARS-D09037'},
    {id: 10870372, current: 'ARS-D09033',   target: 'ARS-D09038'},
    {id: 10870378, current: 'ARS-D09034',   target: 'ARS-D09039'}
];

const mcp = spawn('node', ['E:/RevitMCP/MCP-Server/build/index.js'], {
    stdio: ['pipe', 'pipe', 'inherit']
});

let msgId = 1;
let currentIdx = 0;
let phase = 1; // 1: TEMP, 2: FINAL

function sendCommand(id, value) {
    const req = {
        jsonrpc: "2.0",
        id: msgId++,
        method: "tools/call",
        params: {
            name: "modify_element_parameter",
            arguments: {
                elementId: id,
                parameterName: "Sheet Number",
                value: value
            }
        }
    };
    mcp.stdin.write(JSON.stringify(req) + '\n');
}

function processNext() {
    if (currentIdx >= updates.length) {
        if (phase === 1) {
            console.log("\n--- Phase 1 (TEMP) Finished. Starting Phase 2 (FINAL) ---");
            phase = 2;
            currentIdx = 0;
            processNext();
        } else {
            console.log("\n✅ Glass Curtain Wall reordering finished!");
            mcp.kill();
            process.exit(0);
        }
        return;
    }

    const item = updates[currentIdx];
    if (phase === 1) {
        const tempValue = item.target + "_TMP_G";
        process.stdout.write(`PHASE 1 [${currentIdx + 1}/${updates.length}]: ${item.id} (${item.current}) -> ${tempValue}... `);
        sendCommand(item.id, tempValue);
    } else {
        process.stdout.write(`PHASE 2 [${currentIdx + 1}/${updates.length}]: ${item.id} -> ${item.target}... `);
        sendCommand(item.id, item.target);
    }
}

let buffer = '';
mcp.stdout.on('data', (chunk) => {
    buffer += chunk.toString();
    let newlineIdx;
    while ((newlineIdx = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, newlineIdx).trim();
        buffer = buffer.slice(newlineIdx + 1);
        if (!line) continue;
        try {
            const res = JSON.parse(line);
            if (res.id) {
                if (res.error || (res.result && res.result.isError)) {
                    process.stdout.write('FAILED\n');
                } else {
                    process.stdout.write('OK\n');
                }
                currentIdx++;
                processNext();
            }
        } catch (e) {}
    }
});

setTimeout(processNext, 2000);
