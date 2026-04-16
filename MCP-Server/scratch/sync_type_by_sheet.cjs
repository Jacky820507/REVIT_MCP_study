const fs = require('fs');
const { spawn } = require('child_process');

async function main() {
    // Read the sheets from the previously generated output
    const sheetsFilePath = 'C:/Users/09044/.gemini/antigravity/brain/d28a9073-7281-43f9-8629-2c987b6de1d1/.system_generated/steps/8/output.txt';
    let sheets;
    try {
        sheets = JSON.parse(fs.readFileSync(sheetsFilePath, 'utf8'));
    } catch(err) {
        console.error("Failed to load sheets file", err);
        process.exit(1);
    }
    
    const sheetMap = {};
    for (const s of sheets) {
        if (s.Name && s.Number) {
            sheetMap[s.Name.trim()] = s.Number.trim();
        }
    }
    console.log(`Loaded ${sheets.length} sheets. Built map with ${Object.keys(sheetMap).length} unique names.`);

    const mcp = spawn('node', ['E:/RevitMCP/MCP-Server/build/index.js']);
    let msgId = 1;
    let pendingRequests = {};
    let buffer = '';

    mcp.stdout.on('data', (chunk) => {
        buffer += chunk.toString();
        let lines = buffer.split('\n');
        for (let i = 0; i < lines.length - 1; i++) {
            const line = lines[i].trim();
            if (!line) continue;
            try {
                const res = JSON.parse(line);
                if (res.id && pendingRequests[res.id]) {
                    pendingRequests[res.id](res);
                    delete pendingRequests[res.id];
                }
            } catch (e) {
                // Ignore parse errors from non-json lines
            }
        }
        buffer = lines[lines.length - 1];
    });

    mcp.stderr.on('data', (chunk) => {
        // Output from mcp
    });

    function callTool(name, args) {
        return new Promise((resolve, reject) => {
            const id = msgId++;
            pendingRequests[id] = (response) => {
                if (response.error || (response.result && response.result.isError)) {
                    reject(response);
                } else {
                    try {
                        let content = response.result.content[0].text;
                        try { resolve(JSON.parse(content)); } 
                        catch (e2) { resolve(content); }
                    } catch (e) {
                        resolve(response.result);
                    }
                }
            };
            const req = {
                jsonrpc: "2.0",
                id: id,
                method: "tools/call",
                params: { name, arguments: args }
            };
            mcp.stdin.write(JSON.stringify(req) + '\n');
        });
    }

    try {
        console.log("Fetching types...");
        const types = await callTool('list_family_symbols', { filter: 'TEST-圖號詳圖編號標頭-3.5mm' });
        console.log(`Found ${types.length} types. Processing...`);

        let updated = 0;
        let skipped = 0;
        for (const type of types) {
            let info;
            try {
                info = await callTool('get_element_info', { elementId: type.Id });
            } catch (e) {
                console.log(`Failed to get info for ${type.Id}, skipping.`);
                continue;
            }
            
            let typeNameParam = "";
            let typeNumParam = "";
            for (const p of info.Parameters || []) {
                if (p.Name === "圖說名稱") typeNameParam = p.Value;
                if (p.Name === "詳圖圖號") typeNumParam = p.Value;
            }
            
            if (!typeNameParam || typeNameParam === "" || typeNameParam === "-") {
                console.log(`[SKIP] Type ${type.Id} (${type.Name}): No valid 圖說名稱.`);
                skipped++;
                continue;
            }

            const targetSheetNumber = sheetMap[typeNameParam.trim()];
            if (targetSheetNumber) {
                if (typeNumParam === targetSheetNumber) {
                    console.log(`[SKIP] Type ${type.Id} (${type.Name}): Already has correct 詳圖圖號 '${targetSheetNumber}'`);
                    skipped++;
                } else {
                    console.log(`[UPDATE] Type ${type.Id} (${type.Name}): Updating 詳圖圖號 from '${typeNumParam}' to '${targetSheetNumber}'`);
                    await callTool('modify_element_parameter', {
                        elementId: type.Id,
                        parameterName: "詳圖圖號",
                        value: targetSheetNumber
                    });
                    updated++;
                }
            } else {
                console.log(`[WARN] Type ${type.Id} (${type.Name}): No sheet found with name '${typeNameParam}'`);
                skipped++;
            }
        }

        console.log(`\n--- SUMMARY ---`);
        console.log(`Successfully updated ${updated} types.`);
        console.log(`Skipped ${skipped} types.`);
    } catch (e) {
        console.error("Fatal Error", e);
    } finally {
        mcp.kill();
        process.exit(0);
    }
}

main();
