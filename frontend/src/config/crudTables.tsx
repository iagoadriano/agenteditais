/**
 * Configuração de todas as tabelas CRUD.
 * Define campos, labels e tipos para cada tabela.
 */
import React from "react";
import {
  Building, FileText, Shield, Users, Package, Sliders, Search,
  FileCheck, Layers, BarChart2, Gavel, DollarSign, Scale, Eye,
  Bell, Clock, Mail, Send, Briefcase, TrendingUp, AlertTriangle,
  Database, BookOpen, Target, Zap, Globe, UserPlus, FolderTree, Tag, Tags, GitBranch,
  Plus, Trash2
} from "lucide-react";
import type { CrudPageConfig } from "../components/CrudPage";
import { crudList, crudCreate, crudUpdate, crudDelete } from "../api/crud";

// ─── Editor visual de campos_mascara ──────────────────────────────────────────

export interface CampoMascara {
  campo: string;
  tipo: "texto" | "numero" | "decimal" | "select" | "boolean";
  unidade?: string;
  placeholder?: string;
  opcoes?: string[];       // Para tipo "select"
  obrigatorio?: boolean;
}

const TIPOS_CAMPO = [
  { value: "texto", label: "Texto" },
  { value: "numero", label: "Número inteiro" },
  { value: "decimal", label: "Decimal" },
  { value: "select", label: "Seleção" },
  { value: "boolean", label: "Sim/Não" },
];

function CamposMascaraEditor({ value, onChange }: { value: unknown; onChange: (val: unknown) => void }) {
  const campos: CampoMascara[] = Array.isArray(value)
    ? value.map((v: Record<string, unknown>) => ({ campo: String(v.campo || v.nome || ""), tipo: (v.tipo as CampoMascara["tipo"]) || "texto", unidade: v.unidade ? String(v.unidade) : undefined, placeholder: v.placeholder ? String(v.placeholder) : undefined, opcoes: Array.isArray(v.opcoes) ? v.opcoes.map(String) : undefined, obrigatorio: Boolean(v.obrigatorio) }))
    : [];

  const updateCampo = (idx: number, key: string, val: unknown) => {
    const updated = [...campos];
    updated[idx] = { ...updated[idx], [key]: val };
    onChange(updated);
  };

  const addCampo = () => {
    onChange([...campos, { campo: "", tipo: "texto", placeholder: "" }]);
  };

  const removeCampo = (idx: number) => {
    onChange(campos.filter((_, i) => i !== idx));
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{ fontSize: 13, color: "#94a3b8" }}>Campos técnicos da máscara de entrada</span>
        <button type="button" className="btn btn-secondary btn-sm" onClick={addCampo} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, padding: "4px 8px" }}>
          <Plus size={12} /> Adicionar Campo
        </button>
      </div>
      {campos.length === 0 && (
        <p style={{ fontSize: 12, color: "#64748b", textAlign: "center", padding: 12 }}>
          Nenhum campo definido. Clique em "Adicionar Campo" para criar a máscara.
        </p>
      )}
      {/* Header */}
      {campos.length > 0 && (
        <div style={{ display: "flex", gap: 8, marginBottom: 4, fontSize: 11, color: "#64748b", fontWeight: 600 }}>
          <span style={{ flex: 2 }}>Nome do campo</span>
          <span style={{ width: 110 }}>Tipo</span>
          <span style={{ width: 70 }}>Unidade</span>
          <span style={{ flex: 1 }}>Placeholder / Opções</span>
          <span style={{ width: 30, textAlign: "center" }}>Obr.</span>
          <span style={{ width: 28 }}></span>
        </div>
      )}
      {campos.map((campo, idx) => (
        <div key={idx} style={{ display: "flex", gap: 8, marginBottom: 6, alignItems: "center" }}>
          <input
            type="text"
            className="text-input"
            value={campo.campo}
            onChange={(e) => updateCampo(idx, "campo", e.target.value)}
            placeholder="Nome (ex: Potencia)"
            style={{ flex: 2 }}
          />
          <select
            className="text-input"
            value={campo.tipo}
            onChange={(e) => updateCampo(idx, "tipo", e.target.value)}
            style={{ width: 110 }}
          >
            {TIPOS_CAMPO.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
          <input
            type="text"
            className="text-input"
            value={campo.unidade || ""}
            onChange={(e) => updateCampo(idx, "unidade", e.target.value || undefined)}
            placeholder="Un."
            style={{ width: 70 }}
          />
          {campo.tipo === "select" ? (
            <input
              type="text"
              className="text-input"
              value={(campo.opcoes || []).join(", ")}
              onChange={(e) => updateCampo(idx, "opcoes", e.target.value.split(",").map((s: string) => s.trim()).filter(Boolean))}
              placeholder="Opções separadas por vírgula"
              style={{ flex: 1 }}
            />
          ) : (
            <input
              type="text"
              className="text-input"
              value={campo.placeholder || ""}
              onChange={(e) => updateCampo(idx, "placeholder", e.target.value)}
              placeholder="Ex: 1500W"
              style={{ flex: 1 }}
            />
          )}
          <input
            type="checkbox"
            checked={campo.obrigatorio || false}
            onChange={(e) => updateCampo(idx, "obrigatorio", e.target.checked)}
            title="Obrigatório"
            style={{ width: 16, height: 16, cursor: "pointer" }}
          />
          <button type="button" onClick={() => removeCampo(idx)} style={{ background: "none", border: "none", color: "#ef4444", cursor: "pointer", padding: 4 }}>
            <Trash2 size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}

// ─── Helper: Enum → options ───────────────────────────────────────────────────

function enumOpts(values: Array<string | [string, string]>): { value: string; label: string }[] {
  return values.map((v) => {
    if (Array.isArray(v)) return { value: v[0], label: v[1] };
    return {
      value: v,
      label: v.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    };
  });
}

// ─── Tabelas por Categoria ────────────────────────────────────────────────────

// === 1. EMPRESA ===

export const empresaConfig: CrudPageConfig = {
  table: "empresas",
  title: "Empresas",
  icon: <Building size={24} />,
  fields: [
    { name: "cnpj", label: "CNPJ", type: "text", required: true, width: "half", placeholder: "00.000.000/0001-00" },
    { name: "razao_social", label: "Razão Social", type: "text", required: true, width: "half" },
    { name: "nome_fantasia", label: "Nome Fantasia", type: "text", width: "half" },
    // F01-02: IE obrigatoria
    { name: "inscricao_estadual", label: "Inscrição Estadual", type: "text", required: true, width: "half", placeholder: "Digite ISENTO se aplicavel" },
    { name: "inscricao_municipal", label: "Inscrição Municipal", type: "text", width: "half" },
    { name: "regime_tributario", label: "Regime Tributário", type: "select", options: enumOpts(["simples", "lucro_presumido", "lucro_real"]), width: "half" },
    { name: "porte", label: "Porte", type: "select", options: enumOpts(["me", "epp", "medio", "grande"]), width: "half" },
    { name: "cep", label: "CEP", type: "text", width: "half", placeholder: "00000-000 (popula endereço via ViaCEP)" },
    { name: "uf", label: "UF", type: "text", width: "half", placeholder: "MG" },
    { name: "endereco", label: "Logradouro (Rua/Avenida)", type: "text", width: "full", placeholder: "Ex: Av. Paulista" },
    // F01-07: campos separados
    { name: "endereco_numero", label: "Número", type: "text", width: "half", placeholder: "123 ou S/N" },
    { name: "endereco_complemento", label: "Complemento", type: "text", width: "half", placeholder: "Apto 45, Sala 102" },
    { name: "bairro", label: "Bairro", type: "text", width: "half", placeholder: "Ex: Centro" },
    { name: "cidade", label: "Cidade", type: "text", width: "half" },
    { name: "telefone", label: "Telefone", type: "text", width: "half" },
    { name: "email", label: "Email", type: "email", width: "half" },
    { name: "areas_atuacao", label: "Áreas de Atuação", type: "json", width: "full" },
    { name: "ativo", label: "Ativo", type: "boolean", width: "half" },
  ],
};

// === USUÁRIOS ===

export const usersConfig: CrudPageConfig = {
  table: "users",
  title: "Usuarios",
  icon: <UserPlus size={24} />,
  fields: [
    { name: "name", label: "Nome", type: "text", required: true, width: "half" },
    { name: "email", label: "Email", type: "email", required: true, width: "half" },
    { name: "password", label: "Senha", type: "password", required: true, width: "full", confirmField: "password_confirm", placeholder: "Digite a senha" },
    { name: "picture_url", label: "URL da Foto", type: "text", width: "full" },
    { name: "super", label: "Superusuário", type: "boolean", width: "half" },
  ],
};

export const empresaDocumentosConfig: CrudPageConfig = {
  table: "empresa-documentos",
  title: "Documentos da Empresa",
  icon: <FileText size={24} />,
  parentFk: "empresa_id",
  parentTable: "empresas",
  parentLabelField: "razao_social",
  fields: [
    { name: "empresa_id", label: "Empresa ID", type: "text", required: true, width: "half" },
    { name: "tipo", label: "Tipo", type: "select", required: true, options: enumOpts([
        ["contrato_social", "Contrato Social"],
        ["atestado_capacidade", "Atestado de Capacidade Técnica"],
        ["balanco", "Balanço Patrimonial"],
        ["alvara", "Alvará / Licença Sanitária"],
        ["registro_conselho", "Registro em Conselho"],
        ["procuracao", "Procuração"],
        ["certidao_negativa", "Certidão Negativa Estadual"],
        ["habilitacao_fiscal", "Habilitação Fiscal"],
        ["habilitacao_economica", "Habilitação Econômico-Financeira"],
        ["qualificacao_tecnica", "Qualificação Técnica"],
        ["afe", "Autorização de Funcionamento ANVISA (AFE)"],
        ["cbpad", "Boas Práticas de Distribuição ANVISA (CBPAD)"],
        ["cbpp", "Boas Práticas de Produção ANVISA (CBPP)"],
        ["bombeiros", "Auto de Vistoria do Corpo de Bombeiros"],
        ["outro", "Outro / Certificado ISO / Acreditação"],
      ]), width: "half" },
    { name: "nome_arquivo", label: "Nome do Arquivo", type: "text", required: true, width: "half" },
    { name: "path_arquivo", label: "Caminho do Arquivo", type: "text", required: true, width: "half" },
    { name: "data_emissao", label: "Data de Emissão", type: "date", width: "half" },
    { name: "data_vencimento", label: "Data de Vencimento", type: "date", width: "half" },
    { name: "processado", label: "Processado", type: "boolean", width: "half" },
  ],
};

export const empresaCertidoesConfig: CrudPageConfig = {
  table: "empresa-certidoes",
  title: "Certidões da Empresa",
  icon: <Shield size={24} />,
  parentFk: "empresa_id",
  parentTable: "empresas",
  parentLabelField: "razao_social",
  fields: [
    { name: "empresa_id", label: "Empresa ID", type: "text", required: true, width: "half" },
    { name: "tipo", label: "Tipo", type: "select", required: true, options: enumOpts(["cnd_federal", "cnd_estadual", "cnd_municipal", "fgts", "trabalhista", "outro"]), width: "half" },
    { name: "orgao_emissor", label: "Órgão Emissor", type: "text", width: "half" },
    { name: "numero", label: "Número", type: "text", width: "half" },
    { name: "data_emissao", label: "Data de Emissão", type: "date", width: "half" },
    { name: "data_vencimento", label: "Data de Vencimento", type: "date", required: true, width: "half" },
    { name: "path_arquivo", label: "Caminho do Arquivo", type: "text", width: "half" },
    { name: "status", label: "Status", type: "select", options: enumOpts(["valida", "vencida", "pendente"]), width: "half" },
    { name: "url_consulta", label: "URL de Consulta", type: "text", width: "full" },
  ],
};

export const empresaResponsaveisConfig: CrudPageConfig = {
  table: "empresa-responsaveis",
  // F05-01: renomeado submenu pra abranger Representantes Legais + Tecnicos + Prepostos
  title: "Responsáveis e Representantes",
  icon: <Users size={24} />,
  parentFk: "empresa_id",
  parentTable: "empresas",
  parentLabelField: "razao_social",
  fields: [
    { name: "empresa_id", label: "Empresa ID", type: "text", required: true, width: "half" },
    { name: "nome", label: "Nome", type: "text", required: true, width: "half" },
    { name: "cargo", label: "Cargo", type: "text", width: "half" },
    { name: "cpf", label: "CPF", type: "text", width: "half" },
    { name: "email", label: "Email", type: "email", width: "half" },
    { name: "telefone", label: "Telefone", type: "text", width: "half" },
    { name: "tipo", label: "Tipo", type: "select", options: enumOpts([
      ["representante_legal", "Representante Legal (assina contratos)"],
      ["preposto", "Preposto (representa em pregão — exige documento de outorga)"],
      ["tecnico", "Responsável Técnico (responde pelo produto)"],
    ]), width: "half" },
    // F05-02: validade do mandato/procuracao
    { name: "documento_validade", label: "Validade do mandato/procuração", type: "date", width: "half" },
    // F05-03: documento de outorga (obrigatorio principalmente para preposto)
    { name: "documento_descricao", label: "Documento de outorga (descrição)", type: "text", width: "half", placeholder: "Ex: Procuração 2026, Contrato Social cláusula 5" },
    { name: "documento_path", label: "Caminho/URL do documento (PDF)", type: "text", width: "full", placeholder: "Caminho do PDF da procuração/estatuto/contrato" },
  ],
};

export const beneficiosFiscaisNcmConfig: CrudPageConfig = {
  table: "beneficios-fiscais-ncm",
  title: "Benefícios Fiscais NCM",
  icon: <DollarSign size={24} />,
  fields: [
    { name: "ncm", label: "NCM", type: "text", required: true, width: "half", placeholder: "3822.00.90" },
    { name: "descricao", label: "Descrição", type: "text", width: "half", placeholder: "Reagentes de diagnóstico" },
    { name: "icms", label: "ICMS (%)", type: "number", width: "half" },
    { name: "ipi", label: "IPI (%)", type: "number", width: "half" },
    { name: "pis", label: "PIS (%)", type: "number", width: "half" },
    { name: "cofins", label: "COFINS (%)", type: "number", width: "half" },
    { name: "isencao_icms", label: "Isenção ICMS", type: "boolean", width: "half" },
    { name: "base_legal", label: "Base Legal", type: "text", width: "full", placeholder: "Convênio ICMS 100/97" },
    { name: "ativo", label: "Ativo", type: "boolean", width: "half" },
  ],
};

// === 2. PORTFOLIO ===

// ─── Formulário customizado de criação de Produto (Área → Classe → Subclasse → Máscara) ─

interface SpecCampo {
  campo: string;
  tipo: "texto" | "numero" | "decimal" | "select" | "boolean";
  unidade?: string;
  placeholder?: string;
  opcoes?: string[];
  obrigatorio?: boolean;
}

function parseMascara(raw: unknown): SpecCampo[] {
  try {
    let mascara = typeof raw === "string" ? JSON.parse(raw) : raw;
    // Handle double-encoded JSON
    if (typeof mascara === "string") mascara = JSON.parse(mascara);
    if (!Array.isArray(mascara) || mascara.length === 0) return [];
    return mascara.map((m: Record<string, unknown>) => ({
      campo: String(m.campo || m.nome || ""),
      tipo: (m.tipo as SpecCampo["tipo"]) || "texto",
      unidade: m.unidade ? String(m.unidade) : undefined,
      placeholder: m.placeholder ? String(m.placeholder) : undefined,
      opcoes: Array.isArray(m.opcoes) ? m.opcoes.map(String) : undefined,
      obrigatorio: Boolean(m.obrigatorio),
    }));
  } catch { return []; }
}

function ProdutoCreateForm({ onSaved, onCancel }: { onSaved: () => void; onCancel: () => void }) {
  const [areas, setAreas] = React.useState<Record<string, unknown>[]>([]);
  const [classes, setClasses] = React.useState<Record<string, unknown>[]>([]);
  const [subclasses, setSubclasses] = React.useState<Record<string, unknown>[]>([]);

  const [areaId, setAreaId] = React.useState("");
  const [classeId, setClasseId] = React.useState("");
  const [subclasseId, setSubclasseId] = React.useState("");
  const [nome, setNome] = React.useState("");
  const [fabricante, setFabricante] = React.useState("");
  const [modelo, setModelo] = React.useState("");
  const [ncm, setNcm] = React.useState("");
  const [precoRef, setPrecoRef] = React.useState("");
  const [descricao, setDescricao] = React.useState("");
  const [specs, setSpecs] = React.useState<Record<string, string>>({});
  const [categoria, setCategoria] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const CATEGORIAS = ["equipamento", "reagente", "insumo_hospitalar", "insumo_laboratorial", "informatica", "redes", "mobiliario", "eletronico", "outro"];

  // Carregar hierarquia
  React.useEffect(() => {
    Promise.all([
      crudList("areas-produto", { limit: 100 }),
      crudList("classes-produto-v2", { limit: 200 }),
      crudList("subclasses-produto", { limit: 500 }),
    ]).then(([a, c, s]) => {
      setAreas(a.items || []);
      setClasses(c.items || []);
      setSubclasses(s.items || []);
    }).catch(() => {});
  }, []);

  // Filtros cascata
  const classesFiltradas = areaId ? classes.filter(c => String(c.area_id) === areaId) : [];
  const subclassesFiltradas = classeId ? subclasses.filter(s => String(s.classe_id) === classeId) : [];

  // Máscara da subclasse
  const subSelecionada = subclasses.find(s => String(s.id) === subclasseId);
  const mascara: SpecCampo[] = subSelecionada ? parseMascara(subSelecionada.campos_mascara) : [];

  const handleAreaChange = (v: string) => { setAreaId(v); setClasseId(""); setSubclasseId(""); setNcm(""); setSpecs({}); };
  const handleClasseChange = (v: string) => { setClasseId(v); setSubclasseId(""); setNcm(""); setSpecs({}); };
  const handleSubclasseChange = (v: string) => {
    setSubclasseId(v);
    setSpecs({});
    const sub = subclasses.find(s => String(s.id) === v);
    if (sub && sub.ncms) {
      const ncms = Array.isArray(sub.ncms) ? sub.ncms : [sub.ncms];
      setNcm(String(ncms[0] || ""));
    }
  };

  const handleSave = async () => {
    if (!nome.trim()) { setError("Nome é obrigatório"); return; }
    setSaving(true);
    setError(null);
    try {
      // 1. Criar produto
      const produto = await crudCreate("produtos", {
        nome,
        fabricante,
        modelo,
        ncm,
        subclasse_id: subclasseId || null,
        categoria: categoria || "outro",
        preco_referencia: precoRef ? Number(precoRef) : null,
        descricao,
        status_pipeline: "cadastrado",
      });
      const produtoId = String(produto.id);

      // 2. Salvar especificações da máscara
      const specsPreenchidas = Object.entries(specs).filter(([, v]) => v.trim());
      for (const [campo, valor] of specsPreenchidas) {
        const specDef = mascara.find(m => m.campo === campo);
        await crudCreate("produtos-especificacoes", {
          produto_id: produtoId,
          nome_especificacao: campo,
          valor,
          unidade: specDef?.unidade || null,
        });
      }

      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar");
    } finally {
      setSaving(false);
    }
  };

  const selectStyle: React.CSSProperties = { width: "100%", padding: "8px 12px", borderRadius: 6, border: "1px solid var(--border, #333)", background: "var(--bg-secondary, #1a1a2e)", color: "var(--text-primary, #e2e8f0)", fontSize: 14 };
  const inputStyle = selectStyle;
  const labelStyle: React.CSSProperties = { display: "block", fontSize: 13, fontWeight: 500, marginBottom: 4, color: "var(--text-secondary, #94a3b8)" };

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-header-left">
          <button className="crud-back-btn" onClick={onCancel} title="Cancelar" style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)" }}>
            ← Voltar
          </button>
          <h3 className="card-title">Novo Produto</h3>
        </div>
      </div>
      <div className="card-content">
        {error && <div className="crud-message crud-message-error" style={{ marginBottom: 12 }}>{error}</div>}

        {/* Linha 1: Nome + Área */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
          <div>
            <label style={labelStyle}>Nome do Produto *</label>
            <input style={inputStyle} value={nome} onChange={e => setNome(e.target.value)} placeholder="Ex: Centrífuga Refrigerada" />
          </div>
          <div>
            <label style={labelStyle}>Área</label>
            <select style={selectStyle} value={areaId} onChange={e => handleAreaChange(e.target.value)}>
              <option value="">Selecione a área...</option>
              {areas.map(a => <option key={String(a.id)} value={String(a.id)}>{String(a.nome)}</option>)}
            </select>
          </div>
        </div>

        {/* Linha 2: Classe + Subclasse */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
          <div>
            <label style={labelStyle}>Classe</label>
            <select style={selectStyle} value={classeId} onChange={e => handleClasseChange(e.target.value)} disabled={!areaId}>
              <option value="">Selecione a classe...</option>
              {classesFiltradas.map(c => <option key={String(c.id)} value={String(c.id)}>{String(c.nome)}</option>)}
            </select>
          </div>
          <div>
            <label style={labelStyle}>Subclasse</label>
            <select style={selectStyle} value={subclasseId} onChange={e => handleSubclasseChange(e.target.value)} disabled={!classeId}>
              <option value="">Selecione a subclasse...</option>
              {subclassesFiltradas.map(s => <option key={String(s.id)} value={String(s.id)}>{String(s.nome)}</option>)}
            </select>
          </div>
        </div>

        {/* Linha 3: NCM + Fabricante + Modelo */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 16 }}>
          <div>
            <label style={labelStyle}>NCM <span style={{ fontSize: 11, color: "#64748b" }}>(auto da subclasse)</span></label>
            <input style={inputStyle} value={ncm} onChange={e => setNcm(e.target.value)} placeholder="Selecione a subclasse..." />
          </div>
          <div>
            <label style={labelStyle}>Fabricante</label>
            <input style={inputStyle} value={fabricante} onChange={e => setFabricante(e.target.value)} placeholder="Ex: Shimadzu" />
          </div>
          <div>
            <label style={labelStyle}>Modelo</label>
            <input style={inputStyle} value={modelo} onChange={e => setModelo(e.target.value)} placeholder="Ex: UV-2600i" />
          </div>
        </div>

        {/* Linha 4: Categoria + Preço + Descrição */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 16 }}>
          <div>
            <label style={labelStyle}>Categoria *</label>
            <select style={selectStyle} value={categoria} onChange={e => setCategoria(e.target.value)}>
              <option value="">Selecione...</option>
              {CATEGORIAS.map(c => <option key={c} value={c}>{c.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase())}</option>)}
            </select>
          </div>
          <div>
            <label style={labelStyle}>Preço Referência (R$)</label>
            <input style={inputStyle} type="number" value={precoRef} onChange={e => setPrecoRef(e.target.value)} placeholder="Ex: 25000" />
          </div>
          <div>
            <label style={labelStyle}>Descrição</label>
            <input style={inputStyle} value={descricao} onChange={e => setDescricao(e.target.value)} placeholder="Descrição do produto" />
          </div>
        </div>

        {/* Especificações dinâmicas da máscara */}
        {mascara.length > 0 && (
          <div style={{ marginTop: 8, marginBottom: 16, padding: 16, background: "rgba(139,92,246,0.06)", borderRadius: 8, border: "1px solid rgba(139,92,246,0.2)" }}>
            <h4 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, color: "#8b5cf6", display: "flex", alignItems: "center", gap: 6 }}>
              <Sliders size={16} />
              Especificações Técnicas — {String(subSelecionada?.nome || "")}
            </h4>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              {mascara.map(spec => (
                <div key={spec.campo}>
                  <label style={labelStyle}>
                    {spec.campo}
                    {spec.unidade && <span style={{ color: "#64748b" }}> ({spec.unidade})</span>}
                    {spec.obrigatorio && <span style={{ color: "#ef4444" }}> *</span>}
                  </label>
                  {spec.tipo === "select" && spec.opcoes ? (
                    <select style={selectStyle} value={specs[spec.campo] || ""} onChange={e => setSpecs(p => ({ ...p, [spec.campo]: e.target.value }))}>
                      <option value="">Selecione...</option>
                      {spec.opcoes.map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : spec.tipo === "boolean" ? (
                    <select style={selectStyle} value={specs[spec.campo] || ""} onChange={e => setSpecs(p => ({ ...p, [spec.campo]: e.target.value }))}>
                      <option value="">Selecione...</option>
                      <option value="Sim">Sim</option>
                      <option value="Não">Não</option>
                    </select>
                  ) : (
                    <input
                      style={inputStyle}
                      type={spec.tipo === "numero" || spec.tipo === "decimal" ? "number" : "text"}
                      value={specs[spec.campo] || ""}
                      onChange={e => setSpecs(p => ({ ...p, [spec.campo]: e.target.value }))}
                      placeholder={spec.placeholder || ""}
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Botões */}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button className="action-button action-button-secondary" onClick={onCancel}>Cancelar</button>
          <button className="action-button action-button-primary" onClick={handleSave} disabled={saving || !nome.trim()}>
            {saving ? "Salvando..." : "Salvar Produto"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Formulário de edição de Produto (mostra máscara da subclasse + specs existentes) ─

function ProdutoEditForm({ item, onSaved, onCancel }: { item: Record<string, unknown>; onSaved: () => void; onCancel: () => void }) {
  const produtoId = String(item.id || "");
  const [areas, setAreas] = React.useState<Record<string, unknown>[]>([]);
  const [classes, setClasses] = React.useState<Record<string, unknown>[]>([]);
  const [subclasses, setSubclasses] = React.useState<Record<string, unknown>[]>([]);
  const [existingSpecs, setExistingSpecs] = React.useState<Record<string, unknown>[]>([]);

  const [areaId, setAreaId] = React.useState("");
  const [classeId, setClasseId] = React.useState("");
  const [subclasseId, setSubclasseId] = React.useState(String(item.subclasse_id || ""));
  const [nome, setNome] = React.useState(String(item.nome || ""));
  const [fabricante, setFabricante] = React.useState(String(item.fabricante || ""));
  const [modelo, setModelo] = React.useState(String(item.modelo || ""));
  const [ncm, setNcm] = React.useState(String(item.ncm || ""));
  const [precoRef, setPrecoRef] = React.useState(item.preco_referencia != null ? String(item.preco_referencia) : "");
  const [categoria] = React.useState(String(item.categoria || ""));
  const [descricao, setDescricao] = React.useState(String(item.descricao || ""));
  const [statusPipeline, setStatusPipeline] = React.useState(String(item.status_pipeline || "cadastrado"));
  const [registroAnvisa, setRegistroAnvisa] = React.useState(String(item.registro_anvisa || ""));
  const [specs, setSpecs] = React.useState<Record<string, string>>({});
  const [saving, setSaving] = React.useState(false);
  const [deleting, setDeleting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [loaded, setLoaded] = React.useState(false);

  // Carregar hierarquia + specs existentes
  React.useEffect(() => {
    Promise.all([
      crudList("areas-produto", { limit: 100 }),
      crudList("classes-produto-v2", { limit: 200 }),
      crudList("subclasses-produto", { limit: 500 }),
      crudList("produtos-especificacoes", { parent_id: produtoId, limit: 200 }),
    ]).then(([a, c, s, specsRes]) => {
      setAreas(a.items || []);
      setClasses(c.items || []);
      setSubclasses(s.items || []);
      setExistingSpecs(specsRes.items || []);

      // Preencher specs existentes no form
      const specsMap: Record<string, string> = {};
      for (const sp of (specsRes.items || [])) {
        specsMap[String(sp.nome_especificacao || sp.campo || "")] = String(sp.valor || "");
      }
      setSpecs(specsMap);

      // Resolver cascata a partir da subclasse_id do produto
      const subId = String(item.subclasse_id || "");
      if (subId) {
        const sub = (s.items || []).find((x: Record<string, unknown>) => String(x.id) === subId);
        if (sub) {
          const clsId = String(sub.classe_id || "");
          setClasseId(clsId);
          const cls = (c.items || []).find((x: Record<string, unknown>) => String(x.id) === clsId);
          if (cls) setAreaId(String(cls.area_id || ""));
        }
      }
      setLoaded(true);
    }).catch(() => setLoaded(true));
  }, [produtoId, item.subclasse_id]);

  // Filtros cascata
  const classesFiltradas = areaId ? classes.filter(c => String(c.area_id) === areaId) : [];
  const subclassesFiltradas = classeId ? subclasses.filter(s => String(s.classe_id) === classeId) : [];

  // Máscara da subclasse
  const subSelecionada = subclasses.find(s => String(s.id) === subclasseId);
  const mascara: SpecCampo[] = subSelecionada ? parseMascara(subSelecionada.campos_mascara) : [];

  const handleAreaChange = (v: string) => { setAreaId(v); setClasseId(""); setSubclasseId(""); setSpecs({}); };
  const handleClasseChange = (v: string) => { setClasseId(v); setSubclasseId(""); setSpecs({}); };
  const handleSubclasseChange = (v: string) => {
    setSubclasseId(v);
    // Manter specs existentes que correspondem à nova máscara
    const sub = subclasses.find(s => String(s.id) === v);
    if (sub) {
      const newMascara = parseMascara(sub.campos_mascara);
      const campos = new Set(newMascara.map(m => m.campo));
      const kept: Record<string, string> = {};
      for (const [k, val] of Object.entries(specs)) {
        if (campos.has(k)) kept[k] = val;
      }
      setSpecs(kept);
      // Auto NCM
      if (sub.ncms) {
        const ncms = Array.isArray(sub.ncms) ? sub.ncms : [sub.ncms];
        setNcm(String(ncms[0] || ""));
      }
    }
  };

  const handleSave = async () => {
    if (!nome.trim()) { setError("Nome é obrigatório"); return; }
    setSaving(true);
    setError(null);
    try {
      // 1. Atualizar produto — derivar categoria da classe se possível
      const classeObj = classes.find((c: Record<string, unknown>) => String(c.id) === classeId);
      const classeNome = classeObj ? String(classeObj.nome || "").toLowerCase() : "";
      const catDerivada = classeNome.includes("reagente") ? "reagente"
        : classeNome.includes("equipamento") ? "equipamento"
        : classeNome.includes("insumo") ? "insumo_hospitalar"
        : classeNome.includes("inform") ? "informatica"
        : classeNome.includes("rede") ? "redes"
        : classeNome.includes("mobil") ? "mobiliario"
        : categoria || "outro";
      await crudUpdate("produtos", produtoId, {
        nome, fabricante, modelo, ncm,
        subclasse_id: subclasseId || null,
        categoria: catDerivada,
        preco_referencia: precoRef ? Number(precoRef) : null,
        descricao,
        status_pipeline: statusPipeline,
        registro_anvisa: registroAnvisa || null,
      });

      // 2. Deletar specs antigas e recriar
      for (const sp of existingSpecs) {
        await crudDelete("produtos-especificacoes", String(sp.id));
      }

      // 3. Criar specs novas
      const specsPreenchidas = Object.entries(specs).filter(([, v]) => v.trim());
      for (const [campo, valor] of specsPreenchidas) {
        const specDef = mascara.find(m => m.campo === campo);
        await crudCreate("produtos-especificacoes", {
          produto_id: produtoId,
          nome_especificacao: campo,
          valor,
          unidade: specDef?.unidade || null,
        });
      }

      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao salvar");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`Excluir o produto "${nome}"?`)) return;
    setDeleting(true);
    try {
      await crudDelete("produtos", produtoId);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao excluir");
      setDeleting(false);
    }
  };

  const selectStyle: React.CSSProperties = { width: "100%", padding: "8px 12px", borderRadius: 6, border: "1px solid var(--border, #333)", background: "var(--bg-secondary, #1a1a2e)", color: "var(--text-primary, #e2e8f0)", fontSize: 14 };
  const inputStyle = selectStyle;
  const labelStyle: React.CSSProperties = { display: "block", fontSize: 13, fontWeight: 500, marginBottom: 4, color: "var(--text-secondary, #94a3b8)" };

  if (!loaded) return <div style={{ padding: 24, textAlign: "center", color: "#64748b" }}>Carregando...</div>;

  return (
    <div className="card">
      <div className="card-header">
        <div className="card-header-left">
          <button className="crud-back-btn" onClick={onCancel} title="Voltar" style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-secondary)" }}>
            ← Voltar
          </button>
          <h3 className="card-title">Editar Produto</h3>
        </div>
        <div className="card-header-right" style={{ display: "flex", gap: 8 }}>
          <button className="action-button action-button-danger" onClick={handleDelete} disabled={deleting}>
            {deleting ? "Excluindo..." : "Excluir"}
          </button>
        </div>
      </div>
      <div className="card-content">
        {error && <div className="crud-message crud-message-error" style={{ marginBottom: 12 }}>{error}</div>}

        {/* Linha 1: Nome + Área */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
          <div>
            <label style={labelStyle}>Nome do Produto *</label>
            <input style={inputStyle} value={nome} onChange={e => setNome(e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>Área</label>
            <select style={selectStyle} value={areaId} onChange={e => handleAreaChange(e.target.value)}>
              <option value="">Selecione a área...</option>
              {areas.map(a => <option key={String(a.id)} value={String(a.id)}>{String(a.nome)}</option>)}
            </select>
          </div>
        </div>

        {/* Linha 2: Classe + Subclasse */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
          <div>
            <label style={labelStyle}>Classe</label>
            <select style={selectStyle} value={classeId} onChange={e => handleClasseChange(e.target.value)} disabled={!areaId}>
              <option value="">Selecione a classe...</option>
              {classesFiltradas.map(c => <option key={String(c.id)} value={String(c.id)}>{String(c.nome)}</option>)}
            </select>
          </div>
          <div>
            <label style={labelStyle}>Subclasse</label>
            <select style={selectStyle} value={subclasseId} onChange={e => handleSubclasseChange(e.target.value)} disabled={!classeId}>
              <option value="">Selecione a subclasse...</option>
              {subclassesFiltradas.map(s => <option key={String(s.id)} value={String(s.id)}>{String(s.nome)}</option>)}
            </select>
          </div>
        </div>

        {/* Linha 3: NCM + Fabricante + Modelo */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 16 }}>
          <div>
            <label style={labelStyle}>NCM</label>
            <input style={inputStyle} value={ncm} onChange={e => setNcm(e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>Fabricante</label>
            <input style={inputStyle} value={fabricante} onChange={e => setFabricante(e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>Modelo</label>
            <input style={inputStyle} value={modelo} onChange={e => setModelo(e.target.value)} />
          </div>
        </div>

        {/* Linha 4: Preço + Status + ANVISA + Descrição */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 16, marginBottom: 16 }}>
          <div>
            <label style={labelStyle}>Preço Referência (R$)</label>
            <input style={inputStyle} type="number" value={precoRef} onChange={e => setPrecoRef(e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>Status Pipeline</label>
            <select style={selectStyle} value={statusPipeline} onChange={e => setStatusPipeline(e.target.value)}>
              <option value="cadastrado">Cadastrado</option>
              <option value="qualificado">Qualificado</option>
              <option value="ofertado">Ofertado</option>
              <option value="vencedor">Vencedor</option>
            </select>
          </div>
          <div>
            <label style={labelStyle}>Registro ANVISA</label>
            <input style={inputStyle} value={registroAnvisa} onChange={e => setRegistroAnvisa(e.target.value)} />
          </div>
          <div>
            <label style={labelStyle}>Descrição</label>
            <input style={inputStyle} value={descricao} onChange={e => setDescricao(e.target.value)} />
          </div>
        </div>

        {/* Especificações dinâmicas da máscara */}
        {mascara.length > 0 && (
          <div style={{ marginTop: 8, marginBottom: 16, padding: 16, background: "rgba(139,92,246,0.06)", borderRadius: 8, border: "1px solid rgba(139,92,246,0.2)" }}>
            <h4 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, color: "#8b5cf6", display: "flex", alignItems: "center", gap: 6 }}>
              <Sliders size={16} />
              Especificações Técnicas — {String(subSelecionada?.nome || "")}
            </h4>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              {mascara.map(spec => (
                <div key={spec.campo}>
                  <label style={labelStyle}>
                    {spec.campo}
                    {spec.unidade && <span style={{ color: "#64748b" }}> ({spec.unidade})</span>}
                    {spec.obrigatorio && <span style={{ color: "#ef4444" }}> *</span>}
                  </label>
                  {spec.tipo === "select" && spec.opcoes ? (
                    <select style={selectStyle} value={specs[spec.campo] || ""} onChange={e => setSpecs(p => ({ ...p, [spec.campo]: e.target.value }))}>
                      <option value="">Selecione...</option>
                      {spec.opcoes.map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : spec.tipo === "boolean" ? (
                    <select style={selectStyle} value={specs[spec.campo] || ""} onChange={e => setSpecs(p => ({ ...p, [spec.campo]: e.target.value }))}>
                      <option value="">Selecione...</option>
                      <option value="Sim">Sim</option>
                      <option value="Não">Não</option>
                    </select>
                  ) : (
                    <input
                      style={inputStyle}
                      type={spec.tipo === "numero" || spec.tipo === "decimal" ? "number" : "text"}
                      value={specs[spec.campo] || ""}
                      onChange={e => setSpecs(p => ({ ...p, [spec.campo]: e.target.value }))}
                      placeholder={spec.placeholder || ""}
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Specs que existem mas não estão na máscara (dados legados) */}
        {(() => {
          const mascaraCampos = new Set(mascara.map(m => m.campo));
          const legados = Object.entries(specs).filter(([k, v]) => !mascaraCampos.has(k) && v.trim());
          if (legados.length === 0) return null;
          return (
            <div style={{ marginBottom: 16, padding: 16, background: "rgba(234,179,8,0.06)", borderRadius: 8, border: "1px solid rgba(234,179,8,0.2)" }}>
              <h4 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: "#eab308" }}>
                Especificações:
              </h4>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                {legados.map(([campo, valor]) => (
                  <div key={campo}>
                    <label style={labelStyle}>{campo}</label>
                    <input style={inputStyle} value={valor} onChange={e => setSpecs(p => ({ ...p, [campo]: e.target.value }))} />
                  </div>
                ))}
              </div>
            </div>
          );
        })()}

        {/* Botões */}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button className="action-button action-button-secondary" onClick={onCancel}>Cancelar</button>
          <button className="action-button action-button-primary" onClick={handleSave} disabled={saving || !nome.trim()}>
            {saving ? "Salvando..." : "Salvar Produto"}
          </button>
        </div>
      </div>
    </div>
  );
}

export const produtosConfig: CrudPageConfig = {
  table: "produtos",
  title: "Produtos",
  icon: <Package size={24} />,
  fields: [
    { name: "nome", label: "Nome", type: "text", required: true, width: "half" },
    { name: "codigo_interno", label: "Código Interno", type: "text", width: "half" },
    { name: "categoria", label: "Categoria", type: "select", required: true, options: enumOpts(["equipamento", "reagente", "insumo_hospitalar", "insumo_laboratorial", "informatica", "redes", "mobiliario", "eletronico", "outro"]), width: "half" },
    { name: "subclasse_id", label: "Subclasse", type: "fk", fkTable: "subclasses-produto", fkLabel: "nome", width: "half" },
    { name: "fabricante", label: "Fabricante", type: "text", width: "half" },
    { name: "modelo", label: "Modelo", type: "text", width: "half" },
    { name: "ncm", label: "NCM", type: "text", width: "half" },
    { name: "preco_referencia", label: "Preço Referência", type: "decimal", width: "half" },
    { name: "status_pipeline", label: "Status Pipeline", type: "select", options: [
      { value: "cadastrado", label: "Cadastrado" },
      { value: "qualificado", label: "Qualificado" },
      { value: "ofertado", label: "Ofertado" },
      { value: "vencedor", label: "Vencedor" },
    ], width: "half" },
    { name: "registro_anvisa", label: "Registro ANVISA", type: "text", placeholder: "Ex: 80100300012", width: "half" },
    { name: "anvisa_status", label: "Status ANVISA", type: "select", options: [
      { value: "", label: "N/A" },
      { value: "ativo", label: "Ativo" },
      { value: "em_analise", label: "Em Analise" },
      { value: "cancelado", label: "Cancelado" },
    ], width: "half" },
    { name: "descricao", label: "Descrição", type: "textarea", width: "full" },
  ],
  renderCreateForm: (props) => <ProdutoCreateForm {...props} />,
  renderEditForm: (props) => <ProdutoEditForm {...props} />,
};

export const produtosEspecificacoesConfig: CrudPageConfig = {
  table: "produtos-especificacoes",
  title: "Especificações de Produtos",
  icon: <Sliders size={24} />,
  parentFk: "produto_id",
  parentTable: "produtos",
  parentLabelField: "nome",
  fields: [
    { name: "produto_id", label: "Produto ID", type: "text", required: true, width: "half" },
    { name: "nome_especificacao", label: "Especificação", type: "text", required: true, width: "half" },
    { name: "valor", label: "Valor", type: "text", required: true, width: "half" },
    { name: "unidade", label: "Unidade", type: "text", width: "half" },
    { name: "valor_numerico", label: "Valor Numérico", type: "decimal", width: "half" },
    { name: "operador", label: "Operador", type: "text", width: "half", placeholder: ">=, <=, =, range" },
    { name: "valor_min", label: "Valor Mín", type: "decimal", width: "half" },
    { name: "valor_max", label: "Valor Máx", type: "decimal", width: "half" },
    { name: "pagina_origem", label: "Página Origem", type: "number", width: "half" },
  ],
};

export const produtosDocumentosConfig: CrudPageConfig = {
  table: "produtos-documentos",
  title: "Documentos de Produtos",
  icon: <FileText size={24} />,
  parentFk: "produto_id",
  parentTable: "produtos",
  parentLabelField: "nome",
  fields: [
    { name: "produto_id", label: "Produto ID", type: "text", required: true, width: "half" },
    { name: "tipo", label: "Tipo", type: "select", required: true, options: enumOpts(["manual", "ficha_tecnica", "certificado_anvisa", "certificado_outro"]), width: "half" },
    { name: "nome_arquivo", label: "Nome do Arquivo", type: "text", required: true, width: "half" },
    { name: "path_arquivo", label: "Caminho do Arquivo", type: "text", required: true, width: "half" },
    { name: "processado", label: "Processado", type: "boolean", width: "half" },
  ],
};

// === CLASSIFICAÇÃO DE PRODUTOS ===

export const areasProdutoConfig: CrudPageConfig = {
  table: "areas-produto",
  title: "Areas de Produto",
  icon: <FolderTree size={24} />,
  fields: [
    { name: "nome", label: "Nome", type: "text", required: true, width: "half" },
    { name: "descricao", label: "Descricao", type: "textarea", width: "full" },
    { name: "ativo", label: "Ativo", type: "boolean", width: "half" },
    { name: "ordem", label: "Ordem", type: "number", width: "half" },
  ],
};

export const classesProdutoV2Config: CrudPageConfig = {
  table: "classes-produto-v2",
  title: "Classes de Produto",
  icon: <Tag size={24} />,
  parentFk: "area_id",
  parentTable: "areas-produto",
  parentLabelField: "nome",
  fields: [
    { name: "area_id", label: "Área", type: "fk", fkTable: "areas-produto", fkLabel: "nome", required: true, width: "half" },
    { name: "nome", label: "Nome", type: "text", required: true, width: "half" },
    { name: "descricao", label: "Descrição", type: "textarea", width: "full" },
    { name: "ativo", label: "Ativo", type: "boolean", width: "half" },
    { name: "ordem", label: "Ordem", type: "number", width: "half" },
  ],
};

export const subclassesProdutoConfig: CrudPageConfig = {
  table: "subclasses-produto",
  title: "Subclasses de Produto",
  icon: <Tags size={24} />,
  parentFk: "classe_id",
  parentTable: "classes-produto-v2",
  parentLabelField: "nome",
  grandparentTable: "areas-produto",
  grandparentFk: "area_id",
  grandparentLabelField: "Área",
  fields: [
    { name: "classe_id", label: "Classe", type: "fk", fkTable: "classes-produto-v2", fkLabel: "nome", required: true, width: "half" },
    { name: "nome", label: "Nome", type: "text", required: true, width: "half" },
    { name: "ncms", label: "NCMs", type: "json", width: "full" },
    { name: "campos_mascara", label: "Máscara de Campos", type: "json", width: "full", renderCustom: (value, onChange) => React.createElement(CamposMascaraEditor, { value, onChange }) },
    { name: "ativo", label: "Ativo", type: "boolean", width: "half" },
    { name: "ordem", label: "Ordem", type: "number", width: "half" },
  ],
};

// === 2B. MODALIDADES E ORIGENS ===

export const modalidadesLicitacaoConfig: CrudPageConfig = {
  table: "modalidades-licitacao",
  title: "Modalidades de Licitação",
  icon: <Gavel size={24} />,
  fields: [
    { name: "nome", label: "Nome", type: "text", required: true, width: "half" },
    { name: "descricao", label: "Descrição", type: "textarea", width: "full" },
    { name: "ativo", label: "Ativo", type: "boolean", width: "half" },
    { name: "ordem", label: "Ordem", type: "number", width: "half" },
  ],
};

export const origensOrgaoConfig: CrudPageConfig = {
  table: "origens-orgao",
  title: "Origens de Órgão",
  icon: <GitBranch size={24} />,
  fields: [
    { name: "nome", label: "Nome", type: "text", required: true, width: "half" },
    { name: "descricao", label: "Descrição", type: "textarea", width: "full" },
    { name: "ativo", label: "Ativo", type: "boolean", width: "half" },
    { name: "ordem", label: "Ordem", type: "number", width: "half" },
  ],
};

// === 3. FONTES ===

export const fontesEditaisConfig: CrudPageConfig = {
  table: "fontes-editais",
  title: "Fontes de Editais",
  icon: <Search size={24} />,
  fields: [
    { name: "nome", label: "Nome", type: "text", required: true, width: "half" },
    { name: "tipo", label: "Tipo", type: "select", required: true, options: enumOpts(["api", "scraper"]), width: "half" },
    { name: "url_base", label: "URL Base", type: "text", width: "full" },
    { name: "api_key", label: "API Key", type: "text", width: "half" },
    { name: "ativo", label: "Ativo", type: "boolean", width: "half" },
    { name: "descricao", label: "Descrição", type: "textarea", width: "full" },
  ],
};

export const fontesCertidoesConfig: CrudPageConfig = {
  table: "fontes-certidoes",
  title: "Fontes de Certidões",
  icon: <Globe size={24} />,
  fields: [
    { name: "tipo_certidao", label: "Tipo de Certidão", type: "select", required: true, options: enumOpts(["cnd_federal", "cnd_estadual", "cnd_municipal", "fgts", "trabalhista", "outro"]), width: "half" },
    { name: "nome", label: "Nome da Fonte", type: "text", required: true, width: "half", placeholder: "Ex: Receita Federal - CND" },
    { name: "orgao_emissor", label: "Órgão Emissor", type: "text", width: "half", placeholder: "Ex: Receita Federal / PGFN" },
    { name: "url_portal", label: "URL do Portal", type: "text", required: true, width: "full", placeholder: "https://..." },
    { name: "url_api", label: "URL da API (se disponível)", type: "text", width: "full", placeholder: "https://api..." },
    { name: "metodo_acesso", label: "Método de Acesso", type: "select", options: enumOpts([
      ["publico", "Acesso público (sem login)"],
      ["login_senha", "Login + senha"],
      ["certificado_digital", "Certificado digital (.pfx)"],
      ["api_key", "API key"],
    ]), width: "half" },
    // F04-02: label clara — marca quando NÃO for público (requer credencial)
    { name: "requer_autenticacao", label: "Requer credencial para acessar (marque se NÃO for público)", type: "boolean", width: "half" },
    { name: "usuario", label: "Usuário/Login", type: "text", width: "half", placeholder: "Login no portal (se necessário)" },
    { name: "senha_criptografada", label: "Senha", type: "text", width: "half", placeholder: "Deixe em branco para manter. Valor salvo é criptografado." },
    { name: "certificado_path", label: "Caminho do Certificado Digital", type: "text", width: "full", placeholder: "/caminho/certificado.pfx" },
    { name: "api_key", label: "API Key", type: "text", width: "half", placeholder: "Chave de API (se necessário)" },
    { name: "cnpj_consulta", label: "CNPJ para Consulta", type: "text", width: "half", placeholder: "Se diferente do CNPJ da empresa" },
    { name: "uf", label: "UF", type: "text", width: "half", placeholder: "SP (para CND Estadual)" },
    { name: "cidade", label: "Cidade", type: "text", width: "half", placeholder: "São Paulo (para CND Municipal)" },
    { name: "permite_busca_automatica", label: "Permitir Busca Automática (IA)", type: "boolean", width: "half" },
    { name: "ativo", label: "Ativo", type: "boolean", width: "half" },
    { name: "observacoes", label: "Observações", type: "textarea", width: "full", placeholder: "Notas sobre como acessar o portal, requisitos especiais, etc." },
    { name: "ultima_consulta", label: "Última Consulta", type: "datetime", width: "half" },
    { name: "resultado_ultima_consulta", label: "Resultado Última Consulta", type: "select", options: enumOpts(["sucesso", "erro", "timeout", "login_invalido"]), width: "half" },
  ],
};

// === 4. EDITAIS ===

export const editaisConfig: CrudPageConfig = {
  table: "editais",
  title: "Editais",
  icon: <FileCheck size={24} />,
  fields: [
    { name: "numero", label: "Número", type: "text", required: true, width: "half" },
    { name: "orgao", label: "Órgão", type: "text", required: true, width: "half" },
    { name: "orgao_tipo", label: "Tipo de Órgão", type: "select", options: enumOpts(["federal", "estadual", "municipal", "autarquia", "fundacao"]), width: "half" },
    { name: "modalidade_id", label: "Modalidade", type: "fk", fkTable: "modalidades-licitacao", fkLabel: "nome", width: "half" },
    { name: "categoria", label: "Categoria", type: "select", options: enumOpts(["comodato", "venda_equipamento", "aluguel_com_consumo", "aluguel_sem_consumo", "consumo_reagentes", "consumo_insumos", "servicos", "informatica", "redes", "mobiliario", "outro"]), width: "half" },
    { name: "status", label: "Status", type: "select", options: enumOpts(["novo", "analisando", "participando", "proposta_enviada", "em_pregao", "vencedor", "perdedor", "cancelado", "desistido", "aberto", "fechado", "suspenso", "ganho", "perdido"]), width: "half" },
    { name: "objeto", label: "Objeto", type: "textarea", required: true, width: "full" },
    { name: "uf", label: "UF", type: "text", width: "half" },
    { name: "cidade", label: "Cidade", type: "text", width: "half" },
    { name: "valor_referencia", label: "Valor Referência", type: "decimal", width: "half" },
    { name: "data_publicacao", label: "Data Publicação", type: "date", width: "half" },
    { name: "data_abertura", label: "Data Abertura", type: "datetime", width: "half" },
    { name: "data_limite_proposta", label: "Prazo Proposta", type: "datetime", width: "half" },
    { name: "data_limite_impugnacao", label: "Prazo Impugnação", type: "datetime", width: "half" },
    { name: "data_recursos", label: "Prazo Recursos", type: "datetime", width: "half" },
    { name: "fonte", label: "Fonte", type: "text", width: "half" },
    { name: "url", label: "URL", type: "text", width: "full" },
  ],
};

export const editaisRequisitosConfig: CrudPageConfig = {
  table: "editais-requisitos",
  title: "Requisitos de Editais",
  icon: <Layers size={24} />,
  parentFk: "edital_id",
  parentTable: "editais",
  parentLabelFn: (item) => `${item.numero || ""} - ${item.orgao || ""}`,
  fields: [
    { name: "edital_id", label: "Edital ID", type: "text", required: true, width: "half" },
    { name: "tipo", label: "Tipo", type: "select", required: true, options: enumOpts(["tecnico", "documental", "comercial", "legal"]), width: "half" },
    { name: "descricao", label: "Descrição", type: "textarea", required: true, width: "full" },
    { name: "nome_especificacao", label: "Nome Especificação", type: "text", width: "half" },
    { name: "valor_exigido", label: "Valor Exigido", type: "text", width: "half" },
    { name: "operador", label: "Operador", type: "text", width: "half" },
    { name: "valor_numerico", label: "Valor Numérico", type: "decimal", width: "half" },
    { name: "obrigatorio", label: "Obrigatório", type: "boolean", width: "half" },
    { name: "pagina_origem", label: "Página Origem", type: "number", width: "half" },
  ],
};

export const editaisDocumentosConfig: CrudPageConfig = {
  table: "editais-documentos",
  title: "Documentos de Editais",
  icon: <FileText size={24} />,
  parentFk: "edital_id",
  parentTable: "editais",
  parentLabelFn: (item) => `${item.numero || ""} - ${item.orgao || ""}`,
  fields: [
    { name: "edital_id", label: "Edital ID", type: "text", required: true, width: "half" },
    { name: "tipo", label: "Tipo", type: "select", required: true, options: enumOpts(["edital_principal", "termo_referencia", "anexo", "planilha", "outro"]), width: "half" },
    { name: "nome_arquivo", label: "Nome do Arquivo", type: "text", required: true, width: "half" },
    { name: "path_arquivo", label: "Caminho do Arquivo", type: "text", required: true, width: "half" },
    { name: "processado", label: "Processado", type: "boolean", width: "half" },
  ],
};

export const editaisItensConfig: CrudPageConfig = {
  table: "editais-itens",
  title: "Itens de Editais",
  icon: <Layers size={24} />,
  parentFk: "edital_id",
  parentTable: "editais",
  parentLabelFn: (item) => `${item.numero || ""} - ${item.orgao || ""}`,
  fields: [
    { name: "edital_id", label: "Edital ID", type: "text", required: true, width: "half" },
    { name: "numero_item", label: "Nº Item", type: "number", width: "half" },
    { name: "descricao", label: "Descrição", type: "textarea", width: "full" },
    { name: "unidade_medida", label: "Unidade", type: "text", width: "half" },
    { name: "quantidade", label: "Quantidade", type: "decimal", width: "half" },
    { name: "valor_unitario_estimado", label: "Valor Unit. Estimado", type: "decimal", width: "half" },
    { name: "valor_total_estimado", label: "Valor Total Estimado", type: "decimal", width: "half" },
    { name: "codigo_item", label: "Código Item", type: "text", width: "half" },
  ],
};

// === 5. ANÁLISES ===

export const analisesConfig: CrudPageConfig = {
  table: "analises",
  title: "Análises",
  icon: <BarChart2 size={24} />,
  fields: [
    { name: "edital_id", label: "Edital ID", type: "text", required: true, width: "half" },
    { name: "produto_id", label: "Produto ID", type: "text", required: true, width: "half" },
    { name: "score_tecnico", label: "Score Técnico", type: "decimal", width: "half" },
    { name: "score_comercial", label: "Score Comercial", type: "decimal", width: "half" },
    { name: "score_potencial", label: "Score Potencial", type: "decimal", width: "half" },
    { name: "score_final", label: "Score Final", type: "decimal", width: "half" },
    { name: "requisitos_total", label: "Total Requisitos", type: "number", width: "half" },
    { name: "requisitos_atendidos", label: "Atendidos", type: "number", width: "half" },
    { name: "requisitos_parciais", label: "Parciais", type: "number", width: "half" },
    { name: "requisitos_nao_atendidos", label: "Não Atendidos", type: "number", width: "half" },
    { name: "preco_sugerido", label: "Preço Sugerido", type: "decimal", width: "half" },
    { name: "recomendacao", label: "Recomendação", type: "textarea", width: "full" },
  ],
};

// === 6. PROPOSTAS ===

export const propostasConfig: CrudPageConfig = {
  table: "propostas",
  title: "Propostas",
  icon: <Send size={24} />,
  fields: [
    { name: "edital_id", label: "Edital ID", type: "text", required: true, width: "half" },
    { name: "produto_id", label: "Produto ID", type: "text", required: true, width: "half" },
    { name: "analise_id", label: "Análise ID", type: "text", width: "half" },
    { name: "status", label: "Status", type: "select", options: enumOpts(["rascunho", "revisao", "aprovada", "enviada"]), width: "half" },
    { name: "preco_unitario", label: "Preço Unitário", type: "decimal", width: "half" },
    { name: "preco_total", label: "Preço Total", type: "decimal", width: "half" },
    { name: "quantidade", label: "Quantidade", type: "number", width: "half" },
    { name: "texto_tecnico", label: "Texto Técnico", type: "textarea", width: "full" },
    { name: "arquivo_path", label: "Arquivo", type: "text", width: "full" },
  ],
};

export const propostaTemplatesConfig: CrudPageConfig = {
  table: "proposta-templates",
  title: "Templates de Proposta",
  icon: <FileText size={24} />,
  fields: [
    { name: "nome", label: "Nome", type: "text", required: true, width: "half" },
    { name: "conteudo_md", label: "Conteudo (Markdown)", type: "textarea", width: "full" },
    { name: "ativo", label: "Ativo", type: "boolean", width: "half" },
  ],
};

// === 7. CONCORRÊNCIA ===

export const orgaosPerfilConfig: CrudPageConfig = {
  table: "orgaos-perfil",
  title: "Perfil de Órgãos",
  icon: <Building size={24} />,
  fields: [
    { name: "nome", label: "Nome do Órgão", type: "text", required: true, width: "full" },
    { name: "cnpj", label: "CNPJ", type: "text", required: true, width: "half" },
    { name: "uf", label: "UF", type: "text", width: "quarter" },
    { name: "total_compras", label: "Total Compras", type: "number", width: "quarter" },
    { name: "valor_total_compras", label: "Valor Total", type: "decimal", width: "half" },
    { name: "valor_medio_compras", label: "Valor Médio", type: "decimal", width: "half" },
    { name: "historico_pagamento", label: "Histórico Pagamento", type: "text", width: "half" },
    { name: "analise_ia", label: "Análise IA", type: "textarea", width: "full" },
  ],
};

export const atasConsultadasConfig: CrudPageConfig = {
  table: "atas-consultadas",
  title: "Atas Consultadas",
  icon: <FileText size={24} />,
  fields: [
    { name: "titulo", label: "Título", type: "text", width: "full" },
    { name: "orgao", label: "Órgão", type: "text", width: "half" },
    { name: "cnpj_orgao", label: "CNPJ Órgão", type: "text", width: "half" },
    { name: "uf", label: "UF", type: "text", width: "quarter" },
    { name: "ano", label: "Ano", type: "number", width: "quarter" },
    { name: "seq_compra", label: "Seq. Compra", type: "number", width: "quarter" },
    { name: "numero_controle_pncp", label: "Nº Controle PNCP", type: "text", width: "half" },
    { name: "url_pncp", label: "URL Ata (PNCP)", type: "text", width: "half" },
    { name: "url_edital_origem", label: "URL Edital Origem", type: "text", width: "half" },
    { name: "data_publicacao", label: "Data Publicação", type: "date", width: "half" },
  ],
};

export const concorrentesConfig: CrudPageConfig = {
  table: "concorrentes",
  title: "Concorrentes",
  icon: <Users size={24} />,
  fields: [
    { name: "nome", label: "Nome", type: "text", required: true, width: "half" },
    { name: "cnpj", label: "CNPJ", type: "text", width: "half" },
    { name: "razao_social", label: "Razão Social", type: "text", width: "half" },
    { name: "editais_participados", label: "Editais Participados", type: "number", width: "half" },
    { name: "editais_ganhos", label: "Editais Ganhos", type: "number", width: "half" },
    { name: "preco_medio", label: "Preço Médio", type: "decimal", width: "half" },
    { name: "taxa_vitoria", label: "Taxa Vitória (%)", type: "decimal", width: "half" },
    { name: "segmentos", label: "Segmentos", type: "json", width: "full" },
    { name: "observacoes", label: "Observações", type: "textarea", width: "full" },
  ],
};

export const precosHistoricosConfig: CrudPageConfig = {
  table: "precos-historicos",
  title: "Preços Históricos",
  icon: <DollarSign size={24} />,
  fields: [
    { name: "edital_id", label: "Edital ID", type: "text", width: "half" },
    { name: "produto_id", label: "Produto ID", type: "text", width: "half" },
    { name: "concorrente_id", label: "Concorrente ID", type: "text", width: "half" },
    { name: "preco_referencia", label: "Preço Referência", type: "decimal", width: "half" },
    { name: "preco_vencedor", label: "Preço Vencedor", type: "decimal", width: "half" },
    { name: "nosso_preco", label: "Nosso Preço", type: "decimal", width: "half" },
    { name: "desconto_percentual", label: "Desconto (%)", type: "decimal", width: "half" },
    { name: "empresa_vencedora", label: "Empresa Vencedora", type: "text", width: "half" },
    { name: "resultado", label: "Resultado", type: "select", options: enumOpts(["vitoria", "derrota", "cancelado", "deserto", "revogado"]), width: "half" },
    { name: "motivo_perda", label: "Motivo Perda", type: "select", options: enumOpts(["preco", "tecnica", "documentacao", "prazo", "outro"]), width: "half" },
    { name: "data_homologacao", label: "Data Homologação", type: "date", width: "half" },
    { name: "fonte", label: "Fonte", type: "select", options: enumOpts(["manual", "pncp", "ata_pdf", "painel_precos"]), width: "half" },
  ],
};

export const participacoesEditaisConfig: CrudPageConfig = {
  table: "participacoes-editais",
  title: "Participações em Editais",
  icon: <Scale size={24} />,
  parentFk: "edital_id",
  parentTable: "editais",
  parentLabelFn: (item) => `${item.numero || ""} - ${item.orgao || ""}`,
  fields: [
    { name: "edital_id", label: "Edital ID", type: "text", required: true, width: "half" },
    { name: "concorrente_id", label: "Concorrente ID", type: "text", width: "half" },
    { name: "preco_proposto", label: "Preço Proposto", type: "decimal", width: "half" },
    { name: "posicao_final", label: "Posição Final", type: "number", width: "half" },
    { name: "desclassificado", label: "Desclassificado", type: "boolean", width: "half" },
    { name: "motivo_desclassificacao", label: "Motivo Desclassificação", type: "textarea", width: "full" },
    { name: "fonte", label: "Fonte", type: "select", options: enumOpts(["manual", "pncp", "ata_pdf"]), width: "half" },
  ],
};

// === 8. ALERTAS E MONITORAMENTO ===

export const alertasConfig: CrudPageConfig = {
  table: "alertas",
  title: "Alertas",
  icon: <Bell size={24} />,
  fields: [
    { name: "edital_id", label: "Edital ID", type: "text", required: true, width: "half" },
    { name: "tipo", label: "Tipo", type: "select", required: true, options: enumOpts(["abertura", "impugnacao", "recursos", "proposta", "personalizado"]), width: "half" },
    { name: "data_disparo", label: "Data Disparo", type: "datetime", required: true, width: "half" },
    { name: "tempo_antes_minutos", label: "Minutos Antes", type: "number", width: "half" },
    { name: "status", label: "Status", type: "select", options: enumOpts(["agendado", "disparado", "lido", "cancelado"]), width: "half" },
    { name: "titulo", label: "Título", type: "text", width: "half" },
    { name: "mensagem", label: "Mensagem", type: "textarea", width: "full" },
    { name: "canal_email", label: "Email", type: "boolean", width: "half" },
    { name: "canal_push", label: "Push", type: "boolean", width: "half" },
    { name: "canal_sms", label: "SMS", type: "boolean", width: "half" },
  ],
};

export const monitoramentosConfig: CrudPageConfig = {
  table: "monitoramentos",
  title: "Monitoramentos",
  icon: <Eye size={24} />,
  fields: [
    { name: "termo", label: "Termo de Busca", type: "text", required: true, width: "half" },
    { name: "fontes", label: "Fontes", type: "json", width: "half" },
    { name: "ufs", label: "UFs", type: "json", width: "half" },
    { name: "valor_minimo", label: "Valor Mínimo", type: "decimal", width: "half" },
    { name: "valor_maximo", label: "Valor Máximo", type: "decimal", width: "half" },
    { name: "frequencia_horas", label: "Frequência (horas)", type: "number", width: "half" },
    { name: "score_minimo_alerta", label: "Score Mínimo", type: "number", width: "half" },
    { name: "notificar_email", label: "Notificar Email", type: "boolean", width: "half" },
    { name: "notificar_push", label: "Notificar Push", type: "boolean", width: "half" },
    { name: "ativo", label: "Ativo", type: "boolean", width: "half" },
  ],
};

export const notificacoesConfig: CrudPageConfig = {
  table: "notificacoes",
  title: "Notificações",
  icon: <Mail size={24} />,
  fields: [
    { name: "tipo", label: "Tipo", type: "select", required: true, options: enumOpts(["alerta_prazo", "novo_edital", "alta_aderencia", "resultado", "sistema"]), width: "half" },
    { name: "edital_id", label: "Edital ID", type: "text", width: "half" },
    { name: "alerta_id", label: "Alerta ID", type: "text", width: "half" },
    { name: "titulo", label: "Título", type: "text", required: true, width: "half" },
    { name: "mensagem", label: "Mensagem", type: "textarea", required: true, width: "full" },
    { name: "dados", label: "Dados Extra", type: "json", width: "full" },
    { name: "lida", label: "Lida", type: "boolean", width: "half" },
    { name: "enviado_email", label: "Enviado Email", type: "boolean", width: "half" },
    { name: "enviado_push", label: "Enviado Push", type: "boolean", width: "half" },
  ],
};

export const preferenciasNotificacaoConfig: CrudPageConfig = {
  table: "preferencias-notificacao",
  title: "Preferências de Notificação",
  icon: <Bell size={24} />,
  fields: [
    { name: "email_habilitado", label: "Email Habilitado", type: "boolean", width: "half" },
    { name: "push_habilitado", label: "Push Habilitado", type: "boolean", width: "half" },
    { name: "sms_habilitado", label: "SMS Habilitado", type: "boolean", width: "half" },
    { name: "email_notificacao", label: "Email para Notificações", type: "email", width: "half" },
    { name: "horario_inicio", label: "Horário Início", type: "text", width: "half", placeholder: "07:00" },
    { name: "horario_fim", label: "Horário Fim", type: "text", width: "half", placeholder: "22:00" },
    { name: "dias_semana", label: "Dias da Semana", type: "json", width: "full" },
    { name: "alertas_padrao", label: "Alertas Padrão (minutos)", type: "json", width: "full" },
    { name: "score_minimo_notificacao", label: "Score Mínimo", type: "number", width: "half" },
  ],
};

// === 9. CONTRATOS ===

export const contratosConfig: CrudPageConfig = {
  table: "contratos",
  title: "Contratos",
  icon: <Briefcase size={24} />,
  fields: [
    { name: "edital_id", label: "Edital ID", type: "text", width: "half" },
    { name: "proposta_id", label: "Proposta ID", type: "text", width: "half" },
    { name: "numero_contrato", label: "Nº Contrato", type: "text", width: "half" },
    { name: "orgao", label: "Órgão", type: "text", width: "half" },
    { name: "objeto", label: "Objeto", type: "textarea", width: "full" },
    { name: "valor_total", label: "Valor Total", type: "decimal", width: "half" },
    { name: "data_assinatura", label: "Data Assinatura", type: "date", width: "half" },
    { name: "data_inicio", label: "Data Início", type: "date", width: "half" },
    { name: "data_fim", label: "Data Fim", type: "date", width: "half" },
    { name: "status", label: "Status", type: "select", options: enumOpts(["vigente", "encerrado", "rescindido", "suspenso"]), width: "half" },
    { name: "observacoes", label: "Observações", type: "textarea", width: "full" },
  ],
};

export const contratoEntregasConfig: CrudPageConfig = {
  table: "contrato-entregas",
  title: "Entregas de Contratos",
  icon: <Clock size={24} />,
  parentFk: "contrato_id",
  parentTable: "contratos",
  parentLabelFn: (item) => `${item.numero_contrato || ""} - ${item.orgao || ""}`,
  fields: [
    { name: "contrato_id", label: "Contrato ID", type: "text", required: true, width: "half" },
    { name: "produto_id", label: "Produto ID", type: "text", width: "half" },
    { name: "descricao", label: "Descrição", type: "textarea", width: "full" },
    { name: "quantidade", label: "Quantidade", type: "decimal", width: "half" },
    { name: "valor_unitario", label: "Valor Unitário", type: "decimal", width: "half" },
    { name: "valor_total", label: "Valor Total", type: "decimal", width: "half" },
    { name: "data_prevista", label: "Data Prevista", type: "date", required: true, width: "half" },
    { name: "data_realizada", label: "Data Realizada", type: "date", width: "half" },
    { name: "nota_fiscal", label: "Nota Fiscal", type: "text", width: "half" },
    { name: "numero_empenho", label: "Nº Empenho", type: "text", width: "half" },
    { name: "status", label: "Status", type: "select", options: enumOpts(["pendente", "entregue", "atrasado", "cancelado"]), width: "half" },
    { name: "observacoes", label: "Observações", type: "textarea", width: "full" },
  ],
};

// === 10. RECURSOS ===

export const recursosConfig: CrudPageConfig = {
  table: "recursos",
  title: "Recursos e Impugnações",
  icon: <Gavel size={24} />,
  fields: [
    { name: "edital_id", label: "Edital ID", type: "text", required: true, width: "half" },
    { name: "tipo", label: "Tipo", type: "select", required: true, options: enumOpts(["recurso", "contra_razao", "impugnacao"]), width: "half" },
    { name: "motivo", label: "Motivo", type: "textarea", width: "full" },
    { name: "texto_minuta", label: "Texto da Minuta", type: "textarea", width: "full" },
    { name: "fundamentacao_legal", label: "Fundamentação Legal", type: "textarea", width: "full" },
    { name: "prazo_limite", label: "Prazo Limite", type: "datetime", required: true, width: "half" },
    { name: "data_protocolo", label: "Data Protocolo", type: "datetime", width: "half" },
    { name: "status", label: "Status", type: "select", options: enumOpts(["rascunho", "protocolado", "deferido", "indeferido", "pendente"]), width: "half" },
    { name: "resultado", label: "Resultado", type: "textarea", width: "full" },
    { name: "arquivo_path", label: "Arquivo", type: "text", width: "full" },
  ],
};

// === 10b. TEMPLATES DE RECURSOS ===

export const recursoTemplatesConfig: CrudPageConfig = {
  table: "recurso-templates",
  title: "Templates de Recursos",
  icon: <FileText size={24} />,
  fields: [
    { name: "nome", label: "Nome", type: "text", required: true, width: "half" },
    { name: "tipo", label: "Tipo", type: "select", required: true, options: enumOpts(["impugnacao", "recurso", "contra_razao"]), width: "half" },
    { name: "conteudo_md", label: "Conteudo (Markdown)", type: "textarea", width: "full" },
    { name: "ativo", label: "Ativo", type: "boolean", width: "half" },
  ],
};

// === 11. CRM ===

export const leadsCrmConfig: CrudPageConfig = {
  table: "leads-crm",
  title: "Leads CRM",
  icon: <TrendingUp size={24} />,
  fields: [
    { name: "orgao", label: "Órgão", type: "text", required: true, width: "half" },
    { name: "cnpj_orgao", label: "CNPJ do Órgão", type: "text", width: "half" },
    { name: "edital_id", label: "Edital ID", type: "text", width: "half" },
    { name: "contato_nome", label: "Nome do Contato", type: "text", width: "half" },
    { name: "contato_cargo", label: "Cargo", type: "text", width: "half" },
    { name: "contato_telefone", label: "Telefone", type: "text", width: "half" },
    { name: "contato_email", label: "Email", type: "email", width: "half" },
    { name: "status_pipeline", label: "Status Pipeline", type: "select", options: enumOpts(["prospeccao", "contato", "proposta", "negociacao", "ganho", "perdido", "inativo"]), width: "half" },
    { name: "origem", label: "Origem", type: "text", width: "half" },
    { name: "valor_potencial", label: "Valor Potencial", type: "decimal", width: "half" },
    { name: "proxima_acao", label: "Próxima Ação", type: "textarea", width: "full" },
    { name: "data_proxima_acao", label: "Data Próxima Ação", type: "date", width: "half" },
    { name: "observacoes", label: "Observações", type: "textarea", width: "full" },
  ],
};

export const acoesPosePerdaConfig: CrudPageConfig = {
  table: "acoes-pos-perda",
  title: "Ações Pós-Perda",
  icon: <AlertTriangle size={24} />,
  fields: [
    { name: "edital_id", label: "Edital ID", type: "text", width: "half" },
    { name: "lead_crm_id", label: "Lead CRM ID", type: "text", width: "half" },
    { name: "tipo_acao", label: "Tipo de Ação", type: "select", options: enumOpts(["reprocessar_oferta", "visita_tecnica", "nova_proposta", "recurso", "acompanhar"]), width: "half" },
    { name: "responsavel", label: "Responsável", type: "text", width: "half" },
    { name: "descricao", label: "Descrição", type: "textarea", width: "full" },
    { name: "data_prevista", label: "Data Prevista", type: "date", width: "half" },
    { name: "data_realizada", label: "Data Realizada", type: "date", width: "half" },
    { name: "status", label: "Status", type: "select", options: enumOpts(["pendente", "em_andamento", "concluida", "cancelada"]), width: "half" },
    { name: "resultado", label: "Resultado", type: "textarea", width: "full" },
  ],
};

// === 12. AUDITORIA ===

export const auditoriaLogConfig: CrudPageConfig = {
  table: "auditoria-log",
  title: "Log de Auditoria",
  icon: <Database size={24} />,
  fields: [
    { name: "acao", label: "Ação", type: "text", width: "half" },
    { name: "entidade", label: "Entidade", type: "text", width: "half" },
    { name: "entidade_id", label: "Entidade ID", type: "text", width: "half" },
    { name: "user_email", label: "Email Usuário", type: "text", width: "half" },
    { name: "ip_address", label: "IP", type: "text", width: "half" },
    { name: "user_agent", label: "User Agent", type: "text", width: "full" },
    { name: "dados_antes", label: "Dados Antes", type: "json", width: "full" },
    { name: "dados_depois", label: "Dados Depois", type: "json", width: "full" },
  ],
};

export const aprendizadoFeedbackConfig: CrudPageConfig = {
  table: "aprendizado-feedback",
  title: "Feedback de Aprendizado",
  icon: <BookOpen size={24} />,
  fields: [
    { name: "tipo_evento", label: "Tipo de Evento", type: "select", required: true, options: enumOpts(["resultado_edital", "score_ajustado", "preco_ajustado", "feedback_usuario"]), width: "half" },
    { name: "entidade", label: "Entidade", type: "text", width: "half" },
    { name: "entidade_id", label: "Entidade ID", type: "text", width: "half" },
    { name: "dados_entrada", label: "Dados Entrada", type: "json", width: "full" },
    { name: "resultado_real", label: "Resultado Real", type: "json", width: "full" },
    { name: "delta", label: "Delta", type: "json", width: "full" },
    { name: "aplicado", label: "Aplicado", type: "boolean", width: "half" },
  ],
};

// === 13. PARÂMETROS E ESTRATÉGIA ===

export const parametrosScoreConfig: CrudPageConfig = {
  table: "parametros-score",
  title: "Parâmetros de Score",
  icon: <Target size={24} />,
  fields: [
    { name: "peso_tecnico", label: "Peso Técnico", type: "decimal", width: "half", placeholder: "Aderência técnica do produto" },
    { name: "peso_comercial", label: "Peso Comercial", type: "decimal", width: "half", placeholder: "Viabilidade comercial e preço" },
    { name: "peso_documental", label: "Peso Documental", type: "decimal", width: "half", placeholder: "Regularidade documental e certidões" },
    { name: "peso_complexidade", label: "Peso Complexidade", type: "decimal", width: "half", placeholder: "Complexidade técnica do edital" },
    { name: "peso_juridico", label: "Peso Jurídico", type: "decimal", width: "half", placeholder: "Risco jurídico e cláusulas restritivas" },
    { name: "peso_logistico", label: "Peso Logístico", type: "decimal", width: "half", placeholder: "Viabilidade logística e prazo de entrega" },
    { name: "limiar_go", label: "Limiar GO", type: "decimal", width: "half" },
    { name: "limiar_nogo", label: "Limiar NO-GO", type: "decimal", width: "half" },
    { name: "limiar_tecnico_go", label: "Limiar Técnico GO", type: "decimal", width: "half" },
    { name: "limiar_tecnico_nogo", label: "Limiar Técnico NO-GO", type: "decimal", width: "half" },
    { name: "limiar_juridico_go", label: "Limiar Jurídico GO", type: "decimal", width: "half" },
    { name: "limiar_juridico_nogo", label: "Limiar Jurídico NO-GO", type: "decimal", width: "half" },
    { name: "margem_minima", label: "Margem Mínima", type: "decimal", width: "half" },
    { name: "markup_padrao", label: "Markup Padrao (%)", type: "number", placeholder: "Ex: 30" },
    { name: "custos_fixos", label: "Custos Fixos Mensais (R$)", type: "number", placeholder: "Ex: 15000" },
    { name: "frete_base", label: "Frete Base (R$)", type: "number", placeholder: "Ex: 500" },
  ],
};

export const dispensasConfig: CrudPageConfig = {
  table: "dispensas",
  title: "Dispensas",
  icon: <Zap size={24} />,
  fields: [
    { name: "edital_id", label: "Edital ID", type: "text", required: true, width: "half" },
    { name: "artigo", label: "Artigo", type: "text", width: "half" },
    { name: "valor_limite", label: "Valor Limite", type: "decimal", width: "half" },
    { name: "status", label: "Status", type: "select", options: enumOpts(["aberta", "cotacao_enviada", "adjudicada", "encerrada"]), width: "half" },
    { name: "justificativa", label: "Justificativa", type: "textarea", width: "full" },
    { name: "fornecedores_cotados", label: "Fornecedores Cotados", type: "json", width: "full" },
    { name: "data_limite", label: "Data Limite", type: "datetime", width: "half" },
  ],
};

export const estrategiasEditaisConfig: CrudPageConfig = {
  table: "estrategias-editais",
  title: "Estratégias de Editais",
  icon: <Target size={24} />,
  fields: [
    { name: "edital_id", label: "Edital ID", type: "text", required: true, width: "half" },
    { name: "decisao", label: "Decisão", type: "select", options: enumOpts(["go", "nogo", "acompanhar"]), width: "half" },
    { name: "prioridade", label: "Prioridade", type: "select", options: enumOpts(["alta", "media", "baixa"]), width: "half" },
    { name: "margem_desejada", label: "Margem Desejada (%)", type: "decimal", width: "half" },
    { name: "agressividade_preco", label: "Agressividade Preço", type: "select", options: enumOpts(["conservador", "moderado", "agressivo"]), width: "half" },
    { name: "data_decisao", label: "Data Decisão", type: "datetime", width: "half" },
    { name: "decidido_por", label: "Decidido Por", type: "text", width: "half" },
    { name: "justificativa", label: "Justificativa", type: "textarea", width: "full" },
  ],
};

// === CATEGORIAS DE DOCUMENTO ===

export const categoriasDocumentoConfig: CrudPageConfig = {
  table: "categorias-documento",
  title: "Categorias de Documento",
  icon: <FolderTree size={24} />,
  fields: [
    { name: "nome", label: "Nome", type: "text", required: true, width: "half" },
    { name: "descricao", label: "Descrição", type: "textarea", width: "full" },
    { name: "ordem", label: "Ordem", type: "number", width: "half" },
    { name: "ativo", label: "Ativo", type: "boolean", width: "half" },
  ],
};

// === DOCUMENTOS NECESSÁRIOS ===

export const documentosNecessariosConfig: CrudPageConfig = {
  table: "documentos-necessarios",
  title: "Documentos Necessários",
  icon: <FileText size={24} />,
  fields: [
    { name: "nome", label: "Nome", type: "text", required: true, width: "half" },
    { name: "tipo_chave", label: "Tipo Chave (slug)", type: "text", required: true, width: "half" },
    { name: "categoria_id", label: "Categoria", type: "fk", fkTable: "categorias-documento", fkLabel: "nome", width: "half" },
    { name: "base_legal", label: "Base Legal", type: "text", width: "half" },
    { name: "descricao", label: "Descrição", type: "textarea", width: "full" },
    { name: "validade_dias", label: "Validade (dias)", type: "number", width: "half" },
    { name: "obrigatorio", label: "Obrigatório", type: "boolean", width: "half" },
    { name: "ordem", label: "Ordem", type: "number", width: "half" },
    { name: "ativo", label: "Ativo", type: "boolean", width: "half" },
  ],
};

// ─── All configs map (table slug → config) ────────────────────────────────────

export const ALL_CRUD_CONFIGS: Record<string, CrudPageConfig> = {
  "users": usersConfig,
  "empresas": empresaConfig,
  "empresa-documentos": empresaDocumentosConfig,
  "empresa-certidoes": empresaCertidoesConfig,
  "empresa-responsaveis": empresaResponsaveisConfig,
  "beneficios-fiscais-ncm": beneficiosFiscaisNcmConfig,
  "produtos": produtosConfig,
  "produtos-especificacoes": produtosEspecificacoesConfig,
  "produtos-documentos": produtosDocumentosConfig,
  "areas-produto": areasProdutoConfig,
  "classes-produto-v2": classesProdutoV2Config,
  "subclasses-produto": subclassesProdutoConfig,
  "fontes-editais": fontesEditaisConfig,
  "fontes-certidoes": fontesCertidoesConfig,
  "modalidades-licitacao": modalidadesLicitacaoConfig,
  "origens-orgao": origensOrgaoConfig,
  "editais": editaisConfig,
  "editais-requisitos": editaisRequisitosConfig,
  "editais-documentos": editaisDocumentosConfig,
  "editais-itens": editaisItensConfig,
  "analises": analisesConfig,
  "propostas": propostasConfig,
  "proposta-templates": propostaTemplatesConfig,
  "orgaos-perfil": orgaosPerfilConfig,
  "atas-consultadas": atasConsultadasConfig,
  "concorrentes": concorrentesConfig,
  "precos-historicos": precosHistoricosConfig,
  "participacoes-editais": participacoesEditaisConfig,
  "alertas": alertasConfig,
  "monitoramentos": monitoramentosConfig,
  "notificacoes": notificacoesConfig,
  "preferencias-notificacao": preferenciasNotificacaoConfig,
  "contratos": contratosConfig,
  "contrato-entregas": contratoEntregasConfig,
  "recursos": recursosConfig,
  "recurso-templates": recursoTemplatesConfig,
  "leads-crm": leadsCrmConfig,
  "acoes-pos-perda": acoesPosePerdaConfig,
  "auditoria-log": auditoriaLogConfig,
  "aprendizado-feedback": aprendizadoFeedbackConfig,
  "parametros-score": parametrosScoreConfig,
  "dispensas": dispensasConfig,
  "estrategias-editais": estrategiasEditaisConfig,
  "categorias-documento": categoriasDocumentoConfig,
  "documentos-necessarios": documentosNecessariosConfig,
};
