const fs = require('fs');
const { spawn } = require('child_process');

const dataFile = 'E:/RevitMCP/scratch_csv/mismatch_v3.json';
const data = JSON.parse(fs.readFileSync(dataFile, 'utf8'));
const updates = data.changed;

console.log(`Starting batch update of ${updates.length} sheets via MCP stdio...`);

const mcp = spawn('node', ['E:/RevitMCP/MCP-Server/build/index.js'], {
    stdio: ['pipe', 'pipe', 'inherit']
});

let msgId = 1;
let currentIdx = 0;
let successCount = 0;
let failCount = 0;

function sendNext() {
    if (currentIdx >= updates.length) {
        console.log(`\n✅ Batch update finished! Success: ${successCount}, Failed: ${failCount}`);
        mcp.kill();
        process.exit(0);
        return;
    }

    const item = updates[currentIdx];
    const req = {
        jsonrpc: "2.0",
        id: msgId++,
        method: "tools/call",
        params: {
            name: "modify_element_parameter",
            arguments: {
                elementId: item.Id,
                parameterName: "Sheet Number",
                value: item.TargetNumber
            }
        }
    };

    process.stdout.write(`Updating [${item.Id}] ${item.RevitName} -> ${item.TargetNumber}... `);
    mcp.stdin.write(JSON.stringify(req) + '\n');
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
                    failCount++;
                } else {
                    process.stdout.write('OK\n');
                    successCount++;
                }
                currentIdx++;
                sendNext();
            }
        } catch (e) {}
    }
});

setTimeout(sendNext, 2000);
