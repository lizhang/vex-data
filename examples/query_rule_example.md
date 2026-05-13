1. query: 
{
  "entity": "matches",
  "filter": {
    "and": [
      {"field": "matches.start_time", "op": "gt", "value": "2026-05-09T00:00:00-05:00"},
      {"field": "matches.end_time", "op": "lt", "value": "2026-05-10T23:59:59-05:00"}
    ]
  },
  "orderBy": {"field": "matches.score", "direction": "desc"},
  "selectTop": 25
}


2. query:
{
  "entity": "team",
  "filter": {
    "and": [
      {"field": "teams.city", "op": "eq", "value": "San Diego"},
      {"field": "teams.country", "op": "eq", "value": "United States"}
    ]
  },
  "orderBy": {"field": "rankings.rank", "direction": "asc"},
  "selectTop": 5
}


3. query:
{
  "entity": "event",
  "filter": {
    "or": [
      {"field": "events.country", "op": "eq", "value": "United States"},
      {"field": "events.country", "op": "eq", "value": "Canada"}
    ]
  },
  "orderBy": {"field": "events.time", "direction": "asc"},
  "selectTop": 25
}

