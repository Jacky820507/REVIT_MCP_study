import WebSocket from 'ws';

const ws = new WebSocket('ws://localhost:8964');
// Get geometry info for a few reference lines
const sampleIds = [11928002, 11928003, 11928004, 11928005, 11928018, 11928019, 11928020, 11928021];
let idx = 0;

ws.on('open', () => {
    console.log(`Getting geometry for ${sampleIds.length} reference detail lines...`);
    queryNext();
});

function queryNext() {
    if (idx >= sampleIds.length) {
        ws.close(); process.exit(0);
    }
    ws.send(JSON.stringify({
        CommandName: 'get_element_info',
        Parameters: { elementId: sampleIds[idx] },
        RequestId: `e${idx}`
    }));
}

ws.on('message', (data) => {
    const r = JSON.parse(data.toString());
    if (r.RequestId && r.RequestId.startsWith('e')) {
        const id = sampleIds[idx];
        if (r.Success) {
            const d = r.Data;
            // Extract geometry from the element info
            const geom = d.Geometry || {};
            const params = d.Parameters || {};
            console.log(`\n[${id}]:`);
            console.log(`  Category: ${d.Category}`);
            console.log(`  Type: ${d.TypeName || d.FamilyName}`);
            if (geom.StartPoint) {
                console.log(`  Start: (${(geom.StartPoint.X*304.8).toFixed(1)}, ${(geom.StartPoint.Y*304.8).toFixed(1)}, ${(geom.StartPoint.Z*304.8).toFixed(1)}) mm`);
            }
            if (geom.EndPoint) {
                console.log(`  End:   (${(geom.EndPoint.X*304.8).toFixed(1)}, ${(geom.EndPoint.Y*304.8).toFixed(1)}, ${(geom.EndPoint.Z*304.8).toFixed(1)}) mm`);
            }
            if (geom.Length) {
                console.log(`  Length: ${(geom.Length*304.8).toFixed(1)} mm`);
            }
            // Log any line style info
            if (d.LineStyle) console.log(`  LineStyle: ${d.LineStyle}`);
            // Print BBox
            if (d.BoundingBox) {
                const bb = d.BoundingBox;
                console.log(`  BBox: (${(bb.Min.X*304.8).toFixed(1)},${(bb.Min.Y*304.8).toFixed(1)},${(bb.Min.Z*304.8).toFixed(1)}) ~ (${(bb.Max.X*304.8).toFixed(1)},${(bb.Max.Y*304.8).toFixed(1)},${(bb.Max.Z*304.8).toFixed(1)})`);
            }
            // Check group membership
            const groupParam = Object.entries(params).find(([k, v]) => k.includes('群組') || k.includes('Group'));
            if (groupParam) console.log(`  Group: ${groupParam[1]}`);
        } else {
            console.log(`[${id}] Error: ${r.Error}`);
        }
        idx++;
        queryNext();
    }
});

ws.on('error', (e) => { console.error('WS Error:', e.message); process.exit(1); });
setTimeout(() => { console.log('Timeout'); ws.close(); process.exit(1); }, 30000);
