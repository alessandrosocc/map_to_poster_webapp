const form = document.querySelector("#poster-form");
const themeGrid = document.querySelector("#theme-grid");
const distanceInput = form.elements.distance;
const distanceValue = document.querySelector("#distance-value");
const resetDistanceButton = document.querySelector("#reset-distance");
const statusText = document.querySelector("#status");
const downloadArea = document.querySelector("#download-area");
const posterStage = document.querySelector(".poster-stage");
const preview = document.querySelector("#poster-preview");
const previewLines = document.querySelector(".map-lines");
const previewCity = document.querySelector("#preview-city");
const previewCountry = document.querySelector("#preview-country");
const previewLoading = document.querySelector("#preview-loading");
const formatInput = form.elements.format;
const formatButtons = document.querySelectorAll(".format-option");
const sizeButtons = document.querySelectorAll(".size-option");
const tooltipPopover = document.querySelector("#tooltip-popover");

let selectedTheme = "terracotta";
let themes = [];
let pollTimer = null;
let generationDebounceTimer = null;
let activeJobToken = 0;
const FORM_PREVIEW_DELAY = 900;
const THEME_PREVIEW_DELAY = 350;
const DEFAULT_DISTANCE = 18000;

const cityNotFoundMessage = () => {
  const city = form.elements.city.value.trim() || "this city";
  const country = form.elements.country.value.trim();
  const place = country ? `${city}, ${country}` : city;
  return `I could not find ${place}. Check the city name or enter latitude and longitude.`;
};

const setStatus = (message) => {
  statusText.textContent = message;
};

const displayError = (message) => {
  const text = String(message || "Error");
  if (
    text.includes("Could not find coordinates")
    || text.includes("Geocoding failed")
    || text.includes("Could not locate")
  ) {
    setStatus(cityNotFoundMessage());
    return;
  }
  setStatus(text);
};

const setPreviewLoading = (isLoading) => {
  if (!previewLoading) return;
  previewLoading.hidden = !isLoading;
};

const hideTooltip = () => {
  if (!tooltipPopover) return;
  tooltipPopover.hidden = true;
};

const showTooltip = (target) => {
  if (!tooltipPopover) return;
  const text = target.dataset.tooltip;
  if (!text) return;

  tooltipPopover.textContent = text;
  tooltipPopover.hidden = false;

  const targetRect = target.getBoundingClientRect();
  const tooltipRect = tooltipPopover.getBoundingClientRect();
  const gap = 8;
  const maxLeft = window.innerWidth - tooltipRect.width - 12;
  const left = Math.max(12, Math.min(maxLeft, targetRect.left + targetRect.width / 2 - tooltipRect.width / 2));
  let top = targetRect.bottom + gap;

  if (top + tooltipRect.height > window.innerHeight - 12) {
    top = Math.max(12, targetRect.top - tooltipRect.height - gap);
  }

  tooltipPopover.style.left = `${left}px`;
  tooltipPopover.style.top = `${top}px`;
};

const spacedLatin = (value) => {
  const clean = value.trim();
  if (!clean) return "";
  return /^[\u0000-\u024f\s'-]+$/.test(clean) ? clean.toUpperCase().split("").join("  ") : clean;
};

const updatePreviewText = () => {
  const city = form.elements.displayCity.value || form.elements.city.value || "New York";
  const country = form.elements.displayCountry.value || form.elements.countryLabel.value || form.elements.country.value || "USA";
  previewCity.textContent = spacedLatin(city);
  previewCountry.textContent = country.toUpperCase();
};

const restoreMockPreview = () => {
  preview.classList.remove("has-file");
  preview.querySelectorAll(".generated-preview").forEach((node) => node.remove());
};

const applyThemePreview = (theme) => {
  if (!theme) return;
  const colors = theme.colors;
  restoreMockPreview();
  if (posterStage) {
    posterStage.style.setProperty("--stage-bg", colors.bg);
    posterStage.style.setProperty("--stage-road", colors.road);
    posterStage.style.setProperty("--stage-water", colors.water);
    posterStage.style.setProperty("--stage-parks", colors.parks);
    posterStage.style.setProperty("--stage-text", colors.text);
  }
  preview.style.background = colors.bg;
  preview.style.color = colors.text;
  previewLines.style.color = colors.road;
  preview.style.setProperty("--poster-bg", colors.bg);
};

const themeCard = (theme) => {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `theme-card${theme.id === selectedTheme ? " selected" : ""}`;
  button.dataset.theme = theme.id;
  button.innerHTML = `
    <span
      class="theme-mini-preview"
      style="
        --theme-bg:${theme.colors.bg};
        --theme-road:${theme.colors.road};
        --theme-water:${theme.colors.water};
        --theme-parks:${theme.colors.parks};
        --theme-text:${theme.colors.text};
      "
      aria-hidden="true"
    >
      <i class="theme-water"></i>
      <i class="theme-parks"></i>
      <i class="theme-roads"></i>
      <i class="theme-label"></i>
    </span>
    <strong>${theme.name}</strong>
    <small>${theme.description}</small>
  `;
  button.addEventListener("click", () => {
    selectedTheme = theme.id;
    document.querySelectorAll(".theme-card").forEach((card) => card.classList.remove("selected"));
    button.classList.add("selected");
    applyThemePreview(theme);
    scheduleGeneration({ previewOnly: true, delay: THEME_PREVIEW_DELAY });
  });
  return button;
};

const loadThemes = async () => {
  const response = await fetch("/api/themes");
  const payload = await response.json();
  themes = payload.themes;
  themeGrid.replaceChildren(...themes.map(themeCard));
  applyThemePreview(themes.find((theme) => theme.id === selectedTheme) || themes[0]);
};

const formPayload = (overrides = {}) => ({
  city: form.elements.city.value,
  country: form.elements.country.value,
  latitude: form.elements.latitude.value,
  longitude: form.elements.longitude.value,
  countryLabel: form.elements.countryLabel.value,
  displayCity: form.elements.displayCity.value,
  displayCountry: form.elements.displayCountry.value,
  fontFamily: form.elements.fontFamily.value,
  theme: selectedTheme,
  allThemes: form.elements.allThemes.checked,
  distance: Number(form.elements.distance.value),
  width: Number(form.elements.width.value),
  height: Number(form.elements.height.value),
  format: form.elements.format.value,
  ...overrides,
});

const outputImageCount = () => (form.elements.allThemes.checked ? themes.length : 1);

const renderDownloads = (job) => {
  downloadArea.replaceChildren();

  if (job.request?.previewOnly) {
    const finalButton = document.createElement("button");
    finalButton.type = "button";
    finalButton.className = "download-action";
    finalButton.textContent = form.elements.allThemes.checked
      ? `Generate ZIP ${formatInput.value.toUpperCase()} (${outputImageCount()} images)`
      : `Download final ${formatInput.value.toUpperCase()}`;
    finalButton.addEventListener("click", () => startGeneration({ previewOnly: false, keepPreview: true }));
    downloadArea.append(finalButton);
    return;
  }

  job.files.forEach((file) => {
    if (file.format === "png" || file.format === "svg") {
      const link = document.createElement("a");
      link.href = file.downloadUrl;
      link.download = file.name;
      const image = document.createElement("img");
      image.src = `${file.previewUrl}?t=${Date.now()}`;
      image.alt = file.name;
      link.append(image);
      downloadArea.append(link);
    }
  });

  if (job.archiveUrl) {
    const archive = document.createElement("a");
    archive.href = job.archiveUrl;
    archive.textContent = "Download ZIP";
    downloadArea.append(archive);
  } else if (job.files[0]) {
    const link = document.createElement("a");
    link.href = job.files[0].downloadUrl;
    link.textContent = "Download file";
    downloadArea.append(link);
  }
};

const renderMainPreview = (file) => {
  restoreMockPreview();
  if (!file) return;

  preview.classList.add("has-file");
  const source = `${file.previewUrl}?t=${Date.now()}`;
  let node;

  if (file.format === "pdf") {
    node = document.createElement("iframe");
    node.title = file.name;
    node.src = source;
  } else {
    node = document.createElement("img");
    node.alt = file.name;
    node.src = source;
  }

  node.className = "generated-preview";
  preview.append(node);
};

const pollJob = async (jobId, token) => {
  const response = await fetch(`/api/jobs/${jobId}`);
  const job = await response.json();
  if (token !== activeJobToken) return;
  if (job.error) {
    displayError(job.error);
  } else {
    setStatus(job.progress || job.status);
  }

  if (job.status === "done") {
    clearInterval(pollTimer);
    pollTimer = null;
    setPreviewLoading(false);
    renderMainPreview(job.files[0]);
    renderDownloads(job);
  }

  if (job.status === "error") {
    clearInterval(pollTimer);
    pollTimer = null;
    setPreviewLoading(false);
  }
};

const startGeneration = async ({ previewOnly = false, keepPreview = false } = {}) => {
  if (!form.elements.city.value.trim() || !form.elements.country.value.trim()) {
    setStatus("Fill in city and country");
    return;
  }

  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }

  const token = activeJobToken + 1;
  activeJobToken = token;
  downloadArea.replaceChildren();
  if (!keepPreview) {
    restoreMockPreview();
  }
  setPreviewLoading(previewOnly);
  if (previewOnly) {
    setStatus("Generating the preview above");
  } else if (form.elements.allThemes.checked) {
    setStatus(`Preparing ZIP: ${outputImageCount()} images to generate`);
  } else {
    setStatus("Preparing final file");
  }

  const payloadToSend = formPayload(previewOnly ? { allThemes: false, previewOnly: true } : {});
  const response = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payloadToSend),
  });
  const payload = await response.json();

  if (!response.ok) {
    if (token !== activeJobToken) return;
    displayError(payload.error || "Error");
    setPreviewLoading(false);
    return;
  }

  pollTimer = setInterval(() => pollJob(payload.jobId, token), 1200);
  pollJob(payload.jobId, token);
};

const scheduleGeneration = ({ previewOnly = false, delay = THEME_PREVIEW_DELAY } = {}) => {
  if (generationDebounceTimer) {
    clearTimeout(generationDebounceTimer);
  }
  if (previewOnly) {
    activeJobToken += 1;
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    downloadArea.replaceChildren();
    setPreviewLoading(false);
    setStatus("Preview update queued");
  }
  generationDebounceTimer = setTimeout(() => {
    generationDebounceTimer = null;
    startGeneration({ previewOnly });
  }, delay);
};

const scheduleFormPreview = () => {
  updatePreviewText();
  restoreMockPreview();
  scheduleGeneration({ previewOnly: true, delay: FORM_PREVIEW_DELAY });
};

distanceInput.addEventListener("input", () => {
  distanceValue.textContent = `${Number(distanceInput.value).toLocaleString("it-IT")} m`;
});

resetDistanceButton?.addEventListener("click", () => {
  distanceInput.value = String(DEFAULT_DISTANCE);
  distanceValue.textContent = `${DEFAULT_DISTANCE.toLocaleString("it-IT")} m`;
  scheduleFormPreview();
});

sizeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    form.elements.width.value = button.dataset.width;
    form.elements.height.value = button.dataset.height;
    sizeButtons.forEach((item) => item.classList.toggle("selected", item === button));
    scheduleFormPreview();
  });
});

formatButtons.forEach((button) => {
  button.addEventListener("click", () => {
    formatInput.value = button.dataset.format;
    formatButtons.forEach((item) => {
      const selected = item === button;
      item.classList.toggle("selected", selected);
      item.setAttribute("aria-pressed", String(selected));
    });
    scheduleFormPreview();
  });
});

document.querySelectorAll(".help-tip").forEach((button) => {
  button.addEventListener("mouseenter", () => showTooltip(button));
  button.addEventListener("focus", () => showTooltip(button));
  button.addEventListener("mouseleave", hideTooltip);
  button.addEventListener("blur", hideTooltip);
  button.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (tooltipPopover && !tooltipPopover.hidden && tooltipPopover.textContent === button.dataset.tooltip) {
      hideTooltip();
      return;
    }
    showTooltip(button);
  });
});

document.addEventListener("click", hideTooltip);
window.addEventListener("resize", hideTooltip);
document.querySelector(".controls")?.addEventListener("scroll", hideTooltip);

["input", "change"].forEach((eventName) => {
  form.addEventListener(eventName, scheduleFormPreview);
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  startGeneration();
});

distanceValue.textContent = `${Number(distanceInput.value).toLocaleString("it-IT")} m`;
updatePreviewText();
loadThemes()
  .then(() => scheduleGeneration({ previewOnly: true, delay: THEME_PREVIEW_DELAY }))
  .catch((error) => setStatus(error.message));
