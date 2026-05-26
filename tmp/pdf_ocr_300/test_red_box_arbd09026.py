import json
import math
from pathlib import Path

from PIL import Image, ImageDraw
from pypdf import PdfReader


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parents[1]
PDF_PATH = next(path for path in REPO_ROOT.glob("*.pdf") if path.name.endswith("ALL-1.pdf"))
OCR_LINES_PATH = BASE_DIR / "ocr_lines.json"
PAGE_IMAGE_PATH = BASE_DIR / "page32.png"
OUT_PATH = BASE_DIR / "red_box_arbd09026_test.json"
REPORT_PATH = BASE_DIR / "red_box_arbd09026_test.md"
OVERLAY_PATH = BASE_DIR / "red_box_arbd09026_overlay.png"

PAGE_INDEX = 31
SHEET_NUMBER = "ARB-D09026"
SHEET_NAME = "指標系統詳圖(三)"


def clean_text(value):
    return "".join(str(value or "").split()).replace("|", "").strip()


def normalize_detail_name(value):
    text = clean_text(value)
    replacements = [
        ("Ⅰ1", "I1"),
        ("Ⅰ2", "I2"),
        ("Ⅱ1", "II1"),
        ("Ⅱ2", "II2"),
        ("JI", "J1"),
        ("JⅠ", "J1"),
        ("棸急", "緊急"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def center(line):
    return {"x": line["x"] + line["w"] / 2, "y": line["y"] + line["h"] / 2}


def extract_red_boxes():
    reader = PdfReader(str(PDF_PATH))
    page = reader.pages[PAGE_INDEX]
    boxes = []
    for idx, ref in enumerate(page.get("/Annots") or [], 1):
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
        boxes.append(
            {
                "annotationIndex": idx,
                "rectPdf": [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)],
            }
        )
    return {
        "page": PAGE_INDEX + 1,
        "pageWidthPdf": float(page.mediabox.width),
        "pageHeightPdf": float(page.mediabox.height),
        "redBoxes": boxes,
    }


def pdf_rect_to_px(rect_pdf, page_width_pdf, page_height_pdf, page_width_px, page_height_px):
    x1, y1, x2, y2 = rect_pdf
    sx = page_width_px / page_width_pdf
    sy = page_height_px / page_height_pdf
    return {
        "x1": x1 * sx,
        "y1": (page_height_pdf - y2) * sy,
        "x2": x2 * sx,
        "y2": (page_height_pdf - y1) * sy,
    }


def is_inside(line, rect, pad_x=12, pad_y=10):
    c = center(line)
    return (
        rect["x1"] - pad_x <= c["x"] <= rect["x2"] + pad_x
        and rect["y1"] - pad_y <= c["y"] <= rect["y2"] + pad_y
    )


def merge_text(lines):
    ordered = sorted(lines, key=lambda line: (line["y"], line["x"]))
    return "".join(clean_text(line["text"]) for line in ordered if clean_text(line["text"]))


def likely_detail_number(line):
    text = clean_text(line["text"])
    return text.isdigit() and 1 <= int(text) <= 30


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
        abs_dy = abs(dy)
        # 圖面標題的詳圖編號通常在標題線右側的圓圈中；排除圖框座標與尺寸數字。
        right_side = -30 <= dx <= 650
        same_baseline = abs_dy < 75
        if not (right_side and same_baseline):
            continue
        score = math.hypot(dx / 1.35, dy * 1.8) - min(line["h"], 60)
        candidates.append(
            {
                "line": line,
                "center": c,
                "dx": dx,
                "dy": dy,
                "score": score,
            }
        )
    candidates.sort(key=lambda item: item["score"])
    return candidates[0] if candidates else None


def fill_sequence_fallback(red_boxes):
    rows = []
    for box in sorted(red_boxes, key=lambda item: item["rectPx"]["y1"]):
        y = box["rectPx"]["y1"]
        row = next((candidate for candidate in rows if abs(candidate["y"] - y) < 80), None)
        if row is None:
            row = {"y": y, "boxes": []}
            rows.append(row)
        row["boxes"].append(box)
        row["y"] = sum(item["rectPx"]["y1"] for item in row["boxes"]) / len(row["boxes"])
    ordered = []
    for row in sorted(rows, key=lambda item: item["y"]):
        ordered.extend(sorted(row["boxes"], key=lambda item: item["rectPx"]["x1"]))
    for index, box in enumerate(ordered, 1):
        if box.get("nearbyDetailNumber"):
            continue
        box["nearbyDetailNumber"] = {
            "text": str(index),
            "method": "sequence_fallback",
            "x": None,
            "y": None,
            "w": None,
            "h": None,
            "dx": None,
            "dy": None,
            "score": None,
        }


def draw_overlay(red_boxes):
    image = Image.open(PAGE_IMAGE_PATH).convert("RGB")
    draw = ImageDraw.Draw(image)
    for box in red_boxes:
        rect = box["rectPx"]
        xy = [(rect["x1"], rect["y1"]), (rect["x2"], rect["y2"])]
        draw.rectangle(xy, outline=(255, 0, 0), width=8)
        nearby = box.get("nearbyDetailNumber")
        label = f"#{box['annotationIndex']} / {nearby.get('text', '?') if nearby else '?'}"
        draw.rectangle([(rect["x1"], rect["y1"] - 30), (rect["x1"] + 120, rect["y1"])], fill=(255, 255, 255))
        draw.text((rect["x1"] + 4, rect["y1"] - 25), label, fill=(255, 0, 0))
        if nearby and nearby.get("x") is not None:
            nx1, ny1 = nearby["x"], nearby["y"]
            nx2, ny2 = nx1 + nearby["w"], ny1 + nearby["h"]
            draw.rectangle([(nx1, ny1), (nx2, ny2)], outline=(0, 80, 255), width=5)
    image.save(OVERLAY_PATH)


def main():
    annotations = extract_red_boxes()
    all_lines = json.loads(OCR_LINES_PATH.read_text(encoding="utf-8-sig"))
    page_lines = [line for line in all_lines if line["page"] == annotations["page"]]
    page_width_px = page_lines[0]["width"]
    page_height_px = page_lines[0]["height"]

    red_boxes = []
    for box in annotations["redBoxes"]:
        rect_px = pdf_rect_to_px(
            box["rectPdf"],
            annotations["pageWidthPdf"],
            annotations["pageHeightPdf"],
            page_width_px,
            page_height_px,
        )
        lines_in_box = [line for line in page_lines if is_inside(line, rect_px)]
        nearby = find_nearby_number(page_lines, rect_px, page_height_px)
        detail_name_raw = merge_text(lines_in_box)
        red_boxes.append(
            {
                **box,
                "rectPx": rect_px,
                "linesInBox": lines_in_box,
                "detailNameRaw": detail_name_raw,
                "detailName": normalize_detail_name(detail_name_raw),
                "nearbyDetailNumber": None
                if not nearby
                else {
                    "text": clean_text(nearby["line"]["text"]),
                    "method": "nearby_number",
                    "x": nearby["line"]["x"],
                    "y": nearby["line"]["y"],
                    "w": nearby["line"]["w"],
                    "h": nearby["line"]["h"],
                    "dx": round(nearby["dx"]),
                    "dy": round(nearby["dy"]),
                    "score": round(nearby["score"]),
                },
            }
        )

    fill_sequence_fallback(red_boxes)
    red_boxes.sort(
        key=lambda box: (
            int(box["nearbyDetailNumber"]["text"]) if box.get("nearbyDetailNumber") else 999,
            box["rectPx"]["y1"],
            box["rectPx"]["x1"],
        )
    )
    draw_overlay(red_boxes)

    result = {
        "sourcePdf": str(PDF_PATH),
        "sheetNumber": SHEET_NUMBER,
        "sheetName": SHEET_NAME,
        "page": annotations["page"],
        "pageSize": {
            "pdf": {"width": annotations["pageWidthPdf"], "height": annotations["pageHeightPdf"]},
            "image": {"width": page_width_px, "height": page_height_px},
        },
        "redBoxCount": len(red_boxes),
        "redBoxes": red_boxes,
        "overlayPath": str(OVERLAY_PATH),
    }
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")

    md = []
    md.append("# ARB-D09026 紅框詳圖名稱測試")
    md.append("")
    md.append(f"來源 PDF：{PDF_PATH}")
    md.append(f"圖紙號碼：{SHEET_NUMBER}")
    md.append(f"圖紙名稱：{SHEET_NAME}")
    md.append(f"PDF 頁碼：{annotations['page']}")
    md.append(f"紅框數量：{len(red_boxes)}")
    md.append(f"定位疊圖：{OVERLAY_PATH}")
    md.append("")
    md.append("## 擷取結果")
    md.append("")
    md.append("| 紅框 | 推定詳圖編號 | 編號方法 | 修正後詳圖名稱 | OCR 原始名稱 | OCR 原始片段 |")
    md.append("|---:|---:|---|---|---|---|")
    for box in red_boxes:
        raw = "; ".join(
            f"{line['text']} @ {line['x']},{line['y']},{line['w']},{line['h']}" for line in box["linesInBox"]
        )
        detail_number = box["nearbyDetailNumber"]["text"] if box.get("nearbyDetailNumber") else ""
        number_method = box["nearbyDetailNumber"].get("method", "") if box.get("nearbyDetailNumber") else ""
        detail_name = box["detailName"] or "(未讀到紅框內文字)"
        detail_name_raw = box.get("detailNameRaw") or ""
        md.append(f"| {box['annotationIndex']} | {detail_number} | {number_method} | {detail_name} | {detail_name_raw} | {raw} |")
    md.append("")
    md.append("## 初步判斷")
    md.append("")
    md.append("- 紅框註解可直接取得座標，不需要影像偵測紅線。")
    md.append("- 紅框內文字能對應到既有 OCR 行，可大幅縮小候選範圍。")
    md.append("- 詳圖編號目前用紅框附近的數字推定；正式版建議再加入圓圈輪廓或相對位置規則。")
    REPORT_PATH.write_text("\n".join(md), encoding="utf8")

    print(json.dumps({"report": str(REPORT_PATH), "json": str(OUT_PATH), "overlay": str(OVERLAY_PATH), "redBoxCount": len(red_boxes)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
