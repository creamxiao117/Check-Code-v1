#!/usr/bin/env python3
"""通用项目代码检查器。

只调用已经存在的工具，不安装依赖、不修改源文件；结果同时输出到终端和 Markdown 报告。
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence


EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "bin",
    "obj",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "work",
}

SUPPORTED_SUFFIXES = {
    ".py",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".cs",
    ".ps1",
    ".psm1",
    ".psd1",
    ".sh",
    ".bash",
    ".json",
    ".toml",
    ".yaml",
    ".yml",
    ".md",
}

INSTALL_HINTS = {
    "ruff": "建议：python -m pip install ruff",
    "pytest": "建议：python -m pip install pytest",
    "pre-commit": "建议：python -m pip install pre-commit",
    "npm": "建议安装 Node.js/npm",
    "npx": "建议安装 Node.js/npm",
    "dotnet": "建议安装对应版本的 .NET SDK",
    "PSScriptAnalyzer": "建议：Install-Module PSScriptAnalyzer -Scope CurrentUser",
    "shellcheck": "建议安装 shellcheck",
    "make": "建议安装 GNU Make 或 gmake",
    "yamllint": "建议：python -m pip install yamllint",
    "markdownlint": "建议：npm install --save-dev markdownlint-cli",
}


@dataclass
class CheckResult:
    name: str
    status: str
    command: str = ""
    output: str = ""
    reason: str = ""
    files: list[str] = field(default_factory=list)


@dataclass
class ProjectConfig:
    path: Path | None = None
    strict: bool = False
    run_tests: bool = True
    exclude: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    commands: dict[str, list[str]] = field(default_factory=dict)


def configure_output() -> None:
    """避免 Windows 控制台编码导致中文日志无法显示。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def command_text(command: Sequence[str]) -> str:
    return " ".join(shlex.quote(str(part)) for part in command)


def trim_output(output: str, limit: int = 20000) -> str:
    output = output.strip()
    if len(output) <= limit:
        return output
    return output[:limit] + "\n...[日志已截断]"


def which_in_project(root: Path, names: Iterable[str]) -> str | None:
    """优先查找项目虚拟环境，再查找 PATH。"""
    for name in names:
        candidates = [
            root / ".venv" / "Scripts" / f"{name}.exe",
            root / ".venv" / "Scripts" / name,
            root / ".venv" / "bin" / name,
            root / "venv" / "Scripts" / f"{name}.exe",
            root / "venv" / "Scripts" / name,
            root / "venv" / "bin" / name,
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


def run_command(
    name: str,
    command: Sequence[str],
    root: Path,
    files: Sequence[str] = (),
    timeout: int = 300,
) -> CheckResult:
    """运行外部检查命令并保留原始输出。"""
    executable = command[0]
    if not Path(executable).is_file() and shutil.which(executable) is None:
        return CheckResult(
            name=name,
            status="SKIP",
            command=command_text(command),
            reason=f"未找到工具：{executable}",
            files=list(files),
        )

    try:
        completed = subprocess.run(
            list(command),
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = trim_output((exc.stdout or "") + "\n" + (exc.stderr or ""))
        return CheckResult(
            name=name,
            status="FAIL",
            command=command_text(command),
            output=output,
            reason=f"执行超过 {timeout} 秒后超时",
            files=list(files),
        )
    except OSError as exc:
        return CheckResult(
            name=name,
            status="FAIL",
            command=command_text(command),
            output=str(exc),
            reason="启动检查工具失败",
            files=list(files),
        )

    output = trim_output((completed.stdout or "") + "\n" + (completed.stderr or ""))
    return CheckResult(
        name=name,
        status="PASS" if completed.returncode == 0 else "FAIL",
        command=command_text(command),
        output=output,
        reason="" if completed.returncode == 0 else f"退出码：{completed.returncode}",
        files=list(files),
    )


def run_python_parser(name: str, path: Path, root: Path) -> CheckResult:
    relative = path.relative_to(root).as_posix()
    try:
        if path.suffix.lower() == ".json":
            with path.open("r", encoding="utf-8") as stream:
                json.load(stream)
        else:
            with path.open("rb") as stream:
                tomllib.load(stream)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        return CheckResult(
            name=f"{name}：{relative}",
            status="FAIL",
            command=f"Python 标准库解析 {relative}",
            output=str(exc),
            reason="语法解析失败",
            files=[relative],
        )
    return CheckResult(
        name=f"{name}：{relative}",
        status="PASS",
        command=f"Python 标准库解析 {relative}",
        files=[relative],
    )


def missing_tool_reason(tool: str) -> str:
    return f"未找到 {tool}；{INSTALL_HINTS.get(tool, '请安装项目要求的检查工具')}"


def load_project_config(root: Path) -> ProjectConfig:
    """读取项目根目录的 .check-code.toml，配置错误直接交给调用方处理。"""
    path = root / ".check-code.toml"
    if not path.is_file():
        return ProjectConfig()
    with path.open("rb") as stream:
        document = tomllib.load(stream)
    section = document.get("check-code", {})
    if not isinstance(section, dict):
        raise ValueError(".check-code.toml 的 [check-code] 必须是表")

    exclude = section.get("exclude", [])
    required_tools = section.get("required_tools", [])
    for field_name, value in (("exclude", exclude), ("required_tools", required_tools)):
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f".check-code.toml 的 {field_name} 必须是字符串数组")

    commands_value = section.get("commands", {})
    if not isinstance(commands_value, dict):
        raise ValueError(".check-code.toml 的 [check-code.commands] 必须是表")
    commands: dict[str, list[str]] = {}
    for name, value in commands_value.items():
        if isinstance(value, list) and all(isinstance(item, str) for item in value):
            commands[name] = list(value)
        elif isinstance(value, str):
            commands[name] = shlex.split(value, posix=os.name != "nt")
        else:
            raise ValueError(f".check-code.toml 的命令 {name} 必须是字符串或字符串数组")

    strict = section.get("strict", False)
    run_tests = section.get("run_tests", True)
    if not isinstance(strict, bool) or not isinstance(run_tests, bool):
        raise ValueError(".check-code.toml 的 strict 和 run_tests 必须是布尔值")
    return ProjectConfig(
        path=path,
        strict=strict,
        run_tests=run_tests,
        exclude=list(exclude),
        required_tools=list(required_tools),
        commands=commands,
    )


def is_excluded(relative: str, extra_patterns: Sequence[str] = ()) -> bool:
    normalized = relative.replace("\\", "/").lstrip("./")
    parts = normalized.split("/")
    if any(part in EXCLUDED_DIRS for part in parts):
        return True
    return any(
        fnmatch.fnmatch(normalized, pattern) or any(fnmatch.fnmatch(part, pattern) for part in parts)
        for pattern in extra_patterns
    )


def relative_files(root: Path, paths: Iterable[Path], extra_patterns: Sequence[str] = ()) -> list[str]:
    values: list[str] = []
    for path in paths:
        try:
            relative = path.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        if is_excluded(relative.as_posix(), extra_patterns):
            continue
        values.append(relative.as_posix())
    return sorted(set(values))


def iter_project_files(root: Path, extra_patterns: Sequence[str] = ()) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or is_excluded(path.relative_to(root).as_posix(), extra_patterns):
            continue
        if path.suffix.lower() in SUPPORTED_SUFFIXES or path.name in {
            "package.json",
            "pyproject.toml",
            "pytest.ini",
            "Makefile",
        }:
            paths.append(path)
    return paths


def git_changed_files(root: Path) -> tuple[bool, list[str]]:
    if shutil.which("git") is None:
        return False, []
    check = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check.returncode != 0:
        return False, []

    values: set[str] = set()
    commands = [
        ["git", "diff", "--name-only", "--diff-filter=ACMRTUXB"],
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    for command in commands:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        values.update(line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip())
    return True, sorted(values)


def load_package_json(root: Path) -> dict:
    package = root / "package.json"
    if not package.is_file():
        return {}
    try:
        return json.loads(package.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def package_has_dependency(package: dict, name: str) -> bool:
    for field_name in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        if name in package.get(field_name, {}):
            return True
    return False


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def project_types(root: Path, all_files: Sequence[Path]) -> list[str]:
    names = {path.name.lower() for path in root.iterdir()} if root.exists() else set()
    suffixes = {path.suffix.lower() for path in all_files}
    types: list[str] = []
    if ".py" in suffixes or "pyproject.toml" in names or "pytest.ini" in names:
        types.append("Python")
    if "package.json" in names or suffixes & {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
        types.append("Node.js/TypeScript")
    if ".sln" in suffixes or ".csproj" in suffixes or ".cs" in suffixes:
        types.append(".NET/C#")
    if suffixes & {".ps1", ".psm1", ".psd1"}:
        types.append("PowerShell")
    if suffixes & {".sh", ".bash"}:
        types.append("Shell")
    if ".json" in suffixes:
        types.append("JSON")
    if ".toml" in suffixes:
        types.append("TOML")
    if suffixes & {".yaml", ".yml"}:
        types.append("YAML")
    if ".md" in suffixes:
        types.append("Markdown")
    return types


def add_configured_checks(root: Path, selected: Sequence[str], config: ProjectConfig) -> list[CheckResult]:
    if not config.commands or not selected:
        return []
    return [
        run_command(f"项目命令：{name}", command, root, selected)
        for name, command in config.commands.items()
    ]


def add_required_tool_checks(root: Path, config: ProjectConfig) -> list[CheckResult]:
    results: list[CheckResult] = []
    for tool in config.required_tools:
        if which_in_project(root, [tool]):
            results.append(CheckResult(f"必需工具：{tool}", "PASS"))
        else:
            results.append(CheckResult(f"必需工具：{tool}", "SKIP", reason=missing_tool_reason(tool)))
    return results


def add_python_checks(
    root: Path,
    selected: Sequence[str],
    all_paths: Sequence[Path],
    run_tests: bool = True,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    py_files = [path for path in selected if path.lower().endswith(".py")]
    python_config_names = {"pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini", "ruff.toml"}
    config_changed = any(Path(path).name.lower() in python_config_names for path in selected)
    if not py_files and not config_changed:
        return results

    ruff = which_in_project(root, ["ruff"])
    if py_files and ruff:
        results.append(run_command("Ruff 代码检查", [ruff, "check", *py_files], root, py_files))
        results.append(run_command("Ruff 格式检查", [ruff, "format", "--check", *py_files], root, py_files))
    elif py_files:
        results.append(
            CheckResult(
                name="Ruff",
                status="SKIP",
                reason=missing_tool_reason("ruff"),
                files=py_files,
            )
        )

    has_tests = any(path.name.startswith("test_") or path.name.endswith("_test.py") for path in all_paths)
    if run_tests and has_tests and (py_files or config_changed):
        pytest = which_in_project(root, ["pytest"])
        if pytest:
            results.append(run_command("pytest 测试", [pytest, "-q"], root))
        else:
            results.append(
                CheckResult(
                    name="pytest",
                    status="SKIP",
                    reason=missing_tool_reason("pytest"),
                )
            )
    return results


def add_node_checks(root: Path, selected: Sequence[str], run_tests: bool = True) -> list[CheckResult]:
    package = load_package_json(root)
    js_files = [
        path
        for path in selected
        if Path(path).suffix.lower() in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}
    ]
    if not package and not js_files:
        return []

    results: list[CheckResult] = []
    scripts = package.get("scripts", {}) if isinstance(package, dict) else {}
    npm = which_in_project(root, ["npm.cmd", "npm"])
    package_changed = "package.json" in selected
    if npm and ("lint" in scripts and (js_files or package_changed)):
        results.append(run_command("npm lint", [npm, "run", "lint"], root, js_files))
    elif "lint" in scripts and (js_files or package_changed):
        results.append(CheckResult("npm lint", "SKIP", reason=missing_tool_reason("npm")))

    if run_tests and npm and "test" in scripts and (js_files or package_changed):
        results.append(run_command("npm test", [npm, "run", "test", "--if-present"], root, js_files))
    elif run_tests and "test" in scripts and (js_files or package_changed):
        results.append(CheckResult("npm test", "SKIP", reason=missing_tool_reason("npm")))

    npx = which_in_project(root, ["npx.cmd", "npx"])
    if npx and js_files and "lint" not in scripts and package_has_dependency(package, "eslint"):
        results.append(run_command("ESLint", [npx, "--no-install", "eslint", *js_files], root, js_files))
    elif js_files and "lint" not in scripts and package_has_dependency(package, "eslint"):
        results.append(CheckResult("ESLint", "SKIP", reason=missing_tool_reason("npx")))

    if npx and js_files and package_has_dependency(package, "prettier"):
        results.append(run_command("Prettier 格式检查", [npx, "--no-install", "prettier", "--check", *js_files], root, js_files))
    elif js_files and package_has_dependency(package, "prettier"):
        results.append(CheckResult("Prettier", "SKIP", reason=missing_tool_reason("npx")))
    return results


def add_make_checks(root: Path, selected: Sequence[str], run_tests: bool = True) -> list[CheckResult]:
    """只运行 Makefile 中约定俗成的质量目标，不执行任意业务目标。"""
    makefile = root / "Makefile"
    if not makefile.is_file() or not selected:
        return []
    try:
        content = makefile.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [CheckResult("Makefile", "FAIL", reason=f"读取 Makefile 失败：{exc}")]

    targets = set(re.findall(r"^([A-Za-z0-9_.-]+)\s*:", content, flags=re.MULTILINE))
    supported_targets = [
        target for target in ("lint", "check", "test") if target in targets and (run_tests or target != "test")
    ]
    if not supported_targets:
        return []
    make = which_in_project(root, ["make", "gmake"])
    if not make:
        return [CheckResult("Makefile 质量目标", "SKIP", reason=f"发现 lint/check/test 目标，但{missing_tool_reason('make')}")]
    return [run_command(f"make {target}", [make, target], root) for target in supported_targets]


def add_precommit_check(root: Path, selected: Sequence[str], all_mode: bool) -> tuple[list[CheckResult], bool]:
    """优先执行项目声明的 pre-commit；返回结果和是否可用。"""
    config = root / ".pre-commit-config.yaml"
    if not config.is_file() or not selected:
        return [], False
    precommit = which_in_project(root, ["pre-commit"])
    if not precommit:
        return [CheckResult("pre-commit", "SKIP", reason=f"发现 .pre-commit-config.yaml，但{missing_tool_reason('pre-commit')}")], False
    command = [precommit, "run", "--all-files"] if all_mode else [precommit, "run", "--files", *selected]
    return [run_command("pre-commit", command, root, selected)], True


def add_dotnet_checks(
    root: Path,
    selected: Sequence[str],
    all_paths: Sequence[Path],
    run_tests: bool = True,
) -> list[CheckResult]:
    dotnet_selected = any(Path(path).suffix.lower() in {".cs", ".sln", ".csproj"} for path in selected)
    if not dotnet_selected:
        return []
    project_files = sorted(root.glob("*.sln")) or sorted(root.glob("*.csproj"))
    if not project_files and not any(path.suffix.lower() == ".cs" for path in all_paths):
        return []
    dotnet = which_in_project(root, ["dotnet"])
    if not dotnet:
        return [CheckResult(".NET", "SKIP", reason=missing_tool_reason("dotnet"))]
    if not project_files:
        return [CheckResult(".NET", "SKIP", reason="发现 C# 文件，但没有找到 .sln 或 .csproj")]
    target = str(project_files[0].relative_to(root))
    results = [run_command("dotnet format", [dotnet, "format", target, "--verify-no-changes"], root)]
    if run_tests:
        results.append(run_command("dotnet test", [dotnet, "test", target, "--no-restore"], root))
    return results


def add_powershell_checks(root: Path, selected: Sequence[str]) -> list[CheckResult]:
    ps_files = [path for path in selected if Path(path).suffix.lower() in {".ps1", ".psm1", ".psd1"}]
    if not ps_files:
        return []
    shell = which_in_project(root, ["pwsh", "powershell"])
    if not shell:
        return [CheckResult("PSScriptAnalyzer", "SKIP", reason="未找到 PowerShell；请先安装 PowerShell")]
    module_check = subprocess.run(
        [shell, "-NoProfile", "-Command", "if (Get-Module -ListAvailable -Name PSScriptAnalyzer) { exit 0 } else { exit 3 }"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if module_check.returncode != 0:
        return [
            CheckResult(
                "PSScriptAnalyzer",
                "SKIP",
                reason=missing_tool_reason("PSScriptAnalyzer"),
                files=ps_files,
            )
        ]
    paths = ",".join(ps_quote(str(root / path)) for path in ps_files)
    command = [
        shell,
        "-NoProfile",
        "-Command",
        f"$result = Invoke-ScriptAnalyzer -Path @({paths}); $result | Format-Table -AutoSize; if ($result) {{ exit 1 }}",
    ]
    return [run_command("PSScriptAnalyzer", command, root, ps_files)]


def add_shell_checks(root: Path, selected: Sequence[str]) -> list[CheckResult]:
    shell_files = [path for path in selected if Path(path).suffix.lower() in {".sh", ".bash"}]
    if not shell_files:
        return []
    shellcheck = which_in_project(root, ["shellcheck"])
    if not shellcheck:
        return [CheckResult("ShellCheck", "SKIP", reason=missing_tool_reason("shellcheck"), files=shell_files)]
    return [run_command("ShellCheck", [shellcheck, *shell_files], root, shell_files)]


def add_config_checks(root: Path, selected: Sequence[str]) -> list[CheckResult]:
    results: list[CheckResult] = []
    for relative in selected:
        path = root / relative
        if path.suffix.lower() == ".json":
            results.append(run_python_parser("JSON 语法检查", path, root))
        elif path.suffix.lower() == ".toml":
            results.append(run_python_parser("TOML 语法检查", path, root))

    yaml_files = [path for path in selected if Path(path).suffix.lower() in {".yaml", ".yml"}]
    if yaml_files:
        yamllint = which_in_project(root, ["yamllint"])
        if yamllint:
            results.append(run_command("yamllint", [yamllint, *yaml_files], root, yaml_files))
        else:
            results.append(CheckResult("YAML 语法检查", "SKIP", reason=missing_tool_reason("yamllint"), files=yaml_files))

    markdown_files = [path for path in selected if Path(path).suffix.lower() == ".md"]
    if markdown_files:
        markdownlint = which_in_project(root, ["markdownlint-cli2", "markdownlint"])
        if markdownlint:
            results.append(run_command("Markdown lint", [markdownlint, *markdown_files], root, markdown_files))
        else:
            results.append(CheckResult("Markdown lint", "SKIP", reason=missing_tool_reason("markdownlint"), files=markdown_files))
    return results


def result_fingerprint(result: CheckResult, root: Path) -> str:
    """用稳定的检查名称、文件和归一化日志标识一个已知问题。"""
    output = result.output.replace(str(root), "<PROJECT_ROOT>")
    output = re.sub(r"\s+", " ", output).strip()
    payload = "\n".join(
        [result.name, "|".join(result.files), result.reason, output]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_baseline(path: Path) -> set[str]:
    if not path.is_file():
        return set()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取基线文件 {path}: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("entries"), list):
        raise ValueError(f"基线文件格式无效：{path}")
    fingerprints: set[str] = set()
    for entry in document["entries"]:
        if isinstance(entry, dict) and isinstance(entry.get("fingerprint"), str):
            fingerprints.add(entry["fingerprint"])
    return fingerprints


def apply_baseline(results: Sequence[CheckResult], baseline: set[str], root: Path) -> int:
    suppressed = 0
    for result in results:
        if result.status == "FAIL" and result_fingerprint(result, root) in baseline:
            result.status = "BASELINE"
            result.reason = f"已在基线中；原始失败：{result.reason or '无'}"
            suppressed += 1
    return suppressed


def write_baseline(path: Path, results: Sequence[CheckResult], root: Path) -> None:
    entries = []
    for result in results:
        if result.status != "FAIL":
            continue
        entries.append(
            {
                "fingerprint": result_fingerprint(result, root),
                "name": result.name,
                "files": result.files,
                "reason": result.reason,
            }
        )
    document = {
        "version": 1,
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "entries": entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def markdown_report(
    root: Path,
    scope: str,
    types: Sequence[str],
    selected: Sequence[str],
    results: Sequence[CheckResult],
    exit_code: int,
    config: ProjectConfig,
    baseline_path: Path | None,
    baseline_write_path: Path | None,
    suppressed_count: int,
) -> str:
    statuses = ("PASS", "FAIL", "SKIP", "BASELINE", "INFO")
    counts = {status: sum(result.status == status for result in results) for status in statuses}
    lines = [
        "# Check Code v1 检查报告",
        "",
        f"- 项目：`{root}`",
        f"- 检查时间：`{dt.datetime.now().astimezone().isoformat(timespec='seconds')}`",
        f"- 检查范围：`{scope}`",
        f"- 项目类型：{', '.join(types) if types else '未识别'}",
        f"- 文件数量：`{len(selected)}`",
        f"- 统计：通过 `{counts['PASS']}`，失败 `{counts['FAIL']}`，跳过 `{counts['SKIP']}`，基线 `{counts['BASELINE']}`，信息 `{counts['INFO']}`",
        f"- 配置文件：`{config.path}`" if config.path else "- 配置文件：未使用",
        f"- 基线文件：`{baseline_path}`，抑制问题 `{suppressed_count}`" if baseline_path else "- 基线文件：未使用",
        f"- 新生成基线：`{baseline_write_path}`" if baseline_write_path else "- 新生成基线：未生成",
        f"- 最终退出码：`{exit_code}`",
        "",
        "## 检查结果",
        "",
    ]
    if not results:
        lines.append("未发现可执行的检查项。请确认项目类型、改动范围或安装对应检查工具。")
    for result in results:
        lines.extend([f"### `{result.status}` {result.name}"])
        if result.reason:
            lines.append(f"- 说明：{result.reason}")
        if result.files:
            lines.append(f"- 文件：{', '.join(f'`{item}`' for item in result.files[:30])}")
        if result.command:
            lines.extend(["", "```text", result.command, "```"])
        if result.output:
            lines.extend(["", "原始日志：", "", "```text", result.output, "```"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def print_summary(scope: str, types: Sequence[str], results: Sequence[CheckResult], report: Path, exit_code: int) -> None:
    statuses = ("PASS", "FAIL", "SKIP", "BASELINE", "INFO")
    counts = {status: sum(result.status == status for result in results) for status in statuses}
    print("Check Code v1 检查完成")
    print(f"项目类型：{', '.join(types) if types else '未识别'}")
    print(f"检查范围：{scope}")
    print(f"结果统计：通过 {counts['PASS']}，失败 {counts['FAIL']}，跳过 {counts['SKIP']}，基线 {counts['BASELINE']}，信息 {counts['INFO']}")
    for result in results:
        detail = f" - {result.reason}" if result.reason else ""
        print(f"[{result.status}] {result.name}{detail}")
    print(f"报告文件：{report}")
    print(f"退出码：{exit_code}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查常见代码和配置文件，不修改源文件。")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="项目根目录，默认当前目录")
    parser.add_argument("--all", action="store_true", help="检查整个项目，而不是只检查 Git 改动")
    parser.add_argument("--strict", action="store_true", help="缺少检查工具时返回失败")
    parser.add_argument("--report", type=Path, help="Markdown 报告路径")
    parser.add_argument("--baseline", type=Path, help="已有问题基线 JSON 路径")
    parser.add_argument("--write-baseline", type=Path, help="将本次失败问题写入基线 JSON")
    return parser.parse_args()


def main() -> int:
    configure_output()
    args = parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        print(f"错误：项目根目录不存在：{root}", file=sys.stderr)
        return 2

    try:
        config = load_project_config(root)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        print(f"错误：项目配置无效：{exc}", file=sys.stderr)
        return 2

    all_paths = iter_project_files(root, config.exclude)
    all_relative = relative_files(root, all_paths, config.exclude)
    is_git, changed = git_changed_files(root)
    if args.all:
        scope = "全项目 (--all)"
        selected = all_relative
    elif is_git and changed:
        scope = "Git 未提交改动"
        selected = [
            path
            for path in changed
            if not is_excluded(path, config.exclude)
            and (path in all_relative or Path(path).suffix.lower() in SUPPORTED_SUFFIXES)
        ]
    elif is_git:
        scope = "Git 未提交改动（无改动）"
        selected = []
    else:
        scope = "非 Git 目录，自动降级为全项目"
        selected = all_relative

    types = project_types(root, all_paths)
    results: list[CheckResult] = []
    if is_git and not args.all and not changed:
        results.append(CheckResult("Git 状态", "INFO", reason="没有发现待检查的未提交改动"))
    else:
        precommit_files = selected
        if is_git and not args.all and changed:
            precommit_files = [
                path for path in changed if not is_excluded(path, config.exclude)
            ]
        precommit_results, precommit_available = add_precommit_check(root, precommit_files, args.all)
        results.extend(precommit_results)
        results.extend(add_required_tool_checks(root, config))
        results.extend(add_configured_checks(root, selected, config))
        if not precommit_available:
            results.extend(add_python_checks(root, selected, all_paths, config.run_tests))
            results.extend(add_node_checks(root, selected, config.run_tests))
            results.extend(add_make_checks(root, selected, config.run_tests))
            results.extend(add_dotnet_checks(root, selected, all_paths, config.run_tests))
            results.extend(add_powershell_checks(root, selected))
            results.extend(add_shell_checks(root, selected))
            results.extend(add_config_checks(root, selected))
        if not results:
            results.append(CheckResult("可检查内容", "INFO", reason="未发现适用的检查器或匹配文件"))

    baseline_path = None
    baseline_write_path = None
    baseline: set[str] = set()
    try:
        if args.baseline:
            baseline_path = args.baseline if args.baseline.is_absolute() else root / args.baseline
            baseline_path = baseline_path.resolve()
            baseline = load_baseline(baseline_path)
        if args.write_baseline:
            write_path = args.write_baseline if args.write_baseline.is_absolute() else root / args.write_baseline
            baseline_write_path = write_path.resolve()
            write_baseline(baseline_write_path, results, root)
    except (OSError, ValueError) as exc:
        print(f"错误：基线处理失败：{exc}", file=sys.stderr)
        return 2

    suppressed_count = apply_baseline(results, baseline, root) if baseline else 0
    has_failure = any(result.status == "FAIL" for result in results)
    has_skip = any(result.status == "SKIP" for result in results)
    strict = args.strict or config.strict
    exit_code = 1 if has_failure or (strict and has_skip) else 0

    if args.report:
        report = args.report if args.report.is_absolute() else root / args.report
        report = report.resolve()
    else:
        report = root / "work" / "check-code-v1" / f"check-report-{dt.datetime.now():%Y%m%d-%H%M%S}.md"
    try:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            markdown_report(
                root,
                scope,
                types,
                selected,
                results,
                exit_code,
                config,
                baseline_path,
                baseline_write_path,
                suppressed_count,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"错误：无法写入报告：{exc}", file=sys.stderr)
        return 2

    print_summary(scope, types, results, report, exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
