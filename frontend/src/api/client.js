// Thin fetch wrapper over the sidecar REST contract (Appendix A §A.2).
// Base URL is the hardcoded loopback port shared with the Rust shell + backend
// (no dynamic negotiation). Every failure — network or the uniform error
// envelope (A.2.7) — is normalized into a thrown `ApiError` so the UI has one
// catch path.

const BASE = "http://127.0.0.1:8765";

export class ApiError extends Error {
  constructor(kind, message, detail) {
    super(message || kind);
    this.kind = kind; // bad_api_key | model_error | offline | not_found | bad_request | network
    this.detail = detail ?? null;
  }
}

async function request(method, path, body) {
  let resp;
  try {
    resp = await fetch(BASE + path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    // fetch rejects only on a transport failure — the sidecar isn't reachable.
    throw new ApiError("offline", "Can't reach the local backend.");
  }

  const data = await resp.json().catch(() => null);
  if (!resp.ok) {
    const e = data?.error ?? {};
    throw new ApiError(e.kind ?? "bad_request", e.message ?? `HTTP ${resp.status}`, e.detail);
  }
  return data;
}

export const api = {
  health: () => request("GET", "/health"),
  models: () => request("GET", "/models").then((d) => d.models),

  listAgents: () => request("GET", "/agents").then((d) => d.agents),
  getAgent: (id) => request("GET", `/agents/${id}`).then((d) => d.agent),
  createAgent: (body) => request("POST", "/agents", body).then((d) => d.agent),
  updateAgent: (id, body) => request("PUT", `/agents/${id}`, body).then((d) => d.agent),
  deleteAgent: (id) => request("DELETE", `/agents/${id}`),

  listMessages: (id) => request("GET", `/agents/${id}/messages`).then((d) => d.messages),
  sendMessage: (id, content) =>
    request("POST", `/agents/${id}/messages`, { content }).then((d) => d.messages),
  clearMessages: (id) => request("DELETE", `/agents/${id}/messages`),

  getKeys: () => request("GET", "/keys"),
  putKeys: (body) => request("PUT", "/keys", body),
};
