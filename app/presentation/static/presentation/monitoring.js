/* OPS-01: display committed snapshots; never predict counters or server outcomes. */
(() => {
  "use strict";
  const root = document.querySelector(".ops");
  if (!root) return;
  const content = document.getElementById("ops-data");
  const connection = document.getElementById("ops-connection");
  const timestamp = document.getElementById("ops-timestamp");
  const initial = JSON.parse(document.getElementById("ops-initial").textContent);
  let latestTimestamp = initial ? Date.parse(initial.snapshot_at) : 0;
  let lastSuccess = initial ? performance.now() : -Infinity;
  let timer, controller, busy = false, refreshAgain = false, failures = 0;
  const sections = new Map();

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = String(text);
    if (className) element.className = className;
    return element;
  }
  function paragraph(text) { return node("p", text); }
  function counts(states) {
    const list = node("dl", undefined, "ops__counts");
    Object.entries(states).forEach(([state, count]) => {
      list.append(node("dt", state.replaceAll("_", " ")), node("dd", count));
    });
    return list;
  }
  function section(key, title, data, build) {
    const serialized = JSON.stringify(data);
    if (sections.get(key)?.serialized === serialized) return;
    const element = node("section");
    element.id = `ops-${key}`;
    const heading = node("h2", title);
    heading.id = `ops-${key}-heading`;
    element.setAttribute("aria-labelledby", heading.id);
    element.append(heading, ...build(data));
    const old = sections.get(key);
    if (old) old.element.replaceWith(element);
    else content.append(element);
    sections.set(key, {element, serialized});
  }
  function render(data) {
    if (!sections.size) content.replaceChildren();
    section("processes", "Processes", data.processes, (processes) => {
      const grid = node("div", undefined, "ops__grid");
      processes.forEach((process) => {
        const panel = node("article", undefined, "ops__panel");
        panel.dataset.role = process.role;
        const state = node("strong", process.status, "ops__state");
        state.dataset.state = process.status;
        panel.append(node("h3", process.label), state, paragraph(process.stage),
          paragraph(`Last heartbeat: ${process.last_seen_at || "Not received"}`),
          paragraph(`Last progress: ${process.last_progress_at || "Not recorded"}`));
        if (process.run_id) panel.append(paragraph(`Run #${process.run_id}`));
        if (process.job_id) panel.append(paragraph(`Job #${process.job_id}`));
        if (process.overdue) panel.append(paragraph("Work is overdue; check the last progress time."));
        if (process.status === "stale") panel.append(paragraph("No recent signal from this process."));
        grid.append(panel);
      });
      return [grid];
    });
    section("today", `Today · ${data.business_day}`, [data.business_day, data.today], ([, today]) =>
      [paragraph(`Found today: ${today.found} games.`), counts(today.states)]);
    section("current", "Current run", [data.active_run, data.lease_expired], ([run, expired]) => {
      const parts = run ? [paragraph(`Run #${run.id} · ${run.status}`),
        paragraph(`${run.processed} processed / ${run.selected} selected · ${run.failed} failed`),
        paragraph(`${run.attempts} attempts · business day ${run.business_day || "Not started"}`)] :
        [paragraph("No active core run. The scheduler checks each UTC hour.")];
      if (expired) parts.push(paragraph("Processing lease expired; awaiting recovery."));
      parts.push(node("p", "Core completion saves game data. Reviews and AI summaries continue separately.", "ops__note"));
      return parts;
    });
    section("queues", "Enrichment queues", [data.reviews, data.summaries], (queues) => {
      const grid = node("div", undefined, "ops__grid");
      queues.forEach((queue, index) => {
        const panel = node("article", undefined, "ops__panel");
        panel.append(node("h3", index ? "AI summary jobs" : "Review jobs"),
          paragraph(`${queue.outstanding} outstanding`), counts(queue.states),
          paragraph(queue.oldest_wait_seconds === null ? "No recorded waiting work." :
            `Oldest outstanding: ${queue.oldest_wait_seconds} seconds`));
        grid.append(panel);
      });
      return [grid];
    });
    section("history", "Recent runs", data.history, (history) => {
      const wrapper = node("div", undefined, "ops__table-wrap");
      const table = node("table", undefined, "ops__table");
      const head = node("thead");
      const headings = node("tr");
      ["Run", "Status", "Started (UTC)", "Selected", "Processed", "Failed"].forEach((label) => {
        const cell = node("th", label); cell.scope = "col"; headings.append(cell);
      });
      head.append(headings);
      const body = node("tbody");
      history.forEach((run) => {
        const row = node("tr"); row.dataset.runId = run.id;
        const title = node("th", `#${run.id}`); title.scope = "row"; row.append(title);
        [run.status, run.started_at || "Queued", run.selected, run.processed, run.failed]
          .forEach((value) => row.append(node("td", value)));
        body.append(row);
      });
      if (!history.length) {
        const row = node("tr"), cell = node("td", "No runs recorded yet.");
        cell.colSpan = 6; row.append(cell); body.append(row);
      }
      table.append(head, body); wrapper.append(table);
      return [wrapper];
    });
    timestamp.textContent = data.snapshot_at;
    timestamp.dateTime = data.snapshot_at;
  }
  function freshness() {
    const stale = performance.now() - lastSuccess >= 5000;
    const text = stale ? "Connection lost / data may be stale" :
      document.hidden ? "Updates paused while this tab is hidden" : "Live · updates every second";
    if (connection.textContent !== text) connection.textContent = text;
    connection.dataset.stale = String(stale);
  }
  async function poll() {
    clearTimeout(timer);
    if (document.hidden) return;
    if (busy) { refreshAgain = true; controller.abort(); return; }
    busy = true;
    controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 2000);
    try {
      const response = await fetch(root.dataset.statusUrl, {signal: controller.signal, cache: "no-store"});
      if (!response.ok) throw new Error("Snapshot unavailable");
      const data = await response.json();
      const observed = Date.parse(data.snapshot_at);
      if (!Number.isFinite(observed) || observed < latestTimestamp) throw new Error("Older snapshot");
      if (controller.signal.aborted || document.hidden) return;
      render(data);
      latestTimestamp = observed;
      lastSuccess = performance.now();
      failures = 0;
    } catch {
      failures += 1;
    } finally {
      clearTimeout(timeout);
      busy = false;
      freshness();
      // Even a server recovery without an online event must be observed within five seconds.
      const delay = refreshAgain ? 0 : failures ? 2000 : 1000;
      refreshAgain = false;
      if (!document.hidden) timer = setTimeout(poll, delay);
    }
  }
  document.getElementById("ops-refresh").addEventListener("click", (event) => {
    event.preventDefault(); poll();
  });
  ["online", "focus", "pageshow"].forEach((event) => window.addEventListener(event, poll));
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) { clearTimeout(timer); if (controller) controller.abort(); }
    else { lastSuccess = -Infinity; poll(); }
    freshness();
  });
  if (initial) render(initial);
  setInterval(freshness, 500);
  poll();
})();
