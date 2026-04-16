const { spawn } = require('child_process');
const path = require('path');

const MCP_INDEX = path.resolve(__dirname, '../build/index.js');
const reqId = `req_sheet_info_${Date.now()}`;

const mcpProcess = spawn('node', [MCP_INDEX], {
    stdio: ['pipe', 'pipe', 'inherit'],
    cwd: path.resolve(__dirname, '..')
});

const sheetNumbers = [
    "ARB-D02002", "ARB-D02003", "ARB-D02004", "ARB-D02005", "ARB-D02006", 
    "ARB-D02007", "ARB-D02008", "ARB-D02009", "ARB-D02010", "ARB-D02011", 
    "ARB-D02012", "ARB-D02013", "ARB-D02014"
];

mcpProcess.stdout.on('data', (chunk) => {
    const lines = chunk.toString().split('\n').filter(l => l.trim());
    for (const line of lines) {
        try {
            const parsed = JSON.parse(line);
            if (parsed.id === reqId) {
                console.log(JSON.stringify(parsed.result, null, 2));
                mcpProcess.kill();
                process.exit(0);
            }
        } catch (_) {}
    }
});

setTimeout(() => {
    const request = {
        jsonrpc: '2.0',
        id: reqId,
        method: 'tools/call',
        params: {
            name: 'detect_sheet_matchlines',
            arguments: {
                sheetNumbers: sheetNumbers,
                lineStyleName: '粗虛線'
            }
        }
    };
    mcpProcess.stdin.write(JSON.stringify(request) + '\n');
}, 1000);
