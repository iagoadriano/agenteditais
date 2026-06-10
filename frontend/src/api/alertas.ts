// Fase 2 — Alertas de Pregão (RF-ALE-001/002)
// Endpoints do blueprint backend/alertas_pregao.py

const BASE = "";

function headers() {
  const token = localStorage.getItem("editais_ia_access_token");
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

export interface ContagemRegressiva {
  dias: number;
  horas: number;
  minutos: number;
  texto: string;
  urgencia: "critico" | "atencao" | "confortavel" | "encerrado";
}

export interface EventoAgenda {
  edital_id: string;
  edital_numero: string;
  orgao: string;
  uf: string | null;
  tipo: "abertura" | "proposta" | "impugnacao" | "recursos";
  label: string;
  data_evento: string;
  contagem: ContagemRegressiva;
  alertas_agendados: number;
}

export interface AgendaResponse {
  success: boolean;
  agora: string;
  dias_horizonte: number;
  total: number;
  eventos: EventoAgenda[];
}

export async function getAgendaPregoes(dias = 30): Promise<AgendaResponse> {
  const res = await fetch(`${BASE}/api/alertas/agenda?dias=${dias}`, {
    headers: headers(),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.error || "Erro ao carregar agenda de pregões");
  }
  return res.json();
}

export interface AgendarAutomaticoResponse {
  success: boolean;
  tempos_padrao_minutos: number[];
  eventos_no_horizonte: number;
  eventos_cobertos_agora: number;
  alertas_criados: number;
}

export async function agendarAlertasAutomatico(
  dias = 30
): Promise<AgendarAutomaticoResponse> {
  const res = await fetch(`${BASE}/api/alertas/agendar-automatico`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ dias }),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.error || "Erro ao agendar alertas");
  }
  return res.json();
}

// Baixa o .ics autenticado e dispara o download no browser
export async function baixarCalendarioICS(dias = 30): Promise<void> {
  const res = await fetch(`${BASE}/api/alertas/agenda/ics?dias=${dias}`, {
    headers: headers(),
  });
  if (!res.ok) throw new Error("Erro ao exportar calendário");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "pregoes_facilicita.ics";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
