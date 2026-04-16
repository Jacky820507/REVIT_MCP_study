const WebSocket = require('ws');
const ws = new WebSocket('ws://localhost:8964');

ws.on('open', () => {
    ws.send(JSON.stringify({
        CommandName: 'get_detail_components',
        Parameters: { familyName: '圖號' },
        RequestId: 'final_search'
    }));
});

ws.on('message', (data) => {
    const res = JSON.parse(data.toString());
    if (res.Success) {
        console.log('Total Instances Found:', res.Data.Items.length);
        res.Data.Items.forEach(i => {
            console.log(`ID: ${i.ElementId}, Type: ${i.TypeName}, SheetID: ${i.OwnerViewId}`);
        });
    } else {
        console.error('Error:', res.Error);
    }
    process.exit();
});
