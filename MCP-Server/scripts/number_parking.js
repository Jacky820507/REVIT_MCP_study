/**
 * 停車格自動編號腳本 (Parking Bay Auto-Numbering)
 * 
 * 功能：在當前視圖中，將停車格依「從左到右、從上到下」排序，
 *       分三類（汽車、機車、大客車）各自從 1 開始編號，
 *       寫入例證參數「備註」。
 * 
 * 用法：node scripts/number_parking.js [--tolerance 500] [--order yx|xy] [--dry-run]
 * 
 *   --tolerance <mm>  座標分群容差值（mm），預設 500
 *   --order <mode>    編號順序：
 *                     yx - 由上到下，由左至右 (預設)
 *                     xy - 由左至右，由上到下
 *   --only <key>      僅針對單一類別編號 (car, motorcycle, bus)
 *   --dry-run          僅模擬列印結果，不實際寫入 Revit
 */

import WebSocket from 'ws';

// ============================================================
// 設定
// ============================================================
const PORT = parseInt(process.env.REVIT_MCP_PORT || '8964', 10);

// 解析 CLI 參數
const args = process.argv.slice(2);
const DRY_RUN = args.includes('--dry-run');
const tolIdx = args.indexOf('--tolerance');
const TOLERANCE = tolIdx !== -1 ? parseFloat(args[tolIdx + 1]) : 1500; // mm (更通用的停車格間距)

const orderIdx = args.indexOf('--order');
const SORT_ORDER = orderIdx !== -1 ? args[orderIdx + 1] : 'yx'; // 'yx' or 'xy'

const onlyIdx = args.indexOf('--only');
const ONLY_CATEGORY = onlyIdx !== -1 ? args[onlyIdx + 1] : null; 

const IS_LINEAR = args.includes('--linear'); // 停用蛇形，使用純線性排列

// 起始編號
const startIdx = args.indexOf('--start');
const GENERIC_START = startIdx !== -1 ? parseInt(args[startIdx + 1]) : 1;

const carStartIdx = args.indexOf('--car-start');
const CAR_START = carStartIdx !== -1 ? parseInt(args[carStartIdx + 1]) : GENERIC_START;
const motoStartIdx = args.indexOf('--motorcycle-start');
const MOTORCYCLE_START = motoStartIdx !== -1 ? parseInt(args[motoStartIdx + 1]) : GENERIC_START;
const busStartIdx = args.indexOf('--bus-start');
const BUS_START = busStartIdx !== -1 ? parseInt(args[busStartIdx + 1]) : GENERIC_START;

const CATEGORY_KEYWORDS = [
    { key: 'motorcycle', label: '機車', keyword: '機車' },
    { key: 'bus',        label: '大客車', keyword: '大客車' },
    { key: 'car',        label: '汽車', keyword: '汽車' },
];

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
// 分類函數
// ============================================================
function classifyParking(typeName, familyName, name) {
    const combined = (typeName || '') + (familyName || '') + (name || '');
    // 優先比對「大客車」（避免被「車」吃掉）
    for (const cat of CATEGORY_KEYWORDS) {
        if (combined.includes(cat.keyword)) return cat.key;
    }
    return 'unknown';
}

/**
 * 排序函數：支援蛇形（順時鐘）排列
 * 
 * 蛇形排列邏輯：
 *   yx 模式（由上到下為主）：
 *     第1排 →左到右，第2排 ←右到左，第3排 →左到右...
 *   xy 模式（由左到右為主）：
 *     第1欄 ↓上到下，第2欄 ↑下到上，第3欄 ↓上到下...
 * 
 * @param {Array} bays 停車格列表 (需含 x, y)
 * @param {number} tolerance 容差 (mm)，同排/同欄的判定距離
 * @param {string} mode 'yx' 或 'xy'
 */
function sortParkingBays(bays, tolerance, mode = 'yx') {
    if (bays.length === 0) return bays;

    if (mode === 'xy') {
        // === X 優先：欄蛇形 (左→右，每欄上下交替) ===
        // 1. 依 X 升冪粗排
        bays.sort((a, b) => a.x - b.x);

        // 2. 分群：X 座標落在容差內 → 同欄
        let currentGroupX = bays[0].x;
        let groupIndex = 0;
        for (const bay of bays) {
            if (Math.abs(bay.x - currentGroupX) > tolerance) {
                groupIndex++;
                currentGroupX = bay.x;
            }
            bay._group = groupIndex;
        }

        // 3. 蛇形排序：奇數欄↓(Y降冪)，偶數欄↑(Y升冪)
        bays.sort((a, b) => {
            if (a._group !== b._group) return a._group - b._group;
            if (IS_LINEAR) return b.y - a.y; // 永遠由上至下 (降冪)
            const isEvenGroup = a._group % 2 === 1;
            return isEvenGroup ? (a.y - b.y) : (b.y - a.y);
        });
    } else {
        // === Y 優先（預設）：排蛇形 (上→下，每排左右交替) ===
        // 1. 依 Y 降冪粗排 (最上面的在前)
        bays.sort((a, b) => b.y - a.y);

        // 2. 分群：Y 座標落在容差內 → 同排
        let currentGroupY = bays[0].y;
        let groupIndex = 0;
        for (const bay of bays) {
            if (Math.abs(bay.y - currentGroupY) > tolerance) {
                groupIndex++;
                currentGroupY = bay.y;
            }
            bay._group = groupIndex;
        }

        // 3. 蛇形排序：奇數排→(X升冪)，偶數排←(X降冪)
        bays.sort((a, b) => {
            if (a._group !== b._group) return a._group - b._group;
            if (IS_LINEAR) return a.x - b.x; // 永遠由左至右 (升冪)
            const isEvenGroup = a._group % 2 === 1;
            return isEvenGroup ? (b.x - a.x) : (a.x - b.x);
        });
    }

    // 清理臨時欄位
    for (const bay of bays) delete bay._group;

    return bays;
}

// ============================================================
// 解析座標 — 嘗試從元素資料中提取 X, Y
// ============================================================
function extractLocation(element) {
    // 嘗試多種常見的座標欄位結構
    // 1. 直接的 LocationX / LocationY 欄位
    if (element.LocationX != null && element.LocationY != null) {
        return { x: parseFloat(element.LocationX), y: parseFloat(element.LocationY) };
    }
    // 2. Location 物件
    if (element.Location) {
        const loc = element.Location;
        if (loc.X != null && loc.Y != null) {
            return { x: parseFloat(loc.X), y: parseFloat(loc.Y) };
        }
        if (loc.x != null && loc.y != null) {
            return { x: parseFloat(loc.x), y: parseFloat(loc.y) };
        }
        // 字串格式 "(x, y, z)"
        if (typeof loc === 'string') {
            const m = loc.match(/[\(（]?\s*([-\d.]+)\s*[,，]\s*([-\d.]+)/);
            if (m) return { x: parseFloat(m[1]), y: parseFloat(m[2]) };
        }
    }
    // 3. BoundingBox 中點
    if (element.BoundingBox) {
        const bb = element.BoundingBox;
        if (bb.Min && bb.Max) {
            return {
                x: (parseFloat(bb.Min.X || bb.Min.x || 0) + parseFloat(bb.Max.X || bb.Max.x || 0)) / 2,
                y: (parseFloat(bb.Min.Y || bb.Min.y || 0) + parseFloat(bb.Max.Y || bb.Max.y || 0)) / 2,
            };
        }
    }
    // 4. 檢查 returnFields 回傳的參數值
    if (element.parameters) {
        for (const [key, val] of Object.entries(element.parameters)) {
            if (typeof val === 'string' && val.match(/[\(（]?\s*[-\d.]+\s*[,，]\s*[-\d.]+/)) {
                const m = val.match(/[\(（]?\s*([-\d.]+)\s*[,，]\s*([-\d.]+)/);
                if (m) return { x: parseFloat(m[1]), y: parseFloat(m[2]) };
            }
        }
    }
    return null;
}

// ============================================================
// 主流程
// ============================================================
async function main() {
    console.log('=== 停車格自動編號 ===');
    console.log(`  順序: ${SORT_ORDER === 'xy' ? '⬅️➡️ 由左至右，⬆️⬇️ 由上至下' : '⬆️⬇️ 由上至下，⬅️➡️ 由左至右'}`);
    if (ONLY_CATEGORY) console.log(`  僅編號類別: ${ONLY_CATEGORY}`);
    console.log(`  容差: ${TOLERANCE} mm`);
    console.log(`  模式: ${DRY_RUN ? '🔍 模擬 (dry-run)' : '✍️  實際寫入'}`);
    console.log('');

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
            // 處理 PascalCase Data 欄位
            const viewData = viewDataRaw.Data || viewDataRaw;
            
            if (!viewData || viewData.success === false) {
                console.error('❌ 無法取得當前視圖:', viewData?.error);
                ws.close(); return;
            }
            
            // 重要：修正 ElementId 抓取
            const viewId = viewData.ElementId || viewData.Id || viewData.id || viewData.viewId;
            const viewName = viewData.Name || viewData.name || '(未知)';
            const viewType = viewData.ViewType || viewData.viewType || '';
            
            console.log(`   視圖: ${viewName} (ID: ${viewId})`);
            console.log(`   類型: ${viewType}`);

            if (viewType === 'DrawingSheet') {
                console.log('\n   ⚠️  偵測到您目前在「圖紙 (Sheet)」上。');
                console.log('      腳本需在「平面視圖」中執行才能依座標排序。');
                console.log('      💡 請在左側專案瀏覽器「按兩下」進入平面視圖，或將該視圖「啟用」後再執行。');
                ws.close(); return;
            }

            // ------ Step 2: 探索 Schema ------
            console.log('\n[Step 2] 探索視圖中的類別...');
            const schemaRaw = await sendCommand(ws, 'get_active_schema', { viewId });
            const schema = schemaRaw.Data || schemaRaw;

            if (schema) {
                // 列出所有類別，尋找停車相關的
                const categories = schema.Categories || schema.categories || (Array.isArray(schema) ? schema : []);
                const parkingCats = categories.filter(c => {
                    const name = (c.Name || c.name || c.Category || '').toLowerCase();
                    return name.includes('parking') || name.includes('停車');
                });
                if (parkingCats.length > 0) {
                    console.log('   找到停車類別:', parkingCats.map(c => `${c.Name || c.name} (${c.Count || c.count})`).join(', '));
                } else {
                    console.log('   ⚠️  未直接找到 Parking 類別，將嘗試使用 "Parking" 查詢...');
                }
            }

            // ------ Step 3: 取得欄位名稱 ------
            console.log('\n[Step 3] 取得 Parking 類別欄位...');
            const fieldsRaw = await sendCommand(ws, 'get_category_fields', { category: 'Parking' });
            const fields = fieldsRaw.Data || fieldsRaw;

            if (fields && !fields.error) {
                const fieldNames = fields.Fields || fields.fields || fields.parameters || (Array.isArray(fields) ? fields : []);
                console.log(`   欄位數量: ${fieldNames.length}`);
                // 確認「備註」欄位存在
                const commentField = fieldNames.find(f => {
                    const n = typeof f === 'string' ? f : (f.Name || f.name || '');
                    return n === '備註' || n === 'Comments';
                });
                if (commentField) {
                    console.log('   ✅ 確認「備註」欄位存在');
                } else {
                    console.log('   ⚠️  未找到「備註」欄位，將嘗試直接寫入...');
                }
            }

            // ------ Step 4: 查詢停車格元素 ------
            console.log('\n[Step 4] 查詢當前視圖中的停車格...');
            const queryResRaw = await sendCommand(ws, 'query_elements', {
                category: 'Parking',
                viewId: viewId,
                maxCount: 2000,
            });
            const queryResult = queryResRaw.Data || queryResRaw;

            let elements = [];
            if (Array.isArray(queryResult)) {
                elements = queryResult;
            } else if (queryResult?.Elements || queryResult?.elements) {
                elements = queryResult.Elements || queryResult.elements;
            } else if (queryResult?.success === false) {
                console.error('❌ 查詢失敗:', queryResult.error);
                ws.close(); return;
            }

            console.log(`   共找到 ${elements.length} 個停車格元素`);
            if (elements.length === 0) {
                console.log('   ⚠️  當前視圖沒有停車格，請切換到包含停車格的視圖後重試。');
                ws.close(); return;
            }

            // 印出第一個元素結構供 debug
            console.log('   📋 範例元素結構:', JSON.stringify(elements[0], null, 2).substring(0, 500));

            // ------ Step 5: 分類與座標提取 ------
            console.log('\n[Step 5] 分類與座標提取...');
            const groups = { car: [], motorcycle: [], bus: [], unknown: [] };

            let noLocationCount = 0;
            for (const el of elements) {
                const id = el.ElementId || el.Id || el.id || el.elementId;
                const typeName = el.TypeName || el.typeName || el.Type || el.type || '';
                const familyName = el.FamilyName || el.familyName || el.Family || el.family || '';
                const name = el.Name || el.name || '';
                const category = classifyParking(typeName, familyName, name);

                // 提取座標
                const loc = extractLocation(el);
                if (!loc) {
                    // 如果 query_elements 沒有座標，嘗試呼叫新寫的 get_element_location
                    const info = await sendCommand(ws, 'get_element_location', { elementId: id });
                    const locData = info?.Data || info;
                    
                    let x = null, y = null;

                    if (locData?.Location?.Type === 'Point') {
                        x = locData.Location.X;
                        y = locData.Location.Y;
                    } else if (locData?.BoundingBox?.Center) {
                        x = locData.BoundingBox.Center.X;
                        y = locData.BoundingBox.Center.Y;
                    }

                    if (x !== null && y !== null) {
                        groups[category].push({ id, typeName, familyName, name, x: x, y: y });
                    } else {
                        noLocationCount++;
                        console.warn(`   ⚠️  ID ${id} (${typeName}) 無法取得座標 (Location & BoundingBox 為空)`);
                    }
                } else {
                    groups[category].push({ id, typeName, familyName, name, x: loc.x, y: loc.y });
                }
            }

            if (noLocationCount > 0) {
                console.log(`   ⚠️  ${noLocationCount} 個元素無法取得座標，已跳過`);
            }

            // 統計
            console.log(`\n   📊 分類結果:`);
            console.log(`      汽車: ${groups.car.length} 個`);
            console.log(`      機車: ${groups.motorcycle.length} 個`);
            console.log(`      大客車: ${groups.bus.length} 個`);
            if (groups.unknown.length > 0) {
                console.log(`      ⚠️ 未分類: ${groups.unknown.length} 個 (已跳過)`);
                groups.unknown.forEach(u => console.log(`         - ID ${u.id}: ${u.name || u.familyName} / ${u.typeName}`));
            }

            // ------ Step 6: 排序 ------
            console.log(`\n[Step 6] 排序 (${SORT_ORDER === 'xy' ? '左到右、上到下' : '上到下、左到右'})...`);
            sortParkingBays(groups.car, TOLERANCE, SORT_ORDER);
            sortParkingBays(groups.motorcycle, TOLERANCE, SORT_ORDER);
            sortParkingBays(groups.bus, TOLERANCE, SORT_ORDER);

            // 印出排序預覽
            for (const [key, label] of [['car','汽車'], ['motorcycle','機車'], ['bus','大客車']]) {
                if (groups[key].length === 0) continue;
                if (ONLY_CATEGORY && ONLY_CATEGORY !== key) continue; // 預覽也過濾
                console.log(`\n   ${label} 排序預覽 (前 10 個):`);
                groups[key].slice(0, 10).forEach((b, i) => {
                    const groupInfo = `群組:${b._group}`;
                    console.log(`     ${i+1}. ID:${b.id}  ${groupInfo}  X:${b.x.toFixed(0)}  Y:${b.y.toFixed(0)}`);
                });
                const groupCount = new Set(groups[key].map(b => b._group)).size;
                console.log(`     共 ${groupCount} ${SORT_ORDER === 'xy' ? '欄' : '排'}, ${groups[key].length} 個`);
            }

            // ------ Step 7: 寫入「備註」 ------
            if (DRY_RUN) {
                console.log('\n[Step 7] 🔍 模擬模式 — 不寫入 Revit');
                for (const [key, label, start] of [['car','汽車', CAR_START], ['motorcycle','機車', MOTORCYCLE_START], ['bus','大客車', BUS_START]]) {
                    if (groups[key].length === 0) continue;
                    if (ONLY_CATEGORY && ONLY_CATEGORY !== key) {
                        console.log(`\n   ⏩ 跳過 ${label} (已指定僅編號 ${ONLY_CATEGORY})`);
                        continue;
                    }
                    console.log(`\n   ${label} (共 ${groups[key].length} 個，自 ${start} 開始):`);
                    groups[key].forEach((b, i) => {
                        console.log(`     備註="${start + i}"  ← ID:${b.id} (${b.name || b.typeName})`);
                    });
                }
            } else {
                console.log('\n[Step 7] ✍️  寫入「備註」參數...');
                let totalSuccess = 0;
                let totalFail = 0;

                for (const [key, label, start] of [['car','汽車', CAR_START], ['motorcycle','機車', MOTORCYCLE_START], ['bus','大客車', BUS_START]]) {
                    if (groups[key].length === 0) continue;
                    if (ONLY_CATEGORY && ONLY_CATEGORY !== key) {
                        console.log(`\n   ⏩ 跳過 ${label} (已指定僅編號 ${ONLY_CATEGORY})`);
                        continue;
                    }
                    console.log(`\n   寫入 ${label} (共 ${groups[key].length} 個，自 ${start} 開始)...`);

                    for (let i = 0; i < groups[key].length; i++) {
                        const bay = groups[key][i];
                        const number = String(start + i);

                        const res = await sendCommand(ws, 'modify_element_parameter', {
                            elementId: bay.id,
                            parameterName: '備註',
                            value: number,
                        });

                        if (res && res.success !== false) {
                            totalSuccess++;
                            // 每 50 個印一次進度
                            if ((i + 1) % 50 === 0 || i === groups[key].length - 1) {
                                console.log(`     進度 ${i + 1}/${groups[key].length} (最後編號: ${number})`);
                            }
                        } else {
                            totalFail++;
                            console.error(`     ❌ ID:${bay.id} 寫入失敗: ${res?.error || 'unknown'}`);
                        }
                    }
                }

                console.log(`\n🎉 完成！成功寫入 ${totalSuccess} 個，失敗 ${totalFail} 個`);
            }

            ws.close();
        } catch (err) {
            console.error('❌ 執行錯誤:', err);
            ws.close();
        }
    });
}

main();
