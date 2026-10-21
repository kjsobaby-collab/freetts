# Windows 배포판 빌드: CPU용 torch 가상환경 → PyInstaller(onedir) → 라이선스 목록 → Inno Setup 설치 파일
# 사용: powershell -ExecutionPolicy Bypass -File packaging\build.ps1 [-SkipVenv] [-Offline]
#   -Offline : Kokoro 모델을 설치 파일에 포함 (인터넷 없는 기관용 오프라인 패키지)
param([switch]$SkipVenv, [switch]$Offline)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$venv = Join-Path $root ".venv-build"
$py = Join-Path $venv "Scripts\python.exe"

if (-not $SkipVenv) {
    if (-not (Test-Path $py)) { py -3.12 -m venv $venv }
    & $py -m pip install --upgrade pip
    # 배포판은 CPU용 torch (어느 PC에서나 동작, 용량 절감)
    & $py -m pip install torch --index-url https://download.pytorch.org/whl/cpu
    & $py -m pip install -e ".[kokoro,gui,docx]" pyinstaller pip-licenses
    & $py -m pip install en_core_web_sm@https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
}

if (-not (Test-Path "packaging\bin\ffmpeg.exe")) { & "$root\packaging\fetch_ffmpeg.ps1" }

if ($root.Length -gt 60) { Write-Warning "프로젝트 경로가 깁니다($($root.Length)자). Windows 경로 길이 제한(260자) 때문에 설치 파일 단계가 실패할 수 있습니다." }
# PyInstaller는 DLL 의존성을 PATH에서 찾는다. 빌드 PC의 Anaconda 등 다른 DLL이 섞이지 않도록 PATH를 최소화한다.
$savedPath = $env:PATH
$env:PATH = "$venv\Scripts;$env:SystemRoot\System32;$env:SystemRoot;$env:SystemRoot\System32\Wbem"
& $py -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging\lecture_tts_gui.spec
$env:PATH = $savedPath
$app = Join-Path $root "dist\LectureTTS"
New-Item -ItemType Directory -Force (Join-Path $app "bin") | Out-Null
Copy-Item packaging\bin\* (Join-Path $app "bin") -Force

# 오픈소스 라이선스 고지
& $py -m piplicenses --format=plain-vertical --with-license-file --no-license-path --output-file (Join-Path $app "THIRD_PARTY_LICENSES.txt")
Get-Content src\lecture_tts\data\THIRD_PARTY_NOTICES.md | Add-Content (Join-Path $app "THIRD_PARTY_LICENSES.txt")

# 예제 스크립트
New-Item -ItemType Directory -Force (Join-Path $app "samples") | Out-Null
Copy-Item src\lecture_tts\data\lecture_sample.md (Join-Path $app "samples") -Force

if ($Offline) {
    $env:HF_HOME = Join-Path $app "models"
    & $py -c "from lecture_tts.engines.kokoro_engine import download_model; download_model()"
}

$version = & $py -c "import lecture_tts; print(lecture_tts.__version__)"
$size = "{0:N0} MB" -f ((Get-ChildItem $app -Recurse | Measure-Object Length -Sum).Sum / 1MB)
Write-Host "앱 폴더 크기: $size (설계 문서 8.9에 기록)"

# Inno Setup: 시스템 설치(Program Files) 또는 사용자별 설치(winget 기본) 경로
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (Test-Path $iscc) {
    $defs = @("/DAppVersion=$version")
    if ($Offline) { $defs += "/DOffline=1" }
    & $iscc @defs packaging\installer.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup 컴파일 실패 (exit $LASTEXITCODE). 경로가 너무 길면 짧은 폴더(예: D:\lecture-tts)에서 빌드하세요." }
    Get-ChildItem dist\installer\*.exe | ForEach-Object {
        $h = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
        "$h  $($_.Name)" | Tee-Object -FilePath "$($_.FullName).sha256"
    }
} else {
    Write-Warning "Inno Setup 6이 없습니다: https://jrsoftware.org/isdl.php — 설치 후 다시 실행하세요."
}
