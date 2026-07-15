"""Browser end-to-end smoke test for the static frontend (issue #124).

Automates the manual 2026-07-10 browser verification (#92 task 2): serves
``www/`` locally, intercepts the frontend's data fetches with the committed
synthetic fixture (``tests/e2e/fixture``, built by ``build_fixture.py``),
and drives real headless Chromium across the full render path.

This is a SEPARATE, non-blocking job — marked ``e2e`` and excluded from the fast
``pytest`` run (see pyproject ``addopts``); the e2e CI job opts back in with
``-m e2e``. It needs ``pytest-playwright`` + a Chromium install, so we skip the
whole module cleanly when the plugin isn't present (e.g. the fast job).

Assertions (seeded from the manual run):
  * overview draws rectangles; no ``Infinity``/``NaN``/epoch in any popup (B1–B4)
  * provider toggle works and persists via ``?provider=``
  * city page: Chart.js canvas renders; snapshot ``<select>`` on a multi-run city
  * 0-pano city shows ``—``, not the Unix epoch date (#122 / #69)
  * console/page-error clean on both pages and providers
"""

import functools
import http.server
import os
import socketserver
import threading

import pytest

pytest.importorskip("pytest_playwright")
from playwright.sync_api import Page, expect  # noqa: E402

pytestmark = pytest.mark.e2e

HERE = os.path.dirname(os.path.abspath(__file__))
WWW_DIR = os.path.join(os.path.dirname(os.path.dirname(HERE)), "www")
FIXTURE_DIR = os.path.join(HERE, "fixture")

# Latest-run csv.gz filenames the fixture emits (see build_fixture.py).
ALPHA_LATEST = "alpha-city--alphastate--testland_width_100_height_100_step_20_2026-04-15.csv.gz"
ZERO_CITY = "zero-city--zerostate--testland_width_100_height_100_step_20_2026-04-15.csv.gz"

# Substrings of expected third-party console noise to ignore (analytics/CDN),
# so "console clean" tracks OUR code, not the network environment. The streets
# artifact is optional by design (issue #24) — the fixture has none, so the
# browser logs a 404 console.error for the "_streets.json.gz" fetch that
# street-coverage.js then handles as a silent no-op.
_IGNORABLE_CONSOLE = (
    "favicon",
    "googletagmanager",
    "gtag",
    "google-analytics",
    "doubleclick",
    "_streets.json.gz",
)


@pytest.fixture(scope="session")
def base_url():
    """Serve www/ over http on an ephemeral port for the whole session."""
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=WWW_DIR)

    class QuietServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    httpd = QuietServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture(autouse=True)
def route_fixture_data(page: Page):
    """Fulfill every data fetch from the committed fixture.

    The frontend hardcodes the production data host (STREETSCAPE_DATA_BASE_URL); rather
    than change prod code, we intercept ``**/streetscape-tracker/data/**`` and serve the
    fixture bytes RAW (no Content-Encoding: gzip) so the page's own pako /
    DecompressionStream("gzip") does the decompression, exactly as in prod.
    """

    def handler(route):
        filename = route.request.url.split("/data/")[-1].split("?")[0]
        path = os.path.join(FIXTURE_DIR, filename)
        if not os.path.isfile(path):
            route.fulfill(status=404, body=b"not in fixture")
            return
        with open(path, "rb") as f:
            body = f.read()
        route.fulfill(
            status=200,
            body=body,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(body)),
                "Access-Control-Allow-Origin": "*",
            },
        )

    page.route("**/streetscape-tracker/data/**", handler)
    yield


def _capture_errors(page: Page):
    """Attach console-error + pageerror listeners; return the collected list."""
    errors = []
    page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
    page.on(
        "console",
        lambda msg: (
            errors.append(f"console.{msg.type}: {msg.text}")
            if msg.type == "error" and not any(s in msg.text for s in _IGNORABLE_CONSOLE)
            else None
        ),
    )
    return errors


def test_overview_renders_without_infinity_or_nan(page: Page, base_url):
    errors = _capture_errors(page)
    page.goto(f"{base_url}/index.html")

    # Both GSV cities (Alpha + the 0-pano Zero City) draw a rectangle. A B1–B4
    # crash on the 0-pano city would abort rendering before this succeeds.
    rects = page.locator("path.leaflet-interactive")
    expect(rects).to_have_count(2)

    # Every popup must be free of the Infinity%/NaN/epoch-date bugs. Open one
    # at a time (close between) so the popup locator stays unambiguous.
    popup = page.locator(".leaflet-popup-content")
    for i in range(rects.count()):
        rects.nth(i).click(force=True)
        expect(popup).to_have_count(1)
        text = popup.inner_text()
        for bad in ("Infinity", "NaN", "1969", "1970"):
            assert bad not in text, f"popup {i} contained {bad!r}:\n{text}"
        page.keyboard.press("Escape")
        expect(popup).to_have_count(0)

    assert errors == []


def test_provider_toggle_persists_via_query_param(page: Page, base_url):
    page.goto(f"{base_url}/index.html")
    expect(page.locator("path.leaflet-interactive")).to_have_count(2)  # gsv default

    page.locator('input[name="provider"][value="mapillary"]').check()
    page.wait_for_url("**provider=mapillary**")
    # Only the single Mapillary city remains after the toggle.
    expect(page.locator("path.leaflet-interactive")).to_have_count(1)

    # The choice survives a reload (persisted in the URL, re-read on load).
    page.reload()
    expect(page.locator('input[name="provider"][value="mapillary"]')).to_be_checked()
    expect(page.locator("path.leaflet-interactive")).to_have_count(1)


def test_city_page_multirun_gsv_renders_chart_and_snapshot_select(page: Page, base_url):
    errors = _capture_errors(page)
    page.goto(f"{base_url}/city.html?file={ALPHA_LATEST}")

    # Chart.js canvas is present and laid out (non-zero size).
    canvas = page.locator("#temporal-plot")
    expect(canvas).to_be_visible()
    box = canvas.bounding_box()
    assert box and box["width"] > 0 and box["height"] > 0

    # Multi-run city → snapshot <select>, one <option> per run (2), filtered to
    # the active (GSV) provider.
    select = page.locator("#run-select")
    expect(select).to_be_visible()
    expect(select.locator("option")).to_have_count(2)

    assert errors == []


def test_zero_pano_city_shows_dash_not_epoch(page: Page, base_url):
    errors = _capture_errors(page)
    page.goto(f"{base_url}/city.html?file={ZERO_CITY}")

    stats = page.locator("table.legend-stats")
    expect(stats).to_be_visible()
    text = stats.inner_text()
    # The #122 / #69 regression: null oldest/newest dates must render "—", never
    # the Unix epoch from new Date(null).
    assert "—" in text
    for bad in ("1969", "1970"):
        assert bad not in text, f"legend showed epoch date {bad!r}:\n{text}"

    assert errors == []
