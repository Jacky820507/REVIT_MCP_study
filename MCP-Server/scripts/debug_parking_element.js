import WebSocket from 'ws';

const sendCmd = (ws, cmd, args) => new Promise(r => {
    const id = 'r_' + Date.now();
    const l = d => {
        const m = JSON.parse(d);
        if(m.RequestId === id) { ws.off('message', l); r(m); }
    };
    ws.on('message', l);
    ws.send(JSON.stringify({ CommandName: cmd, Parameters: args, RequestId: id }));
});

const ws = new WebSocket('ws://localhost:8964');
ws.on('open', async () => {
    console.log('--- element 5687765 info ---');
    const info = await sendCmd(ws, 'get_element_info', { elementId: 5687765 });
    console.log(JSON.stringify(info, null, 2));
    ws.close();
});
