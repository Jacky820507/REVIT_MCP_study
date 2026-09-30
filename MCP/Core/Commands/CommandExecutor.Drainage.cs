using System;
using System.Collections.Generic;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using Autodesk.Revit.DB;
using Newtonsoft.Json.Linq;

namespace RevitMCP.Core
{
    public partial class CommandExecutor
    {
        private const double DrainMm = 304.8;
        internal sealed class DrainCircle
        {
            public string Key, Layer;
            public XYZ Center;
            public double Radius;
            public ImportInstance Cad;
            public ViewPlan View;
            public List<Curve> Curves = new List<Curve>();
        }
        private static string DrainHash(string text)
        {
            using (var hash = SHA256.Create())
                return BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(text))).Replace("-", "");
        }
        private static ElementId DrainId(JToken token)
        {
            if (token == null) throw new ArgumentException("Missing element ID.");
            var value = token.Value<long>();
#if REVIT2025_OR_GREATER
            return value.ToElementId();
#else
            return checked((int)value).ToElementId();
#endif
        }
        private static double DrainNumber(JObject obj, string name, double minimum = double.NegativeInfinity)
        {
            if (obj[name] == null) throw new ArgumentException("Missing " + name);
            double n = obj[name].Value<double>();
            if (!DrainageReviewMath.Finite(n) || n < minimum) throw new ArgumentException("Invalid " + name);
            return n;
        }
        private static string DrainRequired(JObject obj, string name)
        {
            string value = (string)obj[name];
            if (string.IsNullOrWhiteSpace(value)) throw new ArgumentException("Missing " + name);
            return value;
        }
        private static ViewPlan DrainView(Document doc, JToken id)
        {
            var view = doc.GetElement(DrainId(id)) as ViewPlan;
            if (view == null || view.IsTemplate || view.GenLevel == null || Math.Abs(view.ViewDirection.Z) < 0.99999)
                throw new ArgumentException("An existing horizontal level plan is required.");
            return view;
        }
        private static ViewPlan DrainOwner(Document doc, ViewPlan view)
        {
            var primary = view.GetPrimaryViewId();
            return primary == ElementId.InvalidElementId ? view : (ViewPlan)doc.GetElement(primary);
        }
        private static IEnumerable<Tuple<Curve, ElementId>> DrainCurves(GeometryElement geometry, Transform transform, int depth = 0)
        {
            if (geometry == null) yield break;
            if (depth > 16) throw new InvalidOperationException("CAD nesting exceeds 16.");
            foreach (GeometryObject obj in geometry)
            {
                var instance = obj as GeometryInstance;
                if (instance != null)
                {
                    foreach (var curve in DrainCurves(instance.GetSymbolGeometry(), transform.Multiply(instance.Transform), depth + 1)) yield return curve;
                }
                else if (obj is Curve)
                {
                    var curve = ((Curve)obj).CreateTransformed(transform);
                    // Preserve source style explicitly; a transient transformed curve need not retain it.
                    yield return Tuple.Create(curve, obj.GraphicsStyleId);
                }
            }
        }
        internal static List<DrainCircle> DrainRead(Document doc, ViewPlan view, ImportInstance cad, HashSet<string> layers, int limit)
        {
            // GetInstanceGeometry traversal uses each instance transform exactly once.
            var curves = DrainCurves(cad.get_Geometry(new Options()), Transform.Identity).Take(100001).ToList();
            if (curves.Count > 100000) throw new InvalidOperationException("CAD exceeds geometry budget; split source/layers first.");
            var groups = new Dictionary<string, DrainCircle>();
            foreach (var source in curves.Where(x => x.Item1 is Arc))
            {
                var arc = (Arc)source.Item1;
                if (Math.Abs(arc.Normal.Z) < 0.99999) continue;
                string layer = (doc.GetElement(source.Item2) as GraphicsStyle)?.GraphicsStyleCategory?.Name ?? "";
                if (layers != null && !layers.Contains(layer)) continue;
                var c = arc.Center;
                string group = layer + "|" + string.Join("|", new[] { c.X, c.Y, c.Z, arc.Radius }.Select(v => v.ToString("R", System.Globalization.CultureInfo.InvariantCulture)));
                DrainCircle item;
                if (!groups.TryGetValue(group, out item))
                    groups[group] = item = new DrainCircle { Center = c, Radius = arc.Radius, Cad = cad, View = view, Layer = layer, Key = DrainHash(cad.UniqueId + "|" + group) };
                item.Curves.Add(arc);
            }
            var result = new List<DrainCircle>();
            foreach (var item in groups.Values)
            {
                var arcs = item.Curves.Cast<Arc>().ToList();
                bool full = arcs.Any(a => !a.IsBound);
                // Accept complementary semicircles only; overlapping/duplicate arcs must not manufacture a circle.
                if (!full && arcs.Count == 2)
                {
                    var a = arcs[0]; var b = arcs[1];
                    full = Math.Abs(a.Length / a.Radius - Math.PI) < 1e-7 && Math.Abs(b.Length / b.Radius - Math.PI) < 1e-7
                        && a.Evaluate(0.5, true).DistanceTo(b.Evaluate(0.5, true)) > item.Radius * 1.99999
                        && ((a.GetEndPoint(0).DistanceTo(b.GetEndPoint(0)) < 1e-6 && a.GetEndPoint(1).DistanceTo(b.GetEndPoint(1)) < 1e-6)
                         || (a.GetEndPoint(0).DistanceTo(b.GetEndPoint(1)) < 1e-6 && a.GetEndPoint(1).DistanceTo(b.GetEndPoint(0)) < 1e-6));
                }
                if (!full) continue;
                if (view.CropBoxActive)
                {
                    var crop = view.CropBox; var p = crop.Transform.Inverse.OfPoint(item.Center);
                    if (p.X < crop.Min.X || p.X > crop.Max.X || p.Y < crop.Min.Y || p.Y > crop.Max.Y) continue;
                }
                result.Add(item);
                if (result.Count > limit) throw new InvalidOperationException("Circle limit exceeded; no partial success returned.");
            }
            return result;
        }
        private object ScanDrainageCad(JObject parameters)
        {
            var doc = _uiApp.ActiveUIDocument.Document;
            var views = new Dictionary<string, ViewPlan>();
            var warnings = new JArray();
            foreach (var id in parameters["viewIds"] as JArray ?? new JArray())
            {
                var v = DrainView(doc, id); views[v.UniqueId] = v;
            }
            var wanted = new HashSet<string>((parameters["sheetNumbers"] as JArray ?? new JArray()).Values<string>());
            if (wanted.Count > 0)
            {
                foreach (ViewSheet sheet in new FilteredElementCollector(doc).OfClass(typeof(ViewSheet)))
                {
                    if (!wanted.Remove(sheet.SheetNumber)) continue;
                    foreach (var id in sheet.GetAllPlacedViews())
                    {
                        var v = doc.GetElement(id) as ViewPlan;
                        if (v != null && !v.IsTemplate && v.GenLevel != null) views[v.UniqueId] = v;
                    }
                }
                if (wanted.Count != 0) throw new ArgumentException("Sheets not found: " + string.Join(", ", wanted));
            }
            if (views.Count == 0 || views.Count > 30) throw new ArgumentException("Specify 1–30 plan views through viewIds or sheetNumbers.");
            bool geometry = (bool?)parameters["includeCircles"] ?? false;
            var layers = new HashSet<string>((parameters["layers"] as JArray ?? new JArray()).Values<string>());
            if (geometry && layers.Count == 0) throw new ArgumentException("Explicit CAD layers required for circle extraction.");
            int limit = (int?)parameters["maxCircles"] ?? 2000;
            if (limit < 1 || limit > 10000) throw new ArgumentException("Invalid maxCircles.");
            var output = new JArray(); int count = 0;
            foreach (var view in views.Values.OrderBy(v => v.Id.GetIdValue()))
            {
                var imports = new JArray();
                foreach (ImportInstance cad in new FilteredElementCollector(doc, view.Id).OfClass(typeof(ImportInstance)))
                {
                    string path = null;
                    try
                    {
                        var reference = ExternalFileUtils.GetExternalFileReference(doc, cad.GetTypeId());
                        path = ModelPathUtils.ConvertModelPathToUserVisiblePath(reference.GetAbsolutePath());
                    }
                    catch (Exception ex) { warnings.Add("CAD source path unavailable: " + cad.Id.GetIdValue() + ": " + ex.Message); }
                    var circles = new JArray();
                    if (geometry)
                        foreach (var c in DrainRead(doc, view, cad, layers, limit - count))
                        {
                            circles.Add(new JObject { ["circleKey"] = c.Key, ["layer"] = c.Layer, ["xMm"] = c.Center.X * DrainMm, ["yMm"] = c.Center.Y * DrainMm, ["zMm"] = c.Center.Z * DrainMm, ["symbolRadiusMm"] = c.Radius * DrainMm, ["kind"] = "unknown", ["direction"] = "unknown" });
                            count++;
                        }
                    var t = cad.GetTotalTransform();
                    imports.Add(new JObject { ["cadId"] = cad.Id.GetIdValue(), ["uniqueId"] = cad.UniqueId, ["sourcePath"] = path, ["isLinked"] = cad.IsLinked,
                        ["transformFeet"] = JArray.FromObject(new[] { new[] {t.BasisX.X,t.BasisX.Y,t.BasisX.Z}, new[] {t.BasisY.X,t.BasisY.Y,t.BasisY.Z}, new[] {t.BasisZ.X,t.BasisZ.Y,t.BasisZ.Z}, new[] {t.Origin.X,t.Origin.Y,t.Origin.Z} }), ["circles"] = circles });
                }
                output.Add(new JObject { ["viewId"] = view.Id.GetIdValue(), ["name"] = view.Name, ["ownerViewId"] = DrainOwner(doc, view).Id.GetIdValue(), ["level"] = view.GenLevel.Name, ["elevationMm"] = view.GenLevel.Elevation * DrainMm, ["scale"] = view.Scale, ["cad"] = imports });
            }
            warnings.Add("Circle candidates only. Crop bounding box is a coarse filter; confirm nonrectangular/split crops. Text, grille and direction require source-symbol evidence; no automatic classification.");
            return new JObject { ["document"] = doc.Title, ["units"] = "Revit internal coordinates in mm; transformFeet uses feet", ["views"] = output, ["warnings"] = warnings };
        }

        private JObject DrainReview(Document doc, JObject input)
        {
            var points = input["points"] as JArray;
            if (points == null || points.Count == 0 || points.Count > 50) throw new ArgumentException("Provide 1–50 points.");
            double clearance = DrainNumber(input, "clearanceMm", 0);
            double radius = DrainNumber(input, "matchRadiusMm", 0.001);
            double tolerance = DrainNumber(input, "alignmentToleranceMm", 0);
            var categories = (input["obstacleCategories"] as JArray ?? new JArray()).Values<string>().Select(s => (BuiltInCategory)Enum.Parse(typeof(BuiltInCategory), s)).ToList();
            if (categories.Count == 0) throw new ArgumentException("Explicit obstacle categories required.");
            var rows = new JArray();
            foreach (JObject point in points)
            {
                var view = DrainView(doc, point["viewId"]);
                var cad = doc.GetElement(DrainId(point["cadId"])) as ImportInstance;
                if (cad == null || !new FilteredElementCollector(doc, view.Id).OfClass(typeof(ImportInstance)).ToElementIds().Contains(cad.Id)) throw new ArgumentException("CAD not present in selected view.");
                var c = DrainRead(doc, view, cad, null, 10000).SingleOrDefault(x => x.Key == (string)point["circleKey"]);
                if (c == null) throw new ArgumentException("Circle no longer found.");
                var issues = new JArray();
                string kind = DrainRequired(point, "kind"), direction = DrainRequired(point, "direction");
                if (!new[] {"pipe", "head"}.Contains(kind) || !new[] {"up", "down", "both", "unknown"}.Contains(direction)) throw new ArgumentException("Invalid symbol kind/direction.");
                if ((bool?)point["verified"] != true || string.IsNullOrWhiteSpace((string)point["evidence"])) issues.Add("symbol_or_label_unverified");
                if (direction == "unknown") issues.Add("direction_unknown");
                if (string.IsNullOrWhiteSpace((string)point["directionEvidence"])) issues.Add("direction_evidence_missing");
                var nominal = DrainageReviewMath.NominalInches((string)point["label"]);
                if (!nominal.HasValue) issues.Add("nominal_size_unreadable_or_ambiguous");
                var hits = new JArray();
                if (point["physicalDiameterMm"] == null || point["zMinMm"] == null || point["zMaxMm"] == null || string.IsNullOrWhiteSpace((string)point["dimensionEvidence"])) issues.Add("physical_envelope_unchecked");
                else
                {
                    double r = (DrainNumber(point, "physicalDiameterMm", 0.001) / 2 + clearance) / DrainMm;
                    double z0 = DrainNumber(point, "zMinMm") / DrainMm, z1 = DrainNumber(point, "zMaxMm") / DrainMm;
                    if (z1 <= z0) throw new ArgumentException("zMaxMm must exceed zMinMm.");
                    var center = new XYZ(c.Center.X, c.Center.Y, z0);
                    var loop = new CurveLoop();
                    loop.Append(Arc.Create(center, r, 0, Math.PI, XYZ.BasisX, XYZ.BasisY));
                    loop.Append(Arc.Create(center, r, Math.PI, 2 * Math.PI, XYZ.BasisX, XYZ.BasisY));
                    var cylinder = GeometryCreationUtilities.CreateExtrusionGeometry(new[] {loop}, XYZ.BasisZ, z1-z0);
                    // Conservative bbox candidates remain review items even if the solid filter does not hit:
                    // unsupported/no-solid architectural geometry must never be reported as clear.
                    var sources = new List<Tuple<Document, Transform, long>> { Tuple.Create(doc, Transform.Identity, 0L) };
                    foreach (var id in input["linkInstanceIds"] as JArray ?? new JArray())
                    {
                        var link = doc.GetElement(DrainId(id)) as RevitLinkInstance;
                        if (link?.GetLinkDocument() == null) { issues.Add("link_unloaded_or_missing:" + id); continue; }
                        sources.Add(Tuple.Create(link.GetLinkDocument(), link.GetTotalTransform(), (long)link.Id.GetIdValue()));
                    }
                    foreach (var source in sources)
                    {
                        var local = SolidUtils.CreateTransformed(cylinder, source.Item2.Inverse);
                        var bb = local.GetBoundingBox();
                        var corners = new List<XYZ>();
                        foreach (double x in new[] {bb.Min.X, bb.Max.X}) foreach (double y in new[] {bb.Min.Y, bb.Max.Y}) foreach (double z in new[] {bb.Min.Z, bb.Max.Z}) corners.Add(bb.Transform.OfPoint(new XYZ(x,y,z)));
                        var outline = new Outline(new XYZ(corners.Min(v=>v.X),corners.Min(v=>v.Y),corners.Min(v=>v.Z)), new XYZ(corners.Max(v=>v.X),corners.Max(v=>v.Y),corners.Max(v=>v.Z)));
                        var candidates = new FilteredElementCollector(source.Item1).WhereElementIsNotElementType().WherePasses(new ElementMulticategoryFilter(categories)).WherePasses(new BoundingBoxIntersectsFilter(outline)).Take(501).ToList();
                        if (candidates.Count > 500) throw new InvalidOperationException("Too many obstacle candidates; reduce vertical range.");
                        var filter = new ElementIntersectsSolidFilter(local);
                        foreach (var obstacle in candidates)
                        {
                            bool intersects = false;
                            try { intersects = filter.PassesFilter(obstacle); } catch { }
                            hits.Add(new JObject { ["elementId"] = obstacle.Id.GetIdValue(), ["linkInstanceId"] = source.Item3, ["status"] = intersects ? "solid_intersection" : "bbox_candidate_requires_review" });
                        }
                    }
                    if (hits.Count > 0) issues.Add("architectural_intersection_or_unresolved_candidate");
                }
                if (kind == "head") issues.Add("head_outlet_route_requires_review");
                if ((bool?)point["requiresGutter"] == true) issues.Add("gutter_effective_region_requires_review");
                // Drawing requires a separately verified symbol template, not a bare circle assumption.
                issues.Add("symbol_reproduction_requires_review");
                rows.Add(new JObject { ["circleKey"] = c.Key, ["viewId"] = view.Id.GetIdValue(), ["ownerViewId"] = DrainOwner(doc, view).Id.GetIdValue(), ["system"] = DrainRequired(point,"system"), ["kind"] = kind, ["direction"] = direction, ["xMm"] = c.Center.X*DrainMm, ["yMm"] = c.Center.Y*DrainMm, ["elevationMm"] = view.GenLevel.Elevation*DrainMm, ["symbolRadiusMm"] = c.Radius*DrainMm, ["nominalInches"] = nominal.HasValue ? new JValue(nominal.Value) : JValue.CreateNull(), ["issues"] = issues, ["obstacles"] = hits });
            }
            foreach (JObject row in rows)
            {
                var connections = new JArray();
                foreach (string side in new[] {"up", "down"})
                {
                    string direction = (string)row["direction"];
                    if (direction != side && direction != "both") continue;
                    var candidates = rows.OfType<JObject>().Where(other => (string)other["system"] == (string)row["system"] && (side == "up" ? (double)other["elevationMm"] > (double)row["elevationMm"] : (double)other["elevationMm"] < (double)row["elevationMm"])).ToList();
                    if (candidates.Count == 0) { connections.Add(new JObject { ["side"] = side, ["status"] = "adjacent_level_not_in_scope" }); continue; }
                    double elevation = side == "up" ? candidates.Min(x=>(double)x["elevationMm"]) : candidates.Max(x=>(double)x["elevationMm"]);
                    var matches = new JArray();
                    foreach (var other in candidates.Where(x => (double)x["elevationMm"] == elevation).GroupBy(x=>(string)x["circleKey"]).Select(g=>g.First()))
                    {
                        double distance = DrainageReviewMath.Distance((double)row["xMm"],(double)row["yMm"],(double)other["xMm"],(double)other["yMm"]);
                        if (distance > radius) continue;
                        string otherDirection = (string)other["direction"];
                        bool? compatible = side == "up" ? DrainageReviewMath.DirectionsConnect(otherDirection, direction) : DrainageReviewMath.DirectionsConnect(direction, otherDirection);
                        matches.Add(new JObject { ["circleKey"] = other["circleKey"], ["offsetMm"] = distance, ["directionCompatible"] = compatible.HasValue ? new JValue(compatible.Value) : JValue.CreateNull(), ["withinTolerance"] = distance <= tolerance, ["sameNominalSize"] = row["nominalInches"].Type == JTokenType.Null || other["nominalInches"].Type == JTokenType.Null ? JValue.CreateNull() : new JValue(JToken.DeepEquals(row["nominalInches"], other["nominalInches"])) });
                    }
                    connections.Add(new JObject { ["side"] = side, ["status"] = "candidates_only_not_confirmed_connection", ["candidates"] = matches });
                }
                row["connections"] = connections;
                row["readyToDraw"] = false;
            }
            return new JObject { ["points"] = rows, ["scope"] = "Explicit categories/links/heights only; all phases and options conservatively included. Cross-floor matching uses nearest supplied elevation, not proof of adjacent floor. No engineering approval implied.", ["drawingEnabled"] = false };
        }
        private object PreviewDrainageReview(JObject parameters)
        {
            return DrainReview(_uiApp.ActiveUIDocument.Document, parameters);
        }
    }
}
