# 오픈소스 구성 요소

이 앱은 다음 오픈소스 구성 요소를 사용합니다. 전체 목록과 라이선스 원문은 설치 폴더의 `THIRD_PARTY_LICENSES.txt`에 있습니다 (배포 빌드 시 `pip-licenses`로 생성).

| 구성 요소 | 라이선스 | 비고 |
|---|---|---|
| Kokoro-82M 모델·kokoro 패키지 | Apache 2.0 | https://huggingface.co/hexgrad/Kokoro-82M |
| misaki (G2P) | Apache 2.0 | |
| PySide6 / Qt 6 | LGPL v3 | 동적 링크(onedir) — 설치 폴더의 Qt 라이브러리를 교체할 수 있습니다. https://www.qt.io/licensing |
| PyTorch | BSD-3-Clause | |
| ffmpeg | LGPL v2.1+ (LGPL 빌드 동봉 원칙) | https://ffmpeg.org/legal.html |
| espeak-ng (espeakng-loader 경유) | GPL v3 | 동봉 여부는 배포 전 라이선스 검토 대상 (설계 문서 8.10.4) |
| num2words | LGPL v2.1 | |
| NumPy, soundfile, PyYAML, pydantic, Typer, Rich | BSD / MIT | |
