const cp = require('child_process');

const processObj = cp.spawn('node', ['build/index.js'], {
    stdio: ['pipe', 'pipe', 'inherit']
});

const cmdId = "req_12345";

processObj.stdout.on('data', (data) => {
    const lines = data.toString().split('\n').filter(l => l.trim() !== '');
    for (const line of lines) {
        try {
            const parsed = JSON.parse(line);
            
            if (parsed.id === cmdId) {
                console.log(JSON.stringify(parsed.result, null, 2));
                processObj.kill();
                process.exit(0);
            }
        } catch (e) {
        }
    }
});

const req = {
    jsonrpc: '2.0',
    id: cmdId,
    method: 'tools/call',
    params: {
        name: 'get_element_info',
        arguments: { elementId: 255960 }
    }
};

setTimeout(() => {
    processObj.stdin.write(JSON.stringify(req) + '\n');
}, 1500);

setTimeout(() => {
    console.log("Timeout");
    processObj.kill();
    process.exit(1);
}, 6000);
