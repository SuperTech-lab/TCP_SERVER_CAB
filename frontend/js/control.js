import { 
    refreshRelationFiles, sendCommandToServer 
} from './api.js';
import {
    sampleRangeCombinationIsValid
} from './business.js';
import { addLogEntry } from './ui.js'; 
import { state } from './state.js';
import { SAMPLE_CHANNELS } from './state.js';

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

    const match = String(channel).match(/^(?:CH)?(9|10|11|12|13|14)$/);
    if (match) return toggleSampleChannelGlobal(parseInt(match[1], 10));

    console.warn("Unknown channel in globalToggleChannel:", channel);
}

function toggleSampleChannelGlobal(channel) {
    const checkbox = document.getElementById(
        `toggleExtraChannel${channel}`,
    );
    if (!checkbox) return;

    const int_state = checkbox.checked ? 1 : 0;
    const command = `set_channel_${channel}: ${int_state}`;

    // Marcamos como pendiente para que el "fetchSensorData" no sobrescriba el toggle
    state.pendingExtraChannels[channel] = true;

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
        state.pendingExtraChannels[channel] = false;
    });
}

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
    let stepRampPayload = null;

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
    } else if (mode === "STEP_RAMP") {
    try {
        stepRampPayload =
        buildRelationStepRampPayload(
            chNum,
            label,
        );
    } catch (error) {
        addLogEntry(
        `❌ STEP_RAMP: ${error.message}`,
        "received",
        );
        return;
    }

    successMarker =
        "RELATION_STEP_RAMP_STARTED:";

    } else {
    startCmd =
        `start_relation:${chNum}:`
        + encodeURIComponent(label);

    successMarker = "RELATION_STARTED:";
    }
    startButton.disabled = true;

    
    try {
    if (mode !== "STEP_RAMP") {
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
    }

    let response;

    if (mode === "STEP_RAMP") {
        addLogEntry(
        "Sending STEP_RAMP start request",
        "sent",
        );

        const httpResponse = await fetch(
        "/start-relation-step-ramp",
        {
            method: "POST",
            headers: {
            "Content-Type": "application/json",
            },
            body: JSON.stringify(
            stepRampPayload,
            ),
        },
        );

        let result;

        try {
        result = await httpResponse.json();
        } catch {
        throw new Error(
            `Invalid HTTP response `
            + `(${httpResponse.status})`,
        );
        }

        response =
        result.status
        ?? result.error
        ?? "";

        addLogEntry(
        `Server response: ${response}`,
        "received",
        );

        if (!httpResponse.ok) {
        throw new Error(
            response
            || `HTTP ${httpResponse.status}`,
        );
        }

    } else {
        addLogEntry(
        `Sending command: ${startCmd}`,
        "sent",
        );

        response = await sendCommandToServer(
        startCmd,
        );

        addLogEntry(
        `Server response: ${response}`,
        "received",
        );
    }
        
    const responseText = (response ?? "")
        .toString()
        .trim();

    if (!responseText.includes(successMarker)) {
        throw new Error(
        responseText
        || "Empty response from TCP server",
        );
    }
    
    if (mode === "STEP_RAMP") {
        const markerIndex =
        responseText.indexOf(successMarker);

        const relationId =
        responseText.slice(
            markerIndex + successMarker.length,
        ).trim();

        if (!relationId) {
        throw new Error(
            "STEP_RAMP relation_id is missing "
            + "from start response.",
        );
        }

        /*
        * A new STEP_RAMP owns a new curve.
        * Do not retain points from the previous relation
        * on the same sample channel.
        */
        relationDataStore[ch].length = 0;

        relationStepRampLiveRelationId =
        relationId;
        relationStepRampLiveNextSeq = 0;
        relationStepRampLiveChannel = ch;

        redrawRelationChart();
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

    const mode = modeSelect.value;

    stopButton.disabled = true;

    try {
    // ============================================================
    // STEP_RAMP
    //
    // Stop is asynchronous. The controller receives the abort
    // request and performs cleanup before finalizing the relation.
    // ============================================================

    if (mode === "STEP_RAMP") {
        addLogEntry(
        "Sending STEP_RAMP stop request",
        "sent",
        );

        const httpResponse = await fetch(
        "/stop-relation",
        {
            method: "POST",
        },
        );

        let result;

        try {
        result = await httpResponse.json();
        } catch {
        throw new Error(
            `Invalid HTTP response `
            + `(${httpResponse.status})`,
        );
        }

        addLogEntry(
        `Server response: ${result.status ?? result.error ?? ""}`,
        "received",
        );

        if (!httpResponse.ok) {
        throw new Error(
            result.error
            || result.status
            || `HTTP ${httpResponse.status}`,
        );
        }

        if (result.status === "STOPPED") {
        /*
        * Rare but valid: relation was finalized
        * synchronously before returning.
        */
        relationRunning = false;

        startButton.disabled = false;
        stopButton.disabled = true;
        channelSelect.disabled = false;
        labelInput.disabled = false;
        modeSelect.disabled = false;

        updateRelationRampControls();

        return;
        }

        if (
        result.status === "STOP_REQUESTED"
        || result.status === "STOPPING"
        ) {
        /*
        * The relation is still active while the worker performs
        * cleanup. Do NOT mark it idle yet.
        *
        * 19E will poll /get-relation-status and release the UI
        * only when the backend reports that the relation is gone.
        */
        relationRunning = true;

        startButton.disabled = true;
        stopButton.disabled = true;
        channelSelect.disabled = true;
        labelInput.disabled = true;
        modeSelect.disabled = true;

        updateRelationRampControls();

        addLogEntry(
            "⏳ STEP_RAMP stop requested; waiting for cleanup.",
            "status",
        );

        return;
        }

        throw new Error(
        `Unexpected STEP_RAMP stop status: `
        + `${result.status ?? "unknown"}`,
        );
    }

    // ============================================================
    // Existing MANUAL / RAMP behaviour
    // ============================================================

    const command = "stop_relation";

    addLogEntry(
        `Sending command: ${command}`,
        "sent",
    );

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
        * Stop was not confirmed.
        * Keep the relation treated as active.
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

if (relationFilesRefreshButton) {
    relationFilesRefreshButton.addEventListener(
        "click",
        refreshRelationFiles,
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

async function toggleChannel50K() {
    const checkbox = document.getElementById("toggle50KGlobal");
    const value = checkbox.checked ? 1 : 0;

    const command = `set_channel_50k:${value}`;

    try {
        state.controls.pending50KToggle = true;
        addLogEntry(`Sending 50K command: ${command}`, "sent");
        const response = await sendCommandToServer(command);
        addLogEntry(`Server response: ${response}`, "received");

        console.log(
        `Channel 50K is now ${checkbox.checked ? "enabled" : "disabled"}`,
        );
        console.log(response);
    } catch (error) {
        checkbox.checked = !checkbox.checked;
        state.controls.pending50KToggle = false;
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
    state.controls.pendingMXCToggle = true;

    addLogEntry(`Sending MXC command: ${command}`, "sent");
    const response = await sendCommandToServer(command);
    addLogEntry(`Server response: ${response}`, "received");

    console.log(
    `Channel MXC is now ${checkbox.checked ? "enabled" : "disabled"}`,
    );
    console.log(response);
} catch (error) {
    checkbox.checked = !checkbox.checked;
    state.controls.pendingMXCToggle = false;
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
    state.controls.pendingSTILLToggle = true;

    addLogEntry(`Sending STILL command: ${command}`, "sent");
    const response = await sendCommandToServer(command);
    addLogEntry(`Server response: ${response}`, "received");

    console.log(
    `Channel STILL is now ${checkbox.checked ? "enabled" : "disabled"}`,
    );
    console.log(response);
} catch (error) {
    checkbox.checked = !checkbox.checked;
    state.controls.pendingSTILLToggle = false;
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
    state.controls.pending4KToggle = true;

    addLogEntry(`Sending 4K command: ${command}`, "sent");
    const response = await sendCommandToServer(command);
    addLogEntry(`Server response: ${response}`, "received");

    console.log(
    `Channel 4K is now ${checkbox.checked ? "enabled" : "disabled"}`,
    );
    console.log(response);
} catch (error) {
    checkbox.checked = !checkbox.checked;
    state.controls.pending4KToggle = false;
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
    if (state.connection.tcpStatus === false) {
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
if (state.connection.tcpStatus === false) {
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
if (state.connection.tcpStatus === false) {
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
if (state.connection.tcpStatus === false) {
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
if (state.connection.tcpStatus === false) {
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

    if (state.connection.tcpStatus === false) {
        addLogEntry(
        "Cannot send Autoscan command: No connection to TCP server",
        "status",
        );
        cb.checked = !desiredState;
        return;
}

const valueStr = desiredState ? "on" : "off";
const command = `set_autoscan:${valueStr}`;

state.controls.pendingAutoscanToggle = true;

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
    state.controls.pendingAutoscanToggle = false;
    console.error(error);
}
}

async function writeSensorSettingsMXC() {
    console.log("Writing sensor settings for MXC...");

    //Check if we have a valid TCP connection
    if (state.connection.tcpStatus === false) {
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
if (state.connection.tcpStatus === false) {
    addLogEntry(
    "Cannot send MXC command: No connection to TCP server",
    "status",
    );
    return;
}

async function writeExcitationMXC() {
    console.log("Writing excitation level for MXC...");

    if (state.connection.tcpStatus === false) {
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
    if (values.MXCSP < 0 || values.MXCSP > 1000) {
    addLogEntry(
        "Error: MXC Setpoint must be between 0.0 and 1.0 K",
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
if (state.connection.tcpStatus === false) {
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
if (state.connection.tcpStatus === false) {
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
    if (state.connection.tcpStatus === false) {
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

async function writeSettingsExtraChannel(requestedChannel = null) {
    if (state.connection.tcpStatus === false) {
        addLogEntry(
        "Cannot send sample-channel command: No connection to TCP server",
        "status",
        );
        return;
    }

    const ch = requestedChannel ?? getSelectedExtraChannel();
    if (!SAMPLE_CHANNELS.includes(ch)) {
        addLogEntry("Error: sample channel must be CH9..CH14", "received");
        return;
    }

    const mode = Number(
        document.getElementById(`sensorModeCH${ch}`)?.value,
    );
    const excitationRange = Number(
        document.getElementById(`sensorRangeCH${ch}`)?.value,
    );
    const resistanceRange = Number(
        document.getElementById(`resistanceRangeCH${ch}`)?.value,
    );
    const autorange = Number(
        document.getElementById(`autorangeCH${ch}`)?.value,
    );

    if (
        ![mode, excitationRange, resistanceRange, autorange]
        .every(Number.isInteger)
    ) {
        addLogEntry(
        `Error: incomplete resistance settings for CH${ch}`,
        "received",
        );
        return;
    }

    if (mode !== 0 && mode !== 1) {
        addLogEntry("Error: mode must be Voltage or Current", "received");
        return;
    }

    if (resistanceRange < 1 || resistanceRange > 22) {
        addLogEntry(
        "Error: resistance range must be between 1 and 22",
        "received",
        );
        return;
    }

    if (autorange !== 0 && autorange !== 1) {
        addLogEntry(
        "Error: range control must be Manual or Autorange",
        "received",
        );
        return;
    }

    if (
        !sampleRangeCombinationIsValid(
        mode,
        excitationRange,
        resistanceRange,
        )
    ) {
        addLogEntry(
        `Error: incompatible excitation and resistance ranges for CH${ch}`,
        "received",
        );
        return;
    }

    const command =
        `set_sample_resistance_settings:${ch}:${mode}`
        + `:${excitationRange}:${resistanceRange}:${autorange}`;

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
    if (progressText) {
        progressText.textContent = `Applying CH${ch} settings atomically...`;
    }

    try {
        addLogEntry(`Sending CH${ch} command: ${command}`, "sent");
        const response = await sendCommandToServer(command);
        addLogEntry(`Server response: ${response}`, "received");

        if (String(response).includes("❌")) {
        throw new Error(response);
        }

        if (progressBar) progressBar.style.width = "100%";
        if (progressText) progressText.textContent = `CH${ch} settings applied`;

        const details = document
        .getElementById(`sensorModeCH${ch}`)
        ?.closest("details");
        if (details) details.dataset.settingsDirty = "false";

        await sleep(350);
        await fetchSensorData(true);

    } catch (error) {
        if (progressText) progressText.textContent = `CH${ch} settings failed`;
        addLogEntry(
        `Error applying CH${ch} settings: ${error.message}`,
        "received",
        );

    } finally {
        setTimeout(() => {
        if (progressContainer) progressContainer.style.display = "none";
        }, 1000);
    }
}

// Wrapper functions retained for the existing per-channel buttons.
async function writeSettingsExtraChannel9() {
    await writeSettingsExtraChannel(9);
}

async function writeSettingsExtraChannel10() {
    await writeSettingsExtraChannel(10);
}

async function writeSettingsExtraChannel11() {
    await writeSettingsExtraChannel(11);
}

async function writeSettingsExtraChannel12() {
    await writeSettingsExtraChannel(12);
}

async function writeSettingsExtraChannel13() {
    await writeSettingsExtraChannel(13);
}

async function writeSettingsExtraChannel14() {
    await writeSettingsExtraChannel(14);
}

// Make functions available for external calls in index.html
document
    .getElementById("toggleMXCGlobal")
    .addEventListener("change", () => {
        globalToggleChannel("MXC");
    });
document
    .getElementById("toggle50KGlobal")
    .addEventListener("change", () => {
        globalToggleChannel("50K");
    });
document
    .getElementById("toggle4KGlobal")
    .addEventListener("change", () => {
        globalToggleChannel("4K");
    });
document
    .getElementById("toggleSTILLGlobal")
    .addEventListener("change", () => {
        globalToggleChannel("STILL");
    });
document
    .getElementById("autorangeMXC")
    .addEventListener("change", () => {
        toggleAutorangeMXC();
    });
document
    .getElementById("toggleExtraChannel9")
    .addEventListener("change", () => {
        globalToggleChannel("9");
    });

document
    .getElementById("toggleExtraChannel10")
    .addEventListener("change", () => {
        globalToggleChannel("10");
    });

document
    .getElementById("toggleExtraChannel11")
    .addEventListener("change", () => {
        globalToggleChannel("11");
    });

document
    .getElementById("toggleExtraChannel12")
    .addEventListener("change", () => {
        globalToggleChannel("12");
    });

document
    .getElementById("toggleExtraChannel13")
    .addEventListener("change", () => {
        globalToggleChannel("13");
    });

document
    .getElementById("toggleExtraChannel14")
    .addEventListener("change", () => {
        globalToggleChannel("14");
    });

document
    .getElementById("writeSettingsButtonCH9")
    .addEventListener("click", () => {
        writeSettingsExtraChannel9();
    });

document
    .getElementById("autoscanToggle")
    .addEventListener("change", () => {
        toggleAutoscan();
    });