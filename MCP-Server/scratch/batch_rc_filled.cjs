const WebSocket = require('ws');

/**
 * 智慧更新版批量腳本：自動偵測變更，跳過未改動的視圖
 */
async function runBatch() {
    const ws = new WebSocket('ws://localhost:8964');

    const sendCommand = (method, params) => {
        return new Promise((resolve, reject) => {
            const id = String(Date.now());
            const request = { method, params, id };
            console.log(`  📤 發送指令: ${method} (id: ${id})`);
            ws.send(JSON.stringify(request));

            const timeout = setTimeout(() => {
                ws.removeListener('message', listener);
                reject(new Error(`指令 ${method} 逾時 (120s)`));
            }, 120000);

            const listener = (data) => {
                const response = JSON.parse(data);
                const respId = response.RequestId || response.requestId || response.id;
                if (String(respId) === id) {
                    clearTimeout(timeout);
                    ws.removeListener('message', listener);
                    if (response.Success === false) {
                        reject(new Error(response.Error || '未知錯誤'));
                    } else {
                        resolve(response.Data);
                    }
                }
            };
            ws.on('message', listener);
        });
    };

    ws.on('open', async () => {
        console.log('✅ 已連接至 Revit MCP Server');

        try {
            const targetSheetNumbers = ['ARA-D04002', 'ARA-D04003'];
            console.log(`🚀 智慧更新模式 — 圖紙: ${targetSheetNumbers.join(', ')}`);
            console.log('   (未變更的視圖將自動跳過)\n');

            const result = await sendCommand('batch_create_rc_filled_region', {
                sheetNumbers: targetSheetNumbers,
                filledRegionTypeName: '深灰色'
            });

            // 顯示每個視圖的狀態
            console.log('📊 視圖處理報告:');
            console.log('─'.repeat(60));
            if (result.Results && Array.isArray(result.Results)) {
                result.Results.forEach(r => {
                    const icon = r.Status === 'unchanged' ? '⏭️' : (r.Status === 'updated' ? '🔄' : '✨');
                    const detail = r.Status === 'unchanged'
                        ? '無變更，跳過'
                        : `刪除 ${r.DeletedCount} → 建立 ${r.CreatedCount}`;
                    console.log(` ${icon} [${r.ViewName}]: ${detail}`);
                });
            }
            console.log('─'.repeat(60));
            console.log(`\n🎉 ${result.Message}`);
            console.log(`   建立: ${result.TotalCreated} | 刪除: ${result.TotalDeleted} | 跳過: ${result.TotalSkipped} 個視圖`);

        } catch (err) {
            console.error('❌ 發生錯誤:', err.message || err);
        } finally {
            ws.close();
        }
    });

    ws.on('error', (err) => {
        console.error('❌ WebSocket 錯誤:', err.message);
    });
}

runBatch();
