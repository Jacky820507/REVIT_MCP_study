const WebSocket = require('ws');

async function sendCmd(ws, method, params) {
    return new Promise((resolve, reject) => {
        const id = Date.now().toString();
        const handler = (data) => {
            const resp = JSON.parse(data.toString());
            if (resp.RequestId === id) {
                ws.off('message', handler);
                resolve(resp);
            }
        };
        ws.on('message', handler);
        ws.send(JSON.stringify({ jsonrpc: '2.0', method, params, id }));
        setTimeout(() => { ws.off('message', handler); reject(new Error('Timeout')); }, 15000);
    });
}

(async () => {
    const ws = new WebSocket('ws://localhost:8964');
    await new Promise(r => ws.on('open', r));
    console.log('Connected.');

    // 1. 查詢 element 7726994 的基本資訊
    const info = await sendCmd(ws, 'get_element_info', { elementId: 7726994 });
    console.log('\n=== Element 7726994 Info ===');
    console.log(JSON.stringify(info.Data, null, 2));

    // 2. 查詢當前作用中的視圖資訊
    const view = await sendCmd(ws, 'get_active_view', {});
    console.log('\n=== Active View ===');
    console.log(JSON.stringify(view.Data, null, 2));

    // 3. 查詢當前視圖內所有 FilledRegion
    const regions = await sendCmd(ws, 'query_elements', { 
        category: 'FilledRegion',
        returnFields: ['Id', 'Name']
    });
    console.log('\n=== FilledRegions in view ===');
    console.log(JSON.stringify(regions.Data, null, 2));

    ws.close();
    process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });
