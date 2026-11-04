# 开发说明

## 目录

- `src/shopping_agent/`：Python 后端、采集适配、研究与数据模型。
- `web/src/`：React 界面；`web/e2e/`：隔离的浏览器测试。
- `src/shopping_agent/web/static/`：随仓库分发的前端构建产物。
- `tests/`：后端测试和必要的离线第三方适配夹具。
- `skills/`：产品研究运行时所需的提示与工具契约。
- `scripts/`、`devtools/`：保留的安装、离线测试和审查工具。
- `config/default.toml`：默认配置，不包含用户凭据。

## 安装与检查

直接在本 Public 仓库开发、测试、构建和发布，以当前代码和测试为准；不需要从 Private 同步代码或生成发行快照。历史研发材料仅按需参考，不作为开发依赖。

推荐 Windows Python 3.12 与 Node.js 24（本轮使用 3.12.10、24.15.0、npm 11.12.1）。Node.js 用于前端开发和测试，普通用户运行已构建工作台不需要它。请在当前源码目录创建独立环境，不复用其他 checkout 的 editable 安装：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

```powershell
# Recommended reproducible backend test environment: Windows Python 3.12.
python -m pip install -r requirements/backend-tests-windows-py312.lock.txt
python -m pip install -c requirements/backend-tests-windows-py312.lock.txt -e ".[test,vision,monitor]"
python -m playwright install chromium
npm --prefix web ci
Set-Location web
npx tsc --noEmit
npm test
npm run build
Set-Location ..
$env:PYTHONUTF8 = "1"
python -m pytest -p devtools.p4_offline_test_guard -q
# Run after serial regression; xdist is included in the test environment lock.
python -m pytest -p devtools.p4_offline_test_guard -n 4 -q
python devtools/release_audit.py HEAD
```

`monitor` 扩展为 Windows 安装后端测试需要的时区数据，部分后端测试也使用 Chromium。需要前端浏览器测试时，再在 `web` 目录执行 `npm run test:e2e`；配置会在独立端口启动隔离夹具服务。不要把真实运行服务设为 E2E 测试目标。

准备产品的真实采集依赖时，在停止服务后执行 `python scripts/setup_monitor.py`：自动获取受支持的固定版本引擎、创建独立环境、安装锁定依赖与用户级 Chromium，并检查环境、生成本地配置。它不执行登录、采集或模型请求。无需为了离线单元测试运行该安装；安装流程测试使用临时 checkout 和模拟安装。`--check-only` 只诊断；已有配置和冲突目录不会覆盖，完整操作见[使用指南](user-guide.md#准备独立采集环境)。

准备程序分别使用应用解释器与独立采集解释器安装各自 Playwright 所需的 Chromium；它们可能使用不同版本，不能只安装其中一个后假定两者都可用。下方前端 E2E 的 Node Playwright 浏览器准备仍须单独执行。

普通 `shopping-agent-web` 优先读取 `config/monitor.local.toml`，不存在时回退 `config/default.toml`；显式 `--config` 优先且路径必须存在。调试和测试应继续明确传入隔离配置，避免误用用户安装。

Windows 后端测试使用 `PYTHONUTF8=1`，使测试及子进程生成的 UTF-8 文件按相同编码读写。少量历史验收测试仅在对应本地材料存在时运行；这些真实材料不随公开源码分发，缺失时会明确跳过，合成数据回归仍照常执行。

锁文件仅供完整后端回归使用，包含可选视觉测试依赖和 pytest-xdist，不改变用户的基础安装依赖。其他平台可按 `pyproject.toml` 安装测试扩展后单独验证。切换源码目录时注意 editable 安装的导入位置；独立候选须在自己的环境安装，不能只切换工作目录就假定已加载候选源码。

Windows 上如需指定 pytest 的 `--basetemp`，请使用系统临时目录中的短路径。过长的验收日志目录再叠加 xdist 子目录、测试名和图片哈希文件名，可能触发 Windows 路径长度限制；日志和 JUnit 可单独保存在项目的验收目录。

后端测试应使用临时数据库和模拟运行时。离线保护插件阻止外部 DNS、网络图片工作线程和真实 Codex 启动；故意验证网络边界的测试需要注入模拟传输，不应关掉保护绕过失败。

已完成的回归与独立安装检查见[验证记录](VALIDATION.md)。离线测试不等于真实平台、模型效果或长期运行验收。前端构建存在大于 500 kB 的包体积提示。

### Desktop E2E

SecondPick 是 Desktop-first 的本地单用户工作台。**Desktop Chromium 是唯一默认 E2E 验收平台**；默认不注册 Mobile project，不要求手机适配。保留的桌面尺寸、键盘、抽屉与布局检查不代表移动端支持承诺。

```powershell
# 后端依赖已按上方锁文件安装；前端浏览器与 Python Playwright 分别安装。
Set-Location web
npm ci
npx playwright install chromium
npm run test:e2e -- --list
npm run test:e2e
```

Playwright 自动启动 8876 端口的临时夹具服务，不复用已有服务。夹具用合成商品、临时数据库、模拟采集和模拟 Runtime，Python 离线保护及浏览器本地代理边界阻止真实平台和模型调用。默认套件不读取维护者的历史 JSON；行情投影与视觉观察数据在 `web/e2e/synthetic-market.ts` 及对应 spec 中明确构造。后端仍有五项显式可选历史验收测试，缺少私有材料时跳过，不应复制真实材料补齐。

失败证据在 `web/test-results/`，可用 `npx playwright show-trace <trace.zip>` 查看。不要删除断言、恢复过时按钮或增加固定 sleep 来处理失败；检查当前 UI、接口契约及任务持久化完成状态。

### 前后端开发联调

在已激活同一个项目虚拟环境的两个终端中分别运行：

```powershell
# 仓库根目录，后端默认端口 8765。
shopping-agent-web --host 127.0.0.1 --port 8765

# 第二个终端，仓库根目录。
npm --prefix web run dev
```

打开 `http://127.0.0.1:5173`。Vite 固定本机 5173 端口并将 `/api` 代理至 `http://127.0.0.1:8765`；端口占用时明确退出，不静默换端口。代理保留浏览器请求的 Host，避免写请求的 Origin 与后端看到的 URL 不一致。后端的 loopback Host 和同源写入检查保持启用，不要通过放宽 CORS、重写 Origin 或关闭校验解决联调问题。若改变后端端口，须同步调整 `web/vite.config.ts` 的代理目标。

开发服务使用配置指定的数据库；新环境默认初始化本地数据，调试时应提供专用 `--config` 和 `--settings`，不要对真实采集数据库运行测试。采集、登录和模型服务仍需用户独立配置与明确授权。

生产模式使用 `npm --prefix web run build` 后由后端同源提供静态资源，无需运行 Vite。`npx tsc --noEmit`（在 web 内）、`npm --prefix web test` 分别检查类型和组件/单元测试；当前没有独立 lint script。

## 开发工具索引

以下是开发与诊断工具，不是部署时必须运行的步骤。先读参数帮助，再选择需要的检查；不要把真实模型回放当作默认离线测试。

| 工具 | 默认行为与显式执行 | 输出与写入 |
|---|---|---|
| `devtools/release_audit.py` | 默认扫描 `HEAD` 的 Git 树，也可传入其他 ref；不调用模型 | JSON 到标准输出，只列问题路径与类别，不打印匹配到的凭据；需要已建立的 Git 历史 |
| `devtools/run_codex_blackbox.py` | 提供必需参数后直接调用真实 Codex CLI，没有计划模式或 `--run` 开关 | 文件权限与详细输出见下一节 |
| `devtools/p4_offline_test_guard.py` | 通过 pytest 的 `-p devtools.p4_offline_test_guard` 加载，阻止外部 DNS/连接、真实网络工作线程和 Codex 启动 | 本身不生成报告；测试数据与日志由 pytest 和用例配置决定 |
| `scripts/replay_model_quality.py` | 默认仅列计划，`calls=0`；`--run --output` 调用真实 CLI；`--rescore <报告> --output` 只重评分，不重新调用模型 | `--case` 可选内置探针，默认单次超时 90 秒；结果保存在指定的新报告文件 |
| `scripts/replay_purchase_journey.py` | 默认仅列八轮计划；`--run --output` 回放；`--audit <报告> --output` 离线检查；`--diagnose <报告> --output` 是一次新的模型调用 | 运行上限由 `--max-calls` 指定，默认 32；`--current-prompt` 仅供 diagnose；指定报告保存调用、输出及遥测 |
| `scripts/replay_statement_corrections.py` | 默认仅列计划；`--run --output` 执行真实模型条件修正探针 | 合成输入，调用上限 3；指定报告保存结果与遥测 |
| `scripts/replay_check_context.py` | 默认仅列计划；`--run --output` 执行；`--reviews` 切换为用户复核来源与失效检查 | 合成输入，调用上限 3；指定报告保存结果与遥测 |
| `scripts/replay_check_suggestions.py` | 默认仅列计划；`--run --output` 执行两轮建议与模拟用户确认流程 | 调用上限 2；临时数据库中的确认不代表对真实用户项目授权 |
| `scripts/audit_answer_copy.py` | 读取位置参数指定的已有报告，`--output` 必填；仅文字检查，不调用模型 | 写新报告，不覆盖输入或已有输出 |
| `scripts/setup_monitor.py` | 获取固定版本引擎、准备独立依赖与浏览器并检查；`--root`、`--venv`、`--config` 支持自定义路径；`--check-only` 不安装、不写配置 | 默认 `.monitor-venv/`；检查成功且文件不存在时原子生成 `config/monitor.local.toml`，普通启动器自动使用；不启动服务或采集 |

五个 `replay_*.py` 工具默认计划模式只输出标准输出，没有默认持久化报告目录。执行、诊断或重评分时，使用调用者指定的 `--output` 新文件，已有输出会被拒绝覆盖。真实执行的合成工作区、数据库等位于系统临时目录，正常退出时清理；不要依赖临时文件作为长期证据。重评分和 audit 读取的是调用者提供的报告，不要求维护者的历史数据。

真实回放使用当前 `CodexRuntime` 的 `read-only` CLI 沙箱；Python 工具本身仍会写临时数据及报告，这也不是操作系统级文件隔离。它们使用已有 CLI 账号，可能产生模型费用，不经过工作台中的项目自动研究授权开关。指定 `--run` 或 `--diagnose` 前应确认调用范围；脚本的合成确认不能替代生产项目的用户授权。

### Codex CLI 黑盒调试

`run_codex_blackbox.py` 的 `--prompt`、`--events`、`--stderr`、`--last-message`、`--cwd` 和 `--model` 均为必需参数。它会读取指定提示文件并立即执行真实 CLI，不是无调用的检查器。

- `--sandbox` 默认 **`workspace-write`**，可选 `read-only`、`workspace-write`、`danger-full-access`；不会因为是调试工具就自动降为只读。`--cwd` 指定工作区，`--session-id` 可恢复已有会话。不要在包含个人数据的工作区直接运行未知提示。
- 事件/标准输出、标准错误和最终答复分别写到 `--events`、`--stderr`、`--last-message`。`--metadata` 可指定元数据文件，未指定时放在 events 同目录，名称为 `<events文件主名>.metadata.json`，记录模型、权限、超时、工作区、会话标识和命令。
- 这些输出以写入模式打开，**可能覆盖已有文件**，应使用新的专用输出目录。`--timeout-seconds` 默认 300 秒，超时会终止本次 CLI 进程树；不影响其他已运行服务。

CLI 调试和真实回放可能向模型服务发送提示与选定证据，输出还可能包含原始返回、会话信息及本机路径。使用合成输入，遵循[隐私边界](PRIVACY.md)，不要提交原始输出、凭据或含个人数据的报告。回放的自动检查通过也不等于模型质量已完成人工验收。

另有 `devtools/readme_screenshots.mjs` 使用合成 API 响应生成素材，输出在 `docs/images/`，`--tour` 还会使用本地 `data/artifacts/` 中的临时帧目录。它会写入图片，不应作为默认安装检查；操作见[素材说明](images/README.md)。

## 发布

先确认 `git status`，审查暂存文件和目标分支可达历史，再执行发布扫描。扫描只报告文件路径与类别，不打印凭据内容；它会将测试地址等也列为待核对项，不是完整 DLP 保证。

项目默认不会导入示例商品。除空目录占位外，`data/` 均为本机运行数据。发布清单和隐私范围见[隐私说明](PRIVACY.md)。
