const fs = require('fs');
const path = require('path');

const dataPath = 'C:\\Users\\09044\\.gemini\\antigravity\\brain\\0eead68f-72f5-4564-a119-cc5c6d0c24c1\\.system_generated\\steps\\103\\output.txt';
const sheets = JSON.parse(fs.readFileSync(dataPath, 'utf8'));

// 此時 sheets 已經是由 auto_renumber_sheets 處理過後的順序
const startNumber = 90001;
const prefix = "TEST-D0";

const finalUpdates = sheets.map((sheet, index) => {
    const numStr = (startNumber + index).toString();
    const newNum = prefix + numStr;
    return {
        id: sheet.Id,
        newNum: newNum
    };
});

fs.writeFileSync('e:\\RevitMCP\\tmp\\final_renumber_list.json', JSON.stringify(finalUpdates, null, 2));
console.log(`Generated ${finalUpdates.length} final updates.`);
