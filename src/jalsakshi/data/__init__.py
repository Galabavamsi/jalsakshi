"""Public data fetchers (docs/ARCHITECTURE.md section 11): JJM IMIS, CGWB 2025 and Open-Meteo.

Every result carries a `SourceTag` (source, url, observed_at when stated, fetched_at, freshness).
Network and parse failures surface as `DataSourceError`, so callers can omit the context block.
"""

from jalsakshi.data.cgwb import BlockGroundwater, fetch_block_groundwater, find_block
from jalsakshi.data.http import DataSourceError, RetryPolicy, make_client
from jalsakshi.data.imis import StateHGJ, fetch_state_hgj
from jalsakshi.data.openmeteo import DailyRain, RainSummary, rain_last_days

__all__ = [
    "BlockGroundwater",
    "DailyRain",
    "DataSourceError",
    "RainSummary",
    "RetryPolicy",
    "StateHGJ",
    "fetch_block_groundwater",
    "fetch_state_hgj",
    "find_block",
    "make_client",
    "rain_last_days",
]
