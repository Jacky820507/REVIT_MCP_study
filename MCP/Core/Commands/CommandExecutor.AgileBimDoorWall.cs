using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
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
        private object PreviewDoorSpecifications(JObject parameters)
        {
            return BuildAgileDoorSpecifications(parameters, false);
        }

        private object ApplyDoorSpecifications(JObject parameters)
        {
            RequireAgileConfirmation(parameters, "apply_door_specifications");
            RequireAgileMode(parameters, "apply_door_specifications");
            return BuildAgileDoorSpecifications(parameters, true);
        }

        private object PreviewDoorWindowNumbering(JObject parameters)
        {
            return BuildAgileDoorWindowNumbering(parameters, false);
        }

        private object ApplyDoorWindowNumbering(JObject parameters)
        {
            RequireAgileConfirmation(parameters, "apply_door_window_numbering");
            RequireAgileMode(parameters, "apply_door_window_numbering");
            return BuildAgileDoorWindowNumbering(parameters, true);
        }

        private object PreviewWallPerformanceClassification(JObject parameters)
        {
            return BuildAgileWallPerformanceClassification(parameters, false);
        }

        private object ApplyWallPerformanceClassification(JObject parameters)
        {
            RequireAgileConfirmation(parameters, "apply_wall_performance_classification");
            RequireAgileMode(parameters, "apply_wall_performance_classification");
            return BuildAgileWallPerformanceClassification(parameters, true);
        }

        private static void RequireAgileConfirmation(JObject parameters, string commandName)
        {
            if (!(parameters["confirm"]?.Value<bool>() ?? false))
            {
                throw new ArgumentException(
                    commandName + " 需要明確傳入 confirm=true；請先呼叫對應的 preview 工具。"
                );
            }
        }

        private static string RequireAgileMode(JObject parameters, string commandName)
        {
            string mode = parameters["mode"]?.Value<string>()?.Trim().ToLowerInvariant();
            if (mode != "fill_blank" && mode != "overwrite")
            {
                throw new ArgumentException(
                    commandName + " 的 mode 必須是 fill_blank 或 overwrite。"
                );
            }
            return mode;
        }

        private object BuildAgileDoorSpecifications(JObject parameters, bool apply)
        {
            Document doc = GetAgileBimDocument();
            string targetParameter = RequireAgileTargetParameter(
                parameters, "門規格");
            string targetScope = ParseAgileTargetScope(parameters["targetScope"], "type");
            string matchField = parameters["matchField"]?.Value<string>()?.Trim().ToLowerInvariant()
                ?? "type";
            ValidateAgileDoorSpecMatchField(matchField);
            string sourceParameter = parameters["sourceParameter"]?.Value<string>()?.Trim();
            if (matchField == "parameter" && string.IsNullOrWhiteSpace(sourceParameter))
            {
                throw new ArgumentException(
                    "門規格 matchField=parameter 時必須指定 sourceParameter。"
                );
            }

            bool includeCurtain = parameters["includeCurtain"]?.Value<bool>() ?? false;
            int maxDoors = ClampAuditLimit(parameters["maxDoors"]?.Value<int?>(), 1, 2000, 500);
            List<AgileMatchRule> rules = ParseAgileMatchRules(
                parameters["rules"] as JArray, "門規格");
            List<AgileOpeningTarget> openings = CollectAgileOpenings(
                doc, parameters, false, includeCurtain, maxDoors, true);
            List<AgileOpeningGroup> groups = GroupAgileOpenings(openings, targetScope);
            List<AgileDoorSpecPlan> plans = groups
                .Select(group => BuildAgileDoorSpecPlan(
                    group, targetParameter, matchField, sourceParameter, rules,
                    parameters["caseInsensitive"]?.Value<bool>() ?? true,
                    parameters["collapseWhitespace"]?.Value<bool>() ?? true))
                .ToList();

            string mode = apply ? RequireAgileMode(parameters, "apply_door_specifications") : "preview";
            int appliedChanges = 0;
            int skippedExisting = 0;
            List<object> failures = new List<object>();
            if (apply)
            {
                List<AgileDoorSpecPlan> writePlans = FilterAgileWritePlans(
                    plans, mode, ref skippedExisting);
                ApplyAgileDoorSpecWrites(
                    doc, writePlans, targetParameter, failures, ref appliedChanges);
            }

            int maxResults = ClampAuditLimit(
                parameters["maxResults"]?.Value<int?>(), 1, 2000, 500);
            List<AgileDoorSpecPlan> returnedPlans = plans.Take(maxResults).ToList();
            return new
            {
                Success = true,
                Applied = apply,
                Mode = mode,
                TargetParameter = targetParameter,
                TargetScope = targetScope,
                MatchField = matchField,
                SourceParameter = sourceParameter,
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
                    Targets = groups.Count,
                    ReturnedPlans = returnedPlans.Count,
                    PlansTruncated = plans.Count > returnedPlans.Count,
                    Proposed = plans.Count(plan => plan.Status == "proposed"),
                    AppliedChanges = appliedChanges,
                    SkippedExisting = skippedExisting,
                    Unchanged = plans.Count(plan => plan.Status == "unchanged"),
                    Unmatched = plans.Count(plan => plan.Status == "unmatched"),
                    Conflicts = plans.Count(plan => plan.Status == "conflict"),
                    Blocked = plans.Count(plan => plan.Status == "blocked")
                },
                Rules = rules.Select(rule => rule.ToResponse()).ToList(),
                Doors = returnedPlans.Select(plan => plan.ToResponse()).ToList(),
                Failures = failures,
                Message = apply
                    ? "門規格已依確認模式處理；請重新查詢模型驗證實際值。"
                    : "門規格 preview 完成；本命令沒有修改模型。"
            };
        }

        private object BuildAgileDoorWindowNumbering(JObject parameters, bool apply)
        {
            Document doc = GetAgileBimDocument();
            string targetParameter = RequireAgileTargetParameter(
                parameters, "門窗編號");
            string targetScope = ParseAgileTargetScope(parameters["targetScope"], "instance");
            string source = parameters["source"]?.Value<string>()?.Trim().ToLowerInvariant()
                ?? "sequence";
            ValidateAgileNumberingSource(source);
            string sequenceScope = parameters["sequenceScope"]?.Value<string>()
                ?.Trim().ToLowerInvariant() ?? "category";
            ValidateAgileSequenceScope(sequenceScope);
            string sourceParameter = parameters["sourceParameter"]?.Value<string>()?.Trim();
            if (source == "parameter" && string.IsNullOrWhiteSpace(sourceParameter))
            {
                throw new ArgumentException(
                    "門窗編號 source=parameter 時必須指定 sourceParameter。"
                );
            }

            bool includeCurtain = parameters["includeCurtain"]?.Value<bool>() ?? false;
            List<AgileOpeningTarget> selected = CollectAgileOpenings(
                doc, parameters, false, includeCurtain, 2000);
            List<AgileOpeningTarget> allOpenings = CollectAgileOpenings(
                doc, parameters, true, includeCurtain, 0);
            List<AgileOpeningGroup> allGroups = GroupAgileOpenings(allOpenings, targetScope);
            HashSet<string> selectedKeys = new HashSet<string>(
                GroupAgileOpenings(selected, targetScope).Select(GetAgileOpeningGroupKey),
                StringComparer.Ordinal);
            List<AgileOpeningGroup> groups = allGroups
                .Where(group => selectedKeys.Contains(GetAgileOpeningGroupKey(group)))
                .ToList();

            string mode = apply
                ? RequireAgileMode(parameters, "apply_door_window_numbering")
                : "fill_blank";
            List<AgileNumberingPlan> plans = BuildAgileNumberingPlans(
                groups, allGroups, targetParameter, source, sourceParameter,
                sequenceScope, mode, parameters);

            int appliedChanges = 0;
            int skippedExisting = plans.Count(plan => plan.Status == "unchanged");
            List<object> failures = new List<object>();
            if (apply)
            {
                List<AgileNumberingPlan> writePlans = plans
                    .Where(plan => plan.Status == "proposed")
                    .ToList();
                ApplyAgileNumberingWrites(
                    doc, writePlans, targetParameter, failures, ref appliedChanges);
            }

            int maxResults = ClampAuditLimit(
                parameters["maxResults"]?.Value<int?>(), 1, 3000, 1000);
            List<AgileNumberingPlan> returnedPlans = plans.Take(maxResults).ToList();
            return new
            {
                Success = true,
                Applied = apply,
                Mode = apply ? mode : "preview",
                TargetParameter = targetParameter,
                TargetScope = targetScope,
                Source = source,
                SourceParameter = sourceParameter,
                SequenceScope = sequenceScope,
                Scope = new
                {
                    Level = parameters["level"]?.Value<string>(),
                    ElementIds = ParseAgileElementIds(parameters["elementIds"] as JArray),
                    IncludeCurtain = includeCurtain,
                    SelectedOpenings = selected.Count,
                    AllOpenings = allOpenings.Count
                },
                Summary = new
                {
                    SelectedTargets = groups.Count,
                    ReturnedPlans = returnedPlans.Count,
                    PlansTruncated = plans.Count > returnedPlans.Count,
                    Proposed = plans.Count(plan => plan.Status == "proposed"),
                    AppliedChanges = appliedChanges,
                    Unchanged = skippedExisting,
                    Blocked = plans.Count(plan => plan.Status == "blocked"),
                    Collisions = plans.Count(plan => plan.Status == "collision")
                },
                Openings = returnedPlans.Select(plan => plan.ToResponse()).ToList(),
                Failures = failures,
                Message = apply
                    ? "門窗編號已依確認模式處理；請重新查詢模型驗證實際值。"
                    : "門窗編號 preview 完成；本命令沒有修改模型。"
            };
        }

        private object BuildAgileWallPerformanceClassification(JObject parameters, bool apply)
        {
            Document doc = GetAgileBimDocument();
            string targetParameter = RequireAgileTargetParameter(
                parameters, "牆性能分類");
            string targetScope = ParseAgileTargetScope(parameters["targetScope"], "instance");
            string matchField = parameters["matchField"]?.Value<string>()?.Trim().ToLowerInvariant()
                ?? "type";
            ValidateAgileWallMatchField(matchField);
            string sourceParameter = parameters["sourceParameter"]?.Value<string>()?.Trim();
            if (matchField == "parameter" && string.IsNullOrWhiteSpace(sourceParameter))
            {
                throw new ArgumentException(
                    "牆性能分類 matchField=parameter 時必須指定 sourceParameter。"
                );
            }

            bool includeCurtain = parameters["includeCurtain"]?.Value<bool>() ?? false;
            int maxWalls = ClampAuditLimit(parameters["maxWalls"]?.Value<int?>(), 1, 5000, 1000);
            List<AgileMatchRule> rules = ParseAgileMatchRules(
                parameters["rules"] as JArray, "牆性能分類");
            List<AgileWallTarget> walls = CollectAgileWalls(
                doc, parameters, includeCurtain, maxWalls,
                matchField == "room_name" || matchField == "room_number");
            List<AgileWallGroup> groups = GroupAgileWalls(walls, targetScope);
            List<AgileWallPlan> plans = groups
                .Select(group => BuildAgileWallPlan(
                    group, targetParameter, matchField, sourceParameter, rules,
                    parameters["caseInsensitive"]?.Value<bool>() ?? true,
                    parameters["collapseWhitespace"]?.Value<bool>() ?? true))
                .ToList();

            string mode = apply ? RequireAgileMode(parameters, "apply_wall_performance_classification") : "preview";
            int appliedChanges = 0;
            int skippedExisting = 0;
            List<object> failures = new List<object>();
            if (apply)
            {
                List<AgileWallPlan> writePlans = FilterAgileWallWritePlans(
                    plans, mode, ref skippedExisting);
                ApplyAgileWallWrites(
                    doc, writePlans, targetParameter, failures, ref appliedChanges);
            }

            int maxResults = ClampAuditLimit(
                parameters["maxResults"]?.Value<int?>(), 1, 5000, 1000);
            List<AgileWallPlan> returnedPlans = plans.Take(maxResults).ToList();
            return new
            {
                Success = true,
                Applied = apply,
                Mode = mode,
                TargetParameter = targetParameter,
                TargetScope = targetScope,
                MatchField = matchField,
                SourceParameter = sourceParameter,
                Scope = new
                {
                    Level = parameters["level"]?.Value<string>(),
                    WallIds = ParseAgileElementIds(parameters["wallIds"] as JArray),
                    IncludeCurtain = includeCurtain,
                    MaxWalls = maxWalls,
                    MaxResults = maxResults
                },
                Summary = new
                {
                    TotalWalls = walls.Count,
                    Targets = groups.Count,
                    ReturnedPlans = returnedPlans.Count,
                    PlansTruncated = plans.Count > returnedPlans.Count,
                    Proposed = plans.Count(plan => plan.Status == "proposed"),
                    AppliedChanges = appliedChanges,
                    SkippedExisting = skippedExisting,
                    Unchanged = plans.Count(plan => plan.Status == "unchanged"),
                    Unmatched = plans.Count(plan => plan.Status == "unmatched"),
                    Conflicts = plans.Count(plan => plan.Status == "conflict"),
                    Blocked = plans.Count(plan => plan.Status == "blocked")
                },
                Rules = rules.Select(rule => rule.ToResponse()).ToList(),
                Walls = returnedPlans.Select(plan => plan.ToResponse()).ToList(),
                Failures = failures,
                Message = apply
                    ? "牆性能分類已依確認模式處理；請重新查詢模型驗證實際值。"
                    : "牆性能分類 preview 完成；本命令沒有修改模型。"
            };
        }

        private static string RequireAgileTargetParameter(JObject parameters, string label)
        {
            string target = parameters["targetParameter"]?.Value<string>()?.Trim();
            if (string.IsNullOrWhiteSpace(target))
            {
                throw new ArgumentException(
                    label + " targetParameter 是必要欄位；請先用參數字典確認實際名稱。"
                );
            }
            return target;
        }

        private static string ParseAgileTargetScope(JToken token, string defaultValue)
        {
            string scope = token?.Value<string>()?.Trim().ToLowerInvariant() ?? defaultValue;
            if (scope != "instance" && scope != "type")
            {
                throw new ArgumentException("targetScope 必須是 instance 或 type。");
            }
            return scope;
        }

        private static List<IdType> ParseAgileElementIds(JArray token)
        {
            if (token == null) return new List<IdType>();
            return token.Select(value => value.Value<IdType>())
                .Where(value => value != 0)
                .Distinct()
                .ToList();
        }

        private static List<AgileMatchRule> ParseAgileMatchRules(
            JArray token, string label)
        {
            if (token == null || token.Count == 0)
            {
                throw new ArgumentException(
                    label + " rules 必須是非空陣列，例如 [{\"id\":\"rule-1\",\"match\":\"內門\",\"value\":\"D-INT\"}]。"
                );
            }

            List<AgileMatchRule> rules = new List<AgileMatchRule>();
            for (int index = 0; index < token.Count; index++)
            {
                JObject item = token[index] as JObject;
                if (item == null)
                {
                    throw new ArgumentException(label + " rules 的每一項都必須是 object。索引：" + index);
                }
                string match = item["match"]?.Value<string>()
                    ?? item["contains"]?.Value<string>();
                string value = item["value"]?.Value<string>()
                    ?? item["proposedValue"]?.Value<string>();
                if (string.IsNullOrWhiteSpace(match) || value == null)
                {
                    throw new ArgumentException(
                        label + " 每條規則都需要非空 match 與 value。索引：" + index);
                }
                rules.Add(new AgileMatchRule
                {
                    RuleId = item["id"]?.Value<string>()?.Trim() ?? "rule-" + (index + 1),
                    Match = NormalizeAgileRuleText(match, true),
                    Value = value.Trim()
                });
            }
            return rules;
        }

        private static string NormalizeAgileRuleText(string value, bool collapseWhitespace)
        {
            string normalized = value ?? "";
            try { normalized = normalized.Normalize(NormalizationForm.FormKC); }
            catch { }
            normalized = normalized.Trim();
            return collapseWhitespace
                ? Regex.Replace(normalized, @"\s+", " ")
                : normalized;
        }

        private static string NormalizeAgileMark(string value)
        {
            string normalized = NormalizeAgileRuleText(value, true);
            return normalized.ToUpperInvariant();
        }

        private static bool IsAgileRuleMatch(
            string source, AgileMatchRule rule, bool caseInsensitive,
            bool collapseWhitespace)
        {
            string haystack = NormalizeAgileRuleText(source, collapseWhitespace);
            string needle = NormalizeAgileRuleText(rule.Match, collapseWhitespace);
            return haystack.IndexOf(
                needle,
                caseInsensitive ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal) >= 0;
        }

        private static List<AgileMatchRule> GetAgileMatchedRules(
            string source, List<AgileMatchRule> rules, bool caseInsensitive,
            bool collapseWhitespace)
        {
            return rules.Where(rule => IsAgileRuleMatch(
                source, rule, caseInsensitive, collapseWhitespace)).ToList();
        }

        private static List<string> GetAgileDistinctRuleValues(List<AgileMatchRule> rules)
        {
            return rules.Select(rule => rule.Value)
                .Distinct(StringComparer.Ordinal)
                .ToList();
        }

        private static bool IsAgileBlank(string value)
        {
            return string.IsNullOrWhiteSpace(value) || string.IsNullOrWhiteSpace(NormalizeAgileMark(value));
        }

        private static string SafeAgileElementName(Element element)
        {
            if (element == null) return "";
            try { return element.Name ?? ""; }
            catch { return ""; }
        }

        private static string SafeAgileFamilyName(FamilySymbol symbol)
        {
            if (symbol == null) return "";
            try { return symbol.FamilyName ?? ""; }
            catch { }
            try { return symbol.Family?.Name ?? ""; }
            catch { return ""; }
        }

        private static string SafeAgileLevelName(Document doc, ElementId levelId)
        {
            try
            {
                if (levelId == null || levelId == ElementId.InvalidElementId) return "";
                return SafeAgileElementName(doc.GetElement(levelId));
            }
            catch { return ""; }
        }

        private static string SafeAgileOpeningLevel(
            Document doc, FamilyInstance instance, out double elevation)
        {
            elevation = 0.0;
            ElementId levelId = ElementId.InvalidElementId;
            try { levelId = instance.LevelId; }
            catch { }
            if (levelId == null || levelId == ElementId.InvalidElementId)
            {
                string[] parameterNames = {
                    "FAMILY_LEVEL_PARAM",
                    "INSTANCE_REFERENCE_LEVEL_PARAM",
                    "SCHEDULE_LEVEL_PARAM"
                };
                foreach (string parameterName in parameterNames)
                {
                    BuiltInParameter builtIn;
                    if (!Enum.TryParse(parameterName, out builtIn)) continue;
                    try
                    {
                        Parameter parameter = instance.get_Parameter(builtIn);
                        if (parameter == null) continue;
                        ElementId candidate = parameter.AsElementId();
                        if (candidate != null && candidate != ElementId.InvalidElementId)
                        {
                            levelId = candidate;
                            break;
                        }
                    }
                    catch { }
                }
            }
            if ((levelId == null || levelId == ElementId.InvalidElementId)
                && instance.Host is Wall hostWall)
            {
                try { levelId = hostWall.LevelId; }
                catch { }
            }
            Level level = null;
            try { level = doc.GetElement(levelId) as Level; }
            catch { }
            if (level != null)
            {
                try { elevation = level.Elevation; }
                catch { }
            }
            return SafeAgileElementName(level);
        }

        private static string SafeAgileWallLevel(
            Document doc, Wall wall, out double elevation)
        {
            elevation = 0.0;
            try
            {
                Level level = doc.GetElement(wall.LevelId) as Level;
                if (level != null)
                {
                    try { elevation = level.Elevation; }
                    catch { }
                    return SafeAgileElementName(level);
                }
            }
            catch { }
            return "";
        }

        private static Parameter ResolveAgileElementParameter(
            Element element, string parameterName, out bool ambiguous)
        {
            ambiguous = false;
            if (element == null || string.IsNullOrWhiteSpace(parameterName)) return null;
            string requested = parameterName.Trim();
            List<Parameter> exactMatches = new List<Parameter>();
            try
            {
                exactMatches = element.Parameters.Cast<Parameter>()
                    .Where(parameter => parameter?.Definition != null
                        && string.Equals(parameter.Definition.Name?.Trim(),
                            requested, StringComparison.OrdinalIgnoreCase))
                    .ToList();
            }
            catch { }
            if (exactMatches.Count > 1)
            {
                ambiguous = true;
                return null;
            }
            if (exactMatches.Count == 1) return exactMatches[0];

            BuiltInParameter? alias = ResolveAgileBuiltInParameterAlias(requested);
            if (alias.HasValue)
            {
                try
                {
                    Parameter parameter = element.get_Parameter(alias.Value);
                    if (parameter != null) return parameter;
                }
                catch { }
            }

            try { return element.LookupParameter(requested); }
            catch { return null; }
        }

        private static BuiltInParameter? ResolveAgileBuiltInParameterAlias(string name)
        {
            switch ((name ?? "").Trim().ToUpperInvariant())
            {
                case "MARK":
                case "INSTANCE_MARK":
                case "ALL_MODEL_MARK":
                    return BuiltInParameter.ALL_MODEL_MARK;
                case "TYPE_MARK":
                case "ALL_MODEL_TYPE_MARK":
                    return BuiltInParameter.ALL_MODEL_TYPE_MARK;
                default:
                    return null;
            }
        }

        private static string SafeAgileParameterValue(Parameter parameter)
        {
            return parameter == null ? "" : GetAgileParameterDisplayValue(parameter);
        }

        private static string GetAgileParameterStatus(Parameter parameter)
        {
            if (parameter == null) return "找不到目標參數。";
            try
            {
                if (parameter.IsReadOnly) return "目標參數是唯讀的。";
                if (parameter.StorageType != StorageType.String)
                    return "目標參數不是 String。";
            }
            catch { return "無法讀取目標參數狀態。"; }
            return "";
        }

        private static void ValidateAgileDoorSpecMatchField(string value)
        {
            string[] allowed = {
                "family", "type", "mark", "from_room_name", "to_room_name",
                "room_name", "host_wall_type", "parameter"
            };
            if (!allowed.Contains(value))
            {
                throw new ArgumentException(
                    "門規格 matchField 必須是 family、type、mark、from_room_name、"
                    + "to_room_name、room_name、host_wall_type 或 parameter。"
                );
            }
        }

        private static void ValidateAgileWallMatchField(string value)
        {
            string[] allowed = {
                "type", "function", "kind", "room_name", "room_number", "parameter"
            };
            if (!allowed.Contains(value))
            {
                throw new ArgumentException(
                    "牆性能分類 matchField 必須是 type、function、kind、room_name、room_number 或 parameter。"
                );
            }
        }

        private static void ValidateAgileNumberingSource(string value)
        {
            string[] allowed = { "sequence", "type_mark", "type_name", "parameter", "constant" };
            if (!allowed.Contains(value))
            {
                throw new ArgumentException(
                    "門窗編號 source 必須是 sequence、type_mark、type_name、parameter 或 constant。"
                );
            }
        }

        private static void ValidateAgileSequenceScope(string value)
        {
            string[] allowed = { "global", "level", "category", "level_category" };
            if (!allowed.Contains(value))
            {
                throw new ArgumentException(
                    "門窗編號 sequenceScope 必須是 global、level、category 或 level_category。"
                );
            }
        }

        private static bool IsAgileDoorCategory(FamilyInstance instance)
        {
            try
            {
                return instance.Category != null
                    && instance.Category.Id.GetIdValue() == (IdType)BuiltInCategory.OST_Doors;
            }
            catch { return false; }
        }

        private static bool IsAgileWindowCategory(FamilyInstance instance)
        {
            try
            {
                return instance.Category != null
                    && instance.Category.Id.GetIdValue() == (IdType)BuiltInCategory.OST_Windows;
            }
            catch { return false; }
        }

        private static bool IsAgileCategoryRequested(JObject parameters, string category)
        {
            JArray categories = parameters["categories"] as JArray;
            if (categories == null || categories.Count == 0) return true;
            return categories.Any(token => string.Equals(
                token.Value<string>()?.Trim(), category, StringComparison.OrdinalIgnoreCase)
                || string.Equals(
                    token.Value<string>()?.Trim(),
                    category == "doors" ? "door" : "window",
                    StringComparison.OrdinalIgnoreCase));
        }

        private static bool IsAgileCurtainOpening(AgileOpeningTarget opening)
        {
            try
            {
                Wall wall = opening.HostWall;
                return wall != null && wall.WallType != null
                    && wall.WallType.Kind == WallKind.Curtain;
            }
            catch { return false; }
        }

        private static List<AgileOpeningTarget> CollectAgileOpenings(
            Document doc, JObject parameters, bool ignoreScope,
            bool includeCurtain, int maxCount, bool doorsOnly = false)
        {
            bool includeDoors = doorsOnly || IsAgileCategoryRequested(parameters, "doors");
            bool includeWindows = !doorsOnly && IsAgileCategoryRequested(parameters, "windows");
            HashSet<IdType> explicitIds = new HashSet<IdType>(
                ParseAgileElementIds(parameters["elementIds"] as JArray));
            HashSet<IdType> explicitDoorIds = new HashSet<IdType>(
                ParseAgileElementIds(parameters["doorIds"] as JArray));
            HashSet<IdType> requestedIds = explicitIds.Count > 0 ? explicitIds : explicitDoorIds;
            string levelFilter = parameters["level"]?.Value<string>()?.Trim();
            List<AgileOpeningTarget> openings = new List<AgileOpeningTarget>();
            BuiltInCategory[] categories = doorsOnly
                ? new[] { BuiltInCategory.OST_Doors }
                : new[] { BuiltInCategory.OST_Doors, BuiltInCategory.OST_Windows };
            foreach (BuiltInCategory category in categories)
            {
                bool wanted = category == BuiltInCategory.OST_Doors
                    ? includeDoors : includeWindows;
                if (!wanted) continue;
                IEnumerable<FamilyInstance> instances;
                try
                {
                    instances = new FilteredElementCollector(doc)
                        .OfCategory(category)
                        .WhereElementIsNotElementType()
                        .OfType<FamilyInstance>();
                }
                catch { continue; }

                foreach (FamilyInstance instance in instances)
                {
                    if (instance == null) continue;
                    IdType id;
                    try { id = instance.Id.GetIdValue(); }
                    catch { continue; }
                    if (!ignoreScope && requestedIds.Count > 0 && !requestedIds.Contains(id)) continue;

                    FamilySymbol symbol = null;
                    try { symbol = instance.Symbol; }
                    catch { }
                    Wall hostWall = null;
                    try { hostWall = instance.Host as Wall; }
                    catch { }
                    AgileOpeningTarget opening = new AgileOpeningTarget
                    {
                        Instance = instance,
                        Symbol = symbol,
                        HostWall = hostWall,
                        ElementId = id,
                        Category = category == BuiltInCategory.OST_Doors ? "door" : "window",
                        CategoryLabel = category == BuiltInCategory.OST_Doors ? "門" : "窗",
                        FamilyName = SafeAgileFamilyName(symbol),
                        TypeName = SafeAgileElementName(symbol),
                        FromRoom = TryGetFromRoom(instance),
                        ToRoom = TryGetToRoom(instance)
                    };
                    opening.Level = SafeAgileOpeningLevel(doc, instance, out double elevation);
                    opening.LevelElevation = elevation;
                    opening.IsCurtain = IsAgileCurtainOpening(opening);
                    if (!includeCurtain && opening.IsCurtain) continue;
                    if (!ignoreScope && !string.IsNullOrWhiteSpace(levelFilter)
                        && opening.Level.IndexOf(levelFilter, StringComparison.OrdinalIgnoreCase) < 0)
                    {
                        continue;
                    }
                    openings.Add(opening);
                }
            }

            List<AgileOpeningTarget> ordered = openings
                .OrderBy(opening => opening.LevelElevation)
                .ThenBy(opening => opening.Category == "door" ? 0 : 1)
                .ThenBy(opening => opening.Level, StringComparer.OrdinalIgnoreCase)
                .ThenBy(opening => opening.FamilyName, StringComparer.OrdinalIgnoreCase)
                .ThenBy(opening => opening.TypeName, StringComparer.OrdinalIgnoreCase)
                .ThenBy(opening => opening.ElementId)
                .ToList();
            return maxCount > 0 ? ordered.Take(maxCount).ToList() : ordered;
        }

        private static string GetAgileOpeningGroupKey(AgileOpeningGroup group)
        {
            return group.TargetScope + ":"
                + group.TargetElementId.ToString(CultureInfo.InvariantCulture);
        }

        private static List<AgileOpeningGroup> GroupAgileOpenings(
            List<AgileOpeningTarget> openings, string targetScope)
        {
            Dictionary<string, AgileOpeningGroup> groups =
                new Dictionary<string, AgileOpeningGroup>(StringComparer.Ordinal);
            foreach (AgileOpeningTarget opening in openings)
            {
                Element target = targetScope == "type" ? opening.Symbol : opening.Instance;
                if (target == null) continue;
                IdType targetId;
                try { targetId = target.Id.GetIdValue(); }
                catch { continue; }
                string key = targetScope + ":"
                    + targetId.ToString(CultureInfo.InvariantCulture);
                if (!groups.TryGetValue(key, out AgileOpeningGroup group))
                {
                    group = new AgileOpeningGroup
                    {
                        TargetScope = targetScope,
                        TargetElement = target,
                        TargetElementId = targetId,
                        Representative = opening,
                        Records = new List<AgileOpeningTarget>()
                    };
                    groups[key] = group;
                }
                group.Records.Add(opening);
            }
            return groups.Values
                .OrderBy(group => group.Representative.LevelElevation)
                .ThenBy(group => group.Representative.Category == "door" ? 0 : 1)
                .ThenBy(group => group.Representative.Level, StringComparer.OrdinalIgnoreCase)
                .ThenBy(group => group.Representative.FamilyName, StringComparer.OrdinalIgnoreCase)
                .ThenBy(group => group.Representative.TypeName, StringComparer.OrdinalIgnoreCase)
                .ThenBy(group => group.TargetElementId)
                .ToList();
        }

        private static string GetAgileOpeningRoomName(Room room)
        {
            return room == null ? "" : GetAgileAuditRoomName(room);
        }

        private static string GetAgileOpeningRoomNumber(Room room)
        {
            try { return room?.Number ?? ""; }
            catch { return ""; }
        }

        private static string GetAgileOpeningSource(
            AgileOpeningTarget opening, string matchField, string sourceParameter)
        {
            switch (matchField)
            {
                case "family":
                    return opening.FamilyName;
                case "type":
                    return opening.TypeName;
                case "mark":
                    return SafeAgileParameterValue(
                        ResolveAgileElementParameter(
                            opening.Instance, "ALL_MODEL_MARK", out bool markAmbiguous));
                case "from_room_name":
                    return GetAgileOpeningRoomName(opening.FromRoom);
                case "to_room_name":
                    return GetAgileOpeningRoomName(opening.ToRoom);
                case "room_name":
                    return string.Join(" / ", new[] {
                        GetAgileOpeningRoomName(opening.FromRoom),
                        GetAgileOpeningRoomName(opening.ToRoom)
                    }.Where(value => !string.IsNullOrWhiteSpace(value)));
                case "host_wall_type":
                    try { return opening.HostWall?.WallType?.Name ?? ""; }
                    catch { return ""; }
                case "parameter":
                    Parameter instanceParameter = ResolveAgileElementParameter(
                        opening.Instance, sourceParameter, out bool instanceAmbiguous);
                    if (instanceParameter != null && !instanceAmbiguous)
                        return SafeAgileParameterValue(instanceParameter);
                    Parameter typeParameter = ResolveAgileElementParameter(
                        opening.Symbol, sourceParameter, out bool typeAmbiguous);
                    return typeParameter != null && !typeAmbiguous
                        ? SafeAgileParameterValue(typeParameter) : "";
                default:
                    return "";
            }
        }

        private static string GetAgileOpeningGroupSource(
            AgileOpeningGroup group, string matchField, string sourceParameter)
        {
            return string.Join(" / ", group.Records
                .Select(record => GetAgileOpeningSource(
                    record, matchField, sourceParameter))
                .Where(value => !string.IsNullOrWhiteSpace(value))
                .Distinct(StringComparer.Ordinal));
        }

        private static AgileDoorSpecPlan BuildAgileDoorSpecPlan(
            AgileOpeningGroup group, string targetParameter, string matchField,
            string sourceParameter, List<AgileMatchRule> rules,
            bool caseInsensitive, bool collapseWhitespace)
        {
            AgileDoorSpecPlan plan = new AgileDoorSpecPlan
            {
                Group = group,
                ElementId = group.TargetElementId,
                TargetScope = group.TargetScope,
                Category = group.Representative.CategoryLabel,
                FamilyName = group.Representative.FamilyName,
                TypeName = group.Representative.TypeName,
                Level = group.Representative.Level,
                InstanceCount = group.Records.Count,
                Status = "blocked"
            };
            Parameter target = ResolveAgileElementParameter(
                group.TargetElement, targetParameter, out bool ambiguous);
            string parameterStatus = ambiguous
                ? "目標參數名稱不唯一。"
                : GetAgileParameterStatus(target);
            if (!string.IsNullOrWhiteSpace(parameterStatus))
            {
                plan.Reason = parameterStatus;
                return plan;
            }
            plan.CurrentValue = SafeAgileParameterValue(target);
            plan.IsBlank = IsAgileBlank(plan.CurrentValue);
            plan.SourceValue = GetAgileOpeningGroupSource(
                group, matchField, sourceParameter);
            List<AgileMatchRule> matched = GetAgileMatchedRules(
                plan.SourceValue, rules, caseInsensitive, collapseWhitespace);
            plan.RuleIds = string.Join(", ", matched.Select(rule => rule.RuleId));
            if (matched.Count == 0)
            {
                plan.Status = "unmatched";
                plan.Reason = string.IsNullOrWhiteSpace(plan.SourceValue)
                    ? "來源值空白或未取得；沒有規則命中。"
                    : "沒有規則命中；保留原值。";
                return plan;
            }
            List<string> values = GetAgileDistinctRuleValues(matched);
            if (values.Count > 1)
            {
                plan.Status = "conflict";
                plan.Reason = "多條規則命中且 proposed value 不一致。";
                return plan;
            }
            plan.ProposedValue = values[0];
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

        private static List<AgileDoorSpecPlan> FilterAgileWritePlans(
            List<AgileDoorSpecPlan> plans, string mode, ref int skippedExisting)
        {
            List<AgileDoorSpecPlan> writePlans = new List<AgileDoorSpecPlan>();
            foreach (AgileDoorSpecPlan plan in plans)
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
            return writePlans;
        }

        private static void ApplyAgileDoorSpecWrites(
            Document doc, List<AgileDoorSpecPlan> plans, string targetParameter,
            List<object> failures, ref int appliedChanges)
        {
            if (plans.Count == 0) return;
            using (Transaction trans = new Transaction(doc, "套用門規格"))
            {
                trans.Start();
                foreach (AgileDoorSpecPlan plan in plans)
                {
                    Parameter parameter = ResolveAgileElementParameter(
                        plan.Group.TargetElement, targetParameter, out bool ambiguous);
                    string error = ambiguous
                        ? "目標參數名稱不唯一。"
                        : GetAgileParameterStatus(parameter);
                    if (!string.IsNullOrWhiteSpace(error))
                    {
                        failures.Add(new { plan.ElementId, Error = error });
                        continue;
                    }
                    try
                    {
                        if (!parameter.Set(plan.ProposedValue))
                        {
                            failures.Add(new { plan.ElementId, Error = "Revit 回傳 false，未能寫入參數。" });
                            continue;
                        }
                        plan.Status = "applied";
                        plan.Reason = "已在單一 Transaction 寫入。";
                        appliedChanges++;
                    }
                    catch (Exception ex)
                    {
                        failures.Add(new { plan.ElementId, Error = ex.Message });
                    }
                }
                if (failures.Count > 0)
                {
                    trans.RollBack();
                    throw new Exception(
                        "門規格寫入失敗，已回復整批變更："
                        + JArray.FromObject(failures).ToString());
                }
                trans.Commit();
            }
        }

        private static List<AgileNumberingPlan> BuildAgileNumberingPlans(
            List<AgileOpeningGroup> groups, List<AgileOpeningGroup> allGroups,
            string targetParameter, string source,
            string sourceParameter, string sequenceScope, string mode,
            JObject parameters)
        {
            List<AgileNumberingPlan> plans = new List<AgileNumberingPlan>();
            Dictionary<string, string> occupied = new Dictionary<string, string>(
                StringComparer.Ordinal);
            Dictionary<string, int> sequenceCounters = new Dictionary<string, int>(
                StringComparer.Ordinal);
            int start = parameters["start"]?.Value<int?>() ?? 1;
            if (start < 0) start = 0;
            int pad = parameters["pad"]?.Value<int?>() ?? 0;
            if (pad < 0 || pad > 12) pad = Math.Max(0, Math.Min(12, pad));

            foreach (AgileOpeningGroup group in allGroups)
            {
                AgileNumberingPlan plan = BuildAgileNumberingPlan(
                    group, targetParameter, source, sourceParameter);
                if (!string.IsNullOrWhiteSpace(plan.CurrentValue))
                {
                    occupied[NormalizeAgileMark(plan.CurrentValue)] = GetAgileOpeningGroupKey(group);
                }
            }

            foreach (AgileOpeningGroup group in groups)
            {
                AgileNumberingPlan plan = BuildAgileNumberingPlan(
                    group, targetParameter, source, sourceParameter);
                plans.Add(plan);
            }

            // In overwrite mode selected targets are allowed to release their old
            // values; values held by non-selected targets remain reserved.
            if (mode == "overwrite")
            {
                HashSet<string> selectedKeys = new HashSet<string>(
                    groups.Select(GetAgileOpeningGroupKey), StringComparer.Ordinal);
                foreach (string key in occupied
                    .Where(pair => selectedKeys.Contains(pair.Value))
                    .Select(pair => pair.Key).ToList())
                {
                    occupied.Remove(key);
                }
            }

            Dictionary<string, string> claimed = new Dictionary<string, string>(
                StringComparer.Ordinal);
            foreach (AgileNumberingPlan plan in plans)
            {
                if (plan.ParameterStatus != "")
                {
                    plan.Status = "blocked";
                    plan.Reason = plan.ParameterStatus;
                    continue;
                }
                if (mode == "fill_blank" && !plan.IsBlank)
                {
                    plan.Status = "unchanged";
                    plan.Reason = "fill_blank 保留既有值。";
                    continue;
                }

                string bucket = GetAgileSequenceBucket(
                    plan.Group.Representative, sequenceScope);
                string value;
                if (source == "sequence")
                {
                    int index = sequenceCounters.ContainsKey(bucket)
                        ? sequenceCounters[bucket] : 0;
                    sequenceCounters[bucket] = index + 1;
                    value = BuildAgileSequenceValue(
                        plan.Group.Representative, parameters, start + index, pad);
                }
                else
                {
                    value = GetAgileNumberingSourceValue(
                        plan.Group.Representative, source, sourceParameter,
                        parameters);
                }
                plan.ProposedValue = value;
                if (IsAgileBlank(value))
                {
                    plan.Status = "blocked";
                    plan.Reason = "來源值空白；沒有可寫入的編號。";
                    continue;
                }
                string normalized = NormalizeAgileMark(value);
                if (string.Equals(normalized, NormalizeAgileMark(plan.CurrentValue),
                    StringComparison.Ordinal) && mode == "overwrite")
                {
                    plan.Status = "unchanged";
                    plan.Reason = "產生值與既有值相同。";
                    continue;
                }
                if (occupied.ContainsKey(normalized))
                {
                    plan.Status = "collision";
                    plan.Reason = "與既有或未選取門窗編號重複。";
                    continue;
                }
                if (claimed.ContainsKey(normalized))
                {
                    plan.Status = "collision";
                    plan.Reason = "本次產生的編號互相重複。";
                    continue;
                }
                claimed[normalized] = GetAgileOpeningGroupKey(plan.Group);
                plan.Status = "proposed";
                plan.Reason = "可依確認模式寫入。";
            }
            return plans;
        }

        private static AgileNumberingPlan BuildAgileNumberingPlan(
            AgileOpeningGroup group, string targetParameter, string source,
            string sourceParameter)
        {
            Parameter parameter = ResolveAgileElementParameter(
                group.TargetElement, targetParameter, out bool ambiguous);
            string parameterStatus = ambiguous
                ? "目標參數名稱不唯一。"
                : GetAgileParameterStatus(parameter);
            string current = parameterStatus == ""
                ? SafeAgileParameterValue(parameter) : "";
            return new AgileNumberingPlan
            {
                Group = group,
                ElementId = group.TargetElementId,
                TargetScope = group.TargetScope,
                Category = group.Representative.CategoryLabel,
                FamilyName = group.Representative.FamilyName,
                TypeName = group.Representative.TypeName,
                Level = group.Representative.Level,
                InstanceCount = group.Records.Count,
                Source = source,
                SourceParameter = sourceParameter,
                CurrentValue = current,
                IsBlank = IsAgileBlank(current),
                ParameterStatus = parameterStatus,
                Status = string.IsNullOrWhiteSpace(parameterStatus) ? "pending" : "blocked",
                Reason = parameterStatus
            };
        }

        private static string GetAgileSequenceBucket(
            AgileOpeningTarget opening, string sequenceScope)
        {
            switch (sequenceScope)
            {
                case "level": return opening.Level ?? "";
                case "category": return opening.Category ?? "";
                case "level_category": return (opening.Level ?? "") + "\u001f" + (opening.Category ?? "");
                default: return "global";
            }
        }

        private static string BuildAgileSequenceValue(
            AgileOpeningTarget opening, JObject parameters, int number, int pad)
        {
            string prefix = parameters["prefix"]?.Value<string>() ?? "";
            if (opening.Category == "door" && parameters["doorPrefix"] != null)
                prefix = parameters["doorPrefix"]?.Value<string>() ?? "";
            if (opening.Category == "window" && parameters["windowPrefix"] != null)
                prefix = parameters["windowPrefix"]?.Value<string>() ?? "";
            string numberText = number.ToString(CultureInfo.InvariantCulture);
            if (pad > 0) numberText = numberText.PadLeft(pad, '0');
            return prefix + numberText;
        }

        private static string GetAgileNumberingSourceValue(
            AgileOpeningTarget opening, string source, string sourceParameter,
            JObject parameters)
        {
            switch (source)
            {
                case "type_mark":
                    return SafeAgileParameterValue(ResolveAgileElementParameter(
                        opening.Symbol, "ALL_MODEL_TYPE_MARK", out bool typeMarkAmbiguous));
                case "type_name":
                    return opening.TypeName;
                case "parameter":
                    Parameter instanceParameter = ResolveAgileElementParameter(
                        opening.Instance, sourceParameter, out bool instanceAmbiguous);
                    if (instanceParameter != null && !instanceAmbiguous)
                        return SafeAgileParameterValue(instanceParameter);
                    return SafeAgileParameterValue(ResolveAgileElementParameter(
                        opening.Symbol, sourceParameter, out bool typeAmbiguous));
                case "constant":
                    return parameters["constant"]?.Value<string>()?.Trim() ?? "";
                default:
                    return "";
            }
        }

        private static void ApplyAgileNumberingWrites(
            Document doc, List<AgileNumberingPlan> plans, string targetParameter,
            List<object> failures, ref int appliedChanges)
        {
            if (plans.Count == 0) return;
            using (Transaction trans = new Transaction(doc, "套用門窗編號"))
            {
                trans.Start();
                foreach (AgileNumberingPlan plan in plans)
                {
                    Parameter parameter = ResolveAgileElementParameter(
                        plan.Group.TargetElement, targetParameter, out bool ambiguous);
                    string error = ambiguous
                        ? "目標參數名稱不唯一。"
                        : GetAgileParameterStatus(parameter);
                    if (!string.IsNullOrWhiteSpace(error))
                    {
                        failures.Add(new { plan.ElementId, Error = error });
                        continue;
                    }
                    try
                    {
                        if (!parameter.Set(plan.ProposedValue))
                        {
                            failures.Add(new { plan.ElementId, Error = "Revit 回傳 false，未能寫入編號。" });
                            continue;
                        }
                        plan.Status = "applied";
                        plan.Reason = "已在單一 Transaction 寫入。";
                        appliedChanges++;
                    }
                    catch (Exception ex)
                    {
                        failures.Add(new { plan.ElementId, Error = ex.Message });
                    }
                }
                if (failures.Count > 0)
                {
                    trans.RollBack();
                    throw new Exception(
                        "門窗編號寫入失敗，已回復整批變更："
                        + JArray.FromObject(failures).ToString());
                }
                trans.Commit();
            }
        }

        private static List<AgileWallTarget> CollectAgileWalls(
            Document doc, JObject parameters, bool includeCurtain,
            int maxCount, bool collectRoomRelations)
        {
            HashSet<IdType> requestedIds = new HashSet<IdType>(
                ParseAgileElementIds(parameters["wallIds"] as JArray));
            string levelFilter = parameters["level"]?.Value<string>()?.Trim();
            Dictionary<IdType, List<Room>> wallRooms = collectRoomRelations
                ? BuildAgileWallRoomIndex(doc)
                : new Dictionary<IdType, List<Room>>();
            List<AgileWallTarget> walls = new List<AgileWallTarget>();
            IEnumerable<Wall> instances;
            try
            {
                instances = new FilteredElementCollector(doc)
                    .OfClass(typeof(Wall))
                    .WhereElementIsNotElementType()
                    .OfType<Wall>();
            }
            catch
            {
                instances = Enumerable.Empty<Wall>();
            }

            foreach (Wall wall in instances)
            {
                if (wall == null) continue;
                IdType id;
                try { id = wall.Id.GetIdValue(); }
                catch { continue; }
                if (requestedIds.Count > 0 && !requestedIds.Contains(id)) continue;
                WallType wallType = null;
                try { wallType = wall.WallType; }
                catch { }
                if (wallType == null) continue;
                bool isCurtain = false;
                try { isCurtain = wallType.Kind == WallKind.Curtain; }
                catch { }
                if (!includeCurtain && isCurtain) continue;
                string level = SafeAgileWallLevel(doc, wall, out double elevation);
                if (!string.IsNullOrWhiteSpace(levelFilter)
                    && level.IndexOf(levelFilter, StringComparison.OrdinalIgnoreCase) < 0)
                {
                    continue;
                }
                List<Room> linkedRooms;
                if (!wallRooms.TryGetValue(id, out linkedRooms))
                    linkedRooms = new List<Room>();
                string function = "";
                string kind = "";
                try { function = wallType.Function.ToString(); }
                catch { }
                try { kind = wallType.Kind.ToString(); }
                catch { }
                walls.Add(new AgileWallTarget
                {
                    Wall = wall,
                    WallType = wallType,
                    ElementId = id,
                    TypeId = wallType.Id.GetIdValue(),
                    Level = level,
                    LevelElevation = elevation,
                    TypeName = SafeAgileElementName(wallType),
                    Function = function,
                    Kind = kind,
                    IsCurtain = isCurtain,
                    Rooms = linkedRooms
                });
            }

            List<AgileWallTarget> ordered = walls
                .OrderBy(wall => wall.LevelElevation)
                .ThenBy(wall => wall.Level, StringComparer.OrdinalIgnoreCase)
                .ThenBy(wall => wall.TypeName, StringComparer.OrdinalIgnoreCase)
                .ThenBy(wall => wall.ElementId)
                .ToList();
            return ordered.Take(maxCount).ToList();
        }

        private static Dictionary<IdType, List<Room>> BuildAgileWallRoomIndex(Document doc)
        {
            Dictionary<IdType, List<Room>> index = new Dictionary<IdType, List<Room>>();
            IEnumerable<Room> rooms;
            try
            {
                rooms = new FilteredElementCollector(doc)
                    .OfCategory(BuiltInCategory.OST_Rooms)
                    .WhereElementIsNotElementType()
                    .OfType<Room>();
            }
            catch
            {
                rooms = Enumerable.Empty<Room>();
            }
            foreach (Room room in rooms)
            {
                if (room == null) continue;
                IList<IList<BoundarySegment>> loops = null;
                try
                {
                    loops = room.GetBoundarySegments(new SpatialElementBoundaryOptions());
                }
                catch { }
                if (loops == null) continue;
                foreach (IList<BoundarySegment> loop in loops)
                {
                    if (loop == null) continue;
                    foreach (BoundarySegment segment in loop)
                    {
                        if (segment == null) continue;
                        Wall wall = doc.GetElement(segment.ElementId) as Wall;
                        if (wall == null) continue;
                        IdType wallId;
                        try { wallId = wall.Id.GetIdValue(); }
                        catch { continue; }
                        if (!index.TryGetValue(wallId, out List<Room> linked))
                        {
                            linked = new List<Room>();
                            index[wallId] = linked;
                        }
                        if (!linked.Any(existing => existing.Id == room.Id))
                            linked.Add(room);
                    }
                }
            }
            return index;
        }

        private static string GetAgileWallSource(
            AgileWallTarget wall, string matchField, string sourceParameter)
        {
            switch (matchField)
            {
                case "type": return wall.TypeName;
                case "function": return wall.Function;
                case "kind": return wall.Kind;
                case "room_name":
                    return string.Join(" / ", wall.Rooms
                        .Select(GetAgileOpeningRoomName)
                        .Where(value => !string.IsNullOrWhiteSpace(value)));
                case "room_number":
                    return string.Join(" / ", wall.Rooms
                        .Select(GetAgileOpeningRoomNumber)
                        .Where(value => !string.IsNullOrWhiteSpace(value)));
                case "parameter":
                    Parameter instanceParameter = ResolveAgileElementParameter(
                        wall.Wall, sourceParameter, out bool instanceAmbiguous);
                    if (instanceParameter != null && !instanceAmbiguous)
                        return SafeAgileParameterValue(instanceParameter);
                    return SafeAgileParameterValue(ResolveAgileElementParameter(
                        wall.WallType, sourceParameter, out bool typeAmbiguous));
                default: return "";
            }
        }

        private static string GetAgileWallGroupSource(
            AgileWallGroup group, string matchField, string sourceParameter)
        {
            return string.Join(" / ", group.Records
                .Select(record => GetAgileWallSource(
                    record, matchField, sourceParameter))
                .Where(value => !string.IsNullOrWhiteSpace(value))
                .Distinct(StringComparer.Ordinal));
        }

        private static string GetAgileWallGroupRoomNames(AgileWallGroup group)
        {
            return string.Join(" / ", group.Records
                .SelectMany(record => record.Rooms ?? new List<Room>())
                .Select(GetAgileOpeningRoomName)
                .Where(value => !string.IsNullOrWhiteSpace(value))
                .Distinct(StringComparer.Ordinal));
        }

        private static List<AgileWallGroup> GroupAgileWalls(
            List<AgileWallTarget> walls, string targetScope)
        {
            Dictionary<string, AgileWallGroup> groups =
                new Dictionary<string, AgileWallGroup>(StringComparer.Ordinal);
            foreach (AgileWallTarget wall in walls)
            {
                Element target = targetScope == "type" ? wall.WallType : wall.Wall;
                if (target == null) continue;
                IdType targetId;
                try { targetId = target.Id.GetIdValue(); }
                catch { continue; }
                string key = targetScope + ":"
                    + targetId.ToString(CultureInfo.InvariantCulture);
                if (!groups.TryGetValue(key, out AgileWallGroup group))
                {
                    group = new AgileWallGroup
                    {
                        TargetScope = targetScope,
                        TargetElement = target,
                        TargetElementId = targetId,
                        Representative = wall,
                        Records = new List<AgileWallTarget>()
                    };
                    groups[key] = group;
                }
                group.Records.Add(wall);
            }
            return groups.Values
                .OrderBy(group => group.Representative.LevelElevation)
                .ThenBy(group => group.Representative.Level, StringComparer.OrdinalIgnoreCase)
                .ThenBy(group => group.Representative.TypeName, StringComparer.OrdinalIgnoreCase)
                .ThenBy(group => group.TargetElementId)
                .ToList();
        }

        private static AgileWallPlan BuildAgileWallPlan(
            AgileWallGroup group, string targetParameter, string matchField,
            string sourceParameter, List<AgileMatchRule> rules,
            bool caseInsensitive, bool collapseWhitespace)
        {
            AgileWallPlan plan = new AgileWallPlan
            {
                Group = group,
                ElementId = group.TargetElementId,
                TargetScope = group.TargetScope,
                TypeName = group.Representative.TypeName,
                Function = group.Representative.Function,
                Kind = group.Representative.Kind,
                Level = group.Representative.Level,
                RoomNames = GetAgileWallGroupRoomNames(group),
                InstanceCount = group.Records.Count,
                Status = "blocked"
            };
            Parameter target = ResolveAgileElementParameter(
                group.TargetElement, targetParameter, out bool ambiguous);
            string parameterStatus = ambiguous
                ? "目標參數名稱不唯一。"
                : GetAgileParameterStatus(target);
            if (!string.IsNullOrWhiteSpace(parameterStatus))
            {
                plan.Reason = parameterStatus;
                return plan;
            }
            plan.CurrentValue = SafeAgileParameterValue(target);
            plan.IsBlank = IsAgileBlank(plan.CurrentValue);
            plan.SourceValue = GetAgileWallGroupSource(
                group, matchField, sourceParameter);
            List<AgileMatchRule> matched = GetAgileMatchedRules(
                plan.SourceValue, rules, caseInsensitive, collapseWhitespace);
            plan.RuleIds = string.Join(", ", matched.Select(rule => rule.RuleId));
            if (matched.Count == 0)
            {
                plan.Status = "unmatched";
                plan.Reason = string.IsNullOrWhiteSpace(plan.SourceValue)
                    ? "來源值空白或未取得；沒有規則命中。"
                    : "沒有規則命中；保留原值。";
                return plan;
            }
            List<string> values = GetAgileDistinctRuleValues(matched);
            if (values.Count > 1)
            {
                plan.Status = "conflict";
                plan.Reason = "多條規則命中且 proposed value 不一致。";
                return plan;
            }
            plan.ProposedValue = values[0];
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

        private static List<AgileWallPlan> FilterAgileWallWritePlans(
            List<AgileWallPlan> plans, string mode, ref int skippedExisting)
        {
            List<AgileWallPlan> writePlans = new List<AgileWallPlan>();
            foreach (AgileWallPlan plan in plans)
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
            return writePlans;
        }

        private static void ApplyAgileWallWrites(
            Document doc, List<AgileWallPlan> plans, string targetParameter,
            List<object> failures, ref int appliedChanges)
        {
            if (plans.Count == 0) return;
            using (Transaction trans = new Transaction(doc, "套用牆性能分類"))
            {
                trans.Start();
                foreach (AgileWallPlan plan in plans)
                {
                    Parameter parameter = ResolveAgileElementParameter(
                        plan.Group.TargetElement, targetParameter, out bool ambiguous);
                    string error = ambiguous
                        ? "目標參數名稱不唯一。"
                        : GetAgileParameterStatus(parameter);
                    if (!string.IsNullOrWhiteSpace(error))
                    {
                        failures.Add(new { plan.ElementId, Error = error });
                        continue;
                    }
                    try
                    {
                        if (!parameter.Set(plan.ProposedValue))
                        {
                            failures.Add(new { plan.ElementId, Error = "Revit 回傳 false，未能寫入牆性能分類。" });
                            continue;
                        }
                        plan.Status = "applied";
                        plan.Reason = "已在單一 Transaction 寫入。";
                        appliedChanges++;
                    }
                    catch (Exception ex)
                    {
                        failures.Add(new { plan.ElementId, Error = ex.Message });
                    }
                }
                if (failures.Count > 0)
                {
                    trans.RollBack();
                    throw new Exception(
                        "牆性能分類寫入失敗，已回復整批變更："
                        + JArray.FromObject(failures).ToString());
                }
                trans.Commit();
            }
        }

        private sealed class AgileMatchRule
        {
            public string RuleId { get; set; }
            public string Match { get; set; }
            public string Value { get; set; }

            public object ToResponse()
            {
                return new { Id = RuleId, Match, Value };
            }
        }

        private sealed class AgileOpeningTarget
        {
            public FamilyInstance Instance { get; set; }
            public FamilySymbol Symbol { get; set; }
            public Wall HostWall { get; set; }
            public Room FromRoom { get; set; }
            public Room ToRoom { get; set; }
            public IdType ElementId { get; set; }
            public string Category { get; set; }
            public string CategoryLabel { get; set; }
            public string FamilyName { get; set; }
            public string TypeName { get; set; }
            public string Level { get; set; }
            public double LevelElevation { get; set; }
            public bool IsCurtain { get; set; }
        }

        private sealed class AgileOpeningGroup
        {
            public string TargetScope { get; set; }
            public Element TargetElement { get; set; }
            public IdType TargetElementId { get; set; }
            public AgileOpeningTarget Representative { get; set; }
            public List<AgileOpeningTarget> Records { get; set; }
        }

        private sealed class AgileDoorSpecPlan
        {
            public AgileOpeningGroup Group { get; set; }
            public IdType ElementId { get; set; }
            public string TargetScope { get; set; }
            public string Category { get; set; }
            public string FamilyName { get; set; }
            public string TypeName { get; set; }
            public string Level { get; set; }
            public int InstanceCount { get; set; }
            public string SourceValue { get; set; }
            public string CurrentValue { get; set; }
            public string ProposedValue { get; set; }
            public string RuleIds { get; set; }
            public string Status { get; set; }
            public string Reason { get; set; }
            public bool IsBlank { get; set; }

            public object ToResponse()
            {
                return new
                {
                    ElementId,
                    TargetScope,
                    Category,
                    Family = FamilyName,
                    Type = TypeName,
                    Level,
                    InstanceCount,
                    SourceValue,
                    CurrentValue,
                    ProposedValue,
                    RuleIds,
                    Status,
                    Reason,
                    FromRoomName = GetAgileOpeningRoomName(Group.Representative.FromRoom),
                    FromRoomNumber = GetAgileOpeningRoomNumber(Group.Representative.FromRoom),
                    ToRoomName = GetAgileOpeningRoomName(Group.Representative.ToRoom),
                    ToRoomNumber = GetAgileOpeningRoomNumber(Group.Representative.ToRoom),
                    HostWallId = Group.Representative.HostWall == null
                        ? (IdType)0 : Group.Representative.HostWall.Id.GetIdValue(),
                    IsCurtain = Group.Representative.IsCurtain
                };
            }
        }

        private sealed class AgileNumberingPlan
        {
            public AgileOpeningGroup Group { get; set; }
            public IdType ElementId { get; set; }
            public string TargetScope { get; set; }
            public string Category { get; set; }
            public string FamilyName { get; set; }
            public string TypeName { get; set; }
            public string Level { get; set; }
            public int InstanceCount { get; set; }
            public string Source { get; set; }
            public string SourceParameter { get; set; }
            public string CurrentValue { get; set; }
            public string ProposedValue { get; set; }
            public string ParameterStatus { get; set; }
            public string Status { get; set; }
            public string Reason { get; set; }
            public bool IsBlank { get; set; }

            public object ToResponse()
            {
                return new
                {
                    ElementId,
                    TargetScope,
                    Category,
                    Family = FamilyName,
                    Type = TypeName,
                    Level,
                    InstanceCount,
                    Source,
                    SourceParameter,
                    CurrentValue,
                    ProposedValue,
                    Status,
                    Reason,
                    FromRoomName = GetAgileOpeningRoomName(Group.Representative.FromRoom),
                    ToRoomName = GetAgileOpeningRoomName(Group.Representative.ToRoom),
                    HostWallId = Group.Representative.HostWall == null
                        ? (IdType)0 : Group.Representative.HostWall.Id.GetIdValue(),
                    IsCurtain = Group.Representative.IsCurtain
                };
            }
        }

        private sealed class AgileWallTarget
        {
            public Wall Wall { get; set; }
            public WallType WallType { get; set; }
            public IdType ElementId { get; set; }
            public IdType TypeId { get; set; }
            public string Level { get; set; }
            public double LevelElevation { get; set; }
            public string TypeName { get; set; }
            public string Function { get; set; }
            public string Kind { get; set; }
            public bool IsCurtain { get; set; }
            public List<Room> Rooms { get; set; }
        }

        private sealed class AgileWallGroup
        {
            public string TargetScope { get; set; }
            public Element TargetElement { get; set; }
            public IdType TargetElementId { get; set; }
            public AgileWallTarget Representative { get; set; }
            public List<AgileWallTarget> Records { get; set; }
        }

        private sealed class AgileWallPlan
        {
            public AgileWallGroup Group { get; set; }
            public IdType ElementId { get; set; }
            public string TargetScope { get; set; }
            public string TypeName { get; set; }
            public string Function { get; set; }
            public string Kind { get; set; }
            public string Level { get; set; }
            public string RoomNames { get; set; }
            public int InstanceCount { get; set; }
            public string SourceValue { get; set; }
            public string CurrentValue { get; set; }
            public string ProposedValue { get; set; }
            public string RuleIds { get; set; }
            public string Status { get; set; }
            public string Reason { get; set; }
            public bool IsBlank { get; set; }

            public object ToResponse()
            {
                return new
                {
                    ElementId,
                    TargetScope,
                    Type = TypeName,
                    Function,
                    Kind,
                    Level,
                    RoomNames,
                    InstanceCount,
                    SourceValue,
                    CurrentValue,
                    ProposedValue,
                    RuleIds,
                    Status,
                    Reason,
                    IsCurtain = Group.Representative.IsCurtain
                };
            }
        }
    }
}
