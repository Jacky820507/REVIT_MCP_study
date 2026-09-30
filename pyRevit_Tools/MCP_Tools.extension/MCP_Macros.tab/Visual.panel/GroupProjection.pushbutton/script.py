# -*- coding: utf-8 -*-
from __future__ import unicode_literals

__persistentengine__ = True

from pyrevit import forms, revit
from Autodesk.Revit import DB
import group_projection_window
import group_projection_source as projection_source

if revit.doc is None or revit.doc.IsFamilyDocument:
    forms.alert('請先開啟專案模型。', exitscript=True)
target_error = projection_source.target_view_error(revit.active_view)
if target_error:
    forms.alert(target_error, exitscript=True)

group_projection_window.open_window(__revit__)
