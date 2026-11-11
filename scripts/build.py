#!/usr/bin/env python3
"""把 rules/*.list 里的域名规则编译成 mihomo 的 .mrs 规则集。

用法：
    python scripts/build.py                  # 编译全部 rules/*.list
    python scripts/build.py proxy direct     # 只编译指定的几个
    python scripts/build.py --download-mihomo   # 先自动下载 mihomo 再编译
    python scripts/build.py --only-fetch        # 只下载 mihomo，不编译

规则写法（每行一条，空行和 # 注释会被忽略）：
    example.com         -> +.example.com   后缀匹配（域名本身 + 所有子域名）
    +.example.com       -> +.example.com   同上，显式写法
    .example.com        -> .example.com    只匹配子域名，不含 example.com 本身
    *.example.com       -> *.example.com   只匹配一级子域名
    =example.com        -> example.com     精确匹配，只匹配 example.com
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = ROOT / "rules"
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
BIN_DIR = ROOT / "bin"

RELEASE_API = "https://api.github.com/repos/MetaCubeX/mihomo/releases/latest"
UA = {"User-Agent": "mihomo-mrs-rules-builder"}

# 域名允许出现的字符：字母数字、连字符、点、通配符
VALID_DOMAIN = re.compile(r"^[a-z0-9*+._-]+$")


# --------------------------------------------------------------------------- #
# mihomo 可执行文件
# --------------------------------------------------------------------------- #
def exe_name() -> str:
    return "mihomo.exe" if os.name == "nt" else "mihomo"


def find_mihomo() -> Path | None:
    """按 环境变量 -> bin/ -> PATH 的顺序找 mihomo。"""
    env = os.environ.get("MIHOMO_BIN")
    if env:
        p = Path(env)
        if p.is_file():
            return p
    local = BIN_DIR / exe_name()
    if local.is_file():
        return local
    found = shutil.which("mihomo")
    return Path(found) if found else None


def _asset_keyword() -> str:
    sysname = platform.system().lower()
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
    if sysname == "windows":
        return f"windows-{arch}-compatible"
    if sysname == "darwin":
        return f"darwin-{arch}"
    return f"linux-{arch}-compatible"


def download_mihomo() -> Path:
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    target = BIN_DIR / exe_name()
    if target.is_file():
        print(f"[mihomo] 已存在：{target}")
        return target

    print("[mihomo] 查询最新版本 ...")
    req = urllib.request.Request(RELEASE_API, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as resp:
        release = json.load(resp)

    keyword = _asset_keyword()
    asset = next(
        (a for a in release["assets"]
         if keyword in a["name"] and a["name"].endswith((".gz", ".zip"))),
        None,
    )
    if asset is None:
        sys.exit(f"[mihomo] 没找到匹配 {keyword} 的发布文件，请手动下载并放到 {target}")

    print(f"[mihomo] 下载 {asset['name']} ({release['tag_name']}) ...")
    req = urllib.request.Request(asset["browser_download_url"], headers=UA)
    with urllib.request.urlopen(req, timeout=300) as resp:
        blob = resp.read()

    if asset["name"].endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            member = next(
                (n for n in zf.namelist()
                 if n.lower().endswith(".exe") or "/mihomo" in n or n == "mihomo"),
                zf.namelist()[0],
            )
            target.write_bytes(zf.read(member))
    else:
        target.write_bytes(gzip.decompress(blob))

    target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"[mihomo] 就绪：{target}（{target.stat().st_size // 1024} KB）")
    return target


# --------------------------------------------------------------------------- #
# 规则解析
# --------------------------------------------------------------------------- #
def normalize(raw: str) -> tuple[str, str] | None:
    """把一行源码规则规范化为 mihomo 认识的写法，返回 (规则, 匹配方式)。"""
    line = raw.split("#", 1)[0].strip()
    if not line:
        return None

    # 带逗号且首段全大写的是 classical 路由规则（DOMAIN-SUFFIX,x / SUB-RULE,(..),y）。
    # 这类规则不能进 behavior=domain 的规则集，mihomo 会直接拒绝。
    probe = re.sub(r"^[-+]\s*", "", line)          # 容忍从 YAML 列表里连带 "- " 一起粘过来
    head = probe.split(",", 1)[0].strip().upper()
    if "," in probe and re.fullmatch(r"[A-Z][A-Z0-9-]*", head):
        raise ValueError(
            f"{raw.strip()!r} 是 classical 路由规则，不能放进 domain 规则集。"
            f"SUB-RULE 只能写在 config.yaml 顶层的 rules: 里（见 snippets/emby.rules.yaml）"
        )

    line = line.lower()
    if any(ch.isspace() for ch in line):
        # 域名中间不可能有空格，几乎都是手滑，宁可报错也不要生成垃圾规则
        raise ValueError(f"域名中含有空白字符：{raw.strip()!r}")

    mode = "suffix"
    if line.startswith("="):
        line, mode = line[1:], "exact"
    elif line.startswith("+."):
        return (line, "suffix")
    elif line.startswith("."):
        return (line, "sub-only")
    elif line.startswith("*."):
        return (line, "wildcard")

    if not VALID_DOMAIN.match(line) or "/" in line:
        raise ValueError(f"无效的域名：{raw.strip()!r}")

    if mode == "exact":
        return (line, "exact")
    return (f"+.{line}", "suffix")


def compile_list(name: str) -> dict:
    src = RULES_DIR / f"{name}.list"
    seen: dict[str, str] = {}
    skipped: list[str] = []

    for lineno, raw in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
        try:
            item = normalize(raw)
        except ValueError as exc:
            skipped.append(f"  第 {lineno} 行：{exc}")
            continue
        if item is None:
            continue
        rule, mode = item
        seen.setdefault(rule, mode)

    if not seen:
        raise SystemExit(f"[{name}] 没有解析出任何有效规则")

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    out = BUILD_DIR / f"{name}.txt"
    # 显式 newline="\n"，避免 Windows 上写出 CRLF 让 git 一直显示已修改
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(sorted(seen)) + "\n")
    return {"name": name, "count": len(seen), "modes": seen, "skipped": skipped, "text": out}


def convert(mihomo: Path, name: str) -> Path:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    src = BUILD_DIR / f"{name}.txt"
    dst = DIST_DIR / f"{name}.mrs"
    proc = subprocess.run(
        [str(mihomo), "convert-ruleset", "domain", "text", str(src), str(dst)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not dst.is_file():
        sys.exit(f"[{name}] 转换失败：\n{proc.stdout}\n{proc.stderr}")
    return dst


def summarize(result: dict, dst: Path) -> None:
    modes: dict[str, int] = {}
    for mode in result["modes"].values():
        modes[mode] = modes.get(mode, 0) + 1
    detail = "、".join(f"{k} {v}" for k, v in sorted(modes.items()))
    size = dst.stat().st_size
    print(f"  {result['name']:<12} {result['count']:>5} 条  {size:>7} B   ({detail})")


def main() -> None:
    ap = argparse.ArgumentParser(description="把 rules/*.list 编译成 dist/*.mrs")
    ap.add_argument("names", nargs="*", help="只编译指定的列表名（默认全部）")
    ap.add_argument("--download-mihomo", action="store_true", help="缺少 mihomo 时自动下载")
    ap.add_argument("--only-fetch", action="store_true", help="只下载 mihomo，不编译")
    args = ap.parse_args()

    mihomo = find_mihomo()
    if mihomo is None and (args.download_mihomo or args.only_fetch):
        mihomo = download_mihomo()
    if args.only_fetch:
        return
    if mihomo is None:
        sys.exit(
            "找不到 mihomo 可执行文件。\n"
            "  方式一：python scripts/build.py --download-mihomo\n"
            "  方式二：把 mihomo 放到 bin/ 目录，或设置环境变量 MIHOMO_BIN"
        )

    names = args.names or sorted(p.stem for p in RULES_DIR.glob("*.list"))
    if not names:
        sys.exit("rules/ 下没有找到任何 .list 文件")

    print(f"[mihomo] {mihomo}")

    # 先把所有清单解析完，有任何一行不合法就整体失败：
    # 静默丢弃一条规则 = 某个站点悄悄不走代理，比直接报错难查得多。
    print("[build] 解析规则 ...")
    results = [compile_list(name) for name in names]
    problems = [(r["name"], line) for r in results for line in r["skipped"]]
    if problems:
        print("[build] 解析失败，以下规则有问题：", file=sys.stderr)
        for name, line in problems:
            print(f"  rules/{name}.list {line}", file=sys.stderr)
        sys.exit(1)

    print("[build] 编译中 ...")
    for result in results:
        dst = convert(mihomo, result["name"])
        summarize(result, dst)
    print(f"[build] 完成，产物在 {DIST_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
