import { RevitSocketClient } from './build/socket.js';

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();
        console.log("Connected. Sending get_all_sheets...");
        const res = await client.sendCommand('get_all_sheets', {});
        console.log(`Success: Found ${res.data.Sheets.length} sheets.`);
        process.exit(0);
    } catch (e) {
        console.error("Connection/Command failed:", e.message);
        process.exit(1);
    }
}
main();
