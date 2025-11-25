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

DEFAULT_CHANNELS = [1, 2, 5, 6]
DEFAULT_CHANNELS_ID = ["50K", "4K", "STILL", "MXC"]
DEFAULT_MXC_SETPOINT_MK = 100.0
DEFAULT_MXC_HEATER_RANGE = "5"

DEFAULT_SENSOR_RESISTANCE_SETTINGS = {
    1: {  # 50K
        "excitation_mode": 0,   # 0 = voltage, 1 = current
        "excitation_range": 5,  # por ejemplo, la misma que MXC o la que tú quieras
    },
    2: {  # 4K
        "excitation_mode": 0,
        "excitation_range": 5,
    },
    5: {  # STILL
        "excitation_mode": 0,
        "excitation_range": 5,
    },
}