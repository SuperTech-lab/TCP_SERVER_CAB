let hasInitializedRunId = false;
let expectedNextRunId = null;
let relationChart = null;
let currentRelationChannel = "CH9";
const RELATION_LIVE_POINTS = 400;
let currentActiveRunId = null;
let relationRunning = false;

const relationDataStore = {
  CH9: [],
  CH10: [],
  CH11: [],
  CH12: [],
  CH13: [],
  CH14: [],
  CH15: [],
};

const relationFilesSelect = document.getElementById(
  "relationFilesSelect",
);
const relationFilesRefreshButton = document.getElementById(
  "relationFilesRefreshButton",
);

const SAMPLE_CHANNELS = [9, 10, 11, 12, 13, 14, 15];
const pendingSampleToggle = {};

async function initRelationStateFromServer() {
  const startButton = document.getElementById(
    "relationStartButton",
  );
  const stopButton = document.getElementById(
    "relationStopButton",
  );
  const channelSelect = document.getElementById(
    "relationChannelSelect",
  );
  const labelInput = document.getElementById(
    "relationLabelInput",
  );
  const modeSelect = document.getElementById(
    "relationModeSelect",
  );
  const targetInput = document.getElementById(
    "relationTargetInput",
  );
  const rateInput = document.getElementById(
    "relationRateInput",
  );

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
    const raw = await sendCommandToServer(
      "get_relation_status",
    );

    let response = (raw ?? "").toString().trim();
    const prefix = "Command received - ";

    if (response.startsWith(prefix)) {
      response = response
        .slice(prefix.length)
        .trim();
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

    if (
      payload.startsWith(
        "RELATION_STATUS:ACTIVE:",
      )
    ) {
      const parts = payload.split(":");

      const relationRunId = parts[2] || null;
      const chNum = parts[3] || null;
      const labelEnc = parts[4] || "";
      const n = parts[5] || "0";

      /*
      * Los campos 6–8 son los añadidos para
      * restaurar el control de la rampa.
      *
      * Si se recibe el formato antiguo,
      * se interpreta como MANUAL.
      */
      const relationMode =
        parts[6] === "RAMP"
          ? "RAMP"
          : "MANUAL";

      const targetMk = parts[7] ?? "";
      const rateMkPerMin = parts[8] ?? "";

      if (!chNum) {
        /*
        * El servidor indica ACTIVE, pero no podemos
        * reconstruir la relación. Bloqueamos Start
        * para evitar iniciar otra relación encima.
        */
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
        decodedLabel = decodeURIComponent(
          labelEnc,
        );
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

      const modeDetails =
        relationMode === "RAMP"
          ? `, target=${targetMk} mK, rate=${rateMkPerMin} mK/min`
          : "";

      addLogEntry(
        `🔁 Relation activa recuperada: `
          + `relation_run_id=${relationRunId ?? "?"} `
          + `(CH${chNum}, n=${n}, mode=${relationMode}`
          + `${modeDetails})`,
        "status",
      );

      return;
    }

    setRelationUiIdle();
  } catch (error) {
    addLogEntry(
      `❌ Error get_relation_status: ${error.message}`,
      "received",
    );
  }
}

function updateRelationLabelVisibility() {
  const ch = document.getElementById("relationChannelSelect").value;
  const input = document.getElementById("relationLabelInput");

  if (
    ["CH9", "CH10", "CH11", "CH12", "CH13", "CH14", "CH15"].includes(ch)
  ) {
    input.style.display = "inline-block";
  } else {
    input.style.display = "none";
    input.value = "";
  }
}

document
  .getElementById("relationChannelSelect")
  .addEventListener("change", updateRelationLabelVisibility);

updateRelationLabelVisibility();

function updateRelationRampControls() {
  const modeSelect = document.getElementById(
    "relationModeSelect",
  );
  const rampControls = document.getElementById(
    "relationRampControls",
  );
  const targetInput = document.getElementById(
    "relationTargetInput",
  );
  const rateInput = document.getElementById(
    "relationRateInput",
  );

  const isRamp = modeSelect.value === "RAMP";

  rampControls.style.display = isRamp
    ? "block"
    : "none";

  targetInput.disabled =
    !isRamp || relationRunning;
  rateInput.disabled =
    !isRamp || relationRunning;
}

document
  .getElementById("relationModeSelect")
  .addEventListener(
    "change",
    updateRelationRampControls,
  );

updateRelationRampControls();

document
  .getElementById("relationStartButton")
  .addEventListener("click", async () => {
    if (relationRunning) return;

    const startButton = document.getElementById(
      "relationStartButton",
    );
    const stopButton = document.getElementById(
      "relationStopButton",
    );
    const channelSelect = document.getElementById(
      "relationChannelSelect",
    );
    const labelInput = document.getElementById(
      "relationLabelInput",
    );
    const modeSelect = document.getElementById(
      "relationModeSelect",
    );

    const ch = channelSelect.value;
    const chNum = ch.replace("CH", "");
    const label = labelInput.value || "NA";
    const mode = modeSelect.value;

    let startCmd;
    let successMarker;

    if (mode === "RAMP") {
      const targetMk = Number(
        document.getElementById(
          "relationTargetInput",
        ).value,
      );
      const rateMkPerMin = Number(
        document.getElementById(
          "relationRateInput",
        ).value,
      );

      if (!Number.isFinite(targetMk) || targetMk <= 0) {
        addLogEntry(
          "❌ Target must be a positive number.",
          "received",
        );
        return;
      }

      if (
        !Number.isFinite(rateMkPerMin)
        || rateMkPerMin <= 0
      ) {
        addLogEntry(
          "❌ Ramp rate must be a positive number.",
          "received",
        );
        return;
      }

      startCmd =
        `start_relation_ramp:${chNum}:`
        + `${targetMk}:${rateMkPerMin}:`
        + encodeURIComponent(label);

      successMarker = "RELATION_RAMP_STARTED:";
    } else {
      startCmd =
        `start_relation:${chNum}:`
        + encodeURIComponent(label);

      successMarker = "RELATION_STARTED:";
    }

    startButton.disabled = true;

    try {
      const selectCmd =
        `select_measure_channel:${chNum}`;

      addLogEntry(
        `Sending: ${selectCmd}`,
        "sent",
      );

      const respSel = await sendCommandToServer(
        selectCmd,
      );

      addLogEntry(
        `Server response: ${respSel}`,
        "received",
      );

      if (
        (respSel ?? "")
          .toString()
          .includes("❌")
      ) {
        throw new Error(respSel);
      }

      clearPendingExtraChannelsForSampleChannels();

      await new Promise(
        (resolve) => setTimeout(resolve, 300),
      );

      await fetchSensorData(true);

      addLogEntry(
        `Sending command: ${startCmd}`,
        "sent",
      );

      const response = await sendCommandToServer(
        startCmd,
      );

      addLogEntry(
        `Server response: ${response}`,
        "received",
      );

      const responseText = (response ?? "")
        .toString()
        .trim();

      if (!responseText.includes(successMarker)) {
        throw new Error(
          responseText
          || "Empty response from TCP server",
        );
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

      addLogEntry(
        `Error starting relation: ${error.message}`,
        "received",
      );
    }
  });

document
  .getElementById("relationStopButton")
  .addEventListener("click", async () => {
    if (!relationRunning) return;

    const startButton = document.getElementById(
      "relationStartButton",
    );
    const stopButton = document.getElementById(
      "relationStopButton",
    );
    const channelSelect = document.getElementById(
      "relationChannelSelect",
    );
    const labelInput = document.getElementById(
      "relationLabelInput",
    );
    const modeSelect = document.getElementById(
      "relationModeSelect",
    );

    const command = "stop_relation";

    stopButton.disabled = true;

    addLogEntry(
      `Sending command: ${command}`,
      "sent",
    );

    try {
      const response = await sendCommandToServer(
        command,
      );

      addLogEntry(
        `Server response: ${response}`,
        "received",
      );

      const responseText = (response ?? "")
        .toString()
        .trim();

      if (
        !responseText.includes(
          "RELATION_STOPPED:",
        )
      ) {
        throw new Error(
          responseText
          || "Empty response from TCP server",
        );
      }

      relationRunning = false;

      startButton.disabled = false;
      stopButton.disabled = true;
      channelSelect.disabled = false;
      labelInput.disabled = false;
      modeSelect.disabled = false;

      updateRelationRampControls();
    } catch (error) {
      /*
      * Si la parada no ha sido confirmada,
      * consideramos que la relación continúa activa.
      */
      relationRunning = true;

      startButton.disabled = true;
      stopButton.disabled = false;
      channelSelect.disabled = true;
      labelInput.disabled = true;
      modeSelect.disabled = true;

      updateRelationRampControls();

      addLogEntry(
        `Error stopping relation: ${error.message}`,
        "received",
      );
    }
  });

function updateRunUI() {
  const playBtn = document.getElementById("runPlayButton");
  const stopBtn = document.getElementById("runStopButton");
  const runIdInput = document.getElementById("runIdInput");
  const runDescInput = document.getElementById("runDescInput");

  if (!playBtn || !stopBtn) return;

  const hasActiveRun = currentActiveRunId !== null;

  playBtn.disabled = hasActiveRun;

  stopBtn.disabled = !hasActiveRun;

  if (runIdInput) {
    runIdInput.disabled = hasActiveRun;
  }
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

      const payload = JSON.parse(match[1]);
      loadHistoricalRun(payload);
    } catch (e) {
      addLogEntry(
        `❌ Error cargando RUN ${runId}: ${e.message}`,
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
    const i = response.indexOf(marker);
    if (i === -1) {
      recentRunsSelect.innerHTML = `<option value="">(error cargando)</option>`;
      addLogEntry(`❌ get_recent_runs: ${response}`, "received");
      return;
    }

    const jsonStr = response.slice(i + marker.length).trim();
    const runs = JSON.parse(jsonStr);

    if (!Array.isArray(runs) || runs.length === 0) {
      recentRunsSelect.innerHTML = `<option value="">(sin runs)</option>`;
      return;
    }

    recentRunsSelect.innerHTML =
      `<option value="">Selecciona un RUN...</option>` +
      runs
        .map((r) => {
          const label = r.description
            ? `RUN ${r.run_id} — ${r.description}`
            : `RUN ${r.run_id}`;
          return `<option value="${
            r.run_id
          }" data-desc="${encodeURIComponent(r.description || "")}">
              ${label}
            </option>`;
        })
        .join("");
  } catch (e) {
    recentRunsSelect.innerHTML = `<option value="">(error cargando)</option>`;
    addLogEntry(`❌ Error get_recent_runs: ${e.message}`, "received");
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

    let m;

    // Caso 1: hay RUN abierto
    m = /ACTIVE_RUN:(\d+)/.exec(response);
    if (m) {
      const activeRun = parseInt(m[1], 10);
      currentActiveRunId = activeRun;

      runIdInput.value = activeRun;
      expectedNextRunId = activeRun;
      addLogEntry(`Active run detected: ${activeRun}`, "status");
      updateRunUI();
      return;
    }

    // Caso 2: no hay abierto
    m = /LAST_RUN:(\d+)/.exec(response);
    if (m) {
      const lastRun = parseInt(m[1], 10);
      const nextRun = lastRun + 1;

      currentActiveRunId = null;
      runIdInput.value = nextRun;
      expectedNextRunId = nextRun;

      addLogEntry(`Next run id set to ${nextRun}`, "status");
      updateRunUI();
      return;
    }

    addLogEntry(
      `Could not parse run id from: "${response}". Using 1.`,
      "status",
    );
    runIdInput.value = 1;
    expectedNextRunId = 1;
  } catch (error) {
    addLogEntry(
      `Error requesting run id: ${error.message}. Using 1.`,
      "received",
    );
    runIdInput.value = 1;
    expectedNextRunId = 1;
  }
}

async function refreshRelationFiles() {
  if (!relationFilesSelect) return;

  relationFilesSelect.innerHTML = `<option value="">(cargando...)</option>`;

  try {
    // Igual que historical runs: se manda comando via HTTP /send-command
    const response = await sendCommandToServer("get_recent_relations");

    const marker = "RECENT_RELATIONS:OK:";
    const i = response.indexOf(marker);
    if (i === -1) {
      relationFilesSelect.innerHTML = `<option value="">(error cargando)</option>`;
      addLogEntry(`❌ get_recent_relations: ${response}`, "received");
      return;
    }

    const jsonStr = response.slice(i + marker.length).trim();
    const files = JSON.parse(jsonStr);

    if (!Array.isArray(files) || files.length === 0) {
      relationFilesSelect.innerHTML = `<option value="">(sin relations)</option>`;
      return;
    }

    relationFilesSelect.innerHTML =
      `<option value="">Selecciona un .dat...</option>` +
      files
        .map((f) => {
          const label = f.label ? ` — ${f.label}` : "";
          const n =
            typeof f.n_points === "number" ? ` (${f.n_points} pts)` : "";
          const when = f.created_at ? ` — ${f.created_at}` : "";
          return `<option value="${encodeURIComponent(f.file_name)}">CH${f.channel_number}${label}${n}${when}</option>`;
        })
        .join("");
  } catch (e) {
    relationFilesSelect.innerHTML = `<option value="">(error cargando)</option>`;
    addLogEntry(
      `❌ Error get_recent_relations: ${e.message}`,
      "received",
    );
  }
}

if (relationFilesRefreshButton) {
  relationFilesRefreshButton.addEventListener(
    "click",
    refreshRelationFiles,
  );
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
  relationFilesSelect.addEventListener("change", async () => {
    const v = relationFilesSelect.value;
    if (!v) return;

    const fileName = decodeURIComponent(v);

    // NO redibujes la gráfica principal. Solo abre ventana auxiliar.
    addLogEntry(`📂 Abriendo relation histórica: ${fileName}`, "status");
    openHistoricalRelationWindow(fileName);
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
//RUN CONTROL:
document.addEventListener("DOMContentLoaded", function () {
  const runIdInput = document.getElementById("runIdInput");
  const runPlayButton = document.getElementById("runPlayButton");
  const runStopButton = document.getElementById("runStopButton");
  const runDescInput = document.getElementById("runDescInput");

  if (!runPlayButton || !runStopButton) {
    console.warn("Run control elements not found in DOM");
    return;
  }

  initRunIdFromServer();
  updateRunUI();

  // Play: start_run o get_run_data según runId
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
      const command = `get_run_data:${runId}`;
      addLogEntry(`Requesting historical data for run ${runId}`, "sent");

      try {
        const response = await sendCommandToServer(command);
        //addLogEntry(`Server response: ${response}`, "received");
        const match = /RUN_DATA:OK:(\{.*\})/.exec(response);
        if (!match) {
          addLogEntry(
            "❌ No RUN_DATA JSON found in server response",
            "received",
          );
          return;
        }

        let payload;
        try {
          payload = JSON.parse(match[1]);
        } catch (e) {
          addLogEntry(
            `❌ Error parsing RUN_DATA JSON: ${e.message}`,
            "received",
          );
          return;
        }

        loadHistoricalRun(payload);
      } catch (error) {
        addLogEntry(
          `Error sending get_run_data: ${error.message}`,
          "received",
        );
      }

      return;
    }

    const desc = runDescInput ? runDescInput.value.trim() : "";
    const command =
      desc.length > 0
        ? `start_run:${runId}:${encodeURIComponent(desc)}`
        : `start_run:${runId}`;
    addLogEntry(`Sending command: ${command}`, "sent");

    try {
      const response = await sendCommandToServer(command);
      const startedMatch = /✅ Run (\d+) started$/.exec(response.trim());
      addLogEntry(`Server response: ${response}`, "received");
      if(
        startedMatch &&
        parseInt(startedMatch[1], 10) === runID
      ){
        currentActiveRunId = runId;
        expectedNextRunId
        updateRunUI();
      } else {
        addLogEntry("❌ Run not started; local state won't change", "received");
      }
    } catch (error) {
      addLogEntry(
        `Error sending start_run: ${error.message}`,
        "received",
      );
    }
  });

  // Stop: end_run
  runStopButton.addEventListener("click", async () => {
    const command = "end_run";
    addLogEntry(`Sending command: ${command}`, "sent");

    try {
      const response = await sendCommandToServer(command);
      const startedMatch = /✅ Run (\d+) started$/.exec(response.trim());
      addLogEntry(`Server response: ${response}`, "received");

      const ended = parseInt(runIdInput.value, 10);
      if(
        startedMatch &&
        parseInt(startedMatch[1], 10) === runID
      ){
        currentActiveRunId = null;
        expectedNextRunId = ended + 1;
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

// Initialize the chart
const ctx = document
  .getElementById("temperatureChartBB")
  .getContext("2d");
let temperatureChartBB;
let temperatureChart50K;
let temperatureChart4K;
let temperatureChartSTILL;
let temperatureChartMXC;
let currentTimeRangeBB = 60; // Start with 1 minute as default
let currentTimeRangeMXC = 60; // Start with 1 minute as default
let currentTimeRange50K = 60; //Start with 1 minute as default
let currentTimeRange4K = 60; //Start with 1 minute as default
let currentTimeRangeSTILL = 60; //Start with 1 minute as default
let tcpConnectionStatus = null;
let firstDataTime = null;
let lastUpdateTime = null;
let initialParametersLoaded = false;
let pendingMXCToggle = false;
let pending50KToggle = false;
let pending4KToggle = false;
let pendingSTILLToggle = false;
let pendingAutoscanToggle = false;
let pendingExtraChannels = {
  9: false,
  10: false,
  11: false,
  12: false,
  13: false,
  14: false,
  15: false,
};

// Variables to store temperature data and timestamps
let temperatureData = [];
let setpointData = [];

// Variables to store relative and absolute time labels
let absoluteTimeLabels = [];
let relativeTimeLabels = [];
/*
        absoluteTimeLabels stores timestamps in miliseconds
        relativeTimeLabels stores time values in seconds relative to firstDataTime.
        relativeTimeLabels is used for x-axis labels in charts, and it is calculated
        as (Date.now() - firstDataTime) / 1000
        */

// Track parameter values
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

// Track last sent values
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

// Track charts for each stage
const charts = {
  "50K": null,
  "4K": null,
  STILL: null,
  MXC: null,
  BB: null,
};

// Store chart data for each stage
const chartDataStore = {
  "50K": {
    labels: [],
    data: [],
    startTime: null,
    lastTimestamp: null,
  },
  "4K": {
    labels: [],
    data: [],
    startTime: null,
    lastTimestamp: null,
  },
  STILL: {
    labels: [],
    data: [],
    startTime: null,
    lastTimestamp: null,
  },
  MXC: {
    labels: [],
    data: [],
    setpoint: [],
    startTime: null,
    lastTimestamp: null,
  },
  BB: { labels: [], data: [], setpoint: [] },
};

// Time range options in seconds (from largest to smallest)
const timeRangeOptions = [
  { value: 60, label: "1 Minute" },
  { value: 300, label: "5 Minutes" },
  { value: 900, label: "15 Minutes" },
  { value: 1800, label: "30 Minutes" },
  { value: 3600, label: "1 Hour" },
  { value: 21600, label: "6 Hours" },
];

// IDs for MXC control parameters
const MXC_CONTROL_IDS = [
  "temperatureSetpointMXC",
  "proportionalGainMXC",
  "integralGainMXC",
  "derivativeGainMXC",
  "heaterRangeMXC",
];

const MXC_SENSOR_IDS = [
  "dwellMXC",
  "pauseMXC",
  "sensorRangeMXC",
  "sensorModeMXC",
];

// Variable to track last time parameters were updated and when to update them again
let lastParameterBoxUpdateTime = 0;
const parameterBoxUpdateInterval = 60000; // 1 minute = 60000

// Set up collapsible sections
function setupCollapsibleSections(context = document) {
  const sectionTitles = context.querySelectorAll(".section-title");

  sectionTitles.forEach((title) => {
    const content = title.nextElementSibling;
    if (!content) return;

    // Ensure initial state matches class
    if (title.classList.contains("collapsed")) {
      content.classList.add("collapsed");
      content.style.maxHeight = "0";
    } else {
      content.classList.remove("collapsed");
      content.style.maxHeight = content.scrollHeight + "px";
    }

    // Prevent duplicate listeners
    if (!title.dataset.listenerAttached) {
      title.addEventListener("click", function (event) {
        // In MXC, do not collapse when clicking buttons, inputs or selects
        if (this.classList.contains("stage-title-mxc")) {
          const clickedControls = event.target.closest("#mxcTitleControls");

          if (clickedControls) {
            return;
          }

          const clickedTitle = event.target.closest("h2");

          const rect = this.getBoundingClientRect();
          const clickedArrowZone = event.clientX > rect.right - 55;

          // MXC only collapses from the title text or the triangle area
          if (!clickedTitle && !clickedArrowZone) {
            return;
          }
        }

        this.classList.toggle("collapsed");

        if (this.classList.contains("collapsed")) {
          content.classList.add("collapsed");
          content.style.maxHeight = "0";
        } else {
          content.classList.remove("collapsed");
          content.style.maxHeight = content.scrollHeight + "px";
        }
      });

      title.dataset.listenerAttached = true;
    }
  });
}
function clearPendingExtraChannelsForSampleChannels() {
  [9, 10, 11, 12, 13, 14, 15].forEach((ch) => {
    if (pendingExtraChannels && pendingExtraChannels[ch] !== undefined) {
      pendingExtraChannels[ch] = false;
    }
  });
}

// Function to update available time range options based on data duration
function updateTimeRangeOptions() {
  const select = document.getElementById("timeRangeMXC");
  const store = chartDataStore["MXC"];
  if (!store || !store.startTime) return;

  const totalElapsedSec = Math.max(
    0,
    (Date.now() - store.startTime) / 1000,
  );

  // timeRangeOptions is ascending: [1m, 5m, 15m, 30m, 1h, 6h]
  select.innerHTML = "";
  for (let i = 0; i < timeRangeOptions.length; i++) {
    const option = timeRangeOptions[i];
    const opt = document.createElement("option");
    opt.value = option.value;
    opt.textContent = option.label;

    // Unlock rule:
    // - First option (1 min) always available
    // - Option i (e.g., 5 min) becomes available when totalElapsed ≥ value of option i-1 (e.g., 1 min)
    if (i === 0) {
      opt.disabled = false;
    } else {
      const prevValue = timeRangeOptions[i - 1].value;
      opt.disabled = totalElapsedSec < prevValue;
    }

    if (option.value === currentTimeRangeMXC) opt.selected = true;
    select.appendChild(opt);
  }

  // If current selection got disabled, snap to largest enabled option
  if (select.options[select.selectedIndex]?.disabled) {
    for (let i = select.options.length - 1; i >= 0; i--) {
      if (!select.options[i].disabled) {
        select.selectedIndex = i;
        currentTimeRangeMXC = parseInt(select.options[i].value, 10);
        break;
      }
    }
  }
}

function updateTimeRangeOptions50K() {
  const select = document.getElementById("timeRange50K");
  const store = chartDataStore["50K"];
  if (!store || !store.startTime) return;

  const totalElapsedSec = Math.max(
    0,
    (Date.now() - store.startTime) / 1000,
  );

  select.innerHTML = "";
  for (let i = 0; i < timeRangeOptions.length; i++) {
    const option = timeRangeOptions[i];
    const opt = document.createElement("option");
    opt.value = option.value;
    opt.textContent = option.label;

    if (i === 0) {
      opt.disabled = false;
    } else {
      const prevValue = timeRangeOptions[i - 1].value;
      opt.disabled = totalElapsedSec < prevValue;
    }

    if (option.value === currentTimeRange50K) opt.selected = true;
    select.appendChild(opt);
  }

  if (select.options[select.selectedIndex]?.disabled) {
    for (let i = select.options.length - 1; i >= 0; i--) {
      if (!select.options[i].disabled) {
        select.selectedIndex = i;
        currentTimeRange50K = parseInt(select.options[i].value, 10);
        break;
      }
    }
  }
}

function updateTimeRangeOptions4K() {
  const select = document.getElementById("timeRange4K");
  const store = chartDataStore["4K"];
  if (!store || !store.startTime) return;

  const totalElapsedSec = Math.max(
    0,
    (Date.now() - store.startTime) / 1000,
  );

  select.innerHTML = "";

  for (let i = 0; i < timeRangeOptions.length; i++) {
    const option = timeRangeOptions[i];
    const opt = document.createElement("option");
    opt.value = option.value;
    opt.textContent = option.label;

    if (i === 0) {
      opt.disabled = false;
    } else {
      const prevValue = timeRangeOptions[i - 1].value;
      opt.disabled = totalElapsedSec < prevValue;
    }

    if (parseInt(option.value, 10) === currentTimeRange4K) {
      opt.selected = true;
    }

    select.appendChild(opt);
  }

  if (select.options[select.selectedIndex]?.disabled) {
    for (let i = select.options.length - 1; i >= 0; i--) {
      if (!select.options[i].disabled) {
        select.selectedIndex = i;
        currentTimeRange4K = parseInt(select.options[i].value, 10);
        break;
      }
    }
  }
}

function updateTimeRangeOptionsSTILL() {
  const select = document.getElementById("timeRangeSTILL");
  const store = chartDataStore["STILL"];
  if (!store || !store.startTime) return;

  const totalElapsedSec = Math.max(
    0,
    (Date.now() - store.startTime) / 1000,
  );

  select.innerHTML = "";

  for (let i = 0; i < timeRangeOptions.length; i++) {
    const option = timeRangeOptions[i];
    const opt = document.createElement("option");
    opt.value = option.value;
    opt.textContent = option.label;

    if (i === 0) {
      opt.disabled = false;
    } else {
      const prevValue = timeRangeOptions[i - 1].value;
      opt.disabled = totalElapsedSec < prevValue;
    }

    if (parseInt(option.value, 10) === currentTimeRangeSTILL) {
      opt.selected = true;
    }

    select.appendChild(opt);
  }

  if (select.options[select.selectedIndex]?.disabled) {
    for (let i = select.options.length - 1; i >= 0; i--) {
      if (!select.options[i].disabled) {
        select.selectedIndex = i;
        currentTimeRangeSTILL = parseInt(select.options[i].value, 10);
        break;
      }
    }
  }
}

// Function to update UI controls with current parameter values
function updateParameterControls() {
  // Update input fields with server values on first load
  if (!initialParametersLoaded) {
    if (currentParameters.temperatureSetpoint !== null) {
      document.getElementById("temperatureSetpoint").value =
        currentParameters.temperatureSetpoint;
    }
    if (currentParameters.heaterPower !== null) {
      document.getElementById("heaterPower").value =
        currentParameters.heaterPower;
    }
    if (currentParameters.heaterRange !== null) {
      document.getElementById("heaterRange").value =
        currentParameters.heaterRange;
    }
    if (currentParameters.temperatureLimit !== null) {
      document.getElementById("temperatureLimit").value =
        currentParameters.temperatureLimit;
    }
    if (currentParameters.timeout !== null) {
      document.getElementById("timeout").value =
        currentParameters.timeout;
    }
    if (currentParameters.proportionalGain !== null) {
      document.getElementById("proportionalGain").value =
        currentParameters.proportionalGain;
    }
    if (currentParameters.integralGain !== null) {
      document.getElementById("integralGain").value =
        currentParameters.integralGain;
    }
    if (currentParameters.derivativeGain !== null) {
      document.getElementById("derivativeGain").value =
        currentParameters.derivativeGain;
    }
    if (currentParameters.MXCSP !== null) {
      document.getElementById("temperatureSetpointMXC").value =
        currentParameters.MXCSP;
    }
    if (currentParameters.MXCP !== null) {
      document.getElementById("proportionalGainMXC").value =
        currentParameters.MXCP;
    }
    if (currentParameters.MXCI !== null) {
      document.getElementById("integralGainMXC").value =
        currentParameters.MXCI;
    }
    if (currentParameters.MXCD !== null) {
      document.getElementById("derivativeGainMXC").value =
        currentParameters.MXCD;
    }
    if (currentParameters.MXCHR !== null) {
      document.getElementById("heaterRangeMXC").value =
        currentParameters.MXCHR;
    }
    if (currentParameters.dwellMXC !== null) {
      document.getElementById("dwellMXC").value =
        currentParameters.dwellMXC;
    }
    if (currentParameters.pauseMXC !== null) {
      document.getElementById("pauseMXC").value =
        currentParameters.pauseMXC;
    }
    if (currentParameters.rangeMXC !== null) {
      document.getElementById("sensorRangeMXC").value =
        currentParameters.rangeMXC;
    }
    if (currentParameters.modeMXC !== null) {
      document.getElementById("sensorModeMXC").value =
        currentParameters.modeMXC;
    }
    if (currentParameters.autorangeMXC !== null) {
      document.getElementById("autorangeMXC").checked =
        currentParameters.autorangeMXC;
    }
    if (currentParameters.dwell50K !== null) {
      document.getElementById("dwell50K").value =
        currentParameters.dwell50K;
    }
    if (currentParameters.pause50K !== null) {
      document.getElementById("pause50K").value =
        currentParameters.pause50K;
    }

    if (currentParameters.dwell4K !== null) {
      document.getElementById("dwell4K").value =
        currentParameters.dwell4K;
    }
    if (currentParameters.pause4K !== null) {
      document.getElementById("pause4K").value =
        currentParameters.pause4K;
    }

    if (currentParameters.dwellSTILL !== null) {
      document.getElementById("dwellSTILL").value =
        currentParameters.dwellSTILL;
    }
    if (currentParameters.pauseSTILL !== null) {
      document.getElementById("pauseSTILL").value =
        currentParameters.pauseSTILL;
    }
    if (currentParameters.range50K !== null) {
      document.getElementById("sensorRange50K").value =
        currentParameters.range50K;
    }
    if (currentParameters.mode50K !== null) {
      document.getElementById("sensorMode50K").value =
        currentParameters.mode50K;
    }
    if (currentParameters.range4K !== null) {
      document.getElementById("sensorRange4K").value =
        currentParameters.range4K;
    }
    if (currentParameters.mode4K !== null) {
      document.getElementById("sensorMode4K").value =
        currentParameters.mode4K;
    }
    if (currentParameters.rangeSTILL !== null) {
      document.getElementById("sensorRangeSTILL").value =
        currentParameters.rangeSTILL;
    }
    if (currentParameters.modeSTILL !== null) {
      document.getElementById("sensorModeSTILL").value =
        currentParameters.modeSTILL;
    }
    if (currentParameters.curveMXC !== null) {
      document.getElementById("curveMXCSelect").value =
        currentParameters.curveMXC;
    }

    if (currentParameters.curve50K !== null) {
      document.getElementById("curve50KSelect").value =
        currentParameters.curve50K;
    }
    if (currentParameters.curve4K !== null) {
      document.getElementById("curve4KSelect").value =
        currentParameters.curve4K;
    }
    if (currentParameters.curveSTILL !== null) {
      document.getElementById("curveSTILLSelect").value =
        currentParameters.curveSTILL;
    }
    initialParametersLoaded = true;
  }

  // Update current value displays
  if (currentParameters.temperatureSetpoint !== null) {
    document.getElementById("currentTemperatureSetpoint").textContent =
      currentParameters.temperatureSetpoint.toFixed(1);
  }
  if (currentParameters.heaterPower !== null) {
    document.getElementById("currentHeaterPower").textContent =
      currentParameters.heaterPower.toFixed(2);
  }
  if (currentParameters.heaterRange !== null) {
    document.getElementById("currentHeaterRange").textContent =
      currentParameters.heaterRange;
  }
  if (currentParameters.temperatureLimit !== null) {
    document.getElementById("currentTemperatureLimit").textContent =
      currentParameters.temperatureLimit.toFixed(1);
  }
  if (currentParameters.timeout !== null) {
    document.getElementById("currentTimeout").textContent =
      currentParameters.timeout.toFixed(0);
  }
  if (currentParameters.proportionalGain !== null) {
    document.getElementById("currentProportionalGain").textContent =
      currentParameters.proportionalGain.toFixed(3);
  }
  if (currentParameters.integralGain !== null) {
    document.getElementById("currentIntegralGain").textContent =
      currentParameters.integralGain.toFixed(3);
  }
  if (currentParameters.derivativeGain !== null) {
    document.getElementById("currentDerivativeGain").textContent =
      currentParameters.derivativeGain.toFixed(3);
  }
  if (currentParameters.MXCSP !== null) {
    document.getElementById("temperatureSetpointMXC").value =
      currentParameters.MXCSP;
  }
  if (currentParameters.MXCP !== null) {
    document.getElementById("proportionalGainMXC").value =
      currentParameters.MXCP;
  }
  if (currentParameters.MXCI !== null) {
    document.getElementById("integralGainMXC").value =
      currentParameters.MXCI;
  }
  if (currentParameters.MXCD !== null) {
    document.getElementById("derivativeGainMXC").value =
      currentParameters.MXCD;
  }
  if (currentParameters.MXCHR !== null) {
    document.getElementById("heaterRangeMXC").value =
      currentParameters.MXCHR;
  }
  if (currentParameters.dwellMXC !== null) {
    document.getElementById("dwellMXC").value =
      currentParameters.dwellMXC;
  }
  if (currentParameters.pauseMXC !== null) {
    document.getElementById("pauseMXC").value =
      currentParameters.pauseMXC;
  }
  if (currentParameters.rangeMXC !== null) {
    document.getElementById("sensorRangeMXC").value =
      currentParameters.rangeMXC;
  }
  if (currentParameters.modeMXC !== null) {
    document.getElementById("sensorModeMXC").value =
      currentParameters.modeMXC;
  }
  if (currentParameters.autorangeMXC !== null) {
    document.getElementById("autorangeMXC").checked =
      currentParameters.autorangeMXC;
  }
  if (currentParameters.dwell50K !== null) {
    document.getElementById("dwell50K").value =
      currentParameters.dwell50K;
  }
  if (currentParameters.pause50K !== null) {
    document.getElementById("pause50K").value =
      currentParameters.pause50K;
  }

  if (currentParameters.dwell4K !== null) {
    document.getElementById("dwell4K").value = currentParameters.dwell4K;
  }
  if (currentParameters.pause4K !== null) {
    document.getElementById("pause4K").value = currentParameters.pause4K;
  }

  if (currentParameters.dwellSTILL !== null) {
    document.getElementById("dwellSTILL").value =
      currentParameters.dwellSTILL;
  }
  if (currentParameters.pauseSTILL !== null) {
    document.getElementById("pauseSTILL").value =
      currentParameters.pauseSTILL;
  }
  if (currentParameters.range50K !== null) {
    document.getElementById("sensorRange50K").value =
      currentParameters.range50K;
  }
  if (currentParameters.mode50K !== null) {
    document.getElementById("sensorMode50K").value =
      currentParameters.mode50K;
  }
  if (currentParameters.range4K !== null) {
    document.getElementById("sensorRange4K").value =
      currentParameters.range4K;
  }
  if (currentParameters.mode4K !== null) {
    document.getElementById("sensorMode4K").value =
      currentParameters.mode4K;
  }
  if (currentParameters.rangeSTILL !== null) {
    document.getElementById("sensorRangeSTILL").value =
      currentParameters.rangeSTILL;
  }
  if (currentParameters.modeSTILL !== null) {
    document.getElementById("sensorModeSTILL").value =
      currentParameters.modeSTILL;
  }
  if (currentParameters.curveMXC !== null) {
    document.getElementById("curveMXCSelect").value =
      currentParameters.curveMXC;
  }
  if (currentParameters.curve50K !== null) {
    document.getElementById("curve50KSelect").value =
      currentParameters.curve50K;
  }
  if (currentParameters.curve4K !== null) {
    document.getElementById("curve4KSelect").value =
      currentParameters.curve4K;
  }
  if (currentParameters.curveSTILL !== null) {
    document.getElementById("curveSTILLSelect").value =
      currentParameters.curveSTILL;
  }
}

// Function to check TCP server connection status
async function checkConnectionStatus() {
  try {
    const response = await fetch("/get-data");
    if (response.ok) {
      return true;
    }
    return false;
  } catch (error) {
    return false;
  }
}

// Function to update connection status (only logs if status changed)
async function updateConnectionStatus() {
  const newStatus = await checkConnectionStatus();

  if (tcpConnectionStatus === null) {
    // Initial status check
    tcpConnectionStatus = newStatus;
    if (tcpConnectionStatus) {
      addLogEntry("HTTP server is connected to TCP server", "status");
    } else {
      addLogEntry("HTTP server is NOT connected to TCP server", "status");
    }
  } else if (newStatus !== tcpConnectionStatus) {
    // Status changed
    tcpConnectionStatus = newStatus;
    if (tcpConnectionStatus) {
      addLogEntry("Reconnected to TCP server", "status");
    } else {
      addLogEntry("Lost connection to TCP server", "status");
    }
  }

  return tcpConnectionStatus;
}

// General function to create any temperature chart (black body or lakeshore stages)
function createTemperatureChart(
  canvasId,
  includesetpoint = false,
  label = "Temperature (K)",
) {
  // Create a new chart instance
  const ctx = document.getElementById(canvasId).getContext("2d");

  const datasets = [
    {
      label: label,
      data: [],
      borderColor: "royalblue", // 'rgba(75, 192, 192, 1)',
      borderWidth: 1,
      pointRadius: 0,
      fill: includesetpoint
        ? {
            target: "1", // Fill to dataset index 1 (setpoint)
            above: "rgba(173, 216, 230, 0.1)", // Fill color when temperature is above setpoint
            below: "rgba(173, 216, 230, 0.1)", // Same fill color when below
          }
        : false,
    },
  ];

  if (includesetpoint) {
    datasets.push({
      label: "Setpoint (K)",
      data: [],
      borderColor: "rgba(255, 99, 132, 0.9)", // Red color
      borderWidth: 2,
      borderDash: [5, 5], // Dashed line
      fill: false,
      pointRadius: 0, // No points
    });
  }

  // Initialize the chart with empty data
  return new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: datasets,
    },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: true,
      scales: {
        x: {
          type: "linear",
          title: {
            display: true,
            text: "Time (s)",
          },
          min: 0,
          max: 60, // Start with 1 minute range
          ticks: {
            callback: function (value) {
              if (currentTimeRangeMXC > 21600) {
                return `${(value / 3600).toFixed(1)}h`;
              } else if (currentTimeRangeMXC > 300) {
                return `${(value / 60).toFixed(1)}m`;
              } else {
                return `${value.toFixed(0)}s`;
              }
            },
          },
        },
        y: {
          title: {
            display: true,
            text: "Temperature (K)",
          },
          beginAtZero: false,
        },
      },
    },
  });
}

// Function that allows double-clicking on the Y-axis to edit limits
function enableYAxisLimitEditing(chart, canvasId) {
  const canvas = document.getElementById(canvasId);

  canvas.addEventListener("dblclick", function (event) {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;

    const yAxis = chart.scales.y;
    const yAxisLeft = yAxis.left;
    const yAxisRight = yAxis.right;

    // If click is inside the Y-axis area
    if (x >= yAxisLeft && x <= yAxisRight) {
      const currentMin = chart.options.scales.y.min ?? yAxis.min;
      const currentMax = chart.options.scales.y.max ?? yAxis.max;

      const newMin = prompt(
        `Enter new Y-axis MIN (current: ${currentMin}):`,
        currentMin,
      );
      if (newMin === null || isNaN(parseFloat(newMin))) return;

      const newMax = prompt(
        `Enter new Y-axis MAX (current: ${currentMax}):`,
        currentMax,
      );
      if (newMax === null || isNaN(parseFloat(newMax))) return;

      chart.options.scales.y.min = parseFloat(newMin);
      chart.options.scales.y.max = parseFloat(newMax);
      chart.update();
    }
  });
}

// Function to update any temperature chart with new data
function updateTemperatureChart(
  chartId,
  temperature,
  setpoint = null,
  timestampMs = Date.now(),
) {
  const now = Number(timestampMs);
  const numericTemperature = Number(temperature);

  if (
    !Number.isFinite(now) ||
    !Number.isFinite(numericTemperature)
  ) {
    return;
  }

  // Ensure chart and store exist
  if (!charts[chartId]) {
    console.warn(`⚠️ Chart ${chartId} not initialized.`);
    return;
  }
  if (!chartDataStore[chartId]) {
    console.warn(
      `⚠️ Data store for ${chartId} not found. Initializing...`,
    );
    chartDataStore[chartId] = {
      labels: [],
      data: [],
      setpoint: [],
      startTime: null,
      lastTimestamp: null,
    };
  }

  const store = chartDataStore[chartId];

  // /get-data is requested every second, but the Lake Shore
  // may keep returning the same acquisition for several requests.
  if (
    store.lastTimestamp !== null &&
    now <= store.lastTimestamp
  ) {
    return;
  }

  // Initialize startTime the first time this runs
  if (!store.startTime) {
    store.startTime = now;
  }

  // Time in seconds since the first data point
  const relTime = (now - store.startTime) / 1000;

  // Push new data
  store.labels.push(relTime);
  store.data.push(numericTemperature);

  if (setpoint !== null) {
    store.setpoint.push(setpoint);
  }

  store.lastTimestamp = now;

  if (chartId === "MXC") {
    updateTimeRangeOptions();
  } else if (chartId === "50K") {
    updateTimeRangeOptions50K();
  } else if (chartId === "4K") {
    updateTimeRangeOptions4K();
  } else if (chartId === "STILL") {
    updateTimeRangeOptionsSTILL();
  }

  console.log(
    `➡ Pushed to ${chartId}: T=${temperature}, S=${setpoint}, t=${relTime.toFixed(
      2,
    )}`,
  );
  console.log(`✅ Store after push (${chartId}):`, store);

  let currentRange;
  if (chartId === "MXC") {
    currentRange = currentTimeRangeMXC;
  } else if (chartId === "50K") {
    currentRange = currentTimeRange50K;
  } else if (chartId === "4K") {
    currentRange = currentTimeRange4K;
  } else if (chartId === "STILL") {
    currentRange = currentTimeRangeSTILL;
  } else if (chartId === "BB") {
    currentRange = currentTimeRangeBB;
  } else {
    currentRange = 60; // fallback por si acaso
  }
  const displayTimeStart = Math.max(0, relTime - currentRange);
  const labelsFiltered = [];
  const tempFiltered = [];
  const setpointFiltered = [];

  for (let i = 0; i < store.labels.length; i++) {
    const t = store.labels[i];
    if (t >= displayTimeStart) {
      labelsFiltered.push(t - displayTimeStart);
      tempFiltered.push(store.data[i]);
      if (setpoint !== null && store.setpoint) {
        setpointFiltered.push(store.setpoint[i]);
      }
    }
  }

  const chart = charts[chartId];
  chart.data.labels = labelsFiltered;
  chart.data.datasets[0].data = tempFiltered;
  if (setpoint !== null && chart.data.datasets[1]) {
    chart.data.datasets[1].data = setpointFiltered;
  }

  // Update x-axis scale
  chart.options.scales.x.min = 0;
  chart.options.scales.x.max = currentRange;

  // Optional Y-axis safety clamp
  chart.options.scales.y.suggestedMin = 0;

  chart.update("none");
}

// Update chart time range function
function updateTimeRange() {
  const timeRangeSelect = document.getElementById("timeRangeMXC");
  currentTimeRangeMXC = parseInt(timeRangeSelect.value, 10); // <-- use the right variable

  // Re-slice from the store immediately so the axis updates now
  redrawFromStore("MXC");
}

function updateTimeRange50K() {
  const timeRangeSelect = document.getElementById("timeRange50K");
  currentTimeRange50K = parseInt(timeRangeSelect.value, 10);
  redrawFromStore("50K");
}

function updateTimeRange4K() {
  const timeRangeSelect = document.getElementById("timeRange4K");
  currentTimeRange4K = parseInt(timeRangeSelect.value, 10);
  redrawFromStore("4K");
}

function updateTimeRangeSTILL() {
  const timeRangeSelect = document.getElementById("timeRangeSTILL");
  currentTimeRangeSTILL = parseInt(timeRangeSelect.value, 10);
  redrawFromStore("STILL");
}

function updateMXCTemperature(value_mK) {
  document.getElementById("currentTemperatureMXC").textContent =
    value_mK.toFixed(4);
}

function updateMXCValues(temp_K, res_ohm, power_watt) {
  const select = document.getElementById("currentMXCValue");

  let tempLabel;

  // Show in mK if < 1 K, else show in K
  if (temp_K < 1.0) {
    tempLabel = `${(temp_K * 1000).toFixed(3)} mK`;
  } else {
    tempLabel = `${temp_K.toFixed(3)} K`;
  }

  select.options[0].text = tempLabel;
  select.options[1].text = `${res_ohm.toFixed(3)} Ω`;
  select.options[2].text = `${power_watt.toExponential(2)} W`;
}

function updateMXCHeaterOutput(percent) {
  const span = document.getElementById("heaterOutputMXC");
  if (!span) return;

  if (typeof percent === "number" && isFinite(percent)) {
    span.textContent = `${percent.toFixed(1)} %`;
  } else {
    span.textContent = "- %";
  }
}

function update50KValues(temp_K, res_ohm, power_watt) {
  const select = document.getElementById("current50KValue");

  let tempLabel =
    typeof temp_K === "number" && isFinite(temp_K)
      ? temp_K < 1.0
        ? `${(temp_K * 1000).toFixed(3)} mK`
        : `${temp_K.toFixed(3)} K`
      : "-";

  const resLabel =
    typeof res_ohm === "number" && isFinite(res_ohm)
      ? `${res_ohm.toFixed(3)} Ω`
      : "- Ω";

  const powerLabel =
    typeof power_watt === "number" && isFinite(power_watt)
      ? `${power_watt.toExponential(2)} W`
      : "- W";

  select.options[0].text = tempLabel;
  select.options[1].text = resLabel;
  select.options[2].text = powerLabel;
}

function update4KValues(temp_K, res_ohm, power_watt) {
  const select = document.getElementById("current4KValue");

  let tempLabel =
    typeof temp_K === "number" && isFinite(temp_K)
      ? temp_K < 1.0
        ? `${(temp_K * 1000).toFixed(3)} mK`
        : `${temp_K.toFixed(3)} K`
      : "-";

  const resLabel =
    typeof res_ohm === "number" && isFinite(res_ohm)
      ? `${res_ohm.toFixed(3)} Ω`
      : "- Ω";

  const powerLabel =
    typeof power_watt === "number" && isFinite(power_watt)
      ? `${power_watt.toExponential(2)} W`
      : "- W";

  select.options[0].text = tempLabel;
  select.options[1].text = resLabel;
  select.options[2].text = powerLabel;
}

function updateSTILLValues(temp_K, res_ohm, power_watt) {
  const select = document.getElementById("currentSTILLValue");

  let tempLabel =
    typeof temp_K === "number" && isFinite(temp_K)
      ? temp_K < 1.0
        ? `${(temp_K * 1000).toFixed(3)} mK`
        : `${temp_K.toFixed(3)} K`
      : "-";

  const resLabel =
    typeof res_ohm === "number" && isFinite(res_ohm)
      ? `${res_ohm.toFixed(3)} Ω`
      : "- Ω";

  const powerLabel =
    typeof power_watt === "number" && isFinite(power_watt)
      ? `${power_watt.toExponential(2)} W`
      : "- W";

  select.options[0].text = tempLabel;
  select.options[1].text = resLabel;
  select.options[2].text = powerLabel;
}

function redrawFromStore(chartId) {
  const chart = charts[chartId];
  const store = chartDataStore[chartId];
  if (!chart || !store) return;

  const now = Date.now();
  const relTime = (now - store.startTime) / 1000;
  let currentRange;
  if (chartId === "MXC") {
    currentRange = currentTimeRangeMXC;
  } else if (chartId === "50K") {
    currentRange = currentTimeRange50K;
  } else if (chartId === "4K") {
    currentRange = currentTimeRange4K;
  } else if (chartId === "STILL") {
    currentRange = currentTimeRangeSTILL;
  } else if (chartId === "BB") {
    currentRange = currentTimeRangeBB;
  } else {
    currentRange = 60;
  }
  const displayTimeStart = Math.max(0, relTime - currentRange);

  const labelsFiltered = [];
  const tempFiltered = [];
  const setpointFiltered = [];

  for (let i = 0; i < store.labels.length; i++) {
    const t = store.labels[i];
    if (t >= displayTimeStart) {
      labelsFiltered.push(t - displayTimeStart);
      tempFiltered.push(store.data[i]);
      if (store.setpoint) setpointFiltered.push(store.setpoint[i]);
    }
  }

  chart.data.labels = labelsFiltered;
  chart.data.datasets[0].data = tempFiltered;
  if (chart.data.datasets[1]) {
    chart.data.datasets[1].data = setpointFiltered;
  }

  chart.options.scales.x.min = 0;
  chart.options.scales.x.max = currentRange;
  chart.update("none");
}

async function loadTemperatureBuffer() {
  try {
    const response = await fetch("/get-buffer", {
      cache: "no-store",
    });

    if (!response.ok) {
      throw new Error(
        `/get-buffer returned HTTP ${response.status}`,
      );
    }

    const payload = await response.json();
    const channels = payload.channels || {};
    const loadedSamples = {};

    for (const chartId of ["50K", "4K", "STILL", "MXC"]) {
      const source = channels[chartId];
      const store = chartDataStore[chartId];

      if (!source || !store) {
        continue;
      }

      const timestamps = Array.isArray(source.timestamps_ms)
        ? source.timestamps_ms
        : [];

      const temperatures = Array.isArray(source.temperature_k)
        ? source.temperature_k
        : [];

      const setpoints =
        chartId === "MXC" && Array.isArray(source.setpoint_k)
          ? source.setpoint_k
          : [];

      const sampleCount = Math.min(
        timestamps.length,
        temperatures.length,
      );

      store.labels.length = 0;
      store.data.length = 0;
      store.startTime = null;
      store.lastTimestamp = null;

      if (Array.isArray(store.setpoint)) {
        store.setpoint.length = 0;
      }

      for (let i = 0; i < sampleCount; i++) {
        const timestamp = Number(timestamps[i]);
        const temperature = Number(temperatures[i]);

        if (
          !Number.isFinite(timestamp) ||
          !Number.isFinite(temperature)
        ) {
          continue;
        }

        if (
          store.lastTimestamp !== null &&
          timestamp <= store.lastTimestamp
        ) {
          continue;
        }

        if (store.startTime === null) {
          store.startTime = timestamp;
        }

        store.labels.push(
          (timestamp - store.startTime) / 1000,
        );

        store.data.push(temperature);
        store.lastTimestamp = timestamp;

        if (chartId === "MXC") {
          const rawSetpoint = setpoints[i];

          if (
            rawSetpoint === null ||
            rawSetpoint === undefined
          ) {
            store.setpoint.push(null);
          } else {
            const numericSetpoint = Number(rawSetpoint);

            store.setpoint.push(
              Number.isFinite(numericSetpoint)
                ? numericSetpoint
                : null,
            );
          }
        }
      }

      loadedSamples[chartId] = store.data.length;

      if (store.startTime !== null) {
        if (chartId === "MXC") {
          updateTimeRangeOptions();
        } else if (chartId === "50K") {
          updateTimeRangeOptions50K();
        } else if (chartId === "4K") {
          updateTimeRangeOptions4K();
        } else if (chartId === "STILL") {
          updateTimeRangeOptionsSTILL();
        }

        redrawFromStore(chartId);
      }
    }

    console.log(
      "✅ Temperature buffer loaded:",
      loadedSamples,
    );
  } catch (error) {
    console.error(
      "Error loading temperature buffer:",
      error,
    );
  }
}

// Function to add a log entry to the log box
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

// Helper function to send a command to the server
async function sendCommandToServer(command) {
  const response = await fetch("/send-command", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ command }),
  });

  const result = await response.json();

  // Check if we thought we were disconnected but got a response
  if (tcpConnectionStatus === false) {
    tcpConnectionStatus = true;
    addLogEntry("Reconnected to TCP server", "status");
  }

  return result.status;
}

// Function to send only changed parameters to the server
async function sendControlParameters() {
  if (tcpConnectionStatus === false) {
    addLogEntry(
      "Cannot send command: No connection to TCP server",
      "status",
    );
    return;
  }

  // Get current values from UI
  const currentValues = {
    temperatureSetpoint: parseFloat(
      document.getElementById("temperatureSetpoint").value,
    ),
    heaterPower: parseFloat(document.getElementById("heaterPower").value),
    heaterRange: document.getElementById("heaterRange").value,
    temperatureLimit: parseFloat(
      document.getElementById("temperatureLimit").value,
    ),
    timeout: parseFloat(document.getElementById("timeout").value),
    proportionalGain: parseFloat(
      document.getElementById("proportionalGain").value,
    ),
    integralGain: parseFloat(
      document.getElementById("integralGain").value,
    ),
    derivativeGain: parseFloat(
      document.getElementById("derivativeGain").value,
    ),
  };

  // Validate values and check for changes
  const commandsToSend = [];

  // Check temperature setpoint
  if (
    !isNaN(currentValues.temperatureSetpoint) &&
    currentValues.temperatureSetpoint !==
      lastSentValues.temperatureSetpoint
  ) {
    commandsToSend.push({
      type: "temperatureSetpoint",
      command: `set_temperature_setpoint:${currentValues.temperatureSetpoint}`,
    });
  }

  // Check heater power
  if (
    !isNaN(currentValues.heaterPower) &&
    currentValues.heaterPower !== lastSentValues.heaterPower
  ) {
    if (currentValues.heaterPower < 0 || currentValues.heaterPower > 1) {
      addLogEntry(
        "Error: Heater power must be between 0.0 and 1.0",
        "received",
      );
      return;
    }
    commandsToSend.push({
      type: "heaterPower",
      command: `set_heater_power:${currentValues.heaterPower}`,
    });
  }

  // Check heater range
  if (currentValues.heaterRange !== lastSentValues.heaterRange) {
    commandsToSend.push({
      type: "heaterRange",
      command: `set_heater_range:${currentValues.heaterRange}`,
    });
  }

  // Check temperature limit
  if (
    !isNaN(currentValues.temperatureLimit) &&
    currentValues.temperatureLimit !== lastSentValues.temperatureLimit
  ) {
    if (currentValues.temperatureLimit < 0) {
      addLogEntry(
        "Error: Temperature limit must be non-negative",
        "received",
      );
      return;
    }
    commandsToSend.push({
      type: "temperatureLimit",
      command: `set_temperature_limit:${currentValues.temperatureLimit}`,
    });
  }

  // Check timeout
  if (
    !isNaN(currentValues.timeout) &&
    currentValues.timeout !== lastSentValues.timeout
  ) {
    if (currentValues.timeout < 0) {
      addLogEntry("Error: Timeout must be non-negative", "received");
      return;
    }
    commandsToSend.push({
      type: "timeout",
      command: `set_timeout:${currentValues.timeout}`,
    });
  }

  // Check proportional gain
  if (
    !isNaN(currentValues.proportionalGain) &&
    currentValues.proportionalGain !== lastSentValues.proportionalGain
  ) {
    if (currentValues.proportionalGain < 0) {
      addLogEntry(
        "Error: Proportional gain must be non-negative",
        "received",
      );
      return;
    }
    commandsToSend.push({
      type: "proportionalGain",
      command: `set_proportional_gain:${currentValues.proportionalGain}`,
    });
  }

  // Check integral gain
  if (
    !isNaN(currentValues.integralGain) &&
    currentValues.integralGain !== lastSentValues.integralGain
  ) {
    if (currentValues.integralGain < 0) {
      addLogEntry(
        "Error: Integral gain must be non-negative",
        "received",
      );
      return;
    }
    commandsToSend.push({
      type: "integralGain",
      command: `set_integral_gain:${currentValues.integralGain}`,
    });
  }

  // Check derivative gain
  if (
    !isNaN(currentValues.derivativeGain) &&
    currentValues.derivativeGain !== lastSentValues.derivativeGain
  ) {
    if (currentValues.derivativeGain < 0) {
      addLogEntry(
        "Error: Derivative gain must be non-negative",
        "received",
      );
      return;
    }
    commandsToSend.push({
      type: "derivativeGain",
      command: `set_derivative_gain:${currentValues.derivativeGain}`,
    });
  }

  // If no changes detected
  if (commandsToSend.length === 0) {
    addLogEntry("No parameter changes detected", "status");
    return;
  }

  // Send changed parameters
  for (const cmd of commandsToSend) {
    try {
      addLogEntry(`Sending command: ${cmd.command}`, "sent");
      const response = await sendCommandToServer(cmd.command);
      addLogEntry(`Server response: ${response}`, "received");

      // Update last sent value if successful
      lastSentValues[cmd.type] = currentValues[cmd.type];
    } catch (error) {
      addLogEntry(
        `Error sending ${cmd.type}: ${error.message}`,
        "received",
      );
    }
  }
}

function normalizeEnabled(v) {
  if (v === undefined || v === null) return false;

  if (typeof v === "boolean") return v;

  if (typeof v === "number") {
    return v !== 0 && !Number.isNaN(v);
  }

  if (typeof v === "string") {
    const t = v.trim().toLowerCase();
    if (t === "") return false;

    if (["1", "on", "true", "yes", "enabled"].includes(t)) return true;
    if (
      ["0", "off", "false", "no", "disabled", "none", "nan"].includes(t)
    )
      return false;

    const n = Number(t);
    if (!Number.isNaN(n)) return n !== 0;

    return false;
  }

  try {
    return !!v;
  } catch {
    return false;
  }
}

// Function that handles fetching sensor data from the server
// and updates the UI accordingly
async function fetchSensorData(forceUpdateControls = false) {
  try {
    // Fetch data from the server using the /get-data channel
    const response = await fetch("/get-data");
    if (!response.ok) {
      if (tcpConnectionStatus !== false) {
        await updateConnectionStatus();
      }
      return;
    }

    // From that response, parse the JSON data
    const data = await response.json();
    console.log("✅ Received data from server:", data);

    const sampleTimestamp = Number(data.sampleTime);

    // Update parameters if they changed
    if (data["50K"] !== undefined) {
      currentParameters["50K"] = parseFloat(data["50K"]);
    }
    if (data["4K"] !== undefined) {
      currentParameters["4K"] = parseFloat(data["4K"]);
    }
    if (data.STILL !== undefined) {
      currentParameters.STILL = parseFloat(data.STILL);
    }
    if (data.MXC !== undefined) {
      currentParameters.MXC = parseFloat(data.MXC);
    }
    if (data.RMXC !== undefined) {
      currentParameters.RMXC = parseFloat(data.RMXC);
    }
    if (data.PMXC !== undefined) {
      currentParameters.PMXC = parseFloat(data.PMXC);
    }
    if (data.enabledMXC !== undefined) {
      currentParameters.enabledMXC = parseInt(data.enabledMXC);
    }
    if (data.enabled50K !== undefined) {
      currentParameters.enabled50K = parseInt(data.enabled50K);
    }
    if (data.enabled4K !== undefined) {
      currentParameters.enabled4K = parseInt(data.enabled4K);
    }
    if (data.enabledSTILL !== undefined) {
      currentParameters.enabledSTILL = parseInt(data.enabledSTILL);
    }
    if (data.setpoint !== undefined) {
      currentParameters.temperatureSetpoint = parseFloat(data.setpoint);
    }
    if (data.heater_power !== undefined) {
      currentParameters.heaterPower = parseFloat(data.heater_power);
    }
    if (data.heater_range !== undefined) {
      currentParameters.heaterRange = data.heater_range;
    }
    if (data.temperature_limit !== undefined) {
      currentParameters.temperatureLimit = parseFloat(
        data.temperature_limit,
      );
    }
    if (data.timeout !== undefined) {
      currentParameters.timeout = parseFloat(data.timeout);
    }
    if (data.proportional_gain !== undefined) {
      currentParameters.proportionalGain = parseFloat(
        data.proportional_gain,
      );
    }
    if (data.integral_gain !== undefined) {
      currentParameters.integralGain = parseFloat(data.integral_gain);
    }
    if (data.derivative_gain !== undefined) {
      currentParameters.derivativeGain = parseFloat(data.derivative_gain);
    }
    if (data.MXCSP !== undefined) {
      currentParameters.MXCSP = parseFloat(data.MXCSP);
    }
    if (data.MXCP !== undefined) {
      currentParameters.MXCP = parseFloat(data.MXCP);
    }
    if (data.MXCI !== undefined) {
      currentParameters.MXCI = parseFloat(data.MXCI);
    }
    if (data.MXCD !== undefined) {
      currentParameters.MXCD = parseFloat(data.MXCD);
    }
    if (data.MXCHR !== undefined) {
      currentParameters.MXCHR = parseFloat(data.MXCHR);
    }
    if (data.dwellMXC !== undefined) {
      currentParameters.dwellMXC = parseFloat(data.dwellMXC);
    }
    if (data.pauseMXC !== undefined) {
      currentParameters.pauseMXC = parseFloat(data.pauseMXC);
    }
    if (data.modeMXC !== undefined) {
      currentParameters.modeMXC = parseInt(data.modeMXC);
    }
    if (data.rangeMXC !== undefined) {
      currentParameters.rangeMXC = parseInt(data.rangeMXC);
    }
    if (data.autorangeMXC !== undefined) {
      currentParameters.autorangeMXC = parseInt(data.autorangeMXC);
    }
    if (data.dwell50K !== undefined) {
      currentParameters.dwell50K = parseFloat(data.dwell50K);
    }
    if (data.pause50K !== undefined) {
      currentParameters.pause50K = parseFloat(data.pause50K);
    }

    if (data.dwell4K !== undefined) {
      currentParameters.dwell4K = parseFloat(data.dwell4K);
    }
    if (data.pause4K !== undefined) {
      currentParameters.pause4K = parseFloat(data.pause4K);
    }

    if (data.dwellSTILL !== undefined) {
      currentParameters.dwellSTILL = parseFloat(data.dwellSTILL);
    }
    if (data.pauseSTILL !== undefined) {
      currentParameters.pauseSTILL = parseFloat(data.pauseSTILL);
    }
    if (data.mode50K !== undefined) {
      currentParameters.mode50K = parseInt(data.mode50K);
    }
    if (data.range50K !== undefined) {
      currentParameters.range50K = parseInt(data.range50K);
    }

    if (data.mode4K !== undefined) {
      currentParameters.mode4K = parseInt(data.mode4K);
    }
    if (data.range4K !== undefined) {
      currentParameters.range4K = parseInt(data.range4K);
    }

    if (data.modeSTILL !== undefined) {
      currentParameters.modeSTILL = parseInt(data.modeSTILL);
    }
    if (data.rangeSTILL !== undefined) {
      currentParameters.rangeSTILL = parseInt(data.rangeSTILL);
    }
    if (data.autoscan !== undefined) {
      currentParameters.autoscan = data.autoscan;
    }
    if (data.curveMXC !== undefined) {
      currentParameters.curveMXC = parseInt(data.curveMXC);
    }
    if (data.curve50K !== undefined) {
      currentParameters.curve50K = parseInt(data.curve50K);
    }
    if (data.curve4K !== undefined) {
      currentParameters.curve4K = parseInt(data.curve4K);
    }
    if (data.curveSTILL !== undefined) {
      currentParameters.curveSTILL = parseInt(data.curveSTILL);
    }
    if (data.R50K !== undefined) {
      currentParameters.R50K = parseFloat(data.R50K);
    }
    if (data.P50K !== undefined) {
      currentParameters.P50K = parseFloat(data.P50K);
    }
    if (data.R4K !== undefined) {
      currentParameters.R4K = parseFloat(data.R4K);
    }
    if (data.P4K !== undefined) {
      currentParameters.P4K = parseFloat(data.P4K);
    }
    if (data.RSTILL !== undefined) {
      currentParameters.RSTILL = parseFloat(data.RSTILL);
    }
    if (data.PSTILL !== undefined) {
      currentParameters.PSTILL = parseFloat(data.PSTILL);
    }
    if (data.heaterOutputMXC !== undefined) {
      currentParameters.heaterOutputMXC = parseFloat(
        data.heaterOutputMXC,
      );
    }
    if (data.RCH9 !== undefined)
      currentParameters.RCH9 = parseFloat(data.RCH9);
    if (data.RCH10 !== undefined)
      currentParameters.RCH10 = parseFloat(data.RCH10);
    if (data.RCH11 !== undefined)
      currentParameters.RCH11 = parseFloat(data.RCH11);
    if (data.RCH12 !== undefined)
      currentParameters.RCH12 = parseFloat(data.RCH12);
    if (data.RCH13 !== undefined)
      currentParameters.RCH13 = parseFloat(data.RCH13);
    if (data.RCH14 !== undefined)
      currentParameters.RCH14 = parseFloat(data.RCH14);
    if (data.RCH15 !== undefined)
      currentParameters.RCH15 = parseFloat(data.RCH15);

    for (let i = 9; i <= 15; i++) {
      if (data[`enabledCH${i}`] !== undefined) {
        currentParameters[`enabledCH${i}`] = normalizeEnabled(
          data[`enabledCH${i}`],
        )
          ? 1
          : 0;
      }
    }
    if (data.scanning_channel !== undefined) {
      currentParameters.scanning_channel = parseInt(
        data.scanning_channel,
      );
      updateScanningChannel(data.scanning_channel);
    }

    for (let i = 9; i <= 15; i++) {
      if (data[`modeCH${i}`] !== undefined) {
        currentParameters[`modeCH${i}`] =
          data[`modeCH${i}`] === null
            ? null
            : parseInt(data[`modeCH${i}`]);
      }
      if (data[`rangeCH${i}`] !== undefined) {
        currentParameters[`rangeCH${i}`] =
          data[`rangeCH${i}`] === null
            ? null
            : parseInt(data[`rangeCH${i}`]);
      }
    }
    // Update UI controls if parameters changed every minute
    // (or the time specified in parameterBoxUpdateInterval variable)
    const now = Date.now();
    if (
      forceUpdateControls ||
      now - lastParameterBoxUpdateTime > parameterBoxUpdateInterval
    ) {
      console.log("🔄 Updating parameter controls with new values");
      lastParameterBoxUpdateTime = now;
      updateParameterControls();
    }

    // Update last sent values to prevent unnecessary updates
    lastSentValues = {
      temperatureSetpoint: currentParameters.temperatureSetpoint,
      heaterPower: currentParameters.heaterPower,
      heaterRange: currentParameters.heaterRange,
      temperatureLimit: currentParameters.temperatureLimit,
      timeout: currentParameters.timeout,
      proportionalGain: currentParameters.proportionalGain,
      integralGain: currentParameters.integralGain,
      derivativeGain: currentParameters.derivativeGain,
      temperatureSetpointMXC: currentParameters.MXCSP,
      dwellMXC: currentParameters.dwellMXC,
      pauseMXC: currentParameters.pauseMXC,
      modeMXC: currentParameters.modeMXC,
      rangeMXC: currentParameters.rangeMXC,
      autorangeMXC: currentParameters.autorangeMXC,
    };

    // Update the 50k chart with the new temperature
    if (currentParameters["50K"] !== null) {
      updateTemperatureChart(
        "50K",
        currentParameters["50K"],
        null,
        sampleTimestamp,
      );
      update50KValues(
        currentParameters["50K"],
        currentParameters.R50K,
        currentParameters.P50K,
      );
    }

    //Update the 4k chart with the new temperature
    if (currentParameters["4K"] !== null) {
      updateTemperatureChart(
        "4K",
        currentParameters["4K"],
        null,
        sampleTimestamp,
      );
      update4KValues(
        currentParameters["4K"],
        currentParameters.R4K,
        currentParameters.P4K,
      );
    }
    // Update the STILL chart with the new temperature
    if (currentParameters.STILL !== null) {
      console.log(
        "📈 Updating STILL chart with:",
        currentParameters.STILL,
      );

      updateTemperatureChart(
        "STILL",
        currentParameters.STILL,
        null,
        sampleTimestamp,
      );
      updateSTILLValues(
        currentParameters.STILL,
        currentParameters.RSTILL,
        currentParameters.PSTILL,
      );
    }

    // Update the MXC chart with the new temperature
    if (currentParameters.MXC !== null) {
      console.log(
        "📈 Updating MXC chart with:",
        currentParameters.MXC,
        currentParameters.temperatureSetpoint,
      );

      updateTemperatureChart(
        "MXC",
        currentParameters.MXC,
        currentParameters.temperatureSetpoint,
        sampleTimestamp,
      );

      updateMXCValues(
        currentParameters.MXC, // Temperature in mK
        currentParameters.RMXC, // Resistance in Ohms
        currentParameters.PMXC,
      ); // Power in Watts

      updateMXCHeaterOutput(currentParameters.heaterOutputMXC);
    }

    // MXC
    const gMXC = document.getElementById("toggleMXCGlobal");
    const enabledMXC = !!currentParameters.enabledMXC;

    if (gMXC) {
      if (pendingMXCToggle) {
        if (gMXC.checked === enabledMXC) {
          pendingMXCToggle = false;
          console.log(
            `✅ MXC backend synced with UI (${enabledMXC ? "ON" : "OFF"})`,
          );
        } else {
          console.log("⏳ Waiting for MXC backend to catch up...");
        }
      } else if (gMXC.checked !== enabledMXC) {
        gMXC.checked = enabledMXC;
        console.log(
          `🔁 Sync MXC toggle -> ${
            enabledMXC ? "ON" : "OFF"
          } (from controller)`,
        );
      }
    }

    // 50K
    const g50K = document.getElementById("toggle50KGlobal");
    const enabled50K = !!currentParameters.enabled50K;

    if (g50K) {
      if (pending50KToggle) {
        if (g50K.checked === enabled50K) {
          pending50KToggle = false;
          console.log(
            `✅ 50K backend synced with UI (${enabled50K ? "ON" : "OFF"})`,
          );
        } else {
          console.log("⏳ Waiting for 50K backend to catch up...");
        }
      } else if (g50K.checked !== enabled50K) {
        g50K.checked = enabled50K;
        console.log(
          `🔁 Sync 50K toggle -> ${
            enabled50K ? "ON" : "OFF"
          } (from controller)`,
        );
      }
    }

    // STILL
    const gSTILL = document.getElementById("toggleSTILLGlobal");
    const enabledSTILL = !!currentParameters.enabledSTILL;

    if (gSTILL) {
      if (pendingSTILLToggle) {
        if (gSTILL.checked === enabledSTILL) {
          pendingSTILLToggle = false;
          console.log(
            `✅ STILL backend synced with UI (${
              enabledSTILL ? "ON" : "OFF"
            })`,
          );
        } else {
          console.log("⏳ Waiting for STILL backend to catch up...");
        }
      } else if (gSTILL.checked !== enabledSTILL) {
        gSTILL.checked = enabledSTILL;
        console.log(
          `🔁 Sync STILL toggle -> ${
            enabledSTILL ? "ON" : "OFF"
          } (from controller)`,
        );
      }
    }

    // 4K
    const g4K = document.getElementById("toggle4kGlobal");
    const enabled4K = !!currentParameters.enabled4K;

    if (g4K) {
      if (pending4KToggle) {
        if (g4K.checked === enabled4K) {
          pending4KToggle = false;
          console.log(
            `✅ 4K backend synced with UI (${enabled4K ? "ON" : "OFF"})`,
          );
        } else {
          console.log("⏳ Waiting for 4K backend to catch up...");
        }
      } else if (g4K.checked !== enabled4K) {
        g4K.checked = enabled4K;
        console.log(
          `🔁 Sync 4K toggle -> ${
            enabled4K ? "ON" : "OFF"
          } (from controller)`,
        );
      }
    }
    updateStageVisibility();

    SAMPLE_CHANNELS.forEach((chNum) => {
      const checkbox = document.getElementById(
        `toggleExtraChannel${chNum}`,
      );
      const backendEnabled = normalizeEnabled(
        currentParameters[`enabledCH${chNum}`],
      );

      if (checkbox) {
        if (pendingExtraChannels[chNum]) {
          if (checkbox.checked === backendEnabled) {
            pendingExtraChannels[chNum] = false;
            console.log(`✅ Extra Channel ${chNum} synced.`);
          } else {
            console.log(`⏳ Waiting for Channel ${chNum} backend...`);
          }
        } else {
          // Sincronización normal si no hay operación pendiente
          if (checkbox.checked !== backendEnabled) {
            checkbox.checked = backendEnabled;
            console.log(
              `🔁 Sync Extra CH${chNum} -> ${backendEnabled ? "ON" : "OFF"}`,
            );
          }
        }
      }

      const rBox = document.getElementById(`currentRCH${chNum}`);
      if (rBox) {
        if (!backendEnabled) {
          rBox.textContent = "--";
        } else {
          const rVal = currentParameters[`RCH${chNum}`];
          if (rVal === undefined || rVal === null || Number.isNaN(rVal)) {
            rBox.textContent = "--";
          } else {
            rBox.textContent = `${Number(rVal).toFixed(2)} Ω`;
          }
        }
      }
    });

    const autoscanToggle = document.getElementById("autoscanToggle");
    if (autoscanToggle && currentParameters.autoscan !== undefined) {
      const backendAutoscanOn = currentParameters.autoscan === "on";

      if (pendingAutoscanToggle) {
        if (autoscanToggle.checked === backendAutoscanOn) {
          pendingAutoscanToggle = false;
          console.log(
            `✅ Autoscan backend synced with UI (${
              backendAutoscanOn ? "ON" : "OFF"
            })`,
          );
        } else {
          console.log("⏳ Waiting for Autoscan backend to catch up...");
        }
      } else {
        if (autoscanToggle.checked !== backendAutoscanOn) {
          autoscanToggle.checked = backendAutoscanOn;
          console.log(
            `🔁 Sync Autoscan toggle -> ${
              backendAutoscanOn ? "ON" : "OFF"
            } (from controller)`,
          );
        }
      }
    }

    updateRelationStore();
    redrawRelationChart();

    if (tcpConnectionStatus === false) {
      await updateConnectionStatus();
    }
  } catch (error) {
    console.error("Error fetching data:", error);
    if (tcpConnectionStatus !== false) {
      await updateConnectionStatus();
    }
  }
}

// Check initial connection status when page loads
document.addEventListener("DOMContentLoaded", async function () {
  // Set up collapsible sections
  setupCollapsibleSections();

  charts["BB"] = createTemperatureChart(
    "temperatureChartBB",
    true,
    "Black Body Temperature (K)",
  );
  charts["50K"] = createTemperatureChart(
    "temperatureChart50K",
    false,
    "Temperature 50K",
  );

  charts["4K"] = createTemperatureChart(
    "temperatureChart4K",
    false,
    "Temperature 4K",
  );
  charts["STILL"] = createTemperatureChart(
    "temperatureChartSTILL",
    false,
    "Temperature STILL",
  );
  charts["MXC"] = createTemperatureChart(
    "temperatureChartMXC",
    false,
    "Temperature MXC",
  );

  enableYAxisLimitEditing(charts["MXC"], "temperatureChartMXC");
  enableYAxisLimitEditing(charts["STILL"], "temperatureChartSTILL");

  await updateConnectionStatus();

  // Add event listeners for Enter key in all input fields
  // Exclude MXC control and sensor IDs  from this since MXC controls have their own keypress handling
  document.querySelectorAll(".control-input").forEach((input) => {
    const id = input.id;
    if (!MXC_CONTROL_IDS.includes(id) && !MXC_SENSOR_IDS.includes(id)) {
      input.addEventListener("keypress", function (e) {
        if (e.key === "Enter") {
          sendControlParameters();
        }
      });
    }
  });

  // Restore the shared temperature history before adding
  // the latest acquisition from /get-data.
  await loadTemperatureBuffer();
  await fetchSensorData();
  await refreshRecentRuns();
  await refreshRelationFiles();
});

// Fetch data every 1 seconds
setInterval(fetchSensorData, 1000);

async function toggleChannel50K() {
  const checkbox = document.getElementById("toggle50KGlobal");
  const value = checkbox.checked ? 1 : 0;

  const command = `set_channel_50k:${value}`;

  try {
    pending50KToggle = true;
    addLogEntry(`Sending 50K command: ${command}`, "sent");
    const response = await sendCommandToServer(command);
    addLogEntry(`Server response: ${response}`, "received");

    console.log(
      `Channel 50K is now ${checkbox.checked ? "enabled" : "disabled"}`,
    );
    console.log(response);
  } catch (error) {
    checkbox.checked = !checkbox.checked;
    pending50KToggle = false;
    addLogEntry(
      `Error sending set_channel_50k: ${error.message}`,
      "received",
    );
    console.error(error);
  }
}

async function toggleChannelMXC() {
  const checkbox = document.getElementById("toggleMXCGlobal");
  const value = checkbox.checked ? 1 : 0;

  const command = `set_channel_mxc:${value}`;

  try {
    pendingMXCToggle = true;

    addLogEntry(`Sending MXC command: ${command}`, "sent");
    const response = await sendCommandToServer(command);
    addLogEntry(`Server response: ${response}`, "received");

    console.log(
      `Channel MXC is now ${checkbox.checked ? "enabled" : "disabled"}`,
    );
    console.log(response);
  } catch (error) {
    checkbox.checked = !checkbox.checked;
    pendingMXCToggle = false;
    addLogEntry(
      `Error sending set_channel_mxc: ${error.message}`,
      "received",
    );
    console.error(error);
  }
}

async function toggleChannelSTILL() {
  const checkbox = document.getElementById("toggleSTILLGlobal");
  const value = checkbox.checked ? 1 : 0;

  const command = `set_channel_still:${value}`;

  try {
    pendingSTILLToggle = true;

    addLogEntry(`Sending STILL command: ${command}`, "sent");
    const response = await sendCommandToServer(command);
    addLogEntry(`Server response: ${response}`, "received");

    console.log(
      `Channel STILL is now ${checkbox.checked ? "enabled" : "disabled"}`,
    );
    console.log(response);
  } catch (error) {
    checkbox.checked = !checkbox.checked;
    pendingSTILLToggle = false;
    addLogEntry(
      `Error sending set_channel_still: ${error.message}`,
      "received",
    );
    console.error(error);
  }
}

async function toggleChannel4k() {
  const checkbox = document.getElementById("toggle4kGlobal");
  const value = checkbox.checked ? 1 : 0;

  const command = `set_channel_4k:${value}`;

  try {
    pending4KToggle = true;

    addLogEntry(`Sending 4K command: ${command}`, "sent");
    const response = await sendCommandToServer(command);
    addLogEntry(`Server response: ${response}`, "received");

    console.log(
      `Channel 4K is now ${checkbox.checked ? "enabled" : "disabled"}`,
    );
    console.log(response);
  } catch (error) {
    checkbox.checked = !checkbox.checked;
    pending4KToggle = false;
    addLogEntry(
      `Error sending set_channel_4k: ${error.message}`,
      "received",
    );
    console.error(error);
  }
}

async function toggleAutorangeMXC() {
  console.log("Toggling MXC autorange...");

  //Comprobamos conexión TCP
  if (tcpConnectionStatus === false) {
    addLogEntry(
      "Cannot send MXC command: No connection to TCP server",
      "status",
    );
    const cb = document.getElementById("autorangeMXC");
    cb.checked = !cb.checked;
    return;
  }

  const cb = document.getElementById("autorangeMXC");
  const value = cb.checked ? 1 : 0; // 1 = ON, 0 = OFF

  const command = `set_autorange_mxc:${value}`;

  try {
    addLogEntry(`Sending MXC autorange command: ${command}`, "sent");
    const response = await sendCommandToServer(command);
    addLogEntry(`Server response: ${response}`, "received");
    console.log(response);
  } catch (error) {
    addLogEntry(
      `Error sending autorange MXC: ${error.message}`,
      "received",
    );
    cb.checked = !cb.checked;
    console.error(error);
  }
}

async function resetDefaultsMXC() {
  if (tcpConnectionStatus === false) {
    addLogEntry(
      "Cannot reset MXC to default: No connection to TCP server",
      "status",
    );
    return;
  }

  const command = "reset_defaults_mxc";

  try {
    addLogEntry(`Sending MXC reset command: ${command}`, "sent");
    const response = await sendCommandToServer(command);
    addLogEntry(`Server response: ${response}`, "received");
    await sleep(1000);
    await fetchSensorData(true);
  } catch (error) {
    addLogEntry(
      `Error sending MXC reset command: ${error.message}`,
      "received",
    );
    console.error(error);
  }
}

async function resetDefaults50K() {
  if (tcpConnectionStatus === false) {
    addLogEntry(
      "Cannot reset 50K to default: No connection to TCP server",
      "status",
    );
    return;
  }

  const command = "reset_defaults_50k";

  try {
    addLogEntry(`Sending 50K reset command: ${command}`, "sent");
    const response = await sendCommandToServer(command);
    addLogEntry(`Server response: ${response}`, "received");
    await sleep(1000);
    await fetchSensorData(true);
  } catch (error) {
    addLogEntry(
      `Error sending 50K reset command: ${error.message}`,
      "received",
    );
    console.error(error);
  }
}

async function resetDefaults4K() {
  if (tcpConnectionStatus === false) {
    addLogEntry(
      "Cannot reset 4K to default: No connection to TCP server",
      "status",
    );
    return;
  }

  const command = "reset_defaults_4k";

  try {
    addLogEntry(`Sending 4K reset command: ${command}`, "sent");
    const response = await sendCommandToServer(command);
    addLogEntry(`Server response: ${response}`, "received");
    await sleep(1000);
    await fetchSensorData(true);
  } catch (error) {
    addLogEntry(
      `Error sending 4K reset command: ${error.message}`,
      "received",
    );
    console.error(error);
  }
}

async function resetDefaultsSTILL() {
  if (tcpConnectionStatus === false) {
    addLogEntry(
      "Cannot reset STILL to default: No connection to TCP server",
      "status",
    );
    return;
  }

  const command = "reset_defaults_still";

  try {
    addLogEntry(`Sending STILL reset command: ${command}`, "sent");
    const response = await sendCommandToServer(command);
    addLogEntry(`Server response: ${response}`, "received");
    await sleep(1000);
    await fetchSensorData(true);
  } catch (error) {
    addLogEntry(
      `Error sending STILL reset command: ${error.message}`,
      "received",
    );
    console.error(error);
  }
}

async function toggleAutoscan() {
  console.log("Toggling Autoscan...");

  const cb = document.getElementById("autoscanToggle");
  const desiredState = cb.checked;

  if (tcpConnectionStatus === false) {
    addLogEntry(
      "Cannot send Autoscan command: No connection to TCP server",
      "status",
    );
    cb.checked = !desiredState;
    return;
  }

  const valueStr = desiredState ? "on" : "off";
  const command = `set_autoscan:${valueStr}`;

  pendingAutoscanToggle = true;

  try {
    addLogEntry(`Sending Autoscan command: ${command}`, "sent");
    const response = await sendCommandToServer(command);
    addLogEntry(`Server response: ${response}`, "received");
    console.log(response);
  } catch (error) {
    addLogEntry(
      `Error sending Autoscan command: ${error.message}`,
      "received",
    );
    cb.checked = !desiredState;
    pendingAutoscanToggle = false;
    console.error(error);
  }
}

async function writeSensorSettingsMXC() {
  console.log("Writing sensor settings for MXC...");

  //Check if we have a valid TCP connection
  if (tcpConnectionStatus === false) {
    addLogEntry(
      "Cannot send MXC command: No connection to TCP server",
      "status",
    );
    return;
  }

  const values = {
    dwellMXC: parseFloat(document.getElementById("dwellMXC").value),
    pauseMXC: parseFloat(document.getElementById("pauseMXC").value),
    rangeMXC: parseInt(
      document.getElementById("sensorRangeMXC").value,
      10,
    ),
    modeMXC: parseInt(document.getElementById("sensorModeMXC").value, 10),
    curveMXC: parseInt(
      document.getElementById("curveMXCSelect").value,
      10,
    ),
  };

  const commands = [];

  if (!isNaN(values.dwellMXC)) {
    if (values.dwellMXC < 0 || values.dwellMXC > 10) {
      addLogEntry(
        "Error: Dwell time must be between 0.0 and 10.0",
        "received",
      );
      return;
    }
    commands.push({
      type: "dwellMXC",
      command: `set_dwell_mxc:${values.dwellMXC}`,
    });
  }

  if (!isNaN(values.pauseMXC)) {
    if (values.pauseMXC < 0 || values.pauseMXC > 10) {
      addLogEntry(
        "Error: Pause time must be between 0.0 and 10.0",
        "received",
      );
      return;
    }
    commands.push({
      type: "pauseMXC",
      command: `set_pause_mxc:${values.pauseMXC}`,
    });
  }

  if (!isNaN(values.rangeMXC)) {
    if (values.rangeMXC < 1 || values.rangeMXC > 8) {
      addLogEntry(
        "Error: Sensor Range (Excitation) must be between 1 and 8",
        "received",
      );
      return;
    }
    commands.push({
      type: "rangeMXC",
      command: `set_sensor_range_mxc:${values.rangeMXC}`,
    });
  }

  if (!isNaN(values.modeMXC)) {
    if (values.modeMXC !== 0 && values.modeMXC !== 1) {
      addLogEntry(
        "Error: Sensor Mode must be 0 (Voltage) or 1 (Current)",
        "received",
      );
      return;
    }
    commands.push({
      type: "modeMXC",
      command: `set_sensor_mode_mxc:${values.modeMXC}`,
    });
  }

  if (!isNaN(values.curveMXC)) {
    if (values.curveMXC < 0 || values.curveMXC > 20) {
      addLogEntry(
        "Error: Curve number must be between 0 and 20",
        "received",
      );
      return;
    }
    commands.push({
      type: "curveMXC",
      command: `set_curve_mxc:${values.curveMXC}`,
    });
  }

  if (commands.length === 0) {
    addLogEntry(
      "No sensor parameter changes detected or valid",
      "status",
    );
    return;
  }

  const progressContainer = document.getElementById(
    "progressContainerMXC",
  );
  const progressBar = document.getElementById("progressBarMXC");
  const progressText = document.getElementById("progressTextMXC");

  progressContainer.style.display = "block";
  progressBar.style.width = "0%";
  progressText.textContent = "Processing sensor settings...";

  for (const cmd of commands) {
    try {
      addLogEntry(`Sending MXC sensor command: ${cmd.command}`, "sent");
      const response = await sendCommandToServer(cmd.command);
      addLogEntry(`Server response: ${response}`, "received");
      lastSentValues[cmd.type] = values[cmd.type];
    } catch (error) {
      addLogEntry(
        `Error sending ${cmd.type}: ${error.message}`,
        "received",
      );
    }
    const progress =
      ((commands.indexOf(cmd) + 1) / commands.length) * 100;
    progressBar.style.width = `${progress}%`;
    progressText.textContent = `Processing sensor settings... ${Math.round(
      progress,
    )}%`;
    await sleep(150);
  }

  setTimeout(() => {
    progressContainer.style.display = "none";
  }, 1000);
}

async function writeControlSettingsMXC() {
  /*  This function is called when the "Write Control Settings" button is clicked
                It is async since it will send commands to the server, performing asynchronous operations
            */

  console.log("Writing control settings for MXC...");

  // Check if we have a valid TCP connection
  // Log error when no connection to TCP server
  if (tcpConnectionStatus === false) {
    addLogEntry(
      "Cannot send MXC command: No connection to TCP server",
      "status",
    );
    return;
  }

  async function writeExcitationMXC() {
    console.log("Writing excitation level for MXC...");

    if (tcpConnectionStatus === false) {
      addLogEntry(
        "Cannot send MXC command: No connection to TCP server",
        "status",
      );
      return;
    }

    const value = document.getElementById("excitationMXC").value;

    if (!isNaN(value)) {
      if (value < 1 || value > 8) {
        addLogEntry(
          "Error: Sensor range must be between 1 and 8",
          "received",
        );
        return;
      }
    }
  }
  // Get current values from UI
  const values = {
    MXCSP: parseFloat(
      document.getElementById("temperatureSetpointMXC").value,
    ),
    MXCP: parseFloat(
      document.getElementById("proportionalGainMXC").value,
    ),
    MXCI: parseFloat(document.getElementById("integralGainMXC").value),
    MXCD: parseFloat(document.getElementById("derivativeGainMXC").value),
    MXCHR: parseFloat(document.getElementById("heaterRangeMXC").value),
  };

  const commands = [];

  if (!isNaN(values.MXCSP)) {
    if (values.MXCSP < 0 || values.MXCSP > 500) {
      addLogEntry(
        "Error: MXC Setpoint must be between 0.0 and 500.0 K",
        "received",
      );
      return;
    }
    commands.push({
      type: "MXCSP",
      command: `set_mxc_temperature_setpoint:${values.MXCSP}`,
    });
  }

  if (!isNaN(values.MXCP)) {
    if (values.MXCP < 0 || values.MXCP > 10) {
      addLogEntry(
        "Error: MXC Proportional Gain must be between 0.0 and 10.0",
        "received",
      );
      return;
    }
    commands.push({
      type: "MXCP",
      command: `set_mxc_proportional_gain:${values.MXCP}`,
    });
  }

  if (!isNaN(values.MXCI)) {
    if (values.MXCI < 0 || values.MXCI > 10) {
      addLogEntry(
        "Error: MXC Integral Gain must be between 0.0 and 10.0",
        "received",
      );
      return;
    }
    commands.push({
      type: "MXCI",
      command: `set_mxc_integral_gain:${values.MXCI}`,
    });
  }

  if (!isNaN(values.MXCD)) {
    if (values.MXCD < 0 || values.MXCD > 100) {
      addLogEntry(
        "Error: MXC Derivative Gain must be between 0.0 and 100.0",
        "received",
      );
      return;
    }
    commands.push({
      type: "MXCD",
      command: `set_mxc_derivative_gain:${values.MXCD}`,
    });
  }

  if (!isNaN(values.MXCHR)) {
    if (values.MXCHR < 0 || values.MXCHR > 8) {
      addLogEntry(
        "Error: There are only eight heater ranges (0-8) available (being 0 OFF)",
        "received",
      );
      return;
    }
    commands.push({
      type: "MXCHR",
      command: `set_mxc_heater_range:${values.MXCHR}`,
    });
  }

  const progressContainer = document.getElementById(
    "progressContainerMXC",
  );
  const progressBar = document.getElementById("progressBarMXC");
  const progressText = document.getElementById("progressTextMXC");
  progressContainer.style.display = "block";
  progressBar.style.width = "0%";
  progressText.textContent = "Processing...";

  for (const cmd of commands) {
    try {
      addLogEntry(`Sending MXC command: ${cmd.command}`, "sent");
      const response = await sendCommandToServer(cmd.command);
      addLogEntry(`Server response: ${response}`, "received");
      console.log(response);
      // Update last sent value if successful
      lastSentValues[cmd.type] = values[cmd.type];
    } catch (error) {
      addLogEntry(
        `Error sending ${cmd.type}: ${error.message}`,
        "received",
      );
    }
    // Update progress bar
    const progress =
      ((commands.indexOf(cmd) + 1) / commands.length) * 100;
    progressBar.style.width = `${progress}%`;
    progressText.textContent = `Processing... ${Math.round(progress)}%`;
    await sleep(150);
  }

  // Hide progress bar after completion
  setTimeout(() => {
    progressContainer.style.display = "none";
  }, 1000);
}

async function writeSettingsSTILL() {
  if (tcpConnectionStatus === false) {
    addLogEntry(
      "Cannot send STILL command: No connection to TCP server",
      "status",
    );
    return;
  }

  const dwell = parseFloat(document.getElementById("dwellSTILL").value);
  const pause = parseFloat(document.getElementById("pauseSTILL").value);
  const range = parseInt(
    document.getElementById("sensorRangeSTILL").value,
    10,
  );
  const mode = parseInt(
    document.getElementById("sensorModeSTILL").value,
    10,
  );
  const curve = parseInt(
    document.getElementById("curveSTILLSelect").value,
    10,
  );
  const commands = [];

  if (!isNaN(dwell)) {
    if (dwell < 0 || dwell > 10) {
      addLogEntry(
        "Error: STILL dwell time must be between 0.0 and 10.0",
        "received",
      );
      return;
    }
    commands.push(`set_dwell_still:${dwell}`);
  }

  if (!isNaN(pause)) {
    if (pause < 0 || pause > 10) {
      addLogEntry(
        "Error: STILL pause time must be between 0.0 and 10.0",
        "received",
      );
      return;
    }
    commands.push(`set_pause_still:${pause}`);
  }

  if (!isNaN(range)) {
    if (range < 1 || range > 8) {
      addLogEntry(
        "Error: STILL Sensor Range must be between 1 and 8",
        "received",
      );
      return;
    }
    commands.push(`set_sensor_range_still:${range}`);
  }

  if (!isNaN(mode)) {
    if (mode !== 0 && mode !== 1) {
      addLogEntry(
        "Error: STILL Sensor Mode must be 0 (Voltage) or 1 (Current)",
        "received",
      );
      return;
    }
    commands.push(`set_sensor_mode_still:${mode}`);
  }

  if (!isNaN(curve)) {
    if (curve < 0 || curve > 20) {
      addLogEntry(
        "Error: STILL Curve must be between 0 and 20",
        "received",
      );
      return;
    }
    commands.push(`set_curve_still:${curve}`);
  }

  if (commands.length === 0) {
    addLogEntry("No STILL sensor parameter changes detected", "status");
    return;
  }

  const progressContainer = document.getElementById(
    "progressContainerSTILL",
  );
  const progressBar = document.getElementById("progressBarSTILL");
  const progressText = document.getElementById("progressTextSTILL");

  progressContainer.style.display = "block";
  progressBar.style.width = "0%";
  progressText.textContent = "Processing STILL settings...";

  for (const cmd of commands) {
    try {
      addLogEntry(`Sending STILL command: ${cmd}`, "sent");
      const response = await sendCommandToServer(cmd);
      addLogEntry(`Server response: ${response}`, "received");
    } catch (error) {
      addLogEntry(
        `Error sending STILL command ${cmd}: ${error.message}`,
        "received",
      );
    }

    const progress =
      ((commands.indexOf(cmd) + 1) / commands.length) * 100;
    progressBar.style.width = `${progress}%`;
    progressText.textContent = `Processing STILL settings... ${Math.round(
      progress,
    )}%`;
    await sleep(150);
  }

  setTimeout(() => {
    progressContainer.style.display = "none";
  }, 1000);
}

async function writeSettings50K() {
  if (tcpConnectionStatus === false) {
    addLogEntry(
      "Cannot send 50K command: No connection to TCP server",
      "status",
    );
    return;
  }

  const dwell = parseFloat(document.getElementById("dwell50K").value);
  const pause = parseFloat(document.getElementById("pause50K").value);
  const range = parseInt(
    document.getElementById("sensorRange50K").value,
    10,
  );
  const mode = parseInt(
    document.getElementById("sensorMode50K").value,
    10,
  );
  const curve = parseInt(
    document.getElementById("curve50KSelect").value,
    10,
  );
  const commands = [];

  if (!isNaN(dwell)) {
    if (dwell < 0 || dwell > 10) {
      addLogEntry(
        "Error: 50K dwell time must be between 0.0 and 10.0",
        "received",
      );
      return;
    }
    commands.push(`set_dwell_50k:${dwell}`);
  }

  if (!isNaN(pause)) {
    if (pause < 0 || pause > 10) {
      addLogEntry(
        "Error: 50K pause time must be between 0.0 and 10.0",
        "received",
      );
      return;
    }
    commands.push(`set_pause_50k:${pause}`);
  }

  if (!isNaN(range)) {
    if (range < 1 || range > 8) {
      addLogEntry(
        "Error: 50K Sensor Range must be between 1 and 8",
        "received",
      );
      return;
    }
    commands.push(`set_sensor_range_50k:${range}`);
  }

  if (!isNaN(mode)) {
    if (mode !== 0 && mode !== 1) {
      addLogEntry(
        "Error: 50K Sensor Mode must be 0 (Voltage) or 1 (Current)",
        "received",
      );
      return;
    }
    commands.push(`set_sensor_mode_50k:${mode}`);
  }

  if (!isNaN(curve)) {
    if (curve < 0 || curve > 20) {
      addLogEntry(
        "Error: 50K Curve must be between 0 and 20",
        "received",
      );
      return;
    }
    commands.push(`set_curve_50k:${curve}`);
  }

  if (commands.length === 0) {
    addLogEntry("No 50K sensor parameter changes detected", "status");
    return;
  }

  const progressContainer = document.getElementById(
    "progressContainer50K",
  );
  const progressBar = document.getElementById("progressBar50K");
  const progressText = document.getElementById("progressText50K");

  progressContainer.style.display = "block";
  progressBar.style.width = "0%";
  progressText.textContent = "Processing 50K settings...";

  for (const cmd of commands) {
    try {
      addLogEntry(`Sending 50K command: ${cmd}`, "sent");
      const response = await sendCommandToServer(cmd);
      addLogEntry(`Server response: ${response}`, "received");
    } catch (error) {
      addLogEntry(
        `Error sending 50K command ${cmd}: ${error.message}`,
        "received",
      );
    }

    const progress =
      ((commands.indexOf(cmd) + 1) / commands.length) * 100;
    progressBar.style.width = `${progress}%`;
    progressText.textContent = `Processing 50K settings... ${Math.round(
      progress,
    )}%`;
    await sleep(150);
  }

  setTimeout(() => {
    progressContainer.style.display = "none";
  }, 1000);
}

async function writeSettings4K() {
  if (tcpConnectionStatus === false) {
    addLogEntry(
      "Cannot send 4K command: No connection to TCP server",
      "status",
    );
    return;
  }

  const dwell = parseFloat(document.getElementById("dwell4K").value);
  const pause = parseFloat(document.getElementById("pause4K").value);
  const range = parseInt(
    document.getElementById("sensorRange4K").value,
    10,
  );
  const mode = parseInt(
    document.getElementById("sensorMode4K").value,
    10,
  );
  const curve = parseInt(
    document.getElementById("curve4KSelect").value,
    10,
  );
  const commands = [];

  if (!isNaN(dwell)) {
    if (dwell < 0 || dwell > 10) {
      addLogEntry(
        "Error: 4K dwell time must be between 0.0 and 10.0",
        "received",
      );
      return;
    }
    commands.push(`set_dwell_4k:${dwell}`);
  }

  if (!isNaN(pause)) {
    if (pause < 0 || pause > 10) {
      addLogEntry(
        "Error: 4K pause time must be between 0.0 and 10.0",
        "received",
      );
      return;
    }
    commands.push(`set_pause_4k:${pause}`);
  }

  if (!isNaN(range)) {
    if (range < 1 || range > 8) {
      addLogEntry(
        "Error: 4K Sensor Range must be between 1 and 8",
        "received",
      );
      return;
    }
    commands.push(`set_sensor_range_4k:${range}`);
  }

  if (!isNaN(mode)) {
    if (mode !== 0 && mode !== 1) {
      addLogEntry(
        "Error: 4K Sensor Mode must be 0 (Voltage) or 1 (Current)",
        "received",
      );
      return;
    }
    commands.push(`set_sensor_mode_4k:${mode}`);
  }

  if (!isNaN(curve)) {
    if (curve < 0 || curve > 20) {
      addLogEntry("Error: 4K Curve must be between 0 and 20", "received");
      return;
    }
    commands.push(`set_curve_4k:${curve}`);
  }

  if (commands.length === 0) {
    addLogEntry("No 4K sensor parameter changes detected", "status");
    return;
  }

  const progressContainer = document.getElementById(
    "progressContainer4K",
  );
  const progressBar = document.getElementById("progressBar4K");
  const progressText = document.getElementById("progressText4K");

  progressContainer.style.display = "block";
  progressBar.style.width = "0%";
  progressText.textContent = "Processing 4K settings...";

  for (const cmd of commands) {
    try {
      addLogEntry(`Sending 4K command: ${cmd}`, "sent");
      const response = await sendCommandToServer(cmd);
      addLogEntry(`Server response: ${response}`, "received");
    } catch (error) {
      addLogEntry(
        `Error sending 4K command ${cmd}: ${error.message}`,
        "received",
      );
    }

    const progress =
      ((commands.indexOf(cmd) + 1) / commands.length) * 100;
    progressBar.style.width = `${progress}%`;
    progressText.textContent = `Processing 4K settings... ${Math.round(
      progress,
    )}%`;
    await sleep(150);
  }

  setTimeout(() => {
    progressContainer.style.display = "none";
  }, 1000);
}

function getSelectedExtraChannel() {
  const sel = document.getElementById("relationChannelSelect");
  if (!sel) return null;
  const ch = parseInt(String(sel.value).replace("CH", ""), 10);
  return Number.isFinite(ch) ? ch : null;
}

async function writeSettingsExtraChannel() {
  if (tcpConnectionStatus === false) {
    addLogEntry(
      "Cannot send Extra channel command: No connection to TCP server",
      "status",
    );
    return;
  }

  const ch = getSelectedExtraChannel();
  if (!ch || ch < 9 || ch > 15) {
    addLogEntry("Error: Extra channel must be CH9..CH15", "received");
    return;
  }

  // Read per-channel inputs (sensorRangeCHx / sensorModeCHx)
  const rangeEl = document.getElementById(`sensorRangeCH${ch}`);
  const modeEl = document.getElementById(`sensorModeCH${ch}`);
  const range = rangeEl ? parseInt(rangeEl.value, 10) : NaN;
  const mode = modeEl ? parseInt(modeEl.value, 10) : NaN;

  const commands = [];

  if (!isNaN(range)) {
    if (range < 1 || range > 8) {
      addLogEntry(
        "Error: Sensor Range must be between 1 and 8",
        "received",
      );
      return;
    }
    commands.push(`set_sensor_range_ch${ch}:${range}`);
  }

  if (!isNaN(mode)) {
    if (mode !== 0 && mode !== 1) {
      addLogEntry(
        "Error: Sensor Mode must be 0 (Voltage) or 1 (Current)",
        "received",
      );
      return;
    }
    commands.push(`set_sensor_mode_ch${ch}:${mode}`);
  }

  if (commands.length === 0) {
    addLogEntry("No Extra channel parameter changes detected", "status");
    return;
  }

  // Prefer per-channel small progress bar inside the channel box
  let progressContainer = document.getElementById(`progressContainerCH${ch}`);
  let progressBar = document.getElementById(`progressBarCH${ch}`);
  let progressText = document.getElementById(`progressTextCH${ch}`);

  // Fallback to global EXTRA progress if per-channel not present
  if (!progressContainer) {
    progressContainer = document.getElementById("progressContainerEXTRA");
    progressBar = document.getElementById("progressBarEXTRA");
    progressText = document.getElementById("progressTextEXTRA");
  }

  if (progressContainer) {
    progressContainer.style.display = "block";
  }
  if (progressBar) progressBar.style.width = "0%";
  if (progressText) progressText.textContent = `Processing CH${ch} settings...`;

  for (let i = 0; i < commands.length; i++) {
    const cmd = commands[i];
    try {
      addLogEntry(`Sending CH${ch} command: ${cmd}`, "sent");
      const response = await sendCommandToServer(cmd);
      addLogEntry(`Server response: ${response}`, "received");
    } catch (error) {
      addLogEntry(
        `Error sending CH${ch} command ${cmd}: ${error.message}`,
        "received",
      );
    }

    const progress = ((i + 1) / commands.length) * 100;
    if (progressBar) progressBar.style.width = `${progress}%`;
    if (progressText) progressText.textContent = `Processing CH${ch} settings... ${Math.round(progress)}%`;
    await sleep(150);
  }

  setTimeout(() => {
    if (progressContainer) progressContainer.style.display = "none";
  }, 1000);
}

// Wrapper functions for individual extra channels
async function writeSettingsExtraChannel9() {
  document.getElementById("relationChannelSelect").value = "CH9";
  await writeSettingsExtraChannel();
}

async function writeSettingsExtraChannel10() {
  document.getElementById("relationChannelSelect").value = "CH10";
  await writeSettingsExtraChannel();
}

async function writeSettingsExtraChannel11() {
  document.getElementById("relationChannelSelect").value = "CH11";
  await writeSettingsExtraChannel();
}

async function writeSettingsExtraChannel12() {
  document.getElementById("relationChannelSelect").value = "CH12";
  await writeSettingsExtraChannel();
}

async function writeSettingsExtraChannel13() {
  document.getElementById("relationChannelSelect").value = "CH13";
  await writeSettingsExtraChannel();
}

async function writeSettingsExtraChannel14() {
  document.getElementById("relationChannelSelect").value = "CH14";
  await writeSettingsExtraChannel();
}

async function writeSettingsExtraChannel15() {
  document.getElementById("relationChannelSelect").value = "CH15";
  await writeSettingsExtraChannel();
}

// Switch between tabs script
// This script handles the tab switching functionality
const tabButtons = document.querySelectorAll(".tab-button");
const tabContents = document.querySelectorAll(".tab-content");

tabButtons.forEach((button) => {
  button.addEventListener("click", () => {
    // Remove active class
    tabButtons.forEach((btn) => btn.classList.remove("active"));
    tabContents.forEach((tab) => tab.classList.remove("active"));

    // Add active class to the clicked tab
    button.classList.add("active");
    const target = document.getElementById(button.dataset.target);
    if (target) {
      target.classList.add("active");
      setupCollapsibleSections(target); // <-- re-initialize here
    }
  });
});

function globalToggleChannel(channel) {
  switch (channel) {
    case "MXC":
      toggleChannelMXC();
      break;
    case "50K":
      toggleChannel50K();
      break;
    case "4K":
      toggleChannel4k();
      break;
    case "STILL":
      toggleChannelSTILL();
      break;
  }

  const match = String(channel).match(/^(?:CH)?(9|10|11|12|13|14|15)$/);
  if (match) return toggleSampleChannelGlobal(parseInt(match[1], 10));

  console.warn("Unknown channel in globalToggleChannel:", channel);
}

function toggleSampleChannelGlobal(channel) {
  const checkbox = document.getElementById(
    `toggleExtraChannel${channel}`,
  );
  if (!checkbox) return;

  const state = checkbox.checked ? 1 : 0;
  const command = `set_channel_${channel}: ${state}`;

  // Marcamos como pendiente para que el "fetchSensorData" no sobrescriba el toggle
  pendingExtraChannels[channel] = true;

  addLogEntry(`Sending command: ${command}`, "sent");

  fetch("/send-command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command }),
  })
    .then((r) => r.json())
    .then((data) => {
      addLogEntry(`Server response: ${data.status}`, "received");
    })
    .catch((err) => {
      console.error("❌ Error:", err);
      // Si hay error, revertimos el checkbox y liberamos el pendiente
      checkbox.checked = !checkbox.checked;
      pendingExtraChannels[channel] = false;
    });
}

function toggleStageElements(stageClass, visible) {
  const els = document.getElementsByClassName(stageClass);
  for (const el of els) {
    el.style.display = visible ? "" : "none";
  }
}

function updateStageVisibility() {
  const enabledMXC = !!currentParameters.enabledMXC;
  const enabled50K = !!currentParameters.enabled50K;
  const enabled4K = !!currentParameters.enabled4K;
  const enabledSTILL = !!currentParameters.enabledSTILL;

  toggleStageElements("stage-mxc", enabledMXC);
  toggleStageElements("stage-50k", enabled50K);
  toggleStageElements("stage-4k", enabled4K);
  toggleStageElements("stage-still", enabledSTILL);
}

function initParticles() {
  const canvas = document.getElementById("particles-canvas");
  const ctx = canvas.getContext("2d");
  let particles = [];
  let animationFrameId;

  function resizeCanvas() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    // Re-initialize particles on resize to ensure distribution is correct
    if (particles.length === 0) {
      createParticles();
    }
  }

  function createParticles() {
    particles = [];
    // Asegura un número de partículas razonable (máx. 100)
    const numParticles = Math.min(
      100,
      Math.floor((canvas.width * canvas.height) / 15000),
    );
    for (let i = 0; i < numParticles; i++) {
      particles.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        radius: Math.random() * 2.5 + 1, // Radio entre 0.5 y 2.0
        vx: Math.random() * 0.4 - 0.2, // Velocidad X
        vy: Math.random() * 0.4 - 0.2, // Velocidad Y
      });
    }
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Color de los elementos (negro o gris muy oscuro)
    const particleColor = "rgba(255, 0, 127, 0.8)"; // Gris oscuro
    const lineColor = "rgba(255, 0, 127, 0.15)"; // Líneas muy tenues

    for (let i = 0; i < particles.length; i++) {
      const p1 = particles[i];

      // 1. Dibujar líneas de conexión
      for (let j = i + 1; j < particles.length; j++) {
        const p2 = particles[j];
        const dist = Math.sqrt(
          Math.pow(p1.x - p2.x, 2) + Math.pow(p1.y - p2.y, 2),
        );

        // Conectar si la distancia es menor a 100px
        if (dist < 100) {
          ctx.beginPath();
          ctx.moveTo(p1.x, p1.y);
          ctx.lineTo(p2.x, p2.y);

          // Opacidad basada en la distancia (más cerca, más opaco)
          const opacity = 1 - dist / 100;
          ctx.strokeStyle = lineColor.replace(
            "0.1",
            (opacity * 0.2).toFixed(2),
          );
          ctx.lineWidth = 0.5;
          ctx.stroke();
        }
      }

      // 2. Mover la partícula
      p1.x += p1.vx;
      p1.y += p1.vy;

      // Rebotar en los bordes
      if (p1.x < 0 || p1.x > canvas.width) p1.vx *= -1;
      if (p1.y < 0 || p1.y > canvas.height) p1.vy *= -1;

      // 3. Dibujar la partícula (punto)
      ctx.beginPath();
      ctx.arc(p1.x, p1.y, p1.radius, 0, Math.PI * 2, false);
      ctx.fillStyle = particleColor;
      ctx.fill();
    }

    animationFrameId = requestAnimationFrame(draw);
  }

  // Initialization
  window.addEventListener("resize", resizeCanvas);
  resizeCanvas();

  // Start animation
  if (animationFrameId) cancelAnimationFrame(animationFrameId);
  animationFrameId = requestAnimationFrame(draw);
}

function getResistanceForChannel(channel) {
  switch (channel) {
    case "STILL":
      return currentParameters.RSTILL;
    case "4K":
      return currentParameters.R4K;
    case "50K":
      return currentParameters.R50K;
    case "CH9":
      return currentParameters.RCH9;
    case "CH10":
      return currentParameters.RCH10;
    case "CH11":
      return currentParameters.RCH11;
    case "CH12":
      return currentParameters.RCH12;
    case "CH13":
      return currentParameters.RCH13;
    case "CH14":
      return currentParameters.RCH14;
    case "CH15":
      return currentParameters.RCH15;
    default:
      return null;
  }
}

function createRelationChart() {
  const canvas = document.getElementById("relationChart");
  if (!canvas) return null;

  const ctx = canvas.getContext("2d");
  return new Chart(ctx, {
    type: "line",
    data: {
      datasets: [
        {
          label: "R(STILL) vs T(MXC)",
          data: [],
          showLine: true,
          pointRadius: 0,
          borderWidth: 2,
          tension: 0.0,
        },
      ],
    },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          type: "linear",
          title: { display: true, text: "MXC Temperature (K)" },
        },
        y: {
          title: { display: true, text: "Resistance (Ω)" },
        },
      },
      plugins: {
        legend: { display: true },
        tooltip: {
          callbacks: {
            label: function (ctx) {
              const x = ctx.parsed.x;
              const y = ctx.parsed.y;
              return `T=${x.toFixed(6)} K, R=${y.toFixed(3)} Ω`;
            },
          },
        },
      },
    },
  });
}

function updateRelationCurrentLabels() {
  const mxcSpan = document.getElementById("relationCurrentMXC");
  const rSpan = document.getElementById("relationCurrentR");
  if (!mxcSpan || !rSpan) return;

  const t = currentParameters.MXC;
  const r = getResistanceForChannel(currentRelationChannel);

  if (typeof t === "number" && isFinite(t)) {
    mxcSpan.textContent =
      t < 1.0 ? `${(t * 1000).toFixed(3)} mK` : `${t.toFixed(6)} K`;
  } else {
    mxcSpan.textContent = "-";
  }

  if (typeof r === "number" && isFinite(r)) {
    rSpan.textContent = `${r.toFixed(3)} Ω`;
  } else {
    rSpan.textContent = "-";
  }
}

function pushRelationPointFor(channel) {
  const t = currentParameters.MXC;
  const r = getResistanceForChannel(channel);

  if (!(typeof t === "number" && isFinite(t))) return;
  if (!(typeof r === "number" && isFinite(r))) return;

  relationDataStore[channel].push({ x: t, y: r });

  const HARD_CAP = 20000;
  if (relationDataStore[channel].length > HARD_CAP) {
    relationDataStore[channel].splice(
      0,
      relationDataStore[channel].length - HARD_CAP,
    );
  }
}

function updateRelationStore() {
  pushRelationPointFor("CH9");
  pushRelationPointFor("CH10");
  pushRelationPointFor("CH11");
  pushRelationPointFor("CH12");
  pushRelationPointFor("CH13");
  pushRelationPointFor("CH14");
  pushRelationPointFor("CH15");
}

function redrawRelationChart() {
  if (!relationChart) return;

  const pts = relationDataStore[currentRelationChannel] || [];
  const windowPts = pts
    .slice(-RELATION_LIVE_POINTS)
    .sort((a, b) => a.x - b.x);

  relationChart.data.datasets[0].data = windowPts;
  relationChart.data.datasets[0].label = `R(${currentRelationChannel}) vs T(MXC)`;
  relationChart.update("none");

  updateRelationCurrentLabels();
}

function onRelationChannelChange() {
  const sel = document.getElementById("relationChannelSelect");
  if (!sel) return;

  currentRelationChannel = sel.value; // "CH9".."CH15"

  updateRelationLabelVisibility();
  redrawRelationChart();
  updateRelationCurrentLabels?.(); // por si existe en tu archivo
}

document.addEventListener("DOMContentLoaded", async () => {
  const sel = document.getElementById("relationChannelSelect");
  if (sel) currentRelationChannel = sel.value;

  await initRelationStateFromServer();

  relationChart = createRelationChart();
  redrawRelationChart();
});

// CALL THE FUNCTION WHEN THE PAGE LOADS
document.addEventListener("DOMContentLoaded", initParticles);

function updateScanningChannel(scanningChannel) {
  document.querySelectorAll(".status-indicator-circle").forEach((el) => {
    el.classList.remove("active");
  });

  if (
    scanningChannel === null ||
    scanningChannel === undefined ||
    scanningChannel === 0
  )
    return;

  const ch = parseInt(scanningChannel, 10);
  if (!Number.isFinite(ch)) return;

  // Soporta ambos patrones de ID
  const el = document.getElementById(`statusCircleCH${ch}`);
  if (el) el.classList.add("active");
}