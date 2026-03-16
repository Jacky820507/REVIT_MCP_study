/**
 * Y轴射线诊断工具
 */

import WebSocket from 'ws';

const ws = new WebSocket('ws://localhost:8964');

let step = 1;
let activeViewId = null;

ws.on('open', function () {
    console.log('=== Y軸射線診斷 ===\n');

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
            const distinctLevel = response.Data.LevelName || response.Data.Level;

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
            const targetRoom = rooms.find(r => r.Name && r.Name.includes('機房')) || rooms[0];

            if (targetRoom) {
                console.log(`房間: ${targetRoom.Name}\n`);

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
            const center = {
                x: room.CenterX,
                y: room.CenterY,
                z: (room.CenterZ || 0) + 1200
            };

            console.log(`射線起點: (${center.x.toFixed(2)}, ${center.y.toFixed(2)}, ${center.z.toFixed(2)})\n`);

            step = 4;
            console.log('--- 診斷 Y 軸（垂直）射線 ---');

            const debugCommand = {
                CommandName: 'create_dimension_by_ray_debug',
                Parameters: {
                    origin: center,
                    direction: { x: 0, y: 1, z: 0 }  // 向上
                },
                RequestId: 'debug_y_' + Date.now()
            };
            ws.send(JSON.stringify(debugCommand));
        }
    } else if (step === 4) {
        if (response.Success && response.Data) {
            const data = response.Data;
            console.log(`使用的 3D 視圖: ${data.View3D}`);
            console.log(`Y軸正向偵測到: ${data.HitCount} 個元素`);

            if (data.HitCount > 0) {
                console.log(`  最近距離: ${data.Hits[0].Distance.toFixed(2)} mm`);
                console.log(`  元素 ID: ${data.Hits[0].ElemId}`);
            } else {
                console.log(`  ❌ 未偵測到牆面`);
            }

            // 再测试反向
            step = 5;
            const debugCommand = {
                CommandName: 'create_dimension_by_ray_debug',
                Parameters: {
                    origin: {
                        x: response.Data.Origin.X,
                        y: response.Data.Origin.Y,
                        z: response.Data.Origin.Z
                    },
                    direction: { x: 0, y: -1, z: 0 }  // 向下
                },
                RequestId: 'debug_y_reverse_' + Date.now()
            };
            ws.send(JSON.stringify(debugCommand));
        } else {
            console.error('診斷失敗:', response.Error);
            ws.close();
        }
    } else if (step === 5) {
        if (response.Success && response.Data) {
            const data = response.Data;
            console.log(`\nY軸反向偵測到: ${data.HitCount} 個元素`);

            if (data.HitCount > 0) {
                console.log(`  最近距離: ${data.Hits[0].Distance.toFixed(2)} mm`);
                console.log(`  元素 ID: ${data.Hits[0].ElemId}`);
            } else {
                console.log(`  ❌ 未偵測到牆面`);
                console.log(`\n可能原因：房間Y方向沒有封閉的牆`);
            }

            console.log('\n🏁 診斷結束');
            setTimeout(() => ws.close(), 1000);
        }
    }
});

ws.on('error', function (err) {
    console.error('錯誤:', err);
});

ws.on('close', function () {
    process.exit(0);
});
