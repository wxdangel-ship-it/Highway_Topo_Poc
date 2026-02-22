import argparse, os, re, json, subprocess, sys, zipfile
from pathlib import Path
from datetime import datetime

def now(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def write_text(p: Path, s: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")

def read_text(p: Path, max_bytes=5_000_000):
    try:
        if p.stat().st_size > max_bytes:
            return None
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

def relpath(p: Path, repo: Path):
    try:
        return str(p.relative_to(repo)).replace("\\","/")
    except Exception:
        return str(p).replace("\\","/")

def redact(s: str):
    s = s.replace("\\","/")
    s = re.sub(r"/mnt/[a-z]/[^ \n\t]*", "<repo_root>/...", s)
    s = re.sub(r"\b[A-Za-z]:/[^\s\n\t]*", "<repo_root>/...", s)
    s = re.sub(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "<internal_ip>", s)
    s = re.sub(r"\b192\.168\.\d{1,3}\.\d{1,3}\b", "<internal_ip>", s)
    s = re.sub(r"\b172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}\b", "<internal_ip>", s)
    s = re.sub(r"\\\\[A-Za-z0-9_.-]+\\[A-Za-z0-9$_.-]+", "<internal_share>", s)
    s = re.sub(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*([^\s]+)", r"\1=<redacted>", s)
    s = re.sub(r"AKIA[0-9A-Z]{16}", "<aws_access_key_redacted>", s)
    return s

def is_text_candidate(p: Path):
    exts = {".py",".md",".txt",".json",".yaml",".yml",".toml",".ini",".cfg",".sh",".cmd",".ps1",".bat"}
    return p.suffix.lower() in exts

def walk_files(repo: Path, exclude_dirnames: set[str]):
    for root, dirs, files in os.walk(repo):
        # prune by dirname
        dirs[:] = [d for d in dirs if d not in exclude_dirnames and not d.startswith(".")]
        rp = Path(root)
        for fn in files:
            yield rp / fn

class IssueBook:
    def __init__(self):
        self.issues = []
        self._seq = 1
    def add(self, severity, dimension, module, path, lines, symbol, summary, impact, recommendation, acceptance, evidence=None):
        iid = f"QA-{self._seq:03d}"
        self._seq += 1
        self.issues.append({
            "id": iid,
            "severity": severity,
            "dimension": dimension,
            "module": module,
            "location": {"path": path, "lines": lines, "symbol": symbol},
            "summary": summary,
            "impact": impact,
            "recommendation": recommendation,
            "acceptance": acceptance,
            "evidence": evidence or []
        })
        return iid

def count_by_sev(issues):
    c = {"Blocker":0,"Major":0,"Minor":0,"Suggestion":0}
    for it in issues:
        c[it["severity"]] = c.get(it["severity"],0) + 1
    return c

def sh(cmd, cwd: Path, log_path: Path, env=None, allow_fail=True):
    p = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    write_text(log_path, p.stdout)
    if p.returncode != 0 and not allow_fail:
        raise RuntimeError(f"Command failed: {cmd}")
    return p.returncode, p.stdout


def parse_git_status(status_text: str):
    items = set()
    for raw in status_text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        if len(line) < 4:
            continue
        state = line[:2]
        path = line[3:].strip().replace("\\", "/")
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        items.add((state, path))
    return items

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    out = Path(args.out).resolve()
    logs = out/"logs"
    inv  = out/"inventory"
    logs.mkdir(parents=True, exist_ok=True)
    inv.mkdir(parents=True, exist_ok=True)

    book = IssueBook()
    checklist = {}

    # Preflight：记录基线 git status，用于区分“既有改动”与“本次运行新增改动”
    _, status_before = sh(["git", "status", "--porcelain"], cwd=repo, log_path=logs/"git_status_before.txt", env=None, allow_fail=True)
    status_before_set = parse_git_status(status_before)

    # exclude dirs (do NOT scan outputs/_work)
    exclude_dirnames = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "outputs",
        "runs",
        "data",
    }
    ignored_module_dirnames = {
        "__pycache__",
        ".pytest_cache",
        ".git",
        "outputs",
        "runs",
        "data",
    }

    def is_module_id_dir(d: Path) -> bool:
        if not d.is_dir():
            return False
        if d.name.startswith("."):
            return False
        if d.name in ignored_module_dirnames:
            return False
        return True
    # 最高优先级文档
    required_docs = [
        "SPEC.md",
        "docs/CODEX_GUARDRAILS.md",
        "docs/AGENT_PLAYBOOK.md",
        "docs/ARTIFACT_PROTOCOL.md",
    ]
    missing = [d for d in required_docs if not (repo/d).exists()]
    if missing:
        checklist["D0-Docs"] = "FAIL"
        book.add(
            "Blocker","D0-Docs","global",
            path=";".join(missing), lines="", symbol="",
            summary="缺少最高优先级护栏文档",
            impact="无法以统一标准审查/验收，且违反项目最高优先级约束",
            recommendation="补齐缺失文档或修正路径；确保 main@HEAD 可定位到这些文件",
            acceptance="required_docs 全部存在且可读",
            evidence=[{"type":"path_check","ref":";".join(missing)}],
        )
    else:
        checklist["D0-Docs"] = "PASS"

    # 模块自动发现：modules/ 与 src/.../modules/ 的并集
    mod_docs_dir = repo/"modules"
    mod_impl_dir = repo/"src"/"highway_topo_poc"/"modules"
    doc_ids = set()
    impl_ids = set()

    if mod_docs_dir.exists():
        for d in mod_docs_dir.iterdir():
            if is_module_id_dir(d):
                doc_ids.add(d.name)
    if mod_impl_dir.exists():
        for d in mod_impl_dir.iterdir():
            if is_module_id_dir(d):
                impl_ids.add(d.name)

    module_ids = sorted(doc_ids.union(impl_ids))
    write_text(inv/"module_ids.json", json.dumps({
        "doc_ids": sorted(doc_ids),
        "impl_ids": sorted(impl_ids),
        "module_ids": module_ids
    }, ensure_ascii=False, indent=2))

    # 范围 tree（轻量，避免过大）
    # 仅列 top-level + 关键目录
    tree_lines = []
    for p in ["SPEC.md","docs","modules","src/highway_topo_poc/modules","tests","tools","scripts"]:
        tree_lines.append(p + ("" if (repo/p).exists() else "  [MISSING]"))
    write_text(inv/"tree_scope.txt", "\n".join(tree_lines) + "\n")

    # 目录规则与契约强制
    contract_index = {}
    entry_index = {}

    for mid in module_ids:
        mod = mid
        doc_dir = repo/"modules"/mid
        impl_dir = repo/"src"/"highway_topo_poc"/"modules"/mid

        # D0: modules/<id> 不应包含 .py
        if doc_dir.exists():
            py_in_doc = list(doc_dir.rglob("*.py"))
            if py_in_doc:
                checklist[f"D0-DirDocNoPy-{mid}"] = "FAIL"
                hits = [relpath(p, repo) for p in py_in_doc[:50]]
                book.add(
                    "Blocker","D0-DirDocNoPy",mod,
                    path=relpath(doc_dir, repo), lines="", symbol="",
                    summary="modules/<id>/ 下发现 .py（违反方案A：modules 只放文档契约）",
                    impact="契约与实现混杂会导致接口漂移、协作困难、审查门禁不稳定",
                    recommendation="将实现代码迁移到 src/highway_topo_poc/modules/<id>/；modules/<id> 仅保留文档",
                    acceptance="modules/<id>/ 下不再出现 .py",
                    evidence=[{"type":"file_list","ref":";".join(hits)}],
                )
            else:
                checklist[f"D0-DirDocNoPy-{mid}"] = "PASS"
        else:
            checklist[f"D0-DocDirExist-{mid}"] = "FAIL"
            book.add(
                "Major","D0-DocDirExist",mod,
                path=relpath(doc_dir, repo), lines="", symbol="",
                summary="缺少 modules/<id>/ 文档契约目录",
                impact="模块契约无法强制，影响内外网协作交付与自动化门禁",
                recommendation="为每个实现模块补齐 modules/<id>/ 并放置契约文档",
                acceptance="modules/<id>/ 存在且包含 INTERFACE_CONTRACT.md",
                evidence=[{"type":"path_check","ref":relpath(doc_dir, repo)}],
            )

        # D0: 实现目录存在性
        if impl_dir.exists():
            checklist[f"D0-ImplDirExist-{mid}"] = "PASS"
            # __init__.py 建议（不是强制 blocker，但缺失会影响 import）
            if not (impl_dir/"__init__.py").exists():
                checklist[f"D3-InitPy-{mid}"] = "FAIL"
                book.add(
                    "Major","D3-InitPy",mod,
                    path=relpath(impl_dir, repo), lines="", symbol="",
                    summary="实现模块目录缺少 __init__.py",
                    impact="可能导致包导入/模块发现失败，影响可维护性与运行一致性",
                    recommendation="补齐 __init__.py（最小改动）",
                    acceptance="__init__.py 存在且 import 路径稳定",
                )
            else:
                checklist[f"D3-InitPy-{mid}"] = "PASS"
        else:
            checklist[f"D0-ImplDirExist-{mid}"] = "FAIL"
            book.add(
                "Major","D0-ImplDirExist",mod,
                path=relpath(impl_dir, repo), lines="", symbol="",
                summary="缺少 src/highway_topo_poc/modules/<id>/ 实现目录",
                impact="模块实现不可定位，无法进行代码审查与复现验证",
                recommendation="确认实现目录是否被放在其他位置，统一迁移回方案A规定路径",
                acceptance="实现目录存在且包含核心实现代码",
                evidence=[{"type":"path_check","ref":relpath(impl_dir, repo)}],
            )

        # D1: 契约强制（必须 INTERFACE_CONTRACT.md）
        contract_path = doc_dir/"INTERFACE_CONTRACT.md"
        contract_index[mid] = relpath(contract_path, repo) if contract_path.exists() else None
        if doc_dir.exists() and not contract_path.exists():
            checklist[f"D1-Contract-{mid}"] = "FAIL"
            book.add(
                "Blocker","D1-Contract",mod,
                path=relpath(doc_dir, repo), lines="", symbol="",
                summary="缺少 INTERFACE_CONTRACT.md（模块契约强制）",
                impact="接口/输入输出/验收口径不可对齐，无法支撑内外网协作交付",
                recommendation="在 modules/<id>/ 补齐 INTERFACE_CONTRACT.md，至少包含：输入/输出/入口/参数/示例/验收",
                acceptance="INTERFACE_CONTRACT.md 存在且章节齐全，并与实现一致",
                evidence=[{"type":"path_check","ref":relpath(contract_path, repo)}],
            )
        elif contract_path.exists():
            # 章节检查
            txt = read_text(contract_path) or ""
            lower = txt.lower()
            required_sections = [
                ("输入","input"),
                ("输出","output"),
                ("入口","entrypoint"),
                ("参数","parameter"),
                ("示例","example"),
                ("验收","accept"),
            ]
            missing_sec = []
            for zh,en in required_sections:
                if (zh not in txt) and (en not in lower):
                    missing_sec.append(f"{zh}/{en}")
            if missing_sec:
                checklist[f"D1-Contract-Sections-{mid}"] = "FAIL"
                book.add(
                    "Major","D1-Contract-Sections",mod,
                    path=relpath(contract_path, repo), lines="", symbol="",
                    summary="INTERFACE_CONTRACT.md 缺少必需章节",
                    impact="契约不可执行，协作/验收门禁不完整",
                    recommendation="补齐缺失章节，确保示例可运行且产物符合 ARTIFACT_PROTOCOL",
                    acceptance="章节齐全；示例命令可复现；产物可被下游消费",
                    evidence=[{"type":"missing_sections","ref":",".join(missing_sec)}],
                )
            else:
                checklist[f"D1-Contract-Sections-{mid}"] = "PASS"

            # 入口弱提取（可选）：从契约中抓取 scripts/ 或 python -m 的字样
            entry = []
            for line in txt.splitlines():
                if "scripts/" in line or "python -m" in line or "pytest" in line:
                    entry.append(line.strip()[:200])
            entry_index[mid] = entry[:20]

    write_text(inv/"contracts_index.json", json.dumps(contract_index, ensure_ascii=False, indent=2))
    write_text(inv/"entrypoints_index.json", json.dumps(entry_index, ensure_ascii=False, indent=2))

    # D2/D7 扫描：legacy-div 命名 / vector关键词 / 内网 / 绝对路径 / secret / 风险代码
    legacy_div_hits = []
    vec_hits = {"DivStripZone":0, "Node":0, "intersection_l":0}
    net_hits, path_hits, secret_hits = [], [], []
    risk_hits = []

    legacy_div_token = "gore" + "area"
    re_legacy_div = re.compile(rf"\b{legacy_div_token}\b|\bgore_area\b", re.IGNORECASE)
    re_div  = re.compile(r"\bDivStripZone\b")
    re_node = re.compile(r"\bNode\b")
    re_inter= re.compile(r"\bintersection_l\b")

    re_priv_ip = re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b|\b192\.168\.\d{1,3}\.\d{1,3}\b|\b172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}\b")
    re_unc = re.compile(r"\\\\[A-Za-z0-9_.-]+\\[A-Za-z0-9$_.-]+")
    re_abs_win = re.compile(r"\b[A-Za-z]:\\")
    re_abs_wsl = re.compile(r"/mnt/[a-z]/")
    re_secret = re.compile(
        r"AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|-----BEGIN (RSA|OPENSSH|EC) PRIVATE KEY-----|\b(api[_-]?key|secret|token|password)\b\s*[:=]\s*(\"[^\"]{8,}\"|'[^']{8,}')",
        re.IGNORECASE,
    )
    re_bare_except = re.compile(r"^\s*except\s*:\s*$")
    re_eval_exec = re.compile(r"\b(eval|exec)\s*\(")

    def should_skip(p: Path):
        rp = relpath(p, repo)
        if rp.startswith("outputs/_work/"):
            return True
        return False

    for p in walk_files(repo, exclude_dirnames):
        if should_skip(p): 
            continue
        if not is_text_candidate(p):
            continue
        txt = read_text(p)
        if txt is None:
            continue
        rp = relpath(p, repo)
        for i, line in enumerate(txt.splitlines(), start=1):
            ln = line.rstrip("\n")
            if re_legacy_div.search(ln):
                legacy_div_hits.append((rp, i, ln.strip()[:200]))
            if re_div.search(ln): vec_hits["DivStripZone"] += 1
            if re_node.search(ln): vec_hits["Node"] += 1
            if re_inter.search(ln): vec_hits["intersection_l"] += 1

            if re_priv_ip.search(ln) or re_unc.search(ln):
                net_hits.append((rp, i, ln.strip()[:200]))
            if re_abs_win.search(ln) or re_abs_wsl.search(ln):
                path_hits.append((rp, i, ln.strip()[:200]))
            if re_secret.search(ln):
                secret_hits.append((rp, i, "<redacted>"))

            # 风险模式：bare except / eval|exec
            if p.suffix.lower() == ".py":
                if re_bare_except.match(ln):
                    risk_hits.append((rp, i, "bare except"))
                if re_eval_exec.search(ln):
                    risk_hits.append((rp, i, "eval/exec call"))

    write_text(logs/"scan_legacy_div.txt", "\n".join([f"{a}:L{b} {c}" for a,b,c in legacy_div_hits]) or "(no hits)")
    write_text(logs/"scan_vector_keywords.json", json.dumps(vec_hits, ensure_ascii=False, indent=2))
    write_text(logs/"scan_network_risk.txt", "\n".join([f"{a}:L{b} {c}" for a,b,c in net_hits]) or "(no hits)")
    write_text(logs/"scan_path_portability.txt", "\n".join([f"{a}:L{b} {c}" for a,b,c in path_hits]) or "(no hits)")
    write_text(logs/"scan_secret_risk.txt", "\n".join([f"{a}:L{b} {c}" for a,b,c in secret_hits]) or "(no hits)")
    write_text(logs/"scan_code_risk.txt", "\n".join([f"{a}:L{b} {c}" for a,b,c in risk_hits]) or "(no hits)")

    # legacy-div naming：Major（若命中在产物 schema/关键写出逻辑，后续人工可升 Blocker）
    if legacy_div_hits:
        checklist["D2-legacy-div"] = "FAIL"
        book.add(
            "Major","D2-legacy-div","global",
            path="multiple", lines="", symbol="keyword_scan",
            summary="发现旧版导流带命名（标准要求移除）",
            impact="违反最新 Patch Vector 标准；下游消费可能失败或产生歧义",
            recommendation="从 SPEC/契约/实现中移除旧命名；统一迁移到 DivStripZone/Node/intersection_l（不保留兼容别名）",
            acceptance="全仓旧命名命中为 0；产物 schema 不再出现旧命名",
            evidence=[{"type":"log","ref":"logs/scan_legacy_div.txt"}],
        )
    else:
        checklist["D2-legacy-div"] = "PASS"

    # Vector 关键词弱校验
    if any(v == 0 for v in vec_hits.values()):
        checklist["D2-VectorKeywords"] = "FAIL"
        book.add(
            "Major","D2-VectorKeywords","global",
            path="(repo scan)", lines="", symbol="keyword_scan",
            summary="Vector 标准关键词出现不完整（弱信号）",
            impact="可能存在契约/实现未对齐最新 Vector 图层标准",
            recommendation="确认并统一使用 DivStripZone/Node/intersection_l 的命名与写出；更新契约示例",
            acceptance="三项关键词均出现；更强门禁可用产物/manifest 实测验证",
            evidence=[{"type":"log","ref":"logs/scan_vector_keywords.json"}],
        )
    else:
        checklist["D2-VectorKeywords"] = "PASS"

    # Secrets：Blocker
    if secret_hits:
        checklist["D7-Secrets"] = "FAIL"
        book.add(
            "Blocker","D7-Secrets","global",
            path="multiple", lines="", symbol="secret_scan",
            summary="疑似敏感信息命中（token/key/password/private key）",
            impact="对外协作与合规风险极高，可能造成泄露",
            recommendation="移出仓库并改为 env/config 注入；必要时进行历史泄露处置（本次仅记录）",
            acceptance="secret 扫描命中为 0；external 报告不包含敏感值",
            evidence=[{"type":"log","ref":"logs/scan_secret_risk.txt"}],
        )
    else:
        checklist["D7-Secrets"] = "PASS"

    # 内网依赖：Major
    if net_hits:
        checklist["D7-InternalNet"] = "FAIL"
        book.add(
            "Major","D7-InternalNet","global",
            path="multiple", lines="", symbol="net_scan",
            summary="发现疑似内网依赖（私网IP/UNC/内网资源）",
            impact="外网/隔离环境不可复现，协作交付风险高",
            recommendation="将内网资源改为可配置（env/config），并提供离线替代与文档说明",
            acceptance="外部协作环境可运行；内网依赖可通过配置替换",
            evidence=[{"type":"log","ref":"logs/scan_network_risk.txt"}],
        )
    else:
        checklist["D7-InternalNet"] = "PASS"

    # 绝对路径：Minor（多发生在文档示例，可后续变量化）
    if path_hits:
        checklist["D7-AbsPath"] = "FAIL"
        book.add(
            "Minor","D7-AbsPath","global",
            path="multiple", lines="", symbol="path_scan",
            summary="发现绝对路径硬编码（Windows盘符/WSL /mnt）",
            impact="跨机器/跨网协作可移植性差，易引发跑不通",
            recommendation="统一改为相对路径 + repo_root/data_root 注入（env/config）；external 文档用变量表达",
            acceptance="协作方在不同路径可运行；路径由配置注入",
            evidence=[{"type":"log","ref":"logs/scan_path_portability.txt"}],
        )
    else:
        checklist["D7-AbsPath"] = "PASS"

    # 风险代码：Minor/Major（按命中内容人工升降级）
    if risk_hits:
        checklist["D3-CodeRisk"] = "FAIL"
        book.add(
            "Minor","D3-CodeRisk","global",
            path="multiple", lines="", symbol="risk_scan",
            summary="发现潜在风险代码模式（bare except / eval/exec）",
            impact="可能导致错误被吞、可维护性与安全性下降",
            recommendation="逐条复核并替换为显式异常类型与日志；避免 eval/exec",
            acceptance="风险模式扫描命中清零或有合理豁免说明",
            evidence=[{"type":"log","ref":"logs/scan_code_risk.txt"}],
        )
    else:
        checklist["D3-CodeRisk"] = "PASS"

    # D5: pytest + smoke
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPYCACHEPREFIX"] = str(out/"pycache")
    env["PYTHONUTF8"] = "1"

    rc_pytest, _ = sh(
        [sys.executable, "-m", "pytest", "-q",
         "-o", f"cache_dir={str(out/'.pytest_cache')}",
         "--basetemp", str(out/"pytest_tmp")],
        cwd=repo, log_path=logs/"pytest.txt", env=env, allow_fail=True
    )
    if rc_pytest != 0:
        checklist["D5-pytest"] = "FAIL"
        book.add(
            "Blocker","D5-pytest","global",
            path="tests/", lines="", symbol="pytest",
            summary="pytest 未通过（main@HEAD 不满足最小门禁）",
            impact="基线不可用，影响持续协作与后续模块推进",
            recommendation="优先修复失败用例（先护栏/再功能），确保隔离环境可通过",
            acceptance="pytest -q 全量通过",
            evidence=[{"type":"log","ref":"logs/pytest.txt"}],
        )
    else:
        checklist["D5-pytest"] = "PASS"

    # smoke marker 检测
    smoke_available = False
    tests_dir = repo/"tests"
    if tests_dir.exists():
        for p in tests_dir.rglob("*.py"):
            t = read_text(p, max_bytes=2_000_000) or ""
            if "pytest.mark.smoke" in t:
                smoke_available = True
                break
    if smoke_available:
        rc_smoke, _ = sh(
            [sys.executable, "-m", "pytest", "-q", "-m", "smoke",
             "-o", f"cache_dir={str(out/'.pytest_cache_smoke')}",
             "--basetemp", str(out/"pytest_tmp_smoke")],
            cwd=repo, log_path=logs/"smoke_pytest.txt", env=env, allow_fail=True
        )
        if rc_smoke != 0:
            checklist["D5-smoke"] = "FAIL"
            book.add(
                "Major","D5-smoke","global",
                path="tests/", lines="", symbol="pytest -m smoke",
                summary="smoke 测试存在但未通过",
                impact="最小闭环不稳定，外部协作/CI 门禁风险高",
                recommendation="修复 smoke 用例与其最小依赖，确保稳定通过且耗时可控",
                acceptance="pytest -q -m smoke 通过",
                evidence=[{"type":"log","ref":"logs/smoke_pytest.txt"}],
            )
        else:
            checklist["D5-smoke"] = "PASS"
    else:
        write_text(logs/"smoke_pytest.txt", "(no pytest.mark.smoke found; smoke not executed)")
        checklist["D5-smoke"] = "FAIL"
        book.add(
            "Major","D5-smoke","global",
            path="tests/", lines="", symbol="smoke_missing",
            summary="未发现 pytest.mark.smoke（最小闭环门禁缺失）",
            impact="缺少最小闭环验证，不利于内外网协作与持续集成",
            recommendation="为关键模块补最小 smoke：小数据、可复现、只写 outputs/_work",
            acceptance="存在 smoke 用例且 pytest -m smoke 可通过",
            evidence=[{"type":"log","ref":"logs/smoke_pytest.txt"}],
        )

    # Postflight：只检查“本次运行新增”的非 outputs/_work 改动
    rc, status_after = sh(["git","status","--porcelain"], cwd=repo, log_path=logs/"git_status_after.txt", env=env, allow_fail=True)
    _ = rc
    status_after_set = parse_git_status(status_after)
    new_items = sorted(status_after_set - status_before_set)
    bad = [f"{state} {path}" for state, path in new_items if not path.startswith("outputs/_work/")]
    if bad:
        checklist["D0-GitClean"] = "FAIL"
        book.add(
            "Blocker","D0-GitClean","global",
            path="(git status)", lines="", symbol="git_status",
            summary="运行新增了 outputs/_work 之外的改动（违反不污染约束）",
            impact="会污染仓库与协作基线，导致不可控副作用",
            recommendation="定位产生文件的命令并改为写入 outputs/_work；必要时调整 pytest cache/basetemp",
            acceptance="相对运行前基线，git status --porcelain 仅新增 outputs/_work 下条目",
            evidence=[{"type":"log","ref":"logs/git_status_after.txt"}, {"type":"bad_lines","ref":";".join(bad[:50])}],
        )
    else:
        checklist["D0-GitClean"] = "PASS"

    # 输出 checklist / issues / reports
    issues = book.issues
    sev = {"Blocker":0,"Major":0,"Minor":0,"Suggestion":0}
    for it in issues:
        sev[it["severity"]] = sev.get(it["severity"],0) + 1

    ck_lines = ["# QA_CHECKLIST", "", f"- time: {now()}", f"- repo: {repo}", ""]
    for k in sorted(checklist.keys()):
        ck_lines.append(f"- {k}: **{checklist[k]}**")
    write_text(out/"QA_CHECKLIST.md", "\n".join(ck_lines) + "\n")

    write_text(out/"QA_ISSUES.json", json.dumps(issues, ensure_ascii=False, indent=2))

    def issues_md(redacted=False):
        head = [
            "# QA_REPORT",
            "",
            f"- time: {now()}",
            f"- repo: {repo if not redacted else '<repo_root>'}",
            f"- modules(auto): {', '.join(module_ids)}",
            "",
            "## Summary",
            f"- Blocker: {sev['Blocker']}",
            f"- Major: {sev['Major']}",
            f"- Minor: {sev['Minor']}",
            f"- Suggestion: {sev['Suggestion']}",
            "",
            "## Issues",
        ]
        lines = head[:]
        for it in issues:
            loc = it["location"]
            p = loc["path"]
            if redacted:
                p = redact(p)
            lines += [
                "",
                f"### {it['id']} | {it['severity']} | {it['dimension']} | {it['module']}",
                f"- location: `{p}` {loc['lines']} {loc['symbol']}",
                f"- summary: {redact(it['summary']) if redacted else it['summary']}",
                f"- impact: {redact(it['impact']) if redacted else it['impact']}",
                f"- recommendation: {redact(it['recommendation']) if redacted else it['recommendation']}",
                f"- acceptance: {redact(it['acceptance']) if redacted else it['acceptance']}",
            ]
            if it.get("evidence"):
                evs = []
                for e in it["evidence"]:
                    evs.append(f"  - {e.get('type')}: {redact(e.get('ref','')) if redacted else e.get('ref','')}")
                lines += ["- evidence:", *evs]
        lines += [
            "",
            "## Inventory",
            "- inventory/module_ids.json",
            "- inventory/contracts_index.json",
            "- inventory/entrypoints_index.json",
            "",
            "## Logs",
            "- logs/pytest.txt",
            "- logs/smoke_pytest.txt",
            "- logs/scan_secret_risk.txt",
            "- logs/scan_legacy_div.txt",
            "- logs/git_status_before.txt / git_status_after.txt",
        ]
        return "\n".join(lines) + "\n"

    write_text(out/"QA_REPORT_INTERNAL.md", issues_md(redacted=False))
    write_text(out/"QA_REPORT_EXTERNAL.md", issues_md(redacted=True))

    # external bundle zip（可选，默认生成）
    zpath = out/"QA_BUNDLE_EXTERNAL.zip"
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fn in ["QA_REPORT_EXTERNAL.md", "QA_ISSUES.json", "QA_CHECKLIST.md"]:
            zf.write(out/fn, arcname=fn)
        for fn in ["logs/pytest.txt","logs/smoke_pytest.txt","logs/scan_secret_risk.txt","logs/scan_legacy_div.txt","logs/scan_network_risk.txt","logs/scan_path_portability.txt","logs/scan_code_risk.txt","logs/scan_vector_keywords.json"]:
            p = out/fn
            if p.exists():
                zf.write(p, arcname=fn)

    print("QA DONE")
    print(f"OUT={out}")

if __name__ == "__main__":
    main()
