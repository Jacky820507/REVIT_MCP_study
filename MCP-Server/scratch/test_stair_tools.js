import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';

async function main() {
    const transport = new StdioClientTransport({
        command: 'node',
        args: ['e:/RevitMCP/MCP-Server/build/index.js']
    });

    const client = new Client(
        { name: 'test-client', version: '1.0.0' },
        { capabilities: {} }
    );

    try {
        await client.connect(transport);
        console.log('Connected to MCP Server');

        console.log('--- Get Line Styles ---');
        const styles = await client.callTool('get_line_styles', {});
        // styles.content[0].text is the JSON string
        const stylesData = JSON.parse(styles.content[0].text);
        console.log('Line Styles:', JSON.stringify(stylesData, null, 2));

        const dashStyle = stylesData.find(s => s.Name.includes('Dash') || s.Name.includes('虛線') || s.Name.includes('隱藏線'));
        const styleId = dashStyle ? dashStyle.Id : null;
        console.log('Selected Style ID:', styleId);

        console.log('--- Trace Stair Geometry ---');
        const traceResult = await client.callTool('trace_stair_geometry', {});
        const stairs = JSON.parse(traceResult.content[0].text);
        console.log('Trace Result:', JSON.stringify(stairs, null, 2));

        for (const stair of stairs) {
            if (stair.HiddenLines && stair.HiddenLines.length > 0) {
                console.log(`Creating ${stair.HiddenLines.length} lines for stair ${stair.StairId}`);
                const createResult = await client.callTool('create_detail_lines', {
                    lines: stair.HiddenLines,
                    styleId: styleId
                });
                console.log('Create Result:', JSON.stringify(createResult, null, 2));
            } else {
                console.log(`No hidden lines detected for stair ${stair.StairId}`);
            }
        }

    } catch (error) {
        console.error('Error:', error);
    } finally {
        process.exit(0);
    }
}

main();
