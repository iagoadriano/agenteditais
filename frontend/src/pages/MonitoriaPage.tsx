import { useState, useEffect, useCallback, useMemo } from "react";
import type { PageProps } from "../types";
import { Radio, Plus, Play, Pause, Trash2, Eye, FileSearch, Globe, AlertCircle, Zap, Edit2, Monitor, Loader2 } from "lucide-react";
import { Card, DataTable, ActionButton, Modal, FormField, TextInput, SelectInput, Checkbox } from "../components/common";
import type { Column } from "../components/common";
import { crudList, crudUpdate, crudDelete } from "../api/crud";
import { executarMonitoramento } from "../api/sprint6";
import { criarMonitoramentoSessao } from "../api/sprint9";

interface Monitoramento {
  id: string;
  termo: string;
  ncm: string | null;
  fontes: string[] | null;
  ufs: string[] | null;
  frequencia_horas: number;
  ultimo_check: string | null;
  proximo_check: string | null;
  score_minimo_alerta: number;
  ativo: boolean;
  editais_encontrados: number;
  created_at: string | null;
  updated_at: string | null;
  tipo?: string;
  edital_id?: string;
  sessao_pregao_id?: string;
}

interface EditalEvento {
  id: string;
  numero: string | null;
  orgao: string | null;
  uf: string | null;
  modalidade: string | null;
  created_at: string | null;
}

type TabId = "ativos" | "eventos" | "erros";

export function MonitoriaPage({ onSendToChat }: PageProps) {
  const [monitoramentos, setMonitoramentos] = useState<Monitoramento[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<TabId>("ativos");
  const [showCriarModal, setShowCriarModal] = useState(false);
  const [detailMon, setDetailMon] = useState<Monitoramento | null>(null);
  const [editingMon, setEditingMon] = useState<Monitoramento | null>(null);
  const [editForm, setEditForm] = useState({ termo: "", ufs: "", frequencia: "4" });

  // Eventos tab
  const [eventos, setEventos] = useState<EditalEvento[]>([]);
  const [eventosLoading, setEventosLoading] = useState(false);
  const [filtroMonEvento, setFiltroMonEvento] = useState("");

  // Erros tab
  const [erroDetailMon, setErroDetailMon] = useState<Monitoramento | null>(null);

  // Criar modal
  const [novoTermo, setNovoTermo] = useState("");
  const [novasUfs, setNovasUfs] = useState("");
  const [frequencia, setFrequencia] = useState("6");
  const [notificarEmail, setNotificarEmail] = useState(true);

  // Sessao Pregao form (UC-LA05)
  const [showSessaoForm, setShowSessaoForm] = useState(false);
  const [sessaoEditalId, setSessaoEditalId] = useState("");
  const [sessaoTermo, setSessaoTermo] = useState("Sessao de Pregao");
  const [sessaoNotificar, setSessaoNotificar] = useState(true);
  const [sessaoSubmitting, setSessaoSubmitting] = useState(false);

  const fetchMonitoramentos = useCallback(async () => {
    setLoading(true);
    try {
      const res = await crudList("monitoramentos", { limit: 200 });
      setMonitoramentos((res.items || []) as unknown as Monitoramento[]);
    } catch (e) { console.error("Erro:", e); }
    setLoading(false);
  }, []);

  useEffect(() => { fetchMonitoramentos(); }, [fetchMonitoramentos]);

  const fetchEventos = useCallback(async () => {
    setEventosLoading(true);
    try {
      const termos = filtroMonEvento
        ? [monitoramentos.find(m => m.id === filtroMonEvento)?.termo].filter(Boolean)
        : monitoramentos.filter(m => m.ativo).map(m => m.termo);
      const allEditais: EditalEvento[] = [];
      for (const _termo of termos) {
        // NOTA: o parametro de busca por termo nunca chegava ao backend
        // (crudList nao serializa "search"); o filtro provavelmente deveria usar "q".
        const res = await crudList("editais", { limit: 50 });
        (res.items || []).forEach((ed: any) => {
          if (!allEditais.find(e => e.id === ed.id)) {
            allEditais.push({ id: ed.id, numero: ed.numero || ed.id, orgao: ed.orgao, uf: ed.uf, modalidade: ed.modalidade, created_at: ed.created_at });
          }
        });
      }
      setEventos(allEditais);
    } catch { setEventos([]); }
    setEventosLoading(false);
  }, [monitoramentos, filtroMonEvento]);

  useEffect(() => {
    if (activeTab === "eventos" && monitoramentos.length > 0) fetchEventos();
  }, [activeTab, fetchEventos, monitoramentos.length]);

  const ativos = monitoramentos.filter(m => m.ativo).length;
  const pausados = monitoramentos.filter(m => !m.ativo).length;
  const totalEncontrados = monitoramentos.reduce((s, m) => s + (m.editais_encontrados || 0), 0);
  const comErro = useMemo(() => monitoramentos.filter(m => {
    if (!m.ativo || !m.ultimo_check) return false;
    const lastCheck = new Date(m.ultimo_check).getTime();
    return (Date.now() - lastCheck) > (m.frequencia_horas || 6) * 3 * 3600000;
  }), [monitoramentos]);

  const handleToggleStatus = async (mon: Monitoramento) => {
    await crudUpdate("monitoramentos", mon.id, { ativo: !mon.ativo });
    fetchMonitoramentos();
  };

  const handleExcluir = async (id: string) => {
    await crudDelete("monitoramentos", id);
    if (detailMon?.id === id) setDetailMon(null);
    fetchMonitoramentos();
  };

  const handleExecutar = async (id: string) => {
    try {
      await executarMonitoramento(id);
      fetchMonitoramentos();
    } catch (e) { console.error("Erro:", e); }
  };

  const handleEditar = (mon: Monitoramento) => {
    setEditForm({ termo: mon.termo, ufs: mon.ufs?.join(", ") || "", frequencia: String(mon.frequencia_horas) });
    setEditingMon(mon);
  };

  const handleSaveEditar = async () => {
    if (!editingMon) return;
    const ufs = editForm.ufs ? editForm.ufs.split(",").map(s => s.trim()).filter(Boolean) : null;
    await crudUpdate("monitoramentos", editingMon.id, {
      termo: editForm.termo,
      ufs: ufs,
      frequencia_horas: parseInt(editForm.frequencia) || 4,
    });
    setEditingMon(null);
    fetchMonitoramentos();
  };

  const handleCriarMonitoramento = () => {
    if (!onSendToChat || !novoTermo) return;
    const ufsStr = novasUfs ? ` ufs=${novasUfs}` : "";
    const emailStr = notificarEmail ? " notificar_email=sim" : "";
    onSendToChat(`configurar monitoramento termo="${novoTermo}" frequencia=${frequencia}h${ufsStr}${emailStr}`);
    setShowCriarModal(false);
    setNovoTermo("");
    setTimeout(fetchMonitoramentos, 3000);
  };

  const handleCriarSessaoPregao = async () => {
    if (!sessaoEditalId.trim()) return;
    setSessaoSubmitting(true);
    try {
      await criarMonitoramentoSessao({
        edital_id: sessaoEditalId.trim(),
        termo: sessaoTermo || "Sessao de Pregao",
        notificar_email: sessaoNotificar,
      });
      setShowSessaoForm(false);
      setSessaoEditalId("");
      setSessaoTermo("Sessao de Pregao");
      setSessaoNotificar(true);
      fetchMonitoramentos();
    } catch (e) {
      console.error("Erro ao criar monitoramento de sessao:", e);
    } finally {
      setSessaoSubmitting(false);
    }
  };

  const formatData = (iso: string | null) => {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }); } catch { return iso; }
  };

  const monColumns: Column<Monitoramento>[] = [
    { key: "termo", header: "Termo", sortable: true },
    { key: "fontes", header: "Fontes", render: m => m.fontes?.length ? m.fontes.map(f => <span key={f} className="status-badge status-badge-neutral" style={{ marginRight: 4 }}>{f}</span>) : "—" },
    { key: "ufs", header: "UFs", render: m => m.ufs?.join(", ") || "Todos" },
    { key: "frequencia_horas", header: "Freq.", render: m => `${m.frequencia_horas}h` },
    { key: "ultimo_check", header: "Ultimo Check", render: m => formatData(m.ultimo_check) },
    { key: "proximo_check", header: "Proximo", render: m => formatData(m.proximo_check) },
    { key: "editais_encontrados", header: "Encontrados", render: m => <span className={m.editais_encontrados > 0 ? "badge-new" : ""}>{m.editais_encontrados || 0}</span>, sortable: true },
    { key: "ativo", header: "Status", render: m => (
      <div style={{ display: "flex", gap: 4, alignItems: "center", flexWrap: "wrap" }}>
        <span className={`status-badge ${m.ativo ? "status-badge-success" : "status-badge-neutral"}`}>{m.ativo ? "Ativo" : "Pausado"}</span>
        {m.tipo === "sessao_pregao" && (
          <span style={{ backgroundColor: "#dbeafe", color: "#2563eb", padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600 }}>Sessao</span>
        )}
      </div>
    ) },
    {
      key: "acoes", header: "Acoes", width: "100px",
      render: m => (
        <div className="table-actions">
          <button title={m.ativo ? "Pausar" : "Ativar"} onClick={(e) => { e.stopPropagation(); handleToggleStatus(m); }}>{m.ativo ? <Pause size={16} /> : <Play size={16} />}</button>
          <button title="Excluir" className="danger" onClick={(e) => { e.stopPropagation(); handleExcluir(m.id); }}><Trash2 size={16} /></button>
        </div>
      ),
    },
  ];

  const eventoColumns: Column<EditalEvento>[] = [
    { key: "created_at", header: "Data Captura", render: e => formatData(e.created_at), sortable: true },
    { key: "numero", header: "Edital", render: e => e.numero || e.id.slice(0, 8) },
    { key: "orgao", header: "Orgao", render: e => e.orgao || "—" },
    { key: "uf", header: "UF", render: e => e.uf || "—" },
    { key: "modalidade", header: "Modalidade", render: e => e.modalidade || "—" },
  ];

  const erroColumns: Column<Monitoramento>[] = [
    { key: "termo", header: "Termo", sortable: true },
    { key: "ufs", header: "UFs", render: m => m.ufs?.join(", ") || "Todos" },
    { key: "frequencia_horas", header: "Freq.", render: m => `${m.frequencia_horas}h` },
    { key: "ultimo_check", header: "Ultimo Check", render: m => {
      const horasAtraso = m.ultimo_check ? Math.round((Date.now() - new Date(m.ultimo_check).getTime()) / 3600000) : 0;
      return <span style={{ color: "#dc2626" }}>{formatData(m.ultimo_check)} <strong>({horasAtraso}h atraso)</strong></span>;
    }},
    { key: "ativo", header: "Status", render: () => <span className="status-badge status-badge-error">Erro</span> },
    {
      key: "acoes", header: "", width: "80px",
      render: m => <button className="btn btn-sm btn-secondary" onClick={(e) => { e.stopPropagation(); setErroDetailMon(m); }}>Diagnostico</button>,
    },
  ];

  const tabs: { id: TabId; label: string; badge?: number }[] = [
    { id: "ativos", label: "Ativos" },
    { id: "eventos", label: "Eventos Capturados" },
    { id: "erros", label: "Erros", badge: comErro.length },
  ];

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-left">
          <Radio size={24} />
          <div>
            <h1>Monitoramento Automatico</h1>
            <p>Configuracao de buscas automaticas de editais</p>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <ActionButton icon={<FileSearch size={14} />} label="Analisar Documentos" variant="secondary" onClick={() => onSendToChat?.("analise os documentos da empresa atual")} />
          <ActionButton icon={<Globe size={14} />} label="Verificar PNCP" variant="secondary" onClick={() => onSendToChat?.("verifique pendencias do CNPJ no PNCP")} />
        </div>
      </div>

      <div className="page-content">
        {/* Tabs */}
        <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
          {tabs.map(t => (
            <button key={t.id} className={`btn ${activeTab === t.id ? "btn-primary" : "btn-secondary"}`} onClick={() => setActiveTab(t.id)} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {t.label}
              {t.badge !== undefined && t.badge > 0 && <span style={{ background: "#ef4444", color: "#fff", borderRadius: "50%", width: 18, height: 18, fontSize: 11, display: "flex", alignItems: "center", justifyContent: "center" }}>{t.badge}</span>}
            </button>
          ))}
        </div>

        {activeTab === "ativos" && (
          <>
            <Card title="Resumo" icon={<Radio size={18} />}>
              <div className="stats-row">
                {([
                  { icon: <Play size={24} />, cls: "success", value: ativos, label: "Ativos" },
                  { icon: <Pause size={24} />, cls: "warning", value: pausados, label: "Pausados" },
                  { icon: <Eye size={24} />, cls: "info", value: totalEncontrados, label: "Editais encontrados" },
                  { icon: <AlertCircle size={24} />, cls: "error", value: comErro.length, label: "Com erro" },
                ] as const).map((s, i) => (
                  <div key={i} className="stat-card">
                    <div className={`stat-icon ${s.cls}`}>{s.icon}</div>
                    <div className="stat-content">
                      <span className="stat-value">{s.value}</span>
                      <span className="stat-label">{s.label}</span>
                    </div>
                  </div>
                ))}
              </div>
            </Card>

            <Card title="Monitoramentos" icon={<Radio size={18} />}
              actions={
                <div style={{ display: "flex", gap: 6 }}>
                  <ActionButton icon={<Plus size={14} />} label="Novo Monitoramento" onClick={() => setShowCriarModal(true)} />
                  <ActionButton icon={<Monitor size={14} />} label="Monitorar Sessao de Pregao" variant="secondary" onClick={() => setShowSessaoForm(!showSessaoForm)} />
                </div>
              }>

              {/* Sessao de Pregao form (UC-LA05) */}
              {showSessaoForm && (
                <div
                  style={{
                    marginBottom: 16,
                    padding: 16,
                    background: "#eff6ff",
                    border: "1px solid #bfdbfe",
                    borderRadius: 8,
                  }}
                >
                  <h4 style={{ margin: "0 0 12px 0", fontSize: 14, display: "flex", alignItems: "center", gap: 6 }}>
                    <Monitor size={16} />
                    Monitorar Sessao de Pregao
                  </h4>
                  <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
                    <FormField label="Edital ID" required>
                      <TextInput
                        value={sessaoEditalId}
                        onChange={setSessaoEditalId}
                        placeholder="ID do edital..."
                      />
                    </FormField>
                    <FormField label="Termo">
                      <TextInput
                        value={sessaoTermo}
                        onChange={setSessaoTermo}
                        placeholder="Sessao de Pregao"
                      />
                    </FormField>
                    <FormField label="Notificar">
                      <Checkbox checked={sessaoNotificar} onChange={setSessaoNotificar} label="Email" />
                    </FormField>
                    <div style={{ display: "flex", gap: 6, paddingBottom: 2 }}>
                      <button
                        className="btn btn-primary"
                        onClick={handleCriarSessaoPregao}
                        disabled={!sessaoEditalId.trim() || sessaoSubmitting}
                        style={{ fontSize: 13 }}
                      >
                        {sessaoSubmitting ? <Loader2 size={14} className="spin" /> : <Monitor size={14} />}
                        {" "}Criar
                      </button>
                      <button
                        className="btn btn-secondary"
                        onClick={() => setShowSessaoForm(false)}
                        style={{ fontSize: 13 }}
                      >
                        Cancelar
                      </button>
                    </div>
                  </div>
                </div>
              )}

              <DataTable data={monitoramentos} columns={monColumns} idKey="id" loading={loading}
                onRowClick={m => setDetailMon(m)} selectedId={detailMon?.id} emptyMessage="Nenhum monitoramento configurado" />
            </Card>
          </>
        )}

        {activeTab === "eventos" && (
          <>
            <Card title="Filtros" icon={<Eye size={18} />}>
              <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
                <FormField label="Monitoramento">
                  <SelectInput value={filtroMonEvento} onChange={setFiltroMonEvento}
                    options={[{ value: "", label: "Todos" }, ...monitoramentos.map(m => ({ value: m.id, label: m.termo }))]} />
                </FormField>
              </div>
            </Card>
            <Card title={`Eventos Capturados (${eventos.length})`} icon={<Eye size={18} />}>
              <DataTable data={eventos} columns={eventoColumns} idKey="id" loading={eventosLoading} emptyMessage="Nenhum evento capturado" />
            </Card>
          </>
        )}

        {activeTab === "erros" && (
          <Card title={`Monitoramentos com Erro (${comErro.length})`} icon={<AlertCircle size={18} />}>
            {comErro.length === 0 ? (
              <p style={{ color: "#9ca3af", textAlign: "center", padding: 24 }}>Nenhum monitoramento com erro</p>
            ) : (
              <DataTable data={comErro} columns={erroColumns} idKey="id" loading={loading}
                onRowClick={m => setErroDetailMon(m)} emptyMessage="Nenhum erro" />
            )}
          </Card>
        )}
      </div>

      {/* Modal Detalhe Monitoramento */}
      <Modal isOpen={!!detailMon} onClose={() => setDetailMon(null)} title={`Detalhe: "${detailMon?.termo || ""}"`} size="large"
        footer={detailMon ? <>
          <button className="btn btn-secondary" onClick={() => { handleToggleStatus(detailMon); setDetailMon(null); }}>
            {detailMon.ativo ? <><Pause size={14} /> Pausar</> : <><Play size={14} /> Reativar</>}
          </button>
          <button className="btn btn-secondary" onClick={() => { handleExecutar(detailMon.id); setDetailMon(null); }}>
            <Zap size={14} /> Executar Agora
          </button>
          <button className="btn btn-secondary" onClick={() => { setDetailMon(null); handleEditar(detailMon); }}>
            <Edit2 size={14} /> Editar
          </button>
          <button className="btn btn-secondary danger" onClick={() => { handleExcluir(detailMon.id); setDetailMon(null); }}>
            <Trash2 size={14} /> Excluir
          </button>
        </> : undefined}>
        {detailMon && (
          <div className="info-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
            <div className="info-item"><label>Termo</label><span>{detailMon.termo}</span></div>
            <div className="info-item"><label>NCM</label><span>{detailMon.ncm || "—"}</span></div>
            <div className="info-item"><label>UFs</label><span>{detailMon.ufs?.join(", ") || "Todos"}</span></div>
            <div className="info-item"><label>Frequencia</label><span>{detailMon.frequencia_horas}h</span></div>
            <div className="info-item"><label>Score minimo</label><span>{detailMon.score_minimo_alerta}%</span></div>
            <div className="info-item"><label>Encontrados</label><span style={{ fontWeight: 700, color: "#3b82f6" }}>{detailMon.editais_encontrados || 0}</span></div>
            <div className="info-item"><label>Ultimo check</label><span>{formatData(detailMon.ultimo_check)}</span></div>
            <div className="info-item"><label>Proximo check</label><span>{formatData(detailMon.proximo_check)}</span></div>
            <div className="info-item"><label>Criado em</label><span>{formatData(detailMon.created_at)}</span></div>
            <div className="info-item"><label>Fontes</label><span>{detailMon.fontes?.join(", ") || "Padrao"}</span></div>
            <div className="info-item"><label>Status</label><span className={`status-badge ${detailMon.ativo ? "status-badge-success" : "status-badge-neutral"}`}>{detailMon.ativo ? "Ativo" : "Pausado"}</span></div>
          </div>
        )}
      </Modal>

      {/* Modal Editar Monitoramento */}
      <Modal isOpen={!!editingMon} onClose={() => setEditingMon(null)} title="Editar Monitoramento"
        footer={<><button className="btn btn-secondary" onClick={() => setEditingMon(null)}>Cancelar</button>
          <button className="btn btn-primary" onClick={handleSaveEditar}>Salvar</button></>}>
        <FormField label="Termo de busca" required>
          <TextInput value={editForm.termo} onChange={v => setEditForm({ ...editForm, termo: v })} />
        </FormField>
        <FormField label="UFs (separar por virgula)">
          <TextInput value={editForm.ufs} onChange={v => setEditForm({ ...editForm, ufs: v })} placeholder="SP, MG, RJ" />
        </FormField>
        <FormField label="Frequencia (horas)">
          <TextInput value={editForm.frequencia} onChange={v => setEditForm({ ...editForm, frequencia: v })} />
        </FormField>
      </Modal>

      {/* Modal Diagnostico de Erro */}
      <Modal isOpen={!!erroDetailMon} onClose={() => setErroDetailMon(null)} title="Diagnostico de Erro"
        footer={erroDetailMon ? <>
          <button className="btn btn-secondary" onClick={() => { handleToggleStatus(erroDetailMon); setErroDetailMon(null); }}>Reiniciar</button>
          <button className="btn btn-secondary" onClick={() => { handleExecutar(erroDetailMon.id); setErroDetailMon(null); }}><Zap size={14} /> Executar Agora</button>
          <button className="btn btn-secondary" onClick={() => { setErroDetailMon(null); handleEditar(erroDetailMon); }}><Edit2 size={14} /> Editar</button>
          <button className="btn btn-secondary danger" onClick={() => { handleExcluir(erroDetailMon.id); setErroDetailMon(null); }}><Trash2 size={14} /> Excluir</button>
        </> : undefined}>
        {erroDetailMon && (
          <div style={{ fontSize: 13 }}>
            <div className="info-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
              <div className="info-item"><label>Termo</label><span>{erroDetailMon.termo}</span></div>
              <div className="info-item"><label>Frequencia</label><span>{erroDetailMon.frequencia_horas}h (limite: {erroDetailMon.frequencia_horas * 3}h)</span></div>
              <div className="info-item"><label>Ultimo check</label><span style={{ color: "#dc2626" }}>{formatData(erroDetailMon.ultimo_check)}</span></div>
              <div className="info-item"><label>Atraso</label><span style={{ color: "#dc2626", fontWeight: 700 }}>{erroDetailMon.ultimo_check ? Math.round((Date.now() - new Date(erroDetailMon.ultimo_check).getTime()) / 3600000) : "?"}h</span></div>
            </div>
            <div style={{ padding: 12, background: "#fef2f2", borderRadius: 6, border: "1px solid #fecaca" }}>
              <strong>Diagnostico:</strong> O ultimo check excedeu o limite de {erroDetailMon.frequencia_horas * 3}h. Possiveis causas: servico de monitoramento parado, erro de conexao com fonte de dados, ou timeout na busca.
            </div>
          </div>
        )}
      </Modal>

      {/* Modal Criar */}
      <Modal isOpen={showCriarModal} onClose={() => setShowCriarModal(false)} title="Criar Monitoramento via IA"
        footer={<><button className="btn btn-secondary" onClick={() => setShowCriarModal(false)}>Cancelar</button>
          <button className="btn btn-primary" onClick={handleCriarMonitoramento} disabled={!novoTermo}><Radio size={14} /> Criar Monitoramento</button></>}>
        <FormField label="Termo de busca" required>
          <TextInput value={novoTermo} onChange={setNovoTermo} placeholder="Ex: microscopio, centrifuga, reagente..." />
        </FormField>
        <FormField label="Estados (UFs) - separar por virgula">
          <TextInput value={novasUfs} onChange={setNovasUfs} placeholder="Ex: SP, MG, RJ (vazio = todos)" />
        </FormField>
        <FormField label="Frequencia (horas)">
          <TextInput value={frequencia} onChange={setFrequencia} placeholder="6" />
        </FormField>
        <FormField label="Notificar por">
          <div className="checkbox-group"><Checkbox checked={notificarEmail} onChange={setNotificarEmail} label="Email" /></div>
        </FormField>
        <p style={{ fontSize: 12, color: "#6b7280", marginTop: 8 }}>O monitoramento sera configurado via chat com a IA.</p>
      </Modal>
    </div>
  );
}
