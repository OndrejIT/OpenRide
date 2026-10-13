import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

from pipeline import gpx
from routes.models import Route

YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
# no API key needed; also refuses videos that cannot be embedded, which the trainer could not play
OEMBED_URL = "https://www.youtube.com/oembed?format=json&url=https://www.youtube.com/watch?v={}"


def parse_youtube_id(value: str) -> str:
    """YouTube URL (watch, youtu.be, shorts, embed, live) or a bare ID -> 11-character video ID."""
    value = value.strip()
    if YT_ID.match(value):
        return value
    url = urlparse(value if "://" in value else f"https://{value}")
    host = (url.hostname or "").removeprefix("www.").removeprefix("m.")
    candidate = ""
    if host == "youtu.be":
        candidate = url.path.lstrip("/").split("/")[0]
    elif host.endswith("youtube.com") or host == "youtube-nocookie.com":
        parts = url.path.strip("/").split("/")
        if parts[0] == "watch":
            candidate = parse_qs(url.query).get("v", [""])[0]
        elif parts[0] in ("shorts", "embed", "live", "v") and len(parts) > 1:
            candidate = parts[1]
    if not YT_ID.match(candidate):
        raise ValueError("Neplatná URL YouTube videa")
    return candidate


def youtube_title(video_id: str) -> str:
    """Video title from YouTube oEmbed; the video ID when YouTube does not answer."""
    try:
        with urlopen(OEMBED_URL.format(video_id), timeout=5) as resp:
            return json.load(resp)["title"][: Route._meta.get_field("title").max_length]
    except HTTPError as e:
        if e.code in (400, 401, 403, 404):
            raise ValueError("Video na YouTube neexistuje, je soukromé nebo nejde vložit na jiný web") from e
        return video_id
    except (URLError, TimeoutError, ValueError, KeyError):
        return video_id


def load_track(route: Route) -> gpx.Track:
    with route.gpx.open("rb") as fh:
        return gpx.parse(fh.read())


def set_profile(route: Route, profile: dict) -> None:
    """Profile with summaries; the map geometry exists only for a profile with positions (from GPX)."""
    route.profile = profile
    route.segment = gpx.simplify(profile["lat"], profile["lon"]) if "lat" in profile else None
    for key, value in gpx.summary(profile).items():
        setattr(route, key, value)


def apply_gpx(route: Route) -> None:
    """Whole-track profile, summaries and map geometry from the route's GPX (virtual ride)."""
    profile, _ = gpx.track_profile(load_track(route))
    set_profile(route, profile)
