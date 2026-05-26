import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const preview = JSON.parse(fs.readFileSync(path.join(__dirname, "detail_metadata_v4_preview.json"), "utf8"));
const review = JSON.parse(fs.readFileSync(path.join(__dirname, "detail_metadata_v4_missing_preview.json"), "utf8"));
const progress = JSON.parse(fs.readFileSync(path.join(__dirname, "v4_all_apply_progress.json"), "utf8"));
const result = JSON.parse(fs.readFileSync(path.join(__dirname, "v4_all_apply_result.json"), "utf8"));

const items = preview.items || [];
const reviewItems = review.reviewOnly || [];

function esc(value) {
  return String(value ?? "").replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
}

function csv(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function sourcePages(item) {
  return (item.sourcePages || []).join(", ");
}

function reviewReason(item) {
  const reasons = [];
  if (item.confidence === "low") reasons.push("低信心：名稱缺少常見詳圖/剖面/平面等關鍵字，或可能是 OCR 誤判");
  if (item.confidence === "low_note_like") reasons.push("低信心：內容像一般註記，可能不是詳圖名稱");
  if ((item.correctionReasons || []).length) reasons.push(`已套用修正：${item.correctionReasons.join(", ")}`);
  if (!reasons.length) reasons.push("建議人工確認");
  return reasons.join("；");
}

function reviewKey(item) {
  return `${item.sheetNumber}|${item.detailNumber}|${item.detailName}`;
}

const reviewKeys = new Set(reviewItems.map(reviewKey));
const bySheet = new Map();
for (const item of items) {
  const row = bySheet.get(item.sheetNumber) || {
    sheetNumber: item.sheetNumber,
    sheetName: item.sheetName,
    total: 0,
    review: 0,
    pages: new Set(),
  };
  row.total += 1;
  if (reviewKeys.has(reviewKey(item))) row.review += 1;
  for (const p of item.sourcePages || []) row.pages.add(p);
  bySheet.set(item.sheetNumber, row);
}

const sheetRows = [...bySheet.values()].sort((a, b) => a.sheetNumber.localeCompare(b.sheetNumber));
const confidenceCounts = items.reduce((acc, item) => {
  const key = item.confidence || "unknown";
  acc[key] = (acc[key] || 0) + 1;
  return acc;
}, {});
const knownCorrections = items.filter((item) => (item.correctionReasons || []).length > 0);

const confidenceLabels = {
  existing_manual: "沿用/參考既有人工修正資料",
  high_correction: "已套用明確人工回饋修正",
  medium: "名稱含常見詳圖關鍵字，建議仍抽查",
  low: "低信心，建議人工查核",
  low_note_like: "疑似一般註記，建議人工查核",
  existing: "既有項目",
};

const md = [];
md.push("# 大樣詳圖ALL.pdf V4 詳圖項目建立結果整理");
md.push("");
md.push(`產生時間：${new Date().toLocaleString("zh-TW", { timeZone: "Asia/Taipei", hour12: false })}`);
md.push(`來源 PDF：${preview.sourcePdf}`);
md.push(`目標詳圖項目：${preview.familyName}`);
md.push("");
md.push("## 執行結果");
md.push("");
md.push(`- Revit 寫入狀態：${progress.status}`);
md.push(`- 本次輸入類型：${result.totalInput}`);
md.push(`- 成功建立：${result.counts?.created ?? 0}`);
md.push(`- 一般項目：${result.normalInput}`);
md.push(`- OCR 疑慮項目：${result.reviewInput}`);
md.push(`- 批次大小：${result.batchSize}`);
md.push("");
md.push("## 信心分類");
md.push("");
md.push("| 分類 | 數量 | 說明 |");
md.push("|---|---:|---|");
for (const [key, count] of Object.entries(confidenceCounts).sort((a, b) => b[1] - a[1])) {
  md.push(`| ${esc(key)} | ${count} | ${esc(confidenceLabels[key] || "")} |`);
}
md.push("");
md.push("## 圖紙彙總");
md.push("");
md.push("| 圖紙號碼 | 圖紙名稱 | 建立類型數 | 需複核 | PDF頁碼 |");
md.push("|---|---|---:|---:|---|");
for (const row of sheetRows) {
  md.push(
    `| ${esc(row.sheetNumber)} | ${esc(row.sheetName)} | ${row.total} | ${row.review} | ${esc(
      [...row.pages].sort((a, b) => a - b).join(", ")
    )} |`
  );
}
md.push("");
md.push("## 需要人工複核的 OCR 疑慮項目");
md.push("");
md.push("這些類型已經依照你的要求先建立到 Revit；此表只做為後續人工查核與修正依據。");
md.push("");
md.push("| 圖紙號碼 | 圖紙名稱 | 詳圖編號 | 目前詳圖名稱 | 信心 | PDF頁碼 | 建議查核原因 |");
md.push("|---|---|---|---|---|---|---|");
for (const item of reviewItems) {
  md.push(
    `| ${esc(item.sheetNumber)} | ${esc(item.sheetName)} | ${esc(item.detailNumber)} | ${esc(
      item.detailName
    )} | ${esc(item.confidence)} | ${esc(sourcePages(item))} | ${esc(reviewReason(item))} |`
  );
}
md.push("");
md.push("## 已套用的人工回饋修正");
md.push("");
if (!knownCorrections.length) {
  md.push("無。");
} else {
  md.push("| 圖紙號碼 | 詳圖編號 | 詳圖名稱 | 修正來源 |");
  md.push("|---|---|---|---|");
  for (const item of knownCorrections) {
    md.push(
      `| ${esc(item.sheetNumber)} | ${esc(item.detailNumber)} | ${esc(item.detailName)} | ${esc(
        (item.correctionReasons || []).join(", ")
      )} |`
    );
  }
}
md.push("");
md.push("## 後續建議");
md.push("");
md.push("1. 優先核對「需要人工複核的 OCR 疑慮項目」表。");
md.push("2. 若確認某筆名稱錯誤，可回饋「圖紙號碼 + 詳圖編號 + 正確詳圖名稱」，再批次修正 Revit 類型參數與類型名稱。");
md.push("3. 下一版 OCR 規則可把確認過的常見錯字加入修正字典，但避免把單一圖號硬寫成特殊規則。");

fs.writeFileSync(path.join(__dirname, "detail_metadata_v4_review_report.md"), md.join("\n"), "utf8");

const allCsvRows = [["圖紙號碼", "圖紙名稱", "詳圖編號", "詳圖名稱", "類型名稱", "信心", "需複核", "PDF頁碼", "來源"]];
for (const item of items) {
  allCsvRows.push([
    item.sheetNumber,
    item.sheetName,
    item.detailNumber,
    item.detailName,
    item.typeName,
    item.confidence,
    reviewKeys.has(reviewKey(item)) ? "是" : "否",
    sourcePages(item),
    (item.sources || []).join(";"),
  ]);
}
fs.writeFileSync(
  path.join(__dirname, "detail_metadata_v4_all_created_types.csv"),
  `\uFEFF${allCsvRows.map((r) => r.map(csv).join(",")).join("\n")}`,
  "utf8"
);

const reviewCsvRows = [["圖紙號碼", "圖紙名稱", "詳圖編號", "目前詳圖名稱", "信心", "PDF頁碼", "建議查核原因", "類型名稱"]];
for (const item of reviewItems) {
  reviewCsvRows.push([
    item.sheetNumber,
    item.sheetName,
    item.detailNumber,
    item.detailName,
    item.confidence,
    sourcePages(item),
    reviewReason(item),
    item.typeName,
  ]);
}
fs.writeFileSync(
  path.join(__dirname, "detail_metadata_v4_review_only.csv"),
  `\uFEFF${reviewCsvRows.map((r) => r.map(csv).join(",")).join("\n")}`,
  "utf8"
);

console.log(
  JSON.stringify(
    {
      report: path.join(__dirname, "detail_metadata_v4_review_report.md"),
      allCsv: path.join(__dirname, "detail_metadata_v4_all_created_types.csv"),
      reviewCsv: path.join(__dirname, "detail_metadata_v4_review_only.csv"),
      total: items.length,
      review: reviewItems.length,
      sheets: sheetRows.length,
    },
    null,
    2
  )
);
