import { useState, useEffect, useCallback, useMemo } from "react";
import type { PageProps } from "../types";
import { Shield, Search, AlertTriangle, Download, Eye, Filter, Copy, Users, Clock, BarChart3 } from "lucide-react";
import { Card, DataTable, ActionButton, Modal, FormField, SelectInput } from "../components/common";
import type { Column } from "../components/common";
import { crudList } from "../api/crud";

interface AuditoriaLog {
  id: string;
  user_email: string | null;
  acao: string;
  entidade: string;
  entidade_id: string | null;
  ip_address: string | null;
  user_agent: string | null;
  dados_antes: any;
  dados_depois: any;
  created_at: string | null;
}

const SENSITIVE_ENTITIES = ["smtp-config", "users", "empresas", "contratos", "propostas", "parametros-score"];

function getDiffFields(antes: any, depois: any): { field: string; before: string; after: string; type: "changed" | "added" | "removed" }[] {
  if (!antes && !depois) return [];
  const a = antes || {};
  const d = depois || {};
  const allKeys = new Set([...Object.keys(a), ...Object.keys(d)]);
  const diffs: { field: string; before: string; after: string; type: "changed" | "added" | "removed" }[] = [];
  allKeys.forEach(key => {
    const bv = JSON.stringify(a[key] ?? null);
    const av = JSON.stringify(d[key] ?? null);
    if (bv !== av) {
      const type = !(key in a) ? "added" : !(key in d) ? "removed" : "changed";
      diffs.push({ field: key, before: a[key] !== undefined ? String(a[key]) : "", after: d[key] !== undefined ? String(d[key]) : "", type });
    }
  });
  return diffs;
}

export function AuditoriaPage(_props: PageProps) {
  const [activeTab, setActiveTab] = useState<"consultar" | "sensiveis" | "exportar">("consultar");
  const [logs, setLogs] = useState<AuditoriaLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [detailLog, setDetailLog] = useState<AuditoriaLog | null>(null);
  const [copyMsg, setCopyMsg] = useState(false);

  // Filtros
  const [filtroEntidade, setFiltroEntidade] = useState("");
  const [filtroUsuario, setFiltroUsuario] = useState("");
  const [filtroPeriodo, setFiltroPeriodo] = useState("7");
  const [filtroAcao, setFiltroAcao] = useState("");

  // Exportar
  const [exportInicio, setExportInicio] = useState("");
  const [exportFim, setExportFim] = useState("");
  const [mascarPii, setMascarPii] = useState(true);
  const [exportando, setExportando] = useState(false);
  const [exportHash, setExportHash] = useState("");
  const [exportEntidades, setExportEntidades] = useState("");
  const [exportUsuarios, setExportUsuarios] = useState("");

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    try {
      const params: any = { limit: 500 };
      if (filtroEntidade) params.search = filtroEntidade;
      if (activeTab === "sensiveis") params.search = "sensitive";
      const res = await crudList("auditoria-log", params);
      let items = (res.items || []) as unknown as AuditoriaLog[];
      if (filtroPeriodo) {
        const diasMs = parseInt(filtroPeriodo) * 86400000;
        items = items.filter(l => l.created_at && new Date(l.created_at).getTime() >= Date.now() - diasMs);
      }
      if (filtroAcao) items = items.filter(l => l.acao.includes(filtroAcao));
      if (filtroUsuario) items = items.filter(l => l.user_email?.toLowerCase().includes(filtroUsuario.toLowerCase()));
      if (activeTab === "sensiveis") {
        items = items.filter(l => SENSITIVE_ENTITIES.includes(l.entidade));
      }
      setLogs(items);
    } catch (e) { console.error("Erro:", e); }
    setLoading(false);
  }, [filtroEntidade, filtroUsuario, filtroPeriodo, filtroAcao, activeTab]);

  useEffect(() => { fetchLogs(); }, [fetchLogs]);

  const formatData = (iso: string | null) => {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }); } catch { return iso; }
  };

  const getAcaoBadge = (acao: string) => {
    const map: Record<string, string> = { create: "status-badge-success", update: "status-badge-info", delete: "status-badge-error", login: "status-badge-neutral" };
    return <span className={`status-badge ${map[acao] || "status-badge-neutral"}`}>{acao}</span>;
  };

  const consultarColumns: Column<AuditoriaLog>[] = [
    { key: "created_at", header: "Data", render: l => formatData(l.created_at), sortable: true },
    { key: "user_email", header: "Usuario", render: l => l.user_email || "—", sortable: true },
    { key: "acao", header: "Acao", render: l => getAcaoBadge(l.acao) },
    { key: "entidade", header: "Entidade", sortable: true },
    { key: "entidade_id", header: "ID", render: l => l.entidade_id ? l.entidade_id.slice(0, 8) + "..." : "—" },
    { key: "ip_address", header: "IP", render: l => l.ip_address || "—" },
    { key: "detalhes", header: "", width: "40px", render: l => <button className="btn-icon" title="Ver detalhes" onClick={() => setDetailLog(l)}><Eye size={14} /></button> },
  ];

  const sensiveisColumns: Column<AuditoriaLog>[] = [
    { key: "created_at", header: "Data", render: l => formatData(l.created_at), sortable: true },
    { key: "user_email", header: "Usuario", render: l => l.user_email || "—", sortable: true },
    { key: "entidade", header: "Entidade", sortable: true },
    {
      key: "campo", header: "Campo Alterado",
      render: l => {
        const diffs = getDiffFields(l.dados_antes, l.dados_depois);
        return diffs.length > 0 ? diffs.map(d => d.field).join(", ") : "—";
      },
    },
    {
      key: "antes", header: "Antes",
      render: l => {
        const diffs = getDiffFields(l.dados_antes, l.dados_depois);
        const first = diffs[0];
        return first ? <span style={{ color: "#dc2626" }}>{first.before.slice(0, 50)}</span> : "—";
      },
    },
    {
      key: "depois", header: "Depois",
      render: l => {
        const diffs = getDiffFields(l.dados_antes, l.dados_depois);
        const first = diffs[0];
        return first ? <span style={{ color: "#16a34a" }}>{first.after.slice(0, 50)}</span> : "—";
      },
    },
    { key: "detalhes", header: "", width: "40px", render: l => <button className="btn-icon" onClick={() => setDetailLog(l)}><Eye size={14} /></button> },
  ];

  // Sensiveis stats
  const sensiveisStats = useMemo(() => {
    const sensiveis = logs;
    const ultimos7d = sensiveis.filter(l => l.created_at && new Date(l.created_at).getTime() >= Date.now() - 7 * 86400000);
    const usuarios = new Set(sensiveis.map(l => l.user_email).filter(Boolean));
    return {
      total: sensiveis.length,
      ultimos7d: ultimos7d.length,
      usuarios: usuarios.size,
      alertas: sensiveis.filter(l => l.acao === "update").length,
    };
  }, [logs]);

  const handleCopyJSON = () => {
    if (!detailLog) return;
    const json = JSON.stringify({ antes: detailLog.dados_antes, depois: detailLog.dados_depois }, null, 2);
    navigator.clipboard.writeText(json);
    setCopyMsg(true);
    setTimeout(() => setCopyMsg(false), 2000);
  };

  const handleExportar = async () => {
    if (!exportInicio || !exportFim) return;
    setExportando(true);
    setExportHash("");
    try {
      const res = await crudList("auditoria-log", { limit: 5000 });
      let items = (res.items || []) as unknown as AuditoriaLog[];
      const inicio = new Date(exportInicio).getTime();
      const fim = new Date(exportFim + "T23:59:59").getTime();
      items = items.filter(l => l.created_at && new Date(l.created_at).getTime() >= inicio && new Date(l.created_at).getTime() <= fim);
      if (exportEntidades) items = items.filter(l => exportEntidades.includes(l.entidade));
      if (exportUsuarios) items = items.filter(l => l.user_email && exportUsuarios.includes(l.user_email));

      let csv = "Data,Usuario,Acao,Entidade,ID Entidade,IP\n";
      items.forEach(l => {
        let email = l.user_email || "—";
        let ip = l.ip_address || "—";
        if (mascarPii) {
          if (email.includes("@")) email = `***@${email.split("@")[1]?.slice(0, 3)}***`;
          if (ip.includes(".")) { const o = ip.split("."); ip = `${o[0]}.${o[1]}.*.*`; }
        }
        csv += `${formatData(l.created_at)},${email},${l.acao},${l.entidade},${l.entidade_id || "—"},${ip}\n`;
      });

      // SHA-256 hash
      const encoder = new TextEncoder();
      const data = encoder.encode(csv);
      const hashBuffer = await crypto.subtle.digest("SHA-256", data);
      const hashArray = Array.from(new Uint8Array(hashBuffer));
      const hashHex = hashArray.map(b => b.toString(16).padStart(2, "0")).join("");
      setExportHash(hashHex);

      const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `auditoria_${exportInicio}_${exportFim}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { console.error("Erro:", e); }
    setExportando(false);
  };

  const handleExportPDF = () => window.print();

  const uniqueEntidades = useMemo(() => [...new Set(logs.map(l => l.entidade))].sort(), [logs]);
  const uniqueUsuarios = useMemo(() => [...new Set(logs.map(l => l.user_email).filter(Boolean))].sort(), [logs]);

  const tabs = [
    { key: "consultar" as const, label: "Consultar", icon: <Search size={14} /> },
    { key: "sensiveis" as const, label: "Alteracoes Sensiveis", icon: <AlertTriangle size={14} /> },
    { key: "exportar" as const, label: "Exportar Compliance", icon: <Download size={14} /> },
  ];

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-left">
          <Shield size={24} />
          <div>
            <h1>Auditoria</h1>
            <p>Rastreamento de alteracoes e compliance</p>
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

        {activeTab === "consultar" && (
          <>
            <Card title="Filtros" icon={<Filter size={18} />}>
              <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
                <FormField label="Entidade">
                  <input type="text" className="form-input" value={filtroEntidade} onChange={e => setFiltroEntidade(e.target.value)} placeholder="Ex: contratos, editais..." style={{ width: 160 }} />
                </FormField>
                <FormField label="Usuario">
                  <input type="text" className="form-input" value={filtroUsuario} onChange={e => setFiltroUsuario(e.target.value)} placeholder="Email do usuario" style={{ width: 180 }} />
                </FormField>
                <FormField label="Acao">
                  <SelectInput value={filtroAcao} onChange={setFiltroAcao} options={[
                    { value: "", label: "Todas" }, { value: "create", label: "Create" },
                    { value: "update", label: "Update" }, { value: "delete", label: "Delete" },
                    { value: "login", label: "Login" },
                  ]} />
                </FormField>
                <FormField label="Periodo">
                  <SelectInput value={filtroPeriodo} onChange={setFiltroPeriodo} options={[
                    { value: "1", label: "Ultimo dia" }, { value: "7", label: "7 dias" },
                    { value: "30", label: "30 dias" }, { value: "90", label: "90 dias" },
                    { value: "365", label: "12 meses" },
                  ]} />
                </FormField>
                <ActionButton icon={<Search size={14} />} label="Buscar" onClick={fetchLogs} />
              </div>
            </Card>
            <Card title={`Registros (${logs.length})`} icon={<Shield size={18} />}>
              <DataTable data={logs} columns={consultarColumns} idKey="id" loading={loading} emptyMessage="Nenhum registro encontrado" />
            </Card>
          </>
        )}

        {activeTab === "sensiveis" && (
          <>
            <div className="stats-row" style={{ display: "flex", gap: 12, marginBottom: 16 }}>
              {([
                { icon: <Shield size={24} />, cls: "error", value: sensiveisStats.total, label: "Total Sensiveis" },
                { icon: <Clock size={24} />, cls: "warning", value: sensiveisStats.ultimos7d, label: "Ultimos 7 dias" },
                { icon: <Users size={24} />, cls: "info", value: sensiveisStats.usuarios, label: "Usuarios Distintos" },
                { icon: <BarChart3 size={24} />, cls: "success", value: sensiveisStats.alertas, label: "Alteracoes (update)" },
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

            <Card title="Filtros" icon={<Filter size={18} />}>
              <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
                <FormField label="Entidade">
                  <input type="text" className="form-input" value={filtroEntidade} onChange={e => setFiltroEntidade(e.target.value)} placeholder="smtp-config, users..." style={{ width: 180 }} />
                </FormField>
                <FormField label="Periodo">
                  <SelectInput value={filtroPeriodo} onChange={setFiltroPeriodo} options={[
                    { value: "7", label: "7 dias" }, { value: "30", label: "30 dias" }, { value: "90", label: "90 dias" },
                  ]} />
                </FormField>
                <ActionButton icon={<Search size={14} />} label="Buscar" onClick={fetchLogs} />
              </div>
            </Card>

            <Card title={`Registros (${logs.length})`} icon={<AlertTriangle size={18} />}>
              <DataTable data={logs} columns={sensiveisColumns} idKey="id" loading={loading} emptyMessage="Nenhuma alteracao sensivel" />
            </Card>
          </>
        )}

        {activeTab === "exportar" && (
          <Card title="Exportar para Compliance" icon={<Download size={18} />}>
            <div style={{ maxWidth: 600 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                <FormField label="Data Inicio">
                  <input type="date" className="form-input" value={exportInicio} onChange={e => setExportInicio(e.target.value)} />
                </FormField>
                <FormField label="Data Fim">
                  <input type="date" className="form-input" value={exportFim} onChange={e => setExportFim(e.target.value)} />
                </FormField>
              </div>
              <FormField label="Entidades (filtrar)">
                <SelectInput value={exportEntidades} onChange={setExportEntidades}
                  options={[{ value: "", label: "Todas" }, ...uniqueEntidades.map(e => ({ value: e, label: e }))]} />
              </FormField>
              <FormField label="Usuarios (filtrar)">
                <SelectInput value={exportUsuarios} onChange={setExportUsuarios}
                  options={[{ value: "", label: "Todos" }, ...uniqueUsuarios.map(u => ({ value: u!, label: u! }))]} />
              </FormField>
              <FormField label="">
                <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer" }}>
                  <input type="checkbox" checked={mascarPii} onChange={e => setMascarPii(e.target.checked)} />
                  Mascarar PII (emails e IPs)
                </label>
              </FormField>
              <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
                <ActionButton icon={<Download size={14} />} label={exportando ? "Exportando..." : "Exportar CSV"} onClick={handleExportar} disabled={!exportInicio || !exportFim || exportando} />
                <ActionButton icon={<Download size={14} />} label="Exportar PDF" variant="secondary" onClick={handleExportPDF} />
              </div>
              {exportHash && (
                <div style={{ marginTop: 12, padding: "8px 12px", background: "#f0fdf4", borderRadius: 6, fontSize: 11, fontFamily: "monospace", wordBreak: "break-all" }}>
                  <strong>SHA-256:</strong> {exportHash}
                </div>
              )}
            </div>
          </Card>
        )}
      </div>

      {/* Modal Detalhe */}
      <Modal isOpen={!!detailLog} onClose={() => setDetailLog(null)} title="Detalhes da Alteracao"
        footer={<>
          <button className="btn btn-secondary" onClick={handleCopyJSON} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Copy size={14} /> {copyMsg ? "Copiado!" : "Copiar JSON"}
          </button>
          <button className="btn btn-secondary" onClick={() => setDetailLog(null)}>Fechar</button>
        </>}>
        {detailLog && (
          <div style={{ fontSize: 13 }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
              <div><strong>Data:</strong> {formatData(detailLog.created_at)}</div>
              <div><strong>Usuario:</strong> {detailLog.user_email || "—"}</div>
              <div><strong>Acao:</strong> {detailLog.acao}</div>
              <div><strong>Entidade:</strong> {detailLog.entidade}</div>
              <div><strong>ID:</strong> {detailLog.entidade_id || "—"}</div>
              <div><strong>IP:</strong> {detailLog.ip_address || "—"}</div>
            </div>
            {detailLog.user_agent && (
              <div style={{ marginBottom: 12, fontSize: 11, color: "#6b7280" }}>
                <strong>User-Agent:</strong> {detailLog.user_agent}
              </div>
            )}

            {/* Diff visual */}
            {(detailLog.dados_antes || detailLog.dados_depois) && (() => {
              const diffs = getDiffFields(detailLog.dados_antes, detailLog.dados_depois);
              const unchanged = Object.keys(detailLog.dados_antes || {}).filter(k => !diffs.find(d => d.field === k));
              return (
                <div>
                  <strong>Alteracoes:</strong>
                  <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 8, fontSize: 12 }}>
                    <thead>
                      <tr style={{ background: "#f3f4f6" }}>
                        <th style={{ padding: "6px 8px", textAlign: "left", borderBottom: "1px solid #e5e7eb" }}>Campo</th>
                        <th style={{ padding: "6px 8px", textAlign: "left", borderBottom: "1px solid #e5e7eb" }}>Antes</th>
                        <th style={{ padding: "6px 8px", textAlign: "left", borderBottom: "1px solid #e5e7eb" }}>Depois</th>
                      </tr>
                    </thead>
                    <tbody>
                      {diffs.map(d => (
                        <tr key={d.field}>
                          <td style={{ padding: "4px 8px", fontWeight: 600, borderBottom: "1px solid #f3f4f6" }}>{d.field}</td>
                          <td style={{ padding: "4px 8px", background: d.type === "added" ? "transparent" : "#fee2e2", borderBottom: "1px solid #f3f4f6", fontFamily: "monospace", fontSize: 11, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>
                            {d.before || "—"}
                          </td>
                          <td style={{ padding: "4px 8px", background: d.type === "removed" ? "transparent" : "#dcfce7", borderBottom: "1px solid #f3f4f6", fontFamily: "monospace", fontSize: 11, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis" }}>
                            {d.after || "—"}
                          </td>
                        </tr>
                      ))}
                      {unchanged.map(k => (
                        <tr key={k} style={{ color: "#9ca3af" }}>
                          <td style={{ padding: "4px 8px", borderBottom: "1px solid #f3f4f6" }}>{k}</td>
                          <td style={{ padding: "4px 8px", borderBottom: "1px solid #f3f4f6", fontFamily: "monospace", fontSize: 11 }}>{String((detailLog.dados_antes || {})[k] ?? "")}</td>
                          <td style={{ padding: "4px 8px", borderBottom: "1px solid #f3f4f6", fontFamily: "monospace", fontSize: 11 }}>{String((detailLog.dados_depois || {})[k] ?? "")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              );
            })()}
          </div>
        )}
      </Modal>
    </div>
  );
}
