# -*- coding: utf-8 -*-
from __future__ import division, unicode_literals

"""CAD 對齊網格匯入——純邏輯，不碰 Revit API。

一張 DWG 用 ``Placement=Origin`` 放進來之後，要做的只剩一件事：算出一個平移量，
讓 CAD 的軸線疊到 Revit 的同名 Grid 上。困難在於「同名」：

**Revit API 讀不到匯入 CAD 裡的文字。** 匯入後的幾何只有線，所以在 Revit 內
只能知道「CAD 有一組間距為 8400、8400、9000 的垂直線」，不知道哪一條叫 C1。
兩條路可以把線對上名字，本模組兩條都走：

1. **軸距序列比對**——把 CAD 一族平行軸的位置和 Revit 同方向 Grid 的位置
   比對，找出讓最多條軸重合的位移。軸距不規則時答案唯一；等距時會出現
   「差一跨」的歧義，這時一定要回報，不能挑一個看起來順眼的。
2. **軸號文字投票**——外部行程（ODA + ezdxf）直接讀 DWG 的軸號文字，每個
   找得到同名 Revit Grid 的軸號投一票給一個位移。有票就以票為準，並用軸距
   比對交叉驗證。

平面上兩族不平行的軸各自得到一個「沿法向的位移」，解 2×2 聯立就是平移向量。
CAD 軸線方向與 Revit 不一致（旋轉過）時直接拒絕：只做平移的工具默默把旋轉
的圖貼上去，比不做更糟。

座標一律用公釐、以 Revit 專案內部原點為準的 XY。
"""

import math
import re


# --- 預設值 ----------------------------------------------------------------

DEFAULT_GRID_LAYER = u'S-GRID'
DEFAULT_LABEL_LAYER = u'S-GRID-IDEN'
DEFAULT_TOLERANCE_MM = 5.0
DEFAULT_MIN_LINE_MM = 1000.0
ANGLE_TOLERANCE_DEG = 0.05
FAMILY_ANGLE_DEG = 0.5
# 軸號到軸線端點的距離上限。軸號泡泡半徑在 1/100 約 400～800mm，再加引線。
DEFAULT_LABEL_REACH_MM = 5000.0

# CAD 繪圖單位 → 公釐。INSUNITS 常常是 0（無單位）或設錯，所以不信任它，
# 改用「哪個倍率能讓最多軸號落在軸線端點旁」來決定。
CANDIDATE_SCALES = (1.0, 10.0, 1000.0, 25.4, 304.8, 100.0)

STATUS_READY = u'可執行'
STATUS_AMBIGUOUS = u'有歧義'
STATUS_FAILED = u'無法對齊'


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value)
    except Exception:
        return unicode(value)  # noqa: F821 - IronPython 2.7


# --- 樓層代碼 --------------------------------------------------------------

_CN_DIGITS = {u'〇': 0, u'零': 0, u'一': 1, u'二': 2, u'兩': 2, u'三': 3,
              u'四': 4, u'五': 5, u'六': 6, u'七': 7, u'八': 8, u'九': 9}


def chinese_number(text):
    """「一」～「九十九」→ int；不是中文數字回 ``None``。"""
    text = _text(text)
    if not text:
        return None
    if u'十' not in text:
        if len(text) == 1 and text in _CN_DIGITS:
            return _CN_DIGITS[text]
        return None
    head, unused, tail = text.partition(u'十')
    if head and head not in _CN_DIGITS:
        return None
    if tail and tail not in _CN_DIGITS:
        return None
    if len(head) > 1 or len(tail) > 1:
        return None
    tens = _CN_DIGITS[head] if head else 1
    ones = _CN_DIGITS[tail] if tail else 0
    return tens * 10 + ones


_CN = u'[〇零一二兩三四五六七八九十]+'

# 順序有意義：地下／屋頂先抓，避免「地下一層」被當成「一層」。
_FLOOR_PATTERNS = (
    (re.compile(u'地下(' + _CN + u'|\\d+)[層樓]'), 'basement'),
    (re.compile(u'(?<![A-Za-z])B(\\d+)(?:F|FL)?(?![A-Za-z0-9])', re.I),
     'basement'),
    (re.compile(u'(?:屋頂突出物?|屋突)(' + _CN + u'|\\d+)[層樓]'), 'roof_n'),
    (re.compile(u'(?<![A-Za-z])R(\\d+)(?:F|FL)(?![A-Za-z0-9])', re.I),
     'roof_n'),
    (re.compile(u'屋頂[層樓]?|屋突|(?<![A-Za-z])RF(?![A-Za-z0-9])', re.I),
     'roof'),
    (re.compile(u'(?<![地下\\d])(' + _CN + u'|\\d+)[層樓]'), 'floor'),
    (re.compile(u'(?<![A-Za-z0-9-])(\\d+)(?:F|FL)(?![A-Za-z0-9])', re.I),
     'floor'),
    (re.compile(u'(?<![A-Za-z])FL(\\d+)(?![A-Za-z0-9])', re.I), 'floor'),
)


def _as_int(token):
    token = _text(token)
    if token.isdigit():
        return int(token)
    return chinese_number(token)


def floor_code(name):
    """從檔名或視圖名稱抽出正規化的樓層代碼：``1F``、``B1``、``RF``、``R1``。

    「物流中心 一層排水平面圖」與「鮮食中心 一層平面索引圖」都得到 ``1F``——
    建築名稱不同是正常的，比對只看樓層。抽不到回 ``None``。

    注意 ``B-1F`` 這種「棟別-樓層」寫法不會被誤判成地下一層：``B`` 後面必須
    直接接數字。
    """
    text = _text(name)
    for pattern, kind in _FLOOR_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        if kind == 'roof':
            return u'RF'
        number = _as_int(match.group(1))
        if number is None:
            continue
        if kind == 'basement':
            return u'B{}'.format(number)
        if kind == 'roof_n':
            return u'R{}'.format(number)
        return u'{}F'.format(number)
    return None


def pair_views_to_files(views, files):
    """``views``：``[(key, name)]``；``files``：``[(key, name)]``。

    回傳 ``{view_key: {'file': file_key or None, 'code': ..., 'reason': ...}}``。
    同一樓層有兩個以上的檔案時不猜，``file`` 留 ``None`` 並說明，交給使用者
    在預覽表手動選。
    """
    by_code = {}
    for file_key, file_name in files:
        code = floor_code(file_name)
        if code:
            by_code.setdefault(code, []).append(file_key)

    result = {}
    for view_key, view_name in views:
        code = floor_code(view_name)
        entry = {'file': None, 'code': code, 'reason': u''}
        if code is None:
            entry['reason'] = u'視圖名稱抽不到樓層代碼'
        else:
            matches = by_code.get(code, [])
            if len(matches) == 1:
                entry['file'] = matches[0]
            elif not matches:
                entry['reason'] = u'沒有 {} 的 CAD 檔'.format(code)
            else:
                entry['reason'] = u'{} 有 {} 個 CAD 檔，請手動選'.format(
                    code, len(matches))
        result[view_key] = entry
    return result


def layer_matches(layer, wanted):
    """圖層比對不分大小寫；xref 綁定後的 ``底圖$0$S-GRID`` 或
    ``底圖|S-GRID`` 也算。刻意**不**做包含比對：``S-GRID`` 不能吃到
    ``S-GRID-IDEN``（軸號泡泡的圓會變成假軸線）。"""
    layer = _text(layer).upper()
    wanted = _text(wanted).upper()
    if not wanted:
        return False
    return layer == wanted or layer.endswith(u'$' + wanted) or \
        layer.endswith(u'|' + wanted)


# --- 幾何 ------------------------------------------------------------------

def _direction_deg(start, end):
    """線的方向角，正規化到 [0, 180)。"""
    angle = math.degrees(math.atan2(end[1] - start[1], end[0] - start[0]))
    angle = angle % 180.0
    if angle >= 180.0 - 1e-9:
        angle = 0.0
    return angle


def _angle_gap(a, b):
    gap = abs(a - b) % 180.0
    return min(gap, 180.0 - gap)


def _normal(angle_deg):
    rad = math.radians(angle_deg)
    return (-math.sin(rad), math.cos(rad))


def _offset(point, normal):
    return point[0] * normal[0] + point[1] * normal[1]


def _length(start, end):
    return math.hypot(end[0] - start[0], end[1] - start[1])


def make_line(start, end, name=None):
    return {'start': (float(start[0]), float(start[1])),
            'end': (float(end[0]), float(end[1])),
            'name': name}


def group_families(lines, min_length=DEFAULT_MIN_LINE_MM,
                   angle_tol=FAMILY_ANGLE_DEG):
    """把線依方向分族。回傳依線數由多到少排序的
    ``[{'angle': deg, 'lines': [line, ...]}]``。短於 ``min_length`` 的線不計——
    軸號泡泡的圓被拆成的短線、引線，都不是軸。"""
    families = []
    for line in lines:
        if _length(line['start'], line['end']) < min_length:
            continue
        angle = _direction_deg(line['start'], line['end'])
        home = None
        for family in families:
            if _angle_gap(family['angle'], angle) <= angle_tol:
                home = family
                break
        if home is None:
            families.append({'angle': angle, 'lines': [line]})
        else:
            home['lines'].append(line)
    families.sort(key=lambda f: -len(f['lines']))
    return families


def family_positions(family, tolerance=DEFAULT_TOLERANCE_MM):
    """一族平行線沿法向的位置，合併重合（同一條軸被打斷成數段）。

    回傳排序後的 ``[{'pos': mm, 'name': ..., 'lines': [...]}]``。
    """
    normal = _normal(family['angle'])
    entries = []
    for line in family['lines']:
        mid = ((line['start'][0] + line['end'][0]) / 2.0,
               (line['start'][1] + line['end'][1]) / 2.0)
        entries.append((_offset(mid, normal), line))
    entries.sort(key=lambda item: item[0])

    merged = []
    for pos, line in entries:
        if merged and abs(pos - merged[-1]['pos']) <= tolerance:
            merged[-1]['lines'].append(line)
            if not merged[-1]['name'] and line.get('name'):
                merged[-1]['name'] = line.get('name')
            continue
        merged.append({'pos': pos, 'name': line.get('name'),
                       'lines': [line]})
    return merged


def match_family(cad_family, revit_families, angle_tol=ANGLE_TOLERANCE_DEG):
    """找出與 CAD 這一族方向相同的 Revit 族。回傳 ``(family, gap_deg)``；
    ``gap_deg`` 超過容差時 family 為 ``None``，呼叫端據此回報旋轉不符。"""
    best = None
    best_gap = None
    for family in revit_families:
        gap = _angle_gap(family['angle'], cad_family['angle'])
        if best_gap is None or gap < best_gap:
            best, best_gap = family, gap
    if best is None or best_gap > angle_tol:
        return None, best_gap
    return best, best_gap


def spacing_shifts(cad_positions, revit_positions,
                   tolerance=DEFAULT_TOLERANCE_MM):
    """所有候選位移與各自能讓幾條軸重合，由多到少排序。

    候選來自每一對 (Revit 位置 − CAD 位置)，互相落在容差內的合併。
    回傳 ``[{'shift': mm, 'hits': n, 'names': [...]}]``。
    """
    cad = [entry['pos'] for entry in cad_positions]
    raw = []
    for r_entry in revit_positions:
        for c in cad:
            raw.append(r_entry['pos'] - c)
    raw.sort()

    clusters = []
    for value in raw:
        if clusters and abs(value - clusters[-1][-1]) <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])

    scored = []
    for cluster in clusters:
        shift = sum(cluster) / len(cluster)
        hits = 0
        names = []
        for c in cad:
            for r_entry in revit_positions:
                if abs(c + shift - r_entry['pos']) <= tolerance:
                    hits += 1
                    if r_entry.get('name'):
                        names.append(r_entry['name'])
                    break
        scored.append({'shift': shift, 'hits': hits, 'names': names})
    scored.sort(key=lambda item: (-item['hits'], abs(item['shift'])))
    return scored


def _distance_point_segment(point, start, end):
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_sq = dx * dx + dy * dy
    if length_sq <= 0:
        return math.hypot(point[0] - start[0], point[1] - start[1])
    t = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    near = (start[0] + t * dx, start[1] + t * dy)
    return math.hypot(point[0] - near[0], point[1] - near[1])


def _nearest_endpoint_distance(point, line):
    return min(math.hypot(point[0] - p[0], point[1] - p[1])
               for p in (line['start'], line['end']))


def normalize_label(text):
    """軸號正規化：去空白、全形轉半形、轉大寫。"""
    value = _text(text).strip()
    out = []
    for ch in value:
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:
            ch = unichr_(code - 0xFEE0)
        if not ch.isspace():
            out.append(ch)
    return u''.join(out).upper()


def unichr_(code):
    try:
        return unichr(code)  # noqa: F821 - IronPython 2.7
    except NameError:
        return chr(code)


def assign_labels(labels, families, reach=DEFAULT_LABEL_REACH_MM):
    """把每個軸號配到最近的軸線端點。

    ``labels``：``[{'text': ..., 'x': mm, 'y': mm}]``（已換算成 Revit 座標）。
    回傳 ``[(label_name, family_index, position_mm, distance_mm)]``。軸號離每條
    軸線端點都超過 ``reach`` 的丟掉——它可能是別的圖面（索引圖）上的字。
    """
    assigned = []
    for label in labels:
        name = normalize_label(label.get('text'))
        if not name:
            continue
        point = (float(label['x']), float(label['y']))
        best = None
        for index, family in enumerate(families):
            normal = _normal(family['angle'])
            for line in family['lines']:
                distance = _nearest_endpoint_distance(point, line)
                if best is None or distance < best[3]:
                    mid = ((line['start'][0] + line['end'][0]) / 2.0,
                           (line['start'][1] + line['end'][1]) / 2.0)
                    best = (name, index, _offset(mid, normal), distance)
        if best is not None and best[3] <= reach:
            assigned.append(best)
    return assigned


def choose_label_scale(labels, cad_lines, reach=DEFAULT_LABEL_REACH_MM,
                       scales=CANDIDATE_SCALES,
                       min_length=DEFAULT_MIN_LINE_MM):
    """決定軸號座標（CAD 繪圖單位）乘多少倍才會落在匯入後的軸線旁。

    Revit 的 ``ImportUnit.Default`` 會自己判斷單位，外部讀檔拿到的卻是原始
    繪圖單位，兩者必須用同一個倍率對起來。回傳 ``(scale, hits)``。
    """
    # 只看夠長的線：軸號泡泡本身的短線就在字旁邊，拿它來比會讓任何倍率都「命中」。
    cad_lines = [line for line in cad_lines
                 if _length(line['start'], line['end']) >= min_length]
    best = (None, 0)
    for scale in scales:
        hits = 0
        for label in labels:
            point = (float(label['x']) * scale, float(label['y']) * scale)
            for line in cad_lines:
                if _nearest_endpoint_distance(point, line) <= reach:
                    hits += 1
                    break
        if hits > best[1]:
            best = (scale, hits)
    return best


def label_shift(assigned, family_index, revit_positions,
                tolerance=DEFAULT_TOLERANCE_MM):
    """用軸號投票決定一族的位移。

    每個能在 Revit 找到同名 Grid 的軸號投一票（Revit 位置 − CAD 位置），
    票數最多的一組取平均。回傳 ``{'shift', 'votes', 'names', 'disagree'}``
    或 ``None``（沒有任何同名軸）。``disagree`` 是投給其他位移的軸號——
    不為空代表 CAD 裡有軸號標錯或同一張圖含多份平面。
    """
    by_name = {}
    for entry in revit_positions:
        if entry.get('name'):
            by_name[normalize_label(entry['name'])] = entry['pos']

    votes = []
    for name, index, pos, unused in assigned:
        if index != family_index or name not in by_name:
            continue
        votes.append((by_name[name] - pos, name))
    if not votes:
        return None
    votes.sort()

    groups = []
    for value, name in votes:
        if groups and abs(value - groups[-1][-1][0]) <= tolerance:
            groups[-1].append((value, name))
        else:
            groups.append([(value, name)])
    groups.sort(key=lambda g: -len(g))
    top = groups[0]
    tied = len(groups) > 1 and len(groups[1]) == len(top)
    shift = sum(value for value, unused in top) / len(top)
    disagree = []
    for group in groups[1:]:
        disagree.extend(name for unused, name in group)
    return {'shift': shift, 'votes': len(top),
            'names': sorted(set(name for unused, name in top)),
            'disagree': sorted(set(disagree)), 'tied': tied}


def solve_translation(angle_a, shift_a, angle_b, shift_b):
    """兩族法向位移 → XY 平移向量。兩族平行時回 ``None``。"""
    na = _normal(angle_a)
    nb = _normal(angle_b)
    det = na[0] * nb[1] - na[1] * nb[0]
    if abs(det) < 1e-6:
        return None
    x = (shift_a * nb[1] - shift_b * na[1]) / det
    y = (na[0] * shift_b - nb[0] * shift_a) / det
    return (x, y)


# --- 整合 ------------------------------------------------------------------

def _family_decision(cad_family, revit_family, family_index, assigned,
                     tolerance):
    """一族軸的位移決策。回傳 dict：shift / method / detail / status。"""
    cad_pos = family_positions(cad_family, tolerance)
    revit_pos = family_positions(revit_family, tolerance)
    shifts = spacing_shifts(cad_pos, revit_pos, tolerance)
    by_label = label_shift(assigned, family_index, revit_pos, tolerance) \
        if assigned else None

    decision = {'shift': None, 'method': u'', 'detail': u'',
                'status': STATUS_FAILED, 'hits': 0,
                'cad_count': len(cad_pos), 'revit_count': len(revit_pos)}

    if by_label is not None and not by_label['tied']:
        decision['shift'] = by_label['shift']
        decision['method'] = u'軸號'
        hits = 0
        for entry in shifts:
            if abs(entry['shift'] - by_label['shift']) <= tolerance:
                hits = entry['hits']
                break
        decision['hits'] = hits
        detail = u'軸號 {} 同意（{} 票）'.format(
            u'、'.join(by_label['names']), by_label['votes'])
        if by_label['disagree']:
            detail += u'；{} 投給別的位置'.format(
                u'、'.join(by_label['disagree']))
        detail += u'；軸距重合 {} 條'.format(hits)
        decision['detail'] = detail
        decision['status'] = STATUS_READY
        return decision

    if not shifts or shifts[0]['hits'] == 0:
        decision['detail'] = u'CAD 與 Revit 軸線沒有可重合的位置'
        return decision

    best = shifts[0]
    decision['shift'] = best['shift']
    decision['hits'] = best['hits']
    decision['method'] = u'軸距'
    rivals = [s for s in shifts[1:] if s['hits'] == best['hits']]
    if rivals or best['hits'] < 2:
        decision['status'] = STATUS_AMBIGUOUS
        if best['hits'] < 2:
            decision['detail'] = u'只有 1 條軸重合，無法確認'
        else:
            decision['detail'] = u'有 {} 個位置同樣重合 {} 條軸（等距軸網），' \
                u'需要軸號才能決定'.format(len(rivals) + 1, best['hits'])
        return decision
    decision['status'] = STATUS_READY
    decision['detail'] = u'軸距重合 {} / {} 條（{}）'.format(
        best['hits'], len(cad_pos), u'、'.join(best['names'][:6]))
    return decision


def plan_alignment(cad_lines, revit_grids, labels=None,
                   tolerance=DEFAULT_TOLERANCE_MM,
                   min_length=DEFAULT_MIN_LINE_MM,
                   label_reach=DEFAULT_LABEL_REACH_MM):
    """一張 CAD 的完整對齊決策。

    - ``cad_lines``：匯入後、平移前的軸線（Revit 座標，mm）。
    - ``revit_grids``：``make_line(start, end, name)`` 形式的 Revit Grid。
    - ``labels``：已換算成 Revit 座標的軸號，可省略。

    回傳 ``{'status', 'translation': (x, y) or None, 'families': [...],
    'reason'}``。
    """
    plan = {'status': STATUS_FAILED, 'translation': None, 'families': [],
            'reason': u''}
    cad_families = group_families(cad_lines, min_length)
    revit_families = group_families(revit_grids, 0.0)
    if len(revit_families) < 2:
        plan['reason'] = u'Revit 裡找不到兩個方向的直線 Grid'
        return plan
    if len(cad_families) < 2:
        plan['reason'] = u'CAD 軸線圖層找不到兩個方向的軸線（讀到 {} 條線）'.format(
            len(cad_lines))
        return plan

    first = cad_families[0]
    second = None
    for family in cad_families[1:]:
        if _angle_gap(family['angle'], first['angle']) > 1.0:
            second = family
            break
    if second is None:
        plan['reason'] = u'CAD 軸線全部平行，無法定出交點'
        return plan

    used = [first, second]
    assigned = assign_labels(labels or [], used, label_reach) if labels \
        else []

    decisions = []
    for index, cad_family in enumerate(used):
        revit_family, gap = match_family(cad_family, revit_families)
        if revit_family is None:
            plan['reason'] = (u'CAD 軸線方向 {:.3f}° 與最接近的 Revit Grid 差 '
                              u'{:.3f}°——CAD 被旋轉過，本工具只做平移'
                              .format(cad_family['angle'], gap or 0.0))
            return plan
        decision = _family_decision(cad_family, revit_family, index,
                                    assigned, tolerance)
        decision['angle'] = revit_family['angle']
        decisions.append(decision)
    plan['families'] = decisions
    plan['labels_used'] = len(assigned)

    if any(d['status'] == STATUS_FAILED for d in decisions):
        plan['reason'] = u'；'.join(d['detail'] for d in decisions
                                   if d['status'] == STATUS_FAILED)
        return plan

    translation = solve_translation(decisions[0]['angle'],
                                    decisions[0]['shift'],
                                    decisions[1]['angle'],
                                    decisions[1]['shift'])
    if translation is None:
        plan['reason'] = u'兩族軸線平行'
        return plan
    plan['translation'] = translation
    if any(d['status'] == STATUS_AMBIGUOUS for d in decisions):
        plan['status'] = STATUS_AMBIGUOUS
        plan['reason'] = u'；'.join(d['detail'] for d in decisions
                                   if d['status'] == STATUS_AMBIGUOUS)
    else:
        plan['status'] = STATUS_READY
    return plan


def describe(plan):
    """給預覽表用的一行說明。"""
    if plan.get('status') == STATUS_FAILED:
        return plan.get('reason') or u''
    parts = [u'{}：{}'.format(d['method'], d['detail'])
             for d in plan.get('families') or []]
    if plan.get('status') == STATUS_AMBIGUOUS and plan.get('reason'):
        parts.append(plan['reason'])
    return u'｜'.join(parts)


def report_rows(entries):
    """CSV 報告的列。``entries`` 每筆含 view / file / status / plan / id。"""
    rows = [[u'視圖', u'CAD 檔', u'樓層', u'狀態', u'方式', u'平移X(mm)',
             u'平移Y(mm)', u'元素ID', u'說明']]
    for entry in entries:
        plan = entry.get('plan') or {}
        translation = plan.get('translation')
        methods = u'/'.join(d.get('method', u'')
                            for d in plan.get('families') or [])
        rows.append([
            _text(entry.get('view')), _text(entry.get('file')),
            _text(entry.get('code')), _text(entry.get('status')), methods,
            u'{:.2f}'.format(translation[0]) if translation else u'',
            u'{:.2f}'.format(translation[1]) if translation else u'',
            _text(entry.get('id') or u''),
            _text(entry.get('note') or describe(plan)),
        ])
    return rows


def csv_text(rows):
    """最小的 CSV 編碼（含 BOM 由呼叫端決定）。"""
    lines = []
    for row in rows:
        cells = []
        for cell in row:
            value = _text(cell)
            if any(ch in value for ch in (u',', u'"', u'\n')):
                value = u'"' + value.replace(u'"', u'""') + u'"'
            cells.append(value)
        lines.append(u','.join(cells))
    return u'\r\n'.join(lines) + u'\r\n'
