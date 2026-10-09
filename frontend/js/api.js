import { state } from './state.js';
import { 
    chartDataStore, parameterBoxUpdateInterval, SAMPLE_CHANNELS
} from './state.js';
import { addLogEntry, updateRunUI,
    updateTimeRangeOptions50K, updateTimeRangeOptions4K, updateTimeRangeOptionsSTILL, 
    updateTimeRangeOptions, updateScanningChannel, syncSampleChannelControls,
    update50KValues, update4KValues, updateSTILLValues, updateMXCValues,
    updateMXCHeaterOutput, updateStageVisibility, updateParameterControls
 } from './ui.js';
import { normalizeEnabled, updateRelationStore } from './business.js';
import { redrawFromStore, redrawRelationChart, updateTemperatureChart } from './charts.js';

export async function fetchRelationStepRampLivePoints(
    forceFullReload = false,
    ) {
    const modeSelect = document.getElementById(
        "relationModeSelect",
    );

    if (
        !state.relation.running
        || !modeSelect
        || modeSelect.value !== "STEP_RAMP"
    ) {
        return;
    }

    /*
    * Avoid overlapping HTTP requests if one poll takes
    * longer than the polling interval.
    */
    if (relationStepRampLiveFetchInProgress) {
        return;
    }

    relationStepRampLiveFetchInProgress = true;

    try {
        async function requestFrom(fromSeq) {
        const response = await fetch(
            "/get-relation-live-points"
            + `?from_seq=${encodeURIComponent(fromSeq)}`,
            {
            cache: "no-store",
            },
        );

        let payload;

        try {
            payload = await response.json();
        } catch {
            throw new Error(
            `Invalid live-points response `
            + `(HTTP ${response.status})`,
            );
        }

        if (!response.ok || !payload.ok) {
            throw new Error(
            payload.error
            || `HTTP ${response.status}`,
            );
        }

        return payload;
        }

        let requestedFromSeq =
        forceFullReload
            ? 0
            : relationStepRampLiveNextSeq;

        let payload = await requestFrom(
        requestedFromSeq,
        );

        /*
        * Status polling is responsible for changing the UI
        * to idle. Nothing should be appended when no relation
        * is active.
        */
        if (
        payload.relation_id === null
        || payload.relation_id === undefined
        ) {
        return;
        }

        if (payload.mode !== "STEP_RAMP") {
        throw new Error(
            `Unexpected live-points mode: `
            + `${payload.mode ?? "null"}`,
        );
        }

        let channelNumber = Number(
        payload.channel,
        );

        if (
        !Number.isInteger(channelNumber)
        || !SAMPLE_CHANNELS.includes(
            channelNumber,
        )
        ) {
        throw new Error(
            "Invalid STEP_RAMP live-points channel.",
        );
        }

        let channelName =
        `CH${channelNumber}`;

        let relationId =
        payload.relation_id === null
        || payload.relation_id === undefined
            ? null
            : String(payload.relation_id);

        if (!relationId) {
        throw new Error(
            "STEP_RAMP live-points relation_id is missing.",
        );
        }

        /*
        * If the browser still carries the sequence number of
        * a previous STEP_RAMP, and the new relation already
        * contains enough points that reset_required was not
        * triggered by the backend, relation_id still lets us
        * detect the change.
        *
        * In that case request the whole new relation again
        * from sequence zero.
        */
        const relationChanged =
        relationStepRampLiveRelationId !== null
        && relationStepRampLiveRelationId
            !== relationId;

        const channelChanged =
        relationStepRampLiveChannel !== null
        && relationStepRampLiveChannel
            !== channelName;

        if (
        (relationChanged || channelChanged)
        && requestedFromSeq !== 0
        ) {
        requestedFromSeq = 0;

        payload = await requestFrom(0);

        if (
            payload.relation_id === null
            || payload.relation_id === undefined
            || payload.mode !== "STEP_RAMP"
        ) {
            return;
        }

        channelNumber = Number(
            payload.channel,
        );

        if (
            !Number.isInteger(channelNumber)
            || !SAMPLE_CHANNELS.includes(
            channelNumber,
            )
        ) {
            throw new Error(
            "Invalid STEP_RAMP live-points channel.",
            );
        }

        channelName =
            `CH${channelNumber}`;

        relationId =
            payload.relation_id === null
            || payload.relation_id === undefined
            ? null
            : String(payload.relation_id);

        if (!relationId) {
            throw new Error(
            "STEP_RAMP live-points relation_id is missing.",
            );
        }
        }

        const mustResetLocalStore =
        forceFullReload
        || payload.reset_required === true
        || relationStepRampLiveRelationId
            !== relationId
        || relationStepRampLiveChannel
            !== channelName;

        if (mustResetLocalStore) {
        relationDataStore[channelName].length = 0;

        relationStepRampLiveNextSeq = 0;
        relationStepRampLiveRelationId =
            relationId;
        relationStepRampLiveChannel =
            channelName;
        }

        if (!Array.isArray(payload.points)) {
        throw new Error(
            "Invalid STEP_RAMP live-points array.",
        );
        }

        /*
        * Append strictly in sequence/acquisition order.
        * No temperature sorting is done here.
        */
        for (const point of payload.points) {
        const seq = Number(point.seq);
        const x = Number(point.x);
        const y = Number(point.y);

        if (
            !Number.isInteger(seq)
            || seq < 0
            || !Number.isFinite(x)
            || !Number.isFinite(y)
        ) {
            throw new Error(
            "Invalid STEP_RAMP live point.",
            );
        }

        /*
        * A repeated request cannot duplicate points.
        */
        if (
            seq < relationStepRampLiveNextSeq
        ) {
            continue;
        }

        /*
        * A sequence gap should never occur. Do not silently
        * draw an incomplete relation.
        */
        if (
            seq !== relationStepRampLiveNextSeq
        ) {
            throw new Error(
            `STEP_RAMP sequence gap: expected `
            + `${relationStepRampLiveNextSeq}, `
            + `received ${seq}.`,
            );
        }

        relationDataStore[channelName].push({
            x: x,
            y: y,
            seq: seq,
            ts_utc_iso:
            point.ts_utc_iso ?? null,
        });

        relationStepRampLiveNextSeq =
            seq + 1;
        }

        const backendNextSeq = Number(
        payload.next_seq,
        );

        if (
        !Number.isInteger(backendNextSeq)
        || backendNextSeq < 0
        ) {
        throw new Error(
            "Invalid STEP_RAMP next_seq.",
        );
        }

        if (
        relationStepRampLiveNextSeq
        !== backendNextSeq
        ) {
        throw new Error(
            `STEP_RAMP sequence mismatch: local `
            + `${relationStepRampLiveNextSeq}, `
            + `backend ${backendNextSeq}.`,
        );
        }

        /*
        * Same memory protection already used by the existing
        * relation store.
        */
        const HARD_CAP = 20000;

        if (
        relationDataStore[channelName].length
        > HARD_CAP
        ) {
        relationDataStore[channelName].splice(
            0,
            relationDataStore[channelName].length
            - HARD_CAP,
        );
        }

        if (
        currentRelationChannel
        === channelName
        ) {
        redrawRelationChart();
        }

    } catch (error) {
        /*
        * Do not fill the visible log every second if the
        * endpoint temporarily fails.
        */
        console.error(
        "STEP_RAMP live-points error:",
        error,
        );
    } finally {
        relationStepRampLiveFetchInProgress =
        false;
    }
}

async function reconcileRelationStepRampFromFile() {
    const relationId =
        relationStepRampLiveRelationId;

    const channelName =
        relationStepRampLiveChannel;

    if (
        !relationId
        || !channelName
    ) {
        return false;
    }

    if (
        !Object.prototype.hasOwnProperty.call(
        relationDataStore,
        channelName,
        )
    ) {
        console.error(
        "STEP_RAMP reconciliation: "
        + `invalid local channel ${channelName}`,
        );

        return false;
    }

    /*
    * _finalize_relation() sets RELATION_ACTIVE=False
    * before the PostgreSQL write is completed.
    *
    * Therefore /get-relation-status may report IDLE
    * slightly before the final .dat is available.
    */
    const MAX_ATTEMPTS = 6;
    const RETRY_DELAY_MS = 250;

    for (
        let attempt = 1;
        attempt <= MAX_ATTEMPTS;
        attempt++
    ) {
        try {
        const response = await fetch(
            "/get-relation-file"
            + `?file_name=${encodeURIComponent(relationId)}`,
            {
            cache: "no-store",
            },
        );

        let payload;

        try {
            payload = await response.json();
        } catch {
            throw new Error(
            `Invalid relation-file response `
            + `(HTTP ${response.status})`,
            );
        }

        if (!response.ok || !payload.ok) {
            throw new Error(
            payload.error
            || `HTTP ${response.status}`,
            );
        }

        if (
            String(payload.file_name)
            !== relationId
        ) {
            throw new Error(
            "Returned relation file does not match "
            + "the active STEP_RAMP relation_id.",
            );
        }

        const channelNumber = Number(
            payload.channel_number,
        );

        const expectedChannel =
            Number(
            channelName.replace("CH", ""),
            );

        if (
            !Number.isInteger(channelNumber)
            || channelNumber !== expectedChannel
        ) {
            throw new Error(
            "Returned relation file has "
            + "an unexpected channel.",
            );
        }

        if (!Array.isArray(payload.points)) {
            throw new Error(
            "Invalid relation-file points array.",
            );
        }

        const finalPoints = [];

        for (
            let i = 0;
            i < payload.points.length;
            i++
        ) {
            const point = payload.points[i];

            const x = Number(point.x);
            const y = Number(point.y);

            if (
            !Number.isFinite(x)
            || !Number.isFinite(y)
            ) {
            throw new Error(
                `Invalid point ${i} in final relation file.`,
            );
            }

            /*
            * get_relation_file currently exposes x/y only.
            * Recreate seq locally from persisted acquisition order.
            */
            finalPoints.push({
            x: x,
            y: y,
            seq: i,
            });
        }

        const declaredPoints = Number(
            payload.n_points,
        );

        if (
            Number.isInteger(declaredPoints)
            && declaredPoints >= 0
            && declaredPoints
            !== finalPoints.length
        ) {
            throw new Error(
            `Final relation point-count mismatch: `
            + `metadata=${declaredPoints}, `
            + `parsed=${finalPoints.length}.`,
            );
        }

        /*
        * Replace, do not append.
        *
        * The persisted .dat is now the definitive
        * representation of the completed STEP_RAMP.
        */
        relationDataStore[channelName] =
            finalPoints;

        relationStepRampLiveNextSeq =
            finalPoints.length;

        if (
            currentRelationChannel
            === channelName
        ) {
            redrawRelationChart();
        }

        console.log(
            `✅ STEP_RAMP reconciled from ${relationId}: `
            + `${finalPoints.length} points`,
        );

        return true;

        } catch (error) {
        if (attempt === MAX_ATTEMPTS) {
            console.error(
            "STEP_RAMP final reconciliation failed:",
            error,
            );

            return false;
        }

        await new Promise(
            (resolve) => setTimeout(
            resolve,
            RETRY_DELAY_MS,
            ),
        );
        }
    }

    return false;
}

export async function refreshRecentRuns() {
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

export async function initRunIdFromServer() {
    if (state.run.hasInitialized) return;
    state.run.hasInitialized = true;

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
        state.run.activeId = activeRun;

        runIdInput.value = activeRun;
        state.run.expectedNextId = activeRun;
        addLogEntry(`Active run detected: ${activeRun}`, "status");
        updateRunUI();
        return;
        }

        // Caso 2: no hay abierto
        m = /LAST_RUN:(\d+)/.exec(response);
        if (m) {
        const lastRun = parseInt(m[1], 10);
        const nextRun = lastRun + 1;

        state.run.activeId = null;
        runIdInput.value = nextRun;
        state.run.expectedNextId = nextRun;

        addLogEntry(`Next run id set to ${nextRun}`, "status");
        updateRunUI();
        return;
        }

        addLogEntry(
        `Could not parse run id from: "${response}". Using 1.`,
        "status",
        );
        runIdInput.value = 1;
        state.run.expectedNextId = 1;
    } catch (error) {
        addLogEntry(
        `Error requesting run id: ${error.message}. Using 1.`,
        "received",
        );
        runIdInput.value = 1;
        state.run.expectedNextId = 1;
    }
}

export async function refreshRelationFiles() {
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
export async function updateConnectionStatus() {
    const newStatus = await checkConnectionStatus();

    if (state.connection.tcpStatus === null) {
        // Initial status check
        state.connection.tcpStatus = newStatus;
        if (state.connection.tcpStatus) {
        addLogEntry("HTTP server is connected to TCP server", "status");
        } else {
        addLogEntry("HTTP server is NOT connected to TCP server", "status");
        }
    } else if (newStatus !== state.connection.tcpStatus) {
        // Status changed
        state.connection.tcpStatus = newStatus;
        if (state.connection.tcpStatus) {
        addLogEntry("Reconnected to TCP server", "status");
        } else {
        addLogEntry("Lost connection to TCP server", "status");
        }
    }

    return state.connection.tcpStatus;
}

export async function loadTemperatureBuffer() {
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

// Helper function to send a command to the server
export async function sendCommandToServer(command) {
    const response = await fetch("/send-command", {
        method: "POST",
        headers: {
        "Content-Type": "application/json",
        },
        body: JSON.stringify({ command }),
    });

    const result = await response.json();

    // Check if we thought we were disconnected but got a response
    if (state.connection.tcpStatus === false) {
        state.connection.tcpStatus = true;
        addLogEntry("Reconnected to TCP server", "status");
    }

    return result.status;
}

// Function to send only changed parameters to the server
export async function sendControlParameters() {
    if (state.connection.tcpStatus === false) {
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
        state.lastSentValues.temperatureSetpoint
    ) {
        commandsToSend.push({
        type: "temperatureSetpoint",
        command: `set_temperature_setpoint:${currentValues.temperatureSetpoint}`,
        });
    }

    // Check heater power
    if (
        !isNaN(currentValues.heaterPower) &&
        currentValues.heaterPower !== state.lastSentValues.heaterPower
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
    if (currentValues.heaterRange !== state.lastSentValues.heaterRange) {
        commandsToSend.push({
        type: "heaterRange",
        command: `set_heater_range:${currentValues.heaterRange}`,
        });
    }

    // Check temperature limit
    if (
        !isNaN(currentValues.temperatureLimit) &&
        currentValues.temperatureLimit !== state.lastSentValues.temperatureLimit
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
        currentValues.timeout !== state.lastSentValues.timeout
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
        currentValues.proportionalGain !== state.lastSentValues.proportionalGain
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
        currentValues.integralGain !== state.lastSentValues.integralGain
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
        currentValues.derivativeGain !== state.lastSentValues.derivativeGain
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
        state.lastSentValues[cmd.type] = currentValues[cmd.type];
        } catch (error) {
        addLogEntry(
            `Error sending ${cmd.type}: ${error.message}`,
            "received",
        );
        }
    }
}

// Function that handles fetching sensor data from the server
// and updates the UI accordingly
export async function fetchSensorData(forceUpdateControls = false) {
    try {
        // Fetch data from the server using the /get-data channel
        const response = await fetch("/get-data");
        if (!response.ok) {
        if (state.connection.tcpStatus !== false) {
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
        state.currentParameters["50K"] = parseFloat(data["50K"]);
        }
        if (data["4K"] !== undefined) {
        state.currentParameters["4K"] = parseFloat(data["4K"]);
        }
        if (data.STILL !== undefined) {
        state.currentParameters.STILL = parseFloat(data.STILL);
        }
        if (data.MXC !== undefined) {
        state.currentParameters.MXC = parseFloat(data.MXC);
        }
        if (data.RMXC !== undefined) {
        state.currentParameters.RMXC = parseFloat(data.RMXC);
        }
        if (data.PMXC !== undefined) {
        state.currentParameters.PMXC = parseFloat(data.PMXC);
        }
        if (data.enabledMXC !== undefined) {
        state.currentParameters.enabledMXC = parseInt(data.enabledMXC);
        }
        if (data.enabled50K !== undefined) {
        state.currentParameters.enabled50K = parseInt(data.enabled50K);
        }
        if (data.enabled4K !== undefined) {
        state.currentParameters.enabled4K = parseInt(data.enabled4K);
        }
        if (data.enabledSTILL !== undefined) {
        state.currentParameters.enabledSTILL = parseInt(data.enabledSTILL);
        }
        if (data.setpoint !== undefined) {
        state.currentParameters.temperatureSetpoint = parseFloat(data.setpoint);
        }
        if (data.heater_power !== undefined) {
        state.currentParameters.heaterPower = parseFloat(data.heater_power);
        }
        if (data.heater_range !== undefined) {
        state.currentParameters.heaterRange = data.heater_range;
        }
        if (data.temperature_limit !== undefined) {
        state.currentParameters.temperatureLimit = parseFloat(
            data.temperature_limit,
        );
        }
        if (data.timeout !== undefined) {
        state.currentParameters.timeout = parseFloat(data.timeout);
        }
        if (data.proportional_gain !== undefined) {
        state.currentParameters.proportionalGain = parseFloat(
            data.proportional_gain,
        );
        }
        if (data.integral_gain !== undefined) {
        state.currentParameters.integralGain = parseFloat(data.integral_gain);
        }
        if (data.derivative_gain !== undefined) {
        state.currentParameters.derivativeGain = parseFloat(data.derivative_gain);
        }
        if (data.MXCSP !== undefined) {
        state.currentParameters.MXCSP = parseFloat(data.MXCSP);
        }
        if (data.MXCP !== undefined) {
        state.currentParameters.MXCP = parseFloat(data.MXCP);
        }
        if (data.MXCI !== undefined) {
        state.currentParameters.MXCI = parseFloat(data.MXCI);
        }
        if (data.MXCD !== undefined) {
        state.currentParameters.MXCD = parseFloat(data.MXCD);
        }
        if (data.MXCHR !== undefined) {
        state.currentParameters.MXCHR = parseFloat(data.MXCHR);
        }
        if (data.dwellMXC !== undefined) {
        state.currentParameters.dwellMXC = parseFloat(data.dwellMXC);
        }
        if (data.pauseMXC !== undefined) {
        state.currentParameters.pauseMXC = parseFloat(data.pauseMXC);
        }
        if (data.modeMXC !== undefined) {
        state.currentParameters.modeMXC = parseInt(data.modeMXC);
        }
        if (data.rangeMXC !== undefined) {
        state.currentParameters.rangeMXC = parseInt(data.rangeMXC);
        }
        if (data.autorangeMXC !== undefined) {
        state.currentParameters.autorangeMXC = parseInt(data.autorangeMXC);
        }
        if (data.dwell50K !== undefined) {
        state.currentParameters.dwell50K = parseFloat(data.dwell50K);
        }
        if (data.pause50K !== undefined) {
        state.currentParameters.pause50K = parseFloat(data.pause50K);
        }

        if (data.dwell4K !== undefined) {
        state.currentParameters.dwell4K = parseFloat(data.dwell4K);
        }
        if (data.pause4K !== undefined) {
        state.currentParameters.pause4K = parseFloat(data.pause4K);
        }

        if (data.dwellSTILL !== undefined) {
        state.currentParameters.dwellSTILL = parseFloat(data.dwellSTILL);
        }
        if (data.pauseSTILL !== undefined) {
        state.currentParameters.pauseSTILL = parseFloat(data.pauseSTILL);
        }
        if (data.mode50K !== undefined) {
        state.currentParameters.mode50K = parseInt(data.mode50K);
        }
        if (data.range50K !== undefined) {
        state.currentParameters.range50K = parseInt(data.range50K);
        }

        if (data.mode4K !== undefined) {
        state.currentParameters.mode4K = parseInt(data.mode4K);
        }
        if (data.range4K !== undefined) {
        state.currentParameters.range4K = parseInt(data.range4K);
        }

        if (data.modeSTILL !== undefined) {
        state.currentParameters.modeSTILL = parseInt(data.modeSTILL);
        }
        if (data.rangeSTILL !== undefined) {
        state.currentParameters.rangeSTILL = parseInt(data.rangeSTILL);
        }
        if (data.autoscan !== undefined) {
        state.currentParameters.autoscan = data.autoscan;
        }
        if (data.curveMXC !== undefined) {
        state.currentParameters.curveMXC = parseInt(data.curveMXC);
        }
        if (data.curve50K !== undefined) {
        state.currentParameters.curve50K = parseInt(data.curve50K);
        }
        if (data.curve4K !== undefined) {
        state.currentParameters.curve4K = parseInt(data.curve4K);
        }
        if (data.curveSTILL !== undefined) {
        state.currentParameters.curveSTILL = parseInt(data.curveSTILL);
        }
        if (data.R50K !== undefined) {
        state.currentParameters.R50K = parseFloat(data.R50K);
        }
        if (data.P50K !== undefined) {
        state.currentParameters.P50K = parseFloat(data.P50K);
        }
        if (data.R4K !== undefined) {
        state.currentParameters.R4K = parseFloat(data.R4K);
        }
        if (data.P4K !== undefined) {
        state.currentParameters.P4K = parseFloat(data.P4K);
        }
        if (data.RSTILL !== undefined) {
        state.currentParameters.RSTILL = parseFloat(data.RSTILL);
        }
        if (data.PSTILL !== undefined) {
        state.currentParameters.PSTILL = parseFloat(data.PSTILL);
        }
        if (data.heaterOutputMXC !== undefined) {
        state.currentParameters.heaterOutputMXC = parseFloat(
            data.heaterOutputMXC,
        );
        }
        if (data.RCH9 !== undefined)
        state.currentParameters.RCH9 = parseFloat(data.RCH9);
        if (data.RCH10 !== undefined)
        state.currentParameters.RCH10 = parseFloat(data.RCH10);
        if (data.RCH11 !== undefined)
        state.currentParameters.RCH11 = parseFloat(data.RCH11);
        if (data.RCH12 !== undefined)
        state.currentParameters.RCH12 = parseFloat(data.RCH12);
        if (data.RCH13 !== undefined)
        state.currentParameters.RCH13 = parseFloat(data.RCH13);
        if (data.RCH14 !== undefined)
        state.currentParameters.RCH14 = parseFloat(data.RCH14);
        SAMPLE_CHANNELS.forEach((channel) => {
        if (data[`enabledCH${channel}`] !== undefined) {
            state.currentParameters[`enabledCH${channel}`] = normalizeEnabled(
            data[`enabledCH${channel}`],
            )
            ? 1
            : 0;
        }
        });
        if (data.scanning_channel !== undefined) {
        state.currentParameters.scanning_channel = parseInt(
            data.scanning_channel,
        );
        updateScanningChannel(data.scanning_channel);
        }

        SAMPLE_CHANNELS.forEach((channel) => {
        if (data[`modeCH${channel}`] !== undefined) {
            state.currentParameters[`modeCH${channel}`] =
            data[`modeCH${channel}`] === null
                ? null
                : parseInt(data[`modeCH${channel}`]);
        }

        const excitationRangeKey = `excitationRangeCH${channel}`;
        const legacyRangeKey = `rangeCH${channel}`;
        const excitationRangeValue =
            data[excitationRangeKey] ?? data[legacyRangeKey];

        if (excitationRangeValue !== undefined) {
            state.currentParameters[excitationRangeKey] =
            excitationRangeValue === null
                ? null
                : parseInt(excitationRangeValue);

            // Keep the old key populated for older code paths.
            state.currentParameters[legacyRangeKey] =
            state.currentParameters[excitationRangeKey];
        }

        ["resistanceRange", "autorange", "excitationOn"].forEach(
            (prefix) => {
            const key = `${prefix}CH${channel}`;

            if (data[key] !== undefined) {
                state.currentParameters[key] =
                data[key] === null ? null : parseInt(data[key]);
            }
            },
        );
        });

        SAMPLE_CHANNELS.forEach(syncSampleChannelControls);

        // Update UI controls if parameters changed every minute
        // (or the time specified in parameterBoxUpdateInterval variable)
        const now = Date.now();
        if (
        forceUpdateControls ||
        now - state.controls.lastParameterBoxUpdateTime > parameterBoxUpdateInterval
        ) {
        console.log("🔄 Updating parameter controls with new values");
        state.controls.lastParameterBoxUpdateTime = now;
        updateParameterControls();
        }

        // Update last sent values to prevent unnecessary updates
        state.lastSentValues = {
        temperatureSetpoint: state.currentParameters.temperatureSetpoint,
        heaterPower: state.currentParameters.heaterPower,
        heaterRange: state.currentParameters.heaterRange,
        temperatureLimit: state.currentParameters.temperatureLimit,
        timeout: state.currentParameters.timeout,
        proportionalGain: state.currentParameters.proportionalGain,
        integralGain: state.currentParameters.integralGain,
        derivativeGain: state.currentParameters.derivativeGain,
        temperatureSetpointMXC: state.currentParameters.MXCSP,
        dwellMXC: state.currentParameters.dwellMXC,
        pauseMXC: state.currentParameters.pauseMXC,
        modeMXC: state.currentParameters.modeMXC,
        rangeMXC: state.currentParameters.rangeMXC,
        autorangeMXC: state.currentParameters.autorangeMXC,
        };

        // Update the 50k chart with the new temperature
        if (state.currentParameters["50K"] !== null) {
        updateTemperatureChart(
            "50K",
            state.currentParameters["50K"],
            null,
            sampleTimestamp,
        );
        update50KValues(
            state.currentParameters["50K"],
            state.currentParameters.R50K,
            state.currentParameters.P50K,
        );
        }

        //Update the 4k chart with the new temperature
        if (state.currentParameters["4K"] !== null) {
        updateTemperatureChart(
            "4K",
            state.currentParameters["4K"],
            null,
            sampleTimestamp,
        );
        update4KValues(
            state.currentParameters["4K"],
            state.currentParameters.R4K,
            state.currentParameters.P4K,
        );
        }
        // Update the STILL chart with the new temperature
        if (state.currentParameters.STILL !== null) {
        console.log(
            "📈 Updating STILL chart with:",
            state.currentParameters.STILL,
        );

        updateTemperatureChart(
            "STILL",
            state.currentParameters.STILL,
            null,
            sampleTimestamp,
        );
        updateSTILLValues(
            state.currentParameters.STILL,
            state.currentParameters.RSTILL,
            state.currentParameters.PSTILL,
        );
        }

        // Update the MXC chart with the new temperature
        if (state.currentParameters.MXC !== null) {
        console.log(
            "📈 Updating MXC chart with:",
            state.currentParameters.MXC,
            state.currentParameters.temperatureSetpoint,
        );

        updateTemperatureChart(
            "MXC",
            state.currentParameters.MXC,
            state.currentParameters.temperatureSetpoint,
            sampleTimestamp,
        );

        updateMXCValues(
            state.currentParameters.MXC, // Temperature in mK
            state.currentParameters.RMXC, // Resistance in Ohms
            state.currentParameters.PMXC,
        ); // Power in Watts

        updateMXCHeaterOutput(state.currentParameters.heaterOutputMXC);
        }

        // MXC
        const gMXC = document.getElementById("toggleMXCGlobal");
        const enabledMXC = !!state.currentParameters.enabledMXC;

        if (gMXC) {
        if (state.controls.pendingMXCToggle) {
            if (gMXC.checked === enabledMXC) {
            state.controls.pendingMXCToggle = false;
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
        const enabled50K = !!state.currentParameters.enabled50K;

        if (g50K) {
        if (state.controls.pending50KToggle) {
            if (g50K.checked === enabled50K) {
            state.controls.pending50KToggle = false;
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
        const enabledSTILL = !!state.currentParameters.enabledSTILL;

        if (gSTILL) {
        if (state.controls.pendingSTILLToggle) {
            if (gSTILL.checked === enabledSTILL) {
            state.controls.pendingSTILLToggle = false;
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
        const enabled4K = !!state.currentParameters.enabled4K;

        if (g4K) {
        if (state.controls.pending4KToggle) {
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
            state.currentParameters[`enabledCH${chNum}`],
        );

        if (checkbox) {
            if (state.pendingExtraChannels[chNum]) {
            if (checkbox.checked === backendEnabled) {
                state.pendingExtraChannels[chNum] = false;
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
            const rVal = state.currentParameters[`RCH${chNum}`];
            if (rVal === undefined || rVal === null || Number.isNaN(rVal)) {
                rBox.textContent = "--";
            } else {
                rBox.textContent = `${Number(rVal).toFixed(2)} Ω`;
            }
            }
        }
        });

        const autoscanToggle = document.getElementById("autoscanToggle");
        if (autoscanToggle && state.currentParameters.autoscan !== undefined) {
        const backendAutoscanOn = state.currentParameters.autoscan === "on";

        if (state.controls.pendingAutoscanToggle) {
            if (autoscanToggle.checked === backendAutoscanOn) {
            state.controls.pendingAutoscanToggle = false;
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

        const relationMode = document.getElementById(
        "relationModeSelect",
        )?.value;

        if (relationMode !== "STEP_RAMP") {
        updateRelationStore();
        redrawRelationChart();
        }

        if (state.connection.tcpStatus === false) {
        await updateConnectionStatus();
        }
    } catch (error) {
        console.error("Error fetching data:", error);
        if (state.connection.tcpStatus !== false) {
        await updateConnectionStatus();
        }
    }
}
