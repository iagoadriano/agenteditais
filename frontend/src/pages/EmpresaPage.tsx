import { useState, useEffect, useCallback, useRef } from "react";
import { Building, Upload, Plus, Trash2, Eye, Download, AlertTriangle, X, RefreshCw, Mail, Phone, Loader2, AlertCircle, Pencil, Search, Sparkles, Globe, Info } from "lucide-react";
import { Card, DataTable, ActionButton, FormField, TextInput, SelectInput, Modal, StatusBadge, UploadLoteIA } from "../components/common";
import type { Column } from "../components/common";
import { crudList, crudGet, crudCreate, crudUpdate, crudDelete, getCrudTokenGetter } from "../api/crud";
import { useAuth } from "../contexts/AuthContext";

interface EmpresaPageProps {
  onSendToChat?: (message: string, file?: File) => Promise<void>;
}

interface Documento {
  id: string;
  nome: string;
  tipo: string;
  validade: string | null;
  // "ok" = válido | "vence" = vence em <=30 dias | "vencido" = passou da data | "falta" = nunca enviado
  status: "ok" | "vence" | "vencido" | "falta";
  arquivo?: string;
}

interface Responsavel {
  id: string;
  nome: string;
  tipo?: string;
  cargo?: string;
  cpf?: string;
  email?: string;
  telefone?: string;
}

interface DocNecessario {
  id: string;
  categoria: string;
  nome: string;
  descricao?: string;
  tipo_chave: string;
  obrigatorio: boolean;
  ordem: number;
}

interface CertidaoAutomatica {
  id: string;
  certidao: string;
  tipo?: string;
  status: "valida" | "vencida" | "pendente" | "buscando" | "erro" | "nao_disponivel";
  data_obtencao: string | null;
  validade: string | null;
  path_arquivo?: string;
  url_consulta?: string;
  orgao_emissor?: string;
  fonte_certidao_id?: string;
  fonte_nome?: string;
  fonte_ativa?: boolean;  // F04-03: status da fonte (ativa/inativa)
  numero?: string;
  permite_busca_automatica?: boolean;
  mensagem?: string;
  dados_extras?: Record<string, unknown>;
}

const TIPO_RESPONSAVEL_OPTIONS = [
  { value: "representante_legal", label: "Representante Legal" },
  { value: "preposto", label: "Preposto" },
  { value: "tecnico", label: "Responsavel Tecnico" },
];

const TIPO_RESPONSAVEL_LABELS: Record<string, string> = {
  representante_legal: "Representante Legal",
  preposto: "Preposto",
  tecnico: "Responsavel Tecnico",
};

function formatPhone(value: string): string {
  const digits = value.replace(/\D/g, '').slice(0, 11);
  if (digits.length <= 2) return digits;
  if (digits.length <= 6) return `(${digits.slice(0,2)}) ${digits.slice(2)}`;
  if (digits.length <= 10) return `(${digits.slice(0,2)}) ${digits.slice(2,6)}-${digits.slice(6)}`;
  return `(${digits.slice(0,2)}) ${digits.slice(2,7)}-${digits.slice(7)}`;
}

function formatCpf(value: string): string {
  const d = value.replace(/\D/g, '').slice(0, 11);
  if (d.length <= 3) return d;
  if (d.length <= 6) return `${d.slice(0,3)}.${d.slice(3)}`;
  if (d.length <= 9) return `${d.slice(0,3)}.${d.slice(3,6)}.${d.slice(6)}`;
  return `${d.slice(0,3)}.${d.slice(3,6)}.${d.slice(6,9)}-${d.slice(9)}`;
}

function calcDocStatus(hasArquivo: boolean, dataVencimento: string | null): "ok" | "vence" | "vencido" | "falta" {
  if (!hasArquivo) return "falta";
  if (!dataVencimento) return "ok";
  const hoje = new Date();
  const venc = new Date(dataVencimento);
  const diffMs = venc.getTime() - hoje.getTime();
  const diffDias = diffMs / (1000 * 60 * 60 * 24);
  if (diffDias <= 0) return "vencido";
  if (diffDias <= 30) return "vence";
  return "ok";
}

export function EmpresaPage({ onSendToChat }: EmpresaPageProps) {
  const { isAdmin, empresa: empresaCtx } = useAuth();
  // Empresa data
  const [empresaId, setEmpresaId] = useState<string | null>(null);
  const [razaoSocial, setRazaoSocial] = useState("");
  const [nomeFantasia, setNomeFantasia] = useState("");
  const [cnpj, setCnpj] = useState("");
  const [inscricaoEstadual, setInscricaoEstadual] = useState("");
  const [website, setWebsite] = useState("");
  const [instagram, setInstagram] = useState("");
  const [linkedin, setLinkedin] = useState("");
  const [facebook, setFacebook] = useState("");
  const [endereco, setEndereco] = useState("");
  // F01-07: campos separados de endereco
  const [enderecoNumero, setEnderecoNumero] = useState("");
  const [enderecoComplemento, setEnderecoComplemento] = useState("");
  const [bairro, setBairro] = useState("");
  const [cidade, setCidade] = useState("");
  const [uf, setUf] = useState("");
  const [cep, setCep] = useState("");
  const [areaPadraoId, setAreaPadraoId] = useState("");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [areasDisponiveis, setAreasDisponiveis] = useState<any[]>([]);

  // Emails e celulares multiplos
  const [emails, setEmails] = useState<string[]>([]);
  const [celulares, setCelulares] = useState<string[]>([]);
  const [novoEmail, setNovoEmail] = useState("");
  const [novoCelular, setNovoCelular] = useState("");

  // Sub-tables
  const [documentos, setDocumentos] = useState<Documento[]>([]);
  const [certidoes, setCertidoes] = useState<CertidaoAutomatica[]>([]);
  const [responsaveis, setResponsaveis] = useState<Responsavel[]>([]);

  // Loading/error states
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [empresaSalva, setEmpresaSalva] = useState(false);

  // Modals
  const [showDocModal, setShowDocModal] = useState(false);
  const [showRespModal, setShowRespModal] = useState(false);

  // Alertas IA
  const [alertasIA] = useState<string>("");

  // Certidoes loading
  const [buscandoCertidoes, setBuscandoCertidoes] = useState(false);
  const [certidoesMsg, setCertidoesMsg] = useState<string | null>(null);
  const [freqCertidoes, setFreqCertidoes] = useState<string>("diaria");

  // Certidoes search progress log
  const [certLogLines, setCertLogLines] = useState<{type: string; text: string; status?: string; time: string}[]>([]);
  const [showCertLog, setShowCertLog] = useState(false);
  const [certLogProgress, setCertLogProgress] = useState<{current: number; total: number}>({current: 0, total: 0});
  const certLogRef = useRef<HTMLDivElement>(null);

  // New/Edit responsavel form
  const [editingRespId, setEditingRespId] = useState<string | null>(null);
  const [novoRespTipo, setNovoRespTipo] = useState("");
  const [novoRespNome, setNovoRespNome] = useState("");
  const [novoRespCargo, setNovoRespCargo] = useState("");
  const [novoRespCpf, setNovoRespCpf] = useState("");
  const [novoRespEmail, setNovoRespEmail] = useState("");
  const [novoRespTel, setNovoRespTel] = useState("");

  // New doc form
  const [novoDocTipo, setNovoDocTipo] = useState("");
  const [novoDocNecId, setNovoDocNecId] = useState("");
  const [novoDocValidade, setNovoDocValidade] = useState("");
  const [novoDocFile, setNovoDocFile] = useState<File | null>(null);
  const [docNecessarios, setDocNecessarios] = useState<DocNecessario[]>([]);

  // Certidao detail modal
  const [showCertDetailModal, setShowCertDetailModal] = useState(false);
  const [certDetail, setCertDetail] = useState<CertidaoAutomatica | null>(null);

  // Certidao detail edit fields
  const [certEditNumero, setCertEditNumero] = useState("");
  const [certEditValidade, setCertEditValidade] = useState("");
  const [certEditOrgao, setCertEditOrgao] = useState("");
  const [certEditStatus, setCertEditStatus] = useState("");
  const [certSaving, setCertSaving] = useState(false);
  const [certSaved, setCertSaved] = useState(false);

  // Upload certidao modal
  const [showCertUploadModal, setShowCertUploadModal] = useState(false);
  const [uploadCertId, setUploadCertId] = useState<string | null>(null);
  const [uploadCertNome, setUploadCertNome] = useState("");
  const [uploadCertFile, setUploadCertFile] = useState<File | null>(null);
  const [uploadCertValidade, setUploadCertValidade] = useState("");
  const [uploadCertNumero, setUploadCertNumero] = useState("");
  const [uploadingCert, setUploadingCert] = useState(false);
  const [capsolverStatus, setCapsolverStatus] = useState<{configurado: boolean; mensagem: string; saldo?: number} | null>(null);

  const loadEmpresa = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      let emp: Record<string, unknown> | null = null;
      if (empresaCtx?.id) {
        // Carrega APENAS a empresa ativa do contexto do usuário
        emp = await crudGet("empresas", empresaCtx.id);
      } else {
        // Sem empresa ativa no contexto: NÃO pré-popular com dados de outra empresa.
        // Mantém formulário em branco para o usuário cadastrar uma nova.
        emp = null;
      }
      if (emp) {
        const id = String(emp.id ?? "");
        setEmpresaId(id);
        setRazaoSocial(String(emp.razao_social ?? ""));
        setNomeFantasia(String(emp.nome_fantasia ?? ""));
        setCnpj(String(emp.cnpj ?? ""));
        setInscricaoEstadual(String(emp.inscricao_estadual ?? ""));
        setWebsite(String(emp.website ?? ""));
        setInstagram(String(emp.instagram ?? ""));
        setLinkedin(String(emp.linkedin ?? ""));
        setFacebook(String(emp.facebook ?? ""));
        setEndereco(String(emp.endereco ?? ""));
        setEnderecoNumero(String(emp.endereco_numero ?? ""));
        setEnderecoComplemento(String(emp.endereco_complemento ?? ""));
        setBairro(String(emp.bairro ?? ""));
        setCidade(String(emp.cidade ?? ""));
        setUf(String(emp.uf ?? ""));
        setCep(String(emp.cep ?? ""));
        const emailsStr = String(emp.emails ?? "");
        setEmails(emailsStr ? emailsStr.split(",").map(e => e.trim()).filter(Boolean) : []);
        const celStr = String(emp.celulares ?? "");
        setCelulares(celStr ? celStr.split(",").map(c => c.trim()).filter(Boolean) : []);
        setFreqCertidoes(String(emp.frequencia_busca_certidoes ?? "diaria"));
        setAreaPadraoId(String(emp.area_padrao_id ?? ""));

        // Load sub-tables
        await loadSubTables(id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar empresa");
    } finally {
      setLoading(false);
    }
  }, [empresaCtx?.id]);

  const loadSubTables = async (id: string) => {
    try {
      // Sincronizar fontes de certidões → cria registros pendentes para fontes sem certidão
      try {
        const tokenFn = getCrudTokenGetter();
        const token = tokenFn ? await tokenFn() : null;
        await fetch("/api/empresa-certidoes/sincronizar-fontes", {
          method: "POST",
          headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          body: JSON.stringify({ empresa_id: id }),
        });
      } catch { /* silencioso — não impede carregar a página */ }

      const [docsRes, certRes, respRes, fontesRes] = await Promise.all([
        crudList("empresa-documentos", { parent_id: id }),
        crudList("empresa-certidoes", { parent_id: id }),
        crudList("empresa-responsaveis", { parent_id: id }),
        // F04-03: precisamos do estado 'ativo' das fontes pra mostrar na tabela
        crudList("fontes-certidoes", { limit: 200 }),
      ]);

      // F04-03: mapa fonte_id -> ativo
      const fonteAtivaMap = new Map<string, boolean>();
      for (const f of fontesRes.items) {
        if (f.id) fonteAtivaMap.set(String(f.id), f.ativo !== false);
      }

      setDocumentos(docsRes.items.map(d => {
        const hasArquivo = !!(d.path_arquivo || d.arquivo);
        const dataVenc = d.data_vencimento ? String(d.data_vencimento) : (d.validade ? String(d.validade) : null);
        return {
          id: String(d.id ?? ""),
          nome: String(d.nome_arquivo || d.nome || d.tipo || ""),
          tipo: String(d.documento_necessario_nome || d.tipo || ""),
          validade: dataVenc,
          status: calcDocStatus(hasArquivo, dataVenc),
          arquivo: d.path_arquivo ? String(d.path_arquivo) : (d.arquivo ? String(d.arquivo) : undefined),
        };
      }));

      setCertidoes(certRes.items.map(c => ({
          id: String(c.id ?? ""),
          certidao: String(c.fonte_nome || c.orgao_emissor || c.tipo || "Certidão"),
          tipo: c.tipo ? String(c.tipo) : undefined,
          status: (c.status as CertidaoAutomatica["status"]) || "pendente",
          data_obtencao: c.data_obtencao ? String(c.data_obtencao) : null,
          validade: c.data_vencimento ? String(c.data_vencimento) : (c.validade ? String(c.validade) : null),
          path_arquivo: c.path_arquivo ? String(c.path_arquivo) : undefined,
          url_consulta: c.url_consulta ? String(c.url_consulta) : undefined,
          orgao_emissor: c.orgao_emissor ? String(c.orgao_emissor) : undefined,
          fonte_certidao_id: c.fonte_certidao_id ? String(c.fonte_certidao_id) : undefined,
          numero: c.numero ? String(c.numero) : undefined,
          fonte_nome: c.fonte_nome ? String(c.fonte_nome) : undefined,
          // F04-03: pega do map de fontes (true se nao achou — comportamento padrao)
          fonte_ativa: c.fonte_certidao_id ? (fonteAtivaMap.get(String(c.fonte_certidao_id)) ?? true) : true,
          permite_busca_automatica: c.permite_busca_automatica !== false,
          mensagem: c.mensagem ? String(c.mensagem) : undefined,
          dados_extras: c.dados_extras && typeof c.dados_extras === "object" ? c.dados_extras as Record<string, unknown> : undefined,
      })));

      setResponsaveis(respRes.items.map(r => ({
        id: String(r.id ?? ""),
        nome: String(r.nome ?? ""),
        tipo: r.tipo ? String(r.tipo) : undefined,
        cargo: r.cargo ? String(r.cargo) : undefined,
        email: r.email ? String(r.email) : undefined,
        telefone: r.telefone ? String(r.telefone) : undefined,
      })));
    } catch {
      // Sub-tables may be empty or not exist yet - not a fatal error
    }
  };

  useEffect(() => {
    loadEmpresa();
    // Carregar áreas de produto para o select
    (async () => {
      try {
        const token = localStorage.getItem("editais_ia_access_token");
        const res = await fetch("/api/areas-produto", {
          headers: { Authorization: token ? `Bearer ${token}` : "" },
        });
        if (res.ok) {
          const data = await res.json();
          if (data.success && Array.isArray(data.items)) {
            setAreasDisponiveis(data.items);
          }
        }
      } catch { /* silencioso */ }
    })();
    // Carregar tipos de documentos necessários para o dropdown
    (async () => {
      try {
        const token = localStorage.getItem("editais_ia_access_token");
        const res = await fetch("/api/documentos-necessarios", {
          headers: { Authorization: token ? `Bearer ${token}` : "" },
        });
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data)) {
            setDocNecessarios(data);
          }
        }
      } catch { /* silencioso */ }
    })();
    // Verificar status do CapSolver
    (async () => {
      try {
        const token = localStorage.getItem("editais_ia_access_token");
        const res = await fetch("/api/capsolver/status", {
          headers: { Authorization: token ? `Bearer ${token}` : "" },
        });
        if (res.ok) {
          const data = await res.json();
          setCapsolverStatus(data);
        }
      } catch { /* silencioso */ }
    })();
  }, [loadEmpresa]);

  // Auto-scroll log to bottom
  useEffect(() => {
    if (certLogRef.current) {
      certLogRef.current.scrollTop = certLogRef.current.scrollHeight;
    }
  }, [certLogLines]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const data = {
        razao_social: razaoSocial,
        nome_fantasia: nomeFantasia,
        cnpj,
        inscricao_estadual: inscricaoEstadual,
        website,
        instagram,
        linkedin,
        facebook,
        endereco,
        endereco_numero: enderecoNumero,
        endereco_complemento: enderecoComplemento,
        bairro,
        cidade,
        uf,
        cep,
        emails: emails.join(","),
        celulares: celulares.join(","),
        area_padrao_id: areaPadraoId || null,
      };

      if (empresaId) {
        await crudUpdate("empresas", empresaId, data);
      } else {
        const created = await crudCreate("empresas", data);
        setEmpresaId(String(created.id ?? ""));
      }
      setError("");
      setEmpresaSalva(true);
      setTimeout(() => setEmpresaSalva(false), 2000);
      window.alert("Dados da empresa salvos com sucesso!");
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erro ao salvar empresa";
      setError(msg);
      window.alert("Erro ao salvar empresa: " + msg);
    } finally {
      setSaving(false);
    }
  };

  const handleAddEmail = () => {
    if (novoEmail.trim()) {
      setEmails([...emails, novoEmail.trim()]);
      setNovoEmail("");
    }
  };

  const handleRemoveEmail = (index: number) => {
    setEmails(emails.filter((_, i) => i !== index));
  };

  const handleAddCelular = () => {
    if (novoCelular.trim()) {
      setCelulares([...celulares, novoCelular.trim()]);
      setNovoCelular("");
    }
  };

  const handleRemoveCelular = (index: number) => {
    setCelulares(celulares.filter((_, i) => i !== index));
  };

  const handleSalvarResponsavel = async () => {
    if (!novoRespNome.trim() || !empresaId) return;
    try {
      // Normaliza campos opcionais: string vazia → null
      // tipo (ENUM no banco) NAO aceita "" — precisa ser null se nao selecionado
      const payload = {
        empresa_id: empresaId,
        tipo: novoRespTipo || null,
        nome: novoRespNome.trim(),
        cargo: novoRespCargo.trim() || null,
        cpf: novoRespCpf.trim() || null,
        email: novoRespEmail.trim() || null,
        telefone: novoRespTel.trim() || null,
      };
      if (editingRespId) {
        await crudUpdate("empresa-responsaveis", editingRespId, payload);
      } else {
        await crudCreate("empresa-responsaveis", payload);
      }
      setEditingRespId(null);
      setNovoRespTipo("");
      setNovoRespNome("");
      setNovoRespCargo("");
      setNovoRespCpf("");
      setNovoRespEmail("");
      setNovoRespTel("");
      setShowRespModal(false);
      await loadSubTables(empresaId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar responsavel");
    }
  };

  const handleEditarResponsavel = (r: Responsavel) => {
    setEditingRespId(r.id);
    setNovoRespTipo(r.tipo || "");
    setNovoRespNome(r.nome);
    setNovoRespCargo(r.cargo || "");
    setNovoRespCpf(r.cpf || "");
    setNovoRespEmail(r.email || "");
    setNovoRespTel(r.telefone || "");
    setShowRespModal(true);
  };

  const handleExcluirResponsavel = async (id: string) => {
    if (!confirm("Excluir este responsavel?")) return;
    try {
      await crudDelete("empresa-responsaveis", id);
      setResponsaveis(responsaveis.filter(r => r.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao excluir responsavel");
    }
  };

  const handleSalvarDocumento = async () => {
    if ((!novoDocTipo && !novoDocNecId) || !empresaId) return;
    try {
      const formData = new FormData();
      formData.append("empresa_id", empresaId);
      if (novoDocNecId) {
        formData.append("documento_necessario_id", novoDocNecId);
      }
      formData.append("tipo", novoDocTipo);
      if (novoDocValidade) formData.append("data_vencimento", novoDocValidade);
      if (novoDocFile) {
        formData.append("file", novoDocFile);
      }

      const headers: HeadersInit = {};
      const tokenFn = getCrudTokenGetter();
      if (tokenFn) {
        const token = await tokenFn();
        if (token) headers["Authorization"] = `Bearer ${token}`;
      }

      const res = await fetch("/api/empresa-documentos/upload", {
        method: "POST",
        headers,
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || "Erro ao fazer upload do documento");
      }

      await loadSubTables(empresaId);
      setNovoDocTipo("");
      setNovoDocNecId("");
      setNovoDocValidade("");
      setNovoDocFile(null);
      setShowDocModal(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar documento");
    }
  };

  const handleExcluirDocumento = async (id: string) => {
    if (!confirm("Excluir este documento?")) return;
    try {
      await crudDelete("empresa-documentos", id);
      setDocumentos(documentos.filter(d => d.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao excluir documento");
    }
  };

  const getAuthHeaders = async (): Promise<HeadersInit> => {
    const headers: HeadersInit = { "Content-Type": "application/json" };
    const tokenFn = getCrudTokenGetter();
    if (tokenFn) {
      const token = await tokenFn();
      if (token) headers["Authorization"] = `Bearer ${token}`;
    }
    return headers;
  };

  const [freqSalva, setFreqSalva] = useState(false);
  const handleFreqCertidoesChange = async (valor: string) => {
    setFreqCertidoes(valor);
    if (empresaId) {
      try {
        await crudUpdate("empresas", empresaId, { frequencia_busca_certidoes: valor });
        setFreqSalva(true);
        setTimeout(() => setFreqSalva(false), 2000);
      } catch (err) {
        console.error("Erro ao salvar frequência:", err);
        setError("Erro ao salvar frequência de busca");
      }
    }
  };

  const handleBuscarCertidoes = async (idsAlvo?: string[]) => {
    if (!empresaId) {
      setError("Cadastre a empresa primeiro (com CNPJ) antes de buscar certidoes.");
      return;
    }
    if (!cnpj) {
      setError("A empresa precisa ter um CNPJ cadastrado para buscar certidoes.");
      return;
    }
    setBuscandoCertidoes(true);
    setCertidoesMsg(null);
    setCertLogLines([]);
    setShowCertLog(true);
    setCertLogProgress({current: 0, total: 0});

    const now = () => new Date().toLocaleTimeString("pt-BR", {hour: "2-digit", minute: "2-digit", second: "2-digit"});
    const addLog = (line: {type: string; text: string; status?: string; time: string}) => {
      setCertLogLines(prev => [...prev, line]);
    };

    try {
      const headers = await getAuthHeaders();
      // F04-04: passa certidao_ids quando o user clica no botao individual
      const body: Record<string, unknown> = { empresa_id: empresaId };
      if (idsAlvo && idsAlvo.length > 0) {
        body.certidao_ids = idsAlvo;
      }
      const res = await fetch("/api/empresa-certidoes/buscar-stream", {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || "Erro ao buscar certidoes");
      }

      const reader = res.body?.getReader();
      if (!reader) throw new Error("Stream não disponível");

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            if (evt.type === "start") {
              setCertLogProgress({current: 0, total: evt.total});
              addLog({type: "info", text: `Iniciando busca em ${evt.total} fontes de certidao...`, time: now()});
            } else if (evt.type === "searching") {
              setCertLogProgress(p => ({...p, current: evt.index - 1}));
              addLog({type: "searching", text: `Buscando: ${evt.fonte}...`, time: now()});
            } else if (evt.type === "result") {
              setCertLogProgress(p => ({...p, current: evt.index}));
              const icon = evt.sucesso
                ? "OBTIDA"
                : evt.status === "nao_disponivel"
                  ? "MANUAL - faca upload do PDF"
                  : "PENDENTE - verifique configuracao";
              addLog({type: "result", text: `[${icon}] ${evt.fonte}: ${evt.mensagem}`, status: evt.status, time: now()});
            } else if (evt.type === "complete") {
              addLog({type: "complete", text: evt.message, time: now()});
              setCertidoesMsg(evt.message);
            } else if (evt.type === "error") {
              addLog({type: "error", text: `ERRO: ${evt.message}`, time: now()});
              setError(evt.message);
            }
          } catch { /* ignore parse errors */ }
        }
      }

      await loadSubTables(empresaId);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Erro ao buscar certidoes";
      addLog({type: "error", text: `ERRO: ${msg}`, time: now()});
      setError(msg);
    } finally {
      setBuscandoCertidoes(false);
    }
  };

  const handleOpenCertUpload = (cert: CertidaoAutomatica) => {
    setUploadCertId(cert.id);
    setUploadCertNome(cert.certidao);
    setUploadCertFile(null);
    setUploadCertValidade("");
    setUploadCertNumero("");
    setShowCertUploadModal(true);
  };

  const handleUploadCertidao = async () => {
    if (!uploadCertId || !uploadCertFile) return;
    setUploadingCert(true);
    try {
      const formData = new FormData();
      formData.append("file", uploadCertFile);
      if (uploadCertValidade) formData.append("data_vencimento", uploadCertValidade);
      if (uploadCertNumero) formData.append("numero", uploadCertNumero);

      const headers: HeadersInit = {};
      const tokenFn = getCrudTokenGetter();
      if (tokenFn) {
        const token = await tokenFn();
        if (token) headers["Authorization"] = `Bearer ${token}`;
      }

      const res = await fetch(`/api/empresa-certidoes/${uploadCertId}/upload`, {
        method: "POST",
        headers,
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || "Erro ao fazer upload da certidao");
      }

      const result = await res.json();
      setShowCertUploadModal(false);
      // F04-06: avisar quando IA detectou validade diferente da digitada pelo user
      if (result.divergencia_validade) {
        const d = result.divergencia_validade;
        alert(
          `⚠ DIVERGÊNCIA DE VALIDADE DETECTADA\n\n` +
          `Você digitou: ${d.data_informada_user}\n` +
          `IA extraiu do PDF: ${d.data_extraida_pdf}\n\n` +
          `Foi salva a data REAL do PDF (${d.data_extraida_pdf}) — ela prevalece sobre a digitada.\n` +
          `Confira o documento se a data parecer estranha.`
        );
      } else if (result.dados_extraidos) {
        alert(`Dados extraídos automaticamente por IA:\n• Situação: ${result.dados_extraidos.situacao || "N/I"}\n• Validade: ${result.dados_extraidos.data_vencimento || "N/I"}\n• Número: ${result.dados_extraidos.numero || "N/I"}\n• Órgão: ${result.dados_extraidos.orgao_emissor || "N/I"}`);
      }
      if (empresaId) await loadSubTables(empresaId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao fazer upload da certidao");
    } finally {
      setUploadingCert(false);
    }
  };

  const getStatusBadge = (status: Documento["status"]) => {
    switch (status) {
      case "ok":
        return <span className="status-badge status-badge-success">OK</span>;
      case "vence":
        return <span className="status-badge status-badge-warning"><AlertTriangle size={12} /> Vence em breve</span>;
      case "vencido":
        return <span className="status-badge status-badge-error"><AlertTriangle size={12} /> Vencido</span>;
      case "falta":
        return <span className="status-badge status-badge-error">Falta envio</span>;
    }
  };

  const handleSaveCertEdit = async () => {
    if (!certDetail) return;
    setCertSaving(true);
    setCertSaved(false);
    try {
      const payload: Record<string, string | null> = {};
      if (certEditNumero !== (certDetail.numero || "")) payload.numero = certEditNumero || null;
      if (certEditValidade !== (certDetail.validade || "")) payload.data_vencimento = certEditValidade || null;
      if (certEditOrgao !== (certDetail.orgao_emissor || "")) payload.orgao_emissor = certEditOrgao || null;
      if (certEditStatus !== (certDetail.status || "")) payload.status = certEditStatus || null;

      if (Object.keys(payload).length === 0) {
        setCertSaving(false);
        setCertSaved(true);
        setTimeout(() => setCertSaved(false), 2000);
        return;
      }

      await crudUpdate("empresa-certidoes", certDetail.id, payload);
      // Update local state
      setCertDetail({ ...certDetail, numero: certEditNumero || undefined, validade: certEditValidade, orgao_emissor: certEditOrgao || undefined, status: certEditStatus as CertidaoAutomatica["status"] });
      setCertSaved(true);
      setTimeout(() => setCertSaved(false), 2000);
      // Refresh table
      if (empresaId) {
        await loadSubTables(empresaId);
      }
    } catch (err) {
      console.error("Erro ao salvar certidao:", err);
      alert("Erro ao salvar alteracoes.");
    } finally {
      setCertSaving(false);
    }
  };

  const docColumns: Column<Documento>[] = [
    { key: "nome", header: "Documento", sortable: true },
    { key: "tipo", header: "Tipo", render: (d) => <span className="text-muted" style={{ fontSize: "12px" }}>{d.tipo}</span> },
    { key: "validade", header: "Validade", render: (d) => d.validade || "-" },
    { key: "status", header: "Status", render: (d) => getStatusBadge(d.status) },
    {
      key: "acoes",
      header: "Acoes",
      width: "120px",
      render: (d) => (
        <div className="table-actions">
          {d.arquivo ? (
            <>
              <button title="Visualizar" onClick={async () => {
                const tokenFn = getCrudTokenGetter();
                const token = tokenFn ? await tokenFn() : null;
                const res = await fetch(`/api/empresa-documentos/${d.id}/download`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
                if (res.ok) {
                  const blob = await res.blob();
                  const url = URL.createObjectURL(blob);
                  window.open(url, "_blank");
                }
              }}><Eye size={16} /></button>
              <button title="Download" onClick={async () => {
                const tokenFn = getCrudTokenGetter();
                const token = tokenFn ? await tokenFn() : null;
                const res = await fetch(`/api/empresa-documentos/${d.id}/download`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
                if (res.ok) {
                  const blob = await res.blob();
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a"); a.href = url; a.download = d.nome || "documento"; a.click(); URL.revokeObjectURL(url);
                }
              }}><Download size={16} /></button>
              <button title="Excluir" className="danger" onClick={() => handleExcluirDocumento(d.id)}><Trash2 size={16} /></button>
            </>
          ) : (
            <button className="btn-small btn-primary" onClick={() => setShowDocModal(true)}>
              <Upload size={14} /> Upload
            </button>
          )}
        </div>
      ),
    },
  ];

  const certidaoColumns: Column<CertidaoAutomatica>[] = [
    { key: "certidao", header: "Certidao", sortable: true },
    {
      key: "fonte_ativa",
      header: "Fonte",
      width: "85px",
      render: (c) => {
        // F04-03: mostrar se a fonte cadastrada esta ativa ou inativa
        const ativa = c.fonte_ativa !== false;
        return (
          <span title={ativa ? "Fonte de certidao ativa — sera usada na busca" : "Fonte INATIVA — nao sera usada"} style={{
            display: "inline-block",
            padding: "2px 8px",
            borderRadius: "10px",
            fontSize: "11px",
            fontWeight: 500,
            background: ativa ? "rgba(34,197,94,0.12)" : "rgba(148,163,184,0.18)",
            color: ativa ? "#16a34a" : "#64748b",
          }}>
            {ativa ? "Ativa" : "Inativa"}
          </span>
        );
      },
    },
    {
      key: "modo",
      header: "Modo",
      width: "100px",
      render: (c) => {
        const auto = c.permite_busca_automatica !== false;
        return (
          <span title={auto ? "Busca automatica disponivel — clique no icone de atualizar" : "Apenas upload manual — sistema nao consegue buscar nesta fonte"} style={{
            display: "inline-block",
            padding: "2px 8px",
            borderRadius: "10px",
            fontSize: "11px",
            fontWeight: 500,
            background: auto ? "rgba(34,197,94,0.12)" : "rgba(234,179,8,0.12)",
            color: auto ? "#16a34a" : "#ca8a04",
          }}>
            {auto ? "Automatica" : "Manual"}
          </span>
        );
      },
    },
    {
      key: "status",
      header: "Status",
      width: "130px",
      render: (c) => {
        const st = c.status;
        if (st === "valida" && c.validade) {
          const dias = Math.ceil((new Date(c.validade).getTime() - Date.now()) / 86400000);
          if (dias <= 0) return <StatusBadge status="error" label="Vencida" size="small" />;
          if (dias <= 15) return <StatusBadge status="warning" label={`Vence em ${dias}d`} size="small" />;
          return <StatusBadge status="success" label={`Valida (${dias}d)`} size="small" />;
        }
        if (st === "valida") return <StatusBadge status="success" label="Valida" size="small" />;
        if (st === "vencida") return <StatusBadge status="error" label="Vencida" size="small" />;
        if (st === "nao_disponivel") return <StatusBadge status="neutral" label="Aguarda upload" size="small" />;
        if (st === "pendente") return <StatusBadge status="warning" label="Acao necessaria" size="small" />;
        if (st === "buscando") return <StatusBadge status="info" label="Buscando..." size="small" />;
        if (st === "erro") return <StatusBadge status="error" label="Erro" size="small" />;
        return <StatusBadge status="neutral" label={st || "-"} size="small" />;
      },
    },
    {
      key: "validade",
      header: "Validade",
      width: "100px",
      render: (c) => c.validade ? new Date(c.validade + "T00:00:00").toLocaleDateString("pt-BR") : "-",
    },
    {
      key: "numero",
      header: "Número",
      width: "150px",
      render: (c) => c.numero
        ? <span title={c.numero} style={{ fontFamily: "monospace", fontSize: 12 }}>{c.numero}</span>
        : <span style={{ color: "var(--text-muted, #888)", fontStyle: "italic" }}>-</span>,
    },
    {
      key: "pdf",
      header: "PDF",
      width: "50px",
      render: (c) => c.path_arquivo
        ? <button title="Visualizar PDF" onClick={async () => {
            const tokenFn = getCrudTokenGetter();
            const token = tokenFn ? await tokenFn() : null;
            const res = await fetch(`/api/empresa-certidoes/${c.id}/download`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
            if (res.ok) {
              const blob = await res.blob();
              const url = URL.createObjectURL(blob);
              window.open(url, "_blank");
            }
          }} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-success, #22c55e)" }}>
            <Eye size={16} />
          </button>
        : <span style={{ color: "var(--text-muted, #ccc)", fontSize: "11px" }}>—</span>,
    },
    {
      key: "acoes",
      header: "Acoes",
      width: "140px",
      render: (c) => (
        <div className="table-actions" style={{ gap: "2px" }}>
          <button title="Editar dados da certidao (numero, validade, orgao emissor)" onClick={() => {
            setCertDetail(c);
            setCertEditNumero(c.numero || "");
            setCertEditValidade(c.validade || "");
            setCertEditOrgao(c.orgao_emissor || "");
            setCertEditStatus(c.status || "");
            setCertSaved(false);
            setShowCertDetailModal(true);
          }} style={{ color: "var(--color-primary, #3b82f6)" }}>
            <Pencil size={18} />
          </button>
          <button title="Fazer upload manual do PDF da certidao (use quando a busca automatica falhou)" onClick={() => handleOpenCertUpload(c)} style={{ color: "var(--color-warning, #f59e0b)" }}>
            <Upload size={15} />
          </button>
          {c.path_arquivo && (
            <button title="Baixar o PDF salvo da certidao" onClick={async () => {
              const tokenFn = getCrudTokenGetter();
              const token = tokenFn ? await tokenFn() : null;
              const res = await fetch(`/api/empresa-certidoes/${c.id}/download?download=true`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
              if (res.ok) {
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a"); a.href = url; a.download = `${c.certidao || "certidao"}.pdf`; a.click(); URL.revokeObjectURL(url);
              }
            }} style={{ color: "var(--color-success, #22c55e)" }}><Download size={15} /></button>
          )}
          {c.permite_busca_automatica !== false && (
            <button title="Atualizar APENAS esta certidao (busca individual)" disabled={buscandoCertidoes} onClick={() => handleBuscarCertidoes([c.id])}>
              <RefreshCw size={15} className={buscandoCertidoes ? "spin" : ""} />
            </button>
          )}
          {c.url_consulta && (
            <button title={`Abrir portal externo (${c.orgao_emissor || c.certidao}) em nova aba — emita a certidao manualmente e depois faca upload`} onClick={() => window.open(c.url_consulta, "_blank")} style={{ color: "var(--color-info, #06b6d4)" }}>
              <Globe size={15} />
            </button>
          )}
        </div>
      ),
    },
  ];

  const respColumns: Column<Responsavel>[] = [
    { key: "tipo", header: "Tipo", render: (r) => TIPO_RESPONSAVEL_LABELS[r.tipo || ""] || r.tipo || "-" },
    { key: "nome", header: "Nome", sortable: true },
    { key: "cargo", header: "Cargo", render: (r) => r.cargo || "-" },
    { key: "email", header: "Email", render: (r) => r.email || "-" },
    {
      key: "acoes",
      header: "Acoes",
      width: "120px",
      render: (r) => (
        <div className="table-actions">
          <button title="Editar" onClick={() => handleEditarResponsavel(r)}><Pencil size={18} /></button>
          <button title="Excluir" className="danger" onClick={() => handleExcluirResponsavel(r.id)}><Trash2 size={18} /></button>
        </div>
      ),
    },
  ];

  if (loading) {
    return (
      <div className="page-container">
        <div className="loading-center">
          <Loader2 size={32} className="spin" />
          <span>Carregando dados da empresa...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-left">
          <Building size={24} />
          <div>
            <h1>{empresaId ? "Dados da Empresa" : "Cadastrar Nova Empresa"}</h1>
            <p>{empresaId
              ? "Cadastro de informacoes e documentos da empresa"
              : "Preencha os dados abaixo. Após salvar, a empresa será vinculada ao seu usuário."}</p>
          </div>
        </div>
        <div className="page-header-actions">
          <ActionButton
            icon={<Search size={16} />}
            label="Verificar Documentos"
            variant="primary"
            onClick={() => onSendToChat?.("Verifique os documentos da nossa empresa contra os editais que estamos participando. Liste documentos faltantes, vencidos e exigencias possivelmente ilegais.")}
          />
        </div>
      </div>

      <div className="page-content">
        {error && (
          <div className="portfolio-error">
            <AlertCircle size={16} />
            <span>{error}</span>
            <button onClick={loadEmpresa}>Tentar novamente</button>
          </div>
        )}

        {/* Informacoes Cadastrais */}
        <Card title="Informacoes Cadastrais" icon={<Building size={18} />}>
          <div className="form-grid form-grid-2">
            <FormField label="Razao Social" required>
              <TextInput value={razaoSocial} onChange={setRazaoSocial} />
            </FormField>
            <FormField label="Nome Fantasia">
              <TextInput value={nomeFantasia} onChange={setNomeFantasia} />
            </FormField>
            <FormField label={empresaId ? "CNPJ (não editável após cadastro)" : "CNPJ"} required>
              <TextInput
                value={cnpj}
                onChange={setCnpj}
                placeholder="00.000.000/0000-00"
                disabled={!!empresaId}
              />
              {empresaId && (
                <small style={{ color: "var(--text-muted, #94a3b8)", display: "block", marginTop: "4px", fontSize: "11px" }}>
                  CNPJ é a chave fiscal da empresa e não pode ser alterado. Para cadastrar outra empresa, use "Selecionar Empresa → Nova Empresa".
                </small>
              )}
            </FormField>
            {/* F01-02: Inscricao Estadual obrigatoria (decisao de produto). IM continua opcional (nem todas tem). */}
            <FormField label="Inscrição Estadual" required>
              <TextInput value={inscricaoEstadual} onChange={setInscricaoEstadual} placeholder="Digite ISENTO se a empresa for isenta" />
            </FormField>
          </div>

          <div className="form-grid form-grid-1">
            <FormField label="Area de Atuacao Padrao">
              <SelectInput
                value={areaPadraoId}
                onChange={setAreaPadraoId}
                options={[
                  { value: "", label: "Selecione uma area..." },
                  ...areasDisponiveis.map((a: { id: string; nome: string }) => ({
                    value: a.id,
                    label: a.nome,
                  })),
                ]}
              />
            </FormField>
          </div>

          <div className="form-section-title">Presenca Digital</div>
          <div className="form-grid form-grid-2">
            <FormField label="Website">
              <TextInput value={website} onChange={setWebsite} type="url" />
            </FormField>
            <FormField label="Instagram">
              <TextInput value={instagram} onChange={setInstagram} prefix="@" />
            </FormField>
            <FormField label="LinkedIn">
              <TextInput value={linkedin} onChange={setLinkedin} />
            </FormField>
            <FormField label="Facebook">
              <TextInput value={facebook} onChange={setFacebook} />
            </FormField>
          </div>

          <div className="form-section-title">Endereco</div>
          {/* F01-07: CEP no topo, popula automaticamente os outros campos */}
          <div className="form-grid form-grid-2">
            <FormField label="CEP — digite e os campos abaixo são preenchidos automaticamente">
              <TextInput value={cep} placeholder="00000-000" onChange={(v) => {
                setCep(v);
                const digits = v.replace(/\D/g, '');
                if (digits.length === 8) {
                  fetch(`https://viacep.com.br/ws/${digits}/json/`)
                    .then(r => r.json())
                    .then(data => {
                      if (!data.erro) {
                        setEndereco(data.logradouro || '');
                        setBairro(data.bairro || '');
                        setCidade(data.localidade || '');
                        setUf(data.uf || '');
                      }
                    })
                    .catch(() => {});
                }
              }} />
            </FormField>
            <FormField label="UF">
              <SelectInput value={uf} onChange={setUf} options={[
                {value: "", label: "Selecione o estado"},
                {value: "AC", label: "AC"}, {value: "AL", label: "AL"}, {value: "AM", label: "AM"},
                {value: "AP", label: "AP"}, {value: "BA", label: "BA"}, {value: "CE", label: "CE"},
                {value: "DF", label: "DF"}, {value: "ES", label: "ES"}, {value: "GO", label: "GO"},
                {value: "MA", label: "MA"}, {value: "MG", label: "MG"}, {value: "MS", label: "MS"},
                {value: "MT", label: "MT"}, {value: "PA", label: "PA"}, {value: "PB", label: "PB"},
                {value: "PE", label: "PE"}, {value: "PI", label: "PI"}, {value: "PR", label: "PR"},
                {value: "RJ", label: "RJ"}, {value: "RN", label: "RN"}, {value: "RO", label: "RO"},
                {value: "RR", label: "RR"}, {value: "RS", label: "RS"}, {value: "SC", label: "SC"},
                {value: "SE", label: "SE"}, {value: "SP", label: "SP"}, {value: "TO", label: "TO"},
              ]} />
            </FormField>
          </div>
          <div className="form-grid form-grid-3">
            <FormField label="Logradouro (Rua/Avenida)">
              <TextInput value={endereco} onChange={setEndereco} placeholder="Ex: Av. Paulista" />
            </FormField>
            <FormField label="Número">
              <TextInput value={enderecoNumero} onChange={setEnderecoNumero} placeholder="123 ou S/N" />
            </FormField>
            <FormField label="Complemento (opcional)">
              <TextInput value={enderecoComplemento} onChange={setEnderecoComplemento} placeholder="Apto 45, Sala 102" />
            </FormField>
          </div>
          <div className="form-grid form-grid-2">
            <FormField label="Bairro">
              <TextInput value={bairro} onChange={setBairro} placeholder="Ex: Centro" />
            </FormField>
            <FormField label="Cidade">
              <TextInput value={cidade} onChange={setCidade} />
            </FormField>
          </div>

          {/* Emails multiplos */}
          <div className="form-section-title">
            <Mail size={16} />
            Emails de Contato
          </div>
          <div className="multi-field-list">
            {emails.map((em, i) => (
              <div key={i} className="multi-field-item">
                <span>{em}</span>
                <button className="btn-icon-small" onClick={() => handleRemoveEmail(i)} title="Remover">
                  <X size={14} />
                </button>
              </div>
            ))}
            <div className="multi-field-add">
              <TextInput
                value={novoEmail}
                onChange={setNovoEmail}
                placeholder="Novo email..."
                type="email"
              />
              <ActionButton
                icon={<Plus size={14} />}
                label="Adicionar"
                onClick={handleAddEmail}
              />
            </div>
          </div>

          {/* Celulares multiplos */}
          <div className="form-section-title">
            <Phone size={16} />
            Celulares / Telefones
          </div>
          <div className="multi-field-list">
            {celulares.map((cel, i) => (
              <div key={i} className="multi-field-item">
                <span>{cel}</span>
                <button className="btn-icon-small" onClick={() => handleRemoveCelular(i)} title="Remover">
                  <X size={14} />
                </button>
              </div>
            ))}
            <div className="multi-field-add">
              <TextInput
                value={novoCelular}
                onChange={(v) => setNovoCelular(formatPhone(v))}
                placeholder="Novo telefone..."
              />
              <ActionButton
                icon={<Plus size={14} />}
                label="Adicionar"
                onClick={handleAddCelular}
              />
            </div>
          </div>

          <div className="form-actions">
            {isAdmin && (
              <ActionButton
                label="Salvar Alteracoes"
                variant="primary"
                onClick={handleSave}
                loading={saving}
              />
            )}
            {empresaSalva && <span style={{ fontSize: "12px", color: "var(--color-success, #22c55e)", fontWeight: 500 }}>Salvo!</span>}
          </div>
        </Card>

        {/* Alertas IA sobre Documentos */}
        <Card
          title="Alertas IA sobre Documentos"
          subtitle="A IA verifica seus documentos contra requisitos de editais"
          icon={<Sparkles size={18} />}
          actions={
            <ActionButton
              icon={<Search size={14} />}
              label="Verificar Documentos"
              variant="primary"
              onClick={() => onSendToChat?.("Verifique os documentos da nossa empresa contra os editais que estamos participando. Liste documentos faltantes, vencidos e exigencias possivelmente ilegais.")}
            />
          }
        >
          {alertasIA ? (
            <div className="alertas-ia-content" style={{ whiteSpace: "pre-wrap", padding: "12px", background: "var(--bg-secondary, #f5f5f5)", borderRadius: "8px", fontSize: "14px", lineHeight: "1.6" }}>
              {alertasIA}
            </div>
          ) : (
            <div style={{ padding: "24px", textAlign: "center", color: "var(--text-muted, #888)" }}>
              <Sparkles size={32} style={{ marginBottom: "8px", opacity: 0.5 }} />
              <p>Clique em &quot;Verificar Documentos&quot; para a IA analisar sua documentacao.</p>
            </div>
          )}
        </Card>

        {/* F03-02: Upload em massa por IA */}
        {empresaId && (
          <Card title="🤖 Cadastro Automático de Documentos por IA (NOVO)" icon={<Upload size={18} />}>
            <UploadLoteIA contexto="documentos" empresaId={empresaId} onConfirmado={() => loadSubTables(empresaId)} />
          </Card>
        )}

        {/* Documentos */}
        <Card
          title="Documentos da Empresa"
          icon={<Upload size={18} />}
          actions={
            <ActionButton
              icon={<Plus size={16} />}
              label="Upload Documento"
              onClick={() => setShowDocModal(true)}
            />
          }
        >
          <DataTable
            data={documentos}
            columns={docColumns}
            idKey="id"
            emptyMessage="Nenhum documento cadastrado"
          />
        </Card>

        {/* Certidoes Automaticas */}
        <Card
          title="Certidoes Automaticas"
          subtitle={cnpj ? `Busca certidoes para CNPJ ${cnpj} nos portais oficiais` : "Cadastre o CNPJ da empresa para buscar certidoes"}
          icon={<RefreshCw size={18} />}
          actions={
            <ActionButton
              icon={buscandoCertidoes ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
              label={buscandoCertidoes ? "Buscando..." : "Buscar Certidoes"}
              variant="primary"
              disabled={buscandoCertidoes || !cnpj}
              onClick={() => handleBuscarCertidoes()}
            />
          }
        >
          {certidoesMsg && !showCertLog && (
            <div style={{ padding: "8px 12px", marginBottom: "12px", background: "var(--bg-success, #dcfce7)", borderRadius: "6px", fontSize: "13px", color: "var(--text-success, #166534)" }}>
              {certidoesMsg}
            </div>
          )}
          {/* Janela de progresso da busca de certidoes */}
          {showCertLog && (
            <div style={{
              margin: "0 0 12px 0",
              border: "1px solid var(--border, #333)",
              borderRadius: "8px",
              overflow: "hidden",
              background: "#1a1a2e",
            }}>
              {/* Header */}
              <div style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "8px 12px",
                background: "#16213e",
                borderBottom: "1px solid #2a2a4a",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                  <span style={{ fontSize: "13px", fontWeight: 600, color: "#e2e8f0" }}>
                    Progresso da Busca
                    {certLogProgress.total > 0 && ` (${certLogProgress.current}/${certLogProgress.total})`}
                  </span>
                  {buscandoCertidoes && <Loader2 size={14} className="spin" style={{ color: "#60a5fa" }} />}
                </div>
                {!buscandoCertidoes && (
                  <button
                    onClick={() => setShowCertLog(false)}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", padding: "2px" }}
                    title="Fechar"
                  >
                    <X size={14} />
                  </button>
                )}
              </div>
              {/* Progress bar */}
              {certLogProgress.total > 0 && (
                <div style={{ height: "3px", background: "#2a2a4a" }}>
                  <div style={{
                    height: "100%",
                    width: `${(certLogProgress.current / certLogProgress.total) * 100}%`,
                    background: buscandoCertidoes ? "#3b82f6" : "#22c55e",
                    transition: "width 0.3s ease",
                  }} />
                </div>
              )}
              {/* Log lines */}
              <div
                style={{
                  maxHeight: "250px",
                  overflowY: "auto",
                  padding: "8px 0",
                  fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
                  fontSize: "12px",
                  lineHeight: "1.7",
                }}
                ref={certLogRef}
              >
                {certLogLines.map((line, i) => (
                  <div key={i} style={{
                    padding: "2px 12px",
                    color:
                      line.type === "error" ? "#f87171" :
                      line.type === "complete" ? "#4ade80" :
                      line.type === "searching" ? "#60a5fa" :
                      line.status === "valida" ? "#4ade80" :
                      line.status === "nao_disponivel" ? "#fbbf24" :
                      line.status === "pendente" ? "#fb923c" :
                      "#cbd5e1",
                  }}>
                    <span style={{ color: "#64748b", marginRight: "8px" }}>{line.time}</span>
                    {line.type === "searching" && <span style={{ color: "#60a5fa" }}>{">> "}</span>}
                    {line.type === "result" && <span style={{ color: line.status === "valida" ? "#4ade80" : "#fbbf24" }}>{"<< "}</span>}
                    {line.type === "complete" && <span style={{ color: "#4ade80" }}>{"== "}</span>}
                    {line.type === "error" && <span style={{ color: "#f87171" }}>{"!! "}</span>}
                    {line.text}
                  </div>
                ))}
                {buscandoCertidoes && certLogLines.length === 0 && (
                  <div style={{ padding: "8px 12px", color: "#64748b" }}>Conectando...</div>
                )}
              </div>
            </div>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: "12px", padding: "8px 12px", marginBottom: "8px" }}>
            <span style={{ fontSize: "13px", color: "var(--text-secondary, #666)" }}>Frequencia de busca automatica:</span>
            <select
              value={freqCertidoes}
              onChange={(e) => handleFreqCertidoesChange(e.target.value)}
              style={{ padding: "4px 8px", borderRadius: "4px", border: "1px solid var(--border, #ddd)", fontSize: "13px", background: "var(--bg-primary, #fff)", color: "var(--text-primary, #333)" }}
            >
              <option value="desativada">Desativada</option>
              <option value="diaria">Diaria</option>
              <option value="semanal">Semanal</option>
              <option value="quinzenal">Quinzenal</option>
              <option value="mensal">Mensal</option>
            </select>
            {freqSalva && <span style={{ fontSize: "12px", color: "var(--color-success, #22c55e)", fontWeight: 500 }}>Salvo!</span>}
          </div>
          <DataTable
            data={certidoes}
            columns={certidaoColumns}
            idKey="id"
            emptyMessage={cnpj
              ? 'Clique em "Buscar Certidoes" para consultar todas as fontes cadastradas'
              : "Cadastre o CNPJ da empresa primeiro"
            }
          />
          {certidoes.length > 0 && (
            <div style={{ padding: "8px 12px", marginTop: "8px", fontSize: "12px", color: "var(--text-muted, #888)" }}>
              {(() => {
                const automaticas = certidoes.filter(c => c.permite_busca_automatica !== false).length;
                const manuais = certidoes.length - automaticas;
                return `${certidoes.length} certidoes (${automaticas} automaticas, ${manuais} manuais). `;
              })()}
              {capsolverStatus && (
                <span style={{
                  display: "inline-block",
                  marginLeft: "8px",
                  padding: "2px 8px",
                  borderRadius: "10px",
                  fontSize: "11px",
                  fontWeight: 500,
                  background: capsolverStatus.configurado ? "rgba(34,197,94,0.15)" : "rgba(234,179,8,0.15)",
                  color: capsolverStatus.configurado ? "#16a34a" : "#ca8a04",
                }}>
                  {capsolverStatus.configurado
                    ? `CapSolver: $${capsolverStatus.saldo?.toFixed(2) || "0.00"}`
                    : "CapSolver: nao configurado"
                  }
                </span>
              )}
            </div>
          )}
        </Card>

        {/* Responsaveis */}
        <Card
          title="Responsaveis"
          actions={
            <ActionButton
              icon={<Plus size={16} />}
              label="Adicionar"
              onClick={() => { setError(null); setShowRespModal(true); }}
            />
          }
        >
          <DataTable
            data={responsaveis}
            columns={respColumns}
            idKey="id"
            emptyMessage="Nenhum responsavel cadastrado"
          />
        </Card>
      </div>

      {/* Modal Upload Documento */}
      <Modal
        isOpen={showDocModal}
        onClose={() => setShowDocModal(false)}
        title="Upload de Documento"
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => setShowDocModal(false)}>Cancelar</button>
            <button className="btn btn-primary" onClick={handleSalvarDocumento} disabled={!novoDocNecId}>Enviar</button>
          </>
        }
      >
        <FormField label="Tipo de Documento" required>
          <select className="select-input" value={novoDocNecId} onChange={(e) => {
            const selId = e.target.value;
            setNovoDocNecId(selId);
            const dn = docNecessarios.find(d => d.id === selId);
            setNovoDocTipo(dn ? dn.tipo_chave : selId);
          }}>
            <option value="">Selecione...</option>
            {(() => {
              const cats = [...new Set(docNecessarios.map(d => d.categoria))];
              return cats.map(cat => (
                <optgroup key={cat} label={cat}>
                  {docNecessarios.filter(d => d.categoria === cat).map(d => (
                    <option key={d.id} value={d.id}>{d.nome}</option>
                  ))}
                </optgroup>
              ));
            })()}
          </select>
        </FormField>
        <FormField label="Arquivo">
          <input type="file" accept=".pdf,.doc,.docx,.jpg,.png" onChange={(e) => setNovoDocFile(e.target.files?.[0] || null)} />
        </FormField>
        <FormField label="Validade">
          <input type="date" className="text-input" value={novoDocValidade} onChange={(e) => setNovoDocValidade(e.target.value)} />
        </FormField>
      </Modal>

      {/* Modal Responsavel */}
      <Modal
        isOpen={showRespModal}
        onClose={() => {
          setShowRespModal(false);
          setEditingRespId(null);
          setNovoRespTipo("");
          setNovoRespNome("");
          setNovoRespCargo("");
          setNovoRespCpf("");
          setNovoRespEmail("");
          setNovoRespTel("");
          setError(null);
        }}
        title={editingRespId ? "Editar Responsavel" : "Adicionar Responsavel"}
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => {
              setShowRespModal(false);
              setEditingRespId(null);
              setNovoRespTipo("");
              setNovoRespNome("");
              setNovoRespCargo("");
              setNovoRespCpf("");
              setNovoRespEmail("");
              setNovoRespTel("");
              setError(null);
            }}>Cancelar</button>
            <button className="btn btn-primary" onClick={handleSalvarResponsavel} disabled={!novoRespNome}>Salvar</button>
          </>
        }
      >
        {error && (
          <div style={{ background: "#fef2f2", color: "#dc2626", padding: "10px 14px", borderRadius: 6, marginBottom: 12, border: "1px solid #fecaca", fontSize: "0.9rem" }}>
            {error}
          </div>
        )}
        <FormField label="Tipo">
          <SelectInput
            value={novoRespTipo}
            onChange={setNovoRespTipo}
            options={TIPO_RESPONSAVEL_OPTIONS}
            placeholder="Selecione o tipo..."
          />
        </FormField>
        <FormField label="Nome" required>
          <TextInput value={novoRespNome} onChange={setNovoRespNome} />
        </FormField>
        <FormField label="Cargo">
          <TextInput value={novoRespCargo} onChange={setNovoRespCargo} />
        </FormField>
        <FormField label="CPF">
          <TextInput value={novoRespCpf} onChange={(v) => setNovoRespCpf(formatCpf(v))} placeholder="000.000.000-00" />
        </FormField>
        <FormField label="Email" required>
          <TextInput value={novoRespEmail} onChange={setNovoRespEmail} type="email" />
        </FormField>
        <FormField label="Telefone">
          <TextInput value={novoRespTel} onChange={(v) => setNovoRespTel(formatPhone(v))} />
        </FormField>
      </Modal>

      {/* Modal Detalhes Certidao — CRUD */}
      <Modal
        isOpen={showCertDetailModal}
        onClose={() => { setShowCertDetailModal(false); setCertDetail(null); }}
        title={`${certDetail?.certidao || "Certidao"}`}
        footer={
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", alignItems: "center" }}>
            <button className="btn btn-primary" onClick={handleSaveCertEdit} disabled={certSaving}>
              {certSaving ? <><Loader2 size={14} className="spin" /> Salvando...</> : "Salvar"}
            </button>
            {certSaved && <span style={{ color: "var(--color-success, #22c55e)", fontSize: "12px", fontWeight: 600 }}>Salvo!</span>}
            {certDetail?.url_consulta && (
              <button className="btn btn-secondary" onClick={() => window.open(certDetail.url_consulta, "_blank")}>
                <Globe size={14} /> Portal
              </button>
            )}
            {certDetail?.path_arquivo && (
              <button className="btn btn-secondary" onClick={async () => {
                const tokenFn = getCrudTokenGetter();
                const token = tokenFn ? await tokenFn() : null;
                const res = await fetch(`/api/empresa-certidoes/${certDetail.id}/download?download=true`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
                if (res.ok) {
                  const blob = await res.blob();
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a"); a.href = url; a.download = `${certDetail.certidao || "certidao"}.pdf`; a.click(); URL.revokeObjectURL(url);
                }
              }}>
                <Download size={14} /> Download
              </button>
            )}
            <button className="btn btn-secondary" onClick={() => { setShowCertDetailModal(false); setCertDetail(null); }}>Fechar</button>
          </div>
        }
      >
        {certDetail && (
          <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
            {/* O que fazer — destaque contextual */}
            {(() => {
              const st = certEditStatus || certDetail.status;
              const auto = certDetail.permite_busca_automatica !== false;
              const temArquivo = !!certDetail.path_arquivo;
              let bgColor = ""; let textColor = ""; let icon = <Info size={16} />; let titulo = ""; let instrucao = "";

              if (st === "valida" && temArquivo) {
                bgColor = "rgba(34,197,94,0.1)"; textColor = "#16a34a";
                icon = <Download size={16} />;
                titulo = "Certidao valida";
                instrucao = "Certidao obtida e dentro da validade.";
              } else if (st === "valida" && !temArquivo) {
                bgColor = "rgba(34,197,94,0.1)"; textColor = "#16a34a";
                titulo = "Certidao valida (sem PDF)";
                instrucao = "Resultado positivo registrado. Nenhum PDF gerado.";
              } else if (st === "vencida" && auto) {
                bgColor = "rgba(239,68,68,0.1)"; textColor = "#dc2626";
                icon = <RefreshCw size={16} />;
                titulo = "Certidao vencida";
                instrucao = "Clique em 'Buscar Certidoes' para renovar automaticamente.";
              } else if (st === "vencida" && !auto) {
                bgColor = "rgba(239,68,68,0.1)"; textColor = "#dc2626";
                icon = <Upload size={16} />;
                titulo = "Certidao vencida — renovacao manual";
                instrucao = "Acesse o portal, emita nova certidao e faca upload.";
              } else if (st === "nao_disponivel") {
                bgColor = "rgba(234,179,8,0.1)"; textColor = "#ca8a04";
                icon = <Upload size={16} />;
                titulo = "Upload manual necessario";
                instrucao = "Acesse o portal, emita a certidao e faca upload. A IA extrai os dados do PDF.";
              } else if (st === "pendente") {
                bgColor = "rgba(249,115,22,0.1)"; textColor = "#ea580c";
                icon = <AlertCircle size={16} />;
                titulo = "Acao necessaria";
                instrucao = certDetail.mensagem || "Verifique a configuracao da fonte ou faca upload manual.";
              } else if (st === "erro") {
                bgColor = "rgba(239,68,68,0.1)"; textColor = "#dc2626";
                icon = <AlertCircle size={16} />;
                titulo = "Erro na busca";
                instrucao = "Tente novamente ou faca upload manual.";
              } else {
                bgColor = "rgba(100,116,139,0.1)"; textColor = "#64748b";
                titulo = "Aguardando";
                instrucao = "Clique em 'Buscar Certidoes' para iniciar.";
              }

              return (
                <div style={{ padding: "10px 14px", background: bgColor, borderRadius: "8px", borderLeft: `4px solid ${textColor}` }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px", color: textColor, fontWeight: 600, fontSize: "13px" }}>
                    {icon} {titulo}
                  </div>
                  <div style={{ fontSize: "12px", lineHeight: "1.4", color: "var(--text-primary, #333)", marginTop: "4px" }}>
                    {instrucao}
                  </div>
                </div>
              );
            })()}

            {/* PDF inline viewer com fallback amigavel */}
            {certDetail.path_arquivo && (
              <div>
                <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-secondary, #666)", marginBottom: "6px" }}>
                  Documento PDF
                </div>
                <object
                  data={`/api/empresa-certidoes/${certDetail.id}/download`}
                  type="application/pdf"
                  style={{ width: "100%", height: "280px", border: "1px solid var(--border, #e2e8f0)", borderRadius: "6px", background: "#f9fafb" }}
                >
                  <div style={{ padding: 16, textAlign: "center", color: "var(--text-muted, #6b7280)", fontSize: 13 }}>
                    Não foi possível exibir o PDF no navegador.{" "}
                    <button
                      type="button"
                      onClick={async () => {
                        const tokenFn = getCrudTokenGetter();
                        const token = tokenFn ? await tokenFn() : null;
                        const res = await fetch(`/api/empresa-certidoes/${certDetail.id}/download?download=true`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
                        if (res.ok) {
                          const blob = await res.blob();
                          const url = URL.createObjectURL(blob);
                          window.open(url, "_blank");
                        } else {
                          alert("Arquivo não encontrado no servidor. Faça upload novamente.");
                        }
                      }}
                      style={{ background: "none", border: "none", color: "var(--primary, #3b82f6)", cursor: "pointer", textDecoration: "underline" }}
                    >Clique aqui para baixar</button>
                  </div>
                </object>
              </div>
            )}

            {/* Campos editaveis */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-muted, #888)", marginBottom: "4px", display: "block" }}>Status</label>
                <select
                  value={certEditStatus}
                  onChange={(e) => setCertEditStatus(e.target.value)}
                  style={{ width: "100%", padding: "6px 8px", borderRadius: "6px", border: "1px solid var(--border, #e2e8f0)", background: "var(--bg-secondary, #fff)", color: "var(--text-primary, #333)", fontSize: "13px" }}
                >
                  <option value="valida">Valida</option>
                  <option value="vencida">Vencida</option>
                  <option value="pendente">Aguardando acao</option>
                  <option value="nao_disponivel">Upload manual</option>
                  <option value="erro">Erro</option>
                </select>
              </div>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-muted, #888)", marginBottom: "4px", display: "block" }}>Modo</label>
                <div style={{ padding: "6px 8px", fontSize: "13px", fontWeight: 500, color: "var(--text-secondary, #666)" }}>
                  {certDetail.permite_busca_automatica !== false ? "Automatica" : "Manual"}
                </div>
              </div>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-muted, #888)", marginBottom: "4px", display: "block" }}>Validade</label>
                <input
                  type="date"
                  value={certEditValidade}
                  onChange={(e) => setCertEditValidade(e.target.value)}
                  style={{ width: "100%", padding: "6px 8px", borderRadius: "6px", border: "1px solid var(--border, #e2e8f0)", background: "var(--bg-secondary, #fff)", color: "var(--text-primary, #333)", fontSize: "13px" }}
                />
              </div>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-muted, #888)", marginBottom: "4px", display: "block" }}>Data Emissao</label>
                <div style={{ padding: "6px 8px", fontSize: "13px", color: "var(--text-secondary, #666)" }}>
                  {certDetail.data_obtencao ? new Date(certDetail.data_obtencao + "T00:00:00").toLocaleDateString("pt-BR") : "—"}
                </div>
              </div>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-muted, #888)", marginBottom: "4px", display: "block" }}>Numero</label>
                <input
                  type="text"
                  value={certEditNumero}
                  onChange={(e) => setCertEditNumero(e.target.value)}
                  placeholder="Numero da certidao"
                  style={{ width: "100%", padding: "6px 8px", borderRadius: "6px", border: "1px solid var(--border, #e2e8f0)", background: "var(--bg-secondary, #fff)", color: "var(--text-primary, #333)", fontSize: "13px" }}
                />
              </div>
              <div>
                <label style={{ fontSize: "11px", color: "var(--text-muted, #888)", marginBottom: "4px", display: "block" }}>Orgao Emissor</label>
                <input
                  type="text"
                  value={certEditOrgao}
                  onChange={(e) => setCertEditOrgao(e.target.value)}
                  placeholder="Orgao emissor"
                  style={{ width: "100%", padding: "6px 8px", borderRadius: "6px", border: "1px solid var(--border, #e2e8f0)", background: "var(--bg-secondary, #fff)", color: "var(--text-primary, #333)", fontSize: "13px" }}
                />
              </div>
            </div>

            {/* Resultado da busca */}
            {certDetail.mensagem && (
              <div>
                <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-secondary, #666)", marginBottom: "4px" }}>
                  Resultado da Busca
                </div>
                <div style={{ fontSize: "12px", lineHeight: "1.5", padding: "8px 12px", background: "var(--bg-tertiary, #f8fafc)", borderRadius: "6px", whiteSpace: "pre-wrap", maxHeight: "100px", overflowY: "auto" }}>
                  {certDetail.mensagem}
                </div>
              </div>
            )}

            {/* Dados extras */}
            {certDetail.dados_extras && Object.keys(certDetail.dados_extras).length > 0 && (
              <div>
                <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-secondary, #666)", marginBottom: "4px" }}>
                  Dados Detalhados
                </div>
                <div style={{ fontSize: "12px", padding: "8px 12px", background: "var(--bg-tertiary, #f8fafc)", borderRadius: "6px", maxHeight: "120px", overflowY: "auto" }}>
                  {Object.entries(certDetail.dados_extras).map(([key, val]) => (
                    <div key={key} style={{ display: "flex", gap: "8px", padding: "3px 0", borderBottom: "1px solid var(--border, #e2e8f020)" }}>
                      <span style={{ color: "var(--text-muted, #888)", minWidth: "140px" }}>{key.replace(/_/g, " ")}</span>
                      <span style={{ fontWeight: 500 }}>{Array.isArray(val) ? val.join(", ") : String(val ?? "—")}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* Modal Upload Certidao */}
      <Modal
        isOpen={showCertUploadModal}
        onClose={() => setShowCertUploadModal(false)}
        title={`Upload Certidao: ${uploadCertNome}`}
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => setShowCertUploadModal(false)}>Cancelar</button>
            <button className="btn btn-primary" onClick={handleUploadCertidao} disabled={!uploadCertFile || uploadingCert}>
              <Upload size={14} /> {uploadingCert ? "Analisando PDF..." : "Enviar"}
            </button>
          </>
        }
      >
        <FormField label="Arquivo (PDF)" required>
          <input
            type="file"
            accept=".pdf,.jpg,.jpeg,.png"
            onChange={(e) => setUploadCertFile(e.target.files?.[0] || null)}
            style={{ width: "100%", padding: "8px", border: "1px solid var(--border-color, #e2e8f0)", borderRadius: "6px" }}
          />
        </FormField>
        <FormField label="Data de Vencimento">
          <input
            type="date"
            value={uploadCertValidade}
            onChange={(e) => setUploadCertValidade(e.target.value)}
            className="form-input"
            style={{ width: "100%", padding: "8px 12px", borderRadius: "6px", border: "1px solid var(--border, #e2e8f0)", background: "var(--bg-secondary, #fff)", color: "var(--text-primary, #333)", fontSize: "14px" }}
          />
        </FormField>
        <FormField label="Numero da Certidao">
          <TextInput
            value={uploadCertNumero}
            onChange={setUploadCertNumero}
            placeholder="Ex: 12345/2026"
          />
        </FormField>
        <div style={{ padding: "8px 0", fontSize: "12px", color: "var(--text-muted, #888)" }}>
          A IA analisara o PDF automaticamente e extraira: <strong>validade, numero, orgao emissor e situacao</strong>.
          Os campos acima sao opcionais — se preenchidos, sobrescrevem os dados extraidos pela IA.
        </div>
      </Modal>
    </div>
  );
}
