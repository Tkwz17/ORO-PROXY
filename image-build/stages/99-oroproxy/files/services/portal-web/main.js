const apiBase = "https://oroproxy.local:8443";
let adminToken = "";

const setupSection = document.getElementById("setup");
const loginSection = document.getElementById("login");
const adminSection = document.getElementById("admin");

async function init() {
  const status = await fetch(`${apiBase}/api/setup/status`).then((r) => r.json());
  if (!status.setup_complete) {
    setupSection.classList.remove("hidden");
    return;
  }
  loginSection.classList.remove("hidden");
  adminSection.classList.remove("hidden");
}

async function post(url, body, auth = false) {
  const headers = { "Content-Type": "application/json" };
  if (auth && adminToken) headers.Authorization = "Token " + adminToken;
  const resp = await fetch(url, { method: "POST", headers, body: JSON.stringify(body) });
  return { ok: resp.ok, status: resp.status, data: await resp.json().catch(() => ({})) };
}

document.getElementById("setup-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const setup_code = document.getElementById("setup-code").value.trim();
  const password = document.getElementById("setup-password").value;
  const res = await post(`${apiBase}/api/setup/complete`, { setup_code, password });
  document.getElementById("setup-result").textContent = res.ok ? "Setup complete. Reload the page." : `Error ${res.status}`;
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
  if (!adminToken) {
    document.getElementById("sessions").textContent = "Please sign in as admin first.";
    return;
  }
  const resp = await fetch(`${apiBase}/api/sessions/active`, {
    headers: { Authorization: "Token " + adminToken },
  });
  const data = await resp.json();
  document.getElementById("sessions").textContent = JSON.stringify(data, null, 2);
});

document.getElementById("user-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = document.getElementById("new-username").value.trim();
  const password = document.getElementById("new-password").value;
  const daily_minutes = Number(document.getElementById("new-minutes").value);
  const res = await post(`${apiBase}/api/users`, { username, password, daily_minutes }, true);
  document.getElementById("admin-result").textContent = res.ok ? "User created." : `Create failed (${res.status})`;
});

init();
