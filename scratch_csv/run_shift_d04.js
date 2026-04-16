const fs = require('fs');
const { spawn } = require('child_process');

const dataFile = 'E:/RevitMCP/scratch_csv/shift_d04.json';
const data = JSON.parse(fs.readFileSync(dataFile, 'utf8'));
const updates = data.changed;

console.log(`Starting shift update of ${updates.length} sheets (Total ${updates.length * 2} operations)...`);

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
            console.log("\n✅ Shift update finished!");
            mcp.kill();
            process.exit(0);
        }
        return;
    }

    const item = updates[currentIdx];
    if (phase === 1) {
        const tempValue = item.TargetNumber + "_TEMP";
        process.stdout.write(`PHASE 1 [${currentIdx + 1}/${updates.length}]: ${item.Id} -> ${tempValue}... `);
        sendCommand(item.Id, tempValue);
    } else {
        process.stdout.write(`PHASE 2 [${currentIdx + 1}/${updates.length}]: ${item.Id} -> ${item.TargetNumber}... `);
        sendCommand(item.Id, item.TargetNumber);
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
