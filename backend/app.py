"""
Agente de Editais - Backend Flask
MVP com 9 ações via Select + Prompt
"""
import os
import json
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS

from models import (
    init_db, get_db, User, Session, Message, RefreshToken, Produto, ProdutoEspecificacao,
    Edital, Analise, Proposta, FonteEdital, Contrato, EstrategiaEdital, Monitoramento,
    ModalidadeLicitacao, OrigemOrgao, AreaProduto, ClasseProdutoV2, SubclasseProduto,
    Empresa, PropostaLog, PropostaTemplate, AnvisaValidacao, ProdutoDocumento,
    UsuarioEmpresa,
    # Sprint 4: Recursos e Impugnações
    Impugnacao, RecursoDetalhado, RecursoTemplate, MonitoramentoJanela, ValidacaoLegal,
    # Sprint 5: Pós-Licitação
    ContratoAditivo, ContratoDesignacao, AtividadeFiscal,
    ARPSaldo, SolicitacaoCarona, AlertaVencimentoRegra,
    ContratoEntrega, AtaConsultada,
    SessaoPregao,
)
from llm import call_deepseek
from tools import (
    _web_search, tool_web_search, tool_download_arquivo, tool_processar_upload,
    tool_extrair_especificacoes, tool_cadastrar_fonte, tool_listar_fontes,
    tool_buscar_editais_fonte, tool_buscar_editais_scraper, tool_extrair_requisitos,
    tool_listar_editais, tool_listar_produtos, tool_calcular_aderencia, tool_gerar_proposta,
    tool_calcular_score_aderencia, tool_salvar_editais_selecionados,
    tool_reprocessar_produto, tool_atualizar_produto,
    tool_buscar_links_editais,
    execute_tool, _extrair_info_produto, PROMPT_EXTRAIR_SPECS,
    tool_calcular_scores_validacao, tool_atualizar_status_proposta,
    tool_verificar_anvisa_proposta, tool_auditoria_documental, tool_smart_split_pdf,
    # Sprint 4: Recursos e Impugnações
    tool_validacao_legal_edital, tool_gerar_peticao_impugnacao,
    tool_analisar_proposta_vencedora, tool_gerar_laudo_recurso,
    # Sprint 5: Pós-Licitação
    tool_calcular_score_logistico, tool_registrar_resultado_api,
    tool_dashboard_contratado_realizado, tool_alertas_vencimento_multi_tier,
    tool_buscar_atas_pncp, tool_baixar_ata_pncp, tool_extrair_ata_pdf,
)
from config import UPLOAD_FOLDER, MAX_HISTORY_MESSAGES

import bcrypt
import jwt
import uuid
from datetime import datetime, timedelta
from functools import wraps

# RN validators (Secao 13 de requisitos_completosv8.md)
# Feature flag default False — wire presente mas dormente ate ENFORCE_RN_VALIDATORS=true
from rn_validators import (
    validar_cnpj, validar_cpf, validar_ncm, validar_email, validar_uf,
    validar_quantidade, validar_lance_d_maior_e, validar_entrega_dentro_saldo,
    validar_gestor_diferente_fiscal, validar_aditivo_cumulativo,
    RNValidationError, check as rn_check,
)
ENFORCE_RN_VALIDATORS = os.environ.get("ENFORCE_RN_VALIDATORS", "false").lower() == "true"

def _arquivo_eh_pdf_valido(filepath: str) -> bool:
    """F04-07: Verifica se um arquivo no disco eh PDF de verdade (magic bytes %PDF).

    Scrapers de certidao podem retornar HTML de erro/login com extensao .pdf.
    Sem essa validacao, o sistema "pensa" que tem o PDF mas o user vai abrir e
    encontrar conteudo aleatorio (caso F04-07 reportado pelo Arnaldo na SEFAZ-MG).
    """
    try:
        if not filepath or not os.path.exists(filepath):
            return False
        with open(filepath, 'rb') as f:
            return f.read(4) == b'%PDF'
    except Exception:
        return False


def rn_enforce(rn_code: str, condition: bool, message: str):
    """Aplica validador de RN apenas se ENFORCE_RN_VALIDATORS=true. Caso contrario, loga warning."""
    if not condition:
        if ENFORCE_RN_VALIDATORS:
            raise RNValidationError(rn_code, message)
        else:
            print(f"[RN-WARN {rn_code}] {message}")

app = Flask(__name__)
# CORS: lê origins de env var. Default cobre dev local.
# Para acesso externo (IP público, ngrok, domínio), set CORS_ORIGINS="http://5.6.7.8:5180,https://abc.ngrok.io"
# Use "*" para aceitar qualquer origin (apenas em ambientes de desenvolvimento).
import os as _os_cors
_cors_origins_env = _os_cors.getenv("CORS_ORIGINS", "")
if _cors_origins_env.strip() == "*":
    CORS(app, origins="*")
elif _cors_origins_env.strip():
    CORS(app, origins=[o.strip() for o in _cors_origins_env.split(",") if o.strip()])
else:
    CORS(app, origins=[
        "http://localhost:5173", "http://localhost:5174", "http://localhost:5175",
        "http://localhost:5180", "http://127.0.0.1:5180",
        "http://localhost:3000",
    ])

# Registrar blueprint CRUD genérico
from crud_routes import crud_bp
app.register_blueprint(crud_bp)

# Sprint 5 V3 — Blueprints de Empenhos e CRM
from empenho_routes import empenho_bp
app.register_blueprint(empenho_bp)
from crm_routes import crm_bp
app.register_blueprint(crm_bp)

# Fase 2 — Inteligência Comercial (RF-CLA, RF-SCO-002/003, RF-PRE)
from inteligencia_comercial import intel_bp
app.register_blueprint(intel_bp)

# Fase 2 — Alertas de Pregão (RF-ALE-001/002: agenda regressiva + ICS)
from alertas_pregao import alertas_bp
app.register_blueprint(alertas_bp)

# Sprint 6 — Audit middleware
from audit_middleware import register_audit_hooks
register_audit_hooks(app)

# Sprint 9/10 — Simulador de Pregao Eletronico (LangNet + DeepSeek)
import sys as _sys_pregao
from pathlib import Path as _Path_pregao
_sys_pregao.path.insert(0, str(_Path_pregao(__file__).resolve().parent / "pregao"))
_sys_pregao.path.insert(0, str(_Path_pregao(__file__).resolve().parent / "langnet"))
from pregao.api_simulador import register_simulador_routes
register_simulador_routes(app)

# JWT Config
JWT_SECRET = "editais-ia-secret-key-change-in-production-2024"
JWT_EXPIRY_HOURS = 24

# Prompts prontos para o dropdown
PROMPTS_PRONTOS = [
    # === CONSULTAS ANALÍTICAS (MindsDB) ===
    {"id": "mindsdb_totais", "nome": "📊 Totais (produtos/editais)", "prompt": "Quantos produtos e editais existem no banco?"},
    {"id": "mindsdb_editais_novos", "nome": "📊 Editais com status novo", "prompt": "Quais editais estão com status novo?"},
    {"id": "mindsdb_editais_orgao", "nome": "📊 Editais por órgão", "prompt": "Liste editais do Ministério da Saúde"},
    {"id": "mindsdb_editais_mes", "nome": "📊 Editais do mês", "prompt": "Quais editais têm data de abertura em fevereiro de 2026?"},
    {"id": "mindsdb_score_medio", "nome": "📊 Score médio de aderência", "prompt": "Qual é o score médio de aderência das análises?"},
    {"id": "mindsdb_produtos_categoria", "nome": "📊 Produtos por categoria", "prompt": "Quantos produtos temos em cada categoria?"},
    {"id": "mindsdb_alta_aderencia", "nome": "📊 Produtos c/ alta aderência", "prompt": "Quais produtos têm aderência acima de 70% em algum edital?"},
    {"id": "mindsdb_propostas", "nome": "📊 Total de propostas", "prompt": "Quantas propostas foram geradas?"},
    {"id": "mindsdb_editais_semana", "nome": "📊 Editais da semana", "prompt": "Quais editais vencem esta semana?"},
    {"id": "mindsdb_melhor_produto", "nome": "📊 Produto c/ melhor score", "prompt": "Qual produto tem o melhor score de aderência?"},
    {"id": "mindsdb_editais_uf", "nome": "📊 Editais por UF", "prompt": "Quantos editais temos por estado (UF)?"},
    {"id": "mindsdb_resumo", "nome": "📊 Resumo geral do banco", "prompt": "Faça um resumo do banco: total de produtos, editais, análises e propostas"},
    # === AÇÕES DO SISTEMA ===
    {"id": "listar_produtos", "nome": "Listar meus produtos", "prompt": "Liste todos os meus produtos cadastrados"},
    {"id": "listar_editais", "nome": "Listar editais abertos", "prompt": "Quais editais estão abertos?"},
    {"id": "calcular_aderencia", "nome": "Calcular aderência", "prompt": "Calcule a aderência do produto [NOME_PRODUTO] ao edital [NUMERO_EDITAL]"},
    {"id": "gerar_proposta", "nome": "Gerar proposta", "prompt": "Gere uma proposta do produto [NOME_PRODUTO] para o edital [NUMERO_EDITAL] com preço R$ [VALOR]"},
    {"id": "buscar_editais", "nome": "Buscar editais", "prompt": "Busque editais de [TERMO] no PNCP"},
    {"id": "cadastrar_fonte", "nome": "Cadastrar fonte", "prompt": "Cadastre a fonte [NOME], tipo [api/scraper], URL [URL]"},
    {"id": "listar_fontes", "nome": "Listar fontes", "prompt": "Quais são as fontes de editais cadastradas?"},
    {"id": "ajuda", "nome": "O que posso fazer?", "prompt": "O que você pode fazer? Quais são suas capacidades?"},
    # === REGISTRO DE RESULTADOS (Sprint 1) ===
    {"id": "registrar_derrota", "nome": "📉 Registrar derrota", "prompt": "Perdemos o edital [NUMERO] para [EMPRESA] com R$ [VALOR_VENCEDOR], nosso preço foi R$ [NOSSO_VALOR]"},
    {"id": "registrar_vitoria", "nome": "🏆 Registrar vitória", "prompt": "Ganhamos o edital [NUMERO] com R$ [VALOR]"},
    {"id": "registrar_cancelado", "nome": "⛔ Edital cancelado", "prompt": "O edital [NUMERO] foi cancelado"},
    {"id": "consultar_resultado", "nome": "🔎 Consultar resultado", "prompt": "Qual o resultado do edital [NUMERO]?"},
    # === BUSCA COM FILTROS ===
    {"id": "buscar_modalidade", "nome": "🔍 Buscar por modalidade", "prompt": "Busque editais de [TERMO] com modalidade [MODALIDADE]"},
    {"id": "buscar_tipo_produto", "nome": "🔍 Buscar por tipo produto", "prompt": "Busque editais de [TERMO] do tipo [TIPO_PRODUTO]"},
    {"id": "buscar_origem", "nome": "🔍 Buscar por origem", "prompt": "Busque editais de [TERMO] de origem [ORIGEM]"},
    {"id": "buscar_filtros", "nome": "🔍 Buscar com filtros", "prompt": "Busque editais de [TERMO] em [UF], modalidade [MODALIDADE], origem [ORIGEM]"},
    # === BUSCA WEB E ANVISA ===
    {"id": "buscar_anvisa", "nome": "🛡️ Buscar registro ANVISA", "prompt": "Busque registros ANVISA para o produto [NOME_PRODUTO]"},
    {"id": "buscar_web_manual", "nome": "🌐 Buscar manual na web", "prompt": "Busque o manual do produto [NOME_PRODUTO] na web e cadastre"},
]


PROMPT_CLASSIFICAR_INTENCAO = """Você é um agente classificador de intenções para um sistema de gestão de editais e licitações.

Analise a mensagem do usuário e classifique em UMA das categorias abaixo:

## CATEGORIAS DO SISTEMA:

### AÇÕES COM ARQUIVOS (quando usuário envia um PDF/documento):
1. **arquivo_cadastrar**: Cadastrar o arquivo como produto no sistema (PADRÃO se não especificar outra ação)
   Exemplos: "cadastre", "salve como produto", "registre", "" (vazio), "cadastre como Analisador X"

2. **arquivo_mostrar**: Mostrar/exibir o conteúdo do arquivo
   Exemplos: "mostre o conteúdo", "exiba o texto", "o que tem nesse PDF?", "leia o documento", "mostra"

3. **arquivo_specs**: Extrair e listar especificações técnicas (sem cadastrar)
   Exemplos: "quais especificações?", "extraia as specs", "liste as características técnicas"

4. **arquivo_resumir**: Fazer um resumo do documento
   Exemplos: "resuma", "faça um resumo", "sintetize", "resuma o documento"

5. **arquivo_analisar**: Fazer análise detalhada do documento
   Exemplos: "analise", "faça uma análise", "avalie o documento", "o que você acha desse manual?"

6. **extrair_ata**: Extrair resultados de uma ata de sessão de pregão/licitação
   Exemplos: "extraia os resultados desta ata", "quem ganhou este pregão?", "registre os resultados da ata", "extraia vencedores", "resultado da licitação"
   Palavras-chave: ata, resultados da ata, vencedor do pregão, extrair resultados, ata de sessão
   IMPORTANTE: Use quando o arquivo é uma ATA de sessão (não um manual de produto)

### AÇÕES DE BUSCA:
7. **buscar_web**: Buscar MATERIAIS/MANUAIS/DATASHEETS na WEB (não editais!)
   Exemplos: "busque na web o manual do equipamento X", "encontre o datasheet do Y"

8. **download_url**: Baixar arquivo de uma URL específica
   Exemplos: "baixe o arquivo da URL: http://...", "baixe https://..."
   IMPORTANTE: Se contém URL (http:// ou https://), classifique como download_url!

9. **buscar_editais**: Buscar EDITAIS/LICITAÇÕES em portais (PNCP, BEC) por TERMO/ÁREA COM cálculo de score de aderência
   Exemplos: "busque editais de tecnologia", "editais da área médica", "busque editais de hematologia"
   Também cobre score rápido, híbrido e profundo: "busque editais de hematologia com score rápido", "busque editais com score profundo nos 5 melhores", "busque editais com score híbrido", "busque editais com análise profunda dos 10 melhores"
   IMPORTANTE: Use quando buscar por TERMO genérico (área, categoria, produto) E calcular score de aderência (qualquer tipo de score: rápido, híbrido ou profundo)

9b. **buscar_editais_simples**: Buscar EDITAIS SEM calcular score - apenas listar os editais encontrados
   Exemplos: "busque editais de tecnologia sem score", "liste editais de hematologia sem calcular aderência", "busque editais de informática apenas listando"
   Palavras-chave: sem score, sem calcular, sem aderência, apenas listar, só listar, listar editais
   IMPORTANTE: Use quando o usuário quer apenas ver os editais sem NENHUMA análise de aderência

10. **buscar_edital_numero**: Buscar UM edital específico pelo NÚMERO
   Exemplos: "busque o edital PE-001/2026", "encontre o edital 90186", "busque edital número 123/2025"
   Palavras-chave: busque o edital, encontre o edital, buscar edital número, edital PE-, edital nº
   IMPORTANTE: Use quando o usuário menciona um NÚMERO específico de edital

### AÇÕES DE LISTAGEM:
9. **listar_editais**: Ver editais JÁ SALVOS no sistema
   Exemplos: "liste meus editais", "editais salvos"

10. **listar_produtos**: Ver produtos cadastrados
    Exemplos: "liste meus produtos", "quais produtos tenho"

11. **listar_fontes**: Ver fontes de editais cadastradas
    Exemplos: "quais fontes?", "liste fontes"

12. **listar_propostas**: Ver propostas técnicas geradas
    Exemplos: "liste minhas propostas", "quais propostas tenho", "propostas geradas", "ver propostas"

### AÇÕES DE PROCESSAMENTO:
13. **calcular_aderencia**: Calcular score produto vs edital
    Exemplos: "calcule aderência do produto X com edital Y"

14. **gerar_proposta**: Gerar proposta técnica
    Exemplos: "gere proposta para o edital X"

15. **cadastrar_fonte**: Cadastrar nova fonte de editais
    Exemplos: "cadastre a fonte BEC-SP"

16. **salvar_editais**: Salvar editais da última busca (um específico ou todos)
    Exemplos: "salve os editais", "salvar recomendados", "salvar todos", "salvar edital 02223/2025", "salvar edital PE-001/2026"
    IMPORTANTE: Use quando o usuário quer SALVAR editais que vieram de uma BUSCA anterior. Diferente de cadastrar_edital que é para criar um edital MANUALMENTE com dados informados.

17. **reprocessar_produto**: Reprocessar/atualizar especificações de um produto
    Exemplos: "reprocesse o produto X", "atualize specs do produto X", "extraia novamente as especificações"

18. **consulta_mindsdb**: Consultas analíticas complexas sobre editais e produtos via linguagem natural
    Exemplos: "qual o score médio de aderência?", "quantos editais por estado?", "qual produto tem melhor desempenho?", "estatísticas dos editais", "análise dos dados", "relatório de editais"
    Use quando: perguntas analíticas, estatísticas, agregações, comparações, rankings, tendências

19. **registrar_resultado**: Registrar resultado de certame (vitória ou derrota) - AFIRMAÇÕES
    Exemplos: "perdemos o edital PE-001", "ganhamos o pregão", "vencedor foi empresa X com R$ 100k", "registre derrota no PE-002", "perdemos por preço para MedLab"
    Palavras-chave: perdemos, ganhamos, vencedor, derrota, vitória, segundo lugar
    IMPORTANTE: Use apenas quando o usuário está AFIRMANDO um resultado, não perguntando.

20. **consultar_resultado**: Consultar/perguntar sobre resultado de certames - PERGUNTAS
    Exemplos: "qual o resultado do edital PE-001?", "quem ganhou o pregão?", "como foi o edital?", "mostre os resultados de todos os editais", "ver resultados dos editais", "listar resultados", "resultados dos certames"
    Palavras-chave: qual o resultado, quem ganhou, quem venceu, como foi, resultados de todos, ver resultados, listar resultados
    IMPORTANTE: Use quando o usuário está PERGUNTANDO sobre resultados (um edital ou todos).

21. **buscar_atas_pncp**: Buscar atas de sessão/registro de preço no PNCP para download
    Exemplos: "busque atas de hematologia", "encontre atas de pregão de equipamentos", "baixe atas de registro de preço", "atas de sessão de pregão"
    Palavras-chave: buscar atas, encontrar atas, baixar atas, atas de registro, atas de sessão, atas pncp
    IMPORTANTE: Use quando o usuário quer BUSCAR atas no portal PNCP (não quando já tem um arquivo)

22. **buscar_precos_pncp**: Buscar preços históricos de contratos no PNCP
    Exemplos: "busque preços de hematologia", "qual o preço de mercado para analisador?", "preços de contratos de equipamentos", "quanto custa um equipamento X no PNCP?"
    Palavras-chave: buscar preços, preço de mercado, preços pncp, quanto custa, preço médio, valores de contrato
    Use quando: usuário quer saber preços praticados em licitações anteriores

23. **historico_precos**: Consultar histórico de preços registrados no sistema
    Exemplos: "mostre histórico de preços de hematologia", "histórico de preços do produto X", "quais preços já registramos?"
    Palavras-chave: histórico de preços, preços registrados, preços salvos, histórico preço

24. **listar_concorrentes**: Listar todos os concorrentes conhecidos
    Exemplos: "liste os concorrentes", "quais concorrentes conhecemos?", "mostre os concorrentes"
    Palavras-chave: listar concorrentes, concorrentes conhecidos, nossos concorrentes

25. **analisar_concorrente**: Analisar um concorrente específico
    Exemplos: "analise o concorrente MedLab", "como está a empresa TechSaúde?", "histórico do concorrente X"
    Palavras-chave: analisar concorrente, análise concorrente, histórico concorrente

26. **recomendar_preco**: Recomendar preço para um produto/edital
    Exemplos: "qual preço sugerir para hematologia?", "recomende preço para analisador", "que preço colocar?"
    Palavras-chave: recomendar preço, sugerir preço, que preço, qual preço colocar

27. **classificar_edital**: Classificar tipo de edital (comodato, venda, aluguel)
    Exemplos: "classifique este edital", "que tipo de edital é este?", "é comodato ou venda?"
    Palavras-chave: classificar edital, tipo de edital, qual modalidade, é comodato

28. **verificar_completude**: Verificar se produto tem todas informações necessárias
    Exemplos: "produto X está completo?", "verifique completude do produto", "falta algo no produto?"
    Palavras-chave: verificar completude, produto completo, falta informação, completude produto

29. **cadastrar_edital**: Cadastrar/registrar manualmente um edital no sistema COM DADOS INFORMADOS PELO USUÁRIO
    Exemplos: "cadastre o edital PE-001/2026, órgão Ministério da Saúde, objeto: aquisição de equipamentos", "registre este edital com os dados...", "adicione o edital número X do órgão Y"
    Palavras-chave: cadastre edital, registre edital, adicione edital, cadastrar edital manualmente, inserir edital
    IMPORTANTE: Use APENAS quando o usuário quer CRIAR um edital MANUALMENTE informando dados (órgão, objeto, etc).
    NÃO USE para "salvar edital NUMERO" que veio de uma busca - isso é salvar_editais!

### SPRINT 2 - ALERTAS E MONITORAMENTO:
30. **configurar_alertas**: Configurar alertas de prazo para um edital
    Exemplos: "configure alertas para PE-001", "avise-me 24h antes da abertura", "quero alerta de impugnação"
    Palavras-chave: configurar alerta, avise-me, lembre-me, alertar antes, alertas para edital

31. **listar_alertas**: Ver alertas configurados / próximos pregões
    Exemplos: "quais alertas tenho?", "meus alertas", "próximos pregões", "alertas configurados"
    Palavras-chave: listar alertas, meus alertas, alertas configurados, próximos pregões

32. **dashboard_prazos**: Ver dashboard de prazos e contagem regressiva
    Exemplos: "mostre dashboard de prazos", "quais editais abrem esta semana?", "timer dos editais"
    Palavras-chave: dashboard prazos, editais abrem, contagem regressiva, timer editais

33. **calendario_editais**: Ver calendário de editais
    Exemplos: "calendário de fevereiro", "calendário de editais", "editais do mês"
    Palavras-chave: calendário editais, calendário mês, ver calendário

34. **configurar_monitoramento**: Configurar monitoramento automático de editais
    Exemplos: "monitore editais de hematologia", "configure busca automática", "avise novos editais de X"
    Palavras-chave: monitorar editais, monitoramento automático, busca automática, avisar novos

35. **listar_monitoramentos**: Ver monitoramentos configurados
    Exemplos: "quais monitoramentos tenho?", "monitoramentos ativos", "ver minhas buscas automáticas"
    Palavras-chave: listar monitoramentos, monitoramentos ativos, minhas buscas

36. **desativar_monitoramento**: Desativar um monitoramento
    Exemplos: "desative monitoramento de hematologia", "pare de monitorar X", "cancele busca automática"
    Palavras-chave: desativar monitoramento, parar monitorar, cancelar busca

37. **configurar_notificacoes**: Configurar preferências de notificação
    Exemplos: "configure meu email de notificação", "quero alertas das 8h às 18h", "preferências de alerta"
    Palavras-chave: configurar notificação, email notificação, preferências alerta

38. **historico_notificacoes**: Ver histórico de notificações
    Exemplos: "histórico de notificações", "notificações não lidas", "ver notificações"
    Palavras-chave: histórico notificações, notificações não lidas, ver notificações

39. **extrair_datas_edital**: Extrair datas importantes de um edital (PDF)
    Exemplos: "extraia as datas deste edital", "quando abre o edital?", "prazo de impugnação"
    Palavras-chave: extrair datas, datas edital, quando abre, prazo impugnação

40. **cancelar_alerta**: Cancelar alertas configurados
    Exemplos: "cancele alertas do PE-001", "remova meus alertas", "desative alertas"
    Palavras-chave: cancelar alerta, remover alerta, desativar alerta

### FASE 2 — INTELIGÊNCIA COMERCIAL:
40b. **score_comercial**: Score de aderência comercial GO/NO-GO de um edital (logística, porte, histórico, prazo)
    Exemplos: "vale a pena participar do PE-001?", "score comercial do edital PE-123/2026", "GO ou NO-GO para o pregão 45/2026?"
    Palavras-chave: score comercial, vale a pena participar, go ou no-go, go/no-go, aderência comercial

### FASE 1 — PRECIFICAÇÃO:
41b. **precif_organizar_lotes**: Organizar itens do edital em lotes
    Exemplos: "organize os lotes do edital PE-001", "importe itens do PNCP e crie lotes", "crie lotes para o edital"
    Palavras-chave: organizar lotes, criar lotes, importar itens, lotes do edital

42b. **precif_selecao_portfolio**: Seleção inteligente de produto do portfolio para item do edital
    Exemplos: "selecione produto para o item 1", "qual produto atende o item?", "seleção inteligente de portfolio"
    Palavras-chave: selecionar produto, seleção portfolio, match produto item, vincular produto

43b. **precif_calcular_volumetria**: Calcular volumetria técnica (kits necessários)
    Exemplos: "calcule a volumetria", "quantos kits preciso?", "calcule kits para 50000 testes"
    Palavras-chave: calcular volumetria, quantos kits, volume ajustado, rendimento

44b. **precif_configurar_custos**: Configurar base de custos (Camada A)
    Exemplos: "configure os custos do item", "custo base do produto", "configure camada A de custos"
    Palavras-chave: configurar custos, custo base, camada A, base de custos, NCM, ICMS

45b. **precif_preco_base**: Montar preço base (Camada B)
    Exemplos: "defina preço base com markup 76%", "preço base manual R$ 150", "configure camada B"
    Palavras-chave: preço base, markup, camada B, montar preço

46b. **precif_valor_referencia**: Definir valor de referência/target (Camada C)
    Exemplos: "defina valor de referência", "target de preço", "configure camada C", "referência do edital"
    Palavras-chave: valor referência, target, camada C, referência edital

47b. **precif_estruturar_lances**: Estruturar lances — valor inicial e mínimo (Camadas D e E)
    Exemplos: "configure lances: inicial R$ 145, mínimo R$ 95", "estruture os lances", "defina faixa de disputa"
    Palavras-chave: estruturar lances, lance inicial, lance mínimo, faixa de disputa, camada D, camada E

48b. **precif_estrategia**: Definir estratégia competitiva e simular cenários
    Exemplos: "quero ganhar este edital", "simule estratégia competitiva", "estratégia agressiva"
    Palavras-chave: estratégia competitiva, quero ganhar, simular disputa, cenários

49b. **precif_historico_camada_f**: Consultar histórico de preços para Camada F
    Exemplos: "busque histórico de preços do produto", "consulte preços históricos", "camada F do item"
    Palavras-chave: histórico preços camada, camada F, preços passados

50b. **precif_comodato**: Gestão de comodato
    Exemplos: "cadastre comodato para o edital", "configure equipamento em comodato", "amortização do equipamento"
    Palavras-chave: comodato, amortização, equipamento comodato, gestão comodato

41. **chat_livre**: Dúvidas gerais, conversas
    Exemplos: "o que é pregão?", "olá", "obrigado"

### CADASTRO DE PRODUTOS:
47. **cadastrar_produto**: Cadastrar um produto manualmente com dados do formulário
    Exemplos: "cadastre manualmente o produto: Nome=...", "registre o produto X", "cadastre o produto Y"
    Palavras-chave: cadastre manualmente, cadastre o produto, registre o produto, criar produto

48. **buscar_anvisa**: Buscar registros de produtos na ANVISA
    Exemplos: "busque o registro ANVISA numero 12345", "busque registros ANVISA para o produto X", "consulte ANVISA do produto Y"
    Palavras-chave: anvisa, registro anvisa, buscar anvisa, consultar anvisa

### ANÁLISE DE EDITAIS:
42. **resumir_edital**: Fazer um resumo de um edital cadastrado
    Exemplos: "resuma o edital PE-001/2026", "faça um resumo do edital", "resumo do edital PE-001", "sintetize o edital"
    Palavras-chave: resumir edital, resumo do edital, sintetize edital, resumo edital
    IMPORTANTE: O usuário quer um resumo executivo do edital (objeto, valor, prazos, requisitos principais)

43. **perguntar_edital**: Responder dúvidas/perguntas sobre um edital específico
    Exemplos: "qual o prazo de entrega do edital PE-001?", "o edital PE-001 exige garantia?", "quais documentos são exigidos no PE-001?", "pergunte ao edital PE-001 sobre [DÚVIDA]"
    Palavras-chave: perguntar ao edital, dúvida sobre edital, o edital exige, o edital pede, prazo do edital, requisitos do edital
    IMPORTANTE: Use quando o usuário tem uma dúvida específica sobre um edital cadastrado

44. **baixar_pdf_edital**: Baixar o PDF de um edital já cadastrado (a partir da URL salva)
    Exemplos: "baixe o PDF do edital PE-001/2026", "faça download do edital PE-001", "baixar edital PE-001", "download do pdf do edital"
    Palavras-chave: baixar pdf edital, download edital, baixar edital, baixe o edital, download pdf edital
    IMPORTANTE: Use quando o usuário quer BAIXAR o arquivo PDF de um edital que já está cadastrado no sistema

45. **atualizar_url_edital**: Atualizar a URL de um edital cadastrado
    Exemplos: "atualize o edital PE-001 com URL: https://...", "mude a URL do edital PE-001 para https://...", "corrija a URL do edital PE-001", "atualize URL do edital"
    Palavras-chave: atualizar url, atualize edital com url, mude url, corrija url, atualizar link edital
    IMPORTANTE: Use quando o usuário quer ATUALIZAR/CORRIGIR a URL de download de um edital já cadastrado

46. **buscar_links_editais**: Retornar links de editais em uma área/categoria específica
    Exemplos: "retorne os links para os editais na área de hematologia", "links de editais de equipamentos médicos", "mostre links de editais de TI", "links para editais de laboratório"
    Palavras-chave: links de editais, links para editais, retorne os links, mostre links editais
    IMPORTANTE: Use quando o usuário quer VER LINKS clicáveis de editais, não calcular score

## CONTEXTO IMPORTANTE:
- **tem_arquivo**: {tem_arquivo} (true se usuário enviou um arquivo junto com a mensagem)
- Se tem_arquivo=true E mensagem vazia ou genérica → **arquivo_cadastrar**
- Se tem_arquivo=true E pede para mostrar/ler → **arquivo_mostrar**

## PARÂMETROS EXTRAS (extraia se mencionados):
- "termo_busca": termo de busca OTIMIZADO para APIs de licitação
- "nome_produto": nome do produto
- "url": URL completa se houver
- "produto": nome do produto para aderência/proposta
- "edital": número/identificador do edital
- "nome_fonte": nome da fonte de editais (ex: "ComprasNet", "BEC-SP")
- "tipo_fonte": tipo da fonte ("api" ou "scraper")

## IMPORTANTE - TERMO DE BUSCA:
Se a intenção for **buscar_editais** ou **buscar_editais_simples**, extraia o termo_busca da mensagem.
REGRA CRÍTICA: Use o termo EXATO que o usuário digitou. NÃO substitua, NÃO "otimize", NÃO troque por sinônimos.
REMOVA do termo_busca: palavras de comando (busque, editais, no, pncp), modificadores de busca (incluindo encerrados, sem calcular score, últimos X dias, sem score, apenas listando, com score rápido, com score profundo, com score híbrido, análise profunda, nos X melhores), nomes de fontes (PNCP, ComprasNet, BEC-SP, Licitacoes-e).
MANTENHA APENAS as palavras-chave do ASSUNTO/PRODUTO.
Exemplos:
- "busque editais de equipamento medico" → termo_busca: "equipamento medico"
- "busque editais de hematologia" → termo_busca: "hematologia"
- "busque editais de material hospitalar" → termo_busca: "material hospitalar"
- "busque editais de informática" → termo_busca: "informática"
- "busque editais de medicamentos incluindo encerrados sem calcular score" → termo_busca: "medicamentos"
- "busque editais de equipamento medico no PNCP últimos 60 dias" → termo_busca: "equipamento medico"
- "busque editais de medicamentos incluindo encerrados últimos 30 dias sem calcular score" → termo_busca: "medicamentos"
- "busque editais de reagentes com score profundo nos 5 melhores" → termo_busca: "reagentes"
- "busque editais de hematologia com score híbrido nos 10 melhores" → termo_busca: "hematologia"
- "busque editais de computadores com análise profunda" → termo_busca: "computadores"

## MENSAGEM DO USUÁRIO:
"{mensagem}"

## RESPOSTA:
Retorne APENAS um JSON:
{{"intencao": "<categoria>", "termo_busca": null, "nome_produto": null, "url": null, "produto": null, "edital": null}}"""


def detectar_intencao_ia(message: str, tem_arquivo: bool = False) -> dict:
    """
    Usa DeepSeek-chat para classificar a intenção do usuário.
    Retorna dict com 'intencao' e parâmetros extraídos.

    Args:
        message: Mensagem do usuário
        tem_arquivo: True se o usuário enviou um arquivo junto
    """
    import json
    import re

    prompt = PROMPT_CLASSIFICAR_INTENCAO.format(
        mensagem=message or "(mensagem vazia)",
        tem_arquivo="true" if tem_arquivo else "false"
    )

    try:
        resposta = call_deepseek(
            [{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0,  # obs 7 validador V8: classificação determinística
            model_override="deepseek-chat"  # Rápido para classificação
        )

        # Extrair JSON da resposta
        json_match = re.search(r'\{[\s\S]*?\}', resposta)
        if json_match:
            resultado = json.loads(json_match.group())
            print(f"[AGENTE] Intenção detectada: {resultado.get('intencao')} | Termo: {resultado.get('termo_busca')}")
            return resultado
    except Exception as e:
        print(f"[AGENTE] Erro na classificação: {e}")

    # Fallback para detecção por palavras-chave
    return {"intencao": detectar_intencao_fallback(message), "termo_busca": None}


def detectar_intencao_fallback(message: str) -> str:
    """Fallback: detecção por palavras-chave (usado se IA falhar)."""
    msg = message.lower()

    # 1. Buscar na WEB (manuais, datasheets) - ANTES de buscar editais!
    if any(p in msg for p in ["busque na web", "buscar na web", "pesquise na web", "datasheet", "manual do"]):
        return "buscar_web"
    if any(p in msg for p in ["especificações do", "especificacoes do"]) and "edital" not in msg:
        return "buscar_web"

    # 2. Upload de manual
    if any(p in msg for p in ["upload", "enviei", "arquivo que", "processe o manual", "processe o pdf"]):
        return "upload_manual"

    # 2.1 Extrair ata de sessão (ANTES de outras ações com arquivo)
    if any(p in msg for p in ["extraia os resultados", "extrair resultados", "resultados da ata",
                               "ata de sessão", "ata de sessao", "vencedor do pregão", "vencedor do pregao",
                               "quem ganhou o pregão", "quem ganhou o pregao", "extraia da ata",
                               "registre os resultados da ata", "resultado da licitação", "resultado da licitacao"]):
        return "extrair_ata"

    # 2.5. Download de URL - ANTES de outras ações
    if "http://" in msg or "https://" in msg:
        if any(p in msg for p in ["baixe", "baixar", "download", "faça download"]):
            return "download_url"
        # Se tem URL e fala de PDF/manual/arquivo, também é download
        if any(p in msg for p in [".pdf", "manual", "arquivo", "documento"]):
            return "download_url"

    # 3. Salvar editais (da busca)
    # Detecta: "salvar edital", "salvar editais", "salvar todos", "salvar recomendados"
    # Também detecta "salvar edital NUMERO" (quando tem número de edital)
    if any(p in msg for p in ["salvar edital", "salvar editais", "salvar todos", "salvar recomendados",
                               "guardar edital", "guardar editais"]):
        return "salvar_editais"
    # "salve" sozinho ou com número de edital
    if "salve" in msg and ("edital" in msg or "editais" in msg or re.search(r'\d{2,}[/]\d{4}', msg)):
        return "salvar_editais"

    # 4. Listar produtos
    if any(p in msg for p in ["meus produtos", "listar produtos", "produtos cadastrados", "ver produtos"]):
        return "listar_produtos"

    # 5. Listar editais salvos
    if any(p in msg for p in ["meus editais", "editais salvos", "editais cadastrados", "ver editais"]):
        return "listar_editais"

    # 5.1 Listar propostas
    if any(p in msg for p in ["minhas propostas", "listar propostas", "propostas geradas", "ver propostas", "propostas cadastradas"]):
        return "listar_propostas"

    # 5.2 Consultar resultado de certame (perguntas sobre resultado)
    # IMPORTANTE: Deve vir ANTES de buscar_editais para ter prioridade
    if any(p in msg for p in ["qual o resultado", "qual foi o resultado", "resultado do edital",
                               "resultado dos editais", "resultados dos editais", "resultado existente",
                               "resultados existentes", "busque o resultado", "buscar resultado",
                               "mostre os resultados", "ver resultados", "listar resultados",
                               "quem ganhou", "quem venceu", "como foi o edital",
                               "resultado do certame", "resultados dos certames"]):
        return "consultar_resultado"

    # 5.3 Registrar resultado de certame (afirmações de vitória/derrota)
    if any(p in msg for p in ["perdemos", "ganhamos", "vencedor foi", "vencedora foi",
                               "derrota", "vitória", "vitoria", "segundo lugar", "terceiro lugar",
                               "registre resultado", "registrar resultado", "perdemos o", "ganhamos o",
                               "foi cancelado", "ficou deserto", "foi revogado", "edital cancelado",
                               "edital deserto", "edital revogado"]):
        return "registrar_resultado"

    # 5.4 Buscar atas no PNCP
    if any(p in msg for p in ["buscar atas", "busque atas", "encontrar atas", "encontre atas",
                               "baixar atas", "baixe atas", "atas de registro", "atas de sessão",
                               "atas de sessao", "atas pncp", "atas do pncp"]):
        return "buscar_atas_pncp"

    # 5.4.1 Buscar preços no PNCP (Funcionalidade 4 Sprint 1)
    if any(p in msg for p in ["buscar preços", "busque preços", "buscar precos", "busque precos",
                               "preço de mercado", "preco de mercado", "preços pncp", "precos pncp",
                               "quanto custa", "preço médio", "preco medio", "valores de contrato",
                               "preços de contrato", "precos de contrato", "preço praticado",
                               "preco praticado", "preços praticados", "precos praticados"]):
        return "buscar_precos_pncp"

    # 5.4.2 Histórico de preços (Funcionalidade 5 Sprint 1)
    if any(p in msg for p in ["histórico de preços", "historico de precos", "preços registrados",
                               "precos registrados", "preços salvos", "precos salvos",
                               "histórico preço", "historico preco"]):
        return "historico_precos"

    # 5.4.3 Listar concorrentes (Funcionalidade 6 Sprint 1)
    if any(p in msg for p in ["listar concorrentes", "liste concorrentes", "concorrentes conhecidos",
                               "nossos concorrentes", "quais concorrentes", "ver concorrentes"]):
        return "listar_concorrentes"

    # 5.4.4 Analisar concorrente (Funcionalidade 6 Sprint 1)
    if any(p in msg for p in ["analisar concorrente", "analise concorrente", "análise concorrente",
                               "analise o concorrente", "histórico concorrente", "historico concorrente"]):
        return "analisar_concorrente"

    # FASE 2 — Score comercial GO/NO-GO (antes de recomendar_preco: "vale a pena" não é preço)
    if any(p in msg for p in ["score comercial", "vale a pena participar", "go ou no-go",
                               "go ou no go", "go/no-go", "go/no go",
                               "aderência comercial", "aderencia comercial"]):
        return "score_comercial"

    # 5.4.5 Recomendar preço (Funcionalidade 7 Sprint 1)
    if any(p in msg for p in ["recomendar preço", "recomendar preco", "sugerir preço", "sugerir preco",
                               "que preço colocar", "que preco colocar", "qual preço sugerir",
                               "qual preco sugerir", "recomende preço", "recomende preco"]):
        return "recomendar_preco"

    # 5.4.6 Classificar edital (Funcionalidade 8 Sprint 1)
    if any(p in msg for p in ["classificar edital", "classifique edital", "tipo de edital",
                               "que tipo de edital", "é comodato", "e comodato", "é venda",
                               "é aluguel", "qual modalidade"]):
        return "classificar_edital"

    # 5.4.7 Verificar completude produto (Funcionalidade 9 Sprint 1)
    if any(p in msg for p in ["verificar completude", "produto completo", "falta informação",
                               "falta informacao", "completude produto", "está completo",
                               "esta completo", "informações faltando"]):
        return "verificar_completude"

    # 5.4.8 Resumir edital
    if any(p in msg for p in ["resumir edital", "resuma o edital", "resumo do edital", "resuma edital",
                               "sintetize o edital", "sintetize edital", "resumo edital"]):
        return "resumir_edital"

    # 5.4.9 Perguntar ao edital
    if any(p in msg for p in ["perguntar ao edital", "pergunte ao edital", "dúvida sobre edital",
                               "duvida sobre edital", "o edital exige", "o edital pede",
                               "prazo do edital", "requisitos do edital", "no edital pe-",
                               "do edital pe-", "edital pe-"]) and "?" in msg:
        return "perguntar_edital"

    # 5.4.10 Baixar PDF do edital
    if any(p in msg for p in ["baixar pdf edital", "baixe o pdf do edital", "download do edital",
                               "baixar edital", "baixe o edital", "download pdf edital",
                               "faça download do edital", "baixe edital"]):
        return "baixar_pdf_edital"

    # 5.4.11 Atualizar URL do edital
    if any(p in msg for p in ["atualize o edital", "atualizar url", "atualize url", "mude a url",
                               "corrija a url", "corrija url", "atualizar link", "atualize link"]):
        if "url" in msg or "http" in msg:
            return "atualizar_url_edital"

    # 5.5 Reprocessar produto
    if any(p in msg for p in ["reprocess", "atualize specs", "atualizar specs", "extraia novamente"]):
        return "reprocessar_produto"

    # 5.6 Excluir edital
    if any(p in msg for p in ["excluir edital", "excluir editais", "deletar edital", "remover edital", "apagar edital"]):
        return "excluir_edital"

    # 5.7 Excluir produto
    if any(p in msg for p in ["excluir produto", "deletar produto", "remover produto", "apagar produto"]):
        return "excluir_produto"

    # 5.8 Atualizar/Editar edital
    if any(p in msg for p in ["editar edital", "atualizar edital", "modificar edital", "alterar edital"]):
        return "atualizar_edital"

    # 5.9 Atualizar/Editar produto
    if any(p in msg for p in ["editar produto", "atualizar produto", "modificar produto", "alterar produto"]):
        return "atualizar_produto"

    # 6. Calcular aderência
    if any(p in msg for p in ["aderência", "aderencia", "score", "compatível", "compatibilidade"]):
        return "calcular_aderencia"

    # 7. Gerar proposta
    if any(p in msg for p in ["proposta", "gerar proposta", "elaborar proposta"]):
        return "gerar_proposta"

    # 8. Fontes
    if any(p in msg for p in ["fonte"]):
        if any(p in msg for p in ["cadastr", "adicion", "nova fonte"]):
            return "cadastrar_fonte"
        return "listar_fontes"

    # 8.5 Cadastrar produto manualmente (via formulário do Portfolio)
    if any(p in msg for p in ["cadastre manualmente o produto", "cadastre o produto", "cadastrar produto",
                               "registre o produto", "criar produto", "crie o produto", "adicione o produto"]):
        return "cadastrar_produto"

    # 8.6 Buscar registros ANVISA
    if any(p in msg for p in ["anvisa", "registro anvisa", "busque anvisa", "consulte anvisa",
                               "buscar anvisa", "consultar anvisa", "registros anvisa"]):
        return "buscar_anvisa"

    # 9. Cadastrar edital manualmente - ANTES de buscar editais
    if any(p in msg for p in ["cadastre o edital", "cadastrar edital", "registre o edital", "adicione o edital", "inserir edital"]):
        return "cadastrar_edital"

    # 10. Detectar se é busca no BANCO ou na WEB
    # Palavras que indicam BANCO LOCAL: "no banco", "cadastrado", "salvo", "no sistema", "banco de dados"
    busca_local = any(p in msg for p in ["no banco", "cadastrado", "salvo", "no sistema", "banco de dados",
                                          "tenho o edital", "tenho edital", "já tenho", "ja tenho"])
    # Palavras que indicam WEB: "na web", "no pncp", "internet", "online", "portal"
    busca_web = any(p in msg for p in ["na web", "no pncp", "pncp", "internet", "online", "portal", "bec"])

    import re

    # 10.1 Buscar edital específico por número
    tem_numero_edital = re.search(r'(PE[-]?\d+|[Pp]reg[aã]o\s*n?[ºo°]?\s*\d+|\d{4,}[/]\d{4}|n[ºo°]\s*\d+)', msg, re.IGNORECASE)
    if any(p in msg for p in ["busque o edital", "encontre o edital", "buscar edital"]) or tem_numero_edital:
        # Sempre usa buscar_edital_numero - a função internamente decide banco/web
        return "buscar_edital_numero"

    # 10.2 Buscar editais por termo
    if any(p in msg for p in ["busque editais", "buscar editais", "encontre editais", "encontrar editais"]):
        if busca_local:
            return "listar_editais"  # Lista do banco
        # Verificar se quer sem score
        sem_score = any(p in msg for p in ["sem score", "sem calcular", "sem aderência", "sem aderencia",
                                            "apenas listar", "só listar", "so listar", "apenas liste",
                                            "só liste", "so liste", "sem análise", "sem analise"])
        if sem_score:
            return "buscar_editais_simples"  # Busca sem calcular score
        else:
            return "buscar_editais"  # Busca na web com score (padrão)

    # 10.3 Buscar produtos
    if any(p in msg for p in ["busque produto", "buscar produto", "encontre produto", "encontrar produto"]):
        if busca_web:
            return "buscar_web"  # Busca manual na web
        else:
            return "listar_produtos"  # Lista do banco (padrão)

    # 11. Consultas analíticas via MindsDB - ANTES de buscar_editais genérico!
    # Inclui consultas com filtros de status, agregações, estatísticas
    palavras_mindsdb = [
        "estatística", "estatistica", "score médio", "score medio", "média de", "media de",
        "quantos editais", "quantos produtos", "análise dos dados", "analise dos dados",
        "relatório", "relatorio", "ranking", "tendência", "tendencia", "comparar",
        "por estado", "por uf", "por categoria", "desempenho", "performance",
        # Consultas de status/resultado
        "status perdido", "status ganho", "status novo", "status cancelado",
        "resultado perdido", "resultado ganho", "editais perdidos", "editais ganhos",
        "editais com status", "editais que estão", "editais que estao",
        "quais editais têm", "quais editais tem", "liste editais com",
        # Agregações
        "total de", "soma de", "contagem de", "quantidade de"
    ]
    if any(p in msg for p in palavras_mindsdb):
        return "consulta_mindsdb"

    # 12. FALLBACK INTELIGENTE: Se parece ser consulta sobre dados do banco → MindsDB
    # Palavras que indicam que é uma pergunta sobre dados armazenados
    palavras_dados_banco = [
        # Entidades do banco
        "edital", "editais", "produto", "produtos", "proposta", "propostas",
        "análise", "analise", "análises", "analises", "ata", "atas",
        "resultado", "resultados", "fonte", "fontes", "concorrente", "concorrentes",
        # Verbos de consulta
        "liste", "listar", "mostre", "mostrar", "exiba", "exibir",
        "quais", "qual", "quantos", "quantas", "onde", "quando",
        # Filtros
        "com valor", "acima de", "abaixo de", "maior que", "menor que",
        "entre", "desde", "até", "depois de", "antes de",
        "do mês", "da semana", "do ano", "de hoje", "de ontem",
        "em são paulo", "em sp", "em minas", "em mg", "no rio",
        # Ordenação
        "ordenado", "ordenados", "mais recente", "mais antigo", "últimos", "ultimos"
    ]

    # Se contém palavras de dados E parece ser uma pergunta/consulta
    eh_pergunta = any(p in msg for p in ["?", "quais", "qual", "quantos", "quantas",
                                          "liste", "mostre", "exiba", "me diga", "me fale"])
    menciona_dados = any(p in msg for p in palavras_dados_banco)

    if menciona_dados and eh_pergunta:
        return "consulta_mindsdb"

    # =============================================================================
    # SPRINT 2: ALERTAS E AUTOMAÇÃO
    # =============================================================================

    # 13.1 Configurar alertas de prazo
    if any(p in msg for p in ["configurar alerta", "configure alerta", "criar alerta", "crie alerta",
                               "avise-me", "lembre-me antes", "alerta para o edital", "alertar sobre",
                               "quero ser avisado", "me avise quando", "notifique-me"]):
        return "configurar_alertas"

    # 13.2 Listar alertas
    if any(p in msg for p in ["meus alertas", "listar alertas", "alertas configurados", "ver alertas",
                               "quais alertas", "alertas ativos", "próximos pregões", "proximos pregoes"]):
        return "listar_alertas"

    # 13.3 Dashboard de prazos
    if any(p in msg for p in ["dashboard de prazo", "dashboard prazos", "contagem regressiva",
                               "prazos dos editais", "próximos prazos", "proximos prazos",
                               "ver prazos", "mostre os prazos", "quais prazos"]):
        return "dashboard_prazos"

    # 13.4 Calendário de editais
    if any(p in msg for p in ["calendário", "calendario", "calendário de editais", "calendario de editais",
                               "editais do mês", "editais do mes", "editais da semana", "agenda de editais",
                               "datas importantes", "próximas datas", "proximas datas"]):
        return "calendario_editais"

    # 13.5 Configurar monitoramento
    if any(p in msg for p in ["configurar monitoramento", "configure monitoramento", "criar monitoramento",
                               "monitorar editais", "monitore editais", "quero monitorar",
                               "acompanhar editais", "busca automática", "busca automatica"]):
        return "configurar_monitoramento"

    # 13.6 Listar monitoramentos
    if any(p in msg for p in ["meus monitoramentos", "listar monitoramentos", "monitoramentos ativos",
                               "ver monitoramentos", "quais monitoramentos", "monitoramentos configurados"]):
        return "listar_monitoramentos"

    # 13.7 Desativar monitoramento
    if any(p in msg for p in ["desativar monitoramento", "parar monitoramento", "cancelar monitoramento",
                               "desative o monitoramento", "pare de monitorar", "remover monitoramento"]):
        return "desativar_monitoramento"

    # 13.8 Configurar notificações
    if any(p in msg for p in ["configurar notificações", "configurar notificacoes", "preferências de notificação",
                               "preferencias de notificacao", "email de notificação", "configurar email",
                               "configurar preferências", "configurar preferencias"]):
        return "configurar_notificacoes"

    # 13.9 Histórico de notificações
    if any(p in msg for p in ["histórico de notificações", "historico de notificacoes", "notificações recebidas",
                               "notificacoes recebidas", "ver notificações", "ver notificacoes",
                               "minhas notificações", "minhas notificacoes", "notificações não lidas",
                               "notificacoes nao lidas"]):
        return "historico_notificacoes"

    # 13.10 Extrair datas de edital
    if any(p in msg for p in ["extrair datas", "extraia as datas", "datas do edital", "prazos do edital",
                               "quais são as datas", "quais sao as datas", "identifique as datas",
                               "encontre as datas"]):
        return "extrair_datas_edital"

    # 13.11 Cancelar alerta
    if any(p in msg for p in ["cancelar alerta", "cancele o alerta", "remover alerta", "remova o alerta",
                               "excluir alerta", "desativar alerta", "não me avise mais",
                               "nao me avise mais"]):
        return "cancelar_alerta"

    return "chat_livre"


def detectar_intencao(message: str) -> str:
    """Wrapper para compatibilidade - retorna apenas a intenção."""
    resultado = detectar_intencao_ia(message)
    return resultado.get("intencao", "chat_livre")


# =============================================================================
# Auth Helpers
# =============================================================================

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False


def create_access_token(user_id: str, email: str, empresa_id: str = None, is_super: bool = False, papel: str = None) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "empresa_id": empresa_id,
        "is_super": is_super,
        "papel": papel,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get('Authorization')

        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]

        if not token:
            return jsonify({"error": "Token não fornecido"}), 401

        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            request.user_id = payload["user_id"]
            request.user_email = payload["email"]
            request.empresa_id = payload.get("empresa_id")
            request.is_super = payload.get("is_super", False)
            request.papel = payload.get("papel")
            # Fallback: se JWT sem empresa_id, buscar primeira empresa do user via UsuarioEmpresa
            if not request.empresa_id:
                db = get_db()
                try:
                    ue = db.query(UsuarioEmpresa).filter(UsuarioEmpresa.user_id == request.user_id, UsuarioEmpresa.ativo == True).first()
                    request.empresa_id = ue.empresa_id if ue else None
                finally:
                    db.close()
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expirado"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Token inválido"}), 401

        return f(*args, **kwargs)
    return decorated


def require_super(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not getattr(request, 'is_super', False):
            return jsonify({"error": "Acesso restrito ao superusuário"}), 403
        return f(*args, **kwargs)
    return decorated


def get_current_user_id():
    return getattr(request, 'user_id', None)


def get_current_empresa_id():
    return getattr(request, 'empresa_id', None)


# =============================================================================
# RN-037 — Consulta de audit log
# =============================================================================

@app.route("/api/auditoria", methods=["GET"])
def api_auditoria():
    """RN-037: consulta log de auditoria. Query params: entidade, entidade_id, limit."""
    from rn_audit import get_auditoria
    entidade = request.args.get("entidade")
    entidade_id = request.args.get("entidade_id")
    try:
        limit = int(request.args.get("limit", 100))
    except (TypeError, ValueError):
        limit = 100
    return jsonify(get_auditoria(entidade=entidade, entidade_id=entidade_id, limit=limit))


# F03-03: Auditoria de aceite de resultado de IA
@app.route("/api/auditoria/aceite-ia", methods=["POST"])
@require_auth
def api_registrar_aceite_ia():
    """Registra que o user revisou e aceitou um resultado de IA.

    Body JSON: {
        "contexto": "upload_certidao" | "cadastro_produto_ia" | etc,
        "recurso_id": "<id da entidade afetada>" (opcional),
        "dados_extraidos_ia": {...} (snapshot do que IA disse),
        "dados_aceitos_user": {...} (snapshot do que foi salvo)
    }
    """
    from models import AuditoriaAceiteIA, User
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.get_json(silent=True) or {}

    contexto = (data.get("contexto") or "").strip()
    if not contexto:
        return jsonify({"error": "Campo 'contexto' obrigatorio"}), 400

    db = get_db()
    try:
        user_email = None
        if user_id:
            user = db.query(User).filter_by(id=user_id).first()
            if user:
                user_email = user.email

        log = AuditoriaAceiteIA(
            id=str(uuid.uuid4()),
            user_id=user_id,
            user_email_snapshot=user_email,
            empresa_id=empresa_id,
            contexto=contexto[:100],
            recurso_id=data.get("recurso_id"),
            dados_extraidos_ia=data.get("dados_extraidos_ia"),
            dados_aceitos_user=data.get("dados_aceitos_user"),
            ip_origem=(request.headers.get("X-Forwarded-For") or request.remote_addr or "")[:64],
            user_agent=(request.headers.get("User-Agent") or "")[:500],
        )
        db.add(log)
        db.commit()
        return jsonify({"ok": True, "id": log.id})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Auth Routes
# =============================================================================

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email e senha são obrigatórios"}), 400

    db = get_db()
    try:
        user = db.query(User).filter(User.email == email).first()
        if not user or not user.password_hash:
            return jsonify({"error": "Email ou senha inválidos"}), 401

        if not verify_password(password, user.password_hash):
            return jsonify({"error": "Email ou senha inválidos"}), 401

        user.last_login_at = datetime.now()

        # Buscar empresa do user (via usuario_empresa N:N, fallback para user_id direto)
        ue = db.query(UsuarioEmpresa).filter(
            UsuarioEmpresa.user_id == user.id, UsuarioEmpresa.ativo == True
        ).first()
        empresa = ue.empresa if ue else db.query(Empresa).filter(Empresa.user_id == user.id).first()
        empresa_id = empresa.id if empresa else None

        # Create refresh token
        refresh_token_value = str(uuid.uuid4())
        refresh_token = RefreshToken(
            token=refresh_token_value,
            user_id=user.id,
            expires_at=datetime.now() + timedelta(days=30)
        )
        db.add(refresh_token)
        db.commit()

        access_token = create_access_token(user.id, user.email, empresa_id=empresa_id, is_super=user.is_super)

        resp = {
            "access_token": access_token,
            "refresh_token": refresh_token_value,
            "user": user.to_dict(),
            "has_empresa": empresa is not None,
        }
        if empresa:
            resp["empresa"] = empresa.to_dict()

        return jsonify(resp)
    finally:
        db.close()


@app.route("/api/auth/register", methods=["POST"])
def register():
    data = request.json or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not name or not email or not password:
        return jsonify({"error": "Nome, email e senha são obrigatórios"}), 400

    if len(password) < 6:
        return jsonify({"error": "A senha deve ter pelo menos 6 caracteres"}), 400

    db = get_db()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            return jsonify({"error": "Este email já está cadastrado"}), 409

        user = User(
            email=email,
            name=name,
            password_hash=hash_password(password)
        )
        db.add(user)
        db.commit()

        # Create refresh token
        refresh_token_value = str(uuid.uuid4())
        refresh_token = RefreshToken(
            token=refresh_token_value,
            user_id=user.id,
            expires_at=datetime.now() + timedelta(days=30)
        )
        db.add(refresh_token)
        db.commit()

        access_token = create_access_token(user.id, user.email)

        return jsonify({
            "access_token": access_token,
            "refresh_token": refresh_token_value,
            "user": user.to_dict(),
            "has_empresa": False,
        }), 201
    finally:
        db.close()


@app.route("/api/auth/user", methods=["GET"])
@require_auth
def get_current_user():
    db = get_db()
    try:
        user = db.query(User).filter(User.id == get_current_user_id()).first()
        if not user:
            return jsonify({"error": "Usuário não encontrado"}), 404
        empresa = db.query(Empresa).filter(Empresa.user_id == user.id).first()
        resp = user.to_dict()
        resp["has_empresa"] = empresa is not None
        if empresa:
            resp["empresa"] = empresa.to_dict()
        return jsonify(resp)
    finally:
        db.close()


@app.route("/api/auth/refresh", methods=["POST"])
def refresh():
    data = request.json or {}
    refresh_token_value = data.get("refresh_token", "")

    if not refresh_token_value:
        return jsonify({"error": "Refresh token não fornecido"}), 400

    db = get_db()
    try:
        token_record = db.query(RefreshToken).filter(
            RefreshToken.token == refresh_token_value,
            RefreshToken.revoked == False,
            RefreshToken.expires_at > datetime.now()
        ).first()

        if not token_record:
            return jsonify({"error": "Refresh token inválido ou expirado"}), 401

        user = db.query(User).filter(User.id == token_record.user_id).first()
        if not user:
            return jsonify({"error": "Usuário não encontrado"}), 404

        empresa = db.query(Empresa).filter(Empresa.user_id == user.id).first()
        empresa_id = empresa.id if empresa else None
        access_token = create_access_token(user.id, user.email, empresa_id=empresa_id)

        resp = {
            "access_token": access_token,
            "user": user.to_dict(),
            "has_empresa": empresa is not None,
        }
        if empresa:
            resp["empresa"] = empresa.to_dict()
        return jsonify(resp)
    finally:
        db.close()


@app.route("/api/auth/logout", methods=["POST"])
@require_auth
def logout():
    data = request.json or {}
    refresh_token_value = data.get("refresh_token", "")

    if refresh_token_value:
        db = get_db()
        try:
            token_record = db.query(RefreshToken).filter(
                RefreshToken.token == refresh_token_value
            ).first()
            if token_record:
                token_record.revoked = True
                db.commit()
        finally:
            db.close()

    return jsonify({"message": "Logout realizado com sucesso"})


@app.route("/api/auth/switch-empresa", methods=["POST"])
@require_auth
def switch_empresa():
    """Troca a empresa ativa e gera novo token JWT."""
    data = request.json or {}
    empresa_id = data.get("empresa_id", "").strip()
    if not empresa_id:
        return jsonify({"error": "empresa_id é obrigatório"}), 400

    db = get_db()
    try:
        # Verificar se superuser ou se tem vínculo via usuario_empresa
        papel = None
        if request.is_super:
            empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
            papel = "super"
        else:
            ue = db.query(UsuarioEmpresa).filter(
                UsuarioEmpresa.user_id == request.user_id,
                UsuarioEmpresa.empresa_id == empresa_id,
                UsuarioEmpresa.ativo == True
            ).first()
            empresa = ue.empresa if ue else None
            papel = ue.papel if ue else None

        if not empresa:
            return jsonify({"error": "Empresa não encontrada ou sem permissão"}), 404

        user = db.query(User).filter(User.id == request.user_id).first()
        access_token = create_access_token(
            request.user_id, request.user_email,
            empresa_id=empresa.id, is_super=user.is_super if user else False,
            papel=papel
        )
        return jsonify({
            "access_token": access_token,
            "empresa": empresa.to_dict(),
            "papel": papel,
        })
    finally:
        db.close()


@app.route("/api/empresa/atual", methods=["GET"])
@require_auth
def get_empresa_atual():
    """Retorna dados da empresa selecionada no JWT. Qualquer usuário autenticado com empresa."""
    if not request.empresa_id:
        return jsonify({"error": "Nenhuma empresa selecionada"}), 404
    db = get_db()
    try:
        empresa = db.query(Empresa).filter(Empresa.id == request.empresa_id).first()
        if not empresa:
            return jsonify({"error": "Empresa não encontrada"}), 404
        return jsonify(empresa.to_dict())
    finally:
        db.close()


@app.route("/api/empresa/atual", methods=["PUT"])
@require_auth
def update_empresa_atual():
    """Atualiza dados da empresa selecionada. Somente admin ou superuser."""
    if not request.empresa_id:
        return jsonify({"error": "Nenhuma empresa selecionada"}), 404
    papel = getattr(request, 'papel', None)
    if not request.is_super and papel != 'admin':
        return jsonify({"error": "Apenas administradores podem editar a empresa"}), 403
    db = get_db()
    try:
        empresa = db.query(Empresa).filter(Empresa.id == request.empresa_id).first()
        if not empresa:
            return jsonify({"error": "Empresa não encontrada"}), 404
        data = request.json or {}
        skip = {"id", "user_id", "created_at", "updated_at"}
        for key, val in data.items():
            if key not in skip and hasattr(empresa, key):
                setattr(empresa, key, val if val != "" else None)
        db.commit()
        db.refresh(empresa)
        return jsonify(empresa.to_dict())
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 400
    finally:
        db.close()


@app.route("/api/admin/associar-empresa", methods=["POST"])
@require_auth
@require_super
def associar_usuario_empresa():
    """Vincula ou desvincula usuário↔empresa. Somente superuser.

    Aceita identificacao da empresa por:
      - empresa_id (UUID) — modo padrao
      - cnpj — busca empresa por CNPJ (util pra fluxos automatizados que
        acabaram de criar via CRUD e nao tem o UUID em mao)
    """
    data = request.json or {}
    user_id = data.get("user_id", "").strip()
    empresa_id = data.get("empresa_id", "").strip()
    cnpj = data.get("cnpj", "").strip()
    papel = data.get("papel", "operador").strip()
    acao = data.get("acao", "vincular").strip()

    if not user_id or (not empresa_id and not cnpj):
        return jsonify({"error": "user_id e (empresa_id OU cnpj) são obrigatórios"}), 400

    db = get_db()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        # Resolve empresa por id OU cnpj
        if empresa_id:
            empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
        else:
            # Busca por CNPJ — normaliza removendo mascara
            cnpj_clean = "".join(c for c in cnpj if c.isdigit())
            empresa = db.query(Empresa).filter(Empresa.cnpj == cnpj_clean).first()
            if not empresa:
                # Tenta com mascara tambem
                empresa = db.query(Empresa).filter(Empresa.cnpj == cnpj).first()
            if empresa:
                empresa_id = empresa.id
        if not user:
            return jsonify({"error": "Usuário não encontrado"}), 404
        if not empresa:
            return jsonify({"error": f"Empresa não encontrada (id={empresa_id or 'NULL'}, cnpj={cnpj or 'NULL'})"}), 404

        if acao == "vincular":
            ue = db.query(UsuarioEmpresa).filter(
                UsuarioEmpresa.user_id == user_id,
                UsuarioEmpresa.empresa_id == empresa_id
            ).first()
            if ue:
                ue.ativo = True
                ue.papel = papel
            else:
                ue = UsuarioEmpresa(user_id=user_id, empresa_id=empresa_id, papel=papel)
                db.add(ue)
            db.commit()
            return jsonify({"message": "Vínculo criado/atualizado", "vinculo": ue.to_dict()})
        elif acao == "desvincular":
            db.query(UsuarioEmpresa).filter(
                UsuarioEmpresa.user_id == user_id,
                UsuarioEmpresa.empresa_id == empresa_id
            ).delete()
            db.commit()
            return jsonify({"message": "Vínculo removido"})
        else:
            return jsonify({"error": "acao deve ser 'vincular' ou 'desvincular'"}), 400
    finally:
        db.close()


@app.route("/api/admin/vinculos", methods=["GET"])
@require_auth
@require_super
def listar_vinculos():
    """Lista vínculos usuario_empresa. Filtra por empresa_id ou user_id via query params."""
    empresa_id = request.args.get("empresa_id")
    user_id = request.args.get("user_id")
    db = get_db()
    try:
        q = db.query(UsuarioEmpresa)
        if empresa_id:
            q = q.filter(UsuarioEmpresa.empresa_id == empresa_id)
        if user_id:
            q = q.filter(UsuarioEmpresa.user_id == user_id)
        vinculos = q.filter(UsuarioEmpresa.ativo == True).all()
        result = []
        for v in vinculos:
            d = v.to_dict()
            d["user_name"] = v.user.name if v.user else None
            d["user_email"] = v.user.email if v.user else None
            d["empresa_nome"] = v.empresa.razao_social if v.empresa else None
            result.append(d)
        return jsonify({"vinculos": result})
    finally:
        db.close()


@app.route("/api/auth/minhas-empresas", methods=["GET"])
@require_auth
def minhas_empresas():
    """Retorna empresas vinculadas ao usuario (mesmo pra super).

    Comportamento corrigido em 2026-04-29: SelecionarEmpresaPage so deve
    mostrar empresas que o user esta EXPLICITAMENTE vinculado via
    usuario_empresa. Mesmo super so opera em empresas onde tem vinculo
    formal (papel definido). "Super" da poder admin global, mas para
    SELECIONAR empresa ativa o user precisa ter sido vinculado.

    - empresas: empresas vinculadas (filtro: usuario_empresa.ativo=1 + empresa.ativo=1)
    - vinculadas: idem (mantido pra compatibilidade com FA-07 do UC-F01)

    Bypass para super: query param ?todas=1 retorna todas as empresas
    do banco — usado em telas de admin (Associar Empresa/Usuario,
    CRUD de empresas) onde super precisa ver todas pra gerenciar.
    """
    db = get_db()
    try:
        # vinculadas explicitas (sempre por usuario_empresa)
        ues = db.query(UsuarioEmpresa).filter(
            UsuarioEmpresa.user_id == request.user_id,
            UsuarioEmpresa.ativo == True
        ).all()
        vinculadas = []
        for ue in ues:
            e = ue.empresa
            if e:  # NAO filtra por e.ativo — vinculo ativo eh suficiente
                vinculadas.append({
                    "id": e.id,
                    "razao_social": e.razao_social,
                    "cnpj": e.cnpj,
                    "nome_fantasia": e.nome_fantasia,
                    "papel": ue.papel,
                })

        # Bypass admin: ?todas=1 + super => retorna todas as empresas ativas
        # (uso restrito a telas de administracao)
        todas_param = request.args.get("todas") == "1"
        if todas_param and request.is_super:
            empresas_all = db.query(Empresa).filter(Empresa.ativo == True).all()
            result = [
                {"id": e.id, "razao_social": e.razao_social, "cnpj": e.cnpj,
                 "nome_fantasia": e.nome_fantasia, "papel": "super"}
                for e in empresas_all
            ]
        else:
            result = vinculadas

        return jsonify({"empresas": result, "vinculadas": vinculadas})
    finally:
        db.close()


# =============================================================================
# Ações Routes
# =============================================================================

@app.route("/api/acoes", methods=["GET"])
def listar_acoes():
    """Lista prompts prontos para o dropdown."""
    return jsonify({"prompts": PROMPTS_PRONTOS})


# =============================================================================
# Auto-rename session
# =============================================================================

def generate_session_title(first_question: str) -> str:
    """Generate a short title for the session based on the first question."""
    prompt = f"""Crie um título curto (3-5 palavras) que resuma esta pergunta sobre licitações/editais:
"{first_question}"
Responda apenas com o título, sem aspas ou pontuação final."""

    try:
        messages = [{"role": "user", "content": prompt}]
        # Usar deepseek-chat para tarefas simples (reasoner retorna vazio para prompts curtos)
        title = call_deepseek(messages, max_tokens=50, model_override="deepseek-chat")
        # Clean up the title
        title = title.strip().strip('"\'').strip()
        # Limit length
        if len(title) > 50:
            title = title[:47] + "..."
        return title if title else None
    except Exception as e:
        print(f"Erro ao gerar título: {e}")
        return None


def count_session_messages(session_id: str, db) -> int:
    """Count messages in a session."""
    return db.query(Message).filter(Message.session_id == session_id).count()


# =============================================================================
# Chat Routes (com suporte a ações)
# =============================================================================

@app.route("/api/chat", methods=["POST"])
@require_auth
def chat():
    """
    Endpoint principal do chat.
    Detecta automaticamente a intenção do usuário.
    """
    data = request.json or {}
    session_id = data.get("session_id")
    message = data.get("message", "").strip()
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()

    if not session_id or not message:
        return jsonify({"error": "session_id e message são obrigatórios"}), 400

    # RN-084: cooldown DeepSeek (60s por empresa). Modo warn-only por default.
    try:
        from rn_deepseek import check_cooldown, CooldownError
        check_cooldown(empresa_id)
    except CooldownError as _ce:
        return jsonify({"error": str(_ce), "rn_code": "RN-084", "wait_seconds": _ce.wait_seconds}), 429
    except Exception as _e:
        print(f"[RN-084] cooldown check error: {_e}")

    db = get_db()
    try:
        # Verificar sessão
        session = db.query(Session).filter(
            Session.id == session_id,
            Session.user_id == user_id
        ).first()

        if not session:
            return jsonify({"error": "Sessão não encontrada"}), 404

        # Check if this is the first user message (for auto-rename)
        is_first_message = count_session_messages(session_id, db) == 0

        # Detectar intenção usando agente IA
        print(f"[CHAT] Detectando intenção para: {message[:50]}...")
        intencao_resultado = detectar_intencao_ia(message)
        action_type = intencao_resultado.get("intencao", "chat_livre")
        termo_busca_ia = intencao_resultado.get("termo_busca")
        print(f"[CHAT] Intenção: {action_type} | Termo: {termo_busca_ia}")

        # Salvar mensagem do usuário
        user_msg = Message(
            session_id=session_id,
            role='user',
            content=message,
            action_type=action_type
        )
        db.add(user_msg)

        # Processar de acordo com a ação detectada
        response_text = ""
        resultado = None

        if action_type == "buscar_web":
            response_text, resultado = processar_buscar_web(message, user_id, intencao_resultado)

        elif action_type == "upload_manual":
            response_text, resultado = processar_upload_manual(message, user_id, intencao_resultado)

        elif action_type == "download_url":
            response_text, resultado = processar_download_url(message, user_id, intencao_resultado)

        elif action_type == "cadastrar_fonte":
            response_text, resultado = processar_cadastrar_fonte(message, user_id, intencao_resultado)

        elif action_type == "buscar_editais":
            response_text, resultado = processar_buscar_editais(message, user_id, termo_ia=termo_busca_ia, empresa_id=empresa_id)

        elif action_type == "buscar_editais_simples":
            response_text, resultado = processar_buscar_editais(message, user_id, termo_ia=termo_busca_ia, calcular_score=False, empresa_id=empresa_id)

        elif action_type == "buscar_edital_numero":
            response_text, resultado = processar_buscar_edital_numero(message, user_id)

        elif action_type == "listar_editais":
            response_text, resultado = processar_listar_editais(message, user_id)

        elif action_type == "listar_produtos":
            response_text, resultado = processar_listar_produtos(message, user_id)

        elif action_type == "listar_fontes":
            response_text, resultado = processar_listar_fontes(message)

        elif action_type == "listar_propostas":
            response_text, resultado = processar_listar_propostas(message, user_id)

        elif action_type == "calcular_aderencia":
            response_text, resultado = processar_calcular_aderencia(message, user_id)

        elif action_type == "gerar_proposta":
            response_text, resultado = processar_gerar_proposta(message, user_id)

        elif action_type == "salvar_editais":
            response_text, resultado = processar_salvar_editais(message, user_id, session_id, db)

        elif action_type == "reprocessar_produto":
            response_text, resultado = processar_reprocessar_produto(message, user_id)

        elif action_type == "excluir_edital":
            response_text, resultado = processar_excluir_edital(message, user_id)

        elif action_type == "excluir_produto":
            response_text, resultado = processar_excluir_produto(message, user_id)

        elif action_type == "atualizar_edital":
            response_text, resultado = processar_atualizar_edital(message, user_id)

        elif action_type == "atualizar_produto":
            response_text, resultado = processar_atualizar_produto(message, user_id)

        elif action_type == "consulta_mindsdb":
            response_text, resultado = processar_consulta_mindsdb(message, user_id)

        elif action_type == "registrar_resultado":
            response_text, resultado = processar_registrar_resultado(message, user_id)

        elif action_type == "consultar_resultado":
            response_text, resultado = processar_consultar_resultado(message, user_id)

        elif action_type == "buscar_atas_pncp":
            response_text, resultado = processar_buscar_atas_pncp(message, user_id)

        elif action_type == "buscar_precos_pncp":
            response_text, resultado = processar_buscar_precos_pncp(message, user_id)

        elif action_type == "historico_precos":
            response_text, resultado = processar_historico_precos(message, user_id)

        elif action_type == "listar_concorrentes":
            response_text, resultado = processar_listar_concorrentes(user_id)

        elif action_type == "analisar_concorrente":
            response_text, resultado = processar_analisar_concorrente(message, user_id)

        elif action_type == "recomendar_preco":
            response_text, resultado = processar_recomendar_preco(message, user_id)

        elif action_type == "classificar_edital":
            response_text, resultado = processar_classificar_edital(message, user_id)

        elif action_type == "score_comercial":
            response_text, resultado = processar_score_comercial(message, user_id, empresa_id)

        elif action_type == "verificar_completude":
            response_text, resultado = processar_verificar_completude(message, user_id)

        elif action_type == "cadastrar_produto":
            response_text, resultado = processar_cadastrar_produto(message, user_id)

        elif action_type == "buscar_anvisa":
            response_text, resultado = processar_buscar_anvisa(message, user_id)

        elif action_type == "cadastrar_edital":
            response_text, resultado = processar_cadastrar_edital(message, user_id, intencao_resultado)

        # =============================================================================
        # SPRINT 2: ALERTAS E AUTOMAÇÃO
        # =============================================================================
        elif action_type == "configurar_alertas":
            response_text = processar_configurar_alertas(message, user_id)

        elif action_type == "listar_alertas":
            response_text = processar_listar_alertas(message, user_id)

        elif action_type == "dashboard_prazos":
            response_text = processar_dashboard_prazos(message, user_id)

        elif action_type == "calendario_editais":
            response_text = processar_calendario_editais(message, user_id)

        elif action_type == "configurar_monitoramento":
            response_text = processar_configurar_monitoramento(message, user_id)

        elif action_type == "listar_monitoramentos":
            response_text = processar_listar_monitoramentos(message, user_id)

        elif action_type == "desativar_monitoramento":
            response_text = processar_desativar_monitoramento(message, user_id)

        elif action_type == "configurar_notificacoes":
            response_text = processar_configurar_notificacoes(message, user_id)

        elif action_type == "historico_notificacoes":
            response_text = processar_historico_notificacoes(message, user_id)

        elif action_type == "extrair_datas_edital":
            response_text = processar_extrair_datas_edital(message, user_id)

        elif action_type == "cancelar_alerta":
            response_text = processar_cancelar_alerta(message, user_id)

        # =============================================================================
        # ANÁLISE DE EDITAIS (Resumir e Perguntar)
        # =============================================================================
        elif action_type == "resumir_edital":
            response_text, resultado = processar_resumir_edital(message, user_id, intencao_resultado)

        elif action_type == "perguntar_edital":
            response_text, resultado = processar_perguntar_edital(message, user_id, intencao_resultado)

        elif action_type == "baixar_pdf_edital":
            response_text, resultado = processar_baixar_pdf_edital(message, user_id, intencao_resultado)

        elif action_type == "atualizar_url_edital":
            response_text, resultado = processar_atualizar_url_edital(message, user_id, intencao_resultado)

        elif action_type == "buscar_links_editais":
            response_text, resultado = processar_buscar_links_editais(message, user_id)

        # =============================================================================
        # FASE 1: PRECIFICAÇÃO (UC-P01 a UC-P10)
        # =============================================================================
        elif action_type == "precif_organizar_lotes":
            response_text, resultado = processar_precif_organizar_lotes(message, user_id, empresa_id)

        elif action_type == "precif_selecao_portfolio":
            response_text, resultado = processar_precif_selecao_portfolio(message, user_id, empresa_id)

        elif action_type == "precif_calcular_volumetria":
            response_text, resultado = processar_precif_calcular_volumetria(message, user_id)

        elif action_type == "precif_configurar_custos":
            response_text, resultado = processar_precif_configurar_custos(message, user_id, empresa_id)

        elif action_type == "precif_preco_base":
            response_text, resultado = processar_precif_preco_base(message, user_id)

        elif action_type == "precif_valor_referencia":
            response_text, resultado = processar_precif_valor_referencia(message, user_id)

        elif action_type == "precif_estruturar_lances":
            response_text, resultado = processar_precif_estruturar_lances(message, user_id)

        elif action_type == "precif_estrategia":
            response_text, resultado = processar_precif_estrategia(message, user_id, empresa_id)

        elif action_type == "precif_historico_camada_f":
            response_text, resultado = processar_precif_historico_camada_f(message, user_id)

        elif action_type == "precif_comodato":
            response_text, resultado = processar_precif_comodato(message, user_id, empresa_id)

        else:  # chat_livre
            response_text = processar_chat_livre(message, user_id, session_id, db)

        # Salvar resposta do assistente
        # Se foi busca de editais, salvar os editais no sources_json para recuperar depois
        sources_data = None
        if action_type in ["buscar_editais", "buscar_editais_simples"] and resultado:
            # Salvar editais para uso posterior (salvar_editais) — banco é LONGTEXT, aguenta tudo
            sources_data = {
                "editais": resultado.get("editais", []),
                "editais_com_score": resultado.get("editais_com_score", []),
                "editais_recomendados": resultado.get("editais_recomendados", []),
                "editais_participar": resultado.get("editais_participar", []),
                "termo": resultado.get("termo")
            }

        assistant_msg = Message(
            session_id=session_id,
            role='assistant',
            content=response_text,
            action_type=action_type,
            sources_json=sources_data
        )
        db.add(assistant_msg)

        # Auto-rename session if first message
        new_session_name = None
        print(f"DEBUG: is_first_message={is_first_message}, session.name='{session.name}'")
        if is_first_message and session.name == "Nova conversa":
            try:
                print(f"DEBUG: Gerando título para: {message[:50]}...")
                new_session_name = generate_session_title(message)
                print(f"DEBUG: Título gerado: {new_session_name}")
                if new_session_name:
                    session.name = new_session_name
            except Exception as e:
                print(f"DEBUG: Erro ao gerar título: {e}")
                pass  # Don't fail the request if rename fails

        # Atualizar sessão
        session.updated_at = datetime.now()
        db.commit()

        response_data = {
            "response": response_text,
            "session_id": session_id,
            "action_type": action_type,
            "resultado": resultado
        }

        if new_session_name:
            response_data["session_name"] = new_session_name

        return jsonify(response_data)

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Processadores de Ações
# =============================================================================

def processar_buscar_web(message: str, user_id: str, intencao_resultado: dict):
    """
    Processa ação: Buscar material/manuais/datasheets na web (DuckDuckGo/Serper/SerpAPI).

    Diferente de buscar_editais - aqui buscamos MANUAIS e ESPECIFICAÇÕES de produtos,
    não licitações/editais.
    """
    # Extrair termo de busca da IA ou usar mensagem
    termo = intencao_resultado.get("termo_busca") or message

    resultado = tool_web_search(termo, user_id)

    if resultado.get("success"):
        response = f"""## 🔍 Busca de Material na Web

**Termo pesquisado:** {termo}
**Total de resultados:** {resultado.get('total_resultados', 0)}
**PDFs encontrados:** {resultado.get('pdfs_encontrados', 0)}

"""
        # Mostrar PDFs encontrados
        pdfs = resultado.get('resultados_pdf', [])
        if pdfs:
            response += "### 📄 PDFs Encontrados\n\n"
            for i, pdf in enumerate(pdfs, 1):
                response += f"**{i}. {pdf['titulo']}**\n"
                response += f"   {pdf['descricao'][:150]}...\n" if len(pdf.get('descricao', '')) > 150 else f"   {pdf.get('descricao', '')}\n"
                response += f"   🔗 [Baixar PDF]({pdf['link']})\n\n"

        # Mostrar outros resultados
        outros = resultado.get('outros_resultados', [])
        if outros:
            response += "### 🌐 Outros Resultados\n\n"
            for i, item in enumerate(outros, 1):
                response += f"**{i}. {item['titulo']}**\n"
                response += f"   🔗 {item['link']}\n\n"

        response += """---
### Próximos passos:
Para baixar um PDF e cadastrar como produto, envie:
`Baixe o arquivo da URL: <cole_a_url_do_pdf>`

O sistema irá:
1. Baixar o arquivo
2. Extrair texto e especificações
3. Cadastrar como produto no sistema"""

    else:
        response = f"❌ Erro na busca: {resultado.get('error', 'Erro desconhecido')}"

    return response, resultado


def processar_upload_manual(message: str, user_id: str, intencao_resultado: dict):
    """
    Processa ação: Upload de manual/PDF para cadastrar produto.

    Nota: O upload físico do arquivo é feito via /api/upload.
    Esta função processa a intenção quando o usuário menciona que quer processar um arquivo.
    """
    nome_produto = intencao_resultado.get("nome_produto")

    if nome_produto:
        response = f"""## 📄 Upload de Manual

Para cadastrar o produto **{nome_produto}**, faça o seguinte:

1. Clique no botão **📎** ao lado do campo de mensagem
2. Selecione o arquivo PDF do manual
3. Após o upload, envie uma mensagem confirmando: "Processe como {nome_produto}"

O sistema irá:
- Extrair o texto do PDF
- Identificar especificações técnicas
- Cadastrar o produto com todas as specs"""
    else:
        response = """## 📄 Upload de Manual

Para cadastrar um produto a partir de um manual PDF:

1. Clique no botão **📎** ao lado do campo de mensagem
2. Selecione o arquivo PDF do manual
3. Após o upload, informe o nome do produto

Exemplo: "Processe o manual que enviei e cadastre como Analisador Bioquímico BS-240"

O sistema extrairá automaticamente as especificações técnicas do manual."""

    return response, {"status": "aguardando_upload", "nome_produto": nome_produto}


def processar_download_url(message: str, user_id: str, intencao_resultado: dict):
    """
    Processa ação: Baixar arquivo de URL, extrair especificações e cadastrar produto.

    Fluxo completo:
    1. Baixa o arquivo da URL
    2. Extrai texto do PDF
    3. Usa IA para extrair especificações técnicas
    4. Cadastra produto no banco
    """
    import re

    intencao_resultado = intencao_resultado or {}

    # Extrair URL da mensagem ou do resultado da IA
    url = intencao_resultado.get("url")
    nome_produto = intencao_resultado.get("nome_produto")

    # Se IA não extraiu a URL, tentar extrair via regex
    if not url:
        url_match = re.search(r'https?://[^\s<>"\']+', message)
        if url_match:
            url = url_match.group()

    if not url:
        return "❌ Não encontrei uma URL na mensagem. Envie no formato:\n`Baixe o arquivo da URL: https://exemplo.com/manual.pdf`", {"error": "URL não encontrada"}

    # Se não tem nome do produto, tentar extrair do nome do arquivo ou pedir
    if not nome_produto:
        # Tentar extrair do nome do arquivo na URL
        filename = url.split('/')[-1].split('?')[0]
        if filename and len(filename) > 5:
            nome_produto = filename.replace('.pdf', '').replace('_', ' ').replace('-', ' ')[:50]

    response = f"## ⏳ Baixando arquivo...\n\n**URL:** {url}\n\n"

    # 1. Baixar o arquivo
    resultado_download = tool_download_arquivo(url, user_id, nome_produto)

    if not resultado_download.get("success"):
        return f"❌ Erro ao baixar arquivo: {resultado_download.get('error')}", resultado_download

    filepath = resultado_download.get("filepath")
    filesize = resultado_download.get("size", 0)
    response += f"✅ Arquivo baixado: {resultado_download.get('filename')} ({filesize/1024:.1f} KB)\n\n"

    # 2. Se não tem nome do produto, pedir ao usuário
    if not nome_produto or nome_produto == "documento":
        response += """## ⚠️ Nome do produto não identificado

Envie o nome do produto para cadastrar. Exemplo:
`Cadastre como Analisador Bioquímico BS-240 da Mindray`

Ou informe mais detalhes:
`Cadastre como [nome], fabricante [fabricante], categoria [categoria]`"""
        return response, {
            "success": True,
            "status": "aguardando_nome_produto",
            "filepath": filepath,
            "filesize": filesize
        }

    # 3. Processar o arquivo e cadastrar produto
    response += f"## ⏳ Processando PDF e extraindo especificações...\n\n"

    # Determinar categoria automaticamente
    categoria = "equipamento"  # Padrão
    nome_lower = nome_produto.lower()
    if any(t in nome_lower for t in ["analisador", "bioquímic", "laborat"]):
        categoria = "equipamento"
    elif any(t in nome_lower for t in ["centrifuga", "microscop"]):
        categoria = "equipamento"
    elif any(t in nome_lower for t in ["cama", "maca", "cadeira"]):
        categoria = "mobiliario"
    elif any(t in nome_lower for t in ["monitor", "desfibrilador", "eletrocard"]):
        categoria = "equipamento"

    resultado_processo = tool_processar_upload(
        filepath=filepath,
        user_id=user_id,
        nome_produto=nome_produto,
        categoria=categoria,
        fabricante="Mindray" if "mindray" in message.lower() else None,
        modelo=None
    )

    if resultado_processo.get("success"):
        produto = resultado_processo.get("produto", {})
        specs = resultado_processo.get("especificacoes", [])

        response += f"""## ✅ Produto Cadastrado com Sucesso!

**Nome:** {produto.get('nome', nome_produto)}
**Categoria:** {categoria}
**Fabricante:** {produto.get('fabricante', 'Não informado')}

### Especificações Extraídas ({len(specs)} encontradas):
"""
        for spec in specs[:10]:  # Mostrar até 10 specs
            response += f"- **{spec.get('nome', 'N/A')}:** {spec.get('valor', 'N/A')}\n"

        if len(specs) > 10:
            response += f"\n... e mais {len(specs) - 10} especificações.\n"

        response += f"\n---\n✅ Produto pronto para calcular aderência com editais!"
    else:
        response += f"❌ Erro ao processar: {resultado_processo.get('error')}"

    return response, resultado_processo


def processar_cadastrar_fonte(message: str, user_id: str, intencao_resultado: dict = None):
    """
    Processa ação: Cadastrar fonte de editais.
    Se tiver todos os dados, cadastra direto.
    Se faltar URL ou tipo, busca na web automaticamente.
    """
    import re

    intencao_resultado = intencao_resultado or {}

    # Verificar se a IA já extraiu os dados (aceitar vários nomes de campo)
    nome_fonte = intencao_resultado.get("nome_fonte") or intencao_resultado.get("nome")
    tipo_fonte = intencao_resultado.get("tipo_fonte") or intencao_resultado.get("tipo")
    url_fonte = intencao_resultado.get("url_fonte") or intencao_resultado.get("url")

    # Se não tem nome_fonte, tentar extrair da mensagem com regex
    if not nome_fonte:
        # Padrão: "fonte NOME" ou "fonte: NOME" ou "cadastre a fonte NOME"
        # Inclui caracteres acentuados (À-ú)
        match = re.search(r'fonte[:\s]+([A-Za-zÀ-ú0-9\-_\s]+?)(?:,|\s+tipo|\s+url|$)', message, re.IGNORECASE)
        if match:
            nome_fonte = match.group(1).strip()

    # Se não tem tipo_fonte, tentar extrair da mensagem
    if not tipo_fonte:
        if 'tipo api' in message.lower() or ', api,' in message.lower() or ' api ' in message.lower():
            tipo_fonte = 'api'
        elif 'tipo scraper' in message.lower() or ', scraper,' in message.lower() or ' scraper ' in message.lower():
            tipo_fonte = 'scraper'

    # Se não tem URL, tentar extrair da mensagem
    if not url_fonte:
        url_match = re.search(r'https?://[^\s,]+', message)
        if url_match:
            url_fonte = url_match.group(0).strip()

    print(f"[FONTE] Dados extraídos: nome={nome_fonte}, tipo={tipo_fonte}, url={url_fonte}")

    # Se tem nome mas falta URL, buscar na web
    if nome_fonte and not url_fonte:
        print(f"[FONTE] URL não informada, buscando na web...")

        # Buscar na web
        resultado_busca = tool_web_search(f"{nome_fonte} portal licitações governo site oficial", user_id, num_results=5)

        # Combinar todos os resultados (PDFs + outros)
        todos_resultados = resultado_busca.get("resultados_pdf", []) + resultado_busca.get("outros_resultados", [])

        if resultado_busca.get("success") and todos_resultados:
            # Usar IA para extrair a URL correta dos resultados
            resultados_texto = "\n".join([
                f"- {r.get('titulo')}: {r.get('link')}"
                for r in todos_resultados[:5]
            ])

            prompt_extrair = f"""Analise os resultados de busca abaixo e identifique a URL oficial do portal de licitações "{nome_fonte}".

Resultados:
{resultados_texto}

Retorne APENAS um JSON com:
- url: URL oficial do portal (a mais provável)
- tipo: "api" se for portal do governo federal ou tiver API conhecida, "scraper" caso contrário
- nome_completo: nome completo/oficial da fonte

JSON:"""

            try:
                resposta_ia = call_deepseek([{"role": "user", "content": prompt_extrair}], max_tokens=300, model_override="deepseek-chat")
                json_match = re.search(r'\{[\s\S]*?\}', resposta_ia)
                if json_match:
                    dados_web = json.loads(json_match.group())
                    url_fonte = dados_web.get("url")
                    if not tipo_fonte:
                        tipo_fonte = dados_web.get("tipo", "scraper")
                    nome_completo = dados_web.get("nome_completo")
                    if nome_completo:
                        nome_fonte = nome_completo
                    print(f"[FONTE] Dados da web: url={url_fonte}, tipo={tipo_fonte}, nome={nome_fonte}")
            except Exception as e:
                print(f"[FONTE] Erro ao extrair dados da web: {e}")
                # Fallback: usar primeiro resultado
                if todos_resultados:
                    primeiro = todos_resultados[0]
                    url_fonte = primeiro.get("link")
                    if not tipo_fonte:
                        tipo_fonte = "scraper"

    # Se ainda não tem tipo, usar padrão
    if not tipo_fonte:
        tipo_fonte = "scraper"

    print(f"[FONTE] Dados finais: nome={nome_fonte}, tipo={tipo_fonte}, url={url_fonte}")

    if nome_fonte and url_fonte:
        resultado = tool_cadastrar_fonte(
            nome=nome_fonte,
            tipo=tipo_fonte,
            url_base=url_fonte,
            descricao=f"Fonte cadastrada via chat: {nome_fonte}"
        )
        if resultado.get("success"):
            response = f"""✅ Fonte cadastrada com sucesso!

**Nome:** {nome_fonte}
**Tipo:** {tipo_fonte}
**URL:** {url_fonte}"""
        elif resultado.get("duplicada"):
            fonte_exist = resultado.get('fonte_existente', {})
            response = f"""⚠️ Fonte já existe!

**Nome:** {fonte_exist.get('nome')}
**URL:** {fonte_exist.get('url')}"""
        else:
            response = f"❌ Erro ao cadastrar: {resultado.get('error')}"
        return response, resultado

    # Se não conseguiu extrair nem da web, pedir mais informações
    response = f"""Não consegui encontrar informações sobre a fonte "{nome_fonte or 'informada'}".

Por favor, forneça os dados completos:
- **Nome**: Nome da fonte
- **Tipo**: api ou scraper
- **URL**: URL base da fonte

Exemplo: `cadastre a fonte BEC-SP, tipo scraper, url https://bec.sp.gov.br`"""
    return response, {"status": "aguardando_dados"}


def _buscar_editais_multifonte(termo: str, user_id: str, uf: str = None,
                                incluir_encerrados: bool = False,
                                buscar_detalhes: bool = True,
                                dias_busca: int = 90,
                                fonte: str = None,
                                modalidade: str = None,
                                tipo_produto: str = None,
                                origem: str = None) -> dict:
    """
    Busca editais em múltiplas fontes (PNCP API + scraper web) EM PARALELO,
    deduplica e retorna resultado consolidado.
    Reutilizada pelo chat (processar_buscar_editais) e pelo endpoint REST (/api/editais/buscar).

    Args:
        fonte: Se especificado, busca APENAS nessa fonte. Valores: 'PNCP', nome de fonte scraper, ou None (todas).
        modalidade: Filtro pós-busca por modalidade (ex: "Pregão Eletrônico").
        tipo_produto: Filtro pós-busca por tipo de produto inferido do objeto (ex: "Reagentes").
        origem: Filtro pós-busca por origem do órgão inferida (ex: "Hospital").
    """
    empresa_id = get_current_empresa_id()
    import re
    from datetime import datetime as _dt
    hoje = _dt.now()
    editais = []
    fontes_consultadas = []
    erros_fontes = []

    # Resolver fonte: pode vir como UUID, nome ou URL
    fonte_nome = None
    if fonte:
        fonte_str = fonte.strip()
        # Se parece UUID, buscar nome no banco
        if len(fonte_str) >= 32 and '-' in fonte_str:
            try:
                _db = get_db()
                fonte_obj = _db.query(FonteEdital).filter(FonteEdital.id == fonte_str).first()
                if fonte_obj:
                    fonte_nome = fonte_obj.nome
                    print(f"[BUSCA-MULTI] Fonte UUID '{fonte_str}' → '{fonte_nome}'")
                _db.close()
            except Exception:
                pass
        if not fonte_nome:
            fonte_nome = fonte_str

    # Normalizar fonte para comparação
    fonte_lower = fonte_nome.lower().strip() if fonte_nome else None
    _fontes_com_api = ('pncp', 'bec', 'bec-sp', 'bec sp', 'comprasnet')
    buscar_pncp = fonte_lower is None or 'pncp' in fonte_lower
    buscar_bec = fonte_lower is None or fonte_lower in ('bec', 'bec-sp', 'bec sp')
    buscar_comprasnet = fonte_lower is None or fonte_lower in ('comprasnet',)

    # obs 30b validador V8: em busca geral, respeitar fontes DESATIVADAS
    # (FonteEdital.ativo=False) — fonte desativada na UI não é consultada.
    if fonte_lower is None:
        try:
            _dbf = get_db()
            _inativas = {
                (f.nome or '').lower().strip()
                for f in _dbf.query(FonteEdital).filter(FonteEdital.ativo == False).all()
            }
            _dbf.close()
            # nome no banco pode ter texto extra (ex.: "ComprasNet (Portal de
            # Compras do Governo Federal)"); usar substring, nao igualdade.
            if any('pncp' in n for n in _inativas):
                buscar_pncp = False
            if any('bec' in n for n in _inativas):
                buscar_bec = False
            if any('comprasnet' in n for n in _inativas):
                buscar_comprasnet = False
            if _inativas:
                print(f"[BUSCA-MULTI] Fontes desativadas ignoradas: {_inativas}")
        except Exception as _e:
            print(f"[BUSCA-MULTI] erro lendo fontes ativas: {_e}")

    # Scraper: apenas quando busca geral ou fonte sem API própria
    if fonte_lower is None:
        buscar_scraper = True
    elif fonte_lower in _fontes_com_api:
        buscar_scraper = False
    else:
        buscar_scraper = True
        buscar_pncp = False

    # Se fonte é BEC ou ComprasNet, não buscar PNCP
    if fonte_lower and 'pncp' not in fonte_lower:
        buscar_pncp = False

    if fonte_lower:
        print(f"[BUSCA-MULTI] Buscando '{termo}' na fonte '{fonte_nome}'...")
    else:
        print(f"[BUSCA-MULTI] Buscando '{termo}' em todas as fontes (PNCP + BEC + ComprasNet + Scraper)...")

    # 1. Buscar no PNCP (API oficial) — com tratamento de erro
    if buscar_pncp:
        try:
            resultado_pncp = tool_buscar_editais_fonte("PNCP", termo, user_id, empresa_id=empresa_id, uf=uf,
                                                        buscar_detalhes=buscar_detalhes,
                                                        incluir_encerrados=incluir_encerrados,
                                                        dias_busca=dias_busca)
            if resultado_pncp.get("success"):
                editais_pncp = resultado_pncp.get("editais", [])
                for ed in editais_pncp:
                    ed['fonte'] = 'PNCP (API)'
                if not incluir_encerrados:
                    antes = len(editais_pncp)
                    editais_pncp = [e for e in editais_pncp if not e.get('encerrado')]
                    filtrados = antes - len(editais_pncp)
                    if filtrados:
                        print(f"[BUSCA-MULTI] PNCP: {filtrados} encerrados removidos")
                editais.extend(editais_pncp)
                fontes_consultadas.append("PNCP (API)")
                print(f"[BUSCA-MULTI] PNCP: {len(editais_pncp)} editais encontrados")
            else:
                erros_fontes.append(f"PNCP: {resultado_pncp.get('error', 'sem resultados')}")
        except Exception as e:
            print(f"[BUSCA-MULTI] Erro PNCP: {e}")
            erros_fontes.append(f"PNCP: {e}")

    # 2. Buscar na BEC-SP (API direta)
    if buscar_bec:
        try:
            from tools import tool_buscar_editais_bec
            resultado_bec = tool_buscar_editais_bec(
                termo, user_id,
                incluir_encerrados=incluir_encerrados,
                dias_busca=dias_busca
            )
            if resultado_bec.get("success"):
                editais_bec = resultado_bec.get("editais", [])
                if not incluir_encerrados:
                    antes = len(editais_bec)
                    editais_bec = [e for e in editais_bec if not e.get('encerrado')]
                    filtrados = antes - len(editais_bec)
                    if filtrados:
                        print(f"[BUSCA-MULTI] BEC-SP: {filtrados} encerrados removidos")
                editais.extend(editais_bec)
                fontes_consultadas.append("BEC-SP (API)")
                print(f"[BUSCA-MULTI] BEC-SP: {len(editais_bec)} editais encontrados")
            else:
                erros_fontes.append(f"BEC-SP: {resultado_bec.get('error', 'sem resultados')}")
        except Exception as e:
            print(f"[BUSCA-MULTI] Erro BEC-SP: {e}")
            erros_fontes.append(f"BEC-SP: {e}")

    # 3. Buscar no ComprasNet (API direta com fallback para scraper)
    _comprasnet_precisa_scraper = False
    if buscar_comprasnet:
        try:
            from tools import tool_buscar_editais_comprasnet
            resultado_cn = tool_buscar_editais_comprasnet(
                termo, user_id,
                incluir_encerrados=incluir_encerrados,
                dias_busca=dias_busca
            )
            if resultado_cn.get("success"):
                editais_cn = resultado_cn.get("editais", [])
                if editais_cn:
                    if not incluir_encerrados:
                        antes = len(editais_cn)
                        editais_cn = [e for e in editais_cn if not e.get('encerrado')]
                        filtrados = antes - len(editais_cn)
                        if filtrados:
                            print(f"[BUSCA-MULTI] ComprasNet: {filtrados} encerrados removidos")
                    editais.extend(editais_cn)
                    fontes_consultadas.append("ComprasNet (API)")
                    print(f"[BUSCA-MULTI] ComprasNet API: {len(editais_cn)} editais")
                elif not resultado_cn.get("api_disponivel", True):
                    _comprasnet_precisa_scraper = True
                    print(f"[BUSCA-MULTI] ComprasNet API indisponível, ativando scraper fallback")
                    erros_fontes.append(f"ComprasNet API: {resultado_cn.get('mensagem', 'indisponível')}")
        except Exception as e:
            print(f"[BUSCA-MULTI] Erro ComprasNet: {e}")
            _comprasnet_precisa_scraper = True
            erros_fontes.append(f"ComprasNet: {e}")

    # Mapear nomes amigáveis de fonte para domínios de URL
    _fonte_to_dominios = {
        'bec-sp': ['bec.sp.gov.br'],
        'bec sp': ['bec.sp.gov.br'],
        'bec': ['bec.sp.gov.br'],
        'comprasnet': ['comprasnet.gov.br'],
        'licitacoes-e': ['licitacoes-e.com.br'],
        'compras.rs': ['compras.rs.gov.br'],
        'compras.mg': ['compras.mg.gov.br'],
        'gov.br': ['gov.br'],
        'licitanet': ['licitanet.com.br'],
        'portal de compras': ['portaldecompraspublicas.com.br'],
    }

    # 4. Buscar em outras fontes via scraper web (Brave/Serper/SerpAPI) — com tratamento de erro
    resultado_scraper = None
    if buscar_scraper or _comprasnet_precisa_scraper:
        try:
            # Determinar domínios para o scraper
            fontes_scraper = None  # None = todas
            if _comprasnet_precisa_scraper and not buscar_scraper:
                # Scraper APENAS para ComprasNet (fallback da API indisponível)
                fontes_scraper = ['comprasnet.gov.br', 'gov.br/compras']
                print(f"[BUSCA-MULTI] Scraper fallback restrito a ComprasNet: {fontes_scraper}")
            elif fonte_lower and 'pncp' not in fonte_lower:
                # Se fonte específica (não PNCP/BEC/ComprasNet), buscar SÓ naquela fonte
                dominios = _fonte_to_dominios.get(fonte_lower, [])
                if not dominios:
                    # Tentar buscar domínio da fonte no banco
                    try:
                        _db = get_db()
                        _fobj = _db.query(FonteEdital).filter(
                            FonteEdital.nome.ilike(f"%{fonte_nome}%")
                        ).first()
                        if _fobj and _fobj.url_base:
                            dom = _fobj.url_base.replace("https://", "").replace("http://", "").split("/")[0]
                            dominios = [dom]
                        _db.close()
                    except Exception:
                        pass
                if dominios:
                    fontes_scraper = dominios
                    print(f"[BUSCA-MULTI] Scraper restrito a: {fontes_scraper}")
            resultado_scraper = tool_buscar_editais_scraper(termo, fontes=fontes_scraper, user_id=user_id)
        except Exception as e:
            print(f"[BUSCA-MULTI] Erro scraper: {e}")
            resultado_scraper = None
            erros_fontes.append(f"Scraper: {e}")

    if resultado_scraper and resultado_scraper.get("success"):
        editais_scraper = resultado_scraper.get("editais", [])
        links_pncp = {ed.get('url', '') for ed in editais}

        palavras_excluir_objeto = [
            'prestação de serviço', 'mão de obra', 'dedicação exclusiva',
            'terceirização', 'lavanderia', 'limpeza', 'manutenção preventiva',
            'manutenção corretiva', 'prorrogação da ata', 'prorrogação parcial',
            'termo aditivo', 'credenciadas no sistema', 'poderão participar'
        ]

        editais_novos = []
        editais_para_enriquecer = []  # (indice, numero_edital, fonte_nome)

        for ed in editais_scraper:
            if ed.get('link') not in links_pncp and ed.get('link'):
                # Filtrar resultados gov.br/pncp.gov.br/compras.gov.br do scraper
                # quando já temos busca PNCP API (são duplicatas em formato inferior)
                ed_link = (ed.get('link', '') or '').lower()
                ed_fonte = (ed.get('fonte', '') or '').lower()
                if buscar_pncp and any(d in ed_link or d in ed_fonte for d in ['pncp.gov.br', 'compras.gov.br', 'www.gov.br']):
                    continue

                # Filtrar por fonte específica se solicitado
                if fonte_lower and 'pncp' not in fonte_lower:
                    ed_fonte = (ed.get('fonte', '') or '').lower()
                    ed_link = (ed.get('link', '') or '').lower()
                    # Verificar se a fonte do edital corresponde à fonte pedida
                    # Tentar match direto e por domínio
                    dominios_alvo = _fonte_to_dominios.get(fonte_lower, [fonte_lower])
                    fonte_match = any(d in ed_fonte or d in ed_link for d in dominios_alvo)
                    if not fonte_match and fonte_lower not in ed_fonte and fonte_lower not in ed_link:
                        continue

                texto = (ed.get('descricao', '') + ' ' + ed.get('titulo', '')).lower()
                eh_servico_ou_prorrogacao = any(p in texto for p in palavras_excluir_objeto)
                if eh_servico_ou_prorrogacao:
                    print(f"[BUSCA-MULTI] Filtrando (serviço/prorrogação): {ed.get('numero', ed.get('titulo', '')[:30])}")
                    continue

                numero_edital = ed.get('numero', ed.get('titulo', '')[:50])

                # Filtrar encerrados pelo ano no número (ex: "04/2025" → ano 2025 < atual)
                if not incluir_encerrados and numero_edital:
                    ano_match = re.search(r'/(\d{4})', numero_edital)
                    if ano_match:
                        ano_edital = int(ano_match.group(1))
                        ano_atual = hoje.year
                        if ano_edital < ano_atual:
                            print(f"[BUSCA-MULTI] Filtrando (ano {ano_edital}): {numero_edital}")
                            continue

                ed_normalizado = {
                    'numero': numero_edital,
                    'orgao': ed.get('orgao', 'Não identificado'),
                    'objeto': ed.get('descricao', ed.get('titulo', '')),
                    'url': ed.get('link'),
                    'fonte': f"{ed.get('fonte', 'Web')} (Scraper)",
                    'fonte_tipo': 'scraper',
                    'modalidade': 'Identificar no portal',
                    'valor_referencia': None,
                    'data_abertura': 'Ver no portal'
                }

                idx = len(editais_novos)
                editais_novos.append(ed_normalizado)

                # Marcar para enriquecimento via PNCP
                # Se NÃO incluir encerrados: enriquecer TODOS de 2026+ (precisamos checar data real)
                # Se incluir encerrados: enriquecer até 5 (só para dados extras)
                if numero_edital and '/' in numero_edital:
                    if not incluir_encerrados:
                        # Precisa verificar data de TODOS os editais do ano atual ou futuro
                        editais_para_enriquecer.append((idx, numero_edital, ed.get('fonte', 'Web')))
                    elif len(editais_para_enriquecer) < 5:
                        editais_para_enriquecer.append((idx, numero_edital, ed.get('fonte', 'Web')))

        # Enriquecer editais do scraper em paralelo via PNCP
        if editais_para_enriquecer:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            from tools import _buscar_edital_pncp_por_numero

            def _enriquecer(args):
                idx, numero, fonte = args
                try:
                    return idx, numero, fonte, _buscar_edital_pncp_por_numero(numero)
                except Exception as e:
                    print(f"[BUSCA-MULTI] Erro ao enriquecer {numero}: {e}")
                    return idx, numero, fonte, None

            n_enriquecer = len(editais_para_enriquecer)
            max_workers = min(n_enriquecer, 8)
            timeout_global = max(30, n_enriquecer * 5)  # 5s por edital, mínimo 30s
            print(f"[BUSCA-MULTI] Enriquecendo {n_enriquecer} editais em paralelo ({max_workers} workers, timeout {timeout_global}s)...")
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(_enriquecer, args): args for args in editais_para_enriquecer}
                for future in as_completed(futures, timeout=timeout_global):
                    try:
                        idx, numero, fonte, dados_pncp = future.result(timeout=10)
                        if dados_pncp:
                            # Filtrar encerrado por data de encerramento/fim de vigência
                            data_enc = dados_pncp.get('data_encerramento') or dados_pncp.get('data_fim_vigencia') or ''
                            data_ab = dados_pncp.get('data_abertura', '')
                            if not incluir_encerrados and data_enc:
                                try:
                                    dt_enc = datetime.fromisoformat(str(data_enc).replace('Z', '')[:19])
                                    if dt_enc < hoje:
                                        editais_novos[idx]['_remover'] = True
                                        print(f"[BUSCA-MULTI] Edital {numero} encerrado (fim: {data_enc[:10]}), removendo")
                                        continue
                                except (ValueError, TypeError):
                                    pass
                            editais_novos[idx].update({
                                'cnpj_orgao': dados_pncp.get('cnpj_orgao'),
                                'ano_compra': dados_pncp.get('ano_compra'),
                                'seq_compra': dados_pncp.get('seq_compra'),
                                'numero_pncp': dados_pncp.get('numero_pncp'),
                                'valor_referencia': dados_pncp.get('valor_referencia'),
                                'data_abertura': data_ab,
                                'uf': dados_pncp.get('uf'),
                                'cidade': dados_pncp.get('cidade'),
                                'orgao': dados_pncp.get('orgao') or editais_novos[idx]['orgao'],
                                'objeto': dados_pncp.get('objeto') or editais_novos[idx]['objeto'],
                                'url': dados_pncp.get('url') or editais_novos[idx]['url'],
                                'fonte': f"{fonte} → PNCP",
                                'fonte_tipo': 'api',
                                'dados_completos': True,
                            })
                            print(f"[BUSCA-MULTI] Edital {numero} enriquecido com dados PNCP")
                    except Exception as e:
                        print(f"[BUSCA-MULTI] Timeout/erro no enriquecimento: {e}")
        # Se NÃO incluir encerrados, remover editais do scraper que não foram verificados
        # (data continua "Ver no portal" = não sabemos se está aberto)
        if not incluir_encerrados:
            indices_enriquecidos = {args[0] for args in editais_para_enriquecer}
            removidos_nao_verificados = 0
            for i, ed in enumerate(editais_novos):
                if ed.get('_remover'):
                    continue
                if i in indices_enriquecidos and not ed.get('dados_completos'):
                    # Foi enviado para enriquecimento mas PNCP não encontrou → não verificável
                    ed['_remover'] = True
                    removidos_nao_verificados += 1
                    print(f"[BUSCA-MULTI] Removendo (não verificado no PNCP): {ed.get('numero', '?')}")
            if removidos_nao_verificados:
                print(f"[BUSCA-MULTI] {removidos_nao_verificados} editais removidos por data não verificável")

        editais.extend([e for e in editais_novos if not e.get('_remover')])
        fontes_scraper = resultado_scraper.get('fontes_consultadas', [])
        fontes_consultadas.extend([f"{f} (Scraper)" for f in fontes_scraper if 'pncp' not in f.lower()])
        total_scraper_final = len([e for e in editais_novos if not e.get('_remover')])
        print(f"[BUSCA-MULTI] Scraper: {total_scraper_final} editais adicionais após filtragem")
        if resultado_scraper.get('erros'):
            for err in resultado_scraper.get('erros', []):
                erros_fontes.append(f"{err.get('fonte')}: {err.get('erro')}")

    # 3. Deduplicar por número de edital + fallback orgão+valor (priorizar PNCP)
    editais_unicos = []
    numeros_vistos = set()
    orgao_valor_vistos = set()
    for ed in editais:
        numero = ed.get('numero', '')
        chave = numero if numero and numero not in ['N/A', 'None', ''] else ed.get('url', '')
        # Chave secundária: orgão + valor (pega duplicatas com números diferentes)
        orgao = (ed.get('orgao') or '').strip().lower()
        valor = ed.get('valor_estimado') or ed.get('valor_referencia') or 0
        chave2 = f"{orgao}|{valor}" if orgao and valor else ""
        if chave and chave in numeros_vistos:
            continue
        if chave2 and chave2 in orgao_valor_vistos:
            continue
        if chave:
            numeros_vistos.add(chave)
        if chave2:
            orgao_valor_vistos.add(chave2)
        editais_unicos.append(ed)

    if len(editais) != len(editais_unicos):
        print(f"[BUSCA-MULTI] Removidas {len(editais) - len(editais_unicos)} duplicatas")
    editais = editais_unicos

    # 4. Filtros pós-busca: modalidade, tipo_produto, origem
    if modalidade:
        # Normalizar: "Pregão Eletrônico" → "pregao eletronico", "pregao_eletronico" → "pregao eletronico"
        import unicodedata
        def _norm_mod(s):
            s = (s or '').lower().replace("_", " ")
            # Remover acentos
            return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
        mod_norm = _norm_mod(modalidade)
        editais_pre = len(editais)
        editais = [e for e in editais if mod_norm in _norm_mod(e.get('modalidade') or '')]
        print(f"[BUSCA-MULTI] Filtro modalidade='{modalidade}': {editais_pre} → {len(editais)}")

    if tipo_produto:
        tp_lower = tipo_produto.lower()
        editais_pre = len(editais)
        editais = [e for e in editais if tp_lower in inferir_tipo_produto(e.get('objeto', '')).lower()]
        print(f"[BUSCA-MULTI] Filtro tipo_produto='{tipo_produto}': {editais_pre} → {len(editais)}")

    if origem:
        orig_lower = origem.lower()
        editais_pre = len(editais)
        editais = [e for e in editais if orig_lower in inferir_origem_orgao(e.get('orgao', ''), e.get('orgao_tipo', '')).lower()]
        print(f"[BUSCA-MULTI] Filtro origem='{origem}': {editais_pre} → {len(editais)}")

    # CV01-4 (Arnaldo Sprint 2 V8): sempre devolver success=True quando a busca
    # rodou ate o fim (mesmo com 0 resultados). Antes, lista vazia virava
    # success=False -> frontend lancava erro generico "Busca sem resultados"
    # ao inves de mostrar empty-state. Erros reais sobem como "erros".
    return {
        "success": True,
        "termo": termo,
        "fontes_consultadas": fontes_consultadas,
        "total_resultados": len(editais),
        "editais": editais,
        "erros": erros_fontes if erros_fontes else None
    }


def processar_buscar_editais(message: str, user_id: str, termo_ia: str = None, calcular_score: bool = True, incluir_encerrados: bool = None, empresa_id: str = None):
    """
    Processa ação: Buscar editais

    Novo fluxo:
    1. Busca editais (sem salvar)
    2. Calcula score de aderência para cada edital vs produtos do usuário
       - tipo_score "rapido" (padrão): score rápido em batch via deepseek-chat
       - tipo_score "hibrido": rápido em todos + profundo (6 dimensões) nos top N
       - tipo_score "profundo": profundo (6 dimensões) direto nos N primeiros
    3. Ordena por score
    4. Mostra recomendações (PARTICIPAR/AVALIAR/NÃO PARTICIPAR) com justificativas
    5. Oferece opção de salvar os recomendados

    Args:
        message: Mensagem original do usuário
        user_id: ID do usuário
        termo_ia: Termo de busca já extraído pelo agente classificador (opcional)
        calcular_score: Se True, calcula score de aderência. Se False, apenas lista os editais.
        incluir_encerrados: Se True, inclui editais já encerrados. Se None, detecta da mensagem.
    """
    import json
    import re

    fonte = None  # None = todas as fontes
    uf = None

    # Detectar fonte da mensagem
    msg_lower_fonte = message.lower()
    if 'no pncp' in msg_lower_fonte or 'do pncp' in msg_lower_fonte or 'pelo pncp' in msg_lower_fonte:
        fonte = "PNCP"
    elif 'comprasnet' in msg_lower_fonte:
        fonte = "comprasnet"
    elif 'licitacoes-e' in msg_lower_fonte or 'licitações-e' in msg_lower_fonte or 'licitanet' in msg_lower_fonte:
        fonte = "licitacoes-e"
    elif 'bec' in msg_lower_fonte and 'sp' in msg_lower_fonte:
        fonte = "bec-sp"
    elif 'compras.rs' in msg_lower_fonte or 'compras rs' in msg_lower_fonte:
        fonte = "compras.rs"
    elif 'portal de compras' in msg_lower_fonte and ('mg' in msg_lower_fonte or 'minas' in msg_lower_fonte):
        fonte = "compras.mg"
    elif 'gov.br' in msg_lower_fonte:
        fonte = "gov.br"
    # Se não especificou fonte → None (busca todas)

    # Detectar se deve incluir editais encerrados
    if incluir_encerrados is None:
        msg_lower = message.lower()
        # Negações explícitas → NÃO incluir encerrados
        negar = any(p in msg_lower for p in [
            'sem incluir encerrados', 'sem encerrados', 'não incluir encerrados',
            'nao incluir encerrados', 'excluir encerrados', 'apenas abertos',
            'somente abertos', 'só abertos', 'so abertos',
        ])
        if negar:
            incluir_encerrados = False
        else:
            # Afirmações explícitas → incluir encerrados
            incluir_encerrados = any(p in msg_lower for p in [
                'incluindo encerrados', 'incluir encerrados', 'com encerrados',
                'mostrar encerrados', 'ver encerrados',
            ])

    # Detectar janela de busca (dias) da mensagem
    dias_busca = 90  # default
    msg_lower_dias = message.lower()
    dias_match = re.search(r'janela\s+de\s+(\d+)\s*dias?', msg_lower_dias)
    if not dias_match:
        dias_match = re.search(r'(?:ultimos|últimos)\s+(\d+)\s*dias?', msg_lower_dias)
    if dias_match:
        dias_busca = int(dias_match.group(1))
        if dias_busca != 0:
            dias_busca = max(7, min(730, dias_busca))
    elif 'sem limite' in msg_lower_dias or 'periodo indefinido' in msg_lower_dias:
        dias_busca = 0

    # Detectar tipo de score da mensagem (rapido/hibrido/profundo)
    tipo_score = "rapido"  # padrão quando calcular_score=True
    limite_score_profundo = 10  # padrão
    if not calcular_score:
        tipo_score = "nenhum"
    else:
        msg_lower_score = message.lower()
        if any(p in msg_lower_score for p in ['score profundo', 'análise profunda', 'analise profunda',
                                               'score detalhado', 'análise detalhada', 'analise detalhada',
                                               'com profundo', '6 dimensões', '6 dimensoes', 'score completo']):
            tipo_score = "profundo"
        elif any(p in msg_lower_score for p in ['score híbrido', 'score hibrido', 'com híbrido', 'com hibrido',
                                                 'modo híbrido', 'modo hibrido']):
            tipo_score = "hibrido"
        elif any(p in msg_lower_score for p in ['score rápido', 'score rapido', 'com rápido', 'com rapido']):
            tipo_score = "rapido"

        # Detectar limite para profundo/híbrido: "nos 5 melhores", "top 10", "nos 20 primeiros", "todos"
        if tipo_score in ("profundo", "hibrido"):
            limite_match = re.search(r'(?:nos|top|primeiros|melhores)\s+(\d+)', msg_lower_score)
            if not limite_match:
                limite_match = re.search(r'(\d+)\s+(?:melhores|primeiros|editais)', msg_lower_score)
            if limite_match:
                limite_score_profundo = int(limite_match.group(1))
                limite_score_profundo = max(1, min(100, limite_score_profundo))
            elif 'todos' in msg_lower_score and ('profundo' in msg_lower_score or 'híbrido' in msg_lower_score or 'hibrido' in msg_lower_score):
                limite_score_profundo = 9999  # Todos

    # Usar termo da IA se disponível, senão extrair da mensagem
    if termo_ia:
        termo = termo_ia
        # Limpar modificadores que a IA pode ter incluído no termo
        import re as _re
        for mod in ['incluindo encerrados', 'sem calcular score', 'sem score', 'sem calcular',
                     'apenas listando', 'no pncp', 'no comprasnet', 'na web',
                     'com modalidade', 'modalidade', 'do tipo', 'de origem',
                     'pregão eletrônico', 'pregao eletronico', 'pregão presencial', 'pregao presencial',
                     'concorrência', 'concorrencia', 'tomada de preços', 'tomada de precos',
                     'convite', 'dispensa', 'inexigibilidade',
                     'origem hospital', 'origem municipal', 'origem estadual', 'origem federal',
                     'origem universidade', 'origem autarquia', 'origem lacen',
                     'tipo reagente', 'tipo equipamento', 'tipo comodato', 'tipo aluguel',
                     'tipo informática', 'tipo informatica', 'tipo insumo',
                     'com score profundo', 'com score rápido', 'com score rapido',
                     'com score híbrido', 'com score hibrido', 'score profundo', 'score rápido',
                     'score rapido', 'score híbrido', 'score hibrido', 'score detalhado',
                     'score completo', 'análise profunda', 'analise profunda',
                     'análise detalhada', 'analise detalhada', 'com profundo', 'com rápido',
                     'com rapido', 'com híbrido', 'com hibrido', 'modo híbrido', 'modo hibrido',
                     '6 dimensões', '6 dimensoes']:
            termo = _re.sub(r'\b' + _re.escape(mod) + r'\b', '', termo, flags=_re.IGNORECASE)
        # Limpar "últimos X dias"
        termo = _re.sub(r'(?:ultimos|últimos)\s+\d+\s*dias?', '', termo, flags=_re.IGNORECASE)
        # Limpar "nos N melhores/primeiros", "top N"
        termo = _re.sub(r'(?:nos|top)\s+\d+\s*(?:melhores|primeiros|editais)?', '', termo, flags=_re.IGNORECASE)
        termo = _re.sub(r'\d+\s+(?:melhores|primeiros)', '', termo, flags=_re.IGNORECASE)
        # Limpar espaços duplicados
        termo = _re.sub(r'\s+', ' ', termo).strip()
        print(f"[BUSCA] Usando termo da IA: '{termo}'")
    else:
        termo = None
        # Tentar extrair parâmetros com LLM (usar deepseek-chat para rapidez)
        prompt = f"""Extraia os parâmetros de busca de editais da mensagem.
Retorne APENAS um JSON válido com: fonte (PNCP, ComprasNet, BEC-SP ou null), termo (palavras-chave da busca), uf (sigla do estado com 2 letras ou null)

Mensagem: "{message}"

JSON:"""

        try:
            resposta = call_deepseek([{"role": "user", "content": prompt}], max_tokens=200, model_override="deepseek-chat")
            json_match = re.search(r'\{[\s\S]*?\}', resposta)
            if json_match:
                dados = json.loads(json_match.group())
                # Só usar fonte do DeepSeek se não foi detectada por palavras-chave
                if fonte is None:
                    fonte_ds = dados.get('fonte')
                    if fonte_ds:
                        fonte = fonte_ds
                termo = dados.get('termo')
                uf = dados.get('uf')
        except Exception as e:
            print(f"Erro ao extrair parâmetros com LLM: {e}")

    # Fallback: extrair termos da própria mensagem
    if not termo:
        # Remover palavras comuns de comando e modificadores de busca
        palavras_ignorar = ['busque', 'buscar', 'procure', 'procurar', 'editais', 'edital', 'de', 'do', 'da',
                           'no', 'na', 'em', 'para', 'pncp', 'comprasnet', 'bec', 'sp', 'são', 'paulo',
                           'retorne', 'mostre', 'liste', 'quero', 'ver', 'todos', 'área', 'area',
                           'incluindo', 'encerrados', 'sem', 'calcular', 'score', 'aderência', 'aderencia',
                           'apenas', 'listando', 'últimos', 'ultimos', 'dias', 'com', 'web',
                           'licitacoes-e', 'licitacoes', 'portal', 'compras', 'fonte',
                           'rápido', 'rapido', 'híbrido', 'hibrido', 'profundo', 'detalhado',
                           'completo', 'análise', 'analise', 'profunda', 'detalhada', 'modo',
                           'melhores', 'primeiros', 'top', 'nos', 'dimensões', 'dimensoes']
        palavras = message.lower().split()
        termos = [p for p in palavras if p not in palavras_ignorar and len(p) > 2]
        termo = ' '.join(termos) if termos else message

    # Limpar frases de filtro do termo (modalidade, tipo, origem)
    _filtros_limpar = [
        r'com\s+modalidade\s+\S+(?:\s+\S+)?', r'modalidade\s+\S+(?:\s+\S+)?',
        r'do\s+tipo\s+\S+', r'tipo\s+\S+',
        r'de\s+origem\s+\S+', r'origem\s+\S+',
    ]
    for padrao in _filtros_limpar:
        termo = re.sub(padrao, '', termo, flags=re.IGNORECASE)
    termo = re.sub(r'\s+', ' ', termo).strip()

    # Detectar UF na mensagem
    ufs = ['AC','AL','AP','AM','BA','CE','DF','ES','GO','MA','MT','MS','MG','PA','PB','PR','PE','PI','RJ','RN','RS','RO','RR','SC','SP','SE','TO']
    msg_upper = message.upper()
    for sigla in ufs:
        if f" {sigla} " in f" {msg_upper} " or msg_upper.endswith(f" {sigla}"):
            uf = sigla
            break
    # Detectar por nome do estado
    if "SÃO PAULO" in msg_upper or "SAO PAULO" in msg_upper:
        uf = "SP"
    elif "RIO DE JANEIRO" in msg_upper:
        uf = "RJ"
    elif "MINAS GERAIS" in msg_upper:
        uf = "MG"

    # Detectar modalidade da mensagem
    modalidade = None
    _modalidades_map = {
        'pregão eletrônico': 'Pregão Eletrônico', 'pregao eletronico': 'Pregão Eletrônico',
        'pregão presencial': 'Pregão Presencial', 'pregao presencial': 'Pregão Presencial',
        'concorrência': 'Concorrência', 'concorrencia': 'Concorrência',
        'tomada de preços': 'Tomada de Preços', 'tomada de precos': 'Tomada de Preços',
        'convite': 'Convite', 'dispensa': 'Dispensa', 'inexigibilidade': 'Inexigibilidade',
    }
    msg_lower_mod = message.lower()
    for chave, valor in _modalidades_map.items():
        if chave in msg_lower_mod:
            modalidade = valor
            break

    # Detectar tipo de produto da mensagem
    tipo_produto = None
    _tipos_map = {
        'reagente': 'Reagentes', 'equipamento': 'Equipamentos', 'comodato': 'Comodato',
        'aluguel': 'Aluguel', 'locação': 'Aluguel', 'locacao': 'Aluguel',
        'insumo': 'Insumos Hospitalares', 'informática': 'Informática', 'informatica': 'Informática',
        'rede': 'Redes', 'mobiliário': 'Mobiliário', 'mobiliario': 'Mobiliário',
    }
    for chave, valor in _tipos_map.items():
        if f'tipo {chave}' in msg_lower_mod or f'do tipo {chave}' in msg_lower_mod:
            tipo_produto = valor
            break

    # Detectar origem da mensagem
    origem = None
    _origens_map = {
        'hospital': 'Hospital', 'universidade': 'Universidade', 'lacen': 'LACEN',
        'força armada': 'Força Armada', 'forca armada': 'Força Armada',
        'autarquia': 'Autarquia', 'municipal': 'Municipal', 'estadual': 'Estadual',
        'federal': 'Federal', 'centro de pesquisa': 'Centros de Pesquisas',
        'fundação de pesquisa': 'Fundações de Pesquisa', 'fundacao de pesquisa': 'Fundações de Pesquisa',
    }
    for chave, valor in _origens_map.items():
        if f'origem {chave}' in msg_lower_mod or f'de origem {chave}' in msg_lower_mod:
            origem = valor
            break

    print(f"[BUSCA] Termo final: '{termo}', Fonte: '{fonte}', UF: '{uf}', Modalidade: '{modalidade}', Tipo: '{tipo_produto}', Origem: '{origem}', Score: '{tipo_score}' (limite={limite_score_profundo})")

    # ========== PASSO 1: Buscar editais em MÚLTIPLAS FONTES ==========
    resultado = _buscar_editais_multifonte(
        termo=termo, user_id=user_id, uf=uf, incluir_encerrados=incluir_encerrados,
        dias_busca=dias_busca, fonte=fonte,
        modalidade=modalidade, tipo_produto=tipo_produto, origem=origem,
    )
    editais = resultado.get("editais", [])
    fontes_consultadas = resultado.get("fontes_consultadas", [])
    erros_fontes = resultado.get("erros") or []

    if not editais:
        fontes_str = ', '.join(fontes_consultadas) if fontes_consultadas else 'nenhuma fonte disponível'
        response = f"""**Busca realizada:** {termo}
**Fontes consultadas:** {fontes_str}

⚠️ Nenhum edital encontrado para '{termo}'.

**Sugestões:**
- Tente termos mais específicos (ex: "monitor LCD 24 polegadas")
- Verifique se há editais salvos: "liste meus editais"
- Cadastre mais fontes de editais: "cadastre a fonte BEC-SP"
"""
        if erros_fontes:
            response += f"\n**Erros nas fontes:** {'; '.join(erros_fontes)}\n"
        return response, resultado

    # ========== PASSO 2: Calcular score de aderência (se solicitado) ==========
    aviso_produtos = None
    if tipo_score == "rapido" and editais:
        print(f"[APP] Score RAPIDO para {len(editais)} editais...")
        resultado_score = tool_calcular_score_aderencia(editais, user_id, empresa_id=empresa_id)
        if resultado_score.get("success"):
            editais_com_score = resultado_score.get("editais_com_score", editais)
            aviso_produtos = resultado_score.get("aviso")
        else:
            editais_com_score = editais

    elif tipo_score == "hibrido" and editais:
        print(f"[APP] Score HIBRIDO para {len(editais)} editais (profundo nos top {limite_score_profundo})...")
        # Passo 1: Score rápido em todos
        resultado_score = tool_calcular_score_aderencia(editais, user_id, empresa_id=empresa_id)
        if resultado_score.get("success"):
            editais_com_score = resultado_score.get("editais_com_score", editais)
            aviso_produtos = resultado_score.get("aviso")
        else:
            editais_com_score = editais
        # Passo 2: Ordenar por score, pegar top N
        editais_com_score.sort(key=lambda x: x.get("score_tecnico", 0), reverse=True)
        top_n = editais_com_score[:limite_score_profundo]
        rest = editais_com_score[limite_score_profundo:]
        # Passo 3: Score profundo nos top N
        top_n = _calcular_score_profundo(top_n, user_id, empresa_id)
        editais_com_score = top_n

    elif tipo_score == "profundo" and editais:
        print(f"[APP] Score PROFUNDO direto em {min(len(editais), limite_score_profundo)} editais...")
        target = editais[:limite_score_profundo]
        target = _calcular_score_profundo(target, user_id, empresa_id)
        editais_com_score = target

    elif tipo_score == "nenhum":
        print(f"[APP] Busca SIMPLES (sem score) - {len(editais)} editais encontrados")
        editais_com_score = editais
    else:
        editais_com_score = editais

    # ========== PASSO 3: Formatar resposta ==========
    total_encontrados = len(editais_com_score)

    fontes_str = ', '.join(fontes_consultadas) if fontes_consultadas else fonte
    _modos_label = {
        "nenhum": "listagem simples (sem score)",
        "rapido": "com score rápido de aderência",
        "hibrido": f"com score híbrido (rápido + profundo nos top {limite_score_profundo})",
        "profundo": f"com score profundo (6 dimensões) em {min(total_encontrados, limite_score_profundo)} editais",
    }
    modo_busca = _modos_label.get(tipo_score, "com análise de aderência")
    response = f"""**Busca realizada:** {termo}
**Fontes consultadas:** {fontes_str}
**Modo:** {modo_busca}
**Resultados:** {total_encontrados} edital(is) encontrado(s)

"""

    if aviso_produtos:
        response += f"⚠️ {aviso_produtos}\n\n"

    # Ordenar: abertos primeiro (por encerramento mais próximo), encerrados no final
    from datetime import datetime as _dt_chat
    def _sort_key_chat(e):
        encerrado = e.get("encerrado", False)
        d = e.get("data_encerramento") or e.get("data_abertura") or ""
        dt = _dt_chat(2099, 12, 31)
        for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = _dt_chat.strptime(d[:19], fmt)
                break
            except (ValueError, TypeError):
                continue
        # Encerrados vão para o final (1), abertos primeiro (0)
        return (1 if encerrado else 0, dt)
    editais_com_score.sort(key=_sort_key_chat)

    # Separar por recomendação — todos os editais, sem limite
    participar = [e for e in editais_com_score if e.get('recomendacao') == 'PARTICIPAR']
    avaliar = [e for e in editais_com_score if e.get('recomendacao') == 'AVALIAR']
    nao_participar = [e for e in editais_com_score if e.get('recomendacao') == 'NÃO PARTICIPAR']
    sem_score = [e for e in editais_com_score if not e.get('recomendacao')]

    def formatar_edital(ed, i):
        """Formata um edital para exibição com botões de ação"""
        numero = ed.get('numero', 'N/A')
        orgao = ed.get('orgao', 'N/A')
        uf_ed = ed.get('uf', '')
        cidade = ed.get('cidade', '')
        local = f"{cidade}/{uf_ed}" if cidade and uf_ed else (uf_ed or cidade or 'Brasil')
        objeto = ed.get('objeto', '')[:200]
        valor = ed.get('valor_referencia')
        valor_str = f"R$ {valor:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.') if valor else "Não informado"
        data_abertura = ed.get('data_abertura', 'Não informada')
        modalidade = ed.get('modalidade', 'N/A')
        url = ed.get('url', '')
        score = ed.get('score_tecnico')
        justificativa = ed.get('justificativa', '')
        fonte_edital = ed.get('fonte', '')
        pdf_url = ed.get('pdf_url', '')
        total_itens = ed.get('total_itens', 0)
        cnpj = ed.get('cnpj_orgao', '')
        ano = ed.get('ano_compra', '')
        seq = ed.get('seq_compra', '')
        dados_completos = ed.get('dados_completos', False)
        encerrado = ed.get('encerrado', False)

        # Badge de fonte com cor
        fonte_badge = ""
        if 'PNCP' in fonte_edital:
            fonte_badge = f"🟢 {fonte_edital}"
        elif 'ComprasNet' in fonte_edital:
            fonte_badge = f"🔵 {fonte_edital}"
        elif 'BEC' in fonte_edital:
            fonte_badge = f"🟡 {fonte_edital}"
        elif 'Scraper' in fonte_edital:
            fonte_badge = f"🟠 {fonte_edital}"
        else:
            fonte_badge = f"⚪ {fonte_edital}" if fonte_edital else ""

        # Badge de status (encerrado ou aberto)
        status_badge = "🔴 ENCERRADO" if encerrado else ""

        texto = f"---\n"
        texto += f"### {i}. [{fonte_badge}] {numero}"
        if score is not None:
            texto += f" | Score: **{score:.0f}%**"
        if status_badge:
            texto += f" | {status_badge}"
        texto += "\n"
        texto += f"**Órgão:** {orgao} ({local})\n"
        texto += f"**Modalidade:** {modalidade}\n"
        texto += f"**Valor estimado:** {valor_str}\n"
        texto += f"**Data abertura:** {data_abertura}\n"
        if total_itens > 0:
            texto += f"**Itens:** {total_itens} item(ns)\n"
        if dados_completos:
            texto += f"**Dados:** ✅ Completos (PNCP)\n"
        texto += f"**Objeto:** {objeto}\n"
        if justificativa:
            texto += f"\n**Análise:** {justificativa}\n"

        # Score profundo (6 dimensões) se disponível
        score_profundo = ed.get('score_profundo')
        if score_profundo:
            sp_scores = score_profundo.get('scores', {})
            decisao = score_profundo.get('decisao', 'AVALIAR')
            decisao_icon = "✅" if decisao == "GO" else ("❌" if decisao == "NO-GO" else "⚠️")
            texto += f"\n**Score Profundo:** {decisao_icon} **{decisao}** (Geral: {score_profundo.get('score_geral', 0)}%)\n"
            texto += f"| Dimensão | Score |\n|---|---|\n"
            for dim_key, dim_label in [('tecnico','Técnico'), ('documental','Documental'), ('complexidade','Complexidade'),
                                       ('juridico','Jurídico'), ('logistico','Logístico'), ('comercial','Comercial')]:
                val = sp_scores.get(dim_key, 0)
                texto += f"| {dim_label} | {val}% |\n"
            sp_just = score_profundo.get('justificativa', '')
            if sp_just:
                texto += f"\n{sp_just}\n"
            positivos = score_profundo.get('pontos_positivos', [])
            atencao = score_profundo.get('pontos_atencao', [])
            if positivos:
                texto += f"\n**Pontos positivos:** " + "; ".join(positivos[:3]) + "\n"
            if atencao:
                texto += f"**Pontos de atenção:** " + "; ".join(atencao[:3]) + "\n"

        # Botões de ação
        texto += f"\n"
        if url:
            texto += f"🔗 [Acessar Portal]({url}) "

        # Botão PDF - usar proxy local para visualização inline
        # URL absoluta do backend (porta 5007)
        backend_url = "http://localhost:5007"
        if cnpj and ano and seq:
            # URL do proxy local que permite visualização no navegador
            proxy_url = f"{backend_url}/api/proxy/pdf/pncp/{cnpj}/{ano}/{seq}"
            texto += f"| 📄 [Ver PDF]({proxy_url}) "
            texto += f"| ⬇️ [Baixar PDF]({proxy_url}?download=true) "
        elif pdf_url:
            # Se tem pdf_url mas não tem dados PNCP, usa direto (com fallback)
            texto += f"| 📄 [Ver PDF]({pdf_url}) "
            texto += f"| ⬇️ [Baixar PDF]({pdf_url}?download=true) "

        texto += "\n\n"
        return texto

    contador = 1

    # Editais recomendados (PARTICIPAR)
    if participar:
        response += "## ✅ RECOMENDADOS PARA PARTICIPAR\n\n"
        for ed in participar:
            response += formatar_edital(ed, contador)
            contador += 1

    # Editais para avaliar
    if avaliar:
        response += "## ⚠️ AVALIAR PARTICIPAÇÃO\n\n"
        for ed in avaliar:
            response += formatar_edital(ed, contador)
            contador += 1

    # Editais não recomendados
    if nao_participar:
        response += "## ❌ NÃO RECOMENDADOS\n\n"
        for ed in nao_participar:
            response += formatar_edital(ed, contador)
            contador += 1

    # Sem score (sem produtos cadastrados)
    if sem_score:
        response += "## 📋 EDITAIS ENCONTRADOS\n\n"
        for ed in sem_score:
            response += formatar_edital(ed, contador)
            contador += 1

    # ========== PASSO 4: Oferecer salvamento ==========
    qtd_participar = len(participar)
    qtd_avaliar = len(avaliar)
    qtd_recomendados = qtd_participar + qtd_avaliar

    if tipo_score != "nenhum" and qtd_recomendados > 0:
        # Busca COM score - mostrar opções por recomendação
        response += f"\n---\n"
        response += f"## 💾 Deseja salvar os editais?\n\n"
        response += f"Encontrei **{qtd_recomendados} edital(is)** recomendado(s):\n"
        if qtd_participar > 0:
            response += f"- ✅ {qtd_participar} para PARTICIPAR\n"
        if qtd_avaliar > 0:
            response += f"- ⚠️ {qtd_avaliar} para AVALIAR\n"
        response += f"\n"

        # Botões de ação (marcação especial para o frontend)
        response += f"<!-- BOTOES_SALVAR -->\n"
        response += f"[[btn:salvar_recomendados:💾 Salvar Recomendados ({qtd_recomendados})]]\n"
        if qtd_participar > 0 and qtd_avaliar > 0:
            response += f"[[btn:salvar_participar:✅ Salvar só PARTICIPAR ({qtd_participar})]]\n"
        response += f"[[btn:salvar_todos:📋 Salvar Todos ({len(editais_com_score)})]]\n"
        response += f"<!-- /BOTOES_SALVAR -->\n\n"

        response += f"*Ou digite: \"salvar editais\", \"salvar recomendados\", \"salvar edital PE-2026/001\"*\n"

    elif tipo_score == "nenhum" and len(editais_com_score) > 0:
        # Busca SEM score - oferecer salvar todos
        response += f"\n---\n"
        response += f"## 💾 Deseja salvar os editais?\n\n"
        response += f"Encontrei **{len(editais_com_score)} edital(is)**.\n\n"

        # Botões de ação
        response += f"<!-- BOTOES_SALVAR -->\n"
        response += f"[[btn:salvar_todos:💾 Salvar Todos ({len(editais_com_score)})]]\n"
        response += f"<!-- /BOTOES_SALVAR -->\n\n"

        response += f"*Ou digite: \"salvar editais\", \"salvar todos\", \"salvar edital [NÚMERO]\"*\n"

    # Adicionar editais ao resultado para possível salvamento posterior
    resultado["editais_com_score"] = editais_com_score
    resultado["editais_recomendados"] = participar + avaliar
    resultado["editais_participar"] = participar
    resultado["editais_avaliar"] = avaliar

    return response, resultado


def processar_buscar_links_editais(message: str, user_id: str):
    """
    Processa ação: Retornar links de editais em uma área.
    Retorna links formatados para o usuário clicar.
    """
    import re

    # Extrair termo/área da mensagem
    termo = None

    # Padrões comuns
    padroes = [
        r'links?\s+(?:para\s+)?(?:os\s+)?editais?\s+(?:na\s+|da\s+|de\s+)?(?:área|area)\s+(.+)',
        r'links?\s+(?:de\s+)?editais?\s+(?:de\s+|para\s+|em\s+)?(.+)',
        r'editais?\s+(?:de\s+|para\s+|em\s+|na\s+área\s+)?(.+)',
        r'busca.+links?\s+(.+)',
        r'(?:retorne|mostre|liste)\s+(?:os\s+)?links?\s+(?:para\s+|de\s+)?(.+)',
    ]

    msg_lower = message.lower()
    for padrao in padroes:
        match = re.search(padrao, msg_lower, re.IGNORECASE)
        if match:
            termo = match.group(1).strip()
            # Limpar palavras desnecessárias
            palavras_remover = ['por favor', 'obrigado', 'pncp', 'web', 'internet']
            for p in palavras_remover:
                termo = termo.replace(p, '').strip()
            break

    # Fallback: usar toda a mensagem após limpeza
    if not termo:
        palavras_ignorar = ['retorne', 'mostre', 'liste', 'busque', 'links', 'link', 'editais',
                           'edital', 'para', 'os', 'de', 'da', 'do', 'na', 'no', 'área', 'area']
        palavras = msg_lower.split()
        termos = [p for p in palavras if p not in palavras_ignorar and len(p) > 2]
        termo = ' '.join(termos) if termos else "equipamentos"

    print(f"[LINKS] Buscando links para área: '{termo}'")

    # Chamar a função de busca de links
    resultado = tool_buscar_links_editais(termo, user_id=user_id)

    if resultado.get("success"):
        return resultado.get("texto", "Nenhum resultado"), resultado
    else:
        return f"❌ Erro ao buscar links: {resultado.get('error', 'Erro desconhecido')}", resultado


def processar_buscar_edital_numero(message: str, user_id: str, buscar_apenas_banco: bool = False):
    """
    Processa busca de um edital específico pelo número.

    Args:
        message: Mensagem do usuário contendo o número do edital
        user_id: ID do usuário
        buscar_apenas_banco: Se True, busca APENAS no banco local. Se False, busca no banco e depois na web.

    Returns:
        Tuple (response_text, resultado)
    """
    empresa_id = get_current_empresa_id()
    import re
    import requests

    # Detectar se é busca no banco ou na web
    msg_lower = message.lower()
    busca_local = any(p in msg_lower for p in ["no banco", "cadastrado", "salvo", "no sistema", "banco de dados",
                                                "tenho o edital", "tenho edital", "já tenho", "ja tenho"])

    # Se especificou banco na mensagem, força busca local
    if busca_local:
        buscar_apenas_banco = True

    # Extrair número do edital da mensagem
    # Padrões: PE-001/2026, PE0013/2025, PE 050/2025, 90186/2025, nº 123, número 456
    padroes = [
        r'PE[-\s]?\d+[/\-]?\d*',  # PE-001/2026, PE0013/2025, PE 050/2025
        r'[Pp]reg[aã]o\s*(?:n[ºo°]?\s*)?\d+[/\-]?\d*',  # Pregão nº 123/2025
        r'[Ee]dital\s*(?:n[ºo°]?\s*)?\d+[/\-]?\d*',  # Edital nº 123/2025
        r'\d{3,}[/\-]\d{4}',  # 90186/2025, 050/2025
        r'n[ºo°]\s*\d+[/\-]?\d*',  # nº 123/2025
    ]

    numero_edital = None
    for padrao in padroes:
        match = re.search(padrao, message, re.IGNORECASE)
        if match:
            numero_edital = match.group().strip()
            # Limpar prefixos comuns que não fazem parte do número
            numero_edital = re.sub(r'^(edital|pregão|pregao|pe|nº|no|n°)\s*', '', numero_edital, flags=re.IGNORECASE).strip()
            break

    if not numero_edital:
        return """❌ **Não consegui identificar o número do edital.**

Por favor, informe o número no formato:
- "Busque o edital PE-001/2026 no banco"
- "Busque o edital PE-001/2026 no PNCP"
- "Tenho o edital PE-001/2026 cadastrado?"
""", None

    print(f"[BUSCA-EDITAL] Buscando edital: {numero_edital} | Apenas banco: {buscar_apenas_banco}")

    # 1. Verificar se está salvo no sistema
    from models import Edital
    from database import SessionLocal

    db = SessionLocal()
    try:
        edital_local = db.query(Edital).filter(
            Edital.numero.ilike(f"%{numero_edital}%"),
            Edital.empresa_id == empresa_id
        ).first()

        if edital_local:
            from models import EditalItem, EditalDocumento

            valor_ref = f"R$ {edital_local.valor_referencia:,.2f}" if edital_local.valor_referencia else '-'
            data_ab = edital_local.data_abertura.strftime('%d/%m/%Y %H:%M') if edital_local.data_abertura else '-'
            data_pub = edital_local.data_publicacao.strftime('%d/%m/%Y') if edital_local.data_publicacao else '-'
            objeto_texto = (edital_local.objeto or '')[:200]
            objeto_sufixo = '...' if len(edital_local.objeto or '') > 200 else ''

            response = f"""## ✅ Edital Encontrado no Sistema

### Dados Gerais
| Campo | Valor |
|-------|-------|
| **Número** | {edital_local.numero} |
| **Órgão** | {edital_local.orgao} |
| **UF/Cidade** | {edital_local.uf or '-'} / {edital_local.cidade or '-'} |
| **Modalidade** | {edital_local.modalidade or '-'} |
| **Status** | {edital_local.status or '-'} |
| **Valor Referência** | {valor_ref} |
| **Data Publicação** | {data_pub} |
| **Data Abertura** | {data_ab} |

### Objeto
{objeto_texto}{objeto_sufixo}

"""
            # Buscar itens do edital
            itens = db.query(EditalItem).filter(EditalItem.edital_id == edital_local.id).order_by(EditalItem.numero_item).all()
            if itens:
                response += f"### Itens ({len(itens)})\n"
                response += "| Item | Descrição | Qtd | Valor Total |\n"
                response += "|------|-----------|-----|-------------|\n"
                for item in itens:
                    desc = (item.descricao or '')[:50]
                    desc_sufixo = '...' if len(item.descricao or '') > 50 else ''
                    qtd = f"{item.quantidade:,.0f} {item.unidade_medida or ''}" if item.quantidade else '-'
                    valor = f"R$ {item.valor_total_estimado:,.2f}" if item.valor_total_estimado else '-'
                    response += f"| {item.numero_item or '-'} | {desc}{desc_sufixo} | {qtd} | {valor} |\n"
                response += "\n"

            # Verificar se tem PDF
            doc = db.query(EditalDocumento).filter(EditalDocumento.edital_id == edital_local.id).first()
            if doc and doc.path_arquivo:
                import os
                if os.path.exists(doc.path_arquivo):
                    response += f"### Documento\n"
                    response += f"📄 **{doc.nome_arquivo}** ({len(doc.texto_extraido or ''):,} caracteres extraídos)\n\n"
                else:
                    response += f"### Documento\n"
                    response += f"⚠️ PDF não disponível (arquivo removido)\n\n"

            # Dados PNCP
            if edital_local.cnpj_orgao:
                response += f"### Dados PNCP\n"
                response += f"- **CNPJ Órgão:** {edital_local.cnpj_orgao}\n"
                response += f"- **Nº PNCP:** {edital_local.numero_pncp or '-'}\n"
                response += f"- **Situação:** {edital_local.situacao_pncp or '-'}\n"
                response += f"- **SRP:** {'Sim' if edital_local.srp else 'Não'}\n\n"

            # URL
            if edital_local.url:
                response += f"### Link\n🔗 {edital_local.url}\n\n"

            response += f"""---
**Ações disponíveis:**
- Baixar PDF: "Baixe o PDF do edital {edital_local.numero}"
- Fazer perguntas: "Qual o prazo de entrega do edital {edital_local.numero}?"
- Calcular aderência: "Calcule aderência do produto X ao edital {edital_local.numero}"
"""
            return response, {"edital": edital_local.numero, "encontrado_local": True, "id": edital_local.id}

        # Se não encontrou no banco e é busca apenas local
        if buscar_apenas_banco:
            return f"""## ❌ Edital não encontrado no banco

O edital **{numero_edital}** não está cadastrado no sistema.

**Opções:**
- Buscar na web: "Busque o edital {numero_edital} no PNCP"
- Cadastrar manualmente: "Cadastre o edital {numero_edital}, órgão [ORGAO], objeto: [OBJETO]"
- Buscar por termo: "Busque editais de [TERMO] no PNCP"
""", {"numero": numero_edital, "encontrado": False}

    finally:
        db.close()

    # 2. Buscar no PNCP (apenas se não for busca exclusiva no banco)
    try:
        # Limpar número para busca
        numero_limpo = re.sub(r'[^\d/]', '', numero_edital)

        url = f"https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao"
        params = {
            "q": numero_edital,
            "pagina": 1,
            "tamanhoPagina": 10
        }

        response_api = requests.get(url, params=params, timeout=30)

        if response_api.status_code == 200:
            dados = response_api.json()
            resultados = dados.get("data", []) or dados.get("items", []) or []

            if resultados:
                response = f"## 🌐 Resultados da Web para: {numero_edital}\n\n"
                response += f"Encontrados: **{len(resultados)}** edital(is)\n\n"

                for i, ed in enumerate(resultados[:5], 1):
                    orgao = ed.get("orgaoEntidade", {}).get("razaoSocial", ed.get("nomeOrgao", "N/A"))
                    numero = ed.get("numeroControlePNCP", ed.get("numero", "N/A"))
                    objeto = ed.get("objetoCompra", ed.get("objeto", "N/A"))[:150]

                    response += f"""### {i}. {numero}
- **Órgão:** {orgao}
- **Objeto:** {objeto}...
- **Modalidade:** {ed.get("modalidadeNome", "N/A")}

"""

                response += "\n---\n*Para salvar, use: \"Salve os editais encontrados\"*"
                return response, {"editais": resultados, "termo": numero_edital}

        # Se não encontrou na API principal, tentar busca genérica
        return processar_buscar_editais(f"edital {numero_edital}", user_id, calcular_score=False)

    except Exception as e:
        print(f"[BUSCA-EDITAL] Erro na API PNCP: {e}")
        # Fallback para busca genérica
        return processar_buscar_editais(f"edital {numero_edital}", user_id, calcular_score=False)


def processar_listar_produtos(message: str, user_id: str):
    empresa_id = get_current_empresa_id()
    """Processa ação: Listar produtos do usuário"""
    resultado = tool_listar_produtos(user_id, empresa_id=empresa_id)

    if resultado.get("success"):
        produtos = resultado.get("produtos", [])
        if produtos:
            response = f"**Seus produtos cadastrados:** {len(produtos)}\n\n"

            # Agrupar por categoria
            por_categoria = {}
            for p in produtos:
                cat = p.get("categoria", "outro")
                if cat not in por_categoria:
                    por_categoria[cat] = []
                por_categoria[cat].append(p)

            for cat, prods in sorted(por_categoria.items()):
                response += f"**[{cat.upper()}]**\n"
                for p in prods:
                    response += f"- {p['nome']} ({p.get('fabricante', 'N/A')} - {p.get('modelo', 'N/A')})\n"
                response += "\n"
        else:
            response = "Você não tem produtos cadastrados ainda. Faça upload de um manual PDF para cadastrar."
    else:
        response = f"Erro ao listar produtos: {resultado.get('error')}"

    return response, resultado


def processar_reprocessar_produto(message: str, user_id: str):
    empresa_id = get_current_empresa_id()
    """
    Reprocessa um produto para extrair especificações novamente.
    Útil quando a extração inicial falhou ou foi incompleta.
    """
    # Tentar identificar o produto na mensagem
    # Primeiro listar produtos do usuário
    produtos_resultado = tool_listar_produtos(user_id, empresa_id=empresa_id)

    if not produtos_resultado.get("success"):
        return "Erro ao buscar seus produtos.", produtos_resultado

    produtos = produtos_resultado.get("produtos", [])
    if not produtos:
        return "Você não tem produtos cadastrados para reprocessar.", {"success": False}

    # Tentar encontrar o produto mencionado na mensagem
    msg_lower = message.lower()
    produto_id = None
    produto_nome = None

    for p in produtos:
        nome_lower = p.get("nome", "").lower()
        modelo_lower = (p.get("modelo") or "").lower()

        # Verificar se nome ou modelo está na mensagem
        if nome_lower and any(parte in msg_lower for parte in nome_lower.split()[:3]):
            produto_id = p.get("id")
            produto_nome = p.get("nome")
            break
        if modelo_lower and modelo_lower in msg_lower:
            produto_id = p.get("id")
            produto_nome = p.get("nome")
            break

    # Se não encontrou, usar o último produto cadastrado
    if not produto_id:
        ultimo = produtos[-1]
        produto_id = ultimo.get("id")
        produto_nome = ultimo.get("nome")

    # Reprocessar
    print(f"[APP] Reprocessando produto: {produto_nome} ({produto_id})")
    resultado = tool_reprocessar_produto(produto_id, user_id, empresa_id=empresa_id)

    if resultado.get("success"):
        specs = resultado.get("specs", [])
        response = f"""## 🔄 Produto Reprocessado!

**Produto:** {resultado.get('produto_nome', produto_nome)}
**ID:** {produto_id}

### Especificações Extraídas ({resultado.get('specs_extraidas', 0)} encontradas):

"""
        for spec in specs[:30]:
            nome = spec.get('nome_especificacao', 'N/A')
            valor = spec.get('valor', 'N/A')
            unidade = spec.get('unidade', '')
            response += f"- **{nome}:** {valor} {unidade}\n"

        if len(specs) > 30:
            response += f"\n... e mais {len(specs) - 30} especificações.\n"

        response += "\n✅ Produto atualizado e pronto para calcular aderência!"
    else:
        response = f"❌ Erro ao reprocessar: {resultado.get('error')}"

    return response, resultado


def processar_excluir_edital(message: str, user_id: str):
    empresa_id = get_current_empresa_id()
    """
    Processa ação: Excluir edital(is).
    Identifica editais por número, ID ou palavras-chave na mensagem.
    """
    from tools import tool_excluir_edital, tool_excluir_editais_multiplos, tool_listar_editais

    msg_lower = message.lower()

    # Verificar se é exclusão de todos
    if "todos" in msg_lower:
        editais_resultado = tool_listar_editais(user_id, empresa_id=empresa_id)
        if not editais_resultado.get("success") or not editais_resultado.get("editais"):
            return "Você não tem editais salvos para excluir.", {"success": False}

        edital_ids = [e["id"] for e in editais_resultado.get("editais", [])]
        resultado = tool_excluir_editais_multiplos(edital_ids, user_id, empresa_id=empresa_id)

        if resultado.get("success"):
            return f"✅ {resultado.get('excluidos', 0)} edital(is) excluído(s) com sucesso!", resultado
        else:
            return f"❌ Erro ao excluir editais: {resultado.get('error')}", resultado

    # Listar editais para identificar qual excluir
    editais_resultado = tool_listar_editais(user_id, empresa_id=empresa_id)
    if not editais_resultado.get("success"):
        return "Erro ao buscar seus editais.", editais_resultado

    editais = editais_resultado.get("editais", [])
    if not editais:
        return "Você não tem editais salvos para excluir.", {"success": False}

    # Tentar encontrar edital por número ou ID na mensagem
    edital_a_excluir = None
    for ed in editais:
        numero = ed.get("numero", "").lower()
        edital_id = ed.get("id", "")

        if numero and numero in msg_lower:
            edital_a_excluir = ed
            break
        if edital_id[:8].lower() in msg_lower:
            edital_a_excluir = ed
            break

    if not edital_a_excluir:
        # Mostrar lista de editais para o usuário escolher
        response = "**Qual edital você deseja excluir?**\n\nEditais salvos:\n"
        for i, ed in enumerate(editais[:10], 1):
            response += f"{i}. **{ed.get('numero')}** - {ed.get('orgao', 'N/A')[:40]}\n"
        response += "\nDigite: 'excluir edital [número]' para confirmar."
        return response, {"success": False, "editais": editais}

    # Excluir o edital encontrado
    resultado = tool_excluir_edital(edital_a_excluir["id"], user_id, empresa_id=empresa_id)

    if resultado.get("success"):
        return f"✅ Edital **{edital_a_excluir.get('numero')}** excluído com sucesso!", resultado
    else:
        return f"❌ Erro ao excluir edital: {resultado.get('error')}", resultado


def processar_excluir_produto(message: str, user_id: str):
    empresa_id = get_current_empresa_id()
    """
    Processa ação: Excluir produto.
    Identifica produto por nome ou ID na mensagem.
    """
    from tools import tool_excluir_produto, tool_listar_produtos

    msg_lower = message.lower()

    # Listar produtos para identificar qual excluir
    produtos_resultado = tool_listar_produtos(user_id, empresa_id=empresa_id)
    if not produtos_resultado.get("success"):
        return "Erro ao buscar seus produtos.", produtos_resultado

    produtos = produtos_resultado.get("produtos", [])
    if not produtos:
        return "Você não tem produtos cadastrados para excluir.", {"success": False}

    # Verificar se é exclusão de todos
    if "todos" in msg_lower:
        excluidos = 0
        erros = 0
        for p in produtos:
            resultado = tool_excluir_produto(p["id"], user_id, empresa_id=empresa_id)
            if resultado.get("success"):
                excluidos += 1
            else:
                erros += 1
        return f"✅ {excluidos} produto(s) excluído(s)!" + (f" ({erros} erros)" if erros else ""), {"success": True, "excluidos": excluidos}

    # Tentar encontrar produto por nome na mensagem
    produto_a_excluir = None
    for p in produtos:
        nome = p.get("nome", "").lower()
        modelo = (p.get("modelo") or "").lower()
        produto_id = p.get("id", "")

        # Verificar se nome, modelo ou ID está na mensagem
        if nome and any(parte in msg_lower for parte in nome.split()[:3]):
            produto_a_excluir = p
            break
        if modelo and modelo in msg_lower:
            produto_a_excluir = p
            break
        if produto_id[:8].lower() in msg_lower:
            produto_a_excluir = p
            break

    if not produto_a_excluir:
        # Mostrar lista de produtos para o usuário escolher
        response = "**Qual produto você deseja excluir?**\n\nProdutos cadastrados:\n"
        for i, p in enumerate(produtos[:10], 1):
            response += f"{i}. **{p.get('nome')}** ({p.get('fabricante', 'N/A')})\n"
        response += "\nDigite: 'excluir produto [nome]' para confirmar."
        return response, {"success": False, "produtos": produtos}

    # Excluir o produto encontrado
    resultado = tool_excluir_produto(produto_a_excluir["id"], user_id, empresa_id=empresa_id)

    if resultado.get("success"):
        return f"✅ Produto **{produto_a_excluir.get('nome')}** excluído com sucesso!", resultado
    else:
        return f"❌ Erro ao excluir produto: {resultado.get('error')}", resultado


def processar_atualizar_edital(message: str, user_id: str):
    empresa_id = get_current_empresa_id()
    """
    Processa ação: Atualizar/Editar edital.
    Usa IA para extrair o que o usuário quer alterar.
    """
    from tools import tool_atualizar_edital, tool_listar_editais

    # Listar editais para identificar qual atualizar
    editais_resultado = tool_listar_editais(user_id, empresa_id=empresa_id)
    if not editais_resultado.get("success"):
        return "Erro ao buscar seus editais.", editais_resultado

    editais = editais_resultado.get("editais", [])
    if not editais:
        return "Você não tem editais salvos para editar.", {"success": False}

    msg_lower = message.lower()

    # Tentar encontrar edital por número na mensagem
    edital_a_editar = None
    for ed in editais:
        numero = ed.get("numero", "").lower()
        if numero and numero in msg_lower:
            edital_a_editar = ed
            break

    if not edital_a_editar:
        # Usar o último edital
        edital_a_editar = editais[0]

    # Extrair campos a atualizar usando IA
    prompt = f"""Analise a mensagem do usuário e extraia quais campos do edital ele quer alterar.

Mensagem: "{message}"

Campos possíveis: numero, orgao, objeto, modalidade, status, valor_referencia, data_abertura, url

Status possíveis: novo, analisando, participar, nao_participar, proposta_enviada, ganho, perdido, cancelado
Modalidades: pregao_eletronico, pregao_presencial, concorrencia, tomada_precos, convite, dispensa, inexigibilidade

IMPORTANTE: Se a mensagem contém uma URL (http:// ou https://), extraia como campo "url".

Retorne JSON com apenas os campos a alterar:
{{"campo1": "novo_valor", "campo2": "novo_valor"}}

Se não identificar campos claros, retorne {{}}
"""

    try:
        resposta_ia = call_deepseek([{"role": "user", "content": prompt}], max_tokens=100, model_override="deepseek-chat")
        import json
        import re
        json_match = re.search(r'\{[\s\S]*?\}', resposta_ia)
        if json_match:
            campos = json.loads(json_match.group())
        else:
            campos = {}
    except:
        campos = {}

    if not campos:
        # Mostrar edital atual e pedir para especificar
        response = f"""**Editar Edital: {edital_a_editar.get('numero')}**

Dados atuais:
- **Número:** {edital_a_editar.get('numero')}
- **Órgão:** {edital_a_editar.get('orgao')}
- **Status:** {edital_a_editar.get('status')}
- **Modalidade:** {edital_a_editar.get('modalidade')}
- **URL:** {edital_a_editar.get('url') or 'Não cadastrada'}

Por favor, especifique o que deseja alterar. Exemplos:
- "alterar status para participar"
- "mudar órgão para Prefeitura de SP"
- "atualizar URL para https://exemplo.com/edital.pdf"
"""
        return response, {"success": False, "edital": edital_a_editar}

    # Aplicar atualizações
    resultado = tool_atualizar_edital(
        edital_id=edital_a_editar["id"],
        user_id=user_id,
        **campos
    )

    if resultado.get("success"):
        edital_atualizado = resultado.get("edital", {})
        response = f"""✅ Edital **{edital_atualizado.get('numero')}** atualizado!

Novos dados:
- **Número:** {edital_atualizado.get('numero')}
- **Órgão:** {edital_atualizado.get('orgao')}
- **Status:** {edital_atualizado.get('status')}
- **Modalidade:** {edital_atualizado.get('modalidade')}
"""
        return response, resultado
    else:
        return f"❌ Erro ao atualizar edital: {resultado.get('error')}", resultado


def processar_cadastrar_produto(message: str, user_id: str):
    """
    Cadastra produto manualmente a partir dos dados enviados pelo formulário do Portfolio.
    Formato: Cadastre manualmente o produto: Nome="X", Fabricante="Y", Modelo="Z",
             Categoria="W", SubclasseId="uuid", NCM="N". Especificacoes: campo=valor[unidade]{tipo}, ...
    """
    import re
    from decimal import Decimal, InvalidOperation
    db = get_db()
    try:
        empresa_id = get_current_empresa_id()

        # Parsear campos do prompt
        def extrair(campo):
            m = re.search(rf'{campo}="([^"]*)"', message)
            return m.group(1).strip() if m else None

        nome = extrair("Nome")
        fabricante = extrair("Fabricante")
        modelo = extrair("Modelo")
        categoria = extrair("Categoria")
        subclasse_id = extrair("SubclasseId")
        ncm = extrair("NCM")

        if not nome:
            return "Informe ao menos o nome do produto. Ex: Cadastre o produto: Nome=\"Analisador X\"", {"error": "nome_obrigatorio"}

        # Validar categoria
        categorias_validas = ['equipamento', 'reagente', 'insumo_hospitalar', 'insumo_laboratorial',
                             'informatica', 'redes', 'mobiliario', 'eletronico', 'comodato', 'outro']
        if not categoria or categoria not in categorias_validas:
            categoria = "outro"

        # Validar subclasse_id se fornecido
        if subclasse_id:
            sub_exists = db.query(SubclasseProduto).filter(SubclasseProduto.id == subclasse_id).first()
            if not sub_exists:
                subclasse_id = None  # Ignorar ID inválido

        # ===== UPSERT por (nome + fabricante + modelo) normalizado =====
        # Critério B: 3 campos juntos identificam um produto comercial.
        # Match: nome, fabricante e modelo normalizados (lowercase, sem acento, espaços colapsados).
        # Fallback: se fabricante OU modelo do existente são vazios E o existente tem o mesmo nome
        #          normalizado, faz match também — cobre o caso "user cadastrou só nome,
        #          IA traz nome+fab+modelo".
        # UPDATE: COALESCE — só preenche campos que estão vazios no existente. Nunca sobrescreve.
        import unicodedata as _ud
        def _norm(s):
            if not s: return ""
            s = _ud.normalize('NFKD', str(s)).encode('ASCII', 'ignore').decode('ASCII')
            s = re.sub(r'[\s\-_]+', ' ', s.lower()).strip()
            return s
        nome_n = _norm(nome)
        fab_n = _norm(fabricante)
        mod_n = _norm(modelo)

        existente = None
        candidatos = db.query(Produto).filter(Produto.empresa_id == empresa_id).all()
        # 1) tenta match estrito (nome+fab+modelo todos batendo)
        for c in candidatos:
            if _norm(c.nome) == nome_n and _norm(c.fabricante) == fab_n and _norm(c.modelo) == mod_n:
                existente = c
                break
        # 2) fallback: mesmo nome E (fabricante OU modelo do existente vazios)
        if not existente:
            for c in candidatos:
                if _norm(c.nome) == nome_n and (not _norm(c.fabricante) or not _norm(c.modelo)):
                    existente = c
                    break

        if existente:
            # UPDATE com COALESCE: só preenche o que está vazio
            campos_atualizados = []
            if not existente.fabricante and fabricante:
                existente.fabricante = fabricante; campos_atualizados.append("fabricante")
            if not existente.modelo and modelo:
                existente.modelo = modelo; campos_atualizados.append("modelo")
            if not existente.ncm and ncm:
                existente.ncm = ncm; campos_atualizados.append("ncm")
            if (not existente.subclasse_id) and subclasse_id:
                existente.subclasse_id = subclasse_id; campos_atualizados.append("subclasse_id")
            if (not existente.categoria or existente.categoria == "outro") and categoria and categoria != "outro":
                existente.categoria = categoria; campos_atualizados.append("categoria")
            db.flush()
            produto_id = existente.id
            produto = existente
            modo_operacao = "atualizado"
        else:
            # Criar produto novo
            produto = Produto(
                user_id=user_id,
                empresa_id=empresa_id,
                nome=nome,
                fabricante=fabricante,
                modelo=modelo,
                categoria=categoria,
                subclasse_id=subclasse_id,
                ncm=ncm,
                status_pipeline="cadastrado",
            )
            db.add(produto)
            db.flush()
            produto_id = produto.id
            modo_operacao = "criado"
            campos_atualizados = []

        # Parsear especificações com formato enriquecido: campo=valor[unidade]{tipo}
        specs_criadas = []
        specs_match = re.search(r'Especificacoes:\s*(.+)$', message)
        if specs_match:
            specs_str = specs_match.group(1)
            for par in specs_str.split(","):
                par = par.strip()
                if "=" in par:
                    campo, resto = par.split("=", 1)
                    campo = campo.strip()
                    resto = resto.strip()

                    # Extrair unidade [xxx] e tipo {xxx} do resto
                    unidade = None
                    tipo = "texto"
                    un_match = re.search(r'\[([^\]]+)\]', resto)
                    if un_match:
                        unidade = un_match.group(1)
                        resto = resto[:un_match.start()] + resto[un_match.end():]
                    tp_match = re.search(r'\{([^\}]+)\}', resto)
                    if tp_match:
                        tipo = tp_match.group(1)
                        resto = resto[:tp_match.start()] + resto[tp_match.end():]

                    valor = resto.strip()
                    if campo and valor:
                        # Converter valor numérico se tipo é numero/decimal
                        valor_numerico = None
                        if tipo in ("numero", "decimal"):
                            try:
                                valor_numerico = Decimal(valor.replace(",", "."))
                            except (InvalidOperation, ValueError):
                                pass

                        # UPSERT spec: se já existe spec com mesmo nome, atualiza valor;
                        # senão cria nova. Evita duplicar specs em re-processamento.
                        spec_existente = db.query(ProdutoEspecificacao).filter(
                            ProdutoEspecificacao.produto_id == produto_id,
                            ProdutoEspecificacao.nome_especificacao == campo
                        ).first()
                        if spec_existente:
                            spec_existente.valor = valor
                            if unidade: spec_existente.unidade = unidade
                            if valor_numerico is not None: spec_existente.valor_numerico = valor_numerico
                            specs_criadas.append(f"{campo}: {valor}{f' {unidade}' if unidade else ''} (atualizada)")
                        else:
                            spec = ProdutoEspecificacao(
                                produto_id=produto_id,
                                nome_especificacao=campo,
                                valor=valor,
                                unidade=unidade,
                                valor_numerico=valor_numerico,
                            )
                            db.add(spec)
                            specs_criadas.append(f"{campo}: {valor}{f' {unidade}' if unidade else ''}")

        db.commit()

        specs_text = ""
        if specs_criadas:
            specs_list = "\n".join([f"  - {s}" for s in specs_criadas])
            specs_text = f"\n\n**Especificacoes ({len(specs_criadas)}):**\n{specs_list}"

        subclasse_text = ""
        if subclasse_id:
            sub = db.query(SubclasseProduto).filter(SubclasseProduto.id == subclasse_id).first()
            subclasse_text = f"\n- **Subclasse:** {sub.nome if sub else subclasse_id}"

        # Mensagem reflete operação real (criado vs atualizado) — V4 fix observação #14 Arnaldo
        if modo_operacao == "atualizado":
            atualizados_text = ""
            if campos_atualizados:
                atualizados_text = f"\n- **Campos preenchidos:** {', '.join(campos_atualizados)}"
            response = f"""## Produto atualizado (já existia no portfolio)

- **Nome:** {nome}
- **ID existente:** {produto_id}{atualizados_text}{subclasse_text}
- **Fabricante:** {produto.fabricante or 'N/I'}
- **Modelo:** {produto.modelo or 'N/I'}
- **NCM:** {produto.ncm or 'N/I'}{specs_text}

A IA identificou que este produto já existia (match por nome+fabricante+modelo)
e completou apenas os campos que estavam vazios. Dados que voce ja tinha digitado
foram preservados."""
        else:
            response = f"""## Produto cadastrado com sucesso

- **Nome:** {nome}
- **Categoria:** {categoria}{subclasse_text}
- **Fabricante:** {fabricante or 'N/I'}
- **Modelo:** {modelo or 'N/I'}
- **NCM:** {ncm or 'N/I'}
- **Status:** cadastrado{specs_text}

O produto foi salvo no banco. Voce pode ver na aba "Meus Produtos" do Portfolio."""

        return response, {"success": True, "produto_id": produto_id, "nome": nome, "modo": modo_operacao, "campos_atualizados": campos_atualizados}

    except Exception as e:
        db.rollback()
        print(f"[ERRO] processar_cadastrar_produto: {e}")
        return f"Erro ao cadastrar produto: {str(e)}", {"error": str(e)}
    finally:
        db.close()


def processar_buscar_anvisa(message: str, user_id: str):
    """
    Busca registros de produtos na ANVISA via web search.
    Aceita número de registro ou nome do produto.
    Atualiza campo registro_anvisa e anvisa_status do produto se encontrar.
    """
    empresa_id = get_current_empresa_id()
    import re
    db = get_db()
    try:
        # Extrair número de registro ou nome do produto
        registro_match = re.search(r'(?:numero|nº|n°|registro)\s*[:\s]*(\d{8,15})', message, re.IGNORECASE)
        registro = registro_match.group(1) if registro_match else None

        # Extrair nome do produto
        nome_match = re.search(r'(?:produto|para o|para)\s+(.+?)(?:\s+na\s+anvisa|\s*$)', message, re.IGNORECASE)
        nome_produto = nome_match.group(1).strip() if nome_match else None

        if not registro and not nome_produto:
            # Tentar extrair qualquer número grande
            num_match = re.search(r'\b(\d{8,15})\b', message)
            if num_match:
                registro = num_match.group(1)
            else:
                # Extrair o que sobra após remover palavras de comando
                cleaned = re.sub(r'(?:busque?|registros?|anvisa|consulte?|do|da|de|o|a|na|no|para)\s*', '', message, flags=re.IGNORECASE).strip()
                if cleaned:
                    nome_produto = cleaned

        if not registro and not nome_produto:
            return "Informe o número do registro ANVISA ou o nome do produto para buscar.", {"error": "dados_insuficientes"}

        # Buscar via _web_search direto (sem filetype:pdf que tool_web_search adiciona)
        if registro:
            search_label = f"registro **{registro}**"
        else:
            search_label = f"produto **{nome_produto}**"

        # Query 1: busca direta com ANVISA
        query1 = f"{registro or nome_produto} registro ANVISA produto saude"
        print(f"[ANVISA] Buscando: {query1}")
        results = _web_search(query1, num_results=5)

        # Query 2: complementar
        query2 = f"ANVISA consulta produtos {registro or nome_produto} situação registro"
        print(f"[ANVISA] Buscando: {query2}")
        results2 = _web_search(query2, num_results=5)

        # Deduplicar por link
        seen_links = {r.get("link") for r in results}
        for r in results2:
            if r.get("link") not in seen_links:
                results.append(r)
                seen_links.add(r.get("link"))

        if not results:
            return f"Nenhum resultado encontrado na ANVISA para {search_label}. Tente com outro termo ou verifique o número do registro.", {"error": "sem_resultados"}

        # Tentar extrair número de registro dos resultados
        import re as re2
        registro_encontrado = registro
        if not registro_encontrado:
            for r in results:
                title_snippet = f"{r.get('title', '')} {r.get('snippet', '')}"
                match = re2.search(r'(?:registro|nº|n°)\s*(?:ANVISA\s*)?[:\s]*(\d{8,15})', title_snippet, re2.IGNORECASE)
                if not match:
                    match = re2.search(r'\b(\d{11,15})\b', title_snippet)
                if match:
                    registro_encontrado = match.group(1)
                    break

        # Tentar atualizar produto no banco
        produto_atualizado = None
        if registro_encontrado and nome_produto:
            produto = db.query(Produto).filter(
                Produto.empresa_id == empresa_id,
                Produto.nome.ilike(f"%{nome_produto}%")
            ).first()
            if produto:
                produto.registro_anvisa = registro_encontrado
                produto.anvisa_status = "ativo"
                db.commit()
                produto_atualizado = produto.nome
        elif registro_encontrado:
            produto = db.query(Produto).filter(
                Produto.empresa_id == empresa_id,
                Produto.registro_anvisa == None  # noqa: E711
            ).first()
            if produto:
                produto.registro_anvisa = registro_encontrado
                produto.anvisa_status = "ativo"
                db.commit()
                produto_atualizado = produto.nome

        # Formatar resposta
        links_text = ""
        for i, r in enumerate(results[:8]):
            title = r.get("title", "Sem título")
            url = r.get("link", "")
            snippet = r.get("snippet", "")[:120]
            links_text += f"\n{i+1}. [{title}]({url})\n   {snippet}\n"

        update_text = ""
        if produto_atualizado:
            update_text = f"\n\n✅ **Produto atualizado:** {produto_atualizado} → Registro ANVISA: {registro_encontrado}, Status: Ativo"
        elif registro_encontrado:
            update_text = f"\n\n📋 **Registro encontrado:** {registro_encontrado}"

        response = f"""## Resultados ANVISA para {search_label}

{links_text}
{update_text}

**Dica:** Acesse os links acima para verificar a situação do registro no portal da ANVISA."""

        return response, {"success": True, "results_count": len(results), "registro": registro_encontrado}

    except Exception as e:
        print(f"[ERRO] processar_buscar_anvisa: {e}")
        return f"Erro ao buscar ANVISA: {str(e)}", {"error": str(e)}
    finally:
        db.close()


def processar_atualizar_produto(message: str, user_id: str):
    """
    Processa ação: Atualizar/Editar produto.
    Usa IA para extrair o que o usuário quer alterar.
    """
    empresa_id = get_current_empresa_id()
    from tools import tool_atualizar_produto, tool_listar_produtos

    # Listar produtos para identificar qual atualizar
    produtos_resultado = tool_listar_produtos(user_id, empresa_id=empresa_id)
    if not produtos_resultado.get("success"):
        return "Erro ao buscar seus produtos.", produtos_resultado

    produtos = produtos_resultado.get("produtos", [])
    if not produtos:
        return "Você não tem produtos cadastrados para editar.", {"success": False}

    msg_lower = message.lower()

    # Tentar encontrar produto por nome na mensagem
    produto_a_editar = None
    for p in produtos:
        nome = p.get("nome", "").lower()
        if nome and any(parte in msg_lower for parte in nome.split()[:3]):
            produto_a_editar = p
            break

    if not produto_a_editar:
        # Usar o último produto
        produto_a_editar = produtos[-1]

    # Extrair campos a atualizar usando IA
    prompt = f"""Analise a mensagem do usuário e extraia quais campos do produto ele quer alterar.

Mensagem: "{message}"

Campos possíveis: nome, fabricante, modelo, categoria

Categorias: equipamento, reagente, insumo_hospitalar, insumo_laboratorial, informatica, redes, mobiliario, eletronico, outro

Retorne JSON com apenas os campos a alterar:
{{"campo1": "novo_valor", "campo2": "novo_valor"}}

Se não identificar campos claros, retorne {{}}
"""

    try:
        resposta_ia = call_deepseek([{"role": "user", "content": prompt}], max_tokens=100, model_override="deepseek-chat")
        import json
        import re
        json_match = re.search(r'\{[\s\S]*?\}', resposta_ia)
        if json_match:
            campos = json.loads(json_match.group())
        else:
            campos = {}
    except:
        campos = {}

    if not campos:
        # Mostrar produto atual e pedir para especificar
        response = f"""**Editar Produto: {produto_a_editar.get('nome')}**

Dados atuais:
- **Nome:** {produto_a_editar.get('nome')}
- **Fabricante:** {produto_a_editar.get('fabricante', 'N/A')}
- **Modelo:** {produto_a_editar.get('modelo', 'N/A')}
- **Categoria:** {produto_a_editar.get('categoria', 'N/A')}

Por favor, especifique o que deseja alterar. Exemplos:
- "alterar fabricante para Philips"
- "mudar categoria para equipamento"
"""
        return response, {"success": False, "produto": produto_a_editar}

    # Aplicar atualizações
    resultado = tool_atualizar_produto(
        produto_id=produto_a_editar["id"],
        user_id=user_id,
        **campos
    )

    if resultado.get("success"):
        produto_atualizado = resultado.get("produto", {})
        response = f"""✅ Produto **{produto_atualizado.get('nome')}** atualizado!

Novos dados:
- **Nome:** {produto_atualizado.get('nome')}
- **Fabricante:** {produto_atualizado.get('fabricante', 'N/A')}
- **Modelo:** {produto_atualizado.get('modelo', 'N/A')}
- **Categoria:** {produto_atualizado.get('categoria', 'N/A')}
"""
        return response, resultado
    else:
        return f"❌ Erro ao atualizar produto: {resultado.get('error')}", resultado


def processar_listar_fontes(message: str):
    """Processa ação: Listar fontes de editais"""
    resultado = tool_listar_fontes()

    if resultado.get("success"):
        fontes = resultado.get("fontes", [])
        if fontes:
            response = f"**Fontes de editais cadastradas:** {len(fontes)}\n\n"
            for f in fontes:
                status = "✅ Ativa" if f.get("ativo") else "❌ Inativa"
                response += f"- **{f['nome']}** ({f['tipo']}) {status}\n"
                response += f"  URL: {f.get('url_base', 'N/A')}\n"
                if f.get('descricao'):
                    response += f"  {f['descricao'][:100]}\n"
                response += "\n"
        else:
            response = "Nenhuma fonte de editais cadastrada."
    else:
        response = f"Erro ao listar fontes: {resultado.get('error')}"

    return response, resultado


def processar_listar_propostas(message: str, user_id: str):
    """Processa ação: Listar propostas geradas pelo usuário"""
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        propostas = db.query(Proposta).filter(
            Proposta.empresa_id == empresa_id
        ).order_by(Proposta.created_at.desc()).limit(20).all()

        if propostas:
            response = f"## 📝 Minhas Propostas ({len(propostas)})\n\n"
            for p in propostas:
                # Buscar edital e produto relacionados
                edital = db.query(Edital).filter(Edital.id == p.edital_id).first()
                produto = db.query(Produto).filter(Produto.id == p.produto_id).first()

                edital_num = edital.numero if edital else "N/A"
                produto_nome = produto.nome[:40] if produto else "N/A"
                preco = f"R$ {p.preco_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if p.preco_total else "N/A"
                data = p.created_at.strftime("%d/%m/%Y %H:%M") if p.created_at else "N/A"

                status_emoji = {
                    "rascunho": "📋",
                    "enviada": "📤",
                    "aceita": "✅",
                    "rejeitada": "❌"
                }.get(p.status, "📋")

                response += f"### {status_emoji} Proposta - Edital {edital_num}\n"
                response += f"- **Produto:** {produto_nome}\n"
                response += f"- **Preço:** {preco}\n"
                response += f"- **Status:** {p.status}\n"
                response += f"- **Data:** {data}\n"
                response += f"- **ID:** `{p.id[:8]}...`\n\n"

            resultado = {"success": True, "propostas": [p.to_dict() for p in propostas], "total": len(propostas)}
        else:
            response = "Você ainda não tem propostas geradas.\n\nPara gerar uma proposta, use:\n`Gere uma proposta do produto [NOME] para o edital [NUMERO] com preço R$ [VALOR]`"
            resultado = {"success": True, "propostas": [], "total": 0}

        return response, resultado

    except Exception as e:
        return f"Erro ao listar propostas: {str(e)}", {"success": False, "error": str(e)}
    finally:
        db.close()


def processar_buscar_editais_score(message: str, user_id: str):
    empresa_id = get_current_empresa_id()
    """Processa ação: Buscar editais + calcular score"""
    # Primeiro buscar editais (sem score — score é calculado abaixo separadamente)
    response_busca, resultado_busca = processar_buscar_editais(message, user_id, calcular_score=False)

    if not resultado_busca.get("success"):
        return response_busca, resultado_busca

    # Depois calcular score para cada edital com os produtos do usuário
    produtos = tool_listar_produtos(user_id, empresa_id=empresa_id)

    if not produtos.get("produtos"):
        return response_busca + "\n\n⚠️ Você não tem produtos cadastrados para calcular aderência.", resultado_busca

    response = response_busca + "\n\n**Análise de Aderência:**\n"
    analises = []

    for edital in resultado_busca.get("editais", [])[:3]:
        for produto in produtos.get("produtos", [])[:2]:
            analise = tool_calcular_aderencia(produto["id"], edital["id"], user_id, empresa_id=empresa_id)
            if analise.get("success"):
                analises.append(analise)
                response += f"\n- {produto['nome']} x {edital['numero']}: **{analise.get('score_tecnico', 0):.0f}%** - {analise.get('recomendacao', '')}"

    resultado_busca["analises"] = analises
    return response, resultado_busca


def processar_listar_editais(message: str, user_id: str):
    empresa_id = get_current_empresa_id()
    """Processa ação: Listar editais salvos"""
    # Extrair filtros da mensagem
    uf = None
    status = None

    message_lower = message.lower()
    if " sp" in message_lower or "são paulo" in message_lower:
        uf = "SP"
    elif " rj" in message_lower or "rio de janeiro" in message_lower:
        uf = "RJ"
    elif " mg" in message_lower or "minas gerais" in message_lower:
        uf = "MG"

    if "novo" in message_lower:
        status = "novo"
    elif "analisando" in message_lower:
        status = "analisando"

    # Verificar se usuário quer ver todos
    mostrar_todos = any(p in message_lower for p in ["todos", "all", "completo", "completa"])
    limite = 100 if mostrar_todos else 20  # Default 20, ou 100 se pedir todos

    resultado = tool_listar_editais(user_id, empresa_id=empresa_id, status=status, uf=uf)

    if resultado.get("success"):
        editais = resultado.get("editais", [])
        if editais:
            total = len(editais)
            editais_mostrar = editais[:limite]

            response = f"**Editais salvos:** {total}"
            if total > limite:
                response += f" (mostrando {limite})"
            response += "\n\n"

            for i, ed in enumerate(editais_mostrar, 1):
                fonte = ed.get('fonte', '')
                fonte_badge = ""
                if 'PNCP' in fonte:
                    fonte_badge = "🟢"
                elif 'ComprasNet' in fonte:
                    fonte_badge = "🔵"
                elif 'BEC' in fonte:
                    fonte_badge = "🟡"
                else:
                    fonte_badge = "⚪"

                response += f"{i}. **{ed['numero']}** ({ed['status']}) {fonte_badge} {fonte}\n"
                response += f"   {ed['orgao']} - {ed['uf'] or 'N/A'}\n"
                response += f"   {ed['objeto'][:80]}...\n"

                # Botões de ação
                botoes = []
                if ed.get('url'):
                    botoes.append(f"[🔗 Portal]({ed['url']})")

                # PDF - verificar se tem pdf_url ou dados PNCP
                pdf_url = ed.get('pdf_url')
                cnpj = ed.get('cnpj_orgao')
                ano = ed.get('ano_compra')
                seq = ed.get('seq_compra')

                if pdf_url:
                    botoes.append(f"[📄 Ver PDF]({pdf_url})")
                    botoes.append(f"[⬇️ Baixar]({pdf_url}?download=true)")
                elif cnpj and ano and seq:
                    pdf_api = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos/1"
                    botoes.append(f"[📄 Ver PDF]({pdf_api})")
                    botoes.append(f"[⬇️ Baixar]({pdf_api})")

                if botoes:
                    response += f"   {' | '.join(botoes)}\n"
                response += "\n"

            if total > limite:
                response += f"\n📋 *Mostrando {limite} de {total} editais. Digite 'listar todos editais' para ver todos.*"
        else:
            response = "Você não tem editais salvos ainda. Use 'Buscar editais' para encontrar oportunidades."
    else:
        response = f"Erro ao listar: {resultado.get('error')}"

    return response, resultado


def _encontrar_produto(produtos: list, message_lower: str):
    """Helper para encontrar produto por nome, modelo ou palavras-chave"""
    for p in produtos:
        nome_lower = (p.get("nome") or "").lower()
        modelo_lower = (p.get("modelo") or "").lower()
        fabricante_lower = (p.get("fabricante") or "").lower()

        # Match exato do nome
        if nome_lower in message_lower:
            return p
        # Match por modelo completo
        if modelo_lower and modelo_lower in message_lower:
            return p
        # Match por parte principal do modelo (primeira palavra significativa)
        if modelo_lower:
            modelo_parts = modelo_lower.split()
            for part in modelo_parts:
                if len(part) >= 5 and part in message_lower:
                    return p
        # Match por fabricante + qualquer parte do modelo
        if fabricante_lower in message_lower:
            if modelo_lower:
                for part in modelo_lower.split():
                    if len(part) >= 3 and part in message_lower:
                        return p
        # Match parcial: qualquer palavra significativa do nome (>5 chars)
        palavras = nome_lower.split()
        for palavra in palavras:
            if len(palavra) > 5 and palavra in message_lower:
                return p
    return None


def processar_calcular_aderencia(message: str, user_id: str):
    empresa_id = get_current_empresa_id()
    """Processa ação: Calcular aderência"""
    # Listar produtos e editais disponíveis
    produtos = tool_listar_produtos(user_id, empresa_id=empresa_id)
    editais = tool_listar_editais(user_id, empresa_id=empresa_id)

    if not produtos.get("produtos"):
        return "Você não tem produtos cadastrados. Faça upload de um manual primeiro.", {"status": "sem_produtos"}

    if not editais.get("editais"):
        return "Você não tem editais salvos. Busque editais primeiro.", {"status": "sem_editais"}

    # Tentar identificar produto e edital na mensagem
    produto_encontrado = None
    edital_encontrado = None

    message_lower = message.lower()

    # Buscar produto - várias estratégias de match
    produto_encontrado = _encontrar_produto(produtos.get("produtos", []), message_lower)

    for e in editais.get("editais", []):
        numero = e.get("numero") or ""
        if numero and numero.lower() in message_lower:
            edital_encontrado = e
            break

    if produto_encontrado and edital_encontrado:
        resultado = tool_calcular_aderencia(
            produto_encontrado["id"],
            edital_encontrado["id"],
            user_id,
            empresa_id=empresa_id
        )

        if resultado.get("success"):
            response = f"""## Análise de Aderência

**Produto:** {resultado.get('produto')}
**Edital:** {resultado.get('edital')}

### Score Técnico: {resultado.get('score_tecnico', 0):.1f}%

"""
            # Se tem requisitos cadastrados
            if resultado.get('requisitos_total', 0) > 0:
                response += f"""**Requisitos:**
- Total: {resultado.get('requisitos_total', 0)}
- Atendidos: {resultado.get('requisitos_atendidos', 0)}
- Parciais: {resultado.get('requisitos_parciais', 0)}
- Não atendidos: {resultado.get('requisitos_nao_atendidos', 0)}

"""
            # Justificativa (da análise via IA)
            if resultado.get('justificativa'):
                response += f"""**Análise:** {resultado.get('justificativa')}

"""
            # Recomendação com emoji
            recomendacao = resultado.get('recomendacao', '')
            if 'RECOMENDADO' in recomendacao and 'NAO' not in recomendacao:
                emoji = "✅"
            elif 'AVALIAR' in recomendacao:
                emoji = "⚠️"
            else:
                emoji = "❌"

            response += f"""### {emoji} Recomendação: {recomendacao}
"""
            return response, resultado

    # Se não identificou, mostrar opções
    response = "Para calcular aderência, informe o produto e o edital.\n\n"
    response += "**Seus produtos:**\n"
    for p in produtos.get("produtos", [])[:5]:
        response += f"- {p['nome']}\n"
    response += "\n**Seus editais:**\n"
    for e in editais.get("editais", [])[:5]:
        response += f"- {e['numero']} ({e['orgao']})\n"
    response += "\nExemplo: 'Analise o Mindray BS-240 para o edital PE-2024-001'"

    return response, {"status": "aguardando_selecao", "produtos": produtos.get("produtos"), "editais": editais.get("editais")}


def processar_gerar_proposta(message: str, user_id: str):
    empresa_id = get_current_empresa_id()
    """Processa ação: Gerar proposta"""
    # Similar ao calcular aderência, precisa identificar produto e edital
    produtos = tool_listar_produtos(user_id, empresa_id=empresa_id)
    editais = tool_listar_editais(user_id, empresa_id=empresa_id)

    if not produtos.get("produtos") or not editais.get("editais"):
        return "Você precisa ter produtos e editais cadastrados para gerar uma proposta.", {"status": "incompleto"}

    # Tentar identificar e extrair preço
    produto_encontrado = None
    edital_encontrado = None
    preco = None

    message_lower = message.lower()

    # Usar helper para encontrar produto
    produto_encontrado = _encontrar_produto(produtos.get("produtos", []), message_lower)

    for e in editais.get("editais", []):
        numero = e.get("numero") or ""
        if numero and numero.lower() in message_lower:
            edital_encontrado = e
            break

    # Extrair preço - buscar padrão "R$ X" ou "preço X" ou "valor X"
    import re
    # Primeiro tenta R$ seguido de número
    preco_match = re.search(r'R\$\s*([\d.,]+)', message)
    if not preco_match:
        # Tenta "preço" ou "valor" seguido de número
        preco_match = re.search(r'(?:preço|preco|valor)\s*(?:de\s*)?R?\$?\s*([\d.,]+)', message, re.IGNORECASE)
    if preco_match:
        try:
            valor_str = preco_match.group(1)
            # Remove pontos de milhar e converte vírgula decimal
            preco = float(valor_str.replace('.', '').replace(',', '.'))
        except:
            pass

    if produto_encontrado and edital_encontrado:
        resultado = tool_gerar_proposta(
            edital_encontrado["id"],
            produto_encontrado["id"],
            user_id,
            preco=preco
        )

        if resultado.get("success"):
            response = f"""**Proposta Gerada com Sucesso!**

**Edital:** {resultado.get('edital')}
**Produto:** {resultado.get('produto')}
**Status:** {resultado.get('status')}

---

{resultado.get('texto_proposta', '')}

---

*Proposta salva com ID: {resultado.get('proposta_id')}*"""
            return response, resultado

    # Se não identificou, mostrar opções
    response = "Para gerar proposta, informe:\n- Produto\n- Edital\n- Preço (opcional)\n\n"
    response += "Exemplo: 'Gere proposta do Mindray BS-240 para edital PE-2024-001 com preço R$ 50.000'"

    return response, {"status": "aguardando_dados"}


def processar_salvar_editais(message: str, user_id: str, session_id: str, db):
    empresa_id = get_current_empresa_id()
    """
    Processa ação: Salvar editais

    Busca no histórico da sessão os editais da última busca e salva os recomendados
    ou os especificados pelo usuário.
    """
    import json
    import re

    msg_lower = message.lower()

    # Determinar o que salvar
    # - "salvar recomendados" ou "salvar editais recomendados" → PARTICIPAR + AVALIAR
    # - "salvar para participar" ou "salvar participar" → só PARTICIPAR
    # - "salvar todos" → todos os editais
    # - "salvar edital NUMERO" → edital específico

    # Primeiro verificar se tem número de edital específico na mensagem
    numero_especifico = None
    numero_match = re.search(r'edital\s+(\S+)', msg_lower)
    if numero_match:
        numero_especifico = numero_match.group(1).upper()
        # Limpar caracteres especiais do número
        numero_especifico = numero_especifico.strip('.,;:')

    # Determinar tipo de salvamento
    if numero_especifico:
        salvar_tipo = "especifico"
    elif "todos" in msg_lower:
        salvar_tipo = "todos"
    elif "participar" in msg_lower:
        salvar_tipo = "participar"
    elif "recomendados" in msg_lower or "recomendado" in msg_lower:
        salvar_tipo = "recomendados"
    else:
        salvar_tipo = "todos"  # Padrão para busca sem score

    # Buscar última mensagem de busca no histórico (com editais salvos em sources_json)
    # Aceita tanto buscar_editais (com score) quanto buscar_editais_simples (sem score)
    ultima_busca = db.query(Message).filter(
        Message.session_id == session_id,
        Message.action_type.in_(["buscar_editais", "buscar_editais_simples"]),
        Message.role == "assistant"
    ).order_by(Message.created_at.desc()).first()

    if not ultima_busca:
        return "Não encontrei uma busca de editais recente. Execute primeiro: **buscar editais de [tema]**", {"status": "sem_busca"}

    # Tentar recuperar editais do sources_json (salvo na busca)
    editais_para_salvar = []
    editais_com_score = []
    editais_participar = []
    editais_recomendados = []

    if ultima_busca.sources_json:
        # Recuperar editais salvos - SEM re-buscar!
        print(f"[SALVAR] Recuperando editais do sources_json...")
        sources = ultima_busca.sources_json
        editais_com_score = sources.get("editais_com_score", sources.get("editais", []))
        editais_participar = sources.get("editais_participar", [])
        editais_recomendados = sources.get("editais_recomendados", [])
        print(f"[SALVAR] Encontrados {len(editais_com_score)} editais salvos na sessão")
    else:
        # Fallback: sources_json vazio, precisa re-buscar (compatibilidade com buscas antigas)
        print(f"[SALVAR] sources_json vazio, buscando mensagem do usuário...")
        ultima_busca_user = db.query(Message).filter(
            Message.session_id == session_id,
            Message.action_type == "buscar_editais",
            Message.role == "user"
        ).order_by(Message.created_at.desc()).first()

        if ultima_busca_user:
            print(f"[SALVAR] Re-executando busca (fallback): {ultima_busca_user.content[:50]}...")
            classificacao = detectar_intencao_ia(ultima_busca_user.content, tem_arquivo=False)
            termo_ia = classificacao.get("termo_busca")
            _, resultado_busca = processar_buscar_editais(ultima_busca_user.content, user_id, termo_ia=termo_ia, calcular_score=False)

            if resultado_busca.get("success"):
                editais_com_score = resultado_busca.get("editais_com_score", [])
                editais_participar = resultado_busca.get("editais_participar", [])
                editais_recomendados = resultado_busca.get("editais_recomendados", [])

    if not editais_com_score:
        return "Não há editais para salvar. Execute uma busca primeiro: **buscar editais de [tema]**", {"status": "sem_editais"}

    print(f"[SALVAR] Tipo: {salvar_tipo}")
    print(f"[SALVAR] editais_com_score: {len(editais_com_score)}")
    print(f"[SALVAR] editais_participar: {len(editais_participar)}")
    print(f"[SALVAR] editais_recomendados: {len(editais_recomendados)}")

    if salvar_tipo == "especifico" and numero_especifico:
        # Salvar edital específico pelo número
        print(f"[SALVAR] Buscando edital específico: {numero_especifico}")
        for ed in editais_com_score:
            numero_edital = (ed.get("numero") or "").upper()
            # Tentar match exato ou parcial
            if numero_especifico in numero_edital or numero_edital in numero_especifico:
                editais_para_salvar.append(ed)
                print(f"[SALVAR] Encontrado edital: {numero_edital}")
                break
            # Tentar match só com números
            nums_busca = re.sub(r'[^\d]', '', numero_especifico)
            nums_edital = re.sub(r'[^\d]', '', numero_edital)
            if nums_busca and nums_edital and (nums_busca in nums_edital or nums_edital in nums_busca):
                editais_para_salvar.append(ed)
                print(f"[SALVAR] Encontrado edital (match numérico): {numero_edital}")
                break
    elif salvar_tipo == "todos":
        # Salvar TODOS os editais encontrados
        editais_para_salvar = editais_com_score
    elif salvar_tipo == "participar":
        # Salvar só os PARTICIPAR (score >= 80 ou recomendação PARTICIPAR)
        editais_para_salvar = editais_participar
        if not editais_para_salvar:
            # Fallback: pegar os com score >= 75 (margem para variação)
            editais_para_salvar = [e for e in editais_com_score if e.get("score_tecnico", 0) >= 75]
            print(f"[SALVAR] Fallback participar: {len(editais_para_salvar)} com score >= 75")
    elif salvar_tipo == "recomendados":
        # Salvar PARTICIPAR + AVALIAR
        editais_para_salvar = editais_recomendados
        if not editais_para_salvar:
            # Fallback: pegar os com score >= 50 ou todos se busca foi sem score
            editais_para_salvar = [e for e in editais_com_score if e.get("score_tecnico", 0) >= 50]
            if not editais_para_salvar:
                # Se ainda não tem (busca sem score), pegar todos
                editais_para_salvar = editais_com_score
            print(f"[SALVAR] Fallback recomendados: {len(editais_para_salvar)} editais")

    print(f"[SALVAR] editais_para_salvar: {len(editais_para_salvar)}")

    if not editais_para_salvar:
        return """Não encontrei editais para salvar.

**Opções:**
- Digite: **salvar editais recomendados** para salvar todos os recomendados
- Digite: **salvar edital [número]** para salvar um específico
- Execute uma nova busca: **buscar editais de [tema]**
""", {"status": "sem_editais"}

    # Salvar os editais selecionados (com verificação de duplicatas)
    resultado_salvar = tool_salvar_editais_selecionados(editais_para_salvar, user_id, empresa_id=empresa_id)

    if resultado_salvar.get("success"):
        salvos = resultado_salvar.get("salvos", [])
        duplicados = resultado_salvar.get("duplicados", [])
        erros = resultado_salvar.get("erros", [])
        incompletos = resultado_salvar.get("incompletos", [])

        response = "## 💾 Resultado do Salvamento\n\n"

        if salvos:
            response += f"**✅ Salvos com sucesso:** {len(salvos)} edital(is)\n"
            for num in salvos[:5]:
                response += f"- {num}\n"
            if len(salvos) > 5:
                response += f"- ... e mais {len(salvos) - 5}\n"
            response += "\n"

        if incompletos:
            response += f"**⚠️ Salvos com dados incompletos:** {len(incompletos)} edital(is)\n"
            response += "Estes editais não foram encontrados no PNCP e têm informações limitadas:\n"
            for num in incompletos[:3]:
                response += f"- {num}\n"
            response += "\n**Dica:** Para obter dados completos, acesse o link do edital e faça upload do PDF manualmente.\n\n"

        if duplicados:
            response += f"**⚠️ Já existentes (ignorados):** {len(duplicados)} edital(is)\n"
            for num in duplicados[:3]:
                response += f"- {num}\n"
            response += "\n"

        if erros:
            response += f"**❌ Erros:** {len(erros)}\n"
            for err in erros[:3]:
                response += f"- {err}\n"
            response += "\n"

        response += "Use **liste meus editais** para ver todos os editais salvos."

        return response, resultado_salvar
    else:
        return f"Erro ao salvar editais: {resultado_salvar.get('error')}", resultado_salvar


def formatar_resposta_tabular(resposta: str) -> str:
    """
    Melhora a formatação de respostas que contêm dados tabulares.
    Converte tabelas mal formatadas para markdown correto.
    """
    import re

    # Se já tem formato markdown de tabela bem formatada, preservar
    if re.search(r'\|[^|]+\|[^|]+\|', resposta) and '---' in resposta:
        return resposta

    linhas = resposta.strip().split("\n")

    # Detectar padrões de tabela (linha com múltiplas colunas separadas)
    # Padrão comum: "ID    Número    Órgão    Status"
    palavras_header = ["id", "número", "numero", "órgão", "orgao", "status", "valor", "data",
                       "nome", "objeto", "modalidade", "fonte", "url", "tipo"]

    for i, linha in enumerate(linhas):
        linha_lower = linha.lower()
        # Verifica se a linha parece um header de tabela
        matches = sum(1 for p in palavras_header if p in linha_lower)

        if matches >= 3:  # Pelo menos 3 palavras de header
            # Encontrou header, tentar converter para markdown
            # Detectar separador (múltiplos espaços ou tab)

            # Tentar separar por tabs primeiro
            if "\t" in linha:
                colunas_header = [c.strip() for c in linha.split("\t") if c.strip()]
            else:
                # Separar por múltiplos espaços (4+)
                colunas_header = [c.strip() for c in re.split(r'\s{4,}', linha) if c.strip()]

            if len(colunas_header) >= 3:
                # Montar tabela markdown
                md_linhas = []

                # Header
                md_linhas.append("| " + " | ".join(colunas_header) + " |")
                md_linhas.append("|" + "|".join("---" for _ in colunas_header) + "|")

                # Dados (linhas seguintes)
                for j in range(i + 1, len(linhas)):
                    data_linha = linhas[j].strip()
                    if not data_linha:
                        continue

                    if "\t" in data_linha:
                        colunas_data = [c.strip() for c in data_linha.split("\t")]
                    else:
                        colunas_data = [c.strip() for c in re.split(r'\s{4,}', data_linha)]

                    # Ajustar número de colunas
                    while len(colunas_data) < len(colunas_header):
                        colunas_data.append("")
                    colunas_data = colunas_data[:len(colunas_header)]

                    # Truncar valores muito longos
                    colunas_data = [c[:80] + "..." if len(c) > 80 else c for c in colunas_data]

                    md_linhas.append("| " + " | ".join(colunas_data) + " |")

                # Texto antes da tabela + tabela
                texto_antes = "\n".join(linhas[:i]).strip()
                tabela = "\n".join(md_linhas)

                if texto_antes:
                    return texto_antes + "\n\n" + tabela
                return tabela

    return resposta


def processar_consulta_mindsdb(message: str, user_id: str):
    """
    Processa consultas analíticas via MindsDB.
    Envia a pergunta em linguagem natural para o agente editais_database_searcher.
    """
    from tools import tool_consulta_mindsdb

    resultado = tool_consulta_mindsdb(message, user_id)

    if resultado.get("success"):
        resposta_mindsdb = resultado.get("resposta", "")

        # Melhorar formatação de tabelas
        resposta_formatada = formatar_resposta_tabular(resposta_mindsdb)

        response = f"""## 📊 Consulta Analítica

**Pergunta:** {message}

---

{resposta_formatada}

---
*Consulta realizada via MindsDB (GPT-4o)*"""
    else:
        error = resultado.get("error", "Erro desconhecido")
        response = f"""## ❌ Erro na Consulta

Não foi possível processar a consulta analítica.

**Erro:** {error}

**Dica:** Tente reformular a pergunta ou use comandos diretos como:
- "liste meus editais"
- "liste meus produtos"
- "calcule aderência do produto X ao edital Y"
"""

    return response, resultado


def processar_registrar_resultado(message: str, user_id: str):
    empresa_id = get_current_empresa_id()
    """
    Processa registro de resultado de certame (vitória/derrota).
    Alimenta a base de preços históricos e concorrentes.
    """
    from tools import tool_registrar_resultado

    resultado = tool_registrar_resultado(message, user_id, empresa_id=empresa_id)

    if not resultado.get("success"):
        error = resultado.get("error", "Erro desconhecido")
        response = f"""❌ **Erro ao registrar resultado**

{error}

**Exemplos de como registrar:**
- "Perdemos o PE-001/2026 para MedLab com R$ 365.000, nosso preço foi R$ 380.000"
- "Ganhamos o edital PE-002/2026 com R$ 290.000"
- "Perdemos o PE-003 por documentação"
- "O edital PE-004 foi cancelado"
"""
        return response, None

    # Montar resposta de sucesso
    emoji_resultado = "🏆" if resultado["resultado"] == "vitoria" else "📊"
    status_texto = {
        "vitoria": "VITÓRIA",
        "derrota": "DERROTA",
        "cancelado": "CANCELADO",
        "deserto": "DESERTO",
        "revogado": "REVOGADO"
    }.get(resultado["resultado"], resultado["resultado"].upper())

    response = f"""{emoji_resultado} **Resultado Registrado - {resultado['edital_numero']}**

**Órgão:** {resultado.get('orgao', 'N/A')}
**Resultado:** {status_texto}
"""

    # Tabela de preços se disponível
    if resultado.get("preco_vencedor") or resultado.get("nosso_preco"):
        response += "\n| Posição | Empresa | Preço |\n"
        response += "|---------|---------|-------|\n"

        if resultado.get("empresa_vencedora") and resultado["resultado"] != "vitoria":
            preco_venc = resultado["preco_vencedor"]
            preco_fmt = f"R$ {preco_venc:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if preco_venc else "N/A"
            response += f"| 1º | {resultado['empresa_vencedora']} | {preco_fmt} |\n"

        if resultado.get("nosso_preco"):
            pos = "1º" if resultado["resultado"] == "vitoria" else "2º"
            nosso_preco = resultado["nosso_preco"]
            preco_fmt = f"R$ {nosso_preco:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if nosso_preco else "N/A"
            response += f"| {pos} | Sua Empresa | {preco_fmt} |\n"

        response += "\n"

    # Análise se foi derrota por preço
    if resultado.get("diferenca") and resultado["resultado"] == "derrota":
        diferenca = resultado["diferenca"]
        diferenca_pct = resultado.get("diferenca_pct", 0)
        desconto = resultado.get("desconto_percentual")

        response += f"""**Análise:**
- Diferença: R$ {diferenca:,.2f} ({diferenca_pct:.1f}%)
"""
        if desconto:
            response += f"- Desconto do vencedor: {desconto:.1f}% sobre referência\n"

        if resultado.get("motivo"):
            motivo_texto = {
                "preco": "Preço",
                "tecnica": "Questão técnica",
                "documentacao": "Documentação",
                "prazo": "Prazo",
                "outro": "Outro"
            }.get(resultado["motivo"], resultado["motivo"])
            response += f"- Motivo principal: {motivo_texto}\n"

        response += f"""
💡 **Insight:** Para editais similares, considere preços ~{diferenca_pct:.0f}% menores.
"""

    # Mensagem de sucesso final
    response += """
✅ Dados salvos no histórico de preços e concorrentes!
"""

    return response, resultado


def processar_consultar_resultado(message: str, user_id: str):
    """
    Consulta resultado de um certame já registrado.
    Suporta consulta de um edital específico ou de todos os editais.
    """
    empresa_id = get_current_empresa_id()
    from models import get_db, Edital, PrecoHistorico, Concorrente, ParticipacaoEdital
    import re

    db = get_db()
    try:
        # Verificar se é consulta de TODOS os editais
        msg_lower = message.lower()
        consulta_todos = any(p in msg_lower for p in [
            "todos os editais", "todos editais", "resultados dos editais",
            "resultado dos editais", "todos os resultados", "listar resultados"
        ])

        if consulta_todos:
            return processar_consultar_todos_resultados(user_id, db)

        # Extrair número do edital da mensagem
        # Padrões: PE-001/2026, 90186, PE001, etc
        padrao = r'(?:PE[-\s]?)?(\d{2,6})(?:/\d{4})?'
        match = re.search(padrao, message, re.IGNORECASE)

        if not match:
            return "❌ Não identifiquei o número do edital. Informe o número (ex: PE-041/2026 ou 90186)\n\nPara ver todos os resultados, use: \"mostre os resultados de todos os editais\"", None

        numero_edital = match.group(0)

        # Buscar edital
        edital = db.query(Edital).filter(
            Edital.numero.ilike(f"%{numero_edital}%"),
            Edital.empresa_id == empresa_id
        ).first()

        if not edital:
            # Tentar busca mais flexível
            numero_limpo = match.group(1)
            edital = db.query(Edital).filter(
                Edital.numero.ilike(f"%{numero_limpo}%"),
                Edital.empresa_id == empresa_id
            ).first()

        if not edital:
            return f"❌ Edital '{numero_edital}' não encontrado no seu cadastro.", None

        # Buscar resultado registrado
        preco_hist = db.query(PrecoHistorico).filter(
            PrecoHistorico.edital_id == edital.id
        ).order_by(PrecoHistorico.data_registro.desc()).first()

        if not preco_hist:
            response = f"""📋 **Edital {edital.numero}**

**Órgão:** {edital.orgao}
**Status:** {edital.status or 'Não definido'}
**Valor Referência:** R$ {float(edital.valor_referencia):,.2f}

⚠️ **Nenhum resultado registrado ainda.**

Para registrar o resultado, use:
- "Perdemos o {edital.numero} para [EMPRESA] com R$ [VALOR]"
- "Ganhamos o {edital.numero} com R$ [VALOR]"
"""
            return response, None

        # Buscar participações
        participacoes = db.query(ParticipacaoEdital).filter(
            ParticipacaoEdital.edital_id == edital.id
        ).order_by(ParticipacaoEdital.posicao_final).all()

        # Montar resposta
        emoji_resultado = "🏆" if preco_hist.resultado == "vitoria" else "📊"
        status_texto = {
            "vitoria": "VITÓRIA",
            "derrota": "DERROTA",
            "cancelado": "CANCELADO",
            "deserto": "DESERTO",
            "revogado": "REVOGADO"
        }.get(preco_hist.resultado, preco_hist.resultado.upper() if preco_hist.resultado else "N/A")

        response = f"""{emoji_resultado} **Resultado do Edital {edital.numero}**

**Órgão:** {edital.orgao}
**Resultado:** {status_texto}
**Data:** {preco_hist.data_homologacao.strftime('%d/%m/%Y') if preco_hist.data_homologacao else 'N/A'}
"""

        # Tabela de participantes
        if participacoes:
            response += "\n**Participantes:**\n"
            response += "| Pos | Empresa | Preço |\n"
            response += "|-----|---------|-------|\n"

            for part in participacoes:
                if part.concorrente_id:
                    conc = db.query(Concorrente).get(part.concorrente_id)
                    nome = conc.nome if conc else "Desconhecido"
                else:
                    nome = "Sua Empresa"

                preco_fmt = f"R$ {float(part.preco_proposto):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if part.preco_proposto else "N/A"
                pos = f"{part.posicao_final}º" if part.posicao_final else "-"
                response += f"| {pos} | {nome} | {preco_fmt} |\n"

            response += "\n"

        # Análise
        if preco_hist.resultado == "derrota" and preco_hist.nosso_preco and preco_hist.preco_vencedor:
            diferenca = float(preco_hist.nosso_preco) - float(preco_hist.preco_vencedor)
            diferenca_pct = (diferenca / float(preco_hist.nosso_preco)) * 100

            response += f"""**Análise:**
- Nosso preço: R$ {float(preco_hist.nosso_preco):,.2f}
- Preço vencedor: R$ {float(preco_hist.preco_vencedor):,.2f}
- Diferença: R$ {diferenca:,.2f} ({diferenca_pct:.1f}%)
"""
            if preco_hist.motivo_perda:
                motivo_texto = {
                    "preco": "Preço",
                    "tecnica": "Questão técnica",
                    "documentacao": "Documentação",
                    "prazo": "Prazo",
                    "outro": "Outro"
                }.get(preco_hist.motivo_perda, preco_hist.motivo_perda)
                response += f"- Motivo: {motivo_texto}\n"

        return response, {"edital_id": edital.id, "resultado": preco_hist.resultado}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"❌ Erro ao consultar resultado: {str(e)}", None
    finally:
        db.close()


def processar_consultar_todos_resultados(user_id: str, db):
    """
    Consulta resultados de TODOS os editais do usuário.
    Retorna uma tabela markdown com os resultados.
    """
    empresa_id = get_current_empresa_id()
    from models import Edital, PrecoHistorico

    try:
        # Buscar editais com resultado registrado (status diferente de 'novo', 'aberto', 'analisando')
        status_com_resultado = ['vencedor', 'perdedor', 'cancelado', 'deserto', 'revogado']

        editais = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.status.in_(status_com_resultado)
        ).order_by(Edital.data_abertura.desc()).all()

        if not editais:
            # Verificar se tem editais sem resultado
            total_editais = db.query(Edital).filter(Edital.empresa_id == empresa_id).count()
            if total_editais > 0:
                return f"""📊 **Resultados de Certames**

⚠️ Nenhum edital com resultado registrado.

Você tem **{total_editais} editais** cadastrados, mas nenhum com resultado definido.

Para registrar um resultado, use:
- "Perdemos o edital [NUMERO] para [EMPRESA] com R$ [VALOR]"
- "Ganhamos o edital [NUMERO] com R$ [VALOR]"
- "O edital [NUMERO] foi cancelado"
""", None
            else:
                return "❌ Você não tem editais cadastrados.", None

        # Contar por status
        contagem = {}
        for e in editais:
            status = e.status or "indefinido"
            contagem[status] = contagem.get(status, 0) + 1

        # Montar tabela markdown
        response = f"""## 📊 Resultados dos Certames

**Total com resultado:** {len(editais)} editais

**Resumo:**
"""
        # Adicionar resumo com emojis
        emoji_status = {
            'vencedor': '🏆',
            'perdedor': '📉',
            'cancelado': '⛔',
            'deserto': '🚫',
            'revogado': '❌'
        }
        for status, qtd in sorted(contagem.items(), key=lambda x: -x[1]):
            emoji = emoji_status.get(status, '📋')
            response += f"- {emoji} **{status.capitalize()}:** {qtd}\n"

        response += "\n---\n\n"

        # Tabela de editais
        response += "| Número | Órgão | Status | Valor Ref. | Data |\n"
        response += "|--------|-------|--------|------------|------|\n"

        for edital in editais[:20]:  # Limitar a 20 para não ficar muito grande
            numero = edital.numero or "N/A"
            orgao = (edital.orgao[:30] + "...") if edital.orgao and len(edital.orgao) > 30 else (edital.orgao or "N/A")
            status = edital.status.capitalize() if edital.status else "N/A"
            valor = f"R$ {float(edital.valor_referencia):,.0f}".replace(",", ".") if edital.valor_referencia else "N/A"
            data = edital.data_abertura.strftime('%d/%m/%Y') if edital.data_abertura else "N/A"

            # Adicionar emoji ao status
            emoji = emoji_status.get(edital.status, '')
            response += f"| {numero} | {orgao} | {emoji} {status} | {valor} | {data} |\n"

        if len(editais) > 20:
            response += f"\n*... e mais {len(editais) - 20} editais*\n"

        response += "\n---\n*Para detalhes de um edital específico, use: \"Qual o resultado do edital [NUMERO]?\"*"

        return response, {"total": len(editais), "contagem": contagem}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"❌ Erro ao consultar resultados: {str(e)}", None


def processar_extrair_ata(texto_pdf: str, filepath: str, user_id: str, filename: str):
    empresa_id = get_current_empresa_id()
    """
    Processa extração de resultados de uma ata de sessão de pregão.

    Args:
        texto_pdf: Texto extraído do PDF
        filepath: Caminho do arquivo
        user_id: ID do usuário
        filename: Nome do arquivo original

    Returns:
        Tuple (response_text, resultado)
    """
    from tools import tool_extrair_ata_pdf

    resultado = tool_extrair_ata_pdf(texto_pdf, user_id, empresa_id=empresa_id)

    if not resultado.get("success"):
        response = f"""## ❌ Erro ao Extrair Ata

**Arquivo:** {filename}

**Erro:** {resultado.get('error', 'Erro desconhecido')}

**Dica:** Certifique-se de que o arquivo é uma ata de sessão de pregão eletrônico.
"""
        return response, resultado

    # Montar resposta formatada
    response = f"""## 📄 Resultados Extraídos da Ata

**Arquivo:** {filename}
**Edital:** {resultado.get('edital', 'Não identificado')}
**Órgão:** {resultado.get('orgao', 'Não identificado')}
**Data da Sessão:** {resultado.get('data_sessao', 'N/A')}
**Objeto:** {resultado.get('objeto', 'N/A')[:200]}{'...' if resultado.get('objeto') and len(resultado.get('objeto', '')) > 200 else ''}

---

### 📊 Itens/Lotes Extraídos

"""

    # Verificar se há aviso (sem itens extraídos)
    if resultado.get("aviso"):
        response += f"""⚠️ **{resultado['aviso']}**

O documento foi processado mas não foram encontrados itens com vencedores/preços estruturados.

**Possíveis causas:**
- A ata pode estar incompleta ou ser de outra fase do pregão
- O formato do PDF pode ser diferente do esperado
- O texto pode estar escaneado (imagem) e não selecionável

**Alternativa:** Registre o resultado manualmente:
- "Perdemos o edital {resultado.get('edital', '[NUMERO]')} para [EMPRESA] com R$ [VALOR]"
- "Ganhamos o edital {resultado.get('edital', '[NUMERO]')} com R$ [VALOR]"

"""
        return response, resultado

    for item in resultado.get("itens", []):
        emoji = "🏆" if item.get("vencedor") else "❓"
        response += f"""**Item {item.get('item', '?')}:** {item.get('descricao', 'N/A')[:100]}...
- {emoji} **Vencedor:** {item.get('vencedor', 'Não identificado')}
- 💰 **Preço:** R$ {item.get('preco_vencedor', 0):,.2f}
- 👥 **Participantes:** {item.get('participantes_count', 0)}

"""

    # Desclassificados
    if resultado.get("desclassificados"):
        response += "### ⚠️ Empresas Desclassificadas\n\n"
        for desc in resultado["desclassificados"]:
            response += f"- **{desc.get('empresa', 'N/A')}:** {desc.get('motivo', 'Motivo não informado')}\n"
        response += "\n"

    # Concorrentes registrados
    response += "---\n\n### 📁 Dados Registrados\n\n"

    if resultado.get("concorrentes_novos"):
        response += f"**Novos concorrentes:** {', '.join(resultado['concorrentes_novos'][:5])}"
        if len(resultado.get('concorrentes_novos', [])) > 5:
            response += f" (+{len(resultado['concorrentes_novos']) - 5})"
        response += "\n"

    if resultado.get("concorrentes_atualizados"):
        response += f"**Concorrentes atualizados:** {len(resultado['concorrentes_atualizados'])}\n"

    if resultado.get("edital_encontrado"):
        response += f"\n✅ **Edital {resultado['edital_encontrado']} encontrado no sistema - dados salvos no histórico!**\n"
    else:
        edital_num = resultado.get('edital', '[NUMERO]')
        itens = resultado.get('itens', [])

        # Obter dados do primeiro item de forma segura
        primeiro_item = itens[0] if itens else {}
        vencedor = primeiro_item.get('vencedor', 'EMPRESA')
        preco = primeiro_item.get('preco_vencedor', 0)
        objeto = resultado.get('objeto', 'equipamentos') or 'equipamentos'

        response += f"""
⚠️ **Edital não encontrado no sistema.**

Para salvar os dados no histórico, primeiro cadastre o edital:
- Busque editais: "busque editais de {objeto[:30]}"
- Ou registre manualmente o resultado: "Perdemos o edital {edital_num} para {vencedor} com R$ {preco:,.0f}"
"""

    return response, resultado


def processar_buscar_atas_pncp(message: str, user_id: str):
    """
    Processa busca de atas de sessão/registro de preço no PNCP.

    Args:
        message: Mensagem do usuário
        user_id: ID do usuário

    Returns:
        Tuple (response_text, resultado)
    """
    from tools import tool_buscar_atas_pncp

    # Extrair termo de busca usando helper
    palavras = ["busque", "buscar", "encontre", "encontrar", "baixe", "baixar",
                "atas", "ata", "de", "do", "da", "no", "na", "pncp", "registro",
                "preço", "preco", "sessão", "sessao"]
    termo = extrair_termo(message, palavras)

    if not termo or len(termo) < 3:
        return """## ❓ Termo de Busca Necessário

Por favor, especifique o que você está buscando. Exemplos:
- "Busque atas de **hematologia**"
- "Encontre atas de **equipamentos hospitalares**"
- "Baixe atas de **material de laboratório**"
""", None

    resultado = tool_buscar_atas_pncp(termo, user_id)

    if not resultado.get("success"):
        response = f"""## ❌ Erro na Busca de Atas

**Termo:** {termo}
**Erro:** {resultado.get('error', 'Erro desconhecido')}

**Dica:** Tente termos mais específicos como:
- "hematologia"
- "equipamento médico"
- "reagentes laboratoriais"
"""
        return response, resultado

    atas = resultado.get("atas", [])

    response = f"""## 📄 Atas Encontradas no PNCP

**Termo:** {termo}
**Total:** {resultado.get('total', len(atas))} atas encontradas
**Fonte:** {resultado.get('fonte', 'PNCP')}

---

"""

    for i, ata in enumerate(atas[:10], 1):
        titulo = ata.get('titulo', 'Sem título')
        orgao = ata.get('orgao', 'N/A')
        descricao = ata.get('descricao', '')[:150]
        data = ata.get('data_assinatura') or ata.get('data_publicacao', 'N/A')
        url = ata.get('url_pncp', ata.get('url', '#'))

        response += f"""### {i}. {titulo}

**Órgão:** {orgao}
**Data:** {data}
**Descrição:** {descricao}{'...' if len(ata.get('descricao', '')) > 150 else ''}

🔗 [Acessar no PNCP]({url})

---

"""

    response += """
### 💡 Como usar as atas:

1. Clique no link para acessar a ata no PNCP
2. Baixe o PDF da ata de sessão
3. Envie o PDF aqui com a mensagem: **"Extraia os resultados desta ata"**

O sistema irá extrair automaticamente os vencedores, preços e participantes!
"""

    return response, resultado


def processar_buscar_precos_pncp(message: str, user_id: str):
    """
    Processa busca de preços de contratos no PNCP.
    Funcionalidade 4 da Sprint 1.

    Args:
        message: Mensagem do usuário
        user_id: ID do usuário

    Returns:
        Tuple (response_text, resultado)
    """
    from tools import tool_buscar_precos_pncp

    # Extrair termo de busca usando helper
    palavras = ["busque", "buscar", "encontre", "encontrar", "preços", "precos",
                "de", "do", "da", "no", "na", "pncp", "mercado", "médio", "medio",
                "quanto", "custa", "valor", "valores", "contrato", "contratos",
                "praticado", "praticados", "histórico", "historico", "qual", "o"]
    termo = extrair_termo(message, palavras)

    if not termo or len(termo) < 3:
        return """## ❓ Termo de Busca Necessário

Por favor, especifique o produto/equipamento que deseja pesquisar. Exemplos:
- "Busque preços de **analisador hematológico**"
- "Qual o preço de mercado para **centrífuga**?"
- "Preços de **reagentes de bioquímica** no PNCP"
""", None

    resultado = tool_buscar_precos_pncp(termo, meses=12, user_id=user_id)

    if not resultado.get("success"):
        response = f"""## ❌ Nenhum Preço Encontrado

**Termo:** {termo}
**Erro:** {resultado.get('error', 'Nenhum contrato encontrado')}

**Dica:** Tente termos mais específicos como:
- "analisador hematológico"
- "equipamento laboratório"
- "reagentes diagnóstico"
"""
        return response, resultado

    # Formatar resposta
    stats = resultado.get("estatisticas", {})
    contratos = resultado.get("contratos", [])
    top_fornecedores = resultado.get("top_fornecedores", [])

    response = f"""## 💰 Preços de Mercado - PNCP

**Termo pesquisado:** {termo}
**Período:** Últimos {resultado.get('periodo_meses', 12)} meses
**Contratos encontrados:** {resultado.get('total_contratos', 0)}
**Fonte:** {resultado.get('fonte', 'PNCP')}

---

### 📊 Estatísticas de Preços

| Métrica | Valor |
|---------|-------|
| **Mínimo** | R$ {stats.get('preco_minimo', 0):,.2f} |
| **Médio** | R$ {stats.get('preco_medio', 0):,.2f} |
| **Mediano** | R$ {stats.get('preco_mediano', 0):,.2f} |
| **Máximo** | R$ {stats.get('preco_maximo', 0):,.2f} |

---

### 🏢 Principais Fornecedores

"""
    for i, forn in enumerate(top_fornecedores[:5], 1):
        response += f"{i}. **{forn.get('nome', 'N/A')[:40]}** - {forn.get('contratos', 0)} contratos (média: R$ {forn.get('preco_medio', 0):,.2f})\n"

    response += """

---

### 📋 Últimos Contratos

"""
    for i, contrato in enumerate(contratos[:10], 1):
        objeto = contrato.get('objeto', contrato.get('titulo', 'N/A'))[:80]
        fornecedor = contrato.get('fornecedor', 'N/A')[:30]
        valor = contrato.get('valor', 0)
        orgao = contrato.get('orgao', 'N/A')[:30]
        data = contrato.get('data_assinatura', contrato.get('data_publicacao', 'N/A'))
        url = contrato.get('url_pncp', '#')

        response += f"""**{i}. {objeto}...**
- 🏢 Órgão: {orgao}
- 🏭 Fornecedor: {fornecedor}
- 💵 Valor: **R$ {valor:,.2f}**
- 📅 Data: {data}
"""
        if url and url != '#':
            response += f"- 🔗 [Ver no PNCP]({url})\n"
        response += "\n"

    response += """
---

### 💡 Como usar esses dados:

1. **Para definir preço de proposta:** Use o preço médio como referência
2. **Para análise de concorrentes:** Veja os principais fornecedores
3. **Para justificativa de preços:** Cite os contratos como referência

📌 **Dica:** Para salvar esses preços no histórico, registre um resultado de edital!
"""

    return response, resultado


# ==================== HELPER: EXTRAÇÃO DE TERMOS ====================

def extrair_termo(message: str, palavras_remover: list) -> str:
    """
    Extrai termo de busca removendo palavras-chave de comando.
    Usa regex com word boundaries para não cortar partes de palavras.

    Args:
        message: Mensagem do usuário
        palavras_remover: Lista de palavras a remover

    Returns:
        Termo extraído limpo
    """
    import re

    texto = message.lower()

    # Remover palavras usando word boundaries para não cortar partes de palavras
    for palavra in palavras_remover:
        # \b = word boundary - só casa com palavra completa
        pattern = r'\b' + re.escape(palavra) + r'\b'
        texto = re.sub(pattern, ' ', texto, flags=re.IGNORECASE)

    # Limpar espaços extras e pontuação no início/fim
    texto = re.sub(r'\s+', ' ', texto).strip()
    texto = re.sub(r'^[.,!?:;\s]+|[.,!?:;\s]+$', '', texto)

    return texto


# ==================== SPRINT 1 - FUNCIONALIDADE 5: HISTÓRICO DE PREÇOS ====================

def processar_historico_precos(message: str, user_id: str):
    empresa_id = get_current_empresa_id()
    """Processa consulta de histórico de preços."""
    from tools import tool_historico_precos

    # Extrair termo usando helper
    palavras = ["histórico", "historico", "preços", "precos", "de", "do", "da",
                "registrados", "salvos", "mostre", "mostrar", "ver", "consultar",
                "quais", "já", "ja"]
    termo = extrair_termo(message, palavras)

    resultado = tool_historico_precos(termo=termo if termo else None, user_id=user_id, empresa_id=empresa_id)

    if not resultado.get("success"):
        return f"""## ❌ Histórico de Preços

**Erro:** {resultado.get('error', 'Nenhum registro encontrado')}

**Dica:** Registre resultados de editais para criar histórico de preços.
""", resultado

    stats = resultado.get("estatisticas", {})
    historico = resultado.get("historico", [])

    response = f"""## 📈 Histórico de Preços

**Termo:** {termo or 'Todos'}
**Total de registros:** {resultado.get('total', 0)}

---

### 📊 Estatísticas

| Métrica | Valor |
|---------|-------|
| **Mínimo** | R$ {stats.get('preco_minimo', 0):,.2f} |
| **Médio** | R$ {stats.get('preco_medio', 0):,.2f} |
| **Mediano** | R$ {stats.get('preco_mediano', 0):,.2f} |
| **Máximo** | R$ {stats.get('preco_maximo', 0):,.2f} |

---

### 📋 Últimos Registros

"""
    for i, h in enumerate(historico[:10], 1):
        resultado_emoji = "🏆" if h.get('resultado') == 'vitoria' else "📊"
        response += f"{i}. {resultado_emoji} **R$ {h.get('preco_vencedor', 0):,.2f}** - {h.get('empresa_vencedora', 'N/A')} ({h.get('data', 'N/A')})\n"

    return response, resultado


# ==================== SPRINT 1 - FUNCIONALIDADE 6: ANÁLISE DE CONCORRENTES ====================

def processar_listar_concorrentes(user_id: str):
    """Processa listagem de concorrentes."""
    from tools import tool_listar_concorrentes

    resultado = tool_listar_concorrentes(user_id=user_id)

    if not resultado.get("success"):
        return f"""## ❌ Concorrentes

**Erro:** {resultado.get('error', 'Nenhum concorrente cadastrado')}

**Dica:** {resultado.get('dica', 'Registre resultados de editais para cadastrar concorrentes automaticamente.')}
""", resultado

    concorrentes = resultado.get("concorrentes", [])

    response = f"""## 👥 Concorrentes Conhecidos

**Total:** {resultado.get('total', 0)} concorrentes

---

| # | Empresa | Participações | Vitórias | Taxa |
|---|---------|---------------|----------|------|
"""
    for i, c in enumerate(concorrentes[:15], 1):
        response += f"| {i} | {c.get('nome', 'N/A')[:25]} | {c.get('editais_participados', 0)} | {c.get('editais_ganhos', 0)} | {c.get('taxa_vitoria', 0):.1f}% |\n"

    response += """

---

💡 **Dica:** Use "analise o concorrente [NOME]" para ver detalhes.
"""
    return response, resultado


def processar_analisar_concorrente(message: str, user_id: str):
    """Processa análise de concorrente específico."""
    from tools import tool_analisar_concorrente

    # Extrair nome do concorrente usando helper
    palavras = ["analise", "analisar", "análise", "concorrente", "o", "do", "da",
                "empresa", "histórico", "historico", "como", "está", "esta"]
    nome = extrair_termo(message, palavras)

    if not nome:
        return """## ❓ Nome do Concorrente

Por favor, especifique o concorrente. Exemplo:
- "Analise o concorrente **MedLab**"
- "Histórico do concorrente **TechSaúde**"
""", None

    resultado = tool_analisar_concorrente(nome, user_id=user_id)

    if not resultado.get("success"):
        return f"""## ❌ Concorrente Não Encontrado

**Buscado:** {nome}
**Erro:** {resultado.get('error', 'Não encontrado')}

**Dica:** {resultado.get('dica', 'Use "liste concorrentes" para ver os cadastrados.')}
""", resultado

    conc = resultado.get("concorrente", {})
    stats = resultado.get("estatisticas_precos", {})
    historico = resultado.get("historico_participacoes", [])

    response = f"""## 🔍 Análise do Concorrente

### {conc.get('nome', 'N/A')}
**CNPJ:** {conc.get('cnpj', 'Não informado')}

---

### 📊 Estatísticas

| Métrica | Valor |
|---------|-------|
| **Editais Participados** | {conc.get('editais_participados', 0)} |
| **Editais Ganhos** | {conc.get('editais_ganhos', 0)} |
| **Taxa de Vitória** | {conc.get('taxa_vitoria', 0):.1f}% |

### 💰 Preços Praticados

| Métrica | Valor |
|---------|-------|
| **Mínimo** | R$ {stats.get('preco_minimo', 0):,.2f} |
| **Médio** | R$ {stats.get('preco_medio', 0):,.2f} |
| **Máximo** | R$ {stats.get('preco_maximo', 0):,.2f} |

---

### 📋 Últimas Participações

"""
    for i, h in enumerate(historico[:10], 1):
        emoji = "🏆" if h.get('venceu') else "📊"
        response += f"{i}. {emoji} {h.get('edital', 'N/A')} - R$ {h.get('preco', 0):,.2f} (#{h.get('posicao', '?')}º)\n"

    return response, resultado


# ==================== SPRINT 1 - FUNCIONALIDADE 7: RECOMENDAÇÃO DE PREÇOS ====================

def processar_recomendar_preco(message: str, user_id: str):
    """Processa recomendação de preço."""
    from tools import tool_recomendar_preco

    # Extrair termo usando helper
    palavras = ["recomendar", "recomende", "sugerir", "sugira", "preço", "preco",
                "que", "qual", "colocar", "para", "de", "do", "da"]
    termo = extrair_termo(message, palavras)

    if not termo:
        return """## ❓ Produto/Termo Necessário

Por favor, especifique o produto. Exemplo:
- "Recomende preço para **analisador hematológico**"
- "Qual preço sugerir para **reagentes bioquímica**?"
""", None

    resultado = tool_recomendar_preco(termo, user_id=user_id)

    if not resultado.get("success"):
        return f"""## ❌ Recomendação de Preço

**Termo:** {termo}
**Erro:** {resultado.get('error', 'Dados insuficientes')}

**Dica:** {resultado.get('dica', 'Registre mais resultados de editais ou busque preços no PNCP.')}
""", resultado

    rec = resultado.get("recomendacao", {})
    stats = resultado.get("estatisticas_historico", resultado.get("estatisticas_mercado", {}))
    fonte = resultado.get("fonte", "")

    response = f"""## 💡 Recomendação de Preço

**Termo:** {termo}
**Fonte:** {fonte.replace('_', ' ').title()}
**Registros analisados:** {stats.get('total_registros', 0)}

---

### 🎯 Preços Sugeridos

| Estratégia | Preço Sugerido |
|------------|----------------|
| 🔥 **Agressivo** | R$ {rec.get('preco_agressivo', rec.get('preco_minimo_sugerido', 0)):,.2f} |
| ✅ **Ideal** | R$ {rec.get('preco_ideal', 0):,.2f} |
| 🛡️ **Conservador** | R$ {rec.get('preco_conservador', rec.get('preco_maximo_sugerido', 0)):,.2f} |

---

### 📊 Referência de Mercado

| Métrica | Valor |
|---------|-------|
| **Preço Médio Vencedor** | R$ {stats.get('preco_medio_vencedor', stats.get('preco_medio', 0)):,.2f} |
| **Preço Mínimo** | R$ {stats.get('preco_minimo_vencedor', stats.get('preco_minimo', 0)):,.2f} |

---

**Justificativa:** {resultado.get('justificativa', 'N/A')}

💡 **Dica:** O preço **ideal** oferece boa margem de vitória com lucro razoável.
"""
    return response, resultado


# ==================== SPRINT 1 - FUNCIONALIDADE 8: CLASSIFICAÇÃO DE EDITAIS ====================

def processar_classificar_edital(message: str, user_id: str):
    """Processa classificação de edital."""
    from tools import tool_classificar_edital

    # Extrair texto do edital ou ID
    msg_lower = message.lower()

    # Verificar se tem ID de edital
    import re
    match_id = re.search(r'edital\s*(\d+)', msg_lower)
    edital_id = int(match_id.group(1)) if match_id else None

    # Usar mensagem como texto se não tem ID
    texto = message if not edital_id else None

    resultado = tool_classificar_edital(edital_id=edital_id, texto_edital=texto, user_id=user_id)

    if not resultado.get("success"):
        return f"""## ❌ Classificação de Edital

**Erro:** {resultado.get('error', 'Não foi possível classificar')}

**Dica:** Forneça o texto do objeto do edital ou o ID de um edital cadastrado.
""", resultado

    categoria = resultado.get("categoria", "outros")
    confianca = resultado.get("confianca", 0)

    # Mapeamento de categorias
    categorias_nome = {
        "comodato": "🤝 Comodato de Equipamentos",
        "aluguel_reagentes": "📦 Aluguel com Reagentes",
        "aluguel_simples": "🏷️ Aluguel Simples",
        "venda": "💰 Venda/Aquisição",
        "consumo_reagentes": "🧪 Consumo de Reagentes",
        "insumos_hospitalares": "🏥 Insumos Hospitalares",
        "insumos_laboratoriais": "🔬 Insumos Laboratoriais",
        "outros": "❓ Outros"
    }

    response = f"""## 🏷️ Classificação do Edital

**Categoria Identificada:** {categorias_nome.get(categoria, categoria)}
**Confiança:** {confianca}%

---

### 📊 Todas as Categorias Detectadas

"""
    for cat, score in resultado.get("todas_categorias", {}).items():
        emoji = "✅" if cat == categoria else "⬜"
        response += f"{emoji} **{cat}**: {score} matches\n"

    response += f"""

---

**Justificativa:** {resultado.get('justificativa', 'N/A')}
"""
    return response, resultado


# ==================== FASE 2 — SCORE COMERCIAL GO/NO-GO ====================

def processar_score_comercial(message: str, user_id: str, empresa_id: str = None):
    """Processa pedido de score de aderência comercial (RF-SCO-002/003)."""
    import re
    from tools import tool_score_comercial

    # Mesmo padrão de extração usado em processar_configurar_alertas
    match_edital = re.search(
        r'(PE[-\s]?[\w]+[-/]?\d*|[Pp]reg[aã]o\s*n?[ºo°]?\s*[\w/]+|\d{1,5}[/]\d{4})',
        message, re.IGNORECASE)
    edital_numero = match_edital.group(1).strip() if match_edital else None

    if not edital_numero:
        return ("⚠️ Para calcular o score comercial, preciso saber qual edital. "
                "Informe o número, por exemplo:\n\n"
                "*\"Vale a pena participar do PE 123/2026?\"*"), {"success": False}

    resultado = tool_score_comercial(
        user_id=user_id, empresa_id=empresa_id, edital_numero=edital_numero)

    if not resultado.get("success"):
        return (f"## ❌ Score Comercial\n\n"
                f"**Erro:** {resultado.get('error', 'Não foi possível calcular')}"), resultado

    emoji_rec = {"GO": "🟢", "AVALIAR": "🟡", "NO_GO": "🔴"}
    rec = resultado.get("recomendacao", "AVALIAR")
    comp = resultado.get("componentes", {})
    nomes = [("logistico", "🚚 Logística"), ("porte", "🏢 Porte x Valor"),
             ("historico", "📊 Histórico"), ("prazo", "⏰ Prazo")]

    response = f"""## {emoji_rec.get(rec, '🟡')} Score Comercial — {resultado.get('edital_numero')}

**Órgão:** {resultado.get('orgao')}{f" ({resultado.get('uf')})" if resultado.get('uf') else ""}

**Score final:** {resultado.get('score_final')}/100 → **{rec.replace('_', ' ')}**

---

### Componentes

"""
    for chave, label in nomes:
        c = comp.get(chave, {})
        response += f"- {label}: **{c.get('score', '—')}** — {c.get('motivo', '')}\n"

    response += ("\n---\n\n*Score consultivo: pondera logística (30%), porte (20%), "
                 "histórico (35%) e prazo (15%). A decisão final é sua.*")
    return response, resultado


# ==================== SPRINT 1 - FUNCIONALIDADE 9: VERIFICAR COMPLETUDE ====================

def processar_verificar_completude(message: str, user_id: str):
    """Processa verificação de completude de produto — usa mesmo tool do endpoint REST."""
    from tools import tool_verificar_completude_produto

    # Extrair nome do produto usando helper
    palavras = ["verificar", "verifique", "completude", "produto", "está", "esta",
                "completo", "falta", "informação", "informacao", "faltando", "o", "do", "da"]
    nome = extrair_termo(message, palavras)

    resultado = tool_verificar_completude_produto(nome_produto=nome if nome else None, user_id=user_id)

    if not resultado.get("success"):
        return f"""## ❌ Verificação de Completude

**Erro:** {resultado.get('error', 'Produto não encontrado')}

**Dica:** Informe o nome do produto. Exemplo: "Verifique completude do **Analisador XYZ**"
""", resultado

    produto = resultado.get("produto", {})
    completude = resultado.get("completude", {})
    campos_basicos = resultado.get("campos_basicos", [])
    mascara_check = resultado.get("mascara_check", [])
    subclasse_nome = resultado.get("subclasse_nome")

    status_emoji = {
        "completo": "✅",
        "quase_completo": "🟡",
        "incompleto": "🟠",
        "muito_incompleto": "🔴"
    }

    response = f"""## 📋 Verificação de Completude

### Produto: {produto.get('nome', 'N/A')}

**Status:** {status_emoji.get(completude.get('status'), '❓')} {completude.get('status', 'N/A').replace('_', ' ').title()}

| Métrica | Percentual |
|---------|-----------|
| **Geral** | {completude.get('percentual_geral', 0)}% |
| **Dados Básicos** | {completude.get('percentual_basicos', 0)}% |
| **Especificações** | {completude.get('percentual_mascara', 0)}% |

---

### Dados Básicos

"""
    for c in campos_basicos:
        emoji = "✅" if c["preenchido"] else "❌"
        valor = c["valor"] if c["preenchido"] else "Não preenchido"
        response += f"- {emoji} **{c['campo']}**: {valor}\n"

    if subclasse_nome and mascara_check:
        preenchidos = sum(1 for c in mascara_check if c["preenchido"])
        response += f"""
---

### Especificações — {subclasse_nome} ({preenchidos}/{len(mascara_check)})

"""
        faltantes = [c for c in mascara_check if not c["preenchido"]]
        if faltantes:
            response += "**Faltantes:**\n"
            for c in faltantes[:20]:
                un = f" ({c['unidade']})" if c.get("unidade") else ""
                response += f"- ❌ {c['campo']}{un}\n"
            if len(faltantes) > 20:
                response += f"- ... e mais {len(faltantes) - 20} campos\n"
    elif not subclasse_nome:
        response += "\n⚠️ Produto sem subclasse atribuída — não é possível verificar especificações contra a máscara.\n"

    recomendacoes = resultado.get("recomendacoes", [])
    if recomendacoes:
        response += "\n---\n\n### 💡 Recomendações\n\n"
        for rec in recomendacoes:
            response += f"- {rec}\n"

    return response, resultado


def processar_cadastrar_edital(message: str, user_id: str, intencao_resultado: dict = None):
    """
    Processa ação: Cadastrar edital manualmente no sistema.

    Extrai dados da mensagem do usuário:
    - Número do edital
    - Órgão
    - Objeto (descrição)
    - Modalidade (opcional)
    - Data de abertura (opcional)
    - UF (opcional)
    """
    empresa_id = get_current_empresa_id()
    from models import Edital
    from database import SessionLocal
    import re
    from datetime import datetime

    # Usar LLM para extrair dados estruturados da mensagem
    prompt_extracao = f"""Extraia os dados do edital da mensagem abaixo e retorne APENAS um JSON:

MENSAGEM: "{message}"

Extraia:
- numero: número/identificador do edital (ex: PE-001/2026, Pregão 15/2026)
- orgao: nome do órgão licitante
- objeto: descrição/objeto da licitação
- modalidade: uma de [pregao_eletronico, pregao_presencial, concorrencia, tomada_precos, convite, leilao, dispensa, inexigibilidade] (default: pregao_eletronico)
- data_abertura: data no formato YYYY-MM-DD (se mencionada)
- uf: sigla do estado (se mencionado)
- cidade: nome da cidade (se mencionado)
- valor_referencia: valor estimado (se mencionado, apenas número)

Retorne APENAS o JSON, sem explicações:
{{"numero": "...", "orgao": "...", "objeto": "...", "modalidade": "...", "data_abertura": null, "uf": null, "cidade": null, "valor_referencia": null}}"""

    try:
        resposta_llm = call_deepseek(
            [{"role": "user", "content": prompt_extracao}],
            max_tokens=500,
            model_override="deepseek-chat"
        )

        # Extrair JSON da resposta
        import json
        json_match = re.search(r'\{[\s\S]*?\}', resposta_llm)
        if not json_match:
            return """❌ **Não consegui extrair os dados do edital.**

Por favor, forneça pelo menos:
- **Número do edital** (ex: PE-001/2026)
- **Órgão** (ex: Hospital das Clínicas)
- **Objeto** (ex: Aquisição de equipamentos)

**Exemplo:**
```
Cadastre o edital PE-001/2026, órgão Hospital das Clínicas UFMG, objeto: Aquisição de analisadores hematológicos
```""", None

        dados = json.loads(json_match.group())

        # Validar campos obrigatórios
        if not dados.get("numero"):
            return "❌ **Número do edital é obrigatório.** Informe o número (ex: PE-001/2026)", None

        if not dados.get("orgao"):
            return "❌ **Órgão é obrigatório.** Informe o órgão licitante.", None

        if not dados.get("objeto"):
            return "❌ **Objeto é obrigatório.** Informe a descrição/objeto da licitação.", None

        # Criar edital no banco
        db = SessionLocal()
        try:
            # Verificar se já existe
            edital_existente = db.query(Edital).filter(
                Edital.numero == dados["numero"],
                Edital.empresa_id == empresa_id
            ).first()

            if edital_existente:
                return f"""⚠️ **Edital já cadastrado!**

**Número:** {edital_existente.numero}
**Órgão:** {edital_existente.orgao}
**Status:** {edital_existente.status}

Se deseja atualizar, use: "Atualize o edital {dados['numero']} com..." """, None

            # Criar novo edital
            novo_edital = Edital(
                user_id=user_id,
                empresa_id=empresa_id,
                numero=dados["numero"],
                orgao=dados["orgao"],
                objeto=dados["objeto"],
                modalidade=dados.get("modalidade", "pregao_eletronico"),
                status="novo",
                fonte="manual",
                uf=dados.get("uf"),
                cidade=dados.get("cidade"),
                valor_referencia=float(dados["valor_referencia"]) if dados.get("valor_referencia") else None
            )

            # Converter data_abertura se existir
            if dados.get("data_abertura"):
                try:
                    novo_edital.data_abertura = datetime.strptime(dados["data_abertura"], "%Y-%m-%d")
                except:
                    pass

            db.add(novo_edital)
            db.commit()
            db.refresh(novo_edital)

            response = f"""✅ **Edital cadastrado com sucesso!**

📋 **Dados do Edital:**
| Campo | Valor |
|-------|-------|
| **Número** | {novo_edital.numero} |
| **Órgão** | {novo_edital.orgao} |
| **Objeto** | {novo_edital.objeto[:100]}{'...' if len(novo_edital.objeto) > 100 else ''} |
| **Modalidade** | {novo_edital.modalidade} |
| **Status** | {novo_edital.status} |
| **UF** | {novo_edital.uf or '-'} |
| **Cidade** | {novo_edital.cidade or '-'} |

---
**Próximos passos:**
- Calcule a aderência: "Calcule aderência do produto X ao edital {novo_edital.numero}"
- Gere uma proposta: "Gere proposta para o edital {novo_edital.numero}"
- Liste seus editais: "Liste meus editais"
"""
            return response, {"edital_id": str(novo_edital.id), "numero": novo_edital.numero}

        finally:
            db.close()

    except json.JSONDecodeError as e:
        return f"❌ Erro ao interpretar dados: {str(e)}", None
    except Exception as e:
        print(f"[ERRO] processar_cadastrar_edital: {e}")
        return f"❌ Erro ao cadastrar edital: {str(e)}", None


# =============================================================================
# PROCESSADORES SPRINT 2: ALERTAS E AUTOMAÇÃO
# =============================================================================

def processar_configurar_alertas(message: str, user_id: str):
    """Processa configuração de alertas de prazo para editais."""
    import re
    from tools import tool_configurar_alertas

    msg = message.lower()

    # Extrair número do edital - aceita formatos: PE-123/2026, PE-TESTE/2026, PE 123, Pregão 123/2026
    match_edital = re.search(r'(PE[-\s]?[\w]+[-/]?\d*|[Pp]reg[aã]o\s*n?[ºo°]?\s*[\w/]+|\d{1,5}[/]\d{4})', message, re.IGNORECASE)
    edital_numero = match_edital.group(1).strip() if match_edital else None

    if not edital_numero:
        return "⚠️ Para configurar alertas, preciso saber qual edital. Informe o número do edital, por exemplo:\n\n*\"Configure alertas para o PE 123/2024\"*"

    # Extrair tempos (horas/minutos antes)
    tempos_minutos = []

    # Padrões de tempo
    match_horas = re.findall(r'(\d+)\s*(?:hora|h)', msg)
    match_dias = re.findall(r'(\d+)\s*(?:dia|d)', msg)
    match_minutos = re.findall(r'(\d+)\s*(?:minuto|min|m\b)', msg)

    for h in match_horas:
        tempos_minutos.append(int(h) * 60)
    for d in match_dias:
        tempos_minutos.append(int(d) * 1440)
    for m in match_minutos:
        tempos_minutos.append(int(m))

    # Se não especificou tempo, usar padrões
    if not tempos_minutos:
        tempos_minutos = [1440, 60, 15]  # 1 dia, 1 hora, 15 min

    # Detectar tipo de alerta
    tipo = "abertura"
    if "impugna" in msg:
        tipo = "impugnacao"
    elif "recurso" in msg:
        tipo = "recursos"
    elif "proposta" in msg:
        tipo = "proposta"

    # Detectar canais
    canais = {"email": True, "push": True}
    if "apenas email" in msg or "só email" in msg:
        canais = {"email": True, "push": False}
    elif "apenas push" in msg or "só push" in msg:
        canais = {"email": False, "push": True}

    resultado = tool_configurar_alertas(
        user_id=user_id,
        edital_numero=edital_numero,
        tempos_minutos=tempos_minutos,
        tipo=tipo,
        canais=canais
    )

    if resultado.get("success"):
        alertas = resultado.get("alertas_criados", [])
        msg_resp = f"✅ **Alertas configurados para {edital_numero}**\n\n"

        if alertas:
            msg_resp += "📋 **Alertas agendados:**\n"
            for a in alertas:
                msg_resp += f"- ⏰ {a['tempo_antes']} antes → {a['data_disparo']}\n"
        else:
            msg_resp += "ℹ️ Os alertas foram configurados com os tempos padrão.\n"

        msg_resp += f"\n🔔 **Canais:** Email: {'✅' if canais['email'] else '❌'} | Push: {'✅' if canais['push'] else '❌'}"

        return msg_resp
    else:
        return f"❌ {resultado.get('error', 'Erro ao configurar alertas')}"


def processar_listar_alertas(message: str, user_id: str):
    """Processa listagem de alertas configurados."""
    from tools import tool_listar_alertas
    msg = message.lower()

    apenas_agendados = "todos" not in msg and "histórico" not in msg and "historico" not in msg
    periodo_dias = 30

    if "semana" in msg:
        periodo_dias = 7
    elif "mês" in msg or "mes" in msg:
        periodo_dias = 30
    elif "ano" in msg:
        periodo_dias = 365

    resultado = tool_listar_alertas(
        user_id=user_id,
        apenas_agendados=apenas_agendados,
        periodo_dias=periodo_dias
    )

    if resultado.get("success"):
        editais_com_alertas = resultado.get("editais", [])
        total_alertas = resultado.get("total_alertas", 0)

        if total_alertas == 0:
            return "📭 Você não tem alertas configurados.\n\nPara criar alertas, diga algo como:\n*\"Configure alertas para o PE 123/2024 com 1 dia e 1 hora de antecedência\"*"

        msg_resp = f"🔔 **Seus Alertas** ({total_alertas} encontrados)\n\n"

        for ed in editais_com_alertas:
            edital_info = ed.get('edital', {})
            alertas = ed.get('alertas', [])
            numero = edital_info.get('numero', 'N/A')
            orgao = edital_info.get('orgao', '')[:40]

            msg_resp += f"📋 **{numero}** - {orgao}\n"

            for a in alertas:
                status_icon = {"agendado": "⏳", "disparado": "✅", "lido": "👁️", "cancelado": "❌"}.get(a.get('status', ''), "📌")
                tipo = a.get('tipo', 'abertura').title()
                data_disparo = a.get('data_disparo', 'N/A')
                # Formatar data ISO para legível
                if data_disparo and data_disparo != 'N/A':
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(data_disparo)
                        data_disparo = dt.strftime("%d/%m/%Y %H:%M")
                    except:
                        pass
                tempo_antes = a.get('tempo_antes', '')

                msg_resp += f"   {status_icon} {tipo} - 📅 {data_disparo}\n"
                if tempo_antes:
                    msg_resp += f"      ⏰ {tempo_antes} antes da abertura\n"

            msg_resp += "\n"

        return msg_resp
    else:
        return f"❌ {resultado.get('error', 'Erro ao listar alertas')}"


def processar_dashboard_prazos(message: str, user_id: str):
    empresa_id = get_current_empresa_id()
    """Processa exibição do dashboard de prazos."""
    from tools import tool_dashboard_prazos
    msg = message.lower()

    dias = 7  # Padrão: próximos 7 dias
    if "mês" in msg or "mes" in msg or "30" in msg:
        dias = 30
    elif "15" in msg:
        dias = 15
    elif "semana" in msg or "7" in msg:
        dias = 7

    resultado = tool_dashboard_prazos(user_id=user_id, empresa_id=empresa_id, dias=dias)

    if resultado.get("success"):
        editais = resultado.get("editais", [])
        stats = resultado.get("estatisticas", {})

        msg_resp = f"📊 **Dashboard de Prazos** (próximos {dias} dias)\n\n"

        # Resumo (estatísticas: total, criticos, altos, medios, normais)
        msg_resp += "### 📈 Resumo\n"
        msg_resp += f"- Total: **{stats.get('total', 0)}** editais\n"
        msg_resp += f"- 🔴 Críticos (< 1 dia): **{stats.get('criticos', 0)}**\n"
        msg_resp += f"- 🟠 Altos (1-3 dias): **{stats.get('altos', 0)}**\n"
        msg_resp += f"- 🟡 Médios (3-7 dias): **{stats.get('medios', 0)}**\n"
        msg_resp += f"- 🟢 Normais (> 7 dias): **{stats.get('normais', 0)}**\n\n"

        if not editais:
            msg_resp += "ℹ️ Nenhum edital com prazo neste período.\n"
        else:
            msg_resp += "### 📋 Editais por Prazo\n\n"

            for e in editais[:10]:  # Limitar a 10
                # Estrutura: edital{id,numero,orgao,...}, datas{...}, tempo_restante{texto,dias,horas}, urgencia, emoji, alertas_configurados
                edital_info = e.get('edital', {})
                datas = e.get('datas', {})
                tempo = e.get('tempo_restante', {})
                icon = e.get('emoji', '🟢')

                numero = edital_info.get('numero', 'N/A')
                orgao = edital_info.get('orgao', '')[:40]
                data_abertura = datas.get('abertura_formatada', 'N/A')
                tempo_texto = tempo.get('texto', 'N/A')
                alertas_qtd = e.get('alertas_configurados', 0)

                msg_resp += f"{icon} **{numero}** - {orgao}\n"
                msg_resp += f"   📅 Abertura: {data_abertura}\n"
                msg_resp += f"   ⏱️ **{tempo_texto}**\n"
                if alertas_qtd:
                    msg_resp += f"   🔔 Alertas: {alertas_qtd}\n"
                msg_resp += "\n"

        return msg_resp
    else:
        return f"❌ {resultado.get('error', 'Erro ao carregar dashboard')}"


def processar_calendario_editais(message: str, user_id: str):
    empresa_id = get_current_empresa_id()
    """Processa exibição do calendário de editais."""
    from datetime import datetime
    from tools import tool_calendario_editais
    import re

    msg = message.lower()
    hoje = datetime.now()

    # Detectar mês/ano
    mes = hoje.month
    ano = hoje.year

    # Padrões para mês
    meses_pt = {
        "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
        "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
        "outubro": 10, "novembro": 11, "dezembro": 12
    }

    for nome, num in meses_pt.items():
        if nome in msg:
            mes = num
            break

    # Detectar ano
    match_ano = re.search(r'20\d{2}', msg)
    if match_ano:
        ano = int(match_ano.group())

    resultado = tool_calendario_editais(user_id=user_id, empresa_id=empresa_id, mes=mes, ano=ano)

    if resultado.get("success"):
        calendario = resultado.get("calendario", {})
        mes_nome = resultado.get("mes_nome", "")
        total = resultado.get("total_editais", 0)

        msg_resp = f"📅 **Calendário de Editais - {mes_nome} {ano}**\n\n"
        msg_resp += f"Total: **{total}** editais no mês\n\n"

        if not calendario:
            msg_resp += "ℹ️ Nenhum edital com data neste mês.\n"
        else:
            # Ordenar por dia
            for dia in sorted(calendario.keys(), key=int):
                editais_dia = calendario[dia]
                msg_resp += f"### 📆 Dia {dia}\n"

                for e in editais_dia:
                    status_icon = {"novo": "🆕", "analisando": "🔍", "participar": "✅", "proposta_enviada": "📤"}.get(e['status'], "📌")
                    msg_resp += f"{status_icon} **{e['numero']}** - {e['orgao'][:35]}\n"
                    if e.get('horario'):
                        msg_resp += f"   ⏰ {e['horario']}\n"
                msg_resp += "\n"

        return msg_resp
    else:
        return f"❌ {resultado.get('error', 'Erro ao carregar calendário')}"


def processar_configurar_monitoramento(message: str, user_id: str):
    """Processa configuração de monitoramento automático de editais."""
    import re
    from tools import tool_configurar_monitoramento

    msg = message.lower()

    # Extrair termo de busca - geralmente vem após "monitore" ou "monitorar"
    match_termo = re.search(r'monitor[ea]?\s+(?:editais\s+(?:de|para|sobre)\s+)?(.+?)(?:\s+(?:no|na|em|com|para)|$)', msg)
    termo = match_termo.group(1).strip() if match_termo else None

    if not termo:
        # Tentar extrair de outra forma
        match_termo2 = re.search(r'(?:busca automática|acompanhar)\s+(?:de\s+)?(.+?)(?:\s+(?:no|na|em)|$)', msg)
        termo = match_termo2.group(1).strip() if match_termo2 else None

    if not termo:
        return "⚠️ Para configurar um monitoramento, preciso saber o que monitorar.\n\nExemplos:\n- *\"Monitore editais de equipamentos laboratoriais\"*\n- *\"Configure monitoramento para reagentes em SP e MG\"*"

    # Detectar fontes
    fontes = []
    if "pncp" in msg:
        fontes.append("pncp")
    if "comprasnet" in msg:
        fontes.append("comprasnet")
    if "bec" in msg:
        fontes.append("bec")
    if not fontes:
        fontes = ["pncp"]  # Padrão

    # Detectar UFs
    ufs = []
    ufs_validas = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
                   "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
                   "SP", "SE", "TO"]
    for uf in ufs_validas:
        if uf.lower() in msg or uf in message:
            ufs.append(uf)

    # Detectar frequência
    frequencia_horas = 4  # Padrão
    if "hora em hora" in msg or "1 hora" in msg:
        frequencia_horas = 1
    elif "2 hora" in msg:
        frequencia_horas = 2
    elif "6 hora" in msg:
        frequencia_horas = 6
    elif "12 hora" in msg:
        frequencia_horas = 12
    elif "diário" in msg or "diario" in msg or "24 hora" in msg:
        frequencia_horas = 24

    # Detectar score mínimo
    score_minimo = 70
    match_score = re.search(r'score\s*(?:mínimo|minimo)?\s*(?:de\s+)?(\d+)', msg)
    if match_score:
        score_minimo = int(match_score.group(1))

    resultado = tool_configurar_monitoramento(
        user_id=user_id,
        termo=termo,
        fontes=fontes,
        ufs=ufs if ufs else None,
        frequencia_horas=frequencia_horas,
        score_minimo=score_minimo
    )

    if resultado.get("success"):
        mon = resultado.get("monitoramento", {})
        msg_resp = f"✅ **Monitoramento Configurado**\n\n"
        msg_resp += f"🔍 **Termo:** {mon.get('termo', termo)}\n"
        msg_resp += f"📡 **Fontes:** {', '.join(mon.get('fontes', fontes))}\n"
        msg_resp += f"📍 **UFs:** {', '.join(mon.get('ufs', ufs)) if mon.get('ufs') else 'Todas'}\n"
        msg_resp += f"⏱️ **Frequência:** A cada {mon.get('frequencia_horas', frequencia_horas)} hora(s)\n"
        msg_resp += f"📊 **Score mínimo para alerta:** {mon.get('score_minimo', score_minimo)}%\n"
        msg_resp += f"\n🆔 ID: `{mon.get('id', 'N/A')}`"

        return msg_resp
    else:
        return f"❌ {resultado.get('error', 'Erro ao configurar monitoramento')}"


def processar_listar_monitoramentos(message: str, user_id: str):
    empresa_id = get_current_empresa_id()
    """Processa listagem de monitoramentos configurados."""
    from tools import tool_listar_monitoramentos
    msg = message.lower()
    apenas_ativos = "todos" not in msg and "inativos" not in msg

    resultado = tool_listar_monitoramentos(user_id=user_id, empresa_id=empresa_id, apenas_ativos=apenas_ativos)

    if resultado.get("success"):
        monitoramentos = resultado.get("monitoramentos", [])

        if not monitoramentos:
            return "📭 Você não tem monitoramentos configurados.\n\nPara criar um monitoramento, diga algo como:\n*\"Monitore editais de equipamentos laboratoriais no PNCP\"*"

        msg_resp = f"🔍 **Seus Monitoramentos** ({len(monitoramentos)} encontrados)\n\n"

        for m in monitoramentos:
            status_icon = "✅" if m.get('ativo') else "⏸️"
            msg_resp += f"{status_icon} **{m['termo']}**\n"
            msg_resp += f"   📡 Fontes: {', '.join(m.get('fontes', []))}\n"
            msg_resp += f"   📍 UFs: {', '.join(m.get('ufs', [])) if m.get('ufs') else 'Todas'}\n"
            msg_resp += f"   ⏱️ A cada {m.get('frequencia_horas', 4)}h\n"
            msg_resp += f"   📊 Score mínimo: {m.get('score_minimo', 70)}%\n"
            if m.get('ultima_execucao'):
                msg_resp += f"   🕐 Última execução: {m['ultima_execucao']}\n"
            if m.get('editais_encontrados'):
                msg_resp += f"   📋 Editais encontrados: {m['editais_encontrados']}\n"
            msg_resp += "\n"

        return msg_resp
    else:
        return f"❌ {resultado.get('error', 'Erro ao listar monitoramentos')}"


def processar_desativar_monitoramento(message: str, user_id: str):
    """Processa desativação de monitoramento."""
    import re
    from tools import tool_desativar_monitoramento

    msg = message.lower()

    # Tentar extrair termo do monitoramento
    match_termo = re.search(r'(?:desativ|par|cancel|remov)[ea]?\s+(?:o\s+)?monitoramento\s+(?:de\s+)?(.+)', msg)
    termo = match_termo.group(1).strip() if match_termo else None

    # Tentar extrair ID
    match_id = re.search(r'id[:\s]+([a-f0-9-]+)', msg, re.IGNORECASE)
    monitoramento_id = match_id.group(1) if match_id else None

    if not termo and not monitoramento_id:
        return "⚠️ Para desativar um monitoramento, informe o termo ou ID.\n\nExemplos:\n- *\"Desative o monitoramento de equipamentos laboratoriais\"*\n- *\"Pare de monitorar reagentes\"*"

    resultado = tool_desativar_monitoramento(
        user_id=user_id,
        termo=termo,
        monitoramento_id=monitoramento_id
    )

    if resultado.get("success"):
        return f"✅ Monitoramento desativado com sucesso!\n\n🔍 **Termo:** {resultado.get('termo', termo or 'N/A')}"
    else:
        return f"❌ {resultado.get('error', 'Erro ao desativar monitoramento')}"


def processar_configurar_notificacoes(message: str, user_id: str):
    """Processa configuração de preferências de notificação."""
    import re
    from tools import tool_configurar_preferencias_notificacao

    msg = message.lower()

    # Extrair email
    match_email = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', message)
    email = match_email.group() if match_email else None

    # Detectar habilitação
    email_habilitado = True
    push_habilitado = True

    if "desativar email" in msg or "sem email" in msg:
        email_habilitado = False
    if "desativar push" in msg or "sem push" in msg:
        push_habilitado = False

    # Detectar horários
    horario_inicio = None
    horario_fim = None

    match_horario = re.search(r'(?:das|entre)\s+(\d{1,2})(?:h|:00)?\s+(?:às|e|até)\s+(\d{1,2})(?:h|:00)?', msg)
    if match_horario:
        horario_inicio = f"{int(match_horario.group(1)):02d}:00"
        horario_fim = f"{int(match_horario.group(2)):02d}:00"

    resultado = tool_configurar_preferencias_notificacao(
        user_id=user_id,
        email_habilitado=email_habilitado,
        push_habilitado=push_habilitado,
        email_notificacao=email,
        horario_inicio=horario_inicio,
        horario_fim=horario_fim
    )

    if resultado.get("success"):
        prefs = resultado.get("preferencias", {})
        msg_resp = "✅ **Preferências de Notificação Atualizadas**\n\n"
        msg_resp += f"📧 **Email:** {'✅ Habilitado' if prefs.get('email_habilitado') else '❌ Desabilitado'}\n"
        if prefs.get('email_notificacao'):
            msg_resp += f"   Enviar para: {prefs['email_notificacao']}\n"
        msg_resp += f"🔔 **Push:** {'✅ Habilitado' if prefs.get('push_habilitado') else '❌ Desabilitado'}\n"

        if prefs.get('horario_inicio') and prefs.get('horario_fim'):
            msg_resp += f"⏰ **Horário:** {prefs['horario_inicio']} às {prefs['horario_fim']}\n"

        return msg_resp
    else:
        return f"❌ {resultado.get('error', 'Erro ao configurar notificações')}"


def processar_historico_notificacoes(message: str, user_id: str):
    """Processa listagem do histórico de notificações."""
    from tools import tool_historico_notificacoes
    msg = message.lower()

    apenas_nao_lidas = "não lida" in msg or "nao lida" in msg or "pendente" in msg

    limite = 20
    if "últimas 10" in msg or "ultimas 10" in msg:
        limite = 10
    elif "últimas 50" in msg or "ultimas 50" in msg:
        limite = 50

    resultado = tool_historico_notificacoes(
        user_id=user_id,
        limite=limite,
        apenas_nao_lidas=apenas_nao_lidas
    )

    if resultado.get("success"):
        notificacoes = resultado.get("notificacoes", [])
        nao_lidas = resultado.get("nao_lidas", 0)

        if not notificacoes:
            return "📭 Você não tem notificações.\n\nAs notificações aparecem quando:\n- Alertas de prazo são disparados\n- Novos editais são encontrados pelo monitoramento\n- O sistema precisa informar algo importante"

        msg_resp = f"📬 **Suas Notificações** ({len(notificacoes)} exibidas"
        if nao_lidas > 0:
            msg_resp += f", {nao_lidas} não lidas"
        msg_resp += ")\n\n"

        for n in notificacoes:
            tipo_icon = {
                "alerta_prazo": "⏰",
                "novo_edital": "📋",
                "alta_aderencia": "⭐",
                "resultado": "📊",
                "sistema": "🔧"
            }.get(n.get('tipo'), "📌")

            lida_icon = "👁️" if n.get('lida') else "🔵"

            msg_resp += f"{lida_icon} {tipo_icon} **{n['titulo']}**\n"
            msg_resp += f"   {n['mensagem'][:100]}{'...' if len(n.get('mensagem', '')) > 100 else ''}\n"
            msg_resp += f"   🕐 {n['created_at']}\n\n"

        return msg_resp
    else:
        return f"❌ {resultado.get('error', 'Erro ao carregar notificações')}"


def processar_extrair_datas_edital(message: str, user_id: str, texto_pdf: str = None):
    """Processa extração de datas importantes de um edital."""
    import re
    from tools import tool_extrair_datas_edital

    # Se não tem texto PDF, informar como usar
    if not texto_pdf:
        # Verificar se há número de edital para buscar
        match_edital = re.search(r'(PE[-]?\d+[-/]?\d*|[Pp]reg[aã]o\s*n?[ºo°]?\s*[\d/]+|\d{1,5}[/]\d{4})', message, re.IGNORECASE)

        if match_edital:
            edital_numero = match_edital.group(1)
            return f"⚠️ Para extrair as datas do edital **{edital_numero}**, faça upload do PDF do edital.\n\nApós o upload, direi:\n*\"Extraia as datas do edital {edital_numero}\"*"
        else:
            return "⚠️ Para extrair datas de um edital, faça upload do PDF primeiro.\n\nApós o upload, diga:\n*\"Extraia as datas do edital PE 123/2024\"*"

    # Se temos texto PDF, extrair datas
    resultado = tool_extrair_datas_edital(
        user_id=user_id,
        texto_edital=texto_pdf
    )

    if resultado.get("success"):
        datas = resultado.get("datas", {})
        msg_resp = "📅 **Datas Extraídas do Edital**\n\n"

        if datas.get("data_abertura"):
            msg_resp += f"📆 **Data de Abertura:** {datas['data_abertura']}\n"
        if datas.get("horario_abertura"):
            msg_resp += f"⏰ **Horário:** {datas['horario_abertura']}\n"
        if datas.get("data_limite_propostas"):
            msg_resp += f"📝 **Limite para Propostas:** {datas['data_limite_propostas']}\n"
        if datas.get("data_impugnacao"):
            msg_resp += f"⚠️ **Prazo Impugnação:** {datas['data_impugnacao']}\n"
        if datas.get("data_recursos"):
            msg_resp += f"📑 **Prazo Recursos:** {datas['data_recursos']}\n"
        if datas.get("data_publicacao"):
            msg_resp += f"📰 **Data Publicação:** {datas['data_publicacao']}\n"

        msg_resp += "\n💡 *Deseja configurar alertas para estas datas?*"

        return msg_resp
    else:
        return f"❌ {resultado.get('error', 'Erro ao extrair datas')}"


def processar_cancelar_alerta(message: str, user_id: str):
    """Processa cancelamento de alertas."""
    import re
    from tools import tool_cancelar_alerta

    msg = message.lower()

    # Extrair número do edital
    match_edital = re.search(r'(PE[-]?\d+[-/]?\d*|[Pp]reg[aã]o\s*n?[ºo°]?\s*[\d/]+|\d{1,5}[/]\d{4})', message, re.IGNORECASE)
    edital_numero = match_edital.group(1) if match_edital else None

    # Extrair ID do alerta
    match_id = re.search(r'alerta[:\s]+([a-f0-9-]+)', msg, re.IGNORECASE)
    alerta_id = match_id.group(1) if match_id else None

    # Cancelar todos?
    cancelar_todos = "todos" in msg

    if not edital_numero and not alerta_id and not cancelar_todos:
        return "⚠️ Para cancelar alertas, informe o edital ou o ID do alerta.\n\nExemplos:\n- *\"Cancele os alertas do PE 123/2024\"*\n- *\"Cancele todos os alertas\"*"

    resultado = tool_cancelar_alerta(
        user_id=user_id,
        alerta_id=alerta_id,
        edital_numero=edital_numero,
        cancelar_todos=cancelar_todos
    )

    if resultado.get("success"):
        qtd = resultado.get("cancelados", 0)
        msg_resp = f"✅ **{qtd} alerta(s) cancelado(s)**\n\n"

        if edital_numero:
            msg_resp += f"📋 Edital: {edital_numero}"

        return msg_resp
    else:
        return f"❌ {resultado.get('error', 'Erro ao cancelar alertas')}"


# =============================================================================
# ANÁLISE DE EDITAIS (Resumir e Perguntar)
# =============================================================================

def processar_resumir_edital(message: str, user_id: str, intencao_resultado: dict = None):
    """
    Processa ação: Resumir um edital cadastrado no sistema.
    Gera um resumo executivo com principais informações.

    Returns: (response_text, resultado_dict)
    """
    empresa_id = get_current_empresa_id()
    import re
    db = get_db()

    try:
        # Extrair número do edital da mensagem
        edital_numero = None
        if intencao_resultado and intencao_resultado.get("edital"):
            edital_numero = intencao_resultado.get("edital")
        else:
            # Tentar extrair padrões como PE-001/2026, PE001/2026, 001/2026
            padrao = re.search(r'(PE[-\s]?\d+[/\-]\d{4}|\d+[/\-]\d{4})', message, re.IGNORECASE)
            if padrao:
                edital_numero = padrao.group(1)

        if not edital_numero:
            return (
                "## ❌ Número do Edital Não Informado\n\n"
                "Por favor, informe o número do edital que deseja resumir.\n\n"
                "**Exemplos:**\n"
                "- \"Resuma o edital PE-001/2026\"\n"
                "- \"Resumo do edital 123/2025\"\n"
                "- \"Faça um resumo do edital PE-041/2026\"",
                {"error": "Número do edital não informado"}
            )

        # Buscar edital no banco
        edital = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.numero.ilike(f"%{edital_numero.replace('-', '%').replace('/', '%')}%")
        ).first()

        if not edital:
            return (
                f"## ❌ Edital Não Encontrado\n\n"
                f"O edital **{edital_numero}** não foi encontrado no seu cadastro.\n\n"
                "**Dica:** Use \"Liste meus editais\" para ver os editais cadastrados.",
                {"error": f"Edital {edital_numero} não encontrado"}
            )

        # Buscar requisitos do edital
        from models import EditalRequisito
        requisitos = db.query(EditalRequisito).filter(
            EditalRequisito.edital_id == edital.id
        ).all()

        # Montar contexto para o resumo
        contexto = f"""
EDITAL: {edital.numero}
ÓRGÃO: {edital.orgao or 'Não informado'}
OBJETO: {edital.objeto or 'Não informado'}
MODALIDADE: {edital.modalidade or 'Não informada'}
VALOR DE REFERÊNCIA: {f'R$ {edital.valor_referencia:,.2f}' if edital.valor_referencia else 'Não informado'}
DATA DE ABERTURA: {edital.data_abertura.strftime('%d/%m/%Y %H:%M') if edital.data_abertura else 'Não informada'}
DATA DE PUBLICAÇÃO: {edital.data_publicacao.strftime('%d/%m/%Y') if edital.data_publicacao else 'Não informada'}
UF: {edital.uf or 'Não informada'}
CIDADE: {edital.cidade or 'Não informada'}
STATUS: {edital.status or 'novo'}

REQUISITOS ({len(requisitos)} encontrados):
"""
        for req in requisitos[:20]:  # Limitar a 20 requisitos
            obrig = "OBRIGATÓRIO" if req.obrigatorio else "Desejável"
            contexto += f"- [{obrig}] {req.descricao[:200]}\n"

        if len(requisitos) > 20:
            contexto += f"\n... e mais {len(requisitos) - 20} requisitos"

        # Chamar LLM para gerar resumo
        prompt_resumo = f"""Faça um RESUMO EXECUTIVO do seguinte edital de licitação.

O resumo deve ser objetivo e incluir:
1. **Objeto**: O que está sendo licitado (em 1-2 frases)
2. **Valor**: Valor de referência e observações
3. **Prazos**: Data de abertura e prazos importantes
4. **Principais Requisitos**: Os 3-5 requisitos mais importantes/restritivos
5. **Alertas**: Pontos de atenção para participação

DADOS DO EDITAL:
{contexto}

Formate a resposta em Markdown com emojis para facilitar a leitura."""

        messages = [{"role": "user", "content": prompt_resumo}]

        resumo = call_deepseek(messages, max_tokens=2000)

        response_text = f"""## 📋 Resumo do Edital {edital.numero}

{resumo}

---
📊 **Dados do Sistema:**
- Status: {edital.status or 'novo'}
- Requisitos cadastrados: {len(requisitos)}
- URL: {edital.url or 'Não disponível'}
"""

        return response_text, {"success": True, "edital": edital.numero, "requisitos": len(requisitos)}

    except Exception as e:
        return f"## ❌ Erro ao Resumir Edital\n\n{str(e)}", {"error": str(e)}
    finally:
        db.close()


def processar_perguntar_edital(message: str, user_id: str, intencao_resultado: dict = None):
    """
    Processa ação: Responder dúvidas sobre um edital específico.

    Fluxo:
    1. Tenta responder com dados cadastrados no banco
    2. Se LLM indicar que não encontrou a informação, verifica se tem PDF
    3. Se tiver PDF, lê e responde
    4. Se não tiver PDF, pede para o usuário fazer upload

    Returns: (response_text, resultado_dict)
    """
    empresa_id = get_current_empresa_id()
    import re
    import os
    db = get_db()

    try:
        # Extrair número do edital da mensagem
        edital_numero = None
        if intencao_resultado and intencao_resultado.get("edital"):
            edital_numero = intencao_resultado.get("edital")
        else:
            # Tentar extrair padrões como PE-001/2026, PE001/2026, 001/2026
            padrao = re.search(r'(PE[-\s]?\d+[/\-]\d{4}|\d+[/\-]\d{4})', message, re.IGNORECASE)
            if padrao:
                edital_numero = padrao.group(1)

        if not edital_numero:
            return (
                "## ❌ Número do Edital Não Informado\n\n"
                "Por favor, informe o número do edital sobre o qual deseja perguntar.\n\n"
                "**Exemplos:**\n"
                "- \"Qual o prazo de entrega do edital PE-001/2026?\"\n"
                "- \"O edital PE-001/2026 exige garantia?\"\n"
                "- \"Quais documentos são exigidos no PE-041/2026?\"",
                {"error": "Número do edital não informado"}
            )

        # Buscar edital no banco
        edital = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.numero.ilike(f"%{edital_numero.replace('-', '%').replace('/', '%')}%")
        ).first()

        if not edital:
            return (
                f"## ❌ Edital Não Encontrado\n\n"
                f"O edital **{edital_numero}** não foi encontrado no seu cadastro.\n\n"
                "**Dica:** Use \"Liste meus editais\" para ver os editais cadastrados.\n"
                f"Ou busque o edital: \"Busque o edital {edital_numero} no PNCP\"",
                {"error": f"Edital {edital_numero} não encontrado"}
            )

        # Buscar requisitos do edital
        from models import EditalRequisito, EditalDocumento
        requisitos = db.query(EditalRequisito).filter(
            EditalRequisito.edital_id == edital.id
        ).all()

        # Buscar documentos PDF do edital
        documentos = db.query(EditalDocumento).filter(
            EditalDocumento.edital_id == edital.id
        ).all()

        # Montar contexto do edital com dados cadastrados
        contexto_banco = f"""
EDITAL: {edital.numero}
ÓRGÃO: {edital.orgao or 'Não informado'}
OBJETO: {edital.objeto or 'Não informado'}
MODALIDADE: {edital.modalidade or 'Não informada'}
VALOR DE REFERÊNCIA: {f'R$ {edital.valor_referencia:,.2f}' if edital.valor_referencia else 'Não informado'}
DATA DE ABERTURA: {edital.data_abertura.strftime('%d/%m/%Y %H:%M') if edital.data_abertura else 'Não informada'}
DATA DE PUBLICAÇÃO: {edital.data_publicacao.strftime('%d/%m/%Y') if edital.data_publicacao else 'Não informada'}
UF: {edital.uf or 'Não informada'}
CIDADE: {edital.cidade or 'Não informada'}
STATUS: {edital.status or 'novo'}

REQUISITOS DO EDITAL ({len(requisitos)} requisitos):
"""
        for req in requisitos:
            obrig = "[OBRIGATÓRIO]" if req.obrigatorio else "[Desejável]"
            tipo = f"({req.tipo})" if req.tipo else ""
            contexto_banco += f"- {obrig} {tipo} {req.descricao}\n"

        if not requisitos:
            contexto_banco += "- Nenhum requisito cadastrado.\n"

        # Detectar se é pergunta específica que provavelmente está no PDF
        msg_lower = message.lower()
        perguntas_especificas = [
            'prazo de entrega', 'prazo entrega', 'dias para entrega', 'entregar em',
            'garantia', 'garantir',
            'local de entrega', 'onde entregar', 'endereço de entrega',
            'forma de pagamento', 'pagamento', 'pagar',
            'penalidade', 'multa', 'sanção', 'sanções',
            'documentos de habilitação', 'habilitação', 'documentos exigidos',
            'qualificação técnica', 'qualificacao tecnica', 'atestado', 'certidão',
            'requisitos técnicos', 'requisitos tecnicos', 'requisito tecnico', 'requisito técnico',
            'exigências técnicas', 'exigencias tecnicas', 'especificações', 'especificacoes',
            'termo de referência', 'anexo', 'especificação técnica', 'especificacao tecnica',
            'cláusula', 'item', 'subitem',
            'critério de julgamento', 'desempate', 'lance',
            'contrato', 'vigência', 'aditivo',
            'reajuste', 'índice', 'igpm', 'ipca',
            'classifique', 'classificar', 'categoria',
        ]
        eh_pergunta_especifica = any(p in msg_lower for p in perguntas_especificas)

        # Verificar se tem PDF disponível ANTES de tentar banco
        doc_com_texto = None
        for doc in documentos:
            if doc.texto_extraido and len(doc.texto_extraido) > 100:
                doc_com_texto = doc
                break
            elif doc.path_arquivo and os.path.exists(doc.path_arquivo):
                try:
                    from tools import tool_processar_upload
                    texto = tool_processar_upload(doc.path_arquivo)
                    if texto and len(texto) > 100:
                        doc.texto_extraido = texto[:200000]  # Aumentar limite
                        doc.processado = True
                        db.commit()
                        doc_com_texto = doc
                        break
                except Exception as e:
                    print(f"[PERGUNTAR_EDITAL] Erro ao ler PDF {doc.nome_arquivo}: {e}")

        # Se é pergunta específica E tem PDF, ir direto pro PDF
        if eh_pergunta_especifica and doc_com_texto:
            print(f"[PERGUNTAR_EDITAL] Pergunta específica detectada. Indo direto pro PDF...")
        else:
            # PASSO 1: Tentar responder com dados do banco (perguntas gerais)
            prompt_banco = f"""Você é um assistente especializado em licitações públicas.

DADOS CADASTRADOS DO EDITAL:
{contexto_banco}

PERGUNTA DO USUÁRIO:
{message}

INSTRUÇÕES IMPORTANTES:
1. Responda a pergunta usando os dados acima
2. Para perguntas amplas como "tudo sobre", "informações", "detalhes", "resumo": apresente TODOS os dados disponíveis de forma organizada
3. SOMENTE responda "INFORMACAO_NAO_ENCONTRADA_NO_CADASTRO" se a pergunta for sobre algo MUITO ESPECÍFICO que realmente não está nos dados (ex: cláusula específica, anexo, item de planilha)
4. Se há dados relevantes para responder, mesmo que parcialmente, responda com o que tem
5. Seja objetivo e organize a resposta em seções quando apropriado

Responda em Markdown (ou a frase especial APENAS se realmente não houver dados relevantes)."""

            messages = [{"role": "user", "content": prompt_banco}]
            resposta_banco = call_deepseek(messages, max_tokens=2000)

            # Verificar se encontrou a informação no banco
            if "INFORMACAO_NAO_ENCONTRADA" not in resposta_banco.upper() and "NÃO ENCONTRADA" not in resposta_banco.upper() and "NÃO CONSTA" not in resposta_banco.upper():
                # Encontrou no banco - retornar resposta
                response_text = f"""## 💬 Resposta sobre o Edital {edital.numero}

{resposta_banco}

---
📋 **Edital:** {edital.numero}
🏢 **Órgão:** {edital.orgao or 'N/I'}
📊 **Fonte:** Dados cadastrados no sistema
"""
                return response_text, {"success": True, "edital": edital.numero, "fonte": "banco"}

            print(f"[PERGUNTAR_EDITAL] Informação não encontrada no banco. Verificando PDFs...")

        # doc_com_texto já foi verificado antes
        if doc_com_texto and doc_com_texto.texto_extraido:
            # PASSO 3: Tem PDF - ler e responder
            print(f"[PERGUNTAR_EDITAL] Lendo PDF: {doc_com_texto.nome_arquivo}")

            texto_completo = doc_com_texto.texto_extraido
            print(f"[PERGUNTAR_EDITAL] Texto total: {len(texto_completo)} caracteres")

            # Extrair palavras-chave da pergunta para busca inteligente
            msg_lower = message.lower()
            palavras_busca = []

            # Mapeamento de termos comuns em editais
            if any(p in msg_lower for p in ['prazo', 'entrega', 'entregar']):
                palavras_busca.extend(['prazo', 'entrega', 'dias', 'úteis', 'corridos', 'fornecimento'])
            if any(p in msg_lower for p in ['garantia', 'garantir']):
                palavras_busca.extend(['garantia', 'garantir', 'meses', 'anos', 'cobertura'])
            if any(p in msg_lower for p in ['pagamento', 'pagar', 'valor']):
                palavras_busca.extend(['pagamento', 'pagar', 'fatura', 'nota fiscal', 'dias'])
            if any(p in msg_lower for p in ['local', 'onde', 'endereço']):
                palavras_busca.extend(['local', 'entrega', 'endereço', 'sede', 'almoxarifado'])
            if any(p in msg_lower for p in ['documento', 'habilitação', 'exigência', 'exige']):
                palavras_busca.extend(['habilitação', 'documento', 'certidão', 'atestado', 'declaração'])
            if any(p in msg_lower for p in ['penalidade', 'multa', 'sanção']):
                palavras_busca.extend(['penalidade', 'multa', 'sanção', 'advertência', 'suspensão'])

            # Chunkar o documento (chunks de 2000 caracteres com overlap de 300)
            chunk_size = 2000
            overlap = 300
            chunks = []
            for i in range(0, len(texto_completo), chunk_size - overlap):
                chunk = texto_completo[i:i + chunk_size]
                chunks.append((i, chunk))  # (posição, texto)

            print(f"[PERGUNTAR_EDITAL] Documento dividido em {len(chunks)} chunks")

            # Criar frases de busca combinadas (mais específicas)
            frases_exatas = []
            if any(p in msg_lower for p in ['prazo', 'entrega']):
                frases_exatas.extend(['prazo de entrega', 'prazo para entrega', 'entrega do objeto',
                                      'prazo de fornecimento', 'dias para entrega', 'dias após'])
            if any(p in msg_lower for p in ['garantia']):
                frases_exatas.extend(['prazo de garantia', 'garantia de', 'meses de garantia', 'anos de garantia'])
            if any(p in msg_lower for p in ['pagamento']):
                frases_exatas.extend(['prazo de pagamento', 'pagamento será', 'dias após', 'nota fiscal'])
            if any(p in msg_lower for p in ['local']):
                frases_exatas.extend(['local de entrega', 'endereço de entrega', 'entregar no', 'entregue no'])

            # Buscar nos chunks - priorizar frases exatas
            chunks_relevantes = []
            for pos, chunk in chunks:
                chunk_lower = chunk.lower()

                # Score alto para frases exatas
                score_exato = sum(3 for f in frases_exatas if f in chunk_lower)
                # Score menor para palavras individuais
                score_palavras = sum(1 for p in palavras_busca if p in chunk_lower)

                score_total = score_exato + score_palavras
                if score_total > 0:
                    chunks_relevantes.append((score_total, pos, chunk))

            # Ordenar por relevância (maior score primeiro)
            chunks_relevantes.sort(key=lambda x: -x[0])

            # Pegar os 12 chunks mais relevantes
            chunks_relevantes = chunks_relevantes[:12]
            print(f"[PERGUNTAR_EDITAL] {len(chunks_relevantes)} chunks relevantes encontrados")
            if chunks_relevantes:
                print(f"[PERGUNTAR_EDITAL] Top scores: {[c[0] for c in chunks_relevantes[:5]]}")

            # Montar contexto com chunks relevantes
            if chunks_relevantes:
                texto_pdf = f"=== TRECHOS RELEVANTES DO EDITAL ===\n\n"
                for i, (score, pos, chunk) in enumerate(chunks_relevantes, 1):
                    texto_pdf += f"--- Trecho {i} (posição {pos}) ---\n{chunk}\n\n"
            else:
                # Sem chunks relevantes, pegar documento inteiro até limite
                texto_pdf = texto_completo[:60000]
                print(f"[PERGUNTAR_EDITAL] Sem chunks relevantes, usando primeiros 60K caracteres")

            prompt_pdf = f"""Você é um assistente especializado em licitações públicas brasileiras.

CONTEÚDO DO EDITAL (extraído do PDF "{doc_com_texto.nome_arquivo}"):
{texto_pdf}

PERGUNTA DO USUÁRIO:
{message}

INSTRUÇÕES:
1. Responda a pergunta com base no conteúdo do edital acima
2. CITE O TRECHO EXATO do edital que contém a resposta (entre aspas)
3. Se a informação estiver em um Anexo ou Termo de Referência, indique qual
4. Se não encontrar a informação específica, diga claramente e sugira onde pode estar
5. Seja objetivo e direto

Responda em Markdown."""

            messages_pdf = [{"role": "user", "content": prompt_pdf}]
            resposta_pdf = call_deepseek(messages_pdf, max_tokens=3000)

            response_text = f"""## 💬 Resposta sobre o Edital {edital.numero}

{resposta_pdf}

---
📋 **Edital:** {edital.numero}
🏢 **Órgão:** {edital.orgao or 'N/I'}
📄 **Fonte:** PDF do edital ({doc_com_texto.nome_arquivo})
"""
            return response_text, {"success": True, "edital": edital.numero, "fonte": "pdf", "arquivo": doc_com_texto.nome_arquivo}

        # PASSO 4: Não tem PDF - pedir upload
        print(f"[PERGUNTAR_EDITAL] Nenhum PDF encontrado para o edital {edital.numero}")

        response_text = f"""## ⚠️ Informação Não Disponível

A informação solicitada **não foi encontrada** nos dados cadastrados do edital **{edital.numero}**.

Para responder sua pergunta, preciso do **PDF do edital**.

### 📤 Como fazer:
1. Faça upload do PDF do edital (arraste ou clique no 📎)
2. Junto com o arquivo, envie sua pergunta novamente

**Exemplo:** Envie o PDF e escreva:
> "Qual o prazo de entrega exigido neste edital?"

---
📋 **Edital:** {edital.numero}
🏢 **Órgão:** {edital.orgao or 'N/I'}
📊 **Dados no sistema:** {len(requisitos)} requisitos cadastrados
📄 **PDFs salvos:** Nenhum
"""
        return response_text, {
            "success": False,
            "edital": edital.numero,
            "precisa_upload": True,
            "mensagem": "PDF do edital necessário para responder esta pergunta"
        }

    except Exception as e:
        return f"## ❌ Erro ao Processar Pergunta\n\n{str(e)}", {"error": str(e)}
    finally:
        db.close()


def processar_baixar_pdf_edital(message: str, user_id: str, intencao_resultado: dict = None):
    empresa_id = get_current_empresa_id()
    """
    Processa ação: Baixar o PDF de um edital cadastrado.

    Fluxo:
    1. Identifica o edital pelo número
    2. Verifica se já tem PDF salvo
    3. Se não tem, usa a URL cadastrada para baixar
    4. Extrai texto do PDF e salva na tabela editais_documentos

    Returns: (response_text, resultado_dict)
    """
    empresa_id = get_current_empresa_id()
    import re
    import os
    import requests
    from datetime import datetime
    db = get_db()

    try:
        # Extrair número do edital da mensagem
        edital_numero = None
        if intencao_resultado and intencao_resultado.get("edital"):
            edital_numero = intencao_resultado.get("edital")
        else:
            # Tentar extrair padrões como PE-001/2026, PE001/2026, 001/2026
            padrao = re.search(r'(PE[-\s]?\d+[/\-]\d{4}|\d+[/\-]\d{4})', message, re.IGNORECASE)
            if padrao:
                edital_numero = padrao.group(1)

        if not edital_numero:
            return (
                "## ❌ Número do Edital Não Informado\n\n"
                "Por favor, informe o número do edital que deseja baixar.\n\n"
                "**Exemplos:**\n"
                "- \"Baixe o PDF do edital PE-001/2026\"\n"
                "- \"Faça download do edital 90006/2026\"\n"
                "- \"Baixar edital PE-041/2026\"",
                {"error": "Número do edital não informado"}
            )

        # Buscar edital no banco
        edital = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.numero.ilike(f"%{edital_numero.replace('-', '%').replace('/', '%')}%")
        ).first()

        if not edital:
            return (
                f"## ❌ Edital Não Encontrado\n\n"
                f"O edital **{edital_numero}** não foi encontrado no seu cadastro.\n\n"
                "**Dica:** Use \"Liste meus editais\" para ver os editais cadastrados.",
                {"error": f"Edital {edital_numero} não encontrado"}
            )

        # Verificar se já tem documento salvo
        from models import EditalDocumento
        doc_existente = db.query(EditalDocumento).filter(
            EditalDocumento.edital_id == edital.id
        ).first()

        # Verificar se existe registro E se o arquivo físico ainda existe
        arquivo_existe = doc_existente and doc_existente.path_arquivo and os.path.exists(doc_existente.path_arquivo)

        if doc_existente and doc_existente.texto_extraido and len(doc_existente.texto_extraido) > 100 and arquivo_existe:
            return (
                f"## ✅ PDF Já Disponível\n\n"
                f"O edital **{edital.numero}** já possui PDF baixado e processado.\n\n"
                f"📄 **Arquivo:** {doc_existente.nome_arquivo}\n"
                f"📝 **Texto extraído:** {len(doc_existente.texto_extraido):,} caracteres\n\n"
                "Você pode fazer perguntas sobre o edital:\n"
                f"- \"Quais itens o edital {edital.numero} comporta?\"\n"
                f"- \"Qual o prazo de entrega do edital {edital.numero}?\"",
                {"success": True, "edital": edital.numero, "ja_existia": True, "arquivo": doc_existente.nome_arquivo, "edital_id": edital.id}
            )

        # Se o registro existe mas arquivo foi apagado, deletar o registro para recriar
        if doc_existente and not arquivo_existe:
            db.delete(doc_existente)
            db.commit()
            doc_existente = None  # Permitir re-download

        # ========== MÉTODO 1: Tentar baixar via API do PNCP (se tiver dados) ==========
        if edital.cnpj_orgao and edital.ano_compra and edital.seq_compra:
            from tools import tool_buscar_arquivos_edital_pncp, tool_baixar_pdf_pncp

            response_text = f"## ⏳ Baixando PDF do Edital {edital.numero}...\n\n"
            response_text += f"🔍 **Fonte:** API do PNCP\n"
            response_text += f"📌 **CNPJ:** {edital.cnpj_orgao} | **Ano:** {edital.ano_compra} | **Seq:** {edital.seq_compra}\n\n"

            # Buscar lista de arquivos
            arquivos_result = tool_buscar_arquivos_edital_pncp(edital_id=edital.id, user_id=user_id)

            if arquivos_result.get('success') and arquivos_result.get('arquivos'):
                arquivos = arquivos_result['arquivos']
                arquivo_edital = arquivos_result.get('arquivo_edital') or arquivos[0]

                response_text += f"📁 **Arquivos encontrados:** {len(arquivos)}\n"
                for arq in arquivos:
                    response_text += f"   - {arq['titulo']}\n"
                response_text += f"\n📥 **Baixando:** {arquivo_edital['titulo']}...\n\n"

                # Baixar o arquivo principal
                download_result = tool_baixar_pdf_pncp(
                    cnpj=edital.cnpj_orgao,
                    ano=edital.ano_compra,
                    seq=edital.seq_compra,
                    sequencial_arquivo=arquivo_edital['sequencial'],
                    user_id=user_id,
                    edital_id=edital.id
                )

                if download_result.get('success'):
                    filepath = download_result['filepath']
                    filename = download_result['filename']
                    filesize = download_result['filesize']

                    response_text += f"✅ **Download concluído:** {filename} ({filesize/1024:.1f} KB)\n\n"

                    # Extrair texto do PDF
                    texto_extraido = ""
                    try:
                        from PyPDF2 import PdfReader
                        reader = PdfReader(filepath)
                        for page in reader.pages:
                            texto_extraido += page.extract_text() or ""
                        response_text += f"📝 **Texto extraído:** {len(texto_extraido):,} caracteres\n\n"
                    except Exception as e:
                        response_text += f"⚠️ **Aviso:** Não foi possível extrair texto: {str(e)}\n\n"

                    # Salvar no banco
                    novo_doc = EditalDocumento(
                        id=str(uuid.uuid4()),
                        edital_id=edital.id,
                        tipo='edital_principal',
                        nome_arquivo=filename,
                        path_arquivo=filepath,
                        texto_extraido=texto_extraido[:100000] if texto_extraido else None,
                        processado=True,
                        created_at=datetime.now()
                    )
                    db.add(novo_doc)
                    db.commit()

                    response_text += "## ✅ PDF Salvo com Sucesso!\n\n"

                    # Extrair requisitos automaticamente (incluindo documentais/certidões)
                    requisitos_extraidos = 0
                    if texto_extraido and len(texto_extraido) > 200:
                        try:
                            resultado_req = tool_extrair_requisitos(edital.id, texto_extraido, user_id, empresa_id=empresa_id)
                            requisitos_extraidos = resultado_req.get("requisitos_extraidos", 0)
                            if requisitos_extraidos > 0:
                                response_text += f"📋 **Requisitos extraídos:** {requisitos_extraidos} (técnicos, documentais e comerciais)\n\n"
                        except Exception as e_req:
                            response_text += f"⚠️ Não foi possível extrair requisitos automaticamente: {str(e_req)}\n\n"

                    response_text += "Agora você pode fazer perguntas sobre o edital:\n"
                    response_text += f"- \"Quais itens o edital {edital.numero} comporta?\"\n"
                    response_text += f"- \"Qual o local de entrega do edital {edital.numero}?\"\n"

                    return response_text, {
                        "success": True,
                        "edital": edital.numero,
                        "arquivo": filename,
                        "tamanho": filesize,
                        "texto_extraido": len(texto_extraido),
                        "requisitos_extraidos": requisitos_extraidos,
                        "fonte": "PNCP"
                    }
                else:
                    response_text += f"⚠️ **Erro no download via PNCP:** {download_result.get('error', 'Erro desconhecido')}\n\n"
                    response_text += "Tentando método alternativo...\n\n"
            else:
                response_text = f"## ⏳ Baixando PDF do Edital {edital.numero}...\n\n"
                response_text += f"⚠️ **PNCP:** Nenhum arquivo encontrado via API\n"
                response_text += "Tentando método alternativo...\n\n"

        # ========== MÉTODO 2: Tentar baixar da URL cadastrada ==========

        # Verificar se tem URL do edital
        if not edital.url:
            return (
                f"## ⚠️ URL do Edital Não Cadastrada\n\n"
                f"O edital **{edital.numero}** não possui URL cadastrada para download.\n\n"
                "**Opções:**\n"
                f"1. Atualize o edital com a URL: \"Atualize o edital {edital.numero} com URL: [URL_DO_PDF]\"\n"
                "2. Faça upload manual do PDF (arraste o arquivo para o chat)",
                {"error": "URL não cadastrada", "edital": edital.numero}
            )

        # Tentar baixar o PDF da URL
        if 'response_text' not in locals():
            response_text = f"## ⏳ Baixando PDF do Edital {edital.numero}...\n\n"
        response_text += f"🔗 **URL:** {edital.url}\n\n"

        try:
            # Baixar o arquivo
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(edital.url, headers=headers, timeout=60, allow_redirects=True)
            response.raise_for_status()

            # Determinar nome do arquivo
            content_type = response.headers.get('Content-Type', '')
            filename = f"edital_{edital.numero.replace('/', '_').replace('-', '_')}"

            if 'pdf' in content_type.lower() or edital.url.lower().endswith('.pdf'):
                filename += ".pdf"
            elif 'html' in content_type.lower():
                # É uma página HTML, não PDF direto - tentar encontrar link do PDF
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(response.content, 'html.parser')

                # Procurar links de PDF na página
                pdf_links = []
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    if '.pdf' in href.lower():
                        # Converter para URL absoluta se necessário
                        if href.startswith('/'):
                            from urllib.parse import urlparse
                            parsed = urlparse(edital.url)
                            href = f"{parsed.scheme}://{parsed.netloc}{href}"
                        elif not href.startswith('http'):
                            href = edital.url.rsplit('/', 1)[0] + '/' + href
                        pdf_links.append(href)

                if pdf_links:
                    # Verificar se a URL cadastrada parece ser genérica (página inicial de portal)
                    url_generica = any(x in edital.url.lower() for x in [
                        '/pt-br', '/home', 'compras.gov', 'pncp.gov', 'bec.sp.gov'
                    ]) and edital.url.count('/') <= 4

                    if url_generica:
                        # URL é genérica demais - pedir URL específica
                        return (
                            f"## ⚠️ URL Genérica Cadastrada\n\n"
                            f"A URL cadastrada para o edital **{edital.numero}** parece ser a página inicial do portal:\n"
                            f"`{edital.url}`\n\n"
                            "Essa URL não aponta diretamente para o edital.\n\n"
                            "**O que fazer:**\n"
                            f"1. Acesse o portal e busque pelo edital {edital.numero}\n"
                            "2. Copie a URL da página específica do edital (ou do PDF)\n"
                            "3. Atualize com a URL correta:\n"
                            f"   `Atualize o edital {edital.numero} com URL: [URL_DO_EDITAL]`\n\n"
                            "Ou faça upload manual do PDF.",
                            {"error": "URL genérica", "edital": edital.numero, "url_atual": edital.url}
                        )

                    # Filtrar links relevantes ao edital
                    # Extrair apenas números do edital para comparação
                    numero_limpo = re.sub(r'[^\d]', '', edital.numero)

                    # Prioridade 1: Links que contenham o número do edital
                    links_com_numero = [l for l in pdf_links if numero_limpo in l]

                    # Prioridade 2: Links com palavras-chave do edital
                    palavras_edital = ['edital', 'pregao', 'pregão', 'pe-', 'pe_', 'licitacao', 'licitação',
                                       'termo_referencia', 'termo-referencia', 'tr_', 'tr-']
                    links_com_palavra = [l for l in pdf_links if any(p in l.lower() for p in palavras_edital)]

                    # Prioridade 3: Excluir links claramente não relacionados
                    palavras_excluir = ['politica', 'policy', 'manual', 'regulamento', 'instrucao', 'normativa',
                                        'template', 'modelo', 'anexo_unico', 'formulario', 'cadastro']
                    links_filtrados = [l for l in pdf_links if not any(p in l.lower() for p in palavras_excluir)]

                    # Escolher o melhor link
                    pdf_url = None
                    if links_com_numero:
                        pdf_url = links_com_numero[0]
                        response_text += f"🔍 **URL original era HTML.** Encontrado PDF com número do edital:\n`{pdf_url}`\n\n"
                    elif links_com_palavra:
                        pdf_url = links_com_palavra[0]
                        response_text += f"🔍 **URL original era HTML.** Encontrado PDF de edital:\n`{pdf_url}`\n\n"
                    elif links_filtrados:
                        pdf_url = links_filtrados[0]
                        response_text += f"🔍 **URL original era HTML.** Encontrado possível PDF:\n`{pdf_url}`\n\n"
                    else:
                        # Todos os links parecem não relacionados - listar para o usuário
                        links_lista = "\n".join([f"- `{l}`" for l in pdf_links[:5]])
                        return (
                            f"## ⚠️ Nenhum PDF do Edital Encontrado\n\n"
                            f"A página do edital **{edital.numero}** contém PDFs, mas nenhum parece ser o edital:\n\n"
                            f"{links_lista}\n\n"
                            "**O que fazer:**\n"
                            "1. Acesse a URL no navegador e encontre o PDF correto\n"
                            "2. Atualize com a URL direta do PDF:\n"
                            f"   `Atualize o edital {edital.numero} com URL: [URL_DO_PDF]`\n\n"
                            "Ou faça upload manual do PDF.",
                            {"error": "PDF não identificado", "edital": edital.numero, "links_encontrados": pdf_links[:5]}
                        )

                    # Baixar o PDF encontrado
                    response_pdf = requests.get(pdf_url, headers=headers, timeout=60, allow_redirects=True)
                    response_pdf.raise_for_status()
                    response = response_pdf  # Substituir o response pelo PDF
                    filename += ".pdf"
                else:
                    # Não encontrou PDF - informar usuário
                    return (
                        f"## ⚠️ URL Não Contém PDF Direto\n\n"
                        f"A URL cadastrada para o edital **{edital.numero}** aponta para uma página HTML, "
                        f"não para o arquivo PDF:\n`{edital.url}`\n\n"
                        "**O que fazer:**\n"
                        "1. Acesse a URL acima no navegador\n"
                        "2. Encontre o link do PDF do edital\n"
                        "3. Atualize com a URL correta:\n"
                        f"   `Atualize o edital {edital.numero} com URL: [URL_DO_PDF]`\n\n"
                        "Ou faça upload manual do PDF (arraste o arquivo para o chat).",
                        {"error": "URL não é PDF direto", "edital": edital.numero, "url_atual": edital.url}
                    )
            else:
                filename += ".pdf"

            # Salvar arquivo
            upload_dir = os.path.join(os.path.dirname(__file__), 'uploads', user_id, 'editais')
            os.makedirs(upload_dir, exist_ok=True)
            filepath = os.path.join(upload_dir, filename)

            with open(filepath, 'wb') as f:
                f.write(response.content)

            filesize = len(response.content)
            response_text += f"✅ **Download concluído:** {filename} ({filesize/1024:.1f} KB)\n\n"

            # Extrair texto do PDF
            texto_extraido = ""
            try:
                if filename.endswith('.pdf'):
                    from PyPDF2 import PdfReader
                    reader = PdfReader(filepath)
                    for page in reader.pages:
                        texto_extraido += page.extract_text() or ""
                elif filename.endswith('.html'):
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(response.content, 'html.parser')
                    texto_extraido = soup.get_text(separator='\n', strip=True)

                response_text += f"📝 **Texto extraído:** {len(texto_extraido):,} caracteres\n\n"
            except Exception as e:
                response_text += f"⚠️ **Aviso:** Não foi possível extrair texto: {str(e)}\n\n"

            # Salvar no banco
            if doc_existente:
                doc_existente.path_arquivo = filepath
                doc_existente.nome_arquivo = filename
                doc_existente.texto_extraido = texto_extraido[:100000] if texto_extraido else None
                doc_existente.processado = True
            else:
                novo_doc = EditalDocumento(
                    id=str(uuid.uuid4()),
                    edital_id=edital.id,
                    tipo='edital_principal',  # Valores: edital_principal, termo_referencia, anexo, planilha, outro
                    nome_arquivo=filename,
                    path_arquivo=filepath,
                    texto_extraido=texto_extraido[:100000] if texto_extraido else None,
                    processado=True,
                    created_at=datetime.now()
                )
                db.add(novo_doc)

            db.commit()

            response_text += "## ✅ PDF Salvo com Sucesso!\n\n"

            # Extrair requisitos automaticamente (incluindo documentais/certidões)
            requisitos_extraidos = 0
            if texto_extraido and len(texto_extraido) > 200:
                try:
                    resultado_req = tool_extrair_requisitos(edital.id, texto_extraido, user_id, empresa_id=empresa_id)
                    requisitos_extraidos = resultado_req.get("requisitos_extraidos", 0)
                    if requisitos_extraidos > 0:
                        response_text += f"📋 **Requisitos extraídos:** {requisitos_extraidos} (técnicos, documentais e comerciais)\n\n"
                except Exception as e_req:
                    response_text += f"⚠️ Não foi possível extrair requisitos automaticamente: {str(e_req)}\n\n"

            response_text += "Agora você pode fazer perguntas sobre o edital:\n"
            response_text += f"- \"Quais itens o edital {edital.numero} comporta?\"\n"
            response_text += f"- \"Qual o local de entrega do edital {edital.numero}?\"\n"
            response_text += f"- \"Me conte tudo sobre o edital {edital.numero}\"\n"

            return response_text, {
                "success": True,
                "edital": edital.numero,
                "arquivo": filename,
                "tamanho": filesize,
                "texto_extraido": len(texto_extraido),
                "requisitos_extraidos": requisitos_extraidos
            }

        except requests.exceptions.RequestException as e:
            return (
                f"## ❌ Erro ao Baixar PDF\n\n"
                f"Não foi possível baixar o arquivo da URL:\n`{edital.url}`\n\n"
                f"**Erro:** {str(e)}\n\n"
                "**Opções:**\n"
                "1. Verifique se a URL está correta\n"
                "2. Tente acessar a URL manualmente e baixar o PDF\n"
                "3. Faça upload manual do PDF (arraste o arquivo para o chat)",
                {"error": str(e), "edital": edital.numero}
            )

    except Exception as e:
        return f"## ❌ Erro ao Processar Download\n\n{str(e)}", {"error": str(e)}
    finally:
        db.close()


def processar_atualizar_url_edital(message: str, user_id: str, intencao_resultado: dict = None):
    """Atualiza a URL de um edital cadastrado"""
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        import re

        # Extrair número do edital da mensagem
        # Padrões: PE-001/2026, 02223/2025, PE001, etc.
        edital_numero = None
        if intencao_resultado and intencao_resultado.get("edital"):
            edital_numero = intencao_resultado["edital"]
        else:
            # Tentar extrair da mensagem
            patterns = [
                r'edital\s+([A-Za-z]{0,3}[-]?\d+[/]\d{4})',  # edital PE-001/2026 ou 02223/2025
                r'edital\s+([A-Za-z]{2,3}[-]?\d+)',  # edital PE-001 ou PE001
                r'([A-Za-z]{2,3}[-]\d+[/]\d{4})',  # PE-001/2026
                r'(\d{4,}[/]\d{4})',  # 02223/2025
            ]
            for pattern in patterns:
                match = re.search(pattern, message, re.IGNORECASE)
                if match:
                    edital_numero = match.group(1)
                    break

        if not edital_numero:
            return (
                "## ⚠️ Número do Edital Não Informado\n\n"
                "Por favor, informe o número do edital que deseja atualizar.\n\n"
                "**Formato:**\n"
                "`Atualize o edital PE-001/2026 com URL: https://exemplo.com/edital.pdf`",
                {"error": "Número do edital não informado"}
            )

        # Extrair a nova URL da mensagem
        url_match = re.search(r'(https?://[^\s<>"]+)', message)
        if not url_match:
            return (
                f"## ⚠️ URL Não Informada\n\n"
                f"Por favor, informe a nova URL para o edital **{edital_numero}**.\n\n"
                "**Formato:**\n"
                f"`Atualize o edital {edital_numero} com URL: https://exemplo.com/edital.pdf`",
                {"error": "URL não informada", "edital": edital_numero}
            )

        nova_url = url_match.group(1)

        # Buscar edital no banco
        editais = db.query(Edital).filter(Edital.empresa_id == empresa_id).all()

        # Normalizar número para comparação
        numero_busca = edital_numero.replace('-', '').replace('/', '').upper()

        edital = None
        for e in editais:
            num_edital = e.numero.replace('-', '').replace('/', '').upper()
            if num_edital == numero_busca or numero_busca in num_edital or num_edital in numero_busca:
                edital = e
                break

        if not edital:
            return (
                f"## ❌ Edital Não Encontrado\n\n"
                f"O edital **{edital_numero}** não foi encontrado no seu cadastro.\n\n"
                "**Dica:** Use \"Liste meus editais\" para ver os editais cadastrados.",
                {"error": f"Edital {edital_numero} não encontrado"}
            )

        # Atualizar a URL
        url_antiga = edital.url
        edital.url = nova_url
        db.commit()

        response_text = f"## ✅ URL Atualizada com Sucesso!\n\n"
        response_text += f"**Edital:** {edital.numero}\n"
        response_text += f"**Órgão:** {edital.orgao or 'N/A'}\n\n"

        if url_antiga:
            response_text += f"**URL anterior:** `{url_antiga}`\n"
        response_text += f"**Nova URL:** `{nova_url}`\n\n"

        response_text += "Agora você pode baixar o PDF:\n"
        response_text += f"- `Baixe o PDF do edital {edital.numero}`"

        return response_text, {
            "success": True,
            "edital": edital.numero,
            "edital_id": edital.id,
            "url_antiga": url_antiga,
            "url_nova": nova_url
        }

    except Exception as e:
        return f"## ❌ Erro ao Atualizar URL\n\n{str(e)}", {"error": str(e)}
    finally:
        db.close()


# =============================================================================
# FASE 1: PRECIFICAÇÃO — Handlers (UC-P01 a UC-P10)
# =============================================================================

def _extrair_id_da_mensagem(message: str, prefixo: str = "edital") -> str:
    """Extrai UUID ou referência de ID de uma mensagem de chat."""
    import re
    # UUID
    m = re.search(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', message, re.I)
    if m:
        return m.group(0)
    return None


def processar_precif_organizar_lotes(message: str, user_id: str, empresa_id: str = None):
    """UC-P01: Organizar edital por lotes"""
    from tools import tool_organizar_lotes
    from models import get_db, Edital
    db = get_db()
    try:
        edital_id = _extrair_id_da_mensagem(message)
        if not edital_id:
            # Pegar último edital do usuário
            edital = db.query(Edital).filter(Edital.empresa_id == empresa_id).order_by(Edital.created_at.desc()).first()
            edital_id = edital.id if edital else None
        if not edital_id:
            return "❌ Nenhum edital encontrado. Salve um edital primeiro.", None

        resultado = tool_organizar_lotes(edital_id=edital_id, user_id=user_id, empresa_id=empresa_id, importar_pncp=True)
        if not resultado.get("success"):
            return f"❌ {resultado.get('error')}", resultado

        lotes = resultado.get("lotes", [])
        total = resultado.get("total_itens", 0)
        txt = f"## ✅ Lotes Organizados\n\n{resultado.get('mensagem')}\n\n"
        txt += f"**Total de itens:** {total}\n\n"
        for l in lotes:
            txt += f"- **Lote {l['numero_lote']}** — {l.get('nome', 'N/A')} | Status: {l.get('status')} | Valor est.: R$ {l.get('valor_estimado', 0):,.2f}\n"

        return txt, resultado
    finally:
        db.close()


def processar_precif_selecao_portfolio(message: str, user_id: str, empresa_id: str = None):
    """UC-P02: Seleção inteligente de portfolio"""
    from tools import tool_selecao_portfolio
    edital_item_id = _extrair_id_da_mensagem(message)
    if not edital_item_id:
        return "❌ Informe o ID do item do edital para seleção de portfolio.", None

    resultado = tool_selecao_portfolio(edital_item_id=edital_item_id, user_id=user_id, empresa_id=empresa_id)
    if not resultado.get("success"):
        return f"❌ {resultado.get('error')}", resultado

    sugestoes = resultado.get("sugestoes", [])
    txt = f"## 🎯 Seleção de Portfolio\n\n{resultado.get('mensagem')}\n\n"
    if sugestoes:
        txt += "| # | Produto | Fabricante | Match | Preço Ref. |\n|---|---------|-----------|-------|------------|\n"
        for i, s in enumerate(sugestoes[:10], 1):
            txt += f"| {i} | {s['nome'][:30]} | {s.get('fabricante', '-')[:20]} | {s['match_score']}% | R$ {s.get('preco_referencia', 0) or 0:,.2f} |\n"
    else:
        txt += "Nenhum produto com match encontrado. Cadastre produtos no portfolio.\n"

    return txt, resultado


def processar_precif_calcular_volumetria(message: str, user_id: str):
    """UC-P03: Cálculo técnico de volumetria"""
    from tools import tool_calcular_volumetria
    import re

    vinculo_id = _extrair_id_da_mensagem(message)
    if not vinculo_id:
        return "❌ Informe o ID do vínculo item-produto para calcular volumetria.", None

    # Extrair números da mensagem
    nums = re.findall(r'[\d.]+', message)
    volume = float(nums[0]) if len(nums) > 0 else None
    rendimento = float(nums[1]) if len(nums) > 1 else None

    resultado = tool_calcular_volumetria(
        edital_item_produto_id=vinculo_id, user_id=user_id,
        volume_edital=volume, rendimento_produto=rendimento
    )
    if not resultado.get("success"):
        return f"❌ {resultado.get('error')}", resultado

    txt = f"## 📊 Volumetria Calculada\n\n"
    txt += f"**Fórmula:** {resultado.get('formula')}\n\n"
    txt += f"- Volume do edital: {resultado.get('volume_edital'):,.0f}\n"
    txt += f"- Rendimento: {resultado.get('rendimento_produto'):,.0f} por kit\n"
    txt += f"- Volume real ajustado: {resultado.get('volume_real_ajustado'):,.0f}\n"
    txt += f"- **Quantidade de kits: {resultado.get('quantidade_kits')}**\n"

    return txt, resultado


def processar_precif_configurar_custos(message: str, user_id: str, empresa_id: str = None):
    """UC-P04: Configurar base de custos (Camada A)"""
    from tools import tool_configurar_custos
    import re

    vinculo_id = _extrair_id_da_mensagem(message)
    if not vinculo_id:
        return "❌ Informe o ID do vínculo item-produto para configurar custos.", None

    # Extrair custo da mensagem
    m = re.search(r'R\$\s*([\d.,]+)', message)
    custo = float(m.group(1).replace('.', '').replace(',', '.')) if m else None

    resultado = tool_configurar_custos(
        edital_item_produto_id=vinculo_id, user_id=user_id,
        custo_unitario=custo, empresa_id=empresa_id
    )
    if not resultado.get("success"):
        return f"❌ {resultado.get('error')}", resultado

    txt = f"## 💰 Base de Custos (Camada A)\n\n{resultado.get('mensagem')}\n\n"
    txt += f"- Custo unitário: R$ {resultado.get('custo_unitario', 0):,.2f}\n"
    txt += f"- NCM: {resultado.get('ncm', 'N/A')}\n"
    txt += f"- ICMS: {resultado.get('icms', 0)}%" + (" (ISENTO)" if resultado.get('isencao_icms') else "") + "\n"
    txt += f"- IPI: {resultado.get('ipi', 0)}% | PIS+COFINS: {resultado.get('pis_cofins', 0)}%\n"
    txt += f"- **Custo base final: R$ {resultado.get('custo_base_final', 0):,.2f}**\n"

    return txt, resultado


def processar_precif_preco_base(message: str, user_id: str):
    """UC-P05: Montar preço base (Camada B)"""
    from tools import tool_montar_preco_base
    import re

    vinculo_id = _extrair_id_da_mensagem(message)
    if not vinculo_id:
        return "❌ Informe o ID do vínculo item-produto.", None

    # Detectar modo
    modo = 'manual'
    if 'markup' in message.lower():
        modo = 'markup'
    elif 'upload' in message.lower():
        modo = 'upload'

    preco = None
    markup = None
    m = re.search(r'R\$\s*([\d.,]+)', message)
    if m:
        preco = float(m.group(1).replace('.', '').replace(',', '.'))
    m2 = re.search(r'(\d+[.,]?\d*)\s*%', message)
    if m2 and modo == 'markup':
        markup = float(m2.group(1).replace(',', '.'))

    resultado = tool_montar_preco_base(
        edital_item_produto_id=vinculo_id, user_id=user_id,
        modo=modo, preco_base=preco, markup_percentual=markup
    )
    if not resultado.get("success"):
        return f"❌ {resultado.get('error')}", resultado

    txt = f"## 📈 Preço Base (Camada B)\n\n{resultado.get('mensagem')}\n\n"
    txt += f"- Custo base (A): R$ {resultado.get('custo_base', 0):,.2f}\n"
    txt += f"- **Preço base (B): R$ {resultado.get('preco_base', 0):,.2f}**\n"
    if resultado.get('markup_percentual'):
        txt += f"- Markup: {resultado.get('markup_percentual'):.1f}%\n"

    return txt, resultado


def processar_precif_valor_referencia(message: str, user_id: str):
    """UC-P06: Definir valor de referência (Camada C)"""
    from tools import tool_definir_referencia
    import re

    vinculo_id = _extrair_id_da_mensagem(message)
    if not vinculo_id:
        return "❌ Informe o ID do vínculo item-produto.", None

    valor_ref = None
    pct = None
    m = re.search(r'R\$\s*([\d.,]+)', message)
    if m:
        valor_ref = float(m.group(1).replace('.', '').replace(',', '.'))
    m2 = re.search(r'(\d+[.,]?\d*)\s*%', message)
    if m2:
        pct = float(m2.group(1).replace(',', '.'))

    resultado = tool_definir_referencia(
        edital_item_produto_id=vinculo_id, user_id=user_id,
        valor_referencia=valor_ref, percentual_sobre_base=pct
    )
    if not resultado.get("success"):
        return f"❌ {resultado.get('error')}", resultado

    comp = resultado.get("comparativo", {})
    txt = f"## 🎯 Valor de Referência (Camada C)\n\n{resultado.get('mensagem')}\n\n"
    txt += f"**Comparativo:**\n"
    txt += f"- Custo (A): R$ {comp.get('custo_base_A', 0):,.2f}\n"
    txt += f"- Preço Base (B): R$ {comp.get('preco_base_B', 0):,.2f}\n"
    txt += f"- **Target (C): R$ {comp.get('target_C', 0):,.2f}**\n"
    if resultado.get('margem_sobre_custo'):
        txt += f"- Margem sobre custo: {resultado['margem_sobre_custo']:.1f}%\n"

    return txt, resultado


def processar_precif_estruturar_lances(message: str, user_id: str):
    """UC-P07: Estruturar lances (Camadas D e E)"""
    from tools import tool_estruturar_lances
    import re

    vinculo_id = _extrair_id_da_mensagem(message)
    if not vinculo_id:
        return "❌ Informe o ID do vínculo item-produto.", None

    # Extrair valores
    valores = re.findall(r'R\$\s*([\d.,]+)', message)
    lance_ini = float(valores[0].replace('.', '').replace(',', '.')) if len(valores) > 0 else None
    lance_min = float(valores[1].replace('.', '').replace(',', '.')) if len(valores) > 1 else None

    resultado = tool_estruturar_lances(
        edital_item_produto_id=vinculo_id, user_id=user_id,
        lance_inicial=lance_ini, lance_minimo=lance_min
    )
    if not resultado.get("success"):
        return f"❌ {resultado.get('error')}", resultado

    txt = f"## ⚡ Estrutura de Lances (Camadas D+E)\n\n{resultado.get('mensagem')}\n\n"
    txt += f"- Custo base: R$ {resultado.get('custo_base', 0):,.2f}\n"
    txt += f"- Lance inicial (D): R$ {resultado.get('lance_inicial', 0):,.2f}\n"
    txt += f"- Lance mínimo (E): R$ {resultado.get('lance_minimo', 0):,.2f}\n"
    txt += f"- **Faixa de disputa:** {resultado.get('faixa_disputa')}\n"
    if resultado.get('margem_minima') is not None:
        txt += f"- Margem mínima: {resultado['margem_minima']:.1f}%\n"
    for w in resultado.get('warnings', []):
        txt += f"\n{w}\n"

    return txt, resultado


def processar_precif_estrategia(message: str, user_id: str, empresa_id: str = None):
    """UC-P08: Estratégia competitiva"""
    from tools import tool_estrategia_competitiva
    from models import get_db, Edital

    edital_id = _extrair_id_da_mensagem(message)
    if not edital_id:
        db = get_db()
        try:
            edital = db.query(Edital).filter(Edital.empresa_id == empresa_id).order_by(Edital.created_at.desc()).first()
            edital_id = edital.id if edital else None
        finally:
            db.close()
    if not edital_id:
        return "❌ Nenhum edital encontrado.", None

    perfil = 'quero_ganhar'
    msg_lower = message.lower()
    if 'não ganhei' in msg_lower or 'nao ganhei' in msg_lower or 'mínimo' in msg_lower or 'minimo' in msg_lower:
        perfil = 'nao_ganhei_minimo'

    resultado = tool_estrategia_competitiva(edital_id=edital_id, user_id=user_id, perfil=perfil, empresa_id=empresa_id)
    if not resultado.get("success"):
        return f"❌ {resultado.get('error')}", resultado

    txt = f"## 🏆 Estratégia Competitiva\n\n{resultado.get('mensagem')}\n\n"
    txt += f"**Perfil:** {'QUERO GANHAR' if perfil == 'quero_ganhar' else 'NÃO GANHEI NO MÍNIMO'}\n\n"
    for c in resultado.get("cenarios", []):
        txt += f"**Item {c.get('item', '?')}:**\n"
        for key in ['cenario_1', 'cenario_2', 'cenario_3']:
            cen = c.get(key, {})
            txt += f"  - {cen.get('label')}: R$ {cen.get('valor', 0):,.2f} (margem: {cen.get('margem', 0):.1f}%)\n"
        txt += "\n"

    return txt, resultado


def processar_precif_historico_camada_f(message: str, user_id: str):
    """UC-P09: Histórico de preços (Camada F)"""
    from tools import tool_historico_precos_camada_f
    import re

    vinculo_id = _extrair_id_da_mensagem(message)
    # Extrair termo de busca
    termo = None
    m = re.search(r'(?:de|para|termo:?)\s+["\']?([^"\']+)["\']?', message, re.I)
    if m:
        termo = m.group(1).strip()

    if not vinculo_id and not termo:
        return "❌ Informe o ID do vínculo item-produto ou um termo de busca.", None

    resultado = tool_historico_precos_camada_f(
        edital_item_produto_id=vinculo_id or "", user_id=user_id, termo=termo
    )
    if not resultado.get("success"):
        return f"❌ {resultado.get('error')}", resultado

    txt = f"## 📜 Histórico de Preços (Camada F)\n\n{resultado.get('mensagem')}\n\n"
    if resultado.get('preco_medio'):
        txt += f"- Preço médio: R$ {resultado['preco_medio']:,.2f}\n"
        txt += f"- Faixa: R$ {resultado.get('preco_min', 0):,.2f} — R$ {resultado.get('preco_max', 0):,.2f}\n"
        txt += f"- Registros: {resultado.get('qtd_registros', 0)}\n"
    else:
        txt += "Nenhum registro de preço encontrado.\n"

    return txt, resultado


def processar_precif_comodato(message: str, user_id: str, empresa_id: str = None):
    """UC-P10: Gestão de comodato"""
    from tools import tool_gestao_comodato
    from models import get_db, Edital
    import re

    edital_id = _extrair_id_da_mensagem(message)
    if not edital_id:
        db = get_db()
        try:
            edital = db.query(Edital).filter(Edital.empresa_id == empresa_id).order_by(Edital.created_at.desc()).first()
            edital_id = edital.id if edital else None
        finally:
            db.close()
    if not edital_id:
        return "❌ Nenhum edital encontrado.", None

    # Extrair nome e valor da mensagem
    nome = None
    valor = None
    meses = None

    m_nome = re.search(r'equipamento[:\s]+["\']?([^"\',$]+)', message, re.I)
    if m_nome:
        nome = m_nome.group(1).strip()

    m_valor = re.search(r'R\$\s*([\d.,]+)', message)
    if m_valor:
        valor = float(m_valor.group(1).replace('.', '').replace(',', '.'))

    m_meses = re.search(r'(\d+)\s*meses', message, re.I)
    if m_meses:
        meses = int(m_meses.group(1))

    resultado = tool_gestao_comodato(
        edital_id=edital_id, user_id=user_id, empresa_id=empresa_id,
        nome_equipamento=nome or "Equipamento",
        valor_equipamento=valor,
        duracao_meses=meses,
    )
    if not resultado.get("success"):
        return f"❌ {resultado.get('error')}", resultado

    com = resultado.get('comodato', {})
    txt = f"## 🔧 Comodato\n\n{resultado.get('mensagem')}\n\n"
    txt += f"- Equipamento: {com.get('nome_equipamento')}\n"
    if com.get('valor_equipamento'):
        txt += f"- Valor: R$ {com['valor_equipamento']:,.2f}\n"
    if com.get('duracao_meses'):
        txt += f"- Prazo: {com['duracao_meses']} meses\n"
    if resultado.get('amortizacao_mensal'):
        txt += f"- **Amortização mensal: R$ {resultado['amortizacao_mensal']:,.2f}**\n"

    return txt, resultado


def processar_chat_livre(message: str, user_id: str, session_id: str, db):
    """Processa chat livre sobre licitações"""
    # Buscar histórico
    historico = db.query(Message).filter(
        Message.session_id == session_id
    ).order_by(Message.created_at.desc()).limit(MAX_HISTORY_MESSAGES).all()

    historico = list(reversed(historico))

    # Montar mensagens
    system_prompt = """Você é um especialista em licitações públicas brasileiras.
Seu conhecimento inclui:
- Lei 14.133/2021 (Nova Lei de Licitações)
- Pregão eletrônico e presencial
- Elaboração de propostas técnicas
- Análise de editais
- Impugnações e recursos
- Comodato de equipamentos
- Contratos administrativos

Responda de forma clara, objetiva e fundamentada na legislação quando aplicável."""

    messages = [{"role": "system", "content": system_prompt}]

    for msg in historico:
        messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "user", "content": message})

    try:
        response = call_deepseek(messages, max_tokens=4000)
        return response
    except Exception as e:
        return f"Erro ao processar: {str(e)}"


# =============================================================================
# Upload Routes
# =============================================================================

@app.route("/api/upload", methods=["POST"])
@require_auth
def upload_manual():
    """
    Upload de manual PDF para extração de especificações.

    Form data:
    - file: arquivo PDF
    - nome_produto: nome do produto
    - categoria: equipamento, reagente, insumo_hospitalar, insumo_laboratorial
    - fabricante: (opcional)
    - modelo: (opcional)
    """
    user_id = get_current_user_id()

    if 'file' not in request.files:
        return jsonify({"error": "Arquivo não enviado"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Nenhum arquivo selecionado"}), 400

    nome_produto = request.form.get('nome_produto')
    categoria = request.form.get('categoria', 'equipamento')
    fabricante = request.form.get('fabricante')
    modelo = request.form.get('modelo')

    if not nome_produto:
        return jsonify({"error": "nome_produto é obrigatório"}), 400

    # Salvar arquivo
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    filename = f"{user_id}_{uuid.uuid4().hex[:8]}_{file.filename}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    # Processar
    empresa_id_atual = get_current_empresa_id()
    resultado = tool_processar_upload(
        filepath=filepath,
        user_id=user_id,
        empresa_id=empresa_id_atual,
        nome_produto=nome_produto,
        categoria=categoria,
        fabricante=fabricante,
        modelo=modelo
    )

    if resultado.get("success"):
        return jsonify(resultado), 201
    else:
        return jsonify(resultado), 400


@app.route("/api/chat-upload", methods=["POST"])
@require_auth
def chat_upload():
    """
    Envia mensagem com arquivo anexo.
    O agente classificador interpreta a intenção do usuário.

    Form data:
    - file: arquivo PDF
    - session_id: ID da sessão de chat
    - message: mensagem do usuário (opcional)
    """
    user_id = get_current_user_id()

    if 'file' not in request.files:
        return jsonify({"error": "Arquivo não enviado"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Nenhum arquivo selecionado"}), 400

    session_id = request.form.get('session_id')
    message = request.form.get('message', '').strip()
    subclasse_id = request.form.get('subclasse_id')  # Para guiar extração com campos_mascara

    if not session_id:
        return jsonify({"error": "session_id é obrigatório"}), 400

    # ========== USAR AGENTE CLASSIFICADOR ==========
    print(f"[CHAT-UPLOAD] Classificando intenção: '{message}' (tem_arquivo=True)")
    intencao_resultado = detectar_intencao_ia(message, tem_arquivo=True)
    intencao_arquivo = intencao_resultado.get("intencao", "arquivo_cadastrar")
    nome_produto = intencao_resultado.get("nome_produto")
    print(f"[CHAT-UPLOAD] Intenção detectada: {intencao_arquivo}")

    # Mapear intenções do classificador para ações internas
    mapa_intencoes = {
        "arquivo_cadastrar": "cadastrar",
        "arquivo_mostrar": "mostrar_conteudo",
        "arquivo_specs": "extrair_specs",
        "arquivo_resumir": "resumir",
        "arquivo_analisar": "analisar",
        "extrair_ata": "extrair_ata",  # Nova ação: extrair resultados de ata de pregão
        # Fallbacks para compatibilidade
        "upload_manual": "cadastrar",
        "chat_livre": "cadastrar"  # Se não entendeu, cadastra
    }
    intencao_arquivo = mapa_intencoes.get(intencao_arquivo, "cadastrar")

    db = get_db()
    try:
        # Verificar sessão
        session = db.query(Session).filter(
            Session.id == session_id,
            Session.user_id == user_id
        ).first()

        if not session:
            return jsonify({"error": "Sessão não encontrada"}), 404

        # Salvar arquivo
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        filename = f"{user_id}_{uuid.uuid4().hex[:8]}_{file.filename}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        # Extrair texto do PDF
        import fitz
        texto_pdf = ""
        try:
            doc = fitz.open(filepath)
            for page in doc:
                texto_pdf += page.get_text()
            doc.close()
        except Exception as e:
            texto_pdf = f"Erro ao extrair texto: {e}"

        # Salvar mensagem do usuário
        acoes_desc = {
            "cadastrar": "Cadastrar como produto",
            "mostrar_conteudo": "Mostrar conteúdo",
            "extrair_specs": "Extrair especificações",
            "resumir": "Resumir documento",
            "analisar": "Analisar documento",
            "extrair_ata": "Extrair resultados da ata"
        }
        user_msg_content = f"📎 **{file.filename}**\n*{acoes_desc.get(intencao_arquivo, 'Processar')}*"
        user_msg = Message(
            session_id=session_id,
            role='user',
            content=user_msg_content,
            action_type='upload_manual'
        )
        db.add(user_msg)

        resultado = {"success": True}
        response_text = ""

        # ========== AÇÃO: MOSTRAR CONTEÚDO ==========
        if intencao_arquivo == "mostrar_conteudo":
            response_text = f"""## 📄 Conteúdo do Documento

**Arquivo:** {file.filename}
**Tamanho:** {len(texto_pdf)} caracteres

---

{texto_pdf[:5000]}

{"..." if len(texto_pdf) > 5000 else ""}

---
*Para cadastrar como produto, envie: "cadastre"*"""

        # ========== AÇÃO: EXTRAIR SPECS (sem cadastrar) ==========
        elif intencao_arquivo == "extrair_specs":
            # info e specs já importados no topo
            info = _extrair_info_produto(texto_pdf[:8000])

            # Extrair specs via IA
            prompt = PROMPT_EXTRAIR_SPECS.format(texto=texto_pdf[:15000])
            resposta_ia = call_deepseek([{"role": "user", "content": prompt}], max_tokens=8000)

            response_text = f"""## 📊 Especificações Extraídas

**Produto identificado:** {info.get('nome', 'N/A')}
**Fabricante:** {info.get('fabricante', 'N/A')}
**Modelo:** {info.get('modelo', 'N/A')}

### Especificações:

{resposta_ia[:4000]}

---
*Para cadastrar como produto, envie: "cadastre"*"""

        # ========== AÇÃO: RESUMIR ==========
        elif intencao_arquivo == "resumir":
            prompt_resumo = f"""Resuma o documento abaixo em português, destacando:
1. Tipo de documento (manual, datasheet, etc)
2. Produto/equipamento descrito
3. Principais características
4. Pontos importantes

DOCUMENTO:
{texto_pdf[:10000]}

RESUMO:"""
            resumo = call_deepseek([{"role": "user", "content": prompt_resumo}], max_tokens=2000, model_override="deepseek-chat")

            response_text = f"""## 📝 Resumo do Documento

**Arquivo:** {file.filename}

{resumo}

---
*Para cadastrar como produto, envie: "cadastre"*"""

        # ========== AÇÃO: ANALISAR ==========
        elif intencao_arquivo == "analisar":
            prompt_analise = f"""Analise o documento técnico abaixo e forneça:
1. Tipo de documento
2. Produto/equipamento descrito
3. Fabricante
4. Principais especificações técnicas
5. Aplicações/uso indicado
6. Pontos fortes e fracos (se identificáveis)

DOCUMENTO:
{texto_pdf[:12000]}

ANÁLISE:"""
            analise = call_deepseek([{"role": "user", "content": prompt_analise}], max_tokens=3000, model_override="deepseek-chat")

            response_text = f"""## 🔍 Análise do Documento

**Arquivo:** {file.filename}

{analise}

---
*Para cadastrar como produto, envie: "cadastre"*"""

        # ========== AÇÃO: EXTRAIR ATA DE SESSÃO ==========
        elif intencao_arquivo == "extrair_ata":
            response_text, resultado = processar_extrair_ata(texto_pdf, filepath, user_id, file.filename)

        # ========== AÇÃO: CADASTRAR (padrão) ==========
        else:
            empresa_id_atual = get_current_empresa_id()
            resultado = tool_processar_upload(
                filepath=filepath,
                user_id=user_id,
                empresa_id=empresa_id_atual,
                nome_produto=nome_produto,
                categoria=None,
                fabricante=None,
                modelo=None,
                subclasse_id=subclasse_id
            )

            if resultado.get("success"):
                produto = resultado.get("produto", {})
                specs = resultado.get("especificacoes", [])

                response_text = f"""## ✅ Produto Cadastrado com Sucesso!

**Nome:** {produto.get('nome', 'N/A')}
**Fabricante:** {produto.get('fabricante', 'Não identificado')}
**Modelo:** {produto.get('modelo', 'Não identificado')}
**Categoria:** {produto.get('categoria', 'equipamento')}
**ID:** {produto.get('id', 'N/A')}

### Especificações Extraídas ({len(specs)} encontradas):
"""
                for spec in specs[:15]:
                    response_text += f"- **{spec.get('nome', 'N/A')}:** {spec.get('valor', 'N/A')}\n"

                if len(specs) > 15:
                    response_text += f"\n... e mais {len(specs) - 15} especificações.\n"

                response_text += "\n---\n✅ Produto pronto para calcular aderência com editais!"
            elif resultado.get("duplicado"):
                prod_exist = resultado.get("produto_existente", {})
                response_text = f"""## ⚠️ Produto já cadastrado!

**Nome:** {prod_exist.get('nome', 'N/A')}
**Modelo:** {prod_exist.get('modelo', 'N/A')}
**ID:** {prod_exist.get('id', 'N/A')}

Use **reprocesse o produto {prod_exist.get('nome')}** para atualizar as especificações."""
            else:
                response_text = f"❌ Erro ao processar arquivo: {resultado.get('error', 'Erro desconhecido')}"

        # Salvar resposta do assistente
        assistant_msg = Message(
            session_id=session_id,
            role='assistant',
            content=response_text,
            action_type='upload_manual'
        )
        db.add(assistant_msg)

        # Atualizar sessão
        session.updated_at = datetime.now()
        db.commit()

        return jsonify({
            "success": resultado.get("success", False),
            "response": response_text,
            "session_id": session_id,
            "action_type": "upload_manual"
        })

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/upload-chat", methods=["POST"])
@require_auth
def upload_chat():
    """
    DEPRECATED - Use /api/chat-upload instead.
    Mantido para compatibilidade.
    """
    user_id = get_current_user_id()

    if 'file' not in request.files:
        return jsonify({"error": "Arquivo não enviado"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Nenhum arquivo selecionado"}), 400

    session_id = request.form.get('session_id')
    nome_produto = request.form.get('nome_produto', '').strip()

    if not session_id:
        return jsonify({"error": "session_id é obrigatório"}), 400
    if not nome_produto:
        return jsonify({"error": "nome_produto é obrigatório"}), 400

    db = get_db()
    try:
        # Verificar sessão
        session = db.query(Session).filter(
            Session.id == session_id,
            Session.user_id == user_id
        ).first()

        if not session:
            return jsonify({"error": "Sessão não encontrada"}), 404

        # Salvar arquivo
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        filename = f"{user_id}_{uuid.uuid4().hex[:8]}_{file.filename}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)

        # Salvar mensagem do usuário
        user_msg_content = f"📎 Upload: **{file.filename}**\nCadastrar como: **{nome_produto}**"
        user_msg = Message(
            session_id=session_id,
            role='user',
            content=user_msg_content,
            action_type='upload_manual'
        )
        db.add(user_msg)

        # Determinar categoria automaticamente
        categoria = "equipamento"
        nome_lower = nome_produto.lower()
        if any(t in nome_lower for t in ["analisador", "bioquímic", "laborat"]):
            categoria = "equipamento"
        elif any(t in nome_lower for t in ["centrifuga", "microscop"]):
            categoria = "equipamento"
        elif any(t in nome_lower for t in ["cama", "maca", "cadeira"]):
            categoria = "mobiliario"
        elif any(t in nome_lower for t in ["monitor", "desfibrilador", "eletrocard"]):
            categoria = "equipamento"

        # Processar arquivo
        empresa_id_atual = get_current_empresa_id()
        resultado = tool_processar_upload(
            filepath=filepath,
            user_id=user_id,
            empresa_id=empresa_id_atual,
            nome_produto=nome_produto,
            categoria=categoria,
            fabricante=None,
            modelo=None
        )

        # Montar resposta
        if resultado.get("success"):
            produto = resultado.get("produto", {})
            specs = resultado.get("especificacoes", [])

            response_text = f"""## ✅ Produto Cadastrado com Sucesso!

**Nome:** {produto.get('nome', nome_produto)}
**Categoria:** {categoria}
**ID:** {produto.get('id', 'N/A')}

### Especificações Extraídas ({len(specs)} encontradas):
"""
            for spec in specs[:15]:
                response_text += f"- **{spec.get('nome', 'N/A')}:** {spec.get('valor', 'N/A')}\n"

            if len(specs) > 15:
                response_text += f"\n... e mais {len(specs) - 15} especificações.\n"

            response_text += "\n---\n✅ Produto pronto para calcular aderência com editais!"
        else:
            response_text = f"❌ Erro ao processar arquivo: {resultado.get('error', 'Erro desconhecido')}"

        # Salvar resposta do assistente
        assistant_msg = Message(
            session_id=session_id,
            role='assistant',
            content=response_text,
            action_type='upload_manual'
        )
        db.add(assistant_msg)

        # Atualizar sessão
        session.updated_at = datetime.now()
        db.commit()

        return jsonify({
            "success": resultado.get("success", False),
            "response": response_text,
            "session_id": session_id,
            "produto": resultado.get("produto"),
            "especificacoes_extraidas": len(resultado.get("especificacoes", []))
        })

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Session Routes
# =============================================================================

@app.route("/api/sessions", methods=["GET"])
@require_auth
def get_sessions():
    user_id = get_current_user_id()
    db = get_db()
    try:
        sessions = db.query(Session).filter(
            Session.user_id == user_id
        ).order_by(Session.updated_at.desc()).all()

        return jsonify({"sessions": [s.to_dict() for s in sessions]})
    finally:
        db.close()


@app.route("/api/sessions", methods=["POST"])
@require_auth
def new_session():
    user_id = get_current_user_id()
    data = request.json or {}
    name = data.get("name", "Nova conversa")

    db = get_db()
    try:
        session = Session(user_id=user_id, name=name)
        db.add(session)
        db.commit()
        return jsonify(session.to_dict()), 201
    finally:
        db.close()


@app.route("/api/sessions/<session_id>", methods=["GET"])
@require_auth
def get_session_detail(session_id):
    user_id = get_current_user_id()
    db = get_db()
    try:
        session = db.query(Session).filter(
            Session.id == session_id,
            Session.user_id == user_id
        ).first()

        if not session:
            return jsonify({"error": "Sessão não encontrada"}), 404

        return jsonify(session.to_dict(include_messages=True))
    finally:
        db.close()


@app.route("/api/sessions/<session_id>", methods=["DELETE"])
@require_auth
def delete_session(session_id):
    user_id = get_current_user_id()
    db = get_db()
    try:
        session = db.query(Session).filter(
            Session.id == session_id,
            Session.user_id == user_id
        ).first()

        if not session:
            return jsonify({"error": "Sessão não encontrada"}), 404

        db.delete(session)
        db.commit()
        return jsonify({"message": "Sessão excluída"})
    finally:
        db.close()


@app.route("/api/sessions/<session_id>", methods=["PATCH"])
@require_auth
def update_session(session_id):
    user_id = get_current_user_id()
    data = request.json or {}
    new_name = data.get("name")

    if not new_name:
        return jsonify({"error": "name é obrigatório"}), 400

    db = get_db()
    try:
        session = db.query(Session).filter(
            Session.id == session_id,
            Session.user_id == user_id
        ).first()

        if not session:
            return jsonify({"error": "Sessão não encontrada"}), 404

        session.name = new_name
        db.commit()
        return jsonify({"message": "Sessão renomeada", "name": new_name})
    finally:
        db.close()


# =============================================================================
# Produtos Routes
# =============================================================================

@app.route("/api/produtos", methods=["GET"])
@require_auth
def listar_produtos_api():
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    categoria = request.args.get("categoria")
    nome = request.args.get("nome")

    resultado = tool_listar_produtos(user_id, empresa_id=empresa_id, categoria=categoria, nome=nome)
    return jsonify(resultado)


@app.route("/api/produtos/<produto_id>", methods=["GET"])
@require_auth
def get_produto(produto_id):
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        produto = db.query(Produto).filter(
            Produto.id == produto_id,
            Produto.empresa_id == empresa_id
        ).first()

        if not produto:
            return jsonify({"error": "Produto não encontrado"}), 404

        return jsonify(produto.to_dict(include_specs=True))
    finally:
        db.close()


@app.route("/api/produtos/<produto_id>/completude", methods=["GET"])
@require_auth
def get_produto_completude(produto_id):
    """Verifica completude do produto: dados básicos + specs vs máscara da subclasse."""
    from tools import tool_verificar_completude_produto
    user_id = get_current_user_id()
    resultado = tool_verificar_completude_produto(produto_id=produto_id, user_id=user_id)
    if not resultado.get("success"):
        return jsonify({"error": resultado.get("error", "Erro")}), 404
    return jsonify(resultado)


@app.route("/api/produtos/completude-batch", methods=["GET"])
@require_auth
def get_produtos_completude_batch():
    """obs 15/16 validador V8: farol+filtro de completude na grade.
    Retorna {produto_id: percentual_geral} para todos os produtos da empresa."""
    from tools import tool_verificar_completude_produto
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        ids = [p.id for p in db.query(Produto).filter(Produto.empresa_id == empresa_id).all()]
    finally:
        db.close()
    out = {}
    for pid in ids:
        try:
            r = tool_verificar_completude_produto(produto_id=pid, user_id=user_id)
            if r.get("success"):
                out[pid] = r.get("completude", {}).get("percentual_geral", 0)
        except Exception as e:
            print(f"[COMPLETUDE-BATCH] erro {pid}: {e}")
    return jsonify({"completude": out})


@app.route("/api/produtos/buscar-web", methods=["POST"])
@require_auth
def buscar_web_estruturado():
    """obs 13 validador V8: retorna resultados ESTRUTURADOS da busca web para
    o usuario escolher o que incorporar — NAO cadastra nada automaticamente."""
    from tools import tool_web_search
    user_id = get_current_user_id()
    data = request.get_json(silent=True) or {}
    nome = (data.get("nome") or "").strip()
    fabricante = (data.get("fabricante") or "").strip()
    if not nome:
        return jsonify({"error": "Informe o nome do produto"}), 400
    termo = f"manual datasheet {nome} {fabricante}".strip()
    resultado = tool_web_search(termo, user_id)
    if not resultado.get("success"):
        return jsonify({"error": resultado.get("error", "Falha na busca")}), 502
    return jsonify({
        "termo": termo,
        "pdfs": resultado.get("resultados_pdf", []),
        "outros": resultado.get("outros_resultados", []),
        "total": resultado.get("total_resultados", 0),
    })


# =============================================================================
# Editais Routes
# =============================================================================

@app.route("/api/editais", methods=["GET"])
@require_auth
def listar_editais_api():
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    status = request.args.get("status")
    uf = request.args.get("uf")
    categoria = request.args.get("categoria")

    resultado = tool_listar_editais(user_id, empresa_id=empresa_id, status=status, uf=uf, categoria=categoria)
    return jsonify(resultado)


@app.route("/api/editais/<edital_id>", methods=["GET"])
@require_auth
def get_edital(edital_id):
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()

        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404

        return jsonify(edital.to_dict(include_requisitos=True))
    finally:
        db.close()


@app.route("/api/editais/<edital_id>/pdf", methods=["GET"])
@require_auth
def download_edital_pdf(edital_id):
    """Download ou visualização do PDF do edital.
    Reutiliza a mesma lógica do chat: baixa, salva localmente, cria EditalDocumento.
    Na segunda vez, serve do disco instantaneamente.
    """
    import re
    import requests as req
    from models import EditalDocumento
    from datetime import datetime
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()

        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404

        download_flag = request.args.get('download', 'false').lower() == 'true'

        # === 1. Já tem arquivo local? Servir direto ===
        doc = db.query(EditalDocumento).filter(
            EditalDocumento.edital_id == edital_id,
            EditalDocumento.tipo == 'edital_principal'
        ).first()

        # Helper: se arquivo é ZIP, extrair PDF do edital de dentro
        import zipfile as _zf
        def _extrair_pdf_de_zip(zip_path):
            if not _zf.is_zipfile(zip_path):
                return zip_path  # Não é ZIP, retorna como está
            print(f"[PDF] Arquivo é ZIP, extraindo PDF: {zip_path}")
            upload_dir = os.path.dirname(zip_path)
            all_pdfs = []
            with _zf.ZipFile(zip_path, 'r') as zf:
                for name in zf.namelist():
                    if name.lower().endswith('.pdf'):
                        zf.extract(name, upload_dir)
                        fpath = os.path.join(upload_dir, name)
                        all_pdfs.append((fpath, os.path.getsize(fpath), os.path.basename(name).lower()))
                for name in zf.namelist():
                    if name.lower().endswith('.zip'):
                        zf.extract(name, upload_dir)
                        nested = os.path.join(upload_dir, name)
                        if _zf.is_zipfile(nested):
                            with _zf.ZipFile(nested, 'r') as zf2:
                                for n2 in zf2.namelist():
                                    if n2.lower().endswith('.pdf'):
                                        zf2.extract(n2, upload_dir)
                                        fp2 = os.path.join(upload_dir, n2)
                                        all_pdfs.append((fp2, os.path.getsize(fp2), os.path.basename(n2).lower()))
                            try: os.remove(nested)
                            except OSError: pass
            if not all_pdfs:
                return zip_path
            edital_pdfs = [p for p in all_pdfs if 'edital' in p[2] and 'anexo' not in p[2] and 'termo' not in p[2] and 'minuta' not in p[2]]
            best = max(edital_pdfs, key=lambda x: x[1]) if edital_pdfs else max(all_pdfs, key=lambda x: x[1])
            for p in all_pdfs:
                if p[0] != best[0]:
                    try: os.remove(p[0])
                    except OSError: pass
            pdf_filename = re.sub(r'[^\w\-_\.]', '_', os.path.basename(best[0]))
            final_path = os.path.join(upload_dir, pdf_filename)
            if best[0] != final_path:
                if os.path.exists(final_path): os.remove(final_path)
                os.rename(best[0], final_path)
            try: os.remove(zip_path)
            except OSError: pass
            # Limpar subpastas
            for p in all_pdfs:
                parent = os.path.dirname(p[0])
                if parent != upload_dir:
                    try: os.removedirs(parent)
                    except OSError: pass
            print(f"[PDF] PDF extraído de ZIP: {final_path}")
            return final_path

        if doc and doc.path_arquivo and os.path.exists(doc.path_arquivo):
            filepath = _extrair_pdf_de_zip(doc.path_arquivo)
            if filepath != doc.path_arquivo:
                doc.path_arquivo = filepath
                db.commit()
            return send_file(
                filepath,
                mimetype='application/pdf',
                as_attachment=download_flag,
                download_name=doc.nome_arquivo or f"edital_{edital.numero}.pdf"
            )

        # Se doc existe mas sem arquivo no disco, deletar para permitir re-download
        if doc and (not doc.path_arquivo or not os.path.exists(doc.path_arquivo or "")):
            db.delete(doc)
            db.commit()
            doc = None

        if edital.pdf_path and os.path.exists(edital.pdf_path):
            filepath = _extrair_pdf_de_zip(edital.pdf_path)
            if filepath != edital.pdf_path:
                edital.pdf_path = filepath
                db.commit()
            return send_file(
                filepath,
                mimetype='application/pdf',
                as_attachment=download_flag,
                download_name=edital.pdf_titulo or f"edital_{edital.numero}.pdf"
            )

        # === 2. Extrair dados PNCP da URL se necessário ===
        if not (edital.cnpj_orgao and edital.ano_compra and edital.seq_compra):
            if edital.url and 'pncp.gov.br' in edital.url:
                # Formato /compras/{cnpj}/{ano}/{seq}
                match = re.search(r'/compras/(\d{14}\d{0,2})/(\d{4})/(\d+)', edital.url)
                if match:
                    edital.cnpj_orgao = match.group(1)
                    edital.ano_compra = int(match.group(2))
                    edital.seq_compra = int(match.group(3))
                else:
                    # Formato /editais/{cnpj}-{id}-{seq}/{ano}
                    match = re.search(r'/editais/(\d{14}\d{0,2})-(\d+)-(\d+)/(\d{4})', edital.url)
                    if match:
                        edital.cnpj_orgao = match.group(1)
                        edital.ano_compra = int(match.group(4))
                        edital.seq_compra = int(match.group(3))
                if match:
                    db.commit()
                    print(f"[PDF] Dados PNCP extraídos da URL: cnpj={edital.cnpj_orgao}, ano={edital.ano_compra}, seq={edital.seq_compra}")

        # === 3. Baixar via PNCP e SALVAR localmente (igual ao chat) ===
        if edital.cnpj_orgao and edital.ano_compra and edital.seq_compra:
            try:
                from tools import tool_buscar_arquivos_edital_pncp, tool_baixar_pdf_pncp

                arquivos_result = tool_buscar_arquivos_edital_pncp(
                    cnpj=edital.cnpj_orgao, ano=edital.ano_compra, seq=edital.seq_compra
                )

                if arquivos_result.get('success') and arquivos_result.get('arquivos'):
                    arquivo_edital = arquivos_result.get('arquivo_edital') or arquivos_result['arquivos'][0]

                    # Baixar e salvar no disco (tool_baixar_pdf_pncp salva em uploads/{user_id}/editais/)
                    download_result = tool_baixar_pdf_pncp(
                        cnpj=edital.cnpj_orgao,
                        ano=edital.ano_compra,
                        seq=edital.seq_compra,
                        sequencial_arquivo=arquivo_edital['sequencial'],
                        user_id=user_id,
                        edital_id=edital.id
                    )

                    if download_result.get('success'):
                        filepath = download_result['filepath']
                        filename = download_result['filename']

                        # Extrair texto do PDF
                        texto_extraido = ""
                        try:
                            from PyPDF2 import PdfReader
                            reader = PdfReader(filepath)
                            for page in reader.pages:
                                texto_extraido += page.extract_text() or ""
                        except Exception:
                            pass

                        # Salvar no banco (EditalDocumento) — igual processar_baixar_pdf_edital
                        novo_doc = EditalDocumento(
                            id=str(uuid.uuid4()),
                            edital_id=edital.id,
                            tipo='edital_principal',
                            nome_arquivo=filename,
                            path_arquivo=filepath,
                            texto_extraido=texto_extraido[:100000] if texto_extraido else None,
                            processado=True,
                            created_at=datetime.now()
                        )
                        db.add(novo_doc)

                        # Atualizar edital com pdf_path, pdf_url, pdf_titulo
                        edital.pdf_path = filepath
                        edital.pdf_url = download_result.get('url') or edital.pdf_url
                        edital.pdf_titulo = arquivo_edital.get('titulo')
                        db.commit()

                        print(f"[PDF] Salvo localmente: {filepath} ({download_result['filesize']/1024:.1f} KB)")

                        return send_file(
                            filepath,
                            mimetype='application/pdf',
                            as_attachment=download_flag,
                            download_name=filename
                        )
            except Exception as e:
                print(f"[PDF] Erro ao baixar via PNCP: {e}")
                import traceback
                traceback.print_exc()

        # === 4. Fallback: proxy da pdf_url ou url genérica ===
        fallback_url = edital.pdf_url or edital.url
        if fallback_url:
            try:
                resp = req.get(fallback_url, timeout=60, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }, allow_redirects=True)
                content_type = resp.headers.get('Content-Type', '')
                if resp.status_code == 200 and ('pdf' in content_type.lower() or fallback_url.lower().endswith('.pdf')):
                    # Salvar localmente
                    upload_dir = os.path.join(UPLOAD_FOLDER, user_id, "editais")
                    os.makedirs(upload_dir, exist_ok=True)
                    safe_numero = re.sub(r'[^\w\-.]', '_', edital.numero or edital_id)
                    filepath = os.path.join(upload_dir, f"edital_{safe_numero}.pdf")
                    with open(filepath, 'wb') as f:
                        f.write(resp.content)

                    novo_doc = EditalDocumento(
                        id=str(uuid.uuid4()),
                        edital_id=edital.id,
                        tipo='edital_principal',
                        nome_arquivo=f"edital_{safe_numero}.pdf",
                        path_arquivo=filepath,
                        processado=False,
                        created_at=datetime.now()
                    )
                    db.add(novo_doc)
                    edital.pdf_path = filepath
                    db.commit()

                    return send_file(
                        filepath,
                        mimetype='application/pdf',
                        as_attachment=download_flag,
                        download_name=f"edital_{safe_numero}.pdf"
                    )
            except Exception as e:
                print(f"[PDF] Erro fallback URL: {e}")

        return jsonify({"error": "PDF não disponível para este edital"}), 404
    finally:
        db.close()


@app.route("/api/editais/<edital_id>/pdf/view", methods=["GET"])
def view_edital_pdf(edital_id):
    """Serve PDF já baixado para visualização inline (iframe/object).
    Usa token via query param para permitir acesso direto pelo browser.
    """
    empresa_id = get_current_empresa_id()
    from models import EditalDocumento
    token = request.args.get('token')
    if not token:
        return jsonify({"error": "Token não fornecido"}), 401
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        user_id = payload.get('user_id')
    except Exception:
        return jsonify({"error": "Token inválido"}), 401

    db = get_db()
    try:
        edital = db.query(Edital).filter(Edital.id == edital_id, Edital.empresa_id == empresa_id).first()
        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404

        doc = db.query(EditalDocumento).filter(
            EditalDocumento.edital_id == edital_id,
            EditalDocumento.tipo == 'edital_principal'
        ).first()

        pdf_path = None
        if doc and doc.path_arquivo and os.path.exists(doc.path_arquivo):
            pdf_path = doc.path_arquivo
        elif edital.pdf_path and os.path.exists(edital.pdf_path):
            pdf_path = edital.pdf_path

        if not pdf_path:
            return jsonify({"error": "PDF não encontrado. Clique em 'Baixar PDF do Edital' na aba IA primeiro."}), 404

        # Ler o arquivo e retornar como response puro — sem Content-Disposition
        # para evitar que o browser trate como download dentro de iframe
        with open(pdf_path, 'rb') as f:
            pdf_bytes = f.read()
        resp = app.response_class(pdf_bytes, mimetype='application/pdf')
        resp.headers['Content-Length'] = str(len(pdf_bytes))
        resp.headers['Cache-Control'] = 'public, max-age=3600'
        return resp
    finally:
        db.close()


# ─── Endpoint: Extrair/Listar Lotes do Edital ────────────────────────────────

@app.route("/api/editais/<edital_id>/lotes", methods=["GET"])
@require_auth
def listar_lotes_edital(edital_id):
    """Lista lotes do edital. Se não existem, retorna lista vazia."""
    from models import Lote, LoteItem, EditalItem
    user_id = get_current_user_id()
    # CV09-12c (Arnaldo Sprint 2 V8): empresa_id era usado MAS NUNCA definido,
    # gerando NameError -> 500 -> frontend setava setLotesEdital([]) e o
    # validador via "0 lotes ao voltar" mesmo apos commit do extrair_lotes.
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        lotes = db.query(Lote).filter(
            Lote.edital_id == edital_id,
            Lote.empresa_id == empresa_id
        ).order_by(Lote.numero_lote).all()

        lotes_resp = []
        for l in lotes:
            ld = l.to_dict()
            lote_itens = db.query(LoteItem).filter(LoteItem.lote_id == l.id).order_by(LoteItem.ordem).all()
            ld["itens"] = []
            for li in lote_itens:
                ei = db.query(EditalItem).filter(EditalItem.id == li.edital_item_id).first()
                if ei:
                    ld["itens"].append(ei.to_dict())
            lotes_resp.append(ld)

        return jsonify({"success": True, "lotes": lotes_resp, "total": len(lotes_resp)})
    finally:
        db.close()


@app.route("/api/editais/<edital_id>/buscar-itens-pncp", methods=["POST"])
@require_auth
def buscar_itens_pncp(edital_id):
    """Busca itens do edital diretamente na API PNCP e salva no banco."""
    user_id = get_current_user_id()
    try:
        from tools import tool_buscar_itens_edital_pncp
        resultado = tool_buscar_itens_edital_pncp(edital_id=edital_id, user_id=user_id)
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/editais/<edital_id>/lotes/extrair", methods=["POST"])
@require_auth
def extrair_lotes_edital(edital_id):
    """Extrai lotes do edital via IA (lê PDF) e cria no banco."""
    from tools import tool_organizar_lotes
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    forcar = request.json.get("forcar", False) if request.is_json else False

    result = tool_organizar_lotes(
        edital_id=edital_id,
        user_id=user_id,
        empresa_id=empresa_id,
        importar_pncp=True,
        forcar=forcar
    )

    status_code = 200 if result.get("success") else 400
    return jsonify(result), status_code


@app.route("/api/editais/numero/<numero>/pdf", methods=["GET"])
@require_auth
def download_edital_pdf_by_numero(numero):
    """Download ou visualização do PDF do edital pelo número"""
    from models import EditalDocumento
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        # Normalizar número para busca
        numero_busca = numero.replace('_', '/').replace('-', '/').upper()

        # Buscar edital pelo número
        edital = db.query(Edital).filter(
            Edital.empresa_id == empresa_id
        ).all()

        # Encontrar edital com número similar
        edital_encontrado = None
        for e in edital:
            num_edital = e.numero.replace('-', '/').upper()
            if num_edital == numero_busca or numero_busca in num_edital or num_edital in numero_busca:
                edital_encontrado = e
                break

        if not edital_encontrado:
            return jsonify({"error": f"Edital {numero} não encontrado"}), 404

        # Buscar documento do edital
        doc = db.query(EditalDocumento).filter(
            EditalDocumento.edital_id == edital_encontrado.id,
            EditalDocumento.tipo == 'edital_principal'
        ).first()

        if not doc or not doc.path_arquivo:
            return jsonify({"error": "PDF não disponível para este edital"}), 404

        if not os.path.exists(doc.path_arquivo):
            return jsonify({"error": "Arquivo não encontrado no servidor"}), 404

        # Parâmetro para forçar download
        download = request.args.get('download', 'false').lower() == 'true'

        return send_file(
            doc.path_arquivo,
            mimetype='application/pdf',
            as_attachment=download,
            download_name=doc.nome_arquivo or f"edital_{edital_encontrado.numero}.pdf"
        )
    finally:
        db.close()


@app.route("/api/proxy/pdf/pncp/<cnpj>/<int:ano>/<int:seq>", methods=["GET"])
@app.route("/api/proxy/pdf/pncp/<cnpj>/<int:ano>/<int:seq>/<int:arquivo_id>", methods=["GET"])
def proxy_pdf_pncp(cnpj, ano, seq, arquivo_id=1):
    """
    Proxy para visualizar PDFs do PNCP no navegador.
    Busca o arquivo da API do PNCP, extrai PDF do ZIP se necessário,
    e retorna com headers corretos para visualização inline.
    """
    import requests as req
    from io import BytesIO
    import zipfile

    # Construir URL do PNCP
    pdf_url = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos/{arquivo_id}"

    try:
        print(f"[PDF PROXY] Buscando: {pdf_url}")
        resp = req.get(pdf_url, timeout=60)

        if resp.status_code == 200:
            content = resp.content
            content_type = resp.headers.get('Content-Type', '')
            content_disp = resp.headers.get('Content-Disposition', '')

            # Detectar nome do arquivo
            filename = f"edital_pncp_{ano}_{seq}.pdf"
            if 'filename=' in content_disp:
                import re
                match = re.search(r'filename[^;=\n]*=(([\'"]).*?\2|[^;\n]*)', content_disp)
                if match:
                    filename = match.group(1).strip('"\'')

            # Verificar se é um ZIP (PNCP frequentemente retorna ZIP com PDFs dentro)
            is_zip = (
                filename.lower().endswith('.zip') or
                'zip' in content_type.lower() or
                content[:4] == b'PK\x03\x04'  # Magic bytes do ZIP
            )

            if is_zip:
                print(f"[PDF PROXY] Arquivo é ZIP, extraindo PDF...")
                try:
                    zip_buffer = BytesIO(content)
                    with zipfile.ZipFile(zip_buffer, 'r') as zf:
                        # Listar arquivos no ZIP
                        pdf_files = [f for f in zf.namelist() if f.lower().endswith('.pdf')]
                        print(f"[PDF PROXY] PDFs no ZIP: {pdf_files}")

                        if pdf_files:
                            # Priorizar arquivo com "Edital" no nome, senão pega o primeiro
                            pdf_to_extract = pdf_files[0]
                            for pf in pdf_files:
                                if 'edital' in pf.lower():
                                    pdf_to_extract = pf
                                    break

                            print(f"[PDF PROXY] Extraindo: {pdf_to_extract}")
                            pdf_content = zf.read(pdf_to_extract)
                            filename = pdf_to_extract
                            content = pdf_content
                        else:
                            print(f"[PDF PROXY] Nenhum PDF encontrado no ZIP")
                            return jsonify({"error": "ZIP não contém arquivos PDF"}), 404
                except zipfile.BadZipFile:
                    print(f"[PDF PROXY] Arquivo não é ZIP válido, tentando como PDF")

            # Parâmetro para forçar download
            download = request.args.get('download', 'false').lower() == 'true'

            pdf_buffer = BytesIO(content)
            return send_file(
                pdf_buffer,
                mimetype='application/pdf',
                as_attachment=download,
                download_name=filename if filename.lower().endswith('.pdf') else f"{filename}.pdf"
            )
        else:
            print(f"[PDF PROXY] Erro PNCP: {resp.status_code}")
            return jsonify({"error": f"PDF não encontrado no PNCP (status {resp.status_code})"}), 404

    except Exception as e:
        print(f"[PDF PROXY] Erro: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Erro ao buscar PDF: {str(e)}"}), 500


# =============================================================================
# Fontes Routes
# =============================================================================

@app.route("/api/fontes", methods=["GET"])
def listar_fontes_api():
    resultado = tool_listar_fontes()
    return jsonify(resultado)


# =============================================================================
# Análises Routes
# =============================================================================

@app.route("/api/analises", methods=["GET"])
@require_auth
def listar_analises():
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        analises = db.query(Analise).filter(
            Analise.empresa_id == empresa_id
        ).order_by(Analise.created_at.desc()).limit(50).all()

        return jsonify({"analises": [a.to_dict() for a in analises]})
    finally:
        db.close()


@app.route("/api/analises/<analise_id>", methods=["GET"])
@require_auth
def get_analise(analise_id):
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        analise = db.query(Analise).filter(
            Analise.id == analise_id,
            Analise.empresa_id == empresa_id
        ).first()

        if not analise:
            return jsonify({"error": "Análise não encontrada"}), 404

        return jsonify(analise.to_dict(include_detalhes=True))
    finally:
        db.close()


# =============================================================================
# Propostas Routes
# =============================================================================

@app.route("/api/propostas", methods=["GET"])
@require_auth
def listar_propostas():
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        propostas = db.query(Proposta).filter(
            Proposta.empresa_id == empresa_id
        ).order_by(Proposta.created_at.desc()).limit(50).all()

        return jsonify({"propostas": [p.to_dict() for p in propostas]})
    finally:
        db.close()


@app.route("/api/propostas/<proposta_id>", methods=["GET"])
@require_auth
def get_proposta(proposta_id):
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        proposta = db.query(Proposta).filter(
            Proposta.id == proposta_id,
            Proposta.empresa_id == empresa_id
        ).first()

        if not proposta:
            return jsonify({"error": "Proposta não encontrada"}), 404

        return jsonify(proposta.to_dict())
    finally:
        db.close()


# =============================================================================
# FASE 2 — Proposta: Novos endpoints (UC-R01 a UC-R07)
# =============================================================================

@app.route("/api/propostas/upload", methods=["POST"])
@require_auth
def upload_proposta():
    """Upload de proposta via arquivo (.docx ou .pdf) + dados do formulário."""
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        edital_id = request.form.get("edital_id")
        produto_id = request.form.get("produto_id")
        preco = request.form.get("preco")
        quantidade = request.form.get("quantidade", 1)
        lote_id = request.form.get("lote_id")

        if not edital_id or not produto_id:
            return jsonify({"error": "edital_id e produto_id são obrigatórios"}), 400

        file = request.files.get("file")
        texto_tecnico = None
        arquivo_path = None

        if file:
            filename = file.filename
            save_dir = os.path.join(UPLOAD_FOLDER, "propostas")
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, f"{uuid.uuid4()}_{filename}")
            file.save(save_path)
            arquivo_path = save_path

            # Se .docx, extrair texto
            if filename.lower().endswith('.docx'):
                try:
                    from docx import Document as DocxDocument
                    doc = DocxDocument(save_path)
                    texto_tecnico = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
                except ImportError:
                    texto_tecnico = "[python-docx não instalado — texto não extraído]"
                except Exception as ex:
                    texto_tecnico = f"[Erro ao extrair texto: {ex}]"

        from decimal import Decimal as _Dec
        proposta = Proposta(
            edital_id=edital_id,
            produto_id=produto_id,
            user_id=user_id,
            empresa_id=empresa_id,
            texto_tecnico=texto_tecnico,
            preco_unitario=_Dec(str(preco)) if preco else None,
            preco_total=_Dec(str(float(preco) * int(quantidade))) if preco else None,
            quantidade=int(quantidade),
            arquivo_path=arquivo_path,
            lote_id=lote_id,
            status='rascunho',
        )
        db.add(proposta)
        db.commit()

        return jsonify({"success": True, "proposta": proposta.to_dict()}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/propostas/<proposta_id>/anvisa", methods=["GET"])
@require_auth
def verificar_anvisa(proposta_id):
    """Verifica status ANVISA do produto da proposta."""
    user_id = get_current_user_id()
    result = tool_verificar_anvisa_proposta(proposta_id, user_id)
    if result.get("success"):
        return jsonify(result)
    return jsonify(result), 404 if "não encontrad" in result.get("error", "") else 500


@app.route("/api/propostas/<proposta_id>/auditoria-docs", methods=["GET"])
@require_auth
def auditoria_documental(proposta_id):
    """Auditoria documental da proposta — checklist de documentos."""
    user_id = get_current_user_id()
    result = tool_auditoria_documental(proposta_id, user_id)
    if result.get("success"):
        return jsonify(result)
    return jsonify(result), 404 if "não encontrad" in result.get("error", "") else 500


@app.route("/api/propostas/<proposta_id>/smart-split", methods=["POST"])
@require_auth
def smart_split(proposta_id):
    """Divide PDF da proposta em partes menores que 25MB."""
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        proposta = db.query(Proposta).filter(
            Proposta.id == proposta_id,
            Proposta.empresa_id == empresa_id
        ).first()
        if not proposta:
            return jsonify({"error": "Proposta não encontrada"}), 404
        if not proposta.arquivo_path:
            return jsonify({"error": "Proposta não possui arquivo anexado"}), 400

        data = request.get_json(silent=True) or {}
        max_size = data.get("max_size_mb", 25)

        result = tool_smart_split_pdf(proposta.arquivo_path, max_size_mb=max_size)
        return jsonify(result)
    finally:
        db.close()


@app.route("/api/propostas/<proposta_id>/dossie", methods=["GET"])
@require_auth
def gerar_dossie(proposta_id):
    """Gera ZIP com dossiê completo da proposta: texto + documentos validados."""
    import zipfile
    import io
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        proposta = db.query(Proposta).filter(
            Proposta.id == proposta_id,
            Proposta.empresa_id == empresa_id
        ).first()
        if not proposta:
            return jsonify({"error": "Proposta não encontrada"}), 404

        # Criar ZIP em memória
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            # 1. Texto da proposta como .txt
            if proposta.texto_tecnico:
                zf.writestr("proposta_tecnica.txt", proposta.texto_tecnico)

            # 2. Arquivo original da proposta (PDF/DOCX)
            if proposta.arquivo_path and os.path.exists(proposta.arquivo_path):
                nome_arq = os.path.basename(proposta.arquivo_path)
                zf.write(proposta.arquivo_path, f"proposta_{nome_arq}")

            # 3. Documentos do produto
            docs_produto = db.query(ProdutoDocumento).filter(
                ProdutoDocumento.produto_id == proposta.produto_id
            ).all()
            for doc in docs_produto:
                if doc.path_arquivo and os.path.exists(doc.path_arquivo):
                    zf.write(doc.path_arquivo, f"documentos/{doc.tipo}_{doc.nome_arquivo}")

            # 4. Resultado ANVISA se houver
            validacoes = db.query(AnvisaValidacao).filter(
                AnvisaValidacao.proposta_id == proposta_id
            ).all()
            if validacoes:
                anvisa_txt = "VALIDAÇÃO ANVISA\n" + "=" * 40 + "\n\n"
                for v in validacoes:
                    anvisa_txt += f"Registro: {v.registro or 'N/A'}\n"
                    anvisa_txt += f"Status: {v.status}\n"
                    anvisa_txt += f"Data verificação: {v.data_verificacao}\n"
                    anvisa_txt += f"Log: {v.log_texto or ''}\n\n"
                zf.writestr("anvisa_validacao.txt", anvisa_txt)

        buffer.seek(0)
        edital = db.query(Edital).filter(Edital.id == proposta.edital_id).first()
        numero = (edital.numero or "sem_numero").replace("/", "-").replace(" ", "_") if edital else "sem_edital"
        filename = f"dossie_proposta_{numero}_{proposta_id[:8]}.zip"

        return send_file(
            buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Dashboard Stats Route
# =============================================================================

@app.route("/api/dashboard/stats", methods=["GET"])
@require_auth
def get_dashboard_stats():
    """Retorna estatísticas reais do banco para o Dashboard, filtradas pelo user_id."""
    from sqlalchemy import func, case
    from datetime import date, timedelta

    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        # Total de editais
        total_editais = db.query(Edital).filter(Edital.empresa_id == empresa_id).count()

        # Editais por status
        status_rows = (
            db.query(Edital.status, func.count(Edital.id))
            .filter(Edital.empresa_id == empresa_id)
            .group_by(Edital.status)
            .all()
        )
        editais_por_status = {row[0]: row[1] for row in status_rows}

        # Total de propostas
        total_propostas = db.query(Proposta).filter(Proposta.empresa_id == empresa_id).count()

        # Propostas por status
        prop_status_rows = (
            db.query(Proposta.status, func.count(Proposta.id))
            .filter(Proposta.empresa_id == empresa_id)
            .group_by(Proposta.status)
            .all()
        )
        propostas_por_status = {row[0]: row[1] for row in prop_status_rows}

        # Taxa de sucesso: editais ganhos / (ganhos + perdidos)
        ganhos = editais_por_status.get('ganho', 0) + editais_por_status.get('vencedor', 0)
        perdidos = editais_por_status.get('perdido', 0) + editais_por_status.get('perdedor', 0)
        total_encerrados = ganhos + perdidos
        taxa_sucesso = round(ganhos / total_encerrados, 4) if total_encerrados > 0 else 0.0

        # Valor total contratado
        valor_row = (
            db.query(func.coalesce(func.sum(Contrato.valor_total), 0))
            .filter(Contrato.empresa_id == empresa_id)
            .scalar()
        )
        valor_total_contratado = float(valor_row) if valor_row else 0.0

        # Editais por mês (últimos 6 meses)
        seis_meses_atras = date.today().replace(day=1)
        # Recalcular como 6 meses atrás
        mes = seis_meses_atras.month - 6
        ano = seis_meses_atras.year
        if mes <= 0:
            mes += 12
            ano -= 1
        from datetime import datetime as dt
        data_inicio = dt(ano, mes, 1)

        mes_rows = (
            db.query(
                func.date_format(Edital.created_at, '%Y-%m').label('mes'),
                func.count(Edital.id).label('total')
            )
            .filter(
                Edital.empresa_id == empresa_id,
                Edital.created_at >= data_inicio
            )
            .group_by('mes')
            .order_by('mes')
            .all()
        )
        editais_por_mes = [{"mes": row[0], "total": row[1]} for row in mes_rows]

        # Próximos prazos (editais com data_abertura nos próximos 30 dias)
        hoje = date.today()
        em_30_dias = hoje + timedelta(days=30)
        prazo_rows = (
            db.query(Edital.numero, Edital.data_abertura, Edital.orgao, Edital.valor_referencia)
            .filter(
                Edital.empresa_id == empresa_id,
                Edital.data_abertura >= hoje,
                Edital.data_abertura <= em_30_dias,
                Edital.status.in_(['novo', 'analisando', 'participando'])
            )
            .order_by(Edital.data_abertura)
            .limit(10)
            .all()
        )
        proximos_prazos = [
            {
                "edital": row[0],
                "prazo": row[1].date().isoformat() if row[1] else None,
                "dias_restantes": (row[1].date() - hoje).days if row[1] else None,
                "orgao": row[2] or "",
                "valor": float(row[3]) if row[3] else 0
            }
            for row in prazo_rows
        ]

        # Lances/sessoes de pregao criados hoje
        lances_hoje = db.query(SessaoPregao).filter(
            SessaoPregao.empresa_id == empresa_id,
            func.date(SessaoPregao.created_at) == hoje
        ).count()

        return jsonify({
            "total_editais": total_editais,
            "editais_por_status": editais_por_status,
            "total_propostas": total_propostas,
            "propostas_por_status": propostas_por_status,
            "taxa_sucesso": taxa_sucesso,
            "valor_total_contratado": valor_total_contratado,
            "editais_por_mes": editais_por_mes,
            "proximos_prazos": proximos_prazos,
            "lances_hoje": lances_hoje
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Endpoints: Modalidades, Origens, Áreas de Produto (filtros parametrizáveis)
# =============================================================================

def inferir_tipo_produto(objeto: str) -> str:
    """Infere o tipo de produto a partir do texto do objeto do edital."""
    if not objeto:
        return ""
    obj = objeto.lower()
    # Reagentes
    if any(w in obj for w in ['reagente', 'kit diagnóstico', 'kit diagnostico', 'teste rápido', 'teste rapido',
                                'hematologi', 'bioquímic', 'bioquimic', 'imunologi', 'microbiologi', 'sorologi']):
        return "Reagentes"
    # Equipamentos
    if any(w in obj for w in ['equipamento', 'analisador', 'microscópio', 'microscopio', 'centrífuga', 'centrifuga',
                                'autoclave', 'espectrofotômetro', 'espectrofotometro', 'aparelho', 'máquina', 'maquina']):
        return "Equipamentos"
    # Comodato
    if any(w in obj for w in ['comodato', 'cessão de uso', 'cessao de uso']):
        return "Comodato"
    # Aluguel
    if any(w in obj for w in ['aluguel', 'locação', 'locacao', 'locaçao']):
        return "Aluguel"
    # Insumos Hospitalares
    if any(w in obj for w in ['insumo', 'material hospitalar', 'luva', 'seringa', 'agulha', 'gaze',
                                'cateter', 'sonda', 'material médico', 'material medico']):
        return "Insumos Hospitalares"
    # Informática
    if any(w in obj for w in ['computador', 'servidor', 'notebook', 'software', 'licença software',
                                'impressora', 'monitor', 'informática', 'informatica', 'desktop']):
        return "Informática"
    # Redes
    if any(w in obj for w in ['switch', 'roteador', 'firewall', 'cabeamento', 'fibra óptica', 'fibra optica', 'rede']):
        return "Redes"
    # Mobiliário
    if any(w in obj for w in ['mobiliário', 'mobiliario', 'mesa', 'cadeira', 'armário', 'armario', 'estante']):
        return "Mobiliário"
    return ""


def inferir_origem_orgao(orgao: str, orgao_tipo: str = "") -> str:
    """Infere a origem/tipo do órgão licitante."""
    if not orgao:
        return ""
    org = orgao.lower()
    tipo = (orgao_tipo or "").lower()

    if any(w in org for w in ['hospital', 'hc ', 'hcpa', 'hu ', 'santa casa']):
        return "Hospital"
    if any(w in org for w in ['universidade', 'ufrj', 'usp', 'unicamp', 'ufmg', 'ufrgs', 'ufsc', 'ufba',
                                'ufscar', 'ufpe', 'unb', 'ufpr', 'unifesp', 'unesp', 'uerj']):
        return "Universidade"
    if any(w in org for w in ['lacen', 'laboratório central', 'laboratorio central']):
        return "LACEN"
    if any(w in org for w in ['exército', 'exercito', 'marinha', 'aeronáutica', 'aeronautica', 'força aérea',
                                'forca aerea', 'comando militar', 'arsenal']):
        return "Força Armada"
    if any(w in org for w in ['fapesp', 'faperj', 'fapemig', 'cnpq', 'capes', 'fundação de amparo',
                                'fundacao de amparo']):
        return "Fundações de Pesquisa"
    if any(w in org for w in ['fiocruz', 'embrapa', 'inpe', 'inpa', 'impa', 'lncc', 'cbpf',
                                'centro de pesquisa', 'instituto de pesquisa']):
        return "Centros de Pesquisas"
    if any(w in org for w in ['fundação', 'fundacao']) and 'pesquisa' not in org:
        return "Fundações Diversas"
    if any(w in org for w in ['autarquia', 'agência', 'agencia', 'anatel', 'anvisa', 'anp', 'ans', 'ana',
                                'ibama', 'inmetro']):
        return "Autarquia"
    if tipo == 'federal' or any(w in org for w in ['ministério', 'ministerio', 'governo federal', 'união', 'uniao']):
        return "Federal"
    if tipo == 'estadual' or any(w in org for w in ['governo do estado', 'secretaria de estado', 'estado de',
                                                      'governo estadual']):
        return "Estadual"
    if tipo == 'municipal' or any(w in org for w in ['prefeitura', 'município', 'municipio', 'câmara municipal',
                                                       'camara municipal']):
        return "Municipal"
    return ""


@app.route("/api/modalidades", methods=["GET"])
@require_auth
def listar_modalidades():
    """Lista todas as modalidades de licitação ativas."""
    db = get_db()
    try:
        items = db.query(ModalidadeLicitacao).filter(ModalidadeLicitacao.ativo == True).order_by(ModalidadeLicitacao.ordem).all()
        return jsonify({"success": True, "items": [m.to_dict() for m in items]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/origens", methods=["GET"])
@require_auth
def listar_origens():
    """Lista todas as origens de órgão ativas."""
    db = get_db()
    try:
        items = db.query(OrigemOrgao).filter(OrigemOrgao.ativo == True).order_by(OrigemOrgao.ordem).all()
        return jsonify({"success": True, "items": [o.to_dict() for o in items]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/areas-produto", methods=["GET"])
@require_auth
def listar_areas_produto():
    """Lista áreas com classes e subclasses aninhadas (filtradas por empresa)."""
    db = get_db()
    try:
        empresa_id = get_current_empresa_id()
        query = db.query(AreaProduto).filter(AreaProduto.ativo == True)
        if empresa_id:
            query = query.filter(AreaProduto.empresa_id == empresa_id)
        items = query.order_by(AreaProduto.ordem).all()
        return jsonify({"success": True, "items": [a.to_dict() for a in items]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Score Profundo: 6 dimensões via Reasoner para editais da busca
# =============================================================================

def _salvar_edital_temp_para_score(edital_data, user_id, empresa_id):
    """Salva edital da busca no banco para poder chamar tool_calcular_scores_validacao.
    Retorna edital_id se criado/encontrado, None se erro."""
    db = get_db()
    try:
        numero = edital_data.get("numero", "")
        orgao = edital_data.get("orgao", "")

        # Verificar se já existe
        existe = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.numero == numero,
            Edital.orgao == orgao
        ).first()

        if existe:
            return str(existe.id)

        # Criar novo
        from datetime import datetime as _dt
        novo = Edital(
            user_id=user_id,
            empresa_id=empresa_id,
            numero=numero or f"TEMP-{str(uuid.uuid4())[:8]}",
            orgao=orgao or "Não identificado",
            objeto=edital_data.get("objeto") or edital_data.get("descricao") or "—",
            modalidade="pregao_eletronico",
            status="temp_score",
            fonte=edital_data.get("fonte"),
            uf=edital_data.get("uf"),
            cidade=edital_data.get("cidade"),
            url=edital_data.get("url") or edital_data.get("link"),
            cnpj_orgao=edital_data.get("cnpj_orgao"),
            ano_compra=edital_data.get("ano_compra"),
            seq_compra=edital_data.get("seq_compra"),
        )
        if edital_data.get("valor_referencia") or edital_data.get("valor_estimado"):
            try:
                novo.valor_referencia = float(edital_data.get("valor_referencia") or edital_data.get("valor_estimado"))
            except (ValueError, TypeError):
                pass
        if edital_data.get("data_abertura"):
            try:
                d = edital_data["data_abertura"]
                if isinstance(d, str):
                    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                        try:
                            novo.data_abertura = _dt.strptime(d[:19], fmt)
                            break
                        except (ValueError, TypeError):
                            continue
            except Exception:
                pass

        db.add(novo)
        db.commit()
        edital_id = str(novo.id)
        print(f"[SCORE_PROFUNDO] Edital salvo: {numero} -> {edital_id}")

        # CV13-9 (Arnaldo Sprint 2 V8): se vier com dados PNCP, agendar
        # auto-download do PDF em background. Antes, 85% dos editais
        # entravam por esse caminho e ficavam sem texto extraido.
        if novo.cnpj_orgao and novo.ano_compra and novo.seq_compra:
            try:
                import threading
                from tools import download_pdf_edital_bg
                _eid = edital_id
                _uid = user_id
                threading.Thread(
                    target=lambda: download_pdf_edital_bg(_eid, _uid),
                    daemon=True,
                    name=f"pdf-edital-{_eid}"
                ).start()
            except Exception as ex:
                print(f"[CV13-9] Erro ao agendar download PDF: {ex}")

        return edital_id
    except Exception as e:
        db.rollback()
        print(f"[SCORE_PROFUNDO] Erro ao salvar edital: {e}")
        return None
    finally:
        db.close()


def _calcular_score_profundo(editais, user_id, empresa_id):
    """Score profundo: 6 dimensões via DeepSeek para cada edital."""
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not editais:
        return editais

    t0 = time.time()

    def _score_one(edital):
        try:
            edital_id = _salvar_edital_temp_para_score(edital, user_id, empresa_id)
            if not edital_id:
                edital["score_tecnico"] = edital.get("score_tecnico", 0)
                edital["score_profundo"] = None
                return edital

            resultado = tool_calcular_scores_validacao(
                edital_id=edital_id, user_id=user_id, produto_id=None
            )

            if resultado.get("success"):
                scores = resultado.get("scores", {})
                score_geral = resultado.get("score_geral", 0)
                # Só sobrescreve score_tecnico se não havia (modo profundo puro)
                # No modo hibrido, preserva o score rápido para ordenação
                if not edital.get("score_tecnico"):
                    edital["score_tecnico"] = score_geral
                edital["score_profundo"] = {
                    "scores": scores,
                    "score_geral": score_geral,
                    "decisao": resultado.get("decisao", "AVALIAR"),
                    "justificativa": resultado.get("justificativa", ""),
                    "pontos_positivos": resultado.get("pontos_positivos", []),
                    "pontos_atencao": resultado.get("pontos_atencao", []),
                }
                # Mapear decisao GO/NO-GO para recomendacao PARTICIPAR/NÃO PARTICIPAR
                decisao = resultado.get("decisao", "AVALIAR")
                if decisao == "GO":
                    edital["recomendacao"] = "PARTICIPAR"
                elif decisao == "NO-GO":
                    edital["recomendacao"] = "NÃO PARTICIPAR"
                else:
                    edital["recomendacao"] = "AVALIAR"
                edital["justificativa"] = resultado.get("justificativa", "")
            else:
                edital["score_profundo"] = None
        except Exception as e:
            print(f"[SCORE_PROFUNDO] Erro: {e}")
            edital["score_profundo"] = None
        return edital

    MAX_WORKERS = min(len(editais), 2)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(_score_one, e): e for e in editais}
        for future in as_completed(futures, timeout=600):
            try:
                future.result()
            except Exception as e:
                print(f"[SCORE_PROFUNDO] Future erro: {e}")

    editais.sort(key=lambda x: x.get("score_tecnico", 0), reverse=True)

    # Limpar editais temporários criados para o cálculo de score
    try:
        db = get_db()
        temp_deletados = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.status == "temp_score"
        ).delete()
        db.commit()
        if temp_deletados:
            print(f"[SCORE_PROFUNDO] {temp_deletados} editais temporarios removidos")
        db.close()
    except Exception as e:
        print(f"[SCORE_PROFUNDO] Erro ao limpar temporarios: {e}")

    elapsed = time.time() - t0
    print(f"[SCORE_PROFUNDO] {len(editais)} editais em {elapsed:.1f}s")
    return editais


# =============================================================================
# Onda 2 - T8: Endpoint REST GET /api/editais/buscar
# =============================================================================

@app.route("/api/editais/buscar", methods=["GET"])
@require_auth
def buscar_editais_rest():
    """
    Endpoint REST para busca de editais — mesma lógica do chat.
    Usa _buscar_editais_multifonte() (PNCP API + scraper web + deduplicação).
    Query params:
      - termo (obrigatório): termo de busca
      - uf (opcional): filtrar por UF (ex: SP, RJ)
      - calcularScore (opcional, default true): calcular score aderência
      - incluirEncerrados (opcional, default false): incluir editais encerrados
      - limite / limit (opcional, default 20): máximo de resultados
      - diasBusca (opcional, default 90): janela de publicação em dias (0 = sem limite)
      - fonte (opcional): fonte específica (PNCP, ComprasNet, etc). Se omitido, busca em todas.
      - modalidade (opcional): filtrar por modalidade (ex: Pregão Eletrônico)
      - tipoProduto / tipo_produto (opcional): filtrar por tipo de produto inferido do objeto
      - origem (opcional): filtrar por origem do órgão inferida
    """
    user_id = get_current_user_id()
    termo = request.args.get("termo", "").strip()
    uf = request.args.get("uf", "").strip().upper() or None
    fonte = request.args.get("fonte", request.args.get("fontes", "")).strip() or None
    modalidade = request.args.get("modalidade", "").strip() or None
    tipo_produto = request.args.get("tipoProduto", request.args.get("tipo_produto", "")).strip() or None
    origem = request.args.get("origem", "").strip() or None
    # Score: tipoScore (nenhum/rapido/hibrido/profundo) com retrocompatibilidade
    tipo_score = request.args.get("tipoScore", request.args.get("tipo_score", "")).strip()
    limite_score_profundo = int(request.args.get("limiteScoreProfundo", request.args.get("limite_score_profundo", 10)))
    if limite_score_profundo == 0:
        limite_score_profundo = 9999  # "Todos"

    # Retrocompatibilidade: calcularScore=true sem tipoScore → "rapido"
    if not tipo_score:
        calcular_score_str = request.args.get("calcularScore", request.args.get("calcular_score", "true"))
        tipo_score = "rapido" if calcular_score_str.lower() == "true" else "nenhum"

    calcular_score = tipo_score != "nenhum"
    incluir_encerrados_str = request.args.get("incluirEncerrados", request.args.get("incluir_encerrados", "false"))
    incluir_encerrados = incluir_encerrados_str.lower() == "true"
    limite = int(request.args.get("limite", request.args.get("limit", 20)))
    dias_busca = int(request.args.get("diasBusca", request.args.get("dias_busca", 90)))
    if dias_busca != 0:
        dias_busca = max(7, min(730, dias_busca))

    if not termo:
        return jsonify({"success": False, "error": "Parâmetro 'termo' é obrigatório"}), 400

    try:
        # Busca multi-fonte: mesma lógica do chat (PNCP + scraper web + deduplicação)
        resultado_busca = _buscar_editais_multifonte(
            termo=termo,
            user_id=user_id,
            uf=uf,
            incluir_encerrados=incluir_encerrados,
            buscar_detalhes=True,
            dias_busca=dias_busca,
            fonte=fonte,
            modalidade=modalidade,
            tipo_produto=tipo_produto,
            origem=origem,
        )

        editais = resultado_busca.get("editais", [])

        # empresa_id necessário para o enriquecimento por termos CATMAT abaixo.
        # BUG (obs25): era definido só MAIS ABAIXO; aqui dava NameError engolido
        # pelo try/except, fazendo o enriquecimento CATMAT nunca rodar.
        empresa_id = get_current_empresa_id()

        # Buscas paralelas extras com termos CATMAT/semânticos dos produtos
        if tipo_score != "nenhum":
            try:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                import unicodedata as _ud

                def _norm_termo(txt):
                    if not txt:
                        return ""
                    txt = _ud.normalize('NFKD', txt).encode('ascii', 'ignore').decode('ascii')
                    return txt.lower().strip()

                # Normalizar termo de busca para matching
                termo_norm = _norm_termo(termo) if termo else ""
                termo_words = {w for w in termo_norm.split() if len(w) > 3}

                db_termos = get_db()
                produtos_user = db_termos.query(Produto).filter(Produto.empresa_id == empresa_id).all()
                termos_busca_extras = set()

                # Só extrair termos de produtos relevantes ao termo buscado
                for p in produtos_user:
                    p_nome_norm = _norm_termo(p.nome or "")
                    p_cat_norm = _norm_termo(p.categoria or "")
                    p_words = set(p_nome_norm.split()) | set(p_cat_norm.split())
                    overlap = termo_words & {w for w in p_words if len(w) > 3}
                    if not overlap:
                        continue
                    for desc in (p.catmat_descricoes or [])[:2]:
                        palavras = [w for w in desc.split() if len(w) > 3][:4]
                        if palavras:
                            termos_busca_extras.add(" ".join(palavras))
                    for t in (p.termos_busca or [])[:3]:
                        termos_busca_extras.add(t)
                db_termos.close()

                # Remover termos genéricos demais que trazem ruído
                TERMOS_GENERICOS_NORM = {
                    "material hospitalar", "material medico", "equipamento hospitalar",
                    "insumo hospitalar", "insumo laboratorial", "material laboratorio",
                    "reagente bioquimico", "equipamento medico", "material odontologico",
                    "servico geral", "material consumo", "material permanente",
                    "material medico hospitalar", "equipamento laboratorio",
                }
                termos_busca_extras = {
                    t for t in termos_busca_extras
                    if _norm_termo(t) not in TERMOS_GENERICOS_NORM and len(t.split()) >= 2
                }

                termos_extras = list(termos_busca_extras)[:5]
                if termos_extras:
                    print(f"[BUSCA] Buscas extras com {len(termos_extras)} termos CATMAT/semânticos: {termos_extras}")
                    with ThreadPoolExecutor(max_workers=3) as executor:
                        futures = {}
                        for t_extra in termos_extras:
                            f = executor.submit(
                                _buscar_editais_multifonte,
                                termo=t_extra, user_id=user_id, uf=uf,
                                incluir_encerrados=incluir_encerrados,
                                buscar_detalhes=True, dias_busca=dias_busca,
                                fonte=fonte,
                            )
                            futures[f] = t_extra

                        for f in as_completed(futures, timeout=30):
                            try:
                                res = f.result()
                                extras = res.get("editais", [])
                                if extras:
                                    # obs 25 validador V8: termos CATMAT/semânticos
                                    # AMPLIAM o leque de oportunidades. Não
                                    # re-filtrar pelo termo digitado — o score de
                                    # aderência (calculado adiante) classifica e o
                                    # usuário avalia. O sistema não deve excluir
                                    # oportunidades a priori.
                                    editais.extend(extras)
                                    print(f"[BUSCA] Termo extra '{futures[f]}': +{len(extras)} editais (sem re-filtro, score decide)")
                            except Exception:
                                pass

                    # Deduplicar por número+órgão e fallback órgão+valor
                    seen = set()
                    seen2 = set()
                    dedup = []
                    for e in editais:
                        chave = f"{e.get('numero', '')}-{e.get('orgao', '')}"
                        orgao = (e.get('orgao') or '').strip().lower()
                        valor = e.get('valor_estimado') or e.get('valor_referencia') or 0
                        chave2 = f"{orgao}|{valor}" if orgao and valor else ""
                        if chave in seen:
                            continue
                        if chave2 and chave2 in seen2:
                            continue
                        seen.add(chave)
                        if chave2:
                            seen2.add(chave2)
                        dedup.append(e)
                    editais = dedup
                    print(f"[BUSCA] Total após dedup: {len(editais)} editais")
            except Exception as e:
                print(f"[BUSCA] Erro buscas extras: {e}")

        # Calcular score ANTES de aplicar limite (para pegar os melhores)
        empresa_id = get_current_empresa_id()
        if tipo_score == "rapido" and editais:
            resultado_score = tool_calcular_score_aderencia(editais=editais, user_id=user_id, empresa_id=empresa_id)
            if resultado_score.get("success"):
                editais = resultado_score.get("editais_com_score", editais)

        elif tipo_score == "hibrido" and editais:
            # Passo 1: Score rápido em TODOS
            resultado_score = tool_calcular_score_aderencia(editais=editais, user_id=user_id, empresa_id=empresa_id)
            if resultado_score.get("success"):
                editais = resultado_score.get("editais_com_score", editais)
            # Passo 2: Ordenar por score desc, pegar os N melhores para profundo
            editais.sort(key=lambda x: x.get("score_tecnico", 0), reverse=True)
            top_n = editais[:limite_score_profundo]
            rest = editais[limite_score_profundo:]
            # Passo 3: Score profundo nos N melhores
            top_n = _calcular_score_profundo(top_n, user_id, empresa_id)
            # Retornar TODOS: top N enriquecidos + restantes com score rápido
            editais = top_n + rest

        elif tipo_score == "profundo" and editais:
            # Score profundo direto nos N primeiros (sem triagem rápida)
            target = editais[:limite_score_profundo]
            rest = editais[limite_score_profundo:]
            target = _calcular_score_profundo(target, user_id, empresa_id)
            editais = target + rest

        # Ordenar: se tem score, por score desc; senão abertos primeiro por data
        from datetime import datetime as _dt
        def _sort_key_rest(e):
            encerrado = e.get("encerrado", False)
            score = e.get("score_tecnico", -1)
            d = e.get("data_encerramento") or e.get("data_abertura") or ""
            dt = _dt(2099, 12, 31)
            for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = _dt.strptime(d[:19], fmt)
                    break
                except (ValueError, TypeError):
                    continue
            if calcular_score:
                # Score desc (negativo para reverse), depois abertos primeiro, depois data
                return (-score, 1 if encerrado else 0, dt)
            return (1 if encerrado else 0, dt)
        editais.sort(key=_sort_key_rest)

        # Aplicar limite DEPOIS da ordenação
        editais = editais[:limite]

        # Normalizar campos de retorno para o frontend
        editais_normalizados = []
        for i, e in enumerate(editais):
            # Gerar ID único: usar ID do banco se existir, senão criar hash do número+órgão
            edital_id = e.get("id")
            if not edital_id:
                import hashlib
                chave = f"{e.get('numero', '')}-{e.get('orgao', '')}-{i}"
                edital_id = hashlib.md5(chave.encode()).hexdigest()
            _objeto = e.get("objeto") or e.get("descricao") or ""
            _orgao = e.get("orgao") or ""
            _orgao_tipo = e.get("orgao_tipo") or "municipal"
            editais_normalizados.append({
                "id": edital_id,
                "numero": e.get("numero"),
                "orgao": _orgao,
                "orgao_tipo": _orgao_tipo,
                "objeto": _objeto,
                "modalidade": e.get("modalidade"),
                "valor_estimado": e.get("valor_referencia") or e.get("valor_estimado"),
                "data_publicacao": e.get("data_publicacao"),
                "data_abertura": e.get("data_abertura"),
                "data_encerramento": e.get("data_encerramento"),
                "uf": e.get("uf") or uf,
                "cidade": e.get("cidade"),
                "url": e.get("url") or e.get("link"),
                "fonte": e.get("fonte"),
                "fonte_tipo": e.get("fonte_tipo"),
                "score_tecnico": e.get("score_tecnico"),
                "recomendacao": e.get("recomendacao"),
                "justificativa": e.get("justificativa"),
                "produtos_aderentes": e.get("produtos_aderentes", []),
                "cnpj_orgao": e.get("cnpj_orgao"),
                "ano_compra": e.get("ano_compra"),
                "seq_compra": e.get("seq_compra"),
                "total_itens": e.get("total_itens", 0),
                "itens": e.get("itens", []),
                "dados_completos": e.get("dados_completos", False),
                "encerrado": e.get("encerrado", False),
                "pdf_url": e.get("pdf_url"),
                "tipo_produto_inferido": inferir_tipo_produto(_objeto),
                "origem_inferida": inferir_origem_orgao(_orgao, _orgao_tipo),
                "score_profundo": e.get("score_profundo"),
            })

        return jsonify({
            "success": True,
            "editais": editais_normalizados,
            "total": len(editais_normalizados),
            "termo": termo,
            "uf": uf,
            "fontes_usadas": resultado_busca.get("fontes_consultadas", []),
            "erros_fontes": resultado_busca.get("erros"),
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# Onda 2 - T9: Endpoint REST GET /api/editais/salvos
# =============================================================================

@app.route("/api/editais/salvos", methods=["GET"])
@require_auth
def listar_editais_salvos():
    """
    Lista editais salvos do usuário com scores e estratégias.
    Query params: status, uf, categoria, com_score (bool), com_estrategia (bool)
    """
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    status = request.args.get("status")
    uf = request.args.get("uf")
    categoria = request.args.get("categoria")
    com_score = request.args.get("com_score", "false").lower() == "true"
    com_estrategia = request.args.get("com_estrategia", "false").lower() == "true"
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))

    db = get_db()
    try:
        query = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.status != "temp_score",  # Excluir editais temporários criados pelo score profundo
        )

        if status:
            query = query.filter(Edital.status == status)
        if uf:
            query = query.filter(Edital.uf == uf.upper())
        if categoria:
            query = query.filter(Edital.categoria == categoria)

        total = query.count()
        editais = query.order_by(Edital.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()

        resultado = []
        for edital in editais:
            edital_dict = edital.to_dict()

            # Incluir melhor score/análise se solicitado
            if com_score:
                melhor_analise = db.query(Analise).filter(
                    Analise.edital_id == edital.id,
                    Analise.empresa_id == empresa_id
                ).order_by(Analise.score_final.desc()).first()
                if melhor_analise:
                    edital_dict["score_tecnico"] = float(melhor_analise.score_tecnico) if melhor_analise.score_tecnico else None
                    edital_dict["score_final"] = float(melhor_analise.score_final) if melhor_analise.score_final else None
                    edital_dict["score_geral"] = float(melhor_analise.score_final) if melhor_analise.score_final else None
                    edital_dict["analise_id"] = melhor_analise.id
                    # Parsear recomendacao: pode ser JSON (novo) ou texto puro (antigo)
                    scores_parsed = False
                    try:
                        rec_data = json.loads(melhor_analise.recomendacao) if melhor_analise.recomendacao else {}
                        if isinstance(rec_data, dict) and "scores" in rec_data:
                            edital_dict["scores"] = rec_data["scores"]
                            edital_dict["decisao_ia"] = rec_data.get("decisao")
                            edital_dict["justificativa_ia"] = rec_data.get("justificativa")
                            edital_dict["pontos_positivos"] = rec_data.get("pontos_positivos", [])
                            edital_dict["pontos_atencao"] = rec_data.get("pontos_atencao", [])
                            scores_parsed = True
                    except (json.JSONDecodeError, TypeError):
                        pass

                    if not scores_parsed:
                        # Recomendacao é texto puro (score profundo antigo) — reconstruir scores dos campos
                        edital_dict["scores"] = {
                            "tecnico": float(melhor_analise.score_tecnico) if melhor_analise.score_tecnico else 0,
                            "documental": 0,
                            "complexidade": 0,
                            "juridico": 0,
                            "logistico": 0,
                            "comercial": float(melhor_analise.score_comercial) if melhor_analise.score_comercial else 0,
                        }
                        rec_text = melhor_analise.recomendacao or ""
                        if rec_text.startswith("GO"):
                            edital_dict["decisao_ia"] = "GO"
                        elif rec_text.startswith("NO-GO"):
                            edital_dict["decisao_ia"] = "NO-GO"
                        else:
                            edital_dict["decisao_ia"] = "AVALIAR"
                        edital_dict["justificativa_ia"] = rec_text.split(": ", 1)[1] if ": " in rec_text else rec_text
                        edital_dict["recomendacao"] = rec_text

            # Incluir estratégia/decisão go-nogo se solicitado
            if com_estrategia:
                estrategia = db.query(EstrategiaEdital).filter(
                    EstrategiaEdital.edital_id == edital.id,
                    EstrategiaEdital.empresa_id == empresa_id
                ).first()
                if estrategia:
                    edital_dict["decisao"] = estrategia.decisao
                    edital_dict["prioridade"] = estrategia.prioridade
                    edital_dict["margem_desejada"] = float(estrategia.margem_desejada) if estrategia.margem_desejada else None
                    edital_dict["justificativa_estrategia"] = estrategia.justificativa
                    edital_dict["estrategia_id"] = estrategia.id

            resultado.append(edital_dict)

        return jsonify({
            "success": True,
            "editais": resultado,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": (total + per_page - 1) // per_page
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Onda 2 - T10: Endpoint POST /api/editais/<id>/scores-validacao
# =============================================================================

@app.route("/api/editais/<edital_id>/scores-validacao", methods=["POST"])
@require_auth
def calcular_scores_validacao_rest(edital_id):
    """
    Calcula 6 dimensões de score de validação para um edital.
    Body (opcional): {"produto_id": "<uuid>"}
    """
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.json or {}
    produto_id = data.get("produto_id")

    try:
        resultado = tool_calcular_scores_validacao(
            edital_id=edital_id,
            user_id=user_id,
            empresa_id=empresa_id,
            produto_id=produto_id
        )
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# Endpoint para calcular score profundo sob demanda (edital não salvo)
@app.route("/api/editais/salvar-scores-captacao", methods=["POST"])
@require_auth
def salvar_scores_captacao():
    """Salva scores calculados na Captação para que a Validação não precise recalcular."""
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.get_json()
    edital_id = data.get("edital_id")
    if not edital_id:
        return jsonify({"error": "edital_id obrigatório"}), 400

    db = get_db()
    try:
        edital = db.query(Edital).filter(Edital.id == edital_id, Edital.empresa_id == empresa_id).first()
        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404

        empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()

        # Buscar produto correspondente (necessário para Analise — produto_id é NOT NULL)
        from models import Produto
        produto = db.query(Produto).filter(Produto.empresa_id == empresa_id).first()
        if not produto:
            return jsonify({"error": "Nenhum produto cadastrado"}), 400
        produto_id = produto.id

        # Verificar se já existe análise para este edital
        analise_existente = db.query(Analise).filter(
            Analise.edital_id == edital_id,
            Analise.empresa_id == empresa_id
        ).first()

        score_tecnico = data.get("score_tecnico", 0)
        score_comercial = data.get("score_comercial", 0)
        score_final = data.get("score_final", 0)
        decisao = data.get("decisao", "AVALIAR")
        justificativa = data.get("justificativa", "")

        recomendacao_text = json.dumps({
            "decisao": decisao,
            "justificativa": justificativa,
            "scores": {
                "tecnico": score_tecnico,
                "documental": data.get("score_documental", 0),
                "complexidade": data.get("score_complexidade", 0),
                "juridico": data.get("score_juridico", 0),
                "logistico": data.get("score_logistico", 0),
                "comercial": score_comercial,
            },
            "pontos_positivos": data.get("pontos_positivos", []),
            "pontos_atencao": data.get("pontos_atencao", []),
        }, ensure_ascii=False)

        if analise_existente:
            analise_existente.score_tecnico = score_tecnico
            analise_existente.score_comercial = score_comercial
            analise_existente.score_final = score_final
            analise_existente.recomendacao = recomendacao_text
        else:
            nova_analise = Analise(
                id=str(uuid.uuid4()),
                edital_id=edital_id,
                produto_id=produto_id,
                user_id=user_id,
                empresa_id=empresa_id,
                score_tecnico=score_tecnico,
                score_comercial=score_comercial,
                score_final=score_final,
                recomendacao=recomendacao_text,
                created_at=datetime.now(),
            )
            db.add(nova_analise)

        db.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/editais/score-profundo-sob-demanda", methods=["POST"])
@require_auth
def score_profundo_sob_demanda():
    """
    Recebe dados de um edital não salvo, salva temporariamente,
    calcula score profundo e retorna resultado.
    """
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.json or {}

    if not data.get("objeto"):
        return jsonify({"success": False, "error": "Campo 'objeto' obrigatório"}), 400

    try:

        # Salvar edital temporário
        edital_id = _salvar_edital_temp_para_score(data, user_id, empresa_id)
        if not edital_id:
            return jsonify({"success": False, "error": "Erro ao salvar edital temporário"}), 500

        # Calcular score profundo
        resultado = tool_calcular_scores_validacao(
            edital_id=edital_id,
            user_id=user_id,
            produto_id=data.get("produto_id")
        )

        # Retornar o edital_id para que o frontend possa usá-lo depois
        if resultado.get("success"):
            resultado["edital_id_temp"] = edital_id

        return jsonify(resultado)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# Onda 2 - T11: Endpoint PUT /api/propostas/<id>/status
# =============================================================================

@app.route("/api/propostas/<proposta_id>/status", methods=["PUT"])
@require_auth
def atualizar_status_proposta(proposta_id):
    """
    Atualiza o status de uma proposta seguindo o workflow:
    rascunho -> revisao -> aprovada -> enviada -> aceita/rejeitada
    """
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.json or {}
    novo_status = data.get("status", "").strip()

    # Status do modelo: rascunho, revisao, aprovada, enviada
    TRANSICOES_VALIDAS = {
        "rascunho": ["revisao"],
        "revisao": ["rascunho", "aprovada"],
        "aprovada": ["revisao", "enviada"],
        "enviada": ["aprovada", "rascunho"]
    }

    STATUS_VALIDOS = list(TRANSICOES_VALIDAS.keys())

    if not novo_status:
        return jsonify({"success": False, "error": "Campo 'status' é obrigatório"}), 400

    if novo_status not in STATUS_VALIDOS:
        return jsonify({
            "success": False,
            "error": f"Status inválido. Válidos: {', '.join(STATUS_VALIDOS)}"
        }), 400

    db = get_db()
    try:
        proposta = db.query(Proposta).filter(
            Proposta.id == proposta_id,
            Proposta.empresa_id == empresa_id
        ).first()

        if not proposta:
            return jsonify({"success": False, "error": "Proposta não encontrada"}), 404

        status_atual = proposta.status
        transicoes = TRANSICOES_VALIDAS.get(status_atual, [])

        if novo_status not in transicoes:
            return jsonify({
                "success": False,
                "error": f"Transição inválida: '{status_atual}' -> '{novo_status}'. Permitidas: {transicoes}"
            }), 400

        proposta.status = novo_status
        proposta.updated_at = datetime.now()
        db.commit()

        return jsonify({
            "success": True,
            "proposta_id": proposta_id,
            "status_anterior": status_atual,
            "status_atual": novo_status,
            "proposta": proposta.to_dict()
        })

    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Onda 2 - T12: Endpoint export PDF/DOCX propostas
# =============================================================================

@app.route("/api/propostas/<proposta_id>/export", methods=["GET"])
@require_auth
def exportar_proposta(proposta_id):
    """
    Exporta proposta em PDF ou DOCX.
    Query param: formato (pdf | docx), padrão = pdf
    """
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    formato = request.args.get("formato", "pdf").lower()

    if formato not in ("pdf", "docx"):
        return jsonify({"success": False, "error": "Formato inválido. Use 'pdf' ou 'docx'"}), 400

    db = get_db()
    try:
        proposta = db.query(Proposta).filter(
            Proposta.id == proposta_id,
            Proposta.empresa_id == empresa_id
        ).first()

        if not proposta:
            return jsonify({"success": False, "error": "Proposta não encontrada"}), 404

        edital = db.query(Edital).filter(Edital.id == proposta.edital_id).first()
        produto = db.query(Produto).filter(Produto.id == proposta.produto_id).first()

        # Montar conteúdo do documento
        titulo = f"Proposta Técnica - {edital.numero if edital else proposta_id}"
        conteudo_linhas = [
            f"PROPOSTA TÉCNICA E COMERCIAL",
            f"",
            f"Edital: {edital.numero if edital else 'N/A'}",
            f"Órgão: {edital.orgao if edital else 'N/A'}",
            f"Objeto: {edital.objeto[:300] if edital and edital.objeto else 'N/A'}",
            f"",
            f"PRODUTO OFERTADO",
            f"Produto: {produto.nome if produto else 'N/A'}",
            f"Fabricante: {produto.fabricante if produto else 'N/A'}",
            f"Modelo: {produto.modelo if produto else 'N/A'}",
            f"",
            f"PROPOSTA COMERCIAL",
            f"Preço Unitário: R$ {proposta.preco_unitario:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.') if proposta.preco_unitario else "Preço Unitário: N/A",
            f"Quantidade: {proposta.quantidade or 1}",
            f"Preço Total: R$ {proposta.preco_total:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.') if proposta.preco_total else "Preço Total: N/A",
            f"",
            f"DESCRIÇÃO TÉCNICA",
            proposta.texto_tecnico or "Sem descrição técnica.",
            f"",
            f"Status: {proposta.status}",
            f"Data: {proposta.created_at.strftime('%d/%m/%Y') if proposta.created_at else 'N/A'}",
        ]
        conteudo_texto = "\n".join(conteudo_linhas)

        import tempfile, os as _os

        if formato == "docx":
            try:
                from docx import Document
                doc = Document()
                doc.add_heading(titulo, 0)
                for linha in conteudo_linhas:
                    if linha:
                        doc.add_paragraph(linha)
                    else:
                        doc.add_paragraph("")
                tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
                doc.save(tmp.name)
                tmp.close()
                return send_file(
                    tmp.name,
                    mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    as_attachment=True,
                    download_name=f"proposta_{proposta_id[:8]}.docx"
                )
            except ImportError:
                return jsonify({"success": False, "error": "python-docx não instalado. Execute: pip install python-docx"}), 500

        else:  # pdf
            try:
                from weasyprint import HTML
                html_content = f"""
                <html><head><meta charset="utf-8">
                <style>
                  body {{ font-family: Arial, sans-serif; margin: 40px; font-size: 12px; }}
                  h1 {{ color: #1e3a5f; border-bottom: 2px solid #1e3a5f; }}
                  h2 {{ color: #1e3a5f; margin-top: 20px; }}
                  .label {{ font-weight: bold; }}
                  table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
                  td {{ padding: 4px 8px; border: 1px solid #ddd; }}
                </style>
                </head><body>
                <h1>{titulo}</h1>
                <pre style="white-space: pre-wrap;">{conteudo_texto}</pre>
                </body></html>
                """
                tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                HTML(string=html_content).write_pdf(tmp.name)
                tmp.close()
                return send_file(
                    tmp.name,
                    mimetype="application/pdf",
                    as_attachment=True,
                    download_name=f"proposta_{proposta_id[:8]}.pdf"
                )
            except ImportError:
                # Fallback: gerar PDF simples com reportlab
                try:
                    from reportlab.lib.pagesizes import A4
                    from reportlab.pdfgen import canvas
                    from reportlab.lib.units import cm

                    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
                    c = canvas.Canvas(tmp.name, pagesize=A4)
                    largura, altura = A4
                    y = altura - 2 * cm

                    c.setFont("Helvetica-Bold", 16)
                    c.drawString(2 * cm, y, titulo)
                    y -= 1 * cm

                    c.setFont("Helvetica", 10)
                    for linha in conteudo_linhas:
                        if y < 2 * cm:
                            c.showPage()
                            y = altura - 2 * cm
                            c.setFont("Helvetica", 10)
                        c.drawString(2 * cm, y, linha[:100])
                        y -= 0.5 * cm

                    c.save()
                    tmp.close()
                    return send_file(
                        tmp.name,
                        mimetype="application/pdf",
                        as_attachment=True,
                        download_name=f"proposta_{proposta_id[:8]}.pdf"
                    )
                except ImportError:
                    return jsonify({"success": False, "error": "Nenhuma lib de PDF disponível. Instale weasyprint ou reportlab"}), 500

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Documentos Necessários — lista de tipos para dropdown
# =============================================================================

@app.route("/api/documentos-necessarios", methods=["GET"])
@require_auth
def listar_documentos_necessarios():
    """Retorna todos os tipos de documentos necessários (ativos), agrupados por categoria."""
    from models import DocumentoNecessario, CategoriaDocumento
    db = get_db()
    try:
        docs = db.query(DocumentoNecessario).outerjoin(CategoriaDocumento).filter(
            DocumentoNecessario.ativo == True
        ).order_by(CategoriaDocumento.ordem, DocumentoNecessario.ordem).all()
        return jsonify([d.to_dict() for d in docs])
    finally:
        db.close()


# =============================================================================
# B1: Upload real de arquivo na EmpresaPage (persistir no disco)
# =============================================================================

@app.route("/api/empresa-documentos/upload", methods=["POST"])
@require_auth
def upload_empresa_documento():
    """
    Upload de documento da empresa (contrato social, atestados, etc).
    Salva arquivo no disco e cria/atualiza registro EmpresaDocumento.

    Form data:
    - file: arquivo (PDF, DOCX, etc.)
    - empresa_id: ID da empresa
    - tipo: tipo do documento (contrato_social, atestado_capacidade, etc.)
    - data_emissao: (opcional) data de emissão
    - data_vencimento: (opcional) data de vencimento
    """
    from models import Empresa, EmpresaDocumento, DocumentoNecessario
    user_id = get_current_user_id()

    if 'file' not in request.files:
        return jsonify({"error": "Arquivo não enviado"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Nenhum arquivo selecionado"}), 400

    empresa_id = request.form.get('empresa_id')
    documento_necessario_id = request.form.get('documento_necessario_id')

    # Tipos validos no ENUM da tabela empresa_documentos.tipo no MySQL.
    _tipos_validos = {
        'contrato_social', 'atestado_capacidade', 'balanco', 'alvara',
        'registro_conselho', 'procuracao', 'certidao_negativa',
        'habilitacao_fiscal', 'habilitacao_economica', 'qualificacao_tecnica',
        'afe', 'cbpad', 'cbpp', 'bombeiros', 'outro'
    }
    # tipo_chave em documentos_necessarios pode usar nomes mais especificos
    # (ex: "fgts", "cnd_federal") que nao existem no enum. Mapa de
    # consolidacao para o tipo enum equivalente.
    _tipo_chave_map = {
        'fgts': 'habilitacao_fiscal',
        'cnd_federal': 'habilitacao_fiscal',
        'cnd_estadual': 'habilitacao_fiscal',
        'cnd_municipal': 'habilitacao_fiscal',
        'sicaf': 'habilitacao_fiscal',
        'estatuto_social': 'contrato_social',
    }

    tipo = 'outro'
    doc_nec = None
    if documento_necessario_id:
        # Resolver tipo a partir do DocumentoNecessario
        db_tmp = get_db()
        try:
            doc_nec = db_tmp.query(DocumentoNecessario).filter(
                DocumentoNecessario.id == documento_necessario_id
            ).first()
            if doc_nec:
                chave = doc_nec.tipo_chave or ''
                if chave in _tipos_validos:
                    tipo = chave
                elif chave in _tipo_chave_map:
                    tipo = _tipo_chave_map[chave]
        finally:
            db_tmp.close()

    if tipo == 'outro' and not documento_necessario_id:
        # Fallback: tentar resolver pelo campo tipo legado
        tipo_raw = request.form.get('tipo', 'outro')
        tipo_norm = tipo_raw.lower().replace(' ', '_').replace('de_', '')
        _tipo_map = {
            'contrato_social': 'contrato_social', 'procuracao': 'procuracao',
            'certidao_negativa': 'certidao_negativa', 'habilitacao_fiscal': 'habilitacao_fiscal',
            'habilitacao_economica': 'habilitacao_economica', 'balanco_patrimonial': 'balanco',
            'qualificacao_tecnica': 'qualificacao_tecnica', 'atestado_capacidade': 'atestado_capacidade',
            'afe': 'afe', 'cbpad': 'cbpad', 'cbpp': 'cbpp',
            'corpo_bombeiros': 'bombeiros', 'bombeiros': 'bombeiros',
            'alvara': 'alvara', 'registro_conselho': 'registro_conselho',
            'outro': 'outro',
        }
        tipo = _tipo_map.get(tipo_norm, tipo_norm)
        if tipo not in _tipos_validos:
            tipo = 'outro'

    if not empresa_id:
        return jsonify({"error": "empresa_id é obrigatório"}), 400

    db = get_db()
    try:
        empresa = db.query(Empresa).filter(
            Empresa.id == empresa_id
        ).first()
        if not empresa:
            return jsonify({"error": "Empresa não encontrada"}), 404

        # Criar diretório para a empresa
        upload_dir = os.path.join(UPLOAD_FOLDER, 'empresa', empresa_id, tipo)
        os.makedirs(upload_dir, exist_ok=True)

        # Salvar arquivo com nome seguro
        from werkzeug.utils import secure_filename
        safe_name = secure_filename(file.filename) or f"doc_{uuid.uuid4().hex[:8]}.pdf"
        filepath = os.path.join(upload_dir, f"{uuid.uuid4().hex[:8]}_{safe_name}")
        file.save(filepath)

        # Criar registro EmpresaDocumento
        doc = EmpresaDocumento()
        doc.id = str(uuid.uuid4())
        doc.empresa_id = empresa_id
        doc.tipo = tipo
        doc.nome_arquivo = file.filename
        doc.path_arquivo = filepath
        if documento_necessario_id:
            doc.documento_necessario_id = documento_necessario_id

        # Datas opcionais
        data_emissao = request.form.get('data_emissao')
        data_vencimento = request.form.get('data_vencimento')
        if data_emissao:
            from datetime import date as date_type
            try:
                doc.data_emissao = date_type.fromisoformat(data_emissao)
            except ValueError:
                pass
        if data_vencimento:
            from datetime import date as date_type
            try:
                doc.data_vencimento = date_type.fromisoformat(data_vencimento)
            except ValueError:
                pass

        db.add(doc)
        db.commit()
        db.refresh(doc)

        return jsonify({
            "success": True,
            "message": f"Documento '{file.filename}' enviado com sucesso",
            "documento": doc.to_dict(),
            "path": filepath
        }), 201

    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        print(f"[upload_empresa_documento] ERRO: {e}", flush=True)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# F01-01/F01-06/F02-03/F03-02: Upload em massa de documentos com classificação por IA
@app.route("/api/upload-lote-ia", methods=["POST"])
@require_auth
def upload_lote_ia():
    """Recebe N arquivos PDF/DOCX, IA classifica cada um por TIPO e extrai metadados.

    Suporta 3 contextos:
      - "cadastro_empresa" → extrai dados da empresa (CNPJ, Razao Social, etc) do contrato social
      - "documentos" → classifica cada arquivo como contrato/alvara/CND/etc. e cria EmpresaDocumento
      - "portfolio" → classifica como catalogo/manual/registro_anvisa/etc. e prepara cadastro de produto

    Form data:
      - file_0, file_1, ... file_N: arquivos
      - contexto: "cadastro_empresa" | "documentos" | "portfolio"
      - empresa_id: ID da empresa (obrigatorio para "documentos" e "portfolio")

    Retorna:
      {
        "ok": True,
        "resultados": [
          {"filename": "contrato.pdf", "classificacao": "contrato_social",
           "dados_extraidos": {...}, "criado_id": "<id>", "erro": null},
          ...
        ],
        "total": 5, "sucessos": 4, "erros": 1
      }

    User precisa REVISAR o resultado e clicar "Aceito" antes de persistir definitivamente.
    """
    from models import Empresa, EmpresaDocumento
    from werkzeug.utils import secure_filename
    import io

    user_id = get_current_user_id()
    contexto = (request.form.get("contexto") or "").strip()
    empresa_id = request.form.get("empresa_id")

    contextos_validos = {"cadastro_empresa", "documentos", "portfolio"}
    if contexto not in contextos_validos:
        return jsonify({"error": f"contexto invalido. Use um de: {sorted(contextos_validos)}"}), 400

    if contexto in ("documentos", "portfolio") and not empresa_id:
        return jsonify({"error": f"empresa_id obrigatorio para contexto '{contexto}'"}), 400

    arquivos = []
    for key in request.files:
        if key.startswith("file"):
            f = request.files[key]
            if f.filename:
                arquivos.append(f)

    if not arquivos:
        return jsonify({"error": "Nenhum arquivo enviado (use chaves file_0, file_1, ...)"}), 400

    if len(arquivos) > 50:
        return jsonify({"error": f"Limite de 50 arquivos por upload. Recebido: {len(arquivos)}"}), 400

    # Diretorio de upload
    upload_dir = os.path.join(UPLOAD_FOLDER, 'lote_ia', empresa_id or 'sem_empresa', uuid.uuid4().hex[:8])
    os.makedirs(upload_dir, exist_ok=True)

    resultados = []
    sucessos = 0
    erros = 0

    for f in arquivos:
        nome_original = f.filename or "sem_nome"
        item = {
            "filename": nome_original,
            "classificacao": None,
            "dados_extraidos": None,
            "criado_id": None,
            "filepath": None,
            "erro": None,
        }
        try:
            # F04-07: validar magic bytes (so para PDFs)
            f.stream.seek(0)
            primeiros = f.stream.read(4)
            f.stream.seek(0)
            ext = os.path.splitext(nome_original)[1].lower()
            if ext == ".pdf" and primeiros != b"%PDF":
                item["erro"] = "Arquivo nao eh PDF valido (magic bytes invalidos)"
                erros += 1
                resultados.append(item)
                continue

            safe_name = secure_filename(nome_original) or f"doc_{uuid.uuid4().hex[:8]}.pdf"
            filepath = os.path.join(upload_dir, f"{uuid.uuid4().hex[:8]}_{safe_name}")
            f.save(filepath)
            item["filepath"] = filepath

            # Extrair texto se for PDF
            texto = ""
            if ext == ".pdf":
                try:
                    import fitz as _fitz
                    doc = _fitz.open(filepath)
                    paginas_texto = []
                    for p in doc:
                        paginas_texto.append(p.get_text())
                    texto = "\n".join(paginas_texto)
                    doc.close()
                except Exception as e_pdf:
                    print(f"[upload_lote_ia] erro PDF {nome_original}: {e_pdf}")

            if not texto or len(texto) < 100:
                item["erro"] = "Nao foi possivel extrair texto do arquivo"
                erros += 1
                resultados.append(item)
                continue

            # Chamar IA pra classificar e extrair metadados
            from llm import call_deepseek
            if contexto == "cadastro_empresa":
                prompt = f"""Voce e um assistente que extrai dados cadastrais de empresa de um documento.
Documento ({nome_original}):
\"\"\"{texto[:8000]}\"\"\"

Retorne APENAS um JSON com os campos:
- razao_social: string ou null
- nome_fantasia: string ou null
- cnpj: string ou null (formato 00.000.000/0000-00)
- inscricao_estadual: string ou null
- inscricao_municipal: string ou null
- cep: string ou null
- endereco: string ou null
- endereco_numero: string ou null
- bairro: string ou null
- cidade: string ou null
- uf: string ou null (2 letras)
- telefone: string ou null
- email: string ou null
- regime_tributario: 'simples' | 'lucro_presumido' | 'lucro_real' | null
- porte: 'me' | 'epp' | 'medio' | 'grande' | null

Responda APENAS o JSON, sem texto antes nem depois."""
            elif contexto == "documentos":
                prompt = f"""Voce classifica documentos de empresa para cadastro em sistema de licitacoes.
Documento ({nome_original}):
\"\"\"{texto[:6000]}\"\"\"

Retorne APENAS um JSON com:
- tipo: um de 'contrato_social', 'atestado_capacidade', 'balanco', 'alvara', 'registro_conselho',
       'procuracao', 'certidao_negativa', 'habilitacao_fiscal', 'qualificacao_tecnica',
       'afe', 'cbpad', 'cbpp', 'bombeiros', 'outro'
- numero: string ou null (numero do documento se houver)
- data_emissao: string YYYY-MM-DD ou null
- data_vencimento: string YYYY-MM-DD ou null
- orgao_emissor: string ou null
- resumo: string curta (1 frase) descrevendo o que eh

Responda APENAS o JSON."""
            else:  # portfolio
                prompt = f"""Voce classifica documentos de produto/portfolio para empresa de licitacoes.
Documento ({nome_original}):
\"\"\"{texto[:6000]}\"\"\"

Retorne APENAS um JSON com:
- tipo: um de 'catalogo', 'manual', 'registro_anvisa', 'spec_tecnica', 'bula', 'certificado_qualidade', 'outro'
- nome_produto: string ou null
- fabricante: string ou null
- modelo: string ou null
- ncm: string ou null (formato 0000.00.00 se identificavel)
- subclasse_sugerida: string ou null (ex: "Monitor Multiparametro", "Reagente Bioquimico")
- area_sugerida: string ou null (ex: "Equipamentos Medico-Hospitalares")
- resumo: string curta

Responda APENAS o JSON."""

            try:
                resposta = call_deepseek([{"role": "user", "content": prompt}], max_tokens=1500)
                resposta = (resposta or "").strip()
                # Remover markdown code fence se houver
                if resposta.startswith("```"):
                    resposta = resposta.split("```")[1]
                    if resposta.startswith("json"):
                        resposta = resposta[4:]
                import json as _json
                dados = _json.loads(resposta)
                item["dados_extraidos"] = dados

                if contexto == "documentos":
                    item["classificacao"] = dados.get("tipo", "outro")
                elif contexto == "portfolio":
                    item["classificacao"] = dados.get("tipo", "outro")
                elif contexto == "cadastro_empresa":
                    item["classificacao"] = "dados_empresa"

                sucessos += 1
            except Exception as e_ia:
                item["erro"] = f"Falha na IA: {str(e_ia)[:200]}"
                erros += 1
        except Exception as e_geral:
            item["erro"] = f"Erro geral: {str(e_geral)[:200]}"
            erros += 1

        resultados.append(item)

    return jsonify({
        "ok": True,
        "contexto": contexto,
        "empresa_id": empresa_id,
        "total": len(arquivos),
        "sucessos": sucessos,
        "erros": erros,
        "resultados": resultados,
        "instrucoes": "Resultados estao em modo RASCUNHO. Revise cada item e chame /api/upload-lote-ia/confirmar com a lista de itens aprovados para persistir definitivamente.",
    })


@app.route("/api/upload-lote-ia/confirmar", methods=["POST"])
@require_auth
def upload_lote_ia_confirmar():
    """Persiste o resultado de upload-lote-ia depois da revisao do user.

    Body JSON: {
      "contexto": "documentos" | "portfolio" | ...,
      "empresa_id": "<id>",
      "itens_aprovados": [
        {"filepath": "/...", "classificacao": "alvara", "dados_extraidos": {...}, "filename": "..."},
        ...
      ]
    }

    Tambem registra um aceite de IA (F03-03) para cada item.
    """
    from models import EmpresaDocumento, AuditoriaAceiteIA
    from datetime import datetime as _dt

    user_id = get_current_user_id()
    data = request.get_json(silent=True) or {}
    contexto = data.get("contexto", "")
    empresa_id = data.get("empresa_id")
    itens = data.get("itens_aprovados", [])

    if not itens:
        return jsonify({"error": "Nenhum item aprovado"}), 400

    db = get_db()
    persistidos = []
    try:
        for item in itens:
            try:
                if contexto == "documentos":
                    doc = EmpresaDocumento(
                        id=str(uuid.uuid4()),
                        empresa_id=empresa_id,
                        tipo=item.get("classificacao", "outro"),
                        nome=item.get("filename", "Documento"),
                        path_arquivo=item.get("filepath"),
                    )
                    extraidos = item.get("dados_extraidos") or {}
                    if extraidos.get("data_vencimento"):
                        try:
                            doc.data_vencimento = _dt.strptime(extraidos["data_vencimento"], "%Y-%m-%d").date()
                        except Exception:
                            pass
                    if extraidos.get("data_emissao"):
                        try:
                            doc.data_emissao = _dt.strptime(extraidos["data_emissao"], "%Y-%m-%d").date()
                        except Exception:
                            pass
                    if extraidos.get("numero"):
                        doc.numero = extraidos["numero"]
                    if extraidos.get("orgao_emissor"):
                        doc.orgao_emissor = extraidos["orgao_emissor"]
                    db.add(doc)
                    db.flush()
                    persistidos.append({"id": doc.id, "tipo": "documento", "filename": item.get("filename")})

                    # F03-03: registrar aceite de IA
                    log = AuditoriaAceiteIA(
                        id=str(uuid.uuid4()),
                        user_id=user_id,
                        empresa_id=empresa_id,
                        contexto="upload_lote_documento",
                        recurso_id=doc.id,
                        dados_extraidos_ia=extraidos,
                        dados_aceitos_user=extraidos,
                    )
                    db.add(log)
                # contexto cadastro_empresa e portfolio sao implementados em fluxos especificos
                # (revisao do user antes de aplicar — ver frontend).
            except Exception as e_item:
                print(f"[upload_lote_ia_confirmar] erro item {item.get('filename')}: {e_item}")

        db.commit()
        return jsonify({
            "ok": True,
            "persistidos": len(persistidos),
            "itens": persistidos,
        })
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/empresa-documentos/<doc_id>/download", methods=["GET"])
@require_auth
def download_empresa_documento(doc_id):
    """Download/visualização de documento da empresa."""
    from models import Empresa, EmpresaDocumento
    user_id = get_current_user_id()
    download = request.args.get('download', 'false').lower() == 'true'

    db = get_db()
    try:
        doc = db.query(EmpresaDocumento).filter(EmpresaDocumento.id == doc_id).first()
        if not doc:
            return jsonify({"error": "Documento não encontrado"}), 404

        # Verificar propriedade via empresa
        empresa = db.query(Empresa).filter(
            Empresa.id == doc.empresa_id
        ).first()
        if not empresa:
            return jsonify({"error": "Acesso negado"}), 403

        if not doc.path_arquivo or not os.path.exists(doc.path_arquivo):
            return jsonify({"error": "Arquivo não encontrado no disco"}), 404

        # Detectar mimetype
        mimetype = 'application/pdf'
        nome = doc.nome_arquivo or 'documento'
        if nome.lower().endswith('.docx'):
            mimetype = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        elif nome.lower().endswith('.doc'):
            mimetype = 'application/msword'
        elif nome.lower().endswith('.txt'):
            mimetype = 'text/plain'

        return send_file(
            doc.path_arquivo,
            mimetype=mimetype,
            as_attachment=download,
            download_name=nome
        )
    finally:
        db.close()


@app.route("/api/empresa-certidoes/<certidao_id>/download", methods=["GET"])
@require_auth
def download_empresa_certidao(certidao_id):
    """Download/visualização de certidão da empresa."""
    from models import Empresa, EmpresaCertidao
    user_id = get_current_user_id()
    download = request.args.get('download', 'false').lower() == 'true'

    db = get_db()
    try:
        cert = db.query(EmpresaCertidao).filter(EmpresaCertidao.id == certidao_id).first()
        if not cert:
            return jsonify({"error": "Certidão não encontrada"}), 404

        empresa = db.query(Empresa).filter(
            Empresa.id == cert.empresa_id
        ).first()
        if not empresa:
            return jsonify({"error": "Acesso negado"}), 403

        if not cert.path_arquivo or not os.path.exists(cert.path_arquivo):
            return jsonify({"error": "Arquivo não encontrado no disco"}), 404

        return send_file(
            cert.path_arquivo,
            mimetype='application/pdf',
            as_attachment=download,
            download_name=f"certidao_{cert.tipo}_{cert.id[:8]}.pdf"
        )
    finally:
        db.close()


def _extrair_dados_certidao_pdf(filepath):
    """
    Extrai texto do PDF de certidão e usa LLM para identificar dados estruturados:
    numero, data_emissao, data_vencimento, orgao_emissor, situacao, resumo.
    Retorna dict ou None se falhar.
    """
    try:
        import fitz
        texto = ""
        doc = fitz.open(filepath)
        for page in doc:
            texto += page.get_text()
        doc.close()

        if not texto or len(texto.strip()) < 30:
            print(f"[CERTIDAO-IA] PDF sem texto suficiente: {len(texto)} chars")
            return None

        # Limitar texto para não estourar contexto
        texto_truncado = texto[:6000]

        from llm import call_deepseek
        prompt = f"""Analise o texto abaixo extraído de uma certidão e retorne APENAS um JSON com os campos:

- "numero": número/código da certidão (string ou null)
- "data_emissao": data de emissão no formato YYYY-MM-DD (string ou null)
- "data_vencimento": data de validade/vencimento no formato YYYY-MM-DD (string ou null)
- "orgao_emissor": órgão que emitiu (ex: "Receita Federal", "FGTS/Caixa", "TST") (string ou null)
- "situacao": uma das opções: "valida", "vencida", "invalida", "negativa", "positiva", "positiva com efeito de negativa", "nada consta", "regular", "irregular" (string)
- "resumo": resumo em 1-2 frases do conteúdo da certidão (string)

Regras:
- Se o texto indicar "NADA CONSTA", "NEGATIVA", "REGULAR" → situacao = correspondente
- Se indicar "POSITIVA" (sem "efeito de negativa") → situacao = "positiva" (débitos existem)
- Datas devem ser convertidas para YYYY-MM-DD
- Se não conseguir identificar um campo, use null
- Retorne APENAS o JSON, sem explicações

TEXTO DA CERTIDÃO:
{texto_truncado}"""

        resposta = call_deepseek(
            [{"role": "user", "content": prompt}],
            max_tokens=1000,
            model_override="deepseek-chat"
        )

        if not resposta:
            return None

        # Extrair JSON da resposta
        import json as json_mod
        import re
        # Tentar encontrar JSON na resposta
        json_match = re.search(r'\{[^{}]*\}', resposta, re.DOTALL)
        if json_match:
            dados = json_mod.loads(json_match.group())
            print(f"[CERTIDAO-IA] Dados extraídos: {dados}")
            return dados

        print(f"[CERTIDAO-IA] Resposta sem JSON válido: {resposta[:200]}")
        return None

    except Exception as e:
        print(f"[CERTIDAO-IA] Erro na extração: {e}")
        return None


@app.route("/api/empresa-certidoes/<certidao_id>/upload", methods=["POST"])
@require_auth
def upload_empresa_certidao(certidao_id):
    """
    Upload de arquivo PDF para uma certidão existente.
    Atualiza path_arquivo, status para 'valida', e data_vencimento se fornecida.

    Form data:
    - file: arquivo PDF
    - data_vencimento: (opcional) data de vencimento no formato YYYY-MM-DD
    - numero: (opcional) número da certidão
    """
    from models import Empresa, EmpresaCertidao
    user_id = get_current_user_id()

    if 'file' not in request.files:
        return jsonify({"error": "Arquivo não enviado"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Nenhum arquivo selecionado"}), 400

    # F04-07: validar magic bytes %PDF antes de salvar
    # (scrapers podem retornar HTML de erro/login com extensao .pdf — rejeitamos)
    file.stream.seek(0)
    primeiros_bytes = file.stream.read(4)
    file.stream.seek(0)
    if primeiros_bytes != b'%PDF':
        return jsonify({
            "error": "O arquivo enviado não é um PDF válido. Verifique se você selecionou o arquivo correto.",
            "magic_bytes_invalidos": True,
        }), 400

    db = get_db()
    try:
        cert = db.query(EmpresaCertidao).filter(EmpresaCertidao.id == certidao_id).first()
        if not cert:
            return jsonify({"error": "Certidão não encontrada"}), 404

        empresa = db.query(Empresa).filter(
            Empresa.id == cert.empresa_id
        ).first()
        if not empresa:
            return jsonify({"error": "Acesso negado"}), 403

        # Criar diretório para certidões
        upload_dir = os.path.join(UPLOAD_FOLDER, 'empresa', cert.empresa_id, 'certidoes')
        os.makedirs(upload_dir, exist_ok=True)

        # Salvar arquivo
        from werkzeug.utils import secure_filename
        safe_name = secure_filename(file.filename) or f"certidao_{uuid.uuid4().hex[:8]}.pdf"
        filepath = os.path.join(upload_dir, f"{uuid.uuid4().hex[:8]}_{safe_name}")
        file.save(filepath)

        # Extrair texto do PDF e usar IA para identificar dados da certidão
        from datetime import date as _date, datetime as _dt
        dados_ia = _extrair_dados_certidao_pdf(filepath)

        cert.path_arquivo = filepath
        cert.data_emissao = _date.today()

        # F04-06: rastrear divergencia entre data digitada pelo user e data extraida pela IA.
        # A data REAL do PDF (extraida pela IA) prevalece sobre a data digitada pelo user
        # — evita o caso "user digita 30/12/2026 mas validade real eh 30/03/2026" que mascara
        # certidoes vencidas como validas.
        data_venc_user_raw = (request.form.get('data_vencimento') or "").strip()
        data_venc_user_parsed = None
        if data_venc_user_raw:
            try:
                data_venc_user_parsed = _dt.strptime(data_venc_user_raw, '%Y-%m-%d').date()
            except ValueError:
                pass

        divergencia_data = None  # dict {data_user, data_ia, prevaleceu}

        if dados_ia:
            # IA extraiu dados — aplicar automaticamente
            data_venc_ia = None
            if dados_ia.get("data_vencimento"):
                try:
                    data_venc_ia = _dt.strptime(dados_ia["data_vencimento"], '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    pass

            # F04-06: se o user digitou validade E a IA extraiu validade do PDF, e divergem,
            # PREVALECE a data extraida do PDF (mais confiavel)
            if data_venc_ia and data_venc_user_parsed and data_venc_ia != data_venc_user_parsed:
                cert.data_vencimento = data_venc_ia
                divergencia_data = {
                    "data_informada_user": data_venc_user_parsed.isoformat(),
                    "data_extraida_pdf": data_venc_ia.isoformat(),
                    "prevaleceu": "data_extraida_pdf",
                    "motivo": "Divergencia detectada entre data digitada e data real do PDF — usada a data real",
                }
            elif data_venc_ia:
                cert.data_vencimento = data_venc_ia
            elif data_venc_user_parsed:
                cert.data_vencimento = data_venc_user_parsed

            if dados_ia.get("data_emissao"):
                try:
                    cert.data_emissao = _dt.strptime(dados_ia["data_emissao"], '%Y-%m-%d').date()
                except (ValueError, TypeError):
                    pass
            if dados_ia.get("numero"):
                cert.numero = dados_ia["numero"]
            if dados_ia.get("orgao_emissor"):
                cert.orgao_emissor = dados_ia["orgao_emissor"]

            situacao = (dados_ia.get("situacao") or "").lower()
            if situacao in ("valida", "válida", "regular", "positiva com efeito de negativa", "nada consta", "negativa"):
                cert.status = 'valida'
            elif situacao in ("vencida", "expirada"):
                cert.status = 'vencida'
            elif situacao in ("invalida", "inválida", "positiva", "irregular"):
                cert.status = 'pendente'
            else:
                cert.status = 'valida'  # Upload manual = assume válida

            cert.mensagem = dados_ia.get("resumo") or "Certidão enviada por upload manual"
            extras = {k: v for k, v in dados_ia.items() if k not in ("resumo",) and v}
            if divergencia_data:
                extras["__divergencia_validade"] = divergencia_data
            cert.dados_extras = extras
        else:
            # Falha na extração IA — salvar com dados mínimos
            cert.status = 'valida'
            cert.mensagem = "Certidão enviada por upload manual (extração automática indisponível)"
            # Sem IA: aceitar data do user (nao tem como validar)
            if data_venc_user_parsed:
                cert.data_vencimento = data_venc_user_parsed

        numero = request.form.get('numero')
        if numero:
            cert.numero = numero

        db.commit()
        msg_base = "Certidão atualizada com sucesso"
        if dados_ia:
            msg_base += " (dados extraídos por IA)"
        if divergencia_data:
            msg_base += f". ATENCAO: a IA detectou validade {divergencia_data['data_extraida_pdf']} no PDF, diferente da que voce digitou ({divergencia_data['data_informada_user']}). Foi usada a data real do PDF."
        return jsonify({
            "success": True,
            "message": msg_base,
            "certidao": cert.to_dict(),
            "dados_extraidos": dados_ia,
            "divergencia_validade": divergencia_data,
        })

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# B4: Usar porte/regime da empresa no cálculo de validação
# (Implementado em tools.py via PROMPT_SCORES_VALIDACAO)
# =============================================================================


# =============================================================================
# B5: Gerar classes/subclasses automaticamente via IA
# =============================================================================

@app.route("/api/parametrizacoes/gerar-classes", methods=["POST"])
@require_auth
def gerar_classes_ia():
    """
    Sprint 8 (UC-CL01): Gera classes e subclasses via IA.
    RN-NEW-09: mínimo 20 produtos. RN-084: cooldown 60s. RN-132: audit.
    Param JSON opcional: {"aplicar": true} para criar registros após geração.
    """
    from models import Produto, AreaProduto, ClasseProdutoV2, SubclasseProduto, AuditoriaLog
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    body = request.get_json(silent=True) or {}
    aplicar = body.get("aplicar", False)

    db = get_db()
    try:
        produtos = db.query(Produto).filter(Produto.empresa_id == empresa_id).all()

        if not produtos:
            return jsonify({"error": "Nenhum produto cadastrado. Cadastre produtos primeiro."}), 400

        # RN-NEW-09: mínimo 20 produtos
        if len(produtos) < 20:
            return jsonify({
                "error": f"Mínimo de 20 produtos exigido (atual: {len(produtos)}). Cadastre mais produtos.",
                "total_produtos": len(produtos)
            }), 400

        # RN-084: cooldown 60s
        ultima = db.query(AuditoriaLog).filter(
            AuditoriaLog.user_id == user_id,
            AuditoriaLog.entidade == 'gerar_classes_ia',
        ).order_by(AuditoriaLog.created_at.desc()).first()
        if ultima and ultima.created_at:
            diff = (datetime.now() - ultima.created_at).total_seconds()
            if diff < 60:
                return jsonify({"error": f"Aguarde {int(60 - diff)}s antes de nova geração."}), 429

        lista_produtos = []
        for p in produtos:
            lista_produtos.append(
                f"- {p.nome} (categoria: {p.categoria}, NCM: {p.ncm or 'N/A'}, "
                f"fabricante: {p.fabricante or 'N/A'}, descricao: {(p.descricao or '')[:80]})"
            )

        prompt = f"""Você é um especialista em classificação de produtos para licitações públicas.

Dado os seguintes {len(produtos)} produtos cadastrados:

{chr(10).join(lista_produtos)}

Agrupe esses produtos em ÁREAS, CLASSES e SUBCLASSES lógicas para facilitar a gestão em processos licitatórios.
Para cada subclasse, sugira campos_mascara (campos técnicos que a IA deve extrair de documentos do produto).

RESPONDA APENAS EM JSON com a seguinte estrutura:
{{
  "areas": [
    {{
      "nome": "Nome da Área",
      "classes": [
        {{
          "nome": "Nome da Classe",
          "descricao": "Descrição breve",
          "subclasses": [
            {{
              "nome": "Nome da Subclasse",
              "ncm": "XXXX.XX.XX",
              "campos_mascara": [{{"nome": "Campo1", "tipo": "texto"}}, {{"nome": "Campo2", "tipo": "numero"}}],
              "produtos_sugeridos": ["Nome Produto 1", "Nome Produto 2"]
            }}
          ]
        }}
      ]
    }}
  ]
}}
"""

        resposta = call_deepseek(
            [{"role": "user", "content": prompt}],
            max_tokens=4000,
            model_override="deepseek-chat"
        )

        # RN-132: audit log
        try:
            db.add(AuditoriaLog(
                user_id=user_id, empresa_id=empresa_id,
                entidade='gerar_classes_ia', operacao='invocacao_deepseek',
                dados_novos={"total_produtos": len(produtos)},
            ))
            db.commit()
        except Exception:
            db.rollback()

        import json as json_mod, re as re_mod
        texto = resposta if isinstance(resposta, str) else str(resposta)
        json_match = re_mod.search(r'\{[\s\S]*\}', texto)
        if not json_match:
            return jsonify({
                "success": True, "areas": [], "raw_response": texto[:2000],
                "message": "IA retornou resposta mas não no formato JSON esperado"
            })

        try:
            resultado = json_mod.loads(json_match.group(0))
        except json_mod.JSONDecodeError:
            return jsonify({
                "success": True, "areas": [], "raw_response": texto[:2000],
                "message": "JSON inválido na resposta da IA"
            })

        areas_data = resultado.get("areas", resultado.get("classes", []))

        # Se aplicar=true, criar registros no banco
        criados = {"areas": 0, "classes": 0, "subclasses": 0, "produtos_vinculados": 0}
        if aplicar and areas_data:
            prod_map = {p.nome.lower().strip(): p for p in produtos}
            for area_d in areas_data:
                area = AreaProduto(empresa_id=empresa_id, nome=area_d["nome"])
                db.add(area)
                db.flush()
                criados["areas"] += 1
                for cls_d in area_d.get("classes", []):
                    classe = ClasseProdutoV2(empresa_id=empresa_id, nome=cls_d["nome"], area_id=area.id, descricao=cls_d.get("descricao"))
                    db.add(classe)
                    db.flush()
                    criados["classes"] += 1
                    for sub_d in cls_d.get("subclasses", []):
                        sub = SubclasseProduto(
                            empresa_id=empresa_id, nome=sub_d["nome"], classe_id=classe.id,
                            ncms=[sub_d["ncm"]] if sub_d.get("ncm") else None,
                            campos_mascara=sub_d.get("campos_mascara"),
                        )
                        db.add(sub)
                        db.flush()
                        criados["subclasses"] += 1
                        for pname in sub_d.get("produtos_sugeridos", []):
                            prod = prod_map.get(pname.lower().strip())
                            if prod:
                                prod.subclasse_id = sub.id
                                criados["produtos_vinculados"] += 1
            db.commit()

        return jsonify({
            "success": True,
            "areas": areas_data,
            "total_produtos": len(produtos),
            "criados": criados if aplicar else None,
        })

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# B6: Vincular documento da empresa a item/requisito do edital
# =============================================================================

@app.route("/api/editais/<edital_id>/vincular-documento", methods=["POST"])
@require_auth
def vincular_documento_edital(edital_id):
    """
    Vincula um documento da empresa a um requisito do edital.

    JSON body:
    - documento_id: ID do EmpresaDocumento ou EmpresaCertidao
    - requisito_id: ID do EditalRequisito
    - tipo_documento: "documento" ou "certidao"
    """
    from models import Empresa, EmpresaDocumento, EmpresaCertidao, EditalRequisito, Edital
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.json or {}

    documento_id = data.get('documento_id')
    requisito_id = data.get('requisito_id')
    tipo_documento = data.get('tipo_documento', 'documento')

    if not documento_id or not requisito_id:
        return jsonify({"error": "documento_id e requisito_id são obrigatórios"}), 400

    db = get_db()
    try:
        # Verificar edital pertence ao usuário
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()
        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404

        # Verificar requisito pertence ao edital
        requisito = db.query(EditalRequisito).filter(
            EditalRequisito.id == requisito_id,
            EditalRequisito.edital_id == edital_id
        ).first()
        if not requisito:
            return jsonify({"error": "Requisito não encontrado"}), 404

        # Vincular (via campo edital_requisito_id no documento)
        if tipo_documento == 'certidao':
            cert = db.query(EmpresaCertidao).filter(EmpresaCertidao.id == documento_id).first()
            if not cert:
                return jsonify({"error": "Certidão não encontrada"}), 404
            cert.edital_requisito_id = requisito_id
        else:
            doc = db.query(EmpresaDocumento).filter(EmpresaDocumento.id == documento_id).first()
            if not doc:
                return jsonify({"error": "Documento não encontrado"}), 404
            doc.edital_requisito_id = requisito_id

        db.commit()

        return jsonify({
            "success": True,
            "message": f"Documento vinculado ao requisito '{requisito.descricao[:60]}'"
        })

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/editais/<edital_id>/documentacao-necessaria", methods=["GET"])
@require_auth
def documentacao_necessaria(edital_id):
    """
    Retorna documentação necessária para o edital, cruzando requisitos extraídos
    do PDF com documentos/certidões reais da empresa.
    Se o edital não tem requisitos documentais extraídos, usa lista padrão de licitações.
    Formato: { documentos: [{ nome, categoria, status, validade, exigido }] }
    """
    from models import Empresa, EmpresaDocumento, EmpresaCertidao, EditalRequisito, Edital
    from datetime import date
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()

    db = get_db()
    try:
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()
        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404

        empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()

        # Requisitos documentais extraídos do edital (se houver)
        requisitos_doc = db.query(EditalRequisito).filter(
            EditalRequisito.edital_id == edital_id,
            EditalRequisito.tipo == 'documental'
        ).all()

        # Documentos e certidões da empresa (indexados por tipo)
        from models import DocumentoNecessario, CategoriaDocumento, FonteCertidao
        docs_empresa_por_tipo = {}
        certs_por_tipo = {}
        certs_por_fonte = {}
        if empresa:
            for d in db.query(EmpresaDocumento).filter(EmpresaDocumento.empresa_id == empresa.id).all():
                docs_empresa_por_tipo.setdefault(d.tipo, []).append(d)
            for c in db.query(EmpresaCertidao).filter(EmpresaCertidao.empresa_id == empresa.id).all():
                certs_por_tipo.setdefault(c.tipo, []).append(c)
                if c.fonte_certidao_id:
                    certs_por_fonte[c.fonte_certidao_id] = c

        hoje = date.today()
        documentos = []

        # === DOCUMENTOS: carregar do banco (documentos_necessarios) ===
        docs_necessarios_db = db.query(DocumentoNecessario).filter(
            DocumentoNecessario.ativo == True
        ).order_by(DocumentoNecessario.ordem).all()

        # === CERTIDÕES: carregar do banco (fontes_certidoes) ===
        fontes_certidoes_db = db.query(FonteCertidao).filter(
            FonteCertidao.ativo == True
        ).order_by(FonteCertidao.nome).all()

        # Tipos de certidão conhecidos (para checar_status)
        TIPOS_CERTIDAO = {fc.tipo_certidao for fc in fontes_certidoes_db if fc.tipo_certidao}

        def checar_status_documento(tipo_ref):
            """Cruza tipo_ref com documentos da empresa."""
            encontrados = docs_empresa_por_tipo.get(tipo_ref, [])
            if encontrados:
                doc = encontrados[0]
                venc = doc.data_vencimento
                if venc and venc < hoje:
                    return "vencido", venc.strftime("%d/%m/%Y") if venc else None
                return "ok", venc.strftime("%d/%m/%Y") if venc else None
            return "faltando", None

        def checar_status_certidao_por_fonte(fonte_id):
            """Cruza fonte_certidao_id com certidões da empresa."""
            cert = certs_por_fonte.get(fonte_id)
            if cert:
                venc = cert.data_vencimento
                if cert.status == "vencida" or (venc and venc < hoje):
                    return "vencido", venc.strftime("%d/%m/%Y") if venc else None
                elif cert.status in ("valida",):
                    return "ok", venc.strftime("%d/%m/%Y") if venc else None
                else:
                    return "faltando", None
            return "faltando", None

        # Tipos exigidos pelo edital (se requisitos foram extraídos do PDF)
        tipos_exigidos_edital = set()
        if requisitos_doc:
            for req in requisitos_doc:
                tipo_ref = (req.nome_especificacao or "").strip().lower()
                tipos_exigidos_edital.add(tipo_ref)

        # === PARTE 1: Documentos da empresa (do banco documentos_necessarios) ===
        for dn in docs_necessarios_db:
            categoria = dn.categoria_rel.nome if dn.categoria_rel else "Outros"

            # Não incluir tipos de certidão aqui (vão na parte 2)
            if dn.tipo_chave in TIPOS_CERTIDAO:
                continue

            status, validade = checar_status_documento(dn.tipo_chave)
            exigido = dn.tipo_chave in tipos_exigidos_edital if requisitos_doc else dn.obrigatorio
            documentos.append({
                "nome": dn.nome,
                "categoria": categoria,
                "status": status,
                "validade": validade,
                "exigido": exigido,
            })

        # === PARTE 2: Certidões (do banco fontes_certidoes) ===
        for fc in fontes_certidoes_db:
            status, validade = checar_status_certidao_por_fonte(fc.id)
            exigido = fc.tipo_certidao in tipos_exigidos_edital if requisitos_doc else True
            documentos.append({
                "nome": fc.nome,
                "categoria": "Certidões e Fiscal",
                "status": status,
                "validade": validade,
                "exigido": exigido,
            })

        # === PARTE 3: Documentos extras do edital — inserir no banco se não existem ===
        if requisitos_doc:
            tipos_ja_incluidos = {dn.tipo_chave for dn in docs_necessarios_db} | {fc.tipo_certidao for fc in fontes_certidoes_db}
            # Buscar categoria "Outros" para inserir novos tipos
            cat_outros = db.query(CategoriaDocumento).filter(CategoriaDocumento.nome.ilike("%outro%")).first()
            cat_outros_id = cat_outros.id if cat_outros else None
            nomes_ja_inseridos = set()

            for req in requisitos_doc:
                tipo_ref = (req.nome_especificacao or "").strip().lower()
                if tipo_ref not in tipos_ja_incluidos and tipo_ref != "":
                    nome = req.descricao[:80] if req.descricao else "Documento exigido pelo edital"

                    # Evitar duplicatas dentro do mesmo lote
                    if nome in nomes_ja_inseridos:
                        continue
                    nomes_ja_inseridos.add(nome)

                    # Gerar tipo_chave único a partir do nome
                    import re as _re
                    tipo_chave_novo = _re.sub(r'[^a-z0-9]', '_', nome.lower().strip())[:50]

                    # Verificar se tipo_chave já existe no banco
                    existe = db.query(DocumentoNecessario).filter(
                        DocumentoNecessario.tipo_chave == tipo_chave_novo
                    ).first()

                    if not existe:
                        # Inserir novo tipo de documento na tabela documentos_necessarios
                        novo_doc_nec = DocumentoNecessario(
                            id=str(uuid.uuid4()),
                            categoria_id=cat_outros_id,
                            nome=nome,
                            tipo_chave=tipo_chave_novo,
                            obrigatorio=True,
                            ativo=True,
                            ordem=200,
                        )
                        db.add(novo_doc_nec)
                        print(f"[DOCS] Novo tipo inserido: {nome} (chave={tipo_chave_novo})")

                    documentos.append({
                        "nome": nome,
                        "categoria": "Outros",
                        "status": "faltando",
                        "validade": None,
                        "exigido": True,
                        "descricao_edital": req.descricao,
                    })

            if nomes_ja_inseridos:
                db.commit()

        return jsonify({
            "success": True,
            "edital_id": edital_id,
            "edital_numero": edital.numero,
            "documentos": documentos,
            "total": len(documentos),
            "fonte": "requisitos_edital" if requisitos_doc else "padrao_licitacao",
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Endpoints REST para Precificação (chamam tools diretamente, sem chat)
# =============================================================================

@app.route("/api/precificacao/buscar-cadastrar-produto/<item_id>", methods=["POST"])
@require_auth
def precif_buscar_cadastrar_produto(item_id):
    """Busca produto na web pela descrição do item, baixa PDF se encontrar, cadastra e vincula."""
    from models import EditalItem
    from tools import tool_web_search
    user_id = get_current_user_id()
    db = get_db()
    try:
        item = db.query(EditalItem).filter(EditalItem.id == item_id).first()
        if not item:
            return jsonify({"success": False, "error": "Item não encontrado"})

        tipo = (request.get_json(silent=True) or {}).get("tipo", "web")  # "web" ou "anvisa"
        desc = (item.descricao or "")[:100]

        if tipo == "anvisa":
            from tools import tool_buscar_anvisa
            resultado = tool_buscar_anvisa(desc, user_id)
        else:
            resultado = tool_web_search(f"manual ficha técnica {desc}", user_id)

        if not resultado.get("success"):
            return jsonify({"success": False, "error": resultado.get("error", "Nenhum resultado")})

        # Retornar resultados para o usuário escolher
        pdfs = resultado.get("resultados_pdf", [])[:5]
        outros = resultado.get("outros_resultados", [])[:5]
        registros_anvisa = resultado.get("registros", [])[:5]

        return jsonify({
            "success": True,
            "item_descricao": desc,
            "pdfs": pdfs,
            "outros": outros,
            "registros_anvisa": registros_anvisa,
            "total": resultado.get("total_resultados", 0),
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        db.close()


@app.route("/api/precificacao/vincular-ia/<item_id>", methods=["POST"])
@require_auth
def precif_vincular_ia(item_id):
    """UC-P02: Seleção inteligente — IA analisa item e sugere melhor produto do portfolio.
    Se body tem produto_id, faz vinculação manual confirmada (sem matching automático)."""
    from tools import tool_selecao_portfolio
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    body = request.get_json(silent=True) or {}
    produto_id = body.get("produto_id")
    resultado = tool_selecao_portfolio(
        edital_item_id=item_id,
        user_id=user_id,
        empresa_id=empresa_id,
        produto_id=produto_id,
    )
    return jsonify(resultado)


@app.route("/api/precificacao/<eip_id>/custos", methods=["POST"])
@require_auth
def precif_custos(eip_id):
    """UC-P04: Configurar custos (Camada A) — calcula tributos e isenção ICMS."""
    from tools import tool_configurar_custos
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.get_json() or {}
    resultado = tool_configurar_custos(
        edital_item_produto_id=eip_id, user_id=user_id,
        custo_unitario=data.get("custo_unitario"),
        custo_fonte=data.get("custo_fonte", "manual"),
        icms=data.get("icms"), ipi=data.get("ipi"), pis_cofins=data.get("pis_cofins"),
        empresa_id=empresa_id,
    )
    return jsonify(resultado)


@app.route("/api/precificacao/<eip_id>/preco-base", methods=["POST"])
@require_auth
def precif_preco_base(eip_id):
    """UC-P05: Montar preço base (Camada B) — manual, custo+markup ou upload."""
    from tools import tool_montar_preco_base
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.get_json() or {}
    print(f"[PRECO_BASE] eip={eip_id[:8]} user={user_id[:8]} empresa={empresa_id} modo={data.get('modo')} markup={data.get('markup_percentual')}")
    resultado = tool_montar_preco_base(
        edital_item_produto_id=eip_id, user_id=user_id,
        empresa_id=empresa_id,
        modo=data.get("modo", "manual"),
        preco_base=data.get("preco_base"),
        markup_percentual=data.get("markup_percentual"),
    )
    return jsonify(resultado)


@app.route("/api/precificacao/<eip_id>/referencia", methods=["POST"])
@require_auth
def precif_referencia(eip_id):
    """UC-P06: Definir valor de referência (Camada C)."""
    from tools import tool_definir_referencia
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.get_json() or {}
    resultado = tool_definir_referencia(
        edital_item_produto_id=eip_id, user_id=user_id,
        empresa_id=empresa_id,
        valor_referencia=data.get("valor_referencia"),
        percentual_sobre_base=data.get("percentual_sobre_base"),
    )
    return jsonify(resultado)


@app.route("/api/precificacao/<eip_id>/lances", methods=["POST"])
@require_auth
def precif_lances(eip_id):
    """UC-P07: Estruturar lances (Camadas D e E)."""
    from tools import tool_estruturar_lances
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.get_json() or {}
    resultado = tool_estruturar_lances(
        edital_item_produto_id=eip_id, user_id=user_id,
        empresa_id=empresa_id,
        lance_inicial=data.get("lance_inicial"),
        lance_minimo=data.get("lance_minimo"),
        modo_inicial=data.get("modo_inicial", "absoluto"),
        modo_minimo=data.get("modo_minimo", "absoluto"),
        desconto_maximo_pct=data.get("desconto_maximo_pct"),
    )
    return jsonify(resultado)


@app.route("/api/precificacao/<edital_id>/estrategia", methods=["POST"])
@require_auth
def precif_estrategia(edital_id):
    """UC-P08: Definir estratégia competitiva."""
    from tools import tool_estrategia_competitiva
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.get_json() or {}
    resultado = tool_estrategia_competitiva(
        edital_id=edital_id, user_id=user_id,
        perfil=data.get("perfil", "quero_ganhar"),
        empresa_id=empresa_id,
    )
    return jsonify(resultado)


@app.route("/api/precificacao/simular-ia", methods=["POST"])
@require_auth
def precif_simular_ia():
    """Simula cenários de lance usando IA (DeepSeek) — sem passar pelo chat."""
    from llm import call_deepseek
    data = request.get_json() or {}
    prompt = data.get("prompt", "")
    if not prompt:
        return jsonify({"success": False, "error": "Prompt vazio"}), 400
    try:
        resposta = call_deepseek(
            [{"role": "user", "content": prompt}],
            max_tokens=2000,
            model_override="deepseek-chat"
        )
        return jsonify({"success": True, "response": resposta})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/precificacao/simular-disputa", methods=["POST"])
@require_auth
def precif_simular_disputa():
    """Simula disputa de lances rodada a rodada usando IA (DeepSeek)."""
    from llm import call_deepseek
    data = request.get_json() or {}

    lance_inicial = data.get("lance_inicial", 0)
    lance_minimo = data.get("lance_minimo", 0)
    custo = data.get("custo", 0)
    perfil = data.get("perfil", "quero_ganhar")
    concorrentes = data.get("concorrentes", [])
    historico = data.get("historico", {})
    produto = data.get("produto", "Produto")

    conc_desc = ""
    for c in concorrentes:
        precos = c.get("precos_historicos", [])
        precos_str = ", ".join([f"R$ {p:.2f}" for p in precos[:5]]) if precos else "sem dados"
        conc_desc += f"- {c['nome']}: preço médio R$ {c.get('preco_medio', 0):.2f}, preços homologados: [{precos_str}]\n"

    estrategia_desc = "QUERO GANHAR — disputa agressiva: reduzir lances até o mínimo para vencer" if perfil == "quero_ganhar" else "NÃO GANHEI NO MÍNIMO — chegou ao piso e não venceu, reposicionar para melhor colocação possível (2º, 3º lugar)"

    prompt = f"""Você é um simulador de disputa de licitação pública (pregão eletrônico brasileiro).

DADOS DA NOSSA EMPRESA:
- Produto: {produto}
- Lance inicial de abertura: R$ {lance_inicial:.2f}
- Lance mínimo (piso, abaixo disso prejuízo): R$ {lance_minimo:.2f}
- Custo base do produto: R$ {custo:.2f}
- Estratégia: {estrategia_desc}

CONCORRENTES IDENTIFICADOS (baseados em atas reais do PNCP):
{conc_desc or "Nenhum concorrente identificado — simule com 2 concorrentes genéricos"}

HISTÓRICO DE MERCADO:
- Preço mínimo homologado: R$ {historico.get('preco_min', 0):.2f}
- Preço médio homologado: R$ {historico.get('preco_medio', 0):.2f}
- Preço máximo homologado: R$ {historico.get('preco_max', 0):.2f}

REGRAS DO PREGÃO ELETRÔNICO (LANCE ABERTO):
- Rodada 1: cada empresa apresenta seu lance inicial
- Rodadas seguintes: empresas podem reduzir lance ou desistir
- Cada concorrente reduz baseado no seu padrão histórico (empresas com preços médios mais baixos são mais agressivas)
- Uma empresa desiste quando o próximo lance ficaria abaixo do seu custo estimado
- A cada rodada, o menor lance lidera
- A disputa termina quando resta só um competidor OU todos chegam ao limite

{"Se a nossa empresa chegar ao lance mínimo e NÃO vencer, mostre o reposicionamento: nosso lance fica no mínimo e indicamos a posição final (2º, 3º lugar)." if perfil == "nao_ganhei_minimo" else "Nossa empresa vai reduzir progressivamente do lance inicial até o mínimo para tentar vencer."}

SIMULE a disputa rodada a rodada. Use valores realistas baseados nos preços históricos dos concorrentes.

RETORNE em formato markdown:

## Simulação de Disputa — Lance Aberto

### Tabela de Rodadas

| Rodada | Nossa Empresa | {" | ".join([c["nome"][:20] for c in concorrentes[:3]]) or "Concorrente A | Concorrente B"} | Observação |
|--------|--------------|{"---|".join(["---" for _ in range(min(len(concorrentes), 3) or 2)])}|------------|
(preencha as rodadas com valores decrescentes realistas)

### Resultado Final
- Resultado: VITÓRIA ou DERROTA
- Lance final: R$ X,XX
- Posição: 1º, 2º ou 3º
- Margem final sobre custo: X%

### Análise do Comportamento dos Concorrentes
(explique como cada concorrente se comportou e por que desistiu ou continuou)

### Recomendação
(diga se o lance mínimo está adequado ou se deveria ser ajustado)"""

    try:
        resposta = call_deepseek(
            [{"role": "user", "content": prompt}],
            max_tokens=3000,
            model_override="deepseek-chat"
        )
        return jsonify({"success": True, "simulacao_md": resposta})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/precificacao/<eip_id>/insights", methods=["GET"])
@require_auth
def precif_insights(eip_id):
    """Agrega histórico + recomendação IA + concorrentes para um item-produto."""
    from tools import tool_insights_precificacao
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    resultado = tool_insights_precificacao(eip_id, user_id, empresa_id=empresa_id)
    return jsonify(resultado)


@app.route("/api/precificacao/<eip_id>/insights-salvos", methods=["GET"])
@require_auth
def precif_insights_salvos(eip_id):
    """Retorna análise IA salva no banco (sem recalcular)."""
    import json as _json
    user_id = get_current_user_id()
    db = get_db()
    try:
        from models import PrecoCamada
        camada = db.query(PrecoCamada).filter(
            PrecoCamada.edital_item_produto_id == eip_id,
            PrecoCamada.empresa_id == empresa_id
        ).first()
        if camada and camada.analise_ia_json:
            data = _json.loads(camada.analise_ia_json)
            data["saved"] = True
            data["saved_at"] = camada.analise_ia_data.isoformat() if camada.analise_ia_data else None
            return jsonify(data)
        return jsonify({"saved": False})
    finally:
        db.close()


@app.route("/api/editais/<edital_id>/analisar-mercado", methods=["POST"])
@require_auth
def analisar_mercado_edital(edital_id):
    """Análise de mercado do órgão: dados PNCP + histórico interno + IA."""
    from models import Edital, OrgaoPerfil, EstrategiaEdital
    from tools import _extrair_json_object
    import requests as req
    from datetime import datetime, timedelta

    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        edital = db.query(Edital).filter(Edital.id == edital_id, Edital.empresa_id == empresa_id).first()
        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404

        cnpj_orgao = edital.cnpj_orgao
        nome_orgao = edital.orgao or ""
        uf_orgao = edital.uf or ""

        if not cnpj_orgao and not nome_orgao:
            return jsonify({"error": "Edital sem dados do órgão (CNPJ ou nome)"}), 400

        # Verificar cache no banco (< 30 dias)
        forcar = (request.get_json(silent=True) or {}).get("forcar", False)
        perfil_db = None
        if cnpj_orgao:
            perfil_db = db.query(OrgaoPerfil).filter(OrgaoPerfil.cnpj == cnpj_orgao).first()

        if perfil_db and not forcar:
            if perfil_db.ultima_atualizacao and perfil_db.ultima_atualizacao > datetime.now() - timedelta(days=30):
                # Retornar do cache
                hist_interno = _calcular_historico_interno(db, nome_orgao, user_id)
                mods_cache = perfil_db.modalidades_frequentes or {}
                esfera_c = "Federal" if any(p in (perfil_db.nome or "").upper() for p in ["MINISTERIO", "FEDERAL", "NACIONAL"]) else "Estadual" if any(p in (perfil_db.nome or "").upper() for p in ["ESTADO", "ESTADUAL"]) else "Municipal"
                return jsonify({
                    "success": True,
                    "cache": True,
                    "orgao": {"nome": perfil_db.nome, "cnpj": perfil_db.cnpj, "uf": perfil_db.uf},
                    "estatisticas": {
                        "total_compras": perfil_db.total_compras,
                        "valor_total": float(perfil_db.valor_total_compras) if perfil_db.valor_total_compras else 0,
                        "valor_medio": float(perfil_db.valor_medio_compras) if perfil_db.valor_medio_compras else 0,
                        "modalidades": mods_cache,
                    },
                    "compras_similares": perfil_db.compras_similares or [],
                    "reputacao": {
                        "esfera": esfera_c,
                        "risco_pagamento": "Baixo" if esfera_c == "Federal" else "Médio" if esfera_c == "Estadual" else "Alto",
                        "volume": "Alto" if (perfil_db.total_compras or 0) > 100 else "Médio" if (perfil_db.total_compras or 0) > 20 else "Baixo",
                        "modalidade_principal": max(mods_cache, key=mods_cache.get) if mods_cache else "N/A",
                        "percentual_pregao": round(mods_cache.get("Pregão - Eletrônico", 0) / max(perfil_db.total_compras or 1, 1) * 100, 1),
                        "editais_similares": len(perfil_db.compras_similares or []),
                    },
                    "historico_interno": hist_interno,
                    "analise_ia": perfil_db.analise_ia or "",
                })

        # === Buscar no PNCP ===
        print(f"[MERCADO] Buscando compras do órgão: {nome_orgao}")
        # Buscar pelo nome do órgão (primeiras 3 palavras significativas)
        import re as _re
        palavras_orgao = [w for w in _re.sub(r'[^\w\s]', '', nome_orgao).split() if len(w) > 2][:4]
        termo_orgao = " ".join(palavras_orgao)

        compras = []
        total_pncp = 0
        try:
            url_search = f"https://pncp.gov.br/api/search/?q={termo_orgao}&tipos_documento=edital&tam_pagina=50&pagina=1&ordenacao=-data"
            resp = req.get(url_search, timeout=20, headers={"Accept": "application/json"})
            if resp.status_code == 200:
                data = resp.json()
                total_pncp = data.get("total", 0)
                for item in data.get("items", []):
                    # Filtrar só do mesmo órgão (CNPJ ou nome)
                    item_cnpj = item.get("orgao_cnpj", "")
                    item_orgao = item.get("orgao_nome", "")
                    if cnpj_orgao and item_cnpj != cnpj_orgao:
                        continue
                    if not cnpj_orgao and nome_orgao[:15].lower() not in item_orgao.lower():
                        continue
                    compras.append({
                        "objeto": (item.get("description") or "")[:80],
                        "valor": item.get("valor_global"),
                        "data": str(item.get("data_publicacao_pncp", ""))[:10],
                        "modalidade": item.get("modalidade_licitacao_nome", ""),
                        "uf": item.get("uf", ""),
                        "cnpj_orgao": item_cnpj,
                        "ano": item.get("ano"),
                        "seq": item.get("numero_sequencial"),
                    })
        except Exception as e:
            print(f"[MERCADO] Erro ao buscar PNCP: {e}")

        # Calcular estatísticas
        valores = [c["valor"] for c in compras if c.get("valor") and c["valor"] > 0]
        valor_total = sum(valores) if valores else 0
        valor_medio = valor_total / len(valores) if valores else 0
        modalidades = {}
        for c in compras:
            mod = c.get("modalidade", "Outro")
            modalidades[mod] = modalidades.get(mod, 0) + 1

        # Compras similares — usar palavras-chave do objeto + produto
        produto_match = None
        analise_exist = db.query(Analise).filter(Analise.edital_id == edital_id, Analise.empresa_id == empresa_id).first()
        if analise_exist and analise_exist.produto_id:
            from models import Produto
            produto_match = db.query(Produto).filter(Produto.id == analise_exist.produto_id).first()

        # Palavras-chave para filtrar compras similares
        # Prioridade: 1) primeira palavra significativa do produto, 2) palavras do objeto
        import unicodedata
        def _sem_acento_lower(txt):
            return ''.join(c for c in unicodedata.normalize('NFD', txt.lower()) if unicodedata.category(c) != 'Mn')

        stop_similar = {"aquisicao", "contratacao", "registro", "preco", "futura", "eventual",
                        "fornecimento", "servico", "atender", "demandas", "necessidades",
                        "destinado", "destinada", "para", "material", "equipamento",
                        "binocular", "trinocular", "automatico", "descartavel", "eletronico",
                        "instituto", "nacional", "federal", "estadual", "municipal",
                        "tecnicas", "cientificas", "pantanal", "eclipse", "modelo"}

        palavras_chave = []
        # Do produto (mais preciso)
        if produto_match:
            for w in _sem_acento_lower(produto_match.nome).split():
                if len(w) > 4 and w not in stop_similar and w not in palavras_chave:
                    palavras_chave.append(w)
        # Do objeto (complementar)
        for w in _sem_acento_lower(edital.objeto or "").split():
            if len(w) > 5 and w not in stop_similar and w not in palavras_chave:
                palavras_chave.append(w)
        palavras_chave = palavras_chave[:4]
        print(f"[MERCADO] Palavras-chave similares: {palavras_chave}")

        similares = []
        for c in compras:
            obj_c = _sem_acento_lower(c.get("objeto") or "")
            if any(p in obj_c for p in palavras_chave):
                similares.append(c)

        # Buscar valores das compras (Search API não retorna valores)
        # Buscar para as 10 primeiras compras (pregões e similares primeiro)
        compras_para_buscar = sorted(compras, key=lambda x: 0 if x in similares else 1)[:10]
        for c in compras_para_buscar:
            if not c.get("valor") or c["valor"] == 0:
                try:
                    c_cnpj = c.get("cnpj_orgao") or cnpj_orgao
                    c_ano = c.get("ano")
                    c_seq = c.get("seq")
                    if c_cnpj and c_ano and c_seq:
                        url_det = f"https://pncp.gov.br/api/consulta/v1/orgaos/{c_cnpj}/compras/{c_ano}/{c_seq}"
                        resp_det = req.get(url_det, timeout=8, headers={"Accept": "application/json"})
                        if resp_det.status_code == 200:
                            dados_det = resp_det.json()
                            valor = dados_det.get("valorTotalEstimado") or dados_det.get("valorTotalHomologado")
                            if not valor:
                                # Somar dos itens
                                url_it = f"https://pncp.gov.br/api/pncp/v1/orgaos/{c_cnpj}/compras/{c_ano}/{c_seq}/itens"
                                resp_it = req.get(url_it, timeout=8, headers={"Accept": "application/json"})
                                if resp_it.status_code == 200:
                                    itens_det = resp_it.json()
                                    if isinstance(itens_det, list):
                                        valor = sum(it.get("valorTotal") or 0 for it in itens_det)
                            if valor and valor > 0:
                                c["valor"] = valor
                except Exception:
                    pass

        # Recalcular valores com dados atualizados
        valores = [c["valor"] for c in compras if c.get("valor") and c["valor"] > 0]
        if valores:
            valor_total = sum(valores)
            valor_medio = valor_total / len(valores)

        # Reputação estruturada (RF-033)
        esfera = "Federal" if any(p in nome_orgao.upper() for p in ["MINISTERIO", "FEDERAL", "NACIONAL"]) else "Estadual" if any(p in nome_orgao.upper() for p in ["ESTADO", "ESTADUAL", "SECRETARIA DE ESTADO"]) else "Municipal"
        reputacao = {
            "esfera": esfera,
            "risco_pagamento": "Baixo" if esfera == "Federal" else "Médio" if esfera == "Estadual" else "Alto",
            "volume": "Alto" if len(compras) > 100 else "Médio" if len(compras) > 20 else "Baixo",
            "modalidade_principal": max(modalidades, key=modalidades.get) if modalidades else "N/A",
            "percentual_pregao": round(modalidades.get("Pregão - Eletrônico", 0) / max(len(compras), 1) * 100, 1),
            "editais_similares": len(similares),
        }

        # Histórico interno
        hist_interno = _calcular_historico_interno(db, nome_orgao, user_id)

        # === Análise IA ===
        analise_ia_texto = ""
        try:
            # CV12-7 (Arnaldo Sprint 2 V8): antes a IA recebia so o tipo de orgao
            # ("baseado em federal/estadual/municipal") e inventava o veredito —
            # respondia "risco baixo" mesmo quando a aba Reputacao mostrava
            # "Alto" em vermelho. Agora passamos o valor JA CALCULADO
            # (reputacao['risco_pagamento']) e mandamos a IA RESPEITAR — nao
            # recalcular nem contradizer.
            prompt_mercado = f"""Analise o perfil deste órgão contratante para licitações:

ÓRGÃO: {nome_orgao}
CNPJ: {cnpj_orgao or 'N/A'}
UF: {uf_orgao}
ESFERA: {reputacao['esfera']}

DADOS DO PNCP:
- Total de compras encontradas: {len(compras)}
- Valor total: R$ {valor_total:,.2f}
- Valor médio por compra: R$ {valor_medio:,.2f}
- Modalidades: {json.dumps(modalidades, ensure_ascii=False)}
- Compras similares ao objeto "{edital.objeto[:50]}": {len(similares)}

HISTÓRICO INTERNO DO SISTEMA:
- Editais deste órgão no sistema: {hist_interno.get('total', 0)}
- Decisões GO: {hist_interno.get('go', 0)} | NO-GO: {hist_interno.get('nogo', 0)}

VALORES JÁ CALCULADOS PELO SISTEMA (use-os como verdade absoluta — não recalcule, não contradiga):
- Risco de pagamento: **{reputacao['risco_pagamento']}** (já derivado da esfera {reputacao['esfera']})
- Volume de contratações: **{reputacao['volume']}**
- Modalidade principal: **{reputacao['modalidade_principal']}**

Gere uma análise concisa (3-5 frases) sobre:
1. Perfil do órgão (volume, tipo de compras, porte) — coerente com os valores acima
2. Risco de pagamento — **OBRIGATÓRIO repetir "{reputacao['risco_pagamento']}"** e explicar por que (não invente outro valor)
3. Oportunidades (recorrência, volume, segmento)
4. Recomendação (vale a pena investir neste órgão?)

Responda APENAS o texto da análise, sem JSON."""

            analise_ia_texto = call_deepseek([{"role": "user", "content": prompt_mercado}], max_tokens=1000, model_override="deepseek-chat")
            analise_ia_texto = analise_ia_texto.strip()
        except Exception as e:
            analise_ia_texto = f"Erro na análise IA: {e}"

        # === Salvar no banco ===
        if perfil_db:
            perfil_db.nome = nome_orgao
            perfil_db.uf = uf_orgao
            perfil_db.total_compras = len(compras)
            perfil_db.valor_total_compras = valor_total
            perfil_db.valor_medio_compras = valor_medio
            perfil_db.modalidades_frequentes = modalidades
            perfil_db.compras_similares = similares[:10]
            perfil_db.analise_ia = analise_ia_texto
            perfil_db.ultima_atualizacao = datetime.now()
        else:
            perfil_db = OrgaoPerfil(
                id=str(uuid.uuid4()),
                cnpj=(cnpj_orgao or f"sc_{nome_orgao}")[:20],
                nome=nome_orgao,
                uf=uf_orgao,
                total_compras=len(compras),
                valor_total_compras=valor_total,
                valor_medio_compras=valor_medio,
                modalidades_frequentes=modalidades,
                compras_similares=similares[:10],
                analise_ia=analise_ia_texto,
                ultima_atualizacao=datetime.now(),
                user_id=user_id,
            )
            db.add(perfil_db)

        db.commit()
        print(f"[MERCADO] Perfil salvo: {nome_orgao}, {len(compras)} compras, {len(similares)} similares")

        return jsonify({
            "success": True,
            "cache": False,
            "orgao": {"nome": nome_orgao, "cnpj": cnpj_orgao, "uf": uf_orgao},
            "estatisticas": {
                "total_compras": len(compras),
                "valor_total": valor_total,
                "valor_medio": valor_medio,
                "modalidades": modalidades,
            },
            "compras_similares": similares[:10],
            "reputacao": reputacao,
            "historico_interno": hist_interno,
            "analise_ia": analise_ia_texto,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


def _calcular_historico_interno(db, nome_orgao, user_id):
    """Calcula decisões internas GO/NO-GO para um órgão."""
    empresa_id = get_current_empresa_id()
    try:
        editais_orgao = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.orgao.ilike(f"%{nome_orgao[:20]}%"),
            Edital.status != "temp_score",
        ).all()
        total = len(editais_orgao)
        go = sum(1 for e in editais_orgao if e.status == "go")
        nogo = sum(1 for e in editais_orgao if e.status == "nogo")
        avaliando = sum(1 for e in editais_orgao if e.status == "avaliando")
        return {"total": total, "go": go, "nogo": nogo, "avaliando": avaliando}
    except Exception:
        return {"total": 0, "go": 0, "nogo": 0, "avaliando": 0}


@app.route("/api/editais/<edital_id>/analisar-riscos", methods=["POST"])
@require_auth
def analisar_riscos_edital(edital_id):
    """Análise completa de riscos: PDF via IA + atas + vencedores + concorrentes."""
    from models import Edital, EditalDocumento, Concorrente, PrecoHistorico, Produto, AtaConsultada
    from tools import _extrair_json_object, tool_buscar_atas_pncp
    import requests as req
    import re as _re
    from datetime import datetime

    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        edital = db.query(Edital).filter(Edital.id == edital_id, Edital.empresa_id == empresa_id).first()
        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404

        # === PASSO 1: Identificar produto match ===
        produto_match = None
        analise_existente = db.query(Analise).filter(Analise.edital_id == edital_id, Analise.empresa_id == empresa_id).first()
        if analise_existente and analise_existente.produto_id:
            produto_match = db.query(Produto).filter(Produto.id == analise_existente.produto_id).first()
        if not produto_match:
            produto_match = db.query(Produto).filter(Produto.empresa_id == empresa_id).first()

        empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()

        # === PASSO 2: Buscar atas no PNCP ===
        # Usar palavras-chave do objeto (mesmo critério do endpoint historico-vencedores)
        import re as _re2
        objeto = edital.objeto or ""
        palavras_stop = {"aquisicao", "aquisição", "de", "do", "da", "dos", "das", "para", "com", "registro", "preco", "preço", "futura", "eventual", "fornecimento"}
        palavras = [w for w in _re2.sub(r'[^\w\s]', ' ', objeto.lower()).split() if w not in palavras_stop and len(w) > 3][:3]
        termo_ata = " ".join(palavras) if palavras else (produto_match.nome if produto_match else objeto[:30])
        print(f"[RISCOS] Buscando atas para: {termo_ata}")
        atas_resultado = tool_buscar_atas_pncp(termo_ata, user_id)
        atas = atas_resultado.get("atas", []) if atas_resultado.get("success") else []
        print(f"[RISCOS] {len(atas)} atas encontradas")

        # === PASSO 3: Buscar vencedores e preços das atas ===
        vencedores_todos = []
        cnpjs_processados = {}
        salvos_concorrentes = 0
        salvos_precos = 0

        salvos_atas = 0
        for ata in atas[:5]:
            cnpj = ata.get("cnpj_orgao") or ""
            ano = ata.get("ano")
            url_pncp = ata.get("url_pncp") or ""
            match_url = _re.search(r'/atas/\d+/\d+/(\d+)/\d+', url_pncp)
            seq_compra = int(match_url.group(1)) if match_url else None
            if not cnpj or not ano or not seq_compra:
                continue

            # Salvar ata no banco (evitar duplicata por numero_controle)
            nc = ata.get("numero_controle") or ""
            ata_db = db.query(AtaConsultada).filter(AtaConsultada.numero_controle_pncp == nc).first() if nc else None
            if not ata_db:
                url_edital_origem = f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq_compra}"
                dp = ata.get("data_publicacao")
                dt_pub = None
                if dp:
                    try:
                        dt_pub = datetime.fromisoformat(str(dp).replace("Z", "")[:19])
                    except (ValueError, TypeError):
                        pass
                ata_db = AtaConsultada(
                    id=str(uuid.uuid4()),
                    edital_id=edital_id,
                    user_id=user_id,
                    numero_controle_pncp=nc or None,
                    titulo=ata.get("titulo"),
                    orgao=ata.get("orgao"),
                    cnpj_orgao=cnpj,
                    uf=ata.get("uf"),
                    ano=ano,
                    seq_compra=seq_compra,
                    url_pncp=url_pncp,
                    url_edital_origem=url_edital_origem,
                    data_publicacao=dt_pub,
                )
                db.add(ata_db)
                db.flush()
                salvos_atas += 1
            try:
                url_itens = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq_compra}/itens"
                resp = req.get(url_itens, timeout=15, headers={"Accept": "application/json"})
                if resp.status_code != 200:
                    continue
                itens = resp.json()
                if not isinstance(itens, list):
                    continue
                vencedores_ata = []
                for item in itens[:10]:
                    num_item = item.get("numeroItem")
                    if not num_item:
                        continue
                    try:
                        url_r = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq_compra}/itens/{num_item}/resultados"
                        resp_r = req.get(url_r, timeout=10, headers={"Accept": "application/json"})
                        if resp_r.status_code == 200:
                            res_item = resp_r.json()
                            if isinstance(res_item, list) and res_item:
                                r = res_item[0]
                                cnpj_venc = (r.get("niFornecedor") or "").replace(".", "").replace("/", "").replace("-", "")
                                nome_venc = r.get("nomeRazaoSocialFornecedor")
                                vencedores_ata.append({
                                    "item": num_item,
                                    "descricao": str(item.get("descricao", ""))[:80],
                                    "quantidade": item.get("quantidade"),
                                    "valor_estimado": item.get("valorUnitarioEstimado"),
                                    "vencedor": nome_venc,
                                    "cnpj_vencedor": cnpj_venc,
                                    "valor_homologado": r.get("valorUnitarioHomologado"),
                                    "qtd_homologada": r.get("quantidadeHomologada"),
                                    "valor_total_homologado": r.get("valorTotalHomologado"),
                                    "porte": r.get("porteFornecedorNome"),
                                })
                                # Salvar concorrente
                                if nome_venc and cnpj_venc:
                                    conc = cnpjs_processados.get(cnpj_venc)
                                    if not conc:
                                        conc = db.query(Concorrente).filter(Concorrente.cnpj == cnpj_venc).first()
                                    if not conc:
                                        conc = Concorrente(id=str(uuid.uuid4()), nome=nome_venc, cnpj=cnpj_venc, editais_participados=1, editais_ganhos=1)
                                        db.add(conc)
                                        db.flush()
                                        salvos_concorrentes += 1
                                    else:
                                        conc.editais_participados = (conc.editais_participados or 0) + 1
                                        conc.editais_ganhos = (conc.editais_ganhos or 0) + 1
                                    cnpjs_processados[cnpj_venc] = conc
                                    # Salvar preço histórico
                                    try:
                                        ph = PrecoHistorico(
                                            id=str(uuid.uuid4()), edital_id=edital_id, user_id=user_id,
                                            empresa_id=empresa_id, concorrente_id=conc.id,
                                            produto_id=produto_match.id if produto_match else None,
                                            ata_consultada_id=ata_db.id,
                                            preco_referencia=item.get("valorUnitarioEstimado"),
                                            preco_vencedor=r.get("valorUnitarioHomologado"),
                                            empresa_vencedora=nome_venc, cnpj_vencedor=cnpj_venc,
                                            resultado="derrota", fonte="pncp", data_registro=datetime.now(),
                                        )
                                        if item.get("valorUnitarioEstimado") and r.get("valorUnitarioHomologado") and item["valorUnitarioEstimado"] > 0:
                                            ph.desconto_percentual = round((1 - r["valorUnitarioHomologado"] / item["valorUnitarioEstimado"]) * 100, 2)
                                        db.add(ph)
                                        salvos_precos += 1
                                    except Exception:
                                        pass
                    except Exception:
                        pass
                if vencedores_ata:
                    vencedores_todos.append({
                        "ata_titulo": ata.get("titulo") or f"Ata {ano}",
                        "orgao": ata.get("orgao"), "uf": ata.get("uf"),
                        "vencedores": vencedores_ata,
                    })
            except Exception:
                pass

        # Commit concorrentes e preços
        try:
            db.commit()
            print(f"[RISCOS] Salvos: {salvos_atas} atas, {salvos_concorrentes} concorrentes, {salvos_precos} preços")
        except Exception:
            db.rollback()

        # === PASSO 4: Calcular recorrência ===
        datas = []
        for ata in atas:
            dp = ata.get("data_publicacao") or ata.get("data_assinatura")
            if dp:
                try:
                    dt = datetime.fromisoformat(str(dp).replace("Z", "")[:19])
                    datas.append(dt)
                except (ValueError, TypeError):
                    pass
        frequencia = None
        if len(datas) >= 2:
            datas.sort()
            diffs = [(datas[i+1] - datas[i]).days for i in range(len(datas)-1)]
            media_dias = sum(diffs) / len(diffs) if diffs else 0
            frequencia = "semestral" if media_dias <= 200 else "anual" if media_dias <= 400 else "esporadica"

        # === PASSO 5: Montar contexto competitivo para IA ===
        contexto_competitivo = ""
        if vencedores_todos:
            nomes_venc = {}
            for va in vencedores_todos:
                for v in va["vencedores"]:
                    n = v.get("vencedor", "")
                    if n:
                        nomes_venc[n] = nomes_venc.get(n, 0) + 1
            top_conc = sorted(nomes_venc.items(), key=lambda x: -x[1])[:3]
            contexto_competitivo = f"\n\nCONTEXTO COMPETITIVO:\n"
            contexto_competitivo += f"- {len(atas)} atas encontradas no PNCP para produto similar\n"
            if frequencia:
                contexto_competitivo += f"- Recorrência: {frequencia}\n"
            for nome, cnt in top_conc:
                contexto_competitivo += f"- Concorrente: {nome} ({cnt} vitória(s))\n"

        # === PASSO 6: Análise via IA do PDF ===
        doc = db.query(EditalDocumento).filter(
            EditalDocumento.edital_id == edital_id,
            EditalDocumento.texto_extraido != None
        ).first()

        analise_ia = {}
        if doc and doc.texto_extraido and len(doc.texto_extraido) >= 200:
            prompt = f"""Você é um especialista em análise de riscos em editais de licitação pública brasileira.

Analise o texto do edital abaixo e extraia uma análise completa de riscos.
{contexto_competitivo}
Retorne APENAS um JSON válido (sem texto adicional) com esta estrutura:
{{
  "modalidade": "tipo da modalidade",
  "prazo_pagamento": "prazo de pagamento ou 'Não informado'",
  "sinais_mercado": ["sinais relevantes detectados"],
  "riscos": [{{"tipo": "juridico|tecnico|financeiro|logistico", "descricao": "...", "severidade": "alto|medio|baixo", "mitigacao": "..."}}],
  "fatal_flaws": ["problemas CRÍTICOS que impedem participação"],
  "flags_juridicos": ["cláusulas restritivas"],
  "trechos_relevantes": [{{"trecho": "trecho do edital (máx 150 chars)", "tipo": "risco|oportunidade|alerta", "comentario": "comentário analítico"}}]
}}

REGRAS:
- 3-5 riscos de diferentes categorias. Se há dados competitivos, inclua riscos de concorrência.
- Fatal flaws são RAROS
- 3-8 trechos relevantes
- Mitigações objetivas e práticas

TEXTO DO EDITAL:
{doc.texto_extraido[:20000]}

ANÁLISE DE RISCOS (JSON):"""

            resposta = call_deepseek([{"role": "user", "content": prompt}], max_tokens=8000, model_override="deepseek-chat")
            analise_ia = _extrair_json_object(resposta)

        # === PASSO 7: Carregar concorrentes do banco ===
        concorrentes_db = db.query(Concorrente).order_by(Concorrente.editais_ganhos.desc()).limit(20).all()
        concorrentes_lista = [{
            "nome": c.nome, "cnpj": c.cnpj,
            "editais_participados": c.editais_participados or 0,
            "editais_ganhos": c.editais_ganhos or 0,
            "taxa_vitoria": round((c.editais_ganhos or 0) / max(c.editais_participados or 1, 1) * 100, 1),
        } for c in concorrentes_db]

        # === RETORNAR TUDO ===
        return jsonify({
            "success": True,
            # Análise IA
            **analise_ia,
            # Atas
            "atas": atas[:10],
            "frequencia": frequencia,
            "termo_ata": termo_ata,
            # Vencedores
            "vencedores_resultados": vencedores_todos,
            # Concorrentes
            "concorrentes": concorrentes_lista,
            # Salvos
            "salvos": {"atas": salvos_atas, "concorrentes": salvos_concorrentes, "precos": salvos_precos},
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/editais/<edital_id>/historico-vencedores", methods=["POST"])
@require_auth
def historico_vencedores_edital(edital_id):
    """Busca atas de registro de preço no PNCP para o mesmo objeto do edital, identificando vencedores anteriores."""
    from tools import tool_buscar_atas_pncp
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        edital = db.query(Edital).filter(Edital.id == edital_id, Edital.empresa_id == empresa_id).first()
        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404

        # Extrair termo de busca do objeto do edital (primeiras 3 palavras significativas)
        import re
        objeto = edital.objeto or ""
        palavras_stop = {"aquisicao", "aquisição", "de", "do", "da", "dos", "das", "para", "com", "registro", "preco", "preço", "futura", "eventual", "fornecimento"}
        palavras = [w for w in re.sub(r'[^\w\s]', ' ', objeto.lower()).split() if w not in palavras_stop and len(w) > 3][:3]
        termo = " ".join(palavras) if palavras else objeto[:30]

        resultado = tool_buscar_atas_pncp(termo, user_id)

        if resultado.get("success"):
            atas = resultado.get("atas", [])
            # Enriquecer: tentar identificar frequência
            datas = []
            for ata in atas:
                dp = ata.get("data_publicacao") or ata.get("data_assinatura")
                if dp:
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(str(dp).replace("Z", "")[:19])
                        datas.append(dt)
                    except (ValueError, TypeError):
                        pass

            frequencia = None
            if len(datas) >= 2:
                datas.sort()
                diffs = [(datas[i+1] - datas[i]).days for i in range(len(datas)-1)]
                media_dias = sum(diffs) / len(diffs) if diffs else 0
                if media_dias <= 200:
                    frequencia = "semestral"
                elif media_dias <= 400:
                    frequencia = "anual"
                else:
                    frequencia = "esporadica"

            return jsonify({
                "success": True,
                "termo": termo,
                "total": resultado.get("total", len(atas)),
                "atas": atas[:10],
                "frequencia": frequencia,
            })
        else:
            return jsonify({"success": False, "error": resultado.get("error", "Nenhuma ata encontrada"), "termo": termo})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/concorrentes/listar", methods=["GET"])
@require_auth
def listar_concorrentes_api():
    """Lista concorrentes cadastrados com estatísticas."""
    from models import Concorrente
    db = get_db()
    try:
        concorrentes = db.query(Concorrente).order_by(Concorrente.editais_ganhos.desc()).limit(20).all()
        return jsonify({
            "success": True,
            "total": len(concorrentes),
            "concorrentes": [{
                "id": c.id,
                "nome": c.nome,
                "cnpj": c.cnpj,
                "editais_participados": c.editais_participados or 0,
                "editais_ganhos": c.editais_ganhos or 0,
                "taxa_vitoria": round((c.editais_ganhos or 0) / max(c.editais_participados or 1, 1) * 100, 1),
                "preco_medio": float(c.preco_medio) if c.preco_medio else None,
            } for c in concorrentes],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/editais/<edital_id>/vencedores-atas", methods=["POST"])
@require_auth
def vencedores_atas_edital(edital_id):
    """Busca vencedores e preços das atas encontradas para o edital."""
    from tools import tool_extrair_vencedores_atas
    user_id = get_current_user_id()
    data = request.get_json(silent=True) or {}
    atas = data.get("atas", [])
    if not atas:
        return jsonify({"error": "Nenhuma ata fornecida"}), 400
    resultado = tool_extrair_vencedores_atas(atas=atas, user_id=user_id, edital_id=edital_id)
    return jsonify(resultado)


@app.route("/api/editais/<edital_id>/extrair-requisitos", methods=["POST"])
@require_auth
def extrair_requisitos_edital(edital_id):
    """
    Extrai requisitos (técnicos, documentais, comerciais) do PDF já baixado do edital.
    Chamado pela aba Documentos quando o edital tem PDF mas não tem requisitos extraídos.
    """
    from models import Edital, EditalDocumento, EditalRequisito
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()

    db = get_db()
    try:
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()
        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404

        # Verificar se já tem requisitos extraídos
        forcar = request.get_json(silent=True) or {}
        forcar = forcar.get("forcar", False)
        requisitos_existentes = db.query(EditalRequisito).filter(
            EditalRequisito.edital_id == edital_id
        ).count()
        if requisitos_existentes > 0 and not forcar:
            return jsonify({
                "success": True,
                "message": f"Edital já possui {requisitos_existentes} requisitos extraídos",
                "requisitos_extraidos": requisitos_existentes,
                "ja_existia": True,
            })

        # Se forçar, deletar requisitos antigos
        if forcar and requisitos_existentes > 0:
            db.query(EditalRequisito).filter(EditalRequisito.edital_id == edital_id).delete()
            db.commit()
            print(f"[EXTRAIR-REQUISITOS] Removidos {requisitos_existentes} requisitos antigos (forcar=True)")

        # Buscar texto do PDF do edital
        doc = db.query(EditalDocumento).filter(
            EditalDocumento.edital_id == edital_id,
            EditalDocumento.texto_extraido != None
        ).first()

        if not doc or not doc.texto_extraido or len(doc.texto_extraido) < 200:
            return jsonify({
                "error": "Edital não possui PDF com texto extraído. Baixe o PDF primeiro.",
                "sem_pdf": True,
            }), 400

        # Extrair requisitos via IA
        resultado = tool_extrair_requisitos(edital_id, doc.texto_extraido, user_id, empresa_id=empresa_id)

        if resultado.get("success"):
            return jsonify({
                "success": True,
                "requisitos_extraidos": resultado.get("requisitos_extraidos", 0),
                "categoria": resultado.get("categoria"),
            })
        else:
            return jsonify({"error": resultado.get("error", "Erro na extração")}), 500

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# B7: SICONV como fonte de busca de editais
# (Implementado em tools.py — parser + integração via scraper web)
# =============================================================================


# =============================================================================
# B8: Busca automática de certidões (portais oficiais)
# =============================================================================


def _tentar_obter_certidao(fonte, cnpj_limpo, empresa, upload_dir):
    """
    Tenta obter a certidão automaticamente via HTTP nos portais públicos.
    Retorna dict com {sucesso, path_arquivo, numero, data_vencimento, mensagem, dados_extras}.

    Testado em 10/03/2026 — resultados reais:

    BUSCA AUTOMÁTICA REAL (sem captcha):
    1. CGU Certidão Correcional — API REST, consolida CEIS+CNEP+CEPIM+CGU-PJ+ePAD
    2. CRF/FGTS (Caixa)        — JSF sem captcha, retorna Regular/Irregular
    3. BrasilAPI CNPJ           — REST gratuita, dados cadastrais + Simples Nacional
    4. API Portal Transparência — REST oficial (requer chave gratuita)

    CAPTCHA (upload manual obrigatório):
    5. CND Federal (Receita)    — URL antiga MORTA (404), migrou para e-CAC com login gov.br
    6. CNDT/TST                 — Captcha próprio (imagem+áudio)
    7. CND Estadual (SEFAZ)     — reCAPTCHA v2 (SP) ou hCaptcha (varia)
    8. CND Municipal            — Varia por município, maioria com captcha
    """
    import requests
    from datetime import date, datetime, timedelta
    import json as json_lib
    import re
    import time

    nome_lower = fonte.nome.lower()
    tipo = fonte.tipo_certidao or ''
    resultado = {
        "sucesso": False, "mensagem": "", "path_arquivo": None,
        "numero": None, "data_vencimento": None, "dados_extras": None
    }

    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html, */*",
    }

    try:
        os.makedirs(upload_dir, exist_ok=True)

        # ═══════════════════════════════════════════════════════════════════
        # 1. CGU CERTIDÃO CORRECIONAL — Consolida CEIS+CNEP+CEPIM+CGU-PJ+ePAD
        #    API pública, SEM captcha, SEM chave. Testado: FUNCIONA.
        # ═══════════════════════════════════════════════════════════════════
        if any(k in nome_lower for k in ['cgu', 'correcional', 'ceis', 'cnep', 'cepim']):
            try:
                # Passo 1: Solicitar consulta
                resp1 = requests.post(
                    "https://certidoes.cgu.gov.br/api/publico/consulta-responsabilizacao",
                    json={
                        "cpfCnpj": [cnpj_limpo],
                        "certidoes": [8],  # ID=8 = Entes Privados (CNPJ)
                        "captcha": "",
                        "idTipoNatureza": 0,
                        "isConsultaReceita": False,
                    },
                    headers=HEADERS,
                    timeout=20,
                )
                if resp1.status_code != 200:
                    resultado["mensagem"] = f"CGU: Erro ao solicitar consulta (HTTP {resp1.status_code})"
                    return resultado

                ids = resp1.json()
                if not ids or not isinstance(ids, list):
                    resultado["mensagem"] = "CGU: Resposta inesperada ao solicitar consulta"
                    return resultado

                result_id = ids[0]

                # Passo 2: Obter resultado (pode levar alguns segundos)
                for tentativa in range(5):
                    time.sleep(1)
                    resp2 = requests.get(
                        f"https://certidoes.cgu.gov.br/api/publico/resultado-consulta-responsabilizacao/{result_id}",
                        headers=HEADERS,
                        timeout=20,
                    )
                    if resp2.status_code == 200:
                        dados = resp2.json()
                        if dados and isinstance(dados, list) and len(dados) > 0:
                            break
                else:
                    resultado["mensagem"] = "CGU: Timeout aguardando resultado da consulta"
                    return resultado

                consulta = dados[0]
                certidoes_result = consulta.get("consultasCertidoes", [])

                # Analisar resultados
                todas_nada_consta = True
                detalhes = []
                for cert_r in certidoes_result:
                    for ws in cert_r.get("consultasWebservices", []):
                        ws_nome = ws.get("nomeWebservice", "")
                        ws_tipo = ws.get("tipoRetornoWebservice", "")
                        detalhes.append(f"{ws_nome}: {ws_tipo}")
                        if ws_tipo != "NADA_CONSTA":
                            todas_nada_consta = False

                nome_encontrado = consulta.get("nomeRequerente", "")
                data_consulta = consulta.get("dataHoraConsulta", "")

                if todas_nada_consta:
                    resultado["sucesso"] = True
                    resultado["data_vencimento"] = (date.today() + timedelta(days=180)).isoformat()
                    resultado["numero"] = f"CGU-{result_id[:8]}"
                    resultado["mensagem"] = f"CGU Certidão Correcional: NADA CONSTA ({', '.join(detalhes)})"
                else:
                    resultado["mensagem"] = f"CGU: ATENÇÃO — Registros encontrados: {', '.join(detalhes)}"

                resultado["dados_extras"] = json_lib.dumps({
                    "nome_encontrado": nome_encontrado,
                    "data_consulta": data_consulta,
                    "webservices": detalhes,
                    "certidao_negativa": todas_nada_consta,
                }, ensure_ascii=False)
                return resultado

            except requests.exceptions.Timeout:
                resultado["mensagem"] = "CGU: Timeout — tente novamente"
            except Exception as e:
                resultado["mensagem"] = f"CGU: Erro — {str(e)[:100]}"
            return resultado

        # ═══════════════════════════════════════════════════════════════════
        # 2. CRF/FGTS — Caixa Econômica — Automação via Playwright
        #    ShieldSquare anti-bot: Playwright executa o JS challenge.
        #    Fallback: mensagem de upload manual.
        # ═══════════════════════════════════════════════════════════════════
        if 'fgts' in nome_lower or 'crf' in nome_lower or 'caixa' in nome_lower or tipo == 'fgts':
            try:
                from certidao_browser import buscar_fgts_browser
                print(f"[CERTIDAO] FGTS: Tentando automação via Playwright...")
                resultado_browser = buscar_fgts_browser(cnpj_limpo, upload_dir)
                if resultado_browser.get("sucesso") or resultado_browser.get("dados_extras"):
                    return resultado_browser
                # Falhou — usar mensagem do browser como fallback
                resultado["mensagem"] = resultado_browser.get("mensagem", "")
            except ImportError:
                pass
            except Exception as e:
                print(f"[CERTIDAO] FGTS browser erro: {e}")

            if not resultado["mensagem"]:
                resultado["mensagem"] = (
                    "FGTS/CRF: Automação indisponível. "
                    "Acesse https://consulta-crf.caixa.gov.br/consultacrf/pages/consultaEmpregador.jsf, "
                    "informe o CNPJ e faça upload do PDF. Validade: 30 dias."
                )
            return resultado

        # ═══════════════════════════════════════════════════════════════════
        # 3. BrasilAPI CNPJ — Dados cadastrais + Simples Nacional (GRATUITA)
        # ═══════════════════════════════════════════════════════════════════
        if 'brasilapi' in nome_lower or 'cnpj' in nome_lower or 'situação cadastral' in nome_lower or 'situacao cadastral' in nome_lower:
            try:
                resp = requests.get(
                    f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_limpo}",
                    headers=HEADERS,
                    timeout=15,
                )
                if resp.status_code == 200:
                    dados = resp.json()
                    situacao = dados.get("descricao_situacao_cadastral", "")
                    simples = dados.get("opcao_pelo_simples", False)
                    razao = dados.get("razao_social", "")

                    if situacao.upper() == "ATIVA":
                        resultado["sucesso"] = True
                        resultado["mensagem"] = f"CNPJ: Situação ATIVA — {razao}. Simples: {'Sim' if simples else 'Não'}"
                        resultado["data_vencimento"] = (date.today() + timedelta(days=30)).isoformat()
                    else:
                        resultado["mensagem"] = f"CNPJ: Situação '{situacao}' — {razao}"

                    resultado["dados_extras"] = json_lib.dumps({
                        "razao_social": razao,
                        "situacao": situacao,
                        "simples_nacional": simples,
                        "uf": dados.get("uf"),
                        "municipio": dados.get("municipio"),
                        "cnae_fiscal": dados.get("cnae_fiscal"),
                        "cnae_descricao": dados.get("cnae_fiscal_descricao"),
                        "porte": dados.get("porte"),
                        "capital_social": dados.get("capital_social"),
                        "socios": [s.get("nome_socio") for s in dados.get("qsa", [])],
                    }, ensure_ascii=False)
                    return resultado
                else:
                    resultado["mensagem"] = f"BrasilAPI: HTTP {resp.status_code}"
            except requests.exceptions.Timeout:
                resultado["mensagem"] = "BrasilAPI: Timeout"
            except Exception as e:
                resultado["mensagem"] = f"BrasilAPI: Erro — {str(e)[:100]}"
            return resultado

        # ═══════════════════════════════════════════════════════════════════
        # 4. API OFICIAL Portal da Transparência (requer chave gratuita)
        #    Cadastro em: portaldatransparencia.gov.br/api-de-dados/cadastrar-email
        #    Header: chave-api-dados
        # ═══════════════════════════════════════════════════════════════════
        if any(k in nome_lower for k in ['transparência', 'transparencia', 'portal transparencia']):
            chave_api = fonte.api_key or ""
            if not chave_api:
                resultado["mensagem"] = (
                    "Portal da Transparência API: Chave API não configurada. "
                    "Cadastre-se gratuitamente em https://portaldatransparencia.gov.br/api-de-dados/cadastrar-email "
                    "e configure a chave na fonte de certidão."
                )
                return resultado

            try:
                api_base = "https://api.portaldatransparencia.gov.br/api-de-dados"
                api_headers = {**HEADERS, "chave-api-dados": chave_api}
                resultados_api = {}

                for cadastro, param in [("ceis", "codigoSancionado"), ("cnep", "codigoSancionado"), ("cepim", "cnpjSancionado")]:
                    resp = requests.get(
                        f"{api_base}/{cadastro}",
                        params={param: cnpj_limpo, "pagina": 1},
                        headers=api_headers,
                        timeout=15,
                    )
                    if resp.status_code == 200:
                        dados = resp.json()
                        registros = dados if isinstance(dados, list) else dados.get("data", [])
                        resultados_api[cadastro.upper()] = len(registros)
                    elif resp.status_code == 401:
                        resultado["mensagem"] = "Portal da Transparência: Chave API inválida"
                        return resultado
                    else:
                        resultados_api[cadastro.upper()] = f"HTTP {resp.status_code}"

                todas_limpo = all(v == 0 for v in resultados_api.values() if isinstance(v, int))
                if todas_limpo:
                    resultado["sucesso"] = True
                    resultado["data_vencimento"] = (date.today() + timedelta(days=180)).isoformat()
                    resultado["mensagem"] = f"Portal Transparência: NADA CONSTA ({', '.join(f'{k}:0' for k in resultados_api)})"
                else:
                    resultado["mensagem"] = f"Portal Transparência: {', '.join(f'{k}:{v}' for k, v in resultados_api.items())}"

                resultado["dados_extras"] = json_lib.dumps(resultados_api, ensure_ascii=False)
                return resultado

            except Exception as e:
                resultado["mensagem"] = f"Portal Transparência API: Erro — {str(e)[:100]}"
            return resultado

        # ═══════════════════════════════════════════════════════════════════
        # 5. CND FEDERAL (Receita Federal / PGFN) — MANUAL
        #    Portal exige hCaptcha invisível (domínios gov.br bloqueados por solvers)
        # ═══════════════════════════════════════════════════════════════════
        if tipo == 'cnd_federal' or 'receita federal' in nome_lower or 'cnd federal' in nome_lower or 'pgfn' in nome_lower:
            resultado["mensagem"] = (
                "CND Federal: Busca automática não disponível — portal da Receita exige hCaptcha "
                "que não pode ser resolvido automaticamente. "
                "Acesse https://servicos.receitafederal.gov.br/servico/certidoes/, "
                "selecione Pessoa Jurídica, informe o CNPJ e clique Emitir Certidão. "
                "Faça upload do PDF — a IA extrai os dados automaticamente."
            )
            resultado["dados_extras"] = {
                "Método": "MANUAL — hCaptcha gov.br não suportado por solvers",
                "Portal": "https://servicos.receitafederal.gov.br/servico/certidoes/",
                "Procedimento": "Selecionar Pessoa Jurídica → Informar CNPJ → Emitir Certidão → Upload PDF",
                "Validade": "180 dias",
            }
            return resultado

        # ═══════════════════════════════════════════════════════════════════
        # 6. CNDT/TST — Automação via Playwright + CapSolver (captcha imagem)
        # ═══════════════════════════════════════════════════════════════════
        if 'cndt' in nome_lower or 'tst' in nome_lower or tipo == 'trabalhista':
            try:
                from certidao_browser import buscar_tst_browser
                from config import CAPSOLVER_API_KEY as _cap_key
                if _cap_key:
                    print(f"[CERTIDAO] TST: Tentando automação via Playwright + CapSolver...")
                    resultado_browser = buscar_tst_browser(cnpj_limpo, upload_dir)
                    if resultado_browser.get("sucesso") or resultado_browser.get("dados_extras"):
                        return resultado_browser
                    resultado["mensagem"] = resultado_browser.get("mensagem", "")
            except ImportError:
                pass
            except Exception as e:
                print(f"[CERTIDAO] TST browser erro: {e}")

            if not resultado["mensagem"]:
                resultado["mensagem"] = (
                    "CNDT/TST: Automação indisponível (CapSolver não configurado ou falha). "
                    "Acesse https://cndt-certidao.tst.jus.br/gerarCertidao.faces, "
                    "informe o CNPJ formatado, resolva o captcha e faça upload do PDF."
                )
            return resultado

        # ═══════════════════════════════════════════════════════════════════
        # 7. CND ESTADUAL (SEFAZ) — Automação via Playwright + CapSolver
        # ═══════════════════════════════════════════════════════════════════
        if tipo == 'cnd_estadual' or 'sefaz' in nome_lower or 'cnd estadual' in nome_lower:
            uf = fonte.uf or (empresa.uf if hasattr(empresa, 'uf') else '')
            url_sefaz = fonte.url_portal or (f"https://www.sefaz.{uf.lower()}.gov.br" if uf else "")

            try:
                from certidao_browser import buscar_sefaz_browser
                from config import CAPSOLVER_API_KEY as _cap_key
                if _cap_key and url_sefaz:
                    ie = fonte.cnpj_consulta or ""  # IE pode estar no cnpj_consulta
                    print(f"[CERTIDAO] SEFAZ-{uf}: Tentando automação via Playwright + CapSolver...")
                    resultado_browser = buscar_sefaz_browser(cnpj_limpo, uf, url_sefaz, upload_dir, ie)
                    if resultado_browser.get("sucesso") or resultado_browser.get("dados_extras"):
                        return resultado_browser
                    resultado["mensagem"] = resultado_browser.get("mensagem", "")
            except ImportError:
                pass
            except Exception as e:
                print(f"[CERTIDAO] SEFAZ browser erro: {e}")

            if not resultado["mensagem"]:
                resultado["mensagem"] = (
                    f"CND Estadual ({uf or 'UF?'}): Automação indisponível. "
                    f"Acesse {url_sefaz}, informe CNPJ + Inscrição Estadual, "
                    "resolva o captcha e faça upload do PDF."
                )
            return resultado

        # ═══════════════════════════════════════════════════════════════════
        # 8. CND MUNICIPAL — Varia por município
        # ═══════════════════════════════════════════════════════════════════
        if tipo == 'cnd_municipal' or 'municipal' in nome_lower or 'prefeitura' in nome_lower:
            cidade = fonte.cidade or (empresa.cidade if hasattr(empresa, 'cidade') else '')
            url_pref = fonte.url_portal or ""
            resultado["mensagem"] = (
                f"CND Municipal ({cidade or 'cidade?'}): Acesse o portal da prefeitura"
                f"{' em ' + url_pref if url_pref else ''}, "
                "informe CNPJ + Inscrição Municipal (CCM) e faça upload do PDF."
            )
            return resultado

        # ═══════════════════════════════════════════════════════════════════
        # FALLBACK — Orientação genérica
        # ═══════════════════════════════════════════════════════════════════
        url_portal = fonte.url_portal or ""
        resultado["mensagem"] = (
            f"Acesse o portal{' em ' + url_portal if url_portal else ''} manualmente, "
            "obtenha a certidão e faça upload do PDF."
        )
        return resultado

    except Exception as e:
        resultado["mensagem"] = f"Erro geral: {str(e)[:100]}"
        return resultado


@app.route("/api/empresa-certidoes/sincronizar-fontes", methods=["POST"])
@require_auth
def sincronizar_fontes_certidoes():
    """
    Sincroniza fontes de certidões com registros de certidões da empresa.
    Para cada fonte ativa que NÃO tem certidão vinculada, cria um registro
    com status 'pendente' ou 'nao_disponivel'.
    Chamado automaticamente ao carregar a página Empresa.
    """
    from models import Empresa, EmpresaCertidao, FonteCertidao
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.json or {}
    empresa_id = data.get('empresa_id')
    if not empresa_id:
        return jsonify({"error": "empresa_id é obrigatório"}), 400

    db = get_db()
    try:
        empresa = db.query(Empresa).filter(
            Empresa.id == empresa_id
        ).first()
        if not empresa:
            return jsonify({"error": "Empresa não encontrada"}), 404

        # Buscar fontes ativas — globais (empresa_id IS NULL) + da empresa
        from sqlalchemy import or_ as _or_
        fontes = db.query(FonteCertidao).filter(
            _or_(
                FonteCertidao.empresa_id == empresa_id,
                FonteCertidao.empresa_id.is_(None),
            ),
            FonteCertidao.ativo == True
        ).all()

        # Buscar certidões existentes
        certs_existentes = db.query(EmpresaCertidao).filter(
            EmpresaCertidao.empresa_id == empresa_id
        ).all()
        fontes_com_cert = {c.fonte_certidao_id for c in certs_existentes if c.fonte_certidao_id}

        criadas = 0
        from datetime import date
        for fonte in fontes:
            if fonte.id in fontes_com_cert:
                continue  # Já tem certidão vinculada

            # Determinar status inicial
            if not fonte.permite_busca_automatica:
                status_novo = "nao_disponivel"
            else:
                status_novo = "pendente"

            nova_cert = EmpresaCertidao()
            nova_cert.id = str(uuid.uuid4())
            nova_cert.empresa_id = empresa_id
            nova_cert.tipo = fonte.tipo_certidao
            nova_cert.orgao_emissor = fonte.orgao_emissor or fonte.nome
            nova_cert.url_consulta = fonte.url_portal or ""
            nova_cert.fonte_certidao_id = fonte.id
            nova_cert.status = status_novo
            nova_cert.data_vencimento = date.today()
            db.add(nova_cert)
            criadas += 1

        if criadas > 0:
            db.commit()

        return jsonify({
            "message": f"Sincronização concluída: {criadas} certidões criadas, {len(certs_existentes)} já existentes",
            "criadas": criadas,
            "total": len(certs_existentes) + criadas,
        })
    finally:
        db.close()


@app.route("/api/empresa-certidoes/buscar-automatica", methods=["POST"])
@require_auth
def buscar_certidoes_automatica():
    """
    Busca certidões da empresa automaticamente nos portais oficiais.
    Itera TODAS as fontes cadastradas (não apenas 5 tipos fixos).
    Para cada fonte ativa:
    1. Verifica se já existe certidão vinculada a essa fonte
    2. Se busca automática permitida e pública: tenta web search
    3. Se requer autenticação: marca como pendente
    4. Se manual: marca como nao_disponivel

    JSON body:
    - empresa_id: ID da empresa
    """
    from models import Empresa, EmpresaCertidao, FonteCertidao
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.json or {}

    empresa_id = data.get('empresa_id')
    if not empresa_id:
        return jsonify({"error": "empresa_id é obrigatório"}), 400

    db = get_db()
    try:
        empresa = db.query(Empresa).filter(
            Empresa.id == empresa_id
        ).first()
        if not empresa:
            return jsonify({"error": "Empresa não encontrada"}), 404

        if not empresa.cnpj:
            return jsonify({"error": "Empresa sem CNPJ cadastrado"}), 400

        cnpj = empresa.cnpj.replace('.', '').replace('/', '').replace('-', '').strip()

        # Buscar fontes ativas: globais (empresa_id IS NULL) + da empresa
        from sqlalchemy import or_ as _or_
        fontes = db.query(FonteCertidao).filter(
            _or_(
                FonteCertidao.empresa_id == empresa_id,
                FonteCertidao.empresa_id.is_(None),
            ),
            FonteCertidao.ativo == True
        ).all()

        if not fontes:
            return jsonify({"error": "Nenhuma fonte de certidão cadastrada. Acesse Cadastros > Empresa > Fontes de Certidões para configurar."}), 400

        resultados = []
        from datetime import date, datetime
        stats = {"publicas": 0, "autenticadas": 0, "manuais": 0, "sem_api_key": 0}

        for fonte in fontes:
            # Verificar se já existe certidão vinculada a esta fonte
            cert_existente = db.query(EmpresaCertidao).filter(
                EmpresaCertidao.empresa_id == empresa_id,
                EmpresaCertidao.fonte_certidao_id == fonte.id
            ).first()

            url_consulta = fonte.url_portal or ""
            resultado_auto = None

            # Classificar a fonte
            if not fonte.permite_busca_automatica:
                # Fonte manual — usar observacoes da fonte como orientação detalhada
                stats["manuais"] += 1
                status_novo = "nao_disponivel"
                acao = fonte.observacoes or "Upload manual necessário"
                # Guardar dados estruturados da fonte para o modal de detalhes
                resultado_auto = {
                    "dados_extras": {
                        "Método de Acesso": fonte.metodo_acesso or "publico",
                        "Portal": fonte.url_portal or "Não informado",
                        "Requer Autenticação": "Sim" if fonte.requer_autenticacao else "Não",
                        "Procedimento": "Acesse o portal, emita a certidão e faça upload do PDF",
                    }
                }
            elif fonte.requer_autenticacao and not fonte.usuario and not fonte.api_key and not fonte.certificado_path:
                # Requer autenticação mas sem credenciais
                stats["autenticadas"] += 1
                status_novo = "pendente"
                acao = f"Configure credenciais ({fonte.metodo_acesso}) em Fontes de Certidões"
            else:
                # Fonte pública ou com credenciais — tentar busca automática real
                stats["publicas"] += 1
                status_novo = "buscando"
                acao = "Buscando automaticamente..."

                # Tentar obter a certidão via HTTP
                upload_dir = os.path.join(UPLOAD_FOLDER, 'empresa', empresa_id, 'certidoes')
                resultado_auto = _tentar_obter_certidao(fonte, cnpj, empresa, upload_dir)

                if resultado_auto and resultado_auto.get("sucesso"):
                    status_novo = "valida"
                    acao = resultado_auto.get("mensagem", "Certidão obtida automaticamente")
                    stats["obtidas_auto"] = stats.get("obtidas_auto", 0) + 1
                elif resultado_auto:
                    status_novo = "pendente"
                    acao = resultado_auto.get("mensagem", "Acesse o portal manualmente")
                    # Contar fontes que precisam de API key separadamente
                    if "Chave de API não configurada" in acao or "Chave de API inválida" in acao:
                        stats["sem_api_key"] += 1
                else:
                    status_novo = "pendente"
                    acao = "Acesse o portal para emitir a certidão"

            # Atualizar ultima_consulta na fonte
            fonte.ultima_consulta = datetime.now()
            fonte.resultado_ultima_consulta = 'sucesso' if status_novo == 'valida' else 'erro'

            if cert_existente:
                cert_existente.url_consulta = url_consulta
                cert_existente.orgao_emissor = fonte.orgao_emissor or fonte.nome
                cert_existente.fonte_certidao_id = fonte.id
                # Persistir mensagem e dados_extras da busca
                cert_existente.mensagem = acao
                if resultado_auto and resultado_auto.get("dados_extras"):
                    import json as json_mod
                    de = resultado_auto["dados_extras"]
                    cert_existente.dados_extras = json_mod.loads(de) if isinstance(de, str) else de
                # F04-08: SEMPRE persistir path_arquivo quando scraper baixou o PDF,
                # independente do status_novo — antes so salvava se status=='valida'
                # (caso CRF/FGTS: scraper baixou PDF mas status ficava pendente, perdia o arquivo).
                # F04-07: validar magic bytes %PDF antes de aceitar
                if resultado_auto and resultado_auto.get("path_arquivo"):
                    pdf_path = resultado_auto["path_arquivo"]
                    if _arquivo_eh_pdf_valido(pdf_path):
                        cert_existente.path_arquivo = pdf_path
                    else:
                        # Arquivo nao eh PDF de verdade (HTML de erro/login do scraper)
                        try:
                            os.remove(pdf_path)  # remove arquivo invalido
                        except OSError:
                            pass
                        print(f"[CERTIDAO] {fonte.nome}: arquivo retornado nao eh PDF valido — descartado")
                if status_novo == 'valida':
                    # Nova busca retornou válida — atualizar dados PRIMEIRO
                    cert_existente.status = 'valida'
                    if resultado_auto and resultado_auto.get("data_vencimento"):
                        try:
                            cert_existente.data_vencimento = datetime.strptime(resultado_auto["data_vencimento"], '%Y-%m-%d').date()
                        except (ValueError, TypeError):
                            pass
                    if resultado_auto and resultado_auto.get("numero"):
                        cert_existente.numero = resultado_auto["numero"]
                    cert_existente.data_emissao = date.today()
                    # Verificar se a nova validade já venceu
                    if cert_existente.data_vencimento and cert_existente.data_vencimento < date.today():
                        cert_existente.status = 'vencida'
                elif cert_existente.data_vencimento and cert_existente.data_vencimento < date.today():
                    cert_existente.status = 'vencida'
                elif cert_existente.status in ('buscando', 'erro'):
                    cert_existente.status = status_novo
                resultados.append({
                    "tipo": fonte.tipo_certidao,
                    "status": "atualizado",
                    "certidao": cert_existente.to_dict(),
                    "fonte_nome": fonte.nome,
                    "fonte_id": fonte.id,
                    "url_consulta": url_consulta,
                    "permite_busca_automatica": fonte.permite_busca_automatica,
                    "requer_autenticacao": fonte.requer_autenticacao,
                    "acao": acao,
                })
            else:
                nova_cert = EmpresaCertidao()
                nova_cert.id = str(uuid.uuid4())
                nova_cert.empresa_id = empresa_id
                nova_cert.tipo = fonte.tipo_certidao
                nova_cert.orgao_emissor = fonte.orgao_emissor or fonte.nome
                nova_cert.url_consulta = url_consulta
                nova_cert.fonte_certidao_id = fonte.id
                nova_cert.status = status_novo
                # F04-07/F04-08: validar PDF antes de persistir
                if resultado_auto and resultado_auto.get("path_arquivo"):
                    pdf_path = resultado_auto["path_arquivo"]
                    if _arquivo_eh_pdf_valido(pdf_path):
                        nova_cert.path_arquivo = pdf_path
                    else:
                        try:
                            os.remove(pdf_path)
                        except OSError:
                            pass
                        print(f"[CERTIDAO] {fonte.nome}: PDF retornado nao eh valido — descartado")
                if resultado_auto and resultado_auto.get("data_vencimento"):
                    try:
                        nova_cert.data_vencimento = datetime.strptime(resultado_auto["data_vencimento"], '%Y-%m-%d').date()
                    except (ValueError, TypeError):
                        nova_cert.data_vencimento = date.today()
                else:
                    nova_cert.data_vencimento = date.today()
                if resultado_auto and resultado_auto.get("numero"):
                    nova_cert.numero = resultado_auto["numero"]
                # Persistir mensagem e dados_extras
                nova_cert.mensagem = acao
                if resultado_auto and resultado_auto.get("dados_extras"):
                    import json as json_mod
                    de = resultado_auto["dados_extras"]
                    nova_cert.dados_extras = json_mod.loads(de) if isinstance(de, str) else de
                if status_novo == 'valida':
                    nova_cert.data_emissao = date.today()
                db.add(nova_cert)
                resultados.append({
                    "tipo": fonte.tipo_certidao,
                    "status": "criado",
                    "certidao": nova_cert.to_dict(),
                    "fonte_nome": fonte.nome,
                    "fonte_id": fonte.id,
                    "url_consulta": url_consulta,
                    "permite_busca_automatica": fonte.permite_busca_automatica,
                    "requer_autenticacao": fonte.requer_autenticacao,
                    "acao": acao,
                })

        db.commit()

        obtidas = stats.get("obtidas_auto", 0)
        sem_key = stats.get("sem_api_key", 0)
        pendentes_captcha = stats['publicas'] - obtidas - sem_key

        # Montar mensagem detalhada
        partes = [f"Busca concluída: {len(resultados)} fontes"]
        detalhes = []
        if obtidas > 0:
            detalhes.append(f"{obtidas} obtidas automaticamente")
        if sem_key > 0:
            detalhes.append(f"{sem_key} aguardando chave de API")
        if pendentes_captcha > 0:
            detalhes.append(f"{pendentes_captcha} pendentes (portal manual)")
        if stats['autenticadas'] > 0:
            detalhes.append(f"{stats['autenticadas']} aguardando credenciais")
        if stats['manuais'] > 0:
            detalhes.append(f"{stats['manuais']} manuais")
        msg = partes[0] + " — " + ", ".join(detalhes) if detalhes else partes[0]

        return jsonify({
            "success": True,
            "message": msg,
            "resultados": resultados,
            "cnpj": empresa.cnpj,
            "stats": stats,
            "nota": "Certidões marcadas como 'Válida' foram obtidas automaticamente. "
                    "Para as demais, clique no ícone de olho para abrir o portal e faça upload do PDF."
        })

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Busca de Certidões com SSE (Server-Sent Events) — progresso em tempo real
# =============================================================================

@app.route("/api/empresa-certidoes/buscar-stream", methods=["POST"])
@require_auth
def buscar_certidoes_stream():
    """
    Mesmo que buscar_certidoes_automatica(), mas retorna SSE stream com progresso.
    Cada fonte emite 2 eventos: 'searching' (início) e 'result' (resultado).
    Evento final: 'complete' com stats.
    """
    import json as json_mod
    from models import Empresa, EmpresaCertidao, FonteCertidao
    from datetime import date, datetime

    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.json or {}
    empresa_id = data.get('empresa_id')
    # F04-04: ids_alvo restringe a busca a apenas certidoes especificas (botao individual)
    certidao_ids_alvo = data.get('certidao_ids') or []

    if not empresa_id:
        return jsonify({"error": "empresa_id é obrigatório"}), 400

    def generate():
        db = get_db()
        try:
            empresa = db.query(Empresa).filter(
                Empresa.id == empresa_id
            ).first()
            if not empresa:
                yield f"data: {json_mod.dumps({'type': 'error', 'message': 'Empresa não encontrada'})}\n\n"
                return
            if not empresa.cnpj:
                yield f"data: {json_mod.dumps({'type': 'error', 'message': 'Empresa sem CNPJ cadastrado'})}\n\n"
                return

            cnpj = empresa.cnpj.replace('.', '').replace('/', '').replace('-', '').strip()

            # Buscar fontes ativas: globais (empresa_id IS NULL) + da empresa
            from sqlalchemy import or_ as _or_
            fontes_q = db.query(FonteCertidao).filter(
                _or_(
                    FonteCertidao.empresa_id == empresa_id,
                    FonteCertidao.empresa_id.is_(None),
                ),
                FonteCertidao.ativo == True
            )
            fontes = fontes_q.all()

            # F04-04: se vieram ids_alvo, filtra apenas as fontes_certidao das certidoes-alvo
            if certidao_ids_alvo:
                certs_alvo = db.query(EmpresaCertidao).filter(
                    EmpresaCertidao.id.in_(certidao_ids_alvo),
                    EmpresaCertidao.empresa_id == empresa_id,
                ).all()
                fonte_ids_validos = {c.fonte_certidao_id for c in certs_alvo if c.fonte_certidao_id}
                fontes = [f for f in fontes if f.id in fonte_ids_validos]

            if not fontes:
                yield f"data: {json_mod.dumps({'type': 'error', 'message': 'Nenhuma fonte de certidão cadastrada.'})}\n\n"
                return

            total = len(fontes)
            nomes_fontes = [f.nome for f in fontes]
            yield f"data: {json_mod.dumps({'type': 'start', 'total': total, 'fontes': nomes_fontes})}\n\n"

            resultados = []
            stats = {"publicas": 0, "autenticadas": 0, "manuais": 0, "sem_api_key": 0, "obtidas_auto": 0}

            for idx, fonte in enumerate(fontes):
                # Emit searching event
                yield f"data: {json_mod.dumps({'type': 'searching', 'index': idx + 1, 'total': total, 'fonte': fonte.nome, 'fonte_id': fonte.id})}\n\n"

                cert_existente = db.query(EmpresaCertidao).filter(
                    EmpresaCertidao.empresa_id == empresa_id,
                    EmpresaCertidao.fonte_certidao_id == fonte.id
                ).first()

                url_consulta = fonte.url_portal or ""
                resultado_auto = None

                # Classificar a fonte
                if not fonte.permite_busca_automatica:
                    stats["manuais"] += 1
                    status_novo = "nao_disponivel"
                    acao = fonte.observacoes or "Upload manual necessário"
                    resultado_auto = {
                        "dados_extras": {
                            "Método de Acesso": fonte.metodo_acesso or "publico",
                            "Portal": fonte.url_portal or "Não informado",
                            "Requer Autenticação": "Sim" if fonte.requer_autenticacao else "Não",
                            "Procedimento": "Acesse o portal, emita a certidão e faça upload do PDF",
                        }
                    }
                    sucesso_flag = False
                elif fonte.requer_autenticacao and not fonte.usuario and not fonte.api_key and not fonte.certificado_path:
                    stats["autenticadas"] += 1
                    status_novo = "pendente"
                    acao = f"Configure credenciais ({fonte.metodo_acesso}) em Fontes de Certidões"
                    sucesso_flag = False
                else:
                    stats["publicas"] += 1
                    status_novo = "buscando"
                    acao = "Buscando automaticamente..."

                    upload_dir = os.path.join(UPLOAD_FOLDER, 'empresa', empresa_id, 'certidoes')
                    resultado_auto = _tentar_obter_certidao(fonte, cnpj, empresa, upload_dir)

                    if resultado_auto and resultado_auto.get("sucesso"):
                        status_novo = "valida"
                        acao = resultado_auto.get("mensagem", "Certidão obtida automaticamente")
                        stats["obtidas_auto"] += 1
                        sucesso_flag = True
                    elif resultado_auto:
                        status_novo = "pendente"
                        acao = resultado_auto.get("mensagem", "Acesse o portal manualmente")
                        if "Chave de API não configurada" in acao or "Chave de API inválida" in acao:
                            stats["sem_api_key"] += 1
                        sucesso_flag = False
                    else:
                        status_novo = "pendente"
                        acao = "Acesse o portal para emitir a certidão"
                        sucesso_flag = False

                # Atualizar fonte
                fonte.ultima_consulta = datetime.now()
                fonte.resultado_ultima_consulta = 'sucesso' if status_novo == 'valida' else 'erro'

                # Criar/atualizar certidão
                if cert_existente:
                    cert_existente.url_consulta = url_consulta
                    cert_existente.orgao_emissor = fonte.orgao_emissor or fonte.nome
                    cert_existente.fonte_certidao_id = fonte.id
                    cert_existente.mensagem = acao
                    if resultado_auto and resultado_auto.get("dados_extras"):
                        de = resultado_auto["dados_extras"]
                        cert_existente.dados_extras = json_mod.loads(de) if isinstance(de, str) else de
                    if status_novo == 'valida':
                        cert_existente.status = 'valida'
                        if resultado_auto and resultado_auto.get("path_arquivo"):
                            cert_existente.path_arquivo = resultado_auto["path_arquivo"]
                        if resultado_auto and resultado_auto.get("data_vencimento"):
                            try:
                                cert_existente.data_vencimento = datetime.strptime(resultado_auto["data_vencimento"], '%Y-%m-%d').date()
                            except (ValueError, TypeError):
                                pass
                        if resultado_auto and resultado_auto.get("numero"):
                            cert_existente.numero = resultado_auto["numero"]
                        cert_existente.data_emissao = date.today()
                        if cert_existente.data_vencimento and cert_existente.data_vencimento < date.today():
                            cert_existente.status = 'vencida'
                    elif cert_existente.data_vencimento and cert_existente.data_vencimento < date.today():
                        cert_existente.status = 'vencida'
                    elif cert_existente.status in ('buscando', 'erro'):
                        cert_existente.status = status_novo
                    resultados.append({"fonte_nome": fonte.nome, "acao": acao, "status": status_novo})
                else:
                    nova_cert = EmpresaCertidao()
                    nova_cert.id = str(uuid.uuid4())
                    nova_cert.empresa_id = empresa_id
                    nova_cert.tipo = fonte.tipo_certidao
                    nova_cert.orgao_emissor = fonte.orgao_emissor or fonte.nome
                    nova_cert.url_consulta = url_consulta
                    nova_cert.fonte_certidao_id = fonte.id
                    nova_cert.status = status_novo
                    if resultado_auto and resultado_auto.get("path_arquivo"):
                        nova_cert.path_arquivo = resultado_auto["path_arquivo"]
                    if resultado_auto and resultado_auto.get("data_vencimento"):
                        try:
                            nova_cert.data_vencimento = datetime.strptime(resultado_auto["data_vencimento"], '%Y-%m-%d').date()
                        except (ValueError, TypeError):
                            nova_cert.data_vencimento = date.today()
                    else:
                        nova_cert.data_vencimento = date.today()
                    if resultado_auto and resultado_auto.get("numero"):
                        nova_cert.numero = resultado_auto["numero"]
                    nova_cert.mensagem = acao
                    if resultado_auto and resultado_auto.get("dados_extras"):
                        de = resultado_auto["dados_extras"]
                        nova_cert.dados_extras = json_mod.loads(de) if isinstance(de, str) else de
                    if status_novo == 'valida':
                        nova_cert.data_emissao = date.today()
                    db.add(nova_cert)
                    resultados.append({"fonte_nome": fonte.nome, "acao": acao, "status": status_novo})

                # Emit result event
                yield f"data: {json_mod.dumps({'type': 'result', 'index': idx + 1, 'total': total, 'fonte': fonte.nome, 'fonte_id': fonte.id, 'sucesso': sucesso_flag, 'status': status_novo, 'mensagem': acao})}\n\n"

            db.commit()

            # Build summary
            obtidas = stats.get("obtidas_auto", 0)
            sem_key = stats.get("sem_api_key", 0)
            partes = [f"Busca concluída: {len(resultados)} fontes"]
            detalhes = []
            if obtidas > 0:
                detalhes.append(f"{obtidas} obtidas automaticamente")
            if sem_key > 0:
                detalhes.append(f"{sem_key} aguardando chave de API")
            if stats['autenticadas'] > 0:
                detalhes.append(f"{stats['autenticadas']} aguardando credenciais")
            if stats['manuais'] > 0:
                detalhes.append(f"{stats['manuais']} manuais")
            msg = partes[0] + " — " + ", ".join(detalhes) if detalhes else partes[0]

            yield f"data: {json_mod.dumps({'type': 'complete', 'message': msg, 'stats': stats})}\n\n"

        except Exception as e:
            db.rollback()
            yield f"data: {json_mod.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            db.close()

    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
        'Connection': 'keep-alive',
    })


# =============================================================================
# CapSolver - Status da automação de certidões
# =============================================================================

@app.route("/api/capsolver/status", methods=["GET"])
@require_auth
def capsolver_status():
    """Retorna status do CapSolver (configurado, saldo) para o frontend."""
    import requests
    from config import CAPSOLVER_API_KEY
    if not CAPSOLVER_API_KEY:
        return jsonify({"configurado": False, "mensagem": "CapSolver não configurado. FGTS, TST e SEFAZ requerem upload manual."})

    try:
        resp = requests.post("https://api.capsolver.com/getBalance", json={
            "clientKey": CAPSOLVER_API_KEY
        }, timeout=10)
        data = resp.json()
        if data.get("errorId", 0) != 0:
            return jsonify({"configurado": False, "mensagem": f"CapSolver: {data.get('errorDescription', 'Erro')}"})
        return jsonify({
            "configurado": True,
            "saldo": data.get("balance", 0),
            "mensagem": f"CapSolver ativo — saldo: ${data.get('balance', 0):.2f}"
        })
    except Exception as e:
        return jsonify({"configurado": False, "mensagem": f"CapSolver: erro de conexão — {str(e)[:80]}"})


# =============================================================================
# Fontes de Certidões - Inicializar fontes padrão
# =============================================================================

@app.route("/api/fontes-certidoes/inicializar", methods=["POST"])
@require_auth
def inicializar_fontes_certidoes():
    """
    Cria as 5 fontes padrão de certidões para o usuário, caso ainda não existam.
    Usa dados da empresa (UF, cidade) para personalizar SEFAZ e Prefeitura.
    """
    from models import FonteCertidao, Empresa
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        # Verificar se já tem fontes
        existentes = db.query(FonteCertidao).filter(
            FonteCertidao.empresa_id == empresa_id
        ).count()
        if existentes > 0:
            return jsonify({"success": True, "message": f"Já existem {existentes} fontes cadastradas", "criadas": 0})

        # Buscar empresa para personalizar fontes estadual/municipal
        empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
        uf = empresa.uf if empresa and empresa.uf else "SP"
        cidade = empresa.cidade if empresa and empresa.cidade else ""

        fontes_padrao = [
            # ── BUSCA AUTOMÁTICA REAL (testado 10/03/2026) ──
            {
                "tipo_certidao": "outro",
                "nome": "CGU - Certidão Correcional",
                "orgao_emissor": "Controladoria-Geral da União (CGU)",
                "url_portal": "https://certidoes.cgu.gov.br/",
                "metodo_acesso": "publico",
                "requer_autenticacao": False,
                "permite_busca_automatica": True,
                "observacoes": "API pública SEM captcha. Consolida CEIS, CNEP, CEPIM, CGU-PJ e ePAD em uma única consulta. Busca automática funcional.",
            },
            {
                "tipo_certidao": "fgts",
                "nome": "Caixa - CRF/FGTS",
                "orgao_emissor": "Caixa Econômica Federal",
                "url_portal": "https://consulta-crf.caixa.gov.br/consultacrf/pages/consultaEmpregador.jsf",
                "metodo_acesso": "publico",
                "requer_autenticacao": False,
                "permite_busca_automatica": True,
                "observacoes": "Portal com ShieldSquare (anti-bot). Automação via Playwright. Validade: 30 dias.",
            },
            {
                "tipo_certidao": "outro",
                "nome": "BrasilAPI - Situação Cadastral CNPJ",
                "orgao_emissor": "Receita Federal (via BrasilAPI)",
                "url_portal": "https://brasilapi.com.br/",
                "metodo_acesso": "publico",
                "requer_autenticacao": False,
                "permite_busca_automatica": True,
                "observacoes": "API gratuita, sem captcha. Retorna situação cadastral, Simples Nacional, sócios, CNAE. Consulta em tempo real.",
            },
            # ── AUTOMAÇÃO VIA PLAYWRIGHT + CAPSOLVER ──
            {
                "tipo_certidao": "cnd_federal",
                "nome": "Receita Federal - CND Federal",
                "orgao_emissor": "Receita Federal / PGFN",
                "url_portal": "https://cav.receita.fazenda.gov.br",
                "metodo_acesso": "login_senha",
                "requer_autenticacao": True,
                "permite_busca_automatica": True,
                "observacoes": "Automação via e-CAC com certificado digital A1 ou login gov.br. Configure credenciais na fonte para busca automática.",
            },
            {
                "tipo_certidao": "trabalhista",
                "nome": "TST - CNDT",
                "orgao_emissor": "Tribunal Superior do Trabalho (TST)",
                "url_portal": "https://cndt-certidao.tst.jus.br/gerarCertidao.faces",
                "metodo_acesso": "publico",
                "requer_autenticacao": False,
                "permite_busca_automatica": True,
                "observacoes": "Automação via Playwright + CapSolver (captcha imagem). Validade: 180 dias.",
            },
            {
                "tipo_certidao": "cnd_estadual",
                "nome": f"SEFAZ-{uf} - CND Estadual",
                "orgao_emissor": f"Secretaria da Fazenda - {uf}",
                "url_portal": f"https://www.sefaz.{uf.lower()}.gov.br",
                "uf": uf,
                "metodo_acesso": "publico",
                "requer_autenticacao": False,
                "permite_busca_automatica": True,
                "observacoes": f"Automação via Playwright + CapSolver (reCAPTCHA/hCaptcha). Estado: {uf}.",
            },
            {
                "tipo_certidao": "cnd_municipal",
                "nome": f"Prefeitura{' de ' + cidade if cidade else ''} - CND Municipal",
                "orgao_emissor": f"Prefeitura{' de ' + cidade if cidade else ''}",
                "url_portal": "",
                "cidade": cidade,
                "uf": uf,
                "metodo_acesso": "publico",
                "requer_autenticacao": False,
                "permite_busca_automatica": False,
                "observacoes": "A URL varia por município (+5.500 portais diferentes). Preencha a URL do portal da prefeitura. Maioria exige captcha. Upload manual.",
            },
        ]

        criadas = 0
        for fonte_data in fontes_padrao:
            fonte = FonteCertidao()
            fonte.id = str(uuid.uuid4())
            fonte.user_id = user_id
            for k, v in fonte_data.items():
                setattr(fonte, k, v)
            db.add(fonte)
            criadas += 1

        db.commit()
        return jsonify({
            "success": True,
            "message": f"{criadas} fontes de certidão criadas com sucesso",
            "criadas": criadas,
            "nota": "Revise as URLs (especialmente Estadual e Municipal) e adicione credenciais se necessário."
        })

    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# B3: Notificação real por email (SMTP)
# =============================================================================

@app.route("/api/notificacoes/enviar-email", methods=["POST"])
@require_auth
def enviar_notificacao_email():
    """
    Envia uma notificação por email.
    Usa a configuração SMTP do scheduler.py.

    JSON body:
    - notificacao_id: (opcional) ID da notificação existente para reenviar
    - assunto: assunto do email
    - corpo: corpo do email (texto ou HTML)
    - destinatario: (opcional) email. Se não informado, usa o email do usuário.
    """
    from models import Notificacao, PreferenciasNotificacao, User
    user_id = get_current_user_id()
    data = request.json or {}

    db = get_db()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return jsonify({"error": "Usuário não encontrado"}), 404

        # Determinar destinatário
        prefs = db.query(PreferenciasNotificacao).filter(
            PreferenciasNotificacao.user_id == user_id
        ).first()
        destinatario = data.get('destinatario') or (prefs.email_notificacao if prefs else None) or user.email

        assunto = data.get('assunto', 'Notificação - Agente Editais')
        corpo = data.get('corpo', '')

        # Se notificacao_id fornecido, buscar dados da notificação
        notificacao_id = data.get('notificacao_id')
        if notificacao_id:
            notif = db.query(Notificacao).filter(
                Notificacao.id == notificacao_id,
                Notificacao.user_id == user_id
            ).first()
            if notif:
                assunto = notif.titulo
                corpo = notif.mensagem

        if not corpo:
            return jsonify({"error": "Corpo do email não pode ser vazio"}), 400

        # Enviar via scheduler.enviar_email_alerta
        from scheduler import enviar_email_alerta
        sucesso = enviar_email_alerta(destinatario, assunto, corpo)

        # Atualizar flag enviado_email na notificação
        if notificacao_id and sucesso:
            notif = db.query(Notificacao).filter(Notificacao.id == notificacao_id).first()
            if notif:
                notif.enviado_email = True
                db.commit()

        if sucesso:
            return jsonify({
                "success": True,
                "message": f"Email enviado para {destinatario}"
            })
        else:
            return jsonify({
                "success": False,
                "message": "SMTP não configurado ou erro no envio. "
                           "Configure SMTP_HOST, SMTP_USER e SMTP_PASSWORD nas variáveis de ambiente.",
                "email_salvo": True
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/notificacoes/config-smtp", methods=["GET"])
@require_auth
def verificar_config_smtp():
    """Verifica se o SMTP está configurado."""
    from scheduler import SMTP_HOST, SMTP_USER, SMTP_PASSWORD
    configurado = bool(SMTP_USER and SMTP_PASSWORD)
    return jsonify({
        "smtp_configurado": configurado,
        "smtp_host": SMTP_HOST if configurado else None,
        "smtp_user": SMTP_USER[:3] + "***" if configurado else None
    })


# =============================================================================
# Scheduler Status + Notificações não-lidas
# =============================================================================

@app.route("/api/scheduler/status", methods=["GET"])
@require_auth
def scheduler_status():
    """Retorna status do scheduler e monitoramentos ativos."""
    from models import Monitoramento as Mon, Notificacao as Notif
    import scheduler as sched_mod

    user_id = get_current_user_id()
    db = get_db()

    # Status do scheduler
    sched_available = getattr(sched_mod, 'SCHEDULER_AVAILABLE', False)
    sched_instance = getattr(sched_mod, 'scheduler', None)
    scheduler_ativo = bool(sched_instance and sched_instance.running) if sched_available else False
    check_interval = getattr(sched_mod, 'CHECK_MONITORAMENTOS_INTERVAL', 60)

    # Monitoramentos do usuário
    monitoramentos = db.query(Mon).filter(
        Mon.user_id == user_id
    ).all()

    ativos = [m for m in monitoramentos if m.ativo]
    inativos = [m for m in monitoramentos if not m.ativo]

    # Notificações não lidas
    nao_lidas = db.query(Notif).filter(
        Notif.user_id == user_id,
        Notif.lida == False
    ).count()

    return jsonify({
        "scheduler_disponivel": sched_available,
        "scheduler_ativo": scheduler_ativo,
        "intervalo_verificacao_min": check_interval,
        "monitoramentos_ativos": len(ativos),
        "monitoramentos_inativos": len(inativos),
        "notificacoes_nao_lidas": nao_lidas,
        "monitoramentos": [{
            "id": m.id,
            "termo": m.termo,
            "ncm": m.ncm,
            "ufs": m.ufs,
            "ativo": m.ativo,
            "frequencia_horas": m.frequencia_horas,
            "ultima_execucao": m.ultima_execucao.isoformat() if m.ultima_execucao else None,
            "proximo_check": m.proximo_check.isoformat() if m.proximo_check else None,
            "editais_encontrados": m.editais_encontrados or 0,
        } for m in monitoramentos],
    })


@app.route("/api/notificacoes/nao-lidas", methods=["GET"])
@require_auth
def notificacoes_nao_lidas():
    """Retorna notificações não lidas do usuário."""
    from models import Notificacao
    user_id = get_current_user_id()
    db = get_db()

    notifs = db.query(Notificacao).filter(
        Notificacao.user_id == user_id,
        Notificacao.lida == False
    ).order_by(Notificacao.created_at.desc()).limit(20).all()

    return jsonify({
        "total": len(notifs),
        "notificacoes": [{
            "id": n.id,
            "tipo": n.tipo,
            "titulo": n.titulo,
            "mensagem": n.mensagem,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        } for n in notifs],
    })


@app.route("/api/notificacoes/<notif_id>/lida", methods=["PUT"])
@require_auth
def marcar_notificacao_lida(notif_id):
    """Marca uma notificação como lida."""
    from models import Notificacao
    user_id = get_current_user_id()
    db = get_db()

    notif = db.query(Notificacao).filter(
        Notificacao.id == notif_id,
        Notificacao.user_id == user_id
    ).first()

    if not notif:
        return jsonify({"error": "Notificação não encontrada"}), 404

    notif.lida = True
    notif.lida_em = datetime.now()
    db.commit()

    return jsonify({"success": True})


@app.route("/api/notificacoes/marcar-todas-lidas", methods=["PUT"])
@require_auth
def marcar_todas_notificacoes_lidas():
    """Marca todas as notificações do usuário como lidas."""
    from models import Notificacao
    user_id = get_current_user_id()
    db = get_db()

    atualizadas = db.query(Notificacao).filter(
        Notificacao.user_id == user_id,
        Notificacao.lida == False
    ).update({"lida": True, "lida_em": datetime.now()})

    db.commit()

    return jsonify({"success": True, "atualizadas": atualizadas})


# =============================================================================
# Endpoints: Reprocessar metadados de produto (CATMAT + termos_busca)
# =============================================================================

@app.route("/api/produtos/<produto_id>/reprocessar-metadados", methods=["POST"])
@require_auth
def reprocessar_metadados(produto_id):
    """Reprocessa CATMAT/CATSER e termos de busca para um produto."""
    from tools import processar_metadados_produto
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        produto = db.query(Produto).filter(
            Produto.id == produto_id,
            Produto.empresa_id == empresa_id
        ).first()
        if not produto:
            return jsonify({"success": False, "error": "Produto não encontrado"}), 404
    finally:
        db.close()

    processar_metadados_produto(produto_id)
    return jsonify({"success": True, "message": f"Metadados reprocessados para {produto_id}"})


@app.route("/api/admin/reprocessar-todos-metadados", methods=["POST"])
@require_auth
def reprocessar_todos_metadados():
    """Reprocessa CATMAT/CATSER e termos de busca para todos os produtos do usuário."""
    from tools import processar_metadados_produto
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        produtos = db.query(Produto).filter(Produto.empresa_id == empresa_id).all()
        ids = [p.id for p in produtos]
    finally:
        db.close()

    for pid in ids:
        processar_metadados_produto(pid)

    return jsonify({"success": True, "total": len(ids)})


# =============================================================================
# SPRINT 4: RECURSOS E IMPUGNAÇÕES — Endpoints (UC-I01 a UC-RE05)
# =============================================================================

@app.route("/api/editais/<edital_id>/validacao-legal", methods=["POST"])
@require_auth
def validacao_legal_edital(edital_id):
    """UC-I01: Validação legal do edital via IA."""
    from tools import tool_validacao_legal_edital
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    resultado = tool_validacao_legal_edital(edital_id=edital_id, user_id=user_id, empresa_id=empresa_id)
    if resultado.get("success"):
        return jsonify(resultado)
    return jsonify(resultado), 400 if resultado.get("sem_pdf") else 500


@app.route("/api/editais/<edital_id>/sugerir-peticao", methods=["POST"])
@require_auth
def sugerir_peticao_edital(edital_id):
    """UC-I02: Sugere petição de impugnação ou esclarecimento."""
    from tools import tool_gerar_peticao_impugnacao
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.get_json(silent=True) or {}
    inconsistencias = data.get("inconsistencias")
    template_id = data.get("template_id")
    tipo = data.get("tipo", "impugnacao")

    resultado = tool_gerar_peticao_impugnacao(
        edital_id=edital_id,
        user_id=user_id,
        empresa_id=empresa_id,
        inconsistencias=inconsistencias,
        template_id=template_id,
        tipo=tipo,
    )
    if resultado.get("success"):
        return jsonify(resultado)
    return jsonify(resultado), 500


@app.route("/api/impugnacoes", methods=["POST"])
@require_auth
def criar_impugnacao():
    """UC-I03: Criar/salvar impugnação manualmente."""
    from models import get_db, Impugnacao, Edital
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.get_json(silent=True) or {}

    edital_id = data.get("edital_id")
    if not edital_id:
        return jsonify({"error": "edital_id é obrigatório"}), 400

    db = get_db()
    try:
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()
        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404

        impugnacao = Impugnacao(
            edital_id=edital_id,
            user_id=user_id,
            empresa_id=empresa_id or edital.empresa_id,
            tipo=data.get("tipo", "impugnacao"),
            status=data.get("status", "rascunho"),
            texto=data.get("texto"),
            inconsistencias_json=json.dumps(data.get("inconsistencias", []), ensure_ascii=False) if data.get("inconsistencias") else data.get("inconsistencias_json"),
            prazo_limite=data.get("prazo_limite"),
            template_id=data.get("template_id"),
        )
        db.add(impugnacao)
        db.commit()

        return jsonify({"success": True, "impugnacao": impugnacao.to_dict()}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/impugnacoes/upload", methods=["POST"])
@require_auth
def upload_impugnacao():
    """UC-I04: Upload de arquivo externo de impugnação."""
    from models import get_db, Impugnacao, Edital
    user_id = get_current_user_id()

    if 'arquivo' not in request.files:
        return jsonify({"error": "Arquivo não fornecido"}), 400

    arquivo = request.files['arquivo']
    edital_id = request.form.get("edital_id")
    impugnacao_id = request.form.get("impugnacao_id")

    if not edital_id:
        return jsonify({"error": "edital_id é obrigatório"}), 400

    db = get_db()
    try:
        # Salvar arquivo
        upload_dir = os.path.join(UPLOAD_FOLDER, "impugnacoes", edital_id)
        os.makedirs(upload_dir, exist_ok=True)
        filename = f"{uuid.uuid4()}_{arquivo.filename}"
        filepath = os.path.join(upload_dir, filename)
        arquivo.save(filepath)

        if impugnacao_id:
            # Atualizar impugnação existente
            impugnacao = db.query(Impugnacao).filter(
                Impugnacao.id == impugnacao_id,
                Impugnacao.empresa_id == empresa_id
            ).first()
            if impugnacao:
                impugnacao.arquivo_path = filepath
                impugnacao.updated_at = datetime.now()
                db.commit()
                return jsonify({"success": True, "impugnacao": impugnacao.to_dict()})
            return jsonify({"error": "Impugnação não encontrada"}), 404
        else:
            # Criar nova impugnação com arquivo
            empresa_id = get_current_empresa_id()
            impugnacao = Impugnacao(
                edital_id=edital_id,
                user_id=user_id,
                empresa_id=empresa_id,
                tipo=request.form.get("tipo", "impugnacao"),
                status="rascunho",
                arquivo_path=filepath,
            )
            db.add(impugnacao)
            db.commit()
            return jsonify({"success": True, "impugnacao": impugnacao.to_dict()}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/editais/<edital_id>/prazo-impugnacao", methods=["GET"])
@require_auth
def prazo_impugnacao_edital(edital_id):
    """UC-I05: Calcula prazo de impugnação (3 dias úteis antes da abertura)."""
    from models import get_db, Edital
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()

    db = get_db()
    try:
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()
        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404

        if not edital.data_abertura:
            return jsonify({
                "edital_id": edital_id,
                "prazo_limite": None,
                "message": "Edital sem data de abertura definida",
                "dias_restantes": None,
            })

        # Calcular 3 dias úteis antes da abertura
        prazo = edital.data_abertura
        dias_uteis = 0
        while dias_uteis < 3:
            prazo -= timedelta(days=1)
            if prazo.weekday() < 5:  # Seg-Sex
                dias_uteis += 1

        agora = datetime.now()
        dias_restantes = (prazo - agora).days if prazo > agora else 0
        expirado = prazo <= agora

        return jsonify({
            "edital_id": edital_id,
            "edital_numero": edital.numero,
            "data_abertura": edital.data_abertura.isoformat(),
            "prazo_limite": prazo.isoformat(),
            "dias_restantes": dias_restantes,
            "expirado": expirado,
            "status": "expirado" if expirado else ("urgente" if dias_restantes <= 1 else "aberto"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/editais/<edital_id>/monitorar-janela", methods=["POST"])
@require_auth
def monitorar_janela_recurso(edital_id):
    """UC-RE01: Cadastrar monitoramento de janela de recurso."""
    from models import get_db, Edital, MonitoramentoJanela
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.get_json(silent=True) or {}

    db = get_db()
    try:
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()
        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404

        # Verificar se já existe monitoramento
        existente = db.query(MonitoramentoJanela).filter(
            MonitoramentoJanela.edital_id == edital_id,
            MonitoramentoJanela.empresa_id == empresa_id,
            MonitoramentoJanela.status != 'encerrada'
        ).first()

        if existente:
            # Atualizar existente
            existente.notificar_whatsapp = data.get("notificar_whatsapp", existente.notificar_whatsapp)
            existente.notificar_email = data.get("notificar_email", existente.notificar_email)
            existente.notificar_sistema = data.get("notificar_sistema", existente.notificar_sistema)
            if data.get("data_abertura"):
                existente.data_abertura = data["data_abertura"]
            if data.get("data_encerramento"):
                existente.data_encerramento = data["data_encerramento"]
            db.commit()
            return jsonify({"success": True, "monitoramento": existente.to_dict(), "atualizado": True})

        # Calcular datas automáticas (janela de recurso geralmente abre após resultado)
        data_abertura = data.get("data_abertura")
        data_encerramento = data.get("data_encerramento")

        # Se edital tem data_recursos, usar como referência
        if not data_abertura and edital.data_recursos:
            data_abertura = edital.data_recursos.isoformat() if hasattr(edital.data_recursos, 'isoformat') else edital.data_recursos

        monitoramento = MonitoramentoJanela(
            edital_id=edital_id,
            user_id=user_id,
            status='aguardando',
            data_abertura=data_abertura,
            data_encerramento=data_encerramento,
            notificar_whatsapp=data.get("notificar_whatsapp", True),
            notificar_email=data.get("notificar_email", True),
            notificar_sistema=data.get("notificar_sistema", True),
        )
        db.add(monitoramento)
        db.commit()

        return jsonify({"success": True, "monitoramento": monitoramento.to_dict()}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/editais/<edital_id>/analisar-vencedora", methods=["POST"])
@require_auth
def analisar_vencedora_edital(edital_id):
    """UC-RE02: Analisar proposta vencedora contra edital."""
    from tools import tool_analisar_proposta_vencedora
    user_id = get_current_user_id()
    data = request.get_json(silent=True) or {}
    proposta_texto = data.get("proposta_vencedora_texto")

    resultado = tool_analisar_proposta_vencedora(
        edital_id=edital_id,
        user_id=user_id,
        proposta_vencedora_texto=proposta_texto,
    )
    if resultado.get("success"):
        return jsonify(resultado)
    return jsonify(resultado), 500


@app.route("/api/recursos", methods=["POST"])
@require_auth
def criar_recurso_detalhado():
    """UC-RE04/RE05: Criar recurso ou contra-razão via IA."""
    from tools import tool_gerar_laudo_recurso
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.get_json(silent=True) or {}

    edital_id = data.get("edital_id")
    if not edital_id:
        return jsonify({"error": "edital_id é obrigatório"}), 400

    resultado = tool_gerar_laudo_recurso(
        edital_id=edital_id,
        user_id=user_id,
        empresa_id=empresa_id,
        tipo=data.get("tipo", "recurso"),
        inconsistencias=data.get("inconsistencias"),
        template_id=data.get("template_id"),
        empresa_alvo=data.get("empresa_alvo"),
    )
    if resultado.get("success"):
        return jsonify(resultado), 201
    return jsonify(resultado), 500


@app.route("/api/recursos/upload", methods=["POST"])
@require_auth
def upload_recurso():
    """Upload de laudo externo de recurso."""
    from models import get_db, RecursoDetalhado, Edital
    user_id = get_current_user_id()

    if 'arquivo' not in request.files:
        return jsonify({"error": "Arquivo não fornecido"}), 400

    arquivo = request.files['arquivo']
    edital_id = request.form.get("edital_id")
    recurso_id = request.form.get("recurso_id")

    if not edital_id:
        return jsonify({"error": "edital_id é obrigatório"}), 400

    db = get_db()
    try:
        # Salvar arquivo
        upload_dir = os.path.join(UPLOAD_FOLDER, "recursos", edital_id)
        os.makedirs(upload_dir, exist_ok=True)
        filename = f"{uuid.uuid4()}_{arquivo.filename}"
        filepath = os.path.join(upload_dir, filename)
        arquivo.save(filepath)

        if recurso_id:
            # Atualizar recurso existente
            recurso = db.query(RecursoDetalhado).filter(
                RecursoDetalhado.id == recurso_id,
                RecursoDetalhado.empresa_id == empresa_id
            ).first()
            if recurso:
                recurso.arquivo_path = filepath
                recurso.updated_at = datetime.now()
                db.commit()
                return jsonify({"success": True, "recurso": recurso.to_dict()})
            return jsonify({"error": "Recurso não encontrado"}), 404
        else:
            # Criar novo recurso com arquivo
            empresa_id = get_current_empresa_id()
            recurso = RecursoDetalhado(
                edital_id=edital_id,
                user_id=user_id,
                empresa_id=empresa_id,
                tipo=request.form.get("tipo", "recurso"),
                status="rascunho",
                arquivo_path=filepath,
            )
            db.add(recurso)
            db.commit()
            return jsonify({"success": True, "recurso": recurso.to_dict()}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/recursos", methods=["GET"])
@require_auth
def listar_recursos_detalhados():
    """Listar recursos/contra-razões de um edital."""
    from models import get_db, RecursoDetalhado
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    edital_id = request.args.get("edital_id")

    db = get_db()
    try:
        query = db.query(RecursoDetalhado).filter(RecursoDetalhado.empresa_id == empresa_id)
        if edital_id:
            query = query.filter(RecursoDetalhado.edital_id == edital_id)
        query = query.order_by(RecursoDetalhado.created_at.desc())

        recursos = query.all()
        return jsonify({
            "success": True,
            "recursos": [r.to_dict() for r in recursos],
            "total": len(recursos),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/recursos/<recurso_id>/status", methods=["PUT"])
@require_auth
def atualizar_status_recurso(recurso_id):
    """Atualizar status de um recurso."""
    from models import get_db, RecursoDetalhado
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    data = request.get_json(silent=True) or {}
    novo_status = data.get("status")

    if not novo_status:
        return jsonify({"error": "status é obrigatório"}), 400

    status_validos = ['rascunho', 'revisao', 'enviado', 'aceito', 'rejeitado']
    if novo_status not in status_validos:
        return jsonify({"error": f"Status inválido. Valores aceitos: {status_validos}"}), 400

    db = get_db()
    try:
        recurso = db.query(RecursoDetalhado).filter(
            RecursoDetalhado.id == recurso_id,
            RecursoDetalhado.empresa_id == empresa_id
        ).first()
        if not recurso:
            return jsonify({"error": "Recurso não encontrado"}), 404

        recurso.status = novo_status
        recurso.updated_at = datetime.now()
        db.commit()

        return jsonify({"success": True, "recurso": recurso.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# SPRINT 5 — PÓS-LICITAÇÃO
# =============================================================================


# ---- Follow-up (UC-FU01, FU02) ----

@app.route('/api/followup/registrar-resultado', methods=['POST'])
@require_auth
def api_followup_registrar_resultado():
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        data = request.get_json()
        result = tool_registrar_resultado_api(data, user_id, empresa_id=empresa_id, db=db)
        if result.get('success'):
            return jsonify(result)
        return jsonify(result), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route('/api/followup/pendentes', methods=['GET'])
@require_auth
def api_followup_pendentes():
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        editais = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.status.in_(['submetido', 'proposta_enviada', 'em_pregao'])
        ).all()
        return jsonify([e.to_dict() for e in editais])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route('/api/followup/resultados', methods=['GET'])
@require_auth
def api_followup_resultados():
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        editais = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.status.in_(['ganho', 'perdido', 'cancelado'])
        ).order_by(Edital.updated_at.desc()).all()
        return jsonify([e.to_dict() for e in editais])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ---- Score Logístico (UC-FU03) ----

@app.route('/api/validacao/score-logistico/<edital_id>', methods=['GET'])
@require_auth
def api_score_logistico(edital_id):
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        result = tool_calcular_score_logistico(edital_id, user_id, empresa_id=empresa_id, db=db)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ---- Atas (UC-AT01, AT02, AT03) ----

@app.route('/api/atas/buscar', methods=['GET'])
@require_auth
def api_atas_buscar():
    db = get_db()
    try:
        user_id = get_current_user_id()
        termo = request.args.get('termo', '')
        if len(termo) < 3:
            return jsonify({"error": "Termo deve ter pelo menos 3 caracteres"}), 400
        result = tool_buscar_atas_pncp(termo, user_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route('/api/atas/extrair-pdf', methods=['POST'])
@require_auth
def api_atas_extrair_pdf():
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        data = request.get_json()
        url = data.get('url', '')
        texto = data.get('texto', '')

        if url and not texto:
            download_result = tool_baixar_ata_pncp(url, user_id)
            if 'erro' in download_result:
                return jsonify(download_result), 400
            texto = download_result.get('texto', '')

        if not texto:
            return jsonify({"error": "Texto ou URL obrigatório"}), 400

        result = tool_extrair_ata_pdf(texto, user_id, empresa_id=empresa_id, db=db)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route('/api/atas/minhas', methods=['GET'])
@require_auth
def api_atas_minhas():
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        atas = db.query(AtaConsultada).filter_by(empresa_id=empresa_id).order_by(AtaConsultada.created_at.desc()).all()
        now = datetime.now()
        total = len(atas)
        vigentes = sum(1 for a in atas if a.data_vigencia_fim and a.data_vigencia_fim > now)
        vencidas = total - vigentes
        return jsonify({
            "stats": {"total": total, "vigentes": vigentes, "vencidas": vencidas},
            "atas": [a.to_dict() for a in atas]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route('/api/atas/salvar', methods=['POST'])
@require_auth
def api_atas_salvar():
    db = get_db()
    try:
        user_id = get_current_user_id()
        data = request.get_json()
        ata = AtaConsultada(
            user_id=user_id,
            numero_controle_pncp=data.get('numero_controle_pncp', ''),
            titulo=data.get('titulo', ''),
            orgao=data.get('orgao', ''),
            cnpj_orgao=data.get('cnpj_orgao', ''),
            uf=data.get('uf', ''),
            url_pncp=data.get('url_pncp', ''),
            data_publicacao=datetime.fromisoformat(data['data_publicacao']) if data.get('data_publicacao') else None,
            data_vigencia_inicio=datetime.fromisoformat(data['data_vigencia_inicio']) if data.get('data_vigencia_inicio') else None,
            data_vigencia_fim=datetime.fromisoformat(data['data_vigencia_fim']) if data.get('data_vigencia_fim') else None,
        )
        db.add(ata)
        db.commit()
        return jsonify({"success": True, "id": ata.id, "ata": ata.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ---- Dashboard Contratado x Realizado (UC-CR01) ----

@app.route('/api/dashboard/contratado-realizado', methods=['GET'])
@require_auth
def api_dashboard_contratado_realizado():
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        periodo = request.args.get('periodo', '6m')
        produto_id = request.args.get('produto_id')
        orgao = request.args.get('orgao')
        result = tool_dashboard_contratado_realizado(user_id, empresa_id=empresa_id, db=db, periodo=periodo, produto_id=produto_id, orgao=orgao)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Dashboard de Perdas — PerdasPage.tsx
# =============================================================================

@app.route("/api/dashboard/perdas", methods=["GET"])
@require_auth
def api_dashboard_perdas():
    from models import PrecoHistorico, Edital
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        periodo_dias = int(request.args.get("periodo_dias", 180))
        desde = datetime.now() - timedelta(days=periodo_dias)

        perdas = db.query(PrecoHistorico).join(
            Edital, PrecoHistorico.edital_id == Edital.id
        ).filter(
            Edital.empresa_id == empresa_id,
            PrecoHistorico.resultado == 'derrota',
            PrecoHistorico.data_registro >= desde,
        ).all()

        motivos = {}
        for p in perdas:
            m = p.motivo_perda or 'outro'
            motivos[m] = motivos.get(m, 0) + 1
        total = len(perdas)
        motivos_list = [
            {"motivo": k, "quantidade": v, "percentual": round(v / max(total, 1) * 100, 1)}
            for k, v in motivos.items()
        ]

        perdas_list = []
        for p in perdas:
            ed = db.query(Edital).filter(Edital.id == p.edital_id).first()
            perdas_list.append({
                "id": p.id,
                "edital": ed.numero if ed else "—",
                "orgao": ed.orgao if ed else "—",
                "data": p.data_registro.strftime("%d/%m/%Y") if p.data_registro else "—",
                "valorProposto": float(p.nosso_preco) if p.nosso_preco else 0,
                "valorVencedor": float(p.preco_vencedor) if p.preco_vencedor else 0,
                "diferenca": abs(float((p.nosso_preco or 0) - (p.preco_vencedor or 0))),
                "motivo": p.motivo_perda or "outro",
                "vencedor": p.empresa_vencedora or "—",
            })

        total_participacoes = db.query(PrecoHistorico).join(
            Edital, PrecoHistorico.edital_id == Edital.id
        ).filter(
            Edital.empresa_id == empresa_id,
            PrecoHistorico.resultado.in_(['vitoria', 'derrota']),
            PrecoHistorico.data_registro >= desde,
        ).count()
        taxa = round(total / max(total_participacoes, 1) * 100, 1)

        return jsonify({
            "perdas": perdas_list,
            "motivos": motivos_list,
            "total": total,
            "taxa_perda": taxa,
            "valor_total_perdido": sum(float(p.nosso_preco or 0) for p in perdas),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Lances — LancesPage.tsx
# =============================================================================

@app.route("/api/lances/hoje", methods=["GET"])
@require_auth
def api_lances_hoje():
    from models import Edital
    from sqlalchemy import func
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        hoje = datetime.now().date()
        editais = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            func.date(Edital.data_abertura) == hoje,
        ).order_by(Edital.data_abertura).all()

        agora = datetime.now()
        pregoes = []
        for e in editais:
            if not e.data_abertura:
                continue
            if e.data_abertura > agora:
                status = "aguardando"
                delta = e.data_abertura - agora
                horas = int(delta.total_seconds() // 3600)
                minutos = int((delta.total_seconds() % 3600) // 60)
                tempo_restante = f"{horas}h{minutos:02d}min" if horas else f"{minutos}min"
            elif e.status in ('encerrado', 'homologado', 'adjudicado', 'perdido', 'vencido'):
                status = "encerrado"
                tempo_restante = None
            else:
                status = "em_andamento"
                tempo_restante = None

            pregoes.append({
                "id": e.id,
                "edital": e.numero,
                "orgao": e.orgao,
                "hora": e.data_abertura.strftime("%H:%M"),
                "status": status,
                "tempoRestante": tempo_restante,
                "url_portal": getattr(e, 'url_pncp', None) or getattr(e, 'url_comprasnet', None),
            })

        return jsonify({"pregoes": pregoes, "total": len(pregoes)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/lances/historico", methods=["GET"])
@require_auth
def api_lances_historico():
    from models import PrecoHistorico, Edital
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        limite = int(request.args.get("limit", 20))
        participacoes = db.query(PrecoHistorico).join(
            Edital, PrecoHistorico.edital_id == Edital.id
        ).filter(
            Edital.empresa_id == empresa_id,
            PrecoHistorico.resultado.in_(['vitoria', 'derrota']),
        ).order_by(PrecoHistorico.data_registro.desc()).limit(limite).all()

        items = []
        for p in participacoes:
            ed = db.query(Edital).filter(Edital.id == p.edital_id).first()
            items.append({
                "id": p.id,
                "edital": ed.numero if ed else "—",
                "orgao": ed.orgao if ed else "—",
                "data": p.data_registro.strftime("%d/%m/%Y") if p.data_registro else "—",
                "nossoLance": float(p.nosso_preco) if p.nosso_preco else 0,
                "lanceVencedor": float(p.preco_vencedor) if p.preco_vencedor else 0,
                "vencedor": p.empresa_vencedora or "—",
                "resultado": p.resultado or "—",
            })

        return jsonify({"historico": items, "total": len(items)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Sprint 9 — Sala Virtual, Scores, Analytics, Health
# =============================================================================

@app.route("/api/precificacao/simular-lance", methods=["POST"])
@require_auth
def api_simular_lance_deterministico():
    """UC-LA01: Simulação determinística de lances."""
    from tools import tool_simular_lance
    data = request.get_json() or {}
    empresa_id = get_current_empresa_id()
    result = tool_simular_lance(
        edital_item_produto_id=data.get("edital_item_produto_id", ""),
        user_id=get_current_user_id(),
        empresa_id=empresa_id,
        num_rodadas=data.get("num_rodadas", 10),
        tipo_decremento=data.get("tipo_decremento", "fixo_reais"),
        valor_decremento=float(data.get("valor_decremento", 10)),
        num_concorrentes=data.get("num_concorrentes", 3),
        perfil=data.get("perfil", "quero_ganhar"),
    )
    return jsonify(result), 200 if result.get("success") else 400


@app.route("/api/sala/criar", methods=["POST"])
@require_auth
def api_sala_criar():
    """UC-LA03: Cria sessão de pregão (sala virtual)."""
    from models import SessaoPregao, Edital, AuditoriaLog
    data = request.get_json() or {}
    empresa_id = get_current_empresa_id()
    user_id = get_current_user_id()
    db = get_db()
    try:
        edital_id = data.get("edital_id")
        edital = db.query(Edital).filter(Edital.id == edital_id, Edital.empresa_id == empresa_id).first()
        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404

        sessao = SessaoPregao(
            user_id=user_id,
            empresa_id=empresa_id,
            edital_id=edital_id,
            modalidade=data.get("modalidade", "aberto"),
            autonomia=data.get("autonomia", "copiloto"),
            timer_aberto_seg=data.get("timer_aberto_seg", 120),
            timer_fechado_seg=data.get("timer_fechado_seg", 300),
            alarme_custo=data.get("alarme_custo", True),
            alarme_minimo=data.get("alarme_minimo", True),
            max_lances_automaticos=data.get("max_lances_automaticos", 20),
            status='configurando',
        )
        db.add(sessao)
        db.add(AuditoriaLog(user_id=user_id, acao="sala_criada",
                            entidade="sessao_pregao", entidade_id=sessao.id,
                            dados_depois={"edital_id": edital_id, "modalidade": sessao.modalidade}))
        db.commit()
        return jsonify({"success": True, "sessao": sessao.to_dict()}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/sala/<sessao_id>/estado", methods=["GET"])
@require_auth
def api_sala_estado(sessao_id):
    """UC-LA03: Retorna estado atual da sala (polling 5s)."""
    from models import SessaoPregao, Lance, PrecoCamada, EditalItemProduto, EditalItem, EstrategiaEdital
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        sessao = db.query(SessaoPregao).filter(
            SessaoPregao.id == sessao_id, SessaoPregao.empresa_id == empresa_id
        ).first()
        if not sessao:
            return jsonify({"error": "Sessão não encontrada"}), 404

        lances = db.query(Lance).filter(Lance.sessao_pregao_id == sessao_id).order_by(Lance.created_at.desc()).all()

        vinculo = db.query(EditalItemProduto).filter(
            EditalItemProduto.empresa_id == empresa_id
        ).join(EditalItem).filter(EditalItem.edital_id == sessao.edital_id).first()

        camada = None
        estrategia = None
        if vinculo:
            camada = db.query(PrecoCamada).filter(PrecoCamada.edital_item_produto_id == vinculo.id).first()
        estrategia = db.query(EstrategiaEdital).filter(
            EstrategiaEdital.edital_id == sessao.edital_id,
            EstrategiaEdital.empresa_id == empresa_id,
        ).first()

        return jsonify({
            "sessao": sessao.to_dict(),
            "lances": [l.to_dict() for l in lances[:50]],
            "camadas": {
                "custo_base": float(camada.custo_base_final or 0) if camada else 0,
                "lance_inicial": float(camada.lance_inicial or 0) if camada else 0,
                "lance_minimo": float(camada.lance_minimo or 0) if camada else 0,
                "margem_minima": float(camada.margem_minima or 0) if camada else 0,
                "target_referencia": float(camada.target_referencia or 0) if camada else 0,
            } if camada else {},
            "estrategia": {
                "perfil": estrategia.perfil_competitivo if estrategia else "copiloto",
                "cenarios": estrategia.cenarios_simulados if estrategia else [],
            },
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/sala/<sessao_id>/lance", methods=["POST"])
@require_auth
def api_sala_lance(sessao_id):
    """UC-LA04: Registra lance na sala virtual (fase aberta)."""
    from models import SessaoPregao, Lance, PrecoCamada, EditalItemProduto, EditalItem, AuditoriaLog
    data = request.get_json() or {}
    empresa_id = get_current_empresa_id()
    user_id = get_current_user_id()
    db = get_db()
    try:
        sessao = db.query(SessaoPregao).filter(
            SessaoPregao.id == sessao_id, SessaoPregao.empresa_id == empresa_id
        ).first()
        if not sessao:
            return jsonify({"error": "Sessão não encontrada"}), 404
        if sessao.status == 'encerrada':
            return jsonify({"error": "Sessão encerrada"}), 400

        valor = float(data.get("valor", 0))
        if valor <= 0:
            return jsonify({"error": "Valor deve ser > 0"}), 400

        vinculo = db.query(EditalItemProduto).filter(
            EditalItemProduto.empresa_id == empresa_id
        ).join(EditalItem).filter(EditalItem.edital_id == sessao.edital_id).first()
        if not vinculo:
            return jsonify({"error": "Nenhum item vinculado ao edital"}), 400

        camada = db.query(PrecoCamada).filter(PrecoCamada.edital_item_produto_id == vinculo.id).first()
        custo = float(camada.custo_base_final or 0) if camada else 0
        margem = ((valor - custo) / custo * 100) if custo > 0 else 0

        ultimo = db.query(Lance).filter(
            Lance.sessao_pregao_id == sessao_id
        ).order_by(Lance.rodada.desc()).first()
        rodada = (ultimo.rodada + 1) if ultimo else 1

        lance = Lance(
            edital_item_produto_id=vinculo.id,
            user_id=user_id,
            empresa_id=empresa_id,
            sessao_pregao_id=sessao_id,
            rodada=rodada,
            valor_lance=valor,
            tipo='decremento' if rodada > 1 else 'inicial',
            fase='aberta',
            margem_sobre_custo=round(margem, 2),
            status='enviado',
        )
        db.add(lance)

        if sessao.status == 'configurando':
            sessao.status = 'ativa'

        db.add(AuditoriaLog(user_id=user_id, acao="lance_enviado",
                            entidade="lance", entidade_id=lance.id,
                            dados_depois={"valor": valor, "rodada": rodada, "margem": round(margem, 2)}))
        db.commit()

        return jsonify({
            "success": True,
            "lance": lance.to_dict(),
            "abaixo_custo": valor < custo,
            "abaixo_minimo": valor < float(camada.lance_minimo or 0) if camada else False,
        })
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/sala/<sessao_id>/lance-fechado", methods=["POST"])
@require_auth
def api_sala_lance_fechado(sessao_id):
    """UC-LA04: Registra lance na fase fechada."""
    from models import SessaoPregao, Lance, PrecoCamada, EditalItemProduto, EditalItem, AuditoriaLog
    data = request.get_json() or {}
    empresa_id = get_current_empresa_id()
    user_id = get_current_user_id()
    db = get_db()
    try:
        sessao = db.query(SessaoPregao).filter(
            SessaoPregao.id == sessao_id, SessaoPregao.empresa_id == empresa_id
        ).first()
        if not sessao or sessao.fase_atual != 'fechada':
            return jsonify({"error": "Sessão não está na fase fechada"}), 400

        valor = float(data.get("valor", 0))
        vinculo = db.query(EditalItemProduto).filter(
            EditalItemProduto.empresa_id == empresa_id
        ).join(EditalItem).filter(EditalItem.edital_id == sessao.edital_id).first()

        camada = db.query(PrecoCamada).filter(PrecoCamada.edital_item_produto_id == vinculo.id).first() if vinculo else None
        custo = float(camada.custo_base_final or 0) if camada else 0
        margem = ((valor - custo) / custo * 100) if custo > 0 else 0

        lance = Lance(
            edital_item_produto_id=vinculo.id if vinculo else None,
            user_id=user_id,
            empresa_id=empresa_id,
            sessao_pregao_id=sessao_id,
            rodada=0,
            valor_lance=valor,
            tipo='minimo',
            fase='fechada',
            margem_sobre_custo=round(margem, 2),
            status='enviado',
        )
        db.add(lance)
        db.add(AuditoriaLog(user_id=user_id, acao="lance_fechado_enviado",
                            entidade="lance", entidade_id=lance.id,
                            dados_depois={"valor": valor, "fase": "fechada"}))
        db.commit()
        return jsonify({"success": True, "lance": lance.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/sala/<sessao_id>/sugerir-lance", methods=["POST"])
@require_auth
def api_sala_sugerir_lance(sessao_id):
    """UC-LA02: Sugestão inteligente de lance via IA."""
    from tools import tool_sugerir_lance
    from models import SessaoPregao, PrecoCamada, EditalItemProduto, EditalItem, EstrategiaEdital
    data = request.get_json() or {}
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        sessao = db.query(SessaoPregao).filter(
            SessaoPregao.id == sessao_id, SessaoPregao.empresa_id == empresa_id
        ).first()
        if not sessao:
            return jsonify({"error": "Sessão não encontrada"}), 404

        vinculo = db.query(EditalItemProduto).filter(
            EditalItemProduto.empresa_id == empresa_id
        ).join(EditalItem).filter(EditalItem.edital_id == sessao.edital_id).first()
        camada = db.query(PrecoCamada).filter(PrecoCamada.edital_item_produto_id == vinculo.id).first() if vinculo else None
        estrategia = db.query(EstrategiaEdital).filter(
            EstrategiaEdital.edital_id == sessao.edital_id, EstrategiaEdital.empresa_id == empresa_id
        ).first()

        result = tool_sugerir_lance(
            sessao_pregao_id=sessao_id,
            user_id=get_current_user_id(),
            empresa_id=empresa_id,
            lance_lider=float(data.get("lance_lider", 0)),
            nosso_ultimo=float(data.get("nosso_ultimo", 0)),
            custo_base=float(camada.custo_base_final or 0) if camada else 0,
            lance_minimo=float(camada.lance_minimo or 0) if camada else 0,
            lance_inicial=float(camada.lance_inicial or 0) if camada else 0,
            target=float(camada.target_referencia or 0) if camada else 0,
            perfil=estrategia.perfil_competitivo if estrategia else "copiloto",
            decremento_medio=float(data.get("decremento_medio", 10)),
        )
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/sala/<sessao_id>/encerrar", methods=["POST"])
@require_auth
def api_sala_encerrar(sessao_id):
    """UC-LA03: Encerra sessão de pregão."""
    from models import SessaoPregao, Lance, AuditoriaLog
    data = request.get_json() or {}
    empresa_id = get_current_empresa_id()
    user_id = get_current_user_id()
    db = get_db()
    try:
        sessao = db.query(SessaoPregao).filter(
            SessaoPregao.id == sessao_id, SessaoPregao.empresa_id == empresa_id
        ).first()
        if not sessao:
            return jsonify({"error": "Sessão não encontrada"}), 404

        sessao.status = 'encerrada'
        sessao.fase_atual = 'encerrada'
        sessao.resultado = data.get("resultado")
        sessao.posicao_final = data.get("posicao_final")
        sessao.robo_ativo = False

        ultimo_lance = db.query(Lance).filter(
            Lance.sessao_pregao_id == sessao_id
        ).order_by(Lance.created_at.desc()).first()
        if ultimo_lance:
            sessao.lance_final = ultimo_lance.valor_lance
            sessao.margem_final = ultimo_lance.margem_sobre_custo

        db.add(AuditoriaLog(user_id=user_id, acao="sala_encerrada",
                            entidade="sessao_pregao", entidade_id=sessao_id,
                            dados_depois={"resultado": sessao.resultado, "posicao": sessao.posicao_final}))
        db.commit()
        return jsonify({"success": True, "sessao": sessao.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/sala/<sessao_id>/robo/ativar", methods=["POST"])
@require_auth
def api_sala_robo_ativar(sessao_id):
    """UC-LA06: Ativa robô de lances automáticos (RN-NEW-12)."""
    from models import SessaoPregao, AuditoriaLog
    auto_bid = os.environ.get('AUTO_BID_ENABLED', 'false').lower() == 'true'
    if not auto_bid:
        return jsonify({"error": "AUTO_BID_ENABLED=false. Robô desabilitado (RN-NEW-12)"}), 403

    data = request.get_json() or {}
    empresa_id = get_current_empresa_id()
    user_id = get_current_user_id()
    db = get_db()
    try:
        sessao = db.query(SessaoPregao).filter(
            SessaoPregao.id == sessao_id, SessaoPregao.empresa_id == empresa_id
        ).first()
        if not sessao:
            return jsonify({"error": "Sessão não encontrada"}), 404
        if sessao.status == 'encerrada':
            return jsonify({"error": "Sessão encerrada"}), 400

        sessao.robo_ativo = True
        sessao.robo_modo_decremento = data.get("modo_decremento", "fixo_reais")
        sessao.robo_valor_decremento = float(data.get("valor_decremento", 10))
        sessao.robo_confirmar_cada = data.get("confirmar_cada", True)
        sessao.max_lances_automaticos = data.get("max_lances", 20)
        sessao.autonomia = 'robo'

        db.add(AuditoriaLog(user_id=user_id, acao="robo_ativado",
                            entidade="sessao_pregao", entidade_id=sessao_id,
                            dados_depois={"modo": sessao.robo_modo_decremento, "valor": float(sessao.robo_valor_decremento or 0)}))
        db.commit()
        return jsonify({"success": True, "sessao": sessao.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/sala/<sessao_id>/robo/desativar", methods=["POST"])
@require_auth
def api_sala_robo_desativar(sessao_id):
    """UC-LA06: Desativa robô."""
    from models import SessaoPregao, AuditoriaLog
    empresa_id = get_current_empresa_id()
    user_id = get_current_user_id()
    db = get_db()
    try:
        sessao = db.query(SessaoPregao).filter(
            SessaoPregao.id == sessao_id, SessaoPregao.empresa_id == empresa_id
        ).first()
        if not sessao:
            return jsonify({"error": "Sessão não encontrada"}), 404
        sessao.robo_ativo = False
        sessao.autonomia = 'copiloto'
        db.add(AuditoriaLog(user_id=user_id, acao="robo_desativado",
                            entidade="sessao_pregao", entidade_id=sessao_id))
        db.commit()
        return jsonify({"success": True, "sessao": sessao.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/sala/<sessao_id>/robo/pausar", methods=["POST"])
@require_auth
def api_sala_robo_pausar(sessao_id):
    """UC-LA06: Pausa robô."""
    from models import SessaoPregao
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        sessao = db.query(SessaoPregao).filter(
            SessaoPregao.id == sessao_id, SessaoPregao.empresa_id == empresa_id
        ).first()
        if not sessao:
            return jsonify({"error": "Sessão não encontrada"}), 404
        sessao.robo_ativo = False
        sessao.status = 'pausada'
        db.commit()
        return jsonify({"success": True, "sessao": sessao.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/monitoramentos/sessao-pregao", methods=["POST"])
@require_auth
def api_monitoramento_sessao_pregao():
    """UC-LA05: Cria monitoramento de sessão de pregão."""
    from models import Monitoramento, AuditoriaLog
    data = request.get_json() or {}
    empresa_id = get_current_empresa_id()
    user_id = get_current_user_id()
    db = get_db()
    try:
        m = Monitoramento(
            user_id=user_id,
            empresa_id=empresa_id,
            tipo='sessao_pregao',
            edital_id=data.get("edital_id"),
            termo=data.get("termo", "Sessão de Pregão"),
            frequencia_horas=1,
            notificar_email=data.get("notificar_email", True),
            ativo=True,
        )
        db.add(m)
        db.add(AuditoriaLog(user_id=user_id, acao="monitoramento_sessao_criado",
                            entidade="monitoramento", entidade_id=m.id,
                            dados_depois={"edital_id": data.get("edital_id"), "tipo": "sessao_pregao"}))
        db.commit()
        return jsonify({"success": True, "monitoramento": m.to_dict()}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/score/competitividade/<edital_id>", methods=["GET"])
@require_auth
def api_score_competitividade(edital_id):
    """UC-SC01: Score de Competitividade 360°."""
    from tools import tool_score_competitividade
    empresa_id = get_current_empresa_id()
    result = tool_score_competitividade(edital_id=edital_id, user_id=get_current_user_id(), empresa_id=empresa_id)
    return jsonify(result), 200 if result.get("success") else 400


@app.route("/api/concorrentes/<concorrente_id>/qualidade", methods=["GET"])
@require_auth
def api_concorrente_qualidade(concorrente_id):
    """UC-SC02: Score de Qualidade do Concorrente."""
    from tools import tool_score_qualidade_concorrente
    empresa_id = get_current_empresa_id()
    result = tool_score_qualidade_concorrente(concorrente_id=concorrente_id, empresa_id=empresa_id)
    return jsonify(result), 200 if result.get("success") else 400


@app.route("/api/analytics/qualidade-orgao/<path:orgao>", methods=["GET"])
@require_auth
def api_qualidade_orgao(orgao):
    """UC-SC02: Qualidade média dos concorrentes por órgão."""
    from models import Concorrente, ParticipacaoEdital, Edital
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        concorrentes = db.query(Concorrente).all()
        scores = []
        for c in concorrentes:
            participados = int(c.editais_participados or 0)
            desclass = db.query(ParticipacaoEdital).filter(
                ParticipacaoEdital.concorrente_id == c.id,
                ParticipacaoEdital.desclassificado == True,
            ).count()
            score = 100 - ((desclass) / max(participados, 1)) * 100
            scores.append(max(0, min(100, round(score, 1))))

        media = round(sum(scores) / max(len(scores), 1), 1)
        return jsonify({"orgao": orgao, "media_qualidade": media, "total_concorrentes": len(scores)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/recursos/<edital_id>/score", methods=["GET"])
@require_auth
def api_score_recurso(edital_id):
    """UC-SC03: Score Numérico de Recurso."""
    from tools import tool_score_recurso
    empresa_id = get_current_empresa_id()
    result = tool_score_recurso(edital_id=edital_id, user_id=get_current_user_id(), empresa_id=empresa_id)
    return jsonify(result), 200 if result.get("success") else 400


@app.route("/api/analytics/tempo-empenho", methods=["GET"])
@require_auth
def api_tempo_empenho():
    """UC-SC04: Tempo Médio do 1º Empenho por contrato/órgão."""
    from models import Contrato, Edital
    from sqlalchemy import func
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        from models import get_db as _gdb
        from empenho_routes import Empenho
        contratos = db.query(Contrato).filter(Contrato.empresa_id == empresa_id).all()

        tempos = []
        por_orgao = {}
        sem_empenho = 0

        for c in contratos:
            primeiro_empenho = db.query(Empenho).filter(
                Empenho.contrato_id == c.id
            ).order_by(Empenho.data_empenho.asc()).first()

            if not primeiro_empenho or not primeiro_empenho.data_empenho or not c.data_assinatura:
                sem_empenho += 1
                continue

            dias = (primeiro_empenho.data_empenho - c.data_assinatura).days
            dias = max(0, dias)
            tempos.append(dias)

            edital = db.query(Edital).filter(Edital.id == c.edital_id).first()
            orgao = edital.orgao if edital else "Desconhecido"
            if orgao not in por_orgao:
                por_orgao[orgao] = []
            por_orgao[orgao].append(dias)

        media_global = round(sum(tempos) / max(len(tempos), 1), 1)

        faixas = {"0-30": 0, "31-60": 0, "61-90": 0, ">90": 0}
        for d in tempos:
            if d <= 30:
                faixas["0-30"] += 1
            elif d <= 60:
                faixas["31-60"] += 1
            elif d <= 90:
                faixas["61-90"] += 1
            else:
                faixas[">90"] += 1

        orgaos = []
        for org, dias_list in por_orgao.items():
            media = round(sum(dias_list) / len(dias_list), 1)
            badge = "Rápido" if media <= 30 else ("Normal" if media <= 60 else "Lento")
            orgaos.append({"orgao": org, "media_dias": media, "contratos": len(dias_list), "badge": badge})

        return jsonify({
            "media_global": media_global,
            "total_contratos": len(tempos),
            "sem_empenho": sem_empenho,
            "distribuicao": faixas,
            "por_orgao": sorted(orgaos, key=lambda x: x["media_dias"]),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/contratos/<contrato_id>/dre", methods=["GET"])
@require_auth
def api_dre_contrato(contrato_id):
    """UC-SC05: DRE simplificado por contrato."""
    from tools import tool_dre_contrato
    empresa_id = get_current_empresa_id()
    result = tool_dre_contrato(contrato_id=contrato_id, user_id=get_current_user_id(), empresa_id=empresa_id)
    return jsonify(result), 200 if result.get("success") else 400


@app.route("/api/precificacao/<edital_id>/simular-dre", methods=["POST"])
@require_auth
def api_simular_dre(edital_id):
    """UC-SC05: DRE simulado por edital."""
    from tools import tool_dre_contrato
    empresa_id = get_current_empresa_id()
    result = tool_dre_contrato(edital_id=edital_id, user_id=get_current_user_id(), empresa_id=empresa_id)
    return jsonify(result), 200 if result.get("success") else 400


@app.route("/api/health", methods=["GET"])
def api_health():
    """UC-HC01: Health check público — sem autenticação (RN-NEW-20)."""
    import time
    from sqlalchemy import text as sa_text
    services = []

    # Database
    try:
        t0 = time.time()
        db = get_db()
        db.execute(sa_text("SELECT 1"))
        db.close()
        services.append({"name": "database", "status": "healthy", "latency_ms": round((time.time() - t0) * 1000, 1)})
    except Exception as e:
        services.append({"name": "database", "status": "unhealthy", "latency_ms": 0, "message": str(e)})

    # PNCP
    try:
        t0 = time.time()
        import requests as req
        resp = req.get("https://pncp.gov.br/api/consulta/v1/contratacoes", timeout=5)
        st = "healthy" if resp.status_code < 500 else "degraded"
        services.append({"name": "pncp", "status": st, "latency_ms": round((time.time() - t0) * 1000, 1)})
    except Exception:
        services.append({"name": "pncp", "status": "degraded", "latency_ms": 0, "message": "timeout"})

    # DeepSeek
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    services.append({
        "name": "deepseek",
        "status": "healthy" if deepseek_key else "degraded",
        "latency_ms": 0,
        "message": "key configured" if deepseek_key else "no API key",
    })

    # Brave
    brave_key = os.environ.get("BRAVE_API_KEY", "") or os.environ.get("SCRAPE_API_KEY", "")
    services.append({
        "name": "brave",
        "status": "healthy" if brave_key else "degraded",
        "latency_ms": 0,
    })

    # SMTP
    smtp_host = os.environ.get("SMTP_SERVER", "") or os.environ.get("SMTP_HOST", "")
    services.append({
        "name": "smtp",
        "status": "healthy" if smtp_host else "degraded",
        "latency_ms": 0,
    })

    # Cache
    services.append({"name": "cache", "status": "healthy", "latency_ms": 0})

    # Scheduler
    services.append({"name": "scheduler", "status": "healthy", "latency_ms": 0})

    unhealthy_count = sum(1 for s in services if s["status"] == "unhealthy")
    db_down = any(s["name"] == "database" and s["status"] == "unhealthy" for s in services)

    if db_down or unhealthy_count >= 3:
        status_global = "unhealthy"
        http_code = 503
    elif any(s["status"] != "healthy" for s in services):
        status_global = "degraded"
        http_code = 200
    else:
        status_global = "healthy"
        http_code = 200

    return jsonify({
        "status": status_global,
        "version": "9.0.0",
        "timestamp": datetime.now().isoformat(),
        "services": services,
    }), http_code


# =============================================================================
# Dashboard de Mercado — MercadoPage.tsx
# =============================================================================

@app.route("/api/dashboard/mercado", methods=["GET"])
@require_auth
def api_dashboard_mercado():
    from models import Edital, EditalItem
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        periodo_dias = int(request.args.get("periodo_dias", 180))
        desde = datetime.now() - timedelta(days=periodo_dias)

        editais = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.created_at >= desde,
        ).all()

        meses = {}
        for e in editais:
            if not e.created_at:
                continue
            chave = e.created_at.strftime("%b/%y")
            if chave not in meses:
                meses[chave] = {"mes": chave, "quantidade": 0, "valorTotal": 0}
            meses[chave]["quantidade"] += 1
            meses[chave]["valorTotal"] += float(e.valor_referencia or 0)

        categorias = {}
        itens = db.query(EditalItem).join(
            Edital, EditalItem.edital_id == Edital.id
        ).filter(
            Edital.empresa_id == empresa_id,
            Edital.created_at >= desde,
        ).all()
        for item in itens:
            cat = (item.descricao_completa or "Sem categoria")[:50]
            if cat not in categorias:
                categorias[cat] = {"categoria": cat, "quantidade": 0, "valores": []}
            categorias[cat]["quantidade"] += 1
            if item.valor_unitario:
                categorias[cat]["valores"].append(float(item.valor_unitario))

        for c in categorias.values():
            c["valorMedio"] = sum(c["valores"]) / max(len(c["valores"]), 1) if c["valores"] else 0
            del c["valores"]

        total_qtd = sum(c["quantidade"] for c in categorias.values()) or 1
        for c in categorias.values():
            c["percentual"] = round(c["quantidade"] / total_qtd * 100, 1)

        top_categorias = sorted(categorias.values(), key=lambda x: x["quantidade"], reverse=True)[:10]

        return jsonify({
            "tendencias": sorted(meses.values(), key=lambda x: x["mes"]),
            "categorias": top_categorias,
            "total_editais": len(editais),
            "valor_total": sum(float(e.valor_referencia or 0) for e in editais),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ---- Cronograma de Entregas (UC-CT03) ----

@app.route('/api/contratos/<contrato_id>/cronograma', methods=['GET'])
@require_auth
def api_contrato_cronograma(contrato_id):
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        contrato = db.query(Contrato).filter_by(id=contrato_id, empresa_id=empresa_id).first()
        if not contrato:
            return jsonify({"error": "Contrato não encontrado"}), 404

        entregas = db.query(ContratoEntrega).filter_by(contrato_id=contrato_id).order_by(ContratoEntrega.data_prevista).all()
        now = datetime.now()

        semanas = {}
        atrasados = []
        proximos_7d = []
        now_date = now.date() if hasattr(now, 'date') else now

        for e in entregas:
            ed = e.to_dict()
            # Normalizar data_prevista para date
            dp = e.data_prevista
            if hasattr(dp, 'date'):
                dp = dp.date()
            elif not dp:
                continue
            if dp:
                # Agrupar por semana
                week_start = dp - timedelta(days=dp.weekday())
                week_key = week_start.strftime('%Y-%m-%d')
                if week_key not in semanas:
                    semanas[week_key] = []
                semanas[week_key].append(ed)

                # Atrasados
                if e.status != 'entregue' and dp < now_date:
                    ed['dias_atraso'] = (now_date - dp).days
                    atrasados.append(ed)

                # Próximos 7 dias
                dias_ate = (dp - now_date).days
                if 0 <= dias_ate <= 7 and e.status != 'entregue':
                    ed['dias_restantes'] = dias_ate
                    proximos_7d.append(ed)

        stats = {
            "pendentes": sum(1 for e in entregas if e.status == 'pendente'),
            "entregues": sum(1 for e in entregas if e.status == 'entregue'),
            "atrasados": len(atrasados),
            "total": len(entregas),
        }

        return jsonify({
            "contrato": contrato.to_dict(),
            "stats": stats,
            "semanas": semanas,
            "atrasados": atrasados,
            "proximos_7d": proximos_7d,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ---- Aditivos (UC-CT04) ----

@app.route('/api/contratos/<contrato_id>/aditivos', methods=['GET', 'POST'])
@require_auth
def api_contrato_aditivos(contrato_id):
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        contrato = db.query(Contrato).filter_by(id=contrato_id, empresa_id=empresa_id).first()
        if not contrato:
            return jsonify({"error": "Contrato não encontrado"}), 404

        if request.method == 'GET':
            aditivos = db.query(ContratoAditivo).filter_by(contrato_id=contrato_id).order_by(ContratoAditivo.created_at.desc()).all()
            total_aditivos = sum(float(a.valor_aditivo or 0) for a in aditivos if a.tipo in ('acrescimo',))
            total_supressoes = sum(abs(float(a.valor_aditivo or 0)) for a in aditivos if a.tipo == 'supressao')
            valor_original = float(contrato.valor_total or 0)
            limite_25 = valor_original * 0.25
            pct_consumido = (total_aditivos / valor_original * 100) if valor_original > 0 else 0
            return jsonify({
                "aditivos": [a.to_dict() for a in aditivos],
                "resumo": {
                    "valor_original": valor_original,
                    "total_acrescimos": total_aditivos,
                    "total_supressoes": total_supressoes,
                    "limite_25_pct": limite_25,
                    "pct_consumido": round(pct_consumido, 2),
                }
            })

        # POST
        data = request.get_json()
        aditivo = ContratoAditivo(
            contrato_id=contrato_id,
            user_id=user_id,
            tipo=data.get('tipo', 'acrescimo'),
            justificativa=data.get('justificativa', ''),
            valor_original=float(contrato.valor_total or 0),
            valor_aditivo=float(data.get('valor_aditivo', 0)),
            percentual=float(data.get('percentual', 0)),
            data_aditivo=datetime.fromisoformat(data['data_aditivo']) if data.get('data_aditivo') else datetime.now(),
            nova_data_fim=datetime.fromisoformat(data['nova_data_fim']) if data.get('nova_data_fim') else None,
            fundamentacao_legal=data.get('fundamentacao_legal', ''),
            status=data.get('status', 'rascunho'),
            observacoes=data.get('observacoes', ''),
        )
        db.add(aditivo)
        db.commit()
        return jsonify({"success": True, "aditivo": aditivo.to_dict()}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route('/api/contratos/<contrato_id>/aditivos/<aditivo_id>', methods=['PUT', 'DELETE'])
@require_auth
def api_contrato_aditivo_detail(contrato_id, aditivo_id):
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        aditivo = db.query(ContratoAditivo).filter_by(id=aditivo_id, contrato_id=contrato_id, empresa_id=empresa_id).first()
        if not aditivo:
            return jsonify({"error": "Aditivo não encontrado"}), 404

        if request.method == 'DELETE':
            db.delete(aditivo)
            db.commit()
            return jsonify({"success": True})

        # PUT
        data = request.get_json()
        for field in ['tipo', 'justificativa', 'fundamentacao_legal', 'status', 'observacoes']:
            if field in data:
                setattr(aditivo, field, data[field])
        if 'valor_aditivo' in data:
            aditivo.valor_aditivo = float(data['valor_aditivo'])
        if 'data_aditivo' in data:
            aditivo.data_aditivo = datetime.fromisoformat(data['data_aditivo'])
        if 'nova_data_fim' in data:
            aditivo.nova_data_fim = datetime.fromisoformat(data['nova_data_fim'])
        db.commit()
        return jsonify({"success": True, "aditivo": aditivo.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ---- Designações (UC-CT05) ----

@app.route('/api/contratos/<contrato_id>/designacoes', methods=['GET', 'POST'])
@require_auth
def api_contrato_designacoes(contrato_id):
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        contrato = db.query(Contrato).filter_by(id=contrato_id, empresa_id=empresa_id).first()
        if not contrato:
            return jsonify({"error": "Contrato não encontrado"}), 404

        if request.method == 'GET':
            designacoes = db.query(ContratoDesignacao).filter_by(contrato_id=contrato_id).all()
            return jsonify([d.to_dict() for d in designacoes])

        # POST
        data = request.get_json()
        designacao = ContratoDesignacao(
            contrato_id=contrato_id,
            user_id=user_id,
            tipo=data.get('tipo', 'gestor'),
            nome=data.get('nome', ''),
            cargo=data.get('cargo', ''),
            cpf=data.get('cpf', ''),
            portaria_numero=data.get('portaria_numero', ''),
            data_inicio=datetime.fromisoformat(data['data_inicio']) if data.get('data_inicio') else datetime.now(),
            data_fim=datetime.fromisoformat(data['data_fim']) if data.get('data_fim') else None,
        )
        db.add(designacao)
        db.commit()
        return jsonify({"success": True, "designacao": designacao.to_dict()}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route('/api/contratos/<contrato_id>/designacoes/<designacao_id>', methods=['PUT', 'DELETE'])
@require_auth
def api_contrato_designacao_detail(contrato_id, designacao_id):
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        desig = db.query(ContratoDesignacao).filter_by(id=designacao_id, contrato_id=contrato_id, empresa_id=empresa_id).first()
        if not desig:
            return jsonify({"error": "Designação não encontrada"}), 404

        if request.method == 'DELETE':
            db.delete(desig)
            db.commit()
            return jsonify({"success": True})

        data = request.get_json()
        for field in ['tipo', 'nome', 'cargo', 'cpf', 'portaria_numero', 'observacoes']:
            if field in data:
                setattr(desig, field, data[field])
        if 'ativo' in data:
            desig.ativo = data['ativo']
        if 'data_fim' in data:
            desig.data_fim = datetime.fromisoformat(data['data_fim'])
        db.commit()
        return jsonify({"success": True, "designacao": desig.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route('/api/contratos/<contrato_id>/designacoes/<designacao_id>/atividades', methods=['GET', 'POST'])
@require_auth
def api_contrato_atividades(contrato_id, designacao_id):
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        if request.method == 'GET':
            atividades = db.query(AtividadeFiscal).filter_by(designacao_id=designacao_id, empresa_id=empresa_id).order_by(AtividadeFiscal.data_atividade.desc()).all()
            return jsonify([a.to_dict() for a in atividades])

        data = request.get_json()
        atividade = AtividadeFiscal(
            designacao_id=designacao_id,
            user_id=user_id,
            tipo=data.get('tipo', 'atesto'),
            descricao=data.get('descricao', ''),
            data_atividade=datetime.fromisoformat(data['data_atividade']) if data.get('data_atividade') else datetime.now(),
            arquivo_path=data.get('arquivo_path', ''),
        )
        db.add(atividade)
        db.commit()
        return jsonify({"success": True, "atividade": atividade.to_dict()}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ---- ARP Saldos e Caronas (UC-CT06) ----

@app.route('/api/atas/<ata_id>/saldos', methods=['GET', 'POST'])
@require_auth
def api_ata_saldos(ata_id):
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        if request.method == 'GET':
            saldos = db.query(ARPSaldo).filter_by(ata_id=ata_id, empresa_id=empresa_id).all()
            return jsonify([s.to_dict() for s in saldos])

        data = request.get_json()
        qtd_reg = float(data.get('quantidade_registrada', 0))
        saldo = ARPSaldo(
            ata_id=ata_id,
            user_id=user_id,
            item_descricao=data.get('item_descricao', ''),
            catmat_catser=data.get('catmat_catser', ''),
            unidade=data.get('unidade', ''),
            quantidade_registrada=qtd_reg,
            saldo_disponivel=qtd_reg,
            valor_unitario=float(data.get('valor_unitario', 0)) if data.get('valor_unitario') else None,
        )
        db.add(saldo)
        db.commit()
        return jsonify({"success": True, "saldo": saldo.to_dict()}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route('/api/atas/<ata_id>/saldos/<saldo_id>/caronas', methods=['GET', 'POST'])
@require_auth
def api_ata_caronas(ata_id, saldo_id):
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        saldo = db.query(ARPSaldo).filter_by(id=saldo_id, ata_id=ata_id, empresa_id=empresa_id).first()
        if not saldo:
            return jsonify({"error": "Saldo ARP não encontrado"}), 404

        if request.method == 'GET':
            caronas = db.query(SolicitacaoCarona).filter_by(arp_saldo_id=saldo_id).order_by(SolicitacaoCarona.created_at.desc()).all()
            return jsonify([c.to_dict() for c in caronas])

        # POST — validar limites Lei 14.133 (50% individual, 2x global)
        data = request.get_json()
        qtd_solicitada = float(data.get('quantidade_solicitada', 0))
        qtd_registrada = float(saldo.quantidade_registrada or 0)

        # Limite individual: 50% do registrado por órgão
        orgao = data.get('orgao_solicitante', '')
        consumo_orgao = db.query(SolicitacaoCarona).filter_by(
            arp_saldo_id=saldo_id, orgao_solicitante=orgao, status='aprovada'
        ).all()
        total_orgao = sum(float(c.quantidade_solicitada or 0) for c in consumo_orgao) + qtd_solicitada
        limite_individual = qtd_registrada * 0.5
        if total_orgao > limite_individual:
            return jsonify({"error": f"Limite individual (50%) excedido. Máximo: {limite_individual}, Solicitado total: {total_orgao}"}), 400

        # Limite global: 2x do registrado
        todas_caronas = db.query(SolicitacaoCarona).filter_by(arp_saldo_id=saldo_id, status='aprovada').all()
        total_global = sum(float(c.quantidade_solicitada or 0) for c in todas_caronas) + qtd_solicitada
        limite_global = qtd_registrada * 2
        if total_global > limite_global:
            return jsonify({"error": f"Limite global (2x) excedido. Máximo: {limite_global}, Total: {total_global}"}), 400

        carona = SolicitacaoCarona(
            arp_saldo_id=saldo_id,
            user_id=user_id,
            orgao_solicitante=orgao,
            cnpj_solicitante=data.get('cnpj_solicitante', ''),
            quantidade_solicitada=qtd_solicitada,
            valor_unitario=float(saldo.valor_unitario or 0),
            justificativa=data.get('justificativa', ''),
        )
        db.add(carona)
        db.commit()
        return jsonify({"success": True, "carona": carona.to_dict()}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route('/api/atas/<ata_id>/saldos/<saldo_id>/caronas/<carona_id>', methods=['PUT'])
@require_auth
def api_ata_carona_detail(ata_id, saldo_id, carona_id):
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        carona = db.query(SolicitacaoCarona).filter_by(id=carona_id, arp_saldo_id=saldo_id, empresa_id=empresa_id).first()
        if not carona:
            return jsonify({"error": "Solicitação não encontrada"}), 404

        data = request.get_json()
        if 'status' in data:
            carona.status = data['status']
            if data['status'] in ('aprovada', 'recusada'):
                carona.data_resposta = datetime.now()
                # Atualizar saldo se aprovada
                if data['status'] == 'aprovada':
                    saldo = db.query(ARPSaldo).filter_by(id=saldo_id).first()
                    if saldo:
                        saldo.consumido_carona = (saldo.consumido_carona or 0) + float(carona.quantidade_solicitada or 0)
                        saldo.saldo_disponivel = float(saldo.quantidade_registrada or 0) - float(saldo.consumido_participante or 0) - float(saldo.consumido_carona or 0)
        if 'observacoes' in data:
            carona.observacoes = data['observacoes']
        db.commit()
        return jsonify({"success": True, "carona": carona.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# ---- Alertas de Vencimento Multi-tier (UC-CR03) ----

@app.route('/api/alertas-vencimento/regras', methods=['GET', 'PUT'])
@require_auth
def api_alertas_vencimento_regras():
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        if request.method == 'GET':
            regras = db.query(AlertaVencimentoRegra).filter_by(empresa_id=empresa_id).all()
            return jsonify([r.to_dict() for r in regras])

        # PUT — upsert rules
        data = request.get_json()
        regras_data = data if isinstance(data, list) else [data]
        results = []
        for rd in regras_data:
            tipo = rd.get('tipo_entidade')
            regra = db.query(AlertaVencimentoRegra).filter_by(empresa_id=empresa_id, tipo_entidade=tipo).first()
            if not regra:
                regra = AlertaVencimentoRegra(empresa_id=empresa_id, tipo_entidade=tipo)
                db.add(regra)
            for field in ['dias_30', 'dias_15', 'dias_7', 'dias_1', 'canal_email', 'canal_push', 'canal_whatsapp', 'escalation_enabled', 'escalation_email', 'ativo']:
                if field in rd:
                    setattr(regra, field, rd[field])
            results.append(regra)
        db.commit()
        return jsonify([r.to_dict() for r in results])
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route('/api/alertas-vencimento/consolidado', methods=['GET'])
@require_auth
def api_alertas_vencimento_consolidado():
    db = get_db()
    try:
        user_id = get_current_user_id()
        empresa_id = get_current_empresa_id()
        result = tool_alertas_vencimento_multi_tier(user_id, empresa_id=empresa_id, db=db)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Sprint 6 — SMTP endpoints
# =============================================================================

@app.route("/api/smtp/testar", methods=["POST"])
@require_auth
def smtp_testar():
    data = request.get_json() or {}
    destinatario = data.get("destinatario_teste")
    if not destinatario:
        return jsonify({"error": "destinatario_teste obrigatório"}), 400
    from smtp_service import SMTPService
    svc = SMTPService()
    ok, msg = svc.test_config(destinatario, empresa_id=getattr(request, "empresa_id", None))
    return jsonify({"success": ok, "message": msg}), 200 if ok else 500


@app.route("/api/smtp/fila/reenviar/<queue_id>", methods=["POST"])
@require_auth
def smtp_reenviar(queue_id):
    db = get_db()
    try:
        from models import EmailQueue
        item = db.query(EmailQueue).filter(EmailQueue.id == queue_id).first()
        if not item:
            return jsonify({"error": "Item não encontrado"}), 404
        if item.status not in ("failed", "bounce"):
            return jsonify({"error": f"Só pode reenviar itens failed/bounce (atual: {item.status})"}), 400
        item.status = "pending"
        item.retry_count = 0
        item.erro_mensagem = None
        db.commit()
        return jsonify({"success": True, "message": f"Item {queue_id} reenfileirado"})
    finally:
        db.close()


# =============================================================================
# Monitoramento — Executar Agora
# =============================================================================

@app.route("/api/monitoramentos/<mon_id>/executar", methods=["POST"])
@require_auth
def monitoramento_executar(mon_id):
    db = get_db()
    try:
        from models import Monitoramento
        mon = db.query(Monitoramento).filter(Monitoramento.id == mon_id).first()
        if not mon:
            return jsonify({"error": "Monitoramento nao encontrado"}), 404
        from datetime import datetime
        mon.ultimo_check = None
        mon.proximo_check = datetime.utcnow()
        mon.ativo = True
        db.commit()
        return jsonify({"success": True, "message": f"Monitoramento '{mon.termo}' enfileirado para execucao"})
    finally:
        db.close()


# =============================================================================
# SPRINT 7 — Mercado TAM/SAM/SOM, Analytics, Aprendizado
# =============================================================================

@app.route("/api/dashboard/mercado/tam-sam-som", methods=["GET"])
@require_auth
def api_mercado_tam_sam_som():
    from models import Edital, Produto, ParametroScore, PrecoHistorico
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        segmento = request.args.get("segmento", "todos")
        periodo_dias = int(request.args.get("periodo_dias", 365))
        desde = datetime.now() - timedelta(days=periodo_dias)

        editais_q = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.created_at >= desde,
        )
        if segmento != "todos":
            editais_q = editais_q.filter(
                func.lower(Edital.categoria).contains(segmento.lower())
            )
        editais = editais_q.all()

        tam_qtd = len(editais)
        tam_valor = sum(float(e.valor_referencia or 0) for e in editais)

        params = db.query(ParametroScore).filter_by(empresa_id=empresa_id).first()
        ufs_atuacao = []
        if params and params.estados_atuacao:
            ufs_atuacao = params.estados_atuacao if isinstance(params.estados_atuacao, list) else []

        produtos = db.query(Produto).filter_by(empresa_id=empresa_id).all()
        ncms_portfolio = set(p.ncm for p in produtos if p.ncm)

        sam_editais = []
        for e in editais:
            if ufs_atuacao and e.uf and e.uf.upper() not in [u.upper() for u in ufs_atuacao]:
                continue
            sam_editais.append(e)

        sam_qtd = len(sam_editais)
        sam_valor = sum(float(e.valor_referencia or 0) for e in sam_editais)

        total_participados = db.query(PrecoHistorico).join(
            Edital, PrecoHistorico.edital_id == Edital.id
        ).filter(Edital.empresa_id == empresa_id).count()
        total_ganhos = db.query(PrecoHistorico).join(
            Edital, PrecoHistorico.edital_id == Edital.id
        ).filter(Edital.empresa_id == empresa_id, PrecoHistorico.resultado == 'vitoria').count()
        taxa_vitoria = total_ganhos / max(total_participados, 1)
        fator_capacidade = 0.8

        som_qtd = int(sam_qtd * taxa_vitoria * fator_capacidade)
        som_valor = sam_valor * taxa_vitoria * fator_capacidade

        cobertura = round(sam_qtd / max(tam_qtd, 1) * 100, 1)
        penetracao = round(som_qtd / max(sam_qtd, 1) * 100, 1)

        meses = {}
        for e in editais:
            if not e.created_at:
                continue
            chave = e.created_at.strftime("%Y-%m")
            if chave not in meses:
                meses[chave] = {"mes": chave, "quantidade": 0, "valor": 0, "som": 0}
            meses[chave]["quantidade"] += 1
            meses[chave]["valor"] += float(e.valor_referencia or 0)
        for m in meses.values():
            m["som"] = int(m["quantidade"] * taxa_vitoria * fator_capacidade)
        tendencias = sorted(meses.values(), key=lambda x: x["mes"])

        cat_map = {}
        for e in editais:
            cat = e.categoria or "Outros"
            if cat not in cat_map:
                cat_map[cat] = {"categoria": cat, "quantidade": 0, "valor": 0}
            cat_map[cat]["quantidade"] += 1
            cat_map[cat]["valor"] += float(e.valor_referencia or 0)
        for c in cat_map.values():
            c["percentual"] = round(c["quantidade"] / max(tam_qtd, 1) * 100, 1)
            c["valorMedio"] = c["valor"] / max(c["quantidade"], 1)
        categorias = sorted(cat_map.values(), key=lambda x: x["quantidade"], reverse=True)[:10]

        seg_precos = {}
        for e in editais:
            if not e.created_at or not e.valor_referencia:
                continue
            seg = e.categoria or "Outros"
            mes = e.created_at.strftime("%Y-%m")
            key = (seg, mes)
            if key not in seg_precos:
                seg_precos[key] = {"segmento": seg, "mes": mes, "valores": []}
            seg_precos[key]["valores"].append(float(e.valor_referencia))
        evolucao_precos = []
        for v in seg_precos.values():
            evolucao_precos.append({
                "segmento": v["segmento"],
                "mes": v["mes"],
                "preco_medio": sum(v["valores"]) / len(v["valores"])
            })
        evolucao_precos.sort(key=lambda x: (x["segmento"], x["mes"]))

        return jsonify({
            "tam": {"qtd": tam_qtd, "valor": round(tam_valor, 2)},
            "sam": {"qtd": sam_qtd, "valor": round(sam_valor, 2), "cobertura_pct": cobertura},
            "som": {"qtd": som_qtd, "valor": round(som_valor, 2), "penetracao_pct": penetracao},
            "stat_cards": {
                "editais_periodo": tam_qtd,
                "valor_total_tam": round(tam_valor, 2),
                "valor_medio": round(tam_valor / max(tam_qtd, 1), 2),
                "taxa_penetracao": penetracao,
                "taxa_vitoria": round(taxa_vitoria * 100, 1),
                "ufs_atuacao": len(ufs_atuacao),
                "ncms_portfolio": len(ncms_portfolio),
                "participados": total_participados,
            },
            "tendencias": tendencias,
            "categorias": categorias,
            "evolucao_precos": evolucao_precos,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/dashboard/mercado/intrusos", methods=["GET"])
@require_auth
def api_mercado_intrusos_list():
    from models import ItemIntruso, Edital
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        criticidade = request.args.get("criticidade", "todos")
        periodo_dias = int(request.args.get("periodo_dias", 365))
        busca = request.args.get("busca", "")
        desde = datetime.now() - timedelta(days=periodo_dias)

        q = db.query(ItemIntruso).filter(
            ItemIntruso.empresa_id == empresa_id,
            ItemIntruso.created_at >= desde,
        )
        if criticidade != "todos":
            q = q.filter(ItemIntruso.criticidade == criticidade)

        intrusos = q.order_by(ItemIntruso.created_at.desc()).all()

        result = []
        editais_afetados = set()
        valor_risco = 0
        for it in intrusos:
            ed = db.query(Edital).filter(Edital.id == it.edital_id).first()
            edital_num = ed.numero if ed else "—"
            if busca and busca.lower() not in (edital_num or "").lower():
                continue
            editais_afetados.add(it.edital_id)
            valor_risco += float(it.valor or 0)
            result.append(it.to_dict() | {"edital_numero": edital_num})

        return jsonify({
            "intrusos": result,
            "stat_cards": {
                "total": len(result),
                "editais_afetados": len(editais_afetados),
                "valor_risco": round(valor_risco, 2),
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/mercado/detectar-intrusos", methods=["POST"])
@require_auth
def api_mercado_detectar_intrusos():
    from models import ItemIntruso, Edital, EditalItem, Produto
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        data = request.get_json() or {}
        edital_id = data.get("edital_id")
        if not edital_id:
            return jsonify({"error": "edital_id obrigatorio"}), 400

        edital = db.query(Edital).filter(Edital.id == edital_id, Edital.empresa_id == empresa_id).first()
        if not edital:
            return jsonify({"error": "Edital nao encontrado"}), 404

        itens = db.query(EditalItem).filter(EditalItem.edital_id == edital_id).all()
        if not itens:
            return jsonify({"error": "Edital sem itens detalhados"}), 400

        produtos = db.query(Produto).filter(Produto.empresa_id == empresa_id).all()
        ncms_portfolio = set(p.ncm for p in produtos if p.ncm)

        valor_total_edital = sum(float(i.valor_total or i.valor_unitario or 0) for i in itens) or 1
        intrusos_criados = []

        for item in itens:
            ncm_item = (item.ncm or "").strip()
            if not ncm_item or ncm_item in ncms_portfolio:
                continue
            valor_item = float(item.valor_total or item.valor_unitario or 0)
            pct = round(valor_item / valor_total_edital * 100, 1)
            if pct > 10:
                crit = "critico"
            elif pct >= 5:
                crit = "medio"
            else:
                crit = "informativo"

            existing = db.query(ItemIntruso).filter_by(
                edital_id=edital_id, ncm=ncm_item, empresa_id=empresa_id
            ).first()
            if existing:
                continue

            intruso = ItemIntruso(
                user_id=user_id, empresa_id=empresa_id, edital_id=edital_id,
                descricao_item=item.descricao_completa or f"Item NCM {ncm_item}",
                ncm=ncm_item, valor=valor_item, percentual_edital=pct,
                criticidade=crit,
                acao_sugerida=f"Item com NCM {ncm_item} nao consta no portfolio. Verificar se e item intruso no edital."
            )
            db.add(intruso)
            intrusos_criados.append(intruso)

        db.commit()
        return jsonify({
            "intrusos": [i.to_dict() for i in intrusos_criados],
            "total": len(intrusos_criados),
        })
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/dashboard/mercado/share", methods=["GET"])
@require_auth
def api_mercado_share():
    from models import Concorrente, ParticipacaoEdital, PrecoHistorico, Edital
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        segmento = request.args.get("segmento", "todos")
        uf = request.args.get("uf", "todos")
        periodo_dias = int(request.args.get("periodo_dias", 365))
        desde = datetime.now() - timedelta(days=periodo_dias)

        conc_ids = db.query(ParticipacaoEdital.concorrente_id).join(
            Edital, ParticipacaoEdital.edital_id == Edital.id
        ).filter(
            Edital.empresa_id == empresa_id,
            ParticipacaoEdital.concorrente_id.isnot(None)
        ).distinct().all()
        conc_ids = [r[0] for r in conc_ids]
        concorrentes = db.query(Concorrente).filter(Concorrente.id.in_(conc_ids)).all() if conc_ids else []

        nosso_ganho = db.query(PrecoHistorico).join(
            Edital, PrecoHistorico.edital_id == Edital.id
        ).filter(Edital.empresa_id == empresa_id, PrecoHistorico.resultado == 'vitoria',
                 PrecoHistorico.data_registro >= desde).count()
        nosso_part = db.query(PrecoHistorico).join(
            Edital, PrecoHistorico.edital_id == Edital.id
        ).filter(Edital.empresa_id == empresa_id,
                 PrecoHistorico.resultado.in_(['vitoria', 'derrota']),
                 PrecoHistorico.data_registro >= desde).count()
        nossa_taxa = round(nosso_ganho / max(nosso_part, 1) * 100, 1)

        share = [{"nome": "Nossa Empresa", "percentual": nossa_taxa, "is_empresa": True}]
        tabela = []
        maior_ameaca = ""
        maior_vitorias = 0
        disputas_total = 0

        for c in concorrentes:
            taxa = round(c.editais_ganhos / max(c.editais_participados, 1) * 100, 1)
            share.append({"nome": c.nome, "percentual": taxa, "is_empresa": False})

            perdas_para = db.query(PrecoHistorico).join(
                Edital, PrecoHistorico.edital_id == Edital.id
            ).filter(
                Edital.empresa_id == empresa_id,
                PrecoHistorico.resultado == 'derrota',
                PrecoHistorico.empresa_vencedora.ilike(f"%{c.nome}%"),
                PrecoHistorico.data_registro >= desde,
            ).count()
            alerta = perdas_para >= 2

            tabela.append({
                "concorrente": c.nome,
                "cnpj": c.cnpj[:10] + "..." if c.cnpj and len(c.cnpj) > 10 else c.cnpj,
                "segmentos": c.segmentos,
                "participados": c.editais_participados,
                "ganhos": c.editais_ganhos,
                "taxa": taxa,
                "preco_medio": float(c.preco_medio) if c.preco_medio else 0,
                "alerta": alerta,
            })
            disputas_total += c.editais_participados
            if c.editais_ganhos > maior_vitorias:
                maior_vitorias = c.editais_ganhos
                maior_ameaca = c.nome

        share.sort(key=lambda x: x["percentual"], reverse=True)

        return jsonify({
            "share": share,
            "tabela": tabela,
            "stat_cards": {
                "concorrentes": len(concorrentes),
                "nossa_taxa": nossa_taxa,
                "maior_ameaca": maior_ameaca or "—",
                "disputas_juntos": disputas_total,
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/dashboard/analytics/funil", methods=["GET"])
@require_auth
def api_analytics_funil():
    from models import Edital
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        periodo_dias = int(request.args.get("periodo_dias", 365))
        desde = datetime.now() - timedelta(days=periodo_dias)

        STAGES = [
            "captado_nao_divulgado", "captado_divulgado", "em_analise", "lead_potencial",
            "monitoramento_concorrencia", "em_impugnacao", "fase_propostas",
            "proposta_submetida", "espera_resultado", "ganho_provisorio",
            "processo_recurso", "contra_razao", "resultado_definitivo"
        ]
        STAGE_LABELS = {
            "captado_nao_divulgado": "Nao Divulgados", "captado_divulgado": "Divulgados",
            "em_analise": "Em Analise", "lead_potencial": "Leads Potenciais",
            "monitoramento_concorrencia": "Monit. Concorrencia", "em_impugnacao": "Em Impugnacao",
            "fase_propostas": "Fase Propostas", "proposta_submetida": "Proposta Submetida",
            "espera_resultado": "Espera Resultado", "ganho_provisorio": "Ganho Provisorio",
            "processo_recurso": "Processo Recurso", "contra_razao": "Contra Razao",
            "resultado_definitivo": "Resultado Definitivo"
        }

        editais = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.created_at >= desde,
        ).all()

        stage_counts = {s: 0 for s in STAGES}
        stage_values = {s: 0.0 for s in STAGES}
        acum = {s: 0 for s in STAGES}

        for e in editais:
            stage = e.pipeline_stage or "captado_nao_divulgado"
            idx = STAGES.index(stage) if stage in STAGES else 0
            for i in range(idx + 1):
                acum[STAGES[i]] += 1
            stage_counts[stage] += 1
            stage_values[stage] += float(e.valor_referencia or 0)

        funil = []
        for i, s in enumerate(STAGES):
            entrada = acum[s]
            saida = acum[STAGES[i + 1]] if i + 1 < len(STAGES) else acum[s]
            conv = round(saida / max(entrada, 1) * 100, 1) if i + 1 < len(STAGES) else 100
            cor = "verde" if conv > 60 else ("amarelo" if conv > 30 else "vermelho")
            funil.append({
                "stage": s, "label": STAGE_LABELS.get(s, s), "quantidade": acum[s],
                "valor": round(stage_values[s], 2), "conversao_pct": conv, "cor": cor,
            })

        analisados = sum(1 for e in editais if e.pipeline_stage in ["em_analise", "lead_potencial"])
        participados = sum(1 for e in editais if e.pipeline_stage in [
            "fase_propostas", "proposta_submetida", "espera_resultado",
            "ganho_provisorio", "processo_recurso", "contra_razao", "resultado_definitivo"
        ])
        resultado = sum(1 for e in editais if e.pipeline_stage == "resultado_definitivo")

        return jsonify({
            "funil": funil,
            "stat_cards": {
                "total_pipeline": len(editais),
                "analisados": analisados,
                "participados": participados,
                "resultado_definitivo": resultado,
            },
            "tabela": funil,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/dashboard/analytics/conversoes", methods=["GET"])
@require_auth
def api_analytics_conversoes():
    from models import Edital, PrecoHistorico, Monitoramento
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        periodo_dias = int(request.args.get("periodo_dias", 365))
        desde = datetime.now() - timedelta(days=periodo_dias)
        desde_anterior = desde - timedelta(days=periodo_dias)

        def calc_taxa(filtro_extra=None, desde_d=desde):
            q = db.query(PrecoHistorico).join(
                Edital, PrecoHistorico.edital_id == Edital.id
            ).filter(Edital.empresa_id == empresa_id, PrecoHistorico.data_registro >= desde_d,
                     PrecoHistorico.resultado.in_(['vitoria', 'derrota']))
            if filtro_extra:
                q = q.filter(filtro_extra)
            total = q.count()
            ganhos = q.filter(PrecoHistorico.resultado == 'vitoria').count()
            return round(ganhos / max(total, 1) * 100, 1), total, ganhos

        taxa_geral, _, _ = calc_taxa()
        taxa_geral_ant, _, _ = calc_taxa(desde_d=desde_anterior)

        tipos_map = {}
        editais = db.query(Edital).filter(Edital.empresa_id == empresa_id, Edital.created_at >= desde).all()
        for e in editais:
            tipo = e.modalidade or "Outro"
            if tipo not in tipos_map:
                tipos_map[tipo] = {"tipo": tipo, "participados": 0, "ganhos": 0}
        precos = db.query(PrecoHistorico).join(
            Edital, PrecoHistorico.edital_id == Edital.id
        ).filter(Edital.empresa_id == empresa_id, PrecoHistorico.data_registro >= desde,
                 PrecoHistorico.resultado.in_(['vitoria', 'derrota'])).all()
        for p in precos:
            ed = db.query(Edital).filter(Edital.id == p.edital_id).first()
            tipo = ed.modalidade or "Outro" if ed else "Outro"
            if tipo not in tipos_map:
                tipos_map[tipo] = {"tipo": tipo, "participados": 0, "ganhos": 0}
            tipos_map[tipo]["participados"] += 1
            if p.resultado == 'vitoria':
                tipos_map[tipo]["ganhos"] += 1
        por_tipo = []
        for v in tipos_map.values():
            v["taxa"] = round(v["ganhos"] / max(v["participados"], 1) * 100, 1)
            v["benchmark"] = 0
            por_tipo.append(v)

        uf_map = {}
        for p in precos:
            ed = db.query(Edital).filter(Edital.id == p.edital_id).first()
            uf_e = ed.uf or "N/A" if ed else "N/A"
            if uf_e not in uf_map:
                uf_map[uf_e] = {"uf": uf_e, "participados": 0, "ganhos": 0}
            uf_map[uf_e]["participados"] += 1
            if p.resultado == 'vitoria':
                uf_map[uf_e]["ganhos"] += 1
        por_uf = []
        melhor_uf = {"nome": "—", "taxa": 0}
        for v in uf_map.values():
            v["taxa"] = round(v["ganhos"] / max(v["participados"], 1) * 100, 1)
            v["benchmark"] = 0
            por_uf.append(v)
            if v["taxa"] > melhor_uf["taxa"]:
                melhor_uf = {"nome": v["uf"], "taxa": v["taxa"]}

        seg_map = {}
        for p in precos:
            ed = db.query(Edital).filter(Edital.id == p.edital_id).first()
            seg = ed.categoria or "Outros" if ed else "Outros"
            if seg not in seg_map:
                seg_map[seg] = {"segmento": seg, "participados": 0, "ganhos": 0}
            seg_map[seg]["participados"] += 1
            if p.resultado == 'vitoria':
                seg_map[seg]["ganhos"] += 1
        por_segmento = []
        melhor_seg = {"nome": "—", "taxa": 0}
        for v in seg_map.values():
            v["taxa"] = round(v["ganhos"] / max(v["participados"], 1) * 100, 1)
            v["benchmark"] = 0
            por_segmento.append(v)
            if v["taxa"] > melhor_seg["taxa"]:
                melhor_seg = {"nome": v["segmento"], "taxa": v["taxa"]}

        total_editais = len(editais)
        monit_count = db.query(Monitoramento).filter(Monitoramento.empresa_id == empresa_id).count()
        contrib_auto = round(monit_count / max(total_editais, 1) * 100, 1)

        return jsonify({
            "stat_cards": {
                "taxa_geral": taxa_geral,
                "melhor_segmento": f"{melhor_seg['nome']} ({melhor_seg['taxa']}%)",
                "melhor_uf": f"{melhor_uf['nome']} ({melhor_uf['taxa']}%)",
                "contribuicao_automatica": contrib_auto,
            },
            "por_tipo": por_tipo,
            "por_uf": por_uf,
            "por_segmento": por_segmento,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/dashboard/analytics/tempos", methods=["GET"])
@require_auth
def api_analytics_tempos():
    from models import Edital, Empenho, Contrato
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        periodo_dias = int(request.args.get("periodo_dias", 365))
        desde = datetime.now() - timedelta(days=periodo_dias)

        STAGES = [
            "captado_nao_divulgado", "captado_divulgado", "em_analise", "lead_potencial",
            "fase_propostas", "proposta_submetida", "espera_resultado", "resultado_definitivo"
        ]

        editais = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.created_at >= desde,
        ).all()

        timestamps = {}
        for e in editais:
            ts = {
                "captado_nao_divulgado": e.created_at,
                "captado_divulgado": e.data_publicacao or e.created_at,
                "em_analise": e.data_publicacao,
                "lead_potencial": e.data_publicacao,
                "fase_propostas": e.data_abertura or e.data_limite_proposta,
                "proposta_submetida": e.data_limite_proposta,
                "espera_resultado": e.data_limite_proposta,
                "resultado_definitivo": e.data_homologacao_prevista,
            }
            timestamps[e.id] = ts

        transicoes = []
        for i in range(len(STAGES) - 1):
            de_s, para_s = STAGES[i], STAGES[i + 1]
            dias_list = []
            for eid, ts in timestamps.items():
                d1, d2 = ts.get(de_s), ts.get(para_s)
                if d1 and d2 and d2 > d1:
                    dias_list.append((d2 - d1).days)
            if dias_list:
                media = round(sum(dias_list) / len(dias_list), 1)
                dias_list.sort()
                mediana = dias_list[len(dias_list) // 2]
                min_d, max_d = min(dias_list), max(dias_list)
                mean = sum(dias_list) / len(dias_list)
                desvio = round((sum((x - mean) ** 2 for x in dias_list) / len(dias_list)) ** 0.5, 1)
            else:
                media = mediana = min_d = max_d = desvio = 0
            cor = "verde" if media < 7 else ("amarelo" if media < 30 else "vermelho")
            transicoes.append({
                "de": de_s, "para": para_s,
                "media_dias": media, "mediana": mediana, "min": min_d, "max": max_d,
                "desvio": desvio, "cor": cor, "is_gargalo": False,
            })

        if transicoes:
            gargalo_idx = max(range(len(transicoes)), key=lambda i: transicoes[i]["media_dias"])
            transicoes[gargalo_idx]["is_gargalo"] = True
            mais_lenta = f"{transicoes[gargalo_idx]['de']} → {transicoes[gargalo_idx]['para']}"
            mais_lenta_dias = transicoes[gargalo_idx]["media_dias"]
            mais_rapida_idx = min(range(len(transicoes)), key=lambda i: transicoes[i]["media_dias"])
            mais_rapida = f"{transicoes[mais_rapida_idx]['de']} → {transicoes[mais_rapida_idx]['para']}"
        else:
            mais_lenta = mais_rapida = "—"
            mais_lenta_dias = 0

        tempo_total = sum(t["media_dias"] for t in transicoes)

        tempo_hom_empenho = 0
        contratos = db.query(Contrato).filter(Contrato.empresa_id == empresa_id).all()
        hom_emp_dias = []
        for c in contratos:
            if not c.edital_id:
                continue
            ed = db.query(Edital).filter(Edital.id == c.edital_id).first()
            if not ed or not ed.data_homologacao_prevista:
                continue
            emp = db.query(Empenho).filter(Empenho.contrato_id == c.id).order_by(Empenho.data_emissao).first()
            if emp and emp.data_emissao and emp.data_emissao > ed.data_homologacao_prevista:
                hom_emp_dias.append((emp.data_emissao - ed.data_homologacao_prevista).days)
        if hom_emp_dias:
            tempo_hom_empenho = round(sum(hom_emp_dias) / len(hom_emp_dias), 1)

        return jsonify({
            "transicoes": transicoes,
            "stat_cards": {
                "tempo_total_medio": round(tempo_total, 1),
                "etapa_mais_lenta": mais_lenta,
                "etapa_mais_lenta_dias": mais_lenta_dias,
                "etapa_mais_rapida": mais_rapida,
                "tempo_homologacao_empenho": tempo_hom_empenho,
            },
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/dashboard/analytics/roi", methods=["GET"])
@require_auth
def api_analytics_roi():
    from sqlalchemy import func
    from models import Edital, PrecoHistorico, Recurso, ItemIntruso
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        periodo_dias = int(request.args.get("periodo_dias", 365))
        desde = datetime.now() - timedelta(days=periodo_dias)

        ganhos = db.query(PrecoHistorico).join(
            Edital, PrecoHistorico.edital_id == Edital.id
        ).filter(Edital.empresa_id == empresa_id, PrecoHistorico.resultado == 'vitoria',
                 PrecoHistorico.data_registro >= desde).all()
        receita = sum(float(g.nosso_preco or 0) for g in ganhos)

        recursos_ok = db.query(Recurso).join(
            Edital, Recurso.edital_id == Edital.id
        ).filter(Edital.empresa_id == empresa_id,
                 Recurso.resultado == 'deferido',
                 Recurso.created_at >= desde).all()
        oportunidades = sum(float(r.valor_envolvido or 0) for r in recursos_ok) if recursos_ok else 0

        produtividade = 40 * 150 * (periodo_dias / 30)

        intrusos_val = db.query(func.sum(ItemIntruso.valor)).filter(
            ItemIntruso.empresa_id == empresa_id,
            ItemIntruso.created_at >= desde,
        ).scalar() or 0
        prevencao = float(intrusos_val)

        total_beneficio = receita + oportunidades + produtividade + prevencao
        custo_sistema = 5000 * (periodo_dias / 30)
        roi_pct = round(total_beneficio / max(custo_sistema, 1) * 100, 1)

        meses_roi = {}
        for g in ganhos:
            if not g.data_registro:
                continue
            mes = g.data_registro.strftime("%Y-%m")
            meses_roi[mes] = meses_roi.get(mes, 0) + float(g.nosso_preco or 0)
        evolucao = []
        acum_val = 0
        for m in sorted(meses_roi.keys()):
            acum_val += meses_roi[m]
            custo_mes = 5000 * (len(evolucao) + 1)
            evolucao.append({"mes": m, "roi_pct": round(acum_val / max(custo_mes, 1) * 100, 1)})

        componentes = [
            {"nome": "Receita Direta", "valor": round(receita, 2), "pct_total": round(receita / max(total_beneficio, 1) * 100, 1), "tendencia": "alta"},
            {"nome": "Oportunidades Salvas", "valor": round(oportunidades, 2), "pct_total": round(oportunidades / max(total_beneficio, 1) * 100, 1), "tendencia": "alta"},
            {"nome": "Produtividade", "valor": round(produtividade, 2), "pct_total": round(produtividade / max(total_beneficio, 1) * 100, 1), "tendencia": "estavel"},
            {"nome": "Prevencao de Perdas", "valor": round(prevencao, 2), "pct_total": round(prevencao / max(total_beneficio, 1) * 100, 1), "tendencia": "alta"},
        ]

        return jsonify({
            "roi_pct": roi_pct,
            "componentes": componentes,
            "evolucao": evolucao,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/dashboard/analytics/perdas", methods=["GET"])
@require_auth
def api_analytics_perdas():
    from models import PrecoHistorico, Edital
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        periodo_dias = int(request.args.get("periodo_dias", 180))
        segmento = request.args.get("segmento", "todos")
        uf = request.args.get("uf", "todos")
        desde = datetime.now() - timedelta(days=periodo_dias)

        q = db.query(PrecoHistorico).join(
            Edital, PrecoHistorico.edital_id == Edital.id
        ).filter(
            Edital.empresa_id == empresa_id,
            PrecoHistorico.resultado == 'derrota',
            PrecoHistorico.data_registro >= desde,
        )
        if segmento != "todos":
            q = q.filter(func.lower(Edital.categoria).contains(segmento.lower()))
        if uf != "todos":
            q = q.filter(func.upper(Edital.uf) == uf.upper())

        perdas = q.all()

        motivos = {}
        for p in perdas:
            m = p.motivo_perda or 'outro'
            motivos[m] = motivos.get(m, 0) + 1
        total = len(perdas)
        motivos_list = [
            {"motivo": k, "quantidade": v, "percentual": round(v / max(total, 1) * 100, 1)}
            for k, v in motivos.items()
        ]
        top_motivo = max(motivos_list, key=lambda x: x["quantidade"])["motivo"] if motivos_list else "—"

        perdas_list = []
        for p in perdas:
            ed = db.query(Edital).filter(Edital.id == p.edital_id).first()
            perdas_list.append({
                "id": p.id,
                "edital": ed.numero if ed else "—",
                "orgao": ed.orgao if ed else "—",
                "data": p.data_registro.strftime("%d/%m/%Y") if p.data_registro else "—",
                "valor": float(p.nosso_preco or 0),
                "motivo": p.motivo_perda or "outro",
                "vencedor": p.empresa_vencedora or "—",
                "preco_vencedor": float(p.preco_vencedor or 0),
                "gap": round(float((p.nosso_preco or 0) - (p.preco_vencedor or 0)), 2),
            })

        total_part = db.query(PrecoHistorico).join(
            Edital, PrecoHistorico.edital_id == Edital.id
        ).filter(
            Edital.empresa_id == empresa_id,
            PrecoHistorico.resultado.in_(['vitoria', 'derrota']),
            PrecoHistorico.data_registro >= desde,
        ).count()
        taxa = round(total / max(total_part, 1) * 100, 1)
        valor_total = sum(float(p.nosso_preco or 0) for p in perdas)

        recomendacoes = []
        if motivos_list:
            top = sorted(motivos_list, key=lambda x: x["quantidade"], reverse=True)
            if top[0]["quantidade"] >= 3:
                recomendacoes.append({
                    "texto": f"Voce perdeu {top[0]['quantidade']} editais por {top[0]['motivo']}. Considere rever sua estrategia neste aspecto.",
                    "tipo": "preco" if top[0]["motivo"] == "preco" else "geral",
                })
            if len(top) > 1 and top[1]["quantidade"] >= 2:
                recomendacoes.append({
                    "texto": f"{top[1]['quantidade']} perdas por {top[1]['motivo']} — avalie acoes corretivas especificas.",
                    "tipo": top[1]["motivo"],
                })
            if total >= 5:
                recomendacoes.append({
                    "texto": f"Taxa de perda de {taxa}% no periodo. Compare com benchmarks do setor para avaliar competitividade.",
                    "tipo": "benchmark",
                })

        return jsonify({
            "stat_cards": {
                "total_perdas": total,
                "valor_perdido": round(valor_total, 2),
                "taxa_perda": taxa,
                "top_motivo": top_motivo,
            },
            "motivos": motivos_list,
            "perdas": perdas_list,
            "recomendacoes": recomendacoes,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/dashboard/aprendizado/feedbacks", methods=["GET"])
@require_auth
def api_aprendizado_feedbacks():
    from models import AprendizadoFeedback
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        tipo = request.args.get("tipo", "todos")
        periodo_dias = int(request.args.get("periodo_dias", 365))
        entidade = request.args.get("entidade", "todos")
        desde = datetime.now() - timedelta(days=periodo_dias)

        q = db.query(AprendizadoFeedback).filter(
            AprendizadoFeedback.empresa_id == empresa_id,
            AprendizadoFeedback.created_at >= desde,
        )
        if tipo != "todos":
            q = q.filter(AprendizadoFeedback.tipo_evento == tipo)
        if entidade != "todos":
            q = q.filter(AprendizadoFeedback.entidade.ilike(f"%{entidade}%"))

        feedbacks = q.order_by(AprendizadoFeedback.created_at.desc()).all()

        total = len(feedbacks)
        aplicados = sum(1 for f in feedbacks if f.aplicado)
        pendentes = total - aplicados
        taxa_adocao = round(aplicados / max(total, 1) * 100, 1)

        return jsonify({
            "feedbacks": [f.to_dict() for f in feedbacks],
            "stat_cards": {
                "total": total,
                "aplicados": aplicados,
                "pendentes": pendentes,
                "taxa_adocao": taxa_adocao,
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/dashboard/aprendizado/sugestoes", methods=["GET"])
@require_auth
def api_aprendizado_sugestoes():
    from models import SugestaoIA
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        sugestoes = db.query(SugestaoIA).filter(
            SugestaoIA.empresa_id == empresa_id,
        ).order_by(SugestaoIA.created_at.desc()).all()

        ativas = [s.to_dict() for s in sugestoes if s.status == 'pendente']
        historico = [s.to_dict() for s in sugestoes if s.status != 'pendente']
        pendentes = len(ativas)
        aceitas = sum(1 for s in sugestoes if s.status == 'aceita')
        rejeitadas = sum(1 for s in sugestoes if s.status == 'rejeitada')

        return jsonify({
            "ativas": ativas,
            "historico": historico,
            "stat_cards": {
                "pendentes": pendentes,
                "aceitas": aceitas,
                "rejeitadas": rejeitadas,
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/aprendizado/sugestoes/<sug_id>/aceitar", methods=["POST"])
@require_auth
def api_sugestao_aceitar(sug_id):
    from models import SugestaoIA, AprendizadoFeedback
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        sug = db.query(SugestaoIA).filter(SugestaoIA.id == sug_id, SugestaoIA.empresa_id == empresa_id).first()
        if not sug:
            return jsonify({"error": "Sugestao nao encontrada"}), 404
        sug.status = 'aceita'

        fb = AprendizadoFeedback(
            user_id=user_id, empresa_id=empresa_id,
            tipo_evento='feedback_usuario', entidade='sugestao_ia',
            entidade_id=sug_id,
            dados_entrada={"sugestao": sug.titulo, "tipo": sug.tipo},
            resultado_real={"acao": "aceita"},
            aplicado=True,
        )
        db.add(fb)
        sug.feedback_id = fb.id
        db.commit()
        return jsonify({"success": True, "sugestao": sug.to_dict(), "feedback_id": fb.id})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/aprendizado/sugestoes/<sug_id>/rejeitar", methods=["POST"])
@require_auth
def api_sugestao_rejeitar(sug_id):
    from models import SugestaoIA, AprendizadoFeedback
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        data = request.get_json() or {}
        motivo = data.get("motivo", "")
        if len(motivo) < 10:
            return jsonify({"error": "Motivo deve ter pelo menos 10 caracteres"}), 400

        sug = db.query(SugestaoIA).filter(SugestaoIA.id == sug_id, SugestaoIA.empresa_id == empresa_id).first()
        if not sug:
            return jsonify({"error": "Sugestao nao encontrada"}), 404
        sug.status = 'rejeitada'
        sug.rejeitado_motivo = motivo

        fb = AprendizadoFeedback(
            user_id=user_id, empresa_id=empresa_id,
            tipo_evento='feedback_usuario', entidade='sugestao_ia',
            entidade_id=sug_id,
            dados_entrada={"sugestao": sug.titulo, "tipo": sug.tipo},
            resultado_real={"acao": "rejeitada", "motivo": motivo},
            aplicado=False, rejeitado_motivo=motivo,
        )
        db.add(fb)
        sug.feedback_id = fb.id
        db.commit()
        return jsonify({"success": True, "sugestao": sug.to_dict()})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/dashboard/aprendizado/padroes", methods=["GET"])
@require_auth
def api_aprendizado_padroes():
    from models import PadraoDetectado
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        padroes = db.query(PadraoDetectado).filter(
            PadraoDetectado.empresa_id == empresa_id,
            PadraoDetectado.ativo == True,
        ).order_by(PadraoDetectado.confianca.desc()).all()

        total = len(padroes)
        alta_confianca = sum(1 for p in padroes if p.confianca and float(p.confianca) >= 70)
        ultima_analise = max((p.created_at for p in padroes), default=None)

        return jsonify({
            "padroes": [p.to_dict() for p in padroes],
            "stat_cards": {
                "total": total,
                "alta_confianca": alta_confianca,
                "ultima_analise": ultima_analise.isoformat() if ultima_analise else "—",
            },
            "timeline": [],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/aprendizado/analisar", methods=["POST"])
@require_auth
def api_aprendizado_analisar():
    from models import PadraoDetectado, AprendizadoFeedback
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        feedbacks = db.query(AprendizadoFeedback).filter(
            AprendizadoFeedback.empresa_id == empresa_id
        ).all()
        if len(feedbacks) < 5:
            return jsonify({"error": "Preciso de pelo menos 5 feedbacks para detectar padroes"}), 400

        return jsonify({"success": True, "novos": 0, "atualizados": 0,
                        "message": "Analise de padroes executada. Padroes sao gerados pelo job semanal ou via seed."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Sprint 8 — Dispensas + Máscaras
# =============================================================================

@app.route("/api/dashboard/dispensas", methods=["GET"])
@require_auth
def api_dashboard_dispensas():
    """UC-DI01: Dashboard de dispensas — stat cards por status, filtros artigo/faixa/uf."""
    from models import Dispensa, Edital
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        base = db.query(Dispensa).filter(Dispensa.empresa_id == empresa_id)

        artigo = request.args.get("artigo", "").strip()
        if artigo:
            base = base.filter(Dispensa.artigo == artigo)

        uf = request.args.get("uf", "").strip().upper()
        if uf:
            base = base.join(Edital, Dispensa.edital_id == Edital.id).filter(Edital.uf == uf)

        valor_min = request.args.get("valor_min", type=float)
        valor_max = request.args.get("valor_max", type=float)
        if valor_min is not None:
            base = base.filter(Dispensa.valor_limite >= valor_min)
        if valor_max is not None:
            base = base.filter(Dispensa.valor_limite <= valor_max)

        from sqlalchemy import func
        status_rows = (
            base.with_entities(Dispensa.status, func.count(Dispensa.id))
            .group_by(Dispensa.status)
            .all()
        )
        por_status = {row[0]: row[1] for row in status_rows}
        total = sum(por_status.values())

        artigos_rows = (
            db.query(Dispensa.artigo, func.count(Dispensa.id))
            .filter(Dispensa.empresa_id == empresa_id)
            .group_by(Dispensa.artigo)
            .all()
        )
        por_artigo = {(row[0] or "N/A"): row[1] for row in artigos_rows}

        return jsonify({
            "success": True,
            "total": total,
            "por_status": por_status,
            "por_artigo": por_artigo,
            "cards": {
                "abertas": por_status.get("aberta", 0),
                "cotacao_enviada": por_status.get("cotacao_enviada", 0),
                "adjudicadas": por_status.get("adjudicada", 0),
                "encerradas": por_status.get("encerrada", 0),
            },
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/dispensas/buscar", methods=["POST"])
@require_auth
def api_dispensas_buscar():
    """UC-DI01: Busca dispensas no PNCP — reusa motor multifonte com modalidade=dispensa."""
    user_id = get_current_user_id()
    body = request.get_json(silent=True) or {}
    termo = body.get("termo", "").strip()
    uf = body.get("uf", "").strip().upper() or None

    if not termo:
        return jsonify({"error": "Informe o termo de busca."}), 400

    resultado = _buscar_editais_multifonte(
        termo=termo,
        user_id=user_id,
        uf=uf,
        incluir_encerrados=body.get("incluir_encerrados", False),
        buscar_detalhes=True,
        dias_busca=body.get("dias_busca", 90),
        modalidade="Dispensa",
    )

    editais = resultado.get("editais", [])

    from models import Dispensa, Edital
    from decimal import Decimal
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        dispensas_criadas = 0
        LIMITES_ARTIGO = {
            "75-I": 50000, "75-II": 100000, "75-III": None,
            "75-IV": None, "75-V": None,
        }

        for ed in editais:
            edital_id = ed.get("id")
            if not edital_id:
                continue
            existente = db.query(Dispensa).filter(
                Dispensa.empresa_id == empresa_id,
                Dispensa.edital_id == edital_id,
            ).first()
            if existente:
                continue

            artigo_detectado = "75-II"
            valor_est = ed.get("valor_estimado")
            if valor_est and isinstance(valor_est, (int, float)):
                if valor_est <= 50000:
                    artigo_detectado = "75-I"

            limite = LIMITES_ARTIGO.get(artigo_detectado)

            disp = Dispensa(
                user_id=user_id,
                empresa_id=empresa_id,
                edital_id=edital_id,
                artigo=artigo_detectado,
                valor_limite=Decimal(str(limite)) if limite else None,
                status="aberta",
            )
            db.add(disp)
            dispensas_criadas += 1

        if dispensas_criadas:
            db.commit()

        return jsonify({
            "success": True,
            "editais_encontrados": len(editais),
            "dispensas_criadas": dispensas_criadas,
            "editais": editais[:50],
        })
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/dispensas/<dispensa_id>/cotacao", methods=["POST"])
@require_auth
def api_dispensas_cotacao(dispensa_id):
    """UC-DI01: Gera cotação via DeepSeek para uma dispensa, usando produtos do portfolio."""
    from models import Dispensa, Edital, Produto
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    db = get_db()
    try:
        dispensa = db.query(Dispensa).filter(
            Dispensa.id == dispensa_id,
            Dispensa.empresa_id == empresa_id,
        ).first()
        if not dispensa:
            return jsonify({"error": "Dispensa não encontrada."}), 404

        edital = db.query(Edital).filter(Edital.id == dispensa.edital_id).first()
        objeto = edital.objeto if edital else "Sem objeto"

        produtos = db.query(Produto).filter(Produto.empresa_id == empresa_id).all()
        lista_prods = "\n".join([
            f"- {p.nome} | Cat: {p.categoria} | Preço ref: {float(p.preco_referencia) if p.preco_referencia else 'N/A'}"
            for p in produtos[:50]
        ])

        prompt = f"""Você é um especialista em dispensas de licitação (Lei 14.133/2021).

Dispensa: {dispensa.artigo}
Objeto: {objeto}
Valor limite: {float(dispensa.valor_limite) if dispensa.valor_limite else 'Não definido'}

Produtos disponíveis no portfolio da empresa:
{lista_prods}

Gere uma cotação formal em texto para esta dispensa contendo:
1. Identificação da empresa fornecedora
2. Objeto da cotação
3. Itens ofertados (com preço unitário e total)
4. Condições de fornecimento (prazo entrega, validade proposta, pagamento)
5. Observações relevantes

Retorne a cotação em texto formatado, pronta para envio."""

        resposta = call_deepseek(
            [{"role": "user", "content": prompt}],
            max_tokens=4000,
            model_override="deepseek-chat"
        )

        dispensa.cotacao_texto = resposta if isinstance(resposta, str) else str(resposta)
        db.commit()

        return jsonify({
            "success": True,
            "cotacao": dispensa.cotacao_texto,
            "dispensa_id": dispensa_id,
        })
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/dispensas/<dispensa_id>/status", methods=["PUT"])
@require_auth
def api_dispensas_status(dispensa_id):
    """UC-DI01: Transição de status com RN-NEW-08 (sem pular) + RN-NEW-11 (adjudicada → lead CRM)."""
    from models import Dispensa, Edital, LeadCRM
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    body = request.get_json(silent=True) or {}
    novo_status = body.get("status", "").strip()

    TRANSICOES_VALIDAS = {
        "aberta": ["cotacao_enviada"],
        "cotacao_enviada": ["aberta", "adjudicada"],
        "adjudicada": ["encerrada"],
        "encerrada": [],
    }

    db = get_db()
    try:
        dispensa = db.query(Dispensa).filter(
            Dispensa.id == dispensa_id,
            Dispensa.empresa_id == empresa_id,
        ).first()
        if not dispensa:
            return jsonify({"error": "Dispensa não encontrada."}), 404

        if novo_status not in ["aberta", "cotacao_enviada", "adjudicada", "encerrada"]:
            return jsonify({"error": f"Status inválido. Válidos: aberta, cotacao_enviada, adjudicada, encerrada"}), 400

        status_anterior = dispensa.status
        transicoes = TRANSICOES_VALIDAS.get(status_anterior, [])
        if novo_status not in transicoes:
            return jsonify({
                "error": f"Transição inválida: '{status_anterior}' → '{novo_status}'. Permitidas: {transicoes}"
            }), 400

        dispensa.status = novo_status
        dispensa.updated_at = datetime.now()

        # RN-NEW-11: adjudicada → criar lead CRM
        lead_criado = None
        if novo_status == "adjudicada":
            edital = db.query(Edital).filter(Edital.id == dispensa.edital_id).first()
            if edital:
                lead_existente = db.query(LeadCRM).filter(
                    LeadCRM.empresa_id == empresa_id,
                    LeadCRM.edital_id == edital.id,
                ).first()
                if not lead_existente:
                    lead = LeadCRM(
                        user_id=user_id,
                        empresa_id=empresa_id,
                        edital_id=edital.id,
                        orgao=edital.orgao or "Órgão da dispensa",
                        origem="dispensa_adjudicada",
                        valor_potencial=dispensa.valor_limite,
                        status_pipeline="proposta",
                    )
                    db.add(lead)
                    lead_criado = True

        db.commit()

        return jsonify({
            "success": True,
            "status_anterior": status_anterior,
            "status_novo": novo_status,
            "lead_crm_criado": lead_criado or False,
        })
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/portfolio/aplicar-mascara", methods=["POST"])
@require_auth
def api_portfolio_aplicar_mascara():
    """UC-MA01: Aplica máscara de descrição a 1 produto via DeepSeek."""
    from models import Produto, SubclasseProduto, AuditoriaLog
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    body = request.get_json(silent=True) or {}
    produto_id = body.get("produto_id", "").strip()

    if not produto_id:
        return jsonify({"error": "produto_id obrigatório."}), 400

    db = get_db()
    try:
        produto = db.query(Produto).filter(
            Produto.id == produto_id,
            Produto.empresa_id == empresa_id,
        ).first()
        if not produto:
            return jsonify({"error": "Produto não encontrado."}), 404

        campos_mascara = []
        if produto.subclasse_id:
            sub = db.query(SubclasseProduto).filter(SubclasseProduto.id == produto.subclasse_id).first()
            if sub and sub.campos_mascara:
                campos_mascara = sub.campos_mascara

        from tools import tool_aplicar_mascara_descricao
        resultado = tool_aplicar_mascara_descricao(
            descricao=produto.descricao or produto.nome,
            ncm=produto.ncm,
            campos_mascara=campos_mascara,
            nome_produto=produto.nome,
            user_id=user_id,
            empresa_id=empresa_id,
        )

        if resultado.get("success"):
            produto.descricao_normalizada = resultado.get("descricao_normalizada")
            produto.mascara_ativa = True
            produto.mascara_metadata = {
                "variantes": resultado.get("variantes", []),
                "sinonimos": resultado.get("sinonimos", []),
                "score_antes": resultado.get("score_antes"),
                "score_depois": resultado.get("score_depois"),
                "campos_mascara_usados": len(campos_mascara),
            }
            db.commit()

        return jsonify({
            "success": resultado.get("success", False),
            "produto_id": produto_id,
            "descricao_original": produto.descricao or produto.nome,
            "descricao_normalizada": resultado.get("descricao_normalizada"),
            "variantes": resultado.get("variantes", []),
            "sinonimos": resultado.get("sinonimos", []),
            "score_antes": resultado.get("score_antes"),
            "score_depois": resultado.get("score_depois"),
        })
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


@app.route("/api/portfolio/aplicar-mascara-lote", methods=["POST"])
@require_auth
def api_portfolio_aplicar_mascara_lote():
    """UC-MA01: Aplica máscara em lote — N produtos sequencialmente."""
    from models import Produto, SubclasseProduto
    user_id = get_current_user_id()
    empresa_id = get_current_empresa_id()
    body = request.get_json(silent=True) or {}
    produto_ids = body.get("produto_ids", [])

    if not produto_ids or not isinstance(produto_ids, list):
        return jsonify({"error": "produto_ids (lista) obrigatório."}), 400

    if len(produto_ids) > 50:
        return jsonify({"error": "Máximo 50 produtos por lote."}), 400

    db = get_db()
    try:
        resultados = []
        sucesso = 0
        falha = 0

        for pid in produto_ids:
            produto = db.query(Produto).filter(
                Produto.id == pid,
                Produto.empresa_id == empresa_id,
            ).first()
            if not produto:
                resultados.append({"produto_id": pid, "success": False, "error": "Não encontrado"})
                falha += 1
                continue

            campos_mascara = []
            if produto.subclasse_id:
                sub = db.query(SubclasseProduto).filter(SubclasseProduto.id == produto.subclasse_id).first()
                if sub and sub.campos_mascara:
                    campos_mascara = sub.campos_mascara

            from tools import tool_aplicar_mascara_descricao
            res = tool_aplicar_mascara_descricao(
                descricao=produto.descricao or produto.nome,
                ncm=produto.ncm,
                campos_mascara=campos_mascara,
                nome_produto=produto.nome,
                user_id=user_id,
                empresa_id=empresa_id,
            )

            if res.get("success"):
                produto.descricao_normalizada = res.get("descricao_normalizada")
                produto.mascara_ativa = True
                produto.mascara_metadata = {
                    "variantes": res.get("variantes", []),
                    "sinonimos": res.get("sinonimos", []),
                    "score_antes": res.get("score_antes"),
                    "score_depois": res.get("score_depois"),
                }
                sucesso += 1
            else:
                falha += 1

            resultados.append({
                "produto_id": pid,
                "nome": produto.nome,
                "success": res.get("success", False),
                "descricao_normalizada": res.get("descricao_normalizada"),
            })

        if sucesso > 0:
            db.commit()

        return jsonify({
            "success": True,
            "total": len(produto_ids),
            "sucesso": sucesso,
            "falha": falha,
            "resultados": resultados,
        })
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    print("=" * 50)
    print("AGENTE DE EDITAIS - MVP")
    print("=" * 50)

    # Criar pasta de uploads
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    print("Inicializando banco de dados...")
    init_db()

    # Criar superuser se não existir
    _db = get_db()
    try:
        if not _db.query(User).filter(User.email == "superuser@sistema.local").first():
            _db.add(User(
                id=str(uuid.uuid4()),
                email="superuser@sistema.local",
                name="Super Admin",
                password_hash=hash_password("super"),
                is_super=True
            ))
            _db.commit()
            print("Superuser criado: superuser@sistema.local / super")
    finally:
        _db.close()

    # Iniciar scheduler para alertas e monitoramentos (Sprint 2)
    # Proteger contra inicialização dupla em debug mode (Flask reloader cria 2 processos)
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        try:
            from scheduler import iniciar_scheduler
            print("Iniciando scheduler de alertas e monitoramentos...")
            iniciar_scheduler()
        except Exception as e:
            print(f"[AVISO] Scheduler não iniciado: {e}")

    print("Servidor pronto na porta 5007!")
    print("=" * 50)

    app.run(host="0.0.0.0", port=5007, debug=True)

