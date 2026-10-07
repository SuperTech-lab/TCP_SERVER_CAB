// js/api.js
async function sendCommandToServer(command) {
  const response = await fetch("/send-command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command }),
  });
  const result = await response.json();

  if (tcpConnectionStatus === false) {
    tcpConnectionStatus = true;
    addLogEntry("Reconnected to TCP server", "status");
  }
  return result.status;
}

async function checkConnectionStatus() {
  try {
    const response = await fetch("/get-data");
    return response.ok;
  } catch (error) {
    return false;
  }
}

async function updateConnectionStatus() {
  const newStatus = await checkConnectionStatus();
  if (tcpConnectionStatus === null) {
    tcpConnectionStatus = newStatus;
    addLogEntry(tcpConnectionStatus ? "HTTP server is connected to TCP server" : "HTTP server is NOT connected to TCP server", "status");
  } else if (newStatus !== tcpConnectionStatus) {
    tcpConnectionStatus = newStatus;
    addLogEntry(tcpConnectionStatus ? "Reconnected to TCP server" : "Lost connection to TCP server", "status");
  }
  return tcpConnectionStatus;
}