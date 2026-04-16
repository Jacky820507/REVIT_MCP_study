const fs = require('fs');

// Path to Revit MCP client script
// Wait, we don't need a Node.js script. We can use the MCP tool: `modify_element_parameter`
// Or better yet, we can write a script that calls the MCP server internally, or just generate a list
// so Antigravity can call it. But calling 193 times via MCP tool might be too slow.
// Let's create a JS script that connects via WS or uses the MCP server if possible.
// Wait! We can use `node MCP-Server/scripts/xxxx.js` pattern as seen in GEMINI.md.
// Let's write a dedicated node script in E:/RevitMCP/scratch_csv/update_sheets.js
// that talks to the Revit MCP Server or Revit Add-in.

// Wait, the project has an MCP-Server that communicates with Revit via WS on port 8964.
// Let's write a Node.js script that connects to ws://127.0.0.1:8964 and sends update commands.
const WebSocket = require('ws');
const path = require('path');

const ws = new WebSocket('ws://127.0.0.1:8964');
const dataFile = path.join(__dirname, 'mismatch.json');
const data = JSON.parse(fs.readFileSync(dataFile, 'utf8'));
const updates = data.changed;

let currentIdx = 0;
let successCount = 0;
let failCount = 0;

ws.on('open', function open() {
    console.log(`Connected to Revit WebSocket. Starting batch update of ${updates.length} sheets...`);
    processNext();
});

function processNext() {
    if (currentIdx >= updates.length) {
        console.log(`\nBatch update finished! Success: ${successCount}, Failed: ${failCount}`);
        ws.close();
        return;
    }

    const item = updates[currentIdx];
    
    // Command payload for modifying parameter
    const payload = {
        command: "modify_element_parameter",
        args: {
            elementId: item.Id,
            parameterName: "圖紙號碼", // Sheet Number in Chinese Revit or "Sheet Number"
            value: item.TargetNumber
        }
    };

    // Note: Revit API parameter for Sheet Number might be "圖紙號碼" or "Sheet Number". 
    // If it fails, we will try the other. We'll send it now.
    process.stdout.write(`Updating [${item.Id}] ${item.RevitName} -> ${item.TargetNumber}... `);
    ws.send(JSON.stringify(payload));
}

ws.on('message', function incoming(message) {
    const response = JSON.parse(message);
    if (response.status === 'success') {
        process.stdout.write('OK\n');
        successCount++;
    } else {
        // Retry with English parameter name if Chinese failed
        if (response.message && response.message.includes('找不到參數')) {
             const item = updates[currentIdx];
             const retryPayload = {
                 command: "modify_element_parameter",
                 args: {
                     elementId: item.Id,
                     parameterName: "Sheet Number",
                     value: item.TargetNumber
                 }
             };
             process.stdout.write(`Retrying with 'Sheet Number'... `);
             
             // We need a temporary handler for the retry
             const retryHandler = (retryMsg) => {
                 ws.off('message', retryHandler);
                 const retryRes = JSON.parse(retryMsg);
                 if (retryRes.status === 'success') {
                     process.stdout.write('OK\n');
                     successCount++;
                 } else {
                     process.stdout.write(`FAILED: ${retryRes.message}\n`);
                     failCount++;
                 }
                 currentIdx++;
                 ws.on('message', incoming); // restore original
                 processNext();
             };
             ws.off('message', incoming);
             ws.on('message', retryHandler);
             ws.send(JSON.stringify(retryPayload));
             return; // Stop current handler
        } else {
            process.stdout.write(`FAILED: ${response.message}\n`);
            failCount++;
        }
    }
    
    currentIdx++;
    processNext();
});

ws.on('error', function error(err) {
    console.error('WebSocket Error:', err.message);
    process.exit(1);
});
