const fs = require('fs');
const { spawn } = require('child_process');

// Read the mismatch JSON file
const dataFile = 'E:/RevitMCP/scratch_csv/mismatch.json';
const data = JSON.parse(fs.readFileSync(dataFile, 'utf8'));
const updates = data.changed; // exactly 193 sheets

console.log(`Starting batch update of ${updates.length} sheets via MCP stdio...`);

// Spawn the MCP server Node.js process
const mcp = spawn('node', ['E:/RevitMCP/MCP-Server/build/index.js'], {
    stdio: ['pipe', 'pipe', 'inherit']
});

// JSON-RPC message ID tracking
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
                parameterName: "Sheet Number", // Revit default internal name usually works, or "圖紙號碼"
                value: item.TargetNumber
            }
        }
    };

    process.stdout.write(`Updating [${item.Id}] ${item.RevitName} -> ${item.TargetNumber}... `);
    mcp.stdin.write(JSON.stringify(req) + '\n');
}

// Handle responses from MCP Server
let buffer = '';
mcp.stdout.on('data', (chunk) => {
    buffer += chunk.toString();
    
    // Process full lines (JSON-RPC messages)
    let newlineIdx;
    while ((newlineIdx = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, newlineIdx).trim();
        buffer = buffer.slice(newlineIdx + 1);
        
        if (!line) continue;
        
        try {
            const res = JSON.parse(line);
            if (res.error) {
                // If "Sheet Number" failed, let's just log it. 
                // Could retry with "圖紙號碼" if needed, but error messages dictate the flow.
                process.stdout.write(`FAILED: ${res.error.message}\n`);
                failCount++;
                currentIdx++;
                sendNext();
            } else if (res.result) {
                if (res.result.isError) {
                    process.stdout.write(`FAILED: ${JSON.stringify(res.result.content)}\n`);
                    failCount++;
                } else {
                    process.stdout.write('OK\n');
                    successCount++;
                }
                currentIdx++;
                sendNext();
            }
        } catch (e) {
            // Ignore non-JSON lines like server startup logs
            // console.log("=> " + line);
        }
    }
});

mcp.stderr?.on('data', (data) => {
    // console.error(`MCP Error: ${data.toString()}`);
});

// Give it 2 seconds to start up before sending the first request
setTimeout(() => {
    sendNext();
}, 2000);
