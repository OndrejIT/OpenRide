import os
from pathlib import Path

import numpy as np
import pytest

# prototype data next to the repo (nakole-video/data); regression tests skip without it
DATA_DIR = Path(os.environ.get("OPENRIDE_TEST_DATA", Path(__file__).resolve().parents[2] / "data"))


def gpx_xml(lat, lon, ele) -> bytes:
    pts = "".join(
        f'<trkpt lat="{a:.7f}" lon="{o:.7f}"><ele>{e:.1f}</ele></trkpt>' for a, o, e in zip(lat, lon, ele, strict=True)
    )
    return (
        '<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><trkseg>{pts}</trkseg></trk></gpx>"
    ).encode()


def straight_climb(length_m=2000.0, grade=5.0, n=201) -> bytes:
    """Due-north track with a constant grade."""
    d = np.linspace(0, length_m, n)
    return gpx_xml(50 + d / 111195.0, np.full(n, 14.0), 200 + grade / 100 * d)


@pytest.fixture
def climb_gpx() -> bytes:
    return straight_climb()


@pytest.fixture(autouse=True)
def _plain_static_storage(settings, tmp_path):
    # the manifest storage needs collectstatic, irrelevant for tests
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.CACHE_DIR = tmp_path / "cache"
    settings.STATIC_ROOT = tmp_path
