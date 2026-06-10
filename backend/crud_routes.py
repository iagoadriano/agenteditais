"""
Rotas CRUD genéricas para todas as tabelas de cadastro.
Registra endpoints REST: GET (list+search), GET/:id, POST, PUT/:id, DELETE/:id
"""
from flask import Blueprint, request, jsonify
from functools import wraps
import jwt as pyjwt
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from models import (
    get_db, Base,
    User, Empresa, EmpresaDocumento, EmpresaCertidao, EmpresaResponsavel,
    Produto, ProdutoEspecificacao, ProdutoDocumento,
    FonteEdital, FonteCertidao, Edital, EditalRequisito, EditalDocumento, EditalItem,
    Analise, AnaliseDetalhe, Proposta,
    Concorrente, PrecoHistorico, ParticipacaoEdital, AtaConsultada, OrgaoPerfil,
    Alerta, Monitoramento, Notificacao, PreferenciasNotificacao,
    Documento, Contrato, ContratoEntrega, Recurso,
    LeadCRM, AcaoPosPerda, AuditoriaLog, AprendizadoFeedback,
    ParametroScore, Dispensa, EstrategiaEdital, ClasseProduto,
    AreaProduto, ClasseProdutoV2, SubclasseProduto,
    ModalidadeLicitacao, OrigemOrgao,
    CategoriaDocumento, DocumentoNecessario,
    # FASE 1 Precificação
    Lote, LoteItem, EditalItemProduto, PrecoCamada, Lance, Comodato,
    BeneficioFiscalNcm,
    # FASE 2 Proposta
    PropostaLog, PropostaTemplate, AnvisaValidacao,
    # SPRINT 4 Recursos e Impugnações
    Impugnacao, RecursoDetalhado, RecursoTemplate, MonitoramentoJanela, ValidacaoLegal,
    # SPRINT 5 Gestão Contratual
    ContratoAditivo, ContratoDesignacao, AtividadeFiscal, ARPSaldo, SolicitacaoCarona,
    AlertaVencimentoRegra,
    # SPRINT 5 V3 — Empenhos, CRM Pipeline
    Empenho, EmpenhoItem, EmpenhoFatura, CRMParametrizacao, EditalDecisao, ValidacaoDecisao, CRMAgendaItem,
    # SPRINT 6 — SMTP / Email
    ConfiguracaoSMTP, EmailTemplate, EmailQueue,
    # SPRINT 7 — Mercado / Analytics / Aprendizado
    SugestaoIA, PadraoDetectado, ItemIntruso,
)
from config import JWT_SECRET_KEY as JWT_SECRET
import bcrypt
import os

# RN validators — Secao 13 de requisitos_completosv8.md
from rn_validators import (
    validar_cnpj, validar_cpf, validar_ncm, validar_email, validar_uf,
    validar_gestor_diferente_fiscal, RNValidationError,
)
from rn_audit import log_transicao as _rn_log_transicao
_ENFORCE_RN = os.environ.get("ENFORCE_RN_VALIDATORS", "false").lower() == "true"

def _rn_warn_or_raise(rn_code: str, condition: bool, message: str):
    """Helper: se enforce=true levanta, senao apenas loga warning."""
    if not condition:
        if _ENFORCE_RN:
            raise RNValidationError(rn_code, message)
        else:
            print(f"[RN-WARN {rn_code}] {message}")


def _friendly_error(exc: Exception, table_slug: str | None = None) -> str:
    """Traduz erros de banco (IntegrityError, DataError, etc) em mensagens legiveis.

    Cobre casos comuns que o usuario final precisa entender:
      - Duplicate entry (violacao de UNIQUE)
      - Data truncated (valor fora do ENUM ou excede tamanho)
      - Cannot be null (coluna NOT NULL sem valor)
      - Foreign key constraint (registro pai inexistente)
    """
    msg = str(exc)
    low = msg.lower()

    if "duplicate entry" in low:
        # Traducoes especificas por tabela
        if table_slug == "empresa-responsaveis" and "uq_empresa_responsavel_cpf" in low:
            return "Ja existe um responsavel com este CPF nesta empresa."
        if table_slug == "empresas" and "cnpj" in low:
            return "Ja existe uma empresa cadastrada com este CNPJ."
        # F13-01: areas/classes duplicadas
        if "uq_area_empresa_nome" in low:
            return "Ja existe uma Area com este nome nesta empresa. Areas devem ser unicas — use Subclasses para variacoes."
        if "uq_classe_empresa_area_nome" in low:
            return "Ja existe uma Classe com este nome nesta Area. Use uma Subclasse para subdividir."
        return "Ja existe um registro com estes dados (violacao de unicidade)."

    if "data truncated for column" in low or "incorrect enum value" in low:
        import re
        m = re.search(r"[Cc]olumn ['\"]?(\w+)['\"]?", msg)
        col = m.group(1) if m else "campo"
        return f"Valor invalido para '{col}'. Verifique se selecionou uma opcao valida."

    if "cannot be null" in low:
        import re
        m = re.search(r"[Cc]olumn ['\"]?(\w+)['\"]?", msg)
        col = m.group(1) if m else "campo obrigatorio"
        return f"O campo '{col}' e obrigatorio."

    if "foreign key constraint" in low:
        return "Referencia invalida: o registro relacionado nao existe ou foi removido."

    # Fallback: retorna o erro original (limitado para nao vazar detalhes tecnicos)
    if len(msg) > 300:
        return msg[:300] + "..."
    return msg

def _validar_rns_payload(table_slug: str, data: dict):
    """Dispatcher de RN validators por table_slug. Aplicado em create e update."""
    if table_slug == "empresas":
        cnpj = data.get("cnpj")
        if cnpj:
            _rn_warn_or_raise("RN-028", validar_cnpj(cnpj), f"CNPJ invalido: {cnpj}")
        email = data.get("email")
        if email:
            _rn_warn_or_raise("RN-042", validar_email(email), f"Email invalido: {email}")
        uf = data.get("uf") or data.get("estado")
        if uf:
            _rn_warn_or_raise("RN-078", validar_uf(uf), f"UF invalida: {uf}")

    elif table_slug == "empresa-responsaveis":
        cpf = data.get("cpf")
        if cpf:
            _rn_warn_or_raise("RN-029", validar_cpf(cpf), f"CPF invalido: {cpf}")
        email = data.get("email")
        if email:
            _rn_warn_or_raise("RN-042", validar_email(email), f"Email invalido: {email}")

    elif table_slug == "produtos":
        ncm = data.get("ncm")
        if ncm:
            _rn_warn_or_raise("RN-035", validar_ncm(ncm), f"NCM deve seguir padrao XXXX.XX.XX: {ncm}")

    elif table_slug == "contrato-designacoes":
        gestor = data.get("gestor_id") or data.get("gestor_user_id")
        fiscal = data.get("fiscal_id") or data.get("fiscal_user_id")
        _rn_warn_or_raise("RN-206",
            validar_gestor_diferente_fiscal(gestor, fiscal),
            "Gestor e Fiscal nao podem ser a mesma pessoa (Art. 117 Lei 14.133/2021)")


def _validar_rns_db(table_slug: str, data: dict, db):
    """RN validators que precisam consultar o DB (cross-row).

    RN-031: bloquear proposta se empresa tem certidao vencida.
    RN-207: soma cumulativa de aditivos <= 25% do valor_total do contrato.
    RN-209: soma de entregas + novo valor <= valor_total do contrato.
    """
    from rn_validators import validar_aditivo_cumulativo, validar_entrega_dentro_saldo
    from sqlalchemy import func as _sqlfunc
    from datetime import date as _date

    if table_slug == "propostas":
        # RN-031: gate de certidao vencida. Feature flag ENFORCE_CERTIDAO_GATE default false.
        _enforce_certidao = os.environ.get("ENFORCE_CERTIDAO_GATE", "false").lower() == "true"
        empresa_id_prop = data.get("empresa_id")
        if not empresa_id_prop:
            try:
                from models import Edital as _Edital
                ed = db.query(_Edital).filter(_Edital.id == data.get("edital_id")).first()
                if ed and hasattr(ed, "empresa_id"):
                    empresa_id_prop = ed.empresa_id
            except Exception:
                pass
        if empresa_id_prop:
            try:
                from models import EmpresaCertidao as _EC
                hoje = _date.today()
                vencidas = db.query(_EC).filter(
                    _EC.empresa_id == empresa_id_prop,
                    _EC.data_vencimento < hoje,
                ).count()
                if vencidas > 0:
                    msg = f"Empresa possui {vencidas} certidao(oes) vencida(s). Regularize antes de submeter proposta."
                    if _enforce_certidao and _ENFORCE_RN:
                        raise RNValidationError("RN-031", msg)
                    print(f"[RN-031 WARN] {msg} (empresa {empresa_id_prop})")
            except RNValidationError:
                raise
            except Exception as _e:
                print(f"[RN-031] erro ao verificar certidoes: {_e}")

    if table_slug == "contrato-aditivos":
        contrato_id = data.get("contrato_id")
        novo_pct = data.get("percentual")
        if contrato_id and novo_pct is not None:
            try:
                soma_existente = db.query(_sqlfunc.coalesce(_sqlfunc.sum(ContratoAditivo.percentual), 0.0))\
                    .filter(ContratoAditivo.contrato_id == contrato_id).scalar() or 0.0
                _rn_warn_or_raise("RN-207",
                    validar_aditivo_cumulativo(float(soma_existente), float(novo_pct)),
                    f"Aditivo cumulativo excederia 25% (existente={soma_existente}%, novo={novo_pct}%). Art. 124-126 Lei 14.133/2021.")
            except (TypeError, ValueError) as _e:
                print(f"[RN-207] Erro ao validar: {_e}")

    elif table_slug == "contrato-entregas":
        contrato_id = data.get("contrato_id")
        novo_valor = data.get("valor_total") or 0
        if contrato_id and novo_valor:
            try:
                contrato = db.query(Contrato).filter(Contrato.id == contrato_id).first()
                if contrato and contrato.valor_total:
                    soma_entregas = db.query(_sqlfunc.coalesce(_sqlfunc.sum(ContratoEntrega.valor_total), 0.0))\
                        .filter(ContratoEntrega.contrato_id == contrato_id).scalar() or 0.0
                    saldo = float(contrato.valor_total) - float(soma_entregas)
                    _rn_warn_or_raise("RN-209",
                        validar_entrega_dentro_saldo(novo_valor, saldo),
                        f"Valor da entrega ({novo_valor}) excede saldo restante do contrato ({saldo}).")
            except (TypeError, ValueError) as _e:
                print(f"[RN-209] Erro ao validar: {_e}")

crud_bp = Blueprint('crud', __name__)


# ─── Auth decorator ────────────────────────────────────────────────────────────

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Token não fornecido"}), 401
        token = auth_header.split(' ')[1]
        try:
            payload = pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            request.user_id = payload["user_id"]
            request.empresa_id = payload.get("empresa_id")
            request.is_super = payload.get("is_super", False)
            request.papel = payload.get("papel")
            # Fallback: se JWT sem empresa_id, buscar primeira empresa do user
            if not request.empresa_id:
                db = get_db()
                try:
                    empresa = db.query(Empresa).filter(Empresa.user_id == request.user_id).first()
                    request.empresa_id = empresa.id if empresa else None
                finally:
                    db.close()
        except pyjwt.ExpiredSignatureError:
            return jsonify({"error": "Token expirado"}), 401
        except pyjwt.InvalidTokenError:
            return jsonify({"error": "Token inválido"}), 401
        return f(*args, **kwargs)
    return decorated


SUPER_ONLY_TABLES: set = set()  # checagens inline abaixo
# Tabelas que só superuser pode criar/editar/deletar
SUPER_WRITE_TABLES = {'empresas', 'users'}
# Tabelas que exigem ao menos admin (is_super ou papel=admin) para escrita
ADMIN_WRITE_TABLES = {'produtos', 'produtos-especificacoes', 'produtos-documentos',
                      'areas-produto', 'classes-produto-v2', 'subclasses-produto',
                      'empresa-documentos', 'empresa-certidoes', 'empresa-responsaveis',
                      'parametros-score', 'fontes-editais', 'fontes-certidoes'}


def get_current_user_id():
    return getattr(request, 'user_id', None)


def get_current_empresa_id():
    return getattr(request, 'empresa_id', None)


# ─── Table registry ────────────────────────────────────────────────────────────

# Maps table slug → { model, user_scoped, parent_fk, search_fields, label }
CRUD_TABLES = {
    # === Empresa ===
    "empresas": {
        "model": Empresa,
        "search_fields": ["cnpj", "razao_social", "nome_fantasia", "cidade"],
        "label": "Empresa",
        "required": ["cnpj", "razao_social"],
    },
    # === Usuários ===
    "users": {
        "model": User,
        "global": True,
        "search_fields": ["email", "name"],
        "label": "Usuário",
        "required": ["email", "name"],
        "password_field": "password",  # campo virtual — será hasheado
    },
    # === Áreas, Classes e Subclasses (por empresa) ===
    "areas-produto": {
        "model": AreaProduto,
        "empresa_scoped": True,
        "search_fields": ["nome"],
        "label": "Área de Produto",
        "required": ["nome"],
    },
    "classes-produto-v2": {
        "model": ClasseProdutoV2,
        "empresa_scoped": True,
        "search_fields": ["nome"],
        "label": "Classe de Produto",
        "required": ["nome", "area_id"],
        "parent_fk": "area_id",
    },
    "subclasses-produto": {
        "model": SubclasseProduto,
        "empresa_scoped": True,
        "search_fields": ["nome"],
        "label": "Subclasse de Produto",
        "required": ["nome", "classe_id"],
        "parent_fk": "classe_id",
    },
    # === Tabelas globais (referência) ===
    "modalidades-licitacao": {
        "model": ModalidadeLicitacao,
        "global": True,
        "search_fields": ["nome"],
        "label": "Modalidade de Licitação",
        "required": ["nome"],
    },
    "origens-orgao": {
        "model": OrigemOrgao,
        "global": True,
        "search_fields": ["nome"],
        "label": "Origem do Órgão",
        "required": ["nome"],
    },
    "empresa-documentos": {
        "model": EmpresaDocumento,
        "user_scoped": False,
        "parent_fk": "empresa_id",
        "parent_model": Empresa,
        "search_fields": ["nome_arquivo", "tipo"],
        "label": "Documento da Empresa",
        "required": ["empresa_id", "tipo", "nome_arquivo", "path_arquivo"],
    },
    "empresa-certidoes": {
        "model": EmpresaCertidao,
        "user_scoped": False,
        "parent_fk": "empresa_id",
        "parent_model": Empresa,
        "search_fields": ["tipo", "orgao_emissor", "numero", "fonte_certidao_id"],
        "label": "Certidão da Empresa",
        "required": ["empresa_id", "tipo", "data_vencimento"],
    },
    "empresa-responsaveis": {
        "model": EmpresaResponsavel,
        "user_scoped": False,
        "parent_fk": "empresa_id",
        "parent_model": Empresa,
        "search_fields": ["nome", "cargo", "email", "cpf"],
        "label": "Responsável da Empresa",
        "required": ["empresa_id", "nome"],
    },
    "beneficios-fiscais-ncm": {
        "model": BeneficioFiscalNcm,
        "user_scoped": False,
        "search_fields": ["ncm", "descricao", "base_legal"],
        "label": "Benefício Fiscal NCM",
        "required": ["ncm"],
    },
    # === Portfolio ===
    "produtos": {
        "model": Produto,
        "empresa_scoped": True,
        "search_fields": ["nome", "codigo_interno", "fabricante", "modelo", "ncm"],
        "label": "Produto",
        "required": ["nome", "categoria"],
    },
    "produtos-especificacoes": {
        "model": ProdutoEspecificacao,
        "user_scoped": False,
        "parent_fk": "produto_id",
        "parent_model": Produto,
        "search_fields": ["nome_especificacao", "valor"],
        "label": "Especificação do Produto",
        "required": ["produto_id", "nome_especificacao", "valor"],
    },
    "produtos-documentos": {
        "model": ProdutoDocumento,
        "user_scoped": False,
        "parent_fk": "produto_id",
        "parent_model": Produto,
        "search_fields": ["nome_arquivo", "tipo"],
        "label": "Documento do Produto",
        "required": ["produto_id", "tipo", "nome_arquivo", "path_arquivo"],
    },
    # === Fontes ===
    "fontes-editais": {
        "model": FonteEdital,
        "user_scoped": False,
        "global": True,
        "search_fields": ["nome", "tipo", "url_base"],
        "label": "Fonte de Edital",
        "required": ["nome", "tipo"],
    },
    "fontes-certidoes": {
        "model": FonteCertidao,
        "empresa_scoped": True,
        "include_globais": True,  # NOVO: tambem mostra fontes com empresa_id IS NULL (catalogo do sistema)
        "search_fields": ["nome", "tipo_certidao", "orgao_emissor", "url_portal", "uf", "cidade"],
        "label": "Fonte de Certidão",
        "required": ["tipo_certidao", "nome", "url_portal"],
        "encrypt_fields": ["senha_criptografada"],
    },
    # === Editais ===
    "editais": {
        "model": Edital,
        "empresa_scoped": True,
        "search_fields": ["numero", "orgao", "objeto", "uf", "cidade"],
        "label": "Edital",
        "required": ["numero", "orgao", "objeto"],
    },
    "editais-requisitos": {
        "model": EditalRequisito,
        "user_scoped": False,
        "parent_fk": "edital_id",
        "parent_model": Edital,
        "search_fields": ["descricao", "nome_especificacao"],
        "label": "Requisito do Edital",
        "required": ["edital_id", "tipo", "descricao"],
    },
    "editais-documentos": {
        "model": EditalDocumento,
        "user_scoped": False,
        "parent_fk": "edital_id",
        "parent_model": Edital,
        "search_fields": ["nome_arquivo", "tipo"],
        "label": "Documento do Edital",
        "required": ["edital_id", "tipo", "nome_arquivo", "path_arquivo"],
    },
    "editais-itens": {
        "model": EditalItem,
        "user_scoped": False,
        "parent_fk": "edital_id",
        "parent_model": Edital,
        "search_fields": ["descricao", "codigo_item"],
        "label": "Item do Edital",
        "required": ["edital_id"],
    },
    # === Análises ===
    "analises": {
        "model": Analise,
        "empresa_scoped": True,
        "search_fields": ["recomendacao"],
        "label": "Análise",
        "required": ["edital_id", "produto_id"],
    },
    "analises-detalhes": {
        "model": AnaliseDetalhe,
        "user_scoped": False,
        "parent_fk": "analise_id",
        "parent_model": Analise,
        "search_fields": ["justificativa", "valor_exigido", "valor_produto"],
        "label": "Detalhe da Análise",
        "required": ["analise_id", "requisito_id", "status"],
    },
    # === Propostas ===
    "propostas": {
        "model": Proposta,
        "empresa_scoped": True,
        "search_fields": ["texto_tecnico"],
        "label": "Proposta",
        "required": ["edital_id", "produto_id"],
    },
    # === Concorrência ===
    "orgaos-perfil": {
        "model": OrgaoPerfil,
        "empresa_scoped": True,
        "search_fields": ["nome", "cnpj", "uf"],
        "label": "Perfil de Órgão",
        "required": ["cnpj"],
    },
    "atas-consultadas": {
        "model": AtaConsultada,
        "empresa_scoped": True,
        "search_fields": ["titulo", "orgao", "cnpj_orgao", "numero_controle_pncp"],
        "label": "Ata Consultada",
        "required": [],
    },
    "concorrentes": {
        "model": Concorrente,
        "user_scoped": False,
        "global": True,
        "search_fields": ["nome", "cnpj", "razao_social"],
        "label": "Concorrente",
        "required": ["nome"],
    },
    "precos-historicos": {
        "model": PrecoHistorico,
        "empresa_scoped": True,
        "search_fields": ["empresa_vencedora", "cnpj_vencedor", "fonte"],
        "label": "Preço Histórico",
        "required": [],
    },
    "participacoes-editais": {
        "model": ParticipacaoEdital,
        "user_scoped": False,
        "parent_fk": "edital_id",
        "parent_model": Edital,
        "search_fields": ["motivo_desclassificacao"],
        "label": "Participação em Edital",
        "required": ["edital_id"],
    },
    # === Alertas e Monitoramento ===
    "alertas": {
        "model": Alerta,
        "empresa_scoped": True,
        "search_fields": ["titulo", "mensagem", "tipo"],
        "label": "Alerta",
        "required": ["edital_id", "tipo", "data_disparo"],
    },
    "monitoramentos": {
        "model": Monitoramento,
        "empresa_scoped": True,
        "search_fields": ["termo"],
        "label": "Monitoramento",
        "required": ["termo"],
    },
    "notificacoes": {
        "model": Notificacao,
        "empresa_scoped": True,
        "search_fields": ["titulo", "mensagem"],
        "label": "Notificação",
        "required": ["tipo", "titulo", "mensagem"],
    },
    "preferencias-notificacao": {
        "model": PreferenciasNotificacao,
        "user_scoped": True,
        "search_fields": [],
        "label": "Preferências de Notificação",
        "required": [],
    },
    # === Documentos Gerados ===
    "documentos": {
        "model": Documento,
        "empresa_scoped": True,
        "search_fields": ["titulo", "tipo"],
        "label": "Documento Gerado",
        "required": ["tipo", "titulo", "conteudo_md"],
    },
    # === Contratos ===
    "contratos": {
        "model": Contrato,
        "empresa_scoped": True,
        "search_fields": ["numero_contrato", "orgao", "objeto"],
        "label": "Contrato",
        "required": [],
    },
    "contrato-entregas": {
        "model": ContratoEntrega,
        "user_scoped": False,
        "parent_fk": "contrato_id",
        "parent_model": Contrato,
        "search_fields": ["descricao", "nota_fiscal", "numero_empenho"],
        "label": "Entrega de Contrato",
        "required": ["contrato_id", "data_prevista"],
    },
    # === Recursos ===
    "recursos": {
        "model": Recurso,
        "empresa_scoped": True,
        "search_fields": ["motivo", "fundamentacao_legal"],
        "label": "Recurso",
        "required": ["edital_id", "tipo", "prazo_limite"],
    },
    # === CRM ===
    "leads-crm": {
        "model": LeadCRM,
        "empresa_scoped": True,
        "search_fields": ["orgao", "cnpj_orgao", "contato_nome", "contato_email"],
        "label": "Lead CRM",
        "required": ["orgao"],
    },
    "acoes-pos-perda": {
        "model": AcaoPosPerda,
        "empresa_scoped": True,
        "search_fields": ["descricao", "responsavel"],
        "label": "Ação Pós-Perda",
        "required": [],
    },
    # === Auditoria ===
    "auditoria-log": {
        "model": AuditoriaLog,
        "user_scoped": True,
        "search_fields": ["acao", "entidade", "user_email"],
        "label": "Log de Auditoria",
        "required": ["acao", "entidade"],
        "read_only": True,
    },
    "aprendizado-feedback": {
        "model": AprendizadoFeedback,
        "empresa_scoped": True,
        "search_fields": ["tipo_evento", "entidade"],
        "label": "Feedback de Aprendizado",
        "required": ["tipo_evento"],
    },
    # === Parâmetros ===
    "parametros-score": {
        "model": ParametroScore,
        "empresa_scoped": True,
        "search_fields": [],
        "label": "Parâmetros de Score",
        "required": [],
    },
    "dispensas": {
        "model": Dispensa,
        "empresa_scoped": True,
        "search_fields": ["artigo", "justificativa"],
        "label": "Dispensa",
        "required": ["edital_id"],
    },
    "estrategias-editais": {
        "model": EstrategiaEdital,
        "empresa_scoped": True,
        "search_fields": ["justificativa", "decidido_por", "edital_id"],
        "label": "Estratégia de Edital",
        "required": ["edital_id"],
    },
    # === Classes de Produtos ===
    "classes-produtos": {
        "model": ClasseProduto,
        "empresa_scoped": True,
        "search_fields": ["nome"],
        "label": "Classe de Produto",
        "required": ["nome", "tipo"],
        "parent_field": "classe_pai_id",
    },
    # === Documentos: Categorias e Tipos Necessários ===
    "categorias-documento": {
        "model": CategoriaDocumento,
        "global": True,
        "search_fields": ["nome"],
        "label": "Categoria de Documento",
        "required": ["nome"],
    },
    "documentos-necessarios": {
        "model": DocumentoNecessario,
        "global": True,
        "search_fields": ["nome", "tipo_chave", "base_legal"],
        "label": "Documento Necessário",
        "required": ["nome", "tipo_chave"],
    },
    # === FASE 1 — Precificação ===
    "lotes": {
        "model": Lote,
        "empresa_scoped": True,
        "parent_fk": "edital_id",
        "parent_model": Edital,
        "search_fields": ["nome", "especialidade"],
        "label": "Lote",
        "required": ["edital_id", "numero_lote"],
    },
    "lote-itens": {
        "model": LoteItem,
        "user_scoped": False,
        "parent_fk": "lote_id",
        "parent_model": Lote,
        "search_fields": [],
        "label": "Item do Lote",
        "required": ["lote_id", "edital_item_id"],
    },
    "edital-item-produto": {
        "model": EditalItemProduto,
        "empresa_scoped": True,
        # parent_id => filtra por item do edital (PrecificacaoPage busca o vinculo de 1 item)
        "parent_fk": "edital_item_id",
        "parent_model": EditalItem,
        "search_fields": [],
        "label": "Vínculo Item-Produto",
        "required": ["edital_item_id", "produto_id"],
    },
    "preco-camadas": {
        "model": PrecoCamada,
        "empresa_scoped": True,
        # parent_id => filtra pela camada do vinculo certo (antes retornava a 1a da empresa)
        "parent_fk": "edital_item_produto_id",
        "parent_model": EditalItemProduto,
        "search_fields": [],
        "label": "Camada de Preço",
        "required": ["edital_item_produto_id"],
    },
    "lances": {
        "model": Lance,
        "empresa_scoped": True,
        "search_fields": ["observacao"],
        "label": "Lance",
        "required": ["edital_item_produto_id", "valor_lance"],
    },
    "comodatos": {
        "model": Comodato,
        "empresa_scoped": True,
        "parent_fk": "edital_id",
        "parent_model": Edital,
        "search_fields": ["nome_equipamento"],
        "label": "Comodato",
        "required": ["edital_id", "nome_equipamento"],
    },
    # === FASE 2 — Proposta ===
    "proposta-templates": {
        "model": PropostaTemplate,
        "user_scoped": False,
        "empresa_scoped": True,
        "search_fields": ["nome"],
        "label": "Template de Proposta",
        "required": ["nome"],
    },
    "proposta-logs": {
        "model": PropostaLog,
        "empresa_scoped": True,
        "parent_fk": "proposta_id",
        "parent_model": Proposta,
        "search_fields": ["campo"],
        "label": "Log de Proposta",
        "required": ["proposta_id", "campo"],
        "read_only": True,
    },
    "anvisa-validacoes": {
        "model": AnvisaValidacao,
        "user_scoped": False,
        "parent_fk": "proposta_id",
        "parent_model": Proposta,
        "search_fields": ["registro", "status"],
        "label": "Validação ANVISA",
        "required": ["proposta_id", "produto_id"],
    },
    # === SPRINT 4 — Recursos e Impugnações ===
    "impugnacoes": {
        "model": Impugnacao,
        "empresa_scoped": True,
        "parent_fk": "edital_id",
        "parent_model": Edital,
        "search_fields": ["texto", "tipo", "status"],
        "label": "Impugnação",
        "required": ["edital_id"],
    },
    "recursos-detalhados": {
        "model": RecursoDetalhado,
        "empresa_scoped": True,
        "parent_fk": "edital_id",
        "parent_model": Edital,
        "search_fields": ["texto_juridico", "texto_tecnico", "empresa_alvo"],
        "label": "Recurso Detalhado",
        "required": ["edital_id"],
    },
    "recurso-templates": {
        "model": RecursoTemplate,
        "user_scoped": False,
        "empresa_scoped": True,
        "search_fields": ["nome", "tipo"],
        "label": "Template de Recurso",
        "required": ["nome", "tipo"],
    },
    "monitoramento-janelas": {
        "model": MonitoramentoJanela,
        "empresa_scoped": True,
        "parent_fk": "edital_id",
        "parent_model": Edital,
        "search_fields": ["status"],
        "label": "Monitoramento de Janela",
        "required": ["edital_id"],
    },
    "validacoes-legais": {
        "model": ValidacaoLegal,
        "empresa_scoped": True,
        "parent_fk": "edital_id",
        "parent_model": Edital,
        "search_fields": ["analise_ia"],
        "label": "Validação Legal",
        "required": ["edital_id"],
        "read_only": True,
    },
    # === SPRINT 5 — Gestão Contratual ===
    "contrato-aditivos": {
        "model": ContratoAditivo,
        "empresa_scoped": True,
        "parent_fk": "contrato_id",
        "parent_model": Contrato,
        "search_fields": ["tipo", "justificativa", "fundamentacao_legal"],
        "label": "Aditivos Contratuais",
        "required": ["contrato_id", "tipo", "justificativa"],
    },
    "contrato-designacoes": {
        "model": ContratoDesignacao,
        "empresa_scoped": True,
        "parent_fk": "contrato_id",
        "parent_model": Contrato,
        "search_fields": ["nome", "cargo", "tipo", "portaria_numero"],
        "label": "Designações de Contrato",
        "required": ["contrato_id", "tipo", "nome"],
    },
    "atividades-fiscais": {
        "model": AtividadeFiscal,
        "empresa_scoped": True,
        "parent_fk": "designacao_id",
        "parent_model": ContratoDesignacao,
        "search_fields": ["tipo", "descricao"],
        "label": "Atividades Fiscais",
        "required": ["designacao_id", "tipo", "descricao"],
    },
    "arp-saldos": {
        "model": ARPSaldo,
        "empresa_scoped": True,
        "parent_fk": "ata_id",
        "parent_model": AtaConsultada,
        "search_fields": ["item_descricao", "catmat_catser"],
        "label": "Saldos ARP",
        "required": ["ata_id", "item_descricao", "quantidade_registrada"],
    },
    "solicitacoes-carona": {
        "model": SolicitacaoCarona,
        "empresa_scoped": True,
        "parent_fk": "arp_saldo_id",
        "parent_model": ARPSaldo,
        "search_fields": ["orgao_solicitante", "cnpj_solicitante"],
        "label": "Solicitações de Carona",
        "required": ["arp_saldo_id", "orgao_solicitante", "quantidade_solicitada"],
    },
    "alerta-regras": {
        "model": AlertaVencimentoRegra,
        "empresa_scoped": True,
        "search_fields": ["tipo_entidade"],
        "label": "Regras de Alerta de Vencimento",
        "required": ["tipo_entidade"],
    },
    # === SPRINT 5 V3 — Empenhos ===
    "empenhos": {
        "model": Empenho,
        "empresa_scoped": True,
        "parent_fk": "contrato_id",
        "parent_model": Contrato,
        "search_fields": ["numero_empenho", "fonte_recurso", "natureza_despesa"],
        "label": "Empenhos",
        "required": ["contrato_id", "numero_empenho", "valor_empenhado", "data_empenho"],
    },
    "empenho-itens": {
        "model": EmpenhoItem,
        "empresa_scoped": True,
        "parent_fk": "empenho_id",
        "parent_model": Empenho,
        "search_fields": ["descricao"],
        "label": "Itens do Empenho",
        "required": ["empenho_id", "descricao", "quantidade", "valor_unitario", "valor_total"],
    },
    "empenho-faturas": {
        "model": EmpenhoFatura,
        "empresa_scoped": True,
        "parent_fk": "empenho_id",
        "parent_model": Empenho,
        "search_fields": ["numero_fatura", "nota_fiscal"],
        "label": "Faturas do Empenho",
        "required": ["empenho_id", "numero_fatura", "valor_fatura", "data_emissao"],
    },
    # === SPRINT 5 V3 — CRM Pipeline ===
    "crm-parametrizacoes": {
        "model": CRMParametrizacao,
        "empresa_scoped": True,
        "search_fields": ["valor", "tipo"],
        "label": "Parametrizações CRM",
        "required": ["tipo", "valor"],
    },
    "edital-decisoes": {
        "model": EditalDecisao,
        "empresa_scoped": True,
        "parent_fk": "edital_id",
        "parent_model": Edital,
        "search_fields": ["motivo_texto", "justificativa", "tipo"],
        "label": "Decisões sobre Editais",
        "required": ["edital_id", "tipo"],
    },
    # CV08-8/10 (Arnaldo Sprint 2 V8): decisao GO/NO-GO da tela de Validacao
    "validacao_decisoes": {
        "model": ValidacaoDecisao,
        "empresa_scoped": True,
        "parent_fk": "edital_id",
        "parent_model": Edital,
        "search_fields": ["edital_numero", "decisao", "motivo", "justificativa"],
        "label": "Decisões de Validação",
        "required": ["edital_id", "decisao"],
    },
    "crm-agenda-items": {
        "model": CRMAgendaItem,
        "empresa_scoped": True,
        "search_fields": ["titulo", "responsavel", "descricao"],
        "label": "Agenda CRM",
        "required": ["titulo", "data_limite"],
    },
    # SPRINT 6 — SMTP / Email
    "smtp-config": {
        "model": ConfiguracaoSMTP,
        "empresa_scoped": False,
        "search_fields": ["host", "from_email"],
        "label": "Configuração SMTP",
        "required": ["host", "port", "from_email"],
        "encrypt_fields": ["password_encrypted"],
    },
    "email-templates": {
        "model": EmailTemplate,
        "empresa_scoped": True,
        "search_fields": ["slug", "nome", "assunto"],
        "label": "Template de Email",
        "required": ["slug", "nome", "assunto", "corpo_html"],
    },
    "email-queue": {
        "model": EmailQueue,
        "empresa_scoped": True,
        "search_fields": ["destinatario", "assunto", "template_slug"],
        "label": "Fila de Email",
        "required": ["destinatario", "assunto"],
        "read_only": ["status", "retry_count", "erro_mensagem", "enviado_em"],
    },
    # === SPRINT 7 — Mercado / Analytics / Aprendizado ===
    "sugestoes-ia": {
        "model": SugestaoIA,
        "empresa_scoped": True,
        "search_fields": ["titulo", "tipo", "descricao"],
        "label": "Sugestao IA",
        "required": ["tipo", "titulo", "descricao"],
    },
    "padroes-detectados": {
        "model": PadraoDetectado,
        "empresa_scoped": True,
        "search_fields": ["titulo", "tipo", "descricao"],
        "label": "Padrao Detectado",
        "required": ["tipo", "titulo", "descricao"],
    },
    "itens-intrusos": {
        "model": ItemIntruso,
        "empresa_scoped": True,
        "search_fields": ["descricao_item", "ncm", "criticidade"],
        "label": "Item Intruso",
        "required": ["edital_id", "descricao_item", "criticidade"],
    },
}


# ─── Helper: set column value with type coercion ───────────────────────────────

def _get_attr_name(model_class, col_name):
    """Retorna o nome do atributo Python para uma coluna DB (pode diferir quando Column tem alias)."""
    for attr_name, mapped_col in model_class.__mapper__.columns.items():
        if mapped_col.name == col_name:
            return attr_name
    return col_name  # fallback: mesmo nome


def _set_column_value(instance, col_name, value, model_class):
    """Set a column value with proper type coercion for SQLAlchemy."""
    col = model_class.__table__.columns.get(col_name)
    if col is None:
        return
    attr_name = _get_attr_name(model_class, col_name)

    col_type = str(col.type)

    # Skip None values for nullable columns
    if value is None or value == "":
        if col.nullable:
            setattr(instance, attr_name, None)
        return

    try:
        if "DECIMAL" in col_type or "NUMERIC" in col_type:
            setattr(instance, attr_name, Decimal(str(value)))
        elif "INTEGER" in col_type or "INT" in col_type:
            setattr(instance, attr_name, int(value))
        elif "BOOLEAN" in col_type or "TINYINT" in col_type:
            if isinstance(value, bool):
                setattr(instance, attr_name, value)
            elif isinstance(value, str):
                setattr(instance, attr_name, value.lower() in ("true", "1", "yes", "sim"))
            else:
                setattr(instance, attr_name, bool(value))
        elif "DATETIME" in col_type:
            if isinstance(value, str):
                parsed = None
                # 1) ISO 8601 completo (inclui o que o JS toISOString() gera:
                #    "2026-05-22T02:25:30.123Z" — com milissegundos e 'Z').
                #    datetime.strptime nao cobre fracao+Z, entao usamos fromisoformat.
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    # normaliza para naive (coluna DATETIME sem timezone)
                    if parsed.tzinfo is not None:
                        parsed = parsed.replace(tzinfo=None)
                except ValueError:
                    parsed = None
                # 2) fallback: formatos explicitos
                if parsed is None:
                    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                        try:
                            parsed = datetime.strptime(value, fmt)
                            break
                        except ValueError:
                            continue
                if parsed is not None:
                    setattr(instance, attr_name, parsed)
            else:
                setattr(instance, attr_name, value)
        elif "DATE" in col_type and "DATETIME" not in col_type:
            if isinstance(value, str):
                from datetime import date
                setattr(instance, attr_name, date.fromisoformat(value))
            else:
                setattr(instance, attr_name, value)
        elif "JSON" in col_type:
            if isinstance(value, str):
                import json
                setattr(instance, attr_name, json.loads(value))
            else:
                setattr(instance, attr_name, value)
        else:
            setattr(instance, attr_name, value)
    except (ValueError, InvalidOperation, TypeError):
        setattr(instance, attr_name, value)


# ─── Schema endpoint ───────────────────────────────────────────────────────────

@crud_bp.route("/api/crud/schema", methods=["GET"])
@require_auth
def get_crud_schema():
    """Return metadata about all CRUD tables for the frontend."""
    schemas = {}
    for slug, config in CRUD_TABLES.items():
        model = config["model"]
        columns = []
        for col in model.__table__.columns:
            if col.name in ("id", "created_at", "updated_at"):
                continue
            col_info = {
                "name": col.name,
                "type": str(col.type).split("(")[0].upper(),
                "nullable": col.nullable,
                "required": col.name in config.get("required", []),
            }
            # Enums
            if hasattr(col.type, "enums"):
                col_info["type"] = "ENUM"
                col_info["options"] = list(col.type.enums)
            # ForeignKey
            for fk in col.foreign_keys:
                col_info["fk"] = str(fk.column)
            if col.default is not None and hasattr(col.default, "arg"):
                arg = col.default.arg
                if callable(arg):
                    col_info["default"] = "auto"
                else:
                    col_info["default"] = str(arg)
            columns.append(col_info)

        schemas[slug] = {
            "label": config["label"],
            "columns": columns,
            "search_fields": config.get("search_fields", []),
            "user_scoped": config.get("user_scoped", False),
            "empresa_scoped": config.get("empresa_scoped", False),
            "global": config.get("global", False),
            "read_only": config.get("read_only", False),
            "parent_fk": config.get("parent_fk"),
        }
    return jsonify(schemas)


# ─── Generic CRUD endpoints ────────────────────────────────────────────────────

@crud_bp.route("/api/crud/<table_slug>", methods=["GET"])
@require_auth
def crud_list(table_slug):
    """List records with optional search. Query params: q (search), parent_id, limit, offset."""
    config = CRUD_TABLES.get(table_slug)
    if not config:
        return jsonify({"error": f"Tabela '{table_slug}' não encontrada"}), 404

    if table_slug in SUPER_ONLY_TABLES and not getattr(request, 'is_super', False):
        return jsonify({"error": "Acesso restrito ao superusuário"}), 403

    model = config["model"]
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    q = request.args.get("q", "").strip()
    parent_id = request.args.get("parent_id")
    limit = min(int(request.args.get("limit", 200)), 500)
    offset = int(request.args.get("offset", 0))

    db = get_db()
    try:
        query = db.query(model)

        is_super = getattr(request, 'is_super', False)
        papel = getattr(request, 'papel', None)
        is_admin = is_super or papel == 'admin'

        # Scope by empresa if empresa_scoped
        if config.get("empresa_scoped") and hasattr(model, "empresa_id") and empresa_id:
            if config.get("include_globais"):
                # Catalogos (ex: fontes_certidoes): mostra registros da empresa OU globais (NULL)
                from sqlalchemy import or_ as _or_
                query = query.filter(_or_(
                    model.empresa_id == empresa_id,
                    model.empresa_id.is_(None),
                ))
                # F04-01: para fontes-certidoes, filtrar globais por UF da empresa
                # (federais: uf NULL → mantem; estaduais/municipais: uf == empresa.uf)
                if table_slug == 'fontes-certidoes':
                    try:
                        from models import Empresa as _Emp
                        emp = db.query(_Emp).filter(_Emp.id == empresa_id).first()
                        if emp and emp.uf:
                            from sqlalchemy import or_ as _or2_, and_ as _and2_
                            # Manter: globais do tipo SEM uf (federais) + globais com uf == empresa.uf + da empresa
                            query = query.filter(_or2_(
                                model.empresa_id == empresa_id,         # da empresa = mantem
                                model.uf.is_(None),                     # global federal (sem UF)
                                model.uf == '',                         # legado: string vazia
                                model.uf == emp.uf,                     # global estadual/municipal da MESMA UF
                            ))
                    except Exception as _ex:
                        print(f"[F04-01] aviso filtro UF nao aplicado: {_ex}")
            else:
                query = query.filter(model.empresa_id == empresa_id)
        elif table_slug == 'empresas':
            # Superuser sempre vê todas as empresas (independente da empresa_id no JWT)
            if is_super:
                pass  # vê todas
            elif empresa_id:
                query = query.filter(model.id == empresa_id)
        elif config.get("user_scoped") and hasattr(model, "user_id") and not is_admin:
            query = query.filter(model.user_id == user_id)
        elif config.get("parent_fk") and parent_id:
            fk_col = getattr(model, config["parent_fk"], None)
            if fk_col is not None:
                query = query.filter(fk_col == parent_id)
            # Verify parent ownership by empresa
            parent_model = config.get("parent_model")
            if parent_model and hasattr(parent_model, "empresa_id") and empresa_id:
                parent = db.query(parent_model).filter(
                    parent_model.id == parent_id,
                    parent_model.empresa_id == empresa_id
                ).first()
                if not parent:
                    return jsonify({"error": "Registro pai não encontrado"}), 404
        elif not config.get("global"):
            # For child tables without parent_id, try to scope by empresa through parent
            if config.get("parent_fk"):
                parent_model = config.get("parent_model")
                if parent_model and hasattr(parent_model, "empresa_id") and empresa_id:
                    fk_col = getattr(model, config["parent_fk"], None)
                    parent_ids = [p.id for p in db.query(parent_model.id).filter(
                        parent_model.empresa_id == empresa_id
                    ).all()]
                    if fk_col is not None:
                        query = query.filter(fk_col.in_(parent_ids))

        # Additional parent filter (works alongside empresa_scoped/user_scoped)
        if parent_id and config.get("parent_fk"):
            fk_col = getattr(model, config["parent_fk"], None)
            if fk_col is not None:
                query = query.filter(fk_col == parent_id)

        # Search
        if q and config.get("search_fields"):
            from sqlalchemy import or_
            conditions = []
            for field_name in config["search_fields"]:
                field = getattr(model, field_name, None)
                if field is not None:
                    conditions.append(field.ilike(f"%{q}%"))
            if conditions:
                query = query.filter(or_(*conditions))

        # Eager load relationships for dispensas
        if table_slug == "dispensas":
            from sqlalchemy.orm import joinedload as _jl
            query = query.options(_jl(model.edital))

        # Order
        if hasattr(model, "created_at"):
            query = query.order_by(model.created_at.desc())
        elif hasattr(model, "nome"):
            query = query.order_by(model.nome)

        total = query.count()
        items = query.offset(offset).limit(limit).all()

        password_field = config.get("password_field")
        encrypt_fields = config.get("encrypt_fields", [])
        serialized = []
        for item in items:
            d = item.to_dict()
            if password_field and hasattr(item, "password_hash"):
                d["has_password"] = bool(item.password_hash)
                d["password"] = item.password_plain if hasattr(item, "password_plain") else ""
            for enc_field in encrypt_fields:
                if d.get(enc_field):
                    d[enc_field] = "••••••••"
            serialized.append(d)

        return jsonify({
            "items": serialized,
            "total": total,
            "limit": limit,
            "offset": offset,
        })
    finally:
        db.close()


@crud_bp.route("/api/crud/<table_slug>/<record_id>", methods=["GET"])
@require_auth
def crud_get(table_slug, record_id):
    """Get a single record by ID."""
    config = CRUD_TABLES.get(table_slug)
    if not config:
        return jsonify({"error": f"Tabela '{table_slug}' não encontrada"}), 404

    if table_slug in SUPER_ONLY_TABLES and not getattr(request, 'is_super', False):
        return jsonify({"error": "Acesso restrito ao superusuário"}), 403

    model = config["model"]
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    is_super = getattr(request, 'is_super', False)
    is_admin = is_super or getattr(request, 'papel', None) == 'admin'
    db = get_db()
    try:
        query = db.query(model).filter(model.id == record_id)
        if config.get("empresa_scoped") and hasattr(model, "empresa_id") and empresa_id:
            if config.get("include_globais"):
                from sqlalchemy import or_ as _or_
                query = query.filter(_or_(
                    model.empresa_id == empresa_id,
                    model.empresa_id.is_(None),
                ))
            else:
                query = query.filter(model.empresa_id == empresa_id)
        elif config.get("user_scoped") and hasattr(model, "user_id") and not is_admin:
            query = query.filter(model.user_id == user_id)

        item = query.first()
        if not item:
            return jsonify({"error": f"{config['label']} não encontrado(a)"}), 404

        result = item.to_dict()
        password_field = config.get("password_field")
        if password_field and hasattr(item, "password_hash"):
            result["has_password"] = bool(item.password_hash)
            result["password"] = item.password_plain if hasattr(item, "password_plain") else ""

        return jsonify(result)
    finally:
        db.close()


@crud_bp.route("/api/crud/<table_slug>", methods=["POST"])
@require_auth
def crud_create(table_slug):
    """Create a new record."""
    config = CRUD_TABLES.get(table_slug)
    if not config:
        return jsonify({"error": f"Tabela '{table_slug}' não encontrada"}), 404

    if config.get("read_only"):
        return jsonify({"error": f"{config['label']} é somente leitura"}), 403

    _is_super = getattr(request, 'is_super', False)
    _is_admin = _is_super or getattr(request, 'papel', None) == 'admin'
    if table_slug in SUPER_WRITE_TABLES and not _is_super:
        return jsonify({"error": "Apenas superusuários podem criar/editar esta tabela"}), 403
    if table_slug in ADMIN_WRITE_TABLES and not _is_admin:
        return jsonify({"error": "Apenas administradores podem criar/editar este recurso"}), 403

    model = config["model"]
    user_id = get_current_user_id()
    data = request.json or {}

    # Validate required fields
    for field_name in config.get("required", []):
        if field_name not in data or data[field_name] in (None, ""):
            return jsonify({"error": f"Campo '{field_name}' é obrigatório"}), 400

    # RN validators (Secao 13 requisitos_completosv8.md)
    try:
        _validar_rns_payload(table_slug, data)
    except RNValidationError as e:
        return jsonify({"error": str(e), "rn_code": e.rn_code}), 400

    db = get_db()

    # RN validators DB-aware (RN-207, RN-209)
    try:
        _validar_rns_db(table_slug, data, db)
    except RNValidationError as e:
        return jsonify({"error": str(e), "rn_code": e.rn_code}), 400

    try:
        instance = model()
        instance.id = str(uuid.uuid4())

        # Set user_id (trilha de auditoria: quem criou)
        if hasattr(model, "user_id"):
            instance.user_id = user_id

        # Set empresa_id if empresa-scoped
        if config.get("empresa_scoped") and hasattr(model, "empresa_id"):
            # Usar empresa_id do body se fornecido, senão usar do token
            instance.empresa_id = data.get("empresa_id") or get_current_empresa_id()

        # Set fields from data
        skip_fields = {"id", "created_at", "updated_at"}
        password_field = config.get("password_field")
        for col in model.__table__.columns:
            if col.name in skip_fields:
                continue
            if col.name == "user_id" and hasattr(model, "user_id"):
                continue
            if col.name == "empresa_id" and config.get("empresa_scoped"):
                continue
            if col.name == "password_hash" and password_field:
                continue  # handled below
            if col.name == "password_plain" and password_field:
                continue  # handled below
            if col.name in data:
                _set_column_value(instance, col.name, data[col.name], model)

        # Hash password if provided
        if password_field and data.get(password_field) and hasattr(model, "password_hash"):
            plain = data[password_field]
            hashed = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            instance.password_hash = hashed
            if hasattr(model, "password_plain"):
                instance.password_plain = plain

        # Encrypt fields (Fernet reversible encryption)
        for enc_field in config.get("encrypt_fields", []):
            val = getattr(instance, enc_field, None)
            if val and isinstance(val, str) and val.strip():
                from crypto_utils import encrypt_password
                setattr(instance, enc_field, encrypt_password(val))

        db.add(instance)
        db.commit()
        db.refresh(instance)

        # RN-037: audit log universal (best-effort, nao quebra fluxo)
        try:
            _AUDITED_TABLES = {
                "empresas", "produtos", "editais", "propostas", "contratos",
                "contrato-aditivos", "contrato-designacoes", "empresa-responsaveis",
                "impugnacoes", "recursos-detalhados",
                "estrategias-editais",  # RN-080: versionamento GO/NO-GO
            }
            if table_slug in _AUDITED_TABLES:
                _rn_log_transicao(
                    entidade=table_slug,
                    entidade_id=str(instance.id),
                    acao="create",
                    dados_antes=None,
                    dados_depois={k: (str(v) if hasattr(v, "isoformat") else v) for k, v in (data or {}).items() if k not in ("password", "senha")},
                    user_id=user_id,
                )
        except Exception as _audit_e:
            print(f"[RN-037] log_transicao create error: {_audit_e}")

        # Background: processar metadados (CATMAT + termos) para produtos
        if table_slug == "produtos":
            try:
                import threading
                from tools import processar_metadados_produto
                _pid = instance.id
                def _run_metadados_bg(pid=_pid):
                    try:
                        processar_metadados_produto(pid)
                        print(f"[CRUD] Metadados background concluido para {pid}")
                    except Exception as ex:
                        print(f"[CRUD] Erro no thread metadados {pid}: {ex}")
                threading.Thread(target=_run_metadados_bg, daemon=True, name=f"metadados-{_pid}").start()
            except Exception as e:
                print(f"[CRUD] Erro ao iniciar metadados background: {e}")

        # CV13-9 (Arnaldo Sprint 2 V8): auto-baixar PDF do edital quando salvo
        # com dados PNCP. Antes, 85% dos editais entravam sem PDF e a IA do
        # UC-CV13 nao tinha texto para responder Q&A / requisitos / classificar.
        if table_slug == "editais":
            try:
                cnpj = getattr(instance, "cnpj_orgao", None)
                ano = getattr(instance, "ano_compra", None)
                seq = getattr(instance, "seq_compra", None)
                if cnpj and ano and seq:
                    import threading
                    from tools import download_pdf_edital_bg
                    _eid = instance.id
                    _uid = user_id
                    def _run_pdf_bg(eid=_eid, uid=_uid):
                        try:
                            download_pdf_edital_bg(eid, uid)
                        except Exception as ex:
                            print(f"[CRUD] Erro no thread pdf-edital {eid}: {ex}")
                    threading.Thread(target=_run_pdf_bg, daemon=True, name=f"pdf-edital-{_eid}").start()
                    print(f"[CRUD] Auto-download PDF agendado para edital {_eid}")
            except Exception as e:
                print(f"[CRUD] Erro ao iniciar download PDF background: {e}")

        result = instance.to_dict()
        # Add password info for users
        if password_field and hasattr(instance, "password_hash"):
            result["has_password"] = bool(instance.password_hash)
            result["password"] = instance.password_plain if hasattr(instance, "password_plain") else ""

        # Mask encrypted fields in response
        for enc_field in config.get("encrypt_fields", []):
            if result.get(enc_field):
                result[enc_field] = "••••••••"

        return jsonify(result), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": _friendly_error(e, table_slug)}), 400
    finally:
        db.close()


@crud_bp.route("/api/crud/<table_slug>/<record_id>", methods=["PUT", "PATCH"])
@require_auth
def crud_update(table_slug, record_id):
    """Update a record."""
    config = CRUD_TABLES.get(table_slug)
    if not config:
        return jsonify({"error": f"Tabela '{table_slug}' não encontrada"}), 404

    if config.get("read_only"):
        return jsonify({"error": f"{config['label']} é somente leitura"}), 403

    _is_super = getattr(request, 'is_super', False)
    _is_admin = _is_super or getattr(request, 'papel', None) == 'admin'
    if table_slug in SUPER_WRITE_TABLES and not _is_super:
        return jsonify({"error": "Apenas superusuários podem criar/editar esta tabela"}), 403
    if table_slug in ADMIN_WRITE_TABLES and not _is_admin:
        return jsonify({"error": "Apenas administradores podem criar/editar este recurso"}), 403

    model = config["model"]
    user_id = get_current_user_id()
    is_super = getattr(request, 'is_super', False)
    is_admin = is_super or getattr(request, 'papel', None) == 'admin'
    data = request.json or {}

    # RN validators (Secao 13 requisitos_completosv8.md)
    try:
        _validar_rns_payload(table_slug, data)
    except RNValidationError as e:
        return jsonify({"error": str(e), "rn_code": e.rn_code}), 400

    db = get_db()

    # RN validators DB-aware (RN-207, RN-209)
    try:
        _validar_rns_db(table_slug, data, db)
    except RNValidationError as e:
        return jsonify({"error": str(e), "rn_code": e.rn_code}), 400

    # RN-086: invalidar scores quando pesos mudam
    if table_slug == "parametros-score":
        try:
            from rn_deepseek import invalidar_scores_empresa
            _emp_id = data.get("empresa_id") or get_current_empresa_id()
            if _emp_id:
                _n = invalidar_scores_empresa(db, _emp_id)
                print(f"[RN-086] {_n} editais marcados como score_stale para empresa {_emp_id}")
        except Exception as _e:
            print(f"[RN-086] erro: {_e}")

    try:
        query = db.query(model).filter(model.id == record_id)
        empresa_id = get_current_empresa_id()
        if config.get("empresa_scoped") and hasattr(model, "empresa_id") and empresa_id:
            if config.get("include_globais"):
                # Permite buscar global pra UPDATE, mas só admin pode salvar (verificado abaixo)
                from sqlalchemy import or_ as _or_
                query = query.filter(_or_(
                    model.empresa_id == empresa_id,
                    model.empresa_id.is_(None),
                ))
            else:
                query = query.filter(model.empresa_id == empresa_id)
        elif config.get("user_scoped") and hasattr(model, "user_id") and not is_admin:
            query = query.filter(model.user_id == user_id)

        instance = query.first()
        if not instance:
            return jsonify({"error": f"{config['label']} não encontrado(a)"}), 404

        # Bloqueia edicao de registros GLOBAIS (empresa_id IS NULL) por user nao-admin
        if config.get("include_globais") and getattr(instance, "empresa_id", None) is None:
            if not is_super:
                return jsonify({
                    "error": f"Esta {config['label']} é do catálogo do sistema (compartilhada). Só superusuários podem editá-la. Para usar uma versão personalizada, crie uma nova fonte com seus próprios dados."
                }), 403

        # RN-037: capturar snapshot "antes" para audit log (best-effort)
        _dados_antes_audit = None
        try:
            if hasattr(instance, "to_dict"):
                _dados_antes_audit = instance.to_dict()
        except Exception:
            _dados_antes_audit = None

        # RN-034/082/205: validar transicao de estado (se aplicavel)
        try:
            from rn_estados import check_transicao_update, TransicaoInvalida
            check_transicao_update(table_slug, instance, data)
        except TransicaoInvalida as _te:
            return jsonify({"error": str(_te), "rn_code": _te.rn_code}), 400

        # Update fields
        skip_fields = {"id", "created_at", "user_id"}
        password_field = config.get("password_field")
        for col in model.__table__.columns:
            if col.name in skip_fields:
                continue
            if col.name == "password_hash" and password_field:
                continue  # handled below
            if col.name == "password_plain" and password_field:
                continue  # handled below
            if col.name in data:
                _set_column_value(instance, col.name, data[col.name], model)

        # Hash password if provided (non-empty)
        if password_field and data.get(password_field) and hasattr(model, "password_hash"):
            plain = data[password_field]
            hashed = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            instance.password_hash = hashed
            if hasattr(model, "password_plain"):
                instance.password_plain = plain

        # Encrypt fields (Fernet reversible encryption)
        for enc_field in config.get("encrypt_fields", []):
            if enc_field in data:
                val = data[enc_field]
                if val and isinstance(val, str) and val.strip() and val != "••••••••":
                    from crypto_utils import encrypt_password
                    setattr(instance, enc_field, encrypt_password(val))
                elif not val or val.strip() == "":
                    setattr(instance, enc_field, None)
                # Se val == "••••••••", não altera (mantém o valor existente)

        db.commit()
        db.refresh(instance)

        # RN-037: audit log universal para update (best-effort)
        try:
            _AUDITED_TABLES = {
                "empresas", "produtos", "editais", "propostas", "contratos",
                "contrato-aditivos", "contrato-designacoes", "empresa-responsaveis",
                "impugnacoes", "recursos-detalhados",
                "estrategias-editais",  # RN-080: versionamento GO/NO-GO
            }
            if table_slug in _AUDITED_TABLES:
                _rn_log_transicao(
                    entidade=table_slug,
                    entidade_id=str(record_id),
                    acao="update",
                    dados_antes=_dados_antes_audit,
                    dados_depois=instance.to_dict() if hasattr(instance, "to_dict") else None,
                    user_id=user_id,
                )
        except Exception as _audit_e:
            print(f"[RN-037] log_transicao update error: {_audit_e}")

        result = instance.to_dict()
        if password_field and hasattr(instance, "password_hash"):
            result["has_password"] = bool(instance.password_hash)
            result["password"] = instance.password_plain if hasattr(instance, "password_plain") else ""

        # Mask encrypted fields in response
        for enc_field in config.get("encrypt_fields", []):
            if result.get(enc_field):
                result[enc_field] = "••••••••"

        return jsonify(result)
    except Exception as e:
        db.rollback()
        return jsonify({"error": _friendly_error(e, table_slug)}), 400
    finally:
        db.close()


@crud_bp.route("/api/crud/<table_slug>/<record_id>", methods=["DELETE"])
@require_auth
def crud_delete(table_slug, record_id):
    """Delete a record."""
    config = CRUD_TABLES.get(table_slug)
    if not config:
        return jsonify({"error": f"Tabela '{table_slug}' não encontrada"}), 404

    if config.get("read_only"):
        return jsonify({"error": f"{config['label']} é somente leitura"}), 403

    _is_super = getattr(request, 'is_super', False)
    _is_admin = _is_super or getattr(request, 'papel', None) == 'admin'
    if table_slug in SUPER_WRITE_TABLES and not _is_super:
        return jsonify({"error": "Apenas superusuários podem criar/editar esta tabela"}), 403
    if table_slug in ADMIN_WRITE_TABLES and not _is_admin:
        return jsonify({"error": "Apenas administradores podem criar/editar este recurso"}), 403

    model = config["model"]
    user_id = get_current_user_id()
    is_super = getattr(request, 'is_super', False)
    is_admin = is_super or getattr(request, 'papel', None) == 'admin'

    db = get_db()
    try:
        query = db.query(model).filter(model.id == record_id)
        empresa_id = get_current_empresa_id()
        if config.get("empresa_scoped") and hasattr(model, "empresa_id") and empresa_id:
            if config.get("include_globais"):
                from sqlalchemy import or_ as _or_
                query = query.filter(_or_(
                    model.empresa_id == empresa_id,
                    model.empresa_id.is_(None),
                ))
            else:
                query = query.filter(model.empresa_id == empresa_id)
        elif config.get("user_scoped") and hasattr(model, "user_id") and not is_admin:
            query = query.filter(model.user_id == user_id)

        instance = query.first()
        if not instance:
            return jsonify({"error": f"{config['label']} não encontrado(a)"}), 404

        # Bloqueia DELETE de registros GLOBAIS por user nao-admin
        if config.get("include_globais") and getattr(instance, "empresa_id", None) is None:
            if not is_super:
                return jsonify({
                    "error": f"Esta {config['label']} é do catálogo do sistema (compartilhada). Só superusuários podem excluí-la."
                }), 403

        db.delete(instance)
        db.commit()

        return jsonify({"message": f"{config['label']} excluído(a) com sucesso"})
    except Exception as e:
        db.rollback()
        return jsonify({"error": _friendly_error(e, table_slug)}), 400
    finally:
        db.close()
