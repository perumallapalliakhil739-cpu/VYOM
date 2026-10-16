"""Shared fixtures: lets the ingestion pipeline be tested fully OFFLINE with a fake FIRMS feed."""
import os, sys, socket, time
from datetime import datetime, timezone, timedelta
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.services.firms_service import firms_service, FIRMS_OPEN_FEEDS  # noqa: E402

# Tests that genuinely need the live internet; skipped automatically when offline.
LIVE_TESTS = {"test_firms_hotspots_normalization", "test_weather_and_atmospheric_oxygen", "test_ingestion_audit_reporting"}


def _online():
    try:
        socket.gethostbyname("firms.modaps.eosdis.nasa.gov")
        return True
    except OSError:
        return False


def pytest_collection_modifyitems(config, items):
    if _online():
        return
    skip = pytest.mark.skip(reason="needs live network (FIRMS / Open-Meteo); run on a connected machine")
    for it in items:
        if it.name in LIVE_TESTS:
            it.add_marker(skip)


def make_row(lat, lon, hours_ago, conf="n", frp=10.0, sat="N", now=None):
    t = (now or datetime.now(timezone.utc)) - timedelta(hours=hours_ago)
    return dict(latitude=lat, longitude=lon, bright_ti4=330.0, scan=0.4, track=0.4,
                acq_date=t.strftime("%Y-%m-%d"), acq_time=t.strftime("%H%M"), satellite=sat,
                instrument="VIIRS", confidence=conf, version="2.0NRT", bright_ti5=290.0,
                frp=frp, daynight="D")


@pytest.fixture
def offline_feed(monkeypatch):
    """Returns inject(rows) -> installs rows as the SNPP feed (other feeds empty) with the network disabled."""
    import requests
    def _no_net(*a, **k):
        raise RuntimeError("network disabled in offline tests")
    monkeypatch.setattr(requests, "get", _no_net)

    def inject(rows):
        df = pd.DataFrame(rows)
        cache = {k: (df if k == "VIIRS_SNPP_NRT" else df.iloc[0:0]) for k in FIRMS_OPEN_FEEDS}
        monkeypatch.setattr(firms_service, "_memory_cache", cache)
        monkeypatch.setattr(firms_service, "_last_fetch_time", {k: time.time() for k in FIRMS_OPEN_FEEDS})
        return df
    return inject
