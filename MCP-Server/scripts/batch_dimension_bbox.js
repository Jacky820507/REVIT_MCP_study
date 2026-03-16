/**
 * 批量房间尺寸标注 (BoundingBox 方法)
 * 使用房间边界框进行标注，保证 100% 覆盖率
 */

import WebSocket from 'ws';

const ws = new WebSocket('ws://localhost:8964');

let step = 1;
let activeViewId = null;
let allRooms = [];
let currentRoomIndex = 0;
let currentAxis = 'X'; // 当前标注的轴向
let stats = {
    total: 0,
    xSuccess: 0,
    ySuccess: 0,
    xFailed: 0,
    yFailed: 0,
    roomsProcessed: 0
};

ws.on('open', function () {
    console.log('=== 批量機電淨尺寸自動標註 (BoundingBox 方法) ===\n');

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
            console.log('--- 開始批量標註 (BoundingBox 方法) ---\n');

            if (stats.total === 0) {
                console.log('⚠️ 沒有房間需要標註');
                ws.close();
                return;
            }

            step = 3;
            currentAxis = 'X';
            processCurrentRoomAxis();
        }
    } else if (step === 3) {
        // X轴标注结果
        if (response.Success && response.Data) {
            console.log(`  ✅ X軸: ${response.Data.Value} mm`);
            stats.xSuccess++;
        } else {
            console.log(`  ⚠️ X軸失敗: ${response.Error}`);
            stats.xFailed++;
        }

        // 继续标注Y轴
        step = 4;
        currentAxis = 'Y';
        setTimeout(() => processCurrentRoomAxis(), 500);
    } else if (step === 4) {
        // Y轴标注结果
        if (response.Success && response.Data) {
            console.log(`  ✅ Y軸: ${response.Data.Value} mm`);
            stats.ySuccess++;
        } else {
            console.log(`  ⚠️ Y軸失敗: ${response.Error}`);
            stats.yFailed++;
        }

        console.log(''); // 空行
        stats.roomsProcessed++;

        // 处理下一个房间
        moveToNextRoom();
    }

    function processCurrentRoomAxis() {
        const room = allRooms[currentRoomIndex];

        if (currentAxis === 'X' && step === 3) {
            console.log(`[${currentRoomIndex + 1}/${stats.total}] ${room.Name || '未命名'} (ID: ${room.ElementId})`);
        }

        const dimCommand = {
            CommandName: 'create_dimension_by_bounding_box',
            Parameters: {
                viewId: activeViewId,
                roomId: room.ElementId,
                axis: currentAxis,
                offset: 500
            },
            RequestId: `dim_${currentAxis}_${Date.now()}`
        };
        ws.send(JSON.stringify(dimCommand));
    }

    function moveToNextRoom() {
        currentRoomIndex++;

        if (currentRoomIndex >= allRooms.length) {
            // 所有房间处理完毕
            printSummary();
            setTimeout(() => ws.close(), 1000);
            return;
        }

        step = 3;
        currentAxis = 'X';
        setTimeout(() => processCurrentRoomAxis(), 500);
    }

    function printSummary() {
        console.log('='.repeat(50));
        console.log('📊 標註統計摘要 (BoundingBox 方法)');
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
        console.log(`成功率: ${((stats.xSuccess + stats.ySuccess) / (stats.total * 2) * 100).toFixed(1)}%`);
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
