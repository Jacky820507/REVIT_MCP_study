import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { RevitSocketClient } from "../../MCP-Server/build/socket.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const previewPath = path.join(__dirname, "detail_metadata_v4_preview.json");
const reviewPath = path.join(__dirname, "detail_metadata_v4_missing_preview.json");
const outputPath = path.join(__dirname, "v4_all_apply_result.json");
const progressPath = path.join(__dirname, "v4_all_apply_progress.json");

const preview = JSON.parse(fs.readFileSync(previewPath, "utf8"));
const review = JSON.parse(fs.readFileSync(reviewPath, "utf8"));
const familyName = preview.familyName;

const reviewKeys = new Set(
  (review.reviewOnly || []).map((item) => `${item.sheetNumber}|${item.detailNumber}|${item.detailName}`)
);

const allItems = preview.items.map((item) => ({
  sheetNumber: item.sheetNumber,
  sheetName: item.sheetName,
  detailNumber: item.detailNumber,
  detailName: item.detailName,
  reviewStatus: reviewKeys.has(`${item.sheetNumber}|${item.detailNumber}|${item.detailName}`)
    ? "review"
    : "normal",
}));

const batchSize = 20;
const batches = [];
for (let i = 0; i < allItems.length; i += batchSize) {
  batches.push(allItems.slice(i, i + batchSize));
}

const client = new RevitSocketClient();
const results = [];
const counts = {};

function writeProgress(extra = {}) {
  fs.writeFileSync(
    progressPath,
    JSON.stringify(
      {
        familyName,
        totalInput: allItems.length,
        batchSize,
        totalBatches: batches.length,
        completedBatches: results.length,
        counts,
        updatedAt: new Date().toISOString(),
        ...extra,
      },
      null,
      2
    ),
    "utf8"
  );
}

function countAction(action) {
  counts[action] = (counts[action] || 0) + 1;
}

writeProgress({ status: "starting" });

try {
  await client.connect();
  writeProgress({ status: "connected" });

  for (let index = 0; index < batches.length; index += 1) {
    const batchItems = batches[index];
    writeProgress({
      status: "running",
      currentBatch: index + 1,
      currentBatchInputCount: batchItems.length,
      currentBatchFirstItem: batchItems[0],
    });

    const response = await client.sendCommand("create_detail_component_types_from_metadata", {
      familyName,
      dryRun: false,
      overwriteExisting: true,
      items: batchItems.map(({ reviewStatus, ...item }) => item),
    });

    const data = response.data || response.Data || response;
    const appliedItems = data.Items || data.items || [];
    for (const applied of appliedItems) {
      countAction(applied.Action || applied.action || "unknown");
    }

    results.push({
      batch: index + 1,
      inputCount: batchItems.length,
      reviewCount: batchItems.filter((item) => item.reviewStatus === "review").length,
      response: data,
    });

    writeProgress({
      status: "running",
      currentBatch: index + 1,
      lastBatchResult: {
        success: data.Success,
        count: data.Count,
        created: data.Created,
        updated: data.Updated,
        skipped: data.Skipped,
        invalid: data.Invalid,
      },
    });
  }

  const finalResult = {
    familyName,
    dryRun: false,
    totalInput: allItems.length,
    reviewInput: allItems.filter((item) => item.reviewStatus === "review").length,
    normalInput: allItems.filter((item) => item.reviewStatus !== "review").length,
    batchSize,
    counts,
    results,
    completedAt: new Date().toISOString(),
  };

  fs.writeFileSync(outputPath, JSON.stringify(finalResult, null, 2), "utf8");
  writeProgress({ status: "completed", outputPath });
  console.log(JSON.stringify({ done: true, totalInput: allItems.length, counts }));
} catch (error) {
  const failedResult = {
    familyName,
    dryRun: false,
    totalInput: allItems.length,
    batchSize,
    counts,
    results,
    error: String(error),
    failedAt: new Date().toISOString(),
  };

  fs.writeFileSync(outputPath, JSON.stringify(failedResult, null, 2), "utf8");
  writeProgress({ status: "failed", error: String(error), outputPath });
  console.error(error);
  process.exitCode = 1;
} finally {
  client.disconnect();
}
