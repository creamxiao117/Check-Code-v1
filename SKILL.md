---
name: check-code-v1
description: 通用代码质量检查技能。用于检查 Git 改动或整个项目中的 Python、JavaScript、TypeScript、C#、PowerShell、Shell 以及 JSON、YAML、TOML、Markdown 文件；自动识别项目结构，优先使用项目已有检查命令，调用可用的 lint、format、test 和语法检查工具，输出中文摘要、原始日志和 Markdown 报告。默认只检查不修改、不安装依赖；用户要求代码检查、提交前检查、PR
...
---

# Check Code v1

## 工作目标

对当前项目进行可审计的静态检查和测试，并明确区分通过、失败、跳过、工具缺失和运行错误。默认检查 Git 未提交改动；需要检查整个项目时使用 `--all`。

## 执行规则

1. 先确认项目根目录和 Git 状态，识别项目清单与可用工具。
2. 优先读取并使用项目已有配置和命令，例如 `pyproject.toml`、`package.json`、`.sln`、`.csproj`、CI 配置和项目脚本；不要重复执行同一检查。
   - 如果存在 `.pre-commit-config.yaml` 且 `pre-commit` 可用，优先执行项目 Hook，并跳过内置重复检查。
3. 运行内置检查器：Python、Node.js/TypeScript、.NET、PowerShell、Shell、JSON、TOML、YAML、Markdown。工具映射见 [references/tool-map.md](references/tool-map.md)。
4. 缺少工具时生成醒目的“待确认安装”清单，列出影响范围和准确安装命令；不自动安装依赖。
5. 默认只检查，不运行格式化器的写入模式、不执行自动修复、不覆盖源文件。
6. 检查结束后运行脚本生成中文摘要和 Markdown 报告；报告默认位于 `work/check-code-v1/`。
7. 不能把“跳过”或“工具缺失”描述为“检查通过”。最终回复必须分别报告通过、失败和跳过项。

## 缺失环境确认流程

检查输出或 Markdown 报告出现“待确认安装”时，必须执行以下流程：

1. 不要直接宣布检查完成；先告诉用户哪些检查被跳过、为什么跳过以及准备执行的安装命令。
2. 明确询问用户是否安装，安装范围优先是当前项目的 `.venv` 或 Node.js `devDependencies`。
3. 用户未确认前，不执行安装命令，不修改项目依赖文件。
4. 用户确认后，执行报告中列出的命令；安装完成后自动重新运行原检查命令。
5. 重新检查仍有失败或缺失时，继续报告实际状态，不能把安装动作当成检查通过。

## Qt / GUI 项目的测试防污染（2026-09-10 实战新增）

项目依赖含 PySide6 / PyQt5/6 时，直接跑 pytest 会在**用户真实桌面弹出空白窗口和通知**（测试污染，用户会当显示 bug 投诉）。执行规则：

1. 跑 pytest 前先查依赖：`grep -iE "pyside6|pyqt" pyproject.toml requirements*.txt`。
2. 命中则确保 `QT_QPA_PLATFORM=offscreen`（优先看项目 conftest.py 是否已设；没设就 export 后再跑，**不要改项目源文件**）。
3. 报告中注明测试是否运行于 offscreen，便于追溯"桌面弹窗"类投诉。

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
- 缺失工具不会自动安装；报告和终端会输出“待确认安装”区块，供 Codex 在对话中请求确认。

## 历史问题基线

老项目可以先记录已有问题：

```powershell
python "D:\AIwork\20260821-Fan-SkillHub\skills\shared\engineering\check-code-v1\scripts\check_code.py" --all --write-baseline baseline.json
```

后续检查时只报告新增问题：

```powershell
python "D:\AIwork\20260821-Fan-SkillHub\skills\shared\engineering\check-code-v1\scripts\check_code.py" --all --baseline baseline.json
```

基线只抑制完全匹配的历史失败项，不会抑制新问题。基线文件应纳入 Git，更新基线前必须人工确认。

## 运行方式

在项目根目录执行：

```powershell
python "D:\AIwork\20260821-Fan-SkillHub\skills\shared\engineering\check-code-v1\scripts\check_code.py"
```

常用参数：

```powershell
# 检查整个项目
python "D:\AIwork\20260821-Fan-SkillHub\skills\shared\engineering\check-code-v1\scripts\check_code.py" --all

# 缺少检查工具时也让命令失败，适合 CI 或 PR
python "D:\AIwork\20260821-Fan-SkillHub\skills\shared\engineering\check-code-v1\scripts\check_code.py" --all --strict

# 指定报告路径
python "D:\AIwork\20260821-Fan-SkillHub\skills\shared\engineering\check-code-v1\scripts\check_code.py" --report work/check-code-v1/latest.md
```

如果项目使用虚拟环境，优先使用项目解释器：

```powershell
.\.venv\Scripts\python.exe "D:\AIwork\20260821-Fan-SkillHub\skills\shared\engineering\check-code-v1\scripts\check_code.py"
```

Windows 无 .venv 时的解释器优先级（2026-09-10 实战新增）：WorkBuddy 托管 Python（`C:\Users\<user>\.workbuddy\binaries\python\versions\<ver>\python.exe`）→ 系统 Python。**注意：PATH 上抓到的解释器/venv 未必装了项目依赖**（如共享 venv 是别的工具专用，pytest 收集即错、退出码 2），先验证再跑：`python -c "import <项目关键依赖>"`，失败则改用 `.check-code.toml` 的 `[check-code.commands]` 把 test/lint 固定到正确解释器。项目 `core.hooksPath` 指向自定义 pre-commit（git config 而非 .pre-commit-config.yaml）时同样算"项目已有 Hook"，跳过内置重复检查。

## 结果处理

- 退出码 `0`：适用的检查通过；可以存在非严格模式下的工具缺失或跳过。
- 退出码 `1`：至少一个适用检查失败。
- 退出码 `2`：技能运行错误、项目根目录无效或报告无法生成。
- 需要修复时，先引用报告中的文件、行号和原始输出，再单独执行修复；不要在本技能检查阶段隐式修改文件。

## 失败修复的常见诱因（直接定位）

修复 check-code-v1 失败时，先按这些高频模式匹配，不要从 0 排查：

| 失败现象 | 高频根因 | 定位命令 |
|:--|:--|:--|
| Ruff F401 `imported but unused` | 引入新 import 但实际未用 | `grep "from xxx import" <file> \| wc -l` vs 使用次数 |
| **Ruff 错误"凭空爆几十上百个"** | pyproject 无 `[tool.ruff.lint] select` → 规则集随 ruff 版本漂移（新版默认集扩张） | `ruff check --isolated <file>` 对照：isolated 也报 = 规则漂移非代码问题；根治 = 锁 `select = ["E","W","F","I","B"]`，勿批量"修"漂移项 |
| Ruff I001 import 排序错 | 新 import 加在文件末尾 | `ruff check --fix` 自动修 |
| Ruff DTZ011 `datetime.date.today()` | 用 local date 而非 UTC | 改 `datetime.now(tz=timezone.utc).date()` |
| Ruff F821 undefined name | 局部 import 在函数内但函数外用 | 移到文件顶部 |
| Ruff RUF100 unused noqa | `# noqa: E501` 之类但 E501 未启用 | 删 noqa |
| Ruff ISC004 implicit str concat | `["foo", "bar"]` 多个相邻 str 无 `,` | 改用 `+` 或 `\n.join()` |
| Markdown MD022 标题前后空行 | 三级标题后缺空行 | 标题后加一行 |
| Ruff 格式错 | 缩进/行长/空行 | `ruff format <file>` 自动修 |
| yamllint CRLF | Windows 写 YAML 用了 CRLF | `sed -i 's/
$//' <file>` + 加 `---` 首行 |

**修完后再跑** `--all`：必须回到 14/14 PASS / 退出码 0 才算完成。

## 多仓并行写时的"只提交自己"纪律

- 跑 `--all` 时**只 fix 自己 commit 的文件**；别人的 M 状态（含 untracked + 别人改的）不动。
- `git status` 输出中：`M `（大写空格）= staged by me；` M`（空格大写）= unstaged by someone else；`??` = untracked。
- 报"最后退出码 1"但报告里只看到别人的文件错 → **不修**，是别的 Agent 在制品；只报状态让用户决定。

## 报告要求

最终报告至少包含：项目类型、检查范围、检查器清单、通过/失败/跳过/基线统计、工具缺失、失败位置、原始日志、建议命令和最终退出码。报告写入项目的 `work/check-code-v1/`，不得写入技能目录。
