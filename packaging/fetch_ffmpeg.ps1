# LGPL 빌드 ffmpeg를 packaging\bin\ffmpeg.exe 로 내려받는다 (저장소에는 바이너리를 넣지 않음).
# 출처: BtbN FFmpeg-Builds (win64-lgpl). 사용한 빌드의 출처·라이선스를 THIRD_PARTY_LICENSES에 기재한다.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$bin = Join-Path $here "bin"
New-Item -ItemType Directory -Force $bin | Out-Null
$url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-lgpl.zip"
$zip = Join-Path $env:TEMP "ffmpeg-lgpl.zip"
$tmp = Join-Path $env:TEMP "ffmpeg-lgpl"
Write-Host "Downloading $url"
Invoke-WebRequest $url -OutFile $zip
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
Expand-Archive $zip -DestinationPath $tmp
$exe = Get-ChildItem $tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1
Copy-Item $exe.FullName (Join-Path $bin "ffmpeg.exe") -Force
$lic = Get-ChildItem $tmp -Recurse -Filter LICENSE* | Select-Object -First 1
if ($lic) { Copy-Item $lic.FullName (Join-Path $bin "FFMPEG_LICENSE.txt") -Force }
Set-Content -Encoding utf8 (Join-Path $bin "FFMPEG_SOURCE.txt") "ffmpeg LGPL build from $url (downloaded $(Get-Date -Format s))"
Write-Host "OK: $bin\ffmpeg.exe"
