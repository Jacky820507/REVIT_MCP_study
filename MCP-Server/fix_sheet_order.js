import { RevitSocketClient } from './build/socket.js';

// All sheets that need to be corrected
const fixes = [
    { elementId: 10126915, from: "ARB-D0274", to: "ARB-D0259", name: "物流中心 一層排水平面圖(1/3)" },
    { elementId: 9840840, from: "ARB-D0259", to: "ARB-D0260", name: "物流中心 一層排水平面圖(2/3)" },
    { elementId: 10126921, from: "ARB-D0275", to: "ARB-D0274", name: "物流中心 一層排水平面圖(2/3)" },
    { elementId: 11195255, from: "ARB-D0260", to: "ARB-D0275", name: "物流中心 一層排水平面圖(3/3)" },
    { elementId: 10126939, from: "ARB-D0278", to: "ARB-D0263", name: "物流中心 三層排水平面圖(1/3)" },
    { elementId: 8093967, from: "ARB-D0263", to: "ARB-D0264", name: "物流中心 三層排水平面圖(2/3)" },
    { elementId: 10126945, from: "ARB-D0279", to: "ARB-D0278", name: "物流中心 三層排水平面圖(2/3)" },
    { elementId: 8093973, from: "ARB-D0264", to: "ARB-D0279", name: "物流中心 三層排水平面圖(3/3)" },
    { elementId: 10126987, from: "ARB-D0286", to: "ARB-D0267", name: "物流中心 五層排水平面圖(1/3)" },
    { elementId: 10126993, from: "ARB-D0287", to: "ARB-D0286", name: "物流中心 五層排水平面圖(2/3)" },
    { elementId: 11195218, from: "ARB-D0267", to: "ARB-D0287", name: "物流中心 五層排水平面圖(3/3)" },
    { elementId: 10376984, from: "ARB-D0271", to: "ARB-D0270", name: "物流中心 屋突層、屋頂層排水平面圖(1/3)" },
    { elementId: 10191426, from: "ARB-D0290", to: "ARB-D0271", name: "物流中心 屋突層、屋頂層排水平面圖(1/3)" },
    { elementId: 10191432, from: "ARB-D0291", to: "ARB-D0290", name: "物流中心 屋突層、屋頂層排水平面圖(2/3)" },
    { elementId: 11194824, from: "ARB-D0270", to: "ARB-D0291", name: "物流中心 屋突層、屋頂層排水平面圖(3/3)" },
];

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();

        // Step 1: Rename all affected sheets to temp names (avoid collision)
        console.log("=== Step 1: 暫時改名避免衝突 ===");
        for (const fix of fixes) {
            const tempName = `_TEMP_FIX_${fix.elementId}`;
            console.log(`  ${fix.from} → ${tempName}`);
            await client.sendCommand('modify_element_parameter', {
                elementId: fix.elementId,
                parameterName: 'Sheet Number',
                value: tempName
            });
        }
        console.log("  暫時改名完成\n");

        // Step 2: Apply correct numbers
        console.log("=== Step 2: 套用正確編號 ===");
        for (const fix of fixes) {
            console.log(`  ElementId ${fix.elementId} → ${fix.to} (${fix.name})`);
            await client.sendCommand('modify_element_parameter', {
                elementId: fix.elementId,
                parameterName: 'Sheet Number',
                value: fix.to
            });
        }
        console.log("\n✅ 修正完成！共修正 " + fixes.length + " 張圖紙");

        process.exit(0);
    } catch (e) {
        console.error("❌ Error:", e.message);
        process.exit(1);
    } finally {
        client.disconnect();
    }
}

main();
