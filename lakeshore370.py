import pyvisa
import threading
import time

# Shared mutex lock for safe device access
_lakeshore_mutex = threading.Lock()

DEFAULT_CHANNELS = [1, 2, 5, 6]
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
    "excitation_mode": 0,       # 0 for voltage, 1 for current
    "excitation_range": 5,      # 5 for 200 uV and 100 pA
    "resistance_range": 14,     # 14 for 3.15 uA R = 6.32 kOhm
    "autorange": 1,             # 0 for NO, 1 for YES
    "excitation": 1,            # 0 for excitation on, 1 = exctiation off
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
                 addr = 'ASRL/dev/ttyUSB0::INSTR',
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
    
    #! -- Device get Methods -- #
    def get_temperature(self, channel: int):
        """ 
            Get temperature read by channel {channel}. 
            Given in Kelvin
        """
        try:
            with _lakeshore_mutex:
                response = self.device.query(f"RDGK? {channel}")
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
                response = self.device.query(f"RDGR? {channel}")
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
                response = self.device.query(f"RDGPWR? {channel}")
            return float(response.strip())
        except Exception as e:
            print(f"Reading channel {channel} failed.\nReason: {e}")
            return None

    def get_channel_status(self, channel: int, verbose=False):
        try:
            with _lakeshore_mutex:
                response = self.device.query(f"INSET? {channel}")
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
                response = self.device.query(f"SETP? {channel}")
            return float(response.strip())

        except Exception as e:
            print(f"Getting temperature setpoint for channel {channel} failed.\nReason: {e}")
            return None

    def get_temperature_setpoint(self):
        try:
            channel = 6 # MXC channel
            with _lakeshore_mutex:
                response = self.device.query(f"SETP? {channel}")
            return float(response.strip())
        except Exception as e:
            print(f"Getting temperature setpoint for channel {channel} failed.\nReason: {e}")
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
                response = self.device.query("PID?")
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
                response = self.device.query(f"INSET? {channel}")
            dwell_time = int(response.split(",")[1])
            return dwell_time
        except Exception as e:
            print(f"Getting dwell time for channel {channel} failed.\nReason: {e}")
            return None
    
    def get_pause_time(self, channel: int):
        try:
            with _lakeshore_mutex:
                response = self.device.query(f"INSET? {channel}")
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
            current_status = self.device.query("SCAN?")
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
                response = self.device.query("CSET?")
            
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
                response = self.device.query("HTRRNG?")
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
                response = self.device.query(f"RDGRNG? {channel}")
            
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
                parameters = self.device.query(f"INSET? {channel}").split(",")
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
                response = self.device.query("HTR?")
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
                self.device.write(f"SETP {value}")
            if verbose: print(f"Set temperature setpoint to {value} {units}.")
        except Exception as e:
            print(f"Setting temperature setpoint failed.\nReason: {e}")

    def set_channel_off(self, channel: int, verbose: bool = False):
        try:
            parameters = self.device.query(f"INSET? {channel}").split(",")
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
                self.device.write(f"INSET {channel},0,{dwell},{pause},{curve},{temp_coeff}")
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
                    parameters = self.device.query(f"INSET? {channel}").split(",")
                time.sleep(0.5)  # Wait for the device to respond
                dwell = parameters[1]
                pause = parameters[2]
                curve = parameters[3]
                temp_coeff = parameters[4]
                if verbose: print(f"Setting channel {channel} on.")
                self.device.write(f"INSET {channel},1,{dwell},{pause},{curve},{temp_coeff}")
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
                    self.device.write(f"INSET {channel},1,{dwell},{pause},{curve},{temp_coeff}")
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
            current_status = self.device.query("SCAN?")  # e.g., "... ,0" or "... ,1"
            print(current_status)
            current_status = current_status.strip().split(",")[-1].strip()
            current_bool = bool(int(current_status))  # 0 -> False, 1 -> True
        except Exception as e:
            print(f"Could not read current autoscan status. Reason: {e}")
            return False

        if status_bool == current_bool:
            print(f"Autoscan is already {'ON' if current_bool else 'OFF'}")
            return False
        else:
            try:
                self.device.write(f"SCAN {int(channel)},{int(status_bool)}")
                return True
            except Exception as e:
                print(f"Could not set autoscan {'ON' if current_bool else 'OFF'}.\nReason: {e}")
                return False
    
    def set_channel_setpoint(self, value: float, channel: int = 6, verbose = True, units: str = 'mK'):
        
        """
        Set the temperature setpoint for a specific channel.
        Args:
            value (float): The temperature setpoint in Kelvin.
            channel (int): The channel number (1, 2, 5, or 6).
        Returns:
            bool: True if the operation was successful, False otherwise.
        """

        if channel != 6:
            print(f"Channel {channel} is not valid for setting temperature setpoint \n. Valid channel is: 6 (MXC).")
            return False

        if units not in ['K', 'mK']:
            print("Units must be 'K' or 'mK'.")
            return False

        if value < 10 or value > 500:
            print("Temperature setpoint must be between 10 mK and 500 mK.")
            return False

        if units == 'mK':
            value = value / 1000 
        elif units == 'K':
            value = value

        try:
            print(f"✏️ Setting temperature setpoint for channel {channel} to {value} K.")
            with _lakeshore_mutex:
                self.device.write(f"SETP {value},{channel}")
            if verbose: print(f"Set temperature setpoint for channel {channel} to {value} K.")
            return True
        except Exception as e:
            print(f"❌Setting temperature setpoint for channel {channel} failed.\nReason: {e}")
            return False
    
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
                self.device.write(f"PID {P},{I},{D}")
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
                    parameters = self.device.query(f"INSET? {channel}").split(",")
                pause = parameters[2]
                curve = parameters[3]
                temp_coeff = parameters[4]
                self.device.write(f"INSET {channel},1,{dwell_time},{pause},{curve},{temp_coeff}")
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
                parameters = self.device.query(f"INSET? {channel}").split(",")

            dwell = parameters[1]
            curve = parameters[3]
            temp_coeff = parameters[4]

            with _lakeshore_mutex:
                self.device.write(f"INSET {channel},1,{dwell},{int(pause_time)},{curve},{temp_coeff}")

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
                parameters = self.device.query(f"INSET? {channel}").split(",")
            current_curve = parameters[3]
            if int(current_curve) == int(curve_number):
                print(f"Curve number {int(curve_number)} is already set to channel {int(channel)}")
                return True
            dwell = parameters[1]
            pause = parameters[2]
            temp_coeff = parameters[4]
            self.device.write(f"INSET {channel},1,{dwell},{pause},{int(curve_number)},{temp_coeff}")
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
                self.device.write(f"CSET {controlled_channel},{filtered_readings},{units},{delay},{heater_display},{str(heater_range)},{heater_resistance}")
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
                self.device.write(f"HTRRNG {range_value}")
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
                    self.device.write(f"CSET {channel},{current_settings[1]},{current_settings[2]},{current_settings[3]},{current_settings[4]},{current_settings[5]},{current_settings[6]}")
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
                self.device.write(cmd)
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
    