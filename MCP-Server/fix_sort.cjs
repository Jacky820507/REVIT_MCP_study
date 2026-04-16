const WebSocket = require('ws');
const ws = new WebSocket('ws://localhost:8964');

const exec = (cmd, params) => new Promise((resolve, reject) => {
    const requestId = 'swp_' + Date.now() + Math.random();
    ws.send(JSON.stringify({ CommandName: cmd, Parameters: params, RequestId: requestId }));

    const listener = (data) => {
        const msg = JSON.parse(data.toString());
        if (msg.RequestId === requestId) {
            ws.removeListener('message', listener);
            if (msg.Error) reject(msg.Error);
            else resolve(msg.Data);
        }
    };
    ws.on('message', listener);
});

ws.on('open', async () => {
    try {
        console.log('Starting swap sequence...');
        // IDs: 7469768 (三), 7398253 (一), 7398259 (二)

        console.log('Moving (三) to TEMP...');
        await exec('modify_element_parameter', { elementId: 7469768, parameterName: 'Sheet Number', value: 'ARA-D0915_TEMP' });

        console.log('Moving (一) to D0913...');
        await exec('modify_element_parameter', { elementId: 7398253, parameterName: 'Sheet Number', value: 'ARA-D0913' });

        console.log('Moving (二) to D0914...');
        await exec('modify_element_parameter', { elementId: 7398259, parameterName: 'Sheet Number', value: 'ARA-D0914' });

        console.log('Moving (三) to D0915...');
        await exec('modify_element_parameter', { elementId: 7469768, parameterName: 'Sheet Number', value: 'ARA-D0915' });

        console.log('Done!');
    } catch (e) {
        console.error('Error during swap:', e);
    } finally {
        ws.close();
    }
});

ws.on('error', (err) => {
    console.error('Connection error:', err);
});
