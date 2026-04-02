/**
 * 射線偵測診斷工具
 * 用於了解為何 ReferenceIntersector 沒有找到牆面
 */

import WebSocket from 'ws';

const ws = new WebSocket('ws://localhost:8964');

const LEVEL_NAME = 'A-2F';
const ROOM_NAME_KEYWORD = '機房';

let step = 1;
let activeViewId = null;

ws.on('open', function () {
    console.log('=== 射線偵測診斷工具 ===\n');

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
            console.log(`   樓層: ${distinctLevel || '未知'}`);

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
            const center = (room.CenterX !== undefined && room.CenterY !== undefined)
                ? { x: room.CenterX, y: room.CenterY, z: (room.CenterZ || 0) + 1200 }
                : null;

            console.log(`📍 房間中心: (${center.x.toFixed(2)}, ${center.y.toFixed(2)}, ${center.z.toFixed(2)})\n`);

            step = 4;
            console.log('--- 診斷：正向 X 軸射線 (向右) ---');

            const debugCommand = {
                CommandName: 'create_dimension_by_ray_debug',
                Parameters: {
                    origin: center,
                    direction: { x: 1, y: 0, z: 0 }
                },
                RequestId: 'debug_ray_' + Date.now()
            };
            ws.send(JSON.stringify(debugCommand));
        }
    } else if (step === 4) {
        if (response.Success && response.Data) {
            const data = response.Data;
            console.log(`✅ 診斷成功`);
            console.log(`   使用的 3D 視圖: ${data.View3D || '未知'}`);
            console.log(`   偵測到的元素數: ${data.HitCount}`);

            if (data.HitCount > 0) {
                console.log(`   最近的牆距離: ${data.Hits[0].Distance.toFixed(2)} mm`);
                console.log(`   元素 ID: ${data.Hits[0].ElemId}`);
            } else {
                console.log(`   ❌ 未偵測到任何牆或柱`);
                console.log(`   可能原因：`);
                console.log(`   1. 3D 視圖開啟了 Section Box (剖面框)`);
                console.log(`   2. 3D 視圖隱藏了牆或柱子`);
                console.log(`   3. 房間中心點位置錯誤`);
            }

            console.log('\n🏁 診斷結束');
            setTimeout(() => ws.close(), 1000);
        } else {
            console.error('❌ 診斷失敗:', response.Error);
            ws.close();
        }
    }
});

ws.on('error', function (err) {
    console.error('連線錯誤:', err);
});

ws.on('close', function () {
    process.exit(0);
});
