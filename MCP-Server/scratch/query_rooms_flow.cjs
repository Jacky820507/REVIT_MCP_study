const WebSocket = require('ws');

const ws = new WebSocket('ws://localhost:8964');

ws.on('open', async function open() {
    console.log('Connected to WebSocket server');

    // Step 1: Get Active View
    const getActiveViewCmd = {
        CommandName: 'get_active_view',
        Parameters: {},
        RequestId: 'req_active_view'
    };
    ws.send(JSON.stringify(getActiveViewCmd));
});

ws.on('message', function incoming(data) {
    const response = JSON.parse(data.toString());
    console.log('Response:', JSON.stringify(response, null, 2));

    if (response.RequestId === 'req_active_view' && response.Success) {
        const levelName = response.Data.LevelName;
        if (levelName) {
            console.log(`Current level identified: ${levelName}`);
            const getRoomsCmd = {
                CommandName: 'get_rooms_by_level',
                Parameters: { level: levelName },
                RequestId: 'req_get_rooms'
            };
            ws.send(JSON.stringify(getRoomsCmd));
        } else {
            console.error('Active view does not have an associated level. Attempting to get all levels...');
            const getAllLevelsCmd = {
                CommandName: 'get_all_levels',
                Parameters: {},
                RequestId: 'req_all_levels'
            };
            ws.send(JSON.stringify(getAllLevelsCmd));
        }
    } else if (response.RequestId === 'req_all_levels' && response.Success) {
        const levels = response.Data.Levels;
        // Search for a level related to "4" since the sheet says 四層
        const targetLevel = levels.find(l => l.Name.includes('B-4F')) || levels[0];
        console.log(`Querying rooms for level: ${targetLevel.Name}`);
        const getRoomsCmd = {
            CommandName: 'get_rooms_by_level',
            Parameters: { level: targetLevel.Name },
            RequestId: 'req_get_rooms'
        };
        ws.send(JSON.stringify(getRoomsCmd));
    } else if (response.RequestId === 'req_get_rooms' && response.Success) {
        const rooms = response.Data.Rooms;
        const smallRooms = rooms.filter(r => r.Area < 40);
        console.log('--- SMALL ROOMS (< 40m2) ---');
        console.log(JSON.stringify(smallRooms, null, 2));
        ws.close();
    }
});

ws.on('error', (err) => console.error('WS Error:', err.message));
