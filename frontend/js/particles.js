export function initParticles() {
    const canvas = document.getElementById("particles-canvas");
    const ctx = canvas.getContext("2d");
    let particles = [];
    let animationFrameId;

    function resizeCanvas() {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
        // Re-initialize particles on resize to ensure distribution is correct
        if (particles.length === 0) {
        createParticles();
        }
    }

    function createParticles() {
        particles = [];
        // Asegura un número de partículas razonable (máx. 100)
        const numParticles = Math.min(
        100,
        Math.floor((canvas.width * canvas.height) / 15000),
        );
        for (let i = 0; i < numParticles; i++) {
        particles.push({
            x: Math.random() * canvas.width,
            y: Math.random() * canvas.height,
            radius: Math.random() * 2.5 + 1, // Radio entre 0.5 y 2.0
            vx: Math.random() * 0.4 - 0.2, // Velocidad X
            vy: Math.random() * 0.4 - 0.2, // Velocidad Y
        });
        }
    }

    function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Color de los elementos (negro o gris muy oscuro)
        const particleColor = "rgba(255, 0, 127, 0.8)"; // Gris oscuro
        const lineColor = "rgba(255, 0, 127, 0.15)"; // Líneas muy tenues

        for (let i = 0; i < particles.length; i++) {
        const p1 = particles[i];

        // 1. Dibujar líneas de conexión
        for (let j = i + 1; j < particles.length; j++) {
            const p2 = particles[j];
            const dist = Math.sqrt(
            Math.pow(p1.x - p2.x, 2) + Math.pow(p1.y - p2.y, 2),
            );

            // Conectar si la distancia es menor a 100px
            if (dist < 100) {
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);

            // Opacidad basada en la distancia (más cerca, más opaco)
            const opacity = 1 - dist / 100;
            ctx.strokeStyle = lineColor.replace(
                "0.1",
                (opacity * 0.2).toFixed(2),
            );
            ctx.lineWidth = 0.5;
            ctx.stroke();
            }
        }

        // 2. Mover la partícula
        p1.x += p1.vx;
        p1.y += p1.vy;

        // Rebotar en los bordes
        if (p1.x < 0 || p1.x > canvas.width) p1.vx *= -1;
        if (p1.y < 0 || p1.y > canvas.height) p1.vy *= -1;

        // 3. Dibujar la partícula (punto)
        ctx.beginPath();
        ctx.arc(p1.x, p1.y, p1.radius, 0, Math.PI * 2, false);
        ctx.fillStyle = particleColor;
        ctx.fill();
        }

        animationFrameId = requestAnimationFrame(draw);
    }

    // Initialization
    window.addEventListener("resize", resizeCanvas);
    resizeCanvas();

    // Start animation
    if (animationFrameId) cancelAnimationFrame(animationFrameId);
    animationFrameId = requestAnimationFrame(draw);
}