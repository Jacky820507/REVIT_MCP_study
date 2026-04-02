using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Architecture;
using Autodesk.Revit.UI;
using Newtonsoft.Json.Linq;

namespace RevitMCP.Core
{
    public partial class CommandExecutor
    {
        private class EdgeData
        {
            public double Depth { get; set; }
            public double Length { get; set; }
            public bool IsStepProfile { get; set; }
            public XYZ P0 { get; set; }
            public XYZ P1 { get; set; }
        }

        private object TraceStairGeometry(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            View view = _uiApp.ActiveUIDocument.ActiveView;

            XYZ viewDir = view.ViewDirection; 
            XYZ origin = view.Origin;

            var runs = new FilteredElementCollector(doc, view.Id)
                .OfCategory(BuiltInCategory.OST_StairsRuns)
                .WhereElementIsNotElementType()
                .Cast<StairsRun>()
                .ToList();

            var result = new List<object>();

            foreach (var run in runs)
            {
                Stairs parentStair = run.GetStairs();
                if (parentStair != null)
                {
                    ElementType stairType = doc.GetElement(parentStair.GetTypeId()) as ElementType;
                    if (stairType != null)
                    {
                        string familyName = stairType.FamilyName;
                        if (!familyName.Contains("組合") && !familyName.Contains("Assembled"))
                        {
                            continue;
                        }
                    }
                }

                Options opt = new Options { DetailLevel = ViewDetailLevel.Fine };
                GeometryElement geom = run.get_Geometry(opt);
                
                var hiddenLines = new List<object>();
                var allEdges = new List<EdgeData>();

                Action<GeometryElement, Transform> collectEdges = null;
                collectEdges = (gelem, transform) => {
                    if (gelem == null) return;
                    foreach (GeometryObject obj in gelem)
                    {
                        if (obj is Solid solid && solid.Faces.Size > 0)
                        {
                            foreach (Edge edge in solid.Edges)
                            {
                                Curve c = edge.AsCurve();
                                if (transform != null && !transform.IsIdentity)
                                {
                                    c = c.CreateTransformed(transform);
                                }
                                
                                if (c.Length < 0.01) continue; 

                                XYZ p0 = c.GetEndPoint(0);
                                XYZ p1 = c.GetEndPoint(1);
                                XYZ mid = c.Evaluate(0.5, true);

                                double depth = (origin - mid).DotProduct(viewDir);
                                
                                double d0 = (origin - p0).DotProduct(viewDir);
                                double d1 = (origin - p1).DotProduct(viewDir);
                                XYZ proj0 = p0 + viewDir * d0;
                                XYZ proj1 = p1 + viewDir * d1;
                                double projLen = proj0.DistanceTo(proj1);

                                if (projLen < 0.01) continue;

                                XYZ dir = (proj1 - proj0).Normalize();

                                bool isHorizontal = Math.Abs(dir.Z) < 0.1;
                                bool isVertical = Math.Abs(Math.Abs(dir.Z) - 1.0) < 0.1;
                                bool isStepProfile = isHorizontal || isVertical || (projLen < 0.65);

                                allEdges.Add(new EdgeData {
                                    Depth = depth,
                                    Length = projLen,
                                    IsStepProfile = isStepProfile,
                                    P0 = p0,
                                    P1 = p1
                                });
                            }
                        }
                        else if (obj is GeometryInstance instance)
                        {
                            Transform currentTransform = transform != null ? transform.Multiply(instance.Transform) : instance.Transform;
                            collectEdges(instance.SymbolGeometry, currentTransform);
                        }
                    }
                };
                collectEdges(geom, null);

                if (allEdges.Count > 0)
                {
                    double minDepth = allEdges.Min(e => e.Depth);
                    if (minDepth <= 0.05) continue;

                    double depthTolerance = 2.5; 
                    var firstRunEdges = allEdges.Where(e => e.Depth <= minDepth + depthTolerance && e.IsStepProfile).ToList();

                    foreach (var edge in firstRunEdges)
                    {
                        hiddenLines.Add(new {
                            startX = Math.Round(edge.P0.X * 304.8, 2),
                            startY = Math.Round(edge.P0.Y * 304.8, 2),
                            startZ = Math.Round(edge.P0.Z * 304.8, 2),
                            endX = Math.Round(edge.P1.X * 304.8, 2),
                            endY = Math.Round(edge.P1.Y * 304.8, 2),
                            endZ = Math.Round(edge.P1.Z * 304.8, 2)
                        });
                    }
                }

                if (hiddenLines.Count > 0)
                {
                    result.Add(new {
                        StairId = run.Id.GetIdValue(),
                        HiddenLines = hiddenLines,
                        TotalEdges = allEdges.Count,
                        FirstRunEdgesCount = hiddenLines.Count
                    });
                }
            }

            return result;
        }
    }
}
