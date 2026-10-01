# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""共用視窗的欄位規格、驗證與取值——純邏輯，不碰 WPF.

18 顆按鈕原本各自用 2～5 個 ``SelectFromList`` 連珠問問題。那個模式有兩個真正
的毛病，換成視窗只是順手：**答案會互相影響**（換樓層改變可選的視圖、換模式改
變後面要問什麼），而連珠讓每次微調都得從第一題重來；而且**取消與「什麼都不
選」在多選對話框裡長得一模一樣**，逼得每顆按鈕都要自己發明一個哨符。

所以欄位在這裡是**資料**：一份規格描述要問什麼、預設是什麼、怎麼驗證、彼此
怎麼連動。視窗只負責把規格畫出來並回填答案，而規格與驗證可以在 CPython 下用
pytest 蓋到——WPF 那一側則盡量薄。

值的型別由欄位種類決定，呼叫端拿到的是乾淨的 Python 值，不是控制項。
"""


# --- 欄位種類 --------------------------------------------------------------

CHOICE = 'choice'
MULTICHOICE = 'multichoice'
TEXT = 'text'
NUMBER = 'number'
BOOL = 'bool'
SECTION = 'section'
NOTE = 'note'

INPUT_KINDS = (CHOICE, MULTICHOICE, TEXT, NUMBER, BOOL)

# 標題帶右上角的徽章。動不動模型是使用者按下去之前最該知道的一件事，
# 所以它是規格的必填項而不是裝飾。
BADGE_READONLY = u'唯讀'
BADGE_WRITE = u'會寫入模型'
BADGE_DELETE = u'會刪除元素'

BADGES = (BADGE_READONLY, BADGE_WRITE, BADGE_DELETE)


def _text(value):
    if value is None:
        return u''
    try:
        return u'{}'.format(value)
    except Exception:
        return unicode(value)  # noqa: F821 - IronPython 2.7


def _field(kind, key, label, **extra):
    field = {
        'kind': kind,
        'key': key,
        'label': _text(label),
        'help': _text(extra.pop('help', u'')),
        'required': bool(extra.pop('required', True)),
        'enabled_when': extra.pop('enabled_when', None),
    }
    field.update(extra)
    return field


def section(label, help=u''):
    """段落標題。純視覺分組，不產生值。"""
    return _field(SECTION, None, label, help=help, required=False)


def note(text, tone='info'):
    """一段說明文字。``tone`` 為 info / warning / danger，只影響顏色。"""
    return _field(NOTE, None, u'', help=text, required=False, tone=tone)


def choice(key, label, options, default=None, help=u'', required=True,
           enabled_when=None):
    """單選。``options`` 為 ``[(label, value)]``；值可以是任何 Python 物件。

    這裡的 value 允許是 ``None``——單選有一個明確的「未選」狀態，不需要像
    ``SelectFromList`` 那樣為了跟「取消」區分而發明哨符。
    """
    return _field(CHOICE, key, label, options=list(options or []),
                  default=default, help=help, required=required,
                  enabled_when=enabled_when)


def multichoice(key, label, options, default=None, help=u'', required=False,
                enabled_when=None, actions=True, filter=None):
    """複選。回傳被勾選的 value 清單。

    ``required=False`` 是預設值，因為**一個都不勾是一個真的答案**（例如
    「以上條件皆不符合」）。連珠對話框做不到這件事，這是換成視窗的主要收穫
    之一，所以不要在這裡把它變回必填。
    """
    return _field(MULTICHOICE, key, label, options=list(options or []),
                  default=list(default or []), help=help, required=required,
                  enabled_when=enabled_when, actions=actions,
                  filter=filter)


def text(key, label, default=u'', help=u'', required=False, placeholder=u'',
         enabled_when=None):
    return _field(TEXT, key, label, default=_text(default), help=help,
                  required=required, placeholder=_text(placeholder),
                  enabled_when=enabled_when)


def number(key, label, default=0.0, minimum=None, maximum=None, unit=u'',
           help=u'', required=True, integer=False, enabled_when=None):
    """數值輸入。``minimum``／``maximum`` 是**夾住**而不是拒絕。

    使用者輸入 1000 而上限是 600 時，把它夾回 600 並說明理由，比丟一句
    「超出範圍」再叫他重打有用——後者只是把工具知道的事藏起來。
    """
    return _field(NUMBER, key, label, default=default, minimum=minimum,
                  maximum=maximum, unit=_text(unit), help=help,
                  required=required, integer=bool(integer),
                  enabled_when=enabled_when)


def boolean(key, label, default=False, help=u'', enabled_when=None):
    return _field(BOOL, key, label, default=bool(default), help=help,
                  required=False, enabled_when=enabled_when)


# --- 規格 ------------------------------------------------------------------

def spec(title, fields, subtitle=u'', badge=BADGE_READONLY, run_label=u'執行',
         footnote=u'', width=None, height=None, secondary_label=u''):
    """一顆按鈕的整份視窗規格。"""
    return {
        'title': _text(title),
        'subtitle': _text(subtitle),
        'badge': badge if badge in BADGES else BADGE_READONLY,
        'run_label': _text(run_label),
        'secondary_label': _text(secondary_label),
        'footnote': _text(footnote),
        'fields': list(fields or []),
        'width': width,
        'height': height,
    }


def input_fields(fields):
    """只有會產生值的欄位（略過 section 與 note）。"""
    return [field for field in fields or []
            if field.get('kind') in INPUT_KINDS and field.get('key')]


def defaults(fields):
    """規格本身描述的初始值。"""
    values = {}
    for field in input_fields(fields):
        kind = field['kind']
        if kind == MULTICHOICE:
            values[field['key']] = list(field.get('default') or [])
        else:
            values[field['key']] = field.get('default')
    return values


def duplicate_keys(fields):
    """重複的欄位 key——後者會靜默蓋掉前者，所以要抓出來。"""
    seen = set()
    repeated = []
    for field in input_fields(fields):
        key = field['key']
        if key in seen and key not in repeated:
            repeated.append(key)
        seen.add(key)
    return repeated


# --- 連動 ------------------------------------------------------------------

def is_enabled(field, values):
    """欄位在目前的答案下是否該啟用。

    ``enabled_when`` 是 ``(key, wanted)``；``wanted`` 可以是單一值或值的集合。
    停用的欄位仍然保有它的值但**不參與驗證**——否則一個看不到、改不了的欄位
    可以擋住整個執行鈕，而使用者完全不知道要去哪裡改。
    """
    condition = field.get('enabled_when')
    if not condition:
        return True
    key, wanted = condition
    current = values.get(key)
    if isinstance(wanted, (list, tuple, set, frozenset)):
        return current in wanted
    return current == wanted


def visible_fields(fields, values):
    return [field for field in fields or []
            if is_enabled(field, values)]


# --- 取值與驗證 ------------------------------------------------------------

def parse_number(raw, field):
    """``(value, error, note)``。數值解析與夾範圍。"""
    label = field.get('label') or field.get('key')
    unit = field.get('unit') or u''
    stripped = _text(raw).strip()
    if not stripped:
        if field.get('required'):
            return None, u'「{}」需要一個數值。'.format(label), u''
        return None, u'', u''
    try:
        value = float(stripped.replace(u',', u''))
    except (TypeError, ValueError):
        return None, u'「{}」不是數字：{}'.format(label, stripped), u''

    note_text = u''
    minimum = field.get('minimum')
    maximum = field.get('maximum')
    if minimum is not None and value < minimum:
        note_text = u'「{}」低於下限，已改為 {:g}{}。'.format(label, minimum, unit)
        value = float(minimum)
    elif maximum is not None and value > maximum:
        note_text = u'「{}」高於上限，已改為 {:g}{}。'.format(label, maximum, unit)
        value = float(maximum)

    if field.get('integer'):
        value = int(round(value))
    return value, u'', note_text


def validate(fields, values):
    """``(errors, notes)``；``errors`` 是 ``{key: message}``。

    只驗證目前**啟用中**的欄位。
    """
    errors = {}
    notes = []
    for field in input_fields(fields):
        if not is_enabled(field, values):
            continue
        key = field['key']
        kind = field['kind']
        label = field.get('label') or key
        value = values.get(key)

        if kind == NUMBER:
            parsed, error, note_text = parse_number(value, field)
            if error:
                errors[key] = error
            else:
                values[key] = parsed
                if note_text:
                    notes.append(note_text)
            continue

        if kind == CHOICE:
            if field.get('required') and value is None:
                errors[key] = u'請選擇「{}」。'.format(label)
            continue

        if kind == MULTICHOICE:
            if field.get('required') and not value:
                errors[key] = u'「{}」至少要選一項。'.format(label)
            continue

        if kind == TEXT:
            if field.get('required') and not _text(value).strip():
                errors[key] = u'「{}」不能是空的。'.format(label)
            continue

    return errors, notes


def split_keywords(raw):
    """逗號分隔的關鍵字字串 → 清單。全形逗號一併吃掉。"""
    text_value = _text(raw).replace(u'，', u',').replace(u'、', u',')
    return [part.strip() for part in text_value.split(u',') if part.strip()]


def option_labels(options):
    return [_text(label) for label, unused in options or []]


def value_for_label(options, label):
    """依顯示文字取回配對的值；找不到回 ``None``。"""
    for option_label, value in options or []:
        if _text(option_label) == _text(label):
            return value
    return None


def label_for_value(options, value):
    for option_label, option_value in options or []:
        if option_value == value:
            return _text(option_label)
    return u''


def matches_filter(label, query):
    """篩選框的比對：空白分隔的每個詞都要出現在文字裡，不分大小寫。

    詞之間是「且」——輸入「一層 排水」要同時含兩者，這比整串當作一個子字串
    實用：視圖名稱的詞序不固定。全形空白也算分隔。
    """
    terms = _text(query).replace(u'　', u' ').lower().split()
    if not terms:
        return True
    haystack = _text(label).lower()
    return all(term in haystack for term in terms)


def unique_labels(options):
    """讓顯示文字唯一，否則依文字回查值會取到錯的那一個。

    重複的後面補空白而不是加編號：使用者看到的仍是原本的名字，而視窗內部
    需要的唯一性也成立。
    """
    seen = set()
    result = []
    for label, value in options or []:
        text_label = _text(label)
        while text_label in seen:
            text_label += u' '
        seen.add(text_label)
        result.append((text_label, value))
    return result


# --- 結果 ------------------------------------------------------------------

# 視窗內的結果表格只是給人看的摘要；完整明細仍然印在 pyRevit 輸出視窗，
# 因為那裡的 linkify 可以直接點到元素。超過這個列數就只顯示前段並說明。
MAX_RESULT_ROWS = 200


def result(summary_lines=None, columns=None, rows=None, tone='info'):
    return {
        'summary': list(summary_lines or []),
        'columns': list(columns or []),
        'rows': list(rows or []),
        'tone': tone,
    }


def truncate_rows(rows, limit=MAX_RESULT_ROWS):
    """``(shown, note)``——被截掉時一定要說，不能只顯示前 200 列而不吭聲。"""
    items = list(rows or [])
    if len(items) <= limit:
        return items, u''
    return items[:limit], (
        u'僅顯示前 {} 列，共 {} 列；完整明細在 pyRevit 輸出視窗。'
        .format(limit, len(items)))
