# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure rules for matching a linked model's levels to the host's — JAC 04.10.

牆轉區域線 already works on host walls (JAC 04.08/04.09, the 依牆 mode of
區域線重新生成). Pulling the walls from a Revit link adds exactly two problems,
and this module owns the second one.

The first is geometric and belongs on the Revit side: link coordinates are not
host coordinates, so every curve needs ``GetTotalTransform`` applied — and the
wall's *normal* needs ``OfVector`` rather than ``OfPoint``, because a direction
must not pick up the translation.

The second is that **link levels and host levels are different elements**. A
link's 「3FL」 may sit at a different elevation from the host's, may be named
differently, or may not exist at all. Nothing can be assumed, so this module
only ever *proposes* a match by elevation and reports how good it is; the
caller is expected to let a person confirm it. Drawing a floor's walls onto
the wrong storey is invisible in plan and produces areas that look right and
are not.

Elevations are millimetres.
"""


MATCH_EXACT = u'高程相同'
MATCH_NEAR = u'高程相近'
MATCH_FAR = u'高程差距大'
MATCH_NONE = u'找不到樓層'

# Levels closer than this are treated as the same storey. Slab thickness and
# structural offsets routinely put a link's level a few tens of mm from the
# host's without them being different floors.
DEFAULT_TOLERANCE_MM = 50.0


def _number(value, fallback=None):
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value).strip()
    except Exception:
        return str(value).strip()


def match_level(host_elevation_mm, link_levels, tolerance_mm=None):
    """Propose the link level for a host elevation.

    ``link_levels`` is ``[{'id', 'name', 'elevation_mm'}]``. Returns
    ``(level, quality, delta_mm)``; ``level`` is ``None`` only when there are
    no levels at all, because a bad match the user can see and reject is more
    useful than no answer at all — but the quality says plainly which it is.
    """
    tolerance = _number(tolerance_mm, DEFAULT_TOLERANCE_MM)
    if tolerance is None:
        tolerance = DEFAULT_TOLERANCE_MM
    target = _number(host_elevation_mm)
    candidates = [level for level in link_levels or []
                  if _number(level.get('elevation_mm')) is not None]
    if not candidates or target is None:
        return None, MATCH_NONE, None

    best = None
    best_delta = None
    for level in candidates:
        delta = abs(_number(level.get('elevation_mm')) - target)
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best = level

    if best_delta <= 1e-6:
        quality = MATCH_EXACT
    elif best_delta <= tolerance:
        quality = MATCH_NEAR
    else:
        quality = MATCH_FAR
    return best, quality, best_delta


def level_label(level, quality=u'', delta_mm=None):
    """A picker label that shows the elevation and how good the match is."""
    if not level:
        return u'(無樓層)'
    text = u'{}　（{:+.0f} mm）'.format(
        _text(level.get('name')) or u'(未命名)',
        _number(level.get('elevation_mm'), 0.0))
    if quality:
        if delta_mm is None:
            text += u'　{}'.format(quality)
        else:
            text += u'　{}（差 {:.0f} mm）'.format(quality, delta_mm)
    return text


def sorted_levels(link_levels):
    """By elevation, not by name: 1F/2F/10F as text puts 10F in the middle."""
    return sorted(
        [level for level in link_levels or []],
        key=lambda level: _number(level.get('elevation_mm'), 0.0))


def match_warning(quality, delta_mm=None):
    """The sentence to show beside a proposed match, or ``''`` when clean."""
    if quality == MATCH_EXACT:
        return u''
    if quality == MATCH_NEAR:
        return u''
    if quality == MATCH_NONE:
        return u'連結模型裡讀不到任何樓層。'
    return (u'最接近的連結樓層與這個面積平面圖差 {:.0f} mm。'
            u'請確認選的是同一層——畫錯樓層在平面圖上看不出來，'
            u'但產生的面積會是錯的。'.format(_number(delta_mm, 0.0)))
