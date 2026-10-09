import { initParticles } from './particles.js';
import { 
    refreshRelationFiles, fetchRelationStepRampLivePoints, 
    refreshRecentRuns, initRunIdFromServer, 
    updateConnectionStatus, fetchSensorData, loadTemperatureBuffer, 
    sendCommandToServer, sendControlParameters,
} from './api.js';
import {
    createRelationChart, redrawRelationChart, createTemperatureChart, enableYAxisLimitEditing,
} from "./charts.js";
import { 
    initRelationStateFromServer, loadRelationStepRampDefaults
} from './business.js';
import { 
    updateRunUI, addLogEntry, setupCollapsibleSections, initializeSampleChannelControls
} from './ui.js';
import { state } from './state.js';
import { charts, MXC_CONTROL_IDS, MXC_SENSOR_IDS } from './state.js';


document.addEventListener("DOMContentLoaded", async () => {

    const sel = document.getElementById(
        "relationChannelSelect",
    );

    if (sel) {
        state.relation.currentChannel = sel.value;
    }

    // Initialize relation chart.
    state.relation.chart = createRelationChart();

    if (!state.relation.chart) {
        console.error(
            "Failed to initialize relation chart.",
        );
        return;
    }

    // Recover relation state from the backend.
    await initRelationStateFromServer();

    if (!state.relation.running) {
        await loadRelationStepRampDefaults();
    }

    // Render available relation data.
    redrawRelationChart();
});

// CALL THE FUNCTION WHEN THE PAGE LOADS
document.addEventListener("DOMContentLoaded", initParticles);

setInterval(fetchRelationStepRampLivePoints,1000);

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

        if (state.run.activeId !== null) {
        addLogEntry("⚠️ A run is already active", "status");
        return;
        }

        const isHistorical =
            state.run.activeId === null &&
            state.run.expectedNextId !== null &&
            runId < state.run.expectedNextId;

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
            state.run.activeId = runId;
            state.run.expectedNextId = state.run.expectedNextId;
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
            state.run.activeId = null;
            state.run.expectedNextId = ended + 1;
            runIdInput.value = state.run.expectedNextId;
            updateRunUI();
        } else {
            addLogEntry("❌ Run not ended; local state won't change", "received");
        }
        } catch (error) {
        addLogEntry(`Error sending end_run: ${error.message}`, "received");
        }
    });
});

// Check initial connection status when page loads
document.addEventListener("DOMContentLoaded", async function () {
    // Set up collapsible sections
    setupCollapsibleSections();
    initializeSampleChannelControls();

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
setInterval(initRelationStateFromServer, 1000);