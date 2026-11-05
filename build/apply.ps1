# 새로 빌드한 exe로 교체 (앱을 먼저 종료: ⚙설정 → 서버 종료)
# 사용: powershell -ExecutionPolicy Bypass -File build\apply.ps1
$ErrorActionPreference = 'Stop'
$base = Split-Path $PSScriptRoot
$name = 'W.S.T'
$new = Join-Path $PSScriptRoot "dist\$name"
if (Get-Process -Name $name -ErrorAction SilentlyContinue) { throw '앱이 아직 실행 중입니다. ⚙설정 → 서버 종료 후 다시 실행하세요.' }
Remove-Item (Join-Path $base '_internal') -Recurse -Force -ErrorAction SilentlyContinue
Move-Item (Join-Path $new '_internal') (Join-Path $base '_internal')
Move-Item (Join-Path $new "$name.exe") (Join-Path $base "$name.exe") -Force
Write-Host "교체 완료: $(Join-Path $base "$name.exe")"
