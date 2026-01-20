from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import socket
import threading
import time
import io
import base64
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import matplotlib.pyplot as plt


# Configuration for the TCP socket server
TCP_HOST = '192.168.38.3'      #Replace with the Raspberry Pi's IP address: 192.168.38.3
TCP_PORT = 65432 

# Global variables to store the latest temperature data
current_50K = None
current_4K = None
current_STILL = None
current_MXC = None
current_mxc_temperature_setpoint = None
current_mxc_proportional_gain = None
current_mxc_integral_gain = None
current_mxc_derivative_gain = None
current_mxc_heater_range = None
current_dwell_MXC = None
current_pause_MXC = None
current_excitation_mode_MXC = None
current_excitation_range_MXC = None
current_excitation_autorange_MXC = None
current_excitation_mode_50K = None
current_excitation_range_50K = None
current_excitation_mode_4K = None
current_excitation_range_4K = None
current_excitation_mode_STILL = None
current_excitation_range_STILL = None
current_dwell_50K = None
current_dwell_4K = None
current_dwell_STILL = None
current_pause_50K = None
current_pause_4K = None
current_pause_STILL = None
current_temperature_setpoint = None
current_heater_power = None
current_heater_range = None
current_temperature_limit = None
current_timeout = None
current_proportional_gain = None
current_integral_gain = None
current_derivative_gain = None
current_R50K = None
current_R4K = None
current_RSTILL = None
current_RMXC = None
current_P50K = None
current_P4K = None
current_PSTILL = None
current_PMXC = None
current_enabled_MXC = None
current_enabled_50K = None
current_enabled_4K = None
current_enabled_STILL = None
current_autoscan = "off"
current_curve_MXC = None
current_curve_50K = None
current_curve_4K = None
current_curve_STILL = None
current_heater_output_MXC = None
current_RUNID = None
current_RCH9  = None
current_RCH10 = None
current_RCH12 = None
current_RCH13 = None
current_RCH14 = None

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            with open('/home/SuperTech/TCP_SERVER_CAB/index.html', 'rb') as file:       #C:\CuartoInformatica\Practicas_CAB\TCP_SERVER\index.html
                self.wfile.write(file.read())

        elif path == '/get-data':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            response = json.dumps({"50K": current_50K,
                                   "4K": current_4K,
                                   "STILL": current_STILL,
                                   "MXC": current_MXC,
                                   "MXCSP": current_mxc_temperature_setpoint,
                                   "MXCP": current_mxc_proportional_gain,
                                   "MXCI": current_mxc_integral_gain,
                                   "MXCD": current_mxc_derivative_gain,
                                   "MXCHR": current_mxc_heater_range,
                                   "dwellMXC": current_dwell_MXC,
                                   "pauseMXC": current_pause_MXC,
                                   "modeMXC": current_excitation_mode_MXC,
                                   "rangeMXC": current_excitation_range_MXC,
                                   "autorangeMXC": current_excitation_autorange_MXC,
                                   "dwell50K": current_dwell_50K,
                                   "dwell4K": current_dwell_4K,
                                   "dwellSTILL": current_dwell_STILL,
                                   "pause50K": current_pause_50K,
                                   "pause4K": current_pause_4K,
                                   "pauseSTILL": current_pause_STILL,
                                   "setpoint": current_temperature_setpoint,
                                   "heater_power": current_heater_power,
                                   "heater_range": current_heater_range,
                                   "temperature_limit": current_temperature_limit,
                                   "timeout": current_timeout,
                                   "proportional_gain": current_proportional_gain,
                                   "integral_gain": current_integral_gain,
                                   "derivative_gain": current_derivative_gain,
                                   "R50K": current_R50K,
                                   "R4K": current_R4K,
                                   "RSTILL": current_RSTILL,
                                   "RMXC": current_RMXC,
                                   "PMXC": current_PMXC,
                                   "enabledMXC": current_enabled_MXC,
                                   "enabled50K": current_enabled_50K,
                                   "enabled4K": current_enabled_4K,
                                   "enabledSTILL": current_enabled_STILL,
                                   "autoscan": current_autoscan,
                                   "mode50K": current_excitation_mode_50K,
                                   "range50K": current_excitation_range_50K,
                                   "mode4K": current_excitation_mode_4K,
                                   "range4K": current_excitation_range_4K,
                                   "modeSTILL": current_excitation_mode_STILL,
                                   "rangeSTILL": current_excitation_range_STILL,
                                   "curveMXC": current_curve_MXC,
                                   "curve50K": current_curve_50K,
                                   "curve4K": current_curve_4K,
                                   "curveSTILL": current_curve_STILL,      
                                   "heaterOutputMXC": current_heater_output_MXC,    
                                   "runID": current_RUNID,      
                                   "RCH9":  current_RCH9,
                                    "RCH10": current_RCH10,
                                    "RCH12": current_RCH12,
                                    "RCH13": current_RCH13,
                                    "RCH14": current_RCH14,
                                   })
                                   

            self.wfile.write(response.encode('utf-8'))

        elif path == '/plot_run':
            run_vals = query.get("run_id")
            if not run_vals:
                self.send_error(400, "Missing run_id")
                return

            try:
                run_id = int(run_vals[0])
            except ValueError:
                self.send_error(400, "Invalid run_id")
                return

            run_payload = self.get_run_payload(run_id)
            if run_payload is None:
                self.send_error(500, "Could not retrieve RUN_DATA")
                return

            html = self.render_run_plot_html(run_payload)

            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode('utf-8'))

        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == '/send-command':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8'))
            command = data.get('command')
            print(command)
            # Forward the command to the TCP socket server
            response = self.send_command_to_tcp_server(command)
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": response}).encode('utf-8'))
        else:
            self.send_error(404)

    def send_command_to_tcp_server(self, command):
        """
        This function creates a new TCP socket called command_socket to send
        the commands to the TCP server. In this way, the continuous sensor
        data transmission from the TCP server to the HTTP server is not interrupted.
        Each POST /send-command request creates a short-lived socket connection
        to send the command and receive a response.
        """

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as command_socket:
                command_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                command_socket.settimeout(10)
                command_socket.connect((TCP_HOST, TCP_PORT))
                command_socket.sendall(command.encode('utf-8'))

                # Read exactly one line (newline-delimited by the TCP server)
                buf = b""
                while b"\n" not in buf:
                    chunk = command_socket.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                response = buf.decode('utf-8', errors='ignore').strip()

            return response or "Error: empty reply from TCP server"
        except Exception as e:
            print(f"Error sending command to TCP server: {e}")
            return f"Error: {str(e)}"
        
    def get_run_payload(self, run_id: int):
        """
        Envía 'get_run_data:RUN_ID' al servidor TCP y extrae el JSON
        después de 'RUN_DATA:OK:'.
        """
        cmd = f"get_run_data:{run_id}"
        raw = self.send_command_to_tcp_server(cmd)
        print("RAW RUN_DATA response:", repr(raw))

        prefix = "RUN_DATA:"
        idx = raw.find(prefix)
        if idx == -1:
            print("RUN_DATA JSON not found in response")
            return None

        part = raw[idx + len(prefix):].strip()

        if part.startswith("ERROR:"):
            print("RUN_DATA error from TCP:", part)
            return None

        ok_prefix = "OK:"
        if part.startswith(ok_prefix):
            json_str = part[len(ok_prefix):].strip()
        else:
            json_str = part

        end = json_str.rfind("}")
        if end != -1:
            json_str = json_str[:end + 1]

        try:
            payload = json.loads(json_str)
            return payload
        except Exception as e:
            print("Error decoding RUN_DATA JSON:", e)
            print("JSON candidate was:", json_str)
            return None
        
    def _parse_ts(self, ts):
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts / 1000.0)
        if isinstance(ts, str):
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                try:
                    return datetime.fromtimestamp(float(ts))
                except Exception:
                    raise ValueError(f"Unsupported timestamp format: {ts!r}")
        raise ValueError(f"Unsupported timestamp type: {type(ts)}")

    def render_run_plot_html(self, run_payload: dict) -> str:
        import io, base64
        import matplotlib.pyplot as plt

        channels = ["50K", "4K", "STILL", "MXC"]
        images = {}  

        for ch_name in channels:
            ch = run_payload.get("channels", {}).get(ch_name)

            fig = plt.figure(figsize=(6, 3.2))
            ax = fig.add_subplot(111)   

            if (not ch or
                not isinstance(ch.get("timestamps"), list) or
                not isinstance(ch.get("temperature_k"), list) or
                len(ch["timestamps"]) == 0):

                ax.set_title(ch_name)
                ax.set_xlabel("Tiempo (s)")
                ax.set_ylabel("Temperatura (K)")
                ax.set_xlim(0, 1)
                ax.set_ylim(0, 1)
                ax.grid(True, alpha=0.3)

            else:
                ts_list = ch["timestamps"]
                temps = ch["temperature_k"]

                t0 = self._parse_ts(ts_list[0])
                t_rel = [(self._parse_ts(t) - t0).total_seconds() for t in ts_list]

                ax.plot(t_rel, temps, label="T")

                if ch_name == "MXC":
                    sp_vals = ch.get("mxc_setpoint_mk")
                    if isinstance(sp_vals, list) and len(sp_vals) == len(t_rel):
                        sp_k = [float(v) if v is not None else None for v in sp_vals]
                        ax.plot(t_rel, sp_k, linestyle="--", color="red", linewidth=1.5, label="Setpoint")

                ax.set_title(ch_name)
                ax.set_xlabel("Tiempo (s)")
                ax.set_ylabel("Temperatura (K)")
                ax.legend(loc="best")

            buf = io.BytesIO()
            fig.tight_layout()
            fig.savefig(buf, format="png", bbox_inches="tight")
            plt.close(fig)
            buf.seek(0)
            images[ch_name] = base64.b64encode(buf.read()).decode("ascii")

        run_id = run_payload.get("run_id")

        html = f"""<!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>RUN {run_id} – gráficas</title>
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <style>
        body {{
        margin: 0;
        background: #111;
        color: #fff;
        font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
        }}
        .wrap {{
        max-width: 1200px;
        margin: 0 auto;
        padding: 18px;
        text-align: center;
        }}
        .grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 14px;
        margin-top: 14px;
        }}
        .card {{
        background: #161616;
        border: 1px solid #2a2a2a;
        border-radius: 12px;
        padding: 10px;
        }}
        .card h3 {{
        margin: 8px 0 10px 0;
        font-size: 16px;
        font-weight: 700;
        color: #e5e7eb;
        }}
        .plot {{
        width: 100%;
        height: auto;
        border-radius: 8px;
        border: 1px solid #2a2a2a;
        cursor: zoom-in;
        user-select: none;
        }}
        /* Modal fullscreen */
        .modal {{
        position: fixed;
        inset: 0;
        display: none;
        align-items: center;
        justify-content: center;
        background: rgba(0,0,0,0.92);
        z-index: 9999;
        padding: 18px;
        }}
        .modal.open {{
        display: flex;
        }}
        .modal-inner {{
        width: min(98vw, 1600px);
        height: min(92vh, 1000px);
        display: flex;
        flex-direction: column;
        gap: 10px;
        }}
        .modal-header {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
        }}
        .modal-title {{
        font-weight: 800;
        text-align: left;
        color: #f3f4f6;
        }}
        .close-btn {{
        background: #ef4444;
        border: none;
        color: white;
        padding: 10px 14px;
        border-radius: 10px;
        cursor: pointer;
        font-weight: 800;
        }}
        .close-btn:hover {{ filter: brightness(0.95); }}
        .modal-img {{
        flex: 1;
        width: 100%;
        height: 100%;
        object-fit: contain;
        border-radius: 12px;
        border: 1px solid #2a2a2a;
        background: #0b0b0b;
        cursor: zoom-out;
        }}
        @media (max-width: 900px) {{
        .grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
    </head>
    <body>
    <div class="wrap">
        <h1 style="margin:0;">RUN {run_id}</h1>
        <p style="margin:8px 0 0 0; color:#cbd5e1;">
        Gráficas de los canales MXC, 50K, 4K y STILL para el RUN {run_id}.
        </p>

        <div class="grid">
        {"".join([f'''
        <div class="card">
            <h3>{ch}</h3>
            <img class="plot"
                src="data:image/png;base64,{images[ch]}"
                alt="Plot {ch}"
                data-title="{ch}"
                onclick="openModal(this)" />
        </div>
        ''' for ch in channels])}
        </div>
    </div>

    <div id="modal" class="modal" onclick="closeModal(event)">
        <div class="modal-inner" onclick="event.stopPropagation()">
        <div class="modal-header">
            <div id="modalTitle" class="modal-title"></div>
            <button class="close-btn" onclick="closeModal()">Cerrar</button>
        </div>
        <img id="modalImg" class="modal-img" src="" alt="Full plot" onclick="closeModal()" />
        </div>
    </div>

    <script>
        function openModal(imgEl) {{
        const modal = document.getElementById("modal");
        const modalImg = document.getElementById("modalImg");
        const modalTitle = document.getElementById("modalTitle");

        modalImg.src = imgEl.src;
        modalTitle.textContent = "RUN {run_id} — " + (imgEl.dataset.title || "");
        modal.classList.add("open");
        }}

        function closeModal(ev) {{
        const modal = document.getElementById("modal");
        modal.classList.remove("open");
        const modalImg = document.getElementById("modalImg");
        modalImg.src = "";
        }}

        document.addEventListener("keydown", (e) => {{
        if (e.key === "Escape") {{
            const modal = document.getElementById("modal");
            if (modal.classList.contains("open")) closeModal();
        }}
        }});
    </script>
    </body>
    </html>"""
        return html



def connect_to_tcp_server():
    # Connect to the TCP server
    global tcp_socket
    try:
        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1) 
        print(f"Connecting to TCP server at {TCP_HOST}:{TCP_PORT}...")
        tcp_socket.connect((TCP_HOST, TCP_PORT))
        # Identify as sensor data subscriber
        tcp_socket.sendall(b'SUB\n')
        print(f"Connected to TCP server.")
        return tcp_socket
    except Exception as e:
        print(f"Error connecting to TCP server: {e}")
        time.sleep(5)
        return None
    
def receive_sensor_data(tcp_socket):

    # Continuously receive temperature data from the TCP server
    # Example response: 
    # "temperature:20,setpoint:0.0,heater_power:0.5,heater_range:LOW,temperature_setpoint:10, timeout:300,
    # proportional_gain:1.0,integral_gain:0.1,derivative_gain:0.01"

    global current_50K
    global current_4K
    global current_STILL
    global current_MXC
    
    global current_R50K
    global current_R4K
    global current_RSTILL
    global current_RMXC
    
    global current_P50K
    global current_P4K
    global current_PSTILL
    global current_PMXC
    
    global current_enabled_MXC
    global current_enabled_50K
    global current_enabled_4K
    global current_enabled_STILL
    
    global current_mxc_temperature_setpoint
    global current_mxc_proportional_gain
    global current_mxc_integral_gain
    global current_mxc_derivative_gain
    global current_mxc_heater_range
    global current_dwell_MXC
    global current_pause_MXC
    global current_excitation_mode_MXC
    global current_excitation_range_MXC
    global current_excitation_autorange_MXC
    global current_excitation_mode_50K
    global current_excitation_range_50K
    global current_excitation_mode_4K
    global current_excitation_range_4K
    global current_excitation_mode_STILL
    global current_excitation_range_STILL
    global current_dwell_50K
    global current_dwell_4K
    global current_dwell_STILL
    global current_pause_50K
    global current_pause_4K
    global current_pause_STILL
    global current_temperature_setpoint
    global current_heater_power
    global current_heater_range
    global current_temperature_limit
    global current_timeout
    global current_proportional_gain
    global current_integral_gain
    global current_derivative_gain
    global current_autoscan
    global current_curve_MXC
    global current_curve_50K
    global current_curve_4K 
    global current_curve_STILL
    global current_heater_output_MXC
    global current_RUNID
    global current_RCH9, current_RCH10, current_RCH12, current_RCH13, current_RCH14


    buf = b""
    while True:
        try:
            chunk = tcp_socket.recv(4096)  # bigger read is fine
            if not chunk:
                raise ConnectionError("Sensor data socket closed by server")
            buf += chunk

            # Process complete lines
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                response = line.decode('utf-8', errors='ignore')

                # Parse the response to extract temperature and control parameters
                params = response.split(',')

                try:
                    current_50K, current_4K, current_STILL, current_MXC = _organize_temperature_data(params[0:4])
                except Exception as e:
                    print(f"Error parsing temperature data: {e}")
                    continue

                try:
                    control_params = _organize_control_params(params[4:9])
                    current_mxc_temperature_setpoint = control_params[0]
                    current_mxc_proportional_gain = control_params[1]
                    current_mxc_integral_gain = control_params[2]
                    current_mxc_derivative_gain = control_params[3]
                    current_mxc_heater_range = control_params[4]
                except Exception as e:
                    print(f"Error parsing MXC control data: {e}")
                    continue

                try:
                    resistance_settings = _organize_mxc_params(params[9:14])
                    current_dwell_MXC = resistance_settings[0]
                    current_pause_MXC = resistance_settings[1]
                    current_excitation_mode_MXC = resistance_settings[2]
                    current_excitation_range_MXC = resistance_settings[3]
                    current_excitation_autorange_MXC = resistance_settings[4]
                except Exception as e:
                    print(f"Error parsing MXC parameters: {e}")
                    continue

                try:
                    still_params = _organize_still_params([params[16], params[19]])
                    current_dwell_STILL = still_params[0]
                    current_pause_STILL = still_params[1]
                except Exception as e:
                    print(f"Error parsing STILL parameters: {e}")
                    continue

                try:
                    fourK_params = _organize_4k_params([params[15], params[18]])
                    current_dwell_4K = fourK_params[0]
                    current_pause_4K = fourK_params[1]
                except Exception as e:
                    print(f"Error parsing 4K parameters: {e}")
                    continue

                try:
                    fiftyK_params = _organize_50k_params([params[14], params[17]])
                    current_dwell_50K = fiftyK_params[0]
                    current_pause_50K = fiftyK_params[1]
                except Exception as e:
                    print(f"Error parsing 50K parameters: {e}")
                    continue

                except Exception as e:
                    print(f"Error parsing dwell/pause 50K/4K/STILL variables: {e}")
                    continue                 

                try:
                    current_temperature_setpoint = float(params[20].split(':')[-1])
                    current_heater_power = float(params[21].split(':')[-1])
                    current_heater_range = params[22].split(':')[-1]
                    current_temperature_limit = float(params[23].split(':')[-1])
                    current_timeout = float(params[24].split(':')[-1])
                    current_proportional_gain = float(params[25].split(':')[-1])
                    current_integral_gain = float(params[26].split(':')[-1])
                    current_derivative_gain = float(params[27].split(':')[-1])
                except Exception as e:
                    print(f"Error parsing control parameters: {e}")
                    continue
                
                try:
                    current_R50K, current_R4K, current_RSTILL, current_RMXC = _organize_resistance_data(params[29:33])
                except Exception as e:
                    print(f"Error parsing resistance data: {e}")
                    continue
                
                try:
                    current_P50K, current_P4K, current_PSTILL, current_PMXC = _organize_power_data(params[33:37])
                except Exception as e:
                    print(f"Error parsing power data: {e}")
                    continue
                
                try:
                    current_enabled_MXC = int(params[37].split(':')[-1])
                except Exception as e:
                    print(f"Error parsing enabled MXC variable: {e}")

                try:
                    current_enabled_50K = int(params[38].split(':')[-1])
                    current_enabled_4K = int(params[39].split(':')[-1])
                    current_enabled_STILL = int(params[40].split(':')[-1])
                except Exception as e:
                    print(f"Error parsing enabled 50K/4K/STILL variables: {e}")

                try:
                    autoscan_raw = int(params[28].split(':')[-1])
                    current_autoscan = "on" if autoscan_raw == 1 else "off"
                except Exception as e:
                    print(f"Error parsing autoscan variable: {e}")
                    current_autoscan = "off"
                
                try:
                    current_excitation_mode_50K = params[41].split(':')[-1].strip()
                    current_excitation_range_50K = params[42].split(':')[-1].strip()

                    current_excitation_mode_4K = params[43].split(':')[-1].strip()
                    current_excitation_range_4K = params[44].split(':')[-1].strip()

                    current_excitation_mode_STILL = params[45].split(':')[-1].strip()
                    current_excitation_range_STILL = params[46].split(':')[-1].strip()

                except Exception as e:
                    print(f"Error parsing excitation/mode 50K/4K/STILL: {e}")

                try:
                    current_curve_MXC   = int(params[47].split(':')[-1].strip())
                    current_curve_50K   = int(params[48].split(':')[-1].strip())
                    current_curve_4K    = int(params[49].split(':')[-1].strip())
                    current_curve_STILL = int(params[50].split(':')[-1].strip())

                except Exception as e:
                    print(f"Error parsing curve values (MXC/50K/4K/STILL): {e}")

                try:
                    current_heater_output_MXC = float(params[51].split(':')[-1].strip())
                except Exception as e:
                    print(f"Error parsing heaterOutputMXC: {e}")
                    current_heater_output_MXC = None

                try:
                    raw_run = params[52].split(':')[-1].strip()
                    if raw_run and raw_run.upper() != "NONE":
                        current_RUNID = int(raw_run)
                    else:
                        current_RUNID = None
                except Exception as e:
                    print(f"⚠ Warning parsing run ID: {e} (raw value = {raw_run!r})")
                    current_RUNID = None

                try:
                    def _parse_rch(i):
                        v = params[i].split(':')[-1].strip()
                        if not v or v.upper() == "NONE":
                            return None
                        return float(v)

                    current_RCH9  = _parse_rch(53)
                    current_RCH10 = _parse_rch(54)
                    current_RCH12 = _parse_rch(55)
                    current_RCH13 = _parse_rch(56)
                    current_RCH14 = _parse_rch(57)

                except Exception as e:
                    print(f"Error parsing extra resistances RCH9/10/12/13/14: {e}")
                    current_RCH9 = current_RCH10 = current_RCH12 = current_RCH13 = current_RCH14 = None

        except socket.timeout:
            continue

        except Exception as e:
            print(f"Error receiving LakeShore370 data: {e}")
            try:
                tcp_socket.close()
            except Exception:
                pass

            try:
                tcp_socket = connect_to_tcp_server()
                buf = b""  # reset buffer on reconnect
            except Exception as e:
                print(f"Error reconnecting to TCP server: {e}")
                time.sleep(5)
                break

def run(server_class=HTTPServer, handler_class=SimpleHTTPRequestHandler,
        tcp_socket=None, port=8080):
    
    if tcp_socket is None: tcp_socket = connect_to_tcp_server()
    
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f"HTTP server running on port {port}")

    # Start the temperature data receiver thread
    temperature_thread = threading.Thread(target=receive_sensor_data,
                         daemon=True, args=(tcp_socket,))
    temperature_thread.start()

    # Start the HTTP server
    httpd.serve_forever()

# ---- Helper functions ----
def _organize_temperature_data(params):

    current_50K = params[0].split(':')[-1].strip()
    if current_50K == "OFF":
        current_50K = None
    else:
        try:
            current_50K = float(current_50K)
        except ValueError:
            current_50K = None
            print("Invalid 50K temperature value received:", params[0])

    current_4K = params[1].split(':')[-1].strip()
    if current_4K == "OFF":
        current_4K = None
    else:
        try:
            current_4K = float(current_4K)
        except ValueError:
            current_4K = None
            print("Invalid 4K temperature value received:", params[1])

    current_STILL = params[2].split(':')[-1].strip()
    if current_STILL == "OFF":
        current_STILL = None
    else:              
        try:
            current_STILL = float(current_STILL)
        except ValueError:
            current_STILL = None
            print("Invalid STILL temperature value received:", params[2])

    current_MXC = params[3].split(':')[-1].strip()
    if current_MXC == "OFF":
        current_MXC = None
    else:
        try:
            current_MXC = float(current_MXC)
        except ValueError:
            current_MXC = None
            print("Invalid MXC temperature value received:", params[3])

    return current_50K, current_4K, current_STILL, current_MXC

def _organize_resistance_data(params):
    
    current_R50K = params[0].split(':')[-1].strip()
    if current_R50K == "OFF":
        current_R50K = None
    else:
        try:
            current_R50K = float(current_R50K)
        except ValueError:
            current_R50K = None
            print("Invalid 50K resistance value received:", params[0])

    current_R4K = params[1].split(':')[-1].strip()
    if current_R4K == "OFF":
        current_R4K = None
    else:
        try:
            current_R4K = float(current_R4K)
        except ValueError:
            current_R4K = None
            print("Invalid 4K resistance value received:", params[1])

    current_RSTILL = params[2].split(':')[-1].strip()
    if current_RSTILL == "OFF":
        current_RSTILL = None
    else:              
        try:
            current_RSTILL = float(current_RSTILL)
        except ValueError:
            current_RSTILL = None
            print("Invalid STILL resistance value received:", params[2])

    current_RMXC = params[3].split(':')[-1].strip()
    if current_RMXC == "OFF":
        current_RMXC = None
    else:
        try:
            current_RMXC = float(current_RMXC)
        except ValueError:
            current_RMXC = None
            print("Invalid MXC resistance value received:", params[3])

    return current_R50K, current_R4K, current_RSTILL, current_RMXC

def _organize_power_data(params):
    
    current_P50K = params[0].split(':')[-1].strip()
    if current_P50K == "OFF":
        current_P50K = None
    else:
        try:
            current_P50K = float(current_P50K)
        except ValueError:
            current_P50K = None
            print("Invalid 50K power value received:", params[0])

    current_P4K = params[1].split(':')[-1].strip()
    if current_P4K == "OFF":
        current_P4K = None
    else:
        try:
            current_P4K = float(current_P4K)
        except ValueError:
            current_P4K = None
            print("Invalid 4K power value received:", params[1])

    current_PSTILL = params[2].split(':')[-1].strip()
    if current_PSTILL == "OFF":
        current_PSTILL = None
    else:              
        try:
            current_PSTILL = float(current_PSTILL)
        except ValueError:
            current_PSTILL = None
            print("Invalid STILL power value received:", params[2])

    current_PMXC = params[3].split(':')[-1].strip()
    if current_PMXC == "OFF":
        current_PMXC = None
    else:
        try:
            current_PMXC = float(current_PMXC)
        except ValueError:
            current_PMXC = None
            print("Invalid MXC resistance value received:", params[3])

    return current_P50K, current_P4K, current_PSTILL, current_PMXC

def _organize_control_params(params):

    try:
        tempSetPointMXC = float(params[0].split(':')[-1].strip()) * 1000 # Convert to mK
    except ValueError:
        tempSetPointMXC = None
        print("Invalid MXC temperature setpoint value received:", params[0])

    try:
        proportionalMXC = float(params[1].split(':')[-1].strip())
    except ValueError:
        proportionalMXC = None
        print("Invalid proportional gain value received:", params[1])

    try:
        integralMXC = float(params[2].split(':')[-1].strip())
    except ValueError:
        integralMXC = None
        print("Invalid integral gain value received:", params[2])

    try:
        derivativeMXC = float(params[3].split(':')[-1].strip())
    except ValueError:
        derivativeMXC = None
        print("Invalid derivative gain value received:", params[3])
    
    try:
        heaterRangeMXC = params[4].split(':')[-1].strip()
    except ValueError:
        heaterRangeMXC = None
        print("Invalid heater range value received:", params[4])

    return tempSetPointMXC, proportionalMXC, integralMXC, derivativeMXC, heaterRangeMXC

def _organize_mxc_params(params):
    
    try:
        dwell_MXC = float(params[0].split(':')[-1].strip())
    except ValueError:
        dwell_MXC = None
        print("Invalid MXC dwell time value received:", params[0])

    try:
        pause_MXC = float(params[1].split(':')[-1].strip())
    except ValueError:
        pause_MXC = None
        print("Invalid MXC pause time value received:", params[1])

    excitation_mode_MXC = params[2].split(':')[-1].strip()
    excitation_range_MXC = params[3].split(':')[-1].strip()
    excitation_autorange_MXC = params[4].split(':')[-1].strip()

    return dwell_MXC, pause_MXC, excitation_mode_MXC, excitation_range_MXC, excitation_autorange_MXC

def _organize_still_params(params):
    try:
        dwell_STILL = float(params[0].split(':')[-1].strip())
    except ValueError:
        dwell_STILL = None
        print("Invalid STILL dwell time value received:", params[0])

    try:
        pause_STILL = float(params[1].split(':')[-1].strip())
    except ValueError:
        pause_STILL = None
        print("Invalid STILL pause time value received:", params[1])

    return dwell_STILL, pause_STILL

def _organize_4k_params(params):
    try:
        dwell_4K = float(params[0].split(':')[-1].strip())
    except ValueError:
        dwell_4K = None
        print("Invalid 4K dwell time value received:", params[0])

    try:
        pause_4K = float(params[1].split(':')[-1].strip())
    except ValueError:
        pause_4K = None
        print("Invalid 4K pause time value received:", params[1])

    return dwell_4K, pause_4K

def _organize_50k_params(params):
    try:
        dwell_50K = float(params[0].split(':')[-1].strip())
    except ValueError:
        dwell_50K = None
        print("Invalid 50K dwell time value received:", params[0])

    try:
        pause_50K = float(params[1].split(':')[-1].strip())
    except ValueError:
        pause_50K = None
        print("Invalid 50K pause time value received:", params[1])

    return dwell_50K, pause_50K


if __name__ == "__main__":
    # Connect to the TCP server
    tcp_socket = connect_to_tcp_server()
    time.sleep(1)
    if tcp_socket:
        run(tcp_socket=tcp_socket)
