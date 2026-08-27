
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    league_code TEXT NOT NULL DEFAULT 'E0',
    season TEXT NOT NULL,
    match_date TEXT NOT NULL,
    kickoff_time TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    referee TEXT,
    home_goals INTEGER,
    away_goals INTEGER,
    home_ht_goals INTEGER,
    away_ht_goals INTEGER,
    full_time_result TEXT,
    half_time_result TEXT,
    source_file TEXT,
    imported_at TEXT NOT NULL,
    UNIQUE(season, match_date, home_team, away_team)
);

CREATE TABLE IF NOT EXISTS team_match_stats (
    match_id TEXT NOT NULL,
    season TEXT NOT NULL,
    match_date TEXT NOT NULL,
    team TEXT NOT NULL,
    opponent TEXT NOT NULL,
    venue TEXT NOT NULL CHECK(venue IN ('H','A')),
    referee TEXT,
    goals_for REAL,
    goals_against REAL,
    ht_goals_for REAL,
    ht_goals_against REAL,
    shots_for REAL,
    shots_against REAL,
    shots_on_target_for REAL,
    shots_on_target_against REAL,
    fouls_committed REAL,
    fouls_suffered REAL,
    corners_for REAL,
    corners_against REAL,
    yellow_cards REAL,
    yellow_cards_opponent REAL,
    red_cards REAL,
    red_cards_opponent REAL,
    xg_for REAL,
    xg_against REAL,
    points INTEGER,
    result TEXT,
    PRIMARY KEY(match_id, team),
    FOREIGN KEY(match_id) REFERENCES matches(match_id)
);

CREATE TABLE IF NOT EXISTS match_odds (
    match_id TEXT NOT NULL,
    odds_key TEXT NOT NULL,
    odds_value REAL,
    source_file TEXT,
    PRIMARY KEY(match_id, odds_key),
    FOREIGN KEY(match_id) REFERENCES matches(match_id)
);

CREATE TABLE IF NOT EXISTS teams (
    team_id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_name TEXT UNIQUE NOT NULL,
    first_season TEXT,
    last_season TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS team_name_mapping (
    source_name TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS referees (
    referee_id INTEGER PRIMARY KEY AUTOINCREMENT,
    referee_name TEXT UNIQUE NOT NULL,
    first_season TEXT,
    last_season TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS referee_match_stats (
    match_id TEXT PRIMARY KEY,
    season TEXT NOT NULL,
    match_date TEXT NOT NULL,
    referee TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_fouls REAL,
    away_fouls REAL,
    total_fouls REAL,
    home_yellow REAL,
    away_yellow REAL,
    total_yellow REAL,
    home_red REAL,
    away_red REAL,
    total_red REAL,
    FOREIGN KEY(match_id) REFERENCES matches(match_id)
);

CREATE TABLE IF NOT EXISTS team_season_stats (
    season TEXT NOT NULL,
    team TEXT NOT NULL,
    matches INTEGER NOT NULL,
    wins INTEGER,
    draws INTEGER,
    losses INTEGER,
    points INTEGER,
    goals_for_avg REAL,
    goals_against_avg REAL,
    shots_for_avg REAL,
    shots_against_avg REAL,
    shots_on_target_for_avg REAL,
    shots_on_target_against_avg REAL,
    fouls_committed_avg REAL,
    fouls_suffered_avg REAL,
    corners_for_avg REAL,
    corners_against_avg REAL,
    yellow_cards_avg REAL,
    yellow_cards_opponent_avg REAL,
    red_cards_avg REAL,
    xg_for_avg REAL,
    xg_against_avg REAL,
    PRIMARY KEY(season, team)
);

CREATE TABLE IF NOT EXISTS team_home_away_stats (
    season TEXT NOT NULL,
    team TEXT NOT NULL,
    venue TEXT NOT NULL,
    matches INTEGER NOT NULL,
    wins INTEGER,
    draws INTEGER,
    losses INTEGER,
    points INTEGER,
    goals_for_avg REAL,
    goals_against_avg REAL,
    shots_for_avg REAL,
    shots_against_avg REAL,
    shots_on_target_for_avg REAL,
    shots_on_target_against_avg REAL,
    fouls_committed_avg REAL,
    fouls_suffered_avg REAL,
    corners_for_avg REAL,
    corners_against_avg REAL,
    yellow_cards_avg REAL,
    yellow_cards_opponent_avg REAL,
    red_cards_avg REAL,
    xg_for_avg REAL,
    xg_against_avg REAL,
    PRIMARY KEY(season, team, venue)
);

CREATE TABLE IF NOT EXISTS team_form_stats (
    season TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    team TEXT NOT NULL,
    window INTEGER NOT NULL,
    matches_used INTEGER NOT NULL,
    points_avg REAL,
    goals_for_avg REAL,
    goals_against_avg REAL,
    shots_for_avg REAL,
    shots_against_avg REAL,
    shots_on_target_for_avg REAL,
    shots_on_target_against_avg REAL,
    fouls_committed_avg REAL,
    fouls_suffered_avg REAL,
    corners_for_avg REAL,
    corners_against_avg REAL,
    yellow_cards_avg REAL,
    yellow_cards_opponent_avg REAL,
    red_cards_avg REAL,
    xg_for_avg REAL,
    xg_against_avg REAL,
    PRIMARY KEY(season, as_of_date, team, window)
);

CREATE TABLE IF NOT EXISTS referee_season_stats (
    season TEXT NOT NULL,
    referee TEXT NOT NULL,
    matches INTEGER NOT NULL,
    fouls_avg REAL,
    home_fouls_avg REAL,
    away_fouls_avg REAL,
    yellow_avg REAL,
    home_yellow_avg REAL,
    away_yellow_avg REAL,
    red_avg REAL,
    PRIMARY KEY(season, referee)
);

CREATE TABLE IF NOT EXISTS referee_form_stats (
    season TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    referee TEXT NOT NULL,
    window INTEGER NOT NULL,
    matches_used INTEGER NOT NULL,
    fouls_avg REAL,
    home_fouls_avg REAL,
    away_fouls_avg REAL,
    yellow_avg REAL,
    red_avg REAL,
    PRIMARY KEY(season, as_of_date, referee, window)
);

CREATE TABLE IF NOT EXISTS league_stats (
    season TEXT PRIMARY KEY,
    matches INTEGER NOT NULL,
    goals_avg REAL,
    home_goals_avg REAL,
    away_goals_avg REAL,
    shots_avg REAL,
    shots_on_target_avg REAL,
    fouls_avg REAL,
    home_fouls_avg REAL,
    away_fouls_avg REAL,
    corners_avg REAL,
    home_corners_avg REAL,
    away_corners_avg REAL,
    yellow_avg REAL,
    red_avg REAL,
    xg_avg REAL
);

CREATE TABLE IF NOT EXISTS standings_history (
    season TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    team TEXT NOT NULL,
    played INTEGER NOT NULL,
    wins INTEGER NOT NULL,
    draws INTEGER NOT NULL,
    losses INTEGER NOT NULL,
    goals_for INTEGER NOT NULL,
    goals_against INTEGER NOT NULL,
    goal_difference INTEGER NOT NULL,
    points INTEGER NOT NULL,
    position INTEGER,
    PRIMARY KEY(season, as_of_date, team)
);

CREATE TABLE IF NOT EXISTS data_sources (
    source_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    source_url TEXT,
    dataset TEXT,
    last_update TEXT
);

CREATE TABLE IF NOT EXISTS update_log (
    update_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at TEXT NOT NULL,
    source_file TEXT,
    rows_read INTEGER,
    matches_after_update INTEGER,
    status TEXT,
    message TEXT
);

CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(match_date);
CREATE INDEX IF NOT EXISTS idx_matches_season ON matches(season);
CREATE INDEX IF NOT EXISTS idx_team_match_team_date ON team_match_stats(team, match_date);
CREATE INDEX IF NOT EXISTS idx_referee_match_ref_date ON referee_match_stats(referee, match_date);
