#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from colorama import Fore, Style, init
from datetime import datetime, timedelta, time
from dotenv import load_dotenv
from time import sleep
import argparse, re, sys
import os
import requests

init(autoreset=True)

# ──────────────────────────────
#  Amadeus credentials
# ──────────────────────────────
load_dotenv()  # loads from .env by default
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")


# ═══════════════════════════════════════════════════════════════════════════════
#  Helper utilities
# ═══════════════════════════════════════════════════════════════════════════════
def get_access_token() -> str:
    resp = requests.post(
        "https://test.api.amadeus.com/v1/security/oauth2/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type":    "client_credentials",
            "client_id":     API_KEY,
            "client_secret": API_SECRET,
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def iso_duration_to_hm(duration: str) -> tuple[int, int]:
    """Return (hours, minutes) from ISO‑8601 PTxdyyM string."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", duration)
    h = int(m.group(1) or 0)
    mi = int(m.group(2) or 0)
    return h, mi


def hm_to_hours(hours: int, minutes: int) -> float:
    return hours + minutes / 60


def parse_day_time_filters(tokens: list[str]) -> dict[str, tuple[time | None, time | None]]:
    """
    Transform tokens like 'Thu(00:00-12:00)' or 'Sat' into a mapping:
    { 'thu': (start_time|None, end_time|None) }
    """
    filters: dict[str, tuple[time | None, time | None]] = {}
    for t in tokens:
        t = t.strip()
        if "(" in t and ")" in t:
            day, rng = t.split("(", 1)
            rng = rng.rstrip(")")
            try:
                start_s, end_s = rng.split("-")
                start_t = datetime.strptime(start_s, "%H:%M").time()
                end_t   = datetime.strptime(end_s,   "%H:%M").time()
            except ValueError:
                sys.exit(f"‼️  Bad time range in '{t}'. Expected HH:MM-HH:MM.")
        else:
            day, start_t, end_t = t, None, None
        filters[day.lower()[:3]] = (start_t, end_t)
    return filters


def time_in_window(t: time, start: time | None, end: time | None) -> bool:
    if start is None or end is None:
        return True
    if start <= end:
        return start <= t <= end
    # over‑midnight window
    return t >= start or t <= end


def day_period(hour: int) -> str:
    """Return 'day' (06‑22) or 'night'."""
    return "day" if 6 <= hour < 22 else "night"


def sort_offers(offers, sort_keys):
    def key_fn(offer):
        itin  = offer["itineraries"][0]
        segs  = itin["segments"]
        dep   = segs[0]["departure"]["at"]
        ret   = offer["itineraries"][-1]["segments"][-1]["arrival"]["at"]
        price = float(offer["price"]["total"])
        h, m  = iso_duration_to_hm(itin["duration"])
        dur   = hm_to_hours(h, m)
        mapping = {
            "price": price,
            "departure_date": datetime.fromisoformat(dep),
            "duration": dur,
            "return_date": datetime.fromisoformat(ret),
        }
        return tuple(mapping[k] for k in sort_keys)
    return sorted(offers, key=key_fn)


def hours_between(dt1: str, dt2: str) -> float:
    t1 = datetime.fromisoformat(dt1)
    t2 = datetime.fromisoformat(dt2)
    return abs((t2 - t1).total_seconds() / 3600)


# ═══════════════════════════════════════════════════════════════════════════════
#  Arg‑parser section
# ═══════════════════════════════════════════════════════════════════════════════
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter,
        description="""🔍  Flexible Flight‑Search CLI (Amadeus Self‑Service)

Supports:
  • Fixed and flexible departure/return dates
  • Rolling windows (“2 weeks”, “1 week 3 days”)
  • Day/time specific filters (Thu(00:00‑12:00))
  • Separate stop‑over limits for outbound / inbound legs
  • Multi‑criteria sorting

EXAMPLES
────────

1️⃣  🔒 Fixed departure & return, nonstop flights only
    python flight_search.py --from LHR --to EVN \
      --depart 2025-07-01 --return 2025-07-05 \
      --nonstop --sort-by price

2️⃣  📅 Flexible range with max stay nights
    python flight_search.py --from LHR LGW --to EVN \
      --depart-start 2025-07-01 --depart-end 2025-07-10 \
      --max-stay 3-4 --max-stops 1 --sort-by price duration

3️⃣  🌀 Rolling window with day/time filters
    python flight_search.py --from LON BHX --to EVN \
      --range-start 2025-05-29 --range-length "5 weeks" \
      --max-stay 3-4 \
      --filter-depart-days-time "Thu(00:00-23:59)" Fri "Sat(00:00-08:00)" \
      --filter-return-days-time Sat Sun Mon \
      --max-departure-stopover 10 7 \
      --max-return-stopover 8 6

4️⃣  📊 Sort by price, then departure date, then duration
    python flight_search.py --from STN --to TBS EVN \
      --depart 2025-06-12 --return 2025-06-16 \
      --sort-by price departure_date duration \
      --max-stay 3-5

5️⃣  🎯 All airports in London & Birmingham, smart filtering
    python flight_search.py \
      --from LHR LGW STN BHX EMA \
      --to EVN \
      --depart-start 2025-06-01 --depart-end 2025-06-30 \
      --max-stay 3-5 7 9-10 \
      --filter-depart-days-time Thu "Fri(00:00-14:00)" "Sat(00:00-09:00)" \
      --filter-return-days-time Mon(06:00-23:59) Tue Wed \
      --max-departure-stopover 10 6 --max-return-stopover 8 \
      --sort-by price duration departure_date return_date

6️⃣  🧪 Flexible weekend return + large stay range
    python flight_search.py --from LHR --to EVN \
      --depart-start 2025-07-10 --depart-end 2025-07-25 \
      --max-stay 4-8 12 14-16 \
      --filter-return-days-time Sat Sun Mon \
      --sort-by price

"""
    )
    # core
    p.add_argument("--from", dest="origins", nargs="+", required=True)
    p.add_argument("--to",   dest="destinations", nargs="+", required=True)

    # fixed vs flexible date controls
    p.add_argument("--depart", type=str)
    p.add_argument("--return", dest="ret", type=str)

    p.add_argument("--depart-start", type=str)
    p.add_argument("--depart-end",   type=str)
    p.add_argument("--return-start", type=str)
    p.add_argument("--return-end",   type=str)

    p.add_argument("--max-stay", type=str, nargs="+")
    p.add_argument("--range-length", type=str)
    p.add_argument("--range-start",  type=str)

    # day/time filters
    p.add_argument("--filter-depart-days-time", nargs="+",
                   help="e.g. \"Thu(00:00-12:00)\" Fri Sat")
    p.add_argument("--filter-return-days-time", nargs="+",
                   help="e.g. Sat \"Sun(10:00-23:59)\" Mon")

    # stopover limits
    p.add_argument("--max-departure-stopover", type=float, nargs="+",
                   help="One value ⇒ applies to day+night. Two ⇒ day night.")
    p.add_argument("--max-return-stopover", type=float, nargs="+",
                   help="Same semantics as above.")

    # misc filters
    p.add_argument("--nonstop", action="store_true")
    p.add_argument("--max-stops", type=int, default=1)
    p.add_argument("--max-results", type=int, default=5)
    p.add_argument("--one-way", action="store_true", help="Skip return flight filtering and print only one-way itineraries")
    p.add_argument("--allow-different-return-airport", action="store_true", help="Allow inbound to land at different airport")
    p.add_argument("--sort-by", nargs="+",
                   choices=["price", "duration", "departure_date", "return_date"],
                   help="Default: price departure_date duration return_date")
    return p


ARGS = build_parser().parse_args()
if not ARGS.sort_by:
    ARGS.sort_by = ["price", "departure_date", "duration", "return_date"]
ALL_MATCHES: list[dict] = []


# ═══════════════════════════════════════════════════════════════════════════════
#  Date‑pair generator
# ═══════════════════════════════════════════════════════════════════════════════
def expand_stay_durations(tokens: list[str | int]) -> list[int]:
    nights = set()
    for tok in tokens:
        s = str(tok)
        if "-" in s:
            try:
                start, end = map(int, s.split("-"))
                nights.update(range(start, end + 1))
            except ValueError:
                sys.exit(f"‼️ Invalid range format in --max-stay: {s}")
        else:
            try:
                nights.add(int(s))
            except ValueError:
                sys.exit(f"‼️ Invalid number in --max-stay: {s}")
    return sorted(nights)


def make_date_pairs() -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if ARGS.max_stay:
        ARGS.max_stay = expand_stay_durations(ARGS.max_stay)

    if ARGS.range_length and ARGS.max_stay:
        base = datetime.fromisoformat(ARGS.range_start).date() if ARGS.range_start else datetime.today().date()
        total_days = parse_range_length(ARGS.range_length)
        for offset in range(total_days):
            d_date = base + timedelta(days=offset)
            for stay in ARGS.max_stay:
                r_date = d_date + timedelta(days=stay)
                pairs.append((d_date.isoformat(), r_date.isoformat()))
    elif ARGS.depart_start and ARGS.depart_end and ARGS.max_stay:
        start = datetime.fromisoformat(ARGS.depart_start).date()
        end   = datetime.fromisoformat(ARGS.depart_end).date()
        while start <= end:
            for stay in ARGS.max_stay:
                ret = start + timedelta(days=stay)
                if ARGS.return_start and ret < datetime.fromisoformat(ARGS.return_start).date():
                    continue
                if ARGS.return_end and ret > datetime.fromisoformat(ARGS.return_end).date():
                    continue
                pairs.append((start.isoformat(), ret.isoformat()))
            start += timedelta(days=1)
    elif ARGS.depart and ARGS.ret:
        pairs.append((ARGS.depart, ARGS.ret))
    else:
        sys.exit("‼️  Provide either fixed dates or a flexible range.")
    return pairs


# ═══════════════════════════════════════════════════════════════════════════════
#  Day/time filter helpers
# ═══════════════════════════════════════════════════════════════════════════════
DEPART_DAY_FILTER = parse_day_time_filters(ARGS.filter_depart_days_time or [])
RETURN_DAY_FILTER = parse_day_time_filters(ARGS.filter_return_days_time or [])

def depart_ok(dep_iso: str) -> bool:
    if not DEPART_DAY_FILTER:
        return True
    dt = datetime.fromisoformat(dep_iso)
    key = dt.strftime("%a").lower()[:3]
    if key not in DEPART_DAY_FILTER:
        return False
    start, end = DEPART_DAY_FILTER[key]
    return time_in_window(dt.time(), start, end)

def return_ok(dep_iso: str) -> bool:
    if not RETURN_DAY_FILTER:
        return True
    dt = datetime.fromisoformat(dep_iso)
    key = dt.strftime("%a").lower()[:3]
    if key not in RETURN_DAY_FILTER:
        return False
    start, end = RETURN_DAY_FILTER[key]
    return time_in_window(dt.time(), start, end)

# stopover limits
def stop_limits(kind: str, hour: int) -> float:
    values = getattr(ARGS, f"max_{kind}_stopover") or []
    if not values:
        return float("inf")
    if len(values) == 1:
        return values[0]
    # 2 values: [day, night]
    return values[0] if day_period(hour) == "day" else values[1]


# ═══════════════════════════════════════════════════════════════════════════════
#  Flight search & printing
# ═══════════════════════════════════════════════════════════════════════════════
def run_search():
    token = get_access_token()
    date_pairs = make_date_pairs()

    for orig in ARGS.origins:
        for dest in ARGS.destinations:
            for d_date, r_date in date_pairs:
                # Check if departure/return pass the day-time filters before making request
                if not depart_ok(d_date + "T12:00:00"):
                    continue
                if not ARGS.one_way and not return_ok(r_date + "T12:00:00"):
                    continue

                print(f"{Fore.BLUE}Checking {orig} → {dest} | {d_date}" + (f" → {r_date}" if not ARGS.one_way else "") + f"...{Style.RESET_ALL}")
                offers = call_amadeus(token, orig, dest, d_date, r_date)
                if not offers:
                    continue

                sorted_offers = sort_offers(offers, ARGS.sort_by)
                best_offer = sorted_offers[0]
                display_offers([best_offer])   # 🟨 Show only best for this query

                ALL_MATCHES.extend(offers)

    # Final summary
    print(f"\n{Fore.YELLOW}🏁 Displaying top {ARGS.max_results} result(s)...\n")
    top = sort_offers(ALL_MATCHES, ARGS.sort_by)[:ARGS.max_results]
    display_offers(top)



def call_amadeus(token: str, origin: str, destination: str,
                 depart: str, ret: str) -> None:
    base_url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
    headers  = {"Authorization": f"Bearer {token}"}
    params   = {
        "originLocationCode":      origin,
        "destinationLocationCode": destination,
        "departureDate":           depart,
        # Optional returnDate
        **({"returnDate": ret} if ret else {}),
        "adults":                  1,
        "max":                     ARGS.max_results,
        "currencyCode":            "GBP",
        "nonStop":                 "true" if ARGS.nonstop else "false",
    }
    # Retry logic for rate limit
    for attempt in range(3):
        rsp = requests.get(base_url, headers=headers, params=params)
        if rsp.status_code != 429:
            break
        print("⚠️  Rate limit hit. Waiting 5 seconds before retrying...")
        sleep(7)
    else:
        print("❌ Amadeus still rate-limiting after retries. Skipping...")
        return

    if rsp.status_code != 200:
        print("Amadeus error:", rsp.json())
        return []

    offers = sort_offers(rsp.json()["data"], ARGS.sort_by)
    return offers


def display_offers(offers) -> None:
    seen: set[tuple] = set()
    for offer in offers:
        price = offer["price"]["total"]
        to_itin   = offer["itineraries"][0]      # outbound
        from_itin = offer["itineraries"][-1]     # inbound

        # --- Outbound checks ---------------------------------------------------
        dep_seg = to_itin["segments"][0]
        if not depart_ok(dep_seg["departure"]["at"]):
            continue

        # --- Inbound checks ----------------------------------------------------
        if not ARGS.one_way:
            # -- Return itinerary (pretty print)
            ret_segs = from_itin["segments"]
            ret_dep_seg = ret_segs[0]
            ret_arr_seg = ret_segs[-1]
            if not ARGS.allow_different_return_airport:
                to_arr = to_itin["segments"][-1]["arrival"]["iataCode"]
                from_arr = ret_arr_seg["arrival"]["iataCode"]
                if to_arr != from_arr:
                    continue
            ret_dep_time = datetime.fromisoformat(ret_dep_seg["departure"]["at"])
            ret_arr_time = datetime.fromisoformat(ret_arr_seg["arrival"]["at"])
            print(f"{Fore.BLUE}Return:")
            print(f"  From:  {ret_dep_seg['departure']['iataCode']}  {ret_dep_seg['departure']['at']} ({ret_dep_time.strftime('%A')})")
            print(f"  To:    {ret_arr_seg['arrival']['iataCode']}  {ret_arr_seg['arrival']['at']} ({ret_arr_time.strftime('%A')})")
            if len(ret_segs) > 1:
                for i in range(1, len(ret_segs)):
                    prev_arr  = datetime.fromisoformat(ret_segs[i - 1]["arrival"]["at"])
                    next_dep  = datetime.fromisoformat(ret_segs[i]["departure"]["at"])
                    stop_code = ret_segs[i]["departure"]["iataCode"]
                    wait_hr   = (next_dep - prev_arr).total_seconds() / 3600
                    wait_fmt  = f"{int(wait_hr)}h {int((wait_hr % 1) * 60)}m"
                    print(f"{Fore.LIGHTBLACK_EX}  ↪ Stopover at {stop_code} for {wait_fmt}")

        if not ARGS.one_way:
            ret_seg = from_itin["segments"][0]
            if not return_ok(ret_seg["departure"]["at"]):
            continue

        # --- Stop‑over filtering ----------------------------------------------
        if not stopovers_ok(to_itin, "departure") or not stopovers_ok(from_itin, "return"):
            continue

        ret_seg = from_itin["segments"][0] if not ARGS.one_way else None
        key = (dep_seg["departure"]["at"], ret_seg["departure"]["at"] if ret_seg else None, price)
        if key in seen:
            continue
        seen.add(key)

        # ---------- PRINT ------------------------------------------------------
        duration_h, duration_m = iso_duration_to_hm(to_itin["duration"])
        dep_dt = datetime.fromisoformat(dep_seg["departure"]["at"])
        arr_dt = datetime.fromisoformat(to_itin["segments"][-1]["arrival"]["at"])
        ret_dt = datetime.fromisoformat(ret_seg["departure"]["at"])
        num_stops = len(to_itin["segments"]) - 1
        print(f"{Fore.GREEN}£{price} | {duration_h}h{duration_m:02d}m | Stops {num_stops}")
        print(f"{Fore.YELLOW}From:  {dep_seg['departure']['iataCode']}  {dep_dt.isoformat()} ({dep_dt.strftime('%A')})")
        print(f"{Fore.CYAN}To:    {to_itin['segments'][-1]['arrival']['iataCode']}  {arr_dt.isoformat()} ({arr_dt.strftime('%A')})")
        if num_stops > 0:
            for i in range(1, len(to_itin["segments"])):
                prev_arr = datetime.fromisoformat(to_itin["segments"][i - 1]["arrival"]["at"])
                next_dep = datetime.fromisoformat(to_itin["segments"][i]["departure"]["at"])
                stop = to_itin["segments"][i]["departure"]["iataCode"]
                wait_hrs = (next_dep - prev_arr).total_seconds() / 3600
                wait_fmt = f"{int(wait_hrs)}h {int((wait_hrs % 1) * 60)}m"
                print(f"{Fore.LIGHTBLACK_EX}  ↪ Stopover at {stop} for {wait_fmt}")
        # -- Return itinerary (pretty print)
        ret_segs = from_itin["segments"]
        ret_dep_seg = ret_segs[0]
        ret_arr_seg = ret_segs[-1]
        ret_dep_time = datetime.fromisoformat(ret_dep_seg["departure"]["at"])
        ret_arr_time = datetime.fromisoformat(ret_arr_seg["arrival"]["at"])

        print(f"{Fore.BLUE}Return:")
        print(f"  From:  {ret_dep_seg['departure']['iataCode']}  {ret_dep_seg['departure']['at']} ({ret_dep_time.strftime('%A')})")
        print(f"  To:    {ret_arr_seg['arrival']['iataCode']}  {ret_arr_seg['arrival']['at']} ({ret_arr_time.strftime('%A')})")

        if len(ret_segs) > 1:
            for i in range(1, len(ret_segs)):
                prev_arr  = datetime.fromisoformat(ret_segs[i - 1]["arrival"]["at"])
                next_dep  = datetime.fromisoformat(ret_segs[i]["departure"]["at"])
                stop_code = ret_segs[i]["departure"]["iataCode"]
                wait_hr   = (next_dep - prev_arr).total_seconds() / 3600
                wait_fmt  = f"{int(wait_hr)}h {int((wait_hr % 1) * 60)}m"
                print(f"{Fore.LIGHTBLACK_EX}  ↪ Stopover at {stop_code} for {wait_fmt}")

        print(Style.RESET_ALL + "-"*60)


def stopovers_ok(itinerary: dict, kind: str) -> bool:
    max_day, max_night = stop_limits(f"{kind}", 12), stop_limits(f"{kind}", 0)  # just to get both
    segs = itinerary["segments"]
    for i in range(1, len(segs)):
        prev_arr  = datetime.fromisoformat(segs[i-1]["arrival"]["at"])
        next_dep  = datetime.fromisoformat(segs[i]["departure"]["at"])
        wait_hr   = hours_between(prev_arr.isoformat(), next_dep.isoformat())
        limit     = stop_limits(f"{kind}", prev_arr.hour)
        if wait_hr > limit or (ARGS.max_stops is not None and len(segs)-1 > ARGS.max_stops):
            return False
    return True


# ════════════════════
if __name__ == "__main__":
    run_search()
