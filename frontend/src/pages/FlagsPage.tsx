import { useState, useEffect, useCallback, useMemo } from "react";
import type { PageProps } from "../types";
import { Flag, Bell, Clock, Plus, CheckCircle, Calendar, Eye, MoreVertical, Download, X, Mail, Smartphone, MessageSquare } from "lucide-react";
import { Card, DataTable, ActionButton, Modal, FormField, SelectInput, Checkbox } from "../components/common";
import type { Column } from "../components/common";
import { crudList, crudUpdate } from "../api/crud";

interface Alerta {
  id: string;
  edital_id: string;
  tipo: string;
  data_disparo: string | null;
  tempo_antes_minutos: number | null;
  status: string;
  canal_email: boolean;
  canal_push: boolean;
  canal_sms: boolean;
  titulo: string | null;
  mensagem: string | null;
  disparado_em: string | null;
  lido_em: string | null;
  silenciado_ate: string | null;
  motivo_silenciamento: string | null;
  created_at: string | null;
}

type TabId = "ativos" | "historico" | "calendario" | "silenciados";
type CriticidadeLevel = "critico" | "alto" | "medio" | "informativo";

function getCriticidade(dataDisparo: string | null): CriticidadeLevel {
  if (!dataDisparo) return "informativo";
  const diasAte = (new Date(dataDisparo).getTime() - Date.now()) / (86400000);
  if (diasAte < 7) return "critico";
  if (diasAte < 15) return "alto";
  if (diasAte < 30) return "medio";
  return "informativo";
}

const CRITICIDADE_CONFIG: Record<CriticidadeLevel, { label: string; color: string; bg: string }> = {
  critico: { label: "Critico", color: "#dc2626", bg: "#fef2f2" },
  alto: { label: "Alto", color: "#ea580c", bg: "#fff7ed" },
  medio: { label: "Medio", color: "#ca8a04", bg: "#fefce8" },
  informativo: { label: "Informativo", color: "#2563eb", bg: "#eff6ff" },
};

export function FlagsPage({ onSendToChat }: PageProps) {
  const [alertas, setAlertas] = useState<Alerta[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<TabId>("ativos");
  const [showCriarModal, setShowCriarModal] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("todos");
  const [filtroTipo, setFiltroTipo] = useState("");
  const [filtroCriticidade, setFiltroCriticidade] = useState("");
  const [filtroPeriodo, setFiltroPeriodo] = useState("");

  // Silenciar modal
  const [silenciarAlerta, setSilenciarAlerta] = useState<Alerta | null>(null);
  const [silenciarAte, setSilenciarAte] = useState("");
  const [silenciarMotivo, setSilenciarMotivo] = useState("");

  // Dropdown menu
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);

  // Calendar popover
  const [calendarPopoverDay, setCalendarPopoverDay] = useState<number | null>(null);

  // Criar modal
  const [novoEdital, setNovoEdital] = useState("");
  const [novoTipo, setNovoTipo] = useState("abertura");
  const [antecedencia24h, setAntecedencia24h] = useState(true);
  const [antecedencia1h, setAntecedencia1h] = useState(true);
  const [antecedencia15min, setAntecedencia15min] = useState(false);

  const fetchAlertas = useCallback(async () => {
    setLoading(true);
    try {
      const res = await crudList("alertas", { limit: 500 });
      setAlertas((res.items || []) as unknown as Alerta[]);
    } catch (e) {
      console.error("Erro ao carregar alertas:", e);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchAlertas(); }, [fetchAlertas]);

  // Counts
  const agendados = alertas.filter(a => a.status === "agendado").length;
  const disparados = alertas.filter(a => a.status === "disparado").length;
  const lidos = alertas.filter(a => a.status === "lido").length;
  const cancelados = alertas.filter(a => a.status === "cancelado").length;

  // Criticidade counts (apenas ativos)
  const ativosAll = alertas.filter(a => a.status === "agendado" || a.status === "disparado");
  const criticos = ativosAll.filter(a => getCriticidade(a.data_disparo) === "critico").length;
  const altos = ativosAll.filter(a => getCriticidade(a.data_disparo) === "alto").length;
  const medios = ativosAll.filter(a => getCriticidade(a.data_disparo) === "medio").length;
  const informativos = ativosAll.filter(a => getCriticidade(a.data_disparo) === "informativo").length;

  // Tab filters
  const tabData = useMemo(() => {
    let data: Alerta[];
    switch (activeTab) {
      case "ativos":
        data = alertas.filter(a => a.status === "agendado" || a.status === "disparado");
        break;
      case "historico":
        data = alertas.filter(a => a.status === "lido" || a.status === "cancelado" || (a.status === "disparado" && a.disparado_em));
        break;
      case "silenciados":
        data = alertas.filter(a => a.status === "silenciado");
        break;
      default:
        data = alertas;
    }
    if (statusFilter !== "todos") data = data.filter(a => a.status === statusFilter);
    if (filtroTipo) data = data.filter(a => a.tipo === filtroTipo);
    if (filtroCriticidade) data = data.filter(a => getCriticidade(a.data_disparo) === filtroCriticidade);
    if (filtroPeriodo) {
      const diasMs = parseInt(filtroPeriodo) * 86400000;
      const desde = Date.now() - diasMs;
      data = data.filter(a => a.created_at && new Date(a.created_at).getTime() >= desde);
    }
    return data;
  }, [alertas, activeTab, statusFilter, filtroTipo, filtroCriticidade, filtroPeriodo]);

  const handleReconhecer = async (id: string) => {
    setMenuOpenId(null);
    await crudUpdate("alertas", id, { status: "lido", lido_em: new Date().toISOString() });
    fetchAlertas();
  };

  const handleCancelar = async (id: string) => {
    setMenuOpenId(null);
    await crudUpdate("alertas", id, { status: "cancelado" });
    fetchAlertas();
  };

  const handleSilenciar = async () => {
    if (!silenciarAlerta || !silenciarAte) return;
    await crudUpdate("alertas", silenciarAlerta.id, {
      status: "silenciado",
      silenciado_ate: new Date(silenciarAte).toISOString(),
      motivo_silenciamento: silenciarMotivo || null,
    });
    setSilenciarAlerta(null);
    setSilenciarAte("");
    setSilenciarMotivo("");
    fetchAlertas();
  };

  const handleReativar = async (id: string) => {
    await crudUpdate("alertas", id, { status: "agendado", silenciado_ate: null, motivo_silenciamento: null });
    fetchAlertas();
  };

  const handleCriarAlerta = () => {
    if (!onSendToChat || !novoEdital) return;
    const tempos: string[] = [];
    if (antecedencia24h) tempos.push("24h");
    if (antecedencia1h) tempos.push("1h");
    if (antecedencia15min) tempos.push("15min");
    onSendToChat(`configurar alertas para o edital ${novoEdital} tipo ${novoTipo} com antecedencia de ${tempos.join(" e ")}`);
    setShowCriarModal(false);
    setNovoEdital("");
    setTimeout(fetchAlertas, 3000);
  };

  const getCriticidadeBadge = (a: Alerta) => {
    const c = getCriticidade(a.data_disparo);
    const cfg = CRITICIDADE_CONFIG[c];
    return <span className="status-badge" style={{ background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.color}30` }}>{cfg.label}</span>;
  };

  const getTipoBadge = (tipo: string) => {
    const labels: Record<string, string> = {
      abertura: "Abertura", impugnacao: "Impugnacao", recursos: "Recursos",
      proposta: "Proposta", contrato_vencimento: "Contrato", entrega_prazo: "Entrega",
      personalizado: "Personalizado", arp_vencimento: "ARP", garantia_vencimento: "Garantia",
    };
    return <span className="status-badge status-badge-neutral">{labels[tipo] || tipo}</span>;
  };

  const getStatusBadge = (status: string) => {
    const map: Record<string, string> = {
      agendado: "status-badge-success", disparado: "status-badge-info",
      lido: "status-badge-neutral", cancelado: "status-badge-error", silenciado: "status-badge-warning",
    };
    return <span className={`status-badge ${map[status] || "status-badge-neutral"}`}>{status}</span>;
  };

  const formatData = (iso: string | null) => {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }); } catch { return iso; }
  };

  const getCanais = (a: Alerta) => (
    <div style={{ display: "flex", gap: 4 }}>
      {a.canal_email && <span title="Email"><Mail size={14} color="#6b7280" /></span>}
      {a.canal_push && <span title="Push"><Smartphone size={14} color="#6b7280" /></span>}
      {a.canal_sms && <span title="SMS"><MessageSquare size={14} color="#6b7280" /></span>}
    </div>
  );

  const ativosColumns: Column<Alerta>[] = [
    { key: "criticidade", header: "Criticidade", render: getCriticidadeBadge },
    { key: "titulo", header: "Titulo", sortable: true, render: (a) => a.titulo || "—" },
    { key: "tipo", header: "Tipo", render: (a) => getTipoBadge(a.tipo) },
    { key: "edital_id", header: "Ref.", render: (a) => a.edital_id ? a.edital_id.slice(0, 8) + "..." : "—" },
    { key: "data_disparo", header: "Disparo", render: (a) => formatData(a.data_disparo), sortable: true },
    { key: "canal", header: "Canal", render: getCanais },
    { key: "status", header: "Status", render: (a) => getStatusBadge(a.status) },
    {
      key: "acoes", header: "", width: "60px",
      render: (a) => (
        <div style={{ position: "relative" }}>
          <button className="btn-icon" onClick={(e) => { e.stopPropagation(); setMenuOpenId(menuOpenId === a.id ? null : a.id); }}>
            <MoreVertical size={16} />
          </button>
          {menuOpenId === a.id && (
            <div style={{ position: "absolute", right: 0, top: 28, background: "#fff", border: "1px solid #e5e7eb", borderRadius: 6, boxShadow: "0 4px 12px rgba(0,0,0,0.1)", zIndex: 100, minWidth: 160 }}>
              <button className="dropdown-item" onClick={() => handleReconhecer(a.id)} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", width: "100%", border: "none", background: "none", cursor: "pointer", fontSize: 13 }}>
                <CheckCircle size={14} color="#22c55e" /> Reconhecer
              </button>
              <button className="dropdown-item" onClick={() => { setMenuOpenId(null); setSilenciarAlerta(a); }} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", width: "100%", border: "none", background: "none", cursor: "pointer", fontSize: 13 }}>
                <Clock size={14} color="#ca8a04" /> Silenciar ate...
              </button>
              <button className="dropdown-item" onClick={() => handleCancelar(a.id)} style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", width: "100%", border: "none", background: "none", cursor: "pointer", fontSize: 13, color: "#dc2626" }}>
                <X size={14} /> Cancelar
              </button>
            </div>
          )}
        </div>
      ),
    },
  ];

  const historicoColumns: Column<Alerta>[] = [
    { key: "data_disparo", header: "Data", render: (a) => formatData(a.disparado_em || a.data_disparo), sortable: true },
    { key: "tipo", header: "Tipo", render: (a) => getTipoBadge(a.tipo) },
    { key: "titulo", header: "Titulo", sortable: true, render: (a) => a.titulo || "—" },
    { key: "criticidade", header: "Criticidade", render: getCriticidadeBadge },
    { key: "status", header: "Status Final", render: (a) => getStatusBadge(a.status) },
  ];

  const silenciadosColumns: Column<Alerta>[] = [
    { key: "titulo", header: "Titulo", sortable: true, render: (a) => a.titulo || "—" },
    { key: "tipo", header: "Tipo", render: (a) => getTipoBadge(a.tipo) },
    { key: "silenciado_ate", header: "Silenciado ate", render: (a) => formatData(a.silenciado_ate) },
    { key: "motivo_silenciamento", header: "Motivo", render: (a) => a.motivo_silenciamento || "—" },
    {
      key: "acoes", header: "", width: "100px",
      render: (a) => (
        <button className="btn btn-sm btn-secondary" onClick={() => handleReativar(a.id)}>Reativar</button>
      ),
    },
  ];

  const handleExportCSV = () => {
    const hist = alertas.filter(a => a.status === "lido" || a.status === "cancelado");
    let csv = "Data,Tipo,Titulo,Criticidade,Status\n";
    hist.forEach(a => {
      csv += `${formatData(a.disparado_em || a.data_disparo)},${a.tipo},${a.titulo || ""},${getCriticidade(a.data_disparo)},${a.status}\n`;
    });
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const el = document.createElement("a");
    el.href = url; el.download = "historico_alertas.csv"; el.click();
    URL.revokeObjectURL(url);
  };

  // Historico stats
  const histAlertas = alertas.filter(a => a.status === "lido" || a.status === "cancelado" || (a.status === "disparado" && a.disparado_em));
  const histDisparados = histAlertas.filter(a => a.disparado_em).length;
  const histReconhecidos = histAlertas.filter(a => a.status === "lido").length;
  const histCancelados = histAlertas.filter(a => a.status === "cancelado").length;
  const taxaReconhecimento = histDisparados > 0 ? Math.round(histReconhecidos / histDisparados * 100) : 0;

  // Calendar
  const agendaMes = useMemo(() => {
    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth();
    const diasNoMes = new Date(year, month + 1, 0).getDate();
    const diasMap = new Map<number, Alerta[]>();
    alertas.forEach(a => {
      if (a.data_disparo && (a.status === "agendado" || a.status === "disparado")) {
        const d = new Date(a.data_disparo);
        if (d.getFullYear() === year && d.getMonth() === month) {
          const dia = d.getDate();
          if (!diasMap.has(dia)) diasMap.set(dia, []);
          diasMap.get(dia)!.push(a);
        }
      }
    });
    return { year, month, diasNoMes, diasMap, primeiroDia: new Date(year, month, 1).getDay() };
  }, [alertas]);

  const mesesPt = ["Janeiro", "Fevereiro", "Marco", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];

  const getDayColor = (alertasDay: Alerta[]) => {
    const criticidades = alertasDay.map(a => getCriticidade(a.data_disparo));
    if (criticidades.includes("critico")) return "#dc2626";
    if (criticidades.includes("alto")) return "#ea580c";
    if (criticidades.includes("medio")) return "#ca8a04";
    return "#2563eb";
  };

  const pipelineCards = [
    { key: "agendado", label: "Agendados", count: agendados, color: "#22c55e" },
    { key: "disparado", label: "Disparados", count: disparados, color: "#3b82f6" },
    { key: "lido", label: "Lidos", count: lidos, color: "#6b7280" },
    { key: "cancelado", label: "Cancelados", count: cancelados, color: "#ef4444" },
  ];

  const tabs: { id: TabId; label: string }[] = [
    { id: "ativos", label: "Ativos" },
    { id: "historico", label: "Historico" },
    { id: "calendario", label: "Calendario" },
    { id: "silenciados", label: "Silenciados" },
  ];

  return (
    <div className="page-container" onClick={() => { setMenuOpenId(null); setCalendarPopoverDay(null); }}>
      <div className="page-header">
        <div className="page-header-left">
          <Flag size={24} />
          <div>
            <h1>Flags e Alertas</h1>
            <p>Pendencias, alertas e lembretes</p>
          </div>
        </div>
      </div>

      <div className="page-content">
        {/* Tabs */}
        <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
          {tabs.map(t => (
            <button key={t.id} className={`btn ${activeTab === t.id ? "btn-primary" : "btn-secondary"}`} onClick={() => setActiveTab(t.id)}>
              {t.label}
            </button>
          ))}
        </div>

        {activeTab === "ativos" && (
          <>
            {/* Stat cards criticidade */}
            <div className="stats-row" style={{ display: "flex", gap: 12, marginBottom: 16 }}>
              {([["critico", criticos, "#dc2626"], ["alto", altos, "#ea580c"], ["medio", medios, "#ca8a04"], ["informativo", informativos, "#2563eb"]] as const).map(([key, count, color]) => (
                <div key={key} className="stat-card" style={{ flex: 1, cursor: "pointer", border: filtroCriticidade === key ? `2px solid ${color}` : "2px solid transparent" }} onClick={() => setFiltroCriticidade(filtroCriticidade === key ? "" : key)}>
                  <div className="stat-content" style={{ textAlign: "center" }}>
                    <span className="stat-value" style={{ color }}>{count}</span>
                    <span className="stat-label">{CRITICIDADE_CONFIG[key].label}s</span>
                  </div>
                </div>
              ))}
            </div>

            {/* Pipeline cards */}
            <Card title="Pipeline de Alertas" icon={<Bell size={18} />}>
              <div style={{ display: "flex", gap: 16 }}>
                {pipelineCards.map(p => (
                  <div key={p.key} onClick={() => setStatusFilter(statusFilter === p.key ? "todos" : p.key)}
                    style={{ flex: 1, padding: 16, borderRadius: 8, cursor: "pointer", border: statusFilter === p.key ? `2px solid ${p.color}` : "2px solid transparent", background: statusFilter === p.key ? `${p.color}10` : "#f9fafb", textAlign: "center", transition: "all 0.2s" }}>
                    <div style={{ fontSize: 28, fontWeight: 700, color: p.color }}>{p.count}</div>
                    <div style={{ fontSize: 13, color: "#6b7280", marginTop: 4 }}>{p.label}</div>
                  </div>
                ))}
              </div>
              {statusFilter !== "todos" && (
                <div style={{ marginTop: 8, textAlign: "center" }}>
                  <button className="btn btn-sm btn-secondary" onClick={() => setStatusFilter("todos")}>
                    <Eye size={12} /> Mostrar todos
                  </button>
                </div>
              )}
            </Card>

            {/* Filtros */}
            <Card title="Filtros" icon={<Eye size={18} />}>
              <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
                <FormField label="Tipo">
                  <SelectInput value={filtroTipo} onChange={setFiltroTipo} options={[
                    { value: "", label: "Todos" },
                    { value: "abertura", label: "Abertura" }, { value: "impugnacao", label: "Impugnacao" },
                    { value: "recursos", label: "Recursos" }, { value: "proposta", label: "Proposta" },
                    { value: "contrato_vencimento", label: "Contrato" }, { value: "entrega_prazo", label: "Entrega" },
                  ]} />
                </FormField>
                <FormField label="Criticidade">
                  <SelectInput value={filtroCriticidade} onChange={setFiltroCriticidade} options={[
                    { value: "", label: "Todas" },
                    { value: "critico", label: "Critico" }, { value: "alto", label: "Alto" },
                    { value: "medio", label: "Medio" }, { value: "informativo", label: "Informativo" },
                  ]} />
                </FormField>
                <FormField label="Periodo">
                  <SelectInput value={filtroPeriodo} onChange={setFiltroPeriodo} options={[
                    { value: "", label: "Todos" },
                    { value: "7", label: "7 dias" }, { value: "15", label: "15 dias" },
                    { value: "30", label: "30 dias" }, { value: "90", label: "90 dias" },
                  ]} />
                </FormField>
              </div>
            </Card>

            {/* Tabela */}
            <Card title={`Alertas Ativos (${tabData.length})`} icon={<Bell size={18} />}
              actions={<ActionButton icon={<Plus size={14} />} label="Novo Alerta" onClick={() => setShowCriarModal(true)} />}>
              <DataTable data={tabData} columns={ativosColumns} idKey="id" loading={loading} emptyMessage="Nenhum alerta ativo" />
            </Card>
          </>
        )}

        {activeTab === "historico" && (
          <>
            <div className="stats-row" style={{ display: "flex", gap: 12, marginBottom: 16 }}>
              {([["Total Disparados", histDisparados, "#3b82f6"], ["Reconhecidos", histReconhecidos, "#22c55e"], ["Cancelados", histCancelados, "#ef4444"], ["Taxa Reconhecimento", `${taxaReconhecimento}%`, "#8b5cf6"]] as [string, number | string, string][]).map(([label, value, color]) => (
                <div key={label} className="stat-card" style={{ flex: 1 }}>
                  <div className="stat-content" style={{ textAlign: "center" }}>
                    <span className="stat-value" style={{ color }}>{value}</span>
                    <span className="stat-label">{label}</span>
                  </div>
                </div>
              ))}
            </div>
            <Card title={`Historico (${tabData.length})`} icon={<Clock size={18} />}
              actions={<ActionButton icon={<Download size={14} />} label="Exportar CSV" onClick={handleExportCSV} />}>
              <DataTable data={tabData} columns={historicoColumns} idKey="id" loading={loading} emptyMessage="Nenhum alerta no historico" />
            </Card>
          </>
        )}

        {activeTab === "calendario" && (
          <Card title={`${mesesPt[agendaMes.month]} ${agendaMes.year}`} icon={<Calendar size={18} />}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 4, textAlign: "center", fontSize: 13 }}>
              {["D", "S", "T", "Q", "Q", "S", "S"].map((d, i) => (
                <div key={i} style={{ fontWeight: 600, color: "#9ca3af", padding: "6px 0" }}>{d}</div>
              ))}
              {Array.from({ length: agendaMes.primeiroDia }).map((_, i) => <div key={`e${i}`} />)}
              {Array.from({ length: agendaMes.diasNoMes }).map((_, i) => {
                const dia = i + 1;
                const alertasDia = agendaMes.diasMap.get(dia) || [];
                const temAlerta = alertasDia.length > 0;
                const isHoje = dia === new Date().getDate();
                const corDia = temAlerta ? getDayColor(alertasDia) : undefined;
                return (
                  <div key={dia} style={{ padding: "8px 2px", borderRadius: 6, background: temAlerta ? `${corDia}15` : isHoje ? "#f3f4f6" : "transparent", border: isHoje ? "2px solid #3b82f6" : "1px solid transparent", fontWeight: temAlerta ? 700 : 400, color: temAlerta ? corDia : "#374151", position: "relative", cursor: temAlerta ? "pointer" : "default" }}
                    onClick={(e) => { if (temAlerta) { e.stopPropagation(); setCalendarPopoverDay(calendarPopoverDay === dia ? null : dia); } }}>
                    {dia}
                    {temAlerta && (
                      <div style={{ fontSize: 10, fontWeight: 700, color: corDia, marginTop: 2 }}>{alertasDia.length}</div>
                    )}
                    {calendarPopoverDay === dia && alertasDia.length > 0 && (
                      <div style={{ position: "absolute", top: "100%", left: "50%", transform: "translateX(-50%)", background: "#fff", border: "1px solid #e5e7eb", borderRadius: 8, boxShadow: "0 4px 12px rgba(0,0,0,0.15)", zIndex: 100, minWidth: 220, padding: 8, textAlign: "left" }}
                        onClick={e => e.stopPropagation()}>
                        {alertasDia.map(a => (
                          <div key={a.id} style={{ padding: "4px 8px", fontSize: 11, borderBottom: "1px solid #f3f4f6" }}>
                            <div style={{ fontWeight: 600 }}>{a.titulo || a.tipo}</div>
                            <div style={{ color: "#6b7280" }}>{formatData(a.data_disparo)}</div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            <div style={{ marginTop: 16, fontSize: 11, color: "#9ca3af", display: "flex", gap: 16 }}>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}><div style={{ width: 8, height: 8, borderRadius: "50%", background: "#dc2626" }} /> Critico</span>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}><div style={{ width: 8, height: 8, borderRadius: "50%", background: "#ea580c" }} /> Alto</span>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}><div style={{ width: 8, height: 8, borderRadius: "50%", background: "#ca8a04" }} /> Medio</span>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}><div style={{ width: 8, height: 8, borderRadius: "50%", background: "#2563eb" }} /> Informativo</span>
            </div>
            <div style={{ marginTop: 8, fontSize: 11, color: "#9ca3af" }}>Dias com alertas agendados</div>
          </Card>
        )}

        {activeTab === "silenciados" && (
          <Card title={`Silenciados (${tabData.length})`} icon={<Clock size={18} />}>
            <DataTable data={tabData} columns={silenciadosColumns} idKey="id" loading={loading} emptyMessage="Nenhum alerta silenciado" />
          </Card>
        )}
      </div>

      {/* Modal Criar Alerta */}
      <Modal isOpen={showCriarModal} onClose={() => setShowCriarModal(false)} title="Criar Alerta via IA"
        footer={<><button className="btn btn-secondary" onClick={() => setShowCriarModal(false)}>Cancelar</button>
          <button className="btn btn-primary" onClick={handleCriarAlerta} disabled={!novoEdital}><Bell size={14} /> Criar Alerta</button></>}>
        <FormField label="Numero do Edital" required>
          <input type="text" className="form-input" value={novoEdital} onChange={(e) => setNovoEdital(e.target.value)} placeholder="Ex: PE-001/2026" />
        </FormField>
        <FormField label="Tipo de Alerta" required>
          <SelectInput value={novoTipo} onChange={setNovoTipo} options={[
            { value: "abertura", label: "Abertura do Edital" }, { value: "impugnacao", label: "Prazo de Impugnacao" },
            { value: "recursos", label: "Prazo de Recursos" }, { value: "proposta", label: "Prazo para Proposta" },
            { value: "entrega_prazo", label: "Prazo de Entrega" },
          ]} />
        </FormField>
        <FormField label="Antecedencia">
          <div className="checkbox-group">
            <Checkbox checked={antecedencia24h} onChange={setAntecedencia24h} label="24 horas" />
            <Checkbox checked={antecedencia1h} onChange={setAntecedencia1h} label="1 hora" />
            <Checkbox checked={antecedencia15min} onChange={setAntecedencia15min} label="15 minutos" />
          </div>
        </FormField>
        <p style={{ fontSize: 12, color: "#6b7280", marginTop: 8 }}>O alerta sera criado via chat com a IA, que calculara as datas automaticamente.</p>
      </Modal>

      {/* Modal Silenciar */}
      <Modal isOpen={!!silenciarAlerta} onClose={() => setSilenciarAlerta(null)} title="Silenciar Alerta"
        footer={<><button className="btn btn-secondary" onClick={() => setSilenciarAlerta(null)}>Cancelar</button>
          <button className="btn btn-primary" onClick={handleSilenciar} disabled={!silenciarAte}>Silenciar</button></>}>
        <p style={{ fontSize: 13, marginBottom: 12 }}>Silenciando: <strong>{silenciarAlerta?.titulo}</strong></p>
        <FormField label="Silenciar ate" required>
          <input type="datetime-local" className="form-input" value={silenciarAte} onChange={e => setSilenciarAte(e.target.value)} />
        </FormField>
        <FormField label="Motivo">
          <textarea className="form-input" rows={3} value={silenciarMotivo} onChange={e => setSilenciarMotivo(e.target.value)} placeholder="Motivo do silenciamento..." />
        </FormField>
      </Modal>
    </div>
  );
}
