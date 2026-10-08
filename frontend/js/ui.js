import { sampleRangeCombinationIsValid } from './business.js';

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

function optionLabel(options, value) {
    return options.find(([index]) => index === value)?.[1] ?? `#${value}`;
}

function markSampleSettingsDirty(channel) {
    const details = document
        .getElementById(`sensorModeCH${channel}`)
        ?.closest("details");

    if (details) details.dataset.settingsDirty = "true";
}

function populateSampleExcitationOptions(
    channel, 
    preferredRange = null
) {
    const modeSelect = document.getElementById(`sensorModeCH${channel}`);
    const excitationSelect = document.getElementById(
        `sensorRangeCH${channel}`,
    );
    const resistanceSelect = document.getElementById(
        `resistanceRangeCH${channel}`,
    );

    if (!modeSelect || !excitationSelect || !resistanceSelect) return;

    const mode = Number(modeSelect.value);
    const resistanceRange = Number(resistanceSelect.value);
    const previousRange = Number(
        preferredRange ?? excitationSelect.value,
    );
    const ranges =
        mode === 1
        ? SAMPLE_CURRENT_EXCITATION_RANGES
        : SAMPLE_VOLTAGE_EXCITATION_RANGES;

    const validRanges = ranges.filter(([rangeIndex]) =>
        sampleRangeCombinationIsValid(
        mode,
        rangeIndex,
        resistanceRange,
        ),
    );

    excitationSelect.replaceChildren(
        ...validRanges.map(([rangeIndex, label]) => {
        const option = document.createElement("option");
        option.value = String(rangeIndex);
        option.textContent = `${rangeIndex} - ${label}`;
        return option;
        }),
    );

    if (validRanges.some(([rangeIndex]) => rangeIndex === previousRange)) {
        excitationSelect.value = String(previousRange);
    }
}

function createSampleSettingRow(
    labelText, 
    selectId, 
    options
) {
    const row = document.createElement("div");
    row.className = "control-row";

    const label = document.createElement("label");
    label.htmlFor = selectId;
    label.style.width = "145px";
    label.style.marginRight = "8px";
    label.textContent = labelText;

    const select = document.createElement("select");
    select.id = selectId;
    select.className = "control-input";
    select.style.width = "170px";
    select.style.marginLeft = "0";

    options.forEach(([value, text]) => {
        const option = document.createElement("option");
        option.value = String(value);
        option.textContent = `${value} - ${text}`;
        select.appendChild(option);
    });

    row.append(label, select);
    return row;
}

function initializeSampleChannelControls() {
    SAMPLE_CHANNELS.forEach((channel) => {
        const modeSelect = document.getElementById(`sensorModeCH${channel}`);
        const excitationSelect = document.getElementById(
        `sensorRangeCH${channel}`,
        );

        if (!modeSelect || !excitationSelect) return;

        const menu = modeSelect.closest(".channel-dropdown-menu");
        const modeRow = modeSelect.closest(".control-row");
        const excitationRow = excitationSelect.closest(".control-row");
        const buttonRow = menu?.querySelector("button")?.closest(".control-row");

        if (!menu || !modeRow || !excitationRow || !buttonRow) return;

        menu.style.minWidth = "380px";
        menu.insertBefore(modeRow, excitationRow);

        const modeLabel = modeRow.querySelector("label");
        const excitationLabel = excitationRow.querySelector("label");

        if (modeLabel) modeLabel.style.width = "145px";
        if (excitationLabel) {
        excitationLabel.style.width = "145px";
        excitationLabel.textContent = "Excitation range:";
        }

        excitationSelect.style.width = "170px";

        const resistanceRow = createSampleSettingRow(
        "Resistance range:",
        `resistanceRangeCH${channel}`,
        SAMPLE_RESISTANCE_RANGES,
        );

        const rangeControlRow = createSampleSettingRow(
        "Range control:",
        `autorangeCH${channel}`,
        [
            [0, "Manual"],
            [1, "Autorange"],
        ],
        );

        const readback = document.createElement("div");
        readback.id = `sampleConfigReadbackCH${channel}`;
        readback.style.fontSize = "11px";
        readback.style.margin = "8px 0";
        readback.style.color = "#555";
        readback.textContent = "Actual: waiting for controller readback...";

        menu.insertBefore(resistanceRow, excitationRow);
        menu.insertBefore(rangeControlRow, buttonRow);
        menu.insertBefore(readback, buttonRow);

        const resistanceSelect = document.getElementById(
        `resistanceRangeCH${channel}`,
        );
        const autorangeSelect = document.getElementById(
        `autorangeCH${channel}`,
        );

        // Sensible initial manual range for the approximately 3 Ω samples.
        modeSelect.value = "1";
        resistanceSelect.value = "8";
        autorangeSelect.value = "0";
        populateSampleExcitationOptions(channel, 15);

        [modeSelect, excitationSelect, resistanceSelect, autorangeSelect]
        .forEach((select) => {
            select.addEventListener("change", () => {
            markSampleSettingsDirty(channel);

            if (select === modeSelect || select === resistanceSelect) {
                populateSampleExcitationOptions(channel);
            }
            });
        });
    });
}

function syncSampleChannelControls(channel) {
    const mode = currentParameters[`modeCH${channel}`];
    const excitationRange =
        currentParameters[`excitationRangeCH${channel}`]
        ?? currentParameters[`rangeCH${channel}`];
    const resistanceRange =
        currentParameters[`resistanceRangeCH${channel}`];
    const autorange = currentParameters[`autorangeCH${channel}`];
    const excitationOn = currentParameters[`excitationOnCH${channel}`];
    const details = document
        .getElementById(`sensorModeCH${channel}`)
        ?.closest("details");
    const readback = document.getElementById(
        `sampleConfigReadbackCH${channel}`,
    );

    if (readback) {
        if (
        mode == null
        || excitationRange == null
        || resistanceRange == null
        || autorange == null
        ) {
        readback.textContent = "Actual: waiting for controller readback...";
        } else {
        const excitationOptions =
            mode === 1
            ? SAMPLE_CURRENT_EXCITATION_RANGES
            : SAMPLE_VOLTAGE_EXCITATION_RANGES;
        const stateText = excitationOn === 0 ? " · excitation OFF" : "";

        readback.textContent =
            `Actual: ${mode === 1 ? "Current" : "Voltage"}`
            + ` · ${optionLabel(excitationOptions, excitationRange)}`
            + ` · ${optionLabel(SAMPLE_RESISTANCE_RANGES, resistanceRange)}`
            + ` · ${autorange === 1 ? "Autorange" : "Manual"}`
            + stateText;
        }
    }

    if (details?.dataset.settingsDirty === "true") return;

    const modeSelect = document.getElementById(`sensorModeCH${channel}`);
    const resistanceSelect = document.getElementById(
        `resistanceRangeCH${channel}`,
    );
    const autorangeSelect = document.getElementById(
        `autorangeCH${channel}`,
    );

    if (modeSelect && mode != null) modeSelect.value = String(mode);
    if (resistanceSelect && resistanceRange != null) {
        resistanceSelect.value = String(resistanceRange);
    }
    if (autorangeSelect && autorange != null) {
        autorangeSelect.value = String(autorange);
    }

    populateSampleExcitationOptions(channel, excitationRange);
}

function updateRelationLabelVisibility() {
    const ch = document.getElementById("relationChannelSelect").value;
    const input = document.getElementById("relationLabelInput");

    if (
        ["CH9", "CH10", "CH11", "CH12", "CH13", "CH14"].includes(ch)
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
    const stepRampControls = document.getElementById(
        "relationStepRampControls",
    );
    const targetInput = document.getElementById(
        "relationTargetInput",
    );
    const rateInput = document.getElementById(
        "relationRateInput",
    );

    const isRamp     = modeSelect.value === "RAMP";
    const isStepRamp = modeSelect.value === "STEP_RAMP";

    rampControls.style.display = isRamp
        ? "block"
        : "none";

    stepRampControls.style.display = isStepRamp
        ? "block"
        : "none";

    targetInput.disabled =
        !isRamp || relationRunning;
    rateInput.disabled =
        !isRamp || relationRunning;

    stepRampControls
        .querySelectorAll("input")
        .forEach((input) => {
        input.disabled =
            !isStepRamp || relationRunning;
        });

    const relationSection =
        modeSelect.closest(".section-content");

        if (
            relationSection
            && !relationSection.classList.contains(
                "collapsed",
            )
        ) {
            requestAnimationFrame(() => {
                relationSection.style.maxHeight =
                relationSection.scrollHeight + "px";
            });
        }
}

document
.getElementById("relationModeSelect")
.addEventListener(
    "change",
    updateRelationRampControls,
);

updateRelationRampControls();

function onRelationChannelChange() {
    const sel = document.getElementById("relationChannelSelect");
    if (!sel) return;

    currentRelationChannel = sel.value; // "CH9".."CH14"

    updateRelationLabelVisibility();
    redrawRelationChart();
    updateRelationCurrentLabels?.(); // por si existe en tu archivo
}

export function updateRunUI() {
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

function openHistoricalRelationWindow(fileName) {
    const url = `/plot_relation?file_name=${encodeURIComponent(fileName)}`;
    window.open(url, "_blank", "width=1200,height=800");
    addLogEntry(
        `✅ Abierta ventana con gráfica Python de relation: ${fileName}`,
        "status",
    );
}

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