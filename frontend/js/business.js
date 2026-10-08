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
        default:
        return null;
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
}

export function sampleRangeCombinationIsValid(
    excitationMode,
    excitationRange,
    resistanceRange,
) {
    if (excitationMode === 1) {
        const internalVoltageRange =
        excitationRange + resistanceRange - 19;
        return internalVoltageRange >= 1 && internalVoltageRange <= 12;
    }

    const currentSourceRange =
        excitationRange - resistanceRange + 19;
    return currentSourceRange >= 1 && currentSourceRange <= 22;
}

async function loadRelationStepRampDefaults() {
    /*
    * Defaults are loaded only once per page.
    *
    * Do not alter the configuration form while an active relation
    * is owned by the backend.
    */
    if (
        relationStepRampDefaultsLoaded
        || relationRunning
    ) {
        return relationStepRampDefaultsLoaded;
    }

    try {
        const response = await fetch(
        "/get-step-ramp-defaults",
        {
            cache: "no-store",
        },
        );

        let payload;

        try {
        payload = await response.json();
        } catch {
        throw new Error(
            `Invalid defaults response `
            + `(HTTP ${response.status})`,
        );
        }

        if (
        !response.ok
        || !payload.ok
        ) {
        throw new Error(
            payload.error
            || `HTTP ${response.status}`,
        );
        }

        const defaults = payload.defaults;

        if (
        defaults === null
        || typeof defaults !== "object"
        || Array.isArray(defaults)
        ) {
        throw new Error(
            "Invalid STEP_RAMP defaults payload.",
        );
        }

        const inputIds = {
        initial_mk:
            "relationStepInitialInput",

        target_mk:
            "relationStepTargetInput",

        step_mk:
            "relationStepSizeInput",

        tolerance_mk:
            "relationStepToleranceInput",

        stable_time_s:
            "relationStepStableTimeInput",

        stability_timeout_s:
            "relationStepTimeoutInput",

        stability_sample_interval_s:
            "relationStepStabilityIntervalInput",

        autorange_max_attempts:
            "relationStepAutorangeAttemptsInput",

        resistance_n_samples:
            "relationStepResistanceSamplesInput",

        resistance_sample_interval_s:
            "relationStepResistanceIntervalInput",

        resistance_max_attempts:
            "relationStepResistanceAttemptsInput",

        max_std_mk:
            "relationStepMaxStdInput",

        max_slope_mk_per_min:
            "relationStepMaxSlopeInput",

        point_measurement_max_attempts:
            "relationStepPointAttemptsInput",
        };

        for (
        const [parameterName, inputId]
        of Object.entries(inputIds)
        ) {
        const input = document.getElementById(
            inputId
        );

        if (!input) {
            throw new Error(
            `STEP_RAMP input not found: ${inputId}.`,
            );
        }

        const value = defaults[
            parameterName
        ];

        /*
        * YAML null keeps an optional frontend field empty.
        */
        if (
            value === null
            || value === undefined
        ) {
            continue;
        }

        if (
            typeof value !== "number"
            || !Number.isFinite(value)
        ) {
            throw new Error(
            `Invalid STEP_RAMP default: `
            + `${parameterName}.`,
            );
        }

        /*
        * Never overwrite a value already restored by the backend
        * or entered by the user.
        */
        if (input.value.trim() === "") {
            input.value = String(
            value
            );
        }
        }

        relationStepRampDefaultsLoaded = true;

        console.info(
        "STEP_RAMP defaults loaded.",
        defaults,
        );

        return true;

    } catch (error) {
        console.error(
        "Could not load STEP_RAMP defaults:",
        error,
        );

        addLogEntry(
        `❌ STEP_RAMP defaults: ${error.message}`,
        "received",
        );

        return false;
    }
}

export async function initRelationStateFromServer() {
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

    const stepInitialInput = document.getElementById(
        "relationStepInitialInput",
    );

    const stepTargetInput = document.getElementById(
        "relationStepTargetInput",
    );
    const stepSizeInput = document.getElementById(
        "relationStepSizeInput",
    );

    const wasRunning = relationRunning;

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
        const response = await fetch(
        "/get-relation-status",
        {
            cache: "no-store",
        },
        );

        let payload;

        try {
        payload = await response.json();
        } catch {
        throw new Error(
            `Invalid status response `
            + `(HTTP ${response.status})`,
        );
        }

        if (!response.ok || !payload.ok) {
        throw new Error(
            payload.error
            || `HTTP ${response.status}`,
        );
        }

        // ================================================================
        // No active RELATION
        // ================================================================

        if (!payload.active) {
        const isStepRamp =
            payload.mode === "STEP_RAMP";

        const stepRampState =
            isStepRamp
            ? payload.state
            : null;

        if (
            wasRunning
            && isStepRamp
        ) {
            /*
            * First try to consume any final in-memory
            * points still exposed by the TCP backend.
            */
            await fetchRelationStepRampLivePoints();

            /*
            * Then replace the live curve with the
            * definitive persisted .dat.
            */
            await reconcileRelationStepRampFromFile();
        }

        setRelationUiIdle();

        if (wasRunning) {

            await loadRelationStepRampDefaults();

            if (isStepRamp) {

            if (stepRampState === "COMPLETE") {

                addLogEntry(
                "✅ STEP_RAMP completed.",
                "status",
                );

            } else if (stepRampState === "ABORTED") {

                addLogEntry(
                "⏹ STEP_RAMP aborted.",
                "status",
                );

            } else if (stepRampState === "ERROR") {

                const errorMessage =
                payload.error
                || "Unknown STEP_RAMP error.";

                addLogEntry(
                `❌ STEP_RAMP failed: ${errorMessage}`,
                "status",
                );

            } else {

                /*
                * Defensive fallback. A non-active STEP_RAMP should
                * normally expose one of its terminal states.
                */
                addLogEntry(
                `⚠ STEP_RAMP finished with state `
                + `${stepRampState ?? "UNKNOWN"}.`,
                "status",
                );
            }

            } else {

            /*
            * Preserve existing MANUAL / native RAMP behaviour.
            */
            addLogEntry(
                "✅ Relation finished.",
                "status",
            );
            }

            await refreshRelationFiles();
        }

        return;
        }

        // ================================================================
        // Active RELATION
        // ================================================================

        const channelNumber = Number(
        payload.channel,
        );

        if (
        !Number.isInteger(channelNumber)
        || !SAMPLE_CHANNELS.includes(
            channelNumber,
        )
        ) {
        throw new Error(
            "Active relation has an invalid channel.",
        );
        }

        const mode = payload.mode;

        if (
        mode !== "MANUAL"
        && mode !== "RAMP"
        && mode !== "STEP_RAMP"
        ) {
        throw new Error(
            `Unknown relation mode: ${mode}`,
        );
        }

        const channelName =
        `CH${channelNumber}`;

        channelSelect.value = channelName;
        currentRelationChannel = channelName;

        labelInput.value =
        payload.label ?? "";

        modeSelect.value = mode;

        // ================================================================
        // Restore mode-specific values exposed by the backend
        // ================================================================

        if (mode === "RAMP") {
        if (
            Number.isFinite(
            Number(payload.target_mk),
            )
        ) {
            targetInput.value =
            payload.target_mk;
        }

        if (
            Number.isFinite(
            Number(payload.rate_mk_per_min),
            )
        ) {
            rateInput.value =
            payload.rate_mk_per_min;
        }
        }

        if (mode === "STEP_RAMP") {
        
        if (
            payload.initial_mk !== null
            && payload.initial_mk !== undefined
            && Number.isFinite(
            Number(payload.initial_mk),
            )
        ) {
            stepInitialInput.value =
            payload.initial_mk;
        }

        if (
            Number.isFinite(
            Number(payload.target_mk),
            )
        ) {
            stepTargetInput.value =
            payload.target_mk;
        }

        if (
            Number.isFinite(
            Number(payload.step_mk),
            )
        ) {
            stepSizeInput.value =
            payload.step_mk;
        }

        const restoredRelationId =
            payload.relation_id === null
            || payload.relation_id === undefined
            ? null
            : String(payload.relation_id);

        if (!restoredRelationId) {
            throw new Error(
            "Active STEP_RAMP relation_id is missing.",
            );
        }

        const trackingChanged =
            relationStepRampLiveRelationId
            !== restoredRelationId
            || relationStepRampLiveChannel
            !== channelName;

        if (trackingChanged) {
            relationDataStore[channelName].length = 0;

            relationStepRampLiveRelationId =
            restoredRelationId;

            relationStepRampLiveNextSeq = 0;

            relationStepRampLiveChannel =
            channelName;
        }
        }

        // ================================================================
        // Lock UI while backend owns the relation
        // ================================================================

        relationRunning = true;

        startButton.disabled = true;

        /*
        * During asynchronous STEP_RAMP shutdown,
        * do not allow a second Stop request.
        */
        stopButton.disabled =
        mode === "STEP_RAMP"
        && (
            payload.abort_requested === true
            || payload.running === false
        );

        channelSelect.disabled = true;
        labelInput.disabled = true;
        modeSelect.disabled = true;

        updateRelationLabelVisibility();
        updateRelationRampControls();

        // ================================================================
        // Log only when an active relation is discovered/restored.
        // Do not produce one log entry per poll.
        // ================================================================

        if (!wasRunning) {
        if (mode === "STEP_RAMP") {
            addLogEntry(
            `🔁 STEP_RAMP activa recuperada: `
            + `CH${channelNumber}, `
            + `state=${payload.state ?? "?"}, `
            + `point=${payload.current_point ?? "?"}`
            + `/${payload.total_points ?? "?"}`,
            "status",
            );
        } else {
            addLogEntry(
            `🔁 Relation activa recuperada: `
            + `CH${channelNumber}, `
            + `mode=${mode}`,
            "status",
            );
        }
        }

    } catch (error) {
        /*
        * A communication/status error is not proof that the
        * backend relation has ended.
        *
        * If the frontend already believed a relation was active,
        * keep the controls locked.
        */
        if (!wasRunning) {
        setRelationUiIdle();
        }

        addLogEntry(
        `❌ Error get_relation_status: `
        + `${error.message}`,
        "received",
        );
    }
}

function buildRelationStepRampPayload(
    channelNumber,
    label,
    ) {
    // ================================================================
    // Local input readers
    // ================================================================

    function requiredNumber(id, name) {
        const element = document.getElementById(id);
        const raw = element.value.trim();

        if (raw === "") {
        throw new Error(
            `${name} is required.`,
        );
        }

        const value = Number(raw);

        if (!Number.isFinite(value)) {
        throw new Error(
            `${name} must be a finite number.`,
        );
        }

        return value;
    }

    function requiredInteger(id, name) {
        const value = requiredNumber(
        id,
        name,
        );

        if (!Number.isInteger(value)) {
        throw new Error(
            `${name} must be an integer.`,
        );
        }

        return value;
    }

    function optionalNumber(id, name) {
        const element = document.getElementById(id);
        const raw = element.value.trim();

        if (raw === "") {
        return null;
        }

        const value = Number(raw);

        if (!Number.isFinite(value)) {
        throw new Error(
            `${name} must be a finite number.`,
        );
        }

        return value;
    }

    function optionalInteger(id, name) {
        const element = document.getElementById(id);
        const raw = element.value.trim();

        if (raw === "") {
        return null;
        }

        const value = Number(raw);

        if (
        !Number.isFinite(value)
        || !Number.isInteger(value)
        ) {
        throw new Error(
            `${name} must be an integer.`,
        );
        }

        return value;
    }

    // ================================================================
    // Channel
    // ================================================================

    const channel = Number(channelNumber);

    if (
        !Number.isInteger(channel)
        || !SAMPLE_CHANNELS.includes(channel)
    ) {
        throw new Error(
        "Invalid STEP_RAMP sample channel.",
        );
    }

    // ================================================================
    // Required parameters
    // ================================================================

    const initialMk = requiredNumber(
        "relationStepInitialInput",
        "Initial",
    );

    const targetMk = requiredNumber(
        "relationStepTargetInput",
        "Target",
    );

    const stepMk = requiredNumber(
        "relationStepSizeInput",
        "Step",
    );

    const toleranceMk = requiredNumber(
        "relationStepToleranceInput",
        "Tolerance",
    );

    const stableTimeS = requiredNumber(
        "relationStepStableTimeInput",
        "Stable time",
    );

    const stabilityTimeoutS = requiredNumber(
        "relationStepTimeoutInput",
        "Stability timeout",
    );

    const stabilitySampleIntervalS =
        requiredNumber(
        "relationStepStabilityIntervalInput",
        "Stability sample interval",
        );

    const autorangeMaxAttempts =
        requiredInteger(
        "relationStepAutorangeAttemptsInput",
        "Autorange max attempts",
        );

    const resistanceNSamples =
        requiredInteger(
        "relationStepResistanceSamplesInput",
        "R samples",
        );

    const resistanceSampleIntervalS =
        requiredNumber(
        "relationStepResistanceIntervalInput",
        "R sample interval",
        );

    const resistanceMaxAttempts =
        requiredInteger(
        "relationStepResistanceAttemptsInput",
        "R max attempts",
        );

    // ================================================================
    // Required-parameter validation
    // ================================================================

    if (
        initialMk < 10
        || initialMk > 800
    ) {
        throw new Error(
        "Initial must be between 10 and 800 mK.",
        );
    }

    if (targetMk < 0) {
        throw new Error(
        "Target must be non-negative.",
        );
    }

    if (stepMk <= 0) {
        throw new Error(
        "Step must be greater than zero.",
        );
    }

    if (toleranceMk <= 0) {
        throw new Error(
        "Tolerance must be greater than zero.",
        );
    }

    if (stableTimeS <= 0) {
        throw new Error(
        "Stable time must be greater than zero.",
        );
    }

    if (stabilityTimeoutS <= stableTimeS) {
        throw new Error(
        "Stability timeout must be greater "
        + "than stable time.",
        );
    }

    if (stabilitySampleIntervalS <= 0) {
        throw new Error(
        "Stability sample interval must be "
        + "greater than zero.",
        );
    }

    if (autorangeMaxAttempts <= 0) {
        throw new Error(
        "Autorange max attempts must be "
        + "greater than zero.",
        );
    }

    if (resistanceNSamples <= 0) {
        throw new Error(
        "R samples must be greater than zero.",
        );
    }

    if (resistanceSampleIntervalS < 0) {
        throw new Error(
        "R sample interval must be non-negative.",
        );
    }

    if (resistanceMaxAttempts <= 0) {
        throw new Error(
        "R max attempts must be greater than zero.",
        );
    }

    if (
        resistanceMaxAttempts
        < resistanceNSamples
    ) {
        throw new Error(
        "R max attempts must be greater than "
        + "or equal to R samples.",
        );
    }

    // ================================================================
    // Optional parameters
    // ================================================================

    const maxStdMk = optionalNumber(
        "relationStepMaxStdInput",
        "Max T std",
    );

    const maxSlopeMkPerMin = optionalNumber(
        "relationStepMaxSlopeInput",
        "Max T slope",
    );

    const pointMeasurementMaxAttempts =
        optionalInteger(
        "relationStepPointAttemptsInput",
        "Point max attempts",
        );

    if (
        maxStdMk !== null
        && maxStdMk < 0
    ) {
        throw new Error(
        "Max T std must be non-negative.",
        );
    }

    if (
        maxSlopeMkPerMin !== null
        && maxSlopeMkPerMin < 0
    ) {
        throw new Error(
        "Max T slope must be non-negative.",
        );
    }

    if (
        pointMeasurementMaxAttempts !== null
        && pointMeasurementMaxAttempts <= 0
    ) {
        throw new Error(
        "Point max attempts must be "
        + "greater than zero.",
        );
    }

    // ================================================================
    // Build payload expected by tcp_server.py
    // ================================================================

    const payload = {
        channel_number              : channel,
        initial_mk                  : initialMk,
        target_mk                   : targetMk,
        step_mk                     : stepMk,
        tolerance_mk                : toleranceMk,
        stable_time_s               : stableTimeS,
        stability_timeout_s         : stabilityTimeoutS,
        stability_sample_interval_s : stabilitySampleIntervalS,
        autorange_max_attempts:
        autorangeMaxAttempts,
        resistance_n_samples:
        resistanceNSamples,
        resistance_sample_interval_s:
        resistanceSampleIntervalS,
        resistance_max_attempts:
        resistanceMaxAttempts,
        label: label,
    };

    if (maxStdMk !== null) {
        payload.max_std_mk = maxStdMk;
    }

    if (maxSlopeMkPerMin !== null) {
        payload.max_slope_mk_per_min =
        maxSlopeMkPerMin;
    }

    if (
        pointMeasurementMaxAttempts !== null
    ) {
        payload.point_measurement_max_attempts =
        pointMeasurementMaxAttempts;
    }

    return payload;
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

function clearPendingExtraChannelsForSampleChannels() {
    SAMPLE_CHANNELS.forEach((ch) => {
        if (pendingExtraChannels && pendingExtraChannels[ch] !== undefined) {
        pendingExtraChannels[ch] = false;
        }
    });
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

function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}