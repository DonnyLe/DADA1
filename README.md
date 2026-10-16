
Deployed app: https://dada1-3370.onrender.com/

Trip Planner Agent

A conversational trip-planning agent running on Gemini Flash. Ask for something like "plan me a day in Boston tomorrow, free things and a cheap lunch" and it checks the weather, finds sights and food, and returns a plan with source URLs. Follow-ups such as "make it cheaper" or "add dinner" adjust the existing plan rather than starting over. A **Build itinerary from this conversation** button turns the chat into a structured `Itinerary` record (days, then activities).

The agent is built to be honest about gaps: no forecasts beyond 16 days, no opening hours, no journey times, and no invented prices. A missing price reads `"unknown"`, never free or zero.

## Architecture

```
trip_planner/
  agent/tools.py       tool definitions
  agent/prompts.py     system prompt
  agent/itinerary.py   Activity / DayPlan / Itinerary models and build_itinerary
  agent/agent.py       create_agent + InMemorySaver (memory keyed by thread_id)
  agentui.py           chat UI
  app.py               entry point (binds 0.0.0.0 on $PORT for Render)
```

- **Agent:** LangChain `create_agent` with Gemini Flash, the tools below, and the system prompt.
- **Memory:** `InMemorySaver` checkpointer; the `thread_id` keeps follow-ups attached to the existing plan.
- **Structured output:** `build_itinerary(model, result)` takes the conversation transcript and returns a typed `Itinerary`. `Activity.cost` is a string so it can say `"unknown"`, and `Itinerary.unknowns` lists what the tools could not confirm.
- **Deployment:** Render web service (root directory `trip_planner`, start command `python app.py`).

## Tools

| Tool | Backend | Purpose |
|---|---|---|
| `get_current_date()` | Python `datetime` (US Eastern) | Resolves "today", "tomorrow", "next Friday" into real `YYYY-MM-DD` dates for the other tools. |
| `get_weather(city, date)` | Open-Meteo (geocode, then forecast) | Forecast for up to 16 days. Reports which place was resolved (e.g. Cambridge, England vs. Massachusetts) and states the available window when a date is out of range. |
| `find_attractions(city, interest)` | Tavily search | Sights, museums, parks. |
| `find_restaurants(city, budget)` | Tavily search | Food and drink. Returns no hours or current prices. |
| `find_events(city, date, category)` | Ticketmaster Discovery API | Ticketed events with real dates, venues and links. Uses venue-local date filters; prices are usually "not published". Flags that an unrecognised category returns zero events. |
| `get_transit_info(city)` | Tavily search | General guidance on metro, bus, passes and fares. No timetables or journey times. |
| `find_performer_events(performer, city, date)` | Ticketmaster (two chained calls) | Extra credit. Looks up the performer's id, then searches events by that id. Handles unknown performers, no events in the city, and ambiguous names. |

Two tools return structured API data (weather, events) and the Tavily tools return prose snippets of unknown freshness, so they fail differently. Every tool returns a readable string and never raises, and the docstrings are what the model reads to pick the right tool.

## Configuration

Environment variables (never committed): `GOOGLE_API_KEY`, `TAVILY_API_KEY`, `TICKETMASTER_API_KEY`. Open-Meteo needs no key.

```bash
cd trip_planner
pip install -r requirements.txt
python -m agent.agent   # chat in the terminal
python app.py           # web UI at http://127.0.0.1:7860
```
