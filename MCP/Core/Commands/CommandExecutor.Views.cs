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
            public BoundingBoxXYZ Bbox;
            public string SheetLabel;
        }

        private class MatchlineResult
        {
            public string View1;
            public string View2;
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

            List<View> dependentViews = dependentViewIds.Select(id => doc.GetElement(id) as View).ToList();

            // 尋找舊的銜接線：根據樣式名稱進行過濾 (因為 2020 版本的線條不一定支援 Comments 屬性)
            var oldLines = new FilteredElementCollector(doc, primaryView.Id)
                .OfCategory(BuiltInCategory.OST_Lines)
                .WhereElementIsNotElementType()
                .Cast<CurveElement>()
                .Where(e => {
                    var style = e.LineStyle as GraphicsStyle;
                    return style != null && style.Name.Contains(lineStyleName);
                })
                .Select(e => e.Id)
                .ToList();

            var oldTexts = new FilteredElementCollector(doc, primaryView.Id)
                .OfClass(typeof(TextNote))
                .Cast<TextNote>()
                .Where(e => !string.IsNullOrEmpty(e.Text) && e.Text.Contains("銜接線"))
                .Select(e => e.Id)
                .ToList();

            using (Transaction trans = new Transaction(doc, "建立叢屬視圖銜接線"))
            {
                trans.Start();

                // 刪除舊線與舊字
                foreach (var id in oldLines) doc.Delete(id);
                foreach (var id in oldTexts) doc.Delete(id);

                // 取得樣式
                GraphicsStyle lineStyle = new FilteredElementCollector(doc)
                    .OfClass(typeof(GraphicsStyle))
                    .Cast<GraphicsStyle>()
                    .FirstOrDefault(s => s.Name.Contains(lineStyleName));

                TextNoteType textType = new FilteredElementCollector(doc)
                    .OfClass(typeof(TextNoteType))
                    .Cast<TextNoteType>()
                    .FirstOrDefault(t => t.Name.Contains(textStyleName)) 
                    ?? new FilteredElementCollector(doc).OfClass(typeof(TextNoteType)).Cast<TextNoteType>().FirstOrDefault();

                var viewData = new List<DependentViewData>();
                foreach (var dv in dependentViews)
                {
                    BoundingBoxXYZ bbox = dv.CropBox;
                    string sheetNum = GetSheetNumber(doc, dv.Id);
                    // 若無圖紙，則用視圖名稱
                    string label = string.IsNullOrEmpty(sheetNum) ? dv.Name : sheetNum;
                    viewData.Add(new DependentViewData { View = dv, Bbox = bbox, SheetLabel = label });
                }

                Transform t = primaryView.CropBox.Transform;
                List<MatchlineResult> results = new List<MatchlineResult>();

                for (int i = 0; i < viewData.Count; i++)
                {
                    for (int j = i + 1; j < viewData.Count; j++)
                    {
                        var v1 = viewData[i];
                        var v2 = viewData[j];

                        // 判斷重疊
                        double minX = Math.Max(v1.Bbox.Min.X, v2.Bbox.Min.X);
                        double maxX = Math.Min(v1.Bbox.Max.X, v2.Bbox.Max.X);
                        double minY = Math.Max(v1.Bbox.Min.Y, v2.Bbox.Min.Y);
                        double maxY = Math.Min(v1.Bbox.Max.Y, v2.Bbox.Max.Y);

                        double tol = 0.5; // 重疊容差 (feet)

                        if (maxX >= minX - tol && maxY >= minY - tol)
                        {
                            double dx = maxX - minX;
                            double dy = maxY - minY;

                            Line matchLine = null;
                            XYZ lineNormal = null;
                            XYZ textPos1 = null;
                            XYZ textPos2 = null;
                            bool isVertical = false;

                            // 調整偏移量 (feet)：從 1.5 稍微縮減到 1.2 讓文字靠近一點
                            double finalOffset = 1.2;

                            if (dx > dy)
                            {
                                // 水平銜接線
                                double midY = (minY + maxY) / 2;
                                XYZ p1 = t.OfPoint(new XYZ(minX, midY, 0));
                                XYZ p2 = t.OfPoint(new XYZ(maxX, midY, 0));

                                if (p1.DistanceTo(p2) > 1.0)
                                {
                                    matchLine = Line.CreateBound(p1, p2);
                                    lineNormal = t.BasisY;

                                    double v1cY = (v1.Bbox.Min.Y + v1.Bbox.Max.Y) / 2;
                                    double v2cY = (v2.Bbox.Min.Y + v2.Bbox.Max.Y) / 2;
                                    XYZ midPt = p1.Add(p2).Divide(2);

                                    if (v1cY > v2cY)
                                    {
                                        textPos1 = midPt.Add(lineNormal.Multiply(finalOffset));
                                        textPos2 = midPt.Add(lineNormal.Multiply(-finalOffset));
                                    }
                                    else
                                    {
                                        textPos1 = midPt.Add(lineNormal.Multiply(-finalOffset));
                                        textPos2 = midPt.Add(lineNormal.Multiply(finalOffset));
                                    }
                                }
                            }
                            else
                            {
                                // 垂直銜接線
                                isVertical = true;
                                double midX = (minX + maxX) / 2;
                                XYZ p1 = t.OfPoint(new XYZ(midX, minY, 0));
                                XYZ p2 = t.OfPoint(new XYZ(midX, maxY, 0));

                                if (p1.DistanceTo(p2) > 1.0)
                                {
                                    matchLine = Line.CreateBound(p1, p2);
                                    lineNormal = t.BasisX;

                                    double v1cX = (v1.Bbox.Min.X + v1.Bbox.Max.X) / 2;
                                    double v2cX = (v2.Bbox.Min.X + v2.Bbox.Max.X) / 2;
                                    XYZ midPt = p1.Add(p2).Divide(2);

                                    if (v1cX > v2cX)
                                    {
                                        textPos1 = midPt.Add(lineNormal.Multiply(finalOffset));
                                        textPos2 = midPt.Add(lineNormal.Multiply(-finalOffset));
                                    }
                                    else
                                    {
                                        textPos1 = midPt.Add(lineNormal.Multiply(-finalOffset));
                                        textPos2 = midPt.Add(lineNormal.Multiply(finalOffset));
                                    }
                                }
                            }

                            if (matchLine != null)
                            {
                                // 繪製線條
                                DetailCurve dc = doc.Create.NewDetailCurve(primaryView, matchLine);
                                if (lineStyle != null) dc.LineStyle = lineStyle;
                                SetComment(dc, "MATCHLINE_AUTO");

                                // 繪製文字
                                if (textType != null)
                                {
                                    TextNoteOptions opts = new TextNoteOptions { TypeId = textType.Id };
                                    opts.HorizontalAlignment = HorizontalTextAlignment.Center;
                                    opts.VerticalAlignment = VerticalTextAlignment.Middle;
                                    
                                    TextNote tn1 = TextNote.Create(doc, primaryView.Id, textPos1, $"銜接線 {v1.SheetLabel}", opts);
                                    SetComment(tn1, "MATCHLINE_AUTO");
                                    
                                    TextNote tn2 = TextNote.Create(doc, primaryView.Id, textPos2, $"銜接線 {v2.SheetLabel}", opts);
                                    SetComment(tn2, "MATCHLINE_AUTO");

                                    if (isVertical)
                                    {
                                        // 垂直線時，文字需要旋轉 90 度與線條平行
                                        Line axis1 = Line.CreateBound(textPos1, textPos1 + XYZ.BasisZ);
                                        Line axis2 = Line.CreateBound(textPos2, textPos2 + XYZ.BasisZ);
                                        ElementTransformUtils.RotateElement(doc, tn1.Id, axis1, Math.PI / 2);
                                        ElementTransformUtils.RotateElement(doc, tn2.Id, axis2, Math.PI / 2);
                                    }
                                }

                                results.Add(new MatchlineResult { View1 = v1.SheetLabel, View2 = v2.SheetLabel });
                            }
                        }
                    }
                }

                trans.Commit();

                return new
                {
                    Success = true,
                    DeletedLines = oldLines.Count,
                    DeletedTexts = oldTexts.Count,
                    CreatedMatchlines = results.Count,
                    Details = results,
                    Message = $"成功清理了 {oldLines.Count} 條舊線與 {oldTexts.Count} 組文字，並繪製了 {results.Count} 條新切圖線。"
                };
            }
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
