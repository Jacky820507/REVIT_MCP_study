const xlsx = require('xlsx');
const fs = require('fs');

// Read Revit sheets
const revitSheetsPath = 'C:/Users/09044/.gemini/antigravity/brain/811df5b4-39b7-4436-9181-c20c8887a752/.system_generated/steps/27/output.txt'; 
let revitData = {};
try {
  revitData = JSON.parse(fs.readFileSync(revitSheetsPath, 'utf8'));
} catch (e) {
  console.error("Failed to read Revit sheets:", e);
  process.exit(1);
}
const revitSheets = revitData.Sheets;

// Read Excel sheets
const workbook = xlsx.readFile('E:/RevitMCP/B-Sheets.xlsx');
const sheetName = workbook.SheetNames[0];
const xlData = xlsx.utils.sheet_to_json(workbook.Sheets[sheetName], { defval: "" });

if(xlData.length === 0) {
    console.log("Excel file is empty");
    process.exit(1);
}

const headers = Object.keys(xlData[0]);
console.log("Excel Headers found:", headers);

// Find the right column names dynamically
let nameCol = headers.find(h => h.includes('圖名') || h.includes('名稱') || h.toLowerCase().includes('name'));
let numCol = headers.find(h => h.includes('圖號') || h.includes('編碼') || h.includes('編號') || h.toLowerCase().includes('number') || h.includes('Sheet Number'));

if (!nameCol || !numCol) {
    console.log("Could not dynamically find name and number columns. Using explicit indexes 0 and 1.");
    numCol = headers[0];
    nameCol = headers[1];
}

console.log(`Using Name Column: '${nameCol}', Number Column: '${numCol}'`);

const excelMap = new Map();
for(const row of xlData) {
    if(row[nameCol]) {
        // Strip spaces from names for robust matching
        const rawName = String(row[nameCol]).trim();
        const rawNum = String(row[numCol]).trim();
        // Remove spaces for comparison: "物流中心 地下一層平面圖" -> "物流中心地下一層平面圖"
        const compactName = rawName.replace(/\s+/g, '');
        // We can also remove half-width and full-width spaces
        const veryCompact = compactName.replace(/　/g, '');
        excelMap.set(veryCompact, { name: rawName, number: rawNum });
    }
}

// Compare
let changed = [];
let notFoundInExcel = [];
let unchanged = [];

for(const rs of revitSheets) {
    const revitNameCompact = rs.SheetName.replace(/\s+/g, '').replace(/　/g, '');
    if (excelMap.has(revitNameCompact)) {
        const xl = excelMap.get(revitNameCompact);
        
        if (rs.SheetNumber !== xl.number) {
            changed.push({
                Id: rs.ElementId,
                RevitName: rs.SheetName,
                CurrentNumber: rs.SheetNumber,
                TargetNumber: xl.number
            });
        } else {
            unchanged.push(rs);
        }
    } else {
        notFoundInExcel.push(rs);
    }
}

console.log(`\nRevit Sheets parsed: ${revitSheets.length}`);
console.log(`Excel Sheets parsed: ${xlData.length}`);
console.log(`\nResults:`);
console.log(`- Sheets matched and NEED UPDATE: ${changed.length}`);
console.log(`- Sheets matched and UNCHANGED: ${unchanged.length}`);
console.log(`- Revit Sheets NOT FOUND in Excel: ${notFoundInExcel.length}`);

// Dump the proposed changes to a file
fs.writeFileSync('E:/RevitMCP/scratch_csv/mismatch.json', JSON.stringify({
    summary: {
        totalRevit: revitSheets.length,
        totalExcel: xlData.length,
        needUpdate: changed.length,
        unchanged: unchanged.length,
        notFound: notFoundInExcel.length
    },
    changed: changed,
}, null, 2));

console.log("Details written to E:/RevitMCP/scratch_csv/mismatch.json");
