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
        #region 詳圖元件管理

        /// <summary>
        /// 取得詳圖元件列表
        /// </summary>
        private object GetDetailComponents(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            string familyFilter = parameters?["familyName"]?.Value<string>() ?? "";

            var detailItems = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_DetailComponents)
                .WhereElementIsNotElementType()
                .Where(e =>
                {
                    var fi = e as FamilyInstance;
                    if (fi == null) return false;
                    return string.IsNullOrEmpty(familyFilter) || fi.Symbol.FamilyName.Contains(familyFilter);
                })
                .Select(e =>
                {
                    var fi = e as FamilyInstance;
                    return new
                    {
                        ElementId = fi.Id.GetIdValue(),
                        FamilyName = fi.Symbol.FamilyName,
                        TypeName = fi.Symbol.Name,
                        OwnerViewId = fi.OwnerViewId.GetIdValue(),
                        Parameters = GetAllDetailParameters(fi)
                    };
                })
                .ToList();

            return new
            {
                Count = detailItems.Count,
                Items = detailItems
            };
        }

        private Dictionary<string, string> GetAllDetailParameters(Element elem)
        {
            var result = new Dictionary<string, string>();
            foreach (Parameter p in elem.Parameters)
            {
                string val = p.AsValueString() ?? p.AsString() ?? "";
                if (!string.IsNullOrEmpty(val))
                {
                    result[p.Definition.Name] = val;
                }
            }
            return result;
        }

        /// <summary>
        /// 同步詳圖元件編號與圖紙編號 (v3.6: Dual Safeguard Mode)
        /// </summary>
        private object SyncDetailComponentNumbers()
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            int updatedInstances = 0;
            int typesCreated = 0;
            int firstMethodMatches = 0;
            int secondMethodMatches = 0;
            int skippedBySafeguard = 0;
            var processedTypes = new HashSet<string>();

            // 1. 建立 ViewId → Sheet 對應表
            var viewToSheetMap = new Dictionary<IdType, ViewSheet>();
            var sheets = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .ToList();

            foreach (var sheet in sheets)
            {
                viewToSheetMap[sheet.Id.GetIdValue()] = sheet;
                foreach (var vpId in sheet.GetAllViewports())
                {
                    var vp = doc.GetElement(vpId) as Viewport;
                    if (vp != null)
                        viewToSheetMap[vp.ViewId.GetIdValue()] = sheet;
                }
            }

            // 2. 找出所有 AE-圖號 元件
            var categories = new List<BuiltInCategory>
            {
                BuiltInCategory.OST_DetailComponents,
                BuiltInCategory.OST_GenericAnnotation
            };

            var allInstances = new List<FamilyInstance>();
            foreach (var cat in categories)
            {
                var instances = new FilteredElementCollector(doc)
                    .OfCategory(cat)
                    .WhereElementIsNotElementType()
                    .Where(e =>
                    {
                        var fi = e as FamilyInstance;
                        return fi != null && fi.Symbol.FamilyName.Contains("AE-圖號");
                    })
                    .Cast<FamilyInstance>();
                allInstances.AddRange(instances);
            }

            using (TransactionGroup tg = new TransactionGroup(doc, "同步詳圖元件編號"))
            {
                tg.Start();

                foreach (var instance in allInstances)
                {
                    IdType ownerViewId = instance.OwnerViewId.GetIdValue();
                    ViewSheet sheet = null;

                    if (!viewToSheetMap.TryGetValue(ownerViewId, out sheet))
                    {
                        Element ownerView = doc.GetElement(ownerViewId.ToElementId());
                        sheet = ownerView as ViewSheet;
                        if (sheet == null) continue;
                    }

                    string sheetNumber = sheet.SheetNumber;
                    string sheetName = sheet.Name;
                    FamilySymbol currentSymbol = instance.Symbol;

                    // v3.6: 保留雙路徑守門，避免誤改共用/標準詳圖。
                    string matchMode = GetDetailTypeSheetNumberMatchMode(currentSymbol.Name, sheetNumber);
                    if (matchMode == null)
                    {
                        skippedBySafeguard++;
                        continue;
                    }

                    string typeKey = $"{currentSymbol.FamilyName}:{currentSymbol.Name}";
                    if (processedTypes.Contains(typeKey)) continue;

                    using (Transaction t = new Transaction(doc, "同步元件類型"))
                    {
                        t.Start();

                        Parameter pTypeSheetNum = currentSymbol.LookupParameter("詳圖圖號");
                        if (pTypeSheetNum != null && !pTypeSheetNum.IsReadOnly)
                            pTypeSheetNum.Set(sheetNumber);

                        Parameter pTypeSheetName = currentSymbol.LookupParameter("圖說名稱");
                        if (pTypeSheetName != null && !pTypeSheetName.IsReadOnly)
                            pTypeSheetName.Set(sheetName);

                        t.Commit();
                        updatedInstances++;
                        if (matchMode == "type_name_starts_with_sheet_number")
                            firstMethodMatches++;
                        else if (matchMode == "sheet_number_starts_with_type_name_prefix")
                            secondMethodMatches++;
                        processedTypes.Add(typeKey);
                    }
                }
                tg.Assimilate();
            }

            return new
            {
                Success = true,
                UpdatedInstances = updatedInstances,
                TypesCreated = typesCreated,
                FirstMethodMatches = firstMethodMatches,
                SecondMethodMatches = secondMethodMatches,
                SkippedBySafeguard = skippedBySafeguard,
                Message = $"同步完成：更新了 {updatedInstances} 個標頭元件，建立了 {typesCreated} 個新類型。第一種作法 {firstMethodMatches} 筆，第二種作法 {secondMethodMatches} 筆，安全跳過 {skippedBySafeguard} 筆。"
            };
        }

        private string GetDetailTypeSheetNumberMatchMode(string typeName, string sheetNumber)
        {
            if (string.IsNullOrWhiteSpace(typeName) || string.IsNullOrWhiteSpace(sheetNumber))
                return null;

            string normalizedTypeName = typeName.Trim();
            string normalizedSheetNumber = sheetNumber.Trim();

            if (normalizedTypeName.Equals(normalizedSheetNumber, StringComparison.OrdinalIgnoreCase) ||
                normalizedTypeName.StartsWith(normalizedSheetNumber + "-", StringComparison.OrdinalIgnoreCase))
            {
                return "type_name_starts_with_sheet_number";
            }

            foreach (string typeNamePrefix in GetDetailTypeNameSheetPrefixCandidates(normalizedTypeName)
                .OrderByDescending(p => p.Length))
            {
                if (!IsUsableSheetNumberPrefix(typeNamePrefix))
                    continue;

                if (normalizedSheetNumber.StartsWith(typeNamePrefix, StringComparison.OrdinalIgnoreCase))
                    return "sheet_number_starts_with_type_name_prefix";
            }

            return null;
        }

        private IEnumerable<string> GetDetailTypeNameSheetPrefixCandidates(string typeName)
        {
            if (string.IsNullOrWhiteSpace(typeName))
                yield break;

            string normalizedTypeName = typeName.Trim();
            yield return normalizedTypeName;

            for (int i = 0; i < normalizedTypeName.Length; i++)
            {
                if (normalizedTypeName[i] == '-')
                {
                    string prefix = normalizedTypeName.Substring(0, i).Trim();
                    if (!string.IsNullOrEmpty(prefix))
                        yield return prefix;
                }
            }
        }

        private bool IsUsableSheetNumberPrefix(string prefix)
        {
            if (string.IsNullOrWhiteSpace(prefix))
                return false;

            string normalizedPrefix = prefix.Trim();
            return normalizedPrefix.Length >= 4 && normalizedPrefix.Any(char.IsDigit);
        }

        /// <summary>
        /// 建立詳圖元件類型（依據圖紙編號）
        /// </summary>
        private object CreateDetailComponentType(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            string sheetNumber = parameters?["sheetNumber"]?.Value<string>();
            string detailName = parameters?["detailName"]?.Value<string>();
            string familyName = parameters?["familyName"]?.Value<string>();
            string detailNumber = parameters?["detailNumber"]?.Value<string>() ?? "1";

            if (string.IsNullOrEmpty(sheetNumber))
                throw new Exception("必須提供 sheetNumber 參數");
            if (string.IsNullOrEmpty(detailName))
                throw new Exception("必須提供 detailName 參數");

            var sheet = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .FirstOrDefault(s => s.SheetNumber == sheetNumber);

            if (sheet == null)
                throw new Exception($"找不到圖紙編號: {sheetNumber}");

            string sheetName = sheet.Name;

            // 尋找基礎 FamilySymbol
            FamilySymbol baseSymbol = null;
            if (!string.IsNullOrEmpty(familyName))
            {
                baseSymbol = new FilteredElementCollector(doc)
                    .OfClass(typeof(FamilySymbol))
                    .Cast<FamilySymbol>()
                    .FirstOrDefault(s => s.FamilyName != null &&
                        (s.FamilyName.Equals(familyName, StringComparison.OrdinalIgnoreCase) || s.FamilyName.Contains(familyName)));
            }
            else
            {
                baseSymbol = new FilteredElementCollector(doc)
                    .OfClass(typeof(FamilySymbol))
                    .Cast<FamilySymbol>()
                    .FirstOrDefault(s => s.FamilyName != null && s.FamilyName.Contains("AE-圖號"));
            }

            if (baseSymbol == null)
                throw new Exception($"找不到基礎詳圖項目族群: {familyName ?? "AE-圖號"}");

            string targetTypeName = BuildDetailComponentTypeName(sheetNumber, sheetName, detailName);

            // 檢查是否已存在
            var existingSymbol = new FilteredElementCollector(doc)
                .OfClass(typeof(FamilySymbol))
                .Cast<FamilySymbol>()
                .FirstOrDefault(s => s.FamilyName == baseSymbol.FamilyName && s.Name == targetTypeName);

            if (existingSymbol != null)
            {
                return new
                {
                    Success = false,
                    Error = $"類型已存在: {targetTypeName}",
                    ExistingTypeId = existingSymbol.Id.GetIdValue()
                };
            }

            using (Transaction t = new Transaction(doc, "建立詳圖元件類型"))
            {
                t.Start();

                var newSymbol = baseSymbol.Duplicate(targetTypeName) as FamilySymbol;
                if (newSymbol == null)
                    throw new Exception($"複製類型失敗: {targetTypeName}");

                Parameter pTypeSheetNum = newSymbol.LookupParameter("詳圖圖號");
                if (pTypeSheetNum != null && !pTypeSheetNum.IsReadOnly)
                    pTypeSheetNum.Set(sheetNumber);

                Parameter pTypeSheetName = newSymbol.LookupParameter("圖說名稱");
                if (pTypeSheetName != null && !pTypeSheetName.IsReadOnly)
                    pTypeSheetName.Set(sheetName ?? "");

                Parameter pTypeDetailName = newSymbol.LookupParameter("詳圖名稱");
                if (pTypeDetailName != null && !pTypeDetailName.IsReadOnly)
                    pTypeDetailName.Set(detailName ?? "");

                Parameter pTypeDetailNumber = newSymbol.LookupParameter("詳圖編號");
                if (pTypeDetailNumber != null && !pTypeDetailNumber.IsReadOnly)
                    pTypeDetailNumber.Set(detailNumber);

                t.Commit();

                return new
                {
                    Success = true,
                    TypeId = newSymbol.Id.GetIdValue(),
                    TypeName = newSymbol.Name,
                    SheetNumber = sheetNumber,
                    SheetName = sheetName,
                    DetailName = detailName,
                    DetailNumber = detailNumber
                };
            }
        }

        private object CreateDetailComponentTypesFromMetadata(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            string familyName = parameters?["familyName"]?.Value<string>() ?? "AE-圖號詳圖編號標頭-3.5mm";
            bool dryRun = parameters?["dryRun"]?.Value<bool>() ?? true;
            bool overwriteExisting = parameters?["overwriteExisting"]?.Value<bool>() ?? false;
            var inputItems = parameters?["items"] as JArray;

            if (inputItems == null || inputItems.Count == 0)
                throw new Exception("請提供 items 陣列，每筆需包含 sheetNumber、sheetName、detailName，可選 detailNumber");

            FamilySymbol baseSymbol = FindDetailComponentBaseSymbol(doc, familyName);
            if (baseSymbol == null)
                throw new Exception($"找不到詳圖項目類型族群: {familyName}");

            var plans = new List<DetailComponentMetadataPlan>();
            foreach (JToken item in inputItems)
            {
                string sheetNumber = item?["sheetNumber"]?.Value<string>()?.Trim() ?? "";
                string sheetName = item?["sheetName"]?.Value<string>()?.Trim() ?? "";
                string detailName = item?["detailName"]?.Value<string>()?.Trim() ?? "";
                string detailNumber = item?["detailNumber"]?.Value<string>()?.Trim() ?? "";
                string targetTypeName = item?["typeName"]?.Value<string>()?.Trim();

                var plan = new DetailComponentMetadataPlan
                {
                    SheetNumber = sheetNumber,
                    SheetName = sheetName,
                    DetailName = detailName,
                    DetailNumber = detailNumber
                };

                if (string.IsNullOrWhiteSpace(sheetNumber) ||
                    string.IsNullOrWhiteSpace(sheetName) ||
                    string.IsNullOrWhiteSpace(detailName))
                {
                    plan.Action = "invalid";
                    plan.Error = "sheetNumber、sheetName、detailName 皆為必要欄位";
                    plans.Add(plan);
                    continue;
                }

                plan.TargetTypeName = string.IsNullOrWhiteSpace(targetTypeName)
                    ? BuildDetailComponentTypeName(sheetNumber, sheetName, detailName)
                    : SanitizeElementTypeName(targetTypeName);

                FamilySymbol existingSymbol = FindFamilySymbol(doc, baseSymbol.FamilyName, plan.TargetTypeName);
                plan.ExistingTypeName = existingSymbol?.Name;
                plan.ExistingTypeId = existingSymbol?.Id.GetIdValue();
                plan.Action = existingSymbol == null ? "create" : (overwriteExisting ? "update" : "skip");
                plans.Add(plan);
            }

            if (dryRun)
            {
                return new
                {
                    Success = true,
                    DryRun = true,
                    FamilyName = baseSymbol.FamilyName,
                    Count = plans.Count,
                    Items = plans
                };
            }

            int created = 0;
            int updated = 0;
            int skipped = 0;
            int invalid = 0;
            var results = new List<object>();

            using (TransactionGroup tg = new TransactionGroup(doc, "從 PDF metadata 建立詳圖項目類型"))
            {
                tg.Start();

                foreach (var plan in plans)
                {
                    if (plan.Action == "invalid")
                    {
                        invalid++;
                        results.Add(new
                        {
                            plan.SheetNumber,
                            plan.SheetName,
                            plan.DetailNumber,
                            plan.DetailName,
                            plan.TargetTypeName,
                            Action = "invalid",
                            plan.Error
                        });
                        continue;
                    }

                    FamilySymbol symbol = FindFamilySymbol(doc, baseSymbol.FamilyName, plan.TargetTypeName);
                    if (symbol != null && !overwriteExisting)
                    {
                        skipped++;
                        results.Add(new
                        {
                            plan.SheetNumber,
                            plan.SheetName,
                            plan.DetailNumber,
                            plan.DetailName,
                            plan.TargetTypeName,
                            TypeId = symbol.Id.GetIdValue(),
                            Action = "skipped"
                        });
                        continue;
                    }

                    using (Transaction t = new Transaction(doc, "建立 PDF 詳圖項目類型"))
                    {
                        t.Start();

                        string action;
                        if (symbol == null)
                        {
                            symbol = baseSymbol.Duplicate(plan.TargetTypeName) as FamilySymbol;
                            if (symbol == null)
                                throw new Exception($"複製類型失敗: {plan.TargetTypeName}");

                            created++;
                            action = "created";
                        }
                        else
                        {
                            updated++;
                            action = "updated";
                        }

                        SetWritableParameter(symbol, "詳圖圖號", plan.SheetNumber);
                        SetWritableParameter(symbol, "圖說名稱", plan.SheetName);
                        SetWritableParameter(symbol, "詳圖編號", plan.DetailNumber);
                        SetWritableParameter(symbol, "詳圖名稱", plan.DetailName);

                        t.Commit();

                        results.Add(new
                        {
                            plan.SheetNumber,
                            plan.SheetName,
                            plan.DetailNumber,
                            plan.DetailName,
                            plan.TargetTypeName,
                            TypeId = symbol.Id.GetIdValue(),
                            Action = action
                        });
                    }
                }

                tg.Assimilate();
            }

            return new
            {
                Success = true,
                DryRun = false,
                FamilyName = baseSymbol.FamilyName,
                Count = plans.Count,
                Created = created,
                Updated = updated,
                Skipped = skipped,
                Invalid = invalid,
                Items = results
            };
        }

        /// <summary>
        /// 列出族群符號
        /// </summary>
        private object CreateDetailComponentTypesFromSheetViewports(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            string sheetNumber = parameters?["sheetNumber"]?.Value<string>();
            string familyName = parameters?["familyName"]?.Value<string>() ?? "AE-圖號詳圖編號標頭-3.5mm";
            bool dryRun = parameters?["dryRun"]?.Value<bool>() ?? true;
            bool overwriteExisting = parameters?["overwriteExisting"]?.Value<bool>() ?? false;

            if (string.IsNullOrEmpty(sheetNumber))
                throw new Exception("請指定 sheetNumber 參數");

            var sheet = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .FirstOrDefault(s => s.SheetNumber.Equals(sheetNumber, StringComparison.OrdinalIgnoreCase));

            if (sheet == null)
                throw new Exception($"找不到圖紙: {sheetNumber}");

            FamilySymbol baseSymbol = FindDetailComponentBaseSymbol(doc, familyName);
            if (baseSymbol == null)
                throw new Exception($"找不到詳圖項目類型族群: {familyName}");

            var viewportPlans = new List<DetailViewportTypePlan>();
            foreach (ElementId vpId in sheet.GetAllViewports())
            {
                var viewport = doc.GetElement(vpId) as Viewport;
                if (viewport == null) continue;

                var view = doc.GetElement(viewport.ViewId) as View;
                if (view == null) continue;

                string detailNumber = GetViewportDetailNumber(viewport);
                string viewName = view.Name ?? "";
                string detailName = GetViewportDetailName(viewport, view);
                string targetTypeName = BuildDetailComponentTypeName(sheet.SheetNumber, sheet.Name, detailName);
                string legacyTypeName = BuildDetailComponentTypeName(sheet.SheetNumber, sheet.Name, viewName);
                FamilySymbol existingSymbol = FindFamilySymbol(doc, baseSymbol.FamilyName, targetTypeName)
                    ?? (targetTypeName == legacyTypeName ? null : FindFamilySymbol(doc, baseSymbol.FamilyName, legacyTypeName));
                bool willRename = existingSymbol != null && existingSymbol.Name != targetTypeName;

                viewportPlans.Add(new DetailViewportTypePlan
                {
                    ViewportId = viewport.Id.GetIdValue(),
                    ViewId = view.Id.GetIdValue(),
                    ViewName = viewName,
                    ViewType = view.ViewType.ToString(),
                    DetailSheetNumber = sheet.SheetNumber,
                    SheetName = sheet.Name,
                    DetailNumber = detailNumber,
                    DetailName = detailName,
                    TargetTypeName = targetTypeName,
                    LegacyTypeName = legacyTypeName,
                    ExistingTypeName = existingSymbol?.Name,
                    ExistingTypeId = existingSymbol?.Id.GetIdValue(),
                    Action = existingSymbol == null ? "create" : (overwriteExisting ? (willRename ? "rename_update" : "update") : "skip")
                });
            }

            if (dryRun)
            {
                return new
                {
                    Success = true,
                    DryRun = true,
                    SheetNumber = sheet.SheetNumber,
                    SheetName = sheet.Name,
                    FamilyName = baseSymbol.FamilyName,
                    Count = viewportPlans.Count,
                    Items = viewportPlans
                };
            }

            int created = 0;
            int updated = 0;
            int skipped = 0;
            var results = new List<object>();

            using (TransactionGroup tg = new TransactionGroup(doc, "從圖紙視埠建立詳圖標頭類型"))
            {
                tg.Start();

                foreach (var plan in viewportPlans)
                {
                    FamilySymbol symbol = FindFamilySymbol(doc, baseSymbol.FamilyName, plan.TargetTypeName)
                        ?? (plan.TargetTypeName == plan.LegacyTypeName ? null : FindFamilySymbol(doc, baseSymbol.FamilyName, plan.LegacyTypeName));
                    string previousTypeName = symbol?.Name;

                    if (symbol != null && !overwriteExisting)
                    {
                        skipped++;
                        results.Add(new
                        {
                            plan.ViewportId,
                            plan.ViewId,
                            plan.TargetTypeName,
                            Action = "skipped",
                            TypeId = symbol.Id.GetIdValue()
                        });
                        continue;
                    }

                    using (Transaction t = new Transaction(doc, "建立詳圖標頭類型"))
                    {
                        t.Start();

                        string action;
                        if (symbol == null)
                        {
                            symbol = baseSymbol.Duplicate(plan.TargetTypeName) as FamilySymbol;
                            if (symbol == null)
                                throw new Exception($"複製類型失敗: {plan.TargetTypeName}");

                            created++;
                            action = "created";
                        }
                        else
                        {
                            if (symbol.Name != plan.TargetTypeName)
                                symbol.Name = plan.TargetTypeName;

                            updated++;
                            action = previousTypeName == plan.TargetTypeName ? "updated" : "renamed_updated";
                        }

                        SetWritableParameter(symbol, "詳圖圖號", plan.DetailSheetNumber);
                        SetWritableParameter(symbol, "圖說名稱", plan.SheetName);
                        SetWritableParameter(symbol, "詳圖編號", plan.DetailNumber);
                        SetWritableParameter(symbol, "詳圖名稱", plan.DetailName);

                        t.Commit();

                        results.Add(new
                        {
                            plan.ViewportId,
                            plan.ViewId,
                            plan.ViewName,
                            plan.TargetTypeName,
                            PreviousTypeName = previousTypeName,
                            TypeId = symbol.Id.GetIdValue(),
                            Action = action,
                            DetailSheetNumber = plan.DetailSheetNumber,
                            SheetName = plan.SheetName,
                            DetailNumber = plan.DetailNumber,
                            DetailName = plan.DetailName
                        });
                    }
                }

                tg.Assimilate();
            }

            return new
            {
                Success = true,
                DryRun = false,
                SheetNumber = sheet.SheetNumber,
                SheetName = sheet.Name,
                FamilyName = baseSymbol.FamilyName,
                Count = viewportPlans.Count,
                Created = created,
                Updated = updated,
                Skipped = skipped,
                Items = results
            };
        }

        private object SyncDetailComponentSheetNumbersByTypeParameters(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            string familyName = parameters?["familyName"]?.Value<string>() ?? "AE-矩形框詳圖元件";
            bool dryRun = parameters?["dryRun"]?.Value<bool>() ?? true;
            var sheetNumberFilter = GetOptionalStringSet(parameters?["sheetNumbers"] ?? parameters?["sheetNumber"]);

            FamilySymbol baseSymbol = FindDetailComponentBaseSymbol(doc, familyName);
            if (baseSymbol == null)
                throw new Exception($"找不到詳圖項目類型族群: {familyName}");

            var matchesByKey = BuildSheetViewportMatchesByTypeParameters(doc, sheetNumberFilter);
            var symbols = new FilteredElementCollector(doc)
                .OfClass(typeof(FamilySymbol))
                .Cast<FamilySymbol>()
                .Where(s => s.FamilyName == baseSymbol.FamilyName)
                .ToList();

            int updated = 0;
            int skipped = 0;
            int notMatched = 0;
            int ambiguous = 0;
            var results = new List<object>();

            Transaction transaction = null;
            if (!dryRun)
            {
                transaction = new Transaction(doc, "依類型參數同步詳圖圖號");
                transaction.Start();
            }

            try
            {
                foreach (FamilySymbol symbol in symbols)
                {
                    string typeSheetName = GetParameterValue(symbol, "圖說名稱");
                    string typeDetailName = GetParameterValue(symbol, "詳圖名稱");
                    string currentSheetNumber = GetParameterValue(symbol, "詳圖圖號");
                    string lookupKey = BuildDetailTypeParameterKey(typeSheetName, typeDetailName);

                    if (string.IsNullOrEmpty(lookupKey) || !matchesByKey.TryGetValue(lookupKey, out var matches) || matches.Count == 0)
                    {
                        notMatched++;
                        results.Add(new
                        {
                            TypeId = symbol.Id.GetIdValue(),
                            TypeName = symbol.Name,
                            SheetName = typeSheetName,
                            DetailName = typeDetailName,
                            CurrentDetailSheetNumber = currentSheetNumber,
                            Action = "not_matched"
                        });
                        continue;
                    }

                    if (matches.Count > 1)
                    {
                        ambiguous++;
                        results.Add(new
                        {
                            TypeId = symbol.Id.GetIdValue(),
                            TypeName = symbol.Name,
                            SheetName = typeSheetName,
                            DetailName = typeDetailName,
                            CurrentDetailSheetNumber = currentSheetNumber,
                            Action = "ambiguous",
                            Matches = matches.Select(m => new
                            {
                                m.SheetNumber,
                                m.SheetName,
                                m.DetailName,
                                m.ViewName,
                                m.DetailNumber,
                                m.ViewportId,
                                m.ViewId
                            }).ToList()
                        });
                        continue;
                    }

                    var match = matches[0];
                    if (string.Equals(currentSheetNumber, match.SheetNumber, StringComparison.OrdinalIgnoreCase))
                    {
                        skipped++;
                        results.Add(new
                        {
                            TypeId = symbol.Id.GetIdValue(),
                            TypeName = symbol.Name,
                            SheetName = typeSheetName,
                            DetailName = typeDetailName,
                            CurrentDetailSheetNumber = currentSheetNumber,
                            TargetDetailSheetNumber = match.SheetNumber,
                            Action = "skip"
                        });
                        continue;
                    }

                    if (!dryRun)
                        SetWritableParameter(symbol, "詳圖圖號", match.SheetNumber);

                    updated++;
                    results.Add(new
                    {
                        TypeId = symbol.Id.GetIdValue(),
                        TypeName = symbol.Name,
                        SheetName = typeSheetName,
                        DetailName = typeDetailName,
                        PreviousDetailSheetNumber = currentSheetNumber,
                        TargetDetailSheetNumber = match.SheetNumber,
                        MatchedSheetName = match.SheetName,
                        MatchedDetailName = match.DetailName,
                        MatchedViewName = match.ViewName,
                        MatchedDetailNumber = match.DetailNumber,
                        Action = dryRun ? "update" : "updated"
                    });
                }

                transaction?.Commit();
            }
            catch
            {
                transaction?.RollBack();
                throw;
            }

            return new
            {
                Success = true,
                DryRun = dryRun,
                FamilyName = baseSymbol.FamilyName,
                SheetNumberFilter = sheetNumberFilter.ToList(),
                TypeCount = symbols.Count,
                Updated = updated,
                Skipped = skipped,
                NotMatched = notMatched,
                Ambiguous = ambiguous,
                Items = results
            };
        }

        private class DetailViewportTypePlan
        {
            public IdType ViewportId { get; set; }
            public IdType ViewId { get; set; }
            public string ViewName { get; set; }
            public string ViewType { get; set; }
            public string DetailSheetNumber { get; set; }
            public string SheetName { get; set; }
            public string DetailNumber { get; set; }
            public string DetailName { get; set; }
            public string TargetTypeName { get; set; }
            public string LegacyTypeName { get; set; }
            public string ExistingTypeName { get; set; }
            public IdType? ExistingTypeId { get; set; }
            public string Action { get; set; }
        }

        private class DetailComponentMetadataPlan
        {
            public string SheetNumber { get; set; }
            public string SheetName { get; set; }
            public string DetailNumber { get; set; }
            public string DetailName { get; set; }
            public string TargetTypeName { get; set; }
            public string ExistingTypeName { get; set; }
            public IdType? ExistingTypeId { get; set; }
            public string Action { get; set; }
            public string Error { get; set; }
        }

        private class DetailTypeSheetMatch
        {
            public string SheetNumber { get; set; }
            public string SheetName { get; set; }
            public string DetailName { get; set; }
            public string ViewName { get; set; }
            public string DetailNumber { get; set; }
            public IdType ViewportId { get; set; }
            public IdType ViewId { get; set; }
        }

        private FamilySymbol FindDetailComponentBaseSymbol(Document doc, string familyName)
        {
            var symbols = new FilteredElementCollector(doc)
                .OfClass(typeof(FamilySymbol))
                .Cast<FamilySymbol>()
                .Where(s => s.FamilyName != null)
                .ToList();

            return symbols.FirstOrDefault(s => s.FamilyName.Equals(familyName, StringComparison.OrdinalIgnoreCase))
                ?? symbols.FirstOrDefault(s => s.FamilyName.Contains(familyName));
        }

        private FamilySymbol FindFamilySymbol(Document doc, string familyName, string typeName)
        {
            return new FilteredElementCollector(doc)
                .OfClass(typeof(FamilySymbol))
                .Cast<FamilySymbol>()
                .FirstOrDefault(s => s.FamilyName == familyName && s.Name == typeName);
        }

        private string BuildDetailComponentTypeName(string sheetNumber, string sheetName, string detailName)
        {
            return SanitizeElementTypeName($"{sheetNumber}-{sheetName}-{detailName}");
        }

        private string SanitizeElementTypeName(string typeName)
        {
            if (string.IsNullOrWhiteSpace(typeName))
                return "";

            var replacements = new Dictionary<char, char>
            {
                ['\\'] = '／',
                [':'] = '：',
                ['{'] = '（',
                ['}'] = '）',
                ['['] = '（',
                [']'] = '）',
                ['|'] = '｜',
                [';'] = '；',
                ['<'] = '＜',
                ['>'] = '＞',
                ['?'] = '？',
                ['`'] = '＇',
                ['~'] = '～'
            };

            var chars = typeName.Trim().Select(c =>
                char.IsControl(c) ? ' ' : (replacements.TryGetValue(c, out char replacement) ? replacement : c));

            return string.Join("", chars).Trim();
        }

        private string GetViewportDetailNumber(Viewport viewport)
        {
            Parameter detailNumberParam = viewport.get_Parameter(BuiltInParameter.VIEWPORT_DETAIL_NUMBER)
                ?? viewport.LookupParameter("詳圖編號");
            return detailNumberParam?.AsString()
                ?? detailNumberParam?.AsValueString()
                ?? "";
        }

        private string GetViewportDetailName(Viewport viewport, View view)
        {
            string titleOnSheet = GetFirstParameterValue(
                new[] { viewport as Element, view as Element },
                "圖紙上的標題",
                "Title on Sheet");
            if (!string.IsNullOrWhiteSpace(titleOnSheet))
                return titleOnSheet.Trim();

            string viewNameParameter = GetFirstParameterValue(
                new[] { viewport as Element, view as Element },
                "視圖名稱",
                "View Name");
            if (!string.IsNullOrWhiteSpace(viewNameParameter))
                return viewNameParameter.Trim();

            return view?.Name ?? "";
        }

        private string GetFirstParameterValue(IEnumerable<Element> elements, params string[] parameterNames)
        {
            foreach (Element element in elements.Where(e => e != null))
            {
                foreach (string parameterName in parameterNames)
                {
                    Parameter parameter = element.LookupParameter(parameterName);
                    string value = parameter?.AsString() ?? parameter?.AsValueString() ?? "";
                    if (!string.IsNullOrWhiteSpace(value))
                        return value;
                }

                var view = element as View;
                Parameter titleParameter = view?.get_Parameter(BuiltInParameter.VIEW_DESCRIPTION);
                string titleValue = titleParameter?.AsString() ?? titleParameter?.AsValueString() ?? "";
                if (!string.IsNullOrWhiteSpace(titleValue))
                    return titleValue;
            }

            return "";
        }

        private Dictionary<string, List<DetailTypeSheetMatch>> BuildSheetViewportMatchesByTypeParameters(
            Document doc,
            HashSet<string> sheetNumberFilter)
        {
            var matchesByKey = new Dictionary<string, List<DetailTypeSheetMatch>>(StringComparer.OrdinalIgnoreCase);
            var sheets = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .Where(s => sheetNumberFilter.Count == 0 || sheetNumberFilter.Contains(s.SheetNumber));

            foreach (ViewSheet sheet in sheets)
            {
                foreach (ElementId viewportId in sheet.GetAllViewports())
                {
                    var viewport = doc.GetElement(viewportId) as Viewport;
                    if (viewport == null) continue;

                    var view = doc.GetElement(viewport.ViewId) as View;
                    if (view == null) continue;

                    string viewName = view.Name ?? "";
                    string detailName = GetViewportDetailName(viewport, view);
                    var match = new DetailTypeSheetMatch
                    {
                        SheetNumber = sheet.SheetNumber,
                        SheetName = sheet.Name,
                        DetailName = detailName,
                        ViewName = viewName,
                        DetailNumber = GetViewportDetailNumber(viewport),
                        ViewportId = viewport.Id.GetIdValue(),
                        ViewId = view.Id.GetIdValue()
                    };

                    AddDetailTypeSheetMatch(matchesByKey, sheet.Name, detailName, match);
                    if (!string.Equals(detailName, viewName, StringComparison.OrdinalIgnoreCase))
                        AddDetailTypeSheetMatch(matchesByKey, sheet.Name, viewName, match);
                }
            }

            return matchesByKey;
        }

        private void AddDetailTypeSheetMatch(
            Dictionary<string, List<DetailTypeSheetMatch>> matchesByKey,
            string sheetName,
            string detailName,
            DetailTypeSheetMatch match)
        {
            string key = BuildDetailTypeParameterKey(sheetName, detailName);
            if (string.IsNullOrEmpty(key))
                return;

            if (!matchesByKey.TryGetValue(key, out var matches))
            {
                matches = new List<DetailTypeSheetMatch>();
                matchesByKey[key] = matches;
            }

            if (!matches.Any(m => m.ViewportId.Equals(match.ViewportId)))
                matches.Add(match);
        }

        private string BuildDetailTypeParameterKey(string sheetName, string detailName)
        {
            string normalizedSheetName = NormalizeParameterKeyValue(sheetName);
            string normalizedDetailName = NormalizeParameterKeyValue(detailName);
            if (string.IsNullOrEmpty(normalizedSheetName) || string.IsNullOrEmpty(normalizedDetailName))
                return "";

            return $"{normalizedSheetName}\u001f{normalizedDetailName}";
        }

        private string NormalizeParameterKeyValue(string value)
        {
            return string.IsNullOrWhiteSpace(value) ? "" : value.Trim();
        }

        private string GetParameterValue(Element element, string parameterName)
        {
            Parameter parameter = element.LookupParameter(parameterName);
            return parameter?.AsString()
                ?? parameter?.AsValueString()
                ?? "";
        }

        private HashSet<string> GetOptionalStringSet(JToken token)
        {
            var values = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (token == null)
                return values;

            if (token is JArray array)
            {
                foreach (JToken item in array)
                {
                    string value = item?.Value<string>();
                    if (!string.IsNullOrWhiteSpace(value))
                        values.Add(value.Trim());
                }

                return values;
            }

            string singleValue = token.Value<string>();
            if (!string.IsNullOrWhiteSpace(singleValue))
                values.Add(singleValue.Trim());

            return values;
        }

        private void SetWritableParameter(Element element, string parameterName, string value)
        {
            Parameter parameter = element.LookupParameter(parameterName);
            if (parameter != null && !parameter.IsReadOnly)
                parameter.Set(value ?? "");
        }

        private object ListDetailComponentTypeParameters(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            string familyName = parameters?["familyName"]?.Value<string>() ?? "";

            var sheetFilters = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            string sheetNumber = parameters?["sheetNumber"]?.Value<string>();
            if (!string.IsNullOrWhiteSpace(sheetNumber))
                sheetFilters.Add(sheetNumber.Trim());

            JArray sheetNumbers = parameters?["sheetNumbers"] as JArray;
            if (sheetNumbers != null)
            {
                foreach (JToken token in sheetNumbers)
                {
                    string value = token?.Value<string>();
                    if (!string.IsNullOrWhiteSpace(value))
                        sheetFilters.Add(value.Trim());
                }
            }

            var items = new FilteredElementCollector(doc)
                .OfClass(typeof(FamilySymbol))
                .Cast<FamilySymbol>()
                .Where(s => string.IsNullOrWhiteSpace(familyName)
                    || string.Equals(s.FamilyName, familyName, StringComparison.OrdinalIgnoreCase)
                    || (s.FamilyName != null && s.FamilyName.IndexOf(familyName, StringComparison.OrdinalIgnoreCase) >= 0))
                .Select(s => new
                {
                    Id = s.Id.GetIdValue(),
                    FamilyName = s.FamilyName ?? "",
                    TypeName = s.Name ?? "",
                    SheetNumber = GetParameterValue(s, "詳圖圖號"),
                    SheetName = GetParameterValue(s, "圖說名稱"),
                    DetailNumber = GetParameterValue(s, "詳圖編號"),
                    DetailName = GetParameterValue(s, "詳圖名稱")
                })
                .Where(item => sheetFilters.Count == 0
                    || sheetFilters.Contains(item.SheetNumber)
                    || sheetFilters.Any(filter => item.TypeName.StartsWith(filter + "-", StringComparison.OrdinalIgnoreCase)))
                .OrderBy(item => item.SheetNumber)
                .ThenBy(item => item.DetailNumber)
                .ThenBy(item => item.DetailName)
                .ToList();

            return new
            {
                Success = true,
                Count = items.Count,
                Items = items
            };
        }

        private object ListFamilySymbols(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            string filterName = parameters?["filter"]?.Value<string>();

            var symbols = new FilteredElementCollector(doc)
                .OfClass(typeof(FamilySymbol))
                .Cast<FamilySymbol>()
                .Where(s => string.IsNullOrEmpty(filterName) ||
                           (s.FamilyName != null && s.FamilyName.Contains(filterName)) ||
                           (s.Name != null && s.Name.Contains(filterName)))
                .Select(s => new
                {
                    Id = s.Id.GetIdValue(),
                    Name = s.Name,
                    FamilyName = s.FamilyName ?? "<NULL>",
                    Category = s.Category?.Name ?? "<NO_CAT>"
                })
                .Take(100)
                .ToList();

            return new { Success = true, Symbols = symbols };
        }

        #endregion
    }
}
