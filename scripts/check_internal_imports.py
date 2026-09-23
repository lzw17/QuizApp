# -*- coding: utf-8 -*-
"""后端内部导入一致性自检（不需要装任何依赖，纯 AST）。

用途：重构/搬运函数后，快速确认没有留下悬空引用。比"跑起来才发现 ImportError"更早一步，
也是 ssh_sync.py push 之前值得跑一遍的静态门禁。

用法：
    python scripts/check_internal_imports.py
退出码 0 = 无问题，1 = 有悬空引用。
"""
import ast
import os
import sys

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
BACKEND = os.path.abspath(BACKEND)
SKIP_DIRS = {"__pycache__", ".git", "venv", ".venv"}


def module_name(rel_path: str) -> str:
    rel = rel_path.replace(os.sep, "/")
    if rel.endswith("/__init__.py"):
        return rel[: -len("/__init__.py")].replace("/", ".")
    if rel == "__init__.py":
        return ""
    return rel[:-3].replace("/", ".")


def collect():
    """返回 {模块名: 顶层名字集合} 与 {模块名: 文件路径}"""
    defined, paths = {}, {}
    for dirpath, dirnames, filenames in os.walk(BACKEND):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, BACKEND)
            mod = module_name(rel)
            paths[mod] = full
            names = set()
            try:
                tree = ast.parse(open(full, encoding="utf-8").read(), filename=full)
            except SyntaxError as exc:
                print("[语法错误] %s: %s" % (rel, exc))
                continue
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    names.add(node.name)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            names.add(target.id)
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    names.add(node.target.id)
                elif isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        names.add(alias.asname or alias.name.split(".")[0])
            defined[mod] = names
    # 包内的子模块本身也算可导入的名字（如 from .models import question）
    for mod in list(defined):
        if "." in mod:
            package, _, child = mod.rpartition(".")
            defined.setdefault(package, set()).add(child)
    return defined, paths


def main():
    defined, paths = collect()
    problems = []
    for mod, full in sorted(paths.items()):
        try:
            tree = ast.parse(open(full, encoding="utf-8").read(), filename=full)
        except SyntaxError:
            continue
        parts = mod.split(".") if mod else []
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.level == 0:
                target = node.module or ""
            else:
                base = parts[: len(parts) - node.level] if len(parts) >= node.level else []
                target = ".".join(base + ([node.module] if node.module else []))
            if target not in defined:
                continue  # 第三方库或项目外模块，不检查
            for alias in node.names:
                if alias.name != "*" and alias.name not in defined[target]:
                    problems.append(
                        "%s:%d  从 %s 导入了不存在的 %s"
                        % (mod.replace(".", "/") + ".py", node.lineno, target, alias.name)
                    )

    print("扫描模块 %d 个" % len(paths))
    if problems:
        print("\n发现 %d 处悬空引用：" % len(problems))
        for problem in problems:
            print("  [x] " + problem)
        sys.exit(1)
    print("[ok] 项目内所有 import 的名字都能解析到，无悬空引用")


if __name__ == "__main__":
    main()
