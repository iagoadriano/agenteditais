import { useState, useEffect, useRef, useCallback } from "react";
import type { PageProps } from "../types";
import {
  FileEdit, Eye, Download, Trash2, Send, Lightbulb, Bold, Italic,
  Heading1, Heading2, List, Table, ToggleLeft, ToggleRight,
  AlertTriangle, CheckCircle, Shield, FileCheck,
  Loader2, Scissors, Archive,
} from "lucide-react";
import {
  Card, DataTable, ActionButton, FilterBar, Modal, FormField,
  TextInput, SelectInput,
} from "../components/common";
import type { Column } from "../components/common";
import { crudList, crudCreate, crudUpdate, crudDelete } from "../api/crud";
import { getEditais, getProdutos } from "../api/client";
import type { Edital, Produto } from "../api/client";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Proposta {
  id: string;
  edital: string;
  edital_id: string;
  orgao: string;
  produto: string;
  produto_id: string;
  lote_id: string;
  template_id: string;
  precoUnitario: number;
  quantidade: number;
  valorTotal: number;
  dataCriacao: string;
  status: "rascunho" | "revisao" | "aprovada" | "enviada";
  conteudo?: string;
}

interface LoteOption {
  id: string;
  numero_lote: number;
  nome: string;
}

interface TemplateOption {
  id: string;
  nome: string;
  conteudo_md: string;
}

interface AnvisaItem {
  produto: string;
  registro: string;
  validade: string;
  status: "valido" | "vencido" | "proximo_vencimento";
}

interface DocItem {
  nome: string;
  tamanho_kb: number;
  status: "presente" | "ausente" | "vencido";
  path?: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function mapCrudToProposta(item: Record<string, unknown>): Proposta {
  const precoUnitario = Number(item.preco_unitario ?? item.precoUnitario ?? 0);
  const quantidade = Number(item.quantidade ?? 1);
  return {
    id: String(item.id ?? ""),
    edital: String(item.numero_edital ?? item.edital ?? ""),
    edital_id: String(item.edital_id ?? ""),
    orgao: String(item.orgao ?? ""),
    produto: String(item.nome_produto ?? item.produto ?? ""),
    produto_id: String(item.produto_id ?? ""),
    lote_id: String(item.lote_id ?? ""),
    template_id: String(item.template_id ?? ""),
    precoUnitario,
    quantidade,
    valorTotal: Number(item.preco_total ?? item.valorTotal ?? precoUnitario * quantidade),
    dataCriacao: String(item.created_at ?? item.dataCriacao ?? "").split("T")[0],
    status: (["rascunho", "revisao", "aprovada", "enviada"].includes(String(item.status))
      ? item.status
      : "rascunho") as Proposta["status"],
    conteudo: item.texto_tecnico ? String(item.texto_tecnico) : undefined,
  };
}

const formatCurrency = (value: number) =>
  new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);

const STATUS_COLORS: Record<string, string> = {
  rascunho: "neutral",
  revisao: "warning",
  aprovada: "success",
  enviada: "info",
};

const STATUS_LABELS: Record<string, string> = {
  rascunho: "Rascunho",
  revisao: "Em Revisao",
  aprovada: "Aprovada",
  enviada: "Enviada",
};

// ─── Markdown Toolbar ─────────────────────────────────────────────────────────

function MarkdownToolbar({ textareaRef }: { textareaRef: React.RefObject<HTMLTextAreaElement | null> }) {
  const insert = (before: string, after = "") => {
    const ta = textareaRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const selected = ta.value.substring(start, end);
    const replacement = `${before}${selected || "texto"}${after}`;
    const newValue = ta.value.substring(0, start) + replacement + ta.value.substring(end);
    // We need to trigger React's onChange manually
    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, "value"
    )?.set;
    nativeInputValueSetter?.call(ta, newValue);
    ta.dispatchEvent(new Event("input", { bubbles: true }));
    ta.focus();
    ta.setSelectionRange(start + before.length, start + before.length + (selected || "texto").length);
  };

  const buttons = [
    { icon: <Bold size={14} />, title: "Negrito", action: () => insert("**", "**") },
    { icon: <Italic size={14} />, title: "Italico", action: () => insert("*", "*") },
    { icon: <Heading1 size={14} />, title: "Titulo H1", action: () => insert("# ") },
    { icon: <Heading2 size={14} />, title: "Titulo H2", action: () => insert("## ") },
    { icon: <List size={14} />, title: "Lista", action: () => insert("- ") },
    { icon: <Table size={14} />, title: "Tabela", action: () => insert("| Col1 | Col2 |\n|------|------|\n| ", " |  |\n") },
  ];

  return (
    <div className="markdown-toolbar" style={{ display: "flex", gap: 4, marginBottom: 6, flexWrap: "wrap" }}>
      {buttons.map((btn, i) => (
        <button
          key={i}
          type="button"
          className="btn btn-secondary btn-sm"
          title={btn.title}
          onClick={btn.action}
          style={{ padding: "4px 8px", display: "flex", alignItems: "center" }}
        >
          {btn.icon}
        </button>
      ))}
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export function PropostaPage(props?: PageProps) {
  const { onSendToChat } = props ?? {};

  // --- State: Lista ---
  const [propostas, setPropostas] = useState<Proposta[]>([]);
  const [loadingLista, setLoadingLista] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState("todas");
  const [selectedProposta, setSelectedProposta] = useState<Proposta | null>(null);
  const [showGerarModal, setShowGerarModal] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadLoading, setUploadLoading] = useState(false);
  const [loading, setLoading] = useState(false);

  // --- State: Listas para selects ---
  const [editais, setEditais] = useState<Edital[]>([]);
  const [produtos, setProdutos] = useState<Produto[]>([]);
  const [lotes, setLotes] = useState<LoteOption[]>([]);
  const [templates, setTemplates] = useState<TemplateOption[]>([]);

  // --- State: Formulario nova proposta ---
  const [novoEdital, setNovoEdital] = useState("");
  const [novoProduto, setNovoProduto] = useState("");
  const [novoPreco, setNovoPreco] = useState("");
  const [novaQuantidade, setNovaQuantidade] = useState("");
  const [novoLote, setNovoLote] = useState("");
  const [novoTemplate, setNovoTemplate] = useState("");
  const [precoSugerido, setPrecoSugerido] = useState<number | null>(null);

  // --- State: Editor rico ---
  const [editorContent, setEditorContent] = useState("");
  const [editorDirty, setEditorDirty] = useState(false);
  const editorRef = useRef<HTMLTextAreaElement>(null);

  // --- State: Descricao Tecnica A/B ---
  const [descMode, setDescMode] = useState<"edital" | "personalizado">("edital");
  const [descPersonalizado, setDescPersonalizado] = useState("");

  // --- State: Auditoria ANVISA ---
  const [anvisaItems, setAnvisaItems] = useState<AnvisaItem[]>([]);
  const [loadingAnvisa, setLoadingAnvisa] = useState(false);
  const [anvisaChecked, setAnvisaChecked] = useState(false);

  // --- State: Auditoria Documental ---
  const [docItems, setDocItems] = useState<DocItem[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [docsChecked, setDocsChecked] = useState(false);
  const [splittingDoc, setSplittingDoc] = useState<string | null>(null);

  // --- State: Status flow ---
  const [updatingStatus, setUpdatingStatus] = useState(false);

  // --- Filtered list ---
  const filteredPropostas = propostas.filter((p) => {
    const matchSearch =
      p.edital.toLowerCase().includes(searchTerm.toLowerCase()) ||
      p.produto.toLowerCase().includes(searchTerm.toLowerCase());
    const matchStatus = statusFilter === "todas" || p.status === statusFilter;
    return matchSearch && matchStatus;
  });

  // ─── Load data on mount ──────────────────────────────────────────────────────

  useEffect(() => {
    const loadData = async () => {
      setLoadingLista(true);
      try {
        const res = await crudList("propostas", { limit: 100 });
        setPropostas(res.items.map(mapCrudToProposta));
      } catch {
        setPropostas([]);
      } finally {
        setLoadingLista(false);
      }

      try {
        // Carregar editais de qualquer status (não só "salvo")
        const editaisSalvos = await getEditais("salvo");
        if (editaisSalvos.length > 0) {
          setEditais(editaisSalvos);
        } else {
          // Fallback: carregar todos os editais
          setEditais(await getEditais());
        }
      } catch {
        setEditais([]);
      }

      try {
        setProdutos(await getProdutos());
      } catch {
        setProdutos([]);
      }

      try {
        const tplRes = await crudList("proposta-templates", { limit: 100 });
        setTemplates(
          tplRes.items.map((t) => ({
            id: String(t.id),
            nome: String(t.nome ?? ""),
            conteudo_md: String(t.conteudo_md ?? ""),
          }))
        );
      } catch {
        setTemplates([]);
      }
    };
    loadData();
  }, []);

  // ─── Load lotes when edital changes ──────────────────────────────────────────

  useEffect(() => {
    if (!novoEdital) {
      setLotes([]);
      setNovoLote("");
      return;
    }
    const edital = editais.find((e) => e.id === novoEdital || e.numero === novoEdital);
    const editalId = edital?.id ?? novoEdital;

    (async () => {
      try {
        const res = await crudList("lotes", { parent_id: editalId, limit: 100 });
        setLotes(
          res.items.map((l) => ({
            id: String(l.id),
            numero_lote: Number(l.numero_lote ?? 0),
            nome: String(l.nome ?? l.descricao ?? `Lote ${l.numero_lote}`),
          }))
        );
      } catch {
        setLotes([]);
      }
    })();

    // Pre-fill preco from PrecoCamada
    (async () => {
      try {
        const res = await crudList("edital-item-produto", { parent_id: editalId, limit: 50 });
        const vinculos = res.items;
        if (vinculos.length > 0) {
          const vinculo = vinculos[0];
          const vinculoId = String(vinculo.id);
          // Try to get preco camada
          try {
            const pcRes = await crudList("preco-camada", { parent_id: vinculoId, limit: 1 });
            if (pcRes.items.length > 0) {
              const pc = pcRes.items[0];
              const lance = Number(pc.lance_inicial ?? 0);
              if (lance > 0 && !novoPreco) {
                setNovoPreco(String(lance));
                setPrecoSugerido(lance);
              }
            }
          } catch { /* ignore */ }
          // Pre-fill quantidade
          const qtd = Number(vinculo.quantidade_kits ?? vinculo.volume_edital ?? 0);
          if (qtd > 0 && !novaQuantidade) {
            setNovaQuantidade(String(qtd));
          }
        }
      } catch { /* ignore */ }
    })();
  }, [novoEdital]); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── When proposta is selected, populate editor ──────────────────────────────

  useEffect(() => {
    if (selectedProposta) {
      setEditorContent(selectedProposta.conteudo ?? "");
      setEditorDirty(false);
      setAnvisaItems([]);
      setAnvisaChecked(false);
      setDocItems([]);
      setDocsChecked(false);
      setDescMode("edital");
      setDescPersonalizado("");
    }
  }, [selectedProposta?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // ─── Handlers ────────────────────────────────────────────────────────────────

  const handleSugerirPreco = async () => {
    const edital = editais.find((e) => e.id === novoEdital || e.numero === novoEdital);
    const produto = produtos.find((p) => p.id === novoProduto || p.nome === novoProduto);
    const editalDesc = edital ? `${edital.numero} - ${edital.orgao}` : novoEdital;
    const produtoDesc = produto ? produto.nome : novoProduto;

    if (onSendToChat && (editalDesc || produtoDesc)) {
      onSendToChat(
        `Sugira um preco unitario competitivo para:\n` +
        `- Edital: ${editalDesc || "(nao selecionado)"}\n` +
        `- Produto: ${produtoDesc || "(nao selecionado)"}\n` +
        `Retorne somente o valor numerico recomendado com justificativa breve.`
      );
    }

    try {
      const res = await crudList("preco-historico", { q: produtoDesc, limit: 20 });
      const items = res.items as Record<string, unknown>[];
      if (items.length > 0) {
        const precos = items.map((i) => Number(i.preco ?? i.preco_ofertado ?? 0)).filter((v) => v > 0);
        if (precos.length > 0) {
          const media = precos.reduce((a, b) => a + b, 0) / precos.length;
          setPrecoSugerido(Math.round(media * 0.95));
        }
      }
    } catch {
      // apenas via IA
    }
  };

  const handleGerarProposta = async () => {
    if (!novoEdital || !novoProduto || !novoPreco || !novaQuantidade) return;
    setLoading(true);

    const edital = editais.find((e) => e.id === novoEdital || e.numero === novoEdital);
    const produto = produtos.find((p) => p.id === novoProduto || p.nome === novoProduto);
    const editalDesc = edital ? `${edital.numero} - ${edital.orgao}` : novoEdital;
    const produtoDesc = produto ? produto.nome : novoProduto;
    const preco = Number(novoPreco);
    const qtd = Number(novaQuantidade);

    try {
      const data: Record<string, unknown> = {
        numero_edital: edital?.numero ?? novoEdital,
        orgao: edital?.orgao ?? "",
        nome_produto: produtoDesc,
        preco_unitario: preco,
        quantidade: qtd,
        preco_total: preco * qtd,
        status: "rascunho",
      };
      if (edital?.id) data.edital_id = edital.id;
      if (produto?.id) data.produto_id = produto.id;
      if (novoLote) data.lote_id = novoLote;
      if (novoTemplate) {
        data.template_id = novoTemplate;
        const tpl = templates.find((t) => t.id === novoTemplate);
        if (tpl?.conteudo_md) data.texto_tecnico = tpl.conteudo_md;
      }

      const created = await crudCreate("propostas", data);
      const novaProposta = mapCrudToProposta(created);

      // Gerar texto com IA direto (sem abrir chat)
      try {
        const loteInfo = novoLote ? ` do Lote ${lotes.find((l) => l.id === novoLote)?.nome ?? ""}` : "";
        const tpl = novoTemplate ? templates.find((t) => t.id === novoTemplate) : null;
        const templateInfo = tpl?.conteudo_md ? `\n\nUSE O SEGUINTE TEMPLATE COMO BASE:\n${tpl.conteudo_md}` : "";
        const prompt = `Gere uma proposta tecnica completa para:\n- Edital: ${editalDesc}\n- Produto: ${produtoDesc}${loteInfo}\n- Preco Unitario: R$ ${preco.toFixed(2)}\n- Quantidade: ${qtd}\n- Valor Total: R$ ${(preco * qtd).toFixed(2)}\n\nInclua: identificacao da empresa, objeto, especificacoes tecnicas do produto, analise de conformidade com o edital, condicoes comerciais, prazo de entrega e validade da proposta.${templateInfo}`;

        const token = localStorage.getItem("editais_ia_access_token");
        const res = await fetch("/api/precificacao/simular-ia", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: token ? `Bearer ${token}` : "" },
          body: JSON.stringify({ prompt }),
        });
        const iaResult = await res.json();
        if (iaResult.success && iaResult.response) {
          // Salvar texto gerado na proposta
          await crudUpdate("propostas", novaProposta.id, { texto_tecnico: iaResult.response });
          novaProposta.conteudo = iaResult.response;
        }
      } catch (iaErr) {
        console.error("[GERAR PROPOSTA IA]", iaErr);
        // Proposta criada mas sem texto IA — usuário pode editar manualmente
      }

      setPropostas([novaProposta, ...propostas]);
      setSelectedProposta(novaProposta);
      setEditorContent(novaProposta.conteudo || "");

      setShowGerarModal(false);
      setNovoEdital("");
      setNovoProduto("");
      setNovoPreco("");
      setNovaQuantidade("");
      setNovoLote("");
      setNovoTemplate("");
      setPrecoSugerido(null);
    } catch (err) {
      console.error("Erro ao criar proposta:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleExcluirProposta = async (id: string) => {
    try {
      await crudDelete("propostas", id);
      setPropostas(propostas.filter((p) => p.id !== id));
      if (selectedProposta?.id === id) {
        setSelectedProposta(null);
      }
    } catch (err) {
      console.error("Erro ao excluir proposta:", err);
    }
  };

  const handleBaixarProposta = (proposta: Proposta, formato: "docx" | "pdf") => {
    const token = localStorage.getItem("editais_ia_access_token");
    const url = `/api/propostas/${proposta.id}/export?formato=${formato}`;
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => {
        if (!res.ok) throw new Error("Erro ao baixar");
        return res.blob();
      })
      .then((blob) => {
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `proposta-${proposta.edital}.${formato}`;
        link.click();
      })
      .catch(() => {
        if (onSendToChat) {
          onSendToChat(`Exporte a proposta ${proposta.edital} no formato ${formato.toUpperCase()}.`);
        }
      });
  };

  const handleBaixarDossie = (proposta: Proposta) => {
    const token = localStorage.getItem("editais_ia_access_token");
    const url = `/api/propostas/${proposta.id}/dossie`;
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then((res) => {
        if (!res.ok) throw new Error("Erro ao baixar dossie");
        return res.blob();
      })
      .then((blob) => {
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `dossie-${proposta.edital}.zip`;
        link.click();
      })
      .catch(() => {
        if (onSendToChat) {
          onSendToChat(`Exporte o dossie completo da proposta ${proposta.edital}.`);
        }
      });
  };

  // --- Status flow ---
  const handleStatusChange = useCallback(async (newStatus: Proposta["status"]) => {
    if (!selectedProposta) return;
    setUpdatingStatus(true);
    try {
      await crudUpdate("propostas", selectedProposta.id, { status: newStatus });
      const updated = { ...selectedProposta, status: newStatus };
      setSelectedProposta(updated);
      setPropostas((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
    } catch (err) {
      console.error("Erro ao atualizar status:", err);
    } finally {
      setUpdatingStatus(false);
    }
  }, [selectedProposta]);

  // --- Save editor content ---
  const handleSaveContent = useCallback(async () => {
    if (!selectedProposta || !editorDirty) return;
    try {
      await crudUpdate("propostas", selectedProposta.id, { texto_tecnico: editorContent });
      const updated = { ...selectedProposta, conteudo: editorContent };
      setSelectedProposta(updated);
      setPropostas((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
      setEditorDirty(false);
    } catch (err) {
      console.error("Erro ao salvar conteudo:", err);
    }
  }, [selectedProposta, editorContent, editorDirty]);

  // --- Auditoria ANVISA ---
  const handleVerificarAnvisa = useCallback(async () => {
    if (!selectedProposta) return;
    setLoadingAnvisa(true);
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      const res = await fetch(`/api/propostas/${selectedProposta.id}/anvisa`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Erro");
      const data = await res.json();
      const items: AnvisaItem[] = Array.isArray(data.registros)
        ? data.registros.map((r: Record<string, unknown>) => ({
            produto: String(r.produto ?? r.nome ?? ""),
            registro: String(r.registro ?? r.numero ?? ""),
            validade: String(r.validade ?? r.data_validade ?? ""),
            status: (["valido", "vencido", "proximo_vencimento"].includes(String(r.status))
              ? r.status
              : "valido") as AnvisaItem["status"],
          }))
        : [];
      setAnvisaItems(items);
      setAnvisaChecked(true);

      // Alert for expired
      const vencidos = items.filter((i) => i.status === "vencido");
      if (vencidos.length > 0) {
        alert(
          `ATENCAO: ${vencidos.length} registro(s) ANVISA vencido(s)!\n` +
          vencidos.map((v) => `- ${v.produto}: ${v.registro}`).join("\n") +
          `\n\nA proposta nao pode ser enviada com registros vencidos.`
        );
      }
    } catch {
      setAnvisaItems([]);
      setAnvisaChecked(true);
      if (onSendToChat) {
        onSendToChat(`Verifique registros ANVISA da proposta ${selectedProposta.id}`);
      }
    } finally {
      setLoadingAnvisa(false);
    }
  }, [selectedProposta, onSendToChat]);

  // --- Auditoria Documental ---
  const handleVerificarDocs = useCallback(async () => {
    if (!selectedProposta) return;
    setLoadingDocs(true);
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      const res = await fetch(`/api/propostas/${selectedProposta.id}/documentos`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Erro");
      const data = await res.json();
      const items: DocItem[] = Array.isArray(data.documentos)
        ? data.documentos.map((d: Record<string, unknown>) => ({
            nome: String(d.nome ?? d.nome_arquivo ?? ""),
            tamanho_kb: Number(d.tamanho_kb ?? d.tamanho ?? 0),
            status: (["presente", "ausente", "vencido"].includes(String(d.status))
              ? d.status
              : "ausente") as DocItem["status"],
            path: d.path ? String(d.path) : undefined,
          }))
        : [];
      setDocItems(items);
      setDocsChecked(true);
    } catch {
      setDocItems([]);
      setDocsChecked(true);
      if (onSendToChat) {
        onSendToChat(`Faca auditoria documental da proposta ${selectedProposta.id}`);
      }
    } finally {
      setLoadingDocs(false);
    }
  }, [selectedProposta, onSendToChat]);

  // --- Fracionar documento > 25MB ---
  const handleFracionarDoc = useCallback(async (docNome: string) => {
    if (!selectedProposta) return;
    setSplittingDoc(docNome);
    try {
      const token = localStorage.getItem("editais_ia_access_token");
      const res = await fetch(`/api/propostas/${selectedProposta.id}/smart-split`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ documento: docNome }),
      });
      if (!res.ok) throw new Error("Erro ao fracionar");
      // Refresh doc list
      await handleVerificarDocs();
    } catch {
      if (onSendToChat) {
        onSendToChat(`Fracione o documento "${docNome}" da proposta ${selectedProposta.id}`);
      }
    } finally {
      setSplittingDoc(null);
    }
  }, [selectedProposta, handleVerificarDocs, onSendToChat]);

  // ─── Badge helpers ───────────────────────────────────────────────────────────

  const getStatusBadge = (status: Proposta["status"]) => (
    <span className={`status-badge status-badge-${STATUS_COLORS[status] ?? "neutral"}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );

  const getAnvisaBadge = (status: AnvisaItem["status"]) => {
    switch (status) {
      case "valido":
        return <span className="status-badge status-badge-success">Valido</span>;
      case "vencido":
        return <span className="status-badge status-badge-danger" style={{ background: "#ef4444", color: "#fff" }}>Vencido</span>;
      case "proximo_vencimento":
        return <span className="status-badge status-badge-warning">Proximo Venc.</span>;
    }
  };

  const getDocStatusBadge = (status: DocItem["status"]) => {
    switch (status) {
      case "presente":
        return <span className="status-badge status-badge-success">Presente</span>;
      case "ausente":
        return <span className="status-badge status-badge-danger" style={{ background: "#ef4444", color: "#fff" }}>Ausente</span>;
      case "vencido":
        return <span className="status-badge status-badge-warning">Vencido</span>;
    }
  };

  // ─── Select options ──────────────────────────────────────────────────────────

  const editalOptions = [
    { value: "", label: "Selecione..." },
    ...editais.map((e) => ({ value: e.id ?? e.numero, label: `${e.numero} - ${e.orgao}` })),
  ];

  const produtoOptions = [
    { value: "", label: "Selecione..." },
    ...produtos.map((p) => ({ value: p.id, label: p.nome })),
  ];

  const loteOptions = [
    { value: "", label: "Sem lote" },
    ...lotes.map((l) => ({ value: l.id, label: `Lote ${l.numero_lote} - ${l.nome}` })),
  ];

  const templateOptions = [
    { value: "", label: "Sem template" },
    ...templates.map((t) => ({ value: t.id, label: t.nome })),
  ];

  // ─── Table columns ──────────────────────────────────────────────────────────

  const columns: Column<Proposta>[] = [
    { key: "edital", header: "Edital", sortable: true },
    { key: "orgao", header: "Orgao" },
    { key: "produto", header: "Produto", sortable: true },
    { key: "valorTotal", header: "Valor Total", render: (p) => formatCurrency(p.valorTotal), sortable: true },
    { key: "dataCriacao", header: "Data", sortable: true },
    { key: "status", header: "Status", render: (p) => getStatusBadge(p.status) },
    {
      key: "acoes",
      header: "Acoes",
      width: "120px",
      render: (p) => (
        <div className="table-actions">
          <button title="Visualizar" onClick={() => setSelectedProposta(p)}><Eye size={16} /></button>
          <button title="Baixar" onClick={() => handleBaixarProposta(p, "pdf")}><Download size={16} /></button>
          <button title="Excluir" className="danger" onClick={() => handleExcluirProposta(p.id)}><Trash2 size={16} /></button>
        </div>
      ),
    },
  ];

  // ─── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-left">
          <FileEdit size={24} />
          <div>
            <h1>Geracao de Propostas</h1>
            <p>Criar e gerenciar propostas tecnicas</p>
          </div>
        </div>
        <div className="page-header-actions">
          <ActionButton
            icon={<FileEdit size={16} />}
            label="Nova Proposta"
            variant="primary"
            onClick={() => setShowGerarModal(true)}
          />
          <ActionButton
            icon={<Download size={16} />}
            label="Upload Proposta Externa"
            variant="neutral"
            onClick={() => setShowUploadModal(true)}
          />
        </div>
      </div>

      <div className="page-content">
        {/* ── Card: Gerar Nova Proposta (inline) ──────────────────────────── */}
        <Card title="Gerar Nova Proposta" icon={<FileEdit size={18} />}>
          <div className="form-grid form-grid-4">
            <FormField label="Edital">
              <SelectInput value={novoEdital} onChange={setNovoEdital} options={editalOptions} />
            </FormField>
            <FormField label="Produto">
              <SelectInput value={novoProduto} onChange={setNovoProduto} options={produtoOptions} />
            </FormField>
            <FormField label="Preco Unitario" hint={precoSugerido ? `Sugerido: ${formatCurrency(precoSugerido)}` : undefined}>
              <div className="input-with-button">
                <TextInput value={novoPreco} onChange={setNovoPreco} type="number" placeholder="R$" />
                <button className="btn-icon" title="Sugerir preco" onClick={handleSugerirPreco}>
                  <Lightbulb size={16} />
                </button>
              </div>
            </FormField>
            <FormField label="Quantidade">
              <TextInput value={novaQuantidade} onChange={setNovaQuantidade} type="number" placeholder="Qtd" />
            </FormField>
          </div>
          {(lotes.length > 0 || templates.length > 0) && (
            <div className="form-grid form-grid-4" style={{ marginTop: 8 }}>
              {lotes.length > 0 && (
                <FormField label="Lote">
                  <SelectInput value={novoLote} onChange={setNovoLote} options={loteOptions} />
                </FormField>
              )}
              <FormField label="Template">
                <SelectInput value={novoTemplate} onChange={setNovoTemplate} options={templateOptions} />
              </FormField>
            </div>
          )}
          <div className="form-actions">
            <ActionButton
              icon={<FileEdit size={16} />}
              label="Gerar Proposta Tecnica"
              variant="primary"
              onClick={handleGerarProposta}
              loading={loading}
            />
          </div>
        </Card>

        {/* ── Card: Minhas Propostas ─────────────────────────────────────── */}
        <Card title="Minhas Propostas" icon={<FileEdit size={18} />}>
          <FilterBar
            searchValue={searchTerm}
            onSearchChange={setSearchTerm}
            searchPlaceholder="Buscar proposta..."
            filters={[
              {
                key: "status",
                label: "Status",
                value: statusFilter,
                onChange: setStatusFilter,
                options: [
                  { value: "todas", label: "Todas" },
                  { value: "rascunho", label: "Rascunho" },
                  { value: "revisao", label: "Em Revisao" },
                  { value: "aprovada", label: "Aprovada" },
                  { value: "enviada", label: "Enviada" },
                ],
              },
            ]}
          />

          <DataTable
            data={filteredPropostas}
            columns={columns}
            idKey="id"
            onRowClick={setSelectedProposta}
            selectedId={selectedProposta?.id}
            emptyMessage={loadingLista ? "Carregando..." : "Nenhuma proposta encontrada"}
          />
        </Card>

        {/* ── Card: Preview + Editor da Proposta ─────────────────────────── */}
        {selectedProposta && (
          <>
            <Card
              title="Proposta Selecionada"
              actions={
                <div className="card-actions" style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                  {getStatusBadge(selectedProposta.status)}
                  <ActionButton
                    icon={<FileEdit size={14} />}
                    label="Salvar Rascunho"
                    variant="secondary"
                    onClick={() => { handleSaveContent(); handleStatusChange("rascunho"); }}
                    loading={updatingStatus}
                    disabled={selectedProposta.status === "enviada"}
                  />
                  <ActionButton
                    icon={<Send size={14} />}
                    label="Enviar para Revisao"
                    variant="warning"
                    onClick={() => handleStatusChange("revisao")}
                    loading={updatingStatus}
                    disabled={selectedProposta.status === "enviada"}
                  />
                  <ActionButton
                    icon={<CheckCircle size={14} />}
                    label="Aprovar"
                    variant="success"
                    onClick={() => handleStatusChange("aprovada")}
                    loading={updatingStatus}
                    disabled={selectedProposta.status !== "revisao"}
                  />
                </div>
              }
            >
              <div className="proposta-preview">
                <div className="proposta-header" style={{ marginBottom: 16 }}>
                  <h3>PROPOSTA TECNICA</h3>
                  <div className="form-grid form-grid-4" style={{ marginTop: 8 }}>
                    <p><strong>Edital:</strong> {selectedProposta.edital}</p>
                    <p><strong>Orgao:</strong> {selectedProposta.orgao}</p>
                    <p><strong>Produto:</strong> {selectedProposta.produto}</p>
                    <p><strong>Preco Unitario:</strong> {formatCurrency(selectedProposta.precoUnitario)}</p>
                    <p><strong>Quantidade:</strong> {selectedProposta.quantidade}</p>
                    <p><strong>Valor Total:</strong> {formatCurrency(selectedProposta.valorTotal)}</p>
                  </div>
                </div>

                {/* ── Descricao Tecnica A/B ────────────────────────────────── */}
                <div style={{ marginBottom: 16 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
                    <strong>Descricao Tecnica:</strong>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => setDescMode(descMode === "edital" ? "personalizado" : "edital")}
                      style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, padding: "4px 10px" }}
                    >
                      {descMode === "edital" ? <ToggleLeft size={14} /> : <ToggleRight size={14} />}
                      {descMode === "edital" ? "Texto do Edital" : "Personalizado"}
                    </button>
                    {descMode === "personalizado" && (
                      <span className="status-badge status-badge-warning" style={{ fontSize: 11 }}>
                        Personalizado
                      </span>
                    )}
                  </div>
                  {descMode === "edital" ? (
                    <div style={{
                      background: "var(--bg-secondary, #1e293b)",
                      padding: 12,
                      borderRadius: 6,
                      fontSize: 13,
                      color: "var(--text-secondary, #94a3b8)",
                      minHeight: 60,
                      fontFamily: "monospace",
                      whiteSpace: "pre-wrap",
                    }}>
                      {selectedProposta.conteudo
                        ? selectedProposta.conteudo.substring(0, 500) + (selectedProposta.conteudo.length > 500 ? "..." : "")
                        : "(Sem descricao tecnica do edital)"}
                    </div>
                  ) : (
                    <textarea
                      value={descPersonalizado}
                      onChange={(e) => setDescPersonalizado(e.target.value)}
                      placeholder="Digite a descricao tecnica personalizada..."
                      style={{
                        width: "100%",
                        minHeight: 100,
                        background: "var(--bg-secondary, #1e293b)",
                        color: "var(--text-primary, #e2e8f0)",
                        border: "1px solid var(--border-color, #334155)",
                        borderRadius: 6,
                        padding: 12,
                        fontFamily: "monospace",
                        fontSize: 13,
                        resize: "vertical",
                      }}
                    />
                  )}
                </div>

                {/* ── Editor Rico ──────────────────────────────────────────── */}
                <div style={{ marginBottom: 16 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                    <strong>Conteudo da Proposta (Markdown):</strong>
                    {editorDirty && (
                      <span style={{ fontSize: 11, color: "#f59e0b" }}>Alteracoes nao salvas</span>
                    )}
                  </div>
                  <MarkdownToolbar textareaRef={editorRef} />
                  <textarea
                    ref={editorRef}
                    value={editorContent}
                    onChange={(e) => { setEditorContent(e.target.value); setEditorDirty(true); }}
                    style={{
                      width: "100%",
                      minHeight: 300,
                      background: "var(--bg-secondary, #1e293b)",
                      color: "var(--text-primary, #e2e8f0)",
                      border: "1px solid var(--border-color, #334155)",
                      borderRadius: 6,
                      padding: 12,
                      fontFamily: "'Fira Code', 'Cascadia Code', 'Consolas', monospace",
                      fontSize: 13,
                      resize: "vertical",
                      lineHeight: 1.6,
                    }}
                    placeholder="Escreva o conteudo da proposta em Markdown..."
                  />
                  {editorDirty && (
                    <div style={{ marginTop: 8 }}>
                      <ActionButton
                        icon={<CheckCircle size={14} />}
                        label="Salvar Conteudo"
                        variant="primary"
                        onClick={handleSaveContent}
                      />
                    </div>
                  )}
                </div>
              </div>
            </Card>

            {/* ── Card: Auditoria ANVISA (UC-R04) ────────────────────────── */}
            <Card
              title="Auditoria ANVISA"
              icon={<Shield size={18} />}
              actions={
                <ActionButton
                  icon={loadingAnvisa ? <Loader2 size={14} className="animate-spin" /> : <Shield size={14} />}
                  label="Verificar Registros"
                  variant="secondary"
                  onClick={handleVerificarAnvisa}
                  loading={loadingAnvisa}
                />
              }
            >
              {!anvisaChecked ? (
                <p style={{ color: "var(--text-secondary, #94a3b8)", fontSize: 13, textAlign: "center", padding: 20 }}>
                  Clique em "Verificar Registros" para consultar registros ANVISA dos produtos da proposta.
                </p>
              ) : anvisaItems.length === 0 ? (
                <p style={{ color: "var(--text-secondary, #94a3b8)", fontSize: 13, textAlign: "center", padding: 20 }}>
                  Nenhum registro ANVISA encontrado ou endpoint nao disponivel.
                </p>
              ) : (
                <div style={{ overflowX: "auto" }}>
                  <table className="data-table" style={{ width: "100%", fontSize: 13 }}>
                    <thead>
                      <tr>
                        <th>Produto</th>
                        <th>Registro</th>
                        <th>Validade</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {anvisaItems.map((item, i) => (
                        <tr key={i}>
                          <td>{item.produto}</td>
                          <td style={{ fontFamily: "monospace" }}>{item.registro}</td>
                          <td>{item.validade}</td>
                          <td>{getAnvisaBadge(item.status)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {anvisaItems.some((i) => i.status === "vencido") && (
                    <div style={{
                      marginTop: 12,
                      padding: 12,
                      background: "#7f1d1d33",
                      border: "1px solid #ef4444",
                      borderRadius: 6,
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      color: "#fca5a5",
                      fontSize: 13,
                    }}>
                      <AlertTriangle size={16} />
                      <span>BLOQUEANTE: Existem registros ANVISA vencidos. A proposta nao pode ser enviada.</span>
                    </div>
                  )}
                </div>
              )}
            </Card>

            {/* ── Card: Auditoria Documental (UC-R05) ────────────────────── */}
            <Card
              title="Auditoria Documental"
              icon={<FileCheck size={18} />}
              actions={
                <ActionButton
                  icon={loadingDocs ? <Loader2 size={14} className="animate-spin" /> : <FileCheck size={14} />}
                  label="Verificar Documentos"
                  variant="secondary"
                  onClick={handleVerificarDocs}
                  loading={loadingDocs}
                />
              }
            >
              {!docsChecked ? (
                <p style={{ color: "var(--text-secondary, #94a3b8)", fontSize: 13, textAlign: "center", padding: 20 }}>
                  Clique em "Verificar Documentos" para conferir documentos exigidos vs disponíveis.
                </p>
              ) : docItems.length === 0 ? (
                <p style={{ color: "var(--text-secondary, #94a3b8)", fontSize: 13, textAlign: "center", padding: 20 }}>
                  Nenhum documento encontrado ou endpoint nao disponivel.
                </p>
              ) : (
                <div style={{ overflowX: "auto" }}>
                  <table className="data-table" style={{ width: "100%", fontSize: 13 }}>
                    <thead>
                      <tr>
                        <th>Documento</th>
                        <th>Tamanho</th>
                        <th>Status</th>
                        <th style={{ width: 100 }}>Acoes</th>
                      </tr>
                    </thead>
                    <tbody>
                      {docItems.map((doc, i) => (
                        <tr key={i}>
                          <td>{doc.nome}</td>
                          <td>
                            {doc.tamanho_kb > 0
                              ? doc.tamanho_kb > 1024
                                ? `${(doc.tamanho_kb / 1024).toFixed(1)} MB`
                                : `${doc.tamanho_kb} KB`
                              : "-"}
                          </td>
                          <td>{getDocStatusBadge(doc.status)}</td>
                          <td>
                            {doc.status === "presente" && doc.tamanho_kb > 25 * 1024 && (
                              <button
                                className="btn btn-secondary btn-sm"
                                title="Fracionar arquivo >25MB"
                                onClick={() => handleFracionarDoc(doc.nome)}
                                disabled={splittingDoc === doc.nome}
                                style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, padding: "2px 8px" }}
                              >
                                {splittingDoc === doc.nome ? <Loader2 size={12} className="animate-spin" /> : <Scissors size={12} />}
                                Fracionar
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {/* Checklist final */}
                  <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: docItems.every((d) => d.status === "presente") ? "#4ade80" : "#f59e0b" }}>
                      {docItems.every((d) => d.status === "presente") ? <CheckCircle size={14} /> : <AlertTriangle size={14} />}
                      <span>
                        {docItems.filter((d) => d.status === "presente").length} de {docItems.length} documentos presentes
                      </span>
                    </div>
                    {docItems.some((d) => d.tamanho_kb > 25 * 1024) && (
                      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "#f59e0b" }}>
                        <AlertTriangle size={14} />
                        <span>Existem documentos maiores que 25MB. Use "Fracionar" para dividir.</span>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </Card>

            {/* ── Card: Exportacao (UC-R06) ──────────────────────────────── */}
            <Card
              title="Exportacao"
              icon={<Download size={18} />}
            >
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", padding: "8px 0" }}>
                <ActionButton
                  icon={<Download size={14} />}
                  label="Baixar PDF"
                  variant="primary"
                  onClick={() => handleBaixarProposta(selectedProposta, "pdf")}
                />
                <ActionButton
                  icon={<Download size={14} />}
                  label="Baixar DOCX"
                  variant="secondary"
                  onClick={() => handleBaixarProposta(selectedProposta, "docx")}
                />
                <ActionButton
                  icon={<Archive size={14} />}
                  label="Baixar Dossie ZIP"
                  variant="secondary"
                  onClick={() => handleBaixarDossie(selectedProposta)}
                />
              </div>
              <div style={{ marginTop: 8 }}>
                <ActionButton
                  icon={<Send size={14} />}
                  label="Enviar por Email"
                  onClick={() => {
                    if (onSendToChat && selectedProposta) {
                      onSendToChat(
                        `Prepare um email para envio da proposta:\n` +
                        `- Edital: ${selectedProposta.edital}\n` +
                        `- Orgao: ${selectedProposta.orgao}\n` +
                        `- Produto: ${selectedProposta.produto}\n` +
                        `- Valor: R$ ${selectedProposta.valorTotal.toFixed(2)}\n` +
                        `Gere o corpo do email profissional para envio da proposta ao orgao licitante.`
                      );
                    }
                  }}
                />
              </div>
            </Card>
          </>
        )}
      </div>

      {/* ── Modal: Nova Proposta ─────────────────────────────────────────── */}
      <Modal
        isOpen={showGerarModal}
        onClose={() => setShowGerarModal(false)}
        title="Gerar Nova Proposta"
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => setShowGerarModal(false)}>Cancelar</button>
            <button className="btn btn-primary" onClick={handleGerarProposta} disabled={loading}>
              {loading ? <Loader2 size={14} className="animate-spin" /> : <FileEdit size={14} />}{" "}
              Gerar Proposta
            </button>
          </>
        }
      >
        <FormField label="Edital" required>
          <SelectInput value={novoEdital} onChange={setNovoEdital} options={editalOptions} />
        </FormField>
        {lotes.length > 0 && (
          <FormField label="Lote">
            <SelectInput value={novoLote} onChange={setNovoLote} options={loteOptions} />
          </FormField>
        )}
        <FormField label="Template">
          <SelectInput value={novoTemplate} onChange={setNovoTemplate} options={templateOptions} />
        </FormField>
        <FormField label="Produto" required>
          <SelectInput value={novoProduto} onChange={setNovoProduto} options={produtoOptions} />
        </FormField>
        <FormField label="Preco Unitario" required hint={precoSugerido ? `Sugerido: ${formatCurrency(precoSugerido)}` : undefined}>
          <div className="input-with-button">
            <TextInput value={novoPreco} onChange={setNovoPreco} type="number" prefix="R$" />
            <button className="btn-icon" title="Sugerir preco" onClick={handleSugerirPreco}>
              <Lightbulb size={16} />
            </button>
          </div>
        </FormField>
        <FormField label="Quantidade" required>
          <TextInput value={novaQuantidade} onChange={setNovaQuantidade} type="number" />
        </FormField>
      </Modal>

      {/* ── Modal: Upload Proposta Externa ───────────────────────────────── */}
      <Modal
        isOpen={showUploadModal}
        onClose={() => { setShowUploadModal(false); setUploadFile(null); }}
        title="Upload de Proposta Externa"
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => { setShowUploadModal(false); setUploadFile(null); }}>Cancelar</button>
            <button className="btn btn-primary" disabled={uploadLoading || !novoEdital || !novoProduto || !uploadFile}
              onClick={async () => {
                if (!uploadFile || !novoEdital || !novoProduto) return;
                setUploadLoading(true);
                try {
                  const token = localStorage.getItem("editais_ia_access_token");
                  const formData = new FormData();
                  formData.append("file", uploadFile);
                  formData.append("edital_id", novoEdital);
                  formData.append("produto_id", novoProduto);
                  formData.append("preco_unitario", novoPreco || "0");
                  formData.append("quantidade", novaQuantidade || "1");
                  if (novoLote) formData.append("lote_id", novoLote);
                  const res = await fetch("/api/propostas/upload", {
                    method: "POST",
                    headers: { Authorization: token ? `Bearer ${token}` : "" },
                    body: formData,
                  });
                  const data = await res.json();
                  if (data.success || data.id) {
                    alert("Proposta importada com sucesso!");
                    setShowUploadModal(false);
                    setUploadFile(null);
                    // Recarregar lista
                    try {
                      const listRes = await crudList("propostas", { limit: 50 });
                      setPropostas(((listRes.items || []) as Record<string, unknown>[]).map(mapCrudToProposta));
                    } catch { /* */ }
                  } else {
                    alert(data.error || "Erro ao importar proposta");
                  }
                } catch (e) {
                  alert(e instanceof Error ? e.message : "Erro no upload");
                } finally {
                  setUploadLoading(false);
                }
              }}
            >
              {uploadLoading ? <Loader2 size={14} className="animate-spin" /> : <Download size={14} />}{" "}
              Importar
            </button>
          </>
        }
      >
        <FormField label="Edital" required>
          <SelectInput value={novoEdital} onChange={setNovoEdital} options={editalOptions} />
        </FormField>
        <FormField label="Produto" required>
          <SelectInput value={novoProduto} onChange={setNovoProduto} options={produtoOptions} />
        </FormField>
        <FormField label="Arquivo da Proposta (.docx, .pdf)" required>
          <input type="file" accept=".docx,.pdf" style={{ fontSize: 13 }}
            onChange={(e) => setUploadFile(e.target.files?.[0] || null)} />
        </FormField>
        <FormField label="Preco Unitario">
          <TextInput value={novoPreco} onChange={setNovoPreco} type="number" prefix="R$" />
        </FormField>
        <FormField label="Quantidade">
          <TextInput value={novaQuantidade} onChange={setNovaQuantidade} type="number" />
        </FormField>
      </Modal>
    </div>
  );
}
