# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Pure source/level identity helpers shared by Revit takeoff buttons.

The strings in this module are persistence keys, not display labels.  Keeping
the source id as its own colon-delimited token is important: ``link:7`` and
``link:70`` must never share a level selection.
"""

try:
    text_type = unicode
except NameError:  # CPython 3 tests
    text_type = str


HOST_SOURCE = 'host'
LINK_PREFIX = 'link:'


def _text(value):
    if isinstance(value, text_type):
        return value
    return text_type(value)


def _integer(value, description):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError('{} must be an integer: {!r}'.format(
            description, value))


def link_source_key(link_id):
    """Return the stable source key for one RevitLinkInstance id."""
    return '{}{}'.format(LINK_PREFIX, _integer(link_id, 'link_id'))


def parse_source_key(source_key):
    """Return ``(kind, link_id)``; host has a ``None`` link id."""
    key = _text(source_key)
    if key == HOST_SOURCE:
        return HOST_SOURCE, None
    parts = key.split(':')
    if len(parts) == 2 and parts[0] == 'link' and parts[1]:
        return 'link', _integer(parts[1], 'link id')
    raise ValueError('Invalid source key: {!r}'.format(source_key))


def level_key(source_key, level_id):
    """Return ``host:<levelId>`` or ``link:<linkId>:<levelId>``."""
    kind, link_id = parse_source_key(source_key)
    level_id = _integer(level_id, 'level_id')
    if kind == HOST_SOURCE:
        return '{}:{}'.format(HOST_SOURCE, level_id)
    return 'link:{}:{}'.format(link_id, level_id)


def parse_level_key(key):
    """Return ``(source_key, level_id)`` after strict token parsing."""
    value = _text(key)
    parts = value.split(':')
    if len(parts) == 2 and parts[0] == HOST_SOURCE and parts[1]:
        return HOST_SOURCE, _integer(parts[1], 'level id')
    if (len(parts) == 3 and parts[0] == 'link'
            and parts[1] and parts[2]):
        source = link_source_key(_integer(parts[1], 'link id'))
        return source, _integer(parts[2], 'level id')
    raise ValueError('Invalid level key: {!r}'.format(key))


def level_ids_for_source(source_key, selected_level_keys):
    """Return selected level ids for one source, or ``None`` for all.

    Selection is deliberately evaluated per source.  If the user selects host
    levels but no levels for a selected link, that link still means all levels.
    """
    parse_source_key(source_key)
    found = set()
    for key in selected_level_keys or []:
        key_source, level_id = parse_level_key(key)
        if key_source == source_key:
            found.add(level_id)
    return found if found else None


def prune_level_keys(selected_level_keys, include_host,
                     selected_link_ids, available_level_keys=None):
    """Drop keys belonging to removed sources or unavailable levels.

    Order is preserved and duplicates are removed.  ``available_level_keys``
    is optional so the same helper can be used before a Revit level catalog
    has been rebuilt.
    """
    allowed_sources = set()
    if include_host:
        allowed_sources.add(HOST_SOURCE)
    for link_id in selected_link_ids or []:
        allowed_sources.add(link_source_key(link_id))
    available = (None if available_level_keys is None
                 else set(_text(key) for key in available_level_keys))
    result = []
    seen = set()
    for raw_key in selected_level_keys or []:
        key = _text(raw_key)
        source_key, unused_level_id = parse_level_key(key)
        if source_key not in allowed_sources:
            continue
        if available is not None and key not in available:
            continue
        if key not in seen:
            result.append(key)
            seen.add(key)
    return result


def disambiguate_labels(identity_label_pairs):
    """Return unique display labels, adding ``[id ...]`` to duplicates.

    ``identity_label_pairs`` is an iterable of ``(stable_id, base_label)``.
    The returned list follows the input order and contains plain strings for
    reliable IronPython/WPF binding.
    """
    pairs = [(item_id, _text(label)) for item_id, label
             in identity_label_pairs]
    counts = {}
    for unused_item_id, label in pairs:
        counts[label] = counts.get(label, 0) + 1
    labels = []
    used = set()
    for item_id, label in pairs:
        candidate = label
        if counts.get(label, 0) > 1:
            candidate = '{} [id {}]'.format(label, item_id)
        if candidate in used:
            candidate = '{} [id {}]'.format(label, item_id)
        suffix = 2
        unique = candidate
        while unique in used:
            unique = '{} ({})'.format(candidate, suffix)
            suffix += 1
        labels.append(unique)
        used.add(unique)
    return labels
