import { RevitSocketClient } from './socket.js';

async function main() {
    const client = new RevitSocketClient();
    client.on('open', async () => {
        try {
            console.log("Connecting to Revit...");
            const res = await client.send('get_all_sheets', {});
            console.log(JSON.stringify(res, null, 2));
            process.exit(0);
        } catch (e) {
            console.error("Error:", e);
            process.exit(1);
        }
    });

    client.on('error', (err) => {
        console.error("Socket error:", err);
        process.exit(1);
    });

    // Timeout if no connection
    setTimeout(() => {
        console.error("Connection timeout");
        process.exit(1);
    }, 10000);
}

main();
