import WebSocket from 'ws';

async function main() {
    const ws = new WebSocket('ws://localhost:8964');

    ws.on('open', () => {
        console.log('Connected to Revit Socket');
        
        const createCmd = {
            CommandName: 'create_detail_component_type',
            Parameters: {
                sheetNumber: 'ARB-D0304',
                detailName: '測試',
                detailNumber: '3',
                familyName: 'TEST-圖號詳圖編號標頭-3.5mm'
            }
        };
        console.log('Sending command:', JSON.stringify(createCmd, null, 2));
        ws.send(JSON.stringify(createCmd));
    });

    ws.on('message', (data) => {
        const response = JSON.parse(data.toString());
        console.log('Response:', JSON.stringify(response, null, 2));
        process.exit(0);
    });

    ws.on('error', (err) => {
        console.error('Socket Error:', err);
        process.exit(1);
    });

    setTimeout(() => {
        console.log('Timeout waiting for response');
        process.exit(1);
    }, 10000);
}

main();
