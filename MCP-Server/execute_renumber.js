import { RevitSocketClient } from './build/socket.js';

async function main() {
    const client = new RevitSocketClient();
    try {
        console.error("Connecting to Revit...");
        await client.connect();

        console.error("Executing auto_renumber_sheets...");
        const res = await client.sendCommand('auto_renumber_sheets', {});

        console.log(JSON.stringify(res.data, null, 2));
        process.exit(0);
    } catch (e) {
        console.error("Error:", e.message);
        process.exit(1);
    } finally {
        client.disconnect();
    }
}

main();
