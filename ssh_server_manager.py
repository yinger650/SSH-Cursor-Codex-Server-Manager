import getpass
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache"


@dataclass
class HostEntry:
    alias: str
    options: dict[str, str] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        user = self.options.get("user", "")
        hostname = self.options.get("hostname", "")
        port = self.options.get("port", "")
        target = hostname or "(no HostName)"
        if user:
            target = f"{user}@{target}"
        if port:
            target = f"{target}:{port}"
        return target


def parse_ssh_config(path: Path) -> list[HostEntry]:
    hosts: list[HostEntry] = []
    current: HostEntry | None = None
    if not path.exists():
        return hosts
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        key, value = parts[0].lower(), parts[1].strip()
        if key == "host":
            for alias in value.split():
                if "*" not in alias and "?" not in alias and "!" not in alias:
                    current = HostEntry(alias=alias)
                    hosts.append(current)
                else:
                    current = None
        elif current:
            current.options[key] = value
    return hosts


def run_cmd(args: list[str], timeout: int = 30, input_text: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(args, 127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(args, 124, exc.stdout or "", exc.stderr or "Command timed out")


def run_ssh(host: str, command: str, timeout: int = 30, password: str | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    args = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=8", host, command]
    if password:
        askpass = ROOT / "ssh_askpass_helper.bat"
        askpass.write_text("@echo off\r\necho %SSH_MANAGER_PASSWORD%\r\n", encoding="ascii")
        env["SSH_ASKPASS"] = str(askpass)
        env["SSH_MANAGER_PASSWORD"] = password
        env["DISPLAY"] = env.get("DISPLAY", "dummy")
        args = ["ssh", "-o", "BatchMode=no", "-o", "StrictHostKeyChecking=accept-new", "-o", "NumberOfPasswordPrompts=1", host, command]
        return subprocess.run(args, text=True, capture_output=True, timeout=timeout, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    return run_cmd(args, timeout=timeout)


def cursor_info() -> dict[str, str]:
    app = os.environ.get("CURSOR_APP")
    if not app:
        cursor_cmd = shutil.which("cursor")
        if cursor_cmd:
            app = str(Path(cursor_cmd).resolve().parents[1])
    candidates = [
        app,
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Cursor\resources\app"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\cursor\resources\app"),
        r"e:\apps\cursor\resources\app",
    ]
    for item in candidates:
        if not item:
            continue
        product = Path(item) / "product.json"
        package = Path(item) / "package.json"
        if product.exists() and package.exists():
            p = json.loads(product.read_text(encoding="utf-8"))
            pkg = json.loads(package.read_text(encoding="utf-8"))
            commit = os.environ.get("CURSOR_COMMIT") or p.get("realCommit") or p.get("commit") or pkg.get("distro")
            return {"app": str(Path(item)), "version": pkg.get("version", ""), "commit": commit or ""}
    raise RuntimeError("未找到 Cursor product.json；可设置 CURSOR_APP 指向 resources\\app")


def codex_info() -> dict[str, str]:
    codex_cmd = shutil.which("codex")
    app_dir = ""
    version = ""
    runtime_sha = ""
    if codex_cmd:
        app_dir = str(Path(codex_cmd).resolve().parent)
        match = re.search(r"OpenAI\.Codex_([^_]+)_", codex_cmd)
        if match:
            version = match.group(1)
    if not app_dir:
        windows_apps = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "WindowsApps"
        candidates = sorted(
            windows_apps.glob(r"OpenAI.Codex_*_x64__*\app\resources"),
            key=lambda p: p.parent.parent.name,
            reverse=True,
        )
        for candidate in candidates:
            if (candidate / "codex.exe").exists() or (candidate / "codex").exists():
                app_dir = str(candidate)
                match = re.search(r"OpenAI\.Codex_([^_]+)_", str(candidate))
                if match:
                    version = match.group(1)
                break
    if app_dir:
        owl = Path(app_dir) / "owl-electron-app.json"
        if owl.exists():
            try:
                data = json.loads(owl.read_text(encoding="utf-8"))
                runtime_sha = data.get("runtimeArchiveSha", "")
            except Exception:
                pass
    return {"app": app_dir, "version": version, "commit": runtime_sha}


def format_bytes(value: float) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def format_eta(seconds: float) -> str:
    if seconds <= 0:
        return "0s"
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{sec:02d}s"
    return f"{sec}s"


def platform_from_uname(uname_s: str, uname_m: str) -> tuple[str, str]:
    if uname_s.strip().lower() != "linux":
        raise RuntimeError(f"暂只支持 Linux 远端，当前是 {uname_s.strip()}")
    machine = uname_m.strip().lower()
    if machine in ("x86_64", "amd64"):
        return "linux-x64", "x64"
    if machine in ("aarch64", "arm64"):
        return "linux-arm64", "arm64"
    raise RuntimeError(f"不支持的远端架构：{uname_m.strip()}")


def codex_platform_from_uname(uname_s: str, uname_m: str) -> tuple[str, str, str]:
    if uname_s.strip().lower() != "linux":
        raise RuntimeError(f"暂只支持 Linux 远端，当前是 {uname_s.strip()}")
    machine = uname_m.strip().lower()
    if machine in ("x86_64", "amd64"):
        return "linux-x64", "x64", "x86_64-unknown-linux-musl"
    if machine in ("aarch64", "arm64"):
        return "linux-arm64", "arm64", "aarch64-unknown-linux-musl"
    raise RuntimeError(f"不支持的远端架构：{uname_m.strip()}")


def local_codex_auth() -> Path:
    auth = Path.home() / ".codex" / "auth.json"
    if not auth.exists() or auth.stat().st_size == 0:
        raise RuntimeError(f"本机未找到 Codex OAuth：{auth}")
    return auth


def npm_command() -> str:
    candidates = [
        shutil.which("npm.cmd"),
        shutil.which("npm"),
        os.path.expandvars(r"%ProgramFiles%\nodejs\npm.cmd"),
        os.path.expandvars(r"%ProgramFiles%\nodejs\npm"),
        os.path.expandvars(r"%APPDATA%\npm\npm.cmd"),
        os.path.expandvars(r"%APPDATA%\npm\npm"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("本机找不到 npm；请安装 Node.js，或把 npm.cmd 加到 PATH")


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SSH Server Manager")
        self.geometry("1180x720")
        self.minsize(980, 560)
        self.q: queue.Queue[tuple[str, str, str | None]] = queue.Queue()
        self.hosts: list[HostEntry] = []
        self.status_vars: dict[str, tk.StringVar] = {}
        self.local_cursor = tk.StringVar(value="Cursor: 检测中")
        self.local_codex = tk.StringVar(value="Codex: 检测中")
        self._build_ui()
        self.refresh_local_info()
        self.refresh_hosts()
        self.after(100, self._drain_log)

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview", rowheight=28)
        style.configure("TButton", padding=(8, 4))

        top = ttk.Frame(self, padding=(10, 10, 10, 6))
        top.pack(fill=tk.X)
        ttk.Button(top, text="刷新 SSH Config", command=self.refresh_hosts).pack(side=tk.LEFT)
        ttk.Button(top, text="刷新本机信息", command=self.refresh_local_info).pack(side=tk.LEFT, padx=(8, 0))

        local = ttk.Frame(self, padding=(10, 0, 10, 8))
        local.pack(fill=tk.X)
        ttk.Label(local, textvariable=self.local_cursor).pack(side=tk.LEFT, padx=(0, 18))
        ttk.Label(local, textvariable=self.local_codex).pack(side=tk.LEFT)

        body = ttk.Frame(self, padding=(10, 0, 10, 6))
        body.pack(fill=tk.BOTH, expand=True)
        columns = ("alias", "target", "status")
        self.tree = ttk.Treeview(body, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("alias", text="Host")
        self.tree.heading("target", text="目标")
        self.tree.heading("status", text="状态")
        self.tree.column("alias", width=190, anchor=tk.W)
        self.tree.column("target", width=420, anchor=tk.W)
        self.tree.column("status", width=360, anchor=tk.W)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        actions = ttk.Frame(body, padding=(10, 0, 0, 0))
        actions.pack(side=tk.LEFT, fill=tk.Y)
        ttk.Button(actions, text="测试可达", command=lambda: self.on_selected(self.test_reachable)).pack(fill=tk.X, pady=(0, 6))
        ttk.Button(actions, text="检查 Cursor", command=lambda: self.on_selected(self.check_cursor)).pack(fill=tk.X, pady=6)
        ttk.Button(actions, text="检查 Codex", command=lambda: self.on_selected(self.check_codex)).pack(fill=tk.X, pady=6)
        ttk.Separator(actions).pack(fill=tk.X, pady=10)
        ttk.Button(actions, text="全部测试可达", command=self.test_all).pack(fill=tk.X, pady=6)
        ttk.Button(actions, text="全部检查 Cursor", command=self.cursor_all).pack(fill=tk.X, pady=6)
        ttk.Button(actions, text="全部检查 Codex", command=self.codex_all).pack(fill=tk.X, pady=6)
        ttk.Button(actions, text="清空日志", command=lambda: self.log.delete("1.0", tk.END)).pack(fill=tk.X, pady=6)

        log_frame = ttk.Frame(self, padding=(10, 0, 10, 10))
        log_frame.pack(fill=tk.BOTH)
        ttk.Label(log_frame, text="日志").pack(anchor=tk.W)
        self.log = tk.Text(log_frame, height=12, wrap=tk.WORD)
        self.log.pack(fill=tk.BOTH, expand=True)

    def refresh_hosts(self) -> None:
        self.hosts = parse_ssh_config(Path.home() / ".ssh" / "config")
        self.tree.delete(*self.tree.get_children())
        for host in self.hosts:
            self.tree.insert("", tk.END, iid=host.alias, values=(host.alias, host.summary, "未测试"))
        self.write_log("system", f"载入 {len(self.hosts)} 个 SSH Host")

    def refresh_local_info(self) -> None:
        try:
            info = cursor_info()
            self.local_cursor.set(f"Cursor: 已安装  version={info['version'] or '-'}  serverCommit={info['commit'] or '-'}")
        except Exception as exc:
            self.local_cursor.set(f"Cursor: 未检测到 ({exc})")
        info = codex_info()
        if info["app"]:
            commit = info["commit"][:12] + "..." if info["commit"] else "-"
            self.local_codex.set(f"Codex: 已安装  version={info['version'] or '-'}  runtimeSha={commit}  包=自动下载/缓存")
        else:
            self.local_codex.set("Codex: 未检测到  包=自动下载/缓存")

    def on_selected(self, fn) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("请选择服务器", "先在列表里选一个 SSH Host。")
            return
        fn(sel[0])

    def test_all(self) -> None:
        for host in self.hosts:
            self.test_reachable(host.alias)

    def cursor_all(self) -> None:
        for host in self.hosts:
            self.check_cursor(host.alias)

    def codex_all(self) -> None:
        for host in self.hosts:
            self.check_codex(host.alias)

    def set_status(self, host: str, status: str) -> None:
        if self.tree.exists(host):
            old = list(self.tree.item(host, "values"))
            old[2] = status
            self.tree.item(host, values=old)

    def write_log(self, host: str, text: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log.insert(tk.END, f"[{stamp}] [{host}] {text}\n")
        self.log.see(tk.END)

    def _drain_log(self) -> None:
        while True:
            try:
                kind, host, text = self.q.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.write_log(host, text or "")
            elif kind == "status":
                self.set_status(host, text or "")
        self.after(100, self._drain_log)

    def background(self, host: str, label: str, fn) -> None:
        self.set_status(host, f"{label}中...")
        threading.Thread(target=self._run_task, args=(host, label, fn), daemon=True).start()

    def _run_task(self, host: str, label: str, fn) -> None:
        try:
            fn(host)
        except Exception as exc:
            self.q.put(("status", host, f"{label}失败"))
            self.q.put(("log", host, f"ERROR: {exc}"))

    def test_reachable(self, host: str) -> None:
        self.background(host, "测试", self._test_reachable)

    def _test_reachable(self, host: str) -> None:
        cp = run_ssh(host, "echo __SSH_OK__; uname -s; uname -m", timeout=15)
        combined = (cp.stdout + cp.stderr).strip()
        if cp.returncode == 0 and "__SSH_OK__" in cp.stdout:
            self.q.put(("status", host, "可达"))
            self.q.put(("log", host, cp.stdout.strip()))
            return
        if "REMOTE HOST IDENTIFICATION HAS CHANGED" in combined or "Host key verification failed" in combined:
            self.q.put(("log", host, "检测到 known_hosts/host key 问题，尝试移除旧记录"))
            for known_host in self.known_hosts_names(host):
                rm = run_cmd(["ssh-keygen", "-R", known_host], timeout=15)
                output = (rm.stdout + rm.stderr).strip()
                if output:
                    self.q.put(("log", host, output))
            cp2 = run_ssh(host, "echo __SSH_OK__; uname -s; uname -m", timeout=20)
            if cp2.returncode == 0 and "__SSH_OK__" in cp2.stdout:
                self.q.put(("status", host, "可达，已刷新 footprint"))
                return
            combined = (cp2.stdout + cp2.stderr).strip()
        if re.search(r"password|permission denied|publickey", combined, re.I):
            self.q.put(("status", host, "需要密码"))
            self.q.put(("log", host, "需要密码认证，请在弹窗输入密码"))
            self.after(0, lambda: self._ask_password_and_retry(host))
            return
        if re.search(r"timed out|could not resolve|network is unreachable|connection refused|connection timed out|no route", combined, re.I):
            self.q.put(("status", host, "网络不可达"))
            self.q.put(("log", host, combined[-1200:]))
            return
        self.q.put(("status", host, "不可达"))
        self.q.put(("log", host, combined[-1200:]))

    def known_hosts_names(self, host: str) -> list[str]:
        names = [host]
        cfg = run_cmd(["ssh", "-G", host], timeout=10)
        if cfg.returncode != 0:
            return names
        data: dict[str, str] = {}
        for line in cfg.stdout.splitlines():
            parts = line.split(None, 1)
            if len(parts) == 2:
                data[parts[0].lower()] = parts[1].strip()
        hostname = data.get("hostname")
        port = data.get("port", "22")
        if hostname:
            names.append(hostname if port == "22" else f"[{hostname}]:{port}")
        return list(dict.fromkeys(names))

    def _ask_password_and_retry(self, host: str) -> None:
        password = simpledialog.askstring("SSH 密码", f"输入 {host} 的 SSH 密码", show="*")
        if not password:
            self.write_log(host, "用户取消密码输入")
            return
        self.background(host, "密码重试", lambda h: self._retry_with_password(h, password))

    def _retry_with_password(self, host: str, password: str) -> None:
        cp = run_ssh(host, "echo __SSH_OK__; uname -s; uname -m", timeout=20, password=password)
        if cp.returncode == 0 and "__SSH_OK__" in cp.stdout:
            self.q.put(("status", host, "可达，密码验证通过"))
        else:
            self.q.put(("status", host, "密码验证失败"))
            self.q.put(("log", host, (cp.stdout + cp.stderr).strip()[-1200:]))

    def check_cursor(self, host: str) -> None:
        self.background(host, "Cursor 检查", self._check_cursor)

    def _check_cursor(self, host: str) -> None:
        info = cursor_info()
        self.q.put(("log", host, "开始检查 Cursor server"))
        self.q.put(("log", host, "SSH 探测远端系统和架构"))
        cp = run_ssh(host, "uname -s; uname -m", timeout=20)
        if cp.returncode != 0:
            raise RuntimeError((cp.stdout + cp.stderr).strip())
        lines = [x.strip() for x in cp.stdout.splitlines() if x.strip()]
        platform, arch = platform_from_uname(lines[0], lines[1])
        self.q.put(("log", host, f"远端平台 {platform}，目标 commit {info['commit']}"))
        commit = info["commit"]
        remote_dir = f"$HOME/.cursor-server/bin/{platform}/{commit}"
        self.q.put(("log", host, "SSH 检查远端 Cursor server 文件"))
        probe = run_ssh(host, f'test -x "{remote_dir}/bin/cursor-server" && test -x "{remote_dir}/node" && test -f "{remote_dir}/product.json" && echo installed || echo missing', timeout=20)
        if "installed" in probe.stdout:
            self.q.put(("status", host, f"Cursor 已是最新 {commit[:8]}"))
            self.q.put(("log", host, f"Cursor server OK: {commit}"))
            return
        self.q.put(("log", host, f"Cursor server 缺失或落后，开始安装 {commit}"))
        archive = self.download_cursor_archive(commit, arch)
        remote_tmp = f"/tmp/{archive.name}"
        self.q.put(("log", host, f"上传安装包到 {remote_tmp}"))
        self.upload_archive(host, archive, remote_tmp)
        self.q.put(("log", host, "上传完成，开始远端解压和校验，远端 tar 解压可能需要几十秒"))
        cmd = (
            f'set -e; target="{remote_dir}"; tmp="{remote_tmp}"; mkdir -p "$target"; '
            'find "$target" -mindepth 1 ! -name "cursor-server-*.tar.gz" -exec rm -rf {} + 2>/dev/null || true; '
            'tar -xzf "$tmp" -C "$target" --strip-components=1; '
            'chmod +x "$target/bin/cursor-server" "$target/node" 2>/dev/null || true; rm -f "$tmp"; '
            'test -x "$target/bin/cursor-server"; test -x "$target/node"; test -f "$target/product.json"; "$target/node" --version'
        )
        inst_start = time.time()
        inst = run_ssh(host, cmd, timeout=120)
        self.q.put(("log", host, f"远端解压校验完成，用时 {format_eta(time.time() - inst_start)}"))
        if inst.returncode != 0:
            raise RuntimeError((inst.stdout + inst.stderr).strip())
        self.q.put(("status", host, f"Cursor 已更新 {commit[:8]}"))
        self.q.put(("log", host, inst.stdout.strip()))

    def download_cursor_archive(self, commit: str, arch: str) -> Path:
        CACHE_DIR.mkdir(exist_ok=True)
        archive = CACHE_DIR / f"cursor-reh-linux-{arch}-{commit}.tar.gz"
        if archive.exists() and archive.stat().st_size > 0:
            self.q.put(("log", "local", f"使用缓存 {archive.name} ({format_bytes(archive.stat().st_size)})"))
            return archive
        url = f"https://downloads.cursor.com/production/{commit}/linux/{arch}/cursor-reh-linux-{arch}.tar.gz"
        self.q.put(("log", "local", f"下载 {url}"))
        try:
            self.download_with_progress(url, archive)
        except Exception as exc:
            self.q.put(("log", "local", f"Python 下载失败，改用 PowerShell: {exc}"))
            ps = run_cmd(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    (
                        "$ErrorActionPreference='Stop'; "
                        "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; "
                        "$headers=@{'User-Agent'='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}; "
                        f"Invoke-WebRequest -Uri '{url}' -Headers $headers -OutFile '{archive}'"
                    ),
                ],
                timeout=180,
            )
            if ps.returncode != 0:
                raise RuntimeError((ps.stdout + ps.stderr).strip())
        if not archive.exists() or archive.stat().st_size == 0:
            raise RuntimeError(f"下载失败，文件为空：{archive}")
        return archive

    def download_with_progress(self, url: str, archive: Path) -> None:
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/gzip,application/octet-stream,*/*",
            },
        )
        tmp = archive.with_suffix(archive.suffix + ".part")
        downloaded = 0
        start = time.time()
        last_log = start
        with urlopen(request, timeout=60) as response, tmp.open("wb") as output:
            total_text = response.headers.get("Content-Length")
            total = int(total_text) if total_text and total_text.isdigit() else 0
            while True:
                chunk = response.read(1024 * 512)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                now = time.time()
                if now - last_log >= 1:
                    elapsed = max(now - start, 0.001)
                    speed = downloaded / elapsed
                    if total:
                        percent = downloaded * 100 / total
                        eta = (total - downloaded) / speed if speed > 0 else 0
                        self.q.put((
                            "log",
                            "local",
                            f"下载进度 {percent:5.1f}%  {format_bytes(downloaded)}/{format_bytes(total)}  "
                            f"{format_bytes(speed)}/s  ETA {format_eta(eta)}",
                        ))
                    else:
                        self.q.put(("log", "local", f"下载进度 {format_bytes(downloaded)}  {format_bytes(speed)}/s"))
                    last_log = now
        tmp.replace(archive)
        elapsed = max(time.time() - start, 0.001)
        self.q.put(("log", "local", f"下载完成 {archive.name}  {format_bytes(downloaded)}  平均 {format_bytes(downloaded / elapsed)}/s"))

    def upload_archive(self, host: str, local: Path, remote: str) -> None:
        total = local.stat().st_size
        start = time.time()
        self.q.put(("log", host, f"上传开始 {local.name} ({format_bytes(total)})"))
        proc = subprocess.Popen(
            ["scp", "-O", str(local), f"{host}:{remote}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        last_log = start
        stderr_parts: list[str] = []
        stdout_parts: list[str] = []
        while proc.poll() is None:
            now = time.time()
            if now - last_log >= 5:
                elapsed = max(now - start, 0.001)
                self.q.put(("log", host, f"上传仍在进行... 已用时 {format_eta(elapsed)}，文件大小 {format_bytes(total)}"))
                last_log = now
            time.sleep(0.2)
        try:
            stdout, stderr = proc.communicate(timeout=1)
            stdout_parts.append(stdout or "")
            stderr_parts.append(stderr or "")
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            stdout_parts.append(stdout or "")
            stderr_parts.append(stderr or "")
        elapsed = max(time.time() - start, 0.001)
        if proc.returncode != 0:
            raise RuntimeError(("".join(stdout_parts) + "".join(stderr_parts)).strip())
        self.q.put(("log", host, f"上传完成 {format_bytes(total)}，平均 {format_bytes(total / elapsed)}/s，用时 {format_eta(elapsed)}"))

    def check_codex(self, host: str) -> None:
        self.background(host, "Codex 检查", self._check_codex)

    def _check_codex(self, host: str) -> None:
        self.q.put(("log", host, "开始检查 Codex CLI"))
        self.q.put(("log", host, "SSH 探测远端系统、架构和现有 Codex"))
        cp = run_ssh(host, "uname -s; uname -m", timeout=20)
        if cp.returncode != 0:
            raise RuntimeError((cp.stdout + cp.stderr).strip())
        lines = [x.strip() for x in cp.stdout.splitlines() if x.strip()]
        platform, arch, triple = codex_platform_from_uname(lines[0], lines[1])
        wanted_version = self.codex_npm_version()
        probe = run_ssh(
            host,
            'set +e; echo "__PATH__"; command -v codex; echo "__VERSION__"; codex --version 2>/dev/null; '
            'echo "__AUTH__"; test -s "$HOME/.codex/auth.json" && echo present || echo missing',
            timeout=25,
        )
        if probe.returncode != 0:
            raise RuntimeError((probe.stdout + probe.stderr).strip())
        self.q.put(("log", host, "Codex 远端探测结果：\n" + (probe.stdout.strip() or "(无输出)")))
        installed_latest = wanted_version in probe.stdout
        self.sync_codex_auth(host)
        if installed_latest:
            self.q.put(("status", host, f"Codex 已是最新 {wanted_version}"))
            self.q.put(("log", host, "Codex 已安装，OAuth 已同步为本机账号"))
            return
        self.q.put(("log", host, f"Codex 缺失或版本不一致，开始离线安装 {wanted_version} ({platform})"))
        local = self.codex_native_archive(wanted_version, platform)
        remote_tmp = f"/tmp/{local.name}"
        self.q.put(("log", host, f"上传 Codex Linux 原生包到 {remote_tmp}"))
        self.upload_archive(host, local, remote_tmp)
        self.q.put(("log", host, "上传完成，开始远端离线展开、写入 codex 启动脚本并校验"))
        cmd = (
            f'set -e; version="{wanted_version}"; triple="{triple}"; archive="{remote_tmp}"; '
            'if [ "$(id -u)" = "0" ]; then root="/opt/openai-codex/$version"; shim="/usr/bin/codex"; '
            'else root="$HOME/.local/share/openai-codex/$version"; shim="$HOME/.local/bin/codex"; fi; '
            'mkdir -p "$root" "$(dirname "$shim")"; '
            'find "$root" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true; '
            'tar -xzf "$archive" -C "$root" --strip-components=1; '
            'bin="$root/vendor/$triple/bin/codex"; test -f "$bin"; chmod +x "$bin"; '
            'chmod +x "$root/vendor/$triple/codex-path/rg" "$root/vendor/$triple/codex-resources/bwrap" "$root/vendor/$triple/codex-resources/zsh/bin/zsh" 2>/dev/null || true; '
            'printf \'#!/bin/sh\nexec "%s" "$@"\n\' "$bin" > "$shim"; chmod +x "$shim"; '
            'if [ "$(id -u)" != "0" ]; then grep -qxF "export PATH=\\"$HOME/.local/bin:$PATH\\"" "$HOME/.profile" 2>/dev/null || echo "export PATH=\\"$HOME/.local/bin:$PATH\\"" >> "$HOME/.profile"; fi; '
            'rm -f "$archive"; "$shim" --version; test -s "$HOME/.codex/auth.json" && echo auth-present'
        )
        inst_start = time.time()
        inst = run_ssh(host, cmd, timeout=180)
        self.q.put(("log", host, f"远端 Codex 安装校验完成，用时 {format_eta(time.time() - inst_start)}"))
        if inst.returncode != 0:
            raise RuntimeError((inst.stdout + inst.stderr).strip())
        self.q.put(("status", host, f"Codex 已安装 {wanted_version}"))
        self.q.put(("log", host, inst.stdout.strip()))

    def codex_npm_version(self) -> str:
        npm = npm_command()
        self.q.put(("log", "local", f"本机联网查询 @openai/codex 最新 npm 版本，使用 {npm}"))
        cp = run_cmd([npm, "view", "@openai/codex", "version", "--json"], timeout=30)
        if cp.returncode != 0:
            raise RuntimeError("本机 npm 查询 Codex 版本失败：" + (cp.stdout + cp.stderr).strip())
        text = cp.stdout.strip()
        try:
            version = json.loads(text)
        except json.JSONDecodeError:
            version = text.strip('"')
        if not version:
            raise RuntimeError("本机 npm 未返回 Codex 版本")
        return str(version)

    def codex_native_archive(self, version: str, platform: str) -> Path:
        target_dir = CACHE_DIR / "codex-npm" / version
        target_dir.mkdir(parents=True, exist_ok=True)
        expected = target_dir / f"openai-codex-{version}-{platform}.tgz"
        if expected.exists() and expected.stat().st_size > 0:
            self.q.put(("log", "local", f"使用缓存 {expected.name} ({format_bytes(expected.stat().st_size)})"))
            return expected
        spec = f"@openai/codex@{version}-{platform}"
        self.q.put(("log", "local", f"本机联网下载 Codex 原生包：npm pack {spec}"))
        start = time.time()
        cp = run_cmd([npm_command(), "pack", spec, "--pack-destination", str(target_dir), "--loglevel", "warn"], timeout=180)
        if cp.returncode != 0:
            raise RuntimeError("本机 npm 下载 Codex 原生包失败：" + (cp.stdout + cp.stderr).strip())
        packed_name = cp.stdout.strip().splitlines()[-1].strip()
        packed = target_dir / packed_name
        if not packed.exists():
            packed = expected
        if not packed.exists() or packed.stat().st_size == 0:
            raise RuntimeError(f"Codex 原生包下载后未找到：{packed}")
        if packed != expected:
            packed.replace(expected)
        elapsed = max(time.time() - start, 0.001)
        self.q.put(("log", "local", f"Codex 原生包下载完成 {expected.name}  {format_bytes(expected.stat().st_size)}  平均 {format_bytes(expected.stat().st_size / elapsed)}/s"))
        return expected

    def sync_codex_auth(self, host: str) -> None:
        auth = local_codex_auth()
        remote_tmp = f"/tmp/codex-auth-{int(time.time())}.json"
        self.q.put(("log", host, "同步本机 Codex OAuth 到远端 ~/.codex/auth.json（日志不会显示 token）"))
        self.upload_archive(host, auth, remote_tmp)
        cmd = (
            f'set -e; mkdir -p "$HOME/.codex"; '
            f'cp "{remote_tmp}" "$HOME/.codex/auth.json"; chmod 600 "$HOME/.codex/auth.json"; rm -f "{remote_tmp}"; '
            'test -s "$HOME/.codex/auth.json" && echo "auth synced"'
        )
        cp = run_ssh(host, cmd, timeout=30)
        if cp.returncode != 0:
            raise RuntimeError("同步 Codex OAuth 失败：" + (cp.stdout + cp.stderr).strip())
        self.q.put(("log", host, cp.stdout.strip()))


if __name__ == "__main__":
    missing = [tool for tool in ("ssh", "scp", "ssh-keygen") if not shutil.which(tool)]
    if missing:
        messagebox.showerror("缺少依赖", "PATH 中找不到：" + ", ".join(missing))
    else:
        App().mainloop()
