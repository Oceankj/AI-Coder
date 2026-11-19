# Work Log

第 2 棒（Pete）：後端核心。分支 `feat/backend-core`。
規格見 [docs/backend-spec.md](docs/backend-spec.md)。

## 問題總整理

新問題加在「未解決」；解決後移到「已解決」，並寫上怎麼解決的。

### 未解決

- **真的前端選到 workspace 後顯示「Could not load」**（2026-11-18，步驟 3）
  前端載入 workspace 時會同時呼叫 `GET /api/workspaces/{id}/runs`，這個路由要到步驟 4 才做，目前回 404，整個 workspace 畫面就載入失敗，底部的 `rootPath` 也不會顯示。
  不是 workspace 路由的問題：建立、選取、重新整理後還在，都驗證過了。
  處理：步驟 4 做完 run 路由後，用同一個瀏覽器腳本重新驗證。

### 已解決

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
| 4 | Run 路由 + Orchestrator + 假 agent | ⬜ |
| 5 | 事件、檔案、下載路由 | ⬜ |
| 6 | 前端整體實測，補齊錯誤情境 | ⬜ |
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
| 8 | 修復上限 | 設定值，預設 2 |
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
