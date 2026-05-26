import { RevitSocketClient } from './build/socket.js';

const dryRun = process.argv.includes('--dry-run');
const prefixPattern = /^ARB-D07\d{3}$/;
const insertionPattern = /^(ARB-D07\d{3})-1$/;

function incrementSheetNumber(value) {
  const match = value.match(/^(.*?)(\d+)$/);
  if (!match) throw new Error(`Cannot increment sheet number: ${value}`);
  const [, prefix, digits] = match;
  const next = String(Number(digits) + 1).padStart(digits.length, '0');
  return `${prefix}${next}`;
}

async function main() {
  const client = new RevitSocketClient();
  await client.connect();

  try {
    const res = await client.sendCommand('get_all_sheets', {});
    if (!res.success) throw new Error(res.error || 'get_all_sheets failed');

    const allSheets = res.data.Sheets;
    const byNumber = new Map(allSheets.map((sheet) => [sheet.SheetNumber, sheet]));
    const insertions = allSheets
      .filter((sheet) => insertionPattern.test(sheet.SheetNumber))
      .sort((a, b) => a.SheetNumber.localeCompare(b.SheetNumber));

    const moves = new Map();
    for (const insertion of insertions) {
      const baseNumber = insertion.SheetNumber.match(insertionPattern)[1];
      let targetNumber = incrementSheetNumber(baseNumber);
      let mover = insertion;

      while (true) {
        if (!prefixPattern.test(targetNumber)) {
          throw new Error(`Refusing to move outside ARB-D07### range: ${targetNumber}`);
        }

        moves.set(mover.ElementId, {
          id: mover.ElementId,
          from: mover.SheetNumber,
          to: targetNumber,
          name: mover.SheetName,
        });

        const occupier = byNumber.get(targetNumber);
        if (!occupier || moves.has(occupier.ElementId)) break;

        mover = occupier;
        targetNumber = incrementSheetNumber(targetNumber);
      }
    }

    const moveList = [...moves.values()].sort((a, b) => a.to.localeCompare(b.to));
    console.log(JSON.stringify({ dryRun, insertionCount: insertions.length, moveCount: moveList.length, moves: moveList }, null, 2));

    if (dryRun || moveList.length === 0) return;

    for (const move of moveList) {
      const tempValue = `TMP-D07-${move.id}`;
      const tempRes = await client.sendCommand('modify_element_parameter', {
        elementId: move.id,
        parameterName: 'Sheet Number',
        value: tempValue,
      });
      if (!tempRes.success) throw new Error(`Temp rename failed for ${move.from}: ${tempRes.error}`);
    }

    for (const move of moveList) {
      const finalRes = await client.sendCommand('modify_element_parameter', {
        elementId: move.id,
        parameterName: 'Sheet Number',
        value: move.to,
      });
      if (!finalRes.success) throw new Error(`Final rename failed for ${move.from} -> ${move.to}: ${finalRes.error}`);
    }

    console.log(`Applied ${moveList.length} ARB-D07 sheet renumber moves.`);
  } finally {
    client.disconnect();
  }
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
