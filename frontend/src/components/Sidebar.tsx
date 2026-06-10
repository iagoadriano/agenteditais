import { APP_NAME } from "../config/branding";
import { useState, useEffect } from "react";
import {
  LogOut, User as UserIcon, ChevronDown, ChevronRight,
  LayoutDashboard, Search, CheckCircle, DollarSign, FileText, Send,
  Gavel, Clock, AlertCircle, Package, BarChart2, Flag, Eye, Users,
  TrendingUp, Scale, AlertTriangle, XCircle, Settings, Building,
  Briefcase, Sliders, GitBranch, Database, Shield, Layers, FileCheck,
  Bell, Mail, Target, BookOpen, Zap, Globe, UserPlus, FolderTree, Tag, Tags,
  Brain
} from "lucide-react";

interface User {
  id: string;
  email: string;
  name: string;
  picture_url: string | null;
  super?: boolean;
}

interface MenuItem {
  id: string;
  icon: React.ReactNode;
  label: string;
  page: string;
  superOnly?: boolean;
}

interface MenuSection {
  id: string;
  icon: React.ReactNode;
  label: string;
  items: (MenuItem | MenuSubSection)[];
}

interface MenuSubSection {
  id: string;
  icon: React.ReactNode;
  label: string;
  items: MenuItem[];
  superOnly?: boolean;
}

function isSubSection(item: MenuItem | MenuSubSection): item is MenuSubSection {
  return "items" in item;
}

const SIDEBAR_SECTIONS: MenuSection[] = [
  {
    id: "fluxo",
    icon: <GitBranch size={18} />,
    label: "Fluxo Comercial",
    items: [
      { id: "captacao", icon: <Search size={16} />, label: "Captacao", page: "captacao" },
      { id: "validacao", icon: <CheckCircle size={16} />, label: "Validacao", page: "validacao" },
      { id: "impugnacao", icon: <AlertCircle size={16} />, label: "Impugnacao", page: "impugnacao" },
      { id: "precificacao", icon: <DollarSign size={16} />, label: "Precificacao", page: "precificacao" },
      { id: "proposta", icon: <FileText size={16} />, label: "Proposta", page: "proposta" },
      { id: "submissao", icon: <Send size={16} />, label: "Submissao", page: "submissao" },
      { id: "lances", icon: <Gavel size={16} />, label: "Disputa Lances", page: "lances" },
      { id: "simulador", icon: <Gavel size={16} />, label: "Simulador Pregão", page: "simulador" },
      { id: "recursos", icon: <Shield size={16} />, label: "Recursos", page: "recursos" },
      { id: "followup", icon: <Clock size={16} />, label: "Followup", page: "followup" },
      { id: "crm", icon: <Users size={16} />, label: "CRM", page: "crm" },
      { id: "producao", icon: <Package size={16} />, label: "Execucao Contrato", page: "producao" },
      { id: "atas", icon: <FileText size={16} />, label: "Atas de Pregao", page: "atas" },
    ]
  },
  {
    id: "cadastros",
    icon: <Database size={18} />,
    label: "Cadastros",
    items: [
      { id: "crud-users", icon: <UserPlus size={16} />, label: "Usuarios", page: "crud:users", superOnly: true },
      { id: "associar-empresa", icon: <UserPlus size={16} />, label: "Associar Empresa/Usuario", page: "associar-empresa", superOnly: true },
      {
        id: "cad-empresa",
        icon: <Building size={16} />,
        label: "Empresa",
        superOnly: true,
        items: [
          { id: "crud-empresa-documentos", icon: <FileText size={14} />, label: "Documentos", page: "crud:empresa-documentos" },
          { id: "crud-empresa-certidoes", icon: <Shield size={14} />, label: "Certidoes", page: "crud:empresa-certidoes" },
          { id: "crud-fontes-certidoes", icon: <Globe size={14} />, label: "Fontes de Certidoes", page: "crud:fontes-certidoes" },
          { id: "crud-empresa-responsaveis", icon: <Users size={14} />, label: "Responsaveis e Representantes", page: "crud:empresa-responsaveis" },
          { id: "crud-cat-doc", icon: <FolderTree size={14} />, label: "Categorias Documento", page: "crud:categorias-documento" },
          { id: "crud-docs-nec", icon: <FileText size={14} />, label: "Tipos de Documento", page: "crud:documentos-necessarios" },
          { id: "crud-beneficios-fiscais-ncm", icon: <DollarSign size={14} />, label: "Beneficios Fiscais NCM", page: "crud:beneficios-fiscais-ncm" },
        ],
      },
      {
        id: "cad-portfolio",
        icon: <Package size={16} />,
        label: "Portfolio",
        items: [
          { id: "crud-produtos", icon: <Package size={14} />, label: "Produtos", page: "crud:produtos" },
          { id: "crud-produtos-specs", icon: <Sliders size={14} />, label: "Especificacoes", page: "crud:produtos-especificacoes" },
          { id: "crud-produtos-docs", icon: <FileText size={14} />, label: "Documentos", page: "crud:produtos-documentos" },
          { id: "crud-areas-produto", icon: <FolderTree size={14} />, label: "Areas", page: "crud:areas-produto" },
          { id: "crud-classes-produto", icon: <Tag size={14} />, label: "Classes", page: "crud:classes-produto-v2" },
          { id: "crud-subclasses-produto", icon: <Tags size={14} />, label: "Subclasses", page: "crud:subclasses-produto" },
        ],
      },
      {
        id: "cad-editais",
        icon: <FileCheck size={16} />,
        label: "Editais",
        items: [
          { id: "crud-editais", icon: <FileCheck size={14} />, label: "Editais", page: "crud:editais" },
          { id: "crud-editais-req", icon: <Layers size={14} />, label: "Requisitos", page: "crud:editais-requisitos" },
          { id: "crud-editais-docs", icon: <FileText size={14} />, label: "Documentos", page: "crud:editais-documentos" },
          { id: "crud-editais-itens", icon: <Layers size={14} />, label: "Itens", page: "crud:editais-itens" },
          { id: "crud-orgaos-perfil", icon: <Building size={14} />, label: "Perfil de Órgãos", page: "crud:orgaos-perfil" },
          { id: "crud-atas", icon: <FileText size={14} />, label: "Atas Consultadas", page: "crud:atas-consultadas" },
          { id: "crud-precos", icon: <DollarSign size={14} />, label: "Histórico de Preços", page: "crud:precos-historicos" },
          { id: "crud-concorrentes", icon: <Users size={14} />, label: "Concorrentes", page: "crud:concorrentes" },
        ],
      },
      {
        id: "cad-analises",
        icon: <BarChart2 size={16} />,
        label: "Analises e Propostas",
        items: [
          { id: "crud-analises", icon: <BarChart2 size={14} />, label: "Analises", page: "crud:analises" },
          { id: "crud-propostas", icon: <Send size={14} />, label: "Propostas", page: "crud:propostas" },
          { id: "crud-proposta-templates", icon: <FileText size={14} />, label: "Templates Proposta", page: "crud:proposta-templates" },
        ],
      },
      {
        id: "cad-concorrencia",
        icon: <Users size={16} />,
        label: "Concorrencia",
        items: [
          { id: "crud-concorrentes", icon: <Users size={14} />, label: "Concorrentes", page: "crud:concorrentes" },
          { id: "crud-precos", icon: <DollarSign size={14} />, label: "Precos Historicos", page: "crud:precos-historicos" },
          { id: "crud-participacoes", icon: <Scale size={14} />, label: "Participacoes", page: "crud:participacoes-editais" },
        ],
      },
      {
        id: "cad-alertas",
        icon: <Bell size={16} />,
        label: "Alertas e Monitor.",
        items: [
          { id: "crud-alertas", icon: <Bell size={14} />, label: "Alertas", page: "crud:alertas" },
          { id: "crud-monitoramentos", icon: <Eye size={14} />, label: "Monitoramentos", page: "crud:monitoramentos" },
          { id: "crud-notificacoes", icon: <Mail size={14} />, label: "Notificacoes", page: "crud:notificacoes" },
          { id: "crud-pref-notif", icon: <Bell size={14} />, label: "Preferencias", page: "crud:preferencias-notificacao" },
        ],
      },
      {
        id: "cad-contratos",
        icon: <Briefcase size={16} />,
        label: "Contratos",
        items: [
          { id: "crud-contratos", icon: <Briefcase size={14} />, label: "Contratos", page: "crud:contratos" },
          { id: "crud-entregas", icon: <Clock size={14} />, label: "Entregas", page: "crud:contrato-entregas" },
          { id: "crud-empenhos", icon: <DollarSign size={14} />, label: "Empenhos", page: "crud:empenhos" },
          { id: "crud-empenho-itens", icon: <Layers size={14} />, label: "Itens Empenho", page: "crud:empenho-itens" },
          { id: "crud-empenho-faturas", icon: <FileText size={14} />, label: "Faturas Empenho", page: "crud:empenho-faturas" },
        ],
      },
      {
        id: "cad-recursos",
        icon: <Gavel size={16} />,
        label: "Recursos",
        items: [
          { id: "crud-recursos", icon: <Gavel size={14} />, label: "Recursos/Impugnacoes", page: "crud:recursos" },
          { id: "crud-recurso-templates", icon: <FileText size={14} />, label: "Templates Recursos", page: "crud:recurso-templates" },
        ],
      },
      {
        id: "cad-crm",
        icon: <TrendingUp size={16} />,
        label: "CRM",
        items: [
          { id: "crud-leads", icon: <TrendingUp size={14} />, label: "Leads", page: "crud:leads-crm" },
          { id: "crud-acoes-perda", icon: <AlertTriangle size={14} />, label: "Acoes Pos-Perda", page: "crud:acoes-pos-perda" },
          { id: "crud-crm-param", icon: <Sliders size={14} />, label: "Parametrizacoes CRM", page: "crud:crm-parametrizacoes" },
          { id: "crud-edital-decisoes", icon: <Gavel size={14} />, label: "Decisoes Editais", page: "crud:edital-decisoes" },
          { id: "crud-crm-agenda", icon: <Clock size={14} />, label: "Agenda CRM", page: "crud:crm-agenda-items" },
        ],
      },
      {
        id: "cad-auditoria",
        icon: <BookOpen size={16} />,
        label: "Auditoria",
        items: [
          { id: "crud-auditoria", icon: <Database size={14} />, label: "Log Auditoria", page: "crud:auditoria-log" },
          { id: "crud-feedback", icon: <BookOpen size={14} />, label: "Feedback Aprendizado", page: "crud:aprendizado-feedback" },
        ],
      },
      {
        id: "cad-parametros",
        icon: <Target size={16} />,
        label: "Parametros",
        items: [
          { id: "crud-param-score", icon: <Target size={14} />, label: "Parametros Score", page: "crud:parametros-score" },
          { id: "crud-dispensas", icon: <Zap size={14} />, label: "Dispensas", page: "crud:dispensas" },
          { id: "crud-estrategias", icon: <Target size={14} />, label: "Estrategias", page: "crud:estrategias-editais" },
          { id: "crud-fontes", icon: <Search size={14} />, label: "Fontes Editais", page: "crud:fontes-editais" },
          { id: "crud-modalidades", icon: <Gavel size={14} />, label: "Modalidades Licitacao", page: "crud:modalidades-licitacao" },
          { id: "crud-origens", icon: <GitBranch size={14} />, label: "Origens Orgao", page: "crud:origens-orgao" },
        ],
      },
    ]
  },
  {
    id: "indicadores",
    icon: <BarChart2 size={18} />,
    label: "Indicadores",
    items: [
      { id: "flags", icon: <Flag size={16} />, label: "Flags", page: "flags" },
      { id: "monitoria", icon: <Eye size={16} />, label: "Monitoria", page: "monitoria" },
      { id: "concorrencia", icon: <Users size={16} />, label: "Concorrencia", page: "concorrencia" },
      { id: "mercado", icon: <TrendingUp size={16} />, label: "Mercado", page: "mercado" },
      { id: "contratado", icon: <Scale size={16} />, label: "Contratado X Realizado", page: "contratado" },
      { id: "atrasos", icon: <AlertTriangle size={16} />, label: "Pedidos em Atraso", page: "atrasos" },
      { id: "perdas", icon: <XCircle size={16} />, label: "Perdas", page: "perdas" },
      { id: "analytics", icon: <BarChart2 size={16} />, label: "Analytics", page: "analytics" },
      { id: "aprendizado", icon: <Brain size={16} />, label: "Aprendizado", page: "aprendizado" },
    ]
  },
  {
    id: "governanca",
    icon: <Shield size={18} />,
    label: "Governanca",
    items: [
      { id: "auditoria", icon: <Shield size={16} />, label: "Auditoria", page: "auditoria" },
      { id: "smtp", icon: <Mail size={16} />, label: "SMTP", page: "smtp", superOnly: true },
    ]
  },
  {
    id: "config",
    icon: <Settings size={18} />,
    label: "Configuracoes",
    items: [
      // F01-05: labels CURTOS pra preservar compatibilidade com tutoriais existentes
      // que usam selector text-is("Empresa") / text-is("Portfolio") etc.
      // A clarificação fica em tooltip (atributo title).
      { id: "empresa", icon: <Building size={16} />, label: "Empresa", page: "empresa" },
      { id: "portfolio", icon: <Briefcase size={16} />, label: "Portfolio", page: "portfolio" },
      { id: "parametros", icon: <Sliders size={16} />, label: "Parametrizacoes", page: "parametros" },
      { id: "selecionar-empresa", icon: <Building size={16} />, label: "Selecionar Empresa", page: "selecionar-empresa" },
    ]
  }
];

interface SidebarProps {
  currentPage: string;
  onNavigate: (page: string) => void;
  user?: User | null;
  onLogout?: () => void;
  isSuper?: boolean;
  isAdmin?: boolean;
}

export function Sidebar({
  currentPage,
  onNavigate,
  user,
  onLogout,
  isSuper = false,
  isAdmin = false,
}: SidebarProps) {
  // F01-08: lembrar preferencia do user em localStorage
  const SIDEBAR_SECTIONS_KEY = "facilicita_sidebar_sections_v1";
  const SIDEBAR_SUBS_KEY = "facilicita_sidebar_subs_v1";

  const [expandedSections, setExpandedSections] = useState<Set<string>>(() => {
    try {
      const saved = localStorage.getItem(SIDEBAR_SECTIONS_KEY);
      if (saved) return new Set(JSON.parse(saved) as string[]);
    } catch { /* ignore */ }
    return new Set(["fluxo"]);  // default: Fluxo Comercial expandido
  });
  const [expandedSubSections, setExpandedSubSections] = useState<Set<string>>(() => {
    try {
      const saved = localStorage.getItem(SIDEBAR_SUBS_KEY);
      if (saved) return new Set(JSON.parse(saved) as string[]);
    } catch { /* ignore */ }
    return new Set();
  });

  // F01-08: persiste mudancas
  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_SECTIONS_KEY, JSON.stringify(Array.from(expandedSections)));
    } catch { /* ignore */ }
  }, [expandedSections]);
  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_SUBS_KEY, JSON.stringify(Array.from(expandedSubSections)));
    } catch { /* ignore */ }
  }, [expandedSubSections]);

  const toggleSection = (sectionId: string) => {
    setExpandedSections(prev => {
      const newSet = new Set(prev);
      if (newSet.has(sectionId)) {
        newSet.delete(sectionId);
      } else {
        newSet.add(sectionId);
      }
      return newSet;
    });
  };

  const toggleSubSection = (subId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setExpandedSubSections(prev => {
      const newSet = new Set(prev);
      if (newSet.has(subId)) {
        newSet.delete(subId);
      } else {
        newSet.add(subId);
      }
      return newSet;
    });
  };

  // F01-08: botao "Recolher tudo"
  const recolherTudo = () => {
    setExpandedSections(new Set());
    setExpandedSubSections(new Set());
  };

  const handleItemClick = (page: string) => {
    onNavigate(page);
  };

  return (
    <div className="sidebar">
      {/* Header com logo */}
      <div className="sidebar-header">
        <div className="sidebar-logo" onClick={() => onNavigate('dashboard')}>
          <span className="logo-icon">{APP_NAME.charAt(0)}</span>
          <h1>{APP_NAME.toLowerCase()}</h1>
        </div>
      </div>

      {/* Navegacao */}
      <nav className="sidebar-nav">
        {/* Dashboard - item fixo fora dos menus */}
        <button
          className={`nav-item nav-item-main ${currentPage === 'dashboard' ? 'active' : ''}`}
          onClick={() => handleItemClick('dashboard')}
        >
          <span className="nav-item-icon"><LayoutDashboard size={18} /></span>
          <span className="nav-item-label">Dashboard</span>
        </button>

        {/* F01-08: botao recolher tudo (so aparece quando alguma secao esta expandida) */}
        {(expandedSections.size > 0 || expandedSubSections.size > 0) && (
          <button
            className="nav-item nav-item-secondary"
            onClick={recolherTudo}
            title="Recolher todas as secoes e subsecoes"
            style={{ fontSize: "11px", opacity: 0.7, padding: "4px 12px" }}
          >
            <span className="nav-item-icon"><ChevronRight size={14} /></span>
            <span className="nav-item-label">Recolher tudo</span>
          </button>
        )}

        {SIDEBAR_SECTIONS.map((section) => (
          <div key={section.id} className="nav-section">
            <button
              className={`nav-section-header ${expandedSections.has(section.id) ? 'expanded' : ''}`}
              onClick={() => toggleSection(section.id)}
            >
              <span className="nav-section-icon">{section.icon}</span>
              <span className="nav-section-label">{section.label}</span>
              <span className="nav-section-chevron">
                {expandedSections.has(section.id) ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              </span>
            </button>

            {expandedSections.has(section.id) && (
              <div className="nav-section-items">
                {section.items.filter(item => !item.superOnly || isSuper).map((item) => {
                  if (isSubSection(item)) {
                    // Render sub-section with expandable items
                    return (
                      <div key={item.id} className="nav-subsection">
                        <button
                          className={`nav-subsection-header ${expandedSubSections.has(item.id) ? 'expanded' : ''}`}
                          onClick={(e) => toggleSubSection(item.id, e)}
                        >
                          <span className="nav-item-icon">{item.icon}</span>
                          <span className="nav-item-label">{item.label}</span>
                          <span className="nav-section-chevron">
                            {expandedSubSections.has(item.id) ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                          </span>
                        </button>
                        {expandedSubSections.has(item.id) && (
                          <div className="nav-subsection-items">
                            {item.items.map((subItem) => (
                              <button
                                key={subItem.id}
                                className={`nav-item nav-item-sub ${currentPage === subItem.page ? 'active' : ''}`}
                                onClick={() => handleItemClick(subItem.page)}
                              >
                                <span className="nav-item-icon">{subItem.icon}</span>
                                <span className="nav-item-label">{subItem.label}</span>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  }
                  // Render regular item
                  return (
                    <button
                      key={item.id}
                      className={`nav-item ${currentPage === item.page ? 'active' : ''}`}
                      onClick={() => handleItemClick(item.page)}
                    >
                      <span className="nav-item-icon">{item.icon}</span>
                      <span className="nav-item-label">{item.label}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        ))}
      </nav>

      {/* Footer com perfil */}
      {user && (
        <div className="sidebar-footer">
          <div className="user-profile">
            {user.picture_url ? (
              <img src={user.picture_url} alt={user.name} className="user-avatar" />
            ) : (
              <div className="user-avatar-placeholder">
                <UserIcon size={20} />
              </div>
            )}
            <div className="user-info">
              <span className="user-name">{user.name}</span>
              <span className="user-email">{user.email}</span>
              <span style={{
                fontSize: '10px', padding: '2px 6px', borderRadius: '4px',
                background: isSuper ? '#7c3aed' : isAdmin ? '#2563eb' : '#6b7280',
                color: '#fff', marginTop: '2px', display: 'inline-block'
              }}>
                {isSuper ? 'Super' : isAdmin ? 'Admin' : 'Operador'}
              </span>
            </div>
            {onLogout && (
              <button className="logout-btn" onClick={onLogout} title="Sair">
                <LogOut size={18} />
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
