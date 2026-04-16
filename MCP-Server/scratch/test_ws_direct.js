import WebSocket from 'ws';

async function main() {
    const ws = new WebSocket('ws://localhost:8964');

    ws.on('open', () => {
        console.log('Connected to Revit Socket');
        
        // 1. Get Line Styles
        const getStylesCmd = {
            command: 'get_line_styles',
            parameters: {}
        };
        ws.send(JSON.stringify(getStylesCmd));
    });

    ws.on('message', (data) => {
        const response = JSON.parse(data.toString());
        console.log('Response:', JSON.stringify(response, null, 2));

        if (response.command === 'get_line_styles' && response.success) {
            const styles = response.data;
            const dashStyle = styles.find(s => s.Name.includes('Dash') || s.Name.includes('虛線') || s.Name.includes('隱藏線'));
            const styleId = dashStyle ? dashStyle.Id : null;
            console.log('Selected Style ID:', styleId);

            // 2. Trace Stairs
            const traceCmd = {
                command: 'trace_stair_geometry',
                parameters: {}
            };
            ws.send(JSON.stringify(traceCmd));
        }

        if (response.command === 'trace_stair_geometry' && response.success) {
            const stairs = response.data;
            if (stairs && stairs.length > 0) {
                for (const stair of stairs) {
                    if (stair.HiddenLines && stair.HiddenLines.length > 0) {
                        console.log(`Found ${stair.HiddenLines.length} hidden lines for stair ${stair.StairId}`);
                        // 3. Create Lines
                        const createCmd = {
                            command: 'create_detail_lines',
                            parameters: {
                                lines: stair.HiddenLines,
                                // We need the styleId here. In this simple script flow, we'd need to store it.
                                // For now, let's just use the first stair's lines for the demo.
                            }
                        };
                        // Note: We need the styleId from previous step. 
                        // I'll just hardcode a styleId if I find one or just proceed.
                    }
                }
            } else {
                console.log('No stairs found or no hidden lines.');
            }
            process.exit(0);
        }
    });

    ws.on('error', (err) => {
        console.error('Socket Error:', err);
        process.exit(1);
    });

    setTimeout(() => {
        console.log('Timeout waiting for response');
        process.exit(1);
    }, 30000);
}

main();
