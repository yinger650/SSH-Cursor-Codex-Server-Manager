@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Update Cursor remote server on an SSH host that cannot download from the internet.
rem Usage:
rem   update-cursor-server.bat [ssh-host]
rem
rem Optional environment overrides:
rem   CURSOR_APP=E:\apps\cursor\resources\app
rem   CURSOR_COMMIT=81fcf2931d7687b4ff3f3017858d0c6dee7e2a68
rem   CURSOR_SERVER_CACHE=E:\some\cache
rem   CURSOR_SCP_OPTS=-O

set "SSH_HOST=%~1"
if not defined SSH_HOST set "SSH_HOST=sdtp01"

set "SCRIPT_DIR=%~dp0"
set "CACHE_DIR=%CURSOR_SERVER_CACHE%"
if not defined CACHE_DIR set "CACHE_DIR=%SCRIPT_DIR%cache"
set "SCP_OPTS=%CURSOR_SCP_OPTS%"
if not defined SCP_OPTS set "SCP_OPTS=-O"

where ssh >nul 2>nul || (
  echo [ERROR] ssh not found in PATH.
  exit /b 1
)
where scp >nul 2>nul || (
  echo [ERROR] scp not found in PATH.
  exit /b 1
)
where powershell >nul 2>nul || (
  echo [ERROR] powershell not found in PATH.
  exit /b 1
)

for /f "usebackq delims=" %%A in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $app=$env:CURSOR_APP; if (-not $app) { $cmd=(Get-Command cursor -ErrorAction SilentlyContinue).Source; if ($cmd) { $app=Split-Path (Split-Path $cmd -Parent) -Parent } }; if (-not $app) { $candidates=@(\"$env:LOCALAPPDATA\Programs\Cursor\resources\app\", \"$env:LOCALAPPDATA\Programs\cursor\resources\app\", \"e:\apps\cursor\resources\app\"); $app=$candidates | Where-Object { Test-Path (Join-Path $_ 'product.json') } | Select-Object -First 1 }; if (-not $app -or -not (Test-Path (Join-Path $app 'product.json'))) { throw 'Cursor app folder not found. Set CURSOR_APP to the folder containing product.json.' }; $product=Get-Content (Join-Path $app 'product.json') -Raw | ConvertFrom-Json; $pkg=Get-Content (Join-Path $app 'package.json') -Raw | ConvertFrom-Json; $commit=$env:CURSOR_COMMIT; if (-not $commit) { $commit=$product.realCommit }; if (-not $commit) { $commit=$product.commit }; if (-not $commit) { $commit=$pkg.distro }; if (-not $commit) { throw 'Cannot read commit from Cursor product.json.' }; $version=$pkg.version; Write-Output ('set CURSOR_APP_RESOURCES=' + $app); Write-Output ('set CURSOR_COMMIT=' + $commit); Write-Output ('set CURSOR_VERSION=' + $version)"`) do %%A
if errorlevel 1 exit /b 1

echo [INFO] SSH host: %SSH_HOST%
echo [INFO] Cursor app: %CURSOR_APP_RESOURCES%
echo [INFO] Cursor version: %CURSOR_VERSION%
echo [INFO] Cursor commit: %CURSOR_COMMIT%

for /f "usebackq delims=" %%A in (`ssh "%SSH_HOST%" "uname -s; uname -m"`) do (
  if not defined REMOTE_OS (
    set "REMOTE_OS=%%A"
  ) else if not defined REMOTE_MACHINE (
    set "REMOTE_MACHINE=%%A"
  )
)
if errorlevel 1 (
  echo [ERROR] Failed to query remote OS/architecture from %SSH_HOST%.
  exit /b 1
)

if /i not "%REMOTE_OS%"=="Linux" (
  echo [ERROR] Only Linux remote hosts are supported by this script. Remote OS: %REMOTE_OS%
  exit /b 1
)

if /i "%REMOTE_MACHINE%"=="x86_64" (
  set "REMOTE_ARCH=x64"
) else if /i "%REMOTE_MACHINE%"=="amd64" (
  set "REMOTE_ARCH=x64"
) else if /i "%REMOTE_MACHINE%"=="aarch64" (
  set "REMOTE_ARCH=arm64"
) else if /i "%REMOTE_MACHINE%"=="arm64" (
  set "REMOTE_ARCH=arm64"
) else (
  echo [ERROR] Unsupported remote architecture: %REMOTE_MACHINE%
  exit /b 1
)

set "REMOTE_PLATFORM=linux-%REMOTE_ARCH%"
set "ARCHIVE_NAME=vscode-reh-%REMOTE_PLATFORM%-%CURSOR_COMMIT%.tar.gz"
set "ARCHIVE_PATH=%CACHE_DIR%\%ARCHIVE_NAME%"
for /f "usebackq delims=" %%A in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$url='https://downloads.cursor.com/production/' + $env:CURSOR_COMMIT + '/linux/' + $env:REMOTE_ARCH + '/cursor-reh-linux-' + $env:REMOTE_ARCH + '.tar.gz'; Write-Output ('set DOWNLOAD_URL=' + $url)"`) do %%A

echo [INFO] Remote platform: %REMOTE_PLATFORM%
echo [INFO] Download URL: %DOWNLOAD_URL%

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $cache='%CACHE_DIR%'; $archive='%ARCHIVE_PATH%'; $url='%DOWNLOAD_URL%'; New-Item -ItemType Directory -Force $cache | Out-Null; if ((Test-Path $archive) -and ((Get-Item $archive).Length -gt 0)) { Write-Host '[INFO] Using cached archive:' $archive } else { Write-Host '[INFO] Downloading archive to:' $archive; Invoke-WebRequest -Uri $url -OutFile $archive }; $size=[Math]::Round((Get-Item $archive).Length/1MB, 1); Write-Host ('[INFO] Archive size: {0} MB' -f $size)"
if errorlevel 1 (
  echo [ERROR] Failed to download Cursor server archive.
  exit /b 1
)

set "REMOTE_TMP=/tmp/%ARCHIVE_NAME%"
set "REMOTE_DIR=.cursor-server/bin/%REMOTE_PLATFORM%/%CURSOR_COMMIT%"

echo [INFO] Uploading archive to %SSH_HOST%:%REMOTE_TMP%
scp %SCP_OPTS% "%ARCHIVE_PATH%" "%SSH_HOST%:%REMOTE_TMP%"
if errorlevel 1 (
  echo [ERROR] Upload failed.
  exit /b 1
)

echo [INFO] Installing Cursor server on %SSH_HOST%
ssh "%SSH_HOST%" "set -e; target=\"$HOME/%REMOTE_DIR%\"; tmp='%REMOTE_TMP%'; mkdir -p \"$target\"; if [ -x \"$target/bin/cursor-server\" ] && [ -x \"$target/node\" ] && [ -f \"$target/product.json\" ]; then echo '[INFO] Existing install looks complete, refreshing files anyway.'; fi; find \"$target\" -mindepth 1 ! -name 'cursor-server-*.tar.gz' -exec rm -rf {} + 2>/dev/null || true; tar -xzf \"$tmp\" -C \"$target\" --strip-components=1; chmod +x \"$target/bin/cursor-server\" \"$target/node\" 2>/dev/null || true; rm -f \"$tmp\"; test -x \"$target/bin/cursor-server\"; test -x \"$target/node\"; test -f \"$target/product.json\"; echo '[OK] Installed at' \"$target\"; \"$target/node\" --version"
if errorlevel 1 (
  echo [ERROR] Remote install or verification failed.
  exit /b 1
)

echo [OK] Cursor server %CURSOR_VERSION% / %CURSOR_COMMIT% is ready on %SSH_HOST%.
exit /b 0
