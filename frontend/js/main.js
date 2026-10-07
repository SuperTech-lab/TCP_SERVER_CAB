async function loadTemperatureBuffer() {
  try {
    const response = await fetch("/get-buffer", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`/get-buffer returned HTTP ${response.status}`);
    }

    const payload = await response.json();
    const channels = payload.channels || {};
    const loadedSamples = {};

    for (const chartId of ["50K", "4K", "STILL", "MXC"]) {
      const source = channels[chartId];
      const store = chartDataStore[chartId];
      if (!source || !store) continue;

      const timestamps = Array.isArray(source.timestamps_ms)
        ? source.timestamps_ms
        : [];
      const temperatures = Array.isArray(source.temperature_k)
        ? source.temperature_k
        : [];
      const setpoints = chartId === "MXC" && Array.isArray(source.setpoint_k)
        ? source.setpoint_k
        : [];
      const sampleCount = Math.min(timestamps.length, temperatures.length);

      store.labels.length = 0;
      store.data.length = 0;
      store.startTime = null;
      store.lastTimestamp = null;
      if (Array.isArray(store.setpoint)) store.setpoint.length = 0;

      for (let index = 0; index < sampleCount; index++) {
        const timestamp = Number(timestamps[index]);
        const temperature = Number(temperatures[index]);
        if (!Number.isFinite(timestamp) || !Number.isFinite(temperature)) continue;
        if (store.lastTimestamp !== null && timestamp <= store.lastTimestamp) continue;
        if (store.startTime === null) store.startTime = timestamp;

        store.labels.push((timestamp - store.startTime) / 1000);
        store.data.push(temperature);
        store.lastTimestamp = timestamp;

        if (chartId === "MXC") {
          const setpoint = setpoints[index];
          store.setpoint.push(
            setpoint === null || setpoint === undefined || !Number.isFinite(Number(setpoint))
              ? null
              : Number(setpoint),
          );
        }
      }

      loadedSamples[chartId] = store.data.length;
      if (store.startTime === null) continue;

      if (chartId === "MXC") updateTimeRangeOptions();
      if (chartId === "50K") updateTimeRangeOptions50K();
      if (chartId === "4K") updateTimeRangeOptions4K();
      if (chartId === "STILL") updateTimeRangeOptionsSTILL();
      redrawFromStore(chartId);
    }

    console.log("✅ Temperature buffer loaded:", loadedSamples);
  } catch (error) {
    console.error("Error loading temperature buffer:", error);
  }
}

async function fetchSensorData(forceUpdateControls = false) {
  try {
    const response = await fetch("/get-data");
    if (!response.ok) {
      if (tcpConnectionStatus !== false) await updateConnectionStatus();
      return;
    }

    const data = await response.json();
    const sampleTimestamp = Number(data.sampleTime);
    const numericKeys = [
      "50K", "4K", "STILL", "MXC", "RMXC", "PMXC", "setpoint",
      "heater_power", "temperature_limit", "timeout", "proportional_gain",
      "integral_gain", "derivative_gain", "MXCSP", "MXCP", "MXCI", "MXCD",
      "MXCHR", "dwellMXC", "pauseMXC", "R50K", "P50K", "R4K", "P4K",
      "RSTILL", "PSTILL", "heaterOutputMXC", "RCH9", "RCH10", "RCH11",
      "RCH12", "RCH13", "RCH14", "RCH15",
    ];
    const parameterNames = {
      "50K": "50K", "4K": "4K", STILL: "STILL", MXC: "MXC", RMXC: "RMXC",
      PMXC: "PMXC", setpoint: "temperatureSetpoint", heater_power: "heaterPower",
      temperature_limit: "temperatureLimit", timeout: "timeout",
      proportional_gain: "proportionalGain", integral_gain: "integralGain",
      derivative_gain: "derivativeGain", MXCSP: "MXCSP", MXCP: "MXCP",
      MXCI: "MXCI", MXCD: "MXCD", MXCHR: "MXCHR", dwellMXC: "dwellMXC",
      pauseMXC: "pauseMXC", R50K: "R50K", P50K: "P50K", R4K: "R4K", P4K: "P4K",
      RSTILL: "RSTILL", PSTILL: "PSTILL", heaterOutputMXC: "heaterOutputMXC",
      RCH9: "RCH9", RCH10: "RCH10", RCH11: "RCH11", RCH12: "RCH12",
      RCH13: "RCH13", RCH14: "RCH14", RCH15: "RCH15",
    };

    for (const key of numericKeys) {
      if (data[key] === undefined) continue;
      const target = parameterNames[key];
      if (target) currentParameters[target] = parseFloat(data[key]);
    }

    const integerKeys = [
      "enabledMXC", "enabled50K", "enabled4K", "enabledSTILL", "modeMXC",
      "rangeMXC", "autorangeMXC", "mode50K", "range50K", "mode4K", "range4K",
      "modeSTILL", "rangeSTILL", "curveMXC", "curve50K", "curve4K", "curveSTILL",
      "scanning_channel",
    ];
    for (const key of integerKeys) {
      if (data[key] !== undefined) currentParameters[key] = parseInt(data[key], 10);
    }

    for (const stage of ["50K", "4K", "STILL"]) {
      for (const key of [`dwell${stage}`, `pause${stage}`]) {
        if (data[key] !== undefined) currentParameters[key] = parseFloat(data[key]);
      }
    }
    for (let channel = 9; channel <= 15; channel++) {
      const enabledKey = `enabledCH${channel}`;
      const modeKey = `modeCH${channel}`;
      const rangeKey = `rangeCH${channel}`;
      if (data[enabledKey] !== undefined) {
        currentParameters[enabledKey] = normalizeEnabled(data[enabledKey]) ? 1 : 0;
      }
      if (data[modeKey] !== undefined) currentParameters[modeKey] = data[modeKey] === null ? null : parseInt(data[modeKey], 10);
      if (data[rangeKey] !== undefined) currentParameters[rangeKey] = data[rangeKey] === null ? null : parseInt(data[rangeKey], 10);
    }

    if (data.heater_range !== undefined) currentParameters.heaterRange = data.heater_range;
    if (data.autoscan !== undefined) currentParameters.autoscan = data.autoscan;
    if (data.scanning_channel !== undefined) updateScanningChannel(data.scanning_channel);

    const now = Date.now();
    if (forceUpdateControls || now - lastParameterBoxUpdateTime > parameterBoxUpdateInterval) {
      lastParameterBoxUpdateTime = now;
      updateParameterControls();
    }

    lastSentValues = {
      temperatureSetpoint: currentParameters.temperatureSetpoint,
      heaterPower: currentParameters.heaterPower,
      heaterRange: currentParameters.heaterRange,
      temperatureLimit: currentParameters.temperatureLimit,
      timeout: currentParameters.timeout,
      proportionalGain: currentParameters.proportionalGain,
      integralGain: currentParameters.integralGain,
      derivativeGain: currentParameters.derivativeGain,
      MXCSP: currentParameters.MXCSP,
      MXCP: currentParameters.MXCP,
      MXCI: currentParameters.MXCI,
      MXCD: currentParameters.MXCD,
      MXCHR: currentParameters.MXCHR,
      dwellMXC: currentParameters.dwellMXC,
      pauseMXC: currentParameters.pauseMXC,
      modeMXC: currentParameters.modeMXC,
      rangeMXC: currentParameters.rangeMXC,
      autorangeMXC: currentParameters.autorangeMXC,
    };

    if (currentParameters["50K"] !== null) {
      updateTemperatureChart("50K", currentParameters["50K"], null, sampleTimestamp);
      update50KValues(currentParameters["50K"], currentParameters.R50K, currentParameters.P50K);
    }
    if (currentParameters["4K"] !== null) {
      updateTemperatureChart("4K", currentParameters["4K"], null, sampleTimestamp);
      update4KValues(currentParameters["4K"], currentParameters.R4K, currentParameters.P4K);
    }
    if (currentParameters.STILL !== null) {
      updateTemperatureChart("STILL", currentParameters.STILL, null, sampleTimestamp);
      updateSTILLValues(currentParameters.STILL, currentParameters.RSTILL, currentParameters.PSTILL);
    }
    if (currentParameters.MXC !== null) {
      updateTemperatureChart("MXC", currentParameters.MXC, currentParameters.temperatureSetpoint, sampleTimestamp);
      updateMXCValues(currentParameters.MXC, currentParameters.RMXC, currentParameters.PMXC);
      updateMXCHeaterOutput(currentParameters.heaterOutputMXC);
    }

    const stageToggles = [
      ["MXC", "toggleMXCGlobal", () => pendingMXCToggle, (value) => { pendingMXCToggle = value; }],
      ["50K", "toggle50KGlobal", () => pending50KToggle, (value) => { pending50KToggle = value; }],
      ["STILL", "toggleSTILLGlobal", () => pendingSTILLToggle, (value) => { pendingSTILLToggle = value; }],
      ["4K", "toggle4kGlobal", () => pending4KToggle, (value) => { pending4KToggle = value; }],
    ];
    for (const [stage, id, getPending, setPending] of stageToggles) {
      const checkbox = document.getElementById(id);
      const enabled = !!currentParameters[`enabled${stage}`];
      if (!checkbox) continue;
      if (getPending()) {
        if (checkbox.checked === enabled) setPending(false);
      } else {
        checkbox.checked = enabled;
      }
    }
    updateStageVisibility();

    for (let channel = 9; channel <= 15; channel++) {
      const checkbox = document.getElementById(`toggleExtraChannel${channel}`);
      const enabled = normalizeEnabled(currentParameters[`enabledCH${channel}`]);
      if (checkbox) {
        if (pendingExtraChannels[channel]) {
          if (checkbox.checked === enabled) pendingExtraChannels[channel] = false;
        } else {
          checkbox.checked = enabled;
        }
      }
      const resistanceBox = document.getElementById(`currentRCH${channel}`);
      const resistance = currentParameters[`RCH${channel}`];
      if (resistanceBox) resistanceBox.textContent = enabled && Number.isFinite(resistance) ? `${Number(resistance).toFixed(2)} Ω` : "--";
    }

    const autoscanToggle = document.getElementById("autoscanToggle");
    if (autoscanToggle && currentParameters.autoscan !== undefined) {
      autoscanToggle.checked = currentParameters.autoscan === "on";
      pendingAutoscanToggle = false;
    }

    updateRelationStore();
    redrawRelationChart();
    if (tcpConnectionStatus === false) await updateConnectionStatus();
  } catch (error) {
    console.error("Error fetching data:", error);
    if (tcpConnectionStatus !== false) await updateConnectionStatus();
  }
}

document.addEventListener("DOMContentLoaded", async function () {
  setupCollapsibleSections();

  charts["BB"] = createTemperatureChart("temperatureChartBB", true, "Black Body Temperature (K)");
  charts["50K"] = createTemperatureChart("temperatureChart50K", false, "Temperature 50K");
  charts["4K"] = createTemperatureChart("temperatureChart4K", false, "Temperature 4K");
  charts["STILL"] = createTemperatureChart("temperatureChartSTILL", false, "Temperature STILL");
  charts["MXC"] = createTemperatureChart("temperatureChartMXC", false, "Temperature MXC");

  enableYAxisLimitEditing(charts["MXC"], "temperatureChartMXC");
  enableYAxisLimitEditing(charts["STILL"], "temperatureChartSTILL");

  await updateConnectionStatus();

  document.querySelectorAll(".control-input").forEach((input) => {
    const id = input.id;
    if (!MXC_CONTROL_IDS.includes(id) && !MXC_SENSOR_IDS.includes(id)) {
      input.addEventListener("keypress", function (e) {
        if (e.key === "Enter") sendControlParameters();
      });
    }
  });

  await loadTemperatureBuffer();
  await fetchSensorData();
  await refreshRecentRuns();
  await refreshRelationFiles();
});

setInterval(fetchSensorData, 1000);