import { RevitSocketClient } from '../build/socket.js';

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();
        const res = await client.sendCommand('get_all_views', {});
        if (res.success) {
            const views = res.data.Views.filter(v => v.Name.includes("-TEST"));
            console.log(`Total views with "-TEST": ${views.length}`);
            views.sort((a,b) => a.Name.localeCompare(b.Name)).forEach(v => console.log(` - ${v.Name}`));
        }
        process.exit(0);
    } catch (e) {
        console.error(e.message);
        process.exit(1);
    }
}
main();
