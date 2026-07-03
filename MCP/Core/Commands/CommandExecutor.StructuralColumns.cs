using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Structure;
using Newtonsoft.Json.Linq;

#nullable disable

#if REVIT2025_OR_GREATER
using IdType = System.Int64;
#else
using IdType = System.Int32;
#endif

namespace RevitMCP.Core
{
    public partial class CommandExecutor
    {
        private object AlignColumnsTopToFloorBottom(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            bool apply = parameters["apply"]?.Value<bool>() ?? false;
            bool dryRun = parameters["dryRun"]?.Value<bool>() ?? !apply;
            double toleranceMm = Math.Max(0, parameters["toleranceMm"]?.Value<double>() ?? 5.0);
            double maxDeltaMm = Math.Max(1, parameters["maxDeltaMm"]?.Value<double>() ?? 6000.0);
            double maxSearchDistanceMm = Math.Max(1, parameters["maxSearchDistanceMm"]?.Value<double>() ?? 6000.0);
            int maxCount = Math.Max(1, parameters["maxCount"]?.Value<int>() ?? 500);
            bool setTopAttachment = parameters["setTopAttachment"]?.Value<bool>() ?? true;
            bool postGeometryCorrection = parameters["postGeometryCorrection"]?.Value<bool>() ?? true;
            string sourceTagPrefix = parameters["sourceTagPrefix"]?.Value<string>() ?? "IFC_STRUCT_SYNC";
            HashSet<IdType> floorIdFilter = ReadIdSet(parameters["floorIds"] as JArray);

            List<Element> columns = CollectTargetStructuralColumns(
                doc,
                parameters["columnIds"] as JArray,
                sourceTagPrefix,
                maxCount);
            View3D detectorView = GetDetector3DView(doc);
            List<Level> levels = new FilteredElementCollector(doc)
                .OfClass(typeof(Level))
                .Cast<Level>()
                .OrderBy(l => l.Elevation)
                .ToList();

            var plans = columns
                .Select(column => BuildColumnTopAlignmentPlan(doc, detectorView, levels, column, floorIdFilter, maxSearchDistanceMm))
                .ToList();

            int adjustedCount = 0;
            var failures = new List<object>();

            if (!dryRun && apply)
            {
                using (Transaction trans = new Transaction(doc, "Align columns top to floor bottom"))
                {
                    trans.Start();
                    FailureHandlingOptions failureOptions = trans.GetFailureHandlingOptions();
                    failureOptions.SetFailuresPreprocessor(new DismissWarningsPreprocessor());
                    trans.SetFailureHandlingOptions(failureOptions);

                    foreach (ColumnTopAlignmentPlan plan in plans.Where(p => p.CanAlign))
                    {
                        try
                        {
                            Element column = doc.GetElement(plan.ColumnId.ToElementId());
                            if (column == null)
                            {
                                plan.Applied = false;
                                plan.SkipReason = "column-not-found";
                                continue;
                            }

                            ApplyColumnTopReference(doc, levels, column, plan);
                            plan.TopAttachmentSet = setTopAttachment && TrySetColumnTopAttachment(column, 0);
                            doc.Regenerate();

                            if (postGeometryCorrection)
                            {
                                ApplyColumnTopGeometryCorrection(column, plan, toleranceMm, maxDeltaMm);
                                doc.Regenerate();
                            }

                            RefreshColumnTopResidual(column, plan);
                            plan.Applied = true;
                            adjustedCount++;
                        }
                        catch (Exception ex)
                        {
                            plan.Applied = false;
                            plan.SkipReason = ex.Message;
                            failures.Add(new { plan.ColumnId, Error = ex.Message });
                        }
                    }

                    trans.Commit();
                }
            }

            return new
            {
                Success = true,
                DryRun = dryRun,
                ApplyRequested = apply,
                SetTopAttachment = setTopAttachment,
                PostGeometryCorrection = postGeometryCorrection,
                SourceTagPrefix = sourceTagPrefix,
                Count = columns.Count,
                Planned = plans.Count(p => p.CanAlign),
                Skipped = plans.Count(p => !p.CanAlign),
                Adjusted = adjustedCount,
                Failed = failures.Count,
                TargetFloors = plans
                    .Where(p => p.CanAlign)
                    .GroupBy(p => new { p.FloorId, p.FloorName })
                    .OrderBy(g => g.Key.FloorName)
                    .Select(g => new
                    {
                        FloorId = g.Key.FloorId,
                        FloorName = g.Key.FloorName,
                        Count = g.Count()
                    })
                    .ToList(),
                Samples = plans.Take(25).Select(p => p.ToResult()).ToList(),
                Failures = failures
            };
        }

        private List<Element> CollectTargetStructuralColumns(Document doc, JArray columnIds, string sourceTagPrefix, int maxCount)
        {
            IEnumerable<Element> source;
            if (columnIds != null && columnIds.Count > 0)
            {
                source = columnIds
                    .Select(id => doc.GetElement(id.Value<IdType>().ToElementId()))
                    .Where(e => e != null);
            }
            else
            {
                source = new FilteredElementCollector(doc)
                    .OfCategory(BuiltInCategory.OST_StructuralColumns)
                    .WhereElementIsNotElementType()
                    .ToElements();
            }

            if (!string.IsNullOrWhiteSpace(sourceTagPrefix) && (columnIds == null || columnIds.Count == 0))
            {
                source = source.Where(e =>
                {
                    string comments = ReadAnyParameterString(e, doc, "備註", "Comments");
                    return comments.IndexOf(sourceTagPrefix, StringComparison.OrdinalIgnoreCase) >= 0;
                });
            }

            return source.Take(maxCount).ToList();
        }

        private ColumnTopAlignmentPlan BuildColumnTopAlignmentPlan(
            Document doc,
            View3D detectorView,
            List<Level> levels,
            Element column,
            HashSet<IdType> floorIdFilter,
            double maxSearchDistanceMm)
        {
            ColumnTopAlignmentPlan plan = new ColumnTopAlignmentPlan
            {
                ColumnId = column.Id.GetIdValue(),
                TypeName = column.Name ?? "",
                CanAlign = false
            };

            double? topZ = GetHighestElementZFeet(column);
            List<XYZ> samplePoints = GetElementPlanSamplePoints(column);
            if (!topZ.HasValue || samplePoints.Count == 0)
            {
                plan.SkipReason = "no-column-geometry";
                return plan;
            }

            plan.OriginalTopZFeet = topZ.Value;
            FloorHitInfo target = samplePoints
                .SelectMany(samplePoint => CollectFloorBottomHitsAtPoint(
                    doc,
                    detectorView,
                    new XYZ(samplePoint.X, samplePoint.Y, topZ.Value),
                    topZ.Value,
                    maxSearchDistanceMm,
                    floorIdFilter))
                .Where(hit => hit != null && hit.HasHit)
                .OrderBy(hit => Math.Abs(hit.BottomZFeet - topZ.Value))
                .FirstOrDefault();

            if (target == null || !target.HasHit)
            {
                plan.SkipReason = "no-floor-bottom-hit";
                return plan;
            }

            plan.CanAlign = true;
            plan.FloorId = target.FloorId;
            plan.FloorName = target.FloorName;
            plan.TargetBottomZFeet = target.BottomZFeet;
            plan.TargetLevel = FindNearestLevelAtOrBelow(levels, target.BottomZFeet);
            plan.TargetOffsetFeet = target.BottomZFeet - plan.TargetLevel.Elevation;
            plan.InitialResidualFeet = topZ.Value - target.BottomZFeet;
            plan.Message = target.Message;
            return plan;
        }

        private void ApplyColumnTopReference(Document doc, List<Level> levels, Element column, ColumnTopAlignmentPlan plan)
        {
            Level targetLevel = plan.TargetLevel ?? FindNearestLevelAtOrBelow(levels, plan.TargetBottomZFeet);
            plan.TargetLevel = targetLevel;
            plan.TargetOffsetFeet = plan.TargetBottomZFeet - targetLevel.Elevation;

            TrySetElementIdParameter(column, targetLevel.Id, BuiltInParameter.FAMILY_TOP_LEVEL_PARAM);
            TrySetDoubleBuiltInParameter(column, plan.TargetOffsetFeet, BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM);
        }

        private void ApplyColumnTopGeometryCorrection(Element column, ColumnTopAlignmentPlan plan, double toleranceMm, double maxDeltaMm)
        {
            double? topZ = GetHighestElementZFeet(column);
            if (!topZ.HasValue)
                return;

            double residualFeet = topZ.Value - plan.TargetBottomZFeet;
            double residualMm = residualFeet * StructuralFramingFeetToMm;
            plan.PreCorrectionResidualFeet = residualFeet;
            if (Math.Abs(residualMm) <= toleranceMm)
                return;

            if (Math.Abs(residualMm) > maxDeltaMm)
            {
                plan.CorrectionSkippedReason = $"geometry-residual>{maxDeltaMm:0.##}mm";
                return;
            }

            double correctionFeet = -residualFeet;
            Parameter attachmentOffset = column.get_Parameter(BuiltInParameter.COLUMN_TOP_ATTACHMENT_OFFSET_PARAM);
            if (attachmentOffset != null && !attachmentOffset.IsReadOnly && attachmentOffset.StorageType == StorageType.Double)
            {
                attachmentOffset.Set(attachmentOffset.AsDouble() + correctionFeet);
                plan.CorrectionParameter = "COLUMN_TOP_ATTACHMENT_OFFSET_PARAM";
            }
            else
            {
                Parameter topOffset = column.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM);
                if (topOffset == null || topOffset.IsReadOnly || topOffset.StorageType != StorageType.Double)
                {
                    plan.CorrectionSkippedReason = "top-offset-readonly";
                    return;
                }

                topOffset.Set(topOffset.AsDouble() + correctionFeet);
                plan.CorrectionParameter = "FAMILY_TOP_LEVEL_OFFSET_PARAM";
            }

            plan.GeometryCorrectionFeet = correctionFeet;
        }

        private void RefreshColumnTopResidual(Element column, ColumnTopAlignmentPlan plan)
        {
            double? finalTop = GetHighestElementZFeet(column);
            if (finalTop.HasValue)
                plan.FinalResidualFeet = finalTop.Value - plan.TargetBottomZFeet;
        }

        private bool TrySetColumnTopAttachment(Element column, double offsetFeet)
        {
            bool changed = false;
            Parameter attached = column.get_Parameter(BuiltInParameter.COLUMN_TOP_ATTACHED_PARAM);
            if (attached != null && !attached.IsReadOnly && attached.StorageType == StorageType.Integer)
            {
                attached.Set(1);
                changed = true;
            }

            Parameter offset = column.get_Parameter(BuiltInParameter.COLUMN_TOP_ATTACHMENT_OFFSET_PARAM);
            if (offset != null && !offset.IsReadOnly && offset.StorageType == StorageType.Double)
            {
                offset.Set(offsetFeet);
                changed = true;
            }

            return changed;
        }

        private double? GetHighestElementZFeet(Element element)
        {
            var vertices = new List<XYZ>();
            try
            {
                Options options = new Options
                {
                    DetailLevel = ViewDetailLevel.Fine,
                    IncludeNonVisibleObjects = false
                };
                CollectGeometryVertices(element.get_Geometry(options), Transform.Identity, vertices);
            }
            catch
            {
                vertices.Clear();
            }

            if (vertices.Count > 0)
                return vertices.Max(v => v.Z);

            BoundingBoxXYZ bbox = element.get_BoundingBox(null);
            return bbox?.Max.Z;
        }

        private List<XYZ> GetElementPlanSamplePoints(Element element)
        {
            var samples = new List<XYZ>();
            BoundingBoxXYZ bbox = element.get_BoundingBox(null);
            if (bbox != null)
            {
                double centerX = (bbox.Min.X + bbox.Max.X) * 0.5;
                double centerY = (bbox.Min.Y + bbox.Max.Y) * 0.5;
                double halfX = Math.Max(0, (bbox.Max.X - bbox.Min.X) * 0.5);
                double halfY = Math.Max(0, (bbox.Max.Y - bbox.Min.Y) * 0.5);
                double offsetX = halfX * 0.8;
                double offsetY = halfY * 0.8;

                AddUniquePlanSample(samples, centerX, centerY);

                if (offsetX > 1e-6)
                {
                    AddUniquePlanSample(samples, centerX - offsetX, centerY);
                    AddUniquePlanSample(samples, centerX + offsetX, centerY);
                }

                if (offsetY > 1e-6)
                {
                    AddUniquePlanSample(samples, centerX, centerY - offsetY);
                    AddUniquePlanSample(samples, centerX, centerY + offsetY);
                }

                if (offsetX > 1e-6 && offsetY > 1e-6)
                {
                    AddUniquePlanSample(samples, centerX - offsetX, centerY - offsetY);
                    AddUniquePlanSample(samples, centerX - offsetX, centerY + offsetY);
                    AddUniquePlanSample(samples, centerX + offsetX, centerY - offsetY);
                    AddUniquePlanSample(samples, centerX + offsetX, centerY + offsetY);
                }

                return samples;
            }

            LocationPoint point = element.Location as LocationPoint;
            if (point != null)
                AddUniquePlanSample(samples, point.Point.X, point.Point.Y);

            return samples;
        }

        private void AddUniquePlanSample(List<XYZ> samples, double x, double y)
        {
            if (samples.Any(p => Math.Abs(p.X - x) < 1e-6 && Math.Abs(p.Y - y) < 1e-6))
                return;

            samples.Add(new XYZ(x, y, 0));
        }

        private class ColumnTopAlignmentPlan
        {
            public IdType ColumnId { get; set; }
            public string TypeName { get; set; }
            public bool CanAlign { get; set; }
            public string SkipReason { get; set; }
            public IdType FloorId { get; set; }
            public string FloorName { get; set; }
            public double OriginalTopZFeet { get; set; }
            public double TargetBottomZFeet { get; set; }
            public Level TargetLevel { get; set; }
            public double TargetOffsetFeet { get; set; }
            public double InitialResidualFeet { get; set; }
            public double? PreCorrectionResidualFeet { get; set; }
            public double? FinalResidualFeet { get; set; }
            public double GeometryCorrectionFeet { get; set; }
            public bool Applied { get; set; }
            public bool TopAttachmentSet { get; set; }
            public string CorrectionParameter { get; set; }
            public string CorrectionSkippedReason { get; set; }
            public string Message { get; set; }

            public object ToResult()
            {
                return new
                {
                    ColumnId,
                    TypeName,
                    CanAlign,
                    SkipReason,
                    FloorId = CanAlign ? (object)FloorId : null,
                    FloorName,
                    OriginalTopZMm = CanAlign ? (object)Math.Round(OriginalTopZFeet * StructuralFramingFeetToMm, 2) : null,
                    TargetBottomZMm = CanAlign ? (object)Math.Round(TargetBottomZFeet * StructuralFramingFeetToMm, 2) : null,
                    TargetLevel = TargetLevel?.Name,
                    TargetOffsetMm = CanAlign ? (object)Math.Round(TargetOffsetFeet * StructuralFramingFeetToMm, 2) : null,
                    InitialResidualMm = CanAlign ? (object)Math.Round(InitialResidualFeet * StructuralFramingFeetToMm, 2) : null,
                    PreCorrectionResidualMm = PreCorrectionResidualFeet.HasValue ? (object)Math.Round(PreCorrectionResidualFeet.Value * StructuralFramingFeetToMm, 2) : null,
                    FinalResidualMm = FinalResidualFeet.HasValue ? (object)Math.Round(FinalResidualFeet.Value * StructuralFramingFeetToMm, 2) : null,
                    GeometryCorrectionMm = Math.Abs(GeometryCorrectionFeet) > 1e-9 ? (object)Math.Round(GeometryCorrectionFeet * StructuralFramingFeetToMm, 2) : null,
                    Applied,
                    TopAttachmentSet,
                    CorrectionParameter,
                    CorrectionSkippedReason,
                    Message
                };
            }
        }
    }
}
