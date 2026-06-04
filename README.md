# SSH Cursor/Codex Server Manager

[English README](README.en.md)

一个用于维护 SSH 服务器上 Cursor Remote Server 和 Codex CLI 的 Windows 图形化工具，特别适合目标服务器无法直接访问公网的环境。

工具会读取本机 SSH config，列出所有 SSH Host，测试可达性，并把本机下载好的 Cursor/Codex 安装包通过 SSH/SCP 上传到远端服务器进行离线安装。

## 解决什么问题

Cursor 和 Codex 通过 SSH 连接远端机器时，通常需要在远端安装对应的 server/CLI 组件。如果服务器没有公网访问权限，自动下载会失败，连接就容易卡住或反复要求登录。

这个工具把所有联网任务放在本机完成：

- 本机下载 Cursor server 压缩包
- 本机通过 npm 下载 Codex Linux 原生包
- 通过 SSH/SCP 上传到远端
- 在远端离线安装或更新
- 将本机 Codex OAuth 登录信息复制到远端用户，减少重复登录

## 功能

- 从 `~/.ssh/config` 读取 SSH Host
- 显示 SSH 别名、目标用户/主机/端口和当前状态
- 测试 SSH 可达性
- 自动处理远端主机 fingerprint 变化导致的 `known_hosts` 问题
- SSH key 不可用时弹窗输入密码
- 清晰显示网络不可达、连接超时、拒绝连接等错误
- 检查并安装/更新 Linux 服务器上的 Cursor server
- 检查并安装/更新 Linux 服务器上的 Codex CLI
- 将本机 Codex OAuth 从 `~/.codex/auth.json` 同步到远端 `~/.codex/auth.json`
- 显示本机 Cursor 版本和 server commit
- 显示本机 Codex 版本和 runtime 信息
- 长时间下载、上传、安装时持续输出进度日志
- 支持通过桌面快捷方式启动，不弹出 cmd 窗口

## 支持范围

当前版本主要面向这个场景：

- 本机：Windows
- 远端服务器：Linux `x86_64` 或 Linux `aarch64/arm64`
- SSH 客户端：本机 PATH 中可用 `ssh`
- SCP 客户端：本机 PATH 中可用 `scp`

暂不支持远端 macOS 或 Windows SSH 服务器。

## 依赖

本机 Windows 需要安装：

- Python 3，且包含 Tkinter
- OpenSSH 客户端：`ssh`、`scp`、`ssh-keygen`
- Node.js/npm，用于本机下载 Codex 包
- Cursor，如果需要更新 Cursor server
- Codex 桌面端/CLI 登录状态，如果需要同步 OAuth 到远端

远端 Linux 服务器需要具备：

- `sh`/`bash`
- `tar`
- `gzip`
- 对安装目录的写入权限

root 用户登录时，Codex 会安装到：

```text
/opt/openai-codex/<version>
```

并写入启动脚本：

```text
/usr/bin/codex
```

非 root 用户登录时，Codex 会安装到：

```text
~/.local/share/openai-codex/<version>
```

并写入启动脚本：

```text
~/.local/bin/codex
```

## 使用方式

克隆或复制本仓库后运行：

```bat
start-gui.bat
```

也可以直接运行：

```powershell
python ssh_server_manager.py
```

GUI 会读取：

```text
%USERPROFILE%\.ssh\config
```

选择一个 Host 后可以点击：

- `测试可达`：测试 SSH 是否可连接
- `检查 Cursor`：检查并安装/更新 Cursor server
- `检查 Codex`：检查并安装/更新 Codex CLI，同时同步 OAuth
- `全部测试可达`：测试所有 Host
- `全部检查 Cursor`：检查所有 Host 的 Cursor server
- `全部检查 Codex`：检查所有 Host 的 Codex CLI

## Cursor 更新流程

点击 `检查 Cursor` 后，工具会：

1. 探测本机 Cursor 安装目录。
2. 从 `product.json` 读取本机 Cursor 版本和 `realCommit`。
3. 通过 `uname` 探测远端 Linux 架构。
4. 在本机下载匹配的 Cursor server 压缩包。
5. 将压缩包缓存到 `cache/`。
6. 上传压缩包到远端 `/tmp`。
7. 解压到远端 `~/.cursor-server/bin/<platform>/<commit>`。
8. 校验 `bin/cursor-server`、`node` 和 `product.json`。

也可以使用独立 bat 脚本：

```bat
update-cursor-server.bat sdtp01
```

可用环境变量：

```bat
set CURSOR_APP=E:\apps\cursor\resources\app
set CURSOR_COMMIT=<cursor-real-commit>
set CURSOR_SERVER_CACHE=E:\some\cache
set CURSOR_SCP_OPTS=-O
```

## Codex 安装流程

点击 `检查 Codex` 后，工具会：

1. 探测远端 Linux 架构。
2. 在本机查询最新 `@openai/codex` npm 版本。
3. 在本机通过 `npm pack` 下载匹配的 Linux 原生包。
4. 将包缓存到 `cache/codex-npm/<version>/`。
5. 上传包到远端 `/tmp`。
6. 在远端离线解压原生 `codex` 可执行文件。
7. 写入远端 `codex` 启动脚本到 PATH 中。
8. 将本机 `%USERPROFILE%\.codex\auth.json` 复制到远端 `~/.codex/auth.json`。
9. 设置 OAuth 文件权限为 `600`。
10. 校验 `codex --version` 和 auth 文件是否存在。

这个流程不要求远端服务器安装 npm，也不要求远端能访问公网。

## 安全说明

Codex OAuth 同步会复制本机登录 token 文件：

```text
%USERPROFILE%\.codex\auth.json
```

到远端：

```text
~/.codex/auth.json
```

请只在你信任的服务器和账号上使用。工具会把远端文件权限设置为 `600`，但远端 root 用户仍然可以读取该文件。日志中不会打印 token 内容。

## 缓存目录

下载的包会缓存到：

```text
cache/
```

重复检查或安装时会优先使用缓存，避免反复下载。

## 已知限制

- 本机支持以 Windows 为主。
- 远端服务器目前只支持 Linux。
- Cursor 更新目前只下载 Linux remote server 包。
- Codex OAuth 同步依赖本机存在 `~/.codex/auth.json`。
- 密码登录依赖 SSH askpass，不同 OpenSSH 版本表现可能有差异。
- 当前还没有打包成安装器。

## 项目文件

- `ssh_server_manager.py`：Tkinter GUI 和主要逻辑
- `start-gui.bat`：启动 GUI
- `update-cursor-server.bat`：独立 Cursor server 更新脚本
- `ssh-server-manager.ico`：桌面快捷方式图标
- `cache/`：本地下载缓存，通常不应提交到仓库

## License

MIT License. See [LICENSE](LICENSE) for details.
