using System;
using Newtonsoft.Json;

namespace RevitMCP.Models
{
    /// <summary>
    /// Revit 命令請求模型
    /// </summary>
    [Serializable]
    public class RevitCommandRequest
    {
        /// <summary>
        /// 命令名稱
        /// </summary>
        [JsonProperty("method")]
        public string CommandName { get; set; }

        [JsonProperty("CommandName")]
        private string CommandNamePascal
        {
            set
            {
                if (string.IsNullOrEmpty(CommandName))
                {
                    CommandName = value;
                }
            }
        }

        [JsonProperty("commandName")]
        private string CommandNameCamel
        {
            set
            {
                if (string.IsNullOrEmpty(CommandName))
                {
                    CommandName = value;
                }
            }
        }

        /// <summary>
        /// 命令參數（JSON 字串）
        /// </summary>
        [JsonProperty("params")]
        public object Parameters { get; set; }

        [JsonProperty("Parameters")]
        private object ParametersPascal
        {
            set
            {
                if (Parameters == null)
                {
                    Parameters = value;
                }
            }
        }

        [JsonProperty("parameters")]
        private object ParametersCamel
        {
            set
            {
                if (Parameters == null)
                {
                    Parameters = value;
                }
            }
        }

        /// <summary>
        /// 請求 ID（用於追蹤回應）
        /// </summary>
        [JsonProperty("id")]
        public string RequestId { get; set; }

        [JsonProperty("RequestId")]
        private string RequestIdPascal
        {
            set
            {
                if (string.IsNullOrEmpty(RequestId))
                {
                    RequestId = value;
                }
            }
        }

        [JsonProperty("requestId")]
        private string RequestIdCamel
        {
            set
            {
                if (string.IsNullOrEmpty(RequestId))
                {
                    RequestId = value;
                }
            }
        }
    }

    /// <summary>
    /// Revit 命令回應模型
    /// </summary>
    [Serializable]
    public class RevitCommandResponse
    {
        /// <summary>
        /// 執行是否成功
        /// </summary>
        public bool Success { get; set; }

        /// <summary>
        /// 回應資料
        /// </summary>
        public object Data { get; set; }

        /// <summary>
        /// 錯誤訊息
        /// </summary>
        public string Error { get; set; }

        /// <summary>
        /// 請求 ID
        /// </summary>
        public string RequestId { get; set; }
    }
}
