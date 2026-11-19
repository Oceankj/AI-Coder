# Work Log

第 2 棒（Pete）：後端核心。分支 `feat/backend-core`。
規格見 [docs/backend-spec.md](docs/backend-spec.md)。

## 問題總整理

新問題加在「未解決」；解決後移到「已解決」，並寫上怎麼解決的。

### 未解決

（目前沒有）

### 已解決

- **同一毫秒建立的 workspace / run 順序會亂掉**（2026-11-19，步驟 4）
  跑 pytest 時偶爾（約 30 次出現 1 次）`test_list_returns_summaries_in_creation_order` 失敗。原因：兩筆資料在同一毫秒建立，`createdAt` 完全相同，排序時順序變成隨機。這是**真的 bug**，不是測試的問題：前端的列表順序也會亂。
  解法：`FileStorage._now()` 保證時間戳一定比上一次大，時鐘沒前進時就往後推 1 毫秒。先寫了兩個用「凍結時鐘」的測試穩定重現問題，修好後拿掉測試裡原本用來閃避的 `time.sleep(0.01)`，整套測試連跑 100 次 0 失敗。

- **瀏覽器 console 有一個跟後端無關的 404**（2026-11-19，步驟 4）
  後端 log 裡沒有任何 404，查出來是前端的 Vite 伺服器沒有 `/favicon.ico`（`frontend/index.html` 也沒設定圖示），瀏覽器自動要圖示時就 404。MSW 模式也一樣。
  解法：瀏覽器檢查腳本忽略 favicon 的錯誤。**給 Ching**：前端要消掉這個錯誤，可以在 `index.html` 加一個 `<link rel="icon">`。

- **真的前端選到 workspace 後顯示「Could not load」**（2026-11-18 發現，2026-11-19 解決）
  原因是前端載入 workspace 時會呼叫 `GET /api/workspaces/{id}/runs`，步驟 3 時這個路由還不存在。
  解法：步驟 4 做好 run 路由後，用同一個瀏覽器腳本重新驗證，`rootPath` 正常顯示，9 項檢查全部通過。

- **Playwright 找不到瀏覽器**（2026-11-18，步驟 3）
  前端的 `@playwright/test` 要求的 Chromium 版本（1255）和電腦上快取的版本（1228）不同，啟動時報 `Executable doesn't exist`。
  解法：瀏覽器檢查改用電腦上已安裝的 Google Chrome（`chromium.launch({ channel: "chrome" })`），不用另外下載瀏覽器。之後如果要跑前端自己的 Playwright 測試，照 `frontend/README.md` 執行 `npx playwright install chromium` 即可。

- **拿掉 `models.py` 的 `GenerationRequest` 後，兩個模組 import 失敗**（2026-11-18，步驟 2）
  `orchestration/orchestrator.py` 和 `api/routes.py` 的骨架還在 import 它，但原本沒有任何測試會載入這兩個檔案，所以測試全過卻沒發現。
  解法：新增 `tests/test_imports.py`，自動 import `ai_coder/` 底下所有模組；並把兩個骨架改成不需要 `GenerationRequest`（run 的需求內容改從 `run.json` 讀）。這兩個檔案在步驟 3～4 會整個重寫。

- **Starlette 的測試工具要求改用 `httpx2`**（2026-11-18，步驟 1）
  FastAPI 0.165 / Starlette 1.10 搭配 `httpx` 時，pytest 會出現
  `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated`。
  解法：開發用套件改成 `httpx2>=2.16`，警告消失。

## 進度

| 步驟 | 內容 | 狀態 |
| --- | --- | --- |
| 1 | 專案設定、FastAPI 骨架、統一錯誤格式、CORS | ✅ 完成 |
| 2 | 儲存層：讀寫 workspace、run 的檔案 | ✅ 完成 |
| 3 | Workspace 的 3 個路由 | ✅ 完成 |
| 4 | Run 路由 + Orchestrator + 假 agent | ✅ 完成 |
| 5 | 事件、檔案、下載路由 | ✅ 完成 |
| 6 | 前端整體實測，補齊錯誤情境 | ✅ 完成 |
| 7 | 交接文件、更新其他文件 | ⬜ |

每一步都是：先寫測試 → 確認測試失敗 → 寫程式 → 測試通過 → 記錄在這裡。

## 決定事項

規劃時決定、文件原本沒寫清楚的地方。完整說明在 spec。

| # | 問題 | 決定 |
| --- | --- | --- |
| 1 | 前端怎麼連後端 | 開 CORS，允許 `http://127.0.0.1:5173` 和 `http://localhost:5173` |
| 2 | `checks.build` 填什麼 | 沒有 build 步驟，永遠是 `not_run` |
| 3 | Orchestrator 怎麼知道測試真的過了 | 新增 `checks.json`，由 `runChecks` 寫入實際結果 |
| 4 | 失敗的 run 能不能下載 | 不行，只有 `completed` 能下載（跟 MSW 一樣） |
| 5 | 檔案不是 UTF-8 | 回 415 `UNSUPPORTED_FILE` |
| 6 | 後端重開時跑到一半的 run | 啟動時改成 `failed` |
| 7 | 路徑檢查放哪 | 先寫基本版在 `workspaces/service.py`，Member A 接手擴充 |
| 8 | 修復上限 | ~~設定值，預設 2~~ → **整個 run 共用的修復次數，預設 3**（2026-11-19 改） |
| 10 | 整個 app 跑一次，還是每個 feature 各跑一次 | **每個 feature 各跑一次**：Planner 拆成最多 4 個 feature，每個 feature 依序跑 Coder → Tester（2026-11-19 決定） |
| 11 | 要不要加一個 AI 來分配、監控工作 | **不要**：拆任務交給 Planner，分配和監控交給 Orchestrator（一般程式，不是 AI），行為固定、可測試、不花 API 額度（2026-11-19 決定） |
| 9 | agent 介面 | `execute(context, recorder)`；MCP client 由 agent 自己建立 |

## 紀錄

### 2026-11-18 — 步驟 1：專案設定、骨架、錯誤格式、CORS

**做了什麼**
- 開分支 `feat/backend-core`
- `backend/.venv` 用 Python 3.12 建立（系統內建的 Python 是 3.9，不符合 `>=3.11`）
- `pyproject.toml`：加入 `fastapi`、`uvicorn[standard]`、`pydantic`；開發用 `pytest`、`httpx2`；設定 pytest 直接從 `src/` 匯入
- `config.py`：`Settings`（資料目錄、修復上限、CORS 來源），可以用環境變數覆蓋
- `api/errors.py`：`ApiError` 和統一錯誤格式。FastAPI 自己產生的錯誤（找不到路由、方法不對、驗證失敗、程式例外）也全部轉成 `{"error": {code, message}}`，驗證失敗回 400 而不是 FastAPI 預設的 422
- `main.py`：`create_app(settings)` 工廠函式，裝上 CORS 和錯誤處理，加了 `GET /api/health`

**測試**（`tests/test_app.py`，11 個）
- 先寫測試，確認全部失敗（模組還不存在），再實作
- 結果：11 passed
- 另外實際啟動 uvicorn，`/api/health` 回 `{"status":"ok"}`，不存在的路由回 404 和正確的錯誤格式

**備註**
- `GET /api/health` 不在 `interfaces.md` 的規格裡，是給前端和組員確認後端有沒有開起來用的，不影響既有規格
- 500 錯誤只在伺服器 log 記錄真正原因，不會把錯誤細節傳給瀏覽器
- `pip install -e ".[dev]"` 會產生 `*.egg-info/`，已加進 `.gitignore`（順便加了 `.DS_Store`）

### 2026-11-18 — 步驟 2：儲存層

**做了什麼**
- `models.py`：定義所有存在磁碟上的資料格式（`WorkspaceRecord`、`RunRecord`、`AgentTask`、`AgentResult`、`CheckExecution`、`RunEvent`、`Usage`）。Python 用 snake_case，JSON 自動轉 camelCase。保留 `AgentRole`、`RunContext`、`AgentTask`、`AgentResult` 這些名稱，因為其他棒的骨架會 import
- `storage/repository.py`：`FileStorage`，唯一讀寫 run 目錄的地方
  - workspace：建立、列出（舊的在前）、讀取
  - run：建立（同時建好所有檔案和第一筆 `queued` 事件）、列出（新的在前）、讀取、更新
  - 事件：新增（ID 自動遞增）、依 cursor 讀取
  - 用量：累加（`totalTokens` 可以另外指定，給 Gemini 的 thinking token 用）
  - 任務：發布、讀取最新的、提交結果
  - 測試執行紀錄：新增（結果由儲存層判斷，不由呼叫者決定）、列出
  - 啟動時把卡在 `queued` / `running` 的 run 改成 `failed`
- 新增 `checks.json`（決定事項 #3），同步更新 `workspaces/README.md` 和 `architecture.md`
- `pydantic` 最低版本改成 2.11（用到的 `validate_by_name` 設定是 2.11 才有）
- spec 補上「Run directory files」一節：每個檔案的 JSON 格式、範例、欄位說明，以及給 Member A 和 Ching 用的 `FileStorage` 方法表

**安全和可靠性的設計**
- ID 會變成資料夾名稱，所以只接受英數字和連字號（1～64 字），`../etc` 這種 ID 一律當作不存在
- 寫 JSON 時先寫暫存檔再改名（atomic write），另一個程式（MCP server）不會讀到寫一半的檔案
- 同一個 run 的「讀取 → 修改 → 寫回」加鎖，事件 ID 不會重複
- 測試執行的 log 只保留最後 20,000 字（測試工具會把失敗摘要印在最後）

**測試**（`tests/test_storage.py` 31 個 + `tests/test_imports.py` 26 個）
- 先寫測試，確認失敗後才實作
- 包含：磁碟上的 JSON 格式、排序、不安全的 ID、跨 workspace 讀不到 run、20 個執行緒同時寫事件 ID 不重複、用量累加、任務的 attempt 編號、測試結果判斷、log 截斷、重啟恢復
- 結果：全部 68 個測試通過

**備註**
- 新增 `test_imports.py` 的原因見「問題總整理」
- MCP server 雖然是另一個程式，但用同一份程式碼：自己建一個 `FileStorage` 指到同一個目錄就好，格式只有一個實作

### 2026-11-18 — 步驟 3：Workspace 的 3 個路由

**做了什麼**
- `api/schemas.py`：HTTP 回應格式 `WorkspaceSummary`、`WorkspaceDetail`，跟 `frontend/src/types/index.ts` 一致
- `api/routes.py`：把原本的空殼換成真的路由
  - `GET /api/workspaces`：回傳 `[{id, name}]`，舊的在前
  - `POST /api/workspaces`：名稱去掉前後空白；缺少、不是字串、空白、不是 JSON、不是物件都回 400 `INVALID_INPUT`；成功回 201
  - `GET /api/workspaces/{id}`：回傳 `{id, name, rootPath, createdAt}`；不存在或不安全的 ID 回 404
  - request body 自己解析，不用 FastAPI 的參數宣告，這樣檢查順序才能跟規格一樣（例如先 404 再 400），錯誤格式也統一
- `main.py`：建立一個共用的 `FileStorage`，掛上路由
- `rootPath`：資料放在 repo 裡（預設）時是 `workspaces/<id>`，跟 MSW 一樣；放在 repo 外面時是絕對路徑
- 新增 `tests/conftest.py`：共用的 `client`、`settings` fixture 和 `assert_error`
- spec 補上「HTTP routes」一節

**測試**
- `tests/test_workspace_routes.py`（22 個；另外 `test_imports.py` 多了 1 個新模組）：先寫測試，確認 16 個失敗後才實作
  - 寫測試時發現兩個測試互相矛盾（測試資料放在 repo 外，`rootPath` 不可能是 `workspaces/<id>`），改成直接測 `display_root_path()` 這個函式，也避免測試寫進真的 repo
- pytest：全部 91 個通過
- **真的前端 + 真的後端**（前端關掉 MSW，用 Chrome 自動操作，腳本放在 scratchpad，是暫時的，步驟 6 會整理成正式測試）：
  - ✅ 頁面從後端讀取 workspace 列表
  - ✅ 建立 workspace 的請求真的送到後端（不是 MSW），回 201，名稱有去掉空白
  - ✅ 對話框關閉，新 workspace 被選取
  - ✅ 重新整理頁面後 workspace 還在（存在磁碟上）
  - ❌ `rootPath` 沒顯示、console 有 404：原因是 `GET …/runs` 還沒做，見「問題總整理」，步驟 4 後重新驗證

**備註**
- 為了跑瀏覽器檢查，在 `frontend/` 執行了 `npm ci`（`node_modules/` 已在 `.gitignore`）

### 2026-11-19 — 步驟 4：Run 路由 + Orchestrator + 假 agent

**先 commit 步驟 1～3**
- `7aa8a52` docs：架構、分工、交接
- `6c3d27a` backend：骨架、儲存層、workspace 路由
- 兩個 commit 都沒有 Co-Authored-By

**做了什麼**
- `orchestration/orchestrator.py`：Planner → Coder → Tester，測試沒過就修（最多 `max_repairs` 次）
  - 每個角色：發布任務 → 設定 `activeRole` → 寫事件 → 呼叫 agent → 確認有提交結果
  - Planner 只跑一次；修復時只重跑 Coder 和 Tester，Coder 會拿到上次失敗的測試輸出（`previousFailure`）
  - **測試有沒有過只看 `checks.json`，而且只看這一輪的紀錄**：Tester 自己說成功不算數，上一輪通過的紀錄也不能拿來用
  - 任何失敗都把 run 改成 `failed`，`error` 寫清楚原因；結束時 `activeRole` 一定清空
- `orchestration/scheduler.py`：在背景執行 run，`POST` 馬上回傳；同一個 workspace 一次只跑一個 run；關閉後端時取消執行中的 run
- `orchestration/recorder.py`：`RunRecorder`，agent 只能透過它寫事件和用量，不能改 run 的狀態
- `agents/base.py`：agent 介面改成 `execute(context, recorder)`，註解寫了 6 條規則（決定事項 #9）
- `agents/placeholder.py`：假的 Planner / Coder / Tester，寫出固定的 Playlist 專案；假 Tester **不會真的跑測試**，事件和 log 都標明 placeholder
- `agents/planner.py`、`coder.py`、`tester.py`：Ching 第 4 棒要實作的骨架，改成新的介面
- `api/schemas.py`、`api/routes.py`：`GET/POST …/runs`、`GET …/runs/{id}`
- `main.py`：建立 orchestrator 和 scheduler；啟動時把卡住的 run 改成 `failed`（決定事項 #6），關閉時取消執行中的 run；`create_app(agents=...)` 讓第 4 棒換成真的 agent
- `config.py`：新增兩個設定：每個假 agent 停頓幾秒（讓前端看得到進度）、假 Tester 前幾次要回報失敗（用來手動測修復迴圈）

**測試**
- 先寫測試，確認失敗後才實作：
  - `test_orchestrator.py`（19 個）：用「照劇本演出」的假 agent 測各種情況：正常完成、事件順序、計畫有傳給 Coder 和 Tester、修復一次後成功、修復次數用完、Tester 說謊、Tester 沒跑測試、用上一輪的結果、agent 沒提交、agent 當掉、同一 workspace 不會同時跑、關閉時的處理
  - `test_run_routes.py`（24 個）：回傳格式、檢查順序（先 404 再 400）、9 種錯誤的 body、跨 workspace 讀 run 回 404、背景執行完成、用設定觸發修復迴圈、啟動時的恢復
  - `test_placeholder_agents.py`（7 個）：假 agent 有照交接規則做、有標明自己是 placeholder；**它寫出的專案真的能通過 `node --test`**
- 寫測試時自己的兩個錯誤：輔助函式取名 `tester_with_results`，被 pytest 當成測試；排程測試跑兩個 run 卻只給一次的結果。都已修正
- pytest：全部 146 個通過；連跑 100 次 0 失敗
- **真的前端 + 真的後端**（Chrome）：9 項全部通過，包括步驟 3 沒過的 `rootPath` 和 console 錯誤
- **真的後端 + HTTP 實測**：`POST` 回 `queued`，接著看到 `running planner → running coder → running tester → completed`，`checks.tests = passed`，專案資料夾裡有 4 個檔案

**給其他棒的發現**
- 產生的專案裡，測試用 `import` 載入 `playlist.js`，Node.js 規定這時專案要有 `package.json` 並設定 `"type": "module"`，否則 `node --test` 會失敗。假 Coder 有寫這個檔案，真的 agent 也要寫（已寫進 spec）
- uvicorn 啟動時呼叫 `create_app()` 不帶參數，第 4 棒要決定怎麼切換成真的 agent（例如新增一個設定），已寫進 spec

**備註**
- 改寫 agent 骨架時，第一次用的 shell 語法 zsh 不支援，三個檔案被清空，馬上用檔案工具重寫，沒有影響
- 前端目前**不能從畫面送出需求**（對話框只存本機草稿），這是 Ching 第 4 棒的前端工作，所以 run 是用 HTTP 直接建立來測的
- 前端顯示 run 進度時會呼叫 `GET …/events`，這個路由步驟 5 才做，所以畫面上的進度要到步驟 5 才能完整驗證

### 2026-11-19 — 改成「每個 feature 各跑一次流程」

**為什麼改**
- 原本的設計是整個 app 只跑一次：Planner 規劃全部 → Coder 一次寫完 → Tester 一次測完
- 討論後改成每個 feature 各跑一次：出錯時知道是哪個 feature、每次只寫一小塊比較容易寫對、比較像真實的漸進式開發、demo 看得到「Feature 2/4」
- 代價是 API 呼叫變多（約 30～40 次），所以加了限制（下面）
- 也討論了要不要加一個 AI 當經理來分配和監控工作。決定**不加**：拆任務是 Planner 的工作；分配和監控的規則是固定的，用程式（Orchestrator）做比較可靠、可以測試，也不花額度。這是 Anthropic 建議的 workflow 模式
- 現在還在第 2 棒，改格式的成本最低；交棒後再改就要動 Member A 和 Ching 的東西

**新的流程**
```
Planner：交出計畫 + feature 清單（1～4 個）
每個 feature 依序：
  Coder：在現有程式上加這個 feature
  Tester：加這個 feature 的測試，然後跑「全部」測試
  過了 → 下一個 feature
  沒過 → 修復次數還有 → Coder 修、Tester 重跑（測試不改）
        修復次數用完 → 整個 run 失敗，後面的 feature 不做
全部 feature 都過 → 完成
```

**限制（控制免費額度）**
| 限制 | 設定 | 預設 |
| --- | --- | --- |
| feature 上限 | `AI_CODER_MAX_FEATURES` | 4 |
| 修復次數，整個 run 共用 | `AI_CODER_MAX_REPAIRS` | 3（原本是每次 run 2 次） |
| 每次跑全部測試 | Tester 的任務說明 | 一律 |
| 修不好就停止 | Orchestrator | 一律 |

**資料格式的改變（交接合約）**
- Planner 的結果多了 `features`：`[{title, description}, ...]`
- Coder / Tester 的任務多了 `feature`（`number`、`total`、`title`、`description`）和 `repair`（是不是修復）
- 任務的 `attempt` 改名為 `sequence`：同一個角色現在會因為不同 feature 拿到很多任務，「第幾次嘗試」會誤導
- 新的事件：`feature_started`、`feature_completed`；`checks`、`repair` 的訊息會寫是第幾個 feature

**改了哪些程式**
- `models.py`：新增 `PlannedFeature`、`TaskFeature`；`AgentResult.features`；`AgentTask` 的 `sequence`、`feature`、`repair`
- `storage/repository.py`：`publish_task` 多了 `feature`、`repair`；`submit_result` 多了 `features`（可以直接收 JSON 的 dict，方便 MCP 工具傳進來）
- `orchestration/orchestrator.py`：重寫成 feature 迴圈；檢查 Planner 的 feature 清單（數量、標題不能空白）
- `config.py`：新增 `max_features`；`max_repairs` 預設改成 3
- `agents/placeholder.py`：假 Planner 規劃兩個 feature（「Filter by genre」、「Smooth transitions」），假 Coder 一次加一個 feature，假 Tester 每個 feature 寫一個測試檔
- `agents/base.py`、`planner.py`、`coder.py`、`tester.py`：介面說明加上 feature 的規則

**測試**
- 先改測試，確認因為新的型別不存在而失敗，再實作
- `test_orchestrator.py`（25 個）：每個 feature 都跑 Coder → Tester、事件順序、任務裡有 feature 資訊、Planner 沒給 feature / 給太多 / 標題空白、feature 內修復、**修復次數跨 feature 共用**、修不好時後面的 feature 不會開始、拿前一個 feature 的通過紀錄充數會被擋下
- `test_storage.py`：新增 feature 欄位和 Planner `features` 的格式測試
- `test_placeholder_agents.py`：假 Planner 規劃兩個 feature
- pytest：全部 155 個通過；連跑 50 次 0 失敗
- **真的後端實測**（設定假 Tester 前 2 次失敗）：事件顯示 feature 1 失敗 → 修復 1 → 失敗 → 修復 2 → 通過 → feature 2 通過 → 完成；最後的專案用**真的 `node --test`** 跑：2 passed, 0 failed

**更新的文件**
- `docs/backend-spec.md`：設定、決定事項 #8 #10、`tasks.json` 格式和範例、事件表、`FileStorage` 方法表、Run lifecycle、失敗原因表、agent 介面、假 agent 說明
- `docs/architecture.md`：決定事項表、架構圖、「One run, step by step」
- `docs/interfaces.md`：`submitResult` 參數、Orchestrator 職責、「One complete run」
- `docs/team-responsibilities.md`：Pete、Member A、Ching 三棒的工作內容
- `backend/tests/README.md`

**備註**
- 使用假 agent 時，`AI_CODER_MAX_FEATURES` 至少要是 2（假 Planner 固定規劃兩個 feature），已寫進 spec

### 2026-11-19 — 步驟 5：事件、檔案、檔案內容、下載路由

**先 commit**：`b319935`（每個 feature 各跑一次流程），沒有 Co-Authored-By

**做了什麼**
- `workspaces/service.py`：路徑檢查，**Member A 的 MCP 檔案工具也要用同一套**（決定事項 #7）
  - `validate_relative_path`：語法檢查（空字串、`/` 開頭、`C:`、反斜線、NUL、空的 / `.` / `..` 片段）
  - `resolve_project_path`：跟著 symlink 找到真正位置，跑到專案外面就拒絕
- `storage/repository.py`：
  - `list_project_files`：列出專案裡的一般檔案（含子資料夾），大小用 bytes，**跳過 symlink**
  - `package_run`：打包 zip 到 `artifacts/<runId>.zip`，附上 `RUNNING.md`（怎麼打開網頁、怎麼跑測試）；專案自己有 `RUNNING.md` 就保留專案的
- `orchestrator.py`：所有 feature 都通過後，**先打包再標記完成**，所以完成的 run 一定可以下載
- `api/routes.py`：4 個路由，**`interfaces.md` 的 10 個路由全部完成**
  - `GET …/events?after=N`：cursor 不合法回 400 `INVALID_CURSOR`；空的 `after` 當作 0（跟 MSW 一樣，因為 JavaScript 的 `Number("")` 是 0）
  - `GET …/files`
  - `GET …/file?path=`：檢查順序 404（run 不存在）→ 400（路徑不合法或 symlink 跑出去）→ 404（檔案不存在或是資料夾）→ 413（超過 2 MiB）→ 415（不是 UTF-8）
  - `GET …/download`：只有 `completed` 能下載，其他回 409；zip 不見了會重新打包
- `api/schemas.py`：`RunEvents`、`ArtifactFile`、`FileContent`
- 把等待 run 完成的輔助函式搬到 `tests/conftest.py`，兩個測試檔共用

**測試**
- 先寫測試，確認失敗後才實作（`test_paths.py` 無法載入、`test_file_routes.py` 43 個裡 36 個失敗）
- `test_paths.py`（23 個）：合法和不合法的路徑、symlink 指到外面的檔案和資料夾、專案內的 symlink 可以用
- `test_file_routes.py`（43 個）：cursor 的各種錯誤值、大小用 bytes（`é` 是 2 bytes）、子資料夾、symlink 不列出、9 種不合法路徑、symlink 逃逸**而且回應裡沒有洩漏檔案內容**、剛好 2 MiB 可以、多 1 byte 就 413、PNG 回 415、zip 內容和 `RUNNING.md`
- pytest：全部 221 個通過；連跑 30 次 0 失敗
- **真的前端 + 真的後端**（Chrome，假 Tester 第 1 次失敗）：10 項全部通過
  - 建立 workspace → 建立 run → 前端狀態顯示 `Tester · …`、`Coder · …` → `No active task · Completed`
  - 側邊欄出現 5 個產生的檔案
  - 點 `playlist.js` 可以預覽內容
  - **預覽區顯示產生的 `index.html`**（Playlist Mixer 標題和 3 首歌）
  - 下載回傳 zip
  - 沒有 API 錯誤、沒有 console 錯誤
- 步驟 3 的瀏覽器腳本也重跑：9 項全部通過

**給 Ching 的發現**
- 前端面板的狀態列只顯示**最新的一筆事件**，而且每 3 秒才問一次。`feature_started` 之後馬上有好幾筆 `tool_call`，所以畫面上幾乎看不到「Feature 2/4 started」。事件 API 本身是對的（4 筆 feature 事件都有）。建議第 4 棒做前端時，另外顯示最近一筆 `feature_*` 事件，或在進度區列出所有事件
- 前端目前還沒有送出需求和下載按鈕（第 4 棒的工作），所以這兩項是直接呼叫 API 測的

**備註**
- `mediaType` 比 MSW 多分了幾種（`.js` 是 `text/javascript`，MSW 是 `text/plain`）。查過前端：語法上色是看檔名，不看 `mediaType`，所以畫面沒有差別。已寫進 spec

### 2026-11-19 — 步驟 6：前端整體實測，瀏覽器測試變成正式測試

**先 commit**：`b1f0bf3`（步驟 5），沒有 Co-Authored-By

**為什麼要做**
- 之前的瀏覽器測試腳本放在暫存資料夾，電腦清理後就會消失，組員也拿不到
- 也還沒測過錯誤情境在前端長什麼樣子

**做了什麼**
- 新增 `backend/e2e/`，**一個指令跑完全部**：`backend/e2e/run.sh`
  - 自動啟動前端（關掉 MSW），每個情境用不同設定啟動後端，跑完就關掉
  - 測試資料放在暫存資料夾，跑完自動刪除，不會寫進 repo
  - 啟動前檢查 port 8000、5173 有沒有被占用、`.venv` 和 `node_modules` 在不在，缺東西會說明要怎麼補
  - 預設用電腦上的 Google Chrome，也可以設 `E2E_BROWSER_CHANNEL=bundled` 改用 Playwright 的 Chromium
- 4 個情境：

| 情境 | 後端設定 | 檢查項目 | 結果 |
| --- | --- | --- | --- |
| `workspaces.mjs` | 預設 | 列表來自後端、建立後去掉空白、被選取、顯示 rootPath、重新整理後還在 | 7/7 |
| `run.mjs` | 假 Tester 第 1 次失敗 | 面板顯示 agent 在工作再變 Completed、事件有修復和兩個 feature、側邊欄有檔案、可以預覽檔案、預覽區顯示 index.html、可以下載 zip | 11/11 |
| `failed-run.mjs`（新） | 假 Tester 一直失敗、只能修 1 次 | 面板顯示 `Failed ·` 和後端給的原因、run 是 failed 且 activeRole 清空、不能下載（409）、feature 2 沒有開始 | 7/7 |
| `backend-down.mjs`（新） | 沒有後端 | 顯示 Retry 按鈕、沒有 workspace、**不會偷偷改用 MSW 的範例資料** | 3/3 |

- 全部 28 項通過，連跑 3 次都通過，跑完 port 都有釋放
- 文件：`backend/e2e/README.md`（怎麼跑、需要什麼、每個情境測什麼、還沒涵蓋的部分）；`docs/backend-spec.md` 和 `backend/tests/README.md` 加上連結

**過程中修正的地方（都是我寫的測試腳本的問題，不是程式的 bug）**
- `workspaces.mjs` 一開始是在頁面載入**之後**才開始等 workspace 列表的回應，可能錯過。改成在打開頁面前就開始記錄所有 API 呼叫
- `backend-down.mjs` 判斷「列表裡沒有 workspace」時，把「Retry loading workspaces」按鈕也算進去了。先把按鈕名稱印出來確認，再排除重試按鈕

**看到的前端行為（記錄下來）**
- run 失敗時，面板顯示的是後端 `error` 欄位的原文，例如：`Failed · Feature 1 of 2 (Filter by genre) failed its tests and no repair rounds are left (limit 1 per run).`。所以後端的錯誤訊息要寫給使用者看得懂，這點在 agent 介面規則裡已經寫了
- 後端沒開時，前端照 `frontend/README.md` 的設計，明確顯示錯誤，不會退回範例資料

**還沒涵蓋（第 4 棒之後補）**
- 前端目前不能送出需求、沒有下載按鈕，所以 `run.mjs` 是直接呼叫 API。Ching 做好之後，改成點按鈕
