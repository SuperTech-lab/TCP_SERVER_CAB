import time
import pyvisa
from pyvisa.constants import StopBits, Parity

# Create resource manager
rm = pyvisa.ResourceManager()

# Open the serial port (make sure this matches your system)
try:
    device = rm.open_resource('ASRL/dev/ttyUSB0::INSTR')
    print("Resource Manager Open")
except Exception as e:
    print("Resource Manage failed. \nReason:", e)

# Configure serial parameters
device.baud_rate = 9600
device.data_bits = 7
device.stop_bits = 10
device.parity = pyvisa.constants.Parity.even
device.write_termination = '\r\n'
device.read_termination = '\r\n'
device.timeout = 3000  # milliseconds

# Query the instrument
try:
    print("\n---- Instrument Identification ----")
    idn = device.query("*IDN?")
    print("Instrument ID:", idn)

    print("\n---- Channel Status ----")
    # Example: read temperature from input channel A
    for channel in [1,2,5,6]:
        channel_on = float(device.query(f"INSET? {channel}").split(",")[0])
        if channel_on:
            temp = device.query(f"RDGK? {channel}")
            print(f"Temperature Ch.{channel}:", temp.strip())
        else:
            print(f"Channel {channel} is off")

except Exception as e:
    print("Communication error:", e)

print("\n--- Sensor Resistance Settings For MXC ---")
sensor_resistance_setup = device.query("RDGRNG? 6") # Assuming channel 6 is the MXC
values = sensor_resistance_setup.strip().split(",")
print("Excitation mode: ", "voltage" if values[0] == "0" else "current")
print("Excitation range: ", values[1])
print("Resistance range: ", values[2])
print("Autorange?: ", "YES" if values[3] == "1" else "NO")
print("Exctitation?: ", "YES" if values[4] == "1" else "NO")

print("\n--- Autoscan Status ---")
value = device.query("SCAN?").strip().split(",")
print("Scan on channel: ", value[0])
print("Autoscan: ", "ON" if value[1]== "1" else "OFF")

print("\n--- Temperature Control Status Settings ---")
temperature_control_setup = device.query("CSET?")
print("Current control settings: ", temperature_control_setup.strip())
values = temperature_control_setup.strip().split(",")
print("Controlled channel: ", values[0])
print("Filtered readings?: ", "YES" if values[1] else "NO")
print("Units: ", "Kelvin" if values[2] == 1 else "Ohms")
print("Delay: ", values[3], " seconds")
print("Heater resistance: ", values[6], " Ohms")
print("Heater displayed value: ", "current" if values[4] == str(1) else "power")
print("Heater range limit: ", values[5])

print("\n--- Heater Status ---")
heater_status = device.query("HTRST?")
print("Heater Status: ", "✅" if int(heater_status.strip()) == 0 else "❌")
heater_range = device.query("HTRRNG?")
print("Heater Range: ", heater_range.strip())
heater_output = device.query("HTR?")
print("Heater Output: ", heater_output.strip())

device.write("RDGRNG 6,0,06,14,1,0")
time.sleep(1)  # Allow time for the command to take effect
response = device.query("RDGRNG? 6")
print("Response: ", response.strip())
device.write("SCAN 6,0")
# Clean up
device.close()
