#!/usr/bin/env python3
"""
Coastal Sage District Roundtable -> recurring calendar events.

The council's /events page doesn't list Roundtable, but the Coastal Sage District page says when
and where it meets (e.g. "second Thursday, 6:30-8:00 PM at <church>"). This module reads that
page, works out the rule, and creates one event per month so the calendar stays in step with it.

Used two ways:
  * imported by sdic_events_to_ics.py, which adds the events on every run
  * run weekly as a watcher:   python roundtable.py --check
      compares the rule on the page with the one saved in docs/roundtable.json and reports a change
      (writes a Slack message with --slack-payload, exits 1 if the page can't be understood any more)
"""
import argparse
import calendar
import datetime as dt
import hashlib
import json
import os
import re
import sys

import requests
from bs4 import BeautifulSoup

PAGE_URL = "https://www.sdicscouting.org/leading-scouts/districts/coastal-sage"
HEADERS = {"User-Agent": "Mozilla/5.0 (personal calendar sync script)"}
STATE_PATH = "docs/roundtable.json"
MONTHS_AHEAD = 12
TITLE = "Coastal Sage Roundtable"

# What the page said when this was written (second Thursday, 6:30-8:00 PM). Used only for fields
# the page doesn't state clearly, or when the page can't be reached.
DEFAULT_RULE = {"nth": 2, "weekday": 3,                      # weekday: Monday=0 ... Sunday=6
                "start": "18:30", "end": "20:00",
                "location": "Northminster Presbyterian Church, 4324 Clairemont Mesa Blvd, "
                            "San Diego, CA 92117"}

ORDINALS = {"1st": 1, "first": 1, "2nd": 2, "second": 2, "3rd": 3, "third": 3,
            "4th": 4, "fourth": 4, "last": -1}
DAYS = {d.lower(): i for i, d in enumerate(calendar.day_name)}
ORD_RE = re.compile(r"\b(1st|first|2nd|second|3rd|third|4th|fourth|last)\s+(" + "|".join(DAYS) + r")s?\b", re.I)
TIME_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\s*(?:-|–|—|to)\s*"
    r"(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)", re.I)


def to_24h(h, m, ap):
    h, m = int(h), int(m or 0)
    ap = ap.lower().replace(".", "")
    if ap == "pm" and h != 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return f"{h:02d}:{m:02d}"


def parse_rule(text):
    """Return (rule, found) from the page text. `found` says whether the day and time were read
    from the page; anything unreadable falls back to DEFAULT_RULE."""
    flat = re.sub(r"\s+", " ", text)
    # same text with line breaks kept as ", ", so an address split over several lines reads naturally
    lined = re.sub(r"\s*\n\s*", ", ", re.sub(r"[ \t]+", " ", text))
    rule, found = dict(DEFAULT_RULE), False
    for m in re.finditer(r"round\s*table", flat, re.I):
        window = flat[m.start(): m.start() + 600]
        o, t = ORD_RE.search(window), TIME_RE.search(window)
        if not (o and t):
            continue
        rule["nth"] = ORDINALS[o.group(1).lower()]
        rule["weekday"] = DAYS[o.group(2).lower()]
        end_ap = t.group(6)
        rule["start"] = to_24h(t.group(1), t.group(2), t.group(3) or end_ap)
        rule["end"] = to_24h(t.group(4), t.group(5), end_ap)
        after = window[t.end():]
        lm = re.search(r"round\s*table", lined, re.I)
        lt = TIME_RE.search(lined[lm.start(): lm.start() + 600]) if lm else None
        if lm and lt:
            after = lined[lm.start():][lt.end():][:400]
        loc = re.match(r"\s*(?:at|@|,|-|–)?\s*(.{5,200}?\b\d{5}\b)", after)
        if loc and re.search(r"\d", loc.group(1)):
            rule["location"] = re.sub(r"^(?:at|@)\s+", "", loc.group(1).strip(" ,."), flags=re.I)
        found = True
        break
    return rule, found


def fetch_page_text(url=PAGE_URL):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser").get_text("\n")


def load_state(path=STATE_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def current_rule(state_path=STATE_PATH):
    """Rule to use right now: the live page if it can be read, else the last saved one, else defaults."""
    try:
        rule, found = parse_rule(fetch_page_text())
        if found:
            return rule, "page"
        print("  ! Roundtable: the district page no longer says when it meets; using the saved rule")
    except Exception as ex:
        print(f"  ! Roundtable: couldn't read the district page ({ex}); using the saved rule")
    saved = load_state(state_path).get("rule")
    return (saved or dict(DEFAULT_RULE)), "saved"


def nth_weekday(year, month, nth, weekday):
    if nth == -1:
        last = calendar.monthrange(year, month)[1]
        d = dt.date(year, month, last)
        return d - dt.timedelta(days=(d.weekday() - weekday) % 7)
    first = dt.date(year, month, 1)
    d = first + dt.timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))
    return d if d.month == month else None


def roundtable_events(today, include_past=False, state_path=STATE_PATH):
    rule, source = current_rule(state_path)
    h1, m1 = map(int, rule["start"].split(":"))
    h2, m2 = map(int, rule["end"].split(":"))
    events, y, m = [], today.year, today.month
    for _ in range(MONTHS_AHEAD + 1):
        d = nth_weekday(y, m, rule["nth"], rule["weekday"])
        if d and (include_past or d >= today):
            events.append({
                "url": PAGE_URL, "title": TITLE, "location": rule["location"],
                "description": "Monthly district meeting for Scouters. Added from the Coastal Sage "
                               "District page (not listed on the council events page); check with "
                               "your unit leaders if a month is skipped.",
                "uid": f"roundtable-coastal-sage-{d:%Y%m%d}",
                "start": d, "end": d, "times": (dt.time(h1, m1), dt.time(h2, m2))})
        m += 1
        if m > 12:
            y, m = y + 1, 1
    print(f"Roundtable: {len(events)} events from the {source} rule "
          f"({rule['nth']} / weekday {rule['weekday']}, {rule['start']}-{rule['end']})")
    return events


def describe(rule):
    names = {1: "first", 2: "second", 3: "third", 4: "fourth", -1: "last"}
    t = lambda s: dt.datetime.strptime(s, "%H:%M").strftime("%I:%M %p").lstrip("0")
    return (f"{names[rule['nth']]} {calendar.day_name[rule['weekday']]}, {t(rule['start'])}–{t(rule['end'])}"
            f" at {rule['location']}")


def check(state_path, slack_path):
    """Weekly watcher. Exit 0 = fine (or rule changed and was saved); exit 1 = page not understood."""
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        text = fetch_page_text()
    except Exception as ex:
        print(f"ERROR: couldn't read the district page: {ex}")
        return 1
    rule, found = parse_rule(text)
    if not found:
        print("ERROR: the district page no longer states when Roundtable meets "
              "(or its layout changed). The calendar keeps using the last saved rule.")
        return 1
    state = load_state(state_path)
    old = state.get("rule")
    section = re.sub(r"\s+", " ", text)
    i = section.lower().find("roundtable")
    digest = hashlib.sha256(section[i:i + 600].encode()).hexdigest()[:12]
    if old != rule:
        print("ROUNDTABLE CHANGED:\n  was: " + (describe(old) if old else "(not recorded yet)")
              + "\n  now: " + describe(rule))
        if old and slack_path:
            msg = (f"*Coastal Sage Roundtable details changed* on the district page.\n"
                   f"Was: {describe(old)}\nNow: {describe(rule)}\n"
                   f"<{PAGE_URL}|District page>. The calendar updates on the next daily run.")
            with open(slack_path, "w", encoding="utf-8") as f:
                json.dump({"text": msg}, f, ensure_ascii=False)
    else:
        print("Roundtable rule unchanged: " + describe(rule))
    os.makedirs(os.path.dirname(state_path) or ".", exist_ok=True)
    with open(state_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"checked_at": now, "rule": rule, "page_text_hash": digest}, f, indent=1)
        f.write("\n")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="weekly watcher (see top of file)")
    ap.add_argument("--state", default=STATE_PATH)
    ap.add_argument("--slack-payload")
    a = ap.parse_args()
    if not a.check:
        ap.error("nothing to do; use --check (the main script imports this module)")
    sys.exit(check(a.state, a.slack_payload))
