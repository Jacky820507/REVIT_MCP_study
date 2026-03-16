import { RevitSocketClient } from './build/socket.js';

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();
        const res = await client.sendCommand('get_all_sheets', {});
        const sheets = res.data.Sheets;

        // Find all sheets with (X/Y) pattern in the D0259~D0292 range
        const targetSheets = sheets.filter(s => {
            const num = parseInt(s.SheetNumber.replace('ARB-D', ''));
            return s.SheetNumber.startsWith('ARB-D02') && num >= 259 && num <= 292;
        });

        // Group by base name (remove the (X/Y) part)
        const regex = /^(.*?)[\(（]([\d]+)\/([\d]+)[\)）]$/;
        const groups = {};

        for (const sheet of targetSheets) {
            const match = sheet.SheetName.match(regex);
            if (match) {
                const baseName = match[1].trim();
                if (!groups[baseName]) groups[baseName] = [];
                groups[baseName].push({
                    ...sheet,
                    index: parseInt(match[2]),
                    total: parseInt(match[3])
                });
            }
        }

        // Check each group for ordering issues
        console.log("=== 分頁圖紙排序分析 ===\n");
        let hasIssue = false;
        const fixes = [];

        for (const [baseName, items] of Object.entries(groups)) {
            if (items.length < 2) continue;

            // Sort by current sheet number
            items.sort((a, b) => a.SheetNumber.localeCompare(b.SheetNumber));

            // Check if the (X/Y) index matches the number order
            let ordered = true;
            for (let i = 1; i < items.length; i++) {
                if (items[i].index < items[i - 1].index) {
                    ordered = false;
                    break;
                }
            }

            if (!ordered) {
                hasIssue = true;
                console.log(`❌ 排序錯誤: ${baseName}`);
                items.forEach(s => console.log(`   ${s.SheetNumber} → ${s.SheetName} (index: ${s.index})`));

                // Calculate correct assignments
                const numbers = items.map(s => s.SheetNumber).sort();
                const sortedByIndex = [...items].sort((a, b) => a.index - b.index);

                console.log(`   修正方案:`);
                for (let i = 0; i < sortedByIndex.length; i++) {
                    if (sortedByIndex[i].SheetNumber !== numbers[i]) {
                        console.log(`   ElementId ${sortedByIndex[i].ElementId}: ${sortedByIndex[i].SheetNumber} → ${numbers[i]} (${sortedByIndex[i].SheetName})`);
                        fixes.push({ elementId: sortedByIndex[i].ElementId, from: sortedByIndex[i].SheetNumber, to: numbers[i], name: sortedByIndex[i].SheetName });
                    }
                }
                console.log("");
            } else {
                console.log(`✅ 排序正確: ${baseName}`);
                items.forEach(s => console.log(`   ${s.SheetNumber} → ${s.SheetName}`));
                console.log("");
            }
        }

        if (!hasIssue) {
            console.log("所有分頁圖紙排序正確！");
        }

        console.log("\n=== 需要修正的清單 (JSON) ===");
        console.log(JSON.stringify(fixes, null, 2));

        process.exit(0);
    } catch (e) {
        console.error("Error:", e.message);
        process.exit(1);
    } finally {
        client.disconnect();
    }
}

main();
