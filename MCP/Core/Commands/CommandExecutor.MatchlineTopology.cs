using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;

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
        /// CropBox 的 Min/Max 位於各自 BoundingBoxXYZ.Transform 的局部座標。
        /// 先轉到模型座標，再轉回母視圖 CropBox 座標，所有相鄰判定才可比較。
        /// </summary>
        private bool TryNormalizeDependentCropBox(
            View view,
            BoundingBoxXYZ bbox,
            string sheetLabel,
            Transform primaryInverse,
            out DependentViewData data,
            out string error)
        {
            data = null;
            error = null;

            if (bbox == null || bbox.Transform == null)
            {
                error = $"從屬視圖「{view.Name}」沒有可用的 CropBox；已保留既有銜接線。";
                return false;
            }

            double z = bbox.Min.Z;
            XYZ[] localCorners =
            {
                new XYZ(bbox.Min.X, bbox.Min.Y, z),
                new XYZ(bbox.Max.X, bbox.Min.Y, z),
                new XYZ(bbox.Min.X, bbox.Max.Y, z),
                new XYZ(bbox.Max.X, bbox.Max.Y, z)
            };
            XYZ[] primaryCorners = localCorners
                .Select(point => primaryInverse.OfPoint(bbox.Transform.OfPoint(point)))
                .ToArray();

            XYZ localXEdge = primaryCorners[1].Subtract(primaryCorners[0]);
            XYZ localYEdge = primaryCorners[2].Subtract(primaryCorners[0]);
            double edgeScale = Math.Max(localXEdge.GetLength(), localYEdge.GetLength());
            double alignmentTolerance = Math.Max(1e-6, edgeScale * 1e-8);
            bool isAxisAligned = Math.Abs(localXEdge.Y) <= alignmentTolerance
                && Math.Abs(localYEdge.X) <= alignmentTolerance;
            if (!isAxisAligned)
            {
                error = $"從屬視圖「{view.Name}」的 CropBox 未與母視圖座標軸對齊；為避免錯誤配對，已保留既有銜接線。";
                return false;
            }

            data = new DependentViewData
            {
                View = view,
                SheetLabel = sheetLabel,
                MinU = primaryCorners.Min(point => point.X),
                MaxU = primaryCorners.Max(point => point.X),
                MinV = primaryCorners.Min(point => point.Y),
                MaxV = primaryCorners.Max(point => point.Y)
            };
            return true;
        }

        /// <summary>
        /// 每個視圖分別從西、東、南、北四邊提出候選。候選必須有足夠的
        /// 垂直投影重疊，且兩個 facing edge 的中線須位於兩個視圖中心之間。
        /// </summary>
        private List<MatchlineSideClaim> BuildMatchlineSideClaims(
            List<DependentViewData> views,
            double adjacencyTolerance,
            double shortCurveTolerance)
        {
            var claims = new List<MatchlineSideClaim>();
            MatchlineSide[] sides =
            {
                MatchlineSide.West,
                MatchlineSide.East,
                MatchlineSide.South,
                MatchlineSide.North
            };

            foreach (DependentViewData source in views)
            {
                foreach (DependentViewData target in views)
                {
                    if (source.View.Id.GetIdValue() == target.View.Id.GetIdValue())
                        continue;
                    if (RectanglesAreNested(source, target, shortCurveTolerance))
                        continue;

                    foreach (MatchlineSide side in sides)
                    {
                        MatchlineSideClaim claim;
                        if (TryBuildMatchlineSideClaim(
                            source, target, side, adjacencyTolerance,
                            shortCurveTolerance, out claim))
                        {
                            claims.Add(claim);
                        }
                    }
                }
            }

            return claims;
        }

        private bool TryBuildMatchlineSideClaim(
            DependentViewData source,
            DependentViewData target,
            MatchlineSide side,
            double adjacencyTolerance,
            double shortCurveTolerance,
            out MatchlineSideClaim claim)
        {
            claim = null;
            double centerTolerance = Math.Max(shortCurveTolerance, 1e-6);
            double minAlong;
            double maxAlong;
            double boundary;
            double normalDistance;
            double facingDistance;
            double positiveGap;
            double sourceAlongCenter;
            double targetAlongCenter;

            switch (side)
            {
                case MatchlineSide.East:
                    if (target.CenterU <= source.CenterU + centerTolerance) return false;
                    minAlong = Math.Max(source.MinV, target.MinV);
                    maxAlong = Math.Min(source.MaxV, target.MaxV);
                    boundary = (source.MaxU + target.MinU) / 2.0;
                    normalDistance = target.CenterU - source.CenterU;
                    facingDistance = Math.Abs(target.MinU - source.MaxU);
                    positiveGap = target.MinU - source.MaxU;
                    sourceAlongCenter = source.CenterV;
                    targetAlongCenter = target.CenterV;
                    if (boundary <= source.CenterU + centerTolerance
                        || boundary >= target.CenterU - centerTolerance) return false;
                    break;

                case MatchlineSide.West:
                    if (target.CenterU >= source.CenterU - centerTolerance) return false;
                    minAlong = Math.Max(source.MinV, target.MinV);
                    maxAlong = Math.Min(source.MaxV, target.MaxV);
                    boundary = (source.MinU + target.MaxU) / 2.0;
                    normalDistance = source.CenterU - target.CenterU;
                    facingDistance = Math.Abs(source.MinU - target.MaxU);
                    positiveGap = source.MinU - target.MaxU;
                    sourceAlongCenter = source.CenterV;
                    targetAlongCenter = target.CenterV;
                    if (boundary >= source.CenterU - centerTolerance
                        || boundary <= target.CenterU + centerTolerance) return false;
                    break;

                case MatchlineSide.North:
                    if (target.CenterV <= source.CenterV + centerTolerance) return false;
                    minAlong = Math.Max(source.MinU, target.MinU);
                    maxAlong = Math.Min(source.MaxU, target.MaxU);
                    boundary = (source.MaxV + target.MinV) / 2.0;
                    normalDistance = target.CenterV - source.CenterV;
                    facingDistance = Math.Abs(target.MinV - source.MaxV);
                    positiveGap = target.MinV - source.MaxV;
                    sourceAlongCenter = source.CenterU;
                    targetAlongCenter = target.CenterU;
                    if (boundary <= source.CenterV + centerTolerance
                        || boundary >= target.CenterV - centerTolerance) return false;
                    break;

                default: // South
                    if (target.CenterV >= source.CenterV - centerTolerance) return false;
                    minAlong = Math.Max(source.MinU, target.MinU);
                    maxAlong = Math.Min(source.MaxU, target.MaxU);
                    boundary = (source.MinV + target.MaxV) / 2.0;
                    normalDistance = source.CenterV - target.CenterV;
                    facingDistance = Math.Abs(source.MinV - target.MaxV);
                    positiveGap = source.MinV - target.MaxV;
                    sourceAlongCenter = source.CenterU;
                    targetAlongCenter = target.CenterU;
                    if (boundary >= source.CenterV - centerTolerance
                        || boundary <= target.CenterV + centerTolerance) return false;
                    break;
            }

            if (positiveGap > adjacencyTolerance) return false;
            if (maxAlong - minAlong <= shortCurveTolerance) return false;

            // 對角視圖通常只在四角形成短重疊，不會包含任一視圖的中心線。
            bool containsSourceCenter = sourceAlongCenter >= minAlong - centerTolerance
                && sourceAlongCenter <= maxAlong + centerTolerance;
            bool containsTargetCenter = targetAlongCenter >= minAlong - centerTolerance
                && targetAlongCenter <= maxAlong + centerTolerance;
            if (!containsSourceCenter && !containsTargetCenter) return false;

            claim = new MatchlineSideClaim
            {
                Source = source,
                Target = target,
                Side = side,
                MinAlong = minAlong,
                MaxAlong = maxAlong,
                Boundary = boundary,
                NormalDistance = normalDistance,
                FacingDistance = facingDistance
            };
            return true;
        }

        private bool RectanglesAreNested(
            DependentViewData first,
            DependentViewData second,
            double tolerance)
        {
            return RectangleContains(first, second, tolerance)
                || RectangleContains(second, first, tolerance);
        }

        private bool RectangleContains(
            DependentViewData outer,
            DependentViewData inner,
            double tolerance)
        {
            return outer.MinU <= inner.MinU + tolerance
                && outer.MaxU >= inner.MaxU - tolerance
                && outer.MinV <= inner.MinV + tolerance
                && outer.MaxV >= inner.MaxV - tolerance;
        }

        /// <summary>
        /// 將同一視圖同一側的所有候選端點切成原子區段。每段只交給法向
        /// 中心距離最近的目標，故中間視圖只會遮蔽其實際覆蓋的部分。
        /// </summary>
        private List<OwnedMatchlineSpan> SelectOwnedMatchlineSpans(
            List<MatchlineSideClaim> claims,
            double shortCurveTolerance)
        {
            var owned = new List<OwnedMatchlineSpan>();
            double mergeTolerance = Math.Max(shortCurveTolerance, 1e-6);

            var groups = claims.GroupBy(item => new
            {
                SourceId = item.Source.View.Id.GetIdValue(),
                item.Side
            });

            foreach (var group in groups)
            {
                var groupClaims = group.ToList();
                var partitionValues = groupClaims
                    .SelectMany(item => new[] { item.MinAlong, item.MaxAlong })
                    .ToList();

                // 同一外向距離上若有兩個上下／左右相鄰視圖，其投影可能互相
                // 重疊。加入兩個目標中心的垂直平分點，讓重疊帶分別歸給
                // 距離該區段較近的視圖，而不是整段由 ElementId 決勝。
                for (int firstIndex = 0;
                    firstIndex < groupClaims.Count; firstIndex++)
                {
                    for (int secondIndex = firstIndex + 1;
                        secondIndex < groupClaims.Count; secondIndex++)
                    {
                        MatchlineSideClaim first = groupClaims[firstIndex];
                        MatchlineSideClaim second = groupClaims[secondIndex];
                        if (Math.Abs(first.NormalDistance - second.NormalDistance)
                            > mergeTolerance)
                        {
                            continue;
                        }

                        double overlapMin = Math.Max(
                            first.MinAlong, second.MinAlong);
                        double overlapMax = Math.Min(
                            first.MaxAlong, second.MaxAlong);
                        if (overlapMax - overlapMin <= shortCurveTolerance)
                            continue;

                        double bisector = (TargetAlongCenter(first)
                            + TargetAlongCenter(second)) / 2.0;
                        if (bisector > overlapMin + mergeTolerance
                            && bisector < overlapMax - mergeTolerance)
                        {
                            partitionValues.Add(bisector);
                        }
                    }
                }

                List<double> endpoints = UniqueSortedValues(
                    partitionValues, mergeTolerance);
                OwnedMatchlineSpan previous = null;

                for (int index = 0; index < endpoints.Count - 1; index++)
                {
                    double minAlong = endpoints[index];
                    double maxAlong = endpoints[index + 1];
                    if (maxAlong - minAlong <= shortCurveTolerance) continue;

                    double midpoint = (minAlong + maxAlong) / 2.0;
                    MatchlineSideClaim winner = groupClaims
                        .Where(item => item.MinAlong <= midpoint + mergeTolerance
                            && item.MaxAlong >= midpoint - mergeTolerance)
                        .OrderBy(item => item.NormalDistance)
                        .ThenBy(item => PerpendicularCenterDistance(item, midpoint))
                        .ThenBy(item => item.FacingDistance)
                        .ThenBy(item => item.Target.View.Id.GetIdValue())
                        .FirstOrDefault();
                    if (winner == null) continue;

                    if (previous != null
                        && previous.Claim.Target.View.Id.GetIdValue()
                            == winner.Target.View.Id.GetIdValue()
                        && previous.Claim.Side == winner.Side
                        && Math.Abs(previous.Claim.Boundary - winner.Boundary)
                            <= mergeTolerance
                        && minAlong <= previous.MaxAlong + mergeTolerance)
                    {
                        previous.MaxAlong = Math.Max(previous.MaxAlong, maxAlong);
                    }
                    else
                    {
                        previous = new OwnedMatchlineSpan
                        {
                            Claim = winner,
                            MinAlong = minAlong,
                            MaxAlong = maxAlong
                        };
                        owned.Add(previous);
                    }
                }
            }

            return owned;
        }

        private double PerpendicularCenterDistance(
            MatchlineSideClaim claim, double alongCoordinate)
        {
            return Math.Abs(TargetAlongCenter(claim) - alongCoordinate);
        }

        private double TargetAlongCenter(MatchlineSideClaim claim)
        {
            return claim.Side == MatchlineSide.East
                || claim.Side == MatchlineSide.West
                ? claim.Target.CenterV
                : claim.Target.CenterU;
        }

        private List<double> UniqueSortedValues(
            IEnumerable<double> values, double tolerance)
        {
            var result = new List<double>();
            foreach (double value in values.OrderBy(item => item))
            {
                if (result.Count == 0
                    || Math.Abs(value - result[result.Count - 1]) > tolerance)
                {
                    result.Add(value);
                }
            }
            return result;
        }

        /// <summary>
        /// 只有 A 的東／北側與 B 的西／南側在同一區段互相選中對方，才是
        /// 真正的相鄰邊界。相連且屬於同一視圖對的區段會合併成一條線。
        /// </summary>
        private List<MatchlineCandidate> BuildMutualMatchlineCandidates(
            List<MatchlineSideClaim> claims,
            Transform primaryTransform,
            double shortCurveTolerance)
        {
            List<OwnedMatchlineSpan> owned = SelectOwnedMatchlineSpans(
                claims, shortCurveTolerance);
            var mutual = new List<MutualMatchlineSpan>();
            double tolerance = Math.Max(shortCurveTolerance, 1e-6);

            foreach (OwnedMatchlineSpan forward in owned)
            {
                if (forward.Claim.Side != MatchlineSide.East
                    && forward.Claim.Side != MatchlineSide.North)
                {
                    continue;
                }

                MatchlineSide reverseSide = forward.Claim.Side == MatchlineSide.East
                    ? MatchlineSide.West
                    : MatchlineSide.South;
                IdType sourceId = forward.Claim.Source.View.Id.GetIdValue();
                IdType targetId = forward.Claim.Target.View.Id.GetIdValue();

                foreach (OwnedMatchlineSpan reverse in owned)
                {
                    if (reverse.Claim.Side != reverseSide
                        || reverse.Claim.Source.View.Id.GetIdValue() != targetId
                        || reverse.Claim.Target.View.Id.GetIdValue() != sourceId)
                    {
                        continue;
                    }

                    double minAlong = Math.Max(forward.MinAlong, reverse.MinAlong);
                    double maxAlong = Math.Min(forward.MaxAlong, reverse.MaxAlong);
                    if (maxAlong - minAlong <= shortCurveTolerance) continue;

                    mutual.Add(new MutualMatchlineSpan
                    {
                        View1 = forward.Claim.Source,
                        View2 = forward.Claim.Target,
                        IsVertical = forward.Claim.Side == MatchlineSide.East,
                        Boundary = (forward.Claim.Boundary
                            + reverse.Claim.Boundary) / 2.0,
                        MinAlong = minAlong,
                        MaxAlong = maxAlong
                    });
                }
            }

            var merged = new List<MutualMatchlineSpan>();
            var mutualGroups = mutual.GroupBy(item => new
            {
                View1Id = item.View1.View.Id.GetIdValue(),
                View2Id = item.View2.View.Id.GetIdValue(),
                item.IsVertical
            });

            foreach (var group in mutualGroups)
            {
                MutualMatchlineSpan current = null;
                foreach (MutualMatchlineSpan span in group
                    .OrderBy(item => item.MinAlong)
                    .ThenBy(item => item.MaxAlong))
                {
                    if (current != null
                        && Math.Abs(current.Boundary - span.Boundary) <= tolerance
                        && span.MinAlong <= current.MaxAlong + tolerance)
                    {
                        current.MaxAlong = Math.Max(current.MaxAlong, span.MaxAlong);
                    }
                    else
                    {
                        current = new MutualMatchlineSpan
                        {
                            View1 = span.View1,
                            View2 = span.View2,
                            IsVertical = span.IsVertical,
                            Boundary = span.Boundary,
                            MinAlong = span.MinAlong,
                            MaxAlong = span.MaxAlong
                        };
                        merged.Add(current);
                    }
                }
            }

            return merged
                .Select(item => CreateMatchlineCandidate(
                    item, primaryTransform, shortCurveTolerance))
                .Where(item => item != null)
                .ToList();
        }

        /// <summary>
        /// View1 固定是左側或下側視圖；兩個文字固定放在最終線段幾何中點
        /// 的兩側，不因網格或其他銜接線而省略或沿線移動。
        /// </summary>
        private MatchlineCandidate CreateMatchlineCandidate(
            MutualMatchlineSpan span,
            Transform primaryTransform,
            double shortCurveTolerance)
        {
            const double textOffset = 1.2; // feet
            XYZ start;
            XYZ end;
            XYZ normal;

            if (span.IsVertical)
            {
                start = primaryTransform.OfPoint(
                    new XYZ(span.Boundary, span.MinAlong, 0));
                end = primaryTransform.OfPoint(
                    new XYZ(span.Boundary, span.MaxAlong, 0));
                normal = primaryTransform.BasisX.Normalize();
            }
            else
            {
                start = primaryTransform.OfPoint(
                    new XYZ(span.MinAlong, span.Boundary, 0));
                end = primaryTransform.OfPoint(
                    new XYZ(span.MaxAlong, span.Boundary, 0));
                normal = primaryTransform.BasisY.Normalize();
            }

            if (start.DistanceTo(end) <= shortCurveTolerance) return null;

            XYZ midpoint = start.Add(end).Divide(2.0);
            string pairKey = String.Format("{0}:{1}:{2}",
                span.IsVertical ? "V" : "H",
                span.View1.View.Id.GetIdValue(),
                span.View2.View.Id.GetIdValue());

            return new MatchlineCandidate
            {
                View1 = span.View1,
                View2 = span.View2,
                Line = Line.CreateBound(start, end),
                TextPos1 = midpoint.Subtract(normal.Multiply(textOffset)),
                TextPos2 = midpoint.Add(normal.Multiply(textOffset)),
                IsVertical = span.IsVertical,
                MinAlong = span.MinAlong,
                MaxAlong = span.MaxAlong,
                PairKey = pairKey
            };
        }
    }
}
