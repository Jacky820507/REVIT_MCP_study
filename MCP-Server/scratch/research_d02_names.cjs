const { RevitSocketClient } = require('../build/socket.js');

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();
        
        // Surgical query for OST_Sheets
        const res = await client.sendCommand('query_elements', {
            category: 'OST_Sheets',
            returnFields: ['Sheet Number', 'Sheet Name']
        });

        if (res.data.Success) {
            const targetSheets = res.data.Elements.filter(s => {
                const num = s['Sheet Number'];
                return num && num.startsWith('ARB-D02');
            });
            console.log(JSON.stringify(targetSheets, null, 2));
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
