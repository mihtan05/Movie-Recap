# Cài đặt tự động Movie Recap Studio Plugin trên máy Windows (sau khi git clone)
$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Split-Path -Parent $MyInvocation.MyCommand.Path)).Path
$CacheDir = "D:\CLIP\temp_cache"
$PluginInstallDir = Join-Path $env:USERPROFILE ".gemini\config\plugins\movie-recap-studio"

Write-Host "1. Tao thu muc bo dem tam tai $CacheDir ..."
New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null

Write-Host "2. Khoi tao moi truong Python (.venv) tai $RepoRoot\.venv ..."
Set-Location $RepoRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    python -m venv .venv
}
& "$RepoRoot\.venv\Scripts\python.exe" -m pip install -r requirements.txt

Write-Host "3. Dang ky Plugin gon nhe (~20 KB) vao Antigravity ($PluginInstallDir) ..."
New-Item -ItemType Directory -Force -Path $PluginInstallDir | Out-Null
Copy-Item -Force "$RepoRoot\plugin.json" "$PluginInstallDir\plugin.json"
Copy-Item -Recurse -Force "$RepoRoot\assets" "$PluginInstallDir\"
Copy-Item -Recurse -Force "$RepoRoot\rules" "$PluginInstallDir\"
Copy-Item -Recurse -Force "$RepoRoot\agents" "$PluginInstallDir\"
Copy-Item -Recurse -Force "$RepoRoot\skills" "$PluginInstallDir\"

$PyExe = ("$RepoRoot\.venv\Scripts\python.exe") -replace "\\", "\\"
$SrvPy = ("$RepoRoot\mcp_server\server.py") -replace "\\", "\\"
$CacheEsc = $CacheDir -replace "\\", "\\"

@"
{
  "mcpServers": {
    "recap-studio": {
      "command": "$PyExe",
      "args": [
        "$SrvPy"
      ],
      "env": {
        "RECAP_CACHE_ROOT": "$CacheEsc",
        "PYTHONIOENCODING": "utf-8"
      }
    }
  }
}
"@ | Set-Content -Encoding utf8 "$PluginInstallDir\mcp_config.json"

Write-Host "=== HOAN TAT! Mo Antigravity va go: 'Mo khung Movie Recap Studio' ==="
