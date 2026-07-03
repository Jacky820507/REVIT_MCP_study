using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Structure;
using Newtonsoft.Json.Linq;

// Revit 2025+ ElementId: int -> long
#if REVIT2025_OR_GREATER
using IdType = System.Int64;
#else
using IdType = System.Int32;
#endif

namespace RevitMCP.Core
{
    public partial class CommandExecutor
    {
        private const double StructuralModelingFeetToMm = 304.8;
        private const double StructuralModelingMmToFeet = 1.0 / 304.8;

        private object GetStructuralFramingTypes(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            string search = parameters["search"]?.Value<string>();

            var types = new FilteredElementCollector(doc)
                .OfClass(typeof(FamilySymbol))
                .Cast<FamilySymbol>()
                .Where(fs => fs.Category != null &&
                    fs.Category.Id.GetIdValue() == (IdType)BuiltInCategory.OST_StructuralFraming)
                .Select(fs => new
                {
                    ElementId = fs.Id.GetIdValue(),
                    TypeName = fs.Name,
                    FamilyName = fs.FamilyName,
                    Category = fs.Category?.Name,
                    WidthMm = ReadSymbolDoubleMm(fs, "w", "寬度", "Width", "b"),
                    DepthMm = ReadSymbolDoubleMm(fs, "h", "深度", "Height", "d"),
                    SectionKeyword = ReadSymbolString(fs, "剖面名稱關鍵字", "類型標記", "Type Mark"),
                    IsActive = fs.IsActive
                })
                .Where(t => string.IsNullOrEmpty(search) ||
                    t.TypeName.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0 ||
                    t.FamilyName.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0 ||
                    (t.SectionKeyword != null && t.SectionKeyword.IndexOf(search, StringComparison.OrdinalIgnoreCase) >= 0))
                .OrderBy(t => t.FamilyName)
                .ThenBy(t => t.TypeName)
                .ToList();

            return new
            {
                Count = types.Count,
                FramingTypes = types
            };
        }

        private object CreateStructuralFraming(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            JArray itemArray = parameters["items"] as JArray;
            List<JObject> items = itemArray != null && itemArray.Count > 0
                ? itemArray.Children<JObject>().ToList()
                : new List<JObject> { parameters };

            if (items.Count > 500)
            {
                throw new ArgumentException("create_structural_framing supports up to 500 items per call.");
            }

            string defaultTypeName = parameters["framingType"]?.Value<string>();
            string defaultLevelName = parameters["levelName"]?.Value<string>() ?? "RF";
            var created = new List<object>();

            using (Transaction trans = new Transaction(doc, "Create structural framing"))
            {
                trans.Start();

                foreach (JObject item in items)
                {
                    string typeName = item["framingType"]?.Value<string>() ?? defaultTypeName;
                    string levelName = item["levelName"]?.Value<string>() ?? defaultLevelName;
                    Level level = FindLevel(doc, levelName, true);

                    FamilySymbol symbol = FindStructuralFramingSymbol(doc, typeName);
                    if (symbol == null)
                    {
                        throw new Exception(string.IsNullOrEmpty(typeName)
                            ? "No StructuralFraming family symbol is available in this project."
                            : $"StructuralFraming type not found: {typeName}");
                    }

                    if (!symbol.IsActive)
                    {
                        symbol.Activate();
                        doc.Regenerate();
                    }

                    double startX = RequireDouble(item, "startX");
                    double startY = RequireDouble(item, "startY");
                    double endX = RequireDouble(item, "endX");
                    double endY = RequireDouble(item, "endY");
                    double defaultZ = item["z"]?.Value<double>()
                        ?? parameters["z"]?.Value<double>()
                        ?? (level.Elevation * StructuralModelingFeetToMm + (item["zOffsetMm"]?.Value<double>() ?? parameters["zOffsetMm"]?.Value<double>() ?? 0));
                    double startZ = item["startZ"]?.Value<double>() ?? defaultZ;
                    double endZ = item["endZ"]?.Value<double>() ?? defaultZ;

                    XYZ start = new XYZ(
                        startX * StructuralModelingMmToFeet,
                        startY * StructuralModelingMmToFeet,
                        startZ * StructuralModelingMmToFeet);
                    XYZ end = new XYZ(
                        endX * StructuralModelingMmToFeet,
                        endY * StructuralModelingMmToFeet,
                        endZ * StructuralModelingMmToFeet);

                    if (start.DistanceTo(end) < 1 * StructuralModelingMmToFeet)
                    {
                        throw new ArgumentException("Structural framing start and end points are too close.");
                    }

                    Line line = Line.CreateBound(start, end);
                    FamilyInstance framing = doc.Create.NewFamilyInstance(line, symbol, level, StructuralType.Beam);

                    TrySetStringParameter(framing, item["mark"]?.Value<string>(), "標記", "Mark");
                    TrySetStringParameter(framing, item["comments"]?.Value<string>() ?? item["comment"]?.Value<string>(), "備註", "Comments");
                    TrySetDoubleParameterMm(framing, item["startOffsetMm"]?.Value<double?>(), "起始樓層偏移", "Start Level Offset");
                    TrySetDoubleParameterMm(framing, item["endOffsetMm"]?.Value<double?>(), "結束樓層偏移", "End Level Offset");
                    TrySetDoubleParameterMm(framing, item["yOffsetMm"]?.Value<double?>(), "Y 向偏移值", "y Offset Value");
                    TrySetDoubleParameterMm(framing, item["zOffsetMm"]?.Value<double?>(), "Z 向偏移值", "z Offset Value");
                    TrySetDoubleParameterRadians(framing, item["rotationDegrees"]?.Value<double?>(), "斷面旋轉", "Cross-Section Rotation");

                    created.Add(new
                    {
                        ElementId = framing.Id.GetIdValue(),
                        FramingType = symbol.Name,
                        FamilyName = symbol.FamilyName,
                        Level = level.Name,
                        Start = new { X = startX, Y = startY, Z = startZ },
                        End = new { X = endX, Y = endY, Z = endZ },
                        LengthMm = Math.Round(start.DistanceTo(end) * StructuralModelingFeetToMm, 2)
                    });
                }

                trans.Commit();
            }

            return new
            {
                Count = created.Count,
                Elements = created
            };
        }

        private FamilySymbol FindStructuralFramingSymbol(Document doc, string typeName)
        {
            var symbols = new FilteredElementCollector(doc)
                .OfClass(typeof(FamilySymbol))
                .Cast<FamilySymbol>()
                .Where(fs => fs.Category != null &&
                    fs.Category.Id.GetIdValue() == (IdType)BuiltInCategory.OST_StructuralFraming);

            if (string.IsNullOrEmpty(typeName))
            {
                return symbols.FirstOrDefault();
            }

            return symbols.FirstOrDefault(fs => fs.Name.Equals(typeName, StringComparison.OrdinalIgnoreCase))
                ?? symbols.FirstOrDefault(fs => fs.FamilyName.IndexOf(typeName, StringComparison.OrdinalIgnoreCase) >= 0)
                ?? symbols.FirstOrDefault(fs => fs.Name.IndexOf(typeName, StringComparison.OrdinalIgnoreCase) >= 0);
        }

        private static double RequireDouble(JObject obj, string name)
        {
            JToken token = obj[name];
            if (token == null || token.Type == JTokenType.Null)
            {
                throw new ArgumentException($"Missing required parameter: {name}");
            }

            return token.Value<double>();
        }

        private static double? ReadSymbolDoubleMm(FamilySymbol symbol, params string[] names)
        {
            foreach (string name in names)
            {
                Parameter parameter = symbol.LookupParameter(name);
                if (parameter != null && parameter.HasValue && parameter.StorageType == StorageType.Double)
                {
                    return Math.Round(parameter.AsDouble() * StructuralModelingFeetToMm, 2);
                }
            }

            return null;
        }

        private static string ReadSymbolString(FamilySymbol symbol, params string[] names)
        {
            foreach (string name in names)
            {
                Parameter parameter = symbol.LookupParameter(name);
                if (parameter != null && parameter.HasValue)
                {
                    return parameter.AsString() ?? parameter.AsValueString();
                }
            }

            return null;
        }

        private static void TrySetStringParameter(Element element, string value, params string[] names)
        {
            if (string.IsNullOrEmpty(value))
            {
                return;
            }

            foreach (string name in names)
            {
                Parameter parameter = element.LookupParameter(name);
                if (parameter != null && !parameter.IsReadOnly && parameter.StorageType == StorageType.String)
                {
                    parameter.Set(value);
                    return;
                }
            }
        }

        private static void TrySetDoubleParameterMm(Element element, double? valueMm, params string[] names)
        {
            if (!valueMm.HasValue)
            {
                return;
            }

            foreach (string name in names)
            {
                Parameter parameter = element.LookupParameter(name);
                if (parameter != null && !parameter.IsReadOnly && parameter.StorageType == StorageType.Double)
                {
                    parameter.Set(valueMm.Value * StructuralModelingMmToFeet);
                    return;
                }
            }
        }

        private static void TrySetDoubleParameterRadians(Element element, double? valueDegrees, params string[] names)
        {
            if (!valueDegrees.HasValue)
            {
                return;
            }

            foreach (string name in names)
            {
                Parameter parameter = element.LookupParameter(name);
                if (parameter != null && !parameter.IsReadOnly && parameter.StorageType == StorageType.Double)
                {
                    parameter.Set(valueDegrees.Value * Math.PI / 180);
                    return;
                }
            }
        }
    }
}
