using System;
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
        private object MoveElement(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType elementId = parameters["elementId"]?.Value<IdType>() ?? 0;
            double dx = parameters["dx"]?.Value<double>() ?? 0;
            double dy = parameters["dy"]?.Value<double>() ?? 0;
            double dz = parameters["dz"]?.Value<double>() ?? 0;

            Element element = doc.GetElement(elementId.ToElementId());
            if (element == null)
            {
                throw new Exception($"Element not found: {elementId}");
            }

            using (Transaction trans = new Transaction(doc, $"Move element: {elementId}"))
            {
                trans.Start();

                XYZ translation = new XYZ(dx / 304.8, dy / 304.8, dz / 304.8);
                ElementTransformUtils.MoveElement(doc, elementId.ToElementId(), translation);

                trans.Commit();

                return new
                {
                    ElementId = elementId,
                    Dx = dx,
                    Dy = dy,
                    Dz = dz,
                    Message = "Element moved successfully"
                };
            }
        }

        private object FlipElement(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType elementId = parameters["elementId"]?.Value<IdType>() ?? 0;
            string flipType = parameters["flipType"]?.Value<string>() ?? "facing";

            Element element = doc.GetElement(elementId.ToElementId());
            if (element == null)
            {
                throw new Exception($"Element not found: {elementId}");
            }

            if (!(element is FamilyInstance familyInstance))
            {
                throw new Exception($"Element {elementId} is not a family instance and cannot be flipped");
            }

            using (Transaction trans = new Transaction(doc, $"Flip element: {elementId}"))
            {
                trans.Start();

                string normalizedFlipType = flipType.ToLowerInvariant();
                if (normalizedFlipType == "facing")
                {
                    if (!familyInstance.CanFlipFacing)
                        throw new Exception("This element does not support facing flip");

                    familyInstance.flipFacing();
                }
                else if (normalizedFlipType == "hand")
                {
                    if (!familyInstance.CanFlipHand)
                        throw new Exception("This element does not support hand flip");

                    familyInstance.flipHand();
                }
                else
                {
                    throw new Exception("Invalid flipType. Use 'facing' or 'hand'");
                }

                trans.Commit();

                return new
                {
                    ElementId = elementId,
                    FlipType = normalizedFlipType,
                    Message = "Element flipped successfully"
                };
            }
        }

        private void CopyInstanceParameters(Element source, Element target)
        {
            foreach (Parameter sourceParam in source.Parameters)
            {
                if (sourceParam.IsReadOnly || !sourceParam.HasValue) continue;

                string paramName = sourceParam.Definition.Name;
                if (paramName.Contains("Level") ||
                    paramName.Contains("Host") ||
                    paramName.Contains("ID") ||
                    paramName.Contains("樓層") ||
                    paramName.Contains("主體") ||
                    paramName == "Mark" ||
                    paramName == "標記")
                    continue;

                Parameter targetParam = target.LookupParameter(paramName);
                if (targetParam == null || targetParam.IsReadOnly) continue;

                try
                {
                    switch (sourceParam.StorageType)
                    {
                        case StorageType.String:
                            targetParam.Set(sourceParam.AsString());
                            break;
                        case StorageType.Double:
                            targetParam.Set(sourceParam.AsDouble());
                            break;
                        case StorageType.Integer:
                            targetParam.Set(sourceParam.AsInteger());
                            break;
                        case StorageType.ElementId:
                            targetParam.Set(sourceParam.AsElementId());
                            break;
                    }
                }
                catch
                {
                    // Some family parameters reject copied values; keep the created element valid.
                }
            }
        }
    }
}
