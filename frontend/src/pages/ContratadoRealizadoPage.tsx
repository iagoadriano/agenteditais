import { useState, useEffect, useCallback } from "react";
import type { PageProps } from "../types";
import {
  BarChart2, TrendingUp, TrendingDown, Clock, AlertTriangle,
  Loader2, RefreshCw, Shield, Calendar, DollarSign, ChevronDown, ChevronUp,
} from "lucide-react";
import { Card, DataTable, FormField, SelectInput, TextInput } from "../components/common";
import type { Column } from "../components/common";
import { getTempoEmpenho, getDREContrato } from "../api/sprint9";

// ─── Types ────────────────────────────────────────────────────────────────────

interface DashboardTotais {
  contratado: number;
  realizado: number;
  variacao_pct: number;
  contratos_ativos: number;
}

interface ContratoRow {
  contrato_id: string;
  numero: string;
  orgao: string;
  objeto: string;
  valor_contratado: number;
  valor_realizado: number;
  variacao_pct: number;
  status: string;
  data_fim: string | null;
}

interface AtrasoRow {
  contrato_id: string;
  contrato_numero: string;
  orgao: string;
  entrega: string;
  data_prevista: string;
  dias_atraso: number;
  severidade: "HIGH" | "MEDIUM" | "LOW";
  valor: number;
}

interface DashboardResponse {
  totais: DashboardTotais;
  contratos: ContratoRow[];
  atrasos: AtrasoRow[];
  proximos_vencimentos: unknown[];
  saude_portfolio: "saudavel" | "atencao" | "critico";
  erro?: string;
}

interface VencimentoRow {
  tipo_entidade: "contrato" | "arp" | "entrega";
  nome: string;
  data_vencimento: string;
  dias_restantes: number;
  valor: number | null;
  entity_id: string;
  urgencia: "vermelho" | "laranja" | "amarelo" | "verde";
}

interface AlertasResumo {
  total: number;
  vermelho: number;
  laranja: number;
  amarelo: number;
  verde: number;
}

interface AlertasResponse {
  vencimentos: VencimentoRow[];
  resumo: AlertasResumo;
  erro?: string;
}

// ─── Sprint 9: UC-SC04 Tempo Empenho ─────────────────────────────────────────

interface TempoEmpenhoOrgao {
  orgao: string;
  media_dias: number;
  contratos: number;
}

interface TempoEmpenhoResponse {
  media_global: number;
  por_orgao: TempoEmpenhoOrgao[];
  erro?: string;
}

// ─── Sprint 9: UC-SC05 DRE ──────────────────────────────────────────────────

interface DRELinha {
  descricao: string;
  valor: number;
  tipo: string;
}

interface DREContrato {
  contrato_id: string;
  margem_liquida_pct: number;
  linhas: DRELinha[];
  erro?: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const formatCurrency = (value: number): string =>
  new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);

const formatDate = (iso: string): string => {
  try {
    return new Date(iso).toLocaleDateString("pt-BR");
  } catch {
    return iso;
  }
};

function authHeaders(): HeadersInit {
  const h: HeadersInit = { "Content-Type": "application/json" };
  const token = localStorage.getItem("editais_ia_access_token");
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function ContratadoRealizadoPage(props?: PageProps) {
  const { onSendToChat } = props ?? {};

  // ── Filters ──
  const [periodo, setPeriodo] = useState("6m");
  const [orgao, setOrgao] = useState("");

  // ── Dashboard data ──
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [dashLoading, setDashLoading] = useState(false);
  const [dashError, setDashError] = useState("");

  // ── Alertas vencimento ──
  const [alertas, setAlertas] = useState<AlertasResponse | null>(null);
  const [alertasLoading, setAlertasLoading] = useState(false);
  const [alertasError, setAlertasError] = useState("");

  // ── Sprint 9: Tempo Empenho (UC-SC04) ──
  const [tempoEmpenho, setTempoEmpenho] = useState<TempoEmpenhoResponse | null>(null);
  const [tempoEmpenhoLoading, setTempoEmpenhoLoading] = useState(false);

  // ── Sprint 9: DRE (UC-SC05) ──
  const [dreCache, setDreCache] = useState<Record<string, DREContrato>>({});
  const [dreExpanded, setDreExpanded] = useState<string | null>(null);
  const [dreLoading, setDreLoading] = useState<string | null>(null);

  // ── Fetch dashboard ──
  const loadDashboard = useCallback(async () => {
    setDashLoading(true);
    setDashError("");
    try {
      const params = new URLSearchParams({ periodo });
      if (orgao.trim()) params.append("orgao", orgao.trim());
      const res = await fetch(`/api/dashboard/contratado-realizado?${params}`, {
        headers: authHeaders(),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `Erro ${res.status}`);
      }
      const data: DashboardResponse = await res.json();
      if (data.erro) throw new Error(data.erro);
      setDashboard(data);
    } catch (e) {
      setDashError(e instanceof Error ? e.message : "Erro ao carregar dashboard");
    } finally {
      setDashLoading(false);
    }
  }, [periodo, orgao]);

  // ── Fetch alertas vencimento ──
  const loadAlertas = useCallback(async () => {
    setAlertasLoading(true);
    setAlertasError("");
    try {
      const res = await fetch("/api/alertas-vencimento/consolidado", {
        headers: authHeaders(),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `Erro ${res.status}`);
      }
      const data: AlertasResponse = await res.json();
      if (data.erro) throw new Error(data.erro);
      setAlertas(data);
    } catch (e) {
      setAlertasError(e instanceof Error ? e.message : "Erro ao carregar alertas");
    } finally {
      setAlertasLoading(false);
    }
  }, []);

  // ── Fetch Tempo Empenho (UC-SC04) ──
  const loadTempoEmpenho = useCallback(async () => {
    setTempoEmpenhoLoading(true);
    try {
      const data: TempoEmpenhoResponse = await getTempoEmpenho();
      if (data.erro) throw new Error(data.erro);
      setTempoEmpenho(data);
    } catch (e) {
      console.error("Erro ao carregar tempo empenho:", e);
    } finally {
      setTempoEmpenhoLoading(false);
    }
  }, []);

  // ── Fetch DRE for a contrato (UC-SC05) ──
  const loadDRE = useCallback(async (contratoId: string) => {
    if (dreCache[contratoId]) {
      setDreExpanded(dreExpanded === contratoId ? null : contratoId);
      return;
    }
    setDreLoading(contratoId);
    try {
      const data: DREContrato = await getDREContrato(contratoId);
      setDreCache((prev) => ({ ...prev, [contratoId]: data }));
      setDreExpanded(contratoId);
    } catch (e) {
      console.error("Erro ao carregar DRE:", e);
    } finally {
      setDreLoading(null);
    }
  }, [dreCache, dreExpanded]);

  // ── Load on mount + filter change ──
  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  useEffect(() => {
    loadAlertas();
  }, [loadAlertas]);

  useEffect(() => {
    loadTempoEmpenho();
  }, [loadTempoEmpenho]);

  // ── Derived data ──
  const totais = dashboard?.totais;
  const contratos = dashboard?.contratos ?? [];
  const atrasos = dashboard?.atrasos ?? [];
  const saude = dashboard?.saude_portfolio ?? "saudavel";

  const atrasosHigh = atrasos.filter((a) => a.severidade === "HIGH");
  const atrasosMedium = atrasos.filter((a) => a.severidade === "MEDIUM");
  const atrasosLow = atrasos.filter((a) => a.severidade === "LOW");

  const totalAtrasados = atrasos.length;
  const altaSeveridade = atrasosHigh.length;
  const valorEmRisco = atrasos.reduce((s, a) => s + (a.valor || 0), 0);

  const vencimentos = alertas?.vencimentos ?? [];
  const resumoAlertas = alertas?.resumo;

  // ── Contrato table columns ──
  const contratosColumns: Column<ContratoRow>[] = [
    { key: "numero", header: "Contrato", sortable: true },
    { key: "orgao", header: "Orgao", sortable: true },
    {
      key: "valor_contratado",
      header: "Contratado (R$)",
      render: (c) => formatCurrency(c.valor_contratado),
    },
    {
      key: "valor_realizado",
      header: "Realizado (R$)",
      render: (c) => formatCurrency(c.valor_realizado),
    },
    {
      key: "variacao_pct",
      header: "Variacao %",
      sortable: true,
      render: (c) => {
        const abs = Math.abs(c.variacao_pct);
        let badgeClass = "status-badge-success"; // green <=5%
        if (abs > 15) badgeClass = "status-badge-danger";
        else if (abs > 5) badgeClass = "status-badge-warning";
        return (
          <span className={`status-badge ${badgeClass}`} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            {c.variacao_pct < 0 ? <TrendingDown size={13} /> : c.variacao_pct > 0 ? <TrendingUp size={13} /> : null}
            {c.variacao_pct.toFixed(1)}%
          </span>
        );
      },
    },
    {
      key: "status",
      header: "Status",
      render: (c) => (
        <span className={`status-badge ${c.status === "vigente" ? "status-badge-success" : c.status === "encerrado" ? "status-badge-neutral" : "status-badge-info"}`}>
          {c.status}
        </span>
      ),
    },
    {
      key: "dias_primeiro_empenho" as keyof ContratoRow,
      header: "1o Empenho (dias)",
      render: (c) => {
        const dias = (c as unknown as Record<string, unknown>).dias_primeiro_empenho as number | null | undefined;
        if (dias == null) return <span style={{ color: "#9ca3af" }}>--</span>;
        let color = "#16a34a";
        if (dias > 60) color = "#dc2626";
        else if (dias > 30) color = "#ca8a04";
        return <span style={{ fontWeight: 600, color }}>{dias}d</span>;
      },
    },
    {
      key: "dre" as keyof ContratoRow,
      header: "DRE",
      render: (c) => {
        const dre = dreCache[c.contrato_id];
        const isLoading = dreLoading === c.contrato_id;
        const isExpanded = dreExpanded === c.contrato_id;

        let badge: React.ReactNode = null;
        if (dre) {
          const m = dre.margem_liquida_pct;
          let bg = "#bbf7d0", color = "#16a34a", label = "Verde";
          if (m < 0) { bg = "#fecaca"; color = "#dc2626"; label = "Vermelho"; }
          else if (m < 5) { bg = "#fef08a"; color = "#ca8a04"; label = "Amarelo"; }
          badge = (
            <span style={{ backgroundColor: bg, color, padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600, marginRight: 6 }}>
              {label} ({m.toFixed(1)}%)
            </span>
          );
        }

        return (
          <div>
            <button
              className="btn btn-sm btn-secondary"
              style={{ fontSize: 11, padding: "2px 8px", display: "inline-flex", alignItems: "center", gap: 4 }}
              onClick={(e) => { e.stopPropagation(); loadDRE(c.contrato_id); }}
              disabled={isLoading}
            >
              {isLoading ? <Loader2 size={12} className="spin" /> : <DollarSign size={12} />}
              DRE
              {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            </button>
            {badge}
          </div>
        );
      },
    },
  ];

  // ── Atrasos table columns (reused per severity group) ──
  const atrasosColumns: Column<AtrasoRow>[] = [
    { key: "contrato_numero", header: "Contrato" },
    { key: "orgao", header: "Orgao" },
    { key: "entrega", header: "Entrega" },
    {
      key: "data_prevista",
      header: "Data Prevista",
      render: (a) => formatDate(a.data_prevista),
    },
    {
      key: "dias_atraso",
      header: "Dias Atraso",
      render: (a) => (
        <span style={{ color: "#dc2626", fontWeight: 600 }}>{a.dias_atraso}d</span>
      ),
    },
    {
      key: "valor",
      header: "Valor",
      render: (a) => (a.valor ? formatCurrency(a.valor) : "—"),
    },
  ];

  // ── Vencimentos table columns ──
  const vencimentosColumns: Column<VencimentoRow>[] = [
    {
      key: "tipo_entidade",
      header: "Tipo",
      render: (v) => {
        const colors: Record<string, string> = {
          contrato: "#3b82f6",
          arp: "#8b5cf6",
          entrega: "#f59e0b",
        };
        return (
          <span
            style={{
              backgroundColor: colors[v.tipo_entidade] || "#6b7280",
              color: "#fff",
              padding: "2px 8px",
              borderRadius: 4,
              fontSize: 12,
              fontWeight: 600,
            }}
          >
            {v.tipo_entidade}
          </span>
        );
      },
    },
    { key: "nome", header: "Nome" },
    {
      key: "data_vencimento",
      header: "Data Vencimento",
      render: (v) => formatDate(v.data_vencimento),
    },
    {
      key: "dias_restantes",
      header: "Dias Restantes",
      render: (v) => (
        <span style={{ fontWeight: 600 }}>{v.dias_restantes}d</span>
      ),
    },
    {
      key: "urgencia",
      header: "Urgencia",
      render: (v) => {
        const colorMap: Record<string, { bg: string; text: string; label: string }> = {
          vermelho: { bg: "#fecaca", text: "#dc2626", label: "Vermelho" },
          laranja: { bg: "#fed7aa", text: "#ea580c", label: "Laranja" },
          amarelo: { bg: "#fef08a", text: "#ca8a04", label: "Amarelo" },
          verde: { bg: "#bbf7d0", text: "#16a34a", label: "Verde" },
        };
        const c = colorMap[v.urgencia] || colorMap.verde;
        return (
          <span
            style={{
              backgroundColor: c.bg,
              color: c.text,
              padding: "2px 10px",
              borderRadius: 4,
              fontSize: 12,
              fontWeight: 600,
            }}
          >
            {c.label}
          </span>
        );
      },
    },
  ];

  // ── Saude badge ──
  const saudeBadge = () => {
    const map: Record<string, { bg: string; text: string; label: string }> = {
      saudavel: { bg: "#bbf7d0", text: "#16a34a", label: "Saudavel" },
      atencao: { bg: "#fef08a", text: "#ca8a04", label: "Atencao" },
      critico: { bg: "#fecaca", text: "#dc2626", label: "Critico" },
    };
    const s = map[saude] || map.saudavel;
    return (
      <span
        style={{
          backgroundColor: s.bg,
          color: s.text,
          padding: "4px 14px",
          borderRadius: 6,
          fontWeight: 700,
          fontSize: 14,
        }}
      >
        {s.label}
      </span>
    );
  };

  // ── Totals row for contratos table ──
  const totalContratado = contratos.reduce((s, c) => s + c.valor_contratado, 0);
  const totalRealizado = contratos.reduce((s, c) => s + c.valor_realizado, 0);

  // ── Handle chat send ──
  const sendToChat = (msg: string) => {
    if (onSendToChat) onSendToChat(msg);
  };

  // ── Severity section renderer ──
  const renderSeverityGroup = (
    title: string,
    items: AtrasoRow[],
    headerColor: string,
    headerBg: string,
  ) => {
    if (items.length === 0) return null;
    return (
      <div style={{ marginBottom: 16 }}>
        <div
          style={{
            backgroundColor: headerBg,
            color: headerColor,
            padding: "6px 14px",
            borderRadius: 6,
            fontWeight: 700,
            fontSize: 14,
            marginBottom: 8,
          }}
        >
          {title} ({items.length})
        </div>
        <DataTable
          data={items}
          columns={atrasosColumns}
          idKey="contrato_id"
          emptyMessage="Nenhum"
        />
      </div>
    );
  };

  return (
    <div className="page-container">
      {/* ── Page Header ── */}
      <div className="page-header">
        <div className="page-header-left">
          <BarChart2 size={24} />
          <div>
            <h1>Contratado X Realizado</h1>
            <p>Dashboard, pedidos em atraso e vencimentos</p>
          </div>
        </div>
        <div className="page-header-right" style={{ display: "flex", gap: 8 }}>
          <button
            className="btn btn-secondary"
            onClick={() => sendToChat("Resuma o dashboard contratado x realizado")}
            title="Enviar para Chat"
          >
            Enviar ao Chat
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => { loadDashboard(); loadAlertas(); }}
            title="Atualizar"
          >
            <RefreshCw size={16} />
          </button>
        </div>
      </div>

      <div className="page-content">
        {/* ════════════════════════════════════════════════════════════════════
         * SECTION 1: Dashboard Contratado x Realizado (UC-CR01)
         * ════════════════════════════════════════════════════════════════════ */}
        <Card title="Dashboard Contratado x Realizado" icon={<BarChart2 size={18} />}>
          {/* ── Sticky filter bar ── */}
          <div
            className="form-inline"
            style={{
              position: "sticky",
              top: 0,
              zIndex: 10,
              backgroundColor: "var(--bg-card, #fff)",
              paddingBottom: 12,
              display: "flex",
              gap: 16,
              alignItems: "flex-end",
              flexWrap: "wrap",
            }}
          >
            <FormField label="Periodo">
              <SelectInput
                value={periodo}
                onChange={setPeriodo}
                options={[
                  { value: "1m", label: "Ultimo mes" },
                  { value: "3m", label: "Ultimos 3 meses" },
                  { value: "6m", label: "Ultimos 6 meses" },
                  { value: "12m", label: "Ultimos 12 meses" },
                  { value: "tudo", label: "Tudo" },
                ]}
              />
            </FormField>
            <FormField label="Orgao">
              <TextInput
                value={orgao}
                onChange={setOrgao}
                placeholder="Filtrar por orgao..."
              />
            </FormField>
          </div>

          {/* ── Loading / Error ── */}
          {dashLoading && (
            <div style={{ textAlign: "center", padding: 32 }}>
              <Loader2 size={28} className="spin" />
              <p>Carregando dashboard...</p>
            </div>
          )}
          {dashError && (
            <div className="alerta-header danger" style={{ marginBottom: 16 }}>
              <AlertTriangle size={18} />
              <span>{dashError}</span>
            </div>
          )}

          {/* ── Stats cards ── */}
          {!dashLoading && totais && (
            <>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                  gap: 16,
                  marginBottom: 24,
                }}
              >
                {/* Total Contratado */}
                <div
                  style={{
                    background: "var(--bg-card, #f8fafc)",
                    border: "1px solid var(--border-color, #e2e8f0)",
                    borderRadius: 8,
                    padding: 16,
                  }}
                >
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 4 }}>
                    Total Contratado
                  </div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: "#1e293b" }}>
                    {formatCurrency(totais.contratado)}
                  </div>
                </div>

                {/* Total Realizado */}
                <div
                  style={{
                    background: "var(--bg-card, #f8fafc)",
                    border: "1px solid var(--border-color, #e2e8f0)",
                    borderRadius: 8,
                    padding: 16,
                  }}
                >
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 4 }}>
                    Total Realizado
                  </div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: "#1e293b" }}>
                    {formatCurrency(totais.realizado)}
                  </div>
                </div>

                {/* Variacao % */}
                <div
                  style={{
                    background: "var(--bg-card, #f8fafc)",
                    border: "1px solid var(--border-color, #e2e8f0)",
                    borderRadius: 8,
                    padding: 16,
                  }}
                >
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 4 }}>
                    Variacao %
                  </div>
                  <div
                    style={{
                      fontSize: 22,
                      fontWeight: 700,
                      color: totais.variacao_pct <= 0 ? "#16a34a" : "#dc2626",
                      display: "flex",
                      alignItems: "center",
                      gap: 6,
                    }}
                  >
                    {totais.variacao_pct <= 0 ? (
                      <TrendingDown size={20} />
                    ) : (
                      <TrendingUp size={20} />
                    )}
                    {totais.variacao_pct.toFixed(1)}%
                    {totais.variacao_pct < 0 && (
                      <span style={{ fontSize: 12, fontWeight: 400, color: "#16a34a" }}>
                        (economia)
                      </span>
                    )}
                  </div>
                </div>

                {/* Saude Portfolio */}
                <div
                  style={{
                    background: "var(--bg-card, #f8fafc)",
                    border: "1px solid var(--border-color, #e2e8f0)",
                    borderRadius: 8,
                    padding: 16,
                  }}
                >
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 4 }}>
                    <Shield size={13} style={{ marginRight: 4, verticalAlign: "middle" }} />
                    Saude Portfolio
                  </div>
                  <div style={{ marginTop: 4 }}>{saudeBadge()}</div>
                </div>

                {/* Tempo Medio 1o Empenho (UC-SC04) */}
                <div
                  style={{
                    background: "var(--bg-card, #f8fafc)",
                    border: "1px solid var(--border-color, #e2e8f0)",
                    borderRadius: 8,
                    padding: 16,
                  }}
                >
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 4 }}>
                    <Clock size={13} style={{ marginRight: 4, verticalAlign: "middle" }} />
                    Tempo Medio 1o Empenho
                  </div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: "#1e293b" }}>
                    {tempoEmpenhoLoading ? (
                      <Loader2 size={18} className="spin" />
                    ) : tempoEmpenho ? (
                      <>{tempoEmpenho.media_global.toFixed(0)} dias</>
                    ) : (
                      "—"
                    )}
                  </div>
                </div>
              </div>

              {/* ── Comparison table ── */}
              <DataTable
                data={contratos}
                columns={contratosColumns}
                idKey="contrato_id"
                emptyMessage="Nenhum contrato encontrado no periodo"
              />

              {/* ── DRE inline expansion (UC-SC05) ── */}
              {dreExpanded && dreCache[dreExpanded] && (
                <div
                  style={{
                    marginTop: 12,
                    padding: 16,
                    background: "#f8fafc",
                    border: "1px solid #e2e8f0",
                    borderRadius: 8,
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                    <h4 style={{ margin: 0, fontSize: 14, display: "flex", alignItems: "center", gap: 6 }}>
                      <DollarSign size={16} />
                      DRE — Contrato {contratos.find((c) => c.contrato_id === dreExpanded)?.numero || dreExpanded}
                    </h4>
                    <button
                      className="btn btn-sm btn-secondary"
                      onClick={() => setDreExpanded(null)}
                      style={{ fontSize: 11, padding: "2px 8px" }}
                    >
                      Fechar
                    </button>
                  </div>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                    <thead>
                      <tr style={{ borderBottom: "2px solid #e2e8f0" }}>
                        <th style={{ textAlign: "left", padding: "6px 8px", color: "#64748b" }}>Descricao</th>
                        <th style={{ textAlign: "right", padding: "6px 8px", color: "#64748b" }}>Valor (R$)</th>
                        <th style={{ textAlign: "center", padding: "6px 8px", color: "#64748b" }}>Tipo</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(dreCache[dreExpanded].linhas || []).map((l, i) => (
                        <tr key={i} style={{ borderBottom: "1px solid #f1f5f9" }}>
                          <td style={{ padding: "6px 8px", fontWeight: l.tipo === "resultado" ? 700 : 400 }}>{l.descricao}</td>
                          <td
                            style={{
                              padding: "6px 8px",
                              textAlign: "right",
                              fontWeight: l.tipo === "resultado" ? 700 : 400,
                              color: l.valor < 0 ? "#dc2626" : "#1e293b",
                            }}
                          >
                            {formatCurrency(l.valor)}
                          </td>
                          <td style={{ padding: "6px 8px", textAlign: "center" }}>
                            <span
                              className={`status-badge ${
                                l.tipo === "receita"
                                  ? "status-badge-success"
                                  : l.tipo === "custo"
                                  ? "status-badge-danger"
                                  : l.tipo === "resultado"
                                  ? "status-badge-info"
                                  : "status-badge-neutral"
                              }`}
                              style={{ fontSize: 11 }}
                            >
                              {l.tipo}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div
                    style={{
                      marginTop: 8,
                      padding: "6px 12px",
                      background: dreCache[dreExpanded].margem_liquida_pct < 0 ? "#fecaca" : dreCache[dreExpanded].margem_liquida_pct < 5 ? "#fef08a" : "#bbf7d0",
                      borderRadius: 6,
                      fontWeight: 700,
                      fontSize: 13,
                      textAlign: "right",
                    }}
                  >
                    Margem Liquida: {dreCache[dreExpanded].margem_liquida_pct.toFixed(1)}%
                  </div>
                </div>
              )}

              {/* ── Totals row ── */}
              {contratos.length > 0 && (
                <div
                  style={{
                    display: "flex",
                    justifyContent: "flex-end",
                    gap: 32,
                    marginTop: 8,
                    padding: "8px 16px",
                    background: "var(--bg-card, #f1f5f9)",
                    borderRadius: 6,
                    fontWeight: 700,
                    fontSize: 14,
                  }}
                >
                  <span>Total Contratado: {formatCurrency(totalContratado)}</span>
                  <span>Total Realizado: {formatCurrency(totalRealizado)}</span>
                  <span
                    style={{
                      color:
                        totalRealizado - totalContratado <= 0 ? "#16a34a" : "#dc2626",
                    }}
                  >
                    Var:{" "}
                    {totalContratado > 0
                      ? (
                          ((totalRealizado - totalContratado) / totalContratado) *
                          100
                        ).toFixed(1)
                      : "0.0"}
                    %
                  </span>
                </div>
              )}
            </>
          )}
        </Card>

        {/* ════════════════════════════════════════════════════════════════════
         * SECTION 1b: Tempo por Orgao (UC-SC04)
         * ════════════════════════════════════════════════════════════════════ */}
        {tempoEmpenho && tempoEmpenho.por_orgao && tempoEmpenho.por_orgao.length > 0 && (
          <Card title="Tempo Medio de 1o Empenho por Orgao" icon={<Clock size={18} />}>
            <DataTable
              data={tempoEmpenho.por_orgao as unknown as Record<string, unknown>[]}
              columns={
                [
                  { key: "orgao", header: "Orgao", sortable: true },
                  {
                    key: "media_dias",
                    header: "Media (dias)",
                    sortable: true,
                    render: (row: Record<string, unknown>) => {
                      const dias = row.media_dias as number;
                      return <span style={{ fontWeight: 600 }}>{dias.toFixed(0)}d</span>;
                    },
                  },
                  {
                    key: "contratos",
                    header: "Contratos",
                    sortable: true,
                    render: (row: Record<string, unknown>) => String(row.contratos),
                  },
                  {
                    key: "badge" as string,
                    header: "Classificacao",
                    render: (row: Record<string, unknown>) => {
                      const dias = row.media_dias as number;
                      let bg = "#bbf7d0", color = "#16a34a", label = "Rapido";
                      if (dias > 60) { bg = "#fecaca"; color = "#dc2626"; label = "Lento"; }
                      else if (dias > 30) { bg = "#fef08a"; color = "#ca8a04"; label = "Normal"; }
                      return (
                        <span
                          style={{
                            backgroundColor: bg,
                            color,
                            padding: "2px 10px",
                            borderRadius: 4,
                            fontSize: 12,
                            fontWeight: 600,
                          }}
                        >
                          {label}
                        </span>
                      );
                    },
                  },
                ] as Column<Record<string, unknown>>[]
              }
              idKey="orgao"
              emptyMessage="Nenhum dado de tempo de empenho"
            />
          </Card>
        )}

        {/* ════════════════════════════════════════════════════════════════════
         * SECTION 2: Pedidos em Atraso (UC-CR02)
         * ════════════════════════════════════════════════════════════════════ */}
        <Card title="Pedidos em Atraso" icon={<AlertTriangle size={18} />}>
          {dashLoading && (
            <div style={{ textAlign: "center", padding: 24 }}>
              <Loader2 size={24} className="spin" />
            </div>
          )}

          {!dashLoading && (
            <>
              {/* ── Stats ── */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                  gap: 12,
                  marginBottom: 20,
                }}
              >
                <div
                  style={{
                    background: "#fef2f2",
                    border: "1px solid #fecaca",
                    borderRadius: 8,
                    padding: 14,
                  }}
                >
                  <div style={{ fontSize: 12, color: "#991b1b" }}>Total Atrasados</div>
                  <div style={{ fontSize: 24, fontWeight: 700, color: "#dc2626" }}>
                    {totalAtrasados}
                  </div>
                </div>
                <div
                  style={{
                    background: "#fef2f2",
                    border: "1px solid #fecaca",
                    borderRadius: 8,
                    padding: 14,
                  }}
                >
                  <div style={{ fontSize: 12, color: "#991b1b" }}>
                    Alta Severidade (&gt;30d)
                  </div>
                  <div style={{ fontSize: 24, fontWeight: 700, color: "#dc2626" }}>
                    {altaSeveridade}
                  </div>
                </div>
                <div
                  style={{
                    background: "#fef2f2",
                    border: "1px solid #fecaca",
                    borderRadius: 8,
                    padding: 14,
                  }}
                >
                  <div style={{ fontSize: 12, color: "#991b1b" }}>Valor em Risco</div>
                  <div style={{ fontSize: 20, fontWeight: 700, color: "#dc2626" }}>
                    {formatCurrency(valorEmRisco)}
                  </div>
                </div>
              </div>

              {/* ── Severity groups ── */}
              {totalAtrasados === 0 && (
                <div style={{ textAlign: "center", padding: 24, color: "#64748b" }}>
                  Nenhum pedido em atraso
                </div>
              )}

              {renderSeverityGroup(
                "CRITICO",
                atrasosHigh,
                "#991b1b",
                "#fecaca",
              )}
              {renderSeverityGroup(
                "ATENCAO",
                atrasosMedium,
                "#92400e",
                "#fef08a",
              )}
              {renderSeverityGroup(
                "OBSERVACAO",
                atrasosLow,
                "#9a3412",
                "#fed7aa",
              )}
            </>
          )}
        </Card>

        {/* ════════════════════════════════════════════════════════════════════
         * SECTION 3: Proximos Vencimentos (UC-CR03)
         * ════════════════════════════════════════════════════════════════════ */}
        <Card title="Proximos Vencimentos" icon={<Calendar size={18} />}>
          {alertasLoading && (
            <div style={{ textAlign: "center", padding: 24 }}>
              <Loader2 size={24} className="spin" />
            </div>
          )}
          {alertasError && (
            <div className="alerta-header danger" style={{ marginBottom: 16 }}>
              <AlertTriangle size={18} />
              <span>{alertasError}</span>
            </div>
          )}

          {!alertasLoading && resumoAlertas && (
            <>
              {/* ── Summary cards ── */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
                  gap: 12,
                  marginBottom: 20,
                }}
              >
                <div
                  style={{
                    background: "#fecaca",
                    borderRadius: 8,
                    padding: 14,
                    textAlign: "center",
                  }}
                >
                  <div style={{ fontSize: 11, color: "#991b1b" }}>
                    Vermelho (&lt;7d)
                  </div>
                  <div style={{ fontSize: 26, fontWeight: 700, color: "#dc2626" }}>
                    {resumoAlertas.vermelho}
                  </div>
                </div>
                <div
                  style={{
                    background: "#fed7aa",
                    borderRadius: 8,
                    padding: 14,
                    textAlign: "center",
                  }}
                >
                  <div style={{ fontSize: 11, color: "#9a3412" }}>Laranja (7-15d)</div>
                  <div style={{ fontSize: 26, fontWeight: 700, color: "#ea580c" }}>
                    {resumoAlertas.laranja}
                  </div>
                </div>
                <div
                  style={{
                    background: "#fef08a",
                    borderRadius: 8,
                    padding: 14,
                    textAlign: "center",
                  }}
                >
                  <div style={{ fontSize: 11, color: "#854d0e" }}>
                    Amarelo (15-30d)
                  </div>
                  <div style={{ fontSize: 26, fontWeight: 700, color: "#ca8a04" }}>
                    {resumoAlertas.amarelo}
                  </div>
                </div>
                <div
                  style={{
                    background: "#bbf7d0",
                    borderRadius: 8,
                    padding: 14,
                    textAlign: "center",
                  }}
                >
                  <div style={{ fontSize: 11, color: "#166534" }}>Verde (&gt;30d)</div>
                  <div style={{ fontSize: 26, fontWeight: 700, color: "#16a34a" }}>
                    {resumoAlertas.verde}
                  </div>
                </div>
              </div>

              {/* ── Vencimentos table ── */}
              <DataTable
                data={vencimentos}
                columns={vencimentosColumns}
                idKey="entity_id"
                emptyMessage="Nenhum vencimento proximo"
              />
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
