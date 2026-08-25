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
        private static readonly string[] DefaultCodeIntegrityProjectParameters =
        {
            "Law_地籍基地面積",
            "Law_法定開挖率%",
            "Law_法定建蔽率%",
            "Law_法定容積率%",
            "Law_機電設備容積乘積%",
            "Law_停車檢討適用法規",
            "Law_供公眾建築物",
            "Law_防火構造",
            "Law_都市計畫區域"
        };

        private static readonly string[] DefaultCodeIntegrityAreaParameters =
        {
            "Law_建管-用途類組",
            "Law_技規-法定名稱"
        };

        private static readonly string[] DefaultCodeIntegrityRequiredLevels =
        {
            "1FL",
            "RFL"
        };

        private static readonly string[] DefaultCodeIntegrityRecommendedLevels =
        {
            "GL"
        };

        private static readonly string[] DefaultCodeIntegrityCategories =
        {
            "Walls",
            "Floors",
            "Doors",
            "Windows",
            "Columns",
            "StructuralFraming",
            "Stairs"
        };

        private static readonly string[] DefaultCodeIntegrityViewKeywords =
        {
            "地籍套繪圖",
            "綠化面積",
            "開挖面積",
            "防火區劃",
            "樓地板面積"
        };

        /// <summary>
        /// 唯讀盤點台灣建築法規 BIM 檢討所需的模型輸入。
        /// 這裡只驗證資料是否存在／可讀，不把 REVIT_112 或任何外部摘要當成現行法規判定。
        /// </summary>
        private object AuditCodeInputs(JObject parameters)
        {
            if (_uiApp.ActiveUIDocument == null || _uiApp.ActiveUIDocument.Document == null)
            {
                throw new InvalidOperationException("ERROR:目前沒有開啟的 Revit 文件，無法執行模型資料完整性檢查。");
            }

            Document doc = _uiApp.ActiveUIDocument.Document;
            string rulePackId = parameters["rulePackId"]?.Value<string>()?.Trim();
            if (string.IsNullOrWhiteSpace(rulePackId))
            {
                rulePackId = "taiwan-building-code-model-integrity";
            }
            string auditRunId = Guid.NewGuid().ToString("N");
            string checkedAtUtc = DateTime.UtcNow.ToString("O");

            bool checkNamedViews = parameters["checkNamedViews"]?.Value<bool>() ?? true;
            bool checkAreaPlanContent = parameters["checkAreaPlanContent"]?.Value<bool>() ?? true;
            bool includeElementSamples = parameters["includeElementSamples"]?.Value<bool>() ?? false;
            int maxElementSamples = ClampAuditLimit(
                parameters["maxElementSamples"]?.Value<int?>(), 1, 50, 10);

            List<string> requiredProjectParameters = ReadCodeIntegrityStrings(
                parameters["requiredProjectParameters"], DefaultCodeIntegrityProjectParameters);
            List<string> requiredAreaParameters = ReadCodeIntegrityStrings(
                parameters["requiredAreaParameters"], DefaultCodeIntegrityAreaParameters);
            List<string> requiredLevels = ReadCodeIntegrityStrings(
                parameters["requiredLevelNames"], DefaultCodeIntegrityRequiredLevels);
            List<string> recommendedLevels = ReadCodeIntegrityStrings(
                parameters["recommendedLevelNames"], DefaultCodeIntegrityRecommendedLevels);
            List<string> requiredCategories = ReadCodeIntegrityStrings(
                parameters["requiredCategories"], DefaultCodeIntegrityCategories);
            List<string> requiredViewKeywords = ReadCodeIntegrityStrings(
                parameters["requiredViewNameKeywords"], DefaultCodeIntegrityViewKeywords);

            List<CodeIntegrityFinding> findings = new List<CodeIntegrityFinding>();
            List<Level> levels = new FilteredElementCollector(doc)
                .OfClass(typeof(Level))
                .Cast<Level>()
                .OrderBy(level => level.Elevation)
                .ToList();

            List<object> levelResults = new List<object>();
            foreach (Level level in levels)
            {
                levelResults.Add(new
                {
                    ElementId = level.Id.GetIdValue(),
                    Name = level.Name,
                    ElevationMm = Math.Round(level.Elevation * 304.8, 2)
                });
            }

            foreach (string requiredLevel in requiredLevels)
            {
                Level match = levels.FirstOrDefault(level => string.Equals(
                    level.Name, requiredLevel, StringComparison.OrdinalIgnoreCase));
                bool exists = match != null;
                AddCodeIntegrityFinding(
                    findings,
                    "level.required." + requiredLevel,
                    exists ? "PASS" : "FAIL",
                    exists ? "info" : "error",
                    exists
                        ? "必要樓層已存在。"
                        : "找不到必要樓層；後續樓層範圍檢討不可直接套用。",
                    new
                    {
                        RequestedName = requiredLevel,
                        MatchedName = match?.Name,
                        Exists = exists
                    },
                    "REVIT_112.pdf p.13：樓層命名與模型輸入契約");
            }

            foreach (string recommendedLevel in recommendedLevels)
            {
                Level match = levels.FirstOrDefault(level => string.Equals(
                    level.Name, recommendedLevel, StringComparison.OrdinalIgnoreCase));
                bool exists = match != null;
                AddCodeIntegrityFinding(
                    findings,
                    "level.recommended." + recommendedLevel,
                    exists ? "PASS" : "WARNING",
                    exists ? "info" : "warning",
                    exists
                        ? "建議樓層已存在。"
                        : "找不到建議樓層；請確認面積圖或基地基準的專案命名。",
                    new
                    {
                        RequestedName = recommendedLevel,
                        MatchedName = match?.Name,
                        Exists = exists
                    },
                    "REVIT_112.pdf p.13：樓層命名與模型輸入契約");
            }

            ProjectInfo projectInfo = doc.ProjectInformation;
            List<object> parameterResults = new List<object>();
            foreach (string parameterName in requiredProjectParameters)
            {
                Parameter parameter = projectInfo?.LookupParameter(parameterName);
                bool exists = parameter != null;
                string value = exists ? ReadCodeIntegrityParameterValue(parameter) : null;
                bool hasValue = HasCodeIntegrityParameterValue(parameter, value);
                string status = !exists ? "FAIL" : hasValue ? "PASS" : "WARNING";
                string severity = !exists ? "error" : hasValue ? "info" : "warning";

                parameterResults.Add(new
                {
                    Name = parameterName,
                    Scope = "ProjectInformation",
                    Exists = exists,
                    HasValue = hasValue,
                    IsReadOnly = exists && parameter.IsReadOnly,
                    StorageType = exists ? parameter.StorageType.ToString() : null,
                    Value = value,
                    ValueStatus = GetCodeIntegrityValueStatus(parameter, value)
                });

                AddCodeIntegrityFinding(
                    findings,
                    "project-parameter." + parameterName,
                    status,
                    severity,
                    !exists
                        ? "Project Information 找不到必要法規輸入參數。"
                        : hasValue
                            ? "必要法規輸入參數存在且有值。"
                            : "必要法規輸入參數存在但目前為空白。",
                    new
                    {
                        Name = parameterName,
                        Scope = "ProjectInformation",
                        Exists = exists,
                        HasValue = hasValue,
                        StorageType = exists ? parameter.StorageType.ToString() : null,
                        ValueStatus = GetCodeIntegrityValueStatus(parameter, value)
                    },
                    "REVIT_112.pdf p.20-22：專案資訊與 Law_* 欄位契約");
            }

            List<object> categoryResults = new List<object>();
            foreach (string categoryName in requiredCategories)
            {
                List<BuiltInCategory> builtInCategories;
                if (!TryResolveCodeIntegrityCategories(categoryName, out builtInCategories))
                {
                    categoryResults.Add(new
                    {
                        RequestedName = categoryName,
                        ResolvedCategories = (object)null,
                        Supported = false,
                        Count = (int?)null,
                        Samples = (object)null
                    });
                    AddCodeIntegrityFinding(
                        findings,
                        "category." + categoryName,
                        "UNKNOWN",
                        "warning",
                        "目前 API 檢查器不認得此類別名稱；請改用支援的內部名稱或中文別名。",
                        new { RequestedName = categoryName },
                        "REVIT_112.pdf p.14：模型必要構件類別契約");
                    continue;
                }

                List<Element> elements = new List<Element>();
                foreach (BuiltInCategory builtInCategory in builtInCategories)
                {
                    try
                    {
                        elements.AddRange(new FilteredElementCollector(doc)
                            .OfCategory(builtInCategory)
                            .WhereElementIsNotElementType()
                            .ToElements());
                    }
                    catch
                    {
                        // Some templates expose a category name but do not allow collection in every context.
                    }
                }
                List<object> samples = null;
                if (includeElementSamples)
                {
                    samples = elements
                        .Take(maxElementSamples)
                        .Select(element => (object)new
                        {
                            ElementId = element.Id.GetIdValue(),
                            Name = element.Name
                        })
                        .ToList();
                }

                categoryResults.Add(new
                {
                    RequestedName = categoryName,
                    ResolvedCategories = builtInCategories.Select(category => category.ToString()).ToList(),
                    Supported = true,
                    Count = elements.Count,
                    Samples = samples
                });
                bool exists = elements.Count > 0;
                AddCodeIntegrityFinding(
                    findings,
                    "category." + categoryName,
                    exists ? "PASS" : "FAIL",
                    exists ? "info" : "error",
                    exists
                        ? "必要模型類別已有元素。"
                        : "必要模型類別目前沒有實例元素。",
                    new
                    {
                        RequestedName = categoryName,
                        ResolvedCategories = builtInCategories.Select(category => category.ToString()).ToList(),
                        Count = elements.Count
                    },
                    "REVIT_112.pdf p.14：模型必要構件類別契約");
            }

            List<Element> areaElements = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Areas)
                .WhereElementIsNotElementType()
                .ToElements()
                .ToList();
            List<object> areaParameterResults = new List<object>();
            foreach (string parameterName in requiredAreaParameters)
            {
                List<object> matches = new List<object>();
                int hasValueCount = 0;
                foreach (Element area in areaElements)
                {
                    Parameter parameter = area.LookupParameter(parameterName);
                    if (parameter == null) continue;

                    string value = ReadCodeIntegrityParameterValue(parameter);
                    bool hasValue = HasCodeIntegrityParameterValue(parameter, value);
                    if (hasValue) hasValueCount++;
                    if (matches.Count < maxElementSamples)
                    {
                        matches.Add(new
                        {
                            ElementId = area.Id.GetIdValue(),
                            Name = area.Name,
                            HasValue = hasValue,
                            Value = value,
                            ValueStatus = GetCodeIntegrityValueStatus(parameter, value)
                        });
                    }
                }

                bool exists = matches.Count > 0;
                string status = !exists ? "FAIL" : hasValueCount > 0 ? "PASS" : "WARNING";
                string severity = !exists ? "error" : hasValueCount > 0 ? "info" : "warning";
                areaParameterResults.Add(new
                {
                    Name = parameterName,
                    Scope = "Areas",
                    AreaCount = areaElements.Count,
                    ExistsOnAnyArea = exists,
                    HasValueCount = hasValueCount,
                    Samples = matches
                });
                AddCodeIntegrityFinding(
                    findings,
                    "area-parameter." + parameterName,
                    status,
                    severity,
                    !exists
                        ? "Area 元素找不到必要法規檢討欄位。"
                        : hasValueCount > 0
                            ? "Area 法規檢討欄位存在且已有至少一筆值。"
                            : "Area 法規檢討欄位存在但目前沒有填值。",
                    new
                    {
                        Name = parameterName,
                        Scope = "Areas",
                        AreaCount = areaElements.Count,
                        ExistsOnAnyArea = exists,
                        HasValueCount = hasValueCount
                    },
                    "REVIT_112.pdf p.34-35：Area 的 Law_建管-用途類組與 Law_技規-法定名稱欄位契約");
            }

            List<object> namedViewResults = new List<object>();
            List<object> areaPlanCoverageResults = new List<object>();
            if (checkNamedViews)
            {
                List<View> views = new FilteredElementCollector(doc)
                    .OfClass(typeof(View))
                    .Cast<View>()
                    .Where(view => !view.IsTemplate)
                    .ToList();

                foreach (string keyword in requiredViewKeywords)
                {
                    List<View> matches = views
                        .Where(view =>
                        {
                            string typeName = ReadCodeIntegrityViewTypeName(doc, view);
                            return (!string.IsNullOrWhiteSpace(view.Name)
                                    && view.Name.IndexOf(keyword, StringComparison.OrdinalIgnoreCase) >= 0)
                                || (!string.IsNullOrWhiteSpace(typeName)
                                    && typeName.IndexOf(keyword, StringComparison.OrdinalIgnoreCase) >= 0);
                        })
                        .OrderBy(view => view.Name)
                        .ToList();
                    List<View> areaPlanMatches = matches
                        .Where(view => view.ViewType == ViewType.AreaPlan)
                        .ToList();
                    int populatedAreaPlanCount = 0;
                    if (checkAreaPlanContent)
                    {
                        foreach (View areaPlan in areaPlanMatches)
                        {
                            int? areaCount = TryCountCodeIntegrityAreasInView(doc, areaPlan);
                            string coverageStatus = !areaCount.HasValue
                                ? "UNKNOWN"
                                : areaCount.Value > 0 ? "PASS" : "WARNING";
                            if (areaCount.HasValue && areaCount.Value > 0)
                            {
                                populatedAreaPlanCount++;
                            }
                            areaPlanCoverageResults.Add(new
                            {
                                Keyword = keyword,
                                ElementId = areaPlan.Id.GetIdValue(),
                                ViewName = areaPlan.Name,
                                TypeName = ReadCodeIntegrityViewTypeName(doc, areaPlan),
                                AreaCount = areaCount,
                                Status = coverageStatus
                            });
                            AddCodeIntegrityFinding(
                                findings,
                                "area-plan-content." + keyword + "." + areaPlan.Id.GetIdValue(),
                                coverageStatus,
                                coverageStatus == "PASS" ? "info" : "warning",
                                coverageStatus == "PASS"
                                    ? "匹配的 AreaPlan 目前含有 Area 實例。"
                                    : coverageStatus == "WARNING"
                                        ? "匹配的 AreaPlan 已存在，但目前沒有 Area 實例；不可直接交給面積計算。"
                                        : "無法讀取匹配 AreaPlan 的 Area 實例數量。",
                                new
                                {
                                    Keyword = keyword,
                                    ViewId = areaPlan.Id.GetIdValue(),
                                    ViewName = areaPlan.Name,
                                    AreaCount = areaCount
                                },
                                "REVIT_112.pdf p.22-34：面積圖 AreaPlan 與 Area 實例契約");
                        }
                    }

                    bool exists = areaPlanMatches.Count > 0;
                    string viewStatus = exists ? "PASS" : matches.Count > 0 ? "WARNING" : "FAIL";
                    namedViewResults.Add(new
                    {
                        Keyword = keyword,
                        Exists = matches.Count > 0,
                        AreaPlanMatchCount = areaPlanMatches.Count,
                        PopulatedAreaPlanCount = checkAreaPlanContent ? populatedAreaPlanCount : (int?)null,
                        Matches = matches.Select(view => new
                        {
                            ElementId = view.Id.GetIdValue(),
                            Name = view.Name,
                            ViewType = view.ViewType.ToString(),
                            TypeName = ReadCodeIntegrityViewTypeName(doc, view)
                        }).ToList()
                    });
                    AddCodeIntegrityFinding(
                        findings,
                        "view.keyword." + keyword,
                        viewStatus,
                        viewStatus == "PASS" ? "info" : viewStatus == "WARNING" ? "warning" : "error",
                        viewStatus == "PASS"
                            ? "必要 AreaPlan 圖面類型名稱已找到。"
                            : viewStatus == "WARNING"
                                ? "找到關鍵字，但沒有對應的 AreaPlan；只有明細表或其他視圖不足以支撐面積圖檢討。"
                                : "找不到必要圖面/面積視圖名稱關鍵字。",
                        new
                        {
                            Keyword = keyword,
                            MatchCount = matches.Count,
                            AreaPlanMatchCount = areaPlanMatches.Count,
                            PopulatedAreaPlanCount = checkAreaPlanContent ? populatedAreaPlanCount : (int?)null
                        },
                        "REVIT_112.pdf p.22-34：地籍、綠化、開挖、防火區劃與樓地板面積圖");
                }
            }
            else
            {
                AddCodeIntegrityFinding(
                    findings,
                    "named-views.skipped",
                    "UNKNOWN",
                    "info",
                    "呼叫端要求略過指定視圖名稱檢查。",
                    new { CheckNamedViews = false },
                    "呼叫端設定；未套用 REVIT_112 面積圖面契約");
            }

            if (checkNamedViews && !checkAreaPlanContent)
            {
                AddCodeIntegrityFinding(
                    findings,
                    "area-plan-content.skipped",
                    "UNKNOWN",
                    "info",
                    "呼叫端要求略過 AreaPlan 內容檢查；視圖名稱存在不代表有 Area 實例。",
                    new { CheckAreaPlanContent = false },
                    "呼叫端設定；未檢查 AreaPlan 內容");
            }

            AddCodeIntegrityFinding(
                findings,
                "ifc-export-profile",
                "UNKNOWN",
                "info",
                "本次唯讀盤點未執行 IFC 匯出，因此不宣稱目前匯出設定為 IFC 2x3 Coordination View。",
                new
                {
                    Checked = false,
                    ExpectedContract = "IFC 2x3 Coordination View"
                },
                "REVIT_112.pdf p.41：IFC 匯出操作契約；需另以實際匯出設定確認");

            List<string> blockingFindingIds = findings
                .Where(finding => finding.Status == "FAIL")
                .Select(finding => finding.Id)
                .ToList();
            List<string> carryForwardFindingIds = findings
                .Where(finding => finding.Status == "WARNING" || finding.Status == "UNKNOWN")
                .Select(finding => finding.Id)
                .ToList();
            string gateStatus = blockingFindingIds.Count > 0
                ? "BLOCKED"
                : carryForwardFindingIds.Count > 0 ? "CONDITIONAL" : "READY";

            return new
            {
                Success = true,
                ReadOnly = true,
                RulePackId = rulePackId,
                AuditRunId = auditRunId,
                CheckedAtUtc = checkedAtUtc,
                Document = new
                {
                    Title = doc.Title,
                    IsFamilyDocument = doc.IsFamilyDocument,
                    RevitVersion = doc.Application.VersionNumber
                },
                Summary = new
                {
                    Pass = findings.Count(finding => finding.Status == "PASS"),
                    Fail = findings.Count(finding => finding.Status == "FAIL"),
                    Warning = findings.Count(finding => finding.Status == "WARNING"),
                    Unknown = findings.Count(finding => finding.Status == "UNKNOWN"),
                    TotalFindings = findings.Count,
                    GateStatus = gateStatus,
                    BlockingFindings = blockingFindingIds.Count,
                    LegalComplianceEvaluated = false
                },
                Gate = new
                {
                    Status = gateStatus,
                    CanProceedToRuleReview = blockingFindingIds.Count == 0,
                    RequiresHumanDecision = carryForwardFindingIds.Count > 0,
                    BlockingFindingIds = blockingFindingIds,
                    CarryForwardFindingIds = carryForwardFindingIds,
                    LegalComplianceEvaluated = false
                },
                AuditInputs = new
                {
                    RequiredProjectParameters = requiredProjectParameters,
                    RequiredAreaParameters = requiredAreaParameters,
                    RequiredLevelNames = requiredLevels,
                    RecommendedLevelNames = recommendedLevels,
                    RequiredCategories = requiredCategories,
                    CheckNamedViews = checkNamedViews,
                    CheckAreaPlanContent = checkAreaPlanContent,
                    RequiredViewNameKeywords = requiredViewKeywords,
                    IncludeElementSamples = includeElementSamples,
                    MaxElementSamples = maxElementSamples
                },
                Parameters = parameterResults,
                AreaParameters = areaParameterResults,
                Levels = levelResults,
                Categories = categoryResults,
                NamedViews = namedViewResults,
                AreaPlanCoverage = areaPlanCoverageResults,
                Findings = findings,
                Notes = new[]
                {
                    "本工具只檢查模型資料完整性，不替代建築師、技師或主管機關的法規判定。",
                    "REVIT_112.pdf 是操作契約來源；現行法規數值與適用範圍仍須由官方法規及案件 jurisdiction 重新確認。",
                    "(無)、（無）、<空白>、<無> 與單獨 '-' 會視為語意空值，不算有效法規輸入。",
                    "AreaPlan 有視圖不代表有 Area 實例；AreaPlanCoverage 必須通過後，該面積圖才可交給計算流程。",
                    "未列出的 IFC、幾何尺寸、面積計算與法規數值檢討，必須在資料完整後由專用規則流程執行。"
                }
            };
        }

        private static List<string> ReadCodeIntegrityStrings(JToken token, IEnumerable<string> defaults)
        {
            List<string> values = new List<string>();
            JArray array = token as JArray;
            if (array != null)
            {
                foreach (JToken item in array)
                {
                    string value = item.Value<string>()?.Trim();
                    if (!string.IsNullOrWhiteSpace(value)
                        && !values.Contains(value, StringComparer.OrdinalIgnoreCase))
                    {
                        values.Add(value);
                    }
                }
            }

            if (values.Count == 0)
            {
                values.AddRange(defaults);
            }
            return values;
        }

        private static string ReadCodeIntegrityParameterValue(Parameter parameter)
        {
            if (parameter == null) return null;
            try
            {
                return parameter.AsValueString() ?? parameter.AsString();
            }
            catch
            {
                return null;
            }
        }

        private static bool HasCodeIntegrityParameterValue(Parameter parameter, string value)
        {
            return parameter != null
                && parameter.HasValue
                && !IsCodeIntegrityEmptyDisplayValue(value);
        }

        private static string GetCodeIntegrityValueStatus(Parameter parameter, string value)
        {
            if (parameter == null) return "PARAMETER_NOT_FOUND";
            if (HasCodeIntegrityParameterValue(parameter, value)) return "VALUE";
            if (IsCodeIntegrityEmptyDisplayValue(value)) return "EMPTY_SENTINEL";
            return "EMPTY";
        }

        private static bool IsCodeIntegrityEmptyDisplayValue(string value)
        {
            string normalized = value?.Trim();
            return string.IsNullOrWhiteSpace(normalized)
                || normalized == "(無)"
                || normalized == "（無）"
                || normalized == "<空白>"
                || normalized == "<無>"
                || normalized == "-";
        }

        private static int? TryCountCodeIntegrityAreasInView(Document doc, View view)
        {
            if (doc == null || view == null || view.ViewType != ViewType.AreaPlan)
            {
                return null;
            }

            try
            {
                return new FilteredElementCollector(doc, view.Id)
                    .OfCategory(BuiltInCategory.OST_Areas)
                    .WhereElementIsNotElementType()
                    .ToElements()
                    .Count;
            }
            catch
            {
                return null;
            }
        }

        private static string ReadCodeIntegrityViewTypeName(Document doc, View view)
        {
            try
            {
                ElementId typeId = view?.GetTypeId();
                if (typeId == null || typeId == ElementId.InvalidElementId) return null;
                Element typeElement = doc.GetElement(typeId);
                return typeElement?.Name;
            }
            catch
            {
                return null;
            }
        }

        private static bool TryResolveCodeIntegrityCategories(
            string requestedName,
            out List<BuiltInCategory> builtInCategories)
        {
            string normalized = (requestedName ?? string.Empty).Trim().ToLowerInvariant();
            switch (normalized)
            {
                case "walls":
                case "wall":
                case "牆":
                case "牆體":
                    builtInCategories = new List<BuiltInCategory> { BuiltInCategory.OST_Walls };
                    return true;
                case "floors":
                case "floor":
                case "樓板":
                    builtInCategories = new List<BuiltInCategory> { BuiltInCategory.OST_Floors };
                    return true;
                case "doors":
                case "door":
                case "門":
                    builtInCategories = new List<BuiltInCategory> { BuiltInCategory.OST_Doors };
                    return true;
                case "windows":
                case "window":
                case "窗":
                    builtInCategories = new List<BuiltInCategory> { BuiltInCategory.OST_Windows };
                    return true;
                case "columns":
                case "column":
                case "柱":
                    builtInCategories = new List<BuiltInCategory>
                    {
                        BuiltInCategory.OST_Columns,
                        BuiltInCategory.OST_StructuralColumns
                    };
                    return true;
                case "structuralcolumns":
                case "structural columns":
                case "結構柱":
                    builtInCategories = new List<BuiltInCategory> { BuiltInCategory.OST_StructuralColumns };
                    return true;
                case "structuralframing":
                case "structural framing":
                case "beams":
                case "beam":
                case "梁":
                case "樑":
                    builtInCategories = new List<BuiltInCategory> { BuiltInCategory.OST_StructuralFraming };
                    return true;
                case "stairs":
                case "stair":
                case "樓梯":
                    builtInCategories = new List<BuiltInCategory> { BuiltInCategory.OST_Stairs };
                    return true;
                default:
                    builtInCategories = null;
                    return false;
            }
        }

        private static void AddCodeIntegrityFinding(
            ICollection<CodeIntegrityFinding> findings,
            string id,
            string status,
            string severity,
            string message,
            object evidence,
            string reference)
        {
            findings.Add(new CodeIntegrityFinding
            {
                Id = id,
                Status = status,
                Severity = severity,
                Message = message,
                Evidence = evidence,
                Reference = reference
            });
        }

        private sealed class CodeIntegrityFinding
        {
            public string Id { get; set; }
            public string Status { get; set; }
            public string Severity { get; set; }
            public string Message { get; set; }
            public object Evidence { get; set; }
            public string Reference { get; set; }
        }
    }
}
