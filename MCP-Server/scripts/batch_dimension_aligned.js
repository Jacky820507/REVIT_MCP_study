/**
 * 批量房間尺寸標註 - 分組對齊版
 * 同排/同列的房間，標註線會自動對齊
 * 
 * 演算法：
 * 1. 收集所有房間資料 (中心點 + 邊界框)
 * 2. 依 Y 座標分組 (X軸標註)，依 X 座標分組 (Y軸標註)
 * 3. 同組房間使用相同的標註線位置
 */

import WebSocket from 'ws';

const ws = new WebSocket('ws://localhost:8964');

const GROUP_THRESHOLD = 2000; // mm，中心點差異在此範圍內視為同一排/同一列

let phase = 'GET_VIEW';
let activeViewId = null;
let allRooms = []; // { Name, ElementId }
let roomDataList = []; // { Name, ElementId, CenterX, CenterY, BBox: {MinX,MaxX,MinY,MaxY} }
let roomInfoIndex = 0;

// 標註佇列
let dimQueue = []; // { roomId, axis, offset }
let dimIndex = 0;
let stats = { xSuccess: 0, ySuccess: 0, xFailed: 0, yFailed: 0 };

ws.on('open', function () {
    console.log('=== 批量標註 (分組對齊版) ===\n');
    ws.send(JSON.stringify({
        CommandName: 'get_active_view',
        Parameters: {},
        RequestId: 'view_' + Date.now()
    }));
});

ws.on('message', function (data) {
    const response = JSON.parse(data.toString());

    switch (phase) {
        case 'GET_VIEW':
            handleGetView(response);
            break;
        case 'GET_ROOMS':
            handleGetRooms(response);
            break;
        case 'GET_ROOM_INFO':
            handleGetRoomInfo(response);
            break;
        case 'CREATE_DIM':
            handleCreateDim(response);
            break;
    }
});

function handleGetView(response) {
    if (!response.Success || !response.Data) { console.error('❌ 無法取得視圖'); ws.close(); return; }

    activeViewId = response.Data.ViewId || response.Data.ElementId || response.Data.Id;
    const viewName = response.Data.Name;
    const level = response.Data.LevelName || response.Data.Level;

    console.log(`📍 視圖: ${viewName} (ID: ${activeViewId})`);
    console.log(`   樓層: ${level}\n`);

    phase = 'GET_ROOMS';
    ws.send(JSON.stringify({
        CommandName: 'get_rooms_by_level',
        Parameters: { level: level },
        RequestId: 'rooms_' + Date.now()
    }));
}

function handleGetRooms(response) {
    if (!response.Success || !response.Data) { console.error('❌ 無法取得房間'); ws.close(); return; }

    allRooms = Array.isArray(response.Data) ? response.Data : (response.Data.Rooms || []);
    console.log(`✅ 找到 ${allRooms.length} 個房間`);
    console.log('\n--- Phase 1: 收集房間資料 ---\n');

    phase = 'GET_ROOM_INFO';
    roomInfoIndex = 0;
    fetchNextRoomInfo();
}

function fetchNextRoomInfo() {
    if (roomInfoIndex >= allRooms.length) {
        // 所有房間資料收集完畢，進入分組階段
        console.log(`\n✅ 資料收集完成 (${roomDataList.length} 個房間)\n`);
        buildAlignedDimQueue();
        return;
    }

    const room = allRooms[roomInfoIndex];
    ws.send(JSON.stringify({
        CommandName: 'get_room_info',
        Parameters: { roomId: room.ElementId },
        RequestId: 'info_' + Date.now()
    }));
}

function handleGetRoomInfo(response) {
    const room = allRooms[roomInfoIndex];

    if (response.Success && response.Data) {
        const d = response.Data;
        const bbox = d.BoundingBox;

        if (bbox && d.CenterX !== undefined && d.CenterY !== undefined) {
            roomDataList.push({
                Name: d.Name || room.Name,
                ElementId: room.ElementId,
                CenterX: d.CenterX,
                CenterY: d.CenterY,
                MinX: bbox.MinX,
                MaxX: bbox.MaxX,
                MinY: bbox.MinY,
                MaxY: bbox.MaxY
            });
            console.log(`  [${roomInfoIndex + 1}/${allRooms.length}] ${d.Name || room.Name} ✅`);
        } else {
            console.log(`  [${roomInfoIndex + 1}/${allRooms.length}] ${room.Name} ⚠️ 無邊界框`);
        }
    }

    roomInfoIndex++;
    setTimeout(() => fetchNextRoomInfo(), 100);
}

// ====== 分組 + 對齊邏輯 ======

function buildAlignedDimQueue() {
    console.log('--- Phase 2: 分組對齊計算 ---\n');

    // X軸標註分組：按 CenterY 分組 (同一排)
    const xGroups = groupBy(roomDataList, 'CenterY', GROUP_THRESHOLD);
    console.log(`X軸分組: ${xGroups.length} 組`);
    xGroups.forEach((group, i) => {
        // 標註線放在這組房間的最下方 (MinY 最小值) 再減去 500mm
        const targetY = Math.min(...group.map(r => r.MinY)) - 500;
        console.log(`  組 ${i + 1}: ${group.map(r => r.Name).join(', ')}`);
        console.log(`         標註線 Y = ${targetY.toFixed(0)} mm`);

        group.forEach(room => {
            // offset = targetY - centerY (轉為 mm)
            const centerY = (room.MinY + room.MaxY) / 2;
            const offset = targetY - centerY;
            dimQueue.push({
                roomId: room.ElementId,
                roomName: room.Name,
                axis: 'X',
                offset: offset
            });
        });
    });

    console.log('');

    // Y軸標註分組：按 CenterX 分組 (同一列)
    const yGroups = groupBy(roomDataList, 'CenterX', GROUP_THRESHOLD);
    console.log(`Y軸分組: ${yGroups.length} 組`);
    yGroups.forEach((group, i) => {
        // 標註線放在這組房間的最右方 (MaxX 最大值) 再加 500mm
        const targetX = Math.max(...group.map(r => r.MaxX)) + 500;
        console.log(`  組 ${i + 1}: ${group.map(r => r.Name).join(', ')}`);
        console.log(`         標註線 X = ${targetX.toFixed(0)} mm`);

        group.forEach(room => {
            const centerX = (room.MinX + room.MaxX) / 2;
            const offset = targetX - centerX;
            dimQueue.push({
                roomId: room.ElementId,
                roomName: room.Name,
                axis: 'Y',
                offset: offset
            });
        });
    });

    console.log(`\n--- Phase 3: 建立標註 (共 ${dimQueue.length} 個) ---\n`);

    phase = 'CREATE_DIM';
    dimIndex = 0;
    processNextDim();
}

function groupBy(rooms, coordKey, threshold) {
    // 按座標排序
    const sorted = [...rooms].sort((a, b) => a[coordKey] - b[coordKey]);

    const groups = [];
    let currentGroup = [sorted[0]];

    for (let i = 1; i < sorted.length; i++) {
        if (sorted[i][coordKey] - sorted[i - 1][coordKey] <= threshold) {
            currentGroup.push(sorted[i]);
        } else {
            groups.push(currentGroup);
            currentGroup = [sorted[i]];
        }
    }
    groups.push(currentGroup);

    return groups;
}

// ====== 標註建立 ======

function processNextDim() {
    if (dimIndex >= dimQueue.length) {
        printSummary();
        setTimeout(() => ws.close(), 1000);
        return;
    }

    const item = dimQueue[dimIndex];

    ws.send(JSON.stringify({
        CommandName: 'create_dimension_by_bounding_box',
        Parameters: {
            viewId: activeViewId,
            roomId: item.roomId,
            axis: item.axis,
            offset: item.offset
        },
        RequestId: `dim_${item.axis}_${dimIndex}_${Date.now()}`
    }));
}

function handleCreateDim(response) {
    const item = dimQueue[dimIndex];

    if (response.Success && response.Data) {
        console.log(`  ✅ ${item.roomName} ${item.axis}軸: ${response.Data.Value} mm`);
        if (item.axis === 'X') stats.xSuccess++; else stats.ySuccess++;
    } else {
        console.log(`  ⚠️ ${item.roomName} ${item.axis}軸失敗: ${response.Error}`);
        if (item.axis === 'X') stats.xFailed++; else stats.yFailed++;
    }

    dimIndex++;
    setTimeout(() => processNextDim(), 300);
}

function printSummary() {
    const total = roomDataList.length;
    console.log('\n' + '='.repeat(50));
    console.log('📊 標註統計摘要 (分組對齊版)');
    console.log('='.repeat(50));
    console.log(`總房間數: ${total}`);
    console.log(`X軸成功: ${stats.xSuccess} ✅  失敗: ${stats.xFailed} ⚠️`);
    console.log(`Y軸成功: ${stats.ySuccess} ✅  失敗: ${stats.yFailed} ⚠️`);
    console.log(`總成功: ${stats.xSuccess + stats.ySuccess}`);
    console.log(`成功率: ${((stats.xSuccess + stats.ySuccess) / (total * 2) * 100).toFixed(1)}%`);
    console.log('='.repeat(50));
    console.log('\n🏁 完成！');
}

ws.on('error', (err) => console.error('錯誤:', err));
ws.on('close', () => process.exit(0));
