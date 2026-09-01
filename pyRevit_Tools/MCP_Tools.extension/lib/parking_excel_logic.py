# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure, CPython-testable rules for the parking Excel updater."""

import re
import unicodedata
import sheet_layout
import takeoff_standalone


TOLERANCE_MM = 50.0

ITEMS = (
    {
        'key': 'bus',
        'label': u'大客車 300*700',
        'schedule': 'bus',
        'width_mm': 3000.0,
        'length_mm': 7000.0,
        'accessible': False,
    },
    {
        'key': 'side_car',
        'label': u'側停汽車 250*600',
        'schedule': 'car',
        'width_mm': 2500.0,
        'length_mm': 6000.0,
        'accessible': False,
    },
    {
        'key': 'general_car',
        'label': u'一般汽車 250*550',
        'schedule': 'car',
        'width_mm': 2500.0,
        'length_mm': 5500.0,
        'accessible': False,
    },
    {
        'key': 'accessible_car',
        'label': u'無障礙汽車 350*600',
        'schedule': 'car',
        'width_mm': 3500.0,
        'length_mm': 6000.0,
        'accessible': True,
    },
    {
        'key': 'general_motorcycle',
        'label': u'一般機車 100*200',
        'schedule': 'motorcycle',
        'width_mm': 1000.0,
        'length_mm': 2000.0,
        'accessible': False,
    },
    {
        'key': 'accessible_motorcycle',
        'label': u'無障礙機車 220*225',
        'schedule': 'motorcycle',
        'width_mm': 2200.0,
        'length_mm': 2250.0,
        'accessible': True,
    },
)

ITEM_BY_KEY = dict((item['key'], item) for item in ITEMS)
CAR_KEYS = ('bus', 'side_car', 'general_car', 'accessible_car')


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value)
    except Exception:
        return str(value)


def normalize_label(value):
    """Normalize Excel/Revit labels without discarding meaningful words."""
    text = unicodedata.normalize('NFKC', _text(value)).lower()
    text = text.replace(u'×', u'*').replace(u'＊', u'*').replace(u'x', u'*')
    text = re.sub(u'[（）()\\[\\]【】{}，,、:：;；]', u'', text)
    return re.sub(r'\s+', u'', text)


def _dimension_scale(a, b, source):
    normalized = normalize_label(source)
    if u'm' in normalized and u'mm' not in normalized:
        return 1000.0
    maximum = max(abs(a), abs(b))
    # Project family names use centimetres (250*550); parameter values may
    # display metres (2.50 x 5.50) while explicit millimetres are already large.
    if maximum <= 10.0:
        return 1000.0
    if maximum < 1000.0:
        return 10.0
    return 1.0


def parse_dimensions(value):
    """Return the first width/length pair as millimetres, or None."""
    text = unicodedata.normalize('NFKC', _text(value)).lower()
    text = text.replace(u'×', u'x').replace(u'＊', u'x').replace(u'*', u'x')
    match = re.search(
        r'(\d+(?:\.\d+)?)\s*(mm|cm|m)?\s*x\s*'
        r'(\d+(?:\.\d+)?)\s*(mm|cm|m)?',
        text,
    )
    if not match:
        return None
    a = float(match.group(1))
    b = float(match.group(3))
    units = (match.group(2), match.group(4))
    if 'mm' in units:
        scale = 1.0
    elif 'cm' in units:
        scale = 10.0
    elif 'm' in units:
        scale = 1000.0
    else:
        scale = _dimension_scale(a, b, text)
    return a * scale, b * scale


def is_accessible_text(value):
    normalized = normalize_label(value)
    return u'無障礙' in normalized or u'access' in normalized


def annotation_matches(value, allowed_values):
    """Return whether a Revit text value matches a selected schedule filter."""
    allowed = set(
        normalize_label(item) for item in (allowed_values or [])
        if normalize_label(item))
    return bool(allowed) and normalize_label(value) in allowed


def classify_space(schedule, width_mm=None, length_mm=None, name=u'',
                   accessible=None, tolerance_mm=TOLERANCE_MM):
    """Classify one bay, constrained by its source schedule."""
    if schedule not in ('bus', 'car', 'motorcycle'):
        raise ValueError('unknown schedule boundary: {}'.format(schedule))
    if width_mm is None or length_mm is None:
        parsed = parse_dimensions(name)
        if parsed:
            width_mm, length_mm = parsed
    if width_mm is None or length_mm is None:
        return None

    candidates = []
    for item in ITEMS:
        if item['schedule'] != schedule:
            continue
        if accessible is not None and bool(item['accessible']) != bool(accessible):
            continue
        direct = (
            abs(float(width_mm) - item['width_mm']) <= tolerance_mm and
            abs(float(length_mm) - item['length_mm']) <= tolerance_mm
        )
        rotated = (
            abs(float(width_mm) - item['length_mm']) <= tolerance_mm and
            abs(float(length_mm) - item['width_mm']) <= tolerance_mm
        )
        if direct or rotated:
            candidates.append(item['key'])
    if len(candidates) == 1:
        return candidates[0]

    if accessible is None:
        return classify_space(
            schedule, width_mm, length_mm, name,
            is_accessible_text(name), tolerance_mm)
    return None


def classify_any_space(width_mm=None, length_mm=None, name=u'',
                       accessible=None, tolerance_mm=TOLERANCE_MM):
    """Classify one bay without requiring a schedule boundary."""
    if width_mm is None or length_mm is None:
        parsed = parse_dimensions(name)
        if parsed:
            width_mm, length_mm = parsed
    if width_mm is None or length_mm is None:
        return None

    candidates = []
    for item in ITEMS:
        if accessible is not None and bool(item['accessible']) != bool(accessible):
            continue
        direct = (
            abs(float(width_mm) - item['width_mm']) <= tolerance_mm and
            abs(float(length_mm) - item['length_mm']) <= tolerance_mm
        )
        rotated = (
            abs(float(width_mm) - item['length_mm']) <= tolerance_mm and
            abs(float(length_mm) - item['width_mm']) <= tolerance_mm
        )
        if direct or rotated:
            candidates.append(item['key'])
    if len(candidates) == 1:
        return candidates[0]

    if accessible is None:
        return classify_any_space(
            width_mm, length_mm, name,
            is_accessible_text(name), tolerance_mm)
    return None


NAME_CATEGORY_HINTS = (
    # (keyword, item key) — matched against the normalized bay/family name.
    # Medium-bus (中巴) bays are counted as 大客車 (bus); their printed size
    # does not land within TOLERANCE_MM of the 300*700 bus standard.
    (u'中巴', 'bus'),
    (u'中型巴士', 'bus'),
    (u'大客車', 'bus'),
    (u'巴士', 'bus'),
)


def classify_by_name(name):
    """Return the item key implied by a bay's name, or None.

    Used only as a fallback after dimensional classification fails, so exact
    size matches are never overridden by a name keyword.
    """
    normalized = normalize_label(name)
    if not normalized:
        return None
    for keyword, key in NAME_CATEGORY_HINTS:
        if normalize_label(keyword) in normalized:
            return key
    return None


def empty_counts():
    return dict((item['key'], 0) for item in ITEMS)


# A bay is normally placed on the slab top, i.e. at or slightly above its own
# level line. The tolerance absorbs bays modelled a little under the level
# (slab top vs level line, sloped ramps) while staying far below any real
# floor-to-floor spacing.
GEOMETRIC_LEVEL_TOLERANCE_MM = 300.0

LEVEL_BASIS_MATCH = u'參數＝幾何'
LEVEL_BASIS_GEOMETRIC = u'幾何（與參數不符）'
LEVEL_BASIS_GEOMETRIC_ONLY = u'僅幾何'
LEVEL_BASIS_PARAMETER_ONLY = u'僅參數'
LEVEL_BASIS_UNKNOWN = u'無樓層資訊'


def resolve_geometric_level_ids(elevation_mm, level_catalog,
                                tolerance_mm=GEOMETRIC_LEVEL_TOLERANCE_MM):
    """Return the level ids a bay physically sits on, highest first-match.

    ``level_catalog`` is ``[(level_id, name, elevation_mm), ...]`` from one
    document. A bay belongs to the highest level at or below its own
    elevation. Levels sharing that elevation (architectural/structural twins)
    are all returned, because either of them can be the one the user ticked.
    Returns ``[]`` when the elevation or the catalog is unusable.
    """
    if elevation_mm is None:
        return []
    ordered = sorted(
        [row for row in (level_catalog or []) if row[2] is not None],
        key=lambda row: float(row[2]))
    if not ordered:
        return []
    limit = float(elevation_mm) + float(tolerance_mm)
    chosen_elevation = None
    for unused_id, unused_name, level_elevation in ordered:
        if float(level_elevation) <= limit:
            chosen_elevation = float(level_elevation)
        else:
            break
    if chosen_elevation is None:
        return []
    return [row[0] for row in ordered
            if float(row[2]) == chosen_elevation]


def level_basis(parameter_level_id, geometric_level_ids):
    """Describe which evidence decided a bay's level, for the audit trail."""
    geometric_level_ids = list(geometric_level_ids or [])
    if not geometric_level_ids:
        return (LEVEL_BASIS_PARAMETER_ONLY if parameter_level_id is not None
                else LEVEL_BASIS_UNKNOWN)
    if parameter_level_id is None:
        return LEVEL_BASIS_GEOMETRIC_ONLY
    if parameter_level_id in geometric_level_ids:
        return LEVEL_BASIS_MATCH
    return LEVEL_BASIS_GEOMETRIC


def wheel_stop_values(counts, multiplier):
    multiplier = int(multiplier)
    if multiplier not in (1, 2):
        raise ValueError('wheel-stop multiplier must be 1 or 2')
    car_total = sum(int(counts.get(key, 0)) for key in CAR_KEYS)
    return car_total, multiplier, car_total * multiplier


def row_formula_shape_ok(row, formulas):
    """Require H on the item row to derive directly from same-row F and G."""
    if not formulas:
        return False
    normalized = [
        re.sub(r"[\s$']", u'', _text(formula)).upper()
        for formula in formulas
    ]
    formula = normalized[0]
    f_ref = u'F{}'.format(int(row))
    g_ref = u'G{}'.format(int(row))
    h_ref = u'H{}'.format(int(row))
    i_ref = u'I{}'.format(int(row))
    allowed = (
        u'={}*{}'.format(f_ref, g_ref),
        u'={}*{}'.format(g_ref, f_ref),
        u'=PRODUCT({},{})'.format(f_ref, g_ref),
        u'=PRODUCT({},{})'.format(g_ref, f_ref),
    )
    h_allowed = list(allowed)
    for expression in allowed:
        body = expression[1:]
        for digits in ('0', '1', '2', '3'):
            h_allowed.append(u'=ROUND({}, {})'.format(body, digits))
            h_allowed.append(u'=ROUND({},{})'.format(body, digits))
    if formula not in h_allowed:
        return False

    if len(normalized) < 3:
        return True
    i_formula = normalized[1]
    j_formula = normalized[2]
    i_allowed = (
        u'={}'.format(h_ref),
        u'=SUM({}:{})'.format(h_ref, h_ref),
    )
    j_allowed = [
        u'={}'.format(i_ref),
    ]
    for digits in ('0', '1', '2', '3'):
        j_allowed.append(u'=ROUND({}, {})'.format(i_ref, digits))
        j_allowed.append(u'=ROUND({},{})'.format(i_ref, digits))
    return i_formula in i_allowed and j_formula in j_allowed


def _normalized_formula(formula):
    return re.sub(r"[\s$']", u'', _text(formula)).upper()


def wheel_stop_formula_multiplier(formula, rows):
    """Return the embedded wheel-stop multiplier for trusted F formulas."""
    if not formula or not rows:
        return None
    car_rows = [int(rows[key]) for key in CAR_KEYS if key in rows]
    if len(car_rows) != len(CAR_KEYS):
        return None
    car_rows = sorted(car_rows)
    if car_rows != list(range(car_rows[0], car_rows[-1] + 1)):
        return None
    car_range = u'{0}{1}:{0}{2}'.format(
        sheet_layout.column_letter(OTHER_COUNT_COL - 1),
        car_rows[0], car_rows[-1])
    normalized = _normalized_formula(formula)
    allowed = []
    for multiplier in (1, 2):
        sum_expr = u'SUM({})'.format(car_range)
        allowed.extend((
            u'={}*{}'.format(sum_expr, multiplier),
            u'={}*{}'.format(multiplier, sum_expr),
        ))
    for multiplier in (1, 2):
        if normalized in allowed and normalized.endswith(u'{}'.format(multiplier)):
            return multiplier
        if normalized in allowed and normalized.startswith(u'={}'.format(multiplier)):
            return multiplier
    return None


def protected_input_formula_shape_ok(key, row, formula, rows):
    """Whitelist F-cell formulas that can be preserved and result-checked."""
    if not formula:
        return True
    if key == 'wheel_stop' and wheel_stop_formula_multiplier(formula, rows):
        return True
    normalized = _normalized_formula(formula)
    # Literal arithmetic only. Cell references, external links, functions, and
    # volatile expressions stay blocked unless a purpose-built rule is added.
    return bool(re.match(r'^=[0-9+\-*/().]+$', normalized))


def excel_row_matches(key, value):
    normalized = normalize_label(value)
    if key == 'wheel_stop':
        return u'塑膠車輪檔' in normalized
    item = ITEM_BY_KEY[key]
    cm_width = int(round(item['width_mm'] / 10.0))
    cm_length = int(round(item['length_mm'] / 10.0))
    dims = u'{}*{}'.format(cm_width, cm_length)
    if dims not in normalized:
        return False
    if key == 'bus':
        return u'大客車' in normalized
    if key == 'side_car':
        return u'側停' in normalized and u'汽車' in normalized
    if key == 'general_car':
        return u'汽車' in normalized and not is_accessible_text(normalized)
    if key == 'accessible_car':
        return u'汽車' in normalized and is_accessible_text(normalized)
    if key == 'general_motorcycle':
        return u'機車' in normalized and not is_accessible_text(normalized)
    if key == 'accessible_motorcycle':
        return u'機車' in normalized and is_accessible_text(normalized)
    return False


def find_unique_item_rows(rows):
    """Map seven item keys to exactly one row from ``[(row, label), ...]``."""
    result = {}
    keys = ['wheel_stop'] + [item['key'] for item in ITEMS]
    for key in keys:
        matches = [row for row, label in rows if excel_row_matches(key, label)]
        if len(matches) != 1:
            raise ValueError(
                u'工項「{}」應唯一命中，實際命中列：{}'.format(
                    u'塑膠車輪檔' if key == 'wheel_stop'
                    else ITEM_BY_KEY[key]['label'],
                    u', '.join(str(row) for row in matches) or u'無',
                )
            )
        result[key] = matches[0]
    return result


# New columns are appended, never inserted: the 公式摘要 COUNTIF below points
# at column F (分類鍵) by position.
STANDALONE_DETAIL_HEADERS = (
    u'來源鍵', u'來源', u'樓層 Id', u'ElementId', u'族群／類型',
    u'分類鍵', u'分類', u'寬(mm)', u'長(mm)', u'群組內', u'狀態',
    u'樓層名稱', u'幾何樓層 Id', u'幾何樓層', u'底部高程(mm)', u'樓層判定')
STANDALONE_FORMULA_HEADERS = (
    u'分類鍵', u'工項', u'模型數量公式', u'倍率', u'計價數量公式')
STANDALONE_AUDIT_HEADERS = (u'檢核項目', u'結果', u'說明')

# 獨立匯出兩張分頁的欄位。公式以前把 F/A/C/D 這幾個字母寫死，跟表頭的排列順序
# 是兩套各自維護的真相：中間插一欄，公式不會壞掉，只會統計到隔壁欄。
STANDALONE_DETAIL_COLUMNS = [
    'source_key', 'source', 'level_id', 'element_id', 'type_name',
    'category_key', 'category', 'width_mm', 'length_mm', 'grouped',
    'status', 'level_name', 'geometry_level_id', 'geometry_level',
    'base_elevation_mm', 'level_basis',
]
STANDALONE_FORMULA_COLUMNS = [
    'category_key', 'label', 'model_qty', 'multiplier', 'billed_qty',
]
for _names, _headers, _label in (
        (STANDALONE_DETAIL_COLUMNS, STANDALONE_DETAIL_HEADERS, 'DETAIL'),
        (STANDALONE_FORMULA_COLUMNS, STANDALONE_FORMULA_HEADERS, 'FORMULA')):
    if len(_names) != len(_headers):
        raise AssertionError(
            u'STANDALONE_{0} 的欄位與表頭長度不一致'.format(_label))
STANDALONE_DETAIL = sheet_layout.SheetLayout(
    STANDALONE_DETAIL_COLUMNS, first_data_row=2,
    name=takeoff_standalone.DETAIL_SHEET)
STANDALONE_FORMULA = sheet_layout.SheetLayout(
    STANDALONE_FORMULA_COLUMNS, first_data_row=2,
    name=takeoff_standalone.FORMULA_SHEET)

# 使用者範本「其他數量」分頁的兩個數量欄。這裡是唯一定義處，parking_excel
# 與這支的驗證邏輯都從這裡取，欄位字母一律導出。
OTHER_COUNT_COL = 6      # F 數量
OTHER_WHEEL_COL = 7      # G 輪檔倍率


def _abs_detail_range(key, last_row):
    """絕對位址的跨分頁範圍（COUNTIF 需要）。"""
    col = STANDALONE_DETAIL.col(key)
    return u"'{0}'!${1}${2}:${1}${3}".format(
        takeoff_standalone.DETAIL_SHEET, col,
        STANDALONE_DETAIL.first_data_row, last_row)



def standalone_tables(takeoff, wheel_stop_multiplier):
    """Build standardized parking workbook rows from a collected takeoff."""
    details = sorted(
        list((takeoff or {}).get('details') or []),
        key=lambda row: (
            _text(row.get('source_key')),
            int(row.get('element_id') or 0)))
    detail_rows = []
    for row in details:
        detail_rows.append([
            _text(row.get('source_key')),
            _text(row.get('source_name')),
            row.get('level_id'),
            row.get('element_id'),
            _text(row.get('name')),
            _text(row.get('classification_key')),
            _text(row.get('classification_label')),
            row.get('width_mm'),
            row.get('length_mm'),
            bool(row.get('grouped')),
            _text(row.get('status')),
            _text(row.get('level_name')),
            row.get('geometric_level_id'),
            _text(row.get('geometric_level_name')),
            row.get('elevation_mm'),
            _text(row.get('level_basis')),
        ])
    detail_last = max(2, len(detail_rows) + 1)
    formula_rows = []
    for index, item in enumerate(ITEMS, 2):
        formula_rows.append([
            item['key'],
            item['label'],
            u'=COUNTIF({},{})'.format(
                _abs_detail_range('category_key', detail_last),
                STANDALONE_FORMULA.cell('category_key', index)),
            1,
            STANDALONE_FORMULA.formula(
                index, u'{model_qty}*{multiplier}'),
        ])
    wheel_row = len(formula_rows) + 2
    first_car_row = 2
    last_car_row = first_car_row + len(CAR_KEYS) - 1
    formula_rows.append([
        u'wheel_stop',
        u'塑膠車輪檔',
        STANDALONE_FORMULA.sum_of(
            'model_qty', first_car_row, last_car_row),
        int(wheel_stop_multiplier),
        STANDALONE_FORMULA.formula(
            wheel_row, u'{model_qty}*{multiplier}'),
    ])

    source_keys = set(
        _text(row.get('source_key')) for row in details
        if _text(row.get('source_key')))
    source_keys.update(
        _text(row.get('source_key'))
        for row in ((takeoff or {}).get('source_counts') or [])
        if _text(row.get('source_key')))
    source_keys = sorted(source_keys)
    unclassified = list((takeoff or {}).get('unclassified') or [])
    ignored = list((takeoff or {}).get('ignored') or [])
    candidates = list(
        (takeoff or {}).get('annotation_candidates') or [])
    level_mismatch = len([
        row for row in details
        if _text(row.get('level_basis')) == LEVEL_BASIS_GEOMETRIC])
    excluded_by_level = sum(
        int(source.get('excluded_by_level') or 0)
        for source in ((takeoff or {}).get('source_counts') or []))
    audit_rows = [
        [u'既有主檔契約', u'INFO', u'小計／其他數量'],
        [u'來源身分', u'PASS', u'、'.join(source_keys) or u'(無資料)'],
        [u'停車位總數', u'CHECK',
         u"=SUM('{0}'!{1})".format(
             takeoff_standalone.FORMULA_SHEET,
             STANDALONE_FORMULA.rng(
                 'model_qty', STANDALONE_FORMULA.first_data_row,
                 len(ITEMS) + 1))],
        [u'未分類', u'BLOCK' if unclassified else u'PASS',
         u'{} 個'.format(len(unclassified))],
        [u'忽略非車位元件', u'INFO', u'{} 個'.format(len(ignored))],
        [u'未納入標註候選', u'REVIEW' if candidates else u'PASS',
         u'{} 個'.format(len(candidates))],
        [u'不在所選樓層而排除', u'INFO', u'{} 個'.format(excluded_by_level)],
        [u'樓層參數與實際高程不符', u'REVIEW' if level_mismatch else u'PASS',
         u'{} 個（已依實際高程歸層）'.format(level_mismatch)],
    ]
    for source in (takeoff or {}).get('source_counts') or []:
        audit_rows.append([
            u'讀取範圍',
            u'PASS',
            u'{}｜{}｜{}｜納入 {} 個，依樓層排除 {} 個'.format(
                _text(source.get('source_key')),
                _text(source.get('name')),
                _text(source.get('levels')) or u'全部樓層',
                int(source.get('included') or 0),
                int(source.get('excluded_by_level') or 0)),
        ])
    return {
        'detail_headers': list(STANDALONE_DETAIL_HEADERS),
        'detail_rows': detail_rows,
        'formula_headers': list(STANDALONE_FORMULA_HEADERS),
        'formula_rows': formula_rows,
        'audit_headers': list(STANDALONE_AUDIT_HEADERS),
        'audit_rows': audit_rows,
    }
