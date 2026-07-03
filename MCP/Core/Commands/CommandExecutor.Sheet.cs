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
        #region 圖紙管理

        /// <summary>
        /// 取得所有圖紙
        /// </summary>
        private object GetAllSheets()
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            var sheets = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .Select(s => new
                {
                    ElementId = s.Id.GetIdValue(),
                    SheetNumber = s.SheetNumber,
                    SheetName = s.Name
                })
                .OrderBy(s => s.SheetNumber)
                .ToList();

            return new
            {
                Count = sheets.Count,
                Sheets = sheets
            };
        }

        /// <summary>
        /// 取得圖框類型
        /// </summary>
        private object GetTitleBlocks()
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            var titleBlocks = new FilteredElementCollector(doc)
                .OfClass(typeof(FamilySymbol))
                .OfCategory(BuiltInCategory.OST_TitleBlocks)
                .Cast<FamilySymbol>()
                .Select(fs => new
                {
                    ElementId = fs.Id.GetIdValue(),
                    Name = fs.Name,
                    FamilyName = fs.FamilyName
                })
                .OrderBy(t => t.FamilyName)
                .ThenBy(t => t.Name)
                .ToList();

            return new
            {
                Count = titleBlocks.Count,
                TitleBlocks = titleBlocks
            };
        }

        /// <summary>
        /// 批次建立圖紙
        /// </summary>
        private object CreateSheets(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType titleBlockId = parameters["titleBlockId"]?.Value<IdType>() ?? 0;
            var sheetsArray = parameters["sheets"] as JArray;

            if (titleBlockId == 0)
                throw new Exception("請提供圖框類型 ID (titleBlockId)");

            if (sheetsArray == null || sheetsArray.Count == 0)
                throw new Exception("請提供要建立的圖紙清單 (sheets)");

            ElementId tbId = titleBlockId.ToElementId();
            Element tbType = doc.GetElement(tbId);
            if (tbType == null)
                throw new Exception($"找不到圖框類型 ID: {titleBlockId}");

            List<object> results = new List<object>();

            using (Transaction trans = new Transaction(doc, "批次建立圖紙"))
            {
                trans.Start();

                foreach (var s in sheetsArray)
                {
                    string number = s["number"]?.Value<string>();
                    string name = s["name"]?.Value<string>();

                    try
                    {
                        ViewSheet sheet = ViewSheet.Create(doc, tbId);
                        if (!string.IsNullOrEmpty(number))
                            sheet.SheetNumber = number;
                        if (!string.IsNullOrEmpty(name))
                            sheet.Name = name;

                        results.Add(new
                        {
                            ElementId = sheet.Id.GetIdValue(),
                            SheetNumber = sheet.SheetNumber,
                            SheetName = sheet.Name,
                            Success = true
                        });
                    }
                    catch (Exception ex)
                    {
                        results.Add(new
                        {
                            SheetNumber = number,
                            SheetName = name,
                            Success = false,
                            Error = ex.Message
                        });
                    }
                }

                trans.Commit();
            }

            return new
            {
                Total = sheetsArray.Count,
                Results = results
            };
        }

        /// <summary>
        /// 取得視埠與圖紙的對應表
        /// </summary>
        private object GetViewportMap()
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            var result = new List<object>();

            var sheets = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .ToList();

            foreach (var sheet in sheets)
            {
                var vportIds = sheet.GetAllViewports();
                foreach (var vpId in vportIds)
                {
                    var vp = doc.GetElement(vpId) as Viewport;
                    if (vp != null)
                    {
                        var view = doc.GetElement(vp.ViewId) as View;
                        result.Add(new
                        {
                            SheetId = sheet.Id.GetIdValue(),
                            SheetNumber = sheet.SheetNumber,
                            SheetName = sheet.Name,
                            ViewportId = vp.Id.GetIdValue(),
                            ViewId = vp.ViewId.GetIdValue(),
                            ViewName = view?.Name ?? "Unknown",
                            ViewType = view?.ViewType.ToString() ?? "Unknown"
                        });
                    }
                }
            }

            return result;
        }

        /// <summary>
        /// 自動修正圖紙編號 (掃描 -1 後綴並合併)
        /// </summary>
        private object GetSheetViewportDetails(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            HashSet<string> sheetNumberFilter = GetSheetNumberFilter(parameters);
            HashSet<string> sheetNameFilter = GetSheetNameFilter(parameters);
            IdType sheetId = parameters["sheetId"]?.Value<IdType>() ?? 0;

            var sheets = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .Where(s => sheetId <= 0 || s.Id.GetIdValue().Equals(sheetId))
                .Where(s => sheetNumberFilter.Count == 0 || sheetNumberFilter.Contains(s.SheetNumber))
                .Where(s => sheetNameFilter.Count == 0 || sheetNameFilter.Contains(s.Name))
                .OrderBy(s => s.SheetNumber)
                .ToList();

            var results = sheets.Select(sheet => new
            {
                SheetId = sheet.Id.GetIdValue(),
                SheetNumber = sheet.SheetNumber,
                SheetName = sheet.Name,
                Viewports = sheet.GetAllViewports()
                    .Select(id => doc.GetElement(id) as Viewport)
                    .Where(vp => vp != null)
                    .Select(vp => BuildViewportDetail(doc, sheet, vp))
                    .ToList()
            }).ToList();

            return new
            {
                Count = results.Count,
                Sheets = results
            };
        }

        private object CopySheetViewports(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            JArray items = parameters["items"] as JArray;
            if (items == null || items.Count == 0)
                throw new Exception("請提供 items 陣列");

            bool dryRun = parameters["dryRun"]?.Value<bool>() ?? false;
            bool copyViewportType = parameters["copyViewportType"]?.Value<bool>() ?? true;
            bool copyRotation = parameters["copyRotation"]?.Value<bool>() ?? true;
            bool copyDetailNumber = parameters["copyDetailNumber"]?.Value<bool>() ?? true;
            bool copyLabel = parameters["copyLabel"]?.Value<bool>() ?? true;
            bool moveExisting = parameters["moveExisting"]?.Value<bool>() ?? true;

            var plans = new List<SheetViewportCopyPlan>();
            foreach (JToken item in items)
            {
                string sourceSheetNumber = item["sourceSheetNumber"]?.Value<string>();
                string targetSheetNumber = item["targetSheetNumber"]?.Value<string>();
                string sourceSheetName = item["sourceSheetName"]?.Value<string>();
                string targetSheetName = item["targetSheetName"]?.Value<string>();
                IdType sourceViewId = item["sourceViewId"]?.Value<IdType>() ?? 0;
                IdType targetViewId = item["targetViewId"]?.Value<IdType>() ?? 0;

                ViewSheet sourceSheet = FindSheet(doc, sourceSheetNumber, sourceSheetName);
                ViewSheet targetSheet = FindSheet(doc, targetSheetNumber, targetSheetName);
                if (sourceSheet == null)
                    throw new Exception($"找不到來源圖紙: {sourceSheetNumber}");
                if (targetSheet == null)
                    throw new Exception($"找不到目標圖紙: {targetSheetNumber}");

                Viewport sourceViewport = FindViewportOnSheet(doc, sourceSheet, sourceViewId, "FloorPlan");
                if (sourceViewport == null)
                    throw new Exception($"來源圖紙 {sourceSheetNumber} 找不到指定的平面圖視埠");

                View targetView = doc.GetElement(targetViewId.ToElementId()) as View;
                if (targetView == null)
                    throw new Exception($"找不到目標視圖: {targetViewId}");

                Viewport existingTargetViewport = FindViewportOnSheet(doc, targetSheet, targetViewId, null);
                if (existingTargetViewport == null && !Viewport.CanAddViewToSheet(doc, targetSheet.Id, targetView.Id))
                    throw new Exception($"視圖已無法放置到圖紙 {targetSheetNumber}: {targetView.Name}");

                if (existingTargetViewport != null && !moveExisting)
                    throw new Exception($"目標圖紙 {targetSheetNumber} 已有此視圖視埠，且 moveExisting=false");

                plans.Add(new SheetViewportCopyPlan
                {
                    SourceSheet = sourceSheet,
                    TargetSheet = targetSheet,
                    SourceViewport = sourceViewport,
                    TargetView = targetView,
                    ExistingTargetViewport = existingTargetViewport,
                    SourceCenter = sourceViewport.GetBoxCenter()
                });
            }

            var results = new List<object>();
            if (dryRun)
            {
                foreach (var plan in plans)
                {
                    results.Add(BuildSheetViewportCopyResult(plan, null, true, "dryRun"));
                }
            }
            else
            {
                using (Transaction trans = new Transaction(doc, "複製圖紙視埠配置"))
                {
                    trans.Start();
                    foreach (var plan in plans)
                    {
                        Viewport targetViewport = plan.ExistingTargetViewport;
                        string action = "moved";
                        if (targetViewport == null)
                        {
                            targetViewport = Viewport.Create(doc, plan.TargetSheet.Id, plan.TargetView.Id, plan.SourceCenter);
                            action = "created";
                        }

                        if (copyViewportType)
                        {
                            ElementId sourceTypeId = plan.SourceViewport.GetTypeId();
                            if (sourceTypeId != null && sourceTypeId != ElementId.InvalidElementId && targetViewport.GetTypeId() != sourceTypeId)
                                targetViewport.ChangeTypeId(sourceTypeId);
                        }

                        if (copyRotation)
                            targetViewport.Rotation = plan.SourceViewport.Rotation;

                        if (copyDetailNumber)
                            CopyViewportStringParameter(plan.SourceViewport, targetViewport, BuiltInParameter.VIEWPORT_DETAIL_NUMBER);

                        if (copyLabel)
                            CopyViewportLabel(plan.SourceViewport, targetViewport);

                        targetViewport.SetBoxCenter(plan.SourceCenter);
                        doc.Regenerate();
                        targetViewport.SetBoxCenter(plan.SourceCenter);

                        results.Add(BuildSheetViewportCopyResult(plan, targetViewport, false, action));
                    }
                    trans.Commit();
                }
            }

            return new
            {
                DryRun = dryRun,
                Count = results.Count,
                Results = results
            };
        }

        private object GetViewportTypes(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            string nameContains = parameters["nameContains"]?.Value<string>();

            var types = CollectViewportTypes(doc)
                .Where(t => string.IsNullOrWhiteSpace(nameContains) || t.Name.IndexOf(nameContains, StringComparison.OrdinalIgnoreCase) >= 0)
                .OrderBy(t => t.Name)
                .Select(t => new
                {
                    TypeId = t.Id.GetIdValue(),
                    TypeName = t.Name,
                    FamilyName = t.FamilyName
                })
                .ToList();

            return new
            {
                Count = types.Count,
                ViewportTypes = types
            };
        }

        private object SyncViewportTypesByViewScale(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            bool dryRun = parameters["dryRun"]?.Value<bool>() ?? false;
            string exactPattern = parameters["exactPattern"]?.Value<string>() ?? "附圖號的有比例標題_A1({scale})A3({doubleScale})";
            string fallbackNameContains = parameters["fallbackNameContains"]?.Value<string>() ?? "有線條的標題";
            HashSet<string> sheetNumberFilter = GetSheetNumberFilter(parameters);
            HashSet<string> sheetNameFilter = GetSheetNameFilter(parameters);
            HashSet<string> allowedViewTypes = ReadViewportViewTypes(parameters);
            HashSet<string> excludedViewTitleKeywords = ReadExcludedViewportTitleKeywords(parameters);

            var viewportTypes = CollectViewportTypes(doc);

            ElementType fallbackType = ResolveFallbackViewportType(viewportTypes, fallbackNameContains);
            if (fallbackType == null)
                throw new Exception($"Fallback viewport type containing '{fallbackNameContains}' was not found.");

            var sheets = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .Where(s => sheetNumberFilter.Count == 0 || sheetNumberFilter.Contains(s.SheetNumber))
                .Where(s => sheetNameFilter.Count == 0 || sheetNameFilter.Contains(s.Name))
                .OrderBy(s => s.SheetNumber)
                .ToList();

            var plans = new List<ViewportTypeScalePlan>();
            int skippedByTitleKeywordCount = 0;
            foreach (ViewSheet sheet in sheets)
            {
                foreach (ElementId viewportId in sheet.GetAllViewports())
                {
                    Viewport viewport = doc.GetElement(viewportId) as Viewport;
                    if (viewport == null) continue;

                    View view = doc.GetElement(viewport.ViewId) as View;
                    if (view == null || !allowedViewTypes.Contains(view.ViewType.ToString()))
                        continue;

                    string titleOnSheet = ReadViewTitleOnSheet(view);
                    if (ContainsAnyKeyword(view.Name, excludedViewTitleKeywords) || ContainsAnyKeyword(titleOnSheet, excludedViewTitleKeywords))
                    {
                        skippedByTitleKeywordCount++;
                        continue;
                    }

                    int scale = view.Scale;
                    string expectedName = exactPattern
                        .Replace("{scale}", scale.ToString())
                        .Replace("{doubleScale}", (scale * 2).ToString());
                    ElementType exactType = viewportTypes.FirstOrDefault(t => t.Name.Equals(expectedName, StringComparison.OrdinalIgnoreCase));
                    ElementType targetType = exactType ?? fallbackType;
                    ElementId currentTypeId = viewport.GetTypeId();

                    plans.Add(new ViewportTypeScalePlan
                    {
                        Sheet = sheet,
                        Viewport = viewport,
                        View = view,
                        CurrentType = doc.GetElement(currentTypeId) as ElementType,
                        TargetType = targetType,
                        MatchedExact = exactType != null,
                        ExpectedTypeName = expectedName
                    });
                }
            }

            if (!dryRun)
            {
                using (Transaction trans = new Transaction(doc, "Sync viewport types by view scale"))
                {
                    trans.Start();
                    foreach (ViewportTypeScalePlan plan in plans)
                    {
                        if (plan.TargetType != null && plan.Viewport.GetTypeId() != plan.TargetType.Id)
                            plan.Viewport.ChangeTypeId(plan.TargetType.Id);
                    }
                    trans.Commit();
                }
            }

            var results = plans.Select(plan => new
            {
                SheetId = plan.Sheet.Id.GetIdValue(),
                SheetNumber = plan.Sheet.SheetNumber,
                SheetName = plan.Sheet.Name,
                ViewportId = plan.Viewport.Id.GetIdValue(),
                ViewId = plan.View.Id.GetIdValue(),
                ViewName = plan.View.Name,
                ViewType = plan.View.ViewType.ToString(),
                ViewScale = plan.View.Scale,
                CurrentTypeId = plan.CurrentType?.Id.GetIdValue(),
                CurrentTypeName = plan.CurrentType?.Name,
                TargetTypeId = plan.TargetType?.Id.GetIdValue(),
                TargetTypeName = plan.TargetType?.Name,
                ExpectedTypeName = plan.ExpectedTypeName,
                MatchedExactScaleType = plan.MatchedExact,
                Action = plan.CurrentType?.Id == plan.TargetType?.Id ? "unchanged" : (dryRun ? "wouldChange" : "changed")
            }).ToList();

            return new
            {
                DryRun = dryRun,
                Count = results.Count,
                ChangedCount = results.Count(r => r.Action == "changed" || r.Action == "wouldChange"),
                FallbackTypeId = fallbackType.Id.GetIdValue(),
                FallbackTypeName = fallbackType.Name,
                AllowedViewTypes = allowedViewTypes.OrderBy(v => v).ToList(),
                ExcludedViewTitleKeywords = excludedViewTitleKeywords.OrderBy(v => v).ToList(),
                SkippedByTitleKeywordCount = skippedByTitleKeywordCount,
                Results = results
            };
        }

        private List<ElementType> CollectViewportTypes(Document doc)
        {
            Viewport sampleViewport = new FilteredElementCollector(doc)
                .OfClass(typeof(Viewport))
                .Cast<Viewport>()
                .FirstOrDefault();

            var ids = new HashSet<IdType>();
            if (sampleViewport != null)
            {
                ElementId currentTypeId = sampleViewport.GetTypeId();
                if (currentTypeId != null && currentTypeId != ElementId.InvalidElementId)
                    ids.Add(currentTypeId.GetIdValue());

                foreach (ElementId typeId in sampleViewport.GetValidTypes())
                {
                    if (typeId != null && typeId != ElementId.InvalidElementId)
                        ids.Add(typeId.GetIdValue());
                }
            }

            return ids
                .Select(id => doc.GetElement(id.ToElementId()) as ElementType)
                .Where(t => t != null)
                .OrderBy(t => t.Name)
                .ToList();
        }

        private bool ContainsAnyKeyword(string value, HashSet<string> keywords)
        {
            if (string.IsNullOrWhiteSpace(value) || keywords == null || keywords.Count == 0)
                return false;

            return keywords.Any(keyword => value.IndexOf(keyword, StringComparison.OrdinalIgnoreCase) >= 0);
        }

        private string ReadViewTitleOnSheet(View view)
        {
            Parameter parameter = view?.get_Parameter(BuiltInParameter.VIEW_DESCRIPTION);
            return parameter?.AsString();
        }

        private HashSet<string> ReadViewportViewTypes(JObject parameters)
        {
            var defaultTypes = new[] { "FloorPlan", "Elevation", "Section" };
            JArray array = parameters["viewTypes"] as JArray;
            IEnumerable<string> values = array != null
                ? array.Select(v => v.Value<string>())
                : defaultTypes;

            return new HashSet<string>(
                values.Where(v => !string.IsNullOrWhiteSpace(v)).Select(v => v.Trim()),
                StringComparer.OrdinalIgnoreCase);
        }

        private HashSet<string> ReadExcludedViewportTitleKeywords(JObject parameters)
        {
            var defaults = new[] { "圖例" };
            JArray array = parameters["excludeViewTitleContains"] as JArray;
            IEnumerable<string> values = array != null
                ? array.Select(v => v.Value<string>())
                : defaults;

            string single = parameters["excludeViewTitleContains"]?.Type == JTokenType.String
                ? parameters["excludeViewTitleContains"]?.Value<string>()
                : null;

            if (!string.IsNullOrWhiteSpace(single))
                values = new[] { single };

            return new HashSet<string>(
                values.Where(v => !string.IsNullOrWhiteSpace(v)).Select(v => v.Trim()),
                StringComparer.OrdinalIgnoreCase);
        }

        private ElementType ResolveFallbackViewportType(List<ElementType> viewportTypes, string fallbackNameContains)
        {
            if (string.IsNullOrWhiteSpace(fallbackNameContains))
                return null;

            return viewportTypes
                .Where(t => t.Name.IndexOf(fallbackNameContains, StringComparison.OrdinalIgnoreCase) >= 0)
                .OrderBy(t => t.Name.Length)
                .ThenBy(t => t.Name)
                .FirstOrDefault();
        }

        private HashSet<string> GetSheetNumberFilter(JObject parameters)
        {
            var filters = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            string sheetNumber = parameters["sheetNumber"]?.Value<string>();
            if (!string.IsNullOrWhiteSpace(sheetNumber))
                filters.Add(sheetNumber.Trim());

            JArray sheetNumbers = parameters["sheetNumbers"] as JArray;
            if (sheetNumbers != null)
            {
                foreach (JToken token in sheetNumbers)
                {
                    string value = token.Value<string>();
                    if (!string.IsNullOrWhiteSpace(value))
                        filters.Add(value.Trim());
                }
            }

            return filters;
        }

        private HashSet<string> GetSheetNameFilter(JObject parameters)
        {
            var filters = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            string sheetName = parameters["sheetName"]?.Value<string>();
            if (!string.IsNullOrWhiteSpace(sheetName))
                filters.Add(sheetName.Trim());

            JArray sheetNames = parameters["sheetNames"] as JArray;
            if (sheetNames != null)
            {
                foreach (JToken token in sheetNames)
                {
                    string value = token.Value<string>();
                    if (!string.IsNullOrWhiteSpace(value))
                        filters.Add(value.Trim());
                }
            }

            return filters;
        }

        private ViewSheet FindSheet(Document doc, string sheetNumber, string sheetName)
        {
            ViewSheet sheet = FindSheetByNumber(doc, sheetNumber);
            if (sheet != null)
                return sheet;

            return FindSheetByName(doc, sheetName);
        }

        private ViewSheet FindSheetByNumber(Document doc, string sheetNumber)
        {
            if (string.IsNullOrWhiteSpace(sheetNumber))
                return null;

            return new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .FirstOrDefault(s => s.SheetNumber.Equals(sheetNumber.Trim(), StringComparison.OrdinalIgnoreCase));
        }

        private ViewSheet FindSheetByName(Document doc, string sheetName)
        {
            if (string.IsNullOrWhiteSpace(sheetName))
                return null;

            string trimmed = sheetName.Trim();
            var matches = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .Where(s => s.Name.Equals(trimmed, StringComparison.OrdinalIgnoreCase))
                .ToList();

            if (matches.Count > 1)
                throw new Exception($"Multiple sheets match name '{trimmed}'. Provide sheet number or sheet id to disambiguate.");

            return matches.FirstOrDefault();
        }

        private Viewport FindViewportOnSheet(Document doc, ViewSheet sheet, IdType viewId, string fallbackViewType)
        {
            foreach (ElementId viewportId in sheet.GetAllViewports())
            {
                Viewport viewport = doc.GetElement(viewportId) as Viewport;
                if (viewport == null) continue;

                if (viewId > 0 && viewport.ViewId.GetIdValue().Equals(viewId))
                    return viewport;

                if (viewId <= 0 && !string.IsNullOrEmpty(fallbackViewType))
                {
                    View view = doc.GetElement(viewport.ViewId) as View;
                    if (view != null && view.ViewType.ToString().Equals(fallbackViewType, StringComparison.OrdinalIgnoreCase))
                        return viewport;
                }
            }

            return null;
        }

        private object BuildViewportDetail(Document doc, ViewSheet sheet, Viewport viewport)
        {
            View view = doc.GetElement(viewport.ViewId) as View;
            XYZ center = viewport.GetBoxCenter();
            Outline outline = viewport.GetBoxOutline();

            return new
            {
                SheetId = sheet.Id.GetIdValue(),
                SheetNumber = sheet.SheetNumber,
                SheetName = sheet.Name,
                ViewportId = viewport.Id.GetIdValue(),
                ViewportTypeId = viewport.GetTypeId().GetIdValue(),
                ViewId = viewport.ViewId.GetIdValue(),
                ViewName = view?.Name ?? "Unknown",
                ViewType = view?.ViewType.ToString() ?? "Unknown",
                DetailNumber = ReadViewportStringParameter(viewport, BuiltInParameter.VIEWPORT_DETAIL_NUMBER),
                Rotation = viewport.Rotation.ToString(),
                BoxCenter = SerializeSheetPoint(center),
                BoxOutline = new
                {
                    Minimum = SerializeSheetPoint(outline.MinimumPoint),
                    Maximum = SerializeSheetPoint(outline.MaximumPoint)
                },
                LabelOffset = SerializeSheetPoint(GetViewportLabelOffset(viewport)),
                LabelLineLength = GetViewportLabelLineLengthMm(viewport)
            };
        }

        private object BuildSheetViewportCopyResult(SheetViewportCopyPlan plan, Viewport targetViewport, bool dryRun, string action)
        {
            Viewport finalViewport = targetViewport ?? plan.ExistingTargetViewport;
            XYZ targetCenter = finalViewport != null ? finalViewport.GetBoxCenter() : plan.SourceCenter;
            XYZ delta = targetCenter - plan.SourceCenter;

            return new
            {
                Action = action,
                DryRun = dryRun,
                SourceSheetNumber = plan.SourceSheet.SheetNumber,
                SourceSheetName = plan.SourceSheet.Name,
                TargetSheetNumber = plan.TargetSheet.SheetNumber,
                TargetSheetName = plan.TargetSheet.Name,
                SourceViewportId = plan.SourceViewport.Id.GetIdValue(),
                TargetViewportId = finalViewport?.Id.GetIdValue(),
                SourceViewId = plan.SourceViewport.ViewId.GetIdValue(),
                TargetViewId = plan.TargetView.Id.GetIdValue(),
                TargetViewName = plan.TargetView.Name,
                SourceCenter = SerializeSheetPoint(plan.SourceCenter),
                TargetCenter = SerializeSheetPoint(targetCenter),
                DeltaMm = SerializeSheetPoint(delta)
            };
        }

        private object SerializeSheetPoint(XYZ point)
        {
            if (point == null) return null;
            return new
            {
                x = point.X * 304.8,
                y = point.Y * 304.8,
                z = point.Z * 304.8
            };
        }

        private string ReadViewportStringParameter(Viewport viewport, BuiltInParameter parameterId)
        {
            Parameter parameter = viewport.get_Parameter(parameterId);
            return parameter?.AsString();
        }

        private void CopyViewportStringParameter(Viewport source, Viewport target, BuiltInParameter parameterId)
        {
            Parameter sourceParameter = source.get_Parameter(parameterId);
            Parameter targetParameter = target.get_Parameter(parameterId);
            if (sourceParameter == null || targetParameter == null || targetParameter.IsReadOnly)
                return;

            targetParameter.Set(sourceParameter.AsString() ?? "");
        }

        private void CopyViewportLabel(Viewport source, Viewport target)
        {
            try
            {
                CopyViewportProperty(source, target, "LabelOffset");
                CopyViewportProperty(source, target, "LabelLineLength");
            }
            catch (Exception ex)
            {
                Logger.Debug($"複製視埠標籤設定失敗: {ex.Message}");
            }
        }

        private XYZ GetViewportLabelOffset(Viewport viewport)
        {
            object value = GetViewportProperty(viewport, "LabelOffset");
            return value as XYZ;
        }

        private double? GetViewportLabelLineLengthMm(Viewport viewport)
        {
            object value = GetViewportProperty(viewport, "LabelLineLength");
            if (value is double lengthFeet)
                return lengthFeet * 304.8;
            return null;
        }

        private object GetViewportProperty(Viewport viewport, string propertyName)
        {
            var property = viewport.GetType().GetProperty(propertyName);
            if (property == null || !property.CanRead)
                return null;
            return property.GetValue(viewport, null);
        }

        private void CopyViewportProperty(Viewport source, Viewport target, string propertyName)
        {
            var sourceProperty = source.GetType().GetProperty(propertyName);
            var targetProperty = target.GetType().GetProperty(propertyName);
            if (sourceProperty == null || targetProperty == null || !sourceProperty.CanRead || !targetProperty.CanWrite)
                return;

            object value = sourceProperty.GetValue(source, null);
            targetProperty.SetValue(target, value, null);
        }

        private class SheetViewportCopyPlan
        {
            public ViewSheet SourceSheet { get; set; }
            public ViewSheet TargetSheet { get; set; }
            public Viewport SourceViewport { get; set; }
            public View TargetView { get; set; }
            public Viewport ExistingTargetViewport { get; set; }
            public XYZ SourceCenter { get; set; }
        }

        private class ViewportTypeScalePlan
        {
            public ViewSheet Sheet { get; set; }
            public Viewport Viewport { get; set; }
            public View View { get; set; }
            public ElementType CurrentType { get; set; }
            public ElementType TargetType { get; set; }
            public bool MatchedExact { get; set; }
            public string ExpectedTypeName { get; set; }
        }

        private object AutoRenumberSheets(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            // Phase 0: Emergency Recovery (Fix _MCPFIX)
            var fixSheets = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .Where(s => s.SheetNumber.EndsWith("_MCPFIX"))
                .ToList();

            if (fixSheets.Count > 0)
            {
                using (Transaction tFix = new Transaction(doc, "還原_MCPFIX"))
                {
                    tFix.Start();
                    foreach (var s in fixSheets)
                    {
                        string original = s.SheetNumber.Replace("_MCPFIX", "");
                        try { s.SheetNumber = original; }
                        catch (Exception ex) { Logger.Debug($"還原 _MCPFIX 失敗: {ex.Message}"); }
                    }
                    tFix.Commit();
                }
            }

            // 1. 重新掃描所有圖紙
            var allSheets = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .ToList();

            var insertSheets = allSheets
                .Where(s => s.SheetNumber.EndsWith("-1"))
                .OrderBy(s => s.SheetNumber)
                .ToList();

            if (insertSheets.Count == 0)
                return new { Success = true, Message = "專案中沒有發現帶有 '-1' 後綴的圖紙" };

            var sheetMap = allSheets.ToDictionary(s => s.SheetNumber, s => s.Id.GetIdValue());
            Dictionary<IdType, string> finalMoves = new Dictionary<IdType, string>();
            Dictionary<string, IdType> reservationMap = new Dictionary<string, IdType>(sheetMap.Count);
            foreach (var kvp in sheetMap) reservationMap[kvp.Key] = kvp.Value;

            int processedInsertions = 0;

            // 2. 計算變更 (模擬過程)
            foreach (var sourceSheet in insertSheets)
            {
                IdType sourceId = sourceSheet.Id.GetIdValue();
                string sourceNumber = sourceSheet.SheetNumber;
                string baseNumber = sourceNumber.Substring(0, sourceNumber.Length - 2);
                string targetNumber = IncrementString(baseNumber);

                string currentMoverNumber = targetNumber;
                IdType currentMoverId = sourceId;

                while (true)
                {
                    if (reservationMap.ContainsKey(currentMoverNumber))
                    {
                        IdType occupierId = reservationMap[currentMoverNumber];
                        if (occupierId == currentMoverId) break;

                        finalMoves[currentMoverId] = currentMoverNumber;
                        reservationMap[currentMoverNumber] = currentMoverId;
                        currentMoverId = occupierId;
                        currentMoverNumber = IncrementString(currentMoverNumber);
                    }
                    else
                    {
                        finalMoves[currentMoverId] = currentMoverNumber;
                        reservationMap[currentMoverNumber] = currentMoverId;
                        break;
                    }

                    if (finalMoves.Count > 2000) break;
                }

                processedInsertions++;
            }

            // 3. 執行變更
            finalMoves = OptimizeSheetOrder(doc, finalMoves);

            int changedCount = 0;
            if (finalMoves.Count > 0)
            {
                using (TransactionGroup tg = new TransactionGroup(doc, "自動圖紙編號修正"))
                {
                    tg.Start();

                    using (Transaction t1 = new Transaction(doc, "Step1:暫存"))
                    {
                        t1.Start();
                        foreach (var id in finalMoves.Keys)
                        {
                            Element elem = doc.GetElement(id.ToElementId());
                            if (elem != null)
                            {
                                Parameter p = elem.get_Parameter(BuiltInParameter.SHEET_NUMBER);
                                if (p != null) p.Set(p.AsString() + "_TEMP_" + Guid.NewGuid().ToString().Substring(0, 5));
                            }
                        }
                        t1.Commit();
                    }

                    using (Transaction t2 = new Transaction(doc, "Step2:最終"))
                    {
                        t2.Start();
                        foreach (var kvp in finalMoves)
                        {
                            Element elem = doc.GetElement(kvp.Key.ToElementId());
                            if (elem != null)
                            {
                                Parameter p = elem.get_Parameter(BuiltInParameter.SHEET_NUMBER);
                                if (p != null) p.Set(kvp.Value);
                                changedCount++;
                            }
                        }
                        t2.Commit();
                    }

                    tg.Assimilate();
                }
            }

            return new
            {
                Success = true,
                ChangedCount = changedCount,
                InsertionsResolved = processedInsertions,
                Message = $"修復並更新完成：處理了 {processedInsertions} 張插入圖紙，共更新 {changedCount} 個編號"
            };
        }

        private List<string> GenerateSequence(string start, int count)
        {
            List<string> result = new List<string> { start };
            string current = start;
            for (int i = 1; i < count; i++)
            {
                current = IncrementString(current);
                result.Add(current);
            }
            return result;
        }

        private string IncrementString(string input)
        {
            var match = System.Text.RegularExpressions.Regex.Match(input, @"(.*?)([0-9]+)$");
            if (match.Success)
            {
                string prefix = match.Groups[1].Value;
                string numberStr = match.Groups[2].Value;
                long number = long.Parse(numberStr) + 1;
                return prefix + number.ToString().PadLeft(numberStr.Length, '0');
            }
            return input + "-1";
        }

        private Dictionary<IdType, string> OptimizeSheetOrder(Document doc, Dictionary<IdType, string> moves)
        {
            var participants = new List<SheetSortInfo>();
            foreach (var kvp in moves)
            {
                Element elem = doc.GetElement(kvp.Key.ToElementId());
                if (elem != null && elem is ViewSheet sheet)
                {
                    participants.Add(new SheetSortInfo { ID = kvp.Key, Name = sheet.Name, TargetNumber = kvp.Value });
                }
            }

            var regex = new System.Text.RegularExpressions.Regex(@"^(.*?)[\(\（]([\d一二三四五六七八九十]+)(?:/[\d]+)?[\)\）]$");
            var matched = participants
                .Select(p => { var m = regex.Match(p.Name); return new { Data = p, Match = m }; })
                .Where(x => x.Match.Success)
                .Select(x => new SheetMatchItem
                {
                    Data = x.Data,
                    BaseName = x.Match.Groups[1].Value.Trim(),
                    MatchIndex = GetSheetNameIndex(x.Match.Groups[2].Value)
                })
                .ToList();

            var groups = matched.GroupBy(x => x.BaseName).ToList();
            var newMoves = new Dictionary<IdType, string>(moves);

            foreach (var grp in groups)
            {
                var items = grp.ToList();
                if (items.Count < 2) continue;

                items.Sort((a, b) => string.Compare(a.Data.TargetNumber, b.Data.TargetNumber, StringComparison.Ordinal));

                var subGroups = new List<List<SheetMatchItem>>();
                var currentSubGroup = new List<SheetMatchItem> { items[0] };

                for (int i = 1; i < items.Count; i++)
                {
                    long prevNum = ExtractTrailingNumber(items[i - 1].Data.TargetNumber);
                    long currNum = ExtractTrailingNumber(items[i].Data.TargetNumber);

                    if (currNum - prevNum <= 3)
                        currentSubGroup.Add(items[i]);
                    else
                    {
                        subGroups.Add(currentSubGroup);
                        currentSubGroup = new List<SheetMatchItem> { items[i] };
                    }
                }
                subGroups.Add(currentSubGroup);

                foreach (var subGrp in subGroups)
                {
                    if (subGrp.Count < 2) continue;
                    var targetNumbers = subGrp.Select(x => x.Data.TargetNumber).OrderBy(n => n).ToList();
                    var sortedSheets = subGrp.OrderBy(x => x.MatchIndex).ToList();
                    for (int i = 0; i < sortedSheets.Count; i++)
                    {
                        if (i < targetNumbers.Count)
                            newMoves[sortedSheets[i].Data.ID] = targetNumbers[i];
                    }
                }
            }

            return newMoves;
        }

        private long ExtractTrailingNumber(string input)
        {
            var match = System.Text.RegularExpressions.Regex.Match(input, @"(\d+)$");
            if (match.Success) return long.Parse(match.Groups[1].Value);
            return 0;
        }

        private int GetSheetNameIndex(string val)
        {
            if (int.TryParse(val, out int n)) return n;
            switch (val)
            {
                case "一": return 1; case "二": return 2; case "三": return 3;
                case "四": return 4; case "五": return 5; case "六": return 6;
                case "七": return 7; case "八": return 8; case "九": return 9;
                case "十": return 10; default: return 999;
            }
        }

        private class SheetSortInfo
        {
            public IdType ID { get; set; }
            public string Name { get; set; }
            public string TargetNumber { get; set; }
        }

        private class SheetMatchItem
        {
            public SheetSortInfo Data { get; set; }
            public string BaseName { get; set; }
            public int MatchIndex { get; set; }
        }

        #endregion
    }
}
