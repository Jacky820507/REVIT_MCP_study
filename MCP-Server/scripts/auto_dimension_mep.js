/**
 * 机电净尺寸自动标注 (改进版 - 容错处理)
 * 尝试X和Y两个方向，失败的方向会跳过并继续
 */

import WebSocket from 'ws';

const ws = new WebSocket('ws://localhost:8964');

const ROOM_NAME_KEYWORD = '機房';

let step = 1;
let activeViewId = null;
let roomCenter = null;

ws.on('open', function () {
    console.log('=== 機電淨尺寸自動標註 (改進版) ===\n');

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
        if (response.Success && response.Data) {
            const rooms = Array.isArray(response.Data) ? response.Data : (response.Data.Rooms || []);
            const targetRoom = rooms.find(r => r.Name && r.Name.includes(ROOM_NAME_KEYWORD)) || rooms[0];

            if (targetRoom) {
                console.log(`✅ 選定房間: ${targetRoom.Name} (ID: ${targetRoom.ElementId})\n`);

                step = 3;
                const roomInfoCommand = {
                    CommandName: 'get_room_info',
                    Parameters: { roomId: targetRoom.ElementId },
                    RequestId: 'get_room_info_' + Date.now()
                };
                ws.send(JSON.stringify(roomInfoCommand));
            }
        }
    } else if (step === 3) {
        if (response.Success && response.Data) {
            const room = response.Data;

            roomCenter = (room.CenterX !== undefined && room.CenterY !== undefined)
                ? { x: room.CenterX, y: room.CenterY, z: (room.CenterZ || 0) + 1200 }
                : null;

            if (!roomCenter) {
                console.error('❌ 無法取得房間中心點');
                ws.close();
                return;
            }

            console.log(`📍 射線起點: (${roomCenter.x.toFixed(2)}, ${roomCenter.y.toFixed(2)}, ${roomCenter.z.toFixed(2)})\n`);
            console.log('--- 開始標註 ---\n');

            step = 4;
            tryXAxisDimension();
        }
    } else if (step === 4) {
        // X軸結果
        if (response.Success && response.Data) {
            console.log(`✅ X軸標註成功! ID: ${response.Data.DimensionId}, 值: ${response.Data.Value} ${response.Data.Unit}`);
        } else {
            console.log(`⚠️ X軸標註失敗: ${response.Error}`);
        }

        // 繼續嘗試Y軸
        step = 5;
        setTimeout(() => tryYAxisDimension(), 1000);
    } else if (step === 5) {
        // Y軸結果
        if (response.Success && response.Data) {
            console.log(`✅ Y軸標註成功! ID: ${response.Data.DimensionId}, 值: ${response.Data.Value} ${response.Data.Unit}`);
        } else {
            console.log(`⚠️ Y軸標註失敗: ${response.Error}`);
        }

        console.log('\n🏁 標註任務完成');
        setTimeout(() => ws.close(), 1000);
    }

    function tryXAxisDimension() {
        console.log('➡️ 嘗試 X 軸標註...');
        const dimXCommand = {
            CommandName: 'create_dimension_by_ray',
            Parameters: {
                viewId: activeViewId,
                origin: roomCenter,
                direction: { x: 1, y: 0, z: 0 },
                counterDirection: { x: -1, y: 0, z: 0 }
            },
            RequestId: 'dim_x_' + Date.now()
        };
        ws.send(JSON.stringify(dimXCommand));
    }

    function tryYAxisDimension() {
        console.log('⬆️ 嘗試 Y 軸標註...');
        const dimYCommand = {
            CommandName: 'create_dimension_by_ray',
            Parameters: {
                viewId: activeViewId,
                origin: roomCenter,
                direction: { x: 0, y: 1, z: 0 },
                counterDirection: { x: 0, y: -1, z: 0 }
            },
            RequestId: 'dim_y_' + Date.now()
        };
        ws.send(JSON.stringify(dimYCommand));
    }
});

ws.on('error', function (err) {
    console.error('連線錯誤:', err);
});

ws.on('close', function () {
    process.exit(0);
});
