const WebSocket = require('ws');

const sheets = [
    { sheetNumber: 'ARB-D0901', detailName: '金屬障板' },
    { sheetNumber: 'ARB-D0902', detailName: '長條鋁企口天花' },
    { sheetNumber: 'ARB-D0903', detailName: '明架岩棉天花板' },
    { sheetNumber: 'ARB-D0904', detailName: '暗架矽酸鈣板天花' },
    { sheetNumber: 'ARB-D0905', detailName: '明架礦纖天花' },
    { sheetNumber: 'ARB-D0906', detailName: '矽酸鈣板天花' },
    { sheetNumber: 'ARB-D0907', detailName: '吊裝口蓋板' },
    { sheetNumber: 'ARB-D0908', detailName: '廁所隔間' },
    { sheetNumber: 'ARB-D0909', detailName: '洗手台及UT' },
    { sheetNumber: 'ARB-D0910', detailName: '無障礙廁所' },
    { sheetNumber: 'ARB-D0911', detailName: '防水閘門' },
    { sheetNumber: 'ARB-D0912', detailName: '防煙捲簾及捲門' },
    { sheetNumber: 'ARB-D0913', detailName: '防煙垂壁' },
    { sheetNumber: 'ARB-D0914', detailName: '輕隔間(一)' },
    { sheetNumber: 'ARB-D0915', detailName: '輕隔間(二)' },
    { sheetNumber: 'ARB-D0916', detailName: '輕隔間(三)' },
    { sheetNumber: 'ARB-D0917', detailName: '屋頂防水' },
    { sheetNumber: 'ARB-D0918', detailName: '玻璃扶手' },
    { sheetNumber: 'ARB-D0919', detailName: '樓梯扶手' },
    { sheetNumber: 'ARB-D0920', detailName: '高架地板' },
    { sheetNumber: 'ARB-D0922', detailName: '側排' },
    { sheetNumber: 'ARB-D0923', detailName: 'FRP水箱' },
    { sheetNumber: 'ARB-D0924', detailName: '防火被覆' },
    { sheetNumber: 'ARB-D0926', detailName: '指標系統(一)' },
    { sheetNumber: 'ARB-D0927', detailName: '指標系統(二)' },
    { sheetNumber: 'ARB-D0928', detailName: '指標系統(三)' },
    { sheetNumber: 'ARB-D0929', detailName: '指標系統(四)' },
    { sheetNumber: 'ARB-D0930', detailName: '鋼浪板屋頂' },
    { sheetNumber: 'ARB-D0931', detailName: '排煙蹲座' }
];

async function createTypes() {
    const ws = new WebSocket('ws://localhost:8964');

    await new Promise(resolve => ws.on('open', resolve));

    const results = [];
    let created = 0;
    let failed = 0;

    for (const sheet of sheets) {
        const requestId = `create_${sheet.sheetNumber}`;

        const promise = new Promise((resolve) => {
            const handler = (data) => {
                const res = JSON.parse(data.toString());
                if (res.RequestId === requestId) {
                    if (res.Success && res.Data.Success) {
                        console.log(`✅ Created: ${res.Data.TypeName}`);
                        created++;
                    } else {
                        console.log(`❌ Failed: ${sheet.sheetNumber} - ${res.Error || res.Data.Error}`);
                        failed++;
                    }
                    resolve();
                }
            };
            ws.on('message', handler);
        });

        ws.send(JSON.stringify({
            CommandName: 'create_detail_component_type',
            Parameters: {
                sheetNumber: sheet.sheetNumber,
                detailName: sheet.detailName
            },
            RequestId: requestId
        }));

        await promise;
        await new Promise(r => setTimeout(r, 100)); // Small delay between requests
    }

    console.log(`\n📊 Summary: ${created} created, ${failed} failed`);
    ws.close();
}

createTypes().catch(console.error);
