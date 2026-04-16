import { RevitSocketClient } from './build/socket.js';

/**
 * 還原策略：
 * 
 * 我之前的修正腳本做了跨組交換，需要還原。
 * 
 * 原始狀態（auto_renumber_sheets 產生的結果，各 ElementId 的"原始位置"）：
 * 
 * === 一層排水 ===
 * Group A (D0258~D0260 範圍):
 *   D0258: 10000534 - (1/3)  ← 沒動過，正確
 *   D0259: 9840840  - (2/3)  ← 我把它移到 D0260
 *   D0260: 11195255 - (3/3)  ← 我把它移到 D0275
 * 
 * Group B (D0271~D0276 範圍，auto_renumber 後):
 *   原本 D0271: 10126915 - (1/3) ← 我把它移到 D0259
 *   原本 D0272: 10126921 - (2/3) ← 我把它移到 D0274
 *   D0273: 10126927 - (3/3) ← 沒動過
 * 
 * 其實原始推移後的正確位置：
 *   10126915 應在 D0274 (原本 auto_renumber 把它安排在 D0271)
 *   10126921 應在 D0275 (原本在 D0272)
 *   10126927 在 D0276 (沒動)
 * 
 * 因為 auto_renumber_sheets 已經做了推移，產生的連續序列本身是正確的，
 * 只不過「同名(X/Y)」群組內的排序可能有誤。
 * 
 * 但用戶的意思是：不要動已有的同名圖紙順序！
 * 原始 auto_renumber_sheets 的推移結果就是正確的位置。
 * 所以我需要把每個 ElementId 還原到 auto_renumber_sheets 的結果狀態。
 * 
 * auto_renumber 結果 vs 目前狀態：
 * 
 * 一層排水：
 *   D0258: 10000534 (1/3) → 目前: 10000534 ✅ 沒變
 *   D0259: 9840840  (2/3) → 目前: 10126915 ❌ 應還原為 9840840
 *   D0260: 11195255 (3/3) → 目前: 9840840  ❌ 應還原為 11195255
 *   ...
 *   D0273: 10126909 索引  → 目前: 10126909 ✅ 沒變
 *   D0274: 10126915 (1/3) → 目前: 10126921 ❌ 應還原為 10126915
 *   D0275: 10126921 (2/3) → 目前: 11195255 ❌ 應還原為 10126921
 *   D0276: 10126927 (3/3) → 目前: 10126927 ✅ 沒變
 */

// 還原清單：將每個 ElementId 移回 auto_renumber_sheets 時產生的正確位置
// 格式: current → target (restore to auto_renumber result)
const restoreList = [
    // === 一層排水 ===
    // 目前 D0259 有 10126915，但 10126915 應回到 D0274
    // 目前 D0260 有 9840840，但 9840840 應回到 D0259
    // 目前 D0274 有 10126921，但 10126921 應回到 D0275
    // 目前 D0275 有 11195255，但 11195255 應回到 D0260
    { elementId: 9840840, to: "ARB-D0259", name: "一層排水平面圖(2/3)" },
    { elementId: 11195255, to: "ARB-D0260", name: "一層排水平面圖(3/3)" },
    { elementId: 10126915, to: "ARB-D0274", name: "一層排水平面圖(1/3)" },
    { elementId: 10126921, to: "ARB-D0275", name: "一層排水平面圖(2/3)" },

    // === 三層排水 ===
    // 目前 D0263 有 10126939，但 10126939 應回到 D0278
    // 目前 D0264 有 8093967，但 8093967 應回到 D0263
    // 目前 D0278 有 10126945，但 10126945 應回到 D0279
    // 目前 D0279 有 8093973，但 8093973 應回到 D0264
    { elementId: 8093967, to: "ARB-D0263", name: "三層排水平面圖(2/3)" },
    { elementId: 8093973, to: "ARB-D0264", name: "三層排水平面圖(3/3)" },
    { elementId: 10126939, to: "ARB-D0278", name: "三層排水平面圖(1/3)" },
    { elementId: 10126945, to: "ARB-D0279", name: "三層排水平面圖(2/3)" },

    // === 五層排水 ===
    // 目前 D0267 有 10126987，但 10126987 應回到 D0286
    // 目前 D0268 有 8094009，但 8094009 應回到 D0267
    // 目前 D0286 有 10126993，但 10126993 應回到 D0287
    // 目前 D0287 有 11195218，但 11195218 應回到 D0268 (was D0267 originally)
    // Wait, let me re-check. Need to figure out original auto_renumber positions.
    // Original after auto_renumber:
    //   D0266: 8094003 (1/3), D0267: 11195218(3/3), D0268: 8094009(2/3)
    //   D0285-D0288 range had: 10126981(索引), 10126987(1/3), 10126993(2/3), 10126999(3/3)
    // My fix moved: 10126987 from D0286→D0267, 10126993 from D0287→D0286, 11195218 from D0267→D0287
    // So restore:
    { elementId: 11195218, to: "ARB-D0267", name: "五層排水平面圖(3/3)" },
    { elementId: 8094009, to: "ARB-D0268", name: "五層排水平面圖(2/3)" },
    { elementId: 10126987, to: "ARB-D0286", name: "五層排水平面圖(1/3)" },
    { elementId: 10126993, to: "ARB-D0287", name: "五層排水平面圖(2/3)" },

    // === 屋突層排水 ===
    // Original after auto_renumber:
    //   D0270: 11194824(3/3), D0271: 10376984(1/3), D0272: 10376990(2/3)
    //   D0289-D0292: 10191420(索引), 10191426(1/3), 10191432(2/3), 10191438(3/3)
    // My fix moved: 10376984 D0271→D0270, 10191426 D0290→D0271, 10191432 D0291→D0290, 11194824 D0270→D0291
    // So restore:
    { elementId: 11194824, to: "ARB-D0270", name: "屋突排水平面圖(3/3)" },
    { elementId: 10376984, to: "ARB-D0271", name: "屋突排水平面圖(1/3)" },
    { elementId: 10191426, to: "ARB-D0290", name: "屋突排水平面圖(1/3)" },
    { elementId: 10191432, to: "ARB-D0291", name: "屋突排水平面圖(2/3)" },
];

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();

        // Step 1: Rename all affected sheets to temp names
        console.log("=== Step 1: 暫時改名避免衝突 ===");
        for (const fix of restoreList) {
            const tempName = `_RESTORE_${fix.elementId}`;
            console.log(`  ElementId ${fix.elementId} → ${tempName}`);
            await client.sendCommand('modify_element_parameter', {
                elementId: fix.elementId,
                parameterName: 'Sheet Number',
                value: tempName
            });
        }
        console.log("  暫時改名完成\n");

        // Step 2: Apply correct numbers
        console.log("=== Step 2: 還原到正確編號 ===");
        for (const fix of restoreList) {
            console.log(`  ElementId ${fix.elementId} → ${fix.to} (${fix.name})`);
            await client.sendCommand('modify_element_parameter', {
                elementId: fix.elementId,
                parameterName: 'Sheet Number',
                value: fix.to
            });
        }
        console.log("\n✅ 還原完成！共還原 " + restoreList.length + " 張圖紙");

        process.exit(0);
    } catch (e) {
        console.error("❌ Error:", e.message);
        process.exit(1);
    } finally {
        client.disconnect();
    }
}

main();
