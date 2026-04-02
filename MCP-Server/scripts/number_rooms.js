/**
 * 房間自動編號腳本 (Room Auto-Numbering)
 * 
 * 功能：在當前視圖中，將房間依「由上往下、由左往右」排序，
 *       根據樓層名稱自動產生前綴 (如 1F->F101, B1F->B101, R1F->R101)，
 *       並寫入房間的「編號 / Number」參數。
 * 
 * 用法：node scripts/number_rooms.js [--tolerance 3000] [--all] [--dry-run]
 * 
 *   --tolerance <mm>  Y 軸分群容差值（mm），預設 3000
 *   --all              對全專案所有樓層的房間進行一次性編碼
 *   --dry-run          僅模擬列印結果，不實際寫入 Revit
 */

import WebSocket from 'ws';

// ============================================================
// 設定
// ============================================================
const PORT = parseInt(process.env.REVIT_MCP_PORT || '8964', 10);

const args = process.argv.slice(2);
const DRY_RUN = args.includes('--dry-run');
const ALL_ROOMS = args.includes('--all');
const tolIdx = args.indexOf('--tolerance');
const TOLERANCE = tolIdx !== -1 ? parseFloat(args[tolIdx + 1]) : 3000; // mm

// ============================================================
// WebSocket 幫手
// ============================================================
function sendCommand(ws, name, params) {
    return new Promise((resolve, reject) => {
        const reqId = 'req_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        const cmd = { CommandName: name, Parameters: params, RequestId: reqId };

        const listener = (data) => {
            try {
                const msg = JSON.parse(data.toString());
                if (msg.RequestId === reqId) {
                    ws.off('message', listener);
                    if (msg.Success) {
                        resolve(msg.Data || { success: true });
                    } else {
                        resolve({ success: false, error: msg.Message || msg.Error || 'Unknown Error' });
                    }
                }
            } catch (e) { /* ignore parse errors from other messages */ }
        };

        ws.on('message', listener);
        ws.send(JSON.stringify(cmd));

        setTimeout(() => {
            ws.off('message', listener);
            resolve({ success: false, error: 'Timeout (30s)' });
        }, 30000);
    });
}

// ============================================================
// 前綴產生邏輯 (Regex)
// ============================================================
function getPrefix(name) {
    if (!name) return 'ROOM_';

    // 1. 地下層 (B1F, B2, B3...)
    let m = name.match(/B(\d+)/i);
    if (m) return `B${m[1]}`;

    // 2. 屋突層 (R1F, R2, RF...)
    m = name.match(/R(\d*)/i);
    if (m) return `R${m[1] || '1'}`;

    // 3. 地上層 (1F, 2F, 3F, F1, F2...)
    m = name.match(/(\d+)F/i) || name.match(/F(\d+)/i) || name.match(/(\d+)/);
    if (m) return `F${m[1]}`;

    return 'ROOM_';
}

// 補零函數 (確保兩位數，如 01, 02)
function padNumber(num) {
    return num < 10 ? `0${num}` : `${num}`;
}

// ============================================================
// 排序函數 (機械排序：由上至下 Y降冪, 由左至右 X升冪)
// ============================================================
function sortRooms(rooms, tolerance) {
    if (rooms.length === 0) return rooms;

    // 1. 依 Y 降冪粗排 (最上面的在前面)
    rooms.sort((a, b) => b.y - a.y);

    // 2. 分群：Y 座標落在容差內 → 同排
    let currentGroupY = rooms[0].y;
    let groupIndex = 0;
    for (const room of rooms) {
        if (Math.abs(room.y - currentGroupY) > tolerance) {
            groupIndex++;
            currentGroupY = room.y;
        }
        room._group = groupIndex;
    }

    // 3. 排序：先按群組排，同群組則依 X 升冪 (左到右)
    rooms.sort((a, b) => {
        if (a._group !== b._group) return a._group - b._group;
        return a.x - b.x;
    });

    // 清理臨時欄位
    for (const room of rooms) delete room._group;

    return rooms;
}

// ============================================================
// 解析座標
// ============================================================
function extractLocation(element) {
    if (element.LocationX != null && element.LocationY != null) {
        return { x: parseFloat(element.LocationX), y: parseFloat(element.LocationY) };
    }
    if (element.Location) {
        const loc = element.Location;
        if (loc.X != null && loc.Y != null) return { x: parseFloat(loc.X), y: parseFloat(loc.Y) };
        if (loc.x != null && loc.y != null) return { x: parseFloat(loc.x), y: parseFloat(loc.y) };
        if (typeof loc === 'string') {
            const m = loc.match(/[\(（]?\s*([-\d.]+)\s*[,，]\s*([-\d.]+)/);
            if (m) return { x: parseFloat(m[1]), y: parseFloat(m[2]) };
        }
    }
    if (element.BoundingBox) {
        const bb = element.BoundingBox;
        if (bb.Min && bb.Max) {
            return {
                x: (parseFloat(bb.Min.X || bb.Min.x || 0) + parseFloat(bb.Max.X || bb.Max.x || 0)) / 2,
                y: (parseFloat(bb.Min.Y || bb.Min.y || 0) + parseFloat(bb.Max.Y || bb.Max.y || 0)) / 2,
            };
        }
    }
    return null;
}

// ============================================================
// 前綴排序函數 (從底層到頂層：B3->B1->F1->F10->R1)
// ============================================================
function sortPrefixes(a, b) {
    const typeA = a[0];
    const typeB = b[0];
    const numA = parseInt(a.slice(1)) || 0;
    const numB = parseInt(b.slice(1)) || 0;

    const typeWeight = (t) => t === 'B' ? -1 : (t === 'F' ? 0 : (t === 'R' ? 1 : 2));
    
    if (typeWeight(typeA) !== typeWeight(typeB)) {
        return typeWeight(typeA) - typeWeight(typeB);
    }

    if (typeA === 'B') return numB - numA; // B3 (3), B1 (1) -> 1 - 3 = -2 (B3先)
    return numA - numB; // F/R 升冪 (F1, F2...)
}

// ============================================================
// 主流程
// ============================================================
async function main() {
    console.log('=== 房間自動編號 (機械排序) ===');
    console.log(`  順序: ⬆️⬇️ 由上往下，⬅️➡️ 由左往右`);
    console.log(`  容差: ${TOLERANCE} mm`);
    console.log(`  模式: ${DRY_RUN ? '🔍 模擬 (dry-run)' : '✍️  實際寫入'}\n`);

    const ws = new WebSocket(`ws://localhost:${PORT}`);

    ws.on('error', (err) => {
        console.error('❌ WebSocket 連線錯誤:', err.message);
        console.error('   請確認 Revit 已開啟且 MCP 外掛已啟用。');
        process.exit(1);
    });

    ws.on('open', async () => {
        console.log('✅ 已連線 Revit MCP Server');

        try {
            // ------ Step 1: 取得當前視圖 ------
            console.log('\n[Step 1] 取得當前視圖...');
            const viewDataRaw = await sendCommand(ws, 'get_active_view', {});
            const viewData = viewDataRaw.Data || viewDataRaw;
            
            if (!viewData || viewData.success === false) {
                console.error('❌ 無法取得當前視圖:', viewData?.error);
                ws.close(); return;
            }
            
            const viewId = viewData.ElementId || viewData.Id || viewData.id || viewData.viewId;
            const viewName = viewData.Name || viewData.name || '';
            const viewType = viewData.ViewType || viewData.viewType || '';
            const activeLevelName = viewData.LevelName || viewData.levelName || '';
            
            console.log(`   視圖: ${viewName} (ID: ${viewId})`);
            if (activeLevelName) console.log(`   樓層: ${activeLevelName}`);

            if (!ALL_ROOMS && viewType === 'DrawingSheet') {
                console.log('\n   ⚠️  偵測到您目前在「圖紙 (Sheet)」上。');
                console.log('      未加上 --all 參數時，腳本需在「平面視圖」中執行才能萃取範圍房間。');
                ws.close(); return;
            }

            // ------ Step 2: 查詢可用欄位 (尋找編號參數名稱) ------
            console.log('\n[Step 2] 查詢 Rooms 類別欄位...');
            const fieldsRaw = await sendCommand(ws, 'get_category_fields', { category: 'Rooms' });
            const fieldsData = fieldsRaw.Data || fieldsRaw || [];
            const fieldNames = fieldsData.InstanceFields || fieldsData.Fields || fieldsData.fields || fieldsData.parameters || (Array.isArray(fieldsData) ? fieldsData : []);
            
            let numberParamName = 'Number';
            if (fieldNames.some(f => (f?.Name || f?.name || f) === '編號')) {
                numberParamName = '編號';
            }
            console.log(`   使用編號欄位: [${numberParamName}]`);

            // ------ Step 3: 查詢視圖/專案中的房間 ------
            console.log(`\n[Step 3] 查詢${ALL_ROOMS ? '全專案所有' : '當前視圖中的'}房間...`);
            const queryArgs = {
                category: 'Rooms',
                maxCount: 9999,
                filters: [],
                returnFields: ['樓層', 'Level', '編號', 'Number'] 
            };
            if (!ALL_ROOMS) {
                queryArgs.viewId = viewId;
            }

            const queryResRaw = await sendCommand(ws, 'query_elements', queryArgs);
            const queryResult = queryResRaw.Data || queryResRaw;

            let elements = [];
            if (Array.isArray(queryResult)) elements = queryResult;
            else if (queryResult?.Elements || queryResult?.elements) elements = queryResult.Elements || queryResult.elements;

            console.log(`   共找到 ${elements.length} 個房間 (Room) 元素`);
            if (elements.length === 0) {
                console.log('   ⚠️  當前視圖沒有房間元素，腳本結束。');
                ws.close(); return;
            }

            if (elements.length > 0) {
                console.log('   📋 第一個房間範例資料:');
                console.log(`     名稱: ${elements[0].Name || elements[0].name}`);
                console.log(`     頂層 keys: ${Object.keys(elements[0]).join(', ')}`);
                console.log(`     參數 keys: ${elements[0].parameters ? Object.keys(elements[0].parameters).join(', ') : '沒有 parameters 物件'}`);
            }

            // ------ Step 4: 取得座標與前綴群組 ------
            console.log('\n[Step 4] 提取中心座標與產生前綴...');
            const prefixGroups = {};
            let noLocationCount = 0;

            for (const el of elements) {
                const id = el.ElementId || el.Id || el.id || el.elementId;
                const name = el.Name || el.name || '';
                
                // 決定前綴：優先使用參數，若無則使用視圖的 activeLevelName，最後才是 viewName
                let levelStr = activeLevelName || viewName;
                if (el.parameters && (el.parameters['樓層'] || el.parameters['Level'])) {
                    levelStr = el.parameters['樓層'] || el.parameters['Level'];
                } else if (el['樓層'] || el['Level']) {
                    levelStr = el['樓層'] || el['Level'];
                }
                const prefix = getPrefix(levelStr);

                // 建立群組
                if (!prefixGroups[prefix]) prefixGroups[prefix] = [];

                // 提取座標
                let loc = extractLocation(el);
                if (!loc) {
                    // 嘗試額外呼叫 C# 獲取座標
                    const info = await sendCommand(ws, 'get_element_location', { elementId: id });
                    const locData = info?.Data || info;
                    
                    let x = null, y = null;
                    if (locData?.Location?.Type === 'Point') {
                        x = locData.Location.X; y = locData.Location.Y;
                    } else if (locData?.BoundingBox?.Center) {
                        x = locData.BoundingBox.Center.X; y = locData.BoundingBox.Center.Y;
                    }

                    if (x !== null && y !== null) {
                        loc = { x, y };
                    }
                }
                
                // 放棄無座標的未放置房間 (Unplaced / Unenclosed)
                if ((el.parameters && el.parameters['面積'] === '未放置') || (el.parameters && el.parameters['面積'] === '未建立圍合')) {
                    noLocationCount++;
                    continue;
                }

                if (loc) {
                    prefixGroups[prefix].push({ id, name, prefix, x: loc.x, y: loc.y });
                } else {
                    noLocationCount++;
                }
            }

            if (noLocationCount > 0) {
                console.log(`   ⚠️  有 ${noLocationCount} 個房間未放置或無法取得座標，將被忽略。`);
            }

            // ------ Step 5 & 6: 排序與寫入 ------
            console.log('\n[Step 5 & 6] 排序與編號分配...');
            let totalSuccess = 0;
            let totalFail = 0;

            const sortedPrefixes = Object.keys(prefixGroups).sort(sortPrefixes);

            for (const prefix of sortedPrefixes) {
                const groupRooms = prefixGroups[prefix];
                if (groupRooms.length === 0) continue;

                console.log(`\n   🏠 前綴 [${prefix}] (共 ${groupRooms.length} 個房間):`);
                
                // 排序
                sortRooms(groupRooms, TOLERANCE);

                // 依序編號
                for (let i = 0; i < groupRooms.length; i++) {
                    const room = groupRooms[i];
                    const seqNum = padNumber(i + 1); // 01, 02...
                    const finalNumber = `${prefix}${seqNum}`;

                    console.log(`     ${i + 1}. [${finalNumber}]  <-  ID:${room.id} (${room.name}) `);

                    if (!DRY_RUN) {
                        const res = await sendCommand(ws, 'modify_element_parameter', {
                            elementId: room.id,
                            parameterName: numberParamName,
                            value: finalNumber,
                        });
                        
                        if (res && res.success !== false) {
                            totalSuccess++;
                        } else {
                            totalFail++;
                            console.error(`       ❌ 寫入失敗: ${res?.error || 'unknown'}`);
                        }
                    }
                }
            }

            if (!DRY_RUN) {
                console.log(`\n🎉 完成寫入！成功: ${totalSuccess} 個，失敗: ${totalFail} 個`);
            } else {
                console.log(`\n🔍 模擬結束，尚未寫入 Revit。若確認無誤請移除 --dry-run 參數。`);
            }

            ws.close();
        } catch (err) {
            console.error('❌ 執行發生錯誤:', err);
            ws.close();
        }
    });
}

main();
