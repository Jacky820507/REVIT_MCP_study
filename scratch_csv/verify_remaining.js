const fs = require('fs');
const { spawn } = require('child_process');

const dataFile = 'E:/RevitMCP/scratch_csv/mismatch.json';
const data = JSON.parse(fs.readFileSync(dataFile, 'utf8'));
const targets = data.changed;

const mcp = spawn('node', ['E:/RevitMCP/MCP-Server/build/index.js'], {
    stdio: ['pipe', 'pipe', 'inherit']
});

let msgId = 1;
const results = [];

function fetchAll() {
    const req = {
        jsonrpc: "2.0",
        id: msgId++,
        method: "tools/call",
        params: {
            name: "get_all_sheets",
            arguments: {}
        }
    };
    mcp.stdin.write(JSON.stringify(req) + '\n');
}

let buffer = '';
mcp.stdout.on('data', (chunk) => {
    buffer += chunk.toString();
    try {
        const lines = buffer.split('\n');
        for (let i = 0; i < lines.length - 1; i++) {
            const line = lines[i].trim();
            if (!line) continue;
            const res = JSON.parse(line);
            if (res.id && res.result && res.result.content) {
                const sheetText = res.result.content[0].text;
                const sheets = JSON.parse(sheetText).Sheets;
                
                // Compare current Revit sheets with targets
                const neededForce = [];
                for (const t of targets) {
                    const rs = sheets.find(s => s.ElementId === t.Id);
                    if (rs && rs.SheetNumber !== t.TargetNumber) {
                        neededForce.push({
                            Id: t.Id,
                            RevitName: t.RevitName,
                            CurrentNumber: rs.SheetNumber,
                            TargetNumber: t.TargetNumber
                        });
                    }
                }
                
                console.log(JSON.stringify(neededForce, null, 2));
                mcp.kill();
                process.exit(0);
            }
        }
        buffer = lines[lines.length - 1];
    } catch (e) {}
});

setTimeout(fetchAll, 2000);
