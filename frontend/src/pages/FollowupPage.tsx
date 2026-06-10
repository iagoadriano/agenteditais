import { useState, useEffect, useCallback } from "react";
import type { PageProps } from "../types";
import { Trophy, XCircle, Ban, Clock, Loader2, Bell, CalendarDays, Download } from "lucide-react";
import { Card, DataTable, ActionButton, FormField, TextInput, TextArea, SelectInput, Modal, TabPanel } from "../components/common";
import type { Column } from "../components/common";
import {
  getAgendaPregoes, agendarAlertasAutomatico, baixarCalendarioICS,
  type EventoAgenda,
} from "../api/alertas";

// ─── Types ────────────────────────────────────────────────────────────────────

interface EditalPendente {
  id: string;
  numero: string;
  orgao: string;
  data_abertura: string | null;
  valor_referencia: number | null;
  status: string;
  created_at: string | null;
  updated_at: string | null;
}

interface EditalResultado {
  id: string;
  numero: string;
  orgao: string;
  status: string;
  valor_referencia: number | null;
  updated_at: string | null;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function FollowupPage(_props?: PageProps) {
  const [pendentes, setPendentes] = useState<EditalPendente[]>([]);
  const [resultados, setResultados] = useState<EditalResultado[]>([]);
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [selectedEdital, setSelectedEdital] = useState<EditalPendente | null>(null);

  // Form state
  const [tipo, setTipo] = useState<"vitoria" | "derrota" | "cancelado">("vitoria");
  const [valorFinal, setValorFinal] = useState("");
  const [vencedor, setVencedor] = useState("");
  const [motivo, setMotivo] = useState("");
  const [justificativa, setJustificativa] = useState("");
  const [observacoes, setObservacoes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const token = localStorage.getItem("editais_ia_access_token");
  const headers: Record<string, string> = { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" };

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [pendRes, resRes] = await Promise.all([
        fetch("/api/followup/pendentes", { headers }),
        fetch("/api/followup/resultados", { headers }),
      ]);
      if (pendRes.ok) setPendentes(await pendRes.json());
      if (resRes.ok) setResultados(await resRes.json());
    } catch (e) { console.error(e); }
    setLoading(false);
  }, []);

  // Alertas state
  const [alertaRegras, setAlertaRegras] = useState<Array<{id:string; tipo_entidade:string; dias_30:boolean; dias_15:boolean; dias_7:boolean; dias_1:boolean; canal_email:boolean; canal_push:boolean; ativo:boolean}>>([]);
  const [vencimentos, setVencimentos] = useState<Array<{tipo_entidade:string; nome:string; data_vencimento:string; dias_restantes:number; urgencia:string}>>([]);
  const [vencResumo, setVencResumo] = useState({ total: 0, vermelho: 0, laranja: 0, amarelo: 0, verde: 0 });

  const fetchAlertas = useCallback(async () => {
    try {
      const [regrasRes, consRes] = await Promise.all([
        fetch("/api/alertas-vencimento/regras", { headers }),
        fetch("/api/alertas-vencimento/consolidado", { headers }),
      ]);
      if (regrasRes.ok) setAlertaRegras(await regrasRes.json());
      if (consRes.ok) { const d = await consRes.json(); setVencimentos(d.vencimentos || []); setVencResumo(d.resumo || { total: 0, vermelho: 0, laranja: 0, amarelo: 0, verde: 0 }); }
    } catch (e) { console.error(e); }
  }, []);

  // Agenda de pregões (RF-ALE-001): contagem regressiva + alertas automáticos
  const [agenda, setAgenda] = useState<EventoAgenda[]>([]);
  const [agendaLoading, setAgendaLoading] = useState(false);
  const [agendaMsg, setAgendaMsg] = useState<string | null>(null);

  const fetchAgenda = useCallback(async () => {
    setAgendaLoading(true);
    try {
      const data = await getAgendaPregoes(30);
      setAgenda(data.eventos);
    } catch (e) { console.error(e); }
    setAgendaLoading(false);
  }, []);

  const handleAgendarAutomatico = async () => {
    setAgendaMsg(null);
    try {
      const r = await agendarAlertasAutomatico(30);
      setAgendaMsg(r.alertas_criados > 0
        ? `${r.alertas_criados} alerta(s) criado(s) para ${r.eventos_cobertos_agora} prazo(s)`
        : "Todos os prazos do período já possuem alertas agendados");
      fetchAgenda();
    } catch (e) {
      setAgendaMsg(e instanceof Error ? e.message : "Erro ao agendar alertas");
    }
  };

  useEffect(() => { fetchData(); fetchAlertas(); fetchAgenda(); }, [fetchData, fetchAlertas, fetchAgenda]);

  const handleRegistrar = async () => {
    if (!selectedEdital) return;
    setSubmitting(true);
    try {
      const res = await fetch("/api/followup/registrar-resultado", {
        method: "POST", headers,
        body: JSON.stringify({
          edital_id: selectedEdital.id,
          tipo,
          valor_final: valorFinal ? parseFloat(valorFinal) : null,
          vencedor,
          motivo_derrota: motivo,
          observacoes: tipo === "cancelado" ? justificativa : observacoes,
        }),
      });
      if (res.ok) {
        setShowModal(false);
        resetForm();
        fetchData();
      }
    } catch (e) { console.error(e); }
    setSubmitting(false);
  };

  const resetForm = () => {
    setTipo("vitoria"); setValorFinal(""); setVencedor(""); setMotivo(""); setJustificativa(""); setObservacoes("");
    setSelectedEdital(null);
  };

  const openModal = (edital: EditalPendente) => {
    setSelectedEdital(edital);
    setValorFinal(edital.valor_referencia ? String(edital.valor_referencia) : "");
    setShowModal(true);
  };

  // Stats
  const vitorias = resultados.filter(r => r.status === "ganho").length;
  const derrotas = resultados.filter(r => r.status === "perdido").length;
  const taxa = vitorias + derrotas > 0 ? Math.round((vitorias / (vitorias + derrotas)) * 100) : 0;

  const fmt = (v: number | null) => v != null ? `R$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}` : "—";

  const pendCols: Column<EditalPendente>[] = [
    { key: "numero", header: "Edital" },
    { key: "orgao", header: "Órgão" },
    { key: "created_at", header: "Data Submissão", render: (r) => r.created_at ? new Date(r.created_at).toLocaleDateString("pt-BR") : "—" },
    { key: "valor_referencia", header: "Valor Proposta", render: (r) => fmt(r.valor_referencia) },
    { key: "id", header: "Ação", render: (r) => <ActionButton label="Registrar" onClick={() => openModal(r)} size="sm" /> },
  ];

  const resCols: Column<EditalResultado>[] = [
    { key: "numero", header: "Edital" },
    { key: "orgao", header: "Órgão" },
    { key: "status", header: "Resultado", render: (r) => {
      const colors: Record<string, string> = { ganho: "#16a34a", perdido: "#dc2626", cancelado: "#6b7280" };
      const labels: Record<string, string> = { ganho: "Vitória", perdido: "Derrota", cancelado: "Cancelado" };
      return <span style={{ background: colors[r.status] || "#6b7280", color: "#fff", padding: "2px 10px", borderRadius: 12, fontSize: 12 }}>{labels[r.status] || r.status}</span>;
    }},
    { key: "valor_referencia", header: "Valor Final", render: (r) => fmt(r.valor_referencia) },
    { key: "updated_at", header: "Data", render: (r) => r.updated_at ? new Date(r.updated_at).toLocaleDateString("pt-BR") : "—" },
  ];

  const tabResultados = (
    <div>
      {/* Stats Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
        {[
          { label: "Pendentes", value: pendentes.length, color: "#3b82f6", icon: <Clock size={20} /> },
          { label: "Vitórias", value: vitorias, color: "#16a34a", icon: <Trophy size={20} /> },
          { label: "Derrotas", value: derrotas, color: "#dc2626", icon: <XCircle size={20} /> },
          { label: "Taxa de Sucesso", value: `${taxa}%`, color: "#eab308", icon: <Ban size={20} /> },
        ].map((s, i) => (
          <Card key={i}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ background: s.color + "20", color: s.color, borderRadius: 8, padding: 8 }}>{s.icon}</div>
              <div>
                <div style={{ fontSize: 12, color: "#6b7280" }}>{s.label}</div>
                <div style={{ fontSize: 24, fontWeight: 700 }}>{s.value}</div>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <Card>
        <h3 style={{ marginBottom: 12 }}>Editais Pendentes de Resultado</h3>
        {loading ? <Loader2 className="animate-spin" /> : <DataTable columns={pendCols} data={pendentes} />}
      </Card>

      <div style={{ marginTop: 20 }}>
        <Card>
          <h3 style={{ marginBottom: 12 }}>Resultados Registrados</h3>
          <DataTable columns={resCols} data={resultados} />
        </Card>
      </div>
    </div>
  );

  const tabAlertas = (
    <div>
      {/* Resumo de vencimentos */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12, marginBottom: 20 }}>
        {[
          { label: "Total", value: vencResumo.total, color: "#3b82f6" },
          { label: "Crítico (<7d)", value: vencResumo.vermelho, color: "#dc2626" },
          { label: "Urgente (7-15d)", value: vencResumo.laranja, color: "#f97316" },
          { label: "Atenção (15-30d)", value: vencResumo.amarelo, color: "#eab308" },
          { label: "Normal (>30d)", value: vencResumo.verde, color: "#16a34a" },
        ].map((s, i) => (
          <Card key={i}>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: 11, color: "#9ca3af" }}>{s.label}</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: s.color }}>{s.value}</div>
            </div>
          </Card>
        ))}
      </div>

      {/* Próximos vencimentos */}
      <Card>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h3><Bell size={18} style={{ display: "inline", marginRight: 8 }} />Próximos Vencimentos</h3>
          <ActionButton label="Atualizar" onClick={fetchAlertas} size="sm" variant="secondary" />
        </div>
        {vencimentos.length === 0 ? (
          <div style={{ textAlign: "center", padding: 20, color: "#6b7280" }}>Nenhum vencimento nos próximos 90 dias</div>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead><tr style={{ borderBottom: "2px solid #374151" }}>
              <th style={{ padding: 8, textAlign: "left" }}>Tipo</th>
              <th style={{ padding: 8, textAlign: "left" }}>Nome</th>
              <th style={{ padding: 8, textAlign: "center" }}>Data</th>
              <th style={{ padding: 8, textAlign: "center" }}>Dias</th>
              <th style={{ padding: 8, textAlign: "center" }}>Urgência</th>
            </tr></thead>
            <tbody>{vencimentos.map((v, i) => {
              const urgColors: Record<string,{bg:string;fg:string}> = { vermelho:{bg:"#fee2e2",fg:"#991b1b"}, laranja:{bg:"#ffedd5",fg:"#9a3412"}, amarelo:{bg:"#fef3c7",fg:"#92400e"}, verde:{bg:"#dcfce7",fg:"#166534"} };
              const c = urgColors[v.urgencia] || urgColors.verde;
              return (
                <tr key={i} style={{ borderBottom: "1px solid #1f2937" }}>
                  <td style={{ padding: 8 }}><span style={{ background: v.tipo_entidade === "contrato" ? "#3b82f620" : v.tipo_entidade === "arp" ? "#8b5cf620" : "#f59e0b20", color: v.tipo_entidade === "contrato" ? "#3b82f6" : v.tipo_entidade === "arp" ? "#8b5cf6" : "#f59e0b", padding: "2px 8px", borderRadius: 8, fontSize: 11 }}>{v.tipo_entidade}</span></td>
                  <td style={{ padding: 8 }}>{v.nome}</td>
                  <td style={{ padding: 8, textAlign: "center" }}>{new Date(v.data_vencimento).toLocaleDateString("pt-BR")}</td>
                  <td style={{ padding: 8, textAlign: "center", fontWeight: 700 }}>{v.dias_restantes}d</td>
                  <td style={{ padding: 8, textAlign: "center" }}><span style={{ background: c.bg, color: c.fg, padding: "2px 10px", borderRadius: 12, fontSize: 12 }}>{v.urgencia}</span></td>
                </tr>
              );
            })}</tbody>
          </table>
        )}
      </Card>

      {/* Regras configuradas */}
      <div style={{ marginTop: 16 }}>
        <Card>
          <h3 style={{ marginBottom: 12 }}>Regras de Alerta Configuradas</h3>
          {alertaRegras.length === 0 ? (
            <div style={{ textAlign: "center", padding: 20, color: "#6b7280" }}>Nenhuma regra configurada. Use o dashboard Contratado x Realizado para configurar.</div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead><tr style={{ borderBottom: "2px solid #374151" }}>
                <th style={{ padding: 8, textAlign: "left" }}>Tipo</th>
                <th style={{ padding: 8, textAlign: "center" }}>30d</th>
                <th style={{ padding: 8, textAlign: "center" }}>15d</th>
                <th style={{ padding: 8, textAlign: "center" }}>7d</th>
                <th style={{ padding: 8, textAlign: "center" }}>1d</th>
                <th style={{ padding: 8, textAlign: "center" }}>Email</th>
                <th style={{ padding: 8, textAlign: "center" }}>Push</th>
                <th style={{ padding: 8, textAlign: "center" }}>Ativo</th>
              </tr></thead>
              <tbody>{alertaRegras.map((r, i) => (
                <tr key={i} style={{ borderBottom: "1px solid #1f2937" }}>
                  <td style={{ padding: 8 }}>{r.tipo_entidade}</td>
                  <td style={{ padding: 8, textAlign: "center" }}>{r.dias_30 ? "✅" : "—"}</td>
                  <td style={{ padding: 8, textAlign: "center" }}>{r.dias_15 ? "✅" : "—"}</td>
                  <td style={{ padding: 8, textAlign: "center" }}>{r.dias_7 ? "✅" : "—"}</td>
                  <td style={{ padding: 8, textAlign: "center" }}>{r.dias_1 ? "✅" : "—"}</td>
                  <td style={{ padding: 8, textAlign: "center" }}>{r.canal_email ? "✅" : "—"}</td>
                  <td style={{ padding: 8, textAlign: "center" }}>{r.canal_push ? "✅" : "—"}</td>
                  <td style={{ padding: 8, textAlign: "center" }}>{r.ativo ? "✅" : "❌"}</td>
                </tr>
              ))}</tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );

  // RF-ALE-001/002 — aba de agenda com contagem regressiva + exportação ICS
  const URGENCIA_CORES: Record<string, string> = {
    critico: "#dc2626", atencao: "#eab308", confortavel: "#16a34a", encerrado: "#6b7280",
  };
  const URGENCIA_LABELS: Record<string, string> = {
    critico: "Crítico (<24h)", atencao: "Atenção (<72h)", confortavel: "Confortável",
  };
  const tabAgenda = (
    <div>
      <div style={{ display: "flex", gap: 12, marginBottom: 16, alignItems: "center", flexWrap: "wrap" }}>
        <ActionButton label="Agendar Alertas Automáticos" onClick={handleAgendarAutomatico} />
        <ActionButton
          label="Exportar Calendário (.ics)"
          variant="secondary"
          onClick={() => baixarCalendarioICS(30).catch((e) => setAgendaMsg(e.message))}
        />
        {agendaMsg && <span style={{ fontSize: 13, color: "#3b82f6" }}>{agendaMsg}</span>}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 20 }}>
        {(["critico", "atencao", "confortavel"] as const).map((u) => (
          <Card key={u}>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: 11, color: "#9ca3af" }}>{URGENCIA_LABELS[u]}</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: URGENCIA_CORES[u] }}>
                {agenda.filter((ev) => ev.contagem.urgencia === u).length}
              </div>
            </div>
          </Card>
        ))}
      </div>

      <Card>
        <h3 style={{ marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
          <CalendarDays size={18} /> Próximos Prazos (30 dias)
        </h3>
        {agendaLoading ? (
          <Loader2 className="animate-spin" />
        ) : agenda.length === 0 ? (
          <div style={{ color: "#6b7280", fontSize: 14 }}>
            Nenhum prazo nos próximos 30 dias. Salve editais com data de abertura para vê-los aqui.
          </div>
        ) : (
          agenda.map((ev) => (
            <div
              key={`${ev.edital_id}-${ev.tipo}`}
              style={{
                display: "flex", alignItems: "center", gap: 12, padding: "10px 12px",
                borderLeft: `4px solid ${URGENCIA_CORES[ev.contagem.urgencia]}`,
                background: "#f9fafb", borderRadius: 6, marginBottom: 8,
              }}
            >
              <div style={{
                minWidth: 86, textAlign: "center", fontWeight: 700, fontSize: 15,
                color: URGENCIA_CORES[ev.contagem.urgencia],
              }}>
                {ev.contagem.texto}
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 14 }}>
                  {ev.label} — {ev.edital_numero}
                </div>
                <div style={{ fontSize: 12, color: "#6b7280" }}>
                  {ev.orgao}{ev.uf ? ` (${ev.uf})` : ""} · {new Date(ev.data_evento).toLocaleString("pt-BR")}
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: ev.alertas_agendados > 0 ? "#16a34a" : "#9ca3af" }}>
                <Bell size={14} />
                {ev.alertas_agendados > 0 ? `${ev.alertas_agendados} alerta(s)` : "sem alertas"}
              </div>
            </div>
          ))
        )}
      </Card>
      <div style={{ marginTop: 8, fontSize: 12, color: "#9ca3af", display: "flex", alignItems: "center", gap: 6 }}>
        <Download size={12} /> O arquivo .ics pode ser importado no Google Calendar, Outlook ou Apple Calendar.
      </div>
    </div>
  );

  return (
    <div style={{ padding: 24 }}>
      <h2 style={{ marginBottom: 20, fontSize: 22, fontWeight: 700 }}>Follow-up de Resultados</h2>
      <TabPanel tabs={[
        { id: "resultados", label: "Resultados" },
        { id: "agenda", label: "Agenda de Pregões" },
        { id: "alertas", label: "Alertas" },
      ]}>
        {(activeTab) => activeTab === "resultados" ? tabResultados : activeTab === "agenda" ? tabAgenda : tabAlertas}
      </TabPanel>

      {showModal && selectedEdital && (
        <Modal title={`Registrar Resultado — ${selectedEdital.numero}`} onClose={() => { setShowModal(false); resetForm(); }}>
          <div style={{ display: "flex", gap: 16, marginBottom: 16 }}>
            {(["vitoria", "derrota", "cancelado"] as const).map(t => (
              <label key={t} style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
                <input type="radio" checked={tipo === t} onChange={() => setTipo(t)} />
                <span style={{ fontWeight: tipo === t ? 700 : 400 }}>{t === "vitoria" ? "Vitória" : t === "derrota" ? "Derrota" : "Cancelado"}</span>
              </label>
            ))}
          </div>

          {tipo !== "cancelado" && (
            <FormField label="Valor Final (R$)">
              <TextInput value={valorFinal} onChange={setValorFinal} placeholder="0,00" />
            </FormField>
          )}

          {tipo === "derrota" && (
            <>
              <FormField label="Empresa Vencedora">
                <TextInput value={vencedor} onChange={setVencedor} placeholder="Nome da empresa" />
              </FormField>
              <FormField label="Motivo da Derrota">
                <SelectInput value={motivo} onChange={setMotivo} options={[
                  { value: "", label: "Selecione..." },
                  { value: "Preço", label: "Preço" }, { value: "Técnico", label: "Técnico" },
                  { value: "Documental", label: "Documental" }, { value: "Recurso", label: "Recurso" },
                  { value: "ME-EPP", label: "ME/EPP" }, { value: "Outro", label: "Outro" },
                ]} />
              </FormField>
            </>
          )}

          {tipo === "cancelado" && (
            <FormField label="Justificativa do Cancelamento">
              <TextArea value={justificativa} onChange={setJustificativa} placeholder="Motivo do cancelamento..." />
            </FormField>
          )}

          <FormField label="Observações">
            <TextArea value={observacoes} onChange={setObservacoes} placeholder="Observações adicionais..." />
          </FormField>

          <div style={{ display: "flex", justifyContent: "flex-end", gap: 12, marginTop: 16 }}>
            <ActionButton label="Cancelar" onClick={() => { setShowModal(false); resetForm(); }} variant="secondary" />
            <ActionButton label={submitting ? "Salvando..." : "Registrar"} onClick={handleRegistrar} disabled={submitting} />
          </div>
        </Modal>
      )}
    </div>
  );
}
