const apiBase = "https://oroproxy.local:8443"; // Admin and account APIs remain HTTPS.
const setupApiBase = window.location.origin; // HTTP bridge exposes only AP Wi-Fi onboarding.
let adminToken = "";
let networkPollTimer = null;

const onboardingSection = document.getElementById("onboarding");
const setupSection = document.getElementById("setup");
const loginSection = document.getElementById("login");
const adminSection = document.getElementById("admin");

function setNetworkStatus(state) {
  const statusEl = document.getElementById("wifi-status");
  if (state.mode === "home") {
    statusEl.textContent = `Connected to ${state.connected_ssid || "home network"}. Reload this page from your home network.`;
    return;
  }
  if (state.mode === "connecting") {
    statusEl.textContent = `Connecting to ${state.connected_ssid || "Wi-Fi"}...`;
    return;
  }
  statusEl.textContent = state.last_error ? `AP mode active. Last error: ${state.last_error}` : "AP mode active.";
}

async function refreshNetworkState() {
  const net = await get(`${setupApiBase}/api/network/state`);
  if (!net.ok) return;
  setNetworkStatus(net.data);
}

async function init() {
  const net = await get(`${setupApiBase}/api/network/state`);
  if (net.ok && net.data.mode !== "home") {
    onboardingSection.classList.remove("hidden");
    setNetworkStatus(net.data);
    if (networkPollTimer) clearInterval(networkPollTimer);
    networkPollTimer = setInterval(refreshNetworkState, 3000);
    return;
  }
  onboardingSection.classList.add("hidden");
  if (networkPollTimer) clearInterval(networkPollTimer);

  const status = await fetch(`${apiBase}/api/setup/status`).then((r) => r.json());
  if (!status.setup_complete) {
    setupSection.classList.remove("hidden");
    return;
  }
  loginSection.classList.remove("hidden");
  adminSection.classList.remove("hidden");
}

async function post(url, body, auth = false, method = "POST") {
  const headers = { "Content-Type": "application/json" };
  if (auth && adminToken) headers.Authorization = "Token " + adminToken;
  const options = { method, headers };
  if (body !== undefined) options.body = JSON.stringify(body);
  const resp = await fetch(url, options);
  return { ok: resp.ok, status: resp.status, data: await resp.json().catch(() => ({})) };
}

async function get(url, auth = false) {
  const headers = {};
  if (auth && adminToken) headers.Authorization = "Token " + adminToken;
  const resp = await fetch(url, { headers });
  return { ok: resp.ok, status: resp.status, data: await resp.json().catch(() => ({})) };
}

function showAdminError() {
  if (!adminToken) {
    document.getElementById("admin-result").textContent = "Please sign in as admin first.";
    return true;
  }
  return false;
}

document.getElementById("setup-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const setup_code = document.getElementById("setup-code").value.trim();
  const password = document.getElementById("setup-password").value;
  const res = await post(`${apiBase}/api/setup/complete`, { setup_code, password });
  document.getElementById("setup-result").textContent = res.ok ? "Setup complete. Reload the page." : `Error ${res.status}`;
});

document.getElementById("wifi-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const ssid = document.getElementById("wifi-ssid").value.trim();
  const password = document.getElementById("wifi-password").value;
  const res = await post(`${setupApiBase}/api/network/connect`, { ssid, password });
  document.getElementById("wifi-result").textContent = res.ok
    ? "OroProxy is joining the network. Reconnect to your home Wi-Fi, then open http://oroproxy.local."
    : `Connection failed: ${res.data.detail || `HTTP ${res.status}`}`;
  refreshNetworkState();
});

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = document.getElementById("username").value.trim();
  const password = document.getElementById("password").value;
  const client_mac = document.getElementById("client-mac").value.trim();
  const res = await post(`${apiBase}/api/auth/login`, { username, password, client_mac });
  if (res.ok) {
    localStorage.setItem("oroproxy_user_token", res.data.token);
    localStorage.setItem("oroproxy_session", res.data.session_id);
    document.getElementById("login-result").textContent = "Login successful.";
  } else {
    document.getElementById("login-result").textContent = `Login failed (${res.status})`;
  }
});

document.getElementById("admin-login").addEventListener("click", async () => {
  const password = document.getElementById("admin-password").value;
  const res = await post(`${apiBase}/api/admin/login`, { password });
  document.getElementById("admin-result").textContent = res.ok ? "Admin authenticated." : `Admin login failed (${res.status})`;
  if (res.ok) adminToken = res.data.token;
});

document.getElementById("refresh-sessions").addEventListener("click", async () => {
  if (showAdminError()) return;
  const res = await get(`${apiBase}/api/sessions/active`, true);
  document.getElementById("sessions").textContent = JSON.stringify(res.data, null, 2);
});

document.getElementById("user-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = document.getElementById("new-username").value.trim();
  const password = document.getElementById("new-password").value;
  const daily_minutes = Number(document.getElementById("new-minutes").value);
  const res = await post(`${apiBase}/api/users`, { username, password, daily_minutes }, true);
  document.getElementById("admin-result").textContent = res.ok ? "User created." : `Create failed (${res.status})`;
});

document.getElementById("refresh-users").addEventListener("click", async () => {
  if (showAdminError()) return;
  const res = await get(`${apiBase}/api/users`, true);
  document.getElementById("users").textContent = JSON.stringify(res.data, null, 2);
});

document.getElementById("update-user-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (showAdminError()) return;
  const username = document.getElementById("update-username").value.trim();
  const minutesRaw = document.getElementById("update-minutes").value;
  const is_active = document.getElementById("update-active").checked;
  const payload = { is_active };
  if (minutesRaw) payload.daily_minutes = Number(minutesRaw);
  const res = await post(`${apiBase}/api/users/${encodeURIComponent(username)}`, payload, true, "PUT");
  document.getElementById("admin-result").textContent = res.ok ? "User updated." : `Update failed (${res.status})`;
});

document.getElementById("delete-user-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (showAdminError()) return;
  const username = document.getElementById("delete-username").value.trim();
  const res = await post(`${apiBase}/api/users/${encodeURIComponent(username)}`, undefined, true, "DELETE");
  document.getElementById("admin-result").textContent = res.ok ? "User deleted." : `Delete failed (${res.status})`;
});

document.getElementById("revoke-session-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (showAdminError()) return;
  const session_id = document.getElementById("revoke-session-id").value.trim();
  const client_mac = document.getElementById("revoke-mac").value.trim();
  const username = document.getElementById("revoke-username").value.trim();
  const res = await post(`${apiBase}/api/sessions/revoke`, { session_id, client_mac, username }, true);
  document.getElementById("admin-result").textContent = res.ok ? "Session revoked." : `Revoke failed (${res.status})`;
});

document.getElementById("refresh-health").addEventListener("click", async () => {
  if (showAdminError()) return;
  const res = await get(`${apiBase}/api/health`, true);
  document.getElementById("health").textContent = JSON.stringify(res.data, null, 2);
});

document.getElementById("logging-on").addEventListener("click", async () => {
  if (showAdminError()) return;
  const res = await post(`${apiBase}/api/settings/logging`, { enabled: true }, true);
  document.getElementById("admin-result").textContent = res.ok ? "Hostname logging enabled." : `Failed (${res.status})`;
});

document.getElementById("logging-off").addEventListener("click", async () => {
  if (showAdminError()) return;
  const res = await post(`${apiBase}/api/settings/logging`, { enabled: false }, true);
  document.getElementById("admin-result").textContent = res.ok ? "Hostname logging disabled." : `Failed (${res.status})`;
});

document.getElementById("refresh-logs").addEventListener("click", async () => {
  if (showAdminError()) return;
  const res = await get(`${apiBase}/api/logs`, true);
  document.getElementById("logs").textContent = JSON.stringify(res.data, null, 2);
});

document.getElementById("clear-logs").addEventListener("click", async () => {
  if (showAdminError()) return;
  const res = await post(`${apiBase}/api/logs/clear`, {}, true);
  document.getElementById("admin-result").textContent = res.ok ? "Logs cleared." : `Failed (${res.status})`;
});

document.getElementById("check-update").addEventListener("click", async () => {
  if (showAdminError()) return;
  const res = await post(`${apiBase}/api/update/check`, {}, true);
  document.getElementById("update-status").textContent = JSON.stringify(res.data, null, 2);
});

document.getElementById("apply-update").addEventListener("click", async () => {
  if (showAdminError()) return;
  const res = await post(`${apiBase}/api/update/apply`, {}, true);
  document.getElementById("admin-result").textContent = res.ok ? "Update applied." : `Update failed (${res.status})`;
});

init();
