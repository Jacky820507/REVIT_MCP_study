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
        #region 樓板子元素高程控制（SlabShapeEditor）

        // 樓板形狀編輯的控制點上限，避免一次灌入過多點導致 Revit 無回應。
        private const int FloorShapePointLimit = 3000;

        /// <summary>
        /// 讀取樓板目前的形狀編輯控制點（子元素），回傳每個頂點的 XYZ（公釐）。
        /// 這是 set_floor_shape_points 的前置查詢：先看現況再決定要改哪些點。
        /// </summary>
        private object GetFloorShapePoints(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            long floorIdRaw = parameters["floorId"]?.Value<long>() ?? 0;
            if (floorIdRaw == 0)
                throw new Exception("必須指定 floorId");

            var floor = doc.GetElement(((IdType)floorIdRaw).ToElementId()) as Floor;
            if (floor == null)
                throw new Exception($"元素 {floorIdRaw} 不存在或不是樓板 (Floor)");

            var editor = floor.GetSlabShapeEditorCompat();
            if (editor == null)
                throw new Exception(
                    $"樓板 {floorIdRaw} 沒有可用的 SlabShapeEditor。" +
                    "此樓板可能是以斜率箭頭或結構斜板定義，需先在 Revit 中改為形狀編輯模式。");

            var vertices = new List<object>();
            foreach (SlabShapeVertex vertex in editor.SlabShapeVertices)
            {
                var position = vertex.Position;
                vertices.Add(new
                {
                    X = Math.Round(position.X * 304.8, 2),
                    Y = Math.Round(position.Y * 304.8, 2),
                    Z = Math.Round(position.Z * 304.8, 2)
                });
            }

            var boundingBox = floor.get_BoundingBox(null);

            return new
            {
                FloorId = floorIdRaw,
                TypeName = doc.GetElement(floor.GetTypeId())?.Name,
                IsShapeEditingEnabled = editor.IsEnabled,
                VertexCount = vertices.Count,
                CreaseCount = editor.SlabShapeCreases.Size,
                Extent = boundingBox == null ? null : new
                {
                    MinX = Math.Round(boundingBox.Min.X * 304.8, 2),
                    MinY = Math.Round(boundingBox.Min.Y * 304.8, 2),
                    MinZ = Math.Round(boundingBox.Min.Z * 304.8, 2),
                    MaxX = Math.Round(boundingBox.Max.X * 304.8, 2),
                    MaxY = Math.Round(boundingBox.Max.Y * 304.8, 2),
                    MaxZ = Math.Round(boundingBox.Max.Z * 304.8, 2)
                },
                Vertices = vertices
            };
        }

        /// <summary>
        /// 依指定的 (x, y, z) 清單設定樓板子元素高程。
        /// XY 落在既有控制點容差內者直接改該點高程；找不到對應點時可選擇新增控制點。
        /// </summary>
        private object SetFloorShapePoints(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            long floorIdRaw = parameters["floorId"]?.Value<long>() ?? 0;
            if (floorIdRaw == 0)
                throw new Exception("必須指定 floorId");

            var pointsToken = parameters["points"] as JArray;
            if (pointsToken == null || pointsToken.Count == 0)
                throw new Exception("必須提供 points（至少一筆 {x, y, z}，單位公釐）");

            double matchToleranceMm = parameters["matchToleranceMm"]?.Value<double>() ?? 10.0;
            double acceptToleranceMm = parameters["acceptToleranceMm"]?.Value<double>() ?? 2.0;
            bool addIfMissing = parameters["addIfMissing"]?.Value<bool>() ?? true;
            bool dryRun = parameters["dryRun"]?.Value<bool>() ?? false;

            if (matchToleranceMm <= 0)
                throw new Exception("matchToleranceMm 必須大於 0");

            var floor = doc.GetElement(((IdType)floorIdRaw).ToElementId()) as Floor;
            if (floor == null)
                throw new Exception($"元素 {floorIdRaw} 不存在或不是樓板 (Floor)");

            var editor = floor.GetSlabShapeEditorCompat();
            if (editor == null)
                throw new Exception(
                    $"樓板 {floorIdRaw} 沒有可用的 SlabShapeEditor。" +
                    "此樓板可能是以斜率箭頭或結構斜板定義，需先在 Revit 中改為形狀編輯模式。");

            double matchToleranceFt = matchToleranceMm / 304.8;
            double acceptToleranceFt = acceptToleranceMm / 304.8;

            // 解析輸入點（公釐 → 英尺）
            var requests = new List<FloorShapePointRequest>();
            for (int index = 0; index < pointsToken.Count; index++)
            {
                var entry = pointsToken[index];
                var x = entry["x"]?.Value<double>();
                var y = entry["y"]?.Value<double>();
                var z = entry["z"]?.Value<double>();
                if (x == null || y == null || z == null)
                    throw new Exception($"points[{index}] 缺少 x / y / z");

                requests.Add(new FloorShapePointRequest(
                    index,
                    new XYZ(x.Value / 304.8, y.Value / 304.8, z.Value / 304.8)));
            }

            // === dryRun：只比對現況，不進 Transaction ===
            if (dryRun)
            {
                var existing = CollectFloorShapeVertexPositions(editor);
                var preview = new List<object>();
                int wouldModify = 0;
                int wouldAdd = 0;

                foreach (var request in requests)
                {
                    var nearest = FindNearestPositionByXY(existing, request.Target, matchToleranceFt);
                    if (nearest != null)
                    {
                        wouldModify++;
                        preview.Add(new
                        {
                            Index = request.Index,
                            Action = "modify",
                            X = Math.Round(request.Target.X * 304.8, 2),
                            Y = Math.Round(request.Target.Y * 304.8, 2),
                            CurrentZ = Math.Round(nearest.Z * 304.8, 2),
                            TargetZ = Math.Round(request.Target.Z * 304.8, 2),
                            DeltaZ = Math.Round((request.Target.Z - nearest.Z) * 304.8, 2)
                        });
                    }
                    else
                    {
                        wouldAdd++;
                        preview.Add(new
                        {
                            Index = request.Index,
                            Action = addIfMissing ? "add" : "skip",
                            X = Math.Round(request.Target.X * 304.8, 2),
                            Y = Math.Round(request.Target.Y * 304.8, 2),
                            CurrentZ = (double?)null,
                            TargetZ = Math.Round(request.Target.Z * 304.8, 2),
                            DeltaZ = (double?)null
                        });
                    }
                }

                return new
                {
                    DryRun = true,
                    FloorId = floorIdRaw,
                    IsShapeEditingEnabled = editor.IsEnabled,
                    ExistingVertexCount = existing.Count,
                    RequestedCount = requests.Count,
                    WouldModify = wouldModify,
                    WouldAdd = addIfMissing ? wouldAdd : 0,
                    WouldSkip = addIfMissing ? 0 : wouldAdd,
                    Points = preview
                };
            }

            // === 實際寫入 ===
            var applied = new List<object>();
            var skipped = new List<object>();
            int addedCount = 0;

            Transaction trans = null;
            try
            {
                trans = TransactionHelper.Begin(doc, "設定樓板子元素高程");
                trans.Start();

                if (!editor.IsEnabled)
                {
                    editor.Enable();
                    doc.Regenerate();
                }

                // 步驟 1：找不到對應控制點者先補點
                if (addIfMissing)
                {
                    var existing = CollectFloorShapeVertexPositions(editor);
                    var pointsToAdd = new List<XYZ>();
                    foreach (var request in requests)
                    {
                        if (FindNearestPositionByXY(existing, request.Target, matchToleranceFt) != null)
                            continue;
                        if (FindNearestPositionByXY(pointsToAdd, request.Target, matchToleranceFt) != null)
                            continue;
                        pointsToAdd.Add(request.Target);
                    }

                    if (pointsToAdd.Count > 0)
                    {
                        int total = existing.Count + pointsToAdd.Count;
                        if (total > FloorShapePointLimit)
                            throw new Exception(
                                $"控制點總數 {total} 超過上限 {FloorShapePointLimit}，請分批處理或降低取樣密度。");

                        // Revit 2020 的 SlabShapeEditor 只有逐點的 DrawPoint，沒有批次 AddPoints。
                        // 落在樓板範圍外的點會擲回例外，記錄後略過，由後續比對階段列入 skipped。
                        foreach (var point in pointsToAdd)
                        {
                            try
                            {
#if REVIT2026_OR_GREATER
                                // Revit 2026 移除了 SlabShapeEditor.DrawPoint，改用批次 AddPoints。
                                // 這裡刻意一次只送一點，維持原本「逐點容錯、失敗略過」的語意。
                                editor.AddPoints(new List<XYZ> { point });
#else
                                editor.DrawPoint(point);
#endif
                                addedCount++;
                            }
                            catch (Exception ex)
                            {
                                Logger.Info(
                                    "[set_floor_shape_points] DrawPoint 失敗 " +
                                    $"({Math.Round(point.X * 304.8, 2)}, {Math.Round(point.Y * 304.8, 2)}): {ex.Message}");
                            }
                        }

                        doc.Regenerate();
                    }
                }

                // 步驟 2：把每個請求對應到實際頂點；對應不到的記為 skipped
                var vertexPositions = CollectFloorShapeVertexPositions(editor);
                var targets = new List<FloorShapePointRequest>();
                foreach (var request in requests)
                {
                    var nearest = FindNearestPositionByXY(vertexPositions, request.Target, matchToleranceFt);
                    if (nearest == null)
                    {
                        skipped.Add(new
                        {
                            Index = request.Index,
                            X = Math.Round(request.Target.X * 304.8, 2),
                            Y = Math.Round(request.Target.Y * 304.8, 2),
                            Reason = addIfMissing
                                ? "補點後仍找不到對應控制點（該 XY 可能落在樓板範圍外）"
                                : "找不到對應控制點且 addIfMissing=false"
                        });
                        continue;
                    }

                    targets.Add(new FloorShapePointRequest(request.Index, request.Target, nearest));
                }

                if (targets.Count == 0)
                    throw new Exception("沒有任何請求點對應到樓板控制點，已中止（未變更模型）。");

                // 步驟 3：兩段式校準寫入。
                // ModifySubElement 的 offset 究竟是絕對值或增量值在不同情境下語意不同，
                // 因此先寫 0 讀回基準高程，再寫入目標差值——兩種語意都會收斂到目標值。
                ApplyFloorVertexOffsets(doc, editor, targets, matchToleranceFt, _ => 0.0);
                var baselineZ = ReadFloorVertexElevations(editor, targets, matchToleranceFt);
                ApplyFloorVertexOffsets(
                    doc, editor, targets, matchToleranceFt,
                    index => targets[index].Target.Z - baselineZ[index]);

                // 步驟 4：驗收。任一點偏差超過容差就整批回滾，不留半套結果。
                var finalZ = ReadFloorVertexElevations(editor, targets, matchToleranceFt);
                var outOfTolerance = new List<object>();
                for (int index = 0; index < targets.Count; index++)
                {
                    double deviationMm = (finalZ[index] - targets[index].Target.Z) * 304.8;
                    if (Math.Abs(deviationMm) > acceptToleranceMm)
                    {
                        outOfTolerance.Add(new
                        {
                            Index = targets[index].Index,
                            TargetZ = Math.Round(targets[index].Target.Z * 304.8, 2),
                            ActualZ = Math.Round(finalZ[index] * 304.8, 2),
                            DeviationMm = Math.Round(deviationMm, 2)
                        });
                        continue;
                    }

                    applied.Add(new
                    {
                        Index = targets[index].Index,
                        X = Math.Round(targets[index].Target.X * 304.8, 2),
                        Y = Math.Round(targets[index].Target.Y * 304.8, 2),
                        BaselineZ = Math.Round(baselineZ[index] * 304.8, 2),
                        TargetZ = Math.Round(targets[index].Target.Z * 304.8, 2),
                        ActualZ = Math.Round(finalZ[index] * 304.8, 2),
                        DeviationMm = Math.Round(deviationMm, 2)
                    });
                }

                if (outOfTolerance.Count > 0)
                {
                    trans.RollBack();
                    return new
                    {
                        Success = false,
                        FloorId = floorIdRaw,
                        RolledBack = true,
                        Reason = $"有 {outOfTolerance.Count} 個控制點的最終高程超出允收容差 {acceptToleranceMm} mm，已整批回滾。",
                        OutOfTolerance = outOfTolerance
                    };
                }

                trans.Commit();

                return new
                {
                    Success = true,
                    FloorId = floorIdRaw,
                    RequestedCount = requests.Count,
                    AppliedCount = applied.Count,
                    AddedPointCount = addedCount,
                    SkippedCount = skipped.Count,
                    AcceptToleranceMm = acceptToleranceMm,
                    Applied = applied,
                    Skipped = skipped
                };
            }
            catch
            {
                if (trans != null && trans.HasStarted() && !trans.HasEnded())
                    trans.RollBack();
                throw;
            }
            finally
            {
                trans?.Dispose();
            }
        }

        /// <summary>
        /// 逐點套用 offset。頂點物件在 Regenerate 後會失效，因此每次都以位置重新尋找。
        /// </summary>
        private static void ApplyFloorVertexOffsets(
            Document doc,
            SlabShapeEditor editor,
            IReadOnlyList<FloorShapePointRequest> targets,
            double matchToleranceFt,
            Func<int, double> offsetSelector)
        {
            for (int index = 0; index < targets.Count; index++)
            {
                var vertex = FindNearestVertexByXY(editor, targets[index].MatchedPosition, matchToleranceFt);
                if (vertex == null)
                    throw new Exception(
                        $"points[{targets[index].Index}] 對應的控制點在重生後遺失，已中止（未變更模型）。");

                editor.ModifySubElement(vertex, offsetSelector(index));
            }

            doc.Regenerate();
        }

        /// <summary>讀回每個目標控制點目前的絕對高程（英尺）。</summary>
        private static double[] ReadFloorVertexElevations(
            SlabShapeEditor editor,
            IReadOnlyList<FloorShapePointRequest> targets,
            double matchToleranceFt)
        {
            var elevations = new double[targets.Count];
            for (int index = 0; index < targets.Count; index++)
            {
                var vertex = FindNearestVertexByXY(editor, targets[index].MatchedPosition, matchToleranceFt);
                if (vertex == null)
                    throw new Exception(
                        $"points[{targets[index].Index}] 對應的控制點在重生後遺失，已中止（未變更模型）。");

                elevations[index] = vertex.Position.Z;
            }

            return elevations;
        }

        private static List<XYZ> CollectFloorShapeVertexPositions(SlabShapeEditor editor)
        {
            var positions = new List<XYZ>();
            foreach (SlabShapeVertex vertex in editor.SlabShapeVertices)
            {
                positions.Add(vertex.Position);
            }

            return positions;
        }

        private static SlabShapeVertex FindNearestVertexByXY(
            SlabShapeEditor editor,
            XYZ target,
            double toleranceFt)
        {
            SlabShapeVertex nearest = null;
            double nearestDistance = double.MaxValue;

            foreach (SlabShapeVertex vertex in editor.SlabShapeVertices)
            {
                double distance = FloorShapeDistanceXY(vertex.Position, target);
                if (distance > toleranceFt || distance >= nearestDistance)
                    continue;

                nearest = vertex;
                nearestDistance = distance;
            }

            return nearest;
        }

        private static XYZ FindNearestPositionByXY(
            IReadOnlyList<XYZ> positions,
            XYZ target,
            double toleranceFt)
        {
            XYZ nearest = null;
            double nearestDistance = double.MaxValue;

            foreach (var position in positions)
            {
                double distance = FloorShapeDistanceXY(position, target);
                if (distance > toleranceFt || distance >= nearestDistance)
                    continue;

                nearest = position;
                nearestDistance = distance;
            }

            return nearest;
        }

        private static double FloorShapeDistanceXY(XYZ first, XYZ second)
        {
            double deltaX = first.X - second.X;
            double deltaY = first.Y - second.Y;
            return Math.Sqrt((deltaX * deltaX) + (deltaY * deltaY));
        }

        private sealed class FloorShapePointRequest
        {
            public FloorShapePointRequest(int index, XYZ target, XYZ matchedPosition = null)
            {
                Index = index;
                Target = target;
                MatchedPosition = matchedPosition;
            }

            /// <summary>對應到輸入 points 陣列的索引，方便使用者回查。</summary>
            public int Index { get; }

            /// <summary>目標位置（英尺），Z 為要達成的絕對高程。</summary>
            public XYZ Target { get; }

            /// <summary>實際匹配到的控制點位置（英尺），供重生後重新尋找。</summary>
            public XYZ MatchedPosition { get; }
        }

        #endregion
    }
}
