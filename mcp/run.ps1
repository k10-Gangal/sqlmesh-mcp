# Start the MCP without Docker (Windows PowerShell). Reads .\.env if present.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (Test-Path .env) {
  Get-Content .env | Where-Object { $_ -match '^\s*[^#\s][^=]*=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    $v = $v.Trim()
    if ($v.Length -ge 2 -and $v.StartsWith("'") -and $v.EndsWith("'")) { $v = $v.Substring(1, $v.Length - 2) }
    Set-Item -Path "Env:$($k.Trim())" -Value $v
  }
}
if (-not $env:CONNECTION_JSON) { throw "Set CONNECTION_JSON (copy .env.example to .env and fill it in)" }
if (-not (Test-Path .venv)) {
  python -m venv .venv
  & .\.venv\Scripts\pip install -r requirements.txt
}
& .\.venv\Scripts\python server.py
