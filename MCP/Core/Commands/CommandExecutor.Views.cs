using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
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
        private class DependentViewData
        {
            public View View;
            public string SheetLabel;
            public double MinU;
            public double MaxU;
            public double MinV;
            public double MaxV;

            public double CenterU
            {
                get { return (MinU + MaxU) / 2.0; }
            }

            public double CenterV
            {
                get { return (MinV + MaxV) / 2.0; }
            }
        }

        private enum MatchlineSide
        {
            West,
            East,
            South,
            North
        }

        private class MatchlineSideClaim
        {
            public DependentViewData Source;
            public DependentViewData Target;
            public MatchlineSide Side;
            public double MinAlong;
            public double MaxAlong;
            public double Boundary;
            public double NormalDistance;
            public double FacingDistance;
        }

        private class OwnedMatchlineSpan
        {
            public MatchlineSideClaim Claim;
            public double MinAlong;
            public double MaxAlong;
        }

        private class MutualMatchlineSpan
        {
            public DependentViewData View1;
            public DependentViewData View2;
            public bool IsVertical;
            public double Boundary;
            public double MinAlong;
            public double MaxAlong;
        }

        private class MatchlineResult
        {
            public string View1;
            public string View2;
        }

        private class MatchlineCandidate
        {
            public DependentViewData View1;
            public DependentViewData View2;
            public Line Line;
            public XYZ TextPos1;
            public XYZ TextPos2;
            public bool IsVertical;
            public double MinAlong;
            public double MaxAlong;
            public string PairKey;
        }

        /// <summary>
        /// 自動為母視圖底下的所有從屬視圖，根據其邊界繪製銜接線與加上文字標籤。
        /// </summary>
        private object CreateDependentViewMatchlines(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType primaryViewIdValue = parameters["primaryViewId"]?.Value<IdType>() ?? 0;
            string lineStyleName = parameters["lineStyleName"]?.Value<string>() ?? "粗虛線";
            string textStyleName = parameters["textStyleName"]?.Value<string>() ?? "微軟正黑體 3.5 mm";

            View primaryView = null;
            if (primaryViewIdValue > 0)
            {
                primaryView = doc.GetElement(new ElementId(primaryViewIdValue)) as View;
            }
            else
            {
                primaryView = _uiApp.ActiveUIDocument.ActiveView;
            }

            if (primaryView == null) throw new Exception("找不到指定的母視圖 (Primary View)。");

            // 取得叢屬視圖
            var dependentViewIds = primaryView.GetDependentViewIds();
            if (dependentViewIds.Count == 0)
            {
                return new { Success = false, Message = "該視圖沒有任何叢屬視圖 (Dependent Views)。" };
            }

            List<View> dependentViews = dependentViewIds
                .Select(id => doc.GetElement(id) as View)
                .Where(view => view != null)
                .ToList();
            if (dependentViews.Count == 0)
            {
                return new { Success = false, Message = "找不到可用的叢屬視圖 (Dependent Views)。" };
            }

            // 尋找舊的銜接線：母視圖與所有從屬視圖都要掃描。
            // 舊版本曾在錯誤視圖建立文字，只掃母視圖會讓那些文字永遠殘留。
            var oldLineIds = new HashSet<ElementId>();
            var oldTextIds = new HashSet<ElementId>();
            var cleanupViews = new List<View> { primaryView };
            cleanupViews.AddRange(dependentViews.Where(view => view.Id != primaryView.Id));

            foreach (View cleanupView in cleanupViews)
            {
                var viewLines = new FilteredElementCollector(doc, cleanupView.Id)
                    .OfCategory(BuiltInCategory.OST_Lines)
                    .WhereElementIsNotElementType()
                    .Cast<CurveElement>();

                foreach (CurveElement element in viewLines)
                {
                    GraphicsStyle style = element.LineStyle as GraphicsStyle;
                    if (style != null && style.Name.Contains(lineStyleName))
                    {
                        oldLineIds.Add(element.Id);
                    }
                }

                var viewTexts = new FilteredElementCollector(doc, cleanupView.Id)
                    .OfClass(typeof(TextNote))
                    .Cast<TextNote>();

                foreach (TextNote element in viewTexts)
                {
                    if (!string.IsNullOrEmpty(element.Text) && element.Text.Contains("銜接線"))
                    {
                        oldTextIds.Add(element.Id);
                    }
                }
            }

            List<ElementId> oldLines = oldLineIds.ToList();
            List<ElementId> oldTexts = oldTextIds.ToList();

            // 取得樣式；所有必要型式先在交易外驗證，避免失敗時先刪除舊標註。
            GraphicsStyle lineStyle = new FilteredElementCollector(doc)
                .OfClass(typeof(GraphicsStyle))
                .Cast<GraphicsStyle>()
                .FirstOrDefault(s => s.Name.Contains(lineStyleName));

            TextNoteType textType = FindMatchlineTextNoteType(doc, textStyleName);
            if (textType == null)
            {
                throw new Exception("模型中找不到可用的文字型式 (TextNoteType)，且無法取得 Revit 預設文字型式。請先在專案中建立一個文字註記型式後重試。");
            }

            BoundingBoxXYZ primaryCropBox = primaryView.CropBox;
            if (primaryCropBox == null || primaryCropBox.Transform == null)
            {
                throw new Exception("母視圖沒有可用的 CropBox，無法計算銜接線位置。");
            }

            var viewData = new List<DependentViewData>();
            Transform primaryTransform = primaryCropBox.Transform;
            Transform primaryInverse = primaryTransform.Inverse;
            foreach (View dv in dependentViews)
            {
                BoundingBoxXYZ bbox = dv.CropBox;
                string sheetNum = GetSheetNumber(doc, dv.Id);
                // 若無圖紙，則用視圖名稱
                string label = string.IsNullOrEmpty(sheetNum) ? dv.Name : sheetNum;

                DependentViewData normalizedView;
                string normalizationError;
                if (!TryNormalizeDependentCropBox(
                    dv, bbox, label, primaryInverse,
                    out normalizedView, out normalizationError))
                {
                    return new
                    {
                        Success = false,
                        DeletedLines = 0,
                        DeletedTexts = 0,
                        CreatedMatchlines = 0,
                        Message = normalizationError
                    };
                }

                viewData.Add(normalizedView);
            }

            if (viewData.Count < 2)
            {
                return new { Success = false, Message = "可用的從屬視圖不足兩個，沒有可計算的銜接邊界。" };
            }

            // 先把四邊候選切成原子區段，再要求相對兩側互相選中最近鄰。
            // 這會排除對角重疊與跨過中間視圖的配對，也能保留 T 形和一對多邊界。
            double shortCurveTolerance = Math.Max(
                doc.Application.ShortCurveTolerance, 1e-6);
            List<MatchlineSideClaim> sideClaims = BuildMatchlineSideClaims(
                viewData, 0.5, shortCurveTolerance);
            List<MatchlineCandidate> adjacentCandidates = BuildMutualMatchlineCandidates(
                sideClaims, primaryTransform, shortCurveTolerance)
                .OrderBy(item => item.PairKey)
                .ThenBy(item => item.MinAlong)
                .ThenBy(item => item.MaxAlong)
                .ThenBy(item => item.View1.SheetLabel)
                .ThenBy(item => item.View2.SheetLabel)
                .ToList();

            if (adjacentCandidates.Count == 0)
            {
                return new
                {
                    Success = false,
                    DeletedLines = 0,
                    DeletedTexts = 0,
                    CreatedMatchlines = 0,
                    Message = "找不到可用的 CropBox 重疊帶或相鄰邊界；已保留既有銜接線，未刪除任何標註。"
                };
            }

            using (Transaction trans = new Transaction(doc, "建立叢屬視圖銜接線"))
            {
                trans.Start();

                // 刪除舊線與舊字
                foreach (var id in oldLines) doc.Delete(id);
                foreach (var id in oldTexts) doc.Delete(id);

                List<MatchlineResult> results = new List<MatchlineResult>();

                TextNoteOptions opts = new TextNoteOptions { TypeId = textType.Id };
                opts.HorizontalAlignment = HorizontalTextAlignment.Center;
                opts.VerticalAlignment = VerticalTextAlignment.Middle;

                foreach (MatchlineCandidate candidate in adjacentCandidates)
                {
                    // 繪製線條
                    DetailCurve dc = doc.Create.NewDetailCurve(primaryView, candidate.Line);
                    if (lineStyle != null) dc.LineStyle = lineStyle;
                    SetComment(dc, "MATCHLINE_AUTO");

                    // 每一組真正相鄰的視圖都固定建立兩側名稱，不再省略文字。
                    TextNote tn1 = TextNote.Create(doc, primaryView.Id, candidate.TextPos1,
                        $"銜接線 {candidate.View1.SheetLabel}", opts);
                    SetComment(tn1, "MATCHLINE_AUTO");

                    TextNote tn2 = TextNote.Create(doc, primaryView.Id, candidate.TextPos2,
                        $"銜接線 {candidate.View2.SheetLabel}", opts);
                    SetComment(tn2, "MATCHLINE_AUTO");

                    if (candidate.IsVertical)
                    {
                        // 垂直線時，文字需要旋轉 90 度與線條平行
                        Line axis1 = Line.CreateBound(candidate.TextPos1, candidate.TextPos1 + XYZ.BasisZ);
                        Line axis2 = Line.CreateBound(candidate.TextPos2, candidate.TextPos2 + XYZ.BasisZ);
                        ElementTransformUtils.RotateElement(doc, tn1.Id, axis1, Math.PI / 2);
                        ElementTransformUtils.RotateElement(doc, tn2.Id, axis2, Math.PI / 2);
                    }

                    results.Add(new MatchlineResult
                    {
                        View1 = candidate.View1.SheetLabel,
                        View2 = candidate.View2.SheetLabel
                    });
                }

                trans.Commit();

                return new
                {
                    Success = true,
                    DeletedLines = oldLines.Count,
                    DeletedTexts = oldTexts.Count,
                    CreatedMatchlines = results.Count,
                    CreatedTexts = results.Count * 2,
                    SuppressedTextMatchlines = 0,
                    SuppressedCrowdedTextMatchlines = 0,
                    SuppressedGridTextMatchlines = 0,
                    Details = results,
                    Message = $"成功清理了 {oldLines.Count} 條舊線與 {oldTexts.Count} 組文字，並為 {results.Count} 組相鄰視圖建立銜接線與 {results.Count * 2} 組兩側文字。"
                };
            }
        }


        /// <summary>
        /// Resolve the requested text type without assuming that the class
        /// collector is the only way to reach Revit's document default.
        /// </summary>
        private TextNoteType FindMatchlineTextNoteType(Document doc, string requestedName)
        {
            List<TextNoteType> textTypes = new FilteredElementCollector(doc)
                .OfClass(typeof(TextNoteType))
                .Cast<TextNoteType>()
                .ToList();

            if (!string.IsNullOrWhiteSpace(requestedName))
            {
                TextNoteType requested = textTypes.FirstOrDefault(st =>
                    !string.IsNullOrEmpty(st.Name) && st.Name.Contains(requestedName));
                if (requested != null) return requested;
            }

            try
            {
                ElementId defaultId = doc.GetDefaultElementTypeId(ElementTypeGroup.TextNoteType);
                if (defaultId != null && defaultId != ElementId.InvalidElementId)
                {
                    TextNoteType defaultType = doc.GetElement(defaultId) as TextNoteType;
                    if (defaultType != null) return defaultType;
                }
            }
            catch
            {
                // Fall through to the first collected type for older models.
            }

            return textTypes.FirstOrDefault();
        }

        private object DetectSheetMatchlines(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            var sheetNumbers = parameters["sheetNumbers"]?.ToObject<List<string>>() ?? new List<string>();
            string lineStyleName = parameters["lineStyleName"]?.Value<string>() ?? "粗虛線";

            if (sheetNumbers.Count == 0)
                throw new Exception("請指定要偵測的圖紙編號 (sheetNumbers)。");

            var sheets = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .Where(s => sheetNumbers.Contains(s.SheetNumber))
                .ToList();

            if (sheets.Count == 0)
                throw new Exception($"找不到指定圖紙: {string.Join(",", sheetNumbers)}");

            var sheetResults = new List<object>();

            // === 追蹤已處理的元素 ID，避免在同一張圖紙內重複計數 ===
            var processedElementIds = new HashSet<ElementId>();

            foreach (var sheet in sheets)
            {
                processedElementIds.Clear(); 
                var placedViews = new List<object>();
                var allLineMatches = new List<object>();
                var allTextMatches = new List<object>();

                foreach (ElementId vpId in sheet.GetAllViewports())
                {
                    Viewport vp = doc.GetElement(vpId) as Viewport;
                    if (vp == null) continue;
                    View view = doc.GetElement(vp.ViewId) as View;
                    if (view == null) continue;

                    // 找出母視圖 (Primary View)
                    ElementId primaryViewId = view.GetPrimaryViewId();
                    bool isDependentView = primaryViewId != null && primaryViewId != ElementId.InvalidElementId;
                    View primaryView = isDependentView ? doc.GetElement(primaryViewId) as View : null;

                    placedViews.Add(new
                    {
                        ViewId = view.Id.GetIdValue(),
                        ViewName = view.Name,
                        ViewType = view.ViewType.ToString(),
                        ViewSheetLabel = GetSheetNumber(doc, view.Id),
                        IsDependentView = isDependentView,
                        PrimaryViewId = isDependentView ? (object)primaryViewId.GetIdValue() : null,
                        PrimaryViewName = primaryView?.Name
                    });

                    // --- 掃描邏輯策略 ---
                    // 為了確保 100% 偵測到所有標註（無論標註是直接畫在從屬視圖，還是定義在母視圖）：
                    // 1. 我們同時掃描視圖本身與母視圖（若存在）。
                    // 2. 利用 processedElementIds (ElementId HashSet) 在同一張圖紙範圍內進行全域去重。
                    //    這能解決「掃描母視圖看到 A 線，掃描從屬視圖又看到 A 線」造成的重複計數問題。

                    // A. 掃描視圖本身
                    ScanViewAndDeduplicate(doc, view, lineStyleName, "View", processedElementIds, allLineMatches, allTextMatches);

                    // B. 若為從屬視圖，額外掃描母視圖
                    if (isDependentView && primaryView != null)
                    {
                        ScanViewAndDeduplicate(doc, primaryView, lineStyleName, "PrimaryView", processedElementIds, allLineMatches, allTextMatches);
                    }
                }




                // --- 掃描 3: 圖紙本身標記 (Sheet space) ---
                var pageElements = new FilteredElementCollector(doc, sheet.Id)
                    .WhereElementIsNotElementType();

                var sheetLineMatches = pageElements.OfClass(typeof(CurveElement))
                    .Cast<CurveElement>()
                    .Where(e => e.LineStyle != null && !string.IsNullOrEmpty(e.LineStyle.Name) && e.LineStyle.Name.Contains(lineStyleName))
                    .Select(e => new
                    {
                        ElementId = e.Id.GetIdValue(),
                        Source = "Sheet",
                        ViewId = (object)null,
                        ViewName = (string)null,
                        Type = "Line",
                        StyleName = e.LineStyle.Name
                    }).ToList();

                var sheetTextMatches = pageElements.OfClass(typeof(TextNote))
                    .Cast<TextNote>()
                    .Where(t => !string.IsNullOrEmpty(t.Text) && t.Text.Contains("銜接線"))
                    .Select(t => new
                    {
                        ElementId = t.Id.GetIdValue(),
                        Source = "Sheet",
                        ViewId = (object)null,
                        ViewName = (string)null,
                        Type = "Text",
                        Text = t.Text
                    }).ToList();

                allLineMatches.AddRange(sheetLineMatches.Cast<object>());
                allTextMatches.AddRange(sheetTextMatches.Cast<object>());

                sheetResults.Add(new
                {
                    SheetNumber = sheet.SheetNumber,
                    SheetName = sheet.Name,
                    PlacedViews = placedViews,
                    LineMatches = allLineMatches,
                    TextMatches = allTextMatches,
                    PlacedViewportCount = placedViews.Count,
                    DetectedMatchlineCount = allLineMatches.Count + allTextMatches.Count
                });
            }

            return new
            {
                Success = true,
                Sheets = sheetResults
            };
        }

        /// <summary>
        /// 掃描指定視圖內的銜接線與銜接文字，結果直接 AddRange 至傳入的列表中。
        /// </summary>
        private void ScanViewAndDeduplicate(Document doc, View view, string lineStyleName, string source,
            HashSet<ElementId> processedIds, List<object> lineMatches, List<object> textMatches)
        {
            var viewElements = new FilteredElementCollector(doc, view.Id)
                .WhereElementIsNotElementType();

            var curveElements = viewElements.OfClass(typeof(CurveElement))
                .Cast<CurveElement>()
                .Where(e => e.LineStyle != null && !string.IsNullOrEmpty(e.LineStyle.Name) && e.LineStyle.Name.Contains(lineStyleName))
                .ToList();

            foreach (var e in curveElements)
            {
                if (processedIds.Add(e.Id))
                {
                    lineMatches.Add(new
                    {
                        ElementId = e.Id.GetIdValue(),
                        Source = source,
                        ViewId = view.Id.GetIdValue(),
                        ViewName = view.Name,
                        Type = "Line",
                        StyleName = e.LineStyle.Name
                    });
                }
            }

            var textElements = new FilteredElementCollector(doc, view.Id)
                .OfClass(typeof(TextNote))
                .Cast<TextNote>()
                .Where(t => !string.IsNullOrEmpty(t.Text) && t.Text.Contains("銜接線"))
                .ToList();

            foreach (var t in textElements)
            {
                if (processedIds.Add(t.Id))
                {
                    textMatches.Add(new
                    {
                        ElementId = t.Id.GetIdValue(),
                        Source = source,
                        ViewId = view.Id.GetIdValue(),
                        ViewName = view.Name,
                        Type = "Text",
                        Text = t.Text
                    });
                }
            }
        }

        private string GetElementComment(Element element)
        {
            Parameter p = element.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);
            if (p != null && p.HasValue)
            {
                return p.AsString();
            }
            return null;
        }

        private string GetSheetNumber(Document doc, ElementId viewId)
        {
            var viewports = new FilteredElementCollector(doc)
                .OfClass(typeof(Viewport))
                .Cast<Viewport>()
                .Where(v => v.ViewId == viewId)
                .ToList();

            if (viewports.Count > 0)
            {
                ElementId sheetId = viewports.First().SheetId;
                ViewSheet sheet = doc.GetElement(sheetId) as ViewSheet;
                if (sheet != null) return sheet.SheetNumber;
            }
            return "";
        }

        private void SetComment(Element el, string comment)
        {
            Parameter p = el.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);
            if (p != null && !p.IsReadOnly)
            {
                p.Set(comment);
            }
        }

        private object GetLineStyles(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            var styles = new FilteredElementCollector(doc)
                .OfClass(typeof(GraphicsStyle))
                .Cast<GraphicsStyle>()
                .Select(s => new { Id = s.Id.GetIdValue(), Name = s.Name })
                .ToList();

            return new { Count = styles.Count, Styles = styles };
        }
    }
}
