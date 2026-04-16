import { RevitSocketClient } from '../build/socket.js';

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();
        console.log("Connected to Revit.");

        // 1. Find Grids
        console.log("Searching for Grids...");
        const gridNames = ["B28", "B23", "B18", "B13", "B8", "CB", "BE", "BA"];
        const gridRes = await client.sendCommand('query_elements', { 
            category: 'Grids', 
            maxCount: 200 
        });
        
        if (gridRes.success) {
            const foundGrids = gridRes.data.Elements.filter(g => gridNames.includes(g.Name));
            console.log(`Found ${foundGrids.length} grids.`);
            foundGrids.forEach(g => console.log(` - ${g.Name} (ID: ${g.ElementId})`));
        } else {
            console.error("Grid query failed:", gridRes.error);
        }

        // 2. Find Views
        console.log("\nSearching for Views...");
        const viewNames = ["一層平面圖-TEST", "三層平面圖-TEST"];
        const viewRes = await client.sendCommand('get_all_views', { });
        
        if (viewRes.success) {
            const foundViews = viewRes.data.Views.filter(v => viewNames.includes(v.Name));
            console.log(`Found ${foundViews.length} views.`);
            foundViews.forEach(v => console.log(` - ${v.Name} (ID: ${v.ElementId})`));
        } else {
            console.error("View query failed:", viewRes.error);
        }

        process.exit(0);
    } catch (e) {
        console.error("Error:", e.message);
        process.exit(1);
    }
}
main();
