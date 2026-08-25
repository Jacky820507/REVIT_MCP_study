# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure offset maths for 牆轉區域線 (JAC 04.08 / 04.09).

A wall's ``LocationCurve`` is **not** its centreline. It is whichever of six
positions the wall type's Location Line setting names — centreline, core
centreline, either finish face, or either core face — so reading the location
curve and calling it 牆心 puts every generated boundary half a wall thickness
out on the walls that happen to use a different setting, and it does so
silently.

Everything here is therefore measured on one axis: distance from the wall's
**geometric centreline**, positive toward ``Wall.Orientation`` (the exterior
side). Layers run exterior-to-interior, so layer 0 sits against the exterior
face. From that, each of the six named positions has a definite value, and the
distance to offset the location curve by is simply
``target - location_line_position``.

Units are whatever the caller uses consistently — the maths is only sums and
halves of widths, so feet in gives feet out.
"""


MODE_CENTRE = 'centre'
MODE_CORE = 'core'
MODE_FACE = 'face'

MODE_LABELS = {
    MODE_CENTRE: u'牆心線（每道牆一條）',
    MODE_CORE: u'核心層邊界（每道牆兩條）',
    MODE_FACE: u'牆面（每道牆兩條）',
}

# The six values Revit's WallLocationLine can take, as reported by the API.
LOCATION_CENTRE = 'WallCenterline'
LOCATION_CORE_CENTRE = 'CoreCenterline'
LOCATION_FACE_EXTERIOR = 'FinishFaceExterior'
LOCATION_FACE_INTERIOR = 'FinishFaceInterior'
LOCATION_CORE_EXTERIOR = 'CoreExterior'
LOCATION_CORE_INTERIOR = 'CoreInterior'

BLOCK_NO_CURVE = u'牆沒有可用的定位線'
BLOCK_NO_WIDTH = u'牆厚度為 0'
BLOCK_NO_CORE = u'這道牆沒有核心層，無法產生核心邊界'
BLOCK_CURTAIN = u'帷幕牆沒有可用的層構造'
BLOCK_STACKED = u'堆疊牆本身沒有層構造（請改用其成員牆）'


def _number(value, fallback=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def layer_offsets(total_width, layer_widths=None, first_core=None,
                  last_core=None):
    """Named positions on the wall's normal axis, measured from the centreline.

    Positive is toward ``Wall.Orientation``. The core is not assumed to be
    centred: its two faces are found by walking the layer widths inward from
    each side, which is the only way to place it on an asymmetric build-up.
    """
    width = abs(_number(total_width))
    half = width / 2.0
    offsets = {
        'exterior': half,
        'interior': -half,
        'centre': 0.0,
    }

    widths = [abs(_number(value)) for value in layer_widths or []]
    has_core = (widths and first_core is not None and last_core is not None
                and 0 <= first_core <= last_core < len(widths))
    if not has_core:
        offsets['core_exterior'] = None
        offsets['core_interior'] = None
        offsets['core_centre'] = None
        return offsets

    outer = sum(widths[:first_core])
    inner = sum(widths[last_core + 1:])
    core_exterior = half - outer
    core_interior = -half + inner
    offsets['core_exterior'] = core_exterior
    offsets['core_interior'] = core_interior
    offsets['core_centre'] = (core_exterior + core_interior) / 2.0
    return offsets


def location_line_position(kind, offsets):
    """Where the wall's location curve sits on that axis, or ``None``.

    ``None`` means the wall reports a core-based location line while having no
    core to measure it against — a contradiction worth surfacing rather than
    silently treating as the centreline.
    """
    table = {
        LOCATION_CENTRE: 'centre',
        LOCATION_CORE_CENTRE: 'core_centre',
        LOCATION_FACE_EXTERIOR: 'exterior',
        LOCATION_FACE_INTERIOR: 'interior',
        LOCATION_CORE_EXTERIOR: 'core_exterior',
        LOCATION_CORE_INTERIOR: 'core_interior',
    }
    key = table.get(u'{}'.format(kind or ''))
    if key is None:
        # An unrecognised setting is treated as the centreline, which is
        # Revit's own default, but the caller is told via the flag below.
        return offsets.get('centre')
    return offsets.get(key)


def targets_for_mode(mode, offsets):
    """The positions this mode wants a boundary line at."""
    if mode == MODE_CENTRE:
        return [('牆心', offsets['centre'])]
    if mode == MODE_FACE:
        return [('外牆面', offsets['exterior']),
                ('內牆面', offsets['interior'])]
    if mode == MODE_CORE:
        return [('核心外緣', offsets.get('core_exterior')),
                ('核心內緣', offsets.get('core_interior'))]
    raise ValueError('unknown mode: {}'.format(mode))


def block_reason(record, mode):
    """Why this wall cannot produce boundary lines in this mode, or ``''``."""
    if record.get('is_curtain'):
        return BLOCK_CURTAIN
    if record.get('is_stacked'):
        return BLOCK_STACKED
    if not record.get('has_curve'):
        return BLOCK_NO_CURVE
    if abs(_number(record.get('width'))) <= 0:
        return BLOCK_NO_WIDTH
    if mode == MODE_CORE:
        offsets = layer_offsets(record.get('width'),
                                record.get('layer_widths'),
                                record.get('first_core'),
                                record.get('last_core'))
        if offsets.get('core_exterior') is None:
            return BLOCK_NO_CORE
    return u''


def plan_offsets(record, mode):
    """``[(label, distance)]`` to offset this wall's location curve by.

    The distance is ``target - location_line_position``, so a wall whose
    location line already sits where the mode wants a line yields 0 and is
    offset not at all.
    """
    offsets = layer_offsets(record.get('width'), record.get('layer_widths'),
                            record.get('first_core'), record.get('last_core'))
    origin = location_line_position(record.get('location_line'), offsets)
    if origin is None:
        # Core-based location line on a wall with no core: fall back to the
        # centreline so the wall is still usable, and say so.
        origin = 0.0
    results = []
    for label, target in targets_for_mode(mode, offsets):
        if target is None:
            continue
        results.append((label, target - origin))
    return results


def build_plan(records, mode=MODE_CENTRE):
    """Split walls into those that yield boundary lines and those that cannot."""
    if mode not in MODE_LABELS:
        raise ValueError('unknown mode: {}'.format(mode))
    seeds = []
    blocked = []
    for record in records or []:
        reason = block_reason(record, mode)
        if reason:
            blocked.append({'record': record, 'reason': reason})
            continue
        offsets = plan_offsets(record, mode)
        if not offsets:
            blocked.append({'record': record, 'reason': BLOCK_NO_CORE})
            continue
        seeds.append({'record': record, 'offsets': offsets})
    return {
        'mode': mode,
        'total': len(records or []),
        'seeds': seeds,
        'blocked': blocked,
        'line_count': sum(len(item['offsets']) for item in seeds),
    }


def plan_lines(plan):
    lines = [
        u'產生方式：{}'.format(MODE_LABELS.get(plan['mode'], plan['mode'])),
        u'',
        u'掃描牆 {} 道'.format(plan['total']),
        u'可產生區域線的牆：{} 道，共 {} 條線（尚未扣除重複）'.format(
            len(plan['seeds']), plan['line_count']),
    ]
    if plan['blocked']:
        lines.append(u'')
        lines.append(u'✗ 略過 {} 道：'.format(len(plan['blocked'])))
        counts = {}
        for row in plan['blocked']:
            counts[row['reason']] = counts.get(row['reason'], 0) + 1
        for reason in sorted(counts, key=lambda key: -counts[key]):
            lines.append(u'　{}：{} 道'.format(reason, counts[reason]))
    return u'\n'.join(lines)
