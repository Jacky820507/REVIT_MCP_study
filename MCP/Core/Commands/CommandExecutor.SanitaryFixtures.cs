using System;
using System.Collections.Generic;
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
        private const double SquareFeetToSquareMeters = 0.09290304;

        private object CheckSanitaryFixtureRequirements(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            string levelName = parameters["level"]?.Value<string>();
            string roomNameContains = parameters["roomNameContains"]?.Value<string>();
            string roomNumberContains = parameters["roomNumberContains"]?.Value<string>();
            double areaPerPerson = Math.Max(0.1, parameters["areaPerPersonM2"]?.Value<double>() ?? 10.0);
            double maleRatio = Math.Max(0.0, parameters["maleRatio"]?.Value<double>() ?? 1.0);
            double femaleRatio = Math.Max(0.0, parameters["femaleRatio"]?.Value<double>() ?? 1.0);
            List<string> excludeKeywords = ResolveSanitaryExcludeKeywords(parameters);

            if (maleRatio <= 0 && femaleRatio <= 0)
            {
                maleRatio = 1.0;
                femaleRatio = 1.0;
            }

            var roomIds = (parameters["roomIds"] as JArray)?
                .Select(v => v.Value<IdType>())
                .Where(id => id != 0)
                .ToList();

            List<Room> rooms = ResolveRoomsForSanitaryCheck(doc, roomIds, levelName, roomNameContains, roomNumberContains);
            if (rooms.Count == 0)
            {
                throw new Exception("No placed rooms matched the sanitary fixture scope.");
            }
            SanitaryBuildingRule rule = ResolveSanitaryBuildingRule(parameters, doc, levelName, rooms);

            List<SanitaryRoomResult> roomResults = rooms
                .Select(room => BuildSanitaryRoomResult(doc, room, areaPerPerson, excludeKeywords))
                .ToList();

            double grossAreaM2 = roomResults.Sum(r => r.AreaM2);
            double excludedAreaM2 = roomResults.Where(r => r.ExcludedFromOccupancy).Sum(r => r.AreaM2);
            double netFactoryAreaM2 = roomResults.Where(r => !r.ExcludedFromOccupancy).Sum(r => r.AreaM2);
            int totalPopulation = CeilingToInt(netFactoryAreaM2 / areaPerPerson);
            double ratioSum = maleRatio + femaleRatio;
            double normalizedMaleRatio = maleRatio / ratioSum;
            double normalizedFemaleRatio = femaleRatio / ratioSum;
            int malePopulation = CeilingToInt(totalPopulation * normalizedMaleRatio);
            int femalePopulation = CeilingToInt(totalPopulation * normalizedFemaleRatio);

            SanitaryFixtureRequirement requirements = new SanitaryFixtureRequirement
            {
                BuildingTypeCode = rule.Code,
                BuildingType = rule.DisplayName,
                RuleId = rule.RuleId,
                GrossAreaM2 = Math.Round(grossAreaM2, 2),
                ExcludedAreaM2 = Math.Round(excludedAreaM2, 2),
                NetFactoryAreaM2 = Math.Round(netFactoryAreaM2, 2),
                AreaPerPersonM2 = areaPerPerson,
                TotalPopulation = totalPopulation,
                MaleRatio = Math.Round(normalizedMaleRatio, 4),
                FemaleRatio = Math.Round(normalizedFemaleRatio, 4),
                MalePopulation = malePopulation,
                FemalePopulation = femalePopulation,
                MaleWaterClosets = CalculateFactoryWarehouseMaleWaterClosets(totalPopulation, malePopulation),
                FemaleWaterClosets = CalculateFactoryWarehouseFemaleWaterClosets(totalPopulation, femalePopulation),
                MaleUrinals = CalculateFactoryWarehouseMaleUrinals(totalPopulation, malePopulation),
                Lavatories = CalculateFactoryWarehouseLavatories(totalPopulation),
                BathtubsOrShowers = "\u4e0d\u9069\u7528"
            };

            return new
            {
                Scope = new
                {
                    Level = levelName,
                    RoomNameContains = roomNameContains,
                    RoomNumberContains = roomNumberContains,
                    TotalRooms = rooms.Count,
                    IncludedRooms = roomResults.Count(r => !r.ExcludedFromOccupancy),
                    ExcludedRooms = roomResults.Count(r => r.ExcludedFromOccupancy),
                    DetectedBuildingType = rule.DisplayName,
                    BuildingTypeCode = rule.Code,
                    BuildingTypeDetection = rule.DetectionReason,
                    ExcludeKeywords = excludeKeywords
                },
                Method = new
                {
                    RuleId = rule.RuleId,
                    RuleDescription = rule.Description,
                    TableColumns = "\u5efa\u7bc9\u7269\u7a2e\u985e / \u5927\u4fbf\u5668 / \u5c0f\u4fbf\u5668 / \u6d17\u9762\u76c6 / \u6d74\u7f38\u6216\u6dcb\u6d74",
                    OccupancyArea = "net factory floor area of the current level after excluding stair halls, elevator rooms, air-raid shelter / refuge rooms, and parking spaces",
                    OccupancyFormula = "ceiling(netFactoryAreaM2 / areaPerPersonM2)",
                    SexSplit = "for populations over 100, male/female populations are rounded up after applying the normalized ratio; default is 1:1",
                    MaleWaterClosets = "factory/warehouse table: 1 for total occupants 1-100; over 100, 1 + ceiling((men - 100) / 120)",
                    FemaleWaterClosets = "factory/warehouse table: 1 for total occupants 1-24, 2 for 25-49, 3 for 50-100; over 100, 3 + ceiling((women - 100) / 30)",
                    MaleUrinals = "factory/warehouse table: 1 for total occupants 1-49, 2 for 50-100; over 100, 2 + ceiling((men - 100) / 60)",
                    Lavatories = "factory/warehouse table: 1 per 10 total occupants up to 100; over 100, ceiling(total occupants / 15)",
                    BathtubsOrShowers = "not applicable for factory/warehouse row"
                },
                TableRow = new
                {
                    BuildingTypeCode = requirements.BuildingTypeCode,
                    BuildingType = requirements.BuildingType,
                    WaterClosets = new
                    {
                        Male = requirements.MaleWaterClosets,
                        Female = requirements.FemaleWaterClosets,
                        Total = requirements.MaleWaterClosets + requirements.FemaleWaterClosets
                    },
                    Urinals = requirements.MaleUrinals,
                    Lavatories = requirements.Lavatories,
                    BathtubsOrShowers = requirements.BathtubsOrShowers
                },
                Requirements = requirements,
                Rooms = roomResults
            };
        }

        private SanitaryBuildingRule ResolveSanitaryBuildingRule(
            JObject parameters,
            Document doc,
            string levelName,
            List<Room> rooms)
        {
            string explicitType = parameters["buildingType"]?.Value<string>()
                ?? parameters["buildingUseGroup"]?.Value<string>()
                ?? parameters["occupancyGroup"]?.Value<string>();
            string activeViewName = _uiApp.ActiveUIDocument?.ActiveView?.Name ?? "";
            string projectInfoName = doc.ProjectInformation?.Name ?? "";
            string sampledRoomNames = string.Join(" ", rooms.Take(20).Select(GetRoomName));
            string evidence = $"{explicitType} {levelName} {activeViewName} {projectInfoName} {sampledRoomNames}";

            SanitaryBuildingRule matchedRule = GetSanitaryBuildingRules()
                .FirstOrDefault(rule => rule.Keywords.Any(keyword =>
                    evidence.IndexOf(keyword, StringComparison.OrdinalIgnoreCase) >= 0));

            if (matchedRule != null)
            {
                matchedRule.DetectionReason = $"Matched C-1 factory/warehouse rule from: {GetSanitizedDetectionEvidence(explicitType, levelName, activeViewName)}";
                return matchedRule;
            }

            if (!string.IsNullOrWhiteSpace(explicitType))
            {
                throw new Exception($"Unsupported sanitary fixture building type: {explicitType}. Current rule package supports C-1 factory/warehouse only.");
            }

            SanitaryBuildingRule defaultRule = GetSanitaryBuildingRules().First(rule => rule.Code == "C-1");
            defaultRule.DetectionReason = "Defaulted to C-1 factory/warehouse because this sanitary fixture package currently supports C-1 only.";
            return defaultRule;
        }

        private List<SanitaryBuildingRule> GetSanitaryBuildingRules()
        {
            return new List<SanitaryBuildingRule>
            {
                new SanitaryBuildingRule
                {
                    Code = "C-1",
                    RuleId = "C-1_FACTORY_WAREHOUSE_SANITARY_FIXTURES",
                    DisplayName = "C-1 \u5de5\u5ee0\u3001\u5009\u5eab",
                    Description = "C-1 factory/warehouse sanitary fixture calculation rule; future building types should be added as separate rules.",
                    Keywords = new List<string>
                    {
                        "C-1", "C1", "\u5de5\u5ee0", "\u5ee0\u623f", "\u5009\u5eab", "factory", "warehouse"
                    }
                }
            };
        }

        private string GetSanitizedDetectionEvidence(string explicitType, string levelName, string activeViewName)
        {
            var parts = new[] { explicitType, levelName, activeViewName }
                .Where(value => !string.IsNullOrWhiteSpace(value))
                .ToList();

            return parts.Count == 0 ? "default context" : string.Join(" / ", parts);
        }

        private List<Room> ResolveRoomsForSanitaryCheck(
            Document doc,
            List<IdType> roomIds,
            string levelName,
            string roomNameContains,
            string roomNumberContains)
        {
            if (roomIds != null && roomIds.Count > 0)
            {
                return roomIds
                    .Select(id => doc.GetElement(id.ToElementId()) as Room)
                    .Where(r => r != null && r.Area > 0)
                    .OrderBy(r => doc.GetElement(r.LevelId)?.Name)
                    .ThenBy(r => r.Number)
                    .ToList();
            }

            IEnumerable<Room> query = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Rooms)
                .WhereElementIsNotElementType()
                .Cast<Room>()
                .Where(r => r.Area > 0);

            if (!string.IsNullOrWhiteSpace(levelName))
            {
                Level level = FindLevel(doc, levelName, false);
                query = query.Where(r => r.LevelId == level.Id);
            }

            if (!string.IsNullOrWhiteSpace(roomNameContains))
            {
                query = query.Where(r => GetRoomName(r).IndexOf(roomNameContains, StringComparison.OrdinalIgnoreCase) >= 0);
            }

            if (!string.IsNullOrWhiteSpace(roomNumberContains))
            {
                query = query.Where(r => (r.Number ?? "").IndexOf(roomNumberContains, StringComparison.OrdinalIgnoreCase) >= 0);
            }

            return query
                .OrderBy(r => doc.GetElement(r.LevelId)?.Name)
                .ThenBy(r => r.Number)
                .ToList();
        }

        private SanitaryRoomResult BuildSanitaryRoomResult(Document doc, Room room, double areaPerPerson, List<string> excludeKeywords)
        {
            double areaM2 = room.Area * SquareFeetToSquareMeters;
            string roomName = GetRoomName(room);
            string roomNumber = room.Number ?? "";
            string exclusionReason = GetSanitaryExclusionReason(roomName, roomNumber, excludeKeywords);

            return new SanitaryRoomResult
            {
                RoomId = room.Id.GetIdValue(),
                Level = doc.GetElement(room.LevelId)?.Name ?? "",
                RoomNumber = roomNumber,
                RoomName = roomName,
                AreaM2 = Math.Round(areaM2, 2),
                Occupancy = string.IsNullOrEmpty(exclusionReason) ? CeilingToInt(areaM2 / areaPerPerson) : 0,
                ExcludedFromOccupancy = !string.IsNullOrEmpty(exclusionReason),
                ExclusionReason = exclusionReason
            };
        }

        private string GetRoomName(Room room)
        {
            return room.get_Parameter(BuiltInParameter.ROOM_NAME)?.AsString() ?? room.Name ?? "";
        }

        private List<string> ResolveSanitaryExcludeKeywords(JObject parameters)
        {
            var defaults = new[]
            {
                "\u6a13\u68af", "\u68af\u9593", "stair",
                "\u96fb\u68af", "elevator", "lift",
                "\u9632\u7a7a", "\u907f\u96e3", "refuge", "shelter",
                "\u505c\u8eca", "\u8eca\u4f4d", "\u8eca\u9053", "parking"
            };

            var result = defaults.ToList();
            if (parameters["excludeKeywords"] is JArray customKeywords)
            {
                result.AddRange(customKeywords
                    .Select(v => v.Value<string>())
                    .Where(v => !string.IsNullOrWhiteSpace(v)));
            }

            return result
                .Select(v => v.Trim())
                .Where(v => v.Length > 0)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToList();
        }

        private string GetSanitaryExclusionReason(string roomName, string roomNumber, List<string> excludeKeywords)
        {
            string haystack = $"{roomName} {roomNumber}";
            string matched = excludeKeywords.FirstOrDefault(keyword =>
                haystack.IndexOf(keyword, StringComparison.OrdinalIgnoreCase) >= 0);

            return matched == null ? "" : $"Matched exclude keyword: {matched}";
        }

        private int CalculateFactoryWarehouseMaleWaterClosets(int totalPopulation, int malePopulation)
        {
            if (totalPopulation <= 0)
            {
                return 0;
            }

            if (totalPopulation <= 100)
            {
                return 1;
            }

            return 1 + CeilingToInt((malePopulation - 100) / 120.0);
        }

        private int CalculateFactoryWarehouseFemaleWaterClosets(int totalPopulation, int femalePopulation)
        {
            if (totalPopulation <= 0)
            {
                return 0;
            }

            if (totalPopulation <= 24)
            {
                return 1;
            }

            if (totalPopulation <= 49)
            {
                return 2;
            }

            if (totalPopulation <= 100)
            {
                return 3;
            }

            return 3 + CeilingToInt((femalePopulation - 100) / 30.0);
        }

        private int CalculateFactoryWarehouseMaleUrinals(int totalPopulation, int malePopulation)
        {
            if (totalPopulation <= 0)
            {
                return 0;
            }

            if (totalPopulation <= 49)
            {
                return 1;
            }

            if (totalPopulation <= 100)
            {
                return 2;
            }

            return 2 + CeilingToInt((malePopulation - 100) / 60.0);
        }

        private int CalculateFactoryWarehouseLavatories(int totalPopulation)
        {
            if (totalPopulation <= 0)
            {
                return 0;
            }

            if (totalPopulation <= 100)
            {
                return CeilingToInt(totalPopulation / 10.0);
            }

            return CeilingToInt(totalPopulation / 15.0);
        }

        private int CeilingToInt(double value)
        {
            return (int)Math.Ceiling(Math.Max(0.0, value));
        }

        private class SanitaryFixtureRequirement
        {
            public string BuildingTypeCode { get; set; }
            public string BuildingType { get; set; }
            public string RuleId { get; set; }
            public double GrossAreaM2 { get; set; }
            public double ExcludedAreaM2 { get; set; }
            public double NetFactoryAreaM2 { get; set; }
            public double AreaPerPersonM2 { get; set; }
            public int TotalPopulation { get; set; }
            public double MaleRatio { get; set; }
            public double FemaleRatio { get; set; }
            public int MalePopulation { get; set; }
            public int FemalePopulation { get; set; }
            public int MaleWaterClosets { get; set; }
            public int FemaleWaterClosets { get; set; }
            public int MaleUrinals { get; set; }
            public int Lavatories { get; set; }
            public string BathtubsOrShowers { get; set; }
        }

        private class SanitaryBuildingRule
        {
            public string Code { get; set; }
            public string RuleId { get; set; }
            public string DisplayName { get; set; }
            public string Description { get; set; }
            public List<string> Keywords { get; set; }
            public string DetectionReason { get; set; }
        }

        private class SanitaryRoomResult
        {
            public IdType RoomId { get; set; }
            public string Level { get; set; }
            public string RoomNumber { get; set; }
            public string RoomName { get; set; }
            public double AreaM2 { get; set; }
            public int Occupancy { get; set; }
            public bool ExcludedFromOccupancy { get; set; }
            public string ExclusionReason { get; set; }
        }
    }
}
