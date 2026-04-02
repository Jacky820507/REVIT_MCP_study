using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Newtonsoft.Json.Linq;

namespace RevitMCP.Core
{
    public partial class CommandExecutor
    {
        /// <summary>
        /// 將選定的填滿範圍從製圖樣式轉換為模型樣式
        /// </summary>
        private object ConvertDraftingToModelPattern()
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            UIDocument uidoc = _uiApp.ActiveUIDocument;
            var selectedIds = uidoc.Selection.GetElementIds();
            
            if (selectedIds.Count == 0)
            {
                throw new Exception("請先選取要轉換的填滿範圍 (Filled Region)。");
            }

            int viewScale = doc.ActiveView.Scale;
            int convertedCount = 0;
            var convertedIds = new List<long>();

            using (Transaction t = new Transaction(doc, "轉換為模型樣式"))
            {
                t.Start();
                try
                {
                    foreach (ElementId id in selectedIds)
                    {
                        Element elem = doc.GetElement(id);
                        if (!(elem is FilledRegion filledRegion)) 
                        {
                            Logger.Info($"跳過非填滿範圍元素: {id}");
                            continue;
                        }
                        
                        Logger.Info($"正在處理填滿範圍: {id}");
                        FilledRegionType oldType = doc.GetElement(filledRegion.GetTypeId()) as FilledRegionType;
                        
                        if (oldType == null)
                        {
                            Logger.Error($"找不到填滿範圍類型: {filledRegion.GetTypeId()}");
                            continue;
                        }

                        // Revit 2018+ 優先使用 ForegroundPatternId
                        ElementId patId = oldType.ForegroundPatternId;
                        if (patId == ElementId.InvalidElementId)
                        {
                            Logger.Info($"類型 {oldType.Name} 沒有前景樣式，跳過。");
                            continue;
                        }

                        FillPatternElement oldPatElem = doc.GetElement(patId) as FillPatternElement;
                        if (oldPatElem == null)
                        {
                            Logger.Error($"找不到樣式元素: {patId}");
                            continue;
                        }

                        FillPattern oldFp = oldPatElem.GetFillPattern();
                        if (oldFp == null)
                        {
                            Logger.Error($"樣式元素 {patId} 沒有有效的 FillPattern");
                            continue;
                        }

                        if (oldFp.Target == FillPatternTarget.Model)
                        {
                            Logger.Info($"樣式 {oldFp.Name} 已經是模型樣式，跳過。");
                            continue;
                        }

                        // 1. 處理樣式放大
                        FillPatternElement newPatElem = GetOrCreateScaledModelPattern(doc, oldPatElem, viewScale);
                        if (newPatElem == null) continue;

                        // 2. 處理類型複製
                        string newTypeName = $"{oldType.Name} - 模型 (1_{viewScale})";
                        FilledRegionType newType = new FilteredElementCollector(doc)
                            .OfClass(typeof(FilledRegionType))
                            .Cast<FilledRegionType>()
                            .FirstOrDefault(x => x.Name == newTypeName);

                        if (newType == null)
                        {
                            newType = oldType.Duplicate(newTypeName) as FilledRegionType;
                            newType.ForegroundPatternId = newPatElem.Id;
                        }

                        // 3. 原地替換
                        filledRegion.ChangeTypeId(newType.Id);
                        convertedCount++;
                        convertedIds.Add(id.GetIdValue());
                        Logger.Info($"成功轉換: {id} -> {newType.Name}");
                    }
                    t.Commit();
                }
                catch (Exception ex)
                {
                    Logger.Error("轉換過程中發生未預期錯誤", ex);
                    if (t.HasStarted()) t.RollBack();
                    throw;
                }
            }

            return new
            {
                Message = $"已成功將 {convertedCount} 個填滿範圍轉換為符合當前比例縮放的模型樣式。",
                ConvertedCount = convertedCount,
                ConvertedIds = convertedIds
            };
        }

        /// <summary>
        /// 自動掃描並將所有被旋轉（在圖紙上）的剖面圖內的製圖樣式轉換為模型樣式
        /// </summary>
        private object AutoConvertRotatedViewportPatterns()
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            int totalConvertedCount = 0;
            int skippedGroupCount = 0;
            var processedViewIds = new HashSet<ElementId>();
            var convertedIds = new List<long>();

            // 1. 取得所有視埠 (Viewports)
            var viewports = new FilteredElementCollector(doc)
                .OfClass(typeof(Viewport))
                .Cast<Viewport>()
                .ToList();

            using (Transaction t = new Transaction(doc, "自動轉換旋轉剖面圖填滿樣式"))
            {
                t.Start();
                try
                {
                    foreach (var vp in viewports)
                    {
                        Parameter rotParam = vp.get_Parameter(BuiltInParameter.VIEWPORT_ATTR_ORIENTATION_ON_SHEET);
                        bool isRotated = vp.Rotation != ViewportRotation.None;
                        if (!isRotated && rotParam != null && rotParam.AsInteger() != 0)
                        {
                            isRotated = true;
                        }

                        // 檢查是否在圖紙上有旋轉
                        if (!isRotated) 
                            continue;

                        ElementId viewId = vp.ViewId;
                        
                        // 避免重複處理同一個視圖
                        if (processedViewIds.Contains(viewId)) 
                            continue;
                            
                        processedViewIds.Add(viewId);

                        View view = doc.GetElement(viewId) as View;
                        if (view == null) 
                            continue;

                        // 依需求：僅針對「剖面圖 (Section)」或「詳圖 (Detail)」
                        if (view.ViewType != ViewType.Section && view.ViewType != ViewType.Detail)
                            continue;

                        int viewScale = view.Scale;

                        // 找出該視圖中所有的 FilledRegion
                        var filledRegions = new FilteredElementCollector(doc, viewId)
                            .OfClass(typeof(FilledRegion))
                            .Cast<FilledRegion>()
                            .ToList();

                        foreach (var fr in filledRegions)
                        {
                            // 根據使用者需求：略過群組內的物件，避免強制解除群組
                            if (fr.GroupId != ElementId.InvalidElementId)
                            {
                                skippedGroupCount++;
                                Logger.Info($"[Auto] 略過群組中的填滿範圍: {fr.Id} (視圖: {view.Name})");
                                continue;
                            }

                            FilledRegionType oldType = doc.GetElement(fr.GetTypeId()) as FilledRegionType;
                            if (oldType == null) continue;

                            // Revit 2018+ 優先使用 ForegroundPatternId
                            ElementId patId = oldType.ForegroundPatternId;
                            if (patId == ElementId.InvalidElementId) continue;

                            FillPatternElement oldPatElem = doc.GetElement(patId) as FillPatternElement;
                            if (oldPatElem == null) continue;

                            FillPattern oldFp = oldPatElem.GetFillPattern();
                            // 如果已經是模型樣式，就跳過
                            if (oldFp == null || oldFp.Target == FillPatternTarget.Model) continue;

                            // 自動將製圖樣式轉為模型樣式
                            FillPatternElement newPatElem = GetOrCreateScaledModelPattern(doc, oldPatElem, viewScale);
                            if (newPatElem == null) continue;

                            string newTypeName = $"{oldType.Name} - 模型 (1_{viewScale})";
                            FilledRegionType newType = new FilteredElementCollector(doc)
                                .OfClass(typeof(FilledRegionType))
                                .Cast<FilledRegionType>()
                                .FirstOrDefault(x => x.Name == newTypeName);

                            if (newType == null)
                            {
                                newType = oldType.Duplicate(newTypeName) as FilledRegionType;
                                newType.ForegroundPatternId = newPatElem.Id;
                            }

                            // 執行選取替換
                            fr.ChangeTypeId(newType.Id);
                            totalConvertedCount++;
                            convertedIds.Add(fr.Id.GetIdValue());
                        }
                    }
                    t.Commit();
                }
                catch (Exception ex)
                {
                    Logger.Error("自動轉換旋轉視埠填滿樣式時發生錯誤", ex);
                    if (t.HasStarted()) t.RollBack();
                    throw;
                }
            }

            return new
            {
                Message = $"自動掃描完成。共檢查了 {processedViewIds.Count} 個旋轉的剖面圖，成功轉換了 {totalConvertedCount} 個填滿範圍，並因群組限制而略過了 {skippedGroupCount} 個物件。",
                ProcessedViewsCount = processedViewIds.Count,
                ConvertedCount = totalConvertedCount,
                SkippedGroupCount = skippedGroupCount,
                ConvertedIds = convertedIds
            };
        }

        /// <summary>
        /// 診斷工具：回傳所有視埠的旋轉狀態與屬性，協助排除遺漏問題
        /// </summary>
        private object CheckViewportsRotation()
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            var viewports = new FilteredElementCollector(doc)
                .OfClass(typeof(Viewport))
                .Cast<Viewport>()
                .ToList();

            var results = new List<object>();

            foreach (var vp in viewports)
            {
                View view = doc.GetElement(vp.ViewId) as View;
                Parameter rotParam = vp.get_Parameter(BuiltInParameter.VIEWPORT_ATTR_ORIENTATION_ON_SHEET);
                
                results.Add(new
                {
                    ViewportId = vp.Id.GetIdValue(),
                    ViewId = vp.ViewId.GetIdValue(),
                    ViewName = view?.Name,
                    ViewType = view?.ViewType.ToString(),
                    RawRotationEnum = vp.Rotation.ToString(),
                    ParamName = rotParam?.Definition?.Name,
                    ParamValue = rotParam?.AsValueString(),
                    ParamInt = rotParam?.AsInteger()
                });
            }

            return results;
        }

        // 供上方呼叫的輔助方法：計算轉換與建立 FillPattern
        private FillPatternElement GetOrCreateScaledModelPattern(Document doc, FillPatternElement oldPatElem, int scale)
        {
            FillPattern oldFp = oldPatElem.GetFillPattern();
            string newPatName = $"{oldFp.Name} - 模型 (1_{scale})";

            FillPatternElement existing = new FilteredElementCollector(doc)
                .OfClass(typeof(FillPatternElement))
                .Cast<FillPatternElement>()
                .FirstOrDefault(x => x.Name == newPatName);

            if (existing != null) return existing;

            // 0 = ToModel / ToModelFace, 1 = ToView / ToViewFace
            FillPattern newFp = new FillPattern(newPatName, FillPatternTarget.Model, (FillPatternHostOrientation)0);
            var oldGrids = oldFp.GetFillGrids();
            var newGrids = new List<FillGrid>();

            foreach (var grid in oldGrids)
            {
                FillGrid newGrid = new FillGrid()
                {
                    Angle = grid.Angle,
                    Origin = grid.Origin,
                    // 核心：將間距與位移乘上視圖比例尺
                    Offset = grid.Offset * scale,
                    Shift = grid.Shift * scale
                };

                var segs = grid.GetSegments();
                if (segs != null && segs.Count > 0)
                {
                    newGrid.SetSegments(segs.Select(s => s * scale).ToList());
                }
                newGrids.Add(newGrid);
            }

            newFp.SetFillGrids(newGrids);
            return FillPatternElement.Create(doc, newFp);
        }
    }
}
