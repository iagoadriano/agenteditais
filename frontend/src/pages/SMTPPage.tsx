import { useState, useEffect, useCallback, useMemo } from "react";
import type { PageProps } from "../types";
import { Mail, Settings, FileText, Send, RefreshCw, CheckCircle, AlertCircle, Clock, Edit2, Save, Plus, X, Eye, Bold, Italic, Link, Percent } from "lucide-react";
import { Card, DataTable, ActionButton, Modal, FormField, SelectInput } from "../components/common";
import type { Column } from "../components/common";
import { crudList, crudUpdate, crudCreate, crudDelete } from "../api/crud";
import { testarSMTP, reenviarEmailFila } from "../api/sprint6";

interface SMTPConfig {
  id: string;
  host: string;
  port: number;
  user: string | null;
  password_encrypted: string | null;
  from_email: string;
  from_name: string | null;
  tls_enabled: boolean;
  smtp_live_mode: boolean;
  updated_at: string | null;
}

interface EmailTemplate {
  id: string;
  slug: string;
  nome: string;
  assunto: string;
  corpo_html: string;
  corpo_text: string | null;
  variaveis_json: string[] | null;
  ativo: boolean;
  versao: number;
  updated_at: string | null;
}

interface EmailQueueItem {
  id: string;
  destinatario: string;
  assunto: string;
  corpo_html: string | null;
  template_slug: string | null;
  status: string;
  retry_count: number;
  max_retries: number;
  erro_mensagem: string | null;
  enviado_em: string | null;
  created_at: string | null;
}

export function SMTPPage(_props: PageProps) {
  const [activeTab, setActiveTab] = useState<"config" | "templates" | "fila">("config");

  // Config
  const [configs, setConfigs] = useState<SMTPConfig[]>([]);
  const [configLoading, setConfigLoading] = useState(true);
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const [testEmail, setTestEmail] = useState("");
  const [showConfirmLive, setShowConfirmLive] = useState(false);
  const [editing, setEditing] = useState(false);
  const [cfgForm, setCfgForm] = useState({ host: "", port: "587", user: "", password: "", from_email: "", from_name: "", seguranca: "tls" });
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; msg: string } | null>(null);

  // Templates
  const [templates, setTemplates] = useState<EmailTemplate[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [editingTemplate, setEditingTemplate] = useState<EmailTemplate | null>(null);
  const [editAssunto, setEditAssunto] = useState("");
  const [editCorpo, setEditCorpo] = useState("");
  const [saveTemplateMsg, setSaveTemplateMsg] = useState("");

  // Fila
  const [fila, setFila] = useState<EmailQueueItem[]>([]);
  const [filaLoading, setFilaLoading] = useState(true);
  const [filaDetailItem, setFilaDetailItem] = useState<EmailQueueItem | null>(null);
  const [filtroFilaStatus, setFiltroFilaStatus] = useState("");
  const [filtroFilaDest, setFiltroFilaDest] = useState("");
  const [filtroFilaPeriodo, setFiltroFilaPeriodo] = useState("");

  const fetchConfig = useCallback(async () => {
    setConfigLoading(true);
    try { const res = await crudList("smtp-config", { limit: 10 }); setConfigs((res.items || []) as unknown as SMTPConfig[]); } catch (e) { console.error(e); }
    setConfigLoading(false);
  }, []);

  const fetchTemplates = useCallback(async () => {
    setTemplatesLoading(true);
    try { const res = await crudList("email-templates", { limit: 100 }); setTemplates((res.items || []) as unknown as EmailTemplate[]); } catch (e) { console.error(e); }
    setTemplatesLoading(false);
  }, []);

  const fetchFila = useCallback(async () => {
    setFilaLoading(true);
    try { const res = await crudList("email-queue", { limit: 500 }); setFila((res.items || []) as unknown as EmailQueueItem[]); } catch (e) { console.error(e); }
    setFilaLoading(false);
  }, []);

  useEffect(() => {
    if (activeTab === "config") fetchConfig();
    else if (activeTab === "templates") fetchTemplates();
    else fetchFila();
  }, [activeTab, fetchConfig, fetchTemplates, fetchFila]);

  useEffect(() => {
    if (activeTab === "fila") { const t = setInterval(fetchFila, 10000); return () => clearInterval(t); }
  }, [activeTab, fetchFila]);

  const config = configs[0] || null;

  const handleTestarSMTP = async () => {
    if (!testEmail) return;
    setTestResult(null);
    try { const res = await testarSMTP(testEmail); setTestResult({ ok: res.success, msg: res.message }); }
    catch (e: any) { setTestResult({ ok: false, msg: e.message || "Erro desconhecido" }); }
  };

  const startEdit = () => {
    if (config) {
      const seg = config.tls_enabled ? (config.port === 465 ? "ssl" : "tls") : "none";
      setCfgForm({ host: config.host || "", port: String(config.port || 587), user: config.user || "", password: "", from_email: config.from_email || "", from_name: config.from_name || "", seguranca: seg });
    } else {
      setCfgForm({ host: "", port: "587", user: "", password: "", from_email: "", from_name: "", seguranca: "tls" });
    }
    setSaveMsg(null);
    setEditing(true);
  };

  const handleSaveConfig = async () => {
    setSaving(true); setSaveMsg(null);
    try {
      const tls = cfgForm.seguranca !== "none";
      const port = cfgForm.seguranca === "ssl" ? 465 : parseInt(cfgForm.port) || 587;
      const payload: Record<string, any> = { host: cfgForm.host, port, user: cfgForm.user || null, from_email: cfgForm.from_email, from_name: cfgForm.from_name || null, tls_enabled: tls };
      if (cfgForm.password) payload.password_encrypted = cfgForm.password;
      if (config) { await crudUpdate("smtp-config", config.id, payload); }
      else { await crudCreate("smtp-config", payload); }
      setSaveMsg({ ok: true, msg: "Configuracao salva com sucesso" });
      setEditing(false);
      fetchConfig();
    } catch (e: any) { setSaveMsg({ ok: false, msg: e.message || "Erro ao salvar" }); }
    setSaving(false);
  };

  const handleToggleLiveMode = async () => {
    if (!config) return;
    if (!config.smtp_live_mode) { setShowConfirmLive(true); return; }
    await crudUpdate("smtp-config", config.id, { smtp_live_mode: false });
    fetchConfig();
  };

  const confirmLiveMode = async () => {
    if (!config) return;
    await crudUpdate("smtp-config", config.id, { smtp_live_mode: true });
    setShowConfirmLive(false);
    fetchConfig();
  };

  const handleSaveTemplate = async () => {
    if (!editingTemplate) return;
    const newVersao = (editingTemplate.versao || 0) + 1;
    await crudUpdate("email-templates", editingTemplate.id, { assunto: editAssunto, corpo_html: editCorpo, versao: newVersao });
    setSaveTemplateMsg(`Template salvo (versao ${newVersao})`);
    setTimeout(() => setSaveTemplateMsg(""), 3000);
    setEditingTemplate(null);
    fetchTemplates();
  };

  const handleReenviar = async (id: string) => {
    try { await reenviarEmailFila(id); fetchFila(); } catch (e) { console.error(e); }
  };

  const handleCancelarEmail = async (id: string) => {
    try { await crudDelete("email-queue", id); fetchFila(); setFilaDetailItem(null); } catch (e) { console.error(e); }
  };

  const insertTag = (tag: string) => {
    const el = document.querySelector("textarea.template-editor") as HTMLTextAreaElement;
    if (!el) return;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    const selected = editCorpo.slice(start, end);
    let insert = "";
    if (tag === "b") insert = `<strong>${selected || "texto"}</strong>`;
    else if (tag === "i") insert = `<em>${selected || "texto"}</em>`;
    else if (tag === "a") insert = `<a href="url">${selected || "link"}</a>`;
    const newCorpo = editCorpo.slice(0, start) + insert + editCorpo.slice(end);
    setEditCorpo(newCorpo);
  };

  const formatData = (iso: string | null) => {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); } catch { return iso; }
  };

  const getStatusBadge = (status: string) => {
    const map: Record<string, { cls: string; icon: React.ReactNode }> = {
      pending: { cls: "status-badge-warning", icon: <Clock size={12} /> },
      sending: { cls: "status-badge-info", icon: <Send size={12} /> },
      sent: { cls: "status-badge-success", icon: <CheckCircle size={12} /> },
      failed: { cls: "status-badge-error", icon: <AlertCircle size={12} /> },
      bounce: { cls: "status-badge-error", icon: <AlertCircle size={12} /> },
    };
    const m = map[status] || { cls: "status-badge-neutral", icon: null };
    return <span className={`status-badge ${m.cls}`}>{m.icon} {status}</span>;
  };

  const templateColumns: Column<EmailTemplate>[] = [
    { key: "slug", header: "Slug", sortable: true },
    { key: "nome", header: "Nome", sortable: true },
    { key: "assunto", header: "Assunto" },
    { key: "versao", header: "Versao", render: t => <span className="status-badge status-badge-neutral">v{t.versao || 1}</span> },
    { key: "updated_at", header: "Ultima Edicao", render: t => formatData(t.updated_at) },
    { key: "ativo", header: "Ativo", render: t => t.ativo ? <CheckCircle size={14} color="#22c55e" /> : <AlertCircle size={14} color="#9ca3af" /> },
    {
      key: "editar", header: "", width: "60px",
      render: t => <button className="btn btn-sm btn-secondary" onClick={() => { setEditingTemplate(t); setEditAssunto(t.assunto); setEditCorpo(t.corpo_html); }}>Editar</button>,
    },
  ];

  const filteredFila = useMemo(() => {
    let data = fila;
    if (filtroFilaStatus) data = data.filter(i => i.status === filtroFilaStatus);
    if (filtroFilaDest) data = data.filter(i => i.destinatario.toLowerCase().includes(filtroFilaDest.toLowerCase()));
    if (filtroFilaPeriodo) {
      const diasMs = parseInt(filtroFilaPeriodo) * 86400000;
      data = data.filter(i => i.created_at && new Date(i.created_at).getTime() >= Date.now() - diasMs);
    }
    return data;
  }, [fila, filtroFilaStatus, filtroFilaDest, filtroFilaPeriodo]);

  const filaColumns: Column<EmailQueueItem>[] = [
    { key: "created_at", header: "Data", render: i => formatData(i.created_at), sortable: true },
    { key: "destinatario", header: "Destinatario", sortable: true },
    { key: "assunto", header: "Assunto" },
    { key: "template_slug", header: "Template", render: i => i.template_slug || "—" },
    { key: "status", header: "Status", render: i => getStatusBadge(i.status) },
    { key: "retry_count", header: "Tentativas", render: i => `${i.retry_count}/${i.max_retries}` },
    { key: "erro_mensagem", header: "Ultima Mensagem", render: i => i.erro_mensagem ? <span style={{ color: "#dc2626", fontSize: 11 }}>{i.erro_mensagem.slice(0, 40)}</span> : "—" },
    {
      key: "acoes", header: "", width: "120px",
      render: i => (
        <div style={{ display: "flex", gap: 4 }}>
          <button className="btn-icon" title="Ver detalhes" onClick={() => setFilaDetailItem(i)}><Eye size={14} /></button>
          {(i.status === "failed" || i.status === "bounce") && (
            <button className="btn btn-sm btn-secondary" onClick={() => handleReenviar(i.id)}><RefreshCw size={12} /> Reenviar</button>
          )}
        </div>
      ),
    },
  ];

  const filaStats = useMemo(() => {
    const pending = fila.filter(i => i.status === "pending").length;
    const sent = fila.filter(i => i.status === "sent").length;
    const failed = fila.filter(i => i.status === "failed" || i.status === "bounce").length;
    const taxa = (sent + failed) > 0 ? Math.round(sent / (sent + failed) * 100) : 0;
    return { pending, sent, failed, taxa };
  }, [fila]);

  const segurancaLabel = config ? (config.tls_enabled ? (config.port === 465 ? "SSL" : "TLS/STARTTLS") : "Nenhuma") : "—";

  const tabs = [
    { key: "config" as const, label: "Configuracao", icon: <Settings size={14} /> },
    { key: "templates" as const, label: "Templates", icon: <FileText size={14} /> },
    { key: "fila" as const, label: "Fila de Envio", icon: <Send size={14} /> },
  ];

  const previewHtml = useMemo(() => {
    let html = editCorpo;
    const vars = editingTemplate?.variaveis_json || [];
    vars.forEach(v => { html = html.replace(new RegExp(`\\{\\{${v}\\}\\}`, "g"), `<em style="color:#6b7280">[${v}]</em>`); });
    return html;
  }, [editCorpo, editingTemplate]);

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-left">
          <Mail size={24} />
          <div>
            <h1>Configuracao SMTP</h1>
            <p>Email, templates e fila de envio</p>
          </div>
        </div>
      </div>

      <div className="page-content">
        <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
          {tabs.map(t => (
            <button key={t.key} className={`btn ${activeTab === t.key ? "btn-primary" : "btn-secondary"}`} onClick={() => setActiveTab(t.key)} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {t.icon} {t.label}
            </button>
          ))}
        </div>

        {activeTab === "config" && (
          <>
            <Card title="Configuracao SMTP" icon={<Settings size={18} />}
              actions={!editing ? <ActionButton icon={config ? <Edit2 size={14} /> : <Plus size={14} />} label={config ? "Editar" : "Criar Configuracao"} onClick={startEdit} /> : undefined}>
              {configLoading ? <p>Carregando...</p> : editing ? (
                <div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
                    <FormField label="Host SMTP">
                      <input type="text" className="form-input" value={cfgForm.host} onChange={e => setCfgForm({ ...cfgForm, host: e.target.value })} placeholder="smtp.gmail.com" />
                    </FormField>
                    <FormField label="Porta">
                      <input type="number" className="form-input" value={cfgForm.port} onChange={e => setCfgForm({ ...cfgForm, port: e.target.value })} placeholder="587" />
                    </FormField>
                    <FormField label="Usuario (login SMTP)">
                      <input type="text" className="form-input" value={cfgForm.user} onChange={e => setCfgForm({ ...cfgForm, user: e.target.value })} />
                    </FormField>
                    <FormField label={config ? "Senha (deixe vazio para manter)" : "Senha"}>
                      <input type="password" className="form-input" value={cfgForm.password} onChange={e => setCfgForm({ ...cfgForm, password: e.target.value })} />
                    </FormField>
                    <FormField label="Email remetente (From)">
                      <input type="email" className="form-input" value={cfgForm.from_email} onChange={e => setCfgForm({ ...cfgForm, from_email: e.target.value })} />
                    </FormField>
                    <FormField label="Nome remetente">
                      <input type="text" className="form-input" value={cfgForm.from_name} onChange={e => setCfgForm({ ...cfgForm, from_name: e.target.value })} />
                    </FormField>
                  </div>
                  <FormField label="Seguranca">
                    <SelectInput value={cfgForm.seguranca} onChange={v => setCfgForm({ ...cfgForm, seguranca: v })}
                      options={[{ value: "tls", label: "TLS/STARTTLS" }, { value: "ssl", label: "SSL" }, { value: "none", label: "Nenhuma" }]} />
                  </FormField>
                  <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
                    <ActionButton icon={<Save size={14} />} label={saving ? "Salvando..." : "Salvar Configuracao"} onClick={handleSaveConfig} disabled={!cfgForm.host || !cfgForm.from_email || saving} />
                    <button className="btn btn-secondary" onClick={() => setEditing(false)} style={{ display: "flex", alignItems: "center", gap: 6 }}><X size={14} /> Cancelar</button>
                  </div>
                  {saveMsg && <div style={{ marginTop: 8, padding: "8px 12px", borderRadius: 6, background: saveMsg.ok ? "#f0fdf4" : "#fef2f2", color: saveMsg.ok ? "#166534" : "#dc2626", fontSize: 13 }}>{saveMsg.msg}</div>}
                </div>
              ) : !config ? (
                <p style={{ color: "#9ca3af" }}>Nenhuma configuracao SMTP cadastrada. Clique em "Criar Configuracao" para configurar.</p>
              ) : (
                <div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 16 }}>
                    <div className="info-item"><label>Host</label><span>{config.host}</span></div>
                    <div className="info-item"><label>Porta</label><span>{config.port}</span></div>
                    <div className="info-item"><label>Seguranca</label><span>{segurancaLabel}</span></div>
                    <div className="info-item"><label>Usuario</label><span>{config.user || "—"}</span></div>
                    <div className="info-item"><label>De (email)</label><span>{config.from_email}</span></div>
                    <div className="info-item"><label>De (nome)</label><span>{config.from_name || "—"}</span></div>
                    <div className="info-item"><label>TLS</label><span>{config.tls_enabled ? "Sim" : "Nao"}</span></div>
                    <div className="info-item"><label>Ultima atualizacao</label><span>{formatData(config.updated_at)}</span></div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 16, padding: 16, background: config.smtp_live_mode ? "#fef2f2" : "#f0fdf4", borderRadius: 8, marginBottom: 16 }}>
                    <div style={{ flex: 1 }}><strong>Modo:</strong> {config.smtp_live_mode ? "PRODUCAO (emails reais)" : "DRY-RUN (apenas log)"}</div>
                    <button className={`btn ${config.smtp_live_mode ? "btn-secondary" : "btn-primary"}`} onClick={handleToggleLiveMode}>{config.smtp_live_mode ? "Desativar Producao" : "Ativar Producao"}</button>
                  </div>
                  <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
                    <FormField label="Email de teste">
                      <input type="email" className="form-input" value={testEmail} onChange={e => setTestEmail(e.target.value)} placeholder="seu@email.com" style={{ width: 260 }} />
                    </FormField>
                    <ActionButton icon={<Send size={14} />} label="Testar Conexao" onClick={handleTestarSMTP} disabled={!testEmail} />
                  </div>
                  {testResult && <div style={{ marginTop: 8, padding: "8px 12px", borderRadius: 6, background: testResult.ok ? "#f0fdf4" : "#fef2f2", color: testResult.ok ? "#166534" : "#dc2626", fontSize: 13 }}>{testResult.ok ? <><CheckCircle size={14} style={{ marginRight: 6 }} />Conectado</> : <><AlertCircle size={14} style={{ marginRight: 6 }} />{testResult.msg}</>}</div>}
                  {saveMsg && <div style={{ marginTop: 8, padding: "8px 12px", borderRadius: 6, background: saveMsg.ok ? "#f0fdf4" : "#fef2f2", color: saveMsg.ok ? "#166534" : "#dc2626", fontSize: 13 }}>{saveMsg.msg}</div>}
                </div>
              )}
            </Card>
          </>
        )}

        {activeTab === "templates" && (
          <>
            {saveTemplateMsg && <div style={{ padding: "8px 16px", background: "#f0fdf4", color: "#166534", borderRadius: 6, marginBottom: 12, fontSize: 13 }}><CheckCircle size={14} style={{ marginRight: 6 }} />{saveTemplateMsg}</div>}
            <Card title="Templates de Email" icon={<FileText size={18} />}>
              <DataTable data={templates} columns={templateColumns} idKey="id" loading={templatesLoading} emptyMessage="Nenhum template cadastrado" />
            </Card>
          </>
        )}

        {activeTab === "fila" && (
          <>
            <Card title="Resumo da Fila" icon={<Send size={18} />}>
              <div className="stats-row">
                {([
                  { icon: <Clock size={24} />, cls: "warning", value: filaStats.pending, label: "Pendentes" },
                  { icon: <CheckCircle size={24} />, cls: "success", value: filaStats.sent, label: "Enviados" },
                  { icon: <AlertCircle size={24} />, cls: "error", value: filaStats.failed, label: "Falhados" },
                  { icon: <Percent size={24} />, cls: filaStats.taxa > 90 ? "success" : filaStats.taxa > 70 ? "warning" : "error", value: `${filaStats.taxa}%`, label: "Taxa Sucesso" },
                ]).map((s, i) => (
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

            <Card title="Filtros" icon={<Eye size={18} />}>
              <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
                <FormField label="Status">
                  <SelectInput value={filtroFilaStatus} onChange={setFiltroFilaStatus} options={[
                    { value: "", label: "Todos" }, { value: "pending", label: "Pendentes" },
                    { value: "sent", label: "Enviados" }, { value: "failed", label: "Falhados" },
                  ]} />
                </FormField>
                <FormField label="Destinatario">
                  <input type="text" className="form-input" value={filtroFilaDest} onChange={e => setFiltroFilaDest(e.target.value)} placeholder="Buscar..." style={{ width: 180 }} />
                </FormField>
                <FormField label="Periodo">
                  <SelectInput value={filtroFilaPeriodo} onChange={setFiltroFilaPeriodo} options={[
                    { value: "", label: "Todos" }, { value: "1", label: "24h" },
                    { value: "7", label: "7 dias" }, { value: "30", label: "30 dias" },
                  ]} />
                </FormField>
              </div>
            </Card>

            <Card title="Fila de Email" icon={<Send size={18} />}
              actions={<ActionButton icon={<RefreshCw size={14} />} label="Atualizar" onClick={fetchFila} />}>
              <DataTable data={filteredFila} columns={filaColumns} idKey="id" loading={filaLoading} emptyMessage="Fila vazia" />
            </Card>
          </>
        )}
      </div>

      {/* Modal Confirmar Producao */}
      <Modal isOpen={showConfirmLive} onClose={() => setShowConfirmLive(false)} title="Confirmar Modo Producao"
        footer={<><button className="btn btn-secondary" onClick={() => setShowConfirmLive(false)}>Cancelar</button>
          <button className="btn btn-primary" onClick={confirmLiveMode}>Confirmar — Ativar Producao</button></>}>
        <div style={{ padding: 16 }}>
          <AlertCircle size={32} color="#f59e0b" style={{ marginBottom: 12 }} />
          <p><strong>Atencao:</strong> Ao ativar o modo producao, emails serao enviados de verdade via SMTP.</p>
        </div>
      </Modal>

      {/* Modal Editar Template (com preview) */}
      <Modal isOpen={!!editingTemplate} onClose={() => setEditingTemplate(null)} title={`Editar Template: ${editingTemplate?.slug || ""}`} size="large"
        footer={<><button className="btn btn-secondary" onClick={() => setEditingTemplate(null)}>Cancelar</button>
          <button className="btn btn-primary" onClick={handleSaveTemplate}>Salvar Nova Versao</button></>}>
        {editingTemplate && (
          <div>
            <FormField label="Assunto">
              <input type="text" className="form-input" value={editAssunto} onChange={e => setEditAssunto(e.target.value)} />
            </FormField>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 12 }}>
              <div>
                <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
                  <button className="btn btn-sm btn-secondary" onClick={() => insertTag("b")} title="Negrito"><Bold size={14} /></button>
                  <button className="btn btn-sm btn-secondary" onClick={() => insertTag("i")} title="Italico"><Italic size={14} /></button>
                  <button className="btn btn-sm btn-secondary" onClick={() => insertTag("a")} title="Link"><Link size={14} /></button>
                </div>
                <textarea className="form-input template-editor" rows={14} value={editCorpo} onChange={e => setEditCorpo(e.target.value)} style={{ fontFamily: "monospace", fontSize: 12 }} />
              </div>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#6b7280", marginBottom: 8 }}>Preview</div>
                <div style={{ border: "1px solid #e5e7eb", borderRadius: 6, padding: 12, minHeight: 280, background: "#fff", fontSize: 13, overflow: "auto" }}
                  dangerouslySetInnerHTML={{ __html: previewHtml }} />
              </div>
            </div>
            {editingTemplate.variaveis_json && (
              <div style={{ marginTop: 8, fontSize: 12, color: "#6b7280" }}>
                <strong>Variaveis:</strong> {(editingTemplate.variaveis_json as string[]).map(v => `{{${v}}}`).join(", ")}
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* Modal Detalhe Email */}
      <Modal isOpen={!!filaDetailItem} onClose={() => setFilaDetailItem(null)} title="Detalhes do Email" size="large"
        footer={filaDetailItem ? <>
          {(filaDetailItem.status === "failed" || filaDetailItem.status === "bounce") && (
            <button className="btn btn-primary" onClick={() => { handleReenviar(filaDetailItem.id); setFilaDetailItem(null); }}><RefreshCw size={14} /> Reenviar</button>
          )}
          {filaDetailItem.status === "pending" && (
            <button className="btn btn-secondary danger" onClick={() => handleCancelarEmail(filaDetailItem.id)}>Cancelar Envio</button>
          )}
          <button className="btn btn-secondary" onClick={() => setFilaDetailItem(null)}>Fechar</button>
        </> : undefined}>
        {filaDetailItem && (
          <div style={{ fontSize: 13 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
              <div><strong>Destinatario:</strong> {filaDetailItem.destinatario}</div>
              <div><strong>Assunto:</strong> {filaDetailItem.assunto}</div>
              <div><strong>Template:</strong> {filaDetailItem.template_slug || "—"}</div>
              <div><strong>Data:</strong> {formatData(filaDetailItem.created_at)}</div>
              <div><strong>Status:</strong> {getStatusBadge(filaDetailItem.status)}</div>
              <div><strong>Tentativas:</strong> {filaDetailItem.retry_count}/{filaDetailItem.max_retries}</div>
            </div>
            {filaDetailItem.erro_mensagem && (
              <div style={{ padding: 12, background: "#fef2f2", borderRadius: 6, marginBottom: 12, border: "1px solid #fecaca" }}>
                <strong>Mensagem de Erro:</strong>
                <pre style={{ fontSize: 11, whiteSpace: "pre-wrap", marginTop: 4 }}>{filaDetailItem.erro_mensagem}</pre>
              </div>
            )}
            {filaDetailItem.corpo_html && (
              <div>
                <strong>Corpo HTML:</strong>
                <div style={{ border: "1px solid #e5e7eb", borderRadius: 6, padding: 12, marginTop: 8, maxHeight: 300, overflow: "auto", background: "#fff" }}
                  dangerouslySetInnerHTML={{ __html: filaDetailItem.corpo_html }} />
              </div>
            )}
          </div>
        )}
      </Modal>
    </div>
  );
}
