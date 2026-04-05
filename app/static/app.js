const healthStatus = document.getElementById("health-status");
const shortenForm = document.getElementById("shorten-form");
const urlInput = document.getElementById("url-input");
const shortenResult = document.getElementById("shorten-result");
const recentUrlsBody = document.getElementById("recent-urls-body");
const statsPanel = document.getElementById("stats-panel");
const logsPanel = document.getElementById("logs-panel");

const systemTargets = {
  cpu_percent: document.getElementById("cpu-percent"),
  memory_used_mb: document.getElementById("memory-used"),
  memory_percent: document.getElementById("memory-percent"),
  disk_percent: document.getElementById("disk-percent"),
};

function buildObservabilityLinks() {
  const host = window.location.hostname || "127.0.0.1";
  document.getElementById("grafana-link").href = `/grafana/`;
  document.getElementById("prometheus-link").href = `/prometheus/`;
  document.getElementById("alertmanager-link").href = `/alertmanager/`;
}

function showResult(html, isError = false) {
  shortenResult.classList.remove("hidden");
  shortenResult.classList.toggle("error", isError);
  shortenResult.innerHTML = html;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function refreshHealth() {
  try {
    const response = await fetch("/health");
    const payload = await response.json();
    healthStatus.textContent = payload.status === "ok" ? "Healthy" : "Degraded";
  } catch (error) {
    healthStatus.textContent = "Unavailable";
  }
}

async function refreshSystem() {
  try {
    const response = await fetch("/system");
    const payload = await response.json();
    systemTargets.cpu_percent.textContent = `${payload.cpu_percent}%`;
    systemTargets.memory_used_mb.textContent = `${payload.memory_used_mb} MB / ${payload.memory_total_mb} MB`;
    systemTargets.memory_percent.textContent = `${payload.memory_percent}%`;
    systemTargets.disk_percent.textContent = `${payload.disk_percent}%`;
  } catch (error) {
    Object.values(systemTargets).forEach((node) => {
      node.textContent = "Unavailable";
    });
  }
}

async function refreshUrls() {
  try {
    const response = await fetch("/urls");
    const payload = await response.json();

    if (!Array.isArray(payload) || payload.length === 0) {
      recentUrlsBody.innerHTML = `
        <tr>
          <td colspan="5" class="empty-state">No active URLs yet. Create one above to start generating traffic.</td>
        </tr>
      `;
      return;
    }

    recentUrlsBody.innerHTML = payload
      .map(
        (urlRecord) => `
          <tr>
            <td><code>${escapeHtml(urlRecord.short_code)}</code></td>
            <td>
              <a href="${escapeHtml(urlRecord.original_url)}" target="_blank" rel="noreferrer">
                ${escapeHtml(urlRecord.original_url)}
              </a>
            </td>
            <td>${escapeHtml(urlRecord.click_count)}</td>
            <td>${escapeHtml(new Date(urlRecord.created_at).toLocaleString())}</td>
            <td>
              <button class="inline-button" data-short-code="${escapeHtml(urlRecord.short_code)}">
                View stats
              </button>
            </td>
          </tr>
        `
      )
      .join("");

    for (const button of recentUrlsBody.querySelectorAll("[data-short-code]")) {
      button.addEventListener("click", () => refreshStats(button.dataset.shortCode));
    }
  } catch (error) {
    recentUrlsBody.innerHTML = `
      <tr>
        <td colspan="5" class="empty-state">Recent URLs could not be loaded.</td>
      </tr>
    `;
  }
}

async function refreshStats(shortCode) {
  statsPanel.textContent = `Loading stats for ${shortCode}...`;

  try {
    const response = await fetch(`/urls/${encodeURIComponent(shortCode)}/stats`);
    if (!response.ok) {
      throw new Error("stats_request_failed");
    }

    const payload = await response.json();
    const breakdownEntries = Object.entries(payload.event_breakdown || {});
    const breakdown = breakdownEntries.length
      ? breakdownEntries.map(([eventType, count]) => `${eventType}: ${count}`).join(", ")
      : "No events recorded";

    statsPanel.innerHTML = `
      <dl>
        <dt>Short code</dt><dd><code>${escapeHtml(payload.short_code)}</code></dd>
        <dt>Title</dt><dd>${escapeHtml(payload.title || "Untitled")}</dd>
        <dt>Original URL</dt><dd><a href="${escapeHtml(payload.original_url)}" target="_blank" rel="noreferrer">${escapeHtml(payload.original_url)}</a></dd>
        <dt>Clicks</dt><dd>${escapeHtml(payload.click_count)}</dd>
        <dt>Active</dt><dd>${payload.is_active ? "Yes" : "No"}</dd>
        <dt>Created</dt><dd>${escapeHtml(new Date(payload.created_at).toLocaleString())}</dd>
        <dt>Updated</dt><dd>${escapeHtml(new Date(payload.updated_at).toLocaleString())}</dd>
        <dt>Total events</dt><dd>${escapeHtml(payload.total_events)}</dd>
        <dt>Event breakdown</dt><dd>${escapeHtml(breakdown)}</dd>
      </dl>
    `;
  } catch (error) {
    statsPanel.textContent = `Stats for ${shortCode} could not be loaded.`;
  }
}

async function refreshLogs() {
  try {
    const response = await fetch("/logs/recent?limit=25");
    const payload = await response.json();
    const logs = Array.isArray(payload.logs) ? payload.logs : [];

    if (logs.length === 0) {
      logsPanel.textContent = "No logs captured yet. Make a request and this panel will populate.";
      return;
    }

    logsPanel.innerHTML = logs
      .map((entry) => {
        const extraEntries = Object.entries(entry)
          .filter(([key]) => !["timestamp", "level", "component", "message"].includes(key))
          .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
          .join(" ");

        return `
          <pre><span class="log-level ${escapeHtml(entry.level.toLowerCase())}">${escapeHtml(entry.level)}</span>${escapeHtml(entry.timestamp)} ${escapeHtml(entry.component)} ${escapeHtml(entry.message)}${extraEntries ? `\n${escapeHtml(extraEntries)}` : ""}</pre>
        `;
      })
      .join("");
  } catch (error) {
    logsPanel.textContent = "Recent logs could not be loaded.";
  }
}

shortenForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const url = urlInput.value.trim();

  try {
    const response = await fetch("/shorten", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ url }),
    });

    const payload = await response.json();
    if (!response.ok) {
      showResult(
        `<strong>Request failed.</strong><br>${escapeHtml(payload.error || "Unable to shorten URL.")}`,
        true
      );
      return;
    }

    showResult(`
      <strong>Short URL created.</strong><br>
      <a href="${escapeHtml(payload.short_url)}" target="_blank" rel="noreferrer">${escapeHtml(payload.short_url)}</a>
      <br>
      Original: ${escapeHtml(payload.original_url)}
    `);
    urlInput.value = "";
    await refreshUrls();
    await refreshLogs();
    await refreshStats(payload.short_code);
  } catch (error) {
    showResult(
      "<strong>Network error.</strong><br>The request could not be completed.",
      true
    );
  }
});

async function bootstrap() {
  buildObservabilityLinks();
  await Promise.all([refreshHealth(), refreshSystem(), refreshUrls(), refreshLogs()]);
}

bootstrap();
window.setInterval(refreshHealth, 10000);
window.setInterval(refreshSystem, 10000);
window.setInterval(refreshUrls, 15000);
window.setInterval(refreshLogs, 5000);
