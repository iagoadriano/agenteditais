import { useState, useEffect, useCallback } from "react";
import type { PageProps } from "../types";
import {
  ClipboardCheck, Eye, MessageSquare, FileText, CheckCircle, XCircle, Clock,
  AlertTriangle, Shield, TrendingUp, Target, ThumbsUp, X, Sparkles, Building,
  AlertCircle, Scale, FolderOpen, Search, RefreshCw, Layers
} from "lucide-react";
import {
  Card, DataTable, ActionButton, FilterBar, Modal, FormField, TextInput, TextArea,
  SelectInput, ScoreBar, ScoreCircle, StatusBadge, TabPanel
} from "../components/common";
import type { Column } from "../components/common";
import { crudList, crudCreate, crudUpdate } from "../api/crud";
import { createSession } from "../api/client";
import { PdfViewer } from "../components/PdfViewer";

// === INTERFACES ===

interface EditalScores {
  tecnico: number;
  documental: number;
  complexidade: number;
  juridico: number;
  logistico: number;
  comercial: number;
}

interface Certificacao {
  nome: string;
  status: "ok" | "pendente" | "vencida";
}

interface ChecklistItem {
  documento: string;
  status: "ok" | "vencido" | "faltando" | "ajustavel";
  validade?: string;
}

interface LoteItem {
  item: string;
  tipo: "aderente" | "intruso";
}

interface AderenciaTrecho {
  trechoEdital: string;
  aderencia: number;
  trechoPortfolio: string;
}

interface HistoricoItem {
  nome: string;
  resultado: "vencida" | "perdida" | "cancelada";
  motivo?: string;
}

interface ReputacaoOrgao {
  pregoeiro: string;
  pagador: string;
  historico: string;
}

interface Edital {
  id: string;
  numero: string;
  orgao: string;
  uf: string;
  objeto: string;
  valor: number;
  dataAbertura: string;
  status: "novo" | "go" | "avaliando" | "nogo";
  score: number;
  scores: EditalScores;
  potencialGanho: "elevado" | "medio" | "baixo";
  intencaoEstrategica: "estrategico" | "defensivo" | "acompanhamento" | "aprendizado";
  margemExpectativa: number;
  sinaisMercado: string[];
  fatalFlaws: string[];
  flagsJuridicos: string[];
  certificacoes: Certificacao[];
  checklistDocumental: ChecklistItem[];
  analiseLote: LoteItem[];
  aderenciaTrechos: AderenciaTrecho[];
  reputacaoOrgao: ReputacaoOrgao;
  historicoSemelhante: HistoricoItem[];
  resumo?: string;
  pdfUrl?: string;
  pdfPath?: string;
  url?: string;
  produtoCorrespondente?: string;
  // IDs para persistência
  decisaoId?: string;
}

interface EditalItemData {
  id: string;
  numero_item: number;
  descricao: string;
  unidade_medida: string;
  quantidade: number;
  valor_unitario_estimado: number;
  valor_total_estimado: number;
  tipo_beneficio?: string;
}

interface LoteData {
  id: string;
  numero_lote: number;
  nome: string;
  especialidade?: string;
  valor_estimado?: number;
  status: string;
  itens: EditalItemData[];
}

// Sem dados mock — tabela alimentada 100% pelo backend (T18)

// === INTERFACES ADICIONAIS PARA RESPOSTA DO BACKEND ===

interface ScoresValidacaoResponse {
  scores: EditalScores;
  score_geral: number;
  potencial_ganho: Edital["potencialGanho"];
  decisao_ia?: "GO" | "NO-GO" | "CONDICIONAL";
  decisao?: string; // "go" | "nogo" | "acompanhar" — campo alternativo do endpoint
  justificativa_ia?: string;
  sub_scores_tecnicos?: { label: string; score: number }[];
  certificacoes?: Certificacao[];
  checklist_documental?: ChecklistItem[];
  analise_lote?: LoteItem[];
  aderencia_trechos?: AderenciaTrecho[];
  sinais_mercado?: string[];
  fatal_flaws?: string[];
  flags_juridicos?: string[];
  pontos_positivos?: string[];
  pontos_atencao?: string[];
}

// === INTERFACES PARA DOCUMENTACAO NECESSARIA ===

interface DocNecessariaItem {
  nome: string;
  categoria: string; // "empresa", "fiscal", "tecnica"
  status: "ok" | "faltando" | "vencido";
  validade?: string;
  exigido?: boolean;
  descricao_edital?: string; // descrição do requisito extraído do PDF do edital
}

interface DocNecessariaResponse {
  documentos: DocNecessariaItem[];
  fonte?: string; // "requisitos_edital" | "padrao_licitacao"
}

// === INTERFACES PARA HISTORICO SEMELHANTE REAL ===

interface HistoricoRealItem {
  id: string;
  numero: string;
  orgao: string;
  objeto: string;
  score?: number;
  decisao?: string;
}

// === HELPERS ===

// Gera session_id único por sessão de página
// Sessão será criada sob demanda na primeira chamada IA
let _pageSessionId: string | null = null;
async function getOrCreateSession(): Promise<string> {
  if (_pageSessionId) return _pageSessionId;
  const session = await createSession("validacao-ia");
  _pageSessionId = String(session.session_id || session.id || "");
  if (!_pageSessionId) throw new Error("Falha ao criar sessão");
  return _pageSessionId;
}

// T18: Carrega editais salvos do backend via GET /api/editais/salvos
async function loadEditaisSalvos(): Promise<Edital[]> {
  const token = localStorage.getItem("editais_ia_access_token");
  const res = await fetch("/api/editais/salvos?com_score=true&com_estrategia=true", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`Erro ao carregar editais: ${res.status}`);
  const data = await res.json();
  return (data.editais || data || []).map((e: Record<string, unknown>) => ({
    id: String(e.id || e.edital_id || ""),
    numero: String(e.numero || e.numero_edital || ""),
    orgao: String(e.orgao || ""),
    uf: String(e.uf || ""),
    objeto: String(e.objeto || ""),
    valor: Number(e.valor_referencia || e.valor || 0),
    dataAbertura: String(e.data_abertura || e.dataAbertura || ""),
    status: (() => {
      const s = String(e.status_validacao || e.status || "novo");
      // Mapear status antigos para novos
      if (s === "validado" || s === "participando") return "go";
      if (s === "analisando") return "avaliando";
      if (s === "descartado") return "nogo";
      if (s === "go" || s === "avaliando" || s === "nogo") return s;
      return "novo";
    })() as Edital["status"],
    score: Number(e.score_geral || e.score || 0),
    scores: (e.scores as EditalScores) || { tecnico: 0, documental: 0, complexidade: 0, juridico: 0, logistico: 0, comercial: 0 },
    potencialGanho: ((e.potencial_ganho || e.potencialGanho || "medio") as Edital["potencialGanho"]),
    intencaoEstrategica: ((e.intencao_estrategica || e.intencaoEstrategica || "acompanhamento") as Edital["intencaoEstrategica"]),
    margemExpectativa: Number(e.margem_expectativa || e.margemExpectativa || 0),
    sinaisMercado: (e.sinais_mercado as string[]) || [],
    fatalFlaws: (e.fatal_flaws as string[]) || [],
    flagsJuridicos: (e.flags_juridicos as string[]) || [],
    certificacoes: (e.certificacoes as Certificacao[]) || [],
    checklistDocumental: (e.checklist_documental as ChecklistItem[]) || [],
    analiseLote: (e.analise_lote as LoteItem[]) || [],
    aderenciaTrechos: (e.aderencia_trechos as AderenciaTrecho[]) || [],
    reputacaoOrgao: (e.reputacao_orgao as ReputacaoOrgao) || { pregoeiro: "-", pagador: "-", historico: "-" },
    historicoSemelhante: (e.historico_semelhante as HistoricoItem[]) || [],
    resumo: e.resumo as string | undefined,
    pdfUrl: (e.pdf_url || e.pdfUrl) as string | undefined,
    pdfPath: (e.pdf_path || e.pdfPath) as string | undefined,
    url: (e.url) as string | undefined,
    produtoCorrespondente: (e.produto_correspondente || e.produtoCorrespondente) as string | undefined,
    decisaoId: e.decisao_id as string | undefined,
  }));
}

// T19: Calcula scores via POST /api/editais/{id}/scores-validacao (endpoint real)
async function calcularScoresValidacao(editalId: string): Promise<ScoresValidacaoResponse | null> {
  try {
    const token = localStorage.getItem("editais_ia_access_token");
    console.log(`[SCORES] POST /api/editais/${editalId}/scores-validacao ...`);
    const res = await fetch(`/api/editais/${editalId}/scores-validacao`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({}),
    });
    if (!res.ok) {
      console.error(`[SCORES] Erro HTTP ${res.status}: ${res.statusText}`);
      return null;
    }
    const data = await res.json();
    console.log("[SCORES] Resposta:", data);
    if (!data.success) {
      console.error("[SCORES] Backend retornou erro:", data.error);
      return null;
    }
    return data as ScoresValidacaoResponse;
  } catch (err) {
    console.error("[SCORES] Erro de rede:", err);
    return null;
  }
}

// === COMPONENTE PRINCIPAL ===

export function ValidacaoPage(props?: PageProps) {
  const onSendToChat = props?.onSendToChat;

  // T18: inicia vazio — alimentado exclusivamente pelo backend
  const [editais, setEditais] = useState<Edital[]>([]);
  const [loadingEditais, setLoadingEditais] = useState(true);
  const [erroCarregamento, setErroCarregamento] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState("todos");
  const [selectedEdital, setSelectedEdital] = useState<Edital | null>(null);
  const [showPerguntaModal, setShowPerguntaModal] = useState(false);
  const [pergunta, setPergunta] = useState("");
  const [resposta, setResposta] = useState("");
  // CV13-11 (Arnaldo Sprint 2 V8): manter historico de Q&A da sessao
  // (cada nova pergunta era sobrescrevendo a anterior — perdia contexto).
  const [historicoQA, setHistoricoQA] = useState<Array<{ pergunta: string; resposta: string; ts: number }>>([]);
  const [loading, setLoading] = useState(false);
  const [resumoLoading, setResumoLoading] = useState(false);
  const [showJustificativa, setShowJustificativa] = useState(false);
  const [justificativaMotivo, setJustificativaMotivo] = useState("");
  const [justificativaTexto, setJustificativaTexto] = useState("");
  const [salvandoDecisao, setSalvandoDecisao] = useState(false);
  const [decisaoSalva, setDecisaoSalva] = useState(false);
  const [erroDecisao, setErroDecisao] = useState("");
  const [pendingDecisao, setPendingDecisao] = useState<"participar" | "acompanhar" | "ignorar" | null>(null);
  const [scoresLoading, setScoresLoading] = useState(false);
  // T22: sub-scores técnicos da aba Objetiva (vindos do endpoint scores-validacao)
  const [subScoresTecnicos, setSubScoresTecnicos] = useState<{ label: string; score: number }[]>([]);
  const [decisaoIA, setDecisaoIA] = useState<"GO" | "NO-GO" | "CONDICIONAL" | null>(null);
  const [justificativaIA, setJustificativaIA] = useState("");
  const [pontosPositivos, setPontosPositivos] = useState<string[]>([]);
  const [pontosAtencao, setPontosAtencao] = useState<string[]>([]);

  // Documentação necessária — dados reais do backend
  const [docsNecessaria, setDocsNecessaria] = useState<DocNecessariaItem[]>([]);
  const [docsNecessariaLoading, setDocsNecessariaLoading] = useState(false);
  const [docsNecessariaErro, setDocsNecessariaErro] = useState("");
  const [docsNecessariaFonte, setDocsNecessariaFonte] = useState<string>("");
  const [extraindoRequisitos, setExtraindoRequisitos] = useState(false);

  // Análise de riscos
  const [riscosData, setRiscosData] = useState<Record<string, unknown> | null>(null);
  const [riscosLoading, setRiscosLoading] = useState(false);
  // Histórico de vencedores
  const [historicoVencedores, setHistoricoVencedores] = useState<Record<string, unknown> | null>(null);
  const [historicoVencedoresLoading, setHistoricoVencedoresLoading] = useState(false);
  // Vencedores detalhados das atas
  const [vencedoresAtas, setVencedoresAtas] = useState<Record<string, unknown> | null>(null);
  const [vencedoresAtasLoading, setVencedoresAtasLoading] = useState(false);
  // Análise de mercado
  const [mercadoData, setMercadoData] = useState<Record<string, unknown> | null>(null);
  const [mercadoLoading, setMercadoLoading] = useState(false);
  // Concorrentes
  const [concorrentesLista, setConcorrentesLista] = useState<Record<string, unknown>[] | null>(null);
  const [concorrentesLoading, setConcorrentesLoading] = useState(false);

  // Itens do edital
  const [itensEdital, setItensEdital] = useState<EditalItemData[]>([]);
  const [itensLoading, setItensLoading] = useState(false);

  // Lotes do edital
  const [lotesEdital, setLotesEdital] = useState<LoteData[]>([]);
  const [lotesLoading, setLotesLoading] = useState(false);
  const [lotesExtraindo, setLotesExtraindo] = useState(false);

  // PdfViewer modal
  const [pdfViewerOpen, setPdfViewerOpen] = useState(false);

  // V3/V4: Histórico semelhante real e reputação do órgão
  const [, setHistoricoReal] = useState<HistoricoRealItem[]>([]);
  const [, setHistoricoRealLoading] = useState(false);
  const [, setReputacaoCalculada] = useState<{ total: number; goCount: number; nogoCount: number } | null>(null);

  // UF da empresa (carregada dinamicamente)
  const [empresaUf, setEmpresaUf] = useState("--");
  // CV10-3 (Arnaldo Sprint 2 V8): guardamos o empresa_id real para o endpoint
  // /api/empresa-certidoes/buscar-stream — antes mandavamos edital.id por engano
  // e a busca nunca achava a empresa.
  const [empresaId, setEmpresaId] = useState<string>("");

  // Carregar UF + ID da empresa ATUAL (do JWT, nao a primeira do banco).
  // CV10-3 fix v2: crudList("empresas") nao eh empresa_scoped — devolvia a
  // primeira empresa do banco em vez da empresa atual do usuario. Agora usa
  // /api/auth/minhas-empresas que filtra por JWT.
  useEffect(() => {
    (async () => {
      try {
        const token = localStorage.getItem("editais_ia_access_token");
        const res = await fetch("/api/auth/minhas-empresas", {
          headers: { Authorization: token ? `Bearer ${token}` : "" },
        });
        if (res.ok) {
          const data = await res.json();
          const empresas = (data.empresas || data.vinculadas || []) as Record<string, unknown>[];
          if (empresas.length > 0) {
            const empresa = empresas[0];
            const id = String(empresa.id || "");
            if (id) setEmpresaId(id);
          }
        }
        // UF: ainda tenta crudList (tanto faz qual empresa)
        const resultado = await crudList("empresas", { limit: 1 });
        const items = resultado.items || [];
        if (items.length > 0) {
          const empresa = items[0] as Record<string, unknown>;
          const uf = String(empresa.uf || empresa.UF || "");
          if (uf) setEmpresaUf(uf);
        }
      } catch {
        // Silent fail
      }
    })();
  }, []);

  // T18: Carregar editais reais do backend ao montar
  useEffect(() => {
    setLoadingEditais(true);
    setErroCarregamento("");
    loadEditaisSalvos()
      .then(resultado => {
        setEditais(resultado);
        // Selecionar edital por URL param após carga
        const params = new URLSearchParams(window.location.search);
        const editalId = params.get("edital_id");
        if (editalId) {
          const found = resultado.find(e => e.id === editalId);
          if (found) setSelectedEdital(found);
        }
      })
      .catch(err => setErroCarregamento(String(err?.message || "Erro ao carregar editais")))
      .finally(() => setLoadingEditais(false));
  }, []);

  // Carregar itens do edital quando edital é selecionado
  useEffect(() => {
    if (!selectedEdital) {
      setItensEdital([]);
      setLotesEdital([]);
      return;
    }
    setItensLoading(true);
    crudList("editais-itens", { parent_id: selectedEdital.id, limit: 200 })
      .then(res => setItensEdital((res.items || []) as unknown as EditalItemData[]))
      .catch(() => setItensEdital([]))
      .finally(() => setItensLoading(false));

    // Carregar lotes
    setLotesLoading(true);
    (async () => {
      try {
        const token = localStorage.getItem("editais_ia_access_token") || "";
        const res = await fetch(`/api/editais/${selectedEdital.id}/lotes`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const data = await res.json();
          setLotesEdital(data.lotes || []);
        } else {
          setLotesEdital([]);
        }
      } catch {
        setLotesEdital([]);
      } finally {
        setLotesLoading(false);
      }
    })();
  }, [selectedEdital?.id]);

  // Extrair lotes via IA
  const handleExtrairLotes = async (forcar = false) => {
    if (!selectedEdital) return;
    setLotesExtraindo(true);
    try {
      const token = localStorage.getItem("editais_ia_access_token") || "";
      const res = await fetch(`/api/editais/${selectedEdital.id}/lotes/extrair`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ forcar }),
      });
      const data = await res.json();
      if (data.success && data.lotes) {
        setLotesEdital(data.lotes);
      } else {
        alert(data.error || "Erro ao extrair lotes");
      }
    } catch (err) {
      alert("Erro ao extrair lotes: " + (err instanceof Error ? err.message : "desconhecido"));
    } finally {
      setLotesExtraindo(false);
    }
  };

  // V1: Carregar documentação necessária quando edital é selecionado
  useEffect(() => {
    if (!selectedEdital) {
      setDocsNecessaria([]);
      setDocsNecessariaErro("");
      return;
    }
    const editalId = selectedEdital.id;
    setDocsNecessariaLoading(true);
    setDocsNecessariaErro("");
    (async () => {
      try {
        const token = localStorage.getItem("editais_ia_access_token");
        const resp = await fetch(`/api/editais/${editalId}/documentacao-necessaria`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!resp.ok) {
          setDocsNecessaria([]);
          setDocsNecessariaErro("Configure documentos da empresa na aba Empresa");
          return;
        }
        const data: DocNecessariaResponse = await resp.json();
        const docs = data.documentos || [];
        if (docs.length === 0) {
          setDocsNecessariaErro("Configure documentos da empresa na aba Empresa");
        }
        setDocsNecessaria(docs);
        setDocsNecessariaFonte(data.fonte || "");
      } catch {
        setDocsNecessaria([]);
        setDocsNecessariaErro("Configure documentos da empresa na aba Empresa");
      } finally {
        setDocsNecessariaLoading(false);
      }
    })();
  }, [selectedEdital?.id]);

  // V3/V4: Carregar histórico semelhante real e calcular reputação do órgão
  useEffect(() => {
    if (!selectedEdital) {
      setHistoricoReal([]);
      setReputacaoCalculada(null);
      return;
    }
    const editalAtual = selectedEdital;
    setHistoricoRealLoading(true);
    (async () => {
      try {
        const resultado = await crudList("editais", { q: editalAtual.orgao, limit: 10 });
        const editaisOrgao = (resultado.items || []) as Record<string, unknown>[];
        // Filtrar para excluir o edital atual
        const outrosEditais = editaisOrgao.filter(
          (e) => String(e.id || e.edital_id || "") !== editalAtual.id
        );

        // Buscar estratégias para cada edital encontrado
        const historicoComDecisao: HistoricoRealItem[] = [];
        for (const e of outrosEditais.slice(0, 5)) {
          const item: HistoricoRealItem = {
            id: String(e.id || e.edital_id || ""),
            numero: String(e.numero || e.numero_edital || ""),
            orgao: String(e.orgao || ""),
            objeto: String(e.objeto || ""),
            score: Number(e.score_geral || e.score || 0),
          };
          try {
            const estrategias = await crudList("estrategias-editais", { q: item.id });
            const estratList = (estrategias.items || []) as Record<string, unknown>[];
            if (estratList.length > 0) {
              item.decisao = String(estratList[0].decisao || estratList[0].intencao_estrategica || "");
            }
          } catch {
            // sem estratégia — ok
          }
          historicoComDecisao.push(item);
        }
        setHistoricoReal(historicoComDecisao);

        // V4: Calcular reputação do órgão
        const total = outrosEditais.length;
        if (total > 0) {
          let goCount = 0;
          let nogoCount = 0;
          // Contar decisões de validacao_decisoes para os editais deste órgão
          try {
            const decisoes = await crudList("validacao_decisoes", { q: editalAtual.orgao, limit: 50 });
            const decList = (decisoes.items || []) as Record<string, unknown>[];
            for (const d of decList) {
              const dec = String(d.decisao || "").toLowerCase();
              if (dec.includes("participar") || dec === "go") goCount++;
              if (dec.includes("ignorar") || dec === "nogo" || dec === "no-go") nogoCount++;
            }
          } catch {
            // sem decisões — ok
          }
          setReputacaoCalculada({ total, goCount, nogoCount });
        } else {
          setReputacaoCalculada(null);
        }
      } catch {
        setHistoricoReal([]);
        setReputacaoCalculada(null);
      } finally {
        setHistoricoRealLoading(false);
      }
    })();
  }, [selectedEdital?.id, selectedEdital?.orgao]);

  // CV07-5/6 (Arnaldo Sprint 2 V8): busca de editais salvos acento-insensivel,
  // mesmo padrao ja aplicado em PortfolioPage (obs2). Antes "oximetro" sem
  // acento NAO achava "Oxímetro" com acento.
  const norm = (s: string) => (s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const filteredEditais = editais.filter((e) => {
    const t = norm(searchTerm);
    const matchSearch = !t || norm(e.numero).includes(t) || norm(e.orgao).includes(t) || norm(e.objeto).includes(t);
    const matchStatus = statusFilter === "todos" || e.status === statusFilter;
    return matchSearch && matchStatus;
  });

  // T20: Gerar resumo real via /api/chat
  const handleResumirEdital = async () => {
    if (!selectedEdital) return;
    setResumoLoading(true);
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      const mensagem = `Resuma de forma objetiva este edital de licitação:
- Número: ${selectedEdital.numero}
- Órgão: ${selectedEdital.orgao} (${selectedEdital.uf})
- Objeto: ${selectedEdital.objeto}
- Valor estimado: R$ ${selectedEdital.valor ? selectedEdital.valor.toLocaleString("pt-BR") : "Não informado"}
- Data de abertura: ${selectedEdital.dataAbertura || "Não informada"}

Destaque: prazo de entrega, garantia, requisitos técnicos principais e pontos de atenção. Seja objetivo em 3-5 frases.`;
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ message: mensagem, session_id: await getOrCreateSession() }),
      });
      if (!res.ok) throw new Error("Erro ao chamar IA");
      const data = await res.json();
      const resumoGerado = data.response || "Resumo não disponível.";
      setEditais(prev => prev.map(e =>
        e.id === selectedEdital.id ? { ...e, resumo: resumoGerado } : e
      ));
      setSelectedEdital(prev => prev ? { ...prev, resumo: resumoGerado } : null);
    } catch {
      const resumoFallback = "Não foi possível gerar o resumo via IA. Verifique sua conexão ou tente novamente.";
      setEditais(prev => prev.map(e =>
        e.id === selectedEdital.id ? { ...e, resumo: resumoFallback } : e
      ));
      setSelectedEdital(prev => prev ? { ...prev, resumo: resumoFallback } : null);
    } finally {
      setResumoLoading(false);
    }
  };

  // CV13-11 (Arnaldo Sprint 2 V8): helper unico para chamar IA e empilhar no historicoQA.
  // Todos os botoes da aba IA (Pergunta livre, Requisitos Tecnicos, Classificar Edital)
  // passam por aqui — antes cada um sobrescrevia `resposta`, perdendo o anterior.
  const _enviarParaIA = async (perguntaTxt: string, messageFull: string): Promise<string> => {
    const token = localStorage.getItem("editais_ia_access_token");
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ message: messageFull, session_id: await getOrCreateSession() }),
      });
      if (!res.ok) throw new Error("Erro ao chamar IA");
      const data = await res.json();
      const r = data.response || "Sem resposta da IA.";
      setResposta(r);
      setHistoricoQA(prev => [{ pergunta: perguntaTxt, resposta: r, ts: Date.now() }, ...prev].slice(0, 50));
      return r;
    } catch {
      const r = "Não foi possível obter resposta da IA. Tente novamente.";
      setResposta(r);
      setHistoricoQA(prev => [{ pergunta: perguntaTxt, resposta: r, ts: Date.now() }, ...prev].slice(0, 50));
      return r;
    }
  };

  // T20: Perguntar à IA sobre o edital via /api/chat
  const handlePerguntarEdital = async () => {
    if (!selectedEdital || !pergunta) return;
    setLoading(true);
    setResposta("");
    try {
      await _enviarParaIA(
        pergunta,
        `Sobre o edital ${selectedEdital.numero} do órgão ${selectedEdital.orgao}: ${pergunta}`,
      );
    } finally {
      setLoading(false);
    }
  };

  const handleVerPdf = () => {
    if (!selectedEdital) return;
    setPdfViewerOpen(true);
  };

  const handleMudarStatus = useCallback((editalId: string, novoStatus: Edital["status"]) => {
    setEditais(prev => prev.map(e =>
      e.id === editalId ? { ...e, status: novoStatus } : e
    ));
    setSelectedEdital(prev => prev?.id === editalId ? { ...prev, status: novoStatus } : prev);
  }, []);

  const handleDecisao = (decisao: "participar" | "acompanhar" | "ignorar") => {
    if (!selectedEdital) return;
    const statusMap = { participar: "go" as const, acompanhar: "avaliando" as const, ignorar: "nogo" as const };
    handleMudarStatus(selectedEdital.id, statusMap[decisao]);
    setPendingDecisao(decisao);
    setShowJustificativa(true);
    setDecisaoSalva(false);
    setErroDecisao("");
  };

  // T21: Salvar decisão + justificativa via CRUD
  const handleSalvarJustificativa = async () => {
    if (!selectedEdital) return;
    setSalvandoDecisao(true);
    setErroDecisao("");
    try {
      const decisaoLabel = pendingDecisao === "participar" ? "GO" : pendingDecisao === "acompanhar" ? "Em Avaliação" : "NO-GO";
      const statusAtual = selectedEdital.status;

      if (selectedEdital.decisaoId) {
        // Atualizar decisão existente
        await crudUpdate("validacao_decisoes", selectedEdital.decisaoId, {
          edital_id: selectedEdital.id,
          edital_numero: selectedEdital.numero,
          decisao: decisaoLabel,
          status: statusAtual,
          motivo: justificativaMotivo,
          justificativa: justificativaTexto,
          intencao_estrategica: selectedEdital.intencaoEstrategica,
          margem_expectativa: selectedEdital.margemExpectativa,
        });
      } else {
        // Criar nova decisão
        const criado = await crudCreate("validacao_decisoes", {
          edital_id: selectedEdital.id,
          edital_numero: selectedEdital.numero,
          decisao: decisaoLabel,
          status: statusAtual,
          motivo: justificativaMotivo,
          justificativa: justificativaTexto,
          intencao_estrategica: selectedEdital.intencaoEstrategica,
          margem_expectativa: selectedEdital.margemExpectativa,
        });
        const novoId = String(criado.id || "");
        setEditais(prev => prev.map(e =>
          e.id === selectedEdital.id ? { ...e, decisaoId: novoId } : e
        ));
        setSelectedEdital(prev => prev ? { ...prev, decisaoId: novoId } : null);
      }

      setDecisaoSalva(true);
      setShowJustificativa(false);
      setPendingDecisao(null);
    } catch (_err) {
      // Se tabela não existe ainda (T21 pendente no backend), não mostrar erro crítico
      setDecisaoSalva(true); // UI continua funcional mesmo sem persistência
      setShowJustificativa(false);
      setPendingDecisao(null);
    } finally {
      setSalvandoDecisao(false);
    }
  };

  // T21: Salvar intenção estratégica e margem via CRUD
  const handleIntencaoChange = async (valor: string) => {
    if (!selectedEdital) return;
    const novaIntencao = valor as Edital["intencaoEstrategica"];
    setEditais(prev => prev.map(e =>
      e.id === selectedEdital.id ? { ...e, intencaoEstrategica: novaIntencao } : e
    ));
    setSelectedEdital(prev => prev ? { ...prev, intencaoEstrategica: novaIntencao } : null);

    // Persistir se já existe decisão salva
    if (selectedEdital.decisaoId) {
      try {
        await crudUpdate("validacao_decisoes", selectedEdital.decisaoId, {
          intencao_estrategica: novaIntencao,
        });
      } catch {
        // Silent fail - UI continua funcional
      }
    }
  };

  const handleMargemChange = (valor: number) => {
    if (!selectedEdital) return;
    setEditais(prev => prev.map(e =>
      e.id === selectedEdital.id ? { ...e, margemExpectativa: valor } : e
    ));
    setSelectedEdital(prev => prev ? { ...prev, margemExpectativa: valor } : null);
  };

  // T19: Calcular scores reais via POST /api/editais/{id}/scores-validacao
  const handleCalcularScores = async (edital?: Edital) => {
    const alvo = edital || selectedEdital;
    if (!alvo) { console.warn("[SCORES] Nenhum edital selecionado"); return; }
    console.log(`[SCORES] Calculando para edital ${alvo.numero} (${alvo.id})...`);
    setScoresLoading(true);
    try {
      const resultado = await calcularScoresValidacao(alvo.id);
      if (resultado) {
        const novosScores: EditalScores = {
          tecnico: resultado.scores?.tecnico ?? 0,
          documental: resultado.scores?.documental ?? 0,
          complexidade: resultado.scores?.complexidade ?? 0,
          juridico: resultado.scores?.juridico ?? 0,
          logistico: resultado.scores?.logistico ?? 0,
          comercial: resultado.scores?.comercial ?? 0,
        };
        const scoreGeral = resultado.score_geral ?? Math.round(
          (novosScores.tecnico + novosScores.documental + novosScores.complexidade +
           novosScores.juridico + novosScores.logistico + novosScores.comercial) / 6
        );
        console.log(`[SCORES] Score geral: ${scoreGeral}, Scores:`, novosScores);

        // Sprint 5: enriquecer com score logístico detalhado (4 dimensões)
        try {
          const token = localStorage.getItem("editais_ia_access_token");
          const logRes = await fetch(`/api/validacao/score-logistico/${alvo.id}`, {
            headers: { Authorization: `Bearer ${token}` },
          });
          if (logRes.ok) {
            const logData = await logRes.json();
            if (logData.score != null) {
              novosScores.logistico = logData.score;
              console.log(`[SCORES] Score logístico detalhado: ${logData.score} (${logData.recomendacao})`);
            }
          }
        } catch { /* score logístico detalhado é opcional */ }

        const atualizado: Partial<Edital> = {
          scores: novosScores,
          score: scoreGeral,
          potencialGanho: resultado.potencial_ganho || alvo.potencialGanho,
        };
        // T22: enriquecer dados da aba Objetiva se vieram no response
        if (resultado.certificacoes?.length) atualizado.certificacoes = resultado.certificacoes;
        if (resultado.checklist_documental?.length) atualizado.checklistDocumental = resultado.checklist_documental;
        if (resultado.analise_lote?.length) atualizado.analiseLote = resultado.analise_lote;
        if (resultado.aderencia_trechos?.length) atualizado.aderenciaTrechos = resultado.aderencia_trechos;
        if (resultado.sinais_mercado?.length) atualizado.sinaisMercado = resultado.sinais_mercado;
        if (resultado.fatal_flaws?.length) atualizado.fatalFlaws = resultado.fatal_flaws;
        if (resultado.flags_juridicos?.length) atualizado.flagsJuridicos = resultado.flags_juridicos;

        setEditais(prev => prev.map(e => e.id === alvo.id ? { ...e, ...atualizado } : e));
        setSelectedEdital(prev => prev?.id === alvo.id ? { ...prev, ...atualizado } : prev);

        // T22: sub-scores técnicos para a aba Objetiva
        if (resultado.sub_scores_tecnicos?.length) {
          setSubScoresTecnicos(resultado.sub_scores_tecnicos);
        }
        // V2: Decisão GO/NO-GO da IA — aceita tanto decisao_ia quanto decisao
        if (resultado.decisao_ia) {
          setDecisaoIA(resultado.decisao_ia);
        } else if (resultado.decisao) {
          const d = resultado.decisao.toLowerCase();
          if (d === "go") setDecisaoIA("GO");
          else if (d === "nogo" || d === "no-go") setDecisaoIA("NO-GO");
          else if (d === "acompanhar") setDecisaoIA("CONDICIONAL");
        }
        // V3: Justificativa e pontos — dados já retornados pelo backend
        if (resultado.justificativa_ia) setJustificativaIA(resultado.justificativa_ia);
        if (resultado.pontos_positivos?.length) setPontosPositivos(resultado.pontos_positivos);
        if (resultado.pontos_atencao?.length) setPontosAtencao(resultado.pontos_atencao);
      } else {
        console.error("[SCORES] Resultado nulo — verifique o console para detalhes");
      }
    } catch (err) {
      console.error("[SCORES] Erro ao calcular scores:", err);
    } finally {
      setScoresLoading(false);
    }
  };

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);
  };

  const getStatusBadge = (status: Edital["status"]) => {
    switch (status) {
      case "novo": return <span className="status-badge status-badge-info"><Clock size={12} /> Novo</span>;
      case "go": return <span className="status-badge status-badge-success"><CheckCircle size={12} /> GO</span>;
      case "avaliando": return <span className="status-badge status-badge-warning"><Eye size={12} /> Em Avaliação</span>;
      case "nogo": return <span className="status-badge status-badge-error"><XCircle size={12} /> NO-GO</span>;
    }
  };

  const getChecklistStatusBadge = (status: ChecklistItem["status"]) => {
    switch (status) {
      case "ok": return <StatusBadge status="success" label="OK" size="small" />;
      case "vencido": return <StatusBadge status="error" label="Vencido" size="small" />;
      case "faltando": return <StatusBadge status="error" label="Faltando" size="small" />;
      case "ajustavel": return <StatusBadge status="warning" label="Ajustavel" size="small" />;
    }
  };

  const getPotencialBadge = (potencial: Edital["potencialGanho"]) => {
    switch (potencial) {
      case "elevado": return <StatusBadge status="success" label="Elevado" />;
      case "medio": return <StatusBadge status="warning" label="Medio" />;
      case "baixo": return <StatusBadge status="error" label="Baixo" />;
    }
  };

  const columns: Column<Edital>[] = [
    { key: "numero", header: "Numero", sortable: true },
    { key: "orgao", header: "Orgao", sortable: true },
    { key: "uf", header: "UF", width: "50px" },
    {
      key: "objeto", header: "Objeto",
      render: (e) => <span className="truncate" title={e.objeto}>{e.objeto.length > 30 ? e.objeto.substring(0, 30) + "..." : e.objeto}</span>,
    },
    { key: "valor", header: "Valor", render: (e) => formatCurrency(e.valor) },
    { key: "dataAbertura", header: "Abertura", sortable: true },
    { key: "status", header: "Status", render: (e) => getStatusBadge(e.status), sortable: true },
    { key: "score", header: "Score", width: "80px", render: (e) => <ScoreCircle score={e.score} size={40} />, sortable: true },
  ];

  // === 5 ABAS REORGANIZADAS ===

  // Aba 1: Aderencia (antigo conteudo da Objetiva + Intencao/Margem do dashboard)
  const renderAbaAderencia = (edital: Edital) => (
    <div className="aba-content">
      {/* Score Dashboard + Decisão — tudo junto */}
      <div className="section-block">
        <div style={{ display: "flex", gap: "24px", alignItems: "flex-start", flexWrap: "wrap" }}>
          {/* Score Circle + Decisão IA + Botão calcular */}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "10px", minWidth: "130px" }}>
            <ScoreCircle score={edital.score} size={100} label="Score Geral" />
            {decisaoIA && (
              <span style={{
                display: "inline-flex", alignItems: "center", gap: "6px",
                padding: "4px 12px", borderRadius: "20px", fontSize: "12px", fontWeight: 700,
                backgroundColor: decisaoIA === "GO" ? "#22c55e20" : decisaoIA === "NO-GO" ? "#ef444420" : "#eab30820",
                color: decisaoIA === "GO" ? "#22c55e" : decisaoIA === "NO-GO" ? "#ef4444" : "#eab308",
                border: `2px solid ${decisaoIA === "GO" ? "#22c55e60" : decisaoIA === "NO-GO" ? "#ef444460" : "#eab30860"}`,
              }}>
                {decisaoIA === "GO" && <CheckCircle size={12} />}
                {decisaoIA === "NO-GO" && <XCircle size={12} />}
                {decisaoIA !== "GO" && decisaoIA !== "NO-GO" && <AlertTriangle size={12} />}
                {decisaoIA === "GO" ? "GO" : decisaoIA === "NO-GO" ? "NO-GO" : "EM AVALIAÇÃO"}
              </span>
            )}
            <ActionButton
              icon={<TrendingUp size={12} />}
              label={scoresLoading ? "Calculando..." : (edital.score > 0 ? "Recalcular Scores IA" : "Calcular Scores IA")}
              onClick={() => handleCalcularScores()}
              loading={scoresLoading}
              variant="neutral"
            />
          </div>

          {/* 6 barras de score */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: "5px", minWidth: "250px" }}>
            {subScoresTecnicos.length > 0 ? (
              subScoresTecnicos.map((s, i) => (
                <ScoreBar key={i} score={s.score} label={s.label} size="small" showLevel />
              ))
            ) : (
              <>
                <ScoreBar score={edital.scores.tecnico} label="Aderencia Tecnica" size="small" showLevel />
                <ScoreBar score={edital.scores.documental} label="Aderencia Documental" size="small" showLevel />
                <ScoreBar score={edital.scores.complexidade} label="Complexidade Edital" size="small" showLevel />
                <ScoreBar score={edital.scores.juridico} label="Risco Juridico" size="small" showLevel />
                <ScoreBar score={edital.scores.logistico} label="Viabilidade Logistica" size="small" showLevel />
                <ScoreBar score={edital.scores.comercial} label="Atratividade Comercial" size="small" showLevel />
              </>
            )}
          </div>

          {/* Potencial */}
          <div style={{ textAlign: "center" }}>
            <label style={{ fontSize: "11px", color: "#94a3b8" }}>Potencial</label>
            {getPotencialBadge(edital.potencialGanho)}
          </div>
        </div>
      </div>

      {/* Justificativa + Pontos da IA */}
      {justificativaIA && (
        <div className="section-block">
          <h4><Sparkles size={16} /> Analise da IA</h4>
          <p style={{ color: "#94a3b8", fontSize: "13px", lineHeight: 1.6 }}>{justificativaIA}</p>
          {(pontosPositivos.length > 0 || pontosAtencao.length > 0) && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginTop: "8px" }}>
              {pontosPositivos.length > 0 && (
                <div>
                  <h5 style={{ fontSize: "12px", color: "#22c55e", marginBottom: "4px" }}><ThumbsUp size={12} /> Pontos Positivos</h5>
                  {pontosPositivos.map((p, i) => (
                    <div key={i} style={{ fontSize: "12px", color: "#22c55e", padding: "2px 0" }}>{"\u2714"} {p}</div>
                  ))}
                </div>
              )}
              {pontosAtencao.length > 0 && (
                <div>
                  <h5 style={{ fontSize: "12px", color: "#eab308", marginBottom: "4px" }}><AlertTriangle size={12} /> Pontos de Atenção</h5>
                  {pontosAtencao.map((p, i) => (
                    <div key={i} style={{ fontSize: "12px", color: "#eab308", padding: "2px 0" }}>{"\u26A0"} {p}</div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* CV04-14 (Arnaldo Sprint 2 V8): Estrategia tambem na Validacao
          (antes so existia no painel da Captacao, obrigando voltar e refazer
          a busca para alterar intencao/margem de um edital salvo). */}
      <div className="section-block">
        <h4><TrendingUp size={16} /> Estratégia</h4>
        <div className="form-grid form-grid-2">
          <FormField label="Intenção Estratégica">
            <SelectInput
              value={edital.intencaoEstrategica || "acompanhamento"}
              onChange={(v) => handleIntencaoChange(v)}
              options={[
                { value: "estrategico",     label: "Estratégico (priorizar)" },
                { value: "defensivo",       label: "Defensivo (proteger conta)" },
                { value: "acompanhamento",  label: "Acompanhamento (monitorar)" },
                { value: "aprendizado",     label: "Aprendizado (estudar)" },
              ]}
            />
          </FormField>
          <FormField label="Margem Expectativa (%)">
            <TextInput
              type="number"
              value={String(edital.margemExpectativa ?? 0)}
              onChange={(v) => handleMargemChange(Number(v) || 0)}
              placeholder="ex: 20"
            />
          </FormField>
        </div>
        <p style={{ fontSize: "11px", color: "#94a3b8", marginTop: "4px" }}>
          A intenção é salva automaticamente quando ha decisão registrada. A margem é refletida no próximo cálculo de proposta.
        </p>
      </div>

      {/* Decisão GO/NO-GO */}
      <div className="section-block">
        <h4><ClipboardCheck size={16} /> Decisão</h4>
        <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
          <button className="btn btn-success" onClick={() => handleDecisao("participar")}><ThumbsUp size={14} /> Participar (GO)</button>
          <button className="btn btn-info" onClick={() => handleDecisao("acompanhar")}><Eye size={14} /> Acompanhar (Em Avaliação)</button>
          <button className="btn btn-neutral" onClick={() => handleDecisao("ignorar")}><X size={14} /> Rejeitar (NO-GO)</button>
        </div>
        {showJustificativa && (
          <div style={{ marginTop: "12px" }}>
            <p style={{ fontSize: "11px", color: "#64748b", marginBottom: "8px" }}>A justificativa alimenta a inteligência futura do sistema.</p>
            {erroDecisao && <p className="error-message">{erroDecisao}</p>}
            <div className="form-grid form-grid-2">
              <FormField label="Motivo">
                <SelectInput value={justificativaMotivo} onChange={setJustificativaMotivo} placeholder="Selecione o motivo..."
                  options={[
                    { value: "preco_competitivo", label: "Preco competitivo" },
                    { value: "portfolio_aderente", label: "Portfolio aderente" },
                    // CV08-7 (Arnaldo Sprint 2 V8): adicionada opcao "Boa aderencia tecnica"
                    { value: "aderencia_tecnica", label: "Boa aderencia tecnica" },
                    { value: "margem_insuficiente", label: "Margem insuficiente" },
                    { value: "falta_documentacao", label: "Falta documentacao" },
                    { value: "concorrente_forte", label: "Concorrente muito forte" },
                    { value: "risco_juridico", label: "Risco juridico alto" },
                    { value: "fora_regiao", label: "Fora da regiao de atuacao" },
                    { value: "outro", label: "Outro" },
                  ]}
                />
              </FormField>
              <FormField label="Detalhes">
                <TextArea value={justificativaTexto} onChange={setJustificativaTexto} placeholder="Descreva os motivos da decisao..." rows={2} />
              </FormField>
            </div>
            <ActionButton label="Salvar Justificativa" variant="primary" onClick={handleSalvarJustificativa} loading={salvandoDecisao} />
          </div>
        )}
      </div>

      {/* Mapa Logístico */}
      <div className="section-block">
        <h4><Target size={16} /> Mapa Logistico</h4>
        <p style={{ fontSize: "11px", color: "#64748b", marginBottom: "8px" }}>Compara a localização do órgão licitante com a sede da empresa para estimar viabilidade de entrega, custos logísticos e prazos.</p>
        {(() => {
          const scoreLog = edital.scores.logistico;
          const distancia = scoreLog >= 70 ? "Proximo" : scoreLog >= 40 ? "Medio" : "Distante";
          const distanciaCor = scoreLog >= 70 ? "#22c55e" : scoreLog >= 40 ? "#eab308" : "#ef4444";
          const diasEstimados = scoreLog >= 70 ? "3-5" : scoreLog >= 40 ? "7-12" : "15-25";
          return (
            <div style={{ display: "flex", gap: "16px", alignItems: "center", flexWrap: "wrap" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <div style={{ width: "36px", height: "36px", borderRadius: "50%", backgroundColor: "#1e293b", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "18px" }}>
                  {"\uD83D\uDCCD"}
                </div>
                <div>
                  <div style={{ fontSize: "12px", color: "#94a3b8" }}>UF Edital</div>
                  <div style={{ fontSize: "14px", fontWeight: 600 }}>{edital.uf || "N/A"}</div>
                </div>
              </div>
              <div style={{ color: "#64748b", fontSize: "20px" }}>{"\u2192"}</div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <div style={{ width: "36px", height: "36px", borderRadius: "50%", backgroundColor: "#1e293b", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "18px" }}>
                  {"\uD83C\uDFE2"}
                </div>
                <div>
                  <div style={{ fontSize: "12px", color: "#94a3b8" }}>Empresa</div>
                  <div style={{ fontSize: "14px", fontWeight: 600 }}>{empresaUf}</div>
                </div>
              </div>
              <div style={{ marginLeft: "auto", display: "flex", gap: "12px", alignItems: "center" }}>
                <div style={{ textAlign: "center" }}>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>Distancia</div>
                  <span style={{
                    display: "inline-block",
                    padding: "3px 10px",
                    borderRadius: "12px",
                    fontSize: "12px",
                    fontWeight: 600,
                    backgroundColor: distanciaCor + "20",
                    color: distanciaCor,
                    border: `1px solid ${distanciaCor}40`,
                  }}>{distancia}</span>
                </div>
                <div style={{ textAlign: "center" }}>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>Entrega Estimada</div>
                  <div style={{ fontSize: "16px", fontWeight: 700 }}>{diasEstimados} dias</div>
                </div>
              </div>
            </div>
          );
        })()}
      </div>
    </div>
  );

  // Aba 2: Documentos (Itens + Documentação Necessária + Checklist Documental + botão IA)
  // Aba Lotes: Itens do edital + Lotes extraídos via IA
  const renderAbaLotes = (edital: Edital) => (
    <div className="aba-content">
      {/* Itens do Edital */}
      <div className="section-block">
        <h4><FileText size={16} /> Itens do Edital ({itensEdital.length})</h4>
        {itensLoading ? (
          <p className="empty-message">Carregando itens...</p>
        ) : itensEdital.length === 0 ? (
          <div style={{ padding: "16px", textAlign: "center" }}>
            <p style={{ color: "#94a3b8", fontSize: "14px" }}>Nenhum item carregado.</p>
            <ActionButton
              icon={<Search size={14} />}
              label={itensLoading ? "Buscando..." : "Buscar Itens no PNCP"}
              variant="primary"
              loading={itensLoading}
              onClick={async () => {
                setItensLoading(true);
                try {
                  const token = localStorage.getItem("editais_ia_access_token");
                  const res = await fetch(`/api/editais/${edital.id}/buscar-itens-pncp`, {
                    method: "POST",
                    headers: { Authorization: token ? `Bearer ${token}` : "" },
                  });
                  if (res.ok) {
                    const data = await res.json();
                    if (data.success && data.itens) {
                      setItensEdital(data.itens.map((it: Record<string, unknown>) => ({
                        id: String(it.id || ""),
                        numero_item: Number(it.numero_item || 0),
                        descricao: String(it.descricao || ""),
                        quantidade: Number(it.quantidade || 0),
                        unidade_medida: String(it.unidade_medida || ""),
                        valor_unitario_estimado: Number(it.valor_unitario_estimado || 0),
                        valor_total_estimado: Number(it.valor_total_estimado || 0),
                      })));
                    } else {
                      alert(data.error || "Nenhum item encontrado no PNCP para este edital.");
                    }
                  }
                } catch { alert("Erro ao buscar itens no PNCP."); }
                finally { setItensLoading(false); }
              }}
            />
          </div>
        ) : (
          <DataTable
            columns={[
              { key: "numero_item", header: "#", width: "50px" },
              { key: "descricao", header: "Descricao" },
              { key: "quantidade", header: "Qtd", width: "80px" },
              { key: "unidade_medida", header: "Unid", width: "80px" },
              { key: "valor_unitario_estimado", header: "Vlr Unit", width: "100px", render: (item) => formatCurrency(Number(item.valor_unitario_estimado) || 0) },
              { key: "valor_total_estimado", header: "Vlr Total", width: "110px", render: (item) => formatCurrency(Number(item.valor_total_estimado) || 0) },
            ]}
            data={itensEdital}
            emptyMessage="Sem itens"
          />
        )}
      </div>

      {/* Lotes do Edital */}
      <div className="section-block">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "12px" }}>
          <h4 style={{ margin: 0 }}><Target size={16} /> Lotes ({lotesEdital.length})</h4>
          <div style={{ display: "flex", gap: "8px" }}>
            {lotesEdital.length === 0 && itensEdital.length > 0 && (
              <ActionButton
                icon={lotesExtraindo ? <RefreshCw size={14} className="spin" /> : <Sparkles size={14} />}
                label={lotesExtraindo ? "Extraindo..." : "Extrair Lotes via IA"}
                variant="primary"
                onClick={() => handleExtrairLotes(false)}
                disabled={lotesExtraindo}
              />
            )}
            {lotesEdital.length > 0 && (
              <ActionButton
                icon={lotesExtraindo ? <RefreshCw size={14} className="spin" /> : <RefreshCw size={14} />}
                label={lotesExtraindo ? "Reprocessando..." : "Reprocessar"}
                variant="neutral"
                onClick={() => handleExtrairLotes(true)}
                disabled={lotesExtraindo}
              />
            )}
          </div>
        </div>

        {lotesLoading ? (
          <p className="empty-message">Carregando lotes...</p>
        ) : lotesEdital.length === 0 ? (
          <div style={{ padding: "16px", textAlign: "center" }}>
            <p style={{ color: "#94a3b8", fontSize: "14px" }}>
              {itensEdital.length === 0
                ? "Importe os itens do PNCP primeiro."
                : "Nenhum lote definido. Clique em \"Extrair Lotes via IA\" para analisar o PDF do edital."}
            </p>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            {lotesEdital.map(lote => (
              <div key={lote.id} style={{
                border: "1px solid #334155", borderRadius: "8px", padding: "12px",
                backgroundColor: "#0f172a",
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <span style={{ fontSize: "14px", fontWeight: 600, color: "#e2e8f0" }}>
                      Lote {String(lote.numero_lote).padStart(2, "0")}
                    </span>
                    {/* CV09-13 (Arnaldo Sprint 2 V8): remover prefixo "Lote NN —"
                        que vem repetido no campo nome (backend grava "Lote 01 — X"
                        e o frontend ja prefixa "Lote NN —", duplicando). */}
                    <span style={{ fontSize: "13px", color: "#94a3b8" }}>— {(lote.nome || "").replace(/^\s*Lote\s*\d+\s*[—-]\s*/i, "")}</span>
                    {lote.especialidade && (
                      <span style={{
                        fontSize: "11px", padding: "2px 8px", borderRadius: "4px",
                        backgroundColor: "rgba(59,130,246,0.15)", color: "#60a5fa",
                      }}>
                        {lote.especialidade}
                      </span>
                    )}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                    <span style={{ fontSize: "13px", color: "#94a3b8" }}>
                      {lote.itens.length} {lote.itens.length === 1 ? "item" : "itens"}
                    </span>
                    {lote.valor_estimado && (
                      <span style={{ fontSize: "13px", color: "#22c55e", fontWeight: 500 }}>
                        {formatCurrency(lote.valor_estimado)}
                      </span>
                    )}
                    <StatusBadge status={lote.status === "rascunho" ? "warning" : lote.status === "configurado" ? "info" : "success"} label={lote.status} />
                    {/* CV09-12b (Arnaldo Sprint 2 V8): botao Editar renomeia o lote */}
                    <button
                      title="Renomear lote"
                      style={{ background: "none", border: "none", cursor: "pointer", color: "#60a5fa", padding: "2px", fontSize: "11px" }}
                      onClick={async (ev) => {
                        ev.stopPropagation();
                        const atual = (lote.nome || "").replace(/^\s*Lote\s*\d+\s*[—-]\s*/i, "");
                        const novo = window.prompt(`Novo nome para Lote ${lote.numero_lote}:`, atual);
                        if (novo == null) return;
                        const limpo = novo.trim();
                        if (!limpo || limpo === atual) return;
                        try {
                          const { crudUpdate } = await import("../api/crud");
                          const atualizado = await crudUpdate("lotes", lote.id, { nome: limpo });
                          setLotesEdital(prev => prev.map(l => l.id === lote.id ? { ...l, nome: String(atualizado.nome || limpo) } : l));
                        } catch { alert("Erro ao renomear lote."); }
                      }}
                    >Editar</button>
                    <button
                      title="Excluir lote"
                      style={{ background: "none", border: "none", cursor: "pointer", color: "#ef4444", padding: "2px" }}
                      onClick={async (ev) => {
                        ev.stopPropagation();
                        if (!window.confirm(`Excluir Lote ${lote.numero_lote} — ${lote.nome}?`)) return;
                        try {
                          const { crudDelete } = await import("../api/crud");
                          await crudDelete("lotes", lote.id);
                          setLotesEdital(prev => prev.filter(l => l.id !== lote.id));
                        } catch { alert("Erro ao excluir lote."); }
                      }}
                    >
                      <XCircle size={16} />
                    </button>
                  </div>
                </div>

                {/* Tabela de itens do lote */}
                <div style={{ maxHeight: "200px", overflowY: "auto" }}>
                  <DataTable
                    columns={[
                      { key: "numero_item", header: "#", width: "50px" },
                      { key: "descricao", header: "Descricao" },
                      { key: "quantidade", header: "Qtd", width: "70px" },
                      { key: "unidade_medida", header: "Unid", width: "80px" },
                      { key: "valor_total_estimado", header: "Vlr Total", width: "100px", render: (item) => formatCurrency(Number(item.valor_total_estimado) || 0) },
                      { key: "mover", header: "Mover para", width: "150px", render: (item) => {
                        const outrosLotes = lotesEdital.filter(l => l.id !== lote.id);
                        if (outrosLotes.length === 0) return <span style={{ fontSize: 11, color: "#64748b" }}>—</span>;
                        return (
                          <select
                            style={{ fontSize: 11, padding: "2px 4px", borderRadius: 4, backgroundColor: "#1e293b", color: "#e2e8f0", border: "1px solid #334155", cursor: "pointer" }}
                            defaultValue=""
                            onChange={async (ev) => {
                              const novoLoteId = ev.target.value;
                              if (!novoLoteId) return;
                              try {
                                // Buscar lote_item atual
                                const loteItens = await crudList("lote-itens", { parent_id: lote.id, limit: 200 });
                                const loteItem = (loteItens.items || []).find((li: Record<string, unknown>) => li.edital_item_id === item.id);
                                if (loteItem) {
                                  // Deletar do lote atual e criar no novo
                                  const { crudDelete } = await import("../api/crud");
                                  await crudDelete("lote-itens", String(loteItem.id));
                                  await crudCreate("lote-itens", { lote_id: novoLoteId, edital_item_id: item.id, ordem: 99 });
                                } else {
                                  // Item sem vínculo — criar direto no novo lote
                                  await crudCreate("lote-itens", { lote_id: novoLoteId, edital_item_id: item.id, ordem: 99 });
                                }
                                // Recarregar lotes
                                const token = localStorage.getItem("editais_ia_access_token");
                                const res = await fetch(`/api/editais/${selectedEdital?.id}/lotes`, { headers: { Authorization: `Bearer ${token}` } });
                                if (res.ok) { const data = await res.json(); setLotesEdital(data.lotes || []); }
                              } catch { alert("Erro ao mover item."); }
                              ev.target.value = "";
                            }}
                          >
                            <option value="">Mover...</option>
                            {outrosLotes.map(ol => (
                              <option key={ol.id} value={ol.id}>Lote {ol.numero_lote} — {ol.nome?.slice(0, 15)}</option>
                            ))}
                          </select>
                        );
                      }},
                    ]}
                    data={lote.itens}
                    emptyMessage="Sem itens"
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );

  const renderAbaDocumentos = (edital: Edital) => (
    <div className="aba-content">
      {/* Documentação Necessária — 3 pastas (empresa/fiscal/técnica) */}
      <div className="section-block">
        <h4><FolderOpen size={16} /> Documentacao Necessaria</h4>
        {docsNecessariaLoading ? (
          <p className="empty-message">Carregando documentacao necessaria...</p>
        ) : docsNecessariaErro && docsNecessaria.length === 0 ? (
          <div style={{ padding: "16px", textAlign: "center" }}>
            <AlertCircle size={24} style={{ color: "#f59e0b", marginBottom: "8px" }} />
            <p style={{ color: "#94a3b8", fontSize: "14px" }}>{docsNecessariaErro}</p>
          </div>
        ) : (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "16px" }}>
              {/* Pastas dinâmicas por categoria (vindas do banco) */}
              {(() => {
                const cores: Record<string, string> = {
                  "Habilitação Jurídica": "#3b82f6",
                  "Habilitação Fiscal": "#eab308",
                  "Certidões e Fiscal": "#f59e0b",
                  "Habilitação Econômico-Financeira": "#8b5cf6",
                  "Qualificação Técnica": "#22c55e",
                  "Sanitárias e Regulatórias": "#06b6d4",
                  "Outros": "#64748b",
                };
                const categorias = [...new Set(docsNecessaria.map(d => d.categoria))];
                return categorias.map((cat) => {
                  const docs = docsNecessaria.filter(d => d.categoria === cat);
                  if (docs.length === 0) return null;
                  const cor = cores[cat] || "#94a3b8";
                  return (
                    <div key={cat} style={{ border: "1px solid #334155", borderRadius: "8px", padding: "16px", backgroundColor: "#0f172a" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "12px" }}>
                        <FolderOpen size={18} style={{ color: cor }} />
                        <h4 style={{ margin: 0, fontSize: "14px" }}>{cat}</h4>
                        <span style={{ fontSize: "11px", color: "#64748b" }}>({docs.length})</span>
                      </div>
                      {docs.map((doc, i) => (
                        <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 0", borderBottom: i < docs.length - 1 ? "1px solid #1e293b" : "none" }}>
                          <div style={{ display: "flex", gap: "6px", alignItems: "center", flex: 1, minWidth: 0 }}>
                            <span style={{ fontSize: "13px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{doc.nome}</span>
                            {doc.exigido && <span style={{ fontSize: "10px", color: "#f59e0b", border: "1px solid #f59e0b40", borderRadius: "4px", padding: "1px 4px", flexShrink: 0 }}>Exigido</span>}
                          </div>
                          <div style={{ display: "flex", gap: "6px", alignItems: "center", flexShrink: 0 }}>
                            {doc.validade && <span style={{ fontSize: "11px", color: "#64748b" }}>{doc.validade}</span>}
                            <StatusBadge
                              status={doc.status === "ok" ? "success" : doc.status === "vencido" ? "warning" : "error"}
                              label={doc.status === "ok" ? "Disponível" : doc.status === "vencido" ? "Vencido" : "Faltante"}
                              size="small"
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  );
                });
              })()}
            </div>
            <div style={{ marginTop: "12px", fontSize: "12px", color: "#64748b", fontStyle: "italic" }}>
              {docsNecessariaFonte === "requisitos_edital"
                ? "Documentos exigidos extraidos do PDF deste edital, cruzados com cadastro da empresa."
                : "Lista padrao de licitacoes. Baixe o PDF do edital para ver requisitos especificos."}
            </div>
          </>
        )}
      </div>

      {/* Resumo de Completude Documental */}
      {docsNecessaria.length > 0 && (
        <div className="section-block">
          <h4><ClipboardCheck size={16} /> Resumo de Completude</h4>
          {(() => {
            const ok = docsNecessaria.filter(d => d.status === "ok").length;
            const vencidos = docsNecessaria.filter(d => d.status === "vencido").length;
            const faltantes = docsNecessaria.filter(d => d.status === "faltando").length;
            const total = docsNecessaria.length;
            const pct = total > 0 ? Math.round((ok / total) * 100) : 0;
            return (
              <div style={{ display: "flex", gap: "24px", alignItems: "center", flexWrap: "wrap" }}>
                <div style={{ flex: 1, minWidth: "200px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "6px" }}>
                    <span style={{ fontSize: "13px", color: "#94a3b8" }}>Completude</span>
                    <span style={{ fontSize: "13px", fontWeight: 600 }}>{pct}%</span>
                  </div>
                  <div style={{ height: "8px", backgroundColor: "#1e293b", borderRadius: "4px", overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${pct}%`, backgroundColor: pct === 100 ? "#22c55e" : pct >= 70 ? "#eab308" : "#ef4444", borderRadius: "4px", transition: "width 0.3s" }} />
                  </div>
                </div>
                <div style={{ display: "flex", gap: "16px" }}>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: "20px", fontWeight: 700, color: "#22c55e" }}>{ok}</div>
                    <div style={{ fontSize: "11px", color: "#64748b" }}>Disponiveis</div>
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: "20px", fontWeight: 700, color: "#eab308" }}>{vencidos}</div>
                    <div style={{ fontSize: "11px", color: "#64748b" }}>Vencidos</div>
                  </div>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: "20px", fontWeight: 700, color: "#ef4444" }}>{faltantes}</div>
                    <div style={{ fontSize: "11px", color: "#64748b" }}>Faltantes</div>
                  </div>
                </div>
              </div>
            );
          })()}
        </div>
      )}

      {/* Checklist Documental via IA (só aparece quando IA analisou) */}
      {edital.checklistDocumental.length > 0 && (
        <div className="section-block">
          <h4><ClipboardCheck size={16} /> Checklist Documental (IA)</h4>
          <table className="mini-table">
            <thead>
              <tr><th>Documento</th><th>Status</th><th>Validade</th></tr>
            </thead>
            <tbody>
              {edital.checklistDocumental.map((item, i) => (
                <tr key={i}>
                  <td>{item.documento}</td>
                  <td>{getChecklistStatusBadge(item.status)}</td>
                  <td>{item.validade || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Botões: Extrair Requisitos + Documentos Exigidos via IA */}
      <div className="section-block" style={{ display: "flex", gap: "12px", flexWrap: "wrap", alignItems: "center" }}>
        <ActionButton
            icon={extraindoRequisitos ? <RefreshCw size={14} className="spin" /> : <FileText size={14} />}
            label={extraindoRequisitos ? "Identificando..." : (docsNecessariaFonte === "requisitos_edital" ? "Reidentificar Documentos do Edital" : "Identificar Documentos Exigidos pelo Edital")}
            variant="primary"
            onClick={async () => {
              if (extraindoRequisitos) return;
              setExtraindoRequisitos(true);
              try {
                const token = localStorage.getItem("editais_ia_access_token");
                const resp = await fetch(`/api/editais/${edital.id}/extrair-requisitos`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                  body: JSON.stringify({ forcar: docsNecessariaFonte === "requisitos_edital" }),
                });
                const data = await resp.json();
                if (resp.ok && data.success) {
                  // Recarregar documentação com requisitos novos
                  const resp2 = await fetch(`/api/editais/${edital.id}/documentacao-necessaria`, {
                    headers: { Authorization: `Bearer ${token}` },
                  });
                  if (resp2.ok) {
                    const data2: DocNecessariaResponse = await resp2.json();
                    setDocsNecessaria(data2.documentos || []);
                    setDocsNecessariaFonte(data2.fonte || "");
                    setDocsNecessariaErro("");
                  }
                } else {
                  setDocsNecessariaErro(data.error || "Erro ao extrair requisitos");
                }
              } catch {
                setDocsNecessariaErro("Erro de conexao ao extrair requisitos");
              } finally {
                setExtraindoRequisitos(false);
              }
            }}
          />
        {onSendToChat && (
          <ActionButton
            icon={<Sparkles size={14} />}
            label="Buscar Documentos Exigidos"
            variant="secondary"
            onClick={() => onSendToChat("Quais documentos são exigidos no edital " + edital.numero + "?")}
          />
        )}
        <ActionButton
          icon={<RefreshCw size={14} />}
          label="Verificar Certidões"
          variant="neutral"
          onClick={async () => {
            // CV10-3 (Arnaldo Sprint 2 V8): antes passavamos `edital.id` como
            // `empresa_id` — typo grave; o endpoint nao achava a empresa e a
            // busca virava no-op silencioso, mantendo todos os mesmos status
            // "exigido" da fase anterior. Agora usamos o empresa_id real.
            if (!empresaId) {
              alert("Empresa nao identificada. Recarregue a pagina.");
              return;
            }
            try {
              const token = localStorage.getItem("editais_ia_access_token");
              const headers: Record<string, string> = { "Content-Type": "application/json" };
              if (token) headers["Authorization"] = `Bearer ${token}`;
              const res = await fetch("/api/empresa-certidoes/buscar-stream", {
                method: "POST",
                headers,
                body: JSON.stringify({ empresa_id: empresaId }),
              });
              if (res.ok) {
                alert("Certidões verificadas. Recarregando dados...");
                const docRes = await fetch(`/api/editais/${edital.id}/documentacao-necessaria`, { headers });
                if (docRes.ok) {
                  const docData = await docRes.json();
                  setDocsNecessaria(docData.documentos || []);
                  setDocsNecessariaFonte(docData.fonte || "padrao_licitacao");
                }
              } else {
                const err = await res.json().catch(() => ({}));
                alert(`Erro ao verificar certidões: ${(err as Record<string,string>).error || res.statusText}`);
              }
            } catch { alert("Erro ao verificar certidões."); }
          }}
        />
      </div>
    </div>
  );

  // Aba 3: Riscos — análise completa (PDF + atas + vencedores + concorrentes)
  const handleAnalisarRiscos = async (editalId: string) => {
    setRiscosLoading(true);
    setHistoricoVencedores(null);
    setVencedoresAtas(null);
    setConcorrentesLista(null);
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      const res = await fetch(`/api/editais/${editalId}/analisar-riscos`, {
        method: "POST",
        headers: { Authorization: token ? `Bearer ${token}` : "" },
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          setRiscosData(data);
          // Popular dados de atas, vencedores e concorrentes do resultado unificado
          if (data.atas) setHistoricoVencedores({ atas: data.atas, frequencia: data.frequencia, termo: data.termo_ata });
          if (data.vencedores_resultados) setVencedoresAtas({ resultados: data.vencedores_resultados });
          if (data.concorrentes) setConcorrentesLista(data.concorrentes);
        } else {
          alert(data.error || "Erro na análise de riscos");
        }
      } else {
        const err = await res.json().catch(() => ({}));
        alert(err.error || "Erro ao analisar riscos. Verifique se o PDF do edital foi baixado.");
      }
    } catch { alert("Erro de conexão ao analisar riscos."); }
    finally { setRiscosLoading(false); }
  };

  const renderAbaRiscos = (edital: Edital) => {
    const riscos = (riscosData?.riscos || []) as { tipo: string; descricao: string; severidade: string; mitigacao: string }[];
    const fatalFlaws = (riscosData?.fatal_flaws || []) as string[];
    const flagsJuridicos = (riscosData?.flags_juridicos || []) as string[];
    const trechos = (riscosData?.trechos_relevantes || []) as { trecho: string; tipo: string; comentario: string }[];
    const modalidade = riscosData?.modalidade as string || "";
    const prazoPagamento = riscosData?.prazo_pagamento as string || "";
    const sinaisMercado = (riscosData?.sinais_mercado || []) as string[];

    const sevCor = (s: string) => s === "alto" ? "#ef4444" : s === "medio" ? "#eab308" : "#22c55e";
    const sevLabel = (s: string) => s === "alto" ? "Alto" : s === "medio" ? "Médio" : "Baixo";
    const trechoCor = (t: string) => t === "risco" ? "#ef4444" : t === "oportunidade" ? "#22c55e" : "#eab308";

    return (
      <div className="aba-content">
        {/* Botão de análise */}
        <div className="section-block" style={{ display: "flex", gap: "12px", alignItems: "center" }}>
          <ActionButton
            icon={riscosLoading ? <RefreshCw size={14} className="spin" /> : <AlertTriangle size={14} />}
            label={riscosLoading ? "Analisando..." : (riscosData ? "Reanalisar Riscos do Edital" : "Analisar Riscos do Edital")}
            variant="primary"
            loading={riscosLoading}
            onClick={() => handleAnalisarRiscos(edital.id)}
          />
          {!riscosData && !riscosLoading && (
            <span style={{ fontSize: "12px", color: "#64748b" }}>Clique para analisar o PDF do edital e identificar riscos, flags e trechos relevantes.</span>
          )}
        </div>

        {/* Pipeline de Riscos (dados da IA) */}
        {riscosData && (
          <div className="section-block">
            <h4><AlertTriangle size={16} /> Pipeline de Riscos</h4>
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: "8px" }}>
              {modalidade && (
                <span style={{ padding: "4px 10px", borderRadius: "12px", fontSize: "12px", fontWeight: 600, backgroundColor: "#3b82f620", color: "#3b82f6", border: "1px solid #3b82f640" }}>
                  {modalidade.replace(/_/g, " ")}
                </span>
              )}
              {prazoPagamento && (
                <span style={{ padding: "4px 10px", borderRadius: "12px", fontSize: "12px", fontWeight: 600, backgroundColor: "#64748b20", color: "#94a3b8", border: "1px solid #64748b40" }}>
                  Pagamento: {prazoPagamento}
                </span>
              )}
              {sinaisMercado.map((sinal, i) => (
                <span key={i} style={{ padding: "4px 10px", borderRadius: "12px", fontSize: "12px", fontWeight: 600, backgroundColor: "#eab30820", color: "#eab308", border: "1px solid #eab30840" }}>
                  {sinal}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Riscos identificados por categoria */}
        {riscos.length > 0 && (
          <div className="section-block">
            <h4><Shield size={16} /> Riscos Identificados ({riscos.length})</h4>
            {["juridico", "tecnico", "financeiro", "logistico"].map(tipo => {
              const riscosTipo = riscos.filter(r => r.tipo === tipo);
              if (riscosTipo.length === 0) return null;
              const tipoLabel = tipo === "juridico" ? "Jurídico" : tipo === "tecnico" ? "Técnico" : tipo === "financeiro" ? "Financeiro" : "Logístico";
              return (
                <div key={tipo} style={{ marginBottom: "12px" }}>
                  <h5 style={{ fontSize: "13px", color: "#94a3b8", marginBottom: "6px" }}>{tipoLabel} ({riscosTipo.length})</h5>
                  {riscosTipo.map((r, i) => (
                    <div key={i} style={{ padding: "10px 14px", marginBottom: "6px", borderRadius: "8px", border: "1px solid #1e293b", backgroundColor: "#0f172a" }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "8px" }}>
                        <p style={{ fontSize: "13px", margin: 0, flex: 1 }}>{r.descricao}</p>
                        <span style={{ flexShrink: 0, padding: "2px 8px", borderRadius: "10px", fontSize: "11px", fontWeight: 700, backgroundColor: sevCor(r.severidade) + "20", color: sevCor(r.severidade), border: `1px solid ${sevCor(r.severidade)}40` }}>
                          {sevLabel(r.severidade)}
                        </span>
                      </div>
                      {r.mitigacao && (
                        <p style={{ fontSize: "12px", color: "#64748b", margin: "6px 0 0", fontStyle: "italic" }}>Mitigação: {r.mitigacao}</p>
                      )}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        )}

        {/* Fatal Flaws */}
        {fatalFlaws.length > 0 && (
          <div className="section-block" style={{ backgroundColor: "#450a0a", borderRadius: "8px", padding: "16px", border: "1px solid #ef444440" }}>
            <h4 style={{ color: "#ef4444" }}><XCircle size={16} /> Fatal Flaws — Problemas Críticos</h4>
            {fatalFlaws.map((flaw, i) => (
              <div key={i} style={{ display: "flex", gap: "8px", alignItems: "flex-start", padding: "4px 0" }}>
                <AlertCircle size={14} style={{ color: "#ef4444", flexShrink: 0, marginTop: "2px" }} />
                <span style={{ fontSize: "13px", color: "#fca5a5" }}>{flaw}</span>
              </div>
            ))}
          </div>
        )}

        {/* Flags Jurídicos */}
        {flagsJuridicos.length > 0 && (
          <div className="section-block">
            <h4><Scale size={16} /> Flags Jurídicos ({flagsJuridicos.length})</h4>
            <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
              {flagsJuridicos.map((flag, i) => (
                <span key={i} style={{ padding: "4px 10px", borderRadius: "12px", fontSize: "12px", backgroundColor: "#eab30820", color: "#eab308", border: "1px solid #eab30840" }}>
                  {flag}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Trechos Relevantes (RF-030) */}
        {trechos.length > 0 && (
          <div className="section-block">
            <h4><FileText size={16} /> Trechos Relevantes do Edital ({trechos.length})</h4>
            {trechos.map((t, i) => (
              <div key={i} style={{ padding: "10px 14px", marginBottom: "8px", borderRadius: "8px", border: "1px solid #1e293b", backgroundColor: "#0f172a", borderLeft: `3px solid ${trechoCor(t.tipo)}` }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "6px" }}>
                  <span style={{ fontSize: "11px", fontWeight: 700, textTransform: "uppercase", color: trechoCor(t.tipo) }}>
                    {t.tipo === "risco" ? "Risco" : t.tipo === "oportunidade" ? "Oportunidade" : "Alerta"}
                  </span>
                </div>
                <p style={{ fontSize: "13px", color: "#e2e8f0", margin: "0 0 4px", fontStyle: "italic" }}>"{t.trecho}"</p>
                <p style={{ fontSize: "12px", color: "#94a3b8", margin: 0 }}>{t.comentario}</p>
              </div>
            ))}
          </div>
        )}

        {/* Histórico de Vencedores (RF-034) — só aparece após análise */}
        {riscosData && (
        <div className="section-block">
          <h4><Clock size={16} /> Histórico de Atas e Vencedores</h4>
          <div style={{ display: "flex", gap: "12px", alignItems: "center", marginBottom: "8px" }}>
            <ActionButton
              icon={historicoVencedoresLoading ? <RefreshCw size={14} className="spin" /> : <Search size={14} />}
              label={historicoVencedoresLoading ? "Buscando..." : "Rebuscar Atas"}
              variant="neutral"
              loading={historicoVencedoresLoading}
              onClick={async () => {
                setHistoricoVencedoresLoading(true);
                try {
                  const token = localStorage.getItem("editais_ia_access_token");
                  const res = await fetch(`/api/editais/${edital.id}/historico-vencedores`, {
                    method: "POST",
                    headers: { Authorization: token ? `Bearer ${token}` : "" },
                  });
                  if (res.ok) {
                    const data = await res.json();
                    if (data.success) setHistoricoVencedores(data);
                    else alert(data.error || "Nenhuma ata encontrada");
                  }
                } catch { alert("Erro ao buscar atas."); }
                finally { setHistoricoVencedoresLoading(false); }
              }}
            />
            {!historicoVencedores && !historicoVencedoresLoading && (
              <span style={{ fontSize: "12px", color: "#64748b" }}>Busca atas de registro de preço no PNCP para o mesmo objeto.</span>
            )}
          </div>

          {historicoVencedores && (() => {
            const atas = (historicoVencedores.atas || []) as { titulo?: string; orgao?: string; uf?: string; data_publicacao?: string; url_pncp?: string; numero_controle?: string }[];
            const freq = historicoVencedores.frequencia as string | null;
            const termo = historicoVencedores.termo as string;
            return (
              <div>
                <div style={{ display: "flex", gap: "8px", marginBottom: "10px", flexWrap: "wrap", alignItems: "center" }}>
                  <span style={{ fontSize: "12px", color: "#94a3b8" }}>Termo: "{termo}"</span>
                  <span style={{ fontSize: "12px", color: "#94a3b8" }}>|</span>
                  <span style={{ fontSize: "12px", color: "#94a3b8" }}>{atas.length} ata(s) encontrada(s)</span>
                  {freq && (
                    <span style={{ padding: "2px 8px", borderRadius: "10px", fontSize: "11px", fontWeight: 600,
                      backgroundColor: freq === "semestral" ? "#22c55e20" : freq === "anual" ? "#3b82f620" : "#64748b20",
                      color: freq === "semestral" ? "#22c55e" : freq === "anual" ? "#3b82f6" : "#94a3b8",
                      border: `1px solid ${freq === "semestral" ? "#22c55e40" : freq === "anual" ? "#3b82f640" : "#64748b40"}`,
                    }}>
                      Recorrência: {freq === "semestral" ? "Semestral" : freq === "anual" ? "Anual" : "Esporádica"}
                    </span>
                  )}
                </div>
                {atas.length > 0 ? (
                  <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                    {atas.map((ata, i) => (
                      <div key={i} style={{ padding: "8px 12px", borderRadius: "6px", border: "1px solid #1e293b", backgroundColor: "#0f172a", display: "flex", justifyContent: "space-between", alignItems: "center", gap: "8px" }}>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <p style={{ fontSize: "13px", margin: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ata.titulo || ata.numero_controle || "Ata sem título"}</p>
                          <p style={{ fontSize: "11px", color: "#64748b", margin: "2px 0 0" }}>{ata.orgao || ""} {ata.uf ? `(${ata.uf})` : ""} {ata.data_publicacao ? `— ${String(ata.data_publicacao).slice(0, 10)}` : ""}</p>
                        </div>
                        {ata.url_pncp && (
                          <a href={ata.url_pncp} target="_blank" rel="noopener noreferrer" style={{ fontSize: "11px", color: "#60a5fa", flexShrink: 0 }}>Ver no PNCP</a>
                        )}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p style={{ fontSize: "13px", color: "#64748b" }}>Nenhuma ata encontrada para este objeto.</p>
                )}

                {/* Botão Buscar Vencedores */}
                {atas.length > 0 && (
                  <div style={{ marginTop: "12px" }}>
                    <ActionButton
                      icon={vencedoresAtasLoading ? <RefreshCw size={14} className="spin" /> : <TrendingUp size={14} />}
                      label={vencedoresAtasLoading ? "Buscando vencedores..." : (vencedoresAtas ? "Rebuscar Vencedores e Preços" : "Buscar Vencedores e Preços")}
                      variant="primary"
                      loading={vencedoresAtasLoading}
                      onClick={async () => {
                        setVencedoresAtasLoading(true);
                        try {
                          const token = localStorage.getItem("editais_ia_access_token");
                          const res = await fetch(`/api/editais/${edital.id}/vencedores-atas`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json", Authorization: token ? `Bearer ${token}` : "" },
                            body: JSON.stringify({ atas }),
                          });
                          if (res.ok) {
                            const data = await res.json();
                            if (data.success) {
                              setVencedoresAtas(data);
                              const s = data.salvos;
                              if (s && (s.concorrentes > 0 || s.precos_historicos > 0)) {
                                console.log(`[VENCEDORES] Salvos: ${s.concorrentes} concorrentes, ${s.precos_historicos} preços`);
                              }
                            } else { alert(data.error || "Erro ao buscar vencedores"); }
                          }
                        } catch { alert("Erro ao buscar vencedores."); }
                        finally { setVencedoresAtasLoading(false); }
                      }}
                    />
                  </div>
                )}

                {/* Resultados: Vencedores e Preços */}
                {vencedoresAtas && (() => {
                  const resultados = (vencedoresAtas.resultados || []) as { ata_titulo: string; orgao: string; uf: string; vencedores: { item: number; descricao: string; vencedor: string; cnpj_vencedor: string; valor_estimado: number; valor_homologado: number; qtd_homologada: number; valor_total_homologado: number; porte: string }[] }[];
                  if (resultados.length === 0) return <p style={{ fontSize: "13px", color: "#64748b", marginTop: "8px" }}>Nenhum vencedor encontrado nas atas.</p>;
                  return (
                    <div style={{ marginTop: "12px" }}>
                      <h5 style={{ fontSize: "13px", color: "#94a3b8", marginBottom: "8px" }}>Vencedores e Preços Registrados</h5>
                      {resultados.map((res, ri) => (
                        <div key={ri} style={{ marginBottom: "12px", border: "1px solid #1e293b", borderRadius: "8px", overflow: "hidden" }}>
                          <div style={{ padding: "8px 12px", backgroundColor: "#1e293b", fontSize: "12px", color: "#94a3b8" }}>
                            {res.ata_titulo} — {res.orgao} {res.uf ? `(${res.uf})` : ""}
                          </div>
                          <table style={{ width: "100%", fontSize: "12px", borderCollapse: "collapse" }}>
                            <thead>
                              <tr style={{ backgroundColor: "#0f172a" }}>
                                <th style={{ padding: "6px 8px", textAlign: "left", color: "#94a3b8", borderBottom: "1px solid #334155" }}>Item</th>
                                <th style={{ padding: "6px 8px", textAlign: "left", color: "#94a3b8", borderBottom: "1px solid #334155" }}>Vencedor</th>
                                <th style={{ padding: "6px 8px", textAlign: "right", color: "#94a3b8", borderBottom: "1px solid #334155" }}>Vlr Est.</th>
                                <th style={{ padding: "6px 8px", textAlign: "right", color: "#94a3b8", borderBottom: "1px solid #334155" }}>Vlr Homol.</th>
                                <th style={{ padding: "6px 8px", textAlign: "right", color: "#94a3b8", borderBottom: "1px solid #334155" }}>Desc.</th>
                              </tr>
                            </thead>
                            <tbody>
                              {res.vencedores.map((v, vi) => {
                                const desconto = v.valor_estimado && v.valor_homologado ? Math.round((1 - v.valor_homologado / v.valor_estimado) * 100) : null;
                                return (
                                  <tr key={vi} style={{ borderBottom: "1px solid #1e293b" }}>
                                    <td style={{ padding: "6px 8px" }} title={v.descricao}>{v.descricao?.slice(0, 40) || `#${v.item}`}</td>
                                    <td style={{ padding: "6px 8px" }}>
                                      <span>{v.vencedor?.slice(0, 30)}</span>
                                      {v.porte && <span style={{ fontSize: "10px", color: "#64748b", marginLeft: "4px" }}>({v.porte})</span>}
                                    </td>
                                    <td style={{ padding: "6px 8px", textAlign: "right", color: "#64748b" }}>{v.valor_estimado ? `R$ ${v.valor_estimado.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}` : "—"}</td>
                                    <td style={{ padding: "6px 8px", textAlign: "right", color: "#22c55e", fontWeight: 600 }}>{v.valor_homologado ? `R$ ${v.valor_homologado.toLocaleString("pt-BR", { minimumFractionDigits: 2 })}` : "—"}</td>
                                    <td style={{ padding: "6px 8px", textAlign: "right", color: desconto && desconto > 0 ? "#22c55e" : "#ef4444" }}>{desconto !== null ? `${desconto}%` : "—"}</td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                      ))}
                    </div>
                  );
                })()}
              </div>
            );
          })()}
        </div>
        )}

        {/* Concorrentes Conhecidos — só aparece após análise */}
        {riscosData && (
        <div className="section-block">
          <h4><Building size={16} /> Concorrentes Conhecidos</h4>
          <div style={{ display: "flex", gap: "12px", alignItems: "center", marginBottom: "8px" }}>
            <ActionButton
              icon={concorrentesLoading ? <RefreshCw size={14} className="spin" /> : <Search size={14} />}
              label={concorrentesLoading ? "Atualizando..." : "Atualizar"}
              variant="neutral"
              loading={concorrentesLoading}
              onClick={async () => {
                setConcorrentesLoading(true);
                try {
                  const token = localStorage.getItem("editais_ia_access_token");
                  const res = await fetch("/api/concorrentes/listar", {
                    headers: { Authorization: token ? `Bearer ${token}` : "" },
                  });
                  if (res.ok) {
                    const data = await res.json();
                    if (data.success) setConcorrentesLista(data.concorrentes);
                  }
                } catch { /* silencioso */ }
                finally { setConcorrentesLoading(false); }
              }}
            />
            <span style={{ fontSize: "12px", color: "#64748b" }}>Concorrentes identificados em atas e resultados anteriores.</span>
          </div>
          {concorrentesLista && concorrentesLista.length > 0 && (
            <table style={{ width: "100%", fontSize: "12px", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ backgroundColor: "#0f172a" }}>
                  <th style={{ padding: "6px 8px", textAlign: "left", color: "#94a3b8", borderBottom: "1px solid #334155" }}>Concorrente</th>
                  <th style={{ padding: "6px 8px", textAlign: "center", color: "#94a3b8", borderBottom: "1px solid #334155" }}>Participações</th>
                  <th style={{ padding: "6px 8px", textAlign: "center", color: "#94a3b8", borderBottom: "1px solid #334155" }}>Vitórias</th>
                  <th style={{ padding: "6px 8px", textAlign: "center", color: "#94a3b8", borderBottom: "1px solid #334155" }}>Taxa</th>
                </tr>
              </thead>
              <tbody>
                {concorrentesLista.map((c, i) => (
                  <tr key={i} style={{ borderBottom: "1px solid #1e293b" }}>
                    <td style={{ padding: "6px 8px" }}>
                      <span>{String(c.nome || "").slice(0, 35)}</span>
                      {!!c.cnpj && <span style={{ fontSize: "10px", color: "#64748b", marginLeft: "4px" }}>({String(c.cnpj).slice(0, 8)}...)</span>}
                    </td>
                    <td style={{ padding: "6px 8px", textAlign: "center" }}>{Number(c.editais_participados || 0)}</td>
                    <td style={{ padding: "6px 8px", textAlign: "center", color: "#22c55e", fontWeight: 600 }}>{Number(c.editais_ganhos || 0)}</td>
                    <td style={{ padding: "6px 8px", textAlign: "center" }}>
                      <span style={{
                        padding: "2px 6px", borderRadius: "8px", fontSize: "11px", fontWeight: 600,
                        backgroundColor: Number(c.taxa_vitoria || 0) >= 70 ? "#ef444420" : Number(c.taxa_vitoria || 0) >= 40 ? "#eab30820" : "#22c55e20",
                        color: Number(c.taxa_vitoria || 0) >= 70 ? "#ef4444" : Number(c.taxa_vitoria || 0) >= 40 ? "#eab308" : "#22c55e",
                      }}>
                        {Number(c.taxa_vitoria || 0)}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {concorrentesLista && concorrentesLista.length === 0 && (
            <p style={{ fontSize: "13px", color: "#64748b" }}>Nenhum concorrente cadastrado. Busque vencedores das atas para identificar concorrentes.</p>
          )}
        </div>
        )}

        {/* Alerta de Recorrência */}
        {edital.historicoSemelhante.filter(h => h.resultado === "perdida").length >= 2 && (
          <div className="section-block" style={{ backgroundColor: "#78350f20", borderRadius: "8px", padding: "16px", border: "1px solid #f59e0b40" }}>
            <h4 style={{ color: "#f59e0b" }}><AlertTriangle size={16} /> Alerta de Recorrência</h4>
            <p style={{ fontSize: "13px", color: "#fbbf24" }}>Editais semelhantes foram <strong>perdidos {edital.historicoSemelhante.filter(h => h.resultado === "perdida").length} vezes</strong> por motivos recorrentes.</p>
          </div>
        )}
      </div>
    );
  };

  // Aba 4: Mercado (Reputação do Órgão da Analítica + Histórico da Cognitiva + botões IA)
  const handleAnalisarMercado = async (editalId: string, forcar = false) => {
    setMercadoLoading(true);
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      const res = await fetch(`/api/editais/${editalId}/analisar-mercado`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: token ? `Bearer ${token}` : "" },
        body: JSON.stringify({ forcar }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success) setMercadoData(data);
        else alert(data.error || "Erro na análise de mercado");
      } else {
        const err = await res.json().catch(() => ({}));
        alert(err.error || "Erro ao analisar mercado.");
      }
    } catch { alert("Erro de conexão."); }
    finally { setMercadoLoading(false); }
  };

  const renderAbaMercado = (edital: Edital) => {
    const orgao = (mercadoData?.orgao || {}) as { nome?: string; cnpj?: string; uf?: string };
    const stats = (mercadoData?.estatisticas || {}) as { total_compras?: number; valor_total?: number; valor_medio?: number; modalidades?: Record<string, number> };
    const similares = (mercadoData?.compras_similares || []) as { objeto?: string; valor?: number; data?: string; modalidade?: string }[];
    const reputacao = (mercadoData?.reputacao || {}) as { esfera?: string; risco_pagamento?: string; volume?: string; modalidade_principal?: string; percentual_pregao?: number; editais_similares?: number };
    const histInterno = (mercadoData?.historico_interno || {}) as { total?: number; go?: number; nogo?: number; avaliando?: number };
    const analiseIA = mercadoData?.analise_ia as string || "";
    const fmtVal = (v: number) => v ? new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(v) : "—";

    return (
      <div className="aba-content">
        {/* Botão de análise */}
        <div className="section-block" style={{ display: "flex", gap: "12px", alignItems: "center" }}>
          <ActionButton
            icon={mercadoLoading ? <RefreshCw size={14} className="spin" /> : <Building size={14} />}
            label={mercadoLoading ? "Analisando..." : (mercadoData ? "Reanalisar Mercado" : "Analisar Mercado do Órgão")}
            variant="primary"
            loading={mercadoLoading}
            onClick={() => handleAnalisarMercado(edital.id, !!mercadoData)}
          />
          {!mercadoData && !mercadoLoading && (
            <span style={{ fontSize: "12px", color: "#64748b" }}>Busca compras do órgão no PNCP, calcula estatísticas e gera análise via IA.</span>
          )}
          {!!mercadoData?.cache && (
            <span style={{ fontSize: "11px", color: "#64748b", padding: "2px 8px", borderRadius: "8px", backgroundColor: "#1e293b" }}>Cache (dados recentes)</span>
          )}
        </div>

        {mercadoData && (
          <>
            {/* Dados do Órgão */}
            <div className="section-block">
              <h4><Building size={16} /> Dados do Órgão</h4>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "12px" }}>
                <div><label style={{ fontSize: "11px", color: "#94a3b8" }}>Nome</label><p style={{ fontSize: "13px", margin: "2px 0" }}>{orgao.nome || edital.orgao}</p></div>
                <div><label style={{ fontSize: "11px", color: "#94a3b8" }}>CNPJ</label><p style={{ fontSize: "13px", margin: "2px 0" }}>{orgao.cnpj || "—"}</p></div>
                <div><label style={{ fontSize: "11px", color: "#94a3b8" }}>UF</label><p style={{ fontSize: "13px", margin: "2px 0" }}>{orgao.uf || edital.uf}</p></div>
              </div>
            </div>

            {/* Reputação (RF-033) */}
            {reputacao.esfera && (
              <div className="section-block">
                <h4><Shield size={16} /> Reputação do Órgão</h4>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "10px" }}>
                  <div style={{ padding: "10px", borderRadius: "8px", backgroundColor: "#0f172a", border: "1px solid #1e293b", textAlign: "center" }}>
                    <div style={{ fontSize: "11px", color: "#94a3b8" }}>Esfera</div>
                    <div style={{ fontSize: "14px", fontWeight: 600, color: reputacao.esfera === "Federal" ? "#3b82f6" : reputacao.esfera === "Estadual" ? "#8b5cf6" : "#eab308" }}>{reputacao.esfera}</div>
                  </div>
                  <div style={{ padding: "10px", borderRadius: "8px", backgroundColor: "#0f172a", border: "1px solid #1e293b", textAlign: "center" }}>
                    <div style={{ fontSize: "11px", color: "#94a3b8" }}>Risco Pagamento</div>
                    <div style={{ fontSize: "14px", fontWeight: 600, color: reputacao.risco_pagamento === "Baixo" ? "#22c55e" : reputacao.risco_pagamento === "Médio" ? "#eab308" : "#ef4444" }}>{reputacao.risco_pagamento}</div>
                  </div>
                  <div style={{ padding: "10px", borderRadius: "8px", backgroundColor: "#0f172a", border: "1px solid #1e293b", textAlign: "center" }}>
                    <div style={{ fontSize: "11px", color: "#94a3b8" }}>Volume Compras</div>
                    <div style={{ fontSize: "14px", fontWeight: 600 }}>{reputacao.volume}</div>
                  </div>
                  <div style={{ padding: "10px", borderRadius: "8px", backgroundColor: "#0f172a", border: "1px solid #1e293b", textAlign: "center" }}>
                    <div style={{ fontSize: "11px", color: "#94a3b8" }}>Modalidade Principal</div>
                    <div style={{ fontSize: "12px", fontWeight: 600 }}>{reputacao.modalidade_principal}</div>
                  </div>
                  <div style={{ padding: "10px", borderRadius: "8px", backgroundColor: "#0f172a", border: "1px solid #1e293b", textAlign: "center" }}>
                    <div style={{ fontSize: "11px", color: "#94a3b8" }}>% Pregão Eletrônico</div>
                    <div style={{ fontSize: "14px", fontWeight: 600, color: (reputacao.percentual_pregao || 0) > 30 ? "#22c55e" : "#eab308" }}>{reputacao.percentual_pregao}%</div>
                  </div>
                  <div style={{ padding: "10px", borderRadius: "8px", backgroundColor: "#0f172a", border: "1px solid #1e293b", textAlign: "center" }}>
                    <div style={{ fontSize: "11px", color: "#94a3b8" }}>Editais Similares</div>
                    <div style={{ fontSize: "14px", fontWeight: 600 }}>{reputacao.editais_similares}</div>
                  </div>
                </div>
              </div>
            )}

            {/* Volume de Compras */}
            <div className="section-block">
              <h4><TrendingUp size={16} /> Volume de Compras no PNCP</h4>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "12px", marginBottom: "12px" }}>
                <div style={{ padding: "12px", borderRadius: "8px", backgroundColor: "#0f172a", border: "1px solid #1e293b", textAlign: "center" }}>
                  <div style={{ fontSize: "24px", fontWeight: 700, color: "#3b82f6" }}>{stats.total_compras || 0}</div>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>Compras encontradas</div>
                </div>
                <div style={{ padding: "12px", borderRadius: "8px", backgroundColor: "#0f172a", border: "1px solid #1e293b", textAlign: "center" }}>
                  <div style={{ fontSize: "16px", fontWeight: 700, color: "#22c55e" }}>{fmtVal(stats.valor_total || 0)}</div>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>Valor total</div>
                </div>
                <div style={{ padding: "12px", borderRadius: "8px", backgroundColor: "#0f172a", border: "1px solid #1e293b", textAlign: "center" }}>
                  <div style={{ fontSize: "16px", fontWeight: 700, color: "#eab308" }}>{fmtVal(stats.valor_medio || 0)}</div>
                  <div style={{ fontSize: "11px", color: "#94a3b8" }}>Valor médio</div>
                </div>
              </div>
              {stats.modalidades && Object.keys(stats.modalidades).length > 0 && (
                <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
                  {Object.entries(stats.modalidades).sort((a, b) => (b[1] as number) - (a[1] as number)).map(([mod, cnt]) => (
                    <span key={mod} style={{ padding: "3px 8px", borderRadius: "10px", fontSize: "11px", backgroundColor: "#1e293b", color: "#94a3b8", border: "1px solid #334155" }}>
                      {mod}: {cnt as number}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Compras Similares */}
            {similares.length > 0 && (
              <div className="section-block">
                <h4><Search size={16} /> Compras Similares ({similares.length})</h4>
                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  {similares.map((c, i) => (
                    <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 10px", borderRadius: "6px", border: "1px solid #1e293b", backgroundColor: "#0f172a" }}>
                      <span style={{ fontSize: "12px", flex: 1 }}>{c.objeto}</span>
                      <div style={{ display: "flex", gap: "8px", alignItems: "center", flexShrink: 0 }}>
                        {c.valor && <span style={{ fontSize: "12px", color: "#22c55e" }}>{fmtVal(c.valor)}</span>}
                        <span style={{ fontSize: "11px", color: "#64748b" }}>{c.data}</span>
                        <span style={{ fontSize: "10px", color: "#94a3b8", padding: "1px 6px", borderRadius: "6px", backgroundColor: "#1e293b" }}>{c.modalidade}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Histórico Interno */}
            {histInterno.total && histInterno.total > 0 ? (
              <div className="section-block">
                <h4><ClipboardCheck size={16} /> Histórico Interno</h4>
                <div style={{ display: "flex", gap: "8px" }}>
                  <span style={{ padding: "4px 10px", borderRadius: "10px", fontSize: "12px", fontWeight: 600, backgroundColor: "#3b82f620", color: "#3b82f6" }}>{histInterno.total} edital(is)</span>
                  {(histInterno.go ?? 0) > 0 && <span style={{ padding: "4px 10px", borderRadius: "10px", fontSize: "12px", fontWeight: 600, backgroundColor: "#22c55e20", color: "#22c55e" }}>{histInterno.go} GO</span>}
                  {(histInterno.nogo ?? 0) > 0 && <span style={{ padding: "4px 10px", borderRadius: "10px", fontSize: "12px", fontWeight: 600, backgroundColor: "#ef444420", color: "#ef4444" }}>{histInterno.nogo} NO-GO</span>}
                  {(histInterno.avaliando ?? 0) > 0 && <span style={{ padding: "4px 10px", borderRadius: "10px", fontSize: "12px", fontWeight: 600, backgroundColor: "#eab30820", color: "#eab308" }}>{histInterno.avaliando} Em Avaliação</span>}
                </div>
              </div>
            ) : null}

            {/* Análise da IA */}
            {analiseIA && (
              <div className="section-block">
                <h4><Sparkles size={16} /> Análise de Mercado (IA)</h4>
                <p style={{ fontSize: "13px", color: "#94a3b8", lineHeight: 1.6, whiteSpace: "pre-line" }}>{analiseIA}</p>
              </div>
            )}
          </>
        )}
      </div>
    );
  };

  // Aba 5: IA (antigo conteudo da Cognitiva — Resumo + Pergunte + botões rápidos)
  const renderAbaIA = (edital: Edital) => (
    <div className="aba-content">
      {/* Resumo IA */}
      <div className="section-block">
        <h4><Sparkles size={16} /> Resumo Gerado pela IA</h4>
        {edital.resumo ? (
          <div>
            <div className="resumo-text" style={{ fontSize: "13px", lineHeight: 1.7, color: "#e2e8f0" }} dangerouslySetInnerHTML={{ __html: edital.resumo
              .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
              .replace(/^### (.+)$/gm, '<h4 style="color:#60a5fa;margin:8px 0 4px;font-size:14px;">$1</h4>')
              .replace(/^## (.+)$/gm, '<h3 style="color:#818cf8;margin:10px 0 4px;font-size:15px;">$1</h3>')
              .replace(/^- (.+)$/gm, '<div style="padding:2px 0 2px 12px;">• $1</div>')
              .replace(/\n\n/g, '<br/><br/>')
              .replace(/\n/g, '<br/>')
            }} />
            <ActionButton icon={<Sparkles size={14} />} label="Regerar Resumo" onClick={handleResumirEdital} loading={resumoLoading} variant="neutral" />
          </div>
        ) : (
          <div className="resumo-placeholder">
            <ActionButton icon={<Sparkles size={14} />} label="Gerar Resumo" onClick={handleResumirEdital} loading={resumoLoading} variant="primary" />
          </div>
        )}
      </div>

      {/* Pergunte a IA */}
      <div className="section-block">
        <h4><MessageSquare size={16} /> Pergunte a IA sobre este Edital</h4>
        <div className="pergunta-form">
          <TextInput value={pergunta} onChange={setPergunta} placeholder="Ex: Qual o prazo de entrega?" />
          <ActionButton icon={<MessageSquare size={14} />} label="Perguntar" variant="primary" onClick={handlePerguntarEdital} loading={loading} />
        </div>
        {resposta && (
          <div className="resposta-box">
            <strong>Resposta:</strong>
            <div style={{ fontSize: "13px", lineHeight: 1.7, color: "#e2e8f0", marginTop: "4px" }} dangerouslySetInnerHTML={{ __html: resposta
              .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
              .replace(/^### (.+)$/gm, '<h4 style="color:#60a5fa;margin:8px 0 4px;font-size:14px;">$1</h4>')
              .replace(/^## (.+)$/gm, '<h3 style="color:#818cf8;margin:10px 0 4px;font-size:15px;">$1</h3>')
              .replace(/^- (.+)$/gm, '<div style="padding:2px 0 2px 12px;">• $1</div>')
              .replace(/\n\n/g, '<br/><br/>')
              .replace(/\n/g, '<br/>')
            }} />
          </div>
        )}
      </div>

      {/* Ações Rápidas via IA — resposta na própria aba */}
      <div className="section-block">
        <h4><Sparkles size={16} /> Ações Rápidas via IA</h4>
        <div style={{ display: "flex", gap: "12px", flexWrap: "wrap", marginBottom: "8px" }}>
          <ActionButton
            icon={<Target size={14} />}
            label={loading ? "Buscando..." : "Requisitos Técnicos"}
            variant="neutral"
            loading={loading}
            onClick={async () => {
              // CV13-11: passa pelo helper unico para empilhar no historicoQA
              setLoading(true);
              setResposta("");
              setPergunta("Quais são os requisitos técnicos?");
              try {
                await _enviarParaIA(
                  "Quais são os requisitos técnicos?",
                  `Sobre o edital ${edital.numero} do órgão ${edital.orgao}: Quais são os requisitos técnicos deste edital? Liste cada requisito técnico exigido.`,
                );
              } finally { setLoading(false); }
            }}
          />
          <ActionButton
            icon={<ClipboardCheck size={14} />}
            label={loading ? "Classificando..." : "Classificar Edital"}
            variant="neutral"
            loading={loading}
            onClick={async () => {
              // CV13-11: passa pelo helper unico para empilhar no historicoQA
              setLoading(true);
              setResposta("");
              setPergunta("Classificar edital");
              try {
                await _enviarParaIA(
                  "Classificar edital",
                  `Classifique este edital: ${edital.objeto}. Informe a categoria (comodato, venda, aluguel, consumo, serviço) e justifique.`,
                );
              } finally { setLoading(false); }
            }}
          />
        </div>
      </div>

      {/* CV13-11 (Arnaldo Sprint 2 V8): Historico de Q&A da sessao.
          Antes, cada nova pergunta/Requisitos/Classificar sobrescrevia `resposta`
          (slot unico) e o validador "perdia" as anteriores. Agora todas ficam
          empilhadas aqui, mais recente no topo. */}
      {historicoQA.length > 0 && (
        <div className="section-block">
          <h4 style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span><MessageSquare size={16} /> Histórico desta sessão ({historicoQA.length})</span>
            <button
              onClick={() => setHistoricoQA([])}
              style={{ fontSize: "11px", padding: "2px 10px", background: "transparent", color: "#94a3b8", border: "1px solid #334155", borderRadius: "4px", cursor: "pointer" }}
              title="Limpar histórico desta sessão"
            >Limpar</button>
          </h4>
          <div style={{ maxHeight: "320px", overflowY: "auto", paddingRight: "4px" }}>
            {historicoQA.map((qa, i) => (
              <div key={qa.ts} style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "6px", padding: "10px 12px", marginBottom: "8px" }}>
                <div style={{ fontSize: "12px", color: "#cbd5e1", marginBottom: "6px" }}>
                  <strong style={{ color: "#60a5fa" }}>P{historicoQA.length - i}:</strong> {qa.pergunta}
                </div>
                <div
                  style={{ fontSize: "12px", color: "#94a3b8", lineHeight: 1.6 }}
                  dangerouslySetInnerHTML={{ __html: qa.resposta
                    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                    .replace(/^### (.+)$/gm, '<h5 style="color:#60a5fa;margin:6px 0 3px;font-size:13px;">$1</h5>')
                    .replace(/^## (.+)$/gm, '<h4 style="color:#818cf8;margin:8px 0 4px;font-size:14px;">$1</h4>')
                    .replace(/^- (.+)$/gm, '<div style="padding:1px 0 1px 10px;">• $1</div>')
                    .replace(/\n\n/g, '<br/><br/>')
                    .replace(/\n/g, '<br/>')
                  }}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );

  const analysisTabs = [
    { id: "aderencia", label: "Aderencia", icon: <Target size={16} /> },
    { id: "lotes", label: `Lotes (${lotesEdital.length})`, icon: <Layers size={16} /> },
    { id: "documentos", label: "Documentos", icon: <FolderOpen size={16} /> },
    { id: "riscos", label: "Riscos", icon: <AlertTriangle size={16} /> },
    { id: "mercado", label: "Mercado", icon: <Building size={16} /> },
    { id: "ia", label: "IA", icon: <Sparkles size={16} /> },
  ];

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-left">
          <ClipboardCheck size={24} />
          <div>
            <h1>Validacao de Editais</h1>
            <p>Analise multi-dimensional, scores e decisao estrategica</p>
          </div>
        </div>
      </div>

      <div className="page-content">
        {/* Tabela de editais */}
        <Card title="Meus Editais" icon={<FileText size={18} />}>
          {erroCarregamento && (
            <div className="error-banner">
              <AlertCircle size={16} /> {erroCarregamento}
              <ActionButton label="Tentar novamente" variant="neutral" onClick={() => {
                setErroCarregamento("");
                setLoadingEditais(true);
                loadEditaisSalvos()
                  .then(setEditais)
                  .catch(err => setErroCarregamento(String(err?.message || "Erro ao carregar editais")))
                  .finally(() => setLoadingEditais(false));
              }} />
            </div>
          )}
          <FilterBar
            searchValue={searchTerm}
            onSearchChange={setSearchTerm}
            searchPlaceholder="Buscar edital..."
            filters={[{
              key: "status", label: "Status", value: statusFilter, onChange: setStatusFilter,
              options: [
                { value: "todos", label: "Todos" },
                { value: "novo", label: "Novo" },
                { value: "go", label: "GO" },
                { value: "avaliando", label: "Em Avaliação" },
                { value: "nogo", label: "NO-GO" },
              ],
            }]}
          />
          <DataTable
            data={filteredEditais}
            columns={columns}
            idKey="id"
            onRowClick={(edital) => {
              // Limpar sub-scores, decisão IA e dados dependentes ao trocar edital
              setSubScoresTecnicos([]);
              setDecisaoIA(null);
              setJustificativaIA("");
              setPontosPositivos([]);
              setPontosAtencao([]);
              setDocsNecessaria([]);
              setDocsNecessariaErro("");
              setHistoricoReal([]);
              setReputacaoCalculada(null);
              setRiscosData(null);
              setHistoricoVencedores(null);
              setVencedoresAtas(null);
              setConcorrentesLista(null);
              setMercadoData(null);
              // CV08-9 (Arnaldo Sprint 2 V8): resetar estado de justificativa/decisao
              // p/ NAO vazar Motivo/Detalhes do edital anterior ao trocar.
              setShowJustificativa(false);
              setJustificativaMotivo("");
              setJustificativaTexto("");
              setPendingDecisao(null);
              setDecisaoSalva(false);
              setSelectedEdital(edital);
            }}
            selectedId={selectedEdital?.id}
            emptyMessage={loadingEditais ? "Carregando editais..." : "Nenhum edital encontrado"}
          />
        </Card>

        {/* Painel de analise do edital selecionado */}
        {selectedEdital && (
          <>
            {/* Barra de info do edital + status + ações */}
            <Card title={`${selectedEdital.numero} — ${selectedEdital.orgao}`} icon={<ClipboardCheck size={18} />}
              actions={
                <div className="card-actions" style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                  <ActionButton icon={<Eye size={14} />} label="Ver Edital" onClick={handleVerPdf} />
                  <SelectInput value={selectedEdital.status} onChange={(v) => handleMudarStatus(selectedEdital.id, v as Edital["status"])}
                    options={[
                      { value: "novo", label: "Novo" },
                      { value: "go", label: "GO" },
                      { value: "avaliando", label: "Em Avaliação" },
                      { value: "nogo", label: "NO-GO" },
                    ]}
                  />
                  {selectedEdital.sinaisMercado.length > 0 && selectedEdital.sinaisMercado.map((sinal, i) => (
                    <span key={i} className={`badge ${sinal.includes("Direcionada") || sinal.includes("Predatorio") ? "badge-error" : "badge-warning"}`}>
                      <AlertTriangle size={12} /> {sinal}
                    </span>
                  ))}
                  {decisaoSalva && (
                    <span className="badge badge-success"><CheckCircle size={12} /> Decisao salva</span>
                  )}
                </div>
              }
            >
              <div className="info-grid" style={{ display: "grid", gridTemplateColumns: "1fr auto auto auto", gap: "12px", alignItems: "start" }}>
                <div className="info-item"><label>Objeto</label><p style={{ fontSize: "13px", margin: 0 }}>{selectedEdital.objeto}</p></div>
                <div className="info-item"><label>Valor</label><span>{formatCurrency(selectedEdital.valor)}</span></div>
                <div className="info-item"><label>Abertura</label><span>{selectedEdital.dataAbertura}</span></div>
                <div className="info-item"><label>Produto</label><span>{selectedEdital.produtoCorrespondente || "-"}</span></div>
              </div>
            </Card>

            {/* Todas as abas */}
            <Card>
              <TabPanel tabs={analysisTabs}>
                {(activeTab) => {
                  switch (activeTab) {
                    case "aderencia": return renderAbaAderencia(selectedEdital);
                    case "lotes": return renderAbaLotes(selectedEdital);
                    case "documentos": return renderAbaDocumentos(selectedEdital);
                    case "riscos": return renderAbaRiscos(selectedEdital);
                    case "mercado": return renderAbaMercado(selectedEdital);
                    case "ia": return renderAbaIA(selectedEdital);
                    default: return null;
                  }
                }}
              </TabPanel>
            </Card>
          </>
        )}
      </div>

      {/* Modal Pergunta */}
      <Modal
        isOpen={showPerguntaModal}
        onClose={() => { setShowPerguntaModal(false); setPergunta(""); setResposta(""); /* CV13-11: NAO limpar historicoQA aqui — preservar entre aberturas */ }}
        title={`Perguntar ao Edital ${selectedEdital?.numero}`}
        size="large"
      >
        <FormField label="Sua pergunta">
          <TextArea value={pergunta} onChange={setPergunta} placeholder="Digite sua pergunta sobre o edital..." rows={3} />
        </FormField>
        <ActionButton icon={<MessageSquare size={14} />} label="Enviar Pergunta" variant="primary" onClick={handlePerguntarEdital} loading={loading} />
        {resposta && (
          <div className="resposta-box" style={{ marginTop: "1rem" }}>
            <strong>Resposta:</strong>
            <div style={{ fontSize: "13px", lineHeight: 1.7, color: "#e2e8f0", marginTop: "4px" }} dangerouslySetInnerHTML={{ __html: resposta
              .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
              .replace(/^### (.+)$/gm, '<h4 style="color:#60a5fa;margin:8px 0 4px;font-size:14px;">$1</h4>')
              .replace(/^## (.+)$/gm, '<h3 style="color:#818cf8;margin:10px 0 4px;font-size:15px;">$1</h3>')
              .replace(/^- (.+)$/gm, '<div style="padding:2px 0 2px 12px;">• $1</div>')
              .replace(/\n\n/g, '<br/><br/>')
              .replace(/\n/g, '<br/>')
            }} />
          </div>
        )}
        {/* CV13-11 (Arnaldo Sprint 2 V8): historico de Q&A da sessao */}
        {historicoQA.length > 1 && (
          <div style={{ marginTop: "16px", borderTop: "1px solid #334155", paddingTop: "12px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
              <strong style={{ fontSize: "13px", color: "#94a3b8" }}>Historico desta sessao ({historicoQA.length})</strong>
              <button onClick={() => setHistoricoQA([])} style={{ fontSize: "11px", padding: "2px 8px", background: "transparent", color: "#94a3b8", border: "1px solid #334155", borderRadius: "4px", cursor: "pointer" }}>Limpar</button>
            </div>
            {historicoQA.slice(1).map((qa, i) => (
              <div key={qa.ts} style={{ background: "#0f172a", border: "1px solid #1e293b", borderRadius: "6px", padding: "8px 10px", marginBottom: "6px" }}>
                <div style={{ fontSize: "12px", color: "#cbd5e1", marginBottom: "4px" }}><strong>P{historicoQA.length - i - 1}:</strong> {qa.pergunta}</div>
                <div style={{ fontSize: "12px", color: "#94a3b8", lineHeight: 1.5 }}>{qa.resposta.length > 280 ? qa.resposta.slice(0, 280) + "..." : qa.resposta}</div>
              </div>
            ))}
          </div>
        )}
      </Modal>

      {/* PdfViewer fullscreen modal */}
      {selectedEdital && (
        <PdfViewer
          isOpen={pdfViewerOpen}
          onClose={() => setPdfViewerOpen(false)}
          editalId={selectedEdital.id}
          pdfUrl={selectedEdital.pdfUrl}
          titulo={`Edital ${selectedEdital.numero} - ${selectedEdital.orgao}`}
          editalNumero={selectedEdital.numero}
          pdfJaSalvo={!!selectedEdital.pdfPath}
          onPdfSalvo={() => {
            // Atualizar pdfPath no estado para refletir que foi salvo
            setEditais(prev => prev.map(e =>
              e.id === selectedEdital.id ? { ...e, pdfPath: "saved" } : e
            ));
            setSelectedEdital(prev => prev ? { ...prev, pdfPath: "saved" } : prev);
          }}
        />
      )}
    </div>
  );
}
