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
            
            if (captured.length === 0) {
                console.log('No sheets found matching ARB-DXXXXX');
                mcp.kill();
                process.exit(0);
                return;
            }

            const blocks = [];
            let currentBlock = [captured[0]];
            
            for (let i = 1; i < captured.length; i++) {
                if (captured[i].num <= captured[i-1].num + 10) { // Gap <= 10 considered same block for summary
                    currentBlock.push(captured[i]);
                } else {
                    blocks.push(currentBlock);
                    currentBlock = [captured[i]];
                }
            }
            blocks.push(currentBlock);
            
            console.log('### Revit 圖紙編號順序檢查報告\n');
            console.log(`檢查範圍：ARB-D00001 ~ ARB-D09030\n`);
            console.log(`| 區塊 | 起始編號 | 結束編號 | 圖紙數量 | 內部缺號 |`);
            console.log(`| :--- | :--- | :--- | :--- | :--- |`);
            
            blocks.forEach((b, idx) => {
                const start = b[0].original;
                const end = b[b.length - 1].original;
                const count = b.length;
                
                const internalGaps = [];
                for(let j=0; j<b.length-1; j++) {
                    if(b[j+1].num > b[j].num + 1) {
                        for(let k=b[j].num+1; k<b[j+1].num; k++) {
                            internalGaps.push('ARB-D' + String(k).padStart(5, '0'));
                        }
                    }
                }
                
                const gapStr = internalGaps.length > 0 ? internalGaps.join(', ') : '無';
                console.log(`| ${idx + 1} | ${start} | ${end} | ${count} | ${gapStr} |`);
            });

            mcp.kill();
            process.exit(0);
        } catch(e) {
            console.error(e);
        }
    }
});
