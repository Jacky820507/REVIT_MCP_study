const fs = require('fs');
const path = require('path');

const dataPath = 'C:\\Users\\09044\\.gemini\\antigravity\\brain\\0eead68f-72f5-4564-a119-cc5c6d0c24c1\\.system_generated\\steps\\16\\output.txt';
const sheets = JSON.parse(fs.readFileSync(dataPath, 'utf8'));

// 按照目前的 Number 排序以維持既有邏輯順序
sheets.sort((a, b) => {
    return a.Number.localeCompare(b.Number, undefined, { numeric: true, sensitivity: 'base' });
});

const startNumber = 90001;
const prefix = "TEST-D0";

const updates = sheets.map((sheet, index) => {
    const newNum = prefix + (startNumber + index).toString();
    return {
        id: sheet.Id,
        oldNum: sheet.Number,
        newNum: newNum
    };
});

// 分批次 (每批 50 個) 以避免 WebSocket 過載
const batchSize = 50;
const batches = [];
for (let i = 0; i < updates.length; i += batchSize) {
    batches.push(updates.slice(i, i + batchSize));
}

// 輸出臨時編號指令與正式編號指令
const script = {
    tempUpdates: updates.map(u => ({ id: u.id, tempNum: "TEMP_" + u.oldNum })),
    finalUpdates: updates.map(u => ({ id: u.id, finalNum: u.newNum }))
};

fs.writeFileSync('e:\\RevitMCP\\tmp\\renumber_prep.json', JSON.stringify(script, null, 2));
console.log(`Prepared ${updates.length} sheet updates.`);
