"""Short glossary of how this database is modeled, added to the schema in the prompt.

Each entry states a fact about the data's structure, not an answer to any particular question.
"""

GLOSSARY = """NOTES ABOUT THIS DATA

Stints: Batting, Pitching and Fielding have one row per player per season per stint. A player who played for
more than one team in a season (a trade) has several rows for that season. A season or career total therefore
needs SUM(...) grouped by playerID (and yearID for a season). To find who led in a stat, sum per player first and
rank the sums; never rank individual rows and never treat one row as a season total.

Franchises: Teams has one row per team per season, and teamID and name change over a franchise's history
(for example the Athletics are PHA, KC1 and OAK). franchID in Teams identifies the franchise across all of those
years, and TeamsFranchises.franchName is the franchise's current name. For all-time, historical or "franchise"
questions, filter and group by franchID (join TeamsFranchises on franchID for the name), not by teamID or
Teams.name. For a specific team in a specific season, teamID/name and yearID are correct."""


def with_glossary(schema_text: str) -> str:
    return GLOSSARY + "\n\n" + schema_text
