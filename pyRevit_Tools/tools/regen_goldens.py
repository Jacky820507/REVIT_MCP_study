# -*- coding: utf-8 -*-
"""重新產生 ``tests\\goldens\\*.json``。

**只在刻意改變輸出行為之後才跑這支**——換算式、改版面、加欄位。單純重構
（把手寫欄位字母換成 SheetLayout）不該讓 golden 改變；如果跑完這支發現
diff 一大片，先停下來想清楚是不是哪裡真的改壞了，不要無腦蓋過去。

用法：
    python tools/regen_goldens.py              # 全部重新產生
    python tools/regen_goldens.py rc_volume_excel scaffold_excel_com   # 只重產指定的

跑完會印出每個 fixture 跟舊 golden 的差異提要，讓你在覆蓋前看一眼。
"""
from __future__ import unicode_literals

import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tests'))

import golden_fixtures as gf  # noqa: E402


def _load(path):
    if not os.path.exists(path):
        return None
    with io.open(path, encoding='utf-8') as handle:
        return json.load(handle)


def _summarize_diff(old, new):
    if old is None:
        return 'new golden (no previous file)'
    if old == new:
        return 'unchanged'
    old_keys = set(old) if isinstance(old, dict) else None
    new_keys = set(new) if isinstance(new, dict) else None
    if old_keys is not None and new_keys is not None and old_keys != new_keys:
        return 'top-level keys changed: {0}'.format(
            (old_keys ^ new_keys))
    return 'content differs (see git diff after writing)'


def main():
    names = sys.argv[1:] or sorted(gf.ALL_FIXTURES)
    unknown = [n for n in names if n not in gf.ALL_FIXTURES]
    if unknown:
        print('未知的 fixture 名稱：{0}'.format(unknown))
        print('可用：{0}'.format(sorted(gf.ALL_FIXTURES)))
        return 1

    if not os.path.isdir(gf.GOLDEN_DIR):
        os.makedirs(gf.GOLDEN_DIR)

    for name in names:
        builder = gf.ALL_FIXTURES[name]
        payload = builder()
        path = os.path.join(gf.GOLDEN_DIR, name + '.json')
        old = _load(path)
        with io.open(path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1,
                      default=str, sort_keys=True)
        print('{0:32} {1}'.format(name, _summarize_diff(old, payload)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
