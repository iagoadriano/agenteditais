import { useState, useEffect, useCallback, useRef } from "react";
import {
  Briefcase, Globe, Search, RefreshCw, Trash2, Eye, Shield,
  Sparkles, Radio, AlertCircle, Loader2, FileText,
  ClipboardList, FolderOpen, ChevronDown, ChevronRight,
  Filter, Zap, ArrowDown, CheckCircle, DollarSign, AlertTriangle,
  Edit2, Save, X, Layers, Check, SquareCheck as SquareCheckIcon
} from "lucide-react";
import { Card, DataTable, ActionButton, FilterBar, Modal, FormField, TextInput, SelectInput, StatusBadge, UploadLoteIA } from "../components/common";
import type { Column } from "../components/common";
import { getProdutos, getProduto, getProdutoCompletude, getProdutosCompletudeBatch, buscarWebEstruturado, reprocessarMetadados, sendMessage, sendMessageWithFile, createSession } from "../api/client";
import type { Produto, ProdutoEspecificacao, CompletudeResult, BuscaWebResposta } from "../api/client";
import { crudList, crudCreate, crudUpdate, crudDelete } from "../api/crud";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface PortfolioPageProps {
  onSendToChat: (message: string, file?: File) => Promise<void>;
}

// Tipos de upload para cadastro por IA
const UPLOAD_TYPES = [
  { id: "manual", label: "Manual Tecnico", accept: ".pdf,.doc,.docx", prompt: "Cadastre este produto a partir do manual" },
  { id: "instrucoes", label: "Instrucoes de Uso / IFU", accept: ".pdf,.doc,.docx", prompt: "Cadastre este produto a partir das instrucoes de uso" },
  { id: "nfs", label: "Nota Fiscal (NFS)", accept: ".pdf,.xlsx,.xls,.csv", prompt: "Importe TODOS os produtos/itens desta nota fiscal. Extraia cada item listado e cadastre cada um individualmente" },
  { id: "plano_contas", label: "Plano de Contas (ERP)", accept: ".pdf,.xlsx,.xls,.csv", prompt: "Importe TODOS os produtos deste plano de contas. Liste e cadastre cada item individualmente" },
  { id: "folders", label: "Folder / Catalogo", accept: ".pdf,.doc,.docx", prompt: "Cadastre este produto a partir do folder" },
  { id: "website", label: "Website do Fabricante", accept: "", prompt: "Busque produtos no website" },
];

interface SpecCampoTop {
  campo: string;
  tipo: "texto" | "numero" | "decimal" | "select" | "boolean";
  unidade?: string;
  placeholder?: string;
  opcoes?: string[];
  obrigatorio?: boolean;
}

interface MascaraResultado {
  produto_id: string;
  descricao_original: string;
  descricao_normalizada: string;
  score_original?: number;
  score_normalizado?: number;
  variantes?: string[];
  sinonimos?: string[];
}

function parseMascaraTop(raw: unknown): SpecCampoTop[] {
  try {
    let mascara = typeof raw === "string" ? JSON.parse(raw) : raw;
    if (typeof mascara === "string") mascara = JSON.parse(mascara);
    if (!Array.isArray(mascara) || mascara.length === 0) return [];
    return mascara.map((m: Record<string, unknown>) => ({
      campo: String(m.campo || m.nome || ""),
      tipo: (m.tipo as SpecCampoTop["tipo"]) || "texto",
      unidade: m.unidade ? String(m.unidade) : undefined,
      placeholder: m.placeholder ? String(m.placeholder) : undefined,
      opcoes: Array.isArray(m.opcoes) ? m.opcoes.map(String) : undefined,
      obrigatorio: Boolean(m.obrigatorio),
    }));
  } catch { return []; }
}

export function PortfolioPage({ onSendToChat }: PortfolioPageProps) {
  // Aba ativa
  const [activeTab, setActiveTab] = useState<"produtos" | "cadastroIA" | "classificacao">("produtos");

  // === PRODUTOS (tabela) ===
  const [produtos, setProdutos] = useState<Produto[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState("");
  const [categoriaFilter] = useState("todas");
  const [filtroArea, setFiltroArea] = useState("");
  const [filtroClasse, setFiltroClasse] = useState("");
  const [filtroSubclasse, setFiltroSubclasse] = useState("");
  const [selectedProduto, setSelectedProduto] = useState<Produto | null>(null);
  const [selectedProdutoFull, setSelectedProdutoFull] = useState<Produto | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [reprocessandoMeta, setReprocessandoMeta] = useState(false);
  const [showMetadados, setShowMetadados] = useState(false);
  // UC-F12 V8 — edicao manual de metadados de captacao
  const [editingMetadados, setEditingMetadados] = useState(false);
  const [editCatmat, setEditCatmat] = useState<string>("");
  const [editCatser, setEditCatser] = useState<string>("");
  const [editTermos, setEditTermos] = useState<string>("");
  const [savingMetadados, setSavingMetadados] = useState(false);
  const [metadadosMsg, setMetadadosMsg] = useState<string | null>(null);
  // obs 12 validador V8 — adicionar especificacao manual ao produto cadastrado
  const [novaSpecNome, setNovaSpecNome] = useState("");
  const [novaSpecValor, setNovaSpecValor] = useState("");
  const [novaSpecUnidade, setNovaSpecUnidade] = useState("");
  const [salvandoSpec, setSalvandoSpec] = useState(false);
  const [specMsg, setSpecMsg] = useState<string | null>(null);
  const detalheRef = useRef<HTMLDivElement>(null);

  // === CADASTRO POR IA (upload) ===
  const [tipoDocumento, setTipoDocumento] = useState("manual");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadNomeProduto, setUploadNomeProduto] = useState("");
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [uploadArea, setUploadArea] = useState("");
  const [uploadClasse, setUploadClasse] = useState("");
  const [uploadSubclasse, setUploadSubclasse] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  // === CLASSIFICACAO ===
  const [expandedArea, setExpandedArea] = useState<string | null>(null);
  const [expandedClasse, setExpandedClasse] = useState<string | null>(null);

  // === HIERARQUIA DO BACKEND (Area → Classe → Subclasse) ===
  const [areasBackend, setAreasBackend] = useState<Record<string, unknown>[]>([]);
  const [classesV2Backend, setClassesV2Backend] = useState<Record<string, unknown>[]>([]);
  const [subclassesBackend, setSubclassesBackend] = useState<Record<string, unknown>[]>([]);

  // === MONITORAMENTOS ===
  const [monitoramentos, setMonitoramentos] = useState<Record<string, unknown>[]>([]);
  const [monitoramentosLoading, setMonitoramentosLoading] = useState(false);

  // === COMPLETUDE ===
  const [completudeResult, setCompletudeResult] = useState<CompletudeResult | null>(null);
  const [completudeLoading, setCompletudeLoading] = useState(false);

  // === FEEDBACK DE PROCESSAMENTO ===
  const [processingMessage, setProcessingMessage] = useState<string | null>(null);
  const [iaResponse, setIaResponse] = useState<string | null>(null);

  // === EDIÇÃO DE PRODUTO ===
  const [editProduto, setEditProduto] = useState<Produto | null>(null);
  const [editForm, setEditForm] = useState<Record<string, string>>({});
  const [editSaving, setEditSaving] = useState(false);
  const [editArea, setEditArea] = useState("");
  const [editClasse, setEditClasse] = useState("");
  const [editSubclasse, setEditSubclasse] = useState("");
  const [editSpecs, setEditSpecs] = useState<Record<string, { id?: string; valor: string; unidade?: string }>>({});
  const [editLoading, setEditLoading] = useState(false);

  // === MODALS ===
  const [showAnvisaModal, setShowAnvisaModal] = useState(false);
  const [showBuscaWebModal, setShowBuscaWebModal] = useState(false);
  const [anvisaRegistro, setAnvisaRegistro] = useState("");
  const [anvisaNomeProduto, setAnvisaNomeProduto] = useState("");
  const [buscaNomeProduto, setBuscaNomeProduto] = useState("");
  const [buscaFabricante, setBuscaFabricante] = useState("");
  // obs 13 validador V8: resultados estruturados da busca web p/ o usuario escolher
  const [buscaWebLoading, setBuscaWebLoading] = useState(false);
  const [buscaWebResultados, setBuscaWebResultados] = useState<BuscaWebResposta | null>(null);
  const [buscaWebSelecionados, setBuscaWebSelecionados] = useState<Set<string>>(new Set());

  // === SELECAO MULTIPLA & CLASSIFICACAO EM LOTE ===
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showClassificarModal, setShowClassificarModal] = useState(false);
  const [classifArea, setClassifArea] = useState("");
  const [classifClasse, setClassifClasse] = useState("");
  const [classifSubclasse, setClassifSubclasse] = useState("");
  const [classifSaving, setClassifSaving] = useState(false);

  // === MASCARA MODAL (resultado por produto) ===
  const [showMascaraModal, setShowMascaraModal] = useState(false);
  const [mascaraResultado, setMascaraResultado] = useState<MascaraResultado | null>(null);
  const [mascaraLoading, setMascaraLoading] = useState(false);
  const [mascaraLoteLoading, setMascaraLoteLoading] = useState(false);
  const [filtroSemClasse, setFiltroSemClasse] = useState(false);
  // obs 15/16 validador V8: farol + filtro de completude na grade
  const [completudeMap, setCompletudeMap] = useState<Record<string, number>>({});
  const [filtroCompletude, setFiltroCompletude] = useState(""); // "", "verde", "amarelo", "vermelho"

  // Carregar produtos reais do backend
  const fetchProdutos = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const categoria = categoriaFilter !== "todas" ? categoriaFilter : undefined;
      const data = await getProdutos(categoria);
      setProdutos(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar produtos");
    } finally {
      setLoading(false);
    }
  }, [categoriaFilter]);

  useEffect(() => {
    fetchProdutos();
  }, [fetchProdutos]);

  // obs 15/16: carrega completude de todos os produtos (farol na grade)
  const carregarCompletude = useCallback(async () => {
    try {
      setCompletudeMap(await getProdutosCompletudeBatch());
    } catch {
      /* silencioso: grade funciona sem farol se endpoint falhar */
    }
  }, []);
  useEffect(() => {
    if (produtos.length > 0) carregarCompletude();
  }, [produtos.length, carregarCompletude]);

  // Carregar hierarquia Area → Classe → Subclasse do backend
  useEffect(() => {
    (async () => {
      try {
        const [areasRes, classesRes, subsRes] = await Promise.all([
          crudList("areas-produto", { limit: 100 }),
          crudList("classes-produto-v2", { limit: 200 }),
          crudList("subclasses-produto", { limit: 500 }),
        ]);
        setAreasBackend(areasRes.items || []);
        setClassesV2Backend(classesRes.items || []);
        setSubclassesBackend(subsRes.items || []);
      } catch (e) {
        console.error("[Portfolio] Erro ao carregar hierarquia:", e);
      }
    })();
    // Carregar monitoramentos
    (async () => {
      setMonitoramentosLoading(true);
      try {
        const res = await crudList("monitoramentos", { limit: 10 });
        setMonitoramentos(res.items || []);
      } catch {
        // silencioso
      } finally {
        setMonitoramentosLoading(false);
      }
    })();
  }, []);

  // Carregar detalhes completos ao selecionar produto
  const handleSelectProduto = useCallback(async (produto: Produto) => {
    setSelectedProduto(produto);
    setLoadingDetail(true);
    try {
      const full = await getProduto(produto.id);
      setSelectedProdutoFull(full);
    } catch {
      setSelectedProdutoFull(produto);
    } finally {
      setLoadingDetail(false);
      setTimeout(() => detalheRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 100);
    }
  }, []);

  // Mapas para filtro hierárquico
  const subclasseToClasseMap = Object.fromEntries(subclassesBackend.map(s => [String(s.id), String(s.classe_id || "")]));
  const classeToAreaMap = Object.fromEntries(classesV2Backend.map(c => [String(c.id), String(c.area_id || "")]));
  // Mapas id → nome para busca textual em subclasse/classe/área
  const subclasseNomeMap = Object.fromEntries(subclassesBackend.map(s => [String(s.id), String(s.nome || "").toLowerCase()]));
  const classeNomeMap = Object.fromEntries(classesV2Backend.map(c => [String(c.id), String(c.nome || "").toLowerCase()]));
  const areaNomeMap = Object.fromEntries(areasBackend.map(a => [String(a.id), String(a.nome || "").toLowerCase()]));

  const filteredProdutos = produtos.filter((p) => {
    // Filtro por texto
    if (searchTerm) {
      // Normaliza acento+caixa: "cirurgico" casa "Cirúrgico" (obs 2 validador V8)
      const norm = (s: string) => (s || "").toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g, "");
      const term = norm(searchTerm);
      const classeIdDoProduto = p.subclasse_id ? subclasseToClasseMap[p.subclasse_id] : "";
      const areaIdDoProduto = classeIdDoProduto ? classeToAreaMap[classeIdDoProduto] : "";
      const subclasseNome = p.subclasse_id ? (subclasseNomeMap[p.subclasse_id] || "") : "";
      const classeNome = classeIdDoProduto ? (classeNomeMap[classeIdDoProduto] || "") : "";
      const areaNome = areaIdDoProduto ? (areaNomeMap[areaIdDoProduto] || "") : "";
      const match = norm(p.nome).includes(term) ||
        norm(p.fabricante || "").includes(term) ||
        norm(p.modelo || "").includes(term) ||
        norm(p.descricao || "").includes(term) ||
        norm(subclasseNome).includes(term) ||
        norm(classeNome).includes(term) ||
        norm(areaNome).includes(term);
      if (!match) return false;
    }
    // Filtro "Sem Classe"
    if (filtroSemClasse && p.subclasse_id) return false;
    // obs 16: filtro por faixa de completude
    if (filtroCompletude) {
      const pct = completudeMap[p.id];
      if (pct == null) return false;
      const faixa = pct >= 90 ? "verde" : pct >= 50 ? "amarelo" : "vermelho";
      if (faixa !== filtroCompletude) return false;
    }
    // Filtro por subclasse
    if (filtroSubclasse && p.subclasse_id !== filtroSubclasse) return false;
    // Filtro por classe (via subclasse do produto)
    if (filtroClasse && !filtroSubclasse) {
      const classeId = p.subclasse_id ? subclasseToClasseMap[p.subclasse_id] : "";
      if (classeId !== filtroClasse) return false;
    }
    // Filtro por área (via classe da subclasse do produto)
    if (filtroArea && !filtroClasse && !filtroSubclasse) {
      const classeId = p.subclasse_id ? subclasseToClasseMap[p.subclasse_id] : "";
      const areaId = classeId ? classeToAreaMap[classeId] : "";
      if (areaId !== filtroArea) return false;
    }
    return true;
  });

  // ============================================================
  // HANDLERS - CADASTRO POR IA (upload)
  // ============================================================

  const handleUploadFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setUploadFile(e.target.files?.[0] || null);
  };

  const handleUploadConfirm = async () => {
    console.log("[CadastroIA] Iniciando upload. tipo:", tipoDocumento, "arquivo:", uploadFile?.name, "subclasse:", uploadSubclasse);
    setProcessingMessage("Processando via IA...");
    setIaResponse(null);

    try {
      const session = await createSession("cadastro-produto");
      console.log("[CadastroIA] Sessao criada:", session.session_id);

      if (tipoDocumento === "website") {
        if (!websiteUrl) { setProcessingMessage(null); return; }
        const resp = await sendMessage(session.session_id, `Busque produtos no website ${websiteUrl} e cadastre`);
        setProcessingMessage(null);
        setIaResponse(resp.response || "Processado pela IA.");
        setWebsiteUrl("");
        fetchProdutos();
        return;
      }

      if (!uploadFile) { setProcessingMessage(null); return; }
      const typeConfig = UPLOAD_TYPES.find(t => t.id === tipoDocumento);
      const prompt = typeConfig?.prompt || "Cadastre este produto";
      const msg = uploadNomeProduto ? `${prompt}: ${uploadNomeProduto}` : prompt;
      console.log("[CadastroIA] Enviando arquivo. msg:", msg);
      const resp = await sendMessageWithFile(session.session_id, msg, uploadFile, uploadSubclasse || undefined);
      console.log("[CadastroIA] Resposta recebida:", resp);
      setProcessingMessage(null);
      setIaResponse(resp.response || "Produto processado pela IA.");
      setUploadFile(null);
      setUploadNomeProduto("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      fetchProdutos();
    } catch (err) {
      console.error("[CadastroIA] Erro:", err);
      setProcessingMessage(null);
      setIaResponse(`Erro: ${err instanceof Error ? err.message : "Falha ao processar"}`);
    }
  };

  // Cascata para upload: Área → Classe → Subclasse (opcional, melhora extração)
  const handleUploadAreaChange = (areaId: string) => {
    setUploadArea(areaId);
    setUploadClasse("");
    setUploadSubclasse("");
  };

  const handleUploadClasseChange = (classeId: string) => {
    setUploadClasse(classeId);
    setUploadSubclasse("");
  };

  // ============================================================
  // HANDLERS - ACOES NA TABELA (via chat)
  // ============================================================

  const handleReprocessar = async (produto: Produto) => {
    await onSendToChat(`Reprocesse as especificacoes do produto ${produto.nome}`);
    setTimeout(() => fetchProdutos(), 3000);
  };

  const handleReprocessarMetadados = async (produtoId: string) => {
    setReprocessandoMeta(true);
    try {
      await reprocessarMetadados(produtoId);
      // Reload product detail
      const updated = await getProduto(produtoId);
      setSelectedProdutoFull(updated);
    } catch (err: unknown) {
      console.error("Erro ao reprocessar metadados:", err);
    } finally {
      setReprocessandoMeta(false);
    }
  };

  // UC-F12 V8 — abre modo de edicao copiando valores atuais para os inputs
  const handleAbrirEdicaoMetadados = () => {
    const d = selectedProdutoFull;
    if (!d) return;
    setEditCatmat((d.catmat_codigos || []).join(", "));
    setEditCatser((d.catser_codigos || []).join(", "));
    setEditTermos((d.termos_busca || []).join(", "));
    setMetadadosMsg(null);
    setEditingMetadados(true);
  };

  const handleCancelarEdicaoMetadados = () => {
    setEditingMetadados(false);
    setMetadadosMsg(null);
  };

  // UC-F12 V8 — salva metadados manualmente via PUT /api/crud/produtos/<id>
  const handleSalvarMetadados = async (produtoId: string) => {
    setSavingMetadados(true);
    setMetadadosMsg(null);
    try {
      const splitCsv = (s: string) => s.split(",").map(t => t.trim()).filter(t => t.length > 0);
      const payload = {
        catmat_codigos: splitCsv(editCatmat),
        catser_codigos: splitCsv(editCatser),
        termos_busca: splitCsv(editTermos),
      };
      await crudUpdate("produtos", produtoId, payload);
      const updated = await getProduto(produtoId);
      setSelectedProdutoFull(updated);
      setEditingMetadados(false);
      setMetadadosMsg("✓ Metadados salvos com sucesso");
      setTimeout(() => setMetadadosMsg(null), 3000);
    } catch (err: unknown) {
      console.error("Erro ao salvar metadados:", err);
      setMetadadosMsg(`✗ Erro: ${err instanceof Error ? err.message : "Falha ao salvar"}`);
    } finally {
      setSavingMetadados(false);
    }
  };

  // obs 12 validador V8 — cria especificacao manual no produto ja cadastrado
  const handleAdicionarSpec = async (produtoId: string) => {
    const nome = novaSpecNome.trim();
    const valor = novaSpecValor.trim();
    if (!nome || !valor) {
      setSpecMsg("✗ Informe nome e valor da especificacao");
      return;
    }
    setSalvandoSpec(true);
    setSpecMsg(null);
    try {
      await crudCreate("produtos-especificacoes", {
        produto_id: produtoId,
        nome_especificacao: nome,
        valor,
        unidade: novaSpecUnidade.trim() || null,
      });
      const updated = await getProduto(produtoId);
      setSelectedProdutoFull(updated);
      setNovaSpecNome(""); setNovaSpecValor(""); setNovaSpecUnidade("");
      setSpecMsg("✓ Especificacao adicionada");
      setTimeout(() => setSpecMsg(null), 3000);
    } catch (err: unknown) {
      console.error("Erro ao adicionar especificacao:", err);
      setSpecMsg(`✗ Erro: ${err instanceof Error ? err.message : "Falha ao adicionar"}`);
    } finally {
      setSalvandoSpec(false);
    }
  };

  const handleExcluir = async (produto: Produto) => {
    if (!confirm(`Tem certeza que deseja excluir "${produto.nome}"?`)) return;
    try {
      await crudDelete("produtos", produto.id);
      setSelectedProduto(null);
      setSelectedProdutoFull(null);
      setEditProduto(null);
      fetchProdutos();
    } catch (err) {
      setError(`Erro ao excluir: ${err instanceof Error ? err.message : "Falha"}`);
    }
  };

  const handleVerificarCompletude = async (produto: Produto) => {
    setCompletudeLoading(true);
    try {
      const result = await getProdutoCompletude(produto.id);
      setCompletudeResult(result);
    } catch (err) {
      setError(`Erro ao verificar completude: ${err instanceof Error ? err.message : "Falha"}`);
    } finally {
      setCompletudeLoading(false);
    }
  };

  const handleEditarAbrir = async (produto: Produto) => {
    console.log("[EDITAR] Abrindo produto:", produto.id, produto.nome, "subclasse_id:", produto.subclasse_id);
    setEditProduto(produto);
    setEditForm({
      nome: produto.nome || "",
      fabricante: produto.fabricante || "",
      modelo: produto.modelo || "",
      codigo_interno: produto.codigo_interno || "",
      ncm: produto.ncm || "",
      descricao: produto.descricao || "",
      categoria: produto.categoria || "",
    });

    // Resolver hierarquia: subclasse → classe → área
    const subId = produto.subclasse_id || "";
    setEditSubclasse(subId);
    if (subId) {
      const sub = subclassesBackend.find(s => String(s.id) === subId);
      const clsId = sub ? String(sub.classe_id || "") : "";
      setEditClasse(clsId);
      if (clsId) {
        const cls = classesV2Backend.find(c => String(c.id) === clsId);
        setEditArea(cls ? String(cls.area_id || "") : "");
      } else {
        setEditArea("");
      }
    } else {
      setEditClasse("");
      setEditArea("");
    }

    // Carregar especificações existentes
    setEditLoading(true);
    try {
      const full = await getProduto(produto.id);
      const specsMap: Record<string, { id?: string; valor: string; unidade?: string }> = {};
      if (full.especificacoes) {
        for (const spec of full.especificacoes) {
          specsMap[spec.nome_especificacao] = {
            id: spec.id,
            valor: spec.valor || "",
            unidade: spec.unidade || "",
          };
        }
      }
      setEditSpecs(specsMap);
    } catch {
      setEditSpecs({});
    } finally {
      setEditLoading(false);
    }
  };

  // Máscara da subclasse selecionada na edição
  const editMascara = (() => {
    if (!editSubclasse) return [];
    const sub = subclassesBackend.find(s => String(s.id) === editSubclasse);
    if (!sub || !sub.campos_mascara) return [];
    return parseMascaraTop(sub.campos_mascara);
  })();

  const handleEditarSalvar = async () => {
    if (!editProduto) return;
    setEditSaving(true);
    try {
      // Salvar dados básicos do produto
      await crudUpdate("produtos", editProduto.id, {
        ...editForm,
        subclasse_id: editSubclasse || null,
      });

      // Salvar especificações: update existentes, create novas
      for (const campo of editMascara) {
        const specData = editSpecs[campo.campo];
        const valor = specData?.valor?.trim() || "";
        if (!valor) continue;
        if (specData?.id) {
          // Update existente
          await crudUpdate("produtos-especificacoes", specData.id, {
            valor,
            unidade: campo.unidade || specData.unidade || "",
          });
        } else {
          // Criar nova
          await crudCreate("produtos-especificacoes", {
            produto_id: editProduto.id,
            nome_especificacao: campo.campo,
            valor,
            unidade: campo.unidade || "",
          });
        }
      }

      setEditProduto(null);
      fetchProdutos();
    } catch (err) {
      setError(`Erro ao salvar: ${err instanceof Error ? err.message : "Falha"}`);
    } finally {
      setEditSaving(false);
    }
  };

  // ANVISA — chama API direto e mostra resposta inline
  const handleAnvisaConfirm = async () => {
    let msg = "";
    if (anvisaRegistro) msg = `Busque o registro ANVISA numero ${anvisaRegistro}`;
    else if (anvisaNomeProduto) msg = `Busque registros ANVISA para o produto ${anvisaNomeProduto}`;
    else return;
    setShowAnvisaModal(false);
    setProcessingMessage("Buscando registros ANVISA...");
    setIaResponse(null);
    try {
      const session = await createSession("busca-anvisa");
      const resp = await sendMessage(session.session_id, msg);
      setProcessingMessage(null);
      setIaResponse(resp.response || "Busca ANVISA concluida.");
      setAnvisaRegistro("");
      setAnvisaNomeProduto("");
      fetchProdutos();
    } catch (err) {
      console.error("[ANVISA] Erro:", err);
      setProcessingMessage(null);
      setIaResponse(`Erro: ${err instanceof Error ? err.message : "Falha na busca ANVISA"}`);
    }
  };

  // Busca Web — chama API direto e mostra resposta inline
  // obs 13 validador V8: busca estruturada, mostra resultados p/ o usuario
  // escolher — NAO cadastra automaticamente.
  const handleBuscaWebConfirm = async () => {
    if (!buscaNomeProduto) return;
    setBuscaWebLoading(true);
    setBuscaWebResultados(null);
    setBuscaWebSelecionados(new Set());
    try {
      const r = await buscarWebEstruturado(buscaNomeProduto, buscaFabricante);
      setBuscaWebResultados(r);
    } catch (err) {
      console.error("[BuscaWeb] Erro:", err);
      setBuscaWebResultados({ termo: buscaNomeProduto, pdfs: [], outros: [], total: 0 });
      setIaResponse(`Erro: ${err instanceof Error ? err.message : "Falha na busca web"}`);
    } finally {
      setBuscaWebLoading(false);
    }
  };

  const toggleBuscaWebItem = (link: string) => {
    setBuscaWebSelecionados(prev => {
      const n = new Set(prev);
      if (n.has(link)) n.delete(link); else n.add(link);
      return n;
    });
  };

  // Incorpora SOMENTE os itens marcados pelo usuario (envia URLs ao chat
  // para download+cadastro — acao explicita, nao automatica).
  const handleIncorporarSelecionados = async () => {
    const urls = Array.from(buscaWebSelecionados);
    if (urls.length === 0) return;
    setShowBuscaWebModal(false);
    setBuscaWebResultados(null);
    setProcessingMessage(`Incorporando ${urls.length} documento(s) selecionado(s)...`);
    setIaResponse(null);
    try {
      const session = await createSession("busca-web");
      for (const url of urls) {
        await sendMessage(session.session_id, `Baixe o arquivo da URL: ${url} e cadastre o produto`);
      }
      setProcessingMessage(null);
      setIaResponse(`✓ ${urls.length} documento(s) processado(s). Verifique os produtos na grade.`);
      setBuscaNomeProduto("");
      setBuscaFabricante("");
      setBuscaWebSelecionados(new Set());
      fetchProdutos();
    } catch (err) {
      console.error("[BuscaWeb] Erro incorporar:", err);
      setProcessingMessage(null);
      setIaResponse(`Erro: ${err instanceof Error ? err.message : "Falha ao incorporar"}`);
    }
  };

  // Parse campos_mascara JSON (used by classificacao tab and edit modal)
  const parseMascara = (raw: unknown): SpecCampoTop[] => {
    try {
      let mascara = typeof raw === "string" ? JSON.parse(raw) : raw;
      if (typeof mascara === "string") mascara = JSON.parse(mascara);
      if (!Array.isArray(mascara) || mascara.length === 0) return [];
      return mascara.map((m: Record<string, unknown>) => ({
        campo: String(m.campo || m.nome || ""),
        tipo: (m.tipo as SpecCampoTop["tipo"]) || "texto",
        unidade: m.unidade ? String(m.unidade) : undefined,
        placeholder: m.placeholder ? String(m.placeholder) : undefined,
        opcoes: Array.isArray(m.opcoes) ? m.opcoes.map(String) : undefined,
        obrigatorio: Boolean(m.obrigatorio),
      }));
    } catch { return []; }
  };

  // Pipeline status badge colors
  const pipelineStatusConfig: Record<string, { color: string; bg: string; label: string }> = {
    cadastrado:  { color: "#6b7280", bg: "rgba(107,114,128,0.12)", label: "Cadastrado" },
    qualificado: { color: "#3b82f6", bg: "rgba(59,130,246,0.12)", label: "Qualificado" },
    ofertado:    { color: "#f59e0b", bg: "rgba(245,158,11,0.12)", label: "Ofertado" },
    vencedor:    { color: "#22c55e", bg: "rgba(34,197,94,0.12)", label: "Vencedor" },
  };

  // Pipeline counters
  const pipelineCounts = {
    cadastrado:  filteredProdutos.filter(p => !p.status_pipeline || p.status_pipeline === "cadastrado").length,
    qualificado: filteredProdutos.filter(p => p.status_pipeline === "qualificado").length,
    ofertado:    filteredProdutos.filter(p => p.status_pipeline === "ofertado").length,
    vencedor:    filteredProdutos.filter(p => p.status_pipeline === "vencedor").length,
  };

  // NCM alert: products without NCM
  const produtosSemNcm = filteredProdutos.filter(p => !p.ncm || p.ncm.trim() === "");

  // Mapa de subclasses para exibir nome na tabela
  const subclasseMap = Object.fromEntries(subclassesBackend.map(s => [String(s.id), String(s.nome || "")]));

  const getSubclasseNome = (p: Produto): string => {
    if (p.subclasse_id && subclasseMap[p.subclasse_id]) return subclasseMap[p.subclasse_id];
    return p.categoria || "-";
  };

  // Mapa classe_id → nome para coluna Classe
  const classeMap = Object.fromEntries(classesV2Backend.map(c => [String(c.id), String(c.nome || "")]));

  const getClasseNome = (p: Produto): string => {
    if (!p.subclasse_id) return "-";
    const classeId = subclasseToClasseMap[p.subclasse_id];
    if (classeId && classeMap[classeId]) return classeMap[classeId];
    return "-";
  };

  // === SELECAO MULTIPLA handlers ===
  const toggleSelectProduto = (id: string) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === filteredProdutos.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(filteredProdutos.map(p => p.id)));
    }
  };

  // === CLASSIFICAR SELECIONADOS handler ===
  const handleClassificarSelecionados = async () => {
    if (!classifSubclasse || selectedIds.size === 0) return;
    setClassifSaving(true);
    try {
      const token = localStorage.getItem("token");
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = "Bearer " + token;
      for (const prodId of selectedIds) {
        await fetch(`/api/crud/produtos/${prodId}`, {
          method: "PUT",
          headers,
          body: JSON.stringify({ subclasse_id: classifSubclasse }),
        });
      }
      setShowClassificarModal(false);
      setSelectedIds(new Set());
      setClassifArea("");
      setClassifClasse("");
      setClassifSubclasse("");
      fetchProdutos();
    } catch (err) {
      setError(`Erro ao classificar: ${err instanceof Error ? err.message : "Falha"}`);
    } finally {
      setClassifSaving(false);
    }
  };

  // === APLICAR MASCARA handler (por produto) ===
  const handleAplicarMascara = async (produtoId: string) => {
    setMascaraLoading(true);
    setShowMascaraModal(true);
    setMascaraResultado(null);
    try {
      const token = localStorage.getItem("token");
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = "Bearer " + token;
      const res = await fetch("/api/portfolio/aplicar-mascara", {
        method: "POST",
        headers,
        body: JSON.stringify({ produto_id: produtoId }),
      });
      if (!res.ok) throw new Error(`Erro ${res.status}`);
      const data = await res.json();
      setMascaraResultado(data);
    } catch (err) {
      setError(`Erro ao aplicar mascara: ${err instanceof Error ? err.message : "Falha"}`);
      setShowMascaraModal(false);
    } finally {
      setMascaraLoading(false);
    }
  };

  // === ACEITAR MASCARA handler ===
  const handleAceitarMascara = async () => {
    if (!mascaraResultado) return;
    try {
      const token = localStorage.getItem("token");
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = "Bearer " + token;
      await fetch(`/api/crud/produtos/${mascaraResultado.produto_id}`, {
        method: "PUT",
        headers,
        body: JSON.stringify({
          descricao_normalizada: mascaraResultado.descricao_normalizada,
          mascara_ativa: true,
        }),
      });
      setShowMascaraModal(false);
      setMascaraResultado(null);
      fetchProdutos();
    } catch (err) {
      setError(`Erro ao aceitar mascara: ${err instanceof Error ? err.message : "Falha"}`);
    }
  };

  // === APLICAR MASCARA EM LOTE handler ===
  const handleAplicarMascaraLote = async () => {
    if (selectedIds.size === 0) return;
    setMascaraLoteLoading(true);
    try {
      const token = localStorage.getItem("token");
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (token) headers["Authorization"] = "Bearer " + token;
      const res = await fetch("/api/portfolio/aplicar-mascara-lote", {
        method: "POST",
        headers,
        body: JSON.stringify({ produto_ids: Array.from(selectedIds) }),
      });
      if (!res.ok) throw new Error(`Erro ${res.status}`);
      setSelectedIds(new Set());
      fetchProdutos();
    } catch (err) {
      setError(`Erro ao aplicar mascara em lote: ${err instanceof Error ? err.message : "Falha"}`);
    } finally {
      setMascaraLoteLoading(false);
    }
  };

  // Colunas da tabela
  const columns: Column<Produto>[] = [
    {
      key: "select", header: "", width: "40px",
      render: (p) => (
        <input
          type="checkbox"
          checked={selectedIds.has(p.id)}
          onChange={(e) => { e.stopPropagation(); toggleSelectProduto(p.id); }}
          onClick={(e) => e.stopPropagation()}
          style={{ cursor: "pointer", width: 16, height: 16 }}
        />
      ),
    },
    {
      key: "nome", header: "Produto", sortable: true,
      render: (p) => (
        <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
          <span>{p.nome}</span>
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {!p.subclasse_id && (
              <span style={{
                display: "inline-block", padding: "1px 8px", borderRadius: 10,
                fontSize: "0.72rem", fontWeight: 600,
                color: "#b45309", background: "rgba(245,158,11,0.15)",
                border: "1px solid rgba(245,158,11,0.3)",
              }}>Sem Classe</span>
            )}
            {p.mascara_ativa && (
              <span style={{
                display: "inline-block", padding: "1px 8px", borderRadius: 10,
                fontSize: "0.72rem", fontWeight: 600,
                color: "#15803d", background: "rgba(34,197,94,0.12)",
                border: "1px solid rgba(34,197,94,0.3)",
              }}>Mascara Ativa</span>
            )}
          </div>
        </div>
      ),
    },
    { key: "fabricante", header: "Fabricante", sortable: true, render: (p) => p.fabricante || "-" },
    { key: "codigo_interno", header: "SKU", render: (p) => p.codigo_interno || "-" },
    {
      key: "classe", header: "Classe", sortable: true,
      render: (p) => getClasseNome(p),
    },
    {
      key: "categoria", header: "Subclasse", sortable: true,
      render: (p) => getSubclasseNome(p),
    },
    {
      key: "descricao_normalizada", header: "Desc. Normalizada",
      render: (p) => {
        const desc = p.descricao_normalizada || "";
        if (!desc) return <span style={{ color: "var(--text-tertiary)", fontSize: "0.82rem" }}>-</span>;
        const truncated = desc.length > 80 ? desc.substring(0, 80) + "..." : desc;
        return (
          <span title={desc} style={{ fontSize: "0.82rem" }}>{truncated}</span>
        );
      },
    },
    {
      key: "status_pipeline", header: "Status", sortable: true,
      render: (p) => {
        const status = p.status_pipeline || "cadastrado";
        const cfg = pipelineStatusConfig[status] || pipelineStatusConfig.cadastrado;
        return (
          <span style={{
            display: "inline-block", padding: "2px 10px", borderRadius: 12,
            fontSize: "0.82rem", fontWeight: 600,
            color: cfg.color, background: cfg.bg,
          }}>
            {cfg.label}
          </span>
        );
      },
    },
    {
      key: "acoes", header: "Acoes", width: "240px",
      render: (p) => (
        <div className="table-actions">
          <button title="Visualizar" onClick={(e) => { e.stopPropagation(); handleSelectProduto(p); }}><Eye size={18} /></button>
          <button title="Editar" onClick={(e) => { e.stopPropagation(); handleEditarAbrir(p); }}><Edit2 size={18} /></button>
          <button title="Aplicar Mascara" onClick={(e) => { e.stopPropagation(); handleAplicarMascara(p.id); }} style={{ color: "#8b5cf6" }}><Layers size={18} /></button>
          <button title="Reprocessar IA" onClick={(e) => { e.stopPropagation(); handleReprocessar(p); }}><RefreshCw size={18} /></button>
          {(() => {
            // obs 15 validador V8: farol de completude na lupa
            const pct = completudeMap[p.id];
            const cor = pct == null ? undefined : pct >= 90 ? "#22c55e" : pct >= 50 ? "#f59e0b" : "#ef4444";
            const tit = pct == null ? "Verificar Completude" : `Completude: ${pct}% — clique para detalhes`;
            return (
              <button title={tit} onClick={(e) => { e.stopPropagation(); handleVerificarCompletude(p); }} style={cor ? { color: cor } : undefined}>
                <Search size={18} />
              </button>
            );
          })()}
          <button title="Excluir" className="danger" onClick={(e) => { e.stopPropagation(); handleExcluir(p); }}><Trash2 size={18} /></button>
        </div>
      ),
    },
  ];

  const detalhe = selectedProdutoFull || selectedProduto;

  return (
    <div className="page-container">
      {/* === HEADER === */}
      <div className="page-header">
        <div className="page-header-left">
          <Briefcase size={24} />
          <div>
            <h1>Portfolio de Produtos</h1>
            <p className="portfolio-subtitle">Etapa mais estrategica — Cadastro e gestao completa do portfolio</p>
          </div>
        </div>
        <div className="page-header-actions">
          <ActionButton icon={<RefreshCw size={16} />} label="Atualizar" onClick={fetchProdutos} />
          <ActionButton icon={<Shield size={16} />} label="Buscar ANVISA" onClick={() => setShowAnvisaModal(true)} />
          <ActionButton icon={<Globe size={16} />} label="Buscar na Web" onClick={() => setShowBuscaWebModal(true)} />
        </div>
      </div>

      {/* === TABS === */}
      <div className="portfolio-tabs">
        <button className={`ptab ${activeTab === "produtos" ? "active" : ""}`} onClick={() => setActiveTab("produtos")}>
          <Eye size={16} /> Meus Produtos ({produtos.length})
        </button>
        <button className={`ptab ${activeTab === "cadastroIA" ? "active" : ""}`} onClick={() => setActiveTab("cadastroIA")}>
          <Sparkles size={16} /> Cadastro por IA
        </button>
        <button className={`ptab ${activeTab === "classificacao" ? "active" : ""}`} onClick={() => setActiveTab("classificacao")}>
          <ClipboardList size={16} /> Classificacao
        </button>
      </div>

      <div className="page-content">
        {error && (
          <div className="portfolio-error">
            <AlertCircle size={16} />
            <span>{error}</span>
            <button onClick={fetchProdutos}>Tentar novamente</button>
          </div>
        )}

        {processingMessage && (
          <div className="portfolio-processing-toast">
            <Loader2 size={16} className="spin" />
            <span>{processingMessage}</span>
          </div>
        )}

        {iaResponse && (
          <Card>
            <div style={{ position: "relative" }}>
              <button
                onClick={() => setIaResponse(null)}
                style={{ position: "absolute", top: 0, right: 0, background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)", fontSize: "18px" }}
              >&times;</button>
              <div style={{ display: "flex", alignItems: "flex-start", gap: "12px" }}>
                <Sparkles size={20} style={{ color: "var(--accent-primary)", flexShrink: 0, marginTop: 2 }} />
                <div className="markdown-response"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({href, children}) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> }}>{iaResponse}</ReactMarkdown></div>
              </div>
            </div>
          </Card>
        )}

        {/* ====================================================
            TAB: MEUS PRODUTOS
            ==================================================== */}
        {activeTab === "produtos" && (
          <>
            {/* Pipeline status counters */}
            <div style={{ display: "flex", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>
              {(Object.entries(pipelineCounts) as [string, number][]).map(([status, count]) => {
                const cfg = pipelineStatusConfig[status];
                return (
                  <div key={status} style={{
                    display: "flex", alignItems: "center", gap: 8,
                    padding: "6px 16px", borderRadius: 8,
                    background: cfg.bg, border: `1px solid ${cfg.color}22`,
                  }}>
                    <span style={{ fontWeight: 700, fontSize: "1.1rem", color: cfg.color }}>{count}</span>
                    <span style={{ fontSize: "0.85rem", color: cfg.color }}>{cfg.label}</span>
                  </div>
                );
              })}
            </div>

            {/* NCM alert summary */}
            {produtosSemNcm.length > 0 && (
              <div style={{
                display: "flex", alignItems: "center", gap: 8,
                padding: "8px 16px", marginBottom: 12, borderRadius: 8,
                background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.25)",
                color: "#f59e0b", fontSize: "0.9rem",
              }}>
                <AlertTriangle size={16} />
                <span><strong>{produtosSemNcm.length}</strong> produto{produtosSemNcm.length > 1 ? "s" : ""} sem NCM cadastrado</span>
              </div>
            )}

            {/* Filtros: Área → Classe → Subclasse */}
            <div style={{ display: "flex", gap: 12, marginBottom: 12, flexWrap: "wrap", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <label style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--text-secondary)", whiteSpace: "nowrap" }}>Área:</label>
                <select
                  className="form-input"
                  style={{ minWidth: 160 }}
                  value={filtroArea}
                  onChange={(e) => { setFiltroArea(e.target.value); setFiltroClasse(""); setFiltroSubclasse(""); }}
                >
                  <option value="">Todas</option>
                  {areasBackend.map(a => (
                    <option key={String(a.id)} value={String(a.id)}>{String(a.nome)}</option>
                  ))}
                </select>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <label style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--text-secondary)", whiteSpace: "nowrap" }}>Classe:</label>
                <select
                  className="form-input"
                  style={{ minWidth: 160 }}
                  value={filtroClasse}
                  disabled={!filtroArea}
                  onChange={(e) => { setFiltroClasse(e.target.value); setFiltroSubclasse(""); }}
                >
                  <option value="">Todas</option>
                  {classesV2Backend
                    .filter(c => !filtroArea || String(c.area_id) === filtroArea)
                    .map(c => (
                      <option key={String(c.id)} value={String(c.id)}>{String(c.nome)}</option>
                    ))}
                </select>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <label style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--text-secondary)", whiteSpace: "nowrap" }}>Subclasse:</label>
                <select
                  className="form-input"
                  style={{ minWidth: 180 }}
                  value={filtroSubclasse}
                  disabled={!filtroClasse}
                  onChange={(e) => setFiltroSubclasse(e.target.value)}
                >
                  <option value="">Todas</option>
                  {subclassesBackend
                    .filter(s => !filtroClasse || String(s.classe_id) === filtroClasse)
                    .map(s => (
                      <option key={String(s.id)} value={String(s.id)}>{String(s.nome)}</option>
                    ))}
                </select>
              </div>
              {/* Filtro "Sem Classe" */}
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <input
                  type="checkbox"
                  id="filtroSemClasse"
                  checked={filtroSemClasse}
                  onChange={(e) => setFiltroSemClasse(e.target.checked)}
                  style={{ cursor: "pointer", width: 16, height: 16 }}
                />
                <label htmlFor="filtroSemClasse" style={{
                  fontSize: "0.85rem", fontWeight: 600, cursor: "pointer",
                  color: filtroSemClasse ? "#b45309" : "var(--text-secondary)", whiteSpace: "nowrap",
                }}>Sem Classe</label>
              </div>
              {/* obs 16 validador V8: filtro por nivel de completude */}
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <label htmlFor="filtroCompletude" style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--text-secondary)", whiteSpace: "nowrap" }}>
                  Completude:
                </label>
                <select
                  id="filtroCompletude"
                  value={filtroCompletude}
                  onChange={(e) => setFiltroCompletude(e.target.value)}
                  style={{ cursor: "pointer" }}
                >
                  <option value="">Todas</option>
                  <option value="verde">🟢 Completo (≥90%)</option>
                  <option value="amarelo">🟡 Parcial (50-89%)</option>
                  <option value="vermelho">🔴 Incompleto (&lt;50%)</option>
                </select>
              </div>
            </div>

            {/* Batch actions bar */}
            <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center", flexWrap: "wrap" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <input
                  type="checkbox"
                  checked={filteredProdutos.length > 0 && selectedIds.size === filteredProdutos.length}
                  onChange={toggleSelectAll}
                  style={{ cursor: "pointer", width: 16, height: 16 }}
                />
                <span style={{ fontSize: "0.82rem", color: "var(--text-secondary)" }}>
                  {selectedIds.size > 0 ? `${selectedIds.size} selecionado(s)` : "Selecionar todos"}
                </span>
              </div>
              {selectedIds.size > 0 && (
                <>
                  <button
                    className="btn btn-primary"
                    style={{ padding: "4px 14px", fontSize: "0.82rem", display: "flex", alignItems: "center", gap: 6 }}
                    onClick={() => { setShowClassificarModal(true); setClassifArea(""); setClassifClasse(""); setClassifSubclasse(""); }}
                  >
                    <SquareCheckIcon size={14} /> Classificar Selecionados ({selectedIds.size})
                  </button>
                  <button
                    className="btn btn-secondary"
                    style={{ padding: "4px 14px", fontSize: "0.82rem", display: "flex", alignItems: "center", gap: 6 }}
                    onClick={handleAplicarMascaraLote}
                    disabled={mascaraLoteLoading}
                  >
                    {mascaraLoteLoading ? <Loader2 size={14} className="spin" /> : <Layers size={14} />}
                    Aplicar Mascara em Lote ({selectedIds.size})
                  </button>
                </>
              )}
            </div>

            <Card>
              <FilterBar
                searchValue={searchTerm}
                onSearchChange={setSearchTerm}
                searchPlaceholder="Buscar produto, fabricante, modelo..."
                filters={[]}
              />
              <DataTable
                data={filteredProdutos}
                columns={columns}
                idKey="id"
                onRowClick={handleSelectProduto}
                selectedId={selectedProduto?.id}
                loading={loading}
                emptyMessage={loading ? "Carregando produtos..." : "Nenhum produto cadastrado. Use as abas Uploads ou Cadastro Manual para adicionar produtos."}
              />
            </Card>

            {/* Detalhes do produto selecionado */}
            {detalhe && (
              <div ref={detalheRef}>
              <Card
                title={`Detalhes: ${detalhe.nome}`}
                actions={
                  <div className="card-actions">
                    <ActionButton icon={<RefreshCw size={14} />} label="Reprocessar IA" onClick={() => handleReprocessar(detalhe)} />
                    <ActionButton icon={<Search size={14} />} label="Verificar Completude" onClick={() => handleVerificarCompletude(detalhe)} />
                    <ActionButton icon={<DollarSign size={14} />} label="Precos de Mercado" onClick={() => onSendToChat("Busque precos de " + detalhe.nome + " no PNCP")} />
                    <ActionButton icon={<Trash2 size={14} />} label="Excluir" onClick={() => handleExcluir(detalhe)} />
                  </div>
                }
              >
                {loadingDetail ? (
                  <div className="loading-detail">
                    <Loader2 size={20} className="spin" />
                    <span>Carregando detalhes...</span>
                  </div>
                ) : (
                  <div className="produto-detalhes">
                    <div className="produto-info-grid">
                      <div className="info-group"><label>Nome</label><span>{detalhe.nome}</span></div>
                      <div className="info-group"><label>Fabricante</label><span>{detalhe.fabricante || "-"}</span></div>
                      <div className="info-group"><label>Modelo</label><span>{detalhe.modelo || "-"}</span></div>
                      <div className="info-group"><label>Categoria</label><span>{detalhe.categoria || "-"}</span></div>
                      <div className="info-group"><label>Classificacao</label><span>{(() => {
                        if (!detalhe.subclasse_id) return "-";
                        const sub = subclassesBackend.find(s => String(s.id) === String(detalhe.subclasse_id));
                        if (!sub) return "-";
                        const classe = classesV2Backend.find(c => String(c.id) === String(sub.classe_id));
                        const area = classe ? areasBackend.find(a => String(a.id) === String(classe.area_id)) : null;
                        return `${area ? String(area.nome) : "?"} → ${classe ? String(classe.nome) : "?"} → ${String(sub.nome)}`;
                      })()}</span></div>
                      <div className="info-group"><label>NCM</label><span>{detalhe.ncm || "-"}</span></div>
                      <div className="info-group"><label>Preco Referencia</label><span>{detalhe.preco_referencia ? `R$ ${detalhe.preco_referencia.toLocaleString("pt-BR")}` : "-"}</span></div>
                      <div className="info-group"><label>Status Pipeline</label><span>{(() => {
                        const st = detalhe.status_pipeline || "cadastrado";
                        const cfg = pipelineStatusConfig[st] || pipelineStatusConfig.cadastrado;
                        return <span style={{ padding: "2px 10px", borderRadius: 12, fontSize: "0.82rem", fontWeight: 600, color: cfg.color, background: cfg.bg }}>{cfg.label}</span>;
                      })()}</span></div>
                      <div className="info-group"><label>Registro ANVISA</label><span>{detalhe.registro_anvisa || "-"}</span></div>
                      <div className="info-group"><label>Status ANVISA</label><span>{detalhe.anvisa_status ? detalhe.anvisa_status.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase()) : "-"}</span></div>
                      {detalhe.descricao && (
                        <div className="info-group full-width"><label>Descricao</label><span>{detalhe.descricao}</span></div>
                      )}
                    </div>

                    {detalhe.especificacoes && detalhe.especificacoes.length > 0 && (
                      <div className="produto-specs">
                        <h4>Especificacoes Tecnicas ({detalhe.especificacoes.length})</h4>
                        <table className="specs-table">
                          <thead>
                            <tr><th>Especificacao</th><th>Valor</th><th>Unidade</th></tr>
                          </thead>
                          <tbody>
                            {detalhe.especificacoes.map((spec: ProdutoEspecificacao) => (
                              <tr key={spec.id}>
                                <td>
                                  <span className="fonte-cell">
                                    <Sparkles size={12} style={{ color: "#8b5cf6" }} />
                                    {spec.nome_especificacao}
                                    <span className="ia-badge" title="Extraido pela IA">IA</span>
                                  </span>
                                </td>
                                <td>{spec.valor || "-"}</td>
                                <td>{spec.unidade || "-"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {(!detalhe.especificacoes || detalhe.especificacoes.length === 0) && (
                      <div className="no-specs">
                        <AlertCircle size={16} />
                        <span>Nenhuma especificacao extraida. Use "Reprocessar IA" para extrair ou adicione manualmente abaixo.</span>
                      </div>
                    )}

                    {/* obs 12 validador V8 — adicionar especificacao manual ao produto */}
                    <div style={{ marginTop: 12, padding: 12, border: "1px solid var(--border-primary)", borderRadius: 8 }}>
                      <div style={{ fontSize: "0.85rem", fontWeight: 600, marginBottom: 8, color: "var(--text-secondary)" }}>
                        Adicionar especificacao manualmente
                      </div>
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
                        <div style={{ flex: 2, minWidth: 160 }}>
                          <FormField label="Especificacao">
                            <TextInput value={novaSpecNome} onChange={setNovaSpecNome} placeholder="Ex: Tensao de operacao" />
                          </FormField>
                        </div>
                        <div style={{ flex: 2, minWidth: 140 }}>
                          <FormField label="Valor">
                            <TextInput value={novaSpecValor} onChange={setNovaSpecValor} placeholder="Ex: 100-240" />
                          </FormField>
                        </div>
                        <div style={{ flex: 1, minWidth: 90 }}>
                          <FormField label="Unidade">
                            <TextInput value={novaSpecUnidade} onChange={setNovaSpecUnidade} placeholder="V" />
                          </FormField>
                        </div>
                        <button
                          className="btn btn-primary"
                          onClick={() => handleAdicionarSpec(detalhe.id)}
                          disabled={salvandoSpec || !novaSpecNome.trim() || !novaSpecValor.trim()}
                          style={{ marginBottom: 2 }}
                        >
                          {salvandoSpec ? "Salvando..." : "+ Adicionar"}
                        </button>
                      </div>
                      {specMsg && (
                        <div style={{ marginTop: 6, fontSize: "0.8rem", color: specMsg.startsWith("✓") ? "#22c55e" : "#ef4444" }}>
                          {specMsg}
                        </div>
                      )}
                    </div>

                    {/* Metadados de Captação */}
                    <div className="metadados-captacao">
                      <h4
                        style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: 6, marginTop: 16 }}
                        onClick={() => setShowMetadados(!showMetadados)}
                      >
                        {showMetadados ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                        Metadados de Captacao
                        <span className="ia-badge" title="Gerado pela IA">IA</span>
                      </h4>
                      {showMetadados && (
                        <div className="metadados-content" style={{ marginTop: 8 }}>
                          {/* UC-F12 V8 — toggle modo edicao */}
                          {!editingMetadados ? (
                            <div style={{ marginBottom: 10 }}>
                              <button
                                onClick={handleAbrirEdicaoMetadados}
                                style={{
                                  padding: "4px 12px", fontSize: 11,
                                  background: "#0f3460", color: "#fff", border: "1px solid #1e4a72",
                                  borderRadius: 4, cursor: "pointer"
                                }}
                              >
                                ✏ Editar metadados manualmente
                              </button>
                              <span style={{ marginLeft: 10, fontSize: 11, color: "#777" }}>
                                ou clique &quot;Reprocessar Metadados&quot; abaixo para regenerar via IA
                              </span>
                            </div>
                          ) : (
                            <div style={{ marginBottom: 10, padding: 8, background: "#fff8e1", border: "1px solid #ffd54f", borderRadius: 4, fontSize: 11, color: "#5d4037" }}>
                              <strong>Modo edição manual</strong> — separe múltiplos valores por vírgula. Salvar substitui os valores da IA.
                            </div>
                          )}
                          {metadadosMsg && (
                            <div style={{ marginBottom: 10, padding: 6, fontSize: 12,
                              background: metadadosMsg.startsWith("✓") ? "#e8f5e9" : "#ffebee",
                              color: metadadosMsg.startsWith("✓") ? "#2e7d32" : "#c62828",
                              borderRadius: 4 }}>{metadadosMsg}</div>
                          )}

                          {/* CATMAT */}
                          <div className="info-group">
                            <label>Codigos CATMAT</label>
                            {editingMetadados ? (
                              <input
                                type="text"
                                value={editCatmat}
                                onChange={(e) => setEditCatmat(e.target.value)}
                                placeholder="ex: 495268, 495269"
                                style={{ width: "100%", padding: "6px 10px", fontSize: 13, border: "1px solid #ccc", borderRadius: 4 }}
                              />
                            ) : (
                              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                                {(detalhe.catmat_codigos && detalhe.catmat_codigos.length > 0)
                                  ? detalhe.catmat_codigos.map((c: string, i: number) => (
                                      <span key={i} className="ia-badge" style={{ fontSize: 11 }} title={detalhe.catmat_descricoes?.[i] || ""}>{c}</span>
                                    ))
                                  : <span style={{ color: "#999", fontSize: 12 }}>Nenhum codigo CATMAT</span>
                                }
                              </div>
                            )}
                          </div>

                          {/* Descrições CATMAT (sempre read-only — descrições vêm da API SIASG) */}
                          {!editingMetadados && detalhe.catmat_descricoes && detalhe.catmat_descricoes.length > 0 && (
                            <div className="info-group" style={{ marginTop: 8 }}>
                              <label>Descricoes CATMAT</label>
                              <div style={{ fontSize: 12, color: "#666" }}>
                                {detalhe.catmat_descricoes.map((d: string, i: number) => (
                                  <div key={i}>• {d}</div>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* CATSER */}
                          <div className="info-group" style={{ marginTop: 8 }}>
                            <label>Codigos CATSER</label>
                            {editingMetadados ? (
                              <input
                                type="text"
                                value={editCatser}
                                onChange={(e) => setEditCatser(e.target.value)}
                                placeholder="ex: 27502, 27510"
                                style={{ width: "100%", padding: "6px 10px", fontSize: 13, border: "1px solid #ccc", borderRadius: 4 }}
                              />
                            ) : (
                              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                                {(detalhe.catser_codigos && detalhe.catser_codigos.length > 0)
                                  ? detalhe.catser_codigos.map((c: string, i: number) => (
                                      <span key={i} className="ia-badge" style={{ fontSize: 11 }}>{c}</span>
                                    ))
                                  : <span style={{ color: "#999", fontSize: 12 }}>Nenhum codigo CATSER</span>
                                }
                              </div>
                            )}
                          </div>

                          {/* Termos de Busca */}
                          <div className="info-group" style={{ marginTop: 8 }}>
                            <label>Termos de Busca Semanticos</label>
                            {editingMetadados ? (
                              <input
                                type="text"
                                value={editTermos}
                                onChange={(e) => setEditTermos(e.target.value)}
                                placeholder="ex: hemograma, hematologia, CBC"
                                style={{ width: "100%", padding: "6px 10px", fontSize: 13, border: "1px solid #ccc", borderRadius: 4 }}
                              />
                            ) : (
                              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                                {(detalhe.termos_busca && detalhe.termos_busca.length > 0)
                                  ? detalhe.termos_busca.map((t: string, i: number) => (
                                      <span key={i} style={{
                                        background: "#e8f5e9", color: "#2e7d32", padding: "2px 8px",
                                        borderRadius: 12, fontSize: 11, border: "1px solid #c8e6c9"
                                      }}>{t}</span>
                                    ))
                                  : <span style={{ color: "#999", fontSize: 12 }}>Nenhum termo gerado</span>
                                }
                              </div>
                            )}
                          </div>

                          {/* UC-F12 V8 — botoes Salvar/Cancelar quando em edicao */}
                          {editingMetadados && (
                            <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
                              <button
                                onClick={() => handleSalvarMetadados(detalhe.id)}
                                disabled={savingMetadados}
                                style={{
                                  padding: "6px 16px", fontSize: 12,
                                  background: "#2e7d32", color: "#fff", border: "none",
                                  borderRadius: 4, cursor: savingMetadados ? "not-allowed" : "pointer", opacity: savingMetadados ? 0.6 : 1
                                }}
                              >
                                {savingMetadados ? "Salvando..." : "✓ Salvar metadados"}
                              </button>
                              <button
                                onClick={handleCancelarEdicaoMetadados}
                                disabled={savingMetadados}
                                style={{
                                  padding: "6px 16px", fontSize: 12,
                                  background: "#fff", color: "#666", border: "1px solid #ccc",
                                  borderRadius: 4, cursor: "pointer"
                                }}
                              >
                                Cancelar
                              </button>
                            </div>
                          )}

                          {/* Última atualização */}
                          <div className="info-group" style={{ marginTop: 8 }}>
                            <label>Ultima Atualizacao</label>
                            <span style={{ fontSize: 12, color: "#999" }}>
                              {detalhe.catmat_updated_at
                                ? new Date(detalhe.catmat_updated_at).toLocaleString("pt-BR")
                                : "Nunca processado"}
                            </span>
                          </div>

                          {/* Botão Reprocessar */}
                          <button
                            style={{
                              marginTop: 10, padding: "6px 14px", fontSize: 12,
                              background: "#7c3aed", color: "#fff", border: "none",
                              borderRadius: 6, cursor: "pointer", display: "flex",
                              alignItems: "center", gap: 6
                            }}
                            disabled={reprocessandoMeta}
                            onClick={() => handleReprocessarMetadados(detalhe.id)}
                          >
                            {reprocessandoMeta ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
                            {reprocessandoMeta ? "Reprocessando..." : "Reprocessar Metadados"}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </Card>
              </div>
            )}
          </>
        )}

        {/* ====================================================
            TAB: CADASTRO POR IA
            ==================================================== */}
        {activeTab === "cadastroIA" && (
          <>
            {/* F02-03: upload em lote por IA — drag-and-drop de varios PDFs */}
            <Card title="🤖 Upload em Lote por IA (NOVO)" subtitle="Arraste varios catalogos/manuais/registros — IA classifica e extrai dados de cada produto. Voce revisa antes de salvar.">
              <UploadLoteIA contexto="portfolio" />
            </Card>

            <Card title="Cadastro por IA" subtitle="Faca upload de documentos e a IA extrai automaticamente os dados do produto e suas especificacoes tecnicas.">
              <div className="cadastro-form">
                {/* Linha 1: Tipo de documento */}
                <div className="cadastro-row">
                  <FormField label="Tipo de Documento">
                    <SelectInput
                      value={tipoDocumento}
                      onChange={(v) => { setTipoDocumento(v); setUploadFile(null); if (fileInputRef.current) fileInputRef.current.value = ""; }}
                      options={UPLOAD_TYPES.map(t => ({ value: t.id, label: t.label }))}
                    />
                  </FormField>
                </div>

                {/* Linha 2: Arquivo ou URL */}
                {tipoDocumento === "website" ? (
                  <div className="cadastro-row">
                    <FormField label="URL do Website" required>
                      <TextInput
                        value={websiteUrl}
                        onChange={setWebsiteUrl}
                        placeholder="https://www.fabricante.com.br/produto"
                      />
                    </FormField>
                  </div>
                ) : (
                  <>
                    <div className="cadastro-row">
                      <FormField label="Arquivo" required>
                        <input
                          ref={fileInputRef}
                          type="file"
                          accept={UPLOAD_TYPES.find(t => t.id === tipoDocumento)?.accept || ".pdf"}
                          onChange={handleUploadFileChange}
                          className="upload-file-input"
                        />
                      </FormField>
                    </div>
                    {uploadFile && (
                      <div className="upload-file-info" style={{ marginBottom: 12 }}>
                        <FileText size={14} />
                        <span>{uploadFile.name} ({(uploadFile.size / 1024).toFixed(0)} KB)</span>
                      </div>
                    )}
                    <div className="cadastro-row">
                      <FormField label="Nome do Produto (opcional)" hint="A IA extrai automaticamente do documento">
                        <TextInput
                          value={uploadNomeProduto}
                          onChange={setUploadNomeProduto}
                          placeholder="Sera extraido automaticamente pela IA"
                        />
                      </FormField>
                    </div>
                  </>
                )}

                {/* Classificacao opcional (melhora extração com máscara) */}
                {tipoDocumento !== "website" && (
                  <div style={{ border: "1px solid var(--border-primary)", borderRadius: 8, padding: 12, marginTop: 8, marginBottom: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                      <Filter size={14} style={{ color: "var(--accent-primary)" }} />
                      <span style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--text-secondary)" }}>
                        Classificacao (opcional — melhora a extracao com a mascara da subclasse)
                      </span>
                    </div>
                    <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                      <div style={{ flex: 1, minWidth: 140 }}>
                        <label style={{ fontSize: "0.8rem", color: "var(--text-tertiary)" }}>Area</label>
                        <select className="form-input" value={uploadArea} onChange={(e) => handleUploadAreaChange(e.target.value)}>
                          <option value="">Todas</option>
                          {areasBackend.map(a => <option key={String(a.id)} value={String(a.id)}>{String(a.nome)}</option>)}
                        </select>
                      </div>
                      <div style={{ flex: 1, minWidth: 140 }}>
                        <label style={{ fontSize: "0.8rem", color: "var(--text-tertiary)" }}>Classe</label>
                        <select className="form-input" value={uploadClasse} disabled={!uploadArea} onChange={(e) => handleUploadClasseChange(e.target.value)}>
                          <option value="">Todas</option>
                          {classesV2Backend.filter(c => !uploadArea || String(c.area_id) === uploadArea).map(c => (
                            <option key={String(c.id)} value={String(c.id)}>{String(c.nome)}</option>
                          ))}
                        </select>
                      </div>
                      <div style={{ flex: 1, minWidth: 140 }}>
                        <label style={{ fontSize: "0.8rem", color: "var(--text-tertiary)" }}>Subclasse</label>
                        <select className="form-input" value={uploadSubclasse} disabled={!uploadClasse} onChange={(e) => setUploadSubclasse(e.target.value)}>
                          <option value="">Todas</option>
                          {subclassesBackend.filter(s => !uploadClasse || String(s.classe_id) === uploadClasse).map(s => (
                            <option key={String(s.id)} value={String(s.id)}>{String(s.nome)}</option>
                          ))}
                        </select>
                      </div>
                    </div>
                  </div>
                )}

                {/* Botao */}
                <div className="cadastro-actions">
                  <button
                    className="btn btn-primary"
                    onClick={handleUploadConfirm}
                    disabled={(tipoDocumento === "website" ? !websiteUrl : !uploadFile) || !!processingMessage}
                  >
                    {processingMessage ? (
                      <><Loader2 size={14} className="spin" /> Processando...</>
                    ) : (
                      <><Sparkles size={14} /> Processar com IA</>
                    )}
                  </button>
                </div>

                {/* Feedback inline */}
                {processingMessage && (
                  <div className="portfolio-processing-toast" style={{ marginTop: 16 }}>
                    <Loader2 size={16} className="spin" />
                    <span>{processingMessage}</span>
                  </div>
                )}
                {iaResponse && (
                  <div style={{ marginTop: 16, padding: "16px", background: "var(--bg-secondary)", borderRadius: 8, position: "relative" }}>
                    <button
                      onClick={() => setIaResponse(null)}
                      style={{ position: "absolute", top: 8, right: 8, background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)", fontSize: "18px" }}
                    >&times;</button>
                    <div style={{ display: "flex", alignItems: "flex-start", gap: "12px" }}>
                      <Sparkles size={20} style={{ color: "var(--accent-primary)", flexShrink: 0, marginTop: 2 }} />
                      <div className="markdown-response"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({href, children}) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> }}>{iaResponse}</ReactMarkdown></div>
                    </div>
                  </div>
                )}
              </div>
            </Card>

            {/* Dica cadastro manual */}
            <div className="ia-dica-card">
              <Edit2 size={18} />
              <div>
                Para cadastro manual (sem IA), use o botao <strong>editar</strong> na aba "Meus Produtos" ou acesse <strong>Cadastros &gt; Produtos</strong> no menu lateral.
              </div>
            </div>
          </>
        )}

        {/* ====================================================
            TAB: CLASSIFICACAO
            ==================================================== */}
        {activeTab === "classificacao" && (
          <>
            <Card title="Estrutura de Classificacao" subtitle="Area → Classe → Subclasse (com mascaras de especificacao)">
              <div className="classificacao-tree">
                {areasBackend.length > 0 ? (
                    areasBackend.map((area) => {
                      const aId = String(area.id);
                      const classesInArea = classesV2Backend.filter(c => String(c.area_id) === aId);
                      return (
                        <div key={aId} className="classificacao-classe">
                          <div
                            className="classificacao-classe-header"
                            onClick={() => setExpandedArea(expandedArea === aId ? null : aId)}
                            style={{ background: "rgba(59,130,246,0.08)" }}
                          >
                            {expandedArea === aId ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                            <FolderOpen size={16} style={{ color: "#3b82f6" }} />
                            <span className="classificacao-classe-nome">{String(area.nome)}</span>
                            <span className="classificacao-count">
                              {classesInArea.length} classe(s)
                            </span>
                          </div>
                          {expandedArea === aId && classesInArea.length > 0 && (
                            <div className="classificacao-subclasses" style={{ paddingLeft: 12 }}>
                              {classesInArea.map((classe) => {
                                const cId = String(classe.id);
                                const subs = subclassesBackend.filter(s => String(s.classe_id) === cId);
                                return (
                                  <div key={cId} className="classificacao-classe" style={{ marginTop: 4 }}>
                                    <div
                                      className="classificacao-classe-header"
                                      onClick={() => setExpandedClasse(expandedClasse === cId ? null : cId)}
                                    >
                                      {expandedClasse === cId ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                      <span className="classificacao-classe-nome">{String(classe.nome)}</span>
                                      <span className="classificacao-count">{subs.length} subclasse(s)</span>
                                    </div>
                                    {expandedClasse === cId && subs.length > 0 && (
                                      <div className="classificacao-subclasses">
                                        {subs.map((sub) => {
                                          const mascara = parseMascara(sub.campos_mascara);
                                          const ncms = Array.isArray(sub.ncms) ? (sub.ncms as string[]).join(", ") : String(sub.ncms || "");
                                          return (
                                            <div key={String(sub.id)} className="classificacao-subclasse">
                                              <span className="classificacao-sub-nome">{String(sub.nome)}</span>
                                              {ncms && <span className="classificacao-ncm-badge small">NCM: {ncms}</span>}
                                              {mascara.length > 0 && (
                                                <span className="classificacao-count" style={{ color: "#8b5cf6" }}>
                                                  {mascara.length} campo(s)
                                                </span>
                                              )}
                                            </div>
                                          );
                                        })}
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      );
                    })
                  ) : (
                    <div className="no-specs">
                      <AlertCircle size={16} />
                      <span>Nenhuma area cadastrada. Configure nos CRUDs de Areas, Classes e Subclasses.</span>
                    </div>
                  )}
              </div>

              <div className="classificacao-ia-note">
                <Sparkles size={16} style={{ color: "#8b5cf6" }} />
                <span>A estrutura de classificacao e gerenciada nos CRUDs de Areas, Classes e Subclasses (menu Cadastros).</span>
              </div>
            </Card>

            {/* Card Agente de Monitoramento + Funil */}
            <Card
              title="Funil de Monitoramento"
              icon={<Radio size={18} />}
              subtitle="O Agente Autonomo que Monitora o Mercado por Voce"
            >
              {monitoramentosLoading ? (
                <div className="loading-detail">
                  <Loader2 size={20} className="spin" />
                  <span>Carregando monitoramentos...</span>
                </div>
              ) : (
                <div className="funil-monitoramento">
                  <div className="funil-steps">
                    <div className="funil-step">
                      <div className="funil-step-icon" style={{ background: "rgba(59,130,246,0.15)" }}>
                        <Radio size={24} style={{ color: "#3b82f6" }} />
                      </div>
                      <div className="funil-step-content">
                        <h4>Monitoramento Continuo</h4>
                        <p>
                          {monitoramentos.filter(m => m.status === "ativo").length} monitoramento(s) ativo(s)
                          {monitoramentos.length > 0 && ` de ${monitoramentos.length} cadastrado(s)`}
                          {monitoramentos.length === 0 && " — nenhum monitoramento cadastrado ainda"}
                        </p>
                      </div>
                    </div>
                    <div className="funil-arrow"><ArrowDown size={20} /></div>

                    <div className="funil-step">
                      <div className="funil-step-icon" style={{ background: "rgba(168,85,247,0.15)" }}>
                        <Filter size={24} style={{ color: "#a855f7" }} />
                      </div>
                      <div className="funil-step-content">
                        <h4>Filtro Inteligente</h4>
                        <p>O sistema classifica automaticamente as oportunidades por categorias estrategicas:</p>
                        <div className="funil-categorias">
                          {classesV2Backend.length > 0
                            ? classesV2Backend.map((c) => (
                                <span key={String(c.id)} className="monitor-tag">{String(c.nome)}</span>
                              ))
                            : (
                              <>
                                <span className="monitor-tag">Comodato de equipamentos</span>
                                <span className="monitor-tag">Alugueis com/sem consumo de reagentes</span>
                                <span className="monitor-tag">Venda de equipamentos</span>
                                <span className="monitor-tag">Consumo de insumos hospitalares</span>
                              </>
                            )
                          }
                        </div>
                      </div>
                    </div>
                    <div className="funil-arrow"><ArrowDown size={20} /></div>

                    <div className="funil-step">
                      <div className="funil-step-icon" style={{ background: "rgba(34,197,94,0.15)" }}>
                        <Zap size={24} style={{ color: "#22c55e" }} />
                      </div>
                      <div className="funil-step-content">
                        <h4>Classificacao Automatica</h4>
                        <p>Classificacao parametrizada em {classesV2Backend.length} classes</p>
                      </div>
                    </div>
                  </div>

                  <div className="funil-status">
                    <StatusBadge
                      status={monitoramentos.some(m => m.status === "ativo") ? "success" : "neutral"}
                      label={monitoramentos.some(m => m.status === "ativo") ? "Agente Ativo" : "Agente Inativo"}
                      size="small"
                    />
                    <span>Ultima verificacao: {(() => {
                      const dt = monitoramentos[0]?.updated_at || monitoramentos[0]?.ultimo_check;
                      if (!dt) return "Nenhuma verificacao ainda";
                      try { return new Date(dt as string).toLocaleString("pt-BR"); } catch { return "Nenhuma verificacao ainda"; }
                    })()}</span>
                  </div>
                </div>
              )}
            </Card>
          </>
        )}
      </div>

      {/* === MODAL COMPLETUDE === */}
      <Modal
        isOpen={!!completudeResult || completudeLoading}
        onClose={() => { setCompletudeResult(null); setCompletudeLoading(false); }}
        title={completudeResult ? `Completude: ${completudeResult.produto.nome}` : "Verificando completude..."}
        footer={
          <button className="btn btn-secondary" onClick={() => setCompletudeResult(null)}>Fechar</button>
        }
      >
        {completudeLoading ? (
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "2rem 0", justifyContent: "center" }}>
            <Loader2 size={20} className="spin" /> Analisando...
          </div>
        ) : completudeResult && (
          <>
            {/* Barras de percentual */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 16 }}>
              <div style={{ textAlign: "center", padding: 12, borderRadius: 8, background: "var(--bg-secondary)" }}>
                <div style={{ fontSize: "1.6rem", fontWeight: 700, color: completudeResult.completude.percentual_geral >= 90 ? "#22c55e" : completudeResult.completude.percentual_geral >= 70 ? "#f59e0b" : completudeResult.completude.percentual_geral >= 40 ? "#fb923c" : "#ef4444" }}>
                  {completudeResult.completude.percentual_geral}%
                </div>
                <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>Geral</div>
              </div>
              <div style={{ textAlign: "center", padding: 12, borderRadius: 8, background: "var(--bg-secondary)" }}>
                <div style={{ fontSize: "1.6rem", fontWeight: 700, color: completudeResult.completude.percentual_basicos >= 90 ? "#22c55e" : completudeResult.completude.percentual_basicos >= 70 ? "#f59e0b" : "#ef4444" }}>
                  {completudeResult.completude.percentual_basicos}%
                </div>
                <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>Dados Basicos</div>
              </div>
              <div style={{ textAlign: "center", padding: 12, borderRadius: 8, background: "var(--bg-secondary)" }}>
                {completudeResult.completude.percentual_mascara == null ? (
                  <div style={{ fontSize: "1.6rem", fontWeight: 700, color: "var(--text-secondary)" }} title="Produto sem subclasse ou subclasse sem mascara de campos — especificacoes nao avaliaveis">
                    N/A
                  </div>
                ) : (
                  <div style={{ fontSize: "1.6rem", fontWeight: 700, color: completudeResult.completude.percentual_mascara >= 90 ? "#22c55e" : completudeResult.completude.percentual_mascara >= 70 ? "#f59e0b" : completudeResult.completude.percentual_mascara >= 40 ? "#fb923c" : "#ef4444" }}>
                    {completudeResult.completude.percentual_mascara}%
                  </div>
                )}
                <div style={{ fontSize: "0.8rem", color: "var(--text-secondary)" }}>Especificacoes</div>
              </div>
            </div>

            {/* Campos básicos */}
            <h4 style={{ margin: "0 0 8px", fontSize: "0.9rem" }}>Dados Basicos ({completudeResult.campos_basicos.filter(c => c.preenchido).length}/{completudeResult.campos_basicos.length})</h4>
            <table style={{ width: "100%", fontSize: "0.85rem", marginBottom: 16, borderCollapse: "collapse" }}>
              <tbody>
                {completudeResult.campos_basicos.map(c => (
                  <tr key={c.campo} style={{ borderBottom: "1px solid var(--border-primary)" }}>
                    <td style={{ padding: "4px 8px", width: 24 }}>
                      {c.preenchido
                        ? <CheckCircle size={16} style={{ color: "#22c55e" }} />
                        : <AlertCircle size={16} style={{ color: "#ef4444" }} />}
                    </td>
                    <td style={{ padding: "4px 8px", fontWeight: 500 }}>{c.campo}</td>
                    <td style={{ padding: "4px 8px", color: c.preenchido ? "var(--text-primary)" : "var(--text-tertiary)" }}>
                      {c.preenchido ? c.valor : "Nao preenchido"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Especificações vs máscara */}
            {completudeResult.subclasse_nome ? (
              <>
                <h4 style={{ margin: "0 0 8px", fontSize: "0.9rem" }}>
                  Especificacoes — {completudeResult.subclasse_nome} ({completudeResult.mascara_check.filter(c => c.preenchido).length}/{completudeResult.mascara_check.length})
                </h4>
                <div style={{ maxHeight: 300, overflowY: "auto" }}>
                  <table style={{ width: "100%", fontSize: "0.85rem", borderCollapse: "collapse" }}>
                    <tbody>
                      {completudeResult.mascara_check.map(c => (
                        <tr key={c.campo} style={{ borderBottom: "1px solid var(--border-primary)" }}>
                          <td style={{ padding: "3px 8px", width: 24 }}>
                            {c.preenchido
                              ? <CheckCircle size={14} style={{ color: "#22c55e" }} />
                              : <AlertCircle size={14} style={{ color: "#ef4444" }} />}
                          </td>
                          <td style={{ padding: "3px 8px", fontWeight: 500 }}>
                            {c.campo}{c.unidade ? ` (${c.unidade})` : ""}
                          </td>
                          <td style={{ padding: "3px 8px", color: c.preenchido ? "var(--text-primary)" : "var(--text-tertiary)" }}>
                            {c.preenchido ? c.valor : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <div style={{ padding: "12px", background: "rgba(245,158,11,0.08)", borderRadius: 8, color: "#f59e0b", fontSize: "0.9rem", display: "flex", alignItems: "center", gap: 8 }}>
                <AlertTriangle size={16} />
                Produto sem subclasse atribuida — nao e possivel verificar especificacoes contra a mascara.
              </div>
            )}
          </>
        )}
      </Modal>

      {/* === MODAL EDITAR PRODUTO === */}
      <Modal
        isOpen={!!editProduto}
        onClose={() => setEditProduto(null)}
        title={`Editar: ${editProduto?.nome || ""}`}
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => setEditProduto(null)}>
              <X size={14} /> Cancelar
            </button>
            <button className="btn btn-primary" onClick={handleEditarSalvar} disabled={editSaving || !editForm.nome}>
              {editSaving ? <Loader2 size={14} className="spin" /> : <Save size={14} />} Salvar
            </button>
          </>
        }
      >
        {editLoading ? (
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "2rem 0", justifyContent: "center" }}>
            <Loader2 size={20} className="spin" /> Carregando dados...
          </div>
        ) : (
          <>
            {/* Dados básicos */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              <FormField label="Nome" required>
                <TextInput value={editForm.nome || ""} onChange={(v) => setEditForm(f => ({ ...f, nome: v }))} placeholder="Nome do produto" />
              </FormField>
              <FormField label="Fabricante">
                <TextInput value={editForm.fabricante || ""} onChange={(v) => setEditForm(f => ({ ...f, fabricante: v }))} placeholder="Fabricante" />
              </FormField>
              <FormField label="Modelo">
                <TextInput value={editForm.modelo || ""} onChange={(v) => setEditForm(f => ({ ...f, modelo: v }))} placeholder="Modelo" />
              </FormField>
              <FormField label="SKU / Codigo Interno">
                <TextInput value={editForm.codigo_interno || ""} onChange={(v) => setEditForm(f => ({ ...f, codigo_interno: v }))} placeholder="Codigo interno / SKU" />
              </FormField>
              <FormField label="NCM" hint="Formato 9999.99.99 (8 digitos). Pontos sao adicionados automaticamente.">
                <TextInput value={editForm.ncm || ""} onChange={(v) => {
                  const digits = v.replace(/\D/g, '').slice(0, 8);
                  let masked = digits;
                  if (digits.length > 4) masked = digits.slice(0,4) + '.' + digits.slice(4);
                  if (digits.length > 6) masked = digits.slice(0,4) + '.' + digits.slice(4,6) + '.' + digits.slice(6);
                  setEditForm(f => ({ ...f, ncm: masked }));
                }} placeholder="Ex: 90273000" />
              </FormField>
              <FormField label="Descricao">
                <TextInput value={editForm.descricao || ""} onChange={(v) => setEditForm(f => ({ ...f, descricao: v }))} placeholder="Descricao do produto" />
              </FormField>
              <FormField label="Categoria" hint="Definida automaticamente pela IA no cadastro; pode ser corrigida aqui.">
                <SelectInput
                  value={editForm.categoria || ""}
                  onChange={(v) => setEditForm(f => ({ ...f, categoria: v }))}
                  options={[
                    { value: "equipamento", label: "Equipamento" },
                    { value: "reagente", label: "Reagente" },
                    { value: "insumo_hospitalar", label: "Insumo Hospitalar" },
                    { value: "insumo_laboratorial", label: "Insumo Laboratorial" },
                    { value: "informatica", label: "Informatica" },
                    { value: "redes", label: "Redes" },
                    { value: "mobiliario", label: "Mobiliario" },
                    { value: "eletronico", label: "Eletronico" },
                    { value: "outro", label: "Outro" },
                  ]}
                />
              </FormField>
            </div>

            {/* Classificação: Área → Classe → Subclasse */}
            <div style={{ marginTop: 16, padding: "12px 0", borderTop: "1px solid var(--border-primary)" }}>
              <h4 style={{ margin: "0 0 10px", fontSize: "0.95rem", color: "var(--text-primary)" }}>Classificacao</h4>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
                <FormField label="Area">
                  <select className="form-input" value={editArea} onChange={(e) => { setEditArea(e.target.value); setEditClasse(""); setEditSubclasse(""); }}>
                    <option value="">Selecione...</option>
                    {areasBackend.map(a => <option key={String(a.id)} value={String(a.id)}>{String(a.nome)}</option>)}
                  </select>
                </FormField>
                <FormField label="Classe">
                  <select className="form-input" value={editClasse} disabled={!editArea} onChange={(e) => { setEditClasse(e.target.value); setEditSubclasse(""); }}>
                    <option value="">Selecione...</option>
                    {classesV2Backend.filter(c => String(c.area_id) === editArea).map(c => <option key={String(c.id)} value={String(c.id)}>{String(c.nome)}</option>)}
                  </select>
                </FormField>
                <FormField label="Subclasse">
                  <select className="form-input" value={editSubclasse} disabled={!editClasse} onChange={(e) => setEditSubclasse(e.target.value)}>
                    <option value="">Selecione...</option>
                    {subclassesBackend.filter(s => String(s.classe_id) === editClasse).map(s => <option key={String(s.id)} value={String(s.id)}>{String(s.nome)}</option>)}
                  </select>
                </FormField>
              </div>
            </div>

            {/* Especificações da máscara */}
            {editMascara.length > 0 && (
              <div style={{ marginTop: 16, padding: "12px 0", borderTop: "1px solid var(--border-primary)" }}>
                <h4 style={{ margin: "0 0 10px", fontSize: "0.95rem", color: "var(--text-primary)" }}>
                  Especificacoes Tecnicas ({editMascara.length} campos)
                </h4>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                  {editMascara.map((campo) => {
                    const specVal = editSpecs[campo.campo]?.valor || "";
                    return (
                      <FormField key={campo.campo} label={`${campo.campo}${campo.unidade ? ` (${campo.unidade})` : ""}`}>
                        {campo.tipo === "select" && campo.opcoes ? (
                          <select
                            className="form-input"
                            value={specVal}
                            onChange={(e) => setEditSpecs(prev => ({ ...prev, [campo.campo]: { ...prev[campo.campo], valor: e.target.value } }))}
                          >
                            <option value="">Selecione...</option>
                            {campo.opcoes.map(op => <option key={op} value={op}>{op}</option>)}
                          </select>
                        ) : campo.tipo === "boolean" ? (
                          <select
                            className="form-input"
                            value={specVal}
                            onChange={(e) => setEditSpecs(prev => ({ ...prev, [campo.campo]: { ...prev[campo.campo], valor: e.target.value } }))}
                          >
                            <option value="">Selecione...</option>
                            <option value="Sim">Sim</option>
                            <option value="Nao">Nao</option>
                          </select>
                        ) : (
                          <TextInput
                            value={specVal}
                            onChange={(v) => setEditSpecs(prev => ({ ...prev, [campo.campo]: { ...prev[campo.campo], valor: v } }))}
                            placeholder={campo.placeholder || campo.campo}
                          />
                        )}
                      </FormField>
                    );
                  })}
                </div>
              </div>
            )}
          </>
        )}
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
        <p className="modal-info">A IA tenta trazer os registros e o usuario valida ou complementa.</p>
        <FormField label="Numero de Registro ANVISA">
          <TextInput value={anvisaRegistro} onChange={setAnvisaRegistro} placeholder="Ex: 80000000001" />
        </FormField>
        <FormField label="ou Nome do Produto">
          <TextInput value={anvisaNomeProduto} onChange={setAnvisaNomeProduto} placeholder="Ex: Reagente Teste Rapido" />
        </FormField>
      </Modal>

      {/* === MODAL BUSCA WEB (obs 13: usuario escolhe o que incorporar) === */}
      <Modal
        isOpen={showBuscaWebModal}
        onClose={() => { setShowBuscaWebModal(false); setBuscaNomeProduto(""); setBuscaFabricante(""); setBuscaWebResultados(null); setBuscaWebSelecionados(new Set()); }}
        title="Buscar Produto na Web"
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => { setShowBuscaWebModal(false); setBuscaWebResultados(null); }}>Cancelar</button>
            {!buscaWebResultados ? (
              <button className="btn btn-primary" onClick={handleBuscaWebConfirm} disabled={!buscaNomeProduto || buscaWebLoading}>
                <Globe size={14} /> {buscaWebLoading ? "Buscando..." : "Buscar"}
              </button>
            ) : (
              <button className="btn btn-primary" onClick={handleIncorporarSelecionados} disabled={buscaWebSelecionados.size === 0}>
                Incorporar selecionados ({buscaWebSelecionados.size})
              </button>
            )}
          </>
        }
      >
        {!buscaWebResultados ? (
          <>
            <p className="modal-info">A busca traz os documentos/manuais encontrados na web. <strong>Nada e cadastrado automaticamente</strong> — voce escolhe o que incorporar.</p>
            <FormField label="Nome do Produto" required>
              <TextInput value={buscaNomeProduto} onChange={setBuscaNomeProduto} placeholder="Ex: Microscopio Optico Olympus CX23" />
            </FormField>
            <FormField label="Fabricante (opcional)">
              <TextInput value={buscaFabricante} onChange={setBuscaFabricante} placeholder="Ex: Olympus" />
            </FormField>
          </>
        ) : (
          <>
            <p className="modal-info">
              {buscaWebResultados.total} resultado(s) para <strong>{buscaWebResultados.termo}</strong>. Marque os documentos a incorporar.
            </p>
            {[...buscaWebResultados.pdfs, ...buscaWebResultados.outros].length === 0 && (
              <div className="no-specs"><AlertCircle size={16} /><span>Nenhum resultado encontrado. Tente refinar o nome/fabricante.</span></div>
            )}
            <div style={{ maxHeight: 360, overflowY: "auto", display: "flex", flexDirection: "column", gap: 8 }}>
              {[...buscaWebResultados.pdfs.map(p => ({ ...p, _pdf: true })), ...buscaWebResultados.outros.map(p => ({ ...p, _pdf: false }))].map((r) => (
                <label key={r.link} style={{ display: "flex", gap: 8, alignItems: "flex-start", padding: 10, border: "1px solid var(--border-primary)", borderRadius: 8, cursor: "pointer", background: buscaWebSelecionados.has(r.link) ? "var(--bg-secondary)" : undefined }}>
                  <input type="checkbox" checked={buscaWebSelecionados.has(r.link)} onChange={() => toggleBuscaWebItem(r.link)} style={{ marginTop: 3, cursor: "pointer" }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: "0.88rem" }}>
                      {r._pdf && <span className="ia-badge" style={{ fontSize: 10, marginRight: 6 }}>PDF</span>}
                      {r.titulo || r.link}
                    </div>
                    {r.descricao && <div style={{ fontSize: "0.78rem", color: "var(--text-secondary)", marginTop: 2 }}>{r.descricao.slice(0, 160)}</div>}
                    <div style={{ fontSize: "0.72rem", color: "var(--accent-primary)", marginTop: 2, wordBreak: "break-all" }}>{r.link}</div>
                  </div>
                </label>
              ))}
            </div>
            <button className="btn btn-secondary" style={{ marginTop: 10 }} onClick={() => { setBuscaWebResultados(null); setBuscaWebSelecionados(new Set()); }}>
              ← Nova busca
            </button>
          </>
        )}
      </Modal>

      {/* === MODAL CLASSIFICAR SELECIONADOS === */}
      <Modal
        isOpen={showClassificarModal}
        onClose={() => setShowClassificarModal(false)}
        title={`Classificar ${selectedIds.size} Produto(s)`}
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => setShowClassificarModal(false)}>
              <X size={14} /> Cancelar
            </button>
            <button
              className="btn btn-primary"
              onClick={handleClassificarSelecionados}
              disabled={classifSaving || !classifSubclasse}
            >
              {classifSaving ? <Loader2 size={14} className="spin" /> : <Check size={14} />}
              Salvar Classificacao
            </button>
          </>
        }
      >
        <p style={{ fontSize: "0.9rem", color: "var(--text-secondary)", marginBottom: 16 }}>
          Selecione a classificacao (Area &rarr; Classe &rarr; Subclasse) para aplicar aos {selectedIds.size} produto(s) selecionado(s).
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 12 }}>
          <FormField label="Area">
            <select
              className="form-input"
              value={classifArea}
              onChange={(e) => { setClassifArea(e.target.value); setClassifClasse(""); setClassifSubclasse(""); }}
            >
              <option value="">Selecione a area...</option>
              {areasBackend.map(a => (
                <option key={String(a.id)} value={String(a.id)}>{String(a.nome)}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Classe">
            <select
              className="form-input"
              value={classifClasse}
              disabled={!classifArea}
              onChange={(e) => { setClassifClasse(e.target.value); setClassifSubclasse(""); }}
            >
              <option value="">Selecione a classe...</option>
              {classesV2Backend
                .filter(c => String(c.area_id) === classifArea)
                .map(c => (
                  <option key={String(c.id)} value={String(c.id)}>{String(c.nome)}</option>
                ))}
            </select>
          </FormField>
          <FormField label="Subclasse">
            <select
              className="form-input"
              value={classifSubclasse}
              disabled={!classifClasse}
              onChange={(e) => setClassifSubclasse(e.target.value)}
            >
              <option value="">Selecione a subclasse...</option>
              {subclassesBackend
                .filter(s => String(s.classe_id) === classifClasse)
                .map(s => (
                  <option key={String(s.id)} value={String(s.id)}>{String(s.nome)}</option>
                ))}
            </select>
          </FormField>
        </div>
      </Modal>

      {/* === MODAL RESULTADO MASCARA === */}
      <Modal
        isOpen={showMascaraModal}
        onClose={() => { setShowMascaraModal(false); setMascaraResultado(null); }}
        title="Resultado da Mascara"
        footer={
          mascaraResultado ? (
            <>
              <button className="btn btn-secondary" onClick={() => { setShowMascaraModal(false); setMascaraResultado(null); }}>
                <X size={14} /> Cancelar
              </button>
              <button className="btn btn-primary" onClick={handleAceitarMascara}>
                <Check size={14} /> Aceitar
              </button>
            </>
          ) : undefined
        }
      >
        {mascaraLoading ? (
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "2rem 0", justifyContent: "center" }}>
            <Loader2 size={20} className="spin" /> Aplicando mascara...
          </div>
        ) : mascaraResultado ? (
          <div>
            {/* Side by side: before / after */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
              <div style={{ padding: 12, borderRadius: 8, background: "rgba(239,68,68,0.06)", border: "1px solid rgba(239,68,68,0.2)" }}>
                <h4 style={{ margin: "0 0 8px", fontSize: "0.85rem", color: "#ef4444" }}>Antes (Original)</h4>
                <p style={{ fontSize: "0.9rem", margin: 0, wordBreak: "break-word" }}>
                  {mascaraResultado.descricao_original || "-"}
                </p>
              </div>
              <div style={{ padding: 12, borderRadius: 8, background: "rgba(34,197,94,0.06)", border: "1px solid rgba(34,197,94,0.2)" }}>
                <h4 style={{ margin: "0 0 8px", fontSize: "0.85rem", color: "#22c55e" }}>Depois (Normalizada)</h4>
                <p style={{ fontSize: "0.9rem", margin: 0, wordBreak: "break-word" }}>
                  {mascaraResultado.descricao_normalizada || "-"}
                </p>
              </div>
            </div>

            {/* Score impact */}
            {(mascaraResultado.score_original !== undefined || mascaraResultado.score_normalizado !== undefined) && (
              <div style={{
                display: "flex", gap: 16, marginBottom: 16, padding: "10px 16px",
                borderRadius: 8, background: "var(--bg-secondary)",
              }}>
                <div>
                  <span style={{ fontSize: "0.8rem", color: "var(--text-tertiary)" }}>Score Original</span>
                  <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "#f59e0b" }}>
                    {mascaraResultado.score_original != null ? mascaraResultado.score_original.toFixed(2) : "-"}
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", fontSize: "1.2rem", color: "var(--text-tertiary)" }}>&rarr;</div>
                <div>
                  <span style={{ fontSize: "0.8rem", color: "var(--text-tertiary)" }}>Score Normalizado</span>
                  <div style={{ fontSize: "1.2rem", fontWeight: 700, color: "#22c55e" }}>
                    {mascaraResultado.score_normalizado != null ? mascaraResultado.score_normalizado.toFixed(2) : "-"}
                  </div>
                </div>
              </div>
            )}

            {/* Variantes */}
            {mascaraResultado.variantes && mascaraResultado.variantes.length > 0 && (
              <div style={{ marginBottom: 12 }}>
                <h4 style={{ margin: "0 0 6px", fontSize: "0.85rem", color: "var(--text-secondary)" }}>Variantes</h4>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {mascaraResultado.variantes.map((v, i) => (
                    <span key={i} style={{
                      padding: "2px 8px", borderRadius: 10, fontSize: "0.78rem",
                      background: "rgba(139,92,246,0.1)", color: "#8b5cf6",
                      border: "1px solid rgba(139,92,246,0.25)",
                    }}>{v}</span>
                  ))}
                </div>
              </div>
            )}

            {/* Sinonimos */}
            {mascaraResultado.sinonimos && mascaraResultado.sinonimos.length > 0 && (
              <div>
                <h4 style={{ margin: "0 0 6px", fontSize: "0.85rem", color: "var(--text-secondary)" }}>Sinonimos</h4>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {mascaraResultado.sinonimos.map((s, i) => (
                    <span key={i} style={{
                      padding: "2px 8px", borderRadius: 10, fontSize: "0.78rem",
                      background: "rgba(59,130,246,0.1)", color: "#3b82f6",
                      border: "1px solid rgba(59,130,246,0.25)",
                    }}>{s}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : null}
      </Modal>
    </div>
  );
}
