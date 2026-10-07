function initParticles() {
	const canvas = document.getElementById("particles-canvas");
	if (!canvas) return;

	const context = canvas.getContext("2d");
	let particles = [];
	let animationFrameId;

	function resizeCanvas() {
		canvas.width = window.innerWidth;
		canvas.height = window.innerHeight;
		if (particles.length === 0) createParticles();
	}

	function createParticles() {
		particles = [];
		const particleCount = Math.min(
			100,
			Math.floor((canvas.width * canvas.height) / 15000),
		);

		for (let index = 0; index < particleCount; index++) {
			particles.push({
				x: Math.random() * canvas.width,
				y: Math.random() * canvas.height,
				radius: Math.random() * 2.5 + 1,
				vx: Math.random() * 0.4 - 0.2,
				vy: Math.random() * 0.4 - 0.2,
			});
		}
	}

	function draw() {
		context.clearRect(0, 0, canvas.width, canvas.height);

		const particleColor = "rgba(255, 0, 127, 0.8)";
		const lineColor = "rgba(255, 0, 127, 0.15)";

		for (let index = 0; index < particles.length; index++) {
			const particle = particles[index];

			for (let otherIndex = index + 1; otherIndex < particles.length; otherIndex++) {
				const otherParticle = particles[otherIndex];
				const distance = Math.sqrt(
					Math.pow(particle.x - otherParticle.x, 2)
						+ Math.pow(particle.y - otherParticle.y, 2),
				);

				if (distance < 100) {
					context.beginPath();
					context.moveTo(particle.x, particle.y);
					context.lineTo(otherParticle.x, otherParticle.y);
					const opacity = 1 - distance / 100;
					context.strokeStyle = lineColor.replace(
						"0.1",
						(opacity * 0.2).toFixed(2),
					);
					context.lineWidth = 0.5;
					context.stroke();
				}
			}

			particle.x += particle.vx;
			particle.y += particle.vy;

			if (particle.x < 0 || particle.x > canvas.width) particle.vx *= -1;
			if (particle.y < 0 || particle.y > canvas.height) particle.vy *= -1;

			context.beginPath();
			context.arc(
				particle.x,
				particle.y,
				particle.radius,
				0,
				Math.PI * 2,
				false,
			);
			context.fillStyle = particleColor;
			context.fill();
		}

		animationFrameId = requestAnimationFrame(draw);
	}

	window.addEventListener("resize", resizeCanvas);
	resizeCanvas();

	if (animationFrameId) cancelAnimationFrame(animationFrameId);
	animationFrameId = requestAnimationFrame(draw);
}

document.addEventListener("DOMContentLoaded", initParticles);