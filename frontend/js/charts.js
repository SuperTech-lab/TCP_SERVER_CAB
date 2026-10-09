import { state } from './state.js';
import { 
    charts, chartDataStore, relationDataStore, RELATION_LIVE_POINTS
} from './state.js'
import { 
    updateRelationCurrentLabels,
    updateTimeRangeOptions50K,
    updateTimeRangeOptions4K,
    updateTimeRangeOptionsSTILL,
 } from './ui.js';

export function createRelationChart() {
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

export function redrawRelationChart() {

    const relationChart = state.relation.chart;

    if (!relationChart) return;

    const currentRelationChannel =
        state.relation.currentChannel;

    const pts =
        relationDataStore[currentRelationChannel] || [];

    const recentPts = pts.slice(
        -RELATION_LIVE_POINTS,
    );

    const relationMode = document.getElementById(
        "relationModeSelect",
    )?.value;

    const windowPts =
        relationMode === "STEP_RAMP"
            ? recentPts
            : recentPts
                .slice()
                .sort((a, b) => a.x - b.x);

    relationChart.data.datasets[0].data = windowPts;

    relationChart.data.datasets[0].label =
        `R(${currentRelationChannel}) vs T(MXC)`;

    relationChart.update("none");

    updateRelationCurrentLabels();
}

// General function to create any temperature chart (black body or lakeshore stages)
export function createTemperatureChart(
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
                            if (state.chart.currentTimeRangeMXC > 21600) {
                                return `${(value / 3600).toFixed(1)}h`;
                            } else if (state.chart.currentTimeRangeMXC > 300) {
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
export function enableYAxisLimitEditing(chart, canvasId) {
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
export function updateTemperatureChart(
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
        currentRange = state.chart.currentTimeRangeMXC;
    } else if (chartId === "50K") {
        currentRange = state.chart.currentTimeRange50K;
    } else if (chartId === "4K") {
        currentRange = state.chart.currentTimeRange4K;
    } else if (chartId === "STILL") {
        currentRange = state.chart.currentTimeRangeSTILL;
    } else if (chartId === "BB") {
        currentRange = state.chart.currentTimeRangeBB;
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

export function redrawFromStore(chartId) {
    const chart = charts[chartId];
    const store = chartDataStore[chartId];
    if (!chart || !store) return;

    const now = Date.now();
    const relTime = (now - store.startTime) / 1000;
    let currentRange;
    if (chartId === "MXC") {
        currentRange = state.chart.currentTimeRangeMXC;
    } else if (chartId === "50K") {
        currentRange = state.chart.currentTimeRange50K;
    } else if (chartId === "4K") {
        currentRange = state.chart.currentTimeRange4K;
    } else if (chartId === "STILL") {
        currentRange = state.chart.currentTimeRangeSTILL;
    } else if (chartId === "BB") {
        currentRange = state.chart.currentTimeRangeBB;
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