// ==========================================================================
// 1. ПОЛУЧЕНИЕ ССЫЛОК НА DOM-ЭЛЕМЕНТЫ
// ==========================================================================
const form = document.querySelector("#analyze-form");
const fileInput = document.querySelector("#log-file");
const fileName = document.querySelector("#file-name");
const submitButton = document.querySelector("#submit-button");
const message = document.querySelector("#form-message");
const resultPanel = document.querySelector("#result-panel");
const resultContent = document.querySelector("#result-content");
const resultTime = document.querySelector("#result-time");
const proposeButton = document.querySelector("#propose-button");
const applyButton = document.querySelector("#apply-button");
const applyMessage = document.querySelector("#apply-message"); // Сообщение под кнопкой Применить
const proposalPanel = document.querySelector("#proposal-panel");
const proposalExplanation = document.querySelector("#proposal-explanation");
const proposalPath = document.querySelector("#proposal-path");
const oldText = document.querySelector("#old-text");
const newText = document.querySelector("#new-text");
const prDescription = document.querySelector("#pr-description");
const repoStatusButton = document.querySelector("#repo-status-button");
const ciScanButton = document.querySelector("#ci-scan-button");
const repoStatus = document.querySelector("#repo-status");
const ciMessage = document.querySelector("#ci-message");
const ciResults = document.querySelector("#ci-results");
const gitActions = document.querySelector("#git-actions");
const prButton = document.querySelector("#pr-button");
const prSuccessBanner = document.querySelector("#pr-success-banner");
const shareRefreshButton = document.querySelector("#share-refresh-button");
const sharePreprocessButton = document.querySelector("#share-preprocess-button");
const shareAnalyzeButton = document.querySelector("#share-analyze-button");
const shareFocus = document.querySelector("#share-focus");
const shareQuestion = document.querySelector("#share-question");
const shareFilesBox = document.querySelector("#share-files");
const shareMessage = document.querySelector("#share-message");
const shareRoot = document.querySelector("#share-root");
const shareResultPanel = document.querySelector("#share-result-panel");
const shareResultTitle = document.querySelector("#share-result-title");
const shareResult = document.querySelector("#share-result");
const shareResultSource = document.querySelector("#share-result-source");
const shareStats = document.querySelector("#share-stats");
const shareOverviewButton = document.querySelector("#share-overview-button");
const shareOverviewPreviewButton = document.querySelector("#share-overview-preview-button");
const shareOverviewAnalyzeButton = document.querySelector("#share-overview-analyze-button");
const shareOverviewLimit = document.querySelector("#share-overview-limit");
const shareOverviewMessage = document.querySelector("#share-overview-message");
const shareOverviewPanel = document.querySelector("#share-overview-panel");
const shareOverviewTitle = document.querySelector("#share-overview-title");
const shareOverviewStats = document.querySelector("#share-overview-stats");
const shareOverviewReport = document.querySelector("#share-overview-report");
const shareOverviewAnalysis = document.querySelector("#share-overview-analysis");
const shareOverviewDrilldown = document.querySelector("#share-overview-drilldown");

let currentProposal = null;
let selectedShareFile = null;
let currentOverview = null;
let overviewTimer = null;

// --- СОХРАНЕНИЕ ПУТИ РЕПОЗИТОРИЯ В LOCALSTORAGE ---
const repoPathInput = document.querySelector("#repo-path");
// Storage is optional: privacy settings must not disable the page's buttons.
try {
  repoPathInput.value = localStorage.getItem("directum_repo_path") || "";
} catch (error) {
  console.warn("Не удалось прочитать сохранённый путь репозитория.", error);
}
repoPathInput.addEventListener("input", () => {
  try {
    localStorage.setItem("directum_repo_path", repoPathInput.value.trim());
  } catch (error) {
    console.warn("Не удалось сохранить путь репозитория.", error);
  }
});

// ==========================================================================
// 2. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
// ==========================================================================
// Local-only rendering: model output is text, never executable HTML.
const hljs = { highlightAll() {} };
function renderMarkdown(text) {
    const node = document.createElement("pre");
    node.style.whiteSpace = "pre-wrap";
    node.style.font = "inherit";
    node.textContent = text || "";
    return node.outerHTML;
}

function setLoading(button, isLoading, loadingText = "") {
    const textSpan = button.querySelector("span:not(.spinner)");
    const spinner = button.querySelector(".spinner");
    
    if (isLoading) {
        button.disabled = true;
        if (textSpan) textSpan.textContent = loadingText;
        if (spinner) spinner.hidden = false;
    } else {
        button.disabled = false;
        if (textSpan) textSpan.textContent = button.dataset.originalText;
        if (spinner) spinner.hidden = true;
    }
}

[submitButton, proposeButton, ciScanButton, applyButton, prButton, shareRefreshButton, sharePreprocessButton, shareAnalyzeButton, shareOverviewButton, shareOverviewPreviewButton, shareOverviewAnalyzeButton].forEach(btn => {
    if (btn) {
        const textSpan = btn.querySelector("span:not(.spinner)");
        if (textSpan) {
            btn.dataset.originalText = textSpan.textContent.trim();
        } else {
            btn.dataset.originalText = btn.textContent.trim();
        }
    }
});

async function getRepositoryPath() {
  const repo = document.querySelector("#repo-path").value.trim();
  if (!repo) throw new Error("Укажите корень репозитория.");
  return repo;
}


function showProposal(payload) {
  currentProposal = payload;
  proposalExplanation.innerHTML = renderMarkdown(payload.explanation);
  proposalPath.textContent = `Файл: ${payload.path}`;
  oldText.textContent = payload.old_text;
  newText.innerHTML = renderMarkdown(payload.new_text);
  hljs.highlightAll();
  prDescription.value = payload.description || "Описание будет сформировано при создании Pull Request.";
  document.querySelector("#pr-title").value = `fix: ${payload.path}`;
  
  if (applyMessage) applyMessage.hidden = true;
  proposalPanel.hidden = false;
  resultPanel.hidden = false;
  proposalPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

// ==========================================================================
// 3.1. ЛОГИ ИЗ СЕТЕВОЙ ПАПКИ DIRECTUM
// ==========================================================================
function formatFileSize(bytes) {
  if (!Number.isFinite(bytes)) return "размер неизвестен";
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

function showShareMessage(text, isError = false) {
  shareMessage.textContent = text;
  shareMessage.style.color = isError ? "var(--gh-danger-fg)" : "var(--gh-fg-default)";
  shareMessage.hidden = !text;
}

function formatShareStats(stats) {
  if (!stats) return "";
  const parts = [];
  if (Number.isFinite(stats.size_bytes)) parts.push(formatFileSize(stats.size_bytes));
  if (Number.isFinite(stats.lines)) parts.push(`${stats.lines.toLocaleString("ru-RU")} строк`);
  const levels = stats.levels || {};
  const errors = (levels.error || 0) + (levels.fatal || 0);
  const warnings = levels.warn || 0;
  if (errors || warnings) parts.push(`Error/Fatal ${errors}`, `Warn ${warnings}`);
  if (Number.isFinite(stats.report_chars)) {
    parts.push(`выжимка ${stats.report_chars.toLocaleString("ru-RU")} симв.`);
  }
  if (stats.truncated) parts.push("сокращено по лимиту");
  return parts.join(" · ");
}

function showOverviewMessage(text, isError = false) {
  shareOverviewMessage.textContent = text;
  shareOverviewMessage.style.color = isError ? "var(--gh-danger-fg)" : "var(--gh-fg-default)";
  shareOverviewMessage.hidden = !text;
}

function formatOverviewStats(stats) {
  if (!stats) return "";
  const parts = [];
  if (Number.isFinite(stats.files_scanned)) {
    const selected = Number.isFinite(stats.files_selected) ? stats.files_selected : stats.files_scanned;
    parts.push(`${stats.files_scanned.toLocaleString("ru-RU")} из ${selected.toLocaleString("ru-RU")} файлов`);
  }
  if (Number.isFinite(stats.bytes_scanned)) parts.push(formatFileSize(stats.bytes_scanned));
  if (Number.isFinite(stats.lines)) parts.push(`${stats.lines.toLocaleString("ru-RU")} строк`);
  if (Number.isFinite(stats.error_events)) parts.push(`Error/Fatal ${stats.error_events.toLocaleString("ru-RU")}`);
  if (Number.isFinite(stats.warning_events)) parts.push(`Warn ${stats.warning_events.toLocaleString("ru-RU")}`);
  if (Number.isFinite(stats.duration_seconds)) parts.push(`${stats.duration_seconds} с`);
  if (stats.truncated) parts.push("охват ограничен");
  return parts.join(" · ");
}

function renderOverviewDrilldown(stats) {
  shareOverviewDrilldown.innerHTML = "";
  const files = (stats && stats.top_files) || [];
  if (!files.length) {
    shareOverviewDrilldown.hidden = true;
    return;
  }

  const title = document.createElement("h3");
  title.className = "text-lg font-semibold mb-3";
  title.textContent = "Файлы с наибольшим числом проблем";
  const list = document.createElement("div");
  list.className = "share-drilldown-list";

  files.slice(0, 12).forEach((file) => {
    const row = document.createElement("div");
    row.className = "share-drilldown-row";

    const text = document.createElement("div");
    text.className = "share-drilldown-text";

    const path = document.createElement("span");
    path.className = "share-drilldown-path";
    path.textContent = file.path;

    const meta = document.createElement("span");
    meta.className = "share-drilldown-meta";
    const parts = [
      `Error/Fatal ${(file.errors || 0) + (file.fatal || 0)}`,
      `Warn ${file.warnings || 0}`,
      `${(file.lines || 0).toLocaleString("ru-RU")} строк`,
    ];
    if (file.top_error) parts.push(`топ: ${file.top_error}`);
    meta.textContent = parts.join(" · ");
    text.append(path, meta);

    const button = document.createElement("button");
    button.className = "gh-btn";
    button.type = "button";
    button.innerHTML = '<span>Детальный анализ</span><span class="spinner" hidden></span>';
    button.dataset.originalText = "Детальный анализ";
    button.addEventListener("click", () => {
      analyzeShareFile(file.path, shareQuestion.value.trim(), button);
    });

    row.append(text, button);
    list.appendChild(row);
  });

  shareOverviewDrilldown.append(title, list);
  shareOverviewDrilldown.hidden = false;
}

function renderShareFiles(files) {
  shareFilesBox.innerHTML = "";
  selectedShareFile = null;
  sharePreprocessButton.disabled = true;
  shareAnalyzeButton.disabled = true;
  shareResultPanel.hidden = true;
  shareStats.hidden = true;
  shareStats.textContent = "";

  if (!files.length) {
    shareFilesBox.hidden = true;
    return;
  }

  files.forEach((file) => {
    const row = document.createElement("div");
    row.className = "share-file-row";

    const label = document.createElement("label");
    label.className = "share-file-info";

    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "share-file";
    radio.value = file.path;
    radio.addEventListener("change", () => {
      selectedShareFile = file.path;
      sharePreprocessButton.disabled = false;
      shareAnalyzeButton.disabled = false;
    });

    const text = document.createElement("span");
    text.className = "share-file-text";

    const name = document.createElement("span");
    name.className = "share-file-name";
    name.textContent = file.path;

    const meta = document.createElement("span");
    meta.className = "share-file-meta";
    meta.textContent = `${formatFileSize(file.size)} · ${file.modified || "дата неизвестна"}`;

    text.append(name, meta);
    label.append(radio, text);

    const download = document.createElement("a");
    download.className = "gh-link text-sm";
    download.href = `/logs/share/file?name=${encodeURIComponent(file.path)}`;
    download.textContent = "Скачать";

    row.append(label, download);
    shareFilesBox.appendChild(row);
  });

  shareFilesBox.hidden = false;
}

async function refreshShareLogs() {
  setLoading(shareRefreshButton, true, "Читаем папку...");
  showShareMessage("");
  try {
    const response = await fetch("/logs/share/files?limit=200");
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Не удалось прочитать сетевую папку.");
    if (payload.root) shareRoot.textContent = payload.root;
    renderShareFiles(payload.files || []);
    if (payload.count) {
      showShareMessage(`Найдено файлов: ${payload.count}`);
    } else {
      showShareMessage("В папке нет файлов .json, .log или .txt.", true);
    }
  } catch (error) {
    shareFilesBox.hidden = true;
    showShareMessage(error.message || "Не удалось прочитать сетевую папку.", true);
  } finally {
    setLoading(shareRefreshButton, false);
  }
}

async function analyzeShareFile(name, question = "", triggerButton = shareAnalyzeButton) {
  if (!name) return;
  setLoading(triggerButton, true, "Анализируем...");
  showShareMessage("");
  shareResultPanel.hidden = true;

  try {
    const repo = document.querySelector("#repo-path").value.trim();
    const params = new URLSearchParams({
      name,
      focus: shareFocus.value,
    });
    if (repo) params.set("repo", repo);
    if (question) params.set("question", question);

    const response = await fetch(`/logs/share/analyze?${params.toString()}`, { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Не удалось проанализировать лог.");

    selectedShareFile = name;
    document.querySelectorAll('input[name="share-file"]').forEach((input) => {
      input.checked = input.value === name;
    });
    sharePreprocessButton.disabled = false;
    shareAnalyzeButton.disabled = false;

    shareResultTitle.textContent = question ? "Ответ по логу" : "Результат анализа";
    shareResult.innerHTML = renderMarkdown(payload.result);
    shareResultSource.textContent = `Файл: ${payload.source}`;
    shareResultSource.hidden = false;
    const statsText = formatShareStats(payload.stats);
    shareStats.textContent = statsText;
    shareStats.hidden = !statsText;
    shareResultPanel.hidden = false;
    shareResultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showShareMessage(error.message || "Не удалось проанализировать лог.", true);
  } finally {
    setLoading(triggerButton, false);
    if (triggerButton === shareAnalyzeButton) {
      shareAnalyzeButton.disabled = !selectedShareFile;
    }
  }
}

// ==========================================================================
// 4. ОБРАБОТЧИКИ СОБЫТИЙ
// ==========================================================================

fileInput.addEventListener("change", () => {
  fileName.textContent = fileInput.files[0]?.name || "Выберите файл или перетащите сюда";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  message.textContent = "";
  message.hidden = true;
  resultPanel.hidden = true;
  
  setLoading(submitButton, true, "Анализируем...");

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  const repo = document.querySelector("#repo-path").value.trim();
  const url = repo ? `/analyze?repo=${encodeURIComponent(repo)}` : "/analyze";

  try {
    const response = await fetch(url, { method: "POST", body: formData });
    const payload = await response.json();
    if (!response.ok) {
      const detail = typeof payload.detail === "string" ? payload.detail : "Проверьте файл и настройки сервера.";
      throw new Error(detail);
    }
    resultContent.innerHTML = renderMarkdown(payload.result);
    hljs.highlightAll();
    resultTime.textContent = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    resultPanel.hidden = false;
    proposalPanel.hidden = true;
    currentProposal = null;
    resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    message.textContent = error.message || "Не удалось выполнить анализ.";
    message.hidden = false;
  } finally {
    setLoading(submitButton, false);
  }
});

shareRefreshButton.addEventListener("click", refreshShareLogs);

sharePreprocessButton.addEventListener("click", async () => {
  if (!selectedShareFile) return;
  setLoading(sharePreprocessButton, true, "Готовим выжимку...");
  showShareMessage("");
  shareResultPanel.hidden = true;

  try {
    const params = new URLSearchParams({
      name: selectedShareFile,
      focus: shareFocus.value,
    });
    const response = await fetch(`/logs/share/preprocess?${params.toString()}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Не удалось подготовить выжимку.");

    shareResultTitle.textContent = "Выжимка лога";
    shareResult.innerHTML = renderMarkdown(payload.report);
    shareResultSource.textContent = `Файл: ${payload.source}`;
    shareResultSource.hidden = false;
    const statsText = formatShareStats(payload.stats);
    shareStats.textContent = statsText;
    shareStats.hidden = !statsText;
    shareResultPanel.hidden = false;
    shareResultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showShareMessage(error.message || "Не удалось подготовить выжимку.", true);
  } finally {
    setLoading(sharePreprocessButton, false);
    sharePreprocessButton.disabled = !selectedShareFile;
  }
});

shareAnalyzeButton.addEventListener("click", () => {
  if (!selectedShareFile) return;
  analyzeShareFile(selectedShareFile, shareQuestion.value.trim(), shareAnalyzeButton);
});

shareQuestion.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || !selectedShareFile) return;
  event.preventDefault();
  analyzeShareFile(selectedShareFile, shareQuestion.value.trim(), shareAnalyzeButton);
});

async function analyzeOverviewReport() {
  if (!currentOverview) return;
  setLoading(shareOverviewAnalyzeButton, true, "Анализируем сводку...");
  shareOverviewButton.disabled = true;
  shareOverviewPreviewButton.disabled = true;
  showOverviewMessage("");
  shareOverviewAnalysis.hidden = true;

  try {
    const repo = document.querySelector("#repo-path").value.trim();
    const url = repo
      ? `/logs/share/overview/analyze?repo=${encodeURIComponent(repo)}`
      : "/logs/share/overview/analyze";
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        report: currentOverview.report,
        stats: currentOverview.stats,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Не удалось проанализировать сводку.");

    shareOverviewAnalysis.innerHTML = renderMarkdown(payload.result);
    shareOverviewAnalysis.hidden = false;
    showOverviewMessage("Анализ сводки готов.", false);
    shareOverviewAnalysis.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showOverviewMessage(error.message || "Не удалось проанализировать сводку.", true);
  } finally {
    setLoading(shareOverviewAnalyzeButton, false);
    shareOverviewButton.disabled = false;
    shareOverviewPreviewButton.disabled = false;
    shareOverviewAnalyzeButton.disabled = !currentOverview;
  }
}

async function collectOverview(triggerButton, analyzeAfter) {
  setLoading(triggerButton, true, "Сканируем логи...");
  shareOverviewButton.disabled = true;
  shareOverviewPreviewButton.disabled = true;
  showOverviewMessage("Сканируем логи. Это может занять несколько минут.");
  shareOverviewPanel.hidden = true;
  shareOverviewAnalyzeButton.disabled = true;
  currentOverview = null;
  const started = Date.now();
  if (overviewTimer) clearInterval(overviewTimer);
  overviewTimer = setInterval(() => {
    const seconds = Math.round((Date.now() - started) / 1000);
    showOverviewMessage(`Сканируем логи… прошло ${seconds} с. Это может занять несколько минут.`);
  }, 1000);

  try {
    const params = new URLSearchParams({
      focus: shareFocus.value,
      limit: shareOverviewLimit.value,
    });
    const response = await fetch(`/logs/share/overview?${params.toString()}`, { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Не удалось собрать общую сводку.");

    currentOverview = payload;
    shareOverviewTitle.textContent = "Сводка по всем логам";
    shareOverviewReport.innerHTML = renderMarkdown(payload.report);
    const statsText = formatOverviewStats(payload.stats);
    shareOverviewStats.textContent = statsText;
    shareOverviewStats.hidden = !statsText;
    shareOverviewAnalysis.innerHTML = "";
    shareOverviewAnalysis.hidden = true;
    renderOverviewDrilldown(payload.stats);
    shareOverviewAnalyzeButton.disabled = false;
    shareOverviewPanel.hidden = false;
    showOverviewMessage(
      analyzeAfter
        ? "Сводка готова. Отправляем её модели..."
        : "Сводка готова. Проверьте её и при необходимости запустите анализ моделью.",
      false
    );
    shareOverviewPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    showOverviewMessage(error.message || "Не удалось собрать общую сводку.", true);
  } finally {
    if (overviewTimer) {
      clearInterval(overviewTimer);
      overviewTimer = null;
    }
    setLoading(triggerButton, false);
    shareOverviewButton.disabled = false;
    shareOverviewPreviewButton.disabled = false;
    shareOverviewAnalyzeButton.disabled = !currentOverview;
  }

  if (analyzeAfter && currentOverview) {
    await analyzeOverviewReport();
  }
}

shareOverviewButton.addEventListener("click", () => collectOverview(shareOverviewButton, true));
shareOverviewPreviewButton.addEventListener("click", () => collectOverview(shareOverviewPreviewButton, false));
shareOverviewAnalyzeButton.addEventListener("click", () => analyzeOverviewReport());

proposeButton.addEventListener("click", async () => {
  setLoading(proposeButton, true, "Ищем исправление...");
  
  const repo = document.querySelector("#repo-path").value.trim();
  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  
  try {
    const response = await fetch(`/propose-fix?repo=${encodeURIComponent(repo)}`, { method: "POST", body: formData });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Не удалось подготовить предложение.");
    showProposal(payload);
  } catch (error) {
    message.textContent = error.message;
    message.style.color = "var(--gh-danger-fg)";
    message.hidden = false;
  } finally {
    setLoading(proposeButton, false);
  }
});

applyButton.addEventListener("click", async () => {
  if (!currentProposal) return;
  setLoading(applyButton, true, "Применяем...");
  
  if (applyMessage) {
      applyMessage.hidden = true;
      applyMessage.textContent = "";
  }

  const repo = document.querySelector("#repo-path").value.trim();
  try {
    const response = await fetch(`/apply-fix?repo=${encodeURIComponent(repo)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...currentProposal, approved: true }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Изменение не применено.");
    
    if (applyMessage) {
        applyMessage.textContent = `${payload.message}: ${payload.path}`;
        applyMessage.style.color = "var(--gh-success-fg)";
        applyMessage.hidden = false;
    }
    gitActions.hidden = false;
  } catch (error) {
    if (applyMessage) {
        applyMessage.textContent = error.message;
        applyMessage.style.color = "var(--gh-danger-fg)";
        applyMessage.hidden = false;
    }
  } finally {
    setLoading(applyButton, false);
  }
});

repoStatusButton.addEventListener("click", async () => {
  setLoading(repoStatusButton, true, "Читаем Git...");
  ciMessage.hidden = true;
  try {
    const repo = await getRepositoryPath();
    const response = await fetch(`/repository/status?repo=${encodeURIComponent(repo)}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Не удалось прочитать Git.");
    
    repoStatus.textContent = `Ветка: ${payload.branch}\nRemote: ${payload.remote || "не настроен"}\nИзменения:\n${payload.changes.join("\n") || "нет"}`;
    repoStatus.hidden = false;
  } catch (error) {
    ciMessage.textContent = error.message;
    ciMessage.style.color = "var(--gh-danger-fg)";
    ciMessage.hidden = false;
  } finally {
    setLoading(repoStatusButton, false);
  }
});

ciScanButton.addEventListener("click", async () => {
  setLoading(ciScanButton, true, "Сканируем...");
  ciMessage.textContent = "";
  ciMessage.hidden = true;
  ciResults.hidden = true;
  
  try {
    const repo = await getRepositoryPath();
    const response = await fetch(`/ci/scan?repo=${encodeURIComponent(repo)}`, { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Не удалось проверить CI.");
    
    ciResults.innerHTML = "";
    if (payload.count) {
        ciMessage.textContent = `Найдено новых запусков: ${payload.count}`;
        ciMessage.style.color = "var(--gh-fg-default)";
        ciMessage.hidden = false;
    } else {
        ciMessage.textContent = "Новых failed workflow нет.";
        ciMessage.style.color = "var(--gh-success-fg)";
        ciMessage.hidden = false;
    }

    payload.results.forEach((item) => {
      const article = document.createElement("article");
      article.className = "ci-result";
      article.innerHTML = `<strong>${item.workflow || "CI"} · run ${item.run_id}</strong><a href="${item.url || "#"}" target="_blank" rel="noreferrer">Открыть workflow</a><p></p><button class="secondary-button ci-fix-button" type="button">Предложить исправление</button>`;
      article.querySelector("p").innerHTML = renderMarkdown(item.analysis);
      // Обновляем подсветку синтаксиса
      hljs.highlightAll();
      article.querySelector(".ci-fix-button").addEventListener("click", async () => {
        const button = article.querySelector(".ci-fix-button");
        button.disabled = true;
        ciMessage.textContent = "Готовим предложение по логам workflow...";
        ciMessage.style.color = "var(--gh-fg-default)";
        ciMessage.hidden = false;
        
        try {
          const repo = await getRepositoryPath();
          const response = await fetch(`/ci/propose-fix?run_id=${item.run_id}&repo=${encodeURIComponent(repo)}`, { method: "POST" });
          const proposal = await response.json();
          if (!response.ok) throw new Error(proposal.detail || "Не удалось подготовить исправление.");
          
          showProposal(proposal);
          ciMessage.textContent = "Предложение готово к проверке.";
          ciMessage.style.color = "var(--gh-success-fg)";
          fixBtn.textContent = "Готово";
        } catch (error) {
          ciMessage.textContent = error.message;
          ciMessage.style.color = "var(--gh-danger-fg)";
          fixBtn.disabled = false;
          fixBtn.textContent = "Предложить фикс";
        }
      });
      
      ciResults.appendChild(article);
    });
    ciResults.hidden = false;
  } catch (error) {
    ciMessage.textContent = error.message;
    ciMessage.style.color = "var(--gh-danger-fg)";
    ciMessage.hidden = false;
  } finally {
    setLoading(ciScanButton, false);
  }
});

prButton.addEventListener("click", async () => {
  if (!currentProposal) return;
  setLoading(prButton, true, "Создаём PR...");
  
  if (prSuccessBanner) prSuccessBanner.hidden = true;

  try {
    const repo = await getRepositoryPath();
    const response = await fetch(`/github/pull-request?repo=${encodeURIComponent(repo)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...currentProposal,
        approved: true,
        base_branch: "main",
        title: document.querySelector("#pr-title").value,
        description: prDescription.value,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Pull Request не создан.");
    
    if (prSuccessBanner) {
        document.querySelector("#pr-link").href = payload.url;
        document.querySelector("#pr-link").textContent = `#${payload.number}`;
        prSuccessBanner.hidden = false;
    }
  } catch (error) {
    if (applyMessage) {
        applyMessage.textContent = error.message;
        applyMessage.style.color = "var(--gh-danger-fg)";
        applyMessage.hidden = false;
        applyMessage.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  } finally {
    setLoading(prButton, false);
  }
});

// Hide only after all event handlers have been registered successfully.
document.querySelector("#startup-message").hidden = true;

// ==========================================================================
// 6. ПЕРЕКЛЮЧЕНИЕ ЭКРАНОВ (Directum RX)
// Изолированный блок: не меняет обработчики запросов и безопасен без window.
// ==========================================================================
function initViewSwitcher() {
  try {
    const views = Array.from(document.querySelectorAll("[data-rx-view]"));
    const tabs = Array.from(document.querySelectorAll(".gh-tab"));
    const homeLinks = Array.from(document.querySelectorAll("[data-rx-home]"));
    const moduleLinks = Array.from(document.querySelectorAll("[data-rx-target]"));
    const breadcrumbCurrent = document.querySelector("#rx-breadcrumb-current");
    const backLink = document.querySelector("#rx-back-to-analyze");

    const labels = {
      home: "Обзор",
      analyze: "Анализ логов",
      ci: "CI/CD",
      share: "Логи Directum",
    };
    const hashToView = {
      "#home-section": "home",
      "#analyze-section": "analyze",
      "#ci-section": "ci",
      "#share-section": "share",
    };
    const viewToHash = {
      home: "#home-section",
      analyze: "#analyze-section",
      ci: "#ci-section",
      share: "#share-section",
    };

    function applyView(requestedView) {
      const target = labels[requestedView] ? requestedView : "home";

      views.forEach((section) => {
        section.hidden = section.getAttribute("data-rx-view") !== target;
      });

      tabs.forEach((tab) => {
        const tabView = tab.getAttribute("data-rx-view-target");
        const isActive = tabView === target;
        if (tab.classList) {
          tab.classList.toggle("active", isActive);
        }
        if (isActive) {
          tab.setAttribute("aria-current", "page");
        } else {
          tab.removeAttribute("aria-current");
        }
      });

      if (breadcrumbCurrent) {
        breadcrumbCurrent.textContent = labels[target];
      }
      if (backLink) {
        backLink.hidden = target === "home";
      }

      if (document.body && document.body.classList) {
        document.body.classList.remove("rx-view-home", "rx-view-analyze", "rx-view-ci", "rx-view-share");
        document.body.classList.add(`rx-view-${target}`);
      }

      if (typeof window !== "undefined") {
        try {
          if (window.history && typeof window.history.replaceState === "function") {
            window.history.replaceState(null, "", viewToHash[target]);
          } else if (window.location) {
            window.location.hash = viewToHash[target];
          }
        } catch (error) {
          // Hash is optional; switching must still work in restricted contexts.
        }
        if (typeof window.scrollTo === "function") {
          try {
            window.scrollTo({ top: 0, behavior: "instant" });
          } catch (error) {
            window.scrollTo(0, 0);
          }
        }
      }
    }

    tabs.forEach((tab) => {
      tab.addEventListener("click", (event) => {
        event.preventDefault();
        applyView(tab.getAttribute("data-rx-view-target") || "home");
      });
    });

    homeLinks.forEach((link) => {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        applyView("home");
      });
    });

    moduleLinks.forEach((link) => {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        applyView(link.getAttribute("data-rx-target") || "home");
      });
    });

    if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
      window.addEventListener("hashchange", () => {
        applyView(hashToView[window.location.hash] || "home");
      });
    }

    const initialView = typeof window !== "undefined" && window.location
      ? hashToView[window.location.hash] || "home"
      : "home";
    applyView(initialView);
  } catch (error) {
    console.warn("Не удалось инициализировать переключение экранов.", error);
  }
}

initViewSwitcher();
