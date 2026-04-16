import { RevitSocketClient } from './build/socket.js';

async function main() {
    const client = new RevitSocketClient();
    try {
        console.log("Connecting to Revit...");
        await client.connect();

        console.log("Fetching all sheets...");
        const res = await client.sendCommand('get_all_sheets', {});
        if (!res.success) throw new Error(res.error);

        const allSheets = res.data.Sheets;
        console.log(`Found ${allSheets.length} sheets.`);

        // Range 1: D0262 - D0281
        const range1TargetStart = 801;
        // Range 2: D0282 - D0297
        const range2TargetStart = 262;

        const renumberMap = [];

        for (const sheet of allSheets) {
            const numPart = sheet.SheetNumber.match(/D(\d+)/);
            if (!numPart) continue;

            const n = parseInt(numPart[1]);

            if (n >= 262 && n <= 281) {
                const targetNum = `ARB-D${String(range1TargetStart + (n - 262)).padStart(4, '0')}`;
                renumberMap.push({ id: sheet.ElementId, original: sheet.SheetNumber, target: targetNum, name: sheet.SheetName });
            } else if (n >= 282 && n <= 297) {
                const targetNum = `ARB-D${String(range2TargetStart + (n - 282)).padStart(4, '0')}`;
                renumberMap.push({ id: sheet.ElementId, original: sheet.SheetNumber, target: targetNum, name: sheet.SheetName });
            }
        }

        if (renumberMap.length === 0) {
            console.log("No matching sheets found in ranges D0262-D0281 or D0282-D0297.");
            process.exit(0);
        }

        console.log(`Planned renumbering for ${renumberMap.length} sheets.`);
        renumberMap.forEach(m => console.log(`  ${m.original} -> ${m.target} (${m.name})`));

        console.log("=== Step 1: Temporarily renaming to avoid conflicts ===");
        for (const item of renumberMap) {
            const tempVal = `_TEMP_${item.id}`;
            await client.sendCommand('modify_element_parameter', {
                elementId: item.id,
                parameterName: "Sheet Number",
                value: tempVal
            });
            console.log(`  Renamed ${item.original} to ${tempVal}`);
        }

        console.log("=== Step 2: Applying target numbers ===");
        for (const item of renumberMap) {
            await client.sendCommand('modify_element_parameter', {
                elementId: item.id,
                parameterName: "Sheet Number",
                value: item.target
            });
            console.log(`  Renamed to final: ${item.target}`);
        }

        console.log("Renumbering complete!");
        process.exit(0);
    } catch (e) {
        console.error("Error:", e.message);
        process.exit(1);
    } finally {
        client.disconnect();
    }
}

main();
