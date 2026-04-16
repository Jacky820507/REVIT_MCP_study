const fs = require('fs');
const { execSync } = require('child_process');

async function run() {
    const data = JSON.parse(fs.readFileSync('e:\\RevitMCP\\tmp\\renumber_prep.json', 'utf8'));
    const tempUpdates = data.tempUpdates;
    
    console.log(`Starting Phase 1: ${tempUpdates.length} temp updates...`);

    const batchSize = 100;
    for (let i = 0; i < tempUpdates.length; i += batchSize) {
        const batch = tempUpdates.slice(i, i + batchSize);
        console.log(`Processing batch ${Math.floor(i/batchSize) + 1}/${Math.ceil(tempUpdates.length/batchSize)}...`);
        
        // 使用 node 腳本調用 MCP 工具，或在這裡構建請求再發送
        // 為了簡單且穩定，我們直接對每個元素分開調用 modify_element_parameter (或者如果能拼成 batch 命令好的話)
        // 但目前的 revit-mcp-2020 似乎沒有批量修改參數的工具，只有批量建立圖紙。
        // 所以我們先逐一調用（考慮到 WebSocket 並行優化，速度應該還可以）。
    }
}

// 修正：為了讓 AI 更有效率執行，我們改寫成直接讓 AI 調用批量命令。
// 如果沒有批量修改參數工具，我會手動連續調用。
