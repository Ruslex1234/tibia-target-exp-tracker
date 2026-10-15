#!/usr/bin/env python3
"""
Probe: can a GitHub Actions runner read tibia.com highscores directly?

Fetches one vocation filtered experience page per vocation for a world and
reports whether Cloudflare let us through and whether the table parsed.
Standard library only. Nothing is committed or posted anywhere.
"""

import gzip
import html
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

WORLD = os.environ.get("PROBE_WORLD", "Firmera")
CATEGORY_EXPERIENCE = 6
PROFESSIONS = {"all": 0, "none": 1, "knights": 2, "paladins": 3, "sorcerers": 4, "druids": 5, "monks": 6}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip",
}


def highscores_url(world: str, profession: int, page: int) -> str:
    query = urllib.parse.urlencode({
        "subtopic": "highscores",
        "world": world,
        "category": CATEGORY_EXPERIENCE,
        "profession": profession,
        "currentpage": page,
    })
    return f"https://www.tibia.com/community/?{query}"


def fetch(url: str):
    """Return (status, headers, body text). Never raises on HTTP errors."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status, headers, raw = resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        status, headers, raw = e.code, e.headers, e.read()
    if headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return status, headers, raw.decode("utf-8", errors="replace")


class RowParser(HTMLParser):
    """Collect the text of every table row as a list of cell strings."""

    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "td" and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_highscores(body: str):
    """Rows look like: Rank | Name | Vocation | World | Level | Points."""
    parser = RowParser()
    parser.feed(body)
    entries = []
    for cells in parser.rows:
        if len(cells) >= 6 and cells[0].isdigit() and cells[4].isdigit():
            entries.append({
                "rank": int(cells[0]),
                "name": html.unescape(cells[1]),
                "vocation": cells[2],
                "world": cells[3],
                "level": int(cells[4]),
                "experience": int(re.sub(r"[^\d]", "", cells[5]) or 0),
            })
    results = re.search(r"Results:\s*([\d,.]+)", body)
    return entries, (results.group(1) if results else "?")


def main():
    print(f"Probing tibia.com highscores for world {WORLD}\n")
    blocked = 0
    for name, profession in PROFESSIONS.items():
        url = highscores_url(WORLD, profession, 1)
        status, headers, body = fetch(url)
        title = re.search(r"<title>(.*?)</title>", body, re.S)
        challenge = headers.get("cf-mitigated") or ("Just a moment" in body and "challenge")
        entries, results = parse_highscores(body)

        print(f"== {name} (profession={profession})")
        print(f"   URL:        {url}")
        print(f"   HTTP:       {status}  server={headers.get('server')}  cf-ray={headers.get('cf-ray')}")
        print(f"   Title:      {title.group(1).strip() if title else '(none)'}")
        print(f"   Challenge:  {challenge or 'no'}")
        print(f"   Results:    {results}  parsed rows on page 1: {len(entries)}")
        for e in entries[:3]:
            print(f"     #{e['rank']:<4} {e['name']:<28} {e['vocation']:<16} lvl {e['level']:<5} {e['experience']:,}")
        if entries:
            last = entries[-1]
            print(f"     ... last on page: #{last['rank']} {last['name']} lvl {last['level']}")
        else:
            blocked += 1
            print(f"   Body start: {' '.join(body[:300].split())}")
        print()
        time.sleep(2)  # be polite

    verdict = "BLOCKED or unparsed" if blocked == len(PROFESSIONS) else (
        "PARTIAL" if blocked else "OK: tibia.com highscores are readable from GitHub Actions")
    print(f"VERDICT: {verdict} ({len(PROFESSIONS) - blocked}/{len(PROFESSIONS)} filters parsed)")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### tibia.com probe ({WORLD})\n\n**{verdict}** ({len(PROFESSIONS) - blocked}/{len(PROFESSIONS)} filters parsed)\n")
    sys.exit(0 if blocked < len(PROFESSIONS) else 1)


if __name__ == "__main__":
    main()
