import { RevitSocketClient } from './build/socket.js';

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();
        const res = await client.sendCommand('get_all_sheets', {});
        const sheets = res.data.Sheets;

        // Filter to the affected range
        const targetSheets = sheets.filter(s => {
            return s.SheetNumber.startsWith('ARB-D02') &&
                parseInt(s.SheetNumber.replace('ARB-D', '')) >= 257 &&
                parseInt(s.SheetNumber.replace('ARB-D', '')) <= 292;
        }).sort((a, b) => a.SheetNumber.localeCompare(b.SheetNumber));

        console.log("=== 目前圖紙狀態 (ARB-D0257 ~ ARB-D0292) ===\n");
        console.log("編號           | ElementId  | 圖紙名稱");
        console.log("-------------- | ---------- | --------");
        for (const s of targetSheets) {
            console.log(`${s.SheetNumber.padEnd(14)} | ${String(s.ElementId).padEnd(10)} | ${s.SheetName}`);
        }

        // Now group by consecutive numbers AND same base name
        const regex = /^(.*?)[\(（]([\d]+)\/([\d]+)[\)）]$/;

        console.log("\n\n=== 連續群組分析 ===\n");

        let currentGroup = [];
        let currentBaseName = null;

        const groups = [];

        for (const s of targetSheets) {
            const match = s.SheetName.match(regex);
            if (match) {
                const baseName = match[1].trim();
                const num = parseInt(s.SheetNumber.replace('ARB-D', ''));

                if (currentBaseName === baseName && currentGroup.length > 0) {
                    const lastNum = parseInt(currentGroup[currentGroup.length - 1].SheetNumber.replace('ARB-D', ''));
                    if (num - lastNum <= 3) { // consecutive (allow small gaps)
                        currentGroup.push({ ...s, index: parseInt(match[2]), baseName });
                        continue;
                    }
                }

                // Start new group
                if (currentGroup.length > 0) groups.push([...currentGroup]);
                currentGroup = [{ ...s, index: parseInt(match[2]), baseName }];
                currentBaseName = baseName;
            } else {
                if (currentGroup.length > 0) groups.push([...currentGroup]);
                currentGroup = [];
                currentBaseName = null;
            }
        }
        if (currentGroup.length > 0) groups.push([...currentGroup]);

        // Check each consecutive group
        const fixes = [];
        for (const grp of groups) {
            if (grp.length < 2) continue;

            // Check order
            let ordered = true;
            for (let i = 1; i < grp.length; i++) {
                if (grp[i].index < grp[i - 1].index) { ordered = false; break; }
            }

            const status = ordered ? "✅" : "❌";
            console.log(`${status} ${grp[0].baseName} [${grp[0].SheetNumber} ~ ${grp[grp.length - 1].SheetNumber}]`);
            grp.forEach(s => console.log(`   ${s.SheetNumber} → ${s.SheetName} (index: ${s.index})`));

            if (!ordered) {
                const numbers = grp.map(s => s.SheetNumber).sort();
                const sortedByIndex = [...grp].sort((a, b) => a.index - b.index);

                console.log(`   修正方案:`);
                for (let i = 0; i < sortedByIndex.length; i++) {
                    if (sortedByIndex[i].SheetNumber !== numbers[i]) {
                        console.log(`   ElementId ${sortedByIndex[i].ElementId}: ${sortedByIndex[i].SheetNumber} → ${numbers[i]}`);
                        fixes.push({ elementId: sortedByIndex[i].ElementId, from: sortedByIndex[i].SheetNumber, to: numbers[i], name: sortedByIndex[i].SheetName });
                    }
                }
            }
            console.log("");
        }

        console.log("\n=== 需要修正的交換清單 ===");
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
