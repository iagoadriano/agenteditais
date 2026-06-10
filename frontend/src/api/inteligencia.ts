// Fase 2 — Inteligência Comercial (RF-CLA, RF-SCO-002/003, RF-PRE)
// Endpoints do blueprint backend/inteligencia_comercial.py

const BASE = "";

function headers() {
  const token = localStorage.getItem("editais_ia_access_token");
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

// ── RF-CLA — Classificação ────────────────────────────────────────────────────

export interface Classificacao {
  categoria: string;
  confianca: number;
  sinais: string[];
  scores: Record<string, number>;
  aplicavel: boolean;
}

export interface ClassificarResponse {
  success: boolean;
  edital_id: string;
  categoria_anterior: string | null;
  classificacao: Classificacao;
  aplicada: boolean;
  error?: string;
}

export async function classificarEdital(
  editalId: string,
  aplicar = true
): Promise<ClassificarResponse> {
  const res = await fetch(
    `${BASE}/api/inteligencia/editais/${editalId}/classificar`,
    { method: "POST", headers: headers(), body: JSON.stringify({ aplicar }) }
  );
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.error || "Erro ao classificar edital");
  }
  return res.json();
}

export interface ClassificarLoteResponse {
  success: boolean;
  total_processados: number;
  total_aplicadas: number;
  resultados: {
    edital_id: string;
    numero: string;
    categoria: string;
    confianca: number;
    aplicada: boolean;
  }[];
}

export async function classificarLote(
  apenasSemCategoria = true,
  aplicar = true
): Promise<ClassificarLoteResponse> {
  const res = await fetch(`${BASE}/api/inteligencia/editais/classificar-lote`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ apenas_sem_categoria: apenasSemCategoria, aplicar }),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.error || "Erro ao classificar editais em lote");
  }
  return res.json();
}

// ── RF-SCO — Score comercial ──────────────────────────────────────────────────

export interface ComponenteScore {
  score: number;
  motivo: string;
  exclusivo_me_epp?: boolean;
  taxa_geral?: number | null;
  taxa_similar?: number | null;
}

export interface ScoreComercialResponse {
  success: boolean;
  edital_id: string;
  edital_numero: string;
  empresa_id: string | null;
  score_final: number;
  recomendacao: "GO" | "AVALIAR" | "NO_GO";
  pesos: Record<string, number>;
  componentes: {
    logistico: ComponenteScore;
    porte: ComponenteScore;
    historico: ComponenteScore;
    prazo: ComponenteScore;
  };
  error?: string;
}

export async function getScoreComercial(
  editalId: string
): Promise<ScoreComercialResponse> {
  const res = await fetch(
    `${BASE}/api/inteligencia/editais/${editalId}/score-comercial`,
    { headers: headers() }
  );
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.error || "Erro ao calcular score comercial");
  }
  return res.json();
}

// ── RF-PRE — Recomendação de preço ────────────────────────────────────────────

export interface CenarioPreco {
  desconto_percentual: number;
  preco_sugerido: number;
}

export interface PontoCurva {
  desconto_percentual: number;
  preco: number;
  probabilidade_vitoria: number;
}

export interface RecomendacaoPrecoResponse {
  success: boolean;
  edital_id: string;
  edital_numero: string;
  valor_referencia: number;
  amostra: number;
  amostra_suficiente: boolean;
  contexto_amostra: string;
  desconto_medio_mercado: number | null;
  cenarios: {
    conservador: CenarioPreco;
    equilibrado: CenarioPreco;
    competitivo: CenarioPreco;
  };
  curva_probabilidade: PontoCurva[];
  aviso: string | null;
  error?: string;
}

export async function getRecomendacaoPreco(
  editalId: string
): Promise<RecomendacaoPrecoResponse> {
  const res = await fetch(
    `${BASE}/api/inteligencia/editais/${editalId}/recomendacao-preco`,
    { headers: headers() }
  );
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.error || "Erro ao recomendar preço");
  }
  return res.json();
}

// Labels amigáveis das categorias do enum Edital.categoria
export const CATEGORIA_LABELS: Record<string, string> = {
  comodato: "Comodato",
  venda_equipamento: "Venda de Equipamento",
  aluguel_com_consumo: "Aluguel com Consumo",
  aluguel_sem_consumo: "Aluguel sem Consumo",
  consumo_reagentes: "Consumo — Reagentes",
  consumo_insumos: "Consumo — Insumos",
  servicos: "Serviços",
  informatica: "Informática",
  redes: "Redes",
  mobiliario: "Mobiliário",
  outro: "Outro",
};
