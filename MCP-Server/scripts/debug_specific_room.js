/**
 * 特定房间Y轴失败诊断工具
 * 针对中控室进行深度诊断
 */

import WebSocket from 'ws';

const ws = new WebSocket('ws://localhost:8964');

const TARGET_ROOM_NAME = '中控室';

let step = 1;
let activeViewId = null;

ws.on('open', function () {
    console.log(`=== ${TARGET_ROOM_NAME} Y軸診斷 ===\n`);

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
            const targetRoom = rooms.find(r => r.Name && r.Name.includes(TARGET_ROOM_NAME));

            if (targetRoom) {
                console.log(`找到房間: ${targetRoom.Name} (ID: ${targetRoom.ElementId})\n`);

                step = 3;
                const roomInfoCommand = {
                    CommandName: 'get_room_info',
                    Parameters: { roomId: targetRoom.ElementId },
                    RequestId: 'get_room_info_' + Date.now()
                };
                ws.send(JSON.stringify(roomInfoCommand));
            } else {
                console.error(`❌ 找不到房間: ${TARGET_ROOM_NAME}`);
                ws.close();
            }
        }
    } else if (step === 3) {
        if (response.Success && response.Data) {
            const room = response.Data;
            console.log(`房間資訊：`);
            console.log(`  名稱: ${room.Name}`);
            console.log(`  編號: ${room.Number || '無'}`);
            console.log(`  樓層: ${room.Level}`);
            console.log(`  中心點: (${room.CenterX}, ${room.CenterY}, ${room.CenterZ})`);
            console.log(`  邊界框:`);
            if (room.BoundingBox) {
                console.log(`    MinX: ${room.BoundingBox.MinX}, MaxX: ${room.BoundingBox.MaxX}`);
                console.log(`    MinY: ${room.BoundingBox.MinY}, MaxY: ${room.BoundingBox.MaxY}`);
                const widthX = room.BoundingBox.MaxX - room.BoundingBox.MinX;
                const widthY = room.BoundingBox.MaxY - room.BoundingBox.MinY;
                console.log(`    理論X寬度: ${widthX.toFixed(2)} mm`);
                console.log(`    理論Y深度: ${widthY.toFixed(2)} mm`);
            }
            console.log('');

            ws.roomCenter = {
                x: room.CenterX,
                y: room.CenterY,
                z: (room.CenterZ || 0) + 1200
            };

            // 测试不同高度的Y轴
            step = 4;
            console.log('--- 測試 Y軸（高度 +1200mm） ---');
            testYAxis(ws.roomCenter);
        }
    } else if (step === 4) {
        // Y轴 +1200mm 结果
        if (response.Success && response.Data) {
            console.log(`✅ Y軸正向偵測: ${response.Data.HitCount} 個元素`);
            if (response.Data.HitCount > 0) {
                console.log(`   距離: ${response.Data.Hits[0].Distance.toFixed(2)} mm`);
            }
        } else {
            console.log(`❌ 失敗`);
        }

        // 测试反向
        step = 5;
        setTimeout(() => {
            console.log('');
            testYAxisReverse(ws.roomCenter);
        }, 500);
    } else if (step === 5) {
        // Y轴反向结果
        if (response.Success && response.Data) {
            console.log(`✅ Y軸反向偵測: ${response.Data.HitCount} 個元素`);
            if (response.Data.HitCount > 0) {
                console.log(`   距離: ${response.Data.Hits[0].Distance.toFixed(2)} mm`);
            }
        } else {
            console.log(`❌ 失敗`);
        }

        // 测试更低的高度
        step = 6;
        const lowerCenter = { ...ws.roomCenter, z: ws.roomCenter.z - 600 }; // -600mm = +600mm
        setTimeout(() => {
            console.log('\n--- 測試 Y軸（高度 +600mm，較低） ---');
            testYAxis(lowerCenter);
        }, 500);
    } else if (step === 6) {
        if (response.Success && response.Data) {
            console.log(`✅ Y軸正向偵測: ${response.Data.HitCount} 個元素`);
            if (response.Data.HitCount > 0) {
                console.log(`   距離: ${response.Data.Hits[0].Distance.toFixed(2)} mm`);
            }
        } else {
            console.log(`❌ 失敗`);
        }

        step = 7;
        const lowerCenter = { ...ws.roomCenter, z: ws.roomCenter.z - 600 };
        setTimeout(() => {
            testYAxisReverse(lowerCenter);
        }, 500);
    } else if (step === 7) {
        if (response.Success && response.Data) {
            console.log(`✅ Y軸反向偵測: ${response.Data.HitCount} 個元素`);
            if (response.Data.HitCount > 0) {
                console.log(`   距離: ${response.Data.Hits[0].Distance.toFixed(2)} mm`);
            }
        } else {
            console.log(`❌ 失敗`);
        }

        console.log('\n--- 診斷結論 ---');
        console.log('如果兩個高度都失敗，可能原因：');
        console.log('1. Y方向沒有完整的牆面（開放式或大門口）');
        console.log('2. 3D視圖的可見性設定隱藏了某些元素');
        console.log('3. 房間邊界與實體牆不一致');

        setTimeout(() => ws.close(), 1000);
    }

    function testYAxis(center) {
        const debugCommand = {
            CommandName: 'create_dimension_by_ray_debug',
            Parameters: {
                origin: center,
                direction: { x: 0, y: 1, z: 0 }
            },
            RequestId: 'test_y_' + Date.now()
        };
        ws.send(JSON.stringify(debugCommand));
    }

    function testYAxisReverse(center) {
        const debugCommand = {
            CommandName: 'create_dimension_by_ray_debug',
            Parameters: {
                origin: center,
                direction: { x: 0, y: -1, z: 0 }
            },
            RequestId: 'test_y_rev_' + Date.now()
        };
        ws.send(JSON.stringify(debugCommand));
    }
});

ws.on('error', function (err) {
    console.error('錯誤:', err);
});

ws.on('close', function () {
    process.exit(0);
});
