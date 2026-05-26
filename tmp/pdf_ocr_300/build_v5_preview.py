import argparse
import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pypdf import PdfReader


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parents[1]
DEFAULT_FAMILY_NAME = "AE-圖號詳圖編號標頭-3.5mm"
DEFAULT_OCR_LINES_PATH = BASE_DIR / "ocr_lines.json"
DEFAULT_V4_PREVIEW_PATH = BASE_DIR / "detail_metadata_v4_preview.json"
DEFAULT_OUTPUT_PREFIX = BASE_DIR / "detail_metadata_v5"
SHEET_RE = re.compile(r"(?:\d{4}[A-Z]-)?([A-Z]{3}-D\d{5})")


OCR_TEXT_CORRECTIONS = [
    ("地坏", "地坪"),
    ("郚", "部"),
    ("隔屛", "隔屏"),
    ("維俢", "維修"),
    ("攔杆", "欄杆"),
    ("嬁", "燈"),
    ("哋面", "地面"),
    ("灻樣", "大樣"),
    ("棸急", "緊急"),
    ("Ⅰ1", "I1"),
    ("Ⅰ2", "I2"),
    ("Ⅱ1", "II1"),
    ("Ⅱ2", "II2"),
    ("JⅠ", "J1"),
    ("JI", "J1"),
]

DETAIL_TITLE_KEYWORDS = [
    "詳圖",
    "示意圖",
    "剖面圖",
    "平面詳圖",
    "平面圖",
    "立面圖",
    "大樣圖",
    "詳剖",
    "收頭",
    "組合圖",
    "操作圖",
    "系統圖",
    "說明圖",
    "標示",
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
]


def clean_text(value):
    return "".join(str(value or "").split()).replace("|", "").strip()


def normalize_text(value):
    return (
        clean_text(value)
        .replace("，", ",")
        .replace("、", ",")
        .replace("：", ":")
        .replace("（", "(")
        .replace("）", ")")
        .upper()
    )


def apply_ocr_corrections(value):
    text = clean_text(value)
    reasons = []
    for source, target in OCR_TEXT_CORRECTIONS:
        if source in text:
            text = text.replace(source, target)
            reasons.append(f"{source}->{target}")
    return text, reasons


def has_chinese(value):
    return any("\u4e00" <= char <= "\u9fff" for char in str(value or ""))


def has_detail_title_keyword(value):
    text = clean_text(value)
    return any(keyword in text for keyword in DETAIL_TITLE_KEYWORDS)


def center(line):
    return {"x": line["x"] + line["w"] / 2, "y": line["y"] + line["h"] / 2}


def parse_detail_numbers(value):
    numbers = set()
    for part in str(value or "").split(","):
        part = part.strip()
        if not part:
            continue
        match = re.match(r"^(\d+)\s*-\s*(\d+)$", part)
        if match:
            start = int(match.group(1))
            end = int(match.group(2))
            for number in range(min(start, end), max(start, end) + 1):
                numbers.add(number)
            continue
        if part.isdigit():
            numbers.add(int(part))
    return sorted(numbers)


def format_detail_numbers(numbers):
    sorted_numbers = sorted(set(int(number) for number in numbers))
    ranges = []
    index = 0
    while index < len(sorted_numbers):
        start = sorted_numbers[index]
        end = start
        while index + 1 < len(sorted_numbers) and sorted_numbers[index + 1] == end + 1:
            index += 1
            end = sorted_numbers[index]
        ranges.append(str(start) if start == end else f"{start}-{end}")
        index += 1
    return ",".join(ranges)


def read_json(path, encoding="utf8"):
    with Path(path).open("r", encoding=encoding) as handle:
        return json.load(handle)


def default_pdf_path():
    preferred = REPO_ROOT / "大樣詳圖ALL-1.pdf"
    if preferred.exists():
        return preferred
    candidates = sorted(REPO_ROOT.glob("*ALL-1.pdf"))
    if candidates:
        return candidates[0]
    fallback = REPO_ROOT / "大樣詳圖ALL.pdf"
    if fallback.exists():
        return fallback
    raise FileNotFoundError("找不到預設 PDF，請用 --pdf 指定檔案。")


def load_sheet_maps(v4_preview_path):
    sheet_name_by_number = {}
    sheet_by_page = {}
    if not Path(v4_preview_path).exists():
        return sheet_name_by_number, sheet_by_page

    preview = read_json(v4_preview_path)
    for item in preview.get("items", []):
        sheet_number = item.get("sheetNumber")
        sheet_name = item.get("sheetName")
        if sheet_number and sheet_name and sheet_number not in sheet_name_by_number:
            sheet_name_by_number[sheet_number] = sheet_name
        for page in item.get("sourcePages") or []:
            if sheet_number and sheet_name:
                sheet_by_page[int(page)] = {"sheetNumber": sheet_number, "sheetName": sheet_name}
    return sheet_name_by_number, sheet_by_page


def infer_sheet_info_by_page(ocr_lines, sheet_name_by_number, sheet_by_page):
    inferred = dict(sheet_by_page)
    lines_by_page = defaultdict(list)
    for line in ocr_lines:
        lines_by_page[int(line["page"])].append(line)

    for page, lines in lines_by_page.items():
        if page in inferred:
            continue
        joined = " ".join(str(line.get("text", "")) for line in lines)
        matches = SHEET_RE.findall(joined)
        if not matches:
            continue
        sheet_number = matches[-1]
        inferred[page] = {
            "sheetNumber": sheet_number,
            "sheetName": sheet_name_by_number.get(sheet_number, ""),
        }
    return inferred


def extract_red_boxes_by_page(pdf_path):
    reader = PdfReader(str(pdf_path))
    result = defaultdict(list)
    page_sizes = {}
    for page_index, page in enumerate(reader.pages):
        page_number = page_index + 1
        page_sizes[page_number] = {"width": float(page.mediabox.width), "height": float(page.mediabox.height)}
        for annotation_index, ref in enumerate(page.get("/Annots") or [], 1):
            obj = ref.get_object()
            color = [float(x) for x in obj.get("/C", [])]
            subtype = str(obj.get("/Subtype", ""))
            rect = [float(x) for x in obj.get("/Rect", [])]
            is_red_square = (
                subtype == "/Square"
                and len(rect) == 4
                and len(color) >= 3
                and color[0] > 0.8
                and color[1] < 0.2
                and color[2] < 0.2
            )
            if not is_red_square:
                continue
            x1, y1, x2, y2 = rect
            result[page_number].append(
                {
                    "annotationIndex": annotation_index,
                    "rectPdf": [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)],
                }
            )
    return result, page_sizes


def pdf_rect_to_px(rect_pdf, page_size_pdf, page_width_px, page_height_px):
    x1, y1, x2, y2 = rect_pdf
    sx = page_width_px / page_size_pdf["width"]
    sy = page_height_px / page_size_pdf["height"]
    return {
        "x1": x1 * sx,
        "y1": (page_size_pdf["height"] - y2) * sy,
        "x2": x2 * sx,
        "y2": (page_size_pdf["height"] - y1) * sy,
    }


def is_inside(line, rect, pad_x=12, pad_y=10):
    c = center(line)
    return rect["x1"] - pad_x <= c["x"] <= rect["x2"] + pad_x and rect["y1"] - pad_y <= c["y"] <= rect["y2"] + pad_y


def merge_text(lines):
    ordered = sorted(lines, key=lambda line: (line["y"], line["x"]))
    return "".join(clean_text(line["text"]) for line in ordered if clean_text(line["text"]))


def likely_detail_number(line):
    text = clean_text(line.get("text", ""))
    return text.isdigit() and 1 <= int(text) <= 40


def find_nearby_number(page_lines, rect, page_height_px):
    title_cx = (rect["x1"] + rect["x2"]) / 2
    title_cy = (rect["y1"] + rect["y2"]) / 2
    candidates = []
    for line in page_lines:
        if not likely_detail_number(line):
            continue
        if line["y"] < 100 or line["y"] > page_height_px - 120:
            continue
        c = center(line)
        dx = c["x"] - title_cx
        dy = c["y"] - title_cy
        right_side = -30 <= dx <= 650
        same_baseline = abs(dy) < 75
        if not (right_side and same_baseline):
            continue
        score = math.hypot(dx / 1.35, dy * 1.8) - min(line["h"], 60)
        candidates.append({"line": line, "center": c, "dx": dx, "dy": dy, "score": score})
    candidates.sort(key=lambda item: item["score"])
    return candidates[0] if candidates else None


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


def circle_score(mask, cx, cy, radius):
    height, width = mask.shape
    points = 96
    hits = 0
    valid = 0
    for index in range(points):
        theta = 2 * math.pi * index / points
        for sample_radius in (radius - 1, radius, radius + 1):
            x = int(round(cx + math.cos(theta) * sample_radius))
            y = int(round(cy + math.sin(theta) * sample_radius))
            if 0 <= x < width and 0 <= y < height:
                valid += 1
                if mask[y, x]:
                    hits += 1
    return hits / valid if valid else 0.0


def detect_circle_candidates(mask):
    height, width = mask.shape
    candidates = []
    for y in range(120, height - 120, 2):
        for x1, x2 in row_runs(mask, y):
            length = x2 - x1 + 1
            if not (170 <= length <= 780):
                continue
            if x1 < 80 or x2 > width - 650:
                continue
            best = None
            for radius in range(25, 48):
                for dy in range(-8, 9, 4):
                    cx = x2 + radius - 4
                    cy = y + dy
                    score = circle_score(mask, cx, cy, radius)
                    if best is None or score > best["score"]:
                        best = {"cx": cx, "cy": cy, "r": radius, "score": score, "run": [x1, y, x2, y]}
            if best and best["score"] >= 0.23:
                candidates.append(best)

    candidates.sort(key=lambda item: item["score"], reverse=True)
    merged = []
    for item in candidates:
        if any(math.hypot(item["cx"] - existing["cx"], item["cy"] - existing["cy"]) < 34 for existing in merged):
            continue
        merged.append(item)
    return sorted(merged, key=lambda item: (item["cy"], item["cx"]))


def ocr_number_inside(page_lines, circle):
    cx, cy, radius = circle["cx"], circle["cy"], circle["r"]
    best = None
    for line in page_lines:
        text = clean_text(line.get("text", ""))
        if not (text.isdigit() and 1 <= int(text) <= 40):
            continue
        c = center(line)
        distance = math.hypot(c["x"] - cx, c["y"] - cy)
        if distance <= radius * 0.75:
            if best is None or distance < best["distance"]:
                best = {"line": line, "text": text, "distance": distance}
    return best


def title_left_of_circle(page_lines, circle):
    cx, cy = circle["cx"], circle["cy"]
    candidates = []
    for line in page_lines:
        text = clean_text(line.get("text", ""))
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
        if not (18 <= line["h"] <= 60):
            continue
        dy = abs(c["y"] - cy)
        gap = cx - right
        if dy > 95 or gap > 1200:
            continue
        score = dy * 2.0 + gap * 0.18 - line["w"] * 0.03 - line["h"] * 0.8
        candidates.append({"line": line, "text": text, "score": score, "dy": dy, "gap": gap})
    candidates.sort(key=lambda item: item["score"])
    return candidates[0] if candidates else None


def row_ordered(items, rect_getter):
    rows = []
    for item in sorted(items, key=lambda value: rect_getter(value)["y"]):
        y = rect_getter(item)["y"]
        row = next((candidate for candidate in rows if abs(candidate["y"] - y) < 100), None)
        if row is None:
            row = {"y": y, "items": []}
            rows.append(row)
        row["items"].append(item)
        row["y"] = sum(rect_getter(value)["y"] for value in row["items"]) / len(row["items"])
    ordered = []
    for row in sorted(rows, key=lambda value: value["y"]):
        ordered.extend(sorted(row["items"], key=lambda value: rect_getter(value)["x"]))
    return ordered


def fill_sequence_fallback(items, position_getter):
    ordered = row_ordered(items, position_getter)
    used = {int(item["detailNumber"]) for item in ordered if str(item.get("detailNumber", "")).isdigit()}
    for index, item in enumerate(ordered, 1):
        if item.get("detailNumber"):
            continue
        candidate = index
        while candidate in used:
            candidate += 1
        item["detailNumber"] = str(candidate)
        item["numberMethod"] = "sequence_fallback"
        item["review"] = True
        item.setdefault("reviewReasons", []).append("圓圈內數字未被 OCR 讀取，使用版面順序補判")
        used.add(candidate)


def confidence_for(item):
    if item.get("review"):
        return "review"
    if item.get("sourceMode") == "red_box_annotation":
        return "high_red_box"
    if item.get("numberMethod") == "circle_ocr":
        return "medium_circle"
    return "low"


def build_red_box_items(page, sheet_info, page_lines, page_size_pdf, red_boxes):
    if not page_lines:
        return []
    page_width_px = page_lines[0]["width"]
    page_height_px = page_lines[0]["height"]
    items = []
    for box in red_boxes:
        rect_px = pdf_rect_to_px(box["rectPdf"], page_size_pdf, page_width_px, page_height_px)
        lines_in_box = [line for line in page_lines if is_inside(line, rect_px)]
        detail_name_raw = merge_text(lines_in_box)
        detail_name, correction_reasons = apply_ocr_corrections(detail_name_raw)
        nearby_number = find_nearby_number(page_lines, rect_px, page_height_px)
        review_reasons = []
        if not detail_name:
            review_reasons.append("紅框內未讀到文字")
        if not nearby_number:
            review_reasons.append("紅框附近未讀到詳圖編號，使用版面順序補判")
        if detail_name and not has_detail_title_keyword(detail_name):
            review_reasons.append("紅框文字未包含常見詳圖名稱關鍵字，建議人工確認")
        item = {
            "sheetNumber": sheet_info["sheetNumber"],
            "sheetName": sheet_info.get("sheetName", ""),
            "detailNumber": clean_text(nearby_number["line"]["text"]) if nearby_number else None,
            "detailName": detail_name,
            "detailNameRaw": detail_name_raw,
            "sourcePage": page,
            "sourceMode": "red_box_annotation",
            "numberMethod": "nearby_number" if nearby_number else "sequence_fallback",
            "review": bool(review_reasons),
            "reviewReasons": review_reasons,
            "correctionReasons": correction_reasons,
            "redBox": {"annotationIndex": box["annotationIndex"], "rectPdf": box["rectPdf"], "rectPx": rect_px},
            "numberLine": nearby_number["line"] if nearby_number else None,
            "titleLine": None,
        }
        items.append(item)

    fill_sequence_fallback(items, lambda value: {"x": value["redBox"]["rectPx"]["x1"], "y": value["redBox"]["rectPx"]["y1"]})
    return items


def build_circle_items(page, sheet_info, page_lines, page_image_path):
    if not page_image_path.exists():
        return []
    image = Image.open(page_image_path).convert("L")
    mask = np.array(image) < 95
    circles = detect_circle_candidates(mask)
    items = []
    for circle in circles:
        number = ocr_number_inside(page_lines, circle)
        title = title_left_of_circle(page_lines, circle)
        if not title:
            continue
        detail_name_raw = title["text"]
        detail_name, correction_reasons = apply_ocr_corrections(detail_name_raw)
        item = {
            "sheetNumber": sheet_info["sheetNumber"],
            "sheetName": sheet_info.get("sheetName", ""),
            "detailNumber": number["text"] if number else None,
            "detailName": detail_name,
            "detailNameRaw": detail_name_raw,
            "sourcePage": page,
            "sourceMode": "circle_left_title",
            "numberMethod": "circle_ocr" if number else "sequence_fallback",
            "review": number is None,
            "reviewReasons": [] if number else ["圓圈內數字未被 OCR 讀取，使用版面順序補判"],
            "correctionReasons": correction_reasons,
            "circle": {key: round(value, 2) if isinstance(value, float) else value for key, value in circle.items()},
            "numberLine": number["line"] if number else None,
            "titleLine": title["line"],
            "titleScore": round(title["score"], 2),
        }
        items.append(item)

    deduped = []
    for item in sorted(items, key=lambda value: (value["circle"]["cy"], value["circle"]["cx"], value.get("titleScore", 0))):
        if any(
            math.hypot(item["circle"]["cx"] - existing["circle"]["cx"], item["circle"]["cy"] - existing["circle"]["cy"]) < 50
            for existing in deduped
        ):
            continue
        deduped.append(item)
    fill_sequence_fallback(deduped, lambda value: {"x": value["circle"]["cx"], "y": value["circle"]["cy"]})
    return deduped


def group_items(raw_items):
    groups = {}
    for item in raw_items:
        if not item.get("sheetNumber") or not item.get("detailName") or not item.get("detailNumber"):
            continue
        key = f"{item['sheetNumber']}|{normalize_text(item['detailName'])}"
        group = groups.setdefault(
            key,
            {
                "sheetNumber": item["sheetNumber"],
                "sheetName": item.get("sheetName", ""),
                "detailName": item["detailName"],
                "detailNameRaw": item.get("detailNameRaw", ""),
                "detailNumbers": set(),
                "sourcePages": set(),
                "sourceModes": set(),
                "numberMethods": set(),
                "reviewReasons": set(),
                "correctionReasons": set(),
                "originalItems": [],
                "review": False,
            },
        )
        for number in parse_detail_numbers(item["detailNumber"]):
            group["detailNumbers"].add(number)
        group["sourcePages"].add(item["sourcePage"])
        group["sourceModes"].add(item["sourceMode"])
        group["numberMethods"].add(item["numberMethod"])
        group["review"] = group["review"] or bool(item.get("review"))
        for reason in item.get("reviewReasons") or []:
            group["reviewReasons"].add(reason)
        for reason in item.get("correctionReasons") or []:
            group["correctionReasons"].add(reason)
        group["originalItems"].append(item)

    results = []
    for group in groups.values():
        detail_number = format_detail_numbers(group["detailNumbers"])
        result = {
            "sheetNumber": group["sheetNumber"],
            "sheetName": group["sheetName"],
            "detailNumber": detail_number,
            "detailNumbers": sorted(group["detailNumbers"]),
            "detailName": group["detailName"],
            "typeName": f"{group['sheetNumber']}-{group['sheetName']}-{group['detailName']}",
            "sourcePages": sorted(group["sourcePages"]),
            "sourceModes": sorted(group["sourceModes"]),
            "numberMethods": sorted(group["numberMethods"]),
            "review": group["review"],
            "reviewReasons": sorted(group["reviewReasons"]),
            "correctionReasons": sorted(group["correctionReasons"]),
            "confidence": confidence_for(
                {
                    "review": group["review"],
                    "sourceMode": "red_box_annotation" if "red_box_annotation" in group["sourceModes"] else "circle_left_title",
                    "numberMethod": "circle_ocr" if "circle_ocr" in group["numberMethods"] else "",
                }
            ),
            "originalItems": group["originalItems"],
        }
        results.append(result)
    return sorted(results, key=lambda item: (item["sheetNumber"], item["detailNumbers"][0] if item["detailNumbers"] else 999, item["detailName"]))


def draw_page_overlay(page_image_path, items, output_path):
    image = Image.open(page_image_path).convert("RGB")
    draw = ImageDraw.Draw(image)
    for item in items:
        if item.get("sourceMode") == "red_box_annotation":
            rect = item["redBox"]["rectPx"]
            draw.rectangle([(rect["x1"], rect["y1"]), (rect["x2"], rect["y2"])], outline=(255, 0, 0), width=7)
            label_x, label_y = rect["x1"], rect["y1"] - 30
            label_color = (255, 0, 0)
        else:
            circle = item["circle"]
            cx, cy, radius = circle["cx"], circle["cy"], circle["r"]
            draw.ellipse([(cx - radius, cy - radius), (cx + radius, cy + radius)], outline=(0, 80, 255), width=6)
            if circle.get("run"):
                draw.line(circle["run"], fill=(255, 0, 0), width=5)
            title = item.get("titleLine")
            if title:
                draw.rectangle([(title["x"], title["y"]), (title["x"] + title["w"], title["y"] + title["h"])], outline=(255, 0, 0), width=5)
            label_x, label_y = cx - 45, cy - radius - 32
            label_color = (0, 80, 255)
        label = f"{item.get('detailNumber', '?')}:{item.get('numberMethod', '')}"
        draw.rectangle([(label_x, label_y), (label_x + 170, label_y + 28)], fill=(255, 255, 255))
        draw.text((label_x + 4, label_y + 4), label, fill=label_color)
    image.save(output_path)


def write_csv(path, items):
    rows = [
        [
            "圖紙號碼",
            "圖紙名稱",
            "詳圖編號",
            "詳圖名稱",
            "類型名稱",
            "來源頁碼",
            "來源模式",
            "編號方式",
            "信心",
            "需複核",
            "複核原因",
            "OCR修正",
        ]
    ]
    for item in items:
        rows.append(
            [
                item["sheetNumber"],
                item["sheetName"],
                item["detailNumber"],
                item["detailName"],
                item["typeName"],
                ",".join(str(page) for page in item["sourcePages"]),
                ",".join(item["sourceModes"]),
                ",".join(item["numberMethods"]),
                item["confidence"],
                "是" if item["review"] else "否",
                "；".join(item["reviewReasons"]),
                "；".join(item["correctionReasons"]),
            ]
        )
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def write_report(path, preview, overlay_paths):
    items = preview["items"]
    review_items = [item for item in items if item["review"]]
    by_sheet = preview["bySheet"]
    lines = []
    lines.append("# PDF 詳圖項目 V5 Preview")
    lines.append("")
    lines.append(f"來源 PDF：{preview['sourcePdf']}")
    lines.append(f"目標詳圖項目：{preview['familyName']}")
    lines.append(f"產生時間：{preview['generatedAt']}")
    lines.append("")
    lines.append("## 統計")
    lines.append("")
    lines.append(f"- 原始候選：{preview['counts']['rawItems']}")
    lines.append(f"- 合併後類型：{preview['counts']['groupedItems']}")
    lines.append(f"- 需複核：{preview['counts']['reviewItems']}")
    lines.append(f"- 紅框模式候選：{preview['counts']['redBoxRawItems']}")
    lines.append(f"- 圓圈左側標題模式候選：{preview['counts']['circleRawItems']}")
    lines.append(f"- 順序補判：{preview['counts']['sequenceFallbackItems']}")
    lines.append("")
    lines.append("## 圖紙彙總")
    lines.append("")
    lines.append("| 圖紙號碼 | 圖紙名稱 | 類型數 | 需複核 | 來源模式 |")
    lines.append("|---|---|---:|---:|---|")
    for row in by_sheet:
        lines.append(
            f"| {row['sheetNumber']} | {row['sheetName']} | {row['count']} | {row['reviewCount']} | {','.join(row['sourceModes'])} |"
        )
    lines.append("")
    lines.append("## 需複核項目")
    lines.append("")
    if not review_items:
        lines.append("無。")
    else:
        lines.append("| 圖紙號碼 | 詳圖編號 | 詳圖名稱 | 來源模式 | 編號方式 | 複核原因 |")
        lines.append("|---|---:|---|---|---|---|")
        for item in review_items:
            lines.append(
                f"| {item['sheetNumber']} | {item['detailNumber']} | {item['detailName']} | {','.join(item['sourceModes'])} | {','.join(item['numberMethods'])} | {'；'.join(item['reviewReasons'])} |"
            )
    lines.append("")
    lines.append("## 全部類型")
    lines.append("")
    lines.append("| 圖紙號碼 | 詳圖編號 | 詳圖名稱 | 來源模式 | 信心 |")
    lines.append("|---|---:|---|---|---|")
    for item in items:
        lines.append(
            f"| {item['sheetNumber']} | {item['detailNumber']} | {item['detailName']} | {','.join(item['sourceModes'])} | {item['confidence']} |"
        )
    if overlay_paths:
        lines.append("")
        lines.append("## 定位疊圖")
        lines.append("")
        for overlay in overlay_paths:
            lines.append(f"- {overlay}")
    Path(path).write_text("\n".join(lines), encoding="utf8")


def build_by_sheet(items):
    grouped = {}
    for item in items:
        row = grouped.setdefault(
            item["sheetNumber"],
            {
                "sheetNumber": item["sheetNumber"],
                "sheetName": item["sheetName"],
                "count": 0,
                "reviewCount": 0,
                "sourceModes": set(),
            },
        )
        row["count"] += 1
        if item["review"]:
            row["reviewCount"] += 1
        for mode in item["sourceModes"]:
            row["sourceModes"].add(mode)
    return [
        {**row, "sourceModes": sorted(row["sourceModes"])}
        for row in sorted(grouped.values(), key=lambda value: value["sheetNumber"])
    ]


def parse_sheet_filter(value):
    if not value:
        return set()
    return {part.strip() for part in value.split(",") if part.strip()}


def main():
    parser = argparse.ArgumentParser(description="Build V5 PDF detail component metadata preview without writing to Revit.")
    parser.add_argument("--pdf", type=Path, default=default_pdf_path(), help="PDF path. Default: 大樣詳圖ALL-1.pdf if present.")
    parser.add_argument("--ocr-lines", type=Path, default=DEFAULT_OCR_LINES_PATH, help="OCR lines JSON generated from the matching PDF pages.")
    parser.add_argument("--v4-preview", type=Path, default=DEFAULT_V4_PREVIEW_PATH, help="Existing V4 preview used only for sheet names/page mapping.")
    parser.add_argument("--sheets", default="", help="Comma-separated sheet numbers to include. Empty means all detected pages.")
    parser.add_argument("--family-name", default=DEFAULT_FAMILY_NAME)
    parser.add_argument("--output-prefix", type=Path, default=DEFAULT_OUTPUT_PREFIX)
    parser.add_argument("--no-overlays", action="store_true", help="Skip overlay image generation.")
    args = parser.parse_args()

    sheet_filter = parse_sheet_filter(args.sheets)
    ocr_lines = read_json(args.ocr_lines, encoding="utf-8-sig")
    lines_by_page = defaultdict(list)
    for line in ocr_lines:
        lines_by_page[int(line["page"])].append(line)

    sheet_name_by_number, sheet_by_page_seed = load_sheet_maps(args.v4_preview)
    sheet_by_page = infer_sheet_info_by_page(ocr_lines, sheet_name_by_number, sheet_by_page_seed)
    red_boxes_by_page, page_sizes_pdf = extract_red_boxes_by_page(args.pdf)

    raw_items = []
    overlay_paths = []
    skipped_pages = []
    for page in sorted(lines_by_page):
        sheet_info = sheet_by_page.get(page)
        if not sheet_info or not sheet_info.get("sheetNumber"):
            skipped_pages.append({"page": page, "reason": "no_sheet_info"})
            continue
        if sheet_filter and sheet_info["sheetNumber"] not in sheet_filter:
            continue
        page_lines = lines_by_page[page]
        page_image_path = BASE_DIR / f"page{page:02d}.png"
        page_items = []
        if red_boxes_by_page.get(page):
            page_items = build_red_box_items(page, sheet_info, page_lines, page_sizes_pdf[page], red_boxes_by_page[page])
        else:
            page_items = build_circle_items(page, sheet_info, page_lines, page_image_path)
        raw_items.extend(page_items)

        if page_items and not args.no_overlays and page_image_path.exists():
            overlay_path = args.output_prefix.parent / f"{args.output_prefix.name}_page{page:02d}_overlay.png"
            draw_page_overlay(page_image_path, page_items, overlay_path)
            overlay_paths.append(str(overlay_path))

    items = group_items(raw_items)
    by_sheet = build_by_sheet(items)
    review_items = [item for item in items if item["review"]]
    counts = {
        "rawItems": len(raw_items),
        "groupedItems": len(items),
        "reviewItems": len(review_items),
        "redBoxRawItems": sum(1 for item in raw_items if item.get("sourceMode") == "red_box_annotation"),
        "circleRawItems": sum(1 for item in raw_items if item.get("sourceMode") == "circle_left_title"),
        "sequenceFallbackItems": sum(1 for item in raw_items if item.get("numberMethod") == "sequence_fallback"),
        "processedSheets": len(by_sheet),
        "skippedPages": len(skipped_pages),
    }
    preview = {
        "sourcePdf": str(args.pdf),
        "familyName": args.family_name,
        "algorithm": "v5_red_box_annotation_or_circle_left_title_preview",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "options": {
            "sheets": sorted(sheet_filter),
            "ocrLinesPath": str(args.ocr_lines),
            "v4PreviewPath": str(args.v4_preview),
            "overlays": not args.no_overlays,
        },
        "counts": counts,
        "bySheet": by_sheet,
        "items": items,
        "reviewOnly": review_items,
        "rawItems": raw_items,
        "skippedPages": skipped_pages,
        "overlayPaths": overlay_paths,
    }

    preview_path = args.output_prefix.with_name(f"{args.output_prefix.name}_preview.json")
    review_path = args.output_prefix.with_name(f"{args.output_prefix.name}_review_only.csv")
    all_csv_path = args.output_prefix.with_name(f"{args.output_prefix.name}_all_types.csv")
    report_path = args.output_prefix.with_name(f"{args.output_prefix.name}_review_report.md")
    preview_path.write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding="utf8")
    write_csv(all_csv_path, items)
    write_csv(review_path, review_items)
    write_report(report_path, preview, overlay_paths)

    print(
        json.dumps(
            {
                "preview": str(preview_path),
                "report": str(report_path),
                "allCsv": str(all_csv_path),
                "reviewCsv": str(review_path),
                "counts": counts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
