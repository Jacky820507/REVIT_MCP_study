using Autodesk.Revit.DB;

// Revit 2025+ 將 ElementId 從 int 改為 long
// 使用 IdType alias 和 GetIdValue() 擴充方法，同時支援 2020-2026
#if REVIT2025_OR_GREATER
using IdType = System.Int64;
#else
using IdType = System.Int32;
#endif

namespace RevitMCP.Core
{
    /// <summary>
    /// Revit API 跨版本相容性工具
    /// Nice3point.Revit.Sdk 會自動定義 REVIT2025_OR_GREATER 等預處理器符號
    /// </summary>
    internal static class RevitCompatibility
    {
        /// <summary>
        /// 取得 ElementId 的數值（2022-2024 回傳 int，2025+ 回傳 long）
        /// </summary>
        internal static IdType GetIdValue(this ElementId id)
        {
#if REVIT2025_OR_GREATER
            return id.Value;
#else
            return id.IntegerValue;
#endif
        }

        /// <summary>
        /// 從數值建立 ElementId（相容 2020-2026）
        /// </summary>
        internal static ElementId ToElementId(this IdType value)
        {
#if REVIT2024_OR_GREATER
            return new ElementId(value);
#else
            return new ElementId((int)value);
#endif
        }

        /// <summary>
        /// 取得品類的 BuiltInCategory（2023 以前不支援直接存取）
        /// </summary>
        internal static BuiltInCategory GetBuiltInCategory(this Category cat)
        {
#if REVIT2023_OR_GREATER
            return cat.BuiltInCategory;
#else
            return (BuiltInCategory)cat.Id.GetIdValue();
#endif
        }

        /// <summary>
        /// 檢查參數定義是否為數值類型
        /// </summary>
        internal static bool IsNumeric(this Definition def)
        {
#if REVIT2022_OR_GREATER
            var dataType = def.GetDataType();
            return dataType == Autodesk.Revit.DB.SpecTypeId.Number || 
                   dataType == Autodesk.Revit.DB.SpecTypeId.Int.Integer ||
                   dataType == Autodesk.Revit.DB.SpecTypeId.Length;
#else
            return def.ParameterType == ParameterType.Number || 
                   def.ParameterType == ParameterType.Integer ||
                   def.ParameterType == ParameterType.Length;
#endif
        }
    }
}
