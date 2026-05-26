import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { RevitSocketClient } from "../../MCP-Server/build/socket.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const previewPath = path.join(__dirname, "detail_metadata_v4_missing_preview.json");
const outputPath = path.join(__dirname, "v4_recommended_apply_result.json");

const preview = JSON.parse(fs.readFileSync(previewPath, "utf8"));
const familyName = preview.familyName;
const allItems = preview.recommendedForImport.map((item) => ({
  sheetNumber: item.sheetNumber,
  sheetName: item.sheetName,
  detailNumber: item.detailNumber,
  detailName: item.detailName,
}));

const client = new RevitSocketClient();
const batches = [];
const batchSize = 20;
for (let i = 0; i < allItems.length; i += batchSize) {
  batches.push(allItems.slice(i, i + batchSize));
}

const results = [];
const counts = {};

function countAction(action) {
  counts[action] = (counts[action] || 0) + 1;
}

try {
  await client.connect();

  for (let index = 0; index < batches.length; index += 1) {
    const items = batches[index];
    const response = await client.sendCommand("create_detail_component_types_from_metadata", {
      familyName,
      dryRun: false,
      overwriteExisting: true,
      items,
    });

    const data = response.data || response.Data || response;
    const appliedItems = data.Items || data.items || [];
    for (const applied of appliedItems) {
      countAction(applied.Action || applied.action || "unknown");
    }

    results.push({
      batch: index + 1,
      inputCount: items.length,
      response: data,
    });

    console.log(
      JSON.stringify({
        batch: index + 1,
        inputCount: items.length,
        success: data.Success,
        created: data.Created,
        updated: data.Updated,
        skipped: data.Skipped,
        invalid: data.Invalid,
      })
    );
  }

  fs.writeFileSync(
    outputPath,
    JSON.stringify(
      {
        familyName,
        dryRun: false,
        totalInput: allItems.length,
        batchSize,
        counts,
        results,
        completedAt: new Date().toISOString(),
      },
      null,
      2
    ),
    "utf8"
  );

  console.log(JSON.stringify({ done: true, totalInput: allItems.length, counts }));
} catch (error) {
  fs.writeFileSync(
    outputPath,
    JSON.stringify(
      {
        familyName,
        dryRun: false,
        totalInput: allItems.length,
        batchSize,
        counts,
        results,
        error: String(error),
        failedAt: new Date().toISOString(),
      },
      null,
      2
    ),
    "utf8"
  );

  console.error(error);
  process.exitCode = 1;
} finally {
  client.disconnect();
}
