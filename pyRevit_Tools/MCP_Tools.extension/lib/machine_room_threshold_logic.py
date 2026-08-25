# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for the machine-room stainless-steel threshold updater."""

import re
import unicodedata

import room_takeoff_sources_logic as room_order_logic

try:
    _character = unichr
except NameError:
    _character = chr


INCLUDE = 'include'
REVIEW = 'review'
EXCLUDE = 'exclude'

HIGH_RISK_WORDS = (
    u'泵房', u'水泵', u'加壓', u'消防泵', u'消防機房', u'冰水主機',
    u'冰水泵', u'發電機', u'水箱', u'水池', u'污水泵', u'廢水泵',
    u'污水處理',
)
ELECTRICAL_WORDS = (
    u'高壓', u'低壓', u'配電', u'變電', u'電氣室', u'弱電', u'電信',
    u'資訊機房', u'server', u'mdf', u'中控', u'中央控制', u'防災中心',
    u'ups', u'不斷電', u'電池室',
)
AIR_SMOKE_WORDS = (
    u'風機房', u'排風機房', u'排氣機房', u'進風機房', u'空調箱',
    u'ahu', u'mau', u'排煙',
)
INCLUDE_WORDS = HIGH_RISK_WORDS + ELECTRICAL_WORDS + AIR_SMOKE_WORDS


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value)
    except Exception:
        return str(value)


SEPARATORS = u'[\\s（）()\\[\\]【】{}，,、:：;；._\\-_/\\\\]'


def _fold(value):
    return unicodedata.normalize('NFKC', _text(value)).lower().replace(
        u'鏽', u'銹')


def normalize_text(value):
    return re.sub(SEPARATORS, u'', _fold(value))


def normalize_spaced(value):
    """Like ``normalize_text`` but separators collapse to one space.

    ``normalize_text`` deletes separators, which is what label and header
    matching needs, but it also turns ``SERVER ROOM`` into ``serverroom`` —
    there is then no boundary left for an ASCII keyword to anchor on.
    """
    return re.sub(u' +', u' ', re.sub(SEPARATORS, u' ', _fold(value))).strip()


def _is_ascii_word(value):
    return bool(re.match(r'^[a-z0-9]+$', value))


def contains_keyword(text, word):
    """Substring match, except ASCII keywords need a latin word boundary.

    ``ups``/``mdf``/``ahu`` are real machine-room markers, but as bare
    substrings they also fire inside unrelated latin words (``GROUPS``,
    ``MAUSOLEUM``). CJK keywords keep plain substring matching on the
    separator-free form — Chinese room names have no word separators to
    anchor on, and ``消防 泵房`` must still match ``泵房``.
    """
    needle = normalize_text(word)
    if not needle:
        return False
    if _is_ascii_word(needle):
        return bool(re.search(
            r'(?<![a-z0-9])' + re.escape(needle) + r'(?![a-z0-9])',
            normalize_spaced(text)))
    return needle in normalize_text(text)


def classify_room(name):
    """Return include/review/exclude from the default room-name rules."""
    if any(contains_keyword(name, word) for word in INCLUDE_WORDS):
        return INCLUDE
    if u'機房' in normalize_text(name):
        return REVIEW
    return EXCLUDE


def room_display(room):
    """Human-readable ``[狀態] 房號 房名`` fragment used by the UI and preview."""
    return u'{} {}'.format(
        _text(room.get('number')), _text(room.get('name'))).strip()


def room_source_display(room):
    """``鮮食中心｜B139 電氣室`` — the model a room came from stays visible.

    Room numbers collide across documents while pointing at completely
    different rooms (F125 is 電氣室 in the host and 女廁 in the 鮮食中心 link),
    so a linked room may never be shown as a bare number+name. Host rooms keep
    the plain form: they are the majority and prefixing every one of them would
    only push the number and name off the visible width.
    """
    body = room_display(room)
    label = _text(room.get('source_label'))
    if not label or room.get('source_key', HOST_SOURCE) == HOST_SOURCE:
        return body
    return u'{}｜{}'.format(label, body)


def room_matches_query(room, query):
    """Free-text filter over room number, name and source model.

    The classification label is deliberately not searchable: it is ASCII
    (``include``/``exclude``), so a one-letter filter would match every room.
    The source label is searchable so "鮮食" narrows the list to one link.
    """
    needle = normalize_text(query)
    if not needle:
        return True
    haystack = normalize_text(u'{} {} {}'.format(
        _text(room.get('number')), _text(room.get('name')),
        _text(room.get('source_label'))))
    return needle in haystack


HOST_SOURCE = 'host'


def link_source_key(link_id):
    return u'link:{}'.format(link_id)


def level_key(source_key, level_id):
    """Composite level identity: ``host:123`` / ``link:456:789``.

    Neither a level name nor an ElementId is unique across documents — the host
    and every link number their own elements from 1 — so the source model has
    to be part of the key.
    """
    return u'{}:{}'.format(source_key, level_id)


def room_uid(source_key, element_id):
    """Composite room identity, for the same reason ``level_key`` exists.

    A door is matched against selected rooms by ElementId, and those repeat
    between the host and a link; keying by document keeps a linked 女廁 from
    being answered with the host's 電氣室.
    """
    return u'{}:{}'.format(source_key, element_id)


def level_filter_for_source(source_key, selected_levels):
    """Level keys chosen for this source, or ``None`` when it is unfiltered.

    Filtering is per source model: a model with no level selected contributes
    every level. Making one link's level selection also silence the host would
    reproduce the failure this feature exists to fix — rooms quietly missing
    from a list the user cannot see them in.
    """
    prefix = u'{}:'.format(source_key)
    keys = set(
        u'{}'.format(key) for key in (selected_levels or ())
        if u'{}'.format(key).startswith(prefix))
    return keys or None


def classification_counts(rooms):
    counts = {INCLUDE: 0, REVIEW: 0, EXCLUDE: 0}
    for room in rooms:
        key = room.get('classification')
        if key in counts:
            counts[key] += 1
    return counts


def is_threshold_label(value):
    value = normalize_text(value)
    return u'不銹鋼門檻機房' in value


def _is_room_number_header(value):
    return _room_number_header_score(value) > 0


def _is_room_name_header(value):
    return _room_name_header_score(value) > 0


def _room_number_header_score(value):
    value = normalize_text(value)
    if value in (u'房號', u'房間編號', u'空間編號', u'roomnumber'):
        return 2
    if value == u'編號':
        return 1
    return 0


def _room_name_header_score(value):
    value = normalize_text(value)
    if value in (u'房名', u'房間名稱', u'空間名稱', u'roomname'):
        return 2
    if value == u'名稱':
        return 1
    return 0


def _is_length_header(value):
    return normalize_text(value) in (u'長', u'長度', u'length')


def _is_quantity_header(value):
    return normalize_text(value) in (u'數量', u'量', u'quantity', u'qty')


def find_room_header(cells):
    """Find one header row from ``[(row, col, value), ...]``."""
    by_row = {}
    for row, col, value in cells:
        entry = by_row.setdefault(int(row), {'number': [], 'name': []})
        number_score = _room_number_header_score(value)
        name_score = _room_name_header_score(value)
        if number_score:
            entry['number'].append((number_score, int(col)))
        if name_score:
            entry['name'].append((name_score, int(col)))
    matches = []
    for row, entry in by_row.items():
        if not entry['number'] or not entry['name']:
            continue
        best_number_score = max(item[0] for item in entry['number'])
        best_name_score = max(item[0] for item in entry['name'])
        number_cols = [
            item[1] for item in entry['number']
            if item[0] == best_number_score
        ]
        name_cols = [
            item[1] for item in entry['name']
            if item[0] == best_name_score
        ]
        if len(number_cols) == 1 and len(name_cols) == 1:
            matches.append((row, number_cols[0], name_cols[0]))
    if len(matches) != 1:
        raise ValueError(
            u'房號/房名表頭應唯一命中，實際命中：{}'.format(
                u', '.join(str(item[0]) for item in matches) or u'無'))
    return matches[0]


def find_unique_target(cells):
    matches = [
        (sheet, int(row), int(col))
        for sheet, row, col, value in cells
        if is_threshold_label(value)
    ]
    if len(matches) != 1:
        raise ValueError(
            u'不鏽鋼門檻(機房)工項應唯一命中，實際命中：{}'.format(
                len(matches)))
    return matches[0]


def find_unique_input_target(cells_by_sheet, target_cells):
    """Resolve the one threshold row that belongs to an input table.

    The same item label can legitimately appear on subtotal/index sheets.
    A writable target must also have a resolvable quantity/length header pair
    on the same worksheet; this keeps the address dynamic without treating
    formula mirrors as input rows.
    """
    matches = []
    rejected = []
    for sheet, row, col, value in target_cells:
        if not is_threshold_label(value):
            continue
        try:
            header_row, quantity_col, length_col = find_input_columns(
                cells_by_sheet.get(sheet, []), int(row), int(col))
            matches.append((
                sheet, int(row), int(col),
                header_row, quantity_col, length_col,
            ))
        except ValueError as error:
            rejected.append(u'{}!{}{}：{}'.format(
                sheet, column_letters(col), int(row), _text(error)))
    if len(matches) != 1:
        addresses = [
            u'{}!{}{}'.format(sheet, column_letters(col), row)
            for sheet, row, col, _, _, _ in matches
        ]
        detail = u'、'.join(addresses) or u'無'
        if rejected:
            detail += u'\n已排除：' + u'\n'.join(rejected)
        raise ValueError(
            u'不鏽鋼門檻(機房)可寫入工項應唯一命中，實際命中：{}（{}）'.format(
                len(matches), detail))
    return matches[0]


def find_input_columns(cells, target_row, label_col):
    """Find the nearest quantity/length pair right of the target label."""
    rows = {}
    for row, col, value in cells:
        row = int(row)
        if row >= int(target_row):
            continue
        entry = rows.setdefault(row, {'quantity': [], 'length': []})
        if _is_quantity_header(value):
            entry['quantity'].append(int(col))
        if _is_length_header(value):
            entry['length'].append(int(col))
    candidates_by_row = {}
    for row, entry in rows.items():
        quantities = sorted(set(
            col for col in entry['quantity'] if col > int(label_col)))
        lengths = sorted(set(
            col for col in entry['length'] if col > int(label_col)))
        header_columns = sorted(set(quantities + lengths))
        pairs = []
        for quantity_col in quantities:
            for length_col in lengths:
                if quantity_col >= length_col:
                    continue
                # Do not pair across another quantity/length group.
                between = [
                    col for col in header_columns
                    if quantity_col < col < length_col
                ]
                if between:
                    continue
                pairs.append((row, quantity_col, length_col))
        if pairs:
            candidates_by_row[row] = pairs
    if not candidates_by_row:
        raise ValueError(u'目標工項上方找不到唯一的數量/長度表頭。')
    nearest_row = max(candidates_by_row)
    row_pairs = candidates_by_row[nearest_row]
    nearest_length = min(item[2] for item in row_pairs)
    nearest = [item for item in row_pairs if item[2] == nearest_length]
    if len(nearest) != 1:
        raise ValueError(u'數量/長度輸入欄無法唯一定位。')
    return nearest[0]


def column_letters(column):
    value = int(column)
    result = u''
    while value:
        value, remainder = divmod(value - 1, 26)
        result = _character(65 + remainder) + result
    return result


def formula_references_inputs(formula, row, quantity_col, length_col):
    normalized = _text(formula).replace(u'$', u'').replace(u' ', u'').upper()
    if not normalized.startswith(u'='):
        return False
    quantity_ref = u'{}{}'.format(column_letters(quantity_col), int(row))
    length_ref = u'{}{}'.format(column_letters(length_col), int(row))
    refs = re.findall(r'(?<![A-Z0-9_])([A-Z]{1,3}[0-9]+)', normalized)
    return quantity_ref in refs and length_ref in refs


BROKEN_REFERENCE = u'#REF!'


def is_broken_reference(formula):
    """A formula Excel has already invalidated by a row/sheet deletion.

    Row-indexed formulas into 內牆 break whenever 空間表更新 removes a room's
    row from that sheet — the workbook's own ``=SUM(內牆!M16:M484)-F19`` has
    always had this exposure, and an index-based 門檻 formula shares it.
    """
    return BROKEN_REFERENCE in _text(formula)


def rebuild_running_total(formula, sheet_name, column, first_row, last_row,
                          minus_ref):
    """Repair ``=SUM(<sheet>!#REF!)-F19`` back to a real range.

    Only this exact shape is repaired; anything else is left for a human, so a
    formula that merely happens to be broken is never rewritten into something
    the estimator did not have.
    """
    value = _text(formula).replace(u' ', u'')
    expected = u'=SUM({}!{})-{}'.format(
        sheet_reference(sheet_name), BROKEN_REFERENCE, minus_ref)
    if value.upper() != expected.upper():
        return None
    return u'=SUM({}!{}{}:{}{})-{}'.format(
        sheet_reference(sheet_name), column, int(first_row),
        column, int(last_row), minus_ref)


def is_safe_length_formula(formula):
    """Allow only numeric addition, count*length terms, or SUM of constants.

    ``count*length`` has to be on the whitelist because it is one of the shapes
    this workflow itself writes; otherwise the next run would refuse to
    overwrite its own output.
    """
    value = _text(formula).replace(u' ', u'')
    if not value:
        return True
    if not value.startswith(u'='):
        return True
    if is_broken_reference(value):
        # Already destroyed: a #REF! formula holds no recoverable information,
        # so refusing to overwrite it only leaves the sheet broken. The caller
        # still surfaces it loudly instead of repairing silently.
        return True
    body = value[1:]
    number = r'(?:\d+(?:\.\d+)?|\.\d+)'
    term = r'(?:' + number + r'(?:\*' + number + r')?)'
    if re.match(r'^' + term + r'(?:\+' + term + r')*$', body):
        return True
    if re.match(r'^SUM\(' + number + r'(?:[;,]' + number + r')*\)$', body,
                re.IGNORECASE):
        return True
    return is_single_column_reference_formula(formula) is not None


_REFERENCE_TERM = re.compile(
    r"^(?P<sum>SUM\()?"
    r"(?P<sheet>'(?:[^']|'')+'|[^!+*/^&()]+)!"
    r"\$?(?P<col>[A-Z]{1,3})\$?(?P<row>\d+)"
    r"(?::\$?(?P<col2>[A-Z]{1,3})\$?(?P<row2>\d+))?"
    r"(?(sum)\))$",
    re.IGNORECASE)


def is_single_column_reference_formula(formula):
    """``(sheet, column, [rows])`` when the formula only sums one column.

    This is the shape this workflow writes when it indexes the opening-width
    column, so it has to be recognised as overwritable. Anything referencing a
    second sheet or a second column returns ``None`` and stays protected — the
    guard still refuses to clobber a formula it does not understand.
    """
    value = _text(formula).replace(u' ', u'')
    if not value.startswith(u'='):
        return None
    sheet = column = None
    rows = []
    for part in value[1:].split(u'+'):
        match = _REFERENCE_TERM.match(part)
        if match is None:
            return None
        columns = [match.group('col').upper()]
        row_values = [int(match.group('row'))]
        if match.group('col2'):
            columns.append(match.group('col2').upper())
            row_values.append(int(match.group('row2')))
            if row_values[1] < row_values[0]:
                return None
        elif match.group('sum'):
            # SUM() around a single cell is fine, but a bare range is not.
            pass
        if len(set(columns)) != 1:
            return None
        name = match.group('sheet').strip(u"'").replace(u"''", u"'")
        if sheet is None:
            sheet, column = name, columns[0]
        elif sheet != name or column != columns[0]:
            return None
        if len(row_values) == 2:
            rows.extend(range(row_values[0], row_values[1] + 1))
        else:
            rows.append(row_values[0])
    if sheet is None:
        return None
    return (sheet, column, rows)


# Measured on 物流中心工項-0720.xls with Excel 16.0: a .xls (BIFF8) sheet takes
# at most 30 arguments per function — so =SUM(w1,...,w31) fails with
# COMException 0x800A03EC — and about 180 terms (~720 chars) in an addition
# chain. .xlsx allows 255 arguments and much longer formulas. Budgets are set
# below the measured ceilings.
XLS_FORMULA_BUDGET = 700
XLSX_FORMULA_BUDGET = 8000


def format_length(value):
    text = (u'{:.10f}'.format(float(value))).rstrip(u'0').rstrip(u'.')
    return text or u'0'


def build_addition_chain(widths):
    """``=0.9+1.8+1.2`` — the shape a cost workbook is written in by hand."""
    values = [format_length(width) for width in widths]
    return u'={}'.format(u'+'.join(values or [u'0']))


def build_grouped_formula(widths):
    """``=12*0.9+7*1.8`` — same total, compact, still reads as a takeoff."""
    order = []
    counts = {}
    for width in widths:
        key = format_length(width)
        if key not in counts:
            counts[key] = 0
            order.append(key)
        counts[key] += 1
    terms = [u'{}*{}'.format(counts[key], key) for key in order]
    return u'={}'.format(u'+'.join(terms or [u'0']))


def _is_opening_width_header(value):
    return normalize_text(value) in (u'寬', u'寬度', u'width')


def find_opening_width_column(cells, header_row, name_col):
    """The single 寬 header on the room table's header row, right of 空間名稱.

    The sheet and column are discovered, not hardcoded: a different workbook
    can put the opening index anywhere as long as it keeps a 編號/空間名稱 pair
    and one 寬 column.
    """
    columns = sorted(set(
        int(col) for row, col, value in cells
        if int(row) == int(header_row) and int(col) > int(name_col)
        and _is_opening_width_header(value)))
    if len(columns) != 1:
        raise ValueError(
            u'開口寬度欄應唯一命中，實際命中：{}'.format(len(columns)))
    return columns[0]


def index_openings(cells, header_row, number_col, name_col, width_col):
    """``[(row, number, name, width), ...]`` for every priced opening.

    A room owns a block of rows: only its first row repeats 編號/空間名稱, the
    following opening rows leave them blank, so the last seen room is carried
    forward.
    """
    by_cell = {}
    for row, col, value in cells:
        by_cell[(int(row), int(col))] = value
    rows = sorted(set(
        int(row) for row, col, value in cells if int(row) > int(header_row)))
    openings = []
    number = name = u''
    for row in rows:
        new_number = _text(by_cell.get((row, int(number_col)), u'')).strip()
        new_name = _text(by_cell.get((row, int(name_col)), u'')).strip()
        if new_number or new_name:
            number = new_number or number
            name = new_name or name
        raw = by_cell.get((row, int(width_col)))
        if raw is None or not _text(raw).strip():
            continue
        try:
            width = float(raw)
        except (TypeError, ValueError):
            continue
        if width <= 0:
            continue
        openings.append((row, number, name, width))
    return openings


def select_opening_rows(openings, selected_rooms):
    """Rows of the opening index that belong to the selected rooms.

    Returns ``(rows, total, matched_room_keys)``. Room identity uses the same
    number-then-name rule as the rest of this workflow.
    """
    rows = []
    total = 0.0
    matched = set()
    for row, number, name, width in openings:
        if not room_matches(selected_rooms, number, name):
            continue
        rows.append(row)
        total += float(width)
        matched.add(room_key(number, name))
    return rows, total, matched


def unmatched_rooms(selected_rooms, matched_keys):
    """Selected rooms that have no priced opening in the index."""
    missing = []
    for room in selected_rooms:
        if room_key(room.get('number'), room.get('name')) not in matched_keys:
            missing.append(room)
    return missing


def collapse_row_runs(rows):
    """``[16,17,18,30]`` -> ``[(16,18),(30,30)]``."""
    runs = []
    for row in sorted(set(int(value) for value in rows)):
        if runs and row == runs[-1][1] + 1:
            runs[-1][1] = row
        else:
            runs.append([row, row])
    return [(start, end) for start, end in runs]


def sheet_reference(sheet_name):
    """Quote the sheet name only when Excel needs it."""
    name = _text(sheet_name)
    if re.search(r"[\s'\"!\[\]{}<>+\-*/^&=,;:()]", name) or re.match(
            r'^\d', name):
        return u"'{}'".format(name.replace(u"'", u"''"))
    return name


def build_reference_formula(sheet_name, column, rows,
                            max_chars=XLS_FORMULA_BUDGET):
    """``=SUM(內牆!M16:M20)+內牆!M30`` — traceable to the opening index.

    Consecutive rows collapse into ranges, and each range gets its own ``SUM``
    joined with ``+`` rather than one ``SUM`` holding every range: a single
    function caps at 30 arguments in .xls, and a real project reaches that.
    """
    sheet = sheet_reference(sheet_name)
    parts = []
    for start, end in collapse_row_runs(rows):
        if start == end:
            parts.append(u'{}!{}{}'.format(sheet, column, start))
        else:
            parts.append(u'SUM({}!{}{}:{}{})'.format(
                sheet, column, start, column, end))
    formula = u'={}'.format(u'+'.join(parts or [u'0']))
    if len(formula) > max_chars:
        raise ValueError(
            u'索引公式長度 {} 超過此 Excel 格式上限 {}，無法寫入。'.format(
                len(formula), max_chars))
    return formula


def build_length_formula(widths, max_chars=XLS_FORMULA_BUDGET):
    """Per-door chain when it fits, else the grouped form.

    ``=SUM(...)`` is deliberately not used: it caps at 30 arguments in .xls.
    """
    chain = build_addition_chain(widths)
    if len(chain) <= max_chars:
        return chain
    grouped = build_grouped_formula(widths)
    if len(grouped) <= max_chars:
        return grouped
    raise ValueError(
        u'門寬公式長度 {} 超過此 Excel 格式上限 {}，無法寫入。'.format(
            len(grouped), max_chars))


def room_key(number, name):
    return normalize_text(number), normalize_text(name)


def room_matches(selected_rooms, number, name):
    """Prefer number+name; use name only when either side lacks a number."""
    number_key, name_key = room_key(number, name)
    for selected in selected_rooms:
        selected_number, selected_name = room_key(
            selected.get('number'), selected.get('name'))
        if number_key and selected_number:
            if number_key == selected_number and name_key == selected_name:
                return True
        elif name_key and name_key == selected_name:
            return True
    return False


def describe_door(record):
    """``ElementId 123 | B101 排風機房 ↔ 走廊`` — enough to find the door.

    A door from a link is prefixed with its model, because its ElementId only
    identifies it inside that document.
    """
    sides = []
    for prefix in ('from', 'to'):
        side = u'{} {}'.format(
            _text(record.get(prefix + '_number')),
            _text(record.get(prefix + '_name'))).strip()
        sides.append(side or u'(無房間)')
    label = _text(record.get('source_label'))
    origin = u'ElementId {}'.format(record.get('element_id'))
    if label and record.get('source_key', HOST_SOURCE) != HOST_SOURCE:
        origin = u'{}｜{}'.format(label, origin)
    return u'{} | {} ↔ {}'.format(origin, sides[0], sides[1])


def door_uid(record):
    """Per-document door identity; ``key`` when the caller supplied one."""
    key = record.get('key')
    if key:
        return u'{}'.format(key)
    return room_uid(record.get('source_key') or HOST_SOURCE,
                    record.get('element_id'))


def summarize_doors(records):
    """De-duplicate per document, sum widths, and report blocking rows.

    Only doors actually included (a machine-room door) can block: an included
    door missing a valid width is a real data gap. Doors that are not included
    are skipped silently — an unrelated project door with no room association
    must never block the machine-room threshold update.
    """
    seen = set()
    included = []
    warnings = []
    blockers = []
    for record in records:
        uid = door_uid(record)
        if uid in seen:
            continue
        seen.add(uid)
        if not record.get('included'):
            continue
        width_m = record.get('width_m')
        if width_m is None or float(width_m) <= 0:
            message = u'門無有效寬度參數：{}'.format(describe_door(record))
            warnings.append(message)
            blockers.append(message)
            continue
        included.append(record)
    total = sum((float(item['width_m']) for item in included), 0.0)
    return {
        'doors': included,
        'total_m': total,
        'warnings': warnings,
        'blockers': blockers,
    }


def write_is_blocked(excel_blockers, door_summary):
    return bool(list(excel_blockers or []) + list(door_summary.get('blockers') or []))


STANDALONE_DETAIL_HEADERS = (
    u'來源鍵', u'來源模型', u'門 ElementId',
    u'From 房號', u'From 房名', u'To 房號', u'To 房名', u'門寬(m)')
STANDALONE_FORMULA_HEADERS = (u'項目', u'公式', u'單位')
STANDALONE_AUDIT_HEADERS = (u'檢核項目', u'結果', u'說明')


def standalone_tables(selected_rooms, door_summary, scopes):
    """Build auditable machine-room-threshold standalone sheet rows."""
    doors = sorted(
        list((door_summary or {}).get('doors') or []),
        key=lambda row: (
            _text(row.get('source_key')),
            room_order_logic.room_number_sort_key(
                row.get('from_number')),
            room_order_logic.room_number_sort_key(
                row.get('to_number')),
            int(row.get('element_id') or 0)))
    detail_rows = []
    for row in doors:
        detail_rows.append([
            _text(row.get('source_key')) or HOST_SOURCE,
            _text(row.get('source_label')) or u'主模型',
            row.get('element_id'),
            _text(row.get('from_number')),
            _text(row.get('from_name')),
            _text(row.get('to_number')),
            _text(row.get('to_name')),
            float(row.get('width_m') or 0.0),
        ])
    detail_last = len(detail_rows) + 1
    if detail_rows:
        count_formula = u'=COUNTA(\'數量明細\'!C2:C{})'.format(detail_last)
        length_formula = u'=SUM(\'數量明細\'!H2:H{})'.format(detail_last)
    else:
        count_formula = u'=0'
        length_formula = u'=0'
    formula_rows = [
        [u'機房門數', count_formula, u'樘'],
        [u'不鏽鋼門檻（機房）總長', length_formula, u'm'],
    ]

    selected_by_source = {}
    for room in selected_rooms or []:
        key = _text(room.get('source_key')) or HOST_SOURCE
        selected_by_source[key] = selected_by_source.get(key, 0) + 1
    audit_rows = [
        [u'既有主檔契約', u'INFO', u'小計／其他長度'],
        [u'選取房間', u'PASS', u'；'.join(
            u'{}={} 間'.format(key, selected_by_source[key])
            for key in sorted(selected_by_source)) or u'0 間'],
    ]
    for scope in scopes or []:
        audit_rows.append([
            u'讀取範圍',
            u'PASS' if scope.get('loaded', True) else u'BLOCK',
            u'{}｜{}｜{}｜{} 間'.format(
                _text(scope.get('source_key')) or _text(scope.get('label')),
                _text(scope.get('label')),
                _text(scope.get('levels')),
                int(scope.get('room_count') or 0)),
        ])
    blockers = list((door_summary or {}).get('blockers') or [])
    warnings = list((door_summary or {}).get('warnings') or [])
    audit_rows.append([
        u'門寬完整性',
        u'BLOCK' if blockers else u'PASS',
        u'；'.join(blockers or warnings) or u'納入門皆有有效寬度',
    ])
    audit_rows.append([
        u'總長交叉檢核',
        u'CHECK',
        u'=\'公式摘要\'!B3',
    ])
    return {
        'detail_headers': list(STANDALONE_DETAIL_HEADERS),
        'detail_rows': detail_rows,
        'formula_headers': list(STANDALONE_FORMULA_HEADERS),
        'formula_rows': formula_rows,
        'audit_headers': list(STANDALONE_AUDIT_HEADERS),
        'audit_rows': audit_rows,
    }
