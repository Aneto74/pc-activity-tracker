const API = "http://127.0.0.1:27420";

async function refresh() {
  try {
    const r = await fetch(`${API}/status`, { signal: AbortSignal.timeout(2000) });
    const d = await r.json();
    document.getElementById("dot").classList.add("ok");
    document.getElementById("statusText").textContent = "Агент подключён";
    document.getElementById("eventsToday").textContent = d.events_today;
    document.getElementById("agentState").textContent = d.paused ? "⏸ Пауза" : "▶ Запись";
  } catch {
    document.getElementById("statusText").textContent = "Агент недоступен";
  }
}

refresh();
