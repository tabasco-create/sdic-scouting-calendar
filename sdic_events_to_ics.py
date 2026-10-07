#!/usr/bin/env python3
"""
Scrape San Diego-Imperial Council events -> .ics file you can import into Google Calendar.

Setup:   pip install requests beautifulsoup4
Run:     python sdic_events_to_ics.py                (upcoming events only)
         python sdic_events_to_ics.py --all          (include past events)
         python sdic_events_to_ics.py -o scouting.ics

How it works:
  1. /events has a "Complete Events List" with title, link, start and end date for
     every event. That gives dates in one request.
  2. It also walks the paginated cards (?3d3ef557_page=N) in case the complete list
     is ever truncated (Webflow caps collection lists at 100 items).
  3. Each event's detail page is fetched for location + description.
  4. Events are written as all-day events with a stable UID, so re-importing an
     updated file updates existing events instead of duplicating them.
"""
import argparse
import datetime as dt
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

BASE = "https://www.sdicscouting.org"
LIST_URL = BASE + "/events"
PAGE_PARAM = "3d3ef557_page"
HEADERS = {"User-Agent": "Mozilla/5.0 (personal calendar sync script)"}

SLUG_RE = re.compile(r"^/events/[^/?#]+$")
US_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
LONG_DATE_RE = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$")
ADDRESS_RE = re.compile(r"\bCA\s+\d{5}\b")
SESSION_DATE_RE = re.compile(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})")
TIME_RANGE_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?\s*(?:-|\u2013|\u2014|to)\s*(\d{1,2})(?::(\d{2}))?\s*(AM|PM)", re.I)
LONG_SPAN_DAYS = 14   # longer than this -> try to split into the individual sessions


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def event_href(tag):
    """Return absolute event URL if this tag is a link to /events/<slug>, else None."""
    if isinstance(tag, Tag) and tag.name == "a":
        href = urljoin(BASE, tag.get("href") or "")
        path = href.replace(BASE, "").split("?")[0].split("#")[0]
        if SLUG_RE.match(path):
            return BASE + path
    return None


# ---------- listing pages ----------

def parse_complete_list(soup):
    """Title + start/end dates for every event in the 'Complete Events List' section."""
    events, cur = {}, None
    marker = soup.find(string=re.compile(r"Complete Events List"))
    if not marker:
        return events
    for node in marker.next_elements:
        url = event_href(node)
        if url:
            cur = events.setdefault(url, {"url": url, "title": "", "dates": []})
            cur["title"] = cur["title"] or node.get_text(strip=True)
        elif isinstance(node, NavigableString):
            t = node.strip()
            if t == "Upcoming Events":      # reached the footer sidebar
                break
            if cur is not None and US_DATE_RE.match(t):
                m, d, y = map(int, t.split("/"))
                cur["dates"].append(dt.date(y, m, d))
    return {u: e for u, e in events.items() if e["dates"]}


def parse_card_urls(soup):
    """Event URLs from the paginated card grid ('our Upcoming Events' section)."""
    urls = []
    marker = soup.find(string=re.compile(r"our Upcoming Events", re.I))
    if not marker:
        return urls
    for node in marker.next_elements:
        if isinstance(node, NavigableString) and node.strip() == "Event Categories":
            break
        url = event_href(node)
        if url and url not in urls:
            urls.append(url)
    return urls


def collect_listing(max_pages=40):
    first = get(LIST_URL)
    events = parse_complete_list(first)
    card_urls = set(parse_card_urls(first))
    for page in range(2, max_pages + 1):
        try:
            soup = get(f"{LIST_URL}?{PAGE_PARAM}={page}")
        except requests.HTTPError:
            break
        urls = parse_card_urls(soup)
        if not urls:
            break
        card_urls.update(urls)
        time.sleep(0.3)
    for u in card_urls:
        events.setdefault(u, {"url": u, "title": "", "dates": []})
    return events


# ---------- detail pages ----------

def parse_detail(url):
    soup = get(url)
    h1 = soup.find("h1")
    out = {"title": h1.get_text(strip=True) if h1 else "", "location": "",
           "description": "", "dates": [], "lines": []}
    if not h1:
        return out

    lines = []
    for node in h1.next_elements:
        if isinstance(node, NavigableString):
            t = node.strip()
            if t in ("Search", "Upcoming Events"):
                break
            if t:
                lines.append(t)
        elif isinstance(node, Tag) and node.name == "a" and ADDRESS_RE.search(node.get_text()):
            out["location"] = node.get_text(strip=True)

    out["lines"] = lines

    # header date sits just above the <h1>
    header = h1.find_previous(string=LONG_DATE_RE)
    long_dates = [header.strip()] if header else []
    long_dates += [l for l in lines if LONG_DATE_RE.match(l)]
    for s in long_dates:
        try:
            out["dates"].append(dt.datetime.strptime(s, "%B %d, %Y").date())
        except ValueError:
            pass

    body = []
    for l in lines:
        if l == "Registration":
            break
        if l != out["location"] and l != "—":
            body.append(l)
    out["description"] = "\n".join(body)
    return out


# ---------- splitting long ranges into sessions ----------

def to_time(h, m, ap):
    return dt.time(int(h) % 12 + (12 if ap.upper() == "PM" else 0), int(m or 0))


def extract_sessions(lines, start, end):
    """Dated sessions (with optional times) mentioned in the page text, inside [start, end]."""
    seen, sessions = set(), []
    for line in lines:
        if LONG_DATE_RE.match(line):          # bare registration-range dates, not sessions
            continue
        for m in SESSION_DATE_RE.finditer(line):
            try:
                d = dt.datetime.strptime(m.group(0), "%B %d, %Y").date()
            except ValueError:
                continue
            if not (start <= d <= end) or d in seen:
                continue
            seen.add(d)
            times = None
            t = TIME_RANGE_RE.search(line[m.end():])
            if t:
                t2 = to_time(t.group(4), t.group(5), t.group(6))
                t1 = to_time(t.group(1), t.group(2), t.group(3) or t.group(6))
                if not t.group(3) and t1 >= t2:   # e.g. "10-2 PM" means 10 AM
                    t1 = to_time(t.group(1), t.group(2), "AM")
                times = (t1, t2)
            sessions.append({"date": d, "times": times})
    return sorted(sessions, key=lambda x: x["date"])


# ---------- ICS output ----------

def esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    raw, out = line.encode("utf-8"), []
    while len(raw) > 74:
        cut = 74
        while (raw[cut] & 0xC0) == 0x80:   # don't split a UTF-8 character
            cut -= 1
        out.append(raw[:cut].decode("utf-8"))
        raw = b" " + raw[cut:]
    out.append(raw.decode("utf-8"))
    return "\r\n".join(out)


def timing_lines(e):
    if e.get("times"):
        t1, t2 = e["times"]
        tz = "TZID=America/Los_Angeles"
        return [f"DTSTART;{tz}:{e['start']:%Y%m%d}T{t1:%H%M%S}",
                f"DTEND;{tz}:{e['start']:%Y%m%d}T{t2:%H%M%S}"]
    return [f"DTSTART;VALUE=DATE:{e['start']:%Y%m%d}",
            f"DTEND;VALUE=DATE:{(e['end'] + dt.timedelta(days=1)):%Y%m%d}"]  # exclusive


def build_ics(events):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SDIC scouting scraper//EN",
             "CALSCALE:GREGORIAN", "X-WR-CALNAME:SDIC Scouting Events",
             "X-WR-TIMEZONE:America/Los_Angeles"]
    for e in events:
        slug = e.get("uid") or e["url"].rsplit("/", 1)[-1]
        desc = (e["description"] + "\n\n" if e["description"] else "") + e["url"]
        lines += [
            "BEGIN:VEVENT",
            f"UID:{slug}@sdicscouting.org",
            f"DTSTAMP:{e['start']:%Y%m%d}T000000Z",  # stable, so unchanged events don't churn the file
            *timing_lines(e),
            f"SUMMARY:{esc(e['title'])}",
            f"DESCRIPTION:{esc(desc)}",
            f"URL:{e['url']}",
        ]
        if e["location"]:
            lines.append(f"LOCATION:{esc(e['location'])}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n"


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="sdic_events.ics")
    ap.add_argument("--all", action="store_true", help="include events that already ended")
    args = ap.parse_args()

    listing = collect_listing()
    print(f"Found {len(listing)} events. Fetching detail pages...")

    final, today = [], dt.date.today()
    for i, (url, base) in enumerate(listing.items(), 1):
        try:
            d = parse_detail(url)
        except Exception as ex:
            print(f"  ! skipped {url}: {ex}")
            continue
        dates = base["dates"] or d["dates"]       # listing dates win; detail page is fallback
        if not dates:
            print(f"  ! no dates for {url}")
            continue
        start, end = min(dates), max(dates)
        if not args.all and end < today:
            continue
        title = d["title"] or base["title"]
        common = {"url": url, "title": title, "location": d["location"],
                  "description": d["description"]}
        sessions = []
        if (end - start).days > LONG_SPAN_DAYS:
            sessions = extract_sessions(d["lines"], start, end)
        if len(sessions) >= 2:
            slug = url.rsplit("/", 1)[-1]
            print(f"  * {title}: {start} to {end} split into {len(sessions)} sessions")
            for n, sess in enumerate(sessions, 1):
                if not args.all and sess["date"] < today:
                    continue
                final.append({**common, "title": f"{title} ({n}/{len(sessions)})",
                              "uid": f"{slug}-{sess['date']:%Y%m%d}",
                              "start": sess["date"], "end": sess["date"], "times": sess["times"]})
        else:
            if (end - start).days > LONG_SPAN_DAYS:
                print(f"  ? {title}: spans {(end - start).days + 1} days, no sessions found - check the source")
            final.append({**common, "start": start, "end": end})
        print(f"  [{i}/{len(listing)}] {start} {title}")
        time.sleep(0.3)

    final.sort(key=lambda e: e["start"])
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        f.write(build_ics(final))
    print(f"\nWrote {len(final)} events to {args.out}")
    print("Import: Google Calendar > Settings > Import & export > Import")


if __name__ == "__main__":
    main()
