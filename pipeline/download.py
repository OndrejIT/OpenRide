"""YouTube download (video only, mp4 up to 720p: enough for VO and OCR, a fraction of the size of HD)."""

from pathlib import Path

from pipeline.progress import report

# H.264 first: the OpenCV wheels on linux/aarch64 cannot decode AV1, which YouTube often serves as the mp4 variant
FORMAT = "bv*[height<={h}][vcodec^=avc1]/bv*[height<={h}][ext=mp4]/b[height<={h}][ext=mp4]/bv*[height<={h}]"


def youtube_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _report(d: dict) -> None:
    if d.get("status") == "downloading":
        report(
            "stahování videa",
            d.get("downloaded_bytes") or 0,
            d.get("total_bytes") or d.get("total_bytes_estimate") or 0,
        )


def download(video_id: str, workdir: Path, name: str = "video", height: int = 720) -> Path:
    import yt_dlp

    workdir.mkdir(parents=True, exist_ok=True)
    out = workdir / f"{name}.mp4"
    if out.exists():
        return out
    opts = {
        "format": FORMAT.format(h=height),
        "outtmpl": str(workdir / f"{name}.download.%(ext)s"),
        "quiet": True,
        "noprogress": True,
        "noplaylist": True,
        "progress_hooks": [_report],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(youtube_url(video_id), download=True)
        Path(ydl.prepare_filename(info)).rename(out)
    return out
