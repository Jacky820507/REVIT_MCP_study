using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Newtonsoft.Json.Linq;

#if REVIT2025_OR_GREATER
using IdType = System.Int64;
#else
using IdType = System.Int32;
#endif

namespace RevitMCP.Core
{
    public partial class CommandExecutor
    {
        #region 從屬視圖與網格

        /// <summary>
        /// 計算網格範圍加上偏移的 BoundingBox
        /// </summary>
        private object CalculateGridBounds(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            var xGridsArray = (parameters["xGrids"] ?? parameters["x_grids"]) as JArray;
            var yGridsArray = (parameters["yGrids"] ?? parameters["y_grids"]) as JArray;
            double offsetMm = parameters["offset_mm"]?.Value<double>() ?? 0;
            double offsetFeet = offsetMm / 304.8;

            List<string> xGridNames = xGridsArray?.Select(x => x.Value<string>()).ToList() ?? new List<string>();
            List<string> yGridNames = yGridsArray?.Select(x => x.Value<string>()).ToList() ?? new List<string>();

            if (xGridNames.Count == 0 && yGridNames.Count == 0)
                throw new Exception("至少需要提供一組 X 軸或 Y 軸網格線名稱");

            var allGrids = new FilteredElementCollector(doc)
                .OfClass(typeof(Grid))
                .Cast<Grid>()
                .ToList();

            double minX = double.MaxValue, maxX = double.MinValue;
            double minY = double.MaxValue, maxY = double.MinValue;

            if (xGridNames.Count > 0)
            {
                foreach (string name in xGridNames)
                {
                    var grid = allGrids.FirstOrDefault(g => g.Name.Equals(name, StringComparison.OrdinalIgnoreCase));
                    if (grid != null)
                    {
                        var curve = grid.Curve;
                        double x = (curve.GetEndPoint(0).X + curve.GetEndPoint(1).X) / 2.0;
                        minX = Math.Min(minX, x);
                        maxX = Math.Max(maxX, x);
                    }
                }
            }

            if (yGridNames.Count > 0)
            {
                foreach (string name in yGridNames)
                {
                    var grid = allGrids.FirstOrDefault(g => g.Name.Equals(name, StringComparison.OrdinalIgnoreCase));
                    if (grid != null)
                    {
                        var curve = grid.Curve;
                        double y = (curve.GetEndPoint(0).Y + curve.GetEndPoint(1).Y) / 2.0;
                        minY = Math.Min(minY, y);
                        maxY = Math.Max(maxY, y);
                    }
                }
            }

            if (xGridNames.Count == 1) { minX -= offsetFeet; maxX += offsetFeet; }
            if (yGridNames.Count == 1) { minY -= offsetFeet; maxY += offsetFeet; }

            double finalMinX = (xGridNames.Count > 0 ? minX : -1000) - offsetFeet;
            double finalMaxX = (xGridNames.Count > 0 ? maxX : 1000) + offsetFeet;
            double finalMinY = (yGridNames.Count > 0 ? minY : -1000) - offsetFeet;
            double finalMaxY = (yGridNames.Count > 0 ? maxY : 1000) + offsetFeet;

            return new
            {
                min = new { x = finalMinX * 304.8, y = finalMinY * 304.8, z = -100 * 304.8 },
                max = new { x = finalMaxX * 304.8, y = finalMaxY * 304.8, z = 100 * 304.8 }
            };
        }

        /// <summary>
        /// 批次建立從屬視圖並套用邊界
        /// </summary>
        private object CreateDependentViews(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            var parentViewIdsArray = parameters["parentViewIds"] as JArray;
            List<IdType> parentViewIds = parentViewIdsArray?.Select(x => x.Value<IdType>()).ToList() ?? new List<IdType>();

            string suffixName = parameters["suffixName"]?.Value<string>();
            IdType sourceCropViewId = (parameters["sourceCropViewId"] ?? parameters["copyCropFromViewId"])?.Value<IdType>() ?? 0;
            IdType scopeBoxId = parameters["scopeBoxId"]?.Value<IdType>() ?? 0;
            bool copyCropShape = parameters["copyCropShape"]?.Value<bool>() ?? true;
            bool copyCropVisibility = parameters["copyCropVisibility"]?.Value<bool>() ?? true;

            View sourceCropView = null;
            if (sourceCropViewId > 0)
            {
                sourceCropView = doc.GetElement(sourceCropViewId.ToElementId()) as View;
                if (sourceCropView == null)
                    throw new Exception($"找不到來源裁切視圖: {sourceCropViewId}");
            }

            double minX = parameters["min"]?["x"]?.Value<double>() ?? 0;
            double minY = parameters["min"]?["y"]?.Value<double>() ?? 0;
            double minZ = parameters["min"]?["z"]?.Value<double>() ?? -100 * 304.8;
            double maxX = parameters["max"]?["x"]?.Value<double>() ?? 0;
            double maxY = parameters["max"]?["y"]?.Value<double>() ?? 0;
            double maxZ = parameters["max"]?["z"]?.Value<double>() ?? 100 * 304.8;

            BoundingBoxXYZ bbox = null;
            if (sourceCropView != null)
            {
                bbox = CloneBoundingBox(sourceCropView.CropBox);
            }
            else
            {
                XYZ min = new XYZ(minX / 304.8, minY / 304.8, minZ / 304.8);
                XYZ max = new XYZ(maxX / 304.8, maxY / 304.8, maxZ / 304.8);
                bbox = new BoundingBoxXYZ { Min = min, Max = max };
            }

            List<object> results = new List<object>();

            using (Transaction trans = new Transaction(doc, "批次建立從屬視圖"))
            {
                trans.Start();

                foreach (IdType viewId in parentViewIds)
                {
                    View parentView = doc.GetElement(viewId.ToElementId()) as View;
                    if (parentView == null || !parentView.CanViewBeDuplicated(ViewDuplicateOption.AsDependent))
                        continue;

                    ElementId newViewId = parentView.Duplicate(ViewDuplicateOption.AsDependent);
                    View newView = doc.GetElement(newViewId) as View;

                    string finalSuffix = suffixName;
                    if (string.IsNullOrEmpty(finalSuffix))
                    {
                        int childCount = parentView.GetDependentViewIds().Count();
                        finalSuffix = childCount.ToString();

                        string targetName = $"{parentView.Name}-{finalSuffix}";
                        int loopGuard = 0;
                        while (new FilteredElementCollector(doc).OfClass(typeof(View)).Cast<View>().Any(v => v.Name == targetName) && loopGuard < 100)
                        {
                            childCount++;
                            finalSuffix = childCount.ToString();
                            targetName = $"{parentView.Name}-{finalSuffix}";
                            loopGuard++;
                        }
                    }

                    string newName = $"{parentView.Name}-{finalSuffix}";
                    try { newView.Name = newName; }
                    catch (Exception ex) { Logger.Debug($"視圖命名失敗: {ex.Message}"); }

                    newView.CropBoxActive = true;
                    newView.CropBoxVisible = true;
                    newView.CropBox = bbox;

                    var warnings = new List<string>();

                    if (sourceCropView != null)
                    {
                        if (copyCropVisibility)
                        {
                            newView.CropBoxActive = sourceCropView.CropBoxActive;
                            newView.CropBoxVisible = sourceCropView.CropBoxVisible;
                        }

                        if (copyCropShape)
                        {
                            warnings.AddRange(CopyCropShape(sourceCropView, newView));
                        }
                    }

                    IdType? appliedScopeBoxId = null;
                    string appliedScopeBoxName = null;
                    if (scopeBoxId > 0)
                    {
                        warnings.AddRange(SetScopeBoxOnView(doc, newView, scopeBoxId.ToElementId(), out appliedScopeBoxId, out appliedScopeBoxName));
                    }

                    results.Add(new
                    {
                        ParentName = parentView.Name,
                        NewViewId = newView.Id.GetIdValue(),
                        NewViewName = newView.Name,
                        SourceCropViewId = sourceCropView?.Id.GetIdValue(),
                        AppliedScopeBoxId = appliedScopeBoxId,
                        AppliedScopeBoxName = appliedScopeBoxName,
                        Warnings = warnings
                    });
                }

                trans.Commit();
            }

            return results;
        }

        private object GetViewCropBox(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType viewId = parameters["viewId"]?.Value<IdType>() ?? 0;
            View view = viewId > 0
                ? doc.GetElement(viewId.ToElementId()) as View
                : _uiApp.ActiveUIDocument.ActiveView;

            if (view == null)
                throw new Exception($"找不到視圖: {viewId}");

            IdType? scopeBoxId = GetAssignedScopeBoxId(view);
            return new
            {
                ViewId = view.Id.GetIdValue(),
                ViewName = view.Name,
                ViewType = view.ViewType.ToString(),
                CropBoxActive = view.CropBoxActive,
                CropBoxVisible = view.CropBoxVisible,
                CropBox = SerializeBoundingBox(view.CropBox),
                ScopeBoxId = scopeBoxId,
                ScopeBoxName = scopeBoxId.HasValue ? doc.GetElement(scopeBoxId.Value.ToElementId())?.Name : null
            };
        }

        private object CopyViewCropBox(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType sourceViewId = parameters["sourceViewId"]?.Value<IdType>() ?? 0;
            var targetViewIdsArray = (parameters["targetViewIds"] ?? parameters["viewIds"]) as JArray;
            var targetViewIds = targetViewIdsArray?.Select(x => x.Value<IdType>()).ToList() ?? new List<IdType>();

            bool copyCropVisibility = parameters["copyCropVisibility"]?.Value<bool>() ?? true;
            bool copyCropShape = parameters["copyCropShape"]?.Value<bool>() ?? true;
            bool copyScopeBox = parameters["copyScopeBox"]?.Value<bool>() ?? false;
            bool dryRun = parameters["dryRun"]?.Value<bool>() ?? false;

            View sourceView = doc.GetElement(sourceViewId.ToElementId()) as View;
            if (sourceView == null)
                throw new Exception($"找不到來源視圖: {sourceViewId}");
            if (targetViewIds.Count == 0)
                throw new Exception("請提供 targetViewIds");

            BoundingBoxXYZ sourceBox = CloneBoundingBox(sourceView.CropBox);
            IdType? sourceScopeBoxId = GetAssignedScopeBoxId(sourceView);
            var results = new List<object>();

            Action<View> apply = targetView =>
            {
                var warnings = new List<string>();
                IdType? appliedScopeBoxId = null;
                string appliedScopeBoxName = null;

                if (!dryRun)
                {
                    targetView.CropBox = CloneBoundingBox(sourceBox);
                    if (copyCropVisibility)
                    {
                        targetView.CropBoxActive = sourceView.CropBoxActive;
                        targetView.CropBoxVisible = sourceView.CropBoxVisible;
                    }
                    else
                    {
                        targetView.CropBoxActive = true;
                    }

                    if (copyCropShape)
                    {
                        warnings.AddRange(CopyCropShape(sourceView, targetView));
                    }

                    if (copyScopeBox && sourceScopeBoxId.HasValue)
                    {
                        warnings.AddRange(SetScopeBoxOnView(doc, targetView, sourceScopeBoxId.Value.ToElementId(), out appliedScopeBoxId, out appliedScopeBoxName));
                    }
                }
                else if (copyScopeBox && sourceScopeBoxId.HasValue)
                {
                    appliedScopeBoxId = sourceScopeBoxId;
                    appliedScopeBoxName = doc.GetElement(sourceScopeBoxId.Value.ToElementId())?.Name;
                }

                results.Add(new
                {
                    TargetViewId = targetView.Id.GetIdValue(),
                    TargetViewName = targetView.Name,
                    DryRun = dryRun,
                    AppliedCropBox = SerializeBoundingBox(sourceBox),
                    AppliedScopeBoxId = appliedScopeBoxId,
                    AppliedScopeBoxName = appliedScopeBoxName,
                    Warnings = warnings
                });
            };

            if (dryRun)
            {
                foreach (IdType targetViewId in targetViewIds)
                {
                    View targetView = doc.GetElement(targetViewId.ToElementId()) as View;
                    if (targetView == null)
                    {
                        results.Add(new { TargetViewId = targetViewId, Error = "找不到目標視圖" });
                        continue;
                    }
                    apply(targetView);
                }
            }
            else
            {
                using (Transaction trans = new Transaction(doc, "複製視圖裁切範圍"))
                {
                    trans.Start();
                    foreach (IdType targetViewId in targetViewIds)
                    {
                        View targetView = doc.GetElement(targetViewId.ToElementId()) as View;
                        if (targetView == null)
                        {
                            results.Add(new { TargetViewId = targetViewId, Error = "找不到目標視圖" });
                            continue;
                        }
                        apply(targetView);
                    }
                    trans.Commit();
                }
            }

            return new
            {
                SourceViewId = sourceView.Id.GetIdValue(),
                SourceViewName = sourceView.Name,
                SourceCropBox = SerializeBoundingBox(sourceBox),
                SourceScopeBoxId = sourceScopeBoxId,
                SourceScopeBoxName = sourceScopeBoxId.HasValue ? doc.GetElement(sourceScopeBoxId.Value.ToElementId())?.Name : null,
                Count = results.Count,
                Results = results
            };
        }

        private object ListScopeBoxes()
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            var boxes = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_VolumeOfInterest)
                .WhereElementIsNotElementType()
                .ToElements()
                .Select(e => new
                {
                    ElementId = e.Id.GetIdValue(),
                    Name = e.Name,
                    BoundingBox = SerializeBoundingBox(e.get_BoundingBox(null))
                })
                .OrderBy(e => e.Name)
                .ToList();

            return new { Count = boxes.Count, ScopeBoxes = boxes };
        }

        private object AssignScopeBoxToViews(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType scopeBoxId = parameters["scopeBoxId"]?.Value<IdType>() ?? 0;
            bool clearScopeBox = parameters["clearScopeBox"]?.Value<bool>() ?? false || scopeBoxId <= 0;
            bool dryRun = parameters["dryRun"]?.Value<bool>() ?? false;
            var viewIdsArray = (parameters["viewIds"] ?? parameters["targetViewIds"]) as JArray;
            var viewIds = viewIdsArray?.Select(x => x.Value<IdType>()).ToList() ?? new List<IdType>();

            if (viewIds.Count == 0)
                throw new Exception("請提供 viewIds");

            Element scopeBox = null;
            if (!clearScopeBox)
            {
                scopeBox = doc.GetElement(scopeBoxId.ToElementId());
                if (scopeBox == null)
                    throw new Exception($"找不到 Scope Box: {scopeBoxId}");
            }

            var results = new List<object>();
            Action<View> apply = view =>
            {
                var warnings = new List<string>();
                IdType? appliedScopeBoxId = null;
                string appliedScopeBoxName = null;

                if (!dryRun)
                {
                    warnings.AddRange(SetScopeBoxOnView(
                        doc,
                        view,
                        clearScopeBox ? ElementId.InvalidElementId : scopeBox.Id,
                        out appliedScopeBoxId,
                        out appliedScopeBoxName));
                }
                else if (!clearScopeBox)
                {
                    appliedScopeBoxId = scopeBox.Id.GetIdValue();
                    appliedScopeBoxName = scopeBox.Name;
                }

                results.Add(new
                {
                    ViewId = view.Id.GetIdValue(),
                    ViewName = view.Name,
                    DryRun = dryRun,
                    ClearScopeBox = clearScopeBox,
                    AppliedScopeBoxId = appliedScopeBoxId,
                    AppliedScopeBoxName = appliedScopeBoxName,
                    Warnings = warnings
                });
            };

            if (dryRun)
            {
                foreach (IdType viewId in viewIds)
                {
                    View view = doc.GetElement(viewId.ToElementId()) as View;
                    if (view == null)
                    {
                        results.Add(new { ViewId = viewId, Error = "找不到視圖" });
                        continue;
                    }
                    apply(view);
                }
            }
            else
            {
                using (Transaction trans = new Transaction(doc, "套用範圍框到視圖"))
                {
                    trans.Start();
                    foreach (IdType viewId in viewIds)
                    {
                        View view = doc.GetElement(viewId.ToElementId()) as View;
                        if (view == null)
                        {
                            results.Add(new { ViewId = viewId, Error = "找不到視圖" });
                            continue;
                        }
                        apply(view);
                    }
                    trans.Commit();
                }
            }

            return new
            {
                ScopeBoxId = clearScopeBox ? (IdType?)null : scopeBox.Id.GetIdValue(),
                ScopeBoxName = clearScopeBox ? null : scopeBox.Name,
                Count = results.Count,
                Results = results
            };
        }

        private BoundingBoxXYZ CloneBoundingBox(BoundingBoxXYZ source)
        {
            if (source == null) return null;
            return new BoundingBoxXYZ
            {
                Min = source.Min,
                Max = source.Max,
                Transform = source.Transform,
                Enabled = source.Enabled
            };
        }

        private object SerializeBoundingBox(BoundingBoxXYZ bbox)
        {
            if (bbox == null) return null;

            Transform t = bbox.Transform;
            return new
            {
                min = new { x = bbox.Min.X * 304.8, y = bbox.Min.Y * 304.8, z = bbox.Min.Z * 304.8 },
                max = new { x = bbox.Max.X * 304.8, y = bbox.Max.Y * 304.8, z = bbox.Max.Z * 304.8 },
                transform = new
                {
                    origin = new { x = t.Origin.X * 304.8, y = t.Origin.Y * 304.8, z = t.Origin.Z * 304.8 },
                    basisX = new { x = t.BasisX.X, y = t.BasisX.Y, z = t.BasisX.Z },
                    basisY = new { x = t.BasisY.X, y = t.BasisY.Y, z = t.BasisY.Z },
                    basisZ = new { x = t.BasisZ.X, y = t.BasisZ.Y, z = t.BasisZ.Z }
                }
            };
        }

        private IdType? GetAssignedScopeBoxId(View view)
        {
            Parameter p = view.get_Parameter(BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP);
            if (p == null || p.StorageType != StorageType.ElementId) return null;
            ElementId id = p.AsElementId();
            if (id == null || id == ElementId.InvalidElementId) return null;
            return id.GetIdValue();
        }

        private List<string> SetScopeBoxOnView(Document doc, View view, ElementId scopeBoxElementId, out IdType? appliedScopeBoxId, out string appliedScopeBoxName)
        {
            appliedScopeBoxId = null;
            appliedScopeBoxName = null;
            var warnings = new List<string>();

            Parameter p = view.get_Parameter(BuiltInParameter.VIEWER_VOLUME_OF_INTEREST_CROP);
            if (p == null)
            {
                warnings.Add("此視圖不支援 Scope Box 參數");
                return warnings;
            }

            if (p.IsReadOnly)
            {
                warnings.Add("Scope Box 參數唯讀，可能受 View Template 或視圖類型限制");
                return warnings;
            }

            p.Set(scopeBoxElementId);

            if (scopeBoxElementId != ElementId.InvalidElementId)
            {
                Element scopeBox = doc.GetElement(scopeBoxElementId);
                appliedScopeBoxId = scopeBoxElementId.GetIdValue();
                appliedScopeBoxName = scopeBox?.Name;
            }

            return warnings;
        }

        private List<string> CopyCropShape(View sourceView, View targetView)
        {
            var warnings = new List<string>();
            try
            {
                ViewCropRegionShapeManager sourceManager = sourceView.GetCropRegionShapeManager();
                ViewCropRegionShapeManager targetManager = targetView.GetCropRegionShapeManager();
                IList<CurveLoop> loops = sourceManager.GetCropShape();

                if (loops == null || loops.Count == 0)
                    return warnings;

                if (loops.Count > 1)
                {
                    warnings.Add("來源視圖有多個 Crop Region；目前僅複製 BoundingBox，不複製多區域裁切形狀");
                    return warnings;
                }

                CurveLoop loop = loops[0];
                if (targetManager.IsCropRegionShapeValid(loop))
                {
                    targetManager.SetCropShape(loop);
                }
                else
                {
                    warnings.Add("來源 Crop Shape 對目標視圖無效，已保留 BoundingBox 裁切");
                }
            }
            catch (Exception ex)
            {
                warnings.Add($"複製 Crop Shape 失敗: {ex.Message}");
            }

            return warnings;
        }

        private object CreateGridCroppedViewsBatch(JObject parameters)
        {
            var boundsParams = new JObject
            {
                ["xGrids"] = parameters["x_grid_names"] ?? parameters["xGrids"] ?? new JArray(),
                ["yGrids"] = parameters["y_grid_names"] ?? parameters["yGrids"] ?? new JArray(),
                ["offset_mm"] = parameters["offset_mm"] ?? parameters["offsetMm"] ?? 1000
            };

            JObject bounds = JObject.FromObject(CalculateGridBounds(boundsParams));

            var createParams = new JObject
            {
                ["parentViewIds"] = parameters["parentViewIds"] ?? new JArray(),
                ["suffixName"] = parameters["suffixName"],
                ["min"] = bounds["min"],
                ["max"] = bounds["max"]
            };

            object createdViews = CreateDependentViews(createParams);

            return new
            {
                Bounds = bounds,
                CreatedViews = createdViews
            };
        }

        #endregion
    }
}
