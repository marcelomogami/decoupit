const player = document.querySelector("#player");
const status = document.querySelector("#status");
const framePosition = document.querySelector("#frame-position");
const timePosition = document.querySelector("#time-position");
const canvas = document.querySelector("#waveform");
const waveformMessage = document.querySelector("#waveform-message");

const fps = Number(document.body.dataset.fps);
const frameCount = Number(document.body.dataset.frameCount);
const waveformUrl = document.body.dataset.waveformUrl;
let peaks = null;
let waveformBase = null;

function formatTime(seconds) {
  const milliseconds = Math.max(0, Math.floor(seconds * 1000));
  const hours = Math.floor(milliseconds / 3600000);
  const minutes = Math.floor((milliseconds % 3600000) / 60000);
  const wholeSeconds = Math.floor((milliseconds % 60000) / 1000);
  const remainder = milliseconds % 1000;
  return [hours, minutes, wholeSeconds]
    .map((value) => String(value).padStart(2, "0"))
    .join(":") + `.${String(remainder).padStart(3, "0")}`;
}

function frameAt(seconds) {
  const frame = Math.floor(Math.max(0, seconds) * fps + 1e-7);
  return Math.min(Math.max(0, frame), frameCount - 1);
}

function updatePosition(seconds = player.currentTime) {
  const frame = frameAt(seconds);
  framePosition.textContent = `Quadro ${frame} de ${frameCount - 1}`;
  timePosition.textContent = formatTime(seconds);
  canvas.setAttribute("aria-valuenow", String(frame));
  drawWaveform();
}

function renderWaveformBase() {
  if (!peaks || !player.duration) {
    return;
  }
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const pixelRatio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.floor(width * pixelRatio));
  canvas.height = Math.max(1, Math.floor(height * pixelRatio));
  waveformBase = document.createElement("canvas");
  waveformBase.width = canvas.width;
  waveformBase.height = canvas.height;
  const context = waveformBase.getContext("2d");
  context.scale(pixelRatio, pixelRatio);
  context.strokeStyle = "#7bb8f4";
  context.lineWidth = 1;
  context.beginPath();
  const center = height / 2;
  const amplitude = Math.max(1, center - 8);
  for (let x = 0; x < width; x += 1) {
    const start = Math.floor((x * peaks.length) / width);
    const end = Math.max(start + 1, Math.floor(((x + 1) * peaks.length) / width));
    let minimum = 0;
    let maximum = 0;
    for (let index = start; index < Math.min(end, peaks.length); index += 1) {
      minimum = Math.min(minimum, peaks[index][0]);
      maximum = Math.max(maximum, peaks[index][1]);
    }
    context.moveTo(x + 0.5, center - (maximum / 32768) * amplitude);
    context.lineTo(x + 0.5, center - (minimum / 32768) * amplitude);
  }
  context.stroke();
}

function drawWaveform() {
  if (!peaks || !player.duration) {
    return;
  }
  const pixelRatio = window.devicePixelRatio || 1;
  const targetWidth = Math.max(1, Math.floor(canvas.clientWidth * pixelRatio));
  const targetHeight = Math.max(1, Math.floor(canvas.clientHeight * pixelRatio));
  if (
    !waveformBase ||
    waveformBase.width !== targetWidth ||
    waveformBase.height !== targetHeight
  ) {
    renderWaveformBase();
  }
  const context = canvas.getContext("2d");
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.drawImage(waveformBase, 0, 0);
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const playhead = (player.currentTime / player.duration) * width;
  context.strokeStyle = "#ff5c70";
  context.lineWidth = 2;
  context.beginPath();
  context.moveTo(playhead, 0);
  context.lineTo(playhead, height);
  context.stroke();
}

function seekToRatio(ratio) {
  if (!player.duration) {
    return;
  }
  player.currentTime = Math.min(1, Math.max(0, ratio)) * player.duration;
  updatePosition();
}

canvas.addEventListener("pointerdown", (event) => {
  const bounds = canvas.getBoundingClientRect();
  seekToRatio((event.clientX - bounds.left) / bounds.width);
});

canvas.addEventListener("keydown", (event) => {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
    return;
  }
  event.preventDefault();
  const direction = event.key === "ArrowLeft" ? -1 : 1;
  const targetFrame = Math.min(
    frameCount - 1,
    Math.max(0, frameAt(player.currentTime) + direction),
  );
  player.currentTime = targetFrame / fps;
  updatePosition(player.currentTime);
});

player.addEventListener("loadedmetadata", () => {
  status.textContent = `Pronto · ${player.videoWidth}x${player.videoHeight}`;
  updatePosition();
});
player.addEventListener("seeked", () => updatePosition());
player.addEventListener("timeupdate", () => updatePosition());
player.addEventListener("error", () => {
  status.textContent = "O navegador não conseguiu reproduzir esta mídia.";
});
window.addEventListener("resize", () => {
  waveformBase = null;
  drawWaveform();
});

if ("requestVideoFrameCallback" in HTMLVideoElement.prototype) {
  const followVideoFrames = (_, metadata) => {
    updatePosition(metadata.mediaTime);
    player.requestVideoFrameCallback(followVideoFrames);
  };
  player.requestVideoFrameCallback(followVideoFrames);
}

if (waveformUrl) {
  fetch(waveformUrl)
    .then((response) => {
      if (!response.ok) {
        throw new Error("waveform indisponível");
      }
      return response.json();
    })
    .then((waveform) => {
      peaks = waveform.peaks;
      waveformMessage.hidden = true;
      canvas.hidden = false;
      drawWaveform();
    })
    .catch(() => {
      waveformMessage.textContent = "Não foi possível carregar o waveform.";
    });
} else {
  waveformMessage.textContent = "Waveform ainda não disponível.";
}
