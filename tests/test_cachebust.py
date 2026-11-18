"""index.html must point at content-hashed CSS and JS so deploys bust caches."""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "web"))
import stamp_assets  # noqa: E402


def test_index_html_uses_current_asset_hashes():
    html = open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
    stamped = stamp_assets.stamp(html)
    assert html == stamped, "run python3 web/stamp_assets.py after changing web assets"
    for name in stamp_assets.ASSETS:
        hashed = "%s?v=%s" % (name, stamp_assets.digest(name))
        assert hashed in html, "missing %s in index.html" % hashed
    assert re.search(r'src="mix\.js\?v=[0-9a-f]{10}"', html)
    assert re.search(r'src="app\.js\?v=[0-9a-f]{10}"', html)
    assert re.search(r'href="style\.css\?v=[0-9a-f]{10}"', html)
