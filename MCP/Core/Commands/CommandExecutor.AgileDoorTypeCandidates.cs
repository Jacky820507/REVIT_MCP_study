using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
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
        /// 以門類型為單位預覽「需求條件 -> 實際門族型」候選，不修改模型。
        /// 同一門類型若被不同房間關係的門共用，只有在所有實例得到同一候選時才會提出 proposed。
        /// </summary>
        private object PreviewDoorTypeCandidates(JObject parameters)
        {
            Document doc = GetAgileBimDocument();
            string matchField = parameters["matchField"]?.Value<string>()?.Trim().ToLowerInvariant()
                ?? "room_name";
            ValidateAgileDoorSpecMatchField(matchField);
            string sourceParameter = parameters["sourceParameter"]?.Value<string>()?.Trim();
            if (matchField == "parameter" && string.IsNullOrWhiteSpace(sourceParameter))
            {
                throw new ArgumentException(
                    "門型候選 matchField=parameter 時必須指定 sourceParameter。"
                );
            }

            List<AgileDoorTypeRule> rules = ParseAgileDoorTypeRules(
                parameters["rules"] as JArray);
            Dictionary<IdType, FamilySymbol> candidateSymbols =
                ValidateAgileDoorTypeCandidates(doc, rules);
            List<string> performanceParameters = ParseAgileDoorPerformanceParameters(
                parameters["performanceParameters"] as JArray);
            bool includeCurtain = parameters["includeCurtain"]?.Value<bool>() ?? false;
            int maxDoors = ClampAuditLimit(
                parameters["maxDoors"]?.Value<int?>(), 1, 2000, 500);
            List<AgileOpeningTarget> openings = CollectAgileOpenings(
                doc, parameters, false, includeCurtain, maxDoors, true);
            List<AgileOpeningGroup> groups = GroupAgileOpenings(openings, "type");
            List<AgileDoorTypeCandidatePlan> plans = groups
                .Select(group => BuildAgileDoorTypeCandidatePlan(
                    group, matchField, sourceParameter, rules, candidateSymbols,
                    performanceParameters,
                    parameters["caseInsensitive"]?.Value<bool>() ?? true,
                    parameters["collapseWhitespace"]?.Value<bool>() ?? true))
                .ToList();

            int maxResults = ClampAuditLimit(
                parameters["maxResults"]?.Value<int?>(), 1, 2000, 500);
            List<AgileDoorTypeCandidatePlan> returnedPlans = plans
                .Take(maxResults)
                .ToList();
            return new
            {
                Success = true,
                ReadOnly = true,
                TargetScope = "type",
                MatchField = matchField,
                SourceParameter = sourceParameter,
                PerformanceParameters = performanceParameters,
                Scope = new
                {
                    Level = parameters["level"]?.Value<string>(),
                    DoorIds = ParseAgileElementIds(parameters["doorIds"] as JArray),
                    IncludeCurtain = includeCurtain,
                    DoorsOnly = true,
                    MaxDoors = maxDoors,
                    MaxResults = maxResults
                },
                Summary = new
                {
                    TotalDoors = openings.Count,
                    CurrentTypes = groups.Count,
                    ReturnedTypes = returnedPlans.Count,
                    PlansTruncated = plans.Count > returnedPlans.Count,
                    ProposedTypes = plans.Count(plan => plan.Status == "proposed"),
                    ProposedInstances = plans
                        .Where(plan => plan.Status == "proposed")
                        .Sum(plan => plan.InstanceCount),
                    UnchangedTypes = plans.Count(plan => plan.Status == "unchanged"),
                    UnmatchedTypes = plans.Count(plan => plan.Status == "unmatched"),
                    Conflicts = plans.Count(plan => plan.Status == "conflict"),
                    Blocked = plans.Count(plan => plan.Status == "blocked")
                },
                Rules = rules.Select(rule => rule.ToResponse()).ToList(),
                DoorTypes = returnedPlans.Select(plan => plan.ToResponse()).ToList(),
                Message = "門型候選 preview 完成；本命令只讀取門、房間關係與族型參數，沒有修改模型。"
            };
        }

        private static List<AgileDoorTypeRule> ParseAgileDoorTypeRules(JArray token)
        {
            if (token == null || token.Count == 0)
            {
                throw new ArgumentException(
                    "門型候選 rules 必須是非空陣列，例如 [{\"id\":\"fire-60\",\"match\":\"F101\",\"targetTypeId\":5035089}]。"
                );
            }

            List<AgileDoorTypeRule> rules = new List<AgileDoorTypeRule>();
            for (int index = 0; index < token.Count; index++)
            {
                JObject item = token[index] as JObject;
                if (item == null)
                {
                    throw new ArgumentException(
                        "門型候選 rules 的每一項都必須是 object。索引：" + index);
                }

                string match = item["match"]?.Value<string>()
                    ?? item["contains"]?.Value<string>();
                JToken targetToken = item["targetTypeId"] ?? item["typeId"];
                IdType targetTypeId = 0;
                try { targetTypeId = targetToken?.Value<IdType>() ?? 0; }
                catch { targetTypeId = 0; }
                if (string.IsNullOrWhiteSpace(match) || targetTypeId == 0)
                {
                    throw new ArgumentException(
                        "門型候選每條規則都需要非空 match 與 targetTypeId。索引：" + index);
                }

                rules.Add(new AgileDoorTypeRule
                {
                    RuleId = item["id"]?.Value<string>()?.Trim() ?? "rule-" + (index + 1),
                    Match = NormalizeAgileRuleText(match, true),
                    TargetTypeId = targetTypeId,
                    Reason = item["reason"]?.Value<string>()?.Trim() ?? ""
                });
            }
            return rules;
        }

        private static Dictionary<IdType, FamilySymbol> ValidateAgileDoorTypeCandidates(
            Document doc, List<AgileDoorTypeRule> rules)
        {
            Dictionary<IdType, FamilySymbol> result =
                new Dictionary<IdType, FamilySymbol>();
            foreach (AgileDoorTypeRule rule in rules)
            {
                if (result.ContainsKey(rule.TargetTypeId)) continue;
                Element target = null;
                try { target = doc.GetElement(rule.TargetTypeId.ToElementId()); }
                catch { }
                FamilySymbol symbol = target as FamilySymbol;
                if (!IsAgileDoorType(symbol))
                {
                    throw new ArgumentException(
                        "targetTypeId " + rule.TargetTypeId.ToString(CultureInfo.InvariantCulture)
                        + " 不是目前專案中的門 FamilySymbol，不能作為門型候選。"
                    );
                }
                result.Add(rule.TargetTypeId, symbol);
            }
            return result;
        }

        private static bool IsAgileDoorType(FamilySymbol symbol)
        {
            try
            {
                return symbol != null
                    && symbol.Category != null
                    && symbol.Category.Id.GetIdValue() == (IdType)BuiltInCategory.OST_Doors;
            }
            catch { return false; }
        }

        private static List<string> ParseAgileDoorPerformanceParameters(JArray token)
        {
            if (token == null) return new List<string>();
            return token
                .Select(value => value.Value<string>()?.Trim())
                .Where(value => !string.IsNullOrWhiteSpace(value))
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .Take(20)
                .ToList();
        }

        private static AgileDoorTypeCandidatePlan BuildAgileDoorTypeCandidatePlan(
            AgileOpeningGroup group, string matchField, string sourceParameter,
            List<AgileDoorTypeRule> rules,
            Dictionary<IdType, FamilySymbol> candidateSymbols,
            List<string> performanceParameters,
            bool caseInsensitive, bool collapseWhitespace)
        {
            FamilySymbol currentSymbol = group.TargetElement as FamilySymbol;
            AgileDoorTypeCandidatePlan plan = new AgileDoorTypeCandidatePlan
            {
                CurrentTypeId = group.TargetElementId,
                CurrentFamilyName = group.Representative.FamilyName,
                CurrentTypeName = group.Representative.TypeName,
                Level = group.Representative.Level,
                InstanceCount = group.Records.Count,
                InstanceIds = group.Records
                    .Select(record => record.ElementId)
                    .OrderBy(id => id)
                    .ToList(),
                RoomPairs = BuildAgileDoorRoomPairs(group),
                CurrentPerformance = GetAgileDoorTypeParameterSnapshot(
                    currentSymbol, performanceParameters),
                Status = "blocked"
            };

            List<AgileDoorTypeRecordMatch> recordMatches = group.Records
                .Select(record =>
                {
                    string source = GetAgileOpeningSource(
                        record, matchField, sourceParameter);
                    return new AgileDoorTypeRecordMatch
                    {
                        Record = record,
                        SourceValue = source,
                        MatchedRules = rules
                            .Where(rule => IsAgileDoorTypeRuleMatch(
                                source, rule, caseInsensitive, collapseWhitespace))
                            .ToList()
                    };
                })
                .ToList();

            plan.SourceValue = string.Join(" / ", recordMatches
                .Select(item => item.SourceValue)
                .Where(value => !string.IsNullOrWhiteSpace(value))
                .Distinct(StringComparer.Ordinal));
            plan.RuleIds = string.Join(", ", recordMatches
                .SelectMany(item => item.MatchedRules)
                .Select(rule => rule.RuleId)
                .Distinct(StringComparer.Ordinal));

            bool anyUnmatched = recordMatches.Any(item => item.MatchedRules.Count == 0);
            bool anyMultipleTargets = recordMatches.Any(item => item.MatchedRules
                .Select(rule => rule.TargetTypeId)
                .Distinct()
                .Count() > 1);
            List<IdType> candidateTypeIds = recordMatches
                .SelectMany(item => item.MatchedRules)
                .Select(rule => rule.TargetTypeId)
                .Distinct()
                .ToList();
            if (candidateTypeIds.Count == 0)
            {
                plan.Status = "unmatched";
                plan.Reason = string.IsNullOrWhiteSpace(plan.SourceValue)
                    ? "房間/類型來源值空白或未取得；沒有規則命中。"
                    : "沒有規則命中；未提出換型候選。";
                return plan;
            }
            if (anyUnmatched || anyMultipleTargets || candidateTypeIds.Count > 1)
            {
                plan.Status = "conflict";
                plan.Reason = anyUnmatched
                    ? "同一門類型內有部分實例沒有規則命中；不能整批換型。"
                    : "同一門類型的房間/來源證據指向不同目標門型；不能整批換型。";
                return plan;
            }

            IdType candidateTypeId = candidateTypeIds[0];
            if (!candidateSymbols.TryGetValue(candidateTypeId, out FamilySymbol candidateSymbol)
                || !IsAgileDoorType(candidateSymbol))
            {
                plan.Status = "blocked";
                plan.Reason = "規則命中的 targetTypeId 不是可用的門 FamilySymbol。";
                return plan;
            }

            plan.TargetTypeId = candidateTypeId;
            plan.TargetFamilyName = SafeAgileFamilyName(candidateSymbol);
            plan.TargetTypeName = SafeAgileElementName(candidateSymbol);
            plan.TargetPerformance = GetAgileDoorTypeParameterSnapshot(
                candidateSymbol, performanceParameters);
            if (candidateTypeId == group.TargetElementId)
            {
                plan.Status = "unchanged";
                plan.Reason = "目前門類型已是規則指定的目標類型。";
            }
            else
            {
                plan.Status = "proposed";
                plan.Reason = "所有共用此門類型的實例都指向同一目標類型；可進入人工核准換型。";
            }
            return plan;
        }

        private static bool IsAgileDoorTypeRuleMatch(
            string source, AgileDoorTypeRule rule, bool caseInsensitive,
            bool collapseWhitespace)
        {
            string haystack = NormalizeAgileRuleText(source, collapseWhitespace);
            string needle = NormalizeAgileRuleText(rule.Match, collapseWhitespace);
            return haystack.IndexOf(
                needle,
                caseInsensitive ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal) >= 0;
        }

        private static List<object> GetAgileDoorTypeParameterSnapshot(
            Element element, List<string> parameterNames)
        {
            List<object> result = new List<object>();
            foreach (string parameterName in parameterNames)
            {
                Parameter parameter = ResolveAgileElementParameter(
                    element, parameterName, out bool ambiguous);
                if (ambiguous)
                {
                    result.Add(new
                    {
                        Name = parameterName,
                        Value = "",
                        Status = "名稱不唯一"
                    });
                }
                else if (parameter == null)
                {
                    result.Add(new
                    {
                        Name = parameterName,
                        Value = "",
                        Status = "找不到參數"
                    });
                }
                else
                {
                    result.Add(new
                    {
                        Name = parameterName,
                        Value = SafeAgileParameterValue(parameter),
                        Status = "ok"
                    });
                }
            }
            return result;
        }

        private static List<AgileDoorRoomPair> BuildAgileDoorRoomPairs(
            AgileOpeningGroup group)
        {
            return group.Records
                .GroupBy(record => GetAgileDoorRoomPairKey(
                    record.FromRoom, record.ToRoom), StringComparer.Ordinal)
                .Select(pair =>
                {
                    AgileOpeningTarget first = pair.First();
                    return new AgileDoorRoomPair
                    {
                        Key = pair.Key,
                        FromRoom = first.FromRoom,
                        ToRoom = first.ToRoom,
                        InstanceIds = pair
                            .Select(record => record.ElementId)
                            .OrderBy(id => id)
                            .ToList()
                    };
                })
                .OrderBy(pair => pair.Key, StringComparer.Ordinal)
                .ToList();
        }

        private static string GetAgileDoorRoomPairKey(Room fromRoom, Room toRoom)
        {
            string[] identities = {
                GetAgileDoorRoomIdentity(fromRoom),
                GetAgileDoorRoomIdentity(toRoom)
            };
            Array.Sort(identities, StringComparer.Ordinal);
            return identities[0] + "|" + identities[1];
        }

        private static string GetAgileDoorRoomIdentity(Room room)
        {
            if (room == null) return "<outside-or-unresolved>";
            try
            {
                return "room:" + room.Id.GetIdValue().ToString(CultureInfo.InvariantCulture);
            }
            catch
            {
                return "room:" + GetAgileOpeningRoomNumber(room) + ":"
                    + GetAgileOpeningRoomName(room);
            }
        }

        private sealed class AgileDoorTypeRule
        {
            public string RuleId { get; set; }
            public string Match { get; set; }
            public IdType TargetTypeId { get; set; }
            public string Reason { get; set; }

            public object ToResponse()
            {
                return new
                {
                    Id = RuleId,
                    Match,
                    TargetTypeId,
                    Reason
                };
            }
        }

        private sealed class AgileDoorTypeRecordMatch
        {
            public AgileOpeningTarget Record { get; set; }
            public string SourceValue { get; set; }
            public List<AgileDoorTypeRule> MatchedRules { get; set; }
        }

        private sealed class AgileDoorRoomPair
        {
            public string Key { get; set; }
            public Room FromRoom { get; set; }
            public Room ToRoom { get; set; }
            public List<IdType> InstanceIds { get; set; }

            public object ToResponse()
            {
                return new
                {
                    Key,
                    FromRoomId = GetAgileDoorRoomId(FromRoom),
                    FromRoomNumber = GetAgileOpeningRoomNumber(FromRoom),
                    FromRoomName = GetAgileOpeningRoomName(FromRoom),
                    ToRoomId = GetAgileDoorRoomId(ToRoom),
                    ToRoomNumber = GetAgileOpeningRoomNumber(ToRoom),
                    ToRoomName = GetAgileOpeningRoomName(ToRoom),
                    InstanceIds
                };
            }
        }

        private static IdType GetAgileDoorRoomId(Room room)
        {
            try { return room == null ? (IdType)0 : room.Id.GetIdValue(); }
            catch { return (IdType)0; }
        }

        private sealed class AgileDoorTypeCandidatePlan
        {
            public IdType CurrentTypeId { get; set; }
            public string CurrentFamilyName { get; set; }
            public string CurrentTypeName { get; set; }
            public string Level { get; set; }
            public int InstanceCount { get; set; }
            public List<IdType> InstanceIds { get; set; }
            public List<AgileDoorRoomPair> RoomPairs { get; set; }
            public string SourceValue { get; set; }
            public string RuleIds { get; set; }
            public List<object> CurrentPerformance { get; set; }
            public IdType TargetTypeId { get; set; }
            public string TargetFamilyName { get; set; }
            public string TargetTypeName { get; set; }
            public List<object> TargetPerformance { get; set; }
            public string Status { get; set; }
            public string Reason { get; set; }

            public object ToResponse()
            {
                return new
                {
                    CurrentTypeId,
                    CurrentFamily = CurrentFamilyName,
                    CurrentType = CurrentTypeName,
                    Level,
                    InstanceCount,
                    InstanceIds,
                    RoomPairs = RoomPairs.Select(pair => pair.ToResponse()).ToList(),
                    SourceValue,
                    RuleIds,
                    CurrentPerformance,
                    TargetTypeId,
                    TargetFamily = TargetFamilyName,
                    TargetType = TargetTypeName,
                    TargetPerformance,
                    Status,
                    Reason
                };
            }
        }
    }
}
