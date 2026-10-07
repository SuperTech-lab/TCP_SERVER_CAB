function clearPendingExtraChannelsForSampleChannels() {
	[9, 10, 11, 12, 13, 14, 15].forEach((channel) => {
		if (pendingExtraChannels?.[channel] !== undefined) {
			pendingExtraChannels[channel] = false;
		}
	});
}

async function sendControlParameters() {
	if (tcpConnectionStatus === false) {
		addLogEntry("Cannot send command: No connection to TCP server", "status");
		return;
	}

	const values = {
		temperatureSetpoint: parseFloat(document.getElementById("temperatureSetpoint").value),
		heaterPower: parseFloat(document.getElementById("heaterPower").value),
		heaterRange: document.getElementById("heaterRange").value,
		temperatureLimit: parseFloat(document.getElementById("temperatureLimit").value),
		timeout: parseFloat(document.getElementById("timeout").value),
		proportionalGain: parseFloat(document.getElementById("proportionalGain").value),
		integralGain: parseFloat(document.getElementById("integralGain").value),
		derivativeGain: parseFloat(document.getElementById("derivativeGain").value),
	};

	const commands = [];
	const addNonNegative = (key, command, message) => {
		if (!isNaN(values[key]) && values[key] !== lastSentValues[key]) {
			if (values[key] < 0) {
				addLogEntry(message, "received");
				return false;
			}
			commands.push({ type: key, command });
		}
		return true;
	};

	if (!addNonNegative(
		"temperatureSetpoint",
		`set_temperature_setpoint:${values.temperatureSetpoint}`,
		"Error: Temperature setpoint must be non-negative",
	)) return;
	if (!isNaN(values.heaterPower) && values.heaterPower !== lastSentValues.heaterPower) {
		if (values.heaterPower < 0 || values.heaterPower > 1) {
			addLogEntry("Error: Heater power must be between 0.0 and 1.0", "received");
			return;
		}
		commands.push({ type: "heaterPower", command: `set_heater_power:${values.heaterPower}` });
	}
	if (values.heaterRange !== lastSentValues.heaterRange) {
		commands.push({ type: "heaterRange", command: `set_heater_range:${values.heaterRange}` });
	}
	if (!addNonNegative(
		"temperatureLimit",
		`set_temperature_limit:${values.temperatureLimit}`,
		"Error: Temperature limit must be non-negative",
	)) return;
	if (!addNonNegative(
		"timeout",
		`set_timeout:${values.timeout}`,
		"Error: Timeout must be non-negative",
	)) return;
	if (!addNonNegative(
		"proportionalGain",
		`set_proportional_gain:${values.proportionalGain}`,
		"Error: Proportional gain must be non-negative",
	)) return;
	if (!addNonNegative(
		"integralGain",
		`set_integral_gain:${values.integralGain}`,
		"Error: Integral gain must be non-negative",
	)) return;
	if (!addNonNegative(
		"derivativeGain",
		`set_derivative_gain:${values.derivativeGain}`,
		"Error: Derivative gain must be non-negative",
	)) return;

	if (commands.length === 0) {
		addLogEntry("No parameter changes detected", "status");
		return;
	}

	for (const item of commands) {
		try {
			addLogEntry(`Sending command: ${item.command}`, "sent");
			const response = await sendCommandToServer(item.command);
			addLogEntry(`Server response: ${response}`, "received");
			lastSentValues[item.type] = values[item.type];
		} catch (error) {
			addLogEntry(`Error sending ${item.type}: ${error.message}`, "received");
		}
	}
}

async function setChannel(checkboxId, commandName, setPending, label) {
	const checkbox = document.getElementById(checkboxId);
	const value = checkbox.checked ? 1 : 0;
	const command = `${commandName}:${value}`;

	try {
		setPending(true);
		addLogEntry(`Sending ${label} command: ${command}`, "sent");
		const response = await sendCommandToServer(command);
		addLogEntry(`Server response: ${response}`, "received");
	} catch (error) {
		checkbox.checked = !checkbox.checked;
		setPending(false);
		addLogEntry(`Error sending ${commandName}: ${error.message}`, "received");
		console.error(error);
	}
}

async function toggleChannel50K() {
	await setChannel("toggle50KGlobal", "set_channel_50k", (value) => { pending50KToggle = value; }, "50K");
}

async function toggleChannelMXC() {
	await setChannel("toggleMXCGlobal", "set_channel_mxc", (value) => { pendingMXCToggle = value; }, "MXC");
}

async function toggleChannelSTILL() {
	await setChannel("toggleSTILLGlobal", "set_channel_still", (value) => { pendingSTILLToggle = value; }, "STILL");
}

async function toggleChannel4k() {
	await setChannel("toggle4kGlobal", "set_channel_4k", (value) => { pending4KToggle = value; }, "4K");
}

async function toggleAutorangeMXC() {
	const checkbox = document.getElementById("autorangeMXC");
	if (tcpConnectionStatus === false) {
		addLogEntry("Cannot send MXC command: No connection to TCP server", "status");
		checkbox.checked = !checkbox.checked;
		return;
	}

	try {
		const command = `set_autorange_mxc:${checkbox.checked ? 1 : 0}`;
		addLogEntry(`Sending MXC autorange command: ${command}`, "sent");
		const response = await sendCommandToServer(command);
		addLogEntry(`Server response: ${response}`, "received");
	} catch (error) {
		checkbox.checked = !checkbox.checked;
		addLogEntry(`Error sending autorange MXC: ${error.message}`, "received");
	}
}

async function toggleAutoscan() {
	const checkbox = document.getElementById("autoscanToggle");
	const desiredState = checkbox.checked;
	if (tcpConnectionStatus === false) {
		addLogEntry("Cannot send Autoscan command: No connection to TCP server", "status");
		checkbox.checked = !desiredState;
		return;
	}

	pendingAutoscanToggle = true;
	try {
		const command = `set_autoscan:${desiredState ? "on" : "off"}`;
		addLogEntry(`Sending Autoscan command: ${command}`, "sent");
		const response = await sendCommandToServer(command);
		addLogEntry(`Server response: ${response}`, "received");
	} catch (error) {
		checkbox.checked = !desiredState;
		pendingAutoscanToggle = false;
		addLogEntry(`Error sending Autoscan command: ${error.message}`, "received");
	}
}

async function resetDefaults(channel, command) {
	if (tcpConnectionStatus === false) {
		addLogEntry(`Cannot reset ${channel} to default: No connection to TCP server`, "status");
		return;
	}
	try {
		addLogEntry(`Sending ${channel} reset command: ${command}`, "sent");
		const response = await sendCommandToServer(command);
		addLogEntry(`Server response: ${response}`, "received");
		await sleep(1000);
		await fetchSensorData(true);
	} catch (error) {
		addLogEntry(`Error sending ${channel} reset command: ${error.message}`, "received");
	}
}

async function resetDefaultsMXC() { await resetDefaults("MXC", "reset_defaults_mxc"); }
async function resetDefaults50K() { await resetDefaults("50K", "reset_defaults_50k"); }
async function resetDefaults4K() { await resetDefaults("4K", "reset_defaults_4k"); }
async function resetDefaultsSTILL() { await resetDefaults("STILL", "reset_defaults_still"); }

async function writeSensorSettingsMXC() {
	if (tcpConnectionStatus === false) {
		addLogEntry("Cannot send MXC command: No connection to TCP server", "status");
		return;
	}

	const values = {
		dwellMXC: parseFloat(document.getElementById("dwellMXC").value),
		pauseMXC: parseFloat(document.getElementById("pauseMXC").value),
		rangeMXC: parseInt(document.getElementById("sensorRangeMXC").value, 10),
		modeMXC: parseInt(document.getElementById("sensorModeMXC").value, 10),
		curveMXC: parseInt(document.getElementById("curveMXCSelect").value, 10),
	};
	const commands = [];
	if (!Number.isNaN(values.dwellMXC)) {
		if (values.dwellMXC < 0 || values.dwellMXC > 10) return addLogEntry("Error: Dwell time must be between 0.0 and 10.0", "received");
		commands.push({ type: "dwellMXC", command: `set_dwell_mxc:${values.dwellMXC}` });
	}
	if (!Number.isNaN(values.pauseMXC)) {
		if (values.pauseMXC < 0 || values.pauseMXC > 10) return addLogEntry("Error: Pause time must be between 0.0 and 10.0", "received");
		commands.push({ type: "pauseMXC", command: `set_pause_mxc:${values.pauseMXC}` });
	}
	if (!Number.isNaN(values.rangeMXC)) {
		if (values.rangeMXC < 1 || values.rangeMXC > 8) return addLogEntry("Error: Sensor Range (Excitation) must be between 1 and 8", "received");
		commands.push({ type: "rangeMXC", command: `set_sensor_range_mxc:${values.rangeMXC}` });
	}
	if (!Number.isNaN(values.modeMXC)) {
		if (values.modeMXC !== 0 && values.modeMXC !== 1) return addLogEntry("Error: Sensor Mode must be 0 (Voltage) or 1 (Current)", "received");
		commands.push({ type: "modeMXC", command: `set_sensor_mode_mxc:${values.modeMXC}` });
	}
	if (!Number.isNaN(values.curveMXC)) {
		if (values.curveMXC < 0 || values.curveMXC > 20) return addLogEntry("Error: Curve number must be between 0 and 20", "received");
		commands.push({ type: "curveMXC", command: `set_curve_mxc:${values.curveMXC}` });
	}
	await sendProgressCommands(commands, "MXC sensor", values, "progressContainerMXC", "progressBarMXC", "progressTextMXC");
}

async function writeControlSettingsMXC() {
	if (tcpConnectionStatus === false) {
		addLogEntry("Cannot send MXC command: No connection to TCP server", "status");
		return;
	}

	const values = {
		MXCSP: parseFloat(document.getElementById("temperatureSetpointMXC").value),
		MXCP: parseFloat(document.getElementById("proportionalGainMXC").value),
		MXCI: parseFloat(document.getElementById("integralGainMXC").value),
		MXCD: parseFloat(document.getElementById("derivativeGainMXC").value),
		MXCHR: parseFloat(document.getElementById("heaterRangeMXC").value),
	};
	const limits = { MXCSP: [0, 500], MXCP: [0, 10], MXCI: [0, 10], MXCD: [0, 100], MXCHR: [0, 8] };
	const commands = [];
	const commandNames = {
		MXCSP: "set_mxc_temperature_setpoint",
		MXCP: "set_mxc_proportional_gain",
		MXCI: "set_mxc_integral_gain",
		MXCD: "set_mxc_derivative_gain",
		MXCHR: "set_mxc_heater_range",
	};

	for (const [type, value] of Object.entries(values)) {
		if (Number.isNaN(value)) continue;
		const [min, max] = limits[type];
		if (value < min || value > max) {
			addLogEntry(`Error: ${type} must be between ${min} and ${max}`, "received");
			return;
		}
		commands.push({ type, command: `${commandNames[type]}:${value}` });
	}
	await sendProgressCommands(commands, "MXC", values, "progressContainerMXC", "progressBarMXC", "progressTextMXC");
}

async function sendProgressCommands(commands, label, values, containerId, barId, textId) {
	if (commands.length === 0) {
		addLogEntry(`No ${label} settings changes detected`, "status");
		return;
	}
	const container = document.getElementById(containerId);
	const bar = document.getElementById(barId);
	const text = document.getElementById(textId);
	if (container) container.style.display = "block";
	if (bar) bar.style.width = "0%";

	for (let i = 0; i < commands.length; i++) {
		const item = commands[i];
		try {
			addLogEntry(`Sending ${label} command: ${item.command}`, "sent");
			const response = await sendCommandToServer(item.command);
			addLogEntry(`Server response: ${response}`, "received");
			if (values && item.type) lastSentValues[item.type] = values[item.type];
		} catch (error) {
			addLogEntry(`Error sending ${item.type || label}: ${error.message}`, "received");
		}
		const progress = ((i + 1) / commands.length) * 100;
		if (bar) bar.style.width = `${progress}%`;
		if (text) text.textContent = `Processing ${label} settings... ${Math.round(progress)}%`;
		await sleep(150);
	}
	setTimeout(() => { if (container) container.style.display = "none"; }, 1000);
}

async function writeSettingsForStage(stage, suffix, label) {
	if (tcpConnectionStatus === false) {
		addLogEntry(`Cannot send ${label} command: No connection to TCP server`, "status");
		return;
	}
	const dwell = parseFloat(document.getElementById(`dwell${stage}`).value);
	const pause = parseFloat(document.getElementById(`pause${stage}`).value);
	const range = parseInt(document.getElementById(`sensorRange${stage}`).value, 10);
	const mode = parseInt(document.getElementById(`sensorMode${stage}`).value, 10);
	const curve = parseInt(document.getElementById(`curve${stage}Select`).value, 10);
	const commands = [];
	const addValue = (value, min, max, message, command) => {
		if (Number.isNaN(value)) return true;
		if (value < min || value > max) {
			addLogEntry(message, "received");
			return false;
		}
		commands.push(command(value));
		return true;
	};
	if (!addValue(dwell, 0, 10, `Error: ${label} dwell time must be between 0.0 and 10.0`, (value) => `set_dwell_${suffix}:${value}`)) return;
	if (!addValue(pause, 0, 10, `Error: ${label} pause time must be between 0.0 and 10.0`, (value) => `set_pause_${suffix}:${value}`)) return;
	if (!addValue(range, 1, 8, `Error: ${label} Sensor Range must be between 1 and 8`, (value) => `set_sensor_range_${suffix}:${value}`)) return;
	if (!addValue(mode, 0, 1, `Error: ${label} Sensor Mode must be 0 (Voltage) or 1 (Current)`, (value) => `set_sensor_mode_${suffix}:${value}`)) return;
	if (!addValue(curve, 0, 20, `Error: ${label} Curve must be between 0 and 20`, (value) => `set_curve_${suffix}:${value}`)) return;
	await sendProgressCommands(commands.map((command) => ({ command })), label, null, `progressContainer${stage}`, `progressBar${stage}`, `progressText${stage}`);
}

async function writeSettingsSTILL() { await writeSettingsForStage("STILL", "still", "STILL"); }
async function writeSettings50K() { await writeSettingsForStage("50K", "50k", "50K"); }
async function writeSettings4K() { await writeSettingsForStage("4K", "4k", "4K"); }

function getSelectedExtraChannel() {
	const select = document.getElementById("relationChannelSelect");
	if (!select) return null;
	const channel = parseInt(String(select.value).replace("CH", ""), 10);
	return Number.isFinite(channel) ? channel : null;
}

async function writeSettingsExtraChannel() {
	if (tcpConnectionStatus === false) {
		addLogEntry("Cannot send Extra channel command: No connection to TCP server", "status");
		return;
	}
	const channel = getSelectedExtraChannel();
	if (!channel || channel < 9 || channel > 15) {
		addLogEntry("Error: Extra channel must be CH9..CH15", "received");
		return;
	}

	const rangeElement = document.getElementById(`sensorRangeCH${channel}`);
	const modeElement = document.getElementById(`sensorModeCH${channel}`);
	const range = rangeElement ? parseInt(rangeElement.value, 10) : NaN;
	const mode = modeElement ? parseInt(modeElement.value, 10) : NaN;
	const commands = [];
	if (!Number.isNaN(range)) {
		if (range < 1 || range > 8) return addLogEntry("Error: Sensor Range must be between 1 and 8", "received");
		commands.push(`set_sensor_range_ch${channel}:${range}`);
	}
	if (!Number.isNaN(mode)) {
		if (mode !== 0 && mode !== 1) return addLogEntry("Error: Sensor Mode must be 0 (Voltage) or 1 (Current)", "received");
		commands.push(`set_sensor_mode_ch${channel}:${mode}`);
	}
	const containerId = `progressContainerCH${channel}`;
	const hasLocalProgress = document.getElementById(containerId);
	await sendProgressCommands(
		commands.map((command) => ({ command })),
		`CH${channel}`,
		null,
		hasLocalProgress ? containerId : "progressContainerEXTRA",
		hasLocalProgress ? `progressBarCH${channel}` : "progressBarEXTRA",
		hasLocalProgress ? `progressTextCH${channel}` : "progressTextEXTRA",
	);
}

for (const channel of [9, 10, 11, 12, 13, 14, 15]) {
	window[`writeSettingsExtraChannel${channel}`] = async () => {
		document.getElementById("relationChannelSelect").value = `CH${channel}`;
		await writeSettingsExtraChannel();
	};
}

function globalToggleChannel(channel) {
	switch (channel) {
		case "MXC": return toggleChannelMXC();
		case "50K": return toggleChannel50K();
		case "4K": return toggleChannel4k();
		case "STILL": return toggleChannelSTILL();
		default: {
			const match = String(channel).match(/^(?:CH)?(9|10|11|12|13|14|15)$/);
			if (match) return toggleSampleChannelGlobal(parseInt(match[1], 10));
			console.warn("Unknown channel in globalToggleChannel:", channel);
		}
	}
}

function toggleSampleChannelGlobal(channel) {
	const checkbox = document.getElementById(`toggleExtraChannel${channel}`);
	if (!checkbox) return;

	const command = `set_channel_${channel}: ${checkbox.checked ? 1 : 0}`;
	pendingExtraChannels[channel] = true;
	addLogEntry(`Sending command: ${command}`, "sent");

	fetch("/send-command", {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ command }),
	})
		.then((response) => response.json())
		.then((data) => addLogEntry(`Server response: ${data.status}`, "received"))
		.catch((error) => {
			console.error("❌ Error:", error);
			checkbox.checked = !checkbox.checked;
			pendingExtraChannels[channel] = false;
		});
}