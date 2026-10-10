using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;
using Newtonsoft.Json.Linq;

#if REVIT2025_OR_GREATER
using IdType = System.Int64;
#else
using IdType = System.Int32;
#endif

namespace RevitMCP.Core
{
    /// <summary>
    /// 明細表批量工具：列出（可關鍵字／品類篩選）、批量建立、批量新增參數欄位。
    /// pyRevit 對應按鈕：BatchCreateSchedules / BatchAddScheduleFields（同一套命名與欄位比對規則）。
    /// </summary>
    public partial class CommandExecutor
    {
        // Revit 不允許出現在檢視名稱裡的字元。
        private static readonly char[] ScheduleNameForbiddenChars =
            new[] { '\\', ':', '{', '}', '[', ']', '|', ';', '<', '>', '?', '`', '~' };

        #region list_schedules

        private object ListSchedules(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            string keyword = parameters["keyword"]?.Value<string>();
            string category = parameters["category"]?.Value<string>();

            var rows = new List<object>();
            foreach (ViewSchedule schedule in CollectUserSchedules(doc))
            {
                string categoryName = GetScheduleCategoryName(doc, schedule);
                if (!ScheduleMatchesKeyword(schedule.Name, keyword)) continue;
                if (!string.IsNullOrWhiteSpace(category) &&
                    !string.Equals(categoryName, category.Trim(), StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                rows.Add(new
                {
                    ScheduleId = schedule.Id.GetIdValue(),
                    Name = schedule.Name,
                    Category = categoryName,
                    FieldCount = schedule.Definition.GetFieldCount()
                });
            }

            return new { Count = rows.Count, Schedules = rows };
        }

        #endregion

        #region batch_create_view_schedules

        private object BatchCreateViewSchedules(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            bool dryRun = parameters["dryRun"]?.Value<bool>() ?? false;
            string onConflict = (parameters["onNameConflict"]?.Value<string>() ?? "skip").Trim().ToLowerInvariant();
            if (onConflict != "skip" && onConflict != "suffix")
            {
                throw new ArgumentException("onNameConflict must be 'skip' or 'suffix'.");
            }

            string nameTemplate = parameters["nameTemplate"]?.Value<string>();
            if (string.IsNullOrWhiteSpace(nameTemplate)) nameTemplate = "{category}明細表";
            var sharedFields = parameters["fields"]?.ToObject<List<string>>() ?? new List<string>();

            // 組出要建立的清單：schedules（逐張指定）＋ categories（共用 fields 與名稱樣板）。
            var requests = new List<ScheduleCreateRequest>();
            if (parameters["schedules"] is JArray explicitList)
            {
                foreach (JToken item in explicitList)
                {
                    string category = item["category"]?.Value<string>();
                    string name = item["name"]?.Value<string>();
                    if (string.IsNullOrWhiteSpace(category))
                    {
                        throw new ArgumentException("Each entry of 'schedules' requires 'category'.");
                    }

                    requests.Add(new ScheduleCreateRequest
                    {
                        Category = category.Trim(),
                        Name = string.IsNullOrWhiteSpace(name) ? RenderScheduleName(nameTemplate, category) : name,
                        Fields = item["fields"]?.ToObject<List<string>>() ?? sharedFields
                    });
                }
            }

            if (parameters["categories"] is JArray categoryList)
            {
                foreach (JToken item in categoryList)
                {
                    string category = item.Value<string>();
                    if (string.IsNullOrWhiteSpace(category)) continue;
                    requests.Add(new ScheduleCreateRequest
                    {
                        Category = category.Trim(),
                        Name = RenderScheduleName(nameTemplate, category),
                        Fields = sharedFields
                    });
                }
            }

            if (requests.Count == 0)
            {
                throw new ArgumentException("batch_create_view_schedules requires 'schedules' or 'categories'.");
            }

            var takenNames = new HashSet<string>(
                CollectUserSchedules(doc).Select(s => s.Name), StringComparer.OrdinalIgnoreCase);

            // 先解析品類與名稱，不動模型——dry-run 與實際建立走同一份計畫。
            foreach (ScheduleCreateRequest request in requests)
            {
                request.CategoryId = ResolveScheduleCategoryId(doc, request.Category);
                request.Name = SanitizeScheduleName(request.Name);

                if (request.CategoryId == ElementId.InvalidElementId)
                {
                    request.Status = "failed";
                    request.Note = $"找不到品類: {request.Category}";
                    continue;
                }

                if (takenNames.Contains(request.Name))
                {
                    if (onConflict == "skip")
                    {
                        request.Status = "skipped";
                        request.Note = "名稱已存在";
                        continue;
                    }

                    int suffix = 2;
                    string candidate;
                    do { candidate = $"{request.Name} ({suffix++})"; }
                    while (takenNames.Contains(candidate));
                    request.Name = candidate;
                }

                takenNames.Add(request.Name);
                request.Status = dryRun ? "planned" : "pending";
            }

            if (!dryRun && requests.Any(r => r.Status == "pending"))
            {
                using (Transaction trans = new Transaction(doc, "批量建立明細表"))
                {
                    trans.Start();
                    foreach (ScheduleCreateRequest request in requests.Where(r => r.Status == "pending"))
                    {
                        using (SubTransaction sub = new SubTransaction(doc))
                        {
                            sub.Start();
                            try
                            {
                                ViewSchedule schedule = ViewSchedule.CreateSchedule(doc, request.CategoryId);
                                schedule.Name = request.Name;
                                ApplyFieldsByName(doc, schedule, request.Fields, true, request);
                                request.ScheduleId = schedule.Id.GetIdValue();
                                request.Status = "created";
                                sub.Commit();
                            }
                            catch (Exception ex)
                            {
                                sub.RollBack();
                                request.Status = "failed";
                                request.Note = ex.Message;
                            }
                        }
                    }

                    if (requests.Any(r => r.Status == "created")) trans.Commit();
                    else trans.RollBack();
                }
            }
            else if (dryRun)
            {
                // dry-run 只回報欄位對得上與否：用 scratch 交易建出來看過就回復，模型不會留下東西。
                PreviewFieldAvailability(doc, requests);
            }

            return new
            {
                DryRun = dryRun,
                Created = requests.Count(r => r.Status == "created"),
                Planned = requests.Count(r => r.Status == "planned"),
                Skipped = requests.Count(r => r.Status == "skipped"),
                Failed = requests.Count(r => r.Status == "failed"),
                Schedules = requests.Select(r => new
                {
                    r.Name,
                    r.Category,
                    r.Status,
                    ScheduleId = r.ScheduleId,
                    AddedFields = r.Added,
                    MissingFields = r.Missing,
                    r.Note
                }).ToList()
            };
        }

        /// <summary>
        /// dry-run 用：在會回復的交易裡建出 scratch 明細表，只為了知道哪些欄位對得上。
        /// </summary>
        private void PreviewFieldAvailability(Document doc, List<ScheduleCreateRequest> requests)
        {
            using (Transaction scratch = new Transaction(doc, "明細表欄位預覽（回復）"))
            {
                scratch.Start();
                try
                {
                    foreach (ScheduleCreateRequest request in requests.Where(r => r.Status == "planned"))
                    {
                        try
                        {
                            ViewSchedule probe = ViewSchedule.CreateSchedule(doc, request.CategoryId);
                            ApplyFieldsByName(doc, probe, request.Fields, false, request);
                        }
                        catch (Exception ex)
                        {
                            request.Status = "failed";
                            request.Note = ex.Message;
                        }
                    }
                }
                finally
                {
                    scratch.RollBack();
                }
            }
        }

        #endregion

        #region add_schedule_fields

        private object AddScheduleFields(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            bool dryRun = parameters["dryRun"]?.Value<bool>() ?? false;
            var fieldNames = parameters["fields"]?.ToObject<List<string>>() ?? new List<string>();
            if (fieldNames.Count == 0)
            {
                throw new ArgumentException("add_schedule_fields requires a non-empty 'fields' list.");
            }

            var targets = new List<ViewSchedule>();
            void AddTarget(ViewSchedule schedule)
            {
                if (schedule != null && targets.All(t => t.Id != schedule.Id)) targets.Add(schedule);
            }

            if (parameters["scheduleIds"] is JArray idList)
            {
                foreach (JToken id in idList)
                {
                    AddTarget(ResolveViewSchedule(doc, id.Value<IdType>(), null));
                }
            }

            if (parameters["scheduleNames"] is JArray nameList)
            {
                foreach (JToken name in nameList)
                {
                    AddTarget(ResolveViewSchedule(doc, null, name.Value<string>()));
                }
            }

            string keyword = parameters["keyword"]?.Value<string>();
            string category = parameters["category"]?.Value<string>();
            if (!string.IsNullOrWhiteSpace(keyword) || !string.IsNullOrWhiteSpace(category))
            {
                foreach (ViewSchedule schedule in CollectUserSchedules(doc))
                {
                    if (!ScheduleMatchesKeyword(schedule.Name, keyword)) continue;
                    if (!string.IsNullOrWhiteSpace(category) &&
                        !string.Equals(GetScheduleCategoryName(doc, schedule), category.Trim(),
                            StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    AddTarget(schedule);
                }
            }

            if (targets.Count == 0)
            {
                throw new ArgumentException(
                    "No target schedule: pass scheduleIds, scheduleNames, or keyword/category that matches at least one schedule.");
            }

            var results = new List<ScheduleCreateRequest>();
            Transaction trans = null;
            if (!dryRun)
            {
                trans = new Transaction(doc, "批量新增明細表欄位");
                trans.Start();
            }

            try
            {
                foreach (ViewSchedule schedule in targets)
                {
                    var item = new ScheduleCreateRequest
                    {
                        Name = schedule.Name,
                        Category = GetScheduleCategoryName(doc, schedule),
                        ScheduleId = schedule.Id.GetIdValue(),
                        Status = dryRun ? "planned" : "updated"
                    };

                    if (dryRun)
                    {
                        ApplyFieldsByName(doc, schedule, fieldNames, false, item);
                    }
                    else
                    {
                        using (SubTransaction sub = new SubTransaction(doc))
                        {
                            sub.Start();
                            try
                            {
                                ApplyFieldsByName(doc, schedule, fieldNames, true, item);
                                sub.Commit();
                            }
                            catch (Exception ex)
                            {
                                sub.RollBack();
                                item.Status = "failed";
                                item.Added.Clear();
                                item.Note = ex.Message;
                            }
                        }
                    }

                    results.Add(item);
                }

                if (trans != null)
                {
                    if (results.Any(r => r.Status == "updated")) trans.Commit();
                    else trans.RollBack();
                }
            }
            catch
            {
                if (trans != null && trans.HasStarted() && !trans.HasEnded()) trans.RollBack();
                throw;
            }
            finally
            {
                trans?.Dispose();
            }

            return new
            {
                DryRun = dryRun,
                Updated = results.Count(r => r.Status == "updated"),
                Planned = results.Count(r => r.Status == "planned"),
                Failed = results.Count(r => r.Status == "failed"),
                Schedules = results.Select(r => new
                {
                    ScheduleId = r.ScheduleId,
                    r.Name,
                    r.Category,
                    r.Status,
                    AddedFields = r.Added,
                    AlreadyPresent = r.Already,
                    MissingFields = r.Missing,
                    r.Note
                }).ToList()
            };
        }

        #endregion

        #region set_schedule_grand_total_title

        private object SetScheduleGrandTotalTitle(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            bool dryRun = parameters["dryRun"]?.Value<bool>() ?? false;
            string template = parameters["title"]?.Value<string>();
            if (string.IsNullOrEmpty(template))
            {
                throw new ArgumentException("set_schedule_grand_total_title requires a non-empty 'title'.");
            }

            var targets = new List<ViewSchedule>();
            void AddTarget(ViewSchedule schedule)
            {
                if (schedule != null && targets.All(t => t.Id != schedule.Id)) targets.Add(schedule);
            }

            if (parameters["scheduleIds"] is JArray idList)
            {
                foreach (JToken id in idList) AddTarget(ResolveViewSchedule(doc, id.Value<IdType>(), null));
            }

            if (parameters["scheduleNames"] is JArray nameList)
            {
                foreach (JToken name in nameList) AddTarget(ResolveViewSchedule(doc, null, name.Value<string>()));
            }

            string keyword = parameters["keyword"]?.Value<string>();
            string category = parameters["category"]?.Value<string>();
            if (!string.IsNullOrWhiteSpace(keyword) || !string.IsNullOrWhiteSpace(category))
            {
                foreach (ViewSchedule schedule in CollectUserSchedules(doc))
                {
                    if (!ScheduleMatchesKeyword(schedule.Name, keyword)) continue;
                    if (!string.IsNullOrWhiteSpace(category) &&
                        !string.Equals(GetScheduleCategoryName(doc, schedule), category.Trim(),
                            StringComparison.OrdinalIgnoreCase))
                    {
                        continue;
                    }

                    AddTarget(schedule);
                }
            }

            if (targets.Count == 0)
            {
                throw new ArgumentException(
                    "No target schedule: pass scheduleIds, scheduleNames, or keyword/category that matches at least one schedule.");
            }

            // {n} = 該明細表目前實際列出的元素數（已套用篩選），與畫面上的逐項列數一致。
            // {first}/{first+k}/{last} = 逐項列「第一個欄位」讀到的編號（第一列／第一列+k／最後一列）。
            var rows = new List<object>();
            Transaction trans = null;
            if (!dryRun)
            {
                trans = new Transaction(doc, "設定明細表自訂總計標題");
                trans.Start();
            }

            try
            {
                bool anyChanged = false;
                foreach (ViewSchedule schedule in targets)
                {
                    ScheduleDefinition definition = schedule.Definition;
                    int count = new FilteredElementCollector(doc, schedule.Id).GetElementCount();
                    string oldTitle = definition.GrandTotalTitle;
                    string status = dryRun ? "planned" : "updated";
                    string note = null;
                    string newTitle = ExpandGrandTotalTemplate(schedule, template, count, out string firstText,
                        out string lastText, out string expandError);

                    if (expandError != null)
                    {
                        status = "failed";
                        note = expandError;
                        newTitle = null;
                    }
                    else if (firstText != null && lastText != null && int.TryParse(firstText, out int firstNo) &&
                             int.TryParse(lastText, out int lastNo) && lastNo != firstNo + count - 1)
                    {
                        note = "編號不連續：第一列 " + firstNo + "、最後一列 " + lastNo + "、共 " + count + " 筆";
                    }

                    if (expandError != null)
                    {
                        // 讀不到編號就不寫，避免寫出錯誤標題
                    }
                    else if (string.Equals(oldTitle, newTitle, StringComparison.Ordinal))
                    {
                        status = "unchanged";
                    }
                    else if (!dryRun)
                    {
                        try
                        {
                            definition.GrandTotalTitle = newTitle;
                            anyChanged = true;
                        }
                        catch (Exception ex)
                        {
                            status = "failed";
                            note = ex.Message;
                        }
                    }

                    rows.Add(new
                    {
                        ScheduleId = schedule.Id.GetIdValue(),
                        schedule.Name,
                        ElementCount = count,
                        FirstNumber = firstText,
                        LastNumber = lastText,
                        ShowGrandTotal = definition.ShowGrandTotal,
                        ShowGrandTotalTitle = definition.ShowGrandTotalTitle,
                        OldTitle = oldTitle,
                        NewTitle = newTitle,
                        Status = status,
                        Note = note
                    });
                }

                if (trans != null)
                {
                    if (anyChanged) trans.Commit();
                    else trans.RollBack();
                }
            }
            catch
            {
                if (trans != null && trans.HasStarted() && !trans.HasEnded()) trans.RollBack();
                throw;
            }
            finally
            {
                trans?.Dispose();
            }

            return new { DryRun = dryRun, Count = rows.Count, Schedules = rows };
        }

        private static readonly Regex GrandTotalFirstToken =
            new Regex(@"\{first(?:\+(\d+))?\}", RegexOptions.Compiled);

        /// <summary>
        /// 展開自訂總計標題樣板。{n}=列出筆數；{first}/{first+k}/{last}=逐項列第一個欄位的編號
        /// （只收純整數儲存格，合計列／標題文字會自然被略過）。樣板用到編號卻讀不到時回傳 error。
        /// </summary>
        private string ExpandGrandTotalTemplate(ViewSchedule schedule, string template, int count,
            out string firstText, out string lastText, out string error)
        {
            firstText = null;
            lastText = null;
            error = null;

            bool needsNumbers = template.Contains("{last}") || GrandTotalFirstToken.IsMatch(template);
            List<int> numbers = ReadScheduleFirstColumnNumbers(schedule);
            if (numbers.Count > 0)
            {
                firstText = numbers[0].ToString();
                lastText = numbers[numbers.Count - 1].ToString();
            }

            if (needsNumbers && numbers.Count == 0)
            {
                error = "讀不到第一個欄位的編號（逐項列第一欄沒有純整數儲存格）；標題用到 {first}/{last} 所以未寫入。";
                return null;
            }

            string result = template.Replace("{n}", count.ToString());
            if (numbers.Count > 0)
            {
                int first = numbers[0];
                result = GrandTotalFirstToken.Replace(result, m =>
                    (first + (m.Groups[1].Success ? int.Parse(m.Groups[1].Value) : 0)).ToString());
                result = result.Replace("{last}", numbers[numbers.Count - 1].ToString());
            }

            return result;
        }

        /// <summary>讀逐項列（Body）第一欄文字，保留可解析成純整數者，依畫面順序。</summary>
        private static List<int> ReadScheduleFirstColumnNumbers(ViewSchedule schedule)
        {
            var numbers = new List<int>();
            TableSectionData body = schedule.GetTableData().GetSectionData(SectionType.Body);
            if (body == null || body.NumberOfColumns < 1) return numbers;

            for (int r = body.FirstRowNumber; r < body.FirstRowNumber + body.NumberOfRows; r++)
            {
                string text = schedule.GetCellText(SectionType.Body, r, body.FirstColumnNumber);
                if (int.TryParse((text ?? "").Trim(), out int value)) numbers.Add(value);
            }

            return numbers;
        }

        #endregion

        #region 共用

        private IEnumerable<ViewSchedule> CollectUserSchedules(Document doc)
        {
            return new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSchedule))
                .Cast<ViewSchedule>()
                .Where(s => !s.IsTitleblockRevisionSchedule && !s.IsTemplate)
                .OrderBy(s => s.Name, StringComparer.OrdinalIgnoreCase);
        }

        /// <summary>空白分隔的每個詞都要出現在名稱裡（且），不分大小寫；與 pyRevit 視窗的篩選框同一套語意。</summary>
        private static bool ScheduleMatchesKeyword(string name, string keyword)
        {
            if (string.IsNullOrWhiteSpace(keyword)) return true;
            string haystack = (name ?? "").ToLowerInvariant();
            return keyword.Replace('　', ' ')
                .Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries)
                .All(term => haystack.Contains(term.ToLowerInvariant()));
        }

        private static string RenderScheduleName(string template, string category)
        {
            string name = template.Replace("{category}", category.Trim());
            return name.Contains(category.Trim()) ? name : name + category.Trim();
        }

        private static string SanitizeScheduleName(string name)
        {
            string cleaned = new string((name ?? "").Select(c =>
                Array.IndexOf(ScheduleNameForbiddenChars, c) >= 0 ? '-' : c).ToArray()).Trim();
            return cleaned.Length == 0 ? "明細表" : cleaned;
        }

        /// <summary>品類名稱（依 Revit 介面語言）或 BuiltInCategory 名稱（OST_Walls / Walls）。</summary>
        private ElementId ResolveScheduleCategoryId(Document doc, string categoryName)
        {
            foreach (Category cat in doc.Settings.Categories)
            {
                if (cat.Name.Equals(categoryName, StringComparison.OrdinalIgnoreCase)) return cat.Id;
            }

            string bicName = categoryName.StartsWith("OST_", StringComparison.OrdinalIgnoreCase)
                ? categoryName : "OST_" + categoryName;
            BuiltInCategory bic;
            if (Enum.TryParse(bicName, true, out bic))
            {
                Category cat = Category.GetCategory(doc, bic);
                if (cat != null) return cat.Id;
            }

            return ElementId.InvalidElementId;
        }

        private static string ScheduleFieldKey(ScheduleFieldType type, ElementId parameterId)
        {
            return ((int)type) + "|" + parameterId.GetIdValue();
        }

        private static string SchedulableFieldName(Document doc, SchedulableField field)
        {
            try { return field.GetName(doc); }
            catch { return null; }
        }

        /// <summary>
        /// 依名稱把欄位加到明細表。apply=false 只算結果不改動。
        /// 同名時實例參數優先；明細表上已有的欄位（同 FieldType＋ParameterId）列入 Already，不重複加。
        /// </summary>
        private void ApplyFieldsByName(Document doc, ViewSchedule schedule, IEnumerable<string> names,
            bool apply, ScheduleCreateRequest report)
        {
            ScheduleDefinition definition = schedule.Definition;
            IList<SchedulableField> schedulable = definition.GetSchedulableFields();

            var existing = new HashSet<string>();
            for (int i = 0; i < definition.GetFieldCount(); i++)
            {
                ScheduleField field = definition.GetField(i);
                existing.Add(ScheduleFieldKey(field.FieldType, field.ParameterId));
            }

            foreach (string raw in names ?? Enumerable.Empty<string>())
            {
                string name = (raw ?? "").Trim();
                if (name.Length == 0) continue;

                SchedulableField match = schedulable
                    .Where(sf => string.Equals(SchedulableFieldName(doc, sf), name, StringComparison.OrdinalIgnoreCase))
                    .OrderBy(sf => sf.FieldType == ScheduleFieldType.Instance ? 0 : 1)
                    .FirstOrDefault();

                if (match == null)
                {
                    report.Missing.Add(name);
                    continue;
                }

                string key = ScheduleFieldKey(match.FieldType, match.ParameterId);
                if (existing.Contains(key))
                {
                    report.Already.Add(name);
                    continue;
                }

                if (apply) definition.AddField(match);
                existing.Add(key);
                report.Added.Add(name);
            }
        }

        private class ScheduleCreateRequest
        {
            public string Name { get; set; }
            public string Category { get; set; }
            public ElementId CategoryId { get; set; } = ElementId.InvalidElementId;
            public List<string> Fields { get; set; } = new List<string>();
            public string Status { get; set; }
            public string Note { get; set; }
            public IdType? ScheduleId { get; set; }
            public List<string> Added { get; } = new List<string>();
            public List<string> Already { get; } = new List<string>();
            public List<string> Missing { get; } = new List<string>();
        }

        #endregion
    }
}
