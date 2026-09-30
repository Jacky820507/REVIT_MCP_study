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
        /// 依外部提供的圖紙紙面座標矩形，在對應圖紙上建立修訂雲形。
        /// 供「PDF 圖說差異比對」按鈕把 PDF 上的差異區域落回 Revit。
        /// dryRun=true 時完全不開 Transaction，只回傳計畫。
        /// </summary>
        /// <remarks>
        /// 雲形建在 ViewSheet 上而不是視圖裡：PDF 頁座標到圖紙紙面座標是單純的
        /// 比例對應，不需要 viewport/crop/scale 換算，位置最不會歪。代價是雲不會
        /// 跟著模型幾何跑——這是刻意的取捨，見 domain/pdf-drawing-diff-revision-cloud.md。
        /// </remarks>
        private object CreateRevisionCloudsOnSheets(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            bool dryRun = parameters["dryRun"]?.Value<bool>() ?? false;
            IdType? revisionIdParam = parameters["revisionId"]?.Value<IdType>();
            IdType? revisionTagTypeIdParam = parameters["revisionTagTypeId"]?.Value<IdType>();
            IdType? referenceCloudIdParam = parameters["referenceCloudId"]?.Value<IdType>();
            string revisionDescription = parameters["revisionDescription"]?.Value<string>();
            bool removeOverlapping = parameters["removeOverlapping"]?.Value<bool>() ?? false;
            bool removeManualOverlaps = parameters["removeManualOverlaps"]?.Value<bool>() ?? false;
            double overlapToleranceMm = parameters["overlapToleranceMm"]?.Value<double>() ?? 3.0;
            if (overlapToleranceMm < 0)
                overlapToleranceMm = 0;
            double overlapToleranceFt = overlapToleranceMm / 304.8;
            string autoCommentPrefix = parameters["autoCommentPrefix"]?.Value<string>();
            if (string.IsNullOrEmpty(autoCommentPrefix))
                autoCommentPrefix = "[自動]";

            JArray specs = parameters["clouds"] as JArray;
            if (specs == null || specs.Count == 0)
                throw new Exception("Parameter 'clouds' is required（至少要有一筆矩形）");

            // 新版 pyRevit 會把範本 ID 放在頂層；保留從單筆 cloud 讀取的
            // 相容路徑，讓舊的呼叫方式也能使用目前選取的方向範本。
            if (!referenceCloudIdParam.HasValue)
            {
                foreach (JToken spec in specs)
                {
                    IdType? perCloudReference = spec["referenceCloudId"]?.Value<IdType>();
                    if (perCloudReference.HasValue)
                    {
                        referenceCloudIdParam = perCloudReference;
                        break;
                    }
                }
            }

            string cloudOrientation = null;
            bool referenceClockwise = ResolveCloudOrientation(
                doc, referenceCloudIdParam, out cloudOrientation);

            // 圖紙以 SheetNumber 索引。重號在 Revit 裡不合法，但 ToDictionary 遇到
            // 髒資料會整批炸掉，所以用 GroupBy 取第一筆，把問題留給個別筆的 Skipped。
            // pyRevit 端另外會帶已選 ViewSheet 的 ElementId；只用文字編號會在
            // PDF DWG NO. 與 Revit 內部 SheetNumber 不同時失去唯一身分。
            List<ViewSheet> allSheets = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .ToList();
            Dictionary<IdType, ViewSheet> sheetsById = allSheets
                .GroupBy(s => s.Id.GetIdValue())
                .ToDictionary(g => g.Key, g => g.First());
            Dictionary<string, ViewSheet> sheetsByNumber = allSheets
                .GroupBy(s => s.SheetNumber ?? string.Empty, StringComparer.Ordinal)
                .ToDictionary(g => g.Key, g => g.First(), StringComparer.Ordinal);

            // 只有在需要清除重疊時才建立既有雲索引；而且限定在本次實際
            // 要處理的圖紙，避免每次執行都掃完整個專案的修訂雲。
            var targetSheetIds = new HashSet<IdType>();
            foreach (JToken spec in specs)
            {
                ViewSheet targetSheet = ResolveCloudSheet(
                    spec, sheetsById, sheetsByNumber, out string targetSheetError);
                if (targetSheet != null)
                    targetSheetIds.Add(targetSheet.Id.GetIdValue());
            }

            Dictionary<IdType, List<ExistingRevisionCloud>> existingCloudsBySheet =
                removeOverlapping && targetSheetIds.Count > 0
                    ? CollectSheetRevisionClouds(
                        doc, sheetsById, targetSheetIds, autoCommentPrefix)
                    : new Dictionary<IdType, List<ExistingRevisionCloud>>();
            var created = new List<object>();
            var skipped = new List<object>();
            var removed = new List<object>();
            var manualOverlaps = new List<object>();
            var revisionTagsCreated = new List<object>();
            var revisionTagsSkipped = new List<object>();
            var deletedCloudIds = new HashSet<IdType>();
            var reportedManualOverlapIds = new HashSet<IdType>();
            var plannedBoundsBySheet = new Dictionary<IdType, List<CloudBounds>>();

            // dry-run 不建 Revision（那會改模型）。有指定就查、沒指定就報告會沿用哪一個。
            Revision revision = ResolveRevision(doc, revisionIdParam, revisionDescription, out bool needsNewRevision);
            FamilySymbol revisionTagType = ResolveRevisionTagType(doc, revisionTagTypeIdParam);
            string revisionTagTypeLabel = DescribeRevisionTagType(revisionTagType);
            if (dryRun)
            {
                foreach (JToken spec in specs)
                {
                    string number = spec["sheetNumber"]?.Value<string>();
                    string label = spec["gridLabel"]?.Value<string>();
                    ViewSheet sheet = ResolveCloudSheet(
                        spec, sheetsById, sheetsByNumber, out string sheetError);
                    if (sheet == null)
                    {
                        skipped.Add(new { SheetNumber = number, GridLabel = label, Reason = sheetError });
                        continue;
                    }
                    string dryRunRectError;
                    if (BuildCloudCurves(
                            spec["rectFt"], referenceClockwise, out dryRunRectError) == null)
                    {
                        skipped.Add(new { SheetNumber = number, GridLabel = label, Reason = dryRunRectError });
                        continue;
                    }
                    CloudBounds candidateBounds = CloudBounds.FromRect(spec["rectFt"]);
                    if (candidateBounds == null)
                    {
                        skipped.Add(new { SheetNumber = number, GridLabel = label, Reason = "rectFt 無效" });
                        continue;
                    }
                    ProcessRevisionCloudOverlaps(
                        doc, sheet, candidateBounds, existingCloudsBySheet,
                        deletedCloudIds, referenceCloudIdParam,
                        removeOverlapping, removeManualOverlaps, overlapToleranceFt,
                        false, removed, manualOverlaps, reportedManualOverlapIds);
                    if (IsPlannedDuplicate(
                            sheet, candidateBounds, plannedBoundsBySheet, overlapToleranceFt))
                    {
                        skipped.Add(new
                        {
                            SheetNumber = number,
                            GridLabel = label,
                            Reason = "與本次執行已排入的雲形重疊"
                        });
                        continue;
                    }
                    AddPlannedBounds(sheet, candidateBounds, plannedBoundsBySheet);
                    created.Add(new
                    {
                        SheetNumber = sheet.SheetNumber,
                        PdfDwgNumber = spec["dwgNumber"]?.Value<string>(),
                        GridLabel = label,
                        Comment = spec["comment"]?.Value<string>()
                    });
                }

                return new
                {
                    DryRun = true,
                    RevisionUsed = revision != null
                        ? $"{revision.SequenceNumber} {revision.Description}"
                    : (needsNewRevision ? "（將建立新修訂）" : "（無）"),
                    CloudOrientation = cloudOrientation,
                    RevisionTagType = revisionTagTypeLabel,
                    RevisionTagsPlanned = revisionTagType == null ? 0 : created.Count,
                    Created = created,
                    Skipped = skipped,
                    Removed = removed,
                    ManualOverlaps = manualOverlaps
                };
            }

            using (Transaction trans = new Transaction(doc, "建立圖說差異修訂雲"))
            {
                trans.Start();
                // 標籤類型只需啟用一次；不要在每朵雲建立時重複觸發
                // IsActive／Activate／Regenerate。
                bool revisionTagTypePrepared = revisionTagType == null ||
                    revisionTagType.IsActive;

                if (revision == null)
                {
                    revision = Revision.Create(doc);
                    revision.Description = string.IsNullOrEmpty(revisionDescription)
                        ? $"圖說差異比對 {DateTime.Now:yyyy-MM-dd}"
                        : revisionDescription;
                    revision.RevisionDate = DateTime.Now.ToString("yyyy-MM-dd");
                }

                foreach (JToken spec in specs)
                {
                    string number = spec["sheetNumber"]?.Value<string>();
                    string label = spec["gridLabel"]?.Value<string>();
                    string comment = spec["comment"]?.Value<string>();

                    try
                    {
                        ViewSheet sheet = ResolveCloudSheet(
                            spec, sheetsById, sheetsByNumber, out string sheetError);
                        if (sheet == null)
                        {
                            skipped.Add(new { SheetNumber = number, GridLabel = label, Reason = sheetError });
                            continue;
                        }

                        IList<Curve> curves = BuildCloudCurves(
                            spec["rectFt"], referenceClockwise, out string rectError);
                        if (curves == null)
                        {
                            skipped.Add(new { SheetNumber = number, GridLabel = label, Reason = rectError });
                            continue;
                        }

                        CloudBounds candidateBounds = CloudBounds.FromRect(spec["rectFt"]);
                        if (candidateBounds == null)
                        {
                            skipped.Add(new { SheetNumber = number, GridLabel = label, Reason = "rectFt 無效" });
                            continue;
                        }
                        ProcessRevisionCloudOverlaps(
                            doc, sheet, candidateBounds, existingCloudsBySheet,
                            deletedCloudIds, referenceCloudIdParam,
                            removeOverlapping, removeManualOverlaps, overlapToleranceFt,
                            true, removed, manualOverlaps, reportedManualOverlapIds);
                        if (IsPlannedDuplicate(
                                sheet, candidateBounds, plannedBoundsBySheet, overlapToleranceFt))
                        {
                            skipped.Add(new
                            {
                                SheetNumber = number,
                                GridLabel = label,
                                Reason = "與本次執行已排入的雲形重疊"
                            });
                            continue;
                        }
                        AddPlannedBounds(sheet, candidateBounds, plannedBoundsBySheet);

                        RevisionCloud cloud = RevisionCloud.Create(doc, sheet, revision.Id, curves);

                        // Comments 是既有 scan_revision_clouds 讀出來放進釋疑 Excel 的欄位，
                        // 差異描述寫在這裡，整條釋疑管線就自動接得上。
                        if (!string.IsNullOrEmpty(comment))
                        {
                            Parameter commentsParam = cloud.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);
                            if (commentsParam != null && !commentsParam.IsReadOnly)
                                commentsParam.Set(comment);
                        }

                        if (revisionTagType != null)
                        {
                            try
                            {
                                if (!revisionTagTypePrepared)
                                {
                                    revisionTagType.Activate();
                                    doc.Regenerate();
                                    revisionTagTypePrepared = true;
                                }

                                XYZ tagPosition = ComputeRevisionTagPosition(
                                    sheet, candidateBounds);
                                IndependentTag tag = CreateRevisionCloudTag(
                                    doc, sheet, cloud, revisionTagType, tagPosition);
                                revisionTagsCreated.Add(new
                                {
                                    ElementId = tag.Id.GetIdValue(),
                                    CloudElementId = cloud.Id.GetIdValue(),
                                    SheetNumber = sheet.SheetNumber,
                                    GridLabel = label,
                                    PositionU = tagPosition.X,
                                    PositionV = tagPosition.Y
                                });
                            }
                            catch (Exception tagEx)
                            {
                                // 標籤建立失敗不回滾已成功建立的雲；回傳逐筆原因，
                                // 讓使用者可以先保留雲再處理未載入／不相容的標籤族群。
                                revisionTagsSkipped.Add(new
                                {
                                    CloudElementId = cloud.Id.GetIdValue(),
                                    SheetNumber = sheet.SheetNumber,
                                    GridLabel = label,
                                    Reason = tagEx.Message
                                });
                            }
                        }

                        created.Add(new
                        {
                            ElementId = cloud.Id.GetIdValue(),
                            SheetId = sheet.Id.GetIdValue(),
                            SheetNumber = sheet.SheetNumber,
                            SheetName = sheet.Name,
                            PdfDwgNumber = spec["dwgNumber"]?.Value<string>(),
                            GridLabel = label,
                            Comment = comment
                        });
                    }
                    catch (Exception ex)
                    {
                        // 逐筆吞例外：一朵畫不出來（框太小、圖紙被鎖）不該讓整批中斷。
                        skipped.Add(new { SheetNumber = number, GridLabel = label, Reason = ex.Message });
                    }
                }

                trans.Commit();
            }

            return new
            {
                DryRun = false,
                RevisionUsed = $"{revision.SequenceNumber} {revision.Description}",
                RevisionId = revision.Id.GetIdValue(),
                CloudOrientation = cloudOrientation,
                RevisionTagType = revisionTagTypeLabel,
                RevisionTagsCreated = revisionTagsCreated.Count,
                RevisionTagsSkipped = revisionTagsSkipped,
                Created = created,
                Skipped = skipped,
                Removed = removed,
                ManualOverlaps = manualOverlaps
            };
        }

        /// <summary>
        /// 以 pyRevit 傳來的 ViewSheet ElementId 解析目標；舊呼叫者沒有 ID 時
        /// 才退回 SheetNumber。ID 存在但找不到時不改配到另一張同名／同號圖紙。
        /// </summary>
        private ViewSheet ResolveCloudSheet(
            JToken spec,
            Dictionary<IdType, ViewSheet> sheetsById,
            Dictionary<string, ViewSheet> sheetsByNumber,
            out string error)
        {
            error = null;
            string number = spec["sheetNumber"]?.Value<string>();
            IdType? sheetId = spec["sheetId"]?.Value<IdType>();

            if (sheetId.HasValue)
            {
                if (sheetsById.TryGetValue(sheetId.Value, out ViewSheet byId))
                    return byId;

                error = $"找不到指定的 Revit 圖紙 ElementId: {sheetId.Value}";
                return null;
            }

            if (!string.IsNullOrEmpty(number) &&
                sheetsByNumber.TryGetValue(number, out ViewSheet byNumber))
                return byNumber;

            error = "專案中找不到這個圖紙編號";
            return null;
        }

        /// <summary>
        /// 建立目前所有圖紙上的修訂雲索引，供重跑時做空間去重。
        /// 只索引能讀到幾何範圍的雲；讀不到範圍時寧可保留，不猜測並刪除。
        /// </summary>
        private Dictionary<IdType, List<ExistingRevisionCloud>> CollectSheetRevisionClouds(
            Document doc,
            Dictionary<IdType, ViewSheet> sheetsById,
            ISet<IdType> targetSheetIds,
            string autoCommentPrefix)
        {
            var result = new Dictionary<IdType, List<ExistingRevisionCloud>>();

            if (targetSheetIds == null || targetSheetIds.Count == 0)
                return result;

            // ElementOwnerViewFilter 是 quick filter；搭配 OR 後只展開本次
            // 目標圖紙的 RevisionCloud，避免先把其他圖紙的雲全部載入記憶體。
            var ownerFilters = targetSheetIds
                .Select(id => (ElementFilter)new ElementOwnerViewFilter(
                    id.ToElementId()))
                .ToList();
            ElementFilter ownerFilter = ownerFilters.Count == 1
                ? ownerFilters[0]
                : new LogicalOrFilter(ownerFilters);
            var clouds = new FilteredElementCollector(doc)
                .OfClass(typeof(RevisionCloud))
                .WherePasses(ownerFilter)
                .Cast<RevisionCloud>()
                .ToList();

            foreach (RevisionCloud cloud in clouds)
            {
                try
                {
                    ElementId ownerViewId = cloud.OwnerViewId;
                    if (ownerViewId == null || ownerViewId == ElementId.InvalidElementId)
                        continue;

                    IdType sheetId = ownerViewId.GetIdValue();
                    if (!targetSheetIds.Contains(sheetId) ||
                        !sheetsById.TryGetValue(sheetId, out ViewSheet sheet))
                        continue;

                    if (!TryGetRevisionCloudBounds(cloud, out CloudBounds bounds))
                        continue;

                    string comments = GetRevisionCloudComments(cloud);
                    var info = new ExistingRevisionCloud
                    {
                        Cloud = cloud,
                        Sheet = sheet,
                        Bounds = bounds,
                        Comments = comments,
                        IsProgramGenerated = IsProgramGeneratedComment(
                            comments, autoCommentPrefix)
                    };

                    if (!result.TryGetValue(sheetId, out List<ExistingRevisionCloud> list))
                    {
                        list = new List<ExistingRevisionCloud>();
                        result[sheetId] = list;
                    }
                    list.Add(info);
                }
                catch (Exception ex)
                {
                    Logger.Debug($"建立修訂雲去重索引失敗，略過 {cloud.Id.GetIdValue()}: {ex.Message}");
                }
            }

            return result;
        }

        private string GetRevisionCloudComments(RevisionCloud cloud)
        {
            try
            {
                return cloud.get_Parameter(
                    BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)?.AsString();
            }
            catch (Exception ex)
            {
                Logger.Debug($"讀取修訂雲 {cloud.Id.GetIdValue()} Comments 失敗: {ex.Message}");
                return null;
            }
        }

        /// <summary>
        /// 新版用明確前綴辨識；舊版尚未有前綴時，辨識本按鈕既有的定位格式。
        /// 空白備註與一般手動備註都不算程式雲，預設不會被刪除。
        /// </summary>
        private bool IsProgramGeneratedComment(string comments, string autoCommentPrefix)
        {
            if (string.IsNullOrEmpty(comments))
                return false;

            if (!string.IsNullOrEmpty(autoCommentPrefix) &&
                comments.StartsWith(autoCommentPrefix, StringComparison.Ordinal))
                return true;

            // 相容第一次部署前已建立的雲，例如「[F4:F5] 新增文字：D4a」。
            return comments.StartsWith("[", StringComparison.Ordinal) &&
                (comments.IndexOf("新增文字：", StringComparison.Ordinal) >= 0 ||
                 comments.IndexOf("刪除文字：", StringComparison.Ordinal) >= 0 ||
                 comments.IndexOf("圖面差異：", StringComparison.Ordinal) >= 0 ||
                 comments.IndexOf(" → ", StringComparison.Ordinal) >= 0);
        }

        private void ProcessRevisionCloudOverlaps(
            Document doc,
            ViewSheet sheet,
            CloudBounds candidateBounds,
            Dictionary<IdType, List<ExistingRevisionCloud>> existingCloudsBySheet,
            HashSet<IdType> deletedCloudIds,
            IdType? protectedCloudId,
            bool removeOverlapping,
            bool removeManualOverlaps,
            double toleranceFt,
            bool deleteMatches,
            List<object> removed,
            List<object> manualOverlaps,
            HashSet<IdType> reportedManualOverlapIds)
        {
            if (!removeOverlapping)
                return;

            IdType sheetId = sheet.Id.GetIdValue();
            if (!existingCloudsBySheet.TryGetValue(
                    sheetId, out List<ExistingRevisionCloud> existing))
                return;

            foreach (ExistingRevisionCloud info in existing)
            {
                IdType cloudId = info.Cloud.Id.GetIdValue();
                if (deletedCloudIds.Contains(cloudId))
                    continue;
                if (protectedCloudId.HasValue && protectedCloudId.Value == cloudId)
                    continue;
                if (!BoundsOverlapOrNear(candidateBounds, info.Bounds, toleranceFt))
                    continue;

                if (info.IsProgramGenerated || removeManualOverlaps)
                {
                    // 只刪除空間上高度相似的舊雲。相鄰設備的框常會局部相交；
                    // 若把「有交集」直接當成同一朵雲，重跑時會誤刪其他有效差異。
                    if (!BoundsAreNearDuplicate(
                            candidateBounds, info.Bounds, toleranceFt, 0.50))
                        continue;

                    if (deleteMatches)
                        doc.Delete(info.Cloud.Id);

                    deletedCloudIds.Add(cloudId);
                    removed.Add(new
                    {
                        ElementId = cloudId,
                        SheetNumber = sheet.SheetNumber,
                        Comments = info.Comments,
                        WasProgramGenerated = info.IsProgramGenerated
                    });
                }
                else if (reportedManualOverlapIds.Add(cloudId))
                {
                    manualOverlaps.Add(new
                    {
                        ElementId = cloudId,
                        SheetNumber = sheet.SheetNumber,
                        Comments = info.Comments
                    });
                }
            }
        }

        private bool IsPlannedDuplicate(
            ViewSheet sheet,
            CloudBounds candidateBounds,
            Dictionary<IdType, List<CloudBounds>> plannedBoundsBySheet,
            double toleranceFt)
        {
            IdType sheetId = sheet.Id.GetIdValue();
            if (!plannedBoundsBySheet.TryGetValue(
                    sheetId, out List<CloudBounds> planned))
                return false;

            // 同一次執行只排除幾乎相同的框。文字框、設備基座與線條範圍
            // 可能合理地互相交疊，不能因為有任意交集就吞掉後續雲形。
            return planned.Any(existing => BoundsAreNearDuplicate(
                candidateBounds, existing, toleranceFt, 0.80));
        }

        private void AddPlannedBounds(
            ViewSheet sheet,
            CloudBounds bounds,
            Dictionary<IdType, List<CloudBounds>> plannedBoundsBySheet)
        {
            IdType sheetId = sheet.Id.GetIdValue();
            if (!plannedBoundsBySheet.TryGetValue(
                    sheetId, out List<CloudBounds> planned))
            {
                planned = new List<CloudBounds>();
                plannedBoundsBySheet[sheetId] = planned;
            }
            planned.Add(bounds);
        }

        private static bool BoundsOverlapOrNear(
            CloudBounds first,
            CloudBounds second,
            double toleranceFt)
        {
            return first.MinU <= second.MaxU + toleranceFt &&
                   first.MaxU + toleranceFt >= second.MinU &&
                   first.MinV <= second.MaxV + toleranceFt &&
                   first.MaxV + toleranceFt >= second.MinV;
        }

        /// <summary>
        /// 判斷兩個範圍是否代表同一朵雲，而不只是局部相交。
        /// 四邊都落在容差內視為相同；否則要求足夠高的 IoU。
        /// </summary>
        private static bool BoundsAreNearDuplicate(
            CloudBounds first,
            CloudBounds second,
            double toleranceFt,
            double minimumIntersectionOverUnion)
        {
            if (first == null || second == null)
                return false;

            bool matchingEdges =
                Math.Abs(first.MinU - second.MinU) <= toleranceFt &&
                Math.Abs(first.MinV - second.MinV) <= toleranceFt &&
                Math.Abs(first.MaxU - second.MaxU) <= toleranceFt &&
                Math.Abs(first.MaxV - second.MaxV) <= toleranceFt;
            if (matchingEdges)
                return true;

            double intersectionWidth = Math.Max(
                0, Math.Min(first.MaxU, second.MaxU) -
                   Math.Max(first.MinU, second.MinU));
            double intersectionHeight = Math.Max(
                0, Math.Min(first.MaxV, second.MaxV) -
                   Math.Max(first.MinV, second.MinV));
            double intersectionArea = intersectionWidth * intersectionHeight;
            if (intersectionArea <= 0)
                return false;

            double firstArea = (first.MaxU - first.MinU) *
                (first.MaxV - first.MinV);
            double secondArea = (second.MaxU - second.MinU) *
                (second.MaxV - second.MinV);
            double unionArea = firstArea + secondArea - intersectionArea;
            if (unionArea <= 0)
                return false;

            return intersectionArea / unionArea >= minimumIntersectionOverUnion;
        }

        private bool TryGetRevisionCloudBounds(
            RevisionCloud cloud,
            out CloudBounds bounds)
        {
            bounds = null;
            IList<Curve> curves;
            try
            {
                curves = cloud.GetSketchCurves();
            }
            catch
            {
                return false;
            }

            if (curves == null || curves.Count == 0)
                return false;

            double minU = double.PositiveInfinity;
            double minV = double.PositiveInfinity;
            double maxU = double.NegativeInfinity;
            double maxV = double.NegativeInfinity;
            bool foundPoint = false;

            foreach (Curve curve in curves)
            {
                if (curve == null)
                    continue;

                IList<XYZ> points = null;
                try
                {
                    points = curve.Tessellate();
                }
                catch
                {
                    // 退回端點；即使某一段曲線不能 tessellate，也不讓整個
                    // 去重流程中止。
                }

                if (points == null || points.Count == 0)
                {
                    try
                    {
                        points = new List<XYZ>
                        {
                            curve.GetEndPoint(0),
                            curve.GetEndPoint(1)
                        };
                    }
                    catch
                    {
                        continue;
                    }
                }

                foreach (XYZ point in points)
                {
                    if (point == null)
                        continue;
                    minU = Math.Min(minU, point.X);
                    minV = Math.Min(minV, point.Y);
                    maxU = Math.Max(maxU, point.X);
                    maxV = Math.Max(maxV, point.Y);
                    foundPoint = true;
                }
            }

            if (!foundPoint || maxU <= minU || maxV <= minV)
                return false;

            bounds = new CloudBounds(minU, minV, maxU, maxV);
            return true;
        }

        /// <summary>
        /// 決定要掛在哪一個 Revision 底下。回傳 null 代表「需要新建一個」。
        /// </summary>
        private Revision ResolveRevision(Document doc, IdType? revisionId, string description, out bool needsNew)
        {
            needsNew = false;

            if (revisionId.HasValue && revisionId.Value > 0)
            {
                Revision byId = doc.GetElement(revisionId.Value.ToElementId()) as Revision;
                if (byId == null)
                    throw new Exception($"找不到修訂 ID: {revisionId.Value}");
                return byId;
            }

            List<Revision> revisions = new FilteredElementCollector(doc)
                .OfClass(typeof(Revision))
                .Cast<Revision>()
                .OrderBy(r => r.SequenceNumber)
                .ToList();

            if (!string.IsNullOrEmpty(description))
            {
                Revision byDescription = revisions.LastOrDefault(
                    r => string.Equals(r.Description, description, StringComparison.Ordinal));
                if (byDescription != null)
                    return byDescription;
                // 指定了說明卻找不到 → 建一個叫這個名字的新修訂，而不是默默沿用別的。
                needsNew = true;
                return null;
            }

            if (revisions.Count > 0)
                return revisions.Last();

            needsNew = true;
            return null;
        }

        /// <summary>
        /// 解析使用者在 UI 選擇的修訂雲狀標籤類型。
        /// 修訂雲標籤是 OST_RevisionCloudTags 的 FamilySymbol；沒有選擇時
        /// 回傳 null，代表只建立雲、不自動放置標籤。
        /// </summary>
        private FamilySymbol ResolveRevisionTagType(
            Document doc,
            IdType? revisionTagTypeId)
        {
            if (!revisionTagTypeId.HasValue || revisionTagTypeId.Value <= 0)
                return null;

            FamilySymbol tagType = doc.GetElement(
                revisionTagTypeId.Value.ToElementId()) as FamilySymbol;
            if (tagType == null)
                throw new Exception(
                    $"找不到修訂雲狀標籤類型 ID: {revisionTagTypeId.Value}");

            Category category = tagType.Category;
            if (category == null ||
                category.Id.GetIdValue() != (IdType)BuiltInCategory.OST_RevisionCloudTags)
            {
                throw new Exception(
                    $"ElementId {revisionTagTypeId.Value} 不是修訂雲狀標籤類型");
            }

            return tagType;
        }

        private string DescribeRevisionTagType(FamilySymbol tagType)
        {
            if (tagType == null)
                return "（不放置修訂雲狀標籤）";

            return $"{tagType.FamilyName} : {tagType.Name} (ID {tagType.Id.GetIdValue()})";
        }

        /// <summary>
        /// 以雲的紙面矩形決定標籤頭位置：優先放在右側，其次左、上、下，
        /// 並保留約 12 mm 的紙邊安全距離。這裡使用 ViewSheet 紙面座標，
        /// 與 RevisionCloud.Create 使用的座標系一致。
        /// </summary>
        private XYZ ComputeRevisionTagPosition(
            ViewSheet sheet,
            CloudBounds bounds)
        {
            if (sheet == null || bounds == null)
                throw new ArgumentNullException("sheet/bounds");

            BoundingBoxUV outline = sheet.Outline;
            if (outline == null || outline.Max.U <= outline.Min.U ||
                outline.Max.V <= outline.Min.V)
            {
                throw new InvalidOperationException("圖紙 Outline 無效，無法定位修訂標籤");
            }

            const double edgePaddingFt = 12.0 / 304.8;
            const double cloudGapFt = 6.0 / 304.8;
            double centerU = (bounds.MinU + bounds.MaxU) / 2.0;
            double centerV = (bounds.MinV + bounds.MaxV) / 2.0;

            var candidates = new List<XYZ>
            {
                new XYZ(bounds.MaxU + cloudGapFt, centerV, 0),
                new XYZ(bounds.MinU - cloudGapFt, centerV, 0),
                new XYZ(centerU, bounds.MaxV + cloudGapFt, 0),
                new XYZ(centerU, bounds.MinV - cloudGapFt, 0)
            };

            foreach (XYZ candidate in candidates)
            {
                if (candidate.X >= outline.Min.U + edgePaddingFt &&
                    candidate.X <= outline.Max.U - edgePaddingFt &&
                    candidate.Y >= outline.Min.V + edgePaddingFt &&
                    candidate.Y <= outline.Max.V - edgePaddingFt)
                {
                    return candidate;
                }
            }

            // 雲形幾乎佔滿圖紙時四側都沒有完整空間；仍將標籤放在
            // 圖紙內且靠近雲中心，避免因為追求完美位置而漏放標籤。
            double minU = outline.Min.U + edgePaddingFt;
            double maxU = outline.Max.U - edgePaddingFt;
            double minV = outline.Min.V + edgePaddingFt;
            double maxV = outline.Max.V - edgePaddingFt;
            return new XYZ(
                Math.Max(minU, Math.Min(maxU, centerU)),
                Math.Max(minV, Math.Min(maxV, centerV)),
                0);
        }

        /// <summary>
        /// 以指定 FamilySymbol 建立一個掛在 RevisionCloud 上的標籤，
        /// 並把 TagHeadPosition 固定在計算出的雲旁位置；不加引線，避免
        /// 大批圖紙產生交錯的引線。
        /// </summary>
        private IndependentTag CreateRevisionCloudTag(
            Document doc,
            ViewSheet sheet,
            RevisionCloud cloud,
            FamilySymbol tagType,
            XYZ tagPosition)
        {
            if (doc == null || sheet == null || cloud == null || tagType == null ||
                tagPosition == null)
            {
                throw new ArgumentNullException("tag creation argument");
            }

            IndependentTag tag = IndependentTag.Create(
                doc,
                tagType.Id,
                sheet.Id,
                new Reference(cloud),
                false,
                TagOrientation.Horizontal,
                tagPosition);
            if (tag == null)
                throw new InvalidOperationException("修訂雲狀標籤建立失敗");
            return tag;
        }

        /// <summary>
        /// 讀取使用者選取的修訂雲，取得其 sketch loop 的方向。
        /// 沒有範本時沿用 Revit API 所要求的順時針預設值。
        /// </summary>
        private bool ResolveCloudOrientation(
            Document doc,
            IdType? referenceCloudId,
            out string description)
        {
            if (!referenceCloudId.HasValue || referenceCloudId.Value <= 0)
            {
                description = "預設方向：順時針";
                return true;
            }

            RevisionCloud referenceCloud = doc.GetElement(
                referenceCloudId.Value.ToElementId()) as RevisionCloud;
            if (referenceCloud == null)
            {
                throw new Exception($"找不到方向範本修訂雲 ElementId: {referenceCloudId.Value}");
            }

            if (!TryGetRevisionCloudSignedArea(
                    referenceCloud, out double signedArea, out string error))
            {
                throw new Exception(
                    $"無法讀取方向範本修訂雲 {referenceCloudId.Value} 的迴圈方向：{error}");
            }

            bool clockwise = signedArea < 0;
            description = $"套用選取修訂雲 {referenceCloudId.Value} 的"
                + $"{(clockwise ? "順時針" : "逆時針")}迴圈方向";
            return clockwise;
        }

        /// <summary>
        /// 從 RevisionCloud.GetSketchCurves() 的端點連接關係計算最大封閉迴圈
        /// 的 signed area。使用最大迴圈可避開極少數含多個 loop 的雲形。
        /// </summary>
        private bool TryGetRevisionCloudSignedArea(
            RevisionCloud cloud,
            out double signedArea,
            out string error)
        {
            signedArea = 0;
            error = null;

            IList<Curve> sketchCurves;
            try
            {
                sketchCurves = cloud.GetSketchCurves();
            }
            catch (Exception ex)
            {
                error = ex.Message;
                return false;
            }

            if (sketchCurves == null || sketchCurves.Count < 3)
            {
                error = "sketch curves 不足三條";
                return false;
            }

            const double pointTolerance = 1e-7;
            var remaining = sketchCurves
                .Where(curve => curve != null)
                .ToList();
            double largestArea = 0;

            while (remaining.Count > 0)
            {
                Curve first = remaining[0];
                remaining.RemoveAt(0);

                XYZ start;
                XYZ current;
                try
                {
                    start = first.GetEndPoint(0);
                    current = first.GetEndPoint(1);
                }
                catch (Exception ex)
                {
                    error = ex.Message;
                    return false;
                }

                var points = new List<XYZ> { start, current };
                int guard = 0;
                while (!PointsMatch(current, start, pointTolerance) &&
                       remaining.Count > 0 && guard++ <= sketchCurves.Count)
                {
                    int nextIndex = FindConnectedCurve(
                        remaining, current, pointTolerance, out XYZ nextPoint);
                    if (nextIndex < 0)
                        break;

                    remaining.RemoveAt(nextIndex);
                    points.Add(nextPoint);
                    current = nextPoint;
                }

                if (!PointsMatch(current, start, pointTolerance) || points.Count < 4)
                    continue;

                double area = 0;
                for (int i = 0; i < points.Count - 1; i++)
                {
                    area += points[i].X * points[i + 1].Y
                        - points[i + 1].X * points[i].Y;
                }

                if (Math.Abs(area) > Math.Abs(largestArea))
                    largestArea = area;
            }

            if (Math.Abs(largestArea) <= 1e-12)
            {
                error = "找不到可判定方向的封閉 sketch loop";
                return false;
            }

            signedArea = largestArea;
            return true;
        }

        private static int FindConnectedCurve(
            IList<Curve> curves,
            XYZ point,
            double tolerance,
            out XYZ nextPoint)
        {
            nextPoint = null;
            for (int i = 0; i < curves.Count; i++)
            {
                Curve curve = curves[i];
                XYZ start = curve.GetEndPoint(0);
                XYZ end = curve.GetEndPoint(1);
                if (PointsMatch(start, point, tolerance))
                {
                    nextPoint = end;
                    return i;
                }
                if (PointsMatch(end, point, tolerance))
                {
                    nextPoint = start;
                    return i;
                }
            }
            return -1;
        }

        private static bool PointsMatch(XYZ first, XYZ second, double tolerance)
        {
            return first != null && second != null && first.DistanceTo(second) <= tolerance;
        }

        /// <summary>
        /// 把圖紙紙面座標的矩形轉成封閉的四條線；無效時回傳 null 並附原因。
        /// </summary>
        private IList<Curve> BuildCloudCurves(
            JToken rect,
            bool clockwise,
            out string error)
        {
            error = null;
            if (rect == null)
            {
                error = "缺少 rectFt";
                return null;
            }

            double minU = rect["minU"]?.Value<double>() ?? 0;
            double minV = rect["minV"]?.Value<double>() ?? 0;
            double maxU = rect["maxU"]?.Value<double>() ?? 0;
            double maxV = rect["maxV"]?.Value<double>() ?? 0;

            // Revit 拒絕比 ShortCurveTolerance 短的線。呼叫端的 build_cloud_rect
            // 已經套過最小尺寸，這裡是最後一道防線，避免中間環節把它壓扁。
            double tolerance = _uiApp.Application.ShortCurveTolerance;
            if (maxU - minU <= tolerance || maxV - minV <= tolerance)
            {
                error = $"矩形太小（{maxU - minU:F4} x {maxV - minV:F4} ft），Revit 畫不出雲形";
                return null;
            }

            XYZ bottomLeft = new XYZ(minU, minV, 0);
            XYZ topLeft = new XYZ(minU, maxV, 0);
            XYZ topRight = new XYZ(maxU, maxV, 0);
            XYZ bottomRight = new XYZ(maxU, minV, 0);

            // 方向直接跟隨範本雲，不再假設所有專案／視圖的紙面視覺方向
            // 都與單純的 XY 判斷相同。順時針路徑是 BL→TL→TR→BR。
            if (clockwise)
            {
                return new List<Curve>
                {
                    Line.CreateBound(bottomLeft, topLeft),
                    Line.CreateBound(topLeft, topRight),
                    Line.CreateBound(topRight, bottomRight),
                    Line.CreateBound(bottomRight, bottomLeft)
                };
            }

            return new List<Curve>
            {
                Line.CreateBound(bottomLeft, bottomRight),
                Line.CreateBound(bottomRight, topRight),
                Line.CreateBound(topRight, topLeft),
                Line.CreateBound(topLeft, bottomLeft)
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

        private sealed class ExistingRevisionCloud
        {
            public RevisionCloud Cloud;
            public ViewSheet Sheet;
            public CloudBounds Bounds;
            public string Comments;
            public bool IsProgramGenerated;
        }

        private sealed class CloudBounds
        {
            public CloudBounds(double minU, double minV, double maxU, double maxV)
            {
                MinU = minU;
                MinV = minV;
                MaxU = maxU;
                MaxV = maxV;
            }

            public double MinU { get; private set; }
            public double MinV { get; private set; }
            public double MaxU { get; private set; }
            public double MaxV { get; private set; }

            public static CloudBounds FromRect(JToken rect)
            {
                if (rect == null)
                    return null;

                double minU = rect["minU"]?.Value<double>() ?? 0;
                double minV = rect["minV"]?.Value<double>() ?? 0;
                double maxU = rect["maxU"]?.Value<double>() ?? 0;
                double maxV = rect["maxV"]?.Value<double>() ?? 0;
                if (maxU <= minU || maxV <= minV)
                    return null;

                return new CloudBounds(minU, minV, maxU, maxV);
            }
        }

        #endregion
    }
}
