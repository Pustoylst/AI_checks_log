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
const proposalPanel = document.querySelector("#proposal-panel");
const proposalExplanation = document.querySelector("#proposal-explanation");
const proposalPath = document.querySelector("#proposal-path");
const oldText = document.querySelector("#old-text");
const newText = document.querySelector("#new-text");
const fixMessage = document.querySelector("#fix-message");
const repoStatusButton = document.querySelector("#repo-status-button");
const ciScanButton = document.querySelector("#ci-scan-button");
const repoStatus = document.querySelector("#repo-status");
const ciMessage = document.querySelector("#ci-message");
const ciResults = document.querySelector("#ci-results");
const gitActions = document.querySelector("#git-actions");
const prButton = document.querySelector("#pr-button");
let currentProposal = null;

function showProposal(payload) {
  currentProposal = payload;
  proposalExplanation.textContent = payload.explanation;
  proposalPath.textContent = `Файл: ${payload.path}`;
  oldText.textContent = payload.old_text;
  newText.textContent = payload.new_text;
  proposalPanel.hidden = false;
  resultPanel.hidden = false;
  proposalPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

fileInput.addEventListener("change", () => {
  fileName.textContent = fileInput.files[0]?.name || "Выберите JSON-файл";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  message.textContent = "";
  resultPanel.hidden = true;
  submitButton.disabled = true;
  submitButton.querySelector("span").textContent = "Анализируем...";

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
    resultContent.textContent = payload.result;
    resultTime.textContent = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    resultPanel.hidden = false;
    proposalPanel.hidden = true;
    currentProposal = null;
    resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    message.textContent = error.message || "Не удалось выполнить анализ.";
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector("span").textContent = "Проверить лог";
  }
});

proposeButton.addEventListener("click", async () => {
  fixMessage.textContent = "";
  proposeButton.disabled = true;
  proposeButton.textContent = "Ищем безопасное исправление...";
  const repo = document.querySelector("#repo-path").value.trim();
  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  try {
    const response = await fetch(`/propose-fix?repo=${encodeURIComponent(repo)}`, { method: "POST", body: formData });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Не удалось подготовить предложение.");
    showProposal(payload);
  } catch (error) {
    fixMessage.textContent = error.message;
  } finally {
    proposeButton.disabled = false;
    proposeButton.textContent = "Предложить исправление";
  }
});

applyButton.addEventListener("click", async () => {
  if (!currentProposal) return;
  applyButton.disabled = true;
  applyButton.firstChild.textContent = "Применяем... ";
  const repo = document.querySelector("#repo-path").value.trim();
  try {
    const response = await fetch(`/apply-fix?repo=${encodeURIComponent(repo)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...currentProposal, approved: true }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Изменение не применено.");
    fixMessage.textContent = `${payload.message}: ${payload.path}`;
    proposalPanel.classList.add("applied");
    gitActions.hidden = false;
  } catch (error) {
    fixMessage.textContent = error.message;
  } finally {
    applyButton.disabled = false;
    applyButton.firstChild.textContent = "Применить изменение ";
  }
});

async function getRepositoryPath() {
  const repo = document.querySelector("#repo-path").value.trim();
  if (!repo) throw new Error("Укажите корень репозитория.");
  return repo;
}

repoStatusButton.addEventListener("click", async () => {
  repoStatusButton.disabled = true;
  try {
    const repo = await getRepositoryPath();
    const response = await fetch(`/repository/status?repo=${encodeURIComponent(repo)}`);
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Не удалось прочитать Git.");
    repoStatus.textContent = `Ветка: ${payload.branch}\nRemote: ${payload.remote || "не настроен"}\nИзменения:\n${payload.changes.join("\n") || "нет"}`;
    repoStatus.hidden = false;
  } catch (error) {
    ciMessage.textContent = error.message;
  } finally {
    repoStatusButton.disabled = false;
  }
});

ciScanButton.addEventListener("click", async () => {
  ciScanButton.disabled = true;
  ciMessage.textContent = "Проверяем новые failed workflow...";
  try {
    const repo = await getRepositoryPath();
    const response = await fetch(`/ci/scan?repo=${encodeURIComponent(repo)}`, { method: "POST" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Не удалось проверить CI.");
    ciResults.innerHTML = "";
    ciMessage.textContent = payload.count ? `Найдено новых запусков: ${payload.count}` : "Новых failed workflow нет.";
    payload.results.forEach((item) => {
      const article = document.createElement("article");
      article.className = "ci-result";
      article.innerHTML = `<strong>${item.workflow || "CI"} · run ${item.run_id}</strong><a href="${item.url || "#"}" target="_blank" rel="noreferrer">Открыть workflow</a><p></p><button class="secondary-button ci-fix-button" type="button">Предложить исправление</button>`;
      article.querySelector("p").textContent = item.analysis;
      article.querySelector(".ci-fix-button").addEventListener("click", async () => {
        const button = article.querySelector(".ci-fix-button");
        button.disabled = true;
        ciMessage.textContent = "Готовим предложение по логам workflow...";
        try {
          const repo = await getRepositoryPath();
          const response = await fetch(`/ci/propose-fix?run_id=${item.run_id}&repo=${encodeURIComponent(repo)}`, { method: "POST" });
          const proposal = await response.json();
          if (!response.ok) throw new Error(proposal.detail || "Не удалось подготовить исправление.");
          showProposal(proposal);
          ciMessage.textContent = "Предложение готово к проверке.";
          button.textContent = "Предложение создано";
          button.disabled = true;
        } catch (error) {
          ciMessage.textContent = error.message;
        } finally {
          button.disabled = false;
        }
      });
      ciResults.appendChild(article);
    });
    ciResults.hidden = false;
  } catch (error) {
    ciMessage.textContent = error.message;
  } finally {
    ciScanButton.disabled = false;
  }
});

prButton.addEventListener("click", async () => {
  if (!currentProposal) return;
  prButton.disabled = true;
  prButton.firstChild.textContent = "Создаём Pull Request... ";
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
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Pull Request не создан.");
    fixMessage.innerHTML = `Pull Request создан: <a href="${payload.url}" target="_blank" rel="noreferrer">#${payload.number}</a>`;
  } catch (error) {
    fixMessage.textContent = error.message;
  } finally {
    prButton.disabled = false;
    prButton.firstChild.textContent = "Создать Pull Request ";
  }
});