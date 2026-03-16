/**
 * 批量机电净尺寸自动标注
 * 为当前视图的所有房间创建X和Y轴净尺寸标注
 */

import WebSocket from 'ws';

const ws = new WebSocket('ws://localhost:8964');

let step = 1;
let activeViewId = null;
let allRooms = [];
let currentRoomIndex = 0;
let stats = {
    total: 0,
    xSuccess: 0,
    ySuccess: 0,
    xFailed: 0,
    yFailed: 0,
    roomsProcessed: 0
};

ws.on('open', function () {
    console.log('=== 批量機電淨尺寸自動標註 ===\n');

    const command = {
        CommandName: 'get_active_view',
        Parameters: {},
        RequestId: 'get_view_' + Date.now()
    };
    ws.send(JSON.stringify(command));
});

ws.on('message', function (data) {
    const response = JSON.parse(data.toString());

    if (step === 1) {
        // 获取视图信息
        if (response.Success && response.Data) {
            activeViewId = response.Data.ViewId || response.Data.ElementId || response.Data.Id;
            const viewName = response.Data.Name;
            const distinctLevel = response.Data.LevelName || response.Data.Level;

            console.log(`📍 目前視圖: ${viewName} (ID: ${activeViewId})`);
            console.log(`   樓層: ${distinctLevel || '未知'}\n`);

            step = 2;
            const roomsCommand = {
                CommandName: 'get_rooms_by_level',
                Parameters: { level: distinctLevel },
                RequestId: 'get_rooms_' + Date.now()
            };
            ws.send(JSON.stringify(roomsCommand));
        }
    } else if (step === 2) {
        // 获取所有房间
        if (response.Success && response.Data) {
            allRooms = Array.isArray(response.Data) ? response.Data : (response.Data.Rooms || []);
            stats.total = allRooms.length;

            console.log(`✅ 找到 ${stats.total} 個房間\n`);
            console.log('--- 開始批量標註 ---\n');

            if (stats.total === 0) {
                console.log('⚠️ 沒有房間需要標註');
                ws.close();
                return;
            }

            step = 3;
            processNextRoom();
        }
    } else if (step === 3) {
        // 获取房间详细信息
        if (response.Success && response.Data) {
            const room = response.Data;
            const roomCenter = (room.CenterX !== undefined && room.CenterY !== undefined)
                ? { x: room.CenterX, y: room.CenterY, z: (room.CenterZ || 0) + 1200 }
                : null;

            if (!roomCenter) {
                console.log(`  ⚠️ 無法取得中心點，跳過\n`);
                moveToNextRoom();
                return;
            }

            // 储存当前房间中心，准备标注
            ws.currentRoomCenter = roomCenter;
            ws.currentRoomName = allRooms[currentRoomIndex].Name;

            step = 4;
            tryDimensionX();
        }
    } else if (step === 4) {
        // X轴标注结果
        if (response.Success && response.Data) {
            console.log(`  ✅ X軸: ${response.Data.Value} mm`);
            stats.xSuccess++;
        } else {
            console.log(`  ⚠️ X軸失敗`);
            stats.xFailed++;
        }

        step = 5;
        setTimeout(() => tryDimensionY(), 500);
    } else if (step === 5) {
        // Y轴标注结果
        if (response.Success && response.Data) {
            console.log(`  ✅ Y軸: ${response.Data.Value} mm`);
            stats.ySuccess++;
        } else {
            console.log(`  ⚠️ Y軸失敗`);
            stats.yFailed++;
        }

        console.log(''); // 空行
        stats.roomsProcessed++;

        // 处理下一个房间
        moveToNextRoom();
    }

    function processNextRoom() {
        if (currentRoomIndex >= allRooms.length) {
            // 所有房间处理完毕
            printSummary();
            setTimeout(() => ws.close(), 1000);
            return;
        }

        const room = allRooms[currentRoomIndex];
        console.log(`[${currentRoomIndex + 1}/${stats.total}] ${room.Name || '未命名'} (ID: ${room.ElementId})`);

        step = 3;
        const roomInfoCommand = {
            CommandName: 'get_room_info',
            Parameters: { roomId: room.ElementId },
            RequestId: 'room_info_' + Date.now()
        };
        ws.send(JSON.stringify(roomInfoCommand));
    }

    function moveToNextRoom() {
        currentRoomIndex++;
        setTimeout(() => processNextRoom(), 500);
    }

    function tryDimensionX() {
        const dimCommand = {
            CommandName: 'create_dimension_by_ray',
            Parameters: {
                viewId: activeViewId,
                origin: ws.currentRoomCenter,
                direction: { x: 1, y: 0, z: 0 },
                counterDirection: { x: -1, y: 0, z: 0 }
            },
            RequestId: 'dim_x_' + Date.now()
        };
        ws.send(JSON.stringify(dimCommand));
    }

    function tryDimensionY() {
        const dimCommand = {
            CommandName: 'create_dimension_by_ray',
            Parameters: {
                viewId: activeViewId,
                origin: ws.currentRoomCenter,
                direction: { x: 0, y: 1, z: 0 },
                counterDirection: { x: 0, y: -1, z: 0 }
            },
            RequestId: 'dim_y_' + Date.now()
        };
        ws.send(JSON.stringify(dimCommand));
    }

    function printSummary() {
        console.log('='.repeat(50));
        console.log('📊 標註統計摘要');
        console.log('='.repeat(50));
        console.log(`總房間數: ${stats.total}`);
        console.log(`已處理: ${stats.roomsProcessed}`);
        console.log('');
        console.log(`X軸標註成功: ${stats.xSuccess} ✅`);
        console.log(`X軸標註失敗: ${stats.xFailed} ⚠️`);
        console.log(`Y軸標註成功: ${stats.ySuccess} ✅`);
        console.log(`Y軸標註失敗: ${stats.yFailed} ⚠️`);
        console.log('');
        console.log(`總成功標註: ${stats.xSuccess + stats.ySuccess}`);
        console.log(`總失敗標註: ${stats.xFailed + stats.yFailed}`);
        console.log('='.repeat(50));
        console.log('\n🏁 批量標註完成！');
    }
});

ws.on('error', function (err) {
    console.error('連線錯誤:', err);
});

ws.on('close', function () {
    process.exit(0);
});
