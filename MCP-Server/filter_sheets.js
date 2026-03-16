import { RevitSocketClient } from './build/socket.js';

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();
        const res = await client.sendCommand('get_all_sheets', {});
        const filtered = res.data.Sheets.filter(s => s.SheetNumber.startsWith('ARB-D02') || s.SheetNumber.includes('D02'));
        console.log(JSON.stringify(filtered, null, 2));
        process.exit(0);
    } catch (e) {
        console.error("Error:", e.message);
        process.exit(1);
    } finally {
        client.disconnect();
    }
}

main();
