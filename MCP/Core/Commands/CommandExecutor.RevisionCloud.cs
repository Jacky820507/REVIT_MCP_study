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
        #region 修訂雲形／釋疑管理

        /// <summary>
        /// 掃描全模型修訂雲形，回傳定位與修訂資訊；writeBack=true 時同步寫入 Mark（釋疑編號）與 Comments（定位字串）。
        /// </summary>
        private object ScanRevisionClouds(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            bool writeBack = parameters["writeBack"]?.Value<bool>() ?? false;
            string markPrefix = parameters["markPrefix"]?.Value<string>();
            if (string.IsNullOrEmpty(markPrefix)) markPrefix = "釋疑";

            List<RevisionCloudEntry> entries = CollectRevisionCloudEntries(doc);

            if (writeBack)
            {
                using (Transaction trans = new Transaction(doc, "寫入釋疑編號"))
                {
                    trans.Start();
                    AssignRevisionCloudMarks(entries, markPrefix);
                    trans.Commit();
                }
            }

            var clouds = entries.Select(e => new
            {
                ElementId = e.CloudId,
                Mark = e.Mark,
                RevisionSequence = e.RevisionSequence,
                RevisionDescription = e.RevisionDescription,
                RevisionDate = e.RevisionDate,
                ViewId = e.ViewId,
                ViewName = e.ViewName,
                ViewType = e.ViewType,
                SheetNumber = e.SheetNumber,
                SheetName = e.SheetName,
                Comments = e.Comments
            }).ToList();

            return new
            {
                Count = clouds.Count,
                Clouds = clouds
            };
        }

        /// <summary>
        /// 為尚未上圖紙、但已有修訂雲形的視圖建立圖紙並加入視埠。dryRun=true 只回傳計畫，不開 Transaction。
        /// </summary>
        private object AddCloudViewsToSheets(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType? titleBlockIdParam = parameters["titleBlockId"]?.Value<IdType>();
            string sheetNumberPrefix = parameters["sheetNumberPrefix"]?.Value<string>();
            if (string.IsNullOrEmpty(sheetNumberPrefix)) sheetNumberPrefix = "RQ-";
            int startNumber = parameters["startNumber"]?.Value<int>() ?? 1;
            bool dryRun = parameters["dryRun"]?.Value<bool>() ?? false;

            FamilySymbol titleBlockType;
            if (titleBlockIdParam.HasValue && titleBlockIdParam.Value > 0)
            {
                titleBlockType = doc.GetElement(titleBlockIdParam.Value.ToElementId()) as FamilySymbol;
                if (titleBlockType == null)
                    throw new Exception($"找不到圖框類型 ID: {titleBlockIdParam.Value}");
            }
            else
            {
                titleBlockType = new FilteredElementCollector(doc)
                    .OfClass(typeof(FamilySymbol))
                    .OfCategory(BuiltInCategory.OST_TitleBlocks)
                    .Cast<FamilySymbol>()
                    .FirstOrDefault();
                if (titleBlockType == null)
                    throw new Exception("專案中沒有可用的圖框類型，請提供 titleBlockId");
            }

            List<RevisionCloudEntry> entries = CollectRevisionCloudEntries(doc);

            // 依 OwnerView 分組，排除雲形直接畫在圖紙上的特例（沒有「視圖」可搬上圖紙）
            var viewGroups = entries
                .Where(e => e.ViewType != "Sheet" && e.ViewId > 0)
                .GroupBy(e => e.ViewId)
                .ToList();

            HashSet<string> usedSheetNumbers = new HashSet<string>(
                new FilteredElementCollector(doc).OfClass(typeof(ViewSheet)).Cast<ViewSheet>().Select(s => s.SheetNumber),
                StringComparer.Ordinal);

            // Viewport.CanAddViewToSheet 需要一個「已存在」的圖紙 ElementId 作探測對象。
            // 借用專案內任一既有圖紙探測；專案目前一張圖紙都沒有時，先建立第一張再補做驗證（失敗就刪除，避免留下用不到的空圖紙）。
            ElementId probeSheetId = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<Element>()
                .FirstOrDefault()?.Id;

            var created = new List<object>();
            var skipped = new List<object>();
            int counter = startNumber;

            using (Transaction trans = dryRun ? null : new Transaction(doc, "建立釋疑視圖圖紙"))
            {
                trans?.Start();

                foreach (var group in viewGroups)
                {
                    IdType viewId = group.Key;
                    string viewName = group.First().ViewName ?? $"View {viewId}";
                    string existingSheetNumber = group.First().SheetNumber;

                    try
                    {
                        View view = doc.GetElement(viewId.ToElementId()) as View;
                        if (view == null)
                        {
                            skipped.Add(new { ViewId = viewId, ViewName = viewName, Reason = "找不到來源視圖" });
                            continue;
                        }

                        if (!string.IsNullOrEmpty(existingSheetNumber))
                        {
                            skipped.Add(new { ViewId = viewId, ViewName = viewName, Reason = $"已在圖紙 {existingSheetNumber} 上" });
                            continue;
                        }

                        bool needsPostCreateCheck = probeSheetId == null;
                        if (!needsPostCreateCheck && !Viewport.CanAddViewToSheet(doc, probeSheetId, view.Id))
                        {
                            skipped.Add(new { ViewId = viewId, ViewName = viewName, Reason = "CanAddViewToSheet 不通過" });
                            continue;
                        }

                        while (usedSheetNumbers.Contains(sheetNumberPrefix + counter))
                            counter++;
                        string candidateNumber = sheetNumberPrefix + counter;

                        if (dryRun)
                        {
                            usedSheetNumbers.Add(candidateNumber);
                            counter++;
                            created.Add(new
                            {
                                ViewId = viewId,
                                ViewName = viewName,
                                SheetNumber = candidateNumber,
                                SheetName = viewName
                            });
                            continue;
                        }

                        ViewSheet newSheet = ViewSheet.Create(doc, titleBlockType.Id);
                        newSheet.SheetNumber = candidateNumber;
                        newSheet.Name = viewName;
                        usedSheetNumbers.Add(candidateNumber);
                        counter++;

                        if (needsPostCreateCheck)
                        {
                            if (!Viewport.CanAddViewToSheet(doc, newSheet.Id, view.Id))
                            {
                                doc.Delete(newSheet.Id);
                                skipped.Add(new { ViewId = viewId, ViewName = viewName, Reason = "CanAddViewToSheet 不通過" });
                                continue;
                            }
                            probeSheetId = newSheet.Id;
                        }

                        BoundingBoxUV outline = newSheet.Outline;
                        XYZ center = new XYZ(
                            (outline.Min.U + outline.Max.U) / 2.0,
                            (outline.Min.V + outline.Max.V) / 2.0,
                            0);
                        Viewport viewport = Viewport.Create(doc, newSheet.Id, view.Id, center);

                        created.Add(new
                        {
                            ViewId = viewId,
                            ViewName = viewName,
                            SheetId = newSheet.Id.GetIdValue(),
                            SheetNumber = newSheet.SheetNumber,
                            SheetName = newSheet.Name,
                            ViewportId = viewport.Id.GetIdValue()
                        });
                    }
                    catch (Exception ex)
                    {
                        skipped.Add(new { ViewId = viewId, ViewName = viewName, Reason = ex.Message });
                    }
                }

                trans?.Commit();
            }

            return new
            {
                TitleBlockUsed = new
                {
                    ElementId = titleBlockType.Id.GetIdValue(),
                    Name = titleBlockType.Name,
                    FamilyName = titleBlockType.FamilyName
                },
                DryRun = dryRun,
                Created = created,
                Skipped = skipped
            };
        }

        /// <summary>
        /// 匯出釋疑清單 Excel（單一工作表），供其他單位填寫回覆。
        /// </summary>
        private object ExportRevisionExcel(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            string outputPath = parameters["outputPath"]?.Value<string>();

            if (string.IsNullOrEmpty(outputPath))
            {
                string projectPath = doc.PathName;
                string projectDir = string.IsNullOrEmpty(projectPath)
                    ? Environment.GetFolderPath(Environment.SpecialFolder.Desktop)
                    : System.IO.Path.GetDirectoryName(projectPath);
                outputPath = System.IO.Path.Combine(projectDir, $"釋疑清單_{DateTime.Now:yyyyMMdd_HHmmss}.xlsx");
            }

            List<RevisionCloudEntry> entries = CollectRevisionCloudEntries(doc);

            using (var wb = new ClosedXML.Excel.XLWorkbook())
            {
                var headerBg = ClosedXML.Excel.XLColor.FromHtml("#4472C4");
                var headerFg = ClosedXML.Excel.XLColor.White;

                var ws = wb.Worksheets.Add("釋疑清單");
                string[] headers = { "釋疑編號", "修訂序號", "修訂說明", "修訂日期", "所在視圖", "視圖類型", "圖紙編號", "圖紙名稱", "元素ID", "回覆", "回覆人", "回覆日期" };
                for (int c = 0; c < headers.Length; c++)
                {
                    ws.Cell(1, c + 1).Value = headers[c];
                    ws.Cell(1, c + 1).Style.Fill.SetBackgroundColor(headerBg).Font.SetFontColor(headerFg).Font.SetBold();
                }

                int r = 2;
                foreach (var e in entries)
                {
                    ws.Cell(r, 1).Value = e.Mark;
                    ws.Cell(r, 2).Value = e.RevisionSequence;
                    ws.Cell(r, 3).Value = e.RevisionDescription;
                    ws.Cell(r, 4).Value = e.RevisionDate;
                    ws.Cell(r, 5).Value = e.ViewName;
                    ws.Cell(r, 6).Value = e.ViewType;
                    ws.Cell(r, 7).Value = e.SheetNumber;
                    ws.Cell(r, 8).Value = e.SheetName;
                    ws.Cell(r, 9).Value = e.CloudId;
                    // 回覆／回覆人／回覆日期（欄 10-12）留空給外單位填寫
                    r++;
                }

                ws.Columns().AdjustToContents();
                wb.SaveAs(outputPath);
            }

            return new
            {
                FilePath = outputPath,
                Count = entries.Count,
                Success = true
            };
        }

        /// <summary>
        /// 共用收集邏輯：掃描全模型修訂雲形並讀出目前的修訂／位置／Mark／Comments 資訊。
        /// 依 (圖紙編號, 視圖名, ElementId) 排序，確保多次呼叫的結果順序可重現。
        /// </summary>
        private List<RevisionCloudEntry> CollectRevisionCloudEntries(Document doc)
        {
            Dictionary<IdType, ViewSheet> viewToSheet = BuildViewToSheetMap(doc);

            var clouds = new FilteredElementCollector(doc)
                .OfClass(typeof(RevisionCloud))
                .Cast<RevisionCloud>()
                .ToList();

            var entries = new List<RevisionCloudEntry>();

            foreach (RevisionCloud cloud in clouds)
            {
                try
                {
                    var entry = new RevisionCloudEntry
                    {
                        Cloud = cloud,
                        CloudId = cloud.Id.GetIdValue()
                    };

                    ElementId ownerViewId = cloud.OwnerViewId;
                    bool hasOwnerView = ownerViewId != null && ownerViewId != ElementId.InvalidElementId;
                    View ownerView = hasOwnerView ? doc.GetElement(ownerViewId) as View : null;

                    entry.ViewId = hasOwnerView ? ownerViewId.GetIdValue() : 0;
                    entry.ViewName = ownerView?.Name;

                    if (ownerView is ViewSheet ownerSheet)
                    {
                        // 特例：雲形直接畫在圖紙上，沒有獨立的「視圖」可搬
                        entry.ViewType = "Sheet";
                        entry.SheetNumber = ownerSheet.SheetNumber;
                        entry.SheetName = ownerSheet.Name;
                    }
                    else
                    {
                        entry.ViewType = ownerView?.ViewType.ToString();
                        if (entry.ViewId > 0 && viewToSheet.TryGetValue(entry.ViewId, out ViewSheet sheet))
                        {
                            entry.SheetNumber = sheet.SheetNumber;
                            entry.SheetName = sheet.Name;
                        }
                    }

                    try
                    {
                        ElementId revisionId = cloud.RevisionId;
                        if (revisionId != null && revisionId != ElementId.InvalidElementId)
                        {
                            Revision revision = doc.GetElement(revisionId) as Revision;
                            if (revision != null)
                            {
                                entry.RevisionSequence = revision.SequenceNumber;
                                entry.RevisionDescription = revision.Description;
                                entry.RevisionDate = revision.RevisionDate;
                            }
                        }
                    }
                    catch (Exception ex)
                    {
                        Logger.Debug($"讀取雲形 {entry.CloudId} 修訂資訊失敗: {ex.Message}");
                    }

                    try
                    {
                        entry.Mark = cloud.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)?.AsString();
                    }
                    catch (Exception ex)
                    {
                        Logger.Debug($"讀取雲形 {entry.CloudId} Mark 失敗: {ex.Message}");
                    }

                    try
                    {
                        entry.Comments = cloud.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)?.AsString();
                    }
                    catch (Exception ex)
                    {
                        Logger.Debug($"讀取雲形 {entry.CloudId} Comments 失敗: {ex.Message}");
                    }

                    entries.Add(entry);
                }
                catch (Exception ex)
                {
                    Logger.Debug($"讀取修訂雲形失敗，略過: {ex.Message}");
                }
            }

            return entries
                .OrderBy(e => e.SheetNumber ?? string.Empty, StringComparer.Ordinal)
                .ThenBy(e => e.ViewName ?? string.Empty, StringComparer.Ordinal)
                .ThenBy(e => e.CloudId)
                .ToList();
        }

        /// <summary>
        /// 建立「視圖 ID → 所在圖紙」對照表（透過 Viewport 反查），避免每朵雲形都重新掃描全部視埠。
        /// </summary>
        private Dictionary<IdType, ViewSheet> BuildViewToSheetMap(Document doc)
        {
            var map = new Dictionary<IdType, ViewSheet>();

            var viewports = new FilteredElementCollector(doc)
                .OfClass(typeof(Viewport))
                .Cast<Viewport>();

            foreach (Viewport vp in viewports)
            {
                try
                {
                    ViewSheet sheet = doc.GetElement(vp.SheetId) as ViewSheet;
                    if (sheet != null && vp.ViewId != null && vp.ViewId != ElementId.InvalidElementId)
                    {
                        map[vp.ViewId.GetIdValue()] = sheet;
                    }
                }
                catch (Exception ex)
                {
                    Logger.Debug($"建立視圖圖紙對照表失敗，略過視埠 {vp.Id.GetIdValue()}: {ex.Message}");
                }
            }

            return map;
        }

        /// <summary>
        /// 依 markPrefix 為未編號的雲形續編，已編號者保持不動；同時刷新 Comments 定位字串。
        /// </summary>
        private void AssignRevisionCloudMarks(List<RevisionCloudEntry> entries, string markPrefix)
        {
            int maxExisting = 0;
            foreach (var e in entries)
            {
                if (!string.IsNullOrEmpty(e.Mark) && e.Mark.StartsWith(markPrefix, StringComparison.Ordinal))
                {
                    string suffix = e.Mark.Substring(markPrefix.Length);
                    if (int.TryParse(suffix, out int n) && n > maxExisting)
                    {
                        maxExisting = n;
                    }
                }
            }

            int nextNumber = maxExisting + 1;

            foreach (var e in entries)
            {
                try
                {
                    bool alreadyNumbered = !string.IsNullOrEmpty(e.Mark) && e.Mark.StartsWith(markPrefix, StringComparison.Ordinal);
                    if (!alreadyNumbered)
                    {
                        string newMark = markPrefix + nextNumber;
                        nextNumber++;

                        Parameter markParam = e.Cloud.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);
                        if (markParam != null && !markParam.IsReadOnly)
                        {
                            markParam.Set(newMark);
                            e.Mark = newMark;
                        }
                    }

                    string locationText = !string.IsNullOrEmpty(e.SheetNumber)
                        ? $"{e.ViewName} [{e.SheetNumber}]"
                        : e.ViewName;

                    Parameter commentsParam = e.Cloud.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);
                    if (commentsParam != null && !commentsParam.IsReadOnly)
                    {
                        commentsParam.Set(locationText ?? string.Empty);
                        e.Comments = locationText;
                    }
                }
                catch (Exception ex)
                {
                    Logger.Debug($"寫入雲形 {e.CloudId} 釋疑編號/定位失敗: {ex.Message}");
                }
            }
        }

        private class RevisionCloudEntry
        {
            public RevisionCloud Cloud;
            public IdType CloudId;
            public string Mark;
            public string Comments;
            public int RevisionSequence;
            public string RevisionDescription;
            public string RevisionDate;
            public IdType ViewId;
            public string ViewName;
            public string ViewType;
            public string SheetNumber;
            public string SheetName;
        }

        #endregion
    }
}
