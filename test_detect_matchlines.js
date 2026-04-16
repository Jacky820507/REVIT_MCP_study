import { spawn } from 'child_process';

// 測試 detect_sheet_matchlines 功能
const testDetectSheetMatchlines = () => {
    console.log('🧪 測試 detect_sheet_matchlines 功能');
    console.log('圖紙號碼: A101-A106');

    const cmd = spawn('node', [
        'MCP-Server/scripts/run_command.js',
        'detect_sheet_matchlines',
        JSON.stringify({
            sheetNumbers: ['A101', 'A102', 'A103', 'A104', 'A105', 'A106'],
            lineStyleName: '粗虛線',
            textStyleName: '微軟正黑體 3.5 mm'
        })
    ], {
        stdio: 'inherit',
        cwd: 'e:/RevitMCP'
    });

    cmd.on('close', (code) => {
        console.log(`\n✅ 測試完成，退出碼: ${code}`);
    });

    cmd.on('error', (err) => {
        console.error('❌ 測試失敗:', err);
    });
};

// 執行測試
testDetectSheetMatchlines();