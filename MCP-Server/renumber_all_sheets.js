import { RevitSocketClient } from './build/socket.js';
import fs from 'fs';

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();

        console.log("=== Step 1: 從最新緩存取得所有圖紙 ===");
        const cachePath = 'C:\\Users\\09044\\.gemini\\antigravity\\brain\\b6e890c4-d528-43fb-8f43-200fd7025ad7\\.system_generated\\steps\\186\\output.txt';
        const content = fs.readFileSync(cachePath, 'utf8');
        const allSheets = JSON.parse(content);
        
        // 只針對 ARB-D09 開頭且後方接著 3 位數字的圖紙 (排除 ARB-D0900001 系列)
        let sheets = allSheets.filter(s => {
            if (!s.Number.startsWith('ARB-D09')) return false;
            const sub = s.Number.substring(7); // 取得 D09 之後的部分
            const match = sub.match(/^(\d{3})(?:-|$)/); // 必須是 3 位數字開頭，後面接 - 或結束
            return match !== null;
        });
        
        console.log(`  找到 ${sheets.length} 張符合 ARB-D09 的圖紙`);

        // 自然排序：處理 ARB-D0900001 與 ARB-D09037 的邏輯關係
        // 使用 numeric: true 的 localeCompare 能處理不同長度的數字串
        sheets.sort((a, b) => a.Number.localeCompare(b.Number, undefined, { numeric: true, sensitivity: 'base' }));

        console.log("\n--- 排序預覽 ---");
        sheets.forEach((s, i) => console.log(`  ${i+1}. ${s.Number} (${s.Name})`));

        // Phase 1: 暫時重新命名
        console.log("\n=== Phase 1: 暫時重新命名以避免衝突 ===");
        for (let i = 0; i < sheets.length; i++) {
            const sheet = sheets[i];
            const tempNumber = `_TEMP_D09_${sheet.Id}`;
            console.log(`  [${i+1}/${sheets.length}] ${sheet.Number} -> ${tempNumber}`);
            await client.sendCommand('modify_element_parameter', {
                elementId: sheet.Id,
                parameterName: '圖紙號碼',
                value: tempNumber
            });
        }

        // Phase 2: 正式按順序重新命名
        console.log("\n=== Phase 2: 正式按順序重新命名 (ARB-D09001 起) ===");
        for (let i = 0; i < sheets.length; i++) {
            const sheet = sheets[i];
            const sequence = (i + 1).toString().padStart(3, '0');
            const targetNumber = `ARB-D09${sequence}`;
            console.log(`  [${i+1}/${sheets.length}] Element ${sheet.Id} -> ${targetNumber} (${sheet.Name})`);
            await client.sendCommand('modify_element_parameter', {
                elementId: sheet.Id,
                parameterName: '圖紙號碼',
                value: targetNumber
            });
        }

        console.log("\n✅ ARB-D09 群組重新編號完成！");
        process.exit(0);
    } catch (e) {
        console.error("❌ 發生錯誤:", e.message);
        process.exit(1);
    } finally {
        client.disconnect();
    }
}

main();
