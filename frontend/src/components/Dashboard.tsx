import { useState, useEffect, useCallback } from "react";
import {
  AlertTriangle, Clock, FileText, TrendingUp, CheckCircle,
  DollarSign, Target, Calendar, ArrowRight, Lightbulb, Search, Sparkles, Brain, Loader2, AlertCircle, RefreshCw,
  Bell, Eye, CheckCheck, XCircle
} from "lucide-react";

interface DashboardProps {
  onNavigate: (page: string) => void;
  onOpenChat: () => void;
}

interface EditalUrgente {
  id: string | number;
  numero: string;
  orgao: string;
  prazo: string;
  valor: string;
}

interface FunilData {
  captacao: number;
  validacao: number;
  precificacao: number;
  proposta: number;
  submissao: number;
  ganhos: number;
}

interface KpisData {
  emAnalise: number;
  propostas: number;
  ganhos: number;
  taxaSucesso: string;
  valorTotal: string;
}

interface StatusBarData {
  novos: number;
  emAnalise: number;
  validados: number;
  propostasEnviadas: number;
  lanceHoje: number;
}

interface DashboardStats {
  urgentes: EditalUrgente[];
  funil: FunilData;
  kpis: KpisData;
  statusBar: StatusBarData;
  insights: string[];
  eventos: Array<{ dia: string; mes: string; titulo: string; subtitulo: string }>;
  aprendizados: string[];
}

interface SchedulerStatus {
  scheduler_ativo: boolean;
  scheduler_disponivel: boolean;
  monitoramentos_ativos: number;
  monitoramentos_inativos: number;
  notificacoes_nao_lidas: number;
  monitoramentos: Array<{
    id: string;
    termo: string;
    ncm?: string;
    ufs?: string[];
    ativo: boolean;
    frequencia_horas: number;
    ultima_execucao?: string;
    proximo_check?: string;
    editais_encontrados: number;
  }>;
}

interface NotificacaoItem {
  id: string;
  tipo: string;
  titulo: string;
  mensagem: string;
  created_at?: string;
}

const STATS_DEFAULTS: DashboardStats = {
  urgentes: [],
  funil: { captacao: 0, validacao: 0, precificacao: 0, proposta: 0, submissao: 0, ganhos: 0 },
  kpis: { emAnalise: 0, propostas: 0, ganhos: 0, taxaSucesso: "0%", valorTotal: "R$ 0" },
  statusBar: { novos: 0, emAnalise: 0, validados: 0, propostasEnviadas: 0, lanceHoje: 0 },
  insights: [],
  eventos: [],
  aprendizados: [],
};

// Token getter - set by the same mechanism as crud.ts
let getDashboardTokenFn: (() => Promise<string | null>) | null = null;

export function setDashboardTokenGetter(fn: () => Promise<string | null>) {
  getDashboardTokenFn = fn;
}

async function fetchDashboardStats(): Promise<DashboardStats> {
  const headers: HeadersInit = { "Content-Type": "application/json" };

  // Tentar obter token via getter ou fallback direto do localStorage
  let token: string | null = null;
  if (getDashboardTokenFn) {
    token = await getDashboardTokenFn();
  }
  if (!token) {
    token = localStorage.getItem("editais_ia_access_token");
  }
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch("/api/dashboard/stats", { headers });
  if (res.status === 401) throw new Error("Nao autenticado");
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as Record<string, string>).error || "Erro ao buscar estatisticas");
  }

  const raw = await res.json();
  const eps = raw.editais_por_status || {};
  const pps = raw.propostas_por_status || {};
  const ganhos = (eps.ganho || 0) + (eps.vencedor || 0);

  const formatCurrency = (v: number) => v >= 1000 ? `R$ ${(v / 1000).toFixed(0)}k` : `R$ ${v.toFixed(0)}`;

  // Transformar resposta do backend para formato do Dashboard
  const stats: DashboardStats = {
    urgentes: (raw.proximos_prazos || []).map((p: { edital: string; prazo: string; dias_restantes: number; orgao?: string; valor?: number }) => ({
      id: p.edital,
      numero: p.edital || "—",
      orgao: p.orgao || "",
      prazo: p.dias_restantes != null ? `${p.dias_restantes} dias` : (p.prazo || "—"),
      valor: p.valor ? formatCurrency(p.valor) : "",
    })),
    funil: {
      captacao: eps.novo || 0,
      validacao: eps.analisando || 0,
      precificacao: eps.precificando || 0,
      proposta: (pps.rascunho || 0) + (pps.revisao || 0) + (pps.aprovada || 0),
      submissao: pps.enviada || 0,
      ganhos: ganhos,
    },
    kpis: {
      emAnalise: eps.analisando || 0,
      propostas: raw.total_propostas || 0,
      ganhos: ganhos,
      taxaSucesso: `${Math.round((raw.taxa_sucesso || 0) * 100)}%`,
      valorTotal: `R$ ${((raw.valor_total_contratado || 0) / 1000).toFixed(0)}k`,
    },
    statusBar: {
      novos: eps.novo || 0,
      emAnalise: eps.analisando || 0,
      validados: eps.participando || 0,
      propostasEnviadas: pps.enviada || 0,
      lanceHoje: raw.lances_hoje || 0,
    },
    insights: [],
    eventos: (raw.proximos_prazos || []).slice(0, 5).map((p: { edital: string; prazo: string }) => {
      const d = p.prazo ? new Date(p.prazo + "T00:00:00") : null;
      return {
        dia: d ? String(d.getDate()) : "—",
        mes: d ? d.toLocaleString("pt-BR", { month: "short" }).toUpperCase() : "",
        titulo: p.edital || "Edital",
        subtitulo: "Prazo de abertura",
      };
    }),
    aprendizados: [],
  };

  return stats;
}

export function Dashboard({ onNavigate, onOpenChat }: DashboardProps) {
  const [buscaRapida, setBuscaRapida] = useState("");
  const [stats, setStats] = useState<DashboardStats>(STATS_DEFAULTS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Monitoramento & Notificações
  const [schedulerStatus, setSchedulerStatus] = useState<SchedulerStatus | null>(null);
  const [notificacoes, setNotificacoes] = useState<NotificacaoItem[]>([]);
  const [showNotifs, setShowNotifs] = useState(false);

  // Insights (sugestoes IA) & Aprendizados (feedbacks)
  const [sugestoesIA, setSugestoesIA] = useState<Array<{ titulo: string; descricao: string; confianca?: number; tipo?: string }>>([]);
  const [feedbacksAprendizado, setFeedbacksAprendizado] = useState<Array<{ tipo_evento: string; entidade?: string; resultado_real?: Record<string, unknown>; created_at?: string }>>([]);

  const loadSchedulerStatus = useCallback(async () => {
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      const headers: HeadersInit = {};
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const [statusRes, notifsRes] = await Promise.all([
        fetch("/api/scheduler/status", { headers }),
        fetch("/api/notificacoes/nao-lidas", { headers }),
      ]);

      if (statusRes.ok) {
        setSchedulerStatus(await statusRes.json());
      }
      if (notifsRes.ok) {
        const data = await notifsRes.json();
        setNotificacoes(data.notificacoes || []);
      }
    } catch {
      // Silencioso
    }
  }, []);

  const marcarTodasLidas = async () => {
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      await fetch("/api/notificacoes/marcar-todas-lidas", {
        method: "PUT",
        headers: { Authorization: token ? `Bearer ${token}` : "" },
      });
      setNotificacoes([]);
      if (schedulerStatus) {
        setSchedulerStatus({ ...schedulerStatus, notificacoes_nao_lidas: 0 });
      }
    } catch { /* silencioso */ }
  };

  const loadStats = useCallback(async (retries = 2) => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchDashboardStats();
      setStats(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erro ao carregar estatisticas";
      // Se 401 e ainda tem retries, aguardar token estar disponivel e tentar novamente
      if (msg.includes("autenticado") && retries > 0) {
        await new Promise(r => setTimeout(r, 1500));
        return loadStats(retries - 1);
      }
      setError(msg);
      // Keep defaults on error so UI still renders
    } finally {
      setLoading(false);
    }
  }, []);

  const loadInsightsAprendizado = useCallback(async () => {
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      const headers: HeadersInit = {};
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const [sugRes, fbRes] = await Promise.all([
        fetch("/api/dashboard/aprendizado/sugestoes", { headers }),
        fetch("/api/dashboard/aprendizado/feedbacks", { headers }),
      ]);

      if (sugRes.ok) {
        const data = await sugRes.json();
        setSugestoesIA((data.ativas || []).slice(0, 4));
      }
      if (fbRes.ok) {
        const data = await fbRes.json();
        setFeedbacksAprendizado((data.feedbacks || []).slice(0, 4));
      }
    } catch {
      // Silencioso — cards ficam com placeholder
    }
  }, []);

  useEffect(() => {
    loadStats();
    loadSchedulerStatus();
    loadInsightsAprendizado();
  }, [loadStats, loadSchedulerStatus, loadInsightsAprendizado]);

  const maxFunil = Math.max(stats.funil?.captacao ?? 0, 1);

  return (
    <div className="dashboard">
      {/* Header com busca rapida */}
      <div className="dashboard-header">
        <div>
          <h1>Dashboard</h1>
          <p className="dashboard-subtitle">Visao geral das suas licitacoes</p>
        </div>
        <div className="dashboard-header-actions">
          <div className="dashboard-search">
            <Search size={16} />
            <input
              type="text"
              placeholder="Buscar editais, produtos, propostas..."
              value={buscaRapida}
              onChange={(e) => setBuscaRapida(e.target.value)}
            />
          </div>
          <button className="dashboard-btn secondary" onClick={() => loadStats()} disabled={loading} title="Atualizar">
            <RefreshCw size={16} className={loading ? "spin" : ""} />
          </button>
          {/* Sininho de notificações */}
          <div style={{ position: "relative" }}>
            <button
              className="dashboard-btn secondary"
              onClick={() => setShowNotifs(!showNotifs)}
              title={`${schedulerStatus?.notificacoes_nao_lidas || 0} notificacoes nao lidas`}
            >
              <Bell size={16} />
              {(schedulerStatus?.notificacoes_nao_lidas || 0) > 0 && (
                <span style={{
                  position: "absolute", top: "-4px", right: "-4px",
                  background: "#ef4444", color: "white", borderRadius: "50%",
                  width: "18px", height: "18px", fontSize: "10px", fontWeight: "bold",
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>{schedulerStatus?.notificacoes_nao_lidas}</span>
              )}
            </button>
            {showNotifs && (
              <div style={{
                position: "absolute", top: "100%", right: 0, zIndex: 1000,
                width: "380px", maxHeight: "400px", overflowY: "auto",
                background: "#1e293b", border: "1px solid #334155", borderRadius: "8px",
                boxShadow: "0 8px 32px rgba(0,0,0,0.4)", marginTop: "8px",
              }}>
                <div style={{ padding: "12px 16px", borderBottom: "1px solid #334155", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <strong style={{ color: "#e2e8f0" }}>Notificacoes</strong>
                  {notificacoes.length > 0 && (
                    <button onClick={marcarTodasLidas} style={{
                      background: "none", border: "none", color: "#60a5fa", cursor: "pointer", fontSize: "12px",
                      display: "flex", alignItems: "center", gap: "4px",
                    }}><CheckCheck size={14} /> Marcar todas lidas</button>
                  )}
                </div>
                {notificacoes.length === 0 ? (
                  <div style={{ padding: "24px 16px", textAlign: "center", color: "#94a3b8" }}>
                    Nenhuma notificacao pendente
                  </div>
                ) : (
                  notificacoes.map(n => (
                    <div key={n.id} style={{
                      padding: "10px 16px", borderBottom: "1px solid #1e293b",
                      background: "#0f172a",
                    }}>
                      <div style={{ fontSize: "13px", fontWeight: 600, color: "#e2e8f0", marginBottom: "4px" }}>{n.titulo}</div>
                      <div style={{ fontSize: "12px", color: "#94a3b8", whiteSpace: "pre-line" }}>{n.mensagem?.slice(0, 150)}</div>
                      {n.created_at && (
                        <div style={{ fontSize: "11px", color: "#64748b", marginTop: "4px" }}>
                          {new Date(n.created_at).toLocaleString("pt-BR")}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
          <button className="dashboard-btn primary" onClick={onOpenChat}>
            <Lightbulb size={18} />
            Perguntar ao Dr. Licita
          </button>
        </div>
      </div>

      {error && (
        <div className="portfolio-error" style={{ marginBottom: "16px" }}>
          <AlertCircle size={16} />
          <span>{error}</span>
          <button onClick={() => loadStats()}>Tentar novamente</button>
        </div>
      )}

      {/* Barra de badges de status */}
      <div className="dashboard-status-bar">
        <button className="status-badge-btn" onClick={() => onNavigate('captacao')}>
          <span className="status-badge-count">
            {loading ? <Loader2 size={14} className="spin" /> : stats.statusBar.novos}
          </span>
          <span className="status-badge-label">Novos</span>
        </button>
        <button className="status-badge-btn" onClick={() => onNavigate('validacao')}>
          <span className="status-badge-count">
            {loading ? <Loader2 size={14} className="spin" /> : stats.statusBar.emAnalise}
          </span>
          <span className="status-badge-label">Em Analise</span>
        </button>
        <button className="status-badge-btn validados" onClick={() => onNavigate('precificacao')}>
          <span className="status-badge-count">
            {loading ? <Loader2 size={14} className="spin" /> : stats.statusBar.validados}
          </span>
          <span className="status-badge-label">Validados</span>
        </button>
        <button className="status-badge-btn enviados" onClick={() => onNavigate('proposta')}>
          <span className="status-badge-count">
            {loading ? <Loader2 size={14} className="spin" /> : stats.statusBar.propostasEnviadas}
          </span>
          <span className="status-badge-label">Propostas Enviadas</span>
        </button>
        <button className="status-badge-btn lances" onClick={() => onNavigate('lances')}>
          <span className="status-badge-count">
            {loading ? <Loader2 size={14} className="spin" /> : stats.statusBar.lanceHoje}
          </span>
          <span className="status-badge-label">Lance Hoje</span>
        </button>
      </div>

      {/* Grid principal */}
      <div className="dashboard-grid">
        {/* Painel de Atenção - Editais Urgentes */}
        <div className="dashboard-card attention">
          <div className="dashboard-card-header">
            <AlertTriangle size={20} className="icon-warning" />
            <h2>Editais Urgentes</h2>
            {!loading && <span className="badge warning">{stats.urgentes.length}</span>}
          </div>
          <div className="dashboard-card-content">
            {loading ? (
              <div className="loading-center"><Loader2 size={20} className="spin" /><span>Carregando...</span></div>
            ) : stats.urgentes.length === 0 ? (
              <div className="empty-state-small">Nenhum edital urgente no momento</div>
            ) : (
              stats.urgentes.map(edital => (
                <div key={edital.id} className="attention-item">
                  <div className="attention-item-info">
                    <span className="attention-item-numero">{edital.numero}</span>
                    <span className="attention-item-orgao">{edital.orgao}</span>
                  </div>
                  <div className="attention-item-meta">
                    <span className="attention-item-prazo">
                      <Clock size={14} /> {edital.prazo}
                    </span>
                    <span className="attention-item-valor">{edital.valor}</span>
                  </div>
                </div>
              ))
            )}
          </div>
          <button className="dashboard-card-action" onClick={() => onNavigate('validacao')}>
            Ver todos <ArrowRight size={16} />
          </button>
        </div>

        {/* Funil de Editais */}
        <div className="dashboard-card funnel">
          <div className="dashboard-card-header">
            <Target size={20} />
            <h2>Funil de Editais</h2>
          </div>
          <div className="dashboard-card-content">
            {loading ? (
              <div className="loading-center"><Loader2 size={20} className="spin" /><span>Carregando...</span></div>
            ) : (
              <div className="funnel-chart">
                <div className="funnel-step" style={{ width: '100%' }}>
                  <div className="funnel-bar captacao" style={{ width: `${(stats.funil.captacao / maxFunil) * 100}%` }}>
                    <span className="funnel-label">Captacao</span>
                    <span className="funnel-value">{stats.funil.captacao}</span>
                  </div>
                </div>
                <div className="funnel-step" style={{ width: '85%' }}>
                  <div className="funnel-bar validacao" style={{ width: `${(stats.funil.validacao / maxFunil) * 100}%` }}>
                    <span className="funnel-label">Validacao</span>
                    <span className="funnel-value">{stats.funil.validacao}</span>
                  </div>
                </div>
                <div className="funnel-step" style={{ width: '70%' }}>
                  <div className="funnel-bar precificacao" style={{ width: `${(stats.funil.precificacao / maxFunil) * 100}%` }}>
                    <span className="funnel-label">Precificacao</span>
                    <span className="funnel-value">{stats.funil.precificacao}</span>
                  </div>
                </div>
                <div className="funnel-step" style={{ width: '55%' }}>
                  <div className="funnel-bar proposta" style={{ width: `${(stats.funil.proposta / maxFunil) * 100}%` }}>
                    <span className="funnel-label">Proposta</span>
                    <span className="funnel-value">{stats.funil.proposta}</span>
                  </div>
                </div>
                <div className="funnel-step" style={{ width: '40%' }}>
                  <div className="funnel-bar submissao" style={{ width: `${(stats.funil.submissao / maxFunil) * 100}%` }}>
                    <span className="funnel-label">Submissao</span>
                    <span className="funnel-value">{stats.funil.submissao}</span>
                  </div>
                </div>
                <div className="funnel-step" style={{ width: '25%' }}>
                  <div className="funnel-bar ganhos" style={{ width: `${(stats.funil.ganhos / maxFunil) * 100}%` }}>
                    <span className="funnel-label">Ganhos</span>
                    <span className="funnel-value">{stats.funil.ganhos}</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* KPIs Row */}
        <div className="dashboard-kpis">
          <div className="kpi-card">
            <div className="kpi-icon blue">
              <FileText size={24} />
            </div>
            <div className="kpi-info">
              <span className="kpi-value">{loading ? <Loader2 size={16} className="spin" /> : stats.kpis.emAnalise}</span>
              <span className="kpi-label">Em Analise</span>
            </div>
          </div>

          <div className="kpi-card">
            <div className="kpi-icon purple">
              <Clock size={24} />
            </div>
            <div className="kpi-info">
              <span className="kpi-value">{loading ? <Loader2 size={16} className="spin" /> : stats.kpis.propostas}</span>
              <span className="kpi-label">Propostas</span>
            </div>
          </div>

          <div className="kpi-card">
            <div className="kpi-icon green">
              <CheckCircle size={24} />
            </div>
            <div className="kpi-info">
              <span className="kpi-value">{loading ? <Loader2 size={16} className="spin" /> : stats.kpis.ganhos}</span>
              <span className="kpi-label">Ganhos</span>
            </div>
          </div>

          <div className="kpi-card">
            <div className="kpi-icon orange">
              <TrendingUp size={24} />
            </div>
            <div className="kpi-info">
              <span className="kpi-value">{loading ? <Loader2 size={16} className="spin" /> : stats.kpis.taxaSucesso}</span>
              <span className="kpi-label">Taxa de Sucesso</span>
            </div>
          </div>

          <div className="kpi-card">
            <div className="kpi-icon gold">
              <DollarSign size={24} />
            </div>
            <div className="kpi-info">
              <span className="kpi-value">{loading ? <Loader2 size={16} className="spin" /> : stats.kpis.valorTotal}</span>
              <span className="kpi-label">Valor Total</span>
            </div>
          </div>
        </div>

        {/* Insights da IA (Sugestoes ativas) */}
        <div className="dashboard-card insights">
          <div className="dashboard-card-header">
            <Lightbulb size={20} className="icon-insight" />
            <h2>Insights da IA</h2>
          </div>
          <div className="dashboard-card-content">
            {loading ? (
              <div className="loading-center"><Loader2 size={20} className="spin" /><span>Carregando...</span></div>
            ) : sugestoesIA.length === 0 ? (
              <div className="empty-state-small">Nenhum insight disponivel ainda</div>
            ) : (
              sugestoesIA.map((sug, i) => (
                <div key={i} className="insight-item">
                  <span className="insight-bullet" style={{ flexShrink: 0 }}>💡</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <span className="insight-text" style={{ fontWeight: 500 }}>{sug.titulo}</span>
                    {sug.confianca != null && (
                      <span style={{ fontSize: "11px", color: "#64748b", marginLeft: "6px" }}>({Number(sug.confianca).toFixed(0)}%)</span>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
          <button className="dashboard-card-action" onClick={() => onNavigate('aprendizado')}>
            Ver todos insights <ArrowRight size={16} />
          </button>
        </div>

        {/* Monitoramento Automático */}
        <div className="dashboard-card" style={{ borderLeft: schedulerStatus?.scheduler_ativo ? "3px solid #22c55e" : "3px solid #ef4444" }}>
          <div className="dashboard-card-header">
            <Eye size={20} />
            <h2>Monitoramento Automatico</h2>
            {schedulerStatus && (
              <span className="badge" style={{
                background: schedulerStatus.scheduler_ativo ? "#22c55e" : "#ef4444",
                color: "white", fontSize: "11px", padding: "2px 8px", borderRadius: "4px",
              }}>
                {schedulerStatus.scheduler_ativo ? "Ativo" : "Inativo"}
              </span>
            )}
          </div>
          <div className="dashboard-card-content">
            {!schedulerStatus ? (
              <div className="loading-center"><Loader2 size={20} className="spin" /><span>Carregando...</span></div>
            ) : !schedulerStatus.scheduler_disponivel ? (
              <div className="empty-state-small" style={{ color: "#ef4444" }}>
                <XCircle size={16} style={{ marginRight: "6px" }} />
                Scheduler nao disponivel (APScheduler nao instalado)
              </div>
            ) : (
              <>
                <div style={{ display: "flex", gap: "16px", marginBottom: "12px", flexWrap: "wrap" }}>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: "24px", fontWeight: "bold", color: "#22c55e" }}>{schedulerStatus.monitoramentos_ativos}</div>
                    <div style={{ fontSize: "11px", color: "#94a3b8" }}>Ativos</div>
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: "24px", fontWeight: "bold", color: "#64748b" }}>{schedulerStatus.monitoramentos_inativos}</div>
                    <div style={{ fontSize: "11px", color: "#94a3b8" }}>Pausados</div>
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: "24px", fontWeight: "bold", color: "#60a5fa" }}>{schedulerStatus.notificacoes_nao_lidas}</div>
                    <div style={{ fontSize: "11px", color: "#94a3b8" }}>Alertas</div>
                  </div>
                </div>
                {schedulerStatus.monitoramentos.filter(m => m.ativo).slice(0, 3).map(m => (
                  <div key={m.id} style={{
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                    padding: "6px 0", borderBottom: "1px solid #1e293b", fontSize: "13px",
                  }}>
                    <div>
                      <strong style={{ color: "#e2e8f0" }}>{m.termo}</strong>
                      {m.ufs && m.ufs.length > 0 && <span style={{ color: "#64748b", marginLeft: "6px" }}>({m.ufs.join(", ")})</span>}
                    </div>
                    <div style={{ display: "flex", gap: "8px", alignItems: "center", fontSize: "11px", color: "#94a3b8" }}>
                      <span>{m.editais_encontrados} encontr.</span>
                      <span>a cada {m.frequencia_horas}h</span>
                    </div>
                  </div>
                ))}
                {schedulerStatus.monitoramentos_ativos === 0 && (
                  <div className="empty-state-small">Nenhum monitoramento ativo</div>
                )}
              </>
            )}
          </div>
          <button className="dashboard-card-action" onClick={() => onNavigate('captacao')}>
            Gerenciar monitoramentos <ArrowRight size={16} />
          </button>
        </div>

        {/* Calendário Resumido */}
        <div className="dashboard-card calendar">
          <div className="dashboard-card-header">
            <Calendar size={20} />
            <h2>Proximos Eventos</h2>
          </div>
          <div className="dashboard-card-content">
            {loading ? (
              <div className="loading-center"><Loader2 size={20} className="spin" /><span>Carregando...</span></div>
            ) : stats.eventos.length === 0 ? (
              <div className="empty-state-small">Nenhum evento proximo</div>
            ) : (
              stats.eventos.map((ev, i) => (
                <div key={i} className="calendar-item">
                  <div className="calendar-date">
                    <span className="calendar-day">{ev.dia}</span>
                    <span className="calendar-month">{ev.mes}</span>
                  </div>
                  <div className="calendar-info">
                    <span className="calendar-title">{ev.titulo}</span>
                    <span className="calendar-subtitle">{ev.subtitulo}</span>
                  </div>
                </div>
              ))
            )}
          </div>
          <button className="dashboard-card-action" onClick={() => onNavigate('calendario')}>
            Ver calendario completo <ArrowRight size={16} />
          </button>
        </div>

        {/* O que o sistema aprendeu (Feedbacks recentes) */}
        <div className="dashboard-card aprendizado">
          <div className="dashboard-card-header">
            <Brain size={20} className="icon-brain" />
            <h2>O que o sistema aprendeu</h2>
          </div>
          <div className="dashboard-card-content">
            {loading ? (
              <div className="loading-center"><Loader2 size={20} className="spin" /><span>Carregando...</span></div>
            ) : feedbacksAprendizado.length === 0 ? (
              <div className="empty-state-small">O sistema ainda esta aprendendo...</div>
            ) : (
              feedbacksAprendizado.map((fb, i) => (
                <div key={i} className="aprendizado-item">
                  <Sparkles size={14} style={{ color: "#8b5cf6", flexShrink: 0 }} />
                  <span>{fb.tipo_evento?.replace(/_/g, " ")}{fb.entidade ? ` — ${fb.entidade}` : ""}</span>
                </div>
              ))
            )}
          </div>
          <button className="dashboard-card-action" onClick={() => onNavigate('aprendizado')}>
            Ver aprendizados <ArrowRight size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
