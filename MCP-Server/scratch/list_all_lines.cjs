const { spawn } = require('child_process');
const path = require('path');

const MCP_INDEX = path.resolve(__dirname, '../build/index.js');
const reqId = `req_list_${Date.now()}`;

const mcpProcess = spawn('node', [MCP_INDEX], {
    stdio: ['pipe', 'pipe', 'inherit'],
    cwd: path.resolve(__dirname, '..')
});

mcpProcess.stdout.on('data', (chunk) => {
    const lines = chunk.toString().split('\n').filter(l => l.trim());
    for (const line of lines) {
        try {
            const parsed = JSON.parse(line);
            if (parsed.id === reqId) {
                const raw = parsed.result?.content?.[0]?.text;
                if (raw) {
                    const data = JSON.parse(raw);
                    console.log(JSON.stringify(data, null, 2));
                }
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
            name: 'query_elements',
            arguments: {
                category: 'OST_Lines',
                all: true,
                returnFields: ['Name', 'LineStyle']
            }
        }
    };
    mcpProcess.stdin.write(JSON.stringify(request) + '\n');
}, 1000);
