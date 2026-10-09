// INMUTABLE CONSTANTS.
// ToDo: check if there are freeze methods to make them inmutable.
export const RELATION_LIVE_POINTS = 400;
export const SAMPLE_CHANNELS = [9, 10, 11, 12, 13, 14];
export const SAMPLE_VOLTAGE_EXCITATION_RANGES = [
    [1, "2.00 µV"],
    [2, "6.32 µV"],
    [3, "20.0 µV"],
    [4, "63.2 µV"],
    [5, "200 µV"],
    [6, "632 µV"],
    [7, "2.00 mV"],
    [8, "6.32 mV"],
    [9, "20.0 mV"],
    [10, "63.2 mV"],
    [11, "200 mV"],
    [12, "632 mV"],
];

export const SAMPLE_CURRENT_EXCITATION_RANGES = [
    [1, "1.00 pA"],
    [2, "3.16 pA"],
    [3, "10.0 pA"],
    [4, "31.6 pA"],
    [5, "100 pA"],
    [6, "316 pA"],
    [7, "1.00 nA"],
    [8, "3.16 nA"],
    [9, "10.0 nA"],
    [10, "31.6 nA"],
    [11, "100 nA"],
    [12, "316 nA"],
    [13, "1.00 µA"],
    [14, "3.16 µA"],
    [15, "10.0 µA"],
    [16, "31.6 µA"],
    [17, "100 µA"],
    [18, "316 µA"],
    [19, "1.00 mA"],
    [20, "3.16 mA"],
    [21, "10.0 mA"],
    [22, "31.6 mA"],
];

export const SAMPLE_RESISTANCE_RANGES = [
    [1, "2.00 mΩ"],
    [2, "6.32 mΩ"],
    [3, "20.0 mΩ"],
    [4, "63.2 mΩ"],
    [5, "200 mΩ"],
    [6, "632 mΩ"],
    [7, "2.00 Ω"],
    [8, "6.32 Ω"],
    [9, "20.0 Ω"],
    [10, "63.2 Ω"],
    [11, "200 Ω"],
    [12, "632 Ω"],
    [13, "2.00 kΩ"],
    [14, "6.32 kΩ"],
    [15, "20.0 kΩ"],
    [16, "63.2 kΩ"],
    [17, "200 kΩ"],
    [18, "632 kΩ"],
    [19, "2.00 MΩ"],
    [20, "6.32 MΩ"],
    [21, "20.0 MΩ"],
    [22, "63.2 MΩ"],
];

// Time range options in seconds (from largest to smallest)
export const timeRangeOptions = [
    { value: 60, label: "1 Minute" },
    { value: 300, label: "5 Minutes" },
    { value: 900, label: "15 Minutes" },
    { value: 1800, label: "30 Minutes" },
    { value: 3600, label: "1 Hour" },
    { value: 21600, label: "6 Hours" },
];

// IDs for MXC control parameters
export const MXC_CONTROL_IDS = [
    "temperatureSetpointMXC",
    "proportionalGainMXC",
    "integralGainMXC",
    "derivativeGainMXC",
    "heaterRangeMXC",
];

export const MXC_SENSOR_IDS = [
    "dwellMXC",
    "pauseMXC",
    "sensorRangeMXC",
    "sensorModeMXC",
];

export const parameterBoxUpdateInterval = 60000; // 1 minute = 60000 milliseconds


// Mutable constants

export const relationDataStore = {
    CH9 : [], CH10: [], CH11: [], CH12: [], CH13: [], CH14: [],
};

export const pendingSampleToggle = {};

export const pendingExtraChannels = {
    9: false, 10: false, 11: false, 12: false, 13: false, 14: false,
};

// Track charts for each stage
export const charts = {
    "50K": null, "4K": null, STILL: null, MXC: null, BB: null,
};

// Store chart data for each stage
export const chartDataStore = {
    "50K": {
        labels: [], data: [], startTime: null, lastTimestamp: null,
    },
    "4K": {
        labels: [], data: [], startTime: null, lastTimestamp: null,
    },
    STILL: {
        labels: [], data: [], startTime: null, lastTimestamp: null,
    },
    MXC: {
        labels: [], data: [], setpoint: [], startTime: null, lastTimestamp: null,
    },
    BB: { 
        labels: [], data: [], setpoint: []
    },
};

// Track parameter values
export const currentParameters = {
    "50K": null,
    "4K": null,
    STILL: null,
    MXC: null,
    MXCSP: null,
    MXCP: null,
    MXCI: null,
    MXCD: null,
    MXCHR: null,
    dwellMXC: null,
    pauseMXC: null,
    modeMXC: null,
    rangeMXC: null,
    autorangeMXC: null,
    temperatureSetpoint: null,
    heaterPower: null,
    heaterRange: null,
    temperatureLimit: null,
    timeout: null,
    proportionalGain: null,
    integralGain: null,
    derivativeGain: null,
    RMXC: null,
    PMXC: null,
    enabledMXC: null,
    enabled50K: null,
    enabled4K: null,
    enabledSTILL: null,
    dwell50K: null,
    pause50K: null,
    dwell4K: null,
    pause4K: null,
    dwellSTILL: null,
    pauseSTILL: null,
    mode50K: null,
    range50K: null,
    mode4K: null,
    range4K: null,
    modeSTILL: null,
    rangeSTILL: null,
    curveMXC: null,
    curve50K: null,
    curve4K: null,
    curveSTILL: null,
    R50K: null,
    P50K: null,
    R4K: null,
    P4K: null,
    RSTILL: null,
    PSTILL: null,
    heaterOutputMXC: null,
    RCH9: null,
    RCH10: null,
    RCH11: null,
    RCH12: null,
    RCH13: null,
    RCH14: null,
    enabledCH9: null,
    enabledCH10: null,
    enabledCH11: null,
    enabledCH12: null,
    enabledCH13: null,
    enabledCH14: null,
    scanning_channel: null,
    modeCH9: null,
    rangeCH9: null,
    modeCH10: null,
    rangeCH10: null,
    modeCH11: null,
    rangeCH11: null,
    modeCH12: null,
    rangeCH12: null,
    modeCH13: null,
    rangeCH13: null,
    modeCH14: null,
    rangeCH14: null,
};

// Track last sent values
export const lastSentValues = {
    temperatureSetpoint: null,
    heaterPower: null,
    heaterRange: null,
    temperatureLimit: null,
    timeout: null,
    proportionalGain: null,
    integralGain: null,
    derivativeGain: null,
    MXCSP: null,
    MXCP: null,
    MXCI: null,
    MXCD: null,
    MXCHR: null,
    dwellMXC: null,
    pauseMXC: null,
    modeMXC: null,
    rangeMXC: null,
    autorangeMXC: null,
};

// Shared state during runtime:

export const state = {
    connection: {
        tcpStatus: null,
        firstDataTime: null,
        lastUpdateTime: null,
    },

    run: {
        hasInitialized: false,
        expectedNextId: null,
        activeId: null,
    },

    relation: {
        running: false,
        chart: null,
        currentChannel: 'CH9',
        stepRamp: {
            relationId: null,
            nextSeq: 0,
            channel: null,
            fetchInProgress: false,
            defaultsLoaded: false,
        },
    },

    chart: {
        temperatureChartBB: null,
        temperatureChart50K: null,
        temperatureChart4K: null,
        temperatureChartSTILL: null,
        temperatureChartMXC: null,
        currentTimeRangeBB: 60,
        currentTimeRangeMXC: 60,
        currentTimeRange50K: 60,
        currentTimeRange4K: 60,
        currentTimeRangeSTILL: 60,
        temperatureData: [],
        setpointData: [],
        absoluteTimeLabels: [],
        relativeTimeLabels: [],
        /*
        absoluteTimeLabels stores timestamps in miliseconds
        relativeTimeLabels stores time values in seconds relative to firstDataTime.
        relativeTimeLabels is used for x-axis labels in charts, and it is calculated
        as (Date.now() - firstDataTime) / 1000
        */
    },

    controls: {
        initialParametersLoaded: false,
        pendingMXCToggle: false,
        pending50KToggle: false,
        pending4KToggle: false,
        pendingSTILLToggle: false,
        pendingAutoscanToggle: false,
        lastParameterBoxUpdateTime: 0,
    },

    // Convenience aliases: use the same objects, never copies.
    currentParameters,
    lastSentValues,
    charts,
    chartDataStore,
    relationDataStore,
    pendingSampleToggle,
    pendingExtraChannels,
};