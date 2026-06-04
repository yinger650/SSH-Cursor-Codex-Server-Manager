# SSH Cursor/Codex Server Manager

[中文说明](README.md)

A small Windows GUI for maintaining Cursor Remote SSH server files and Codex CLI installs on Linux SSH servers, especially when the servers cannot access the public internet.

The tool reads your local SSH config, lists all configured hosts, tests connectivity, and can upload locally downloaded Cursor/Codex packages to remote servers for offline installation.

## Why

Cursor and Codex often need a matching server-side component on each SSH target. That is painful when your SSH servers are behind restricted networks and cannot download packages by themselves.

This tool keeps the network work on your local Windows machine:

- download Cursor server archives locally
- download Codex Linux native packages locally with npm
- upload packages over SSH/SCP
- install or update the remote files offline
- copy local Codex OAuth auth to the remote user so repeated login is not needed

## Features

- Load hosts from `~/.ssh/config`
- Show SSH alias, target user/host/port, and status
- Test SSH reachability
- Automatically refresh changed host fingerprints in `known_hosts`
- Prompt for SSH password when key authentication is not enough
- Report unreachable network errors clearly
- Check and install/update Cursor server for Linux SSH targets
- Check and install/update Codex CLI for Linux SSH targets
- Sync local Codex OAuth from `~/.codex/auth.json` to remote `~/.codex/auth.json`
- Show local Cursor version and server commit
- Show local Codex version/runtime info
- Log long operations with clear progress messages
- Run from a desktop shortcut without opening a cmd window

## Supported Platforms

Current scope:

- Local machine: Windows
- Remote machines: Linux `x86_64` or Linux `aarch64/arm64`
- SSH client: OpenSSH available in `PATH`
- SCP client: OpenSSH `scp` available in `PATH`

Remote macOS and Windows SSH targets are not supported yet.

## Requirements

Install these on the local Windows machine:

- Python 3 with Tkinter
- OpenSSH client: `ssh`, `scp`, `ssh-keygen`
- Node.js/npm, used to download Codex packages locally
- Cursor, if you want Cursor server update support
- Codex desktop/CLI login, if you want OAuth sync to remote hosts

The remote Linux server should have:

- `sh`/`bash`
- `tar`
- `gzip`
- write permission for the target install path

For root SSH users, Codex is installed under `/opt/openai-codex/<version>` and a shim is written to `/usr/bin/codex`.

For non-root SSH users, Codex is installed under `~/.local/share/openai-codex/<version>` and a shim is written to `~/.local/bin/codex`.

## Usage

Clone or copy this repository, then run:

```bat
start-gui.bat
```

Or run directly:

```powershell
python ssh_server_manager.py
```

The GUI will load hosts from:

```text
%USERPROFILE%\.ssh\config
```

Select a host and use:

- `测试可达`: test SSH connectivity
- `检查 Cursor`: check/install Cursor server
- `检查 Codex`: check/install Codex CLI and sync OAuth
- `全部测试可达`: test all hosts
- `全部检查 Cursor`: check Cursor on all hosts
- `全部检查 Codex`: check Codex on all hosts

## Cursor Update Flow

For Cursor, the tool:

1. Detects the local Cursor install.
2. Reads local Cursor version and `realCommit` from `product.json`.
3. Detects remote Linux architecture with `uname`.
4. Downloads the matching Cursor server archive locally from Cursor's download endpoint.
5. Caches the archive under `cache/`.
6. Uploads it to `/tmp` on the remote server.
7. Extracts it into `~/.cursor-server/bin/<platform>/<commit>`.
8. Verifies `bin/cursor-server`, `node`, and `product.json`.

You can also use the standalone batch script:

```bat
update-cursor-server.bat sdtp01
```

Useful environment variables:

```bat
set CURSOR_APP=E:\apps\cursor\resources\app
set CURSOR_COMMIT=<cursor-real-commit>
set CURSOR_SERVER_CACHE=E:\some\cache
set CURSOR_SCP_OPTS=-O
```

## Codex Install Flow

For Codex, the tool:

1. Detects the remote Linux architecture.
2. Queries the latest `@openai/codex` npm version locally.
3. Downloads the matching Linux native package locally with `npm pack`.
4. Caches it under `cache/codex-npm/<version>/`.
5. Uploads the package to `/tmp` on the remote server.
6. Extracts the native `codex` binary offline.
7. Writes a small `codex` shim into the remote user's PATH.
8. Copies local `%USERPROFILE%\.codex\auth.json` to remote `~/.codex/auth.json`.
9. Sets OAuth file permissions to `600`.
10. Verifies `codex --version` and auth file presence.

The remote server does not need npm or internet access for this install path.

## Security Notes

Codex OAuth sync copies your local Codex login token file:

```text
%USERPROFILE%\.codex\auth.json
```

to:

```text
~/.codex/auth.json
```

on the remote server.

Only use this on servers and accounts you trust. The tool sets file mode to `600`, but anyone with root access on the remote server can still read it. Logs intentionally do not print token contents.

## Cache

Downloaded packages are cached in:

```text
cache/
```

This allows repeated installs to reuse local packages without downloading again.

## Known Limitations

- Local machine support is Windows-focused.
- Remote server support is Linux-only.
- Cursor support currently targets Linux remote server archives.
- Codex OAuth sync assumes the local Codex login is stored in `~/.codex/auth.json`.
- Password authentication uses an SSH askpass helper and may vary depending on the local OpenSSH build.
- The tool does not package itself as an installer yet.

## Project Files

- `ssh_server_manager.py`: Tkinter GUI and main logic
- `start-gui.bat`: starts the GUI
- `update-cursor-server.bat`: standalone Cursor server update script
- `ssh-server-manager.ico`: icon used for the desktop shortcut
- `cache/`: local package cache, usually not meant to be committed

## License

MIT License. See [LICENSE](LICENSE) for details.
