# Lecture Script → English TTS 생성기 설계 및 구현 문서

> 버전: v0.5 · 작성일: 2026-10-20
> 변경: TTS 엔진을 무료 구성으로 확정 — 기본 **Kokoro**(로컬), 보조 **Piper**(로컬 경량), **Azure Speech F0**(클라우드 무료 티어) / v0.3: 출력 기본값 mp3 확정, 음성 비교(audition) 추가 / v0.4: **GUI 데스크톱 앱(PySide6)** 설계 추가(8장) / v0.5: **외부 배포 확정** — 배포 요구사항(8.10) 추가, 설치 파일 필수화
> 목적: 강의 스크립트 파일을 입력받아 영어 음성(TTS) 파일을 생성하는 프로그램의 설계와 단계별 구현 계획을 정의한다.

---

## 1. 개요

### 1.1 배경
강의 영상·오디오 콘텐츠를 만들 때 원고(스크립트)를 사람이 직접 녹음하면 시간이 많이 들고, 수정할 때마다 재녹음이 필요하다. 이 프로그램은 스크립트 파일만 수정하면 일관된 품질의 영어 내레이션을 자동으로 다시 만들 수 있도록 하는 것을 목표로 한다.

### 1.2 목표
- 강의 스크립트(텍스트 기반 파일)를 입력으로 받아 영어 음성 파일을 생성한다.
- 슬라이드/섹션 단위로 오디오를 분할 출력하고, 전체를 하나로 합친 파일도 제공한다.
- 자막 파일(SRT/VTT)을 함께 생성하여 영상 편집에 바로 쓸 수 있게 한다.
- TTS 엔진을 교체할 수 있도록 엔진 계층을 추상화한다.
- 변경된 문장만 다시 합성하도록 캐시를 둔다(비용·시간 절감).
- 터미널 없이 쓸 수 있는 **GUI 데스크톱 앱**과, 자동화·일괄 처리용 **CLI**를 함께 제공한다(같은 core 공유).

### 1.3 범위 밖 (Non-goals, v1 기준)
- 한국어 → 영어 번역 (입력은 영어 스크립트로 가정. 번역은 v2 확장 항목)
- 영상 합성(슬라이드 이미지 + 오디오 → mp4)
- 다중 사용자 웹 서비스(서버 배포) 형태

---

## 2. 요구사항

### 2.1 기능 요구사항

| ID | 요구사항 | 우선순위 |
|---|---|---|
| F1 | `.txt`, `.md` 스크립트 입력 지원 | 필수 |
| F2 | `.docx`, `.srt` 입력 지원 | 선택 |
| F3 | 슬라이드/섹션 구분 마커 인식 (예: `## Slide 3`, `[SLIDE 3]`) | 필수 |
| F4 | 쉼(pause), 강조, 발음 지정 등 인라인 지시어 지원 | 필수 |
| F5 | 텍스트 정규화 (숫자, 약어, 기호, 수식, 코드 등 읽기 변환) | 필수 |
| F6 | 엔진별 글자 수 제한에 맞춘 문장 단위 청킹 | 필수 |
| F7 | 화자 음성(voice), 속도, 피치, 출력 포맷 설정 | 필수 |
| F8 | 섹션별 오디오 + 전체 병합 오디오 출력 (mp3/wav) | 필수 |
| F9 | 자막(SRT/VTT) 및 타임스탬프 JSON 출력 | 필수 |
| F10 | 문장 단위 캐시 및 증분 재생성 | 필수 |
| F11 | 사용자 발음 사전(용어집) | 권장 |
| F12 | 드라이런(dry-run): 합성 없이 정규화 결과·예상 비용 미리보기 | 권장 |
| F13 | 다중 화자(예: 강사/질문자) 지원 | 선택 |
| G1 | GUI: 스크립트 열기·편집(구문 강조)·저장 | 필수 |
| G2 | GUI: 섹션 목록과 섹션별 생성 상태 표시, 섹션 단위 생성 | 필수 |
| G3 | GUI: 엔진·음성·속도·출력 포맷(기본 mp3) 설정 패널 | 필수 |
| G4 | GUI: 진행률·남은 시간·중지, 생성 중에도 창이 멈추지 않음 | 필수 |
| G5 | GUI: 섹션/전체 오디오 재생 + 재생 중 문장 하이라이트 | 필수 |
| G6 | GUI: 선택 영역 즉시 듣기, 정규화 미리보기 | 권장 |
| G7 | GUI: 초기 설정 마법사(의존성 점검·모델 다운로드) | 권장 |
| G8 | GUI: 음성 비교 창, 발음 사전 편집기 | 권장 |
| G9 | Windows 설치 파일 배포 (Python 없는 PC에서 설치·실행) | **필수** |
| G10 | 오프라인 설치 지원 (모델 포함 설치 패키지 또는 모델 파일 가져오기) | 권장 |
| G11 | 버전 표시·업데이트 확인, 오류 보고용 로그 내보내기 | 권장 |

### 2.2 비기능 요구사항
- **확장성**: 새 TTS 엔진은 어댑터 클래스 하나 추가로 연결 가능해야 한다.
- **안정성**: API 오류 시 지수 백오프 재시도, 부분 실패 시 실패한 청크만 재시도.
- **성능**: 청크 단위 병렬 합성 (동시성 제한 설정 가능).
- **재현성**: 같은 입력 + 같은 설정이면 같은 결과(캐시 키에 설정 포함).
- **보안**: API 키는 환경변수 또는 `.env`로만 관리, 로그에 노출 금지.
- **이식성**: Windows / macOS / Linux에서 동작 (ffmpeg 의존).

---

## 3. 입력 스크립트 형식

### 3.1 기본 형식 (Markdown 권장)

```markdown
# Lecture 3: Introduction to Neural Networks

## Slide 1: Welcome
Hello everyone, and welcome to lecture three. [pause 1s]
Today we'll talk about *neural networks*.

## Slide 2: What is a Perceptron?
A perceptron computes a weighted sum, w·x + b. [pause 500ms]
We use {ReLU|R-E-L-U} as the activation function.

<!-- 이 줄은 주석이므로 읽지 않음 -->
```

### 3.2 마커 및 지시어 문법

| 문법 | 의미 | 예시 |
|---|---|---|
| `# 제목` | 강의 제목 (메타데이터, 기본값: 읽지 않음) | `# Lecture 3` |
| `## Slide N: 제목` / `[SLIDE N]` | 섹션 구분 → 개별 오디오 파일 단위 | `## Slide 2: Intro` |
| `[pause 1s]`, `[pause 500ms]` | 지정 시간 무음 | `[pause 2s]` |
| `*단어*` | 강조 (SSML `<emphasis>`) | `*important*` |
| `{표기\|읽기}` | 발음 지정 (표기는 자막에, 읽기는 음성에) | `{SQL\|sequel}` |
| `[speaker: name]` | 이후 문단의 화자 전환 | `[speaker: student]` |
| `[rate 0.9]` | 이후 문단 속도 변경 | `[rate 0.85]` |
| `<!-- ... -->` | 주석, 무시 | |
| 빈 줄 | 문단 구분 → 기본 문단 간 쉼 삽입 | |

> 마커 정규식은 설정 파일에서 변경 가능하게 하여 기존 스크립트 양식에도 맞출 수 있도록 한다.

---

## 4. 시스템 아키텍처

### 4.1 처리 파이프라인

```
 ┌──────────┐   ┌──────────┐   ┌────────────┐   ┌──────────┐
 │  Loader  │──▶│  Parser  │──▶│ Normalizer │──▶│ Chunker  │
 └──────────┘   └──────────┘   └────────────┘   └──────────┘
   파일 읽기       섹션/지시어      숫자·약어·기호       엔진 한도에 맞게
   인코딩 처리     → 문서 모델(AST)  읽기 변환          문장 단위 분할
                                                        │
                                                        ▼
 ┌──────────┐   ┌───────────────┐   ┌─────────┐   ┌──────────────┐
 │ Exporter │◀──│ AudioAssembler│◀──│  Cache  │◀──│ TTS Adapter  │
 └──────────┘   └───────────────┘   └─────────┘   └──────────────┘
  mp3/wav,        청크 연결, 쉼 삽입,   해시 기반        SSML 생성 +
  SRT/VTT,        음량 정규화,          재사용          엔진 API 호출
  manifest.json   타임스탬프 계산
```

### 4.2 핵심 데이터 모델

```python
# models.py
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class Directive:
    kind: Literal["pause", "emphasis", "phoneme", "speaker", "rate"]
    value: str | float | None = None

@dataclass
class Segment:
    """정규화 이전/이후 텍스트 조각. 지시어가 섞여 있을 수 있다."""
    display_text: str          # 자막에 표시될 원문
    spoken_text: str           # 실제로 읽힐 텍스트 (정규화 후)
    directives: list[Directive] = field(default_factory=list)

@dataclass
class Paragraph:
    segments: list[Segment]
    speaker: str = "default"
    rate: float = 1.0

@dataclass
class Section:
    index: int
    title: str | None
    paragraphs: list[Paragraph]

@dataclass
class LectureDocument:
    title: str | None
    sections: list[Section]
    source_path: str

@dataclass
class Chunk:
    """TTS 엔진 1회 호출 단위."""
    id: str                    # f"{section:03d}-{seq:04d}"
    section_index: int
    ssml_or_text: str
    display_text: str
    voice: str
    rate: float
    trailing_pause_ms: int = 0
    cache_key: str = ""

@dataclass
class AudioClip:
    chunk_id: str
    path: str
    duration_ms: int
```

---

## 5. 모듈 상세 설계

### 5.1 디렉터리 구조

```
lecture-tts/
├── pyproject.toml
├── README.md
├── .env.example
├── config/
│   ├── default.yaml
│   └── lexicon.yaml              # 발음 사전
├── src/lecture_tts/
│   ├── __init__.py
│   ├── cli.py                    # 진입점 (Typer)
│   ├── config.py                 # 설정 로드/검증 (pydantic)
│   ├── models.py                 # 데이터 모델
│   ├── loaders/
│   │   ├── base.py
│   │   ├── text_loader.py        # .txt / .md
│   │   ├── docx_loader.py
│   │   └── srt_loader.py
│   ├── parser.py                 # 섹션·지시어 파싱
│   ├── normalizer/
│   │   ├── __init__.py
│   │   ├── numbers.py
│   │   ├── abbreviations.py
│   │   ├── symbols.py
│   │   └── lexicon.py
│   ├── chunker.py
│   ├── ssml.py                   # SSML 빌더
│   ├── engines/
│   │   ├── base.py               # TTSEngine 추상 클래스
│   │   ├── registry.py           # 엔진 이름 → 클래스 매핑
│   │   ├── fake_engine.py        # 테스트용 (무음/사인파 반환)
│   │   ├── kokoro_engine.py      # 기본 엔진 (로컬)
│   │   ├── piper_engine.py       # 경량 엔진 (로컬)
│   │   └── azure_engine.py       # Azure Speech F0 (클라우드, 선택)
│   ├── cache.py
│   ├── synthesizer.py            # 병렬 합성 오케스트레이션
│   ├── assembler.py              # pydub/ffmpeg 오디오 결합
│   ├── subtitles.py              # SRT/VTT 생성
│   ├── progress.py               # ProgressReporter, CancelToken (CLI·GUI 공통)
│   ├── pipeline.py               # 전체 흐름 조립
│   └── gui/                      # GUI 앱 (PySide6) — core만 호출
│       ├── app.py                # GUI 진입점 (lecture-tts-gui)
│       ├── main_window.py        # 메인 창 레이아웃
│       ├── controller.py         # AppController, ProjectState
│       ├── workers.py            # EngineHost, PipelineWorker (QThread)
│       ├── widgets/
│       │   ├── script_editor.py  # 편집기 + 구문 강조 + 실시간 검증
│       │   ├── section_list.py
│       │   ├── settings_panel.py
│       │   └── player_bar.py     # QMediaPlayer 기반 플레이어
│       ├── dialogs/
│       │   ├── setup_wizard.py   # 초기 설정 마법사
│       │   ├── audition.py       # 음성 비교
│       │   ├── lexicon_editor.py # 발음 사전 편집기
│       │   └── preferences.py
│       ├── project.py            # .lttproj 저장/불러오기
│       └── resources/            # 아이콘, 스타일
├── packaging/
│   ├── lecture_tts_gui.spec      # PyInstaller 설정
│   ├── installer.iss             # Inno Setup 스크립트
│   └── bin/ffmpeg.exe            # 배포 시 동봉 (저장소에는 다운로드 스크립트만)
└── tests/
    ├── fixtures/
    ├── test_parser.py
    ├── test_normalizer.py
    ├── test_chunker.py
    ├── test_assembler.py
    ├── test_pipeline_e2e.py
    └── gui/                      # pytest-qt 테스트
```

### 5.2 Loader
- 책임: 파일 확장자에 따라 적절한 로더를 선택해 순수 텍스트(+ 구조 힌트)를 반환.
- 인코딩: UTF-8 우선, 실패 시 `charset-normalizer`로 감지.
- `.docx`: `python-docx`로 문단 추출, Heading 스타일 → 섹션 마커로 변환.
- `.srt`: 각 큐(cue)를 문단으로 취급, 원래 타임코드는 메타데이터로 보존(선택적으로 타이밍 맞춤에 활용).

```python
class Loader(ABC):
    extensions: tuple[str, ...]
    @abstractmethod
    def load(self, path: Path) -> str: ...
```

### 5.3 Parser
- 줄 단위 상태 기계(state machine)로 처리.
  1. 주석 제거 → 2. 섹션 헤더 감지 → 3. 빈 줄로 문단 분리 → 4. 인라인 지시어 토큰화.
- 섹션 마커가 없으면 문서 전체를 섹션 1개로 취급.
- 지시어 파싱 오류(예: `[pause abc]`)는 경고 로그 후 무시하고 원문 유지 여부를 설정으로 선택.

### 5.4 Normalizer
TTS 엔진이 잘못 읽기 쉬운 요소를 읽기 좋은 영어 문장으로 변환한다. **display_text는 그대로 두고 spoken_text만 바꾼다** (자막은 원문 유지).

| 유형 | 입력 예 | 변환 결과 |
|---|---|---|
| 정수/소수 | `3.14` | three point one four |
| 서수 | `3rd` | third |
| 연도 | `2026` | twenty twenty-six |
| 퍼센트 | `25%` | twenty-five percent |
| 통화 | `$1.5M` | one point five million dollars |
| 범위 | `5–10` | five to ten |
| 약어(사전) | `e.g.`, `i.e.`, `etc.` | for example, that is, et cetera |
| 두문자어 | `API`, `GPU` | A P I, G P U (사전에 없으면 대문자 철자 읽기 규칙 적용) |
| 수식 기호 | `x^2`, `≤`, `≈` | x squared, less than or equal to, approximately |
| 코드/식별자 | `snake_case`, `getValue()` | snake case, get value |
| URL/이메일 | `example.com` | example dot com |

- 구현: 규칙 순서가 중요하므로 `normalizer/__init__.py`에서 파이프라인 순서를 명시.
  `lexicon(사용자 사전) → symbols → numbers → abbreviations → cleanup`
- 숫자 → 단어 변환은 `num2words` 라이브러리 사용.
- 사용자 발음 사전 `lexicon.yaml` 예:

```yaml
# 표기: 읽기
PyTorch: pie torch
SQL: sequel
LaTeX: lah tech
GPT: G P T
```

### 5.5 Chunker
- 엔진별 최대 입력 길이(`max_chars`)를 넘지 않도록 문장 단위로 묶는다.
- 문장 분리: `pysbd` 또는 정규식(약어 예외 처리 포함).
- 규칙
  1. 섹션 경계에서는 항상 청크를 끊는다.
  2. 화자/속도 변경 지시어에서 청크를 끊는다.
  3. 문단 경계는 가능하면 끊고, 문단 간 기본 쉼(`paragraph_pause_ms`)을 `trailing_pause_ms`로 기록.
  4. 한 문장이 `max_chars`를 넘으면 쉼표/세미콜론 기준으로 재분할.
- 청크가 너무 짧으면(예: 30자 미만) 다음 문장과 합쳐 억양 부자연스러움을 줄인다.
- 자막 정확도를 위해 청크 길이를 작게 할지(정확도↑, 호출 수↑) 크게 할지는 `chunk_strategy: sentence | paragraph`로 선택.

### 5.6 SSML Builder
- SSML 지원 엔진: `<speak>`, `<break time="500ms"/>`, `<emphasis>`, `<prosody rate="90%">`, `<sub alias="sequel">SQL</sub>` 생성.
- SSML 미지원 엔진: 지시어를 제거한 평문을 보내고, pause는 Assembler 단계에서 무음 삽입으로 처리.
- 특수문자 XML 이스케이프(`&`, `<`, `>`) 필수.

### 5.7 TTS Engine 어댑터

```python
# engines/base.py
class TTSEngine(ABC):
    name: str
    max_chars: int
    supports_ssml: bool
    supports_word_timestamps: bool = False

    @abstractmethod
    async def synthesize(self, chunk: Chunk, out_path: Path) -> AudioClip:
        """chunk를 합성해 out_path에 저장하고 AudioClip 반환."""

    def list_voices(self) -> list[str]:
        return []

    def estimate_cost(self, chars: int) -> float | None:
        return None
```

- 엔진 등록은 레지스트리 패턴: `ENGINES = {"kokoro": KokoroEngine, "piper": PiperEngine, "azure": AzureEngine, "fake": FakeEngine}`
- 로컬 엔진은 CPU/GPU 연산이므로 `synthesize()` 내부에서 `asyncio.to_thread()`로 실행하고, **모델은 엔진 초기화 시 1회만 로드**한다.

#### 5.7.1 엔진 구성 (무료)

| 역할 | 엔진 | 실행 위치 | 라이선스/비용 | SSML | 단어 타이밍 | 용도 |
|---|---|---|---|---|---|---|
| **기본** | Kokoro (82M) | 로컬 (CPU 가능, GPU/Apple Silicon 가속) | Apache 2.0, 무료 | ✗ | ✗ (청크 단위) | 실제 강의 내레이션 |
| 경량 | Piper | 로컬 (CPU, 매우 빠름) | MIT, 무료 | ✗ | ✗ | 초안 미리듣기, 저사양 PC |
| 클라우드(선택) | Azure Speech F0 | 클라우드 | 월 50만 자 무료, 초과 시 자동 과금 없이 중단 | ✓ | ✓ (WordBoundary) | 정밀 발음 제어·단어 단위 자막 |
| 테스트 | FakeEngine | 로컬 | — | — | — | 단위/통합 테스트 |

> 분량 감각: 말하기 속도 150wpm 기준 1시간 강의 ≈ 9,000 단어 ≈ 약 5만 자. Azure F0는 월 약 10시간 분량.
> 참고(선택 확장): 강사 본인 목소리 복제가 필요하면 Chatterbox(MIT, GPU 권장)를 어댑터로 추가할 수 있다. 본인 동의가 있는 음성만 사용한다.
> 비권장: `edge-tts` 등 비공식 무료 라이브러리는 공식 API가 아니어서 차단·약관 위험이 있으므로 기본 엔진으로 쓰지 않는다.

#### 5.7.2 Kokoro 어댑터 (기본)
- 설치: `pip install kokoro soundfile` + 시스템에 `espeak-ng` 설치 권장(사전에 없는 단어의 발음 변환 폴백용).
- 첫 실행 시 모델 가중치를 Hugging Face에서 내려받으므로, `lecture-tts setup kokoro` 명령으로 미리 다운로드하도록 한다. 이후에는 오프라인 동작.
- 언어 코드: 미국 영어 `a`, 영국 영어 `b`. 음성 예: `af_heart`(미국 여성), `am_michael`(미국 남성), `bf_emma`(영국 여성) 등 — 설치 버전의 음성 목록을 `lecture-tts voices --engine kokoro`로 확인.
- 출력: 24kHz mono float 배열 → `soundfile`로 WAV 저장.
- 속도: `speed` 파라미터로 조절 (설정의 `rate`와 매핑).
- SSML 미지원 → 지시어 처리 방식:
  - `[pause]`, 문단 쉼 → Assembler에서 무음 삽입
  - `*강조*` → 기호만 제거하고 평문으로 읽음 (강조 표현 불가, 문서화)
  - `{표기|읽기}` 및 발음 사전 → Normalizer에서 **철자 치환**(respelling)으로 처리
- 청크 길이: 내부적으로 긴 문장을 나누지만 억양 안정성을 위해 `max_chars: 400` 정도로 제한.
- 동시성: 한 프로세스에서 모델 1개를 순차 실행(`concurrency: 1`)이 기본. CPU 코어가 많으면 프로세스 풀로 확장(Phase 3).

```python
# engines/kokoro_engine.py
import asyncio, numpy as np, soundfile as sf
from kokoro import KPipeline

class KokoroEngine(TTSEngine):
    name = "kokoro"
    max_chars = 400
    supports_ssml = False
    SAMPLE_RATE = 24000

    def __init__(self, cfg):
        self.voice = cfg.voice or "af_heart"
        self.pipeline = KPipeline(lang_code=cfg.lang_code or "a")  # 모델 1회 로드

    def _run(self, text: str, speed: float) -> np.ndarray:
        parts = [audio for _, _, audio in self.pipeline(text, voice=self.voice, speed=speed)]
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)

    async def synthesize(self, chunk: Chunk, out_path: Path) -> AudioClip:
        audio = await asyncio.to_thread(self._run, chunk.ssml_or_text, chunk.rate)
        sf.write(out_path, audio, self.SAMPLE_RATE)
        return AudioClip(chunk.id, str(out_path), int(len(audio) / self.SAMPLE_RATE * 1000))
```
> 위 코드는 구조 예시이며, `KPipeline`의 반환 형태 등 세부 API는 설치한 kokoro 버전 문서로 확인한다.

#### 5.7.3 Piper 어댑터 (경량)
- 설치: `pip install piper-tts`, 음성 모델(.onnx + .json)을 내려받아 `models/piper/`에 저장 (예: `en_US-lessac-high`).
- 출력 샘플레이트는 음성 모델 설정(json)에서 읽는다 → Assembler에서 공통 샘플레이트로 리샘플링.
- 용도: `--engine piper`로 빠른 초안 생성 후 검수, 최종본은 Kokoro로 생성.

#### 5.7.4 Azure Speech F0 어댑터 (선택)
- 설치: `pip install azure-cognitiveservices-speech`, 환경변수 `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`.
- Azure 포털에서 Speech 리소스 생성 시 가격 계층 **Free F0** 선택.
- SSML 전체 기능 사용: `<break>`, `<emphasis>`, `<prosody>`, `<sub>`, `<phoneme>`.
- `synthesis_word_boundary` 이벤트로 단어별 타이밍 수집 → 단어 단위 자막.
- 무료 티어 제약 대응:
  - SSML 태그 문자도 사용량에 포함되므로, 실행 전 `preview --estimate-cost`로 **SSML 포함 글자 수**를 계산해 월 한도 대비 표시.
  - 호출 빈도 제한이 있으므로 `concurrency: 1`, 429 응답 시 백오프.
  - 사용량 누적을 `.cache/usage.json`(월별)에 기록하고, 한도 근접 시 경고. 한도 초과 시 `fallback_engine`(Kokoro)으로 전환 옵션.

### 5.8 Cache
- 캐시 키 = `sha256(engine + voice + rate + pitch + format + spoken_ssml + engine_version)`
- 저장 위치: `.cache/tts/{key[:2]}/{key}.wav` + 메타데이터 `{key}.json`(duration 등).
- 스크립트 한 문장만 수정하면 해당 청크만 재합성된다.
- `--no-cache`, `cache clear` 명령 제공.

### 5.9 Synthesizer (오케스트레이션)
- `asyncio` + `Semaphore(concurrency)`로 동시 호출 수 제한.
- 재시도: `tenacity`로 지수 백오프 (예: 최대 5회, 1s → 2s → 4s ... , 429/5xx만 재시도).
- 진행률: `rich.progress` 표시.
- 실패 청크 목록을 `failed_chunks.json`에 기록하고 `--resume`으로 이어서 실행.

### 5.10 Audio Assembler
- `pydub`(내부적으로 ffmpeg) 사용.
- 처리 순서
  1. 청크 오디오 로드 → 샘플레이트/채널 통일 (예: 24kHz 또는 44.1kHz, mono)
  2. `trailing_pause_ms`, `[pause]`만큼 무음 삽입
  3. 섹션 앞뒤 여백(`section_padding_ms`) 추가
  4. 음량 정규화 (목표 약 -16 LUFS, `ffmpeg loudnorm` 필터 또는 pyloudnorm)
  5. 섹션별 파일 export + 전체 병합 파일 export
- 각 청크의 시작/끝 시간을 누적 계산하여 타임라인 생성 → Subtitles 모듈로 전달.

### 5.11 Subtitles / Manifest
- 기본: 청크(문장) 단위 큐 생성, 텍스트는 `display_text` 사용.
- 엔진이 단어 타임스탬프를 제공하면 단어 단위로 더 정밀하게 분할.
- 자막 한 줄 최대 길이(예: 42자), 최대 2줄 규칙 적용.
- `manifest.json` 예:

```json
{
  "title": "Lecture 3: Introduction to Neural Networks",
  "engine": "kokoro", "voice": "af_heart",
  "total_duration_ms": 734200,
  "sections": [
    {
      "index": 1, "title": "Welcome",
      "file": "sections/01_welcome.mp3",
      "start_ms": 0, "end_ms": 41250,
      "chunks": [
        {"id": "001-0001", "start_ms": 0, "end_ms": 5320,
         "text": "Hello everyone, and welcome to lecture three."}
      ]
    }
  ]
}
```

---

## 6. 설정 파일

```yaml
# config/default.yaml
engine:
  name: kokoro              # kokoro | piper | azure | fake
  fallback_engine: kokoro   # azure 한도 초과·오류 시 전환 (null이면 중단)
  rate: 1.0

engines:                    # 엔진별 세부 설정
  kokoro:
    lang_code: a            # a=미국 영어, b=영국 영어
    voice: af_heart
    max_chars: 400
  piper:
    model_path: models/piper/en_US-lessac-high.onnx
  azure:
    voice: en-US-JennyNeural
    region_env: AZURE_SPEECH_REGION
    key_env: AZURE_SPEECH_KEY
    monthly_char_limit: 500000
    warn_at_ratio: 0.8

speakers:                   # 다중 화자 매핑 (엔진별 음성 이름 사용)
  default: { voice: af_heart }
  student: { voice: am_michael, rate: 1.05 }

parsing:
  section_patterns:
    - '^##\s*Slide\s*(\d+)\s*:?\s*(.*)$'
    - '^\[SLIDE\s*(\d+)\]\s*(.*)$'
  read_title: false
  on_invalid_directive: warn   # warn | error | keep_text

normalization:
  lexicon: config/lexicon.yaml
  spell_out_acronyms: true
  read_urls: true

chunking:
  strategy: sentence           # sentence | paragraph
  min_chars: 30
  max_chars: null              # null이면 엔진 기본값 사용

audio:
  format: mp3                  # 기본값 mp3 (확정). 영상 편집용은 --format wav
  bitrate: 128k                # 음성 내레이션은 128k로 충분, 고품질 배포는 192k
  sample_rate: 24000
  paragraph_pause_ms: 600
  section_padding_ms: 1000
  loudness_lufs: -16
  export_sections: true
  export_merged: true

subtitles:
  formats: [srt, vtt]
  max_line_chars: 42

runtime:
  concurrency: 1               # 로컬 엔진은 1 권장 (모델 1개 순차 실행)
  max_retries: 5
  cache_dir: .cache/tts
  output_dir: output
```

설정 우선순위: **CLI 옵션 > 사용자 설정 파일(`--config`) > `default.yaml`**

---

## 7. CLI 설계

```bash
# 기본 실행
lecture-tts build lecture03.md

# 로컬 모델 사전 다운로드 (최초 1회)
lecture-tts setup kokoro
lecture-tts setup piper --voice en_US-lessac-high

# 엔진·음성·출력 지정
lecture-tts build lecture03.md --voice am_michael -o out/lec03
lecture-tts build lecture03.md --engine piper            # 빠른 초안
lecture-tts build lecture03.md --engine azure --voice en-US-JennyNeural

# Azure 무료 티어 이번 달 사용량 확인
lecture-tts usage --engine azure

# 합성 없이 정규화 결과 / 청크 / 예상 비용 확인
lecture-tts preview lecture03.md --show normalized
lecture-tts preview lecture03.md --show chunks --estimate-cost   # Azure 사용 시 글자 수·한도 대비

# 특정 섹션만 재생성
lecture-tts build lecture03.md --sections 2,5-7

# 실패한 청크 이어서 처리
lecture-tts build lecture03.md --resume

# 폴더 일괄 처리
lecture-tts batch ./scripts --glob "*.md"

# 출력 포맷 (기본 mp3)
lecture-tts build lecture03.md --format wav   # 영상 편집용 고음질

# 후보 음성 비교 샘플 생성
lecture-tts audition --voices af_heart,am_michael,bf_emma --rates 0.9,1.0

# 보조 명령
lecture-tts voices --engine kokoro
lecture-tts cache clear
```

### 출력 구조
```
output/lecture03/
├── lecture03_full.mp3
├── lecture03_full.srt
├── lecture03_full.vtt
├── sections/
│   ├── 01_welcome.mp3
│   ├── 01_welcome.srt
│   └── 02_what-is-a-perceptron.mp3
├── manifest.json
├── normalized_script.txt     # 실제로 읽힌 텍스트 (검수용)
└── build.log
```

---

## 8. GUI 애플리케이션 설계

### 8.1 목표와 원칙
- 터미널을 쓰지 않는 강의 제작자도 **스크립트 열기 → 미리듣기 → 생성 → 수정 → 부분 재생성**을 한 화면에서 할 수 있게 한다.
- **GUI는 얇은 계층**이다. 파싱·정규화·합성·병합은 모두 기존 `core` 파이프라인을 그대로 호출하고, CLI와 GUI가 같은 코드를 공유한다. GUI 전용 로직은 화면 상태 관리와 사용자 입력 처리로 한정한다.
- 무거운 작업(모델 로딩, 합성, 병합)은 **절대 UI 스레드에서 실행하지 않는다.** 모든 장시간 작업은 작업 스레드에서 실행하고 시그널로 진행 상황을 전달한다.
- 대상 OS: Windows 10/11 x64 우선, macOS는 동일 코드로 지원(배포는 후순위).

### 8.2 프레임워크 선정

| 후보 | 장점 | 단점 | 판단 |
|---|---|---|---|
| **PySide6 (Qt 6)** | 네이티브 데스크톱 앱, 풍부한 위젯, 오디오 재생(Qt Multimedia), 스레드·시그널 모델, 구문 강조 지원, LGPL | 학습량이 다소 있음, 배포 용량 큼 | **채택** |
| Gradio | 코드가 매우 짧음, 브라우저 기반 UI | 데스크톱 앱 느낌이 약하고 편집기·세밀한 상태 관리가 어려움 | 빠른 시제품용으로만 고려 |
| Tkinter | 표준 라이브러리, 설치 불필요 | 위젯이 빈약, 오디오 재생·편집기 구현 부담 | 제외 |
| Flet | 현대적 UI, Python만으로 작성 | 데스크톱 오디오·편집기 기능이 상대적으로 제한적 | 제외 |

> PySide6는 LGPL이므로 PyInstaller 등으로 배포할 때 Qt 라이브러리를 동적 링크 형태(기본 동작)로 유지하고 라이선스 고지를 포함한다.

### 8.3 화면 구성 (메인 창)

```
┌───────────────────────────────────────────────────────────────────────────────┐
│ [열기] [저장] │ [▶ 전체 생성] [⟳ 변경분만 생성] [■ 중지] │ [출력 폴더 열기]      │  ← 툴바
├──────────────┬─────────────────────────────────────────────┬──────────────────┤
│ 섹션 목록     │  [원문 편집] [정규화 미리보기] [청크 보기]     │ 설정 패널         │
│              │ ┌─────────────────────────────────────────┐ │                  │
│ ● 1 Welcome  │ │ ## Slide 1: Welcome                     │ │ 엔진  [Kokoro ▼] │
│ ● 2 Percept… │ │ Hello everyone, and welcome to lecture  │ │ 음성  [af_heart▼]│
│ ◐ 3 Activat… │ │ three. [pause 1s]                       │ │ 억양  ◉미국 ○영국 │
│ ○ 4 Training │ │ We use {ReLU|R-E-L-U} as the ...        │ │ 속도  [━━●━] 0.95│
│ ✕ 5 Summary  │ │                                         │ │ 포맷  ◉mp3 ○wav  │
│              │ │   (구문 강조: 섹션·지시어·주석 색 구분)     │ │ 출력  [폴더…]     │
│ ● 완료        │ └─────────────────────────────────────────┘ │                  │
│ ◐ 생성 중     │                                             │ [▶ 선택 영역 듣기]│
│ ○ 미생성/변경 │                                             │ [음성 비교…]      │
│ ✕ 오류        │                                             │ [발음 사전…]      │
├──────────────┴─────────────────────────────────────────────┴──────────────────┤
│ ▶ ❚❚ ■  [섹션 3 ▼]  00:41 ━━━━━━━●━━━━━━━━━━━━━━━━━ 02:15   🔊━━●            │  ← 플레이어
│ 진행: 섹션 3/5 · 청크 12/30  [██████████░░░░░░░░] 40%   남은 시간 약 1분 20초    │  ← 진행률
│ ▸ 로그 (접기/펼치기)                                                            │
└───────────────────────────────────────────────────────────────────────────────┘
```

| 영역 | 기능 |
|---|---|
| 툴바 | 스크립트 열기/저장, 전체 생성, 변경분만 생성(캐시 활용), 중지, 출력 폴더 열기 |
| 섹션 목록 | 파싱된 섹션 표시, 상태 아이콘(완료/생성 중/미생성·변경됨/오류), 클릭 시 편집기 해당 위치로 이동, 우클릭 메뉴(이 섹션만 생성, 이 섹션 재생) |
| 편집기 | 스크립트 편집, 구문 강조, 잘못된 지시어 밑줄 표시, 자동 저장 |
| 정규화 미리보기 | 실제로 읽힐 텍스트(spoken_text)를 읽기 전용으로 표시 → 숫자·약어 변환 검수 |
| 청크 보기 | 청크 단위 분할 결과와 캐시 적중 여부 표 |
| 설정 패널 | 엔진·음성·억양·속도·출력 포맷(기본 mp3)·출력 폴더. 변경 즉시 프로젝트 설정에 반영 |
| 선택 영역 듣기 | 편집기에서 선택한 문장만 즉시 합성해 재생(파일로 저장하지 않음). 발음 확인용 |
| 플레이어 | 섹션별/전체 오디오 재생, 시크바, 볼륨. **재생 위치에 해당하는 문장을 편집기에서 하이라이트** |
| 진행률·로그 | 섹션/청크 진행률, 남은 시간 추정, 접을 수 있는 로그 패널 |

### 8.4 보조 창

| 창 | 기능 |
|---|---|
| **초기 설정 마법사** | 첫 실행 시 환경 점검: ffmpeg, espeak-ng, Kokoro 모델 존재 여부를 ✓/✕로 표시하고, 모델 다운로드(진행률 표시)와 누락 프로그램 설치 안내 링크 제공 |
| **음성 비교(Audition)** | 후보 음성 × 속도를 체크박스로 선택 → 샘플 문장 합성 → 표에서 바로 재생·비교 → "기본 음성으로 지정" 버튼 (부록 A 절차의 GUI 버전) |
| **발음 사전 편집기** | `lexicon.yaml`을 표(표기 / 읽기)로 편집, 행 추가·삭제, 각 행 "듣기" 버튼으로 즉시 확인 |
| **환경설정** | 기본 출력 폴더, 기본 엔진·음성, 문단/섹션 쉼 길이, 음량 목표, 자막 형식, 캐시 위치·용량·비우기, Azure 키 입력(선택) |

### 8.5 주요 사용자 흐름

1. **첫 실행**: 초기 설정 마법사 → 모델 다운로드 → 메인 창
2. **새 강의 생성**: 스크립트 열기 → 섹션 목록 자동 표시 → 정규화 미리보기로 검수 → 전체 생성 → 플레이어로 확인
3. **수정 후 재생성**: 편집기에서 문장 수정 → 해당 섹션이 "변경됨(○)"으로 표시 → "변경분만 생성" → 바뀐 청크만 합성(캐시) → 해당 섹션과 전체 파일만 다시 병합
4. **발음 교정**: 잘못 읽힌 단어 선택 → 우클릭 "발음 사전에 추가" → 읽기 입력 → 듣기로 확인 → 저장

### 8.6 GUI 아키텍처

```
┌────────────── UI 스레드 ──────────────┐        ┌──────── 작업 스레드 (QThread) ────────┐
│ MainWindow / Widgets (View)           │        │ EngineHost                            │
│        ▲ 시그널          │ 사용자 동작  │        │  - 엔진(모델) 1회 로드 후 상주           │
│        │                ▼             │ 요청    │  - asyncio 루프 실행                   │
│ AppController (상태·명령 관리)          │ ─────▶ │  - core.pipeline 호출                  │
│  - ProjectState (스크립트, 설정, 상태)   │ ◀───── │  - ProgressReporter → Qt 시그널 변환    │
└───────────────────────────────────────┘ 시그널  │  - CancelToken으로 중지 처리            │
                                                 └───────────────────────────────────────┘
```

- **core 파이프라인 변경 사항** (CLI·GUI 공통):
  - `ProgressReporter` 프로토콜을 받아 단계별 이벤트(섹션 시작, 청크 완료, 섹션 완료, 오류)를 보고한다. CLI는 Rich 진행률로, GUI는 Qt 시그널로 구현한다.
  - `CancelToken`을 받아 청크 사이마다 확인하고, 중지 시 완료된 청크는 캐시에 남긴 채 깔끔하게 종료한다.
  - `run_pipeline(..., sections=[3])`처럼 **특정 섹션만** 생성하는 인터페이스를 제공한다.
  - "변경 여부 판단"은 섹션별 청크 캐시 키 목록을 비교해 계산하는 순수 함수(`diff_sections`)로 분리한다.
- **EngineHost**: 엔진 로딩에 수 초가 걸리므로, 작업 스레드 하나에 엔진을 상주시키고 생성 요청을 큐로 받아 처리한다. 엔진·음성 언어가 바뀔 때만 다시 로드한다.
- **선택 영역 듣기**: 같은 EngineHost에 우선순위 높은 짧은 요청으로 보내고, 결과는 임시 파일로 받아 바로 재생한다.

```python
# core/progress.py
class ProgressReporter(Protocol):
    def section_started(self, index: int, total_chunks: int) -> None: ...
    def chunk_done(self, section: int, chunk_id: str, cached: bool) -> None: ...
    def section_done(self, index: int, audio_path: str) -> None: ...
    def error(self, where: str, message: str) -> None: ...

class CancelToken:
    def __init__(self): self._cancelled = threading.Event()
    def cancel(self): self._cancelled.set()
    @property
    def cancelled(self) -> bool: return self._cancelled.is_set()
```

```python
# gui/workers.py
class PipelineWorker(QObject):
    sectionStarted = Signal(int, int)
    chunkDone = Signal(int, str, bool)
    sectionDone = Signal(int, str)
    failed = Signal(str, str)
    finished = Signal(object)          # BuildResult

    def __init__(self, cfg: AppConfig):
        super().__init__()
        self.cfg = cfg
        self.cancel_token = CancelToken()

    @Slot(str, list)
    def build(self, script_path: str, sections: list[int]) -> None:
        reporter = QtProgressReporter(self)   # ProgressReporter 구현 → 위 시그널 emit
        try:
            result = asyncio.run(run_pipeline(Path(script_path), self.cfg,
                                              sections=sections or None,
                                              reporter=reporter,
                                              cancel=self.cancel_token))
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit("build", str(e))

# 사용: worker.moveToThread(thread); 버튼 클릭 → QMetaObject.invokeMethod 또는 시그널로 build 호출
```

### 8.7 프로젝트 파일과 상태 저장
- 강의 하나를 **프로젝트 파일** `*.lttproj`(JSON)로 저장: 스크립트 경로, 설정 덮어쓰기 값, 마지막 출력 폴더, 섹션별 마지막 생성 캐시 키.
- 스크립트가 프로젝트 파일 없이 열리면 기본 설정으로 임시 프로젝트를 만든다.
- 최근 파일 목록, 창 크기·분할 위치, 마지막 선택 음성은 `QSettings`에 저장.
- 편집기 자동 저장(예: 입력 멈춘 뒤 2초) + 생성 직전 강제 저장.

### 8.8 세부 구현 포인트
- **구문 강조**: `QSyntaxHighlighter`로 섹션 헤더, `[pause …]`, `{표기|읽기}`, `*강조*`, `[speaker: …]`, 주석을 각각 다른 색으로 표시. Parser의 지시어 정규식을 그대로 재사용해 규칙을 한 곳에서 관리한다.
- **실시간 검증**: 입력이 멈추면 Parser를 백그라운드에서 돌려 잘못된 지시어에 물결 밑줄 + 툴팁 경고.
- **오디오 재생**: `QMediaPlayer` + `QAudioOutput`. 재생 위치(ms)를 `manifest.json` 타임라인과 비교해 현재 문장을 편집기에서 하이라이트하고, 문장을 더블클릭하면 해당 위치부터 재생.
- **남은 시간 추정**: 최근 청크들의 (합성 시간 / 글자 수) 이동 평균 × 남은 글자 수.
- **다크 모드**: Qt 스타일의 시스템 테마를 따른다.
- **오류 표시**: 사용자용 짧은 메시지 대화상자 + "자세히" 버튼으로 로그 원문 표시. 의존성 누락(ffmpeg, espeak-ng, 모델)은 초기 설정 마법사로 바로 연결.

### 8.9 패키징·배포 (Windows)
- **PyInstaller `--onedir`** 방식으로 빌드한다. torch가 포함되어 용량이 커서 `--onefile`은 실행 때마다 압축 해제로 시작이 매우 느리기 때문이다.
- `ffmpeg.exe`는 앱 폴더의 `bin/`에 동봉하고, 시작 시 PATH 앞에 추가한다(사용자가 따로 설치할 필요 없음, ffmpeg 라이선스 고지 포함).
- espeak-ng는 초기 설정 마법사에서 설치 여부를 확인하고, 없으면 설치 파일 링크를 안내한다.
- Kokoro 모델은 설치 파일에 넣지 않고, 첫 실행 때 `%LOCALAPPDATA%\LectureTTS\models`로 내려받는다(Hugging Face 캐시 경로를 이 위치로 지정).
- 설치 파일은 Inno Setup으로 만들어 시작 메뉴·바탕화면 바로가기를 생성한다.
- 배포 용량은 CPU용 torch 기준으로도 수백 MB 이상이 예상되므로, 실제 빌드 후 측정해 문서에 기록한다.
- 배포판은 **CPU용 torch로 빌드**한다(어느 PC에서나 동작, 용량 절감). GPU 가속판은 필요 시 별도 빌드로 제공한다.

### 8.10 외부 배포 요구사항

다른 사람들에게 배포하므로, 개발자 PC가 아닌 **일반 사용자 PC**에서 문제없이 설치·실행되는 것을 기준으로 한다.

#### 8.10.1 설치·첫 실행
- 사용자는 **설치 파일 하나만 실행**하면 된다. Python, ffmpeg, 가상환경 설치를 요구하지 않는다.
- 설치 경로는 사용자별 설치(`%LOCALAPPDATA%\Programs\LectureTTS`)를 기본으로 해 관리자 권한 없이 설치되게 한다.
- 첫 실행 시 초기 설정 마법사가 모델을 내려받는다. 다운로드 실패에 대비해 **이어받기·재시도**와 진행률을 제공한다.
- 학교·기관처럼 인터넷이 막힌 환경을 위해 **오프라인 패키지**(모델 포함 설치 파일) 또는 "모델 폴더 가져오기" 메뉴를 제공한다.
- 한글 사용자 이름·한글/공백이 포함된 경로에서 동작해야 한다(모든 경로는 `pathlib`로 처리, 외부 프로그램 호출 시 인용 처리).

#### 8.10.2 최소 사양 (빌드 후 실측해 확정)
| 항목 | 목표 |
|---|---|
| OS | Windows 10/11 64비트 |
| 메모리 | 8GB 이상 권장 |
| 디스크 | 앱 + 모델 + 캐시 여유 공간 (실측 후 기재) |
| GPU | 불필요 (있으면 GPU 가속판 선택 가능) |
| 인터넷 | 첫 실행 모델 다운로드 시에만 필요 (오프라인 패키지 사용 시 불필요) |

#### 8.10.3 Windows 보안 경고 대응
- 서명되지 않은 설치 파일은 Windows SmartScreen이 "알 수 없는 게시자" 경고를 띄운다.
- 선택지: ① **코드 서명 인증서** 구매 후 설치 파일·exe 서명(경고 감소, 유료) ② 서명 없이 배포하고 사용자 안내 문서에 "추가 정보 → 실행" 방법 명시.
- 배포 규모가 커지면 ①로 전환한다. 어느 쪽이든 설치 파일의 SHA-256 해시를 배포 페이지에 함께 공개한다.

#### 8.10.4 라이선스 점검 (배포 전 필수)
배포판에는 여러 오픈소스 구성 요소가 포함되므로, 앱의 "정보" 화면과 설치 폴더의 `THIRD_PARTY_LICENSES.txt`에 고지를 모은다.

| 구성 요소 | 라이선스 | 배포 시 확인 사항 |
|---|---|---|
| Kokoro 모델·코드 | Apache 2.0 | 고지 포함 |
| PySide6 / Qt | LGPL v3 | 동적 링크 유지(onedir 기본 동작), 고지·라이선스 원문 포함, 사용자가 Qt 라이브러리를 교체할 수 있는 구조 유지 |
| ffmpeg | 빌드에 따라 LGPL 또는 GPL | **LGPL 빌드**를 동봉하는 것을 원칙으로 하고, 사용한 빌드의 출처·라이선스 기재 |
| espeak-ng | GPL v3 | 앱에 직접 동봉할지(발음 처리 의존 패키지가 라이브러리를 포함하는지 포함) **배포 전 확인 필요**. 동봉 시 GPL 조건이 앱 배포 방식에 미치는 영향을 검토하고, 별도 설치 안내 방식과 비교해 결정 |
| PyTorch 등 Python 패키지 | 각 패키지 라이선스 | `pip-licenses`로 목록 자동 생성 |

> 라이선스 해석이 애매한 항목(특히 GPL 구성 요소 동봉 여부)은 배포 전에 소속 기관의 담당 부서나 전문가에게 확인한다.

#### 8.10.5 버전 관리·업데이트
- 버전 표기는 `MAJOR.MINOR.PATCH`(예: 1.2.0). 앱 "정보" 화면과 설치 파일 이름에 표시.
- 시작 시(설정에서 끌 수 있음) 배포 페이지(예: GitHub Releases)의 최신 버전을 확인해 **새 버전 알림**만 표시한다. 자동 설치는 하지 않는다.
- 업데이트 설치 시 사용자 설정·발음 사전·캐시·모델은 유지한다(앱 폴더와 사용자 데이터 폴더 분리: 데이터는 `%LOCALAPPDATA%\LectureTTS\`).
- 설정 파일·프로젝트 파일에 `schema_version`을 넣어, 구버전 파일을 열 때 자동 변환한다.

#### 8.10.6 지원·문제 해결
- **오류 보고용 로그 내보내기**: 메뉴 "도움말 → 진단 정보 내보내기"로 로그·환경 정보(OS, 앱 버전, 의존성 점검 결과)를 zip으로 저장. 스크립트 원문과 API 키는 포함하지 않는다.
- 처리되지 않은 예외는 충돌 대화상자로 보여 주고 로그를 자동 저장한다.
- 사용 데이터 수집(텔레메트리)은 하지 않는다.
- Azure 등 클라우드 엔진 키는 **각 사용자가 자신의 키를 입력**하며, 배포판에 키를 포함하지 않는다. 입력한 키는 Windows 자격 증명 관리자(`keyring`)에 저장한다.

#### 8.10.7 사용자 문서
- 설치 가이드(보안 경고 대처 포함), 빠른 시작(스크립트 작성 규칙 → 생성 → 수정), 스크립트 문법 요약표(3.2절), 자주 묻는 질문.
- 앱 안의 "도움말 → 스크립트 문법" 메뉴에서 같은 내용을 바로 볼 수 있게 한다.
- 예제 스크립트(`samples/lecture_sample.md`)를 설치 시 함께 제공한다.

#### 8.10.8 배포 전 점검 (릴리스 체크리스트)
- [ ] 개발 도구가 없는 **깨끗한 Windows 10·11 PC(또는 VM)**에서 설치 → 첫 실행 → 모델 다운로드 → 생성 → 재생 확인
- [ ] 관리자 권한 없는 계정, 한글 사용자 이름 계정에서 확인
- [ ] 오프라인 패키지로 인터넷 없이 설치·생성 확인
- [ ] 이전 버전 위에 업데이트 설치 시 설정·사전 유지 확인
- [ ] 제거(언인스톨) 시 앱 폴더 삭제, 사용자 데이터는 삭제 여부를 묻기
- [ ] `THIRD_PARTY_LICENSES.txt`, 버전 번호, 해시값, 릴리스 노트 확인

### 8.11 GUI 테스트
- `pytest-qt`로 위젯 단위 테스트: 스크립트 열기 → 섹션 목록 표시, 설정 변경 → 상태 반영, 중지 버튼 → 작업 종료.
- GUI 테스트는 항상 `FakeEngine`을 사용해 모델 없이 빠르게 실행한다.
- 수동 점검 항목: 생성 중 창 응답성(멈춤 없음), 중지 후 재시작, 재생-문장 하이라이트 싱크, 한글 경로·공백 포함 경로 처리.

---

## 9. 기술 스택

| 구분 | 선택 | 비고 |
|---|---|---|
| 언어 | **Python 3.12** (3.10~3.12 지원) | kokoro 0.9.4가 3.13 이상을 지원하지 않음 → 가상환경으로 3.12 고정 |
| CLI | Typer, Rich | 진행률·컬러 로그 |
| 설정 | PyYAML, pydantic | 스키마 검증 |
| 텍스트 | num2words, pysbd, charset-normalizer | |
| 문서 입력 | python-docx, srt | 선택 기능 |
| 오디오 | pydub + ffmpeg, pyloudnorm | ffmpeg 시스템 설치 필요 |
| TTS (기본) | kokoro, soundfile, espeak-ng(시스템) | 설치: `pip install lecture-tts[kokoro]` |
| TTS (경량) | piper-tts | extras `[piper]` |
| TTS (클라우드) | azure-cognitiveservices-speech | extras `[azure]` |
| 재시도 | tenacity | |
| 환경변수 | python-dotenv | `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION` |
| GUI | **PySide6** (Qt Widgets, Qt Multimedia) | extras `[gui]`, LGPL |
| 배포 | PyInstaller(`--onedir`), Inno Setup | Windows 설치 파일 |
| 테스트 | pytest, pytest-asyncio, pytest-qt | |
| 품질 | ruff, mypy | |

> 엔진 패키지는 `pyproject.toml`의 optional-dependencies(extras)로 분리해, 사용하는 엔진만 설치하게 한다.

---

## 10. 오류 처리 및 로깅

| 상황 | 처리 |
|---|---|
| 입력 파일 없음/인코딩 오류 | 즉시 종료, 명확한 메시지 |
| 지시어 문법 오류 | 설정(`on_invalid_directive`)에 따라 경고/중단 |
| API 키 누락 (Azure) | 시작 시점에 검증 후 종료 |
| 로컬 모델 미다운로드 | `lecture-tts setup <engine>` 안내 후 종료 |
| espeak-ng 미설치 | 경고만 출력 (사전 외 단어 발음 품질 저하 가능) |
| Azure 월 한도 근접/초과 | 80%에서 경고, 초과 시 `fallback_engine`으로 전환 또는 중단 |
| 엔진 간 음성 혼용 | 한 빌드 안에서 엔진이 바뀌면 경고 (음색 불일치) |
| 429 / 5xx | 지수 백오프 재시도 |
| 4xx(입력 오류) | 해당 청크 실패 기록, 나머지 계속 진행 |
| ffmpeg 미설치 | 시작 시 `ffmpeg -version` 확인, 설치 안내 |
| 일부 청크 실패 | 병합 파일 생성 보류, `--resume` 안내 |

- 로그 레벨: `--verbose`, `--quiet`
- 로그에 API 키·전체 스크립트 원문은 남기지 않음 (청크 ID와 앞 40자만).

---

## 11. 테스트 전략

- **단위 테스트**
  - Parser: 섹션 마커 변형, 지시어 조합, 주석, 빈 문서
  - Normalizer: 숫자/통화/약어/수식 케이스 테이블 기반 테스트(입력→기대 출력)
  - Chunker: `max_chars` 경계, 초장문 문장 재분할, 섹션 경계 유지
  - SSML: XML 이스케이프, 중첩 지시어
- **통합 테스트**
  - `FakeEngine`(정해진 길이의 사인파/무음 반환)으로 전체 파이프라인 실행 → 타임스탬프·자막·manifest 정합성 검증
  - 캐시 적중: 한 문장만 수정 후 재실행 시 해당 청크만 합성되는지 확인
- **수동 검수 체크리스트**
  - 전문 용어 발음, 숫자 읽기, 문단 간 쉼 자연스러움, 섹션 간 음량 편차, 자막 싱크

---

## 12. 구현 로드맵

| 단계 | 내용 | 산출물 / 완료 기준 |
|---|---|---|
| **Phase 0** 기반 | 프로젝트 골격, 설정 로드, CLI 뼈대, 로깅 | `lecture-tts --help` 동작 |
| **Phase 1** MVP | txt/md Loader, Parser(섹션+pause), 기본 Normalizer, Chunker, **FakeEngine + KokoroEngine**, `setup kokoro`, 단순 병합 | md 입력 → Kokoro로 전체 mp3 1개 생성 |
| **Phase 2** 품질 | 정규화 규칙 확장, 발음 사전(철자 치환), 음량 정규화, 섹션별 출력 | 섹션별 mp3 + 자연스러운 쉼/발음 |
| **Phase 3** 운영성 | 캐시, 프로세스 풀 병렬화, 재시도, `--resume`, `preview` | 문장 1개 수정 시 수 초 내 재생성 |
| **Phase 4** 부가 기능 | SRT/VTT(청크 단위), manifest, **PiperEngine**, docx/srt 입력, 다중 화자, batch | 영상 편집에 바로 쓰이는 출력 일체 |
| **Phase 4.5** 클라우드(선택) | **AzureEngine**(SSML·단어 타이밍), 사용량 추적, 한도 초과 시 폴백 | 단어 단위 자막, 월 한도 내 운영 |
| **Phase G1** GUI 골격 | 메인 창 레이아웃, 스크립트 열기/편집/저장, 설정 패널, PipelineWorker로 전체 생성(진행률·중지) | 버튼 하나로 mp3 생성, 생성 중 창 멈춤 없음 |
| **Phase G2** GUI 작업 흐름 | 섹션 목록·상태, 섹션 단위/변경분 생성, 플레이어 + 문장 하이라이트, 정규화 미리보기, 구문 강조 | 수정 → 변경분 생성 → 재생이 한 화면에서 완결 |
| **Phase G3** GUI 편의 기능 | 초기 설정 마법사, 음성 비교 창, 발음 사전 편집기, 선택 영역 듣기, 프로젝트 파일 | 처음 쓰는 사람도 설명 없이 사용 가능 |
| **Phase G4** 배포 (**필수**) | PyInstaller 빌드, ffmpeg(LGPL) 동봉, Inno Setup 설치 파일, 모델 다운로드(이어받기)·오프라인 패키지, 라이선스 고지, 진단 정보 내보내기, 업데이트 알림, 사용자 문서 | 8.10.8 릴리스 체크리스트 전 항목 통과 |
| **Phase 5** 확장(선택) | 한국어 스크립트 → 영어 번역 단계, 슬라이드+오디오 영상 합성 | 별도 설계 |

### 구현 순서 팁
1. `FakeEngine`을 가장 먼저 만들어 모델 로딩 없이 빠르게 파이프라인 전체를 개발·테스트한다.
2. Normalizer는 실제 강의 스크립트 샘플에서 틀리게 읽힌 사례를 모아 테스트 케이스로 축적한다.
3. Kokoro는 로컬 실행이라 비용 부담이 없으므로 Phase 1부터 실제 음성으로 자주 들어보며 Normalizer를 튜닝한다.
4. Azure는 무료 한도를 아끼기 위해 캐시(Phase 3) 구현 이후에 붙인다.
5. GUI는 Phase 1 MVP가 CLI로 동작한 뒤 시작한다. G1 시작 전에 core에 `ProgressReporter`·`CancelToken`·섹션 단위 생성 인터페이스를 먼저 넣어 두면 GUI 작업이 단순해진다.
6. 권장 진행 순서: Phase 0 → 1 → 2 → **G1** → 3 → **G2** → 4 → **G3** → **G4** (CLI 기능과 GUI를 번갈아 키워 매 단계 실제로 써 볼 수 있게 한다)

---

## 13. 핵심 코드 스켈레톤

```python
# pipeline.py
async def run_pipeline(input_path: Path, cfg: AppConfig, *,
                       sections: list[int] | None = None,      # None이면 전체
                       reporter: ProgressReporter = NullReporter(),
                       cancel: CancelToken | None = None) -> BuildResult:
    raw = load_file(input_path)
    doc = Parser(cfg.parsing).parse(raw, source_path=str(input_path))
    doc = Normalizer(cfg.normalization).apply(doc)

    engine = create_engine(cfg.engine)
    chunks = Chunker(cfg.chunking, engine).split(doc)

    cache = TTSCache(cfg.runtime.cache_dir)
    if sections:
        chunks = [c for c in chunks if c.section_index in sections]
    clips = await Synthesizer(engine, cache, cfg.runtime, reporter, cancel).run(chunks)

    timeline = AudioAssembler(cfg.audio).assemble(doc, chunks, clips, out_dir=cfg.output_dir)
    SubtitleWriter(cfg.subtitles).write(timeline, out_dir=cfg.output_dir)
    write_manifest(doc, timeline, cfg)
    return BuildResult(timeline=timeline)
```

```python
# synthesizer.py
class Synthesizer:
    def __init__(self, engine, cache, runtime_cfg, reporter, cancel=None):
        self.engine, self.cache = engine, cache
        self.reporter, self.cancel = reporter, cancel
        self.sem = asyncio.Semaphore(runtime_cfg.concurrency)

    async def _one(self, chunk: Chunk) -> AudioClip:
        if (hit := self.cache.get(chunk.cache_key)):
            self.reporter.chunk_done(chunk.section_index, chunk.id, cached=True)
            return hit
        async with self.sem:
            if self.cancel and self.cancel.cancelled:   # 중지 요청 확인
                raise BuildCancelled()
            clip = await retry_async(self.engine.synthesize, chunk,
                                     self.cache.path_for(chunk.cache_key))
        self.cache.put(chunk.cache_key, clip)            # 완료분은 캐시에 남김
        self.reporter.chunk_done(chunk.section_index, chunk.id, cached=False)
        return clip

    async def run(self, chunks: list[Chunk]) -> list[AudioClip]:
        return await asyncio.gather(*(self._one(c) for c in chunks))
```

---

## 14. 미결정 사항 (결정 필요)

- [x] 1차 TTS 엔진 선정 → Kokoro(기본) / Piper(경량) / Azure F0(선택)
- [ ] 기본 음성(성별·억양: 미국식 `a` / 영국식 `b`) 및 기본 말하기 속도 — `audition_voices.py`(부록 A)로 후보 음성 × 속도 샘플을 생성해 비교 후 결정
- [ ] 실행 환경: GPU 유무 → Kokoro 처리 속도·병렬화 전략에 영향
- [ ] 강사 목소리 복제(Chatterbox) 필요 여부
- [ ] 기존 강의 스크립트의 실제 양식 → 섹션 마커 정규식 확정
- [ ] 수식·코드가 많은 강의인지 여부 → Normalizer 투자 범위
- [ ] 한국어 원고 번역 기능 필요 여부 (Phase 5 포함 여부)
- [x] GUI 사용 대상 → **다른 사람들에게 배포** (설치 파일 필수, 8.10)
- [ ] 배포 채널: GitHub Releases / 기관 내부 공유 드라이브 / 홈페이지 → 업데이트 확인 방식에 영향
- [ ] 코드 서명 인증서 구매 여부 (8.10.3)
- [ ] espeak-ng 동봉 vs 별도 설치 안내 — 라이선스 검토 후 결정 (8.10.4)
- [ ] 앱 이름·아이콘
- [ ] GUI 언어: 한국어 UI만 vs 한/영 전환 (Qt 번역 파일 사용 여부)
- [x] GUI 프레임워크 → **PySide6** (8.2)
- [x] 출력 기본값 → **mp3** (128kbps). 영상 편집용 고음질이 필요할 때만 `--format wav`

---

## 부록 A. 기본 음성 선정 절차

1. 실제 강의 스크립트에서 **전문 용어·숫자·긴 문장이 섞인 단락 1개**(약 30초 분량)를 고른다.
2. `audition_voices.py`로 후보 음성 × 속도 조합의 mp3를 생성한다.
   - 후보(미국식 `a`): `af_heart`, `af_bella`, `am_michael`, `am_fenrir`
   - 후보(영국식 `b`): `bf_emma`, `bm_george`
   - 속도: `0.9`, `1.0` (강의는 약간 느린 0.9~0.95가 알아듣기 쉬운 경우가 많음)
3. 평가 기준: ① 장시간 들어도 피로하지 않은가 ② 전문 용어 발음 ③ 문장 끝 억양의 자연스러움 ④ 수강생(비원어민 포함)이 알아듣기 쉬운 속도
4. 선택 결과를 `config/default.yaml`의 `engines.kokoro.voice`, `lang_code`, `engine.rate`에 반영하고, 이 문서 14장의 해당 항목을 체크한다.

> 음성 이름은 Kokoro 버전에 따라 다를 수 있으므로, 스크립트가 실패하면 설치된 버전의 VOICES 목록을 확인한다.