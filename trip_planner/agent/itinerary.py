"""Trip planner: the structured itinerary.

To be used to extract one typed itinerary from the conversation.

Please note `cost` is a STRING, not a number, so that
"unknown" is something the itinerary can actually say, and so a price can carry
where it came from. If it were a float the model would have to invent a figure
to fill it, and a made-up price looks exactly like a real one.
"""

from typing import Literal

from pydantic import BaseModel, Field


class Activity(BaseModel):
    """One thing the traveller does."""
    time: str = Field(description="When it starts, e.g. '09:30' or 'morning'")
    name: str = Field(description="What it is, e.g. 'Museum of Fine Arts'")
    kind: Literal["sight", "food", "event", "travel", "other"] = Field(
        description="Which tool this came from: sight, food, event, travel, other")
    cost: str = Field(
        description="'free' only when something actually says it is free; a price "
                    "a tool gave you, marked with where it came from, like "
                    "'$45-120 (Ticketmaster)' or '$27 (blog, unconfirmed)'; or "
                    "'unknown'. Most things will be 'unknown' — that is the honest "
                    "answer, and an unknown price is never 0.")
    source: str = Field(description="The URL this came from, or 'none' if there isn't one")


# TODO: write DayPlan. One day of the trip: a date, what the weather said, and a
# list of Activity. An itinerary is a list of days, each holding a list of
# activities, one level more nesting than W03a.2.
class DayPlan(BaseModel):
    """One day of the trip."""
    date: str = Field(
        description="The date for this day, like '2026-10-05', or just 'day 1' "
                    "if there wasn't a real date to go on")
    weather: str = Field(
        description="Quick summary of what get_weather said for this day (e.g. 'rain, high 12C/low 7C'), or 'unknown' if we never "
                    "checked")
    activities: list[Activity] = Field(
        description="The things planned for this day, in order")


# TODO: write Itinerary. The city, a list of DayPlan, and an `unknowns` list of
# everything the tools could not confirm. Give every field a Field(description=...):
# those descriptions are what the model reads when it fills the model in.
class Itinerary(BaseModel):
    """A complete plan for a trip."""
    city: str = Field(description="The destination city")
    days: list[DayPlan] = Field(description="Each day of the trip in order")
    unknowns: list[str] = Field(
        description="Things the tools couldn't confirm during the conversation, like opening hours, journey times, prices that weren't "
                    "published, or a forecast that was too far out. Leave this empty if nothing like that came up.")


ITINERARIES = []


def build_itinerary(model, result) -> Itinerary:
    """Extract a structured itinerary from a finished planning conversation.

    This is `file_ticket` from W03b.1 pointed at a trip. Build the transcript from result["messages"], 
    call model.with_structured_output(Itinerary) on it, append to ITINERARIES, and return it.
    """
    # TODO: implement
    transcript_lines = []
    for message in result["messages"]:
        if message.text:
            transcript_lines.append(f"{type(message).__name__}: {message.text}")
    transcript = "\n".join(transcript_lines)

    itinerary = model.with_structured_output(Itinerary).invoke(
        "Extract a structured trip itinerary from this planning conversation. "
        "Only put down a cost if it was actually mentioned somewhere, otherwise just use 'unknown'. " \
        "Don't guess a number, and don't treat a missing price as 0 or free. " \
        "Put anything the tools couldn't confirm in 'unknowns' "
        "(opening hours, journey times, unpublished prices, a forecast past the 16-day window, etc).\n\n" + transcript)
    ITINERARIES.append(itinerary)
    return itinerary
