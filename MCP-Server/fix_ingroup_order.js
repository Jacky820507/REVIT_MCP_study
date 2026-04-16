import { RevitSocketClient } from './build/socket.js';

// Only fix within-group ordering. No cross-group mixing.
const fixes = [
    // 五層排水 D0266~D0268: currently (1/3), (3/3), (2/3) → should be (1/3), (2/3), (3/3)
    { elementId: 8094009, to: "ARB-D0267", name: "五層排水平面圖(2/3)" },   // D0268 → D0267
    { elementId: 11195218, to: "ARB-D0268", name: "五層排水平面圖(3/3)" },   // D0267 → D0268

    // 屋突層排水 D0270~D0272: currently (3/3), (1/3), (2/3) → should be (1/3), (2/3), (3/3)
    { elementId: 10376984, to: "ARB-D0270", name: "屋突排水平面圖(1/3)" },   // D0271 → D0270
    { elementId: 10376990, to: "ARB-D0271", name: "屋突排水平面圖(2/3)" },   // D0272 → D0271
    { elementId: 11194824, to: "ARB-D0272", name: "屋突排水平面圖(3/3)" },   // D0270 → D0272
];

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();

        console.log("=== Step 1: 暫時改名 ===");
        for (const fix of fixes) {
            const tempName = `_INGROUP_${fix.elementId}`;
            await client.sendCommand('modify_element_parameter', {
                elementId: fix.elementId, parameterName: 'Sheet Number', value: tempName
            });
            console.log(`  ${fix.elementId} → ${tempName}`);
        }

        console.log("\n=== Step 2: 套用正確編號 ===");
        for (const fix of fixes) {
            await client.sendCommand('modify_element_parameter', {
                elementId: fix.elementId, parameterName: 'Sheet Number', value: fix.to
            });
            console.log(`  ${fix.elementId} → ${fix.to} (${fix.name})`);
        }

        console.log("\n✅ 組內排序修正完成！");
        process.exit(0);
    } catch (e) {
        console.error("❌ Error:", e.message);
        process.exit(1);
    } finally {
        client.disconnect();
    }
}

main();
