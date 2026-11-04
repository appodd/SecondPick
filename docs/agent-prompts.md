# Agent 部署与使用 Prompt

将对应场景的模板复制给**具备本机终端与文件操作能力的外部 AI Agent**。无需提前填写一长串参数；让 Agent 先检查当前目录、已有安装和服务，再询问必要的信息。日常使用时，可以在模板后补一句想找的商品或想完成的操作。

外部 Agent 负责帮助部署、运行和操作 SecondPick；SecondPick 内部 AI Runtime 负责商品研究，目前文字研究使用 Codex CLI。外部 Agent 可用不代表内部研究已配置好。基础采集不需要 Codex CLI；AI 增强模式需要额外配置 CLI 与账号授权，项目自动研究另行授权，默认不授权。视觉模型始终可选。

[首次部署](#首次部署) · [更新现有安装](#更新现有安装) · [日常使用](#日常使用) · [English templates](#english-templates)

返回项目介绍：[简体中文](../README.md#快速开始) · [English](../README.en.md#quick-start)。具体安装步骤见[使用指南](user-guide.md)，升级前核对[开发说明](DEVELOPMENT.md)和[隐私边界](PRIVACY.md)。

## 中文模板

### 首次部署

已有安装需要升级时，使用下一份模板。发现已有项目但无法判断是不是正在使用的安装时，先核对，不重复部署。

```text
请帮我在这台电脑部署并运行 SecondPick。
仓库：https://github.com/appodd/SecondPick，首次获取使用 main 分支。

先检查当前工作目录、会话已知位置及常用项目目录，寻找已有 SecondPick 仓库、
本地服务与数据目录，不无差别扫描整块磁盘。找到则检查并复用；没有再选合适目录
获取仓库。若有多个安装或位置不明确，再向我询问。仓库登录由我本人完成。

阅读 README.md、docs/user-guide.md、docs/architecture.md 和 docs/DEVELOPMENT.md。
检查系统、Python、浏览器、端口及虚拟环境，根据实际状态规划并执行必要安装，
优先使用现有兼容环境。区分“网页工作台可启动”和“真实采集已就绪”。
首次安装使用 Python 3.12 创建项目环境并安装应用，再运行 python scripts/setup_monitor.py。
由统一程序获取固定版本引擎、准备独立 Python 依赖、应用登录与采集浏览器，
执行环境检查并生成启动配置，不让用户手动 clone 外部引擎、checkout 或拼接独立环境。
准备成功后在仓库根目录运行 shopping-agent-web，默认自动读取本地监控配置；
已有显式自定义配置时先核对原启动方式和数据位置，不擅自切换。
不要同时启动多个实例操作同一数据库，也不要将服务绑定到公网。

询问我使用基础采集还是 AI 增强模式，再带我完成对应的首次引导。
基础模式不安装不需要的 CLI 或视觉扩展；AI 增强模式需单独检查 Codex CLI
和账号授权。外部 Agent 的模型配置不等于 SecondPick 内部 Runtime 已配置。
若本机已有 Codex CLI 和有效授权，先检查版本、服务进程可访问的命令路径及认证
是否满足 SecondPick 要求；满足就复用，不重复安装或要求重新登录，不读取凭据内容。
只有缺失、失效或不兼容时才说明需要补充的安装或授权步骤。
视觉模型始终可选，商品图片处理能力按实际需要准备。

默认保留已有数据、配置和未提交改动。写入持久化配置前说明路径与具体改动，
只对尚未获得明确授权的变更请求确认，已有授权范围内不重复询问。
闲鱼登录和模型账号登录由我本人完成，不索取、读取或输出密钥、Cookie 等凭据。
不要因完成引导而授权自动研究。真实采集、模型调用和项目自动研究授权，
应说明范围并按用户授权及项目确认流程执行，不作为默认部署测试。

最后打开工作台，报告访问地址、启动和停止方式、数据与配置位置、实际检查结果，
区分工作台、采集和 AI 能力的就绪情况，并列出还需要我完成的步骤。
当前文档未支持的环境如无法验证，应如实说明。
```

### 更新现有安装

```text
请检查并更新这台电脑上的 SecondPick。

先从当前目录和已知项目位置寻找已有安装，核对仓库 remote、当前分支与提交、
未提交改动、虚拟环境、启动方式、端口、实际配置和数据位置。多个安装不明确时
再询问我，不克隆新副本替代现有运行数据，也不自动切换分支。
阅读当前和拟更新版本的 README.md、docs/user-guide.md、docs/DEVELOPMENT.md
与 docs/architecture.md，检查依赖、独立引擎版本和数据迁移要求。

先完成只读检查，再说明拟更新的版本、兼容性、文件和持久化配置改动及回退方式，
针对尚未授权的变更取得确认。保留本地改动；不强制 reset、清理、覆盖或推送。
若升级需要改数据库，先确认迁移要求并在安全状态下备份；不猜测迁移命令。
检查是否有运行中的采集、研究或待调度任务，说明停止和恢复的影响，
按授权安排维护，不为升级直接终止活动任务。备份须与数据库写入状态一致，
保留原配置、登录资料和数据目录，记录原提交及恢复步骤。

按文档更新代码和必要依赖，沿用用户的基础或 AI 增强模式，不额外启用研究。
在已正常停止相关服务的原项目环境运行 python scripts/setup_monitor.py，统一准备或修复采集依赖。
默认安装随后运行 shopping-agent-web，无需手动拼接 --config；自定义安装按原实际配置
使用准备程序的 --config 并保留显式启动方式。只读诊断可用 python scripts/setup_monitor.py --check-only。
自定义安装的只读诊断也需带上原 --config 路径。
已有引擎版本冲突、修改或未知目录时，保留现场并按程序提示处理，不强制 checkout 或覆盖。
如需 AI，先检查并复用已有兼容的 Codex CLI 和有效授权，避免重复安装或授权；
不覆盖独立引擎本地改动，不启动多个实例共用数据库。需要用户登录时由本人完成。
涉及自动研究授权或监控范围变化，单独展示并确认，不把升级视为授权。

用本地诊断检查并恢复原启动方式，不默认执行真实采集或付费模型调用。
报告更新前后版本、备份位置、实际检查结果、服务状态和仍需处理的兼容性问题。
如不能安全更新，保留现状并说明具体原因和可行下一步。
```

### 日常使用

```text
请帮我使用这台电脑上已有的 SecondPick，完成我接下来描述的选购或管理任务。

先阅读 README.md、docs/user-guide.md，并从已有目录、启动记录或已知本机地址
确认实际安装与服务。检查现有项目、目标、监控和研究状态，优先复用相关内容。
不要要求我先填写完整参数表；先理解我的目标，再询问尚缺少且会影响操作的信息。

根据已有数据提出具体操作：可以浏览商品、筛选收藏、比较候选、调整目标，
或创建监控、按需发起研究。使用界面或已有支持的工具，不直接改数据库。
涉及目标、运行配置等持久化变更时，先展示修改及影响，并取得相应确认；
明确授权过的范围不重复询问。不要自动扩大监控范围或开启长期任务。
启动真实采集前展示关键词、模式、频率、数量限制，遵循项目范围确认流程。

只采集时不依赖 Codex CLI，不发起 AI 解析、研究或追问。
需要研究时检查 SecondPick 内部 Codex CLI 和账号授权，展示目标版本、商品范围
及可能的模型调用；自动研究需项目单独授权，默认不授权，视觉模型可选。
外部 Agent 可用不代表内部研究 Runtime 就绪，也不代表已授权自动研究。

登录失效、验证码或平台限制交由我本人按正常流程处理，不绕过验证，
不读取或输出凭据，不向卖家发消息、议价、下单或支付。
最后汇报实际执行状态、采集结果或研究覆盖及待核实问题，区分排队、运行和完成。
```

## English templates

An external Agent needs local terminal and file access. It should inspect the installation before asking for missing information. Its own model access does not configure SecondPick's internal Codex CLI runtime or authorize project research.

[First-time deployment](#first-time-deployment) · [Update an existing installation](#update-an-existing-installation) · [Daily use](#daily-use)

### First-time deployment

Use the update template when upgrading an existing installation. If an existing checkout may already be in use, inspect it before creating another one.

```text
Help me deploy and run SecondPick on this computer.
Repository: https://github.com/appodd/SecondPick.
Use main for a new checkout.

Inspect the current directory, known session locations, and usual project directories for
an existing checkout, service, and data. Do not scan the entire disk indiscriminately.
Inspect and reuse an existing installation; otherwise obtain the repository in a suitable
location. Ask if multiple installations or ambiguous locations need a choice.
I will handle repository authentication myself.

Read README.en.md, docs/user-guide.md, docs/architecture.md, and docs/DEVELOPMENT.md.
Inspect the OS, Python, browser, ports, and environments; plan and execute the necessary
installation using compatible existing resources. Distinguish a working web interface
from real collection readiness. For a new installation, use Python 3.12 to create the
project environment and install the app, then run python scripts/setup_monitor.py.
Let that program fetch the pinned engine, prepare isolated Python dependencies and both
login and collection browsers, check the environment, and generate startup configuration.
Do not make the user manually clone or check out the external engine or assemble its environment.
After success, run shopping-agent-web from the repository root; generated local monitoring
configuration is loaded automatically. Preserve existing explicit custom configuration,
startup methods, and data locations rather than switching them silently.
Do not run multiple instances against one database or expose the service publicly.

Ask whether I want Basic collection or AI-enhanced mode, then guide me through onboarding.
Basic mode needs no CLI or unnecessary vision extras. AI-enhanced mode additionally needs
Codex CLI and account authentication. The external Agent's model configuration does not
configure SecondPick's internal Runtime. If Codex CLI is already installed and authenticated,
check its version, command availability to the service process, and authentication status
against SecondPick's requirements without reading credentials. Reuse it when compatible;
do not reinstall or request login again. Explain additional steps only when installation
or authentication is missing, invalid, or incompatible. Vision is optional; prepare image processing
capabilities only as needed.

Preserve existing data, configuration, and uncommitted changes. Explain the paths and
changes before persistent configuration writes. Confirm changes not already authorized;
do not repeatedly ask for actions within an explicitly authorized scope.
I will perform Xianyu and model-account login. Do not request, read, or print credentials.
Completing onboarding does not authorize automatic research. Explain the scope of real
collection, model calls, or project research authorization and follow user authorization
and the project's confirmation flow; do not use them as default deployment tests.

Open the workspace and report its URL, start/stop instructions, data/configuration locations,
actual checks, separate workspace/collection/AI readiness, and remaining steps for me.
Clearly report environments unsupported by current docs if you cannot verify them.
```

### Update an existing installation

```text
Help me inspect and update my existing SecondPick installation.

Find it in the current or known project locations. Inspect its remote, branch, commit,
uncommitted changes, environment, startup method, ports, actual configuration, and data.
Ask if multiple installations are ambiguous. Do not replace it with a new checkout or
switch branches automatically. Read README.en.md, docs/user-guide.md, docs/DEVELOPMENT.md,
and docs/architecture.md for both the current and proposed versions. Check dependencies,
the supported collection-engine revision, and migration requirements.

Perform read-only checks first. Explain the target version, compatibility, file and
persistent configuration changes, and rollback plan; confirm changes not already authorized.
Preserve local work. Do not force reset, clean, overwrite, or push.
If database changes are needed, establish the migration requirements and back up safely;
do not invent migration commands. Check running collection, research, and scheduled work.
Explain stop/resume effects and arrange maintenance within authorization rather than
terminating active work. Keep backups consistent with database writes. Preserve original
configuration, login profiles, and data locations; record the original commit and recovery steps.

Update code and required dependencies according to the docs. Preserve Basic or AI-enhanced
mode and existing permissions. When AI is needed, inspect and reuse compatible existing
Codex CLI and valid authentication rather than reinstalling or requesting login again.
After stopping the relevant services normally, run python scripts/setup_monitor.py in
the original project environment to prepare or repair collection dependencies. For a
default installation, restart with shopping-agent-web; no manual --config assembly is needed.
For custom installations, pass their actual --config to the preparation program and
preserve the explicit startup configuration. Use python scripts/setup_monitor.py --check-only
for read-only diagnostics. Preserve conflicting engine revisions, local changes, or unknown
directories and follow the reported instructions; do not force checkout or overwrite them.
Read-only diagnostics for a custom installation must also include its original --config path.
Do not overwrite engine modifications or run multiple
instances against one database. I will handle any required login.
Show and separately confirm research authorization or monitor-scope changes; an update
does not grant them.

Use local diagnostics and restore the original startup method. Do not default to real
collection or paid model calls. Report before/after versions, backup locations, actual
checks, service state, and outstanding compatibility issues. If the update cannot proceed
safely, preserve the installation and explain the specific reason and next steps.
```

### Daily use

```text
Help me use my existing SecondPick installation for the shopping or management task I describe next.

Read README.en.md and docs/user-guide.md. Locate the actual installation and service from
existing directories, startup records, or known local URLs. Inspect projects, goals,
monitors, and research state, reusing relevant existing work. Understand my request before
asking for missing information that materially affects the action; do not demand a long form.

Propose concrete actions based on existing data: browse, filter, save, compare, revise
goals, create monitors, or request research. Use the UI or supported tools, not direct
database edits. Show persistent changes to goals or runtime configuration and their impact
before obtaining the appropriate confirmation. Do not repeat requests within explicitly
authorized scope or silently expand collection scope or enable long-term tasks.
Before real collection, show keywords, mode, frequency, and limits and follow the project's
scope confirmation flow.

Collection-only use requires no Codex CLI and must not trigger AI drafting, research,
or follow-up calls. For research, check SecondPick's internal Codex CLI and authentication;
show the goal version, listing scope, and potential model calls. Automatic research needs
separate project authorization and is off by default; vision is optional. The external
Agent being available does not imply that internal research is ready or authorized.

Let me handle expired login, verification challenges, and platform restrictions normally.
Do not bypass verification, read or print credentials, message sellers, negotiate,
order, or pay. Report actual execution state, collection results or research coverage,
and questions to verify, distinguishing queued, running, and completed work.
```
