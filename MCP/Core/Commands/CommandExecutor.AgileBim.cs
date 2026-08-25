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
        /// <summary>
        /// Read-only relationship audit for the first Agile BIM workflow slice.
        /// It deliberately reports evidence and uncertainty; it does not write parameters,
        /// create geometry, or infer design intent from FromRoom/ToRoom alone.
        /// </summary>
        private object AuditRoomWallDoorRelations(JObject parameters)
        {
            if (_uiApp.ActiveUIDocument == null)
            {
                throw new Exception("沒有作用中的 Revit 文件，無法盤點房間、牆與門窗關係。");
            }

            Document doc = _uiApp.ActiveUIDocument.Document;
            string levelName = parameters["level"]?.Value<string>();
            bool includeUnnamed = parameters["includeUnnamed"]?.Value<bool>() ?? true;
            bool includeUnplaced = parameters["includeUnplaced"]?.Value<bool>() ?? true;
            bool includeWindows = parameters["includeWindows"]?.Value<bool>() ?? true;
            bool includeUnassigned = parameters["includeUnassigned"]?.Value<bool>() ?? true;
            bool includeWallDetails = parameters["includeWallDetails"]?.Value<bool>() ?? true;
            int maxRooms = ClampAuditLimit(parameters["maxRooms"]?.Value<int?>(), 1, 200, 100);
            int maxUnassigned = ClampAuditLimit(parameters["maxUnassigned"]?.Value<int?>(), 0, 500, 200);

            List<IdType> explicitRoomIds = (parameters["roomIds"] as JArray)?
                .Select(value => value.Value<IdType>())
                .Where(id => id != 0)
                .Distinct()
                .ToList();

            List<Room> rooms = ResolveAgileAuditRooms(
                doc, levelName, explicitRoomIds, includeUnnamed, includeUnplaced);
            int totalRoomCount = rooms.Count;
            List<AgileAuditRoomRecord> allRecords = rooms
                .Select(BuildAgileAuditRoomRecord)
                .ToList();
            List<AgileAuditRoomRecord> returnedRecords = allRecords
                .Take(maxRooms)
                .ToList();
            Dictionary<IdType, AgileAuditRoomRecord> roomById = allRecords
                .ToDictionary(record => record.ElementId);
            Dictionary<IdType, List<AgileAuditRoomRecord>> wallToRooms =
                new Dictionary<IdType, List<AgileAuditRoomRecord>>();
            HashSet<IdType> boundaryWallIds = new HashSet<IdType>();

            foreach (AgileAuditRoomRecord record in allRecords)
            {
                AttachAgileAuditBoundaries(doc, record, boundaryWallIds, wallToRooms,
                    includeWallDetails);
            }

            List<object> unassignedDoors = new List<object>();
            List<object> unassignedWindows = new List<object>();
            HashSet<IdType> assignedDoorIds = new HashSet<IdType>();
            HashSet<IdType> assignedWindowIds = new HashSet<IdType>();
            int totalDoorCount = 0;
            int totalWindowCount = 0;

            List<FamilyInstance> doors = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Doors)
                .WhereElementIsNotElementType()
                .OfType<FamilyInstance>()
                .ToList();

            foreach (FamilyInstance door in doors)
            {
                totalDoorCount++;
                AttachAgileAuditOpening(doc, door, true, roomById, wallToRooms,
                    assignedDoorIds, unassignedDoors, maxUnassigned);
            }

            if (includeWindows)
            {
                List<FamilyInstance> windows = new FilteredElementCollector(doc)
                    .OfCategory(BuiltInCategory.OST_Windows)
                    .WhereElementIsNotElementType()
                    .OfType<FamilyInstance>()
                    .ToList();

                foreach (FamilyInstance window in windows)
                {
                    totalWindowCount++;
                    AttachAgileAuditOpening(doc, window, false, roomById, wallToRooms,
                        assignedWindowIds, unassignedWindows, maxUnassigned);
                }
            }

            foreach (AgileAuditRoomRecord record in allRecords)
            {
                if (record.BoundaryWallIds.Count == 0)
                {
                    record.RelationStatus = "unresolved";
                    if (record.Warnings.Count == 0)
                    {
                        record.Warnings.Add("未取得可辨識的邊界牆；需檢查 Room Bounding、Phase 或邊界設定。");
                    }
                }
                else if (record.RelationStatus != "unresolved")
                {
                    record.RelationStatus = "confirmed";
                }
            }

            int assignedDoorCount = assignedDoorIds.Count;
            int assignedWindowCount = assignedWindowIds.Count;
            int inferredDoorCount = allRecords.Sum(record =>
                record.Doors.Count(item => ReadAuditRelationStatus(item) == "inferred"));
            int inferredWindowCount = allRecords.Sum(record =>
                record.Windows.Count(item => ReadAuditRelationStatus(item) == "inferred"));

            return new
            {
                Success = true,
                Scope = new
                {
                    Level = levelName,
                    RoomIds = explicitRoomIds,
                    IncludeUnnamed = includeUnnamed,
                    IncludeUnplaced = includeUnplaced,
                    IncludeWindows = includeWindows,
                    IncludeUnassigned = includeUnassigned,
                    IncludeWallDetails = includeWallDetails,
                    MaxRooms = maxRooms,
                    MaxUnassigned = maxUnassigned,
                    Rule = "Room boundaries are evidence; door/window FromRoom and ToRoom are reported separately. Host-wall matching is marked inferred and never treated as design intent."
                },
                Summary = new
                {
                    TotalRooms = totalRoomCount,
                    ReturnedRooms = returnedRecords.Count,
                    RoomsTruncated = totalRoomCount > returnedRecords.Count,
                    BoundaryWalls = boundaryWallIds.Count,
                    TotalDoors = totalDoorCount,
                    AssignedDoors = assignedDoorCount,
                    InferredDoors = inferredDoorCount,
                    UnassignedDoors = Math.Max(0, totalDoorCount - assignedDoorIds.Count),
                    TotalWindows = totalWindowCount,
                    AssignedWindows = assignedWindowCount,
                    InferredWindows = inferredWindowCount,
                    UnassignedWindows = Math.Max(0, totalWindowCount - assignedWindowIds.Count)
                },
                Rooms = returnedRecords.Select(record => record.ToResponse(includeWallDetails)).ToList(),
                UnassignedDoors = includeUnassigned ? unassignedDoors : null,
                UnassignedWindows = includeUnassigned && includeWindows ? unassignedWindows : null,
                Message = "唯讀盤點完成；本命令沒有修改模型。"
            };
        }

        private List<Room> ResolveAgileAuditRooms(
            Document doc,
            string levelName,
            List<IdType> explicitRoomIds,
            bool includeUnnamed,
            bool includeUnplaced)
        {
            IEnumerable<Room> query;
            if (explicitRoomIds != null && explicitRoomIds.Count > 0)
            {
                query = explicitRoomIds
                    .Select(id => doc.GetElement(id.ToElementId()) as Room)
                    .Where(room => room != null);
            }
            else
            {
                query = new FilteredElementCollector(doc)
                    .OfCategory(BuiltInCategory.OST_Rooms)
                    .WhereElementIsNotElementType()
                    .OfType<Room>();
            }

            if (!string.IsNullOrWhiteSpace(levelName))
            {
                Level targetLevel = FindLevel(doc, levelName, false);
                query = query.Where(room => room.LevelId == targetLevel.Id);
            }

            return query
                .Where(room => includeUnplaced || room.Area > 0)
                .Where(room => includeUnnamed || !string.IsNullOrWhiteSpace(GetAgileAuditRoomName(room)))
                .OrderBy(room => SafeAgileAuditLevelName(doc, room))
                .ThenBy(room => GetAgileAuditRoomNumber(room))
                .ThenBy(room => GetAgileAuditRoomName(room))
                .ToList();
        }

        private AgileAuditRoomRecord BuildAgileAuditRoomRecord(Room room)
        {
            return new AgileAuditRoomRecord
            {
                ElementId = room.Id.GetIdValue(),
                UniqueId = room.UniqueId,
                Number = GetAgileAuditRoomNumber(room),
                Name = GetAgileAuditRoomName(room),
                Level = SafeAgileAuditLevelName(_uiApp.ActiveUIDocument.Document, room),
                AreaM2 = Math.Round(room.Area * 0.09290304, 2),
                RelationStatus = "unresolved"
            };
        }

        private void AttachAgileAuditBoundaries(
            Document doc,
            AgileAuditRoomRecord record,
            HashSet<IdType> boundaryWallIds,
            Dictionary<IdType, List<AgileAuditRoomRecord>> wallToRooms,
            bool includeWallDetails)
        {
            try
            {
                Room room = doc.GetElement(record.ElementId.ToElementId()) as Room;
                if (room == null)
                {
                    record.Warnings.Add("無法重新取得 Room 元素。");
                    return;
                }

                IList<IList<BoundarySegment>> loops = room.GetBoundarySegments(
                    new SpatialElementBoundaryOptions());
                if (loops == null || loops.Count == 0)
                {
                    record.Warnings.Add("Room 沒有邊界線段。");
                    return;
                }

                foreach (IList<BoundarySegment> loop in loops)
                {
                    if (loop == null) continue;
                    foreach (BoundarySegment segment in loop)
                    {
                        if (segment == null) continue;
                        Element boundary = doc.GetElement(segment.ElementId);
                        if (!(boundary is Wall wall)) continue;

                        IdType wallId = wall.Id.GetIdValue();
                        boundaryWallIds.Add(wallId);
                        if (!record.BoundaryWallIds.Add(wallId)) continue;

                        if (includeWallDetails)
                        {
                            record.BoundaryWalls.Add(new
                            {
                                ElementId = wallId,
                                UniqueId = wall.UniqueId,
                                Name = SafeAgileAuditElementName(wall),
                                Type = SafeAgileAuditWallTypeName(wall),
                                RelationStatus = "confirmed"
                            });
                        }

                        if (!wallToRooms.TryGetValue(wallId, out List<AgileAuditRoomRecord> linkedRooms))
                        {
                            linkedRooms = new List<AgileAuditRoomRecord>();
                            wallToRooms[wallId] = linkedRooms;
                        }
                        if (!linkedRooms.Contains(record)) linkedRooms.Add(record);
                    }
                }

                if (record.BoundaryWallIds.Count > 0)
                {
                    record.RelationStatus = "confirmed";
                }
            }
            catch (Exception ex)
            {
                record.RelationStatus = "unresolved";
                record.Warnings.Add("讀取 Room 邊界失敗：" + ex.Message);
            }
        }

        private void AttachAgileAuditOpening(
            Document doc,
            FamilyInstance opening,
            bool isDoor,
            Dictionary<IdType, AgileAuditRoomRecord> roomById,
            Dictionary<IdType, List<AgileAuditRoomRecord>> wallToRooms,
            HashSet<IdType> assignedOpeningIds,
            List<object> unassigned,
            int maxUnassigned)
        {
            Room fromRoom = isDoor
                ? SafeGetDoorFromRoom(doc, opening)
                : SafeGetWindowFromRoom(doc, opening);
            Room toRoom = isDoor
                ? SafeGetDoorToRoom(doc, opening)
                : SafeGetWindowToRoom(doc, opening);

            IdType openingId = opening.Id.GetIdValue();
            var matched = new List<Tuple<AgileAuditRoomRecord, string>>();
            AddAgileAuditRoomMatch(roomById, fromRoom, matched, "FromRoom");
            AddAgileAuditRoomMatch(roomById, toRoom, matched, "ToRoom");

            if (matched.Count == 0 && opening.Host != null)
            {
                IdType hostId = opening.Host.Id.GetIdValue();
                if (wallToRooms.TryGetValue(hostId, out List<AgileAuditRoomRecord> hostRooms))
                {
                    foreach (AgileAuditRoomRecord record in hostRooms)
                    {
                        matched.Add(Tuple.Create(record, "HostWallBoundary"));
                    }
                }
            }

            if (matched.Count == 0)
            {
                if (unassigned.Count < maxUnassigned)
                {
                    unassigned.Add(BuildAgileAuditOpeningSummary(
                        doc, opening, isDoor, fromRoom, toRoom, "unresolved", "NoRoomMatch"));
                }
                return;
            }

            string relationStatus = matched.Any(item => item.Item2 == "FromRoom" || item.Item2 == "ToRoom")
                ? "confirmed"
                : "inferred";

            foreach (Tuple<AgileAuditRoomRecord, string> match in matched
                .GroupBy(item => item.Item1.ElementId)
                .Select(group => group.First()))
            {
                AgileAuditRoomRecord record = match.Item1;
                if (isDoor)
                {
                    if (!record.DoorIds.Add(openingId)) continue;
                    record.Doors.Add(BuildAgileAuditOpeningSummary(
                        doc, opening, true, fromRoom, toRoom, relationStatus, match.Item2));
                }
                else
                {
                    if (!record.WindowIds.Add(openingId)) continue;
                    record.Windows.Add(BuildAgileAuditOpeningSummary(
                        doc, opening, false, fromRoom, toRoom, relationStatus, match.Item2));
                }
                assignedOpeningIds.Add(openingId);
            }
        }

        private static void AddAgileAuditRoomMatch(
            Dictionary<IdType, AgileAuditRoomRecord> roomById,
            Room room,
            List<Tuple<AgileAuditRoomRecord, string>> matches,
            string source)
        {
            if (room == null) return;
            IdType roomId = room.Id.GetIdValue();
            if (roomById.TryGetValue(roomId, out AgileAuditRoomRecord record)
                && !matches.Any(item => item.Item1.ElementId == roomId))
            {
                matches.Add(Tuple.Create(record, source));
            }
        }

        private object BuildAgileAuditOpeningSummary(
            Document doc,
            FamilyInstance opening,
            bool isDoor,
            Room fromRoom,
            Room toRoom,
            string relationStatus,
            string relationSource)
        {
            Element type = doc.GetElement(opening.GetTypeId());
            Element host = opening.Host;
            return new
            {
                ElementId = opening.Id.GetIdValue(),
                UniqueId = opening.UniqueId,
                Category = isDoor ? "Doors" : "Windows",
                Family = SafeAgileAuditFamilyName(opening),
                Type = SafeAgileAuditSymbolName(opening),
                TypeMark = isDoor
                    ? GetParameterString(type, BuiltInParameter.ALL_MODEL_TYPE_MARK)
                    : GetWindowParameterString(type, BuiltInParameter.ALL_MODEL_TYPE_MARK),
                Mark = isDoor
                    ? GetParameterString(opening, BuiltInParameter.ALL_MODEL_MARK)
                    : GetWindowParameterString(opening, BuiltInParameter.ALL_MODEL_MARK),
                HostWallId = host == null ? (IdType)0 : host.Id.GetIdValue(),
                Level = isDoor ? GetDoorLevelName(doc, opening) : GetWindowLevelName(doc, opening),
                FromRoomId = fromRoom == null ? (IdType)0 : fromRoom.Id.GetIdValue(),
                FromRoomNumber = fromRoom?.Number,
                FromRoomName = fromRoom == null ? null : GetAgileAuditRoomName(fromRoom),
                ToRoomId = toRoom == null ? (IdType)0 : toRoom.Id.GetIdValue(),
                ToRoomNumber = toRoom?.Number,
                ToRoomName = toRoom == null ? null : GetAgileAuditRoomName(toRoom),
                RelationStatus = relationStatus,
                RelationSource = relationSource
            };
        }

        private static int ClampAuditLimit(int? value, int min, int max, int fallback)
        {
            int resolved = value ?? fallback;
            return Math.Max(min, Math.Min(max, resolved));
        }

        private static string ReadAuditRelationStatus(object item)
        {
            try
            {
                var property = item.GetType().GetProperty("RelationStatus");
                return property?.GetValue(item, null) as string;
            }
            catch
            {
                return null;
            }
        }

        private static string GetAgileAuditRoomName(Room room)
        {
            try
            {
                return room.get_Parameter(BuiltInParameter.ROOM_NAME)?.AsString()
                    ?? room.Name
                    ?? "";
            }
            catch
            {
                return "";
            }
        }

        private static string GetAgileAuditRoomNumber(Room room)
        {
            try { return room.Number ?? ""; }
            catch { return ""; }
        }

        private static string SafeAgileAuditLevelName(Document doc, Room room)
        {
            try { return doc.GetElement(room.LevelId)?.Name; }
            catch { return null; }
        }

        private static string SafeAgileAuditElementName(Element element)
        {
            try { return element?.Name; }
            catch { return null; }
        }

        private static string SafeAgileAuditWallTypeName(Wall wall)
        {
            try { return wall.WallType?.Name; }
            catch { return SafeAgileAuditElementName(wall); }
        }

        private static string SafeAgileAuditFamilyName(FamilyInstance instance)
        {
            try { return instance.Symbol?.FamilyName; }
            catch { return null; }
        }

        private static string SafeAgileAuditSymbolName(FamilyInstance instance)
        {
            try { return instance.Symbol?.Name; }
            catch { return null; }
        }

        private sealed class AgileAuditRoomRecord
        {
            public IdType ElementId { get; set; }
            public string UniqueId { get; set; }
            public string Number { get; set; }
            public string Name { get; set; }
            public string Level { get; set; }
            public double AreaM2 { get; set; }
            public string RelationStatus { get; set; }
            public List<object> BoundaryWalls { get; } = new List<object>();
            public List<object> Doors { get; } = new List<object>();
            public List<object> Windows { get; } = new List<object>();
            public List<string> Warnings { get; } = new List<string>();

            public HashSet<IdType> BoundaryWallIds { get; } = new HashSet<IdType>();
            public HashSet<IdType> DoorIds { get; } = new HashSet<IdType>();
            public HashSet<IdType> WindowIds { get; } = new HashSet<IdType>();

            public object ToResponse(bool includeWallDetails)
            {
                return new
                {
                    ElementId,
                    UniqueId,
                    Number,
                    Name,
                    Level,
                    AreaM2,
                    RelationStatus,
                    BoundaryWalls = includeWallDetails ? BoundaryWalls : null,
                    Doors,
                    Windows,
                    Warnings
                };
            }
        }
    }
}
