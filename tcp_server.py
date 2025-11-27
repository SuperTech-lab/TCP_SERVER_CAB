import socket
import random
import time
import threading
from lakeshore370 import LakeShore370
from default_config import (DEFAULT_PID, CURRENT_RANGE_LIST, DEFAULT_MXC_RESISTANCE_RANGE_SETTINGS, SENSOR_RESISTANCE_RANGE_LIST, DEFAULT_CHANNELS, 
DEFAULT_CHANNELS_ID, DEFAULT_SETTINGS, DEFAULT_MXC_SETPOINT_MK, DEFAULT_MXC_HEATER_RANGE, DEFAULT_SENSOR_RESISTANCE_SETTINGS)

ls = LakeShore370()



# Configuration
HOST = '0.0.0.0' # Listen on all network interfaces
PORT = 65432  # Port to listen on

# Mutex to protect the heater power level
heater_mutex = threading.Lock() 


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
    
    if command.startswith("set_temperature_setpoint"):
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
                    message = f"❌ Failed to set dwell time for MXC"
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
            reset_flag = int(parts[2]) if len(parts) > 2 else 1

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
                if bool(channel_status and reset_flag):
                    apply_default_channel_timing(6)
                    apply_default_mxc_settings()
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
            reset_flag = int(parts[2]) if len(parts) > 2 else 1

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
                if bool(channel_status and reset_flag):
                    apply_default_channel_timing(1)
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
            reset_flag = int(parts[2]) if len(parts) > 2 else 1

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
                if bool(channel_status and reset_flag):
                    apply_default_channel_timing(2)
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
            reset_flag = int(parts[2]) if len(parts) > 2 else 1

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
                if bool(channel_status and reset_flag):
                    apply_default_channel_timing(5)
                message = f"✅ STILL sensor is now {'On' if bool(channel_status) else 'Off'}"
            else:
                message = f"❌ Failed to set STILL sensor {'On' if bool(channel_status) else 'Off'}"

            print(message)
            return message

        except Exception as e:
            message = f"❌ Error setting STILL sensor status: {e}"
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

            enabled_channels = []
            with heater_mutex:
                for ch in sorted(DEFAULT_CHANNELS):
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
                channel_enabled_MXC = int(ls.get_channel_status(6))  # MXC is channel 6
                channel_enabled_50K = int(ls.get_channel_status(1))
                channel_enabled_STILL = int(ls.get_channel_status(5))

        except Exception as e:
            print(f"Error reading MXC channel status\nReason: {e}")
            channel_enabled_MXC = 0
        
        try:
            with heater_mutex: tempSetPointMXC = ls.get_temperature_setpoint()  # Channel 6 is MXC
        except Exception as e:
            print(f"Error reading temperature setpoint for MXC from LakeShore\nReason: {e}")
            tempSetPointMXC = None

        try:
            with heater_mutex: LSPID = ls.get_control_parameters()
            proportionalMXC = LSPID['P']
            integralMXC = LSPID['I']
            derivativeMXC = LSPID['D']

            time.sleep(0.1) # Small delay to ensure communictation channel is ready
            
            with heater_mutex: heaterRangeMXC = ls.get_control_range()
            
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
                
                
        controlParams = {
            'MXCSP': tempSetPointMXC,
            'P': proportionalMXC,
            'I': integralMXC,
            'D': derivativeMXC,
            'HR': heaterRangeMXC,
        }

        sensorParams = {
            'sensor_mode'      : modeMXC,
            'sensor_range'     : excitationMXC,
            'sensor_autorange' : autorangeMXC,
            'sensor_mode_50K'   : mode50K,
            'sensor_range_50K'  : excitation50K,
            'sensor_mode_4K'    : mode4K,
            'sensor_range_4K'   : excitation4K,
            'sensor_mode_STILL' : modeSTILL,
            'sensor_range_STILL': excitationSTILL,
            'dwell_times'      : dwell_times,
            'pause_times'      : pause_times,
            'autoscan'         : autoscan,
            'enabledMXC'       : channel_enabled_MXC
        }

        sensorValues = {
            'temperatures' : temperatures,
            'resistances'  : resistances,
            'powers'       : powers,
        }
        
        try:
            broadcast_temperature(sensorValues, controlParams, sensorParams)
        except Exception as e:
            print(f"Error broadcasting temperature data: {e}")
        
        time.sleep(1)

def broadcast_temperature(sensorValues, controlParams, sensorParams):

    temperatures = sensorValues['temperatures']
    resistances  = sensorValues['resistances']
    powers       = sensorValues['powers']
    
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
                    f"RMXC: {resistances['MXC']},"
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
                    f"rangeSTILL: {sensorParams['sensor_range_STILL']}\n"
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


if __name__ == "__main__":
    start_server()