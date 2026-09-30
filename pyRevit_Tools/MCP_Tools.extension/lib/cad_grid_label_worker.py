#! python3
# -*- coding: utf-8 -*-
"""從 DWG／DXF 讀出軸號文字——CPython 3 + ezdxf（DWG 另需 ODA File Converter）。

**這個檔案是 CPython 3，不是 IronPython 2.7。** 第一行的 ``#! python3`` 是
CLAUDE.md 明列的豁免指令：pyRevit 不匯入它，只由 ``cad_grid_label_runner``
以獨立行程執行，以及被 ``pyRevit_Tools/tests/`` 的 pytest 匯入。

存在的理由只有一個：**Revit API 讀不到匯入 CAD 裡的文字**。軸號（C1、CI）
只能從檔案本身讀。

用法：``python cad_grid_label_worker.py <args.json>``；args 為
``{"files": [...], "labelLayer": "S-GRID-IDEN", "outputPath": "..."}``。
結果寫到 outputPath：``{"files": {path: {"labels": [...], "insunits": n,
"error": ...}}, "python": ..., "oda": ...}``。座標是 CAD 原始繪圖單位——
換算成公釐由 Revit 端用匯入後的實際幾何決定（見 ``cad_align_logic``）。
"""

import glob
import json
import os
import sys


ODA_GLOBS = (
    r'C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe',
    r'C:\Program Files (x86)\ODA\ODAFileConverter*\ODAFileConverter.exe',
)


def find_oda(patterns=ODA_GLOBS):
    """最新版的 ODAFileConverter.exe，找不到回 None。版本號排序取最後一個。"""
    found = []
    for pattern in patterns:
        found.extend(glob.glob(pattern))
    if not found:
        return None
    return sorted(found)[-1]


def layer_matches(layer, wanted):
    """圖層比對不分大小寫；xref 綁定後的 ``底圖$0$S-GRID-IDEN`` 也算。"""
    layer = (layer or '').upper()
    wanted = (wanted or '').upper()
    if not wanted:
        return False
    return layer == wanted or layer.endswith('$' + wanted) or \
        layer.endswith('|' + wanted)


def clean_mtext(text):
    """MTEXT 的格式碼（``\\P``、``{\\fArial;C1}``）剝掉只留字。"""
    try:
        from ezdxf.tools.text import plain_mtext
        return plain_mtext(text)
    except Exception:
        return text


def _entity_text(entity):
    kind = entity.dxftype()
    if kind == 'TEXT':
        return entity.dxf.text, entity.dxf.insert
    if kind == 'MTEXT':
        return clean_mtext(entity.text), entity.dxf.insert
    if kind == 'ATTRIB':
        return entity.dxf.text, entity.dxf.insert
    return None, None


def collect_labels(entities, label_layer):
    """模型空間（含圖塊內、已套用插入變換）裡指定圖層的文字。"""
    labels = []
    for entity in entities:
        kind = entity.dxftype()
        if kind == 'INSERT':
            # 圖塊內的文字：virtual_entities 已套用插入點／比例／旋轉。
            try:
                inner = list(entity.virtual_entities())
            except Exception:
                inner = []
            block_layer = entity.dxf.layer
            for sub in inner:
                if sub.dxftype() in ('TEXT', 'MTEXT') and (
                        layer_matches(sub.dxf.layer, label_layer) or
                        (sub.dxf.layer == '0' and
                         layer_matches(block_layer, label_layer))):
                    text, point = _entity_text(sub)
                    if text:
                        labels.append({'text': text.strip(),
                                       'x': point[0], 'y': point[1]})
            for attrib in getattr(entity, 'attribs', []) or []:
                if layer_matches(attrib.dxf.layer, label_layer) or \
                        layer_matches(block_layer, label_layer):
                    text, point = _entity_text(attrib)
                    if text:
                        labels.append({'text': text.strip(),
                                       'x': point[0], 'y': point[1]})
            continue
        if kind not in ('TEXT', 'MTEXT'):
            continue
        if not layer_matches(entity.dxf.layer, label_layer):
            continue
        text, point = _entity_text(entity)
        if text and text.strip():
            labels.append({'text': text.strip(), 'x': point[0], 'y': point[1]})
    return labels


def read_document(path, oda_exe):
    import ezdxf
    if path.lower().endswith('.dxf'):
        return ezdxf.readfile(path)
    if not oda_exe:
        raise RuntimeError('讀 DWG 需要 ODA File Converter，但本機找不到')
    from ezdxf.addons import odafc
    try:
        ezdxf.options.set('odafc-addon', 'win_exec_path', oda_exe)
    except Exception:
        pass
    oda_dir = os.path.dirname(oda_exe)
    if oda_dir not in os.environ.get('PATH', ''):
        os.environ['PATH'] = os.environ.get('PATH', '') + os.pathsep + oda_dir
    return odafc.readfile(path)


def process(files, label_layer, oda_exe):
    results = {}
    for path in files:
        entry = {'labels': [], 'insunits': None, 'error': None}
        try:
            doc = read_document(path, oda_exe)
            entry['insunits'] = doc.header.get('$INSUNITS', 0)
            entry['labels'] = collect_labels(doc.modelspace(), label_layer)
        except Exception as error:
            entry['error'] = '{}: {}'.format(type(error).__name__, error)
        results[path] = entry
    return results


def main(argv):
    if len(argv) < 2:
        print(json.dumps({'error': '用法：cad_grid_label_worker.py <args.json>'}))
        return 2
    with open(argv[1], 'rb') as stream:
        args = json.loads(stream.read().decode('utf-8'))
    try:
        import ezdxf  # noqa: F401
    except Exception as error:
        print(json.dumps({
            'error': '缺少 ezdxf（pip install ezdxf）：{}'.format(error),
            'python': sys.executable}, ensure_ascii=False))
        return 1
    oda_exe = find_oda()
    payload = {
        'python': sys.executable,
        'oda': oda_exe,
        'files': process(args.get('files') or [],
                         args.get('labelLayer') or 'S-GRID-IDEN', oda_exe),
    }
    with open(args['outputPath'], 'wb') as stream:
        stream.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
