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
        private object QueryScheduleData(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            IdType? scheduleId = parameters["scheduleId"]?.Value<IdType>();
            string scheduleName = parameters["scheduleName"]?.Value<string>();
            int maxRows = parameters["maxRows"]?.Value<int>() ?? 500;
            bool includeEmptyRows = parameters["includeEmptyRows"]?.Value<bool>() ?? false;

            if (!scheduleId.HasValue && string.IsNullOrWhiteSpace(scheduleName))
            {
                throw new ArgumentException("query_schedule_data requires scheduleId or scheduleName.");
            }

            if (maxRows <= 0)
            {
                maxRows = 500;
            }

            ViewSchedule schedule = ResolveViewSchedule(doc, scheduleId, scheduleName);
            TableSectionData body = schedule.GetTableData().GetSectionData(SectionType.Body);

            int totalBodyRows = body.NumberOfRows;
            int totalBodyColumns = body.NumberOfColumns;

            var fields = GetScheduleFields(doc, schedule);
            var columnNames = GetScheduleColumnNames(fields, totalBodyColumns);
            var rows = new List<Dictionary<string, string>>();
            var rawRows = new List<List<string>>();
            int matchingRowCount = 0;

            for (int rowIndex = 0; rowIndex < totalBodyRows; rowIndex++)
            {
                var rawRow = new List<string>();
                var row = new Dictionary<string, string>();
                bool hasValue = false;

                for (int columnIndex = 0; columnIndex < totalBodyColumns; columnIndex++)
                {
                    string cellText = GetScheduleCellText(schedule, rowIndex, columnIndex);
                    if (!string.IsNullOrWhiteSpace(cellText))
                    {
                        hasValue = true;
                    }

                    rawRow.Add(cellText);
                    row[columnNames[columnIndex]] = cellText;
                }

                if (!includeEmptyRows && !hasValue)
                {
                    continue;
                }

                matchingRowCount++;
                if (rows.Count >= maxRows)
                {
                    continue;
                }

                rawRows.Add(rawRow);
                rows.Add(row);
            }

            return new
            {
                ScheduleId = schedule.Id.GetIdValue(),
                ScheduleName = schedule.Name,
                Category = GetScheduleCategoryName(doc, schedule),
                TotalBodyRows = totalBodyRows,
                TotalBodyColumns = totalBodyColumns,
                MatchingRows = matchingRowCount,
                ReturnedRows = rows.Count,
                MaxRows = maxRows,
                Truncated = matchingRowCount > rows.Count,
                Columns = fields,
                Rows = rows,
                RawRows = rawRows
            };
        }

        private ViewSchedule ResolveViewSchedule(Document doc, IdType? scheduleId, string scheduleName)
        {
            if (scheduleId.HasValue)
            {
                ViewSchedule schedule = doc.GetElement(scheduleId.Value.ToElementId()) as ViewSchedule;
                if (schedule == null || schedule.IsTitleblockRevisionSchedule)
                {
                    throw new ArgumentException($"Schedule not found: {scheduleId.Value}");
                }

                return schedule;
            }

            var schedules = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSchedule))
                .Cast<ViewSchedule>()
                .Where(s => !s.IsTitleblockRevisionSchedule)
                .ToList();

            ViewSchedule exact = schedules.FirstOrDefault(s =>
                s.Name.Equals(scheduleName, StringComparison.OrdinalIgnoreCase));
            if (exact != null)
            {
                return exact;
            }

            var matches = schedules
                .Where(s => s.Name.IndexOf(scheduleName, StringComparison.OrdinalIgnoreCase) >= 0)
                .ToList();

            if (matches.Count == 1)
            {
                return matches[0];
            }

            if (matches.Count > 1)
            {
                throw new ArgumentException(
                    $"Multiple schedules match '{scheduleName}': {string.Join(", ", matches.Select(s => $"{s.Name} ({s.Id.GetIdValue()})"))}");
            }

            throw new ArgumentException($"Schedule not found: {scheduleName}");
        }

        private string GetScheduleCategoryName(Document doc, ViewSchedule schedule)
        {
            ElementId categoryId = schedule.Definition.CategoryId;
            if (categoryId == ElementId.InvalidElementId)
            {
                return null;
            }

            return Category.GetCategory(doc, categoryId)?.Name;
        }

        private List<ScheduleColumnInfo> GetScheduleFields(Document doc, ViewSchedule schedule)
        {
            var fields = new List<ScheduleColumnInfo>();
            ScheduleDefinition definition = schedule.Definition;

            for (int index = 0; index < definition.GetFieldCount(); index++)
            {
                ScheduleField field = definition.GetField(index);
                string fieldName = GetScheduleFieldName(doc, field);
                string heading = string.IsNullOrWhiteSpace(field.ColumnHeading) ? fieldName : field.ColumnHeading;

                fields.Add(new ScheduleColumnInfo
                {
                    Index = index,
                    Name = fieldName,
                    Heading = heading,
                    IsHidden = field.IsHidden
                });
            }

            return fields;
        }

        private List<string> GetScheduleColumnNames(List<ScheduleColumnInfo> fields, int columnCount)
        {
            var names = new List<string>();
            var usedNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            foreach (ScheduleColumnInfo field in fields)
            {
                if (field.IsHidden)
                {
                    continue;
                }

                string baseName = string.IsNullOrWhiteSpace(field.Heading) ? field.Name : field.Heading;
                names.Add(MakeUniqueColumnName(baseName, usedNames));

                if (names.Count == columnCount)
                {
                    break;
                }
            }

            while (names.Count < columnCount)
            {
                names.Add(MakeUniqueColumnName($"Column{names.Count + 1}", usedNames));
            }

            return names;
        }

        private string MakeUniqueColumnName(string baseName, HashSet<string> usedNames)
        {
            string candidate = string.IsNullOrWhiteSpace(baseName) ? "Column" : baseName.Trim();
            string uniqueName = candidate;
            int suffix = 2;

            while (usedNames.Contains(uniqueName))
            {
                uniqueName = $"{candidate}_{suffix}";
                suffix++;
            }

            usedNames.Add(uniqueName);
            return uniqueName;
        }

        private string GetScheduleFieldName(Document doc, ScheduleField field)
        {
            try
            {
                return field.GetName();
            }
            catch
            {
                try
                {
                    SchedulableField schedulableField = field.GetSchedulableField();
                    return schedulableField?.GetName(doc) ?? field.ColumnHeading ?? "";
                }
                catch
                {
                    return field.ColumnHeading ?? "";
                }
            }
        }

        private string GetScheduleCellText(ViewSchedule schedule, int rowIndex, int columnIndex)
        {
            try
            {
                return schedule.GetCellText(SectionType.Body, rowIndex, columnIndex) ?? "";
            }
            catch
            {
                return "";
            }
        }

        private class ScheduleColumnInfo
        {
            public int Index { get; set; }
            public string Name { get; set; }
            public string Heading { get; set; }
            public bool IsHidden { get; set; }
        }
    }
}
