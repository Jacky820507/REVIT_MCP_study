/**
 * Revit Socket Client
 * Handles WebSocket communication with Revit Plugin
 */

import WebSocket from 'ws';

export interface RevitCommand {
    commandName: string;
    parameters: Record<string, any>;
    requestId?: string;
}

export interface RevitResponse {
    success: boolean;
    data?: any;
    error?: string;
    requestId?: string;
}

// 預設 port 為 8964，可透過環境變數 REVIT_MCP_PORT 覆寫
const DEFAULT_PORT = 8964;

function getConfiguredPort(): number {
    const envPort = process.env.REVIT_MCP_PORT;
    if (envPort) {
        const parsed = parseInt(envPort, 10);
        if (!isNaN(parsed) && parsed >= 1024 && parsed <= 65535) {
            return parsed;
        }
        console.error(`[Socket] Invalid REVIT_MCP_PORT="${envPort}", using default ${DEFAULT_PORT}`);
    }
    return DEFAULT_PORT;
}

export class RevitSocketClient {
    private ws: WebSocket | null = null;
    private connecting: Promise<void> | null = null;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private explicitlyDisconnected = false;
    private host: string = 'localhost';
    private port: number = DEFAULT_PORT;
    private reconnectInterval: number = 5000; // 5 seconds
    private responseHandlers: Map<string, (response: RevitResponse) => void> = new Map();

    /**
     * 連線時回報給 Revit add-in 的客戶端名稱（來自 MCP initialize 的 clientInfo.name，
     * 例如 claude-code / claude-ai / Visual Studio Code）。由 index.ts 在連線前設定。
     * add-in 會以此顯示「目前佔用連線的工具」。
     */
    public clientName: string = "unknown";
    // 同一個 MCP Server process 重連時沿用這個 ID；不同 process 即使
    // clientInfo.name 相同，也不能互相踢掉獨佔連線，否則會形成 409/重連風暴。
    private readonly clientInstanceId: string =
        `codex-mcp-${process.pid}-${Date.now()}-${Math.random().toString(36).slice(2)}`;

    constructor(host: string = 'localhost', port?: number) {
        this.host = host;
        this.port = port ?? getConfiguredPort();
    }

    /**
     * Connect to Revit Plugin
     */
    async connect(): Promise<void> {
        if (this.isConnected()) {
            return;
        }

        // MCP host 可能同時送出多個 tool call；所有 call 必須共用同一個握手，
        // 否則第二個 WebSocket 會被 Revit 的獨佔鎖正確拒絕為 HTTP 409。
        if (this.connecting) {
            return this.connecting;
        }

        this.explicitlyDisconnected = false;
        const attempt = this.openConnection();
        this.connecting = attempt;

        try {
            await attempt;
        } finally {
            if (this.connecting === attempt) {
                this.connecting = null;
            }
            if (!this.isConnected()) {
                this.scheduleReconnect();
            }
        }
    }

    private openConnection(): Promise<void> {
        return new Promise((resolve, reject) => {
            const wsUrl = `ws://${this.host}:${this.port}/?client=${encodeURIComponent(this.clientName)}&instance=${encodeURIComponent(this.clientInstanceId)}`;
            console.error(`[Socket] Connecting to Revit: ${wsUrl}`);

            const socket = new WebSocket(wsUrl);
            this.ws = socket;
            let settled = false;

            const settleReject = (error: Error) => {
                if (settled) {
                    return;
                }
                settled = true;
                reject(error);
            };

            socket.on('open', () => {
                console.error('[Socket] Connected to Revit Plugin');
                if (!settled) {
                    settled = true;
                    resolve();
                }
            });

            socket.on('message', (data: WebSocket.Data) => {
                try {
                    const rawResponse = JSON.parse(data.toString());
                    // Map PascalCase from C# to camelCase for internal use
                    const response: RevitResponse = {
                        success: rawResponse.Success,
                        data: rawResponse.Data,
                        error: rawResponse.Error,
                        requestId: rawResponse.RequestId,
                    };
                    console.error('[Socket] Received response:', response);

                    // Handle Response
                    if (response.requestId) {
                        const handler = this.responseHandlers.get(response.requestId);
                        if (handler) {
                            handler(response);
                            this.responseHandlers.delete(response.requestId);
                        }
                    }
                } catch (error) {
                    console.error('[Socket] Failed to parse message:', error);
                }
            });

            socket.on('error', (error) => {
                console.error('[Socket] WebSocket Error:', error);
                settleReject(error instanceof Error ? error : new Error(String(error)));
            });

            socket.on('close', () => {
                console.error('[Socket] Connection closed');
                if (this.ws === socket) {
                    this.ws = null;
                }

                if (!settled) {
                    settleReject(new Error('Revit WebSocket closed before connection was established'));
                }

                this.scheduleReconnect();
            });

            // Connection Timeout
            setTimeout(() => {
                if (!settled && socket.readyState !== WebSocket.OPEN) {
                    try {
                        socket.close();
                    } catch {
                        // Ignore a socket that has already been closed by ws.
                    }
                    settleReject(new Error('Connection Timeout: Please ensure Revit Plugin is running and MCP server is enabled'));
                }
            }, 10000);
        });
    }

    private scheduleReconnect(): void {
        if (this.explicitlyDisconnected || this.reconnectTimer !== null || this.isConnected() || this.connecting) {
            return;
        }

        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            if (this.explicitlyDisconnected || this.isConnected() || this.connecting) {
                return;
            }

            console.error('[Socket] Attempting to reconnect...');
            this.connect().catch(err => {
                console.error('[Socket] Reconnection failed:', err);
            });
        }, this.reconnectInterval);
    }

    /**
     * Send command to Revit
     */
    async sendCommand(commandName: string, parameters: Record<string, any> = {}, timeoutMs: number = 30000): Promise<RevitResponse> {
        if (!this.isConnected()) {
            throw new Error('Not connected to Revit Plugin');
        }

        const requestId = this.generateRequestId();
        const command = {
            method: commandName,
            params: parameters,
            id: requestId,
        };

        console.error(`[Socket] Sending command: ${commandName}`, parameters);

        return new Promise((resolve, reject) => {
            // Register response handler
            this.responseHandlers.set(requestId, (response: RevitResponse) => {
                if (response.success) {
                    resolve(response);
                } else {
                    reject(new Error(response.error || 'Command failed'));
                }
            });

            // Send command
            this.ws?.send(JSON.stringify(command));

            // Request Timeout
            setTimeout(() => {
                if (this.responseHandlers.has(requestId)) {
                    this.responseHandlers.delete(requestId);
                    reject(new Error('Command timed out'));
                }
            }, timeoutMs); // default 30 seconds; cross-document commands pass a longer value
        });
    }

    /**
     * Check connection status
     */
    isConnected(): boolean {
        return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
    }

    /**
     * Disconnect
     */
    disconnect(): void {
        this.explicitlyDisconnected = true;
        if (this.reconnectTimer !== null) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }

        const socket = this.ws;
        this.ws = null;
        if (socket) {
            socket.close();
        }
    }

    /**
     * Generate Request ID
     */
    private generateRequestId(): string {
        return `req_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
    }
}
