import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MCP_INDEX = path.resolve(__dirname, 'build/index.js');

// === 參數設定 ===
// 從命令列讀取圖紙號碼，例如: node detect_matchlines.js ARB-D01001 ARB-D01002
const sheetNumbers = process.argv.slice(2);

if (sheetNumbers.length === 0) {
    console.error('❌ 請提供圖紙號碼，例如：');
    console.error('   node detect_matchlines.js ARA-D01001 ARA-D01002');
    process.exit(1);
}

console.log('==========================================');
console.log('   偵測指定圖紙銜接線與文字');
console.log('==========================================');
console.log(`📋 掃瞄圖紙：${sheetNumbers.join(', ')}`);
console.log('');

const mcpProcess = spawn('node', [MCP_INDEX], {
    stdio: ['pipe', 'pipe', 'inherit'],
    cwd: __dirname
});

const reqId = `req_detect_${Date.now()}`;
let resolved = false;

mcpProcess.stdout.on('data', (chunk) => {
    const lines = chunk.toString().split('\n').filter(l => l.trim());
    for (const line of lines) {
        try {
            const parsed = JSON.parse(line);
            if (parsed.id === reqId) {
                resolved = true;
                mcpProcess.kill();

                if (parsed.result?.isError) {
                    console.error('❌ 執行失敗：');
                    console.error(parsed.result.content?.[0]?.text || '未知錯誤');
                    process.exit(1);
                }

                const raw = parsed.result?.content?.[0]?.text;
                if (!raw) {
                    console.error('❌ 無法解析回應');
                    process.exit(1);
                }

                const data = JSON.parse(raw);
                printResults(data);
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
                sheetNumbers,
                lineStyleName: '粗虛線',
            }
        }
    };
    mcpProcess.stdin.write(JSON.stringify(request) + '\n');
}, 1500);

setTimeout(() => {
    if (!resolved) {
        console.error('❌ 連線逾時，請確認 Revit 已啟動並開啟 MCP 服務。');
        mcpProcess.kill();
        process.exit(1);
    }
}, 15000);

function printResults(data) {
    if (!data.Success) {
        console.error(`❌ 失敗：${data.Message}`);
        return;
    }

    const sheets = data.Sheets || [];
    for (const sheet of sheets) {
        console.log(`\n📄 圖紙：[${sheet.SheetNumber}] ${sheet.SheetName}`);
        console.log(`   放置視圖數：${sheet.PlacedViewportCount}`);

        if (sheet.PlacedViews?.length > 0) {
            console.log('   視圖清單：');
            for (const v of sheet.PlacedViews) {
                console.log(`     - [${v.ViewId}] ${v.ViewName} (${v.ViewType}) 圖號：${v.ViewSheetLabel || '—'}`);
            }
        }

        const total = sheet.DetectedMatchlineCount || 0;
        console.log(`\n   偵測銜接元素：${total} 個`);

        if (sheet.LineMatches?.length > 0) {
            console.log('   🔵 銜接線 (Lines)：');
            for (const l of sheet.LineMatches) {
                console.log(`     - ID: ${l.ElementId} | 樣式: ${l.StyleName}`);
            }
        } else {
            console.log('   🔵 銜接線 (Lines)：無');
        }

        if (sheet.TextMatches?.length > 0) {
            console.log('   🟡 銜接文字 (Texts)：');
            for (const t of sheet.TextMatches) {
                console.log(`     - ID: ${t.ElementId} | 文字: ${t.Text}`);
            }
        } else {
            console.log('   🟡 銜接文字 (Texts)：無');
        }
    }

    console.log('\n✅ 偵測完成！');
}
