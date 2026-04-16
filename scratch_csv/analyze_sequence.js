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
            const sheets = JSON.parse(res.result.content[0].text).Sheets;
            
            // Range: ARB-D00001 to ARB-D09030
            const pattern = /^ARB-D(\d+)$/;
            const captured = [];
            
            sheets.forEach(s => {
                const match = s.SheetNumber.match(pattern);
                if (match) {
                    const num = parseInt(match[1]);
                    captured.push({ num, original: s.SheetNumber, name: s.SheetName });
                }
            });
            
            captured.sort((a, b) => a.num - b.num);
            
            console.log('--- Sheet Number Sequence Analysis ---');
            console.log(`Total sheets matching pattern "ARB-DXXXXX": ${captured.length}`);
            
            if (captured.length === 0) {
                console.log('No sheets found matching the pattern.');
                mcp.kill();
                process.exit(0);
                return;
            }

            const min = captured[0].num;
            const max = captured[captured.length - 1].num;
            console.log(`Range found: ARB-D${String(min).padStart(5, '0')} to ARB-D${String(max).padStart(5, '0')}`);
            
            const gaps = [];
            for (let i = 0; i < captured.length - 1; i++) {
                const current = captured[i].num;
                const next = captured[i+1].num;
                if (next > current + 1) {
                    gaps.push({ from: current + 1, to: next - 1 });
                }
            }
            
            if (gaps.length > 0) {
                console.log('\n⚠️ Found gaps in the sequence:');
                gaps.forEach(g => {
                    if (g.from === g.to) {
                        console.log(`- Missing: ARB-D${String(g.from).padStart(5, '0')}`);
                    } else {
                        console.log(`- Missing: ARB-D${String(g.from).padStart(5, '0')} to ARB-D${String(g.to).padStart(5, '0')} (${g.to - g.from + 1} sheets)`);
                    }
                });
            } else {
                console.log('\n✅ No gaps found! The sequence is continuous.');
            }
            
            // Check for potential out-of-range or duplicates (handled by sort/loop for gaps)
            const duplicates = [];
            for (let i = 0; i < captured.length - 1; i++) {
                if (captured[i].num === captured[i+1].num) {
                    duplicates.push(captured[i].original);
                }
            }
            if (duplicates.length > 0) {
                 console.log('\n❌ Found duplicates (matching number part):', duplicates);
            }

            mcp.kill();
            process.exit(0);
        } catch(e) {
            console.error(e);
        }
    }
});
