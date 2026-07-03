using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Architecture;
using Newtonsoft.Json.Linq;

namespace RevitMCP.Core
{
    public partial class CommandExecutor
    {
        private object RenumberRoomsByLevel(JObject parameters)
        {
            Stopwatch sw = Stopwatch.StartNew();
            Document doc = _uiApp.ActiveUIDocument.Document;

            string levelName = parameters["level"]?.Value<string>();
            string startNumber = parameters["startNumber"]?.Value<string>();
            bool dryRun = parameters["dryRun"]?.Value<bool>() ?? false;
            bool includeUnnamed = parameters["includeUnnamed"]?.Value<bool>() ?? true;
            bool allowExistingNumberConflicts = parameters["allowExistingNumberConflicts"]?.Value<bool>() ?? false;
            double yToleranceMm = parameters["yToleranceMm"]?.Value<double>() ?? 3000.0;
            string requestedParameterName = parameters["parameterName"]?.Value<string>();

            if (string.IsNullOrWhiteSpace(levelName))
            {
                throw new Exception("Parameter 'level' is required.");
            }

            if (string.IsNullOrWhiteSpace(startNumber))
            {
                throw new Exception("Parameter 'startNumber' is required, e.g. B134.");
            }

            NumberSeed seed = ParseNumberSeed(startNumber);
            Level targetLevel = ResolveRoomNumberingLevel(doc, levelName);
            double toleranceFeet = yToleranceMm / 304.8;

            List<RoomNumberingItem> items = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Rooms)
                .WhereElementIsNotElementType()
                .Cast<Room>()
                .Where(room => room.LevelId == targetLevel.Id)
                .Where(room => room.Area > 0)
                .Select(room => CreateRoomNumberingItem(room))
                .Where(item => item != null)
                .Where(item => includeUnnamed || item.HasName)
                .ToList();

            List<object> skippedRooms = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Rooms)
                .WhereElementIsNotElementType()
                .Cast<Room>()
                .Where(room => room.LevelId == targetLevel.Id)
                .Where(room => room.Area <= 0 || CreateRoomCenter(room) == null)
                .Select(room => new
                {
                    ElementId = room.Id.GetIdValue(),
                    Name = GetRoomNumberingRoomName(room),
                    Number = room.Number,
                    Reason = room.Area <= 0 ? "Unplaced or zero-area room" : "Room has no usable center point"
                } as object)
                .ToList();

            SortRoomNumberingItems(items, toleranceFeet);

            for (int i = 0; i < items.Count; i++)
            {
                RoomNumberingItem item = items[i];
                item.Sequence = i + 1;
                item.NewNumber = seed.Prefix + (seed.StartIndex + i).ToString("D" + seed.Width, CultureInfo.InvariantCulture);
            }

            List<object> conflicts = FindExternalRoomNumberConflicts(doc, items);
            if (conflicts.Count > 0 && !allowExistingNumberConflicts)
            {
                throw new Exception("Proposed room numbers already exist outside the target level. Re-run with allowExistingNumberConflicts=true if this is intentional. Conflicts: " + JArray.FromObject(conflicts).ToString());
            }

            string parameterNameUsed = requestedParameterName;
            int changedCount = 0;
            List<object> failures = new List<object>();

            if (!dryRun && items.Count > 0)
            {
                using (Transaction trans = new Transaction(doc, "Batch room renumber by level"))
                {
                    trans.Start();
                    FailureHandlingOptions failureOptions = trans.GetFailureHandlingOptions();
                    failureOptions.SetFailuresPreprocessor(new DismissWarningsPreprocessor());
                    trans.SetFailureHandlingOptions(failureOptions);

                    foreach (RoomNumberingItem item in items)
                    {
                        Parameter numberParam = GetWritableRoomNumberParameter(item.Room, requestedParameterName, out string resolvedName);
                        if (numberParam == null)
                        {
                            failures.Add(new
                            {
                                ElementId = item.ElementId,
                                Name = item.Name,
                                OldNumber = item.OldNumber,
                                NewNumber = item.NewNumber,
                                Error = "No writable room number parameter was found."
                            });
                            continue;
                        }

                        if (string.IsNullOrEmpty(parameterNameUsed))
                        {
                            parameterNameUsed = resolvedName;
                        }

                        bool success = numberParam.Set(item.NewNumber);
                        if (success)
                        {
                            changedCount++;
                        }
                        else
                        {
                            failures.Add(new
                            {
                                ElementId = item.ElementId,
                                Name = item.Name,
                                OldNumber = item.OldNumber,
                                NewNumber = item.NewNumber,
                                ParameterName = resolvedName,
                                Error = "Revit returned false while setting the parameter."
                            });
                        }
                    }

                    if (failures.Count > 0)
                    {
                        trans.RollBack();
                        throw new Exception("Room renumbering failed and was rolled back: " + JArray.FromObject(failures).ToString());
                    }

                    trans.Commit();
                }
            }
            else if (items.Count > 0)
            {
                Parameter previewParam = GetWritableRoomNumberParameter(items[0].Room, requestedParameterName, out string resolvedName);
                parameterNameUsed = requestedParameterName ?? resolvedName;
            }

            sw.Stop();

            return new
            {
                Success = true,
                Applied = !dryRun,
                DryRun = dryRun,
                Level = targetLevel.Name,
                LevelId = targetLevel.Id.GetIdValue(),
                RequestedLevel = levelName,
                StartNumber = startNumber,
                EndNumber = items.Count > 0 ? items[items.Count - 1].NewNumber : startNumber,
                Count = items.Count,
                ChangedCount = dryRun ? 0 : changedCount,
                ParameterName = parameterNameUsed ?? requestedParameterName ?? "ROOM_NUMBER",
                YToleranceMm = yToleranceMm,
                DurationMs = sw.ElapsedMilliseconds,
                Conflicts = conflicts,
                SkippedRooms = skippedRooms,
                Rooms = items.Select(item => new
                {
                    item.Sequence,
                    item.Row,
                    item.ElementId,
                    item.Name,
                    OldNumber = item.OldNumber,
                    NewNumber = item.NewNumber,
                    CenterX = Math.Round(item.Center.X * 304.8, 2),
                    CenterY = Math.Round(item.Center.Y * 304.8, 2)
                }).ToList()
            };
        }

        private static NumberSeed ParseNumberSeed(string startNumber)
        {
            Match match = Regex.Match(startNumber.Trim(), @"^(.*?)(\d+)$");
            if (!match.Success)
            {
                throw new Exception("startNumber must end with digits, e.g. B134.");
            }

            return new NumberSeed
            {
                Prefix = match.Groups[1].Value,
                StartIndex = int.Parse(match.Groups[2].Value, CultureInfo.InvariantCulture),
                Width = match.Groups[2].Value.Length
            };
        }

        private Level ResolveRoomNumberingLevel(Document doc, string levelName)
        {
            List<Level> levels = new FilteredElementCollector(doc)
                .OfClass(typeof(Level))
                .Cast<Level>()
                .OrderBy(level => level.Elevation)
                .ToList();

            List<Level> exact = levels
                .Where(level => string.Equals(level.Name, levelName, StringComparison.OrdinalIgnoreCase))
                .ToList();
            if (exact.Count == 1) return exact[0];

            List<Level> suffix = levels
                .Where(level => level.Name.EndsWith(levelName, StringComparison.OrdinalIgnoreCase))
                .ToList();
            if (suffix.Count == 1) return suffix[0];

            List<Level> contains = levels
                .Where(level => level.Name.IndexOf(levelName, StringComparison.OrdinalIgnoreCase) >= 0
                    || levelName.IndexOf(level.Name, StringComparison.OrdinalIgnoreCase) >= 0)
                .ToList();
            if (contains.Count == 1) return contains[0];

            if (exact.Count > 1 || suffix.Count > 1 || contains.Count > 1)
            {
                List<string> candidates = exact.Count > 1 ? exact.Select(level => level.Name).ToList()
                    : suffix.Count > 1 ? suffix.Select(level => level.Name).ToList()
                    : contains.Select(level => level.Name).ToList();
                throw new Exception("Level name is ambiguous. Candidates: " + string.Join(", ", candidates));
            }

            throw new Exception("Level was not found: " + levelName);
        }

        private static RoomNumberingItem CreateRoomNumberingItem(Room room)
        {
            XYZ center = CreateRoomCenter(room);
            if (center == null)
            {
                return null;
            }

            string name = GetRoomNumberingRoomName(room);
            bool hasName = !string.IsNullOrWhiteSpace(name) && name != "Room";

            return new RoomNumberingItem
            {
                Room = room,
                ElementId = room.Id.GetIdValue(),
                Name = string.IsNullOrWhiteSpace(name) ? "(Unnamed)" : name,
                HasName = hasName,
                OldNumber = room.Number,
                Center = center
            };
        }

        private static string GetRoomNumberingRoomName(Room room)
        {
            return room.get_Parameter(BuiltInParameter.ROOM_NAME)?.AsString() ?? room.Name;
        }

        private static XYZ CreateRoomCenter(Room room)
        {
            LocationPoint locPoint = room.Location as LocationPoint;
            if (locPoint != null)
            {
                return locPoint.Point;
            }

            BoundingBoxXYZ bbox = room.get_BoundingBox(null);
            if (bbox == null)
            {
                return null;
            }

            return new XYZ(
                (bbox.Min.X + bbox.Max.X) / 2.0,
                (bbox.Min.Y + bbox.Max.Y) / 2.0,
                (bbox.Min.Z + bbox.Max.Z) / 2.0);
        }

        private static void SortRoomNumberingItems(List<RoomNumberingItem> items, double toleranceFeet)
        {
            items.Sort((a, b) => b.Center.Y.CompareTo(a.Center.Y));

            double currentGroupY = items.Count > 0 ? items[0].Center.Y : 0.0;
            int row = 0;
            foreach (RoomNumberingItem item in items)
            {
                if (Math.Abs(item.Center.Y - currentGroupY) > toleranceFeet)
                {
                    row++;
                    currentGroupY = item.Center.Y;
                }

                item.Row = row + 1;
            }

            items.Sort((a, b) =>
            {
                int rowCompare = a.Row.CompareTo(b.Row);
                if (rowCompare != 0) return rowCompare;
                return a.Center.X.CompareTo(b.Center.X);
            });
        }

        private Parameter GetWritableRoomNumberParameter(Room room, string requestedParameterName, out string resolvedName)
        {
            resolvedName = null;

            if (!string.IsNullOrWhiteSpace(requestedParameterName))
            {
                Parameter requested = room.LookupParameter(requestedParameterName);
                if (requested != null && !requested.IsReadOnly && requested.StorageType == StorageType.String)
                {
                    resolvedName = requested.Definition?.Name ?? requestedParameterName;
                    return requested;
                }
            }

            Parameter builtIn = room.get_Parameter(BuiltInParameter.ROOM_NUMBER);
            if (builtIn != null && !builtIn.IsReadOnly && builtIn.StorageType == StorageType.String)
            {
                resolvedName = builtIn.Definition?.Name ?? "ROOM_NUMBER";
                return builtIn;
            }

            foreach (string candidateName in new[] { "編號", "Number" })
            {
                Parameter candidate = room.LookupParameter(candidateName);
                if (candidate != null && !candidate.IsReadOnly && candidate.StorageType == StorageType.String)
                {
                    resolvedName = candidate.Definition?.Name ?? candidateName;
                    return candidate;
                }
            }

            return null;
        }

        private List<object> FindExternalRoomNumberConflicts(Document doc, List<RoomNumberingItem> plannedItems)
        {
            HashSet<ElementId> plannedIds = new HashSet<ElementId>(plannedItems.Select(item => item.Room.Id));
            HashSet<string> proposedNumbers = new HashSet<string>(plannedItems.Select(item => item.NewNumber));

            return new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Rooms)
                .WhereElementIsNotElementType()
                .Cast<Room>()
                .Where(room => !plannedIds.Contains(room.Id))
                .Where(room => proposedNumbers.Contains(room.Number))
                .Select(room => new
                {
                    ElementId = room.Id.GetIdValue(),
                    Name = GetRoomNumberingRoomName(room),
                    Number = room.Number,
                    Level = doc.GetElement(room.LevelId)?.Name
                } as object)
                .ToList();
        }

        private class NumberSeed
        {
            public string Prefix { get; set; }
            public int StartIndex { get; set; }
            public int Width { get; set; }
        }

        private class RoomNumberingItem
        {
            public Room Room { get; set; }
            public int Sequence { get; set; }
            public int Row { get; set; }
            public long ElementId { get; set; }
            public string Name { get; set; }
            public bool HasName { get; set; }
            public string OldNumber { get; set; }
            public string NewNumber { get; set; }
            public XYZ Center { get; set; }
        }
    }
}
