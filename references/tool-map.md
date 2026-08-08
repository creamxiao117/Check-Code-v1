# 检查器与工具映射

## 通用原则

- 优先使用项目已经声明的命令和配置。
- 只调用本机或项目环境中已经存在的工具。
- 不使用会自动下载依赖的命令；Node.js 检查使用 `npx --no-install`。
- 检查器缺失时记录为 `SKIP`，并生成待确认安装命令；`--strict` 时才升级为失败。
- 项目自定义配置放在 `.check-code.toml`，历史问题使用 `--baseline` 管理，不要把临时例外硬编码到技能中。

## 文件与项目识别

| 识别信号 | 检查器 |
| --- | --- |
| `.py`、`pyproject.toml`、`pytest.ini` | Ruff、pytest |
| `package.json`、`.js`、`.jsx`、`.ts`、`.tsx` | 项目 lint/test、ESLint、Prettier |
| `.sln`、`.csproj`、`.cs` | `dotnet format`、`dotnet test` |
| `.ps1`、`.psm1`、`.psd1` | PSScriptAnalyzer |
| `.sh`、`.bash` | ShellCheck |
| `.json` | Python 标准库 `json` |
| `.toml` | Python 3.11+ 标准库 `tomllib` |
| `.yaml`、`.yml` | `yamllint`（如果已安装） |
| `.md` | `markdownlint` 或 `markdownlint-cli`（如果已安装） |
| `.pre-commit-config.yaml` | `pre-commit run` 或 `pre-commit run --all-files` |

## 推荐安装提示

技能不会自动执行这些安装命令，只在终端和报告中生成待确认安装清单：

```text
Python: python -m pip install ruff pytest
Node.js: npm install --save-dev eslint prettier
.NET: 安装对应 .NET SDK
PowerShell: Install-Module PSScriptAnalyzer -Scope CurrentUser
Shell: 安装 shellcheck
YAML: python -m pip install yamllint
Markdown: npm install --save-dev markdownlint-cli
```

## 项目命令优先级

- `package.json` 中存在 `lint` 时运行 `npm run lint`。
- `package.json` 中存在 `test` 时运行 `npm run test --if-present`。
- `Makefile` 中存在 `lint`、`check` 或 `test` 目标时，只运行这些质量目标。
- 存在 `.pre-commit-config.yaml` 且工具可用时，优先运行项目 Hook，避免重复运行内置检查器。
- 不自动猜测或执行任意 `Makefile` 目标、部署脚本和业务脚本。
- `.sln` 优先于单个 `.csproj`；没有解决方案时使用发现到的第一个项目文件。
