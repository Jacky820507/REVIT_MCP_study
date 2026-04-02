/**
 * 【詳圖項目參數同步工具 - 最終版】
 * ========================================
 */
import WebSocket from 'ws';

const TARGET_FAMILY = "AE-圖號詳圖編號標頭-3.5mm";
const ws = new WebSocket('ws://localhost:8964');

let symbols = [];
let sheets = [];
const pendingRequests = new Map();

function normalizeName(str) {
    if (!str) return "";
    return str
        .replace("詳圖", "")
        .replace(/[（\(\)）]/g, "")
        .replace(/\s+/g, "")
        .replace(/[０-９]/g, s => String.fromCharCode(s.charCodeAt(0) - 0xfee0))
        .replace(/[Ａ-Ｚ]/g, s => String.fromCharCode(s.charCodeAt(0) - 0xfee0))
        .replace(/[ａ-ｚ]/g, s => String.fromCharCode(s.charCodeAt(0) - 0xfee0))
        .replace(/[\-\_\.]/g, "")
        .trim();
}

function sendCommand(commandName, parameters) {
    const requestId = `req_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
    const payload = JSON.stringify({
        CommandName: commandName,
        Parameters: parameters,
        RequestId: requestId
    });
    
    return new Promise((resolve, reject) => {
        pendingRequests.set(requestId, { resolve, reject });
        ws.send(payload);
        setTimeout(() => {
            if (pendingRequests.has(requestId)) {
                pendingRequests.delete(requestId);
                reject(new Error(`Request ${requestId} timeout`));
            }
        }, 15000);
    });
}

ws.on('open', async () => {
    console.log(`=== 開始執行詳圖項目同步: ${TARGET_FAMILY} ===`);
    
    try {
        // 1. 獲取符號
        console.log("> 正在獲取族群符號...");
        const symRes = await sendCommand('list_family_symbols', { filter: TARGET_FAMILY });
        symbols = symRes.Data || [];
        console.log(`> 找到 ${symbols.length} 個類型符號`);

        // 2. 獲取圖紙
        console.log("> 正在獲取所有圖紙...");
        const sheetRes = await sendCommand('get_all_sheets', {});
        sheets = sheetRes.Data || [];
        console.log(`> 找到 ${sheets.length} 張圖紙`);

        // 3. 執行更新
        await processUpdate();
    } catch (err) {
        console.error("❌ 初始化失敗:", err.message);
        ws.close();
    }
});

ws.on('message', (data) => {
    const res = JSON.parse(data.toString());
    if (pendingRequests.has(res.RequestId)) {
        const { resolve } = pendingRequests.get(res.RequestId);
        pendingRequests.delete(res.RequestId);
        resolve(res);
    }
});

async function processUpdate() {
    console.log("\n--- 開始比對與更新 (順序執行) ---");
    let matchCount = 0;
    
    for (const symbol of symbols) {
        // 尋找對應的圖紙 (以類型名稱是否以該圖紙編號開頭來判斷，符合 Safeguard Mode 原則)
        let matchedSheet = null;
        for (const s of sheets) {
            const sheetNum = s.Number || s.圖紙號碼;
            if (sheetNum && symbol.Name.startsWith(sheetNum + "-")) {
                matchedSheet = s;
                break;
            }
        }

        // 當資產編號未匹配時，使用備用之模糊比對 (Legacy Fallback)
        if (!matchedSheet) {
            const nameParts = symbol.Name.split('-');
            const baseName = nameParts.length > 2 ? nameParts.slice(2).join('-') : symbol.Name;
            const normalizedBase = normalizeName(baseName);
            
            if (normalizedBase && normalizedBase.length >= 2) {
                matchedSheet = sheets.find(s => {
                    const normalizedSheet = normalizeName(s.Name || s.圖紙名稱);
                    return normalizedSheet === normalizedBase || 
                           normalizedSheet.includes(normalizedBase) || 
                           normalizedBase.includes(normalizedSheet);
                });
            }
        }

        if (matchedSheet) {
            matchCount++;
            const sheetNumber = matchedSheet.Number || matchedSheet.圖紙號碼;
            const sheetName = matchedSheet.Name || matchedSheet.圖紙名稱;

            // 確保有備註敘述 (DetailName)
            // 先嘗試從 Revit 的「詳圖名稱」參數取得
            let remark = symbol.DetailName;
            if (!remark) {
                 // Fallback 從原名稱提取
                 // 如果原名稱已經是 {SheetNumber}-{SheetName}-{Remark} 格式，則取第三段
                 const nameParts = symbol.Name.split('-');
                 if (nameParts.length >= 4) { // e.g. ARB - D0901 - 圖紙名稱 - 備註
                     // Find the part after the sheetName
                     const prefix = `${sheetNumber}-${sheetName}-`;
                     if (symbol.Name.startsWith(prefix)) {
                         remark = symbol.Name.substring(prefix.length);
                     } else {
                         remark = nameParts.slice(nameParts.length - 1).join('-');
                     }
                 } else {
                     remark = nameParts[nameParts.length - 1]; // 取最後一段作為備註
                 }
            }

            // 新類型名稱 = {圖紙編號}-{原始圖紙名稱}-{備註敘述}
            const newTypeName = `${sheetNumber}-${sheetName}-${remark}`;
            
            console.log(`[${matchCount}] 📍 準備更新: [${symbol.Name}] -> [${newTypeName}]`);
            
            try {
                // 如果目前名稱不同，則重新命名
                if (symbol.Name !== newTypeName) {
                    await sendCommand('rename_element', {
                        elementId: symbol.Id,
                        newName: newTypeName
                    });
                }
                
                // 修改參數
                await sendCommand('modify_element_parameter', {
                    elementId: symbol.Id,
                    parameterName: "詳圖圖號",
                    value: sheetNumber
                });

                await sendCommand('modify_element_parameter', {
                    elementId: symbol.Id,
                    parameterName: "圖說名稱",
                    value: sheetName
                });
                
                console.log(`   ✅ 成功: ${newTypeName}`);
                // 稍微延遲避免過快
                await new Promise(r => setTimeout(r, 100));
            } catch (err) {
                console.error(`   ❌ 失敗: ${err.message}`);
            }
        }
    }

    console.log(`\n--- 全部完成，共處理 ${matchCount} 個項目 ---`);
    ws.close();
}

ws.on('error', (e) => console.error('❌ Socket Error:', e.message));
ws.on('close', () => process.exit(0));
