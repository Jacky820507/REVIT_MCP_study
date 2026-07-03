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
        private object GetViewGridDetails(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType viewId = parameters["viewId"]?.Value<IdType>() ?? 0;
            View view = viewId > 0
                ? doc.GetElement(viewId.ToElementId()) as View
                : _uiApp.ActiveUIDocument.ActiveView;

            if (view == null)
                throw new Exception($"View not found: {viewId}");

            HashSet<string> gridFilter = ReadStringSet(parameters, "gridNames", "grids");
            List<Grid> grids = GetVisibleGridsInView(doc, view, gridFilter);

            return new
            {
                ViewId = view.Id.GetIdValue(),
                ViewName = view.Name,
                ViewType = view.ViewType.ToString(),
                Count = grids.Count,
                Grids = grids.Select(g => BuildViewGridDetail(g, view)).ToList()
            };
        }

        private object SyncGridExtentsBetweenViews(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            JArray pairs = (parameters["pairs"] ?? parameters["items"]) as JArray;
            if (pairs == null || pairs.Count == 0)
                throw new Exception("Please provide pairs/items with sourceViewId and targetViewId.");

            bool dryRun = parameters["dryRun"]?.Value<bool>() ?? false;
            bool copyCurves = parameters["copyCurves"]?.Value<bool>() ?? true;
            bool copyExtentTypes = parameters["copyExtentTypes"]?.Value<bool>() ?? true;
            bool copyBubbles = parameters["copyBubbles"]?.Value<bool>() ?? true;
            bool forceViewSpecific = parameters["forceViewSpecific"]?.Value<bool>() ?? false;
            HashSet<string> gridFilter = ReadStringSet(parameters, "gridNames", "grids");

            List<GridSyncPair> plans = new List<GridSyncPair>();
            foreach (JToken token in pairs)
            {
                IdType sourceViewId = token["sourceViewId"]?.Value<IdType>() ?? 0;
                IdType targetViewId = token["targetViewId"]?.Value<IdType>() ?? 0;

                View sourceView = doc.GetElement(sourceViewId.ToElementId()) as View;
                View targetView = doc.GetElement(targetViewId.ToElementId()) as View;

                if (sourceView == null)
                    throw new Exception($"Source view not found: {sourceViewId}");
                if (targetView == null)
                    throw new Exception($"Target view not found: {targetViewId}");

                plans.Add(new GridSyncPair
                {
                    SourceView = sourceView,
                    TargetView = targetView
                });
            }

            Func<List<object>> run = () =>
            {
                List<object> pairResults = new List<object>();
                foreach (GridSyncPair plan in plans)
                {
                    List<Grid> sourceGrids = GetVisibleGridsInView(doc, plan.SourceView, gridFilter);
                    List<object> gridResults = new List<object>();

                    foreach (Grid grid in sourceGrids)
                    {
                        gridResults.Add(SyncGridInViewPair(
                            grid,
                            plan.SourceView,
                            plan.TargetView,
                            dryRun,
                            copyCurves,
                            copyExtentTypes,
                            copyBubbles,
                            forceViewSpecific));
                    }

                    int appliedCount = gridResults.Count(r => (bool)(r.GetType().GetProperty("Applied")?.GetValue(r) ?? false));
                    int errorCount = gridResults.Count(r => r.GetType().GetProperty("Error")?.GetValue(r) != null);

                    pairResults.Add(new
                    {
                        SourceViewId = plan.SourceView.Id.GetIdValue(),
                        SourceViewName = plan.SourceView.Name,
                        TargetViewId = plan.TargetView.Id.GetIdValue(),
                        TargetViewName = plan.TargetView.Name,
                        GridCount = gridResults.Count,
                        AppliedCount = appliedCount,
                        ErrorCount = errorCount,
                        Grids = gridResults
                    });
                }

                return pairResults;
            };

            List<object> results;
            if (dryRun)
            {
                results = run();
            }
            else
            {
                using (Transaction trans = new Transaction(doc, "Sync grid extents between views"))
                {
                    trans.Start();
                    results = run();
                    trans.Commit();
                }
            }

            return new
            {
                DryRun = dryRun,
                CopyCurves = copyCurves,
                CopyExtentTypes = copyExtentTypes,
                CopyBubbles = copyBubbles,
                ForceViewSpecific = forceViewSpecific,
                PairCount = results.Count,
                Results = results
            };
        }

        private object SyncGridInViewPair(
            Grid grid,
            View sourceView,
            View targetView,
            bool dryRun,
            bool copyCurves,
            bool copyExtentTypes,
            bool copyBubbles,
            bool forceViewSpecific)
        {
            List<string> warnings = new List<string>();

            try
            {
                DatumExtentType sourceEnd0 = GetDatumExtentTypeSafe(grid, DatumEnds.End0, sourceView, warnings, "source");
                DatumExtentType sourceEnd1 = GetDatumExtentTypeSafe(grid, DatumEnds.End1, sourceView, warnings, "source");
                DatumExtentType targetBeforeEnd0 = GetDatumExtentTypeSafe(grid, DatumEnds.End0, targetView, warnings, "target");
                DatumExtentType targetBeforeEnd1 = GetDatumExtentTypeSafe(grid, DatumEnds.End1, targetView, warnings, "target");

                bool sourceUsesViewSpecific =
                    forceViewSpecific ||
                    sourceEnd0 == DatumExtentType.ViewSpecific ||
                    sourceEnd1 == DatumExtentType.ViewSpecific;

                DatumExtentType sourceCurveMode = sourceUsesViewSpecific
                    ? DatumExtentType.ViewSpecific
                    : DatumExtentType.Model;

                Curve sourceCurve = GetFirstDatumCurve(grid, sourceView, sourceCurveMode, warnings, "source");
                if (sourceCurve == null && sourceCurveMode == DatumExtentType.ViewSpecific)
                {
                    sourceCurve = GetFirstDatumCurve(grid, sourceView, DatumExtentType.Model, warnings, "source fallback");
                }

                Curve targetBeforeCurve = GetFirstDatumCurve(grid, targetView, sourceCurveMode, warnings, "target before");
                bool? sourceBubbleEnd0 = GetBubbleVisibleSafe(grid, DatumEnds.End0, sourceView, warnings, "source");
                bool? sourceBubbleEnd1 = GetBubbleVisibleSafe(grid, DatumEnds.End1, sourceView, warnings, "source");

                if (!dryRun)
                {
                    if (copyCurves && sourceUsesViewSpecific && sourceCurve != null)
                    {
                        SetDatumExtentTypeSafe(grid, DatumEnds.End0, targetView, DatumExtentType.ViewSpecific, warnings);
                        SetDatumExtentTypeSafe(grid, DatumEnds.End1, targetView, DatumExtentType.ViewSpecific, warnings);

                        Curve targetReferenceCurve =
                            GetFirstDatumCurve(grid, targetView, DatumExtentType.ViewSpecific, warnings, "target reference") ??
                            GetFirstDatumCurve(grid, targetView, DatumExtentType.Model, warnings, "target reference");
                        Curve targetCurve = ProjectDatumCurveToTargetDatumPlane(sourceCurve, targetReferenceCurve);
                        grid.SetCurveInView(DatumExtentType.ViewSpecific, targetView, targetCurve);
                    }

                    if (copyExtentTypes)
                    {
                        DatumExtentType finalEnd0 = forceViewSpecific ? DatumExtentType.ViewSpecific : sourceEnd0;
                        DatumExtentType finalEnd1 = forceViewSpecific ? DatumExtentType.ViewSpecific : sourceEnd1;
                        SetDatumExtentTypeSafe(grid, DatumEnds.End0, targetView, finalEnd0, warnings);
                        SetDatumExtentTypeSafe(grid, DatumEnds.End1, targetView, finalEnd1, warnings);
                    }

                    if (copyBubbles)
                    {
                        SetBubbleVisibleSafe(grid, DatumEnds.End0, targetView, sourceBubbleEnd0, warnings);
                        SetBubbleVisibleSafe(grid, DatumEnds.End1, targetView, sourceBubbleEnd1, warnings);
                    }
                }

                DatumExtentType targetAfterEnd0 = dryRun
                    ? (forceViewSpecific ? DatumExtentType.ViewSpecific : sourceEnd0)
                    : GetDatumExtentTypeSafe(grid, DatumEnds.End0, targetView, warnings, "target after");
                DatumExtentType targetAfterEnd1 = dryRun
                    ? (forceViewSpecific ? DatumExtentType.ViewSpecific : sourceEnd1)
                    : GetDatumExtentTypeSafe(grid, DatumEnds.End1, targetView, warnings, "target after");

                DatumExtentType afterCurveMode =
                    targetAfterEnd0 == DatumExtentType.ViewSpecific || targetAfterEnd1 == DatumExtentType.ViewSpecific
                        ? DatumExtentType.ViewSpecific
                        : DatumExtentType.Model;
                Curve targetAfterCurve = dryRun
                    ? (sourceCurve != null && sourceUsesViewSpecific ? ProjectDatumCurveToTargetDatumPlane(sourceCurve, targetBeforeCurve) : targetBeforeCurve)
                    : GetFirstDatumCurve(grid, targetView, afterCurveMode, warnings, "target after");

                return new
                {
                    GridId = grid.Id.GetIdValue(),
                    GridName = grid.Name,
                    Applied = !dryRun,
                    DryRun = dryRun,
                    SourceEnd0 = sourceEnd0.ToString(),
                    SourceEnd1 = sourceEnd1.ToString(),
                    TargetBeforeEnd0 = targetBeforeEnd0.ToString(),
                    TargetBeforeEnd1 = targetBeforeEnd1.ToString(),
                    TargetAfterEnd0 = targetAfterEnd0.ToString(),
                    TargetAfterEnd1 = targetAfterEnd1.ToString(),
                    SourceBubbleEnd0 = sourceBubbleEnd0,
                    SourceBubbleEnd1 = sourceBubbleEnd1,
                    SourceCurveMode = sourceCurveMode.ToString(),
                    SourceCurve = SerializeDatumCurve(sourceCurve),
                    TargetBeforeCurve = SerializeDatumCurve(targetBeforeCurve),
                    TargetAfterCurve = SerializeDatumCurve(targetAfterCurve),
                    Warnings = warnings
                };
            }
            catch (Exception ex)
            {
                return new
                {
                    GridId = grid.Id.GetIdValue(),
                    GridName = grid.Name,
                    Applied = false,
                    DryRun = dryRun,
                    Error = ex.Message,
                    Warnings = warnings
                };
            }
        }

        private List<Grid> GetVisibleGridsInView(Document doc, View view, HashSet<string> gridFilter)
        {
            IEnumerable<Grid> grids = new FilteredElementCollector(doc, view.Id)
                .OfClass(typeof(Grid))
                .Cast<Grid>();

            if (gridFilter != null && gridFilter.Count > 0)
            {
                grids = grids.Where(g => gridFilter.Contains(g.Name));
            }

            return grids.OrderBy(g => g.Name, StringComparer.OrdinalIgnoreCase).ToList();
        }

        private object BuildViewGridDetail(Grid grid, View view)
        {
            List<string> warnings = new List<string>();
            DatumExtentType end0 = GetDatumExtentTypeSafe(grid, DatumEnds.End0, view, warnings, "view");
            DatumExtentType end1 = GetDatumExtentTypeSafe(grid, DatumEnds.End1, view, warnings, "view");
            DatumExtentType curveMode =
                end0 == DatumExtentType.ViewSpecific || end1 == DatumExtentType.ViewSpecific
                    ? DatumExtentType.ViewSpecific
                    : DatumExtentType.Model;

            return new
            {
                GridId = grid.Id.GetIdValue(),
                GridName = grid.Name,
                End0ExtentType = end0.ToString(),
                End1ExtentType = end1.ToString(),
                BubbleEnd0 = GetBubbleVisibleSafe(grid, DatumEnds.End0, view, warnings, "view"),
                BubbleEnd1 = GetBubbleVisibleSafe(grid, DatumEnds.End1, view, warnings, "view"),
                CurveMode = curveMode.ToString(),
                Curve = SerializeDatumCurve(GetFirstDatumCurve(grid, view, curveMode, warnings, "view")),
                Warnings = warnings
            };
        }

        private HashSet<string> ReadStringSet(JObject parameters, params string[] propertyNames)
        {
            foreach (string propertyName in propertyNames)
            {
                JArray array = parameters[propertyName] as JArray;
                if (array == null) continue;

                return new HashSet<string>(
                    array.Select(v => v.Value<string>())
                        .Where(v => !string.IsNullOrWhiteSpace(v)),
                    StringComparer.OrdinalIgnoreCase);
            }

            return new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        }

        private DatumExtentType GetDatumExtentTypeSafe(Grid grid, DatumEnds end, View view, List<string> warnings, string label)
        {
            try
            {
                return grid.GetDatumExtentTypeInView(end, view);
            }
            catch (Exception ex)
            {
                warnings.Add($"{label} {grid.Name} {end} extent type read failed: {ex.Message}");
                return DatumExtentType.Model;
            }
        }

        private void SetDatumExtentTypeSafe(Grid grid, DatumEnds end, View view, DatumExtentType type, List<string> warnings)
        {
            try
            {
                grid.SetDatumExtentType(end, view, type);
            }
            catch (Exception ex)
            {
                warnings.Add($"Set {grid.Name} {end} extent type failed: {ex.Message}");
            }
        }

        private Curve GetFirstDatumCurve(Grid grid, View view, DatumExtentType type, List<string> warnings, string label)
        {
            try
            {
                IList<Curve> curves = grid.GetCurvesInView(type, view);
                return curves?.FirstOrDefault();
            }
            catch (Exception ex)
            {
                warnings.Add($"{label} {grid.Name} {type} curve read failed: {ex.Message}");
                return null;
            }
        }

        private bool? GetBubbleVisibleSafe(Grid grid, DatumEnds end, View view, List<string> warnings, string label)
        {
            try
            {
                return grid.IsBubbleVisibleInView(end, view);
            }
            catch (Exception ex)
            {
                warnings.Add($"{label} {grid.Name} {end} bubble read failed: {ex.Message}");
                return null;
            }
        }

        private void SetBubbleVisibleSafe(Grid grid, DatumEnds end, View view, bool? visible, List<string> warnings)
        {
            if (!visible.HasValue)
                return;

            try
            {
                if (visible.Value)
                    grid.ShowBubbleInView(end, view);
                else
                    grid.HideBubbleInView(end, view);
            }
            catch (Exception ex)
            {
                warnings.Add($"Set {grid.Name} {end} bubble failed: {ex.Message}");
            }
        }

        private Curve ProjectDatumCurveToTargetDatumPlane(Curve curve, Curve targetReferenceCurve)
        {
            if (curve == null)
                return null;

            double targetZ = targetReferenceCurve?.GetEndPoint(0).Z ?? curve.GetEndPoint(0).Z;
            XYZ p0 = WithZ(curve.GetEndPoint(0), targetZ);
            XYZ p1 = WithZ(curve.GetEndPoint(1), targetZ);

            if (curve is Line)
            {
                return Line.CreateBound(p0, p1);
            }

            if (curve is Arc)
            {
                XYZ mid = WithZ(curve.Evaluate(0.5, true), targetZ);
                return Arc.Create(p0, p1, mid);
            }

            double dz = targetZ - curve.GetEndPoint(0).Z;
            return curve.CreateTransformed(Transform.CreateTranslation(new XYZ(0, 0, dz)));
        }

        private XYZ WithZ(XYZ point, double z)
        {
            return new XYZ(point.X, point.Y, z);
        }

        private object SerializeDatumCurve(Curve curve)
        {
            if (curve == null)
                return null;

            XYZ start = curve.GetEndPoint(0);
            XYZ end = curve.GetEndPoint(1);
            XYZ mid = curve.Evaluate(0.5, true);

            return new
            {
                Type = curve.GetType().Name,
                Start = SerializeXyz(start),
                End = SerializeXyz(end),
                Mid = SerializeXyz(mid),
                LengthMm = curve.Length * 304.8
            };
        }

        private object SerializeXyz(XYZ point)
        {
            if (point == null)
                return null;

            return new
            {
                x = point.X * 304.8,
                y = point.Y * 304.8,
                z = point.Z * 304.8
            };
        }

        private class GridSyncPair
        {
            public View SourceView { get; set; }
            public View TargetView { get; set; }
        }
    }
}
