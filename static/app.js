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

let currentProposal = null;

// --- СОХРАНЕНИЕ ПУТИ РЕПОЗИТОРИЯ В LOCALSTORAGE ---
const repoPathInput = document.querySelector("#repo-path");
if (localStorage.getItem("directum_repo_path")) {
  repoPathInput.value = localStorage.getItem("directum_repo_path");
}
repoPathInput.addEventListener("input", () => {
  localStorage.setItem("directum_repo_path", repoPathInput.value.trim());
});

// ==========================================================================
// 2. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
// ==========================================================================
function renderMarkdown(text) {
    if (!text) return "";
    const rawHtml = marked.parse(text);
    return DOMPurify.sanitize(rawHtml);
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

[submitButton, proposeButton, ciScanButton, applyButton, prButton].forEach(btn => {
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

// ==========================================================================
// 3. ОТОБРАЖЕНИЕ ПРЕДЛОЖЕННОГО ИСПРАВЛЕНИЯ (Diff)
// ==========================================================================
function showProposal(payload) {
  currentProposal = payload;
  
  if (!resultContent.innerHTML.trim() || resultContent.innerHTML.includes("Ожидание")) {
      resultContent.innerHTML = renderMarkdown(payload.analysis || "Анализ доступен в логах workflow.");
      hljs.highlightAll();
  }

  proposalExplanation.innerHTML = renderMarkdown(payload.explanation);
  proposalPath.textContent = `Файл: ${payload.path}`;
  oldText.textContent = payload.old_text;
  
  if (!payload.new_text || payload.new_text.trim() === "") {
    newText.innerHTML = '<span style="color: var(--gh-fg-muted); font-style: italic;">Агент не смог предложить безопасное изменение для этого фрагмента.</span>';
  } else {
    newText.innerHTML = renderMarkdown(payload.new_text);
    hljs.highlightAll();
  }
  
  prDescription.value = payload.description || "Описание будет сформировано при создании Pull Request.";
  document.querySelector("#pr-title").value = `fix: ${payload.path}`;
  
  if (applyMessage) applyMessage.hidden = true;
  proposalPanel.hidden = false;
  resultPanel.hidden = false;
  proposalPanel.scrollIntoView({ behavior: "smooth", block: "start" });
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
      article.className = "gh-box mt-3"; 
      
      article.innerHTML = `
        <div class="gh-box-header flex-between" style="padding: 12px 16px;">
            <div>
                <strong>${item.workflow || "CI"} · run ${item.run_id}</strong>
                <a href="${item.url || "#"}" target="_blank" rel="noreferrer" class="gh-text-muted" style="margin-left: 8px; font-size: 12px; text-decoration: none;">Открыть workflow</a>
            </div>
            <button class="gh-btn ci-fix-button" type="button">Предложить фикс</button>
        </div>
        <div class="gh-box-body">
            <div class="gh-markdown-body" style="font-size: 13px; padding: 0; border: none;"></div>
        </div>
      `;
      
      article.querySelector(".gh-markdown-body").innerHTML = renderMarkdown(item.analysis);
      hljs.highlightAll();

      const fixBtn = article.querySelector(".ci-fix-button");
      fixBtn.addEventListener("click", async () => {
        fixBtn.disabled = true;
        fixBtn.textContent = "Готовим...";
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