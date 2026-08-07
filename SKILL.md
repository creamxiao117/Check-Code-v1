---
name: check-code-v1
description: 通用代码质量检查技能。用于检查 Git 改动或整个项目中的 Python、JavaScript、TypeScript、C#、PowerShell、Shell 以及 JSON、YAML、TOML、Markdown 文件；自动识别项目结构，优先使用项目已有检查命令，调用可用的 lint、format、test 和语法检查工具，输出中文摘要、原始日志和 Markdown 报告。默认只检查不修改、不安装依赖；用户要求代码检查、提交前检查、PR 检查、质量检查或验证改动时使用。
---

# Check Code v1

## 工作目标

对当前项目进行可审计的静态检查和测试，并明确区分通过、失败、跳过、工具缺失和运行错误。默认检查 Git 未提交改动；需要检查整个项目时使用 `--all`。

## 执行规则

1. 先确认项目根目录和 Git 状态，识别项目清单与可用工具。
2. 优先读取并使用项目已有配置和命令，例如 `pyproject.toml`、`package.json`、`.sln`、`.csproj`、CI 配置和项目脚本；不要重复执行同一检查。
   - 如果存在 `.pre-commit-config.yaml` 且 `pre-commit` 可用，优先执行项目 Hook，并跳过内置重复检查。
3. 运行内置检查器：Python、Node.js/TypeScript、.NET、PowerShell、Shell、JSON、TOML、YAML、Markdown。工具映射见 [references/tool-map.md](references/tool-map.md)。
4. 缺少工具时只报告工具名称、影响范围和安装建议，不自动安装依赖。
5. 默认只检查，不运行格式化器的写入模式、不执行自动修复、不覆盖源文件。
6. 检查结束后运行脚本生成中文摘要和 Markdown 报告；报告默认位于 `work/check-code-v1/`。
7. 不能把“跳过”或“工具缺失”描述为“检查通过”。最终回复必须分别报告通过、失败和跳过项。

## 项目配置

项目根目录可以增加 `.check-code.toml`，控制本项目的检查行为：

```toml
[check-code]
strict = false
run_tests = true
exclude = ["generated/**", "vendor/**"]
required_tools = ["ruff", "pytest"]

[check-code.commands]
lint = ["npm", "run", "lint"]
test = ["npm", "run", "test", "--if-present"]
```

- `strict`：项目级严格模式；命令行 `--strict` 优先级更高。
- `run_tests`：设为 `false` 时跳过 pytest、npm test、dotnet test 和 Makefile test。
- `exclude`：使用相对路径或 glob 排除生成物、第三方目录等。
- `required_tools`：声明本项目必须具备的工具；缺失时会报告，严格模式下返回失败。
- `[check-code.commands]`：追加项目自定义检查命令，命令数组不经过 Shell 解释。

## 历史问题基线

老项目可以先记录已有问题：

```powershell
python "C:\Users\Fan-SJSS\.codex\skills\check-code-v1\scripts\check_code.py" --all --write-baseline baseline.json
```

后续检查时只报告新增问题：

```powershell
python "C:\Users\Fan-SJSS\.codex\skills\check-code-v1\scripts\check_code.py" --all --baseline baseline.json
```

基线只抑制完全匹配的历史失败项，不会抑制新问题。基线文件应纳入 Git，更新基线前必须人工确认。

## 运行方式

在项目根目录执行：

```powershell
python "C:\Users\Fan-SJSS\.codex\skills\check-code-v1\scripts\check_code.py"
```

常用参数：

```powershell
# 检查整个项目
python "C:\Users\Fan-SJSS\.codex\skills\check-code-v1\scripts\check_code.py" --all

# 缺少检查工具时也让命令失败，适合 CI 或 PR
python "C:\Users\Fan-SJSS\.codex\skills\check-code-v1\scripts\check_code.py" --all --strict

# 指定报告路径
python "C:\Users\Fan-SJSS\.codex\skills\check-code-v1\scripts\check_code.py" --report work/check-code-v1/latest.md
```

如果项目使用虚拟环境，优先使用项目解释器：

```powershell
.\.venv\Scripts\python.exe "C:\Users\Fan-SJSS\.codex\skills\check-code-v1\scripts\check_code.py"
```

## 结果处理

- 退出码 `0`：适用的检查通过；可以存在非严格模式下的工具缺失或跳过。
- 退出码 `1`：至少一个适用检查失败。
- 退出码 `2`：技能运行错误、项目根目录无效或报告无法生成。
- 需要修复时，先引用报告中的文件、行号和原始输出，再单独执行修复；不要在本技能检查阶段隐式修改文件。

## 报告要求

最终报告至少包含：项目类型、检查范围、检查器清单、通过/失败/跳过/基线统计、工具缺失、失败位置、原始日志、建议命令和最终退出码。报告写入项目的 `work/check-code-v1/`，不得写入技能目录。
