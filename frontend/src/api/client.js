/**
 * TRACE API Client
 * Centralized HTTP service for interacting with the TRACE FastAPI backend.
 * Provides consistent error handling, structured status codes, and type-safe payload dispatch.
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

class ApiError extends Error {
  constructor(message, status, data = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
    this.reason = data?.reason || null;
    this.explanation = data?.explanation || data?.detail || message;
  }
}

async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  const headers = {
    'Accept': 'application/json',
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...options.headers,
  };

  try {
    const res = await fetch(url, {
      ...options,
      headers,
    });

    const isJson = res.headers.get('content-type')?.includes('application/json');
    const data = isJson ? await res.json() : await res.text();

    if (!res.ok) {
      const errorMsg = data?.explanation || data?.detail || data?.reason || `HTTP ${res.status}`;
      throw new ApiError(errorMsg, res.status, data);
    }

    return data;
  } catch (err) {
    if (err instanceof ApiError) {
      throw err;
    }
    // Network errors or connection refused
    throw new ApiError(
      `Backend unreachable at ${BASE_URL}. Ensure FastAPI server is running.`,
      0,
      { detail: err.message }
    );
  }
}

export const api = {
  health: () => request('/health'),
  getProjects: () => request('/projects'),
  getProject: (id) => request(`/projects/${id}`),
  getProjectTrace: (id) => request(`/projects/${id}/trace`),
  getClaims: (projectId = null) => {
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
    return request(`/claims${query}`);
  },
  releaseTranche: (projectId) =>
    request(`/projects/${projectId}/release`, { method: 'POST' }),
  getAuditTrail: (projectId = null, limit = 50) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (projectId) params.set('project_id', projectId);
    return request(`/audit?${params.toString()}`);
  },
  getMetrics: () => request('/metrics'),
  getScenarios: () => request('/demo/scenarios'),
  runScenario: (name) =>
    request(`/demo/scenarios/${encodeURIComponent(name)}/run`, { method: 'POST' }),
  resetDemo: () =>
    request('/demo/reset', { method: 'POST' }),
};

export { ApiError };
