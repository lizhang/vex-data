"""Async client for the RobotEvents API v2 with automatic pagination."""

import asyncio
from typing import Any

import httpx

from app.config import settings

_PER_PAGE = 250


class RobotEventsClient:
    def __init__(self) -> None:
        self._base = settings.robotevents_base_url
        self._headers = {
            "Authorization": f"Bearer {settings.robotevents_api_key}",
            "Accept": "application/json",
        }

    async def _get_page(
        self, client: httpx.AsyncClient, path: str, params: dict, page: int
    ) -> dict:
        resp = await client.get(
            f"{self._base}{path}",
            headers=self._headers,
            params={**params, "page": page, "per_page": _PER_PAGE},
        )
        resp.raise_for_status()
        return resp.json()

    async def _fetch_all(self, path: str, params: dict | None = None) -> list[dict]:
        params = params or {}
        records: list[dict] = []

        async with httpx.AsyncClient(timeout=30) as client:
            first = await self._get_page(client, path, params, page=1)
            records.extend(first["data"])
            last_page: int = first["meta"]["last_page"]
            if last_page > 1:
                pages = await asyncio.gather(
                    *[self._get_page(client, path, params, page=p) for p in range(2, last_page + 1)]
                )
                for page in pages:
                    records.extend(page["data"])

        return records

    async def get_events(
        self, season_id: int, program_ids: list[int] | None = None
    ) -> list[dict]:
        params: dict[str, Any] = {"season[]": season_id}
        if program_ids:
            params["program[]"] = program_ids
        return await self._fetch_all("/events", params)

    async def get_event_teams(self, event_id: int) -> list[dict]:
        return await self._fetch_all(f"/events/{event_id}/teams")

    async def get_event_skills(self, event_id: int) -> list[dict]:
        return await self._fetch_all(f"/events/{event_id}/skills")

    async def get_event_matches(self, event_id: int, division_id: int) -> list[dict]:
        return await self._fetch_all(
            f"/events/{event_id}/divisions/{division_id}/matches"
        )

    async def get_all_matches_for_event(self, event: dict) -> list[dict]:
        """Fetch matches across all divisions; tag each record with division + season."""
        all_matches: list[dict] = []
        season_id = (event.get("season") or {}).get("id")
        for div in event.get("divisions", []):
            matches = await self.get_event_matches(event["id"], div["id"])
            for m in matches:
                m["_division_id"] = div["id"]
                m["_division_name"] = div.get("name", "")
                m["_season_id"] = season_id
            all_matches.extend(matches)
        return all_matches
