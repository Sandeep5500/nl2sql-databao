#!/usr/bin/env python3
"""Build a small foreign SQLite database for synthesis smoke tests.

Deliberately NOT one of the 30 Spider 2.0 local databases: training data must
never touch a test schema (see documents/judge_finetuning_plan.md §3.1). This is
a stand-in for a sampled SynSQL database, for use before SynSQL's databases.zip
is unpacked on Babel.

Shaped to match our test distribution (median 13 tables / 77 columns): 10 tables,
68 columns. Carries the kinds of mess our failure taxonomy depends on -- NULLs
that change join semantics, a column declared INTEGER that stores text, and
near-duplicate rows -- so synthesized questions can exercise them.

It also deliberately leaves ENTITIES WITH ZERO MATCHING ROWS in most
relationships: stations with no trips, members who never rode, bikes in storage,
technicians with no jobs, an unchosen plan, a model never acquired. Without
these, LEFT JOIN and INNER JOIN return identical results and the `boundary`
bucket cannot build a trap at all -- measured: 18 of 21 generation attempts
failed with "naive gives an identical result" on a seed-7 database where 7 of 8
relationships were fully saturated. Real databases have such gaps naturally;
uniform random assignment over 60k rows does not.

Usage (from nl2sql-v2/):
    uv run python scripts/make_synth_db.py --out /tmp/bikeshare.sqlite
"""

import argparse
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DDL = """
CREATE TABLE boroughs (
    borough_id INTEGER PRIMARY KEY, borough_name TEXT NOT NULL,
    population INTEGER, area_km2 REAL);

CREATE TABLE stations (
    station_id INTEGER PRIMARY KEY, station_name TEXT NOT NULL,
    borough_id INTEGER REFERENCES boroughs(borough_id),
    latitude REAL, longitude REAL, capacity INTEGER,
    installed_on TEXT, is_active INTEGER);

CREATE TABLE bike_models (
    model_id INTEGER PRIMARY KEY, model_name TEXT, manufacturer TEXT,
    is_electric INTEGER, weight_kg REAL, battery_wh INTEGER);

CREATE TABLE bikes (
    bike_id INTEGER PRIMARY KEY,
    model_id INTEGER REFERENCES bike_models(model_id),
    acquired_on TEXT, status TEXT, total_km REAL, last_service_on TEXT);

CREATE TABLE plans (
    plan_id INTEGER PRIMARY KEY, plan_name TEXT, monthly_fee_cents INTEGER,
    included_minutes INTEGER, overage_per_min_cents INTEGER, active_from TEXT);

CREATE TABLE members (
    member_id INTEGER PRIMARY KEY, joined_on TEXT,
    plan_id INTEGER REFERENCES plans(plan_id),
    birth_year INTEGER, gender TEXT, postcode TEXT,
    referred_by INTEGER REFERENCES members(member_id));

CREATE TABLE promos (
    promo_code TEXT PRIMARY KEY, description TEXT, discount_pct REAL,
    valid_from TEXT, valid_to TEXT,
    max_uses INTEGER);          -- declared INTEGER, some rows store 'unlimited'

CREATE TABLE trips (
    trip_id INTEGER PRIMARY KEY,
    bike_id INTEGER REFERENCES bikes(bike_id),
    member_id INTEGER REFERENCES members(member_id),   -- NULL for casual riders
    start_station_id INTEGER REFERENCES stations(station_id),
    end_station_id INTEGER REFERENCES stations(station_id),  -- NULL if not returned
    started_at TEXT, ended_at TEXT, duration_sec INTEGER,
    distance_km REAL, fare_cents INTEGER, promo_code TEXT);

CREATE TABLE technicians (
    technician_id INTEGER PRIMARY KEY, technician_name TEXT, hired_on TEXT,
    depot_borough_id INTEGER REFERENCES boroughs(borough_id),
    hourly_rate_cents INTEGER);

CREATE TABLE maintenance (
    job_id INTEGER PRIMARY KEY,
    bike_id INTEGER REFERENCES bikes(bike_id),
    reported_at TEXT, completed_at TEXT, issue_type TEXT,
    cost_cents INTEGER,
    technician_id INTEGER REFERENCES technicians(technician_id),
    station_id INTEGER REFERENCES stations(station_id));

CREATE TABLE weather_daily (
    day TEXT, borough_id INTEGER REFERENCES boroughs(borough_id),
    temp_c_avg REAL, precip_mm REAL, wind_kph REAL,
    PRIMARY KEY (day, borough_id));
"""

BOROUGHS = [("Harbourside", 412000, 58.2), ("Northgate", 288000, 91.7),
            ("Eastvale", 196000, 44.1), ("Kingsmere", 533000, 120.4),
            ("Riverton", 147000, 33.8)]
ISSUES = ["flat tyre", "brake wear", "battery fault", "bent wheel",
          "chain slip", "vandalism", "firmware update"]
STATUSES = ["in_service", "in_service", "in_service", "maintenance", "retired"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--trips", type=int, default=60000)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    db = sqlite3.connect(out)
    db.executescript(DDL)

    db.executemany("INSERT INTO boroughs VALUES (?,?,?,?)",
                   [(i + 1, n, p, a) for i, (n, p, a) in enumerate(BOROUGHS)])

    stations = []
    for sid in range(1, 61):
        b = rng.randint(1, 5)
        stations.append((sid, f"{BOROUGHS[b-1][0]} {rng.choice(['Park','Square','Bridge','Market','Station','Quay'])} {sid}",
                         b, round(51.4 + rng.random() * 0.3, 5), round(-0.3 + rng.random() * 0.4, 5),
                         rng.choice([12, 16, 20, 24, 30, 40]),
                         str(date(2019, 1, 1) + timedelta(days=rng.randint(0, 1400))),
                         1 if rng.random() > 0.08 else 0))
    db.executemany("INSERT INTO stations VALUES (?,?,?,?,?,?,?,?)", stations)

    models = [(1, "CityCruise 1", "Veloworks", 0, 14.2, None),
              (2, "CityCruise 2", "Veloworks", 0, 13.6, None),
              (3, "Volt S", "Amperide", 1, 21.4, 420),
              (4, "Volt S Plus", "Amperide", 1, 22.8, 560),
              (5, "Haul 300", "Veloworks", 0, 28.9, None),
              (6, "Volt Cargo", "Amperide", 1, 34.1, 700),
              (7, "Volt Cargo 2", "Amperide", 1, 35.0, 820)]   # ordered, none in fleet
    db.executemany("INSERT INTO bike_models VALUES (?,?,?,?,?,?)", models)

    bikes = []
    for bid in range(1, 801):
        acq = date(2019, 3, 1) + timedelta(days=rng.randint(0, 1500))
        # rng.randint(1, 6) never picks model 7, which stays unacquired
        bikes.append((bid, rng.randint(1, 6), str(acq), rng.choice(STATUSES),
                      round(rng.uniform(5, 9000), 1),
                      str(acq + timedelta(days=rng.randint(30, 900)))))
    db.executemany("INSERT INTO bikes VALUES (?,?,?,?,?,?)", bikes)

    db.executemany("INSERT INTO plans VALUES (?,?,?,?,?,?)", [
        (1, "Pay as you go", 0, 0, 18, "2019-01-01"),
        (2, "Commuter", 1500, 600, 12, "2019-01-01"),
        (3, "Commuter Plus", 2900, 1800, 8, "2020-06-01"),
        (4, "Annual", 11900, 9000, 6, "2021-02-01"),
        (5, "Corporate", 24900, 20000, 4, "2025-07-01")])   # launched, nobody on it yet

    members = []
    for mid in range(1, 3001):
        members.append((mid, str(date(2019, 1, 1) + timedelta(days=rng.randint(0, 1700))),
                        rng.choice([1, 1, 2, 2, 2, 3, 3, 4]),   # never plan 5
                        rng.choice([None] + list(range(1950, 2008))),
                        rng.choice(["F", "M", "X", None]),
                        f"{rng.choice('NESW')}{rng.randint(1,20)} {rng.randint(1,9)}{rng.choice('ABDEFG')}{rng.choice('ABDEFG')}",
                        rng.choice([None] * 7 + [rng.randint(1, max(1, mid - 1))])))
    db.executemany("INSERT INTO members VALUES (?,?,?,?,?,?,?)", members)

    # max_uses is declared INTEGER but two rows store text -- mirrors the
    # declared-type mismatch we measured in the Spider 2.0 databases.
    db.executemany("INSERT INTO promos VALUES (?,?,?,?,?,?)", [
        ("SPRING20", "20% off spring weekends", 20.0, "2022-03-01", "2022-05-31", 5000),
        ("WELCOME", "First ride free", 100.0, "2019-01-01", "2026-12-31", "unlimited"),
        ("COMMUTE10", "10% off peak hours", 10.0, "2023-01-09", "2023-12-22", 20000),
        ("WINTER15", "15% off winter", 15.0, "2023-11-01", "2024-02-29", 8000),
        ("STUDENT", "Student discount", 25.0, "2021-09-01", "2026-12-31", "unlimited"),
        ("EVFIRST", "Free e-bike upgrade", 0.0, "2024-04-01", "2024-09-30", 1200),
        ("REFER5", "Referral credit", 5.0, "2020-01-01", "2026-12-31", 60000),
        ("LAPSED", "Expired test code", 50.0, "2019-05-01", "2019-06-01", 10)])

    techs = []
    for tid in range(1, 26):
        techs.append((tid, f"Tech {tid:02d}",
                      str(date(2019, 1, 1) + timedelta(days=rng.randint(0, 1600))),
                      rng.randint(1, 5), rng.choice([1800, 2050, 2200, 2450, 2700])))
    db.executemany("INSERT INTO technicians VALUES (?,?,?,?,?)", techs)

    # Held back from trip assignment so they stay empty (see module docstring).
    idle_stations = set(rng.sample(range(1, 61), 8))        # newly installed
    idle_bikes = set(rng.sample(range(1, 801), 60))         # in storage
    idle_members = set(rng.sample(range(1, 3001), 400))     # signed up, never rode
    active_stations = [s for s in range(1, 61) if s not in idle_stations]
    active_bikes = [b for b in range(1, 801) if b not in idle_bikes]
    active_members = [m for m in range(1, 3001) if m not in idle_members]

    codes = ["SPRING20", "WELCOME", "COMMUTE10", "WINTER15", "STUDENT",
             "EVFIRST", "REFER5", None, None, None, None, None]
    trips = []
    for tid in range(1, args.trips + 1):
        start = date(2022, 1, 1) + timedelta(days=rng.randint(0, 1000))
        hh, mm = rng.randint(5, 23), rng.randint(0, 59)
        dur = max(60, int(rng.gammavariate(2.0, 420)))
        s_st = rng.choice(active_stations)
        # 1.5% of trips are never returned -> end_station_id NULL
        e_st = None if rng.random() < 0.015 else rng.choice(active_stations)
        member = None if rng.random() < 0.22 else rng.choice(active_members)  # casual riders
        trips.append((tid, rng.choice(active_bikes), member, s_st, e_st,
                      f"{start} {hh:02d}:{mm:02d}:00",
                      f"{start} {hh:02d}:{mm:02d}:00" if e_st is None else
                      str(date.fromisoformat(str(start))) + f" {min(23,hh+dur//3600):02d}:{mm:02d}:00",
                      dur, round(dur / 3600 * rng.uniform(8, 19), 2),
                      int(max(0, dur / 60 * rng.uniform(6, 20))),
                      rng.choice(codes)))
    db.executemany("INSERT INTO trips VALUES (?,?,?,?,?,?,?,?,?,?,?)", trips)

    jobs = []
    jid = 1
    for _ in range(1500):
        bike = rng.randint(1, 800)
        rep = date(2022, 1, 1) + timedelta(days=rng.randint(0, 1000))
        done = None if rng.random() < 0.07 else str(rep + timedelta(days=rng.randint(0, 21)))
        issue = rng.choice(ISSUES)
        jobs.append((jid, bike, str(rep), done, issue,
                     int(rng.uniform(400, 18000)), rng.randint(1, 21), rng.randint(1, 60)))
        jid += 1
        # ~6% near-duplicates: same bike and issue, a few days later
        if rng.random() < 0.06:
            rep2 = rep + timedelta(days=rng.randint(1, 5))
            jobs.append((jid, bike, str(rep2), str(rep2 + timedelta(days=rng.randint(0, 9))),
                         issue, int(rng.uniform(400, 18000)), rng.randint(1, 21), rng.randint(1, 60)))
            jid += 1
    db.executemany("INSERT INTO maintenance VALUES (?,?,?,?,?,?,?,?)", jobs)

    wx = []
    for d in range(1000):
        day = str(date(2022, 1, 1) + timedelta(days=d))
        for b in range(1, 6):
            wx.append((day, b, round(rng.uniform(-3, 29), 1),
                       round(max(0.0, rng.gammavariate(1.3, 2.2)), 1),
                       round(rng.uniform(2, 48), 1)))
    db.executemany("INSERT INTO weather_daily VALUES (?,?,?,?,?)", wx)

    db.commit()
    cur = db.cursor()
    tables = [r[0] for r in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    ncols = 0
    print(f"wrote {out}  ({out.stat().st_size/1e6:.1f} MB)")
    for t in tables:
        cols = len(list(cur.execute(f'PRAGMA table_info("{t}")')))
        rows = cur.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        ncols += cols
        print(f"  {t:16s} {cols:3d} cols  {rows:7,d} rows")
    print(f"  {'TOTAL':16s} {ncols:3d} cols across {len(tables)} tables")
    db.close()


if __name__ == "__main__":
    main()
