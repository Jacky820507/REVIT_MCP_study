import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function main() {
    const args = process.argv.slice(2);
    const dryRun = args.includes('--dry-run');

    console.log("==========================================");
    console.log("   自動繪製切圖界線 (Matchlines) 輔助程式");
    console.log("==========================================");

    if (dryRun) {
        console.log("[Dry-Run 模式] 僅做測試呼叫...");
    }

    const requestPayload = {
        jsonrpc: "2.0",
        id: Date.now().toString(),
        method: "tools/call",
        params: {
            name: "create_dependent_view_matchlines",
            arguments: {
                lineStyleName: "粗虛線",
                textStyleName: "微軟正黑體 3.5 mm"
            }
        }
    };

    console.log("發送指令至 Revit MCP Server...");
    
    // 呼叫本地的 MCP Server，並將標準輸出導出
    const mcpServer = spawn('node', [path.join(__dirname, 'build/index.js')]);

    let responseData = '';
    
    mcpServer.stdout.on('data', (data) => {
        responseData += data.toString();
        const lines = responseData.split('\n');
        for (let i = 0; i < lines.length - 1; i++) {
            const line = lines[i].trim();
            if (!line) continue;
            
            try {
                const res = JSON.parse(line);
                if (res.id === requestPayload.id) {
                    if (res.result && !res.result.isError) {
                        const content = JSON.parse(res.result.content[0].text);
                        console.log("\n✅ 執行成功：");
                        console.log(JSON.stringify(content, null, 2));
                    } else {
                        console.log("\n❌ 執行失敗：", res.error || res.result.content[0].text);
                    }
                    mcpServer.kill();
                    process.exit(0);
                }
            } catch (e) {
                // Ignore incomplete JSON chunks
            }
        }
        responseData = lines[lines.length - 1]; 
    });

    mcpServer.stderr.on('data', (data) => {
        console.error(`[Server Error]: ${data}`);
    });

    mcpServer.on('close', (code) => {
        console.log(`MCP 伺服器已退出，代碼: ${code}`);
    });

    mcpServer.stdin.write(JSON.stringify(requestPayload) + '\n');
}

main().catch(console.error);
