// V.A.U.L.T. HUD — frontend logic

const POLL_MS = 1500;
let orbCtx, orbAngle = 0;
let currentState = "offline";

// ── Polling ──────────────────────────────────────────

async function pollStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    updateVoice(data);
    setConnected(true);
  } catch {
    setConnected(false);
  }
}

async function pollMetrics() {
  try {
    const res = await fetch("/api/metrics");
    const m = await res.json();

    setText("m-vault", m.vault_notes);
    setText("m-reports", m.reports);
    setText("m-skills", m.skills_loaded);
    setText("m-stt", (m.stt_device || "unknown").toUpperCase());
    setText("m-tts", (m.tts_status || "stub").toUpperCase());
    setText("m-last", truncate(m.last_command, 14));

    // Social tiles stay hidden until a fetcher writes real numbers.
    const social = document.getElementById("social-metrics");
    const hasSocial = [m.yt_subscribers, m.yt_latest_views, m.ig_followers]
      .some(v => v !== null && v !== undefined);
    if (social) {
      social.hidden = !hasSocial;
      if (hasSocial) {
        setText("m-yt-subs", fmt(m.yt_subscribers));
        setText("m-yt-views", fmt(m.yt_latest_views));
        setText("m-ig", fmt(m.ig_followers));
      }
    }
  } catch { /* server not up yet */ }
}

function truncate(s, n) {
  if (!s) return "none";
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function fmt(n) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

// ── Voice state ──────────────────────────────────────

function updateVoice(data) {
  const stateEl = document.getElementById("voice-state");
  const transcriptEl = document.getElementById("transcript");
  const responseEl = document.getElementById("response");

  currentState = data.state || "offline";
  stateEl.textContent = currentState.toUpperCase();
  stateEl.className = currentState;

  if (data.transcript) transcriptEl.textContent = "You: " + data.transcript;
  if (data.response)   responseEl.textContent = "Jarvis: " + data.response;
}

function setConnected(ok) {
  const el = document.getElementById("connection-status");
  el.textContent = ok ? "Connected" : "Disconnected";
  el.className = ok ? "connected" : "";
}

// ── Command buttons ──────────────────────────────────

const JOB_POLL_MS = 2000;
const JOB_MAX_POLLS = 300;  // 10 minutes, matching the server-side timeout

document.querySelectorAll(".cmd-btn").forEach(btn => {
  btn.addEventListener("click", async () => {
    const cmd = btn.dataset.cmd;
    const output = document.getElementById("cmd-output");

    // Skills take minutes — the request only starts the job, then we poll.
    document.querySelectorAll(".cmd-btn").forEach(b => b.classList.add("disabled"));
    btn.classList.add("running");
    output.textContent = `Starting /${cmd}...`;

    try {
      const res = await fetch("/api/run-command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: cmd }),
      });
      const data = await res.json();

      if (!res.ok || !data.job_id) {
        output.textContent = data.error || "Could not start command.";
        return;
      }
      await pollJob(data.job_id, cmd, output);
    } catch (err) {
      output.textContent = "Error: " + err.message;
    } finally {
      btn.classList.remove("running");
      document.querySelectorAll(".cmd-btn").forEach(b => b.classList.remove("disabled"));
    }
  });
});

async function pollJob(jobId, cmd, output) {
  for (let i = 0; i < JOB_MAX_POLLS; i++) {
    await new Promise(r => setTimeout(r, JOB_POLL_MS));

    let job;
    try {
      const res = await fetch(`/api/run-command/${jobId}`);
      job = await res.json();
    } catch {
      continue;  // transient — keep polling rather than dropping the job
    }

    if (job.status === "running") {
      output.textContent = `Running /${cmd}... ${Math.round(job.elapsed)}s`;
      continue;
    }

    output.textContent = job.message || `Finished (exit ${job.exit_code})`;
    // A skill run usually writes to the vault, so refresh what depends on it.
    pollMetrics();
    pollSubscriptions();
    return;
  }
  output.textContent = `/${cmd} is still running — check the terminal.`;
}

async function checkCli() {
  try {
    const res = await fetch("/api/cli-status");
    const d = await res.json();
    if (!d.available) {
      const output = document.getElementById("cmd-output");
      if (output) output.textContent = d.detail;
      document.querySelectorAll(".cmd-btn").forEach(b => b.classList.add("disabled"));
    }
  } catch { /* server not up yet */ }
}

// ── Push to talk (server-side mic) ───────────────────

const micBtn = document.getElementById("mic-btn");
const micCancel = document.getElementById("mic-cancel");
let micHeld = false;
let voicePollTimer = null;

async function voiceAction(action) {
  const res = await fetch(`/api/voice/${action}`, { method: "POST" });
  return res.json();
}

function showVoiceError(msg) {
  const el = document.getElementById("voice-error");
  if (el) el.textContent = msg || "";
}

async function micDown(e) {
  e.preventDefault();
  if (micHeld) return;
  micHeld = true;

  micBtn.classList.add("recording");
  micBtn.textContent = "Listening — release to send";
  micCancel.hidden = false;
  showVoiceError("");

  const d = await voiceAction("start");
  if (d.error) {
    showVoiceError(d.error);
    resetMic();
  }
}

async function micUp(e) {
  e.preventDefault();
  if (!micHeld) return;
  micHeld = false;

  micBtn.classList.remove("recording");
  micBtn.classList.add("busy");
  micBtn.textContent = "Processing...";
  micCancel.hidden = true;

  const d = await voiceAction("stop");
  if (d.error) {
    showVoiceError(d.error);
    resetMic();
    return;
  }
  startVoicePolling();
}

function resetMic() {
  micHeld = false;
  micBtn.classList.remove("recording", "busy");
  micBtn.textContent = "Hold to Talk";
  micCancel.hidden = true;
}

function startVoicePolling() {
  clearInterval(voicePollTimer);
  voicePollTimer = setInterval(async () => {
    let s;
    try {
      s = await (await fetch("/api/voice/state")).json();
    } catch { return; }

    if (s.state === "processing") micBtn.textContent = `Transcribing... ${s.elapsed}s`;
    else if (s.state === "speaking") micBtn.textContent = "Speaking...";

    if (s.error) showVoiceError(s.error);

    if (s.state === "idle" || s.state === "error") {
      clearInterval(voicePollTimer);
      resetMic();
      pollStatus();
    }
  }, 700);
}

if (micBtn) {
  // Press-and-hold. The server records for exactly as long as the button is
  // down, so this feels like push-to-talk even though the mic is server-side.
  micBtn.addEventListener("mousedown", micDown);
  micBtn.addEventListener("touchstart", micDown, { passive: false });
  // Bound on window so releasing off the button still stops the recording,
  // rather than leaving it listening forever.
  window.addEventListener("mouseup", micUp);
  window.addEventListener("touchend", micUp);

  micCancel?.addEventListener("click", async (e) => {
    e.stopPropagation();
    micHeld = false;
    await voiceAction("cancel");
    resetMic();
    showVoiceError("");
  });

  // Spacebar works too, matching the terminal loop's key.
  window.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !e.repeat && !micHeld &&
        !["INPUT", "TEXTAREA", "BUTTON"].includes(document.activeElement?.tagName)) {
      micDown(e);
    }
  });
  window.addEventListener("keyup", (e) => {
    if (e.code === "Space" && micHeld) micUp(e);
  });

  // Warm the Whisper model so the first recording doesn't stall on model load.
  voiceAction("preload").catch(() => {});
}

// ── Tabs ─────────────────────────────────────────────

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById("tab-" + tab.dataset.tab).classList.add("active");
    if (tab.dataset.tab === "subs") pollSubscriptions();
  });
});

// ── Subscriptions ────────────────────────────────────

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function money(amount, currency) {
  if (amount == null) return "—";
  return `${currency || ""} ${Number(amount).toFixed(2)}`.trim();
}

async function pollSubscriptions() {
  const list = document.getElementById("subs-list");
  if (!list) return;

  try {
    const res = await fetch("/api/subscriptions");
    const d = await res.json();

    if (!d.available) {
      setText("subs-monthly", "—");
      setText("subs-yearly", "");
      list.innerHTML = `<div class="subs-empty">No subscription data yet.
        <code>python -m subs.cli sync --source fixtures</code></div>`;
      ["subs-warn", "subs-review", "subs-renewals", "subs-overlap"]
        .forEach(id => { const el = document.getElementById(id); if (el) el.hidden = true; });
      return;
    }

    setText("subs-monthly", d.monthly_display || "—");
    setText("subs-yearly", d.yearly_display ? `${d.yearly_display} per year` : "");

    // Currencies aren't converted server-side — say so rather than implying a total.
    const warn = document.getElementById("subs-warn");
    if (warn) {
      warn.hidden = !d.totals.mixed_currency;
      warn.textContent = "Currencies shown separately — no FX rate configured.";
    }

    // Review queue
    const review = document.getElementById("subs-review");
    if (review) {
      if (d.needs_review.length) {
        review.hidden = false;
        review.innerHTML =
          `<div class="subs-section-title">Needs review (${d.needs_review.length})</div>` +
          d.needs_review.map(s => `
            <div class="review-row" data-id="${s.id}">
              <span class="sub-merchant">${esc(s.merchant_name)}
                <span class="sub-meta">${esc(money(s.amount, s.currency))} ·
                conf ${(s.confidence || 0).toFixed(2)}</span></span>
              <button class="review-btn yes" data-action="confirm">keep</button>
              <button class="review-btn no" data-action="reject">drop</button>
            </div>`).join("");
      } else {
        review.hidden = true;
      }
    }

    // Renewals in the next 30 days
    const renewals = document.getElementById("subs-renewals");
    if (renewals) {
      const soon = d.renewals.filter(r => r.days_until <= 7);
      if (soon.length) {
        renewals.hidden = false;
        renewals.innerHTML =
          `<div class="subs-section-title">Renewing within 7 days</div>` +
          soon.map(s => `
            <div class="sub-row soon">
              <span class="sub-merchant">${esc(s.merchant_name)}</span>
              <span class="sub-amount">${esc(money(s.amount, s.currency))}
                <span class="sub-meta">in ${s.days_until}d</span></span>
            </div>`).join("");
      } else {
        renewals.hidden = true;
      }
    }

    // Stale — no charge seen for 2+ billing cycles, so probably cancelled.
    const staleBox = document.getElementById("subs-stale");
    if (staleBox) {
      if (d.stale?.length) {
        staleBox.hidden = false;
        staleBox.innerHTML =
          `<div class="subs-section-title">Probably cancelled (${d.stale.length})</div>` +
          d.stale.map(s => `
            <div class="review-row" data-id="${s.id}">
              <span class="sub-merchant">${esc(s.merchant_name)}
                <span class="sub-meta">${esc(money(s.amount, s.currency))} ·
                no charge in ${s.cycles_missed} cycles</span></span>
              <button class="review-btn yes" data-action="confirm">keep</button>
              <button class="review-btn no" data-action="reject">drop</button>
            </div>`).join("");
      } else {
        staleBox.hidden = true;
      }
    }

    // Active list
    list.innerHTML =
      `<div class="subs-section-title">Active (${d.active.length})</div>` +
      (d.active.length
        ? d.active.map(s => `
            <div class="sub-row${s.is_stale ? " stale" : ""}">
              <span class="sub-merchant">${esc(s.merchant_name)}
                <span class="sub-meta">${esc(s.billing_cycle || "")}${
                  s.is_stale ? " · no recent charge" : ""}</span></span>
              <span class="sub-amount">${esc(money(s.amount, s.currency))}</span>
            </div>`).join("")
        : `<div class="subs-empty">None tracked yet.</div>`);

    // Category overlap
    const overlap = document.getElementById("subs-overlap");
    if (overlap) {
      if (d.overlap.length) {
        overlap.hidden = false;
        overlap.innerHTML =
          `<div class="subs-section-title">Possible overlap</div>` +
          d.overlap.map(g => `
            <div class="overlap-item"><strong>${esc(g.category)}</strong>:
              ${esc(g.merchants.join(", "))} — ${esc(g.monthly_display)}/mo</div>`).join("");
      } else {
        overlap.hidden = true;
      }
    }
  } catch {
    list.innerHTML = `<div class="subs-empty">Could not reach the server.</div>`;
  }
}

// Rows are re-rendered on every poll, so delegate from the containers rather
// than binding each button. Same handler serves the review and stale lists.
async function handleReviewClick(e) {
  const btn = e.target.closest(".review-btn");
  if (!btn) return;
  const row = btn.closest(".review-row");
  const id = Number(row?.dataset.id);
  if (!id) return;

  btn.disabled = true;
  try {
    await fetch("/api/subscriptions/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, action: btn.dataset.action }),
    });
    pollSubscriptions();
  } catch {
    btn.disabled = false;
  }
}

document.getElementById("subs-review")?.addEventListener("click", handleReviewClick);
document.getElementById("subs-stale")?.addEventListener("click", handleReviewClick);

// ── Orb animation ────────────────────────────────────

function initOrb() {
  const canvas = document.getElementById("orb");
  if (!canvas) return;
  orbCtx = canvas.getContext("2d");
  drawOrb();
}

function drawOrb() {
  if (!orbCtx) return;
  const w = 280, h = 280, cx = w / 2, cy = h / 2;
  orbCtx.clearRect(0, 0, w, h);

  // State-dependent colors and pulse
  let baseColor, glowAlpha, pulseSpeed;
  switch (currentState) {
    case "listening":
      baseColor = "#00ff88"; glowAlpha = 0.4; pulseSpeed = 3; break;
    case "processing":
      baseColor = "#ffaa00"; glowAlpha = 0.3; pulseSpeed = 5; break;
    case "speaking":
      baseColor = "#00d4ff"; glowAlpha = 0.5; pulseSpeed = 2; break;
    default:
      baseColor = "#2a2a3e"; glowAlpha = 0.1; pulseSpeed = 0.5;
  }

  const pulse = Math.sin(orbAngle * pulseSpeed) * 0.15 + 0.85;
  const r = 80 * pulse;

  // Glow
  const grad = orbCtx.createRadialGradient(cx, cy, r * 0.3, cx, cy, r * 1.8);
  grad.addColorStop(0, baseColor);
  grad.addColorStop(0.5, baseColor + "44");
  grad.addColorStop(1, "transparent");
  orbCtx.fillStyle = grad;
  orbCtx.fillRect(0, 0, w, h);

  // Core sphere
  orbCtx.beginPath();
  orbCtx.arc(cx, cy, r, 0, Math.PI * 2);
  orbCtx.fillStyle = baseColor + "33";
  orbCtx.fill();
  orbCtx.strokeStyle = baseColor;
  orbCtx.lineWidth = 1.5;
  orbCtx.stroke();

  // Rotating ring particles
  const particleCount = 24;
  for (let i = 0; i < particleCount; i++) {
    const angle = (i / particleCount) * Math.PI * 2 + orbAngle;
    const pr = r + 15 + Math.sin(angle * 3 + orbAngle * 2) * 8;
    const px = cx + Math.cos(angle) * pr;
    const py = cy + Math.sin(angle) * pr;
    const size = 1.5 + Math.sin(angle + orbAngle) * 0.8;

    orbCtx.beginPath();
    orbCtx.arc(px, py, size, 0, Math.PI * 2);
    orbCtx.fillStyle = baseColor;
    orbCtx.globalAlpha = 0.4 + Math.sin(angle * 2) * 0.3;
    orbCtx.fill();
    orbCtx.globalAlpha = 1;
  }

  orbAngle += 0.015;
  requestAnimationFrame(drawOrb);
}

// ── Clock ────────────────────────────────────────────

function updateClock() {
  const el = document.getElementById("clock");
  if (el) el.textContent = new Date().toLocaleTimeString();
}

// ── Init ─────────────────────────────────────────────

initOrb();
updateClock();
setInterval(updateClock, 1000);
setInterval(pollStatus, POLL_MS);
setInterval(pollMetrics, POLL_MS * 4);
pollStatus();
pollMetrics();
pollSubscriptions();
checkCli();
