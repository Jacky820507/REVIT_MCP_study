/**
 * 分析停車格座標分佈與模型線路徑的相關性
 * 目標：理解蛇形排列邏輯
 */
import { readFileSync } from 'fs';

const data = JSON.parse(readFileSync('e:/RevitMCP/MCP-Server/scratch/parking_analysis.json', 'utf-8'));
const motos = data.all_motorcycle_locations;
const lines = data.motorcycle_lines.Members;

console.log('=== 模型線路徑 ===');
console.log('線段1:', `(${lines[0].Location.StartX}, ${lines[0].Location.StartY}) → (${lines[0].Location.EndX}, ${lines[0].Location.EndY})`);
console.log('線段2:', `(${lines[1].Location.StartX}, ${lines[1].Location.StartY}) → (${lines[1].Location.EndX}, ${lines[1].Location.EndY})`);
console.log('線段3:', `(${lines[2].Location.StartX}, ${lines[2].Location.StartY}) → (${lines[2].Location.EndX}, ${lines[2].Location.EndY})`);

// 路徑方向：線1 從左上往右下 → 線2 從右上往右下 → 線3 從右往左
// 整體看：先從上方往下掃，然後到下方往左走

console.log('\n=== X 座標分群 (欄) ===');
// 找出所有不重複的 X 值
const xValues = [...new Set(motos.map(m => m.x))].sort((a, b) => a - b);
console.log(`X 不重複值 (${xValues.length}):`, xValues);

// 以 tolerance 分群 (相近的 X 歸為同一欄)
const X_TOLERANCE = 1500; // mm
const columns = [];
const used = new Set();
for (const x of xValues) {
    if (used.has(x)) continue;
    const group = xValues.filter(v => Math.abs(v - x) <= X_TOLERANCE && !used.has(v));
    group.forEach(v => used.add(v));
    const avgX = group.reduce((s, v) => s + v, 0) / group.length;
    columns.push({ x: avgX, xValues: group });
}
console.log(`\n分成 ${columns.length} 欄:`);

// 對每欄的機車按 Y 排序
for (const col of columns) {
    const members = motos.filter(m => col.xValues.some(x => Math.abs(m.x - x) <= 500));
    members.sort((a, b) => b.y - a.y); // Y 由高到低 = 由上到下
    col.members = members;
    col.yRange = { max: members[0]?.y, min: members[members.length - 1]?.y };
    console.log(`  欄 X≈${Math.round(col.x)} | ${members.length} 個 | Y: ${col.yRange.max} ~ ${col.yRange.min}`);
}

console.log('\n=== Y 座標分群 (排) ===');
const yValues = [...new Set(motos.map(m => m.y))].sort((a, b) => b - a); // 由高到低
console.log(`Y 不重複值 (${yValues.length}):`, yValues.slice(0, 20), '...');

// Y 分群 (同排)
const Y_TOLERANCE = 1500;
const rows = [];
const usedY = new Set();
for (const y of yValues) {
    if (usedY.has(y)) continue;
    const group = yValues.filter(v => Math.abs(v - y) <= Y_TOLERANCE && !usedY.has(v));
    group.forEach(v => usedY.add(v));
    const avgY = group.reduce((s, v) => s + v, 0) / group.length;
    rows.push({ y: avgY, yValues: group });
}
console.log(`\n分成 ${rows.length} 排:`);

for (const row of rows) {
    const members = motos.filter(m => row.yValues.some(y => Math.abs(m.y - y) <= 500));
    members.sort((a, b) => a.x - b.x); // X 由小到大 = 由左到右
    row.members = members;
    row.xRange = { min: members[0]?.x, max: members[members.length - 1]?.x };
    console.log(`  排 Y≈${Math.round(row.y)} | ${members.length} 個 | X: ${row.xRange.min} ~ ${row.xRange.max}`);
}

// === 蛇形分析 ===
console.log('\n=== 蛇形排列分析 (由上到下，由左到右) ===');
console.log('欄數:', columns.length);
columns.sort((a, b) => a.x - b.x); // 由左到右

console.log('\n按欄排列 (由左到右):');
let totalIdx = 0;
for (let i = 0; i < columns.length; i++) {
    const col = columns[i];
    // 蛇形：奇數欄由上到下，偶數欄由下到上
    const isEvenCol = i % 2 === 1;
    if (isEvenCol) {
        col.members.sort((a, b) => a.y - b.y); // 由下到上→反轉
    } else {
        col.members.sort((a, b) => b.y - a.y); // 由上到下
    }
    
    console.log(`\n  欄${i+1} (X≈${Math.round(col.x)}) ${isEvenCol ? '↑由下到上' : '↓由上到下'} | ${col.members.length} 個`);
    for (const m of col.members.slice(0, 5)) {
        totalIdx++;
        console.log(`    #${totalIdx}: ID=${m.id} (${m.x}, ${m.y})`);
    }
    if (col.members.length > 5) {
        totalIdx += col.members.length - 5;
        console.log(`    ...共 ${col.members.length} 個`);
    }
}

// === 排分析（由上到下，蛇形左右） ===
console.log('\n\n=== 蛇形排列分析 (由上「排」到下，左右蛇行) ===');
rows.sort((a, b) => b.y - a.y); // 由上到下
let idx2 = 0;
for (let i = 0; i < rows.length; i++) {
    const row = rows[i];
    const isEvenRow = i % 2 === 1;
    if (isEvenRow) {
        row.members.sort((a, b) => b.x - a.x); // 右到左
    } else {
        row.members.sort((a, b) => a.x - b.x); // 左到右
    }
    
    console.log(`  排${i+1} (Y≈${Math.round(row.y)}) ${isEvenRow ? '←右到左' : '→左到右'} | ${row.members.length} 個`);
    for (const m of row.members.slice(0, 3)) {
        idx2++;
        console.log(`    #${idx2}: (${m.x}, ${m.y})`);
    }
    if (row.members.length > 3) {
        idx2 += row.members.length - 3;
        console.log(`    ...共 ${row.members.length} 個`);
    }
}
console.log(`\n機車總計: ${motos.length}`);
