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

Windows 后端测试使用 `PYTHONUTF8=1`，使测试及子进程生成的 UTF-8 文件按相同编码读写。少量历史验收测试仅在对应本地材料存在时运行；这些真实材料不随公开源码分发，缺失时会明确跳过，合成数据回归仍照常执行。

锁文件仅供完整后端回归使用，包含可选视觉测试依赖和 pytest-xdist，不改变用户的基础安装依赖。其他平台可按 `pyproject.toml` 安装测试扩展后单独验证。切换源码目录时注意 editable 安装的导入位置；独立候选须在自己的环境安装，不能只切换工作目录就假定已加载候选源码。

Windows 上如需指定 pytest 的 `--basetemp`，请使用系统临时目录中的短路径。过长的验收日志目录再叠加 xdist 子目录、测试名和图片哈希文件名，可能触发 Windows 路径长度限制；日志和 JUnit 可单独保存在项目的验收目录。

后端测试应使用临时数据库和模拟运行时。离线保护插件阻止外部 DNS、网络图片工作线程和真实 Codex 启动；故意验证网络边界的测试需要注入模拟传输，不应关掉保护绕过失败。

已完成的回归与独立安装检查见[验证记录](VALIDATION.md)。离线测试不等于真实平台、模型效果或长期运行验收。前端构建存在大于 500 kB 的包体积提示。

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
| `scripts/setup_monitor.py` | 默认准备独立引擎环境；`--venv` 可指定环境；`--check-only` 检查已有环境而不安装依赖或生成本地配置 | 默认 `.monitor-venv/`，安装清单写入其中的 `installed-packages.txt`；检查成功且配置不存在时生成 `config/monitor.local.toml`，不自动启动服务或采集 |

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
