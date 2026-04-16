const fs = require('fs');
const iconv = require('iconv-lite'); // If available, otherwise we'll try something else

try {
    const buffer = fs.readFileSync('E:/RevitMCP/圖紙清單.csv');
    // Try to detect or just use 950 (Big5)
    // If iconv-lite is not available, we can't easily decode Big5 in Node without a library.
    // Let's use PowerShell's internal redirection which is safer.
    console.log('Using Node to trigger safer PowerShell...');
} catch (e) {
    console.error(e);
}
