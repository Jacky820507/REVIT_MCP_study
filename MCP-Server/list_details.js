import { RevitSocketClient } from './build/socket.js';

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();
        const res = await client.sendCommand('get_all_sheets', {});
        const sheets = res.data.Sheets;

        const target = sheets.filter(s => {
            if (!s.SheetNumber) return false;
            const numPart = parseInt(s.SheetNumber.replace('ARB-D', ''));
            return s.SheetNumber.startsWith('ARB-D02') && numPart >= 260 && numPart <= 310;
        }).sort((a, b) => a.SheetNumber.localeCompare(b.SheetNumber));

        console.log(JSON.stringify(target, null, 2));
        process.exit(0);
    } catch (e) {
        process.exit(1);
    }
}
main();
