const { spawn } = require('child_process');
const path = require('path');

const MCP_INDEX = path.resolve(__dirname, '../build/index.js');
const reqId = `req_debug_${Date.now()}`;

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
            name: 'get_element_info', // 假設有個工具可以列出視圖內元素，或者我們用 generic query
            arguments: {
                category: 'OST_Lines',
                viewId: 695
            }
        }
    };
    // 檢查是否有 get_element_info 
    // 若沒有，我們用 query_elements
    const queryRequest = {
        jsonrpc: '2.0',
        id: reqId,
        method: 'tools/call',
        params: {
            name: 'query_elements',
            arguments: {
                category: 'OST_Lines',
                viewId: 695
            }
        }
    };
    mcpProcess.stdin.write(JSON.stringify(queryRequest) + '\n');
}, 1000);
