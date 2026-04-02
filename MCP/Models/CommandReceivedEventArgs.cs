using System;
using System.Net.WebSockets;

namespace RevitMCP.Models
{
    public class CommandReceivedEventArgs : EventArgs
    {
        public RevitCommandRequest Request { get; set; }
        public WebSocket SourceSocket { get; set; }
    }
}
