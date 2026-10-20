"""프로젝트 파일 (*.lttproj, JSON): 스크립트 경로 + 설정 덮어쓰기 값 + 마지막 출력 폴더."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_SCHEMA = 1
PROJECT_EXT = ".lttproj"


@dataclass
class Project:
    script: str | None = None
    overrides: dict = field(default_factory=dict)   # AppConfig에 deep-merge될 값
    last_output: str | None = None
    path: str | None = None                         # 프로젝트 파일 자신의 위치 (저장 안 함)

    def to_json(self) -> str:
        base = Path(self.path).parent if self.path else None
        script = self.script
        if base and script:  # 프로젝트 폴더 기준 상대 경로로 저장 (폴더째 옮겨도 동작)
            try:
                script = Path(script).resolve().relative_to(base.resolve()).as_posix()
            except ValueError:
                pass
        return json.dumps({"schema_version": PROJECT_SCHEMA, "script": script, "overrides": self.overrides,
                           "last_output": self.last_output}, ensure_ascii=False, indent=2)

    def save(self, path: str | Path) -> None:
        self.path = str(path)
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data = migrate(data)
        script = data.get("script")
        if script and not Path(script).is_absolute():
            script = str((Path(path).parent / script).resolve())
        return cls(script=script, overrides=data.get("overrides") or {},
                   last_output=data.get("last_output"), path=str(path))


def migrate(data: dict) -> dict:
    """구버전 프로젝트 파일 자동 변환 (schema_version 기준)."""
    v = int(data.get("schema_version", 0))
    if v < 1:
        data.setdefault("overrides", data.pop("settings", {}) or {})
    data["schema_version"] = PROJECT_SCHEMA
    return data
