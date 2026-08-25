# -*- coding: utf-8 -*-
from __future__ import unicode_literals

"""Zip an OpenXML part list into an .xlsx file.

Deliberately thin: everything that decides *what* goes in the file lives in
:mod:`xlsx_xml`, which is pure and unit-tested. This module only writes bytes,
using .NET's ``ZipArchive`` so the button never needs Excel installed — the
same approach the takeoff buttons already use.

``System.IO.Compression`` is not one of the assemblies IronPython's host
loads by default (unlike ``System.IO`` or ``System.Text``), so ``clr.AddReference``
has to name it explicitly before the ``from ... import`` below can resolve —
without it the import fails at runtime with
``ImportError: Cannot import name ZipArchive``, which reads like a missing
class rather than a missing assembly reference.
"""

import clr
clr.AddReference('System.IO.Compression')

from System.IO import FileAccess, FileMode, FileStream
from System.IO.Compression import ZipArchive, ZipArchiveMode
from System.Text import Encoding

import xlsx_xml


def _write_entry(archive, name, content):
    entry = archive.CreateEntry(name)
    stream = entry.Open()
    try:
        data = Encoding.UTF8.GetBytes(content)
        stream.Write(data, 0, data.Length)
    finally:
        stream.Close()


def write_workbook(path, sheets):
    """Write ``[(sheet_name, rows, spec)]`` to ``path`` as .xlsx."""
    parts = xlsx_xml.workbook_parts(sheets)
    stream = FileStream(path, FileMode.Create, FileAccess.ReadWrite)
    archive = ZipArchive(stream, ZipArchiveMode.Create)
    try:
        for name, content in parts:
            _write_entry(archive, name, content)
    finally:
        archive.Dispose()
        stream.Close()
    return path
