const WebSocket = require('ws');
const ws = new WebSocket('ws://localhost:8964');

ws.on('open', () => {
    ws.send(JSON.stringify({
        CommandName: 'get_detail_components',
        Parameters: { familyName: '圖號' },
        RequestId: 'debug_all'
    }));
});

ws.on('message', (data) => {
    const res = JSON.parse(data.toString());
    if (res.Success) {
        console.log('Total Instances:', res.Data.Items.length);
        // Note: this list might be limited by the Take(50) in the C# code if I use get_detail_components
        // I should check if I can remove Take(50) or use another query.
    }
    process.exit();
});
