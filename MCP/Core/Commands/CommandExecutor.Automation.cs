using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Newtonsoft.Json.Linq;

#if REVIT2024_OR_GREATER
using IdType = System.Int64;
#else
using IdType = System.Int32;
#endif

namespace RevitMCP.Core
{
    public partial class CommandExecutor
    {
        private object GetElementLocation(JObject parameters)
        {
            IdType elementId = parameters["elementId"]?.Value<IdType>() ?? 0;
            Document doc = _uiApp.ActiveUIDocument.Document;
            Element element = doc.GetElement(new ElementId(elementId));

            if (element == null) return new { error = "Element not found." };

            XYZ point = null;
            if (element.Location is LocationPoint lp)
            {
                point = lp.Point;
            }
            else if (element.Location is LocationCurve lc)
            {
                point = (lc.Curve.GetEndPoint(0) + lc.Curve.GetEndPoint(1)) / 2;
            }
            else
            {
                BoundingBoxXYZ bbox = element.get_BoundingBox(null);
                if (bbox != null) point = (bbox.Min + bbox.Max) / 2;
            }

            if (point == null) return new { error = "Could not determine element location." };

            return new
            {
                x = point.X * 304.8,
                y = point.Y * 304.8,
                z = point.Z * 304.8
            };
        }

        private object RenameElement(JObject parameters)
        {
            IdType elementId = parameters["elementId"]?.Value<IdType>() ?? 0;
            string newName = parameters["newName"]?.Value<string>();
            Document doc = _uiApp.ActiveUIDocument.Document;

            if (string.IsNullOrEmpty(newName)) throw new Exception("New name is required.");

            Element element = doc.GetElement(new ElementId(elementId));
            if (element == null) throw new Exception("Element not found.");

            using (Transaction trans = new Transaction(doc, "Rename Element"))
            {
                trans.Start();
                element.Name = newName;
                trans.Commit();
            }

            return new { status = "success", elementId, newName };
        }

        private object MeasureClearance(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            
            // Extract origin and direction
            JToken originToken = parameters["origin"];
            XYZ origin = new XYZ(
                originToken["x"].Value<double>() / 304.8,
                originToken["y"].Value<double>() / 304.8,
                originToken["z"].Value<double>() / 304.8
            );

            JToken directionToken = parameters["direction"];
            XYZ direction = new XYZ(
                directionToken["x"].Value<double>(),
                directionToken["y"].Value<double>(),
                directionToken["z"].Value<double>()
            ).Normalize();

            // Find 3D View for Raycasting
            View3D view3D = new FilteredElementCollector(doc)
                .OfClass(typeof(View3D))
                .Cast<View3D>()
                .FirstOrDefault(v => !v.IsTemplate);

            if (view3D == null) throw new Exception("A 3D view is required for clearance check.");

            // Standard obstacles
            List<BuiltInCategory> categories = new List<BuiltInCategory> {
                BuiltInCategory.OST_Walls,
                BuiltInCategory.OST_StructuralColumns,
                BuiltInCategory.OST_Columns,
                BuiltInCategory.OST_StructuralFraming,
                BuiltInCategory.OST_Ceilings,
                BuiltInCategory.OST_Floors,
                BuiltInCategory.OST_DuctCurves,
                BuiltInCategory.OST_PipeCurves,
                BuiltInCategory.OST_Stairs
            };

            ElementMulticategoryFilter filter = new ElementMulticategoryFilter(categories);
            ReferenceIntersector intersector = new ReferenceIntersector(filter, FindReferenceTarget.Element, view3D);
            
            ReferenceWithContext referenceWithContext = intersector.FindNearest(origin, direction);

            if (referenceWithContext == null)
            {
                return new { hit = false, distance = -1 };
            }

            double distanceFeet = referenceWithContext.Proximity;
            double distanceMm = distanceFeet * 304.8;
            Element hitElement = doc.GetElement(referenceWithContext.GetReference().ElementId);

            return new
            {
                hit = true,
                distance = distanceMm,
                elementId = hitElement.Id.IntegerValue,
#if REVIT2024_OR_GREATER
                elementIdLong = hitElement.Id.Value,
#endif
                elementName = hitElement.Name,
                category = hitElement.Category?.Name
            };
        }
    }
}
