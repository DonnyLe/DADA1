"""Trip planner: Tools

Two rules, the same ones from the Husky Tech agent:
  1. Return a readable string. Never raise, never return a bare dict.
  2. When you have nothing useful, SAY SO in the return value. "No results —
     try a nearby larger city" is a sentence the model can act on.
"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

import requests
from langchain.tools import tool
from langchain_tavily import TavilySearch

# Use these URLs for their corresponding tools
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
EVENTS_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
ATTRACTIONS_URL = "https://app.ticketmaster.com/discovery/v2/attractions.json"

FORECAST_DAYS = 16          # all Open-Meteo will forecast: today + 15
MAX_RESULTS = 3

# Open-Meteo returns a WMO code, not words. Only the common ones are listed;
# anything else falls through to "code N", which will keep the agent honest.
WEATHER_CODES = {
    0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
    66: "freezing rain", 67: "freezing rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 77: "snow grains", 80: "rain showers", 81: "rain showers",
    82: "violent rain showers", 85: "snow showers", 86: "snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail",
}


def _search(query: str) -> str:
    """Run one web search and format the hits. Shared by the four find_* tools."""
    try:
        results = TavilySearch(max_results=MAX_RESULTS).invoke({"query": query})
    except Exception as e:
        return f"The search failed ({e}). Tell the user you could not look this up."

    hits = results.get("results", []) if isinstance(results, dict) else []
    if not hits:
        return (f"No results for '{query}'. Try a nearby larger city, or tell the "
                f"user you could not find anything — do not fill the gap from memory.")

    lines = []
    for i, h in enumerate(hits, 1):
        snippet = " ".join((h.get("content") or "").split())[:300]
        lines.append(f"{i}. {h.get('title', 'untitled')}\n   {h.get('url', '')}\n   {snippet}")
    return "\n".join(lines) + (
        "\nThese snippets are the only evidence you have. They do not include "
        "opening hours, and a price counts only if it is written above.")


def _geocode(city: str) -> tuple[str, float, float, str]:
    """City name -> (label, latitude, longitude, ambiguity_note). Written for you.

    Raises ValueError if nothing matches. The ambiguity note is the interesting
    part: this API ranks by population, so "Cambridge" puts England ahead of
    Massachusetts and "Portland" puts Oregon ahead of Maine.
    """
    r = requests.get(GEOCODE_URL, params={"name": city.strip(), "count": 5,
                                          "language": "en", "format": "json"},
                     timeout=15)
    r.raise_for_status()
    results = (r.json() or {}).get("results") or []
    if not results:
        raise ValueError(f"No place matches '{city}'.")

    def describe(r):
        return ", ".join(x for x in (r["name"], r.get("admin1"), r.get("country")) if x)

    top = results[0]
    label = describe(top)

    # Every US city shares its name with a hamlet somewhere; "Boston, Georgia (pop. 1,400)"
    # is noise, and an agent that hedges on every city stops being useful.
    top_pop = top.get("population") or 0
    rivals = [describe(o) for o in results[1:4]
              if o["name"].lower() == top["name"].lower()
              and (o.get("population") or 0) >= 0.10 * top_pop]
    note = (f" NOTE: '{city}' is ambiguous — could also be {'; '.join(rivals)}. "
            f"Confirm which one before planning." if rivals else "")
    return label, top["latitude"], top["longitude"], note

# taken from W02b, to check if date is out of bounds
def _days_until(target_date: str) -> int:
    """Days from today until target_date (YYYY-MM-DD)
    """
    target = datetime.strptime(target_date, "%Y-%m-%d").date()
    return (target - datetime.now().date()).days


# NOTE: The tools already have some docstring descriptions
# but you can modify them if you find the descriptions insufficient or inaccurate.
@tool
def get_weather(city: str, date: str = "") -> str:
    """Get the weather forecast for a city on a date (YYYY-MM-DD).

    Only the next 16 days can be forecast. For any date beyond that the forecast
    does not exist, and this tool will say so.  Say that plainly instead of
    describing what the season is usually like. Leave date empty for today.

    The city name is resolved to a real place, and this tool tells you WHICH
    place it picked. If other places share the name, it says so: check it matches
    what the user meant before you plan anything.
    """
    # TODO: implement. Return a readable string
    label: str
    lat: float
    lon: float
    note: str
    try:
        label, lat, lon, note = _geocode(city)
    except ValueError as e:
        return f"{e}. No geocoding city matches, ensure the city name is correct or try a nearby larger city."
    if date == '':
        date = datetime.now().strftime("%Y-%m-%d")

    days_out = _days_until(date)

    if days_out < 0:
        return f"{date} is in the past. I can only forecast from today onward.{note}"

    if days_out >= FORECAST_DAYS:
        last_day: str = (datetime.now().date() + timedelta(days=FORECAST_DAYS - 1)).isoformat()
        return (f"No forecast for {date} in {label}. Only today through {last_day} "
                f"({FORECAST_DAYS} days out) are available.{note}")

    try:
        r = requests.get(FORECAST_URL, params={
            "latitude": lat,
            "longitude": lon,
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max",
            "timezone": "auto",
            "forecast_days": FORECAST_DAYS,
        }, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        return f"Forecast lookup failed ({e}). Tell the user you could not check the weather."

    daily: dict[str, Any] = r.json().get("daily", {})
    dates: list[str] = daily.get("time", [])
    if date not in dates:
        window: str
        if dates:
            window = f"{dates[0]} to {dates[-1]}"
        else:
            window = "no dates available"
        return (f"No forecast for {date} in {label}. Only {window} "
                f"are available.{note}")

    date_index = dates.index(date)
    code = daily.get("weather_code", [None])[date_index]
    desc = WEATHER_CODES.get(code, f"code {code}")
    temp_high = daily.get("temperature_2m_max", [None])[date_index]
    temp_low = daily.get("temperature_2m_min", [None])[date_index]
    rain_values: list[int] | None = daily.get("precipitation_probability_max")
    rain_chance_percent: int | None
    if rain_values:
        rain_chance_percent = rain_values[date_index]
    else:
        rain_chance_percent = None
    rain_description: str
    if rain_chance_percent is not None:
        rain_description = f", {rain_chance_percent}% chance of precipitation"
    else:
        rain_description = ""
    return (f"Forecast for {label} on {date}: {desc}, high {temp_high}°C / low {temp_low}°C"
            f"{rain_description}.{note} This is the forecast data itself and has no "
            f"source link, so do not attach a URL to it.")


@tool
def find_attractions(city: str, interest: str = "") -> str:
    """Find sights, museums, parks and landmarks in a city.

    interest narrows it, e.g. "art", "history", "outdoors", "free".
    Use this for things to SEE. For food use find_restaurants; for things
    happening on a particular date use find_events.
    """
    # TODO: implement. Return a readable string
    query: str = f"best things to see and do in {city}"
    if interest:
        query += f" for {interest}"
    query += " attractions sights"
    return _search(query)


@tool
def find_restaurants(city: str, budget: str = "") -> str:
    """Find places to eat in a city.

    budget narrows it, e.g. "cheap", "mid-range", "fine dining".
    Use this for food and drink only. It does not return opening hours or
    current prices, so do not promise either.
    """
    # TODO: implement. Return a readable string; never raise.
    query: str = f"best restaurants to eat in {city}"
    if budget:
        query += f" {budget}"
    return _search(query)


def _ticketmaster_events(params: dict[str, Any]) -> list[dict[str, Any]]:
    r = requests.get(EVENTS_URL, params=params, timeout=15)
    r.raise_for_status()
    embedded: dict[str, Any] = r.json().get("_embedded", {})
    return embedded.get("events", [])


# extracted out this out so both find_performer_events and find_events can use this 
def format_events_helper(events: list[dict[str, Any]]) -> str:
    print_lines: list[str] = []
    unpriced: int = 0
    for event in events[:10]:
        event_name: str = event.get("name", "untitled event")
        event_start_date: dict[str, Any] = event.get("dates", {}).get("start", {})
        event_date_string: str = event_start_date.get("localDate", "date unknown")
        event_local_time_string: str = event_start_date.get("localTime", "")
        venues: list[dict[str, Any]] = event.get("_embedded", {}).get("venues", [])
        venue: str
        if venues:
            venue = venues[0].get("name", "venue unknown")
        else:
            venue = "venue unknown"
        url: str = event.get("url", "")

        price_ranges: list[dict[str, Any]] | None = event.get("priceRanges")
        if price_ranges:
            # ignore the other price ranges, prices_ranges[0] is standard prices
            standard_price_range: dict[str, Any] = price_ranges[0]
            low_price: float | None = standard_price_range.get("min")
            high_price: float | None = standard_price_range.get("max")
            if low_price == 0 and high_price == 0:
                price: str = "price listed as $0.00-$0.00 (a seller placeholder, not free admission)"
            else:
                price: str = f"${low_price}-${high_price} {standard_price_range.get('currency', '')}"
        else:
            price: str = "price not published"
            unpriced += 1

        print_lines.append(f"- {event_name}: {event_date_string} {event_local_time_string} at {venue}. {price}. {url}")

    event_count: int = min(len(events), 10)
    note: str
    if event_count:
        note = (f"\n({unpriced} of {event_count} shown have no published price; that is "
                f"normal for this API, not a gap in the search.)")
    else:
        note = ""
    return "\n".join(print_lines) + note


@tool
def find_events(city: str, date: str = "", category: str = "") -> str:
    """Find real ticketed events in a city: concerts, sport, theatre, festivals.

    date is YYYY-MM-DD and means that day in the venue's own local time; leave
    it empty for the week ahead. Unlike the search tools this returns structured
    records: real dates, real venues, real links.

    category narrows by type. The five broad ones always work: "music", "sports",
    "arts & theatre", "film", "miscellaneous". Many narrower ones work too —
    "comedy", "rock", "jazz", "classical", "hip-hop", "country", "pop",
    "basketball", "hockey", "theatre", "musical", "dance", "family". Leave it
    empty for everything.

    But some plausible-sounding words match nothing at all ("opera", "magic"),
    and a category the API does not recognise returns ZERO EVENTS rather than an
    error — identical to a genuinely quiet weekend. Prefer a word from the list
    above, and never report "there is nothing on" from an empty filtered result
    without checking again without the filter.

    MOST EVENTS COME BACK WITH NO PRICE. The API documents a price field and
    fills it in for only a small fraction of events, under 10% in every city
    tested. "price not published" means exactly that. Do not substitute a guess,
    and do not read a missing price as free admission. A price published as 0 is
    a placeholder, not a free ticket.

    This only covers events sold through Ticketmaster. A quiet result does not
    mean nothing is happening. Say that rather than implying the city is empty.
    """
    # TODO: implement. Return a readable string.
    api_key: str | None = os.getenv("TICKETMASTER_API_KEY")
    if not api_key:
        return "Event lookup is unavailable: no TICKETMASTER_API_KEY is configured."

    start_date: str
    end_date: str
    # clean whitespace just in case
    if date.strip():
        start_date = date.strip()
        end_date = date.strip()
    else:
        # if date is empty, choose the current day as the starting point 
        # NOTE: I decided to also make the end date 7 days after the start date in this case 
        today = datetime.now().date()
        start_date = today.isoformat()
        end_date = (today + timedelta(days=7)).isoformat()

    base_params: dict[str, Any] = {
        "apikey": api_key,
        "city": city,
        # localStartDateTime is an array query parameter; the format is [start, end] as one comma-joined string
        "localStartDateTime": ",".join([f"{start_date}T00:00:00", f"{end_date}T23:59:59"]),
        "size": 50,
        "sort": "date,asc",
    }

    try:
        params: dict[str, Any] = dict(base_params)
        # clean just in case 
        if category.strip():
            params["classificationName"] = category.strip()
        events: list[dict[str, Any]] = _ticketmaster_events(params)
    except requests.RequestException as e:
        return f"Event lookup failed ({e}). Tell the user you could not check events."

    if not events and category.strip():
        try:
            unfiltered: list[dict[str, Any]] = _ticketmaster_events(dict(base_params))
        except requests.RequestException:
            unfiltered = []
        if unfiltered:
            return (f"No events matched category '{category}' in {city} for this window, but {len(unfiltered)} other ticketed events were found. "
                    f"'{category}' may not be a category this API recognizes. An unrecognized category returns zero results, not an error. Try "
                    f"again without a category filter, or use one of: music, sports, arts & theatre, film, miscellaneous.")
        return (f"No ticketed events found in {city} for this window, with or without the '{category}' filter." 
                f"This only covers events sold through Ticketmaster. A quiet result does not mean nothing is "
                f"happening in the city.")

    if not events:
        return (f"No ticketed events found in {city} for this window. This only "
                f"covers events sold through Ticketmaster. A quiet result does not "
                f"mean nothing is happening in the city.")

    return format_events_helper(events)


@tool
def get_transit_info(city: str) -> str:
    """Get general information about getting around a city: metro, bus, passes, fares.

    This returns written guidance, NOT timetables and NOT journey times. If the
    user asks how many minutes a specific trip takes, say you cannot look that
    up rather than estimating it.
    """
    # TODO: implement. Return a readable string
    query: str = f"how to get around {city} public transportation metro bus fares day passes"
    return _search(query)



# NOTE: I added this extra current date function to help the agent when 
# the prompt includes "weekend" or "next week". This is mainly for case 8a. 
# I'm not sure if this is required. 
@tool
def get_current_date() -> str:
    """Get today's date and day of the week.

    Call this whenever the user says "today", "tonight", "tomorrow", "this
    weekend" or "next Friday", so you know which calendar date they mean. Then  pass real YYYY-MM-DD dates to the other tools.
    Times are US Eastern.
    """
    now = datetime.now(ZoneInfo("America/New_York"))
    return f"Today is {now.strftime('%A')} {now.date().isoformat()}."


@tool
def find_performer_events(performer: str, city: str, date: str = "") -> str:
    """Find when and where a specific performer, team, or touring show plays in a city.

    performer should be an act, not a place: a band, a sports team, or a touring
    show, like "Boston Celtics" and "Taylor Swift". This does two Ticketmaster lookups behind the scenes. First it 
    searches for the performer to get their id, then it searches for events tied to that id in the given
    city. That makes it more reliable than find_events when someone asks whether
    a specific act is playing while they're in town.

    date is YYYY-MM-DD in the venue's local time. Leave it empty to check any upcoming date. If the name 
    matches more than one real act, say so instead of guessing which one was meant. "Boston" 
    could mean the Celtics, the Bruins, or a band called Boston Manor. If the performer is real but just isn't playing
    in that city, say that plainly. 

    WARNING: Ticketmaster calls performers, teams, and touring shows "attractions," which is confusing. Searching this for "museum" turns up
    things like touring exhibitions, not the actual Museum of Fine Arts. Use find_attractions for real tourist sights, not this tool.
    """
    api_key: str | None = os.getenv("TICKETMASTER_API_KEY")
    if not api_key:
        return "Performer lookup is unavailable: no TICKETMASTER_API_KEY is configured."

    try:
        r = requests.get(ATTRACTIONS_URL, params={
            "apikey": api_key, "keyword": performer, "size": 10,
        }, timeout=15)
        r.raise_for_status()
    except requests.RequestException as e:
        return f"Performer lookup failed ({e}). Tell the user you could not check this."

    embedded: dict[str, Any] = r.json().get("_embedded", {})
    attractions: list[dict[str, Any]] = embedded.get("attractions", [])
    if not attractions:
        return (f"No performer, team, or touring show matching '{performer}' was found on Ticketmaster."
                f"Do not guess. Tell the user it could not be found there.")

    exact: list[dict[str, Any]] = []
    for attraction_match in attractions:
        if attraction_match.get("name", "").lower() == performer.strip().lower():
            exact.append(attraction_match)

    candidates: list[dict[str, Any]]
    if len(exact) == 1:
        candidates = exact
    else:
        candidates = attractions
    # handle ambiguous results where multiple acts are matched
    if len(candidates) > 1:
        candidate_names: list[str] = []
        for candidate in candidates[:6]:
            candidate_names.append(candidate.get("name", "?"))
        names: str = ", ".join(candidate_names)
        return (f"'{performer}' is ambiguous on Ticketmaster. It matches several "
                f"acts: {names}. Ask the user which one they meant before searching "
                f"for events.")

    attraction: dict[str, Any] = candidates[0]
    attraction_id: str | None = attraction.get("id")
    resolved_name: str = attraction.get("name", performer)

    start_date: str
    end_date: str
    if date.strip():
        start_date = date.strip()
        end_date = date.strip()
    else:
        today = datetime.now().date()
        start_date = today.isoformat()
        end_date = (today + timedelta(days=180)).isoformat()

    try:
        events: list[dict[str, Any]] = _ticketmaster_events({
            "apikey": api_key,
            "attractionId": attraction_id,
            "city": city,
            # array parameter: [start, end] as one comma-joined value
            "localStartDateTime": ",".join([f"{start_date}T00:00:00", f"{end_date}T23:59:59"]),
            "size": 20,
            "sort": "date,asc",
        })
    except requests.RequestException as e:
        return f"Event lookup failed ({e}). Tell the user you could not check this."

    if not events:
        return (f"{resolved_name} is a real, findable act on Ticketmaster, but has no events listed in {city} for this window."
                f"That is a real answer. Do not imply the act never performs or tours.")

    return format_events_helper(events)


TOOLS = [get_weather, find_attractions, find_restaurants, find_events,
         get_transit_info, find_performer_events, get_current_date]
