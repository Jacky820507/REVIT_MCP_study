import { RevitSocketClient } from '../build/socket.js';

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();
        console.log("Connected to Revit.");

        const parentViewIds = [12041291, 12041199];
        const x_grid_names = ["B8", "B13", "B18", "B23", "B28"];
        const y_grid_names = ["BA", "BE", "CB"];

        console.time("BatchOperation");
        console.log("Calling create_grid_cropped_views_batch...");
        
        const res = await client.sendCommand('create_grid_cropped_views_batch', {
            parentViewIds,
            x_grid_names,
            y_grid_names,
            offset_mm: 1000
        });

        console.timeEnd("BatchOperation");

        if (res.success) {
            console.log(`Success! Created ${res.data.TotalCreated} views.`);
            res.data.CreatedViews.slice(0, 5).forEach(v => console.log(` - ${v.Name} (ID: ${v.ElementId})`));
            if (res.data.TotalCreated > 5) console.log(` ... and ${res.data.TotalCreated - 5} more.`);
        } else {
            console.error("Batch tool failed:", res.error);
        }

        process.exit(0);
    } catch (e) {
        console.error("Error:", e.message);
        process.exit(1);
    }
}
main();
