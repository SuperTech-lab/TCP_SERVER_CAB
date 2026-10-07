// js/state.js
let hasInitializedRunId = false;
let expectedNextRunId = null;
let relationChart = null;
let currentRelationChannel = "CH9";
const RELATION_LIVE_POINTS = 400;
let currentActiveRunId = null;
let relationRunning = false;

const relationDataStore = { CH9: [], CH10: [], CH11: [], CH12: [], CH13: [], CH14: [], CH15: [] };
const SAMPLE_CHANNELS = [9, 10, 11, 12, 13, 14, 15];
const pendingSampleToggle = {};

let tcpConnectionStatus = null;
let firstDataTime = null;
let lastUpdateTime = null;
let initialParametersLoaded = false;
let pendingMXCToggle = false;
let pending50KToggle = false;
let pending4KToggle = false;
let pendingSTILLToggle = false;
let pendingAutoscanToggle = false;
let pendingExtraChannels = { 9: false, 10: false, 11: false, 12: false, 13: false, 14: false, 15: false };

let currentTimeRangeBB = 60;
let currentTimeRangeMXC = 60;
let currentTimeRange50K = 60;
let currentTimeRange4K = 60;
let currentTimeRangeSTILL = 60;

let currentParameters = {
  "50k": null,
  "4k": null,
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
  RCH15: null,
  enabledCH9: null,
  enabledCH10: null,
  enabledCH11: null,
  enabledCH12: null,
  enabledCH13: null,
  enabledCH14: null,
  enabledCH15: null,
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
  modeCH15: null,
  rangeCH15: null,
};

let lastSentValues = {
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

const charts = { "50K": null, "4K": null, STILL: null, MXC: null, BB: null };
const chartDataStore = {
  "50K": { labels: [], data: [], startTime: null, lastTimestamp: null },
  "4K": { labels: [], data: [], startTime: null, lastTimestamp: null },
  STILL: { labels: [], data: [], startTime: null, lastTimestamp: null },
  MXC: { labels: [], data: [], setpoint: [], startTime: null, lastTimestamp: null },
  BB: { labels: [], data: [], setpoint: [] },
};

const timeRangeOptions = [
  { value: 60, label: "1 Minute" },
  { value: 300, label: "5 Minutes" },
  { value: 900, label: "15 Minutes" },
  { value: 1800, label: "30 Minutes" },
  { value: 3600, label: "1 Hour" },
  { value: 21600, label: "6 Hours" },
];

const MXC_CONTROL_IDS = ["temperatureSetpointMXC", "proportionalGainMXC", "integralGainMXC", "derivativeGainMXC", "heaterRangeMXC"];
const MXC_SENSOR_IDS = ["dwellMXC", "pauseMXC", "sensorRangeMXC", "sensorModeMXC"];

let lastParameterBoxUpdateTime = 0;
const parameterBoxUpdateInterval = 60000;

// Función global de temporización compartida
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}