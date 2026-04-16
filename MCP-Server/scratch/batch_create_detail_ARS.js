import WebSocket from 'ws';

const TARGET_FAMILY = "AE-圖號詳圖編號標頭-3.5mm";
const sheetsToCreate = [
    { number: "ARS-D09031", name: "玻璃帷幕立面圖" },
    { number: "ARS-D09032", name: "玻璃帷幕平剖圖" },
    { number: "ARS-D09033", name: "玻璃帷幕詳圖(一)" },
    { number: "ARS-D09034", name: "玻璃帷幕詳圖(二)" },
    { number: "ARS-D09035", name: "玻璃帷幕詳圖(三)" },
    { number: "ARS-D09036", name: "FRP水箱詳圖(一)" },
    { number: "ARS-D09037", name: "FRP水箱詳圖(二)" },
    { number: "ARS-D09038", name: "護欄圖騰詳圖" }
];

const ws = new WebSocket('ws://localhost:8964');

const sendCommand = (commandName, parameters) => {
    const requestId = `req_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
    const payload = JSON.stringify({
        CommandName: commandName,
        Parameters: parameters,
        RequestId: requestId
    });
    
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
            console.error(`Request ${requestId} timeout`);
            process.exit(1);
        }, 30000);

        const onMessage = (data) => {
            const res = JSON.parse(data.toString());
            if (res.RequestId === requestId) {
                ws.removeListener('message', onMessage);
                clearTimeout(timer);
                resolve(res);
            }
        };
        ws.on('message', onMessage);
        ws.send(payload);
    });
};

ws.on('open', async () => {
    console.log("=== 開始批次建立詳圖項目類型 ===");
    for (const sheet of sheetsToCreate) {
        console.log(`> 正在建立: ${sheet.number} - ${sheet.name}`);
        try {
            const res = await sendCommand('create_detail_component_type', {
                sheetNumber: sheet.number,
                detailName: sheet.name, // 使用圖說名稱作為預設之詳圖名稱 (備註)
                familyName: TARGET_FAMILY
            });
            if (res.Success) {
                console.log(`   ✅ 成功: ${res.Data.Name} (ID: ${res.Data.Id})`);
            } else {
                console.error(`   ❌ 失敗: ${res.ErrorMessage}`);
            }
        } catch (err) {
            console.error(`   ❌ 錯誤: ${err.message}`);
        }
    }
    console.log("\n=== 全部完成 ===");
    ws.close();
});

ws.on('error', (e) => console.error('❌ Socket Error:', e.message));
ws.on('close', () => process.exit(0));
