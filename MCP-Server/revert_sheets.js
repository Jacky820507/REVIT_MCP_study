import { RevitSocketClient } from './build/socket.js';
import fs from 'fs';

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();

        console.log("=== 正在讀取備份資料 ===");
        const cachePath = 'C:\\Users\\09044\\.gemini\\antigravity\\brain\\b6e890c4-d528-43fb-8f43-200fd7025ad7\\.system_generated\\steps\\5\\output.txt';
        const content = fs.readFileSync(cachePath, 'utf8');
        const originalSheets = JSON.parse(content);
        
        console.log(`找到 ${originalSheets.length} 張圖紙的備份紀錄`);

        console.log("\n=== Phase 1: 暫時解除編號衝突 ===");
        for (let i = 0; i < originalSheets.length; i++) {
            const sheet = originalSheets[i];
            const tempNumber = `_RESTORE_${sheet.Id}`;
            await client.sendCommand('modify_element_parameter', {
                elementId: sheet.Id,
                parameterName: '圖紙號碼',
                value: tempNumber
            });
        }

        console.log("\n=== Phase 2: 恢復原始編號 ===");
        for (let i = 0; i < originalSheets.length; i++) {
            const sheet = originalSheets[i];
            console.log(`  [${i+1}/${originalSheets.length}] 恢復: ${sheet.Number} (${sheet.Name})`);
            await client.sendCommand('modify_element_parameter', {
                elementId: sheet.Id,
                parameterName: '圖紙號碼',
                value: sheet.Number
            });
        }

        console.log("\n✅ 恢復完成！");
        process.exit(0);
    } catch (e) {
        console.error("❌ 錯誤:", e.message);
        process.exit(1);
    } finally {
        client.disconnect();
    }
}
main();
