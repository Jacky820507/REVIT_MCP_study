using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;

namespace RevitMCP.Core
{
    // Pure geometry/label logic; tested without loading Revit.
    public static class DrainageReviewMath
    {
        public static bool Finite(double value) => !double.IsNaN(value) && !double.IsInfinity(value);
        public static double Distance(double x, double y, double a, double b) => Math.Sqrt((x-a)*(x-a)+(y-b)*(y-b));

        public static bool? DirectionsConnect(string upper, string lower)
        {
            var valid = new[] { "up", "down", "both", "unknown" };
            if (!valid.Contains(upper) || !valid.Contains(lower)) throw new ArgumentException("Invalid direction.");
            if (upper == "unknown" || lower == "unknown") return null;
            return (upper == "down" || upper == "both") && (lower == "up" || lower == "both");
        }

        public static double? NominalInches(string label)
        {
            // Reject multiple sizes and ranges rather than silently reading the first one.
            var matches = Regex.Matches(label ?? "", "(?<![0-9./-])([0-9]+(?:\\.[0-9]+)?(?:[ ]+[0-9]+/[0-9]+)?|[0-9]+/[0-9]+)[ ]*(?:[\"″吋]|in(?:ch)?\\b)", RegexOptions.IgnoreCase);
            if (matches.Count != 1) return null;
            string token = matches[0].Groups[1].Value.Trim();
            double result = 0;
            foreach (string part in token.Split(new[] {' '}, StringSplitOptions.RemoveEmptyEntries))
            {
                string[] fraction = part.Split('/');
                double a;
                if (!double.TryParse(fraction[0], NumberStyles.Float, CultureInfo.InvariantCulture, out a)) return null;
                if (fraction.Length == 2)
                {
                    double b;
                    if (!double.TryParse(fraction[1], NumberStyles.Float, CultureInfo.InvariantCulture, out b) || b <= 0) return null;
                    a /= b;
                }
                result += a;
            }
            return Finite(result) && result > 0 ? (double?)result : null;
        }

        public static bool Inside(double x, double y, IList<double[]> ring)
        {
            bool inside = false;
            for (int i=0, j=ring.Count-1; i<ring.Count; j=i++)
                if ((ring[i][1]>y)!=(ring[j][1]>y) && x < (ring[j][0]-ring[i][0])*(y-ring[i][1])/(ring[j][1]-ring[i][1])+ring[i][0]) inside=!inside;
            return inside;
        }

        public static double EdgeDistance(double x, double y, IList<double[]> ring)
        {
            double best = double.PositiveInfinity;
            for (int i=0; i<ring.Count; i++)
            {
                var a=ring[i]; var b=ring[(i+1)%ring.Count];
                double dx=b[0]-a[0], dy=b[1]-a[1], length=dx*dx+dy*dy;
                double t=length==0 ? 0 : Math.Max(0, Math.Min(1, ((x-a[0])*dx+(y-a[1])*dy)/length));
                best=Math.Min(best, Distance(x,y,a[0]+t*dx,a[1]+t*dy));
            }
            return best;
        }

        public static bool DiskInside(double x, double y, double radius, IList<double[]> boundary, IList<List<double[]>> holes)
        {
            if (!Inside(x,y,boundary) || EdgeDistance(x,y,boundary)<radius) return false;
            return holes.All(h=>!Inside(x,y,h) && EdgeDistance(x,y,h)>=radius);
        }
    }
}
