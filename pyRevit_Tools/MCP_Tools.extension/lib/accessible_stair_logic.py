# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for 無障礙樓梯數量檢核 (JAC 10.05).

建築技術規則建築設計施工編 §167-2：建築物設置之直通樓梯，至少應有一座為
無障礙樓梯。

One sentence of law, three things Revit cannot answer on its own — which is
where all the design here comes from.

**Counting designations would produce false passes.** A stair carrying the
project's 無障礙 marker but built with 20cm risers is not an 無障礙樓梯; it is
a mislabelled ordinary stair. So the quota counts stairs that are *both*
designated and geometrically qualifying, and 「已標示但不符」 is reported as
its own category — on a real project that row is the whole point of running
this.

**Which limit applies is a declaration, not a measurement.** 規範 304.1 sets
R≦16cm / T≧26cm; 304.4 relaxes it to R≦18cm / T≧24cm, but only for 第2層以上
供住宅使用之公寓大廈 whose 樓地板面積 ≦240m². Nothing in the model says which
one a project is, so the caller passes it in and the report names the rule it
applied. Defaulting silently to the looser pair is exactly how a checker comes
to bless a non-compliant building.

**A stair is not a Revit element.** 直通樓梯 means a run of stairs continuous
from a storey down to the 避難層, which in a model is several ``Stairs``
elements — or one ``MultistoryStairs`` — that this module chains back together.
Chains that never reach the 避難層 are not part of the §167-2 denominator.

Where an answer genuinely cannot be derived — a winder or spiral run, whose
級深 varies along the tread — the verdict is 需人工確認 and never 符合. A
building whose only candidate is unresolved is reported as 無法判定, not as a
pass and not as a failure.

Lengths are millimetres.
"""


# 規範 304.1 一般情形；304.4 為公寓大廈特別規定。兩者的 2R+T 區間相同。
RULE_GENERAL = 'general'
RULE_APARTMENT = 'apartment'

RULE_LIMITS = {
    RULE_GENERAL: {
        'max_riser_mm': 160.0,
        'min_tread_mm': 260.0,
        'label': u'規範 304.1（一般）：級高 ≦16cm、級深 ≧26cm',
        'clause': u'304.1',
    },
    RULE_APARTMENT: {
        'max_riser_mm': 180.0,
        'min_tread_mm': 240.0,
        'label': u'規範 304.4（公寓大廈特別規定）：級高 ≦18cm、級深 ≧24cm',
        'clause': u'304.4',
    },
}

MIN_TWO_R_PLUS_T_MM = 550.0
MAX_TWO_R_PLUS_T_MM = 650.0

# Purely to absorb the float noise in Revit's computed ActualRiserHeight. It is
# not a regulatory tolerance: 「16公分以下」 is a 最大值, and 規範 103.1's 3%
# allowance explicitly excludes dimensions marked 最大/最小/限定範圍.
EPSILON_MM = 0.5

# Two stairs meeting at a level are only the same stairwell if they are also in
# the same place. Without this, every stack of unrelated stairwells on adjacent
# floors merges into one chain and the 直通樓梯 count collapses.
DEFAULT_CHAIN_TOLERANCE_MM = 2000.0

SINGLE_BUILDING = u'（整棟）'

# Verdicts, worst-last so a chain carrying several stairs takes the weakest.
VERDICT_OK = u'符合'
VERDICT_REVIEW = u'需人工確認'
VERDICT_FAIL = u'不符'

FAIL_RISER = u'級高超過上限'
FAIL_TREAD = u'級深不足'
FAIL_FORMULA = u'2R+T 超出 55~65cm'
FAIL_OPEN_RISER = u'露空式樓梯（規範 302.1）'
FAIL_NOT_UNIFORM = u'同一樓梯級高或級深不統一（規範 304.1）'
REVIEW_RUN_STYLE = u'旋轉/扇形梯段，級深沿踏面變化，需人工確認'
REVIEW_NO_DIMENSION = u'讀不到級高或級深'

FAIL_ORDER = (
    FAIL_OPEN_RISER,
    FAIL_RISER,
    FAIL_TREAD,
    FAIL_FORMULA,
    FAIL_NOT_UNIFORM,
    REVIEW_RUN_STYLE,
    REVIEW_NO_DIMENSION,
)

# StairsRunStyle values whose 級深 is not constant across the tread.
VARIABLE_TREAD_STYLES = (u'Spiral', u'Winder')


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def _number(value, fallback=None):
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def rule_label(rule):
    return RULE_LIMITS.get(rule, RULE_LIMITS[RULE_GENERAL])['label']


def stair_failures(record, rule=RULE_GENERAL):
    """Rule breaches for one ``Stairs`` element, worst-first.

    Returns ``(failures, reviews)``. A review is something this module refuses
    to rule on rather than something it found wrong, and the two must not be
    merged: a reviewed stair may still turn out compliant, but it can never be
    counted toward the quota on our say-so.
    """
    limits = RULE_LIMITS.get(rule, RULE_LIMITS[RULE_GENERAL])
    failures = []
    reviews = []

    riser = _number(record.get('riser_mm'))
    tread = _number(record.get('tread_mm'))

    if riser is None or tread is None or riser <= 0 or tread <= 0:
        reviews.append(REVIEW_NO_DIMENSION)
    else:
        if riser > limits['max_riser_mm'] + EPSILON_MM:
            failures.append(FAIL_RISER)
        if tread < limits['min_tread_mm'] - EPSILON_MM:
            failures.append(FAIL_TREAD)
        combined = 2.0 * riser + tread
        if (combined < MIN_TWO_R_PLUS_T_MM - EPSILON_MM
                or combined > MAX_TWO_R_PLUS_T_MM + EPSILON_MM):
            failures.append(FAIL_FORMULA)

    # ``risers_present`` is Revit's own 梯級間有無垂直板; ``None`` means the
    # parameter was unreadable, which is not evidence of an open riser.
    if record.get('risers_present') is False:
        failures.append(FAIL_OPEN_RISER)

    for style in record.get('run_styles') or []:
        if _text(style) in VARIABLE_TREAD_STYLES:
            reviews.append(REVIEW_RUN_STYLE)
            break

    ordered_fail = [item for item in FAIL_ORDER if item in failures]
    ordered_review = [item for item in FAIL_ORDER if item in reviews]
    return ordered_fail, ordered_review


def _centroid(record):
    return (_number(record.get('centre_x_mm'), 0.0),
            _number(record.get('centre_y_mm'), 0.0))


def _close_enough(first, second, tolerance_mm):
    ax, ay = _centroid(first)
    bx, by = _centroid(second)
    return abs(ax - bx) <= tolerance_mm and abs(ay - by) <= tolerance_mm


def build_chains(records, tolerance_mm=DEFAULT_CHAIN_TOLERANCE_MM):
    """Group ``Stairs`` records into vertical runs — one chain per stairwell.

    A ``MultistoryStairs`` group is authoritative: Revit already states those
    pieces are one stair. Everything else is chained by 「上一段的頂部樓層等於
    下一段的基準樓層」, but only when the two also sit in roughly the same place
    — level numbers alone would weld separate stairwells together.
    """
    items = list(records or [])
    if not items:
        return []

    parent = {}

    def find(key):
        while parent.get(key, key) != key:
            parent[key] = parent.get(parent[key], parent[key])
            key = parent[key]
        return key

    def union(first, second):
        a, b = find(first), find(second)
        if a != b:
            parent[a] = b

    for record in items:
        parent.setdefault(record.get('id'), record.get('id'))

    # Revit's own grouping first.
    by_multistory = {}
    for record in items:
        key = record.get('multistory_id')
        if _number(key, -1) > 0:
            by_multistory.setdefault(key, []).append(record)
    for group in by_multistory.values():
        for record in group[1:]:
            union(group[0].get('id'), record.get('id'))

    # Then level adjacency, within one building and one location.
    for lower in items:
        for upper in items:
            if lower is upper:
                continue
            if _text(lower.get('building')) != _text(upper.get('building')):
                continue
            top = lower.get('top_level_id')
            base = upper.get('base_level_id')
            if top is None or base is None or top != base:
                continue
            if not _close_enough(lower, upper, tolerance_mm):
                continue
            union(lower.get('id'), upper.get('id'))

    buckets = {}
    order = []
    for record in items:
        key = find(record.get('id'))
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(record)

    chains = []
    for key in order:
        members = sorted(buckets[key],
                         key=lambda item: (_number(item.get('base_elevation_mm'),
                                                   0.0),
                                           _number(item.get('id'), 0)))
        level_ids = []
        for record in members:
            for field in ('base_level_id', 'top_level_id'):
                value = record.get(field)
                if value is not None and value not in level_ids:
                    level_ids.append(value)
            for value in record.get('multistory_level_ids') or []:
                if value not in level_ids:
                    level_ids.append(value)
        bases = [_number(item.get('base_elevation_mm')) for item in members]
        tops = [_number(item.get('top_elevation_mm')) for item in members]
        bases = [value for value in bases if value is not None]
        tops = [value for value in tops if value is not None]
        chains.append({
            'key': key,
            'members': members,
            'ids': [item.get('id') for item in members],
            'building': _text(members[0].get('building')) or SINGLE_BUILDING,
            'level_ids': level_ids,
            'bottom_mm': min(bases) if bases else None,
            'top_mm': max(tops) if tops else None,
            'name': _text(members[0].get('name'))
                    or _text(members[0].get('type_name')),
        })
    return chains


def serves_refuge(chain, refuge_level_id):
    """Does this chain actually reach the 避難層?

    §93 defines a 直通樓梯 as one reaching 避難層或地面, so a stair running only
    between upper floors is not part of what §167-2 counts. Level identity is
    used rather than elevation: two levels can share a height.
    """
    if refuge_level_id is None:
        return True
    return refuge_level_id in (chain.get('level_ids') or [])


def _uniform(members, field):
    values = [_number(item.get(field)) for item in members]
    values = [value for value in values if value is not None and value > 0]
    if len(values) < 2:
        return True
    return max(values) - min(values) <= EPSILON_MM


def evaluate_chain(chain, rule=RULE_GENERAL):
    """Verdict for one stairwell: 符合 / 不符 / 需人工確認."""
    failures = []
    reviews = []
    for record in chain.get('members') or []:
        member_fail, member_review = stair_failures(record, rule)
        for item in member_fail:
            if item not in failures:
                failures.append(item)
        for item in member_review:
            if item not in reviews:
                reviews.append(item)

    # 304.1「樓梯上所有梯級之級高及級深應統一」 spans the whole stair, so it
    # can only be judged once the pieces are back together.
    if not (_uniform(chain.get('members'), 'riser_mm')
            and _uniform(chain.get('members'), 'tread_mm')):
        if FAIL_NOT_UNIFORM not in failures:
            failures.append(FAIL_NOT_UNIFORM)

    if failures:
        verdict = VERDICT_FAIL
    elif reviews:
        verdict = VERDICT_REVIEW
    else:
        verdict = VERDICT_OK

    result = dict(chain)
    result['failures'] = [item for item in FAIL_ORDER if item in failures]
    result['reviews'] = [item for item in FAIL_ORDER if item in reviews]
    result['verdict'] = verdict
    result['designated'] = any(bool(item.get('designated'))
                               for item in chain.get('members') or [])
    result['designation_values'] = sorted(set(
        _text(item.get('designation_value'))
        for item in chain.get('members') or []
        if _text(item.get('designation_value'))))
    widths = [_number(item.get('min_run_width_mm'))
              for item in chain.get('members') or []]
    widths = [value for value in widths if value is not None and value > 0]
    result['min_run_width_mm'] = min(widths) if widths else None
    risers = [_number(item.get('riser_mm')) for item in chain.get('members')
              or []]
    treads = [_number(item.get('tread_mm')) for item in chain.get('members')
              or []]
    risers = [value for value in risers if value is not None and value > 0]
    treads = [value for value in treads if value is not None and value > 0]
    result['riser_mm'] = max(risers) if risers else None
    result['tread_mm'] = min(treads) if treads else None
    return result


# Building outcomes.
BUILDING_PASS = u'符合'
BUILDING_FAIL = u'不符'
BUILDING_UNDECIDED = u'無法判定'
BUILDING_NO_STAIR = u'無直通樓梯'


def evaluate(records, rule=RULE_GENERAL, refuge_level_id=None,
             tolerance_mm=DEFAULT_CHAIN_TOLERANCE_MM):
    """Full §167-2 check, per building."""
    chains = [evaluate_chain(chain, rule)
              for chain in build_chains(records, tolerance_mm)]

    buildings = {}
    order = []
    for chain in chains:
        key = chain['building']
        if key not in buildings:
            buildings[key] = {
                'building': key,
                'direct': [],
                'not_direct': [],
                'qualified': [],
                'designated_failing': [],
                'designated_review': [],
                'candidates': [],
            }
            order.append(key)
        entry = buildings[key]
        chain['serves_refuge'] = serves_refuge(chain, refuge_level_id)
        if chain['serves_refuge']:
            entry['direct'].append(chain)
            if chain['designated']:
                if chain['verdict'] == VERDICT_OK:
                    entry['qualified'].append(chain)
                elif chain['verdict'] == VERDICT_REVIEW:
                    entry['designated_review'].append(chain)
                else:
                    entry['designated_failing'].append(chain)
            elif chain['verdict'] == VERDICT_OK:
                # Not claimed as accessible, but nothing in its dimensions
                # would stop it — worth telling the designer about.
                entry['candidates'].append(chain)
        else:
            entry['not_direct'].append(chain)

    results = []
    for key in order:
        entry = buildings[key]
        if not entry['direct']:
            entry['outcome'] = BUILDING_NO_STAIR
        elif entry['qualified']:
            entry['outcome'] = BUILDING_PASS
        elif entry['designated_review']:
            entry['outcome'] = BUILDING_UNDECIDED
        else:
            entry['outcome'] = BUILDING_FAIL
        results.append(entry)

    return {
        'rule': rule,
        'rule_label': rule_label(rule),
        'refuge_level_id': refuge_level_id,
        'tolerance_mm': _number(tolerance_mm, DEFAULT_CHAIN_TOLERANCE_MM),
        'chains': chains,
        'buildings': results,
        'total_stairs': len(list(records or [])),
        'failed_ids': [stair_id
                       for entry in results
                       for chain in entry['designated_failing']
                       for stair_id in chain['ids']],
    }


def has_problem(result):
    """True when at least one building is not demonstrably compliant."""
    for entry in result.get('buildings') or []:
        if entry['outcome'] != BUILDING_PASS:
            return True
        if entry['designated_failing'] or entry['designated_review']:
            return True
    return False


def _chain_line(chain):
    detail = u'；'.join(chain['failures'] + chain['reviews'])
    riser = chain.get('riser_mm')
    tread = chain.get('tread_mm')
    if riser and tread:
        size = u'級高 {:.0f} / 級深 {:.0f} mm'.format(riser, tread)
    else:
        size = u'尺寸不明'
    return u'　{}（{} 段）　{}　{}'.format(
        chain['name'] or u'(未命名)', len(chain['ids']), size, detail).rstrip()


def report_lines(result):
    lines = [
        u'依建築技術規則建築設計施工編 §167-2：',
        u'　建築物設置之直通樓梯，至少應有一座為無障礙樓梯。',
        u'',
        u'採用尺寸規則：{}'.format(result['rule_label']),
        u'共 {} 座樓梯元素，歸併為 {} 組樓梯'.format(
            result['total_stairs'], len(result['chains'])),
        u'',
    ]

    for entry in result['buildings']:
        lines.append(u'【{}】{}'.format(entry['building'], entry['outcome']))
        lines.append(u'　通達避難層的樓梯：{} 組（其中已標示為無障礙 {} 組）'
                     .format(len(entry['direct']),
                             len(entry['qualified'])
                             + len(entry['designated_failing'])
                             + len(entry['designated_review'])))

        if entry['outcome'] == BUILDING_PASS:
            lines.append(u'　✓ 有 {} 組同時已標示且尺寸符合。'
                         .format(len(entry['qualified'])))
        elif entry['outcome'] == BUILDING_NO_STAIR:
            lines.append(u'　找不到通達避難層的樓梯，無法就本條檢核。')
        elif entry['outcome'] == BUILDING_UNDECIDED:
            lines.append(u'　? 已標示的樓梯尚無法判定，本條未能認定符合。')
        else:
            lines.append(u'　✗ 沒有任何一組同時已標示且尺寸符合。')

        if entry['designated_failing']:
            lines.append(u'　已標示為無障礙但尺寸不符（不計入本條）：')
            for chain in entry['designated_failing'][:8]:
                lines.append(_chain_line(chain))
        if entry['designated_review']:
            lines.append(u'　已標示為無障礙但需人工確認：')
            for chain in entry['designated_review'][:8]:
                lines.append(_chain_line(chain))
        if not entry['qualified'] and entry['candidates']:
            lines.append(u'　未標示但尺寸符合、可考慮指定為無障礙樓梯：')
            for chain in entry['candidates'][:8]:
                lines.append(_chain_line(chain))
        if entry['not_direct']:
            lines.append(u'　未通達避難層、不列入本條計算：{} 組'
                         .format(len(entry['not_direct'])))
        lines.append(u'')

    lines.append(u'本工具只檢核 §167-2 的「數量」與 規範 302.1／304 的尺寸。')
    lines.append(u'扶手（305）、警示設施（306）、平台高差（303.3）須另行人工確認。')
    return u'\n'.join(lines).rstrip()
