const { RevitSocketClient } = require('../build/socket.js');

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();
        
        console.log("Step 1: Confirming B1F Primary View ID...");
        const primaryViewId = 11428320; // "物流中心地下一層平面圖(分圖) TEST"
        const vInfo = await client.sendCommand('get_element_info', { elementId: primaryViewId });
        if (!vInfo.success) {
            console.error("Critical Error: Could not find mother view 11428320.");
            process.exit(1);
        } else {
            console.log("Found Mother View:", vInfo.data.Name);
        }

        console.log(`Step 2: Executing create_dependent_view_matchlines for PrimaryViewId: ${primaryViewId}`);
        const createRes = await client.sendCommand('create_dependent_view_matchlines', {
            primaryViewId: primaryViewId,
            lineStyleName: "粗虛線",
            textStyleName: "微軟正黑體 3.5 mm"
        });

        console.log("Result:", JSON.stringify(createRes, null, 2));

        if (createRes.success && createRes.data.Success) {
            console.log("Step 3: Verifying sheets ARB-D02002 to ARB-D02014...");
            const sheetNums = [];
            for (let i = 2; i <= 14; i++) {
                sheetNums.push(`ARB-D02${String(i).padStart(3, '0')}`);
            }

            const detectRes = await client.sendCommand('detect_sheet_matchlines', {
                sheetNumbers: sheetNums,
                lineStyleName: "粗虛線"
            });
            
            console.log("Verification Result Summary:");
            detectRes.data.Sheets.forEach(s => {
                console.log(`Sheet ${s.SheetNumber}: Matchlines found: ${s.DetectedMatchlineCount}`);
            });
        }

        process.exit(0);
    } catch (e) {
        console.error("Error:", e.message);
        process.exit(1);
    } finally {
        client.disconnect();
    }
}

main();
