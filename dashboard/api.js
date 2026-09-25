const TOKEN_KEY = "seekly_token";
const EMAIL_KEY = "seekly_email";

const Auth = {
  getToken: () => localStorage.getItem(TOKEN_KEY),
  getEmail: () => localStorage.getItem(EMAIL_KEY),
  setSession: (token, email) => {
    localStorage.setItem(TOKEN_KEY, token);
    if (email) localStorage.setItem(EMAIL_KEY, email);
  },
  clearSession: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(EMAIL_KEY);
  },
  isLoggedIn: () => !!localStorage.getItem(TOKEN_KEY),
};

async function apiRequest(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = Auth.getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const resp = await fetch(`${window.SEEKLY_API_BASE}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (resp.status === 401 && auth) {
    Auth.clearSession();
    window.location.href = "index.html";
    return null;
  }

  if (resp.status === 204) return null;

  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const message = data.detail || `request failed (${resp.status})`;
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return data;
}

const Api = {
  signup: (email, password) =>
    apiRequest("/v1/auth/signup", { method: "POST", body: { email, password }, auth: false }),
  login: (email, password) =>
    apiRequest("/v1/auth/login", { method: "POST", body: { email, password }, auth: false }),
  me: () => apiRequest("/v1/auth/me"),
  listKeys: () => apiRequest("/v1/keys"),
  createKey: (name, rateLimitPerMinute) =>
    apiRequest("/v1/keys", {
      method: "POST",
      body: { name, rate_limit_per_minute: rateLimitPerMinute || null },
    }),
  updateKey: (id, rateLimitPerMinute) =>
    apiRequest(`/v1/keys/${id}`, {
      method: "PATCH",
      body: { rate_limit_per_minute: rateLimitPerMinute },
    }),
  revokeKey: (id) => apiRequest(`/v1/keys/${id}`, { method: "DELETE" }),
};
