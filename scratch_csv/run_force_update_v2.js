const fs = require('fs');
const { spawn } = require('child_process');

const forceData = JSON.parse(fs.readFileSync('E:/RevitMCP/scratch_csv/force_list_v2.json', 'utf8'));

const mcp = spawn('node', ['E:/RevitMCP/MCP-Server/build/index.js'], {
    stdio: ['pipe', 'pipe', 'inherit']
});

let msgId = 1;
let currentIdx = 0;
let stage = 1; // 1: TEMP, 2: FINAL

function sendCommand(id, param, value) {
    const req = {
        jsonrpc: "2.0", id: msgId++, method: "tools/call",
        params: { name: "modify_element_parameter", arguments: { elementId: id, parameterName: "Sheet Number", value: value } }
    };
    mcp.stdin.write(JSON.stringify(req) + '\n');
}

function processNext() {
    if (currentIdx >= forceData.length) {
        console.log("\n✅ Force update V2 finished!");
        mcp.kill();
        process.exit(0);
        return;
    }
    const item = forceData[currentIdx];
    if (stage === 1) {
        process.stdout.write(`Stage 1: [${item.Id}] -> ${item.TargetNumber}_TEMP... `);
        sendCommand(item.Id, "Sheet Number", item.TargetNumber + "_TEMP");
    } else {
        process.stdout.write(`Stage 2: [${item.Id}] -> ${item.TargetNumber}... `);
        sendCommand(item.Id, "Sheet Number", item.TargetNumber);
    }
}

let buffer = '';
mcp.stdout.on('data', (chunk) => {
    buffer += chunk.toString();
    let lines = buffer.split('\n');
    for (let i = 0; i < lines.length - 1; i++) {
        const line = lines[i].trim();
        if (!line) continue;
        try {
            const res = JSON.parse(line);
            if (res.id) {
                if (res.error || (res.result && res.result.isError)) {
                    process.stdout.write("FAILED\n");
                } else {
                    process.stdout.write("OK\n");
                }
                if (stage === 1) stage = 2; else { stage = 1; currentIdx++; }
                processNext();
            }
        } catch (e) {}
    }
    buffer = lines[lines.length - 1];
});

setTimeout(processNext, 2000);
