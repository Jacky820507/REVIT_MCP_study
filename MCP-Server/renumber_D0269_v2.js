import { RevitSocketClient } from './build/socket.js';

const renumberMap = [
    { id: 10126957, target: "ARB-D0270", name: "四層排水平面索引圖" },
    { id: 10126963, target: "ARB-D0271", name: "四層排水平面圖(1/3)" },
    { id: 10126969, target: "ARB-D0272", name: "四層排水平面圖(2/3)" },
    { id: 10126975, target: "ARB-D0273", name: "四層排水平面圖(3/3)" },
    { id: 8093997, target: "ARB-D0274", name: "五層排水索引圖" },
    { id: 8094003, target: "ARB-D0275", name: "五層排水平面圖(1/3)" },
    { id: 8094009, target: "ARB-D0276", name: "五層排水平面圖(2/3)" },
    { id: 11195218, target: "ARB-D0277", name: "五層排水平面圖(3/3)" },
    { id: 10376978, target: "ARB-D0278", name: "屋突層排水平面索引圖" },
    { id: 10376984, target: "ARB-D0279", name: "屋突層排水平面圖(1/3)" },
    { id: 10376990, target: "ARB-D0280", name: "屋突層排水平面圖(2/3)" },
    { id: 11194824, target: "ARB-D0281", name: "屋突層排水平面圖(3/3)" },
    { id: 10126909, target: "ARB-D0282", name: "一層排水索引圖" },
    { id: 10126915, target: "ARB-D0283", name: "一層排水平面圖(1/3)" },
    { id: 10126921, target: "ARB-D0284", name: "一層排水平面圖(2/3)" },
    { id: 10126927, target: "ARB-D0285", name: "一層排水平面圖(3/3)" },
    { id: 10126933, target: "ARB-D0286", name: "三層排水索引圖" },
    { id: 10126939, target: "ARB-D0287", name: "三層排水平面圖(1/3)" },
    { id: 10126945, target: "ARB-D0288", name: "三層排水平面圖(2/3)" },
    { id: 10126951, target: "ARB-D0289", name: "三層排水平面圖(3/3)" },
];

async function main() {
    const client = new RevitSocketClient();
    try {
        await client.connect();

        console.log("=== Resuming: Applying final target numbers ===");
        for (const item of renumberMap) {
            try {
                await client.sendCommand('modify_element_parameter', {
                    elementId: item.id,
                    parameterName: "Sheet Number",
                    value: item.target
                });
                console.log(`OK: Id:${item.id} -> ${item.target} (${item.name})`);
            } catch (e) {
                console.log(`SKIP/RETRY: Id:${item.id} already processed or conflict? ${e.message}`);
                // Try renaming to temp again just in case
                await client.sendCommand('modify_element_parameter', {
                    elementId: item.id,
                    parameterName: "Sheet Number",
                    value: `_RETRY_${item.id}`
                });
                await client.sendCommand('modify_element_parameter', {
                    elementId: item.id,
                    parameterName: "Sheet Number",
                    value: item.target
                });
                console.log(`RE-OK: Id:${item.id} -> ${item.target}`);
            }
        }

        console.log("Renumbering complete.");
        process.exit(0);
    } catch (e) {
        console.error(e);
        process.exit(1);
    }
}
main();
