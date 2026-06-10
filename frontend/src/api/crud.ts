/**
 * CRUD API client genérico para todas as tabelas de cadastro.
 * Endpoints: /api/crud/<table>
 */

const API_BASE = "";

let getAccessTokenFn: (() => Promise<string | null>) | null = null;

export function setCrudTokenGetter(fn: () => Promise<string | null>) {
  getAccessTokenFn = fn;
}

export function getCrudTokenGetter(): (() => Promise<string | null>) | null {
  return getAccessTokenFn;
}

async function getAuthHeaders(): Promise<HeadersInit> {
  const headers: HeadersInit = { "Content-Type": "application/json" };
  if (getAccessTokenFn) {
    const token = await getAccessTokenFn();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

// ─── Types ────────────────────────────────────────────────────────────────────

export interface CrudColumnSchema {
  name: string;
  type: string;
  nullable: boolean;
  required: boolean;
  options?: string[];
  fk?: string;
  default?: string;
}

export interface CrudTableSchema {
  label: string;
  columns: CrudColumnSchema[];
  search_fields: string[];
  user_scoped: boolean;
  empresa_scoped: boolean;
  global: boolean;
  read_only: boolean;
  parent_fk?: string;
}

export interface CrudListResponse {
  items: Record<string, unknown>[];
  total: number;
  limit: number;
  offset: number;
}

// ─── Schema ───────────────────────────────────────────────────────────────────

let schemaCache: Record<string, CrudTableSchema> | null = null;

export async function getCrudSchema(): Promise<Record<string, CrudTableSchema>> {
  if (schemaCache) return schemaCache;
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}/api/crud/schema`, { headers });
  if (!res.ok) throw new Error("Erro ao buscar schema CRUD");
  schemaCache = await res.json();
  return schemaCache!;
}

export function clearSchemaCache() {
  schemaCache = null;
}

// ─── CRUD Operations ──────────────────────────────────────────────────────────

export async function crudList(
  table: string,
  params?: {
    q?: string;
    parent_id?: string;
    limit?: number;
    offset?: number;
    /** Filtros por FK usados por algumas páginas (ex.: PrecificacaoPage) */
    edital_item_id?: string;
    edital_item_produto_id?: string;
  }
): Promise<CrudListResponse> {
  const headers = await getAuthHeaders();
  const urlParams = new URLSearchParams();
  if (params?.q) urlParams.append("q", params.q);
  if (params?.parent_id) urlParams.append("parent_id", params.parent_id);
  if (params?.limit) urlParams.append("limit", String(params.limit));
  if (params?.offset) urlParams.append("offset", String(params.offset));

  const res = await fetch(`${API_BASE}/api/crud/${table}?${urlParams}`, { headers });
  if (res.status === 401) throw new Error("Não autenticado");
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Erro ao listar registros");
  }
  return res.json();
}

export async function crudGet(table: string, id: string): Promise<Record<string, unknown>> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}/api/crud/${table}/${id}`, { headers });
  if (res.status === 401) throw new Error("Não autenticado");
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Registro não encontrado");
  }
  return res.json();
}

export async function crudCreate(
  table: string,
  data: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}/api/crud/${table}`, {
    method: "POST",
    headers,
    body: JSON.stringify(data),
  });
  if (res.status === 401) throw new Error("Não autenticado");
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Erro ao criar registro");
  }
  return res.json();
}

export async function crudUpdate(
  table: string,
  id: string,
  data: Record<string, unknown>
): Promise<Record<string, unknown>> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}/api/crud/${table}/${id}`, {
    method: "PUT",
    headers,
    body: JSON.stringify(data),
  });
  if (res.status === 401) throw new Error("Não autenticado");
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Erro ao atualizar registro");
  }
  return res.json();
}

export async function crudDelete(table: string, id: string): Promise<void> {
  const headers = await getAuthHeaders();
  const res = await fetch(`${API_BASE}/api/crud/${table}/${id}`, {
    method: "DELETE",
    headers,
  });
  if (res.status === 401) throw new Error("Não autenticado");
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || "Erro ao excluir registro");
  }
}
