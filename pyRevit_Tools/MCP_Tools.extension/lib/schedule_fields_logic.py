# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""明細表欄位編輯器：可用欄位 ⇄ 明細表欄位的純邏輯。

不碰 Revit、不碰 WPF，IronPython 2.7 與 CPython 3 都能跑（測試在
``tests/test_schedule_fields_logic.py``）。

每張明細表的編輯狀態是 ``{'used': [...], 'pool': [...]}``：``used`` 是
明細表欄位（有順序），``pool`` 是可用欄位。兩邊的元素都是 entry dict::

    {'key', 'name', 'heading', 'hidden', 'fixed', 'field_id'}

- ``key``：欄位身分。可排程欄位用 ``"<ScheduleFieldType>|<ParameterId>"``，
  所以同一個共用/專案/內建參數在不同明細表之間對得上（複製設定靠它）。
  計算值、組合參數這類無法從可用欄位重新加回的欄位用 ``"x:<FieldId>"``，
  ``fixed`` 為真。
- ``field_id``：明細表上既有欄位的 ScheduleFieldId 整數；新加入的是 ``None``。

既有欄位移到可用欄位再移回來，會拿回同一個 entry（同一個 field_id），
寫入時視為沒動，不會刪掉重建——重建會把它的篩選/排序設定一起弄丟。
"""


def text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value)
    except Exception:
        return u''


def field_key(field_type, param_id):
    return u'{}|{}'.format(text(field_type), text(param_id))


def fixed_key(field_id):
    return u'x:{}'.format(text(field_id))


def entry(key, name, heading=None, hidden=False, fixed=False, field_id=None,
          source=u''):
    """``source`` 是給人看的來源標記（例如「類型」），同名的實例/類型參數
    才分得出來；不參與比對。"""
    name = text(name)
    return {'key': key, 'name': name,
            'heading': name if heading is None else text(heading),
            'hidden': bool(hidden), 'fixed': bool(fixed),
            'field_id': field_id, 'source': text(source)}


def _copy(item):
    return dict(item)


def _name_key(item):
    return (item['name'].lower(), item['key'])


def new_state(used, available):
    """``available`` 裡已經在 ``used`` 的 key 會被排除；pool 依名稱排序。"""
    used = [_copy(item) for item in used]
    taken = set(item['key'] for item in used)
    pool = [_copy(item) for item in available if item['key'] not in taken]
    pool.sort(key=_name_key)
    return {'used': used, 'pool': pool}


def clone(state):
    return {'used': [_copy(i) for i in state['used']],
            'pool': [_copy(i) for i in state['pool']]}


def keys_of(items):
    return [item['key'] for item in items]


# ── 編輯操作（都回傳新的 state，不改傳入的） ─────────────────────────

def add(state, keys, at=None):
    """把 pool 裡的 ``keys`` 依 pool 順序插到 used 的 ``at`` 位置（預設最後）。"""
    state = clone(state)
    wanted = set(keys)
    moving = [i for i in state['pool'] if i['key'] in wanted]
    state['pool'] = [i for i in state['pool'] if i['key'] not in wanted]
    if at is None or at > len(state['used']):
        at = len(state['used'])
    state['used'][at:at] = moving
    return state


def remove(state, keys):
    state = clone(state)
    wanted = set(keys)
    moving = [i for i in state['used'] if i['key'] in wanted]
    state['used'] = [i for i in state['used'] if i['key'] not in wanted]
    state['pool'].extend(moving)
    state['pool'].sort(key=_name_key)
    return state


def move(state, keys, delta):
    """選取的欄位整組上移（-1）或下移（+1）一格；碰到邊界的那一個不動。"""
    state = clone(state)
    used = state['used']
    wanted = set(keys)
    order = range(len(used)) if delta < 0 else range(len(used) - 1, -1, -1)
    for index in order:
        if used[index]['key'] not in wanted:
            continue
        target = index + (-1 if delta < 0 else 1)
        if 0 <= target < len(used) and used[target]['key'] not in wanted:
            used[index], used[target] = used[target], used[index]
    return state


def move_to_edge(state, keys, top):
    state = clone(state)
    wanted = set(keys)
    picked = [i for i in state['used'] if i['key'] in wanted]
    rest = [i for i in state['used'] if i['key'] not in wanted]
    state['used'] = picked + rest if top else rest + picked
    return state


def set_heading(state, key, heading):
    state = clone(state)
    for item in state['used']:
        if item['key'] == key:
            item['heading'] = text(heading)
    return state


def set_hidden(state, keys, hidden):
    state = clone(state)
    wanted = set(keys)
    for item in state['used']:
        if item['key'] in wanted:
            item['hidden'] = bool(hidden)
    return state


def display_name(item):
    if item.get('source'):
        return u'{}（{}）'.format(item['name'], item['source'])
    return item['name']


def matches(item, keyword):
    """空白分隔的每個關鍵字都要出現在名稱或標題裡（不分大小寫）。"""
    haystack = (item['name'] + u' ' + item.get('heading', u'')).lower()
    for word in text(keyword).lower().split():
        if word not in haystack:
            return False
    return True


def label(item, in_pool=False):
    parts = [display_name(item)]
    if not in_pool and item['heading'] != item['name']:
        parts.append(u'→「{}」'.format(item['heading']))
    if item['hidden']:
        parts.append(u'（隱藏）')
    if item['fixed']:
        parts.append(u'（計算值，移除後只能在本次復原）')
    if not in_pool and item['field_id'] is None:
        parts.append(u'＋新增')
    return u' '.join(parts)


# ── 差異與複製 ──────────────────────────────────────────────────────

def diff(original, used):
    """原本的 used 清單 vs 編輯後的 used 清單。

    ``reordered`` 的意思是「只做增刪的話 Revit 自然得到的順序」跟目標不同，
    也就是寫入時需要呼叫 SetFieldOrder。新增欄位一律先 AddField 到最後。
    """
    final_keys = set(keys_of(used))
    original_keys = set(keys_of(original))
    removed = [i for i in original if i['key'] not in final_keys]
    added = [i for i in used if i['key'] not in original_keys]
    before = dict((i['key'], i) for i in original)
    renamed = [(i, before[i['key']]['heading'], i['heading'])
               for i in used
               if i['key'] in before and before[i['key']]['heading'] != i['heading']]
    hidden = [(i, before[i['key']]['hidden'], i['hidden'])
              for i in used
              if i['key'] in before and before[i['key']]['hidden'] != i['hidden']]
    hidden += [(i, False, True) for i in added if i['hidden']]
    natural = [k for k in keys_of(original) if k in final_keys] + keys_of(added)
    reordered = natural != keys_of(used)
    renamed += [(i, i['name'], i['heading']) for i in added
                if i['heading'] != i['name']]
    return {'removed': removed, 'added': added, 'renamed': renamed,
            'hidden': hidden, 'reordered': reordered,
            'changed': bool(removed or added or renamed or hidden
                            or reordered)}


def copy_layout(source_used, target):
    """把來源的欄位清單（順序與標題）套到 ``target`` state。

    回傳 ``(new_state, missing)``：``missing`` 是目標明細表沒有這個可用欄位、
    只好略過的來源欄位名稱。計算值欄位（``fixed``）在別張表一定對不上。
    目標原本有、來源沒有的欄位會移回可用欄位。標題與隱藏狀態都跟著來源。
    """
    state = clone(target)
    by_key = dict((i['key'], i) for i in state['used'] + state['pool'])
    used = []
    missing = []
    for item in source_used:
        found = by_key.get(item['key'])
        if found is None or item['fixed']:
            missing.append(item['name'])
            continue
        found = _copy(found)
        found['heading'] = item['heading']
        found['hidden'] = item['hidden']
        used.append(found)
    taken = set(keys_of(used))
    pool = [i for i in state['used'] + state['pool'] if i['key'] not in taken]
    pool.sort(key=_name_key)
    return {'used': used, 'pool': pool}, missing


def summary_lines(change):
    lines = []
    if change['removed']:
        lines.append(u'移除 {} 欄：{}'.format(
            len(change['removed']),
            u'、'.join(i['name'] for i in change['removed'])))
    if change['added']:
        lines.append(u'加入 {} 欄：{}'.format(
            len(change['added']),
            u'、'.join(i['name'] for i in change['added'])))
    for item, old, new in change['renamed']:
        lines.append(u'改標題：{}「{}」→「{}」'.format(item['name'], old, new))
    shown = [i['name'] for i, old, new in change['hidden'] if not new]
    hidden = [i['name'] for i, old, new in change['hidden'] if new]
    if hidden:
        lines.append(u'隱藏 {} 欄：{}'.format(len(hidden), u'、'.join(hidden)))
    if shown:
        lines.append(u'取消隱藏 {} 欄：{}'.format(len(shown), u'、'.join(shown)))
    if change['reordered']:
        lines.append(u'重新排序')
    return lines
