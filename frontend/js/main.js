import { initParticles } from './particles.js';
import { fetchRelationStepRampLivePoints } from './api.js';
import { refreshRelationFiles } from './api.js';
import { fetchSensorData } from './api.js';
import { initRunIdFromServer } from './api.js';
import { initRelationStateFromServer } from './business.js';
import { updateRunUI } from './ui.js';

// ToDo: currentActiveRunId variable is not defined. I have defined it as null
// but check if there's a problem because other parts of the code in other files
// might be using it.

let currentActiveRunId = null; // CHECK

document.addEventListener("DOMContentLoaded", async () => {
    
    // ToDo: currentRelationChannel variable is not defined.
    let currentRelationChannel;

    const sel = document.getElementById("relationChannelSelect");
    if (sel) currentRelationChannel = sel.value;

    await initRelationStateFromServer();

    if (!relationRunning) {
        await loadRelationStepRampDefaults();
    }
    relationChart = createRelationChart();
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