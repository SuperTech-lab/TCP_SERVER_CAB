function updateTimeRange() {
  const timeRangeSelect = document.getElementById("timeRangeMXC");
  currentTimeRangeMXC = parseInt(timeRangeSelect.value, 10);
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

function updateTimeRangeOptions() {
  const select = document.getElementById("timeRangeMXC");
  const store = chartDataStore.MXC;
  if (!store || !store.startTime) return;

  const elapsed = Math.max(0, (Date.now() - store.startTime) / 1000);
  select.innerHTML = "";

  for (let i = 0; i < timeRangeOptions.length; i++) {
    const option = timeRangeOptions[i];
    const element = document.createElement("option");
    element.value = option.value;
    element.textContent = option.label;
    element.disabled = i > 0 && elapsed < timeRangeOptions[i - 1].value;
    element.selected = option.value === currentTimeRangeMXC;
    select.appendChild(element);
  }

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
  updateTimeRangeOptionsFor(
    "50K",
    "timeRange50K",
    currentTimeRange50K,
    (value) => { currentTimeRange50K = value; },
  );
}

function updateTimeRangeOptions4K() {
  updateTimeRangeOptionsFor(
    "4K",
    "timeRange4K",
    currentTimeRange4K,
    (value) => { currentTimeRange4K = value; },
  );
}

function updateTimeRangeOptionsSTILL() {
  updateTimeRangeOptionsFor(
    "STILL",
    "timeRangeSTILL",
    currentTimeRangeSTILL,
    (value) => { currentTimeRangeSTILL = value; },
  );
}

function updateTimeRangeOptionsFor(chartId, selectId, currentRange, setRange) {
  const select = document.getElementById(selectId);
  const store = chartDataStore[chartId];
  if (!select || !store || !store.startTime) return;

  const elapsed = Math.max(0, (Date.now() - store.startTime) / 1000);
  select.innerHTML = "";

  for (let i = 0; i < timeRangeOptions.length; i++) {
    const option = timeRangeOptions[i];
    const element = document.createElement("option");
    element.value = option.value;
    element.textContent = option.label;
    element.disabled = i > 0 && elapsed < timeRangeOptions[i - 1].value;
    element.selected = option.value === currentRange;
    select.appendChild(element);
  }

  if (select.options[select.selectedIndex]?.disabled) {
    for (let i = select.options.length - 1; i >= 0; i--) {
      if (!select.options[i].disabled) {
        select.selectedIndex = i;
        setRange(parseInt(select.options[i].value, 10));
        break;
      }
    }
  }
}

function createTemperatureChart(
  canvasId,
  includeSetpoint = false,
  label = "Temperature (K)",
) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return null;

  const datasets = [
    {
      label,
      data: [],
      borderColor: "royalblue",
      borderWidth: 1,
      pointRadius: 0,
      fill: includeSetpoint
        ? {
            target: "1",
            above: "rgba(173, 216, 230, 0.1)",
            below: "rgba(173, 216, 230, 0.1)",
          }
        : false,
    },
  ];

  if (includeSetpoint) {
    datasets.push({
      label: "Setpoint (K)",
      data: [],
      borderColor: "rgba(255, 99, 132, 0.9)",
      borderWidth: 2,
      borderDash: [5, 5],
      fill: false,
      pointRadius: 0,
    });
  }

  return new Chart(canvas.getContext("2d"), {
    type: "line",
    data: { labels: [], datasets },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: true,
      scales: {
        x: {
          type: "linear",
          title: { display: true, text: "Time (s)" },
          min: 0,
          max: 60,
          ticks: {
            callback(value) {
              if (currentTimeRangeMXC > 21600) return `${(value / 3600).toFixed(1)}h`;
              if (currentTimeRangeMXC > 300) return `${(value / 60).toFixed(1)}m`;
              return `${value.toFixed(0)}s`;
            },
          },
        },
        y: {
          title: { display: true, text: "Temperature (K)" },
          beginAtZero: false,
        },
      },
    },
  });
}

function enableYAxisLimitEditing(chart, canvasId) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || !chart) return;

  canvas.addEventListener("dblclick", (event) => {
    const rect = canvas.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const yAxis = chart.scales.y;

    if (x < yAxis.left || x > yAxis.right) return;

    const currentMin = chart.options.scales.y.min ?? yAxis.min;
    const currentMax = chart.options.scales.y.max ?? yAxis.max;
    const newMin = prompt(`Enter new Y-axis MIN (current: ${currentMin}):`, currentMin);
    if (newMin === null || isNaN(parseFloat(newMin))) return;

    const newMax = prompt(`Enter new Y-axis MAX (current: ${currentMax}):`, currentMax);
    if (newMax === null || isNaN(parseFloat(newMax))) return;

    chart.options.scales.y.min = parseFloat(newMin);
    chart.options.scales.y.max = parseFloat(newMax);
    chart.update();
  });
}

function updateTemperatureChart(
  chartId,
  temperature,
  setpoint = null,
  timestampMs = Date.now(),
) {
  const timestamp = Number(timestampMs);
  const numericTemperature = Number(temperature);
  if (!Number.isFinite(timestamp) || !Number.isFinite(numericTemperature)) return;
  if (!charts[chartId]) return;

  if (!chartDataStore[chartId]) {
    chartDataStore[chartId] = {
      labels: [],
      data: [],
      setpoint: [],
      startTime: null,
      lastTimestamp: null,
    };
  }

  const store = chartDataStore[chartId];
  if (store.lastTimestamp !== null && timestamp <= store.lastTimestamp) return;
  if (!store.startTime) store.startTime = timestamp;

  const relativeTime = (timestamp - store.startTime) / 1000;
  store.labels.push(relativeTime);
  store.data.push(numericTemperature);
  if (setpoint !== null) store.setpoint.push(setpoint);
  store.lastTimestamp = timestamp;

  if (chartId === "MXC") updateTimeRangeOptions();
  if (chartId === "50K") updateTimeRangeOptions50K();
  if (chartId === "4K") updateTimeRangeOptions4K();
  if (chartId === "STILL") updateTimeRangeOptionsSTILL();

  let range = 60;
  if (chartId === "MXC") range = currentTimeRangeMXC;
  if (chartId === "50K") range = currentTimeRange50K;
  if (chartId === "4K") range = currentTimeRange4K;
  if (chartId === "STILL") range = currentTimeRangeSTILL;
  if (chartId === "BB") range = currentTimeRangeBB;

  const displayStart = Math.max(0, relativeTime - range);
  const labels = [];
  const temperatures = [];
  const setpoints = [];

  for (let i = 0; i < store.labels.length; i++) {
    if (store.labels[i] >= displayStart) {
      labels.push(store.labels[i] - displayStart);
      temperatures.push(store.data[i]);
      if (setpoint !== null && store.setpoint) setpoints.push(store.setpoint[i]);
    }
  }

  const chart = charts[chartId];
  chart.data.labels = labels;
  chart.data.datasets[0].data = temperatures;
  if (setpoint !== null && chart.data.datasets[1]) {
    chart.data.datasets[1].data = setpoints;
  }
  chart.options.scales.x.min = 0;
  chart.options.scales.x.max = range;
  chart.options.scales.y.suggestedMin = 0;
  chart.update("none");
}

function redrawFromStore(chartId) {
  const chart = charts[chartId];
  const store = chartDataStore[chartId];
  if (!chart || !store || !store.startTime) return;

  const relativeTime = (Date.now() - store.startTime) / 1000;
  let range = 60;
  if (chartId === "MXC") range = currentTimeRangeMXC;
  if (chartId === "50K") range = currentTimeRange50K;
  if (chartId === "4K") range = currentTimeRange4K;
  if (chartId === "STILL") range = currentTimeRangeSTILL;
  if (chartId === "BB") range = currentTimeRangeBB;

  const displayStart = Math.max(0, relativeTime - range);
  const labels = [];
  const temperatures = [];
  const setpoints = [];

  for (let i = 0; i < store.labels.length; i++) {
    if (store.labels[i] >= displayStart) {
      labels.push(store.labels[i] - displayStart);
      temperatures.push(store.data[i]);
      if (store.setpoint) setpoints.push(store.setpoint[i]);
    }
  }

  chart.data.labels = labels;
  chart.data.datasets[0].data = temperatures;
  if (chart.data.datasets[1]) chart.data.datasets[1].data = setpoints;
  chart.options.scales.x.min = 0;
  chart.options.scales.x.max = range;
  chart.update("none");
}

function createRelationChart() {
  const canvas = document.getElementById("relationChart");
  if (!canvas) return null;

  return new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      datasets: [{
        label: "R(STILL) vs T(MXC)",
        data: [],
        showLine: true,
        pointRadius: 0,
        borderWidth: 2,
        tension: 0,
      }],
    },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { type: "linear", title: { display: true, text: "MXC Temperature (K)" } },
        y: { title: { display: true, text: "Resistance (Ω)" } },
      },
      plugins: {
        legend: { display: true },
        tooltip: {
          callbacks: {
            label(context) {
              const x = context.parsed.x;
              const y = context.parsed.y;
              return `T=${x.toFixed(6)} K, R=${y.toFixed(3)} Ω`;
            },
          },
        },
      },
    },
  });
}

function redrawRelationChart() {
  if (!relationChart) return;

  const points = relationDataStore[currentRelationChannel] || [];
  const visiblePoints = points
    .slice(-RELATION_LIVE_POINTS)
    .sort((a, b) => a.x - b.x);

  relationChart.data.datasets[0].data = visiblePoints;
  relationChart.data.datasets[0].label =
    `R(${currentRelationChannel}) vs T(MXC)`;
  relationChart.update("none");
  updateRelationCurrentLabels();
}