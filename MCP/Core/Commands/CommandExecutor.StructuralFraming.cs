using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Structure;
using Autodesk.Revit.UI;
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
        private const double StructuralFramingFeetToMm = 304.8;
        private const double StructuralFramingMmToFeet = 1.0 / 304.8;

        private object AlignBeamsTopToFloorBottom(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            bool apply = parameters["apply"]?.Value<bool>() ?? false;
            bool dryRun = parameters["dryRun"]?.Value<bool>() ?? !apply;
            double toleranceMm = parameters["toleranceMm"]?.Value<double>() ?? 5.0;
            double maxDeltaMm = parameters["maxDeltaMm"]?.Value<double>() ?? 1000.0;
            double maxSearchDistanceMm = parameters["maxSearchDistanceMm"]?.Value<double>() ?? 3000.0;
            double endSampleDistanceMm = parameters["endSampleDistanceMm"]?.Value<double>() ?? 300.0;
            int beamSampleCount = Math.Max(3, Math.Min(25, parameters["beamSampleCount"]?.Value<int>() ?? 9));
            int maxCount = parameters["maxCount"]?.Value<int>() ?? 500;
            bool selectedOnly = parameters["selectedOnly"]?.Value<bool>() ?? false;
            bool requireBothEnds = parameters["requireBothEnds"]?.Value<bool>() ?? true;
            bool preserveVerticalStacks = parameters["preserveVerticalStacks"]?.Value<bool>() ?? false;
            string floorSelectionMode = parameters["floorSelectionMode"]?.Value<string>() ?? "auto_by_beam";
            double slopeDetectionToleranceMm = parameters["slopeDetectionToleranceMm"]?.Value<double>() ?? 20.0;
            bool alignWhenTopAboveFloorBottom = parameters["alignWhenTopAboveFloorBottom"]?.Value<bool>() ?? true;
            bool disallowJoinsBeforeAlign = parameters["disallowJoinsBeforeAlign"]?.Value<bool>() ?? true;
            bool postAlignGeometryCorrection = parameters["postAlignGeometryCorrection"]?.Value<bool>() ?? true;
            double maxGeometryCorrectionMm = parameters["maxGeometryCorrectionMm"]?.Value<double>() ?? maxDeltaMm;
            string levelName = parameters["levelName"]?.Value<string>();
            IdType? viewId = parameters["viewId"]?.Value<IdType>();

            List<string> startParameterNames = GetParameterNameList(
                parameters["startOffsetParameterNames"] as JArray,
                "起始樓層偏移",
                "起點樓層偏移",
                "起始樓層偏移",
                "起點樓層偏移",
                "Start Level Offset");

            List<string> endParameterNames = GetParameterNameList(
                parameters["endOffsetParameterNames"] as JArray,
                "結束樓層偏移",
                "終點樓層偏移",
                "結束樓層偏移",
                "終點樓層偏移",
                "End Level Offset");

            HashSet<IdType> floorIdFilter = ReadIdSet(parameters["floorIds"] as JArray);
            List<Element> beams = CollectTargetBeams(doc, parameters["beamIds"] as JArray, selectedOnly, viewId, levelName, maxCount);
            View3D detectorView = GetDetector3DView(doc);

            var plans = new List<BeamAlignmentPlan>();
            var skipped = new List<object>();
            var geometryCorrections = new List<object>();
            BeamJoinDisallowResult joinDisallowResult = new BeamJoinDisallowResult();
            int adjustedCount = 0;

            if (!dryRun && apply)
            {
                using (Transaction trans = new Transaction(doc, "Align beams top to floor bottom"))
                {
                    trans.Start();
                    FailureHandlingOptions failureOptions = trans.GetFailureHandlingOptions();
                    failureOptions.SetFailuresPreprocessor(new DismissWarningsPreprocessor());
                    trans.SetFailureHandlingOptions(failureOptions);

                    if (disallowJoinsBeforeAlign)
                    {
                        joinDisallowResult = DisallowStructuralFramingJoins(beams);
                        if (joinDisallowResult.ChangedCount > 0)
                            doc.Regenerate();
                    }

                    BeamAlignmentBuildResult buildResult = BuildBeamAlignmentPlans(
                        doc,
                        detectorView,
                        beams,
                        startParameterNames,
                        endParameterNames,
                        floorIdFilter,
                        toleranceMm,
                        maxDeltaMm,
                        maxSearchDistanceMm,
                        endSampleDistanceMm,
                        beamSampleCount,
                        requireBothEnds,
                        floorSelectionMode,
                        slopeDetectionToleranceMm,
                        alignWhenTopAboveFloorBottom,
                        preserveVerticalStacks);
                    plans = buildResult.Plans;
                    skipped = buildResult.Skipped;

                    foreach (BeamAlignmentPlan plan in plans)
                    {
                        try
                        {
                            if (plan.StartDeltaFeet.HasValue)
                            {
                                plan.StartParameter.Set(plan.OldStartOffsetFeet + plan.StartDeltaFeet.Value);
                            }

                            if (plan.EndDeltaFeet.HasValue)
                            {
                                plan.EndParameter.Set(plan.OldEndOffsetFeet + plan.EndDeltaFeet.Value);
                            }

                            plan.Applied = true;
                            adjustedCount++;
                        }
                        catch (Exception ex)
                        {
                            plan.CanApply = false;
                            plan.SkipReason = $"寫入參數失敗: {ex.Message}";
                        }
                    }

                    if (adjustedCount > 0)
                    {
                        doc.Regenerate();

                        if (postAlignGeometryCorrection)
                        {
                            geometryCorrections = ApplyPostAlignGeometryCorrections(
                                doc,
                                detectorView,
                                plans,
                                toleranceMm,
                                maxGeometryCorrectionMm,
                                maxSearchDistanceMm,
                                endSampleDistanceMm,
                                beamSampleCount);
                        }
                    }

                    trans.Commit();
                }
            }
            else
            {
                BeamAlignmentBuildResult buildResult = BuildBeamAlignmentPlans(
                    doc,
                    detectorView,
                    beams,
                    startParameterNames,
                    endParameterNames,
                    floorIdFilter,
                    toleranceMm,
                    maxDeltaMm,
                    maxSearchDistanceMm,
                    endSampleDistanceMm,
                    beamSampleCount,
                    requireBothEnds,
                    floorSelectionMode,
                    slopeDetectionToleranceMm,
                    alignWhenTopAboveFloorBottom,
                    preserveVerticalStacks);
                plans = buildResult.Plans;
                skipped = buildResult.Skipped;
            }

            var planResults = plans.Select(p => p.ToResult()).ToList();

            return new
            {
                Success = true,
                DryRun = dryRun,
                ApplyRequested = apply,
                BeamCount = beams.Count,
                PlannedCount = plans.Count,
                AdjustedCount = dryRun ? 0 : adjustedCount,
                SkippedCount = skipped.Count + plans.Count(p => !p.CanApply),
                ToleranceMm = toleranceMm,
                MaxDeltaMm = maxDeltaMm,
                MaxSearchDistanceMm = maxSearchDistanceMm,
                BeamSampleCount = beamSampleCount,
                FloorSelectionMode = floorSelectionMode,
                SlopeDetectionToleranceMm = slopeDetectionToleranceMm,
                AlignWhenTopAboveFloorBottom = alignWhenTopAboveFloorBottom,
                DisallowJoinsBeforeAlign = disallowJoinsBeforeAlign,
                JoinDisallow = joinDisallowResult.ToResult(),
                PostAlignGeometryCorrection = postAlignGeometryCorrection,
                MaxGeometryCorrectionMm = maxGeometryCorrectionMm,
                GeometryCorrections = geometryCorrections,
                PreserveVerticalStacks = preserveVerticalStacks,
                StartOffsetParameterNames = startParameterNames,
                EndOffsetParameterNames = endParameterNames,
                Results = planResults.Concat(skipped).ToList()
            };
        }

        private BeamAlignmentBuildResult BuildBeamAlignmentPlans(
            Document doc,
            View3D detectorView,
            List<Element> beams,
            List<string> startParameterNames,
            List<string> endParameterNames,
            HashSet<IdType> floorIdFilter,
            double toleranceMm,
            double maxDeltaMm,
            double maxSearchDistanceMm,
            double endSampleDistanceMm,
            int beamSampleCount,
            bool requireBothEnds,
            string floorSelectionMode,
            double slopeDetectionToleranceMm,
            bool alignWhenTopAboveFloorBottom,
            bool preserveVerticalStacks)
        {
            var result = new BeamAlignmentBuildResult();

            if (preserveVerticalStacks)
            {
                var stackCandidates = new List<BeamAlignmentPlan>();
                foreach (Element beam in beams)
                {
                    BeamAlignmentPlan plan = BuildBeamAlignmentPlan(
                        doc,
                        detectorView,
                        beam,
                        startParameterNames,
                        endParameterNames,
                        floorIdFilter,
                        toleranceMm,
                        1000000.0,
                        maxSearchDistanceMm,
                        endSampleDistanceMm,
                        beamSampleCount,
                        requireBothEnds,
                        floorSelectionMode,
                        slopeDetectionToleranceMm,
                        alignWhenTopAboveFloorBottom);

                    if (plan.CanApply || IsWithinToleranceStackAnchor(plan))
                        stackCandidates.Add(plan);
                    else
                        result.Skipped.Add(plan.ToResult());
                }

                foreach (BeamAlignmentPlan plan in BuildVerticalStackPreservedPlans(stackCandidates, toleranceMm, maxDeltaMm))
                {
                    if (plan.CanApply)
                        result.Plans.Add(plan);
                    else
                        result.Skipped.Add(plan.ToResult());
                }
            }
            else
            {
                foreach (Element beam in beams)
                {
                    BeamAlignmentPlan plan = BuildBeamAlignmentPlan(
                        doc,
                        detectorView,
                        beam,
                        startParameterNames,
                        endParameterNames,
                        floorIdFilter,
                        toleranceMm,
                        maxDeltaMm,
                        maxSearchDistanceMm,
                        endSampleDistanceMm,
                        beamSampleCount,
                        requireBothEnds,
                        floorSelectionMode,
                        slopeDetectionToleranceMm,
                        alignWhenTopAboveFloorBottom);

                    if (plan.CanApply)
                        result.Plans.Add(plan);
                    else
                        result.Skipped.Add(plan.ToResult());
                }
            }

            return result;
        }

        private BeamAlignmentPlan BuildBeamAlignmentPlan(
            Document doc,
            View3D detectorView,
            Element beam,
            List<string> startParameterNames,
            List<string> endParameterNames,
            HashSet<IdType> floorIdFilter,
            double toleranceMm,
            double maxDeltaMm,
            double maxSearchDistanceMm,
            double endSampleDistanceMm,
            int beamSampleCount,
            bool requireBothEnds,
            string floorSelectionMode,
            double slopeDetectionToleranceMm,
            bool alignWhenTopAboveFloorBottom)
        {
            var plan = new BeamAlignmentPlan
            {
                BeamId = beam.Id.GetIdValue(),
                BeamName = beam.Name ?? "",
                BeamTypeName = doc.GetElement(beam.GetTypeId())?.Name ?? "",
                CanApply = false
            };

            if (!IsStructuralFramingElement(beam))
            {
                plan.SkipReason = "元素不是 StructuralFraming";
                return plan;
            }

            LocationCurve locationCurve = beam.Location as LocationCurve;
            if (locationCurve == null)
            {
                plan.SkipReason = "樑沒有 LocationCurve";
                return plan;
            }

            Curve curve = locationCurve.Curve;
            XYZ start = curve.GetEndPoint(0);
            XYZ end = curve.GetEndPoint(1);
            double curveLength = curve.Length;
            if (curveLength < 1e-6)
            {
                plan.SkipReason = "樑 LocationCurve 長度過短";
                return plan;
            }

            Parameter startParam = FindWritableParameter(beam, startParameterNames, out string startParamName);
            Parameter endParam = FindWritableParameter(beam, endParameterNames, out string endParamName);
            if (startParam == null || endParam == null)
            {
                plan.SkipReason = $"找不到可寫入偏移參數: start={startParamName ?? "N/A"}, end={endParamName ?? "N/A"}";
                return plan;
            }

            if (startParam.StorageType != StorageType.Double || endParam.StorageType != StorageType.Double)
            {
                plan.SkipReason = "偏移參數不是長度/Double 類型";
                return plan;
            }

            plan.StartParameter = startParam;
            plan.EndParameter = endParam;
            plan.StartParameterName = startParamName;
            plan.EndParameterName = endParamName;
            plan.OldStartOffsetFeet = startParam.AsDouble();
            plan.OldEndOffsetFeet = endParam.AsDouble();

            BeamEndpointTopInfo topInfo = GetBeamEndpointTopInfo(beam, curve, endSampleDistanceMm);
            if (!topInfo.HasStartTop || !topInfo.HasEndTop)
            {
                plan.SkipReason = "無法可靠取得樑端頂部高程";
                return plan;
            }

            XYZ axis = (end - start).Normalize();
            double insetFeet = Math.Min(endSampleDistanceMm * StructuralFramingMmToFeet, curveLength * 0.25);
            XYZ startSample = start + axis.Multiply(insetFeet);
            XYZ endSample = end - axis.Multiply(insetFeet);

            FloorHitInfo startFloor;
            FloorHitInfo endFloor;
            if (floorSelectionMode.Equals("nearest_at_beam", StringComparison.OrdinalIgnoreCase))
            {
                startFloor = FindNearestFloorBottomAtPoint(
                    doc,
                    detectorView,
                    startSample,
                    topInfo.StartTopZ,
                    maxSearchDistanceMm,
                    floorIdFilter);

                endFloor = FindNearestFloorBottomAtPoint(
                    doc,
                    detectorView,
                    endSample,
                    topInfo.EndTopZ,
                    maxSearchDistanceMm,
                    floorIdFilter);
            }
            else if (floorSelectionMode.Equals("auto_by_beam", StringComparison.OrdinalIgnoreCase))
            {
                ResolveAutoFloorTargetsAlongBeam(
                    doc,
                    detectorView,
                    curve,
                    topInfo,
                    startSample,
                    endSample,
                    maxSearchDistanceMm,
                    endSampleDistanceMm,
                    beamSampleCount,
                    floorIdFilter,
                    slopeDetectionToleranceMm,
                    out startFloor,
                    out endFloor);
            }
            else
            {
                FloorHitInfo sharedTarget = FindDominantFloorBottomAlongBeam(
                    doc,
                    detectorView,
                    curve,
                    topInfo,
                    maxSearchDistanceMm,
                    endSampleDistanceMm,
                    beamSampleCount,
                    floorIdFilter);

                startFloor = CloneFloorHitWithBeamTop(sharedTarget, topInfo.StartTopZ);
                endFloor = CloneFloorHitWithBeamTop(sharedTarget, topInfo.EndTopZ);
            }

            plan.StartBeamTopZFeet = topInfo.StartTopZ;
            plan.EndBeamTopZFeet = topInfo.EndTopZ;
            plan.StartSamplePoint = startSample;
            plan.EndSamplePoint = endSample;
            plan.StartFloor = startFloor;
            plan.EndFloor = endFloor;

            if (!startFloor.HasHit || !endFloor.HasHit)
            {
                if (requireBothEnds)
                {
                    plan.SkipReason = $"找不到樓板底: start={startFloor.Message}, end={endFloor.Message}";
                    return plan;
                }
            }

            if (ShouldLowerBeamTopToFloorBottom(startFloor, toleranceMm, alignWhenTopAboveFloorBottom))
            {
                double deltaFeet = startFloor.BottomZFeet - topInfo.StartTopZ;
                double deltaMm = deltaFeet * StructuralFramingFeetToMm;
                if (Math.Abs(deltaMm) > maxDeltaMm)
                {
                    plan.SkipReason = $"起點調整量 {Math.Round(deltaMm, 2)}mm 超過 maxDeltaMm";
                    return plan;
                }
                plan.StartDeltaFeet = Math.Abs(deltaMm) <= toleranceMm ? (double?)null : deltaFeet;
            }

            if (ShouldLowerBeamTopToFloorBottom(endFloor, toleranceMm, alignWhenTopAboveFloorBottom))
            {
                double deltaFeet = endFloor.BottomZFeet - topInfo.EndTopZ;
                double deltaMm = deltaFeet * StructuralFramingFeetToMm;
                if (Math.Abs(deltaMm) > maxDeltaMm)
                {
                    plan.SkipReason = $"終點調整量 {Math.Round(deltaMm, 2)}mm 超過 maxDeltaMm";
                    return plan;
                }
                plan.EndDeltaFeet = Math.Abs(deltaMm) <= toleranceMm ? (double?)null : deltaFeet;
            }

            if (!plan.StartDeltaFeet.HasValue && !plan.EndDeltaFeet.HasValue)
            {
                plan.SkipReason = alignWhenTopAboveFloorBottom
                    ? "梁頂未高於樓板底或偏差皆在容許誤差內"
                    : "兩端偏差皆在容許誤差內";
                return plan;
            }

            plan.CanApply = true;
            return plan;
        }

        private bool BeamTopExceedsFloorTop(FloorHitInfo floorHit, double toleranceMm)
        {
            return floorHit?.HasHit == true
                && floorHit.BeamTopAboveFloorTopFeet.HasValue
                && floorHit.BeamTopAboveFloorTopFeet.Value * StructuralFramingFeetToMm > toleranceMm;
        }

        private bool ShouldLowerBeamTopToFloorBottom(FloorHitInfo floorHit, double toleranceMm, bool alignWhenTopAboveFloorBottom)
        {
            if (floorHit?.HasHit != true)
                return false;

            if (!alignWhenTopAboveFloorBottom)
                return BeamTopExceedsFloorTop(floorHit, toleranceMm);

            double beamTopAboveBottomMm = -floorHit.DistanceToBeamTopFeet * StructuralFramingFeetToMm;
            return beamTopAboveBottomMm > toleranceMm;
        }

        private bool IsWithinToleranceStackAnchor(BeamAlignmentPlan plan)
        {
            return plan.StartParameter != null
                && plan.EndParameter != null
                && plan.StartFloor?.HasHit == true
                && plan.EndFloor?.HasHit == true
                && !plan.StartDeltaFeet.HasValue
                && !plan.EndDeltaFeet.HasValue;
        }

        private List<BeamAlignmentPlan> BuildVerticalStackPreservedPlans(
            List<BeamAlignmentPlan> candidates,
            double toleranceMm,
            double maxDeltaMm)
        {
            var results = new List<BeamAlignmentPlan>();

            foreach (var group in candidates.GroupBy(GetVerticalStackKey))
            {
                BeamAlignmentPlan controller = group
                    .OrderByDescending(p => (p.StartBeamTopZFeet + p.EndBeamTopZFeet) / 2.0)
                    .First();

                double? controllerStartDelta = controller.StartDeltaFeet;
                double? controllerEndDelta = controller.EndDeltaFeet;
                double? controllerStartDeltaMm = controllerStartDelta.HasValue
                    ? controllerStartDelta.Value * StructuralFramingFeetToMm
                    : (double?)null;
                double? controllerEndDeltaMm = controllerEndDelta.HasValue
                    ? controllerEndDelta.Value * StructuralFramingFeetToMm
                    : (double?)null;

                bool startOverLimit = controllerStartDeltaMm.HasValue && Math.Abs(controllerStartDeltaMm.Value) > maxDeltaMm;
                bool endOverLimit = controllerEndDeltaMm.HasValue && Math.Abs(controllerEndDeltaMm.Value) > maxDeltaMm;
                bool hasStackDelta =
                    (controllerStartDeltaMm.HasValue && Math.Abs(controllerStartDeltaMm.Value) > toleranceMm) ||
                    (controllerEndDeltaMm.HasValue && Math.Abs(controllerEndDeltaMm.Value) > toleranceMm);

                foreach (BeamAlignmentPlan plan in group)
                {
                    plan.PreserveVerticalStack = true;
                    plan.StackGroupKey = group.Key;
                    plan.StackControllerBeamId = controller.BeamId;

                    if (startOverLimit)
                    {
                        plan.CanApply = false;
                        plan.SkipReason = $"最高梁起點調整量 {Math.Round(controllerStartDeltaMm.Value, 2)}mm 超過 maxDeltaMm";
                        results.Add(plan);
                        continue;
                    }

                    if (endOverLimit)
                    {
                        plan.CanApply = false;
                        plan.SkipReason = $"最高梁終點調整量 {Math.Round(controllerEndDeltaMm.Value, 2)}mm 超過 maxDeltaMm";
                        results.Add(plan);
                        continue;
                    }

                    if (!hasStackDelta)
                    {
                        plan.CanApply = false;
                        plan.SkipReason = "最高梁兩端偏差皆在容許誤差內";
                        results.Add(plan);
                        continue;
                    }

                    plan.StartDeltaFeet = controllerStartDeltaMm.HasValue && Math.Abs(controllerStartDeltaMm.Value) > toleranceMm
                        ? controllerStartDelta
                        : (double?)null;
                    plan.EndDeltaFeet = controllerEndDeltaMm.HasValue && Math.Abs(controllerEndDeltaMm.Value) > toleranceMm
                        ? controllerEndDelta
                        : (double?)null;
                    plan.CanApply = plan.StartDeltaFeet.HasValue || plan.EndDeltaFeet.HasValue;
                    plan.SkipReason = plan.CanApply ? null : "最高梁兩端偏差皆在容許誤差內";
                    results.Add(plan);
                }
            }

            return results;
        }

        private BeamJoinDisallowResult DisallowStructuralFramingJoins(IEnumerable<Element> beams)
        {
            var result = new BeamJoinDisallowResult();

            foreach (Element beam in beams)
            {
                FamilyInstance instance = beam as FamilyInstance;
                if (instance == null)
                    continue;

                for (int end = 0; end <= 1; end++)
                {
                    result.AttemptedCount++;
                    try
                    {
                        bool shouldDisallow = true;
                        try
                        {
                            shouldDisallow = StructuralFramingUtils.IsJoinAllowedAtEnd(instance, end);
                        }
                        catch
                        {
                            shouldDisallow = true;
                        }

                        if (shouldDisallow)
                        {
                            StructuralFramingUtils.DisallowJoinAtEnd(instance, end);
                            result.ChangedCount++;
                        }
                    }
                    catch (Exception ex)
                    {
                        result.FailedCount++;
                        if (result.Failures.Count < 20)
                        {
                            result.Failures.Add(new
                            {
                                BeamId = beam.Id.GetIdValue(),
                                End = end,
                                Reason = ex.Message
                            });
                        }
                    }
                }
            }

            return result;
        }

        private List<object> ApplyPostAlignGeometryCorrections(
            Document doc,
            View3D detectorView,
            List<BeamAlignmentPlan> plans,
            double toleranceMm,
            double maxCorrectionMm,
            double maxSearchDistanceMm,
            double endSampleDistanceMm,
            int beamSampleCount)
        {
            var results = new List<object>();
            var appliedPlans = plans.Where(p => p.Applied && p.StartParameter != null && p.EndParameter != null).ToList();
            int correctionCount = 0;

            foreach (var group in appliedPlans.GroupBy(p => !string.IsNullOrWhiteSpace(p.StackGroupKey) ? p.StackGroupKey : $"beam:{p.BeamId}"))
            {
                var groupPlans = group.ToList();
                BeamResidualProbe worstProbe = null;

                foreach (BeamAlignmentPlan plan in groupPlans)
                {
                    Element beam = doc.GetElement(plan.BeamId.ToElementId());
                    BeamResidualProbe probe = FindMaxBeamTopResidualAboveFloorBottom(
                        doc,
                        detectorView,
                        beam,
                        plan,
                        maxSearchDistanceMm,
                        endSampleDistanceMm,
                        beamSampleCount);

                    if (probe == null)
                        continue;

                    plan.PostGeometryMaxResidualFeet = probe.MaxResidualFeet;
                    plan.PostGeometryWorstSampleT = probe.SampleT;

                    if (probe.MaxResidualFeet * StructuralFramingFeetToMm > toleranceMm &&
                        (worstProbe == null || probe.MaxResidualFeet > worstProbe.MaxResidualFeet))
                    {
                        worstProbe = probe;
                    }
                }

                if (worstProbe == null)
                    continue;

                double correctionFeet = -worstProbe.MaxResidualFeet;
                double correctionMm = Math.Abs(correctionFeet * StructuralFramingFeetToMm);
                if (correctionMm > maxCorrectionMm)
                {
                    results.Add(new
                    {
                        StackGroupKey = group.Key,
                        Applied = false,
                        Reason = $"幾何補償量 {Math.Round(correctionMm, 2)}mm 超過 maxGeometryCorrectionMm",
                        WorstBeamId = worstProbe.BeamId,
                        WorstFloorId = worstProbe.FloorId,
                        MaxResidualMm = Math.Round(worstProbe.MaxResidualFeet * StructuralFramingFeetToMm, 2),
                        SampleT = Math.Round(worstProbe.SampleT, 3)
                    });
                    continue;
                }

                int changedInGroup = 0;
                foreach (BeamAlignmentPlan plan in groupPlans)
                {
                    try
                    {
                        plan.StartParameter.Set(plan.StartParameter.AsDouble() + correctionFeet);
                        plan.EndParameter.Set(plan.EndParameter.AsDouble() + correctionFeet);
                        plan.PostGeometryCorrectionFeet = correctionFeet;
                        changedInGroup++;
                        correctionCount++;
                    }
                    catch (Exception ex)
                    {
                        results.Add(new
                        {
                            StackGroupKey = group.Key,
                            BeamId = plan.BeamId,
                            Applied = false,
                            Reason = $"幾何補償寫入失敗: {ex.Message}"
                        });
                    }
                }

                if (changedInGroup > 0)
                {
                    results.Add(new
                    {
                        StackGroupKey = group.Key,
                        Applied = true,
                        BeamCount = changedInGroup,
                        CorrectionMm = Math.Round(correctionFeet * StructuralFramingFeetToMm, 2),
                        WorstBeamId = worstProbe.BeamId,
                        WorstFloorId = worstProbe.FloorId,
                        MaxResidualMm = Math.Round(worstProbe.MaxResidualFeet * StructuralFramingFeetToMm, 2),
                        SampleT = Math.Round(worstProbe.SampleT, 3)
                    });
                }
            }

            if (correctionCount > 0)
                doc.Regenerate();

            return results;
        }

        private BeamResidualProbe FindMaxBeamTopResidualAboveFloorBottom(
            Document doc,
            View3D detectorView,
            Element beam,
            BeamAlignmentPlan plan,
            double maxSearchDistanceMm,
            double endSampleDistanceMm,
            int beamSampleCount)
        {
            if (beam == null || plan?.StartFloor?.HasHit != true || plan.EndFloor?.HasHit != true)
                return null;

            LocationCurve locationCurve = beam.Location as LocationCurve;
            if (locationCurve == null)
                return null;

            Curve curve = locationCurve.Curve;
            if (curve == null || curve.Length < 1e-6)
                return null;

            BeamEndpointTopInfo topInfo = GetBeamEndpointTopInfo(beam, curve, endSampleDistanceMm);
            if (!topInfo.HasStartTop || !topInfo.HasEndTop)
                return null;

            int sampleCount = Math.Max(3, Math.Min(25, beamSampleCount));
            double insetParam = Math.Min(endSampleDistanceMm * StructuralFramingMmToFeet, curve.Length * 0.25) / curve.Length;
            double sampleSpan = Math.Max(0.0, 1.0 - (2.0 * insetParam));
            BeamResidualProbe worst = null;

            for (int i = 0; i < sampleCount; i++)
            {
                double ratio = sampleCount == 1 ? 0.5 : (double)i / (sampleCount - 1);
                double t = insetParam + (sampleSpan * ratio);
                XYZ samplePoint = curve.Evaluate(t, true);
                double beamTopZFeet = topInfo.StartTopZ + ((topInfo.EndTopZ - topInfo.StartTopZ) * t);
                IdType floorId = GetPlanTargetFloorIdAtSample(plan, t);

                FloorHitInfo floorHit = FindFloorBottomAtPointForFloor(
                    doc,
                    detectorView,
                    samplePoint,
                    beamTopZFeet,
                    maxSearchDistanceMm,
                    floorId);

                if (floorHit == null || !floorHit.HasHit)
                    continue;

                double residualFeet = beamTopZFeet - floorHit.BottomZFeet;
                if (worst == null || residualFeet > worst.MaxResidualFeet)
                {
                    worst = new BeamResidualProbe
                    {
                        BeamId = plan.BeamId,
                        FloorId = floorId,
                        MaxResidualFeet = residualFeet,
                        SampleT = t,
                        BeamTopZFeet = beamTopZFeet,
                        FloorBottomZFeet = floorHit.BottomZFeet
                    };
                }
            }

            return worst;
        }

        private IdType GetPlanTargetFloorIdAtSample(BeamAlignmentPlan plan, double normalizedParameter)
        {
            if (plan.StartFloor?.HasHit == true && plan.EndFloor?.HasHit == true)
            {
                if (plan.StartFloor.FloorId.Equals(plan.EndFloor.FloorId))
                    return plan.StartFloor.FloorId;

                return normalizedParameter <= 0.5 ? plan.StartFloor.FloorId : plan.EndFloor.FloorId;
            }

            if (plan.StartFloor?.HasHit == true)
                return plan.StartFloor.FloorId;

            return plan.EndFloor.FloorId;
        }

        private string GetVerticalStackKey(BeamAlignmentPlan plan)
        {
            string a = FormatStackPoint(plan.StartSamplePoint);
            string b = FormatStackPoint(plan.EndSamplePoint);
            string floorKey = $"{plan.StartFloor?.FloorId ?? 0}:{plan.EndFloor?.FloorId ?? 0}";

            return string.CompareOrdinal(a, b) <= 0
                ? $"{a}|{b}|{floorKey}"
                : $"{b}|{a}|{floorKey}";
        }

        private string FormatStackPoint(XYZ point)
        {
            if (point == null) return "null";

            double xMm = point.X * StructuralFramingFeetToMm;
            double yMm = point.Y * StructuralFramingFeetToMm;
            double roundMm = 25.0;
            return $"{Math.Round(xMm / roundMm) * roundMm:0}:{Math.Round(yMm / roundMm) * roundMm:0}";
        }

        private List<Element> CollectTargetBeams(
            Document doc,
            JArray beamIds,
            bool selectedOnly,
            IdType? viewId,
            string levelName,
            int maxCount)
        {
            IEnumerable<Element> source;

            if (beamIds != null && beamIds.Count > 0)
            {
                source = beamIds
                    .Select(id => doc.GetElement(id.Value<IdType>().ToElementId()))
                    .Where(e => e != null);
            }
            else if (selectedOnly)
            {
                source = _uiApp.ActiveUIDocument.Selection.GetElementIds()
                    .Select(id => doc.GetElement(id))
                    .Where(e => e != null);
            }
            else
            {
                FilteredElementCollector collector = viewId.HasValue
                    ? new FilteredElementCollector(doc, viewId.Value.ToElementId())
                    : new FilteredElementCollector(doc);

                source = collector
                    .OfCategory(BuiltInCategory.OST_StructuralFraming)
                    .WhereElementIsNotElementType()
                    .ToElements();
            }

            return source
                .Where(IsStructuralFramingElement)
                .Where(e => string.IsNullOrWhiteSpace(levelName) || ElementMatchesLevel(doc, e, levelName))
                .Take(Math.Max(1, maxCount))
                .ToList();
        }

        private View3D GetDetector3DView(Document doc)
        {
            View3D view = new FilteredElementCollector(doc)
                .OfClass(typeof(View3D))
                .Cast<View3D>()
                .Where(v => !v.IsTemplate)
                .OrderBy(v => v.IsSectionBoxActive ? 1 : 0)
                .FirstOrDefault();

            if (view == null)
                throw new Exception("需要至少一個非樣板 3D View 才能使用 ReferenceIntersector 找樓板底");

            return view;
        }

        private BeamEndpointTopInfo GetBeamEndpointTopInfo(Element beam, Curve curve, double endSampleDistanceMm)
        {
            XYZ start = curve.GetEndPoint(0);
            XYZ end = curve.GetEndPoint(1);
            XYZ axis = (end - start).Normalize();
            double length = curve.Length;
            double sampleFeet = Math.Min(endSampleDistanceMm * StructuralFramingMmToFeet, length * 0.25);

            List<XYZ> vertices = new List<XYZ>();
            Options options = new Options
            {
                DetailLevel = ViewDetailLevel.Fine,
                IncludeNonVisibleObjects = false
            };

            try
            {
                GeometryElement geometry = beam.get_Geometry(options);
                CollectGeometryVertices(geometry, Transform.Identity, vertices);
            }
            catch
            {
                vertices.Clear();
            }

            double? startTop = null;
            double? endTop = null;

            foreach (XYZ vertex in vertices)
            {
                double along = (vertex - start).DotProduct(axis);
                if (along >= -0.1 && along <= sampleFeet)
                {
                    startTop = !startTop.HasValue ? vertex.Z : Math.Max(startTop.Value, vertex.Z);
                }

                double fromEnd = length - along;
                if (fromEnd >= -0.1 && fromEnd <= sampleFeet)
                {
                    endTop = !endTop.HasValue ? vertex.Z : Math.Max(endTop.Value, vertex.Z);
                }
            }

            if (!startTop.HasValue || !endTop.HasValue)
            {
                BoundingBoxXYZ bbox = beam.get_BoundingBox(null);
                if (bbox != null)
                {
                    double topOffset = bbox.Max.Z - Math.Max(start.Z, end.Z);
                    if (!startTop.HasValue) startTop = start.Z + topOffset;
                    if (!endTop.HasValue) endTop = end.Z + topOffset;
                }
            }

            return new BeamEndpointTopInfo
            {
                HasStartTop = startTop.HasValue,
                HasEndTop = endTop.HasValue,
                StartTopZ = startTop ?? 0,
                EndTopZ = endTop ?? 0
            };
        }

        private void CollectGeometryVertices(GeometryElement geometry, Transform transform, List<XYZ> vertices)
        {
            if (geometry == null) return;

            foreach (GeometryObject obj in geometry)
            {
                if (obj is Solid solid && solid.Faces.Size > 0)
                {
                    foreach (Face face in solid.Faces)
                    {
                        Mesh mesh = face.Triangulate();
                        for (int i = 0; i < mesh.NumTriangles; i++)
                        {
                            MeshTriangle triangle = mesh.get_Triangle(i);
                            vertices.Add(transform.OfPoint(triangle.get_Vertex(0)));
                            vertices.Add(transform.OfPoint(triangle.get_Vertex(1)));
                            vertices.Add(transform.OfPoint(triangle.get_Vertex(2)));
                        }
                    }
                }
                else if (obj is GeometryInstance instance)
                {
                    Transform nextTransform = transform.Multiply(instance.Transform);
                    CollectGeometryVertices(instance.GetInstanceGeometry(), nextTransform, vertices);
                }
            }
        }

        private FloorHitInfo FindLowestFloorBottomOnHitLevel(
            Document doc,
            Element beam,
            FloorHitInfo levelHint,
            HashSet<IdType> floorIdFilter)
        {
            ElementId targetLevelId = null;
            if (levelHint != null && levelHint.LevelId.HasValue)
                targetLevelId = levelHint.LevelId.Value.ToElementId();

            if (targetLevelId == null || targetLevelId == ElementId.InvalidElementId)
                targetLevelId = GetElementReferenceLevelId(doc, beam);

            string targetLevelName = GetLevelName(doc, targetLevelId);
            if (targetLevelId == null || targetLevelId == ElementId.InvalidElementId)
            {
                return new FloorHitInfo
                {
                    HasHit = false,
                    Message = "floor-level-not-found"
                };
            }

            FloorHitInfo best = null;
            var floors = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Floors)
                .WhereElementIsNotElementType()
                .ToElements();

            foreach (Element floor in floors)
            {
                IdType floorId = floor.Id.GetIdValue();
                if (floorIdFilter != null && floorIdFilter.Count > 0 && !floorIdFilter.Contains(floorId))
                    continue;

                ElementId floorLevelId = GetElementReferenceLevelId(doc, floor);
                if (!SameElementId(targetLevelId, floorLevelId))
                    continue;

                double? bottomZFeet = GetLowestElementZFeet(floor);
                if (!bottomZFeet.HasValue)
                    continue;

                var candidate = new FloorHitInfo
                {
                    HasHit = true,
                    FloorId = floorId,
                    FloorName = floor.Name ?? "",
                    LevelId = floorLevelId.GetIdValue(),
                    LevelName = GetLevelName(doc, floorLevelId),
                    BottomZFeet = bottomZFeet.Value,
                    LevelOffsetFeet = GetFloorBottomLevelOffsetFeet(doc, floorLevelId, bottomZFeet.Value),
                    Message = "lowest_by_level"
                };

                if (best == null || candidate.BottomZFeet < best.BottomZFeet)
                    best = candidate;
            }

            return best ?? new FloorHitInfo
            {
                HasHit = false,
                LevelId = targetLevelId.GetIdValue(),
                LevelName = targetLevelName,
                Message = "no-floor-on-hit-level"
            };
        }

        private bool SameFloorLevel(FloorHitInfo first, FloorHitInfo second)
        {
            if (first == null || second == null || !first.LevelId.HasValue || !second.LevelId.HasValue)
                return false;

            return first.LevelId.Value == second.LevelId.Value;
        }

        private FloorHitInfo CloneFloorHitWithBeamTop(FloorHitInfo source, double beamTopZFeet)
        {
            if (source == null)
                return new FloorHitInfo { HasHit = false, Message = "no-floor-target" };

            return new FloorHitInfo
            {
                HasHit = source.HasHit,
                FloorId = source.FloorId,
                FloorName = source.FloorName,
                LevelId = source.LevelId,
                LevelName = source.LevelName,
                BottomZFeet = source.BottomZFeet,
                TopZFeet = source.TopZFeet,
                DistanceToBeamTopFeet = source.HasHit ? source.BottomZFeet - beamTopZFeet : 0,
                BeamTopAboveFloorTopFeet = source.HasHit && source.TopZFeet.HasValue ? beamTopZFeet - source.TopZFeet.Value : (double?)null,
                AreaFeet = source.AreaFeet,
                LevelOffsetFeet = source.LevelOffsetFeet,
                SampleHitCount = source.SampleHitCount,
                Message = source.Message
            };
        }

        private double? GetLowestElementZFeet(Element element)
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
                return vertices.Min(v => v.Z);

            BoundingBoxXYZ bbox = element.get_BoundingBox(null);
            return bbox?.Min.Z;
        }

        private ElementId GetElementReferenceLevelId(Document doc, Element element)
        {
            if (element == null)
                return ElementId.InvalidElementId;

            if (element.LevelId != ElementId.InvalidElementId)
                return element.LevelId;

            Parameter referenceLevelParam = element.get_Parameter(BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM);
            if (referenceLevelParam != null && referenceLevelParam.StorageType == StorageType.ElementId)
            {
                ElementId levelId = referenceLevelParam.AsElementId();
                if (levelId != ElementId.InvalidElementId)
                    return levelId;
            }

            Parameter levelParam = element.get_Parameter(BuiltInParameter.LEVEL_PARAM);
            if (levelParam != null && levelParam.StorageType == StorageType.ElementId)
            {
                ElementId levelId = levelParam.AsElementId();
                if (levelId != ElementId.InvalidElementId)
                    return levelId;
            }

            return ElementId.InvalidElementId;
        }

        private bool SameElementId(ElementId a, ElementId b)
        {
            return a != null &&
                   b != null &&
                   a != ElementId.InvalidElementId &&
                   b != ElementId.InvalidElementId &&
                   a.GetIdValue() == b.GetIdValue();
        }

        private string GetLevelName(Document doc, ElementId levelId)
        {
            if (levelId == null || levelId == ElementId.InvalidElementId)
                return "";

            return (doc.GetElement(levelId) as Level)?.Name ?? "";
        }

        private double? GetFloorBottomLevelOffsetFeet(Document doc, ElementId levelId, double bottomZFeet)
        {
            if (levelId == null || levelId == ElementId.InvalidElementId)
                return null;

            Level level = doc.GetElement(levelId) as Level;
            return level == null ? (double?)null : bottomZFeet - level.Elevation;
        }

        private void PopulateFloorTopInfo(FloorHitInfo hit, Element floor, XYZ samplePoint, double beamTopZFeet, double xyToleranceFeet)
        {
            if (hit == null || !hit.HasHit || floor == null)
                return;

            double? topZ = TryGetFloorTopZFromHorizontalFaces(floor, samplePoint, xyToleranceFeet);
            if (!topZ.HasValue)
            {
                BoundingBoxXYZ bbox = floor.get_BoundingBox(null);
                if (bbox != null && PointInsideBoxXY(samplePoint, bbox, xyToleranceFeet))
                    topZ = bbox.Max.Z;
            }

            if (topZ.HasValue)
            {
                hit.TopZFeet = topZ.Value;
                hit.BeamTopAboveFloorTopFeet = beamTopZFeet - topZ.Value;
            }
        }

        private FloorHitInfo FindNearestFloorBottomAtPoint(
            Document doc,
            View3D detectorView,
            XYZ samplePoint,
            double beamTopZFeet,
            double maxSearchDistanceMm,
            HashSet<IdType> floorIdFilter)
        {
            double maxSearchFeet = maxSearchDistanceMm * StructuralFramingMmToFeet;
            XYZ origin = new XYZ(samplePoint.X, samplePoint.Y, beamTopZFeet - maxSearchFeet);
            ReferenceIntersector intersector = new ReferenceIntersector(
                new ElementCategoryFilter(BuiltInCategory.OST_Floors),
                FindReferenceTarget.Face,
                detectorView);

            IList<ReferenceWithContext> hits = intersector.Find(origin, XYZ.BasisZ);
            if (hits == null || hits.Count == 0)
            {
                return new FloorHitInfo { HasHit = false, Message = "未找到樓板" };
            }

            FloorHitInfo best = null;
            FloorHitInfo fallback = null;

            foreach (ReferenceWithContext hit in hits.OrderBy(h => h.Proximity))
            {
                Reference reference = hit.GetReference();
                if (reference == null) continue;

                IdType floorId = reference.ElementId.GetIdValue();
                if (floorIdFilter != null && floorIdFilter.Count > 0 && !floorIdFilter.Contains(floorId))
                    continue;

                Element floor = doc.GetElement(reference.ElementId);
                if (floor == null) continue;

                double hitZ = reference.GlobalPoint != null
                    ? reference.GlobalPoint.Z
                    : origin.Z + hit.Proximity;

                double deltaFromTop = hitZ - beamTopZFeet;
                if (Math.Abs(deltaFromTop) > maxSearchFeet)
                    continue;

                bool normalKnown;
                bool isBottomFace = IsLikelyBottomFace(floor, reference, out normalKnown);
                ElementId floorLevelId = GetElementReferenceLevelId(doc, floor);
                var candidate = new FloorHitInfo
                {
                    HasHit = true,
                    FloorId = floorId,
                    FloorName = floor.Name ?? "",
                    LevelId = floorLevelId.GetIdValue(),
                    LevelName = GetLevelName(doc, floorLevelId),
                    BottomZFeet = hitZ,
                    DistanceToBeamTopFeet = deltaFromTop,
                    LevelOffsetFeet = GetFloorBottomLevelOffsetFeet(doc, floorLevelId, hitZ),
                    Message = normalKnown ? "face" : "face-normal-unknown"
                };
                PopulateFloorTopInfo(candidate, floor, samplePoint, beamTopZFeet, 50.0 * StructuralFramingMmToFeet);

                if (isBottomFace)
                {
                    if (best == null || Math.Abs(candidate.DistanceToBeamTopFeet) < Math.Abs(best.DistanceToBeamTopFeet))
                        best = candidate;
                }
                else if (fallback == null || Math.Abs(candidate.DistanceToBeamTopFeet) < Math.Abs(fallback.DistanceToBeamTopFeet))
                {
                    BoundingBoxXYZ bbox = floor.get_BoundingBox(null);
                    if (bbox != null)
                    {
                        candidate.BottomZFeet = bbox.Min.Z;
                        candidate.DistanceToBeamTopFeet = candidate.BottomZFeet - beamTopZFeet;
                        candidate.LevelOffsetFeet = GetFloorBottomLevelOffsetFeet(doc, floorLevelId, candidate.BottomZFeet);
                        candidate.Message = "fallback-bounding-box";
                        PopulateFloorTopInfo(candidate, floor, samplePoint, beamTopZFeet, 50.0 * StructuralFramingMmToFeet);
                        fallback = candidate;
                    }
                }
            }

            return best ?? fallback ?? new FloorHitInfo { HasHit = false, Message = "未找到可用樓板底面" };
        }

        private FloorHitInfo FindLowestFloorBottomAtPoint(
            Document doc,
            View3D detectorView,
            XYZ samplePoint,
            double beamTopZFeet,
            double maxSearchDistanceMm,
            HashSet<IdType> floorIdFilter)
        {
            double maxSearchFeet = maxSearchDistanceMm * StructuralFramingMmToFeet;
            XYZ origin = new XYZ(samplePoint.X, samplePoint.Y, beamTopZFeet - maxSearchFeet);
            ReferenceIntersector intersector = new ReferenceIntersector(
                new ElementCategoryFilter(BuiltInCategory.OST_Floors),
                FindReferenceTarget.Face,
                detectorView);

            IList<ReferenceWithContext> hits = intersector.Find(origin, XYZ.BasisZ);
            if (hits == null || hits.Count == 0)
                return new FloorHitInfo { HasHit = false, Message = "no-floor-hit" };

            FloorHitInfo best = null;
            FloorHitInfo fallback = null;
            var seenBottomFaces = new HashSet<IdType>();
            var seenFallbacks = new HashSet<IdType>();

            foreach (ReferenceWithContext hit in hits.OrderBy(h => h.Proximity))
            {
                Reference reference = hit.GetReference();
                if (reference == null) continue;

                IdType floorId = reference.ElementId.GetIdValue();
                if (floorIdFilter != null && floorIdFilter.Count > 0 && !floorIdFilter.Contains(floorId))
                    continue;

                Element floor = doc.GetElement(reference.ElementId);
                if (floor == null) continue;

                double hitZ = reference.GlobalPoint != null
                    ? reference.GlobalPoint.Z
                    : origin.Z + hit.Proximity;

                double deltaFromTop = hitZ - beamTopZFeet;
                if (Math.Abs(deltaFromTop) > maxSearchFeet)
                    continue;

                bool normalKnown;
                bool isBottomFace = IsLikelyBottomFace(floor, reference, out normalKnown);
                ElementId floorLevelId = GetElementReferenceLevelId(doc, floor);

                if (isBottomFace)
                {
                    if (!seenBottomFaces.Add(floorId))
                        continue;

                    var candidate = new FloorHitInfo
                    {
                        HasHit = true,
                        FloorId = floorId,
                        FloorName = floor.Name ?? "",
                        LevelId = floorLevelId.GetIdValue(),
                        LevelName = GetLevelName(doc, floorLevelId),
                        BottomZFeet = hitZ,
                        DistanceToBeamTopFeet = hitZ - beamTopZFeet,
                        LevelOffsetFeet = GetFloorBottomLevelOffsetFeet(doc, floorLevelId, hitZ),
                        Message = "lowest_by_vertical_hit"
                    };
                    PopulateFloorTopInfo(candidate, floor, samplePoint, beamTopZFeet, 50.0 * StructuralFramingMmToFeet);

                    if (best == null || candidate.BottomZFeet < best.BottomZFeet)
                        best = candidate;
                }
                else if (!normalKnown && seenFallbacks.Add(floorId))
                {
                    BoundingBoxXYZ bbox = floor.get_BoundingBox(null);
                    if (bbox == null)
                        continue;

                    var candidate = new FloorHitInfo
                    {
                        HasHit = true,
                        FloorId = floorId,
                        FloorName = floor.Name ?? "",
                        LevelId = floorLevelId.GetIdValue(),
                        LevelName = GetLevelName(doc, floorLevelId),
                        BottomZFeet = bbox.Min.Z,
                        DistanceToBeamTopFeet = bbox.Min.Z - beamTopZFeet,
                        LevelOffsetFeet = GetFloorBottomLevelOffsetFeet(doc, floorLevelId, bbox.Min.Z),
                        Message = "lowest_by_vertical_hit_bbox"
                    };
                    PopulateFloorTopInfo(candidate, floor, samplePoint, beamTopZFeet, 50.0 * StructuralFramingMmToFeet);

                    if (fallback == null || candidate.BottomZFeet < fallback.BottomZFeet)
                        fallback = candidate;
                }
            }

            return best ?? fallback ?? new FloorHitInfo { HasHit = false, Message = "no-floor-bottom-hit" };
        }

        private FloorHitInfo FindDominantFloorBottomAlongBeam(
            Document doc,
            View3D detectorView,
            Curve curve,
            BeamEndpointTopInfo topInfo,
            double maxSearchDistanceMm,
            double endSampleDistanceMm,
            int beamSampleCount,
            HashSet<IdType> floorIdFilter)
        {
            double curveLength = curve.Length;
            if (curveLength < 1e-6)
                return new FloorHitInfo { HasHit = false, Message = "beam-curve-too-short" };

            double insetFeet = Math.Min(endSampleDistanceMm * StructuralFramingMmToFeet, curveLength * 0.25);
            double startParam = insetFeet / curveLength;
            double endParam = 1.0 - startParam;
            var candidates = new Dictionary<IdType, FloorCandidateInfo>();
            var areaCache = new Dictionary<IdType, double>();

            for (int i = 0; i < beamSampleCount; i++)
            {
                double sampleRatio = beamSampleCount == 1 ? 0.5 : (double)i / (beamSampleCount - 1);
                double curveParam = startParam + (endParam - startParam) * sampleRatio;
                XYZ samplePoint = curve.Evaluate(curveParam, true);
                double sampleTopZ = topInfo.StartTopZ + (topInfo.EndTopZ - topInfo.StartTopZ) * sampleRatio;

                foreach (FloorHitInfo hit in CollectFloorBottomHitsAtPoint(
                    doc,
                    detectorView,
                    samplePoint,
                    sampleTopZ,
                    maxSearchDistanceMm,
                    floorIdFilter))
                {
                    if (!candidates.TryGetValue(hit.FloorId, out FloorCandidateInfo candidate))
                    {
                        if (!areaCache.TryGetValue(hit.FloorId, out double areaFeet))
                        {
                            Element floor = doc.GetElement(hit.FloorId.ToElementId());
                            areaFeet = GetElementPlanAreaFeet(floor);
                            areaCache[hit.FloorId] = areaFeet;
                        }

                        candidate = new FloorCandidateInfo
                        {
                            Representative = hit,
                            AreaFeet = areaFeet
                        };
                        candidates[hit.FloorId] = candidate;
                    }

                    candidate.HitCount++;
                    if (Math.Abs(hit.DistanceToBeamTopFeet) < Math.Abs(candidate.Representative.DistanceToBeamTopFeet))
                        candidate.Representative = hit;
                }
            }

            List<FloorCandidateInfo> candidateList = candidates.Values
                .Where(c => c.HitCount > 0)
                .ToList();

            int dominantHitCount = candidateList.Count == 0 ? 0 : candidateList.Max(c => c.HitCount);
            FloorCandidateInfo selected = candidateList
                .Where(c => c.HitCount == dominantHitCount)
                .OrderBy(c => c.Representative.LevelOffsetFeet ?? double.PositiveInfinity)
                .ThenByDescending(c => c.AreaFeet)
                .ThenBy(c => Math.Abs(c.Representative.DistanceToBeamTopFeet))
                .FirstOrDefault();

            if (selected == null)
                return new FloorHitInfo { HasHit = false, Message = "no-dominant-floor-hit" };

            FloorHitInfo source = selected.Representative;
            return new FloorHitInfo
            {
                HasHit = true,
                FloorId = source.FloorId,
                FloorName = source.FloorName,
                LevelId = source.LevelId,
                LevelName = source.LevelName,
                BottomZFeet = source.BottomZFeet,
                TopZFeet = source.TopZFeet,
                DistanceToBeamTopFeet = 0,
                AreaFeet = selected.AreaFeet,
                LevelOffsetFeet = source.LevelOffsetFeet,
                SampleHitCount = selected.HitCount,
                Message = "dominant_area_lowest_level_offset_by_beam"
            };
        }

        private void ResolveAutoFloorTargetsAlongBeam(
            Document doc,
            View3D detectorView,
            Curve curve,
            BeamEndpointTopInfo topInfo,
            XYZ startSample,
            XYZ endSample,
            double maxSearchDistanceMm,
            double endSampleDistanceMm,
            int beamSampleCount,
            HashSet<IdType> floorIdFilter,
            double slopeDetectionToleranceMm,
            out FloorHitInfo startFloor,
            out FloorHitInfo endFloor)
        {
            FloorHitInfo sharedTarget = FindDominantFloorBottomAlongBeam(
                doc,
                detectorView,
                curve,
                topInfo,
                maxSearchDistanceMm,
                endSampleDistanceMm,
                beamSampleCount,
                floorIdFilter);

            startFloor = CloneFloorHitWithBeamTop(sharedTarget, topInfo.StartTopZ);
            endFloor = CloneFloorHitWithBeamTop(sharedTarget, topInfo.EndTopZ);

            if (sharedTarget == null || !sharedTarget.HasHit)
                return;

            FloorHitInfo startByFloor = FindFloorBottomAtPointForFloor(
                doc,
                detectorView,
                startSample,
                topInfo.StartTopZ,
                maxSearchDistanceMm,
                sharedTarget.FloorId);

            FloorHitInfo endByFloor = FindFloorBottomAtPointForFloor(
                doc,
                detectorView,
                endSample,
                topInfo.EndTopZ,
                maxSearchDistanceMm,
                sharedTarget.FloorId);

            if (startByFloor == null || !startByFloor.HasHit || endByFloor == null || !endByFloor.HasHit)
                return;

            double slopeDeltaMm = Math.Abs(startByFloor.BottomZFeet - endByFloor.BottomZFeet) * StructuralFramingFeetToMm;
            if (slopeDeltaMm > Math.Max(0.0, slopeDetectionToleranceMm))
            {
                startByFloor.AreaFeet = sharedTarget.AreaFeet;
                startByFloor.SampleHitCount = sharedTarget.SampleHitCount;
                startByFloor.Message = $"auto_slope_endpoint_bottom(delta={Math.Round(slopeDeltaMm, 2)}mm)";

                endByFloor.AreaFeet = sharedTarget.AreaFeet;
                endByFloor.SampleHitCount = sharedTarget.SampleHitCount;
                endByFloor.Message = $"auto_slope_endpoint_bottom(delta={Math.Round(slopeDeltaMm, 2)}mm)";

                startFloor = startByFloor;
                endFloor = endByFloor;
                return;
            }

            startFloor.Message = $"auto_horizontal_dominant_bottom(delta={Math.Round(slopeDeltaMm, 2)}mm)";
            endFloor.Message = startFloor.Message;
        }

        private FloorHitInfo FindFloorBottomAtPointForFloor(
            Document doc,
            View3D detectorView,
            XYZ samplePoint,
            double beamTopZFeet,
            double maxSearchDistanceMm,
            IdType floorId)
        {
            var filter = new HashSet<IdType> { floorId };
            return CollectFloorBottomHitsAtPoint(
                    doc,
                    detectorView,
                    samplePoint,
                    beamTopZFeet,
                    maxSearchDistanceMm,
                    filter)
                .Where(hit => hit.HasHit && hit.FloorId == floorId)
                .OrderBy(hit => Math.Abs(hit.DistanceToBeamTopFeet))
                .FirstOrDefault();
        }

        private List<FloorHitInfo> CollectFloorBottomHitsAtPoint(
            Document doc,
            View3D detectorView,
            XYZ samplePoint,
            double beamTopZFeet,
            double maxSearchDistanceMm,
            HashSet<IdType> floorIdFilter)
        {
            double maxSearchFeet = maxSearchDistanceMm * StructuralFramingMmToFeet;
            XYZ origin = new XYZ(samplePoint.X, samplePoint.Y, beamTopZFeet - maxSearchFeet);
            ReferenceIntersector intersector = new ReferenceIntersector(
                new ElementCategoryFilter(BuiltInCategory.OST_Floors),
                FindReferenceTarget.Face,
                detectorView);

            IList<ReferenceWithContext> hits = intersector.Find(origin, XYZ.BasisZ);
            var results = new List<FloorHitInfo>();
            if (hits == null || hits.Count == 0)
                return CollectGeometryFloorBottomHitsAtPoint(doc, samplePoint, beamTopZFeet, maxSearchDistanceMm, floorIdFilter);

            var seen = new HashSet<IdType>();
            foreach (ReferenceWithContext hit in hits.OrderBy(h => h.Proximity))
            {
                Reference reference = hit.GetReference();
                if (reference == null) continue;

                IdType floorId = reference.ElementId.GetIdValue();
                if (seen.Contains(floorId))
                    continue;

                if (floorIdFilter != null && floorIdFilter.Count > 0 && !floorIdFilter.Contains(floorId))
                    continue;

                Element floor = doc.GetElement(reference.ElementId);
                if (floor == null) continue;

                double hitZ = reference.GlobalPoint != null
                    ? reference.GlobalPoint.Z
                    : origin.Z + hit.Proximity;

                double deltaFromTop = hitZ - beamTopZFeet;
                if (Math.Abs(deltaFromTop) > maxSearchFeet)
                    continue;

                bool normalKnown;
                bool isBottomFace = IsLikelyBottomFace(floor, reference, out normalKnown);
                if (!isBottomFace && normalKnown)
                    continue;

                if (!isBottomFace)
                {
                    BoundingBoxXYZ bbox = floor.get_BoundingBox(null);
                    if (bbox == null)
                        continue;

                    hitZ = bbox.Min.Z;
                    deltaFromTop = hitZ - beamTopZFeet;
                    if (Math.Abs(deltaFromTop) > maxSearchFeet)
                        continue;
                }

                ElementId floorLevelId = GetElementReferenceLevelId(doc, floor);
                var floorHit = new FloorHitInfo
                {
                    HasHit = true,
                    FloorId = floorId,
                    FloorName = floor.Name ?? "",
                    LevelId = floorLevelId.GetIdValue(),
                    LevelName = GetLevelName(doc, floorLevelId),
                    BottomZFeet = hitZ,
                    DistanceToBeamTopFeet = deltaFromTop,
                    LevelOffsetFeet = GetFloorBottomLevelOffsetFeet(doc, floorLevelId, hitZ),
                    Message = normalKnown ? "sample_bottom_face" : "sample_bottom_bbox"
                };
                PopulateFloorTopInfo(floorHit, floor, samplePoint, beamTopZFeet, 50.0 * StructuralFramingMmToFeet);
                results.Add(floorHit);
                seen.Add(floorId);
            }

            if (results.Count == 0)
            {
                results.AddRange(CollectGeometryFloorBottomHitsAtPoint(
                    doc,
                    samplePoint,
                    beamTopZFeet,
                    maxSearchDistanceMm,
                    floorIdFilter));
            }

            return results;
        }

        private List<FloorHitInfo> CollectGeometryFloorBottomHitsAtPoint(
            Document doc,
            XYZ samplePoint,
            double beamTopZFeet,
            double maxSearchDistanceMm,
            HashSet<IdType> floorIdFilter)
        {
            double maxSearchFeet = maxSearchDistanceMm * StructuralFramingMmToFeet;
            double xyToleranceFeet = 50.0 * StructuralFramingMmToFeet;
            var results = new List<FloorHitInfo>();

            IEnumerable<Element> floors = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Floors)
                .WhereElementIsNotElementType()
                .ToElements();

            foreach (Element floor in floors)
            {
                IdType floorId = floor.Id.GetIdValue();
                if (floorIdFilter != null && floorIdFilter.Count > 0 && !floorIdFilter.Contains(floorId))
                    continue;

                FloorHitInfo hit = TryGetFloorGeometryHit(doc, floor, samplePoint, beamTopZFeet, maxSearchFeet, xyToleranceFeet);
                if (hit != null)
                    results.Add(hit);
            }

            return results;
        }

        private FloorHitInfo TryGetFloorGeometryHit(
            Document doc,
            Element floor,
            XYZ samplePoint,
            double beamTopZFeet,
            double maxSearchFeet,
            double xyToleranceFeet)
        {
            double? bottomZ = TryGetFloorBottomZFromHorizontalFaces(floor, samplePoint, xyToleranceFeet);
            string message = "geometry-bottom-face";

            if (!bottomZ.HasValue)
            {
                BoundingBoxXYZ bbox = floor.get_BoundingBox(null);
                if (bbox == null || !PointInsideBoxXY(samplePoint, bbox, xyToleranceFeet))
                    return null;

                bottomZ = bbox.Min.Z;
                message = "geometry-bounding-box";
            }

            double deltaFromTop = bottomZ.Value - beamTopZFeet;
            if (Math.Abs(deltaFromTop) > maxSearchFeet)
                return null;

            ElementId floorLevelId = GetElementReferenceLevelId(doc, floor);
            var result = new FloorHitInfo
            {
                HasHit = true,
                FloorId = floor.Id.GetIdValue(),
                FloorName = floor.Name ?? "",
                LevelId = floorLevelId.GetIdValue(),
                LevelName = GetLevelName(doc, floorLevelId),
                BottomZFeet = bottomZ.Value,
                DistanceToBeamTopFeet = deltaFromTop,
                LevelOffsetFeet = GetFloorBottomLevelOffsetFeet(doc, floorLevelId, bottomZ.Value),
                Message = message
            };

            PopulateFloorTopInfo(result, floor, samplePoint, beamTopZFeet, xyToleranceFeet);
            return result;
        }

        private double? TryGetFloorBottomZFromHorizontalFaces(Element floor, XYZ samplePoint, double xyToleranceFeet)
        {
            var coveredBottomFaces = new List<double>();

            try
            {
                Options options = new Options
                {
                    DetailLevel = ViewDetailLevel.Fine,
                    IncludeNonVisibleObjects = false
                };

                GeometryElement geometry = floor.get_Geometry(options);
                CollectFloorBottomFaceHits(geometry, Transform.Identity, samplePoint, xyToleranceFeet, coveredBottomFaces);
            }
            catch
            {
                coveredBottomFaces.Clear();
            }

            return coveredBottomFaces.Count == 0 ? (double?)null : coveredBottomFaces.Min();
        }

        private double? TryGetFloorTopZFromHorizontalFaces(Element floor, XYZ samplePoint, double xyToleranceFeet)
        {
            var coveredTopFaces = new List<double>();

            try
            {
                Options options = new Options
                {
                    DetailLevel = ViewDetailLevel.Fine,
                    IncludeNonVisibleObjects = false
                };

                GeometryElement geometry = floor.get_Geometry(options);
                CollectFloorTopFaceHits(geometry, Transform.Identity, samplePoint, xyToleranceFeet, coveredTopFaces);
            }
            catch
            {
                coveredTopFaces.Clear();
            }

            return coveredTopFaces.Count == 0 ? (double?)null : coveredTopFaces.Max();
        }

        private void CollectFloorBottomFaceHits(
            GeometryElement geometry,
            Transform transform,
            XYZ samplePoint,
            double xyToleranceFeet,
            List<double> bottomZValues)
        {
            if (geometry == null) return;

            foreach (GeometryObject obj in geometry)
            {
                if (obj is Solid solid && solid.Faces.Size > 0)
                {
                    foreach (Face face in solid.Faces)
                    {
                        BoundingBoxUV faceBox = face.GetBoundingBox();
                        UV center = new UV(
                            (faceBox.Min.U + faceBox.Max.U) / 2.0,
                            (faceBox.Min.V + faceBox.Max.V) / 2.0);

                        XYZ normal = transform.OfVector(face.ComputeNormal(center));
                        if (normal.Z > -0.2)
                            continue;

                        Mesh mesh = face.Triangulate();
                        for (int i = 0; i < mesh.NumTriangles; i++)
                        {
                            MeshTriangle triangle = mesh.get_Triangle(i);
                            XYZ a = transform.OfPoint(triangle.get_Vertex(0));
                            XYZ b = transform.OfPoint(triangle.get_Vertex(1));
                            XYZ c = transform.OfPoint(triangle.get_Vertex(2));

                            double? localZ = TryInterpolateTriangleZAtXY(samplePoint, a, b, c, xyToleranceFeet);
                            if (localZ.HasValue)
                            {
                                bottomZValues.Add(localZ.Value);
                                break;
                            }
                        }
                    }
                }
                else if (obj is GeometryInstance instance)
                {
                    CollectFloorBottomFaceHits(
                        instance.GetInstanceGeometry(),
                        transform.Multiply(instance.Transform),
                        samplePoint,
                        xyToleranceFeet,
                        bottomZValues);
                }
            }
        }

        private void CollectFloorTopFaceHits(
            GeometryElement geometry,
            Transform transform,
            XYZ samplePoint,
            double xyToleranceFeet,
            List<double> topZValues)
        {
            if (geometry == null) return;

            foreach (GeometryObject obj in geometry)
            {
                if (obj is Solid solid && solid.Faces.Size > 0)
                {
                    foreach (Face face in solid.Faces)
                    {
                        BoundingBoxUV faceBox = face.GetBoundingBox();
                        UV center = new UV(
                            (faceBox.Min.U + faceBox.Max.U) / 2.0,
                            (faceBox.Min.V + faceBox.Max.V) / 2.0);

                        XYZ normal = transform.OfVector(face.ComputeNormal(center));
                        if (normal.Z < 0.2)
                            continue;

                        Mesh mesh = face.Triangulate();
                        for (int i = 0; i < mesh.NumTriangles; i++)
                        {
                            MeshTriangle triangle = mesh.get_Triangle(i);
                            XYZ a = transform.OfPoint(triangle.get_Vertex(0));
                            XYZ b = transform.OfPoint(triangle.get_Vertex(1));
                            XYZ c = transform.OfPoint(triangle.get_Vertex(2));

                            double? localZ = TryInterpolateTriangleZAtXY(samplePoint, a, b, c, xyToleranceFeet);
                            if (localZ.HasValue)
                            {
                                topZValues.Add(localZ.Value);
                                break;
                            }
                        }
                    }
                }
                else if (obj is GeometryInstance instance)
                {
                    CollectFloorTopFaceHits(
                        instance.GetInstanceGeometry(),
                        transform.Multiply(instance.Transform),
                        samplePoint,
                        xyToleranceFeet,
                        topZValues);
                }
            }
        }

        private bool PointInsideBoxXY(XYZ point, BoundingBoxXYZ box, double toleranceFeet)
        {
            return point.X >= box.Min.X - toleranceFeet
                && point.X <= box.Max.X + toleranceFeet
                && point.Y >= box.Min.Y - toleranceFeet
                && point.Y <= box.Max.Y + toleranceFeet;
        }

        private double? TryInterpolateTriangleZAtXY(XYZ p, XYZ a, XYZ b, XYZ c, double toleranceFeet)
        {
            if (!PointInTriangleXY(p, a, b, c, toleranceFeet))
                return null;

            XYZ ab = b - a;
            XYZ ac = c - a;
            XYZ normal = ab.CrossProduct(ac);
            if (Math.Abs(normal.Z) < 1e-9)
                return (a.Z + b.Z + c.Z) / 3.0;

            return a.Z - ((normal.X * (p.X - a.X)) + (normal.Y * (p.Y - a.Y))) / normal.Z;
        }

        private bool PointInTriangleXY(XYZ p, XYZ a, XYZ b, XYZ c, double toleranceFeet)
        {
            if (!PointInsideTriangleBoundingBoxXY(p, a, b, c, toleranceFeet))
                return false;

            double denominator = ((b.Y - c.Y) * (a.X - c.X)) + ((c.X - b.X) * (a.Y - c.Y));
            if (Math.Abs(denominator) < 1e-9)
                return DistancePointToSegmentXY(p, a, b) <= toleranceFeet
                    || DistancePointToSegmentXY(p, b, c) <= toleranceFeet
                    || DistancePointToSegmentXY(p, c, a) <= toleranceFeet;

            double alpha = (((b.Y - c.Y) * (p.X - c.X)) + ((c.X - b.X) * (p.Y - c.Y))) / denominator;
            double beta = (((c.Y - a.Y) * (p.X - c.X)) + ((a.X - c.X) * (p.Y - c.Y))) / denominator;
            double gamma = 1.0 - alpha - beta;
            double tolerance = Math.Max(1e-7, toleranceFeet / Math.Max(GetTriangleMaxEdgeLengthXY(a, b, c), 1e-6));

            return alpha >= -tolerance && beta >= -tolerance && gamma >= -tolerance;
        }

        private bool PointInsideTriangleBoundingBoxXY(XYZ p, XYZ a, XYZ b, XYZ c, double toleranceFeet)
        {
            double minX = Math.Min(a.X, Math.Min(b.X, c.X)) - toleranceFeet;
            double maxX = Math.Max(a.X, Math.Max(b.X, c.X)) + toleranceFeet;
            double minY = Math.Min(a.Y, Math.Min(b.Y, c.Y)) - toleranceFeet;
            double maxY = Math.Max(a.Y, Math.Max(b.Y, c.Y)) + toleranceFeet;
            return p.X >= minX && p.X <= maxX && p.Y >= minY && p.Y <= maxY;
        }

        private double GetTriangleMaxEdgeLengthXY(XYZ a, XYZ b, XYZ c)
        {
            return Math.Max(
                DistanceXY(a, b),
                Math.Max(DistanceXY(b, c), DistanceXY(c, a)));
        }

        private double DistanceXY(XYZ a, XYZ b)
        {
            double dx = a.X - b.X;
            double dy = a.Y - b.Y;
            return Math.Sqrt(dx * dx + dy * dy);
        }

        private double DistancePointToSegmentXY(XYZ p, XYZ a, XYZ b)
        {
            double dx = b.X - a.X;
            double dy = b.Y - a.Y;
            double lengthSquared = dx * dx + dy * dy;
            if (lengthSquared < 1e-12)
                return DistanceXY(p, a);

            double t = ((p.X - a.X) * dx + (p.Y - a.Y) * dy) / lengthSquared;
            t = Math.Max(0, Math.Min(1, t));
            XYZ projection = new XYZ(a.X + t * dx, a.Y + t * dy, 0);
            return DistanceXY(new XYZ(p.X, p.Y, 0), projection);
        }

        private double GetElementPlanAreaFeet(Element element)
        {
            if (element == null)
                return 0;

            Parameter areaParameter = element.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED);
            if (areaParameter != null && areaParameter.StorageType == StorageType.Double)
            {
                double area = areaParameter.AsDouble();
                if (area > 0)
                    return area;
            }

            double bestHorizontalFaceArea = 0;
            try
            {
                Options options = new Options
                {
                    DetailLevel = ViewDetailLevel.Fine,
                    IncludeNonVisibleObjects = false
                };
                GeometryElement geometry = element.get_Geometry(options);
                foreach (GeometryObject obj in geometry)
                {
                    Solid solid = obj as Solid;
                    if (solid == null || solid.Faces == null) continue;

                    foreach (Face face in solid.Faces)
                    {
                        BoundingBoxUV bbox = face.GetBoundingBox();
                        UV center = new UV(
                            (bbox.Min.U + bbox.Max.U) / 2.0,
                            (bbox.Min.V + bbox.Max.V) / 2.0);

                        XYZ normal = face.ComputeNormal(center);
                        if (Math.Abs(normal.Z) > 0.5 && face.Area > bestHorizontalFaceArea)
                            bestHorizontalFaceArea = face.Area;
                    }
                }
            }
            catch
            {
                bestHorizontalFaceArea = 0;
            }

            if (bestHorizontalFaceArea > 0)
                return bestHorizontalFaceArea;

            BoundingBoxXYZ box = element.get_BoundingBox(null);
            if (box == null)
                return 0;

            return Math.Max(0, box.Max.X - box.Min.X) * Math.Max(0, box.Max.Y - box.Min.Y);
        }

        private bool IsLikelyBottomFace(Element element, Reference reference, out bool normalKnown)
        {
            normalKnown = false;

            try
            {
                GeometryObject geometryObject = element.GetGeometryObjectFromReference(reference);
                Face face = geometryObject as Face;
                if (face == null) return true;

                BoundingBoxUV bbox = face.GetBoundingBox();
                UV center = new UV(
                    (bbox.Min.U + bbox.Max.U) / 2.0,
                    (bbox.Min.V + bbox.Max.V) / 2.0);

                XYZ normal = face.ComputeNormal(center);
                normalKnown = true;
                return normal.Z < -0.2;
            }
            catch
            {
                return true;
            }
        }

        private bool IsStructuralFramingElement(Element element)
        {
            return element?.Category != null &&
                   element.Category.GetBuiltInCategory() == BuiltInCategory.OST_StructuralFraming;
        }

        private bool ElementMatchesLevel(Document doc, Element element, string levelName)
        {
            string normalized = levelName.Trim();

            Level level = null;
            if (element.LevelId != ElementId.InvalidElementId)
                level = doc.GetElement(element.LevelId) as Level;

            if (level != null && level.Name.IndexOf(normalized, StringComparison.OrdinalIgnoreCase) >= 0)
                return true;

            Parameter referenceLevelParam = element.get_Parameter(BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM);
            if (referenceLevelParam != null)
            {
                string value = referenceLevelParam.AsValueString() ?? "";
                if (value.IndexOf(normalized, StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;

                ElementId levelId = referenceLevelParam.AsElementId();
                Level parameterLevel = doc.GetElement(levelId) as Level;
                if (parameterLevel != null && parameterLevel.Name.IndexOf(normalized, StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
            }

            return false;
        }

        private Parameter FindWritableParameter(Element element, List<string> names, out string matchedName)
        {
            matchedName = null;
            foreach (string name in names)
            {
                Parameter parameter = element.LookupParameter(name);
                if (parameter != null)
                {
                    matchedName = name;
                    if (!parameter.IsReadOnly) return parameter;
                }
            }

            return null;
        }

        private List<string> GetParameterNameList(JArray names, params string[] defaults)
        {
            var result = new List<string>();
            if (names != null)
            {
                foreach (JToken token in names)
                {
                    string value = token.Value<string>();
                    if (!string.IsNullOrWhiteSpace(value)) result.Add(value.Trim());
                }
            }

            foreach (string value in defaults)
            {
                if (!result.Any(x => x.Equals(value, StringComparison.OrdinalIgnoreCase)))
                    result.Add(value);
            }

            return result;
        }

        private HashSet<IdType> ReadIdSet(JArray ids)
        {
            if (ids == null || ids.Count == 0) return null;
            return new HashSet<IdType>(ids.Select(id => id.Value<IdType>()));
        }

        private class BeamAlignmentBuildResult
        {
            public List<BeamAlignmentPlan> Plans { get; } = new List<BeamAlignmentPlan>();
            public List<object> Skipped { get; } = new List<object>();
        }

        private class BeamJoinDisallowResult
        {
            public int AttemptedCount { get; set; }
            public int ChangedCount { get; set; }
            public int FailedCount { get; set; }
            public List<object> Failures { get; } = new List<object>();

            public object ToResult()
            {
                return new
                {
                    AttemptedCount,
                    ChangedCount,
                    FailedCount,
                    Failures
                };
            }
        }

        private class BeamResidualProbe
        {
            public IdType BeamId { get; set; }
            public IdType FloorId { get; set; }
            public double MaxResidualFeet { get; set; }
            public double SampleT { get; set; }
            public double BeamTopZFeet { get; set; }
            public double FloorBottomZFeet { get; set; }
        }

        private class BeamEndpointTopInfo
        {
            public bool HasStartTop { get; set; }
            public bool HasEndTop { get; set; }
            public double StartTopZ { get; set; }
            public double EndTopZ { get; set; }
        }

        private class FloorHitInfo
        {
            public bool HasHit { get; set; }
            public IdType FloorId { get; set; }
            public string FloorName { get; set; }
            public IdType? LevelId { get; set; }
            public string LevelName { get; set; }
            public double BottomZFeet { get; set; }
            public double? TopZFeet { get; set; }
            public double DistanceToBeamTopFeet { get; set; }
            public double? BeamTopAboveFloorTopFeet { get; set; }
            public double AreaFeet { get; set; }
            public double? LevelOffsetFeet { get; set; }
            public int SampleHitCount { get; set; }
            public string Message { get; set; }

            public object ToResult()
            {
                return new
                {
                    HasHit,
                    FloorId = HasHit ? (object)FloorId : null,
                    FloorName,
                    LevelId,
                    LevelName,
                    BottomZMm = HasHit ? (object)Math.Round(BottomZFeet * StructuralFramingFeetToMm, 2) : null,
                    TopZMm = HasHit && TopZFeet.HasValue ? (object)Math.Round(TopZFeet.Value * StructuralFramingFeetToMm, 2) : null,
                    DeltaToBeamTopMm = HasHit ? (object)Math.Round(DistanceToBeamTopFeet * StructuralFramingFeetToMm, 2) : null,
                    BeamTopAboveFloorBottomMm = HasHit ? (object)Math.Round(-DistanceToBeamTopFeet * StructuralFramingFeetToMm, 2) : null,
                    BeamTopAboveFloorTopMm = HasHit && BeamTopAboveFloorTopFeet.HasValue ? (object)Math.Round(BeamTopAboveFloorTopFeet.Value * StructuralFramingFeetToMm, 2) : null,
                    AreaM2 = HasHit && AreaFeet > 0 ? (object)Math.Round(AreaFeet * 0.09290304, 2) : null,
                    LevelOffsetMm = HasHit && LevelOffsetFeet.HasValue ? (object)Math.Round(LevelOffsetFeet.Value * StructuralFramingFeetToMm, 2) : null,
                    SampleHitCount = HasHit && SampleHitCount > 0 ? (object)SampleHitCount : null,
                    Message
                };
            }
        }

        private class FloorCandidateInfo
        {
            public FloorHitInfo Representative { get; set; }
            public int HitCount { get; set; }
            public double AreaFeet { get; set; }
        }

        private class BeamAlignmentPlan
        {
            public IdType BeamId { get; set; }
            public string BeamName { get; set; }
            public string BeamTypeName { get; set; }
            public bool CanApply { get; set; }
            public bool Applied { get; set; }
            public string SkipReason { get; set; }
            public bool PreserveVerticalStack { get; set; }
            public string StackGroupKey { get; set; }
            public IdType? StackControllerBeamId { get; set; }
            public Parameter StartParameter { get; set; }
            public Parameter EndParameter { get; set; }
            public string StartParameterName { get; set; }
            public string EndParameterName { get; set; }
            public double OldStartOffsetFeet { get; set; }
            public double OldEndOffsetFeet { get; set; }
            public double? StartDeltaFeet { get; set; }
            public double? EndDeltaFeet { get; set; }
            public double StartBeamTopZFeet { get; set; }
            public double EndBeamTopZFeet { get; set; }
            public XYZ StartSamplePoint { get; set; }
            public XYZ EndSamplePoint { get; set; }
            public FloorHitInfo StartFloor { get; set; }
            public FloorHitInfo EndFloor { get; set; }
            public double? PostGeometryMaxResidualFeet { get; set; }
            public double? PostGeometryCorrectionFeet { get; set; }
            public double? PostGeometryWorstSampleT { get; set; }

            public object ToResult()
            {
                return new
                {
                    BeamId,
                    BeamName,
                    BeamTypeName,
                    CanApply,
                    Applied,
                    SkipReason,
                    PreserveVerticalStack,
                    StackGroupKey,
                    StackControllerBeamId,
                    StartParameterName,
                    EndParameterName,
                    OldStartOffsetMm = Math.Round(OldStartOffsetFeet * StructuralFramingFeetToMm, 2),
                    OldEndOffsetMm = Math.Round(OldEndOffsetFeet * StructuralFramingFeetToMm, 2),
                    StartDeltaMm = StartDeltaFeet.HasValue ? (object)Math.Round(StartDeltaFeet.Value * StructuralFramingFeetToMm, 2) : null,
                    EndDeltaMm = EndDeltaFeet.HasValue ? (object)Math.Round(EndDeltaFeet.Value * StructuralFramingFeetToMm, 2) : null,
                    NewStartOffsetMm = StartDeltaFeet.HasValue ? (object)Math.Round((OldStartOffsetFeet + StartDeltaFeet.Value) * StructuralFramingFeetToMm, 2) : null,
                    NewEndOffsetMm = EndDeltaFeet.HasValue ? (object)Math.Round((OldEndOffsetFeet + EndDeltaFeet.Value) * StructuralFramingFeetToMm, 2) : null,
                    PostGeometryMaxResidualMm = PostGeometryMaxResidualFeet.HasValue ? (object)Math.Round(PostGeometryMaxResidualFeet.Value * StructuralFramingFeetToMm, 2) : null,
                    PostGeometryCorrectionMm = PostGeometryCorrectionFeet.HasValue ? (object)Math.Round(PostGeometryCorrectionFeet.Value * StructuralFramingFeetToMm, 2) : null,
                    PostGeometryWorstSampleT = PostGeometryWorstSampleT.HasValue ? (object)Math.Round(PostGeometryWorstSampleT.Value, 3) : null,
                    StartBeamTopZMm = Math.Round(StartBeamTopZFeet * StructuralFramingFeetToMm, 2),
                    EndBeamTopZMm = Math.Round(EndBeamTopZFeet * StructuralFramingFeetToMm, 2),
                    StartSample = StartSamplePoint == null ? null : new
                    {
                        X = Math.Round(StartSamplePoint.X * StructuralFramingFeetToMm, 2),
                        Y = Math.Round(StartSamplePoint.Y * StructuralFramingFeetToMm, 2),
                        Z = Math.Round(StartSamplePoint.Z * StructuralFramingFeetToMm, 2)
                    },
                    EndSample = EndSamplePoint == null ? null : new
                    {
                        X = Math.Round(EndSamplePoint.X * StructuralFramingFeetToMm, 2),
                        Y = Math.Round(EndSamplePoint.Y * StructuralFramingFeetToMm, 2),
                        Z = Math.Round(EndSamplePoint.Z * StructuralFramingFeetToMm, 2)
                    },
                    StartFloor = StartFloor?.ToResult(),
                    EndFloor = EndFloor?.ToResult()
                };
            }
        }
    }
}
