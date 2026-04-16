const { RevitSocketClient } = require('../build/socket.js');

async function main() {
    const client = new RevitSocketClient();
    try {
        console.log("Connecting to Revit...");
        await client.connect();
        console.log("Connected. Sending detect_sheet_matchlines command...");
        
        const sheetNumbers = [
            "ARB-D02002", "ARB-D02003", "ARB-D02004", "ARB-D02005", "ARB-D02006", 
            "ARB-D02007", "ARB-D02008", "ARB-D02009", "ARB-D02010", "ARB-D02011", 
            "ARB-D02012", "ARB-D02013", "ARB-D02014"
        ];
        
        const res = await client.sendCommand('detect_sheet_matchlines', {
            sheetNumbers: sheetNumbers,
            lineStyleName: '粗虛線'
        });

        if (res.data.Success) {
            const mappings = res.data.Sheets.map(s => ({
                Sheet: s.SheetNumber,
                Views: s.PlacedViews.map(v => ({
                    Id: v.ViewId,
                    Name: v.ViewName,
                    PrimaryId: v.PrimaryViewId,
                    PrimaryName: v.PrimaryViewName
                }))
            }));
            console.log(JSON.stringify(mappings, null, 2));
        } else {
            console.error("Tool report failure:", res.data);
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
