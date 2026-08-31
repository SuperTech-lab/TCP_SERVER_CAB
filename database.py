import re
import threading
import psycopg2

from dataclasses import dataclass
from datetime import datetime, timezone
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
from default_config import (DB_INSERT_INTERVAL, SAMPLE_CHANNELS)

from lakeshore370 import LakeShore370

# DataBase conection params
db_delay          = DB_INSERT_INTERVAL
last_db_insert_ts = None
DB_POOL           = None
CURRENT_RUN_ID    = None

@dataclass
class RelationState:
    active               : bool = False
    run_id               : str | None = None
    channel              : int | None = None
    label                : str | None = None
    buffer               : list[tuple] = None
    ramp_controlled      : bool = False
    ramp_target_mk       : float | None = None
    ramp_rate_mk_per_min : float | None = None

RELATION_ACTIVE               = False
RELATION_RUN_ID               = None
RELATION_CHANNEL              = None   
RELATION_LABEL                = None     
RELATION_BUFFER               = []
RELATION_RAMP_CONTROLLED      = False
RELATION_RAMP_TARGET_MK       = None
RELATION_RAMP_RATE_MK_PER_MIN = None


def init_db_pool():
    global DB_POOL
    if DB_POOL is None:
        DB_POOL = ThreadedConnectionPool(
            minconn=1,
            maxconn=10,   
            host="192.168.38.4",
            port=5432,
            dbname="lakeshore_db",
            user="lakeshore_app",  
            password="Ricardo",
        )
        print("✅ DB connection pool initialized")


def close_db_pool():
    global DB_POOL
    if DB_POOL is not None:
        DB_POOL.closeall()
        DB_POOL = None
        print("🔻 DB connection pool closed")


@contextmanager
def get_db_conn():
    """
    Maneja el pool de conexiones de la bd
    """
    if DB_POOL is None:
        raise RuntimeError("DB_POOL not initialized.")

    conn = DB_POOL.getconn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        DB_POOL.putconn(conn)

def start_run(global_run_id: int, description: str | None = None):
    global CURRENT_RUN_ID, last_db_insert_ts

    if CURRENT_RUN_ID is not None:
        print(
            f"⚠ There's already a running RUN "
            f"(RUN_ID = {CURRENT_RUN_ID}). Close it with end_run()"
        )
        return False

    try:
        global_run_id = int(global_run_id)
    except (ValueError, TypeError):
        print("❌ RUN_ID must be an integer")
        return False

    if description is not None:
        description = description.strip()
        if description == "":
            description = None

    with get_db_conn() as conn:
        with conn.cursor() as cur:
            try:
                # PostgreSQL is the source of truth. Do not create a new RUN
                # if an unfinished RUN already exists.
                cur.execute(
                    """
                    SELECT run_id
                    FROM runs
                    WHERE ended_at IS NULL
                    ORDER BY started_at DESC
                    LIMIT 2;
                    """
                )
                open_rows = cur.fetchall()

                if open_rows:
                    conn.rollback()
                    last_db_insert_ts = None

                    if len(open_rows) == 1:
                        CURRENT_RUN_ID = int(open_rows[0][0])
                        print(
                            "⚠ An active RUN already exists in DB "
                            f"(RUN_ID = {CURRENT_RUN_ID}); new RUN not created"
                        )
                    else:
                        run_ids = ", ".join(
                            str(row[0]) for row in open_rows
                        )
                        CURRENT_RUN_ID = None
                        print(
                            "❌ Multiple active RUNs found in DB "
                            f"({run_ids}); new RUN not created"
                        )

                    return False

                cur.execute(
                    """
                    INSERT INTO runs (run_id, started_at, description)
                    VALUES (%s, now(), %s)
                    RETURNING run_id;
                    """,
                    (global_run_id, description),
                )

                CURRENT_RUN_ID = int(cur.fetchone()[0])
                conn.commit()

                last_db_insert_ts = None
                print(f"🏁 RUN {CURRENT_RUN_ID} started")
                return True

            except psycopg2.Error as e:
                conn.rollback()
                CURRENT_RUN_ID = None
                last_db_insert_ts = None
                print(f"❌ Error during RUN {global_run_id} initiation: {e}")
                return False

def end_run():
    global CURRENT_RUN_ID, last_db_insert_ts

    if CURRENT_RUN_ID is None:
        print("⚠ No hay un RUN activo inequívoco")
        return None

    ended_run_id = CURRENT_RUN_ID

    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE runs
                SET ended_at = now()
                WHERE run_id = %s
                  AND ended_at IS NULL
                RETURNING run_id;
                """,
                (ended_run_id,),
            )
            row = cur.fetchone()

        if row is None:
            conn.rollback()
            print(f"❌ RUN {ended_run_id} was not open in DB")
            return None

        conn.commit()

    CURRENT_RUN_ID = None
    last_db_insert_ts = None
    print(f"🏁 RUN {ended_run_id} finalizado")
    return ended_run_id

def resume_active_run_from_db():
    """
    Synchronize CURRENT_RUN_ID with PostgreSQL.

    A RUN with ended_at IS NULL remains active across a restart of
    tcp_server.py. If no RUN is open, the server starts without one.
    """

    global CURRENT_RUN_ID, last_db_insert_ts

    try:
        with get_db_conn() as conn:
            with conn.cursor() as cur:
                print("📡 Checking active RUN state in DB")

                cur.execute(
                    """
                    SELECT run_id
                    FROM runs
                    WHERE ended_at IS NULL
                    ORDER BY started_at DESC
                    LIMIT 2;
                    """
                )
                rows = cur.fetchall()

            # End the read-only transaction before returning the
            # connection to the pool.
            conn.rollback()

        if not rows:
            CURRENT_RUN_ID = None
            last_db_insert_ts = None
            print(
                "🛈 No active RUN found in DB; "
                "server starts without an active RUN"
            )
            return None

        if len(rows) > 1:
            run_ids = ", ".join(str(row[0]) for row in rows)
            CURRENT_RUN_ID = None
            last_db_insert_ts = None
            print(
                "❌ Multiple active RUNs found in DB "
                f"({run_ids}); refusing to choose one automatically"
            )
            return None

        CURRENT_RUN_ID = int(rows[0][0])
        last_db_insert_ts = None

        print(
            f"♻ Active RUN resumed from DB: "
            f"RUN_ID = {CURRENT_RUN_ID}"
        )
        return CURRENT_RUN_ID

    except Exception as e:
        print(f"❌ Error resuming active RUN from DB: {e}")
        CURRENT_RUN_ID = None
        last_db_insert_ts = None
        return None

def _as_db_bool(value) -> bool:
    if value is None: return False
    if isinstance(value, bool): return value
    if isinstance(value, (int, float)): return value != 0
    return str(value).strip().lower() in {"1", "true", "on", "yes"}

def _safe_label(label: str | None) -> str:
    if not label:
        return "NA"
    s = label.strip()
    if not s:
        return "NA"
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:60] if s else "NA"

def _make_relation_filename(label: str | None) -> str:
    date = datetime.now().strftime("%Y_%m_%d_%H%M%S")
    safe = _safe_label(label)
    return f"{date}_RvsT_{safe}.dat"

def _build_relation_dat(channel_number: int, label: str | None, buf_points: list[tuple]) -> bytes:
    lines = []
    lines.append(f"# Relation file")
    lines.append(f"# created_at_utc: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"# channel_number: {channel_number}")
    lines.append(f"# label: {label if label is not None else ''}")
    lines.append("# columns: seq, ts_utc_iso, tmxc_k, resistance_ohm")
    for i, (ts, tmxc_k, r_ohm) in enumerate(buf_points):
        ts_iso = ts.isoformat()
        lines.append(f"{i}\t{ts_iso}\t{tmxc_k:.12g}\t{r_ohm:.12g}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _reset_relation_state():

    global RELATION_ACTIVE
    global RELATION_RUN_ID
    global RELATION_CHANNEL
    global RELATION_LABEL
    global RELATION_BUFFER
    global RELATION_RAMP_CONTROLLED
    global RELATION_RAMP_TARGET_MK
    global RELATION_RAMP_RATE_MK_PER_MIN

    RELATION_ACTIVE = False
    RELATION_RUN_ID = None
    RELATION_CHANNEL = None
    RELATION_LABEL = None
    RELATION_BUFFER = []

    RELATION_RAMP_CONTROLLED = False
    RELATION_RAMP_TARGET_MK = None
    RELATION_RAMP_RATE_MK_PER_MIN = None


def _start_relation_common(
    channel_number: int,
    label: str | None = None,
):
    global RELATION_ACTIVE
    global RELATION_RUN_ID
    global RELATION_CHANNEL
    global RELATION_LABEL
    global RELATION_BUFFER
    global RELATION_RAMP_CONTROLLED
    global RELATION_RAMP_TARGET_MK
    global RELATION_RAMP_RATE_MK_PER_MIN

    if RELATION_ACTIVE:
        print("⚠ Ya hay una relation en curso.")
        return None

    try:
        channel_number = int(channel_number)
    except (ValueError, TypeError):
        print("❌ channel_number must be an integer")
        return None

    if channel_number not in SAMPLE_CHANNELS:
        print(
            f"❌ Invalid relation channel: {channel_number}. "
            f"Valid channels are: {SAMPLE_CHANNELS}"
        )
        return None

    if label is not None:
        label = label.strip() or None

    RELATION_ACTIVE = True
    RELATION_CHANNEL = channel_number
    RELATION_LABEL = label
    RELATION_BUFFER = []
    RELATION_RUN_ID = _make_relation_filename(label)

    # A normal relation does not own a Lake Shore ramp.
    RELATION_RAMP_CONTROLLED = False
    RELATION_RAMP_TARGET_MK = None
    RELATION_RAMP_RATE_MK_PER_MIN = None

    print(
        "▶ RELATION iniciada "
        f"file={RELATION_RUN_ID} "
        f"(CH{RELATION_CHANNEL}, label={RELATION_LABEL})"
    )
    return RELATION_RUN_ID


def start_relation(
    channel_number: int,
    label: str | None = None,
):
    return _start_relation_common(
        channel_number=channel_number,
        label=label,
    )

def start_relation_ramp(
    lakeshore      : tuple[LakeShore370, threading.Lock],   
    channel_number : int,
    target_mk      : float,
    rate_k_per_min : float,
    label          : str | None = None,
):
    global RELATION_RAMP_CONTROLLED
    global RELATION_RAMP_TARGET_MK
    global RELATION_RAMP_RATE_MK_PER_MIN

    try:
        target_mk = float(target_mk)
        rate_k_per_min = float(rate_k_per_min)
    except (ValueError, TypeError):
        return None, (
            "Ramp target and rate must be numeric."
        )

    relation_id = _start_relation_common(
        channel_number=channel_number,
        label=label,
    )

    if relation_id is None:
        return None, (
            "Could not start the relation acquisition."
        )

    try:
        with lakeshore[1]:  # Acquire the heater mutex
            ramp_result = lakeshore[0].start_ramp(
                target_mk=target_mk,
                rate_k_per_min=rate_k_per_min,
            )

    except Exception as e:
        _reset_relation_state()

        print(
            "❌ Error starting relation ramp."
            f"\nReason: {e}"
        )
        return None, str(e)

    if not isinstance(ramp_result, dict):
        _reset_relation_state()

        return None, (
            "Lake Shore returned an invalid ramp result."
        )

    if not ramp_result.get("ok"):
        error = ramp_result.get(
            "error",
            "Unknown ramp start error.",
        )

        # Cancel the acquisition state if the ramp
        # could not be started and verified.
        _reset_relation_state()

        print(
            "❌ RELATION cancelled because the "
            f"MXC ramp failed: {error}"
        )
        return None, error

    RELATION_RAMP_CONTROLLED = True
    RELATION_RAMP_TARGET_MK = target_mk
    RELATION_RAMP_RATE_MK_PER_MIN = (
        rate_k_per_min * 1000
    )

    print(
        "↗ MXC ramp associated with RELATION "
        f"file={relation_id}, "
        f"target={target_mk:g} mK, "
        f"rate={rate_k_per_min * 1000:g} mK/min"
    )

    return relation_id, None

def stop_relation(
        lakeshore      : tuple[LakeShore370, threading.Lock],   
    ):

    global RELATION_ACTIVE
    global RELATION_RUN_ID
    global RELATION_CHANNEL
    global RELATION_LABEL
    global RELATION_BUFFER

    if not RELATION_ACTIVE or RELATION_RUN_ID is None:
        print("⚠ No hay relation en curso")
        return None, 0

    file_name = RELATION_RUN_ID
    n_points = len(RELATION_BUFFER)
    channel_number = RELATION_CHANNEL
    label = RELATION_LABEL

    # Debe conservarse antes de reiniciar el estado.
    ramp_controlled = RELATION_RAMP_CONTROLLED
    ramp_stop_error = None

    dat_bytes = _build_relation_dat(
        channel_number,
        label,
        RELATION_BUFFER,
    )

    # Solo una relación que inició la rampa puede detenerla.
    if ramp_controlled:
        try:
            with lakeshore[1]:  # Acquire the heater mutex
                ramp_result = lakeshore[0].stop_ramp()

            if not isinstance(ramp_result, dict):
                ramp_stop_error = (
                    "Lake Shore returned an invalid "
                    "ramp stop result."
                )

            elif not ramp_result.get("ok"):
                ramp_stop_error = ramp_result.get(
                    "error",
                    "Unknown ramp stop error.",
                )

        except Exception as e:
            ramp_stop_error = str(e)

        if ramp_stop_error is None:
            print(
                "↘ MXC ramp stopped by RELATION "
                f"file={file_name}"
            )
        else:
            print(
                "❌ RELATION stopped, but the MXC ramp "
                "could not be stopped."
                f"\nReason: {ramp_stop_error}"
            )

    with get_db_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO relation_files (
                        file_name,
                        channel_number,
                        label,
                        n_points,
                        data
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (file_name) DO UPDATE SET
                        created_at = now(),
                        channel_number = EXCLUDED.channel_number,
                        label = EXCLUDED.label,
                        n_points = EXCLUDED.n_points,
                        data = EXCLUDED.data;
                    """,
                    (
                        file_name,
                        channel_number,
                        label,
                        n_points,
                        psycopg2.Binary(dat_bytes),
                    ),
                )
                conn.commit()

            except psycopg2.Error as e:
                conn.rollback()
                print(
                    "❌ Error guardando relation file "
                    f"{file_name}: {e}"
                )
                # Aunque falle la DB, se cierra la captura.

    _reset_relation_state()

    print(
        "⏹ RELATION finalizada. "
        f"file={file_name} puntos={n_points}"
    )
    return file_name, n_points
