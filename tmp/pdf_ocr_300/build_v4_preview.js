const fs = require("fs");
const path = require("path");

const baseDir = __dirname;
const v2 = JSON.parse(fs.readFileSync(path.join(baseDir, "detail_metadata_v2_calibrated_preview.json"), "utf8"));
const v3 = JSON.parse(fs.readFileSync(path.join(baseDir, "detail_metadata_v3_calibrated_preview.json"), "utf8"));

const knownCorrections = new Map([
  [
    "ARB-D09002|5",
    {
      detailName: "3F,5F碼頭區排水溝/地坪覆面層/防水層詳圖",
      reason: "user_feedback_prefix_recovery",
    },
  ],
  [
    "ARB-D09018|4",
    {
      detailName: "C3,C9鋁企口天花板安裝示意圖",
      reason: "user_feedback_merge_same_title",
    },
  ],
  [
    "ARB-D09018|5",
    {
      detailName: "C3,C9鋁企口天花板安裝示意圖",
      reason: "user_feedback_merge_same_title",
    },
  ],
]);

const ocrTextCorrections = [
  ["地坏", "地坪"],
  ["郚", "部"],
  ["隔屛", "隔屏"],
  ["維俢", "維修"],
  ["攔杆", "欄杆"],
  ["嬁", "燈"],
  ["哋面", "地面"],
  ["灻樣", "大樣"],
];

function correctOcrText(value) {
  let text = String(value || "");
  for (const [from, to] of ocrTextCorrections) {
    text = text.split(from).join(to);
  }
  return text;
}

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

function formatNumbers(numbers) {
  const sorted = [...new Set(numbers)].sort((a, b) => a - b);
  const ranges = [];
  for (let i = 0; i < sorted.length; i += 1) {
    const start = sorted[i];
    let end = start;
    while (sorted[i + 1] === end + 1) {
      i += 1;
      end = sorted[i];
    }
    ranges.push(start === end ? String(start) : `${start}-${end}`);
  }
  return ranges.join(",");
}

function applyKnownCorrection(item) {
  const numbers = parseNumbers(item.detailNumber);
  let corrected = {
    ...item,
    sheetName: correctOcrText(item.sheetName),
    detailName: correctOcrText(item.detailName),
  };
  const applied = [];
  if (numbers.length === 1) {
    const correction = knownCorrections.get(`${item.sheetNumber}|${numbers[0]}`);
    if (correction) {
      corrected.detailName = correction.detailName;
      applied.push(correction.reason);
    }
  }
  return { ...corrected, correctionReasons: applied };
}

function itemNumbers(item) {
  return parseNumbers(item.detailNumber);
}

function noteLike(detailName) {
  const text = normalizeText(detailName);
  const notePatterns = [
    "本圖為",
    "僅供參考",
    "承商",
    "不得低於",
    "施工前",
    "依圖說厚度",
    "防火區劃",
    "符合設計",
    "內政",
    "安裝之確實位置",
    "現場監工",
  ];
  return notePatterns.some((p) => text.includes(normalizeText(p)));
}

function hasDetailKeyword(detailName) {
  const text = normalizeText(detailName);
  const keywords = [
    "詳圖",
    "示意圖",
    "剖面圖",
    "平面圖",
    "立面圖",
    "大樣圖",
    "詳剖",
    "收頭圖",
    "組合圖",
    "安裝",
    "剖面",
    "平面",
    "立面",
    "大樣",
    "基座",
    "扶手",
    "欄杆",
    "人孔",
    "排水",
    "防水",
    "水箱",
    "門板",
    "底框",
    "邊框",
    "接頭",
    "結構圖",
  ];
  return keywords.some((p) => text.includes(normalizeText(p)));
}

function confidenceFor(group) {
  if (group.sources.some((s) => s.startsWith("revit_manual_reference"))) return "existing_manual";
  if (group.correctionReasons.length > 0) return "high_correction";
  if (group.currentStatus === "alreadyExists") return "existing";
  if (noteLike(group.detailName)) return "low_note_like";
  if (hasDetailKeyword(group.detailName)) return "medium";
  return "low";
}

function groupItems(items, options = {}) {
  const { applyCorrections = true } = options;
  const groups = new Map();
  for (const raw of items) {
    const item = applyCorrections ? applyKnownCorrection(raw) : { ...raw, correctionReasons: [] };
    const key = `${item.sheetNumber}|${normalizeText(item.detailName)}`;
    if (!groups.has(key)) {
      groups.set(key, {
        sheetNumber: item.sheetNumber,
        sheetName: item.sheetName,
        detailName: item.detailName,
        numberSet: new Set(),
        sourcePages: new Set(),
        sources: new Set(),
        originalItems: [],
        correctionReasons: new Set(item.correctionReasons || []),
      });
    }
    const group = groups.get(key);
    for (const n of itemNumbers(item)) group.numberSet.add(n);
    if (item.sourcePage) group.sourcePages.add(item.sourcePage);
    if (item.source) group.sources.add(item.source);
    for (const reason of item.correctionReasons || []) group.correctionReasons.add(reason);
    group.originalItems.push({
      sheetNumber: item.sheetNumber,
      detailNumber: item.detailNumber,
      detailName: item.detailName,
      source: item.source,
      sourcePage: item.sourcePage,
    });
  }

  return [...groups.values()].map((group) => {
    const numbers = [...group.numberSet].sort((a, b) => a - b);
    return {
      sheetNumber: group.sheetNumber,
      sheetName: group.sheetName,
      detailNumber: formatNumbers(numbers),
      detailNumbers: numbers,
      detailName: group.detailName,
      typeName: `${group.sheetNumber}-${group.sheetName}-${group.detailName}`,
      sourcePages: [...group.sourcePages].sort((a, b) => a - b),
      sources: [...group.sources].sort(),
      correctionReasons: [...group.correctionReasons].sort(),
      originalItems: group.originalItems,
    };
  });
}

const v4Items = groupItems(v2.items, { applyCorrections: true });
const currentGroups = groupItems(v3.items, { applyCorrections: false });

const currentBySheetNumber = new Map();
const currentBySheetName = new Map();
for (const group of currentGroups) {
  for (const n of group.detailNumbers) {
    const numberKey = `${group.sheetNumber}|${n}`;
    if (!currentBySheetNumber.has(numberKey)) currentBySheetNumber.set(numberKey, []);
    currentBySheetNumber.get(numberKey).push(group);
  }
  currentBySheetName.set(`${group.sheetNumber}|${normalizeText(group.detailName)}`, group);
}

function statusFor(group) {
  const sameName = currentBySheetName.get(`${group.sheetNumber}|${normalizeText(group.detailName)}`);
  if (sameName) {
    const covered = group.detailNumbers.every((n) => sameName.detailNumbers.includes(n));
    if (covered) return { status: "alreadyExists", relatedCurrent: [sameName.typeName] };
  }

  const related = [];
  for (const n of group.detailNumbers) {
    for (const current of currentBySheetNumber.get(`${group.sheetNumber}|${n}`) || []) {
      related.push(current.typeName);
    }
  }

  if (related.length > 0) {
    return {
      status: group.detailNumbers.length > 1 ? "mergeOrCorrectExisting" : "correctExisting",
      relatedCurrent: [...new Set(related)],
    };
  }

  return { status: "missingAdd", relatedCurrent: [] };
}

for (const group of v4Items) {
  const { status, relatedCurrent } = statusFor(group);
  group.currentStatus = status;
  group.relatedCurrentTypes = relatedCurrent;
  group.confidence = confidenceFor(group);
  group.recommendedForImport =
    status !== "alreadyExists" &&
    !group.confidence.startsWith("low") &&
    group.confidence !== "existing_manual" &&
    group.confidence !== "existing";
}

const missingOrCorrection = v4Items.filter((item) => item.currentStatus !== "alreadyExists");
const recommended = missingOrCorrection.filter((item) => item.recommendedForImport);
const reviewOnly = missingOrCorrection.filter((item) => !item.recommendedForImport);

function bySheetCounts(items) {
  const counts = {};
  for (const item of items) counts[item.sheetNumber] = (counts[item.sheetNumber] || 0) + 1;
  return Object.fromEntries(Object.entries(counts).sort(([a], [b]) => a.localeCompare(b)));
}

const preview = {
  sourcePdf: v2.sourcePdf,
  familyName: "AE-圖號詳圖編號標頭-3.5mm",
  algorithm: "v4_preview_from_v2_plus_user_corrections_grouped",
  generatedAt: new Date().toISOString(),
  counts: {
    v2InputItems: v2.items.length,
    v3CurrentInputItems: v3.items.length,
    v4GroupedItems: v4Items.length,
    currentGroups: currentGroups.length,
    missingOrCorrection: missingOrCorrection.length,
    recommendedForImport: recommended.length,
    reviewOnly: reviewOnly.length,
  },
  byStatus: bySheetCounts(missingOrCorrection),
  items: v4Items,
  missingOrCorrection,
  recommendedForImport: recommended,
  reviewOnly,
};

fs.writeFileSync(path.join(baseDir, "detail_metadata_v4_preview.json"), JSON.stringify(preview, null, 2), "utf8");
fs.writeFileSync(path.join(baseDir, "detail_metadata_v4_missing_preview.json"), JSON.stringify({
  ...preview,
  items: undefined,
  missingOrCorrection,
  recommendedForImport: recommended,
  reviewOnly,
}, null, 2), "utf8");

const lines = [];
lines.push(`v2_input_items=${v2.items.length}`);
lines.push(`v3_current_items=${v3.items.length}`);
lines.push(`v4_grouped_items=${v4Items.length}`);
lines.push(`missing_or_correction=${missingOrCorrection.length}`);
lines.push(`recommended_for_import=${recommended.length}`);
lines.push(`review_only=${reviewOnly.length}`);
lines.push("");
lines.push("[recommended_for_import_by_sheet]");
for (const [sheet, count] of Object.entries(bySheetCounts(recommended))) lines.push(`${sheet}: ${count}`);
lines.push("");
lines.push("[recommended_for_import]");
for (const item of recommended) {
  lines.push(`${item.sheetNumber} ${item.detailNumber}. ${item.detailName} | ${item.currentStatus} | ${item.confidence}`);
  if (item.relatedCurrentTypes.length > 0) {
    for (const related of item.relatedCurrentTypes) lines.push(`  current: ${related}`);
  }
}
lines.push("");
lines.push("[review_only]");
for (const item of reviewOnly) {
  lines.push(`${item.sheetNumber} ${item.detailNumber}. ${item.detailName} | ${item.currentStatus} | ${item.confidence}`);
}
fs.writeFileSync(path.join(baseDir, "detail_metadata_v4_missing_summary.txt"), lines.join("\n"), "utf8");

console.log(JSON.stringify(preview.counts, null, 2));
