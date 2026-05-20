"""
src/scraper.py

UFC Stats Web Scraper
Scrapes fight, event, and fighter data from ufcstats.com and saves it to
data/raw_fights.csv for downstream feature engineering and ML.

Site structure:
  Events list  : http://ufcstats.com/statistics/events/completed?page=all
  Event detail : http://ufcstats.com/event-details/<id>
  Fight detail : http://ufcstats.com/fight-details/<id>
  Fighter page : http://ufcstats.com/fighter-details/<id>

Usage:
  python -m src.scraper                  # scrape everything → data/raw_fights.csv
  python -m src.scraper --max-events 5   # quick test with 5 events
"""

import argparse
import re
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

# ── Config ──────────────────────────────────────────────────────────────────
# All of this will need to get moved to an env file later.

# TODO MOVE ALL OF THIS TO A CONFIG FILE OR ENV VARS.
BASE_URL = "http://ufcstats.com"
EVENTS_URL = f"{BASE_URL}/statistics/events/completed?page=all"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "data" / "raw_fights.csv"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; UFC-ML-Scraper/1.0; +research)"}
REQUEST_DELAY = 1.5  # seconds between requests – be polite


# ── HTTP helper ──────────────────────────────────────────────────────────────
def _get_soup(url: str) -> BeautifulSoup:
    """Fetch *url* and return a BeautifulSoup parse tree. Sleeps after each call."""
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    time.sleep(REQUEST_DELAY)
    return BeautifulSoup(resp.text, "html.parser")


# ── Value parsing helpers ────────────────────────────────────────────────────
def _parse_int(val: str) -> Optional[int]:
    val = val.strip()
    return int(val) if val.lstrip("-").isdigit() else None


def _parse_pct(val: str) -> Optional[float]:
    """'67%' → 0.67, '---' → None"""
    val = val.strip().replace("%", "")
    try:
        return round(float(val) / 100, 4)
    except ValueError:
        return None


def _parse_of(val: str) -> tuple[Optional[int], Optional[int]]:
    """'10 of 30' → (10, 30)"""
    m = re.match(r"(\d+)\s+of\s+(\d+)", val.strip())
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def _parse_ctrl(val: str) -> Optional[int]:
    """'2:30' → 150 (seconds). '--' or empty → None."""
    val = val.strip()
    if not val or val == "--":
        return None
    m = re.match(r"(\d+):(\d{2})", val)
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _parse_height(val: str) -> Optional[float]:
    """'6\\' 2"' → 74.0 (inches)"""
    m = re.match(r"(\d+)'\s*(\d+)", val.strip())
    return float(int(m.group(1)) * 12 + int(m.group(2))) if m else None


def _parse_reach(val: str) -> Optional[float]:
    """'72"' → 72.0"""
    m = re.match(r"(\d+\.?\d*)", val.strip())
    return float(m.group(1)) if m else None


def _parse_weight(val: str) -> Optional[float]:
    """'185 lbs.' → 185.0"""
    m = re.match(r"(\d+\.?\d*)", val.strip())
    return float(m.group(1)) if m else None


# ── 1. Events list ───────────────────────────────────────────────────────────
def scrape_event_urls() -> list[dict]:
    """
    Scrape the completed-events index page.

    Returns a list of dicts:
        event_name, event_date, event_location, event_url
    """
    soup = _get_soup(EVENTS_URL)
    table = soup.find("table", class_="b-statistics__table-events")
    if not table:
        raise RuntimeError(
            "Events table not found — check CSS selector or site structure."
        )

    events = []
    for row in table.select("tbody tr.b-statistics__table-row"):
        cells = row.find_all("td")
        if not cells:
            continue

        name_link = cells[0].find("a")
        if not name_link:
            continue

        name = name_link.get_text(strip=True)
        url = name_link["href"]

        # Date is often in a <span class="b-statistics__date"> inside the first cell
        date_tag = cells[0].find("span", class_="b-statistics__date")
        if date_tag:
            date = date_tag.get_text(strip=True)
        elif len(cells) > 1:
            date = cells[1].get_text(strip=True)
        else:
            date = ""

        location = cells[-1].get_text(strip=True)

        events.append(
            {
                "event_name": name,
                "event_date": date,
                "event_location": location,
                "event_url": url,
            }
        )

    print(f"  Found {len(events)} completed events.")
    return events


# ── 2. Fights per event ───────────────────────────────────────────────────────
def scrape_event_fights(event_url: str) -> list[dict]:
    """
    Scrape the fight card from a single event page.

    Each fight row in the event table has a ``data-link`` attribute pointing
    to the fight detail page.  Columns (0-indexed):

        0 : result / bonus icons
        1 : fighters  (two <p> or <a> tags: red on top, blue on bottom)
        2 : KD
        3 : Sig. Str.
        4 : Sig. Str. %
        5 : Tot. Str.
        6 : Td
        7 : Td %
        8 : Sub. Att
        9 : Pass
        10: Rev.

    Returns a list of dicts with fight_url, fighter names/urls, weight class,
    method, finish round, and finish time.
    """
    soup = _get_soup(event_url)

    # Event-level info (weight class per fight is on the fight detail page)
    fights = []
    for row in soup.select("tr.b-fight-details__table-row[data-link]"):
        fight_url = row.get("data-link", "").strip()
        if not fight_url:
            continue

        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        # Fighter names and links (cell 1 contains both fighters)
        fighter_links = cells[1].find_all("a") if len(cells) > 1 else []
        r_name = fighter_links[0].get_text(strip=True) if len(fighter_links) > 0 else ""
        b_name = fighter_links[1].get_text(strip=True) if len(fighter_links) > 1 else ""
        r_fighter_url = fighter_links[0]["href"] if len(fighter_links) > 0 else ""
        b_fighter_url = fighter_links[1]["href"] if len(fighter_links) > 1 else ""

        fights.append(
            {
                "fight_url": fight_url,
                "r_fighter": r_name,
                "b_fighter": b_name,
                "r_fighter_url": r_fighter_url,
                "b_fighter_url": b_fighter_url,
            }
        )

    return fights


# ── 3. Fight details ─────────────────────────────────────────────────────────
def scrape_fight_details(fight_url: str) -> dict:
    """
    Scrape a fight detail page for result and totals stats.

    Totals table columns (cell indices, 0 = fighter names):
        1 : KD
        2 : Sig. Str.   (landed of attempted)
        3 : Sig. Str. %
        4 : Tot. Str.   (landed of attempted)
        5 : Td          (landed of attempted)
        6 : Td %
        7 : Sub. Att
        8 : Rev.
        9 : Ctrl        (mm:ss)

    Each data cell contains two <p> tags – top = red corner, bottom = blue corner.
    """
    soup = _get_soup(fight_url)
    data: dict = {"fight_url": fight_url}

    # ── Winner ──────────────────────────────────────────────────────────────
    for person in soup.select("div.b-fight-details__person"):
        status = person.find("i", class_="b-fight-details__person-status")
        if status and status.get_text(strip=True).upper() == "W":
            name_tag = person.find("h3", class_="b-fight-details__person-name")
            if name_tag:
                link = name_tag.find("a")
                data["winner_name"] = (link or name_tag).get_text(strip=True)

    # ── Fight metadata ───────────────────────────────────────────────────────
    for item in soup.select(
        "p.b-fight-details__text-item, i.b-fight-details__text-item"
    ):
        text = item.get_text(" ", strip=True)
        if text.startswith("Method:"):
            data["method"] = text.replace("Method:", "").strip()
        elif text.startswith("Round:"):
            data["finish_round"] = _parse_int(text.replace("Round:", "").strip())
        elif text.startswith("Time:"):
            data["finish_time"] = text.replace("Time:", "").strip()
        elif text.startswith("Time format:"):
            fmt = text.replace("Time format:", "").strip()
            data["time_format"] = fmt
            m = re.match(r"(\d+)\s+Rnd", fmt)
            data["total_rounds"] = int(m.group(1)) if m else None
        elif text.startswith("Referee:"):
            data["referee"] = text.replace("Referee:", "").strip()

    # ── Title bout ───────────────────────────────────────────────────────────
    fight_type_tag = soup.find("i", class_="b-fight-details__fight-title")
    fight_type_text = (
        fight_type_tag.get_text(strip=True).lower() if fight_type_tag else ""
    )
    data["is_title_bout"] = int("title bout" in fight_type_text)

    # Weight class: e.g. "Lightweight Bout" → "Lightweight"
    if fight_type_tag:
        wc = re.sub(r"\s+bout$", "", fight_type_text, flags=re.IGNORECASE).strip()
        data["weight_class"] = wc.title()

    # ── Totals table ─────────────────────────────────────────────────────────
    tables = soup.select("table.b-fight-details__table")
    if not tables:
        return data

    totals_table = tables[0]
    data_rows = totals_table.select("tbody tr")
    if not data_rows:
        return data

    # First data row = cumulative totals for the whole fight
    cells = data_rows[0].find_all("td")

    def two_vals(cell) -> tuple[str, str]:
        """Return (red_value, blue_value) from a cell with two <p> tags."""
        ps = cell.find_all("p")
        return (
            ps[0].get_text(strip=True) if len(ps) > 0 else "",
            ps[1].get_text(strip=True) if len(ps) > 1 else "",
        )

    if len(cells) >= 10:
        # Cell 0 holds fighter names; first <p> = red corner, second = blue corner.
        # This is the authoritative source for corner assignment – the event-page
        # listing always puts the winner first, which would bias win_red to 1.
        name_ps = cells[0].find_all("p")
        if len(name_ps) >= 2:
            r_link = name_ps[0].find("a")
            b_link = name_ps[1].find("a")
            if r_link:
                data["r_fighter"] = r_link.get_text(strip=True)
                data["r_fighter_url"] = r_link.get("href", "")
            if b_link:
                data["b_fighter"] = b_link.get_text(strip=True)
                data["b_fighter_url"] = b_link.get("href", "")

        r_kd, b_kd = two_vals(cells[1])
        data["r_kd"] = _parse_int(r_kd)
        data["b_kd"] = _parse_int(b_kd)

        r_sig, b_sig = two_vals(cells[2])
        data["r_sig_str"], data["r_sig_str_att"] = _parse_of(r_sig)
        data["b_sig_str"], data["b_sig_str_att"] = _parse_of(b_sig)

        r_sig_pct, b_sig_pct = two_vals(cells[3])
        data["r_sig_str_pct"] = _parse_pct(r_sig_pct)
        data["b_sig_str_pct"] = _parse_pct(b_sig_pct)

        r_str, b_str = two_vals(cells[4])
        data["r_str"], data["r_str_att"] = _parse_of(r_str)
        data["b_str"], data["b_str_att"] = _parse_of(b_str)

        r_td, b_td = two_vals(cells[5])
        data["r_td"], data["r_td_att"] = _parse_of(r_td)
        data["b_td"], data["b_td_att"] = _parse_of(b_td)

        r_td_pct, b_td_pct = two_vals(cells[6])
        data["r_td_pct"] = _parse_pct(r_td_pct)
        data["b_td_pct"] = _parse_pct(b_td_pct)

        r_sub, b_sub = two_vals(cells[7])
        data["r_sub_att"] = _parse_int(r_sub)
        data["b_sub_att"] = _parse_int(b_sub)

        r_rev, b_rev = two_vals(cells[8])
        data["r_rev"] = _parse_int(r_rev)
        data["b_rev"] = _parse_int(b_rev)

        r_ctrl, b_ctrl = two_vals(cells[9])
        data["r_ctrl_sec"] = _parse_ctrl(r_ctrl)
        data["b_ctrl_sec"] = _parse_ctrl(b_ctrl)

    return data


# ── 4. Fighter career stats ──────────────────────────────────────────────────
def scrape_fighter(fighter_url: str) -> dict:
    """
    Scrape a fighter's profile page for career stats and physical attributes.

    Physical attributes:  height_in, weight_lbs, reach_in, stance, dob
    Career stats:         slpm, str_acc, sapm, str_def,
                          td_avg, td_acc, td_def, sub_avg
    Record:               wins, losses, draws

    Note: these are *career-to-date* stats at time of scraping, not pre-fight
    stats.  For a proper historical ML pipeline you would need per-fight
    cumulative stats, but these career averages are a useful baseline.
    """
    soup = _get_soup(fighter_url)
    data: dict = {"fighter_url": fighter_url}

    # Name
    name_tag = soup.find("span", class_="b-content__title-highlight")
    data["name"] = name_tag.get_text(strip=True) if name_tag else ""

    # Record  "Record: 25-3-0 (1 NC)"
    record_tag = soup.find("span", class_="b-content__title-record")
    if record_tag:
        record_text = record_tag.get_text(strip=True)
        record_text = re.sub(r"Record:\s*", "", record_text)
        record_text = re.sub(r"\(.*\)", "", record_text).strip()  # drop NC note
        parts = record_text.split("-")
        data["wins"] = int(parts[0]) if len(parts) > 0 and parts[0].isdigit() else None
        data["losses"] = (
            int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        )
        data["draws"] = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None

    # Physical attributes and career stats (all in <li class="b-list__box-list-item"> elements)
    for li in soup.select("li.b-list__box-list-item"):
        label_tag = li.find("i", class_="b-list__box-item-title")
        if not label_tag:
            continue

        label = label_tag.get_text(strip=True).rstrip(":").strip()
        # Value is the text remaining after the label tag
        label_tag.extract()
        value = li.get_text(strip=True)

        if label == "Height":
            data["height_in"] = _parse_height(value)
        elif label == "Weight":
            data["weight_lbs"] = _parse_weight(value)
        elif label == "Reach":
            data["reach_in"] = _parse_reach(value)
        elif label == "STANCE":
            data["stance"] = value
        elif label == "DOB":
            data["dob"] = value
        elif label == "SLpM":
            try:
                data["slpm"] = float(value)
            except ValueError:
                pass
        elif label == "Str. Acc.":
            data["str_acc"] = _parse_pct(value)
        elif label == "SApM":
            try:
                data["sapm"] = float(value)
            except ValueError:
                pass
        elif label == "Str. Def":
            data["str_def"] = _parse_pct(value)
        elif label == "TD Avg.":
            try:
                data["td_avg"] = float(value)
            except ValueError:
                pass
        elif label == "TD Acc.":
            data["td_acc"] = _parse_pct(value)
        elif label == "TD Def.":
            data["td_def"] = _parse_pct(value)
        elif label == "Sub. Avg.":
            try:
                data["sub_avg"] = float(value)
            except ValueError:
                pass

    return data


# ── 5. Resolve winner to red/blue ────────────────────────────────────────────
def _resolve_winner(winner_name: str, r_fighter: str, b_fighter: str) -> Optional[int]:
    """
    Return 1 if red corner wins, 0 if blue corner wins, None if ambiguous.
    Uses substring matching to handle name formatting differences.
    """
    if not winner_name:
        return None
    wn = winner_name.lower()
    if wn in r_fighter.lower() or r_fighter.lower() in wn:
        return 1
    if wn in b_fighter.lower() or b_fighter.lower() in wn:
        return 0
    return None


# ── 6. Full pipeline ─────────────────────────────────────────────────────────
def scrape_all(max_events: Optional[int] = None) -> pd.DataFrame:
    """
    Orchestrate the full scrape: events → fights → fight details + fighter stats.

    Args:
        max_events: cap the number of events processed (None = all).

    Returns:
        Raw DataFrame with one row per fight.
    """
    print("Step 1/3  Scraping event list...")
    events = scrape_event_urls()
    if max_events:
        events = events[:max_events]
        print(f"  (capped at {max_events} events for this run)")

    all_rows: list[dict] = []
    n = len(events)

    # Cache fighter pages so each fighter is only fetched once per run
    fighter_cache: dict[str, dict] = {}

    for i, event in enumerate(events):
        print(
            f"\nStep 2/3  [{i + 1}/{n}] {event['event_name']}  ({event['event_date']})"
        )

        try:
            fights = scrape_event_fights(event["event_url"])
        except Exception as exc:
            print(f"  SKIP – error scraping event: {exc}")
            continue

        print(f"  {len(fights)} fights found")

        for fight in fights:
            row: dict = {**event, **fight}

            # Fight-level totals + outcome
            try:
                fight_data = scrape_fight_details(fight["fight_url"])
                row.update(fight_data)
            except Exception as exc:
                print(f"  WARN – fight detail error ({fight['fight_url']}): {exc}")

            # Red fighter stats (cached).
            # Use row's r_fighter_url – fight_data may have corrected the corner
            # assignment, overriding whatever the event page listed.
            r_url = row.get("r_fighter_url", "")
            if r_url:
                if r_url not in fighter_cache:
                    try:
                        fighter_cache[r_url] = scrape_fighter(r_url)
                    except Exception as exc:
                        print(f"  WARN – red fighter error: {exc}")
                        fighter_cache[r_url] = {}
                r_stats = fighter_cache[r_url]
                row.update(
                    {f"r_{k}": v for k, v in r_stats.items() if k != "fighter_url"}
                )

            # Blue fighter stats (cached).
            b_url = row.get("b_fighter_url", "")
            if b_url:
                if b_url not in fighter_cache:
                    try:
                        fighter_cache[b_url] = scrape_fighter(b_url)
                    except Exception as exc:
                        print(f"  WARN – blue fighter error: {exc}")
                        fighter_cache[b_url] = {}
                b_stats = fighter_cache[b_url]
                row.update(
                    {f"b_{k}": v for k, v in b_stats.items() if k != "fighter_url"}
                )

            # Determine win_red label
            row["win_red"] = _resolve_winner(
                row.get("winner_name", ""),
                row.get("r_fighter", ""),
                row.get("b_fighter", ""),
            )

            all_rows.append(row)

    df = pd.DataFrame(all_rows)
    print(f"\nStep 3/3  Done.  Total fights scraped: {len(df)}")
    return df


def save(df: pd.DataFrame, path: Path = OUTPUT_PATH) -> None:
    """Save the raw DataFrame to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    print(f"Saved → {path}  ({len(df)} rows, {len(df.columns)} columns)")


# ── CLI entry point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape ufcstats.com fight data")
    parser.add_argument(
        "--max-events",
        type=int,
        default=None,
        metavar="N",
        help="Limit scrape to the N most recent events (default: all)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        metavar="PATH",
        help=f"Output CSV path (default: {OUTPUT_PATH})",
    )
    args = parser.parse_args()

    df = scrape_all(max_events=args.max_events)
    save(df, path=args.output)
    print(df.head())
