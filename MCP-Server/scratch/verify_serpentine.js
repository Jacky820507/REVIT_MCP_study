/**
 * 驗證蛇形排序：使用實際停車格資料
 */
import { readFileSync } from 'fs';

const data = JSON.parse(readFileSync('e:/RevitMCP/MCP-Server/scratch/parking_analysis.json', 'utf-8'));
const motos = data.all_motorcycle_locations.map(m => ({ ...m }));

// 複製排序函數 (與 number_parking.js 中的一致)
function sortParkingBays(bays, tolerance, mode = 'yx') {
    if (bays.length === 0) return bays;

    if (mode === 'xy') {
        bays.sort((a, b) => a.x - b.x);
        let currentGroupX = bays[0].x;
        let groupIndex = 0;
        for (const bay of bays) {
            if (Math.abs(bay.x - currentGroupX) > tolerance) {
                groupIndex++;
                currentGroupX = bay.x;
            }
            bay._group = groupIndex;
        }
        bays.sort((a, b) => {
            if (a._group !== b._group) return a._group - b._group;
            const isEvenGroup = a._group % 2 === 1;
            return isEvenGroup ? (a.y - b.y) : (b.y - a.y);
        });
    } else {
        bays.sort((a, b) => b.y - a.y);
        let currentGroupY = bays[0].y;
        let groupIndex = 0;
        for (const bay of bays) {
            if (Math.abs(bay.y - currentGroupY) > tolerance) {
                groupIndex++;
                currentGroupY = bay.y;
            }
            bay._group = groupIndex;
        }
        bays.sort((a, b) => {
            if (a._group !== b._group) return a._group - b._group;
            const isEvenGroup = a._group % 2 === 1;
            return isEvenGroup ? (b.x - a.x) : (a.x - b.x);
        });
    }
    for (const bay of bays) delete bay._group;
    return bays;
}

// === 測試 xy 模式 (欄蛇形，符合模型線路徑) ===
console.log('=== xy 模式 (欄蛇形：由左到右，每欄上下交替) ===\n');
sortParkingBays(motos, 1500, 'xy');

let prevCol = null;
let colCount = 0;
for (let i = 0; i < motos.length; i++) {
    const m = motos[i];
    // 檢測換欄
    if (i === 0 || Math.abs(m.x - motos[i-1].x) > 1500) {
        colCount++;
        const dir = colCount % 2 === 1 ? '↓上到下' : '↑下到上';
        console.log(`\n--- 欄${colCount} (X≈${Math.round(m.x)}) ${dir} ---`);
    }
    const num = 578 + i;
    if (i < 3 || (motos[i+1] && Math.abs(motos[i+1].x - m.x) > 1500) || i === motos.length - 1) {
        console.log(`  #${num}: (${m.x}, ${m.y})`);
    } else if (i === 3) {
        console.log(`  ...`);
    }
}
console.log(`\n總計: ${motos.length} 個, 編號 578~${578 + motos.length - 1}`);

// 驗證蛇形順序
console.log('\n=== 驗證蛇形方向 ===');
const motos2 = data.all_motorcycle_locations.map(m => ({ ...m }));
sortParkingBays(motos2, 1500, 'xy');
let currentX = -Infinity;
let colIdx = -1;
let cols = [];
for (const m of motos2) {
    if (Math.abs(m.x - currentX) > 1500) {
        cols.push([]);
        colIdx++;
        currentX = m.x;
    }
    cols[colIdx].push(m);
}

for (let c = 0; c < cols.length; c++) {
    const col = cols[c];
    const ys = col.map(m => m.y);
    const isDescending = ys.every((v, i) => i === 0 || v <= ys[i-1]);
    const isAscending = ys.every((v, i) => i === 0 || v >= ys[i-1]);
    const expected = c % 2 === 0 ? '↓降冪' : '↑升冪';
    const actual = isDescending ? '↓降冪' : isAscending ? '↑升冪' : '❌混合';
    const ok = (c % 2 === 0 && isDescending) || (c % 2 === 1 && isAscending);
    console.log(`  欄${c+1}: ${col.length}個, Y ${actual} ${ok ? '✅' : '❌'} (期望 ${expected})`);
}
