const { spawn } = require('child_process');

// Shift 20 sheets from 020-039 down by 2 (to 018-037)
const updates = [
    {id: 10870044, current: 'ARS-D09020', target: 'ARS-D09018'},
    {id: 10870049, current: 'ARS-D09021', target: 'ARS-D09019'},
    {id: 10870054, current: 'ARS-D09022', target: 'ARS-D09020'},
    {id: 12002058, current: 'ARS-D09023', target: 'ARS-D09021'},
    {id: 10870059, current: 'ARS-D09024', target: 'ARS-D09022'},
    {id: 10870064, current: 'ARS-D09025', target: 'ARS-D09023'},
    {id: 8094351,   current: 'ARS-D09026', target: 'ARS-D09024'},
    {id: 10870069, current: 'ARS-D09027', target: 'ARS-D09025'},
    {id: 10870074, current: 'ARS-D09028', target: 'ARS-D09026'},
    {id: 10870079, current: 'ARS-D09029', target: 'ARS-D09027'},
    {id: 10870084, current: 'ARS-D09030', target: 'ARS-D09028'},
    {id: 10870089, current: 'ARS-D09031', target: 'ARS-D09029'},
    {id: 10870094, current: 'ARS-D09032', target: 'ARS-D09030'},
    {id: 12002114, current: 'ARS-D09033', target: 'ARS-D09031'},
    {id: 12002120, current: 'ARS-D09034', target: 'ARS-D09032'},
    {id: 12002126, current: 'ARS-D09035', target: 'ARS-D09033'},
    {id: 12002132, current: 'ARS-D09036', target: 'ARS-D09034'},
    {id: 12002138, current: 'ARS-D09037', target: 'ARS-D09035'},
    {id: 10870372, current: 'ARS-D09038', target: 'ARS-D09036'},
    {id: 10870378, current: 'ARS-D09039', target: 'ARS-D09037'}
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
            console.log("\n✅ ARS-D09 gap fix finished!");
            mcp.kill();
            process.exit(0);
        }
        return;
    }

    const item = updates[currentIdx];
    if (phase === 1) {
        const tempValue = item.target + "_GAP_FIX";
        process.stdout.write(`PHASE 1 [${currentIdx + 1}/${updates.length}]: ${item.current} -> ${tempValue}... `);
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
