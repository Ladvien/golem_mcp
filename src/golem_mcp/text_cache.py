"""Disk-cached wrapper around Kimodo's LLM2Vec text encoder (imported by the worker only).

The 8B encoder runs on CPU (the GPU is shared), so a miss costs minutes. Embeddings are a pure
function of (encoder weights, text), so each one is cached as `<sha256>.pt` and the encoder is only
constructed on the first miss.
"""

import hashlib
import os
from pathlib import Path

import torch
from kimodo.model import LLM2VecEncoder
from kimodo.model.load_model import TEXT_ENCODER_PRESETS


class CachedTextEncoder:
    """Drop-in for `LLM2VecEncoder.__call__`: `list[str] | str` -> `(feats, lengths)`."""

    def __init__(self, cache_dir: Path) -> None:
        self._kwargs = dict(TEXT_ENCODER_PRESETS["llm2vec"]["kwargs"])
        kw = self._kwargs
        self._key_prefix = f"{kw['base_model_name_or_path']}|{kw['peft_model_name_or_path']}|{kw['dtype']}"
        self._cache_dir = cache_dir
        self._inner: LLM2VecEncoder | None = None
        self.hits = 0
        self.misses = 0
        cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def loaded(self) -> bool:
        return self._inner is not None

    def _path(self, text: str) -> Path:
        key = hashlib.sha256((self._key_prefix + "\0" + text).encode()).hexdigest()
        return self._cache_dir / f"{key}.pt"

    def _embed(self, text: str) -> torch.Tensor:
        path = self._path(text)
        if path.exists():
            self.hits += 1
            cached: torch.Tensor = torch.load(path, weights_only=True)
            return cached
        self.misses += 1
        if self._inner is None:
            self._inner = LLM2VecEncoder(**self._kwargs)
        feats, _lengths = self._inner([text])
        feat: torch.Tensor = feats[0].cpu()
        tmp = path.with_suffix(".pt.tmp")
        torch.save(feat, tmp)
        os.replace(tmp, path)
        return feat

    def __call__(self, texts: list[str] | str) -> tuple[torch.Tensor, list[int] | int]:
        if isinstance(texts, str):
            return self._embed(texts), 1
        feats = [self._embed(t) for t in texts]
        return torch.stack(feats), [1] * len(feats)
