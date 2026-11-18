#!/usr/bin/env python3
"""Write content-hash query strings onto style.css, mix.js, and app.js in index.html.

Run this after changing those files so phones and other caches pick up the new
copy. The deploy copies web/ as-is, so the hashes have to be current in the
commit.
"""
import hashlib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = ("style.css", "mix.js", "app.js")


def digest(name):
    path = os.path.join(HERE, name)
    return hashlib.md5(open(path, "rb").read()).hexdigest()[:10]


def stamp(html):
    out = html
    for name in ASSETS:
        hashed = "%s?v=%s" % (name, digest(name))
        out, n = re.subn(
            r'((?:href|src)=")%s(?:\?v=[^"]*)?(")' % re.escape(name),
            r"\1%s\2" % hashed,
            out,
        )
        if n < 1:
            raise SystemExit("index.html has no %s reference to stamp" % name)
    return out


def main():
    path = os.path.join(HERE, "index.html")
    html = open(path, encoding="utf-8").read()
    updated = stamp(html)
    if updated == html:
        print("already stamped")
        return 0
    open(path, "w", encoding="utf-8").write(updated)
    print("stamped", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
