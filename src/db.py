"""Database initialization — creates connection, sets PRAGMAs, and builds tables/views."""

import logging
import sqlite3

log = logging.getLogger(__name__)


def init_db(db_path: str, config: dict) -> sqlite3.Connection:
    """Open (or create) the SQLite database at *db_path* and set it up.

    Parameters
    ----------
    db_path:
        Filesystem path to the SQLite database file.
    config:
        The full configuration dict returned by :func:`config.load_config`.
        The ``database`` sub-dict is read for PRAGMA settings.

    Returns
    -------
    sqlite3.Connection
        An open connection with WAL mode, indexes, and views in place.
    """
    db_cfg = config.get("database", {})
    wal_mode = db_cfg.get("wal_mode", True)
    cache_size = db_cfg.get("cache_size", -4000)
    busy_timeout = db_cfg.get("busy_timeout", 5000)

    conn = sqlite3.connect(db_path, check_same_thread=False)

    # -- PRAGMAs ------------------------------------------------------------
    if wal_mode:
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA cache_size={cache_size}")
    conn.execute(f"PRAGMA busy_timeout={busy_timeout}")
    conn.execute("PRAGMA synchronous=NORMAL")

    # -- ODS layer: raw HTTP responses --------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ods_raw_quotes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            request_ts    TEXT    NOT NULL,
            url           TEXT    NOT NULL,
            status_code   INTEGER,
            raw_text      TEXT,
            latency_ms    REAL,
            parse_ok      INTEGER DEFAULT 1,
            error_detail  TEXT,
            symbols_in    TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_ods_request_ts
        ON ods_raw_quotes (request_ts)
    """)

    # -- DWD layer: parsed per-symbol quotes --------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dwd_quotes (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol        TEXT    NOT NULL,
            name          TEXT,
            quote_date    TEXT,
            quote_time    TEXT,
            open          REAL,
            prev_close    REAL,
            current       REAL,
            high          REAL,
            low           REAL,
            volume        REAL,
            amount        REAL,
            change_pct    REAL,
            delta_volume  REAL,
            delta_amount  REAL,
            tick_index    INTEGER,
            order_book    TEXT,
            fetched_at    TEXT    NOT NULL,
            latency_ms    REAL,
            is_first_tick INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_dwd_symbol_fetched
        ON dwd_quotes (symbol, fetched_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_dwd_symbol_date
        ON dwd_quotes (symbol, quote_date)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_dwd_quote_date
        ON dwd_quotes (quote_date)
    """)

    # -- DWS layer: aggregated minute bars ----------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dws_minute_bars (
            symbol        TEXT NOT NULL,
            bar_minute    TEXT NOT NULL,
            open          REAL,
            high          REAL,
            low           REAL,
            close         REAL,
            volume        REAL,
            amount        REAL,
            tick_count    INTEGER,
            first_tick_id INTEGER,
            last_tick_id  INTEGER,
            PRIMARY KEY (symbol, bar_minute)
        ) WITHOUT ROWID
    """)

    # -- DWS layer: daily summary -------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dws_daily_summary (
            symbol         TEXT NOT NULL,
            trade_date     TEXT NOT NULL,
            open           REAL,
            high           REAL,
            low            REAL,
            close          REAL,
            prev_close     REAL,
            volume         REAL,
            amount         REAL,
            change_pct     REAL,
            tick_count     INTEGER,
            first_tick_at  TEXT,
            last_tick_at   TEXT,
            avg_latency_ms REAL,
            PRIMARY KEY (symbol, trade_date)
        ) WITHOUT ROWID
    """)

    # -- ADS views ----------------------------------------------------------
    conn.execute("""
        CREATE VIEW IF NOT EXISTS ads_latest_quotes AS
        SELECT dq.*
        FROM dwd_quotes dq
        INNER JOIN (
            SELECT symbol, MAX(fetched_at) AS max_fetched
            FROM dwd_quotes
            GROUP BY symbol
        ) latest
        ON dq.symbol = latest.symbol AND dq.fetched_at = latest.max_fetched
    """)

    conn.execute("""
        CREATE VIEW IF NOT EXISTS ads_intraday_stats AS
        SELECT
            symbol,
            quote_date,
            MIN(current)  AS low,
            MAX(current)  AS high,
            MAX(fetched_at) AS last_tick_at,
            MIN(fetched_at) AS first_tick_at,
            COUNT(*)       AS tick_count,
            SUM(delta_volume) AS total_delta_volume,
            SUM(delta_amount) AS total_delta_amount,
            AVG(latency_ms)   AS avg_latency_ms
        FROM dwd_quotes
        WHERE quote_date = DATE('now', 'localtime')
        GROUP BY symbol, quote_date
    """)

    conn.execute("""
        CREATE VIEW IF NOT EXISTS ads_price_alerts AS
        SELECT *
        FROM dwd_quotes
        WHERE ABS(change_pct) > 2.0
          AND fetched_at >= DATETIME('now', '-1 hour', 'localtime')
    """)

    # -- ADS: 实时盘中指标 -----------------------------------------------------
    conn.execute("""
        CREATE VIEW IF NOT EXISTS ads_intraday_vwap AS
        SELECT
            symbol,
            bar_minute,
            CASE WHEN SUM(volume) > 0
                 THEN SUM(amount) / SUM(volume)
                 ELSE NULL END AS vwap,
            SUM(volume) AS cum_volume,
            SUM(amount) AS cum_amount,
            MAX(close)  AS last_close
        FROM dws_minute_bars
        WHERE bar_minute LIKE DATE('now', 'localtime') || '%'
        GROUP BY symbol
    """)

    conn.execute("""
        CREATE VIEW IF NOT EXISTS ads_daily_closes AS
        SELECT
            symbol,
            trade_date,
            open,
            high,
            low,
            close,
            volume,
            amount,
            prev_close,
            change_pct,
            LAG(close, 1) OVER (PARTITION BY symbol ORDER BY trade_date) AS prev_close_calc,
            ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trade_date) AS day_seq
        FROM dws_daily_summary
        ORDER BY symbol, trade_date
    """)

    # -- DIM 层：节点数据（getHQNodeData API） --------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dwd_node_data (
            symbol          TEXT NOT NULL PRIMARY KEY,
            code            TEXT,
            name            TEXT,
            trade           REAL,
            pricechange     REAL,
            changepercent   REAL,
            buy             REAL,
            sell            REAL,
            settlement      REAL,
            open            REAL,
            high            REAL,
            low             REAL,
            volume          REAL,
            amount          REAL,
            ticktime        TEXT,
            per             REAL,
            pb              REAL,
            mktcap          REAL,
            nmc             REAL,
            turnoverratio   REAL,
            fetched_at      TEXT NOT NULL
        ) WITHOUT ROWID
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_node_data_fetched
        ON dwd_node_data (fetched_at)
    """)

    # -- DIM 层：行业分类 ----------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dim_industries (
            code          TEXT NOT NULL PRIMARY KEY,
            name          TEXT NOT NULL,
            level         INTEGER DEFAULT 1,
            parent_code   TEXT,
            updated_at    TEXT NOT NULL
        ) WITHOUT ROWID
    """)

    # -- DIM 层：概念板块 ----------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dim_concepts (
            code          TEXT NOT NULL PRIMARY KEY,
            name          TEXT NOT NULL,
            updated_at    TEXT NOT NULL
        ) WITHOUT ROWID
    """)

    # -- DIM 层：标的分类映射 ------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dim_symbol_classifications (
            symbol              TEXT NOT NULL,
            classification_type TEXT NOT NULL,
            classification_code TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            PRIMARY KEY (symbol, classification_type, classification_code)
        ) WITHOUT ROWID
    """)

    # -- ADS：标的基本面视图 --------------------------------------------------
    conn.execute("""
        CREATE VIEW IF NOT EXISTS ads_symbol_fundamentals AS
        SELECT
            n.symbol,
            n.name,
            n.trade,
            n.changepercent,
            n.per,
            n.pb,
            n.mktcap,
            n.nmc           AS circ_mktcap,
            n.turnoverratio,
            n.volume,
            n.amount,
            n.fetched_at,
            sc.classification_code AS sw_industry
        FROM dwd_node_data n
        LEFT JOIN dim_symbol_classifications sc
            ON n.symbol = sc.symbol
            AND sc.classification_type = 'sw_industry'
    """)

    conn.commit()
    log.info("Database initialized at %s (wal_mode=%s)", db_path, wal_mode)
    return conn
