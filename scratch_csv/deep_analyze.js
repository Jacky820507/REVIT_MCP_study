const xlsx = require('xlsx');
const fs = require('fs');

// Read Revit sheets
const revitSheetsPath = 'C:/Users/09044/.gemini/antigravity/brain/811df5b4-39b7-4436-9181-c20c8887a752/.system_generated/steps/27/output.txt'; 
const revitData = JSON.parse(fs.readFileSync(revitSheetsPath, 'utf8'));
const revitSheets = revitData.Sheets;

// Read Excel
const workbook = xlsx.readFile('E:/RevitMCP/B-Sheets.xlsx');
const sheetName = workbook.SheetNames[0];
const xlData = xlsx.utils.sheet_to_json(workbook.Sheets[sheetName], { defval: "" });

const headers = Object.keys(xlData[0]);
let numCol = headers[0];
let nameCol = headers[1];

const excelItems = xlData.map(row => ({
    name: String(row[nameCol] || "").trim(),
    number: String(row[numCol] || "").trim(),
    cleanName: String(row[nameCol] || "").replace(/\s+/g, '').replace(/　/g, '')
}));

// Find unmatched
const exactMatchesIds = new Set();
const exactMatches = [];
for(const rs of revitSheets) {
    const rClean = rs.SheetName.replace(/\s+/g, '').replace(/　/g, '');
    const found = excelItems.find(x => x.cleanName === rClean);
    if(found) {
        exactMatchesIds.add(rs.ElementId);
    }
}

const unmatchedRevit = revitSheets.filter(rs => !exactMatchesIds.has(rs.ElementId));

const analysisResults = [];

for(const rs of unmatchedRevit) {
    const rName = rs.SheetName;
    const rClean = rName.replace(/\s+/g, '').replace(/　/g, '');
    
    // Pattern 1: Strip common suffixes from Revit Name (-1, -A, (1), etc)
    const strippedName = rName.replace(/[-\s]\d+$/g, '').replace(/\(\d+\)$/g, '').trim();
    const strippedClean = strippedName.replace(/\s+/g, '').replace(/　/g, '');

    // Pattern 2: Revit Name contains Excel Name or vice-versa
    let candidates = [];

    for(const xl of excelItems) {
        // If stripped name matches excel exactly
        if (xl.cleanName === strippedClean) {
            candidates.push({ ...xl, reason: 'Stripped Suffix Match' });
            continue;
        }

        // If Revit contains Excel or Excel contains Revit (long common substring)
        if (xl.cleanName.length > 4 && (rClean.includes(xl.cleanName) || xl.cleanName.includes(rClean))) {
            candidates.push({ ...xl, reason: 'Partial String Match' });
            continue;
        }
    }

    // Sort candidates: Stripped hits first
    candidates.sort((a, b) => (a.reason === 'Stripped Suffix Match' ? -1 : 1));

    analysisResults.push({
        revit: rs,
        candidates: candidates.slice(0, 3) // Top 3
    });
}

// Generate report
let md = `# ❓ 未匹配圖紙深層分析報告\n\n`;
md += `我們針對在 Excel 中找不到精確名稱的 **${unmatchedRevit.length}** 張圖紙進行了模式比對，以下是分析結果：\n\n`;

const suffixMatches = analysisResults.filter(r => r.candidates.some(c => c.reason === 'Stripped Suffix Match'));
const partialMatches = analysisResults.filter(r => r.candidates.length > 0 && !r.candidates.some(c => c.reason === 'Stripped Suffix Match'));
const noMatches = analysisResults.filter(r => r.candidates.length === 0);

md += `### 💡 統計分類\n`;
md += `- **[類別 A] 帶有後綴的圖紙**: **${suffixMatches.length}** 張 (例如 ` + "`名稱-1`" + ` 匹配到 ` + "`名稱`" + `)\n`;
md += `- **[類別 B] 部分名稱相似**: **${partialMatches.length}** 張 (包含子字串)\n`;
md += `- **[類別 C] 完全無頭緒**: **${noMatches.length}** 張\n\n`;

md += `## 🚀 [類別 A] 帶有後綴的建議 (前 20 筆)\n`;
md += `這類通常就是您提到的過期圖紙，建議直接對進去。\n\n`;
md += `| Revit 圖紙名稱 | 目前編號 | 建議匹配 Excel 名稱 | 建議更新編號 |\n`;
md += `|:---|:---|:---|:---|\n`;
suffixMatches.slice(0, 20).forEach(r => {
    const c = r.candidates.find(ci => ci.reason === 'Stripped Suffix Match');
    md += `| ${r.revit.SheetName} | \`${r.revit.SheetNumber}\` | ${c.name} | \`${c.number}\` |\n`;
});

md += `\n## 🔍 [類別 B] 名稱相似但需人工檢查 (前 20 筆)\n`;
md += `這類名稱可能有多寫一些字或描述略有不同。\n\n`;
md += `| Revit 圖紙名稱 | 目前編號 | 潛在對應 Excel 名稱 | 候選編號 |\n`;
md += `|:---|:---|:---|:---|\n`;
partialMatches.slice(0, 20).forEach(r => {
    const c = r.candidates[0];
    md += `| ${r.revit.SheetName} | \`${r.revit.SheetNumber}\` | ${c.name} | \`${c.number}\` |\n`;
});

md += `\n## 🛑 [類別 C] 完全找不到的圖紙 (前 20 筆)\n`;
md += `這些圖紙完全不在 B-Sheets.xlsx 的清單中，建議人工移除或保留。\n\n`;
md += `| Revit 圖紙名稱 | 目前編號 |\n`;
md += `|:---|:---|\n`;
noMatches.slice(0, 20).forEach(r => {
    md += `| ${r.revit.SheetName} | \`${r.revit.SheetNumber}\` |\n`;
});

fs.writeFileSync('C:/Users/09044/.gemini/antigravity/brain/811df5b4-39b7-4436-9181-c20c8887a752/unmatched_analysis.md', md);
console.log("Analysis completed.");
