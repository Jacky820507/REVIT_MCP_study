import { RevitSocketClient } from '../build/socket.js';

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();
        console.log("Connected to Revit.");

        const parentViews = [
            { id: 12041291, name: "一層平面圖-TEST" },
            { id: 12041199, name: "三層平面圖-TEST" }
        ];

        const xIntervals = [
            ["B8", "B13"],
            ["B13", "B18"],
            ["B18", "B23"],
            ["B23", "B28"]
        ];

        const yIntervals = [
            ["BA", "BE"],
            ["BE", "CB"]
        ];

        for (const view of parentViews) {
            console.log(`\nProcessing parent view: ${view.name}`);
            
            for (const xInt of xIntervals) {
                for (const yInt of yIntervals) {
                    const suffix = `${xInt[0]}-${xInt[1]}_${yInt[0]}-${yInt[1]}`;
                    console.log(`  Creating view for zone ${suffix}...`);

                    // 1. Calculate Bounds
                    const boundsRes = await client.sendCommand('calculate_grid_bounds', {
                        x_grids: xInt,
                        y_grids: yInt,
                        offset_mm: 1000
                    });

                    if (!boundsRes.success) {
                        console.error(`    Failed to calculate bounds for ${suffix}:`, boundsRes.error);
                        continue;
                    }

                    // 2. Create Dependent View
                    const createRes = await client.sendCommand('create_dependent_views', {
                        parentViewIds: [view.id],
                        min: boundsRes.data.min,
                        max: boundsRes.data.max,
                        suffixName: suffix
                    });

                    if (createRes.success) {
                        console.log(`    Successfully created: ${createRes.data.CreatedViews[0].Name}`);
                    } else {
                        console.error(`    Failed to create view for ${suffix}:`, createRes.error);
                    }
                }
            }
        }

        console.log("\nFinished processing all views.");
        process.exit(0);
    } catch (e) {
        console.error("Critical Error:", e.message);
        process.exit(1);
    }
}
main();
