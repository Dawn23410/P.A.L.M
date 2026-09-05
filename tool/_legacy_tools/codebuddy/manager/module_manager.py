"""
P.A.L.M · 模块管理器核心
=========================
模块包全生命周期管理：解包、验证、安装、启动、停止、卸载。
严格遵循 MODULE_PACKAGE_SPEC.md 规范。
"""

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import py7zr

# ─── 路径常量 ────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKAGES_DIR = PROJECT_ROOT / "packages"
MODULES_DIR = PROJECT_ROOT / "modules"
MANAGER_DIR = PROJECT_ROOT / "manager"

# ─── 数据模型 ────────────────────────────────────────────────────

REQUIRED_MANIFEST_FIELDS = ["module", "version", "type", "description", "entry"]
OPTIONAL_MANIFEST_GROUPS = ["dependencies", "config", "deploy", "author"]

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


@dataclass
class ModuleInfo:
    """模块元数据（从 MANIFEST.json 解析）"""
    module: str = ""
    version: str = ""
    type: str = ""
    description: str = ""
    author: str = ""
    entry: str = ""
    dependencies: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)
    deploy: dict = field(default_factory=dict)


@dataclass
class ModuleState:
    """模块运行时状态"""
    module: str
    version: str
    path: str               # 模块目录的绝对路径
    manifest: dict          # 原始 MANIFEST.json
    status: str = "stopped" # stopped | running | error
    pid: Optional[int] = None
    port: Optional[int] = None
    started_at: Optional[str] = None
    error: str = ""


# ─── 模块管理器 ──────────────────────────────────────────────────

class ModuleManager:
    """模块管理器——单例，管理所有已安装模块的全生命周期"""

    def __init__(self):
        self._modules: dict[str, ModuleState] = {}  # key = module name
        self._processes: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()
        self._scan_modules()

    # ── 扫描已安装模块 ───────────────────────────────────────────

    def _scan_modules(self):
        """启动时扫描 modules/ 目录，加载已安装的模块信息"""
        if not MODULES_DIR.exists():
            return
        for entry in sorted(MODULES_DIR.iterdir()):
            if not entry.is_dir():
                continue
            manifest_path = entry / "MANIFEST.json"
            if not manifest_path.exists():
                continue
            try:
                result = self._validate_manifest(manifest_path)
                if result["valid"]:
                    info = result["info"]
                    state = ModuleState(
                        module=info.module,
                        version=info.version,
                        path=str(entry),
                        manifest=result["raw"],
                        status="stopped",
                    )
                    self._modules[info.module] = state
            except Exception as e:
                print(f"[Manager] 加载失败 {entry.name}: {e}")

    # ── MANIFEST 校验 ────────────────────────────────────────────

    def _validate_manifest(self, manifest_path: Path) -> dict:
        """
        严格校验 MANIFEST.json，依据规范 §3
        返回: {"valid": bool, "info": ModuleInfo|None, "raw": dict|None, "errors": [str]}
        """
        errors = []
        if not manifest_path.exists():
            return {"valid": False, "info": None, "raw": None, "errors": ["未找到 MANIFEST.json"]}

        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return {"valid": False, "info": None, "raw": None, "errors": [f"MANIFEST.json 格式错误: {e}"]}

        if not isinstance(raw, dict):
            return {"valid": False, "info": None, "raw": None, "errors": ["MANIFEST.json 根节点必须是一个对象"]}

        # 检查必需字段
        for field in REQUIRED_MANIFEST_FIELDS:
            if field not in raw or not isinstance(raw[field], str) or not raw[field].strip():
                errors.append(f"缺少必填字段: '{field}'")

        # 检查 version 是否符合 semver
        if "version" in raw and raw["version"]:
            if not SEMVER_RE.match(str(raw["version"])):
                errors.append(f"版本号格式错误: '{raw['version']}' (应为 X.Y.Z)")

        if errors:
            return {"valid": False, "info": None, "raw": raw, "errors": errors}

        # 提取可选组并输出 deprecate 警告
        if "dependencies" in raw and isinstance(raw["dependencies"], dict):
            deps = raw["dependencies"]
            if "runtime" in deps:
                print(f"[Manager] [WARN] 模块 '{raw.get('module')}' 声明了运行时依赖: {deps['runtime']}")
            if "packages" in deps and deps["packages"]:
                print(f"[Manager] [WARN] 模块 '{raw.get('module')}' 声明了包依赖: {deps['packages']}")
                print(f"[Manager] [WARN]   依赖隔离尚未实现，包可能冲突")

        info = ModuleInfo(
            module=str(raw.get("module", "")),
            version=str(raw.get("version", "")),
            type=str(raw.get("type", "")),
            description=str(raw.get("description", "")),
            author=str(raw.get("author", "")),
            entry=str(raw.get("entry", "")),
            dependencies=raw.get("dependencies", {}),
            config=raw.get("config", {}),
            deploy=raw.get("deploy", {}),
        )

        return {"valid": True, "info": info, "raw": raw, "errors": []}

    # ── 列出可用包 (packages/) ──────────────────────────────────

    def list_packages(self) -> list[dict]:
        """列出 packages/ 下的 .7z 文件"""
        if not PACKAGES_DIR.exists():
            return []
        result = []
        for f in sorted(PACKAGES_DIR.iterdir()):
            if f.suffix.lower() == ".7z":
                result.append({
                    "filename": f.name,
                    "size": f.stat().st_size,
                    "modified": f.stat().st_mtime,
                })
        return result

    def delete_package(self, filename: str) -> dict:
        """删除 packages/ 下的 .7z 包文件"""
        package_path = PACKAGES_DIR / filename
        if not package_path.exists():
            return {"success": False, "error": f"包文件 '{filename}' 未找到"}
        if package_path.suffix.lower() != ".7z":
            return {"success": False, "error": "仅支持删除 .7z 文件"}
        try:
            package_path.unlink()
            return {"success": True, "message": f"Package '{filename}' deleted"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ── 安装模块 ─────────────────────────────────────────────────

    def install(self, filename: str) -> dict:
        """
        6步安装链路：解压 → 验证 → 校验 → 检查依赖 → postInstall → 启动
        任一环节失败 → 回滚
        """
        package_path = PACKAGES_DIR / filename
        if not package_path.exists():
            return {"success": False, "error": f"包文件 '{filename}' 不存在于 packages/ 目录"}

        if package_path.suffix.lower() != ".7z":
            return {"success": False, "error": "仅支持 .7z 格式的模块包"}

        # 创建临时解压目录（用于 ZIPS LIP 安全校验）
        tmp_dir = Path(tempfile.mkdtemp(prefix="palm_install_"))
        rollback_items: list[Path] = [tmp_dir]  # 回滚清单

        try:
            # ── Step 1: 解压（含路径穿越防护） ───────────────────
            extract_result = self._extract_safe(package_path, tmp_dir)
            if not extract_result["success"]:
                self._rollback(rollback_items)
                return {"success": False, "error": f"解压失败: {extract_result['error']}"}

            # 确定解压后的根目录（可能有一层嵌套）
            extracted_root = extract_result["root"]

            # ── Step 2: 验证 MANIFEST.json ─────────────────────
            manifest_path = extracted_root / "MANIFEST.json"
            validation = self._validate_manifest(manifest_path)
            if not validation["valid"]:
                self._rollback(rollback_items)
                return {
                    "success": False,
                    "error": "MANIFEST 校验失败",
                    "details": validation["errors"],
                }

            info = validation["info"]
            raw_manifest = validation["raw"]

            # ── Step 3: 检查是否已安装 ──────────────────────────
            with self._lock:
                if info.module in self._modules:
                    self._rollback(rollback_items)
                    return {"success": False, "error": f"模块 '{info.module}' 已安装"}

            # ── Step 4: 校验 entry 文件存在 ────────────────────
            entry_path = extracted_root / info.entry
            if not entry_path.exists():
                self._rollback(rollback_items)
                return {"success": False, "error": f"入口文件 '{info.entry}' 未在包中找到"}

            # 检查脚本目录
            scripts_dir = extracted_root / "scripts"
            if not scripts_dir.exists():
                print(f"[Manager] [WARN] 模块 '{info.module}' 缺少 scripts/ 目录")

            # ── Step 5: 移动到 modules/ ──────────────────────────
            target_dir = MODULES_DIR / f"{info.module}-v{info.version}"
            if target_dir.exists():
                self._fast_rmtree(target_dir)
            shutil.copytree(extracted_root, target_dir, dirs_exist_ok=True)
            rollback_items.append(target_dir)

            # ── Step 6: postInstall 钩子（后台执行，不阻塞安装） ──
            post_install_scripts = info.deploy.get("postInstall", [])
            if post_install_scripts:
                for script_rel in post_install_scripts:
                    script_path = target_dir / script_rel
                    if script_path.exists():
                        print(f"[Manager] 执行 postInstall: {script_rel}")
                        threading.Thread(
                            target=self._run_script_async,
                            args=(script_path, target_dir, script_rel),
                            daemon=True,
                        ).start()

            # ── Step 7: 写入 SHA-256（内存计算，无需重读磁盘） ──
            manifest_path = target_dir / "MANIFEST.json"
            try:
                sha = self._manifest_sha256(raw_manifest)
                raw_manifest["sha256"] = sha
                manifest_path.write_text(
                    json.dumps(raw_manifest, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                print(f"[Manager] SHA-256: {sha}")
            except Exception as e:
                print(f"[Manager] [WARN] SHA-256 写入失败: {e}")

            # ── 注册模块 ──────────────────────────────────────────
            port = info.config.get("port") if isinstance(info.config, dict) else None
            state = ModuleState(
                module=info.module,
                version=info.version,
                path=str(target_dir),
                manifest=raw_manifest,
                status="stopped",
                port=port,
            )
            with self._lock:
                self._modules[info.module] = state

            # 清理临时目录
            self._rollback([tmp_dir], cleanup_only=True)

            return {
                "success": True,
                "module": {
                    "name": info.module,
                    "version": info.version,
                    "type": info.type,
                    "description": info.description,
                    "path": str(target_dir),
                    "port": port,
                    "status": "stopped",
                },
            }

        except Exception as e:
            self._rollback(rollback_items)
            return {"success": False, "error": f"安装失败: {str(e)}"}

    # ── 安全解压（防 Zip Slip） ─────────────────────────────────

    def _extract_safe(self, archive: Path, target: Path) -> dict:
        """使用 py7zr 安全解压 7z 包，防止路径穿越"""
        target.mkdir(parents=True, exist_ok=True)
        target_resolved = target.resolve()

        try:
            with py7zr.SevenZipFile(archive, mode="r") as z:
                # 提取前先检查所有文件路径
                names = z.getnames()
                for name in names:
                    full = (target_resolved / name).resolve()
                    try:
                        full.relative_to(target_resolved)
                    except ValueError:
                        self._fast_rmtree(target_resolved)
                        return {
                            "success": False,
                            "error": f"检测到路径穿越攻击: '{name}'",
                        }

                z.extractall(path=str(target_resolved))
                extracted_files = list(target_resolved.rglob("*"))

            # 确定解压根目录
            items = list(target_resolved.iterdir())
            root = items[0] if len(items) == 1 and items[0].is_dir() else target_resolved
            return {"success": True, "root": root, "files": extracted_files}

        except Exception as e:
            self._fast_rmtree(target_resolved)
            return {"success": False, "error": str(e)}

    # ── 卸载模块 ─────────────────────────────────────────────────

    def uninstall(self, module_name: str) -> dict:
        """卸载模块：停止 → 清理目录 → 移除注册信息"""
        with self._lock:
            if module_name not in self._modules:
                return {"success": False, "error": f"模块 '{module_name}' 未找到"}

            state = self._modules[module_name]

        # 先停止
        if state.status == "running":
            stop_result = self.stop(module_name)
            if not stop_result["success"]:
                return stop_result

        # 执行 preUninstall 钩子
        deploy = state.manifest.get("deploy", {})
        pre_uninstall_scripts = deploy.get("preUninstall", []) if isinstance(deploy, dict) else []
        for script_rel in pre_uninstall_scripts:
            script_path = Path(state.path) / script_rel
            if script_path.exists():
                try:
                    subprocess.run([str(script_path)], cwd=state.path, shell=True, timeout=30)
                except Exception as e:
                    print(f"[Manager] [WARN] 卸载前脚本 '{script_rel}' 执行失败: {e}")

        # 删除目录（快速）
        module_path = Path(state.path)
        if module_path.exists():
            self._fast_rmtree(module_path)

        # 移除注册
        with self._lock:
            self._modules.pop(module_name, None)
            self._processes.pop(module_name, None)

        return {"success": True, "message": f"Module '{module_name}' uninstalled"}

    # ── 启动模块 ─────────────────────────────────────────────────

    def start(self, module_name: str) -> dict:
        """启动模块：读取 entry，以子进程方式执行"""
        with self._lock:
            if module_name not in self._modules:
                return {"success": False, "error": f"模块 '{module_name}' 未找到"}

            state = self._modules[module_name]
            if state.status == "running":
                return {"success": True, "message": f"Module '{module_name}' is already running"}

            entry = state.manifest.get("entry", "")
            module_path = Path(state.path)

        entry_path = module_path / entry
        if not entry_path.exists():
            return {"success": False, "error": f"入口文件 '{entry}' 不存在于模块目录"}

        try:
            # 判断 entry 类型并执行
            if entry.endswith(".py"):
                python = sys.executable
                proc = subprocess.Popen(
                    [python, str(entry_path)],
                    cwd=str(module_path),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
            elif entry.endswith(".bat") or entry.endswith(".cmd"):
                proc = subprocess.Popen(
                    [str(entry_path)],
                    cwd=str(module_path),
                    shell=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
            elif entry.endswith(".js") or entry.endswith(".mjs"):
                proc = subprocess.Popen(
                    ["node", str(entry_path)],
                    cwd=str(module_path),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
            else:
                # 尝试直接执行
                proc = subprocess.Popen(
                    [str(entry_path)],
                    cwd=str(module_path),
                    shell=True,
                )

            with self._lock:
                self._modules[module_name].status = "running"
                self._modules[module_name].pid = proc.pid
                self._modules[module_name].started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
                self._processes[module_name] = proc

            # 监控子进程（后台线程）
            self._monitor_process(module_name, proc)

            return {
                "success": True,
                "module": module_name,
                "pid": proc.pid,
                "entry": entry,
            }

        except Exception as e:
            with self._lock:
                self._modules[module_name].status = "error"
                self._modules[module_name].error = str(e)
            return {"success": False, "error": f"Failed to start module: {str(e)}"}

    # ── 停止模块 ─────────────────────────────────────────────────

    def stop(self, module_name: str) -> dict:
        """停止模块进程"""
        with self._lock:
            if module_name not in self._modules:
                return {"success": False, "error": f"模块 '{module_name}' 未找到"}

            proc = self._processes.get(module_name)
            if proc is None:
                self._modules[module_name].status = "stopped"
                return {"success": True, "message": "模块未在运行"}

        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, timeout=10)
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception as e:
            print(f"[Manager] [WARN] 终止进程 {proc.pid} 失败: {e}")

        with self._lock:
            self._processes.pop(module_name, None)
            if module_name in self._modules:
                self._modules[module_name].status = "stopped"
                self._modules[module_name].pid = None

        return {"success": True, "message": f"Module '{module_name}' stopped"}

    # ── 进程监控 ─────────────────────────────────────────────────

    def _monitor_process(self, module_name: str, proc: subprocess.Popen):
        """后台线程监控子进程，进程退出时更新状态"""
        def monitor():
            try:
                proc.wait()
            except Exception:
                pass
            finally:
                with self._lock:
                    if module_name in self._modules:
                        self._modules[module_name].status = "stopped"
                        self._modules[module_name].pid = None
                    self._processes.pop(module_name, None)

        t = threading.Thread(target=monitor, daemon=True)
        t.start()

    # ── 获取模块信息 ─────────────────────────────────────────────

    def validate_package(self, archive_path: Path) -> dict:
        """
        验证一个 .7z 包文件：读 MANIFEST.json 内容并校验。
        不安装，只验证。验证后清理临时文件。
        """
        if not archive_path.exists():
            return {"success": False, "error": f"文件未找到: {archive_path}"}
        if archive_path.suffix.lower() != ".7z":
            return {"success": False, "error": "仅支持 .7z 格式的模块包"}

        tmp = None
        try:
            # 使用 py7zr 从 7z 包中提取 MANIFEST.json
            with py7zr.SevenZipFile(archive_path, mode="r") as z:
                names = z.getnames()
                if "MANIFEST.json" not in names:
                    return {"success": False, "error": "包内未找到 MANIFEST.json"}
                tmp = Path(tempfile.mkdtemp(prefix="palm_val_"))
                z.extract(path=str(tmp), targets=["MANIFEST.json"])
                manifest_path = tmp / "MANIFEST.json"
                if not manifest_path.exists():
                    return {"success": False, "error": "MANIFEST.json 提取失败"}
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))

            if not isinstance(raw, dict):
                return {"success": False, "error": "MANIFEST.json 根节点必须是一个对象"}

            # 字段校验
            errors = []
            for field in REQUIRED_MANIFEST_FIELDS:
                if field not in raw or not isinstance(raw[field], str) or not raw[field].strip():
                    errors.append(f"缺少必填字段: '{field}'")
            if "version" in raw and raw["version"] and not SEMVER_RE.match(str(raw["version"])):
                errors.append(f"版本号格式错误: '{raw['version']}' (应为 X.Y.Z)")

            if errors:
                return {"success": False, "error": "MANIFEST 校验失败", "details": errors, "raw_manifest": raw}

            # 输出依赖警告
            if "dependencies" in raw and isinstance(raw["dependencies"], dict):
                deps = raw["dependencies"]
                if "runtime" in deps:
                    print(f"[Manager] [WARN] 模块 '{raw.get('module')}' 运行时依赖: {deps['runtime']}")
                if "packages" in deps and deps["packages"]:
                    print(f"[Manager] [WARN] 模块 '{raw.get('module')}' 包依赖: {deps['packages']}")

            info = {
                "module": str(raw.get("module", "")),
                "version": str(raw.get("version", "")),
                "type": str(raw.get("type", "")),
                "description": str(raw.get("description", "")),
                "author": str(raw.get("author", "")),
                "entry": str(raw.get("entry", "")),
                "port": raw.get("config", {}).get("port") if isinstance(raw.get("config"), dict) else None,
            }
            return {"success": True, "info": info, "manifest": raw}

        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            if tmp and tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)

    # ── 获取模块信息 ─────────────────────────────────────────────

    def get_modules(self) -> list[dict]:
        """返回所有模块的当前状态列表"""
        with self._lock:
            return [
                {
                    "name": s.module,
                    "version": s.version,
                    "type": s.manifest.get("type", ""),
                    "description": s.manifest.get("description", ""),
                    "status": s.status,
                    "pid": s.pid,
                    "port": s.port,
                    "startedAt": s.started_at,
                    "error": s.error,
                    "path": s.path,
                }
                for s in sorted(self._modules.values(), key=lambda x: x.module)
            ]

    # ── SHA-256 完整性校验 ──────────────────────────────────────────

    @staticmethod
    def _manifest_sha256(manifest: dict) -> str:
        """计算 MANIFEST.json 的 SHA-256（排除 sha256 字段自身）"""
        clean = {k: v for k, v in manifest.items() if k != "sha256"}
        raw = json.dumps(clean, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def check_integrity(self, module_name: str) -> dict:
        """检查单个模块的完整性。返回状态: valid / corrupted / missing"""
        with self._lock:
            if module_name not in self._modules:
                return {"module": module_name, "status": "缺失", "expected": "", "actual": ""}
            state = self._modules[module_name]

        manifest_path = Path(state.path) / "MANIFEST.json"
        if not manifest_path.exists():
            return {"module": module_name, "status": "损坏", "expected": "", "actual": "", "error": "未找到 MANIFEST.json"}

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            return {"module": module_name, "status": "损坏", "expected": "", "actual": "", "error": str(e)}

        stored = manifest.get("sha256", "")
        computed = self._manifest_sha256(manifest)

        if stored and stored == computed:
            return {"module": module_name, "status": "valid", "expected": stored, "actual": computed}
        elif stored and stored != computed:
            return {"module": module_name, "status": "损坏", "expected": stored, "actual": computed,
                    "error": "SHA-256 不匹配 — 模块可能已被篡改"}
        else:
            return {"module": module_name, "status": "valid", "expected": "", "actual": computed,
                    "warning": "MANIFEST 中缺少 sha256 字段（旧版模块）"}

    def get_modules_with_status(self) -> list[dict]:
        """获取所有模块状态（含未安装的包），status: 未安装 | 已安装 | 损坏"""
        installed = {}
        for s in list(self._modules.values()):
            integrity = self.check_integrity(s.module)
            st = "损坏" if integrity["status"] == "损坏" else "已安装"
            installed[s.module] = {
                "name": s.module,
                "version": s.version,
                "type": s.manifest.get("type", ""),
                "description": s.manifest.get("description", ""),
                "author": s.manifest.get("author", ""),
                "entry": s.manifest.get("entry", ""),
                "status": st,
                "integrity": integrity,
                "port": s.port,
                "path": s.path,
                "running": s.status == "running",
            }

        if PACKAGES_DIR.exists():
            for f in sorted(PACKAGES_DIR.iterdir()):
                if f.suffix.lower() != ".7z":
                    continue
                name = f.stem
                sep = name.rfind("-v")
                if sep == -1:
                    continue
                module_name = name[:sep]
                version = name[sep + 2:]
                if module_name not in installed:
                    installed[module_name] = {
                        "name": module_name,
                        "version": version,
                        "type": "", "description": "", "author": "", "entry": "",
                        "status": "未安装",
                        "integrity": {"status": "none"},
                        "port": None,
                        "path": str(f), "running": False,
                    }

        return sorted(installed.values(), key=lambda x: x["name"])

    def get_module(self, module_name: str) -> Optional[dict]:
        """获取单个模块详情"""
        with self._lock:
            s = self._modules.get(module_name)
            if s is None:
                return None
            return {
                "name": s.module,
                "version": s.version,
                "type": s.manifest.get("type", ""),
                "description": s.manifest.get("description", ""),
                "status": s.status,
                "pid": s.pid,
                "port": s.port,
                "startedAt": s.started_at,
                "error": s.error,
                "path": s.path,
                "manifest": s.manifest,
            }

    # ── 回滚 ─────────────────────────────────────────────────────

    def _fast_rmtree(self, path: Path):
        """快速删除目录（Windows 上用 rd 比 shutil.rmtree 快数倍）"""
        if not path.exists():
            return
        if sys.platform == "win32":
            subprocess.run(
                ["rd", "/S", "/Q", str(path)],
                shell=True, capture_output=True, timeout=30,
            )
        else:
            shutil.rmtree(path, ignore_errors=True)

    @staticmethod
    def _run_script_async(script_path: Path, cwd: Path, name: str):
        """后台运行脚本（不阻塞调用者）"""
        try:
            subprocess.run(
                [str(script_path)], cwd=str(cwd), shell=True,
                timeout=120, capture_output=True, text=True,
            )
        except subprocess.TimeoutExpired:
            print(f"[Manager] [WARN] postInstall 脚本 '{name}' 超时")
        except Exception as e:
            print(f"[Manager] [WARN] postInstall 脚本 '{name}' 失败: {e}")

    def _rollback(self, items: list[Path], cleanup_only: bool = False):
        """回滚：清理临时文件和已创建的目录"""
        for item in items:
            if item.exists():
                try:
                    if item.is_dir():
                        self._fast_rmtree(item)
                    else:
                        item.unlink(missing_ok=True)
                except Exception as e:
                    print(f"[Manager] 回滚警告: 删除 {item} 失败: {e}")

    # ── 启动所有模块（用于启动脚本） ─────────────────────────────

    def start_all(self) -> list[dict]:
        """启动所有已安装的模块（按字母顺序）"""
        results = []
        with self._lock:
            names = sorted(self._modules.keys())
        for name in names:
            result = self.start(name)
            results.append({"module": name, "success": result["success"], "pid": result.get("pid")})
            time.sleep(0.5)  # 模块间留出启动缓冲
        return results

    def wait_for_modules(self, timeout: int = 30) -> bool:
        """轮询等待所有模块进入 running 状态（最多 timeout 秒）"""
        for _ in range(timeout):
            with self._lock:
                if self._modules and all(s.status == "running" for s in self._modules.values()):
                    return True
            time.sleep(1)
        return False


# ── 全局单例 ──────────────────────────────────────────────────────

_manager: Optional[ModuleManager] = None


def get_manager() -> ModuleManager:
    global _manager
    if _manager is None:
        _manager = ModuleManager()
    return _manager
