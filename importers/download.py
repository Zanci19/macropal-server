"""Resumable download of a large dump file, with size and checksum reporting.

The OpenFoodFacts JSONL export is ~13 GB. A broken SSH session or a flaky link
should cost the remaining bytes, not the whole transfer, so the file is fetched
with an HTTP `Range` request that continues from whatever is already on disk.
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

CHUNK = 1024 * 1024


@dataclass(slots=True)
class DownloadResult:
    path: Path
    size: int
    sha256: str | None
    resumed_from: int
    downloaded: int
    remote_last_modified: str | None

    @property
    def already_complete(self) -> bool:
        return self.downloaded == 0


def human(num: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(num) < 1024 or unit == "TiB":
            return f"{num:,.1f} {unit}"
        num /= 1024
    return f"{num} B"


def remote_info(url: str, timeout: float = 60.0) -> tuple[int | None, str | None]:
    """`(content_length, last_modified)` for `url`, following redirects."""
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        response = client.head(url)
        response.raise_for_status()

    length = response.headers.get("content-length")
    return (int(length) if length else None), response.headers.get("last-modified")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)

    return digest.hexdigest()


def download(
    url: str,
    dest: Path,
    *,
    resume: bool = True,
    checksum: bool = False,
    timeout: float = 60.0,
) -> DownloadResult:
    """Fetch `url` into `dest`, continuing a partial file when there is one.

    A `.part` file holds the partial download; it is renamed into place only
    once the transfer matches the length the server advertised, so a truncated
    file can never be mistaken for a finished one.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")

    expected, last_modified = remote_info(url, timeout=timeout)
    log.info(
        "remote %s: %s%s",
        url,
        human(expected) if expected else "unknown size",
        f", last modified {last_modified}" if last_modified else "",
    )

    if dest.exists() and expected is not None and dest.stat().st_size == expected:
        log.info("%s is already complete (%s)", dest, human(expected))
        return DownloadResult(
            path=dest,
            size=expected,
            sha256=sha256_file(dest) if checksum else None,
            resumed_from=expected,
            downloaded=0,
            remote_last_modified=last_modified,
        )

    start = partial.stat().st_size if (resume and partial.exists()) else 0

    if start and expected is not None and start >= expected:
        # Leftover from an interrupted run against an older, larger dump.
        log.warning("partial file is >= the remote size; starting over")
        start = 0

    headers = {"Range": f"bytes={start}-"} if start else {}
    mode = "ab" if start else "wb"

    if start:
        log.info("resuming at %s", human(start))

    downloaded = 0
    began = time.monotonic()
    last_log = began

    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        with client.stream("GET", url, headers=headers) as response:
            if start and response.status_code == 200:
                # The server ignored the Range header — restart cleanly.
                log.warning("server ignored Range; restarting from zero")
                start, mode, downloaded = 0, "wb", 0

            response.raise_for_status()

            with partial.open(mode) as handle:
                for chunk in response.iter_bytes(CHUNK):
                    handle.write(chunk)
                    downloaded += len(chunk)

                    now = time.monotonic()
                    if now - last_log >= 10:
                        rate = downloaded / max(now - began, 1e-9)
                        done = start + downloaded
                        pct = f" ({done / expected:.1%})" if expected else ""
                        log.info("%s%s at %s/s", human(done), pct, human(rate))
                        last_log = now

    size = partial.stat().st_size

    if expected is not None and size != expected:
        raise RuntimeError(
            f"download incomplete: got {size} bytes, server advertised {expected}. "
            f"Re-run to resume from {partial}."
        )

    partial.replace(dest)
    log.info("saved %s (%s)", dest, human(size))

    digest = None
    if checksum:
        log.info("computing sha256 (reads the whole file once)...")
        digest = sha256_file(dest)
        log.info("sha256 %s", digest)

    return DownloadResult(
        path=dest,
        size=size,
        sha256=digest,
        resumed_from=start,
        downloaded=downloaded,
        remote_last_modified=last_modified,
    )
