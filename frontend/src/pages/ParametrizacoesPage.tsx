import { useState, useEffect, useCallback, useRef } from "react";
import type { PageProps } from "../types";
import { Settings, Globe, Bell, Palette, Play, Pause, MapPin, AlertTriangle, Loader2, Lock, DollarSign, Layers, Plus, Trash2, Edit2, ChevronRight, ChevronDown, Cpu, FolderTree, Package, RefreshCw, X } from "lucide-react";
import { Card, ActionButton, TabPanel, FormField, TextInput, Checkbox, SelectInput } from "../components/common";
import { crudList, crudCreate, crudUpdate, crudDelete } from "../api/crud";

interface Fonte {
  id: string;
  nome: string;
  tipo: "api" | "scraper";
  url: string;
  ativo: boolean;
}

interface ClasseProdutoAPI {
  id: string;
  nome: string;
  tipo: string;
  ncms: string[];
  classe_pai_id: string | null;
  campos_mascara: Record<string, unknown> | null;
  qtd_produtos: number;
}

interface CampoMascara {
  campo: string;
  placeholder: string;
}

interface Subclasse {
  id: string;
  nome: string;
  ncms: string;
  produtos: number;
  campos_mascara?: CampoMascara[] | null;
}

interface Classe {
  id: string;
  nome: string;
  ncms: string;
  subclasses: Subclasse[];
  produtos: number;
}

// === Classes Tab Interfaces ===
interface AreaProduto {
  id: string;
  nome: string;
  classes: ClasseV2[];
}

interface ClasseV2 {
  id: string;
  nome: string;
  descricao?: string;
  area_id: string;
  subclasses: SubclasseV2[];
}

interface SubclasseV2 {
  id: string;
  nome: string;
  ncms: string[];
  campos_mascara: CampoMascaraV2[] | null;
  classe_id: string;
  qtd_produtos: number;
}

interface CampoMascaraV2 {
  nome: string;
  tipo: string;
}

interface ProdutoSemClasse {
  id: string;
  nome: string;
  categoria?: string;
  ncm?: string;
}

interface GerarClassesResult {
  success: boolean;
  areas: GerarClasseArea[];
  total_produtos?: number;
  criados?: { areas: number; classes: number; subclasses: number; produtos_vinculados: number } | null;
  message?: string;
}

interface GerarClasseArea {
  nome: string;
  classes: GerarClasseClasse[];
}

interface GerarClasseClasse {
  nome: string;
  descricao?: string;
  subclasses: GerarClasseSubclasse[];
}

interface GerarClasseSubclasse {
  nome: string;
  ncm?: string;
  campos_mascara?: CampoMascaraV2[];
  produtos_sugeridos?: string[];
}

interface ParametroScoreAPI {
  id: string;
  estados_atuacao: string[];
  prazo_maximo: number;
  frequencia_maxima: string;
  tam: string;
  sam: string;
  som: string;
  tipos_edital: string[];
  palavras_chave: string[];
  ncms_busca: string[];
  [key: string]: unknown;
}

interface ParametroScore {
  id: string;
  nome: string;
  peso: number;
}

// Lista de estados brasileiros
const ESTADOS_BR = [
  { uf: "AC", nome: "Acre" }, { uf: "AL", nome: "Alagoas" }, { uf: "AP", nome: "Amapa" },
  { uf: "AM", nome: "Amazonas" }, { uf: "BA", nome: "Bahia" }, { uf: "CE", nome: "Ceara" },
  { uf: "DF", nome: "Distrito Federal" }, { uf: "ES", nome: "Espirito Santo" }, { uf: "GO", nome: "Goias" },
  { uf: "MA", nome: "Maranhao" }, { uf: "MT", nome: "Mato Grosso" }, { uf: "MS", nome: "Mato Grosso do Sul" },
  { uf: "MG", nome: "Minas Gerais" }, { uf: "PA", nome: "Para" }, { uf: "PB", nome: "Paraiba" },
  { uf: "PR", nome: "Parana" }, { uf: "PE", nome: "Pernambuco" }, { uf: "PI", nome: "Piaui" },
  { uf: "RJ", nome: "Rio de Janeiro" }, { uf: "RN", nome: "Rio Grande do Norte" }, { uf: "RS", nome: "Rio Grande do Sul" },
  { uf: "RO", nome: "Rondonia" }, { uf: "RR", nome: "Roraima" }, { uf: "SC", nome: "Santa Catarina" },
  { uf: "SP", nome: "Sao Paulo" }, { uf: "SE", nome: "Sergipe" }, { uf: "TO", nome: "Tocantins" },
];


export function ParametrizacoesPage(_props: PageProps) {
  const [fontes, setFontes] = useState<Fonte[]>([]);
  const [loadingFontes, setLoadingFontes] = useState(true);
  const [, setErrorFontes] = useState<string | null>(null);
  const [, setParametros] = useState<ParametroScore[]>([]);
  const [, setLoadingParametros] = useState(true);
  const [, setClasses] = useState<Classe[]>([]);

  // === Classes Tab State ===
  const [areasTree, setAreasTree] = useState<AreaProduto[]>([]);
  const [produtosSemClasse, setProdutosSemClasse] = useState<ProdutoSemClasse[]>([]);
  const [loadingClassesTab, setLoadingClassesTab] = useState(false);
  const [expandedAreas, setExpandedAreas] = useState<Set<string>>(new Set());
  const [expandedClasses, setExpandedClasses] = useState<Set<string>>(new Set());
  const [selectedSubclasse, setSelectedSubclasse] = useState<SubclasseV2 | null>(null);
  const [selectedSubclasseAreaNome, setSelectedSubclasseAreaNome] = useState("");
  const [selectedSubclasseClasseNome, setSelectedSubclasseClasseNome] = useState("");
  // CRUD modals
  const [showNewAreaModal, setShowNewAreaModal] = useState(false);
  const [showNewClasseModal, setShowNewClasseModal] = useState(false);
  const [showNewSubclasseModal, setShowNewSubclasseModal] = useState(false);
  const [editingItem, setEditingItem] = useState<{ type: "area" | "classe" | "subclasse"; id: string; nome: string; extra?: Record<string, unknown> } | null>(null);
  const [newItemNome, setNewItemNome] = useState("");
  const [newItemParentId, setNewItemParentId] = useState("");
  const [newItemNcms, setNewItemNcms] = useState("");
  const [savingClassesItem, setSavingClassesItem] = useState(false);
  // AI generation
  const [showGerarIAModal, setShowGerarIAModal] = useState(false);
  const [gerarIALoading, setGerarIALoading] = useState(false);
  const [gerarIAResult, setGerarIAResult] = useState<GerarClassesResult | null>(null);
  const [gerarIAError, setGerarIAError] = useState<string | null>(null);
  // Aplicar ao portfolio
  const [showAplicarModal, setShowAplicarModal] = useState(false);
  const [aplicarAreaId, setAplicarAreaId] = useState("");
  const [aplicarClasseId, setAplicarClasseId] = useState("");
  const [aplicarSubclasseId, setAplicarSubclasseId] = useState("");
  const [aplicarProdutoIds, setAplicarProdutoIds] = useState<Set<string>>(new Set());
  const [savingAplicar, setSavingAplicar] = useState(false);
  // Edit subclasse detail
  const [editSubclasseNome, setEditSubclasseNome] = useState("");
  const [editSubclasseNcms, setEditSubclasseNcms] = useState("");
  const [editSubclasseCampos, setEditSubclasseCampos] = useState("");
  const [savingSubclasseDetail, setSavingSubclasseDetail] = useState(false);

  // Parametros-score state (persisted)
  const [paramScoreId, setParamScoreId] = useState<string | null>(null);
  const [paramScore, setParamScore] = useState<ParametroScoreAPI | null>(null);
  const [loadingParamScore, setLoadingParamScore] = useState(true);
  const [savingParamScore, setSavingParamScore] = useState(false);

  // Palavras-chave e NCMs editing
  const [editingPalavras, setEditingPalavras] = useState(false);
  const [palavrasText, setPalavrasText] = useState("");
  const [editingNcms, setEditingNcms] = useState(false);
  const [ncmsText, setNcmsText] = useState("");

  // Configuracoes de notificacao
  const [emailNotif, setEmailNotif] = useState("contato@aquila.com.br");
  const [notifEmail, setNotifEmail] = useState(true);
  const [notifSistema, setNotifSistema] = useState(true);
  const [notifSms, setNotifSms] = useState(false);
  const [frequenciaResumo, setFrequenciaResumo] = useState("diario");

  // Preferencias
  const [tema, setTema] = useState("claro");
  const [idioma, setIdioma] = useState("pt-BR");
  const [fusoHorario, setFusoHorario] = useState("America/Sao_Paulo");

  // Tipos de edital (modalidades do banco)
  const [modalidades, setModalidades] = useState<{ id: string; nome: string; ativo: boolean }[]>([]);
  const [tiposEditalSelecionados, setTiposEditalSelecionados] = useState<Set<string>>(new Set());

  // Regiao de atuacao
  const [estadosSelecionados, setEstadosSelecionados] = useState<Set<string>>(new Set());
  const [todoBrasil, setTodoBrasil] = useState(false);

  // Comercial - Tempo de Entrega + Mercado
  const [prazoMaximo, setPrazoMaximo] = useState("");
  const [frequenciaMaxima, setFrequenciaMaxima] = useState("semanal");
  const [tam, setTam] = useState("");
  const [sam, setSam] = useState("");
  const [som, setSom] = useState("");

  // RF-014: Custos e Margens
  const [markupPadrao, setMarkupPadrao] = useState("");
  const [custosFixos, setCustosFixos] = useState("");
  const [freteBase, setFreteBase] = useState("");

  // Pesos de Score (6 dimensoes)
  const [pesoTecnico, setPesoTecnico] = useState("0.35");
  const [pesoComercial, setPesoComercial] = useState("0.10");
  const [pesoDocumental, setPesoDocumental] = useState("0.15");
  const [pesoComplexidade, setPesoComplexidade] = useState("0.15");
  const [pesoJuridico, setPesoJuridico] = useState("0.20");
  const [pesoLogistico, setPesoLogistico] = useState("0.05");

  // Limiares de decisao GO/NO-GO
  const [limiarGo, setLimiarGo] = useState("70");
  const [limiarNogo, setLimiarNogo] = useState("40");
  const [limiarTecnicoGo, setLimiarTecnicoGo] = useState("60");
  const [limiarTecnicoNogo, setLimiarTecnicoNogo] = useState("30");
  const [limiarJuridicoGo, setLimiarJuridicoGo] = useState("60");
  const [limiarJuridicoNogo, setLimiarJuridicoNogo] = useState("30");


  // R1: Feedback salvar notificacoes
  const [notifSalvas, setNotifSalvas] = useState(false);

  // R2: Feedback salvar preferencias
  const [prefSalvas, setPrefSalvas] = useState(false);

  // Feedback generico para saves (C1/C2)
  const [salvoFeedback, setSalvoFeedback] = useState<string | null>(null);
  const [erroSave, setErroSave] = useState<string | null>(null);


  // Ref for tab container to programmatically switch tabs
  const tabContainerRef = useRef<HTMLDivElement>(null);

  const loadFontes = useCallback(async () => {
    try {
      setLoadingFontes(true);
      setErrorFontes(null);
      const res = await crudList("fontes-editais");
      setFontes(res.items.map(f => ({
        id: String(f.id ?? ""),
        nome: String(f.nome ?? ""),
        tipo: (f.tipo as "api" | "scraper") || "api",
        url: String(f.url ?? ""),
        ativo: Boolean(f.ativo ?? true),
      })));
    } catch (err) {
      setErrorFontes(err instanceof Error ? err.message : "Erro ao carregar fontes");
    } finally {
      setLoadingFontes(false);
    }
  }, []);

  const loadParametros = useCallback(async () => {
    try {
      setLoadingParametros(true);
      const res = await crudList("parametros-score");
      setParametros(res.items.map(p => ({
        id: String(p.id ?? ""),
        nome: String(p.nome ?? ""),
        peso: Number(p.peso ?? 0),
      })));
    } catch {
      // May not exist yet
    } finally {
      setLoadingParametros(false);
    }
  }, []);

  const loadModalidades = useCallback(async () => {
    try {
      const res = await crudList("modalidades-licitacao", { limit: 100 });
      setModalidades(res.items.map(m => ({
        id: String(m.id),
        nome: String(m.nome),
        ativo: Boolean(m.ativo ?? true),
      })));
    } catch {
      // May not exist yet
    }
  }, []);

  const loadClasses = useCallback(async () => {
    try {
      const res = await crudList("classes-produtos", { limit: 500 });
      const items = res.items as unknown as ClasseProdutoAPI[];

      // Build hierarchical tree from flat list
      const classesTop = items.filter(i => i.tipo === "classe");
      const tree: Classe[] = classesTop.map(c => {
        const subs = items.filter(i => i.tipo === "subclasse" && String(i.classe_pai_id) === String(c.id));
        return {
          id: String(c.id),
          nome: c.nome,
          ncms: Array.isArray(c.ncms) ? c.ncms.join(", ") : String(c.ncms || ""),
          produtos: c.qtd_produtos || 0,
          subclasses: subs.map(s => ({
            id: String(s.id),
            nome: s.nome,
            ncms: Array.isArray(s.ncms) ? s.ncms.join(", ") : String(s.ncms || ""),
            produtos: s.qtd_produtos || 0,
            campos_mascara: Array.isArray(s.campos_mascara) ? s.campos_mascara as unknown as CampoMascara[] : null,
          })),
        };
      });
      setClasses(tree);
    } catch {
      // May not exist yet
    }
  }, []);

  // === Classes Tab Data Loaders ===
  const loadClassesTab = useCallback(async () => {
    setLoadingClassesTab(true);
    try {
      const [areasRes, classesRes, subclassesRes, prodRes] = await Promise.all([
        crudList("areas-produto", { limit: 200 }),
        crudList("classes-produto-v2", { limit: 500 }),
        crudList("subclasses-produto", { limit: 1000 }),
        crudList("produtos", { limit: 2000 }),
      ]);

      const areasRaw = areasRes.items;
      const classesRaw = classesRes.items;
      const subclassesRaw = subclassesRes.items;

      // Count products per subclasse
      const prodCountBySubclasse: Record<string, number> = {};
      const prodsWithoutClass: ProdutoSemClasse[] = [];
      for (const p of prodRes.items) {
        const sid = p.subclasse_id ? String(p.subclasse_id) : null;
        if (sid) {
          prodCountBySubclasse[sid] = (prodCountBySubclasse[sid] || 0) + 1;
        } else {
          prodsWithoutClass.push({
            id: String(p.id),
            nome: String(p.nome || ""),
            categoria: p.categoria ? String(p.categoria) : undefined,
            ncm: p.ncm ? String(p.ncm) : undefined,
          });
        }
      }
      setProdutosSemClasse(prodsWithoutClass);

      // Build tree: Area -> Classe -> Subclasse
      const tree: AreaProduto[] = areasRaw.map((a) => {
        const areaId = String(a.id);
        const areaClasses: ClasseV2[] = classesRaw
          .filter((c) => String(c.area_id) === areaId)
          .map((c) => {
            const classeId = String(c.id);
            const classeSubclasses: SubclasseV2[] = subclassesRaw
              .filter((s) => String(s.classe_id) === classeId)
              .map((s) => ({
                id: String(s.id),
                nome: String(s.nome || ""),
                ncms: Array.isArray(s.ncms) ? (s.ncms as string[]) : [],
                campos_mascara: Array.isArray(s.campos_mascara) ? (s.campos_mascara as unknown as CampoMascaraV2[]) : null,
                classe_id: classeId,
                qtd_produtos: prodCountBySubclasse[String(s.id)] || 0,
              }));
            return {
              id: classeId,
              nome: String(c.nome || ""),
              descricao: c.descricao ? String(c.descricao) : undefined,
              area_id: areaId,
              subclasses: classeSubclasses,
            };
          });
        return {
          id: areaId,
          nome: String(a.nome || ""),
          classes: areaClasses,
        };
      });

      setAreasTree(tree);
    } catch (err) {
      console.error("Erro ao carregar classes tab:", err);
    } finally {
      setLoadingClassesTab(false);
    }
  }, []);

  const handleGerarClassesIA = async (aplicar: boolean) => {
    const token = localStorage.getItem("token");
    if (aplicar) {
      setGerarIALoading(true);
    } else {
      setGerarIALoading(true);
      setGerarIAResult(null);
      setGerarIAError(null);
      setShowGerarIAModal(true);
    }
    try {
      const res = await fetch("/api/parametrizacoes/gerar-classes", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
        body: JSON.stringify({ aplicar }),
      });
      const data = await res.json();
      if (!res.ok) {
        setGerarIAError(data.error || "Erro ao gerar classes");
      } else {
        setGerarIAResult(data as GerarClassesResult);
        if (aplicar) {
          setShowGerarIAModal(false);
          await loadClassesTab();
        }
      }
    } catch (err) {
      setGerarIAError(err instanceof Error ? err.message : "Erro de rede");
    } finally {
      setGerarIALoading(false);
    }
  };

  const handleDeleteClassesItem = async (type: "area" | "classe" | "subclasse", id: string) => {
    if (!confirm(`Deseja realmente excluir este(a) ${type}?`)) return;
    const table = type === "area" ? "areas-produto" : type === "classe" ? "classes-produto-v2" : "subclasses-produto";
    try {
      await crudDelete(table, id);
      await loadClassesTab();
      if (selectedSubclasse?.id === id) setSelectedSubclasse(null);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Erro ao excluir");
    }
  };

  const handleCreateClassesItem = async (type: "area" | "classe" | "subclasse") => {
    if (!newItemNome.trim()) return;
    setSavingClassesItem(true);
    const table = type === "area" ? "areas-produto" : type === "classe" ? "classes-produto-v2" : "subclasses-produto";
    const payload: Record<string, unknown> = { nome: newItemNome.trim() };
    if (type === "classe") payload.area_id = newItemParentId;
    if (type === "subclasse") {
      payload.classe_id = newItemParentId;
      if (newItemNcms.trim()) payload.ncms = newItemNcms.split(",").map((n) => n.trim()).filter(Boolean);
    }
    try {
      await crudCreate(table, payload);
      setNewItemNome("");
      setNewItemParentId("");
      setNewItemNcms("");
      if (type === "area") setShowNewAreaModal(false);
      if (type === "classe") setShowNewClasseModal(false);
      if (type === "subclasse") setShowNewSubclasseModal(false);
      await loadClassesTab();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Erro ao criar");
    } finally {
      setSavingClassesItem(false);
    }
  };

  const handleEditClassesItem = async () => {
    if (!editingItem || !newItemNome.trim()) return;
    setSavingClassesItem(true);
    const table = editingItem.type === "area" ? "areas-produto" : editingItem.type === "classe" ? "classes-produto-v2" : "subclasses-produto";
    try {
      await crudUpdate(table, editingItem.id, { nome: newItemNome.trim() });
      setEditingItem(null);
      setNewItemNome("");
      await loadClassesTab();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Erro ao editar");
    } finally {
      setSavingClassesItem(false);
    }
  };

  const handleSaveSubclasseDetail = async () => {
    if (!selectedSubclasse) return;
    setSavingSubclasseDetail(true);
    try {
      const ncmsArr = editSubclasseNcms.split(",").map((n) => n.trim()).filter(Boolean);
      let camposParsed: CampoMascaraV2[] | null = null;
      if (editSubclasseCampos.trim()) {
        try {
          camposParsed = JSON.parse(editSubclasseCampos);
        } catch {
          alert("campos_mascara deve ser JSON valido. Ex: [{\"nome\":\"Campo1\",\"tipo\":\"texto\"}]");
          setSavingSubclasseDetail(false);
          return;
        }
      }
      await crudUpdate("subclasses-produto", selectedSubclasse.id, {
        nome: editSubclasseNome,
        ncms: ncmsArr,
        campos_mascara: camposParsed,
      });
      setSelectedSubclasse(null);
      await loadClassesTab();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Erro ao salvar subclasse");
    } finally {
      setSavingSubclasseDetail(false);
    }
  };

  const handleAplicarPortfolio = async () => {
    if (!aplicarSubclasseId || aplicarProdutoIds.size === 0) return;
    setSavingAplicar(true);
    try {
      const promises = Array.from(aplicarProdutoIds).map((pid) =>
        crudUpdate("produtos", pid, { subclasse_id: aplicarSubclasseId })
      );
      await Promise.all(promises);
      setShowAplicarModal(false);
      setAplicarProdutoIds(new Set());
      setAplicarAreaId("");
      setAplicarClasseId("");
      setAplicarSubclasseId("");
      await loadClassesTab();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Erro ao aplicar");
    } finally {
      setSavingAplicar(false);
    }
  };

  const toggleArea = (id: string) => {
    setExpandedAreas((prev) => {
      const n = new Set(prev);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  };

  const toggleClasseExpand = (id: string) => {
    setExpandedClasses((prev) => {
      const n = new Set(prev);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  };

  const loadParamScore = useCallback(async () => {
    try {
      setLoadingParamScore(true);
      const res = await crudList("parametros-score");
      if (res.items.length > 0) {
        const p = res.items[0] as unknown as ParametroScoreAPI;
        const id = String(p.id);
        setParamScoreId(id);
        setParamScore(p);

        // Populate local state from persisted data
        const estados = Array.isArray(p.estados_atuacao) ? p.estados_atuacao : [];
        setEstadosSelecionados(new Set(estados));
        setTodoBrasil(estados.length === 27);
        setPrazoMaximo(p.prazo_maximo != null ? String(p.prazo_maximo) : "");
        setFrequenciaMaxima(p.frequencia_maxima || "semanal");
        // obs 28: backend manda number; exibir mascarado pt-BR
        const numToMask = (n: unknown): string => {
          if (n == null || n === "" || Number(n) === 0) return "";
          const num = Number(n);
          if (isNaN(num)) return "";
          return num.toLocaleString("pt-BR", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
        };
        setTam(numToMask(p.tam));
        setSam(numToMask(p.sam));
        setSom(numToMask(p.som));
        // RF-014: Custos e Margens
        setMarkupPadrao(p.markup_padrao != null ? String(p.markup_padrao) : "");
        setCustosFixos(p.custos_fixos != null ? String(p.custos_fixos) : "");
        setFreteBase(p.frete_base != null ? String(p.frete_base) : "");
        const tipos = Array.isArray(p.tipos_edital) ? p.tipos_edital : [];
        setTiposEditalSelecionados(new Set(tipos));

        // Populate score weights
        if (p.peso_tecnico != null) setPesoTecnico(String(p.peso_tecnico));
        if (p.peso_comercial != null) setPesoComercial(String(p.peso_comercial));
        if (p.peso_documental != null) setPesoDocumental(String(p.peso_documental));
        if (p.peso_complexidade != null) setPesoComplexidade(String(p.peso_complexidade));
        if (p.peso_juridico != null) setPesoJuridico(String(p.peso_juridico));
        if (p.peso_logistico != null) setPesoLogistico(String(p.peso_logistico));
        // Limiares GO/NO-GO
        if (p.limiar_go != null) setLimiarGo(String(p.limiar_go));
        if (p.limiar_nogo != null) setLimiarNogo(String(p.limiar_nogo));
        if (p.limiar_tecnico_go != null) setLimiarTecnicoGo(String(p.limiar_tecnico_go));
        if (p.limiar_tecnico_nogo != null) setLimiarTecnicoNogo(String(p.limiar_tecnico_nogo));
        if (p.limiar_juridico_go != null) setLimiarJuridicoGo(String(p.limiar_juridico_go));
        if (p.limiar_juridico_nogo != null) setLimiarJuridicoNogo(String(p.limiar_juridico_nogo));

        // UC-F17: notificacoes e preferencias persistidas
        if (p.email_notificacao != null) setEmailNotif(String(p.email_notificacao));
        if (p.notif_email != null) setNotifEmail(Boolean(p.notif_email));
        if (p.notif_sistema != null) setNotifSistema(Boolean(p.notif_sistema));
        if (p.notif_sms != null) setNotifSms(Boolean(p.notif_sms));
        if (p.frequencia_resumo != null) setFrequenciaResumo(String(p.frequencia_resumo));
        if (p.tema != null) setTema(String(p.tema));
        if (p.idioma != null) setIdioma(String(p.idioma));
        if (p.fuso_horario != null) setFusoHorario(String(p.fuso_horario));
      }
    } catch {
      // May not exist yet
    } finally {
      setLoadingParamScore(false);
    }
  }, []);

  useEffect(() => {
    loadFontes();
    loadParametros();
    loadClasses();
    loadParamScore();
    loadModalidades();
    loadClassesTab();
  }, [loadFontes, loadParametros, loadClasses, loadParamScore, loadModalidades, loadClassesTab]);

  const handleToggleFonte = async (id: string) => {
    const fonte = fontes.find(f => f.id === id);
    if (!fonte) return;
    try {
      await crudUpdate("fontes-editais", id, { ativo: !fonte.ativo });
      setFontes(fontes.map(f => f.id === id ? { ...f, ativo: !f.ativo } : f));
    } catch (err) {
      setErrorFontes(err instanceof Error ? err.message : "Erro ao atualizar fonte");
    }
  };


  // Helper to ensure parametros-score record exists, returns the id
  const ensureParamScore = async (): Promise<string> => {
    if (paramScoreId) return paramScoreId;
    const created = await crudCreate("parametros-score", {
      estados_atuacao: [],
      prazo_maximo: 30,
      frequencia_maxima: "semanal",
      tam: 0,
      sam: 0,
      som: 0,
      tipos_edital: [],
      palavras_chave: [],
      ncms_busca: [],
    });
    const id = String(created.id);
    setParamScoreId(id);
    setParamScore(created as unknown as ParametroScoreAPI);
    return id;
  };

  // Save a partial update to parametros-score
  const saveParamScore = async (data: Record<string, unknown>) => {
    setSavingParamScore(true);
    setErroSave(null);
    try {
      const id = await ensureParamScore();
      await crudUpdate("parametros-score", id, data);
      setParamScore(prev => prev ? { ...prev, ...data } as ParametroScoreAPI : prev);
      setSalvoFeedback("Salvo!");
      setTimeout(() => setSalvoFeedback(null), 3000);
    } catch (err) {
      console.error("Erro ao salvar parametros-score:", err);
      setErroSave("Erro ao salvar. Verifique suas permissões.");
      setTimeout(() => setErroSave(null), 5000);
    } finally {
      setSavingParamScore(false);
    }
  };

  const toggleEstado = (uf: string) => {
    // obs 27 validador V8: permitir desmarcar UF individual mesmo apos
    // "Atuar em todo o Brasil" — sai do modo todoBrasil mantendo as demais.
    if (todoBrasil) {
      setTodoBrasil(false);
      const todasMenos = new Set(ESTADOS_BR.map(e => e.uf));
      todasMenos.delete(uf);
      setEstadosSelecionados(todasMenos);
      return;
    }
    setEstadosSelecionados(prev => {
      const newSet = new Set(prev);
      if (newSet.has(uf)) {
        newSet.delete(uf);
      } else {
        newSet.add(uf);
      }
      return newSet;
    });
  };

  const handleTodoBrasil = (checked: boolean) => {
    setTodoBrasil(checked);
    if (checked) {
      setEstadosSelecionados(new Set(ESTADOS_BR.map(e => e.uf)));
    } else {
      setEstadosSelecionados(new Set());
    }
  };

  // Save handlers for comercial tab
  const handleSalvarEstados = async () => {
    await saveParamScore({ estados_atuacao: Array.from(estadosSelecionados) });
  };

  const handleSalvarTempoEntrega = async () => {
    await saveParamScore({
      prazo_maximo: prazoMaximo ? Number(prazoMaximo) : 0,
      frequencia_maxima: frequenciaMaxima,
    });
  };

  const handleSalvarMercado = async () => {
    // obs 28: campos mascarados pt-BR -> converter para number no transito
    await saveParamScore({
      tam: toMoney(tam),
      sam: toMoney(sam),
      som: toMoney(som),
    });
  };

  // RF-014: Salvar custos e margens
  // toMoney: aceita "15.000,50" ou "15000.50" ou "15000,50" e devolve number
  const toMoney = (v: string): number => {
    if (!v) return 0;
    const cleaned = v.replace(/\./g, '').replace(',', '.');
    const n = Number(cleaned);
    return isNaN(n) ? 0 : n;
  };

  // obs 28 validador V8: mascara monetaria pt-BR enquanto digita.
  // Mantem so digitos + uma virgula decimal; agrupa milhar com ponto.
  // Entrada (usuario): "1234567" -> exibicao: "1.234.567"; "1234,5" -> "1.234,5".
  // Trânsito: usar toMoney(...) no save converte de volta para number.
  const maskMoedaInput = (v: string): string => {
    if (!v) return "";
    let s = v.replace(/[^\d,]/g, "");
    const firstComma = s.indexOf(",");
    if (firstComma !== -1) {
      // mantem apenas a primeira virgula
      s = s.slice(0, firstComma + 1) + s.slice(firstComma + 1).replace(/,/g, "");
    }
    const [intPart, decPart] = s.split(",");
    const intFmt = (intPart || "").replace(/^0+(?=\d)/, "").replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    if (s.indexOf(",") === -1) return intFmt;
    return `${intFmt || "0"},${(decPart || "").slice(0, 2)}`;
  };
  const handleSalvarCustos = async () => {
    await saveParamScore({
      markup_padrao: toMoney(markupPadrao),
      custos_fixos: toMoney(custosFixos),
      frete_base: toMoney(freteBase),
    });
  };

  const handleSalvarPesosScore = async () => {
    const pesos = {
      peso_tecnico: parseFloat(pesoTecnico) || 0,
      peso_comercial: parseFloat(pesoComercial) || 0,
      peso_documental: parseFloat(pesoDocumental) || 0,
      peso_complexidade: parseFloat(pesoComplexidade) || 0,
      peso_juridico: parseFloat(pesoJuridico) || 0,
      peso_logistico: parseFloat(pesoLogistico) || 0,
    };
    const soma = Object.values(pesos).reduce((a, b) => a + b, 0);
    if (Math.abs(soma - 1.0) > 0.01) {
      alert(`A soma dos pesos deve ser 1.00 (atual: ${soma.toFixed(2)}). Ajuste os valores antes de salvar.`);
      return;
    }
    await saveParamScore(pesos);
  };

  const handleSalvarLimiares = async () => {
    await saveParamScore({
      limiar_go: parseFloat(limiarGo) || 70,
      limiar_nogo: parseFloat(limiarNogo) || 40,
      limiar_tecnico_go: parseFloat(limiarTecnicoGo) || 60,
      limiar_tecnico_nogo: parseFloat(limiarTecnicoNogo) || 30,
      limiar_juridico_go: parseFloat(limiarJuridicoGo) || 60,
      limiar_juridico_nogo: parseFloat(limiarJuridicoNogo) || 30,
    });
  };

  const handleSalvarTiposEdital = async () => {
    await saveParamScore({ tipos_edital: Array.from(tiposEditalSelecionados) });
  };

  const toggleModalidade = (nome: string) => {
    setTiposEditalSelecionados(prev => {
      const newSet = new Set(prev);
      if (newSet.has(nome)) {
        newSet.delete(nome);
      } else {
        newSet.add(nome);
      }
      return newSet;
    });
  };

  const handleSalvarPalavrasChave = async () => {
    const palavras = palavrasText.split(",").map(p => p.trim()).filter(Boolean);
    await saveParamScore({ palavras_chave: palavras });
    setEditingPalavras(false);
  };

  const handleSalvarNcmsBusca = async () => {
    const ncms = ncmsText.split(",").map(n => n.trim()).filter(Boolean);
    await saveParamScore({ ncms_busca: ncms });
    setEditingNcms(false);
  };

  // R1: Salvar notificacoes
  const handleSalvarNotificacoes = async () => {
    try {
      await saveParamScore({
        email_notificacao: emailNotif,
        notif_email: notifEmail,
        notif_sistema: notifSistema,
        notif_sms: notifSms,
        frequencia_resumo: frequenciaResumo,
      });
      setNotifSalvas(true);
      setTimeout(() => setNotifSalvas(false), 3000);
    } catch (e) {
      console.error("Erro ao salvar notificacoes:", e);
    }
  };

  // R2: Salvar preferencias
  const handleSalvarPreferencias = async () => {
    try {
      await saveParamScore({
        tema: tema,
        idioma: idioma,
        fuso_horario: fusoHorario,
      });
      setPrefSalvas(true);
      setTimeout(() => setPrefSalvas(false), 3000);
    } catch (e) {
      console.error("Erro ao salvar preferencias:", e);
    }
  };

  // Soma dos pesos para validacao
  const somaPesos = parseFloat(pesoTecnico || "0") + parseFloat(pesoComercial || "0") +
    parseFloat(pesoDocumental || "0") + parseFloat(pesoComplexidade || "0") +
    parseFloat(pesoJuridico || "0") + parseFloat(pesoLogistico || "0");

  // Computed values for Classes tab stats
  const totalAreas = areasTree.length;
  const totalClasses = areasTree.reduce((s, a) => s + a.classes.length, 0);
  const totalProdutosSemClasse = produtosSemClasse.length;

  // Cascading selects for Aplicar modal
  const aplicarClasses = aplicarAreaId ? areasTree.find((a) => a.id === aplicarAreaId)?.classes || [] : [];
  const aplicarSubclasses = aplicarClasseId ? aplicarClasses.find((c) => c.id === aplicarClasseId)?.subclasses || [] : [];

  const tabs = [
    { id: "score", label: "Score", icon: <Settings size={16} /> },
    { id: "comercial", label: "Comercial", icon: <Globe size={16} /> },
    { id: "fontes", label: "Fontes de Busca", icon: <Globe size={16} /> },
    { id: "notificacoes", label: "Notificacoes", icon: <Bell size={16} /> },
    { id: "preferencias", label: "Preferencias", icon: <Palette size={16} /> },
    { id: "classes", label: "Classes", icon: <Layers size={16} /> },
  ];

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-left">
          <Settings size={24} />
          <div>
            <h1>Parametrizacoes</h1>
            <p>Configuracoes gerais do sistema</p>
          </div>
        </div>
      </div>

      {salvoFeedback && (
        <div style={{ position: "fixed", top: 16, right: 16, zIndex: 9999, background: "#16a34a", color: "#fff", padding: "10px 20px", borderRadius: 6, fontSize: "0.95rem", boxShadow: "0 4px 12px rgba(0,0,0,0.15)" }}>
          ✓ {salvoFeedback}
        </div>
      )}
      {erroSave && (
        <div style={{ position: "fixed", top: 16, right: 16, zIndex: 9999, background: "#dc2626", color: "#fff", padding: "10px 20px", borderRadius: 6, fontSize: "0.95rem", boxShadow: "0 4px 12px rgba(0,0,0,0.15)" }}>
          ✗ {erroSave}
        </div>
      )}

      <div className="page-content" ref={tabContainerRef}>
        <TabPanel tabs={tabs}>
          {(activeTab) => {
            switch (activeTab) {
              case "score":
                return (
                  <>
                    {loadingParamScore ? (
                      <div className="loading-center"><Loader2 size={20} className="spin" /><span>Carregando parametros de score...</span></div>
                    ) : (
                    <>
                    <Card title="Pesos das Dimensoes" subtitle="Pesos que ponderam cada dimensao no calculo do score final (devem somar 1.00)">
                      <div className="form-grid form-grid-2">
                        <FormField label="Peso Tecnico" hint="Aderencia tecnica do produto">
                          <TextInput value={pesoTecnico} onChange={(v) => setPesoTecnico(v)} type="number" placeholder="0.35" />
                        </FormField>
                        <FormField label="Peso Documental" hint="Regularidade documental e certidoes">
                          <TextInput value={pesoDocumental} onChange={(v) => setPesoDocumental(v)} type="number" placeholder="0.15" />
                        </FormField>
                        <FormField label="Peso Complexidade" hint="Complexidade tecnica do edital">
                          <TextInput value={pesoComplexidade} onChange={(v) => setPesoComplexidade(v)} type="number" placeholder="0.15" />
                        </FormField>
                        <FormField label="Peso Juridico" hint="Risco juridico e clausulas restritivas">
                          <TextInput value={pesoJuridico} onChange={(v) => setPesoJuridico(v)} type="number" placeholder="0.20" />
                        </FormField>
                        <FormField label="Peso Logistico" hint="Viabilidade logistica e prazo de entrega">
                          <TextInput value={pesoLogistico} onChange={(v) => setPesoLogistico(v)} type="number" placeholder="0.05" />
                        </FormField>
                        <FormField label="Peso Comercial" hint="Viabilidade comercial e preco">
                          <TextInput value={pesoComercial} onChange={(v) => setPesoComercial(v)} type="number" placeholder="0.10" />
                        </FormField>
                      </div>
                      <div style={{ marginTop: "8px", fontSize: "13px", color: somaPesos >= 0.99 && somaPesos <= 1.01 ? "#22c55e" : "#ef4444" }}>
                        Soma atual: {somaPesos.toFixed(2)} {somaPesos >= 0.99 && somaPesos <= 1.01 ? "" : "(deve ser 1.00)"}
                      </div>
                      <div className="form-actions" style={{ marginTop: "12px" }}>
                        <ActionButton label={savingParamScore ? "Salvando..." : "Salvar Pesos"} variant="primary" onClick={handleSalvarPesosScore} disabled={savingParamScore} />
                      </div>
                    </Card>

                    <Card title="Limiares de Decisao GO / NO-GO" subtitle="Defina os limiares para classificacao automatica dos editais">
                      <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                        <div>
                          <h4 style={{ margin: "0 0 8px", fontSize: "14px", color: "var(--text-secondary)" }}>Score Final</h4>
                          <div className="form-grid form-grid-2">
                            <FormField label="Minimo para GO" hint="Score final >= este valor para GO">
                              <TextInput value={limiarGo} onChange={(v) => setLimiarGo(v)} type="number" placeholder="70" />
                            </FormField>
                            <FormField label="Maximo para NO-GO" hint="Score final < este valor para NO-GO">
                              <TextInput value={limiarNogo} onChange={(v) => setLimiarNogo(v)} type="number" placeholder="40" />
                            </FormField>
                          </div>
                        </div>
                        <div>
                          <h4 style={{ margin: "0 0 8px", fontSize: "14px", color: "var(--text-secondary)" }}>Score Tecnico</h4>
                          <div className="form-grid form-grid-2">
                            <FormField label="Minimo para GO" hint="Score tecnico >= este valor para GO">
                              <TextInput value={limiarTecnicoGo} onChange={(v) => setLimiarTecnicoGo(v)} type="number" placeholder="60" />
                            </FormField>
                            <FormField label="Maximo para NO-GO" hint="Score tecnico < este valor para NO-GO">
                              <TextInput value={limiarTecnicoNogo} onChange={(v) => setLimiarTecnicoNogo(v)} type="number" placeholder="30" />
                            </FormField>
                          </div>
                        </div>
                        <div>
                          <h4 style={{ margin: "0 0 8px", fontSize: "14px", color: "var(--text-secondary)" }}>Score Juridico</h4>
                          <div className="form-grid form-grid-2">
                            <FormField label="Minimo para GO" hint="Score juridico >= este valor para GO">
                              <TextInput value={limiarJuridicoGo} onChange={(v) => setLimiarJuridicoGo(v)} type="number" placeholder="60" />
                            </FormField>
                            <FormField label="Maximo para NO-GO" hint="Score juridico < este valor para NO-GO">
                              <TextInput value={limiarJuridicoNogo} onChange={(v) => setLimiarJuridicoNogo(v)} type="number" placeholder="30" />
                            </FormField>
                          </div>
                        </div>
                      </div>
                      <div style={{ marginTop: "16px", padding: "12px", background: "var(--bg-secondary)", borderRadius: "8px", fontSize: "13px", lineHeight: "1.6" }}>
                        <strong>Regra atual:</strong><br />
                        GO: score_final &gt;= {limiarGo} E tecnico &gt;= {limiarTecnicoGo} E juridico &gt;= {limiarJuridicoGo}<br />
                        NO-GO: score_final &lt; {limiarNogo} OU tecnico &lt; {limiarTecnicoNogo} OU juridico &lt; {limiarJuridicoNogo}<br />
                        AVALIAR: demais casos
                      </div>
                      <div className="form-actions" style={{ marginTop: "12px" }}>
                        <ActionButton label={savingParamScore ? "Salvando..." : "Salvar Limiares"} variant="primary" onClick={handleSalvarLimiares} disabled={savingParamScore} />
                      </div>
                    </Card>
                    </>
                    )}
                  </>
                );

              case "comercial":
                return (
                  <>
                    {loadingParamScore ? (
                      <div className="loading-center"><Loader2 size={20} className="spin" /><span>Carregando parametros comerciais...</span></div>
                    ) : (
                    <>
                    <Card title="Regiao de Atuacao" icon={<MapPin size={18} />}>
                      <div className="regiao-atuacao">
                        <div className="regiao-header">
                          <Checkbox
                            checked={todoBrasil}
                            onChange={handleTodoBrasil}
                            label="Atuar em todo o Brasil"
                          />
                        </div>
                        <div className="estados-grid">
                          {ESTADOS_BR.map((estado) => (
                            <button
                              key={estado.uf}
                              className={`estado-btn ${(todoBrasil || estadosSelecionados.has(estado.uf)) ? "selected" : ""}`}
                              onClick={() => toggleEstado(estado.uf)}
                              title={todoBrasil ? `${estado.nome} — clique para excluir este estado` : estado.nome}
                            >
                              {estado.uf}
                            </button>
                          ))}
                        </div>
                        <div className="estados-resumo">
                          <strong>Estados selecionados:</strong> {estadosSelecionados.size === 27 ? "Todos (Brasil)" : Array.from(estadosSelecionados).join(", ")}
                        </div>
                        <div className="form-actions" style={{ marginTop: "12px" }}>
                          <ActionButton label={savingParamScore ? "Salvando..." : "Salvar Estados"} variant="primary" onClick={handleSalvarEstados} disabled={savingParamScore} />
                        </div>
                      </div>
                    </Card>

                    <Card title="Tempo de Entrega">
                      <div className="form-grid form-grid-2">
                        <FormField label="Prazo maximo aceito (dias)">
                          <TextInput value={prazoMaximo} onChange={(v) => setPrazoMaximo(v)} type="number" />
                        </FormField>
                        <FormField label="Frequencia maxima">
                          <SelectInput
                            value={frequenciaMaxima}
                            onChange={(v) => setFrequenciaMaxima(v)}
                            options={[
                              { value: "diaria", label: "Diaria" },
                              { value: "semanal", label: "Semanal" },
                              { value: "quinzenal", label: "Quinzenal" },
                              { value: "mensal", label: "Mensal" },
                            ]}
                          />
                        </FormField>
                      </div>
                      <div className="form-actions" style={{ marginTop: "12px" }}>
                        <ActionButton label={savingParamScore ? "Salvando..." : "Salvar Prazo/Frequencia"} variant="primary" onClick={handleSalvarTempoEntrega} disabled={savingParamScore} />
                      </div>
                    </Card>

                    <Card title="Mercado (TAM/SAM/SOM)">
                      <div className="form-grid form-grid-3">
                        <FormField label="TAM (Mercado Total)" hint="Editais/ano">
                          <TextInput value={tam} onChange={(v) => setTam(maskMoedaInput(v))} prefix="R$" placeholder="Ex: 1.500.000,00" />
                        </FormField>
                        <FormField label="SAM (Mercado Alcancavel)">
                          <TextInput value={sam} onChange={(v) => setSam(maskMoedaInput(v))} prefix="R$" placeholder="Ex: 800.000,00" />
                        </FormField>
                        <FormField label="SOM (Mercado Objetivo)">
                          <TextInput value={som} onChange={(v) => setSom(maskMoedaInput(v))} prefix="R$" placeholder="Ex: 250.000,00" />
                        </FormField>
                      </div>
                      <div className="form-actions" style={{ marginTop: "12px" }}>
                        <ActionButton label={savingParamScore ? "Salvando..." : "Salvar Mercado"} variant="primary" onClick={handleSalvarMercado} disabled={savingParamScore} />
                        <ActionButton icon={<Lock size={14} />} label="Calcular com IA (Onda 4)" onClick={() => {}} disabled />
                      </div>
                    </Card>

                    <Card title="Custos e Margens" icon={<DollarSign size={18} />}>
                      <div className="form-grid form-grid-3">
                        <FormField label="Markup Padrao (%)" hint="Percentual. Use ponto ou virgula. Ex: 30,5">
                          <TextInput value={markupPadrao} onChange={(v) => setMarkupPadrao(v.replace(/[^0-9.,]/g, ''))} placeholder="Ex: 30,5" />
                        </FormField>
                        <FormField label="Custos Fixos Mensais (R$)" hint="Use ponto ou virgula. Ex: 15000,50">
                          <TextInput value={custosFixos} onChange={(v) => setCustosFixos(v.replace(/[^0-9.,]/g, ''))} prefix="R$" placeholder="Ex: 15000,50" />
                        </FormField>
                        <FormField label="Frete Base (R$)" hint="Use ponto ou virgula. Ex: 500,00">
                          <TextInput value={freteBase} onChange={(v) => setFreteBase(v.replace(/[^0-9.,]/g, ''))} prefix="R$" placeholder="Ex: 500,00" />
                        </FormField>
                      </div>
                      <div className="form-actions" style={{ marginTop: "12px" }}>
                        <ActionButton label={savingParamScore ? "Salvando..." : "Salvar Custos"} variant="primary" onClick={handleSalvarCustos} disabled={savingParamScore} />
                      </div>
                    </Card>

                    <Card title="Modalidades de Licitacao Desejadas" subtitle="Selecione as modalidades em que a empresa deseja participar">
                      {modalidades.length === 0 ? (
                        <p className="text-muted" style={{ padding: 12, textAlign: "center", fontSize: 13 }}>
                          Nenhuma modalidade cadastrada.
                          <button style={{ marginLeft: 8, color: "var(--accent)", background: "none", border: "none", cursor: "pointer", textDecoration: "underline" }}
                            onClick={() => window.dispatchEvent(new CustomEvent("navigate-to", { detail: { page: "crud:modalidades-licitacao" } }))}>
                            Cadastrar Modalidades
                          </button>
                        </p>
                      ) : (
                        <div className="checkbox-grid">
                          {modalidades.filter(m => m.ativo).map(m => (
                            <Checkbox
                              key={m.id}
                              checked={tiposEditalSelecionados.has(m.nome)}
                              onChange={() => toggleModalidade(m.nome)}
                              label={m.nome}
                            />
                          ))}
                        </div>
                      )}
                      <div className="form-actions" style={{ marginTop: "12px" }}>
                        <ActionButton label={savingParamScore ? "Salvando..." : "Salvar Modalidades"} variant="primary" onClick={handleSalvarTiposEdital} disabled={savingParamScore} />
                      </div>
                    </Card>

                    {/* Pesos e Norteadores movidos para aba Score */}
                    </>
                    )}
                  </>
                );

              case "fontes":
                return (
                  <>
                    <Card
                      title="Fontes de Editais"
                      subtitle="Fontes ativas para busca de editais"
                      actions={
                        <ActionButton
                          icon={<Settings size={14} />}
                          label="Gerenciar Fontes"
                          variant="primary"
                          onClick={() => window.dispatchEvent(new CustomEvent("navigate-to", { detail: { page: "crud:fontes-editais" } }))}
                        />
                      }
                    >
                      {loadingFontes ? (
                        <div className="loading-center">
                          <Loader2 size={20} className="spin" />
                          <span>Carregando fontes...</span>
                        </div>
                      ) : fontes.length === 0 ? (
                        <p className="text-muted" style={{ padding: 12, textAlign: "center", fontSize: 13 }}>
                          Nenhuma fonte cadastrada. Use o botao acima para gerenciar fontes.
                        </p>
                      ) : (
                        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                          {fontes.map(f => (
                            <div key={f.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "8px 12px", background: "var(--bg-secondary)", borderRadius: 6 }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                                <span style={{ fontSize: 13, fontWeight: 500 }}>{f.nome}</span>
                                <span style={{ fontSize: 11, color: "var(--text-tertiary)" }}>{f.tipo.toUpperCase()}</span>
                              </div>
                              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <span className={`status-badge ${f.ativo ? "status-badge-success" : "status-badge-neutral"}`} style={{ fontSize: 11 }}>
                                  {f.ativo ? "Ativa" : "Inativa"}
                                </span>
                                <button
                                  title={f.ativo ? "Desativar" : "Ativar"}
                                  onClick={() => handleToggleFonte(f.id)}
                                  style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)", padding: 4 }}
                                >
                                  {f.ativo ? <Pause size={14} /> : <Play size={14} />}
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </Card>

                    <Card title="Palavras-chave de Busca">
                      <div className="palavras-chave">
                        <ActionButton icon={<Lock size={14} />} label="Gerar do portfolio (Onda 4)" onClick={() => {}} disabled />
                        {editingPalavras ? (
                          <div style={{ marginTop: "8px" }}>
                            <FormField label="Palavras-chave (separadas por virgula)">
                              <TextInput
                                value={palavrasText}
                                onChange={setPalavrasText}
                                placeholder="microscopio, centrifuga, autoclave"
                              />
                            </FormField>
                            <div className="form-actions" style={{ marginTop: "8px" }}>
                              <ActionButton label={savingParamScore ? "Salvando..." : "Salvar"} variant="primary" onClick={handleSalvarPalavrasChave} disabled={savingParamScore} />
                              <ActionButton label="Cancelar" onClick={() => setEditingPalavras(false)} />
                            </div>
                          </div>
                        ) : (
                          <div className="tags-container">
                            {(paramScore?.palavras_chave && paramScore.palavras_chave.length > 0)
                              ? paramScore.palavras_chave.map((p, i) => (
                                  <span key={i} className="tag">{p}</span>
                                ))
                              : <span className="text-muted" style={{ fontSize: "13px" }}>Nenhuma palavra-chave cadastrada</span>
                            }
                            <button className="tag tag-add" onClick={() => {
                              setPalavrasText(paramScore?.palavras_chave?.join(", ") || "");
                              setEditingPalavras(true);
                            }}>+ Editar</button>
                          </div>
                        )}
                      </div>
                    </Card>

                    <Card title="NCMs para Busca" subtitle="Extraidos automaticamente das classes/subclasses do portfolio">
                      <div className="ncms-busca">
                        <div className="ncms-actions">
                          <ActionButton
                            icon={<Lock size={14} />}
                            label="Sincronizar NCMs (Onda 4)"
                            onClick={() => {}}
                            disabled
                          />
                        </div>
                        {editingNcms ? (
                          <div style={{ marginTop: "8px" }}>
                            <FormField label="NCMs (separados por virgula)">
                              <TextInput
                                value={ncmsText}
                                onChange={setNcmsText}
                                placeholder="9011.10.00, 9011.20.00, 8421.19.10"
                              />
                            </FormField>
                            <div className="form-actions" style={{ marginTop: "8px" }}>
                              <ActionButton label={savingParamScore ? "Salvando..." : "Salvar"} variant="primary" onClick={handleSalvarNcmsBusca} disabled={savingParamScore} />
                              <ActionButton label="Cancelar" onClick={() => setEditingNcms(false)} />
                            </div>
                          </div>
                        ) : (
                          <div className="tags-container">
                            {(paramScore?.ncms_busca && paramScore.ncms_busca.length > 0)
                              ? paramScore.ncms_busca.map((n, i) => (
                                  <span key={i} className="tag">{n}</span>
                                ))
                              : <span className="text-muted" style={{ fontSize: "13px" }}>Nenhum NCM cadastrado</span>
                            }
                            <button className="tag tag-add" onClick={() => {
                              setNcmsText(paramScore?.ncms_busca?.join(", ") || "");
                              setEditingNcms(true);
                            }}>+ Adicionar NCM</button>
                          </div>
                        )}
                        <p className="text-muted" style={{ marginTop: "8px", fontSize: "12px" }}>
                          NCMs sao usados para busca direta no PNCP por codigo de produto
                        </p>
                      </div>
                    </Card>

                  </>
                );

              case "notificacoes":
                return (
                  <Card title="Configuracoes de Notificacao">
                    <FormField label="Email para notificacoes">
                      <TextInput value={emailNotif} onChange={setEmailNotif} type="email" />
                    </FormField>

                    <div className="form-section-title">Receber por</div>
                    <div className="checkbox-grid">
                      <Checkbox checked={notifEmail} onChange={setNotifEmail} label="Email" />
                      <Checkbox checked={notifSistema} onChange={setNotifSistema} label="Sistema" />
                      <Checkbox checked={notifSms} onChange={setNotifSms} label="SMS" />
                    </div>

                    <FormField label="Frequencia do resumo">
                      <SelectInput
                        value={frequenciaResumo}
                        onChange={setFrequenciaResumo}
                        options={[
                          { value: "imediato", label: "Imediato" },
                          { value: "diario", label: "Diario" },
                          { value: "semanal", label: "Semanal" },
                        ]}
                      />
                    </FormField>

                    <div className="form-actions">
                      <ActionButton label={savingParamScore ? "Salvando..." : "Salvar"} variant="primary" onClick={handleSalvarNotificacoes} disabled={savingParamScore} />
                      {notifSalvas && (
                        <span className="status-badge status-badge-success" style={{ marginLeft: "8px" }}>Salvo!</span>
                      )}
                    </div>
                  </Card>
                );

              case "preferencias":
                return (
                  <Card title="Preferencias do Sistema">
                    <FormField label="Tema">
                      <div className="radio-group">
                        <label className="radio-wrapper">
                          <input
                            type="radio"
                            checked={tema === "escuro"}
                            onChange={() => setTema("escuro")}
                          />
                          <span>Escuro</span>
                        </label>
                        <label className="radio-wrapper">
                          <input
                            type="radio"
                            checked={tema === "claro"}
                            onChange={() => setTema("claro")}
                          />
                          <span>Claro</span>
                        </label>
                      </div>
                    </FormField>

                    <FormField label="Idioma">
                      <SelectInput
                        value={idioma}
                        onChange={setIdioma}
                        options={[
                          { value: "pt-BR", label: "Portugues (Brasil)" },
                          { value: "en-US", label: "English (US)" },
                          { value: "es-ES", label: "Espanol" },
                        ]}
                      />
                    </FormField>

                    <FormField label="Fuso horario">
                      <SelectInput
                        value={fusoHorario}
                        onChange={setFusoHorario}
                        options={[
                          { value: "America/Sao_Paulo", label: "America/Sao_Paulo (GMT-3)" },
                          { value: "America/Manaus", label: "America/Manaus (GMT-4)" },
                          { value: "America/Belem", label: "America/Belem (GMT-3)" },
                        ]}
                      />
                    </FormField>

                    <div className="form-actions">
                      <ActionButton label={savingParamScore ? "Salvando..." : "Salvar"} variant="primary" onClick={handleSalvarPreferencias} disabled={savingParamScore} />
                      {prefSalvas && (
                        <span className="status-badge status-badge-success" style={{ marginLeft: "8px" }}>Salvo!</span>
                      )}
                    </div>
                  </Card>
                );

              case "classes":
                return (
                  <>
                    {loadingClassesTab ? (
                      <div className="loading-center"><Loader2 size={20} className="spin" /><span>Carregando hierarquia de classes...</span></div>
                    ) : (
                    <>
                    {/* Stat Cards */}
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "16px", marginBottom: "16px" }}>
                      <div style={{ padding: "20px", background: "var(--bg-secondary)", borderRadius: "12px", border: "1px solid var(--border-color)" }}>
                        <div style={{ fontSize: "12px", color: "var(--text-tertiary)", textTransform: "uppercase", fontWeight: 600, marginBottom: "4px" }}>Areas</div>
                        <div style={{ fontSize: "28px", fontWeight: 700, color: "var(--text-primary)" }}>{totalAreas}</div>
                      </div>
                      <div style={{ padding: "20px", background: "var(--bg-secondary)", borderRadius: "12px", border: "1px solid var(--border-color)" }}>
                        <div style={{ fontSize: "12px", color: "var(--text-tertiary)", textTransform: "uppercase", fontWeight: 600, marginBottom: "4px" }}>Classes</div>
                        <div style={{ fontSize: "28px", fontWeight: 700, color: "var(--text-primary)" }}>{totalClasses}</div>
                      </div>
                      <div style={{ padding: "20px", background: "var(--bg-secondary)", borderRadius: "12px", border: "1px solid var(--border-color)" }}>
                        <div style={{ fontSize: "12px", color: "var(--text-tertiary)", textTransform: "uppercase", fontWeight: 600, marginBottom: "4px" }}>Produtos sem Classe</div>
                        <div style={{ fontSize: "28px", fontWeight: 700, color: totalProdutosSemClasse > 0 ? "#ef4444" : "#22c55e" }}>{totalProdutosSemClasse}</div>
                      </div>
                    </div>

                    {/* Action Buttons */}
                    <div style={{ display: "flex", gap: "8px", marginBottom: "16px", flexWrap: "wrap" }}>
                      <ActionButton icon={<Plus size={14} />} label="Nova Area" variant="primary" onClick={() => { setNewItemNome(""); setShowNewAreaModal(true); }} />
                      <ActionButton icon={<Plus size={14} />} label="Nova Classe" onClick={() => { setNewItemNome(""); setNewItemParentId(""); setShowNewClasseModal(true); }} />
                      <ActionButton icon={<Plus size={14} />} label="Nova Subclasse" onClick={() => { setNewItemNome(""); setNewItemParentId(""); setNewItemNcms(""); setShowNewSubclasseModal(true); }} />
                      <ActionButton icon={<Cpu size={14} />} label="Gerar Classes via IA" onClick={() => handleGerarClassesIA(false)} />
                      <ActionButton icon={<Package size={14} />} label="Aplicar ao Portfolio" onClick={() => { setAplicarAreaId(""); setAplicarClasseId(""); setAplicarSubclasseId(""); setAplicarProdutoIds(new Set()); setShowAplicarModal(true); }} disabled={totalProdutosSemClasse === 0} />
                      <ActionButton icon={<RefreshCw size={14} />} label="Atualizar" onClick={loadClassesTab} />
                    </div>

                    {/* Tree + Detail layout */}
                    <div style={{ display: "grid", gridTemplateColumns: selectedSubclasse ? "1fr 380px" : "1fr", gap: "16px" }}>
                      {/* Tree View */}
                      <Card title="Hierarquia de Classes" icon={<FolderTree size={18} />}>
                        {areasTree.length === 0 ? (
                          <p className="text-muted" style={{ padding: 16, textAlign: "center", fontSize: 13 }}>
                            Nenhuma area cadastrada. Crie areas, classes e subclasses para organizar seu portfolio.
                          </p>
                        ) : (
                          <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                            {areasTree.map((area) => (
                              <div key={area.id}>
                                {/* Area row */}
                                <div style={{ display: "flex", alignItems: "center", gap: "6px", padding: "8px 8px", borderRadius: "6px", cursor: "pointer", background: expandedAreas.has(area.id) ? "var(--bg-secondary)" : "transparent" }} onClick={() => toggleArea(area.id)}>
                                  {expandedAreas.has(area.id) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                  <FolderTree size={14} style={{ color: "var(--accent)" }} />
                                  <span style={{ fontWeight: 600, fontSize: "14px", flex: 1 }}>{area.nome}</span>
                                  <span className="status-badge status-badge-neutral" style={{ fontSize: "11px" }}>{area.classes.length} classes</span>
                                  <button onClick={(e) => { e.stopPropagation(); setEditingItem({ type: "area", id: area.id, nome: area.nome }); setNewItemNome(area.nome); }} style={{ background: "none", border: "none", cursor: "pointer", padding: "2px", color: "var(--text-tertiary)" }} title="Editar"><Edit2 size={13} /></button>
                                  <button onClick={(e) => { e.stopPropagation(); handleDeleteClassesItem("area", area.id); }} style={{ background: "none", border: "none", cursor: "pointer", padding: "2px", color: "var(--text-tertiary)" }} title="Excluir"><Trash2 size={13} /></button>
                                </div>
                                {/* Classes under area */}
                                {expandedAreas.has(area.id) && area.classes.map((cls) => (
                                  <div key={cls.id} style={{ marginLeft: "24px" }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: "6px", padding: "6px 8px", borderRadius: "6px", cursor: "pointer", background: expandedClasses.has(cls.id) ? "var(--bg-tertiary, var(--bg-secondary))" : "transparent" }} onClick={() => toggleClasseExpand(cls.id)}>
                                      {expandedClasses.has(cls.id) ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                                      <Layers size={13} style={{ color: "#6366f1" }} />
                                      <span style={{ fontWeight: 500, fontSize: "13px", flex: 1 }}>{cls.nome}</span>
                                      <span className="status-badge status-badge-neutral" style={{ fontSize: "10px" }}>{cls.subclasses.length} sub</span>
                                      <button onClick={(e) => { e.stopPropagation(); setEditingItem({ type: "classe", id: cls.id, nome: cls.nome }); setNewItemNome(cls.nome); }} style={{ background: "none", border: "none", cursor: "pointer", padding: "2px", color: "var(--text-tertiary)" }} title="Editar"><Edit2 size={12} /></button>
                                      <button onClick={(e) => { e.stopPropagation(); handleDeleteClassesItem("classe", cls.id); }} style={{ background: "none", border: "none", cursor: "pointer", padding: "2px", color: "var(--text-tertiary)" }} title="Excluir"><Trash2 size={12} /></button>
                                    </div>
                                    {/* Subclasses under classe */}
                                    {expandedClasses.has(cls.id) && cls.subclasses.map((sub) => (
                                      <div key={sub.id} style={{ marginLeft: "24px", display: "flex", alignItems: "center", gap: "6px", padding: "5px 8px", borderRadius: "6px", cursor: "pointer", background: selectedSubclasse?.id === sub.id ? "var(--accent-bg, rgba(99,102,241,0.1))" : "transparent" }} onClick={() => {
                                        setSelectedSubclasse(sub);
                                        setSelectedSubclasseAreaNome(area.nome);
                                        setSelectedSubclasseClasseNome(cls.nome);
                                        setEditSubclasseNome(sub.nome);
                                        setEditSubclasseNcms(sub.ncms.join(", "));
                                        setEditSubclasseCampos(sub.campos_mascara ? JSON.stringify(sub.campos_mascara, null, 2) : "");
                                      }}>
                                        <Package size={12} style={{ color: "#22c55e" }} />
                                        <span style={{ fontSize: "13px", flex: 1 }}>{sub.nome}</span>
                                        <span className="status-badge status-badge-success" style={{ fontSize: "10px" }}>{sub.qtd_produtos} prod</span>
                                        <button onClick={(e) => { e.stopPropagation(); handleDeleteClassesItem("subclasse", sub.id); }} style={{ background: "none", border: "none", cursor: "pointer", padding: "2px", color: "var(--text-tertiary)" }} title="Excluir"><Trash2 size={12} /></button>
                                      </div>
                                    ))}
                                  </div>
                                ))}
                              </div>
                            ))}
                          </div>
                        )}
                      </Card>

                      {/* Detail Panel */}
                      {selectedSubclasse && (
                        <Card title="Detalhe da Subclasse" icon={<Package size={18} />} actions={
                          <button onClick={() => setSelectedSubclasse(null)} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-tertiary)" }}><X size={16} /></button>
                        }>
                          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                            <div style={{ fontSize: "11px", color: "var(--text-tertiary)" }}>
                              {selectedSubclasseAreaNome} &gt; {selectedSubclasseClasseNome}
                            </div>
                            <FormField label="Nome">
                              <TextInput value={editSubclasseNome} onChange={setEditSubclasseNome} />
                            </FormField>
                            <FormField label="NCMs (separados por virgula)">
                              <TextInput value={editSubclasseNcms} onChange={setEditSubclasseNcms} placeholder="9011.10.00, 9011.20.00" />
                            </FormField>
                            <FormField label="Classe Pai">
                              <TextInput value={selectedSubclasseClasseNome} onChange={() => {}} disabled />
                            </FormField>
                            <FormField label="campos_mascara (JSON)" hint="Array de objetos com nome e tipo">
                              <textarea
                                value={editSubclasseCampos}
                                onChange={(e) => setEditSubclasseCampos(e.target.value)}
                                style={{ width: "100%", minHeight: "100px", padding: "8px", borderRadius: "6px", border: "1px solid var(--border-color)", background: "var(--bg-secondary)", color: "var(--text-primary)", fontSize: "12px", fontFamily: "monospace", resize: "vertical" }}
                                placeholder='[{"nome": "Campo1", "tipo": "texto"}]'
                              />
                            </FormField>
                            <div style={{ fontSize: "12px", color: "var(--text-tertiary)" }}>
                              Produtos vinculados: {selectedSubclasse.qtd_produtos}
                            </div>
                            <div className="form-actions">
                              <ActionButton label={savingSubclasseDetail ? "Salvando..." : "Salvar"} variant="primary" onClick={handleSaveSubclasseDetail} disabled={savingSubclasseDetail} />
                            </div>
                          </div>
                        </Card>
                      )}
                    </div>

                    {/* === MODALS === */}

                    {/* New Area Modal */}
                    {showNewAreaModal && (
                      <div className="modal-overlay" onClick={() => setShowNewAreaModal(false)}>
                        <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "420px" }}>
                          <div className="modal-header"><h3>Nova Area</h3><button onClick={() => setShowNewAreaModal(false)} className="modal-close"><X size={18} /></button></div>
                          <div className="modal-body">
                            <FormField label="Nome da Area">
                              <TextInput value={newItemNome} onChange={setNewItemNome} placeholder="Ex: Equipamentos Laboratoriais" />
                            </FormField>
                          </div>
                          <div className="modal-footer">
                            <ActionButton label="Cancelar" onClick={() => setShowNewAreaModal(false)} />
                            <ActionButton label={savingClassesItem ? "Criando..." : "Criar"} variant="primary" onClick={() => handleCreateClassesItem("area")} disabled={savingClassesItem || !newItemNome.trim()} />
                          </div>
                        </div>
                      </div>
                    )}

                    {/* New Classe Modal */}
                    {showNewClasseModal && (
                      <div className="modal-overlay" onClick={() => setShowNewClasseModal(false)}>
                        <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "420px" }}>
                          <div className="modal-header"><h3>Nova Classe</h3><button onClick={() => setShowNewClasseModal(false)} className="modal-close"><X size={18} /></button></div>
                          <div className="modal-body">
                            <FormField label="Area">
                              <SelectInput value={newItemParentId} onChange={setNewItemParentId} options={[{ value: "", label: "Selecione a area..." }, ...areasTree.map((a) => ({ value: a.id, label: a.nome }))]} />
                            </FormField>
                            <FormField label="Nome da Classe">
                              <TextInput value={newItemNome} onChange={setNewItemNome} placeholder="Ex: Microscopios" />
                            </FormField>
                          </div>
                          <div className="modal-footer">
                            <ActionButton label="Cancelar" onClick={() => setShowNewClasseModal(false)} />
                            <ActionButton label={savingClassesItem ? "Criando..." : "Criar"} variant="primary" onClick={() => handleCreateClassesItem("classe")} disabled={savingClassesItem || !newItemNome.trim() || !newItemParentId} />
                          </div>
                        </div>
                      </div>
                    )}

                    {/* New Subclasse Modal */}
                    {showNewSubclasseModal && (
                      <div className="modal-overlay" onClick={() => setShowNewSubclasseModal(false)}>
                        <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "480px" }}>
                          <div className="modal-header"><h3>Nova Subclasse</h3><button onClick={() => setShowNewSubclasseModal(false)} className="modal-close"><X size={18} /></button></div>
                          <div className="modal-body">
                            <FormField label="Classe pai">
                              <SelectInput value={newItemParentId} onChange={setNewItemParentId} options={[{ value: "", label: "Selecione a classe..." }, ...areasTree.flatMap((a) => a.classes.map((c) => ({ value: c.id, label: `${a.nome} > ${c.nome}` })))]} />
                            </FormField>
                            <FormField label="Nome da Subclasse">
                              <TextInput value={newItemNome} onChange={setNewItemNome} placeholder="Ex: Microscopios Opticos" />
                            </FormField>
                            <FormField label="NCMs (separados por virgula)">
                              <TextInput value={newItemNcms} onChange={setNewItemNcms} placeholder="9011.10.00, 9011.20.00" />
                            </FormField>
                          </div>
                          <div className="modal-footer">
                            <ActionButton label="Cancelar" onClick={() => setShowNewSubclasseModal(false)} />
                            <ActionButton label={savingClassesItem ? "Criando..." : "Criar"} variant="primary" onClick={() => handleCreateClassesItem("subclasse")} disabled={savingClassesItem || !newItemNome.trim() || !newItemParentId} />
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Edit Item Modal */}
                    {editingItem && (
                      <div className="modal-overlay" onClick={() => setEditingItem(null)}>
                        <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "420px" }}>
                          <div className="modal-header"><h3>Editar {editingItem.type === "area" ? "Area" : editingItem.type === "classe" ? "Classe" : "Subclasse"}</h3><button onClick={() => setEditingItem(null)} className="modal-close"><X size={18} /></button></div>
                          <div className="modal-body">
                            <FormField label="Nome">
                              <TextInput value={newItemNome} onChange={setNewItemNome} />
                            </FormField>
                          </div>
                          <div className="modal-footer">
                            <ActionButton label="Cancelar" onClick={() => setEditingItem(null)} />
                            <ActionButton label={savingClassesItem ? "Salvando..." : "Salvar"} variant="primary" onClick={handleEditClassesItem} disabled={savingClassesItem || !newItemNome.trim()} />
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Gerar Classes IA Modal */}
                    {showGerarIAModal && (
                      <div className="modal-overlay" onClick={() => { if (!gerarIALoading) setShowGerarIAModal(false); }}>
                        <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "700px", maxHeight: "80vh", overflow: "auto" }}>
                          <div className="modal-header"><h3><Cpu size={18} style={{ marginRight: "8px" }} />Gerar Classes via IA</h3><button onClick={() => { if (!gerarIALoading) setShowGerarIAModal(false); }} className="modal-close"><X size={18} /></button></div>
                          <div className="modal-body">
                            {gerarIALoading && (
                              <div className="loading-center" style={{ padding: "40px" }}><Loader2 size={24} className="spin" /><span>Analisando produtos com DeepSeek...</span></div>
                            )}
                            {gerarIAError && (
                              <div style={{ padding: "16px", background: "#fef2f2", border: "1px solid #fecaca", borderRadius: "8px", color: "#dc2626", fontSize: "13px" }}>
                                <AlertTriangle size={16} style={{ marginRight: "6px", verticalAlign: "middle" }} />{gerarIAError}
                              </div>
                            )}
                            {gerarIAResult && !gerarIALoading && (
                              <div>
                                <p style={{ fontSize: "13px", color: "var(--text-secondary)", marginBottom: "12px" }}>
                                  IA sugeriu {gerarIAResult.areas?.length || 0} areas a partir de {gerarIAResult.total_produtos || 0} produtos.
                                </p>
                                {/* Preview tree */}
                                <div style={{ background: "var(--bg-secondary)", borderRadius: "8px", padding: "12px", maxHeight: "400px", overflow: "auto" }}>
                                  {(gerarIAResult.areas || []).map((area, ai) => (
                                    <div key={ai} style={{ marginBottom: "12px" }}>
                                      <div style={{ fontWeight: 600, fontSize: "14px", display: "flex", alignItems: "center", gap: "6px" }}><FolderTree size={14} style={{ color: "var(--accent)" }} />{area.nome}</div>
                                      {(area.classes || []).map((cls, ci) => (
                                        <div key={ci} style={{ marginLeft: "20px", marginTop: "6px" }}>
                                          <div style={{ fontWeight: 500, fontSize: "13px", display: "flex", alignItems: "center", gap: "6px" }}><Layers size={13} style={{ color: "#6366f1" }} />{cls.nome}</div>
                                          {cls.descricao && <div style={{ marginLeft: "19px", fontSize: "11px", color: "var(--text-tertiary)" }}>{cls.descricao}</div>}
                                          {(cls.subclasses || []).map((sub, si) => (
                                            <div key={si} style={{ marginLeft: "20px", marginTop: "4px", fontSize: "12px", display: "flex", alignItems: "center", gap: "6px" }}>
                                              <Package size={11} style={{ color: "#22c55e" }} />
                                              <span>{sub.nome}</span>
                                              {sub.ncm && <span className="status-badge status-badge-neutral" style={{ fontSize: "10px" }}>NCM: {sub.ncm}</span>}
                                              {sub.produtos_sugeridos && sub.produtos_sugeridos.length > 0 && <span className="status-badge status-badge-success" style={{ fontSize: "10px" }}>{sub.produtos_sugeridos.length} prod</span>}
                                            </div>
                                          ))}
                                        </div>
                                      ))}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                          {gerarIAResult && !gerarIALoading && (
                            <div className="modal-footer">
                              <ActionButton label="Cancelar" onClick={() => setShowGerarIAModal(false)} />
                              <ActionButton label={gerarIALoading ? "Aplicando..." : "Aceitar Tudo"} variant="primary" onClick={() => handleGerarClassesIA(true)} disabled={gerarIALoading || !gerarIAResult?.areas?.length} />
                            </div>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Aplicar ao Portfolio Modal */}
                    {showAplicarModal && (
                      <div className="modal-overlay" onClick={() => setShowAplicarModal(false)}>
                        <div className="modal-content" onClick={(e) => e.stopPropagation()} style={{ maxWidth: "600px", maxHeight: "80vh", overflow: "auto" }}>
                          <div className="modal-header"><h3><Package size={18} style={{ marginRight: "8px" }} />Aplicar ao Portfolio</h3><button onClick={() => setShowAplicarModal(false)} className="modal-close"><X size={18} /></button></div>
                          <div className="modal-body">
                            <p style={{ fontSize: "13px", color: "var(--text-secondary)", marginBottom: "12px" }}>
                              {produtosSemClasse.length} produto(s) sem classe. Selecione a classificacao e os produtos a vincular.
                            </p>
                            {/* Cascading selects */}
                            <div className="form-grid form-grid-3" style={{ marginBottom: "12px" }}>
                              <FormField label="Area">
                                <SelectInput value={aplicarAreaId} onChange={(v) => { setAplicarAreaId(v); setAplicarClasseId(""); setAplicarSubclasseId(""); }} options={[{ value: "", label: "Selecione..." }, ...areasTree.map((a) => ({ value: a.id, label: a.nome }))]} />
                              </FormField>
                              <FormField label="Classe">
                                <SelectInput value={aplicarClasseId} onChange={(v) => { setAplicarClasseId(v); setAplicarSubclasseId(""); }} options={[{ value: "", label: "Selecione..." }, ...aplicarClasses.map((c) => ({ value: c.id, label: c.nome }))]} />
                              </FormField>
                              <FormField label="Subclasse">
                                <SelectInput value={aplicarSubclasseId} onChange={setAplicarSubclasseId} options={[{ value: "", label: "Selecione..." }, ...aplicarSubclasses.map((s) => ({ value: s.id, label: s.nome }))]} />
                              </FormField>
                            </div>
                            {/* Product list with checkboxes */}
                            <div style={{ border: "1px solid var(--border-color)", borderRadius: "8px", maxHeight: "300px", overflow: "auto" }}>
                              <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--border-color)", background: "var(--bg-secondary)", display: "flex", alignItems: "center", gap: "8px" }}>
                                <Checkbox checked={aplicarProdutoIds.size === produtosSemClasse.length && produtosSemClasse.length > 0} onChange={(checked) => { if (checked) { setAplicarProdutoIds(new Set(produtosSemClasse.map((p) => p.id))); } else { setAplicarProdutoIds(new Set()); } }} label={`Selecionar todos (${produtosSemClasse.length})`} />
                              </div>
                              {produtosSemClasse.map((p) => (
                                <div key={p.id} style={{ padding: "6px 12px", borderBottom: "1px solid var(--border-color)", display: "flex", alignItems: "center", gap: "8px", fontSize: "13px" }}>
                                  <Checkbox checked={aplicarProdutoIds.has(p.id)} onChange={(checked) => {
                                    setAplicarProdutoIds((prev) => {
                                      const n = new Set(prev);
                                      checked ? n.add(p.id) : n.delete(p.id);
                                      return n;
                                    });
                                  }} label="" />
                                  <span style={{ flex: 1 }}>{p.nome}</span>
                                  {p.categoria && <span className="status-badge status-badge-neutral" style={{ fontSize: "10px" }}>{p.categoria}</span>}
                                  {p.ncm && <span style={{ fontSize: "11px", color: "var(--text-tertiary)" }}>NCM: {p.ncm}</span>}
                                </div>
                              ))}
                            </div>
                          </div>
                          <div className="modal-footer">
                            <ActionButton label="Cancelar" onClick={() => setShowAplicarModal(false)} />
                            <ActionButton label={savingAplicar ? "Salvando..." : `Vincular ${aplicarProdutoIds.size} produto(s)`} variant="primary" onClick={handleAplicarPortfolio} disabled={savingAplicar || !aplicarSubclasseId || aplicarProdutoIds.size === 0} />
                          </div>
                        </div>
                      </div>
                    )}

                    </>
                    )}
                  </>
                );

              default:
                return null;
            }
          }}
        </TabPanel>
      </div>
    </div>
  );
}
