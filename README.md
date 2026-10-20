# Lecture TTS

강의 스크립트(.md/.txt/.docx/.srt)를 영어 내레이션(mp3/wav)과 자막(SRT/VTT)으로 만드는 앱.
설계: [`lecture tts design.md`](lecture%20tts%20design.md) (v0.5)

- 기본 엔진 **Kokoro-82M** (로컬, 무료) · 경량 **Piper** · 클라우드 **Azure Speech F0** (선택) · 테스트용 **Fake**
- 섹션별 오디오 + 전체 병합본 + SRT/VTT + `manifest.json` + `normalized_script.txt`
- 문장 단위 캐시: 한 문장만 고치면 그 문장만 다시 합성
- **GUI**(PySide6)와 **CLI**(Typer)가 같은 core 파이프라인을 공유

## 다운로드·설치

| 문서 | 내용 |
|---|---|
| [배포 매뉴얼 (Word)](docs/LectureTTS_배포매뉴얼.docx) | 설치 파일 빌드, 배포, 사용자 PC 설치·업데이트·제거, 오프라인 설치 |
| [사용 설명서 (Word)](docs/LectureTTS_사용설명서.docx) | 화면 구성, 스크립트 작성 규칙, 생성·재생, 설정, CLI, 자주 묻는 질문 |

**설치 파일**: [Releases](https://github.com/kjsobaby-collab/freetts/releases)에 `LectureTTS-<버전>-setup.exe`가 올라오면
내려받아 실행하면 됩니다 (Python 불필요, 관리자 권한 불필요). 아직 릴리스가 없으면 아래 소스 설치를 사용하세요.

**소스 설치** (Windows, Python 3.12 필요):

```powershell
git clone https://github.com/kjsobaby-collab/freetts.git
cd freetts
py -3.12 -m venv .venv
.venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu   # NVIDIA GPU는 pytorch.org의 CUDA용 명령 사용
.venv\Scripts\pip install -e ".[kokoro,gui,docx]"
.venv\Scripts\pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl
powershell -ExecutionPolicy Bypass -File packaging\fetch_ffmpeg.ps1   # PATH에 ffmpeg가 있으면 생략
.venv\Scripts\lecture-tts setup kokoro   # 음성 모델 다운로드 (약 330MB, 최초 1회)
.venv\Scripts\lecture-tts-gui
```

## 개발 환경 실행

```powershell
.venv\Scripts\activate
pip install -e ".[kokoro,gui,docx,dev]"

lecture-tts-gui                       # GUI
lecture-tts build lecture03.md        # CLI
pytest                                # 테스트 (FakeEngine, 모델 불필요)
```

설치하지 않고 실행: `$env:PYTHONPATH="src"; python -m lecture_tts gui`

## CLI

```bash
lecture-tts setup kokoro                          # 모델 사전 다운로드 (최초 1회)
lecture-tts build lecture03.md                    # 전체 생성 (mp3)
lecture-tts build lecture03.md --sections 2,5-7   # 일부 섹션만
lecture-tts build lecture03.md -v am_michael -r 0.95 -f wav -o out
lecture-tts build lecture03.md --engine piper     # 빠른 초안 (pip install piper-tts; setup piper)
lecture-tts preview lecture03.md --show chunks --estimate-cost
lecture-tts audition --voices af_heart,bf_emma --rates 0.9,1.0
lecture-tts batch ./scripts --glob "*.md"
lecture-tts voices --engine kokoro
lecture-tts cache info | cache clear
```

출력: `<스크립트 폴더>/output/<스크립트 이름>/` (설정 `runtime.output_dir` 또는 `-o`로 변경)

## 스크립트 문법

`## Slide N: 제목` · `[SLIDE N]` · `Slide N. 제목` 섹션 구분, `[pause 1s]`/`[pause]` 쉼, `{SQL|sequel}` 발음 지정,
`*강조*`, `[speaker: student]`, `[rate 0.9]`, `<!-- 주석 -->`. 자세한 표는 앱의 도움말 → 스크립트 문법
(`src/lecture_tts/data/syntax_help.md`).

## 설정

우선순위: CLI 옵션 > `--config` 파일 > 사용자 설정(`%LOCALAPPDATA%\LectureTTS\settings.yaml`, GUI 환경설정) >
기본값(`src/lecture_tts/data/default.yaml`). 발음 사전: `%LOCALAPPDATA%\LectureTTS\lexicon.yaml`.

## 구조

```
src/lecture_tts/
  loaders.py parser.py normalizer/ chunker.py      텍스트 → 청크
  engines/ (kokoro, piper, azure, fake, registry)  TTS 어댑터
  cache.py synthesizer.py assembler.py subtitles.py
  pipeline.py progress.py cli.py doctor.py
  gui/ (app, main_window, workers, project, widgets/, dialogs/)
packaging/  PyInstaller spec, Inno Setup, ffmpeg(LGPL) 다운로드, build.ps1
tests/      parser·normalizer·chunker·e2e·GUI(pytest-qt)
```

## Windows 배포판 빌드

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1            # 온라인 설치판
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -Offline   # 모델 포함 오프라인 설치판
```

CPU용 torch 가상환경(`.venv-build`)을 만들고 PyInstaller(onedir) → ffmpeg 동봉 → 라이선스 목록 → Inno Setup 설치 파일
(`dist\installer\*.exe` + SHA-256)을 만든다. Inno Setup 6 필요. 배포 전 설계 문서 8.10.8 릴리스 체크리스트를 확인한다.
