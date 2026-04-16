import { RevitSocketClient } from '../build/socket.js';

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();
        
        const gridNames = ["B28", "B23", "B18", "B13", "B8", "CB", "BE", "BA"];
        const gridRes = await client.sendCommand('get_all_grids', {});
        
        if (!gridRes.success) {
            console.error("Failed to get grids:", gridRes.error);
            process.exit(1);
        }

        const foundGrids = gridRes.data.Grids.filter(g => gridNames.includes(g.Name));
        console.log("Grid Details:");
        foundGrids.forEach(g => {
            console.log(` - ${g.Name}: ${g.Direction}, Start(${g.StartX}, ${g.StartY}), End(${g.EndX}, ${g.EndY})`);
        });

        // Horizontal zones (X intervals)
        const xGrids = ["B28", "B23", "B18", "B13", "B8"].map(name => foundGrids.find(g => g.Name === name)).filter(Boolean);
        // Vertical zones (Y intervals)
        const yGrids = ["CB", "BE", "BA"].map(name => foundGrids.find(g => g.Name === name)).filter(Boolean);

        xGrids.sort((a, b) => a.StartX - b.StartX);
        yGrids.sort((a, b) => a.StartY - b.StartY);

        console.log("\nX Intervals:");
        for(let i=0; i<xGrids.length-1; i++) {
            console.log(`  Zone X${i+1}: ${xGrids[i].Name} to ${xGrids[i+1].Name}`);
        }

        console.log("\nY Intervals:");
        for(let j=0; j<yGrids.length-1; j++) {
            console.log(`  Zone Y${j+1}: ${yGrids[j].Name} to ${yGrids[j+1].Name}`);
        }

        process.exit(0);
    } catch (e) {
        console.error("Error:", e.message);
        process.exit(1);
    }
}
main();
