"""문장(청크) 단위 합성 결과 캐시. 키에 엔진·음성·속도·텍스트·엔진 버전이 포함된다."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from .models import AudioClip, Chunk


def make_cache_key(engine_name: str, engine_version: str, chunk: Chunk, sample_rate: int) -> str:
    payload = json.dumps([engine_name, engine_version, chunk.voice, round(chunk.rate, 3),
                          chunk.text, sample_rate], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class TTSCache:
    def __init__(self, root: Path, enabled: bool = True):
        self.root = Path(root)
        self.enabled = enabled

    def path_for(self, key: str) -> Path:
        p = self.root / key[:2] / f"{key}.wav"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def _meta(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def has(self, key: str) -> bool:
        return self._meta(key).exists() and (self.root / key[:2] / f"{key}.wav").exists()

    def get(self, key: str, chunk_id: str = "") -> AudioClip | None:
        if not self.enabled or not self.has(key):
            return None
        try:
            meta = json.loads(self._meta(key).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return AudioClip(chunk_id, str(self.root / key[:2] / f"{key}.wav"), int(meta["duration_ms"]))

    def put(self, key: str, clip: AudioClip) -> None:
        self._meta(key).write_text(json.dumps({"duration_ms": clip.duration_ms}), encoding="utf-8")

    def clear(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)

    def size_bytes(self) -> int:
        if not self.root.exists():
            return 0
        return sum(f.stat().st_size for f in self.root.rglob("*") if f.is_file())
