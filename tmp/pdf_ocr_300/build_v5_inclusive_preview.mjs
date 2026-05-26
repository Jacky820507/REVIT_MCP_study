import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const v4Path = path.join(__dirname, "detail_metadata_v4_preview.json");
const v5Path = path.join(__dirname, "detail_metadata_v5_preview.json");
const outputPath = path.join(__dirname, "detail_metadata_v5_inclusive_preview.json");
const reportPath = path.join(__dirname, "detail_metadata_v5_inclusive_review_report.md");
const allCsvPath = path.join(__dirname, "detail_metadata_v5_inclusive_all_types.csv");
const reviewCsvPath = path.join(__dirname, "detail_metadata_v5_inclusive_review_only.csv");

const v4 = JSON.parse(fs.readFileSync(v4Path, "utf8"));
const v5 = JSON.parse(fs.readFileSync(v5Path, "utf8"));

function normalizeText(value) {
  return String(value || "")
    .replace(/\s+/g, "")
    .replace(/[，、,]/g, ",")
    .replace(/[：:]/g, ":")
    .replace(/[（]/g, "(")
    .replace(/[）]/g, ")")
    .replace(/[·‧．。]/g, "")
    .toUpperCase();
}

function parseNumbers(value) {
  const nums = new Set();
  String(value || "")
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .forEach((part) => {
      const range = part.match(/^(\d+)\s*-\s*(\d+)$/);
      if (range) {
        const a = Number(range[1]);
        const b = Number(range[2]);
        for (let n = Math.min(a, b); n <= Math.max(a, b); n += 1) nums.add(n);
        return;
      }
      const n = Number(part);
      if (Number.isFinite(n)) nums.add(n);
    });
  return [...nums].sort((a, b) => a - b);
}

function intersects(a, b) {
  const bSet = new Set(b);
  return a.some((value) => bSet.has(value));
}

function formatNumbers(numbers) {
  const sorted = [...new Set(numbers.filter((value) => Number.isFinite(value)))].sort((a, b) => a - b);
  const parts = [];
  for (let i = 0; i < sorted.length; i += 1) {
    const start = sorted[i];
    let end = start;
    while (i + 1 < sorted.length && sorted[i + 1] === end + 1) {
      i += 1;
      end = sorted[i];
    }
    parts.push(start === end ? String(start) : `${start}-${end}`);
  }
  return parts.join(",");
}

function csv(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function toBaseItem(item, sourceMode, review, reviewReasons = []) {
  const detailNumbers = item.detailNumbers?.length ? item.detailNumbers : parseNumbers(item.detailNumber);
  const sourcePages = item.sourcePages?.length
    ? item.sourcePages
    : item.sourcePage
      ? [item.sourcePage]
      : [];
  const sourceModes = item.sourceModes?.length ? item.sourceModes : [sourceMode];
  const numberMethods = item.numberMethods?.length ? item.numberMethods : item.numberMethod ? [item.numberMethod] : [];
  const sheetNumber = item.sheetNumber;
  const sheetName = item.sheetName || "";
  const detailName = item.detailName || "";
  return {
    sheetNumber,
    sheetName,
    detailNumber: item.detailNumber,
    detailNumbers,
    detailName,
    typeName: `${sheetNumber}-${sheetName}-${detailName}`,
    sourcePages,
    sourceModes,
    numberMethods,
    review,
    reviewReasons,
    correctionReasons: item.correctionReasons || [],
    confidence: item.confidence || (review ? "review" : "medium"),
    originalItems: item.originalItems || [item],
  };
}

const v5Items = (v5.items || []).map((item) =>
  toBaseItem(
    item,
    item.sourceModes?.[0] || "v5",
    Boolean(item.review),
    item.reviewReasons || []
  )
);

const keptV4 = [];
for (const item of v4.items || []) {
  const v4Numbers = item.detailNumbers?.length ? item.detailNumbers : parseNumbers(item.detailNumber);
  const replacedByV5 = v5Items.some((candidate) => candidate.sheetNumber === item.sheetNumber && intersects(candidate.detailNumbers, v4Numbers));
  if (replacedByV5) continue;
  keptV4.push(
    toBaseItem(item, "v4_fallback", true, [
      "V5 未偵測到同圖紙同詳圖編號，使用 V4/OCR 候選補入，需人工查核",
    ])
  );
}

const mergedRaw = [...v5Items, ...keptV4];
const groupedMap = new Map();
for (const item of mergedRaw) {
  const key = `${item.sheetNumber}|${normalizeText(item.detailName)}`;
  let row = groupedMap.get(key);
  if (!row) {
    row = {
      sheetNumber: item.sheetNumber,
      sheetName: item.sheetName,
      detailName: item.detailName,
      detailNumbers: new Set(),
      sourcePages: new Set(),
      sourceModes: new Set(),
      numberMethods: new Set(),
      review: item.review,
      reviewReasons: new Set(),
      correctionReasons: new Set(),
      originalItems: [],
      confidence: item.confidence,
    };
    groupedMap.set(key, row);
  }

  for (const n of item.detailNumbers || parseNumbers(item.detailNumber)) row.detailNumbers.add(n);
  for (const page of item.sourcePages || []) row.sourcePages.add(page);
  for (const mode of item.sourceModes || []) row.sourceModes.add(mode);
  for (const method of item.numberMethods || []) row.numberMethods.add(method);
  for (const reason of item.reviewReasons || []) row.reviewReasons.add(reason);
  for (const reason of item.correctionReasons || []) row.correctionReasons.add(reason);
  row.review = row.review || item.review;
  row.originalItems.push(...(item.originalItems || [item]));
}

const merged = [...groupedMap.values()].map((row) => {
  const detailNumbers = [...row.detailNumbers].sort((a, b) => a - b);
  const detailNumber = formatNumbers(detailNumbers);
  return {
    sheetNumber: row.sheetNumber,
    sheetName: row.sheetName,
    detailNumber,
    detailNumbers,
    detailName: row.detailName,
    typeName: `${row.sheetNumber}-${row.sheetName}-${row.detailName}`,
    sourcePages: [...row.sourcePages].sort((a, b) => a - b),
    sourceModes: [...row.sourceModes].sort(),
    numberMethods: [...row.numberMethods].sort(),
    review: row.review,
    reviewReasons: [...row.reviewReasons].sort(),
    correctionReasons: [...row.correctionReasons].sort(),
    confidence: row.confidence || (row.review ? "review" : "medium"),
    originalItems: row.originalItems,
  };
}).sort((a, b) => {
  const sheetCompare = a.sheetNumber.localeCompare(b.sheetNumber);
  if (sheetCompare) return sheetCompare;
  return (a.detailNumbers[0] || 999) - (b.detailNumbers[0] || 999) || normalizeText(a.detailName).localeCompare(normalizeText(b.detailName));
});

const bySheetMap = new Map();
for (const item of merged) {
  const row = bySheetMap.get(item.sheetNumber) || {
    sheetNumber: item.sheetNumber,
    sheetName: item.sheetName,
    count: 0,
    reviewCount: 0,
    sourceModes: new Set(),
  };
  row.count += 1;
  if (item.review) row.reviewCount += 1;
  for (const mode of item.sourceModes) row.sourceModes.add(mode);
  bySheetMap.set(item.sheetNumber, row);
}

const bySheet = [...bySheetMap.values()]
  .map((row) => ({ ...row, sourceModes: [...row.sourceModes].sort() }))
  .sort((a, b) => a.sheetNumber.localeCompare(b.sheetNumber));

const reviewOnly = merged.filter((item) => item.review);
const preview = {
  sourcePdf: v5.sourcePdf || v4.sourcePdf,
  familyName: v5.familyName || v4.familyName,
  algorithm: "v5_inclusive_v5_primary_v4_fallback",
  generatedAt: new Date().toISOString(),
  counts: {
    v5Items: v5Items.length,
    v4FallbackItems: keptV4.length,
    rawMergedItems: mergedRaw.length,
    groupedItems: merged.length,
    reviewItems: reviewOnly.length,
  },
  bySheet,
  items: merged,
  reviewOnly,
};

fs.writeFileSync(outputPath, JSON.stringify(preview, null, 2), "utf8");

const rows = [["圖紙號碼", "圖紙名稱", "詳圖編號", "詳圖名稱", "類型名稱", "來源模式", "需複核", "複核原因"]];
for (const item of merged) {
  rows.push([
    item.sheetNumber,
    item.sheetName,
    item.detailNumber,
    item.detailName,
    item.typeName,
    item.sourceModes.join(","),
    item.review ? "是" : "否",
    item.reviewReasons.join("；"),
  ]);
}
fs.writeFileSync(allCsvPath, `\uFEFF${rows.map((row) => row.map(csv).join(",")).join("\n")}`, "utf8");

const reviewRows = rows.slice(0, 1);
for (const item of reviewOnly) {
  reviewRows.push([
    item.sheetNumber,
    item.sheetName,
    item.detailNumber,
    item.detailName,
    item.typeName,
    item.sourceModes.join(","),
    "是",
    item.reviewReasons.join("；"),
  ]);
}
fs.writeFileSync(reviewCsvPath, `\uFEFF${reviewRows.map((row) => row.map(csv).join(",")).join("\n")}`, "utf8");

const md = [];
md.push("# V5 Inclusive 詳圖項目 Preview");
md.push("");
md.push(`來源 PDF：${preview.sourcePdf}`);
md.push(`目標詳圖項目：${preview.familyName}`);
md.push("");
md.push("## 統計");
md.push("");
md.push(`- V5 優先項目：${preview.counts.v5Items}`);
md.push(`- V4 補洞項目：${preview.counts.v4FallbackItems}`);
md.push(`- 合併後類型：${preview.counts.groupedItems}`);
md.push(`- 需複核：${preview.counts.reviewItems}`);
md.push("");
md.push("## 圖紙彙總");
md.push("");
md.push("| 圖紙號碼 | 圖紙名稱 | 類型數 | 需複核 | 來源模式 |");
md.push("|---|---|---:|---:|---|");
for (const row of bySheet) {
  md.push(`| ${row.sheetNumber} | ${row.sheetName} | ${row.count} | ${row.reviewCount} | ${row.sourceModes.join(",")} |`);
}
md.push("");
md.push("## 需複核項目");
md.push("");
md.push("| 圖紙號碼 | 詳圖編號 | 詳圖名稱 | 來源模式 | 複核原因 |");
md.push("|---|---:|---|---|---|");
for (const item of reviewOnly) {
  md.push(`| ${item.sheetNumber} | ${item.detailNumber} | ${item.detailName} | ${item.sourceModes.join(",")} | ${item.reviewReasons.join("；")} |`);
}
fs.writeFileSync(reportPath, md.join("\n"), "utf8");

console.log(
  JSON.stringify(
    {
      preview: outputPath,
      report: reportPath,
      allCsv: allCsvPath,
      reviewCsv: reviewCsvPath,
      counts: preview.counts,
    },
    null,
    2
  )
);
