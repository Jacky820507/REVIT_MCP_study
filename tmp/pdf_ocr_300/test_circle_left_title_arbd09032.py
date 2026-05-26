import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


BASE_DIR = Path(__file__).resolve().parent
OCR_LINES_PATH = BASE_DIR / "ocr_lines.json"
PAGE_IMAGE_PATH = BASE_DIR / "page38.png"
OUT_PATH = BASE_DIR / "circle_left_title_arbd09032_test.json"
REPORT_PATH = BASE_DIR / "circle_left_title_arbd09032_test.md"
OVERLAY_PATH = BASE_DIR / "circle_left_title_arbd09032_overlay.png"

PAGE = 38
SHEET_NUMBER = "ARB-D09032"
SHEET_NAME = "防煙捲簾及捲門詳圖"


def clean_text(value):
    return "".join(str(value or "").split()).replace("|", "").strip()


def normalize_detail_name(value):
    text = clean_text(value)
    replacements = [
        ("不鏽鋼鐵捲門", "不鏽鋼鐵捲門"),
        ("婪", "簾"),
        ("槏", "機"),
        ("絍", "縫"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def center(line):
    return {"x": line["x"] + line["w"] / 2, "y": line["y"] + line["h"] / 2}


def row_runs(mask, y):
    xs = np.flatnonzero(mask[y])
    if xs.size == 0:
        return []
    runs = []
    start = int(xs[0])
    prev = int(xs[0])
    for x in xs[1:]:
        x = int(x)
        if x == prev + 1:
            prev = x
            continue
        runs.append((start, prev))
        start = prev = x
    runs.append((start, prev))
    return runs


def circle_score(mask, cx, cy, r):
    h, w = mask.shape
    points = 96
    hits = 0
    valid = 0
    for i in range(points):
        theta = 2 * math.pi * i / points
        for rr in (r - 1, r, r + 1):
            x = int(round(cx + math.cos(theta) * rr))
            y = int(round(cy + math.sin(theta) * rr))
            if 0 <= x < w and 0 <= y < h:
                valid += 1
                if mask[y, x]:
                    hits += 1
    if valid == 0:
        return 0.0
    return hits / valid


def detect_circle_candidates(mask):
    h, w = mask.shape
    candidates = []
    # Detail title underlines are relatively long horizontal strokes with a circle at the right end.
    for y in range(120, h - 120, 2):
        for x1, x2 in row_runs(mask, y):
            length = x2 - x1 + 1
            if not (170 <= length <= 760):
                continue
            if x1 < 80 or x2 > w - 850:
                continue
            best = None
            for r in range(25, 48):
                for dy in range(-8, 9, 4):
                    cx = x2 + r - 4
                    cy = y + dy
                    score = circle_score(mask, cx, cy, r)
                    if best is None or score > best["score"]:
                        best = {"cx": cx, "cy": cy, "r": r, "score": score, "run": [x1, y, x2, y]}
            if best and best["score"] >= 0.23:
                candidates.append(best)

    candidates.sort(key=lambda item: item["score"], reverse=True)
    merged = []
    for item in candidates:
        if any(math.hypot(item["cx"] - m["cx"], item["cy"] - m["cy"]) < 34 for m in merged):
            continue
        merged.append(item)
    return sorted(merged, key=lambda item: (item["cy"], item["cx"]))


def ocr_number_inside(lines, circle):
    cx, cy, r = circle["cx"], circle["cy"], circle["r"]
    best = None
    for line in lines:
        text = clean_text(line["text"])
        if not (text.isdigit() and 1 <= int(text) <= 30):
            continue
        c = center(line)
        dist = math.hypot(c["x"] - cx, c["y"] - cy)
        if dist <= r * 0.75:
            if best is None or dist < best["dist"]:
                best = {"line": line, "text": text, "dist": dist}
    return best


def has_chinese(text):
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def has_detail_title_keyword(text):
    keywords = ["詳圖", "立面圖", "剖面圖", "平面詳圖", "平面圖", "操作圖", "系統圖", "說明圖"]
    return any(keyword in text for keyword in keywords)


def title_left_of_circle(lines, circle):
    cx, cy = circle["cx"], circle["cy"]
    candidates = []
    for line in lines:
        text = clean_text(line["text"])
        if not text or not has_chinese(text):
            continue
        if not has_detail_title_keyword(text):
            continue
        if any(skip in text.upper() for skip in ("NTS", "UNIT", "DWG", "JOB", "ISSUE")):
            continue
        c = center(line)
        right = line["x"] + line["w"]
        if right > cx - 8:
            continue
        if not (18 <= line["h"] <= 55):
            continue
        dy = abs(c["y"] - cy)
        gap = cx - right
        if dy > 95 or gap > 1150:
            continue
        # Prefer large, same-baseline text close to the circle; penalize note lines and dimensions.
        score = dy * 2.0 + gap * 0.18 - line["w"] * 0.03 - line["h"] * 0.8
        candidates.append({"line": line, "text": text, "score": score, "dy": dy, "gap": gap})
    if not candidates:
        return None
    candidates.sort(key=lambda item: item["score"])
    return candidates[0]


def fill_missing_numbers(items):
    rows = []
    for item in sorted(items, key=lambda value: value["circle"]["cy"]):
        cy = item["circle"]["cy"]
        row = next((candidate for candidate in rows if abs(candidate["cy"] - cy) < 100), None)
        if row is None:
            row = {"cy": cy, "items": []}
            rows.append(row)
        row["items"].append(item)
        row["cy"] = sum(i["circle"]["cy"] for i in row["items"]) / len(row["items"])
    ordered = []
    for row in sorted(rows, key=lambda value: value["cy"]):
        ordered.extend(sorted(row["items"], key=lambda value: value["circle"]["cx"]))

    used = {int(item["detailNumber"]) for item in ordered if item.get("detailNumber") and str(item["detailNumber"]).isdigit()}
    for index, item in enumerate(ordered, 1):
        if item.get("detailNumber"):
            continue
        candidate = index
        while candidate in used:
            candidate += 1
        item["detailNumber"] = str(candidate)
        item["numberMethod"] = "sequence_fallback"
        item["review"] = True
        used.add(candidate)


def draw_overlay(image_path, items):
    image = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    for item in items:
        c = item["circle"]
        cx, cy, r = c["cx"], c["cy"], c["r"]
        draw.ellipse([(cx - r, cy - r), (cx + r, cy + r)], outline=(0, 80, 255), width=6)
        line = c.get("run")
        if line:
            draw.line(line, fill=(255, 0, 0), width=5)
        title = item.get("titleLine")
        if title:
            x1, y1 = title["x"], title["y"]
            x2, y2 = x1 + title["w"], y1 + title["h"]
            draw.rectangle([(x1, y1), (x2, y2)], outline=(255, 0, 0), width=5)
        label = f"{item.get('detailNumber', '?')}:{item.get('numberMethod', '')}"
        draw.rectangle([(cx - 45, cy - r - 32), (cx + 120, cy - r)], fill=(255, 255, 255))
        draw.text((cx - 40, cy - r - 28), label, fill=(0, 80, 255))
    image.save(OVERLAY_PATH)


def main():
    image = Image.open(PAGE_IMAGE_PATH).convert("L")
    arr = np.array(image)
    # Keep dark drawing strokes; avoid faint grey OCR/noise.
    mask = arr < 95
    lines = [line for line in json.loads(OCR_LINES_PATH.read_text(encoding="utf-8-sig")) if line["page"] == PAGE]

    circles = detect_circle_candidates(mask)
    items = []
    for circle in circles:
        number = ocr_number_inside(lines, circle)
        title = title_left_of_circle(lines, circle)
        if not title:
            continue
        detail_name_raw = title["text"]
        items.append(
            {
                "detailNumber": number["text"] if number else None,
                "numberMethod": "circle_ocr" if number else "missing_circle_number",
                "detailName": normalize_detail_name(detail_name_raw),
                "detailNameRaw": detail_name_raw,
                "review": number is None,
                "circle": {k: round(v, 2) if isinstance(v, float) else v for k, v in circle.items()},
                "numberLine": number["line"] if number else None,
                "titleLine": title["line"],
                "titleScore": round(title["score"], 2),
            }
        )

    # Deduplicate titles/circles that came from multi-line underline strokes.
    deduped = []
    for item in sorted(items, key=lambda value: (value["circle"]["cy"], value["circle"]["cx"], value["titleScore"])):
        if any(
            math.hypot(item["circle"]["cx"] - existing["circle"]["cx"], item["circle"]["cy"] - existing["circle"]["cy"]) < 50
            for existing in deduped
        ):
            continue
        deduped.append(item)
    items = deduped
    fill_missing_numbers(items)
    items.sort(key=lambda value: int(value["detailNumber"]) if str(value.get("detailNumber", "")).isdigit() else 999)
    draw_overlay(PAGE_IMAGE_PATH, items)

    result = {
        "sheetNumber": SHEET_NUMBER,
        "sheetName": SHEET_NAME,
        "page": PAGE,
        "detectedCount": len(items),
        "items": items,
        "overlayPath": str(OVERLAY_PATH),
    }
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")

    md = []
    md.append("# ARB-D09032 圓圈編號 + 左側大字標題測試")
    md.append("")
    md.append(f"圖紙號碼：{SHEET_NUMBER}")
    md.append(f"圖紙名稱：{SHEET_NAME}")
    md.append(f"PDF 頁碼：{PAGE}")
    md.append(f"偵測數量：{len(items)}")
    md.append(f"定位疊圖：{OVERLAY_PATH}")
    md.append("")
    md.append("## 擷取結果")
    md.append("")
    md.append("| 詳圖編號 | 編號方式 | 詳圖名稱 | OCR 原始名稱 | 需複核 |")
    md.append("|---:|---|---|---|---|")
    for item in items:
        md.append(
            f"| {item['detailNumber']} | {item['numberMethod']} | {item['detailName']} | {item['detailNameRaw']} | {'是' if item.get('review') else '否'} |"
        )
    md.append("")
    md.append("## 初步判斷")
    md.append("")
    md.append("- 不畫紅框時也可以先找詳圖圓圈，再往左擷取同一基準線的大字標題。")
    md.append("- 圓圈內數字若 OCR 漏讀，仍可用版面順序補判，但必須標記為需複核。")
    md.append("- 這個方法比純整頁 OCR 好，但遇到施工說明或表格區仍需要過濾規則。")
    REPORT_PATH.write_text("\n".join(md), encoding="utf8")

    print(
        json.dumps(
            {
                "report": str(REPORT_PATH),
                "json": str(OUT_PATH),
                "overlay": str(OVERLAY_PATH),
                "detectedCount": len(items),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
