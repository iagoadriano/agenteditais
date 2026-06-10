import { useState, useEffect, useMemo, useCallback } from "react";
import type { PageProps } from "../types";
import { Search, Save, Download, Eye, FileText, ExternalLink, Calendar, AlertTriangle, Sparkles, X, CheckCircle, Plus, Pause, Trash2, Brain, DollarSign, History, RefreshCw, ShoppingCart, Send } from "lucide-react";
import { useAuth } from "../contexts/AuthContext";
import {
  Card, StatCard, DataTable, ActionButton, FormField, TextInput, Checkbox,
  SelectInput, ScoreCircle, StarRating, RadioGroup, StatusBadge,
  TabPanel, Modal,
} from "../components/common";
import type { Column } from "../components/common";
import { crudList, crudCreate, crudUpdate, crudDelete } from "../api/crud";
import InteligenciaComercialPanel from "../components/InteligenciaComercialPanel";

// --- Interfaces ---

interface EditalScores {
  tecnico: number;
  comercial: number;
  recomendacao: number;
}

interface GapItem {
  item: string;
  tipo: "atendido" | "parcial" | "nao_atendido";
}

interface EditalBusca {
  id: string;
  numero: string;
  orgao: string;
  uf: string;
  objeto: string;
  valor: number;
  dataAbertura: string;
  diasRestantes: number;
  score: number;
  scores: EditalScores;
  status: "aberto" | "encerrado";
  produtoCorrespondente: string | null;
  classificacaoTipo: string;
  classificacaoOrigem: string;
  tipoProdutoInferido: string;
  origemInferida: string;
  potencialGanho: "elevado" | "medio" | "baixo";
  intencaoEstrategica: "estrategico" | "defensivo" | "acompanhamento" | "aprendizado";
  margemExpectativa: number;
  gaps: GapItem[];
  modalidade?: string;
  selected?: boolean;
  url?: string;
  fonte?: string;
  orgaoTipo?: string;
  justificativa?: string;
  recomendacaoTexto?: string;
  scoreProfundo?: {
    scores: { tecnico: number; documental: number; complexidade: number; juridico: number; logistico: number; comercial: number };
    score_geral: number;
    decisao: string;
    justificativa: string;
    pontos_positivos: string[];
    pontos_atencao: string[];
  } | null;
  // Itens do edital (vindos do PNCP via enriquecimento)
  itens?: { numero_item?: number; descricao?: string; quantidade?: number; unidade_medida?: string; valor_unitario_estimado?: number; valor_total_estimado?: number }[];
  totalItens?: number;
  // RF-013: Vinculo com classe/subclasse de produto
  classe_produto_id?: string;
  subclasse_produto_id?: string;
  // Dados PNCP para download de PDF e URL do portal
  cnpj_orgao?: string;
  ano_compra?: number;
  seq_compra?: number;
  // IDs de registros salvos (para update)
  editalSalvoId?: string;
  estrategiaId?: string;
  // UC-SC01: Score de competitividade
  score_competitividade?: number | null;
}

interface MonitoramentoInfo {
  id: string;
  termo: string;
  nome?: string;
  ncm?: string;
  fontes?: string[];
  ufs?: string[];
  incluir_encerrados?: boolean;
  valor_minimo?: number;
  valor_maximo?: number;
  frequencia_horas?: number;
  score_minimo_alerta?: number;
  ativo: boolean;
  ultimo_check?: string;
  editais_encontrados?: number;
}

// --- Interfaces Dispensas ---

interface DispensaItem {
  id: string;
  numero: string;
  orgao: string;
  uf: string;
  artigo: string;
  objeto: string;
  valor: number;
  valor_limite?: number;
  prazo_dias: number;
  status: "aberta" | "cotacao_enviada" | "adjudicada" | "encerrada";
  data_publicacao?: string;
  data_encerramento?: string;
}

interface DispensaStats {
  abertas: number;
  cotacao_enviada: number;
  adjudicadas: number;
  encerradas: number;
}

interface DispensaCotacaoResult {
  success: boolean;
  cotacao_id?: string;
  valor_proposto?: number;
  itens?: { descricao: string; quantidade: number; valor_unitario: number; valor_total: number }[];
  observacoes?: string;
  error?: string;
}

// Transicoes de status validas para dispensas
const DISPENSA_STATUS_TRANSITIONS: Record<string, { value: string; label: string }[]> = {
  aberta: [
    { value: "cotacao_enviada", label: "Cotacao Enviada" },
    { value: "encerrada", label: "Encerrada" },
  ],
  cotacao_enviada: [
    { value: "adjudicada", label: "Adjudicada" },
    { value: "encerrada", label: "Encerrada" },
  ],
  adjudicada: [
    { value: "encerrada", label: "Encerrada" },
  ],
  encerrada: [],
};

const ARTIGOS_DISPENSA = [
  { value: "", label: "Todos" },
  { value: "75-I", label: "Art. 75, I" },
  { value: "75-II", label: "Art. 75, II" },
  { value: "75-III", label: "Art. 75, III" },
  { value: "75-IV", label: "Art. 75, IV" },
  { value: "75-V", label: "Art. 75, V" },
];

// --- UFs brasileiras ---
const UFS = [
  { value: "todas", label: "Todas" },
  { value: "AC", label: "Acre" }, { value: "AL", label: "Alagoas" }, { value: "AP", label: "Amapa" },
  { value: "AM", label: "Amazonas" }, { value: "BA", label: "Bahia" }, { value: "CE", label: "Ceara" },
  { value: "DF", label: "Distrito Federal" }, { value: "ES", label: "Espirito Santo" },
  { value: "GO", label: "Goias" }, { value: "MA", label: "Maranhao" }, { value: "MT", label: "Mato Grosso" },
  { value: "MS", label: "Mato Grosso do Sul" }, { value: "MG", label: "Minas Gerais" },
  { value: "PA", label: "Para" }, { value: "PB", label: "Paraiba" }, { value: "PR", label: "Parana" },
  { value: "PE", label: "Pernambuco" }, { value: "PI", label: "Piaui" }, { value: "RJ", label: "Rio de Janeiro" },
  { value: "RN", label: "Rio Grande do Norte" }, { value: "RS", label: "Rio Grande do Sul" },
  { value: "RO", label: "Rondonia" }, { value: "RR", label: "Roraima" }, { value: "SC", label: "Santa Catarina" },
  { value: "SP", label: "Sao Paulo" }, { value: "SE", label: "Sergipe" }, { value: "TO", label: "Tocantins" },
];

// --- Helpers ---

function calcularDiasRestantes(dataAbertura: string): number {
  if (!dataAbertura) return 0;
  try {
    // Tenta parsear tanto "DD/MM/YYYY" quanto "YYYY-MM-DD" ou ISO
    let data: Date;
    if (dataAbertura.includes("/")) {
      const [d, m, y] = dataAbertura.split("/").map(Number);
      data = new Date(y, m - 1, d);
    } else {
      data = new Date(dataAbertura);
    }
    const hoje = new Date();
    hoje.setHours(0, 0, 0, 0);
    const diff = Math.ceil((data.getTime() - hoje.getTime()) / (1000 * 60 * 60 * 24));
    return diff > 0 ? diff : 0;
  } catch {
    return 0;
  }
}

function formatarDataBr(dataStr: string): string {
  if (!dataStr) return "—";
  try {
    if (dataStr.includes("/")) return dataStr;
    const data = new Date(dataStr);
    if (isNaN(data.getTime())) return dataStr;
    return data.toLocaleDateString("pt-BR");
  } catch {
    return dataStr;
  }
}

function inferirPotencialGanho(score: number): "elevado" | "medio" | "baixo" {
  if (score >= 80) return "elevado";
  if (score >= 50) return "medio";
  return "baixo";
}

// Mapa de estados vizinhos (adjacentes) para calculo de score comercial
const UF_VIZINHOS: Record<string, string[]> = {
  AC: ["AM", "RO"],
  AL: ["BA", "PE", "SE"],
  AP: ["PA"],
  AM: ["AC", "RO", "MT", "PA", "RR"],
  BA: ["AL", "SE", "PE", "PI", "TO", "GO", "MG", "ES"],
  CE: ["PI", "PE", "PB", "RN"],
  DF: ["GO", "MG"],
  ES: ["BA", "MG", "RJ"],
  GO: ["BA", "TO", "MT", "MS", "MG", "DF"],
  MA: ["PI", "TO", "PA"],
  MT: ["AM", "PA", "TO", "GO", "MS", "RO"],
  MS: ["MT", "GO", "MG", "SP", "PR"],
  MG: ["BA", "ES", "RJ", "SP", "MS", "GO", "DF"],
  PA: ["AM", "MT", "TO", "MA", "AP", "RR"],
  PB: ["PE", "RN", "CE"],
  PR: ["SP", "MS", "SC"],
  PE: ["AL", "BA", "PI", "CE", "PB"],
  PI: ["MA", "CE", "PE", "BA", "TO"],
  RJ: ["ES", "MG", "SP"],
  RN: ["CE", "PB"],
  RS: ["SC"],
  RO: ["AC", "AM", "MT"],
  RR: ["AM", "PA"],
  SC: ["PR", "RS"],
  SP: ["MG", "RJ", "MS", "PR"],
  SE: ["AL", "BA"],
  TO: ["MA", "PI", "BA", "GO", "MT", "PA"],
};

function calcularScoreComercial(ufEdital: string, estadosAtuacao: string[]): number {
  if (!ufEdital || estadosAtuacao.length === 0) return 20;
  const ufUpper = ufEdital.toUpperCase().trim();
  // UF esta nos estados de atuacao
  if (estadosAtuacao.some(u => u.toUpperCase().trim() === ufUpper)) return 100;
  // UF adjacente a algum estado de atuacao
  const vizinhos = new Set<string>();
  for (const uf of estadosAtuacao) {
    const adj = UF_VIZINHOS[uf.toUpperCase().trim()] || [];
    adj.forEach(v => vizinhos.add(v));
  }
  if (vizinhos.has(ufUpper)) return 60;
  // Fora da regiao
  return 20;
}

// Mapeia dados do endpoint /api/editais/buscar para EditalBusca
function normalizarEditalDaBusca(e: Record<string, unknown>, estadosAtuacao: string[]): EditalBusca {
  const scoreTecnico = Number(e.score_tecnico ?? 0);
  const dataAbertura = formatarDataBr(String(e.data_abertura ?? ""));
  // Usar data_encerramento para calcular prazo restante (é a data limite real).
  // Fallback para data_abertura se encerramento não existir.
  const dataParaPrazo = String(e.data_encerramento ?? e.data_abertura ?? "");
  const diasRestantes = calcularDiasRestantes(dataParaPrazo);

  // C1: Score comercial corrigido (RF-020)
  let scoreComercial: number;
  if (e.score_comercial !== undefined && e.score_comercial !== null) {
    scoreComercial = Number(e.score_comercial);
  } else {
    scoreComercial = calcularScoreComercial(String(e.uf ?? ""), estadosAtuacao);
  }

  // Se score profundo existe, usar ele; senao, media rapida
  const scoreProfundoGeral = e.score_profundo
    ? Number((e.score_profundo as Record<string, unknown>).score_geral ?? 0)
    : 0;
  const scoreGeral = scoreProfundoGeral > 0
    ? Math.round(scoreProfundoGeral)
    : Math.round((scoreTecnico + scoreComercial) / 2);

  // Extrair produto correspondente da lista de produtos aderentes
  const produtos = e.produtos_aderentes as (string | { produto_nome?: string; aderencia?: number })[] | undefined;
  let produtoCorrespondente: string | null = null;
  if (produtos && produtos.length > 0) {
    const first = produtos[0];
    produtoCorrespondente = typeof first === "string" ? first : (first?.produto_nome ?? null);
  }

  // C2: Gaps reais do backend (RF-024)
  let gaps: GapItem[] = [];
  const rawGaps = e.analise_gaps ?? e.gaps;
  if (Array.isArray(rawGaps) && rawGaps.length > 0) {
    gaps = rawGaps.map((g: unknown) => {
      if (typeof g === "object" && g !== null && "item" in (g as Record<string, unknown>)) {
        const gObj = g as Record<string, unknown>;
        return {
          item: String(gObj.item ?? ""),
          tipo: (String(gObj.tipo ?? "nao_atendido")) as GapItem["tipo"],
        };
      }
      return { item: String(g), tipo: "nao_atendido" as const };
    });
  } else if (scoreTecnico > 0 || scoreComercial > 0) {
    // Gerar gaps basicos quando o array esta vazio mas temos scores
    if (scoreTecnico < 70) {
      gaps.push({ item: "Aderencia tecnica insuficiente", tipo: scoreTecnico >= 40 ? "parcial" : "nao_atendido" });
    }
    if (scoreComercial < 70) {
      gaps.push({ item: "Regiao de atuacao fora do ideal", tipo: scoreComercial >= 40 ? "parcial" : "nao_atendido" });
    }
    if (scoreTecnico >= 70 && scoreComercial >= 70) {
      gaps.push({ item: "Requisitos basicos atendidos", tipo: "atendido" });
    }
  }

  return {
    id: String(e.id ?? ""),
    numero: String(e.numero ?? "—"),
    orgao: String(e.orgao ?? "—"),
    uf: String(e.uf ?? "—"),
    objeto: String(e.objeto ?? "—"),
    valor: Number(e.valor_estimado ?? 0),
    dataAbertura,
    diasRestantes,
    score: scoreGeral,
    scores: {
      tecnico: scoreTecnico,
      comercial: scoreComercial,
      recomendacao: Number(e.recomendacao ?? scoreGeral),
    },
    status: Boolean(e.encerrado) ? "encerrado" : "aberto",
    produtoCorrespondente,
    classificacaoTipo: String(e.tipo_produto_inferido || e.modalidade || "—"),
    classificacaoOrigem: String(e.origem_inferida || e.orgao_tipo || "—"),
    tipoProdutoInferido: String(e.tipo_produto_inferido ?? ""),
    origemInferida: String(e.origem_inferida ?? ""),
    potencialGanho: inferirPotencialGanho(scoreGeral),
    intencaoEstrategica: "acompanhamento",
    margemExpectativa: 15,
    gaps,
    url: String(e.url ?? ""),
    fonte: String(e.fonte ?? ""),
    modalidade: String(e.modalidade ?? "—"),
    orgaoTipo: String(e.orgao_tipo ?? "outro"),
    justificativa: String(e.justificativa ?? ""),
    recomendacaoTexto: String(e.recomendacao ?? ""),
    itens: Array.isArray(e.itens) ? (e.itens as Record<string, unknown>[]).map(it => ({
      numero_item: it.numero_item != null ? Number(it.numero_item) : undefined,
      descricao: String(it.descricao ?? ""),
      quantidade: it.quantidade != null ? Number(it.quantidade) : undefined,
      unidade_medida: it.unidade_medida ? String(it.unidade_medida) : undefined,
      valor_unitario_estimado: it.valor_unitario_estimado != null ? Number(it.valor_unitario_estimado) : undefined,
      valor_total_estimado: it.valor_total_estimado != null ? Number(it.valor_total_estimado) : undefined,
    })) : [],
    totalItens: Number(e.total_itens ?? 0),
    scoreProfundo: e.score_profundo ? {
      scores: (e.score_profundo as Record<string, unknown>).scores as { tecnico: number; documental: number; complexidade: number; juridico: number; logistico: number; comercial: number },
      score_geral: Number((e.score_profundo as Record<string, unknown>).score_geral ?? 0),
      decisao: String((e.score_profundo as Record<string, unknown>).decisao ?? "AVALIAR"),
      justificativa: String((e.score_profundo as Record<string, unknown>).justificativa ?? ""),
      pontos_positivos: ((e.score_profundo as Record<string, unknown>).pontos_positivos as string[]) || [],
      pontos_atencao: ((e.score_profundo as Record<string, unknown>).pontos_atencao as string[]) || [],
    } : null,
    classe_produto_id: e.classe_produto_id ? String(e.classe_produto_id) : undefined,
    subclasse_produto_id: e.subclasse_produto_id ? String(e.subclasse_produto_id) : undefined,
    cnpj_orgao: e.cnpj_orgao ? String(e.cnpj_orgao) : undefined,
    ano_compra: e.ano_compra ? Number(e.ano_compra) : undefined,
    seq_compra: e.seq_compra ? Number(e.seq_compra) : undefined,
  };
}

// --- Contagens de prazos ---
function contarPrazos(editais: EditalBusca[]) {
  const abertos = editais.filter(e => e.status === "aberto");
  return {
    dias2: abertos.filter(e => e.diasRestantes <= 2 && e.diasRestantes > 0).length,
    dias5: abertos.filter(e => e.diasRestantes <= 5 && e.diasRestantes > 0).length,
    dias10: abertos.filter(e => e.diasRestantes <= 10 && e.diasRestantes > 0).length,
    dias20: abertos.filter(e => e.diasRestantes <= 20 && e.diasRestantes > 0).length,
  };
}

// --- Componente ---

export function CaptacaoPage(props?: PageProps) {
  const onSendToChat = props?.onSendToChat;
  const { empresa } = useAuth();
  const [termo, setTermo] = useState("");
  const [termoDropdownAberto, setTermoDropdownAberto] = useState(false);
  const [uf, setUf] = useState("todas");
  const [fonte, setFonte] = useState("todas");
  const [classificacaoTipo, setClassificacaoTipo] = useState("todos");
  const [classificacaoOrigem, setClassificacaoOrigem] = useState("todos");

  // Select cascata: Área → Classe → Subclasse
  const [selectedArea, setSelectedArea] = useState("");
  const [selectedClasse, setSelectedClasse] = useState("");
  const [selectedSubclasse, setSelectedSubclasse] = useState("");
  const [modalidadeFiltro, setModalidadeFiltro] = useState("todos");
  const [tipoScore, setTipoScore] = useState<"nenhum" | "rapido" | "hibrido" | "profundo">("nenhum");
  const [limiteScoreProfundo, setLimiteScoreProfundo] = useState<number>(10);
  const [incluirEncerrados, setIncluirEncerrados] = useState(false);

  // RF-013: Filtro local por classe de produto
  const [filtroClasseProduto, setFiltroClasseProduto] = useState("todos");
  const [classesV2, setClassesV2] = useState<{ value: string; label: string }[]>([]);

  const [resultados, setResultados] = useState<EditalBusca[]>([]);
  const [relatorioMD, setRelatorioMD] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  // CV01-6 (Arnaldo Sprint 2 V8): avisos por fonte (BEC indisponivel, NCM ignorado, etc)
  const [errosFontes, setErrosFontes] = useState<string[] | null>(null);

  // CV01-3 (Arnaldo Sprint 2 V8): limpar todos os filtros
  const handleLimparFiltros = () => {
    setTermo("");
    setNcm("");
    setUf("todas");
    setFonte("todas");
    setModalidadeFiltro("todos");
    setClassificacaoTipo("todos");
    setClassificacaoOrigem("todos");
    setTipoScore("nenhum");
    setIncluirEncerrados(false);
    setResultados([]);
    setErro(null);
    setErrosFontes(null);
  };
  const [painelEdital, setPainelEdital] = useState<EditalBusca | null>(null);
  const [intencaoLocal, setIntencaoLocal] = useState<EditalBusca["intencaoEstrategica"]>("estrategico");
  const [margemLocal, setMargemLocal] = useState(15);
  const [salvandoEstrategia, setSalvandoEstrategia] = useState(false);
  const [estrategiaSalva, setEstrategiaSalva] = useState(false);
  const [variaPorProduto, setVariaPorProduto] = useState(false);
  const [variaPorRegiao, setVariaPorRegiao] = useState(false);

  const [monitoramentos, setMonitoramentos] = useState<MonitoramentoInfo[]>([]);
  const [loadingMonitoramentos, setLoadingMonitoramentos] = useState(false);

  // C1: Estados de atuacao carregados de parametros-score
  const [estadosAtuacao, setEstadosAtuacao] = useState<string[]>([]);

  // C3: NCM search field
  const [ncm, setNcm] = useState("");
  const [diasBusca, setDiasBusca] = useState("90");

  // C3: Novo monitoramento inline form (mesmos parâmetros da busca)
  const [showNovoMonitoramento, setShowNovoMonitoramento] = useState(false);
  const [novoMonTermo, setNovoMonTermo] = useState("");
  const [novoMonNcm, setNovoMonNcm] = useState("");
  const [novoMonUfs, setNovoMonUfs] = useState("");
  const [novoMonFonte, setNovoMonFonte] = useState("pncp");
  const [novoMonEncerrados, setNovoMonEncerrados] = useState(false);
  const [novoMonFreq, setNovoMonFreq] = useState("24h");
  const [novoMonScoreMin, setNovoMonScoreMin] = useState(70);

  // C2: Scores de validacao (gaps reais do endpoint)
  const [scoresValidacao, setScoresValidacao] = useState<Record<string, unknown> | null>(null);
  const [loadingScores, setLoadingScores] = useState(false);

  // --- Dispensas state ---
  const [dispensas, setDispensas] = useState<DispensaItem[]>([]);
  const [dispensaStats, setDispensaStats] = useState<DispensaStats>({ abertas: 0, cotacao_enviada: 0, adjudicadas: 0, encerradas: 0 });
  const [dispensasLoading, setDispensasLoading] = useState(false);
  const [dispensasErro, setDispensasErro] = useState<string | null>(null);
  // Dispensas filters
  const [dispFiltroArtigo, setDispFiltroArtigo] = useState("");
  const [dispFiltroValorMin, setDispFiltroValorMin] = useState("");
  const [dispFiltroValorMax, setDispFiltroValorMax] = useState("");
  const [dispFiltroUf, setDispFiltroUf] = useState("");
  const [dispFiltroOrgao, setDispFiltroOrgao] = useState("");
  // Dispensas busca PNCP
  const [dispBuscaTermo, setDispBuscaTermo] = useState("");
  const [dispBuscaUf, setDispBuscaUf] = useState("");
  const [dispBuscaDias, setDispBuscaDias] = useState("90");
  const [dispBuscaLoading, setDispBuscaLoading] = useState(false);
  // Dispensas cotacao modal
  const [cotacaoModalOpen, setCotacaoModalOpen] = useState(false);
  const [cotacaoResult, setCotacaoResult] = useState<DispensaCotacaoResult | null>(null);
  const [cotacaoLoading, setCotacaoLoading] = useState(false);
  const [cotacaoDispensaId, setCotacaoDispensaId] = useState<string | null>(null);
  // Dispensas status update
  const [statusUpdateId, setStatusUpdateId] = useState<string | null>(null);

  // Fontes de editais carregadas do banco
  const [fontesDisponiveis, setFontesDisponiveis] = useState<{ value: string; label: string }[]>([]);
  // Modalidades, origens e tipos de produto carregados do banco
  const [modalidadesDisponiveis, setModalidadesDisponiveis] = useState<{ value: string; label: string; id: string }[]>([]);
  const [origensDisponiveis, setOrigensDisponiveis] = useState<{ value: string; label: string }[]>([]);
  const [tiposProdutoDisponiveis, setTiposProdutoDisponiveis] = useState<{ value: string; label: string }[]>([]);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [areasData, setAreasData] = useState<any[]>([]);
  // Produtos do portfólio para select no campo Termo
  const [produtosPortfolio, setProdutosPortfolio] = useState<{ value: string; label: string }[]>([]);

  // Cascata: classes filtradas pela área selecionada
  const classesForArea = useMemo(() => {
    if (!selectedArea) return tiposProdutoDisponiveis;
    const area = areasData.find((a: Record<string, unknown>) => a.id === selectedArea);
    if (!area?.classes) return [];
    return (area.classes as Record<string, unknown>[]).map((c: Record<string, unknown>) => ({
      value: String(c.id ?? ""),
      label: String(c.nome ?? ""),
    }));
  }, [selectedArea, areasData, tiposProdutoDisponiveis]);

  // Cascata: subclasses filtradas pela classe selecionada
  const subclassesForClasse = useMemo(() => {
    if (!selectedClasse) return [];
    for (const area of areasData) {
      const classes = (area as Record<string, unknown>).classes as Record<string, unknown>[] | undefined;
      if (classes) {
        const cls = classes.find((c: Record<string, unknown>) => c.id === selectedClasse);
        if (cls?.subclasses) {
          return (cls.subclasses as Record<string, unknown>[]).map((s: Record<string, unknown>) => ({
            value: String(s.id ?? ""),
            label: String(s.nome ?? ""),
          }));
        }
      }
    }
    return [];
  }, [selectedClasse, areasData]);

  // Áreas como options para select
  const areasOptions = useMemo(() => {
    return areasData.map((a: Record<string, unknown>) => ({
      value: String(a.id ?? ""),
      label: String(a.nome ?? ""),
    }));
  }, [areasData]);

  // Carrega monitoramentos, fontes, dispensas e parametros ao montar
  useEffect(() => {
    carregarMonitoramentos();
    carregarDispensas();
    carregarDispensaStats();
    // Carregar fontes de editais do banco
    (async () => {
      try {
        const res = await crudList("fontes-editais", { limit: 50 });
        const items = res.items as Record<string, unknown>[];
        // CV01-1 (Arnaldo Sprint 2 V8): deduplicar tambem variantes (PNCP /
        // PNCP Portal / PNCP - Portal Nacional) colapsando para a familia.
        const vistos = new Set<string>();
        const opcoes: { value: string; label: string }[] = [];
        const familia = (n: string) => {
          const x = n.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").trim();
          if (x.includes("pncp")) return "pncp";
          if (x.includes("comprasnet") || x.includes("compras gov") || x.includes("compras.gov")) return "comprasnet";
          if (x.includes("bec")) return "bec";
          if (x.includes("licitacoes-e") || x.includes("licitacoese") || x.includes("bb licit")) return "licitacoes-e";
          return x;
        };
        for (const f of items) {
          if (!f.ativo) continue;
          const nome = String(f.nome ?? "").trim();
          const chave = familia(nome);
          if (chave && !vistos.has(chave)) {
            vistos.add(chave);
            opcoes.push({ value: String(f.id), label: nome });
          }
        }
        opcoes.sort((a, b) => a.label.localeCompare(b.label));
        setFontesDisponiveis(opcoes);
      } catch {
        // Fallback vazio
      }
    })();
    // Carregar produtos do portfólio para o select de Termo
    (async () => {
      try {
        const res = await crudList("produtos", { limit: 100 });
        const items = res.items as Record<string, unknown>[];
        setProdutosPortfolio(items.map(p => ({
          value: String(p.nome ?? ""),
          label: String(p.nome ?? ""),
        })));
      } catch { /* silencioso */ }
    })();
    // Carregar modalidades do banco
    (async () => {
      try {
        const token = localStorage.getItem("editais_ia_access_token");
        const res = await fetch("/api/modalidades", {
          headers: { Authorization: token ? `Bearer ${token}` : "" },
        });
        if (res.ok) {
          const data = await res.json();
          if (data.success && Array.isArray(data.items)) {
            setModalidadesDisponiveis(data.items.map((m: Record<string, unknown>) => ({
              value: String(m.nome ?? ""),
              label: String(m.nome ?? ""),
              id: String(m.id ?? ""),
            })));
          }
        }
      } catch { /* silencioso */ }
    })();
    // Carregar origens do banco
    (async () => {
      try {
        const token = localStorage.getItem("editais_ia_access_token");
        const res = await fetch("/api/origens", {
          headers: { Authorization: token ? `Bearer ${token}` : "" },
        });
        if (res.ok) {
          const data = await res.json();
          if (data.success && Array.isArray(data.items)) {
            setOrigensDisponiveis(data.items.map((o: Record<string, unknown>) => ({
              value: String(o.nome ?? ""),
              label: String(o.nome ?? ""),
            })));
          }
        }
      } catch { /* silencioso */ }
    })();
    // Carregar áreas, classes e subclasses do banco (hierarquia completa)
    (async () => {
      try {
        const token = localStorage.getItem("editais_ia_access_token");
        const res = await fetch("/api/areas-produto", {
          headers: { Authorization: token ? `Bearer ${token}` : "" },
        });
        if (res.ok) {
          const data = await res.json();
          if (data.success && Array.isArray(data.items)) {
            setAreasData(data.items);
            // Tipos produto flat (para compatibilidade)
            const tipos: { value: string; label: string }[] = [];
            for (const area of data.items) {
              const classes = (area as Record<string, unknown>).classes as Record<string, unknown>[] | undefined;
              if (classes) {
                for (const cls of classes) {
                  tipos.push({ value: String(cls.nome ?? ""), label: String(cls.nome ?? "") });
                }
              }
            }
            setTiposProdutoDisponiveis(tipos);
            // Pre-fill area com area_padrao da empresa
            if (empresa?.area_padrao_id) {
              setSelectedArea(empresa.area_padrao_id);
            }
          }
        }
      } catch { /* silencioso */ }
    })();
    // RF-013: Carregar classes de produto v2 para filtro local
    (async () => {
      try {
        const res = await crudList("classes-produto-v2", { limit: 200 });
        const items = res.items as Record<string, unknown>[];
        setClassesV2(items.map(c => ({
          value: String(c.id ?? ""),
          label: String(c.nome ?? ""),
        })));
      } catch { /* silencioso */ }
    })();
    // C1: Carregar estados de atuacao para calculo de score comercial
    (async () => {
      try {
        const paramRes = await crudList("parametros-score", { limit: 1 });
        const estados = paramRes.items[0]?.estados_atuacao;
        if (Array.isArray(estados)) {
          setEstadosAtuacao(estados as string[]);
        }
      } catch {
        // Silencioso - usara fallback score=20
      }
    })();
  }, []);

  // --- Dispensas handlers ---
  const carregarDispensaStats = useCallback(async () => {
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      const res = await fetch("/api/dashboard/dispensas", {
        headers: { Authorization: token ? `Bearer ${token}` : "" },
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success || data.cards || data.stats) {
          const s = data.cards || data.stats || data;
          setDispensaStats({
            abertas: Number(s.abertas ?? 0),
            cotacao_enviada: Number(s.cotacao_enviada ?? 0),
            adjudicadas: Number(s.adjudicadas ?? 0),
            encerradas: Number(s.encerradas ?? 0),
          });
        }
      }
    } catch {
      // Silencioso
    }
  }, []);

  const carregarDispensas = useCallback(async () => {
    setDispensasLoading(true);
    setDispensasErro(null);
    try {
      const res = await crudList("dispensas", { limit: 200 });
      const items = (res.items || []) as Record<string, unknown>[];
      setDispensas(items.map(d => ({
        id: String(d.id ?? ""),
        numero: String(d.numero ?? ""),
        orgao: String(d.orgao ?? ""),
        uf: String(d.uf ?? ""),
        artigo: String(d.artigo ?? ""),
        objeto: String(d.objeto ?? ""),
        valor: Number(d.valor ?? d.valor_estimado ?? 0),
        valor_limite: d.valor_limite != null ? Number(d.valor_limite) : undefined,
        prazo_dias: (() => {
          const enc = String(d.data_encerramento ?? d.data_abertura ?? "");
          return calcularDiasRestantes(enc);
        })(),
        status: (String(d.status ?? "aberta")) as DispensaItem["status"],
        data_publicacao: d.data_publicacao ? String(d.data_publicacao) : undefined,
        data_encerramento: d.data_encerramento ? String(d.data_encerramento) : undefined,
      })));
    } catch (e) {
      setDispensasErro(e instanceof Error ? e.message : "Erro ao carregar dispensas");
    } finally {
      setDispensasLoading(false);
    }
  }, []);

  const handleBuscarDispensasPNCP = async () => {
    if (!dispBuscaTermo.trim()) {
      setDispensasErro("Informe um termo de busca");
      return;
    }
    setDispBuscaLoading(true);
    setDispensasErro(null);
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      const res = await fetch("/api/dispensas/buscar", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: token ? `Bearer ${token}` : "",
        },
        body: JSON.stringify({
          termo: dispBuscaTermo.trim(),
          uf: dispBuscaUf.trim() || undefined,
          dias_busca: Number(dispBuscaDias) || 90,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          // Reload the list after search populates the DB
          await carregarDispensas();
          await carregarDispensaStats();
        } else {
          setDispensasErro(data.error || "Busca sem resultados");
        }
      } else {
        const err = await res.json().catch(() => ({}));
        setDispensasErro((err as Record<string, string>).error || "Erro ao buscar dispensas");
      }
    } catch (e) {
      setDispensasErro(e instanceof Error ? e.message : "Erro ao buscar dispensas");
    } finally {
      setDispBuscaLoading(false);
    }
  };

  const handleGerarCotacao = async (dispensaId: string) => {
    setCotacaoDispensaId(dispensaId);
    setCotacaoLoading(true);
    setCotacaoResult(null);
    setCotacaoModalOpen(true);
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      const res = await fetch(`/api/dispensas/${dispensaId}/cotacao`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: token ? `Bearer ${token}` : "",
        },
      });
      const data = await res.json();
      setCotacaoResult(data as DispensaCotacaoResult);
      if (data.success) {
        await carregarDispensas();
        await carregarDispensaStats();
      }
    } catch (e) {
      setCotacaoResult({
        success: false,
        error: e instanceof Error ? e.message : "Erro ao gerar cotacao",
      });
    } finally {
      setCotacaoLoading(false);
    }
  };

  const handleAtualizarStatusDispensa = async (dispensaId: string, novoStatus: string) => {
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      const res = await fetch(`/api/dispensas/${dispensaId}/status`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: token ? `Bearer ${token}` : "",
        },
        body: JSON.stringify({ status: novoStatus }),
      });
      if (res.ok) {
        setStatusUpdateId(null);
        await carregarDispensas();
        await carregarDispensaStats();
      } else {
        const err = await res.json().catch(() => ({}));
        alert((err as Record<string, string>).error || "Erro ao atualizar status");
      }
    } catch {
      alert("Erro ao atualizar status da dispensa");
    }
  };

  // Dispensas filtered list
  const dispensasFiltradas = useMemo(() => {
    let lista = dispensas;
    if (dispFiltroArtigo) {
      lista = lista.filter(d => d.artigo === dispFiltroArtigo);
    }
    if (dispFiltroValorMin) {
      const min = Number(dispFiltroValorMin);
      if (!isNaN(min)) lista = lista.filter(d => d.valor >= min);
    }
    if (dispFiltroValorMax) {
      const max = Number(dispFiltroValorMax);
      if (!isNaN(max)) lista = lista.filter(d => d.valor <= max);
    }
    if (dispFiltroUf.trim()) {
      const ufF = dispFiltroUf.trim().toUpperCase();
      lista = lista.filter(d => d.uf.toUpperCase().includes(ufF));
    }
    if (dispFiltroOrgao.trim()) {
      const orgF = dispFiltroOrgao.trim().toLowerCase();
      lista = lista.filter(d => d.orgao.toLowerCase().includes(orgF));
    }
    return lista;
  }, [dispensas, dispFiltroArtigo, dispFiltroValorMin, dispFiltroValorMax, dispFiltroUf, dispFiltroOrgao]);

  // Dispensas table columns
  const dispensasColumns: Column<DispensaItem>[] = useMemo(() => [
    { key: "numero", header: "Numero", sortable: true, width: "120px" },
    {
      key: "orgao",
      header: "Orgao",
      sortable: true,
      render: (d) => (
        <span title={d.orgao}>
          {d.orgao.length > 35 ? d.orgao.substring(0, 35) + "..." : d.orgao}
        </span>
      ),
    },
    { key: "uf", header: "UF", width: "50px" },
    { key: "artigo", header: "Artigo", width: "80px", sortable: true },
    {
      key: "objeto",
      header: "Objeto",
      render: (d) => (
        <span title={d.objeto}>
          {d.objeto.length > 45 ? d.objeto.substring(0, 45) + "..." : d.objeto}
        </span>
      ),
    },
    {
      key: "valor",
      header: "Valor",
      width: "120px",
      sortable: true,
      render: (d) => (
        <span>
          {formatCurrency(d.valor)}
          {d.valor_limite && d.valor > d.valor_limite && (
            <span style={{
              display: "inline-block",
              marginLeft: "6px",
              padding: "1px 5px",
              fontSize: "10px",
              fontWeight: 700,
              color: "#fbbf24",
              backgroundColor: "#78350f",
              border: "1px solid #92400e",
              borderRadius: "3px",
              whiteSpace: "nowrap",
            }}>
              RN-NEW-07
            </span>
          )}
        </span>
      ),
    },
    {
      key: "prazo_dias",
      header: "Prazo",
      width: "80px",
      sortable: true,
      render: (d) => {
        if (d.status === "encerrada") return <StatusBadge status="neutral" label="Encerrada" size="small" />;
        if (d.prazo_dias < 5) return <StatusBadge status="error" label={`${d.prazo_dias}d`} size="small" />;
        if (d.prazo_dias <= 15) return <StatusBadge status="warning" label={`${d.prazo_dias}d`} size="small" />;
        return <StatusBadge status="success" label={`${d.prazo_dias}d`} size="small" />;
      },
    },
    {
      key: "status",
      header: "Status",
      width: "120px",
      sortable: true,
      render: (d) => {
        const statusMap: Record<string, { status: "success" | "warning" | "error" | "neutral"; label: string }> = {
          aberta: { status: "success", label: "Aberta" },
          cotacao_enviada: { status: "warning", label: "Cotacao Env." },
          adjudicada: { status: "success", label: "Adjudicada" },
          encerrada: { status: "neutral", label: "Encerrada" },
        };
        const s = statusMap[d.status] || { status: "neutral" as const, label: d.status };
        return <StatusBadge status={s.status} label={s.label} size="small" />;
      },
    },
    {
      key: "acoes" as keyof DispensaItem,
      header: "Acoes",
      width: "160px",
      render: (d) => (
        <div style={{ display: "flex", gap: "4px", flexWrap: "wrap" }}>
          {d.status !== "encerrada" && (
            <button
              title="Gerar Cotacao"
              onClick={(ev) => { ev.stopPropagation(); handleGerarCotacao(d.id); }}
              style={{
                padding: "3px 8px", fontSize: "11px", border: "1px solid #334155",
                borderRadius: "4px", backgroundColor: "transparent", color: "#60a5fa",
                cursor: "pointer", display: "flex", alignItems: "center", gap: "3px",
              }}
            >
              <Send size={12} /> Cotacao
            </button>
          )}
          {DISPENSA_STATUS_TRANSITIONS[d.status]?.length > 0 && (
            <div style={{ position: "relative" }}>
              <button
                title="Atualizar Status"
                onClick={(ev) => { ev.stopPropagation(); setStatusUpdateId(statusUpdateId === d.id ? null : d.id); }}
                style={{
                  padding: "3px 8px", fontSize: "11px", border: "1px solid #334155",
                  borderRadius: "4px", backgroundColor: "transparent", color: "#94a3b8",
                  cursor: "pointer", display: "flex", alignItems: "center", gap: "3px",
                }}
              >
                <RefreshCw size={12} /> Status
              </button>
              {statusUpdateId === d.id && (
                <div style={{
                  position: "absolute", top: "100%", right: 0, zIndex: 50,
                  background: "#1e293b", border: "1px solid #334155", borderRadius: "6px",
                  minWidth: "150px", marginTop: "2px", boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
                }}>
                  {DISPENSA_STATUS_TRANSITIONS[d.status].map(t => (
                    <div
                      key={t.value}
                      onClick={(ev) => { ev.stopPropagation(); handleAtualizarStatusDispensa(d.id, t.value); }}
                      style={{
                        padding: "6px 10px", cursor: "pointer", fontSize: "12px",
                        color: "#e2e8f0", borderBottom: "1px solid #1e293b",
                      }}
                      onMouseEnter={(ev) => (ev.currentTarget.style.background = "#334155")}
                      onMouseLeave={(ev) => (ev.currentTarget.style.background = "transparent")}
                    >
                      {t.label}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      ),
    },
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ], [statusUpdateId]);

  const carregarMonitoramentos = async () => {
    setLoadingMonitoramentos(true);
    try {
      const res = await crudList("monitoramentos", { limit: 10 });
      const items = res.items as Record<string, unknown>[];
      setMonitoramentos(items.map(m => ({
        id: String(m.id ?? ""),
        termo: String(m.termo ?? ""),
        ncm: m.ncm ? String(m.ncm) : undefined,
        fontes: m.fontes as string[] | undefined,
        ufs: m.ufs as string[] | undefined,
        incluir_encerrados: Boolean(m.incluir_encerrados ?? false),
        valor_minimo: m.valor_minimo ? Number(m.valor_minimo) : undefined,
        valor_maximo: m.valor_maximo ? Number(m.valor_maximo) : undefined,
        frequencia_horas: Number(m.frequencia_horas ?? 24),
        score_minimo_alerta: m.score_minimo_alerta ? Number(m.score_minimo_alerta) : undefined,
        ativo: Boolean(m.ativo ?? true),
        ultimo_check: m.ultima_execucao ? formatarDataBr(String(m.ultima_execucao)) : undefined,
        editais_encontrados: Number(m.editais_encontrados ?? 0),
      })));
    } catch {
      // Silencioso - monitoramentos são opcionais
    } finally {
      setLoadingMonitoramentos(false);
    }
  };

  // T13: Busca real via REST
  const handleBuscar = async () => {
    // Prioridade: Tipo Produto > Termo digitado/selecionado
    let termoBusca = "";
    if (classificacaoTipo !== "todos") {
      // Tipo Produto selecionado → busca abrangente pelo tipo
      termoBusca = classificacaoTipo.toLowerCase();
      // Se subclasse selecionada, refinar o termo de busca
      if (selectedSubclasse) {
        const sub = subclassesForClasse.find(s => s.value === selectedSubclasse);
        if (sub) {
          termoBusca = sub.label.toLowerCase();
        }
      }
    } else {
      termoBusca = termo.trim();
    }
    if (!termoBusca) {
      setErro("Informe um termo de busca ou selecione um Tipo Produto");
      return;
    }
    setLoading(true);
    setErro(null);
    setErrosFontes(null);
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      // CV01-2a (Arnaldo Sprint 2 V8): NCM nao eh filtro estruturado no backend.
      // Antes era concatenado no termo ('foo NCM 90230000') e zerava a busca
      // porque o PNCP search nao indexa NCM no texto. Agora apenas avisamos.
      if (ncm.trim()) {
        setErrosFontes(prev => ([...(prev || []), `Filtro NCM "${ncm.trim()}" foi ignorado (ainda nao suportado pelo PNCP search). Refine seu termo se quiser limitar resultados.`]));
      }
      const params = new URLSearchParams({
        termo: termoBusca,
        tipoScore: tipoScore,
        incluirEncerrados: String(incluirEncerrados),
        limite: "2000",
        diasBusca: diasBusca,
      });
      if (tipoScore === "hibrido" || tipoScore === "profundo") {
        params.append("limiteScoreProfundo", String(limiteScoreProfundo));
      }
      if (uf !== "todas") params.append("uf", uf);
      if (fonte !== "todas") params.append("fonte", fonte);
      if (modalidadeFiltro !== "todos") params.append("modalidade", modalidadeFiltro);
      if (classificacaoTipo !== "todos") params.append("tipoProduto", classificacaoTipo);
      if (classificacaoOrigem !== "todos") params.append("origem", classificacaoOrigem);

      const res = await fetch(`/api/editais/buscar?${params}`, {
        headers: { Authorization: token ? `Bearer ${token}` : "" },
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error((err as Record<string, string>).error || "Erro ao buscar editais");
      }

      const data = await res.json() as { success: boolean; editais?: Record<string, unknown>[]; error?: string; erros?: string[] | null; total_resultados?: number };

      if (!data.success) {
        throw new Error(data.error || "Erro ao buscar editais");
      }

      // CV01-6 (Arnaldo Sprint 2 V8): expor avisos de fontes indisponiveis para o usuario
      if (data.erros && data.erros.length > 0) {
        setErrosFontes(prev => ([...(prev || []), ...data.erros!]));
      }

      const editais = (data.editais ?? []).map(e => normalizarEditalDaBusca(e, estadosAtuacao));

      // Cruzar com editais já salvos para indicar "Já salvo"
      try {
        const resSalvos = await fetch("/api/editais/salvos?per_page=500&com_estrategia=true", {
          headers: { Authorization: token ? `Bearer ${token}` : "" },
        });
        if (resSalvos.ok) {
          const dataSalvos = await resSalvos.json();
          const salvos = (dataSalvos.editais || []) as Record<string, unknown>[];
          for (const ed of editais) {
            const match = salvos.find((s) =>
              String(s.numero) === ed.numero && String(s.orgao) === ed.orgao
            );
            if (match) {
              ed.editalSalvoId = String(match.id);
              // Restaurar estratégia salva
              if (match.estrategia_id) {
                ed.estrategiaId = String(match.estrategia_id);
              }
              // Recuperar intenção original da justificativa (formato: "Intenção: estrategico")
              const justif = String(match.justificativa_estrategia || "");
              const intMatch = justif.match(/Inten[çc][aã]o:\s*(\w+)/i);
              if (intMatch) {
                const intVal = intMatch[1].toLowerCase();
                if (["estrategico", "defensivo", "acompanhamento", "aprendizado"].includes(intVal)) {
                  ed.intencaoEstrategica = intVal as typeof ed.intencaoEstrategica;
                }
              } else {
                // Fallback: mapeamento inverso decisao → intenção
                const decisao = String(match.decisao || "");
                const prioridade = String(match.prioridade || "");
                const inversoMap: Record<string, typeof ed.intencaoEstrategica> = {
                  go: "estrategico",
                  acompanhar: prioridade === "media" ? "defensivo" : "acompanhamento",
                  nogo: "aprendizado",
                };
                if (decisao && inversoMap[decisao]) {
                  ed.intencaoEstrategica = inversoMap[decisao];
                }
              }
              if (match.margem_desejada != null && Number(match.margem_desejada) > 0) {
                ed.margemExpectativa = Number(match.margem_desejada);
              }
            }
          }
        }
      } catch { /* silencioso */ }

      setResultados(editais);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Erro ao buscar editais");
      setResultados([]);
    } finally {
      setLoading(false);
    }
  };

  // T14: Salvar edital via CRUD
  const salvarEditalNoBanco = async (edital: EditalBusca): Promise<string | null> => {
    try {
      // Buscar modalidade_id da tabela ModalidadeLicitacao
      const modNome = edital.modalidade && edital.modalidade !== "—" ? edital.modalidade : "";
      const modMatch = modalidadesDisponiveis.find(m =>
        m.value.toLowerCase().replace(/[^a-z]/g, "").includes(modNome.toLowerCase().replace(/[^a-z]/g, "")) ||
        modNome.toLowerCase().replace(/[^a-z]/g, "").includes(m.value.toLowerCase().replace(/[^a-z]/g, ""))
      );
      const modalidade_id = modMatch?.id || null;

      const payload: Record<string, unknown> = {
        numero: edital.numero,
        orgao: edital.orgao,
        orgao_tipo: edital.orgaoTipo || "municipal",
        uf: edital.uf !== "—" ? edital.uf : null,
        objeto: edital.objeto,
        modalidade_id,
        valor_referencia: edital.valor || null,
        data_abertura: (() => {
          // Converter DD/MM/YYYY para YYYY-MM-DD para o MySQL
          const d = edital.dataAbertura;
          if (!d || d === "—") return null;
          if (d.includes("/")) {
            const [dia, mes, ano] = d.split("/");
            return `${ano}-${mes}-${dia}`;
          }
          return d; // Já em formato ISO
        })(),
        status: "novo",
        fonte: edital.fonte || "pncp",
        url: edital.url || (edital.cnpj_orgao && edital.ano_compra && edital.seq_compra
          ? `https://pncp.gov.br/app/editais/${edital.cnpj_orgao}/${edital.ano_compra}/${edital.seq_compra}`
          : null),
        cnpj_orgao: edital.cnpj_orgao || null,
        ano_compra: edital.ano_compra || null,
        seq_compra: edital.seq_compra || null,
        pdf_url: edital.cnpj_orgao && edital.ano_compra && edital.seq_compra
          ? `https://pncp.gov.br/pncp-api/v1/orgaos/${edital.cnpj_orgao}/compras/${edital.ano_compra}/${edital.seq_compra}/arquivos/1`
          : null,
      };
      // Se já tem ID do backend (UUID), reutiliza (não duplica)
      let editalId: string | null = null;
      if (edital.id && edital.id.length === 36) {
        // Promover de temp_score para novo + ATUALIZAR campos PNCP (cnpj/ano/seq podem ter
        // ficado vazios no salvamento temp). Envia payload completo, não só status.
        try { await crudUpdate("editais", edital.id, payload); } catch { /* ignora se não existe */ }
        editalId = edital.id;
      }
      if (!editalId) {
        // Verificar se já existe um edital temp_score com mesmo número+órgão
        try {
          const existentes = await crudList("editais", { q: edital.numero });
          const tempExistente = (existentes.items || []).find(
            (e: Record<string, unknown>) => e.numero === edital.numero && e.orgao === edital.orgao
          );
          if (tempExistente) {
            editalId = String(tempExistente.id);
            await crudUpdate("editais", editalId, payload);
          }
        } catch { /* ignora — cria novo */ }
      }
      if (!editalId) {
        const criado = await crudCreate("editais", payload);
        editalId = String(criado.id ?? "");
      }

      // P1: Salvar itens do edital no banco (alimenta aba Lotes na Validação)
      if (editalId && edital.itens && edital.itens.length > 0) {
        // Itens vieram na busca — salvar via CRUD
        for (const item of edital.itens) {
          try {
            await crudCreate("editais-itens", {
              edital_id: editalId,
              numero_item: item.numero_item ?? null,
              descricao: item.descricao || "",
              quantidade: item.quantidade ?? null,
              unidade_medida: item.unidade_medida || null,
              valor_unitario_estimado: item.valor_unitario_estimado ?? null,
              valor_total_estimado: item.valor_total_estimado ?? null,
            });
          } catch { /* ignora duplicatas */ }
        }
      } else if (editalId && edital.cnpj_orgao && edital.ano_compra && edital.seq_compra) {
        // Itens não vieram na busca — buscar direto do PNCP
        try {
          const token = localStorage.getItem("editais_ia_access_token");
          await fetch(`/api/editais/${editalId}/buscar-itens-pncp`, {
            method: "POST",
            headers: { Authorization: token ? `Bearer ${token}` : "" },
          });
        } catch { /* silencioso */ }
      }

      // P2: Salvar scores da Captação (evita recálculo na Validação)
      if (editalId && (edital.scoreProfundo || edital.score > 0)) {
        try {
          const token = localStorage.getItem("editais_ia_access_token");
          const scorePayload = edital.scoreProfundo ? {
            edital_id: editalId,
            score_tecnico: edital.scoreProfundo.scores.tecnico,
            score_documental: edital.scoreProfundo.scores.documental,
            score_complexidade: edital.scoreProfundo.scores.complexidade,
            score_juridico: edital.scoreProfundo.scores.juridico,
            score_logistico: edital.scoreProfundo.scores.logistico,
            score_comercial: edital.scoreProfundo.scores.comercial,
            score_final: edital.scoreProfundo.score_geral,
            decisao: edital.scoreProfundo.decisao,
            justificativa: edital.scoreProfundo.justificativa,
            pontos_positivos: edital.scoreProfundo.pontos_positivos,
            pontos_atencao: edital.scoreProfundo.pontos_atencao,
          } : {
            // Score rápido (sem profundo) — salva técnico + comercial
            edital_id: editalId,
            score_tecnico: edital.scores.tecnico,
            score_comercial: edital.scores.comercial,
            score_final: edital.score,
            decisao: edital.recomendacaoTexto === "PARTICIPAR" ? "GO" : edital.recomendacaoTexto === "NAO PARTICIPAR" ? "NO-GO" : "AVALIAR",
            justificativa: edital.justificativa || "",
          };
          const scoreResp = await fetch("/api/editais/salvar-scores-captacao", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: token ? `Bearer ${token}` : "",
            },
            body: JSON.stringify(scorePayload),
          });
          const scoreResult = await scoreResp.json().catch(() => ({}));
          console.log("[SALVAR-SCORES]", scoreResp.status, scoreResult);
        } catch (err) { console.error("[SALVAR-SCORES] erro:", err); }
      }

      return editalId;
    } catch {
      return null;
    }
  };

  const handleBaixarPdfEdital = async (editalId: string, nomeEdital: string) => {
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      const resp = await fetch(`/api/editais/${editalId}/pdf?download=true`, {
        headers: { Authorization: token ? `Bearer ${token}` : "" },
      });
      if (resp.ok) {
        const blob = await resp.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `edital_${nomeEdital.replace(/[^a-zA-Z0-9]/g, "_")}.pdf`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
      } else {
        alert("PDF não disponível para download neste edital.");
      }
    } catch {
      alert("Erro ao baixar PDF do edital.");
    }
  };

  const handleSalvarEdital = async (edital: EditalBusca) => {
    const editalId = await salvarEditalNoBanco(edital);
    if (!editalId) {
      alert("Erro ao salvar edital");
      return;
    }
    // Atualiza ID local
    setResultados(prev => prev.map(e =>
      e.id === edital.id ? { ...e, editalSalvoId: editalId } : e
    ));
    if (painelEdital?.id === edital.id) {
      setPainelEdital(prev => prev ? { ...prev, editalSalvoId: editalId } : prev);
    }

    // Perguntar se deseja baixar o PDF do edital
    const hasPncpData = edital.cnpj_orgao && edital.ano_compra && edital.seq_compra;
    if (hasPncpData && window.confirm("Edital salvo! Deseja baixar o PDF do edital?")) {
      await handleBaixarPdfEdital(editalId, edital.numero);
    }
  };

  // CV03-13 (Arnaldo Sprint 2 V8): salvar em LOTE agora atualiza o badge
  // 'salvo' de cada item (antes so o handler individual fazia setResultados;
  // o lote só dava alert e os boxes seguiam oferecendo salvar de novo).
  const _setSalvoLocal = (mapaIds: Record<string, string>) => {
    if (!mapaIds || Object.keys(mapaIds).length === 0) return;
    setResultados(prev => prev.map(e => mapaIds[e.id] ? { ...e, editalSalvoId: mapaIds[e.id] } : e));
    if (painelEdital && mapaIds[painelEdital.id]) {
      setPainelEdital(prev => prev ? { ...prev, editalSalvoId: mapaIds[prev.id] } : prev);
    }
  };

  const handleSalvarTodos = async () => {
    const naoSalvos = resultados.filter(e => !e.editalSalvoId);
    const mapa: Record<string, string> = {};
    for (const edital of naoSalvos) {
      const id = await salvarEditalNoBanco(edital);
      if (id) mapa[edital.id] = id;
    }
    _setSalvoLocal(mapa);
    alert(Object.keys(mapa).length > 0 ? `${Object.keys(mapa).length} edital(is) salvo(s)` : "Todos os editais ja estao salvos");
  };

  const handleSalvarRecomendados = async () => {
    const recomendados = resultados.filter(e => e.score >= 70 && !e.editalSalvoId);
    const mapa: Record<string, string> = {};
    for (const edital of recomendados) {
      const id = await salvarEditalNoBanco(edital);
      if (id) mapa[edital.id] = id;
    }
    _setSalvoLocal(mapa);
    alert(Object.keys(mapa).length > 0 ? `${Object.keys(mapa).length} edital(is) recomendado(s) salvo(s)` : "Todos os recomendados ja estao salvos");
  };

  // T15: Persistir intenção estratégica e margem
  const handleSalvarEstrategia = async () => {
    if (!painelEdital) return;
    setSalvandoEstrategia(true);
    setEstrategiaSalva(false);
    try {
      // Garante que o edital está salvo primeiro
      let editalId = painelEdital.editalSalvoId || (painelEdital.id.length === 36 ? painelEdital.id : null);
      if (!editalId) {
        editalId = await salvarEditalNoBanco(painelEdital);
      }
      if (!editalId) throw new Error("Não foi possível salvar o edital");

      // Mapa intenção -> decisao/prioridade do modelo
      const decisaoMap: Record<string, string> = {
        estrategico: "go",
        defensivo: "acompanhar",
        acompanhamento: "acompanhar",
        aprendizado: "nogo",
      };
      const prioridadeMap: Record<string, string> = {
        estrategico: "alta",
        defensivo: "media",
        acompanhamento: "baixa",
        aprendizado: "baixa",
      };

      const payload: Record<string, unknown> = {
        edital_id: editalId,
        decisao: decisaoMap[intencaoLocal] ?? "acompanhar",
        prioridade: prioridadeMap[intencaoLocal] ?? "media",
        margem_desejada: margemLocal,
        justificativa: `Intenção: ${intencaoLocal}`,
      };

      let estrategiaId = painelEdital.estrategiaId;

      // Se não tem estrategiaId, buscar se já existe uma para este edital
      if (!estrategiaId) {
        try {
          const existentes = await crudList("estrategias-editais", { q: editalId ?? "" });
          const existente = existentes.items.find((e: Record<string, unknown>) => String(e.edital_id) === editalId);
          if (existente) {
            estrategiaId = String(existente.id);
          }
        } catch { /* ignorar erro de busca */ }
      }

      // CV04-15 (Arnaldo Sprint 2 V8): persistir tambem intencaoEstrategica e
      // margemExpectativa no estado, p/ que ao REABRIR o painel sem recarregar
      // os valores recem-salvos apareçam (antes so 'aparecia' após sair/voltar).
      const _patch = { estrategiaId: undefined as string | undefined, editalSalvoId: editalId ?? undefined,
                        intencaoEstrategica: intencaoLocal, margemExpectativa: margemLocal };
      if (estrategiaId) {
        await crudUpdate("estrategias-editais", estrategiaId, payload);
        _patch.estrategiaId = estrategiaId;
      } else {
        const criada = await crudCreate("estrategias-editais", payload);
        _patch.estrategiaId = String(criada.id ?? "");
      }
      setResultados(prev => prev.map(e =>
        e.id === painelEdital.id ? { ...e, ..._patch } : e
      ));
      setPainelEdital(prev => prev ? { ...prev, ..._patch } : prev);
      setEstrategiaSalva(true);
      setTimeout(() => setEstrategiaSalva(false), 3000);
    } catch (e) {
      alert("Erro ao salvar estratégia: " + (e instanceof Error ? e.message : ""));
    } finally {
      setSalvandoEstrategia(false);
    }
  };

  // C2: Buscar scores de validacao (gaps reais) via endpoint
  const fetchScoresValidacao = async (editalId: string) => {
    // Precisa de UUID completo (36 chars) para chamar o endpoint
    if (!editalId || editalId.length !== 36) {
      setScoresValidacao(null);
      return;
    }
    setLoadingScores(true);
    setScoresValidacao(null);
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      const res = await fetch(`/api/editais/${editalId}/scores-validacao`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: token ? `Bearer ${token}` : "",
        },
        body: JSON.stringify({}),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          setScoresValidacao(data);
        }
      }
    } catch {
      // Silencioso - scores sao opcionais
    } finally {
      setLoadingScores(false);
    }
  };

  // Score profundo sob demanda: salva edital temp no backend e calcula
  const fetchScoreProfundoSobDemanda = async (edital: EditalBusca) => {
    setLoadingScores(true);
    setScoresValidacao(null);
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      const res = await fetch("/api/editais/score-profundo-sob-demanda", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: token ? `Bearer ${token}` : "",
        },
        body: JSON.stringify({
          numero: edital.numero,
          orgao: edital.orgao,
          objeto: edital.objeto,
          uf: edital.uf,
          modalidade: edital.modalidade,
          valor_estimado: edital.valor || undefined,
          fonte: edital.fonte,
          url: edital.url,
          data_abertura: edital.dataAbertura || undefined,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.success) {
          setScoresValidacao(data);
          // Atualizar o edital com o ID temporário para futuras chamadas
          if (data.edital_id_temp) {
            edital.editalSalvoId = data.edital_id_temp;
          }
          // Propagar score profundo de volta ao array de resultados
          // para que o relatório MD/PDF use dados atualizados
          const sp = data.scores || data;
          const scoreProfundoObj = {
            scores: {
              tecnico: Number(sp.score_tecnico ?? 0),
              documental: Number(sp.score_documental ?? 0),
              complexidade: Number(sp.score_complexidade ?? 0),
              juridico: Number(sp.score_juridico ?? 0),
              logistico: Number(sp.score_logistico ?? 0),
              comercial: Number(sp.score_comercial ?? 0),
            },
            score_geral: Number(sp.score_final ?? sp.score_geral ?? 0),
            decisao: String(sp.decisao ?? "AVALIAR"),
            justificativa: String(sp.justificativa ?? ""),
            pontos_positivos: (sp.pontos_positivos as string[]) || [],
            pontos_atencao: (sp.pontos_atencao as string[]) || [],
          };
          const scoreGeralAtualizado = Math.round(scoreProfundoObj.score_geral);
          setResultados(prev => prev.map(e =>
            e.id === edital.id ? {
              ...e,
              scoreProfundo: scoreProfundoObj,
              score: scoreGeralAtualizado > 0 ? scoreGeralAtualizado : e.score,
              editalSalvoId: data.edital_id_temp || e.editalSalvoId,
            } : e
          ));
          if (painelEdital?.id === edital.id) {
            setPainelEdital(prev => prev ? {
              ...prev,
              scoreProfundo: scoreProfundoObj,
              score: scoreGeralAtualizado > 0 ? scoreGeralAtualizado : prev.score,
              editalSalvoId: data.edital_id_temp || prev.editalSalvoId,
            } : prev);
          }
        }
      }
    } catch {
      // Silencioso
    } finally {
      setLoadingScores(false);
    }
  };

  const handleAbrirPainel = (edital: EditalBusca) => {
    setPainelEdital(edital);
    setIntencaoLocal(edital.intencaoEstrategica);
    setMargemLocal(edital.margemExpectativa);
    setEstrategiaSalva(false);
    // Se já tem score profundo do híbrido, não precisa buscar
    if (edital.scoreProfundo) {
      setScoresValidacao(null);
      setLoadingScores(false);
      return;
    }
    // C2: Lazy-load scores de validacao ao abrir o painel
    const editalId = edital.editalSalvoId || (edital.id.length === 36 ? edital.id : null);
    if (editalId) {
      fetchScoresValidacao(editalId);
    } else if (tipoScore !== "nenhum") {
      // Edital sem UUID e sem score profundo: calcular sob demanda
      fetchScoreProfundoSobDemanda(edital);
    } else {
      setScoresValidacao(null);
      setLoadingScores(false);
    }
  };

  const handleToggleSelect = (id: string) => {
    setResultados(resultados.map(e =>
      e.id === id ? { ...e, selected: !e.selected } : e
    ));
  };

  // Gerar MD do relatório a partir dos dados já processados (mesma fonte da tabela)
  const gerarRelatorioMD = (editais: EditalBusca[], termoB: string, fonteB: string, tipoScoreB: string): string => {
    const now = new Date();
    const dataHora = now.toLocaleString("pt-BR");
    const fmtVal = (v: number) => v ? new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(v) : "—";
    const esc = (s: string) => (s || "—").replace(/\|/g, "\\|").replace(/\n/g, " ");
    const prazoLabel = (e: EditalBusca) => {
      if (e.status === "encerrado") return "Encerrado";
      if (e.diasRestantes <= 2) return `🔴 ${e.diasRestantes}d`;
      if (e.diasRestantes <= 5) return `🟡 ${e.diasRestantes}d`;
      return `${e.diasRestantes}d`;
    };
    const fonteLabel = fontesDisponiveis.find(f => f.value === fonteB)?.label || fonteB || "—";

    let md = `# Relatório Completo de Busca de Editais\n\n`;
    md += `**Data/Hora:** ${dataHora}  \n`;
    md += `**Termo de busca:** ${termoB || "—"}  \n`;
    md += `**Fonte:** ${fonteLabel}  \n`;
    md += `**Modo Score:** ${tipoScoreB}  \n`;
    md += `**Total de resultados:** ${editais.length}  \n\n`;
    md += `---\n\n`;

    // Ordenar por score decrescente (mesma ordem da tabela UI)
    const editaisOrdenados = [...editais].sort((a, b) => b.score - a.score);

    // Tabela resumo — mesmas colunas da tabela na UI
    md += `## Tabela Resumo\n\n`;
    md += `| # | Fonte | Numero | Orgao | UF | Modalidade | Objeto | Valor | Produto | Prazo | Score |\n`;
    md += `|---|---|---|---|---|---|---|---|---|---|---|\n`;
    editaisOrdenados.forEach((e, i) => {
      const fonteR = (e.fonte || "—").includes("PNCP") ? "PNCP" : (e.fonte || "—");
      const objetoResumo = e.objeto.length > 50 ? e.objeto.substring(0, 50) + "..." : e.objeto;
      md += `| ${i + 1} | ${fonteR} | ${esc(e.numero)} | ${esc(e.orgao.length > 40 ? e.orgao.substring(0, 40) + "..." : e.orgao)} | ${e.uf} | ${esc(e.modalidade || "—")} | ${esc(objetoResumo)} | ${fmtVal(e.valor)} | ${esc(e.produtoCorrespondente || "Nenhum")} | ${prazoLabel(e)} | **${e.score}/100** |\n`;
    });
    md += `\n---\n\n`;

    // Detalhe de cada edital (mesma ordem da tabela)
    md += `## Detalhes por Edital\n\n`;
    editaisOrdenados.forEach((e, i) => {
      md += `### ${i + 1}. ${e.numero} — ${e.orgao}\n\n`;

      md += `| Campo | Valor |\n`;
      md += `|---|---|\n`;
      md += `| **Numero** | ${esc(e.numero)} |\n`;
      md += `| **Orgao** | ${esc(e.orgao)} |\n`;
      md += `| **UF** | ${e.uf} |\n`;
      md += `| **Modalidade** | ${esc(e.modalidade || "—")} |\n`;
      md += `| **Fonte** | ${esc(e.fonte || "—")} |\n`;
      md += `| **Valor** | ${fmtVal(e.valor)} |\n`;
      md += `| **Abertura** | ${e.dataAbertura || "—"} |\n`;
      md += `| **Status** | ${e.status === "aberto" ? `🟢 Aberto (${e.diasRestantes}d)` : "⚫ Encerrado"} |\n`;
      md += `| **Produto Correspondente** | ${esc(e.produtoCorrespondente || "Nenhum")} |\n`;
      md += `| **Potencial de Ganho** | ${e.potencialGanho.charAt(0).toUpperCase() + e.potencialGanho.slice(1)} |\n`;
      if (e.url) {
        md += `| **Link Portal** | [Abrir no PNCP](${e.url}) |\n`;
      }
      md += `\n`;

      md += `**Objeto:**\n> ${esc(e.objeto)}\n\n`;

      if (e.justificativa) {
        md += `**Justificativa IA:**\n> ${esc(e.justificativa)}\n\n`;
      }

      if (e.recomendacaoTexto && e.recomendacaoTexto !== "0" && e.recomendacaoTexto !== "NaN") {
        const emoji = e.recomendacaoTexto === "PARTICIPAR" ? "🟢" : e.recomendacaoTexto === "AVALIAR" ? "🟡" : "🔴";
        md += `**Recomendação:** ${emoji} ${e.recomendacaoTexto}\n\n`;
      }

      if (tipoScoreB !== "nenhum") {
        md += `**Score Geral: ${e.score}/100**\n\n`;

        if (e.scoreProfundo) {
          const s = e.scoreProfundo.scores;
          const icon = (v: number) => v >= 70 ? "🟢" : v >= 40 ? "🟡" : "🔴";
          md += `#### 6 Dimensões de Score\n\n`;
          md += `| Dimensão | Score | Status |\n`;
          md += `|---|---|---|\n`;
          md += `| Técnico | ${s.tecnico}% | ${icon(s.tecnico)} |\n`;
          md += `| Documental | ${s.documental}% | ${icon(s.documental)} |\n`;
          md += `| Complexidade | ${s.complexidade}% | ${icon(s.complexidade)} |\n`;
          md += `| Jurídico | ${s.juridico}% | ${icon(s.juridico)} |\n`;
          md += `| Logístico | ${s.logistico}% | ${icon(s.logistico)} |\n`;
          md += `| Comercial | ${s.comercial}% | ${icon(s.comercial)} |\n`;
          md += `\n`;

          const dEmoji = e.scoreProfundo.decisao === "GO" ? "🟢" : e.scoreProfundo.decisao === "NO-GO" ? "🔴" : "🟡";
          md += `**Decisão: ${dEmoji} ${e.scoreProfundo.decisao}**\n`;
          if (e.scoreProfundo.justificativa) {
            md += `> ${esc(e.scoreProfundo.justificativa)}\n`;
          }
          md += `\n`;

          if (e.scoreProfundo.pontos_positivos.length > 0) {
            md += `**Pontos Positivos:**\n`;
            e.scoreProfundo.pontos_positivos.forEach(p => { md += `- ✅ ${esc(p)}\n`; });
            md += `\n`;
          }

          if (e.scoreProfundo.pontos_atencao.length > 0) {
            md += `**Pontos de Atenção:**\n`;
            e.scoreProfundo.pontos_atencao.forEach(p => { md += `- ⚠️ ${esc(p)}\n`; });
            md += `\n`;
          }
        } else {
          md += `| Métrica | Valor |\n`;
          md += `|---|---|\n`;
          md += `| Aderência Técnica | ${e.scores.tecnico}/100 |\n`;
          md += `| Aderência Comercial | ${e.scores.comercial}/100 |\n`;
          md += `\n`;
        }
      }

      if (e.itens && e.itens.length > 0) {
        md += `#### Itens do Edital (${e.itens.length})\n\n`;
        md += `| # | Descrição | Qtd | Valor Total |\n`;
        md += `|---|---|---|---|\n`;
        e.itens.forEach((item, idx) => {
          md += `| ${item.numero_item ?? idx + 1} | ${esc(item.descricao || "—")} | ${item.quantidade ?? "—"} | ${item.valor_total_estimado ? fmtVal(item.valor_total_estimado) : "—"} |\n`;
        });
        md += `\n`;
      }

      if (e.gaps && e.gaps.length > 0) {
        md += `#### Análise de Gaps\n\n`;
        e.gaps.forEach(g => {
          const gIcon = g.tipo === "atendido" ? "🟢" : g.tipo === "parcial" ? "🟡" : "🔴";
          md += `- ${gIcon} **${g.tipo.replace("_", " ")}**: ${esc(g.item)}\n`;
        });
        md += `\n`;
      }

      md += `---\n\n`;
    });

    return md;
  };

  // Regenerar relatório sempre que resultados mudam
  useEffect(() => {
    if (resultados.length > 0) {
      const editaisParaRelatorio = filtroClasseProduto === "todos" ? resultados : resultados.filter(e => e.classe_produto_id === filtroClasseProduto);
      setRelatorioMD(gerarRelatorioMD(editaisParaRelatorio, termo, fonte, tipoScore));
    } else {
      setRelatorioMD("");
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resultados, filtroClasseProduto]);

  // Exibir relatório já gerado em nova aba
  const handleRelatorioCompleto = () => {
    const md = relatorioMD;
    if (!md) return;
    const now = new Date();
    const dataHora = now.toLocaleString("pt-BR");

    // Parse tables properly
    const tableRegex = /(\|.+\|\n)+/g;
    let html = md.replace(tableRegex, (tableBlock) => {
      const rows = tableBlock.trim().split('\n').filter(r => r.trim());
      if (rows.length < 2) return tableBlock;
      let t = '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;border-color:#334155;margin:8px 0;width:100%;font-size:13px;">\n';
      rows.forEach((row, ri) => {
        if (ri === 1 && row.match(/^\|[\s-|]+\|$/)) return; // skip separator
        const cells = row.split('|').filter((_, ci, arr) => ci > 0 && ci < arr.length - 1).map(c => c.trim());
        const tag = ri === 0 ? 'th' : 'td';
        const bg = ri === 0 ? ' style="background:#1e293b;color:#94a3b8;text-align:left;"' : '';
        t += '<tr>' + cells.map(c => `<${tag}${bg}>${c}</${tag}>`).join('') + '</tr>\n';
      });
      t += '</table>\n';
      return t;
    });

    // Now convert remaining markdown
    html = html
      .replace(/^#### (.+)$/gm, '<h4 style="color:#60a5fa;margin:16px 0 8px;">$1</h4>')
      .replace(/^### (.+)$/gm, '<h3 style="color:#818cf8;margin:24px 0 12px;padding-bottom:6px;border-bottom:1px solid #334155;">$1</h3>')
      .replace(/^## (.+)$/gm, '<h2 style="color:#a78bfa;margin:32px 0 16px;">$1</h2>')
      .replace(/^# (.+)$/gm, '<h1 style="color:#e2e8f0;margin:0 0 24px;">$1</h1>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color:#60a5fa;">$1</a>')
      .replace(/^> (.+)$/gm, '<blockquote style="border-left:3px solid #475569;padding:4px 12px;margin:4px 0;color:#94a3b8;font-style:italic;">$1</blockquote>')
      .replace(/^- (.+)$/gm, '<div style="padding:2px 0 2px 16px;">$1</div>')
      .replace(/^---$/gm, '<hr style="border:none;border-top:1px solid #334155;margin:24px 0;"/>')
      .replace(/  \n/g, '<br/>');

    const fullHtml = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>Relatório Completo — ${dataHora}</title>
  <style>
    body {
      background: #0f172a;
      color: #e2e8f0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
      max-width: 1100px;
      margin: 0 auto;
      padding: 64px 24px 32px;
      line-height: 1.6;
    }
    table { font-size: 13px; }
    th { font-weight: 600; }
    td, th { padding: 6px 10px; border: 1px solid #334155; }
    tr:nth-child(even) { background: #1e293b; }
    blockquote { border-left: 3px solid #475569; padding: 4px 12px; margin: 4px 0; color: #94a3b8; font-style: italic; }
    h1 { color: #e2e8f0; font-size: 24px; margin-bottom: 24px; }
    h2 { color: #a78bfa; font-size: 20px; margin: 32px 0 16px; }
    h3 { color: #818cf8; font-size: 16px; margin: 24px 0 12px; padding-bottom: 6px; border-bottom: 1px solid #334155; }
    h4 { color: #60a5fa; font-size: 14px; margin: 16px 0 8px; }
    hr { border: none; border-top: 1px solid #334155; margin: 24px 0; }
    strong { color: #f1f5f9; }
    @media print {
      @page { size: landscape; margin: 10mm; }
      body { background: white; color: #1e293b; padding-top: 0; max-width: none; }
      h1, h2, h3, h4, strong { color: #1e293b; }
      table { font-size: 10px; }
      td, th { border-color: #cbd5e1; padding: 3px 5px; }
      tr:nth-child(even) { background: #f1f5f9; }
      blockquote { color: #64748b; border-color: #94a3b8; }
      .toolbar-relatorio { display: none !important; }
    }
    .toolbar-relatorio {
      position: fixed; top: 0; left: 0; right: 0; z-index: 1000;
      background: #1e293b; border-bottom: 2px solid #334155;
      padding: 10px 24px; display: flex; gap: 12px; align-items: center;
    }
    .toolbar-relatorio button {
      padding: 8px 18px; border: none; border-radius: 6px; cursor: pointer;
      font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 6px;
    }
    .btn-md { background: #3b82f6; color: white; }
    .btn-md:hover { background: #2563eb; }
    .btn-pdf { background: #8b5cf6; color: white; }
    .btn-pdf:hover { background: #7c3aed; }
    .toolbar-relatorio span { color: #94a3b8; font-size: 13px; margin-left: auto; }
  </style>
</head>
<body>
<div class="toolbar-relatorio">
  <button class="btn-md" onclick="baixarMD()">&#x1F4E5; Baixar MD</button>
  <button class="btn-pdf" onclick="window.print()">&#x1F4C4; Baixar PDF</button>
  <span>Relatório gerado em ${dataHora}</span>
</div>
${html}
<script>
var mdContent = ${JSON.stringify(md)};
function baixarMD() {
  var blob = new Blob(['\\uFEFF' + mdContent], { type: 'text/markdown;charset=utf-8;' });
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url;
  a.download = 'relatorio_editais_${now.toISOString().slice(0, 10)}.md';
  a.click();
  URL.revokeObjectURL(url);
}
</script>
</body>
</html>`;

    const blob = new Blob([fullHtml], { type: 'text/html;charset=utf-8' });
    const blobUrl = URL.createObjectURL(blob);
    window.open(blobUrl, '_blank');
  };

  // C1: Exportar CSV
  const handleExportarCSV = () => {
    if (!resultados.length) return;
    const header = 'Numero;Orgao;UF;Objeto;Valor;Abertura;Score\n';
    const rows = resultados.map(e =>
      `${e.numero};${e.orgao};${e.uf};"${(e.objeto || '').replace(/"/g, '""')}";${e.valor || ''};${e.dataAbertura || ''};${e.score || ''}`
    ).join('\n');
    const blob = new Blob(['\ufeff' + header + rows], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `editais_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // T16: Navegação para ValidacaoPage com edital_id
  const handleIrParaValidacao = (edital: EditalBusca) => {
    const editalId = edital.editalSalvoId || (edital.id.length === 36 ? edital.id : null);
    // Dispara evento customizado para o App.tsx capturar
    window.dispatchEvent(new CustomEvent("navigate-to", {
      detail: { page: "validacao", edital_id: editalId }
    }));
  };

  const formatCurrency = (value: number) => {
    if (!value) return "—";
    return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);
  };

  const getRowClass = (edital: EditalBusca) => {
    if (edital.score >= 80) return "row-score-high";
    if (edital.score >= 50) return "row-score-medium";
    return "row-score-low";
  };

  const getGapColor = (tipo: string) => {
    if (tipo === "atendido") return "success";
    if (tipo === "parcial") return "warning";
    return "error";
  };

  const getGapLabel = (tipo: string) => {
    if (tipo === "atendido") return "Atendido";
    if (tipo === "parcial") return "Parcial";
    return "Nao atendido";
  };

  // RF-013: Filtro local por classe de produto
  const filteredResultados = useMemo(() => {
    if (filtroClasseProduto === "todos") return resultados;
    return resultados.filter(e => e.classe_produto_id === filtroClasseProduto);
  }, [resultados, filtroClasseProduto]);

  const prazos = contarPrazos(filteredResultados.length > 0 ? filteredResultados : []);

  const columns: Column<EditalBusca>[] = [
    {
      key: "selected",
      header: "",
      width: "70px",
      render: (e) => e.editalSalvoId ? (
        <span title="Edital ja salvo" style={{
          display: "inline-flex", alignItems: "center", gap: "3px",
          backgroundColor: "#052e16", color: "#22c55e", border: "1px solid #16a34a",
          borderRadius: "4px", padding: "2px 6px", fontSize: "10px", fontWeight: 700,
          whiteSpace: "nowrap",
        }}>
          <CheckCircle size={12} /> SALVO
        </span>
      ) : (
        <input
          type="checkbox"
          checked={e.selected || false}
          onClick={(ev) => ev.stopPropagation()}
          onChange={() => handleToggleSelect(e.id)}
        />
      ),
    },
    {
      key: "fonte",
      header: "Fonte",
      width: "100px",
      render: (e) => {
        const f = e.fonte || "—";
        let label = f;
        let color = "#888";
        if (f.includes("PNCP")) { label = "PNCP"; color = "#2e7d32"; }
        else if (f.includes("comprasnet") || f.includes("ComprasNet")) { label = "ComprasNet"; color = "#1565c0"; }
        else if (f.includes("bec") || f.includes("BEC")) { label = "BEC-SP"; color = "#f9a825"; }
        else if (f.includes("licitacoes") || f.includes("Licitacoes")) { label = "Licitações-e"; color = "#e65100"; }
        else if (f.includes("compras.rs")) { label = "Compras RS"; color = "#6a1b9a"; }
        else if (f.includes("compras.mg")) { label = "Compras MG"; color = "#ad1457"; }
        else if (f.includes("Scraper")) { label = f.split(" (")[0]; color = "#e65100"; }
        return <span style={{ color, fontWeight: 600, fontSize: "0.8em" }}>{label}</span>;
      },
      sortable: true,
    },
    { key: "numero", header: "Numero", sortable: true },
    { key: "orgao", header: "Orgao", sortable: true },
    { key: "uf", header: "UF", width: "50px" },
    {
      key: "modalidade",
      header: "Modalidade",
      width: "120px",
      sortable: true,
      render: (e) => {
        // Buscar nome da modalidade na tabela do banco
        const modVal = e.modalidade ?? "";
        const modLabel = modalidadesDisponiveis.find(m =>
          m.value.toLowerCase().replace(/[^a-z]/g, "").includes(modVal.toLowerCase().replace(/[^a-z]/g, "")) ||
          modVal.toLowerCase().replace(/[^a-z]/g, "").includes(m.value.toLowerCase().replace(/[^a-z]/g, ""))
        )?.label || modVal || "—";
        return <span style={{ fontSize: "0.8em" }}>{modLabel}</span>;
      },
    },
    {
      key: "objeto",
      header: "Objeto",
      render: (e) => (
        <span className="truncate" title={e.objeto}>
          {e.objeto.length > 45 ? e.objeto.substring(0, 45) + "..." : e.objeto}
        </span>
      ),
    },
    {
      key: "valor",
      header: "Valor",
      render: (e) => formatCurrency(e.valor),
      sortable: true,
    },
    {
      key: "produtoCorrespondente",
      header: "Produto",
      render: (e) => e.produtoCorrespondente ? (
        <span className="produto-correspondente" title={e.produtoCorrespondente}>
          {e.produtoCorrespondente.length > 25 ? e.produtoCorrespondente.substring(0, 25) + "..." : e.produtoCorrespondente}
        </span>
      ) : (
        <span className="text-muted">—</span>
      ),
    },
    {
      key: "diasRestantes",
      header: "Prazo",
      width: "70px",
      render: (e) => {
        if (e.status === "encerrado") return <StatusBadge status="neutral" label="Encerrado" size="small" />;
        if (e.diasRestantes <= 2) return <StatusBadge status="error" label={`${e.diasRestantes}d`} size="small" />;
        if (e.diasRestantes <= 5) return <StatusBadge status="warning" label={`${e.diasRestantes}d`} size="small" />;
        return <span>{e.diasRestantes}d</span>;
      },
      sortable: true,
    },
    {
      key: "score",
      header: "Score",
      width: "70px",
      render: (e) => tipoScore !== "nenhum" ? (
        <div
          className="score-cell-tooltip"
          style={{ position: "relative" }}
          onMouseEnter={(ev) => {
            const tooltip = ev.currentTarget.querySelector(".gap-tooltip") as HTMLElement;
            if (tooltip) tooltip.style.display = "block";
          }}
          onMouseLeave={(ev) => {
            const tooltip = ev.currentTarget.querySelector(".gap-tooltip") as HTMLElement;
            if (tooltip) tooltip.style.display = "none";
          }}
        >
          <ScoreCircle score={e.score} size={40} />
          <div
            className="gap-tooltip"
            style={{
              display: "none",
              position: "absolute",
              bottom: "100%",
              left: "50%",
              transform: "translateX(-50%)",
              backgroundColor: "#1e293b",
              color: "#e2e8f0",
              borderRadius: "8px",
              padding: "10px 14px",
              fontSize: "12px",
              lineHeight: "1.5",
              minWidth: "200px",
              maxWidth: "300px",
              zIndex: 9999,
              boxShadow: "0 4px 16px rgba(0,0,0,0.3)",
              pointerEvents: "none",
              whiteSpace: "normal",
            }}
          >
            <div style={{ fontWeight: 700, marginBottom: "6px", borderBottom: "1px solid #334155", paddingBottom: "4px" }}>Analise de Gaps</div>
            {e.gaps.length > 0 ? (
              e.gaps.map((g, i) => (
                <div key={i} style={{ display: "flex", gap: "6px", alignItems: "flex-start", marginBottom: "3px" }}>
                  <span style={{ color: g.tipo === "atendido" ? "#22c55e" : g.tipo === "parcial" ? "#eab308" : "#ef4444", flexShrink: 0 }}>
                    {g.tipo === "atendido" ? "\u2714" : g.tipo === "parcial" ? "\u25CF" : "\u2718"}
                  </span>
                  <span>{g.item}</span>
                </div>
              ))
            ) : (
              <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                <span style={{ color: "#22c55e" }}>{"\u2714"}</span>
                <span>Todos os requisitos atendidos</span>
              </div>
            )}
            <div style={{ marginTop: "6px", borderTop: "1px solid #334155", paddingTop: "4px", fontSize: "11px", color: "#94a3b8" }}>
              Tec: {e.scores.tecnico}% | Com: {e.scores.comercial}% | Rec: {e.scores.recomendacao}%
            </div>
          </div>
        </div>
      ) : <span>-</span>,
      sortable: true,
    },
    {
      key: "score_competitividade",
      header: "Competitividade",
      width: "110px",
      render: (e) => {
        const sc = e.score_competitividade;
        if (sc == null) return <span style={{ color: "var(--text-secondary)", fontSize: "0.8em" }}>—</span>;
        const color = sc > 70 ? "#22c55e" : sc >= 40 ? "#eab308" : "#ef4444";
        const bg = sc > 70 ? "#052e16" : sc >= 40 ? "#422006" : "#450a0a";
        const label = sc > 70 ? "Alta" : sc >= 40 ? "Média" : "Baixa";
        return (
          <span style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            fontSize: "0.8em", fontWeight: 600, padding: "2px 8px",
            borderRadius: 4, color, backgroundColor: bg, border: `1px solid ${color}40`,
          }}>
            {sc} — {label}
          </span>
        );
      },
      sortable: true,
    },
    {
      key: "acoes",
      header: "Acoes",
      width: "80px",
      render: (e) => (
        <div className="table-actions">
          <button title="Ver detalhes" onClick={() => handleAbrirPainel(e)}><Eye size={16} /></button>
          {e.editalSalvoId ? (
            <button title="Ja salvo" disabled style={{ color: "#22c55e", opacity: 0.7, cursor: "default" }}><CheckCircle size={16} /></button>
          ) : (
            <button title="Salvar edital" onClick={() => handleSalvarEdital(e)}><Save size={16} /></button>
          )}
        </div>
      ),
    },
  ];

  const selectedCount = resultados.filter(e => e.selected).length;

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-left">
          <Search size={24} />
          <div>
            <h1>Captacao de Editais</h1>
            <p>Busca e captacao de novos editais</p>
          </div>
        </div>
      </div>

      <div className="page-content">
        <TabPanel
          tabs={[
            { id: "editais", label: "Editais", icon: <FileText size={16} /> },
            { id: "dispensas", label: "Dispensas", icon: <ShoppingCart size={16} /> },
          ]}
          defaultTab="editais"
        >
          {(activeTab) => activeTab === "editais" ? (
          <>
        {/* Prazos de submissao */}
        <div className="stat-cards-grid">
          <StatCard
            icon={<AlertTriangle size={20} />}
            value={prazos.dias2}
            label="Proximos 2 dias"
            color="red"
          />
          <StatCard
            icon={<Calendar size={20} />}
            value={prazos.dias5}
            label="Proximos 5 dias"
            color="orange"
          />
          <StatCard
            icon={<Calendar size={20} />}
            value={prazos.dias10}
            label="Proximos 10 dias"
            color="yellow"
          />
          <StatCard
            icon={<Calendar size={20} />}
            value={prazos.dias20}
            label="Proximos 20 dias"
            color="blue"
          />
        </div>

        {/* Card de busca */}
        <Card title="Buscar Editais" icon={<Search size={18} />}>
          <div className="form-grid form-grid-4">
            <FormField label="Termo / Produto">
              <div style={{ position: "relative" }}>
                <input
                  type="text"
                  value={termo}
                  onChange={(e) => { setTermo(e.target.value); setTermoDropdownAberto(true); }}
                  onFocus={() => setTermoDropdownAberto(true)}
                  onBlur={() => setTimeout(() => setTermoDropdownAberto(false), 150)}
                  placeholder={classificacaoTipo !== "todos" ? `Tipo Produto: ${classificacaoTipo}` : "Digite ou selecione um produto..."}
                  className="form-input"
                  style={{ width: "100%", minHeight: "42px", backgroundColor: "#0f172a", color: "#e2e8f0" }}
                  disabled={classificacaoTipo !== "todos"}
                />
                {termoDropdownAberto && classificacaoTipo === "todos" && produtosPortfolio.length > 0 && (
                  <div style={{
                    position: "absolute", top: "100%", left: 0, right: 0, zIndex: 50,
                    background: "#1e293b", border: "1px solid #334155", borderRadius: "6px",
                    maxHeight: "200px", overflowY: "auto", marginTop: "2px",
                  }}>
                    {produtosPortfolio
                      .filter(p => !termo || p.label.toLowerCase().includes(termo.toLowerCase()))
                      .map((p) => (
                        <div
                          key={p.value}
                          onMouseDown={() => { setTermo(p.value); setTermoDropdownAberto(false); }}
                          style={{
                            padding: "6px 10px", cursor: "pointer", fontSize: "13px",
                            color: "#e2e8f0", borderBottom: "1px solid #1e293b",
                          }}
                          onMouseEnter={(ev) => (ev.currentTarget.style.background = "#334155")}
                          onMouseLeave={(ev) => (ev.currentTarget.style.background = "transparent")}
                        >
                          {p.label}
                        </div>
                      ))}
                  </div>
                )}
                {classificacaoTipo !== "todos" && (
                  <div style={{ fontSize: "11px", color: "#94a3b8", marginTop: "2px" }}>
                    Usando Tipo Produto: {classificacaoTipo}
                  </div>
                )}
              </div>
            </FormField>
            <FormField label="UF">
              <SelectInput value={uf} onChange={setUf} options={UFS} />
            </FormField>
            <FormField label="Fonte">
              <SelectInput
                value={fonte}
                onChange={setFonte}
                options={[
                  { value: "todas", label: "Todas as fontes" },
                  ...fontesDisponiveis,
                ]}
              />
            </FormField>
          </div>

          <div className="form-grid form-grid-3" style={{ marginTop: "12px" }}>
            <FormField label="Area de Atuacao">
              <SelectInput
                value={selectedArea}
                onChange={(v) => { setSelectedArea(v); setSelectedClasse(""); setSelectedSubclasse(""); setClassificacaoTipo("todos"); }}
                options={[
                  { value: "", label: "Todas" },
                  ...areasOptions,
                ]}
              />
            </FormField>
            <FormField label="Tipo Produto (Classe)">
              <SelectInput
                value={selectedClasse || classificacaoTipo}
                onChange={(v) => {
                  setSelectedClasse(v);
                  setSelectedSubclasse("");
                  const cls = classesForArea.find(c => c.value === v);
                  setClassificacaoTipo(cls ? cls.label : "todos");
                }}
                options={[
                  { value: "todos", label: "Todos" },
                  ...classesForArea,
                ]}
              />
            </FormField>
            <FormField label="Subclasse (opcional)">
              <SelectInput
                value={selectedSubclasse}
                onChange={setSelectedSubclasse}
                options={[
                  { value: "", label: "Todas" },
                  ...subclassesForClasse,
                ]}
              />
            </FormField>
          </div>

          <div className="form-grid form-grid-4" style={{ marginTop: "12px" }}>
            <FormField label="Modalidade">
              <SelectInput
                value={modalidadeFiltro}
                onChange={setModalidadeFiltro}
                options={[
                  { value: "todos", label: "Todas" },
                  ...modalidadesDisponiveis,
                ]}
              />
            </FormField>
            <FormField label="Origem">
              <SelectInput
                value={classificacaoOrigem}
                onChange={setClassificacaoOrigem}
                options={[
                  { value: "todos", label: "Todas" },
                  ...origensDisponiveis,
                ]}
              />
            </FormField>
            <FormField label="NCM (codigo)">
              <TextInput
                value={ncm}
                onChange={setNcm}
                placeholder="Ex: 9027.80.99"
              />
            </FormField>
            <FormField label="Classe de Produto (filtro local)">
              <SelectInput
                value={filtroClasseProduto}
                onChange={setFiltroClasseProduto}
                options={[
                  { value: "todos", label: "Todas as classes" },
                  ...classesV2,
                ]}
              />
            </FormField>
          </div>

          <div className="form-grid form-grid-4" style={{ marginTop: "12px" }}>
            <FormField label="Periodo de publicacao">
              <SelectInput
                value={diasBusca}
                onChange={setDiasBusca}
                options={[
                  { value: "30", label: "Ultimos 30 dias" },
                  { value: "60", label: "Ultimos 60 dias" },
                  { value: "90", label: "Ultimos 90 dias" },
                  { value: "180", label: "Ultimos 180 dias" },
                  { value: "365", label: "Ultimo ano" },
                  { value: "0", label: "Todos (sem limite)" },
                ]}
              />
            </FormField>
          </div>

          <div style={{ display: "flex", gap: "12px", flexWrap: "wrap", alignItems: "flex-end" }}>
            <div style={{ minWidth: "180px" }}>
              <FormField label="Analise de Score">
                <SelectInput
                  value={tipoScore}
                  onChange={(v) => setTipoScore(v as "nenhum" | "rapido" | "hibrido" | "profundo")}
                  options={[
                    { value: "nenhum", label: "Sem Score" },
                    { value: "rapido", label: "Score Rapido" },
                    { value: "hibrido", label: "Score Hibrido" },
                    { value: "profundo", label: "Score Profundo" },
                  ]}
                />
              </FormField>
            </div>
            {(tipoScore === "hibrido" || tipoScore === "profundo") && (
              <div style={{ minWidth: "140px" }}>
                <FormField label="Qtd editais profundo">
                  <SelectInput
                    value={String(limiteScoreProfundo)}
                    onChange={(v) => setLimiteScoreProfundo(Number(v))}
                    options={[
                      { value: "5", label: "5 editais" },
                      { value: "10", label: "10 editais" },
                      { value: "20", label: "20 editais" },
                      { value: "0", label: "Todos" },
                    ]}
                  />
                </FormField>
              </div>
            )}
            <Checkbox
              checked={incluirEncerrados}
              onChange={setIncluirEncerrados}
              label="Incluir editais encerrados"
            />
          </div>

          <div style={{ marginTop: "16px", display: "flex", justifyContent: "center", gap: "8px" }}>
            <ActionButton
              icon={<Search size={16} />}
              label="Buscar Editais"
              variant="primary"
              onClick={handleBuscar}
              loading={loading}
            />
            {/* CV01-3 (Arnaldo Sprint 2 V8): botao Limpar filtros */}
            <ActionButton
              label="Limpar filtros"
              variant="neutral"
              onClick={handleLimparFiltros}
            />
          </div>

          {erro && (
            <div className="alert alert-error" style={{ marginTop: "12px" }}>
              {erro}
            </div>
          )}

          {/* CV01-6 + CV01-2a (Arnaldo Sprint 2 V8): avisos de fontes/filtros */}
          {errosFontes && errosFontes.length > 0 && (
            <div className="alert" style={{ marginTop: "12px", background: "#1e293b", border: "1px solid #475569", color: "#fbbf24", padding: "10px 12px", borderRadius: "6px" }}>
              <strong style={{ display: "block", marginBottom: "4px", fontSize: "12px" }}>⚠ Avisos da busca:</strong>
              <ul style={{ margin: 0, paddingLeft: "20px", fontSize: "12px", lineHeight: 1.5 }}>
                {errosFontes.map((msg, i) => <li key={i}>{msg}</li>)}
              </ul>
            </div>
          )}

          {/* CV01-4: empty-state explicito quando a busca rodou mas zero resultados */}
          {!loading && !erro && resultados.length === 0 && termo && (
            <div className="alert" style={{ marginTop: "12px", background: "#0f172a", border: "1px solid #334155", color: "#94a3b8", padding: "12px", borderRadius: "6px", textAlign: "center" }}>
              <strong style={{ display: "block", marginBottom: "4px" }}>Nenhum edital encontrado</strong>
              <span style={{ fontSize: "12px" }}>Tente relaxar os filtros (UF, modalidade, score) ou usar um termo mais geral.</span>
            </div>
          )}
        </Card>

        {/* Resultados + Painel lateral */}
        {resultados.length > 0 && (
          <div className={`captacao-layout ${painelEdital ? "with-panel" : ""}`}>
            {/* Tabela de resultados */}
            <div className="captacao-table-area">
              <Card
                title={`Resultados (${filteredResultados.length} editais encontrados${filtroClasseProduto !== "todos" ? " - filtrado" : ""})`}
                icon={<FileText size={18} />}
                actions={
                  <div className="card-actions">
                    <ActionButton icon={<FileText size={14} />} label="Relatório Completo" onClick={handleRelatorioCompleto} />
                    <ActionButton icon={<Save size={14} />} label="Salvar Todos" onClick={handleSalvarTodos} />
                    <ActionButton icon={<Save size={14} />} label="Salvar Score >= 70%" onClick={handleSalvarRecomendados} />
                    <ActionButton icon={<Download size={14} />} label="Exportar CSV" onClick={handleExportarCSV} />
                  </div>
                }
              >
                {selectedCount > 0 && (
                  <div className="selection-bar">
                    <span>{selectedCount} edital(is) selecionado(s)</span>
                    <ActionButton
                      label="Salvar Selecionados"
                      onClick={async () => {
                        // CV03-13 (Arnaldo Sprint 2 V8): atualiza badge dos selecionados
                        const selecionados = resultados.filter(e => e.selected && !e.editalSalvoId);
                        const mapa: Record<string, string> = {};
                        for (const edital of selecionados) {
                          const id = await salvarEditalNoBanco(edital);
                          if (id) mapa[edital.id] = id;
                        }
                        _setSalvoLocal(mapa);
                        alert(Object.keys(mapa).length > 0 ? `${Object.keys(mapa).length} edital(is) salvo(s)` : "Todos os selecionados ja estao salvos");
                      }}
                      variant="primary"
                    />
                  </div>
                )}

                <DataTable
                  data={filteredResultados}
                  columns={columns}
                  idKey="id"
                  emptyMessage="Nenhum edital encontrado"
                  loading={loading}
                  rowClassName={(e) => getRowClass(e)}
                  onRowClick={(e) => handleAbrirPainel(e)}
                  defaultSortKey={tipoScore !== "nenhum" ? "score" : undefined}
                  defaultSortDirection={tipoScore !== "nenhum" ? "desc" : "asc"}
                />
              </Card>
            </div>

            {/* Painel lateral de detalhes */}
            {painelEdital && (
              <div className="captacao-panel">
                <Card
                  title={painelEdital.numero}
                  subtitle={painelEdital.orgao}
                  actions={
                    <button className="btn-icon" onClick={() => setPainelEdital(null)} title="Fechar">
                      <X size={18} />
                    </button>
                  }
                >
                  {/* Dados completos do edital */}
                  <div className="panel-section">
                    <h4>Dados do Edital</h4>
                    <div style={{ fontSize: "13px", lineHeight: "1.6" }}>
                      <div style={{ display: "flex", gap: "8px", marginBottom: "4px" }}>
                        <span style={{ color: "#64748b", minWidth: "80px", flexShrink: 0 }}>Numero:</span>
                        <span style={{ color: "#e2e8f0" }}>{painelEdital.numero}</span>
                      </div>
                      <div style={{ display: "flex", gap: "8px", marginBottom: "4px" }}>
                        <span style={{ color: "#64748b", minWidth: "80px", flexShrink: 0 }}>Orgao:</span>
                        <span style={{ color: "#e2e8f0" }}>{painelEdital.orgao}</span>
                      </div>
                      <div style={{ display: "flex", gap: "8px", marginBottom: "4px" }}>
                        <span style={{ color: "#64748b", minWidth: "80px", flexShrink: 0 }}>UF:</span>
                        <span style={{ color: "#e2e8f0" }}>{painelEdital.uf}</span>
                      </div>
                      <div style={{ display: "flex", gap: "8px", marginBottom: "4px" }}>
                        <span style={{ color: "#64748b", minWidth: "80px", flexShrink: 0 }}>Modalidade:</span>
                        <span style={{ color: "#e2e8f0" }}>{painelEdital.modalidade}</span>
                      </div>
                      <div style={{ display: "flex", gap: "8px", marginBottom: "4px" }}>
                        <span style={{ color: "#64748b", minWidth: "80px", flexShrink: 0 }}>Fonte:</span>
                        <span style={{ color: "#e2e8f0" }}>{painelEdital.fonte}</span>
                      </div>
                      <div style={{ display: "flex", gap: "8px", marginBottom: "4px" }}>
                        <span style={{ color: "#64748b", minWidth: "80px", flexShrink: 0 }}>Valor:</span>
                        <span style={{ color: "#e2e8f0" }}>{formatCurrency(painelEdital.valor)}</span>
                      </div>
                      <div style={{ display: "flex", gap: "8px", marginBottom: "4px" }}>
                        <span style={{ color: "#64748b", minWidth: "80px", flexShrink: 0 }}>Abertura:</span>
                        <span style={{ color: "#e2e8f0" }}>{painelEdital.dataAbertura || "—"}</span>
                      </div>
                      <div style={{ display: "flex", gap: "8px", marginBottom: "4px" }}>
                        <span style={{ color: "#64748b", minWidth: "80px", flexShrink: 0 }}>Status:</span>
                        <StatusBadge status={painelEdital.status === "aberto" ? "success" : "neutral"} label={painelEdital.status === "aberto" ? `Aberto (${painelEdital.diasRestantes}d)` : "Encerrado"} size="small" />
                      </div>
                      <div style={{ marginTop: "8px" }}>
                        <span style={{ color: "#64748b", display: "block", marginBottom: "4px" }}>Objeto:</span>
                        <div style={{ color: "#cbd5e1", backgroundColor: "#0f172a", padding: "8px", borderRadius: "6px", fontSize: "12px", lineHeight: "1.5", maxHeight: "150px", overflowY: "auto" }}>
                          {painelEdital.objeto}
                        </div>
                      </div>
                      {tipoScore !== "nenhum" && painelEdital.justificativa && (
                        <div style={{ marginTop: "8px" }}>
                          <span style={{ color: "#64748b", display: "block", marginBottom: "4px" }}>Justificativa IA:</span>
                          <div style={{ color: "#94a3b8", backgroundColor: "#0f172a", padding: "8px", borderRadius: "6px", fontSize: "12px", lineHeight: "1.5", fontStyle: "italic" }}>
                            {painelEdital.justificativa}
                          </div>
                        </div>
                      )}
                      {tipoScore !== "nenhum" && painelEdital.recomendacaoTexto && painelEdital.recomendacaoTexto !== "0" && painelEdital.recomendacaoTexto !== "NaN" && (
                        <div style={{ marginTop: "6px", display: "flex", gap: "8px", alignItems: "center" }}>
                          <span style={{ color: "#64748b", minWidth: "80px", flexShrink: 0 }}>Recomendacao:</span>
                          <StatusBadge
                            status={painelEdital.recomendacaoTexto === "PARTICIPAR" ? "success" : painelEdital.recomendacaoTexto === "AVALIAR" ? "warning" : "error"}
                            label={painelEdital.recomendacaoTexto}
                            size="small"
                          />
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Fase 2 — Inteligência Comercial (RF-CLA, RF-SCO, RF-PRE) */}
                  <InteligenciaComercialPanel
                    editalId={painelEdital.editalSalvoId || (painelEdital.id.length === 36 ? painelEdital.id : null)}
                  />

                  {/* Score principal — só mostra se busca usou score */}
                  {tipoScore !== "nenhum" && (
                  <div className="panel-score-section">
                    <ScoreCircle score={painelEdital.scoreProfundo ? painelEdital.scoreProfundo.score_geral : painelEdital.score} size={100} label="Score Geral" />
                  </div>
                  )}

                  {tipoScore !== "nenhum" && painelEdital.scoreProfundo ? (
                    /* 6 sub-scores do score profundo */
                    <div className="panel-section">
                      <h4>6 Dimensoes de Score</h4>
                      <div style={{ marginBottom: "10px" }}>
                        {[
                          { key: "tecnico", label: "Tecnico" },
                          { key: "documental", label: "Documental" },
                          { key: "complexidade", label: "Complexidade" },
                          { key: "juridico", label: "Juridico" },
                          { key: "logistico", label: "Logistico" },
                          { key: "comercial", label: "Comercial" },
                        ].map(dim => {
                          const val = painelEdital.scoreProfundo!.scores[dim.key as keyof typeof painelEdital.scoreProfundo.scores] ?? 0;
                          const status: "success" | "warning" | "error" = val >= 70 ? "success" : val >= 40 ? "warning" : "error";
                          return (
                            <div key={dim.key} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                              <span style={{ fontSize: "13px", color: "#cbd5e1" }}>{dim.label}</span>
                              <StatusBadge status={status} label={`${val}%`} size="small" />
                            </div>
                          );
                        })}
                      </div>
                      {/* Decisao GO/NO-GO */}
                      <div style={{ marginBottom: "8px", padding: "6px 10px", borderRadius: "6px", backgroundColor: painelEdital.scoreProfundo.decisao === "GO" ? "#052e16" : painelEdital.scoreProfundo.decisao === "NO-GO" ? "#450a0a" : "#1e293b" }}>
                        <strong style={{ color: painelEdital.scoreProfundo.decisao === "GO" ? "#22c55e" : painelEdital.scoreProfundo.decisao === "NO-GO" ? "#ef4444" : "#eab308" }}>
                          {painelEdital.scoreProfundo.decisao}
                        </strong>
                        {painelEdital.scoreProfundo.justificativa && (
                          <div style={{ fontSize: "12px", color: "#94a3b8", marginTop: "4px" }}>
                            {painelEdital.scoreProfundo.justificativa}
                          </div>
                        )}
                      </div>
                      {/* Pontos positivos */}
                      {painelEdital.scoreProfundo.pontos_positivos.length > 0 && (
                        <div style={{ marginBottom: "6px" }}>
                          <div style={{ fontSize: "12px", fontWeight: 600, color: "#22c55e", marginBottom: "4px" }}>Pontos positivos:</div>
                          {painelEdital.scoreProfundo.pontos_positivos.map((p, i) => (
                            <div key={i} style={{ fontSize: "12px", color: "#cbd5e1", display: "flex", gap: "4px", marginBottom: "2px" }}>
                              <span style={{ color: "#22c55e", flexShrink: 0 }}>{"\u2714"}</span>
                              <span>{p}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      {/* Pontos de atencao */}
                      {painelEdital.scoreProfundo.pontos_atencao.length > 0 && (
                        <div style={{ marginBottom: "6px" }}>
                          <div style={{ fontSize: "12px", fontWeight: 600, color: "#eab308", marginBottom: "4px" }}>Pontos de atencao:</div>
                          {painelEdital.scoreProfundo.pontos_atencao.map((p, i) => (
                            <div key={i} style={{ fontSize: "12px", color: "#cbd5e1", display: "flex", gap: "4px", marginBottom: "2px" }}>
                              <span style={{ color: "#eab308", flexShrink: 0 }}>{"\u26A0"}</span>
                              <span>{p}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : tipoScore !== "nenhum" ? (
                    /* 3 sub-scores: Técnico e Comercial em gauge circular, Recomendação em estrelas */
                    <div className="panel-subscores" style={{ display: "flex", gap: "16px", alignItems: "flex-start", flexWrap: "wrap" }}>
                      <div style={{ textAlign: "center" }}>
                        <ScoreCircle score={painelEdital.scores.tecnico} size={60} />
                        <div style={{ fontSize: "11px", color: "#94a3b8", marginTop: "2px" }}>Aderencia Tecnica</div>
                      </div>
                      <div style={{ textAlign: "center" }}>
                        <ScoreCircle score={painelEdital.scores.comercial} size={60} />
                        <div style={{ fontSize: "11px", color: "#94a3b8", marginTop: "2px" }}>Aderencia Comercial</div>
                      </div>
                      <div style={{ textAlign: "center", flex: 1, minWidth: "120px" }}>
                        <StarRating score={painelEdital.scores.recomendacao} />
                        <div style={{ fontSize: "11px", color: "#94a3b8", marginTop: "2px" }}>Recomendacao</div>
                      </div>
                    </div>
                  ) : null}

                  {/* Produto correspondente — só com score */}
                  {tipoScore !== "nenhum" && (
                  <div className="panel-section">
                    <h4>Produto Correspondente</h4>
                    {painelEdital.produtoCorrespondente ? (
                      <div className="panel-produto">
                        <Sparkles size={14} />
                        <span>{painelEdital.produtoCorrespondente}</span>
                      </div>
                    ) : (
                      <p className="text-muted">Nenhum produto correspondente encontrado</p>
                    )}
                  </div>
                  )}

                  {/* Potencial de Ganho — só com score */}
                  {tipoScore !== "nenhum" && (
                  <div className="panel-section">
                    <h4>Potencial de Ganho</h4>
                    <StatusBadge
                      status={
                        painelEdital.potencialGanho === "elevado" ? "success" :
                        painelEdital.potencialGanho === "medio" ? "warning" : "error"
                      }
                      label={painelEdital.potencialGanho.charAt(0).toUpperCase() + painelEdital.potencialGanho.slice(1)}
                    />
                  </div>
                  )}

                  {/* Itens do Edital */}
                  {painelEdital.itens && painelEdital.itens.length > 0 && (
                    <div className="panel-section">
                      <h4>Itens do Edital ({painelEdital.itens.length})</h4>
                      <div style={{ maxHeight: "200px", overflowY: "auto", fontSize: "12px" }}>
                        <table style={{ width: "100%", borderCollapse: "collapse" }}>
                          <thead>
                            <tr style={{ borderBottom: "1px solid #334155", color: "#64748b", fontSize: "11px" }}>
                              <th style={{ padding: "4px", textAlign: "left" }}>#</th>
                              <th style={{ padding: "4px", textAlign: "left" }}>Descricao</th>
                              <th style={{ padding: "4px", textAlign: "right" }}>Qtd</th>
                              <th style={{ padding: "4px", textAlign: "right" }}>Valor Total</th>
                            </tr>
                          </thead>
                          <tbody>
                            {painelEdital.itens.map((item, idx) => (
                              <tr key={idx} style={{ borderBottom: "1px solid #1e293b" }}>
                                <td style={{ padding: "4px", color: "#94a3b8" }}>{item.numero_item ?? idx + 1}</td>
                                <td style={{ padding: "4px", color: "#cbd5e1", maxWidth: "180px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={item.descricao}>
                                  {item.descricao && item.descricao.length > 40 ? item.descricao.substring(0, 40) + "..." : item.descricao}
                                </td>
                                <td style={{ padding: "4px", color: "#94a3b8", textAlign: "right" }}>
                                  {item.quantidade ?? "—"} {item.unidade_medida ?? ""}
                                </td>
                                <td style={{ padding: "4px", color: "#e2e8f0", textAlign: "right" }}>
                                  {item.valor_total_estimado ? formatCurrency(item.valor_total_estimado) : "—"}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                  {painelEdital.totalItens === 0 && painelEdital.itens?.length === 0 && (
                    <div className="panel-section">
                      <h4>Itens do Edital</h4>
                      <p className="text-muted" style={{ fontSize: "12px" }}>Nenhum item disponivel. Itens sao carregados automaticamente para editais do PNCP.</p>
                    </div>
                  )}

                  {/* Intencao Estrategica - T15 */}
                  <div className="panel-section">
                    <h4>Intencao Estrategica</h4>
                    <RadioGroup
                      value={intencaoLocal}
                      onChange={(v) => setIntencaoLocal(v as EditalBusca["intencaoEstrategica"])}
                      name="intencao-panel"
                      options={[
                        { value: "estrategico", label: "Estrategico" },
                        { value: "defensivo", label: "Defensivo" },
                        { value: "acompanhamento", label: "Acompanhamento" },
                        { value: "aprendizado", label: "Aprendizado" },
                      ]}
                    />
                  </div>

                  {/* Expectativa de Margem - T15 */}
                  <div className="panel-section">
                    <h4>Expectativa de Margem: {margemLocal}%</h4>
                    <input
                      type="range"
                      min="0"
                      max="50"
                      value={margemLocal}
                      onChange={(e) => setMargemLocal(Number(e.target.value))}
                      className="slider-input"
                    />
                    <div className="slider-labels">
                      <span>0%</span>
                      <span>50%</span>
                    </div>
                    {/* Botões Varia por Produto / Região (F7) */}
                    <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
                      <button
                        onClick={() => setVariaPorProduto(!variaPorProduto)}
                        style={{
                          flex: 1,
                          padding: "6px 10px",
                          fontSize: "12px",
                          border: variaPorProduto ? "2px solid #3b82f6" : "1px solid #334155",
                          borderRadius: "6px",
                          backgroundColor: variaPorProduto ? "#1e3a5f" : "transparent",
                          color: variaPorProduto ? "#60a5fa" : "#94a3b8",
                          cursor: "pointer",
                          fontWeight: variaPorProduto ? 600 : 400,
                        }}
                      >
                        Varia por Produto
                      </button>
                      <button
                        onClick={() => setVariaPorRegiao(!variaPorRegiao)}
                        style={{
                          flex: 1,
                          padding: "6px 10px",
                          fontSize: "12px",
                          border: variaPorRegiao ? "2px solid #3b82f6" : "1px solid #334155",
                          borderRadius: "6px",
                          backgroundColor: variaPorRegiao ? "#1e3a5f" : "transparent",
                          color: variaPorRegiao ? "#60a5fa" : "#94a3b8",
                          cursor: "pointer",
                          fontWeight: variaPorRegiao ? 600 : 400,
                        }}
                      >
                        Varia por Regiao
                      </button>
                    </div>
                    {variaPorProduto && (
                      <div style={{ marginTop: "8px", padding: "8px", backgroundColor: "#0f172a", borderRadius: "6px", fontSize: "12px" }}>
                        <div style={{ color: "#94a3b8", marginBottom: "4px" }}>Margem por produto (ajuste individual via Parametrizacoes)</div>
                        <div style={{ color: "#64748b", fontStyle: "italic" }}>Configure as margens por produto na aba Parametrizacoes &gt; Comerciais</div>
                      </div>
                    )}
                    {variaPorRegiao && (
                      <div style={{ marginTop: "8px", padding: "8px", backgroundColor: "#0f172a", borderRadius: "6px", fontSize: "12px" }}>
                        <div style={{ color: "#94a3b8", marginBottom: "4px" }}>Margem por regiao (ajuste individual via Parametrizacoes)</div>
                        <div style={{ color: "#64748b", fontStyle: "italic" }}>Configure as margens por UF na aba Parametrizacoes &gt; Comerciais</div>
                      </div>
                    )}
                  </div>

                  {/* Analise de Gaps - C2: Dados reais do endpoint scores-validacao (somente se nao tem scoreProfundo inline e usou score) */}
                  {tipoScore !== "nenhum" && !painelEdital.scoreProfundo && (
                  <div className="panel-section">
                    <h4>Analise de Gaps / Validacao</h4>
                    {loadingScores ? (
                      <p className="text-muted">Carregando scores de validacao...</p>
                    ) : scoresValidacao ? (
                      <div className="gaps-list">
                        {/* 6 dimensoes de score */}
                        <div style={{ marginBottom: "10px" }}>
                          {[
                            { key: "tecnico", label: "Tecnico" },
                            { key: "documental", label: "Documental" },
                            { key: "complexidade", label: "Complexidade" },
                            { key: "juridico", label: "Juridico" },
                            { key: "logistico", label: "Logistico" },
                            { key: "comercial", label: "Comercial" },
                          ].map(dim => {
                            const scores = scoresValidacao.scores as Record<string, number> | undefined;
                            const val = scores?.[dim.key] ?? null;
                            const status: "success" | "warning" | "error" = val === null ? "error" : val >= 70 ? "success" : val >= 40 ? "warning" : "error";
                            return (
                              <div key={dim.key} className="gap-item" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "4px" }}>
                                <span>{dim.label}</span>
                                <StatusBadge status={status} label={val !== null ? `${val}%` : "N/A"} size="small" />
                              </div>
                            );
                          })}
                        </div>
                        {/* Decisao GO/NO-GO */}
                        {Boolean(scoresValidacao.decisao) && (
                          <div style={{ marginBottom: "8px", padding: "6px 10px", borderRadius: "6px", backgroundColor: String(scoresValidacao.decisao) === "GO" ? "#052e16" : String(scoresValidacao.decisao) === "NO-GO" ? "#450a0a" : "#1e293b" }}>
                            <strong style={{ color: String(scoresValidacao.decisao) === "GO" ? "#22c55e" : String(scoresValidacao.decisao) === "NO-GO" ? "#ef4444" : "#eab308" }}>
                              {String(scoresValidacao.decisao)}
                            </strong>
                            {Boolean(scoresValidacao.justificativa) && (
                              <div style={{ fontSize: "12px", color: "#94a3b8", marginTop: "4px" }}>
                                {String(scoresValidacao.justificativa)}
                              </div>
                            )}
                          </div>
                        )}
                        {/* Pontos positivos */}
                        {Array.isArray(scoresValidacao.pontos_positivos) && (scoresValidacao.pontos_positivos as string[]).length > 0 && (
                          <div style={{ marginBottom: "6px" }}>
                            <div style={{ fontSize: "12px", fontWeight: 600, color: "#22c55e", marginBottom: "4px" }}>Pontos positivos:</div>
                            {(scoresValidacao.pontos_positivos as string[]).map((p, i) => (
                              <div key={i} style={{ fontSize: "12px", color: "#cbd5e1", display: "flex", gap: "4px", marginBottom: "2px" }}>
                                <span style={{ color: "#22c55e", flexShrink: 0 }}>{"\u2714"}</span>
                                <span>{p}</span>
                              </div>
                            ))}
                          </div>
                        )}
                        {/* Pontos de atencao */}
                        {Array.isArray(scoresValidacao.pontos_atencao) && (scoresValidacao.pontos_atencao as string[]).length > 0 && (
                          <div style={{ marginBottom: "6px" }}>
                            <div style={{ fontSize: "12px", fontWeight: 600, color: "#eab308", marginBottom: "4px" }}>Pontos de atencao:</div>
                            {(scoresValidacao.pontos_atencao as string[]).map((p, i) => (
                              <div key={i} style={{ fontSize: "12px", color: "#cbd5e1", display: "flex", gap: "4px", marginBottom: "2px" }}>
                                <span style={{ color: "#eab308", flexShrink: 0 }}>{"\u26A0"}</span>
                                <span>{p}</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : painelEdital.gaps.length > 0 ? (
                      /* Fallback: gaps locais da busca */
                      <div className="gaps-list">
                        {painelEdital.gaps.map((g, i) => (
                          <div key={i} className="gap-item">
                            <StatusBadge status={getGapColor(g.tipo) as "success" | "warning" | "error"} label={getGapLabel(g.tipo)} size="small" />
                            <span>{g.item}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-muted">Nenhum gap identificado</p>
                    )}
                  </div>
                  )}

                  {/* Info adicional */}
                  <div className="panel-section">
                    <div className="info-grid-compact">
                      <div className="info-item-compact">
                        <label>Valor</label>
                        <span>{formatCurrency(painelEdital.valor)}</span>
                      </div>
                      <div className="info-item-compact">
                        <label>Abertura</label>
                        <span>{painelEdital.dataAbertura}</span>
                      </div>
                      <div className="info-item-compact">
                        <label>Tipo</label>
                        <span>{painelEdital.classificacaoTipo}</span>
                      </div>
                      <div className="info-item-compact">
                        <label>Origem</label>
                        <span>{painelEdital.classificacaoOrigem}</span>
                      </div>
                    </div>
                  </div>

                  {/* Feedback de estratégia salva */}
                  {estrategiaSalva && (
                    <div className="alert alert-success" style={{ marginBottom: "8px" }}>
                      <CheckCircle size={14} /> Estrategia salva com sucesso
                    </div>
                  )}

                  {/* Acoes */}
                  <div className="panel-actions">
                    <ActionButton
                      icon={<Save size={14} />}
                      label="Salvar Estrategia"
                      variant="primary"
                      onClick={handleSalvarEstrategia}
                      loading={salvandoEstrategia}
                    />
                    <ActionButton
                      icon={painelEdital.editalSalvoId ? <CheckCircle size={14} /> : <Save size={14} />}
                      label={painelEdital.editalSalvoId ? "Ja Salvo" : "Salvar Edital"}
                      onClick={() => handleSalvarEdital(painelEdital)}
                      disabled={!!painelEdital.editalSalvoId}
                    />
                    <ActionButton
                      icon={<ExternalLink size={14} />}
                      label="Ir para Validacao"
                      onClick={() => handleIrParaValidacao(painelEdital)}
                    />
                    {painelEdital.url && (
                      <ActionButton
                        icon={<ExternalLink size={14} />}
                        label="Abrir no Portal"
                        onClick={() => window.open(painelEdital.url, "_blank")}
                      />
                    )}
                    {painelEdital.editalSalvoId && painelEdital.cnpj_orgao && (
                      <ActionButton
                        icon={<Download size={14} />}
                        label="Baixar PDF"
                        onClick={() => handleBaixarPdfEdital(painelEdital.editalSalvoId!, painelEdital.numero)}
                      />
                    )}
                  </div>

                  {/* C4: Botoes de IA */}
                  {onSendToChat && (
                    <div className="panel-section">
                      <h4>Acoes de IA</h4>
                      <div className="panel-actions">
                        <ActionButton
                          icon={<Brain size={14} />}
                          label="Classificar Edital via IA"
                          onClick={() => onSendToChat("Classifique este edital: " + painelEdital.objeto)}
                        />
                        <ActionButton
                          icon={<DollarSign size={14} />}
                          label="Recomendar Preco"
                          onClick={() => onSendToChat("Recomende preco para " + painelEdital.objeto)}
                        />
                        <ActionButton
                          icon={<History size={14} />}
                          label="Historico de Precos"
                          onClick={() => onSendToChat("Busque precos de " + painelEdital.objeto + " no PNCP")}
                        />
                      </div>
                    </div>
                  )}
                </Card>
              </div>
            )}
          </div>
        )}

        {/* Monitoramento automatico - T17 + C3 */}
        <Card
          title="Monitoramento Automatico"
          icon={<Eye size={18} />}
          actions={
            <ActionButton
              icon={<Plus size={14} />}
              label="Novo Monitoramento"
              variant="primary"
              onClick={() => setShowNovoMonitoramento(!showNovoMonitoramento)}
            />
          }
        >
          <div className="monitoramento-info">
            {/* Formulario completo para novo monitoramento (mesmos parâmetros da busca) */}
            {showNovoMonitoramento && (
              <div style={{ marginBottom: "16px", padding: "12px", backgroundColor: "#0f172a", borderRadius: "8px", border: "1px solid #334155" }}>
                <div className="form-grid form-grid-4">
                  <FormField label="Termo de busca *">
                    <TextInput
                      value={novoMonTermo}
                      onChange={setNovoMonTermo}
                      placeholder="Ex: equipamentos laboratoriais"
                    />
                  </FormField>
                  <FormField label="NCM (opcional)">
                    <TextInput
                      value={novoMonNcm}
                      onChange={setNovoMonNcm}
                      placeholder="Ex: 9018.19.90"
                    />
                  </FormField>
                  <FormField label="UFs (separadas por virgula)">
                    <TextInput
                      value={novoMonUfs}
                      onChange={setNovoMonUfs}
                      placeholder="Ex: SP, RJ, MG (vazio = todas)"
                    />
                  </FormField>
                  <FormField label="Fonte">
                    <SelectInput
                      value={novoMonFonte}
                      onChange={setNovoMonFonte}
                      options={[
                        { value: "todas", label: "Todas as fontes" },
                        ...fontesDisponiveis,
                      ]}
                    />
                  </FormField>
                </div>
                <div className="form-grid form-grid-4" style={{ marginTop: "8px" }}>
                  <FormField label="Frequencia">
                    <SelectInput
                      value={novoMonFreq}
                      onChange={setNovoMonFreq}
                      options={[
                        { value: "6h", label: "A cada 6 horas" },
                        { value: "12h", label: "A cada 12 horas" },
                        { value: "24h", label: "A cada 24 horas" },
                        { value: "semanal", label: "Semanal" },
                      ]}
                    />
                  </FormField>
                  <FormField label="Score minimo alerta">
                    <SelectInput
                      value={String(novoMonScoreMin)}
                      onChange={(v) => setNovoMonScoreMin(Number(v))}
                      options={[
                        // CV06-1/2 (Arnaldo Sprint 2 V8): adicionadas opcoes 30% e 40%
                        { value: "0", label: "Todos (sem filtro)" },
                        { value: "30", label: "30% ou mais" },
                        { value: "40", label: "40% ou mais" },
                        { value: "50", label: "50% ou mais" },
                        { value: "60", label: "60% ou mais" },
                        { value: "70", label: "70% ou mais" },
                        { value: "80", label: "80% ou mais" },
                      ]}
                    />
                  </FormField>
                  <FormField label="Incluir encerrados">
                    <SelectInput
                      value={novoMonEncerrados ? "sim" : "nao"}
                      onChange={(v) => setNovoMonEncerrados(v === "sim")}
                      options={[
                        { value: "nao", label: "Nao (somente abertos)" },
                        { value: "sim", label: "Sim" },
                      ]}
                    />
                  </FormField>
                  <div className="form-field-actions">
                    <ActionButton
                      icon={<Plus size={14} />}
                      label="Criar"
                      variant="primary"
                      onClick={async () => {
                        if (!novoMonTermo.trim()) return;
                        try {
                          const freqMap: Record<string, number> = { "6h": 6, "12h": 12, "24h": 24, "semanal": 168 };
                          const ufsArray = novoMonUfs.trim()
                            ? novoMonUfs.split(",").map(u => u.trim().toUpperCase()).filter(Boolean)
                            : null;
                          const fontesArray = novoMonFonte === "todas" ? null : [novoMonFonte];
                          await crudCreate("monitoramentos", {
                            termo: novoMonTermo.trim(),
                            ncm: novoMonNcm.trim() || null,
                            fontes: fontesArray,
                            ufs: ufsArray,
                            incluir_encerrados: novoMonEncerrados,
                            frequencia_horas: freqMap[novoMonFreq] || 24,
                            score_minimo_alerta: novoMonScoreMin,
                            ativo: true,
                          });
                          setNovoMonTermo("");
                          setNovoMonNcm("");
                          setNovoMonUfs("");
                          setNovoMonFonte("pncp");
                          setNovoMonEncerrados(false);
                          setNovoMonFreq("24h");
                          setNovoMonScoreMin(70);
                          setShowNovoMonitoramento(false);
                          await carregarMonitoramentos();
                        } catch {
                          alert("Erro ao criar monitoramento");
                        }
                      }}
                    />
                  </div>
                </div>
              </div>
            )}

            {loadingMonitoramentos ? (
              <p className="text-muted">Carregando monitoramentos...</p>
            ) : monitoramentos.length > 0 ? (
              <>
                <p><strong>Monitoramentos ativos:</strong> {monitoramentos.filter(m => m.ativo).length} de {monitoramentos.length}</p>
                <div style={{ marginTop: "8px" }}>
                  {monitoramentos.slice(0, 5).map(m => (
                    <div key={m.id} style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "6px", flexWrap: "wrap" }}>
                      <StatusBadge
                        status={m.ativo ? "success" : "neutral"}
                        label={m.ativo ? "Ativo" : "Inativo"}
                        size="small"
                      />
                      <span><strong>{m.termo}</strong></span>
                      {m.ncm && (
                        <span className="text-muted">NCM: {m.ncm}</span>
                      )}
                      {m.ufs && m.ufs.length > 0 && (
                        <span className="text-muted">({m.ufs.join(", ")})</span>
                      )}
                      {m.fontes && m.fontes.length > 0 && (
                        <span className="text-muted">[{m.fontes.join(", ")}]</span>
                      )}
                      {m.frequencia_horas && (
                        <span className="text-muted">a cada {m.frequencia_horas}h</span>
                      )}
                      {m.score_minimo_alerta && m.score_minimo_alerta > 0 && (
                        <span className="text-muted">score&ge;{m.score_minimo_alerta}%</span>
                      )}
                      {m.editais_encontrados !== undefined && m.editais_encontrados > 0 && (
                        <span className="text-muted">{m.editais_encontrados} encontrado(s)</span>
                      )}
                      {m.ultimo_check && (
                        <span className="text-muted">— ultimo: {m.ultimo_check}</span>
                      )}
                      {/* C3: Botoes Pausar e Excluir por monitoramento */}
                      <div style={{ display: "flex", gap: "4px", marginLeft: "auto" }}>
                        <button
                          title={m.ativo ? "Pausar monitoramento" : "Retomar monitoramento"}
                          onClick={async () => {
                            try {
                              await crudUpdate("monitoramentos", m.id, { ativo: !m.ativo });
                              await carregarMonitoramentos();
                            } catch {
                              alert("Erro ao atualizar monitoramento");
                            }
                          }}
                          style={{
                            padding: "3px 8px",
                            fontSize: "11px",
                            border: "1px solid #334155",
                            borderRadius: "4px",
                            backgroundColor: "transparent",
                            color: m.ativo ? "#eab308" : "#22c55e",
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            gap: "4px",
                          }}
                        >
                          <Pause size={12} />
                          {m.ativo ? "Pausar" : "Retomar"}
                        </button>
                        {/* CV06-3 (Arnaldo Sprint 2 V8): botao Editar — permite renomear
                            o termo de busca do monitoramento sem precisar recriar. */}
                        <button
                          title="Editar termo do monitoramento"
                          onClick={async () => {
                            const atual = m.termo || m.nome || "";
                            const novo = window.prompt("Editar termo do monitoramento:", atual);
                            if (novo == null) return;
                            const limpo = novo.trim();
                            if (!limpo || limpo === atual) return;
                            try {
                              await crudUpdate("monitoramentos", m.id, { termo: limpo, nome: limpo });
                              await carregarMonitoramentos();
                            } catch {
                              alert("Erro ao editar monitoramento");
                            }
                          }}
                          style={{
                            padding: "3px 8px",
                            fontSize: "11px",
                            border: "1px solid #334155",
                            borderRadius: "4px",
                            backgroundColor: "transparent",
                            color: "#60a5fa",
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            gap: "4px",
                          }}
                        >
                          Editar
                        </button>
                        <button
                          title="Excluir monitoramento"
                          onClick={async () => {
                            // CV06-4 (Arnaldo Sprint 2 V8): pedir confirmacao antes
                            // de excluir (padronizar com exclusao de lote que ja tem).
                            if (!window.confirm(`Excluir o monitoramento "${m.nome || m.termo || m.id}"? Esta acao nao pode ser desfeita.`)) return;
                            try {
                              await crudDelete("monitoramentos", m.id);
                              await carregarMonitoramentos();
                            } catch {
                              alert("Erro ao excluir monitoramento");
                            }
                          }}
                          style={{
                            padding: "3px 8px",
                            fontSize: "11px",
                            border: "1px solid #334155",
                            borderRadius: "4px",
                            backgroundColor: "transparent",
                            color: "#ef4444",
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            gap: "4px",
                          }}
                        >
                          <Trash2 size={12} />
                          Excluir
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
                {monitoramentos.length > 5 && (
                  <p className="text-muted" style={{ marginTop: "4px" }}>
                    +{monitoramentos.length - 5} monitoramento(s) adicionais
                  </p>
                )}
              </>
            ) : (
              <>
                <p className="text-muted">Nenhum monitoramento configurado.</p>
                <p style={{ marginTop: "4px" }}>Configure via chat: <em>"Monitore editais de equipamentos laboratoriais no PNCP"</em></p>
              </>
            )}
            <div style={{ marginTop: "12px" }}>
              {/* CV06-3 (Arnaldo Sprint 2 V8): rotulo "Recarregar lista" deixa claro
                  que nao executa novo crawl — so atualiza a UI a partir do banco. */}
              <ActionButton label="Recarregar lista" onClick={carregarMonitoramentos} />
            </div>
          </div>
        </Card>
          </>
          ) : (
          <>
        {/* ======== ABA DISPENSAS ======== */}

        {/* Stats dispensas */}
        <div className="stat-cards-grid">
          <StatCard
            icon={<ShoppingCart size={20} />}
            value={dispensaStats.abertas}
            label="Abertas"
            color="green"
          />
          <StatCard
            icon={<Send size={20} />}
            value={dispensaStats.cotacao_enviada}
            label="Cotacao Enviada"
            color="blue"
          />
          <StatCard
            icon={<CheckCircle size={20} />}
            value={dispensaStats.adjudicadas}
            label="Adjudicadas"
            color="purple"
          />
          <StatCard
            icon={<Calendar size={20} />}
            value={dispensaStats.encerradas}
            label="Encerradas"
            color="blue"
          />
        </div>

        {/* Buscar Dispensas PNCP */}
        <Card title="Buscar Dispensas PNCP" icon={<Search size={18} />}>
          <div className="form-grid form-grid-4">
            <FormField label="Termo de busca">
              <TextInput
                value={dispBuscaTermo}
                onChange={setDispBuscaTermo}
                placeholder="Ex: material de escritorio"
              />
            </FormField>
            <FormField label="UF">
              <TextInput
                value={dispBuscaUf}
                onChange={setDispBuscaUf}
                placeholder="Ex: SP"
              />
            </FormField>
            <FormField label="Periodo de publicacao">
              <SelectInput
                value={dispBuscaDias}
                onChange={setDispBuscaDias}
                options={[
                  { value: "30", label: "Ultimos 30 dias" },
                  { value: "60", label: "Ultimos 60 dias" },
                  { value: "90", label: "Ultimos 90 dias" },
                  { value: "180", label: "Ultimos 180 dias" },
                ]}
              />
            </FormField>
            <div style={{ display: "flex", alignItems: "flex-end", paddingBottom: "4px" }}>
              <ActionButton
                icon={<Search size={16} />}
                label="Buscar Dispensas PNCP"
                variant="primary"
                onClick={handleBuscarDispensasPNCP}
                loading={dispBuscaLoading}
              />
            </div>
          </div>
          {dispensasErro && (
            <div className="alert alert-error" style={{ marginTop: "12px" }}>
              {dispensasErro}
            </div>
          )}
        </Card>

        {/* Filtros locais */}
        <Card title="Filtros" icon={<Search size={18} />}>
          <div className="form-grid form-grid-4">
            <FormField label="Artigo">
              <SelectInput
                value={dispFiltroArtigo}
                onChange={setDispFiltroArtigo}
                options={ARTIGOS_DISPENSA}
              />
            </FormField>
            <FormField label="Valor minimo">
              <TextInput
                value={dispFiltroValorMin}
                onChange={setDispFiltroValorMin}
                placeholder="0"
              />
            </FormField>
            <FormField label="Valor maximo">
              <TextInput
                value={dispFiltroValorMax}
                onChange={setDispFiltroValorMax}
                placeholder="1000000"
              />
            </FormField>
            <FormField label="UF">
              <TextInput
                value={dispFiltroUf}
                onChange={setDispFiltroUf}
                placeholder="Ex: SP"
              />
            </FormField>
          </div>
          <div className="form-grid form-grid-4" style={{ marginTop: "8px" }}>
            <FormField label="Orgao">
              <TextInput
                value={dispFiltroOrgao}
                onChange={setDispFiltroOrgao}
                placeholder="Buscar por orgao..."
              />
            </FormField>
          </div>
        </Card>

        {/* Tabela de dispensas */}
        <Card
          title={`Dispensas (${dispensasFiltradas.length})`}
          icon={<ShoppingCart size={18} />}
          actions={
            <ActionButton
              icon={<RefreshCw size={14} />}
              label="Atualizar"
              onClick={async () => { await carregarDispensas(); await carregarDispensaStats(); }}
            />
          }
        >
          <DataTable
            data={dispensasFiltradas}
            columns={dispensasColumns}
            idKey="id"
            emptyMessage="Nenhuma dispensa encontrada. Use a busca acima para importar dispensas do PNCP."
            loading={dispensasLoading}
            defaultSortKey="prazo_dias"
            defaultSortDirection="asc"
          />
        </Card>

        {/* Modal de cotacao */}
        <Modal
          isOpen={cotacaoModalOpen}
          onClose={() => { setCotacaoModalOpen(false); setCotacaoResult(null); setCotacaoDispensaId(null); }}
          title={`Cotacao — Dispensa ${cotacaoDispensaId ? cotacaoDispensaId.substring(0, 8) + "..." : ""}`}
          size="large"
          footer={
            <button
              className="btn btn-secondary"
              onClick={() => { setCotacaoModalOpen(false); setCotacaoResult(null); setCotacaoDispensaId(null); }}
            >
              Fechar
            </button>
          }
        >
          {cotacaoLoading ? (
            <div style={{ textAlign: "center", padding: "32px" }}>
              <p className="text-muted">Gerando cotacao...</p>
            </div>
          ) : cotacaoResult ? (
            cotacaoResult.success ? (
              <div>
                {cotacaoResult.cotacao_id && (
                  <div style={{ marginBottom: "12px" }}>
                    <strong style={{ color: "#22c55e" }}>Cotacao gerada com sucesso!</strong>
                    <span className="text-muted" style={{ marginLeft: "8px" }}>ID: {cotacaoResult.cotacao_id}</span>
                  </div>
                )}
                {cotacaoResult.valor_proposto != null && (
                  <div style={{ marginBottom: "8px" }}>
                    <span style={{ color: "#64748b" }}>Valor Proposto: </span>
                    <strong>{formatCurrency(cotacaoResult.valor_proposto)}</strong>
                  </div>
                )}
                {cotacaoResult.itens && cotacaoResult.itens.length > 0 && (
                  <div style={{ marginTop: "12px" }}>
                    <h4 style={{ fontSize: "14px", marginBottom: "8px" }}>Itens da Cotacao</h4>
                    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "13px" }}>
                      <thead>
                        <tr style={{ borderBottom: "1px solid #334155", color: "#64748b" }}>
                          <th style={{ padding: "6px", textAlign: "left" }}>Descricao</th>
                          <th style={{ padding: "6px", textAlign: "right" }}>Qtd</th>
                          <th style={{ padding: "6px", textAlign: "right" }}>Vlr Unit.</th>
                          <th style={{ padding: "6px", textAlign: "right" }}>Vlr Total</th>
                        </tr>
                      </thead>
                      <tbody>
                        {cotacaoResult.itens.map((item, idx) => (
                          <tr key={idx} style={{ borderBottom: "1px solid #1e293b" }}>
                            <td style={{ padding: "6px", color: "#cbd5e1" }}>{item.descricao}</td>
                            <td style={{ padding: "6px", textAlign: "right", color: "#94a3b8" }}>{item.quantidade}</td>
                            <td style={{ padding: "6px", textAlign: "right", color: "#e2e8f0" }}>{formatCurrency(item.valor_unitario)}</td>
                            <td style={{ padding: "6px", textAlign: "right", color: "#e2e8f0" }}>{formatCurrency(item.valor_total)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {cotacaoResult.observacoes && (
                  <div style={{ marginTop: "12px", padding: "8px", backgroundColor: "#0f172a", borderRadius: "6px", fontSize: "12px", color: "#94a3b8" }}>
                    <strong>Observacoes:</strong> {cotacaoResult.observacoes}
                  </div>
                )}
              </div>
            ) : (
              <div className="alert alert-error">
                {cotacaoResult.error || "Erro ao gerar cotacao"}
              </div>
            )
          ) : null}
        </Modal>
          </>
          )}
        </TabPanel>
      </div>
    </div>
  );
}
