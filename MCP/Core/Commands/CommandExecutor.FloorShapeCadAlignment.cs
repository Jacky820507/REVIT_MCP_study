#if REVIT2024_OR_GREATER
using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.UI;
using Autodesk.Revit.UI.Selection;
using Newtonsoft.Json.Linq;

namespace RevitMCP.Core
{
    public partial class CommandExecutor
    {
        private const double FloorShapeCadMmToFt = 1.0 / 304.8;
        private const double FloorShapeCadPointToleranceMm = 1.0;

        /// <summary>
        /// 互動式將目前點選的樓板子元素直線，替換成點選 CAD 線的平面位置。
        ///
        /// Revit API 沒有提供 SlabShapeCrease 的 XY 平移方法；因此採用同一交易內
        /// 刪除既有 split line，再以 CAD 線端點加入新 split line。失敗時整批回滾。
        /// </summary>
        private object AlignSelectedFloorShapeLineToCad(JObject parameters)
        {
            UIDocument uiDocument = _uiApp.ActiveUIDocument;
            if (uiDocument == null)
                throw new Exception("目前沒有開啟的 Revit 文件。");

            Document doc = uiDocument.Document;
            Reference floorReference;
            Reference cadReference;

            try
            {
                floorReference = uiDocument.Selection.PickObject(
                    ObjectType.Subelement,
                    new FloorShapeSubelementSelectionFilter(),
                    "請選取要對齊的樓板子元素直線");
            }
            catch (Autodesk.Revit.Exceptions.OperationCanceledException)
            {
                return new { Success = false, Cancelled = true, Stage = "floor-subelement" };
            }

            Floor floor = doc.GetElement(floorReference.ElementId) as Floor;
            if (floor == null)
                throw new Exception("選取的子元素不是樓板子元素。");

            if (floorReference.ElementReferenceType != ElementReferenceType.REFERENCE_TYPE_SUBELEMENT)
                throw new Exception("請點選樓板的子元素線，不要只點選整片樓板。");

            Subelement selectedSubelement = doc.GetSubelement(floorReference);
            if (selectedSubelement == null || !selectedSubelement.IsValidObject)
                throw new Exception("無法取得選取的樓板子元素。請重新點選一次。");

            Curve sourceCurve = selectedSubelement.GetGeometryObject(uiDocument.ActiveView) as Curve;
            if (sourceCurve == null)
                sourceCurve = floor.GetGeometryObjectFromReference(floorReference) as Curve;

            Line sourceLine = sourceCurve as Line;
            if (sourceLine == null)
                throw new Exception("目前只支援直線型樓板子元素；弧形或自動折線請先在 Revit 中轉成直線分割線。");

            if (!floor.CanDeleteSubelement(selectedSubelement))
                throw new Exception("這條線目前不可刪除，可能是自動折線。請先在 Revit 中將折線轉成分割線，再執行對齊。");

            try
            {
                cadReference = uiDocument.Selection.PickObject(
                    ObjectType.PointOnElement,
                    new CadImportSelectionFilter(),
                    "請點選底下 CAD 的目標線");
            }
            catch (Autodesk.Revit.Exceptions.OperationCanceledException)
            {
                return new { Success = false, Cancelled = true, Stage = "cad-line" };
            }

            ImportInstance cad = doc.GetElement(cadReference.ElementId) as ImportInstance;
            if (cad == null)
                throw new Exception("第二次選取不是 CAD 匯入或連結。請點選 DWG/DXF 的線段。");

            XYZ pickPoint = cadReference.GlobalPoint;
            if (pickPoint == null)
                throw new Exception("無法取得 CAD 點選位置。請在平面視圖中重新點選 CAD 線。");

            Line cadLine = FindNearestCadLine(doc, cad, pickPoint, uiDocument.ActiveView);
            if (cadLine == null)
                throw new Exception("在點選位置附近找不到可用的 CAD 直線或多段線線段。");

            XYZ sourceStart = sourceLine.GetEndPoint(0);
            XYZ sourceEnd = sourceLine.GetEndPoint(1);
            XYZ cadStart = cadLine.GetEndPoint(0);
            XYZ cadEnd = cadLine.GetEndPoint(1);

            // 依原線方向決定 CAD 端點順序，讓原本兩端的相對高程盡量保留。
            if ((sourceEnd - sourceStart).DotProduct(cadEnd - cadStart) < 0)
            {
                XYZ swap = cadStart;
                cadStart = cadEnd;
                cadEnd = swap;
            }

            // 只改平面位置；依原線方向保留兩端既有高程，避免 CAD 線偏移較大時
            // 以投影外插出不預期的坡度。
            XYZ replacementStart = new XYZ(cadStart.X, cadStart.Y, sourceStart.Z);
            XYZ replacementEnd = new XYZ(cadEnd.X, cadEnd.Y, sourceEnd.Z);

            using (Transaction transaction = new Transaction(doc, "樓板子元素線對齊 CAD"))
            {
                transaction.Start();
                try
                {
                    bool elementDeleted = floor.DeleteSubelement(selectedSubelement);
                    if (elementDeleted || !floor.IsValidObject)
                        throw new Exception("刪除原樓板子元素線後樓板失效，已中止。");

                    doc.Regenerate();

                    SlabShapeEditor editor = floor.GetSlabShapeEditorCompat();
                    if (editor == null)
                        throw new Exception("樓板沒有可用的 SlabShapeEditor。");
                    if (!editor.IsEnabled)
                        editor.Enable();

                    doc.Regenerate();
                    SlabShapeVertex startVertex = FindOrCreateVertex(doc, editor, replacementStart);
                    SlabShapeVertex endVertex = FindOrCreateVertex(doc, editor, replacementEnd);
                    if (startVertex == null || endVertex == null)
                        throw new Exception("CAD 線端點不在樓板範圍內，無法建立樓板分割線。");

                    if (FloorShapeCadXYDistance(startVertex.Position, endVertex.Position) <=
                        FloorShapeCadPointToleranceMm * FloorShapeCadMmToFt)
                        throw new Exception("CAD 線長度太短，無法建立有效的樓板分割線。");

                    IList<SlabShapeCrease> createdCreases = AddSplitLineCompat(editor, startVertex, endVertex);
                    doc.Regenerate();

                    SlabShapeEditor finalEditor = floor.GetSlabShapeEditorCompat();
                    int matchingCreaseCount = CountMatchingCreases(
                        finalEditor,
                        replacementStart,
                        replacementEnd,
                        FloorShapeCadPointToleranceMm * FloorShapeCadMmToFt * 2.0);
                    if (matchingCreaseCount == 0)
                        throw new Exception("新分割線建立後驗收不到對應幾何，已回滾。");

                    transaction.Commit();

                    return new
                    {
                        Success = true,
                        FloorId = floor.Id.GetIdValue(),
                        CadId = cad.Id.GetIdValue(),
                        DeletedOriginalSubelement = true,
                        CreatedCreaseCount = createdCreases == null ? 0 : createdCreases.Count,
                        MatchingCreaseCount = matchingCreaseCount,
                        SourceStart = ToMillimeters(sourceStart),
                        SourceEnd = ToMillimeters(sourceEnd),
                        CadStart = ToMillimeters(cadStart),
                        CadEnd = ToMillimeters(cadEnd),
                        Message = "樓板子元素線已對齊至點選的 CAD 線。"
                    };
                }
                catch
                {
                    if (transaction.HasStarted() && !transaction.HasEnded())
                        transaction.RollBack();
                    throw;
                }
            }
        }

        private static Line FindNearestCadLine(Document doc, ImportInstance cad, XYZ pickPoint, View view)
        {
            Options options = new Options
            {
                ComputeReferences = true,
                View = view,
                IncludeNonVisibleObjects = false
            };

            GeometryElement geometry = cad.get_Geometry(options);
            if (geometry == null)
                return null;

            List<Line> candidates = new List<Line>();
            Transform cadTransform = cad.GetTotalTransform();
            foreach (GeometryObject geometryObject in geometry)
            {
                GeometryInstance instance = geometryObject as GeometryInstance;
                if (instance == null)
                    continue;

                GeometryElement symbolGeometry = instance.GetSymbolGeometry();
                if (symbolGeometry == null)
                    continue;

                CollectCadLines(doc, symbolGeometry, cadTransform.Multiply(instance.Transform), candidates);
            }

            Line nearest = null;
            double nearestDistance = double.MaxValue;
            foreach (Line candidate in candidates)
            {
                double distance = PointToLineDistance(pickPoint, candidate);
                if (distance < nearestDistance)
                {
                    nearest = candidate;
                    nearestDistance = distance;
                }
            }

            return nearest;
        }

        private static void CollectCadLines(
            Document doc,
            GeometryElement geometry,
            Transform sourceToProject,
            List<Line> lines)
        {
            foreach (GeometryObject geometryObject in geometry)
            {
                GeometryInstance nested = geometryObject as GeometryInstance;
                if (nested != null)
                {
                    GeometryElement nestedGeometry = nested.GetSymbolGeometry();
                    if (nestedGeometry != null)
                        CollectCadLines(doc, nestedGeometry, sourceToProject.Multiply(nested.Transform), lines);
                    continue;
                }

                try
                {
                    Line line = geometryObject as Line;
                    if (line != null)
                    {
                        AddTransformedCadLine(lines, sourceToProject, line.GetEndPoint(0), line.GetEndPoint(1));
                        continue;
                    }

                    PolyLine polyLine = geometryObject as PolyLine;
                    if (polyLine == null)
                        continue;

                    IList<XYZ> points = polyLine.GetCoordinates();
                    for (int index = 0; index < points.Count - 1; index++)
                        AddTransformedCadLine(lines, sourceToProject, points[index], points[index + 1]);
                }
                catch
                {
                    // 單一 CAD 幾何損壞時跳過，繼續找其他有效線段。
                }
            }
        }

        private static void AddTransformedCadLine(List<Line> lines, Transform transform, XYZ start, XYZ end)
        {
            XYZ transformedStart = transform.OfPoint(start);
            XYZ transformedEnd = transform.OfPoint(end);
            if (transformedStart.DistanceTo(transformedEnd) > 1e-9)
                lines.Add(Line.CreateBound(transformedStart, transformedEnd));
        }

        private static SlabShapeVertex FindOrCreateVertex(Document doc, SlabShapeEditor editor, XYZ target)
        {
            double tolerance = FloorShapeCadPointToleranceMm * FloorShapeCadMmToFt;
            foreach (SlabShapeVertex vertex in editor.SlabShapeVertices)
            {
                if (FloorShapeCadXYDistance(vertex.Position, target) <= tolerance)
                    return vertex;
            }

#if REVIT2026_OR_GREATER
            editor.AddPoints(new List<XYZ> { target });
#else
            editor.DrawPoint(target);
#endif
            doc.Regenerate();

            SlabShapeEditor refreshedEditor = editor;
            foreach (SlabShapeVertex vertex in refreshedEditor.SlabShapeVertices)
            {
                if (FloorShapeCadXYDistance(vertex.Position, target) <= tolerance)
                    return vertex;
            }

            return null;
        }

        private static IList<SlabShapeCrease> AddSplitLineCompat(
            SlabShapeEditor editor,
            SlabShapeVertex startVertex,
            SlabShapeVertex endVertex)
        {
#if REVIT2025_OR_GREATER
            return editor.AddSplitLine(startVertex, endVertex);
#else
            editor.DrawSplitLine(startVertex, endVertex);
            return new List<SlabShapeCrease>();
#endif
        }

        private static int CountMatchingCreases(
            SlabShapeEditor editor,
            XYZ start,
            XYZ end,
            double tolerance)
        {
            if (editor == null)
                return 0;

            int count = 0;
            foreach (SlabShapeCrease crease in editor.SlabShapeCreases)
            {
                Curve curve = crease.Curve;
                Line line = curve as Line;
                if (line == null)
                    continue;

                XYZ first = line.GetEndPoint(0);
                XYZ second = line.GetEndPoint(1);
                bool sameDirection = first.DistanceTo(start) <= tolerance && second.DistanceTo(end) <= tolerance;
                bool reverseDirection = first.DistanceTo(end) <= tolerance && second.DistanceTo(start) <= tolerance;
                if (sameDirection || reverseDirection)
                    count++;
            }

            return count;
        }

        private static double PointToLineDistance(XYZ point, Line line)
        {
            XYZ start = line.GetEndPoint(0);
            XYZ end = line.GetEndPoint(1);
            XYZ direction = end - start;
            double lengthSquared = direction.X * direction.X + direction.Y * direction.Y;
            if (lengthSquared <= 1e-12)
                return FloorShapeCadXYDistance(point, start);

            double parameter = ((point.X - start.X) * direction.X +
                                (point.Y - start.Y) * direction.Y) / lengthSquared;
            parameter = Math.Max(0.0, Math.Min(1.0, parameter));
            XYZ closest = new XYZ(
                start.X + direction.X * parameter,
                start.Y + direction.Y * parameter,
                point.Z);
            return FloorShapeCadXYDistance(point, closest);
        }

        private static double FloorShapeCadXYDistance(XYZ first, XYZ second)
        {
            double deltaX = first.X - second.X;
            double deltaY = first.Y - second.Y;
            return Math.Sqrt(deltaX * deltaX + deltaY * deltaY);
        }

        private static object ToMillimeters(XYZ point)
        {
            return new
            {
                X = Math.Round(point.X * 304.8, 2),
                Y = Math.Round(point.Y * 304.8, 2),
                Z = Math.Round(point.Z * 304.8, 2)
            };
        }

        private sealed class FloorShapeSubelementSelectionFilter : ISelectionFilter
        {
            public bool AllowElement(Element element)
            {
                return element is Floor;
            }

            public bool AllowReference(Reference reference, XYZ position)
            {
                return reference != null &&
                       reference.ElementReferenceType == ElementReferenceType.REFERENCE_TYPE_SUBELEMENT;
            }
        }

        private sealed class CadImportSelectionFilter : ISelectionFilter
        {
            public bool AllowElement(Element element)
            {
                return element is ImportInstance;
            }

            public bool AllowReference(Reference reference, XYZ position)
            {
                return true;
            }
        }
    }
}
#endif
