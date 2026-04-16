const fs = require('fs');
const { spawn } = require('child_process');

// --- Config ---
const CSV_PATH = 'E:/RevitMCP/圖紙清單_utf8.csv';
const TITLE_BLOCK_ID = 4428;
const BATCH_SIZE = 50; 
const SKIP_FIRST = 0; 

// --- Read CSV (UTF-8) ---
const text = fs.readFileSync(CSV_PATH, 'utf8');
const lines = text.split(/\r?\n/).filter(l => l.trim());
const allSheets = lines.slice(1).map(line => {
    const [number, ...nameParts] = line.split(',');
    return { number: number.trim(), name: nameParts.join(',').trim() };
}).filter(s => s.number && s.name).slice(SKIP_FIRST);

console.log(`📄 CSV 讀取完成: 共 ${allSheets.length} 張圖紙`);

// --- Start MCP Server ---
// Using the path to index.js in the RevitMCP repository
const mcp = spawn('node', ['E:/RevitMCP/MCP-Server/build/index.js'], {
    stdio: ['pipe', 'pipe', 'inherit']
});

let msgId = 1;
let batchIdx = 0;
let totalCreated = 0;
let totalFailed = 0;

// Split into batches
const batches = [];
for (let i = 0; i < allSheets.length; i += BATCH_SIZE) {
    batches.push(allSheets.slice(i, i + BATCH_SIZE));
}
console.log(`📦 分成 ${batches.length} 批次，每批最多 ${BATCH_SIZE} 張`);

function sendBatch() {
    if (batchIdx >= batches.length) {
        console.log(`\n✅ 全部完成! 成功: ${totalCreated}, 失敗: ${totalFailed}`);
        mcp.kill();
        process.exit(0);
        return;
    }

    const batch = batches[batchIdx];
    const req = {
        jsonrpc: "2.0",
        id: msgId++,
        method: "tools/call",
        params: {
            name: "create_sheets",
            arguments: {
                titleBlockId: TITLE_BLOCK_ID,
                sheets: batch
            }
        }
    };

    console.log(`\n📋 批次 ${batchIdx + 1}/${batches.length}: 建立 ${batch.length} 張 (${batch[0].number} ~ ${batch[batch.length - 1].number})...`);
    mcp.stdin.write(JSON.stringify(req) + '\n');
}

let buffer = '';
mcp.stdout.on('data', (chunk) => {
    buffer += chunk.toString();
    let newlineIdx;
    while ((newlineIdx = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, newlineIdx).trim();
        buffer = buffer.slice(newlineIdx + 1);
        if (!line) continue;
        try {
            const res = JSON.parse(line);
            if (res.id) {
                if (res.error || (res.result && res.result.isError)) {
                    const errMsg = res.error?.message || JSON.stringify(res.result);
                    console.log(`  ❌ 批次 ${batchIdx + 1} 失敗: ${errMsg}`);
                    totalFailed += batches[batchIdx].length;
                } else {
                    console.log(`  ✅ 批次 ${batchIdx + 1} 完成`);
                    totalCreated += batches[batchIdx].length;
                }
                batchIdx++;
                sendBatch();
            }
        } catch (e) {}
    }
});

// Wait for MCP to initialize, then start
setTimeout(sendBatch, 2000);
