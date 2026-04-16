const fs = require('fs');
const data = JSON.parse(fs.readFileSync('mismatch.json', 'utf8'));

let md = `# 圖紙清單比對結果\n\n`;
md += `## 摘要\n`;
md += `- Revit 專案中現有圖紙總數：**${data.summary.totalRevit}**\n`;
md += `- Excel 表格中讀取到的圖紙總數：**${data.summary.totalExcel}**\n\n`;
md += `### 比對情況\n`;
md += `- ✅ 名稱相符且需要更新編號的圖紙：**${data.summary.needUpdate}** 張\n`;
md += `- ⚪ 名稱相符且編號已正確（無需更新）：**${data.summary.unchanged}** 張\n`;
md += `- ❌ 在 Excel 中找不到對應名稱的 Revit 圖紙：**${data.summary.notFound}** 張\n\n`;

md += `## 📝 需要更新編號的圖紙清單 (共 ${data.changed.length} 張)\n\n`;
md += `| Revit 圖紙名稱 | 目前編號 | 目標編號 (來自 Excel) |\n`;
md += `|:---|:---|:---|\n`;

// Only show first 50 as preview or all? Let's show all since it's an artifact.
data.changed.forEach(item => {
    md += `| ${item.RevitName} | \`${item.CurrentNumber}\` | \`${item.TargetNumber}\` |\n`;
});

md += `\n\n---`;

fs.writeFileSync('C:/Users/09044/.gemini/antigravity/brain/811df5b4-39b7-4436-9181-c20c8887a752/compare_result.md', md);
console.log("Markdown result generated.");
