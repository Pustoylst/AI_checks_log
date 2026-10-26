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
let currentProposal = null;

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
    currentProposal = payload;
    proposalExplanation.textContent = payload.explanation;
    proposalPath.textContent = `Файл: ${payload.path}`;
    oldText.textContent = payload.old_text;
    newText.textContent = payload.new_text;
    proposalPanel.hidden = false;
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
  } catch (error) {
    fixMessage.textContent = error.message;
  } finally {
    applyButton.disabled = false;
    applyButton.firstChild.textContent = "Применить изменение ";
  }
});