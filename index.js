
function plotChart() {
    const ctx = document.getElementById('myChart');

    new Chart(ctx, {
    type: 'bar',
    data: {
        labels: ['Red', 'Blue', 'Yellow', 'Green', 'Purple', 'Orange'],
        datasets: [{
        label: '# of Votes',
        data: [12, 19, 3, 5, 2, 3],
        borderWidth: 1
        }]
    },
    options: {
        scales: {
        y: {
            beginAtZero: true
        }
        }
    }
    });
}

async function sendCommand() {
    const commandInput = document.getElementById('commandInput');
    const responseBox = document.getElementById('responseBox');

    const command = commandInput.value.trim();
    if (!command) {
        responseBox.textContent = "Please enter a command.";
        return;
    }

    try {
        const response = await fetch('/send-command', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ command }),
        });

        const result = await response.json();
        responseBox.textContent = result.status;
        plotChart();
    } catch (error) {
        responseBox.textContent = `Error: ${error.message}`;
    }
}
