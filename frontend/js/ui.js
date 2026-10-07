// js/ui.js
function addLogEntry(message, type) {
  const logEntry = document.createElement("div");
  logEntry.className = `log-entry log-${type}`;
  logEntry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;

  const logBoxBB = document.getElementById("logBoxBB");
  const logBoxLS = document.getElementById("logBoxLS");

  if (logBoxBB) {
    logBoxBB.appendChild(logEntry.cloneNode(true));
    logBoxBB.scrollTop = logBoxBB.scrollHeight;
  }
  if (logBoxLS) {
    logBoxLS.appendChild(logEntry.cloneNode(true));
    logBoxLS.scrollTop = logBoxLS.scrollHeight;
  }
}

function setupCollapsibleSections(context = document) {
  const sectionTitles = context.querySelectorAll(".section-title");

  sectionTitles.forEach((title) => {
    const content = title.nextElementSibling;
    if (!content) return;

    if (title.classList.contains("collapsed")) {
      content.classList.add("collapsed");
      content.style.maxHeight = "0";
    } else {
      content.classList.remove("collapsed");
      content.style.maxHeight = `${content.scrollHeight}px`;
    }

    if (title.dataset.listenerAttached) return;

    title.addEventListener("click", (event) => {
      if (title.classList.contains("stage-title-mxc")) {
        if (event.target.closest("#mxcTitleControls")) return;
        const clickedTitle = event.target.closest("h2");
        const bounds = title.getBoundingClientRect();
        const clickedArrow = event.clientX > bounds.right - 55;
        if (!clickedTitle && !clickedArrow) return;
      }

      title.classList.toggle("collapsed");
      const collapsed = title.classList.contains("collapsed");
      content.classList.toggle("collapsed", collapsed);
      content.style.maxHeight = collapsed ? "0" : `${content.scrollHeight}px`;
    });
    title.dataset.listenerAttached = "true";
  });
}

function updateParameterControls() {
  const setValue = (id, value, property = "value") => {
    const element = document.getElementById(id);
    if (element && value !== null && value !== undefined) element[property] = value;
  };

  const inputBindings = {
    temperatureSetpoint: "temperatureSetpoint",
    heaterPower: "heaterPower",
    heaterRange: "heaterRange",
    temperatureLimit: "temperatureLimit",
    timeout: "timeout",
    proportionalGain: "proportionalGain",
    integralGain: "integralGain",
    derivativeGain: "derivativeGain",
    MXCSP: "temperatureSetpointMXC",
    MXCP: "proportionalGainMXC",
    MXCI: "integralGainMXC",
    MXCD: "derivativeGainMXC",
    MXCHR: "heaterRangeMXC",
    dwellMXC: "dwellMXC",
    pauseMXC: "pauseMXC",
    rangeMXC: "sensorRangeMXC",
    modeMXC: "sensorModeMXC",
    dwell50K: "dwell50K",
    pause50K: "pause50K",
    range50K: "sensorRange50K",
    mode50K: "sensorMode50K",
    dwell4K: "dwell4K",
    pause4K: "pause4K",
    range4K: "sensorRange4K",
    mode4K: "sensorMode4K",
    dwellSTILL: "dwellSTILL",
    pauseSTILL: "pauseSTILL",
    rangeSTILL: "sensorRangeSTILL",
    modeSTILL: "sensorModeSTILL",
    curveMXC: "curveMXCSelect",
    curve50K: "curve50KSelect",
    curve4K: "curve4KSelect",
    curveSTILL: "curveSTILLSelect",
  };

  if (!initialParametersLoaded) {
    Object.entries(inputBindings).forEach(([parameter, elementId]) => {
      setValue(elementId, currentParameters[parameter]);
    });
    if (currentParameters.autorangeMXC !== null) {
      setValue("autorangeMXC", !!currentParameters.autorangeMXC, "checked");
    }
    initialParametersLoaded = true;
  }

  const displayBindings = {
    temperatureSetpoint: ["currentTemperatureSetpoint", 1],
    heaterPower: ["currentHeaterPower", 2],
    temperatureLimit: ["currentTemperatureLimit", 1],
    timeout: ["currentTimeout", 0],
    proportionalGain: ["currentProportionalGain", 3],
    integralGain: ["currentIntegralGain", 3],
    derivativeGain: ["currentDerivativeGain", 3],
  };
  Object.entries(displayBindings).forEach(([parameter, [elementId, decimals]]) => {
    const value = currentParameters[parameter];
    if (value !== null && Number.isFinite(Number(value))) {
      setValue(elementId, Number(value).toFixed(decimals), "textContent");
    }
  });
  setValue("currentHeaterRange", currentParameters.heaterRange, "textContent");
}

function normalizeEnabled(value) {
  if (value === undefined || value === null) return false;
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0 && !Number.isNaN(value);
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (normalized === "") return false;
    if (["1", "on", "true", "yes", "enabled"].includes(normalized)) return true;
    if (["0", "off", "false", "no", "disabled", "none", "nan"].includes(normalized)) return false;
    const numeric = Number(normalized);
    return !Number.isNaN(numeric) && numeric !== 0;
  }
  try {
    return Boolean(value);
  } catch {
    return false;
  }
}

function updateMXCTemperature(valueMK) {
  const element = document.getElementById("currentTemperatureMXC");
  if (element && Number.isFinite(valueMK)) element.textContent = valueMK.toFixed(4);
}

function updateMXCValues(temperature, resistance, power) {
  const select = document.getElementById("currentMXCValue");
  if (!select) return;
  const numericTemperature = Number(temperature);
  const numericResistance = Number(resistance);
  const numericPower = Number(power);
  select.options[0].text = Number.isFinite(numericTemperature)
    ? numericTemperature < 1 ? `${(numericTemperature * 1000).toFixed(3)} mK` : `${numericTemperature.toFixed(3)} K`
    : "-";
  select.options[1].text = Number.isFinite(numericResistance) ? `${numericResistance.toFixed(3)} Ω` : "- Ω";
  select.options[2].text = Number.isFinite(numericPower) ? `${numericPower.toExponential(2)} W` : "- W";
}

function updateMXCHeaterOutput(percent) {
  const element = document.getElementById("heaterOutputMXC");
  if (!element) return;
  element.textContent = typeof percent === "number" && isFinite(percent)
    ? `${percent.toFixed(1)} %`
    : "- %";
}

function updateStageValues(selectId, temperature, resistance, power) {
  const select = document.getElementById(selectId);
  if (!select) return;
  const numericTemperature = Number(temperature);
  const numericResistance = Number(resistance);
  const numericPower = Number(power);
  select.options[0].text = Number.isFinite(numericTemperature)
    ? numericTemperature < 1 ? `${(numericTemperature * 1000).toFixed(3)} mK` : `${numericTemperature.toFixed(3)} K`
    : "-";
  select.options[1].text = Number.isFinite(numericResistance) ? `${numericResistance.toFixed(3)} Ω` : "- Ω";
  select.options[2].text = Number.isFinite(numericPower) ? `${numericPower.toExponential(2)} W` : "- W";
}

function update50KValues(temperature, resistance, power) {
  updateStageValues("current50KValue", temperature, resistance, power);
}

function update4KValues(temperature, resistance, power) {
  updateStageValues("current4KValue", temperature, resistance, power);
}

function updateSTILLValues(temperature, resistance, power) {
  updateStageValues("currentSTILLValue", temperature, resistance, power);
}

function toggleStageElements(stageClass, visible) {
  for (const element of document.getElementsByClassName(stageClass)) {
    element.style.display = visible ? "" : "none";
  }
}

function updateStageVisibility() {
  toggleStageElements("stage-mxc", !!currentParameters.enabledMXC);
  toggleStageElements("stage-50k", !!currentParameters.enabled50K);
  toggleStageElements("stage-4k", !!currentParameters.enabled4K);
  toggleStageElements("stage-still", !!currentParameters.enabledSTILL);
}

function updateScanningChannel(scanningChannel) {
  document.querySelectorAll(".status-indicator-circle").forEach((element) => {
    element.classList.remove("active");
  });
  if (scanningChannel === null || scanningChannel === undefined || scanningChannel === 0) return;
  const channel = parseInt(scanningChannel, 10);
  if (!Number.isFinite(channel)) return;
  const element = document.getElementById(`statusCircleCH${channel}`);
  if (element) element.classList.add("active");
}

document.addEventListener("DOMContentLoaded", () => {
  const tabButtons = document.querySelectorAll(".tab-button");
  const tabContents = document.querySelectorAll(".tab-content");

  tabButtons.forEach((button) => {
    button.addEventListener("click", () => {
      tabButtons.forEach((btn) => btn.classList.remove("active"));
      tabContents.forEach((tab) => tab.classList.remove("active"));

      button.classList.add("active");
      const target = document.getElementById(button.dataset.target);
      if (target) {
        target.classList.add("active");
        setupCollapsibleSections(target);
      }
    });
  });
});