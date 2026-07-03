using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
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
        private object SyncMaterialBoardFamilyTypes(JObject parameters)
        {
            Stopwatch sw = Stopwatch.StartNew();
            Document doc = _uiApp.ActiveUIDocument.Document;

            string familyName = parameters?["familyName"]?.Value<string>() ?? "AE-\u6750\u6599\u7248";
            string csvPath = ResolveMaterialBoardCsvPath(parameters?["csvPath"]?.Value<string>());
            bool dryRun = parameters?["dryRun"]?.Value<bool>() ?? !(parameters?["apply"]?.Value<bool>() ?? false);
            bool createMissingTypes = parameters?["createMissingTypes"]?.Value<bool>() ?? false;
            bool updateAtParameters = parameters?["updateAtParameters"]?.Value<bool>() ?? true;
            string atParameterPrefix = parameters?["atParameterPrefix"]?.Value<string>() ?? "@";
            var atParameterNames = GetMaterialBoardOptionalStringSet(parameters?["atParameterNames"]);

            List<MaterialBoardRow> rows = ReadMaterialBoardCsv(csvPath);
            if (rows.Count == 0)
            {
                throw new Exception($"No material rows were found in CSV: {csvPath}");
            }

            List<FamilySymbol> familySymbols = new FilteredElementCollector(doc)
                .OfClass(typeof(FamilySymbol))
                .Cast<FamilySymbol>()
                .Where(symbol => symbol.FamilyName != null &&
                    (symbol.FamilyName.Equals(familyName, StringComparison.OrdinalIgnoreCase) ||
                     symbol.FamilyName.IndexOf(familyName, StringComparison.OrdinalIgnoreCase) >= 0))
                .OrderBy(symbol => symbol.Name)
                .ToList();

            if (familySymbols.Count == 0)
            {
                throw new Exception($"Family was not found: {familyName}");
            }

            FamilySymbol baseSymbol = ResolveMaterialBoardBaseSymbol(familySymbols, parameters?["baseTypeName"]?.Value<string>());
            var symbolsByName = familySymbols
                .GroupBy(symbol => symbol.Name ?? "", StringComparer.OrdinalIgnoreCase)
                .ToDictionary(group => group.Key, group => group.ToList(), StringComparer.OrdinalIgnoreCase);

            Dictionary<string, List<FamilySymbol>> symbolsByMaterialCode = BuildMaterialBoardSymbolsByMaterialCode(doc, familySymbols, rows, out HashSet<IdType> materialMatchedSymbolIds);
            Dictionary<string, List<FamilySymbol>> symbolsByCode = BuildMaterialBoardSymbolsByCode(familySymbols, rows, materialMatchedSymbolIds);
            var plans = new List<MaterialBoardPlan>();
            var codeSet = new HashSet<string>(rows.Select(row => row.Code), StringComparer.OrdinalIgnoreCase);

            foreach (MaterialBoardRow row in rows)
            {
                string targetTypeName = BuildMaterialBoardTypeName(row);
                List<FamilySymbol> matches = new List<FamilySymbol>();

                if (symbolsByMaterialCode.TryGetValue(row.Code, out List<FamilySymbol> materialNameMatches))
                {
                    matches.AddRange(materialNameMatches);
                }

                if (matches.Count == 0 && symbolsByCode.TryGetValue(row.Code, out List<FamilySymbol> codeMatches))
                {
                    matches.AddRange(codeMatches);
                }

                if (matches.Count == 0 && symbolsByName.TryGetValue(targetTypeName, out List<FamilySymbol> nameMatches))
                {
                    matches.AddRange(nameMatches);
                }

                matches = matches.Distinct(new MaterialBoardSymbolComparer()).ToList();

                MaterialBoardPlan plan = new MaterialBoardPlan
                {
                    MaterialCode = row.Code,
                    MaterialName = row.Name,
                    TargetTypeName = targetTypeName
                };

                if (matches.Count > 1)
                {
                    plan.Action = "ambiguous";
                    plan.Warnings.Add("More than one family type matches this material code.");
                    plan.MatchedTypes = matches.Select(BuildMaterialBoardTypeSnapshot).ToList();
                    plans.Add(plan);
                    continue;
                }

                FamilySymbol symbol = matches.FirstOrDefault();
                if (symbol == null)
                {
                    plan.Action = createMissingTypes ? "create" : "missing";
                    plan.Warnings.Add(createMissingTypes
                        ? "No matching type was found; a new type will be duplicated from the base type."
                        : "No matching type was found. Re-run with createMissingTypes=true if a new type should be created.");
                    if (createMissingTypes)
                        BuildMaterialBoardParameterChanges(doc, baseSymbol, row, updateAtParameters, atParameterPrefix, atParameterNames, plan, false);
                    plans.Add(plan);
                    continue;
                }

                plan.Symbol = symbol;
                plan.TypeId = symbol.Id.GetIdValue();
                plan.CurrentTypeName = symbol.Name;
                plan.CurrentMaterialCode = GetMaterialBoardCodeFromSymbol(symbol, codeSet);
                plan.Action = symbol.Name == targetTypeName ? "update" : "rename_update";

                FamilySymbol nameConflict = FindMaterialBoardTypeNameConflict(familySymbols, symbol, targetTypeName);
                if (nameConflict != null)
                {
                    plan.Action = "name_conflict";
                    plan.Warnings.Add($"Target type name is already used by ElementId {nameConflict.Id.GetIdValue()}.");
                    plan.ConflictType = BuildMaterialBoardTypeSnapshot(nameConflict);
                }

                BuildMaterialBoardParameterChanges(doc, symbol, row, updateAtParameters, atParameterPrefix, atParameterNames, plan, true);
                if (plan.Action == "update" && plan.ParameterChanges.Count == 0 && !HasMaterialBoardMaterialChanges(plan.MaterialChange) && plan.UnsupportedParameters.Count == 0)
                {
                    plan.Action = "no_change";
                }

                plans.Add(plan);
            }

            List<object> unmatchedFamilyTypes = familySymbols
                .Where(symbol =>
                {
                    string code = GetMaterialBoardCodeFromSymbol(symbol, codeSet);
                    if (!string.IsNullOrWhiteSpace(code))
                        return false;

                    return !rows.Any(row => string.Equals(symbol.Name, BuildMaterialBoardTypeName(row), StringComparison.OrdinalIgnoreCase));
                })
                .Select(BuildMaterialBoardTypeSnapshot)
                .ToList();

            int conflictCount = plans.Count(plan => plan.Action == "name_conflict" || plan.Action == "ambiguous");
            if (!dryRun && conflictCount > 0)
            {
                throw new Exception("Material board sync has conflicts. Run dryRun=true and resolve ambiguous/name_conflict items before applying.");
            }

            int created = 0;
            int renamed = 0;
            int updated = 0;
            int unchanged = plans.Count(plan => plan.Action == "no_change");
            int missing = plans.Count(plan => plan.Action == "missing");
            var failures = new List<object>();

            if (!dryRun)
            {
                using (Transaction trans = new Transaction(doc, "Sync AE material board types"))
                {
                    trans.Start();

                    foreach (MaterialBoardPlan plan in plans.Where(p => p.Action == "create" || p.Action == "update" || p.Action == "rename_update"))
                    {
                        FamilySymbol symbol = plan.Symbol;
                        string previousTypeName = symbol?.Name;

                        try
                        {
                            if (symbol == null)
                            {
                                symbol = baseSymbol.Duplicate(plan.TargetTypeName) as FamilySymbol;
                                if (symbol == null)
                                {
                                    failures.Add(new { plan.MaterialCode, plan.TargetTypeName, Error = "Failed to duplicate base type." });
                                    continue;
                                }

                                plan.TypeId = symbol.Id.GetIdValue();
                                created++;
                            }
                            else if (!string.Equals(symbol.Name, plan.TargetTypeName, StringComparison.OrdinalIgnoreCase))
                            {
                                symbol.Name = plan.TargetTypeName;
                                renamed++;
                            }

                            if (HasMaterialBoardMaterialChanges(plan.MaterialChange))
                            {
                                Material material = doc.GetElement(plan.MaterialChange.MaterialId) as Material;
                                if (material == null)
                                {
                                    failures.Add(new
                                    {
                                        plan.MaterialCode,
                                        plan.TargetTypeName,
                                        Error = "Material was not found while applying material changes."
                                    });
                                    continue;
                                }

                                if (!string.Equals(material.Name, plan.MaterialChange.TargetName, StringComparison.Ordinal))
                                {
                                    Material nameConflict = FindMaterialBoardMaterial(doc, plan.MaterialChange.TargetName);
                                    if (nameConflict != null && nameConflict.Id.GetIdValue() != material.Id.GetIdValue())
                                    {
                                        failures.Add(new
                                        {
                                            plan.MaterialCode,
                                            plan.TargetTypeName,
                                            MaterialId = material.Id.GetIdValue(),
                                            TargetMaterialName = plan.MaterialChange.TargetName,
                                            Error = $"Target material name is already used by ElementId {nameConflict.Id.GetIdValue()}."
                                        });
                                        continue;
                                    }

                                    material.Name = plan.MaterialChange.TargetName;
                                }

                                foreach (MaterialBoardParameterChange change in plan.MaterialChange.ParameterChanges)
                                {
                                    Parameter parameter = ResolveMaterialBoardParameter(material, change);
                                    if (parameter == null || parameter.IsReadOnly)
                                    {
                                        failures.Add(new
                                        {
                                            plan.MaterialCode,
                                            plan.TargetTypeName,
                                            MaterialId = material.Id.GetIdValue(),
                                            change.ParameterName,
                                            Error = parameter == null ? "Material parameter not found." : "Material parameter is read-only."
                                        });
                                        continue;
                                    }

                                    if (!SetMaterialBoardParameterValue(parameter, change))
                                    {
                                        failures.Add(new
                                        {
                                            plan.MaterialCode,
                                            plan.TargetTypeName,
                                            MaterialId = material.Id.GetIdValue(),
                                            change.ParameterName,
                                            Error = "Revit returned false while setting the material parameter."
                                        });
                                    }
                                }
                            }

                            foreach (MaterialBoardParameterChange change in plan.ParameterChanges)
                            {
                                Parameter parameter = ResolveMaterialBoardParameter(symbol, change);
                                if (parameter == null || parameter.IsReadOnly)
                                {
                                    failures.Add(new
                                    {
                                        plan.MaterialCode,
                                        plan.TargetTypeName,
                                        change.ParameterName,
                                        Error = parameter == null ? "Parameter not found." : "Parameter is read-only."
                                    });
                                    continue;
                                }

                                if (!SetMaterialBoardParameterValue(parameter, change))
                                {
                                    failures.Add(new
                                    {
                                        plan.MaterialCode,
                                        plan.TargetTypeName,
                                        change.ParameterName,
                                        Error = "Revit returned false while setting the parameter."
                                    });
                                }
                            }

                            if (plan.ParameterChanges.Count > 0 || HasMaterialBoardMaterialChanges(plan.MaterialChange))
                            {
                                updated++;
                            }

                            plan.TypeId = symbol.Id.GetIdValue();
                            plan.CurrentTypeName = previousTypeName;
                        }
                        catch (Exception ex)
                        {
                            failures.Add(new
                            {
                                plan.MaterialCode,
                                plan.TargetTypeName,
                                Error = ex.Message
                            });
                        }
                    }

                    if (failures.Count > 0)
                    {
                        trans.RollBack();
                        throw new Exception("Material board sync failed and was rolled back: " + JArray.FromObject(failures).ToString());
                    }

                    trans.Commit();
                }
            }

            sw.Stop();

            return new
            {
                Success = true,
                DryRun = dryRun,
                Applied = !dryRun,
                CsvPath = csvPath,
                FamilyName = familySymbols.First().FamilyName,
                BaseType = BuildMaterialBoardTypeSnapshot(baseSymbol),
                MaterialRows = rows.Count,
                FamilyTypeCount = familySymbols.Count,
                CreateMissingTypes = createMissingTypes,
                UpdateAtParameters = updateAtParameters,
                AtParameterPrefix = atParameterPrefix,
                PlannedCreate = plans.Count(plan => plan.Action == "create"),
                PlannedRenameUpdate = plans.Count(plan => plan.Action == "rename_update"),
                PlannedUpdate = plans.Count(plan => plan.Action == "update"),
                NoChange = unchanged,
                Missing = missing,
                ConflictCount = conflictCount,
                Created = dryRun ? 0 : created,
                Renamed = dryRun ? 0 : renamed,
                Updated = dryRun ? 0 : updated,
                DurationMs = sw.ElapsedMilliseconds,
                UnmatchedFamilyTypes = unmatchedFamilyTypes,
                Items = plans.Select(plan => new
                {
                    plan.MaterialCode,
                    plan.MaterialName,
                    plan.TypeId,
                    plan.CurrentTypeName,
                    plan.TargetTypeName,
                    plan.CurrentMaterialCode,
                    plan.Action,
                    ParameterChanges = plan.ParameterChanges.Select(change => new
                    {
                        change.Kind,
                        change.ParameterName,
                        change.CurrentValue,
                        change.TargetValue
                    }).ToList(),
                    MaterialChange = plan.MaterialChange == null ? null : new
                    {
                        plan.MaterialChange.MaterialIdValue,
                        plan.MaterialChange.CurrentName,
                        plan.MaterialChange.TargetName,
                        ParameterChanges = plan.MaterialChange.ParameterChanges.Select(change => new
                        {
                            change.Kind,
                            change.ParameterName,
                            change.CurrentValue,
                            change.TargetValue
                        }).ToList()
                    },
                    plan.UnsupportedParameters,
                    plan.Warnings,
                    plan.MatchedTypes,
                    plan.ConflictType
                }).ToList()
            };
        }

        private object UpdateMaterialBoardFamilyTypesById(JObject parameters)
        {
            Stopwatch sw = Stopwatch.StartNew();
            Document doc = _uiApp.ActiveUIDocument.Document;

            string familyName = parameters?["familyName"]?.Value<string>() ?? "AE-\u6750\u6599\u7248";
            bool dryRun = parameters?["dryRun"]?.Value<bool>() ?? !(parameters?["apply"]?.Value<bool>() ?? false);
            bool updateAtParameters = parameters?["updateAtParameters"]?.Value<bool>() ?? true;
            string atParameterPrefix = parameters?["atParameterPrefix"]?.Value<string>() ?? "@";
            var atParameterNames = GetMaterialBoardOptionalStringSet(parameters?["atParameterNames"]);
            JArray items = parameters?["items"] as JArray;
            if (items == null || items.Count == 0)
                throw new Exception("items is required.");

            var plans = new List<MaterialBoardPlan>();
            var failures = new List<object>();
            int renamed = 0;
            int updated = 0;

            if (dryRun)
            {
                foreach (JToken item in items)
                {
                    MaterialBoardPlan plan = BuildMaterialBoardByIdPlan(
                        doc,
                        familyName,
                        item,
                        updateAtParameters,
                        atParameterPrefix,
                        atParameterNames);
                    plans.Add(plan);
                }
            }
            else
            {
                using (Transaction trans = new Transaction(doc, "Update AE material board types by id"))
                {
                    trans.Start();

                    foreach (JToken item in items)
                    {
                        MaterialBoardPlan plan = BuildMaterialBoardByIdPlan(
                            doc,
                            familyName,
                            item,
                            updateAtParameters,
                            atParameterPrefix,
                            atParameterNames);
                        plans.Add(plan);

                        if (plan.Symbol == null)
                        {
                            failures.Add(new { plan.MaterialCode, plan.TargetTypeName, Error = "Family type was not found." });
                            continue;
                        }

                        try
                        {
                            FamilySymbol conflict = FindMaterialBoardTypeNameConflict(
                                new FilteredElementCollector(doc)
                                    .OfClass(typeof(FamilySymbol))
                                    .Cast<FamilySymbol>()
                                    .Where(symbol => symbol.FamilyName != null &&
                                        (symbol.FamilyName.Equals(familyName, StringComparison.OrdinalIgnoreCase) ||
                                         symbol.FamilyName.IndexOf(familyName, StringComparison.OrdinalIgnoreCase) >= 0))
                                    .ToList(),
                                plan.Symbol,
                                plan.TargetTypeName);

                            if (conflict != null)
                            {
                                failures.Add(new
                                {
                                    plan.MaterialCode,
                                    plan.TargetTypeName,
                                    Error = $"Target type name is already used by ElementId {conflict.Id.GetIdValue()}."
                                });
                                continue;
                            }

                            if (!string.Equals(plan.Symbol.Name, plan.TargetTypeName, StringComparison.Ordinal))
                            {
                                plan.Symbol.Name = plan.TargetTypeName;
                                renamed++;
                            }

                            ApplyMaterialBoardMaterialChange(doc, plan, failures);
                            ApplyMaterialBoardParameterChanges(plan.Symbol, plan, failures);

                            if (plan.ParameterChanges.Count > 0 || HasMaterialBoardMaterialChanges(plan.MaterialChange))
                                updated++;
                        }
                        catch (Exception ex)
                        {
                            failures.Add(new
                            {
                                plan.MaterialCode,
                                plan.TargetTypeName,
                                Error = ex.Message
                            });
                        }
                    }

                    if (failures.Count > 0)
                    {
                        trans.RollBack();
                        throw new Exception("Material board type update failed and was rolled back: " + JArray.FromObject(failures).ToString());
                    }

                    trans.Commit();
                }
            }

            sw.Stop();
            return new
            {
                Success = true,
                DryRun = dryRun,
                Applied = !dryRun,
                FamilyName = familyName,
                Planned = plans.Count,
                Renamed = dryRun ? 0 : renamed,
                Updated = dryRun ? 0 : updated,
                DurationMs = sw.ElapsedMilliseconds,
                Items = plans.Select(BuildMaterialBoardPlanSnapshot).ToList()
            };
        }

        private MaterialBoardPlan BuildMaterialBoardByIdPlan(
            Document doc,
            string familyName,
            JToken item,
            bool updateAtParameters,
            string atParameterPrefix,
            HashSet<string> atParameterNames)
        {
            IdType typeIdValue = item["typeId"].Value<IdType>();
            FamilySymbol symbol = doc.GetElement(new ElementId(typeIdValue)) as FamilySymbol;
            string code = item["code"]?.Value<string>()?.Trim() ?? "";
            string name = item["name"]?.Value<string>()?.Trim() ?? "";
            string targetTypeName = item["targetTypeName"]?.Value<string>()?.Trim();
            if (string.IsNullOrWhiteSpace(targetTypeName))
            {
                string safeName = NormalizeMaterialBoardRevitName(name);
                targetTypeName = string.IsNullOrWhiteSpace(code) ? safeName : $"{code}-{safeName}";
            }

            var row = new MaterialBoardRow
            {
                Code = code,
                Name = name
            };

            var plan = new MaterialBoardPlan
            {
                Symbol = symbol,
                TypeId = typeIdValue,
                MaterialCode = code,
                MaterialName = name,
                CurrentTypeName = symbol?.Name,
                TargetTypeName = targetTypeName,
                CurrentMaterialCode = symbol == null ? "" : ReadMaterialBoardTypeMark(symbol),
                Action = symbol == null ? "missing" : (symbol.Name == targetTypeName ? "update" : "rename_update")
            };

            if (symbol == null)
                return plan;

            if (symbol.FamilyName == null ||
                (!symbol.FamilyName.Equals(familyName, StringComparison.OrdinalIgnoreCase) &&
                 symbol.FamilyName.IndexOf(familyName, StringComparison.OrdinalIgnoreCase) < 0))
            {
                plan.Symbol = null;
                plan.Warnings.Add($"TypeId {typeIdValue} is not in family {familyName}.");
                return plan;
            }

            BuildMaterialBoardParameterChanges(doc, symbol, row, updateAtParameters, atParameterPrefix, atParameterNames, plan, true);
            if (plan.Action == "update" && plan.ParameterChanges.Count == 0 && !HasMaterialBoardMaterialChanges(plan.MaterialChange))
                plan.Action = "no_change";

            return plan;
        }

        private object BuildMaterialBoardPlanSnapshot(MaterialBoardPlan plan)
        {
            return new
            {
                plan.MaterialCode,
                plan.MaterialName,
                plan.TypeId,
                plan.CurrentTypeName,
                plan.TargetTypeName,
                plan.CurrentMaterialCode,
                plan.Action,
                ParameterChanges = plan.ParameterChanges.Select(change => new
                {
                    change.Kind,
                    change.ParameterName,
                    change.CurrentValue,
                    change.TargetValue
                }).ToList(),
                MaterialChange = plan.MaterialChange == null ? null : new
                {
                    plan.MaterialChange.MaterialIdValue,
                    plan.MaterialChange.CurrentName,
                    plan.MaterialChange.TargetName,
                    ParameterChanges = plan.MaterialChange.ParameterChanges.Select(change => new
                    {
                        change.Kind,
                        change.ParameterName,
                        change.CurrentValue,
                        change.TargetValue
                    }).ToList()
                },
                plan.UnsupportedParameters,
                plan.Warnings,
                plan.MatchedTypes,
                plan.ConflictType
            };
        }

        private void ApplyMaterialBoardMaterialChange(Document doc, MaterialBoardPlan plan, List<object> failures)
        {
            if (!HasMaterialBoardMaterialChanges(plan.MaterialChange))
                return;

            Material material = doc.GetElement(plan.MaterialChange.MaterialId) as Material;
            if (material == null)
            {
                failures.Add(new
                {
                    plan.MaterialCode,
                    plan.TargetTypeName,
                    Error = "Material was not found while applying material changes."
                });
                return;
            }

            if (!string.Equals(material.Name, plan.MaterialChange.TargetName, StringComparison.Ordinal))
            {
                Material nameConflict = FindMaterialBoardMaterial(doc, plan.MaterialChange.TargetName);
                if (nameConflict != null && nameConflict.Id.GetIdValue() != material.Id.GetIdValue())
                {
                    failures.Add(new
                    {
                        plan.MaterialCode,
                        plan.TargetTypeName,
                        MaterialId = material.Id.GetIdValue(),
                        TargetMaterialName = plan.MaterialChange.TargetName,
                        Error = $"Target material name is already used by ElementId {nameConflict.Id.GetIdValue()}."
                    });
                    return;
                }

                material.Name = plan.MaterialChange.TargetName;
            }

            foreach (MaterialBoardParameterChange change in plan.MaterialChange.ParameterChanges)
            {
                Parameter parameter = ResolveMaterialBoardParameter(material, change);
                if (parameter == null || parameter.IsReadOnly)
                {
                    failures.Add(new
                    {
                        plan.MaterialCode,
                        plan.TargetTypeName,
                        MaterialId = material.Id.GetIdValue(),
                        change.ParameterName,
                        Error = parameter == null ? "Material parameter not found." : "Material parameter is read-only."
                    });
                    continue;
                }

                if (!SetMaterialBoardParameterValue(parameter, change))
                {
                    failures.Add(new
                    {
                        plan.MaterialCode,
                        plan.TargetTypeName,
                        MaterialId = material.Id.GetIdValue(),
                        change.ParameterName,
                        Error = "Revit returned false while setting the material parameter."
                    });
                }
            }
        }

        private void ApplyMaterialBoardParameterChanges(FamilySymbol symbol, MaterialBoardPlan plan, List<object> failures)
        {
            foreach (MaterialBoardParameterChange change in plan.ParameterChanges)
            {
                Parameter parameter = ResolveMaterialBoardParameter(symbol, change);
                if (parameter == null || parameter.IsReadOnly)
                {
                    failures.Add(new
                    {
                        plan.MaterialCode,
                        plan.TargetTypeName,
                        change.ParameterName,
                        Error = parameter == null ? "Parameter not found." : "Parameter is read-only."
                    });
                    continue;
                }

                if (!SetMaterialBoardParameterValue(parameter, change))
                {
                    failures.Add(new
                    {
                        plan.MaterialCode,
                        plan.TargetTypeName,
                        change.ParameterName,
                        Error = "Revit returned false while setting the parameter."
                    });
                }
            }
        }

        private string ResolveMaterialBoardCsvPath(string requestedPath)
        {
            if (!string.IsNullOrWhiteSpace(requestedPath))
            {
                string explicitPath = Environment.ExpandEnvironmentVariables(requestedPath.Trim());
                if (File.Exists(explicitPath))
                    return explicitPath;

                throw new FileNotFoundException("Material CSV was not found.", explicitPath);
            }

            string envPath = Environment.GetEnvironmentVariable("REVITMCP_MATERIAL_TABLE_CSV");
            if (!string.IsNullOrWhiteSpace(envPath) && File.Exists(envPath))
                return envPath;

            string[] candidates =
            {
                @"E:\GitHub Library\RevitMCP\??銵典???csv",
                Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "??銵典???csv")
            };

            foreach (string candidate in candidates)
            {
                if (File.Exists(candidate))
                    return candidate;
            }

            throw new FileNotFoundException("Material CSV was not found. Pass csvPath explicitly.", candidates[0]);
        }

        private List<MaterialBoardRow> ReadMaterialBoardCsv(string csvPath)
        {
            var rows = new List<MaterialBoardRow>();
            var seenCodes = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            foreach (string line in File.ReadAllLines(csvPath, Encoding.UTF8))
            {
                if (string.IsNullOrWhiteSpace(line))
                    continue;

                List<string> cells = ParseMaterialBoardCsvLine(line);
                if (cells.Count < 2)
                    continue;

                string code = (cells[0] ?? "").Trim().TrimStart('\uFEFF');
                string name = (cells[1] ?? "").Trim();

                if (string.IsNullOrWhiteSpace(code) ||
                    code.Equals("\u6750\u6599\u7de8\u865f", StringComparison.OrdinalIgnoreCase) ||
                    name.Equals("\u6750\u6599\u540d\u7a31", StringComparison.OrdinalIgnoreCase) ||
                    string.IsNullOrWhiteSpace(name))
                {
                    continue;
                }

                if (seenCodes.Add(code))
                {
                    rows.Add(new MaterialBoardRow
                    {
                        Code = code,
                        Name = name
                    });
                }
            }

            return rows;
        }

        private List<string> ParseMaterialBoardCsvLine(string line)
        {
            var cells = new List<string>();
            var current = new StringBuilder();
            bool inQuotes = false;

            for (int i = 0; i < line.Length; i++)
            {
                char ch = line[i];
                if (ch == '"')
                {
                    if (inQuotes && i + 1 < line.Length && line[i + 1] == '"')
                    {
                        current.Append('"');
                        i++;
                    }
                    else
                    {
                        inQuotes = !inQuotes;
                    }

                    continue;
                }

                if (ch == ',' && !inQuotes)
                {
                    cells.Add(current.ToString());
                    current.Clear();
                    continue;
                }

                current.Append(ch);
            }

            cells.Add(current.ToString());
            return cells;
        }

        private FamilySymbol ResolveMaterialBoardBaseSymbol(List<FamilySymbol> familySymbols, string baseTypeName)
        {
            if (!string.IsNullOrWhiteSpace(baseTypeName))
            {
                FamilySymbol requested = familySymbols.FirstOrDefault(symbol =>
                    symbol.Name != null && symbol.Name.Equals(baseTypeName, StringComparison.OrdinalIgnoreCase));
                if (requested != null)
                    return requested;
            }

            return familySymbols.First();
        }

        private Dictionary<string, List<FamilySymbol>> BuildMaterialBoardSymbolsByMaterialCode(
            Document doc,
            List<FamilySymbol> familySymbols,
            List<MaterialBoardRow> rows,
            out HashSet<IdType> materialMatchedSymbolIds)
        {
            var rowsByName = rows
                .GroupBy(row => GetMaterialBoardNameKey(row.Name), StringComparer.OrdinalIgnoreCase)
                .ToDictionary(group => group.Key, group => group.ToList(), StringComparer.OrdinalIgnoreCase);
            var rowCodes = new HashSet<string>(rows.Select(row => row.Code), StringComparer.OrdinalIgnoreCase);
            var result = new Dictionary<string, List<FamilySymbol>>(StringComparer.OrdinalIgnoreCase);
            materialMatchedSymbolIds = new HashSet<IdType>();

            foreach (FamilySymbol symbol in familySymbols)
            {
                foreach (string key in GetMaterialBoardNameKeysFromSymbol(doc, symbol))
                {
                    if (string.IsNullOrWhiteSpace(key) || !rowsByName.TryGetValue(key, out List<MaterialBoardRow> matchingRows))
                        continue;

                    MaterialBoardRow targetRow = PickMaterialBoardRowForSymbol(symbol, matchingRows, rowCodes);
                    if (targetRow == null)
                        continue;

                    materialMatchedSymbolIds.Add(symbol.Id.GetIdValue());
                    if (!result.TryGetValue(targetRow.Code, out List<FamilySymbol> symbols))
                        result[targetRow.Code] = symbols = new List<FamilySymbol>();

                    if (!symbols.Any(existing => existing.Id.GetIdValue().Equals(symbol.Id.GetIdValue())))
                        symbols.Add(symbol);
                }
            }

            return result;
        }

        private MaterialBoardRow PickMaterialBoardRowForSymbol(
            FamilySymbol symbol,
            List<MaterialBoardRow> matchingRows,
            HashSet<string> rowCodes)
        {
            if (matchingRows == null || matchingRows.Count == 0)
                return null;

            if (matchingRows.Count == 1)
                return matchingRows[0];

            string currentCode = GetMaterialBoardCodeFromSymbol(symbol, rowCodes);
            string currentPrefix = GetMaterialBoardCodePrefix(currentCode);
            if (!string.IsNullOrWhiteSpace(currentPrefix))
            {
                List<MaterialBoardRow> samePrefixRows = matchingRows
                    .Where(row => string.Equals(GetMaterialBoardCodePrefix(row.Code), currentPrefix, StringComparison.OrdinalIgnoreCase))
                    .ToList();
                if (samePrefixRows.Count == 1)
                    return samePrefixRows[0];
            }

            return null;
        }

        private string GetMaterialBoardCodePrefix(string code)
        {
            string value = (code ?? "").Trim();
            if (string.IsNullOrWhiteSpace(value))
                return "";

            return new string(value.TakeWhile(char.IsLetter).ToArray());
        }

        private IEnumerable<string> GetMaterialBoardNameKeysFromSymbol(Document doc, FamilySymbol symbol)
        {
            foreach (Parameter parameter in GetMaterialBoardSurfaceMaterialParameters(symbol, new HashSet<string>(StringComparer.OrdinalIgnoreCase)))
            {
                string materialName = ReadMaterialBoardSurfaceMaterialName(doc, parameter);
                if (!string.IsNullOrWhiteSpace(materialName))
                    yield return GetMaterialBoardNameKey(materialName);
            }

            string typeNameTail = ExtractMaterialBoardTypeNameTail(symbol.Name);
            if (!string.IsNullOrWhiteSpace(typeNameTail))
                yield return GetMaterialBoardNameKey(typeNameTail);
        }

        private string ReadMaterialBoardSurfaceMaterialName(Document doc, Parameter parameter)
        {
            if (parameter == null)
                return "";

            if (parameter.StorageType == StorageType.ElementId)
            {
                ElementId materialId = parameter.AsElementId();
                Material material = materialId == null || materialId == ElementId.InvalidElementId
                    ? null
                    : doc.GetElement(materialId) as Material;
                return StripMaterialBoardAtPrefix(material?.Name);
            }

            return StripMaterialBoardAtPrefix(ReadMaterialBoardParameterValue(parameter));
        }

        private string ExtractMaterialBoardTypeNameTail(string typeName)
        {
            string value = (typeName ?? "").Trim();
            if (string.IsNullOrWhiteSpace(value))
                return "";

            int index = 0;
            while (index < value.Length && char.IsLetter(value[index]))
                index++;
            while (index < value.Length && char.IsDigit(value[index]))
                index++;

            if (index > 0 && index < value.Length && IsMaterialBoardCodeSeparator(value[index]))
                return value.Substring(index + 1).Trim();

            return value;
        }

        private bool IsMaterialBoardCodeSeparator(char ch)
        {
            return ch == '-' ||
                   ch == '=' ||
                   ch == '_' ||
                   ch == ' ' ||
                   ch == '\uFF0D' ||
                   ch == '\uFF1D';
        }

        private string StripMaterialBoardAtPrefix(string value)
        {
            string text = (value ?? "").Trim();
            return text.StartsWith("@", StringComparison.Ordinal) ? text.Substring(1).Trim() : text;
        }

        private string GetMaterialBoardNameKey(string value)
        {
            return NormalizeMaterialBoardRevitName(StripMaterialBoardAtPrefix(value)).Trim();
        }

        private Dictionary<string, List<FamilySymbol>> BuildMaterialBoardSymbolsByCode(
            List<FamilySymbol> familySymbols,
            List<MaterialBoardRow> rows,
            HashSet<IdType> skipSymbolIds)
        {
            var rowCodes = new HashSet<string>(rows.Select(row => row.Code), StringComparer.OrdinalIgnoreCase);
            var result = new Dictionary<string, List<FamilySymbol>>(StringComparer.OrdinalIgnoreCase);

            foreach (FamilySymbol symbol in familySymbols)
            {
                if (skipSymbolIds != null && skipSymbolIds.Contains(symbol.Id.GetIdValue()))
                    continue;

                string code = GetMaterialBoardCodeFromSymbol(symbol, rowCodes);
                if (string.IsNullOrWhiteSpace(code))
                    continue;

                if (!result.TryGetValue(code, out List<FamilySymbol> symbols))
                {
                    symbols = new List<FamilySymbol>();
                    result[code] = symbols;
                }

                symbols.Add(symbol);
            }

            return result;
        }

        private string GetMaterialBoardCodeFromSymbol(FamilySymbol symbol, HashSet<string> rowCodes)
        {
            string typeMark = ReadMaterialBoardTypeMark(symbol);
            if (!string.IsNullOrWhiteSpace(typeMark) && rowCodes.Contains(typeMark.Trim()))
                return typeMark.Trim();

            string typeName = symbol.Name ?? "";
            foreach (string code in rowCodes.OrderByDescending(c => c.Length))
            {
                if (typeName.Equals(code, StringComparison.OrdinalIgnoreCase) ||
                    typeName.StartsWith(code + "-", StringComparison.OrdinalIgnoreCase) ||
                    typeName.StartsWith(code + "\uFF0D", StringComparison.OrdinalIgnoreCase) ||
                    typeName.StartsWith(code + "=", StringComparison.OrdinalIgnoreCase) ||
                    typeName.StartsWith(code + "\uFF1A", StringComparison.OrdinalIgnoreCase) ||
                    typeName.StartsWith(code + "_", StringComparison.OrdinalIgnoreCase) ||
                    typeName.StartsWith(code + " ", StringComparison.OrdinalIgnoreCase))
                {
                    return code;
                }
            }

            return "";
        }

        private string ReadMaterialBoardTypeMark(FamilySymbol symbol)
        {
            Parameter parameter = symbol.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_MARK)
                ?? symbol.LookupParameter("璅?")
                ?? symbol.LookupParameter("憿?璅?")
                ?? symbol.LookupParameter("Type Mark");

            return parameter?.AsString() ?? parameter?.AsValueString() ?? "";
        }

        private object BuildMaterialBoardTypeSnapshot(FamilySymbol symbol)
        {
            return new
            {
                TypeId = symbol.Id.GetIdValue(),
                FamilyName = symbol.FamilyName ?? "",
                TypeName = symbol.Name ?? "",
                TypeMark = ReadMaterialBoardTypeMark(symbol),
                Description = ReadMaterialBoardDescription(symbol),
                AtParameters = GetMaterialBoardAtParameters(symbol, "@")
                    .Select(parameter => new
                    {
                        Name = parameter.Definition?.Name ?? "",
                        Value = ReadMaterialBoardParameterValue(parameter),
                        StorageType = parameter.StorageType.ToString(),
                        IsReadOnly = parameter.IsReadOnly
                    })
                    .ToList()
            };
        }

        private string ReadMaterialBoardDescription(FamilySymbol symbol)
        {
            Parameter parameter = symbol.get_Parameter(BuiltInParameter.ALL_MODEL_DESCRIPTION)
                ?? symbol.LookupParameter("?膩")
                ?? symbol.LookupParameter("Description");

            return parameter?.AsString() ?? parameter?.AsValueString() ?? "";
        }

        private FamilySymbol FindMaterialBoardTypeNameConflict(
            List<FamilySymbol> familySymbols,
            FamilySymbol currentSymbol,
            string targetTypeName)
        {
            return familySymbols.FirstOrDefault(symbol =>
                symbol.Id.GetIdValue() != currentSymbol.Id.GetIdValue() &&
                string.Equals(symbol.Name, targetTypeName, StringComparison.OrdinalIgnoreCase));
        }

        private void BuildMaterialBoardParameterChanges(
            Document doc,
            FamilySymbol symbol,
            MaterialBoardRow row,
            bool updateAtParameters,
            string atParameterPrefix,
            HashSet<string> atParameterNames,
            MaterialBoardPlan plan,
            bool allowCurrentMaterialRename)
        {
            AddMaterialBoardParameterChange(
                plan,
                symbol,
                "Description",
                BuiltInParameter.ALL_MODEL_DESCRIPTION,
                new[] { "?膩", "Description" },
                row.Name);

            AddMaterialBoardParameterChange(
                plan,
                symbol,
                "TypeMark",
                BuiltInParameter.ALL_MODEL_TYPE_MARK,
                new[] { "璅?", "憿?璅?", "Type Mark" },
                row.Code);

            if (!updateAtParameters)
                return;

            string targetMaterialName = NormalizeMaterialBoardRevitName(row.Name);
            string targetSurfaceMaterialName = "@" + targetMaterialName;
            List<Parameter> surfaceMaterialParameters = GetMaterialBoardSurfaceMaterialParameters(symbol, atParameterNames);

            if (surfaceMaterialParameters.Count == 0)
            {
                plan.Warnings.Add("Surface material type parameter was not found; surface material was not changed for this material.");
                return;
            }

            Material material = ResolveMaterialBoardTargetMaterial(
                doc,
                symbol,
                surfaceMaterialParameters,
                row,
                targetSurfaceMaterialName,
                plan,
                allowCurrentMaterialRename);
            if (material == null)
            {
                return;
            }

            foreach (Parameter parameter in surfaceMaterialParameters)
            {
                string parameterName = parameter.Definition?.Name ?? "";
                string targetValue = targetSurfaceMaterialName;
                ElementId targetElementId = material.Id;

                if (!CanSetMaterialBoardParameter(parameter))
                {
                    plan.UnsupportedParameters.Add(new
                    {
                        ParameterName = parameterName,
                        parameter.StorageType,
                        TargetValue = targetValue
                    });
                    continue;
                }

                string currentValue = ReadMaterialBoardParameterValue(parameter);
                if (!string.Equals(currentValue, targetValue, StringComparison.Ordinal))
                {
                    plan.ParameterChanges.Add(new MaterialBoardParameterChange
                    {
                        Kind = "AtParameter",
                        ParameterName = parameterName,
                        CurrentValue = currentValue,
                        TargetValue = targetValue,
                        TargetElementId = targetElementId
                    });
                }
            }
        }

        private Material ResolveMaterialBoardTargetMaterial(
            Document doc,
            FamilySymbol symbol,
            List<Parameter> surfaceMaterialParameters,
            MaterialBoardRow row,
            string targetSurfaceMaterialName,
            MaterialBoardPlan plan,
            bool allowCurrentMaterialRename)
        {
            Material targetMaterial = FindMaterialBoardMaterial(doc, targetSurfaceMaterialName);
            if (targetMaterial != null)
            {
                AddMaterialBoardMaterialChange(targetMaterial, row, targetSurfaceMaterialName, plan);
                return targetMaterial;
            }

            if (allowCurrentMaterialRename)
            {
                Material currentMaterial = FindMaterialBoardCurrentSurfaceMaterial(doc, surfaceMaterialParameters);
                if (currentMaterial != null)
                {
                    AddMaterialBoardMaterialChange(currentMaterial, row, targetSurfaceMaterialName, plan);
                    return currentMaterial;
                }
            }

            plan.Warnings.Add($"Material not found and no current surface material can be renamed: {targetSurfaceMaterialName}");
            return null;
        }

        private Material FindMaterialBoardCurrentSurfaceMaterial(Document doc, List<Parameter> surfaceMaterialParameters)
        {
            foreach (Parameter parameter in surfaceMaterialParameters)
            {
                if (parameter?.StorageType != StorageType.ElementId)
                    continue;

                ElementId materialId = parameter.AsElementId();
                if (materialId == null || materialId == ElementId.InvalidElementId)
                    continue;

                Material material = doc.GetElement(materialId) as Material;
                if (material != null)
                    return material;
            }

            return null;
        }

        private void AddMaterialBoardMaterialChange(
            Material material,
            MaterialBoardRow row,
            string targetSurfaceMaterialName,
            MaterialBoardPlan plan)
        {
            if (material == null || plan == null)
                return;

            var change = new MaterialBoardMaterialChange
            {
                MaterialId = material.Id,
                MaterialIdValue = material.Id.GetIdValue(),
                CurrentName = material.Name,
                TargetName = targetSurfaceMaterialName
            };

            AddMaterialBoardElementParameterChange(
                change.ParameterChanges,
                material,
                "MaterialDescription",
                BuiltInParameter.ALL_MODEL_DESCRIPTION,
                new[] { "?膩", "Description" },
                row.Name,
                plan);

            AddMaterialBoardElementParameterChange(
                change.ParameterChanges,
                material,
                "MaterialMark",
                BuiltInParameter.ALL_MODEL_MARK,
                new[] { "璅?", "Mark", "Type Mark" },
                row.Code,
                plan);

            if (!HasMaterialBoardMaterialChanges(change))
                return;

            plan.MaterialChange = change;
        }

        private void AddMaterialBoardParameterChange(
            MaterialBoardPlan plan,
            FamilySymbol symbol,
            string kind,
            BuiltInParameter builtInParameter,
            string[] fallbackNames,
            string targetValue)
        {
            Parameter parameter = symbol.get_Parameter(builtInParameter);
            string parameterName = parameter?.Definition?.Name;

            if (parameter == null)
            {
                foreach (string fallbackName in fallbackNames)
                {
                    parameter = symbol.LookupParameter(fallbackName);
                    if (parameter != null)
                    {
                        parameterName = fallbackName;
                        break;
                    }
                }
            }

            if (parameter == null)
            {
                plan.Warnings.Add($"Parameter not found: {kind}");
                return;
            }

            if (!CanSetMaterialBoardParameter(parameter))
            {
                plan.UnsupportedParameters.Add(new
                {
                    ParameterName = parameterName ?? kind,
                    parameter.StorageType,
                    TargetValue = targetValue
                });
                return;
            }

            string currentValue = ReadMaterialBoardParameterValue(parameter);
            if (!string.Equals(currentValue, targetValue, StringComparison.Ordinal))
            {
                plan.ParameterChanges.Add(new MaterialBoardParameterChange
                {
                    Kind = kind,
                    BuiltInParameter = builtInParameter,
                    ParameterName = parameterName ?? kind,
                    FallbackNames = fallbackNames,
                    CurrentValue = currentValue,
                    TargetValue = targetValue
                });
            }
        }

        private void AddMaterialBoardElementParameterChange(
            List<MaterialBoardParameterChange> changes,
            Element element,
            string kind,
            BuiltInParameter builtInParameter,
            string[] fallbackNames,
            string targetValue,
            MaterialBoardPlan plan)
        {
            Parameter parameter = element.get_Parameter(builtInParameter);
            string parameterName = parameter?.Definition?.Name;

            if (parameter == null)
            {
                foreach (string fallbackName in fallbackNames)
                {
                    parameter = element.LookupParameter(fallbackName);
                    if (parameter != null)
                    {
                        parameterName = fallbackName;
                        break;
                    }
                }
            }

            if (parameter == null)
            {
                plan.Warnings.Add($"Material parameter not found: {kind}");
                return;
            }

            if (!CanSetMaterialBoardParameter(parameter))
            {
                plan.UnsupportedParameters.Add(new
                {
                    ParameterName = parameterName ?? kind,
                    parameter.StorageType,
                    TargetValue = targetValue
                });
                return;
            }

            string currentValue = ReadMaterialBoardParameterValue(parameter);
            if (!string.Equals(currentValue, targetValue, StringComparison.Ordinal))
            {
                changes.Add(new MaterialBoardParameterChange
                {
                    Kind = kind,
                    BuiltInParameter = builtInParameter,
                    ParameterName = parameterName ?? kind,
                    FallbackNames = fallbackNames,
                    CurrentValue = currentValue,
                    TargetValue = targetValue
                });
            }
        }

        private List<Parameter> GetMaterialBoardAtParameters(FamilySymbol symbol, string atParameterPrefix)
        {
            string prefix = string.IsNullOrEmpty(atParameterPrefix) ? "@" : atParameterPrefix;
            return symbol.Parameters
                .Cast<Parameter>()
                .Where(parameter =>
                {
                    string name = parameter.Definition?.Name ?? "";
                    return name.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
                })
                .OrderBy(parameter => parameter.Definition?.Name)
                .ToList();
        }

        private List<Parameter> GetMaterialBoardSurfaceMaterialParameters(FamilySymbol symbol, HashSet<string> explicitNames)
        {
            return symbol.Parameters
                .Cast<Parameter>()
                .Where(parameter =>
                {
                    string name = parameter.Definition?.Name ?? "";
                    if (explicitNames.Count > 0)
                        return explicitNames.Contains(name);

                    string normalized = name.Trim().ToLowerInvariant();
                    return parameter.StorageType == StorageType.ElementId &&
                           (normalized == "\u8868\u9762\u6750\u6599" ||
                            normalized == "銵券??" ||
                            normalized == "surface material" ||
                            normalized == "material" ||
                            (normalized.Contains("\u8868\u9762") && normalized.Contains("\u6750\u6599")) ||
                            (normalized.Contains("銵券") && normalized.Contains("??")) ||
                            (normalized.Contains("surface") && normalized.Contains("material")));
                })
                .OrderBy(parameter => parameter.Definition?.Name)
                .ToList();
        }

        private bool IsMaterialBoardAtParameterForMaterial(string parameterName, string materialName)
        {
            string candidate = ((parameterName ?? "").Trim()).TrimStart('@').Trim();
            string expected = (materialName ?? "").Trim();
            return string.Equals(candidate, expected, StringComparison.Ordinal);
        }

        private Material FindMaterialBoardMaterial(Document doc, string materialName)
        {
            if (doc == null || string.IsNullOrWhiteSpace(materialName))
                return null;

            string expected = materialName.Trim();
            return new FilteredElementCollector(doc)
                .OfClass(typeof(Material))
                .Cast<Material>()
                .FirstOrDefault(material =>
                    string.Equals((material.Name ?? "").Trim(), expected, StringComparison.Ordinal));
        }

        private string GetMaterialBoardAtParameterTarget(string parameterName, MaterialBoardRow row)
        {
            string normalized = (parameterName ?? "").Trim().TrimStart('@').ToLowerInvariant();
            if (normalized.Contains("蝺刻?") ||
                normalized.Contains("隞?Ⅳ") ||
                normalized.Contains("璅?") ||
                normalized.Contains("code") ||
                normalized.Contains("mark") ||
                normalized.Contains("number") ||
                normalized == "id")
            {
                return row.Code;
            }

            return row.Name;
        }

        private Parameter ResolveMaterialBoardParameter(Element element, MaterialBoardParameterChange change)
        {
            if (change.BuiltInParameter.HasValue)
            {
                Parameter parameter = element.get_Parameter(change.BuiltInParameter.Value);
                if (parameter != null)
                    return parameter;
            }

            if (!string.IsNullOrWhiteSpace(change.ParameterName))
            {
                Parameter parameter = element.LookupParameter(change.ParameterName);
                if (parameter != null)
                    return parameter;
            }

            if (change.FallbackNames != null)
            {
                foreach (string fallbackName in change.FallbackNames)
                {
                    Parameter parameter = element.LookupParameter(fallbackName);
                    if (parameter != null)
                        return parameter;
                }
            }

            return null;
        }

        private static bool CanSetMaterialBoardParameter(Parameter parameter)
        {
            return parameter != null &&
                   !parameter.IsReadOnly &&
                   (parameter.StorageType == StorageType.String ||
                    parameter.StorageType == StorageType.Integer ||
                    parameter.StorageType == StorageType.Double ||
                    parameter.StorageType == StorageType.ElementId);
        }

        private static string ReadMaterialBoardParameterValue(Parameter parameter)
        {
            return parameter?.AsString() ?? parameter?.AsValueString() ?? "";
        }

        private static bool SetMaterialBoardParameterValue(Parameter parameter, MaterialBoardParameterChange change)
        {
            string value = change?.TargetValue;
            switch (parameter.StorageType)
            {
                case StorageType.String:
                    return parameter.Set(value ?? "");
                case StorageType.Integer:
                case StorageType.Double:
                    return parameter.SetValueString(value ?? "");
                case StorageType.ElementId:
                    return change?.TargetElementId != null && parameter.Set(change.TargetElementId);
                default:
                    return false;
            }
        }

        private static bool HasMaterialBoardMaterialChanges(MaterialBoardMaterialChange change)
        {
            return change != null &&
                   (!string.Equals(change.CurrentName, change.TargetName, StringComparison.Ordinal) ||
                    change.ParameterChanges.Count > 0);
        }

        private string BuildMaterialBoardTypeName(MaterialBoardRow row)
        {
            return $"{row.Code}-{NormalizeMaterialBoardRevitName(row.Name)}";
        }

        private string NormalizeMaterialBoardRevitName(string name)
        {
            if (string.IsNullOrWhiteSpace(name))
                return "";

            var replacements = new Dictionary<char, char>
            {
                ['\\'] = '\uFF3C',
                [':'] = '\uFF1A',
                ['{'] = '\uFF5B',
                ['}'] = '\uFF5D',
                ['['] = '\uFF3B',
                [']'] = '\uFF3D',
                ['|'] = '\uFF5C',
                [';'] = '\uFF1B',
                ['<'] = '\uFF1C',
                ['>'] = '\uFF1E',
                ['?'] = '\uFF1F',
                ['`'] = '\uFF40',
                ['~'] = '\uFF5E'
            };

            IEnumerable<char> chars = name.Trim().Select(ch =>
                char.IsControl(ch) ? ' ' : (replacements.TryGetValue(ch, out char replacement) ? replacement : ch));

            return string.Concat(chars).Trim();
        }

        private string SanitizeMaterialBoardTypeName(string typeName)
        {
            return NormalizeMaterialBoardRevitName(typeName);
        }

        private HashSet<string> GetMaterialBoardOptionalStringSet(JToken token)
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

        private class MaterialBoardRow
        {
            public string Code { get; set; }
            public string Name { get; set; }
        }

        private class MaterialBoardPlan
        {
            public FamilySymbol Symbol { get; set; }
            public IdType? TypeId { get; set; }
            public string MaterialCode { get; set; }
            public string MaterialName { get; set; }
            public string CurrentTypeName { get; set; }
            public string TargetTypeName { get; set; }
            public string CurrentMaterialCode { get; set; }
            public string Action { get; set; }
            public List<MaterialBoardParameterChange> ParameterChanges { get; set; } = new List<MaterialBoardParameterChange>();
            public MaterialBoardMaterialChange MaterialChange { get; set; }
            public List<object> UnsupportedParameters { get; set; } = new List<object>();
            public List<string> Warnings { get; set; } = new List<string>();
            public List<object> MatchedTypes { get; set; } = new List<object>();
            public object ConflictType { get; set; }
        }

        private class MaterialBoardMaterialChange
        {
            public ElementId MaterialId { get; set; }
            public IdType MaterialIdValue { get; set; }
            public string CurrentName { get; set; }
            public string TargetName { get; set; }
            public List<MaterialBoardParameterChange> ParameterChanges { get; set; } = new List<MaterialBoardParameterChange>();
        }

        private class MaterialBoardParameterChange
        {
            public string Kind { get; set; }
            public BuiltInParameter? BuiltInParameter { get; set; }
            public string ParameterName { get; set; }
            public string[] FallbackNames { get; set; }
            public string CurrentValue { get; set; }
            public string TargetValue { get; set; }
            public ElementId TargetElementId { get; set; }
        }

        private class MaterialBoardSymbolComparer : IEqualityComparer<FamilySymbol>
        {
            public bool Equals(FamilySymbol x, FamilySymbol y)
            {
                if (ReferenceEquals(x, y))
                    return true;
                if (x == null || y == null)
                    return false;
                return x.Id.GetIdValue().Equals(y.Id.GetIdValue());
            }

            public int GetHashCode(FamilySymbol obj)
            {
                return obj?.Id.GetIdValue().GetHashCode() ?? 0;
            }
        }
    }
}
