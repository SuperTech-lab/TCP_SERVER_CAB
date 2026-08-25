import pyvisa
import threading
import time

# Shared mutex lock for safe device access
# Changed Lock for RLock (Reentrant Lock) to allow the same thread to acquire the lock multiple times if needed
# It is convenient when a protected function calls another protected function.
_lakeshore_mutex = threading.RLock()

# LakeShore 370 device communication requires at least 50 ms between commands
# Using 55 ms as safe margin
MIN_COMMUNICATION_INTERVAL_S = 0.055

# Ramp implementation for temperature control min and max rate values in Kelvin/min
MIN_RAMP_RATE_K_PER_MIN = 0.001
MAX_RAMP_RATE_K_PER_MIN = 10.0
MIN_TARGET_TEMPERATURE_MK = 10.0
MAX_TARGET_TEMPERATURE_MK = 900.0

# These reading status flags are used to identify the LakeShore 370 channel status and act accordingly
# The flags are represented as bit masks.
# These flags can be combined; for example, 00000101 means (CS OVL and VMIX OVL combined)
READING_STATUS_FLAGS = {
    1   : "CS OVL",     # 00000001
    2   : "VCM OVL",    # 00000010
    4   : "VMIX OVL",   # 00000100
    8   : "VDIF OVL",   # 00001000
    16  : "R. OVER",    # 00010000
    32  : "R. UNDER",   # 00100000
    64  : "T. OVER",    # 01000000
    128 : "T. UNDER",   # 10000000
}

DEFAULT_CHANNELS = [1, 2, 5, 6, 9, 10, 11, 12, 13, 14, 15]
DEFAULT_CHANNELS_ID = ["50K", "4K", "STILL", "MXC"]
ALL_CHANNELS = range(1, 17)

# Default channel settings
# [dwell time, change pause time, curve number, temperature coefficient]
# dwell time (seconds): from 1 to 200
# pause time (seconds): from 3 to 200
# curve number: 0 means no curve, from 1 to 20.
# temperature coefficient: 1 for negative, 2 for positive.

DEFAULT_SETTINGS = {
    1: ['010, 003, 01, 2'],  # 50 K stage
    2: ['010, 003, 02, 2'],  # 4 K stage
    5: ['010, 003, 03, 2'],  # STILL stage
    6: ['001, 001, 04, 2']   # MXC stage
}

DEFAULT_PID = {
    "P": 1.0,       # Proportional gain
    "I": 1.0,       # Integral gain
    "D": 10.0,      # Derivative gain
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
    "excitation_mode"  : 0,      # 0 for voltage, 1 for current
    "excitation_range" : 5,      # 5 for 200 uV and 100 pA
    "resistance_range" : 14,     # 14 for 3.15 uA R = 6.32 kOhm
    "autorange"        : 1,      # 0 for NO, 1 for YES
    "excitation"       : 1,      # 0 for excitation on, 1 = exctiation off
}

CURVE_NAMES = {
    1  :    "PT-100-20K (PT1011)",
    2  :    "CX-1050-CD-BF1 (X64005)",
    5  :    "CX-1010-CD-BF0 (X63593)",
    6  :    "RU-1000-BF0.007 (U03308)"
    
}

DEFAULT_CURVES = {
    1 : 1,
    2 : 2,
    5 : 3,
    6 : 4,
}

class LakeShore370:

    """A class to interface with the Lake Shore 370 temperature controller.
    This class provides methods to read temperatures, set temperature setpoints,
    and control the channels of the device.
    Attributes:
        addr (str): The VISA address of the device.
        baud_rate (int): The baud rate for serial communication.
        timeout (int): The timeout for device communication in milliseconds.
    """
    #! -- Initialization -- #
    def __init__(self,
                 addr = 'ASRL/dev/ttyUSB1::INSTR',
                 baud_rate = 9600,
                 timeout = 2000):

        self.rm = pyvisa.ResourceManager()
        self.device = self.rm.open_resource(addr)
        self.device.baud_rate = baud_rate
        self.device.data_bits = 7
        self.device.stop_bits = pyvisa.constants.StopBits.one
        self.device.parity = pyvisa.constants.Parity.odd
        self.device.write_termination = '\r\n'
        self.device.read_termination = '\r\n'
        self.device.timeout = timeout  # milliseconds
        self._when_last_communication_completed = 0.0

    #! -- Communication Methods -- #
    def _wait_for_communication_slot(self):
        """
        Wait until another Lake Shore communication is permitted
        It compares the current time with the time of completition of the last communication.
        If the elapsed time between the completition and current time is less than the minimumum
        communication interval it waits.
        """
        elapsed_time = time.monotonic() - self._when_last_communication_completed
        # monotonic avoids issues with system clock changes

        remaining_time = MIN_COMMUNICATION_INTERVAL_S - elapsed_time

        if remaining_time > 0:
            time.sleep(remaining_time)

    def _query(self, command: str) -> str:
        """
        Execute one VISA query with locking.
        Checks if communication slot is available and waits if needed.
        Stores the completition time of the command.
        """
        with _lakeshore_mutex:
            self._wait_for_communication_slot()
            try:
                return self.device.query(command)
            finally:
                self._when_last_communication_completed = time.monotonic()

    def _write(self, command: str) -> None:
        """
        Execute one VISA write command with locking.
        Checks if communication slot is availablea and waits if necessary.
        Stores the completition time of the command.
        """
        with _lakeshore_mutex:
            self._wait_for_communication_slot()
            try:
                self.device.write(command)
            finally:
                self._when_last_communication_completed = time.monotonic()

    #! -- Device status Methods -- #
    def get_reading_status(self, channel: int) -> int:
        """
        Get the reading status for a specific channel.
        Args:
            channel (int): The channel number.
        Returns:
            int: The reading status in lakeshore code (check READING_STATUS_FLAGS for meanings).
        """
        try:
            response = self._query(f"RDGST? {channel}")
            return int(response.strip())
        except Exception as e:
            print(f"Getting reading status for channel {channel} failed.\nReason: {e}")
            return None

    @staticmethod
    def describe_reading_status(status_code: int) -> list[str]:
        """
        Convert an RDGST bit mask into readable status labels.
        """
        errors = []

        for flag, description in READING_STATUS_FLAGS.items():
            if status_code & flag:
                errors.append(description)

        return errors

    #! -- Device get Methods -- #
    def get_temperature(self, channel: int):
        """ 
            Get temperature read by channel {channel}. 
            Given in Kelvin
        """
        try:
            with _lakeshore_mutex:
                # RLock maintains the lock for the same thread,
                # allowing making multiple queries (RDGST? and RDGK?) without releasing the lock in between.
                status_code = self.get_reading_status(channel)

                if status_code is None:
                    # The exception message is managed in get_reading_status()
                    return None

                if status_code != 0:
                    errors = self.describe_reading_status(status_code)
                    description = " | ".join(errors)

                    if not description:
                        description = f"Unknown error code: {status_code}"

                    print(f"Warning: Reading status for channel {channel} indicates an error: {description}")

                    return None

                response = self._query(f"RDGK? {channel}")
            return float(response.strip())

        except Exception as e:
            print(f"Reading channel {channel} failed.\nReason: {e}")
            return None
        
    def get_resistance(self, channel: int):
        """ 
            Get resistance read by channel {channel}. 
            Given in Ohms
        """
        try:
            with _lakeshore_mutex:
                response = self._query(f"RDGR? {channel}")
            return float(response.strip())
        except Exception as e:
            print(f"Reading channel {channel} failed.\nReason: {e}")
            return None
    
    def get_power(self, channel: int):
        """ 
            Get excitation power read by channel {channel}. 
            Given in Watts
        """
        try:
            with _lakeshore_mutex:
                response = self._query(f"RDGPWR? {channel}")
            return float(response.strip())
        except Exception as e:
            print(f"Reading channel {channel} failed.\nReason: {e}")
            return None

    def get_channel_status(self, channel: int, verbose=False):
        try:
            with _lakeshore_mutex:
                response = self._query(f"INSET? {channel}")
            status = int(response.split(",")[0])
            #time.sleep(0.1)  # Wait for the device to respond
            if verbose:
                if status == '1':
                    print(f"Channel {channel} is ON.")
                else:
                    print(f"Channel {channel} is OFF.")

            return status
                
        except Exception as e:
            print(f"Getting channel {channel} status failed.\nReason: {e}")
            return None

    def get_channel_setpoint(self, channel: int = 6):
        """
        Get the temperature setpoint for a specific channel.
        Args:
            channel (int): The channel number (1, 2, 5, or 6).
        Returns:
            float: The temperature setpoint in Kelvin.
        """
        if channel != 6:
            print(f"Channel {channel} is not valid for getting temperature setpoint. Valid channel is: 6 (MXC).")
            return None

        try:
            with _lakeshore_mutex:
                response = self._query("SETP?") # removed channel since there's only one setpoint for the device
            return float(response.strip())

        except Exception as e:
            print(f"Getting temperature setpoint for channel {channel} failed.\nReason: {e}")
            return None

    def get_temperature_setpoint(self):
        try:
            channel = 6 # MXC channel
            with _lakeshore_mutex:
                response = self._query("SETP?") # removed channel since there's only one setpoint for the device
            return float(response.strip())
        except Exception as e:
            print(f"Getting temperature setpoint for channel {channel} failed.\nReason: {e}")
            return None

    def get_control_mode(self) -> int | None:
        """
        Return the temperature-control mode reported by CMODE?.

        Mode 1 is closed-loop PID control.
        Mode 4 disables temperature control.
        """
        try:
            response = self._query("CMODE?")
            return int(response.strip())

        except Exception as e:
            print(
                "Getting temperature control mode failed."
                f"\nReason: {e}"
            )
            return None

    def get_ramp_parameters(self) -> dict | None:
        """
        Return the configured ramp state and rate.

        Returns:
            dict: Ramp enabled state and rate in K/min.
        """
        try:
            response = self._query("RAMP?")
            fields = [
                field.strip()
                for field in response.strip().split(",")
            ]

            if len(fields) != 2:
                raise ValueError(
                    f"Unexpected RAMP? response: {response!r}"
                )

            return {
                "enabled": bool(int(fields[0])),
                "rate_k_per_min": float(fields[1]),
            }

        except Exception as e:
            print(
                "Getting setpoint ramp parameters failed."
                f"\nReason: {e}"
            )
            return None

    def get_ramp_status(self) -> bool | None:
        """
        Return True only while the setpoint is actively ramping.
        """
        try:
            response = self._query("RAMPST?")
            return bool(int(response.strip()))

        except Exception as e:
            print(
                "Getting setpoint ramp status failed."
                f"\nReason: {e}"
            )
            return None

    def get_control_parameters(self) -> dict:

        """
        Get control parameters (P, I, D) from the channel 6 of the Lakeshore 370 AC device.
        
        The device returns a string in the format "nnnnnn,nnnnn,nnnnn" where each nnnnn is a floating point number.
        1. P: Proportional gain
        2. I: Integral gain
        3. D: Derivative gain

        Returns:
            dict: A dictionary containing the control parameters.
        """
        try:
            with _lakeshore_mutex:
                response = self._query("PID?")
            parameters = response.split(",")
            control_params = {
                "P": float(parameters[0]),
                "I": float(parameters[1]),
                "D": float(parameters[2]),
            }
            
            return control_params
        
        except Exception as e:
            print(f"Getting control parameters failed.\nReason: {e}")
            return None

    def get_dwell_time(self, channel: int):
        try:
            with _lakeshore_mutex:
                response = self._query(f"INSET? {channel}")
            dwell_time = int(response.split(",")[1])
            return dwell_time
        except Exception as e:
            print(f"Getting dwell time for channel {channel} failed.\nReason: {e}")
            return None
    
    def get_pause_time(self, channel: int):
        try:
            with _lakeshore_mutex:
                response = self._query(f"INSET? {channel}")
            pause_time = int(response.split(",")[2])
            return pause_time
        except Exception as e:
            print(f"Getting pause time for channel {channel} failed.\nReason: {e}")
            return None
    
    def get_autoscan(self) -> bool:
        
        """
        Asks the lakeshore controller for the autoscan status and what channel is set in autoscan
        """
        
        try:
            with _lakeshore_mutex:
                current_status = self._query("SCAN?")
            return current_status.split(",")
        except Exception as e:
            print(f"Could not read current autoscan status. Reason: {e}")
            return None
    
    #! --- Multichannel Get methods ----- #
    
    def get_channels_on(self):
        channels_on_list = []
        for channel in ALL_CHANNELS:
            if bool(self.get_channel_status(channel)): channels_on_list.append(channel)
        
        return channels_on_list
    
    def get_channels_dwell_time(self, channels=None):

        if channels is None:
            channels = DEFAULT_CHANNELS

        dwell_times = {}

        if not isinstance(channels, list):
            print("Channels must be a list of integers.")
            return None

        for index, channel in enumerate(channels):

            dwell = self.get_dwell_time(channel)

            if dwell is None:
                print(f"Failed to get dwell time for channel {channel}.")

            # Store the dwell time in a dictionary
            if dwell_times is not None and dwell is not None:
                dwell_times[DEFAULT_CHANNELS_ID[index]] = dwell

        return dwell_times
    
    def get_channels_pause_time(self, channels=None):

        if channels is None:
            channels = DEFAULT_CHANNELS

        pause_times = {}

        if not isinstance(channels, list):
            print("Channels must be a list of integers.")
            return None

        for index, channel in enumerate(channels):

            pause = self.get_pause_time(channel)
            if pause is None:
                print(f"Failed to get dwell or pause time for channel {channel}.")

            # Store the pause time in a dictionary
            if pause_times is not None and pause is not None:
                pause_times[DEFAULT_CHANNELS_ID[index]] = pause

        return pause_times

    def get_control_settings(self, return_dict=False):

        """
        Get the control settings from the Lakeshore 370 device.
        Returns:
            list: A list containing the control settings in the order:
                [controlled channel, filtered readings, units, delay, heater current display, heater range, heater resistance]

            controlled_channel: str - from 1 to 16 (1 = 50K, 2 = 4K, 5 = STILL, 6 = MXC)
            filtered_readings:  int - 1 for True (filtered readings are used), 0 for False (unfiltered readings are used)
            units: 1 for Kelvin, 2 for Ohms
            delay: int - delay in seconds
            heater current display: if 1 heater output display is current, if 2 heater output display is power
            heater range: str - from 1 to 8 (see CURRENT_RANGE_LIST for values)
            heater resistance: float - heater resistance in Ohms
        Raises:
            Exception: If there is an error communicating with the device.
        """

        try:
            with _lakeshore_mutex:
                response = self._query("CSET?")
            
            if return_dict: 
                control_params = response.strip().split(",")
                return _translate_control_settings_to_dictionary(control_params)

            else: return response.strip().split(",")

        except Exception as e:
            print(f"Getting control settings failed.\nReason: {e}")
            return None


    def get_control_channel(self):

        """
        Get the controlled channel from the Lakeshore 370 device.
        Returns:
            str: The controlled channel (e.g., "MXC").
        """

        try:
            controlled_channel = self.get_control_settings()[0]

            if controlled_channel == '6':
                return "MXC"
            elif controlled_channel == '5':
                return "STILL"
            elif controlled_channel == '2':
                return "4K"
            elif controlled_channel == '1':
                return "50K"
            else:
                print(f"Unknown controlled channel: {controlled_channel}")
                return None
        except Exception as e:
            print(f"Getting controlled channel failed.\nReason: {e}")
            return None

    def get_control_range(self):

        """
        Get the control range from the Lakeshore 370 device.
        Args:
        Returns:
            str|dict: The control range (e.g., "4K") or a dictionary with the control range.
        """

        try:
            with _lakeshore_mutex:
                response = self._query("HTRRNG?")
            control_heater_range = response.strip()
            time.sleep(0.1)  # Wait for the device to respond
            control_settings = self.get_control_settings()
            control_heater_display = control_settings[4]
            if control_heater_display == '1':
                return control_heater_range
            elif control_heater_display == '2':
                print("Heater output display is power, not current. NOT DEFINED YET.")
                return None
            else:
                print(f"Unknown heater display value: {control_heater_display}")
                return None
        except Exception as e:
            print(f"Getting control range failed.\nReason: {e}")
       
            return None
    
    def get_sensor_resistance_settings(self, channel: int = 6, return_dict=False) -> str|dict:

        """
        Get the sensor resistance settings used for the specified channel.
        Args:
            channel (int): The channel number (default is 6).
            return_dict (bool): If True, return a dictionary with the sensor resistance settings.
        Returns:
            str|dict: The sensor resistance settings (e.g., "2.00 uV and 1.00 pA") or a dictionary with the settings.
        """

        if channel not in DEFAULT_CHANNELS:
            print(f"Channel {channel} is not valid. Valid channels are: {DEFAULT_CHANNELS}")
            return None
        
        try:
            with _lakeshore_mutex:
                response = self._query(f"RDGRNG? {channel}")
            
            values = response.strip().split(",")

            if return_dict:
                return _translate_sensor_resistance_settings_to_dictionary(values)
            else:
                return values

        except Exception as e:
            print(f"Getting sensor resistance settings for channel {channel} failed.\nReason: {e}")
            return None


    def get_channel_curve(self, channel: int) -> int | None:
        """
        Devuelve el número de curva configurado en un canal (campo 4 de INSET?).
        """
        if channel not in DEFAULT_CHANNELS:
            print(f"Channel {channel} is not valid. Valid channels are: {DEFAULT_CHANNELS}")
            return None

        try:
            with _lakeshore_mutex:
                parameters = self._query(f"INSET? {channel}").split(",")
            curve = int(parameters[3])
            return curve
        except Exception as e:
            print(f"Getting curve for channel {channel} failed.\nReason: {e}")
            return None
        
    def get_heater_output_percent(self):
        """
        Get heater output as percentage of full scale (0–100 %).
        """
        try:
            with _lakeshore_mutex:
                response = self._query("HTR?")
            return float(response.strip())
        except Exception as e:
            print(f"Getting heater output failed.\nReason: {e}")
            return None
        
    # ! -- Device set Methods -- #

    def set_temperature_setpoint(self, value: float, units: str = 'K', verbose=False):
        # Value can be in Kelvin or Ohms, depending on the device configuration.
        if units not in ['K', 'Ohms']:
            print("Units must be 'K' or 'Ohms'.")
            return
        try:
            with _lakeshore_mutex:
                self._write(f"SETP {value}")
            if verbose: print(f"Set temperature setpoint to {value} {units}.")
        except Exception as e:
            print(f"Setting temperature setpoint failed.\nReason: {e}")

    def set_channel_off(self, channel: int, verbose: bool = False):
        try:
            parameters = self._query(f"INSET? {channel}").split(",")
            time.sleep(0.5)  # Wait for the device to respond
            if parameters[0] == '0':
                print(f"Channel {channel} is already off.")
                return False
                
            else:
                dwell = parameters[1]
                pause = parameters[2]
                curve = parameters[3]
                temp_coeff = parameters[4]
                if verbose: print(f"Setting channel {channel} off.")
                self._write(f"INSET {channel},0,{dwell},{pause},{curve},{temp_coeff}")
                if verbose: print(f"Channel {channel} is now set off")
                # if the other parameters are not specificied command won't work
                return True

        except Exception as e:
            print(f"Setting channel {channel} off failed.\nReason: {e}")
            return False
    
    def set_channel_on(self, channel: int, settings=None, verbose: bool = False):
        
        if channel not in DEFAULT_CHANNELS:
            print(f"Channel {channel} is not valid. Valid channels are: {DEFAULT_CHANNELS}")
            return False

        if settings is None:
            try:
                with _lakeshore_mutex:
                    parameters = self._query(f"INSET? {channel}").split(",")
                time.sleep(0.5)  # Wait for the device to respond
                dwell = parameters[1]
                pause = parameters[2]
                curve = parameters[3]
                temp_coeff = parameters[4]
                if verbose: print(f"Setting channel {channel} on.")
                self._write(f"INSET {channel},1,{dwell},{pause},{curve},{temp_coeff}")
                if verbose: print(f"Channel {channel} is set on with parameters: {dwell}, {pause}, {curve}, {temp_coeff}")
                return True
            except Exception as e:
                print(f"Reading channel {channel} parameters failed when switching on.\nReason: {e}")
                return False
        else: 
            if len(settings) != 4:
                print("Settings must be a list of 4 elements: [dwell time, pause time, curve number, temperature coefficient]")
                return False
            dwell, pause, curve, temp_coeff = settings
            
            try:
                with _lakeshore_mutex:
                    self._write(f"INSET {channel},1,{dwell},{pause},{curve},{temp_coeff}")
                print(f"Channel {channel} is set on with custom parameters: {dwell}, {pause}, {curve}, {temp_coeff}")
                return True
            except Exception as e:
                print(f"Setting channel {channel} on failed.\nReason: {e}")
                return False

    def set_autoscan(self, status: bool | str = "Off", channel: int = 6) -> bool:
        
        """
        Set autoscan ON/OFF. Accepts bool or common string forms ("on"/"off", "1"/"0", "true"/"false", "yes"/"no").
        Returns True if a change was made, False if already in that state or on error.
        """
        
        # Normalizing status to bool
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

        # Read current status from the instrument
        try:
            current_status = self._query("SCAN?")  # e.g., "... ,0" or "... ,1"
            print(current_status)
            current_status = current_status.strip().split(",")[-1].strip()
            current_bool = bool(int(current_status))  # 0 -> False, 1 -> True
        except Exception as e:
            print(f"Could not read current autoscan status. Reason: {e}")
            return False

        if status_bool == current_bool:
            print(f"Autoscan is already {'ON' if current_bool else 'OFF'}")
            return True
        else:
            try:
                self._write(f"SCAN {int(channel)},{int(status_bool)}")
                return True
            except Exception as e:
                print(f"Could not set autoscan {'ON' if current_bool else 'OFF'}.\nReason: {e}")
                return False
    def recover_scan(self) -> bool:
        """
        Reinitialize the Lake Shore scan and verify the final state.

        SCAN 6,0 selects channel 6 with autoscan disabled.
        SCAN 1,1 restarts autoscan from channel 1.
        """
        try:
            # Keep the complete recovery sequence atomic.
            with _lakeshore_mutex:
                self._write("SCAN 6,0")
                self._write("SCAN 1,1")
                response = self._query("SCAN?")

            fields = [
                field.strip()
                for field in response.strip().split(",")
            ]

            if len(fields) < 2:
                print(
                    "Unexpected SCAN? response after recovery: "
                    f"{response!r}"
                )
                return False

            channel = int(fields[0])
            autoscan_enabled = int(fields[1])

            if channel == 1 and autoscan_enabled == 1:
                print(
                    "Scan recovered: autoscan ON "
                    "starting at channel 1"
                )
                return True

            print(
                "Scan recovery verification failed: "
                f"SCAN? returned channel={channel}, "
                f"autoscan={autoscan_enabled}"
            )
            return False

        except Exception as e:
            print(
                "Scan recovery failed.\n"
                f"Reason: {e}"
            )
            return False
    
    def set_channel_setpoint(
        self,
        value: float,
        channel: int = 6,
        verbose: bool = True,
        units: str = "mK",
    ) -> bool:
        """
        Set an immediate/manual MXC temperature setpoint.

        A manual setpoint must never use a previously enabled native
        Lake Shore ramp. Therefore, RAMP is explicitly disabled before
        writing the new SETP value.
        """

        if channel != 6:
            print(
                f"Channel {channel} is not valid for setting "
                "temperature setpoint. Valid channel is 6 (MXC)."
            )
            return False

        if units not in ("K", "mK"):
            print("Units must be 'K' or 'mK'.")
            return False

        try:
            value = float(value)
        except (TypeError, ValueError):
            print("Temperature setpoint must be numeric.")
            return False

        if units == "mK":
            value_mk = value
            value_k = value / 1000.0
        else:
            value_k = value
            value_mk = value * 1000.0

        if not (
            MIN_TARGET_TEMPERATURE_MK
            <= value_mk
            <= 500.0
        ):
            print(
                "Temperature setpoint must be between "
                "10 mK and 500 mK."
            )
            return False

        try:
            with _lakeshore_mutex:

                # ------------------------------------------------------
                # A manual SETP must never inherit a previous RAMP state.
                # ------------------------------------------------------

                ramp_parameters = self.get_ramp_parameters()

                if ramp_parameters is None:
                    print(
                        "Could not read ramp configuration before "
                        "setting manual MXC setpoint."
                    )
                    return False

                rate_k_per_min = float(
                    ramp_parameters["rate_k_per_min"]
                )

                if ramp_parameters["enabled"]:

                    print(
                        "⚠️ Native ramp was enabled. "
                        "Disabling it before manual setpoint."
                    )

                    self._write(
                        f"RAMP 0,{rate_k_per_min:.6g}"
                    )

                    # Verify that RAMP is actually disabled.
                    confirmed_ramp = self.get_ramp_parameters()

                    if (
                        confirmed_ramp is None
                        or confirmed_ramp["enabled"]
                    ):
                        print(
                            "❌ Could not disable native ramp "
                            "before manual setpoint."
                        )
                        return False

                # ------------------------------------------------------
                # Apply immediate setpoint.
                #
                # SETP has no channel argument on the Model 370.
                # ------------------------------------------------------

                print(
                    f"✏️ Setting temperature setpoint for "
                    f"channel {channel} to {value_k} K."
                )

                self._write(
                    f"SETP {value_k:.12g}"
                )

                # ------------------------------------------------------
                # Verify SETP and make sure no ramp started.
                # ------------------------------------------------------

                confirmed_setpoint_k = (
                    self.get_temperature_setpoint()
                )

                ramp_active = self.get_ramp_status()

                confirmed_ramp = self.get_ramp_parameters()

            if confirmed_setpoint_k is None:
                print(
                    "❌ Could not verify MXC setpoint."
                )
                return False

            if abs(
                float(confirmed_setpoint_k) - value_k
            ) > 1e-6:
                print(
                    "❌ MXC setpoint verification failed: "
                    f"requested {value_k} K, "
                    f"reported {confirmed_setpoint_k} K."
                )
                return False

            if ramp_active:
                print(
                    "❌ Unexpected ramp started after "
                    "manual setpoint."
                )
                return False

            if (
                confirmed_ramp is None
                or confirmed_ramp["enabled"]
            ):
                print(
                    "❌ Native ramp remains enabled after "
                    "manual setpoint."
                )
                return False

            if verbose:
                print(
                    f"Set temperature setpoint for "
                    f"channel {channel} to {value_k} K."
                )

            return True

        except Exception as e:
            print(
                f"❌ Setting temperature setpoint for "
                f"channel {channel} failed."
                f"\nReason: {e}"
            )
            return False
    def set_ramp(
        self,
        enabled: bool,
        rate_k_per_min: float,
    ) -> bool:
        """
        Configure the native setpoint ramp and verify it with RAMP?.

        Args:
            enabled: True to enable ramping, False to disable it.
            rate_k_per_min: Ramp rate in K/min.

        Returns:
            bool: True if the requested configuration was accepted.
        """
        try:
            rate_k_per_min = float(rate_k_per_min)

        except (TypeError, ValueError):
            print("Ramp rate must be numeric.")
            return False
        
        print('Rate:', rate_k_per_min)
        if not (
            MIN_RAMP_RATE_K_PER_MIN
            <= rate_k_per_min * 1000
            <= MAX_RAMP_RATE_K_PER_MIN
        ):
            print(
                "Ramp rate must be between "
                f"{MIN_RAMP_RATE_K_PER_MIN} and "
                f"{MAX_RAMP_RATE_K_PER_MIN} K/min."
            )
            return False

        enabled_value = int(bool(enabled))

        try:
            with _lakeshore_mutex:
                self._write(
                    f"RAMP {enabled_value},{rate_k_per_min:.6g}"
                )
                response = self._query("RAMP?")

            fields = [
                field.strip()
                for field in response.strip().split(",")
            ]

            if len(fields) != 2:
                print(
                    f"Unexpected RAMP? response: {response!r}"
                )
                return False

            configured_enabled = int(fields[0])
            configured_rate = float(fields[1])

            return (
                configured_enabled == enabled_value
                and abs(
                    configured_rate - rate_k_per_min
                ) <= 5e-7
            )

        except Exception as e:
            print(
                "Setting setpoint ramp failed."
                f"\nReason: {e}"
            )
            return False

    def start_ramp(
        self,
        target_mk: float,
        rate_k_per_min: float,
        channel: int = 6,
    ) -> dict:
        """
        Validate the closed-loop MXC setup and start the native 370 ramp.

        The complete preflight and RAMP/SETP sequence is kept atomic with the
        same communication RLock used by every query and write.
        """
        try:
            target_mk = float(target_mk)
            rate_k_per_min = float(rate_k_per_min)

        except (TypeError, ValueError) as e:
            return {
                "ok": False,
                "error": f"Invalid numeric value: {e}",
            }

        if channel != 6:
            return {
                "ok": False,
                "error": "The controlled MXC channel must be 6.",
            }

        if not (MIN_TARGET_TEMPERATURE_MK <= 
                target_mk <= 
                MAX_TARGET_TEMPERATURE_MK):
            return {
                "ok": False,
                "error": (
                    "Target temperature must be between "
                    f"{MIN_TARGET_TEMPERATURE_MK} and "
                    f"{MAX_TARGET_TEMPERATURE_MK} mK."
                ),
            }
        print('Rate:', rate_k_per_min)
        if not (
            MIN_RAMP_RATE_K_PER_MIN
            <= rate_k_per_min
            <= MAX_RAMP_RATE_K_PER_MIN
        ):
            return {
                "ok": False,
                "error": (
                    "Ramp rate must be between "
                    f"{MIN_RAMP_RATE_K_PER_MIN} and "
                    f"{MAX_RAMP_RATE_K_PER_MIN} mK/min."
                ),
            }

        target_k = target_mk / 1000.0

        try:
            with _lakeshore_mutex:
                control_settings = self.get_control_settings(
                    return_dict=True
                )
                control_mode = self.get_control_mode()
                heater_range = self._query("HTRRNG?").strip()
                mxc_status = self.get_reading_status(channel)
                initial_setpoint_k = (
                    self.get_temperature_setpoint()
                )

                if control_settings is None:
                    return {
                        "ok": False,
                        "error": (
                            "CSET? did not return valid data."
                        ),
                    }

                if (
                    int(control_settings["controlled_channel"])
                    != channel
                ):
                    return {
                        "ok": False,
                        "error": (
                            "CSET control channel is not "
                            "MXC channel 6."
                        ),
                    }

                if control_settings["units"] != "Kelvin":
                    return {
                        "ok": False,
                        "error": (
                            "CSET units must be Kelvin for "
                            "setpoint ramping."
                        ),
                    }

                if control_mode != 1:
                    return {
                        "ok": False,
                        "error": (
                            "CMODE must be 1 "
                            "(closed-loop PID)."
                        ),
                    }

                if int(heater_range) <= 0:
                    return {
                        "ok": False,
                        "error": "The MXC heater range is off.",
                    }

                if mxc_status is None or mxc_status != 0:
                    return {
                        "ok": False,
                        "error": (
                            f"MXC RDGST status is "
                            f"{mxc_status!r}, not 000."
                        ),
                    }

                if initial_setpoint_k is None:
                    return {
                        "ok": False,
                        "error": (
                            "Could not read the initial "
                            "MXC setpoint."
                        ),
                    }

                if not self.set_ramp(
                    True,
                    rate_k_per_min,
                ):
                    return {
                        "ok": False,
                        "error": (
                            "RAMP configuration "
                            "verification failed."
                        ),
                    }

                self._write(f"SETP {target_k:.12g}")

                current_setpoint_k = (
                    self.get_temperature_setpoint()
                )
                ramp_active = self.get_ramp_status()
                
                print(
                    "Ramp start verification:"
                    f"\n  Initial SETP: {initial_setpoint_k:.6f} K"
                    f"\n  Current SETP: {current_setpoint_k} K"
                    f"\n  Target SETP:  {target_k:.6f} K"
                    f"\n  RAMPST?:      {ramp_active}"
                )

                if current_setpoint_k is None:
                    return {
                        "ok": False,
                        "error": "Could not verify SETP? after ramp start.",
                    }

                if ramp_active is None:
                    return {
                        "ok": False,
                        "error": "Could not read RAMPST? after ramp start.",
                    }

                if (
                    abs(target_k - initial_setpoint_k) > 1e-6
                    and not ramp_active
                ):
                    return {
                        "ok": False,
                        "error": (
                            "Lake Shore accepted the RAMP configuration "
                            "but RAMPST? reports that the setpoint is not ramping."
                        ),
                    }

            if (
                current_setpoint_k is None
                or ramp_active is None
            ):
                return {
                    "ok": False,
                    "error": (
                        "Could not verify SETP?/RAMPST? "
                        "after ramp start."
                    ),
                }

            return {
                "ok": True,
                "initial_setpoint_k": float(
                    initial_setpoint_k
                ),
                "target_k": target_k,
                "rate_k_per_min": rate_k_per_min,
                "current_setpoint_k": float(
                    current_setpoint_k
                ),
                "ramp_active": bool(ramp_active),
            }

        except Exception as e:
            print(
                "Starting MXC ramp failed."
                f"\nReason: {e}"
            )
            return {
                "ok": False,
                "error": str(e),
            }

    def stop_ramp(
        self,
        channel: int = 6,
    ) -> dict:
        """
        Stop the native MXC ramp and disable the ramp feature.

        If a ramp is active, the current measured MXC temperature is
        used as the new hold setpoint before disabling RAMP. This avoids
        leaving the previous ramp target as the active setpoint.

        The function always leaves the Lake Shore ramp feature disabled.
        """
        try:
            with _lakeshore_mutex:

                # ----------------------------------------------------------
                # Read current ramp state and configuration
                # ----------------------------------------------------------

                ramp_active_before = self.get_ramp_status()

                if ramp_active_before is None:
                    return {
                        "ok": False,
                        "error": (
                            "Could not read the initial "
                            "ramp status."
                        ),
                    }

                ramp_parameters = self.get_ramp_parameters()

                if ramp_parameters is None:
                    return {
                        "ok": False,
                        "error": (
                            "Could not read the current "
                            "ramp parameters."
                        ),
                    }

                ramp_enabled_before = bool(
                    ramp_parameters["enabled"]
                )

                rate_k_per_min = float(
                    ramp_parameters["rate_k_per_min"]
                )

                hold_setpoint_k = None

                # ----------------------------------------------------------
                # If actively ramping, replace the old target with the
                # current measured MXC temperature.
                # ----------------------------------------------------------

                if ramp_active_before:

                    current_temperature_k = self.get_temperature(
                        channel
                    )

                    if current_temperature_k is None:
                        return {
                            "ok": False,
                            "error": (
                                "Could not read the current "
                                "MXC temperature."
                            ),
                        }

                    hold_setpoint_k = float(
                        current_temperature_k
                    )

                    # The old SETP is the final ramp target.
                    # Replace it with the current measured temperature
                    # before disabling the ramp.
                    self._write(
                        f"SETP {hold_setpoint_k:.12g}"
                    )

                # ----------------------------------------------------------
                # Disable the ramp feature completely.
                #
                # The rate value must still be supplied by the RAMP command.
                # ----------------------------------------------------------

                self._write(
                    f"RAMP 0,{rate_k_per_min:.6g}"
                )

                # ----------------------------------------------------------
                # Verify final state
                # ----------------------------------------------------------

                confirmed_ramp_parameters = (
                    self.get_ramp_parameters()
                )

                ramp_active_after = (
                    self.get_ramp_status()
                )

                confirmed_setpoint_k = (
                    self.get_temperature_setpoint()
                )

            # --------------------------------------------------------------
            # Validate verification queries
            # --------------------------------------------------------------

            if confirmed_ramp_parameters is None:
                return {
                    "ok": False,
                    "error": (
                        "Could not verify the final "
                        "ramp configuration."
                    ),
                }

            if ramp_active_after is None:
                return {
                    "ok": False,
                    "error": (
                        "Could not verify the final "
                        "ramp status."
                    ),
                }

            if confirmed_setpoint_k is None:
                return {
                    "ok": False,
                    "error": (
                        "Could not verify the final "
                        "MXC setpoint."
                    ),
                }

            # RAMP? must report disabled.
            if confirmed_ramp_parameters["enabled"]:
                return {
                    "ok": False,
                    "error": (
                        "The ramp feature remains enabled "
                        "after the stop command."
                    ),
                }

            # RAMPST? must report no active ramp.
            if ramp_active_after:
                return {
                    "ok": False,
                    "error": (
                        "The setpoint is still actively "
                        "ramping after the stop command."
                    ),
                }

            # --------------------------------------------------------------
            # If there was an active ramp, verify that SETP ended close to
            # the temperature used as the hold value.
            # --------------------------------------------------------------

            if (
                hold_setpoint_k is not None
                and abs(
                    float(confirmed_setpoint_k)
                    - hold_setpoint_k
                ) > 1e-4
            ):
                return {
                    "ok": False,
                    "error": (
                        "Ramp stopped, but the final "
                        "setpoint does not match the "
                        "requested hold temperature."
                    ),
                    "hold_setpoint_k": hold_setpoint_k,
                    "confirmed_setpoint_k": float(
                        confirmed_setpoint_k
                    ),
                }

            return {
                "ok": True,
                "was_active": bool(ramp_active_before),
                "ramp_enabled_before": ramp_enabled_before,
                "hold_setpoint_k": hold_setpoint_k,
                "confirmed_setpoint_k": float(
                    confirmed_setpoint_k
                ),
                "ramp_enabled": False,
                "ramp_active": False,
                "rate_k_per_min": rate_k_per_min,
            }

        except Exception as e:
            print(
                "Stopping MXC ramp failed."
                f"\nReason: {e}"
            )

            return {
                "ok": False,
                "error": str(e),
            }
    
    def set_control_parameters(self, P: float = None, I: float = None, D: float = None, channel: int = 6, verbose: bool = False):
        """
        Set the control parameters (P, I, D) for the channel 6 of the Lakeshore 370 AC device.
        
        Args:
            P (float): Proportional gain.
            I (float): Integral gain.
            D (float): Derivative gain.
            channel (int): The channel number (default is 6).
            verbose (bool): If True, prints confirmation messages.
        
        Returns:
            bool: True if the operation was successful, False otherwise.
        """
        if channel != 6:
            print(f"Channel {channel} is not valid for setting control parameters. Valid channel is: 6 (MXC).")
            return False
        
        try:
            if P is None: P = self.get_control_parameters().get("P", DEFAULT_PID["P"])
            if I is None: I = self.get_control_parameters().get("I", DEFAULT_PID["I"])
            if D is None: D = self.get_control_parameters().get("D", DEFAULT_PID["D"])
            with _lakeshore_mutex:
                self._write(f"PID {P},{I},{D}")
            if verbose: print(f"Set control parameters for channel {channel}: P={P}, I={I}, D={D}.")
            return True
        except Exception as e:
            print(f"Setting control parameters for channel {channel} failed.\nReason: {e}")
            return False

    def set_channel_dwell_time(self, dwell_time, channel: int):
        
        """
        Set the dwell time for a specific channel.
        Args:
            dwell_time (int): The dwell time in seconds (1 to 200).
            channel (int): The channel number (1, 2, 5, or 6).
        Returns:
            bool: True if the operation was successful, False otherwise.
        """

        try:
            if dwell_time < 1 or dwell_time > 200:
                print("Dwell time must be between 1 and 200 seconds.")
                return False
            current_dwell_time = self.get_dwell_time(channel)
            if dwell_time == current_dwell_time:
                print(f"Dwell time for channel {channel} is already set to {dwell_time} seconds.")
                return True

            if channel not in DEFAULT_CHANNELS:
                print(f"Channel {channel} is not valid. Valid channels are: {DEFAULT_CHANNELS}")
                return False 
            else:
                with _lakeshore_mutex:
                    parameters = self._query(f"INSET? {channel}").split(",")
                pause = parameters[2]
                curve = parameters[3]
                temp_coeff = parameters[4]
                self._write(f"INSET {channel},1,{dwell_time},{pause},{curve},{temp_coeff}")
                print(f"Dwell time for channel {channel} set to {dwell_time} seconds.")
                return True

        except Exception as e:
            print(f"Getting dwell time for channel {channel} failed.\nReason: {e}")
            return False


    def set_channel_pause_time(self, pause_time, channel: int):
        """
        Set the pause time for a specific channel.
        Args:
            pause_time (int): Pause time in seconds (3 to 200).
            channel (int): Channel number (1, 2, 5, or 6).
        Returns:
            bool: True if the operation was successful, False otherwise.
        """
        try:
            if pause_time < 3 or pause_time > 200:
                print("Pause time must be between 3 and 200 seconds.")
                return False

            if channel not in DEFAULT_CHANNELS:
                print(f"Channel {channel} is not valid. Valid channels are: {DEFAULT_CHANNELS}")
                return False

            with _lakeshore_mutex:
                parameters = self._query(f"INSET? {channel}").split(",")

            dwell = parameters[1]
            curve = parameters[3]
            temp_coeff = parameters[4]

            with _lakeshore_mutex:
                self._write(f"INSET {channel},1,{dwell},{int(pause_time)},{curve},{temp_coeff}")

            print(f"Pause time for channel {channel} set to {pause_time} seconds.")
            return True

        except Exception as e:
            print(f"Setting pause time for channel {channel} failed.\nReason: {e}")
            return False


    def set_channel_curve(self, curve_number : int | None = None, channel : int = 1) -> bool:
        
        """
        Set the curve number for a specific channel.
        Args:
            curve_number (int): The curve number.
            channel (int): The channel number (1, 2, 5, or 6).
        Returns:
            bool: True if the operation was successful, False otherwise.
        """

        if channel not in DEFAULT_CHANNELS:
            print(f"Channel {channel} is not valid. Valid channels are: {DEFAULT_CHANNELS}")
            return False 

        if curve_number is None:
            curve_number = DEFAULT_CURVES[int(channel)]

        if curve_number < 0:
            print(f"Curve number can only be 0 (no curve) or positive")
            return False
        elif curve_number > 20:
            print(f"Curve number cannot be higher than 20")
            return False 

        try:
            with _lakeshore_mutex:
                parameters = self._query(f"INSET? {channel}").split(",")
            current_curve = parameters[3]
            if int(current_curve) == int(curve_number):
                print(f"Curve number {int(curve_number)} is already set to channel {int(channel)}")
                return True
            dwell = parameters[1]
            pause = parameters[2]
            temp_coeff = parameters[4]
            self._write(f"INSET {channel},1,{dwell},{pause},{int(curve_number)},{temp_coeff}")
            print(f"Curve #{int(curve_number)} succesfully set to channel {channel}.")
            return True

        except Exception as e:
            print(f"Setting curve for channel {channel} failed.\nReason: {e}")
            return False

        return False


    def set_control_settings(self, settings: list, verbose: bool = True) -> bool:

        """
        Set the control settings for the Lakeshore 370 device. 
        Args:
            settings (list): A list containing the control settings in the order:
                [controlled channel, filtered readings, units, delay, heater current display, heater range, heater resistance]
            verbose (bool): If True, prints confirmation messages.
        Returns:
            bool: True if the operation was successful, False otherwise.
        """

        if len(settings) != 7:
            print("Settings must be a list of 7 elements: [controlled channel, filtered readings, units, delay, heater current display, heater range, heater resistance]")
            return False

        controlled_channel = int(settings[0])
        filtered_readings = settings[1]
        units = settings[2]
        delay = settings[3]
        heater_display = settings[4]
        heater_range = settings[5]
        heater_resistance = settings[6]

        if controlled_channel not in DEFAULT_CHANNELS:
            print(f"Controlled channel {controlled_channel} is not valid. Valid channels are: {DEFAULT_CHANNELS}")
            return False

        try:
            with _lakeshore_mutex:
                self._write(f"CSET {controlled_channel},{filtered_readings},{units},{delay},{heater_display},{str(heater_range)},{heater_resistance}")
            if verbose: print(f"Control settings set to: {settings}")
            return True
        except Exception as e:
            print(f"Setting control settings failed.\nReason: {e}")
            return False

    def set_control_range(self, range_value:str, verbose: bool = True) -> bool:

        """
        Set the control range for the Lakeshore 370 device heater. 
        Args:
            range_value (str): The control range value (e.g., "1", "2", ..., "8").
            verbose (bool): If True, prints confirmation messages.
        Returns:
            bool: True if the operation was successful, False otherwise.
        """

        if range_value not in CURRENT_RANGE_LIST:
            print(f"Control range {range_value} is not valid. Valid ranges are: {list(CURRENT_RANGE_LIST.keys())}")
            return False

        try:
            with _lakeshore_mutex:
                self._write(f"HTRRNG {range_value}")
            if verbose: print(f"Control range set to: {CURRENT_RANGE_LIST[range_value][0]}")
            return True
        except Exception as e:
            print(f"Setting control range failed.\nReason: {e}")
            return False

    def set_control_settings_channel(self, channel: int = 6, verbose: bool = True) -> bool:

        """
        Set the controlled channel for the Lakeshore 370 device.
        Args:
            channel (int): The channel number to set as controlled (1, 2, 5, or 6).
            verbose (bool): If True, prints confirmation messages.
        Returns:
            bool: True if the operation was successful, False otherwise.
        """

        if channel not in DEFAULT_CHANNELS:
            print(f"Channel {channel} is not valid. Valid channels are: {DEFAULT_CHANNELS}")
            return False

        current_settings = self.get_control_settings()
        time.sleep(0.2)  # Wait for the device to respond
        if current_settings is None:
            print("Failed to get current control settings.")
            return False
        else:
            try:
                with _lakeshore_mutex:
                    self._write(f"CSET {channel},{current_settings[1]},{current_settings[2]},{current_settings[3]},{current_settings[4]},{current_settings[5]},{current_settings[6]}")
                if verbose: print(f"Control channel set to {channel}.")
                return True

            except Exception as e:
                print(f"Setting control channel to {channel} failed.\nReason: {e}")
                return False

    def set_sensor_resistance_settings(self, channel: int = 6, settings: dict | None = None, verbose: bool = True) -> bool:
        
        """
        Set the sensor resistance settings for the specified channel.
        Args:
            channel (int): The channel number (default is 6).
            settings (dict): A dictionary containing the sensor resistance settings.
                Example: {"excitation_mode": 0, "excitation_range": 5, "resistance_range": 3, "autorange": 1, "excitation": 1}
            verbose (bool): If True, prints confirmation messages.
        Returns:
            bool: True if the operation was successful, False otherwise.
        """

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
        
        cmd = (
            f"RDGRNG {channel},"
            f"{excitation_mode},"
            f"{excitation_range},"
            f"{resistance_range},"
            f"{autorange},"
            f"{excitation},"
        )
        
        print(cmd)
        
        try:
            with _lakeshore_mutex:
                self._write(cmd)
            if verbose: 
                print(f"Sensor resistance settings for channel {channel} set to: {settings}")
            return True
        except Exception as e:
            print(f"Setting sensor resistance settings for channel {channel} failed.\nReason: {e}")
            return False

    # ! -- Device control Methods -- #
    def close(self):
        try:

            with _lakeshore_mutex:
                self.device.close()
            print("Device connection closed.")
            return True
        except Exception as e:
            print(f"Failed to close device connection.\nReason: {e}")
            return False
        
def _translate_control_settings_to_dictionary(control_params: list) -> dict:

    controlled_channel = control_params[0]
    filtered_readings = True if control_params[1] == '1' else False
    units = "Kelvin" if control_params[2] == '1' else "Ohms"
    delay = int(control_params[3])
    heater_resistance = float(control_params[6])
    heater_display = float(control_params[4]) # current = 1, power = 2 - default is current
    heater_range = control_params[5] # check CURRENT_RANGE_LIST for range values

    control_settings = {
        "controlled_channel": controlled_channel,
        "filtered_readings": filtered_readings,
        "units": units,
        "delay": delay,
        "heater_display": heater_display,
        "HR": heater_range, # Heater range as integer from 1 to 8 / check CURRENT_RANGE_LIST for ranges
        "heater_resistance": heater_resistance,
    }
    
    return control_settings

def _translate_sensor_resistance_settings_to_dictionary(values: list) -> dict:

    """
    Translate the sensor resistance settings from a list to a dictionary.
    Args:
        values (list): A list containing the sensor resistance settings.
    Returns:
        dict: A dictionary with the translated sensor resistance settings.
    """

    excitation_mode = values[0]         # 0 for voltage, 1 for current
    excitation_range = str(int(values[1]))        # check SENSOR_RESISTANCE_RANGE_LIST for range values
    resistance_range = str(int(values[2]))        # check RESISTANCE_RANGE_LIST for range values
    autorange = values[3]
    excitation = values[4]

    sensor_resistance_settings = {
                "excitation_mode": excitation_mode,
                "excitation_range": excitation_range,
                "resistance_range": resistance_range,
                "autorange": autorange,
                "excitation": excitation
    }

    return sensor_resistance_settings

def _b2i(x):
    " Normalize bool-like fields to ints "
    return int(x) if isinstance(x, (bool, int)) else x

def _i2s(x):
    "Normalize to range format"
    x = str(x)
    if len(x) == 1: x = "0" + x
    elif len(x) == 2: x = x
    else: raise("Excitation range format wrong. Only permited str or int.")
    return x
    