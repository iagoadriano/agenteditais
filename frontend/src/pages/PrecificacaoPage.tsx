import { useState, useEffect, useCallback } from "react";
import type { PageProps } from "../types";
import {
  DollarSign, Search, TrendingUp, History, Lightbulb, Package,
  Layers, Target, BarChart3, Shield, ChevronDown, ChevronUp,
  Check, AlertTriangle, Download, X, Globe, Loader2, Sparkles, FileText,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Card, DataTable, ActionButton, FormField, TextInput, SelectInput,
  TabPanel, Modal,
} from "../components/common";
import type { Column } from "../components/common";
import { crudList, crudCreate, crudUpdate, crudGet } from "../api/crud";
import { createSession, sendMessage } from "../api/client";
import { getEditais, getProdutos } from "../api/client";
import type { Edital, Produto } from "../api/client";
import { simularLanceDeterministico, getScoreCompetitividade, simularDRE } from "../api/sprint9";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Lote {
  id: string;
  edital_id: string;
  numero_lote: number;
  nome: string;
  especialidade: string | null;
  volume_exigido: number | null;
  valor_estimado: number | null;
  status: string;
  tipo_amostra?: string | null;
  equipamento_exigido?: string | null;
  observacoes_tecnicas?: string | null;
}

interface EditalItem {
  id: string;
  numero_item: number;
  descricao: string;
  unidade_medida: string;
  quantidade: number | null;
  valor_unitario_estimado: number | null;
  valor_total_estimado: number | null;
  tipo_beneficio?: string | null;
  /** Flag derivada no frontend (tipo_beneficio === "ignorado") */
  _ignorado?: boolean;
}

interface Vinculo {
  id: string;
  edital_item_id: string;
  produto_id: string;
  match_score: number | null;
  confirmado: boolean;
  volume_edital: number | null;
  rendimento_produto: number | null;
  repeticoes_amostras: number;
  repeticoes_calibradores: number;
  repeticoes_controles: number;
  volume_real_ajustado: number | null;
  quantidade_kits: number | null;
  formula_calculo: string | null;
}

interface PrecoCamada {
  id: string;
  edital_item_produto_id: string;
  custo_unitario: number | null;
  custo_fonte: string | null;
  ncm: string | null;
  icms: number | null;
  ipi: number | null;
  pis_cofins: number | null;
  isencao_icms: boolean;
  custo_base_final: number | null;
  modo_preco_base: string | null;
  markup_percentual: number | null;
  preco_base: number | null;
  valor_referencia_edital: number | null;
  valor_referencia_disponivel: boolean;
  percentual_sobre_base?: number | null;
  target_referencia: number | null;
  margem_sobre_custo: number | null;
  lance_inicial: number | null;
  lance_minimo: number | null;
  margem_minima: number | null;
  preco_medio_historico: number | null;
  preco_min_historico: number | null;
  preco_max_historico: number | null;
  qtd_registros_historico: number;
  status: string;
}

interface Comodato {
  id: string;
  edital_id: string;
  nome_equipamento: string;
  valor_equipamento: number | null;
  duracao_meses: number | null;
  valor_mensal_amortizacao: number | null;
  custo_manutencao_mensal: number | null;
  custo_instalacao: number | null;
  condicoes_especiais: string | null;
  status: string;
}

interface HistoricoPreco {
  id: string;
  produto: string;
  preco: number;
  data: string;
  edital: string;
  resultado: "ganho" | "perdido";
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (v: number | null | undefined) =>
  v != null ? new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(v) : "—";

const pct = (v: number | null | undefined) =>
  v != null ? `${v.toFixed(1)}%` : "—";

// ─── Component ────────────────────────────────────────────────────────────────

export function PrecificacaoPage(props?: PageProps) {
  const { onSendToChat } = props ?? {};

  // ── Global state ──
  const [editais, setEditais] = useState<Edital[]>([]);
  const [produtos, setProdutos] = useState<Produto[]>([]);
  const [editalId, setEditalId] = useState("");
  const [loading, setLoading] = useState(false);

  // ── Tab: Lotes (UC-P01) ──
  const [lotes, setLotes] = useState<Lote[]>([]);
  const [loteItensMap, setLoteItensMap] = useState<Record<string, string[]>>({});
  const [itensEdital, setItensEdital] = useState<EditalItem[]>([]);
  const [iaProcessing, setIaProcessing] = useState<string | null>(null);
  const [iaResponse, setIaResponse] = useState<string | null>(null);
  // Modals: Buscar na Web / ANVISA (mesmo padrão do PortfolioPage)
  const [showBuscaWebModal, setShowBuscaWebModal] = useState(false);
  const [showAnvisaModal, setShowAnvisaModal] = useState(false);
  const [buscaNomeProduto, setBuscaNomeProduto] = useState("");
  const [buscaFabricante, setBuscaFabricante] = useState("");
  const [anvisaRegistro, setAnvisaRegistro] = useState("");
  const [anvisaNomeProduto, setAnvisaNomeProduto] = useState("");
  const [loteExpandido, setLoteExpandido] = useState<string | null>(null);
  const [loteEspecialidade, setLoteEspecialidade] = useState("");
  const [loteVolume, setLoteVolume] = useState("");
  const [loteTipoAmostra, setLoteTipoAmostra] = useState("");
  const [loteEquipamento, setLoteEquipamento] = useState("");
  const [loteObservacoes, setLoteObservacoes] = useState("");

  // ── Tab: Custos e Preços (UC-P02 a UC-P06) ──
  const [vinculos, setVinculos] = useState<Vinculo[]>([]);
  const [vinculoId, setVinculoId] = useState("");
  const [camada, setCamada] = useState<PrecoCamada | null>(null);
  // UC-P02: Seleção
  const [selecaoItemId, setSelecaoItemId] = useState("");
  const [sugestoes, setSugestoes] = useState<Array<{ produto_id: string; nome: string; fabricante: string; match_score: number }>>([]);
  const [showSelecaoModal, setShowSelecaoModal] = useState(false);
  // UC-P03: Volumetria
  const [precisaVolumetria, setPrecisaVolumetria] = useState<boolean | null>(null);
  const [volEdital, setVolEdital] = useState("");
  const [rendimento, setRendimento] = useState("");
  const [repAmostras, setRepAmostras] = useState("0");
  const [repCalib, setRepCalib] = useState("0");
  const [repControles, setRepControles] = useState("0");
  // UC-P04: Custos
  const [custoUnit, setCustoUnit] = useState("");
  const [editIcms, setEditIcms] = useState("");
  const [editIpi, setEditIpi] = useState("");
  const [editPisCofins, setEditPisCofins] = useState("");
  // UC-P05: Preço base
  const [modoPrecoBase, setModoPrecoBase] = useState("markup");
  const [markup, setMarkup] = useState("");
  const [precoBaseManual, setPrecoBaseManual] = useState("");
  const [reutilizarPreco, setReutilizarPreco] = useState(false);
  // UC-P06: Referência
  const [valorRef, setValorRef] = useState("");
  const [pctSobreBase, setPctSobreBase] = useState("");

  // ── Insights IA (histórico + recomendação) ──
  const [insights, setInsights] = useState<{
    historico: { qtd_registros: number; preco_min: number | null; preco_medio: number | null; preco_max: number | null };
    recomendacao: { custo_sugerido: number | null; markup_sugerido: number | null; preco_base_sugerido: number | null; referencia_sugerida: number | null; faixa: { agressivo: number | null; ideal: number | null; conservador: number | null }; justificativa: string; fonte: string | null };
    concorrentes: Array<{ nome: string; taxa_vitoria: number; preco_medio: number; editais_ganhos: number }>;
    referencia_edital: number | null;
    tem_dados?: boolean;
    termos_tentados?: string[];
    etapa?: string;
    atas_encontradas?: number;
  } | null>(null);
  const [insightsLoading, setInsightsLoading] = useState(false);

  // ── Tab: Lances (UC-P07 + UC-P08) ──
  const [lanceInicial, setLanceInicial] = useState("");
  const [lanceMinimo, setLanceMinimo] = useState("");
  const [descontoMax, setDescontoMax] = useState("");
  const [modoInicial, setModoInicial] = useState("absoluto");
  const [modoMinimo, setModoMinimo] = useState("absoluto");
  // UC-P08: Estratégia
  const [perfil, setPerfil] = useState("quero_ganhar");
  const [cenarios, setCenarios] = useState<Record<string, unknown>[]>([]);
  const [cenarioExplicacaoIA, setCenarioExplicacaoIA] = useState<string | null>(null);
  const [cenarioExplicacaoLoading, setCenarioExplicacaoLoading] = useState(false);
  const [disputaSimulacaoMD, setDisputaSimulacaoMD] = useState<string | null>(null);
  const [disputaLoading, setDisputaLoading] = useState(false);

  // ── Tab: Estratégia — Sprint 9 ──
  // UC-LA01: Simulador Determinístico
  const [simDetOpen, setSimDetOpen] = useState(false);
  const [simDetNumRodadas, setSimDetNumRodadas] = useState("10");
  const [simDetTipoDecremento, setSimDetTipoDecremento] = useState("fixo_reais");
  const [simDetValorDecremento, setSimDetValorDecremento] = useState("");
  const [simDetNumConcorrentes, setSimDetNumConcorrentes] = useState("3");
  const [simDetPerfil, setSimDetPerfil] = useState("quero_ganhar");
  const [simDetLoading, setSimDetLoading] = useState(false);
  const [simDetResult, setSimDetResult] = useState<Record<string, unknown> | null>(null);
  // UC-SC01: Score Competitividade
  const [scoreComp, setScoreComp] = useState<Record<string, unknown> | null>(null);
  const [scoreCompLoading, setScoreCompLoading] = useState(false);
  // UC-SC05: Simular DRE
  const [dreResult, setDreResult] = useState<Record<string, unknown> | null>(null);
  const [dreLoading, setDreLoading] = useState(false);

  // ── Tab: Histórico (UC-P09) + Comodato (UC-P10) ──
  const [termoBusca, setTermoBusca] = useState("");
  const [historico, setHistorico] = useState<HistoricoPreco[]>([]);
  const [histStats, setHistStats] = useState<{ media: number; min: number; max: number } | null>(null);
  const [comodatos, setComodatos] = useState<Comodato[]>([]);
  // Visão consolidada: camadas de TODOS os vínculos do edital
  const [todasCamadas, setTodasCamadas] = useState<Record<string, PrecoCamada>>({});
  const [comodatoNome, setComodatoNome] = useState("");
  const [comodatoValor, setComodatoValor] = useState("");
  const [comodatoMeses, setComodatoMeses] = useState("");

  // ── Load data ──
  useEffect(() => {
    (async () => {
      try { setEditais(await getEditais()); } catch { setEditais([]); }
      try { setProdutos(await getProdutos()); } catch { setProdutos([]); }
    })();
  }, []);

  const editalOptions = [
    { value: "", label: "Selecione um edital..." },
    ...editais.map((e) => ({ value: e.id ?? e.numero, label: `${e.numero} — ${e.orgao}` })),
  ];

  // ── Load lotes when edital changes ──
  const loadLotes = useCallback(async (eid: string) => {
    if (!eid) { setLotes([]); setItensEdital([]); return; }
    setLoading(true);
    try {
      const res = await crudList("lotes", { parent_id: eid, limit: 100 });
      const lotesData = (res.items as unknown as Lote[]) || [];
      setLotes(lotesData);
      const itensRes = await crudList("editais-itens", { parent_id: eid, limit: 200 });
      const itensComIgnorado = ((itensRes.items || []) as Record<string, unknown>[]).map(it => ({
        ...it,
        _ignorado: it.tipo_beneficio === "ignorado",
      }));
      setItensEdital(itensComIgnorado as unknown as EditalItem[]);
      // Load lote_itens para saber quais itens pertencem a cada lote
      const loteItensMap: Record<string, string[]> = {};
      for (const lote of lotesData) {
        try {
          const liRes = await crudList("lote-itens", { parent_id: lote.id, limit: 200 });
          loteItensMap[lote.id] = ((liRes.items || []) as Record<string, unknown>[]).map(li => String(li.edital_item_id));
        } catch { loteItensMap[lote.id] = []; }
      }
      setLoteItensMap(loteItensMap);
      // Load vinculos — filtrar apenas itens deste edital
      const allItemIds = new Set(itensComIgnorado.map((i) => (i as Record<string, unknown>).id as string));
      const vRes = await crudList("edital-item-produto", { limit: 500 });
      const allVinculos = (vRes.items as unknown as Vinculo[]) || [];
      const vinculosFiltrados = allVinculos.filter(v => allItemIds.has(v.edital_item_id));
      setVinculos(vinculosFiltrados);
      // Load camadas de TODOS os vínculos para visão consolidada
      const camadasMap: Record<string, PrecoCamada> = {};
      for (const v of vinculosFiltrados) {
        try {
          const pcRes = await crudList("preco-camadas", { parent_id: v.id, limit: 1 });
          if (pcRes.items?.length > 0) camadasMap[v.id] = pcRes.items[0] as unknown as PrecoCamada;
        } catch { /* ignore */ }
      }
      setTodasCamadas(camadasMap);
      // Load comodatos
      const cRes = await crudList("comodatos", { parent_id: eid, limit: 50 });
      setComodatos((cRes.items as unknown as Comodato[]) || []);
    } catch { /* empty */ }
    setLoading(false);
  }, []);

  useEffect(() => { if (editalId) loadLotes(editalId); }, [editalId, loadLotes]);

  // ── Load Score Competitividade (UC-SC01) when edital changes ──
  useEffect(() => {
    if (!editalId) { setScoreComp(null); return; }
    (async () => {
      setScoreCompLoading(true);
      try {
        const res = await getScoreCompetitividade(editalId);
        setScoreComp(res.success !== false ? res : null);
      } catch { setScoreComp(null); }
      finally { setScoreCompLoading(false); }
    })();
  }, [editalId]);

  // ── Load camada when vinculo changes → preencher campos do banco ──
  useEffect(() => {
    if (!vinculoId) { setCamada(null); return; }
    (async () => {
      try {
        const res = await crudList("preco-camadas", { parent_id: vinculoId, limit: 1 });
        const items = res.items as unknown as PrecoCamada[];
        if (items.length > 0) {
          const c = items[0];
          setCamada(c);
          // Inicializar campos com valores salvos no banco
          if (c.custo_unitario) setCustoUnit(String(Number(c.custo_unitario)));
          if (c.markup_percentual) setMarkup(String(Number(c.markup_percentual)));
          if (c.preco_base && !c.markup_percentual) setPrecoBaseManual(String(Number(c.preco_base)));
          if (c.modo_preco_base) setModoPrecoBase(c.modo_preco_base);
          if (c.valor_referencia_edital) setValorRef(String(Number(c.valor_referencia_edital)));
          if (c.lance_inicial) setLanceInicial(String(Number(c.lance_inicial)));
          if (c.lance_minimo) setLanceMinimo(String(Number(c.lance_minimo)));
        } else {
          setCamada(null);
          setCustoUnit(""); setMarkup(""); setPrecoBaseManual(""); setValorRef(""); setPctSobreBase("");
          setLanceInicial(""); setLanceMinimo("");
        }
      } catch { setCamada(null); }
    })();
  }, [vinculoId]);

  // ── Detecção de necessidade de conversão + pré-preenchimento via especificações ──
  useEffect(() => {
    if (!vinculoId) { setPrecisaVolumetria(null); return; }
    const v = vinculos.find(vv => vv.id === vinculoId);
    if (!v) { setPrecisaVolumetria(null); return; }
    const item = itensEdital.find(i => i.id === v.edital_item_id);
    const prod = produtos.find(p => p.id === v.produto_id);
    const desc = ((item?.descricao || "") + " " + (prod?.nome || "")).toLowerCase()
      .normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    const cat = (prod?.categoria || "").toLowerCase();

    // Termos que indicam conversão (produto vendido em embalagem com rendimento)
    const termosVolumetria = ["kit", "reagente", "caixa com", "frasco", "testes", "determinacoes", "dosagens", "ensaios", "reacoes"];
    // Termos que indicam compra unitária (sem conversão)
    const termosUnitario = ["microscopio", "autoclave", "centrifuga", "equipamento", "impressora", "computador", "monitor", "balanca"];

    const temTermoVol = termosVolumetria.some(t => desc.includes(t)) || cat === "reagente";
    const temTermoUnit = termosUnitario.some(t => desc.includes(t)) || cat === "equipamento";

    if (temTermoUnit && !temTermoVol) setPrecisaVolumetria(false);
    else if (temTermoVol) setPrecisaVolumetria(true);
    else setPrecisaVolumetria(false);

    // Pré-preencher: quantidade do edital
    const qtdItem = item?.quantidade;
    if (qtdItem && Number(qtdItem) > 0) setVolEdital(String(Number(qtdItem)));
    else setVolEdital("");

    // Buscar especificações do produto para rendimento e repetições
    if (prod) {
      (async () => {
        try {
          const specsRes = await crudList("produtos-especificacoes", { parent_id: prod.id, limit: 50 });
          const specs = (specsRes.items || []) as Record<string, unknown>[];
          const getSpec = (nome: string) => {
            const s = specs.find(sp => String(sp.nome_especificacao || "").toLowerCase().includes(nome.toLowerCase()));
            return s ? String(s.valor || "") : "";
          };

          // Rendimento: especificação do produto é fonte primária, vínculo é fallback
          const rendSpec = Number(getSpec("Rendimento") || 0);
          const rendVinc = Number(v.rendimento_produto || 0);
          if (rendSpec > 0) setRendimento(String(rendSpec));
          else if (rendVinc > 0) setRendimento(String(rendVinc));
          else setRendimento("");

          // Repetições: especificação é fonte primária, vínculo é fallback
          const repAmSpec = Number(getSpec("Amostras") || 0);
          const repCalSpec = Number(getSpec("Calibradores") || 0);
          const repCtSpec = Number(getSpec("Controles") || 0);
          setRepAmostras(String(repAmSpec || Number(v.repeticoes_amostras) || 0));
          setRepCalib(String(repCalSpec || Number(v.repeticoes_calibradores) || 0));
          setRepControles(String(repCtSpec || Number(v.repeticoes_controles) || 0));

          // Se encontrou rendimento na spec, forçar detecção de conversão
          if (rendSpec && Number(rendSpec) > 0) setPrecisaVolumetria(true);
        } catch {
          // Sem especificações — usar dados do vínculo
          setRendimento(v.rendimento_produto ? String(v.rendimento_produto) : "");
          setRepAmostras(String(v.repeticoes_amostras || 0));
          setRepCalib(String(v.repeticoes_calibradores || 0));
          setRepControles(String(v.repeticoes_controles || 0));
        }
      })();
    } else {
      setRendimento("");
      setRepAmostras("0");
      setRepCalib("0");
      setRepControles("0");
    }
  }, [vinculoId, vinculos, itensEdital, produtos]);

  // ── Helper: aplicar insights nos campos ──
  const _aplicarInsights = useCallback((data: Record<string, unknown>) => {
    if (data.tem_dados && data.recomendacao) {
      const rec = data.recomendacao as Record<string, unknown>;
      if (rec.custo_sugerido && !camada?.custo_unitario) setCustoUnit(String(rec.custo_sugerido));
      if (rec.preco_base_sugerido && !camada?.preco_base) {
        setModoPrecoBase("manual");
        setPrecoBaseManual(String(rec.preco_base_sugerido));
      }
      if ((data.referencia_edital || rec.referencia_sugerida) && !camada?.valor_referencia_edital) {
        setValorRef(String(data.referencia_edital || rec.referencia_sugerida));
      }
      if (rec.lance_inicial_sugerido && !camada?.lance_inicial) setLanceInicial(String(rec.lance_inicial_sugerido));
      if (rec.lance_minimo_sugerido && !camada?.lance_minimo) setLanceMinimo(String(rec.lance_minimo_sugerido));
    }
  }, [camada]);

  // ── Buscar insights IA ao selecionar vínculo (salvo primeiro, PNCP se necessário) ──
  useEffect(() => {
    if (!vinculoId) { setInsights(null); return; }
    setInsightsLoading(true);
    setInsights(null);
    const token = localStorage.getItem("editais_ia_access_token");
    const headers = { Authorization: token ? `Bearer ${token}` : "" };

    // 1. Tentar carregar insights salvos (instantâneo)
    fetch(`/api/precificacao/${vinculoId}/insights-salvos`, { headers })
      .then(r => r.json())
      .then(saved => {
        if (saved.saved && saved.success && saved.tem_dados) {
          setInsights(saved);
          _aplicarInsights(saved);
          setInsightsLoading(false);
          return;
        }
        // 2. Se não tem salvo → chamar pipeline completo (PNCP)
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 45000);
        fetch(`/api/precificacao/${vinculoId}/insights`, { headers, signal: controller.signal })
          .then(r2 => r2.json())
          .then(data => {
            if (data.success) { setInsights(data); _aplicarInsights(data); }
          })
          .catch(() => {})
          .finally(() => { clearTimeout(timeout); setInsightsLoading(false); });
      })
      .catch(() => { setInsightsLoading(false); });
  }, [vinculoId, _aplicarInsights]);

  // ── Handlers ──

  const handleCriarLotes = async () => {
    if (!editalId) return;
    if (itensEdital.length === 0) return;
    // Criar lote via CRUD com todos os itens existentes
    try {
      const valorTotal = itensEdital.reduce((s, i) => s + (i.valor_total_estimado || 0), 0);
      const lote = await crudCreate("lotes", {
        edital_id: editalId,
        numero_lote: lotes.length + 1,
        nome: `Lote ${String(lotes.length + 1).padStart(2, "0")}`,
        valor_estimado: valorTotal,
        status: "rascunho",
      });
      // Vincular itens ao lote
      const loteId = (lote as Record<string, unknown>).id as string;
      for (let i = 0; i < itensEdital.length; i++) {
        await crudCreate("lote-itens", {
          lote_id: loteId,
          edital_item_id: itensEdital[i].id,
          ordem: i + 1,
        });
      }
      loadLotes(editalId);
    } catch { /* */ }
  };

  const handleSalvarLote = async (loteId: string) => {
    try {
      await crudUpdate("lotes", loteId, {
        especialidade: loteEspecialidade || undefined,
        volume_exigido: loteVolume ? Number(loteVolume) : undefined,
        tipo_amostra: loteTipoAmostra || undefined,
        equipamento_exigido: loteEquipamento || undefined,
        observacoes_tecnicas: loteObservacoes || undefined,
        status: "configurado",
      });
      loadLotes(editalId);
    } catch { /* */ }
  };

  const handleSelecaoPortfolio = async (itemId: string) => {
    setSelecaoItemId(itemId);
    // Carregar produtos e ordenar por relevância ao item
    try {
      const res = await crudList("produtos", { limit: 100 });
      const prods = res.items as unknown as Array<{ id: string; nome: string; fabricante: string; categoria: string }>;
      // Encontrar descrição do item para match
      const item = itensEdital.find(it => it.id === itemId);
      const descItem = (item?.descricao || "").toLowerCase();
      // Calcular score de match simples (palavras em comum)
      const palavrasItem = descItem.split(/\s+/).filter(w => w.length > 3);
      const sugestoesSorted = prods.map(p => {
        const nomeLower = p.nome.toLowerCase();
        const matchCount = palavrasItem.filter(w => nomeLower.includes(w)).length;
        return { produto_id: p.id, nome: p.nome, fabricante: p.fabricante || "—", categoria: p.categoria || "", match_score: matchCount };
      }).sort((a, b) => b.match_score - a.match_score);
      setSugestoes(sugestoesSorted);
    } catch (err) { console.error("[SELECAO] Erro ao carregar produtos:", err); }
    setShowSelecaoModal(true);
  };

  const handleConfirmarSelecao = async (produtoId: string) => {
    try {
      // Buscar vínculo existente (no state OU no banco)
      let existente = vinculos.find(v => v.edital_item_id === selecaoItemId);
      if (!existente) {
        // Tentar buscar no banco (pode existir mas não estar no state filtrado)
        try {
          const dbRes = await crudList("edital-item-produto", { parent_id: selecaoItemId, limit: 1 });
          const dbItems = (dbRes.items || []) as unknown as Vinculo[];
          if (dbItems.length > 0) existente = dbItems[0];
        } catch { /* ignore */ }
      }
      if (existente) {
        try {
          await crudUpdate("edital-item-produto", existente.id, {
            produto_id: produtoId,
            match_score: 100,
            confirmado: true,
          });
        } catch {
          // Se update falha (ex: constraint), deletar e recriar
          const { crudDelete } = await import("../api/crud");
          await crudDelete("edital-item-produto", existente.id);
          await crudCreate("edital-item-produto", {
            edital_item_id: selecaoItemId,
            produto_id: produtoId,
            match_score: 100,
            confirmado: true,
          });
        }
      } else {
        await crudCreate("edital-item-produto", {
          edital_item_id: selecaoItemId,
          produto_id: produtoId,
          match_score: 100,
          confirmado: true,
        });
      }
      setShowSelecaoModal(false);
      loadLotes(editalId);
      alert("Produto vinculado com sucesso!");
    } catch (err) {
      console.error("[SELECAO] Erro:", err);
      alert("Erro ao vincular produto.");
    }
  };

  const handleCalcVolume = async () => {
    if (!vinculoId) return;
    setLoading(true);
    try {
      const vol = Number(volEdital) || 0;
      const rend = Number(rendimento) || 1;
      const rAmostras = Number(repAmostras) || 0;
      const rCalib = Number(repCalib) || 0;
      const rControles = Number(repControles) || 0;
      const total = vol + rAmostras + rCalib + rControles;
      const kits = Math.ceil(total / rend);
      const formula = `(${vol} + ${rAmostras} + ${rCalib} + ${rControles}) / ${rend} = ${(total/rend).toFixed(3)} → ${kits} kits`;
      await crudUpdate("edital-item-produto", vinculoId, {
        volume_edital: vol,
        rendimento_produto: rend,
        repeticoes_amostras: rAmostras,
        repeticoes_calibradores: rCalib,
        repeticoes_controles: rControles,
        volume_real_ajustado: total,
        quantidade_kits: kits,
        formula_calculo: formula,
      });
      // Refresh
      const v = await crudGet("edital-item-produto", vinculoId) as unknown as Vinculo;
      setVinculos(prev => prev.map(x => x.id === vinculoId ? v : x));
      alert(`Conversão salva! ${kits} embalagens/kits necessários.`);
    } catch (err) {
      console.error("[VOLUMETRIA] Erro:", err);
      alert(`Erro ao calcular: ${err instanceof Error ? err.message : "Erro desconhecido"}`);
    } finally {
      setLoading(false);
    }
  };

  const _fetchPrecif = async (url: string, body: Record<string, unknown>) => {
    const token = localStorage.getItem("editais_ia_access_token");
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: token ? `Bearer ${token}` : "" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!data.success) throw new Error(data.error || "Erro");
    return data;
  };

  // Helper: recarregar camada do banco e atualizar todasCamadas
  const _recarregarCamada = async () => {
    const res = await crudList("preco-camadas", { parent_id: vinculoId, limit: 1 });
    if (res.items?.length > 0) {
      const c = res.items[0] as unknown as PrecoCamada;
      setCamada(c);
      setTodasCamadas(prev => ({ ...prev, [vinculoId]: c }));
      return c;
    }
    return null;
  };

  const handleSalvarCustos = async () => {
    if (!vinculoId) return;
    setLoading(true);
    try {
      await _fetchPrecif(`/api/precificacao/${vinculoId}/custos`, {
        custo_unitario: custoUnit ? parseFloat(custoUnit) : null,
      });
      const c = await _recarregarCamada();
      // CASCATA: recalcular B (se markup) e E (lance mínimo)
      const msgs = ["Custos salvos."];
      if (c?.custo_base_final) {
        const custoFinal = Number(c.custo_base_final);
        // B: se markup definido, recalcular preço base
        const mk = markup ? parseFloat(markup) : (c.markup_percentual ? Number(c.markup_percentual) : null);
        if (mk && mk > 0 && modoPrecoBase === "markup") {
          const novoB = (custoFinal * (1 + mk / 100)).toFixed(2);
          setPrecoBaseManual(novoB);
          msgs.push(`Preço Base recalculado: R$ ${novoB}`);
        }
        // E: lance mínimo = custo + 10%
        const novoE = (custoFinal * 1.10).toFixed(2);
        setLanceMinimo(novoE);
        msgs.push(`Lance Mínimo recalculado: R$ ${novoE}`);
      }
      alert(msgs.join(" "));
    } catch (e) { alert(e instanceof Error ? e.message : "Erro ao salvar custos"); }
    finally { setLoading(false); }
  };

  const handleSalvarPrecoBase = async () => {
    if (!vinculoId) return;
    setLoading(true);
    try {
      await _fetchPrecif(`/api/precificacao/${vinculoId}/preco-base`, {
        modo: modoPrecoBase === "markup" ? "custo_markup" : "manual",
        markup_percentual: modoPrecoBase === "markup" && markup ? parseFloat(markup) : null,
        preco_base: modoPrecoBase !== "markup" && precoBaseManual ? parseFloat(precoBaseManual) : null,
      });
      const c = await _recarregarCamada();
      // CASCATA: recalcular C (se % definido) e D (lance inicial)
      const msgs = ["Preço Base salvo."];
      if (c?.preco_base) {
        const pb = Number(c.preco_base);
        // C: se % sobre base definido, recalcular referência
        const pct = pctSobreBase ? parseFloat(pctSobreBase) : (c.percentual_sobre_base ? Number(c.percentual_sobre_base) : null);
        if (pct && pct > 0) {
          const novoC = (pb * pct / 100).toFixed(2);
          setValorRef(novoC);
          msgs.push(`Referência recalculada: R$ ${novoC}`);
        }
        // D: lance inicial = preço base
        setLanceInicial(pb.toFixed(2));
        msgs.push(`Lance Inicial recalculado: R$ ${pb.toFixed(2)}`);
      }
      alert(msgs.join(" "));
    } catch (e) { alert(e instanceof Error ? e.message : "Erro ao salvar preço base"); }
    finally { setLoading(false); }
  };

  const handleSalvarReferencia = async () => {
    if (!vinculoId) return;
    setLoading(true);
    try {
      await _fetchPrecif(`/api/precificacao/${vinculoId}/referencia`, {
        valor_referencia: valorRef ? parseFloat(valorRef) : null,
        percentual_sobre_base: pctSobreBase ? parseFloat(pctSobreBase) : null,
      });
      await _recarregarCamada();
      alert("Valor de referência salvo!");
    } catch (e) { alert(e instanceof Error ? e.message : "Erro ao salvar referência"); }
    finally { setLoading(false); }
  };

  const handleSalvarLances = async () => {
    if (!vinculoId) return;
    // Validação de prejuízo
    const custoBase = camada?.custo_base_final ? Number(camada.custo_base_final) : 0;
    const minVal = lanceMinimo ? parseFloat(lanceMinimo) : 0;
    const iniVal = lanceInicial ? parseFloat(lanceInicial) : 0;
    if (custoBase > 0 && minVal > 0 && minVal < custoBase) {
      const margem = ((minVal - custoBase) / custoBase * 100).toFixed(1);
      if (!window.confirm(`⚠️ ATENÇÃO: Lance mínimo (R$ ${minVal.toFixed(2)}) está ABAIXO do custo (R$ ${custoBase.toFixed(2)}).\nMargem: ${margem}% — PREJUÍZO!\n\nDeseja salvar mesmo assim?`)) return;
    }
    if (iniVal > 0 && minVal > 0 && minVal > iniVal) {
      if (!window.confirm(`⚠️ Lance mínimo (R$ ${minVal.toFixed(2)}) é MAIOR que o lance inicial (R$ ${iniVal.toFixed(2)}).\n\nDeseja salvar mesmo assim?`)) return;
    }
    setLoading(true);
    try {
      await _fetchPrecif(`/api/precificacao/${vinculoId}/lances`, {
        lance_inicial: lanceInicial ? parseFloat(lanceInicial) : null,
        lance_minimo: lanceMinimo ? parseFloat(lanceMinimo) : null,
        modo_inicial: modoInicial,
        modo_minimo: modoMinimo,
        desconto_maximo_pct: descontoMax ? parseFloat(descontoMax) : null,
      });
      await _recarregarCamada();
      alert("Lances salvos!");
    } catch (e) { alert(e instanceof Error ? e.message : "Erro ao salvar lances"); }
    finally { setLoading(false); }
  };

  const handleSimularEstrategia = async () => {
    if (!editalId) return;
    setLoading(true);
    try {
      const result = await _fetchPrecif(`/api/precificacao/${editalId}/estrategia`, { perfil });
      // Backend retorna: cenarios: [{item, cenario_1: {valor, margem, label}, cenario_2, cenario_3}]
      let cens: Record<string, unknown>[] = [];
      if (Array.isArray(result.cenarios)) {
        // Cada elemento é um item com cenario_1/2/3 dentro
        for (const itemCen of result.cenarios) {
          const c1 = itemCen.cenario_1 as Record<string, unknown> | undefined;
          const c2 = itemCen.cenario_2 as Record<string, unknown> | undefined;
          const c3 = itemCen.cenario_3 as Record<string, unknown> | undefined;
          if (c1) cens.push(c1);
          if (c2) cens.push(c2);
          if (c3) cens.push(c3);
        }
      }
      // Substituir cenários (nova simulação limpa os anteriores)
      setCenarios(cens);
      setCenarioExplicacaoIA(null); // Limpar explicação anterior
      if (cens.length > 0) {
        alert(`Simulação concluída! ${cens.length} cenários. Use "Análise por IA" para análise detalhada.`);
      } else {
        alert("Nenhum cenário gerado. Verifique se custos e lances estão salvos na aba Custos e Preços.");
      }
    } catch (e) { alert(e instanceof Error ? e.message : "Erro ao simular estratégia"); }
    finally { setLoading(false); }
  };

  // Abrir explicação em nova aba (MD/PDF)
  const handleExportarExplicacaoCenarios = () => {
    if (!cenarioExplicacaoIA) return;
    const now = new Date();
    const dataHora = now.toLocaleString("pt-BR");
    const prod = vinculoId ? produtos.find(p => p.id === vinculos.find(v => v.id === vinculoId)?.produto_id) : null;
    const ed = editais.find(e => (e.id ?? e.numero) === editalId);

    let md = `# Análise de Cenários de Disputa\n\n`;
    md += `**Data:** ${dataHora}\n`;
    md += `**Edital:** ${ed?.numero || editalId} — ${ed?.orgao || ""}\n`;
    md += `**Produto:** ${prod?.nome || ""}\n`;
    md += `**Estratégia:** ${perfil === "quero_ganhar" ? "Quero Ganhar" : "Não Ganhei no Mínimo"}\n\n`;
    md += `---\n\n`;
    md += `## Cenários\n\n`;
    md += `| Cenário | Valor | Margem |\n|---|---|---|\n`;
    for (const c of cenarios.slice(0, 6)) {
      md += `| ${c.label} | R$ ${Number(c.valor || 0).toFixed(2)} | ${Number(c.margem || 0).toFixed(1)}% |\n`;
    }
    md += `\n---\n\n`;
    md += cenarioExplicacaoIA;

    const tableRegex = /(\|.+\|\n)+/g;
    let html = md.replace(tableRegex, (tableBlock) => {
      const rows = tableBlock.trim().split('\n').filter(r => r.trim());
      if (rows.length < 2) return tableBlock;
      let t = '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;border-color:#334155;margin:8px 0;width:100%;font-size:13px;">\n';
      rows.forEach((row, ri) => {
        if (ri === 1 && row.match(/^\|[\s-|]+\|$/)) return;
        const cells = row.split('|').filter((_, ci, arr) => ci > 0 && ci < arr.length - 1).map(c => c.trim());
        const tag = ri === 0 ? 'th' : 'td';
        const bg = ri === 0 ? ' style="background:#1e293b;color:#94a3b8;text-align:left;"' : '';
        t += '<tr>' + cells.map(c => `<${tag}${bg}>${c}</${tag}>`).join('') + '</tr>\n';
      });
      t += '</table>\n';
      return t;
    });
    html = html
      .replace(/^### (.+)$/gm, '<h3 style="color:#818cf8;margin:24px 0 12px;">$1</h3>')
      .replace(/^## (.+)$/gm, '<h2 style="color:#a78bfa;margin:32px 0 16px;">$1</h2>')
      .replace(/^# (.+)$/gm, '<h1 style="color:#e2e8f0;margin:0 0 24px;">$1</h1>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/^- (.+)$/gm, '<div style="padding:2px 0 2px 16px;">• $1</div>')
      .replace(/^---$/gm, '<hr style="border:none;border-top:1px solid #334155;margin:24px 0;"/>')
      .replace(/\n/g, '<br/>');

    const fullHtml = `<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Análise de Cenários — ${dataHora}</title>
<style>body{background:#0f172a;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,monospace;max-width:1100px;margin:0 auto;padding:64px 24px 32px;line-height:1.6}table{font-size:13px}th{font-weight:600}td,th{padding:6px 10px;border:1px solid #334155}tr:nth-child(even){background:#1e293b}strong{color:#f1f5f9}@media print{body{background:white;color:#1e293b;padding-top:0}h1,h2,h3,strong{color:#1e293b}td,th{border-color:#cbd5e1}tr:nth-child(even){background:#f1f5f9}.toolbar{display:none!important}}.toolbar{position:fixed;top:0;left:0;right:0;z-index:1000;background:#1e293b;border-bottom:2px solid #334155;padding:10px 24px;display:flex;gap:12px;align-items:center}.toolbar button{padding:8px 18px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600}.btn-md{background:#3b82f6;color:white}.btn-pdf{background:#8b5cf6;color:white}.toolbar span{color:#94a3b8;font-size:13px;margin-left:auto}</style></head><body>
<div class="toolbar"><button class="btn-md" onclick="baixarMD()">📥 Baixar MD</button><button class="btn-pdf" onclick="window.print()">📄 Baixar PDF</button><span>${dataHora}</span></div>
${html}
<script>var mdContent=${JSON.stringify(md)};function baixarMD(){var b=new Blob(['\\uFEFF'+mdContent],{type:'text/markdown;charset=utf-8;'});var u=URL.createObjectURL(b);var a=document.createElement('a');a.href=u;a.download='analise_cenarios_${now.toISOString().slice(0, 10)}.md';a.click()}</script></body></html>`;
    window.open(URL.createObjectURL(new Blob([fullHtml], { type: 'text/html;charset=utf-8' })), '_blank');
  };

  const handleBuscarHistorico = async () => {
    if (!termoBusca) return;
    setLoading(true);
    setHistStats(null);
    setHistorico([]);
    try {
      // Tentar busca no CRUD (empresa_vencedora)
      const res = await crudList("precos-historicos", { q: termoBusca, limit: 50 });
      let items = (res.items || []) as Record<string, unknown>[];

      // Se não encontrou, buscar todos e filtrar localmente pelo termo
      if (items.length === 0) {
        const allRes = await crudList("precos-historicos", { limit: 200 });
        const allItems = (allRes.items || []) as Record<string, unknown>[];
        const termoLower = termoBusca.toLowerCase();
        items = allItems.filter(it => {
          const venc = String(it.empresa_vencedora || "").toLowerCase();
          const fonte = String(it.fonte || "").toLowerCase();
          const edObj = String(it.edital_objeto || it.edital || "").toLowerCase();
          return venc.includes(termoLower) || fonte.includes(termoLower) || edObj.includes(termoLower);
        });
      }

      // Se AINDA não encontrou, buscar todos do edital atual
      if (items.length === 0 && editalId) {
        const edRes = await crudList("precos-historicos", { parent_id: editalId, limit: 200 });
        items = (edRes.items || []) as Record<string, unknown>[];
      }

      const mapped: HistoricoPreco[] = items.map((item) => ({
        id: String(item.id ?? ""),
        produto: String(item.empresa_vencedora ?? item.produto ?? ""),
        preco: Number(item.preco_vencedor ?? item.preco ?? 0),
        data: String(item.data_homologacao ?? item.data_registro ?? item.data ?? ""),
        edital: String(item.edital_objeto ?? item.edital ?? ""),
        resultado: (item.resultado === "vitoria" ? "ganho" : "perdido") as "ganho" | "perdido",
      }));
      setHistorico(mapped);
      const vals = mapped.map(h => h.preco).filter(v => v > 0);
      if (vals.length > 0) {
        setHistStats({
          media: vals.reduce((a, b) => a + b, 0) / vals.length,
          min: Math.min(...vals),
          max: Math.max(...vals),
        });
      } else {
        alert(`Nenhum registro encontrado para "${termoBusca}". Tente: coagulação, reagente, ou o nome do concorrente.`);
      }
    } catch {
      if (onSendToChat) onSendToChat(`busque preços históricos de ${termoBusca} no PNCP`);
    }
    setLoading(false);
  };

  const handleSalvarComodato = async () => {
    if (!editalId) return;
    try {
      const meses = Number(comodatoMeses) || 0;
      const valor = Number(comodatoValor.replace(/\./g, "").replace(",", ".")) || 0;
      await crudCreate("comodatos", {
        edital_id: editalId,
        nome_equipamento: comodatoNome || "Equipamento",
        valor_equipamento: valor,
        duracao_meses: meses,
        valor_mensal_amortizacao: meses > 0 ? valor / meses : null,
      });
      loadLotes(editalId);
      setComodatoNome(""); setComodatoValor(""); setComodatoMeses("");
    } catch { /* */ }
  };

  const handleExportCSV = () => {
    if (historico.length === 0) return;
    const header = "Produto;Preco;Data;Edital;Resultado\n";
    const rows = historico.map((h) => `${h.produto};${h.preco};${h.data};${h.edital};${h.resultado}`).join("\n");
    const blob = new Blob([header + rows], { type: "text/csv;charset=utf-8;" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "historico-precos.csv";
    link.click();
  };

  // ── Relatório de Custos e Preços ──
  const handleRelatorioCustoPreco = () => {
    const v = vinculos.find(vv => vv.id === vinculoId);
    const item = v ? itensEdital.find(i => i.id === v.edital_item_id) : null;
    const prod = v ? produtos.find(p => p.id === v.produto_id) : null;
    const ed = editais.find(e => (e.id ?? e.numero) === editalId);
    const lote = Object.entries(loteItensMap).find(([, ids]) => v && ids.includes(v.edital_item_id));
    const loteObj = lote ? lotes.find(l => l.id === lote[0]) : null;

    const now = new Date();
    const dataHora = now.toLocaleString("pt-BR");
    let md = `# Relatório de Custos e Preços\n\n`;
    md += `**Data:** ${dataHora}\n\n`;
    md += `---\n\n`;
    md += `## 1. Identificação\n\n`;
    md += `| Campo | Valor |\n|---|---|\n`;
    md += `| **Edital** | ${ed?.numero || editalId} |\n`;
    md += `| **Órgão** | ${ed?.orgao || "—"} |\n`;
    md += `| **Lote** | ${loteObj ? `${loteObj.numero_lote} — ${loteObj.nome}` : "—"} |\n`;
    md += `| **Item** | ${item?.descricao?.slice(0, 100) || "—"} |\n`;
    md += `| **Produto** | ${prod?.nome || "—"} |\n`;
    md += `| **Fabricante** | ${prod?.fabricante || "—"} |\n`;
    md += `| **Quantidade** | ${item?.quantidade || "—"} |\n`;
    md += `\n---\n\n`;

    // Conversão de quantidade
    if (curVinculo?.formula_calculo) {
      md += `## 2. Conversão de Quantidade\n\n`;
      md += `| Campo | Valor |\n|---|---|\n`;
      md += `| **Volume do Edital** | ${curVinculo.volume_edital || "—"} |\n`;
      md += `| **Rendimento por Embalagem** | ${curVinculo.rendimento_produto || "—"} |\n`;
      md += `| **Repetições (Amostras/Calib./Controles)** | ${curVinculo.repeticoes_amostras}/${curVinculo.repeticoes_calibradores}/${curVinculo.repeticoes_controles} |\n`;
      md += `| **Fórmula** | ${curVinculo.formula_calculo} |\n`;
      md += `| **Quantidade de Kits** | **${curVinculo.quantidade_kits}** |\n`;
      md += `\n---\n\n`;
    }

    // Insights IA
    if (insights && (insights as Record<string, unknown>).tem_dados) {
      md += `## 3. Análise de Mercado (IA)\n\n`;
      md += `| Indicador | Valor |\n|---|---|\n`;
      md += `| **Registros encontrados** | ${insights.historico.qtd_registros} |\n`;
      md += `| **Preço mínimo** | ${insights.historico.preco_min != null ? fmt(insights.historico.preco_min) : "—"} |\n`;
      md += `| **Preço médio** | ${insights.historico.preco_medio != null ? fmt(insights.historico.preco_medio) : "—"} |\n`;
      md += `| **Preço máximo** | ${insights.historico.preco_max != null ? fmt(insights.historico.preco_max) : "—"} |\n`;
      md += `| **Fonte** | ${insights.recomendacao.fonte || "—"} |\n`;
      if (insights.referencia_edital != null) md += `| **Referência do Edital** | ${fmt(insights.referencia_edital)} |\n`;
      md += `\n`;

      const variacaoAlta = insights.historico.preco_max && insights.historico.preco_min && Number(insights.historico.preco_max) / Number(insights.historico.preco_min) > 5;

      md += `### Sugestões de Preço\n\n`;
      md += `| Camada | Valor Sugerido | Critério |\n|---|---|---|\n`;
      md += `| **(A) Custo** | ${insights.recomendacao.custo_sugerido ? fmt(insights.recomendacao.custo_sugerido) : "—"} | 85% da referência histórica |\n`;
      md += `| **(B) Preço Base** | ${insights.recomendacao.preco_base_sugerido ? fmt(insights.recomendacao.preco_base_sugerido) : "—"} | 97% da média (preço competitivo) |\n`;
      md += `| **(C) Referência** | ${insights.recomendacao.referencia_sugerida ? fmt(insights.recomendacao.referencia_sugerida) : "—"} | Target estratégico |\n`;
      md += `| **(D) Lance Inicial** | ${(insights.recomendacao as Record<string, unknown>).lance_inicial_sugerido ? fmt((insights.recomendacao as Record<string, unknown>).lance_inicial_sugerido as number) : "—"} | = Preço Base |\n`;
      md += `| **(E) Lance Mínimo** | ${(insights.recomendacao as Record<string, unknown>).lance_minimo_sugerido ? fmt((insights.recomendacao as Record<string, unknown>).lance_minimo_sugerido as number) : "—"} | Custo + 10% margem |\n`;
      md += `\n`;

      md += `### Como a IA calculou cada valor\n\n`;
      if (insights.recomendacao.custo_sugerido) {
        md += `**(A) Base de Custos — ${fmt(insights.recomendacao.custo_sugerido)}**\n`;
        md += `> Calculado como 85% da referência histórica. Preço mínimo dos vencedores: ${fmt(insights.historico.preco_min)}, média: ${fmt(insights.historico.preco_medio)}.`;
        md += variacaoAlta ? ` Alta variação detectada (${fmt(insights.historico.preco_min)} a ${fmt(insights.historico.preco_max)}) — usado percentil entre mínimo e média como base, em vez do mínimo puro.\n\n` : `\n\n`;
      }
      if (insights.recomendacao.preco_base_sugerido) {
        md += `**(B) Preço Base — ${fmt(insights.recomendacao.preco_base_sugerido)}**\n`;
        md += `> 97% da média dos vencedores (${fmt(insights.historico.preco_medio)}). Faixa competitiva: ${fmt(insights.recomendacao.faixa.agressivo)} (agressivo) a ${fmt(insights.recomendacao.faixa.conservador)} (conservador).`;
        md += insights.recomendacao.markup_sugerido ? ` Markup implícito sobre o custo: ${insights.recomendacao.markup_sugerido}%.\n\n` : `\n\n`;
      }
      if (insights.referencia_edital || insights.recomendacao.referencia_sugerida) {
        const refVal = insights.referencia_edital || insights.recomendacao.referencia_sugerida;
        md += `**(C) Valor de Referência — ${fmt(refVal as number)}**\n`;
        md += insights.referencia_edital
          ? `> Valor importado diretamente do edital. Este é o teto estimado pelo órgão licitante.\n\n`
          : `> 99% da média histórica (preço conservador). Serve como target estratégico — o valor máximo que se pretende atingir na disputa.\n\n`;
      }
      if ((insights.recomendacao as Record<string, unknown>).lance_inicial_sugerido) {
        md += `**(D) Lance Inicial — ${fmt((insights.recomendacao as Record<string, unknown>).lance_inicial_sugerido as number)}**\n`;
        md += `> Igual ao preço base sugerido. É o valor de entrada no leilão/pregão.\n\n`;
      }
      if ((insights.recomendacao as Record<string, unknown>).lance_minimo_sugerido) {
        md += `**(E) Lance Mínimo — ${fmt((insights.recomendacao as Record<string, unknown>).lance_minimo_sugerido as number)}**\n`;
        md += `> Custo sugerido (${fmt(insights.recomendacao.custo_sugerido)}) + 10% de margem mínima. Abaixo deste valor, a operação gera prejuízo.\n\n`;
      }

      // Concorrentes
      if (insights.concorrentes.length > 0) {
        md += `### Concorrentes\n\n`;
        md += `| Empresa | Vitórias | Taxa | Preço Médio |\n|---|---|---|---|\n`;
        for (const c of insights.concorrentes) {
          md += `| ${c.nome} | ${c.editais_ganhos} | ${c.taxa_vitoria.toFixed(1)}% | ${fmt(c.preco_medio)} |\n`;
        }
        md += `\n`;
      }

      // Vencedores detalhados
      const vencDet = (insights as Record<string, unknown>).vencedores_detalhes as Array<Record<string, unknown>> | undefined;
      if (vencDet && vencDet.length > 0) {
        md += `### Preços Detalhados dos Vencedores\n\n`;
        for (const res of vencDet) {
          md += `**${res.ata_titulo} — ${res.orgao}**\n\n`;
          md += `| Item | Descrição | Vencedor | Estimado | Homologado |\n|---|---|---|---|---|\n`;
          for (const vv of ((res.vencedores || []) as Array<Record<string, unknown>>)) {
            md += `| ${vv.item} | ${String(vv.descricao || "").slice(0, 40)} | ${String(vv.vencedor || "").slice(0, 25)} | ${vv.valor_estimado ? fmt(Number(vv.valor_estimado)) : "—"} | ${vv.valor_homologado ? fmt(Number(vv.valor_homologado)) : "—"} |\n`;
          }
          md += `\n`;
        }
      }

      // Justificativa IA
      if (insights.recomendacao.justificativa) {
        md += `### Justificativa IA\n\n`;
        md += `${insights.recomendacao.justificativa}\n\n`;
      }
      md += `---\n\n`;
    }

    // Valores definidos (salvos) — só mostrar se tem algum valor preenchido
    const temValoresDefinidos = camada && (camada.custo_unitario || camada.preco_base || camada.lance_inicial);
    if (temValoresDefinidos) {
      md += `## 4. Valores Definidos pelo Usuário\n\n`;
      md += `| Campo | Valor |\n|---|---|\n`;
      if (camada.custo_unitario) md += `| **Custo Unitário** | ${fmt(Number(camada.custo_unitario))} |\n`;
      if (camada.ncm) md += `| **NCM** | ${camada.ncm} |\n`;
      if (camada.icms != null) md += `| **ICMS** | ${camada.icms}%${camada.isencao_icms ? " (ISENTO)" : ""} |\n`;
      if (camada.ipi != null) md += `| **IPI** | ${camada.ipi}% |\n`;
      if (camada.pis_cofins != null) md += `| **PIS+COFINS** | ${camada.pis_cofins}% |\n`;
      if (camada.custo_base_final) md += `| **Custo Base Final** | ${fmt(Number(camada.custo_base_final))} |\n`;
      if (camada.modo_preco_base) md += `| **Modo Preço Base** | ${camada.modo_preco_base} |\n`;
      if (camada.markup_percentual) md += `| **Markup** | ${camada.markup_percentual}% |\n`;
      if (camada.preco_base) md += `| **Preço Base** | ${fmt(Number(camada.preco_base))} |\n`;
      if (camada.valor_referencia_edital) md += `| **Valor Referência** | ${fmt(Number(camada.valor_referencia_edital))} |\n`;
      if (camada.target_referencia) md += `| **Target** | ${fmt(Number(camada.target_referencia))} |\n`;
      if (camada.margem_sobre_custo != null) md += `| **Margem sobre Custo** | ${camada.margem_sobre_custo}% |\n`;
      if (camada.lance_inicial) md += `| **Lance Inicial** | ${fmt(Number(camada.lance_inicial))} |\n`;
      if (camada.lance_minimo) md += `| **Lance Mínimo** | ${fmt(Number(camada.lance_minimo))} |\n`;
      if (camada.margem_minima != null) md += `| **Margem Mínima** | ${camada.margem_minima}% |\n`;
    }

    // Abrir em nova aba com toolbar MD/PDF (mesmo padrão da Captação)
    const tableRegex = /(\|.+\|\n)+/g;
    let html = md.replace(tableRegex, (tableBlock) => {
      const rows = tableBlock.trim().split('\n').filter(r => r.trim());
      if (rows.length < 2) return tableBlock;
      let t = '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;border-color:#334155;margin:8px 0;width:100%;font-size:13px;">\n';
      rows.forEach((row, ri) => {
        if (ri === 1 && row.match(/^\|[\s-|]+\|$/)) return;
        const cells = row.split('|').filter((_, ci, arr) => ci > 0 && ci < arr.length - 1).map(c => c.trim());
        const tag = ri === 0 ? 'th' : 'td';
        const bg = ri === 0 ? ' style="background:#1e293b;color:#94a3b8;text-align:left;"' : '';
        t += '<tr>' + cells.map(c => `<${tag}${bg}>${c}</${tag}>`).join('') + '</tr>\n';
      });
      t += '</table>\n';
      return t;
    });
    html = html
      .replace(/^#### (.+)$/gm, '<h4 style="color:#60a5fa;margin:16px 0 8px;">$1</h4>')
      .replace(/^### (.+)$/gm, '<h3 style="color:#818cf8;margin:24px 0 12px;padding-bottom:6px;border-bottom:1px solid #334155;">$1</h3>')
      .replace(/^## (.+)$/gm, '<h2 style="color:#a78bfa;margin:32px 0 16px;">$1</h2>')
      .replace(/^# (.+)$/gm, '<h1 style="color:#e2e8f0;margin:0 0 24px;">$1</h1>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" style="color:#60a5fa;">$1</a>')
      .replace(/^> (.+)$/gm, '<blockquote style="border-left:3px solid #475569;padding:4px 12px;margin:4px 0;color:#94a3b8;">$1</blockquote>')
      .replace(/^- (.+)$/gm, '<div style="padding:2px 0 2px 16px;">• $1</div>')
      .replace(/^---$/gm, '<hr style="border:none;border-top:1px solid #334155;margin:24px 0;"/>')
      .replace(/  \n/g, '<br/>');

    const fullHtml = `<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Relatório Custos e Preços — ${dataHora}</title>
<style>body{background:#0f172a;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,monospace;max-width:1100px;margin:0 auto;padding:64px 24px 32px;line-height:1.6}table{font-size:13px}th{font-weight:600}td,th{padding:6px 10px;border:1px solid #334155}tr:nth-child(even){background:#1e293b}h1{color:#e2e8f0;font-size:24px}h2{color:#a78bfa;font-size:20px}h3{color:#818cf8;font-size:16px;border-bottom:1px solid #334155;padding-bottom:6px}strong{color:#f1f5f9}@media print{@page{margin:10mm}body{background:white;color:#1e293b;padding-top:0;max-width:none}h1,h2,h3,h4,strong{color:#1e293b}td,th{border-color:#cbd5e1}tr:nth-child(even){background:#f1f5f9}.toolbar-relatorio{display:none!important}}.toolbar-relatorio{position:fixed;top:0;left:0;right:0;z-index:1000;background:#1e293b;border-bottom:2px solid #334155;padding:10px 24px;display:flex;gap:12px;align-items:center}.toolbar-relatorio button{padding:8px 18px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600}.btn-md{background:#3b82f6;color:white}.btn-pdf{background:#8b5cf6;color:white}.toolbar-relatorio span{color:#94a3b8;font-size:13px;margin-left:auto}</style></head><body>
<div class="toolbar-relatorio"><button class="btn-md" onclick="baixarMD()">📥 Baixar MD</button><button class="btn-pdf" onclick="window.print()">📄 Baixar PDF</button><span>Relatório gerado em ${dataHora}</span></div>
${html}
<script>var mdContent=${JSON.stringify(md)};function baixarMD(){var b=new Blob(['\\uFEFF'+mdContent],{type:'text/markdown;charset=utf-8;'});var u=URL.createObjectURL(b);var a=document.createElement('a');a.href=u;a.download='relatorio_custos_precos_${now.toISOString().slice(0, 10)}.md';a.click();URL.revokeObjectURL(u)}</script></body></html>`;

    const blob = new Blob([fullHtml], { type: 'text/html;charset=utf-8' });
    window.open(URL.createObjectURL(blob), '_blank');
  };

  // ── Vinculo selector for Custos e Preços/Lances tabs ──
  const vinculoOptions = [
    { value: "", label: "Selecione item-produto..." },
    ...vinculos.map(v => {
      const item = itensEdital.find(i => i.id === v.edital_item_id);
      const prod = produtos.find(p => p.id === v.produto_id);
      // Descobrir lote do item
      const loteEntry = Object.entries(loteItensMap).find(([, ids]) => ids.includes(v.edital_item_id));
      const lote = loteEntry ? lotes.find(l => l.id === loteEntry[0]) : null;
      // Nome curto do item (extrair de parênteses ou tipo de análise)
      const desc = item?.descricao || "";
      const parenMatch = desc.match(/\(([^)]{2,30})\)/);
      const tipoMatch = desc.match(/tipo de an[aá]lise:\s*([^,]{3,40})/i);
      const shortName = parenMatch ? parenMatch[1] : tipoMatch ? tipoMatch[1].trim() : desc.slice(0, 30);
      const loteLabel = lote ? `Lote ${lote.numero_lote} (${lote.nome})` : "";
      return {
        value: v.id,
        label: `${loteLabel} → ${shortName} / ${prod?.nome?.slice(0, 30) ?? "Produto"} ${v.confirmado ? "✓" : ""}`,
      };
    }),
  ];

  const curVinculo = vinculos.find(v => v.id === vinculoId);

  // Detectar se existe produto compatível no portfolio para um item
  const _norm = (s: string) => s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  const _stopWords = new Set(["para","tipo","conjunto","completo","caracteristicas","adicionais","equipamento","apresentacao","metodo","teste","reagente","diagnostico","clinico","marca","dispositivos"]);
  const temProdutoCompativelNoPortfolio = useCallback((descricao: string): boolean => {
    if (!descricao || produtos.length === 0) return false;
    // Extrair nome curto: conteúdo entre parênteses (ex: "TP", "TTPA") ou tipo de análise
    const parenMatch = descricao.match(/\(([^)]{2,30})\)/);
    const tipoMatch = descricao.match(/tipo de an[aá]lise:\s*([^,]{3,60})/i);
    const keyPhrase = parenMatch ? parenMatch[1] : tipoMatch ? tipoMatch[1] : "";
    if (!keyPhrase) return false; // sem nome curto identificável = não dá pra comparar
    const keyNorm = _norm(keyPhrase);
    const keyWords = keyNorm.split(/\s+/).filter(w => w.length > 2 && !_stopWords.has(w));
    if (keyWords.length === 0) return false;

    return produtos.some(p => {
      const nomeLower = _norm(p.nome || "");
      // Match: pelo menos 1 palavra-chave do nome curto aparece no nome do produto
      return keyWords.some(kw => nomeLower.includes(kw));
    });
  }, [produtos]);

  // ── Column defs ──
  const historicoColumns: Column<HistoricoPreco>[] = [
    { key: "produto", header: "Produto", sortable: true },
    { key: "preco", header: "Preço", render: (h) => fmt(h.preco), sortable: true },
    { key: "data", header: "Data", sortable: true },
    { key: "edital", header: "Edital" },
    {
      key: "resultado", header: "Resultado",
      render: (h) => (
        <span className={`status-badge ${h.resultado === "ganho" ? "status-badge-success" : "status-badge-error"}`}>
          {h.resultado === "ganho" ? "Ganho" : "Perdido"}
        </span>
      ),
    },
  ];

  // ── Handlers: Buscar na Web / ANVISA (modal → IA) ──
  const handleBuscaWebConfirm = async () => {
    if (!buscaNomeProduto) return;
    const msg = buscaFabricante
      ? `Busque o manual do produto ${buscaNomeProduto} do fabricante ${buscaFabricante} na web e cadastre`
      : `Busque o manual do produto ${buscaNomeProduto} na web e cadastre`;
    setShowBuscaWebModal(false);
    setIaProcessing("Buscando produto na web...");
    setIaResponse(null);
    try {
      const session = await createSession("precif-busca-web");
      const sid = String(session.session_id || session.id);
      const resp = await sendMessage(sid, msg);
      setIaResponse(resp.response || "Busca web concluída.");
      setBuscaNomeProduto("");
      setBuscaFabricante("");
      if (editalId) loadLotes(editalId);
    } catch (err) {
      console.error("[BuscaWeb] Erro:", err);
      setIaResponse(`Erro: ${err instanceof Error ? err.message : "Falha na busca web"}`);
    } finally {
      setIaProcessing(null);
    }
  };

  const handleAnvisaConfirm = async () => {
    let msg = "";
    if (anvisaRegistro) msg = `Busque o registro ANVISA numero ${anvisaRegistro}`;
    else if (anvisaNomeProduto) msg = `Busque registros ANVISA para o produto ${anvisaNomeProduto}`;
    else return;
    setShowAnvisaModal(false);
    setIaProcessing("Buscando registros ANVISA...");
    setIaResponse(null);
    try {
      const session = await createSession("precif-anvisa");
      const sid = String(session.session_id || session.id);
      const resp = await sendMessage(sid, msg);
      setIaResponse(resp.response || "Busca ANVISA concluída.");
      setAnvisaRegistro("");
      setAnvisaNomeProduto("");
      if (editalId) loadLotes(editalId);
    } catch (err) {
      console.error("[ANVISA] Erro:", err);
      setIaResponse(`Erro: ${err instanceof Error ? err.message : "Falha na busca ANVISA"}`);
    } finally {
      setIaProcessing(null);
    }
  };

  // ── Tabs ──
  const tabs = [
    { id: "lotes", label: `Lotes ${lotes.length > 0 ? (lotes.some(l => l.status === "configurado") ? "✅" : "⚠️") : "❌"}`, icon: <Layers size={16} /> },
    { id: "camadas", label: `Custos e Preços ${Object.values(todasCamadas).some(c => c.preco_base) ? "✅" : Object.values(todasCamadas).some(c => c.custo_unitario) ? "⚠️" : vinculos.length > 0 ? "⚠️" : "❌"}`, icon: <DollarSign size={16} /> },
    { id: "lances", label: `Lances ${Object.values(todasCamadas).some(c => c.lance_inicial) ? "✅" : "❌"}`, icon: <Target size={16} /> },
    { id: "estrategia", label: "Estratégia", icon: <BarChart3 size={16} /> },
    { id: "historico", label: "Histórico", icon: <History size={16} /> },
  ];

  // ─── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-left">
          <DollarSign size={24} />
          <div>
            <h1>Precificação</h1>
            <p>Custos, preços, lances e estratégia competitiva</p>
          </div>
        </div>
      </div>

      {/* Edital selector — global */}
      <div className="page-content">
        <Card title="Edital" icon={<Search size={18} />}>
          <div className="form-grid form-grid-2">
            <FormField label="Selecione o edital">
              <SelectInput value={editalId} onChange={setEditalId} options={editalOptions} />
            </FormField>
            <div className="form-field-actions" style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
              <ActionButton
                icon={<Layers size={16} />}
                label="Criar Lotes"
                variant="primary"
                onClick={handleCriarLotes}
                loading={loading}
                disabled={itensEdital.length === 0}
              />
            </div>
          </div>
        </Card>

        {editalId && (
          <TabPanel tabs={tabs} defaultTab="lotes">
            {(activeTab) => (
              <>
                {/* ═══════════════════ TAB: LOTES (UC-P01) ═══════════════════ */}
                {activeTab === "lotes" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    <Card title={`Lotes (${lotes.length})`} icon={<Layers size={18} />}>
                      {lotes.length === 0 ? (
                        <p style={{ color: "var(--text-secondary)", padding: "16px 0" }}>
                          {itensEdital.length === 0
                            ? "Este edital não possui itens. Importe os itens na fase de captação/validação antes de precificar."
                            : `${itensEdital.length} item(ns) encontrado(s). Clique em "Criar Lotes" para agrupá-los.`}
                        </p>
                      ) : (
                        <div>
                          {lotes.map((lote) => (
                            <div key={lote.id} className="card" style={{ marginBottom: 8, padding: 12 }}>
                              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer" }}
                                onClick={() => {
                                  const novoId = loteExpandido === lote.id ? null : lote.id;
                                  setLoteExpandido(novoId);
                                  if (novoId) {
                                    setLoteEspecialidade(lote.especialidade || "");
                                    setLoteVolume(String(lote.volume_exigido || ""));
                                    setLoteTipoAmostra(String(lote.tipo_amostra || ""));
                                    setLoteEquipamento(String(lote.equipamento_exigido || ""));
                                    setLoteObservacoes(String(lote.observacoes_tecnicas || ""));
                                  }
                                }}>
                                <div>
                                  <strong>Lote {lote.numero_lote}</strong> — {lote.nome || "Sem nome"}
                                  <span className={`status-badge status-badge-${lote.status === "configurado" ? "success" : "warning"}`} style={{ marginLeft: 8 }}>
                                    {lote.status}
                                  </span>
                                </div>
                                <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                                  <span>{fmt(lote.valor_estimado)}</span>
                                  {loteExpandido === lote.id ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                                </div>
                              </div>
                              {loteExpandido === lote.id && (
                                <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
                                  <div className="form-grid form-grid-3">
                                    <FormField label="Especialidade">
                                      <TextInput value={loteEspecialidade || lote.especialidade || ""} onChange={setLoteEspecialidade} placeholder="Ex: Hematologia, Microscopia" />
                                    </FormField>
                                    <FormField label="Volume Exigido (testes/unidades)">
                                      <TextInput value={loteVolume || String(lote.volume_exigido || "")} onChange={setLoteVolume} placeholder="Ex: 50000" />
                                    </FormField>
                                    <FormField label="Tipo de Amostra">
                                      <TextInput value={loteTipoAmostra || String(lote.tipo_amostra || "")} onChange={setLoteTipoAmostra} placeholder="Ex: Sangue total, Soro, Urina" />
                                    </FormField>
                                  </div>
                                  <div className="form-grid form-grid-2" style={{ marginTop: 8 }}>
                                    <FormField label="Equipamento Exigido">
                                      <TextInput value={loteEquipamento || String(lote.equipamento_exigido || "")} onChange={setLoteEquipamento} placeholder="Ex: Analisador bioquímico, Microscópio" />
                                    </FormField>
                                    <FormField label="Descrição / Observações Técnicas">
                                      <TextInput value={loteObservacoes || String(lote.observacoes_tecnicas || "")} onChange={setLoteObservacoes} placeholder="Observações sobre o lote" />
                                    </FormField>
                                  </div>
                                  <div style={{ marginTop: 8 }}>
                                    <ActionButton icon={<Check size={16} />} label="Atualizar Lote" variant="primary" onClick={() => handleSalvarLote(lote.id)} />
                                  </div>

                                  {/* Itens deste lote */}
                                  <h4 style={{ margin: "12px 0 8px" }}>Itens do Edital</h4>
                                  <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
                                    <thead>
                                      <tr style={{ borderBottom: "1px solid var(--border)" }}>
                                        <th style={{ textAlign: "left", padding: 4 }}>#</th>
                                        <th style={{ textAlign: "left", padding: 4 }}>Descrição</th>
                                        <th style={{ textAlign: "right", padding: 4 }}>Qtd</th>
                                        <th style={{ textAlign: "right", padding: 4 }}>Valor Unit.</th>
                                        <th style={{ textAlign: "left", padding: 4 }}>Produto Vinculado</th>
                                        <th style={{ padding: 4 }}></th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {(() => {
                                        // Filtrar itens que pertencem a este lote
                                        const itensDoLote = loteItensMap[lote.id]
                                          ? itensEdital.filter(it => loteItensMap[lote.id].includes(it.id))
                                          : itensEdital; // fallback: todos (lote sem mapeamento)
                                        return itensDoLote;
                                      })().slice(0, 20).map((it) => {
                                        const vinculo = vinculos.find(v => v.edital_item_id === it.id);
                                        const prodVinculado = vinculo ? produtos.find(p => p.id === vinculo.produto_id) : null;
                                        return (
                                        <tr key={it.id} style={{ borderBottom: "1px solid var(--border-light, #eee)" }}>
                                          <td style={{ padding: 4 }}>{it.numero_item}</td>
                                          <td style={{ padding: 4, maxWidth: 350 }}>
                                            {(() => {
                                              const desc = it.descricao || "";
                                              // Extrair nome curto: conteúdo entre parênteses ou "tipo de análise: ..."
                                              const parenMatch = desc.match(/\(([^)]{2,30})\)/);
                                              const tipoMatch = desc.match(/tipo de an[aá]lise:\s*([^,]{3,60})/i);
                                              const shortName = parenMatch ? parenMatch[1] : tipoMatch ? tipoMatch[1].trim() : null;
                                              return (
                                                <div>
                                                  {shortName && (
                                                    <strong style={{ display: "block", fontSize: 13, marginBottom: 2, color: "var(--text-primary)" }}>
                                                      {shortName}
                                                    </strong>
                                                  )}
                                                  <span style={{ fontSize: 11, color: "var(--text-secondary)", display: "block", maxWidth: 320, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                                    {desc}
                                                  </span>
                                                </div>
                                              );
                                            })()}
                                          </td>
                                          <td style={{ textAlign: "right", padding: 4 }}>{it.quantidade}</td>
                                          <td style={{ textAlign: "right", padding: 4 }}>{fmt(it.valor_unitario_estimado)}</td>
                                          <td style={{ padding: 4 }}>
                                            {prodVinculado ? (
                                              <span style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 8, fontSize: 12, fontWeight: 600, backgroundColor: "#22c55e20", color: "#22c55e", border: "1px solid #22c55e40" }}>
                                                ✅ {prodVinculado.nome?.slice(0, 30)}
                                              </span>
                                            ) : it._ignorado || it.tipo_beneficio === "ignorado" ? (
                                              <span style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 8, fontSize: 12, fontWeight: 600, backgroundColor: "#64748b20", color: "#94a3b8", border: "1px solid #64748b40" }}>
                                                ⏭️ Ignorado
                                              </span>
                                            ) : temProdutoCompativelNoPortfolio(it.descricao) ? (
                                              <span style={{ fontSize: 12, color: "#f59e0b" }}>⚠️ Não vinculado — existe produto compatível</span>
                                            ) : (
                                              <span style={{ fontSize: 12, color: "#ef4444" }}>❌ Sem produto no portfolio</span>
                                            )}
                                          </td>
                                          <td style={{ padding: 4, textAlign: "center" }}>
                                            <div style={{ display: "flex", gap: 4, justifyContent: "center", flexWrap: "wrap" }}>
                                              <ActionButton
                                                icon={<Target size={14} />}
                                                label={prodVinculado ? "Trocar" : "Vincular"}
                                                variant={prodVinculado ? "neutral" : "primary"}
                                                onClick={() => handleSelecaoPortfolio(it.id)}
                                              />
                                              <ActionButton
                                                icon={<Lightbulb size={14} />}
                                                label="IA"
                                                variant="neutral"
                                                loading={loading}
                                                onClick={async () => {
                                                  setLoading(true);
                                                  try {
                                                    const token = localStorage.getItem("editais_ia_access_token");
                                                    const res = await fetch(`/api/precificacao/vincular-ia/${it.id}`, {
                                                      method: "POST",
                                                      headers: { Authorization: token ? `Bearer ${token}` : "" },
                                                    });
                                                    const data = await res.json();
                                                    if (data.success && data.auto_vinculado) {
                                                      loadLotes(editalId);
                                                      alert(`IA vinculou: ${data.produto_nome || "Produto"} (match: ${data.match_score || 0}%)\n${data.justificativa || ""}`);
                                                    } else if (data.success && !data.auto_vinculado) {
                                                      // IA não encontrou match suficiente
                                                      const cadastrar = window.confirm(
                                                        "Nenhum produto compatível encontrado no portfolio.\n\n" +
                                                        "Deseja cadastrar um novo produto?\n" +
                                                        "(Clique OK para ir ao Portfolio, Cancelar para pular este item)"
                                                      );
                                                      if (cadastrar) {
                                                        window.dispatchEvent(new CustomEvent("navigate-to", { detail: { page: "portfolio" } }));
                                                      }
                                                    } else {
                                                      const cadastrar = window.confirm(
                                                        `${data.error || "Nenhum produto compatível"}\n\nDeseja cadastrar um novo produto no Portfolio?`
                                                      );
                                                      if (cadastrar) {
                                                        window.dispatchEvent(new CustomEvent("navigate-to", { detail: { page: "portfolio" } }));
                                                      }
                                                    }
                                                  } catch { alert("Erro ao vincular com IA"); }
                                                  finally { setLoading(false); }
                                                }}
                                              />
                                              {prodVinculado ? (
                                                <ActionButton
                                                  icon={<X size={14} />}
                                                  label="Desvincular"
                                                  variant="neutral"
                                                  onClick={async () => {
                                                    if (!window.confirm(`Desvincular "${prodVinculado.nome?.slice(0, 30)}" deste item?`)) return;
                                                    try {
                                                      const { crudDelete } = await import("../api/crud");
                                                      await crudDelete("edital-item-produto", vinculo!.id);
                                                      loadLotes(editalId);
                                                    } catch { alert("Erro ao desvincular."); }
                                                  }}
                                                />
                                              ) : it._ignorado ? (
                                                <ActionButton
                                                  icon={<Check size={14} />}
                                                  label="Reativar"
                                                  variant="neutral"
                                                  onClick={async () => {
                                                    try {
                                                      await crudUpdate("editais-itens", it.id, { tipo_beneficio: null });
                                                      setItensEdital(prev => prev.map(item =>
                                                        item.id === it.id ? { ...item, _ignorado: false } as EditalItem : item
                                                      ));
                                                    } catch { alert("Erro ao reativar item."); }
                                                  }}
                                                />
                                              ) : (
                                                <>
                                                  <ActionButton
                                                    icon={<Globe size={14} />}
                                                    label="Buscar na Web"
                                                    variant="neutral"
                                                    onClick={() => {
                                                      setBuscaNomeProduto((it.descricao || "").slice(0, 120));
                                                      setBuscaFabricante("");
                                                      setShowBuscaWebModal(true);
                                                    }}
                                                  />
                                                  <ActionButton
                                                    icon={<Shield size={14} />}
                                                    label="ANVISA"
                                                    variant="neutral"
                                                    onClick={() => {
                                                      setAnvisaNomeProduto((it.descricao || "").slice(0, 120));
                                                      setAnvisaRegistro("");
                                                      setShowAnvisaModal(true);
                                                    }}
                                                  />
                                                  <ActionButton
                                                    icon={<X size={14} />}
                                                    label="Ignorar"
                                                    variant="neutral"
                                                    onClick={async () => {
                                                      try {
                                                        await crudUpdate("editais-itens", it.id, { tipo_beneficio: "ignorado" });
                                                        setItensEdital(prev => prev.map(item =>
                                                          item.id === it.id ? { ...item, _ignorado: true } as EditalItem : item
                                                        ));
                                                      } catch { alert("Erro ao ignorar item."); }
                                                    }}
                                                  />
                                                </>
                                              )}
                                            </div>
                                          </td>
                                        </tr>
                                        );
                                      })}
                                    </tbody>
                                  </table>
                                  {itensEdital.length > 20 && <p style={{ fontSize: 12, color: "var(--text-secondary)" }}>... e mais {itensEdital.length - 20} itens</p>}
                                  {/* Resposta da IA (busca web / ANVISA) */}
                                  {iaProcessing && (
                                    <div style={{ marginTop: 8, padding: "8px 12px", borderRadius: 6, backgroundColor: "#1e293b", fontSize: 12, color: "#60a5fa", display: "flex", alignItems: "center", gap: 8 }}>
                                      <Loader2 size={14} className="spin" /> {iaProcessing}
                                    </div>
                                  )}
                                  {iaResponse && !iaProcessing && (
                                    <Card>
                                      <div style={{ position: "relative" }}>
                                        <button
                                          onClick={() => setIaResponse(null)}
                                          style={{ position: "absolute", top: 0, right: 0, background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)", fontSize: 18 }}
                                        >&times;</button>
                                        <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
                                          <Sparkles size={18} style={{ color: "var(--accent-primary)", flexShrink: 0, marginTop: 2 }} />
                                          <div className="markdown-response" style={{ fontSize: 12, maxHeight: 300, overflowY: "auto" }}>
                                            <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({href, children}) => <a href={href as string} target="_blank" rel="noopener noreferrer">{children}</a> }}>{iaResponse}</ReactMarkdown>
                                          </div>
                                        </div>
                                      </div>
                                    </Card>
                                  )}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </Card>
                  </div>
                )}

                {/* ═══════════════════ TAB: CUSTOS E PREÇOS (UC-P02 a UC-P06) ═══════════════════ */}
                {activeTab === "camadas" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    {/* Visão consolidada por lote */}
                    {vinculos.length > 0 && (
                      <Card title="Resumo de Precificação" icon={<BarChart3 size={18} />}>
                        <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
                          <thead>
                            <tr style={{ borderBottom: "2px solid var(--border)" }}>
                              <th style={{ textAlign: "left", padding: 6 }}>Item</th>
                              <th style={{ textAlign: "left", padding: 6 }}>Produto</th>
                              <th style={{ textAlign: "right", padding: 6 }}>Qtd</th>
                              <th style={{ textAlign: "right", padding: 6 }}>Custo (A)</th>
                              <th style={{ textAlign: "right", padding: 6 }}>Base (B)</th>
                              <th style={{ textAlign: "right", padding: 6 }}>Ref (C)</th>
                              <th style={{ textAlign: "right", padding: 6 }}>Lance (D)</th>
                              <th style={{ textAlign: "right", padding: 6 }}>Mín (E)</th>
                              <th style={{ textAlign: "center", padding: 6 }}>Status</th>
                            </tr>
                          </thead>
                          <tbody>
                            {vinculos.map(v => {
                              const it = itensEdital.find(i => i.id === v.edital_item_id);
                              const prod = produtos.find(p => p.id === v.produto_id);
                              const pc = todasCamadas[v.id];
                              const desc = it?.descricao || "";
                              const parenM = desc.match(/\(([^)]{2,30})\)/);
                              const tipoM = desc.match(/tipo de an[aá]lise:\s*([^,]{3,40})/i);
                              const shortN = parenM ? parenM[1] : tipoM ? tipoM[1].trim() : desc.slice(0, 20);
                              const completo = pc?.custo_unitario && pc?.preco_base && pc?.lance_inicial;
                              const parcial = pc?.custo_unitario || pc?.preco_base;
                              return (
                                <tr key={v.id}
                                  style={{ borderBottom: "1px solid var(--border-light, #eee)", cursor: "pointer", backgroundColor: v.id === vinculoId ? "#3b82f615" : "transparent" }}
                                  onClick={() => setVinculoId(v.id)}
                                >
                                  <td style={{ padding: 6, fontWeight: 600 }}>{shortN}</td>
                                  <td style={{ padding: 6, fontSize: 11 }}>{prod?.nome?.slice(0, 25) || "—"}</td>
                                  <td style={{ textAlign: "right", padding: 6 }}>{it?.quantidade || "—"}</td>
                                  <td style={{ textAlign: "right", padding: 6 }}>{pc?.custo_unitario ? fmt(Number(pc.custo_unitario)) : "—"}</td>
                                  <td style={{ textAlign: "right", padding: 6 }}>{pc?.preco_base ? fmt(Number(pc.preco_base)) : "—"}</td>
                                  <td style={{ textAlign: "right", padding: 6 }}>{pc?.target_referencia ? fmt(Number(pc.target_referencia)) : "—"}</td>
                                  <td style={{ textAlign: "right", padding: 6 }}>{pc?.lance_inicial ? fmt(Number(pc.lance_inicial)) : "—"}</td>
                                  <td style={{ textAlign: "right", padding: 6 }}>{pc?.lance_minimo ? fmt(Number(pc.lance_minimo)) : "—"}</td>
                                  <td style={{ textAlign: "center", padding: 6 }}>
                                    {completo ? "✅" : parcial ? "⚠️" : "❌"}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                        <div style={{ marginTop: 8, fontSize: 12, color: "var(--text-secondary)", display: "flex", gap: 16 }}>
                          <span>Itens precificados: <strong>{vinculos.filter(v => todasCamadas[v.id]?.lance_inicial).length}/{vinculos.length}</strong></span>
                          {vinculos.some(v => todasCamadas[v.id]?.custo_unitario) && (
                            <span>Total Custo: <strong>{fmt(vinculos.reduce((s, v) => s + (Number(todasCamadas[v.id]?.custo_unitario || 0) * Number(itensEdital.find(i => i.id === v.edital_item_id)?.quantidade || 0)), 0))}</strong></span>
                          )}
                        </div>
                      </Card>
                    )}

                    {/* Item-Produto selector */}
                    <Card title="Selecionar Item-Produto" icon={<Package size={18} />}>
                      <FormField label="Vínculo Item ↔ Produto">
                        <SelectInput value={vinculoId} onChange={setVinculoId} options={vinculoOptions} />
                      </FormField>
                      {vinculoOptions.length <= 1 && (
                        <p style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 8 }}>
                          Nenhum vínculo item-produto encontrado. Vá à aba Lotes e clique no ícone <Target size={12} /> para vincular produtos.
                        </p>
                      )}
                      {vinculoId && (
                        <div style={{ marginTop: 8 }}>
                          <ActionButton icon={<FileText size={14} />} label="Relatório de Custos e Preços" variant="neutral" onClick={handleRelatorioCustoPreco} />
                        </div>
                      )}
                    </Card>

                    {vinculoId && (
                      <>
                        {/* Banner de detecção de volumetria */}
                        <Card title="Conversão de Quantidade" icon={<BarChart3 size={18} />}>
                          <div style={{ padding: 16, borderRadius: 8, border: "2px solid #3b82f6", backgroundColor: "#3b82f610", textAlign: "center" }}>
                            <p style={{ fontSize: 16, fontWeight: 700, marginBottom: 8, color: "var(--text-primary)" }}>
                              Este item requer conversão de quantidade?
                            </p>
                            <p style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 16 }}>
                              {precisaVolumetria
                                ? "Detectamos que este item é vendido em embalagem com rendimento fixo (ex: kit com X testes, caixa com X unidades). O cálculo converte a quantidade do edital em número de embalagens."
                                : "Detectamos que este item é de compra unitária. A quantidade do edital será usada diretamente."}
                            </p>
                            <div style={{ display: "flex", gap: 12, justifyContent: "center" }}>
                              <button
                                className="btn btn-primary"
                                style={{ fontSize: 14, padding: "8px 24px", opacity: precisaVolumetria ? 1 : 0.5 }}
                                onClick={() => setPrecisaVolumetria(true)}
                              >
                                Sim, converter quantidade
                              </button>
                              <button
                                className="btn btn-secondary"
                                style={{ fontSize: 14, padding: "8px 24px", opacity: !precisaVolumetria ? 1 : 0.5 }}
                                onClick={() => setPrecisaVolumetria(false)}
                              >
                                Não, usar quantidade do edital
                              </button>
                            </div>
                          </div>

                          {/* UC-P03: Campos de volumetria — só se confirmado */}
                          {precisaVolumetria && (
                            <>
                              <div className="form-grid form-grid-3" style={{ marginTop: 12 }}>
                                <FormField label="Quantidade do Edital">
                                  <TextInput value={volEdital} onChange={setVolEdital} placeholder="Qtd exigida no edital" />
                                </FormField>
                                <FormField label="Rendimento por Embalagem">
                                  <TextInput value={rendimento} onChange={setRendimento} placeholder="Unidades por embalagem/kit" />
                                </FormField>
                                <FormField label="Rep. Amostras">
                                  <TextInput value={repAmostras} onChange={setRepAmostras} placeholder="0" />
                                </FormField>
                                <FormField label="Rep. Calibradores">
                                  <TextInput value={repCalib} onChange={setRepCalib} placeholder="0" />
                                </FormField>
                                <FormField label="Rep. Controles">
                                  <TextInput value={repControles} onChange={setRepControles} placeholder="0" />
                                </FormField>
                                <div className="form-field-actions">
                                  <ActionButton icon={<BarChart3 size={16} />} label="Calcular e Salvar" variant="primary" onClick={handleCalcVolume} loading={loading} />
                                </div>
                              </div>
                              {curVinculo?.formula_calculo && (
                                <div style={{ marginTop: 12, padding: 12, background: "var(--bg-secondary, #f5f5f5)", borderRadius: 8, fontSize: 13 }}>
                                  <strong>Fórmula:</strong> {curVinculo.formula_calculo}<br />
                                  <strong>Kits necessários:</strong> {curVinculo.quantidade_kits}
                                </div>
                              )}
                            </>
                          )}

                          {/* Sem volumetria: mostra resumo direto */}
                          {precisaVolumetria === false && (
                            <div style={{ marginTop: 12, padding: 12, background: "var(--bg-secondary, #f5f5f5)", borderRadius: 8, fontSize: 13 }}>
                              {(() => {
                                const item = itensEdital.find(i => i.id === curVinculo?.edital_item_id);
                                const qtd = item?.quantidade || 0;
                                return (
                                  <>
                                    <strong>Quantidade do edital:</strong> {qtd} unidades — será usada diretamente como quantidade final.
                                  </>
                                );
                              })()}
                            </div>
                          )}
                        </Card>

                        {/* Card IA: Precificação Assistida */}
                        <Card title="Precificação Assistida por IA" icon={<Sparkles size={18} />}>
                          {insightsLoading && (
                            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "16px 0", color: "#60a5fa", fontSize: 13 }}>
                              <Loader2 size={16} className="spin" /> Buscando histórico de preços e atas no PNCP...
                            </div>
                          )}
                          {!insightsLoading && (!insights || !(insights as Record<string, unknown>).tem_dados) && (
                            <div style={{ padding: "12px", fontSize: 13, color: "var(--text-secondary)", borderRadius: 8, backgroundColor: "var(--bg-secondary, #f5f5f5)" }}>
                              <p style={{ marginBottom: 8 }}>Nenhum registro histórico ou ata encontrado para este produto.</p>
                              <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                                <ActionButton icon={<Search size={14} />} label="Regenerar Análise" variant="primary" loading={insightsLoading}
                                  onClick={() => {
                                    setInsights(null);
                                    setInsightsLoading(true);
                                    const token = localStorage.getItem("editais_ia_access_token");
                                    fetch(`/api/precificacao/${vinculoId}/insights`, { headers: { Authorization: token ? `Bearer ${token}` : "" } })
                                      .then(r => r.json()).then(data => { if (data.success) setInsights(data); })
                                      .catch(() => {}).finally(() => setInsightsLoading(false));
                                  }}
                                />
                              </div>
                              {insights && insights.termos_tentados && (
                                <p style={{ fontSize: 11, marginTop: 8, color: "#64748b" }}>
                                  Termos buscados: {insights.termos_tentados.join(" | ")}
                                  {insights.etapa && <span> | Etapa: {String(insights.etapa)}</span>}
                                </p>
                              )}
                            </div>
                          )}
                          {!insightsLoading && insights && insights.tem_dados && (
                            <>
                              {/* Banner resumo */}
                              <div style={{ display: "flex", gap: 16, padding: "8px 12px", borderRadius: 8, backgroundColor: "#3b82f610", border: "1px solid #3b82f630", fontSize: 13, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
                                <span><strong>{insights.historico.qtd_registros}</strong> registros</span>
                                {(insights as Record<string, unknown>).atas_encontradas ? <span><strong>{String((insights as Record<string, unknown>).atas_encontradas)}</strong> atas</span> : null}
                                {insights.historico.preco_min != null && (
                                  <>
                                    <span>Mín: <strong style={{ color: "#22c55e" }}>{fmt(insights.historico.preco_min)}</strong></span>
                                    <span>Média: <strong>{fmt(insights.historico.preco_medio)}</strong></span>
                                    <span>Máx: <strong style={{ color: "#ef4444" }}>{fmt(insights.historico.preco_max)}</strong></span>
                                  </>
                                )}
                                {insights.referencia_edital != null && (
                                  <span>Ref. Edital: <strong style={{ color: "#f59e0b" }}>{fmt(insights.referencia_edital)}</strong></span>
                                )}
                                {insights.recomendacao.fonte && (
                                  <span style={{ padding: "2px 8px", borderRadius: 4, fontSize: 11, backgroundColor: "#3b82f620", color: "#3b82f6" }}>
                                    {insights.recomendacao.fonte}
                                  </span>
                                )}
                                <ActionButton icon={<Search size={12} />} label="Regenerar" variant="neutral"
                                  onClick={() => {
                                    setInsights(null);
                                    setInsightsLoading(true);
                                    const token = localStorage.getItem("editais_ia_access_token");
                                    fetch(`/api/precificacao/${vinculoId}/insights`, { headers: { Authorization: token ? `Bearer ${token}` : "" } })
                                      .then(r => r.json()).then(data => { if (data.success) setInsights(data); })
                                      .catch(() => {}).finally(() => setInsightsLoading(false));
                                  }}
                                />
                              </div>

                              {/* 5 cards: sugestões A-E */}
                              <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8, marginBottom: 12 }}>
                                {[
                                  { label: "Custo (A)", valor: insights.recomendacao.custo_sugerido, desc: "85% da ref. histórica", action: () => setCustoUnit(String(insights.recomendacao.custo_sugerido)) },
                                  { label: "Preço Base (B)", valor: insights.recomendacao.preco_base_sugerido, desc: `Faixa: ${fmt(insights.recomendacao.faixa?.agressivo)}–${fmt(insights.recomendacao.faixa?.conservador)}`, action: () => { setModoPrecoBase("manual"); setPrecoBaseManual(String(insights.recomendacao.preco_base_sugerido)); } },
                                  { label: "Referência (C)", valor: insights.referencia_edital || insights.recomendacao.referencia_sugerida, desc: insights.referencia_edital ? "valor do edital" : "preço conservador", action: () => setValorRef(String(insights.referencia_edital || insights.recomendacao.referencia_sugerida)) },
                                  { label: "Lance Inicial (D)", valor: (insights.recomendacao as Record<string, unknown>).lance_inicial_sugerido as number | null, desc: "= preço base sugerido", action: () => setLanceInicial(String((insights.recomendacao as Record<string, unknown>).lance_inicial_sugerido)) },
                                  { label: "Lance Mínimo (E)", valor: (insights.recomendacao as Record<string, unknown>).lance_minimo_sugerido as number | null, desc: "custo + margem 10%", action: () => setLanceMinimo(String((insights.recomendacao as Record<string, unknown>).lance_minimo_sugerido)) },
                                ].map((s, i) => (
                                  <div key={i} style={{ padding: 10, borderRadius: 8, border: "1px solid var(--border)", textAlign: "center" }}>
                                    <p style={{ fontSize: 10, color: "var(--text-secondary)", marginBottom: 2, fontWeight: 600 }}>{s.label}</p>
                                    <p style={{ fontSize: 18, fontWeight: 700, color: "var(--text-primary)", marginBottom: 2 }}>
                                      {s.valor ? fmt(s.valor as number) : "—"}
                                    </p>
                                    <p style={{ fontSize: 9, color: "var(--text-secondary)", marginBottom: 6 }}>{s.desc}</p>
                                    {s.valor && (
                                      <button className="btn btn-secondary" style={{ fontSize: 10, padding: "2px 8px" }} onClick={s.action}>
                                        Usar →
                                      </button>
                                    )}
                                  </div>
                                ))}
                              </div>

                              {/* Concorrentes (colapsável) */}
                              {insights.concorrentes.length > 0 && (
                                <details style={{ fontSize: 12, marginBottom: 8 }}>
                                  <summary style={{ cursor: "pointer", color: "var(--text-secondary)", marginBottom: 6 }}>
                                    Concorrentes principais ({insights.concorrentes.length})
                                  </summary>
                                  <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
                                    <thead>
                                      <tr style={{ borderBottom: "1px solid var(--border)" }}>
                                        <th style={{ textAlign: "left", padding: 4 }}>Empresa</th>
                                        <th style={{ textAlign: "right", padding: 4 }}>Vitórias</th>
                                        <th style={{ textAlign: "right", padding: 4 }}>Taxa</th>
                                        <th style={{ textAlign: "right", padding: 4 }}>Preço Médio</th>
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {insights.concorrentes.map((c, i) => (
                                        <tr key={i} style={{ borderBottom: "1px solid var(--border-light, #eee)" }}>
                                          <td style={{ padding: 4 }}>{c.nome}</td>
                                          <td style={{ textAlign: "right", padding: 4 }}>{c.editais_ganhos}</td>
                                          <td style={{ textAlign: "right", padding: 4 }}>{c.taxa_vitoria.toFixed(1)}%</td>
                                          <td style={{ textAlign: "right", padding: 4 }}>{fmt(c.preco_medio)}</td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                </details>
                              )}

                              {/* Atas encontradas (expansível) */}
                              {(insights as Record<string, unknown>).atas_detalhes && ((insights as Record<string, unknown>).atas_detalhes as Array<Record<string, string>>).length > 0 && (
                                <details style={{ fontSize: 12, marginBottom: 8 }}>
                                  <summary style={{ cursor: "pointer", color: "var(--text-secondary)", marginBottom: 6 }}>
                                    Atas consultadas ({((insights as Record<string, unknown>).atas_detalhes as Array<Record<string, string>>).length})
                                  </summary>
                                  {((insights as Record<string, unknown>).atas_detalhes as Array<Record<string, string>>).map((ata, i) => (
                                    <div key={i} style={{ padding: "6px 8px", marginBottom: 4, borderRadius: 6, backgroundColor: "var(--bg-secondary, #f5f5f5)", fontSize: 12 }}>
                                      <strong>{ata.titulo}</strong> — {ata.orgao} ({ata.uf})
                                      {ata.url_pncp && (
                                        <a href={ata.url_pncp} target="_blank" rel="noopener noreferrer" style={{ marginLeft: 8, color: "#3b82f6", fontSize: 11 }}>Ver no PNCP ↗</a>
                                      )}
                                    </div>
                                  ))}
                                </details>
                              )}

                              {/* Preços detalhados dos vencedores (expansível) */}
                              {(insights as Record<string, unknown>).vencedores_detalhes && ((insights as Record<string, unknown>).vencedores_detalhes as Array<Record<string, unknown>>).length > 0 && (
                                <details style={{ fontSize: 12, marginBottom: 8 }}>
                                  <summary style={{ cursor: "pointer", color: "var(--text-secondary)", marginBottom: 6 }}>
                                    Preços detalhados dos vencedores
                                  </summary>
                                  {((insights as Record<string, unknown>).vencedores_detalhes as Array<Record<string, unknown>>).map((res, ri) => (
                                    <div key={ri} style={{ marginBottom: 8 }}>
                                      <p style={{ fontSize: 11, fontWeight: 600, marginBottom: 4, color: "var(--text-primary)" }}>
                                        {String(res.ata_titulo)} — {String(res.orgao)}
                                      </p>
                                      <table style={{ width: "100%", fontSize: 11, borderCollapse: "collapse" }}>
                                        <thead>
                                          <tr style={{ borderBottom: "1px solid var(--border)" }}>
                                            <th style={{ textAlign: "left", padding: 3 }}>Item</th>
                                            <th style={{ textAlign: "left", padding: 3 }}>Descrição</th>
                                            <th style={{ textAlign: "left", padding: 3 }}>Vencedor</th>
                                            <th style={{ textAlign: "right", padding: 3 }}>Estimado</th>
                                            <th style={{ textAlign: "right", padding: 3 }}>Homologado</th>
                                          </tr>
                                        </thead>
                                        <tbody>
                                          {((res.vencedores || []) as Array<Record<string, unknown>>).map((v, vi) => (
                                            <tr key={vi} style={{ borderBottom: "1px solid var(--border-light, #eee)" }}>
                                              <td style={{ padding: 3 }}>{String(v.item)}</td>
                                              <td style={{ padding: 3, maxWidth: 150, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{String(v.descricao || "")}</td>
                                              <td style={{ padding: 3 }}>{String(v.vencedor || "").slice(0, 25)}</td>
                                              <td style={{ textAlign: "right", padding: 3 }}>{v.valor_estimado ? fmt(Number(v.valor_estimado)) : "—"}</td>
                                              <td style={{ textAlign: "right", padding: 3, fontWeight: 600 }}>{v.valor_homologado ? fmt(Number(v.valor_homologado)) : "—"}</td>
                                            </tr>
                                          ))}
                                        </tbody>
                                      </table>
                                    </div>
                                  ))}
                                </details>
                              )}

                              {/* Justificativa IA detalhada */}
                              {insights.recomendacao.justificativa && (
                                <details open style={{ fontSize: 12, marginTop: 8 }}>
                                  <summary style={{ cursor: "pointer", color: "var(--text-secondary)", marginBottom: 6, fontWeight: 600 }}>
                                    <Sparkles size={12} style={{ display: "inline", marginRight: 4 }} /> Análise IA — Justificativa dos preços
                                  </summary>
                                  <div className="markdown-response" style={{ fontSize: 12, padding: "8px 12px", borderRadius: 8, backgroundColor: "var(--bg-secondary, #f5f5f5)", border: "1px solid var(--border)" }}>
                                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{insights.recomendacao.justificativa}</ReactMarkdown>
                                  </div>
                                </details>
                              )}
                            </>
                          )}
                        </Card>

                        {/* UC-P04: Base de Custos */}
                        <Card title="Base de Custos" icon={<DollarSign size={18} />}>
                          {/* Explicação IA */}
                          {insights && insights.tem_dados && insights.recomendacao.custo_sugerido && (
                            <div style={{ padding: "8px 12px", borderRadius: 6, backgroundColor: "#3b82f608", border: "1px solid #3b82f620", fontSize: 12, color: "var(--text-secondary)", marginBottom: 12 }}>
                              <Sparkles size={12} style={{ display: "inline", marginRight: 4, color: "#3b82f6" }} />
                              <strong>IA:</strong> Custo sugerido de <strong>{fmt(insights.recomendacao.custo_sugerido)}</strong> — calculado como 85% da referência histórica.
                              Preço mínimo dos vencedores: {fmt(insights.historico.preco_min)}, média: {fmt(insights.historico.preco_medio)}.
                              {insights.historico.preco_max && insights.historico.preco_min && Number(insights.historico.preco_max) / Number(insights.historico.preco_min) > 5
                                ? " Alta variação detectada — usado percentil entre mínimo e média como base."
                                : ""}
                            </div>
                          )}
                          <div className="form-grid form-grid-3">
                            <FormField label="Custo Unitário (R$)">
                              <TextInput value={custoUnit} onChange={setCustoUnit} placeholder="Custo de aquisição" />
                            </FormField>
                            <FormField label="NCM">
                              <TextInput value={camada?.ncm || ""} onChange={() => {}} placeholder="Automático do produto" />
                            </FormField>
                            <div />
                          </div>
                          <div className="form-grid form-grid-3" style={{ marginTop: 8 }}>
                            <FormField label="ICMS (%)" hint={camada?.isencao_icms ? "ISENTO — NCM 3822" : ""}>
                              <TextInput value={editIcms || String(camada?.icms ?? "")} onChange={setEditIcms} placeholder="0" />
                            </FormField>
                            <FormField label="IPI (%)">
                              <TextInput value={editIpi || String(camada?.ipi ?? "")} onChange={setEditIpi} placeholder="0" />
                            </FormField>
                            <FormField label="PIS+COFINS (%)">
                              <TextInput value={editPisCofins || String(camada?.pis_cofins ?? "")} onChange={setEditPisCofins} placeholder="9.25" />
                            </FormField>
                          </div>
                          <div style={{ marginTop: 8 }}>
                            <ActionButton icon={<Check size={16} />} label="Salvar Custos" variant="primary" onClick={handleSalvarCustos} />
                          </div>
                          {camada?.custo_base_final && (
                            <div style={{ marginTop: 12, padding: 12, background: "var(--bg-secondary, #f5f5f5)", borderRadius: 8, fontSize: 13 }}>
                              <strong>Custo Final: {fmt(camada.custo_base_final)}</strong>
                              <span style={{ marginLeft: 12, color: "var(--text-secondary)" }}>
                                (ICMS: {pct(camada.icms)}{camada.isencao_icms ? " ISENTO" : ""} | IPI: {pct(camada.ipi)} | PIS+COFINS: {pct(camada.pis_cofins)})
                              </span>
                            </div>
                          )}
                        </Card>

                        {/* UC-P05: Preço Base */}
                        <Card title="Preço Base" icon={<TrendingUp size={18} />}>
                          {/* Explicação IA */}
                          {insights && insights.tem_dados && insights.recomendacao.preco_base_sugerido && (
                            <div style={{ padding: "8px 12px", borderRadius: 6, backgroundColor: "#3b82f608", border: "1px solid #3b82f620", fontSize: 12, color: "var(--text-secondary)", marginBottom: 12 }}>
                              <Sparkles size={12} style={{ display: "inline", marginRight: 4, color: "#3b82f6" }} />
                              <strong>IA:</strong> Preço base sugerido de <strong>{fmt(insights.recomendacao.preco_base_sugerido)}</strong> — 97% da média dos vencedores ({fmt(insights.historico.preco_medio)}).
                              Faixa competitiva: {fmt(insights.recomendacao.faixa.agressivo)} (agressivo) a {fmt(insights.recomendacao.faixa.conservador)} (conservador).
                              {insights.recomendacao.markup_sugerido ? ` Markup implícito: ${insights.recomendacao.markup_sugerido}%.` : ""}
                            </div>
                          )}
                          <div className="form-grid form-grid-3">
                            <FormField label="Modo">
                              <SelectInput value={modoPrecoBase} onChange={setModoPrecoBase} options={[
                                { value: "markup", label: "Custo + Markup" },
                                { value: "manual", label: "Manual" },
                                { value: "upload", label: "Upload" },
                              ]} />
                            </FormField>
                            {modoPrecoBase === "markup" ? (
                              <FormField label="Markup (%)">
                                <TextInput value={markup} onChange={setMarkup} placeholder="30" />
                              </FormField>
                            ) : modoPrecoBase === "upload" ? (
                              <FormField label="Tabela de Preços (.csv)">
                                <input type="file" accept=".csv" style={{ fontSize: 13 }} onChange={(e) => {
                                  const file = e.target.files?.[0];
                                  if (!file) return;
                                  const reader = new FileReader();
                                  reader.onload = (ev) => {
                                    const text = ev.target?.result as string;
                                    const lines = text.split("\n").filter(l => l.trim());
                                    // Tentar extrair preço da primeira linha de dados (pular header)
                                    for (let i = 1; i < lines.length; i++) {
                                      const cols = lines[i].split(/[;,\t]/);
                                      const preco = cols.find(c => /^\d+[.,]\d+$/.test(c.trim()));
                                      if (preco) { setPrecoBaseManual(preco.trim().replace(",", ".")); break; }
                                    }
                                  };
                                  reader.readAsText(file);
                                }} />
                              </FormField>
                            ) : (
                              <FormField label="Preço Base (R$)">
                                <TextInput value={precoBaseManual} onChange={setPrecoBaseManual} placeholder="Preço de venda" />
                              </FormField>
                            )}
                            <div className="form-field-actions">
                              <ActionButton icon={<Check size={16} />} label="Salvar Preço Base" variant="primary" onClick={handleSalvarPrecoBase} />
                            </div>
                          </div>
                          <div style={{ marginTop: 8 }}>
                            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer", color: "var(--text-secondary)" }}>
                              <input type="checkbox" checked={reutilizarPreco} onChange={(e) => setReutilizarPreco(e.target.checked)} />
                              Reutilizar este Preço Base em outros editais
                            </label>
                          </div>
                          {camada?.preco_base && (
                            <div style={{ marginTop: 12, padding: 12, background: "var(--bg-secondary, #f5f5f5)", borderRadius: 8, fontSize: 13 }}>
                              Custo: {fmt(camada.custo_base_final)} → <strong>Preço Base: {fmt(camada.preco_base)}</strong>
                              {camada.markup_percentual && <span> (markup: {pct(camada.markup_percentual)})</span>}
                            </div>
                          )}
                        </Card>

                        {/* UC-P06: Valor de Referência */}
                        <Card title="Valor de Referência" icon={<Target size={18} />}>
                          {/* Explicação IA */}
                          {insights && insights.tem_dados && (insights.referencia_edital || insights.recomendacao.referencia_sugerida) && (
                            <div style={{ padding: "8px 12px", borderRadius: 6, backgroundColor: "#3b82f608", border: "1px solid #3b82f620", fontSize: 12, color: "var(--text-secondary)", marginBottom: 12 }}>
                              <Sparkles size={12} style={{ display: "inline", marginRight: 4, color: "#3b82f6" }} />
                              <strong>IA:</strong> {insights.referencia_edital
                                ? `Valor de referência do edital: ${fmt(insights.referencia_edital)}. Este é o teto estimado pelo órgão.`
                                : `Referência sugerida de ${fmt(insights.recomendacao.referencia_sugerida)} — 99% da média histórica (preço conservador). Serve como target estratégico na disputa.`
                              }
                            </div>
                          )}
                          <div className="form-grid form-grid-3">
                            <FormField label="Valor Referência (R$)" hint={camada?.valor_referencia_disponivel ? "Importado do edital" : "Não disponível no edital"}>
                              <TextInput value={valorRef} onChange={setValorRef} placeholder="Target estratégico" />
                            </FormField>
                            <FormField label="OU % sobre Preço Base">
                              <TextInput value={pctSobreBase || String(camada?.percentual_sobre_base || "")} onChange={setPctSobreBase} placeholder="95" />
                            </FormField>
                            <div className="form-field-actions">
                              <ActionButton icon={<Check size={16} />} label="Salvar Target" variant="primary" onClick={handleSalvarReferencia} />
                            </div>
                          </div>
                          {camada?.target_referencia && (
                            <div style={{ marginTop: 12, padding: 12, background: "var(--bg-secondary, #f5f5f5)", borderRadius: 8, fontSize: 13 }}>
                              <strong>Comparativo:</strong> Custo={fmt(camada.custo_base_final)} | Preço Base={fmt(camada.preco_base)} | <strong>Referência={fmt(camada.target_referencia)}</strong>
                              {camada.margem_sobre_custo != null && <span> | Margem: {pct(camada.margem_sobre_custo)}</span>}
                            </div>
                          )}
                        </Card>
                      </>
                    )}
                  </div>
                )}

                {/* ═══════════════════ TAB: LANCES (UC-P07 + UC-P08) ═══════════════════ */}
                {activeTab === "lances" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    {/* Item-Produto selector */}
                    <Card title="Selecionar Item-Produto" icon={<Package size={18} />}>
                      <FormField label="Vínculo Item ↔ Produto">
                        <SelectInput value={vinculoId} onChange={setVinculoId} options={vinculoOptions} />
                      </FormField>
                    </Card>

                    {vinculoId && (
                      <>
                        {/* Explicação IA dos lances */}
                        {insights && (insights as Record<string, unknown>).tem_dados && (
                          <Card title="Sugestões IA para Lances" icon={<Sparkles size={18} />}>
                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
                              <div style={{ padding: "8px 12px", borderRadius: 6, backgroundColor: "#3b82f608", border: "1px solid #3b82f620", fontSize: 12 }}>
                                <Sparkles size={12} style={{ display: "inline", marginRight: 4, color: "#3b82f6" }} />
                                <strong>Lance Inicial sugerido: {fmt((insights.recomendacao as Record<string, unknown>).lance_inicial_sugerido as number)}</strong>
                                <p style={{ margin: "4px 0 0", color: "var(--text-secondary)" }}>
                                  Igual ao preço base sugerido. Valor de entrada no pregão.
                                  {insights.recomendacao.faixa.agressivo && insights.recomendacao.faixa.conservador &&
                                    ` Faixa: ${fmt(insights.recomendacao.faixa.agressivo)} (agressivo) a ${fmt(insights.recomendacao.faixa.conservador)} (conservador).`}
                                </p>
                              </div>
                              <div style={{ padding: "8px 12px", borderRadius: 6, backgroundColor: "#3b82f608", border: "1px solid #3b82f620", fontSize: 12 }}>
                                <Sparkles size={12} style={{ display: "inline", marginRight: 4, color: "#3b82f6" }} />
                                <strong>Lance Mínimo sugerido: {fmt((insights.recomendacao as Record<string, unknown>).lance_minimo_sugerido as number)}</strong>
                                <p style={{ margin: "4px 0 0", color: "var(--text-secondary)" }}>
                                  Custo sugerido ({fmt(insights.recomendacao.custo_sugerido)}) + 10% de margem. Abaixo disso, prejuízo.
                                </p>
                              </div>
                            </div>
                            {insights.recomendacao.justificativa && (
                              <details style={{ fontSize: 12 }}>
                                <summary style={{ cursor: "pointer", color: "var(--text-secondary)", marginBottom: 6 }}>
                                  Recomendação IA completa
                                </summary>
                                <div className="markdown-response" style={{ fontSize: 12, padding: "8px 12px", borderRadius: 8, backgroundColor: "var(--bg-secondary, #f5f5f5)", border: "1px solid var(--border)", maxHeight: 200, overflowY: "auto" }}>
                                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{insights.recomendacao.justificativa}</ReactMarkdown>
                                </div>
                              </details>
                            )}
                            <div style={{ marginTop: 8 }}>
                              <ActionButton icon={<FileText size={14} />} label="Relatório de Custos e Preços" variant="neutral" onClick={handleRelatorioCustoPreco} />
                            </div>
                          </Card>
                        )}

                        {/* UC-P07: Lances D + E */}
                        <Card title="Estrutura de Lances" icon={<Target size={18} />}>
                          <div className="form-grid form-grid-2">
                            <div>
                              <h4 style={{ marginBottom: 8 }}>Valor Inicial do Lance</h4>
                              <FormField label="Modo">
                                <SelectInput value={modoInicial} onChange={setModoInicial} options={[
                                  { value: "absoluto", label: "Valor Absoluto" },
                                  { value: "percentual_referencia", label: "% da Referência" },
                                ]} />
                              </FormField>
                              <FormField label="Valor Inicial (R$)">
                                <TextInput value={lanceInicial} onChange={setLanceInicial} placeholder="Valor do lance inicial" />
                              </FormField>
                            </div>
                            <div>
                              <h4 style={{ marginBottom: 8 }}>Valor Mínimo do Lance</h4>
                              <FormField label="Modo">
                                <SelectInput value={modoMinimo} onChange={setModoMinimo} options={[
                                  { value: "absoluto", label: "Valor Absoluto" },
                                  { value: "percentual_desconto", label: "% Desconto Máximo" },
                                ]} />
                              </FormField>
                              {modoMinimo === "absoluto" ? (
                                <FormField label="Valor Mínimo (R$)">
                                  <TextInput value={lanceMinimo} onChange={setLanceMinimo} placeholder="Valor mínimo aceitável" />
                                </FormField>
                              ) : (
                                <FormField label="Desconto Máximo (%)">
                                  <TextInput value={descontoMax} onChange={setDescontoMax} placeholder="36.67" />
                                </FormField>
                              )}
                            </div>
                          </div>
                          <div style={{ marginTop: 12 }}>
                            <ActionButton icon={<Check size={16} />} label="Salvar Lances" variant="primary" onClick={handleSalvarLances} />
                          </div>

                          {/* Barra visual */}
                          {camada && (camada.lance_inicial || camada.lance_minimo) && (() => {
                            const custo = camada.custo_base_final || 0;
                            const ini = camada.lance_inicial || 0;
                            const min = camada.lance_minimo || 0;
                            const target = camada.target_referencia || 0;
                            const maxVal = Math.max(custo, ini, min, target, 1);
                            const scale = (v: number) => `${Math.min((v / maxVal) * 100, 100)}%`;
                            return (
                              <div style={{ marginTop: 16, padding: 12, background: "var(--bg-secondary, #f5f5f5)", borderRadius: 8 }}>
                                <p style={{ fontSize: 12, marginBottom: 8 }}><strong>Barra de Faixa de Disputa</strong></p>
                                <div style={{ position: "relative", height: 24, background: "#e5e7eb", borderRadius: 12, overflow: "hidden" }}>
                                  {custo > 0 && <div style={{ position: "absolute", left: 0, width: scale(custo), height: "100%", background: "#ef4444", opacity: 0.3 }} />}
                                  {min > 0 && <div style={{ position: "absolute", left: scale(min), width: `calc(${scale(ini)} - ${scale(min)})`, height: "100%", background: "#22c55e", opacity: 0.3 }} />}
                                </div>
                                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginTop: 4 }}>
                                  <span>Custo: {fmt(custo)}</span>
                                  <span>Mínimo: {fmt(min)}</span>
                                  <span>Target: {fmt(target)}</span>
                                  <span>Inicial: {fmt(ini)}</span>
                                </div>
                                {camada.margem_minima != null && (
                                  <p style={{ fontSize: 12, marginTop: 4 }}>
                                    Margem mínima: <strong>{pct(camada.margem_minima)}</strong>
                                    {(camada.margem_minima ?? 0) < 0 && <span style={{ color: "red", marginLeft: 4 }}><AlertTriangle size={12} /> Abaixo do custo!</span>}
                                  </p>
                                )}
                              </div>
                            );
                          })()}
                        </Card>

                        {/* UC-P08: Estratégia Competitiva */}
                        <Card title="Estratégia Competitiva (UC-P08)" icon={<Shield size={18} />}>
                          {/* Explanation card */}
                          <div style={{
                            background: "var(--bg-secondary, #f8f9fa)", borderRadius: 8,
                            padding: 16, marginBottom: 16, border: "1px solid var(--border-light, #e2e8f0)",
                          }}>
                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
                              <div>
                                <h4 style={{ margin: "0 0 6px", fontSize: 14 }}>🏆 "Quero Ganhar"</h4>
                                <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
                                  Disputa agressiva: lances decrescentes até o valor mínimo (E).
                                  Máxima chance de vitória.
                                </p>
                                <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--color-danger, #ef4444)" }}>
                                  Risco: margem mínima.
                                </p>
                              </div>
                              <div>
                                <h4 style={{ margin: "0 0 6px", fontSize: 14 }}>📊 "Não Ganhei no Mínimo"</h4>
                                <p style={{ margin: 0, fontSize: 13, color: "var(--text-secondary)" }}>
                                  Reposicionamento: se não ganhou com lance mínimo, posicionar para melhor colocação possível.
                                </p>
                                <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--color-info, #3b82f6)" }}>
                                  Objetivo: 2º ou 3º lugar para futuras negociações.
                                </p>
                              </div>
                            </div>
                            {insights && insights.recomendacao?.faixa?.agressivo != null && insights.recomendacao?.faixa?.conservador != null && (
                              <div style={{
                                marginTop: 12, padding: "10px 14px", borderRadius: 6,
                                background: "#1e3a5f", border: "1px solid #3b82f6",
                                fontSize: 13, color: "#e2e8f0",
                              }}>
                                <strong style={{ color: "#93c5fd" }}>💡 Insight histórico:</strong>{" "}
                                Com base no histórico, lance entre{" "}
                                <strong style={{ color: "#60a5fa" }}>{fmt(insights.recomendacao.faixa.agressivo)}</strong> e{" "}
                                <strong style={{ color: "#60a5fa" }}>{fmt(insights.recomendacao.faixa.conservador)}</strong>{" "}
                                tem maior chance de vitória.
                                {insights.historico?.qtd_registros > 0 && (
                                  <span style={{ marginLeft: 8, color: "#94a3b8" }}>
                                    ({insights.historico.qtd_registros} registros analisados)
                                  </span>
                                )}
                              </div>
                            )}
                          </div>

                          <div className="form-grid form-grid-2">
                            <div
                              onClick={() => setPerfil("quero_ganhar")}
                              style={{
                                padding: 16, borderRadius: 8, cursor: "pointer",
                                border: perfil === "quero_ganhar" ? "2px solid #22c55e" : "1px solid var(--border)",
                                background: perfil === "quero_ganhar" ? "#22c55e" : "transparent",
                                color: perfil === "quero_ganhar" ? "#fff" : "var(--text-primary)",
                              }}
                            >
                              <h4 style={{ color: perfil === "quero_ganhar" ? "#fff" : "var(--text-primary)" }}>🏆 QUERO GANHAR</h4>
                              <p style={{ fontSize: 13, color: perfil === "quero_ganhar" ? "#dcfce7" : "var(--text-secondary)" }}>Disputa agressiva até o lance mínimo — máxima chance de vitória</p>
                            </div>
                            <div
                              onClick={() => setPerfil("nao_ganhei_minimo")}
                              style={{
                                padding: 16, borderRadius: 8, cursor: "pointer",
                                border: perfil === "nao_ganhei_minimo" ? "2px solid #f59e0b" : "1px solid var(--border)",
                                background: perfil === "nao_ganhei_minimo" ? "#f59e0b" : "transparent",
                                color: perfil === "nao_ganhei_minimo" ? "#fff" : "var(--text-primary)",
                              }}
                            >
                              <h4 style={{ color: perfil === "nao_ganhei_minimo" ? "#fff" : "var(--text-primary)" }}>📊 NÃO GANHEI NO MÍNIMO</h4>
                              <p style={{ fontSize: 13, color: perfil === "nao_ganhei_minimo" ? "#fef3c7" : "var(--text-secondary)" }}>Reposicionar para melhor colocação (2º, 3º lugar)</p>
                            </div>
                          </div>
                          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
                            <ActionButton icon={<TrendingUp size={16} />} label="Análise de Lances" variant="primary" onClick={handleSimularEstrategia} />
                            <ActionButton icon={<Sparkles size={16} />} label="Análise por IA" variant="neutral" loading={cenarioExplicacaoLoading}
                              onClick={async () => {
                                if (!vinculoId) { alert("Selecione um vínculo."); return; }
                                setCenarios([]);
                                setCenarioExplicacaoIA(null);
                                setCenarioExplicacaoLoading(true);
                                try {
                                  const prod = produtos.find(p => p.id === vinculos.find(v => v.id === vinculoId)?.produto_id);
                                  const custoReal = camada?.custo_base_final ? Number(camada.custo_base_final) : 0;
                                  const lanceIniReal = lanceInicial ? parseFloat(lanceInicial) : Number(camada?.lance_inicial || 0);
                                  const lanceMinReal = lanceMinimo ? parseFloat(lanceMinimo) : Number(camada?.lance_minimo || 0);
                                  const histInfo = insights ? `Histórico: ${insights.historico.qtd_registros} registros, mín R$ ${insights.historico.preco_min}, média R$ ${insights.historico.preco_medio}, máx R$ ${insights.historico.preco_max}` : "Sem histórico disponível";
                                  const concInfo = insights?.concorrentes?.length ? insights.concorrentes.map(c => `${c.nome} (preço médio: R$ ${c.preco_medio})`).join(", ") : "Sem concorrentes identificados";

                                  const prompt = `Você é um especialista em licitações públicas. Analise a situação e gere cenários de disputa de lances.

PRODUTO: ${prod?.nome || "Produto"}
CUSTO BASE: R$ ${custoReal.toFixed(2)}
LANCE INICIAL DEFINIDO: R$ ${lanceIniReal.toFixed(2)}
LANCE MÍNIMO DEFINIDO: R$ ${lanceMinReal.toFixed(2)}
ESTRATÉGIA: ${perfil === "quero_ganhar" ? "QUERO GANHAR — disputa agressiva até o mínimo" : "NÃO GANHEI NO MÍNIMO — reposicionar para melhor colocação"}
${histInfo}
CONCORRENTES: ${concInfo}
${insights?.recomendacao?.justificativa ? `\nCONTEXTO:\n${insights.recomendacao.justificativa.slice(0, 800)}` : ""}

Gere EXATAMENTE 3 cenários de lance em formato JSON seguido de explicação detalhada.

PRIMEIRO, retorne um bloco JSON com os cenários:
\`\`\`json
[
  {"label": "Nome do cenário", "valor": 99.99, "margem": 15.5},
  {"label": "Nome do cenário", "valor": 88.88, "margem": 8.2},
  {"label": "Nome do cenário", "valor": 77.77, "margem": 2.1}
]
\`\`\`

DEPOIS, explique cada cenário em detalhes:
## Cenário 1: [nome]
- O que significa esse lance
- Margem e viabilidade
- Riscos e vantagens
- Quando usar

## Cenário 2: [nome]
...

## Cenário 3: [nome]
...

## Recomendação Final
Qual cenário é mais adequado e por quê.`;

                                  // Chamar endpoint dedicado (não o chat, que intercepta keywords)
                                  const token = localStorage.getItem("editais_ia_access_token");
                                  const res = await fetch("/api/precificacao/simular-ia", {
                                    method: "POST",
                                    headers: { "Content-Type": "application/json", Authorization: token ? `Bearer ${token}` : "" },
                                    body: JSON.stringify({ prompt }),
                                  });
                                  const resp = await res.json();
                                  if (!resp.success) throw new Error(resp.error || "Erro na simulação IA");
                                  const respText = resp.response || "";

                                  // Extrair JSON dos cenários
                                  const jsonMatch = respText.match(/```json\s*([\s\S]*?)```/);
                                  if (jsonMatch) {
                                    try {
                                      const parsed = JSON.parse(jsonMatch[1]) as Record<string, unknown>[];
                                      const iaCens = parsed.map(c => ({
                                        label: `🤖 ${c.label}`,
                                        valor: Number(c.valor || 0),
                                        margem: Number(c.margem || 0),
                                      }));
                                      setCenarios(iaCens);
                                    } catch { /* JSON parse failed, cenários ficam vazios */ }
                                  }

                                  // A explicação é tudo depois do JSON (ou tudo se não teve JSON)
                                  const explicacao = jsonMatch
                                    ? respText.slice(respText.indexOf("```", respText.indexOf("```json") + 7) + 3).trim()
                                    : respText;
                                  setCenarioExplicacaoIA(explicacao || respText);
                                } catch (e) {
                                  console.error("[SIMULACAO IA]", e);
                                  setCenarioExplicacaoIA(`Erro: ${e instanceof Error ? e.message : "Falha na simulação IA"}`);
                                } finally {
                                  setCenarioExplicacaoLoading(false);
                                }
                              }}
                            />
                            <ActionButton icon={<Target size={16} />} label="Simulador de Disputa" variant="neutral" loading={disputaLoading}
                              onClick={async () => {
                                if (!vinculoId) { alert("Selecione um vínculo."); return; }
                                setDisputaSimulacaoMD(null);
                                setDisputaLoading(true);
                                try {
                                  const lanceIniReal = lanceInicial ? parseFloat(lanceInicial) : Number(camada?.lance_inicial || 0);
                                  const lanceMinReal = lanceMinimo ? parseFloat(lanceMinimo) : Number(camada?.lance_minimo || 0);
                                  const custoReal = camada?.custo_base_final ? Number(camada.custo_base_final) : 0;
                                  const prod = produtos.find(p => p.id === vinculos.find(v => v.id === vinculoId)?.produto_id);

                                  // Montar dados dos concorrentes
                                  const concs = (insights?.concorrentes || []).map(c => ({
                                    nome: c.nome,
                                    preco_medio: c.preco_medio,
                                    precos_historicos: [] as number[],
                                  }));
                                  // Enriquecer com preços detalhados dos vencedores
                                  const vencDet = (insights as Record<string, unknown>)?.vencedores_detalhes as Array<Record<string, unknown>> | undefined;
                                  if (vencDet) {
                                    for (const ata of vencDet) {
                                      for (const v of ((ata.vencedores || []) as Array<Record<string, unknown>>)) {
                                        const nome = String(v.vencedor || "");
                                        const preco = Number(v.valor_homologado || 0);
                                        if (nome && preco > 0) {
                                          const conc = concs.find(c => nome.includes(c.nome.split(" ")[0]));
                                          if (conc) conc.precos_historicos.push(preco);
                                        }
                                      }
                                    }
                                  }

                                  const token = localStorage.getItem("editais_ia_access_token");
                                  const res = await fetch("/api/precificacao/simular-disputa", {
                                    method: "POST",
                                    headers: { "Content-Type": "application/json", Authorization: token ? `Bearer ${token}` : "" },
                                    body: JSON.stringify({
                                      lance_inicial: lanceIniReal,
                                      lance_minimo: lanceMinReal,
                                      custo: custoReal,
                                      perfil,
                                      concorrentes: concs,
                                      historico: insights?.historico || {},
                                      produto: prod?.nome || "Produto",
                                    }),
                                  });
                                  const resp = await res.json();
                                  if (!resp.success) throw new Error(resp.error || "Erro na simulação");
                                  setDisputaSimulacaoMD(resp.simulacao_md || "Simulação sem resultado.");
                                } catch (e) {
                                  console.error("[DISPUTA]", e);
                                  setDisputaSimulacaoMD(`Erro: ${e instanceof Error ? e.message : "Falha na simulação de disputa"}`);
                                } finally {
                                  setDisputaLoading(false);
                                }
                              }}
                            />
                          </div>
                          {cenarios.length > 0 && (
                            <div style={{ marginTop: 12, fontSize: 13 }}>
                              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                                <h4>Simulações ({cenarios.length} cenários)</h4>
                                <button onClick={() => setCenarios([])} style={{ fontSize: 11, background: "none", border: "none", color: "var(--text-secondary)", cursor: "pointer" }}>Limpar</button>
                              </div>
                              <div style={{ display: "grid", gridTemplateColumns: `repeat(${Math.min(cenarios.length, 3)}, 1fr)`, gap: 8 }}>
                                {cenarios.map((c, i) => {
                                  const label = String(c.label || `Cenário ${i + 1}`);
                                  const valor = Number(c.valor || 0);
                                  const margem = Number(c.margem || 0);
                                  const isNeg = margem < 0;
                                  const isIA = label.startsWith("IA ");
                                  return (
                                    <div key={i} style={{
                                      padding: 12, borderRadius: 8, textAlign: "center",
                                      border: isIA ? "1px solid #8b5cf640" : "1px solid var(--border)",
                                      backgroundColor: isIA ? "#8b5cf610" : "transparent",
                                    }}>
                                      <p style={{ fontSize: 10, color: isIA ? "#8b5cf6" : "var(--text-secondary)", fontWeight: 600, marginBottom: 4 }}>
                                        {isIA && "🤖 "}{label}
                                      </p>
                                      <p style={{ fontSize: 18, fontWeight: 700 }}>{valor > 0 ? fmt(valor) : "—"}</p>
                                      <p style={{ fontSize: 11, color: isNeg ? "#ef4444" : "#22c55e", marginTop: 4 }}>
                                        Margem: {margem.toFixed(1)}%{isNeg && " ⚠️"}
                                      </p>
                                    </div>
                                  );
                                })}
                              </div>
                              {cenarios.some(c => Number(c.margem || 0) < 0) && (
                                <p style={{ marginTop: 8, fontSize: 12, color: "#ef4444" }}>
                                  ⚠️ Cenários com margem negativa indicam prejuízo. Revise custos e lances.
                                </p>
                              )}
                              {cenarios.length > 6 && (
                                <p style={{ marginTop: 4, fontSize: 11, color: "var(--text-secondary)" }}>
                                  Mostrando 6 de {cenarios.length} cenários.
                                </p>
                              )}
                            </div>
                          )}

                          {/* Explicação IA dos cenários */}
                          {cenarioExplicacaoLoading && (
                            <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 8, color: "#60a5fa", fontSize: 13 }}>
                              <Loader2 size={14} className="spin" /> Gerando análise IA dos cenários...
                            </div>
                          )}
                          {cenarioExplicacaoIA && !cenarioExplicacaoLoading && (
                            <div style={{ marginTop: 12 }}>
                              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                                <h4 style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                  <Sparkles size={14} style={{ color: "#8b5cf6" }} /> Análise IA dos Cenários
                                </h4>
                                <ActionButton icon={<FileText size={12} />} label="Relatório MD/PDF" variant="neutral" onClick={handleExportarExplicacaoCenarios} />
                              </div>
                              <div className="markdown-response" style={{ fontSize: 12, padding: "12px", borderRadius: 8, backgroundColor: "var(--bg-secondary, #f5f5f5)", border: "1px solid var(--border)", maxHeight: 400, overflowY: "auto" }}>
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>{cenarioExplicacaoIA}</ReactMarkdown>
                              </div>
                            </div>
                          )}

                          {/* Simulador de Disputa */}
                          {disputaLoading && (
                            <div style={{ marginTop: 16, display: "flex", alignItems: "center", gap: 8, color: "#f59e0b", fontSize: 13 }}>
                              <Loader2 size={14} className="spin" /> Simulando disputa de lances com IA...
                            </div>
                          )}
                          {disputaSimulacaoMD && !disputaLoading && (
                            <div style={{ marginTop: 16 }}>
                              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                                <h4 style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                  <Target size={14} style={{ color: "#f59e0b" }} /> Simulação de Disputa
                                </h4>
                                <ActionButton icon={<FileText size={12} />} label="Relatório MD/PDF" variant="neutral" onClick={() => {
                                  const now = new Date();
                                  const dataHora = now.toLocaleString("pt-BR");
                                  const prod = vinculoId ? produtos.find(p => p.id === vinculos.find(v => v.id === vinculoId)?.produto_id) : null;
                                  const ed = editais.find(e => (e.id ?? e.numero) === editalId);
                                  let md = `# Simulação de Disputa de Lances\n\n**Data:** ${dataHora}\n**Edital:** ${ed?.numero || ""} — ${ed?.orgao || ""}\n**Produto:** ${prod?.nome || ""}\n**Estratégia:** ${perfil === "quero_ganhar" ? "Quero Ganhar" : "Não Ganhei no Mínimo"}\n\n---\n\n${disputaSimulacaoMD}`;
                                  const tableRegex = /(\|.+\|\n)+/g;
                                  let html = md.replace(tableRegex, (tb) => { const rows = tb.trim().split('\n').filter(r => r.trim()); if (rows.length < 2) return tb; let t = '<table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;border-color:#334155;margin:8px 0;width:100%;font-size:13px;">\n'; rows.forEach((row, ri) => { if (ri === 1 && row.match(/^\|[\s-|]+\|$/)) return; const cells = row.split('|').filter((_, ci, arr) => ci > 0 && ci < arr.length - 1).map(c => c.trim()); const tag = ri === 0 ? 'th' : 'td'; const bg = ri === 0 ? ' style="background:#1e293b;color:#94a3b8;text-align:left;"' : ''; t += '<tr>' + cells.map(c => `<${tag}${bg}>${c}</${tag}>`).join('') + '</tr>\n'; }); t += '</table>\n'; return t; });
                                  html = html.replace(/^### (.+)$/gm, '<h3 style="color:#818cf8;margin:24px 0 12px;">$1</h3>').replace(/^## (.+)$/gm, '<h2 style="color:#a78bfa;margin:32px 0 16px;">$1</h2>').replace(/^# (.+)$/gm, '<h1 style="color:#e2e8f0;margin:0 0 24px;">$1</h1>').replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/^- (.+)$/gm, '<div style="padding:2px 0 2px 16px;">• $1</div>').replace(/^---$/gm, '<hr style="border:none;border-top:1px solid #334155;margin:24px 0;"/>');
                                  const fullHtml = `<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Simulação de Disputa — ${dataHora}</title><style>body{background:#0f172a;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,monospace;max-width:1100px;margin:0 auto;padding:64px 24px 32px;line-height:1.6}table{font-size:13px}th{font-weight:600}td,th{padding:6px 10px;border:1px solid #334155}tr:nth-child(even){background:#1e293b}strong{color:#f1f5f9}@media print{body{background:white;color:#1e293b;padding-top:0}h1,h2,h3,strong{color:#1e293b}td,th{border-color:#cbd5e1}tr:nth-child(even){background:#f1f5f9}.toolbar{display:none!important}}.toolbar{position:fixed;top:0;left:0;right:0;z-index:1000;background:#1e293b;border-bottom:2px solid #334155;padding:10px 24px;display:flex;gap:12px;align-items:center}.toolbar button{padding:8px 18px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600}.btn-md{background:#3b82f6;color:white}.btn-pdf{background:#8b5cf6;color:white}.toolbar span{color:#94a3b8;font-size:13px;margin-left:auto}</style></head><body><div class="toolbar"><button class="btn-md" onclick="baixarMD()">📥 Baixar MD</button><button class="btn-pdf" onclick="window.print()">📄 Baixar PDF</button><span>${dataHora}</span></div>${html}<script>var mdContent=${JSON.stringify(md)};function baixarMD(){var b=new Blob(['\\uFEFF'+mdContent],{type:'text/markdown;charset=utf-8;'});var u=URL.createObjectURL(b);var a=document.createElement('a');a.href=u;a.download='simulacao_disputa_${now.toISOString().slice(0, 10)}.md';a.click()}</script></body></html>`;
                                  window.open(URL.createObjectURL(new Blob([fullHtml], { type: 'text/html;charset=utf-8' })), '_blank');
                                }} />
                              </div>
                              <div className="markdown-response" style={{ fontSize: 12, padding: "12px", borderRadius: 8, backgroundColor: "#1e293b", border: "1px solid #f59e0b40", maxHeight: 500, overflowY: "auto" }}>
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>{disputaSimulacaoMD}</ReactMarkdown>
                              </div>
                            </div>
                          )}
                        </Card>
                      </>
                    )}
                  </div>
                )}

                {/* ═══════════════════ TAB: ESTRATÉGIA (Sprint 9) ═══════════════════ */}
                {activeTab === "estrategia" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

                    {/* ── UC-SC01: Score de Competitividade ── */}
                    <Card title="Score de Competitividade (UC-SC01)" icon={<BarChart3 size={18} />}>
                      {scoreCompLoading ? (
                        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "16px 0", color: "var(--text-secondary)" }}>
                          <Loader2 size={16} className="spin" /> Carregando score...
                        </div>
                      ) : scoreComp ? (
                        <div>
                          <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
                            <div style={{
                              width: 72, height: 72, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center",
                              fontSize: 24, fontWeight: 700, color: "#fff",
                              background: Number(scoreComp.score ?? 0) > 70 ? "#22c55e" : Number(scoreComp.score ?? 0) >= 40 ? "#eab308" : "#ef4444",
                            }}>
                              {Number(scoreComp.score ?? 0)}
                            </div>
                            <div>
                              <p style={{ fontSize: 14, fontWeight: 600, margin: 0 }}>
                                Competitividade: {Number(scoreComp.score ?? 0) > 70 ? "Alta" : Number(scoreComp.score ?? 0) >= 40 ? "Média" : "Baixa"}
                              </p>
                              {scoreComp.bootstrap_pncp ? (
                                <span style={{
                                  display: "inline-block", marginTop: 4, fontSize: 11, padding: "2px 8px",
                                  borderRadius: 4, background: "#3b82f620", color: "#3b82f6", border: "1px solid #3b82f640",
                                }}>
                                  estimativa PNCP
                                </span>
                              ) : null}
                            </div>
                          </div>
                          {Array.isArray(scoreComp.fatores) && (scoreComp.fatores as Array<Record<string, unknown>>).map((f, i) => (
                            <div key={i} style={{ marginBottom: 8 }}>
                              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 2 }}>
                                <span>{String(f.nome ?? f.label ?? `Fator ${i + 1}`)}</span>
                                <span style={{ fontWeight: 600 }}>{Number(f.valor ?? f.score ?? 0).toFixed(0)}%</span>
                              </div>
                              <div style={{ height: 6, borderRadius: 3, background: "#e5e7eb", overflow: "hidden" }}>
                                <div style={{
                                  height: "100%", borderRadius: 3, transition: "width 0.3s",
                                  width: `${Math.min(Number(f.valor ?? f.score ?? 0), 100)}%`,
                                  background: Number(f.valor ?? f.score ?? 0) > 70 ? "#22c55e" : Number(f.valor ?? f.score ?? 0) >= 40 ? "#eab308" : "#ef4444",
                                }} />
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p style={{ color: "var(--text-secondary)", padding: "12px 0", fontSize: 13 }}>
                          {editalId ? "Score não disponível para este edital." : "Selecione um edital para ver o score."}
                        </p>
                      )}
                    </Card>

                    {/* ── UC-LA01: Simulador Determinístico ── */}
                    <Card title="Simulador Determinístico (UC-LA01)" icon={<Target size={18} />}
                      actions={
                        <button onClick={() => setSimDetOpen(!simDetOpen)} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)" }}>
                          {simDetOpen ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
                        </button>
                      }
                    >
                      {simDetOpen && (
                        <div>
                          <div className="form-grid form-grid-3" style={{ marginBottom: 12 }}>
                            <FormField label="Nº Rodadas">
                              <TextInput value={simDetNumRodadas} onChange={setSimDetNumRodadas} placeholder="10" />
                            </FormField>
                            <FormField label="Tipo Decremento">
                              <SelectInput value={simDetTipoDecremento} onChange={setSimDetTipoDecremento} options={[
                                { value: "fixo_reais", label: "Fixo (R$)" },
                                { value: "percentual_ultimo", label: "Percentual do último" },
                              ]} />
                            </FormField>
                            <FormField label="Valor Decremento">
                              <TextInput value={simDetValorDecremento} onChange={setSimDetValorDecremento} placeholder="0.50" />
                            </FormField>
                            <FormField label="Nº Concorrentes">
                              <TextInput value={simDetNumConcorrentes} onChange={setSimDetNumConcorrentes} placeholder="3" />
                            </FormField>
                            <FormField label="Perfil">
                              <SelectInput value={simDetPerfil} onChange={setSimDetPerfil} options={[
                                { value: "quero_ganhar", label: "Quero Ganhar" },
                                { value: "nao_ganhei_minimo", label: "Não Ganhei no Mínimo" },
                              ]} />
                            </FormField>
                          </div>
                          <ActionButton
                            icon={<TrendingUp size={16} />}
                            label="Simular"
                            variant="primary"
                            loading={simDetLoading}
                            disabled={!vinculoId}
                            onClick={async () => {
                              if (!vinculoId) { alert("Selecione um vínculo na aba Lances."); return; }
                              setSimDetLoading(true);
                              setSimDetResult(null);
                              try {
                                const res = await simularLanceDeterministico({
                                  edital_item_produto_id: vinculoId,
                                  num_rodadas: parseInt(simDetNumRodadas) || 10,
                                  tipo_decremento: simDetTipoDecremento,
                                  valor_decremento: parseFloat(simDetValorDecremento) || undefined,
                                  num_concorrentes: parseInt(simDetNumConcorrentes) || 3,
                                  perfil: simDetPerfil,
                                });
                                setSimDetResult(res);
                              } catch (e) { alert(e instanceof Error ? e.message : "Erro na simulação"); }
                              finally { setSimDetLoading(false); }
                            }}
                          />
                          {!vinculoId && (
                            <p style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 8 }}>
                              Selecione um vínculo Item ↔ Produto na aba "Lances" antes de simular.
                            </p>
                          )}

                          {/* Resultados */}
                          {simDetResult && (
                            <div style={{ marginTop: 16 }}>
                              <div className="stat-cards-grid" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 16 }}>
                                <div className="stat-card stat-card-blue">
                                  <div className="stat-card-icon"><Target size={20} /></div>
                                  <div className="stat-card-content">
                                    <span className="stat-card-value">{String(simDetResult.posicao_final ?? "—")}</span>
                                    <span className="stat-card-label">Posição Final</span>
                                  </div>
                                </div>
                                <div className="stat-card stat-card-green">
                                  <div className="stat-card-icon"><DollarSign size={20} /></div>
                                  <div className="stat-card-content">
                                    <span className="stat-card-value">{fmt(Number(simDetResult.lance_final ?? 0))}</span>
                                    <span className="stat-card-label">Lance Final</span>
                                  </div>
                                </div>
                                <div className="stat-card stat-card-yellow">
                                  <div className="stat-card-icon"><TrendingUp size={20} /></div>
                                  <div className="stat-card-content">
                                    <span className="stat-card-value">{pct(Number(simDetResult.margem_final ?? 0))}</span>
                                    <span className="stat-card-label">Margem Final</span>
                                  </div>
                                </div>
                              </div>

                              {Array.isArray(simDetResult.rodadas) && (simDetResult.rodadas as Array<Record<string, unknown>>).length > 0 && (
                                <DataTable
                                  data={simDetResult.rodadas as Array<Record<string, unknown>>}
                                  columns={[
                                    { key: "rodada", header: "Rodada", width: "70px", render: (r) => String(r.rodada ?? "") },
                                    { key: "lance_empresa", header: "Nosso Lance", render: (r) => fmt(Number(r.lance_empresa ?? 0)) },
                                    { key: "lance_lider", header: "Líder", render: (r) => fmt(Number(r.lance_lider ?? 0)) },
                                    { key: "posicao", header: "Posição", width: "80px", render: (r) => String(r.posicao ?? "") },
                                    { key: "margem", header: "Margem", width: "80px", render: (r) => pct(Number(r.margem ?? 0)) },
                                  ] as Column<Record<string, unknown>>[]}
                                />
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </Card>

                    {/* ── UC-SC05: Simular DRE ── */}
                    <Card title="DRE Projetada (UC-SC05)" icon={<FileText size={18} />}>
                      <ActionButton
                        icon={<BarChart3 size={16} />}
                        label="Simular DRE"
                        variant="primary"
                        loading={dreLoading}
                        disabled={!editalId}
                        onClick={async () => {
                          if (!editalId) return;
                          setDreLoading(true);
                          setDreResult(null);
                          try {
                            const res = await simularDRE(editalId);
                            setDreResult(res);
                          } catch (e) { alert(e instanceof Error ? e.message : "Erro ao simular DRE"); }
                          finally { setDreLoading(false); }
                        }}
                      />
                      {dreResult && (
                        <div style={{ marginTop: 16 }}>
                          {/* Badge de atratividade */}
                          {dreResult.atratividade ? (() => {
                            const atrat = String(dreResult.atratividade);
                            const color = atrat === "verde" || atrat === "alta" ? "#22c55e"
                              : atrat === "amarelo" || atrat === "media" ? "#eab308" : "#ef4444";
                            const label = atrat === "verde" || atrat === "alta" ? "Atrativo"
                              : atrat === "amarelo" || atrat === "media" ? "Moderado" : "Não Atrativo";
                            return (
                              <span style={{
                                display: "inline-block", marginBottom: 12, fontSize: 12, padding: "4px 12px",
                                borderRadius: 6, fontWeight: 600, color: "#fff", background: color,
                              }}>
                                Atratividade: {label}
                              </span>
                            );
                          })() : null}

                          {/* Tabela DRE */}
                          {Array.isArray(dreResult.linhas) && (
                            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                              <thead>
                                <tr style={{ borderBottom: "2px solid var(--border)" }}>
                                  <th style={{ textAlign: "left", padding: "8px 12px" }}>Linha</th>
                                  <th style={{ textAlign: "right", padding: "8px 12px" }}>Valor (R$)</th>
                                  <th style={{ textAlign: "right", padding: "8px 12px" }}>% Receita</th>
                                </tr>
                              </thead>
                              <tbody>
                                {(dreResult.linhas as Array<Record<string, unknown>>).map((l, i) => {
                                  const isTotal = String(l.linha ?? "").toLowerCase().includes("resultado") || String(l.linha ?? "").toLowerCase().includes("lucro");
                                  return (
                                    <tr key={i} style={{ borderBottom: "1px solid var(--border)", fontWeight: isTotal ? 700 : 400 }}>
                                      <td style={{ padding: "6px 12px" }}>{String(l.linha ?? l.descricao ?? "")}</td>
                                      <td style={{ textAlign: "right", padding: "6px 12px" }}>{fmt(Number(l.valor ?? 0))}</td>
                                      <td style={{ textAlign: "right", padding: "6px 12px" }}>{l.pct_receita != null ? pct(Number(l.pct_receita)) : "—"}</td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          )}
                        </div>
                      )}
                    </Card>
                  </div>
                )}

                {/* ═══════════════════ TAB: HISTÓRICO (UC-P09 + UC-P10) ═══════════════════ */}
                {activeTab === "historico" && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                    {/* UC-P09: Histórico */}
                    <Card title="Consultar Histórico de Preços (UC-P09)" icon={<Search size={18} />}>
                      <div className="form-grid form-grid-3">
                        <FormField label="Produto/Termo">
                          <TextInput value={termoBusca} onChange={setTermoBusca} placeholder="reagente hematologia" />
                        </FormField>
                        <div className="form-field-actions" style={{ display: "flex", gap: 8 }}>
                          <ActionButton icon={<Search size={16} />} label="Filtrar" variant="primary" onClick={handleBuscarHistorico} loading={loading} />
                          <ActionButton icon={<Download size={16} />} label="CSV" onClick={handleExportCSV} />
                        </div>
                      </div>
                    </Card>

                    {histStats && (
                      <Card title="Estatísticas" icon={<TrendingUp size={18} />}>
                        <div style={{ display: "flex", gap: 24 }}>
                          <div><label style={{ fontSize: 12 }}>Preço Médio</label><br /><strong>{fmt(histStats.media)}</strong></div>
                          <div><label style={{ fontSize: 12 }}>Mínimo</label><br /><strong style={{ color: "green" }}>{fmt(histStats.min)}</strong></div>
                          <div><label style={{ fontSize: 12 }}>Máximo</label><br /><strong style={{ color: "red" }}>{fmt(histStats.max)}</strong></div>
                        </div>
                      </Card>
                    )}

                    {historico.length > 0 && (
                      <Card title="Resultados" icon={<History size={18} />}>
                        <DataTable data={historico} columns={historicoColumns} idKey="id" emptyMessage="Nenhum registro" />
                      </Card>
                    )}

                    {/* UC-P10: Comodato */}
                    <Card
                      title="Gestão de Comodato (UC-P10)"
                      icon={<Lightbulb size={18} />}
                      actions={
                        <span className="status-badge status-badge-warning" style={{ fontSize: 11 }}>
                          Processo manual — IA futura no roadmap
                        </span>
                      }
                    >
                      <div className="form-grid form-grid-3">
                        <FormField label="Equipamento">
                          <TextInput value={comodatoNome} onChange={setComodatoNome} placeholder="Analisador XYZ-3000" />
                        </FormField>
                        <FormField label="Valor do Equipamento (R$)">
                          <TextInput value={comodatoValor} onChange={setComodatoValor} placeholder="250000" />
                        </FormField>
                        <FormField label="Prazo (meses)">
                          <TextInput value={comodatoMeses} onChange={setComodatoMeses} placeholder="60" />
                        </FormField>
                      </div>
                      {comodatoValor && comodatoMeses && Number(comodatoMeses) > 0 && (
                        <p style={{ marginTop: 8, fontSize: 13 }}>
                          Amortização mensal: <strong>{fmt(Number(comodatoValor.replace(/\./g, "").replace(",", ".")) / Number(comodatoMeses))}</strong>
                        </p>
                      )}
                      <div style={{ marginTop: 12 }}>
                        <ActionButton icon={<Check size={16} />} label="Salvar Comodato" variant="primary" onClick={handleSalvarComodato} />
                      </div>

                      {comodatos.length > 0 && (
                        <div style={{ marginTop: 16 }}>
                          <h4>Comodatos Cadastrados</h4>
                          <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse", marginTop: 8 }}>
                            <thead>
                              <tr style={{ borderBottom: "1px solid var(--border)" }}>
                                <th style={{ textAlign: "left", padding: 4 }}>Equipamento</th>
                                <th style={{ textAlign: "right", padding: 4 }}>Valor</th>
                                <th style={{ textAlign: "right", padding: 4 }}>Meses</th>
                                <th style={{ textAlign: "right", padding: 4 }}>Amort./mês</th>
                                <th style={{ padding: 4 }}>Status</th>
                              </tr>
                            </thead>
                            <tbody>
                              {comodatos.map((c) => (
                                <tr key={c.id} style={{ borderBottom: "1px solid var(--border-light, #eee)" }}>
                                  <td style={{ padding: 4 }}>{c.nome_equipamento}</td>
                                  <td style={{ textAlign: "right", padding: 4 }}>{fmt(c.valor_equipamento)}</td>
                                  <td style={{ textAlign: "right", padding: 4 }}>{c.duracao_meses}</td>
                                  <td style={{ textAlign: "right", padding: 4 }}>{fmt(c.valor_mensal_amortizacao)}</td>
                                  <td style={{ padding: 4 }}><span className="status-badge">{c.status}</span></td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}

                      {/* Impacto no preço do lote */}
                      {comodatos.length > 0 && (() => {
                        const totalEquipamentos = comodatos.length;
                        const valorTotalEquipamentos = comodatos.reduce((acc, c) => acc + (c.valor_equipamento || 0), 0);
                        const amortizacaoMensalTotal = comodatos.reduce((acc, c) => acc + (c.valor_mensal_amortizacao || 0), 0);
                        const totalItensEdital = itensEdital.reduce((acc, item) => acc + (item.quantidade || 0), 0);
                        const impactoPorItem = totalItensEdital > 0 ? amortizacaoMensalTotal / totalItensEdital : 0;

                        return (
                          <div style={{
                            marginTop: 16, padding: 16, borderRadius: 8,
                            background: "var(--bg-primary-light, #eff6ff)",
                            border: "1px solid var(--color-primary, #3b82f6)",
                          }}>
                            <h4 style={{ margin: "0 0 12px", fontSize: 14, color: "var(--color-primary, #3b82f6)" }}>
                              📦 Impacto do Comodato no Preço
                            </h4>
                            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 16, fontSize: 13 }}>
                              <div>
                                <label style={{ fontSize: 11, color: "var(--text-secondary)" }}>Total equipamentos</label>
                                <br /><strong>{totalEquipamentos}</strong>
                              </div>
                              <div>
                                <label style={{ fontSize: 11, color: "var(--text-secondary)" }}>Valor total equipamentos</label>
                                <br /><strong>{fmt(valorTotalEquipamentos)}</strong>
                              </div>
                              <div>
                                <label style={{ fontSize: 11, color: "var(--text-secondary)" }}>Amortização mensal total</label>
                                <br /><strong>{fmt(amortizacaoMensalTotal)}</strong>
                              </div>
                              <div>
                                <label style={{ fontSize: 11, color: "var(--text-secondary)" }}>Impacto por item do lote</label>
                                <br />
                                <strong style={{ color: totalItensEdital > 0 ? "var(--color-danger, #ef4444)" : "var(--text-secondary)" }}>
                                  {totalItensEdital > 0
                                    ? `+ ${fmt(impactoPorItem)} /item`
                                    : "Sem itens vinculados"}
                                </strong>
                              </div>
                            </div>
                            {totalItensEdital > 0 && (
                              <p style={{ marginTop: 8, fontSize: 12, color: "var(--text-secondary)" }}>
                                Cálculo: {fmt(amortizacaoMensalTotal)} (amortização mensal) ÷ {totalItensEdital} itens = {fmt(impactoPorItem)} por item
                              </p>
                            )}
                          </div>
                        );
                      })()}
                    </Card>
                  </div>
                )}
              </>
            )}
          </TabPanel>
        )}

        {/* Seleção de Portfolio Modal */}
        <Modal isOpen={showSelecaoModal} title="Seleção de Portfolio" onClose={() => setShowSelecaoModal(false)} size="large">
            <p style={{ marginBottom: 12 }}>Selecione o produto do portfolio para vincular ao item:</p>
            <table style={{ width: "100%", fontSize: 13, borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)" }}>
                  <th style={{ textAlign: "left", padding: 6 }}>Produto</th>
                  <th style={{ textAlign: "left", padding: 6 }}>Fabricante</th>
                  <th style={{ padding: 6 }}>Ação</th>
                </tr>
              </thead>
              <tbody>
                {sugestoes.map((s) => (
                  <tr key={s.produto_id} style={{ borderBottom: "1px solid var(--border-light, #eee)" }}>
                    <td style={{ padding: 6 }}>{s.nome}</td>
                    <td style={{ padding: 6 }}>{s.fabricante || "—"}</td>
                    <td style={{ padding: 6, textAlign: "center" }}>
                      <ActionButton
                        label="Selecionar"
                        variant="primary"
                        onClick={() => handleConfirmarSelecao(s.produto_id)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Modal>

          {/* === MODAL BUSCAR NA WEB === */}
          <Modal
            isOpen={showBuscaWebModal}
            onClose={() => { setShowBuscaWebModal(false); setBuscaNomeProduto(""); setBuscaFabricante(""); }}
            title="Buscar Produto na Web"
            footer={
              <>
                <button className="btn btn-secondary" onClick={() => setShowBuscaWebModal(false)}>Cancelar</button>
                <button className="btn btn-primary" onClick={handleBuscaWebConfirm} disabled={!buscaNomeProduto}>
                  <Globe size={14} /> Buscar via IA
                </button>
              </>
            }
          >
            <p style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 12 }}>
              A IA busca informações do produto na web e cadastra automaticamente no portfólio.
            </p>
            <FormField label="Nome do Produto" required>
              <TextInput value={buscaNomeProduto} onChange={setBuscaNomeProduto} placeholder="Ex: Reagente Hematologia XN-L" />
            </FormField>
            <FormField label="Fabricante (opcional)">
              <TextInput value={buscaFabricante} onChange={setBuscaFabricante} placeholder="Ex: Sysmex" />
            </FormField>
          </Modal>

          {/* === MODAL ANVISA === */}
          <Modal
            isOpen={showAnvisaModal}
            onClose={() => { setShowAnvisaModal(false); setAnvisaRegistro(""); setAnvisaNomeProduto(""); }}
            title="Registros de Produtos pela ANVISA"
            footer={
              <>
                <button className="btn btn-secondary" onClick={() => setShowAnvisaModal(false)}>Cancelar</button>
                <button className="btn btn-primary" onClick={handleAnvisaConfirm} disabled={!anvisaRegistro && !anvisaNomeProduto}>
                  <Shield size={14} /> Buscar via IA
                </button>
              </>
            }
          >
            <p style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 12 }}>
              A IA tenta trazer os registros e o usuário valida ou complementa.
            </p>
            <FormField label="Número de Registro ANVISA">
              <TextInput value={anvisaRegistro} onChange={setAnvisaRegistro} placeholder="Ex: 80000000001" />
            </FormField>
            <FormField label="ou Nome do Produto">
              <TextInput value={anvisaNomeProduto} onChange={setAnvisaNomeProduto} placeholder="Ex: Reagente Teste Rápido" />
            </FormField>
          </Modal>
      </div>
    </div>
  );
}
