"""Per-database domain notes appended to the agent's context (BigQuery arm only).

Gated behind run_benchmark's --domain-notes (AgentConfig is untouched, so the SQLite
baseline and prompt parity are unaffected). Keyed by the question's `db` field.

BOUNDARY — benchmark integrity: these are LEGITIMATE data-model facts (grain, nested
structure, entity identity, missing-value sentinels, unit conventions) a domain analyst
would know from the dataset's own schema and public documentation. They never name a
specific table, value, or answer because "gold uses it"; nothing here is derived from a
gold query or an expected result. The never-solved analysis showed the model already reads
each question's external_knowledge doc and still mis-models these recurring facts; the notes
restate the data model, not the solution.
"""

# Google Analytics 4 web export (bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*)
_GA4 = """[DATABASE NOTES — GA4 event export]
- event_params and user_properties are ARRAYs of key/value structs. Read a key with a
  scalar subquery, e.g. (SELECT value.int_value FROM UNNEST(event_params) WHERE key='ga_session_id').
- A SESSION is identified by (user_pseudo_id, ga_session_id) TOGETHER — ga_session_id is
  unique only within a user, so counting it alone merges different users' sessions.
- An ENGAGED session is one whose event_params key 'session_engaged' = '1'.
- Session-scoped source / medium / campaign come from the event_params keys 'source' /
  'medium' / 'campaign' — take the FIRST non-null value within the session (ordered by
  event_timestamp). The record-level traffic_source.* is the USER's first-touch attribution,
  not the session's, and gives different numbers.
- Default channel grouping is a CASE over that session source/medium/campaign; when a
  document is attached it defines the exact conditions — follow them verbatim.
- event_date is a 'YYYYMMDD' STRING; use PARSE_DATE('%Y%m%d', event_date) and _TABLE_SUFFIX."""

# Firebase gaming export — same GA4 schema (firebase-public-project.analytics_153293282.events_*)
_FIREBASE = """[DATABASE NOTES — Firebase/GA4 gaming event export]
- Same GA4 structure: event_params is an array of key/value structs; a session is
  (user_pseudo_id, ga_session_id); session_start marks a session's start.
- A NEW user on a day: event_date = DATE(TIMESTAMP_MICROS(user_first_touch_timestamp)).
- Retention week bucketing: days_since_cohort = DATE_DIFF(active_date, cohort_date, DAY);
  week = CEIL(days_since_cohort / 7) with the cohort day (day 0) = week 0. Monday-based
  weeks are DATE_TRUNC(d, WEEK(MONDAY)).
- event_date is a 'YYYYMMDD' STRING; use PARSE_DATE and _TABLE_SUFFIX for the date range."""

# Universal Analytics sample (bigquery-public-data.google_analytics_sample.ga_sessions_*)
_GA360 = """[DATABASE NOTES — Google Analytics (Universal) ga_sessions]
- One row per SESSION, identified by (fullVisitorId, visitId). hits is a nested ARRAY and
  hits.product is nested within hits — UNNEST(hits), then UNNEST(hits.product), to reach
  page/product rows.
- "Average X per visitor" = SUM(X) / COUNT(DISTINCT fullVisitorId), NOT AVG(X) (AVG divides
  by session/hit rows, a different denominator).
- A purchase/transaction is hits.transaction.transactionId IS NOT NULL (or product.product
  Revenue IS NOT NULL at the product grain); totals.transactions is a session-level count.
- date is a 'YYYYMMDD' STRING (PARSE_DATE('%Y%m%d', date)); tables are day-sharded (_TABLE_
  SUFFIX). Revenue fields (totalTransactionRevenue, productRevenue) are in micros — divide
  by 1,000,000."""

# World Bank (bigquery-public-data.world_bank_* : country_summary + indicators_data/international_debt)
_WORLD_BANK = """[DATABASE NOTES — World Bank]
- The country_summary table mixes real COUNTRIES with AGGREGATE groupings (e.g. 'World',
  regions, income groups). Aggregate rows have an empty region (region = '') and usually a
  null income_group. To analyze only real countries, join indicators to country_summary and
  exclude region = '' (and income_group IS NULL where relevant), or the aggregates are
  double-counted."""

# NOAA GSOD daily global weather (bigquery-public-data.noaa_gsod.gsod* + .stations)
_NOAA_GSOD = """[DATABASE NOTES — NOAA GSOD weather]
- Missing-value SENTINELS are not real measurements and must be excluded: temp/max/min =
  9999.9, prcp = 99.99, wdsp/sndp = 999.9, gust = 999.9.
- A station is keyed by (stn = usaf, wban). A station NAME can map to several usaf codes —
  select stations by name via the .stations table rather than hard-coding one stn.
- Units are US customary: temp °F (→°C: (F-32)/1.8), wind knots (→ m/s: *1852/3600), prcp
  inches (→ cm: *2.54). gsod is year-sharded (gsod20YY, or gsod* with _TABLE_SUFFIX)."""

NOTES: dict[str, str] = {
    "ga4": _GA4,
    "firebase": _FIREBASE,
    "ga360": _GA360,
    "world_bank": _WORLD_BANK,
    "noaa_data": _NOAA_GSOD,
}


def domain_notes(db_name: str) -> str | None:
    """Curated data-model notes for a database, or None if none are authored."""
    return NOTES.get(db_name)
