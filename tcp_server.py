import socket
import random
import time
import json
import threading
from lakeshore370 import LakeShore370
from psycopg2.pool import ThreadedConnectionPool
import psycopg2
from contextlib import contextmanager
from default_config import (DEFAULT_PID, CURRENT_RANGE_LIST, DEFAULT_MXC_RESISTANCE_RANGE_SETTINGS, SENSOR_RESISTANCE_RANGE_LIST, DEFAULT_CHANNELS, DEFAULT_EXTRA_CHANNELS, 
                            DEFAULT_CHANNELS_ID, DEFAULT_SETTINGS, DEFAULT_MXC_SETPOINT_MK, DEFAULT_MXC_HEATER_RANGE, DEFAULT_SENSOR_RESISTANCE_SETTINGS, DB_INSERT_INTERVAL, 
                            DEFAULT_CURVES, CURVE_NAMES, SAMPLE_CHANNELS
                            )
import urllib.parse
import re
from datetime import datetime, timezone

ls = LakeShore370()



# Configuration
HOST = '0.0.0.0' # Listen on all network interfaces
PORT = 65432  # Port to listen on

# Mutex to protect the heater power level
heater_mutex = threading.Lock() 

#DB conection params
db_delay = DB_INSERT_INTERVAL
last_db_insert_ts = None
DB_POOL = None
CURRENT_RUN_ID = None

last_sensorValues = None
last_controlParams = None
last_sensorParams = None

RELATION_ACTIVE = False
RELATION_RUN_ID = None
RELATION_CHANNEL = None   
RELATION_LABEL = None     
RELATION_BUFFER = []


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
        print("✅ DB connection pool inicializado")



def close_db_pool():
    global DB_POOL
    if DB_POOL is not None:
        DB_POOL.closeall()
        DB_POOL = None
        print("🔻 DB connection pool cerrado")


@contextmanager
def get_db_conn():
    """
    Maneja el pool de conexiones de la bd
    """
    if DB_POOL is None:
        raise RuntimeError("DB_POOL no inicializado. Llama a init_db_pool() al arrancar.")

    conn = DB_POOL.getconn()
    try:
        yield conn
    finally:
        DB_POOL.putconn(conn)

def start_run(global_run_id: int, description: str | None = None):
    global CURRENT_RUN_ID, last_db_insert_ts

    if CURRENT_RUN_ID is not None:
        print(f"⚠ Ya hay un RUN en curso (RUN_ID = {CURRENT_RUN_ID}). Ciérralo antes con end_run.")
        return

    try:
        global_run_id = int(global_run_id)
    except (ValueError, TypeError):
        print("❌ RUN_ID must be an integer")
        return

    if description is not None:
        description = description.strip()
        if description == "":
            description = None

    with get_db_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO runs (run_id, started_at, description)
                    VALUES (%s, now(), %s)
                    RETURNING run_id;
                    """,
                    (global_run_id, description),
                )
                CURRENT_RUN_ID = cur.fetchone()[0]
                conn.commit()
                last_db_insert_ts = None
                print(f"🏁 RUN {CURRENT_RUN_ID} iniciado")
            except psycopg2.Error as e:
                conn.rollback()
                print(f"❌ Error iniciando RUN {global_run_id}: {e}")
                CURRENT_RUN_ID = None



def end_run():

    global CURRENT_RUN_ID

    if CURRENT_RUN_ID is None:
        print("⚠ No hay RUN en curso")
        return

    with get_db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE runs SET ended_at = now() WHERE run_id = %s;",
                (CURRENT_RUN_ID,),
            )
        conn.commit()

    print(f"🏁 RUN {CURRENT_RUN_ID} finalizado")
    CURRENT_RUN_ID = None


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


def start_relation(channel_number: int, label: str | None = None):
    global RELATION_ACTIVE, RELATION_RUN_ID, RELATION_CHANNEL, RELATION_LABEL, RELATION_BUFFER

    if RELATION_ACTIVE:
        print("⚠ Ya hay una relation en curso.")
        return None

    try:
        channel_number = int(channel_number)
    except (ValueError, TypeError):
        print("❌ channel_number must be an integer")
        return None

    if label is not None:
        label = label.strip() or None

    RELATION_ACTIVE = True
    RELATION_CHANNEL = channel_number
    RELATION_LABEL = label
    RELATION_BUFFER = []

    RELATION_RUN_ID = _make_relation_filename(label)

    print(f"▶ RELATION iniciada file={RELATION_RUN_ID} (CH{RELATION_CHANNEL}, label={RELATION_LABEL})")
    return RELATION_RUN_ID


def stop_relation():
    global RELATION_ACTIVE, RELATION_RUN_ID, RELATION_CHANNEL, RELATION_LABEL, RELATION_BUFFER

    if not RELATION_ACTIVE or RELATION_RUN_ID is None:
        print("⚠ No hay relation en curso")
        return None, 0

    file_name = RELATION_RUN_ID
    n_points = len(RELATION_BUFFER)
    channel_number = RELATION_CHANNEL
    label = RELATION_LABEL

    dat_bytes = _build_relation_dat(channel_number, label, RELATION_BUFFER)

    with get_db_conn() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO relation_files (file_name, channel_number, label, n_points, data)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (file_name) DO UPDATE SET
                        created_at = now(),
                        channel_number = EXCLUDED.channel_number,
                        label = EXCLUDED.label,
                        n_points = EXCLUDED.n_points,
                        data = EXCLUDED.data;
                    """,
                    (file_name, channel_number, label, n_points, psycopg2.Binary(dat_bytes)),
                )
                conn.commit()
            except psycopg2.Error as e:
                conn.rollback()
                print(f"❌ Error guardando relation file {file_name}: {e}")
                # aunque falle DB, paramos captura para no quedar colgados

    RELATION_ACTIVE = False
    RELATION_RUN_ID = None
    RELATION_CHANNEL = None
    RELATION_LABEL = None
    RELATION_BUFFER = []

    print(f"⏹ RELATION finalizada. file={file_name} puntos={n_points}")
    return file_name, n_points




def apply_default_channel_timing(channel: int) -> bool:
    """
    Aplica los tiempos por defecto (dwell y pause) de DEFAULT_SETTINGS
    y también el excitation_mode / excitation_range de
    DEFAULT_SENSOR_RESISTANCE_SETTINGS al canal indicado del LakeShore.
    """
    try:
        config_str = DEFAULT_SETTINGS[channel][0]
        parts = [x.strip() for x in config_str.split(",")]

        dwell_str, pause_str = parts[0], parts[1]
        dwell = float(dwell_str)
        pause = float(pause_str)
    except Exception as e:
        print(f"Error parsing DEFAULT_SETTINGS for channel {channel}: {e}")
        return False

    excitation_mode = None
    excitation_range = None
    try:
        sensor_defaults = DEFAULT_SENSOR_RESISTANCE_SETTINGS.get(channel)
        if sensor_defaults is not None:
            excitation_mode = int(sensor_defaults["excitation_mode"])
            excitation_range = int(sensor_defaults["excitation_range"])
    except Exception as e:
        print(f"Error parsing DEFAULT_SENSOR_RESISTANCE_SETTINGS for channel {channel}: {e}")

    ok = True

    try:
        with heater_mutex:
            ok_dwell = ls.set_channel_dwell_time(dwell, channel=channel)
        if not ok_dwell:
            ok = False
    except Exception as e:
        print(f"Error applying default dwell to channel {channel}: {e}")
        ok = False

    try:
        with heater_mutex:
            ok_pause = ls.set_channel_pause_time(pause, channel=channel)
        if not ok_pause:
            ok = False
    except Exception as e:
        print(f"Error applying default pause to channel {channel}: {e}")
        ok = False

    if excitation_mode is not None and excitation_range is not None:
        try:
            with heater_mutex:
                current_settings = ls.get_sensor_resistance_settings(
                    channel=channel, return_dict=True
                )

            current_settings["excitation_mode"] = excitation_mode
            current_settings["excitation_range"] = excitation_range

            time.sleep(0.1)

            with heater_mutex:
                ok_sensor = ls.set_sensor_resistance_settings(
                    channel=channel, settings=current_settings
                )

            if not ok_sensor:
                ok = False

        except Exception as e:
            print(f"Error applying default excitation settings to channel {channel}: {e}")
            ok = False
    else:
        print(f"(Info) No default excitation settings defined for channel {channel}")

    if ok:
        print(
            f"✅ Applied default settings to channel {channel}: "
            f"dwell={dwell}s, pause={pause}s, "
            f"mode={excitation_mode}, range={excitation_range}"
        )
    else:
        print(f"⚠️ Could not fully apply default settings to channel {channel}")

    print(f"🔧 Channel {channel} initialised to default settings")
    return ok


def apply_default_mxc_settings() -> None:
    """
    Aplica los parámetros por defecto de MXC (PID y ajustes de resistencia).
    """
    try:
        with heater_mutex:
            ls.set_control_parameters(
                P=DEFAULT_PID["P"],
                I=DEFAULT_PID["I"],
                D=DEFAULT_PID["D"],
            )

            ls.set_sensor_resistance_settings(
                channel=6,
                settings=DEFAULT_MXC_RESISTANCE_RANGE_SETTINGS,
            )

            ls.set_channel_setpoint(DEFAULT_MXC_SETPOINT_MK)
            ls.set_control_range(DEFAULT_MXC_HEATER_RANGE)

        print("✅ Applied default MXC settings")
    except Exception as e:
        print(f"Error applying default MXC settings: {e}")


def apply_default_curve_settings(channel: int) -> bool:
    """
    Aplica la curva por defecto (DEFAULT_CURVES) a un canal dado.
    """
    try:
        default_curve = DEFAULT_CURVES[channel]
    except KeyError:
        print(f"(Info) No default curve defined for channel {channel}")
        return False

    try:
        with heater_mutex:
            ls.set_channel_curve(default_curve, channel=channel)
        current_curves[channel] = default_curve
        print(f"✅ Applied default curve {default_curve} to channel {channel}")
        return True
    except Exception as e:
        print(f"Error applying default curve to channel {channel}: {e}")
        return False

# Global variables
clients = [] # List to keep track of connected clients
clients_lock = threading.Lock() # Mutex to protect the clients list

current_temperature_setpoint = 0.0 # Current temperature setpoint for PID controll (in K)
current_heater_power = 0.0 # Current heater power level (0.0 to 1.0)
current_heater_range = 'LOW' # Current heater power range ('LOW', 'MID', 'HIGH')
current_temperature_limit = 30.0 # Current temperature limit (in K)
current_timeout = 300.0 # Current temperature setpoint for control (in s)
current_proportional_gain = 0.0 # Current proportional gain
current_integral_gain = 0.0 # Current integral gain
current_derivative_gain = 0.0 # Current derivative gain
current_mxc_temperature_setpoint = DEFAULT_MXC_SETPOINT_MK # Current MXC temperature setpoint
current_mxc_proportional_gain = DEFAULT_PID['P'] # Current MXC proportional gain
current_mxc_integral_gain = DEFAULT_PID['I'] # Current MXC integral gain
current_mxc_derivative_gain = DEFAULT_PID['D'] # Current MXC derivative gain
current_mxc_resistance_mode = DEFAULT_MXC_RESISTANCE_RANGE_SETTINGS['excitation_mode'] # Current MXC resistance mode
current_mxc_resistance_range = DEFAULT_MXC_RESISTANCE_RANGE_SETTINGS['excitation_range'] # Current MXC resistance range
current_mxc_resistance_autorange = DEFAULT_MXC_RESISTANCE_RANGE_SETTINGS['autorange'] # Current MXC resistance autorange
current_curves = {
    1: DEFAULT_CURVES[1],  # 50K
    2: DEFAULT_CURVES[2],  # 4K
    5: DEFAULT_CURVES[5],  # STILL
    6: DEFAULT_CURVES[6],  # MXC
}

def _is_connected(sock) -> bool:
    try:
        return sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) == 0 and sock.fileno() != -1
    except OSError:
        return False

def _prune_clients():
    removed = 0
    with clients_lock:
        alive = []
        for c, a in clients:
            try:
                # If fileno == -1 the socket is closed; skip it
                if c.fileno() != -1:
                    alive.append((c, a))
                else:
                    removed += 1
            except Exception:
                removed += 1
        clients[:] = alive
    if removed:
        print(f"Pruned {removed} dead subscriber(s)")

# Function to handle incoming commands from clients
def handle_command(command):

    # This function will be called in a separate thread for each client
    # It will process the input commands and control the heater accordingly

    print(f"Received command: {command}")

    global current_mxc_temperature_setpoint
    global current_mxc_proportional_gain
    global current_mxc_integral_gain
    global current_mxc_derivative_gain
    global current_mxc_resistance_autorange
    global current_mxc_resistance_range
    global current_mxc_resistance_mode
    global current_temperature_setpoint
    global current_heater_power
    global current_heater_range
    global current_temperature_limit
    global current_timeout
    global current_proportional_gain
    global current_integral_gain
    global current_derivative_gain

    cmd = command.strip()

    CONTROL_COMMAND_PREFIXES = (
        "set_mxc_temperature_setpoint",
        "set_temperature_setpoint",
        "set_mxc_proportional_gain",
        "set_mxc_integral_gain",
        "set_mxc_derivative_gain",
        "set_mxc_heater_range",
        "set_proportional_gain",
        "set_integral_gain",
        "set_derivative_gain",
        "set_heater_power",
        "set_heater_range",
        "set_temperature_limit",
        "set_timeout",
    )

    if cmd.startswith(CONTROL_COMMAND_PREFIXES):
        try:
            with heater_mutex:
                autoscan_state = ls.get_autoscan()
        except Exception:
            autoscan_state = None

        # autoscan_state = (channel, enabled)
        if autoscan_state and len(autoscan_state) >= 2:
            enabled = int(autoscan_state[1])
        else:
            enabled = 0

        if enabled == 1:
            print("⚠️ Autoscan is ON — disabling automatically before applying control settings")
            with heater_mutex:
                ls.set_autoscan("off")
            time.sleep(0.1)
            print("✅ Autoscan disabled")


    if cmd.startswith("start_relation"):
        parts = cmd.split(":", 2)
        if len(parts) < 2:
            return "❌ Syntax: start_relation:<CHANNEL_NUMBER>[:<LABEL>]"

        try:
            ch = int(parts[1])
        except (ValueError, TypeError):
            return "❌ CHANNEL_NUMBER must be an integer"

        label = None
        if len(parts) == 3:
            label = urllib.parse.unquote(parts[2])

        relation_id = start_relation(ch, label)
        if relation_id is None:
            return "❌ Failed to start relation"

        return f"RELATION_STARTED:{relation_id}"

    elif cmd == "stop_relation":
        relation_id, n = stop_relation()
        if relation_id is None:
            return "❌ No active relation"
        return f"RELATION_STOPPED:{relation_id}:{n}"
    
    elif cmd == "get_relation_status":
        if RELATION_ACTIVE and RELATION_RUN_ID is not None:
            label = RELATION_LABEL if RELATION_LABEL is not None else ""
            ch = RELATION_CHANNEL if RELATION_CHANNEL is not None else -1
            n = len(RELATION_BUFFER)
            return (
                "RELATION_STATUS:ACTIVE:"
                f"{RELATION_RUN_ID}:{ch}:{urllib.parse.quote(label)}:{n}"
            )
        else:
            return "RELATION_STATUS:IDLE"
    

    elif cmd == "get_recent_relations":
        """
        Return latest saved relation .dat files stored in relation_files.
        Output: RECENT_RELATIONS:OK:[{file_name, created_at, channel_number, label, n_points}, ...]
        """
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT file_name, created_at, channel_number, label, n_points
                        FROM relation_files
                        ORDER BY created_at DESC
                        LIMIT 50
                    """)
                    rows = cur.fetchall()

            payload = [
                {
                    "file_name": r[0],
                    "created_at": r[1].isoformat() if r[1] else None,
                    "channel_number": int(r[2]),
                    "label": r[3],
                    "n_points": int(r[4]),
                }
                for r in rows
            ]
            return "RECENT_RELATIONS:OK:" + json.dumps(payload)

        except Exception as e:
            return f"ERROR:get_recent_relations:{e}"


    elif cmd.startswith("get_relation_file:"):
        """
        Fetch and parse a stored relation .dat from relation_files.
        Output: RELATION_FILE:OK:{file_name, created_at, channel_number, label, n_points, points:[{x,y},...]}
        """
        try:
            parts = cmd.split(":", 1)
            if len(parts) != 2 or not parts[1].strip():
                return "RELATION_FILE:ERROR:Syntax. Use get_relation_file:<FILE_NAME>"

            file_name = parts[1].strip()

            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT file_name, created_at, channel_number, label, n_points, data
                        FROM relation_files
                        WHERE file_name = %s
                    """, (file_name,))
                    row = cur.fetchone()

            if not row:
                return f"RELATION_FILE:ERROR:Not found: {file_name}"

            file_name, created_at, ch, label, n_points, data = row

            text = bytes(data).decode("utf-8", errors="ignore")

            # Tu formato real: seq, ts_utc_iso, tmxc_k, resistance_ohm
            points = []
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                cols = line.split()
                if len(cols) < 4:
                    continue
                try:
                    x = float(cols[2])  # tmxc_k
                    y = float(cols[3])  # resistance_ohm
                    points.append({"x": x, "y": y})
                except:
                    continue

            payload = {
                "file_name": file_name,
                "created_at": created_at.isoformat() if created_at else None,
                "channel_number": int(ch),
                "label": label,
                "n_points": int(n_points) if n_points is not None else len(points),
                "points": points,
            }

            return "RELATION_FILE:OK:" + json.dumps(payload)

        except Exception as e:
            return f"RELATION_FILE:ERROR:{e}"


    if cmd.startswith("start_run"):
        parts = cmd.split(":", 2)
        if len(parts) < 2:
            message = "❌ Syntax: start_run:<RUN_ID>[:<DESCRIPTION>]"
            print(message)
            return message

        try:
            global_run_id = int(parts[1])
        except (ValueError, TypeError):
            message = "❌ RUN_ID must be an integer"
            print(message)
            return message

        desc = None
        if len(parts) == 3:
            desc = urllib.parse.unquote(parts[2])   #the description

        start_run(global_run_id, desc)

        if CURRENT_RUN_ID is not None:
            message = f"✅ Run {CURRENT_RUN_ID} started"
        else:
            message = "❌ Failed to start run"

        print(message)
        return message

    elif cmd == "get_recent_runs":
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT run_id, COALESCE(description, '')
                        FROM runs
                        ORDER BY started_at DESC
                        LIMIT 5;
                    """)
                    rows = cur.fetchall()

            payload = [{"run_id": int(r[0]), "description": r[1]} for r in rows]
            return "RECENT_RUNS:OK:" + json.dumps(payload)
        except Exception as e:
            return f"ERROR:get_recent_runs:{e}"

    elif cmd == "end_run":
        end_run()
        return "✅ Run ended"
    
    elif cmd == "get_last_run":
        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT run_id
                        FROM runs
                        WHERE ended_at IS NULL
                        ORDER BY started_at DESC
                        LIMIT 1;
                    """)
                    row = cur.fetchone()

                    if row:
                        active = row[0]
                        message = f"ACTIVE_RUN:{active}"
                        print(f"📡 get_last_run -> {message}")
                        return message

                    cur.execute("SELECT COALESCE(MAX(run_id), 0) FROM runs;")
                    last_run = cur.fetchone()[0]

            message = f"LAST_RUN:{last_run}"
            print(f"📡 get_last_run -> {message}")
            return message

        except Exception as e:
            message = f"ERROR:get_last_run:{e}"
            print(message)
            return message


    elif cmd.startswith("get_run_data"):
        parts = cmd.split(":")
        if len(parts) != 2:
            message = "RUN_DATA:ERROR:Syntax. Use get_run_data:<RUN_ID>"
            print(message)
            return message

        try:
            run_id = int(parts[1])
        except ValueError:
            message = "RUN_DATA:ERROR:RUN_ID must be an integer"
            print(message)
            return message

        CHANNEL_IDS = {
            "MXC":  6,
            "STILL": 5,
            "4K":   2,
            "50K":  1,
        }
        ID_TO_NAME = {v: k for k, v in CHANNEL_IDS.items()}

        try:
            with get_db_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT
                            channel_id,
                            extract(epoch FROM ts) * 1000 AS ts_ms,
                            temperature_k,
                            resistance_ohm,
                            power_w,
                            mxc_setpoint_mk
                        FROM channel_data
                        WHERE run_id = %s
                        ORDER BY ts ASC;
                        """,
                        (run_id,),
                    )
                    rows = cur.fetchall()

            if not rows:
                message = f"RUN_DATA:ERROR:No data found for RUN_ID {run_id}"
                print(message)
                return message

            data_by_channel = {}
            for channel_id, ts_ms, temp, res, power, mxc_sp_mk  in rows:
                ch_name = ID_TO_NAME.get(channel_id, str(channel_id))

                if ch_name not in data_by_channel:
                    data_by_channel[ch_name] = {
                        "timestamps": [],
                        "temperature_k": [],
                        "resistance_ohm": [],
                        "power_w": [],
                        "mxc_setpoint_mk": [],
                    }

                def to_float(x):
                    return float(x) if x is not None else None

                data_by_channel[ch_name]["timestamps"].append(float(ts_ms))
                data_by_channel[ch_name]["temperature_k"].append(to_float(temp))
                data_by_channel[ch_name]["resistance_ohm"].append(to_float(res))
                data_by_channel[ch_name]["power_w"].append(to_float(power))
                data_by_channel[ch_name]["mxc_setpoint_mk"].append(to_float(mxc_sp_mk))

            payload = {
                "run_id": run_id,
                "channels": data_by_channel,
            }

            json_str = json.dumps(payload)
            message = f"RUN_DATA:OK:{json_str}"
            print(f"📡 get_run_data -> {len(rows)} rows returned for RUN {run_id}")
            return message

        except Exception as e:
            message = f"RUN_DATA:ERROR:{e}"
            print(message)
            return message
    
    elif command.startswith("set_temperature_setpoint"):
        # Sintaxis to set the heater power: "set_temperature_setpoint:10" in Kelvin
        try:
            new_temperature_setpoint = float(command.split(":")[-1])
            if 0.0 <= new_temperature_setpoint <= 20.0:
                with heater_mutex:
                    current_temperature_setpoint = new_temperature_setpoint
                message = f"Temperature setpoint to {new_temperature_setpoint}"
                print(message)
            else:
                message = f"Temperature setpoint should be between 0 K and 20 K"
                print(message)
            return message           
        except Exception as e:
            message = f"Error setting new temperature setpoint: {e}"
            print(message)
            return message

    elif command.startswith("set_heater_power"):
        # Sintaxis to set the heater power: "set_heater_power:0.5"
        try:
            new_power = float(command.split(":")[-1])
            if 0.0 <= new_power <= 1.0:
                with heater_mutex:
                    current_heater_power = new_power
                message = f"Set heater power to {new_power}"
                print(message)
            else:
                message = f"Heater power must be between 0.0 and 1.0"
                print(message)
            return message           
        except Exception as e:
            message = f"Error setting heater power: {e}"
            print(message)
            return message
        
    elif command.startswith("set_heater_range"):
        # Sintaxis to set the heater power: "ser_heater_range:LOW"
        try:
            new_range = command.split(":")[-1]
            if new_range in ['LOW', 'MID', 'HIGH']:
                with heater_mutex:
                    current_heater_range = new_range
                message = f"Set heater range to {new_range}"
                print(message)
            else:
                message = f"Heater range must be LOW, MID or HIGH"
                print(message)
            return(message)
        except Exception as e:
            message = f"Error setting heater range: {e}"
            print(message)
            return message
        
    elif command.startswith("set_temperature_limit"):
        # Sintaxis to set the temperature limit: "set_temperature_limit:20" in K
        try:
            new_temperature_limit = float(command.split(":")[-1])
            if new_temperature_limit > 0. and new_temperature_limit <= 30.0:
                with heater_mutex:
                    current_temperature_limit = new_temperature_limit
                message = f"Set temperature limit to {new_temperature_limit} K"
                print(message)
            else:
                message = f"Temperature limit must be positive and lower than 30 K"
                print(message)
            return(message)
        except Exception as e:
            message = f"Error setting temperature limit"
            print(message)
            return message
        
    elif command.startswith("set_timeout"):
        # Sintaxis to set the temperature limit: "set_timeout:300" in s
        try:
            new_timeout = float(command.split(":")[-1])
            if new_timeout > 0.:
                with heater_mutex:
                    current_timeout = new_timeout
                message = f"Set temperature limit to {new_timeout} s"
                print(message)
            else:
                message = f"Controll timeout must be positive"
                print(message)
            return(message)
        except Exception as e:
            message = f"Error setting timeout"
            print(message)
            return message
        
    elif command.startswith("set_proportional_gain"):
        # Sintaxis to set the proportional gain: "set_proportional_gain:0.5"
        try:
            new_gain = float(command.split(":")[-1])
            if new_gain >= 0.0:
                # Set the proportional gain 
                with heater_mutex:
                    current_proportional_gain = new_gain
                message = f"Set proportional gain to {new_gain}"
                print(message)
            else:
                message = f"Proportional gain must be non-negative"
                print(message)
            return message
        except Exception as e:
            print(f"Error setting proportional gain: {e}")

    elif command.startswith("set_integral_gain"):
        # Sintaxis to set the integral gain: "set_integral_gain:0.5"
        try:
            new_gain = float(command.split(":")[-1])
            if new_gain >= 0.0:
                # Set the integral gain
                with heater_mutex:
                    current_integral_gain = new_gain
                message = f"Set integral gain to {new_gain}"
                print(message)
            else:
                message = f"Integral gain must be non-negative"
                print(message)
            return message
        except Exception as e:
            print(f"Error setting integral gain: {e}")

    elif command.startswith("set_derivative_gain"):
        # Sintaxis to set the derivative gain: "set_derivative_gain:0.5"
        try:
            new_gain = float(command.split(":")[-1])
            if new_gain >= 0.0:
                # Set the derivative gain
                with heater_mutex:
                    current_derivative_gain = new_gain
                message = f"Set derivative gain to {new_gain}"
                print(message)
            else:
                message = f"Derivative gain must be non-negative"
                print(message)
            return message
        except Exception as e:
            print(f"Error setting derivative gain: {e}")

    elif command.startswith("set_mxc_temperature_setpoint"):
        # Sintaxis to set the temperature setpoint for MXC: "set_temperature_setpoint_mxc:100"
        try:
            new_temperature_setpoint = float(command.split(":")[-1])
            if 0.0 <= new_temperature_setpoint <= 500.0:
                if (new_temperature_setpoint<10):
                    print("⚠️ Temperature setpoint under 10mK might be useless")
                with heater_mutex:
                    # Mutex protection ensures that only one thread acces the LakeShore device at a time
                    success = ls.set_channel_setpoint(new_temperature_setpoint, channel=6)  # Channel 6 is MXC
                if success:
                    attempts = 5
                    actual_setpoint = None
                    for i in range(attempts):
                        time.sleep(0.2)
                        with heater_mutex: actual_setpoint = ls.get_channel_setpoint(channel=6)
                        if actual_setpoint is not None:
                            break

                    if actual_setpoint is None:
                        message = "❌ Failed to read back MXC setpoint after multiple attempts."
                        print(message)
                        return message

                    actual_setpoint *= 1000  # Convert to mK for consistency
                    
                    if abs(actual_setpoint - new_temperature_setpoint) < 1e-2:
                        current_mxc_temperature_setpoint = new_temperature_setpoint
                        message = f"✅ Setpoint for MXC succesfully set to {new_temperature_setpoint} mK"
                    else:
                        message = (
                            f"⚠️ Mismatch: Tried to set MXC setpoint to {new_temperature_setpoint:.2f} mK, "+
                            f"but the device reports {actual_setpoint:.2f} mK"
                        )
                else:
                    message = f"❌ Failed to set temperature setpoint for MXC"
            else:
                message = f"❌ Temperature setpoint for MXC must be between 10 mK and 500 mK"
            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting temperature setpoint for MXC: {e}"
            print(message)
            return message
    
    elif command.startswith("set_mxc_proportional_gain"):
        # Sintaxis to set the proportional gain for MXC: "set_proportional_gain_mxc:1.0"
        try:
            new_gain = float(command.split(":")[-1])
            if new_gain >= 0.0:
                with heater_mutex:
                    # Mutex protection ensures that only one thread acces the LakeShore device at a time
                    success = ls.set_control_parameters(P=new_gain)
                if success:
                    attempts = 3
                    actual_gain = None
                    for i in range(attempts):
                        time.sleep(0.2)
                        with heater_mutex: actual_gain = ls.get_control_parameters()['P']
                        if actual_gain is not None:
                            break
                    if actual_gain is None:
                        message = "❌ Failed to read back MXC proportional gain after multiple attempts."
                        print(message)
                        return message
                    else:
                        current_mxc_proportional_gain = new_gain
                        message = f"✅ Proportional gain for MXC succesfully set to {new_gain}"
                else:
                    message = f"❌ Failed to set proportional gain for MXC"
            else:
                message = f"❌ Proportional gain must be non-negative"
            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting proportional gain for MXC: {e}"
            print(message)
            return message
    
    elif command.startswith("set_mxc_integral_gain"):
        # Sintaxis to set the integral gain for MXC: "set_integral_gain_mxc:1.0"
        try:
            new_gain = float(command.split(":")[-1])
            if new_gain >= 0.0:
                with heater_mutex:
                    # Mutex protection ensures that only one thread acces the LakeShore device at a time
                    success = ls.set_control_parameters(I=new_gain)
                if success:
                    attemps = 3
                    actual_gain = None
                    for i in range(attemps):
                        time.sleep(0.2)
                        with heater_mutex: actual_gain = ls.get_control_parameters()['I']
                        if actual_gain is not None:
                            break
                    if actual_gain is None:
                        message = "❌ Failed to read back MXC integral gain after multiple attempts."
                        print(message)
                        return message
                    else:
                        current_mxc_integral_gain = new_gain
                        message = f"✅ Integral gain for MXC succesfully set to {new_gain}"
                else:
                    message = f"❌ Failed to set integral gain for MXC"
            else:
                message = f"❌ Integral gain must be non-negative"
            print(message)
            return message
        except Exception as e:
            message = f"❌ Error setting integral gain for MXC: {e}"
            print(message)
            return message
            
    elif command.startswith("set_mxc_derivative_gain"):
        # Sintaxis to set the derivative gain for MXC: "set_derivative_gain_mxc:1.0"
        try:
            new_gain = float(command.split(":")[-1])
            if new_gain >= 0.0:
                with heater_mutex:
                    # Mutex protection ensures that only one thread acces the LakeShore device at a time
                    success = ls.set_control_parameters(D=new_gain)
                if success:
                    attempts = 3
                    actual_gain = None
                    for i in range(attempts):
                        time.sleep(0.2)
                        with heater_mutex: actual_gain = ls.get_control_parameters()['D']
                        if actual_gain is not None:
                            break
                    if actual_gain is None:
                        message = "❌ Failed to read back MXC derivative gain after multiple attempts."
                        print(message)
                        return message
                    else:
                        current_mxc_derivative_gain = new_gain
                        message = f"✅ Derivative gain for MXC succesfully set to {new_gain}"
                else:
                    message = f"❌ Failed to set derivative gain for MXC"
            else:
                message = f"❌ Derivative gain must be non-negative"
            print(message)
            return message  
        except Exception as e:
            message = f"❌ Error setting derivative gain for MXC: {e}"
            print(message)
            return message

    elif command.startswith("set_mxc_heater_range"):
        # Sintaxis to set the heater range for MXC (LakeShore 370): "set_mxc_heater_range:integer" with integer between (0:OFF and 8:100mA).
        # Check CURRENT_RANGE_LIST for the range values.
        try:
            new_range = str(command.split(":")[-1])
            if 0 <= int(new_range) <= 8:
                with heater_mutex:
                    current_range = ls.get_control_range()

                time.sleep(0.1)  # Small delay to ensure communication channel is ready
                with heater_mutex: success = ls.set_control_range(new_range)
                if success:
                    current_mxc_heater_range = new_range
                    message = f"✅ Heater range for MXC succesfully set to {CURRENT_RANGE_LIST[str(new_range)][0]} {CURRENT_RANGE_LIST[str(new_range)][1]}"
                else:
                    message = f"❌ Failed to set heater range for MXC"
                print(message)
                return message
            else:
                message = f"❌ Heater range must be between 0 (OFF) and 8 (100 mA)"
                print(message)
                return message
                
        except Exception as e:
            message = f"❌ Error setting heater range for MXC: {e}"
            print(message)
            return message

    elif command.startswith("set_dwell_mxc"):
        # Sintaxis to set the dwell time for MXC: "set_dwell_mxc:5.0"
        try:
            new_dwell_time = float(command.split(":")[-1])
            if new_dwell_time >= 0.0:
                with heater_mutex: success = ls.set_channel_dwell_time(new_dwell_time, channel=6)  # Channel 6 is MXC
                if success:
                    message = f"✅ Dwell time succesfully set for MXC to {new_dwell_time} s"
                else:
                    message = f"❌ Failed to set dwell time for MXC:"
                print(message)                
            else:
                message += f"Dwell time must be non-negative"
                print(message)
            return message

        except Exception as e:
            message = f"Error setting dwell time for MXC: {e}"
            print(message)
            return message

    elif command.startswith("set_dwell_50k"):
        try:
            new_dwell_time = float(command.split(":")[-1])
            if new_dwell_time >= 0.0:
                with heater_mutex:
                    success = ls.set_channel_dwell_time(new_dwell_time, channel=1) 
                if success:
                    message = f"✅ Dwell time succesfully set for 50K to {new_dwell_time} s"
                else:
                    message = "❌ Failed to set dwell time for 50K"
                print(message)
            else:
                message = "Dwell time must be non-negative"
                print(message)
            return message
        except Exception as e:
            message = f"Error setting dwell time for 50K: {e}"
            print(message)
            return message

    elif command.startswith("set_dwell_4k"):
        try:
            new_dwell_time = float(command.split(":")[-1])
            if new_dwell_time >= 0.0:
                with heater_mutex:
                    success = ls.set_channel_dwell_time(new_dwell_time, channel=2)
                if success:
                    message = f"✅ Dwell time succesfully set for 4K to {new_dwell_time} s"
                else:
                    message = "❌ Failed to set dwell time for 4K"
                print(message)
            else:
                message = "Dwell time must be non-negative"
                print(message)
            return message
        except Exception as e:
            message = f"Error setting dwell time for 4K: {e}"
            print(message)
            return message

    elif command.startswith("set_dwell_still"):
        try:
            new_dwell_time = float(command.split(":")[-1])
            if new_dwell_time >= 0.0:
                with heater_mutex:
                    success = ls.set_channel_dwell_time(new_dwell_time, channel=5) 
                if success:
                    message = f"✅ Dwell time succesfully set for STILL to {new_dwell_time} s"
                else:
                    message = "❌ Failed to set dwell time for STILL"
                print(message)
            else:
                message = "Dwell time must be non-negative"
                print(message)
            return message
        except Exception as e:
            message = f"Error setting dwell time for STILL: {e}"
            print(message)
            return message

    elif command.startswith("set_pause_mxc"):
        # Sintaxis to set the pause time for MXC: "set_pause_mxc:5.0"
        try:
            new_pause_time = float(command.split(":")[-1])
            if new_pause_time >= 0.0:
                with heater_mutex: ls.set_channel_pause_time(new_pause_time, channel=6)  # Channel 6 is MXC
                message = f"✅ Pause time succesfully set for MXC to {new_pause_time} s"
                print(message)
            else:
                message = f"❌ Pause time must be non-negative"
                print(message)
            return message
        except Exception as e:
            message = f"Error setting pause time for MXC: {e}"
            print(message)
            return message
        
    elif command.startswith("set_pause_50k"):
        try:
            new_pause_time = float(command.split(":")[-1])
            if new_pause_time >= 0.0:
                with heater_mutex:
                    success = ls.set_channel_pause_time(new_pause_time, channel=1)
                if success:
                    message = f"✅ Pause time succesfully set for 50k to {new_pause_time} s"
                else:
                    message = "❌ Failed to set pause time for 50K"
                print(message)
            else:
                message = "Pause time must be non-negative"
                print(message)
            return message
        except Exception as e:
            message = f"Error setting pause time for 50K: {e}"
            print(message)
            return message

    elif command.startswith("set_pause_4k"):
        try:
            new_pause_time = float(command.split(":")[-1])
            if new_pause_time >= 0.0:
                with heater_mutex:
                    success = ls.set_channel_pause_time(new_pause_time, channel=2)
                if success:
                    message = f"✅ Pause time succesfully set for 4k to {new_pause_time} s"
                else:
                    message = "❌ Failed to set pause time for 4K"
                print(message)
            else:
                message = "Pause time must be non-negative"
                print(message)
            return message
        except Exception as e:
            message = f"Error setting pause time for 4K: {e}"
            print(message)
            return message

    elif command.startswith("set_pause_still"):
        try:
            new_pause_time = float(command.split(":")[-1])
            if new_pause_time >= 0.0:
                with heater_mutex:
                    success = ls.set_channel_pause_time(new_pause_time, channel=5)
                if success:
                    message = f"✅ Pause time succesfully set for STILL to {new_pause_time} s"
                else:
                    message = "❌ Failed to set pause time for STILL"
                print(message)
            else:
                message = "Pause time must be non-negative"
                print(message)
            return message
        except Exception as e:
            message = f"Error setting pause time for STILL: {e}"
            print(message)
            return message

    elif command.startswith("set_sensor_range_mxc"):
        try:
            new_range = str(command.split(":")[-1])
            if 1<= int(new_range) <= 8:
                with heater_mutex:
                    current_sensor_settings = ls.get_sensor_resistance_settings(channel=6, return_dict=True)  # Channel 6 is MXC
                time.sleep(0.1)  # Small delay to ensure communication channel is ready
                current_sensor_settings['excitation_range'] = new_range
                with heater_mutex:
                    success = ls.set_sensor_resistance_settings(channel=6, settings=current_sensor_settings)  # Channel 6 is MXC
                if success:
                    current_mxc_resistance_range = new_range
                    message = f"✅ Sensor range for MXC succesfully set to {SENSOR_RESISTANCE_RANGE_LIST[str(new_range)][0]} {SENSOR_RESISTANCE_RANGE_LIST[str(new_range)][1]}"
                else:
                    message = f"❌ Failed to set sensor range for MXC"
                print(message)
                return message
        except Exception as e:
            message = f"❌ Error setting sensor range for MXC: {e}"
            print(message)
            return message
    
    elif command.startswith("set_sensor_range_50k"):
        try:
            new_range = str(command.split(":")[-1])
            if 1 <= int(new_range) <= 8:
                with heater_mutex:
                    current_sensor_settings = ls.get_sensor_resistance_settings(channel=1, return_dict=True)
                time.sleep(0.1)
                current_sensor_settings['excitation_range'] = new_range
                with heater_mutex:
                    success = ls.set_sensor_resistance_settings(channel=1, settings=current_sensor_settings)
                if success:
                    message = f"✅ Sensor range for 50K succesfully set to {SENSOR_RESISTANCE_RANGE_LIST[str(new_range)][0]} {SENSOR_RESISTANCE_RANGE_LIST[str(new_range)][1]}"
                else:
                    message = "❌ Failed to set sensor range for 50K"
                print(message)
                return message
        except Exception as e:
            message = f"❌ Error setting sensor range for 50K: {e}"
            print(message)
            return message

    elif command.startswith("set_sensor_range_4k"):
        try:
            new_range = str(command.split(":")[-1])
            if 1 <= int(new_range) <= 8:
                with heater_mutex:
                    current_sensor_settings = ls.get_sensor_resistance_settings(channel=2, return_dict=True)
                time.sleep(0.1)
                current_sensor_settings['excitation_range'] = new_range
                with heater_mutex:
                    success = ls.set_sensor_resistance_settings(channel=2, settings=current_sensor_settings)
                if success:
                    message = f"✅ Sensor range for 4K succesfully set to {SENSOR_RESISTANCE_RANGE_LIST[str(new_range)][0]} {SENSOR_RESISTANCE_RANGE_LIST[str(new_range)][1]}"
                else:
                    message = "❌ Failed to set sensor range for 4K"
                print(message)
                return message
        except Exception as e:
            message = f"❌ Error setting sensor range for 4K: {e}"
            print(message)
            return message

    elif command.startswith("set_sensor_range_still"):
        try:
            new_range = str(command.split(":")[-1])
            if 1 <= int(new_range) <= 8:
                with heater_mutex:
                    current_sensor_settings = ls.get_sensor_resistance_settings(channel=5, return_dict=True)
                time.sleep(0.1)
                current_sensor_settings['excitation_range'] = new_range
                with heater_mutex:
                    success = ls.set_sensor_resistance_settings(channel=5, settings=current_sensor_settings)
                if success:
                    message = f"✅ Sensor range for STILL succesfully set to {SENSOR_RESISTANCE_RANGE_LIST[str(new_range)][0]} {SENSOR_RESISTANCE_RANGE_LIST[str(new_range)][1]}"
                else:
                    message = "❌ Failed to set sensor range for STILL"
                print(message)
                return message
        except Exception as e:
            message = f"❌ Error setting sensor range for STILL: {e}"
            print(message)
            return message

    elif command.startswith("set_channel_mxc"):
        try:
            parts = command.split(":")
            channel_status = int(parts[1])    

            with heater_mutex:
                current_status = int(ls.get_channel_status(channel = 6))

            time.sleep(0.5)  # Small delay to ensure communication channel is ready
            if current_status == channel_status:
                message = f"❌ MXC sensor is already {'On' if bool(current_status) else 'Off'}"
                print(message)
                return message

            attempts = 5
            success = False
            for index in range(attempts):
                if bool(channel_status): 
                    with heater_mutex:
                        success = ls.set_channel_on(6)
                else:
                    with heater_mutex:
                        success = ls.set_channel_off(6)
                            
                time.sleep(0.5) 
                if success: break

            if success:
                message = f"✅ MXC sensor is now {'On' if bool(channel_status) else 'Off'}"
            else:
                message = f"❌ Failed to set MXC sensor {'On' if bool(channel_status) else 'Off'}"
                
            time.sleep(1.0) 
            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting MXC sensor status: {e}"
            print(message)
            time.sleep(1.0) 
            return message

    elif command.startswith("set_channel_50k"):
        try:
            parts = command.split(":")
            channel_status = int(parts[1])    

            with heater_mutex:
                current_status = int(ls.get_channel_status(channel = 1))

            time.sleep(0.5)  # Small delay to ensure communication channel is ready
            if current_status == channel_status:
                message = f"❌ 50k sensor is already {'On' if bool(current_status) else 'Off'}"
                print(message)
                return message

            attempts = 5
            success = False
            for index in range(attempts):
                if bool(channel_status): 
                    with heater_mutex:
                        success = ls.set_channel_on(1)
                else:
                    with heater_mutex:
                        success = ls.set_channel_off(1)
                            
                time.sleep(0.5) 
                if success: break

            if success:
                message = f"✅ 50k sensor is now {'On' if bool(channel_status) else 'Off'}"
            else:
                message = f"❌ Failed to set 50k sensor {'On' if bool(channel_status) else 'Off'}"
                
            time.sleep(1.0) 
            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting 50k sensor status: {e}"
            print(message)
            time.sleep(1.0) 
            return message


    elif command.startswith("set_channel_4k"):
        try:
            parts = command.split(":")
            channel_status = int(parts[1])    

            with heater_mutex:
                current_status = int(ls.get_channel_status(channel=2))

            time.sleep(0.5)
            if current_status == channel_status:
                message = f"❌ 4K sensor is already {'On' if bool(current_status) else 'Off'}"
                print(message)
                return message

            attempts = 5
            success = False
            for _ in range(attempts):
                if bool(channel_status):
                    with heater_mutex:
                        success = ls.set_channel_on(2)
                else:
                    with heater_mutex:
                        success = ls.set_channel_off(2)
                time.sleep(0.5)
                if success:
                    break

            if success:
                message = f"✅ 4K sensor is now {'On' if bool(channel_status) else 'Off'}"
            else:
                message = f"❌ Failed to set 4K sensor {'On' if bool(channel_status) else 'Off'}"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting 4K sensor status: {e}"
            print(message)
            return message

    elif command.startswith("set_channel_still"):
        try:
            parts = command.split(":")
            channel_status = int(parts[1])    

            with heater_mutex:
                current_status = int(ls.get_channel_status(channel=5))

            time.sleep(0.5)
            if current_status == channel_status:
                message = f"❌ STILL sensor is already {'On' if bool(current_status) else 'Off'}"
                print(message)
                return message

            attempts = 5
            success = False
            for _ in range(attempts):
                if bool(channel_status):
                    with heater_mutex:
                        success = ls.set_channel_on(5)
                else:
                    with heater_mutex:
                        success = ls.set_channel_off(5)
                time.sleep(0.5)
                if success:
                    break

            if success:
                message = f"✅ STILL sensor is now {'On' if bool(channel_status) else 'Off'}"
            else:
                message = f"❌ Failed to set STILL sensor {'On' if bool(channel_status) else 'Off'}"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting STILL sensor status: {e}"
            print(message)
            return message


    elif command.startswith("set_channel_9"):
        try:
            parts = command.split(":")
            channel_status = int(parts[1])

            with heater_mutex:
                current_status = int(ls.get_channel_status(channel=9))

            time.sleep(0.5)
            if current_status == channel_status:
                message = f"❌ Channel 9 is already {'On' if bool(current_status) else 'Off'}"
                print(message)
                return message

            attempts = 5
            success = False
            for _ in range(attempts):
                if bool(channel_status):
                    with heater_mutex:
                        success = ls.set_channel_on(9)
                else:
                    with heater_mutex:
                        success = ls.set_channel_off(9)
                time.sleep(0.5)
                if success:
                    break

            if success:
                message = f"✅ Channel 9 is now {'On' if bool(channel_status) else 'Off'}"
            else:
                message = f"❌ Failed to set Channel 9 {'On' if bool(channel_status) else 'Off'}"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting Channel 9 status: {e}"
            print(message)
            return message

    elif command.startswith("set_channel_10"):
        try:
            parts = command.split(":")
            channel_status = int(parts[1])

            with heater_mutex:
                current_status = int(ls.get_channel_status(channel=10))

            time.sleep(0.5)
            if current_status == channel_status:
                message = f"❌ Channel 10 is already {'On' if bool(current_status) else 'Off'}"
                print(message)
                return message

            attempts = 5
            success = False
            for _ in range(attempts):
                if bool(channel_status):
                    with heater_mutex:
                        success = ls.set_channel_on(10)
                else:
                    with heater_mutex:
                        success = ls.set_channel_off(10)
                time.sleep(0.5)
                if success:
                    break

            if success:
                message = f"✅ Channel 10 is now {'On' if bool(channel_status) else 'Off'}"
            else:
                message = f"❌ Failed to set Channel 10 {'On' if bool(channel_status) else 'Off'}"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting Channel 10 status: {e}"
            print(message)
            return message
    
    elif command.startswith("set_channel_11"):
        try:
            parts = command.split(":")
            channel_status = int(parts[1])

            with heater_mutex:
                current_status = int(ls.get_channel_status(channel=11))

            time.sleep(0.5)
            if current_status == channel_status:
                message = f"❌ Channel 11 is already {'On' if bool(current_status) else 'Off'}"
                print(message)
                return message

            attempts = 5
            success = False
            for _ in range(attempts):
                if bool(channel_status):
                    with heater_mutex:
                        success = ls.set_channel_on(11)
                else:
                    with heater_mutex:
                        success = ls.set_channel_off(11)
                time.sleep(0.5)
                if success:
                    break

            if success:
                message = f"✅ Channel 11 is now {'On' if bool(channel_status) else 'Off'}"
            else:
                message = f"❌ Failed to set Channel 11 {'On' if bool(channel_status) else 'Off'}"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting Channel 11 status: {e}"
            print(message)
            return message

    elif command.startswith("set_channel_12"):
        try:
            parts = command.split(":")
            channel_status = int(parts[1])

            with heater_mutex:
                current_status = int(ls.get_channel_status(channel=12))

            time.sleep(0.5)
            if current_status == channel_status:
                message = f"❌ Channel 12 is already {'On' if bool(current_status) else 'Off'}"
                print(message)
                return message

            attempts = 5
            success = False
            for _ in range(attempts):
                if bool(channel_status):
                    with heater_mutex:
                        success = ls.set_channel_on(12)
                else:
                    with heater_mutex:
                        success = ls.set_channel_off(12)
                time.sleep(0.5)
                if success:
                    break

            if success:
                message = f"✅ Channel 12 is now {'On' if bool(channel_status) else 'Off'}"
            else:
                message = f"❌ Failed to set Channel 12 {'On' if bool(channel_status) else 'Off'}"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting Channel 12 status: {e}"
            print(message)
            return message

    elif command.startswith("set_channel_13"):
        try:
            parts = command.split(":")
            channel_status = int(parts[1])

            with heater_mutex:
                current_status = int(ls.get_channel_status(channel=13))

            time.sleep(0.5)
            if current_status == channel_status:
                message = f"❌ Channel 13 is already {'On' if bool(current_status) else 'Off'}"
                print(message)
                return message

            attempts = 5
            success = False
            for _ in range(attempts):
                if bool(channel_status):
                    with heater_mutex:
                        success = ls.set_channel_on(13)
                else:
                    with heater_mutex:
                        success = ls.set_channel_off(13)
                time.sleep(0.5)
                if success:
                    break

            if success:
                message = f"✅ Channel 13 is now {'On' if bool(channel_status) else 'Off'}"
            else:
                message = f"❌ Failed to set Channel 13 {'On' if bool(channel_status) else 'Off'}"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting Channel 13 status: {e}"
            print(message)
            return message

    elif command.startswith("set_channel_14"):
        try:
            parts = command.split(":")
            channel_status = int(parts[1])

            with heater_mutex:
                current_status = int(ls.get_channel_status(channel=14))

            time.sleep(0.5)
            if current_status == channel_status:
                message = f"❌ Channel 14 is already {'On' if bool(current_status) else 'Off'}"
                print(message)
                return message

            attempts = 5
            success = False
            for _ in range(attempts):
                if bool(channel_status):
                    with heater_mutex:
                        success = ls.set_channel_on(14)
                else:
                    with heater_mutex:
                        success = ls.set_channel_off(14)
                time.sleep(0.5)
                if success:
                    break

            if success:
                message = f"✅ Channel 14 is now {'On' if bool(channel_status) else 'Off'}"
            else:
                message = f"❌ Failed to set Channel 14 {'On' if bool(channel_status) else 'Off'}"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting Channel 14 status: {e}"
            print(message)
            return message

    elif command.startswith("set_channel_15"):
        try:
            parts = command.split(":")
            channel_status = int(parts[1])

            with heater_mutex:
                current_status = int(ls.get_channel_status(channel=15))

            time.sleep(0.5)
            if current_status == channel_status:
                message = f"❌ Channel 15 is already {'On' if bool(current_status) else 'Off'}"
                print(message)
                return message

            attempts = 5
            success = False
            for _ in range(attempts):
                if bool(channel_status):
                    with heater_mutex:
                        success = ls.set_channel_on(15)
                else:
                    with heater_mutex:
                        success = ls.set_channel_off(15)
                time.sleep(0.5)
                if success:
                    break

            if success:
                message = f"✅ Channel 15 is now {'On' if bool(channel_status) else 'Off'}"
            else:
                message = f"❌ Failed to set Channel 15 {'On' if bool(channel_status) else 'Off'}"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting Channel 15 status: {e}"
            print(message)
            return message

    elif command == "reset_defaults_mxc":
        try:
            ok_timing = apply_default_channel_timing(6)
            apply_default_mxc_settings()
            ok_curve = apply_default_curve_settings(6)
            if ok_timing and ok_curve:
                message = "✅ MXC channel reset to default settings"
            else:
                message = "⚠️ MXC defaults applied with some errors (check log)"
            print(message)
            return message
        except Exception as e:
            message = f"❌ Error resetting MXC defaults: {e}"
            print(message)
            return message

    elif command == "reset_defaults_50k":
        try:
            ok_timing = apply_default_channel_timing(1)
            ok_curve = apply_default_curve_settings(1)
            if ok_timing and ok_curve:
                message = "✅ 50K channel reset to default settings"
            else:
                message = "⚠️ 50K defaults applied with some errors (check log)"
            print(message)
            return message
        except Exception as e:
            message = f"❌ Error resetting 50K defaults: {e}"
            print(message)
            return message

    elif command == "reset_defaults_4k":
        try:
            ok_timing = apply_default_channel_timing(2)
            ok_curve = apply_default_curve_settings(2)
            if ok_timing and ok_curve:
                message = "✅ 4K channel reset to default settings"
            else:
                message = "⚠️ 4K defaults applied with some errors (check log)"
            print(message)
            return message
        except Exception as e:
            message = f"❌ Error resetting 4K defaults: {e}"
            print(message)
            return message

    elif command == "reset_defaults_still":
        try:
            ok_timing = apply_default_channel_timing(5)
            ok_curve = apply_default_curve_settings(5)
            if ok_timing and ok_curve:
                message = "✅ STILL channel reset to default settings"
            else:
                message = "⚠️ STILL defaults applied with some errors (check log)"
            print(message)
            return message
        except Exception as e:
            message = f"❌ Error resetting STILL defaults: {e}"
            print(message)
            return message

    elif command.startswith("set_sensor_mode_mxc"):
        
        try:
            new_mode = int(command.split(":")[-1])

            if new_mode not in (0, 1):
                message = f"❌ Sensor mode for MXC must be 0 (voltage) or 1 (current)"
                print(message)
                return message

            with heater_mutex:
                current_settings = ls.get_sensor_resistance_settings(channel=6, return_dict=True)

            time.sleep(0.1)

            if not isinstance(current_settings, dict):
                message = "❌ Could not read current sensor settings for MXC"
                print(message)
                return message

            current_settings['excitation_mode'] = new_mode

            with heater_mutex:
                success = ls.set_sensor_resistance_settings(channel=6, settings=current_settings)

            if success:
                current_mxc_resistance_mode = new_mode
                mode_str = "voltage" if new_mode == 0 else "current"
                message = f"✅ Sensor mode for MXC succesfully set to {mode_str}"
            else:
                message = "❌ Failed to set sensor mode for MXC"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting sensor mode for MXC: {e}"
            print(message)
            return message
            
    elif command.startswith("set_sensor_mode_50k"):
        try:
            new_mode = int(command.split(":")[-1])

            if new_mode not in (0, 1):
                message = "❌ Sensor mode for 50K must be 0 (voltage) or 1 (current)"
                print(message)
                return message

            with heater_mutex:
                current_settings = ls.get_sensor_resistance_settings(channel=1, return_dict=True)

            time.sleep(0.1)
            current_settings['excitation_mode'] = new_mode

            with heater_mutex:
                success = ls.set_sensor_resistance_settings(channel=1, settings=current_settings)

            if success:
                mode_str = "voltage" if new_mode == 0 else "current"
                message = f"✅ Sensor mode for 50K succesfully set to {mode_str}"
            else:
                message = "❌ Failed to set sensor mode for 50K"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting sensor mode for 50K: {e}"
            print(message)
            return message

    elif command.startswith("set_sensor_mode_4k"):
        try:
            new_mode = int(command.split(":")[-1])

            if new_mode not in (0, 1):
                message = "❌ Sensor mode for 4K must be 0 (voltage) or 1 (current)"
                print(message)
                return message

            with heater_mutex:
                current_settings = ls.get_sensor_resistance_settings(channel=2, return_dict=True)

            time.sleep(0.1)
            current_settings['excitation_mode'] = new_mode

            with heater_mutex:
                success = ls.set_sensor_resistance_settings(channel=2, settings=current_settings)

            if success:
                mode_str = "voltage" if new_mode == 0 else "current"
                message = f"✅ Sensor mode for 4K succesfully set to {mode_str}"
            else:
                message = "❌ Failed to set sensor mode for 4K"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting sensor mode for 4K: {e}"
            print(message)
            return message

    elif command.startswith("set_sensor_mode_still"):
        try:
            new_mode = int(command.split(":")[-1])

            if new_mode not in (0, 1):
                message = "❌ Sensor mode for STILL must be 0 (voltage) or 1 (current)"
                print(message)
                return message

            with heater_mutex:
                current_settings = ls.get_sensor_resistance_settings(channel=5, return_dict=True)

            time.sleep(0.1)
            current_settings['excitation_mode'] = new_mode

            with heater_mutex:
                success = ls.set_sensor_resistance_settings(channel=5, settings=current_settings)

            if success:
                mode_str = "voltage" if new_mode == 0 else "current"
                message = f"✅ Sensor mode for STILL succesfully set to {mode_str}"
            else:
                message = "❌ Failed to set sensor mode for STILL"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting sensor mode for STILL: {e}"
            print(message)
            return message

    elif command.startswith("set_autorange_mxc"):
        try:
            new_value = int(command.split(":")[-1])

            if new_value not in (0, 1):
                message = "❌ Autorange for MXC must be 0 (OFF) or 1 (ON)"
                print(message)
                return message

            with heater_mutex:
                current_sensor_settings = ls.get_sensor_resistance_settings(channel=6, return_dict=True)

            time.sleep(0.1) 

            current_sensor_settings['autorange'] = new_value

            with heater_mutex:
                success = ls.set_sensor_resistance_settings(channel=6, settings=current_sensor_settings)

            if success:               
                current_mxc_resistance_autorange = new_value
                message = f"✅ Autorange for MXC successfully set to {'ON' if new_value else 'OFF'}"
            else:
                message = "❌ Failed to set autorange for MXC"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting autorange for MXC: {e}"
            print(message)
            return message
        
    elif command.startswith("set_autoscan"):
        try:
            parts = command.split(":")
            if len(parts) < 2:
                message = (
                    "❌ Invalid syntax for set_autoscan. "
                    "Use 'set_autoscan:on' or 'set_autoscan:off'"
                )
                print(message)
                return message

            flag_str = parts[1].strip().lower() #ON, OFF, on or off

            if flag_str not in ("on", "off"):
                message = "❌ Autoscan value must be 'on' or 'off'"
                print(message)
                return message

            if flag_str == "off":
                with heater_mutex:
                    success = ls.set_autoscan("off")

                if success:
                    message = "✅ Autoscan disabled"
                else:
                    message = "❌ Failed to disable autoscan"

                print(message)
                return message

            scan_channels = sorted(set(DEFAULT_CHANNELS) | set(DEFAULT_EXTRA_CHANNELS))  

            enabled_channels = []
            with heater_mutex:
                for ch in scan_channels:
                    try:
                        if int(ls.get_channel_status(channel=ch)) == 1:
                            enabled_channels.append(ch)
                    except Exception as e:
                        print(f"⚠️ Warning checking channel {ch} status: {e}")

            if not enabled_channels:
                message = "❌ Cannot enable autoscan: no channels are ON"
                print(message)
                return message

            start_channel = enabled_channels[0]

            with heater_mutex:
                success = ls.set_autoscan("on", start_channel)

            if success:
                time.sleep(0.1)
                try:
                    with heater_mutex:
                        autoscan_status = ls.get_autoscan()
                except Exception:
                    autoscan_status = None

                if isinstance(autoscan_status, (list, tuple)) and len(autoscan_status) >= 2:
                    ch = int(autoscan_status[0])
                    en = int(autoscan_status[1])
                else:
                    ch = start_channel
                    en = 0

                state_str = "ON" if en == 1 else "OFF"
                message = f"✅ Autoscan {state_str} starting at channel {ch}"
            else:
                message = "❌ Failed to enable autoscan"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting autoscan: {e}"
            print(message)
            return message

    elif command.startswith("set_curve_mxc"):
        try:
            curve = int(command.split(":")[-1])

            if curve not in CURVE_NAMES:
                message = f"❌ Curve {curve} is not defined"
                print(message)
                return message

            with heater_mutex:
                ok = ls.set_channel_curve(curve, channel=6)

            if ok:
                current_curves[6] = curve
                message = f"✅ MXC curve set to {curve} - {CURVE_NAMES[curve]}"
            else:
                message = f"❌ Failed to set MXC curve to {curve}"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting MXC curve: {e}"
            print(message)
            return message
    
    elif command.startswith("set_curve_50k"):
        try:
            curve = int(command.split(":")[-1])

            if curve not in CURVE_NAMES:
                message = f"❌ Curve {curve} is not defined"
                print(message)
                return message

            with heater_mutex:
                ok = ls.set_channel_curve(curve, channel=1)  

            if ok:
                current_curves[1] = curve
                message = f"✅ 50K curve set to {curve} - {CURVE_NAMES[curve]}"
            else:
                message = f"❌ Failed to set 50K curve to {curve}"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting 50K curve: {e}"
            print(message)
            return message

    elif command.startswith("set_curve_4k"):
        try:
            curve = int(command.split(":")[-1])

            if curve not in CURVE_NAMES:
                message = f"❌ Curve {curve} is not defined"
                print(message)
                return message

            with heater_mutex:
                ok = ls.set_channel_curve(curve, channel=2)  

            if ok:
                current_curves[2] = curve
                message = f"✅ 4K curve set to {curve} - {CURVE_NAMES[curve]}"
            else:
                message = f"❌ Failed to set 4K curve to {curve}"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting 4K curve: {e}"
            print(message)
            return message

    elif command.startswith("set_curve_still"):
        try:
            curve = int(command.split(":")[-1])

            if curve not in CURVE_NAMES:
                message = f"❌ Curve {curve} is not defined"
                print(message)
                return message

            with heater_mutex:
                ok = ls.set_channel_curve(curve, channel=5)  

            if ok:
                current_curves[5] = curve
                message = f"✅ STILL curve set to {curve} - {CURVE_NAMES[curve]}"
            else:
                message = f"❌ Failed to set STILL curve to {curve}"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting STILL curve: {e}"
            print(message)
            return message  
    
    elif command.startswith("select_measure_channel:"):
        try:
            parts = command.split(":")
            print('parts', parts)
            if len(parts) != 2:
                return "❌ Syntax: select_measure_channel:<9-15>"

            target = int(parts[1])
            
            print('target', target)
            if target not in SAMPLE_CHANNELS:
                return "❌ Target must be one of 9..15"

            # Shotdown all channel excepts the selected one
            with heater_mutex:
                for ch in SAMPLE_CHANNELS:
                    time.sleep(0.5)
                    if ch == target:
                        ls.set_channel_on(ch)
                    else:
                        ls.set_channel_off(ch)
                    

            return f"✅ Measurement channel selected: CH{target} (others OFF)"

        except Exception as e:
            return f"❌ Error selecting measurement channel: {e}"

    
    else:
        print("Unknown command")
 
            

def start_server():

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind((HOST, PORT))
            server_socket.listen()
            print(f"Server listening on {HOST}:{PORT}")

            # Start the fake temperature sensor in a separate thread
            threading.Thread(target=lakeshore_temperature_sensor, daemon=True).start()

                        
            while True:
                conn, addr = server_socket.accept()
                print(f"Connected by {addr}")
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                # Start a new thread to handle the client
                threading.Thread(target=client_handler, args=(conn, addr), daemon=True).start()

    except KeyboardInterrupt:
        print("\nServer interrupted by user. Closing...")

    except Exception as e:
        print(f"Unhandled exception: {e}")

def client_handler(conn, addr):

    # A first read determines the mode: "SUB" or "CMD"
    try:
        first = conn.recv(1024)
        if not first:
            conn.close()
            return
        text = first.decode('utf-8', errors='ignore').strip()
    except Exception as e:
        print(f"Error receiving first bytes from {addr}: {e}")
        conn.close()
        return

    #---- Subscriber mode
    if text.upper().startswith("SUB"):
        print(f"Client {addr} connected in subscriber mode")
        # Keep writes snappy and detect dead peers sooner
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        try:
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)  # 30 seconds before sending first keepalive
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)  # 10 seconds between keepalive probes
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)  # 3 probes before considering the connection dead
        except OSError as e:
            pass # Ignore if the OS does not support these options
        
        with clients_lock:
            clients.append((conn, addr))
        # The broadcast loop will remove+close on error/peer close
        return

    #---- Command mode
    try:
        command = text
        message = handle_command(command)
        # send a line-delimited response back to the client
        conn.sendall(b"Command received - " + message.encode('utf-8') + b"\n")
    except Exception as e:
        print(f"Error handling command from {addr}: {e}")
        conn.sendall((b"Error handling command " + str(e).encode('utf-8') + b"\n"))
    finally:
        conn.close()
        print(f"Connection with {addr} closed")

def lakeshore_temperature_sensor():

    """
    This function reads the temperature from the LakeShore 370 AC device.

    """
    temperatures = {}
    resistances = {}
    powers = {}

    while True:
        try:
            for index, channel in enumerate(DEFAULT_CHANNELS):
                if ls.get_channel_status(channel):
                    with heater_mutex: temperatures[DEFAULT_CHANNELS_ID[index]] = ls.get_temperature(channel)
                    with heater_mutex: resistances[DEFAULT_CHANNELS_ID[index]] = ls.get_resistance(channel)
                    with heater_mutex: powers[DEFAULT_CHANNELS_ID[index]] = ls.get_power(channel)
                else: 
                    temperatures[DEFAULT_CHANNELS_ID[index]] = "OFF"
                    resistances[DEFAULT_CHANNELS_ID[index]] = "OFF"
                    powers[DEFAULT_CHANNELS_ID[index]] = "OFF"
        except Exception as e:
            print(f"Error reading temperature from LakeShore\nReason: {e}")

        # Which channels are enabled?
        try:
            with heater_mutex: 
                channel_enabled_MXC   = int(ls.get_channel_status(6))  # MXC is channel 6
                channel_enabled_50K   = int(ls.get_channel_status(1))
                channel_enabled_STILL = int(ls.get_channel_status(5))

        except Exception as e:
            print(f"Error reading MXC channel status\nReason: {e}")
            channel_enabled_MXC = 0
        
        try:
            with heater_mutex: 
                tempSetPointMXC = ls.get_temperature_setpoint()  # Channel 6 is MXC
        except Exception as e:
            print(f"Error reading temperature setpoint for MXC from LakeShore\nReason: {e}")
            tempSetPointMXC = None

        try:
            with heater_mutex: LSPID = ls.get_control_parameters()
            proportionalMXC = LSPID['P']
            integralMXC     = LSPID['I']
            derivativeMXC   = LSPID['D']

            time.sleep(0.1) # Small delay to ensure communictation channel is ready
            
            with heater_mutex: 
                heaterRangeMXC = ls.get_control_range()
                heaterOutputMXC = ls.get_heater_output_percent()
            
        except Exception as e:
            print(f"Error reading control parameters from LakeShore\nReason: {e}")
            proportionalMXC = integralMXC = derivativeMXC = None

        try:
            with heater_mutex: resistance_mxc_settings = ls.get_sensor_resistance_settings(channel=6, return_dict=True)  # Channel 6 is MXC
            modeMXC = resistance_mxc_settings['excitation_mode']
            excitationMXC = resistance_mxc_settings['excitation_range']
            autorangeMXC = resistance_mxc_settings['autorange']
        except Exception as e:
            print(f"Error reading sensor resistance settings from LakeShore\nReason: {e}")
            modeMXC = excitationMXC = autorangeMXC = None

        try:
            with heater_mutex:
                resistance_50K_settings = ls.get_sensor_resistance_settings(channel=1, return_dict=True)
                resistance_4K_settings  = ls.get_sensor_resistance_settings(channel=2, return_dict=True)
                resistance_STILL_settings = ls.get_sensor_resistance_settings(channel=5, return_dict=True)

            mode50K = resistance_50K_settings['excitation_mode']
            excitation50K = resistance_50K_settings['excitation_range']

            mode4K = resistance_4K_settings['excitation_mode']
            excitation4K = resistance_4K_settings['excitation_range']

            modeSTILL = resistance_STILL_settings['excitation_mode']
            excitationSTILL = resistance_STILL_settings['excitation_range']

        except Exception as e:
            print(f"Error reading sensor resistance settings for 50K/4K/STILL\nReason: {e}")
            mode50K = excitation50K = None
            mode4K = excitation4K = None
            modeSTILL = excitationSTILL = None

        try:
            with heater_mutex: dwell_times = ls.get_channels_dwell_time(DEFAULT_CHANNELS)
        except Exception as e: 
            print(f"Error reading dwell times from LakeShore\nReason: {e}")
            dwell_times = {channel: None for channel in DEFAULT_CHANNELS_ID}

        try:
            with heater_mutex: pause_times = ls.get_channels_pause_time(DEFAULT_CHANNELS) 
        except Exception as e: 
            print(f"Error reading pause times from LakeShore\nReason: {e}")
            pause_times = {channel: None for channel in DEFAULT_CHANNELS_ID}

        
        try:
            with heater_mutex: autoscan = ls.get_autoscan()
        except Exception as e:
            print(f"Error reading autoscan setting from LakeShore\nReason: {e}")
        
        # --- Normalizing autoscan format
        try: 
            if autoscan is None:
                autoscan = ('0', '0')
            elif isinstance(autoscan, (list, tuple)) and len(autoscan)>=2:
                autoscan =(str(autoscan[0]), str(autoscan[1]))
            else:
                autoscan = ('0', str(autoscan))
        except NameError:
            # Maybe ls.get_autoscan() fails and autoscan is not defined
            autoscan = ('0', '0')
        
        extra_resistances = {}

        for ch in SAMPLE_CHANNELS:
            if ls.get_channel_status(ch):
                try:
                    with heater_mutex:
                        extra_resistances[f"CH{ch}"] = ls.get_resistance(ch)
                except Exception:
                    extra_resistances[f"CH{ch}"] = None
            else:
                extra_resistances[f"CH{ch}"] = "OFF"

        if RELATION_ACTIVE and RELATION_RUN_ID is not None and RELATION_CHANNEL is not None:
            try:
                tmxc_k = temperatures.get("MXC")
                r_key = f"CH{RELATION_CHANNEL}"
                r_ohm = extra_resistances.get(r_key)

                if tmxc_k is not None and r_ohm is not None:
                    RELATION_BUFFER.append((datetime.now(timezone.utc), float(tmxc_k), float(r_ohm)))
            except Exception as e:
                print(f"⚠ Relation sampling error: {e}")
                
        controlParams = {
            'MXCSP'           : tempSetPointMXC,
            'P'               : proportionalMXC,
            'I'               : integralMXC,
            'D'               : derivativeMXC,
            'HR'              : heaterRangeMXC,
            'heaterOutputMXC' : heaterOutputMXC,
        }

        sensorParams = {
            'sensor_mode'       : modeMXC,
            'sensor_range'      : excitationMXC,
            'sensor_autorange'  : autorangeMXC,
            'sensor_mode_50K'   : mode50K,
            'sensor_range_50K'  : excitation50K,
            'sensor_mode_4K'    : mode4K,
            'sensor_range_4K'   : excitation4K,
            'sensor_mode_STILL' : modeSTILL,
            'sensor_range_STILL': excitationSTILL,
            'dwell_times'       : dwell_times,
            'pause_times'       : pause_times,
            'autoscan'          : autoscan,
            'enabledMXC'        : channel_enabled_MXC,
            'curve_MXC'         : current_curves[6],
            'curve_50K'         : current_curves[1],
            'curve_4K'          : current_curves[2],
            'curve_STILL'       : current_curves[5]
        }

        sensorValues = {
            'temperatures'      : temperatures,
            'resistances'       : resistances,
            'powers'            : powers,
            'extra_resistances' : extra_resistances,
        }
        
        global last_sensorValues, last_controlParams, last_sensorParams
        last_sensorValues = sensorValues
        last_controlParams = controlParams
        last_sensorParams = sensorParams

        try:
            broadcast_temperature(sensorValues, controlParams, sensorParams)
        except Exception as e:
            print(f"Error broadcasting temperature data: {e}")

        maybe_insert_measurements()
        
        time.sleep(1)


def broadcast_temperature(sensorValues, controlParams, sensorParams):

    temperatures      = sensorValues['temperatures']
    resistances       = sensorValues['resistances']
    powers            = sensorValues['powers']
    extra_resistances = sensorValues['extra_resistances']
    
    dwell_times = sensorParams['dwell_times']
    pause_times = sensorParams['pause_times']

    # Send the sensor data to all connected clients
    global current_mxc_temperature_setpoint
    global current_proportionalMXC
    global current_integralMXC
    global current_derivativeMXC
    global current_ls_heater_range

    global current_mxc_resistance_mode
    global current_mxc_resistance_range
    global current_mxc_resistance_autorange
    global current_dwell_time
    global current_pause_time
    global autoscan

    global current_temperature_setpoint
    global current_heater_power
    global current_timeout
    global current_proportional_gain
    global current_integral_gain
    global current_derivative_gain
    

    print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()), "Broadcasting temperatures:")

    for index, channel in enumerate(DEFAULT_CHANNELS):
        if temperatures[DEFAULT_CHANNELS_ID[index]] != "OFF":
            channel_temperature = temperatures[DEFAULT_CHANNELS_ID[index]]
            formated_temperature = f"{channel_temperature if channel_temperature > 1.0 else channel_temperature * 1000}"
            formated_units = "K" if channel_temperature > 1.0 else "mK"
            print(f"Channel {DEFAULT_CHANNELS_ID[index]} Temperature: {formated_temperature} {formated_units}")

    for index, channel in enumerate(list(extra_resistances.keys())):
        if extra_resistances[channel] != "OFF":
            formated_resistance = extra_resistances[channel]
            print(f"Channel {channel} Resistance: {formated_resistance} Ohms")

    if CURRENT_RANGE_LIST[controlParams['HR']][0] != 0:
        print(f"MXC Temperature Setpoint: {controlParams['MXCSP']} K")
        print(f"Heater Range MXC: {controlParams['HR']} ({CURRENT_RANGE_LIST[controlParams['HR']][0]} {CURRENT_RANGE_LIST[controlParams['HR']][1]})")

    print("Autoscan is set " + ("ON" if str(sensorParams['autoscan'][1]) == '1' else "OFF"))
    if sensorParams['autoscan'][1] == '1': print(f"Scanning channel {int(sensorParams['autoscan'][0])}")
    
    if not int(sensorParams['sensor_mode']): print(f"Sensor Mode MXC: voltage ({SENSOR_RESISTANCE_RANGE_LIST[sensorParams['sensor_range']][0]} {SENSOR_RESISTANCE_RANGE_LIST[sensorParams['sensor_range']][1]})")
    else: print(f"Sensor Mode MXC: current ({SENSOR_RESISTANCE_RANGE_LIST[sensorParams['sensor_range']][2]} {SENSOR_RESISTANCE_RANGE_LIST[sensorParams['sensor_range']][3]})")

    try:
        message = (
                    f"50K: {temperatures['50K']}," +
                    f"4K: {temperatures['4K']}," +
                    f"STILL: {temperatures['STILL']}," +
                    f"MXC: {temperatures['MXC']}," +
                    f"MXCSP: {controlParams['MXCSP']}," +
                    f"MXCP: {controlParams['P']}," +
                    f"MXCI: {controlParams['I']}," +
                    f"MXCD: {controlParams['D']}," +
                    f"MXCHR: {controlParams['HR']}," +
                    f"dwellMXC: {dwell_times['MXC']}," +
                    f"pauseMXC: {pause_times['MXC']}," +
                    f"modeMXC: {sensorParams['sensor_mode']}," +
                    f"rangeMXC: {sensorParams['sensor_range']}," +
                    f"autorangeMXC: {sensorParams['sensor_autorange']}," +
                    f"dwell_50K: {dwell_times['50K']}," +
                    f"dwell_4K: {dwell_times['4K']}," +
                    f"dwell_STILL: {dwell_times['STILL']}," +
                    f"pause_50K: {pause_times['50K']}," +
                    f"pause_4K: {pause_times['4K']}," +
                    f"pause_STILL: {pause_times['STILL']}," +
                    f"setpoint: {current_temperature_setpoint}," +
                    f"heater_power:{current_heater_power}," +
                    f"heater_range:{current_heater_range}," +
                    f"temperature_limit:{current_temperature_limit}," +
                    f"timeout:{current_timeout}," + 
                    f"proportional_gain:{current_proportional_gain}," +
                    f"integral_gain:{current_integral_gain}," +
                    f"derivative_gain:{current_derivative_gain}," +
                    f"autoscan:{sensorParams['autoscan'][1]}," +  
                    f"R50K: {resistances['50K']}," +
                    f"R4K: {resistances['4K']}," +
                    f"RSTILL: {resistances['STILL']}," +
                    f"RMXC: {resistances['MXC']}," +
                    f"P50K: {powers['50K']}," +
                    f"P4K: {powers['4K']}," +
                    f"PSTILL: {powers['STILL']}," +
                    f"PMXC: {powers['MXC']}," +
                    f"enabledMXC: {sensorParams['enabledMXC']}," +
                    f"enabled50K: {int(ls.get_channel_status(1))}," +
                    f"enabled4K: {int(ls.get_channel_status(2))}," +
                    f"enabledSTILL: {int(ls.get_channel_status(5))}," +
                    f"mode50K: {sensorParams['sensor_mode_50K']}," +
                    f"range50K: {sensorParams['sensor_range_50K']}," +
                    f"mode4K: {sensorParams['sensor_mode_4K']}," +
                    f"range4K: {sensorParams['sensor_range_4K']}," +
                    f"modeSTILL: {sensorParams['sensor_mode_STILL']}," +
                    f"rangeSTILL: {sensorParams['sensor_range_STILL']}," +
                    f"curveMXC: {sensorParams['curve_MXC']}," +
                    f"curve50K: {sensorParams['curve_50K']}," +
                    f"curve4K: {sensorParams['curve_4K']}," +
                    f"curveSTILL: {sensorParams['curve_STILL']}," +
                    f"heaterOutputMXC: {controlParams['heaterOutputMXC']}," +
                    f"RUNID: {CURRENT_RUN_ID}," +
                    f"RCH9: {extra_resistances.get('CH9')}," +
                    f"RCH10: {extra_resistances.get('CH10')}," +
                    f"RCH11: {extra_resistances.get('CH11')}," +
                    f"RCH12: {extra_resistances.get('CH12')}," +
                    f"RCH13: {extra_resistances.get('CH13')}," +
                    f"RCH14: {extra_resistances.get('CH14')}," +
                    f"RCH15: {extra_resistances.get('CH15')}," +
                    f"enabledCH9: {int(ls.get_channel_status(9))}," +
                    f"enabledCH10: {int(ls.get_channel_status(10))}," +
                    f"enabledCH11: {int(ls.get_channel_status(11))}," +
                    f"enabledCH12: {int(ls.get_channel_status(12))}," +
                    f"enabledCH13: {int(ls.get_channel_status(13))}," +
                    f"enabledCH14: {int(ls.get_channel_status(14))}," +
                    f"enabledCH15: {int(ls.get_channel_status(15))}\n"
                    ).encode('utf-8')
        
    except Exception as e:
        print(f"Error formatting broadcast message: {e}")
    
    _prune_clients() # clean up dead clients

    to_remove = []
    with clients_lock:
        target_list = list(clients)

    for sock, addr in target_list:
        try:
            sock.sendall(message)
        except Exception as e:
            # Don't call getpeername() here—socket may be gone
            print(f"Error broadcasting data to client {addr}: {e}")
            to_remove.append((sock, addr))

    if to_remove:
        with clients_lock:
            for dead in to_remove:
                try:
                    clients.remove(dead)
                except ValueError:
                    pass
                try:
                    dead[0].close()
                except Exception:
                    pass



def maybe_insert_measurements():
    global last_db_insert_ts
    global last_sensorValues, last_controlParams, last_sensorParams

    now = datetime.now(timezone.utc)
    if last_db_insert_ts is not None:
        if now - last_db_insert_ts < db_delay:
            return  

    last_db_insert_ts = now

    run_id = CURRENT_RUN_ID
    if run_id is None:
        return

    CHANNEL_IDS = {
        "MXC":  6,
        "STILL": 5,
        "4K":   2,
        "50K":  1,
    }

    CURVES_BY_NAME = {
        "MXC":   current_curves[6],
        "STILL": current_curves[5],
        "4K":    current_curves[2],
        "50K":   current_curves[1],
    }

    if (
        last_sensorValues is None
        or last_controlParams is None
        or last_sensorParams is None
    ):
        print("Skipping DB insert: no sensor data available yet")
        return

    temperatures = last_sensorValues["temperatures"]
    resistances  = last_sensorValues["resistances"]
    powers       = last_sensorValues["powers"]

    dwell_times  = last_sensorParams["dwell_times"]
    pause_times  = last_sensorParams["pause_times"]

    mxc_sp  = last_controlParams["MXCSP"]
    mxc_p   = last_controlParams["P"]
    mxc_i   = last_controlParams["I"]
    mxc_d   = last_controlParams["D"]
    mxc_hr  = last_controlParams["HR"]

    per_channel = [
        (
            "MXC",
            temperatures["MXC"],
            resistances["MXC"],
            powers["MXC"],
            dwell_times["MXC"],
            pause_times["MXC"],
            last_sensorParams["sensor_mode"],       
            last_sensorParams["sensor_range"],      
            last_sensorParams["sensor_autorange"],
            bool(last_sensorParams["enabledMXC"]),        

            mxc_sp, mxc_p, mxc_i, mxc_d, mxc_hr,
            CURVES_BY_NAME["MXC"],
        ),
        (
            "STILL",
            temperatures["STILL"],
            resistances["STILL"],
            powers["STILL"],
            dwell_times["STILL"],
            pause_times["STILL"],
            last_sensorParams["sensor_mode_STILL"],
            last_sensorParams["sensor_range_STILL"],
            None,
            bool(ls.get_channel_status(5)),          

            None, None, None, None, None,
            CURVES_BY_NAME["STILL"],          
        ),
        (
            "4K",
            temperatures["4K"],
            resistances["4K"],
            powers["4K"],
            dwell_times["4K"],
            pause_times["4K"],
            last_sensorParams["sensor_mode_4K"],
            last_sensorParams["sensor_range_4K"],
            None,
            bool(ls.get_channel_status(2)),         

            None, None, None, None, None,
            CURVES_BY_NAME["4K"],
        ),
        (
            "50K",
            temperatures["50K"],
            resistances["50K"],
            powers["50K"],
            dwell_times["50K"],
            pause_times["50K"],
            last_sensorParams["sensor_mode_50K"],
            last_sensorParams["sensor_range_50K"],
            None,
            bool(ls.get_channel_status(1)),         

            None, None, None, None, None,
            CURVES_BY_NAME["50K"],
        ),
    ]

    with get_db_conn() as conn:
        with conn.cursor() as cur:
            for (
                name, temp_k, res_ohm, power_w,
                dwell_s, pause_s,
                mode, range_, autorange,
                enabled,
                mxc_sp, mxc_p, mxc_i, mxc_d, mxc_hr,
                curve_id
            ) in per_channel:

                if not enabled:
                    continue

                channel_id = CHANNEL_IDS[name]

                cur.execute(
                    """
                    INSERT INTO channel_data (
                        run_id, channel_id, ts,
                        temperature_k,
                        resistance_ohm,
                        power_w,
                        dwell_s, pause_s,
                        excitation_mode,
                        excitation_range,
                        autorange,
                        enabled,
                        mxc_setpoint_mk,
                        mxc_p_gain,
                        mxc_i_gain,
                        mxc_d_gain,
                        mxc_heater_range,
                        curve
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s,
                        %s, %s, %s, %s, %s,
                        %s
                    )
                    """,
                    (
                        run_id, channel_id, now,
                        temp_k,
                        res_ohm,
                        power_w,
                        dwell_s,
                        pause_s,
                        mode,
                        range_,
                        autorange,
                        enabled,
                        mxc_sp,
                        mxc_p,
                        mxc_i,
                        mxc_d,
                        mxc_hr,
                        curve_id
                    ),
                )
        conn.commit()



if __name__ == "__main__":
    try:
        init_db_pool()
        start_server()
    finally:
        close_db_pool()