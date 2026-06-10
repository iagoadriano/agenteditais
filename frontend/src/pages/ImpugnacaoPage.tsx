import { useState, useEffect, useCallback } from "react";
import type { PageProps } from "../types";
import {
  AlertTriangle, FileText, Lightbulb, Save, Clock,
  Scale, Search, Upload, Download, Send, Eye, Loader2, Plus,
  Shield, XCircle, Trash2, Edit3,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Card, DataTable, ActionButton, FormField, TextArea,
  SelectInput, Modal, TabPanel,
} from "../components/common";
import type { Column } from "../components/common";
import { getEditais, createSession, sendMessage } from "../api/client";
import type { Edital } from "../api/client";
import { crudList, crudCreate, crudUpdate, crudDelete } from "../api/crud";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Inconsistencia {
  id: number;
  trecho: string;
  lei_violada: string;
  gravidade: "ALTA" | "MEDIA" | "BAIXA";
  sugestao: "Esclarecimento" | "Impugnacao";
}

interface Peticao {
  id: string;
  edital_id: string;
  edital_numero: string;
  tipo: "esclarecimento" | "impugnacao";
  template_id: string;
  status: "rascunho" | "revisao" | "enviada";
  conteudo: string;
  data_criacao: string;
}

interface PrazoEdital {
  id: string;
  numero: string;
  orgao: string;
  data_abertura: string;
  prazo_limite: string;
  dias_restantes: number;
  status: "ativo" | "expirado";
}

interface TemplateOption {
  id: string;
  nome: string;
  conteudo_md: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function calcularPrazoLimite(dataAbertura: string): { prazoLimite: string; diasRestantes: number; status: "ativo" | "expirado" } {
  if (!dataAbertura) return { prazoLimite: "--", diasRestantes: 0, status: "expirado" };
  const abertura = new Date(dataAbertura);
  // 3 dias uteis antes = subtrair dias uteis
  let diasUteis = 3;
  const prazo = new Date(abertura);
  while (diasUteis > 0) {
    prazo.setDate(prazo.getDate() - 1);
    const dia = prazo.getDay();
    if (dia !== 0 && dia !== 6) diasUteis--;
  }
  const hoje = new Date();
  hoje.setHours(0, 0, 0, 0);
  prazo.setHours(0, 0, 0, 0);
  const diffMs = prazo.getTime() - hoje.getTime();
  const diffDias = Math.ceil(diffMs / (1000 * 60 * 60 * 24));
  return {
    prazoLimite: prazo.toLocaleDateString("pt-BR"),
    diasRestantes: diffDias,
    status: diffDias < 0 ? "expirado" : "ativo",
  };
}

function getGravidadeBadgeClass(g: string): string {
  switch (g) {
    case "ALTA": return "status-badge-error";
    case "MEDIA": return "status-badge-warning";
    case "BAIXA": return "status-badge-info";
    default: return "status-badge-neutral";
  }
}

function getPrazoColor(dias: number): string {
  if (dias < 0) return "text-danger";
  if (dias < 3) return "text-danger";
  if (dias <= 5) return "text-warning";
  return "text-success";
}

// ─── Component ────────────────────────────────────────────────────────────────

export function ImpugnacaoPage(props?: PageProps) {
  const { onSendToChat } = props ?? {};

  // ── Shared state ──
  const [editais, setEditais] = useState<Edital[]>([]);
  const [editalId, setEditalId] = useState("");
  const [loadingEditais, setLoadingEditais] = useState(false);

  // ── Tab: Validacao Legal ──
  const [inconsistencias, setInconsistencias] = useState<Inconsistencia[]>([]);
  const [validacaoLoading, setValidacaoLoading] = useState(false);
  const [validacaoStatus, setValidacaoStatus] = useState("");
  const [peticaoSugerida, setPeticaoSugerida] = useState("");
  const [peticaoLoading, setPeticaoLoading] = useState(false);

  // ── Tab: Peticoes ──
  const [peticoes, setPeticoes] = useState<Peticao[]>([]);
  const [selectedPeticao, setSelectedPeticao] = useState<Peticao | null>(null);
  const [showNovaPeticaoModal, setShowNovaPeticaoModal] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [peticaoTipo, setPeticaoTipo] = useState<"esclarecimento" | "impugnacao">("esclarecimento");
  const [peticaoTemplateId, setPeticaoTemplateId] = useState("");
  const [peticaoEditalId, setPeticaoEditalId] = useState("");
  const [peticaoConteudo, setPeticaoConteudo] = useState("");
  const [templates, setTemplates] = useState<TemplateOption[]>([]);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadEditalId, setUploadEditalId] = useState("");
  const [peticoesSaving, setPeticoesSaving] = useState(false);

  // ── Tab: Prazos ──
  const [prazos, setPrazos] = useState<PrazoEdital[]>([]);

  // ── Load editais ──
  useEffect(() => {
    loadEditais();
    loadTemplates();
    loadPeticoes();
  }, []);

  const loadEditais = async () => {
    setLoadingEditais(true);
    try {
      const data = await getEditais();
      setEditais(data || []);
      // Build prazos from editais
      const prazosList: PrazoEdital[] = (data || [])
        .filter((e: Edital) => e.data_abertura)
        .map((e: Edital) => {
          const { prazoLimite, diasRestantes, status } = calcularPrazoLimite(e.data_abertura || "");
          return {
            id: e.id || "",
            numero: e.numero,
            orgao: e.orgao,
            data_abertura: e.data_abertura ? new Date(e.data_abertura).toLocaleDateString("pt-BR") : "--",
            prazo_limite: prazoLimite,
            dias_restantes: diasRestantes,
            status,
          };
        })
        .sort((a: PrazoEdital, b: PrazoEdital) => a.dias_restantes - b.dias_restantes);
      setPrazos(prazosList);
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
        })));
      }
    } catch {
      // Templates table may not exist yet - graceful fallback
      setTemplates([]);
    }
  };

  const loadPeticoes = async () => {
    try {
      const data = await crudList("recursos");
      // crudList pode retornar array puro OU envelope paginado {items,total,...}
      const lista = Array.isArray(data) ? data : (data?.items || []);
      {
        setPeticoes(lista.map((r: Record<string, unknown>) => ({
          id: String(r.id),
          edital_id: String(r.edital_id || ""),
          edital_numero: String(r.edital_numero || r.edital_id || ""),
          tipo: (r.tipo === "impugnacao" ? "impugnacao" : "esclarecimento") as "esclarecimento" | "impugnacao",
          template_id: String(r.template_id || ""),
          status: (r.status as Peticao["status"]) || "rascunho",
          conteudo: String(r.texto_minuta || ""),
          data_criacao: r.created_at ? new Date(String(r.created_at)).toLocaleDateString("pt-BR") : new Date().toLocaleDateString("pt-BR"),
        })));
      }
    } catch {
      setPeticoes([]);
    }
  };

  // ── Validacao Legal handlers ──

  const handleAnalisarEdital = useCallback(async () => {
    if (!editalId) return;
    setValidacaoLoading(true);
    setValidacaoStatus("Analisando conformidade legal do edital...");
    setInconsistencias([]);
    setPeticaoSugerida("");
    try {
      // Chamar endpoint direto que usa tool_validacao_legal_edital (lê PDF real)
      const token = localStorage.getItem("editais_ia_access_token");
      const resp = await fetch(`/api/editais/${editalId}/validacao-legal`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      });
      const data = await resp.json();
      setValidacaoStatus("");

      if (data.success && data.inconsistencias && data.inconsistencias.length > 0) {
        // Mapear inconsistências da tool para o formato do frontend
        const mapped = data.inconsistencias.map((inc: any, idx: number) => ({
          id: String(idx + 1),
          trecho: inc.trecho || "",
          lei_violada: inc.lei_violada || "",
          gravidade: (inc.gravidade || "media").toLowerCase(),
          sugestao_tipo: inc.sugestao_tipo || "esclarecimento",
          fundamentacao: inc.fundamentacao || "",
          sugestao_correcao: inc.sugestao_correcao || "",
        }));
        setInconsistencias(mapped);
      } else if (data.sem_pdf) {
        setPeticaoSugerida("⚠️ Este edital não possui PDF com texto extraído. Baixe o PDF do edital primeiro para realizar a análise legal.");
      } else if (data.error) {
        setPeticaoSugerida(`❌ Erro: ${data.error}`);
      } else {
        setPeticaoSugerida("✅ Nenhuma inconsistência legal encontrada neste edital.");
      }
    } catch (err) {
      console.error("Erro na validacao legal:", err);
      setValidacaoStatus("Erro ao analisar edital.");
    } finally {
      setValidacaoLoading(false);
    }
  }, [editalId]);

  const handleGerarPeticao = useCallback(async () => {
    if (!editalId) return;
    setPeticaoLoading(true);
    try {
      const session = await createSession("gerar-peticao");
      const sid = String(session.session_id || session.id);
      const edital = editais.find(e => e.id === editalId);
      const incons = inconsistencias.map(i => `- ${i.trecho} (${i.lei_violada})`).join("\n");
      const prompt = `Gere uma peticao de impugnacao para o edital ${edital?.numero || editalId} com base nas seguintes inconsistencias:\n${incons || "Inconsistencias identificadas na analise anterior."}\n\nUse formato formal de peticao com: Cabecalho, Dos Fatos, Do Direito, Do Pedido, e encerramento. Responda em markdown.`;
      const resp = await sendMessage(sid, prompt);
      setPeticaoSugerida(resp.response || "");
    } catch (err) {
      console.error("Erro ao gerar peticao:", err);
    } finally {
      setPeticaoLoading(false);
    }
  }, [editalId, editais, inconsistencias]);

  // ── Peticoes handlers ──

  const handleGerarComIA = async () => {
    if (!peticaoEditalId) return;
    setPeticoesSaving(true);
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      const resp = await fetch(`/api/editais/${peticaoEditalId}/sugerir-peticao`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ tipo: peticaoTipo, template_id: peticaoTemplateId || null }),
      });
      const data = await resp.json();
      if (data?.success) {
        // backend ja criou registro Impugnacao com texto; pega o texto pra mostrar
        const texto = data.texto || data.texto_minuta || data.conteudo || "";
        if (texto) setPeticaoConteudo(texto);
        loadPeticoes();
      } else if (data?.error) {
        console.error("IA peticao:", data.error);
      }
    } catch (e) {
      console.error("Erro IA peticao:", e);
    } finally {
      setPeticoesSaving(false);
    }
  };

  const handleNovaPeticao = async () => {
    if (!peticaoEditalId) return;
    setPeticoesSaving(true);
    try {
      let conteudo = peticaoConteudo;
      if (peticaoTemplateId && !conteudo) {
        const tmpl = templates.find(t => t.id === peticaoTemplateId);
        conteudo = tmpl?.conteudo_md || "";
      }
      await crudCreate("recursos", {
        edital_id: peticaoEditalId,
        tipo: peticaoTipo,
        motivo: peticaoTipo === "impugnacao" ? "Impugnacao ao edital" : "Pedido de esclarecimento",
        texto_minuta: conteudo,
        status: "rascunho",
        prazo_limite: new Date().toISOString(),
      });
      setShowNovaPeticaoModal(false);
      setPeticaoTipo("esclarecimento");
      setPeticaoTemplateId("");
      setPeticaoEditalId("");
      setPeticaoConteudo("");
      loadPeticoes();
    } catch (err) {
      console.error("Erro ao criar peticao:", err);
    } finally {
      setPeticoesSaving(false);
    }
  };

  const handleUploadPeticao = async () => {
    if (!uploadFile || !uploadEditalId) return;
    setPeticoesSaving(true);
    try {
      // Read file contents
      const text = await uploadFile.text();
      await crudCreate("recursos", {
        edital_id: uploadEditalId,
        tipo: "impugnacao",
        motivo: `Upload: ${uploadFile.name}`,
        texto_minuta: text,
        status: "rascunho",
        prazo_limite: new Date().toISOString(),
        arquivo_path: uploadFile.name,
      });
      setShowUploadModal(false);
      setUploadFile(null);
      setUploadEditalId("");
      loadPeticoes();
    } catch (err) {
      console.error("Erro ao fazer upload:", err);
    } finally {
      setPeticoesSaving(false);
    }
  };

  const handleSalvarRascunho = async () => {
    if (!selectedPeticao) return;
    setPeticoesSaving(true);
    try {
      await crudUpdate("recursos", selectedPeticao.id, {
        texto_minuta: selectedPeticao.conteudo,
        status: "rascunho",
      });
      loadPeticoes();
    } catch (err) {
      console.error("Erro ao salvar:", err);
    } finally {
      setPeticoesSaving(false);
    }
  };

  const handleEnviarRevisao = async () => {
    if (!selectedPeticao) return;
    setPeticoesSaving(true);
    try {
      await crudUpdate("recursos", selectedPeticao.id, {
        texto_minuta: selectedPeticao.conteudo,
        status: "protocolado",
      });
      loadPeticoes();
      setSelectedPeticao(null);
    } catch (err) {
      console.error("Erro ao enviar para revisao:", err);
    } finally {
      setPeticoesSaving(false);
    }
  };

  const handleExportPDF = () => {
    if (!selectedPeticao) return;
    if (onSendToChat) {
      onSendToChat(`Exporte em PDF a peticao do edital ${selectedPeticao.edital_numero}`);
    }
  };

  const handleExportDOCX = () => {
    if (!selectedPeticao) return;
    if (onSendToChat) {
      onSendToChat(`Exporte em DOCX a peticao do edital ${selectedPeticao.edital_numero}`);
    }
  };

  const handleDeletePeticao = async (id: string) => {
    try {
      await crudDelete("recursos", id);
      if (selectedPeticao?.id === id) setSelectedPeticao(null);
      loadPeticoes();
    } catch (err) {
      console.error("Erro ao excluir peticao:", err);
    }
  };

  // ── Edital options ──
  const editalOptions = editais.map(e => ({
    value: e.id || "",
    label: `${e.numero} - ${e.orgao}`,
  }));

  // ── Columns ──

  const inconsistenciasColumns: Column<Inconsistencia>[] = [
    { key: "id", header: "#", width: "50px" },
    { key: "trecho", header: "Trecho" },
    { key: "lei_violada", header: "Lei Violada" },
    {
      key: "gravidade",
      header: "Gravidade",
      width: "120px",
      render: (item) => (
        <span className={`status-badge ${getGravidadeBadgeClass(item.gravidade)}`}>
          {item.gravidade}
        </span>
      ),
    },
    {
      key: "sugestao",
      header: "Sugestao",
      width: "140px",
      render: (item) => (
        <span className={`status-badge ${item.sugestao === "Impugnacao" ? "status-badge-error" : "status-badge-info"}`}>
          {item.sugestao}
        </span>
      ),
    },
  ];

  const peticoesColumns: Column<Peticao>[] = [
    { key: "edital_numero", header: "Edital", sortable: true },
    {
      key: "tipo",
      header: "Tipo",
      render: (p) => p.tipo === "impugnacao" ? "Impugnacao" : "Esclarecimento",
    },
    {
      key: "status",
      header: "Status",
      render: (p) => {
        switch (p.status) {
          case "rascunho":
            return <span className="status-badge status-badge-neutral"><Edit3 size={12} /> Rascunho</span>;
          case "revisao":
            return <span className="status-badge status-badge-warning"><Eye size={12} /> Em Revisao</span>;
          case "enviada":
            return <span className="status-badge status-badge-success"><Send size={12} /> Enviada</span>;
          default:
            return <span className="status-badge status-badge-neutral">{p.status}</span>;
        }
      },
    },
    { key: "data_criacao", header: "Data", sortable: true },
    {
      key: "acoes",
      header: "Acoes",
      width: "160px",
      render: (p) => (
        <div style={{ display: "flex", gap: 4 }}>
          <ActionButton
            icon={<Eye size={14} />}
            label="Ver"
            onClick={() => setSelectedPeticao(p)}
          />
          <ActionButton
            icon={<Trash2 size={14} />}
            label=""
            variant="danger"
            onClick={() => handleDeletePeticao(p.id)}
          />
        </div>
      ),
    },
  ];

  const prazosColumns: Column<PrazoEdital>[] = [
    { key: "numero", header: "Edital", sortable: true },
    { key: "orgao", header: "Orgao" },
    { key: "data_abertura", header: "Data Abertura", sortable: true },
    { key: "prazo_limite", header: "Prazo Limite (3d uteis)", sortable: true },
    {
      key: "dias_restantes",
      header: "Dias Restantes",
      sortable: true,
      render: (p) => (
        <span className={getPrazoColor(p.dias_restantes)} style={{ fontWeight: 600 }}>
          {p.status === "expirado" ? (
            <span className="status-badge status-badge-error"><XCircle size={12} /> EXPIRADO</span>
          ) : (
            `${p.dias_restantes} dias`
          )}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (p) => {
        if (p.status === "expirado") {
          return <span className="status-badge status-badge-error">Expirado</span>;
        }
        if (p.dias_restantes > 5) {
          return <span className="status-badge status-badge-success">OK</span>;
        }
        if (p.dias_restantes >= 3) {
          return <span className="status-badge status-badge-warning">Atencao</span>;
        }
        return <span className="status-badge status-badge-error">Urgente</span>;
      },
    },
  ];

  // ─── Tabs ──────────────────────────────────────────────────────────────────

  const tabs = [
    { id: "validacao", label: "Validacao Legal", icon: <Scale size={16} /> },
    { id: "peticoes", label: "Peticoes", icon: <FileText size={16} />, badge: peticoes.length || undefined },
    { id: "prazos", label: "Prazos", icon: <Clock size={16} />, badge: prazos.filter(p => p.dias_restantes <= 5 && p.status !== "expirado").length || undefined },
  ];

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-left">
          <AlertTriangle size={24} />
          <div>
            <h1>Impugnacoes e Esclarecimentos</h1>
            <p>Validacao legal, peticoes e controle de prazos (UC-I01 a UC-I05)</p>
          </div>
        </div>
      </div>

      <div className="page-content">
        <TabPanel tabs={tabs} defaultTab="validacao">
          {(activeTab) => {
            // ─── Tab: Validacao Legal ────────────────────────────────────
            if (activeTab === "validacao") {
              return (
                <>
                  <Card title="Analise de Conformidade Legal" icon={<Scale size={18} />}>
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
                      <ActionButton
                        icon={<Search size={16} />}
                        label="Analisar Edital"
                        variant="primary"
                        onClick={handleAnalisarEdital}
                        loading={validacaoLoading}
                        disabled={!editalId || validacaoLoading}
                      />
                    </div>

                    {validacaoLoading && (
                      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: 16, color: "#94a3b8" }}>
                        <Loader2 size={16} className="spin" />
                        <span>{validacaoStatus || "Analisando..."}</span>
                      </div>
                    )}

                    {inconsistencias.length > 0 && (
                      <>
                        <DataTable
                          data={inconsistencias}
                          columns={inconsistenciasColumns}
                          idKey="id"
                          emptyMessage="Nenhuma inconsistencia encontrada"
                        />
                        <div style={{ marginTop: 12 }}>
                          <ActionButton
                            icon={<Lightbulb size={16} />}
                            label="Gerar Peticao"
                            variant="primary"
                            onClick={handleGerarPeticao}
                            loading={peticaoLoading}
                            disabled={peticaoLoading}
                          />
                        </div>
                      </>
                    )}

                    {peticaoSugerida && (
                      <Card title="Resultado da Analise" icon={<Shield size={18} />}>
                        <div className="markdown-content" style={{ padding: 16 }}>
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{peticaoSugerida}</ReactMarkdown>
                        </div>
                      </Card>
                    )}
                  </Card>
                </>
              );
            }

            // ─── Tab: Peticoes ───────────────────────────────────────────
            if (activeTab === "peticoes") {
              return (
                <>
                  <Card
                    title="Peticoes"
                    icon={<FileText size={18} />}
                    actions={
                      <div style={{ display: "flex", gap: 8 }}>
                        <ActionButton
                          icon={<Plus size={14} />}
                          label="Nova Peticao"
                          variant="primary"
                          onClick={() => setShowNovaPeticaoModal(true)}
                        />
                        <ActionButton
                          icon={<Upload size={14} />}
                          label="Upload Peticao"
                          onClick={() => setShowUploadModal(true)}
                        />
                      </div>
                    }
                  >
                    <DataTable
                      data={peticoes}
                      columns={peticoesColumns}
                      idKey="id"
                      emptyMessage="Nenhuma peticao cadastrada"
                    />
                  </Card>

                  {selectedPeticao && (
                    <Card
                      title={`Editando: ${selectedPeticao.edital_numero} - ${selectedPeticao.tipo === "impugnacao" ? "Impugnacao" : "Esclarecimento"}`}
                      icon={<Edit3 size={18} />}
                      actions={
                        <div style={{ display: "flex", gap: 8 }}>
                          <ActionButton
                            icon={<Download size={14} />}
                            label="PDF"
                            onClick={handleExportPDF}
                          />
                          <ActionButton
                            icon={<Download size={14} />}
                            label="DOCX"
                            onClick={handleExportDOCX}
                          />
                        </div>
                      }
                    >
                      {/* Simple rich editor toolbar */}
                      <div style={{ display: "flex", gap: 4, padding: "8px 0", borderBottom: "1px solid var(--border-color, #334155)" }}>
                        <button className="btn btn-secondary btn-sm" onClick={() => setPeticaoConteudo(selectedPeticao.conteudo)} title="Copiar para edicao" style={{ fontSize: 12, padding: "4px 8px" }}>
                          Editar
                        </button>
                      </div>
                      <TextArea
                        value={selectedPeticao.conteudo}
                        onChange={(val) => setSelectedPeticao({ ...selectedPeticao, conteudo: val })}
                        rows={18}
                        placeholder="Conteudo da peticao..."
                      />
                      <div style={{ display: "flex", gap: 8, marginTop: 12, justifyContent: "flex-end" }}>
                        <ActionButton
                          icon={<Save size={14} />}
                          label="Salvar Rascunho"
                          onClick={handleSalvarRascunho}
                          loading={peticoesSaving}
                        />
                        <ActionButton
                          icon={<Send size={14} />}
                          label="Enviar para Revisao"
                          variant="primary"
                          onClick={handleEnviarRevisao}
                          loading={peticoesSaving}
                        />
                      </div>
                    </Card>
                  )}

                  {/* Modal: Nova Peticao */}
                  <Modal
                    isOpen={showNovaPeticaoModal}
                    onClose={() => setShowNovaPeticaoModal(false)}
                    title="Nova Peticao"
                    size="large"
                    footer={
                      <>
                        <button className="btn btn-secondary" onClick={() => setShowNovaPeticaoModal(false)}>Cancelar</button>
                        <button className="btn btn-info" onClick={handleGerarComIA} disabled={!peticaoEditalId || peticoesSaving} title="Gera a peça com IA usando a inconsistencias detectadas na analise legal">
                          {peticoesSaving ? <Loader2 size={14} className="spin" /> : <Lightbulb size={14} />} Gerar com IA
                        </button>
                        <button className="btn btn-primary" onClick={handleNovaPeticao} disabled={!peticaoEditalId || peticoesSaving}>
                          {peticoesSaving ? <Loader2 size={14} className="spin" /> : <Plus size={14} />} Criar
                        </button>
                      </>
                    }
                  >
                    <FormField label="Edital" required>
                      <SelectInput
                        value={peticaoEditalId}
                        onChange={setPeticaoEditalId}
                        options={editalOptions}
                        placeholder="Selecione o edital..."
                      />
                    </FormField>
                    <FormField label="Tipo" required>
                      <SelectInput
                        value={peticaoTipo}
                        onChange={(v) => setPeticaoTipo(v as "esclarecimento" | "impugnacao")}
                        options={[
                          { value: "esclarecimento", label: "Esclarecimento" },
                          { value: "impugnacao", label: "Impugnacao" },
                        ]}
                      />
                    </FormField>
                    <FormField label="Template">
                      <SelectInput
                        value={peticaoTemplateId}
                        onChange={(v) => {
                          setPeticaoTemplateId(v);
                          const tmpl = templates.find(t => t.id === v);
                          if (tmpl) setPeticaoConteudo(tmpl.conteudo_md);
                        }}
                        options={[
                          { value: "", label: "Nenhum (em branco)" },
                          ...templates.map(t => ({ value: t.id, label: t.nome })),
                        ]}
                      />
                    </FormField>
                    <FormField label="Conteudo">
                      <TextArea
                        value={peticaoConteudo}
                        onChange={setPeticaoConteudo}
                        rows={8}
                        placeholder="Conteudo da peticao (opcional se usar template)..."
                      />
                    </FormField>
                  </Modal>

                  {/* Modal: Upload Peticao */}
                  <Modal
                    isOpen={showUploadModal}
                    onClose={() => setShowUploadModal(false)}
                    title="Upload de Peticao"
                    footer={
                      <>
                        <button className="btn btn-secondary" onClick={() => setShowUploadModal(false)}>Cancelar</button>
                        <button className="btn btn-primary" onClick={handleUploadPeticao} disabled={!uploadFile || !uploadEditalId || peticoesSaving}>
                          {peticoesSaving ? <Loader2 size={14} className="spin" /> : <Upload size={14} />} Upload
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
                    <FormField label="Arquivo (.docx / .pdf)" required>
                      <input
                        type="file"
                        accept=".docx,.pdf,.doc"
                        onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                        className="text-input"
                      />
                    </FormField>
                  </Modal>
                </>
              );
            }

            // ─── Tab: Prazos ────────────────────────────────────────────
            if (activeTab === "prazos") {
              return (
                <Card title="Prazos de Impugnacao e Esclarecimento" icon={<Clock size={18} />}>
                  {loadingEditais ? (
                    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: 16, color: "#94a3b8" }}>
                      <Loader2 size={16} className="spin" />
                      <span>Carregando prazos...</span>
                    </div>
                  ) : (
                    <DataTable
                      data={prazos}
                      columns={prazosColumns}
                      idKey="id"
                      emptyMessage="Nenhum edital com data de abertura definida"
                    />
                  )}
                </Card>
              );
            }

            return null;
          }}
        </TabPanel>
      </div>
    </div>
  );
}
