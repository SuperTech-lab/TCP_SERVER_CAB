async function initRelationStateFromServer() {
  const startButton = document.getElementById("relationStartButton");
  const stopButton = document.getElementById("relationStopButton");
  const channelSelect = document.getElementById("relationChannelSelect");
  const labelInput = document.getElementById("relationLabelInput");
  const modeSelect = document.getElementById("relationModeSelect");
  const targetInput = document.getElementById("relationTargetInput");
  const rateInput = document.getElementById("relationRateInput");

  function setRelationUiIdle() {
    relationRunning = false;
    startButton.disabled = false;
    stopButton.disabled = true;
    channelSelect.disabled = false;
    labelInput.disabled = false;
    modeSelect.disabled = false;
    updateRelationLabelVisibility();
    updateRelationRampControls();
  }

  try {
    const raw = await sendCommandToServer("get_relation_status");
    let response = (raw ?? "").toString().trim();
    const prefix = "Command received - ";

    if (response.startsWith(prefix)) {
      response = response.slice(prefix.length).trim();
    }

    const marker = "RELATION_STATUS:";
    const idx = response.indexOf(marker);
    if (idx === -1) {
      setRelationUiIdle();
      addLogEntry(
        `❌ get_relation_status: no RELATION_STATUS en "${raw}"`,
        "received",
      );
      return;
    }

    const payload = response.slice(idx).trim();
    if (payload.startsWith("RELATION_STATUS:ACTIVE:")) {
      const parts = payload.split(":");
      const relationRunId = parts[2] || null;
      const chNum = parts[3] || null;
      const labelEnc = parts[4] || "";
      const n = parts[5] || "0";
      const relationMode = parts[6] === "RAMP" ? "RAMP" : "MANUAL";
      const targetMk = parts[7] ?? "";
      const rateMkPerMin = parts[8] ?? "";

      if (!chNum) {
        relationRunning = true;
        startButton.disabled = true;
        stopButton.disabled = false;
        channelSelect.disabled = true;
        labelInput.disabled = true;
        modeSelect.disabled = true;
        updateRelationRampControls();
        addLogEntry(
          `❌ RELATION_STATUS ACTIVE malformado: "${payload}"`,
          "received",
        );
        return;
      }

      const chStr = `CH${chNum}`;
      let decodedLabel = "";
      try {
        decodedLabel = decodeURIComponent(labelEnc);
      } catch {
        decodedLabel = labelEnc;
      }

      channelSelect.value = chStr;
      labelInput.value = decodedLabel;
      modeSelect.value = relationMode;
      if (relationMode === "RAMP") {
        targetInput.value = targetMk;
        rateInput.value = rateMkPerMin;
      }

      currentRelationChannel = chStr;
      relationRunning = true;
      startButton.disabled = true;
      stopButton.disabled = false;
      channelSelect.disabled = true;
      labelInput.disabled = true;
      modeSelect.disabled = true;
      updateRelationLabelVisibility();
      updateRelationRampControls();

      const modeDetails = relationMode === "RAMP"
        ? `, target=${targetMk} mK, rate=${rateMkPerMin} mK/min`
        : "";
      addLogEntry(
        `🔁 Relation activa recuperada: relation_run_id=${relationRunId ?? "?"} `
          + `(CH${chNum}, n=${n}, mode=${relationMode}${modeDetails})`,
        "status",
      );
      return;
    }

    setRelationUiIdle();
  } catch (error) {
    addLogEntry(`❌ Error get_relation_status: ${error.message}`, "received");
  }
}

function updateRelationLabelVisibility() {
  const channel = document.getElementById("relationChannelSelect").value;
  const input = document.getElementById("relationLabelInput");
  const sampleChannels = ["CH9", "CH10", "CH11", "CH12", "CH13", "CH14", "CH15"];

  if (sampleChannels.includes(channel)) {
    input.style.display = "inline-block";
  } else {
    input.style.display = "none";
    input.value = "";
  }
}

function updateRelationRampControls() {
  const modeSelect = document.getElementById("relationModeSelect");
  const rampControls = document.getElementById("relationRampControls");
  const targetInput = document.getElementById("relationTargetInput");
  const rateInput = document.getElementById("relationRateInput");
  const isRamp = modeSelect.value === "RAMP";

  rampControls.style.display = isRamp ? "block" : "none";
  targetInput.disabled = !isRamp || relationRunning;
  rateInput.disabled = !isRamp || relationRunning;
}

document
  .getElementById("relationChannelSelect")
  .addEventListener("change", updateRelationLabelVisibility);
document
  .getElementById("relationModeSelect")
  .addEventListener("change", updateRelationRampControls);
updateRelationLabelVisibility();
updateRelationRampControls();

document
  .getElementById("relationStartButton")
  .addEventListener("click", async () => {
    if (relationRunning) return;

    const startButton = document.getElementById("relationStartButton");
    const stopButton = document.getElementById("relationStopButton");
    const channelSelect = document.getElementById("relationChannelSelect");
    const labelInput = document.getElementById("relationLabelInput");
    const modeSelect = document.getElementById("relationModeSelect");
    const chNum = channelSelect.value.replace("CH", "");
    const label = labelInput.value || "NA";
    const mode = modeSelect.value;
    let startCmd;
    let successMarker;

    if (mode === "RAMP") {
      const targetMk = Number(document.getElementById("relationTargetInput").value);
      const rateMkPerMin = Number(document.getElementById("relationRateInput").value);
      if (!Number.isFinite(targetMk) || targetMk <= 0) {
        addLogEntry("❌ Target must be a positive number.", "received");
        return;
      }
      if (!Number.isFinite(rateMkPerMin) || rateMkPerMin <= 0) {
        addLogEntry("❌ Ramp rate must be a positive number.", "received");
        return;
      }
      startCmd = `start_relation_ramp:${chNum}:${targetMk}:${rateMkPerMin}:${encodeURIComponent(label)}`;
      successMarker = "RELATION_RAMP_STARTED:";
    } else {
      startCmd = `start_relation:${chNum}:${encodeURIComponent(label)}`;
      successMarker = "RELATION_STARTED:";
    }

    startButton.disabled = true;
    try {
      const selectCmd = `select_measure_channel:${chNum}`;
      addLogEntry(`Sending: ${selectCmd}`, "sent");
      const responseSelect = await sendCommandToServer(selectCmd);
      addLogEntry(`Server response: ${responseSelect}`, "received");
      if ((responseSelect ?? "").toString().includes("❌")) {
        throw new Error(responseSelect);
      }

      clearPendingExtraChannelsForSampleChannels();
      await new Promise((resolve) => setTimeout(resolve, 300));
      await fetchSensorData(true);
      addLogEntry(`Sending command: ${startCmd}`, "sent");
      const response = await sendCommandToServer(startCmd);
      addLogEntry(`Server response: ${response}`, "received");

      const responseText = (response ?? "").toString().trim();
      if (!responseText.includes(successMarker)) {
        throw new Error(responseText || "Empty response from TCP server");
      }

      relationRunning = true;
      startButton.disabled = true;
      stopButton.disabled = false;
      channelSelect.disabled = true;
      labelInput.disabled = true;
      modeSelect.disabled = true;
      updateRelationRampControls();
    } catch (error) {
      relationRunning = false;
      startButton.disabled = false;
      stopButton.disabled = true;
      channelSelect.disabled = false;
      labelInput.disabled = false;
      modeSelect.disabled = false;
      updateRelationRampControls();
      addLogEntry(`Error starting relation: ${error.message}`, "received");
    }
  });

document
  .getElementById("relationStopButton")
  .addEventListener("click", async () => {
    if (!relationRunning) return;

    const startButton = document.getElementById("relationStartButton");
    const stopButton = document.getElementById("relationStopButton");
    const channelSelect = document.getElementById("relationChannelSelect");
    const labelInput = document.getElementById("relationLabelInput");
    const modeSelect = document.getElementById("relationModeSelect");
    const command = "stop_relation";

    stopButton.disabled = true;
    addLogEntry(`Sending command: ${command}`, "sent");

    try {
      const response = await sendCommandToServer(command);
      addLogEntry(`Server response: ${response}`, "received");
      const responseText = (response ?? "").toString().trim();
      if (!responseText.includes("RELATION_STOPPED:")) {
        throw new Error(responseText || "Empty response from TCP server");
      }

      relationRunning = false;
      startButton.disabled = false;
      stopButton.disabled = true;
      channelSelect.disabled = false;
      labelInput.disabled = false;
      modeSelect.disabled = false;
      updateRelationRampControls();
    } catch (error) {
      relationRunning = true;
      startButton.disabled = true;
      stopButton.disabled = false;
      channelSelect.disabled = true;
      labelInput.disabled = true;
      modeSelect.disabled = true;
      updateRelationRampControls();
      addLogEntry(`Error stopping relation: ${error.message}`, "received");
    }
  });

function updateRunUI() {
  const playButton = document.getElementById("runPlayButton");
  const stopButton = document.getElementById("runStopButton");
  const runIdInput = document.getElementById("runIdInput");
  const runDescInput = document.getElementById("runDescInput");
  if (!playButton || !stopButton) return;

  const hasActiveRun = currentActiveRunId !== null;
  playButton.disabled = hasActiveRun;
  stopButton.disabled = !hasActiveRun;
  if (runIdInput) runIdInput.disabled = hasActiveRun;
  if (runDescInput) runDescInput.disabled = hasActiveRun;
}

function loadHistoricalRun(runPayload) {
  if (!runPayload || !runPayload.run_id) {
    addLogEntry("Error: RUN_DATA sin run_id", "received");
    return;
  }

  const runId = runPayload.run_id;
  const url = `/plot_run?run_id=${encodeURIComponent(runId)}`;
  window.open(url, "_blank", "width=1200,height=800");
  addLogEntry(
    `✅ Abierta ventana con gráficas Python del RUN histórico ${runId}`,
    "status",
  );
}

const recentRunsSelect = document.getElementById("recentRunsSelect");
if (recentRunsSelect) {
  recentRunsSelect.addEventListener("change", async () => {
    const runId = parseInt(recentRunsSelect.value, 10);
    if (!runId) return;
    addLogEntry(`📂 Cargando RUN histórico ${runId}`, "status");

    try {
      const response = await sendCommandToServer(`get_run_data:${runId}`);
      const match = /RUN_DATA:OK:(\{.*\})/.exec(response);
      if (!match) {
        addLogEntry("❌ No RUN_DATA encontrado", "received");
        return;
      }
      loadHistoricalRun(JSON.parse(match[1]));
    } catch (error) {
      addLogEntry(
        `❌ Error cargando RUN ${runId}: ${error.message}`,
        "received",
      );
    }
  });
}

async function refreshRecentRuns() {
  if (!recentRunsSelect) return;
  recentRunsSelect.innerHTML = `<option value="">(cargando...)</option>`;

  try {
    const response = await sendCommandToServer("get_recent_runs");
    const marker = "RECENT_RUNS:OK:";
    const index = response.indexOf(marker);
    if (index === -1) {
      recentRunsSelect.innerHTML = `<option value="">(error cargando)</option>`;
      addLogEntry(`❌ get_recent_runs: ${response}`, "received");
      return;
    }

    const runs = JSON.parse(response.slice(index + marker.length).trim());
    if (!Array.isArray(runs) || runs.length === 0) {
      recentRunsSelect.innerHTML = `<option value="">(sin runs)</option>`;
      return;
    }

    recentRunsSelect.innerHTML =
      `<option value="">Selecciona un RUN...</option>`
      + runs.map((run) => {
        const label = run.description
          ? `RUN ${run.run_id} — ${run.description}`
          : `RUN ${run.run_id}`;
        return `<option value="${run.run_id}">${label}</option>`;
      }).join("");
  } catch (error) {
    recentRunsSelect.innerHTML = `<option value="">(error cargando)</option>`;
    addLogEntry(`❌ Error get_recent_runs: ${error.message}`, "received");
  }
}

async function initRunIdFromServer() {
  if (hasInitializedRunId) return;
  hasInitializedRunId = true;
  const runIdInput = document.getElementById("runIdInput");
  if (!runIdInput) return;

  try {
    addLogEntry("Requesting last/active run id...", "status");
    const response = await sendCommandToServer("get_last_run");
    let match = /ACTIVE_RUN:(\d+)/.exec(response);
    if (match) {
      const activeRun = parseInt(match[1], 10);
      currentActiveRunId = activeRun;
      runIdInput.value = activeRun;
      expectedNextRunId = activeRun;
      addLogEntry(`Active run detected: ${activeRun}`, "status");
      updateRunUI();
      return;
    }

    match = /LAST_RUN:(\d+)/.exec(response);
    if (match) {
      const nextRun = parseInt(match[1], 10) + 1;
      currentActiveRunId = null;
      runIdInput.value = nextRun;
      expectedNextRunId = nextRun;
      addLogEntry(`Next run id set to ${nextRun}`, "status");
      updateRunUI();
      return;
    }

    addLogEntry(`Could not parse run id from: "${response}". Using 1.`, "status");
    runIdInput.value = 1;
    expectedNextRunId = 1;
  } catch (error) {
    addLogEntry(`Error requesting run id: ${error.message}. Using 1.`, "received");
    runIdInput.value = 1;
    expectedNextRunId = 1;
  }
}

async function refreshRelationFiles() {
  if (!relationFilesSelect) return;
  relationFilesSelect.innerHTML = `<option value="">(cargando...)</option>`;

  try {
    const response = await sendCommandToServer("get_recent_relations");
    const marker = "RECENT_RELATIONS:OK:";
    const index = response.indexOf(marker);
    if (index === -1) {
      relationFilesSelect.innerHTML = `<option value="">(error cargando)</option>`;
      addLogEntry(`❌ get_recent_relations: ${response}`, "received");
      return;
    }

    const files = JSON.parse(response.slice(index + marker.length).trim());
    if (!Array.isArray(files) || files.length === 0) {
      relationFilesSelect.innerHTML = `<option value="">(sin relations)</option>`;
      return;
    }

    relationFilesSelect.innerHTML =
      `<option value="">Selecciona un .dat...</option>`
      + files.map((file) => {
        const label = file.label ? ` — ${file.label}` : "";
        const points = typeof file.n_points === "number"
          ? ` (${file.n_points} pts)`
          : "";
        const createdAt = file.created_at ? ` — ${file.created_at}` : "";
        return `<option value="${encodeURIComponent(file.file_name)}">CH${file.channel_number}${label}${points}${createdAt}</option>`;
      }).join("");
  } catch (error) {
    relationFilesSelect.innerHTML = `<option value="">(error cargando)</option>`;
    addLogEntry(`❌ Error get_recent_relations: ${error.message}`, "received");
  }
}

const relationFilesSelect = document.getElementById("relationFilesSelect");
const relationFilesRefreshButton = document.getElementById("relationFilesRefreshButton");

if (relationFilesRefreshButton) {
  relationFilesRefreshButton.addEventListener("click", refreshRelationFiles);
}

function openHistoricalRelationWindow(fileName) {
  const url = `/plot_relation?file_name=${encodeURIComponent(fileName)}`;
  window.open(url, "_blank", "width=1200,height=800");
  addLogEntry(
    `✅ Abierta ventana con gráfica Python de relation: ${fileName}`,
    "status",
  );
}

if (relationFilesSelect) {
  relationFilesSelect.addEventListener("change", () => {
    const value = relationFilesSelect.value;
    if (!value) return;
    const fileName = decodeURIComponent(value);
    addLogEntry(`📂 Abriendo relation histórica: ${fileName}`, "status");
    openHistoricalRelationWindow(fileName);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const runIdInput = document.getElementById("runIdInput");
  const runPlayButton = document.getElementById("runPlayButton");
  const runStopButton = document.getElementById("runStopButton");
  const runDescInput = document.getElementById("runDescInput");

  if (!runPlayButton || !runStopButton || !runIdInput) {
    console.warn("Run control elements not found in DOM");
    return;
  }

  initRunIdFromServer();
  updateRunUI();

  runPlayButton.addEventListener("click", async () => {
    const runId = parseInt(runIdInput.value, 10);

    if (currentActiveRunId !== null) {
      addLogEntry("⚠️ A run is already active", "status");
      return;
    }

    const isHistorical =
      currentActiveRunId === null &&
      expectedNextRunId !== null &&
      runId < expectedNextRunId;

    if (isNaN(runId) || runId <= 0) {
      addLogEntry("Error: RUN_ID must be a positive integer", "received");
      return;
    }

    if (isHistorical) {
      try {
        const response = await sendCommandToServer(`get_run_data:${runId}`);
        const match = /RUN_DATA:OK:(\{.*\})/.exec(response);
        if (!match) {
          addLogEntry("❌ No RUN_DATA JSON found in server response", "received");
          return;
        }
        loadHistoricalRun(JSON.parse(match[1]));
      } catch (error) {
        addLogEntry(`Error sending get_run_data: ${error.message}`, "received");
      }
      return;
    }

    const description = runDescInput ? runDescInput.value.trim() : "";
    const command = description.length > 0
      ? `start_run:${runId}:${encodeURIComponent(description)}`
      : `start_run:${runId}`;
    addLogEntry(`Sending command: ${command}`, "sent");

    try {
      const response = await sendCommandToServer(command);
      const startedMatch = /Run (\d+) started$/i.exec(response.trim());
      addLogEntry(`Server response: ${response}`, "received");

      if (startedMatch && parseInt(startedMatch[1], 10) === runId) {
        currentActiveRunId = runId;
        expectedNextRunId = runId + 1;
        updateRunUI();
      } else {
        addLogEntry("❌ Run not started; local state won't change", "received");
      }
    } catch (error) {
      addLogEntry(`Error sending start_run: ${error.message}`, "received");
    }
  });

  runStopButton.addEventListener("click", async () => {
    const command = "end_run";
    addLogEntry(`Sending command: ${command}`, "sent");

    try {
      const response = await sendCommandToServer(command);
      const endedMatch = /Run (\d+) (?:ended|stopped|finished)$/i.exec(
        response.trim(),
      );
      const endedRunId = endedMatch
        ? parseInt(endedMatch[1], 10)
        : currentActiveRunId;
      addLogEntry(`Server response: ${response}`, "received");

      if (Number.isFinite(endedRunId)) {
        currentActiveRunId = null;
        expectedNextRunId = endedRunId + 1;
        runIdInput.value = expectedNextRunId;
        updateRunUI();
      } else {
        addLogEntry("❌ Run not ended; local state won't change", "received");
      }
    } catch (error) {
      addLogEntry(`Error sending end_run: ${error.message}`, "received");
    }
  });
});

function getResistanceForChannel(channel) {
  switch (channel) {
    case "STILL": return currentParameters.RSTILL;
    case "4K": return currentParameters.R4K;
    case "50K": return currentParameters.R50K;
    case "CH9": return currentParameters.RCH9;
    case "CH10": return currentParameters.RCH10;
    case "CH11": return currentParameters.RCH11;
    case "CH12": return currentParameters.RCH12;
    case "CH13": return currentParameters.RCH13;
    case "CH14": return currentParameters.RCH14;
    case "CH15": return currentParameters.RCH15;
    default: return null;
  }
}

function updateRelationCurrentLabels() {
  const mxcSpan = document.getElementById("relationCurrentMXC");
  const resistanceSpan = document.getElementById("relationCurrentR");
  if (!mxcSpan || !resistanceSpan) return;

  const temperature = currentParameters.MXC;
  const resistance = getResistanceForChannel(currentRelationChannel);
  mxcSpan.textContent = typeof temperature === "number" && isFinite(temperature)
    ? temperature < 1 ? `${(temperature * 1000).toFixed(3)} mK` : `${temperature.toFixed(6)} K`
    : "-";
  resistanceSpan.textContent = typeof resistance === "number" && isFinite(resistance)
    ? `${resistance.toFixed(3)} Ω`
    : "-";
}

function pushRelationPointFor(channel) {
  const temperature = currentParameters.MXC;
  const resistance = getResistanceForChannel(channel);
  if (!(typeof temperature === "number" && isFinite(temperature))) return;
  if (!(typeof resistance === "number" && isFinite(resistance))) return;

  relationDataStore[channel].push({ x: temperature, y: resistance });
  const hardCap = 20000;
  if (relationDataStore[channel].length > hardCap) {
    relationDataStore[channel].splice(
      0,
      relationDataStore[channel].length - hardCap,
    );
  }
}

function updateRelationStore() {
  ["CH9", "CH10", "CH11", "CH12", "CH13", "CH14", "CH15"]
    .forEach(pushRelationPointFor);
}

function onRelationChannelChange() {
  const select = document.getElementById("relationChannelSelect");
  if (!select) return;
  currentRelationChannel = select.value;
  updateRelationLabelVisibility();
  redrawRelationChart();
  updateRelationCurrentLabels();
}

document.addEventListener("DOMContentLoaded", async () => {
  const select = document.getElementById("relationChannelSelect");
  if (select) currentRelationChannel = select.value;
  await initRelationStateFromServer();
  relationChart = createRelationChart();
  redrawRelationChart();
});