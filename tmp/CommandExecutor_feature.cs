using System;
using System.Collections.Generic;
using System.Linq;
using Autodesk.Revit.DB;
using Autodesk.Revit.DB.Architecture;
using Autodesk.Revit.UI;
using Newtonsoft.Json.Linq;
using RevitMCP.Models;

// Revit 2025+ ElementId: int → long
#if REVIT2025_OR_GREATER
using IdType = System.Int64;
#else
using IdType = System.Int32;
#endif

namespace RevitMCP.Core
{
    /// <summary>
    /// 命令執行器 - 執行各種 Revit 操作
    /// </summary>
    public class CommandExecutor
    {
        private readonly UIApplication _uiApp;

        public CommandExecutor(UIApplication uiApp)
        {
            _uiApp = uiApp ?? throw new ArgumentNullException(nameof(uiApp));
        }

        /// <summary>
        /// 共用方法：查找樓層
        /// </summary>
        private Level FindLevel(Document doc, string levelName, bool useFirstIfNotFound = true)
        {
            var level = new FilteredElementCollector(doc)
                .OfClass(typeof(Level))
                .Cast<Level>()
                .FirstOrDefault(l => l.Name == levelName || l.Name.Contains(levelName) || levelName.Contains(l.Name));

            if (level == null && useFirstIfNotFound)
            {
                level = new FilteredElementCollector(doc)
                    .OfClass(typeof(Level))
                    .Cast<Level>()
                    .OrderBy(l => l.Elevation)
                    .FirstOrDefault();
            }

            if (level == null)
            {
                throw new Exception($"找不到樓層: {levelName}");
            }

            return level;
        }

        /// <summary>
        /// 執行命令
        /// </summary>
        public RevitCommandResponse ExecuteCommand(RevitCommandRequest request)
        {
            try
            {
                var parameters = request.Parameters as JObject ?? new JObject();
                object result = null;

                switch (request.CommandName.ToLower())
                {
                    case "create_wall":
                        result = CreateWall(parameters);
                        break;
                    
                    case "get_project_info":
                        result = GetProjectInfo();
                        break;

                    
                    case "create_floor":
                        result = CreateFloor(parameters);
                        break;
                    
                    case "get_all_levels":
                        result = GetAllLevels();
                        break;
                    
                    case "get_element_info":
                        result = GetElementInfo(parameters);
                        break;
                    
                    case "delete_element":
                        result = DeleteElement(parameters);
                        break;
                    
                    case "modify_element_parameter":
                        result = ModifyElementParameter(parameters);
                        break;
                    
                    case "create_door":
                        result = CreateDoor(parameters);
                        break;
                    
                    case "create_window":
                        result = CreateWindow(parameters);
                        break;
                    
                    case "get_all_grids":
                        result = GetAllGrids();
                        break;
                    
                    case "get_column_types":
                        result = GetColumnTypes(parameters);
                        break;
                    
                    case "create_column":
                        result = CreateColumn(parameters);
                        break;
                    
                    case "get_furniture_types":
                        result = GetFurnitureTypes(parameters);
                        break;
                    
                    case "place_furniture":
                        result = PlaceFurniture(parameters);
                        break;
                    
                    case "get_room_info":
                        result = GetRoomInfo(parameters);
                        break;
                    
                    case "get_rooms_by_level":
                        result = GetRoomsByLevel(parameters);
                        break;
                    
                    case "get_all_views":
                        result = GetAllViews(parameters);
                        break;
                    
                    case "get_active_view":
                        result = GetActiveView();
                        break;
                    
                    case "set_active_view":
                        result = SetActiveView(parameters);
                        break;
                    case "select_element":
                        result = SelectElement(parameters);
                        break;
                    case "zoom_to_element":
                        result = ZoomToElement(parameters);
                        break;
                    case "measure_distance":
                        result = MeasureDistance(parameters);
                        break;
                    case "get_wall_info":
                        result = GetWallInfo(parameters);
                        break;
                    case "create_dimension":
                        result = CreateDimension(parameters);
                        break;
                    case "create_dimension_by_ray":
                        result = CreateDimensionByRay(parameters);
                        break;
                    case "create_dimension_by_bounding_box":
                        result = CreateDimensionByBoundingBox(parameters);
                        break;
                    case "create_dimension_by_ray_debug":
                        result = CreateDimensionByRay_Debug(parameters);
                        break;
                    case "query_walls_by_location":
                        result = QueryWallsByLocation(parameters);
                        break;
                    case "query_elements":
                    case "query_elements_with_filter":
                        result = QueryElements(parameters);
                        break;
                    case "get_active_schema":
                        result = GetActiveSchema(parameters);
                        break;
                    case "get_category_fields":
                        result = GetCategoryFields(parameters);
                        break;
                    case "get_field_values":
                        result = GetFieldValues(parameters);
                        break;
                    case "override_element_graphics":
                        result = OverrideElementGraphics(parameters);
                        break;
                    case "clear_element_override":
                        result = ClearElementOverride(parameters);
                        break;
                    case "unjoin_wall_joins":
                        result = UnjoinWallJoins(parameters);
                        break;
                    case "rejoin_wall_joins":
                        result = RejoinWallJoins(parameters);
                        break;
                    case "check_exterior_wall_openings":
                        result = CheckExteriorWallOpenings(parameters);
                        break;
                    case "get_room_daylight_info":
                        result = GetRoomDaylightInfo(parameters);
                        break;
                    case "get_view_templates":
                        result = GetViewTemplates(parameters);
                        break;
                    case "get_viewport_map":
                        result = GetViewportMap();
                        break;
                    case "get_wall_types":
                        result = GetWallTypes(parameters);
                        break;
                    case "change_element_type":
                        result = ChangeElementType(parameters);
                        break;
                    case "get_titleblocks":
                        result = GetTitleBlocks();
                        break;
                    case "create_sheets":
                        result = CreateSheets(parameters);
                        break;
                    case "get_all_sheets":
                        result = GetAllSheets();
                        break;
                    case "auto_renumber_sheets":
                        result = AutoRenumberSheets(parameters);
                        break;
                    case "get_detail_components":
                        result = GetDetailComponents(parameters);
                        break;
                    case "get_schedules":
                        result = GetSchedules(parameters);
                        break;
                    case "sync_detail_component_numbers":
                        result = SyncDetailComponentNumbers();
                        break;
                    case "create_detail_component_type":
                        result = CreateDetailComponentType(parameters);
                        break;
                    case "calculate_grid_bounds":
                        result = CalculateGridBounds(parameters);
                        break;
                    case "create_dependent_views":
                        result = CreateDependentViews(parameters);
                        break;
                    case "create_detail_lines":
                        result = CreateDetailLines(parameters);
                        break;
                    case "list_family_symbols":
                        result = ListFamilySymbols(parameters);
                        break;
                    case "get_line_styles":
                        result = GetLineStyles();
                        break;
                    case "trace_stair_geometry":
                        result = TraceStairGeometry(parameters);
                        break;
                    default:
                        throw new NotImplementedException($"未實作的命令: {request.CommandName}");
                }

                return new RevitCommandResponse
                {
                    Success = true,
                    Data = result,
                    RequestId = request.RequestId
                };
            }
            catch (Exception ex)
            {
                return new RevitCommandResponse
                {
                    Success = false,
                    Error = ex.Message,
                    RequestId = request.RequestId
                };
            }
        }

        #region 命令實作

        /// <summary>
        /// 建立牆
        /// </summary>
        private object CreateWall(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            double startX = parameters["startX"]?.Value<double>() ?? 0;
            double startY = parameters["startY"]?.Value<double>() ?? 0;
            double endX = parameters["endX"]?.Value<double>() ?? 0;
            double endY = parameters["endY"]?.Value<double>() ?? 0;
            double height = parameters["height"]?.Value<double>() ?? 3000;

            // 轉換為英尺 (Revit 內部單位)
            XYZ start = new XYZ(startX / 304.8, startY / 304.8, 0);
            XYZ end = new XYZ(endX / 304.8, endY / 304.8, 0);

            using (Transaction trans = new Transaction(doc, "建立牆"))
            {
                trans.Start();

                // 建立線
                Line line = Line.CreateBound(start, end);

                // 取得預設樓層
                Level level = new FilteredElementCollector(doc)
                    .OfClass(typeof(Level))
                    .Cast<Level>()
                    .FirstOrDefault();

                if (level == null)
                {
                    throw new Exception("找不到樓層");
                }

                // 建立牆
                Wall wall = Wall.Create(doc, line, level.Id, false);
                
                // 設定高度
                Parameter heightParam = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
                if (heightParam != null && !heightParam.IsReadOnly)
                {
                    heightParam.Set(height / 304.8);
                }

                trans.Commit();

                return new
                {
                    ElementId = wall.Id.GetIdValue(),
                    Message = $"成功建立牆，ID: {wall.Id.GetIdValue()}"
                };
            }
        }

        /// <summary>
        /// 取得專案資訊
        /// </summary>
        private object GetProjectInfo()
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            ProjectInfo projInfo = doc.ProjectInformation;

            return new
            {
                ProjectName = doc.Title,
                BuildingName = projInfo.BuildingName,
                OrganizationName = projInfo.OrganizationName,
                Author = projInfo.Author,
                Address = projInfo.Address,
                ClientName = projInfo.ClientName,
                ProjectNumber = projInfo.Number,
                ProjectStatus = projInfo.Status
            };
        }

        /// <summary>
        /// 取得所有樓層
        /// </summary>
        private object GetAllLevels()
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            var levels = new FilteredElementCollector(doc)
                .OfClass(typeof(Level))
                .Cast<Level>()
                .OrderBy(l => l.Elevation)
                .Select(l => new
                {
                    ElementId = l.Id.GetIdValue(),
                    Name = l.Name,
                    Elevation = Math.Round(l.Elevation * 304.8, 2) // 轉換為公釐
                })
                .ToList();

            return new
            {
                Count = levels.Count,
                Levels = levels
            };
        }

        /// <summary>
        /// 取得元素資訊
        /// </summary>
        private object GetElementInfo(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType elementId = parameters["elementId"]?.Value<IdType>() ?? 0;

            Element element = doc.GetElement(elementId.ToElementId());
            if (element == null)
            {
                throw new Exception($"找不到元素 ID: {elementId}");
            }

            var parameterList = new List<object>();
            foreach (Parameter param in element.Parameters)
            {
                if (param.HasValue)
                {
                    parameterList.Add(new
                    {
                        Name = param.Definition.Name,
                        Value = param.AsValueString() ?? param.AsString(),
                        Type = param.StorageType.ToString()
                    });
                }
            }

            return new
            {
                ElementId = element.Id.GetIdValue(),
                Name = element.Name,
                Category = element.Category?.Name,
                Type = doc.GetElement(element.GetTypeId())?.Name,
                Level = doc.GetElement(element.LevelId)?.Name,
                Parameters = parameterList
            };
        }

        /// <summary>
        /// 刪除元素
        /// </summary>
        private object DeleteElement(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType elementId = parameters["elementId"]?.Value<IdType>() ?? 0;

            using (Transaction trans = new Transaction(doc, "刪除元素"))
            {
                trans.Start();

                Element element = doc.GetElement(elementId.ToElementId());
                if (element == null)
                {
                    throw new Exception($"找不到元素 ID: {elementId}");
                }

                doc.Delete(elementId.ToElementId());
                trans.Commit();

                return new
                {
                    Message = $"成功刪除元素 ID: {elementId}"
                };
            }
        }

        /// <summary>
        /// 建立樓板
        /// </summary>
        private object CreateFloor(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            
            var pointsArray = parameters["points"] as JArray;
            string levelName = parameters["levelName"]?.Value<string>() ?? "Level 1";
            
            if (pointsArray == null || pointsArray.Count < 3)
            {
                throw new Exception("需要至少 3 個點來建立樓板");
            }

            using (Transaction trans = new Transaction(doc, "建立樓板"))
            {
                trans.Start();

                // 取得樓層
                Level level = FindLevel(doc, levelName, true);

                // 取得建立點
                var points = pointsArray.Select(p => new XYZ(
                    p["x"]?.Value<double>() / 304.8 ?? 0,
                    p["y"]?.Value<double>() / 304.8 ?? 0,
                    0
                )).ToList();

                // 取得預設樓板類型
                FloorType floorType = new FilteredElementCollector(doc)
                    .OfClass(typeof(FloorType))
                    .Cast<FloorType>()
                    .FirstOrDefault(x => x.IsFoundationSlab == false);

                if (floorType == null)
                {
                    floorType = new FilteredElementCollector(doc)
                        .OfClass(typeof(FloorType))
                        .Cast<FloorType>()
                        .FirstOrDefault();
                }

                if (floorType == null)
                {
                    throw new Exception("找不到樓板類型");
                }

#if REVIT2020
                // Revit 2020: 使用 Create.NewFloor (CurveArray)
                CurveArray curveArray = new CurveArray();
                for (int i = 0; i < points.Count; i++)
                {
                    XYZ start = points[i];
                    XYZ end = points[(i + 1) % points.Count];
                    curveArray.Append(Line.CreateBound(start, end));
                }

                // NewFloor (CurveArray profile, bool structural) 
                // 注意: 舊版 API 很多變種，這是常見的一種
                Floor floor = doc.Create.NewFloor(curveArray, false);
                
                // 設定參數 (如果需要)
                Parameter pLevel = floor.get_Parameter(BuiltInParameter.LEVEL_PARAM);
                if(pLevel != null && !pLevel.IsReadOnly) 
                {
                   pLevel.Set(level.Id);
                }
#else
                // Revit 2022+: 使用 CurveLoop
                CurveLoop curveLoop = new CurveLoop();
                for (int i = 0; i < points.Count; i++)
                {
                    XYZ start = points[i];
                    XYZ end = points[(i + 1) % points.Count];
                    curveLoop.Append(Line.CreateBound(start, end));
                }

                // 使用 Floor.Create (適用於 Revit 2022+)
                Floor floor = Floor.Create(doc, new List<CurveLoop> { curveLoop }, floorType.Id, level.Id);
#endif

                trans.Commit();

                return new
                {
                    ElementId = floor.Id.GetIdValue(),
                    Level = level.Name,
                    Message = $"成功建立樓板，ID: {floor.Id.GetIdValue()}"
                };
            }
        }


        /// <summary>
        /// 修改元素參數
        /// </summary>
        private object ModifyElementParameter(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType elementId = parameters["elementId"]?.Value<IdType>() ?? 0;
            string parameterName = parameters["parameterName"]?.Value<string>();
            string value = parameters["value"]?.Value<string>();

            if (string.IsNullOrEmpty(parameterName))
            {
                throw new Exception("請指定參數名稱");
            }

            Element element = doc.GetElement(elementId.ToElementId());
            if (element == null)
            {
                throw new Exception($"找不到元素 ID: {elementId}");
            }

            using (Transaction trans = new Transaction(doc, "修改參數"))
            {
                trans.Start();

                // 特別處理：修改元素名稱 (Element.Name)
                if (parameterName.Equals("Name", StringComparison.OrdinalIgnoreCase))
                {
                    element.Name = value;
                    trans.Commit();
                    return new
                    {
                        ElementId = elementId,
                        ParameterName = parameterName,
                        NewValue = value,
                        Message = $"成功將元素名稱修改為 {value}"
                    };
                }

                Parameter param = null;
                if (parameterName == "Sheet Number" || parameterName == "圖紙編號" || parameterName == "SheetNumber")
                {
                    param = element.get_Parameter(BuiltInParameter.SHEET_NUMBER);
                }
                else
                {
                    param = element.LookupParameter(parameterName);
                }

                if (param == null)
                {
                    throw new Exception($"找不到參數: {parameterName}");
                }

                if (param.IsReadOnly)
                {
                    throw new Exception($"參數 {parameterName} 是唯讀的");
                }

                bool success = false;
                switch (param.StorageType)
                {
                    case StorageType.String:
                        success = param.Set(value);
                        break;
                    case StorageType.Double:
                        if (double.TryParse(value, out double dVal))
                            success = param.Set(dVal);
                        break;
                    case StorageType.Integer:
                        if (int.TryParse(value, out int iVal))
                            success = param.Set(iVal);
                        break;
                    default:
                        throw new Exception($"不支援的參數類型: {param.StorageType}");
                }

                if (!success)
                {
                    throw new Exception($"設定參數失敗");
                }

                trans.Commit();

                return new
                {
                    ElementId = elementId,
                    ParameterName = parameterName,
                    NewValue = value,
                    Message = $"成功修改參數 {parameterName}"
                };
            }
        }

        /// <summary>
        /// 建立門
        /// </summary>
        private object CreateDoor(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType wallId = parameters["wallId"]?.Value<IdType>() ?? 0;
            double locationX = parameters["locationX"]?.Value<double>() ?? 0;
            double locationY = parameters["locationY"]?.Value<double>() ?? 0;

            Wall wall = doc.GetElement(wallId.ToElementId()) as Wall;
            if (wall == null)
            {
                throw new Exception($"找不到牆 ID: {wallId}");
            }

            using (Transaction trans = new Transaction(doc, "建立門"))
            {
                trans.Start();

                // 取得門類型
                FamilySymbol doorSymbol = new FilteredElementCollector(doc)
                    .OfClass(typeof(FamilySymbol))
                    .OfCategory(BuiltInCategory.OST_Doors)
                    .Cast<FamilySymbol>()
                    .FirstOrDefault();

                if (doorSymbol == null)
                {
                    throw new Exception("找不到門類型");
                }

                if (!doorSymbol.IsActive)
                {
                    doorSymbol.Activate();
                    doc.Regenerate();
                }

                // 取得牆的樓層
                Level level = doc.GetElement(wall.LevelId) as Level;
                XYZ location = new XYZ(locationX / 304.8, locationY / 304.8, level?.Elevation ?? 0);

                FamilyInstance door = doc.Create.NewFamilyInstance(
                    location, doorSymbol, wall, level, 
                    Autodesk.Revit.DB.Structure.StructuralType.NonStructural);

                trans.Commit();

                return new
                {
                    ElementId = door.Id.GetIdValue(),
                    DoorType = doorSymbol.Name,
                    WallId = wallId,
                    Message = $"成功建立門，ID: {door.Id.GetIdValue()}"
                };
            }
        }

        /// <summary>
        /// 建立窗
        /// </summary>
        private object CreateWindow(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType wallId = parameters["wallId"]?.Value<IdType>() ?? 0;
            double locationX = parameters["locationX"]?.Value<double>() ?? 0;
            double locationY = parameters["locationY"]?.Value<double>() ?? 0;

            Wall wall = doc.GetElement(wallId.ToElementId()) as Wall;
            if (wall == null)
            {
                throw new Exception($"找不到牆 ID: {wallId}");
            }

            using (Transaction trans = new Transaction(doc, "建立窗"))
            {
                trans.Start();

                // 取得窗類型
                FamilySymbol windowSymbol = new FilteredElementCollector(doc)
                    .OfClass(typeof(FamilySymbol))
                    .OfCategory(BuiltInCategory.OST_Windows)
                    .Cast<FamilySymbol>()
                    .FirstOrDefault();

                if (windowSymbol == null)
                {
                    throw new Exception("找不到窗類型");
                }

                if (!windowSymbol.IsActive)
                {
                    windowSymbol.Activate();
                    doc.Regenerate();
                }

                // 取得牆的樓層
                Level level = doc.GetElement(wall.LevelId) as Level;
                XYZ location = new XYZ(locationX / 304.8, locationY / 304.8, (level?.Elevation ?? 0) + 3); // 窗戶高度 3 英尺

                FamilyInstance window = doc.Create.NewFamilyInstance(
                    location, windowSymbol, wall, level,
                    Autodesk.Revit.DB.Structure.StructuralType.NonStructural);

                trans.Commit();

                return new
                {
                    ElementId = window.Id.GetIdValue(),
                    WindowType = windowSymbol.Name,
                    WallId = wallId,
                    Message = $"成功建立窗，ID: {window.Id.GetIdValue()}"
                };
            }
        }

        /// <summary>
        /// 取得所有網格線
        /// </summary>
        private object GetAllGrids()
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            var grids = new FilteredElementCollector(doc)
                .OfClass(typeof(Grid))
                .Cast<Grid>()
                .Select(g =>
                {
                    // 取得 Grid 的曲線（通常是直線）
                    Curve curve = g.Curve;
                    XYZ startPoint = curve.GetEndPoint(0);
                    XYZ endPoint = curve.GetEndPoint(1);

                    // 判斷方向（水平或垂直）
                    double dx = Math.Abs(endPoint.X - startPoint.X);
                    double dy = Math.Abs(endPoint.Y - startPoint.Y);
                    string direction = dx > dy ? "水平" : "垂直";

                    return new
                    {
                        ElementId = g.Id.GetIdValue(),
                        Name = g.Name,
                        Direction = direction,
                        StartX = Math.Round(startPoint.X * 304.8, 2),  // 英尺 → 公釐
                        StartY = Math.Round(startPoint.Y * 304.8, 2),
                        EndX = Math.Round(endPoint.X * 304.8, 2),
                        EndY = Math.Round(endPoint.Y * 304.8, 2)
                    };
                })
                .OrderBy(g => g.Name)
                .ToList();

            return new
            {
                Count = grids.Count,
                Grids = grids
            };
        }

        /// <summary>
        /// 取得柱類型
        /// </summary>
        private object GetColumnTypes(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            string materialFilter = parameters["material"]?.Value<string>();

            // 查詢結構柱和建築柱的 FamilySymbol
            var columnTypes = new FilteredElementCollector(doc)
                .OfClass(typeof(FamilySymbol))
                .Cast<FamilySymbol>()
                .Where(fs => fs.Category != null && 
                    (fs.Category.Id.GetIdValue() == (IdType)BuiltInCategory.OST_Columns ||
                     fs.Category.Id.GetIdValue() == (IdType)BuiltInCategory.OST_StructuralColumns))
                .Select(fs =>
                {
                    // 嘗試取得尺寸參數
                    double width = 0, depth = 0;
                    
                    // 常見的柱尺寸參數名稱
                    Parameter widthParam = fs.LookupParameter("寬度") ?? 
                                          fs.LookupParameter("Width") ?? 
                                          fs.LookupParameter("b");
                    Parameter depthParam = fs.LookupParameter("深度") ?? 
                                          fs.LookupParameter("Depth") ?? 
                                          fs.LookupParameter("h");
                    
                    if (widthParam != null && widthParam.HasValue)
                        width = Math.Round(widthParam.AsDouble() * 304.8, 0);  // 轉公釐
                    if (depthParam != null && depthParam.HasValue)
                        depth = Math.Round(depthParam.AsDouble() * 304.8, 0);

                    return new
                    {
                        ElementId = fs.Id.GetIdValue(),
                        TypeName = fs.Name,
                        FamilyName = fs.FamilyName,
                        Category = fs.Category?.Name,
                        Width = width,
                        Depth = depth,
                        SizeDescription = width > 0 && depth > 0 ? $"{width}x{depth}" : "未知尺寸"
                    };
                })
                .Where(ct => string.IsNullOrEmpty(materialFilter) || 
                             ct.FamilyName.Contains(materialFilter) || 
                             ct.TypeName.Contains(materialFilter))
                .OrderBy(ct => ct.FamilyName)
                .ThenBy(ct => ct.TypeName)
                .ToList();

            return new
            {
                Count = columnTypes.Count,
                ColumnTypes = columnTypes
            };
        }

        /// <summary>
        /// 建立柱子
        /// </summary>
        private object CreateColumn(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            // 解析參數
            double x = parameters["x"]?.Value<double>() ?? 0;
            double y = parameters["y"]?.Value<double>() ?? 0;
            string bottomLevelName = parameters["bottomLevel"]?.Value<string>() ?? "Level 1";
            string topLevelName = parameters["topLevel"]?.Value<string>();
            string columnTypeName = parameters["columnType"]?.Value<string>();

            // 轉換座標（公釐 → 英尺）
            XYZ location = new XYZ(x / 304.8, y / 304.8, 0);

            using (Transaction trans = new Transaction(doc, "建立柱子"))
            {
                trans.Start();

                // 取得底部樓層
                Level bottomLevel = FindLevel(doc, bottomLevelName, true);

                // 取得柱類型（FamilySymbol）
                FamilySymbol columnSymbol = new FilteredElementCollector(doc)
                    .OfClass(typeof(FamilySymbol))
                    .Cast<FamilySymbol>()
                    .Where(fs => fs.Category != null &&
                        (fs.Category.Id.GetIdValue() == (IdType)BuiltInCategory.OST_Columns ||
                         fs.Category.Id.GetIdValue() == (IdType)BuiltInCategory.OST_StructuralColumns))
                    .FirstOrDefault(fs => string.IsNullOrEmpty(columnTypeName) || 
                                          fs.Name == columnTypeName ||
                                          fs.FamilyName.Contains(columnTypeName));

                if (columnSymbol == null)
                {
                    throw new Exception(string.IsNullOrEmpty(columnTypeName) 
                        ? "專案中沒有可用的柱類型" 
                        : $"找不到柱類型: {columnTypeName}");
                }

                // 確保 FamilySymbol 已啟用
                if (!columnSymbol.IsActive)
                {
                    columnSymbol.Activate();
                    doc.Regenerate();
                }

                // 建立柱子
                FamilyInstance column = doc.Create.NewFamilyInstance(
                    location,
                    columnSymbol,
                    bottomLevel,
                    Autodesk.Revit.DB.Structure.StructuralType.Column
                );

                // 設定頂部樓層（如果有指定）
                if (!string.IsNullOrEmpty(topLevelName))
                {
                    Level topLevel = new FilteredElementCollector(doc)
                        .OfClass(typeof(Level))
                        .Cast<Level>()
                        .FirstOrDefault(l => l.Name == topLevelName);

                    if (topLevel != null)
                    {
                        Parameter topLevelParam = column.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM);
                        if (topLevelParam != null && !topLevelParam.IsReadOnly)
                        {
                            topLevelParam.Set(topLevel.Id);
                        }
                    }
                }

                trans.Commit();

                return new
                {
                    ElementId = column.Id.GetIdValue(),
                    ColumnType = columnSymbol.Name,
                    FamilyName = columnSymbol.FamilyName,
                    Level = bottomLevel.Name,
                    LocationX = x,
                    LocationY = y,
                    Message = $"成功建立柱子，ID: {column.Id.GetIdValue()}"
                };
            }
        }

        /// <summary>
        /// 取得家具類型
        /// </summary>
        private object GetFurnitureTypes(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            string categoryFilter = parameters["category"]?.Value<string>();

            var furnitureTypes = new FilteredElementCollector(doc)
                .OfClass(typeof(FamilySymbol))
                .OfCategory(BuiltInCategory.OST_Furniture)
                .Cast<FamilySymbol>()
                .Select(fs => new
                {
                    ElementId = fs.Id.GetIdValue(),
                    TypeName = fs.Name,
                    FamilyName = fs.FamilyName,
                    IsActive = fs.IsActive
                })
                .Where(ft => string.IsNullOrEmpty(categoryFilter) ||
                             ft.FamilyName.Contains(categoryFilter) ||
                             ft.TypeName.Contains(categoryFilter))
                .OrderBy(ft => ft.FamilyName)
                .ThenBy(ft => ft.TypeName)
                .ToList();

            return new
            {
                Count = furnitureTypes.Count,
                FurnitureTypes = furnitureTypes
            };
        }

        /// <summary>
        /// 放置家具
        /// </summary>
        private object PlaceFurniture(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            double x = parameters["x"]?.Value<double>() ?? 0;
            double y = parameters["y"]?.Value<double>() ?? 0;
            string furnitureTypeName = parameters["furnitureType"]?.Value<string>();
            string levelName = parameters["level"]?.Value<string>() ?? "Level 1";
            double rotation = parameters["rotation"]?.Value<double>() ?? 0;

            // 轉換座標（公釐 → 英尺）
            XYZ location = new XYZ(x / 304.8, y / 304.8, 0);

            using (Transaction trans = new Transaction(doc, "放置家具"))
            {
                trans.Start();

                // 取得樓層
                Level level = FindLevel(doc, levelName, true);

                // 取得家具類型
                FamilySymbol furnitureSymbol = new FilteredElementCollector(doc)
                    .OfClass(typeof(FamilySymbol))
                    .OfCategory(BuiltInCategory.OST_Furniture)
                    .Cast<FamilySymbol>()
                    .FirstOrDefault(fs => fs.Name == furnitureTypeName ||
                                          fs.FamilyName.Contains(furnitureTypeName));

                if (furnitureSymbol == null)
                {
                    throw new Exception($"找不到家具類型: {furnitureTypeName}");
                }

                // 確保 FamilySymbol 已啟用
                if (!furnitureSymbol.IsActive)
                {
                    furnitureSymbol.Activate();
                    doc.Regenerate();
                }

                // 放置家具
                FamilyInstance furniture = doc.Create.NewFamilyInstance(
                    location,
                    furnitureSymbol,
                    level,
                    Autodesk.Revit.DB.Structure.StructuralType.NonStructural
                );

                // 旋轉
                if (Math.Abs(rotation) > 0.001)
                {
                    Line axis = Line.CreateBound(location, location + XYZ.BasisZ);
                    ElementTransformUtils.RotateElement(doc, furniture.Id, axis, rotation * Math.PI / 180);
                }

                trans.Commit();

                return new
                {
                    ElementId = furniture.Id.GetIdValue(),
                    FurnitureType = furnitureSymbol.Name,
                    FamilyName = furnitureSymbol.FamilyName,
                    Level = level.Name,
                    LocationX = x,
                    LocationY = y,
                    Rotation = rotation,
                    Message = $"成功放置家具，ID: {furniture.Id.GetIdValue()}"
                };
            }
        }

        /// <summary>
        /// 取得房間資訊
        /// </summary>
        private object GetRoomInfo(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType? roomId = parameters["roomId"]?.Value<IdType>();
            string roomName = parameters["roomName"]?.Value<string>();

            Room room = null;

            if (roomId.HasValue)
            {
                room = doc.GetElement(roomId.Value.ToElementId()) as Room;
            }
            else if (!string.IsNullOrEmpty(roomName))
            {
                room = new FilteredElementCollector(doc)
                    .OfCategory(BuiltInCategory.OST_Rooms)
                    .WhereElementIsNotElementType()
                    .Cast<Room>()
                    .FirstOrDefault(r => r.Name.Contains(roomName) || 
                                         r.get_Parameter(BuiltInParameter.ROOM_NAME)?.AsString()?.Contains(roomName) == true);
            }

            if (room == null)
            {
                throw new Exception(roomId.HasValue 
                    ? $"找不到房間 ID: {roomId}" 
                    : $"找不到房間名稱包含: {roomName}");
            }

            // 取得房間位置點
            LocationPoint locPoint = room.Location as LocationPoint;
            XYZ center = locPoint?.Point ?? XYZ.Zero;

            // 取得 BoundingBox
            BoundingBoxXYZ bbox = room.get_BoundingBox(null);
            
            // 取得面積
            double area = room.Area * 0.092903; // 平方英尺 → 平方公尺

            return new
            {
                ElementId = room.Id.GetIdValue(),
                Name = room.get_Parameter(BuiltInParameter.ROOM_NAME)?.AsString(),
                Number = room.Number,
                Level = doc.GetElement(room.LevelId)?.Name,
                Area = Math.Round(area, 2),
                CenterX = Math.Round(center.X * 304.8, 2),
                CenterY = Math.Round(center.Y * 304.8, 2),
                CenterZ = Math.Round(center.Z * 304.8, 2),
                BoundingBox = bbox != null ? new
                {
                    MinX = Math.Round(bbox.Min.X * 304.8, 2),
                    MinY = Math.Round(bbox.Min.Y * 304.8, 2),
                    MaxX = Math.Round(bbox.Max.X * 304.8, 2),
                    MaxY = Math.Round(bbox.Max.Y * 304.8, 2)
                } : null
            };
        }

        /// <summary>
        /// 取得樓層房間清單
        /// </summary>
        private object GetRoomsByLevel(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            string levelName = parameters["level"]?.Value<string>();
            bool includeUnnamed = parameters["includeUnnamed"]?.Value<bool>() ?? true;

            if (string.IsNullOrEmpty(levelName))
            {
                throw new Exception("請指定樓層名稱");
            }

            // 取得指定樓層
            Level targetLevel = FindLevel(doc, levelName, false);

            // 取得該樓層的所有房間
            var rooms = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Rooms)
                .WhereElementIsNotElementType()
                .Cast<Room>()
                .Where(r => r.LevelId == targetLevel.Id)
                .Where(r => r.Area > 0) // 排除面積為 0 的房間（未封閉）
                .Select(r => 
                {
                    string roomName = r.get_Parameter(BuiltInParameter.ROOM_NAME)?.AsString();
                    bool hasName = !string.IsNullOrEmpty(roomName) && roomName != "房間";
                    
                    // 取得房間中心點
                    LocationPoint locPoint = r.Location as LocationPoint;
                    XYZ center = locPoint?.Point ?? XYZ.Zero;
                    
                    // 取得面積（平方英尺 → 平方公尺）
                    double areaM2 = r.Area * 0.092903;
                    
                    return new
                    {
                        ElementId = r.Id.GetIdValue(),
                        Name = roomName ?? "未命名",
                        Number = r.Number,
                        Area = Math.Round(areaM2, 2),
                        HasName = hasName,
                        CenterX = Math.Round(center.X * 304.8, 2),
                        CenterY = Math.Round(center.Y * 304.8, 2)
                    };
                })
                .Where(r => includeUnnamed || r.HasName)
                .OrderBy(r => r.Number)
                .ToList();

            // 計算統計
            double totalArea = rooms.Sum(r => r.Area);
            int roomsWithName = rooms.Count(r => r.HasName);
            int roomsWithoutName = rooms.Count(r => !r.HasName);

            return new
            {
                Level = targetLevel.Name,
                LevelId = targetLevel.Id.GetIdValue(),
                TotalRooms = rooms.Count,
                TotalArea = Math.Round(totalArea, 2),
                RoomsWithName = roomsWithName,
                RoomsWithoutName = roomsWithoutName,
                DataCompleteness = rooms.Count > 0 
                    ? $"{Math.Round((double)roomsWithName / rooms.Count * 100, 1)}%" 
                    : "N/A",
                Rooms = rooms
            };
        }

        /// <summary>
        /// 取得房間採光資訊
        /// </summary>
        private object GetRoomDaylightInfo(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            string levelName = parameters["level"]?.Value<string>();

            IEnumerable<Room> rooms;
            if (!string.IsNullOrEmpty(levelName))
            {
                Level level = FindLevel(doc, levelName, false);
                rooms = new FilteredElementCollector(doc)
                    .OfCategory(BuiltInCategory.OST_Rooms)
                    .WhereElementIsNotElementType()
                    .Cast<Room>()
                    .Where(r => r.LevelId == level.Id && r.Area > 0);
            }
            else
            {
                rooms = new FilteredElementCollector(doc)
                    .OfCategory(BuiltInCategory.OST_Rooms)
                    .WhereElementIsNotElementType()
                    .Cast<Room>()
                    .Where(r => r.Area > 0);
            }


            // 預先取得所有 Room Tags 並建立對照表 (RoomId -> List<TagId>)
            // 預先取得所有 Room Tags 並建立對照表 (RoomId -> List<TagId>)
            // 預先取得所有 Room Tags 並建立對照表 (RoomId -> List<TagId>)
            var roomTagCollector = new FilteredElementCollector(doc)
                .OfClass(typeof(SpatialElementTag))
                .WhereElementIsNotElementType()
                .Where(e => e is RoomTag)
                .Cast<RoomTag>();

            var roomTagMap = new Dictionary<IdType, List<IdType>>();
            foreach (var tag in roomTagCollector)
            {
                // 注意：Tag 可能沒有關聯的 Room (Orphaned)
                try {
                    // Tag.Room 屬性在某些視圖可能無效，或需用 Tag.IsOrphaned
                    if (tag.Room != null) 
                    {
                        IdType roomId = tag.Room.Id.GetIdValue();
                        if (!roomTagMap.ContainsKey(roomId))
                        {
                            roomTagMap[roomId] = new List<IdType>();
                        }
                        roomTagMap[roomId].Add(tag.Id.GetIdValue());
                    }
                } catch {}
            }

            var roomData = new List<object>();
            SpatialElementBoundaryOptions options = new SpatialElementBoundaryOptions();
            var globalProcessedIds = new HashSet<IdType>();

            foreach (Room room in rooms)
            {
                var openings = new List<object>();

                IList<IList<BoundarySegment>> segments = room.GetBoundarySegments(options);
                if (segments != null)
                {
                    foreach (IList<BoundarySegment> segmentList in segments)
                    {
                        foreach (BoundarySegment segment in segmentList)
                        {
                            Element element = doc.GetElement(segment.ElementId);
                            if (element is Wall wall)
                            {
                                IList<ElementId> insertIds = wall.FindInserts(true, false, false, false);
                                foreach (ElementId insertId in insertIds)
                                {
                                    if (globalProcessedIds.Contains(insertId.GetIdValue())) continue;

                                    Element insert = doc.GetElement(insertId);
                                    if (insert is FamilyInstance fi &&
                                        (fi.Category.Id.GetIdValue() == (IdType)BuiltInCategory.OST_Windows))
                                    {
                                        bool belongsToRoom = false;

                                        // Geometric check: is the window within this boundary segment's range?
                                        if (wall.Location is LocationCurve wallLocCurve && insert.Location is LocationPoint insertLoc)
                                        {
                                            Curve wallCurve = wallLocCurve.Curve;
                                            Curve segmentCurve = segment.GetCurve();

                                            IntersectionResult resStart = wallCurve.Project(segmentCurve.GetEndPoint(0));
                                            IntersectionResult resEnd = wallCurve.Project(segmentCurve.GetEndPoint(1));

                                            if (resStart != null && resEnd != null)
                                            {
                                                double tMin = Math.Min(resStart.Parameter, resEnd.Parameter);
                                                double tMax = Math.Max(resStart.Parameter, resEnd.Parameter);

                                                IntersectionResult resWindow = wallCurve.Project(insertLoc.Point);
                                                if (resWindow != null)
                                                {
                                                    double tWindow = resWindow.Parameter;
                                                    // 500mm tolerance to catch windows near segment boundaries
                                                    double tol = 500.0 / 304.8;
                                                    if (tWindow >= tMin - tol && tWindow <= tMax + tol)
                                                    {
                                                        belongsToRoom = true;
                                                    }
                                                }
                                            }
                                            else
                                            {
                                                // Fallback: projection failed, use Room API
                                                if (fi.FromRoom != null && fi.FromRoom.Id == room.Id) belongsToRoom = true;
                                                else if (fi.ToRoom != null && fi.ToRoom.Id == room.Id) belongsToRoom = true;
                                            }
                                        }
                                        else
                                        {
                                            // Non-curve wall fallback
                                            if (fi.FromRoom != null && fi.FromRoom.Id == room.Id) belongsToRoom = true;
                                            else if (fi.ToRoom != null && fi.ToRoom.Id == room.Id) belongsToRoom = true;
                                        }

                                        if (!belongsToRoom) continue;
                                        globalProcessedIds.Add(insertId.GetIdValue());

                                        bool isExterior = wall.WallType.Function == WallFunction.Exterior;

                                        const double FEET_TO_MM = 304.8;
                                        Element symbol = fi.Symbol;

                                        BuiltInParameter[] widthBips = new BuiltInParameter[] { BuiltInParameter.FAMILY_WIDTH_PARAM, BuiltInParameter.WINDOW_WIDTH };
                                        string[] widthNames = new string[] { "粗略寬度", "寬度", "Width", "寬" };

                                        BuiltInParameter[] heightBips = new BuiltInParameter[] { BuiltInParameter.FAMILY_HEIGHT_PARAM, BuiltInParameter.WINDOW_HEIGHT };
                                        string[] heightNames = new string[] { "粗略高度", "高度", "Height", "高" };

                                        BuiltInParameter[] sillBips = new BuiltInParameter[] { BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM };
                                        string[] sillNames = new string[] { "窗台高度", "Sill Height", "底高度", "窗臺高度" };

                                        BuiltInParameter[] headBips = new BuiltInParameter[] { BuiltInParameter.INSTANCE_HEAD_HEIGHT_PARAM };
                                        string[] headNames = new string[] { "窗頂高度", "Head Height", "頂高度" };

                                        double? wVal = GetParamValue(fi, widthBips, widthNames);
                                        if (wVal == null || wVal == 0)
                                        {
                                            wVal = GetParamValue(symbol, widthBips, widthNames);
                                        }
                                        double widthRaw = wVal ?? 0;
                                        double width = widthRaw * FEET_TO_MM;

                                        double? hVal = GetParamValue(fi, heightBips, heightNames);
                                        if (hVal == null || hVal == 0)
                                        {
                                            hVal = GetParamValue(symbol, heightBips, heightNames);
                                        }
                                        double heightRaw = hVal ?? 0;
                                        double height = heightRaw * FEET_TO_MM;

                                        double sillHeightRaw = GetParamValue(fi, sillBips, sillNames) ?? 0;
                                        double sillHeight = sillHeightRaw * FEET_TO_MM;

                                        double headHeightRaw = GetParamValue(fi, headBips, headNames) ?? (sillHeightRaw + heightRaw);
                                        double headHeight = headHeightRaw * FEET_TO_MM;

                                        openings.Add(new
                                        {
                                            Id = insert.Id.GetIdValue(),
                                            Name = insert.Name,
                                            FamilyName = fi.Symbol.FamilyName,
                                            Category = insert.Category.Name,
                                            Width = Math.Round(width, 2),
                                            Height = Math.Round(height, 2),
                                            SillHeight = Math.Round(sillHeight, 2),
                                            HeadHeight = Math.Round(headHeight, 2),
                                            IsExterior = isExterior,
                                            HostWallId = wall.Id.GetIdValue()
                                        });
                                    }
                                }
                            }
                        }
                    }
                }

                // 取得房間標籤 ID
                List<IdType> tagIds = new List<IdType>();
                if (roomTagMap.ContainsKey(room.Id.GetIdValue()))
                {
                    tagIds = roomTagMap[room.Id.GetIdValue()];
                }

                roomData.Add(new
                {
                    ElementId = room.Id.GetIdValue(),
                    Name = room.get_Parameter(BuiltInParameter.ROOM_NAME)?.AsString() ?? "未命名",
                    Number = room.Number,
                    Level = doc.GetElement(room.LevelId)?.Name,
                    Area = Math.Round(room.Area * 0.092903, 2),
                    Openings = openings,
                    TagIds = tagIds
                });
            }

            return new
            {
                Count = roomData.Count,
                Rooms = roomData
            };
        }

        private double? GetParamDouble(Element e, BuiltInParameter bip)
        {
            Parameter p = e.get_Parameter(bip);
            if (p != null && (p.StorageType == StorageType.Double)) return p.AsDouble();
            return null;
        }

        private double? GetParamValue(Element e, BuiltInParameter[] bips, string[] names)
        {
            if (e == null) return null;
            
            foreach (BuiltInParameter bip in bips)
            {
                var val = GetParamDouble(e, bip);
                if (val.HasValue)
                {
                    System.Diagnostics.Debug.WriteLine($"Found via BIP: {bip} = {val}");
                    return val;
                }
            }
            
            foreach (var name in names)
            {
                Parameter p = e.LookupParameter(name);
                if (p != null && p.StorageType == StorageType.Double)
                {
                    System.Diagnostics.Debug.WriteLine($"Found via Name: {name} = {p.AsDouble()}");
                    return p.AsDouble();
                }
            }
            
            // Fallback: iterate all parameters to find by name match
            foreach (Parameter param in e.Parameters)
            {
                if (param.StorageType != StorageType.Double) continue;
                
                string paramName = param.Definition.Name;
                foreach (var name in names)
                {
                    if (paramName == name)
                    {
                        System.Diagnostics.Debug.WriteLine($"Found via iteration: {paramName} = {param.AsDouble()}");
                        return param.AsDouble();
                    }
                }
            }
            
            return null;
        }

        /// <summary>
        /// 取得所有視圖
        /// </summary>
        private object GetAllViews(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            string viewTypeFilter = parameters["viewType"]?.Value<string>();
            string levelNameFilter = parameters["levelName"]?.Value<string>();

            var views = new FilteredElementCollector(doc)
                .OfClass(typeof(View))
                .Cast<View>()
                .Where(v => !v.IsTemplate && v.CanBePrinted)
                .Select(v =>
                {
                    string levelName = "";
                    if (v.GenLevel != null)
                    {
                        levelName = v.GenLevel.Name;
                    }

                    return new
                    {
                        ElementId = v.Id.GetIdValue(),
                        Name = v.Name,
                        ViewType = v.ViewType.ToString(),
                        LevelName = levelName,
                        Scale = v.Scale
                    };
                })
                .Where(v => string.IsNullOrEmpty(viewTypeFilter) || 
                            v.ViewType.ToLower().Contains(viewTypeFilter.ToLower()))
                .Where(v => string.IsNullOrEmpty(levelNameFilter) || 
                            v.LevelName.Contains(levelNameFilter))
                .OrderBy(v => v.ViewType)
                .ThenBy(v => v.Name)
                .ToList();

            return new
            {
                Count = views.Count,
                Views = views
            };
        }

        /// <summary>
        /// 取得目前視圖
        /// </summary>
        private object GetActiveView()
        {
            View activeView = _uiApp.ActiveUIDocument.ActiveView;
            Document doc = _uiApp.ActiveUIDocument.Document;

            string levelName = "";
            if (activeView.GenLevel != null)
            {
                levelName = activeView.GenLevel.Name;
            }

            return new
            {
                ElementId = activeView.Id.GetIdValue(),
                Name = activeView.Name,
                ViewType = activeView.ViewType.ToString(),
                LevelName = levelName,
                Scale = activeView.Scale
            };
        }

        /// <summary>
        /// 切換視圖
        /// </summary>
        private object SetActiveView(JObject parameters)
        {
            IdType viewId = parameters["viewId"]?.Value<IdType>() ?? 0;
            Document doc = _uiApp.ActiveUIDocument.Document;

            View view = doc.GetElement(viewId.ToElementId()) as View;
            if (view == null)
            {
                throw new Exception($"找不到視圖 ID: {viewId}");
            }

            _uiApp.ActiveUIDocument.ActiveView = view;

            return new
            {
                Success = true,
                ViewId = viewId,
                ViewName = view.Name,
                Message = $"已切換至視圖: {view.Name}"
            };
        }

        /// <summary>
        /// 選取元素
        /// </summary>
        private object SelectElement(JObject parameters)
        {
            var elementIds = new List<ElementId>();
            
            // 支援單一 ID
            if (parameters.ContainsKey("elementId"))
            {
                IdType id = parameters["elementId"].Value<IdType>();
                if (id > 0) elementIds.Add(id.ToElementId());
            }

            // 支援多個 ID
            if (parameters.ContainsKey("elementIds"))
            {
                var ids = parameters["elementIds"].Values<IdType>();
                foreach (var id in ids)
                {
                    if (id > 0) elementIds.Add(id.ToElementId());
                }
            }

            if (elementIds.Count == 0)
            {
                throw new Exception("未提供有效的 elementId 或 elementIds");
            }

            Document doc = _uiApp.ActiveUIDocument.Document;
            
            // 選取元素
            _uiApp.ActiveUIDocument.Selection.SetElementIds(elementIds);

            return new
            {
                Success = true,
                Count = elementIds.Count,
                Message = $"已選取 {elementIds.Count} 個元素"
            };
        }

        /// <summary>
        /// 縮放至元素
        /// </summary>
        private object ZoomToElement(JObject parameters)
        {
            IdType elementId = parameters["elementId"]?.Value<IdType>() ?? 0;
            Document doc = _uiApp.ActiveUIDocument.Document;

            Element element = doc.GetElement(elementId.ToElementId());
            if (element == null)
            {
                throw new Exception($"找不到元素 ID: {elementId}");
            }

            // 顯示元素（會自動縮放）
            var elementIds = new List<ElementId> { elementId.ToElementId() };
            _uiApp.ActiveUIDocument.ShowElements(elementIds);

            return new
            {
                Success = true,
                ElementId = elementId,
                ElementName = element.Name,
                Message = $"已縮放至元素: {element.Name}"
            };
        }

        /// <summary>
        /// 測量距離
        /// </summary>
        private object MeasureDistance(JObject parameters)
        {
            double p1x = parameters["point1X"]?.Value<double>() ?? 0;
            double p1y = parameters["point1Y"]?.Value<double>() ?? 0;
            double p1z = parameters["point1Z"]?.Value<double>() ?? 0;
            double p2x = parameters["point2X"]?.Value<double>() ?? 0;
            double p2y = parameters["point2Y"]?.Value<double>() ?? 0;
            double p2z = parameters["point2Z"]?.Value<double>() ?? 0;

            // 轉換為英尺
            XYZ point1 = new XYZ(p1x / 304.8, p1y / 304.8, p1z / 304.8);
            XYZ point2 = new XYZ(p2x / 304.8, p2y / 304.8, p2z / 304.8);

            double distanceFeet = point1.DistanceTo(point2);
            double distanceMm = distanceFeet * 304.8;

            return new
            {
                Distance = Math.Round(distanceMm, 2),
                Unit = "mm",
                Point1 = new { X = p1x, Y = p1y, Z = p1z },
                Point2 = new { X = p2x, Y = p2y, Z = p2z }
            };
        }

        /// <summary>
        /// 取得牆資訊
        /// </summary>
        private object GetWallInfo(JObject parameters)
        {
            IdType wallId = parameters["wallId"]?.Value<IdType>() ?? 0;
            Document doc = _uiApp.ActiveUIDocument.Document;

            Wall wall = doc.GetElement(wallId.ToElementId()) as Wall;
            if (wall == null)
            {
                throw new Exception($"找不到牆 ID: {wallId}");
            }

            // 取得牆的位置曲線
            LocationCurve locCurve = wall.Location as LocationCurve;
            Curve curve = locCurve?.Curve;

            XYZ startPoint = curve?.GetEndPoint(0) ?? XYZ.Zero;
            XYZ endPoint = curve?.GetEndPoint(1) ?? XYZ.Zero;

            // 取得牆厚度
            double thickness = wall.Width * 304.8; // 英尺 → 公釐

            // 取得牆長度
            double length = curve != null ? curve.Length * 304.8 : 0;

            // 取得牆高度
            Parameter heightParam = wall.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
            double height = heightParam != null ? heightParam.AsDouble() * 304.8 : 0;

            return new
            {
                ElementId = wallId,
                Name = wall.Name,
                WallType = wall.WallType.Name,
                Thickness = Math.Round(thickness, 2),
                Length = Math.Round(length, 2),
                Height = Math.Round(height, 2),
                StartX = Math.Round(startPoint.X * 304.8, 2),
                StartY = Math.Round(startPoint.Y * 304.8, 2),
                EndX = Math.Round(endPoint.X * 304.8, 2),
                EndY = Math.Round(endPoint.Y * 304.8, 2),
                Level = doc.GetElement(wall.LevelId)?.Name
            };
        }

        /// <summary>
        /// 建立尺寸標註
        /// </summary>
        private object CreateDimension(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            
            IdType viewId = parameters["viewId"]?.Value<IdType>() ?? 0;
            double startX = parameters["startX"]?.Value<double>() ?? 0;
            double startY = parameters["startY"]?.Value<double>() ?? 0;
            double endX = parameters["endX"]?.Value<double>() ?? 0;
            double endY = parameters["endY"]?.Value<double>() ?? 0;
            double offset = parameters["offset"]?.Value<double>() ?? 500;

            View view = doc.GetElement(viewId.ToElementId()) as View;
            if (view == null)
            {
                throw new Exception($"找不到視圖 ID: {viewId}");
            }

            using (Transaction trans = new Transaction(doc, "建立尺寸標註"))
            {
                trans.Start();

                // 轉換座標
                XYZ start = new XYZ(startX / 304.8, startY / 304.8, 0);
                XYZ end = new XYZ(endX / 304.8, endY / 304.8, 0);

                // 建立參考線
                Line line = Line.CreateBound(start, end);

                // 建立尺寸標註用的參考陣列
                ReferenceArray refArray = new ReferenceArray();

                // 使用 DetailCurve 作為參考
                // 先建立兩個詳圖線作為參考點
                XYZ perpDir = new XYZ(-(end.Y - start.Y), end.X - start.X, 0).Normalize();
                double offsetFeet = offset / 304.8;

                // 偏移後的標註線位置
                XYZ dimLinePoint = start.Add(perpDir.Multiply(offsetFeet));
                Line dimLine = Line.CreateBound(
                    start.Add(perpDir.Multiply(offsetFeet)),
                    end.Add(perpDir.Multiply(offsetFeet))
                );

                // 使用 NewDetailCurve 建立參考（建立足夠長的線段）
                // 詳圖線應垂直於標註方向，作為標註的參考點
                double lineLength = 1.0; // 1 英尺 = 約 305mm

                // 使用 perpDir（垂直方向）來建立詳圖線
                DetailCurve dc1 = doc.Create.NewDetailCurve(view, Line.CreateBound(
                    start.Subtract(perpDir.Multiply(lineLength / 2)), 
                    start.Add(perpDir.Multiply(lineLength / 2))));
                DetailCurve dc2 = doc.Create.NewDetailCurve(view, Line.CreateBound(
                    end.Subtract(perpDir.Multiply(lineLength / 2)), 
                    end.Add(perpDir.Multiply(lineLength / 2))));

                refArray.Append(dc1.GeometryCurve.Reference);
                refArray.Append(dc2.GeometryCurve.Reference);

                // 建立尺寸標註
                Dimension dim = doc.Create.NewDimension(view, dimLine, refArray);

                // 注意：保留詳圖線作為標註參考點（如需刪除請手動處理）

                trans.Commit();

                double dimValue = dim.Value.HasValue ? dim.Value.Value * 304.8 : 0;

                return new
                {
                    DimensionId = dim.Id.GetIdValue(),
                    Value = Math.Round(dimValue, 2),
                    Unit = "mm",
                    ViewId = viewId,
                    ViewName = view.Name,
                    Message = $"成功建立尺寸標註: {Math.Round(dimValue, 0)} mm"
                };
            }
        }

        /// <summary>
        /// 查詢指定位置附近的牆體
        /// </summary>
        private object QueryWallsByLocation(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            
            double centerX = parameters["x"]?.Value<double>() ?? 0;
            double centerY = parameters["y"]?.Value<double>() ?? 0;
            double searchRadius = parameters["searchRadius"]?.Value<double>() ?? 5000;
            string levelName = parameters["level"]?.Value<string>();

            // 轉換為英尺
            XYZ center = new XYZ(centerX / 304.8, centerY / 304.8, 0);
            double radiusFeet = searchRadius / 304.8;

            // 取得所有牆
            var wallCollector = new FilteredElementCollector(doc)
                .OfClass(typeof(Wall))
                .WhereElementIsNotElementType()
                .Cast<Wall>();

            // 如果指定樓層，過濾樓層
            if (!string.IsNullOrEmpty(levelName))
            {
                var level = new FilteredElementCollector(doc)
                    .OfClass(typeof(Level))
                    .Cast<Level>()
                    .FirstOrDefault(l => l.Name.Contains(levelName));

                if (level != null)
                {
                    wallCollector = wallCollector.Where(w => w.LevelId == level.Id);
                }
            }

            var nearbyWalls = new List<object>();

            foreach (var wall in wallCollector)
            {
                LocationCurve locCurve = wall.Location as LocationCurve;
                if (locCurve == null) continue;

                Curve curve = locCurve.Curve;
                XYZ startPoint = curve.GetEndPoint(0);
                XYZ endPoint = curve.GetEndPoint(1);
                
                // 計算點到線段的最近距離
                XYZ wallDir = (endPoint - startPoint).Normalize();
                XYZ toCenter = center - startPoint;
                double proj = toCenter.DotProduct(wallDir);
                double wallLength = curve.Length;
                
                XYZ closestPoint;
                if (proj < 0)
                    closestPoint = startPoint;
                else if (proj > wallLength)
                    closestPoint = endPoint;
                else
                    closestPoint = startPoint + wallDir * proj;
                
                double distToWall = center.DistanceTo(closestPoint) * 304.8;

                if (distToWall <= searchRadius)
                {
                    // 取得牆厚度
                    double thickness = wall.Width * 304.8;
                    
                    // 計算牆的方向向量（垂直於位置線）
                    XYZ perpendicular = new XYZ(-wallDir.Y, wallDir.X, 0);
                    double halfThickness = wall.Width / 2;
                    
                    // 牆的兩個面
                    XYZ face1Point = closestPoint + perpendicular * halfThickness;
                    XYZ face2Point = closestPoint - perpendicular * halfThickness;

                    nearbyWalls.Add(new
                    {
                        ElementId = wall.Id.GetIdValue(),
                        Name = wall.Name,
                        WallType = wall.WallType.Name,
                        Thickness = Math.Round(thickness, 2),
                        Length = Math.Round(curve.Length * 304.8, 2),
                        DistanceToCenter = Math.Round(distToWall, 2),
                        // 位置線座標
                        LocationLine = new
                        {
                            StartX = Math.Round(startPoint.X * 304.8, 2),
                            StartY = Math.Round(startPoint.Y * 304.8, 2),
                            EndX = Math.Round(endPoint.X * 304.8, 2),
                            EndY = Math.Round(endPoint.Y * 304.8, 2)
                        },
                        // 最近點位置
                        ClosestPoint = new
                        {
                            X = Math.Round(closestPoint.X * 304.8, 2),
                            Y = Math.Round(closestPoint.Y * 304.8, 2)
                        },
                        // 兩側面座標（在最近點處）
                        Face1 = new
                        {
                            X = Math.Round(face1Point.X * 304.8, 2),
                            Y = Math.Round(face1Point.Y * 304.8, 2)
                        },
                        Face2 = new
                        {
                            X = Math.Round(face2Point.X * 304.8, 2),
                            Y = Math.Round(face2Point.Y * 304.8, 2)
                        },
                        // 判斷牆是水平還是垂直
                        Orientation = Math.Abs(wallDir.X) > Math.Abs(wallDir.Y) ? "Horizontal" : "Vertical"
                    });
                }
            }

            // 直接返回列表（已在搜尋時過濾距離）

            return new
            {
                Count = nearbyWalls.Count,
                SearchCenter = new { X = centerX, Y = centerY },
                SearchRadius = searchRadius,
                Walls = nearbyWalls
            };
        }


        /// <summary>
        /// 查詢視圖中的元素 (增強版)
        /// </summary>
        private object QueryElements(JObject parameters)
        {
            try
            {
                string categoryName = parameters["category"]?.Value<string>();
                IdType? viewId = parameters["viewId"]?.Value<IdType>();
                int maxCount = parameters["maxCount"]?.Value<int>() ?? 100;
                JArray filters = parameters["filters"] as JArray;
                JArray returnFields = parameters["returnFields"] as JArray;

                // 相容簡易版 query_elements 的 family / type / level 參數
                string familyFilter = parameters["family"]?.Value<string>();
                string typeFilter = parameters["type"]?.Value<string>();
                string levelFilter = parameters["level"]?.Value<string>();

                if (string.IsNullOrEmpty(categoryName))
                {
                    throw new Exception("必須提供 category 參數（例如：Walls, Rooms, Doors, Windows）");
                }

                Document doc = _uiApp.ActiveUIDocument.Document;
                
                // 使用全文件收集器（避免限定在不適當的 View 導致結果為空）
                FilteredElementCollector collector;
                if (viewId.HasValue)
                {
                    collector = new FilteredElementCollector(doc, viewId.Value.ToElementId());
                }
                else
                {
                    collector = new FilteredElementCollector(doc);
                }

                // 1. 品類過濾
                ElementId catId = ResolveCategoryId(doc, categoryName);
                if (catId != ElementId.InvalidElementId)
                {
                    collector.OfCategoryId(catId);
                }
                else
                {
                    // 備用方案: 根據常用名稱
                    string catLower = categoryName.ToLowerInvariant();
                    if (catLower == "walls" || catLower == "牆") collector.OfClass(typeof(Wall));
                    else if (catLower == "rooms" || catLower == "房間") collector.OfCategory(BuiltInCategory.OST_Rooms);
                    else if (catLower == "doors" || catLower == "門") collector.OfCategory(BuiltInCategory.OST_Doors);
                    else if (catLower == "windows" || catLower == "窗") collector.OfCategory(BuiltInCategory.OST_Windows);
                    else if (catLower == "floors" || catLower == "樓板") collector.OfCategory(BuiltInCategory.OST_Floors);
                    else if (catLower == "columns" || catLower == "柱") collector.OfCategory(BuiltInCategory.OST_Columns);
                    else throw new Exception($"無法辨識品類: {categoryName}。請使用英文名稱如 Walls, Rooms, Doors, Windows, Floors, Columns");
                }

                var elements = collector.WhereElementIsNotElementType().ToElements();
                var filteredList = new List<Element>();

                // 2. 執行過濾邏輯
                foreach (var elem in elements)
                {
                    bool match = true;

                    // 進階版 filters 過濾
                    if (filters != null)
                    {
                        foreach (var filter in filters)
                        {
                            string field = filter["field"]?.Value<string>();
                            string op = filter["operator"]?.Value<string>();
                            string targetValue = filter["value"]?.Value<string>();
                            
                            if (!CheckFilterMatch(elem, field, op, targetValue))
                            {
                                match = false;
                                break;
                            }
                        }
                    }

                    // 簡易版 family 過濾
                    if (match && !string.IsNullOrEmpty(familyFilter))
                    {
                        string elemFamily = elem.get_Parameter(BuiltInParameter.ELEM_FAMILY_PARAM)?.AsValueString() ?? "";
                        if (!elemFamily.IndexOf(familyFilter, StringComparison.OrdinalIgnoreCase).Equals(0) 
                            && !elemFamily.Contains(familyFilter))
                            match = false;
                    }

                    // 簡易版 type 過濾
                    if (match && !string.IsNullOrEmpty(typeFilter))
                    {
                        string elemType = elem.get_Parameter(BuiltInParameter.ELEM_TYPE_PARAM)?.AsValueString() ?? "";
                        if (!elemType.IndexOf(typeFilter, StringComparison.OrdinalIgnoreCase).Equals(0)
                            && !elemType.Contains(typeFilter))
                            match = false;
                    }

                    // 簡易版 level 過濾
                    if (match && !string.IsNullOrEmpty(levelFilter))
                    {
                        string elemLevel = elem.get_Parameter(BuiltInParameter.LEVEL_NAME)?.AsValueString() 
                                        ?? elem.get_Parameter(BuiltInParameter.INSTANCE_SCHEDULE_ONLY_LEVEL_PARAM)?.AsValueString()
                                        ?? "";
                        if (!elemLevel.Contains(levelFilter))
                            match = false;
                    }

                    if (match) filteredList.Add(elem);
                    if (filteredList.Count >= maxCount) break;
                }

                // 3. 準備回傳欄位
                var resultList = filteredList.Select(elem =>
                {
                    var item = new Dictionary<string, object>
                    {
                        { "ElementId", elem.Id.GetIdValue() },
                        { "Name", elem.Name ?? "" }
                    };

                    if (returnFields != null)
                    {
                        foreach (var f in returnFields)
                        {
                            string fieldName = f.Value<string>();
                            if (string.IsNullOrEmpty(fieldName) || item.ContainsKey(fieldName)) continue;
                            
                            Parameter p = FindParameter(elem, fieldName);
                            if (p != null) 
                            {
                                string val = p.AsValueString() ?? p.AsString() ?? "";
                                item[fieldName] = val;
                            }
                            else
                            {
                                item[fieldName] = "N/A";
                            }
                        }
                    }
                    return item;
                }).ToList();

                return new { Success = true, Count = resultList.Count, Elements = resultList };
            }
            catch (Exception ex)
            {
                throw new Exception($"QueryElements 錯誤: {ex.Message}");
            }
        }

        private Parameter FindParameter(Element elem, string name)
        {
            // 1. 優先找實例參數
            foreach (Parameter p in elem.Parameters)
            {
                if (p.Definition.Name.Equals(name, StringComparison.OrdinalIgnoreCase)) return p;
            }

            // 2. 找類型參數
            Element typeElem = elem.Document.GetElement(elem.GetTypeId());
            if (typeElem != null)
            {
                foreach (Parameter p in typeElem.Parameters)
                {
                    if (p.Definition.Name.Equals(name, StringComparison.OrdinalIgnoreCase)) return p;
                }
            }

            return null;
        }

        private bool CheckFilterMatch(Element elem, string field, string op, string targetValue)
        {
            Parameter p = FindParameter(elem, field);
            if (p == null) return false;

            string val = p.AsValueString() ?? p.AsString() ?? "";
            
            switch (op)
            {
                case "equals": return val.Equals(targetValue, StringComparison.OrdinalIgnoreCase);
                case "contains": return val.Contains(targetValue);
                case "not_equals": return !val.Equals(targetValue, StringComparison.OrdinalIgnoreCase);
                case "less_than":
                case "greater_than":
                    // 移除單位字串並嘗試解析
                    string cleanVal = System.Text.RegularExpressions.Regex.Replace(val, @"[^\d.-]", "");
                    if (double.TryParse(cleanVal, out double v1) && 
                        double.TryParse(targetValue, out double v2))
                    {
                        return op == "less_than" ? v1 < v2 : v1 > v2;
                    }
                    return false;
                default: return false;
            }
        }

        private ElementId ResolveCategoryId(Document doc, string name)
        {
            if (string.IsNullOrEmpty(name)) return ElementId.InvalidElementId;

            foreach (Category cat in doc.Settings.Categories)
            {
                if (cat.Name.Equals(name, StringComparison.OrdinalIgnoreCase) || 
                    ((BuiltInCategory)cat.Id.GetIdValue()).ToString().Equals("OST_" + name, StringComparison.OrdinalIgnoreCase) ||
                    ((BuiltInCategory)cat.Id.GetIdValue()).ToString().Equals(name, StringComparison.OrdinalIgnoreCase))
                    return cat.Id;
            }
            return ElementId.InvalidElementId;
        }

        /// <summary>
        /// 取得視圖架構 (第一階段)
        /// </summary>
        private object GetActiveSchema(JObject parameters)
        {
            try
            {
                Document doc = _uiApp.ActiveUIDocument.Document;
                IdType? viewId = parameters["viewId"]?.Value<IdType>();
                ElementId targetViewId = viewId.HasValue ? viewId.Value.ToElementId() : doc.ActiveView.Id;

                var collector = new FilteredElementCollector(doc, targetViewId);
                var categories = collector.WhereElementIsNotElementType()
                    .Where(e => e.Category != null)
                    .GroupBy(e => e.Category.Id.GetIdValue())
                    .Select(g => {
                        ElementId catId = g.Key.ToElementId();
                        Category cat = Category.GetCategory(doc, catId);
                        return new { 
                            Name = cat?.Name ?? "未知品類",
                            InternalName = cat != null ? ((BuiltInCategory)cat.Id.GetIdValue()).ToString().Replace("OST_", "") : "Unknown",
                            Count = g.Count() 
                        };
                    })
                    .OrderByDescending(c => c.Count)
                    .ToList();

                return new { Success = true, ViewId = targetViewId.GetIdValue(), Categories = categories };
            }
            catch (Exception ex)
            {
                throw new Exception($"GetActiveSchema 錯誤: {ex.Message}");
            }
        }

        /// <summary>
        /// 取得品類參數欄位 (第二階段 - A)
        /// </summary>
        private object GetCategoryFields(JObject parameters)
        {
            try
            {
                string categoryName = parameters["category"]?.Value<string>();
                Document doc = _uiApp.ActiveUIDocument.Document;
                ElementId catId = ResolveCategoryId(doc, categoryName);
                
                if (catId == ElementId.InvalidElementId)
                    throw new Exception($"找不到品類: {categoryName}");

                Element sample = new FilteredElementCollector(doc)
                    .OfCategoryId(catId)
                    .WhereElementIsNotElementType()
                    .FirstElement();
                
                if (sample == null) 
                    return new { Success = false, Message = $"專案中沒有任何 {categoryName} 元素可供分析" };

                var instanceFields = sample.GetOrderedParameters()
                    .Where(p => {
                        InternalDefinition def = p.Definition as InternalDefinition;
                        return def == null || def.Visible;
                    })
                    .Select(p => p.Definition.Name)
                    .Distinct()
                    .ToList();

                var typeFields = new List<string>();
                ElementId typeId = sample.GetTypeId();
                if (typeId != ElementId.InvalidElementId)
                {
                    Element typeElem = doc.GetElement(typeId);
                    if (typeElem != null)
                    {
                        typeFields = typeElem.GetOrderedParameters()
                            .Where(p => {
                                InternalDefinition def = p.Definition as InternalDefinition;
                                return def == null || def.Visible;
                            })
                            .Select(p => p.Definition.Name)
                            .Distinct()
                            .ToList();
                    }
                }

                return new { Success = true, Category = categoryName, InstanceFields = instanceFields, TypeFields = typeFields };
            }
            catch (Exception ex)
            {
                throw new Exception($"GetCategoryFields 錯誤: {ex.Message}");
            }
        }

        /// <summary>
        /// 取得參數值分布 (第二階段 - B)
        /// </summary>
        private object GetFieldValues(JObject parameters)
        {
            string categoryName = parameters["category"]?.Value<string>();
            string fieldName = parameters["fieldName"]?.Value<string>();
            int maxSamples = parameters["maxSamples"]?.Value<int>() ?? 500;
            
            Document doc = _uiApp.ActiveUIDocument.Document;
            ElementId catId = ResolveCategoryId(doc, categoryName);
            var elements = new FilteredElementCollector(doc).OfCategoryId(catId).WhereElementIsNotElementType().Take(maxSamples);

            var values = new HashSet<string>();
            bool isNumeric = false;
            double min = double.MaxValue;
            double max = double.MinValue;

            foreach (var elem in elements)
            {
                Parameter p = elem.LookupParameter(fieldName);
                if (p == null)
                {
                    Element typeElem = doc.GetElement(elem.GetTypeId());
                    if (typeElem != null) p = typeElem.LookupParameter(fieldName);
                }
                
                if (p != null && p.HasValue)
                {
                    string valString = p.AsValueString() ?? p.AsString();
                    if (valString != null) values.Add(valString);

                    if (p.StorageType == StorageType.Double || p.StorageType == StorageType.Integer)
                    {
                        isNumeric = true;
                        double val = (p.StorageType == StorageType.Double) ? p.AsDouble() : p.AsInteger();
                        
                        // 轉換為 mm (如果適用)
                        try { if (p.Definition.IsLengthUnit()) val *= 304.8; } catch { }
                        
                        if (val < min) min = val;
                        if (val > max) max = val;
                    }
                }
            }

            return new { 
                Success = true, 
                Category = categoryName, 
                Field = fieldName, 
                UniqueValues = values.Take(20).ToList(),
                IsNumeric = isNumeric,
                Range = isNumeric ? new { Min = Math.Round(min, 2), Max = Math.Round(max, 2) } : null
            };
        }

        /// <summary>
        /// 覆寫元素圖形顯示
        /// 支援平面圖（切割樣式）和立面圖/剖面圖（表面樣式）
        /// </summary>
        private object OverrideElementGraphics(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType elementId = parameters["elementId"].Value<IdType>();
            IdType? viewId = parameters["viewId"]?.Value<IdType>();

            // 取得視圖
            View view;
            if (viewId.HasValue)
            {
                view = doc.GetElement(viewId.Value.ToElementId()) as View;
                if (view == null)
                    throw new Exception($"找不到視圖 ID: {viewId}");
            }
            else
            {
                view = _uiApp.ActiveUIDocument.ActiveView;
            }

            // 取得元素
            Element element = doc.GetElement(elementId.ToElementId());
            if (element == null)
                throw new Exception($"找不到元素 ID: {elementId}");

            // 判斷使用切割樣式或表面樣式
            // patternMode: "auto" (自動根據視圖類型), "cut" (切割), "surface" (表面)
            string patternMode = parameters["patternMode"]?.Value<string>() ?? "auto";
            
            bool useCutPattern = false;
            if (patternMode == "cut")
            {
                useCutPattern = true;
            }
            else if (patternMode == "surface")
            {
                useCutPattern = false;
            }
            else // auto
            {
                // 平面圖、天花板平面圖使用切割樣式
                // 立面圖、剖面圖、3D 視圖使用表面樣式
                useCutPattern = (view.ViewType == ViewType.FloorPlan || 
                                 view.ViewType == ViewType.CeilingPlan ||
                                 view.ViewType == ViewType.AreaPlan ||
                                 view.ViewType == ViewType.EngineeringPlan);
            }

            using (Transaction trans = new Transaction(doc, "Override Element Graphics"))
            {
                trans.Start();

                // 建立覆寫設定
                OverrideGraphicSettings overrideSettings = new OverrideGraphicSettings();

                // 取得實心填滿圖樣 ID
                ElementId solidPatternId = GetSolidFillPatternId(doc);

                // 設定填滿顏色
                if (parameters["surfaceFillColor"] != null)
                {
                    var colorObj = parameters["surfaceFillColor"];
                    byte r = (byte)colorObj["r"].Value<int>();
                    byte g = (byte)colorObj["g"].Value<int>();
                    byte b = (byte)colorObj["b"].Value<int>();
                    Color fillColor = new Color(r, g, b);

                    if (useCutPattern)
                    {
                        // 平面圖：使用切割樣式（前景）
                        overrideSettings.SetCutForegroundPatternColor(fillColor);
                        if (solidPatternId != null && solidPatternId != ElementId.InvalidElementId)
                        {
                            overrideSettings.SetCutForegroundPatternId(solidPatternId);
                            overrideSettings.SetCutForegroundPatternVisible(true);
                        }
                    }
                    else
                    {
                        // 立面圖/剖面圖：使用表面樣式
                        overrideSettings.SetSurfaceForegroundPatternColor(fillColor);
                        if (solidPatternId != null && solidPatternId != ElementId.InvalidElementId)
                        {
                            overrideSettings.SetSurfaceForegroundPatternId(solidPatternId);
                            overrideSettings.SetSurfaceForegroundPatternVisible(true);
                        }
                    }
                }

                // 設定線條顏色（可選）
                if (parameters["lineColor"] != null)
                {
                    var lineColorObj = parameters["lineColor"];
                    byte r = (byte)lineColorObj["r"].Value<int>();
                    byte g = (byte)lineColorObj["g"].Value<int>();
                    byte b = (byte)lineColorObj["b"].Value<int>();
                    Color lineColor = new Color(r, g, b);
                    
                    if (useCutPattern)
                    {
                        overrideSettings.SetCutLineColor(lineColor);
                    }
                    else
                    {
                        overrideSettings.SetProjectionLineColor(lineColor);
                    }
                }

                // 設定透明度
                int transparency = parameters["transparency"]?.Value<int>() ?? 0;
                if (transparency > 0)
                {
                    overrideSettings.SetSurfaceTransparency(transparency);
                }

                // 應用覆寫
                view.SetElementOverrides(elementId.ToElementId(), overrideSettings);

                trans.Commit();

                return new
                {
                    Success = true,
                    ElementId = elementId,
                    ViewId = view.Id.GetIdValue(),
                    ViewType = view.ViewType.ToString(),
                    PatternMode = useCutPattern ? "Cut" : "Surface",
                    ViewName = view.Name,
                    Message = $"已成功覆寫元素 {elementId} 在視圖 '{view.Name}' 的圖形顯示"
                };
            }
        }

        /// <summary>
        /// 清除元素圖形覆寫
        /// </summary>
        private object ClearElementOverride(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType? singleElementId = parameters["elementId"]?.Value<IdType>();
            var elementIdsArray = parameters["elementIds"] as JArray;
            IdType? viewId = parameters["viewId"]?.Value<IdType>();

            // 取得視圖
            View view;
            if (viewId.HasValue)
            {
                view = doc.GetElement(viewId.Value.ToElementId()) as View;
                if (view == null)
                    throw new Exception($"找不到視圖 ID: {viewId}");
            }
            else
            {
                view = _uiApp.ActiveUIDocument.ActiveView;
            }

            // 收集要清除的元素 ID
            List<IdType> elementIds = new List<IdType>();
            if (singleElementId.HasValue)
            {
                elementIds.Add(singleElementId.Value);
            }
            if (elementIdsArray != null)
            {
                elementIds.AddRange(elementIdsArray.Select(id => id.Value<IdType>()));
            }

            if (elementIds.Count == 0)
            {
                throw new Exception("請提供至少一個元素 ID");
            }

            using (Transaction trans = new Transaction(doc, "Clear Element Override"))
            {
                trans.Start();

                int successCount = 0;
                foreach (IdType elemId in elementIds)
                {
                    Element element = doc.GetElement(elemId.ToElementId());
                    if (element != null)
                    {
                        // 設定空的覆寫設定 = 重置為預設
                        view.SetElementOverrides(elemId.ToElementId(), new OverrideGraphicSettings());
                        successCount++;
                    }
                }

                trans.Commit();

                return new
                {
                    Success = true,
                    ClearedCount = successCount,
                    ViewId = view.Id.GetIdValue(),
                    ViewName = view.Name,
                    Message = $"已清除 {successCount} 個元素在視圖 '{view.Name}' 的圖形覆寫"
                };
            }
        }

        /// <summary>
        /// 取得實心填滿圖樣 ID
        /// </summary>
        private ElementId GetSolidFillPatternId(Document doc)
        {
            // 嘗試找到實心填滿圖樣
            FilteredElementCollector collector = new FilteredElementCollector(doc);
            var fillPatterns = collector
                .OfClass(typeof(FillPatternElement))
                .Cast<FillPatternElement>()
                .Where(fp => fp.GetFillPattern().IsSolidFill)
                .ToList();

            if (fillPatterns.Any())
            {
                return fillPatterns.First().Id;
            }

            return ElementId.InvalidElementId;
        }

        // 靜態變數：儲存取消接合的元素對
        private static List<Tuple<ElementId, ElementId>> _unjoinedPairs = new List<Tuple<ElementId, ElementId>>();

        /// <summary>
        /// 取消牆體與其他元素（柱子等）的接合關係
        /// </summary>
        private object UnjoinWallJoins(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            
            // 取得牆體 ID 列表
            var wallIdsArray = parameters["wallIds"] as JArray;
            IdType? viewId = parameters["viewId"]?.Value<IdType>();
            
            List<IdType> wallIds = new List<IdType>();
            if (wallIdsArray != null)
            {
                wallIds.AddRange(wallIdsArray.Select(id => id.Value<IdType>()));
            }
            
            // 如果沒有提供 wallIds，則查詢視圖中所有牆體
            if (wallIds.Count == 0 && viewId.HasValue)
            {
                var collector = new FilteredElementCollector(doc, viewId.Value.ToElementId());
                var walls = collector.OfClass(typeof(Wall)).ToElements();
                wallIds = walls.Select(w => w.Id.GetIdValue()).ToList();
            }
            
            if (wallIds.Count == 0)
            {
                throw new Exception("請提供 wallIds 或 viewId 參數");
            }

            int unjoinedCount = 0;
            _unjoinedPairs.Clear();

            using (Transaction trans = new Transaction(doc, "Unjoin Wall Geometry"))
            {
                trans.Start();

                foreach (IdType wallId in wallIds)
                {
                    Wall wall = doc.GetElement(wallId.ToElementId()) as Wall;
                    if (wall == null) continue;

                    // 取得牆體的 BoundingBox 來找附近的柱子
                    BoundingBoxXYZ bbox = wall.get_BoundingBox(null);
                    if (bbox == null) continue;

                    // 擴大搜尋範圍
                    XYZ min = bbox.Min - new XYZ(1, 1, 1);
                    XYZ max = bbox.Max + new XYZ(1, 1, 1);
                    Outline outline = new Outline(min, max);

                    // 查詢附近的柱子
                    var columnCollector = new FilteredElementCollector(doc)
                        .OfCategory(BuiltInCategory.OST_Columns)
                        .WherePasses(new BoundingBoxIntersectsFilter(outline));
                    
                    var structColumnCollector = new FilteredElementCollector(doc)
                        .OfCategory(BuiltInCategory.OST_StructuralColumns)
                        .WherePasses(new BoundingBoxIntersectsFilter(outline));

                    var columns = columnCollector.ToElements().Concat(structColumnCollector.ToElements());

                    foreach (Element column in columns)
                    {
                        try
                        {
                            if (JoinGeometryUtils.AreElementsJoined(doc, wall, column))
                            {
                                JoinGeometryUtils.UnjoinGeometry(doc, wall, column);
                                _unjoinedPairs.Add(new Tuple<ElementId, ElementId>(wall.Id, column.Id));
                                unjoinedCount++;
                            }
                        }
                        catch
                        {
                            // 忽略無法取消接合的元素
                        }
                    }
                }

                trans.Commit();
            }

            return new
            {
                Success = true,
                UnjoinedCount = unjoinedCount,
                WallCount = wallIds.Count,
                StoredPairs = _unjoinedPairs.Count,
                Message = $"已取消 {unjoinedCount} 個接合關係"
            };
        }

        /// <summary>
        /// 恢復之前取消的接合關係
        /// </summary>
        private object RejoinWallJoins(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            
            if (_unjoinedPairs.Count == 0)
            {
                return new
                {
                    Success = true,
                    RejoinedCount = 0,
                    Message = "沒有需要恢復的接合關係"
                };
            }

            int rejoinedCount = 0;

            using (Transaction trans = new Transaction(doc, "Rejoin Wall Geometry"))
            {
                trans.Start();

                foreach (var pair in _unjoinedPairs)
                {
                    try
                    {
                        Element elem1 = doc.GetElement(pair.Item1);
                        Element elem2 = doc.GetElement(pair.Item2);
                        
                        if (elem1 != null && elem2 != null)
                        {
                            if (!JoinGeometryUtils.AreElementsJoined(doc, elem1, elem2))
                            {
                                JoinGeometryUtils.JoinGeometry(doc, elem1, elem2);
                                rejoinedCount++;
                            }
                        }
                    }
                    catch
                    {
                        // 忽略無法恢復接合的元素
                    }
                }

                trans.Commit();
            }

            int storedCount = _unjoinedPairs.Count;
            _unjoinedPairs.Clear();

            return new
            {
                Success = true,
                RejoinedCount = rejoinedCount,
                TotalPairs = storedCount,
                Message = $"已恢復 {rejoinedCount} 個接合關係"
            };
        }

        /// <summary>
        /// 取得牆類型
        /// </summary>
        private object GetWallTypes(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            string search = parameters["search"]?.Value<string>();

            var wallTypes = new FilteredElementCollector(doc)
                .OfClass(typeof(WallType))
                .Cast<WallType>()
                .Select(wt => new
                {
                    ElementId = wt.Id.GetIdValue(),
                    Name = wt.Name
                });

            if (!string.IsNullOrEmpty(search))
            {
                wallTypes = wallTypes.Where(wt => wt.Name.Contains(search));
            }

            var result = wallTypes.OrderBy(wt => wt.Name).ToList();

            return new
            {
                Count = result.Count,
                WallTypes = result
            };
        }

        /// <summary>
        /// 變更元素類型
        /// </summary>
        private object ChangeElementType(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType? singleElementId = parameters["elementId"]?.Value<IdType>();
            var elementIdsArray = parameters["elementIds"] as JArray;
            IdType targetTypeId = parameters["typeId"]?.Value<IdType>() ?? 0;

            if (targetTypeId == 0)
            {
                throw new Exception("必須提供目標類型的 Element ID (typeId)");
            }

            ElementId newTypeId = targetTypeId.ToElementId();
            Element targetType = doc.GetElement(newTypeId);
            if (targetType == null)
            {
                throw new Exception($"找不到目標類型 ID: {targetTypeId}");
            }

            // 收集要變更的元素 ID
            List<IdType> elementIds = new List<IdType>();
            if (singleElementId.HasValue)
            {
                elementIds.Add(singleElementId.Value);
            }
            if (elementIdsArray != null)
            {
                elementIds.AddRange(elementIdsArray.Select(id => id.Value<IdType>()));
            }

            if (elementIds.Count == 0)
            {
                throw new Exception("請提供至少一個元素 ID");
            }

            using (Transaction trans = new Transaction(doc, "變更元素類型"))
            {
                trans.Start();

                int successCount = 0;
                foreach (IdType id in elementIds)
                {
                    Element elem = doc.GetElement(id.ToElementId());
                    if (elem != null && elem.CanHaveTypeAssigned())
                    {
                        try
                        {
                            elem.ChangeTypeId(newTypeId);
                            successCount++;
                        }
                        catch
                        {
                            // 忽略變更失敗的元素
                        }
                    }
                }

                trans.Commit();

                return new
                {
                    Success = true,
                    ChangedCount = successCount,
                    Message = $"已成功變更 {successCount} 個元素的類型"
                };
            }
        }

        /// <summary>
        /// 取得圖框類型
        /// </summary>
        private object GetTitleBlocks()
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            var titleBlocks = new FilteredElementCollector(doc)
                .OfClass(typeof(FamilySymbol))
                .OfCategory(BuiltInCategory.OST_TitleBlocks)
                .Cast<FamilySymbol>()
                .Select(fs => new
                {
                    ElementId = fs.Id.GetIdValue(),
                    Name = fs.Name,
                    FamilyName = fs.FamilyName
                })
                .OrderBy(t => t.FamilyName)
                .ThenBy(t => t.Name)
                .ToList();

            return new
            {
                Count = titleBlocks.Count,
                TitleBlocks = titleBlocks
            };
        }

        /// <summary>
        /// 批次建立圖紙
        /// </summary>
        private object CreateSheets(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            IdType titleBlockId = parameters["titleBlockId"]?.Value<IdType>() ?? 0;
            var sheetsArray = parameters["sheets"] as JArray;

            if (titleBlockId == 0)
            {
                throw new Exception("請提供圖框類型 ID (titleBlockId)");
            }

            if (sheetsArray == null || sheetsArray.Count == 0)
            {
                throw new Exception("請提供要建立的圖紙清單 (sheets)");
            }

            ElementId tbId = titleBlockId.ToElementId();
            Element tbType = doc.GetElement(tbId);
            if (tbType == null)
            {
                throw new Exception($"找不到圖框類型 ID: {titleBlockId}");
            }

            List<object> results = new List<object>();

            using (Transaction trans = new Transaction(doc, "批次建立圖紙"))
            {
                trans.Start();

                foreach (var s in sheetsArray)
                {
                    string number = s["number"]?.Value<string>();
                    string name = s["name"]?.Value<string>();

                    try
                    {
                        // 建立圖紙
                        ViewSheet sheet = ViewSheet.Create(doc, tbId);
                        
                        // 設定編號與名稱
                        if (!string.IsNullOrEmpty(number))
                            sheet.SheetNumber = number;
                        
                        if (!string.IsNullOrEmpty(name))
                            sheet.Name = name;

                        results.Add(new
                        {
                            ElementId = sheet.Id.GetIdValue(),
                            SheetNumber = sheet.SheetNumber,
                            SheetName = sheet.Name,
                            Success = true
                        });
                    }
                    catch (Exception ex)
                    {
                        results.Add(new
                        {
                            SheetNumber = number,
                            SheetName = name,
                            Success = false,
                            Error = ex.Message
                        });
                    }
                }

                trans.Commit();
            }

            return new
            {
                Total = sheetsArray.Count,
                Results = results
            };
        }

        /// <summary>
        /// 取得視埠與圖紙的對應表 (診斷用)
        /// </summary>
        private object GetViewportMap()
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            var result = new List<object>();

            var sheets = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .ToList();

            foreach (var sheet in sheets)
            {
                var vportIds = sheet.GetAllViewports();
                foreach (var vpId in vportIds)
                {
                    var vp = doc.GetElement(vpId) as Viewport;
                    if (vp != null)
                    {
                        var view = doc.GetElement(vp.ViewId) as View;
                        result.Add(new
                        {
                            SheetId = sheet.Id.GetIdValue(),
                            SheetNumber = sheet.SheetNumber,
                            SheetName = sheet.Name,
                            ViewportId = vp.Id.GetIdValue(),
                            ViewId = vp.ViewId.GetIdValue(),
                            ViewName = view?.Name ?? "Unknown",
                            ViewType = view?.ViewType.ToString() ?? "Unknown"
                        });
                    }
                }
            }

            return result;
        }

        /// <summary>
        /// 取得所有圖紙
        /// </summary>
        private object GetAllSheets()
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            var sheets = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .Select(s => new
                {
                    ElementId = s.Id.GetIdValue(),
                    SheetNumber = s.SheetNumber,
                    SheetName = s.Name
                })
                .OrderBy(s => s.SheetNumber)
                .ToList();

            return new
            {
                Count = sheets.Count,
                Sheets = sheets
            };
        }

        /// <summary>
        /// 自動修正圖紙編號 (掃描 -1 後綴並合併)
        /// </summary>
        private object AutoRenumberSheets(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            // --- Phase 0: Emergency Recovery (Fix _MCPFIX) ---
            // 如果上次執行失敗殘留 _MCPFIX，先嘗試還原
            var fixSheets = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .Where(s => s.SheetNumber.EndsWith("_MCPFIX"))
                .ToList();

            if (fixSheets.Count > 0)
            {
                using (Transaction tFix = new Transaction(doc, "還原_MCPFIX"))
                {
                    tFix.Start();
                    foreach (var s in fixSheets)
                    {
                        string original = s.SheetNumber.Replace("_MCPFIX", "");
                        try { s.SheetNumber = original; } catch { /* Ignore collisions during simple restore */ }
                    }
                    tFix.Commit();
                }
            }
            // ------------------------------------------------

            // 1. 重新掃描所有圖紙
            var allSheets = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .ToList();

            // 找出插入目標 (後綴為 "-1")
            var insertSheets = allSheets
                .Where(s => s.SheetNumber.EndsWith("-1"))
                .OrderBy(s => s.SheetNumber)
                .ToList();

            if (insertSheets.Count == 0)
            {
                return new { Success = true, Message = "專案中沒有發現帶有 '-1' 後綴的圖紙" };
            }

            var sheetMap = allSheets.ToDictionary(s => s.SheetNumber, s => s.Id.GetIdValue());
            
            // 用於儲存最終變更: ElementId -> NewNumber
            Dictionary<IdType, string> finalMoves = new Dictionary<IdType, string>();
            
            // 用於追蹤號碼佔用狀況 (包含既有 unoccupied + 已經此輪分配的)
            // Key: Number, Value: Occupier ElementId (若為 -1 表示被新分配的號碼佔用)
            Dictionary<string, IdType> reservationMap = new Dictionary<string, IdType>(sheetMap.Count);
            foreach(var kvp in sheetMap) reservationMap[kvp.Key] = kvp.Value;

            int processedInsertions = 0;

            // 2. 計算變更 (模擬過程)
            // 必須依順序處理，因為前面的推移會改變 reservationMap
            foreach (var sourceSheet in insertSheets)
            {
                IdType sourceId = sourceSheet.Id.GetIdValue();
                string sourceNumber = sourceSheet.SheetNumber; // e.g. ARB-D0902-1
                
                // 計算目標: 去掉 "-1" -> ARB-D0902 -> +1 -> ARB-D0903
                string baseNumber = sourceNumber.Substring(0, sourceNumber.Length - 2); 
                string targetNumber = IncrementString(baseNumber);

                // 鏈鎖推移邏輯
                // 我們要將 sourceSheet 移動到 targetNumber
                // 如果 targetNumber 被佔用，該佔用者要移到 next...
                
                string currentMoverNumber = targetNumber; 
                IdType currentMoverId = sourceId; // 起始移動者

                // 處理鏈鎖
                while (true)
                {
                    // 檢查目標是否被佔用
                    if (reservationMap.ContainsKey(currentMoverNumber))
                    {
                        IdType occupierId = reservationMap[currentMoverNumber];
                        
                        // 如果佔用者就是自己 (例如已經在 map 中)，則視為移動起點，不衝突
                        if (occupierId == currentMoverId)
                        {
                            // 已經到位
                            break;
                        }

                        // 宣告 currentMover 搶佔 target
                        finalMoves[currentMoverId] = currentMoverNumber;
                        // 更新 reservation: currentMover 佔據 currentMoverNumber
                        // 但注意：原佔用者 occupierId 被踢出了，需要找新家
                        reservationMap[currentMoverNumber] = currentMoverId; 

                        // 接下來要處理被踢出的 occupier
                        currentMoverId = occupierId;
                        currentMoverNumber = IncrementString(currentMoverNumber); 
                    }
                    else
                    {
                        // 目標是空的，直接進駐
                        finalMoves[currentMoverId] = currentMoverNumber;
                        reservationMap[currentMoverNumber] = currentMoverId;
                        break; // 鏈鎖結束
                    }

                    // 安全煞車
                    if (finalMoves.Count > 2000) break;
                }
                
                processedInsertions++;
            }

            // 3. 執行變更
            // [New] Smart Sort: 根據圖紙名稱的 (一) (二) (三) 進行重排
            finalMoves = OptimizeSheetOrder(doc, finalMoves);

            int changedCount = 0;
            if (finalMoves.Count > 0)
            {
                using (TransactionGroup tg = new TransactionGroup(doc, "自動圖紙編號修正"))
                {
                    tg.Start();

                    // Step A: 加入暫存後綴 (避免交換時衝突)
                    // 只要在 finalMoves 列表中的都要改
                    using (Transaction t1 = new Transaction(doc, "Step1:暫存"))
                    {
                        t1.Start();
                        foreach (var id in finalMoves.Keys)
                        {
                            Element elem = doc.GetElement(id.ToElementId());
                            if (elem != null) 
                            {
                                Parameter p = elem.get_Parameter(BuiltInParameter.SHEET_NUMBER);
                                // 使用 Guid 確保絕對唯一，避免 _MCPFIX 再次衝突的可能性
                                if (p != null) p.Set(p.AsString() + "_TEMP_" + Guid.NewGuid().ToString().Substring(0,5));
                            }
                        }
                        t1.Commit();
                    }

                    // Step B: 套用正確編號
                    using (Transaction t2 = new Transaction(doc, "Step2:最終"))
                    {
                        t2.Start();
                        foreach (var kvp in finalMoves)
                        {
                            Element elem = doc.GetElement(kvp.Key.ToElementId());
                            if (elem != null)
                            {
                                Parameter p = elem.get_Parameter(BuiltInParameter.SHEET_NUMBER);
                                if (p != null) p.Set(kvp.Value);
                                changedCount++;
                            }
                        }
                        t2.Commit();
                    }

                    tg.Assimilate();
                }
            }

            return new
            {
                Success = true,
                ChangedCount = changedCount,
                InsertionsResolved = processedInsertions,
                Message = $"修復並更新完成：處理了 {processedInsertions} 張插入圖紙，共更新 {changedCount} 個編號"
            };
        }

        /// <summary>
        /// 智慧遞增產生編號序列
        /// </summary>
        private List<string> GenerateSequence(string start, int count)
        {
            List<string> result = new List<string> { start };
            string current = start;

            for (int i = 1; i < count; i++)
            {
                current = IncrementString(current);
                result.Add(current);
            }

            return result;
        }

        /// <summary>
        /// 簡易字串遞增邏輯：尋找結尾數字並 +1
        /// </summary>
        private string IncrementString(string input)
        {
            var match = System.Text.RegularExpressions.Regex.Match(input, @"(.*?)([0-9]+)$");
            if (match.Success)
            {
                string prefix = match.Groups[1].Value;
                string numberStr = match.Groups[2].Value;
                long number = long.Parse(numberStr) + 1;
                return prefix + number.ToString().PadLeft(numberStr.Length, '0');
            }
            return input + "-1"; // 無法解析則加後綴
        }

        
        /// <summary>
        /// 根據圖紙名稱的語意 (一、二、三) 或分頁 (1/3、2/3) 優化編號順序
        /// 注意：只在連續編號群組內排序，不會跨區間混合同名圖紙
        /// </summary>
        private Dictionary<IdType, string> OptimizeSheetOrder(Document doc, Dictionary<IdType, string> moves)
        {
            // 1. 取得所有參與者的完整資訊
            var participants = new List<SheetSortInfo>();
            foreach (var kvp in moves)
            {
                Element elem = doc.GetElement(kvp.Key.ToElementId());
                if (elem != null && elem is ViewSheet sheet)
                {
                    participants.Add(new SheetSortInfo { ID = kvp.Key, Name = sheet.Name, TargetNumber = kvp.Value });
                }
            }

            // 2. 分組：根據去除括號後的 "Base Name"
            // Regex: 支援 (一), (二), (1), (2) 以及 (1/3), (2/3) 等分頁格式
            var regex = new System.Text.RegularExpressions.Regex(@"^(.*?)[\(\（]([\d一二三四五六七八九十]+)(?:/[\d]+)?[\)\）]$");
            
            // 先轉成帶有 MatchIndex 的強型別列表
            var matched = participants
                .Select(p => {
                    var m = regex.Match(p.Name);
                    return new { Data = p, Match = m };
                })
                .Where(x => x.Match.Success)
                .Select(x => new SheetMatchItem { 
                    Data = x.Data, 
                    BaseName = x.Match.Groups[1].Value.Trim(),
                    MatchIndex = GetSheetNameIndex(x.Match.Groups[2].Value) 
                })
                .ToList();

            var groups = matched.GroupBy(x => x.BaseName).ToList();

            var newMoves = new Dictionary<IdType, string>(moves);

            foreach (var grp in groups)
            {
                var items = grp.ToList();
                // 如果群組內只有一張，無需排序
                if (items.Count < 2) continue;

                // [Critical Fix] 再根據連續目標編號進行子分組
                // 避免同名但不同區間的圖紙被混合排序
                items.Sort((a, b) => string.Compare(a.Data.TargetNumber, b.Data.TargetNumber, System.StringComparison.Ordinal));

                // 子分組: 相鄰編號差距 > 3 就切割為新群組
                var subGroups = new List<List<SheetMatchItem>>();
                var currentSubGroup = new List<SheetMatchItem> { items[0] };

                for (int i = 1; i < items.Count; i++)
                {
                    long prevNum = ExtractTrailingNumber(items[i - 1].Data.TargetNumber);
                    long currNum = ExtractTrailingNumber(items[i].Data.TargetNumber);

                    if (currNum - prevNum <= 3)
                    {
                        currentSubGroup.Add(items[i]);
                    }
                    else
                    {
                        subGroups.Add(currentSubGroup);
                        currentSubGroup = new List<SheetMatchItem> { items[i] };
                    }
                }
                subGroups.Add(currentSubGroup);

                // 對每個子群組分別排序
                foreach (var subGrp in subGroups)
                {
                    if (subGrp.Count < 2) continue;

                    // 取得子群組內所有的目標編號，並自然排序
                    var targetNumbers = subGrp.Select(x => x.Data.TargetNumber).OrderBy(n => n).ToList();

                    // 取得子群組內的所有圖紙，並根據名稱中的 MatchIndex 排序
                    var sortedSheets = subGrp.OrderBy(x => x.MatchIndex).ToList();

                    // 重新配對
                    for (int i = 0; i < sortedSheets.Count; i++)
                    {
                        if (i < targetNumbers.Count)
                        {
                            newMoves[sortedSheets[i].Data.ID] = targetNumbers[i];
                        }
                    }
                }
            }

            return newMoves;
        }


        /// <summary>
        /// 從編號字串中提取結尾數字 (用於判斷連續性)
        /// </summary>
        private long ExtractTrailingNumber(string input)
        {
            var match = System.Text.RegularExpressions.Regex.Match(input, @"(\d+)$");
            if (match.Success) return long.Parse(match.Groups[1].Value);
            return 0;
        }


        private int GetSheetNameIndex(string val)
        {
            if (int.TryParse(val, out int n)) return n;
            
            switch (val)
            {
                case "一": return 1;
                case "二": return 2;
                case "三": return 3;
                case "四": return 4;
                case "五": return 5;
                case "六": return 6;
                case "七": return 7;
                case "八": return 8;
                case "九": return 9;
                case "十": return 10;
                default: return 999;
            }
        }

        /// <summary>
        /// 取得詳圖元件列表
        /// </summary>
        private object GetDetailComponents(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            string familyFilter = parameters?["familyName"]?.Value<string>() ?? "";

            var detailItems = new FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_DetailComponents)
                .WhereElementIsNotElementType()
                .Where(e => {
                    var fi = e as FamilyInstance;
                    if (fi == null) return false;
                    return string.IsNullOrEmpty(familyFilter) || fi.Symbol.FamilyName.Contains(familyFilter);
                })
                .Select(e => {
                    var fi = e as FamilyInstance;
                    return new
                    {
                        ElementId = fi.Id.GetIdValue(),
                        FamilyName = fi.Symbol.FamilyName,
                        TypeName = fi.Symbol.Name,
                        OwnerViewId = fi.OwnerViewId.GetIdValue(),
                        Parameters = GetAllParameters(fi)
                    };
                })
                .ToList();

            return new
            {
                Count = detailItems.Count,
                Items = detailItems
            };
        }

        private Dictionary<string, string> GetAllParameters(Element elem)
        {
            var result = new Dictionary<string, string>();
            foreach (Parameter p in elem.Parameters)
            {
                string val = p.AsValueString() ?? p.AsString() ?? "";
                if (!string.IsNullOrEmpty(val))
                {
                    result[p.Definition.Name] = val;
                }
            }
            return result;
        }

        /// <summary>
        /// 取得專案中的明細表
        /// </summary>
        private object GetSchedules(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            string nameFilter = parameters?["name"]?.Value<string>() ?? "";

            var schedules = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSchedule))
                .Cast<ViewSchedule>()
                .Where(vs => !vs.IsTitleblockRevisionSchedule)
                .Where(vs => string.IsNullOrEmpty(nameFilter) || vs.Name.Contains(nameFilter))
                .Select(vs => new
                {
                    ElementId = vs.Id.GetIdValue(),
                    Name = vs.Name,
                    CategoryName = vs.Definition.CategoryId != ElementId.InvalidElementId 
                        ? (Category.GetCategory(doc, vs.Definition.CategoryId)?.Name ?? "N/A") 
                        : "N/A"
                })
                .ToList();

            return new
            {
                Count = schedules.Count,
                Schedules = schedules
            };
        }
        /// <summary>
        /// 同步詳圖元件編號與圖紙編號 (v2: Element-First Approach)
        /// </summary>
        private object SyncDetailComponentNumbers()
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            int updatedInstances = 0;
            int typesCreated = 0;
            var logs = new List<string>();
            
            // 用於追蹤已處理的類型，避免重複 Duplicate
            var processedTypes = new HashSet<string>();

            // 1. 建立 ViewId → Sheet 對應表 (包含視埠內的視圖)
            var viewToSheetMap = new Dictionary<IdType, ViewSheet>();
            var sheets = new FilteredElementCollector(doc)
                .OfClass(typeof(ViewSheet))
                .Cast<ViewSheet>()
                .ToList();
            
            foreach (var sheet in sheets)
            {
                // 建立 Sheet 自身的對應
                viewToSheetMap[sheet.Id.GetIdValue()] = sheet;
                
                // 建立視埠內視圖的對應
                foreach (var vpId in sheet.GetAllViewports())
                {
                    var vp = doc.GetElement(vpId) as Viewport;
                    if (vp != null)
                    {
                        viewToSheetMap[vp.ViewId.GetIdValue()] = sheet;
                    }
                }
            }

            // 2. 找出所有 AE-圖號 元件 (支援 OST_DetailComponents 和 OST_GenericAnnotation)
            var categories = new List<BuiltInCategory> { 
                BuiltInCategory.OST_DetailComponents, 
                BuiltInCategory.OST_GenericAnnotation 
            };
            
            var allInstances = new List<FamilyInstance>();
            foreach (var cat in categories)
            {
                var instances = new FilteredElementCollector(doc)
                    .OfCategory(cat)
                    .WhereElementIsNotElementType()
                    .Where(e => {
                        var fi = e as FamilyInstance;
                        return fi != null && fi.Symbol.FamilyName.Contains("AE-圖號");
                    })
                    .Cast<FamilyInstance>();
                allInstances.AddRange(instances);
            }

            using (TransactionGroup tg = new TransactionGroup(doc, "同步詳圖元件編號"))
            {
                tg.Start();

                foreach (var instance in allInstances)
                {
                    // 3. 查詢該元件所在的圖紙
                    IdType ownerViewId = instance.OwnerViewId.GetIdValue();
                    ViewSheet sheet = null;
                    
                    // 首先嘗試從 viewport 映射表查找
                    if (!viewToSheetMap.TryGetValue(ownerViewId, out sheet))
                    {
                        // 如果查不到，可能是元件直接放在圖紙上 (drafting view or annotation on sheet)
                        // 嘗試將 OwnerViewId 當作 SheetId 來查找
                        Element ownerView = doc.GetElement(ownerViewId.ToElementId());
                        sheet = ownerView as ViewSheet;
                        
                        if (sheet == null)
                        {
                            // 既不在 viewport 視圖中，也不在圖紙上，跳過
                            continue;
                        }
                    }

                    string sheetNumber = sheet.SheetNumber;
                    string sheetName = sheet.Name;
                    FamilySymbol currentSymbol = instance.Symbol;
                    
                    // 4. 讀取現有的「詳圖名稱」參數 (優先使用參數值)
                    Parameter pCurrentDetailName = currentSymbol.LookupParameter("詳圖名稱");
                    string detailName = pCurrentDetailName?.AsString() ?? "";
                    
                    // 5. 如果參數為空，從現有類型名稱進行精準解析
                    if (string.IsNullOrEmpty(detailName))
                    {
                        string typeName = currentSymbol.Name;
                        // 移除 圖紙編號- 的前綴 (考慮編號本身帶有橫線的情形)
                        string prefix = sheetNumber + "-";
                        if (typeName.StartsWith(prefix))
                        {
                            string remaining = typeName.Substring(prefix.Length);
                            // 剩下的部分如果是 "圖紙名稱-詳圖名稱" 或只是 "圖紙名稱"
                            int lastDash = remaining.LastIndexOf('-');
                            if (lastDash > 0)
                            {
                                string extractedDetail = remaining.Substring(lastDash + 1);
                                // 檢查提取出來的是否真的是詳圖名稱，還是只是內容重複
                                if (extractedDetail != sheetName)
                                {
                                    detailName = extractedDetail;
                                }
                            }
                        }
                    }
                    
                    // 如果還是空的且舊名稱中能找到圖紙名稱以外的部分，則保留。否則預設給空或由使用者手動處理。
                    // 這裡的邏輯是：如果我們無法確定詳圖名稱，就不要亂加。
                    
                    // 6. 只更新現有類型參數 (v3.5: Safeguard Mode)
                    // 核心邏輯：只有當類型名稱已經符合圖紙編號時才進行參數同步。
                    // 這能避免「共用標準詳圖」（如 D0921）在被放到其他圖紙（如 D02X2）時，參數被錯誤地「感染」。
                    
                    if (!currentSymbol.Name.StartsWith(sheetNumber + "-"))
                    {
                        // 如果類型名稱與目前圖紙不匹配，跳過此實例，不更改其類型參數。
                        continue;
                    }

                    // 避免重複處理同一類型
                    string typeKey = $"{currentSymbol.FamilyName}:{currentSymbol.Name}";
                    if (processedTypes.Contains(typeKey)) continue;

                    using (Transaction t = new Transaction(doc, "同步元件類型"))
                    {
                        t.Start();
                        
                        // 更新當前類型的參數（詳圖圖號、圖說名稱）
                        Parameter pTypeSheetNum = currentSymbol.LookupParameter("詳圖圖號");
                        if (pTypeSheetNum != null && !pTypeSheetNum.IsReadOnly)
                        {
                            pTypeSheetNum.Set(sheetNumber);
                        }
                        
                        Parameter pTypeSheetName = currentSymbol.LookupParameter("圖說名稱");
                        if (pTypeSheetName != null && !pTypeSheetName.IsReadOnly)
                        {
                            pTypeSheetName.Set(sheetName);
                        }

                        t.Commit();
                        updatedInstances++;
                        processedTypes.Add(typeKey);
                    }
                }
                tg.Assimilate();
            }

            return new
            {
                Success = true,
                UpdatedInstances = updatedInstances,
                TypesCreated = typesCreated,
                Message = $"同步完成：更新了 {updatedInstances} 個標頭元件，建立了 {typesCreated} 個新類型。"
            };
        }

        /// <summary>
        /// 建立詳圖元件類型（依據圖紙編號）
        /// </summary>
        private object CreateDetailComponentType(JObject parameters)
        {
            try {
                Document doc = _uiApp.ActiveUIDocument.Document;
                
                // 1. 取得參數
                string sheetNumber = parameters?["sheetNumber"]?.Value<string>();
                string detailName = parameters?["detailName"]?.Value<string>();
                string familyName = parameters?["familyName"]?.Value<string>();
                string detailNumber = parameters?["detailNumber"]?.Value<string>() ?? "1";
                
                if (string.IsNullOrEmpty(sheetNumber))
                {
                    return new { Success = false, Error = "必須提供 sheetNumber 參數" };
                }
                
                if (string.IsNullOrEmpty(detailName))
                {
                    return new { Success = false, Error = "必須提供 detailName 參數" };
                }
                
                // 2. 查詢圖紙
                var sheet = new FilteredElementCollector(doc)
                    .OfClass(typeof(ViewSheet))
                    .Cast<ViewSheet>()
                    .FirstOrDefault(s => s.SheetNumber == sheetNumber);
                
                if (sheet == null)
                {
                    return new { Success = false, Error = $"找不到圖紙編號: {sheetNumber}" };
                }
                
                string sheetName = sheet.Name;
                
                // 3. 尋找指定的 family 的任一類型作為基礎
                FamilySymbol baseSymbol = null;
                if (!string.IsNullOrEmpty(familyName))
                {
                    baseSymbol = new FilteredElementCollector(doc)
                        .OfClass(typeof(FamilySymbol))
                        .Cast<FamilySymbol>()
                        .FirstOrDefault(s => s.FamilyName != null && (s.FamilyName.Equals(familyName, StringComparison.OrdinalIgnoreCase) || s.FamilyName.Contains(familyName)));
                    
                    if (baseSymbol == null)
                    {
                        return new { Success = false, Error = $"找不到指定的詳圖項目族群: {familyName}" };
                    }
                }
                else
                {
                    baseSymbol = new FilteredElementCollector(doc)
                        .OfClass(typeof(FamilySymbol))
                        .Cast<FamilySymbol>()
                        .FirstOrDefault(s => s.FamilyName != null && s.FamilyName.Contains("AE-圖號"));
                    
                    if (baseSymbol == null)
                    {
                        return new { Success = false, Error = "找不到 AE-圖號詳圖編號標頭 family" };
                    }
                }
                
                // 4. 建構目標類型名稱
                string targetTypeName = $"{sheetNumber}-{sheetName}-{detailName}";
                
                // 5. 檢查是否已存在
                try
                {
                    var existingSymbol = new FilteredElementCollector(doc)
                        .OfClass(typeof(FamilySymbol))
                        .Cast<FamilySymbol>()
                        .FirstOrDefault(s => s.FamilyName != null && s.FamilyName == baseSymbol.FamilyName && s.Name == targetTypeName);
                    
                    if (existingSymbol != null)
                    {
                        return new 
                        { 
                            Success = false, 
                            Error = $"類型已存在: {targetTypeName}",
                            ExistingTypeId = existingSymbol.Id.GetIdValue()
                        };
                    }
                }
                catch (Exception ex)
                {
                    return new { Success = false, Error = $"查詢現有類型時發生錯誤: {ex.Message}" };
                }
                
                // 6. 建立新類型
                using (Transaction t = new Transaction(doc, "建立詳圖元件類型"))
                {
                    try
                    {
                        t.Start();
                        
                        if (baseSymbol == null) return new { Success = false, Error = "baseSymbol 為空，無法複製" };
                        
                        var newSymbol = baseSymbol.Duplicate(targetTypeName) as FamilySymbol;
                        if (newSymbol == null) return new { Success = false, Error = $"複製類型失敗: {targetTypeName}" };
                        
                        // 7. 設定類型參數（v3 mapping）
                        // 詳圖圖號 ← 圖紙編號
                        Parameter pTypeSheetNum = newSymbol.LookupParameter("詳圖圖號");
                        if (pTypeSheetNum != null && !pTypeSheetNum.IsReadOnly)
                        {
                            pTypeSheetNum.Set(sheetNumber);
                        }
                        
                        // 圖說名稱 ← 圖紙名稱
                        Parameter pTypeSheetName = newSymbol.LookupParameter("圖說名稱");
                        if (pTypeSheetName != null && !pTypeSheetName.IsReadOnly)
                        {
                            pTypeSheetName.Set(sheetName ?? "");
                        }
                        
                        // 詳圖名稱 ← 使用者輸入
                        Parameter pTypeDetailName = newSymbol.LookupParameter("詳圖名稱");
                        if (pTypeDetailName != null && !pTypeDetailName.IsReadOnly)
                        {
                            pTypeDetailName.Set(detailName ?? "");
                        }
                        
                        // 詳圖編號 ← 使用者輸入或預設 "1"
                        Parameter pTypeDetailNumber = newSymbol.LookupParameter("詳圖編號");
                        if (pTypeDetailNumber != null && !pTypeDetailNumber.IsReadOnly)
                        {
                            pTypeDetailNumber.Set(detailNumber);
                        }
                        
                        t.Commit();
                        
                        return new
                        {
                            Success = true,
                            TypeId = newSymbol.Id.GetIdValue(),
                            TypeName = newSymbol.Name,
                            SheetNumber = sheetNumber,
                            SheetName = sheetName,
                            DetailName = detailName,
                            DetailNumber = detailNumber
                        };
                    }
                    catch (Exception ex)
                    {
                        if (t.GetStatus() == TransactionStatus.Started) t.RollBack();
                        return new { Success = false, Error = $"建立類型核心錯誤: {ex.Message}" };
                    }
                }
            } catch (Exception ex) {
                return new { Success = false, Error = $"CreateDetailComponentType 全域錯誤: {ex.Message}\n{ex.StackTrace}" };
            }
        }

        private object ListFamilySymbols(JObject parameters)
        {
            try
            {
                Document doc = _uiApp.ActiveUIDocument.Document;
                string filterName = parameters?["filter"]?.Value<string>();

                var symbols = new FilteredElementCollector(doc)
                    .OfClass(typeof(FamilySymbol))
                    .Cast<FamilySymbol>()
                    .Where(s => string.IsNullOrEmpty(filterName) || 
                               (s.FamilyName != null && s.FamilyName.Contains(filterName)) ||
                               (s.Name != null && s.Name.Contains(filterName)))
                    .Select(s => new { 
                        Id = s.Id.GetIdValue(), 
                        Name = s.Name, 
                        FamilyName = s.FamilyName ?? "<NULL>",
                        Category = s.Category?.Name ?? "<NO_CAT>"
                    })
                    .Take(100)
                    .ToList();

                return new { Success = true, Symbols = symbols };
            }
            catch (Exception ex)
            {
                return new { Success = false, Error = ex.Message, StackTrace = ex.StackTrace };
            }
        }

        private class SheetSortInfo
        {
            public IdType ID { get; set; }
            public string Name { get; set; }
            public string TargetNumber { get; set; }
        }

        private class SheetMatchItem
        {
            public SheetSortInfo Data { get; set; }
            public string BaseName { get; set; }
            public int MatchIndex { get; set; }
        }

        #endregion

        #region 視圖樣版查詢

        /// <summary>
        /// 取得所有視圖樣版及其設定
        /// </summary>
        private object GetViewTemplates(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            bool includeDetails = parameters["includeDetails"]?.Value<bool>() ?? true;

            // 取得所有視圖樣版 (IsTemplate = true)
            var viewTemplates = new FilteredElementCollector(doc)
                .OfClass(typeof(View))
                .Cast<View>()
                .Where(v => v.IsTemplate)
                .OrderBy(v => v.ViewType.ToString())
                .ThenBy(v => v.Name)
                .ToList();

            var templateList = new List<object>();

            foreach (var template in viewTemplates)
            {
                var templateInfo = new Dictionary<string, object>
                {
                    ["ElementId"] = template.Id.GetIdValue(),
                    ["Name"] = template.Name,
                    ["ViewType"] = template.ViewType.ToString(),
                    ["ViewFamily"] = template.ViewType.ToString()
                };

                if (includeDetails)
                {
                    // 取得詳細等級
                    try
                    {
                        templateInfo["DetailLevel"] = template.DetailLevel.ToString();
                    }
                    catch { templateInfo["DetailLevel"] = "N/A"; }

                    // 取得視覺樣式
                    try
                    {
                        templateInfo["DisplayStyle"] = template.DisplayStyle.ToString();
                    }
                    catch { templateInfo["DisplayStyle"] = "N/A"; }

                    // 取得比例尺
                    try
                    {
                        templateInfo["Scale"] = template.Scale > 0 ? $"1:{template.Scale}" : "N/A";
                    }
                    catch { templateInfo["Scale"] = "N/A"; }

                    // 取得視圖樣版控制的參數
                    try
                    {
                        var nonControlledParams = template.GetNonControlledTemplateParameterIds();
                        var allParams = template.GetTemplateParameterIds();
                        templateInfo["ControlledParameterCount"] = allParams.Count - nonControlledParams.Count;
                        templateInfo["TotalParameterCount"] = allParams.Count;
                    }
                    catch 
                    { 
                        templateInfo["ControlledParameterCount"] = "N/A";
                        templateInfo["TotalParameterCount"] = "N/A";
                    }

                    // 取得類別可見性設定（僅列出主要隱藏的類別）
                    try
                    {
                        var hiddenCategories = new List<string>();
                        var categories = doc.Settings.Categories;
                        foreach (Category cat in categories)
                        {
                            try
                            {
                                if (cat.CategoryType == CategoryType.Model || cat.CategoryType == CategoryType.Annotation)
                                {
                                    if (!template.GetCategoryHidden(cat.Id))
                                        continue;
                                    hiddenCategories.Add(cat.Name);
                                }
                            }
                            catch { }
                        }
                        templateInfo["HiddenCategoryCount"] = hiddenCategories.Count;
                        // 只列出前 10 個隱藏類別
                        templateInfo["HiddenCategories"] = hiddenCategories.Take(10).ToList();
                    }
                    catch { templateInfo["HiddenCategories"] = new List<string>(); }

                    // 取得視圖專屬覆寫（篩選器）
                    try
                    {
                        var filterIds = template.GetFilters();
                        var filterNames = filterIds
                            .Select(id => doc.GetElement(id)?.Name ?? "Unknown")
                            .ToList();
                        templateInfo["FilterCount"] = filterIds.Count;
                        templateInfo["Filters"] = filterNames;
                    }
                    catch 
                    { 
                        templateInfo["FilterCount"] = 0;
                        templateInfo["Filters"] = new List<string>(); 
                    }

                    // 取得裁剪設定
                    try
                    {
                        templateInfo["CropBoxActive"] = template.CropBoxActive;
                        templateInfo["CropBoxVisible"] = template.CropBoxVisible;
                    }
                    catch 
                    { 
                        templateInfo["CropBoxActive"] = "N/A";
                        templateInfo["CropBoxVisible"] = "N/A";
                    }

                    // 取得底層設定
                    try
                    {
                        templateInfo["SupportsUnderlay"] = (template.ViewType == ViewType.FloorPlan || 
                                                            template.ViewType == ViewType.CeilingPlan ||
                                                            template.ViewType == ViewType.AreaPlan);
                    }
                    catch { templateInfo["SupportsUnderlay"] = false; }
                }

                templateList.Add(templateInfo);
            }

            return new
            {
                ProjectName = doc.Title,
                Count = templateList.Count,
                ViewTemplates = templateList
            };
        }

        #endregion

        /// <summary>
        /// 使用射線偵測建立尺寸標註 (Ray-Casting)
        /// </summary>
        private object CreateDimensionByRay(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            IdType viewId = parameters["viewId"]?.Value<IdType>() ?? 0;
            
            // 起點 (通常是房間中心)
            double originX = parameters["origin"]?["x"]?.Value<double>() ?? 0;
            double originY = parameters["origin"]?["y"]?.Value<double>() ?? 0;
            double originZ = parameters["origin"]?["z"]?.Value<double>() ?? 0;

            // 正向射線方向
            double dirX = parameters["direction"]?["x"]?.Value<double>() ?? 0;
            double dirY = parameters["direction"]?["y"]?.Value<double>() ?? 0;
            double dirZ = parameters["direction"]?["z"]?.Value<double>() ?? 0;
            
            // 反向射線方向 (若未提供，則取反)
            double counterDirX = parameters["counterDirection"]?["x"]?.Value<double>() ?? -dirX;
            double counterDirY = parameters["counterDirection"]?["y"]?.Value<double>() ?? -dirY;
            double counterDirZ = parameters["counterDirection"]?["z"]?.Value<double>() ?? -dirZ;

            View view = doc.GetElement(viewId.ToElementId()) as View;
            if (view == null)
            {
                throw new Exception($"找不到視圖 ID: {viewId}");
            }

            // 收集所有可用的3D視圖（優先選擇沒有Section Box的）
            List<View3D> available3DViews = new FilteredElementCollector(doc)
                .OfClass(typeof(View3D))
                .Cast<View3D>()
                .Where(v => !v.IsTemplate)
                .OrderBy(v => v.IsSectionBoxActive ? 1 : 0) // 沒有Section Box的排前面
                .ToList();
            
            if (available3DViews.Count == 0)
            {
                throw new Exception("專案中沒有可用的 3D 視圖");
            }

            using (Transaction trans = new Transaction(doc, "建立射線標註"))
            {
                trans.Start();

                // 轉換座標與向量
                XYZ origin = new XYZ(originX / 304.8, originY / 304.8, originZ / 304.8);
                XYZ direction = new XYZ(dirX, dirY, dirZ).Normalize();
                XYZ counterDirection = new XYZ(counterDirX, counterDirY, counterDirZ).Normalize();

                Reference ref1 = null;
                Reference ref2 = null;
                
                // 嘗試使用不同的3D視圖，直到找到能偵測到兩個方向牆面的視圖
                foreach (View3D view3D in available3DViews)
                {
                    ElementFilter filter = new ElementMulticategoryFilter(new List<BuiltInCategory> { 
                        BuiltInCategory.OST_Walls, 
                        BuiltInCategory.OST_StructuralColumns, 
                        BuiltInCategory.OST_Columns 
                    });
                    ReferenceIntersector iterator = new ReferenceIntersector(filter, FindReferenceTarget.Face, view3D);
                    
                    ReferenceWithContext ref1Context = iterator.FindNearest(origin, direction);
                    ReferenceWithContext ref2Context = iterator.FindNearest(origin, counterDirection);

                    if (ref1Context != null && ref2Context != null)
                    {
                        // 成功找到兩個方向的牆面
                        ref1 = ref1Context.GetReference();
                        ref2 = ref2Context.GetReference();
                        break;
                    }
                }

                if (ref1 == null || ref2 == null)
                {
                    throw new Exception("所有3D視圖都無法偵測到足夠的邊界，請確認房間周圍是否有完整的牆面");
                }

                // 取得接觸點
                XYZ point1 = ref1.GlobalPoint;
                XYZ point2 = ref2.GlobalPoint;

                // 建立標註參考線的位置 (稍微偏移原點，避免重疊)
                XYZ dimDir = direction.CrossProduct(XYZ.BasisZ);
                if (dimDir.IsZeroLength()) dimDir = XYZ.BasisX;

                double offset = 500 / 304.8; 
                XYZ dimLineStart = point1.Add(dimDir.Multiply(offset));
                XYZ dimLineEnd = point2.Add(dimDir.Multiply(offset));
                Line dimLine = Line.CreateBound(dimLineStart, dimLineEnd);

                // 建立參考陣列
                ReferenceArray refArray = new ReferenceArray();
                refArray.Append(ref1);
                refArray.Append(ref2);

                // 建立標註
                Dimension dim = doc.Create.NewDimension(view, dimLine, refArray);

                trans.Commit();

                double dimValue = dim.Value.HasValue ? dim.Value.Value * 304.8 : 0;

                return new
                {
                    DimensionId = dim.Id.GetIdValue(),
                    Value = Math.Round(dimValue, 2),
                    Unit = "mm"
                };
            }
        }

        private object CreateDimensionByBoundingBox(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;

            IdType viewId = parameters["viewId"]?.Value<IdType>() ?? 0;
            IdType roomId = parameters["roomId"]?.Value<IdType>() ?? 0;
            string axis = parameters["axis"]?.Value<string>() ?? "X";
            double offset = parameters["offset"]?.Value<double>() ?? 500; // mm

            View view = doc.GetElement(viewId.ToElementId()) as View;
            if (view == null)
            {
                throw new Exception($"找不到視圖 ID: {viewId}");
            }

            Room room = doc.GetElement(roomId.ToElementId()) as Room;
            if (room == null)
            {
                throw new Exception($"找不到房間 ID: {roomId}");
            }

            BoundingBoxXYZ bbox = room.get_BoundingBox(view);
            if (bbox == null)
            {
                throw new Exception($"房間 {room.Name} 沒有邊界框");
            }

            using (Transaction trans = new Transaction(doc, "建立邊界框標註"))
            {
                trans.Start();

                XYZ min = bbox.Min;
                XYZ max = bbox.Max;
                double offsetFeet = offset / 304.8;

                XYZ point1, point2, dimLineStart, dimLineEnd;

                if (axis.ToUpper() == "X")
                {
                    // X軸：從 MinX 到 MaxX
                    double centerY = (min.Y + max.Y) / 2;
                    point1 = new XYZ(min.X, centerY, min.Z);
                    point2 = new XYZ(max.X, centerY, min.Z);
                    
                    // 標註線偏移到上方
                    dimLineStart = new XYZ(min.X, centerY + offsetFeet, min.Z);
                    dimLineEnd = new XYZ(max.X, centerY + offsetFeet, min.Z);
                }
                else // Y軸
                {
                    // Y軸：從 MinY 到 MaxY
                    double centerX = (min.X + max.X) / 2;
                    point1 = new XYZ(centerX, min.Y, min.Z);
                    point2 = new XYZ(centerX, max.Y, min.Z);
                    
                    // 標註線偏移到右側
                    dimLineStart = new XYZ(centerX + offsetFeet, min.Y, min.Z);
                    dimLineEnd = new XYZ(centerX + offsetFeet, max.Y, min.Z);
                }

                Line dimLine = Line.CreateBound(dimLineStart, dimLineEnd);

                // 建立參考點 (使用DetailCurve)
                double lineLength = 1.0; // 1英尺
                XYZ perpDir = (axis.ToUpper() == "X") ? XYZ.BasisY : XYZ.BasisX;

                DetailCurve dc1 = doc.Create.NewDetailCurve(view, Line.CreateBound(
                    point1.Subtract(perpDir.Multiply(lineLength / 2)),
                    point1.Add(perpDir.Multiply(lineLength / 2))));
                DetailCurve dc2 = doc.Create.NewDetailCurve(view, Line.CreateBound(
                    point2.Subtract(perpDir.Multiply(lineLength / 2)),
                    point2.Add(perpDir.Multiply(lineLength / 2))));

                ReferenceArray refArray = new ReferenceArray();
                refArray.Append(dc1.GeometryCurve.Reference);
                refArray.Append(dc2.GeometryCurve.Reference);

                Dimension dim = doc.Create.NewDimension(view, dimLine, refArray);

                trans.Commit();

                double dimValue = dim.Value.HasValue ? dim.Value.Value * 304.8 : 0;

                return new
                {
                    DimensionId = dim.Id.GetIdValue(),
                    Value = Math.Round(dimValue, 2),
                    Unit = "mm",
                    Axis = axis,
                    RoomName = room.Name
                };
            }
        }

        #region 批次從屬視圖依網格裁剪
        
        /// <summary>
        /// 計算網格範圍加上偏移的 BoundingBox
        /// </summary>
        private object CalculateGridBounds(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            
            var xGridsArray = parameters["xGrids"] as JArray;
            var yGridsArray = parameters["yGrids"] as JArray;
            double offsetMm = parameters["offset_mm"]?.Value<double>() ?? 0;
            double offsetFeet = offsetMm / 304.8;
            
            List<string> xGridNames = xGridsArray?.Select(x => x.Value<string>()).ToList() ?? new List<string>();
            List<string> yGridNames = yGridsArray?.Select(x => x.Value<string>()).ToList() ?? new List<string>();

            if (xGridNames.Count == 0 && yGridNames.Count == 0)
            {
                throw new Exception("至少需要提供一組 X 軸或 Y 軸網格線名稱");
            }

            // 抓取所有這張圖上的網格
            var allGrids = new FilteredElementCollector(doc)
                .OfClass(typeof(Grid))
                .Cast<Grid>()
                .ToList();

            double minX = double.MaxValue;
            double maxX = double.MinValue;
            double minY = double.MaxValue;
            double maxY = double.MinValue;

            // 處理 X 軸網格 (垂直線，取得其 X 座標)
            if (xGridNames.Count > 0)
            {
                foreach (string name in xGridNames)
                {
                    var grid = allGrids.FirstOrDefault(g => g.Name.Equals(name, StringComparison.OrdinalIgnoreCase));
                    if (grid != null)
                    {
                        var curve = grid.Curve;
                        // 取起點與終點的 X 座標來決定邊界 (垂直線 X 應相近)
                        double x1 = curve.GetEndPoint(0).X;
                        double x2 = curve.GetEndPoint(1).X;
                        double x = (x1 + x2) / 2.0;
                        
                        minX = Math.Min(minX, x);
                        maxX = Math.Max(maxX, x);
                    }
                }
            }

            // 處理 Y 軸網格 (水平線，取得其 Y 座標)
            if (yGridNames.Count > 0)
            {
                foreach (string name in yGridNames)
                {
                    var grid = allGrids.FirstOrDefault(g => g.Name.Equals(name, StringComparison.OrdinalIgnoreCase));
                    if (grid != null)
                    {
                        var curve = grid.Curve;
                        // 取起點與終點的 Y 座標來決定邊界 (水平線 Y 應相近)
                        double y1 = curve.GetEndPoint(0).Y;
                        double y2 = curve.GetEndPoint(1).Y;
                        double y = (y1 + y2) / 2.0;

                        minY = Math.Min(minY, y);
                        maxY = Math.Max(maxY, y);
                    }
                }
            }
            
            // 防呆處理：如果不滿兩條線，自己加上 offset
            if (xGridNames.Count == 1)
            {
                // minX 與 maxX 目前一樣，往外擴
                minX -= offsetFeet;
                maxX += offsetFeet;
            }
            if (yGridNames.Count == 1)
            {
                minY -= offsetFeet;
                maxY += offsetFeet;
            }

            // 最終的邊界
            double finalMinX = (xGridNames.Count > 0 ? minX : -1000) - offsetFeet;
            double finalMaxX = (xGridNames.Count > 0 ? maxX : 1000) + offsetFeet;
            double finalMinY = (yGridNames.Count > 0 ? minY : -1000) - offsetFeet;
            double finalMaxY = (yGridNames.Count > 0 ? maxY : 1000) + offsetFeet;

            // Z 軸給足夠大的範圍
            XYZ min = new XYZ(finalMinX, finalMinY, -100);
            XYZ max = new XYZ(finalMaxX, finalMaxY, 100);

            return new
            {
                min = new { x = finalMinX * 304.8, y = finalMinY * 304.8, z = -100 * 304.8 },
                max = new { x = finalMaxX * 304.8, y = finalMaxY * 304.8, z =  100 * 304.8 }
            };
        }

        /// <summary>
        /// 批次建立從屬視圖並套用邊界
        /// </summary>
        private object CreateDependentViews(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            
            var parentViewIdsArray = parameters["parentViewIds"] as JArray;
            List<IdType> parentViewIds = parentViewIdsArray?.Select(x => x.Value<IdType>()).ToList() ?? new List<IdType>();
            
            string suffixName = parameters["suffixName"]?.Value<string>();
            
            double minX = parameters["min"]?["x"]?.Value<double>() ?? 0;
            double minY = parameters["min"]?["y"]?.Value<double>() ?? 0;
            double minZ = parameters["min"]?["z"]?.Value<double>() ?? -100 * 304.8;
            double maxX = parameters["max"]?["x"]?.Value<double>() ?? 0;
            double maxY = parameters["max"]?["y"]?.Value<double>() ?? 0;
            double maxZ = parameters["max"]?["z"]?.Value<double>() ??  100 * 304.8;

            XYZ min = new XYZ(minX / 304.8, minY / 304.8, minZ / 304.8);
            XYZ max = new XYZ(maxX / 304.8, maxY / 304.8, maxZ / 304.8);
            BoundingBoxXYZ bbox = new BoundingBoxXYZ { Min = min, Max = max };

            List<object> results = new List<object>();

            using (Transaction trans = new Transaction(doc, "批次建立從屬視圖"))
            {
                trans.Start();

                foreach (IdType viewId in parentViewIds)
                {
                    View parentView = doc.GetElement(viewId.ToElementId()) as View;
                    if (parentView == null || !parentView.CanViewBeDuplicated(ViewDuplicateOption.AsDependent))
                    {
                        continue;
                    }

                    // 1. 建立從屬視圖
                    ElementId newViewId = parentView.Duplicate(ViewDuplicateOption.AsDependent);
                    View newView = doc.GetElement(newViewId) as View;

                    // 2. 決定命名後綴
                    string finalSuffix = suffixName;
                    if (string.IsNullOrEmpty(finalSuffix))
                    {
                        // 找尋已有的從屬視圖，自動編號
                        int childCount = parentView.GetDependentViewIds().Count();
                        finalSuffix = childCount.ToString();
                        
                        // 嘗試避免名稱重複
                        string targetName = $"{parentView.Name}-{finalSuffix}";
                        int loopGuard = 0;
                        while(new FilteredElementCollector(doc).OfClass(typeof(View)).Cast<View>().Any(v => v.Name == targetName) && loopGuard < 100)
                        {
                            childCount++;
                            finalSuffix = childCount.ToString();
                            targetName = $"{parentView.Name}-{finalSuffix}";
                            loopGuard++;
                        }
                    }

                    // 3. 重新命名
                    string newName = $"{parentView.Name}-{finalSuffix}";
                    try
                    {
                        newView.Name = newName;
                    }
                    catch { /* 忽略已經存在的名稱錯誤，保持預設命名 */ }

                    // 4. 設定裁剪範圍
                    newView.CropBoxActive = true;
                    newView.CropBoxVisible = true;
                    newView.CropBox = bbox;

                    results.Add(new
                    {
                        ParentName = parentView.Name,
                        NewViewId = newView.Id.GetIdValue(),
                        NewViewName = newView.Name
                    });
                }

                trans.Commit();
            }

            return results;
        }

        #endregion

        #region 外牆開口檢討

        /// <summary>
        /// 執行外牆開口檢討（第45條 + 第110條）
        /// </summary>
        private object CheckExteriorWallOpenings(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            UIDocument uidoc = _uiApp.ActiveUIDocument;

            bool checkArticle45 = parameters["checkArticle45"]?.Value<bool>() ?? true;
            bool checkArticle110 = parameters["checkArticle110"]?.Value<bool>() ?? true;
            bool colorizeViolations = parameters["colorizeViolations"]?.Value<bool>() ?? true;
            bool checkBuildingDistance = parameters["checkBuildingDistance"]?.Value<bool>() ?? false;
            bool exportReport = parameters["exportReport"]?.Value<bool>() ?? false;
            string reportPath = parameters["reportPath"]?.Value<string>();

            var checker = new ExteriorWallOpeningChecker(doc);
            var allResults = new List<object>();

            using (Transaction trans = new Transaction(doc, "外牆開口檢討"))
            {
                // 使用防禦性交易處理
                bool isTransactionStarted = false;

                // 2. 取得所有外牆
                int totalWalls = 0;
                int totalOpenings = 0;
                int violations = 0;
                int warnings = 0;
                int passed = 0;
                
                // 1. 取得基地邊界線
                // Note: GetPropertyLines doesn't require transaction status to run, assuming it just reads.
                // However, to be safe and consistent with previous flow, we'll keep logic similar but ensure variables are scoped correctly.
                List<Curve> propertyLines = null;

                try
                {
                    if (trans.Start() == TransactionStatus.Started)
                    {
                        isTransactionStarted = true;

                        // DEBUG VERSION LOG
                        System.Diagnostics.Debug.WriteLine("DLL Version: 2026.01.14.02 - Transaction Started");

                        propertyLines = checker.GetPropertyLines();
                        if (propertyLines.Count == 0)
                        {
                            throw new InvalidOperationException("找不到基地邊界線（PropertyLine）。請確認專案中已建立地界線，且您已結束編輯模式（打勾）。");
                        }

                        var exteriorWalls = checker.GetExteriorWalls();

                        // 3. 遍歷每面外牆
                        foreach (var wall in exteriorWalls)
                        {
                            totalWalls++;
                            var openings = checker.GetWallOpenings(wall);

                            foreach (var opening in openings)
                            {
                                totalOpenings++;
                                var openingInfo = checker.GetOpeningInfo(opening);
                                if (openingInfo == null) continue;

                                // 計算距離
                                var boundaryResult = checker.CalculateDistanceToBoundary(openingInfo, propertyLines);
                                var distanceToBoundary = boundaryResult.MinDistance;
                                var distanceToBuilding = checkBuildingDistance
                                    ? checker.CalculateDistanceToAdjacentBuildings(openingInfo, wall)
                                    : double.MaxValue;

                                // 執行檢查
                                ExteriorWallOpeningChecker.Article45Result article45Result = null;
                                ExteriorWallOpeningChecker.Article110Result article110Result = null;

                                if (checkArticle45)
                                {
                                    article45Result = checker.CheckArticle45(openingInfo, distanceToBoundary, distanceToBuilding);
                                }

                                if (checkArticle110)
                                {
                                    article110Result = checker.CheckArticle110(openingInfo, distanceToBoundary, distanceToBuilding);
                                }

                                // 視覺化
                                if (colorizeViolations)
                                {
                                    var overallStatus = DetermineOverallStatus(article45Result, article110Result);
                                    ColorizeOpening(doc, uidoc.ActiveView, opening.Id, overallStatus);

                                    if (overallStatus == ExteriorWallOpeningChecker.CheckStatus.Fail) violations++;
                                    else if (overallStatus == ExteriorWallOpeningChecker.CheckStatus.Warning) warnings++;
                                    else passed++;

                                    // 如果違規或有警告，建立標註 (Dimension)
                                    if ((overallStatus == ExteriorWallOpeningChecker.CheckStatus.Fail || overallStatus == ExteriorWallOpeningChecker.CheckStatus.Warning) && boundaryResult.ClosestPoint != null)
                                    {
                                        try
                                        {
                                            // 1. 定義標註線 (Opening Center -> Boundary Point)
                                            // 確保 Z 軸一致 (在開口高度)
                                            XYZ start = openingInfo.Location;
                                            XYZ end = new XYZ(boundaryResult.ClosestPoint.X, boundaryResult.ClosestPoint.Y, start.Z);
                                            
                                            // 避免極短線段
                                            if (start.DistanceTo(end) > 0.01)
                                            {
                                                Line line = Line.CreateBound(start, end);

                                                // 2. 建立參考平面 (SketchPlane)
                                                // 需要一個包含該線的平面。水平線通常位於 XY 平面。
                                                XYZ norm = XYZ.BasisZ;
                                                Plane plane = Plane.CreateByNormalAndOrigin(norm, start);
                                                SketchPlane sketchPlane = SketchPlane.Create(doc, plane);

                                                // 3. 建立模型線 (Model Line)
                                                ModelCurve modelCurve = doc.Create.NewModelCurve(line, sketchPlane);
                                                
                                                // 嘗試設定線樣式為紅色 (若有)
                                                // (省略樣式設定以保持簡單)

                                                // 4. 建立尺寸標註 (Dimension)
                                                // 尺寸標註必須依附於 View。如果 View 是 3D View，必須設定 WorkPoint。
                                                // 簡單起見，嘗試建立基於模型線端點的尺寸。
                                                
                                                ReferenceArray refArray = new ReferenceArray();
                                                refArray.Append(modelCurve.GeometryCurve.GetEndPointReference(0));
                                                refArray.Append(modelCurve.GeometryCurve.GetEndPointReference(1));

                                                Dimension dim = doc.Create.NewDimension(uidoc.ActiveView, line, refArray);

                                                // 5. 將標註設為紅色
                                                OverrideGraphicSettings redOverride = new OverrideGraphicSettings();
                                                redOverride.SetProjectionLineColor(new Color(255, 0, 0)); // 紅色
                                                uidoc.ActiveView.SetElementOverrides(dim.Id, redOverride);
                                            }
                                        }
                                        catch (Exception dimEx)
                                        {
                                            // 標註建立失敗不應中斷檢討流程
                                            System.Diagnostics.Debug.WriteLine($"無法建立標註: {dimEx.Message}");
                                        }
                                    }
                                }

                                // 記錄結果
                                allResults.Add(new
                                {
                                    openingId = openingInfo.OpeningId.GetIdValue(),
                                    wallId = openingInfo.WallId?.GetIdValue(),
                                    openingType = openingInfo.OpeningType,
                                    location = new
                                    {
                                        x = Math.Round(openingInfo.Location.X * 304.8, 2),
                                        y = Math.Round(openingInfo.Location.Y * 304.8, 2),
                                        z = Math.Round(openingInfo.Location.Z * 304.8, 2)
                                    },
                                    area = Math.Round(openingInfo.Area * 0.0929, 2), // 平方英尺 → 平方公尺
                                    article45 = article45Result,
                                    article110 = article110Result
                                });
                            }
                        }

                        trans.Commit();
                    }
                    else
                    {
                        throw new InvalidOperationException("無法啟動 Revit 交易，可能目前正處於其他命令或編輯模式中。");
                    }

                    var summary = new
                    {
                        totalWalls,
                        totalOpenings,
                        violations,
                        warnings,
                        passed,
                        propertyLineCount = propertyLines.Count
                    };

                    var response = new
                    {
                        success = true,
                        summary,
                        details = allResults,
                        message = $"檢討完成：共檢查 {totalWalls} 面外牆、{totalOpenings} 個開口"
                    };

                    // 匯出報表（可選）
                    if (exportReport && !string.IsNullOrEmpty(reportPath))
                    {
                        System.IO.File.WriteAllText(reportPath,
                            Newtonsoft.Json.JsonConvert.SerializeObject(response, Newtonsoft.Json.Formatting.Indented));
                    }

                    return response;
                }
                catch (Exception ex)
                {
                    if (isTransactionStarted && trans.GetStatus() == TransactionStatus.Started)
                    {
                        trans.RollBack();
                    }
                    throw new Exception($"外牆開口檢討失敗：{ex.Message}");
                }
            }
        }

        /// <summary>
        /// 判定總體狀態
        /// </summary>
        private ExteriorWallOpeningChecker.CheckStatus DetermineOverallStatus(
            ExteriorWallOpeningChecker.Article45Result article45Result,
            ExteriorWallOpeningChecker.Article110Result article110Result)
        {
            var statuses = new List<ExteriorWallOpeningChecker.CheckStatus>();

            if (article45Result != null) statuses.Add(article45Result.OverallStatus);
            if (article110Result != null) statuses.Add(article110Result.OverallStatus);

            if (statuses.Contains(ExteriorWallOpeningChecker.CheckStatus.Fail)) 
                return ExteriorWallOpeningChecker.CheckStatus.Fail;
            if (statuses.Contains(ExteriorWallOpeningChecker.CheckStatus.Warning)) 
                return ExteriorWallOpeningChecker.CheckStatus.Warning;
            return ExteriorWallOpeningChecker.CheckStatus.Pass;
        }

        /// <summary>
        /// 為開口元素設定顏色
        /// 同時設定 Cut（平面圖）和 Surface（立面圖）樣式，確保所有視圖類型都能顯示
        /// </summary>
        private void ColorizeOpening(Document doc, View view, ElementId openingId, ExteriorWallOpeningChecker.CheckStatus status)
        {
            var overrideSettings = new OverrideGraphicSettings();
            ElementId solidPatternId = GetSolidFillPatternId(doc);
            Color color;

            switch (status)
            {
                case ExteriorWallOpeningChecker.CheckStatus.Fail:
                    color = new Color(255, 0, 0); // 紅色
                    break;
                case ExteriorWallOpeningChecker.CheckStatus.Warning:
                    color = new Color(255, 165, 0); // 橘色
                    break;
                case ExteriorWallOpeningChecker.CheckStatus.Pass:
                    color = new Color(0, 255, 0); // 綠色
                    break;
                default:
                    return;
            }

            // 投影線顏色（所有視圖通用）
            overrideSettings.SetProjectionLineColor(color);

            // Surface pattern（立面/剖面/3D）
            overrideSettings.SetSurfaceForegroundPatternColor(color);
            if (solidPatternId != null && solidPatternId != ElementId.InvalidElementId)
            {
                overrideSettings.SetSurfaceForegroundPatternId(solidPatternId);
                overrideSettings.SetSurfaceForegroundPatternVisible(true);
            }

            // Cut pattern（平面圖中門窗被牆切割時顯示）
            overrideSettings.SetCutForegroundPatternColor(color);
            if (solidPatternId != null && solidPatternId != ElementId.InvalidElementId)
            {
                overrideSettings.SetCutForegroundPatternId(solidPatternId);
                overrideSettings.SetCutForegroundPatternVisible(true);
            }

            // Cut line 顏色
            overrideSettings.SetCutLineColor(color);

            view.SetElementOverrides(openingId, overrideSettings);
        }

        private object CreateDimensionByRay_Debug(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            double originX = parameters["origin"]?["x"]?.Value<double>() ?? 0;
            double originY = parameters["origin"]?["y"]?.Value<double>() ?? 0;
            double originZ = parameters["origin"]?["z"]?.Value<double>() ?? 0;
            double dirX = parameters["direction"]?["x"]?.Value<double>() ?? 0;
            double dirY = parameters["direction"]?["y"]?.Value<double>() ?? 0;
            double dirZ = parameters["direction"]?["z"]?.Value<double>() ?? 1;

            XYZ origin = new XYZ(originX / 304.8, originY / 304.8, originZ / 304.8);
            XYZ direction = new XYZ(dirX, dirY, dirZ).Normalize();

            View3D view3D = new FilteredElementCollector(doc).OfClass(typeof(View3D)).Cast<View3D>().FirstOrDefault(v => !v.IsTemplate);
            
            ElementFilter filter = new ElementMulticategoryFilter(new List<BuiltInCategory> { BuiltInCategory.OST_Walls, BuiltInCategory.OST_StructuralColumns, BuiltInCategory.OST_Columns });
            ReferenceIntersector iterator = new ReferenceIntersector(filter, FindReferenceTarget.Element, view3D);
            
            IList<ReferenceWithContext> hits = iterator.Find(origin, direction);

            return new
            {
                Origin = new { X = originX, Y = originY, Z = originZ },
                Direction = new { X = dirX, Y = dirY, Z = dirZ },
                View3D = view3D?.Name,
                HitCount = hits.Count,
                Hits = hits.Select(h => new { 
                    Distance = h.Proximity * 304.8, 
                    ElemId = h.GetReference()?.ElementId?.GetIdValue() 
                }).ToList()
            };
        }
        /// <summary>
        /// 取得所有線型樣式
        /// </summary>
        private object GetLineStyles()
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            var result = new List<Dictionary<string, object>>();
            
            var allStyles = new FilteredElementCollector(doc)
                .OfClass(typeof(GraphicsStyle))
                .ToElements();

            foreach (Element elem in allStyles)
            {
                GraphicsStyle gs = elem as GraphicsStyle;
                if (gs == null) continue;
                
                try
                {
                    Category cat = gs.GraphicsStyleCategory;
                    if (cat == null) continue;
                    Category parent = cat.Parent;
                    if (parent == null) continue;
                    
                    // 使用名稱比對而非 Id 轉型，更穩定
                    if (parent.Name == "Lines" || parent.Name == "線" || parent.Name == "線條")
                    {
                        result.Add(new Dictionary<string, object> {
                            { "Id", gs.Id.IntegerValue },
                            { "Name", gs.Name }
                        });
                    }
                }
                catch
                {
                    continue;
                }
            }

            return result.OrderBy(r => r["Name"].ToString()).ToList();
        }



        /// <summary>
        /// 建立多條詳圖線
        /// </summary>
        private object CreateDetailLines(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            View view = _uiApp.ActiveUIDocument.ActiveView;
            
            var linesArray = parameters["lines"] as JArray;
            IdType? styleId = parameters["styleId"]?.Value<IdType>();

            if (linesArray == null || linesArray.Count == 0)
                throw new Exception("請提供線段座標列表");

            // 取得視圖平面資訊 (確保 DetailCurve 正確落在視圖平面上)
            XYZ viewDir = view.ViewDirection;
            XYZ origin = view.Origin;

            using (Transaction trans = new Transaction(doc, "建立詳圖線"))
            {
                trans.Start();
                
                GraphicsStyle style = null;
                if (styleId.HasValue && styleId.Value > 0)
                {
                    style = doc.GetElement(styleId.Value.ToElementId()) as GraphicsStyle;
                }

                var detailCurves = new List<IdType>();
                int skipped = 0;
                foreach (var lineData in linesArray)
                {
                    try
                    {
                        double startX = lineData["startX"]?.Value<double>() ?? 0;
                        double startY = lineData["startY"]?.Value<double>() ?? 0;
                        double startZ = lineData["startZ"]?.Value<double>() ?? 0;
                        double endX = lineData["endX"]?.Value<double>() ?? 0;
                        double endY = lineData["endY"]?.Value<double>() ?? 0;
                        double endZ = lineData["endZ"]?.Value<double>() ?? 0;

                        XYZ p0 = new XYZ(startX / 304.8, startY / 304.8, startZ / 304.8);
                        XYZ p1 = new XYZ(endX / 304.8, endY / 304.8, endZ / 304.8);

                        // 投影到視圖平面: 新點 = 原點 + (深度 * 視圖方向)
                        double depth0 = (origin - p0).DotProduct(viewDir);
                        XYZ start = p0 + viewDir * depth0;

                        double depth1 = (origin - p1).DotProduct(viewDir);
                        XYZ end = p1 + viewDir * depth1;
                        
                        // 確保投影後線段長度仍然有效
                        if (start.DistanceTo(end) < 0.01) { skipped++; continue; }

                        Line line = Line.CreateBound(start, end);
                        DetailCurve dc = doc.Create.NewDetailCurve(view, line);
                        
                        if (style != null)
                            dc.LineStyle = style;
                            
                        detailCurves.Add(dc.Id.GetIdValue());
                    }
                    catch
                    {
                        skipped++;
                    }
                }

                trans.Commit();
                return new { Count = detailCurves.Count, Skipped = skipped, ElementIds = detailCurves };
            }
        }

        private class EdgeData 
        {
            public double Depth;
            public double Length;
            public bool IsStepProfile;
            public XYZ P0;
            public XYZ P1;
        }

        /// <summary>
        /// 追蹤樓梯幾何並偵測被遮擋的邊緣 (支援剖面圖，僅繪製切面後方第一排踏階)
        /// </summary>
        private object TraceStairGeometry(JObject parameters)
        {
            Document doc = _uiApp.ActiveUIDocument.Document;
            View view = _uiApp.ActiveUIDocument.ActiveView;

            XYZ viewDir = view.ViewDirection; // 預設指向螢幕外部 (朝向觀察者)
            XYZ origin = view.Origin;

            // 僅抓取 StairRuns (梯段)，排除 Landings (平台) 與 Supports (支撐)
            var runs = new FilteredElementCollector(doc, view.Id)
                .OfCategory(BuiltInCategory.OST_StairsRuns)
                .WhereElementIsNotElementType()
                .Cast<Autodesk.Revit.DB.Architecture.StairsRun>()
                .ToList();

            var result = new List<object>();

            foreach (var run in runs)
            {
                // [過濾邏輯]：只處理有「側邊支撐(桁條)」的組合樓梯 (Assembled Stairs)
                Autodesk.Revit.DB.Architecture.Stairs parentStair = run.GetStairs();
                if (parentStair != null)
                {
                    ElementType stairType = doc.GetElement(parentStair.GetTypeId()) as ElementType;
                    if (stairType != null)
                    {
                        string familyName = stairType.FamilyName;
                        // 排除 RC 樓梯 (現場澆注樓梯/整體樓梯)，因為沒有側邊桁條遮擋，不需要畫背面虛線
                        if (!familyName.Contains("組合") && !familyName.Contains("Assembled"))
                        {
                            continue;
                        }
                    }
                }

                // 用 DetailLevel = Fine 取 3D 模型實體幾何
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
                                
                                if (c.Length < 0.01) continue; // 忽略極小邊 (< 3mm)

                                XYZ p0 = c.GetEndPoint(0);
                                XYZ p1 = c.GetEndPoint(1);
                                XYZ mid = c.Evaluate(0.5, true);

                                // 計算深度 (Depth > 0 代表在切面後方)
                                double depth = (origin - mid).DotProduct(viewDir);
                                
                                // 投影後的長度與方向
                                double d0 = (origin - p0).DotProduct(viewDir);
                                double d1 = (origin - p1).DotProduct(viewDir);
                                XYZ proj0 = p0 + viewDir * d0;
                                XYZ proj1 = p1 + viewDir * d1;
                                double projLen = proj0.DistanceTo(proj1);

                                // 忽略投影後變為點的邊
                                if (projLen < 0.01) continue;

                                XYZ dir = (proj1 - proj0).Normalize();

                                bool isHorizontal = Math.Abs(dir.Z) < 0.1;
                                bool isVertical = Math.Abs(Math.Abs(dir.Z) - 1.0) < 0.1;

                                // 踏階輪廓條件: 水平(踏面)、垂直(豎板)，或者投影長度很短(如突出的收邊/倒角)
                                // 短於 0.65 ft (約 20 cm) 的線都會被保留，但會濾掉長度超過的斜線(如梯段底部的斜板)
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
                    // 該梯段的最淺深度 (最靠近切面的點)
                    double minDepth = allEdges.Min(e => e.Depth);
                    
                    // 【修正 2】如果這個梯段有任何部分被剖切到或在切面前方 (minDepth <= 0.05)，
                    // 則代表這是「前景梯段」，我們不畫它的背面邊線，直接略過整個梯段。
                    if (minDepth <= 0.05) continue;

                    // 僅保留第一排的踏階與豎板 (距離該梯段最前緣 2.5 呎內)
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

        #endregion
    }
}





