<h2 align="center"><font color="#8B0000"> 友善提醒：本專案預設使用 Port: 8964，請確保該埠號未被佔用 </font></h2>

# Revit MCP - AI-Powered Revit Control

English | [繁體中文](README.zh-TW.md)

Revit MCP lets AI clients call Autodesk Revit tools through the Model Context Protocol (MCP). The MCP server forwards tool calls to a local Revit add-in, and the add-in executes the corresponding Revit API workflow.

- Demo video: [Revit MCP - AI-Powered BIM Workflow Demonstration](https://youtu.be/YpAYF-GxrhA)
- Knowledge site: <https://shuotao.github.io/REVIT_MCP_study/>
- Default WebSocket port: `8964`

## Current Project Counts

| Item | Count | Source |
|---|---:|---|
| Runtime MCP tools | 146 | `registerRevitTools()` in `MCP-Server/src/tools/index.ts` |
| Domain SOP files | 61 | `domain/*.md` except `README.md`, plus `domain/references/*.md` |
| Claude skills | 42 | `.claude/skills/*/SKILL.md` |

When these numbers change, update `CLAUDE.md`, `README.zh-TW.md`, this file, `docs/DOCUMENT_AUDIENCE_INVENTORY.md`, and run:

**📚 知識站：<https://shuotao.github.io/REVIT_MCP_study/>** — 三層架構 / 22 命題 / 決策框架 / 全 67 Domain + 30 Skill + 139 Tool 視覺化索引

---

> [!IMPORTANT]
> ## 🌍 部署者必讀：設定全域 AI 邊界
> 
> 若您使用 **Google Antigravity** 或 **Gemini CLI**，為了確保 AI 進入本專案時**不會繞過**專案內的實作邊界（如 L1-L5 限制），請務必在您的全域規則中設定專案級文件的最高優先級。
> 
> 1. 請自行使用編輯器建立或開啟（若目錄不存在請先建立）：
>    - Mac/Linux: `~/.gemini/GEMINI.md`
>    - Windows: `%USERPROFILE%\.gemini\GEMINI.md`
> 2. 複製並加入以下極簡的「全域先決條件」範本：
> 
> ```markdown
> # Global Agent Rules
> 1. Before executing any task, ALWAYS check the current workspace root for `GEMINI.md`, `CLAUDE.md`, or `.agents/rules/`.
> 2. If present, MUST READ them first. These project-level files act as your absolute constitution. 
> 3. Their instructions and capability boundaries STRICTLY OVERRIDE any default behaviors or global rules.
> ```
> *(遵循原廠邏輯：將全域規則保持極簡，純粹作為「引導 AI 尋找專案憲法」的入口，避免過多指令干擾造成幻覺。)*

---

> [!TIP]
> ## 你是誰？從這裡開始
>
> 本專案有多個入口文件，請依你的身份選擇閱讀路徑：
>
> | 你的身份 | 先讀這個 | 再讀這個 |
> |---|---|---|
> | **想理解這個專案在做什麼** | [shuotao.github.io/REVIT_MCP_study](https://shuotao.github.io/REVIT_MCP_study/)（知識站） | — |
> | **想安裝使用 Revit MCP** | 本檔下方「一鍵安裝」段 | — |
> | **想貢獻 domain 知識 / SOP / 規則** | [CONTRIBUTING.md](./CONTRIBUTING.md) | [domain/README.md](./domain/README.md) |
> | **想開發新工具 / 修改程式碼** | [CLAUDE.md](./CLAUDE.md) | 執行 `/dev-guide` 命令 |
> | **想了解整體架構** | [CLAUDE.md](./CLAUDE.md) | [docs/DOCS_STRUCTURE.md](./docs/DOCS_STRUCTURE.md) |
> | **我是 AI Agent**（Claude / Gemini / Copilot） | [CLAUDE.md](./CLAUDE.md)（**必讀**） | 依任務觸發對應 skill |
>
> ---
>
> ### 關鍵原則（所有角色都要遵守）
>
> - **AI 規範唯一性**：`GEMINI.md` 和 `AGENTS.md` 皆重定向至 `CLAUDE.md`，為專案唯一 AI 規範文件
> - **Safety First**：所有 Revit 操作必須可逆，使用 Transaction 確保可復原
> - **Workflow Compliance**：AI Agent 執行任務前，必須先檢查 `domain/` 目錄是否已有對應的工作流程
> - **貢獻邊界**：程式碼由維護者管理，外部貢獻者只修改 `domain/` 知識檔案（詳見 [CONTRIBUTING.md](./CONTRIBUTING.md)）
>
> ---

> [!CAUTION]
> ##  Git Pull 後必讀：重新編譯 Revit Add-in
> 
> 如果您執行了 `git pull` 更新專案，且更新內容包含 **C# 程式碼變更**（`MCP/*.cs` 檔案），**必須重新編譯並部署 Revit Add-in DLL**，否則新功能將無法使用！
> 
> **快速步驟：**
> 1. **關閉 Revit**（否則無法覆蓋 DLL）
> 2. 執行編譯：
>    ```powershell
>    cd "您的專案路徑/MCP"
>    # 根據您的 Revit 版本選擇對應的組態：
>    dotnet build -c Release.R22   # Revit 2022
>    dotnet build -c Release.R23   # Revit 2023
>    dotnet build -c Release.R24   # Revit 2024
>    dotnet build -c Release.R25   # Revit 2025
>    dotnet build -c Release.R26   # Revit 2026
>    ```
> 3. 複製 DLL 到 Revit Addins 資料夾：
>    ```powershell
>    Copy-Item "bin/Release.R{YY}/RevitMCP.dll" "C:\ProgramData\Autodesk\Revit\Addins\2024\RevitMCP\" -Force
>    ```
> 4. 重新啟動 Revit
> 
> | 更新類型 | 需重新編譯 DLL？ | 需重啟 Revit？ |
> |----------|:---------------:|:-------------:|
> | C# 程式碼 (`MCP/*.cs`) | ✅ 是 | ✅ 是 |
> | MCP Server (`MCP-Server/*.ts`) | ❌ 否 | ❌ 否（只需重啟 MCP Server） |
> | 設定檔 (`*.json`, `*.addin`) | ❌ 否 | ⚠️ 視情況 |
>
> 💡 **使用 Claude Code 的使用者**：本專案內建 Claude Code 技能可自動化上述步驟：
> ```
> /build-revit             # 選擇 Revit 版本後自動編譯
> /build-revit --all       # 一次編譯所有版本（2022-2026）
> /deploy-addon            # 自動部署 DLL 到正確路徑（僅 Windows）
> ```

## 一鍵安裝（推薦新手使用）

**完全不需要任何程式知識！** 只要三步：

1. `git clone` 本專案（[不會 clone？看這裡](#-透過-git-clone-的首次設定)）
2. 在 `scripts` 資料夾中找到 **`setup.bat`**
3. **雙擊執行** — 不需要管理員權限

腳本會自動完成所有安裝步驟：
- 檢查並安裝 Node.js 和 .NET SDK
- 編譯 MCP Server
- 讓您選擇 Revit 版本（支援多選，用方向鍵和空白鍵操作）
- 編譯並部署 Revit Add-in
- 自動設定 AI 客戶端（Claude Desktop、Gemini CLI、VS Code）

> **AI Agent 模式**：如果您透過 AI 助手操作，可使用非互動模式：
> ```powershell
> powershell -ExecutionPolicy Bypass -File scripts/setup.ps1 -NonInteractive -RevitVersions "2024,2025"
> ```

---

## 🎯 功能特色

- **AI 直接控制 Revit** - 透過自然語言指令操作 Revit
- **支援多種 AI 平台** - Claude Desktop、Gemini CLI、VS Code Copilot、Google Antigravity
- **豐富的 Revit 工具** - 建立牆、樓板、門窗、查詢元素等
- **即時雙向通訊** - WebSocket 即時連線

##  專案結構

```
REVIT-MCP/
├── MCP/                    # Revit Add-in (C#)
│   ├── Application.cs           # 主程式進入點
│   ├── ConnectCommand.cs        # 連線命令
│   ├── RevitMCP.addin           # Add-in 配置
│   ├── RevitMCP.csproj          # 統一專案檔 (Revit 2022–2026, Nice3point SDK)
│   ├── Core/                    # 核心功能
│   │   ├── SocketService.cs     # WebSocket 服務
│   │   ├── CommandExecutor.cs   # 命令執行器
│   │   ├── RevitCompatibility.cs # 跨版本相容層 (ElementId int→long)
│   │   └── ExternalEventManager.cs
│   ├── Models/                  # 資料模型
│   └── Configuration/           # 設定管理
├── MCP-Server/             # MCP Server (Node.js/TypeScript)
│   ├── src/
│   │   ├── index.ts                 # MCP Server 主程式
│   │   ├── socket.ts                # Socket 客戶端
│   │   └── tools/
│   │       └── revit-tools.ts       # Revit 工具定義
│   ├── build/                       # 編譯輸出
│   ├── package.json
│   └── tsconfig.json
└── README.md
```

## Architecture

```text
AI Client
  Claude Desktop / Claude Code / Gemini CLI / VS Code Copilot / Antigravity
        |
        | stdio
        v
MCP Server
  Node.js / TypeScript
  MCP-Server/build/index.js
        |
        | WebSocket ws://localhost:8964
        v
Revit Add-in
  C# / Revit API
  MCP/Application.cs
  MCP/Core/SocketService.cs
  MCP/Core/ExternalEventManager.cs
        |
        v
Autodesk Revit
```

External AI clients do not need an API key inside this repository. Their account and authorization are managed by the AI client itself. Only an embedded Revit chat feature that directly calls an AI API would need an API key.

## Requirements

| Item | Requirement |
|---|---|
| OS | Windows 10 or later |
| Revit | Autodesk Revit 2022, 2023, 2024, 2025, 2026 |
| .NET | .NET Framework 4.8 for Revit 2022-2024; .NET 8 for Revit 2025-2026 |
| Node.js | LTS, preferably 20.x or later |

## One-Click Setup

Recommended for new users:

```powershell
# 檢查是否已安裝
node --version

# 如果沒有安裝，請前往 https://nodejs.org 下載 LTS 版本
```

For AI agents or non-interactive setup:

```powershell
# 進入 MCP-Server 資料夾
cd "您的專案路徑/MCP-Server"

The setup script checks prerequisites, installs dependencies, builds the MCP server, builds and deploys the Revit add-in, and helps configure common AI clients.

## Manual Setup

### 1. Build the MCP Server

```powershell
cd MCP-Server
npm install

# 編譯 TypeScript
npm run build
```

AI clients launch:

設定檔中的路徑需要根據您的環境修改：

### 2. Build the Revit Add-in

Choose the configuration that matches your Revit version:

```powershell
# 進入 MCP 專案資料夾
cd "您的專案路徑/MCP"

# 根據您的 Revit 版本選擇對應的組態：
dotnet build -c Release.R22   # Revit 2022
dotnet build -c Release.R23   # Revit 2023
dotnet build -c Release.R24   # Revit 2024
dotnet build -c Release.R25   # Revit 2025
dotnet build -c Release.R26   # Revit 2026
```

Expected output:

---

## 📦 安裝步驟

#### 步驟 1：安裝 Revit Add-in（只需複製檔案）

**簡單說：我們需要把一個檔案放到 Revit 的特定資料夾裡。**

 **重要：在開始前，請確認您的 Revit 版本**  
- 開啟 Revit
- 點擊左上角的「Autodesk Revit 202X」（X 是您的版本號）
- 再點擊「幫助」→「關於 Autodesk Revit」
- 查看版本號並記住它（例如：2022、2023、2024、2025 或 2026）

#### 方式 A：使用自動化腳本（推薦）

**最簡單的方法：執行自動安裝指令稿**

1. **前往 scripts 資料夾**
   - 開啟檔案總管，進入專案的 `scripts/` 資料夾

2. **執行安裝腳本**
   - 右鍵選擇 `install-addon.ps1`
   - 選擇「以 PowerShell 執行」
   
   >  **如果遇到權限問題**：
   > 請以系統管理員身分開啟 PowerShell，並執行：
   > ```powershell
   > Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   > .\install-addon.ps1
   > ```

3. **腳本會自動執行**
   - 編譯 C# 專案
   - 偵測您的 Revit 版本（2022、2023、2024）
   - 複製 DLL 和 .addin 檔案到正確位置

4. **完成**
   - 看到「安裝成功」訊息即完成
   - 重新啟動 Revit

>  **提示**：如果腳本執行失敗，請確認已安裝 .NET SDK 並可執行 `dotnet` 命令。

#### 方式 B：手動編譯與安裝

1. **確認已安裝 .NET SDK**
   ```powershell
   # 檢查 .NET SDK
   dotnet --version
   
   # 如果未安裝，請前往 https://dotnet.microsoft.com/download
   ```

2. **編譯專案**
   ```powershell
   # 進入專案目錄
   cd "您的專案路徑\MCP"
   
   # 根據您的 Revit 版本選擇對應的組態
   dotnet build -c Release.R22   # Revit 2022
   dotnet build -c Release.R23   # Revit 2023
   dotnet build -c Release.R24   # Revit 2024
   dotnet build -c Release.R25   # Revit 2025
   dotnet build -c Release.R26   # Revit 2026
   ```
   
   編譯成功後，DLL 檔案會產生在 `bin\Release` 資料夾中。

3. **複製檔案到 Revit Addins 資料夾**
   ```powershell
   # 開啟 Revit Addins 資料夾（將 2022 改為您的版本）
   explorer %APPDATA%\Autodesk\Revit\Addins\2022
   
   # 或使用指令複製
   Copy-Item "bin\Release.R{YY}\RevitMCP.dll" "%APPDATA%\Autodesk\Revit\Addins\2022\" -Force
   Copy-Item "RevitMCP.addin" "%APPDATA%\Autodesk\Revit\Addins\2022\" -Force
   ```
   
   >  **版本對照**：Revit 2022 → `Addins\2022` | Revit 2023 → `Addins\2023` | Revit 2024 → `Addins\2024` | Revit 2025 → `Addins\2025` | Revit 2026 → `Addins\2026`

4. **重新啟動 Revit**

### 步驟 2：安裝 MCP Server（AI 和 Revit 的「翻譯官」）

**簡單說：我們需要安裝一些軟體工具，讓 AI 能和 Revit 溝通。**

#### 前置準備：檢查是否已安裝 Node.js

MCP Server 需要 Node.js 才能執行。先檢查您是否已安裝：

1. **打開命令提示字元**
   - 按 `Win + R`
   - 輸入 `cmd`，按 Enter

2. **檢查 Node.js**
   - 在命令提示字元輸入：`node --version`
   - 如果看到版本號（例如 v20.0.0），表示已安裝，**跳過下載步驟**
   - 如果看到「找不到命令」，表示未安裝，請按以下步驟下載

3. **下載並安裝 Node.js**（如果需要）
   - 打開瀏覽器，訪問 https://nodejs.org
   - 點擊左邊的「LTS」按鈕（推薦版本）
   - 下載 Windows 安裝程式（`.msi` 檔案）
   - 執行下載的安裝程式，一直點「Next」直到完成
   - 重新啟動電腦

#### 安裝步驟

1. **打開命令提示字元**
   - 按 `Win + R`
   - 輸入 `cmd`，按 Enter

2. **進入 MCP Server 資料夾**
   - 複製貼上以下指令，按 Enter（**注意：把路徑中的使用者名稱改成您電腦的帳號，版本號保持不變或根據需要修改**）：
     ```
     cd C:\Users\您的使用者名稱\Desktop\MCP\REVIT_MCP_study\MCP-Server
     ```
   - 提示：「您的使用者名稱」是您 Windows 登入時用的帳號名稱
   
   >  **路徑可能不同？**
   > - 如果您把專案資料夾放在不同位置（例如 C:\MCP），請自行調整上面的路徑
   > - 要找到專案資料夾：用滑鼠右鍵點擊 MCP-Server 資料夾 → 內容 → 位置，複製該路徑即可

3. **安裝軟體相依套件**
   - 在命令提示字元輸入：
     ```
     npm install
     ```
   - 會自動下載並安裝所需的軟體
   - 等待完成（可能需要 1-5 分鐘）
   - 完成時應該看到「added XXX packages」

4. **製作程式（轉換成可執行的檔案）**
   - 輸入以下指令：
     ```
     npm run build
     ```
   - 等待完成
   - 完成時應該看到一個 `build/` 資料夾被建立

**恭喜！您已經完成安裝了。** 現在可以進行下一步的設定。

### 步驟 3：設定 AI 平台

請參考下方的 **[多方案 AI Agent 設定](#-多方案-ai-agent-設定)** 章節。

---

##  啟動方式

### 1️⃣ 啟動 Revit 並開啟 MCP 服務

1. 開啟 Revit 2022
2. 載入或建立專案
3. 在「MCP Tools」面板點擊「**MCP 服務 (開/關)**」按鈕
4. 確認看到「WebSocket 伺服器已啟動，監聽: localhost:8964」

>  **關於埠號 (Port) 的說明**：
> - `8964` 是 MCP Server 預設的通訊埠號
> - 埠號是一個任意號碼，有可能被其他程式佔用
> - **常見問題：Port 8964 被 System (PID: 4) 佔用**
>   - 原因：Revit 異常關閉後，HTTP.sys 的 Request Queue 殘留
>   - 修復：在**系統管理員** PowerShell 中執行 `net stop http /y; net start http`
>   - 或執行：`powershell -ExecutionPolicy Bypass -File scripts\release-port.ps1`
>   - 若 HTTP 服務卡在 STOP_PENDING，需重新開機
> - 如果是被其他程式佔用（非 PID 4），可手動調整埠號：
>   1. 開啟本專案的設定檔 `MCP-Server/src/index.ts`
>   2. 找到 `PORT = 8964` 的這一行
>   3. 改成其他未被使用的埠號，例如 `8766` 或 `9000`
>   4. 重新編譯：`npm run build`
>   5. 所有使用此 MCP Server 的 AI 應用程式也要更新埠號設定（改為同樣的新埠號）

### 2️⃣ 透過 AI 平台連線

依您選擇的 AI 平台，參考下方的設定說明。

---

##  多方案 AI Agent 設定

### 核心概念：MCP Clients 與 MCP Server

在開始設定之前，需要理解本架構的核心概念：

#### 什麼是 MCP Client？

**MCP Client（客戶端）** 是指能夠理解並使用 MCP 工具的 AI 應用程式。簡單來說，就是：
- Claude Desktop
- Gemini CLI
- VS Code Copilot
- Google Antigravity

這些應用程式內部內建了「MCP 客戶端」功能，讓它們可以讀取和調用 MCP Server 提供的工具。

#### 什麼是 MCP Server？

**MCP Server** 是本專案中的 Node.js 應用程式（`MCP-Server/build/index.js`），它：
- 定義了 Revit 操作工具（create_wall、query_elements 等）
- 透過 WebSocket 與 Revit Add-in 通訊
- 將 AI 指令轉換為 Revit API 調用

---

### 4+1 方案架構說明

本專案提供了 **5 種使用方案**，分為兩大類：

#### 外部調用方案（4 種）

這些方案都遵循相同的架構：

```
┌─────────────────┐
│   AI 應用程式   │  (Claude Desktop / Gemini CLI / VS Code / Antigravity)
│  (MCP Client)   │
└────────┬────────┘
         │ 1. 讀取 MCP Server 地址
         │
┌────────▼────────┐
│   MCP Server    │  (Node.js - 本專案提供)
│  (Revit Tools)  │
└────────┬────────┘
         │ 2. WebSocket 連接
         │
┌────────▼────────┐
│  Revit Add-in   │  (C# - RevitMCP.dll)
│  (WebSocket)    │
└────────┬────────┘
         │ 3. Revit API 調用
         │
┌────────▼────────┐
│  Revit 應用程式  │
└─────────────────┘
```

Example for Revit 2024:

```text
MCP/bin/Release.R24/RevitMCP.dll
```

### 3. Deploy the Add-in

Recommended:

```powershell
.\scripts\install-addon.ps1
```

For manual deployment, place the `.addin` file and DLL under the matching Revit Addins directory, and keep the relative assembly path in `RevitMCP.addin`:

```xml
<Assembly>RevitMCP\RevitMCP.dll</Assembly>
```

Do not create version-specific `.addin` files, and do not hardcode absolute DLL paths.

## AI Client Configuration

Project-level `.mcp.json`:

```json
{
  "mcpServers": {
    "revit-mcp": {
      "type": "stdio",
      "command": "node",
      "args": ["./MCP-Server/build/index.js"],
      "env": {}
    }
  }
}
```

VS Code config in `.vscode/mcp.json`:

```json
{
  "servers": {
    "revit-mcp": {
      "type": "stdio",
      "command": "node",
      "args": ["${workspaceFolder}/MCP-Server/build/index.js"],
      "env": {}
    }
  }
}
```

Other AI clients use the same concept: launch `MCP-Server/build/index.js` with `node`.

Config template per client:

| AI Client | Config location | Template |
|---|---|---|
| Claude Code | project root `.mcp.json` | built in, works out of the box |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` | `MCP-Server/claude_desktop_config.json` |
| Gemini CLI | `~/.gemini/settings.json` | `MCP-Server/gemini_mcp_config.json` |
| VS Code Copilot | `.vscode/mcp.json` | built in |
| Antigravity | UI settings | `Antigravity_MCP_Complete_Guide.md` |

Replace `<YOUR_PROJECT_PATH>` in the templates with the actual project path on your machine.

### Switching Between AI Clients

The Revit-side WebSocket service accepts only one MCP connection at a time: a newly connected MCP server replaces the previous connection. Multiple AI clients are therefore used by switching, not concurrently:

1. Close the current AI client (or disable its MCP server).
2. Start the other AI client; once its MCP server connects to `localhost:8964`, it takes over.
3. If the connection misbehaves, restart the MCP service from the Revit ribbon to reset it.

## Startup Flow

1. Start Revit.
2. Open or create a Revit project.
3. Enable the MCP service from the Revit ribbon.
4. Confirm the Revit add-in is listening on `localhost:8964`.
5. Start or restart the AI client so it loads the MCP server.
6. Call Revit MCP tools from the AI client.

If `localhost:8964` is unreachable, Revit may not be running, the MCP service may be off, the port may be occupied, or the AI client and Revit add-in may be using different port settings.

## Project Structure

```text
REVIT_MCP/
  MCP/                         Revit Add-in (C#)
    Application.cs             Revit add-in entry point
    RevitMCP.csproj            Single multi-version project
    RevitMCP.addin             Single add-in manifest
    Core/
      SocketService.cs         Revit-side WebSocket server
      ExternalEventManager.cs  UI-thread execution bridge
      RevitCompatibility.cs    Revit 2022-2026 compatibility helpers
      CommandExecutor.cs       Main command dispatcher
      Commands/*.cs            Command modules
  MCP-Server/                  MCP Server (Node.js / TypeScript)
    src/index.ts               stdio MCP server entry
    src/socket.ts              WebSocket client to Revit
    src/tools/*.ts             MCP tool definitions
  domain/                      Shared BIM SOPs; do not convert to English-only
  .claude/                     AI commands and skills
  docs/                        Human-facing docs and public knowledge site
  scripts/                     Setup, deployment, QA/QC scripts
  log/                         Append-only session and commit logs
```

## AI Docs and Human Docs

| Type | Location | Rule |
|---|---|---|
| AI-only | `CLAUDE.md`, `.claude/commands/`, `.claude/skills/` | English-first to avoid mojibake |
| Human-facing | `README.md`, `README.zh-TW.md`, `docs/`, `scripts/README.md` | Match the reader's language |
| Shared | `domain/*.md`, `log/README.md` | Domain files must remain Chinese-readable and must not become English-only |
| Historical | `docs/_archive/**`, old logs | Preserve by default |

See [docs/DOCUMENT_AUDIENCE_INVENTORY.md](./docs/DOCUMENT_AUDIENCE_INVENTORY.md).

## Domain, Skill, and Tool Responsibilities

- `domain/*.md`: BIM SOPs, regulatory logic, and calculation methods. Shared by humans and AI.
- `.claude/skills/*/SKILL.md`: AI workflow orchestration.
- `MCP-Server/src/tools/*.ts`: MCP tool definitions and input schemas.
- `MCP/Core/Commands/*.cs`: Revit API implementation.

If a Domain file and a Skill disagree on method, the Domain file wins.

### MCP Server 在各方案中的角色

After documentation, tool, Domain, Skill, build, or deployment changes, run:

```
MCP Server 的責任：
1. 定義 Revit 工具 (create_wall、query_elements 等)
2. 接收 AI 應用程式的工具調用請求
3. 透過 WebSocket 將請求轉發給 Revit Add-in
4. 返回執行結果給 AI 應用程式
```

Before deployment, run a full check:

---

### 方案選擇建議

| 場景 | 推薦方案 | 原因 |
|------|---------|------|
| 日常使用，最簡單 | Claude Desktop | 無需額外配置，直接用現成應用 |
| 想在 Revit 內對話 | 內嵌 Chat（Gemini API）| 最流暢的使用體驗 |
| 偏好 Google | Gemini CLI | 用自己的 Google 帳戶 |
| 程式開發者 | VS Code Copilot | 在開發環境中無縫使用 |
| 進階 AI 開發 | Antigravity | 多視窗與 Agent 同步執行 |

---

### 方案 1️⃣：Gemini CLI

Gemini CLI 是 Google 的命令列 AI 工具，可以在終端機直接與 Gemini 2.5 Flash 對話。

#### 步驟 1：安裝 Gemini CLI（適合初學者）

**什麼是 Gemini CLI？** 它是一個可以在 Windows 命令提示字元或 PowerShell 執行的工具。

1. **下載 Node.js**（如果還沒安裝）
   - 前往 https://nodejs.org
   - 點擊「LTS」版本下載
   - 執行下載的安裝程式，一直點「Next」到完成
   - 重新啟動電腦

2. **開啟 PowerShell**
   - 按 `Win + X`
   - 選擇「Windows PowerShell (系統管理員)」
   - 複製貼上下方指令，按 Enter：
   ```powershell
   npm install -g @google/gemini-cli
   ```
   - 等待安裝完成（會看到綠色的勾勾）
   
   >  **如果遇到「已停用指令碼執行」錯誤**：
   > 先執行此指令允許腳本執行，然後再重試安裝：
   > ```powershell
   > Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   > ```

#### 步驟 2：設定 MCP Server 連線

> [!IMPORTANT]
> **Gemini CLI 使用 `settings.json` 設定 MCP，而非 `--config` 參數！**
> 
> 這與 Claude Desktop 和其他工具不同。Gemini CLI 會讀取使用者目錄下的 `~/.gemini/settings.json` 檔案。

**設定方式：編輯 `settings.json` 檔案**

1. **開啟設定檔位置**

   **Windows**：
   - 按 `Win + R`，輸入以下路徑，按 Enter：
     ```
     %USERPROFILE%\.gemini
     ```
   - 如果資料夾不存在，手動建立 `.gemini` 資料夾
   
   **macOS / Linux**：
   ```bash
   cd ~/.gemini
   # 如果不存在，先建立
   mkdir -p ~/.gemini
   ```
   
   - 找到 `settings.json` 檔案並用記事本開啟（如果不存在就新建一個）

2. **加入 MCP Server 設定**
   
   將檔案內容修改為（如果檔案已有其他內容，請保留並加入 `mcpServers` 區塊）：
   ```json
   {
     "mcpServers": {
       "revit-mcp": {
         "command": "node",
         "args": [
           "C:\\您的路徑\\REVIT MCP\\MCP-Server\\build\\index.js"
         ],
         "env": {
           "REVIT_VERSION": "2022"
         }
       }
     }
   }
   ```
   
   >  **請將路徑改為您實際的專案位置！**
   > 
   > 例如：`C:\\Users\\YourName\\Desktop\\REVIT MCP\\MCP-Server\\build\\index.js`

3. **儲存檔案並重新啟動 Gemini CLI**

#### 步驟 3：啟動並測試

1. **先啟動 Revit**
   - 開啟 Revit 2022
   - 在「MCP Tools」面板點擊「**MCP 服務 (開/關)**」按鈕
   - 看到「WebSocket 伺服器已啟動」就成功了

2. **開啟 Gemini CLI**
   - 開啟 PowerShell
   - 執行：
   ```powershell
   gemini
   ```

3. **確認 MCP 已連接**
   ```
   /mcp list
   ```
   - 應該會看到 `revit-mcp` 伺服器

4. **測試對話**
   ```
   > 請列出 Revit 專案中的所有樓層
   > 請幫我建立一面 5 米長的牆
   ```

---

### 方案 2️⃣：VS Code (GitHub Copilot)

在程式碼編輯器 VS Code 中直接與 AI 對話並控制 Revit。

#### 步驟 1：安裝 VS Code

1. 前往 https://code.visualstudio.com
2. 點擊藍色的「Download」按鈕
3. 執行下載的安裝程式
4. 一直點「Next」直到完成，重新啟動電腦

#### 步驟 2.5：使用本專案的已配置版本（推薦！）

**好消息：我們已經為您準備好了設定檔！**

1. **開啟本專案資料夾**
   - 用滑鼠右鍵點擊 `c:\Users\User\Desktop\REVIT MCP` 資料夾
   - 選擇「**以 VS Code 開啟**」
   - 或者在 VS Code 中點擊 File → Open Folder，選擇此資料夾

2. **設定檔已在 `.vscode/mcp.json` 中**
   - 檔案已經準備好，您無需修改任何東西
   - 系統會自動載入這個設定

#### 步驟 3：啟動（初學者版）

1. **確認 Revit MCP 服務已啟動**
   - 開啟 Revit 2022
   - 點擊「MCP 服務 (開/關)」

2. **在 VS Code 中開啟 Copilot Chat**
   - 按快捷鍵 `Ctrl + Shift + I`
   - 或點擊左邊 Copilot 圖示
   
3. **開始提問**
   - 在聊天框輸入：「請幫我在 Revit 中查詢所有的柱子」
   - AI 會自動使用 Revit 工具執行您的指令

---

### 方案 3️⃣：Claude Desktop（推薦初學者！）

Anthropic 官方桌面應用程式，這是**最簡單的方式**。

#### 步驟 1：安裝 Claude Desktop

1. 前往 https://claude.ai/download
2. 點擊「Download for Windows」
3. 執行下載的 `.exe` 安裝程式
4. 安裝完成後重新啟動電腦

#### 步驟 2.5：在 Claude Desktop 中直接添加 MCP（最簡單！）

**無需複製檔案！直接在應用程式中設定：**

1. **打開 Claude Desktop 應用程式**

2. **點擊右上角的「 設定」**
   - 或在左下角找到「Settings」

3. **找到「MCP Servers」選項**

4. **點擊「Add Server」或「新增伺服器」**

5. **填入以下資訊**
   - **名稱**：`revit-mcp`
   - **命令**：`node`
   - **參數**：`C:\Users\User\Desktop\REVIT MCP\MCP-Server\build\index.js`
   - **環境變數**：
     ```
     REVIT_VERSION: 2022
     ```
     
   >  **版本不同？修改環境變數**：
   > - Revit 2022：改為 `REVIT_VERSION: 2022`
   > - Revit 2023：改為 `REVIT_VERSION: 2023`
   > - Revit 2024：改為 `REVIT_VERSION: 2024`

6. **點擊「Save」或「儲存」** - 完成！

#### 步驟 3：啟動（初學者版）

1. **啟動 Revit**
   - 開啟 Revit 2022
   - 點擊「MCP 服務 (開/關)」

2. **使用 Claude Desktop**
   - Claude 應用程式會自動連接 Revit
   - 直接在聊天框輸入對話，例如：
   ```
   請幫我在 Revit 中建立一個 3m × 5m 的樓板
   ```

3. **Claude 會自動為您執行操作！**

---

### 方案 4️⃣：Google Antigravity

[Google Antigravity](https://antigravity.google/) 是 Google 推出的「以代理程式為主」的開發平台，將 IDE 帶入 AI Agent 時代。

**主要特色：**
- 以開放原始碼的 VS Code 為基礎，但大幅改變使用者體驗
- 介面分成兩個主要視窗：**Editor**（編輯器）和 **Agent Manager**（代理程式管理員）
- 可同時派遣**多個代理程式**處理不同工作（非線性、非同步執行）
- 內建 **Antigravity Browser**（瀏覽器子代理程式）可執行網頁測試與錄影
- 代理程式會產生「構件」（Artifacts）如工作計畫、程式碼差異、螢幕截圖等
- 目前僅適用於**個人 Gmail 帳戶**的預先發布版（免費使用）

#### 步驟 1：安裝 Google Antigravity

1. **前往下載頁面**
   - 開啟瀏覽器，前往 https://antigravity.google/download
   - 點選適用於您作業系統的版本（Windows / Mac / Linux）
   - 執行安裝程式，完成安裝

2. **啟動 Antigravity 並完成設定**
   - 開啟 Antigravity 應用程式
   - 選擇設定流程（可從現有 VS Code 或 Cursor 設定匯入，或重新開始）
   - 選擇編輯器主題（深色/淺色）
   - 選擇代理程式使用模式：
     - **代理程式導向開發**：Agent 自主執行，較少人為介入
     - **代理程式輔助開發**（推薦）：Agent 做出決策後返回給使用者核准
     - **以審查為導向的開發**：Agent 一律要求審查
     - **自訂設定**：完全自訂控制

3. **使用 Google 帳戶登入**
   - 點選「Sign in to Google」
   - 使用個人 Gmail 帳戶登入
   - 系統會為此建立新的 Chrome 設定檔

#### 步驟 2：設定瀏覽器代理程式（Antigravity Browser）

Antigravity 的一大特色是內建瀏覽器子代理程式，可讓 AI 直接操作網頁。

1. **在 Agent Manager 中開始對話**
   - 選取 `Playground` 或任意工作區
   - 輸入需要瀏覽器的指令（例如：「前往 antigravity.google」）

2. **安裝 Chrome 擴充功能**
   - Agent 會提示需要設定瀏覽器代理程式
   - 點選 `Setup`，按照指示安裝 Chrome 擴充功能
   - 安裝完成後，Agent 即可控制瀏覽器執行工作

#### 步驟 3：設定 MCP Server 連接 Revit

>  **注意**：Antigravity 執行在本機，MCP Server 也需要在同一台 Windows 電腦上運行（因為需要連接 Revit）。

1. **開啟工作區**
   - 在 Agent Manager 中點選 `Workspaces`
   - 選擇本專案的 `MCP-Server` 資料夾作為工作區

2. **透過對話啟動 MCP 連接**
   - 在 Agent Manager 中開始新對話
   - 告訴 Agent：「請執行 node build/index.js 啟動 MCP Server」
   - 或直接在編輯器的終端機中執行：
     ```
     cd C:\Users\您的使用者名稱\Desktop\REVIT MCP\MCP-Server
     node build/index.js
     ```

3. **開始與 Revit 互動**
   - 確認 Revit 已啟動且 MCP 服務已開啟
   - 在 Agent Manager 中輸入指令，例如：
     ```
     請幫我在 Revit 中建立一面 5 米長的牆
     ```

#### 🎯 Antigravity 的獨特優勢

| 功能 | 說明 |
|------|------|
| **多代理程式並行** | 可同時派遣 5 個以上的代理程式處理不同工作 |
| **構件（Artifacts）** | 代理程式會產生工作計畫、實作計畫、程式碼差異、螢幕截圖、瀏覽器錄影等 |
| **瀏覽器整合** | 內建 Chrome 瀏覽器子代理程式，可點選、捲動、輸入、讀取控制台等 |
| **收件匣（Inbox）** | 集中追蹤所有對話與工作狀態 |
| **Google 文件風格註解** | 可對構件和程式碼差異加上註解，Agent 會根據意見回饋進行修改 |

> 📚 **更多資訊**：請參閱 [Google Antigravity 官方教學](https://codelabs.developers.google.com/getting-started-google-antigravity?hl=zh-tw)

---

## 🛠️ 可用的 MCP 工具

### 基礎建模工具

| 工具名稱 | 說明 |
|---------|------|
| `create_wall` | 建立牆 |
| `create_floor` | 建立樓板 |
| `create_door` | 建立門 |
| `create_window` | 建立窗 |
| `create_column` | 建立柱子 |
| `create_dimension` | 建立尺寸標註 |

### 資訊查詢工具

| 工具名稱 | 說明 |
|---------|------|
| `get_project_info` | 取得專案資訊 |
| `query_elements` | 查詢元素（支援篩選條件） |
| `get_element_info` | 取得元素詳細資訊 |
| `get_all_levels` | 取得所有樓層 |
| `get_all_grids` | 取得所有網格線（含座標，可計算交會點） |
| `get_column_types` | 取得柱類型清單（含尺寸資訊） |
| `get_furniture_types` | 取得家具類型清單 |
| `get_room_info` | 取得房間詳細資訊（中心點、邊界範圍） |
| `get_rooms_by_level` | 取得樓層所有房間清單（含面積統計） |
| `get_wall_info` | 取得牆的詳細資訊 |
| `query_walls_by_location` | 依位置查詢牆 |

### 視圖與導航工具

| 工具名稱 | 說明 |
|---------|------|
| `get_all_views` | 取得所有視圖清單 |
| `get_active_view` | 取得目前使用中的視圖 |
| `set_active_view` | 切換使用中的視圖 |
| `select_element` | 選取元素 |
| `zoom_to_element` | 縮放至指定元素 |
| `measure_distance` | 量測兩點距離 |

### 元素操作工具

| 工具名稱 | 說明 |
|---------|------|
| `modify_element_parameter` | 修改元素參數 |
| `delete_element` | 刪除元素 |
| `place_furniture` | 放置家具 |

### 視覺化工具

| 工具名稱 | 說明 |
|---------|------|
| `override_element_graphics` | 覆寫元素圖形（顏色、線型等） |
| `clear_element_override` | 清除元素的圖形覆寫 |
| `unjoin_wall_joins` | 取消牆接合（用於上色前） |
| `rejoin_wall_joins` | 恢復牆接合（上色後還原） |


---

##  進階功能：Revit Add-in 中整合 AI API（Gemini 2.5 Flash）

### 功能說明

讓 Revit 使用者直接在 Add-in 中開啟一個**對話視窗**，與 Gemini 2.5 Flash AI 交互式對話並控制 Revit。無需額外啟動外部工具。

```
┌─────────────────────────────────────┐
│        Revit 視窗                   │
├─────────────────────────────────────┤
│  MCP Tools                          │
│  ┌──────────────────────────────┐  │
│  │ MCP 服務(開/關)              │  │
│  ├──────────────────────────────┤  │
│  │ MCP 設定                     │  │
│  ├──────────────────────────────┤  │
│  │ 🆕 AI Chat 助手（新功能）    │  │
│  └──────────────────────────────┘  │
│                                     │
│  ┌─────────────────────────────────┐│
│  │ AI Chat 視窗 (WPF 對話框)       ││
│  ├─────────────────────────────────┤│
│  │ 您：請幫我建立一個 3mx5m 的樓板 ││
│  │ AI: 我已建立樓板，ID: 123456   ││
│  │                                 ││
│  │ [輸入框] [傳送按鈕]             ││
│  └─────────────────────────────────┘│
└─────────────────────────────────────┘
```

QA/QC checks:

- forbidden legacy files and paths
- required file structure
- README / CLAUDE / docs count alignment
- Domain table forward and reverse coverage
- local Markdown link rot
- Domain frontmatter
- document audience classification
- mojibake risk in canonical docs

## Troubleshooting

### AI cannot find Revit tools

Check:

1. `npm run build` has been run in `MCP-Server`.
2. The AI client's MCP config points to the correct `MCP-Server/build/index.js`.
3. The AI client has been restarted or has reloaded MCP servers.

### MCP Server cannot connect to Revit

Check:

1. Revit is running.
2. The MCP service is enabled in the Revit ribbon.
3. `localhost:8964` is not occupied.
4. If HTTP.sys / PID 4 is holding the port, try:

namespace RevitMCP.Core
{
    /// <summary>
    /// Gemini 2.5 Flash API 整合服務
    /// </summary>
    public class GeminiChatService
    {
        private readonly string _apiKey;
        private readonly string _apiUrl = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent";
        private readonly HttpClient _httpClient;

        public GeminiChatService(string apiKey)
        {
            _apiKey = apiKey ?? throw new ArgumentNullException(nameof(apiKey));
            _httpClient = new HttpClient();
        }

        /// <summary>
        /// 與 Gemini AI 交互式對話
        /// </summary>
        public async Task<string> ChatAsync(string userMessage, string context = "")
        {
            try
            {
                // 構建請求
                var requestBody = new
                {
                    contents = new[]
                    {
                        new
                        {
                            parts = new[]
                            {
                                new
                                {
                                    text = $"{context}\n\n用戶問題: {userMessage}"
                                }
                            }
                        }
                    },
                    generationConfig = new
                    {
                        temperature = 0.7,
                        maxOutputTokens = 1024
                    }
                };

                var jsonContent = JsonConvert.SerializeObject(requestBody);
                var content = new StringContent(jsonContent, Encoding.UTF8, "application/json");

                // 發送請求到 Gemini API
                var response = await _httpClient.PostAsync(
                    $"{_apiUrl}?key={_apiKey}",
                    content
                );

                if (!response.IsSuccessStatusCode)
                {
                    throw new Exception($"Gemini API 錯誤: {response.StatusCode}");
                }

                // 解析回應
                var responseContent = await response.Content.ReadAsStringAsync();
                dynamic result = JsonConvert.DeserializeObject(responseContent);
                
                string aiResponse = result.candidates[0].content.parts[0].text;
                return aiResponse;
            }
            catch (Exception ex)
            {
                return $"AI 服務錯誤: {ex.Message}";
            }
        }
    }
}
```

### Revit does not show the MCP Tools panel

Confirm the `.addin` file and DLL were deployed under the matching `%APPDATA%\Autodesk\Revit\Addins\{version}` directory, then restart Revit.

## Important Rules

- Keep one `MCP/RevitMCP.csproj`.
- Keep one `MCP/RevitMCP.addin`.
- Do not create version-specific `.csproj` or `.addin` files.
- Do not create nested `MCP/MCP/` directories.
- Do not change `.addin` `<Assembly>` to an absolute path.
- Do not convert Domain files to English-only.
- Do not bypass the MCP server with hand-written WebSocket JSON.
- For live Revit view, level, selection, or document state, AI must query live state in the current turn.

## Document Navigation

| Document | Purpose |
|---|---|
| [CLAUDE.md](./CLAUDE.md) | Main AI agent constitution and project map |
| [AGENTS.md](./AGENTS.md) | Redirect to `CLAUDE.md` |
| [GEMINI.md](./GEMINI.md) | Redirect to `CLAUDE.md` |
| [README.zh-TW.md](./README.zh-TW.md) | Traditional Chinese README |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | Contribution guide |
| [CHANGELOG.md](./CHANGELOG.md) | Release history |
| [domain/README.md](./domain/README.md) | Domain SOP catalog |
| [domain/lessons.md](./domain/lessons.md) | Project lessons |
| [.claude/skills/](./.claude/skills/) | AI skills |
| [.claude/commands/](./.claude/commands/) | AI slash commands |
| [scripts/README.md](./scripts/README.md) | Script documentation |
| [docs/DOCUMENT_AUDIENCE_INVENTORY.md](./docs/DOCUMENT_AUDIENCE_INVENTORY.md) | Document audience inventory |
| [docs/DOCS_STRUCTURE.md](./docs/DOCS_STRUCTURE.md) | Docs directory guide |
| [log/README.md](./log/README.md) | Log append rules |

                return Result.Succeeded;
            }
            catch (Exception ex)
            {
                TaskDialog.Show("錯誤", $"開啟 AI Chat 失敗: {ex.Message}");
                return Result.Failed;
            }
        }
    }
}
```

#### 步驟 4：建立 WPF 視窗 UI

在 `MCP/` 中建立 `ChatWindow.xaml`：

```xml
<Window x:Class="RevitMCP.ChatWindow"
        xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Revit AI Chat 助手"
        Height="600"
        Width="500"
        Background="#F5F5F5">
    <Grid>
        <Grid.RowDefinitions>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- 聊天歷史 -->
        <ListBox x:Name="ChatHistory"
                 Grid.Row="0"
                 Margin="10"
                 Background="White"
                 BorderThickness="1"
                 BorderBrush="#DDD">
            <ListBox.ItemTemplate>
                <DataTemplate>
                    <Border Margin="5" Padding="10" CornerRadius="5">
                        <TextBlock Text="{Binding}"
                                   TextWrapping="Wrap"
                                   Foreground="#333"/>
                    </Border>
                </DataTemplate>
            </ListBox.ItemTemplate>
        </ListBox>

        <!-- 輸入區域 -->
        <Grid Grid.Row="1" Margin="10" Background="White" Height="80">
            <Grid.ColumnDefinitions>
                <ColumnDefinition Width="*"/>
                <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>

            <TextBox x:Name="InputBox"
                     Grid.Column="0"
                     VerticalAlignment="Top"
                     Padding="10"
                     TextWrapping="Wrap"
                     AcceptsReturn="True"
                     PlaceholderText="輸入您的問題..."/>

            <Button x:Name="SendButton"
                    Grid.Column="1"
                    Margin="5"
                    Padding="15,10"
                    Background="#007ACC"
                    Foreground="White"
                    Content="傳送"
                    Click="SendButton_Click"/>
        </Grid>
    </Grid>
</Window>
```

#### 步驟 5：後端代碼 (ChatWindow.xaml.cs)

```csharp
using System.Collections.ObjectModel;
using System.Windows;
using Autodesk.Revit.UI;
using RevitMCP.Core;

namespace RevitMCP
{
    public partial class ChatWindow : Window
    {
        private readonly GeminiChatService _chatService;
        private readonly UIApplication _uiApp;
        private readonly ObservableCollection<string> _messages;

        public ChatWindow(GeminiChatService chatService, UIApplication uiApp)
        {
            InitializeComponent();
            _chatService = chatService;
            _uiApp = uiApp;
            _messages = new ObservableCollection<string>();
            ChatHistory.ItemsSource = _messages;

            _messages.Add(" AI 助手已就緒。請輸入您的問題來控制 Revit。");
            _messages.Add(" 例如：請建立一個 5 米長的牆");
        }

        private async void SendButton_Click(object sender, RoutedEventArgs e)
        {
            string userInput = InputBox.Text.Trim();
            if (string.IsNullOrEmpty(userInput)) return;

            // 顯示用戶訊息
            _messages.Add($"👤 您: {userInput}");
            InputBox.Clear();

            // 獲取 AI 回應
            SendButton.IsEnabled = false;
            SendButton.Content = "處理中...";

            try
            {
                string context = $"您是 Revit BIM 專家助手。可用的 Revit 命令包括: " +
                    "create_wall, create_floor, query_elements, get_project_info 等。" +
                    "請用中文簡潔回答，並說明您的操作。";

                string response = await _chatService.ChatAsync(userInput, context);
                _messages.Add($" AI: {response}");

                // 如果 AI 建議執行操作，可以在這裡添加自動執行邏輯
            }
            finally
            {
                SendButton.IsEnabled = true;
                SendButton.Content = "傳送";
            }
        }
    }
}
```

#### 步驟 6：在 Add-in 中註冊新按鈕

修改 `Application.cs` 中的 `OnStartup` 方法，加入 AI Chat 按鈕：

```csharp
public Result OnStartup(UIControlledApplication application)
{
    try
    {
        RibbonPanel panel = application.CreateRibbonPanel("MCP Tools");
        
        string assemblyPath = Assembly.GetExecutingAssembly().Location;

        // 現有按鈕...
        
        // 🆕 新增 AI Chat 按鈕
        PushButtonData chatButtonData = new PushButtonData(
            "MCPChat",
            "AI Chat\n助手",
            assemblyPath,
            "RevitMCP.Commands.ChatCommand");
        chatButtonData.ToolTip = "開啟 AI 對話助手，與 Gemini 2.5 Flash 交互式控制 Revit";
        PushButton chatButton = panel.AddItem(chatButtonData) as PushButton;

        return Result.Succeeded;
    }
    catch (Exception ex)
    {
        TaskDialog.Show("錯誤", "載入 MCP Tools 失敗: " + ex.Message);
        return Result.Failed;
    }
}
```

#### 步驟 7：設定環境變數（給最終使用者）

1. **按 `Win + Pause` 或 `Win + X` → 系統**

2. **點擊「進階系統設定」**

3. **點擊「環境變數」按鈕**

4. **在「系統變數」中點擊「新增」**

5. **填入以下資訊**
   - 變數名稱：`GEMINI_API_KEY`
   - 變數值：`您從步驟1複製的 API Key`

6. **點擊「確定」並重新啟動 Revit**

### 步驟 8：編譯並測試

1. **編譯 C# 專案**
   ```powershell
   cd MCP
   dotnet build -c Release.R22
   ```

2. **複製 DLL 到 Revit Add-in 目錄**
   ```powershell
   $target = "$env:APPDATA\Autodesk\Revit\Addins\2022"
   Copy-Item "bin\Release.R22\RevitMCP.dll" $target
   ```

3. **重新啟動 Revit**

4. **點擊「AI Chat 助手」按鈕**
   - 應該會看到聊天視窗
   - 開始與 AI 對話！

### 實際使用示例

```
👤 用戶：我想在 Level 2 建立 3 個方形樓板，尺寸都是 5m × 5m

 AI：我可以幫您建立 3 個方形樓板。我會在以下位置建立它們：
- 樓板1：(0, 0) 到 (5, 5)
- 樓板2：(6, 0) 到 (11, 5)  
- 樓板3：(12, 0) 到 (17, 5)

現在建立中...完成！已建立 3 個樓板，ID 分別為 123456, 123457, 123458

👤 用戶：請把樓板1 的高度改成 4m

 AI：我已將樓板1 的高度改為 4m。修改完成！
```

---

## 🔒 安全注意事項

 **重要安全提醒**：

1. **Port 管理** - MCP Server 預設監聽 `localhost:8964`，僅限本機存取
2. **防火牆** - 不建議對外開放連接埠
3. **程式碼審查** - 執行前請確認程式碼來源可信
4. **備份** - 操作前請備份 Revit 專案
5. **API Key 保管** - 絕不要將 API Key 提交到 GitHub，使用環境變數管理

## 📝 常見問題

### Q: Revit 沒有顯示 MCP Tools 面板？
A: 確認 `RevitMCP.addin` 已正確放置在 Add-in 目錄，並重新啟動 Revit。

### Q: MCP Server 無法連線到 Revit？
A:
1. 確認 Revit 中已點擊「MCP 服務 (開/關)」啟動服務
2. 確認 Port 8964 未被其他程式佔用
3. 若顯示「Port 8964 被 System (PID: 4) 佔用」，執行 `scripts\release-port.ps1`（需系統管理員）
4. 檢查防火牆設定

### Q: AI 說找不到 Revit 工具？
A: 確認 MCP Server 設定檔路徑正確，並重新啟動 AI 應用程式。

---

## 📖 附錄：技術補充說明

>  以下內容為進階技術說明，一般使用者可略過此章節。

### A. 什麼是 WebSocket？

本專案使用 **WebSocket** 作為 MCP Server 與 Revit Add-in 之間的通訊協議。

**WebSocket** 是一種網路通訊標準（非本專案自創名詞），具有以下特點：

| 特性 | 說明 |
|------|------|
| **雙向通訊** | 伺服器和客戶端可隨時互相傳送訊息 |
| **低延遲** | 建立連接後保持開啟，無需每次重新連接 |
| **即時性** | 適合需要快速回應的操作（如 Revit 即時控制） |

**簡單類比：**
- 傳統 HTTP = 每次打電話，講完就掛斷
- WebSocket = 保持通話中，雙方隨時可以說話

### B. 為什麼選擇 WebSocket？

本專案選擇 WebSocket 的理由：

1. **即時性需求** - Revit 操作需要立即回應
2. **持久連接** - 多個 AI 命令會持續發送，單一連接更有效率
3. **雙向通訊** - Revit 有時需要主動通知（如進度更新、錯誤訊息）
4. **跨語言支援** - Node.js 和 C# 都原生支援
5. **MCP 標準** - Model Context Protocol 官方即採用 WebSocket

### C. 其他通訊技術比較

如果您有興趣了解其他技術選項：

| 技術 | 延遲 | 雙向 | 易用性 | 適用場景 |
|------|------|------|--------|----------|
| **WebSocket**  | 低 |  | ⭐⭐⭐⭐ | 本專案選用 |
| HTTP REST | 高 |  | ⭐⭐⭐⭐⭐ | 簡單查詢 |
| gRPC | 最低 |  | ⭐⭐ | 高性能場景 |
| Named Pipes | 最低 |  | ⭐⭐ | 純本機通訊 |
| SignalR | 低 |  | ⭐⭐⭐⭐ | .NET 生態系 |

### D. 埠號 (Port) 補充說明

本專案預設使用 `8964` 埠號，這是一個任意選擇的數字。

**常見埠號範圍：**
- `0-1023`：系統保留埠（如 80=HTTP, 443=HTTPS）
- `1024-49151`：註冊埠（常見應用程式使用）
- `49152-65535`：動態/私有埠（可自由使用）

`8964` 屬於註冊埠範圍，通常不會與系統服務衝突，但仍可能被其他應用程式佔用。

---

## ❓ 常見問題與疑難排解

如果您在安裝過程中遇到問題，請參考以下解法：

### 1. 執行 .bat 批次檔時閃退或報錯
- **症狀**：點擊 `install-addon.bat` 視窗一閃即逝，或顯示 `The system cannot find the path`。
- **原因**：若您是透過 Git 在不同作業系統間同步（如 Mac 到 Windows），檔案的換行格式可能變成了 **LF**，但 Windows 批次檔需要 **CRLF**。
- **解法**：
  1. 放棄 `.bat`，改用 PowerShell 執行 `.ps1` 腳本。
  2. 或者使用 VS Code 將檔案右下角的換行格式切換回 `CRLF` 並存檔。

### 2. PowerShell 出現大量亂碼紅字
- **症狀**：執行 `.ps1` 時出現問號亂碼（如 `?誘 蠟幅??`），導致安裝失敗。
- **原因**：PowerShell 對於繁體中文環境的編碼支援問題。
- **解法**：
  1. 用「記事本」開啟 `install-addon.ps1` 檔。
  2. 選擇「另存新檔」，編碼改選 **「具有 BOM 的 UTF-8」(UTF-8 with BOM)**。
  3. 存檔後重新執行指令。

### 3. 顯示「找不到 DLL」
- **原因**：本專案目前未上傳預編譯的二進位檔案 (Release)。
- **解法**：請務必確認您已執行過 `dotnet build -c Release` 編譯指令（請參閱上方的安裝步驟）。

---

## 📄 授權

MIT License

## 🤝 貢獻

歡迎提交 Issue 和 Pull Request！

---

## 📚 文件導覽

| 文件 | 說明 |
|:-----|:----|
| **AI 規範** | |
| [CLAUDE.md](./CLAUDE.md) | **專案唯一規範文件**：架構、建構指令、部署規則、程式碼慣例 |
| [GEMINI.md](./GEMINI.md) | 重定向至 CLAUDE.md（供 Gemini CLI / Google AI 讀取） |
| [AGENTS.md](./AGENTS.md) | 重定向至 CLAUDE.md（供 OpenAI / Copilot 讀取） |
| [docs/ai-guard-rails-portable.md](./docs/ai-guard-rails-portable.md) | **Fork 維護者必讀**：可貼進你 fork 的 CLAUDE.md 的最小 Guard Rails snippet（AI Guard Rails + Tool Call Data Honesty + Domain Method Compliance 三段） |
| **專案文件** | |
| [CHANGELOG.md](./CHANGELOG.md) | 版本變更日誌（v1.0.0 ~ v1.5.1） |
| [CONTRIBUTING.md](./CONTRIBUTING.md) | 貢獻指南：如何提交工作流程與經驗規則 |
| [README.en.md](./README.en.md) | English version of this README |
| **domain/** | |
| [domain/README.md](./domain/README.md) | 領域知識目錄（AI 工作流程 SOP） |
| [domain/lessons.md](./domain/lessons.md) | 開發經驗與避坑規則（由 `/lessons` 指令維護） |
| **log/** | |
| [log/README.md](./log/README.md) | 事件日誌系統說明（Karpathy LLM Wiki pattern，跨 AI 自動維護） |
| **docs/** | |
| [docs/DOCS_STRUCTURE.md](./docs/DOCS_STRUCTURE.md) | 文件目錄結構說明 |
| [shuotao.github.io/REVIT_MCP_study](https://shuotao.github.io/REVIT_MCP_study/) | 公開知識站（10 頁 + 25 SVG，源碼於 `docs/BIM_MCP/`） |
| **scripts/** | |
| [scripts/README.md](./scripts/README.md) | 安裝腳本使用說明 |
| **Claude Code 自動化** | |
| [.claude/skills/](./\.claude/skills/) | Claude Code 技能（`/build-revit`、`/deploy-addon`） |
| [.claude/commands/](./\.claude/commands/) | 斜線指令定義（`/lessons`、`/domain`、`/review`） |

---

**Enjoy your AI-powered Revit development! **
