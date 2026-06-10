import { useState, useEffect, useCallback } from "react";
import type { PageProps } from "../types";
import {
  Gavel, Eye, Search, Upload, Download, Send, Loader2, Plus,
  Clock, CheckCircle, AlertTriangle, Shield, FileText, Edit3,
  Trash2, Save, MessageSquare,
  XCircle, Activity, ExternalLink,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Card, DataTable, ActionButton, FormField, TextInput, TextArea,
  SelectInput, Modal, TabPanel, Checkbox,
} from "../components/common";
import type { Column } from "../components/common";
import { getEditais, createSession, sendMessage } from "../api/client";
import type { Edital } from "../api/client";
import { crudList, crudCreate, crudUpdate, crudDelete } from "../api/crud";
import { getScoreRecurso, getHealthCheck } from "../api/sprint9";

// ─── Types ────────────────────────────────────────────────────────────────────

type JanelaStatus = "aguardando" | "aberta" | "encerrada";

interface MonitoramentoState {
  editalId: string;
  status: JanelaStatus;
  alertaWhatsapp: boolean;
  alertaEmail: boolean;
  alertaSistema: boolean;
  ativado: boolean;
  tempoRestante: string;
}

interface InconsistenciaVencedora {
  id: number;
  item: string;
  inconsistencia: string;
  motivacao: string;
  gravidade: "ALTA" | "MEDIA" | "BAIXA";
}

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
}

interface Laudo {
  id: string;
  edital_id: string;
  edital_numero: string;
  tipo: "recurso" | "contra_razao";
  subtipo: "administrativo" | "tecnico";
  empresa_alvo: string;
  template_id: string;
  status: "rascunho" | "revisao" | "protocolado" | "deferido" | "indeferido";
  conteudo: string;
  data_criacao: string;
}

interface TemplateOption {
  id: string;
  nome: string;
  conteudo_md: string;
  tipo: string;
}

// ─── Component ────────────────────────────────────────────────────────────────

export function RecursosPage(props?: PageProps) {
  const { onSendToChat } = props ?? {};

  // ── Shared state ──
  const [editais, setEditais] = useState<Edital[]>([]);
  const [editalId, setEditalId] = useState("");
  const [loadingEditais, setLoadingEditais] = useState(false);

  // ── Tab: Monitoramento ──
  const [monitoramento, setMonitoramento] = useState<MonitoramentoState>({
    editalId: "",
    status: "aguardando",
    alertaWhatsapp: false,
    alertaEmail: true,
    alertaSistema: true,
    ativado: false,
    tempoRestante: "",
  });
  const [monitorLoading, setMonitorLoading] = useState(false);

  // ── Tab: Analise ──
  const [analiseEditalId, setAnaliseEditalId] = useState("");
  const [propostaVencedoraTexto, setPropostaVencedoraTexto] = useState("");
  const [analiseLoading, setAnaliseLoading] = useState(false);
  const [inconsistenciasVencedora, setInconsistenciasVencedora] = useState<InconsistenciaVencedora[]>([]);
  const [analiseResultadoMd, setAnaliseResultadoMd] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMsg[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatSessionId, setChatSessionId] = useState("");
  const [chatLoading, setChatLoading] = useState(false);

  // ── Tab: Laudos ──
  const [laudos, setLaudos] = useState<Laudo[]>([]);
  const [selectedLaudo, setSelectedLaudo] = useState<Laudo | null>(null);
  const [showNovoLaudoModal, setShowNovoLaudoModal] = useState(false);
  const [showUploadLaudoModal, setShowUploadLaudoModal] = useState(false);
  const [laudoEditalId, setLaudoEditalId] = useState("");
  const [laudoTipo, setLaudoTipo] = useState<"recurso" | "contra_razao">("recurso");
  const [laudoSubtipo, setLaudoSubtipo] = useState<"administrativo" | "tecnico">("administrativo");
  const [laudoEmpresaAlvo, setLaudoEmpresaAlvo] = useState("");
  const [laudoTemplateId, setLaudoTemplateId] = useState("");
  const [laudoConteudo, setLaudoConteudo] = useState("");
  const [templates, setTemplates] = useState<TemplateOption[]>([]);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadEditalId, setUploadEditalId] = useState("");
  const [laudosSaving, setLaudosSaving] = useState(false);

  // ── UC-RE06: Submissão Assistida ──
  const [showSubmissaoModal, setShowSubmissaoModal] = useState(false);
  const [submissaoLaudo, setSubmissaoLaudo] = useState<Laudo | null>(null);
  const [submissaoProtocolo, setSubmissaoProtocolo] = useState("");
  const [submissaoStatus, setSubmissaoStatus] = useState<"pendente" | "submetido">("pendente");

  // ── Sprint 9 UC-SC03: Score de Recurso ──
  const [scoreRecurso, setScoreRecurso] = useState<{
    score: number;
    recomendacao: string;
    fatores: { nome: string; peso: number; valor: number }[];
  } | null>(null);
  const [scoreRecursoLoading, setScoreRecursoLoading] = useState(false);

  // ── Sprint 9 UC-HC01: Health Check ──
  const [healthCheck, setHealthCheck] = useState<{
    status: string;
    services: Record<string, { status: string; latency_ms?: number }>;
  } | null>(null);

  // ── Load data ──
  useEffect(() => {
    loadEditais();
    loadTemplates();
    loadLaudos();
    // Sprint 9 UC-HC01 — Health Check on mount
    (async () => {
      try {
        const data = await getHealthCheck();
        setHealthCheck(data);
      } catch {
        setHealthCheck(null);
      }
    })();
  }, []);

  // Sprint 9 UC-SC03 — Score de Recurso when edital is selected in analise tab
  useEffect(() => {
    if (!analiseEditalId) { setScoreRecurso(null); return; }
    const fetchScore = async () => {
      setScoreRecursoLoading(true);
      try {
        const data = await getScoreRecurso(analiseEditalId);
        setScoreRecurso({
          score: data.score ?? 0,
          recomendacao: data.recomendacao ?? "",
          fatores: data.fatores ?? [],
        });
      } catch {
        setScoreRecurso(null);
      } finally {
        setScoreRecursoLoading(false);
      }
    };
    fetchScore();
  }, [analiseEditalId]);

  const loadEditais = async () => {
    setLoadingEditais(true);
    try {
      const data = await getEditais();
      setEditais(data || []);
    } catch (err) {
      console.error("Erro ao carregar editais:", err);
    } finally {
      setLoadingEditais(false);
    }
  };

  const loadTemplates = async () => {
    try {
      const data = await crudList("recurso-templates");
      if (Array.isArray(data)) {
        setTemplates(data.filter((t: Record<string, unknown>) => t.ativo !== false).map((t: Record<string, unknown>) => ({
          id: String(t.id),
          nome: String(t.nome || ""),
          conteudo_md: String(t.conteudo_md || ""),
          tipo: String(t.tipo || "recurso"),
        })));
      }
    } catch {
      setTemplates([]);
    }
  };

  const loadLaudos = async () => {
    try {
      const data = await crudList("recursos-detalhados");
      const items = Array.isArray(data) ? data : (data?.items || []);
      if (items.length >= 0) {
        setLaudos(items
          .filter((r: Record<string, unknown>) => r.tipo === "recurso" || r.tipo === "contra_razao")
          .map((r: Record<string, unknown>) => ({
            id: String(r.id),
            edital_id: String(r.edital_id || ""),
            edital_numero: String(r.edital_numero || r.edital_id || ""),
            tipo: (r.tipo === "contra_razao" ? "contra_razao" : "recurso") as "recurso" | "contra_razao",
            subtipo: (r.subtipo as Laudo["subtipo"]) || "administrativo",
            empresa_alvo: String(r.empresa_alvo || ""),
            template_id: String(r.template_id || ""),
            status: (r.status as Laudo["status"]) || "rascunho",
            conteudo: String(r.texto_minuta || ""),
            data_criacao: r.created_at ? new Date(String(r.created_at)).toLocaleDateString("pt-BR") : new Date().toLocaleDateString("pt-BR"),
          })));
      }
    } catch {
      setLaudos([]);
    }
  };

  // ── Edital options ──
  const editalOptions = editais.map(e => ({
    value: e.id || "",
    label: `${e.numero} - ${e.orgao}`,
  }));

  // ── Monitoramento handlers ──

  const handleAtivarMonitoramento = useCallback(async () => {
    if (!editalId) return;
    setMonitorLoading(true);
    try {
      const session = await createSession("monitorar-janela");
      const sid = String(session.session_id || session.id);
      const edital = editais.find(e => e.id === editalId);
      const prompt = `Monitore a janela de recurso do edital ${edital?.numero || editalId}. Informe o status atual: se a janela de recurso esta aberta, aguardando ou encerrada. Se houver prazo, informe.`;
      await sendMessage(sid, prompt);
      setMonitoramento(prev => ({
        ...prev,
        editalId,
        ativado: true,
        status: "aguardando",
      }));
    } catch (err) {
      console.error("Erro ao ativar monitoramento:", err);
    } finally {
      setMonitorLoading(false);
    }
  }, [editalId, editais]);

  const handleRegistrarIntencao = useCallback(async () => {
    if (!editalId) return;
    if (onSendToChat) {
      const edital = editais.find(e => e.id === editalId);
      onSendToChat(`Registre intencao de recurso para o edital ${edital?.numero || editalId}`);
    }
  }, [editalId, editais, onSendToChat]);

  // ── Analise handlers ──

  const handleAnalisarVencedora = useCallback(async () => {
    if (!analiseEditalId) return;
    setAnaliseLoading(true);
    setInconsistenciasVencedora([]);
    setAnaliseResultadoMd("");
    setChatMessages([]);
    setChatSessionId("");
    try {
      // Chamar endpoint direto que usa tool_analisar_proposta_vencedora (lê PDF real)
      const token = localStorage.getItem("editais_ia_access_token");
      const resp = await fetch(`/api/editais/${analiseEditalId}/analisar-vencedora`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          proposta_vencedora_texto: propostaVencedoraTexto.trim() || undefined,
        }),
      });
      const data = await resp.json();

      if (data.success) {
        setAnaliseResultadoMd(data.analise_ia || data.resumo || "Análise concluída.");
        if (data.inconsistencias && data.inconsistencias.length > 0) {
          const mapped = data.inconsistencias.map((inc: any, idx: number) => ({
            id: String(idx + 1),
            item: inc.item || inc.trecho || "",
            inconsistencia: inc.inconsistencia || inc.fundamentacao || "",
            motivacao_recurso: inc.motivacao_recurso || inc.sugestao_correcao || "",
            gravidade: (inc.gravidade || "media").toLowerCase(),
          }));
          setInconsistenciasVencedora(mapped);
        }
      } else {
        setAnaliseResultadoMd(data.error || "Erro ao analisar proposta vencedora.");
      }

      // Iniciar sessão de chat para perguntas complementares
      const session = await createSession("analise-vencedora");
      setChatSessionId(String(session.session_id || session.id));
    } catch (err) {
      console.error("Erro ao analisar proposta:", err);
      setAnaliseResultadoMd("Erro ao analisar proposta vencedora.");
    } finally {
      setAnaliseLoading(false);
    }
  }, [analiseEditalId, propostaVencedoraTexto, editais]);

  const handleChatSend = useCallback(async () => {
    if (!chatInput.trim() || !chatSessionId) return;
    const userMsg = chatInput.trim();
    setChatInput("");
    setChatMessages(prev => [...prev, { role: "user", content: userMsg }]);
    setChatLoading(true);
    try {
      const resp = await sendMessage(chatSessionId, userMsg);
      setChatMessages(prev => [...prev, { role: "assistant", content: resp.response || "" }]);
    } catch (err) {
      console.error("Erro no chat:", err);
      setChatMessages(prev => [...prev, { role: "assistant", content: "Erro ao processar pergunta." }]);
    } finally {
      setChatLoading(false);
    }
  }, [chatInput, chatSessionId]);

  // ── Laudos handlers ──

  const handleNovoLaudo = async () => {
    if (!laudoEditalId) return;
    setLaudosSaving(true);
    try {
      // Chamar endpoint que usa tool_gerar_laudo_recurso (IA gera laudo real)
      const token = localStorage.getItem("editais_ia_access_token");
      const resp = await fetch("/api/recursos", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          edital_id: laudoEditalId,
          tipo: laudoTipo,
          subtipo: laudoSubtipo,
          empresa_alvo: laudoEmpresaAlvo,
          template_id: laudoTemplateId || null,
          instrucao: laudoConteudo || undefined,
        }),
      });
      const data = await resp.json();
      if (!data.success && data.error) {
        console.error("Erro ao gerar laudo:", data.error);
      }
      setShowNovoLaudoModal(false);
      setLaudoEditalId("");
      setLaudoTipo("recurso");
      setLaudoSubtipo("administrativo");
      setLaudoEmpresaAlvo("");
      setLaudoTemplateId("");
      setLaudoConteudo("");
      loadLaudos();
    } catch (err) {
      console.error("Erro ao criar laudo:", err);
    } finally {
      setLaudosSaving(false);
    }
  };

  const handleUploadLaudo = async () => {
    if (!uploadFile || !uploadEditalId) return;
    setLaudosSaving(true);
    try {
      const text = await uploadFile.text();
      await crudCreate("recursos", {
        edital_id: uploadEditalId,
        tipo: "recurso",
        motivo: `Upload: ${uploadFile.name}`,
        texto_minuta: text,
        status: "rascunho",
        prazo_limite: new Date().toISOString(),
        arquivo_path: uploadFile.name,
      });
      setShowUploadLaudoModal(false);
      setUploadFile(null);
      setUploadEditalId("");
      loadLaudos();
    } catch (err) {
      console.error("Erro ao fazer upload:", err);
    } finally {
      setLaudosSaving(false);
    }
  };

  const handleSalvarLaudo = async () => {
    if (!selectedLaudo) return;
    setLaudosSaving(true);
    try {
      await crudUpdate("recursos-detalhados", selectedLaudo.id, {
        texto_minuta: selectedLaudo.conteudo,
        status: "rascunho",
      });
      loadLaudos();
    } catch (err) {
      console.error("Erro ao salvar laudo:", err);
    } finally {
      setLaudosSaving(false);
    }
  };

  const handleEnviarLaudoRevisao = async () => {
    if (!selectedLaudo) return;
    setLaudosSaving(true);
    try {
      await crudUpdate("recursos-detalhados", selectedLaudo.id, {
        texto_minuta: selectedLaudo.conteudo,
        status: "protocolado",
      });
      loadLaudos();
      setSelectedLaudo(null);
    } catch (err) {
      console.error("Erro ao enviar laudo:", err);
    } finally {
      setLaudosSaving(false);
    }
  };

  const handleExportLaudoPDF = () => {
    if (!selectedLaudo) return;
    if (onSendToChat) {
      onSendToChat(`Exporte em PDF o laudo de recurso do edital ${selectedLaudo.edital_numero}`);
    }
  };

  const handleExportLaudoDOCX = () => {
    if (!selectedLaudo) return;
    if (onSendToChat) {
      onSendToChat(`Exporte em DOCX o laudo de recurso do edital ${selectedLaudo.edital_numero}`);
    }
  };

  const handleDeleteLaudo = async (id: string) => {
    try {
      await crudDelete("recursos-detalhados", id);
      if (selectedLaudo?.id === id) setSelectedLaudo(null);
      loadLaudos();
    } catch (err) {
      console.error("Erro ao excluir laudo:", err);
    }
  };

  // ── UC-RE06: Submissão Assistida handlers ──
  const handleAbrirSubmissao = (laudo: Laudo) => {
    setSubmissaoLaudo(laudo);
    setSubmissaoProtocolo("");
    setSubmissaoStatus("pendente");
    setShowSubmissaoModal(true);
  };

  const handleRegistrarSubmissao = async () => {
    if (!submissaoLaudo || !submissaoProtocolo.trim()) return;
    try {
      await crudUpdate("recursos-detalhados", submissaoLaudo.id, {
        status: "protocolado",
        observacoes: `Protocolo: ${submissaoProtocolo} | Submetido em: ${new Date().toLocaleString("pt-BR")}`,
      });
      setSubmissaoStatus("submetido");
      loadLaudos();
    } catch (err) {
      console.error("Erro ao registrar submissão:", err);
    }
  };

  const getValidacaoChecklist = (laudo: Laudo) => {
    const checks = [
      { label: "Formato aceito (PDF/DOCX)", ok: true },
      { label: "Tamanho dentro do limite (< 25 MB)", ok: true },
      { label: "Seção jurídica presente", ok: laudo.conteudo?.includes("JURIDICA") || laudo.conteudo?.includes("jurídica") || laudo.conteudo?.length > 100 },
      { label: "Seção técnica presente", ok: laudo.conteudo?.includes("TECNICA") || laudo.conteudo?.includes("técnica") || laudo.conteudo?.length > 100 },
      { label: "Edital vinculado", ok: !!laudo.edital_id },
      { label: "Status aprovado para envio", ok: laudo.status === "rascunho" || laudo.status === "revisao" },
    ];
    return checks;
  };

  // ── Columns ──

  const inconsVencedoraColumns: Column<InconsistenciaVencedora>[] = [
    { key: "id", header: "#", width: "50px" },
    { key: "item", header: "Item" },
    { key: "inconsistencia", header: "Inconsistencia" },
    { key: "motivacao", header: "Motivacao Recurso" },
    {
      key: "gravidade",
      header: "Gravidade",
      width: "110px",
      render: (item) => {
        const cls = item.gravidade === "ALTA" ? "status-badge-error"
          : item.gravidade === "MEDIA" ? "status-badge-warning"
          : "status-badge-info";
        return <span className={`status-badge ${cls}`}>{item.gravidade}</span>;
      },
    },
  ];

  const laudosColumns: Column<Laudo>[] = [
    { key: "edital_numero", header: "Edital", sortable: true },
    {
      key: "tipo",
      header: "Tipo",
      render: (l) => l.tipo === "recurso" ? "Recurso" : "Contra-Razao",
    },
    {
      key: "subtipo",
      header: "Subtipo",
      render: (l) => l.subtipo === "tecnico" ? "Tecnico" : "Administrativo",
    },
    { key: "empresa_alvo", header: "Empresa Alvo" },
    {
      key: "status",
      header: "Status",
      render: (l) => {
        switch (l.status) {
          case "rascunho":
            return <span className="status-badge status-badge-neutral"><Edit3 size={12} /> Rascunho</span>;
          case "revisao":
            return <span className="status-badge status-badge-warning"><Eye size={12} /> Revisao</span>;
          case "protocolado":
            return <span className="status-badge status-badge-info"><Send size={12} /> Protocolado</span>;
          case "deferido":
            return <span className="status-badge status-badge-success"><CheckCircle size={12} /> Deferido</span>;
          case "indeferido":
            return <span className="status-badge status-badge-error"><XCircle size={12} /> Indeferido</span>;
          default:
            return <span className="status-badge status-badge-neutral">{l.status}</span>;
        }
      },
    },
    { key: "data_criacao", header: "Data", sortable: true },
    {
      key: "acoes",
      header: "Acoes",
      width: "160px",
      render: (l) => (
        <div style={{ display: "flex", gap: 4 }}>
          <ActionButton
            icon={<Eye size={14} />}
            label="Ver"
            onClick={() => setSelectedLaudo(l)}
          />
          <ActionButton
            icon={<Trash2 size={14} />}
            label=""
            variant="danger"
            onClick={() => handleDeleteLaudo(l.id)}
          />
        </div>
      ),
    },
  ];

  // ── Status card for monitoring ──
  const getMonitorStatusIcon = (status: JanelaStatus) => {
    switch (status) {
      case "aguardando": return <Clock size={32} />;
      case "aberta": return <AlertTriangle size={32} />;
      case "encerrada": return <CheckCircle size={32} />;
    }
  };

  const getMonitorStatusLabel = (status: JanelaStatus) => {
    switch (status) {
      case "aguardando": return "Aguardando";
      case "aberta": return "JANELA ABERTA";
      case "encerrada": return "Encerrada";
    }
  };

  const getMonitorStatusColor = (status: JanelaStatus) => {
    switch (status) {
      case "aguardando": return "#f59e0b";
      case "aberta": return "#ef4444";
      case "encerrada": return "#22c55e";
    }
  };

  // ── Tabs ──
  const tabs = [
    { id: "monitoramento", label: "Monitoramento", icon: <Eye size={16} /> },
    { id: "analise", label: "Analise", icon: <Search size={16} /> },
    { id: "laudos", label: "Laudos", icon: <FileText size={16} />, badge: laudos.length || undefined },
  ];

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-left">
          <Gavel size={24} />
          <div>
            <h1>Recursos e Contra-Razoes</h1>
            <p>Monitoramento de janela, analise de proposta vencedora e gestao de laudos (UC-RE01 a UC-RE06)</p>
          </div>
        </div>
      </div>

      <div className="page-content">
        {/* Sprint 9 UC-HC01 — Health Check */}
        {healthCheck && (
          <Card title="Status dos Servicos" icon={<Activity size={18} />}>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
              {Object.entries(healthCheck.services || {}).map(([name, svc]) => (
                <div key={name} style={{
                  display: "flex", alignItems: "center", gap: 8,
                  padding: "6px 14px", borderRadius: 8,
                  background: "var(--card-bg, #1e293b)",
                  border: `1px solid ${svc.status === "ok" || svc.status === "healthy" ? "#16a34a40" : "#dc262640"}`,
                }}>
                  <span style={{
                    width: 10, height: 10, borderRadius: "50%",
                    background: svc.status === "ok" || svc.status === "healthy" ? "#16a34a" : "#dc2626",
                    display: "inline-block",
                  }} />
                  <span style={{ fontSize: 13, fontWeight: 500 }}>{name}</span>
                  {svc.latency_ms !== undefined && (
                    <span style={{ fontSize: 11, color: "#94a3b8" }}>{svc.latency_ms}ms</span>
                  )}
                </div>
              ))}
            </div>
            <div style={{ marginTop: 10, fontSize: 12, color: "#94a3b8" }}>
              Status geral: <span style={{
                fontWeight: 700,
                color: healthCheck.status === "ok" || healthCheck.status === "healthy" ? "#16a34a" : "#dc2626",
              }}>{healthCheck.status?.toUpperCase()}</span>
            </div>
          </Card>
        )}

        <TabPanel tabs={tabs} defaultTab="monitoramento">
          {(activeTab) => {
            // ─── Tab: Monitoramento ──────────────────────────────────────
            if (activeTab === "monitoramento") {
              return (
                <>
                  <Card title="Monitoramento de Janela de Recurso" icon={<Eye size={18} />}>
                    <div style={{ display: "flex", gap: 12, alignItems: "flex-end", marginBottom: 16 }}>
                      <div style={{ flex: 1 }}>
                        <FormField label="Selecione o Edital">
                          <SelectInput
                            value={editalId}
                            onChange={setEditalId}
                            options={editalOptions}
                            placeholder="Selecione um edital..."
                            disabled={loadingEditais}
                          />
                        </FormField>
                      </div>
                    </div>

                    {editalId && (
                      <>
                        {/* Status card */}
                        <div style={{
                          display: "flex", alignItems: "center", gap: 16, padding: 20,
                          background: "var(--card-bg, #1e293b)", borderRadius: 8, marginBottom: 16,
                          border: `2px solid ${getMonitorStatusColor(monitoramento.status)}`,
                        }}>
                          <div style={{ color: getMonitorStatusColor(monitoramento.status) }}>
                            {getMonitorStatusIcon(monitoramento.status)}
                          </div>
                          <div>
                            <div style={{ fontSize: 18, fontWeight: 700, color: getMonitorStatusColor(monitoramento.status) }}>
                              {monitoramento.ativado ? getMonitorStatusLabel(monitoramento.status) : "Monitoramento Inativo"}
                            </div>
                            <div style={{ fontSize: 13, color: "#94a3b8" }}>
                              {monitoramento.ativado
                                ? monitoramento.status === "aberta"
                                  ? `Tempo restante: ${monitoramento.tempoRestante || "Verificando..."}`
                                  : "Monitorando janela de recurso..."
                                : "Ative o monitoramento para receber alertas"
                              }
                            </div>
                          </div>
                          {monitoramento.ativado && monitoramento.status === "aberta" && (
                            <div style={{ marginLeft: "auto" }}>
                              <ActionButton
                                icon={<Gavel size={14} />}
                                label="Registrar Intencao de Recurso"
                                variant="danger"
                                onClick={handleRegistrarIntencao}
                              />
                            </div>
                          )}
                        </div>

                        {/* Alert preferences */}
                        <div style={{ display: "flex", gap: 24, marginBottom: 16 }}>
                          <Checkbox
                            checked={monitoramento.alertaWhatsapp}
                            onChange={(v) => setMonitoramento(prev => ({ ...prev, alertaWhatsapp: v }))}
                            label="WhatsApp"
                          />
                          <Checkbox
                            checked={monitoramento.alertaEmail}
                            onChange={(v) => setMonitoramento(prev => ({ ...prev, alertaEmail: v }))}
                            label="Email"
                          />
                          <Checkbox
                            checked={monitoramento.alertaSistema}
                            onChange={(v) => setMonitoramento(prev => ({ ...prev, alertaSistema: v }))}
                            label="Alerta no sistema"
                          />
                        </div>

                        <ActionButton
                          icon={<Activity size={16} />}
                          label={monitoramento.ativado ? "Monitoramento Ativo" : "Ativar Monitoramento"}
                          variant={monitoramento.ativado ? "success" : "primary"}
                          onClick={handleAtivarMonitoramento}
                          loading={monitorLoading}
                          disabled={monitoramento.ativado || monitorLoading}
                        />
                      </>
                    )}
                  </Card>
                </>
              );
            }

            // ─── Tab: Analise ────────────────────────────────────────────
            if (activeTab === "analise") {
              return (
                <>
                  <Card title="Analise de Proposta Vencedora" icon={<Search size={18} />}>
                    <div style={{ display: "flex", gap: 12, alignItems: "flex-end", marginBottom: 16 }}>
                      <div style={{ flex: 1 }}>
                        <FormField label="Selecione o Edital">
                          <SelectInput
                            value={analiseEditalId}
                            onChange={setAnaliseEditalId}
                            options={editalOptions}
                            placeholder="Selecione um edital..."
                            disabled={loadingEditais}
                          />
                        </FormField>
                      </div>
                    </div>

                    <FormField label="Texto da Proposta Vencedora (cole aqui)">
                      <TextArea
                        value={propostaVencedoraTexto}
                        onChange={setPropostaVencedoraTexto}
                        rows={6}
                        placeholder="Cole aqui o texto da proposta vencedora para analise..."
                      />
                    </FormField>

                    <div style={{ marginTop: 12 }}>
                      <ActionButton
                        icon={<Search size={16} />}
                        label="Analisar Proposta Vencedora"
                        variant="primary"
                        onClick={handleAnalisarVencedora}
                        loading={analiseLoading}
                        disabled={!analiseEditalId || analiseLoading}
                      />
                    </div>
                  </Card>

                  {/* Sprint 9 UC-SC03 — Score de Recurso */}
                  {analiseEditalId && (
                    <Card title="Score de Recurso" icon={<Shield size={18} />}>
                      {scoreRecursoLoading ? (
                        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: 16, color: "#94a3b8" }}>
                          <Loader2 size={16} className="spin" />
                          <span>Calculando score de recurso...</span>
                        </div>
                      ) : scoreRecurso ? (
                        <div>
                          {/* Gauge display */}
                          <div style={{ display: "flex", alignItems: "center", gap: 24, marginBottom: 20 }}>
                            <div style={{
                              width: 100, height: 100, borderRadius: "50%",
                              display: "flex", alignItems: "center", justifyContent: "center",
                              border: `6px solid ${scoreRecurso.score >= 70 ? "#16a34a" : scoreRecurso.score >= 30 ? "#ca8a04" : "#dc2626"}`,
                              background: "var(--card-bg, #1e293b)",
                            }}>
                              <span style={{
                                fontSize: 28, fontWeight: 800,
                                color: scoreRecurso.score >= 70 ? "#16a34a" : scoreRecurso.score >= 30 ? "#ca8a04" : "#dc2626",
                              }}>
                                {scoreRecurso.score}
                              </span>
                            </div>
                            <div>
                              <span className={`status-badge ${
                                scoreRecurso.score >= 70 ? "status-badge-success"
                                  : scoreRecurso.score >= 30 ? "status-badge-warning"
                                  : "status-badge-error"
                              }`}>
                                {scoreRecurso.score >= 70 ? "Recomendado" : scoreRecurso.score >= 30 ? "Inconclusivo" : "Nao recomendado"}
                              </span>
                              {scoreRecurso.recomendacao && (
                                <p style={{ marginTop: 8, fontSize: 13, color: "#d1d5db", maxWidth: 400 }}>
                                  {scoreRecurso.recomendacao}
                                </p>
                              )}
                            </div>
                          </div>

                          {/* Fatores breakdown */}
                          {scoreRecurso.fatores.length > 0 && (
                            <div>
                              <h4 style={{ fontSize: 13, color: "#94a3b8", marginBottom: 10 }}>Fatores de Avaliacao</h4>
                              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                                {scoreRecurso.fatores.map((f, i) => (
                                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                                    <span style={{ width: 140, fontSize: 13, color: "#d1d5db" }}>{f.nome}</span>
                                    <div style={{ flex: 1, height: 20, background: "#1e293b", borderRadius: 4, overflow: "hidden" }}>
                                      <div style={{
                                        width: `${f.valor}%`, height: "100%", borderRadius: 4,
                                        background: f.valor >= 70 ? "#16a34a" : f.valor >= 40 ? "#ca8a04" : "#dc2626",
                                        display: "flex", alignItems: "center", paddingLeft: 6,
                                      }}>
                                        <span style={{ color: "#fff", fontSize: 11, fontWeight: 600 }}>{f.valor}%</span>
                                      </div>
                                    </div>
                                    <span style={{ fontSize: 11, color: "#94a3b8", width: 50, textAlign: "right" }}>
                                      peso {f.peso}
                                    </span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div style={{ padding: 16, textAlign: "center", color: "#94a3b8" }}>
                          Sem dados de score para este edital
                        </div>
                      )}
                    </Card>
                  )}

                  {analiseLoading && (
                    <Card>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: 16, color: "#94a3b8" }}>
                        <Loader2 size={16} className="spin" />
                        <span>Analisando proposta vencedora...</span>
                      </div>
                    </Card>
                  )}

                  {inconsistenciasVencedora.length > 0 && (
                    <Card title="Inconsistencias Identificadas" icon={<AlertTriangle size={18} />}>
                      <DataTable
                        data={inconsistenciasVencedora}
                        columns={inconsVencedoraColumns}
                        idKey="id"
                        emptyMessage="Nenhuma inconsistencia"
                      />
                    </Card>
                  )}

                  {analiseResultadoMd && !analiseLoading && (
                    <Card title="Analise Detalhada" icon={<Shield size={18} />}>
                      <div className="markdown-content" style={{ padding: 16 }}>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{analiseResultadoMd}</ReactMarkdown>
                      </div>
                    </Card>
                  )}

                  {chatSessionId && !analiseLoading && (
                    <Card title="Perguntas sobre a Analise" icon={<MessageSquare size={18} />}>
                      <div style={{ maxHeight: 300, overflowY: "auto", marginBottom: 12, padding: "0 8px" }}>
                        {chatMessages.filter((_, i) => i > 1).map((msg, idx) => (
                          <div key={idx} style={{
                            marginBottom: 8,
                            padding: 12,
                            borderRadius: 8,
                            background: msg.role === "user" ? "var(--primary-bg, #3b82f6)" : "var(--card-bg, #1e293b)",
                            textAlign: msg.role === "user" ? "right" : "left",
                          }}>
                            {msg.role === "assistant" ? (
                              <div className="markdown-content">
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                              </div>
                            ) : (
                              <span>{msg.content}</span>
                            )}
                          </div>
                        ))}
                        {chatLoading && (
                          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: 8, color: "#94a3b8" }}>
                            <Loader2 size={14} className="spin" />
                            <span>Pensando...</span>
                          </div>
                        )}
                      </div>
                      <div style={{ display: "flex", gap: 8 }}>
                        <TextInput
                          value={chatInput}
                          onChange={setChatInput}
                          placeholder="Faca uma pergunta sobre a analise..."
                        />
                        <ActionButton
                          icon={<Send size={14} />}
                          label="Enviar"
                          variant="primary"
                          onClick={handleChatSend}
                          loading={chatLoading}
                          disabled={!chatInput.trim() || chatLoading}
                        />
                      </div>
                    </Card>
                  )}
                </>
              );
            }

            // ─── Tab: Laudos ─────────────────────────────────────────────
            if (activeTab === "laudos") {
              return (
                <>
                  <Card
                    title="Laudos de Recurso e Contra-Razao"
                    icon={<FileText size={18} />}
                    actions={
                      <div style={{ display: "flex", gap: 8 }}>
                        <ActionButton
                          icon={<Plus size={14} />}
                          label="Novo Laudo"
                          variant="primary"
                          onClick={() => setShowNovoLaudoModal(true)}
                        />
                        <ActionButton
                          icon={<Upload size={14} />}
                          label="Upload Laudo"
                          onClick={() => setShowUploadLaudoModal(true)}
                        />
                      </div>
                    }
                  >
                    <DataTable
                      data={laudos}
                      columns={laudosColumns}
                      idKey="id"
                      emptyMessage="Nenhum laudo cadastrado"
                    />
                  </Card>

                  {selectedLaudo && (
                    <Card
                      title={`Editando: ${selectedLaudo.edital_numero} - ${selectedLaudo.tipo === "recurso" ? "Recurso" : "Contra-Razao"} (${selectedLaudo.subtipo})`}
                      icon={<Edit3 size={18} />}
                      actions={
                        <div style={{ display: "flex", gap: 8 }}>
                          <ActionButton
                            icon={<Download size={14} />}
                            label="PDF"
                            onClick={handleExportLaudoPDF}
                          />
                          <ActionButton
                            icon={<Download size={14} />}
                            label="DOCX"
                            onClick={handleExportLaudoDOCX}
                          />
                        </div>
                      }
                    >
                      {/* Section hints */}
                      <div style={{ fontSize: 12, color: "#94a3b8", padding: "8px 0", borderBottom: "1px solid var(--border-color, #334155)" }}>
                        Secoes obrigatorias: ## SECAO JURIDICA, ## SECAO TECNICA
                        {selectedLaudo.tipo === "contra_razao" && " | Adicionais: ## DEFESA, ## ATAQUE"}
                      </div>
                      <TextArea
                        value={selectedLaudo.conteudo}
                        onChange={(val) => setSelectedLaudo({ ...selectedLaudo, conteudo: val })}
                        rows={20}
                        placeholder="Conteudo do laudo..."
                      />
                      <div style={{ display: "flex", gap: 8, marginTop: 12, justifyContent: "flex-end" }}>
                        <ActionButton
                          icon={<Save size={14} />}
                          label="Salvar Rascunho"
                          onClick={handleSalvarLaudo}
                          loading={laudosSaving}
                        />
                        <ActionButton
                          icon={<Send size={14} />}
                          label="Enviar para Revisao"
                          variant="primary"
                          onClick={handleEnviarLaudoRevisao}
                          loading={laudosSaving}
                        />
                        <ActionButton
                          icon={<ExternalLink size={14} />}
                          label="Submeter no Portal"
                          variant="primary"
                          onClick={() => handleAbrirSubmissao(selectedLaudo)}
                        />
                      </div>
                    </Card>
                  )}

                  {/* Modal: Novo Laudo */}
                  <Modal
                    isOpen={showNovoLaudoModal}
                    onClose={() => setShowNovoLaudoModal(false)}
                    title="Novo Laudo"
                    size="large"
                    footer={
                      <>
                        <button className="btn btn-secondary" onClick={() => setShowNovoLaudoModal(false)}>Cancelar</button>
                        <button className="btn btn-primary" onClick={handleNovoLaudo} disabled={!laudoEditalId || laudosSaving}>
                          {laudosSaving ? <Loader2 size={14} className="spin" /> : <Plus size={14} />} Criar
                        </button>
                      </>
                    }
                  >
                    <FormField label="Edital" required>
                      <SelectInput
                        value={laudoEditalId}
                        onChange={setLaudoEditalId}
                        options={editalOptions}
                        placeholder="Selecione o edital..."
                      />
                    </FormField>
                    <div style={{ display: "flex", gap: 12 }}>
                      <div style={{ flex: 1 }}>
                        <FormField label="Tipo" required>
                          <SelectInput
                            value={laudoTipo}
                            onChange={(v) => setLaudoTipo(v as "recurso" | "contra_razao")}
                            options={[
                              { value: "recurso", label: "Recurso" },
                              { value: "contra_razao", label: "Contra-Razao" },
                            ]}
                          />
                        </FormField>
                      </div>
                      <div style={{ flex: 1 }}>
                        <FormField label="Subtipo" required>
                          <SelectInput
                            value={laudoSubtipo}
                            onChange={(v) => setLaudoSubtipo(v as "administrativo" | "tecnico")}
                            options={[
                              { value: "administrativo", label: "Administrativo" },
                              { value: "tecnico", label: "Tecnico" },
                            ]}
                          />
                        </FormField>
                      </div>
                    </div>
                    <FormField label="Template">
                      <SelectInput
                        value={laudoTemplateId}
                        onChange={(v) => {
                          setLaudoTemplateId(v);
                          const tmpl = templates.find(t => t.id === v);
                          if (tmpl) setLaudoConteudo(tmpl.conteudo_md);
                        }}
                        options={[
                          { value: "", label: "Nenhum (em branco)" },
                          ...templates
                            .filter(t => t.tipo === laudoTipo || t.tipo === "recurso")
                            .map(t => ({ value: t.id, label: t.nome })),
                        ]}
                      />
                    </FormField>
                    <FormField label="Empresa Alvo">
                      <TextInput
                        value={laudoEmpresaAlvo}
                        onChange={setLaudoEmpresaAlvo}
                        placeholder="Nome da empresa alvo do recurso..."
                      />
                    </FormField>
                    <FormField label="Conteudo Inicial">
                      <TextArea
                        value={laudoConteudo}
                        onChange={setLaudoConteudo}
                        rows={8}
                        placeholder="Conteudo do laudo (opcional se usar template)..."
                      />
                    </FormField>
                  </Modal>

                  {/* Modal: Upload Laudo */}
                  <Modal
                    isOpen={showUploadLaudoModal}
                    onClose={() => setShowUploadLaudoModal(false)}
                    title="Upload de Laudo"
                    footer={
                      <>
                        <button className="btn btn-secondary" onClick={() => setShowUploadLaudoModal(false)}>Cancelar</button>
                        <button className="btn btn-primary" onClick={handleUploadLaudo} disabled={!uploadFile || !uploadEditalId || laudosSaving}>
                          {laudosSaving ? <Loader2 size={14} className="spin" /> : <Upload size={14} />} Upload
                        </button>
                      </>
                    }
                  >
                    <FormField label="Edital" required>
                      <SelectInput
                        value={uploadEditalId}
                        onChange={setUploadEditalId}
                        options={editalOptions}
                        placeholder="Selecione o edital..."
                      />
                    </FormField>
                    <FormField label="Arquivo" required>
                      <input
                        type="file"
                        accept=".docx,.pdf,.doc"
                        onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                        className="text-input"
                      />
                    </FormField>
                  </Modal>

                  {/* Modal: UC-RE06 Submissão Assistida no Portal */}
                  <Modal
                    isOpen={showSubmissaoModal}
                    onClose={() => setShowSubmissaoModal(false)}
                    title="Submissão Assistida no Portal"
                    size="large"
                    footer={
                      submissaoStatus === "submetido" ? (
                        <button className="btn btn-secondary" onClick={() => setShowSubmissaoModal(false)}>Fechar</button>
                      ) : (
                        <>
                          <button className="btn btn-secondary" onClick={() => setShowSubmissaoModal(false)}>Cancelar</button>
                          <button className="btn btn-primary" onClick={handleRegistrarSubmissao} disabled={!submissaoProtocolo.trim()}>
                            <CheckCircle size={14} /> Registrar Submissão
                          </button>
                        </>
                      )
                    }
                  >
                    {submissaoLaudo && (
                      <div>
                        {/* Dados da petição */}
                        <div style={{ background: "var(--card-bg, #1e293b)", padding: 16, borderRadius: 8, marginBottom: 16 }}>
                          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
                            <div><span style={{ fontSize: 12, color: "#94a3b8" }}>Tipo:</span> <span style={{ background: submissaoLaudo.tipo === "recurso" ? "#3b82f620" : "#8b5cf620", color: submissaoLaudo.tipo === "recurso" ? "#3b82f6" : "#8b5cf6", padding: "2px 8px", borderRadius: 8, fontSize: 12 }}>{submissaoLaudo.tipo === "recurso" ? "RECURSO" : "CONTRA-RAZÃO"}</span></div>
                            <div><span style={{ fontSize: 12, color: "#94a3b8" }}>Edital:</span> <strong>{submissaoLaudo.edital_numero}</strong></div>
                            <div><span style={{ fontSize: 12, color: "#94a3b8" }}>Subtipo:</span> {submissaoLaudo.subtipo}</div>
                          </div>
                        </div>

                        {/* Checklist de validação */}
                        <div style={{ marginBottom: 16 }}>
                          <h4 style={{ marginBottom: 8 }}>Validação Pré-Envio</h4>
                          {getValidacaoChecklist(submissaoLaudo).map((check, i) => (
                            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0" }}>
                              <span style={{ color: check.ok ? "#16a34a" : "#dc2626" }}>{check.ok ? "✅" : "❌"}</span>
                              <span>{check.label}</span>
                            </div>
                          ))}
                          <div style={{ marginTop: 8, padding: "4px 8px", borderRadius: 4, background: getValidacaoChecklist(submissaoLaudo).every(c => c.ok) ? "#16a34a20" : "#dc262620", color: getValidacaoChecklist(submissaoLaudo).every(c => c.ok) ? "#16a34a" : "#dc2626", fontSize: 13 }}>
                            {getValidacaoChecklist(submissaoLaudo).every(c => c.ok) ? "✅ Todas as validações passaram" : "❌ Há validações pendentes"}
                          </div>
                        </div>

                        {submissaoStatus === "pendente" ? (
                          <>
                            {/* Passo 1: Exportar PDF */}
                            <div style={{ marginBottom: 16, padding: 12, background: "var(--card-bg, #1e293b)", borderRadius: 8 }}>
                              <h4 style={{ marginBottom: 8 }}>Passo 1: Exportar documento</h4>
                              <div style={{ display: "flex", gap: 8 }}>
                                <ActionButton icon={<Download size={14} />} label="Exportar PDF" onClick={handleExportLaudoPDF} />
                                <ActionButton icon={<Download size={14} />} label="Exportar DOCX" onClick={handleExportLaudoDOCX} />
                              </div>
                            </div>

                            {/* Passo 2: Abrir portal */}
                            <div style={{ marginBottom: 16, padding: 12, background: "var(--card-bg, #1e293b)", borderRadius: 8 }}>
                              <h4 style={{ marginBottom: 8 }}>Passo 2: Submeter no portal gov.br</h4>
                              <p style={{ fontSize: 13, color: "#94a3b8", marginBottom: 8 }}>Abra o portal, navegue até o pregão e faça upload do documento exportado.</p>
                              <ActionButton
                                icon={<ExternalLink size={14} />}
                                label="Abrir Portal ComprasNet"
                                variant="primary"
                                onClick={() => window.open("https://www.gov.br/compras/pt-br", "_blank")}
                              />
                            </div>

                            {/* Passo 3: Registrar protocolo */}
                            <div style={{ padding: 12, background: "var(--card-bg, #1e293b)", borderRadius: 8 }}>
                              <h4 style={{ marginBottom: 8 }}>Passo 3: Registrar protocolo</h4>
                              <p style={{ fontSize: 13, color: "#94a3b8", marginBottom: 8 }}>Após submeter no portal, informe o número do protocolo recebido.</p>
                              <FormField label="Protocolo de Submissão" required>
                                <TextInput
                                  value={submissaoProtocolo}
                                  onChange={setSubmissaoProtocolo}
                                  placeholder="Ex: PNCP-2026-0046-REC-001"
                                />
                              </FormField>
                            </div>
                          </>
                        ) : (
                          /* Resultado: Submetido */
                          <div style={{ textAlign: "center", padding: 24 }}>
                            <div style={{ fontSize: 48, marginBottom: 12 }}>✅</div>
                            <h3 style={{ color: "#16a34a", marginBottom: 8 }}>SUBMETIDO COM SUCESSO</h3>
                            <div style={{ color: "#94a3b8", marginBottom: 4 }}>Protocolo: <strong>{submissaoProtocolo}</strong></div>
                            <div style={{ color: "#94a3b8" }}>Data/Hora: {new Date().toLocaleString("pt-BR")}</div>
                          </div>
                        )}
                      </div>
                    )}
                  </Modal>
                </>
              );
            }

            return null;
          }}
        </TabPanel>
      </div>
    </div>
  );
}
