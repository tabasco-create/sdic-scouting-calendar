# SDIC Scouting Events Calendar

A free, parent-run calendar feed of upcoming events from the [San Diego-Imperial Council](https://www.sdicscouting.org/events). Subscribe once and new events show up in your calendar app automatically.

> **Unofficial.** This project is not run or endorsed by the San Diego-Imperial Council or Scouting America. It is built from the council's public events page, and the [council website](https://www.sdicscouting.org/events) is always the source of truth. Check each event's page for times, costs, forms and registration.

## Subscribe

**[Open the subscribe page](https://tabasco-create.github.io/sdic-scouting-calendar/)**

Or use these directly:

| App | How |
|---|---|
| Google Calendar | [Click to add](https://calendar.google.com/calendar/r?cid=webcal://tabasco-create.github.io/sdic-scouting-calendar/sdic_events.ics) |
| Apple Calendar / Outlook | [Click to subscribe](webcal://tabasco-create.github.io/sdic-scouting-calendar/sdic_events.ics) |
| Any other app | Subscribe by URL: `https://tabasco-create.github.io/sdic-scouting-calendar/sdic_events.ics` |

Please **subscribe** rather than download and import the file. A subscription updates itself, while an import is a one-time copy that goes stale.

## Good to know

- **Events are all-day entries.** Times, when the council lists them, are on each event's page.
- **Updates run daily, but your app may be slower.** Google Calendar can take several hours to a day to refresh subscribed calendars. Apple and Outlook are usually quicker.
- **Multi-day events** (camporees, camps, trainings) appear as a single block across their dates.
- **Errors in the council's listing carry over.** If a date on the council site looks wrong, it will look wrong here too.

## How it works

1. A Python script (`sdic_events_to_ics.py`) reads the council's events page, which lists every event with its dates, then visits each event's page for the location and description.
2. It writes the results to a standard calendar file (`docs/sdic_events.ics`).
3. A GitHub Action runs the script on a schedule and saves the updated file.
4. GitHub Pages serves the file at a fixed address, which is what calendar apps subscribe to.

Each event keeps a stable ID, so changes to an existing event update it in your calendar instead of creating duplicates.

## Something wrong?

- **Wrong or missing event?** First check the [council's events page](https://www.sdicscouting.org/events). If it looks right there but wrong here, [open an issue](../../issues) with the event name and what's off.
- **Calendar stopped updating?** The council may have changed their website layout, which can break the script. Open an issue and it will get looked at.

## Running it yourself

```
pip install requests beautifulsoup4
python sdic_events_to_ics.py            # upcoming events only
python sdic_events_to_ics.py --all      # include past events
python sdic_events_to_ics.py -o my.ics  # custom output file
```

The script is deliberately gentle on the council's server: one request per event with a short pause between each, run once a day.

## Credits

Event information belongs to the San Diego-Imperial Council. This repository only reformats it into a calendar feed.
