"""HTTPS downloads with progress and optional SHA-256 check."""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

from .toolchain import Progress

USER_AGENT = "fontlab"


class DownloadError(RuntimeError):
    pass


def fetch(url: str, dest: Path, progress: Progress, sha256: str | None = None) -> Path:
    name = url.rsplit("/", 1)[-1]
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while chunk := resp.read(1 << 16):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if total:
                    progress(f"downloading {name} {done * 100 // total}%")
    except OSError as e:
        raise DownloadError(f"download failed: {url}: {e}") from e
    if sha256 and digest.hexdigest() != sha256:
        dest.unlink(missing_ok=True)
        raise DownloadError(f"checksum mismatch for {name}")
    return dest
