const { spawn } = require('child_process');
const path = require('path');

const MCP_INDEX = path.resolve(__dirname, '../build/index.js');
const reqId = `req_create_${Date.now()}`;

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
            name: 'create_dependent_view_matchlines',
            arguments: {
                primaryViewId: 695,
                lineStyleName: '粗虛線',
                textStyleName: '微軟正黑體 3.5 mm'
            }
        }
    };
    mcpProcess.stdin.write(JSON.stringify(request) + '\n');
}, 1000);
