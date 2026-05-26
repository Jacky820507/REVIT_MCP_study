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
        private const double FeetToMm = 304.8;

        private object SyncRoomCeilingFinishFromCeilings(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            string levelName = parameters["level"]?.Value<string>();
            string roomName = parameters["roomName"]?.Value<string>();
            string targetParameter = parameters["targetParameter"]?.Value<string>() ?? "天花板塗層";
            bool apply = parameters["apply"]?.Value<bool>() ?? false;
            bool overwrite = parameters["overwrite"]?.Value<bool>() ?? false;
            int sampleGrid = Math.Max(1, Math.Min(parameters["sampleGrid"]?.Value<int>() ?? 3, 7));
            string multiMatchStrategy = (parameters["multiMatchStrategy"]?.Value<string>() ?? "largestOverlap").Trim();
            var roomIds = (parameters["roomIds"] as JArray)?
                .Select(v => v.Value<IdType>())
                .Where(id => id != 0)
                .ToList();

            var rooms = ResolveRoomsForCeilingFinish(doc, roomIds, levelName, roomName);
            var ceilings = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Ceilings)
                .WhereElementIsNotElementType()
                .ToElements()
                .ToList();

            var results = new List<RoomCeilingFinishResult>();

            foreach (Room room in rooms)
            {
                RoomCeilingFinishResult result = AnalyzeRoomCeilingFinish(
                    doc,
                    room,
                    ceilings,
                    targetParameter,
                    overwrite,
                    sampleGrid,
                    multiMatchStrategy);

                results.Add(result);
            }

            int appliedCount = 0;
            if (apply)
            {
                using (Transaction trans = new Transaction(doc, "同步房間天花板塗層"))
                {
                    trans.Start();

                    foreach (RoomCeilingFinishResult result in results.Where(r => r.CanWrite && !string.IsNullOrWhiteSpace(r.ProposedValue)))
                    {
                        Room room = doc.GetElement(result.RoomId.ToElementId()) as Room;
                        Parameter param = room?.LookupParameter(targetParameter);
                        if (param == null || param.IsReadOnly)
                        {
                            result.Status = param == null ? "MissingTargetParameter" : "ReadOnlyTargetParameter";
                            continue;
                        }

                        if (SetStringLikeParameter(param, result.ProposedValue))
                        {
                            appliedCount++;
                            result.Applied = true;
                            result.Status = "Applied";
                        }
                        else
                        {
                            result.Status = "WriteFailed";
                            result.Warnings.Add($"無法寫入參數 {targetParameter}");
                        }
                    }

                    trans.Commit();
                }
            }

            return new
            {
                Apply = apply,
                Overwrite = overwrite,
                TargetParameter = targetParameter,
                TypeMarkSource = "Ceiling type ALL_MODEL_TYPE_MARK / 類型標記 / Type Mark",
                TotalRooms = rooms.Count,
                TotalCeilings = ceilings.Count,
                RoomsWithCandidate = results.Count(r => r.Candidates.Count > 0),
                PlannedUpdates = results.Count(r => r.CanWrite && !string.IsNullOrWhiteSpace(r.ProposedValue)),
                AppliedUpdates = appliedCount,
                SkippedExistingValue = results.Count(r => r.Status == "SkippedExistingValue"),
                MissingTargetParameter = results.Count(r => r.Status == "MissingTargetParameter"),
                ReadOnlyTargetParameter = results.Count(r => r.Status == "ReadOnlyTargetParameter"),
                NoCandidate = results.Count(r => r.Status == "NoCandidate"),
                NoTypeMark = results.Count(r => r.Status == "NoTypeMark"),
                Results = results
            };
        }

        private List<Room> ResolveRoomsForCeilingFinish(Document doc, List<IdType> roomIds, string levelName, string roomName)
        {
            if (roomIds != null && roomIds.Count > 0)
            {
                return roomIds
                    .Select(id => doc.GetElement(id.ToElementId()) as Room)
                    .Where(r => r != null && r.Area > 0)
                    .OrderBy(r => r.Number)
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

            if (!string.IsNullOrWhiteSpace(roomName))
            {
                query = query.Where(r =>
                    (r.Number ?? "").IndexOf(roomName, StringComparison.OrdinalIgnoreCase) >= 0 ||
                    (r.get_Parameter(BuiltInParameter.ROOM_NAME)?.AsString() ?? "").IndexOf(roomName, StringComparison.OrdinalIgnoreCase) >= 0);
            }

            return query.OrderBy(r => doc.GetElement(r.LevelId)?.Name).ThenBy(r => r.Number).ToList();
        }

        private RoomCeilingFinishResult AnalyzeRoomCeilingFinish(
            Document doc,
            Room room,
            List<Element> ceilings,
            string targetParameter,
            bool overwrite,
            int sampleGrid,
            string multiMatchStrategy)
        {
            string roomName = room.get_Parameter(BuiltInParameter.ROOM_NAME)?.AsString() ?? room.Name ?? "";
            string levelName = doc.GetElement(room.LevelId)?.Name ?? "";
            var result = new RoomCeilingFinishResult
            {
                RoomId = room.Id.GetIdValue(),
                RoomNumber = room.Number,
                RoomName = roomName,
                Level = levelName
            };

            Parameter target = room.LookupParameter(targetParameter);
            if (target == null)
            {
                result.Status = "MissingTargetParameter";
                result.Warnings.Add($"房間缺少參數 {targetParameter}");
                return result;
            }

            result.CurrentValue = target.AsString() ?? target.AsValueString() ?? "";
            if (target.IsReadOnly)
            {
                result.Status = "ReadOnlyTargetParameter";
                result.Warnings.Add($"參數 {targetParameter} 是唯讀");
                return result;
            }

            if (!overwrite && !string.IsNullOrWhiteSpace(result.CurrentValue))
            {
                result.Status = "SkippedExistingValue";
                result.Warnings.Add("既有值非空，未啟用 overwrite");
                return result;
            }

            BoundingBoxXYZ roomBox = room.get_BoundingBox(null);
            if (roomBox == null)
            {
                result.Status = "NoRoomBoundingBox";
                result.Warnings.Add("無法取得房間 BoundingBox");
                return result;
            }

            foreach (Element ceiling in ceilings)
            {
                ElementId ceilingLevelId = GetElementLevelId(ceiling);
                if (ceilingLevelId != ElementId.InvalidElementId && ceilingLevelId != room.LevelId)
                {
                    continue;
                }

                CeilingCandidate candidate = BuildCeilingCandidate(doc, room, roomBox, ceiling, sampleGrid);
                if (candidate != null)
                {
                    result.Candidates.Add(candidate);
                }
            }

            result.Candidates = result.Candidates
                .OrderByDescending(c => c.Score)
                .ThenByDescending(c => c.OverlapAreaM2)
                .ToList();

            if (result.Candidates.Count == 0)
            {
                result.Status = "NoCandidate";
                result.Warnings.Add("未找到落在房間範圍內的天花板");
                return result;
            }

            var candidatesWithMark = result.Candidates
                .Where(c => !string.IsNullOrWhiteSpace(c.TypeMark))
                .ToList();

            if (candidatesWithMark.Count == 0)
            {
                result.Status = "NoTypeMark";
                result.Warnings.Add("有找到天花板，但天花板類型沒有類型標記");
                return result;
            }

            if (multiMatchStrategy.Equals("join", StringComparison.OrdinalIgnoreCase))
            {
                result.ProposedValue = string.Join("+", candidatesWithMark
                    .GroupBy(c => c.TypeMark)
                    .OrderByDescending(g => g.Sum(c => c.Score))
                    .Select(g => g.Key));
            }
            else
            {
                result.ProposedValue = candidatesWithMark.First().TypeMark;
            }

            result.Status = "Ready";
            result.CanWrite = true;
            return result;
        }

        private CeilingCandidate BuildCeilingCandidate(Document doc, Room room, BoundingBoxXYZ roomBox, Element ceiling, int sampleGrid)
        {
            BoundingBoxXYZ ceilingBox = ceiling.get_BoundingBox(null);
            if (ceilingBox == null || !BoundingBoxesOverlapXY(roomBox, ceilingBox))
            {
                return null;
            }

            double minX = Math.Max(roomBox.Min.X, ceilingBox.Min.X);
            double maxX = Math.Min(roomBox.Max.X, ceilingBox.Max.X);
            double minY = Math.Max(roomBox.Min.Y, ceilingBox.Min.Y);
            double maxY = Math.Min(roomBox.Max.Y, ceilingBox.Max.Y);
            double overlapArea = Math.Max(0, maxX - minX) * Math.Max(0, maxY - minY);
            if (overlapArea <= 0)
            {
                return null;
            }

            int insideSamples = 0;
            int totalSamples = sampleGrid * sampleGrid;
            double z = (roomBox.Min.Z + roomBox.Max.Z) / 2.0;

            for (int ix = 0; ix < sampleGrid; ix++)
            {
                double x = minX + (maxX - minX) * ((ix + 0.5) / sampleGrid);
                for (int iy = 0; iy < sampleGrid; iy++)
                {
                    double y = minY + (maxY - minY) * ((iy + 0.5) / sampleGrid);
                    if (room.IsPointInRoom(new XYZ(x, y, z)))
                    {
                        insideSamples++;
                    }
                }
            }

            if (insideSamples == 0)
            {
                return null;
            }

            string typeName = "";
            string typeMark = "";
            Element type = doc.GetElement(ceiling.GetTypeId());
            if (type != null)
            {
                typeName = type.Name;
                typeMark = GetTypeMark(type);
            }

            double insideRatio = (double)insideSamples / totalSamples;
            double overlapAreaM2 = overlapArea * 0.09290304;

            return new CeilingCandidate
            {
                CeilingId = ceiling.Id.GetIdValue(),
                TypeId = ceiling.GetTypeId().GetIdValue(),
                TypeName = typeName,
                TypeMark = typeMark,
                OverlapAreaM2 = Math.Round(overlapAreaM2, 3),
                InsideSampleRatio = Math.Round(insideRatio, 3),
                Score = Math.Round(overlapAreaM2 * insideRatio, 3)
            };
        }

        private ElementId GetElementLevelId(Element element)
        {
            if (element.LevelId != ElementId.InvalidElementId)
            {
                return element.LevelId;
            }

            Parameter levelParam = element.get_Parameter(BuiltInParameter.LEVEL_PARAM);
            return levelParam?.AsElementId() ?? ElementId.InvalidElementId;
        }

        private bool BoundingBoxesOverlapXY(BoundingBoxXYZ a, BoundingBoxXYZ b)
        {
            return a.Min.X <= b.Max.X &&
                   a.Max.X >= b.Min.X &&
                   a.Min.Y <= b.Max.Y &&
                   a.Max.Y >= b.Min.Y;
        }

        private string GetTypeMark(Element type)
        {
            Parameter markParam = type.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_MARK)
                ?? type.LookupParameter("類型標記")
                ?? type.LookupParameter("Type Mark");

            return markParam?.AsString() ?? markParam?.AsValueString() ?? "";
        }

        private bool SetStringLikeParameter(Parameter param, string value)
        {
            switch (param.StorageType)
            {
                case StorageType.String:
                    return param.Set(value);
                case StorageType.Integer:
                case StorageType.Double:
                    return param.SetValueString(value);
                default:
                    return false;
            }
        }

        private class RoomCeilingFinishResult
        {
            public IdType RoomId { get; set; }
            public string RoomNumber { get; set; }
            public string RoomName { get; set; }
            public string Level { get; set; }
            public string CurrentValue { get; set; }
            public string ProposedValue { get; set; }
            public string Status { get; set; }
            public bool CanWrite { get; set; }
            public bool Applied { get; set; }
            public List<string> Warnings { get; set; } = new List<string>();
            public List<CeilingCandidate> Candidates { get; set; } = new List<CeilingCandidate>();
        }

        private class CeilingCandidate
        {
            public IdType CeilingId { get; set; }
            public IdType TypeId { get; set; }
            public string TypeName { get; set; }
            public string TypeMark { get; set; }
            public double OverlapAreaM2 { get; set; }
            public double InsideSampleRatio { get; set; }
            public double Score { get; set; }
        }
    }
}
