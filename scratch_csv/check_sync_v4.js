const fs = require('fs');
const { spawn } = require('child_process');

const mcp = spawn('node', ['E:/RevitMCP/MCP-Server/build/index.js'], { stdio: ['pipe', 'pipe', 'inherit'] });
let msgId = 1;

setTimeout(() => {
    mcp.stdin.write(JSON.stringify({jsonrpc:'2.0', id:msgId++, method:'tools/call', params:{name:'get_all_sheets', arguments:{}}}) + '\n');
}, 2000);

let buffer = '';
mcp.stdout.on('data', (chunk) => {
    buffer += chunk.toString();
    if (buffer.includes('}]')) {
        try {
            const resLine = buffer.split('\n').find(l=>l.includes('result'));
            if(!resLine) return;
            const res = JSON.parse(resLine);
            const currentSheets = JSON.parse(res.result.content[0].text).Sheets;
            const data = JSON.parse(fs.readFileSync('E:/RevitMCP/scratch_csv/mismatch_v4_final.json', 'utf8')).changed;
            
            console.log('--- Final Status of All Mismatches ---');
            let mismatchCount = 0;
            for (let i = 0; i < data.length; i++) {
                const target = data[i];
                const actual = currentSheets.find(s => s.ElementId === target.Id);
                if (!actual || actual.SheetNumber !== target.Target) {
                    console.log(`MISMATCH - ID: ${target.Id} | Name: ${target.Name}`);
                    console.log(`   Target: ${target.Target} | Actual: ${actual ? actual.SheetNumber : 'NOT FOUND'}`);
                    mismatchCount++;
                }
            }
            console.log(`\nFinal Verification: ${data.length - mismatchCount}/${data.length} sheets correct.`);
            console.log(`Total remaining mismatches: ${mismatchCount}`);
            mcp.kill();
            process.exit(0);
        } catch(e) {}
    }
});
