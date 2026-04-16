const { spawn } = require('child_process');

const fixList = [
    {id: 10865030, old: 'ARB-D09001', new: 'ARS-D09011'}, // Note: User said ARB-D09001 to ARS-D09001
    {id: 10865030, old: 'ARB-D09001', new: 'ARS-D09001'},
    {id: 10869982, old: 'ARB-D09002', new: 'ARS-D09002'},
    {id: 10903198, old: 'ARB-D09003', new: 'ARS-D09003'},
    {id: 10903204, old: 'ARB-D09004', new: 'ARS-D09004'},
    {id: 10869989, old: 'ARB-D09005', new: 'ARS-D09005'},
    {id: 10869994, old: 'ARB-D09006', new: 'ARS-D09006'},
    {id: 10869999, old: 'ARB-D09007', new: 'ARS-D09007'},
    {id: 10870004, old: 'ARB-D09008', new: 'ARS-D09008'},
    {id: 10870009, old: 'ARB-D09009', new: 'ARS-D09009'},
    {id: 10870014, old: 'ARB-D09010', new: 'ARS-D09010'},
    {id: 10870019, old: 'ARB-D09011', new: 'ARS-D09011'},
    {id: 10870024, old: 'ARB-D09012', new: 'ARS-D09012'},
    {id: 10870029, old: 'ARB-D09013', new: 'ARS-D09013'},
    {id: 10903171, old: 'ARB-D09014', new: 'ARS-D09014'},
    {id: 10870034, old: 'ARB-D09015', new: 'ARS-D09015'},
    {id: 10870039, old: 'ARB-D09016', new: 'ARS-D09016'},
    {id: 10870044, old: 'ARB-D09017', new: 'ARS-D09017'},
    {id: 10870049, old: 'ARB-D09018', new: 'ARS-D09018'},
    {id: 10870054, old: 'ARB-D09019', new: 'ARS-D09019'},
    {id: 10870059, old: 'ARB-D09020', new: 'ARS-D09020'},
    {id: 10870064, old: 'ARB-D09021', new: 'ARS-D09021'},
    {id: 8094351, old: 'ARB-D09022', new: 'ARS-D09022'},
    {id: 10870069, old: 'ARB-D09023', new: 'ARS-D09023'},
    {id: 10870074, old: 'ARB-D09024', new: 'ARS-D09024'},
    {id: 10870079, old: 'ARB-D09025', new: 'ARS-D09025'},
    {id: 10870084, old: 'ARB-D09026', new: 'ARS-D09026'},
    {id: 10870089, old: 'ARB-D09027', new: 'ARS-D09027'},
    {id: 10870094, old: 'ARB-D09028', new: 'ARS-D09028'},
    {id: 10870372, old: 'ARB-D09029', new: 'ARS-D09029'}
    // ARB-D09030 already done.
];

const mcp = spawn('node', ['E:/RevitMCP/MCP-Server/build/index.js'], { stdio: ['pipe', 'pipe', 'inherit'] });
let msgId = 1;
let index = 0;

function sendNext() {
    if (index >= fixList.length) {
        console.log('--- All Done ---');
        mcp.kill();
        process.exit(0);
    }
    const item = fixList[index];
    console.log(`[${index+1}/${fixList.length}] Renaming ${item.old} -> ${item.new}...`);
    mcp.stdin.write(JSON.stringify({
        jsonrpc: '2.0',
        id: msgId++,
        method: 'tools/call',
        params: {
            name: 'modify_element_parameter',
            arguments: {
                elementId: item.id,
                parameterName: 'Sheet Number',
                value: item.new
            }
        }
    }) + '\n');
}

mcp.stdout.on('data', (chunk) => {
    const data = chunk.toString();
    if (data.includes('result')) {
        index++;
        setTimeout(sendNext, 400); // 400ms delay between updates for stability
    }
});

setTimeout(sendNext, 3000); // Wait for initialization
