import threading
import time
import random

_lakeshore_mutex = threading.Lock()


DEFAULT_CHANNELS = [1, 2, 5, 6]#, 7]
DEFAULT_CHANNELS_ID = ["50K", "4K", "STILL", "MXC"]#, "CH7"]
ALL_CHANNELS = range(1, 17)

# [dwell time, pause time, curve number, temperature coefficient]
DEFAULT_SETTINGS = {
    1: ['010, 003, 01, 2'],  # 50 K stage
    2: ['010, 003, 02, 2'],  # 4 K stage
    5: ['010, 003, 03, 2'],  # STILL stage
    6: ['001, 001, 04, 2']   # MXC stage
}

DEFAULT_PID = {
    "P": 1.0,  # Proportional gain
    "I": 1.0,  # Integral gain
    "D": 10.0, # Derivative gain
}

CURRENT_RANGE_LIST = {
    "0": ("Off", ""),
    "1": (31.6, 'uA'),
    "2": (100, 'uA'),
    "3": (316, 'uA'),
    "4": (1, 'mA'),
    "5": (3.16, 'mA'),
    "6": (10, 'mA'),
    "7": (31.6, 'mA'),
    "8": (100, 'mA'),
}

SENSOR_RESISTANCE_RANGE_LIST = {
    "1": (2.00, 'uV', 1.00, 'pA'),
    "2": (6.32, 'uV', 3.16, 'pA'),
    "3": (20.00, 'uV', 10.00, 'pA'),
    "4": (63.10, 'uV', 31.60, 'pA'),
    "5": (200.00, 'uV', 100.00, 'pA'),
    "6": (632.00, 'uV', 316.00, 'pA'),
    "7": (2.00, 'mV', 1.00, 'nA'),
    "8": (6.32, 'mV', 3.16, 'nA')
}

RESISTANCE_RANGE_LIST = {
    "1": (2.00, 'miliOhms'),
    "2": (6.32, 'miliOhms'),
    "3": (20.00, 'miliOhms'),
    "4": (63.20, 'miliOhms'),
    "5": (200.00, 'miliOhms'),
    "6": (632.00, 'miliOhms'),
    "7": (2.00, 'Ohms'),
    "8": (6.32, 'Ohms')
}

DEFAULT_MXC_RESISTANCE_RANGE_SETTINGS = {
    "excitation_mode": 0,  # 0 voltage, 1 current
    "excitation_range": 4, # 5 → 200 µV / 100 pA
    "resistance_range": 14,
    "autorange": 1,        # 1 = YES
    "excitation": 0,       # 1 = excitation OFF
}

CURVE_NAMES = {
    1: "PT-100-20K (PT1011)",
    2: "CX-1050-CD-BF1 (X64005)",
    5: "CX-1010-CD-BF0 (X63593)",
    6: "RU-1000-BF0.007 (U03308)"
}

DEFAULT_CURVES = {
    1: 1,
    2: 2,
    5: 5,
    6: 6,
}

#Mapa canal → etiqueta
CHANNEL_LABEL = {
    1: "50K",
    2: "4K",
    5: "STILL",
    6: "MXC",
}

#Transforma campos de tipo bool a int
def _b2i(x):
    return int(x) if isinstance(x, (bool, int)) else x

#Numeros de rango a string
def _i2s(x):
    x = str(x)
    if len(x) == 1:
        x = "0" + x
    elif len(x) == 2:
        x = x
    else:
        raise ValueError("Excitation range format wrong. Only permitted 1–2 digit int/str.")
    return x


def _translate_control_settings_to_dictionary(control_params: list) -> dict:
    controlled_channel = control_params[0]
    filtered_readings = True if control_params[1] == '1' else False
    units = "Kelvin" if control_params[2] == '1' else "Ohms"
    delay = int(control_params[3])
    heater_display = float(control_params[4])  # 1 current, 2 power
    heater_range = control_params[5]
    heater_resistance = float(control_params[6])

    return {
        "controlled_channel": controlled_channel,
        "filtered_readings": filtered_readings,
        "units": units,
        "delay": delay,
        "heater_display": heater_display,
        "HR": heater_range,
        "heater_resistance": heater_resistance,
    }


def _translate_sensor_resistance_settings_to_dictionary(values: list) -> dict:
    excitation_mode   = values[0]
    excitation_range  = str(int(values[1]))
    resistance_range  = str(int(values[2]))
    autorange         = values[3]
    excitation        = values[4]

    return {
        "excitation_mode": excitation_mode,
        "excitation_range": excitation_range,
        "resistance_range": resistance_range,
        "autorange": autorange,
        "excitation": excitation
    }


# -------------------------------------------------------------------
#                       Dummy LakeShore370
# -------------------------------------------------------------------

class LakeShore370:
    """
    Dummy compatible con la API del Lakeshore real usada en tcp_server.py.

    - No abre ningún recurso VISA.
    - Devuelve temperaturas/resistencias/potencias simuladas.
    - Mantiene estado interno de:
      * PID (DEFAULT_PID)
      * rango de heater (string de CURRENT_RANGE_LIST)
      * setpoint MXC (SETP canal 6, en K internamente)
      * ajustes de resistencia MXC (DEFAULT_MXC_RESISTANCE_RANGE_SETTINGS)
      * dwell/pause times, autoscan, etc.
    """

    def __init__(self, addr=None, baud_rate=9600, timeout=2000):
        # Estado interno simulado
        self._temps_K = {
            "50K": 50.0,
            "4K": 4.2,
            "STILL": 1.0,
            "MXC": 0.0,   # 100 mK
        }
        self._resistances_ohm = {
            "50K": 100.0,
            "4K": 200.0,
            "STILL": 500.0,
            "MXC": 1000.0,
        }
        self._powers_W = {
            "50K": 0.0,
            "4K": 0.0,
            "STILL": 0.0,
            "MXC": 0.0,
        }
        self._heater_output_percent = 0.0
        self._curves = {
            1: DEFAULT_CURVES[1],   # 50K
            2: DEFAULT_CURVES[2],   # 4K
            5: DEFAULT_CURVES[5],   # STILL
            6: DEFAULT_CURVES[6],   # MXC
        }
        """ self._temps_K["CH7"] = self._temps_K["MXC"]
        self._resistances_ohm["CH7"] = 800.0 """
        # Canales ON por defecto
        self._channel_status = {ch: 1 for ch in DEFAULT_CHANNELS}

        # PID del heater (canal controlado, por defecto MXC=6)
        self._pid = DEFAULT_PID.copy()
        self._control_channel = 6
        self._heater_range = "5"  # algo razonable (3.16 mA)
        self._heater_resistance = 100.0  # Ohm ficticio
        self._heater_display = 1   # corriente
        self._filtered_readings = 1
        self._units = 1           # Kelvin
        self._delay = 1

        # Setpoint MXC (en K internamente, como hace SETP en el real)
        self._mxc_setpoint_K = self._temps_K["MXC"]

        # Config de sensor MXC
        self._sensor_resistance_settings = DEFAULT_MXC_RESISTANCE_RANGE_SETTINGS.copy()

        # Dwell/Pause simulated (basados en DEFAULT_SETTINGS)
        self._dwell_times = {
            "50K": 10,
            "4K": 10,
            "STILL": 10,
            "MXC": 1,
        }
        self._pause_times = {
            "50K": 3,
            "4K": 3,
            "STILL": 3,
            "MXC": 1,
        }

        # Autoscan: [channel, status]
        # status 0 = off, 1 = on
        self._autoscan = ["6", "0"]

        #self._channel_status[7] = 1

        print("Dummy LakeShore370 inicializado (sin hardware real).")

    # ---------------------- GET MÉTODOS ------------------------------

    def _label_from_channel(self, channel: int) -> str:
        return CHANNEL_LABEL.get(channel, f"CH{channel}")

    def get_temperature(self, channel: int):
        """
        Devuelve temperatura en K del canal indicado.
        """
        label = self._label_from_channel(channel)
        with _lakeshore_mutex:
            base = self._temps_K.get(label, 0.0)
            # Pequeña variación aleatoria para que "se mueva"
            noise = random.uniform(-0.005, 0.005)
            value = max(base + noise, 0.0)
            self._temps_K[label] = value
            return value
        
    def get_channel_curve(self, channel: int) -> int | None:
        """
        Devuelve la curva asignada al canal (para simular INSET? campo curva).
        """
        if channel not in DEFAULT_CHANNELS:
            print(f"Dummy: Channel {channel} invalid. Valid: {DEFAULT_CHANNELS}")
            return None

        with _lakeshore_mutex:
            return int(self._curves.get(channel, 0))

    def get_resistance(self, channel: int):
        """
        Devuelve resistencia en Ohmios del canal indicado.
        El canal 7 está artificialmente correlacionado con la temperatura MXC.
        """
        label = self._label_from_channel(channel)

        with _lakeshore_mutex:

            # ----------- CANAL 7 FICTICIO -----------
            if channel == 7:
                T_mxc = self._temps_K.get("MXC", 0.05)

                # Relación artificial pero realista:
                # R ↓ cuando T ↓ (tipo sensor resistivo)
                # R = R0 * (T / T0)^alpha
                T0 = 0.05        # 50 mK referencia
                R0 = 1000.0      # 1 kΩ a 50 mK
                alpha = 1.2      # pendiente suave

                R = R0 * (max(T_mxc, 1e-4) / T0) ** alpha
                noise = random.uniform(-5.0, 5.0)

                value = max(R + noise, 1.0)
                self._resistances_ohm["CH7"] = value
                return value

            # ----------- RESTO DE CANALES -----------
            base = self._resistances_ohm.get(label, 0.0)
            noise = random.uniform(-0.5, 0.5)
            value = max(base + noise, 0.0)
            self._resistances_ohm[label] = value
            return value

    def get_power(self, channel: int):
        """
        Devuelve potencia de excitación en W (simulada).
        """
        label = self._label_from_channel(channel)
        with _lakeshore_mutex:
            return self._powers_W.get(label, 0.0)

    def get_channel_status(self, channel: int, verbose=False):
        with _lakeshore_mutex:
            status = int(self._channel_status.get(channel, 0))
        if verbose:
            print(f"Channel {channel} is {'ON' if status else 'OFF'}.")
        return status

    def get_channel_setpoint(self, channel: int = 6):
        if channel != 6:
            print("Dummy: sólo se implementa setpoint para canal 6 (MXC).")
            return None
        with _lakeshore_mutex:
            return float(self._mxc_setpoint_K)

    def get_temperature_setpoint(self):
        # Igual que en el real, devuelve SETP (K) del canal 6
        with _lakeshore_mutex:
            return float(self._mxc_setpoint_K)

    def get_control_parameters(self) -> dict:
        with _lakeshore_mutex:
            return {
                "P": float(self._pid["P"]),
                "I": float(self._pid["I"]),
                "D": float(self._pid["D"]),
            }

    def get_dwell_time(self, channel: int):
        label = self._label_from_channel(channel)
        with _lakeshore_mutex:
            return int(self._dwell_times.get(label, 0))

    def get_pause_time(self, channel: int):
        label = self._label_from_channel(channel)
        with _lakeshore_mutex:
            return int(self._pause_times.get(label, 0))

    def get_autoscan(self):
        """
        Devuelve algo tipo ["6", "0"] como el SCAN? real.
        """
        with _lakeshore_mutex:
            # Lo devolvemos como lista de strings, tcp_server ya lo normaliza.
            return list(self._autoscan)

    def get_channels_dwell_time(self, channels=None):
        if channels is None:
            channels = DEFAULT_CHANNELS

        dwell_times = {}
        if not isinstance(channels, list):
            print("Channels must be a list of integers.")
            return None

        for idx, ch in enumerate(channels):
            label = DEFAULT_CHANNELS_ID[idx]
            dwell_times[label] = self.get_dwell_time(ch)

        return dwell_times

    def get_channels_pause_time(self, channels=None):
        if channels is None:
            channels = DEFAULT_CHANNELS

        pause_times = {}
        if not isinstance(channels, list):
            print("Channels must be a list of integers.")
            return None

        for idx, ch in enumerate(channels):
            label = DEFAULT_CHANNELS_ID[idx]
            pause_times[label] = self.get_pause_time(ch)

        return pause_times

    def get_control_settings(self, return_dict=False):
        with _lakeshore_mutex:
            params = [
                str(self._control_channel),
                str(self._filtered_readings),
                str(self._units),
                str(self._delay),
                str(int(self._heater_display)),
                str(self._heater_range),
                str(self._heater_resistance),
            ]

        if return_dict:
            return _translate_control_settings_to_dictionary(params)
        return params

    def get_control_channel(self):
        """
        Devuelve "MXC", "STILL", "4K" o "50K" según el canal controlado.
        """
        with _lakeshore_mutex:
            ch = int(self._control_channel)
        if ch == 6:
            return "MXC"
        elif ch == 5:
            return "STILL"
        elif ch == 2:
            return "4K"
        elif ch == 1:
            return "50K"
        else:
            return None

    def get_control_range(self):
        """
        Devuelve el HR (string 0–8) del heater.
        """
        with _lakeshore_mutex:
            return str(self._heater_range)

    def get_sensor_resistance_settings(self, channel: int = 6, return_dict=False):
        if channel not in DEFAULT_CHANNELS:
            print(f"Channel {channel} is not valid. Valid channels are: {DEFAULT_CHANNELS}")
            return None

        with _lakeshore_mutex:
            mode  = int(self._sensor_resistance_settings["excitation_mode"])
            erng  = int(self._sensor_resistance_settings["excitation_range"])
            rrng  = int(self._sensor_resistance_settings["resistance_range"])
            auto  = int(self._sensor_resistance_settings["autorange"])
            exct  = int(self._sensor_resistance_settings["excitation"])

        values = [
            str(mode),
            str(erng),
            str(rrng),
            str(auto),
            str(exct),
        ]

        if return_dict:
            return _translate_sensor_resistance_settings_to_dictionary(values)
        return values


    def get_heater_output_percent(self):
        
        """
        Devuelve un porcentaje de salida del heater (0–100 %) simulado
        para la MXC, compatible con el método del LakeShore real.

        Lo calculamos en función de la diferencia entre setpoint y
        temperatura actual de la MXC: si la MXC está por debajo del
        setpoint, sube el %; si está por encima, se acerca a 0.
        """
        with _lakeshore_mutex:
            temp = float(self._temps_K.get("MXC", 0.0))
            setp = float(self._mxc_setpoint_K)

            # Error (K): cuánto falta para el setpoint
            error = setp - temp

            if error <= 0:
                base = 0.0
            else:
                # Escala el error a 0–100% (ajustado "a ojo" para el dummy)
                # Por ejemplo, 0.05 K por debajo de setpoint ⇒ ~100 %
                base = min(error * 2000.0, 100.0)

            # Un poquito de ruido para que no sea totalmente constante
            noise = random.uniform(-2.0, 2.0)
            value = max(0.0, min(100.0, base + noise))

            # Guardamos algo coherente en la potencia también (opcional)
            self._heater_output_percent = value
            self._powers_W["MXC"] = 1e-3 * (value / 100.0)  # hasta 1 mW ficticio

            return value

    # ---------------------- SET MÉTODOS ------------------------------

    def set_temperature_setpoint(self, value: float, units: str = 'K', verbose=False):
        """
        Versión genérica (no usada directamente por tcp_server).
        """
        if units not in ['K', 'Ohms']:
            print("Units must be 'K' or 'Ohms'.")
            return
        with _lakeshore_mutex:
            if units == 'K':
                self._mxc_setpoint_K = float(value)
            else:
                # En dummy ignoramos Ohms
                self._mxc_setpoint_K = float(self._mxc_setpoint_K)
        if verbose:
            print(f"[DUMMY] Set temperature setpoint to {self._mxc_setpoint_K} K.")

    def set_channel_setpoint(self, value: float, channel: int = 6,
                             verbose: bool = True, units: str = 'mK'):
        """
        Versión dummy de set_channel_setpoint del real:
        - value en mK (por defecto)
        - rango permitido 10–500 mK
        - guarda internamente en K
        """
        if channel != 6:
            print("Dummy: sólo se implementa setpoint en canal 6 (MXC).")
            return False

        if units not in ['K', 'mK']:
            print("Units must be 'K' or 'mK'.")
            return False

        # Validación igual que el real
        if value < 0 or value > 500:
            print("Temperature setpoint must be between 10 mK and 500 mK.")
            return False

        with _lakeshore_mutex:
            if units == 'mK':
                self._mxc_setpoint_K = float(value) / 1000.0
            else:
                self._mxc_setpoint_K = float(value)

        if verbose:
            print(f"[DUMMY] Set MXC setpoint to {self._mxc_setpoint_K} K (channel 6).")
        return True

    def set_control_parameters(self, P: float = None, I: float = None, D: float = None,
                               channel: int = 6, verbose: bool = False):
        if channel != 6:
            print("Dummy: sólo implemento PID para canal 6 (MXC).")
            return False

        with _lakeshore_mutex:
            if P is None:
                P = self._pid["P"]
            if I is None:
                I = self._pid["I"]
            if D is None:
                D = self._pid["D"]
            self._pid["P"] = float(P)
            self._pid["I"] = float(I)
            self._pid["D"] = float(D)

        if verbose:
            print(f"[DUMMY] PID set: P={P}, I={I}, D={D}")
        return True

    def set_control_range(self, range_value: str, verbose: bool = True):
        if range_value not in CURRENT_RANGE_LIST:
            print(f"Control range {range_value} is not valid. Valid ranges are: {list(CURRENT_RANGE_LIST.keys())}")
            return False
        with _lakeshore_mutex:
            self._heater_range = str(range_value)
        if verbose:
            name, unit = CURRENT_RANGE_LIST[range_value]
            print(f"[DUMMY] Control range set to: {name} {unit}")
        return True

    def set_control_settings_channel(self, channel: int = 6, verbose: bool = True):
        if channel not in DEFAULT_CHANNELS:
            print(f"Channel {channel} is not valid. Valid channels are: {DEFAULT_CHANNELS}")
            return False
        with _lakeshore_mutex:
            self._control_channel = int(channel)
        if verbose:
            print(f"[DUMMY] Control channel set to {channel}.")
        return True

    def set_sensor_resistance_settings(self, channel: int = 6,
                                      settings: dict | None = None,
                                      verbose: bool = True) -> bool:
        if channel not in DEFAULT_CHANNELS:
            print(f"Channel {channel} is not valid. Valid channels are: {DEFAULT_CHANNELS}")
            return False

        base = DEFAULT_MXC_RESISTANCE_RANGE_SETTINGS.copy()
        if settings is None:
            merged = base
        else:
            allowed_keys = set(base.keys())
            unknown = set(settings.keys()) - allowed_keys
            if unknown:
                print(f"Unknown setting keys: {sorted(unknown)}. Allowed: {sorted(allowed_keys)}")
                return False
            merged = {**base, **settings}

        try:
            excitation_mode = int(merged['excitation_mode'])
            excitation_range = _i2s(merged['excitation_range'])
            resistance_range = int(merged['resistance_range'])
            autorange = _b2i(merged['autorange'])
            excitation = _b2i(merged['excitation'])
        except KeyError as e:
            print(f"Missing required key in settings/defaults: {e}")
            return False
        except (TypeError, ValueError) as e:
            print(f"Invalid value type in settings: {e}")
            return False

        with _lakeshore_mutex:
            self._sensor_resistance_settings = {
                "excitation_mode": excitation_mode,
                "excitation_range": int(excitation_range),
                "resistance_range": resistance_range,
                "autorange": int(autorange),
                "excitation": int(excitation),
            }

        if verbose:
            print(f"[DUMMY] Sensor resistance settings for channel {channel} set to: {self._sensor_resistance_settings}")
        return True

    def set_autoscan(self, status: bool | str = "Off", channel: int = 6) -> bool:
        # Normalización tipo real
        if isinstance(status, str):
            s = status.strip().lower()
            if s in {"on", "1", "true", "yes"}:
                status_bool = True
            elif s in {"off", "0", "false", "no"}:
                status_bool = False
            else:
                raise ValueError(f"Unrecognized status string: {status!r}")
        elif isinstance(status, bool):
            status_bool = status
        else:
            raise TypeError("status must be bool or str")

        with _lakeshore_mutex:
            self._autoscan = [str(channel), "1" if status_bool else "0"]

        print(f"[DUMMY] Autoscan {'ON' if status_bool else 'OFF'} on channel {channel}")
        return True

    def set_channel_off(self, channel: int, verbose: bool = False):
        with _lakeshore_mutex:
            self._channel_status[channel] = 0
        if verbose:
            print(f"[DUMMY] Channel {channel} set OFF")
        return True

    def set_channel_on(self, channel: int, settings=None, verbose: bool = False):
        if channel not in DEFAULT_CHANNELS:
            print(f"Channel {channel} is not valid. Valid channels are: {DEFAULT_CHANNELS}")
            return False
        with _lakeshore_mutex:
            self._channel_status[channel] = 1
        if verbose:
            print(f"[DUMMY] Channel {channel} set ON (settings ignored in dummy)")
        return True
    
    def set_channel_dwell_time(self, dwell: float, channel: int, verbose: bool = False) -> bool:

        if channel not in DEFAULT_CHANNELS:
            print(f"Channel {channel} is not valid. Valid channels are: {DEFAULT_CHANNELS}")
            return False

        label = self._label_from_channel(channel)
        with _lakeshore_mutex:
            self._dwell_times[label] = float(dwell)

        if verbose:
            print(f"[DUMMY] Dwell time for {label} (ch {channel}) set to {dwell} s")
        return True

    def set_channel_pause_time(self, pause: float, channel: int, verbose: bool = False) -> bool:

        if channel not in DEFAULT_CHANNELS:
            print(f"Channel {channel} is not valid. Valid channels are: {DEFAULT_CHANNELS}")
            return False

        label = self._label_from_channel(channel)
        with _lakeshore_mutex:
            self._pause_times[label] = float(pause)

        if verbose:
            print(f"[DUMMY] Pause time for {label} (ch {channel}) set to {pause} s")
        return True

    def set_channel_curve(self, curve_number: int, channel: int, verbose: bool = True) -> bool:
        """
        Dummy del comando para asignar una curva a un canal.
        Simula el comportamiento del Lakeshore real.
        """
        if channel not in DEFAULT_CHANNELS:
            print(f"Dummy: Channel {channel} is not valid. Valid: {DEFAULT_CHANNELS}")
            return False

        if not isinstance(curve_number, int):
            print("Dummy: Curve number must be int.")
            return False

        with _lakeshore_mutex:
            self._curves[channel] = int(curve_number)

        if verbose:
            print(f"[DUMMY] Curve for channel {channel} set to {curve_number}")

        return True
    
    def close(self):
        print("[DUMMY] Closing dummy LakeShore370 (no hardware).")
        return True
