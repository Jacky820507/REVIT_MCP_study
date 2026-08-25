using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Architecture;
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
        /// <summary>
        /// Read-only inventory of the parameters actually exposed by Room elements.
        /// The result is a dictionary for later rule authoring; it never guesses a
        /// project parameter name and never opens a transaction.
        /// </summary>
        private object GetRoomParameterDictionary(JObject parameters)
        {
            Document doc = GetAgileBimDocument();
            string levelName = parameters["level"]?.Value<string>();
            bool includeUnplaced = parameters["includeUnplaced"]?.Value<bool>() ?? true;
            bool includeValues = parameters["includeValues"]?.Value<bool>() ?? false;
            int maxRooms = ClampAuditLimit(parameters["maxRooms"]?.Value<int?>(), 1, 500, 200);
            int maxParameters = ClampAuditLimit(parameters["maxParameters"]?.Value<int?>(), 1, 1000, 500);
            int maxSamplesPerParameter = ClampAuditLimit(
                parameters["maxSamplesPerParameter"]?.Value<int?>(), 0, 20, 5);

            List<IdType> explicitRoomIds = ParseAgileRoomIds(parameters["roomIds"] as JArray);
            List<Room> allRooms = ResolveAgileAuditRooms(
                doc, levelName, explicitRoomIds, true, includeUnplaced);
            List<Room> rooms = allRooms.Take(maxRooms).ToList();

            HashSet<string> requestedNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            JArray requestedParameterNames = parameters["parameterNames"] as JArray;
            if (requestedParameterNames != null)
            {
                foreach (JToken token in requestedParameterNames)
                {
                    string name = token.Value<string>()?.Trim();
                    if (!string.IsNullOrWhiteSpace(name)) requestedNames.Add(name);
                }
            }

            Dictionary<string, AgileRoomParameterEntry> entries =
                new Dictionary<string, AgileRoomParameterEntry>(StringComparer.OrdinalIgnoreCase);
            foreach (Room room in rooms)
            {
                foreach (Parameter parameter in room.Parameters)
                {
                    if (parameter?.Definition == null) continue;
                    string name = parameter.Definition.Name?.Trim();
                    if (string.IsNullOrWhiteSpace(name)) continue;
                    if (requestedNames.Count > 0 && !requestedNames.Contains(name)) continue;

                    if (!entries.TryGetValue(name, out AgileRoomParameterEntry entry))
                    {
                        entry = new AgileRoomParameterEntry(name);
                        entries[name] = entry;
                    }

                    entry.Add(room, parameter, includeValues, maxSamplesPerParameter);
                }
            }

            List<AgileRoomParameterEntry> returnedEntries = entries.Values
                .OrderBy(entry => entry.Name, StringComparer.OrdinalIgnoreCase)
                .Take(maxParameters)
                .ToList();

            return new
            {
                Success = true,
                Scope = new
                {
                    Level = levelName,
                    RoomIds = explicitRoomIds,
                    IncludeUnplaced = includeUnplaced,
                    IncludeValues = includeValues,
                    MaxRooms = maxRooms,
                    MaxParameters = maxParameters,
                    MaxSamplesPerParameter = maxSamplesPerParameter
                },
                Summary = new
                {
                    TotalRooms = allRooms.Count,
                    SampledRooms = rooms.Count,
                    RoomsTruncated = allRooms.Count > rooms.Count,
                    DiscoveredParameters = entries.Count,
                    ReturnedParameters = returnedEntries.Count,
                    ParametersTruncated = entries.Count > returnedEntries.Count
                },
                Parameters = returnedEntries.Select(entry => entry.ToResponse()).ToList(),
                Message = "唯讀參數字典完成；請使用回傳的實際 Name、StorageType 與 IsReadOnly 撰寫分類規則。"
            };
        }

        private object PreviewRoomClassification(JObject parameters)
        {
            return BuildAgileRoomClassification(parameters, false);
        }

        private object ApplyRoomClassification(JObject parameters)
        {
            if (!(parameters["confirm"]?.Value<bool>() ?? false))
            {
                throw new ArgumentException(
                    "apply_room_classification 需要明確傳入 confirm=true；先呼叫 preview_room_classification。"
                );
            }

            string mode = parameters["mode"]?.Value<string>()?.Trim().ToLowerInvariant();
            if (mode != "fill_blank" && mode != "overwrite")
            {
                throw new ArgumentException(
                    "apply_room_classification 的 mode 必須是 fill_blank 或 overwrite。"
                );
            }

            return BuildAgileRoomClassification(parameters, true);
        }

        private object BuildAgileRoomClassification(JObject parameters, bool apply)
        {
            Document doc = GetAgileBimDocument();
            string targetParameter = parameters["targetParameter"]?.Value<string>()?.Trim();
            if (string.IsNullOrWhiteSpace(targetParameter))
            {
                throw new ArgumentException(
                    "targetParameter 是必要欄位；請先用 get_room_parameter_dictionary 確認實際名稱。"
                );
            }

            string matchField = parameters["matchField"]?.Value<string>()?.Trim().ToLowerInvariant()
                ?? "name";
            if (matchField != "name" && matchField != "number"
                && matchField != "department" && matchField != "parameter")
            {
                throw new ArgumentException(
                    "matchField 必須是 name、number、department 或 parameter。"
                );
            }

            string sourceParameter = parameters["sourceParameter"]?.Value<string>()?.Trim();
            if (matchField == "parameter" && string.IsNullOrWhiteSpace(sourceParameter))
            {
                throw new ArgumentException(
                    "matchField=parameter 時必須指定 sourceParameter。"
                );
            }

            bool includeUnplaced = parameters["includeUnplaced"]?.Value<bool>() ?? false;
            bool includeUnnamed = parameters["includeUnnamed"]?.Value<bool>() ?? true;
            bool caseInsensitive = parameters["caseInsensitive"]?.Value<bool>() ?? true;
            bool collapseWhitespace = parameters["collapseWhitespace"]?.Value<bool>() ?? true;
            int maxRooms = ClampAuditLimit(parameters["maxRooms"]?.Value<int?>(), 1, 1000, 500);
            int maxResults = ClampAuditLimit(parameters["maxResults"]?.Value<int?>(), 1, 1000, 500);

            List<AgileRoomClassificationRule> rules =
                ParseAgileRoomClassificationRules(parameters["rules"] as JArray,
                    collapseWhitespace);
            List<IdType> explicitRoomIds = ParseAgileRoomIds(parameters["roomIds"] as JArray);
            List<Room> allRooms = ResolveAgileAuditRooms(
                doc, parameters["level"]?.Value<string>(), explicitRoomIds,
                includeUnnamed, includeUnplaced);
            List<Room> rooms = allRooms.Take(maxRooms).ToList();

            List<AgileRoomClassificationPlan> plans = rooms
                .Select(room => BuildAgileRoomClassificationPlan(
                    room, targetParameter, matchField, sourceParameter, rules,
                    caseInsensitive, collapseWhitespace))
                .ToList();

            string mode = apply
                ? parameters["mode"]?.Value<string>()?.Trim().ToLowerInvariant()
                : "preview";
            int plannedChanges = plans.Count(plan => plan.Status == "proposed");
            int appliedChanges = 0;
            int skippedExisting = 0;
            List<object> failures = new List<object>();

            if (apply)
            {
                List<AgileRoomClassificationPlan> writePlans = new List<AgileRoomClassificationPlan>();
                foreach (AgileRoomClassificationPlan plan in plans)
                {
                    if (plan.Status != "proposed") continue;
                    if (mode == "fill_blank" && !plan.IsBlank)
                    {
                        plan.Status = "skipped_existing";
                        plan.Reason = "fill_blank 保留既有值。";
                        skippedExisting++;
                        continue;
                    }
                    writePlans.Add(plan);
                }

                if (writePlans.Count > 0)
                {
                    using (Transaction trans = new Transaction(doc, "套用房間分類"))
                    {
                        trans.Start();
                        FailureHandlingOptions failureOptions = trans.GetFailureHandlingOptions();
                        failureOptions.SetFailuresPreprocessor(new DismissWarningsPreprocessor());
                        trans.SetFailureHandlingOptions(failureOptions);

                        foreach (AgileRoomClassificationPlan plan in writePlans)
                        {
                            Parameter parameter = ResolveAgileRoomParameter(
                                plan.Room, targetParameter, out bool ambiguous);
                            if (parameter == null || ambiguous)
                            {
                                failures.Add(new
                                {
                                    plan.ElementId,
                                    plan.Number,
                                    Error = ambiguous
                                        ? "目標參數名稱不唯一。"
                                        : "找不到目標參數。"
                                });
                                continue;
                            }

                            if (parameter.IsReadOnly || parameter.StorageType != StorageType.String)
                            {
                                failures.Add(new
                                {
                                    plan.ElementId,
                                    plan.Number,
                                    Error = parameter.IsReadOnly
                                        ? "目標參數是唯讀的。"
                                        : "房間分類目前只支援 String 參數。"
                                });
                                continue;
                            }

                            try
                            {
                                if (parameter.Set(plan.ProposedValue))
                                {
                                    appliedChanges++;
                                    plan.Status = "applied";
                                    plan.Reason = "已在單一 Transaction 寫入。";
                                }
                                else
                                {
                                    failures.Add(new
                                    {
                                        plan.ElementId,
                                        plan.Number,
                                        Error = "Revit 回傳 false，未能寫入參數。"
                                    });
                                }
                            }
                            catch (Exception ex)
                            {
                                failures.Add(new
                                {
                                    plan.ElementId,
                                    plan.Number,
                                    Error = ex.Message
                                });
                            }
                        }

                        if (failures.Count > 0)
                        {
                            trans.RollBack();
                            throw new Exception(
                                "房間分類寫入失敗，已回復整批變更："
                                + JArray.FromObject(failures).ToString());
                        }

                        trans.Commit();
                    }
                }
            }

            List<AgileRoomClassificationPlan> returnedPlans = plans
                .Take(maxResults)
                .ToList();
            return new
            {
                Success = true,
                Applied = apply,
                Mode = mode,
                TargetParameter = targetParameter,
                MatchField = matchField,
                SourceParameter = sourceParameter,
                RuleCount = rules.Count,
                Scope = new
                {
                    Level = parameters["level"]?.Value<string>(),
                    RoomIds = explicitRoomIds,
                    IncludeUnnamed = includeUnnamed,
                    IncludeUnplaced = includeUnplaced,
                    CaseInsensitive = caseInsensitive,
                    CollapseWhitespace = collapseWhitespace,
                    MaxRooms = maxRooms,
                    MaxResults = maxResults
                },
                Summary = new
                {
                    TotalRooms = allRooms.Count,
                    SampledRooms = rooms.Count,
                    RoomsTruncated = allRooms.Count > rooms.Count,
                    ReturnedPlans = returnedPlans.Count,
                    PlansTruncated = plans.Count > returnedPlans.Count,
                    Proposed = plannedChanges,
                    AppliedChanges = appliedChanges,
                    SkippedExisting = skippedExisting,
                    Unchanged = plans.Count(plan => plan.Status == "unchanged"),
                    Unmatched = plans.Count(plan => plan.Status == "unmatched"),
                    Conflicts = plans.Count(plan => plan.Status == "conflict"),
                    Blocked = plans.Count(plan => plan.Status == "blocked")
                },
                Rules = rules.Select(rule => rule.ToResponse()).ToList(),
                Rooms = returnedPlans.Select(plan => plan.ToResponse()).ToList(),
                Message = apply
                    ? "房間分類已依確認模式處理；請重新查詢模型驗證實際值。"
                    : "房間分類 preview 完成；本命令沒有修改模型。"
            };
        }

        private List<AgileRoomClassificationRule> ParseAgileRoomClassificationRules(
            JArray token,
            bool collapseWhitespace)
        {
            if (token == null || token.Count == 0)
            {
                throw new ArgumentException(
                    "rules 必須是非空陣列，例如 [{\"id\":\"office\",\"match\":\"辦公\",\"value\":\"OFFICE\"}]。"
                );
            }

            List<AgileRoomClassificationRule> rules = new List<AgileRoomClassificationRule>();
            for (int index = 0; index < token.Count; index++)
            {
                JObject item = token[index] as JObject;
                if (item == null)
                {
                    throw new ArgumentException("rules 的每一項都必須是 object。索引：" + index);
                }

                string match = item["match"]?.Value<string>()
                    ?? item["contains"]?.Value<string>();
                string value = item["value"]?.Value<string>()
                    ?? item["proposedValue"]?.Value<string>();
                if (string.IsNullOrWhiteSpace(match) || value == null)
                {
                    throw new ArgumentException(
                        "每條分類規則都需要非空 match 與 value。索引：" + index);
                }

                string normalizedMatch = NormalizeAgileClassificationText(
                    match, collapseWhitespace);
                if (string.IsNullOrWhiteSpace(normalizedMatch))
                {
                    throw new ArgumentException("分類規則的 match 不可在正規化後變成空白。索引：" + index);
                }

                rules.Add(new AgileRoomClassificationRule
                {
                    RuleId = item["id"]?.Value<string>()?.Trim()
                        ?? "rule-" + (index + 1),
                    Match = normalizedMatch,
                    Value = value.Trim()
                });
            }

            return rules;
        }

        private AgileRoomClassificationPlan BuildAgileRoomClassificationPlan(
            Room room,
            string targetParameter,
            string matchField,
            string sourceParameter,
            List<AgileRoomClassificationRule> rules,
            bool caseInsensitive,
            bool collapseWhitespace)
        {
            AgileRoomClassificationPlan plan = new AgileRoomClassificationPlan
            {
                Room = room,
                ElementId = room.Id.GetIdValue(),
                Number = room.Number ?? "",
                Name = GetAgileAuditRoomName(room),
                Level = SafeAgileAuditLevelName(_uiApp.ActiveUIDocument.Document, room),
                Status = "blocked"
            };

            Parameter target = ResolveAgileRoomParameter(room, targetParameter, out bool targetAmbiguous);
            if (target == null || targetAmbiguous)
            {
                plan.Reason = targetAmbiguous
                    ? "目標參數名稱不唯一；請改用參數字典的實際名稱或縮小 scope。"
                    : "找不到目標參數；請先用 get_room_parameter_dictionary 確認名稱。";
                return plan;
            }

            if (target.IsReadOnly)
            {
                plan.Reason = "目標參數是唯讀的。";
                return plan;
            }

            if (target.StorageType != StorageType.String)
            {
                plan.Reason = "房間分類目前只支援 String 參數；請先確認 StorageType。";
                return plan;
            }

            plan.CurrentValue = GetAgileParameterDisplayValue(target);
            plan.IsBlank = string.IsNullOrWhiteSpace(plan.CurrentValue);

            string sourceValue;
            string sourceError;
            if (!TryGetAgileRoomClassificationSource(
                    room, matchField, sourceParameter, out sourceValue, out sourceError))
            {
                plan.Reason = sourceError;
                return plan;
            }

            plan.SourceValue = sourceValue;
            string normalizedSource = NormalizeAgileClassificationText(
                sourceValue, collapseWhitespace);
            StringComparison comparison = caseInsensitive
                ? StringComparison.OrdinalIgnoreCase
                : StringComparison.Ordinal;

            List<AgileRoomClassificationRule> matchedRules = rules
                .Where(rule => normalizedSource.IndexOf(rule.Match, comparison) >= 0)
                .ToList();
            List<string> proposedValues = matchedRules
                .Select(rule => rule.Value)
                .Distinct(StringComparer.Ordinal)
                .ToList();

            plan.RuleIds = matchedRules.Count == 0
                ? ""
                : string.Join(", ", matchedRules.Select(rule => rule.RuleId));
            if (matchedRules.Count == 0)
            {
                plan.Status = "unmatched";
                plan.Reason = "沒有規則命中；保留原值。";
                return plan;
            }

            if (proposedValues.Count > 1)
            {
                plan.Status = "conflict";
                plan.Reason = "多條規則命中且 proposed value 不一致。";
                return plan;
            }

            plan.ProposedValue = proposedValues[0];
            if (string.Equals(plan.CurrentValue, plan.ProposedValue, StringComparison.Ordinal))
            {
                plan.Status = "unchanged";
                plan.Reason = "既有值已符合命中規則。";
            }
            else
            {
                plan.Status = "proposed";
                plan.Reason = "規則命中，可依 fill_blank 或 overwrite 處理。";
            }

            return plan;
        }

        private bool TryGetAgileRoomClassificationSource(
            Room room,
            string matchField,
            string sourceParameter,
            out string sourceValue,
            out string error)
        {
            sourceValue = "";
            error = null;
            switch (matchField)
            {
                case "name":
                    sourceValue = GetAgileAuditRoomName(room);
                    return true;
                case "number":
                    sourceValue = room.Number ?? "";
                    return true;
                case "department":
                    sourceValue = room.get_Parameter(BuiltInParameter.ROOM_DEPARTMENT)?.AsString() ?? "";
                    return true;
                case "parameter":
                    Parameter source = ResolveAgileRoomParameter(room, sourceParameter, out bool ambiguous);
                    if (source == null || ambiguous)
                    {
                        error = ambiguous
                            ? "來源參數名稱不唯一。"
                            : "找不到來源參數：" + sourceParameter;
                        return false;
                    }
                    sourceValue = GetAgileParameterDisplayValue(source);
                    return true;
                default:
                    error = "不支援的 matchField：" + matchField;
                    return false;
            }
        }

        private static Parameter ResolveAgileRoomParameter(
            Room room,
            string parameterName,
            out bool ambiguous)
        {
            ambiguous = false;
            if (room == null || string.IsNullOrWhiteSpace(parameterName)) return null;

            string requested = parameterName.Trim();
            List<Parameter> exactMatches = room.Parameters
                .Cast<Parameter>()
                .Where(parameter => parameter?.Definition != null
                    && string.Equals(
                        parameter.Definition.Name?.Trim(),
                        requested,
                        StringComparison.OrdinalIgnoreCase))
                .ToList();
            if (exactMatches.Count > 1)
            {
                ambiguous = true;
                return null;
            }
            if (exactMatches.Count == 1) return exactMatches[0];

            Parameter alias = ResolveAgileRoomBuiltInParameter(room, requested);
            if (alias != null) return alias;

            // LookupParameter supports project-local names that are not present in
            // the built-in aliases above. It is only used after exact enumeration,
            // so the dictionary remains the source of truth for ambiguous names.
            return room.LookupParameter(requested);
        }

        private static Parameter ResolveAgileRoomBuiltInParameter(Room room, string parameterName)
        {
            switch (parameterName.ToUpperInvariant())
            {
                case "ROOM_NAME":
                    return room.get_Parameter(BuiltInParameter.ROOM_NAME);
                case "ROOM_NUMBER":
                    return room.get_Parameter(BuiltInParameter.ROOM_NUMBER);
                case "ROOM_DEPARTMENT":
                    return room.get_Parameter(BuiltInParameter.ROOM_DEPARTMENT);
                default:
                    return null;
            }
        }

        private static string GetAgileParameterDisplayValue(Parameter parameter)
        {
            if (parameter == null) return "";
            try
            {
                return parameter.StorageType == StorageType.String
                    ? parameter.AsString() ?? ""
                    : parameter.AsValueString() ?? "";
            }
            catch
            {
                return "";
            }
        }

        private static string NormalizeAgileClassificationText(string value, bool collapseWhitespace)
        {
            string normalized = (value ?? "").Trim();
            return collapseWhitespace
                ? Regex.Replace(normalized, @"\s+", " ")
                : normalized;
        }

        private static List<IdType> ParseAgileRoomIds(JArray token)
        {
            if (token == null) return null;
            return token
                .Select(value => value.Value<IdType>())
                .Where(id => id != 0)
                .Distinct()
                .ToList();
        }

        private Document GetAgileBimDocument()
        {
            if (_uiApp?.ActiveUIDocument == null)
            {
                throw new Exception("沒有作用中的 Revit 文件，無法執行 Agile BIM 房間資料工作流。");
            }
            return _uiApp.ActiveUIDocument.Document;
        }

        private sealed class AgileRoomParameterEntry
        {
            public AgileRoomParameterEntry(string name)
            {
                Name = name;
            }

            public string Name { get; }
            public HashSet<IdType> ParameterIds { get; } = new HashSet<IdType>();
            public HashSet<string> StorageTypes { get; } =
                new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            public int SampleCount { get; private set; }
            public int WritableSampleCount { get; private set; }
            public int ReadOnlySampleCount { get; private set; }
            public List<object> Samples { get; } = new List<object>();

            public void Add(Room room, Parameter parameter, bool includeValues, int maxSamples)
            {
                if (parameter.Id != null) ParameterIds.Add(parameter.Id.GetIdValue());
                StorageTypes.Add(parameter.StorageType.ToString());
                SampleCount++;
                if (parameter.IsReadOnly) ReadOnlySampleCount++;
                else WritableSampleCount++;

                if (includeValues && Samples.Count < maxSamples)
                {
                    Samples.Add(new
                    {
                        ElementId = room.Id.GetIdValue(),
                        Number = room.Number ?? "",
                        Value = GetAgileParameterDisplayValue(parameter),
                        HasValue = parameter.HasValue,
                        IsReadOnly = parameter.IsReadOnly
                    });
                }
            }

            public object ToResponse()
            {
                return new
                {
                    Name,
                    ParameterIds = ParameterIds.OrderBy(id => id).ToList(),
                    StorageTypes = StorageTypes.OrderBy(value => value).ToList(),
                    SampleCount,
                    WritableSampleCount,
                    ReadOnlySampleCount,
                    Samples = Samples.Count == 0 ? null : Samples
                };
            }
        }

        private sealed class AgileRoomClassificationRule
        {
            public string RuleId { get; set; }
            public string Match { get; set; }
            public string Value { get; set; }

            public object ToResponse()
            {
                return new
                {
                    Id = RuleId,
                    Match,
                    Value
                };
            }
        }

        private sealed class AgileRoomClassificationPlan
        {
            public Room Room { get; set; }
            public IdType ElementId { get; set; }
            public string Number { get; set; }
            public string Name { get; set; }
            public string Level { get; set; }
            public string SourceValue { get; set; } = "";
            public string CurrentValue { get; set; } = "";
            public string ProposedValue { get; set; } = "";
            public string RuleIds { get; set; } = "";
            public string Status { get; set; }
            public string Reason { get; set; }
            public bool IsBlank { get; set; }

            public object ToResponse()
            {
                return new
                {
                    ElementId,
                    Number,
                    Name,
                    Level,
                    SourceValue,
                    CurrentValue,
                    ProposedValue,
                    RuleIds,
                    Status,
                    Reason
                };
            }
        }
    }
}
