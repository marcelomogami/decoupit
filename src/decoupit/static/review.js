const player = document.querySelector("#player");
const status = document.querySelector("#status");
const framePosition = document.querySelector("#frame-position");
const timePosition = document.querySelector("#time-position");
const canvas = document.querySelector("#waveform");
const waveformMessage = document.querySelector("#waveform-message");
const transcript = document.querySelector("#transcript");
const transcriptMessage = document.querySelector("#transcript-message");
const transcriptLanguage = document.querySelector("#transcript-language");
const transcriptSearch = document.querySelector("#transcript-search");
const transcriptQuery = document.querySelector("#transcript-query");
const previousMatch = document.querySelector("#previous-match");
const nextMatch = document.querySelector("#next-match");
const matchCount = document.querySelector("#match-count");

const fps = Number(document.body.dataset.fps);
const frameCount = Number(document.body.dataset.frameCount);
const waveformUrl = document.body.dataset.waveformUrl;
const transcriptUrl = document.body.dataset.transcriptUrl;
let peaks = null;
let waveformBase = null;
let transcriptWords = [];
let activeWordIndex = -1;
let searchableTranscript = "";
let searchMatches = [];
let currentMatchIndex = -1;

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
  updateTranscript(seconds);
}

function wordAt(timeUs) {
  let lower = 0;
  let upper = transcriptWords.length - 1;
  let candidate = -1;
  while (lower <= upper) {
    const middle = Math.floor((lower + upper) / 2);
    if (transcriptWords[middle].startUs <= timeUs) {
      candidate = middle;
      lower = middle + 1;
    } else {
      upper = middle - 1;
    }
  }
  if (candidate >= 0 && timeUs < transcriptWords[candidate].endUs) {
    return candidate;
  }
  return -1;
}

function updateTranscript(seconds) {
  const nextWordIndex = wordAt(Math.round(Math.max(0, seconds) * 1000000));
  if (nextWordIndex === activeWordIndex) {
    return;
  }
  if (activeWordIndex >= 0) {
    transcriptWords[activeWordIndex].element.classList.remove("active");
  }
  activeWordIndex = nextWordIndex;
  if (activeWordIndex >= 0) {
    const element = transcriptWords[activeWordIndex].element;
    element.classList.add("active");
    element.scrollIntoView({ block: "nearest" });
  }
}

function normalizeSearchText(text) {
  return text
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLocaleLowerCase();
}

function updateMatchCount() {
  if (searchMatches.length === 0) {
    matchCount.textContent = transcriptQuery.value.trim() ? "Nenhum resultado" : "";
  } else if (currentMatchIndex < 0) {
    matchCount.textContent = `${searchMatches.length} resultado${searchMatches.length === 1 ? "" : "s"}`;
  } else {
    matchCount.textContent = `${currentMatchIndex + 1} de ${searchMatches.length}`;
  }
  previousMatch.disabled = searchMatches.length === 0;
  nextMatch.disabled = searchMatches.length === 0;
}

function clearSearchClasses() {
  for (const word of transcriptWords) {
    word.element.classList.remove("search-match", "search-current");
  }
}

function wordIndexesForSearchRange(start, end) {
  let lower = 0;
  let upper = transcriptWords.length - 1;
  let first = transcriptWords.length;
  while (lower <= upper) {
    const middle = Math.floor((lower + upper) / 2);
    if (transcriptWords[middle].searchEnd > start) {
      first = middle;
      upper = middle - 1;
    } else {
      lower = middle + 1;
    }
  }
  const indexes = [];
  for (
    let index = first;
    index < transcriptWords.length && transcriptWords[index].searchStart < end;
    index += 1
  ) {
    indexes.push(index);
  }
  return indexes;
}

function findSearchMatches() {
  clearSearchClasses();
  searchMatches = [];
  currentMatchIndex = -1;
  const query = normalizeSearchText(transcriptQuery.value.trim());
  if (!query) {
    updateMatchCount();
    return;
  }
  let position = 0;
  while ((position = searchableTranscript.indexOf(query, position)) >= 0) {
    const end = position + query.length;
    const wordIndexes = wordIndexesForSearchRange(position, end);
    if (wordIndexes.length > 0) {
      searchMatches.push({
        firstWordIndex: wordIndexes[0],
        lastWordIndex: wordIndexes[wordIndexes.length - 1],
      });
      for (const index of wordIndexes) {
        transcriptWords[index].element.classList.add("search-match");
      }
    }
    position = end;
  }
  updateMatchCount();
}

function selectSearchMatch(direction) {
  if (searchMatches.length === 0) {
    return;
  }
  if (currentMatchIndex >= 0) {
    const previous = searchMatches[currentMatchIndex];
    for (let index = previous.firstWordIndex; index <= previous.lastWordIndex; index += 1) {
      transcriptWords[index].element.classList.remove("search-current");
    }
  }
  currentMatchIndex =
    (currentMatchIndex + direction + searchMatches.length) % searchMatches.length;
  const match = searchMatches[currentMatchIndex];
  for (let index = match.firstWordIndex; index <= match.lastWordIndex; index += 1) {
    transcriptWords[index].element.classList.add("search-current");
  }
  const firstWord = transcriptWords[match.firstWordIndex];
  player.currentTime = firstWord.startUs / 1000000;
  firstWord.element.focus({ preventScroll: true });
  firstWord.element.scrollIntoView({ block: "nearest" });
  updatePosition(player.currentTime);
  updateMatchCount();
}

function renderTranscript(documentData) {
  transcript.replaceChildren();
  transcriptLanguage.textContent = documentData.language;
  transcriptWords = [];
  searchableTranscript = "";
  for (const segment of documentData.segments) {
    if (searchableTranscript) {
      searchableTranscript += " ";
    }
    const paragraph = document.createElement("p");
    paragraph.className = "transcript-segment";
    for (const word of segment.words) {
      const element = document.createElement("button");
      element.type = "button";
      element.className = "transcript-word";
      element.textContent = word.text;
      element.title = `Ir para ${formatTime(word.start_us / 1000000)}`;
      element.addEventListener("click", () => {
        player.currentTime = word.start_us / 1000000;
        updatePosition(player.currentTime);
      });
      paragraph.append(element);
      const normalizedText = normalizeSearchText(word.text);
      const searchStart = searchableTranscript.length;
      searchableTranscript += normalizedText;
      transcriptWords.push({
        startUs: word.start_us,
        endUs: word.end_us,
        element,
        searchStart,
        searchEnd: searchableTranscript.length,
      });
    }
    transcript.append(paragraph);
  }
  if (transcriptWords.length === 0) {
    const message = document.createElement("p");
    message.textContent = "Nenhuma fala foi detectada.";
    transcript.append(message);
  }
  activeWordIndex = -1;
  updateTranscript(player.currentTime);
  findSearchMatches();
}

transcriptQuery.addEventListener("input", findSearchMatches);
transcriptSearch.addEventListener("submit", (event) => {
  event.preventDefault();
  selectSearchMatch(1);
});
previousMatch.addEventListener("click", () => selectSearchMatch(-1));

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

if (transcriptUrl) {
  fetch(transcriptUrl)
    .then((response) => {
      if (!response.ok) {
        throw new Error("transcrição indisponível");
      }
      return response.json();
    })
    .then(renderTranscript)
    .catch(() => {
      transcriptMessage.textContent = "Não foi possível carregar a transcrição.";
    });
} else {
  transcriptMessage.textContent = "Transcrição ainda não disponível.";
}
