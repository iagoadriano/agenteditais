"""
Tools para o Agente de Editais.
Cada tool é uma função que o agente pode chamar para executar ações específicas.
"""
import json
import os
import re
import uuid
import requests
import fitz  # PyMuPDF
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from decimal import Decimal

from models import (
    get_db, Produto, ProdutoEspecificacao, ProdutoDocumento,
    FonteEdital, Edital, EditalRequisito, EditalDocumento, EditalItem,
    Analise, AnaliseDetalhe, Proposta,
    Concorrente, PrecoHistorico, ParticipacaoEdital,
    ParametroScore, Empresa, SubclasseProduto, ClasseProdutoV2,
    # FASE 1 Precificação
    Lote, LoteItem, EditalItemProduto, PrecoCamada, Lance, Comodato,
    EstrategiaEdital, BeneficioFiscalNcm,
    # FASE 2 Proposta
    PropostaLog, PropostaTemplate, AnvisaValidacao,
    DocumentoNecessario, EmpresaDocumento,
    # SPRINT 4 Recursos e Impugnações
    Impugnacao, RecursoDetalhado, RecursoTemplate, MonitoramentoJanela, ValidacaoLegal,
    # SPRINT 5 Pós-Licitação
    Contrato, ContratoEntrega, AtaConsultada, Alerta,
    ContratoAditivo, ContratoDesignacao, AtividadeFiscal,
    ARPSaldo, SolicitacaoCarona, AlertaVencimentoRegra,
    # SPRINT 9
    Recurso, SessaoPregao,
)
from llm import call_deepseek
from config import UPLOAD_FOLDER, PNCP_BASE_URL, BEC_API_BASE_URL, BEC_CACHE_TTL_HOURS, COMPRASNET_API_URL, COMPRASNET_TIMEOUT

# === Cliente PNCP via Playwright (bypassa F5 Bot Defense em pncp.gov.br) ===
# Mantém helper de fallback p/ requests caso Playwright não esteja disponível.
try:
    from pncp_playwright_client import pncp_search as _pncp_search_pw
    _PNCP_PW_OK = True
except Exception as _e:
    _PNCP_PW_OK = False
    print(f"[PNCP] Playwright client indisponível ({_e}); usando requests (provavelmente bloqueado).")


def _pncp_search_fetch(termo, pagina, tam_pagina=50, ordenacao="-data"):
    """Wrapper único: tenta Playwright; se falhar, cai p/ requests legacy."""
    if _PNCP_PW_OK:
        try:
            return _pncp_search_pw(q=termo, tipos_documento="edital",
                                    tam_pagina=tam_pagina, pagina=pagina, ordenacao=ordenacao)
        except Exception as e:
            print(f"[PNCP] Playwright falhou ({e}); tentando requests.")
    SEARCH_URL = "https://pncp.gov.br/api/search/"
    resp = requests.get(SEARCH_URL,
                        params={"q": termo, "tipos_documento": "edital",
                                "tam_pagina": tam_pagina, "pagina": pagina, "ordenacao": ordenacao},
                        timeout=20, headers={"Accept": "application/json"})
    if resp.status_code != 200:
        return {"items": [], "total": 0, "_http_status": resp.status_code}
    return resp.json()


# ==================== BUSCA WEB GENÉRICA ====================

def _web_search(query: str, num_results: int = 10) -> list:
    """
    Busca web genérica que abstrai DuckDuckGo, Serper, SerpAPI, Google CSE ou Brave.
    Retorna lista de dicts com {title, link, snippet}.
    A API usada é definida pela variável SCRAPE_API no .env.
    """
    from config import SCRAPE_API

    api = SCRAPE_API  # duckduckgo | serper | serpapi | google_cse | brave

    if api == "serper":
        return _web_search_serper(query, num_results)
    elif api == "serpapi":
        return _web_search_serpapi(query, num_results)
    elif api == "google_cse":
        return _web_search_google_cse(query, num_results)
    elif api == "brave":
        return _web_search_brave(query, num_results)
    else:
        return _web_search_duckduckgo(query, num_results)


def _web_search_duckduckgo(query: str, num_results: int = 10) -> list:
    """Busca via DuckDuckGo (gratuito, sem API key)."""
    try:
        from duckduckgo_search import DDGS
        resultados = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, region="br-pt", max_results=num_results):
                resultados.append({
                    "title": r.get("title", ""),
                    "link": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
        print(f"[SCRAPE-DDG] '{query[:50]}' → {len(resultados)} resultados")
        return resultados
    except Exception as e:
        print(f"[SCRAPE-DDG] Erro: {e}")
        return []


def _web_search_serper(query: str, num_results: int = 10) -> list:
    """Busca via Serper API (serper.dev, pago)."""
    from config import SERPER_API_KEY, SERPER_API_URL
    try:
        response = requests.post(
            SERPER_API_URL,
            headers={
                'X-API-KEY': SERPER_API_KEY,
                'Content-Type': 'application/json'
            },
            json={
                'q': query,
                'num': num_results,
                'gl': 'br',
                'hl': 'pt'
            },
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        resultados = []
        for item in data.get('organic', []):
            resultados.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        print(f"[SCRAPE-SERPER] '{query[:50]}' → {len(resultados)} resultados")
        return resultados
    except Exception as e:
        print(f"[SCRAPE-SERPER] Erro: {e}")
        return []


def _web_search_serpapi(query: str, num_results: int = 10) -> list:
    """Busca via SerpAPI (serpapi.com, pago)."""
    from config import SERPAPI_API_KEY
    try:
        params = {
            "engine": "google",
            "q": query,
            "num": num_results,
            "gl": "br",
            "hl": "pt",
            "api_key": SERPAPI_API_KEY,
        }
        response = requests.get("https://serpapi.com/search", params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        resultados = []
        for item in data.get("organic_results", []):
            resultados.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        print(f"[SCRAPE-SERPAPI] '{query[:50]}' → {len(resultados)} resultados")
        return resultados
    except Exception as e:
        print(f"[SCRAPE-SERPAPI] Erro: {e}")
        return []


def _web_search_google_cse(query: str, num_results: int = 10) -> list:
    """Busca via Google Custom Search Engine (100 queries/dia gratis)."""
    from config import GOOGLE_CSE_API_KEY, GOOGLE_CSE_CX
    try:
        # Google CSE retorna no máximo 10 por request
        params = {
            "key": GOOGLE_CSE_API_KEY,
            "cx": GOOGLE_CSE_CX,
            "q": query,
            "num": min(num_results, 10),
            "gl": "br",
            "hl": "pt",
        }
        response = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params=params,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        resultados = []
        for item in data.get("items", []):
            resultados.append({
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            })
        print(f"[SCRAPE-GCSE] '{query[:50]}' → {len(resultados)} resultados")
        return resultados
    except Exception as e:
        print(f"[SCRAPE-GCSE] Erro: {e}")
        return []


def _web_search_brave(query: str, num_results: int = 10) -> list:
    """Busca via Brave Search API (2000 queries/mes gratis)."""
    from config import BRAVE_API_KEY
    try:
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": BRAVE_API_KEY,
        }
        params = {
            "q": query,
            "count": min(num_results, 20),
            "country": "BR",
            "search_lang": "pt-br",
            "text_decorations": False,
        }
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers=headers,
            params=params,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        resultados = []
        for item in data.get("web", {}).get("results", []):
            resultados.append({
                "title": item.get("title", ""),
                "link": item.get("url", ""),
                "snippet": item.get("description", ""),
            })
        print(f"[SCRAPE-BRAVE] '{query[:50]}' → {len(resultados)} resultados")
        return resultados
    except Exception as e:
        print(f"[SCRAPE-BRAVE] Erro: {e}")
        return []


# ==================== PROMPTS PARA EXTRAÇÃO ====================

PROMPT_EXTRAIR_SPECS = """Extraia TODAS as especificações técnicas do texto abaixo.

Para cada especificação, retorne um objeto JSON com:
- nome: nome descritivo da especificação (ex: "Temperatura de operação", "Largura", "Peso", "Alimentação", "Consumo energético")
- valor: valor completo como está no texto (ex: "15 a 30°C", "645 mm", "78 kg")
- unidade: unidade de medida se houver (ex: "mm", "kg", "°C", "%", "kPa", "VA")

Exemplo:
[
  {{"nome": "Temperatura de operação", "valor": "15 a 30°C", "unidade": "°C"}},
  {{"nome": "Largura", "valor": "645 mm", "unidade": "mm"}},
  {{"nome": "Peso total", "valor": "78 kg", "unidade": "kg"}}
]

Retorne APENAS um array JSON válido, sem texto adicional.

TEXTO:
{texto}

JSON:
"""

def _build_prompt_mascara(texto: str, campos_mascara: list) -> str:
    """
    Constrói prompt de extração dirigido pelos campos da máscara da subclasse.
    Extrai exatamente os campos definidos na máscara + quaisquer outros encontrados.
    """
    campos_lista = []
    for c in campos_mascara:
        nome = c.get("campo") or c.get("nome") or ""
        tipo = c.get("tipo", "texto")
        unidade = c.get("unidade", "")
        obrig = " (OBRIGATÓRIO)" if c.get("obrigatorio") else ""
        desc = f'- "{nome}"'
        if unidade:
            desc += f" (unidade: {unidade})"
        if tipo == "numero":
            desc += " [valor inteiro]"
        elif tipo == "decimal":
            desc += " [valor decimal]"
        elif tipo == "select":
            opcoes = c.get("opcoes", [])
            if opcoes:
                desc += f" [opções: {', '.join(opcoes)}]"
        elif tipo == "boolean":
            desc += " [Sim/Não]"
        desc += obrig
        campos_lista.append(desc)

    campos_str = "\n".join(campos_lista)

    return f"""Extraia as especificações técnicas do texto abaixo.

CAMPOS PRIORITÁRIOS que DEVEM ser extraídos (se disponíveis no texto):
{campos_str}

Além desses, extraia TAMBÉM qualquer outra especificação técnica relevante encontrada no texto.

Para cada especificação, retorne um objeto JSON com:
- nome: nome descritivo da especificação
- valor: valor completo como está no texto
- unidade: unidade de medida se houver
- valor_numerico: valor numérico (se aplicável), como float
- operador: "=", "<", "<=", ">=", ">", "range" (se aplicável)
- valor_min: valor mínimo se for faixa (float)
- valor_max: valor máximo se for faixa (float)

Retorne APENAS um array JSON válido, sem texto adicional.

TEXTO:
{texto}

JSON:
"""


PROMPT_EXTRAIR_REQUISITOS = """Você é um especialista em análise de editais de licitação.

Analise o texto do edital abaixo e extraia TODOS os requisitos técnicos, documentais e comerciais.

Para cada requisito, retorne um objeto JSON com:
- tipo: "tecnico", "documental" ou "comercial"
- descricao: descrição completa do requisito
- nome_especificacao: para tipo "documental", use o código do documento/certidão da lista abaixo. Para tipo "tecnico", nome da especificação (ex: "Sensibilidade", "Voltagem")
- valor_exigido: para tipo "documental", use a subcategoria: "documento", "certidao" ou "tecnico". Para outros tipos, o valor exigido (ex: "≤ 0.05 mg/dL")
- operador: operador se houver ("<", "<=", "=", ">=", ">")
- valor_numerico: valor numérico extraído
- obrigatorio: true se for obrigatório, false se for desejável

CÓDIGOS DE DOCUMENTOS para nome_especificacao (tipo "documental"):
Documentos da empresa (valor_exigido="documento"):
  contrato_social, alvara, procuracao, afe, cbpad, cbpp, bombeiros
Certidões fiscais (valor_exigido="certidao"):
  cnd_federal, cnd_estadual, cnd_municipal, fgts, trabalhista
Qualificação técnica (valor_exigido="tecnico"):
  atestado_capacidade, registro_conselho, balanco, qualificacao_tecnica

Se o edital pedir um documento que não está na lista, use nome_especificacao="outro" e coloque o nome real na descricao.

Retorne APENAS um array JSON válido, sem texto adicional.

TEXTO DO EDITAL:
{texto}

REQUISITOS EXTRAÍDOS (JSON):
"""

PROMPT_CLASSIFICAR_EDITAL = """Analise o objeto do edital e classifique em uma das categorias:
- comodato: equipamento em comodato com consumo de reagentes
- venda_equipamento: venda direta de equipamento
- aluguel_com_consumo: aluguel de equipamento com consumo obrigatório
- aluguel_sem_consumo: aluguel de equipamento sem consumo
- consumo_reagentes: apenas reagentes/kits
- consumo_insumos: insumos hospitalares ou laboratoriais
- servicos: prestação de serviços

OBJETO DO EDITAL:
{objeto}

Responda APENAS com a categoria (uma palavra), sem explicação.
"""

PROMPT_GERAR_PROPOSTA = """Você é um especialista em elaboração de propostas técnicas para licitações públicas brasileiras.

Com base nas informações abaixo, gere uma PROPOSTA TÉCNICA COMPLETA e profissional.

## DADOS DO EDITAL:
- Número: {numero_edital}
- Órgão: {orgao}
- Objeto: {objeto}

## PRODUTO OFERTADO:
- Nome: {nome_produto}
- Fabricante: {fabricante}
- Modelo: {modelo}

## ESPECIFICAÇÕES TÉCNICAS DO PRODUTO:
{especificacoes}

## ANÁLISE DE REQUISITOS DO EDITAL:
{analise_requisitos}

## PREÇO PROPOSTO: R$ {preco}

---

GERE A PROPOSTA TÉCNICA COMPLETA em Markdown com TODAS as seções abaixo. NÃO OMITA NENHUMA SEÇÃO:

# PROPOSTA TÉCNICA - EDITAL Nº {numero_edital}

## 1. IDENTIFICAÇÃO DA PROPONENTE
(Incluir campos em branco: Razão Social, CNPJ, Endereço, Telefone, E-mail, Representante Legal)

## 2. OBJETO DA PROPOSTA
(Descrição clara do que está sendo ofertado, referenciando o edital)

## 3. DESCRIÇÃO TÉCNICA DO PRODUTO
(Detalhar o produto, fabricante, modelo e principais características técnicas)

## 4. ATENDIMENTO AOS REQUISITOS DO EDITAL
(OBRIGATÓRIO: Criar uma TABELA MARKDOWN comparando requisitos do edital vs especificações do produto)

| Requisito do Edital | Especificação Oferecida | Status |
|---------------------|-------------------------|--------|
| (requisito 1) | (spec do produto) | ✅ Atende |
| (requisito 2) | (spec do produto) | ✅ Atende |

## 5. CONDIÇÕES COMERCIAIS
OBRIGATÓRIO incluir:
- **PREÇO UNITÁRIO: R$ {preco}**
- **PREÇO TOTAL: R$ {preco}** (quantidade: 1 unidade)
- Prazo de entrega: XX dias após emissão da ordem de fornecimento
- Prazo de garantia: XX meses
- Assistência técnica: disponível em todo território nacional
- Forma de pagamento: conforme edital

## 6. VALIDADE DA PROPOSTA
A presente proposta tem validade de 60 (sessenta) dias, contados da data de sua apresentação.

## 7. DECLARAÇÕES
Incluir declarações padrão:
- Declaração de que os produtos atendem às especificações técnicas
- Declaração de inexistência de fato impeditivo
- Declaração de não emprego de menores
- Declaração de conformidade com a legislação vigente

## 8. ENCERRAMENTO
Local, data e assinatura do representante legal.

---
IMPORTANTE: Gere a proposta COMPLETA com TODAS as 8 seções acima. O preço R$ {preco} DEVE aparecer na seção 5.
"""


# ==================== FUNÇÕES AUXILIARES ====================

def _extrair_json_array(texto: str) -> List[Dict]:
    """
    Extrai um array JSON de uma resposta da IA.
    Lida com casos onde a resposta vem com ```json ou markdown.
    """
    # Remover blocos de código markdown
    texto_limpo = texto
    if "```json" in texto:
        # Extrair conteúdo entre ```json e ```
        match = re.search(r'```json\s*([\s\S]*?)\s*```', texto)
        if match:
            texto_limpo = match.group(1)
    elif "```" in texto:
        match = re.search(r'```\s*([\s\S]*?)\s*```', texto)
        if match:
            texto_limpo = match.group(1)

    # Tentar extrair array JSON
    json_match = re.search(r'\[[\s\S]*\]', texto_limpo)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    return []


def _extrair_json_object(texto: str) -> Dict:
    """Extrai um objeto JSON {} de uma resposta da IA."""
    texto_limpo = texto
    if "```json" in texto:
        match = re.search(r'```json\s*([\s\S]*?)\s*```', texto)
        if match:
            texto_limpo = match.group(1)
    elif "```" in texto:
        match = re.search(r'```\s*([\s\S]*?)\s*```', texto)
        if match:
            texto_limpo = match.group(1)
    json_match = re.search(r'\{[\s\S]*\}', texto_limpo)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    return {}


def _extrair_info_produto(texto: str) -> Dict[str, Any]:
    """
    Usa IA para extrair informações do produto a partir do texto do manual.
    Retorna: nome, fabricante, modelo, categoria
    """
    prompt = f"""Analise o texto abaixo (extraído de um manual/datasheet) e identifique:

1. **Nome do produto** - Nome comercial completo do equipamento/produto
2. **Fabricante** - Empresa que fabrica o produto
3. **Modelo** - Código/número do modelo
4. **Categoria** - Uma das opções: equipamento, reagente, insumo_hospitalar, insumo_laboratorial, informatica, redes, mobiliario, eletronico, outro

TEXTO:
{texto[:5000]}

Retorne APENAS um JSON válido no formato:
{{"nome": "Nome do Produto", "fabricante": "Nome do Fabricante", "modelo": "ABC-123", "categoria": "equipamento"}}

Se não encontrar alguma informação, use null.
JSON:"""

    try:
        print(f"[TOOLS] Chamando IA para extrair info do produto...")
        resposta = call_deepseek([{"role": "user", "content": prompt}], max_tokens=500, temperature=0, model_override="deepseek-chat")
        print(f"[TOOLS] Resposta da IA: {resposta[:300]}")

        # Extrair JSON da resposta
        import re
        json_match = re.search(r'\{[\s\S]*?\}', resposta)
        if json_match:
            info = json.loads(json_match.group())
            print(f"[TOOLS] JSON extraído: {info}")
            return {
                "nome": info.get("nome") or "Produto",
                "fabricante": info.get("fabricante"),
                "modelo": info.get("modelo"),
                "categoria": info.get("categoria", "equipamento")
            }
        else:
            print(f"[TOOLS] Não encontrou JSON na resposta")
    except Exception as e:
        print(f"[TOOLS] Erro ao extrair info do produto: {e}")

    return {"nome": "Produto", "fabricante": None, "modelo": None, "categoria": "equipamento"}


def _extrair_lista_produtos(texto: str) -> List[Dict[str, Any]]:
    """
    Para NF / plano de contas (obs 5/8 validador V8): extrai a LISTA de
    produtos do documento, nao apenas o primeiro. Retorna [] se nao
    identificar multiplos itens (caller faz fallback mono-produto).
    """
    prompt = f"""O texto abaixo foi extraido de uma nota fiscal ou plano de contas (ERP).
Liste TODOS os produtos/itens distintos presentes. Para cada item identifique:
- nome (descricao do produto)
- fabricante (se houver, senao null)
- modelo (se houver, senao null)
- categoria: equipamento, reagente, insumo_hospitalar, insumo_laboratorial, informatica, redes, mobiliario, eletronico ou outro

TEXTO:
{texto[:15000]}

Retorne APENAS um array JSON. Exemplo:
[{{"nome":"Produto A","fabricante":"X","modelo":"M1","categoria":"equipamento"}}]
Se houver um unico produto, retorne array com 1 elemento. JSON:"""
    try:
        resposta = call_deepseek([{"role": "user", "content": prompt}], max_tokens=4000, temperature=0, model_override="deepseek-chat")
        itens = _extrair_json_array(resposta)
        out = []
        vistos = set()
        for it in itens or []:
            nome = (it.get("nome") or "").strip()
            if not nome or nome.lower() in ("produto", "produtos", "n/a"):
                continue
            chave = nome.lower()
            if chave in vistos:
                continue
            vistos.add(chave)
            cat = it.get("categoria") or "equipamento"
            out.append({
                "nome": nome,
                "fabricante": it.get("fabricante"),
                "modelo": it.get("modelo"),
                "categoria": cat,
            })
        return out
    except Exception as e:
        print(f"[TOOLS] _extrair_lista_produtos erro: {e}")
        return []


# ==================== TOOLS ====================

def tool_web_search(query: str, user_id: str, num_results: int = 10) -> Dict[str, Any]:
    """
    Busca informações na web (Google/DuckDuckGo).
    Retorna resultados de busca que podem conter links para PDFs/manuais.
    Usa a API configurada em SCRAPE_API (.env): duckduckgo, serper ou serpapi.
    """
    try:
        # Adicionar filetype:pdf para priorizar PDFs
        search_query = f"{query} filetype:pdf"

        raw_results = _web_search(search_query, num_results)

        # Mapear para formato esperado
        resultados = []
        for i, item in enumerate(raw_results):
            resultados.append({
                'titulo': item.get('title', ''),
                'link': item.get('link', ''),
                'descricao': item.get('snippet', ''),
                'posicao': i + 1
            })

        # Filtrar apenas PDFs
        pdfs = [r for r in resultados if '.pdf' in r['link'].lower()]
        outros = [r for r in resultados if '.pdf' not in r['link'].lower()]

        return {
            "success": True,
            "query": query,
            "total_resultados": len(resultados),
            "pdfs_encontrados": len(pdfs),
            "resultados_pdf": pdfs[:5],  # Top 5 PDFs
            "outros_resultados": outros[:3],  # Top 3 outros
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Erro inesperado: {str(e)}",
            "query": query
        }


def tool_buscar_editais_scraper(termo: str, fontes: List[str] = None, user_id: str = None) -> Dict[str, Any]:
    """
    Busca editais em múltiplas fontes usando busca web (DuckDuckGo/Serper/SerpAPI com site:).
    Não depende de APIs específicas de cada portal.
    A API usada é definida pela variável SCRAPE_API no .env.

    Args:
        termo: Termo de busca (ex: "equipamento laboratorial")
        fontes: Lista de URLs base das fontes (ex: ["bec.sp.gov.br", "comprasnet.gov.br"])
        user_id: ID do usuário

    Returns:
        Dict com editais encontrados de todas as fontes
    """
    # Se não especificar fontes, buscar nas principais cadastradas
    if not fontes:
        db = get_db()
        try:
            fontes_db = db.query(FonteEdital).filter(FonteEdital.ativo == True).all()
            fontes = []
            for f in fontes_db:
                # Extrair domínio da URL
                url = f.url_base
                if url:
                    # Remover protocolo e path
                    dominio = url.replace("https://", "").replace("http://", "").split("/")[0]
                    if dominio not in fontes:
                        fontes.append(dominio)
        finally:
            db.close()

    # Se ainda não tem fontes, usar padrão
    if not fontes:
        fontes = [
            "pncp.gov.br",
            "gov.br/compras",
            "bec.sp.gov.br",
            "compras.mg.gov.br",
            "licitacoes-e.com.br",
            "transferegov.sistema.gov.br"
        ]

    print(f"[SCRAPER] Buscando '{termo}' em {len(fontes)} fontes: {fontes}")

    todos_resultados = []
    erros = []

    # Palavras que indicam que NÃO é um edital de AQUISIÇÃO DE PRODUTOS
    palavras_excluir = [
        # Concursos e RH
        'concurso público', 'concurso publico', 'vagas para', 'aprovados',
        'convocação', 'convocacao', 'nomeação', 'nomeacao', 'posse',
        'inscrição', 'inscricao', 'gabarito', 'resultado preliminar',
        'funcionário', 'funcionarios', 'salário', 'salario', '13º',
        # Notícias
        'notícia', 'noticia', 'comunicado', 'portaria', 'decreto',
        'lei complementar', 'resolução', 'resolucao', 'será atendido',
        'passam para', 'transição', 'como vai funcionar', 'servidores estaduais',
        'atendimentos do sas', 'serão transferidos',
        # Serviços (não produtos)
        'prestação de serviço', 'prestacao de servico', 'mão de obra', 'mao de obra',
        'dedicação exclusiva', 'dedicacao exclusiva', 'terceirização', 'terceirizacao',
        'serviço de lavanderia', 'servico de lavanderia', 'serviço de limpeza',
        'manutenção preventiva', 'manutencao preventiva', 'manutenção corretiva',
        # Prorrogações/Aditivos (não novos editais)
        'termo aditivo', 'prorrogação da ata', 'prorrogacao da ata',
        'prorrogação parcial', 'prorrogacao parcial',
        # Editais genéricos sem objeto
        'poderão participar do processo as empresas devidamente credenciadas'
    ]

    # Padrões de URL que indicam página de edital (não notícia)
    padroes_url_edital = [
        '/editais/', '/edital/', '/pregao/', '/licitacao/', '/licitacoes/',
        '/compras/', '/dispensa/', '/inexigibilidade/', '/ata-registro/',
        'edital=', 'pregao=', 'licitacao=', 'processo='
    ]

    for fonte in fontes[:5]:  # Limitar a 5 fontes para não demorar muito
        try:
            # Montar query com site: - buscar por aquisição de bens/equipamentos
            search_query = f"site:{fonte} pregão eletrônico aquisição {termo} 2025 OR 2026"

            print(f"[SCRAPER] Buscando: {search_query}")

            raw_results = _web_search(search_query, 10)

            # Processar resultados
            resultados_fonte = 0
            for item in raw_results:
                link = item.get('link', '')
                titulo = item.get('title', '')
                descricao = item.get('snippet', '')
                texto_completo = (titulo + " " + descricao).lower()

                # 1. Filtrar resultados que são notícias/concursos
                eh_noticia = any(palavra in texto_completo for palavra in palavras_excluir)
                if eh_noticia:
                    print(f"[SCRAPER] Ignorando (notícia): {titulo[:40]}...")
                    continue

                # 2. Verificar se a URL parece ser de um edital
                url_lower = link.lower()
                eh_url_edital = any(padrao in url_lower for padrao in padroes_url_edital)

                # 3. Extrair número do edital
                numero_edital = _extrair_numero_edital(titulo + " " + descricao)

                # 4. Se não tem número E não é URL de edital, provavelmente é notícia
                if not numero_edital and not eh_url_edital:
                    print(f"[SCRAPER] Ignorando (sem número/URL): {titulo[:40]}...")
                    continue

                # 5. Extrair órgão
                orgao = _extrair_orgao(titulo + " " + descricao)

                # Se não extraiu órgão, tentar extrair do título de forma mais simples
                if not orgao and '-' in titulo:
                    # Padrão comum: "Edital 123/2025 - Prefeitura de XYZ"
                    partes = titulo.split('-')
                    if len(partes) > 1:
                        orgao = partes[-1].strip()[:80]

                # Fallback: usar nome amigável da fonte
                if not orgao:
                    fonte_nomes = {
                        'www.administracao.pr.gov.br': 'Governo do Paraná',
                        'www.compras.rs.gov.br': 'Governo do Rio Grande do Sul',
                        'www.gov.br': 'Governo Federal',
                        'www.comprasnet.gov.br': 'ComprasNet - Gov Federal',
                        'www.licitacoes-e.com.br': 'Licitações-e (BB)',
                        'portaldecompraspublicas.com.br': 'Portal de Compras Públicas',
                        'www.comprasnet.ba.gov.br': 'Governo da Bahia',
                        'www.bec.sp.gov.br': 'BEC - Governo de São Paulo',
                        'www.compras.mg.gov.br': 'Governo de Minas Gerais',
                        'www.licitanet.com.br': 'LicitaNet',
                        'pncp.gov.br': 'PNCP - Portal Nacional'
                    }
                    orgao = fonte_nomes.get(fonte, fonte)

                # Usar título como fallback para número se não encontrou
                if not numero_edital:
                    # Tentar usar parte do título que parece ser identificador
                    numero_edital = titulo[:50] if len(titulo) < 60 else None

                edital_info = {
                    'fonte': fonte,
                    'titulo': titulo,
                    'link': link,
                    'descricao': descricao,
                    'numero': numero_edital,
                    'orgao': orgao,
                    'tipo': 'scraper'
                }
                todos_resultados.append(edital_info)
                resultados_fonte += 1

            print(f"[SCRAPER] {fonte}: {resultados_fonte} editais válidos (de {len(raw_results)} resultados)")

        except Exception as e:
            print(f"[SCRAPER] Erro em {fonte}: {e}")
            erros.append({"fonte": fonte, "erro": str(e)})

    # Remover duplicatas por link
    links_vistos = set()
    resultados_unicos = []
    for r in todos_resultados:
        if r['link'] not in links_vistos:
            links_vistos.add(r['link'])
            resultados_unicos.append(r)

    print(f"[SCRAPER] Total: {len(resultados_unicos)} editais únicos encontrados")

    return {
        "success": True,
        "termo": termo,
        "fontes_consultadas": fontes[:5],
        "total_resultados": len(resultados_unicos),
        "editais": resultados_unicos[:20],  # Top 20
        "erros": erros if erros else None
    }


def tool_buscar_links_editais(termo: str, user_id: str = None) -> Dict[str, Any]:
    """
    Busca editais e retorna links formatados para exibição.
    Usa PNCP API como fonte principal para garantir links válidos.

    Args:
        termo: Área/categoria de busca (ex: "equipamentos médicos", "reagentes")
        user_id: ID do usuário

    Returns:
        Dict com links formatados em texto
    """
    from config import PNCP_BASE_URL

    print(f"[LINKS] Buscando links de editais para: {termo}")

    links_texto = []
    editais_encontrados = []
    hoje = datetime.now()

    try:
        import unicodedata

        def _sem_acento(txt):
            return unicodedata.normalize('NFKD', txt).encode('ascii', 'ignore').decode('ascii')

        # Preparar palavras do termo para filtro ALL-words
        termo_norm = _sem_acento(termo.lower())
        palavras_termo = [p for p in termo_norm.split() if len(p) > 2]

        # Buscar via Search API do PNCP (Playwright -> bypassa F5; fallback requests)
        all_items = []
        for pagina in range(1, 5):  # Até 4 páginas (200 itens)
            try:
                data = _pncp_search_fetch(termo, pagina=pagina, tam_pagina=50)
            except Exception as e:
                print(f"[LINKS] PNCP erro pag {pagina}: {e}")
                break
            items = data.get("items", [])
            if not items:
                break
            all_items.extend(items)
            if len(all_items) >= data.get("total", 0):
                break

        print(f"[LINKS] Search API: {len(all_items)} itens coletados")

        for item in all_items:
            descricao = (item.get('description', '') or '')
            titulo = (item.get('title', '') or '')
            texto_norm = _sem_acento(f"{titulo} {descricao}".lower())

            # FILTRO: ALL-words match
            if palavras_termo and not all(p in texto_norm for p in palavras_termo):
                continue

            # Filtrar encerrados
            edital_enc = False
            data_fim_vig = item.get('data_fim_vigencia', '')
            if data_fim_vig:
                try:
                    dt_fim = datetime.fromisoformat(str(data_fim_vig).replace('Z', '')[:19])
                    if dt_fim < hoje:
                        edital_enc = True
                except (ValueError, TypeError):
                    pass
            if item.get('tem_resultado', False):
                edital_enc = True
            if item.get('cancelado', False):
                edital_enc = True
            sit = (item.get('situacao_nome', '') or '').lower()
            if sit in ('suspensa', 'revogada', 'anulada', 'encerrada', 'homologada'):
                edital_enc = True
            if edital_enc:
                continue

            orgao = item.get('orgao_nome', 'Órgão não informado')
            objeto_texto = descricao[:100]
            modalidade_nome = item.get('modalidade_licitacao_nome', 'Pregão')
            numero = item.get('numero', '')
            ano = item.get('ano', '')
            seq = item.get('numero_sequencial')
            uf_item = item.get('uf', '')
            cidade = item.get('municipio_nome', '')
            valor = item.get('valor_global', 0)
            cnpj = (item.get('orgao_cnpj', '') or '').replace('.', '').replace('/', '').replace('-', '')
            item_url = item.get('item_url', '')

            # Construir URL (item_url /compras/... é formato API, não portal)
            if item_url and not item_url.startswith('/compras/'):
                url_edital = f"https://pncp.gov.br{item_url}"
            elif cnpj and ano and seq:
                url_edital = f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}"
            else:
                numero_pncp = item.get('numero_controle_pncp', '')
                if numero_pncp:
                    # numero_pncp formato: 01263896000164-1-000142/2026 → cnpj/ano/seq
                    import re as _re
                    _m = _re.match(r'(\d{14})-\d+-(\d+)/(\d{4})', numero_pncp)
                    url_edital = f"https://pncp.gov.br/app/editais/{_m.group(1)}/{_m.group(3)}/{int(_m.group(2))}" if _m else 'URL não disponível'
                else:
                    url_edital = 'URL não disponível'

            # Formatar número
            if numero and ano:
                numero_formatado = f"{modalidade_nome} {numero}/{ano}"
            else:
                numero_formatado = item.get('numero_controle_pncp', 'S/N')

            localizacao = f"{cidade}/{uf_item}" if cidade and uf_item else (uf_item or "Brasil")
            valor_fmt = f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if valor else "Não informado"

            data_pub = item.get('data_publicacao_pncp', '')
            if data_pub:
                try:
                    dt = datetime.fromisoformat(str(data_pub).replace("Z", "")[:19])
                    data_fmt = dt.strftime("%d/%m/%Y às %H:%M")
                except:
                    data_fmt = str(data_pub)[:10]
            else:
                data_fmt = "Não informada"

            edital_info = {
                "numero": numero_formatado,
                "orgao": orgao,
                "objeto": objeto_texto,
                "localizacao": localizacao,
                "valor": valor_fmt,
                "data_abertura": data_fmt,
                "url": url_edital
            }
            editais_encontrados.append(edital_info)

            texto_link = f"""
📋 **{numero_formatado}**
   📍 {orgao} - {localizacao}
   📝 {objeto_texto}
   💰 Valor: {valor_fmt}
   📅 Abertura: {data_fmt}
   🔗 Link: {url_edital}
"""
            links_texto.append(texto_link)

            if len(editais_encontrados) >= 15:
                break

        # Se não encontrou nada no PNCP, tentar Serper
        if not editais_encontrados:
            print("[LINKS] PNCP não retornou resultados, tentando scraper web...")
            resultado_scraper = tool_buscar_editais_scraper(termo, user_id=user_id)

            if resultado_scraper.get("success") and resultado_scraper.get("editais"):
                for item in resultado_scraper["editais"][:10]:
                    numero = item.get("numero", "S/N")
                    orgao = item.get("orgao", "Não informado")
                    titulo = item.get("titulo", "")
                    descricao = item.get("descricao", "")
                    url_edital = item.get("link", "")

                    # Filtrar links que são PDFs ou atas (não são links de editais)
                    if url_edital.lower().endswith('.pdf'):
                        continue

                    edital_info = {
                        "numero": numero,
                        "orgao": orgao,
                        "objeto": descricao[:100] if descricao else titulo[:100],
                        "url": url_edital
                    }
                    editais_encontrados.append(edital_info)

                    texto_link = f"""
📋 **{numero}** - {orgao}
   📝 {descricao[:100] if descricao else titulo[:100]}
   🔗 Link: {url_edital}
"""
                    links_texto.append(texto_link)

    except Exception as e:
        print(f"[LINKS] Erro na busca: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e),
            "texto": f"Erro ao buscar editais: {e}"
        }

    # Montar resposta formatada
    if editais_encontrados:
        texto_resposta = f"""🔍 **Editais encontrados para "{termo}"**

{chr(10).join(links_texto)}

---
Total: {len(editais_encontrados)} editais encontrados
Fonte: PNCP - Portal Nacional de Contratações Públicas
"""
    else:
        texto_resposta = f"""⚠️ Nenhum edital encontrado para "{termo}" nos últimos 90 dias.

Tente:
- Usar termos mais genéricos (ex: "laboratorio" em vez de "analisador hematológico")
- Buscar por categoria ampla (ex: "equipamentos médicos", "reagentes")
"""

    return {
        "success": True,
        "termo": termo,
        "total": len(editais_encontrados),
        "editais": editais_encontrados,
        "texto": texto_resposta
    }


def _extrair_numero_edital(texto: str) -> str:
    """Extrai número do edital do texto."""
    import re
    # Padrões comuns: PE 001/2025, Pregão 123/2025, Edital nº 456/2025
    padroes = [
        r'(?:PE|Pregão|PREGÃO|Edital|EDITAL)[:\s]*[Nn]?[ºo°]?\s*(\d+[/-]\d{4})',
        r'(?:PE|Pregão|PREGÃO)[:\s]*(\d+[/-]\d{4})',
        r'[Nn][ºo°]\s*(\d+[/-]\d{4})',
        r'(\d{1,5}[/-]20\d{2})',
    ]
    for padrao in padroes:
        match = re.search(padrao, texto)
        if match:
            return match.group(1)
    return None


def _extrair_orgao(texto: str) -> str:
    """Extrai nome do órgão do texto."""
    import re
    # Padrões comuns - ordem de prioridade
    padroes = [
        # Órgãos específicos
        r'(Prefeitura\s+(?:Municipal\s+)?(?:de\s+)?[A-Za-zÀ-ú\s]+?)(?:\s*[-–,\.]|\s*$)',
        r'(Secretaria\s+(?:de\s+)?(?:Estado\s+)?(?:da\s+)?[A-Za-zÀ-ú\s]+?)(?:\s*[-–,\.]|\s*$)',
        r'(Hospital\s+[A-Za-zÀ-ú\s]+?)(?:\s*[-–,\.]|\s*$)',
        r'(Universidade\s+[A-Za-zÀ-ú\s]+?)(?:\s*[-–,\.]|\s*$)',
        r'(Ministério\s+(?:da\s+|do\s+)?[A-Za-zÀ-ú\s]+?)(?:\s*[-–,\.]|\s*$)',
        r'(Governo\s+(?:do\s+)?(?:Estado\s+)?(?:de\s+)?[A-Za-zÀ-ú\s]+?)(?:\s*[-–,\.]|\s*$)',
        r'(Fundação\s+[A-Za-zÀ-ú\s]+?)(?:\s*[-–,\.]|\s*$)',
        r'(Instituto\s+[A-Za-zÀ-ú\s]+?)(?:\s*[-–,\.]|\s*$)',
        r'(CELIC[A-Za-zÀ-ú\s\-]*)',  # Central de Licitações
        r'(Departamento\s+(?:de\s+)?[A-Za-zÀ-ú\s]+?)(?:\s*[-–,\.]|\s*$)',
        # Siglas de estados (fallback)
        r'(?:Estado\s+(?:do\s+|de\s+)?)([A-Za-zÀ-ú\s]+?)(?:\s*[-–,\.]|\s*$)',
    ]
    for padrao in padroes:
        match = re.search(padrao, texto, re.IGNORECASE)
        if match:
            orgao = match.group(1).strip()
            # Limpar e validar
            if len(orgao) > 5 and len(orgao) < 100:
                return orgao[:100]
    return None


def tool_download_arquivo(url: str, user_id: str, nome_produto: str = None) -> Dict[str, Any]:
    """
    Baixa arquivo de uma URL e salva localmente.
    """
    try:
        # Criar pasta de uploads se não existir
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)

        # Fazer download
        response = requests.get(url, timeout=60, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response.raise_for_status()

        # Determinar nome do arquivo
        filename = url.split('/')[-1].split('?')[0]
        if not filename.endswith('.pdf'):
            filename = f"{nome_produto or 'documento'}_{uuid.uuid4().hex[:8]}.pdf"

        filepath = os.path.join(UPLOAD_FOLDER, f"{user_id}_{filename}")

        with open(filepath, 'wb') as f:
            f.write(response.content)

        return {
            "success": True,
            "filepath": filepath,
            "filename": filename,
            "size": len(response.content)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _extrair_texto_por_paginas(filepath: str) -> List[Dict[str, Any]]:
    """
    Extrai texto do PDF página por página.
    Retorna lista de dicts com número da página e texto.
    """
    paginas = []
    doc = fitz.open(filepath)
    for i, page in enumerate(doc):
        texto = page.get_text()
        paginas.append({
            "pagina": i + 1,
            "texto": texto,
            "chars": len(texto)
        })
    doc.close()
    return paginas


def _extrair_texto_de_arquivo(filepath: str) -> List[Dict[str, Any]]:
    """
    Extrai texto de PDF, CSV, XLSX/XLS ou DOCX (obs 4 validador V8: antes so
    PDF; CSV/XLSX davam erro mesmo com o accept prometendo esses formatos).
    Retorna a mesma estrutura de _extrair_texto_por_paginas (lista de
    {pagina, texto, chars}) para reaproveitar todo o pipeline a jusante.
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".pdf":
        return _extrair_texto_por_paginas(filepath)

    if ext in (".csv", ".xlsx", ".xls"):
        import pandas as _pd
        try:
            if ext == ".csv":
                # tenta separadores comuns de ERP brasileiro
                try:
                    df = _pd.read_csv(filepath, sep=None, engine="python", dtype=str)
                except Exception:
                    df = _pd.read_csv(filepath, sep=";", dtype=str)
            else:
                df = _pd.read_excel(filepath, dtype=str)
        except Exception as e:
            print(f"[TOOLS] Erro lendo planilha {ext}: {e}")
            return []
        df = df.fillna("")
        # Cada linha = um "registro"; texto tabular legivel pela IA
        cabecalho = " | ".join(str(c) for c in df.columns)
        linhas = []
        for _, row in df.iterrows():
            linhas.append(" | ".join(str(v) for v in row.values))
        texto = cabecalho + "\n" + "\n".join(linhas)
        return [{"pagina": 1, "texto": texto, "chars": len(texto), "linhas_tabela": len(df)}]

    if ext in (".docx", ".doc"):
        try:
            import docx as _docx
            d = _docx.Document(filepath)
            partes = [p.text for p in d.paragraphs if p.text.strip()]
            for tbl in d.tables:
                for r in tbl.rows:
                    partes.append(" | ".join(c.text.strip() for c in r.cells))
            texto = "\n".join(partes)
            return [{"pagina": 1, "texto": texto, "chars": len(texto)}]
        except Exception as e:
            print(f"[TOOLS] Erro lendo {ext}: {e}")
            return []

    print(f"[TOOLS] Formato nao suportado: {ext}")
    return []


def _encontrar_paginas_specs(paginas: List[Dict[str, Any]]) -> str:
    """
    Busca inteligentemente as páginas que contêm especificações técnicas.
    Retorna o texto concatenado das páginas relevantes.
    """
    keywords_specs = [
        'especificações', 'specifications', 'technical data', 'dados técnicos',
        'características técnicas', 'informações técnicas', 'technical information',
        'dimensões', 'dimensions', 'peso', 'weight', 'voltagem', 'voltage',
        'alimentação', 'power supply', 'consumo', 'consumption', 'temperatura',
        'faixa de medição', 'range', 'precisão', 'accuracy', 'sensibilidade'
    ]

    paginas_relevantes = []

    for pag in paginas:
        texto_lower = pag["texto"].lower()
        score = sum(1 for kw in keywords_specs if kw in texto_lower)
        if score >= 2:  # Pelo menos 2 keywords
            paginas_relevantes.append((score, pag["pagina"], pag["texto"]))

    # Ordenar por score (mais relevantes primeiro)
    paginas_relevantes.sort(key=lambda x: x[0], reverse=True)

    # Pegar as 10 páginas mais relevantes
    texto_specs = ""
    for score, num, texto in paginas_relevantes[:10]:
        texto_specs += f"\n\n=== PÁGINA {num} ===\n{texto}"

    return texto_specs


def _extrair_specs_em_chunks(texto_completo: str, produto_id: str, db, campos_mascara: list = None) -> List[Dict]:
    """
    Processa documento grande em chunks e extrai especificações.
    Se campos_mascara fornecido, usa prompt dirigido para extrair exatamente esses campos.
    """
    MAX_CHUNK_SIZE = 60000
    specs_totais = []

    if len(texto_completo) <= MAX_CHUNK_SIZE:
        chunks = [texto_completo]
    else:
        chunks = []
        for i in range(0, len(texto_completo), MAX_CHUNK_SIZE):
            chunks.append(texto_completo[i:i + MAX_CHUNK_SIZE])

    print(f"[TOOLS] Processando {len(chunks)} chunk(s) de specs")

    for i, chunk in enumerate(chunks):
        print(f"[TOOLS] Processando chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")

        # Usar prompt dirigido se temos campos_mascara
        if campos_mascara and isinstance(campos_mascara, list) and len(campos_mascara) > 0:
            prompt = _build_prompt_mascara(chunk, campos_mascara)
        else:
            prompt = PROMPT_EXTRAIR_SPECS.format(texto=chunk)

        resposta = call_deepseek([{"role": "user", "content": prompt}], max_tokens=16000)

        try:
            specs = _extrair_json_array(resposta)
            if specs:
                print(f"[TOOLS] Chunk {i+1}: {len(specs)} specs encontradas")

                for spec in specs:
                    # Aceitar tanto 'nome_especificacao' quanto 'nome'
                    nome_spec = spec.get('nome_especificacao') or spec.get('nome') or 'N/A'

                    # Evitar duplicatas
                    if not any((s.get('nome_especificacao') or s.get('nome')) == nome_spec for s in specs_totais):
                        # db=None: modo "extrair sem persistir" (usado pelo merge
                        # do reprocessar, obs 10) — apenas retorna os dicts.
                        if db is not None:
                            spec_obj = ProdutoEspecificacao(
                                produto_id=produto_id,
                                nome_especificacao=nome_spec,
                                valor=spec.get('valor', 'N/A'),
                                unidade=spec.get('unidade'),
                                valor_numerico=spec.get('valor_numerico'),
                                operador=spec.get('operador'),
                                valor_min=spec.get('valor_min'),
                                valor_max=spec.get('valor_max')
                            )
                            db.add(spec_obj)
                        # Normalizar o spec para usar nome_especificacao
                        spec['nome_especificacao'] = nome_spec
                        specs_totais.append(spec)
        except json.JSONDecodeError as e:
            print(f"[TOOLS] Erro ao parsear chunk {i+1}: {e}")

    return specs_totais


def tool_processar_upload(filepath: str, user_id: str, empresa_id: str = None, nome_produto: str = None,
                          categoria: str = None, fabricante: str = None,
                          modelo: str = None, subclasse_id: str = None) -> Dict[str, Any]:
    """
    Processa um arquivo PDF uploadado:
    1. Extrai texto com PyMuPDF (todas as páginas)
    2. Busca inteligentemente páginas com especificações
    3. Usa IA para identificar nome do produto, fabricante e especificações
    4. Usa campos_mascara da subclasse (se disponível) para guiar extração
    5. Salva produto e specs no banco
    """
    db = get_db()
    try:
        # 1. Extrair texto do arquivo (PDF/CSV/XLSX/DOCX — obs 4 validador V8)
        print(f"[TOOLS] Extraindo texto de: {filepath}")
        paginas = _extrair_texto_de_arquivo(filepath)
        texto_completo = "\n".join([p["texto"] for p in paginas])

        if not texto_completo.strip():
            _ext = os.path.splitext(filepath)[1].lower()
            return {"success": False, "error": f"Não foi possível extrair texto do arquivo ({_ext or 'sem extensão'}). Formatos suportados: PDF, CSV, XLSX, XLS, DOCX."}

        print(f"[TOOLS] Arquivo: {len(paginas)} bloco(s), {len(texto_completo)} caracteres")

        # === MULTI-ITEM (obs 5/8 validador V8): NF / plano de contas com varios
        # produtos devem gerar N cadastros, nao so o primeiro. So entra nesse
        # modo quando o usuario NAO forcou um nome_produto especifico e o
        # documento aparenta ser multi-item (tabela com >1 linha OU nome de
        # arquivo sugere nota fiscal / plano de contas). PDF de manual unico
        # segue o fluxo mono-produto original intacto. ===
        _fname = os.path.basename(filepath).lower()
        _linhas_tab = sum(int(p.get("linhas_tabela") or 0) for p in paginas)
        _sugere_multi = (_linhas_tab > 1) or any(
            k in _fname for k in ("nota", "nfe", "nfs", "nf_", "plano", "conta", "erp", "cadastro")
        )
        if (not nome_produto or not nome_produto.strip()) and _sugere_multi:
            lista = _extrair_lista_produtos(texto_completo)
            if len(lista) > 1:
                print(f"[TOOLS] Multi-item detectado: {len(lista)} produtos no documento")
                criados, pulados = [], []
                # nomes ja existentes p/ dedupe (normalizado)
                import unicodedata as _ud2
                def _nz(t):
                    return ' '.join(_ud2.normalize('NFKD', (t or '').lower()).encode('ASCII', 'ignore').decode('ASCII').split())
                existentes = { _nz(p.nome) for p in db.query(Produto).filter(Produto.empresa_id == empresa_id).all() }
                for item in lista:
                    nz = _nz(item["nome"])
                    if nz in existentes:
                        pulados.append({"nome": item["nome"], "motivo": "ja cadastrado"})
                        continue
                    cat = item.get("categoria") or "equipamento"
                    if cat not in ('equipamento','reagente','insumo_hospitalar','insumo_laboratorial',
                                   'informatica','redes','mobiliario','eletronico','outro'):
                        cat = "equipamento"
                    prod = Produto(
                        user_id=user_id, empresa_id=empresa_id,
                        nome=item["nome"], categoria=cat,
                        fabricante=item.get("fabricante"), modelo=item.get("modelo"),
                    )
                    db.add(prod)
                    db.flush()
                    existentes.add(nz)
                    criados.append({"id": prod.id, "nome": prod.nome})
                # COMMIT antes de disparar background: a thread de metadados
                # abre sessao propria e so enxerga o produto se ja persistido.
                # Disparar antes do commit perdia os inserts (produtos nao
                # persistiam apesar de "criados" no log).
                db.commit()
                # Metadados em background SO apos commit (produtos ja no banco)
                for _c in criados:
                    try:
                        import threading as _th
                        _pid = _c["id"]
                        _th.Thread(target=lambda pid=_pid: processar_metadados_produto(pid),
                                   daemon=True, name=f"metadados-{_pid}").start()
                    except Exception as _e:
                        print(f"[TOOLS] bg metadados multi {_e}")
                print(f"[TOOLS] Multi-item: {len(criados)} criados, {len(pulados)} pulados")
                return {
                    "success": True,
                    "multi_item": True,
                    "total_documento": len(lista),
                    "produtos_criados": len(criados),
                    "produtos_pulados": len(pulados),
                    "criados": criados,
                    "pulados": pulados,
                    "nome": f"{len(criados)} produtos importados",
                }
            # len(lista) <= 1: cai no fluxo mono-produto abaixo

        # 2. Se não tem nome do produto, extrair automaticamente via IA
        if not nome_produto or nome_produto.strip() == "":
            print(f"[TOOLS] Extraindo info do produto automaticamente...")
            # Usar primeiras páginas para identificar produto
            texto_inicio = texto_completo[:10000]
            info_produto = _extrair_info_produto(texto_inicio)
            print(f"[TOOLS] Info extraída: {info_produto}")
            nome_produto = info_produto.get("nome", "Produto sem nome")
            if not fabricante:
                fabricante = info_produto.get("fabricante")
            if not modelo:
                modelo = info_produto.get("modelo")
            if not categoria:
                categoria = info_produto.get("categoria", "equipamento")

        # Garantir categoria válida
        categorias_validas = ['equipamento', 'reagente', 'insumo_hospitalar', 'insumo_laboratorial',
                             'informatica', 'redes', 'mobiliario', 'eletronico', 'outro']
        if not categoria or categoria not in categorias_validas:
            categoria = "equipamento"

        # 3. Verificar se produto já existe (mesmo nome + mesmo usuário)
        # Normalizar nome para comparação (remover espaços extras, lowercase)
        import unicodedata
        def normalizar_nome(nome):
            if not nome:
                return ""
            # Remover acentos
            nome = unicodedata.normalize('NFKD', nome).encode('ASCII', 'ignore').decode('ASCII')
            # Lowercase e remover espaços extras
            nome = ' '.join(nome.lower().split())
            return nome

        nome_normalizado = normalizar_nome(nome_produto)

        # Buscar todos os produtos do usuário para comparação normalizada
        produtos_usuario = db.query(Produto).filter(Produto.empresa_id == empresa_id).all()
        produto_existente = None

        for p in produtos_usuario:
            # Comparar nome normalizado
            if normalizar_nome(p.nome) == nome_normalizado:
                produto_existente = p
                break
            # Comparar modelo se disponível
            if modelo and p.modelo and normalizar_nome(p.modelo) == normalizar_nome(modelo):
                produto_existente = p
                break

        if produto_existente:
            return {
                "success": False,
                "error": f"Produto já cadastrado: '{produto_existente.nome}' (ID: {produto_existente.id})",
                "duplicado": True,
                "produto_existente": {
                    "id": produto_existente.id,
                    "nome": produto_existente.nome,
                    "modelo": produto_existente.modelo,
                    "fabricante": produto_existente.fabricante
                }
            }

        # 4. Validar subclasse e carregar campos_mascara
        campos_mascara = None
        if subclasse_id:
            sub = db.query(SubclasseProduto).filter(SubclasseProduto.id == subclasse_id).first()
            if sub:
                if sub.campos_mascara:
                    try:
                        campos_mascara = json.loads(sub.campos_mascara) if isinstance(sub.campos_mascara, str) else sub.campos_mascara
                        print(f"[TOOLS] Usando campos_mascara da subclasse '{sub.nome}': {len(campos_mascara)} campos")
                    except Exception:
                        campos_mascara = None
            else:
                subclasse_id = None  # ID inválido

        # 4.1 Auto-detectar subclasse se não informada
        if not subclasse_id and nome_produto:
            print(f"[TOOLS] Auto-detectando subclasse para '{nome_produto}'...")
            import unicodedata as _ud
            def _norm(t):
                return _ud.normalize('NFKD', (t or '').lower()).encode('ASCII', 'ignore').decode('ASCII')

            # Sinônimos e palavras-chave extras por subclasse (nome normalizado → keywords)
            _KEYWORDS_EXTRA = {
                "desktops e notebooks": ["desktop", "notebook", "laptop", "optiplex", "thinkpad", "thinkcentre", "latitude", "inspiron", "vostro", "computador", "pc"],
                "impressoras": ["impressora", "laserjet", "deskjet", "multifuncional", "mfp", "printer"],
                "desfibriladores": ["desfibrilador", "cardioversor", "dea", "aed"],
                "monitores": ["monitor"],
                "monitores de sinais vitais": ["multiparametro", "multiparametros", "sinais vitais", "umec", "beneview"],
                "oximetros": ["oximetro", "oximeto", "oximetria", "spo2"],
                "bombas de infusao": ["bomba de infusao", "bomba infusao", "infusao volumetrica"],
                "cadeiras de rodas": ["cadeira de rodas", "cadeira rodas"],
                "autoclaves": ["autoclave"],
                "switches": ["switch", "sg350", "sg300", "catalyst"],
                "roteadores": ["roteador", "router", "archer", "wireless"],
                "nobreaks": ["nobreak", "no-break", "ups"],
                "analisadores hematologicos": ["analisador hematologia", "hematologia", "bc-5150", "bc-5000", "xn-1000", "xn-550"],
                "eletrocardiografos": ["eletrocardiografo", "ecg"],
                "camas hospitalares": ["cama hospitalar", "cama hospital"],
            }

            todas_subclasses = db.query(SubclasseProduto).all()
            nome_norm = _norm(nome_produto)
            palavras_nome = nome_norm.split()
            melhor_sub = None
            melhor_score = 0

            for s in todas_subclasses:
                sub_norm = _norm(s.nome)
                score = 0

                # 1) Match por keywords extras (prioridade alta)
                keywords = _KEYWORDS_EXTRA.get(sub_norm, [])
                for kw in keywords:
                    kw_n = _norm(kw)
                    if kw_n in nome_norm:
                        # Multi-word keyword vale mais
                        score = max(score, len(kw_n.split()) * 100 + len(kw_n))

                # 2) Match por palavras da subclasse no nome do produto
                sub_palavras = [p for p in sub_norm.split() if len(p) >= 3 and p not in ('de', 'do', 'da', 'dos', 'das', 'e')]
                if sub_palavras:
                    matches = 0
                    for sp in sub_palavras:
                        sp_base = sp.rstrip('s').rstrip('es') if len(sp) > 4 else sp
                        for pn in palavras_nome:
                            pn_base = pn.rstrip('s').rstrip('es') if len(pn) > 4 else pn
                            if sp_base == pn_base or (len(sp_base) >= 5 and (sp_base in pn_base or pn_base in sp_base)):
                                matches += 1
                                break
                    if matches > 0:
                        # Proporção de palavras da subclasse que deram match
                        ratio = matches / len(sub_palavras)
                        word_score = int(ratio * 50) + matches * 10
                        score = max(score, word_score)

                if score > melhor_score:
                    melhor_score = score
                    melhor_sub = s

            if melhor_sub and melhor_score >= 10:
                subclasse_id = melhor_sub.id
                print(f"[TOOLS] Subclasse auto-detectada: '{melhor_sub.nome}' (score={melhor_score})")
                if melhor_sub.campos_mascara and not campos_mascara:
                    try:
                        campos_mascara = json.loads(melhor_sub.campos_mascara) if isinstance(melhor_sub.campos_mascara, str) else melhor_sub.campos_mascara
                        print(f"[TOOLS] Usando campos_mascara auto-detectada: {len(campos_mascara)} campos")
                    except Exception:
                        pass
            else:
                print(f"[TOOLS] Nenhuma subclasse encontrada para '{nome_produto}'")

        # 5. Buscar empresa pelo empresa_id
        empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first() if empresa_id else None

        # 5.1 Criar produto no banco
        produto = Produto(
            user_id=user_id,
            empresa_id=empresa_id,
            nome=nome_produto,
            categoria=categoria,
            fabricante=fabricante,
            modelo=modelo,
            subclasse_id=subclasse_id
        )
        db.add(produto)
        db.flush()

        # 6. Salvar documento (texto completo)
        doc_registro = ProdutoDocumento(
            produto_id=produto.id,
            tipo='manual',
            nome_arquivo=os.path.basename(filepath),
            path_arquivo=filepath,
            texto_extraido=texto_completo,
            processado=False
        )
        db.add(doc_registro)

        # 7. Buscar páginas com especificações
        print(f"[TOOLS] Buscando páginas com especificações técnicas...")
        texto_specs = _encontrar_paginas_specs(paginas)

        if not texto_specs:
            print(f"[TOOLS] Nenhuma página de specs encontrada, usando últimas páginas")
            ultimas_paginas = paginas[-20:] if len(paginas) > 20 else paginas
            texto_specs = "\n".join([p["texto"] for p in ultimas_paginas])

        print(f"[TOOLS] Texto de specs: {len(texto_specs)} caracteres")

        # 8. Extrair especificações em chunks (com máscara se disponível)
        specs_salvas = _extrair_specs_em_chunks(texto_specs, produto.id, db, campos_mascara=campos_mascara)

        # 7. Marcar documento como processado
        doc_registro.processado = True
        db.commit()

        # Background: buscar CATMAT e gerar termos de busca semânticos
        try:
            import threading
            _pid_meta = produto.id
            def _run_metadados_bg(pid=_pid_meta):
                try:
                    processar_metadados_produto(pid)
                    print(f"[TOOLS] Metadados background concluido para {pid}")
                except Exception as ex:
                    print(f"[TOOLS] Erro no thread metadados {pid}: {ex}")
            threading.Thread(target=_run_metadados_bg, daemon=True, name=f"metadados-{_pid_meta}").start()
            print(f"[TOOLS] Metadados em background para produto {produto.id}")
        except Exception as e:
            print(f"[TOOLS] Erro ao iniciar metadados background: {e}")

        return {
            "success": True,
            "produto_id": produto.id,
            "nome": nome_produto,
            "specs_extraidas": len(specs_salvas),
            "specs": specs_salvas[:10],  # Retornar primeiras 10
            # Adicionar estrutura completa para o app.py
            "produto": {
                "id": produto.id,
                "nome": nome_produto,
                "fabricante": fabricante,
                "modelo": modelo,
                "categoria": categoria
            },
            "especificacoes": specs_salvas
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_extrair_especificacoes(texto: str, produto_id: str, user_id: str, empresa_id: str = None) -> Dict[str, Any]:
    """
    Extrai especificações de um texto e salva no banco.
    """
    db = get_db()
    try:
        # Verificar se produto existe e pertence ao usuário
        produto = db.query(Produto).filter(
            Produto.id == produto_id,
            Produto.empresa_id == empresa_id
        ).first()

        if not produto:
            return {"success": False, "error": "Produto não encontrado"}

        # Extrair specs com IA
        prompt = PROMPT_EXTRAIR_SPECS.format(texto=texto[:15000])
        resposta = call_deepseek([{"role": "user", "content": prompt}], max_tokens=8000)

        specs_salvas = []
        try:
            specs = _extrair_json_array(resposta)
            if specs:
                for spec in specs:
                    spec_obj = ProdutoEspecificacao(
                        produto_id=produto_id,
                        nome_especificacao=spec.get('nome_especificacao', 'N/A'),
                        valor=spec.get('valor', 'N/A'),
                        unidade=spec.get('unidade'),
                        valor_numerico=spec.get('valor_numerico'),
                        operador=spec.get('operador'),
                        valor_min=spec.get('valor_min'),
                        valor_max=spec.get('valor_max')
                    )
                    db.add(spec_obj)
                    specs_salvas.append(spec)
                db.commit()
        except json.JSONDecodeError:
            pass

        return {
            "success": True,
            "produto_id": produto_id,
            "specs_extraidas": len(specs_salvas)
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_reprocessar_produto(produto_id: str, user_id: str, empresa_id: str = None) -> Dict[str, Any]:
    """
    Reprocessa um produto existente para extrair especificações novamente.
    Útil quando a extração inicial falhou ou foi incompleta.
    Usa o documento já salvo no banco.
    """
    db = get_db()
    try:
        # Verificar se produto existe e pertence ao usuário
        produto = db.query(Produto).filter(
            Produto.id == produto_id,
            Produto.empresa_id == empresa_id
        ).first()

        if not produto:
            return {"success": False, "error": "Produto não encontrado"}

        # Buscar documento do produto
        documento = db.query(ProdutoDocumento).filter(
            ProdutoDocumento.produto_id == produto_id
        ).first()

        if not documento:
            texto_specs = produto.descricao or f"{produto.nome} {produto.modelo or ''}".strip()
            if not texto_specs:
                return {"success": False, "error": "Nenhum texto disponível para reprocessar (sem documento e sem descrição)"}
        elif documento.path_arquivo and os.path.exists(documento.path_arquivo):
            print(f"[TOOLS] Reprocessando produto do arquivo: {documento.path_arquivo}")
            paginas = _extrair_texto_por_paginas(documento.path_arquivo)
            texto_specs = _encontrar_paginas_specs(paginas)

            if not texto_specs:
                ultimas_paginas = paginas[-20:] if len(paginas) > 20 else paginas
                texto_specs = "\n".join([p["texto"] for p in ultimas_paginas])
        elif documento.texto_extraido:
            # Usar texto salvo
            texto_specs = documento.texto_extraido
        else:
            return {"success": False, "error": "Nenhum texto disponível para reprocessar"}

        # MERGE (obs 10 validador V8): NAO apagar specs existentes — reprocessar
        # deve COMPLEMENTAR. Specs cadastradas manualmente (UC-F08) ou extraidas
        # antes sao preservadas; specs com mesmo nome sao atualizadas; novas sao
        # adicionadas. Antes o codigo fazia DELETE incondicional e destruia tudo.
        specs_antigas = db.query(ProdutoEspecificacao).filter(
            ProdutoEspecificacao.produto_id == produto_id
        ).all()
        idx_antigas = { (s.nome_especificacao or "").strip().lower(): s for s in specs_antigas }

        # Extrai novas specs SEM persistir (db None evita db.add interno)
        print(f"[TOOLS] Reprocessando specs ({len(texto_specs)} chars) — modo merge")
        specs_extraidas = _extrair_specs_em_chunks(texto_specs, produto_id, db=None)

        atualizadas = 0
        adicionadas = 0
        for spec in specs_extraidas:
            nome_spec = (spec.get('nome_especificacao') or spec.get('nome') or 'N/A')
            chave = nome_spec.strip().lower()
            existente = idx_antigas.get(chave)
            if existente is not None:
                # Atualiza valor/unidade da spec ja existente (preserva o registro)
                existente.valor = spec.get('valor', existente.valor)
                if spec.get('unidade') is not None:
                    existente.unidade = spec.get('unidade')
                if spec.get('valor_numerico') is not None:
                    existente.valor_numerico = spec.get('valor_numerico')
                if spec.get('operador') is not None:
                    existente.operador = spec.get('operador')
                if spec.get('valor_min') is not None:
                    existente.valor_min = spec.get('valor_min')
                if spec.get('valor_max') is not None:
                    existente.valor_max = spec.get('valor_max')
                atualizadas += 1
            else:
                db.add(ProdutoEspecificacao(
                    produto_id=produto_id,
                    nome_especificacao=nome_spec,
                    valor=spec.get('valor', 'N/A'),
                    unidade=spec.get('unidade'),
                    valor_numerico=spec.get('valor_numerico'),
                    operador=spec.get('operador'),
                    valor_min=spec.get('valor_min'),
                    valor_max=spec.get('valor_max'),
                ))
                idx_antigas[chave] = True  # evita duplicar se repetir no mesmo lote
                adicionadas += 1

        db.commit()
        print(f"[TOOLS] Merge specs: {adicionadas} novas, {atualizadas} atualizadas, "
              f"{len(specs_antigas)} preservadas (nenhuma apagada)")

        return {
            "success": True,
            "produto_id": produto_id,
            "produto_nome": produto.nome,
            "specs_extraidas": len(specs_extraidas),
            "specs_adicionadas": adicionadas,
            "specs_atualizadas": atualizadas,
            "specs_preservadas": len(specs_antigas),
            "specs": specs_extraidas[:20]
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_atualizar_produto(produto_id: str, user_id: str, empresa_id: str = None, nome: str = None,
                           fabricante: str = None, modelo: str = None,
                           categoria: str = None) -> Dict[str, Any]:
    """
    Atualiza informações de um produto existente.
    """
    db = get_db()
    try:
        produto = db.query(Produto).filter(
            Produto.id == produto_id,
            Produto.empresa_id == empresa_id
        ).first()

        if not produto:
            return {"success": False, "error": "Produto não encontrado"}

        if nome:
            produto.nome = nome
        if fabricante:
            produto.fabricante = fabricante
        if modelo:
            produto.modelo = modelo
        if categoria:
            categorias_validas = ['equipamento', 'reagente', 'insumo_hospitalar', 'insumo_laboratorial',
                                 'informatica', 'redes', 'mobiliario', 'eletronico', 'outro']
            if categoria in categorias_validas:
                produto.categoria = categoria

        db.commit()

        return {
            "success": True,
            "produto": {
                "id": produto.id,
                "nome": produto.nome,
                "fabricante": produto.fabricante,
                "modelo": produto.modelo,
                "categoria": produto.categoria
            }
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_excluir_produto(produto_id: str, user_id: str, empresa_id: str = None) -> Dict[str, Any]:
    """
    Exclui um produto e todas suas especificações e documentos associados.
    """
    db = get_db()
    try:
        produto = db.query(Produto).filter(
            Produto.id == produto_id,
            Produto.empresa_id == empresa_id
        ).first()

        if not produto:
            return {"success": False, "error": "Produto não encontrado"}

        nome_produto = produto.nome

        # Excluir especificações associadas
        db.query(ProdutoEspecificacao).filter(
            ProdutoEspecificacao.produto_id == produto_id
        ).delete()

        # Excluir documentos associados
        db.query(ProdutoDocumento).filter(
            ProdutoDocumento.produto_id == produto_id
        ).delete()

        # Excluir análises associadas
        db.query(Analise).filter(
            Analise.produto_id == produto_id
        ).delete()

        # Excluir o produto
        db.delete(produto)
        db.commit()

        return {
            "success": True,
            "message": f"Produto '{nome_produto}' excluído com sucesso, incluindo especificações, documentos e análises associadas."
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_excluir_edital(edital_id: str, user_id: str, empresa_id: str = None) -> Dict[str, Any]:
    """
    Exclui um edital e todos seus requisitos e análises associados.
    """
    db = get_db()
    try:
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()

        if not edital:
            return {"success": False, "error": "Edital não encontrado"}

        numero_edital = edital.numero

        # Excluir requisitos associados
        db.query(EditalRequisito).filter(
            EditalRequisito.edital_id == edital_id
        ).delete()

        # Excluir documentos associados
        db.query(EditalDocumento).filter(
            EditalDocumento.edital_id == edital_id
        ).delete()

        # Excluir análises associadas
        db.query(Analise).filter(
            Analise.edital_id == edital_id
        ).delete()

        # Excluir detalhes de análise (se existirem análises com detalhes)
        # Primeiro buscar IDs das análises
        analise_ids = [a.id for a in db.query(Analise.id).filter(Analise.edital_id == edital_id).all()]
        if analise_ids:
            db.query(AnaliseDetalhe).filter(
                AnaliseDetalhe.analise_id.in_(analise_ids)
            ).delete(synchronize_session=False)

        # Excluir o edital
        db.delete(edital)
        db.commit()

        return {
            "success": True,
            "message": f"Edital '{numero_edital}' excluído com sucesso, incluindo requisitos, documentos e análises associadas."
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_excluir_editais_multiplos(edital_ids: List[str], user_id: str, empresa_id: str = None) -> Dict[str, Any]:
    """
    Exclui múltiplos editais de uma vez.
    """
    db = get_db()
    try:
        excluidos = []
        erros = []

        for edital_id in edital_ids:
            resultado = tool_excluir_edital(edital_id, user_id, empresa_id=empresa_id)
            if resultado.get("success"):
                excluidos.append(edital_id)
            else:
                erros.append({"id": edital_id, "erro": resultado.get("error")})

        return {
            "success": len(excluidos) > 0,
            "excluidos": len(excluidos),
            "erros": len(erros),
            "detalhes_erros": erros if erros else None,
            "message": f"{len(excluidos)} edital(is) excluído(s) com sucesso." + (f" {len(erros)} erro(s)." if erros else "")
        }
    finally:
        db.close()


def tool_atualizar_edital(edital_id: str, user_id: str, empresa_id: str = None, numero: str = None,
                          orgao: str = None, objeto: str = None,
                          modalidade: str = None, status: str = None,
                          valor_referencia: float = None,
                          data_abertura: str = None, url: str = None) -> Dict[str, Any]:
    """
    Atualiza informações de um edital existente.
    """
    db = get_db()
    try:
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()

        if not edital:
            return {"success": False, "error": "Edital não encontrado"}

        if numero:
            edital.numero = numero
        if orgao:
            edital.orgao = orgao
        if objeto:
            edital.objeto = objeto
        if modalidade:
            modalidades_validas = ['pregao_eletronico', 'pregao_presencial', 'concorrencia',
                                   'tomada_precos', 'convite', 'dispensa', 'inexigibilidade']
            if modalidade in modalidades_validas:
                edital.modalidade = modalidade
        if status:
            status_validos = ['novo', 'analisando', 'participar', 'nao_participar',
                             'proposta_enviada', 'ganho', 'perdido', 'cancelado']
            if status in status_validos:
                edital.status = status
        if valor_referencia is not None:
            edital.valor_referencia = valor_referencia
        if data_abertura:
            from datetime import datetime
            try:
                edital.data_abertura = datetime.strptime(data_abertura, "%Y-%m-%d")
            except:
                pass  # Ignorar se formato inválido
        if url:
            edital.url = url

        db.commit()

        return {
            "success": True,
            "edital": {
                "id": edital.id,
                "numero": edital.numero,
                "orgao": edital.orgao,
                "objeto": edital.objeto[:100] + "..." if len(edital.objeto or '') > 100 else edital.objeto,
                "modalidade": edital.modalidade,
                "status": edital.status,
                "valor_referencia": float(edital.valor_referencia) if edital.valor_referencia else None
            }
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_cadastrar_fonte(nome: str, tipo: str, url_base: str,
                         descricao: str = None, api_key: str = None) -> Dict[str, Any]:
    """
    Cadastra uma nova fonte de editais no banco.
    Verifica duplicatas por nome ou URL.
    """
    db = get_db()
    try:
        # Verificar se já existe fonte com mesmo nome ou URL
        fonte_existente = db.query(FonteEdital).filter(
            (FonteEdital.nome.ilike(nome)) |
            (FonteEdital.url_base == url_base)
        ).first()

        if fonte_existente:
            return {
                "success": False,
                "error": f"Fonte já cadastrada: '{fonte_existente.nome}' ({fonte_existente.url_base})",
                "duplicada": True,
                "fonte_existente": {
                    "id": fonte_existente.id,
                    "nome": fonte_existente.nome,
                    "url": fonte_existente.url_base
                }
            }

        fonte = FonteEdital(
            nome=nome,
            tipo=tipo,
            url_base=url_base,
            descricao=descricao,
            api_key=api_key,
            ativo=True
        )
        db.add(fonte)
        db.commit()

        return {
            "success": True,
            "fonte_id": fonte.id,
            "nome": nome,
            "message": f"Fonte '{nome}' cadastrada com sucesso!"
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_listar_fontes() -> Dict[str, Any]:
    """
    Lista todas as fontes de editais cadastradas.
    """
    db = get_db()
    try:
        fontes = db.query(FonteEdital).filter(FonteEdital.ativo == True).all()
        return {
            "success": True,
            "fontes": [f.to_dict() for f in fontes],
            "total": len(fontes)
        }
    finally:
        db.close()


def tool_buscar_editais_fonte(fonte: str, termo: str, user_id: str, empresa_id: str = None,
                               uf: str = None, modalidade: str = None,
                               buscar_detalhes: bool = True,
                               incluir_encerrados: bool = False,
                               dias_busca: int = 90) -> Dict[str, Any]:
    """
    Busca editais em uma fonte específica (PNCP).

    Args:
        buscar_detalhes: Se True, busca itens e PDF para cada edital (mais lento, mais completo)
        incluir_encerrados: Se True, inclui editais já encerrados (data abertura no passado)
        dias_busca: Janela de busca em dias (0 = sem limite, usa 730 dias como máximo técnico)
    """
    from datetime import timedelta

    db = get_db()
    try:
        # Buscar fonte no banco
        fonte_obj = db.query(FonteEdital).filter(
            (FonteEdital.id == fonte) | (FonteEdital.nome.ilike(f"%{fonte}%"))
        ).first()

        if not fonte_obj:
            return {"success": False, "error": f"Fonte '{fonte}' não encontrada"}

        editais_encontrados = []

        if 'PNCP' in fonte_obj.nome.upper():
            # Estratégia HÍBRIDA para PNCP:
            # 1. Search API (rápido, filtra por texto) para obter editais relevantes
            # 2. Endpoint de detalhes para buscar valorTotalEstimado em paralelo
            # Isso é MUITO mais rápido que baixar tudo via /contratacoes/publicacao
            try:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                import unicodedata

                hoje = datetime.now()
                janela = dias_busca if dias_busca > 0 else 730
                data_limite = hoje - timedelta(days=janela)

                def _sem_acento(txt):
                    return unicodedata.normalize('NFKD', txt).encode('ascii', 'ignore').decode('ascii')

                # Preparar palavras do termo para filtro ALL-words local
                termo_norm = _sem_acento(termo.lower())
                palavras_termo = [p for p in termo_norm.split() if len(p) > 2]

                print(f"[TOOLS] Buscando PNCP Search API + detalhes: q='{termo}', janela={janela}d")

                # ===== PASSO 1: Search API via Playwright (bypassa F5 Bot Defense) =====
                MAX_PAGINAS = 10
                all_items = []

                for pagina in range(1, MAX_PAGINAS + 1):
                    try:
                        data = _pncp_search_fetch(termo, pagina=pagina, tam_pagina=50)
                        items = data.get("items", [])
                        total = data.get("total", 0)

                        if pagina == 1:
                            print(f"[TOOLS] Search API: {total} resultados totais")

                        if not items:
                            break

                        all_items.extend(items)

                        if len(all_items) >= total:
                            break
                    except Exception as e:
                        print(f"[TOOLS] Search API página {pagina} erro: {e}")
                        break

                print(f"[TOOLS] Search API coletou: {len(all_items)} itens")

                # ===== PASSO 2: Filtrar e mapear =====
                editais_em_aberto = 0
                editais_encerrados = 0
                editais_sem_valor = []  # (indice, edital_data) para buscar valor depois

                for item in all_items:
                    descricao = (item.get('description', '') or '').lower()
                    titulo = (item.get('title', '') or '').lower()
                    texto_completo = f"{titulo} {descricao}"
                    texto_norm = _sem_acento(texto_completo)

                    # FILTRO 1: ANY-words match (basta 1 palavra do termo aparecer)
                    # A Search API do PNCP já faz busca por relevância; filtro local
                    # só garante que ao menos 1 palavra-chave esteja no texto.
                    if palavras_termo and not any(p in texto_norm for p in palavras_termo):
                        continue

                    # FILTRO 2: Janela de datas
                    data_pub_str = item.get('data_publicacao_pncp', '')
                    if data_pub_str:
                        try:
                            data_pub = datetime.fromisoformat(str(data_pub_str).replace('Z', '')[:19])
                            if data_pub < data_limite:
                                continue
                        except (ValueError, TypeError):
                            pass

                    # FILTRO 3: Encerrados
                    edital_encerrado = False
                    cancelado = item.get('cancelado', False)
                    situacao = (item.get('situacao_nome', '') or '').lower()

                    data_fim_vig = item.get('data_fim_vigencia', '')
                    if data_fim_vig:
                        try:
                            dt_fim = datetime.fromisoformat(str(data_fim_vig).replace('Z', '')[:19])
                            if dt_fim < hoje:
                                edital_encerrado = True
                        except (ValueError, TypeError):
                            pass

                    if item.get('tem_resultado', False):
                        edital_encerrado = True
                    if cancelado:
                        edital_encerrado = True
                    if situacao in ('suspensa', 'revogada', 'anulada', 'encerrada', 'homologada'):
                        edital_encerrado = True

                    if edital_encerrado:
                        editais_encerrados += 1
                        if not incluir_encerrados:
                            continue

                    # CV11-4 (Arnaldo Sprint 2 V8): excluir editais cuja data de abertura
                    # ja passou — sao licitacoes vencidas que poluiam o radar.
                    data_ab_str = item.get('data_inicio_vigencia', '') or item.get('data_abertura_proposta', '')
                    if data_ab_str and not incluir_encerrados:
                        try:
                            dt_ab = datetime.fromisoformat(str(data_ab_str).replace('Z', '')[:19])
                            if dt_ab < hoje:
                                editais_encerrados += 1
                                continue
                        except (ValueError, TypeError):
                            pass

                    editais_em_aberto += 1

                    # Extrair dados
                    orgao_nome = item.get('orgao_nome', 'N/A')
                    cnpj = (item.get('orgao_cnpj', '') or '').replace('.', '').replace('/', '').replace('-', '')
                    uf_item = item.get('uf', '')
                    # CV01-2b (Arnaldo Sprint 2 V8): aplicar filtro UF — o parametro
                    # `uf` chegava ate aqui mas nao era usado, retornando editais
                    # de qualquer estado mesmo quando o usuario filtrou (ex.: PR).
                    if uf:
                        ufs_alvo = [u.strip().upper() for u in (uf if isinstance(uf, list) else str(uf).split(',')) if u.strip()]
                        if ufs_alvo and (uf_item or '').upper() not in ufs_alvo:
                            continue
                    cidade = item.get('municipio_nome', '')
                    ano = item.get('ano')
                    seq = item.get('numero_sequencial')
                    numero_pncp = item.get('numero_controle_pncp', '')
                    item_url = item.get('item_url', '')

                    if item_url and not item_url.startswith('/compras/'):
                        link = f"https://pncp.gov.br{item_url}"
                    elif cnpj and ano and seq:
                        link = f"https://pncp.gov.br/app/editais/{cnpj}/{ano}/{seq}"
                    elif numero_pncp:
                        # numero_pncp formato: cnpj-1-seq/ano → cnpj/ano/seq
                        _m_pncp = re.match(r'(\d{14})-\d+-(\d+)/(\d{4})', numero_pncp)
                        link = f"https://pncp.gov.br/app/editais/{_m_pncp.group(1)}/{_m_pncp.group(3)}/{int(_m_pncp.group(2))}" if _m_pncp else None
                    else:
                        link = None

                    modalidade_api = (item.get('modalidade_licitacao_nome', '') or '').lower()
                    if 'eletrônico' in modalidade_api or 'eletronico' in modalidade_api:
                        modalidade_db = 'pregao_eletronico'
                    elif 'presencial' in modalidade_api:
                        modalidade_db = 'pregao_presencial'
                    elif 'concorrência' in modalidade_api or 'concorrencia' in modalidade_api:
                        modalidade_db = 'concorrencia'
                    elif 'tomada' in modalidade_api:
                        modalidade_db = 'tomada_precos'
                    elif 'convite' in modalidade_api:
                        modalidade_db = 'convite'
                    elif 'dispensa' in modalidade_api:
                        modalidade_db = 'dispensa'
                    elif 'inexigibilidade' in modalidade_api:
                        modalidade_db = 'inexigibilidade'
                    else:
                        modalidade_db = 'pregao_eletronico'

                    esfera = (item.get('esfera_nome', '') or '').lower()
                    if 'municipal' in esfera:
                        orgao_tipo = 'municipal'
                    elif 'estadual' in esfera or 'distrital' in esfera:
                        orgao_tipo = 'estadual'
                    elif 'federal' in esfera:
                        orgao_tipo = 'federal'
                    else:
                        orgao_tipo = 'municipal'

                    titulo_raw = item.get('title', '') or ''
                    numero_match = re.search(r'n[ºo°]\s*(.+)', titulo_raw, re.IGNORECASE)
                    if numero_match:
                        numero_edital = numero_match.group(1).strip()
                    elif item.get('numero'):
                        numero_edital = item.get('numero')
                    else:
                        # CV02-11 (Arnaldo Sprint 2 V8): nao usar titulo_raw como numero
                        # quando ele repete o orgao (ex.: "Pregão da Prefeitura de X"); melhor
                        # devolver "N/A" e deixar o usuario perceber dados faltantes.
                        titulo_norm = titulo_raw.lower().strip()
                        orgao_norm = (orgao_nome or '').lower().strip()
                        if titulo_norm and orgao_norm and orgao_norm in titulo_norm:
                            numero_edital = 'N/A'
                        else:
                            numero_edital = titulo_raw or 'N/A'

                    edital_data = {
                        "numero": numero_edital,
                        "orgao": orgao_nome,
                        "orgao_tipo": orgao_tipo,
                        "uf": uf_item,
                        "cidade": cidade,
                        "objeto": descricao[:500] if descricao else f"Contratação - {termo}",
                        "modalidade": modalidade_db,
                        "valor_referencia": item.get('valor_global'),
                        "data_publicacao": item.get('data_publicacao_pncp'),
                        "data_abertura": item.get('data_inicio_vigencia'),
                        "data_encerramento": item.get('data_fim_vigencia'),
                        "url": link,
                        "numero_pncp": numero_pncp,
                        "cnpj_orgao": cnpj,
                        "ano_compra": ano,
                        "seq_compra": seq,
                        "srp": False,
                        "situacao": item.get('situacao_nome'),
                        "fonte": "PNCP (API)",
                        "fonte_tipo": "api",
                        "encerrado": edital_encerrado,
                    }

                    # Enriquecer com itens e PDF (apenas para primeiros 5)
                    if buscar_detalhes and len(editais_encontrados) < 5:
                        edital_data = _enriquecer_edital_pncp(edital_data)

                    editais_encontrados.append(edital_data)

                    # Marcar para busca de valor se não tem
                    if not edital_data.get('valor_referencia') and cnpj and ano and seq:
                        editais_sem_valor.append((len(editais_encontrados) - 1, edital_data))

                # ===== PASSO 3: Buscar valores em paralelo (rápido, ~3-5s) =====
                if editais_sem_valor:
                    def _buscar_valor(args):
                        idx, ed = args
                        try:
                            url = f"{PNCP_BASE_URL}/orgaos/{ed['cnpj_orgao']}/compras/{ed['ano_compra']}/{ed['seq_compra']}"
                            resp = requests.get(url, headers={"Accept": "application/json"}, timeout=10)
                            if resp.status_code == 200:
                                dados = resp.json()
                                link_origem = dados.get('linkSistemaOrigem')
                                return idx, dados.get('valorTotalEstimado'), dados.get('valorTotalHomologado'), link_origem
                            return idx, None, None, None
                        except Exception:
                            return idx, None, None, None

                    n_buscar = len(editais_sem_valor)
                    max_w = min(n_buscar, 10)
                    print(f"[TOOLS] Buscando valores de {n_buscar} editais em paralelo ({max_w} workers)...")
                    valores_encontrados = 0
                    with ThreadPoolExecutor(max_workers=max_w) as executor:
                        futures = {executor.submit(_buscar_valor, args): args for args in editais_sem_valor}
                        for future in as_completed(futures, timeout=max(30, n_buscar * 2)):
                            try:
                                idx, valor_est, valor_hom, link_origem = future.result(timeout=10)
                                valor_final = valor_est or valor_hom
                                if valor_final:
                                    editais_encontrados[idx]['valor_referencia'] = valor_final
                                    valores_encontrados += 1
                                # Salvar linkSistemaOrigem como campo extra (site do órgão)
                                if link_origem:
                                    editais_encontrados[idx]['link_sistema_origem'] = link_origem
                            except Exception:
                                pass
                    print(f"[TOOLS] Valores obtidos: {valores_encontrados}/{n_buscar}")

                if incluir_encerrados:
                    print(f"[TOOLS] Encontrados {len(editais_encontrados)} editais (incluindo {editais_encerrados} encerrados)")
                else:
                    print(f"[TOOLS] Encontrados {len(editais_encontrados)} editais EM ABERTO (filtrados {editais_encerrados} já encerrados)")

            except Exception as e:
                print(f"[TOOLS] Erro ao buscar PNCP: {e}")
                import traceback
                traceback.print_exc()

        # Se não encontrou na API, buscar editais existentes no banco que correspondam ao termo
        if not editais_encontrados:
            print(f"[TOOLS] Buscando no banco local por '{termo}'")
            editais_db = db.query(Edital).filter(
                Edital.empresa_id == empresa_id,
                Edital.objeto.ilike(f"%{termo}%")
            ).order_by(Edital.created_at.desc()).limit(10).all()

            if editais_db:
                editais_encontrados = [e.to_dict() for e in editais_db]
            else:
                # Não criar fake - informar que não encontrou
                return {
                    "success": True,
                    "fonte": fonte_obj.nome,
                    "termo": termo,
                    "editais": [],
                    "total": 0,
                    "mensagem": f"Nenhum edital encontrado para '{termo}'. A API do PNCP pode estar indisponível ou não há editais recentes com esse termo."
                }

        # NÃO faz commit - não salvou nada no banco
        return {
            "success": True,
            "fonte": fonte_obj.nome,
            "termo": termo,
            "editais": editais_encontrados,  # Já são dicts, não precisa converter
            "total": len(editais_encontrados)
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# ==================== BEC-SP API (Bolsa Eletrônica de Compras - SP) ====================

BEC_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache", "bec")


def _bec_cache_path(endpoint_key: str) -> str:
    os.makedirs(BEC_CACHE_DIR, exist_ok=True)
    return os.path.join(BEC_CACHE_DIR, f"bec_{endpoint_key}.json")


def _bec_cache_valid(endpoint_key: str) -> bool:
    path = _bec_cache_path(endpoint_key)
    if not os.path.exists(path):
        return False
    mtime = os.path.getmtime(path)
    age_hours = (datetime.now().timestamp() - mtime) / 3600
    return age_hours < BEC_CACHE_TTL_HOURS


def _bec_cache_read(endpoint_key: str) -> list:
    if not _bec_cache_valid(endpoint_key):
        return None
    try:
        with open(_bec_cache_path(endpoint_key), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _bec_cache_write(endpoint_key: str, data: list):
    try:
        os.makedirs(BEC_CACHE_DIR, exist_ok=True)
        with open(_bec_cache_path(endpoint_key), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        print(f"[BEC-CACHE] Gravado {len(data)} itens em {endpoint_key}")
    except Exception as e:
        print(f"[BEC-CACHE] Erro ao gravar: {e}")


def _bec_buscar_lista_itens(tipo_pregao: str) -> list:
    """Baixa lista completa de itens BEC de um tipo de pregão. Usa cache 24h."""
    cached = _bec_cache_read(tipo_pregao)
    if cached is not None:
        print(f"[BEC] Cache hit para {tipo_pregao}: {len(cached)} itens")
        return cached

    url = f"{BEC_API_BASE_URL}/{tipo_pregao}/NegociacaoItemOC/"
    print(f"[BEC] Baixando lista completa: {url}")
    try:
        resp = requests.get(url, timeout=60, headers={"Accept": "application/json"})
        if resp.status_code != 200:
            print(f"[BEC] Erro HTTP {resp.status_code} em {tipo_pregao}")
            return []
        itens = resp.json()
        if isinstance(itens, list):
            _bec_cache_write(tipo_pregao, itens)
            print(f"[BEC] Baixado {len(itens)} itens de {tipo_pregao}")
            return itens
        return []
    except requests.exceptions.Timeout:
        print(f"[BEC] Timeout ao baixar {tipo_pregao} (60s)")
        # Tentar cache stale
        stale = None
        try:
            with open(_bec_cache_path(tipo_pregao), 'r', encoding='utf-8') as f:
                stale = json.load(f)
        except Exception:
            pass
        if stale:
            print(f"[BEC] Usando cache stale ({len(stale)} itens)")
            return stale
        return []
    except Exception as e:
        print(f"[BEC] Erro ao baixar {tipo_pregao}: {e}")
        return []


def _bec_filtrar_itens(itens: list, termo: str, max_resultados: int = 30) -> list:
    """Filtra itens BEC por all-words match no DescItem."""
    import unicodedata

    def _sem_acento(txt):
        return unicodedata.normalize('NFKD', txt).encode('ascii', 'ignore').decode('ascii')

    termo_norm = _sem_acento(termo.lower())
    palavras = [p for p in termo_norm.split() if len(p) > 2]
    if not palavras:
        return []

    resultados = []
    for item in itens:
        desc = _sem_acento((item.get('DescItem', '') or '').lower())
        if all(p in desc for p in palavras):
            resultados.append(item)
            if len(resultados) >= max_resultados:
                break

    print(f"[BEC] Filtro '{termo}': {len(resultados)}/{len(itens)} itens casaram")
    return resultados


def _bec_buscar_detalhe_item(codigo: int, tipo_origem: str = None) -> list:
    """Busca detalhes (OCs) de um item BEC. Retorna lista de OCs."""
    tipos = [tipo_origem] if tipo_origem else ['pregaoM', 'pregaoS', 'pregaoRP']
    for tipo in tipos:
        url = f"{BEC_API_BASE_URL}/{tipo}/NegociacaoItemOC/{codigo}"
        try:
            resp = requests.get(url, timeout=15, headers={"Accept": "application/json"})
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list) and len(data) > 0:
                    for d in data:
                        d['_tipo_pregao'] = tipo
                    return data
                elif data and isinstance(data, dict) and data.get('OC'):
                    data['_tipo_pregao'] = tipo
                    return [data]
        except Exception:
            continue
    return []


def tool_buscar_editais_bec(termo: str, user_id: str,
                            incluir_encerrados: bool = False,
                            dias_busca: int = 90) -> Dict[str, Any]:
    """
    Busca editais na BEC-SP via API direta.
    1. Baixa listas de itens (cache 24h) dos 3 tipos de pregão
    2. Filtra por all-words match
    3. Busca detalhe (OC/edital) em paralelo
    4. Agrupa por OC para não duplicar
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from datetime import timedelta

    print(f"[BEC-API] Buscando '{termo}' na BEC-SP API...")
    editais_encontrados = []
    ocs_vistas = set()

    # PASSO 1: Carregar itens das 3 listas (com cache)
    todos_itens = []
    for tipo in ['pregaoM', 'pregaoS', 'pregaoRP']:
        itens = _bec_buscar_lista_itens(tipo)
        for item in itens:
            item['_tipo_pregao'] = tipo
        todos_itens.extend(itens)

    print(f"[BEC-API] Total de itens carregados (3 listas): {len(todos_itens)}")

    # PASSO 2: Filtrar por termo
    itens_casados = _bec_filtrar_itens(todos_itens, termo, max_resultados=30)

    if not itens_casados:
        print(f"[BEC-API] Nenhum item casou com '{termo}'")
        return {
            "success": True,
            "fonte": "BEC-SP (API)",
            "termo": termo,
            "editais": [],
            "total": 0,
            "mensagem": f"Nenhum item encontrado na BEC-SP para '{termo}'"
        }

    # PASSO 3: Buscar detalhes em paralelo
    def _buscar_detalhe(item):
        codigo = item.get('Codigo')
        tipo = item.get('_tipo_pregao')
        if not codigo:
            return []
        return _bec_buscar_detalhe_item(codigo, tipo_origem=tipo)

    todos_detalhes = []
    max_w = min(len(itens_casados), 10)
    print(f"[BEC-API] Buscando detalhes de {len(itens_casados)} itens ({max_w} workers)...")

    with ThreadPoolExecutor(max_workers=max_w) as executor:
        futures = {executor.submit(_buscar_detalhe, item): item for item in itens_casados}
        for future in as_completed(futures, timeout=60):
            try:
                detalhes = future.result(timeout=15)
                item_orig = futures[future]
                for det in detalhes:
                    det['_item_original'] = item_orig
                todos_detalhes.extend(detalhes)
            except Exception:
                pass

    print(f"[BEC-API] Obtidos {len(todos_detalhes)} detalhes de OC")

    # PASSO 4: Agrupar por OC e normalizar
    hoje = datetime.now()
    for det in todos_detalhes:
        oc = det.get('OC', '')
        if not oc or oc in ocs_vistas:
            continue
        ocs_vistas.add(oc)

        # Verificar encerramento
        dt_enc_str = det.get('DT_ENCERRAMENTO')
        encerrado = False
        data_encerramento = None
        if dt_enc_str:
            for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y'):
                try:
                    dt_enc = datetime.strptime(str(dt_enc_str)[:19], fmt)
                    data_encerramento = dt_enc.isoformat()
                    if dt_enc < hoje:
                        encerrado = True
                    break
                except ValueError:
                    continue

        situacao = (det.get('SITUACAO', '') or '').upper()
        # Normalizar acentos para comparação (ex: HOMOLOGAÇÃO → HOMOLOGACAO)
        import unicodedata as _ud
        situacao_norm = ''.join(c for c in _ud.normalize('NFD', situacao) if _ud.category(c) != 'Mn')
        if any(s in situacao_norm for s in ('ENCERRAD', 'HOMOLOGA', 'REVOGAD', 'ANULAD', 'FRACASSAD', 'DESERT')):
            encerrado = True

        if encerrado and not incluir_encerrados:
            continue

        # Mapear modalidade
        procedimento = (det.get('PROCEDIMENTO', '') or '').lower()
        if 'eletrônico' in procedimento or 'eletronico' in procedimento:
            modalidade = 'pregao_eletronico'
        elif 'presencial' in procedimento:
            modalidade = 'pregao_presencial'
        elif 'dispensa' in procedimento:
            modalidade = 'dispensa'
        else:
            modalidade = 'pregao_eletronico'

        item_orig = det.get('_item_original', {})
        link_edital = det.get('LINK_EDITAL') or ''
        if not link_edital:
            link_edital = f"https://www.bec.sp.gov.br/bec_pregao_ui/Edital/{oc}"

        edital_data = {
            "numero": oc,
            "orgao": det.get('UNIDADE_COMPRADORA', 'BEC-SP'),
            "orgao_tipo": "estadual",
            "uf": "SP",
            "cidade": "",
            "objeto": item_orig.get('DescItem', f"Pregão BEC - {termo}"),
            "modalidade": modalidade,
            "valor_referencia": None,
            "data_publicacao": None,
            "data_abertura": None,
            "data_encerramento": data_encerramento,
            "url": link_edital,
            "situacao": det.get('SITUACAO'),
            "fonte": "BEC-SP (API)",
            "fonte_tipo": "api",
            "encerrado": encerrado,
        }
        editais_encontrados.append(edital_data)

    # PASSO 5: Encerrados por período (se incluir_encerrados)
    if incluir_encerrados and dias_busca > 0:
        try:
            data_fim = datetime.now()
            data_ini = data_fim - timedelta(days=dias_busca)
            url_enc = (f"{BEC_API_BASE_URL}/pregao_encerrado/OC_encerrada/"
                       f"{data_ini.strftime('%d%m%Y')}/{data_fim.strftime('%d%m%Y')}")
            print(f"[BEC-API] Buscando encerrados: {url_enc}")
            resp_enc = requests.get(url_enc, timeout=30, headers={"Accept": "application/json"})
            if resp_enc.status_code == 200:
                encerrados = resp_enc.json()
                if isinstance(encerrados, list):
                    import unicodedata
                    def _sem_acento(txt):
                        return unicodedata.normalize('NFKD', txt).encode('ascii', 'ignore').decode('ascii')
                    termo_norm = _sem_acento(termo.lower())
                    palavras = [p for p in termo_norm.split() if len(p) > 2]
                    for enc in encerrados:
                        oc = enc.get('OC', '')
                        if not oc or oc in ocs_vistas:
                            continue
                        # Encerrados não têm DescItem, então verificar unidade compradora
                        uc = _sem_acento((enc.get('UNIDADE_COMPRADORA', '') or '').lower())
                        if palavras and not any(p in uc for p in palavras):
                            continue
                        ocs_vistas.add(oc)
                        dt_enc_str = enc.get('DT_ENCERRAMENTO', '')
                        editais_encontrados.append({
                            "numero": oc,
                            "orgao": enc.get('UNIDADE_COMPRADORA', 'BEC-SP'),
                            "orgao_tipo": "estadual",
                            "uf": "SP",
                            "objeto": f"Pregão BEC encerrado - {termo}",
                            "modalidade": "pregao_eletronico",
                            "valor_referencia": None,
                            "data_encerramento": dt_enc_str,
                            "url": enc.get('LINK_EDITAL') or '',
                            "situacao": enc.get('SITUACAO', 'ENCERRADO'),
                            "fonte": "BEC-SP (API)",
                            "fonte_tipo": "api",
                            "encerrado": True,
                        })
                    print(f"[BEC-API] Encerrados adicionados: {len([e for e in editais_encontrados if e.get('encerrado')])} no total")
        except Exception as e:
            print(f"[BEC-API] Erro ao buscar encerrados: {e}")

    print(f"[BEC-API] Total editais BEC: {len(editais_encontrados)}")
    return {
        "success": True,
        "fonte": "BEC-SP (API)",
        "termo": termo,
        "editais": editais_encontrados,
        "total": len(editais_encontrados)
    }


# ==================== COMPRASNET API (Portal de Compras Gov Federal) ====================

def tool_buscar_editais_comprasnet(termo: str, user_id: str,
                                   incluir_encerrados: bool = False,
                                   dias_busca: int = 90) -> Dict[str, Any]:
    """
    Busca editais no ComprasNet (dados.gov.br). DEFENSIVO: API frequentemente indisponível (503).
    Se API falhar, retorna api_disponivel=False para fallback no scraper.
    """
    from datetime import timedelta

    print(f"[COMPRASNET-API] Buscando '{termo}' no ComprasNet API...")

    hoje = datetime.now()
    data_ate = hoje.strftime('%d/%m/%Y')
    data_de = (hoje - timedelta(days=dias_busca)).strftime('%d/%m/%Y')

    try:
        params = {
            "data_abertura_de": data_de,
            "data_abertura_ate": data_ate,
            "tam_pagina": 50,
        }
        resp = requests.get(COMPRASNET_API_URL, params=params, timeout=COMPRASNET_TIMEOUT,
                            headers={"Accept": "application/json"})

        if resp.status_code == 503:
            print(f"[COMPRASNET-API] Serviço indisponível (503)")
            return {
                "success": True, "fonte": "ComprasNet (API)", "termo": termo,
                "editais": [], "total": 0, "api_disponivel": False,
                "mensagem": "API do ComprasNet indisponível (503). Usando scraper como fallback."
            }

        if resp.status_code != 200:
            print(f"[COMPRASNET-API] Erro HTTP {resp.status_code}")
            return {
                "success": True, "fonte": "ComprasNet (API)", "termo": termo,
                "editais": [], "total": 0, "api_disponivel": False,
                "mensagem": f"API do ComprasNet retornou erro {resp.status_code}"
            }

        data = resp.json()
        licitacoes = data.get('_embedded', {}).get('licitacoes', [])

        # Filtrar por termo
        import unicodedata
        def _sem_acento(txt):
            return unicodedata.normalize('NFKD', txt).encode('ascii', 'ignore').decode('ascii')

        termo_norm = _sem_acento(termo.lower())
        palavras = [p for p in termo_norm.split() if len(p) > 2]

        editais = []
        for lic in licitacoes:
            objeto = (lic.get('objeto', '') or '')
            texto = _sem_acento(objeto.lower())
            if palavras and not all(p in texto for p in palavras):
                continue

            encerrado = False
            data_ab_str = lic.get('data_abertura_proposta', '')
            if data_ab_str:
                try:
                    dt_ab = datetime.fromisoformat(str(data_ab_str).replace('Z', '')[:19])
                    if dt_ab < hoje:
                        encerrado = True
                except (ValueError, TypeError):
                    pass

            if encerrado and not incluir_encerrados:
                continue

            modalidade_raw = (lic.get('modalidade_licitacao', '') or '').lower()
            if 'pregão' in modalidade_raw or 'pregao' in modalidade_raw:
                modalidade = 'pregao_eletronico'
            elif 'concorrência' in modalidade_raw or 'concorrencia' in modalidade_raw:
                modalidade = 'concorrencia'
            elif 'dispensa' in modalidade_raw:
                modalidade = 'dispensa'
            else:
                modalidade = 'pregao_eletronico'

            numero = lic.get('numero_aviso', lic.get('numero', ''))
            uasg = lic.get('uasg', {})
            if isinstance(uasg, str):
                uasg = {}

            edital_data = {
                "numero": str(numero),
                "orgao": uasg.get('nome', 'ComprasNet'),
                "orgao_tipo": "federal",
                "uf": uasg.get('uf', ''),
                "cidade": uasg.get('municipio', ''),
                "objeto": objeto[:500],
                "modalidade": modalidade,
                "valor_referencia": lic.get('valor_estimado'),
                "data_publicacao": lic.get('data_publicacao'),
                "data_abertura": lic.get('data_abertura_proposta'),
                "data_encerramento": lic.get('data_entrega_proposta'),
                "url": lic.get('_links', {}).get('self', {}).get('href', ''),
                "fonte": "ComprasNet (API)",
                "fonte_tipo": "api",
                "encerrado": encerrado,
            }
            editais.append(edital_data)

        print(f"[COMPRASNET-API] Encontrados {len(editais)} editais")
        return {
            "success": True, "fonte": "ComprasNet (API)", "termo": termo,
            "editais": editais, "total": len(editais), "api_disponivel": True,
        }

    except requests.exceptions.Timeout:
        print(f"[COMPRASNET-API] Timeout ({COMPRASNET_TIMEOUT}s)")
        return {
            "success": True, "fonte": "ComprasNet (API)", "termo": termo,
            "editais": [], "total": 0, "api_disponivel": False,
            "mensagem": f"API do ComprasNet não respondeu (timeout {COMPRASNET_TIMEOUT}s)"
        }
    except requests.exceptions.ConnectionError:
        print(f"[COMPRASNET-API] Erro de conexão")
        return {
            "success": True, "fonte": "ComprasNet (API)", "termo": termo,
            "editais": [], "total": 0, "api_disponivel": False,
            "mensagem": "API do ComprasNet inacessível"
        }
    except Exception as e:
        print(f"[COMPRASNET-API] Erro inesperado: {e}")
        return {
            "success": True, "fonte": "ComprasNet (API)", "termo": termo,
            "editais": [], "total": 0, "api_disponivel": False,
            "mensagem": f"Erro: {e}"
        }


def tool_extrair_requisitos(edital_id: str, texto: str, user_id: str, empresa_id: str = None) -> Dict[str, Any]:
    """
    Extrai requisitos de um texto de edital e salva no banco.
    """
    db = get_db()
    try:
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()

        if not edital:
            return {"success": False, "error": "Edital não encontrado"}

        # Classificar edital
        prompt_class = PROMPT_CLASSIFICAR_EDITAL.format(objeto=edital.objeto)
        categoria = call_deepseek([{"role": "user", "content": prompt_class}], max_tokens=50)
        categoria = categoria.strip().lower()
        if categoria in ['comodato', 'venda_equipamento', 'aluguel_com_consumo',
                         'aluguel_sem_consumo', 'consumo_reagentes', 'consumo_insumos', 'servicos']:
            edital.categoria = categoria

        # Carregar tipos de documento do banco para o prompt
        from models import DocumentoNecessario, CategoriaDocumento
        docs_nec = db.query(DocumentoNecessario).filter(DocumentoNecessario.ativo == True).order_by(DocumentoNecessario.ordem).all()

        # Agrupar por categoria para injetar no prompt
        categorias_docs = {}
        for dn in docs_nec:
            cat_nome = dn.categoria_rel.nome if dn.categoria_rel else "Outros"
            categorias_docs.setdefault(cat_nome, []).append(f"{dn.tipo_chave} ({dn.nome})")

        lista_tipos_str = ""
        for cat_nome, tipos in categorias_docs.items():
            lista_tipos_str += f"\n{cat_nome}:\n"
            for t in tipos:
                lista_tipos_str += f"  {t}\n"

        # Montar prompt com tipos dinâmicos
        prompt_dinamico = f"""Você é um especialista em análise de editais de licitação.

Analise o texto do edital abaixo e extraia TODOS os requisitos técnicos, documentais e comerciais.

Para cada requisito, retorne um objeto JSON com:
- tipo: "tecnico", "documental" ou "comercial"
- descricao: descrição completa do requisito
- nome_especificacao: para tipo "documental", use o código (tipo_chave) da lista abaixo que melhor corresponde. Para tipo "tecnico", nome da especificação.
- valor_exigido: para tipo "documental", use a subcategoria: "documento", "certidao" ou "tecnico". Para outros tipos, o valor exigido.
- operador: operador se houver ("<", "<=", "=", ">=", ">")
- valor_numerico: valor numérico extraído
- obrigatorio: true se for obrigatório, false se for desejável

CÓDIGOS DE DOCUMENTOS DISPONÍVEIS (use o tipo_chave como nome_especificacao):
{lista_tipos_str}
Se o edital exigir um documento que não se encaixa em nenhum código acima, use nome_especificacao="outro".

IMPORTANTE: Identifique também documentos de habilitação IMPLÍCITOS que todo pregão eletrônico exige (contrato social, certidões fiscais, atestados técnicos, etc.), mesmo que o edital diga apenas "conforme SICAF" ou "habilitação conforme Lei 14.133/2021". Esses documentos são obrigatórios por lei.

Retorne APENAS um array JSON válido, sem texto adicional.

TEXTO DO EDITAL:
{texto[:15000]}

REQUISITOS EXTRAÍDOS (JSON):
"""
        resposta = call_deepseek([{"role": "user", "content": prompt_dinamico}], max_tokens=8000)

        requisitos_salvos = []
        try:
            requisitos = _extrair_json_array(resposta)
            if requisitos:
                for req in requisitos:
                    req_obj = EditalRequisito(
                        edital_id=edital_id,
                        tipo=req.get('tipo', 'tecnico'),
                        descricao=req.get('descricao', 'N/A'),
                        nome_especificacao=req.get('nome_especificacao'),
                        valor_exigido=req.get('valor_exigido'),
                        operador=req.get('operador'),
                        valor_numerico=req.get('valor_numerico'),
                        obrigatorio=req.get('obrigatorio', True)
                    )
                    db.add(req_obj)
                    requisitos_salvos.append(req)
                db.commit()
        except json.JSONDecodeError:
            pass

        return {
            "success": True,
            "edital_id": edital_id,
            "categoria": edital.categoria,
            "requisitos_extraidos": len(requisitos_salvos)
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_listar_editais(user_id: str, empresa_id: str = None, status: str = None,
                        uf: str = None, categoria: str = None) -> Dict[str, Any]:
    """
    Lista editais salvos do usuário com filtros opcionais.
    """
    db = get_db()
    try:
        query = db.query(Edital).filter(Edital.empresa_id == empresa_id)

        if status:
            query = query.filter(Edital.status == status)
        if uf:
            query = query.filter(Edital.uf == uf.upper())
        if categoria:
            query = query.filter(Edital.categoria == categoria)

        editais = query.order_by(Edital.created_at.desc()).limit(50).all()

        return {
            "success": True,
            "editais": [e.to_dict() for e in editais],
            "total": len(editais)
        }
    finally:
        db.close()


def tool_listar_produtos(user_id: str, empresa_id: str = None, categoria: str = None,
                         nome: str = None) -> Dict[str, Any]:
    """
    Lista produtos do usuário com filtros opcionais.
    """
    db = get_db()
    try:
        query = db.query(Produto).filter(Produto.empresa_id == empresa_id)

        if categoria:
            query = query.filter(Produto.categoria == categoria)
        if nome:
            query = query.filter(Produto.nome.ilike(f"%{nome}%"))

        produtos = query.order_by(Produto.created_at.desc()).all()

        return {
            "success": True,
            "produtos": [p.to_dict(include_specs=True) for p in produtos],
            "total": len(produtos)
        }
    finally:
        db.close()


def _get_pesos_score(db, user_id: str, empresa_id: str = None) -> Dict[str, float]:
    """
    Lê pesos da tabela parametros_score para o user_id.
    Retorna defaults se não houver configuração cadastrada.
    """
    params = db.query(ParametroScore).filter(ParametroScore.empresa_id == empresa_id).first()
    if params:
        return {
            "peso_tecnico": float(params.peso_tecnico) if params.peso_tecnico else 0.40,
            "peso_comercial": float(params.peso_comercial) if params.peso_comercial else 0.25,
            "peso_participacao": float(params.peso_participacao) if params.peso_participacao else 0.20,
            "peso_ganho": float(params.peso_ganho) if params.peso_ganho else 0.15,
            "limiar_go": float(params.limiar_go) if params.limiar_go else 70.0,
            "limiar_nogo": float(params.limiar_nogo) if params.limiar_nogo else 40.0,
        }
    return {
        "peso_tecnico": 0.40,
        "peso_comercial": 0.25,
        "peso_participacao": 0.20,
        "peso_ganho": 0.15,
        "limiar_go": 70.0,
        "limiar_nogo": 40.0,
    }


def tool_calcular_aderencia(produto_id: str, edital_id: str, user_id: str, empresa_id: str = None) -> Dict[str, Any]:
    """
    Calcula a aderência de um produto a um edital.
    Compara especificações do produto com requisitos do edital.
    """
    db = get_db()
    try:
        # Carregar pesos configurados pelo usuário (ou defaults)
        pesos = _get_pesos_score(db, user_id, empresa_id)
        limiar_go = pesos["limiar_go"]
        limiar_nogo = pesos["limiar_nogo"]

        # Buscar produto e edital
        produto = db.query(Produto).filter(
            Produto.id == produto_id,
            Produto.empresa_id == empresa_id
        ).first()

        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()

        if not produto:
            return {"success": False, "error": "Produto não encontrado"}
        if not edital:
            return {"success": False, "error": "Edital não encontrado"}

        # Buscar specs e requisitos
        specs = db.query(ProdutoEspecificacao).filter(
            ProdutoEspecificacao.produto_id == produto_id
        ).all()

        requisitos = db.query(EditalRequisito).filter(
            EditalRequisito.edital_id == edital_id
        ).all()

        # Se não tem requisitos cadastrados, calcular aderência via IA
        if not requisitos:
            # Buscar itens do edital
            itens = db.query(EditalItem).filter(
                EditalItem.edital_id == edital_id
            ).all()

            # Montar contexto do edital
            contexto_edital = f"""
EDITAL: {edital.numero}
ÓRGÃO: {edital.orgao}
OBJETO: {edital.objeto}
MODALIDADE: {edital.modalidade}
"""
            if itens:
                contexto_edital += "\nITENS DO EDITAL:\n"
                for item in itens:
                    contexto_edital += f"- Item {item.numero_item}: {item.descricao}\n"

            # Montar contexto do produto
            contexto_produto = f"""
PRODUTO: {produto.nome}
FABRICANTE: {produto.fabricante or 'N/I'}
MODELO: {produto.modelo or 'N/I'}
CATEGORIA: {produto.categoria or 'N/I'}
DESCRIÇÃO: {produto.descricao or 'N/I'}
"""
            if specs:
                contexto_produto += "\nESPECIFICAÇÕES TÉCNICAS:\n"
                for spec in specs[:20]:  # Limitar a 20 specs
                    contexto_produto += f"- {spec.nome_especificacao}: {spec.valor}\n"

            # Usar IA para calcular aderência
            prompt = f"""Analise a aderência do produto ao edital.

{contexto_edital}

{contexto_produto}

INSTRUÇÕES:
1. Compare o produto com o objeto e itens do edital
2. Determine se o produto é compatível com o que o edital solicita
3. Retorne um JSON com:
   - score: número de 0 a 100 (0 = totalmente incompatível, 100 = perfeita aderência)
   - recomendacao: "RECOMENDADO", "AVALIAR" ou "NAO_RECOMENDADO"
   - justificativa: breve explicação (max 200 caracteres)
   - compativel: true/false

Retorne APENAS o JSON, sem texto adicional.

Exemplo:
{{"score": 15, "recomendacao": "NAO_RECOMENDADO", "justificativa": "Produto é equipamento médico, edital é para material hidráulico", "compativel": false}}
"""
            try:
                resposta = call_deepseek([{"role": "user", "content": prompt}], max_tokens=500)
                # Extrair JSON da resposta
                import json
                # Limpar resposta
                resposta_limpa = resposta.strip()
                if resposta_limpa.startswith("```"):
                    resposta_limpa = resposta_limpa.split("```")[1]
                    if resposta_limpa.startswith("json"):
                        resposta_limpa = resposta_limpa[4:]
                resposta_limpa = resposta_limpa.strip()

                resultado_ia = json.loads(resposta_limpa)

                score_bruto = resultado_ia.get("score", 0)
                # Aplicar peso_tecnico ao score bruto da IA
                score = round(score_bruto * pesos["peso_tecnico"] / 0.40, 2)
                # Usar limiares configurados para recomendar
                if score >= limiar_go:
                    recomendacao = "RECOMENDADO"
                elif score >= limiar_nogo:
                    recomendacao = "AVALIAR"
                else:
                    recomendacao = "NAO_RECOMENDADO"
                justificativa = resultado_ia.get("justificativa", "Análise via IA")

                return {
                    "success": True,
                    "produto": produto.nome,
                    "edital": edital.numero,
                    "score_tecnico": score,
                    "recomendacao": recomendacao,
                    "justificativa": justificativa,
                    "metodo": "ia_sem_requisitos",
                    "requisitos_total": 0,
                    "requisitos_atendidos": 0,
                    "requisitos_parciais": 0,
                    "requisitos_nao_atendidos": 0
                }
            except Exception as e:
                print(f"[ADERENCIA] Erro na análise via IA: {e}")
                return {
                    "success": True,
                    "produto": produto.nome,
                    "edital": edital.numero,
                    "score_tecnico": 0,
                    "recomendacao": "AVALIAR",
                    "justificativa": f"Não foi possível calcular (edital sem requisitos). Erro: {str(e)[:50]}",
                    "metodo": "erro_ia",
                    "requisitos_total": 0,
                    "requisitos_atendidos": 0,
                    "requisitos_parciais": 0,
                    "requisitos_nao_atendidos": 0
                }

        # Criar análise
        analise = Analise(
            edital_id=edital_id,
            produto_id=produto_id,
            user_id=user_id,
            requisitos_total=len(requisitos)
        )
        db.add(analise)
        db.flush()

        # Analisar cada requisito
        atendidos = 0
        parciais = 0
        nao_atendidos = 0
        detalhes = []

        specs_dict = {s.nome_especificacao.lower(): s for s in specs}

        for req in requisitos:
            status = 'nao_atendido'
            valor_produto = None
            justificativa = "Especificação não encontrada no produto"
            spec_encontrada = None

            # Tentar encontrar spec correspondente
            if req.nome_especificacao:
                nome_lower = req.nome_especificacao.lower()
                # Busca exata
                if nome_lower in specs_dict:
                    spec_encontrada = specs_dict[nome_lower]
                else:
                    # Busca parcial
                    for nome, spec in specs_dict.items():
                        if nome_lower in nome or nome in nome_lower:
                            spec_encontrada = spec
                            break

            if spec_encontrada:
                valor_produto = spec_encontrada.valor

                # Comparar valores
                if req.valor_numerico and spec_encontrada.valor_numerico:
                    req_val = float(req.valor_numerico)
                    prod_val = float(spec_encontrada.valor_numerico)

                    if req.operador == '<=':
                        if prod_val <= req_val:
                            status = 'atendido'
                            justificativa = f"Produto ({prod_val}) ≤ Exigido ({req_val})"
                        else:
                            status = 'nao_atendido'
                            justificativa = f"Produto ({prod_val}) > Exigido ({req_val})"
                    elif req.operador == '>=':
                        if prod_val >= req_val:
                            status = 'atendido'
                            justificativa = f"Produto ({prod_val}) ≥ Exigido ({req_val})"
                        else:
                            status = 'nao_atendido'
                            justificativa = f"Produto ({prod_val}) < Exigido ({req_val})"
                    elif req.operador == '=':
                        if abs(prod_val - req_val) < 0.001:
                            status = 'atendido'
                            justificativa = f"Produto ({prod_val}) = Exigido ({req_val})"
                        else:
                            status = 'parcial'
                            justificativa = f"Produto ({prod_val}) ≠ Exigido ({req_val})"
                    else:
                        # Sem operador específico, considerar parcial
                        status = 'parcial'
                        justificativa = f"Especificação encontrada: {valor_produto}"
                else:
                    # Não numérico, considerar atendido se encontrou
                    status = 'atendido'
                    justificativa = f"Especificação encontrada: {valor_produto}"

            # Contar
            if status == 'atendido':
                atendidos += 1
            elif status == 'parcial':
                parciais += 1
            else:
                nao_atendidos += 1

            # Salvar detalhe
            detalhe = AnaliseDetalhe(
                analise_id=analise.id,
                requisito_id=req.id,
                especificacao_id=spec_encontrada.id if spec_encontrada else None,
                status=status,
                valor_exigido=req.valor_exigido,
                valor_produto=valor_produto,
                justificativa=justificativa
            )
            db.add(detalhe)
            detalhes.append({
                "requisito": req.descricao[:100],
                "status": status,
                "justificativa": justificativa
            })

        # Calcular scores usando peso_tecnico dos parâmetros configurados
        total = len(requisitos)
        score_tecnico = ((atendidos + parciais * 0.5) / total) * 100 if total > 0 else 0
        # Score final ponderado pelo peso técnico configurado
        score_final = round(score_tecnico * pesos["peso_tecnico"] / 0.40, 2)

        analise.requisitos_atendidos = atendidos
        analise.requisitos_parciais = parciais
        analise.requisitos_nao_atendidos = nao_atendidos
        analise.score_tecnico = Decimal(str(round(score_tecnico, 2)))
        analise.score_final = Decimal(str(score_final))

        # Gerar recomendação usando limiares configurados
        if score_tecnico >= limiar_go:
            analise.recomendacao = "RECOMENDADO participar. Alta aderência técnica."
        elif score_tecnico >= limiar_nogo:
            analise.recomendacao = "AVALIAR participação. Aderência média, verificar requisitos não atendidos."
        else:
            analise.recomendacao = "NÃO RECOMENDADO. Baixa aderência técnica."

        edital.status = 'analisando'
        db.commit()

        return {
            "success": True,
            "analise_id": analise.id,
            "produto": produto.nome,
            "edital": edital.numero,
            "score_tecnico": float(analise.score_tecnico),
            "requisitos_total": total,
            "requisitos_atendidos": atendidos,
            "requisitos_parciais": parciais,
            "requisitos_nao_atendidos": nao_atendidos,
            "recomendacao": analise.recomendacao,
            "detalhes": detalhes[:10]  # Primeiros 10
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_gerar_proposta(edital_id: str, produto_id: str, user_id: str, empresa_id: str = None,
                        preco: float = None, lote_id: str = None,
                        template_id: str = None) -> Dict[str, Any]:
    """
    Gera uma proposta técnica para um edital.
    Se lote_id fornecido, busca dados de precificação (PrecoCamada) do vínculo item-produto.
    Se template_id fornecido, usa o template como base para a estrutura da proposta.
    """
    db = get_db()
    try:
        # Buscar dados
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()

        produto = db.query(Produto).filter(
            Produto.id == produto_id,
            Produto.empresa_id == empresa_id
        ).first()

        if not edital:
            return {"success": False, "error": "Edital não encontrado"}
        if not produto:
            return {"success": False, "error": "Produto não encontrado"}

        # Buscar análise existente
        analise = db.query(Analise).filter(
            Analise.edital_id == edital_id,
            Analise.produto_id == produto_id
        ).first()

        # Buscar specs do produto
        specs = db.query(ProdutoEspecificacao).filter(
            ProdutoEspecificacao.produto_id == produto_id
        ).all()
        specs_texto = "\n".join([f"- {s.nome_especificacao}: {s.valor}" for s in specs])

        # Buscar requisitos do edital
        requisitos = db.query(EditalRequisito).filter(
            EditalRequisito.edital_id == edital_id
        ).all()
        requisitos_texto = ""
        if requisitos:
            requisitos_texto = "\n".join([
                f"- {r.descricao} (Tipo: {r.tipo}, Obrigatório: {'Sim' if r.obrigatorio else 'Não'})"
                for r in requisitos
            ])
        else:
            requisitos_texto = "Requisitos específicos não cadastrados para este edital."

        # Buscar análise de aderência se existir
        analise_texto = ""
        if analise:
            detalhes = db.query(AnaliseDetalhe).filter(
                AnaliseDetalhe.analise_id == analise.id
            ).all()
            if detalhes:
                analise_texto = "\n\nANÁLISE DE ADERÊNCIA:\n" + "\n".join([
                    f"- {d.justificativa} ({d.status})" for d in detalhes
                ])

        # Combinar requisitos e análise
        requisitos_e_analise = requisitos_texto + analise_texto

        # FASE 2: Buscar dados de precificação se lote_id fornecido
        preco_camada_texto = ""
        if lote_id:
            # Buscar vínculos item-produto do lote para este produto
            from sqlalchemy import and_
            vinculos = (
                db.query(EditalItemProduto)
                .join(LoteItem, LoteItem.edital_item_id == EditalItemProduto.edital_item_id)
                .filter(
                    LoteItem.lote_id == lote_id,
                    EditalItemProduto.produto_id == produto_id,
                    EditalItemProduto.empresa_id == empresa_id
                ).all()
            )
            for vinculo in vinculos:
                camada = db.query(PrecoCamada).filter(
                    PrecoCamada.edital_item_produto_id == vinculo.id,
                    PrecoCamada.empresa_id == empresa_id
                ).first()
                if camada:
                    custo = float(camada.custo_base_final) if camada.custo_base_final else None
                    preco_base = float(camada.preco_base) if camada.preco_base else None
                    lance_ini = float(camada.lance_inicial) if camada.lance_inicial else None
                    preco_camada_texto += f"\n\nDADOS DE PRECIFICAÇÃO:"
                    if custo:
                        preco_camada_texto += f"\n- Custo base (Camada A): R$ {custo:,.4f}"
                    if preco_base:
                        preco_camada_texto += f"\n- Preço base (Camada B): R$ {preco_base:,.4f}"
                    if lance_ini:
                        preco_camada_texto += f"\n- Lance inicial (Camada D): R$ {lance_ini:,.4f}"
                    if camada.markup_percentual:
                        preco_camada_texto += f"\n- Markup: {float(camada.markup_percentual):.2f}%"
                    # Usar lance_inicial como preço se não definido
                    if not preco and lance_ini:
                        preco = lance_ini

        # Formatar preço
        preco_formatado = f"{preco:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if preco else "A definir"

        # Buscar template se fornecido
        template_instrucao = ""
        if template_id:
            template = db.query(PropostaTemplate).filter(
                PropostaTemplate.id == template_id,
                PropostaTemplate.ativo == True
            ).first()
            if template and template.conteudo_md:
                template_instrucao = f"\n\nIMPORTANTE — USE O SEGUINTE TEMPLATE COMO BASE PARA A ESTRUTURA DA PROPOSTA:\n\n{template.conteudo_md}\n\nAdapte o template acima com os dados reais do edital e produto. Mantenha a estrutura e seções do template.\n"

        # Gerar proposta com IA
        prompt = PROMPT_GERAR_PROPOSTA.format(
            numero_edital=edital.numero or "S/N",
            orgao=edital.orgao or "Não informado",
            objeto=edital.objeto or "Não informado",
            nome_produto=produto.nome or "Produto",
            fabricante=produto.fabricante or "N/A",
            modelo=produto.modelo or "N/A",
            especificacoes=specs_texto or "Especificações não cadastradas",
            analise_requisitos=requisitos_e_analise + preco_camada_texto,
            preco=preco_formatado
        )

        # Adicionar template ao prompt se disponível
        prompt_final = prompt + template_instrucao

        # Usar max_tokens maior para proposta completa
        texto_proposta = call_deepseek([{"role": "user", "content": prompt_final}], max_tokens=32000)

        # Salvar proposta
        proposta = Proposta(
            edital_id=edital_id,
            produto_id=produto_id,
            analise_id=analise.id if analise else None,
            user_id=user_id,
            texto_tecnico=texto_proposta,
            preco_unitario=Decimal(str(preco)) if preco else None,
            preco_total=Decimal(str(preco)) if preco else None,
            quantidade=1,
            status='rascunho',
            lote_id=lote_id,
        )
        db.add(proposta)
        db.commit()

        return {
            "success": True,
            "proposta_id": proposta.id,
            "edital": edital.numero,
            "produto": produto.nome,
            "texto_proposta": texto_proposta,
            "status": "rascunho",
            "lote_id": lote_id,
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# ==================== MAPEAMENTO DE TOOLS ====================

TOOLS_MAP = {
    "web_search": tool_web_search,
    "download_arquivo": tool_download_arquivo,
    "processar_upload": tool_processar_upload,
    "extrair_especificacoes": tool_extrair_especificacoes,
    "cadastrar_fonte": tool_cadastrar_fonte,
    "listar_fontes": tool_listar_fontes,
    "buscar_editais_fonte": tool_buscar_editais_fonte,
    "extrair_requisitos": tool_extrair_requisitos,
    "listar_editais": tool_listar_editais,
    "listar_produtos": tool_listar_produtos,
    "calcular_aderencia": tool_calcular_aderencia,
    "gerar_proposta": tool_gerar_proposta,
}


def execute_tool(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executa uma tool pelo nome.
    """
    if tool_name not in TOOLS_MAP:
        return {"success": False, "error": f"Tool '{tool_name}' não encontrada"}

    try:
        return TOOLS_MAP[tool_name](**params)
    except TypeError as e:
        return {"success": False, "error": f"Parâmetros inválidos: {e}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# NOVAS FUNÇÕES: Score de Aderência e Salvamento
# =============================================================================

# ── Pré-filtro por keywords (sem LLM) ────────────────────────────────────────

# ==================== METADADOS DE CAPTAÇÃO (CATMAT/TERMOS) ====================

def _buscar_catmat_produto(produto_id: str, db=None) -> Dict:
    """Busca códigos CATMAT/CATSER na API de dados abertos do governo.
    Estratégia em 2 passos:
      1. Buscar PDMs (tipos de produto) nos grupos relevantes, filtrar por nome
      2. Buscar itens do PDM encontrado
    """
    from difflib import SequenceMatcher

    CATMAT_BASE = "https://dadosabertos.compras.gov.br"
    # Grupos relevantes para saúde/laboratório
    GRUPOS_RELEVANTES = [
        64,  # Medicamentos, Drogas e Produtos Biológicos
        65,  # Equipamentos e Artigos para Uso Médico, Dentário e Veterinário
        66,  # Instrumentos e Equipamentos de Laboratório
    ]
    # Palavras genéricas que não devem ser usadas para matching (causam falsos positivos)
    STOP_WORDS_CATMAT = {
        "azul", "azuis", "branco", "branca", "preto", "preta", "verde", "vermelho",
        "amarelo", "rosa", "cinza", "para", "para", "tipo", "modelo", "manual",
        "descartável", "descartavel", "esteril", "estéril", "esterilizado",
        "esterilizada", "automático", "automatico", "digital", "elétrico",
        "eletrico", "horizontal", "vertical", "portátil", "portatil",
        "ultra", "mini", "micro", "maxi", "grande", "pequeno", "médio",
        "litros", "litro", "unidade", "caixa", "pacote", "frasco",
    }

    close_db = False
    if db is None:
        db = get_db()
        close_db = True

    try:
        produto = db.query(Produto).filter(Produto.id == produto_id).first()
        if not produto:
            return {"success": False, "error": "Produto não encontrado"}

        nome = produto.nome or ""
        palavras_nome = [w for w in nome.split() if len(w) > 3 and w.lower() not in STOP_WORDS_CATMAT]
        nome_lower = nome.lower()

        catmat_codigos = []
        catmat_descricoes = []
        catser_codigos = []

        # === PASSO 1: Buscar PDMs nos grupos relevantes, filtrar por nome ===
        pdms_match = []
        for grupo_id in GRUPOS_RELEVANTES:
            try:
                pdms = []
                pagina = 1
                while True:
                    resp = requests.get(
                        f"{CATMAT_BASE}/modulo-material/3_consultarPdmMaterial",
                        params={"codigoGrupo": grupo_id, "tamanhoPagina": 500, "pagina": pagina},
                        timeout=15
                    )
                    if resp.status_code != 200:
                        print(f"[CATMAT] Grupo {grupo_id} pag {pagina}: HTTP {resp.status_code}")
                        break
                    data = resp.json()
                    pagina_pdms = data.get("resultado", [])
                    pdms.extend(pagina_pdms)
                    # API SIASG nao garante ordem estavel: ler TODAS as paginas
                    # garante resultado deterministico (Grupo 66 tem 1155 PDMs em 3 paginas)
                    if data.get("paginasRestantes", 0) <= 0 or not pagina_pdms or pagina >= 10:
                        break
                    pagina += 1
                for pdm in pdms:
                    pdm_nome = (pdm.get("nomePdm") or "").lower()
                    if not pdm_nome:
                        continue
                    # Match: palavras significativas (>3 chars) do produto no nome do PDM
                    score = 0
                    matched_words = []
                    for p in palavras_nome:
                        if len(p) > 3 and p.lower() in pdm_nome:
                            score += 2  # Match de palavra é sinal forte
                            matched_words.append(p)
                    if pdm_nome in nome_lower or nome_lower in pdm_nome:
                        score += 3
                    # Similarity check (threshold alto para evitar falsos positivos)
                    ratio = SequenceMatcher(None, nome_lower, pdm_nome).ratio()
                    if ratio >= 0.55:
                        score += 1
                    if score > 0:
                        pdms_match.append((pdm, score, ratio))
                print(f"[CATMAT] Grupo {grupo_id}: {len(pdms)} PDMs, {len([x for x in pdms_match if x[0] in pdms])} matches")
            except Exception as e:
                print(f"[CATMAT] Erro grupo {grupo_id}: {e}")

        # Ordenar por melhor match e pegar top 3
        pdms_match.sort(key=lambda x: (x[1], x[2]), reverse=True)
        top_pdms = pdms_match[:3]

        # === PASSO 2: Buscar itens dos PDMs encontrados ===
        for pdm_info, pdm_score, _ in top_pdms:
            cod_pdm = pdm_info.get("codigoPdm")
            if not cod_pdm:
                continue
            try:
                resp = requests.get(
                    f"{CATMAT_BASE}/modulo-material/4_consultarItemMaterial",
                    params={"codigoPdm": cod_pdm, "tamanhoPagina": 50},
                    timeout=15
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                itens = data.get("resultado", [])
                for item in itens:
                    desc = item.get("descricaoItem", "")
                    codigo = str(item.get("codigoItem", ""))
                    if not desc or not codigo:
                        continue
                    # Filtrar por similaridade com nome do produto
                    desc_lower = desc.lower()
                    ratio = SequenceMatcher(None, nome_lower, desc_lower).ratio()
                    # Palavras significativas (>3 chars) do produto na descrição do item
                    palavras_match = sum(1 for p in palavras_nome[:5] if p.lower() in desc_lower and len(p) > 3)
                    # PDM com score forte (>=2): aceitar itens com 1+ palavra match
                    # PDM com score fraco: exigir ratio alta ou 2+ palavras
                    if pdm_score >= 2:
                        aceitar = ratio >= 0.30 or palavras_match >= 1
                    else:
                        aceitar = ratio >= 0.35 or palavras_match >= 2
                    if aceitar:
                        if codigo not in catmat_codigos:
                            catmat_codigos.append(codigo)
                            catmat_descricoes.append(desc)
                print(f"[CATMAT] PDM {cod_pdm} ({pdm_info.get('nomePdm')}): {len(itens)} itens, {len(catmat_codigos)} matches acum.")
            except Exception as e:
                print(f"[CATMAT] Erro PDM {cod_pdm}: {e}")

        # Limitar a top 5
        catmat_codigos = catmat_codigos[:5]
        catmat_descricoes = catmat_descricoes[:5]

        # === CATSER: Buscar Serviço se categoria sugere serviço ===
        categorias_servico = {"comodato", "aluguel"}
        if produto.categoria in categorias_servico or any(w in nome_lower for w in ["comodato", "locação", "aluguel", "serviço"]):
            try:
                resp = requests.get(
                    f"{CATMAT_BASE}/modulo-servico/6_consultarItemServico",
                    params={"tamanhoPagina": 50},
                    timeout=15
                )
                if resp.status_code == 200:
                    data = resp.json()
                    itens = data.get("resultado", [])
                    for item in itens:
                        desc = (item.get("descricaoItem") or "").lower()
                        codigo = str(item.get("codigoItem", ""))
                        if codigo and any(p.lower() in desc for p in palavras_nome[:2]):
                            if codigo not in catser_codigos:
                                catser_codigos.append(codigo)
            except Exception as e:
                print(f"[CATSER] Erro: {e}")

        catser_codigos = catser_codigos[:5]

        # Gravar no banco
        produto.catmat_codigos = catmat_codigos or []
        produto.catmat_descricoes = catmat_descricoes or []
        produto.catser_codigos = catser_codigos or []
        produto.catmat_updated_at = datetime.now()
        db.commit()

        print(f"[CATMAT] Produto '{produto.nome}': {len(catmat_codigos)} CATMAT, {len(catser_codigos)} CATSER")
        return {"success": True, "catmat": catmat_codigos, "catser": catser_codigos, "descricoes": catmat_descricoes}

    except Exception as e:
        print(f"[CATMAT] Erro geral: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        if close_db:
            db.close()


PROMPT_GERAR_TERMOS_BUSCA = """Você é um especialista em licitações públicas brasileiras.
Dado o produto abaixo, gere termos de busca para encontrar editais que demandem este produto.

Produto: {nome}
Categoria: {categoria}
Fabricante: {fabricante}
Modelo: {modelo}
Especificações: {specs_texto}
Códigos CATMAT: {catmat_codigos}
Descrições CATMAT: {catmat_descricoes}

Gere termos que cubram:
- Sinônimos e variações de nomenclatura
- Termos técnicos das especificações
- Termos que órgãos públicos usam para descrever este produto
- Abreviações e siglas comuns
- Termos relacionados que indicam necessidade

Retorne APENAS JSON: {{"termos": ["termo1", "termo2", ...]}}
Mínimo 8, máximo 25 termos. Sem repetições."""


def _gerar_termos_busca_produto(produto_id: str, db=None) -> Dict:
    """Gera termos de busca semânticos via IA para um produto."""
    close_db = False
    if db is None:
        db = get_db()
        close_db = True

    try:
        produto = db.query(Produto).filter(Produto.id == produto_id).first()
        if not produto:
            return {"success": False, "error": "Produto não encontrado"}

        # Carregar specs
        specs = db.query(ProdutoEspecificacao).filter(
            ProdutoEspecificacao.produto_id == produto.id
        ).limit(10).all()
        specs_texto = "; ".join([f"{s.nome_especificacao}: {s.valor}" for s in specs]) or "Não disponível"

        prompt = PROMPT_GERAR_TERMOS_BUSCA.format(
            nome=produto.nome or "",
            categoria=produto.categoria or "",
            fabricante=produto.fabricante or "N/A",
            modelo=produto.modelo or "N/A",
            specs_texto=specs_texto,
            catmat_codigos=json.dumps(produto.catmat_codigos or [], ensure_ascii=False),
            catmat_descricoes=json.dumps(produto.catmat_descricoes or [], ensure_ascii=False),
        )

        resposta = call_deepseek(
            [{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.3,
            model_override="deepseek-chat"
        )

        if not resposta:
            return {"success": False, "error": "Resposta vazia da IA"}

        # Parsear JSON
        json_match = re.search(r'\{[\s\S]*\}', resposta)
        if json_match:
            data = json.loads(json_match.group())
            termos = data.get("termos", [])
            if isinstance(termos, list):
                # Validar: apenas strings, sem duplicatas
                termos = list(dict.fromkeys([t for t in termos if isinstance(t, str) and len(t.strip()) > 1]))[:25]
                produto.termos_busca = termos
                produto.termos_busca_updated_at = datetime.now()
                db.commit()
                print(f"[TERMOS] Produto '{produto.nome}': {len(termos)} termos gerados")
                return {"success": True, "termos": termos}

        return {"success": False, "error": "IA não retornou JSON válido"}

    except Exception as e:
        print(f"[TERMOS] Erro: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        if close_db:
            db.close()


def processar_metadados_produto(produto_id: str):
    """Busca CATMAT + gera termos. Chamado após cadastro/update do produto."""
    db = get_db()
    try:
        print(f"[METADADOS] Processando metadados para produto {produto_id}...")
        _buscar_catmat_produto(produto_id, db)
        _gerar_termos_busca_produto(produto_id, db)
        print(f"[METADADOS] Concluído para produto {produto_id}")
    except Exception as e:
        print(f"[METADADOS] Erro: {e}")
    finally:
        db.close()


# ==================== PRE-FILTRO E SCORE RÁPIDO ====================

STOPWORDS_PT = {
    "de", "da", "do", "das", "dos", "em", "no", "na", "para", "por", "com",
    "sem", "como", "que", "uma", "um", "os", "as", "ou", "ao", "aos",
    "e", "a", "o", "se", "es", "le", "la", "lo", "el",
    "aquisicao", "contratacao", "servico", "servicos", "fornecimento",
    "pregao", "eletronico", "presencial", "licitacao", "registro", "precos",
    "empresa", "objeto", "lote", "item", "itens", "unidade", "valor",
}

CATEGORY_SYNONYMS = {
    "equipamento": {"equipamento", "equipamentos", "aparelho", "instrumento", "sistema", "maquina"},
    "reagente": {"reagente", "reagentes", "kit", "kits", "teste", "ensaio", "diagnostico"},
    "insumo_hospitalar": {"insumo", "insumos", "descartavel", "hospitalar", "material", "medico"},
    "insumo_laboratorial": {"laboratorial", "laboratorio", "vidraria", "pipeta", "tubo", "lamina"},
    "informatica": {"informatica", "computador", "notebook", "servidor", "software", "desktop", "computadores"},
    "redes": {"rede", "redes", "switch", "roteador", "cabeamento", "fibra"},
    "mobiliario": {"movel", "moveis", "mobiliario", "mesa", "cadeira", "armario"},
    "eletronico": {"eletronico", "monitor", "impressora", "projetor", "tela"},
    "medicamento": {"medicamento", "medicamentos", "farmaco", "remedio", "farmaceutico"},
    "alimento": {"alimento", "alimentos", "alimentacao", "refeicao", "genero", "generos"},
}


def _build_product_keyword_index(produtos_data, db):
    """Constrói índice de keywords dos produtos para pré-filtro rápido."""
    import unicodedata

    def _norm(txt):
        if not txt:
            return ""
        txt = unicodedata.normalize('NFKD', txt).encode('ascii', 'ignore').decode('ascii')
        return txt.lower().strip()

    categorias_expandidas = set()
    keywords = set()
    fabricantes = set()
    modelos = set()
    specs_keywords = set()

    for p in produtos_data:
        # Categoria → expandir com sinônimos
        cat = _norm(p.get("categoria", ""))
        if cat:
            categorias_expandidas.add(cat)
            for cat_key, synonyms in CATEGORY_SYNONYMS.items():
                if cat in synonyms or cat_key == cat or cat.startswith(cat_key):
                    categorias_expandidas.update(synonyms)
                    break

        # Nome → tokenizar
        nome = _norm(p.get("nome", ""))
        for word in nome.split():
            if len(word) > 2 and word not in STOPWORDS_PT:
                keywords.add(word)

        # Fabricante
        fab = _norm(p.get("fabricante", ""))
        if fab and len(fab) > 2:
            fabricantes.add(fab)

        # Modelo
        mod = _norm(p.get("modelo", ""))
        if mod and len(mod) > 2:
            modelos.add(mod)

        # Specs (já carregadas em produtos_data)
        for spec_name in p.get("specs", []):
            spec_norm = _norm(spec_name)
            for word in spec_norm.split():
                if len(word) > 2 and word not in STOPWORDS_PT:
                    specs_keywords.add(word)

        # Termos semânticos gerados pela IA (sinal forte)
        termos = p.get("termos_busca") or []
        for t in termos:
            t_norm = _norm(t)
            if len(t_norm) > 2:
                keywords.add(t_norm)

        # Descrições CATMAT (vocabulário governamental)
        catmat_descs = p.get("catmat_descricoes") or []
        for desc in catmat_descs:
            desc_norm = _norm(desc)
            for word in desc_norm.split():
                if len(word) > 3 and word not in STOPWORDS_PT:
                    keywords.add(word)

    print(f"[TOOLS] Keyword index: {len(keywords)} keywords, {len(categorias_expandidas)} cat-synonyms, "
          f"{len(fabricantes)} fabricantes, {len(modelos)} modelos, {len(specs_keywords)} spec-words")

    return {
        "categorias_expandidas": categorias_expandidas,
        "keywords": keywords,
        "fabricantes": fabricantes,
        "modelos": modelos,
        "specs_keywords": specs_keywords,
    }


def _pre_filter_editais(editais, keyword_index):
    """Pré-filtra editais por keywords, sem usar LLM. Conservador: na dúvida, mantém."""
    import unicodedata

    def _norm(txt):
        if not txt:
            return ""
        txt = unicodedata.normalize('NFKD', txt).encode('ascii', 'ignore').decode('ascii')
        return txt.lower().strip()

    relevant = []
    filtered = []

    cats = keyword_index["categorias_expandidas"]
    kws = keyword_index["keywords"]
    fabs = keyword_index["fabricantes"]
    mods = keyword_index["modelos"]
    specs = keyword_index["specs_keywords"]

    for edital in editais:
        objeto = _norm(edital.get("objeto", ""))
        if not objeto:
            # Sem objeto → manter (conservador)
            relevant.append(edital)
            continue

        # Check fabricante
        fab_match = any(f in objeto for f in fabs if len(f) > 3)

        # Check modelo
        mod_match = any(m in objeto for m in mods if len(m) > 3)

        # Check categoria (contar quantas casam)
        cat_matches = sum(1 for c in cats if c in objeto and len(c) > 3)
        cat_match = cat_matches > 0

        # Check keywords (contar quantas casam)
        kw_matches = sum(1 for k in kws if k in objeto and len(k) > 3)

        # Check specs
        spec_match = any(s in objeto for s in specs if len(s) > 3)

        # Regras de relevância (conservador — na dúvida, manter)
        is_relevant = (
            fab_match or                                    # Fabricante encontrado
            mod_match or                                    # Modelo encontrado
            cat_match or                                    # Sinônimo de categoria encontrado
            kw_matches >= 1 or                              # 1+ keyword de produto
            spec_match                                      # Spec de produto encontrada
        )

        if is_relevant:
            relevant.append(edital)
        else:
            # Marcar como filtrado com score 0
            edital['score_tecnico'] = 0
            edital['recomendacao'] = 'NAO PARTICIPAR'
            edital['justificativa'] = 'Pre-filtro: objeto sem relacao com portfolio de produtos.'
            edital['produtos_aderentes'] = []
            filtered.append(edital)

    print(f"[TOOLS] Pre-filter: {len(relevant)} relevant, {len(filtered)} filtered out of {len(editais)} total")
    return relevant, filtered


# ── Prompt e Batch para score rápido ──────────────────────────────────────────

PROMPT_CALCULAR_SCORE_BATCH = """Analise a aderencia entre os PRODUTOS da empresa e os EDITAIS abaixo.

## PRODUTOS:
{produtos_json}

## EDITAIS:
{editais_json}

## REGRAS:
- 80-100: PARTICIPAR (produto atende DIRETAMENTE ao objeto, specs compativeis)
- 50-79: AVALIAR (categoria certa mas specs podem nao bater — ex: volume, modelo, tipo diferentes)
- 0-49: NAO PARTICIPAR (produtos nao correspondem ao objeto)

IMPORTANTE: Diferencie por ESPECIFICACOES tecnicas. Exemplos:
- Seringa 10mL NAO atende edital de seringa insulina 1mL (volume e tipo diferentes)
- Microscopio optico NAO atende edital de microscopio eletronico
- Edital de SERVICO (manutencao, reinstalacao, profissional) NAO e atendido por PRODUTO

Responda APENAS com um JSON array, um item por edital, NA MESMA ORDEM:
[{{"idx":0,"score_tecnico":85,"recomendacao":"PARTICIPAR","produto_principal":"Nome do produto","justificativa":"Frase curta explicando"}}]

IMPORTANTE: Responda SOMENTE o JSON array, sem texto adicional."""


def _score_batch(batch_editais, produtos_json, batch_num, total_batches):
    """Calcula score para um lote de editais via deepseek-chat (rápido)."""
    import time

    t0 = time.time()
    # Preparar editais para o prompt (objeto limitado a 300 chars)
    editais_for_prompt = []
    for i, ed in enumerate(batch_editais):
        editais_for_prompt.append({
            "idx": i,
            "numero": ed.get("numero", "N/A"),
            "orgao": ed.get("orgao", "N/A"),
            "objeto": (ed.get("objeto", "") or "")[:300],
        })

    editais_json = json.dumps(editais_for_prompt, ensure_ascii=False)

    prompt = PROMPT_CALCULAR_SCORE_BATCH.format(
        produtos_json=produtos_json,
        editais_json=editais_json,
    )

    print(f"[TOOLS] Batch {batch_num}/{total_batches}: scoring {len(batch_editais)} editais...")

    try:
        resposta = call_deepseek(
            [{"role": "user", "content": prompt}],
            max_tokens=1500,
            model_override="deepseek-chat"
        )

        if not resposta or len(resposta.strip()) < 5:
            print(f"[TOOLS] Batch {batch_num}: resposta vazia, zerando scores")
            return [{"score_tecnico": 0, "recomendacao": "AVALIAR", "produto_principal": "", "justificativa": "Erro: resposta vazia da IA"} for _ in batch_editais]

        # Extrair JSON array da resposta
        json_match = re.search(r'\[[\s\S]*\]', resposta)
        if json_match:
            raw_json = json_match.group()
            # Limpar chars que quebram parser
            raw_json = raw_json.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
            raw_json = re.sub(r'  +', ' ', raw_json)

            scores = json.loads(raw_json)
            elapsed = time.time() - t0
            print(f"[TOOLS] Batch {batch_num}/{total_batches}: {len(scores)} scores em {elapsed:.1f}s")
            return scores
        else:
            print(f"[TOOLS] Batch {batch_num}: nenhum JSON array encontrado")
            print(f"[TOOLS] Resposta bruta: {resposta[:200]}...")
            return [{"score_tecnico": 0, "recomendacao": "AVALIAR", "produto_principal": "", "justificativa": "Erro ao processar resposta da IA"} for _ in batch_editais]

    except Exception as e:
        elapsed = time.time() - t0
        print(f"[TOOLS] Batch {batch_num}: ERRO em {elapsed:.1f}s: {e}")
        return [{"score_tecnico": 0, "recomendacao": "AVALIAR", "produto_principal": "", "justificativa": f"Erro: {str(e)[:80]}"} for _ in batch_editais]


# ── Prompt original (mantido para compatibilidade) ───────────────────────────

PROMPT_CALCULAR_SCORE = """Você é um especialista em análise de licitações públicas brasileiras.

Analise a aderência entre os PRODUTOS do portfólio da empresa e o EDITAL de licitação.

## PRODUTOS DO PORTFÓLIO DA EMPRESA:
{produtos_json}

## EDITAL A ANALISAR:
- Número: {numero}
- Órgão: {orgao}
- Objeto: {objeto}
- Valor estimado: {valor}

## CRITÉRIOS DE ANÁLISE:
1. **Aderência Técnica**: Os produtos atendem ao objeto do edital? Há compatibilidade técnica?
2. **Categoria**: A categoria dos produtos (informática, equipamento médico, etc.) corresponde ao tipo de contratação?
3. **Especificações**: As especificações dos produtos são compatíveis com os requisitos implícitos do edital?

## REGRAS DE SCORE:
- **80-100%**: Alta aderência - produtos atendem diretamente ao objeto. Recomendação: PARTICIPAR
- **50-79%**: Média aderência - produtos podem atender com adaptações. Recomendação: AVALIAR
- **0-49%**: Baixa aderência - produtos não correspondem ao objeto. Recomendação: NÃO PARTICIPAR

## RESPOSTA OBRIGATÓRIA:
Forneça sua análise em formato JSON:

```json
{{
    "score_tecnico": <número inteiro de 0 a 100>,
    "recomendacao": "<PARTICIPAR ou AVALIAR ou NÃO PARTICIPAR>",
    "produtos_aderentes": [
        {{
            "produto_id": "<id do produto>",
            "produto_nome": "<nome do produto>",
            "aderencia": <número 0-100>,
            "motivo": "<explicação de 1-2 frases>"
        }}
    ],
    "justificativa": "<Explicação detalhada de 2-3 parágrafos explicando: 1) Por que o score foi atribuído, 2) Quais produtos são mais aderentes e por quê, 3) Riscos e oportunidades da participação>"
}}
```"""


def tool_calcular_score_aderencia(editais: List[Dict], user_id: str, empresa_id: str = None) -> Dict[str, Any]:
    """
    Calcula o score de aderência para uma lista de editais vs produtos do usuário/empresa.
    Pipeline de 3 camadas: pré-filtro por keywords → score batch → paralelo com deepseek-chat.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    t_total = time.time()
    db = get_db()
    try:
        # 1. Buscar produtos da empresa (ou do user como fallback)
        if empresa_id:
            produtos = db.query(Produto).filter(Produto.empresa_id == empresa_id).all()
        else:
            produtos = db.query(Produto).filter(Produto.empresa_id == empresa_id).all()

        if not produtos:
            return {
                "success": True,
                "editais_com_score": editais,
                "aviso": "Você não tem produtos cadastrados. Cadastre produtos para calcular aderência."
            }

        # 2. Preparar dados dos produtos (resumidos)
        produtos_data = []
        for p in produtos:
            specs = db.query(ProdutoEspecificacao).filter(
                ProdutoEspecificacao.produto_id == p.id
            ).limit(5).all()
            specs_resumo = [f"{s.nome_especificacao}: {s.valor}" for s in specs]

            produtos_data.append({
                "id": p.id,
                "nome": p.nome,
                "categoria": p.categoria,
                "fabricante": p.fabricante,
                "modelo": p.modelo,
                "specs": specs_resumo,
                "termos_busca": p.termos_busca or [],
                "catmat_descricoes": p.catmat_descricoes or [],
            })

        # JSON compacto para o prompt batch (com specs para diferenciação)
        produtos_for_prompt = []
        for p in produtos_data:
            entry = {
                "nome": p["nome"],
                "categoria": p.get("categoria", ""),
                "fabricante": p.get("fabricante", ""),
            }
            if p.get("modelo"):
                entry["modelo"] = p["modelo"]
            if p.get("specs"):
                entry["specs"] = p["specs"][:5]
            produtos_for_prompt.append(entry)
        produtos_json = json.dumps(produtos_for_prompt, ensure_ascii=False)
        print(f"[TOOLS] Portfolio: {len(produtos)} produtos, JSON prompt: {len(produtos_json)} chars")

        # 3. CAMADA 1: Pré-filtro por keywords (sem LLM, <100ms)
        t_prefilter = time.time()
        keyword_index = _build_product_keyword_index(produtos_data, db)
        relevant, filtered = _pre_filter_editais(editais, keyword_index)
        t_prefilter = time.time() - t_prefilter
        print(f"[TOOLS] Pre-filtro em {t_prefilter*1000:.0f}ms")

        # 4. CAMADA 2+3: Score batch + paralelo
        if relevant:
            BATCH_SIZE = 5 if len(produtos_data) <= 50 else 3
            batches = [relevant[i:i+BATCH_SIZE] for i in range(0, len(relevant), BATCH_SIZE)]
            total_batches = len(batches)
            MAX_WORKERS = min(total_batches, 4)

            print(f"[TOOLS] Scoring {len(relevant)} editais em {total_batches} batches ({BATCH_SIZE}/batch, {MAX_WORKERS} workers)")

            # CV02-12 (Arnaldo Sprint 2 V8): set normalizado de nomes/modelos reais
            # do portfolio, usado para vetar alucinacoes da IA (ex.: "GEN-2024-PRO").
            import unicodedata as _ucv12
            def _norm_prod(s):
                return _ucv12.normalize('NFKD', (s or '').lower()).encode('ascii','ignore').decode('ascii').strip()
            portfolio_nomes_norm = set()
            for _p in produtos_data:
                if _p.get('nome'):
                    portfolio_nomes_norm.add(_norm_prod(_p['nome']))
                if _p.get('modelo'):
                    portfolio_nomes_norm.add(_norm_prod(_p['modelo']))

            t_score = time.time()
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_batch = {}
                for batch_idx, batch in enumerate(batches):
                    future = executor.submit(
                        _score_batch, batch, produtos_json, batch_idx + 1, total_batches
                    )
                    future_to_batch[future] = (batch_idx, batch)

                for future in as_completed(future_to_batch, timeout=120):
                    batch_idx, batch = future_to_batch[future]
                    try:
                        scores = future.result()
                        # Atribuir scores aos editais do batch
                        for i, edital in enumerate(batch):
                            if i < len(scores):
                                s = scores[i]
                                edital['score_tecnico'] = s.get('score_tecnico', 0)
                                edital['recomendacao'] = s.get('recomendacao', 'AVALIAR')
                                edital['justificativa'] = s.get('justificativa', '')
                                # Converter produto_principal para formato esperado pelo frontend
                                prod_nome = s.get('produto_principal', '')
                                # CV02-12: validar que o nome devolvido bate com o portfolio
                                # real — IA inventava SKUs (ex.: "GEN-2024-PRO") que nao
                                # existiam, induzindo o validador a erro.
                                prod_nome_norm = _norm_prod(prod_nome)
                                prod_valido = bool(prod_nome) and (
                                    prod_nome_norm in portfolio_nomes_norm or
                                    any(prod_nome_norm in pn or pn in prod_nome_norm for pn in portfolio_nomes_norm if len(pn) > 4)
                                )
                                if prod_nome and prod_valido:
                                    edital['produtos_aderentes'] = [{
                                        "produto_nome": prod_nome,
                                        "aderencia": s.get('score_tecnico', 0)
                                    }]
                                else:
                                    if prod_nome and not prod_valido:
                                        print(f"[TOOLS] CV02-12: descartando produto alucinado '{prod_nome}' (nao bate com portfolio)")
                                    edital['produtos_aderentes'] = []
                                print(f"[TOOLS] Score {edital.get('numero')}: {edital['score_tecnico']}% - {edital['recomendacao']}")
                            else:
                                edital['score_tecnico'] = 0
                                edital['recomendacao'] = 'AVALIAR'
                                edital['justificativa'] = 'Score nao retornado pelo batch.'
                                edital['produtos_aderentes'] = []
                    except Exception as e:
                        print(f"[TOOLS] Erro no batch {batch_idx + 1}: {e}")
                        for edital in batch:
                            edital['score_tecnico'] = 0
                            edital['recomendacao'] = 'AVALIAR'
                            edital['justificativa'] = f'Erro no batch: {str(e)[:80]}'
                            edital['produtos_aderentes'] = []

            t_score = time.time() - t_score
            print(f"[TOOLS] Scoring total em {t_score:.1f}s")

        # 5. Combinar relevant + filtered, ordenar por score desc
        editais_com_score = relevant + filtered
        editais_com_score.sort(key=lambda x: x.get('score_tecnico', 0), reverse=True)

        t_total = time.time() - t_total
        print(f"[TOOLS] === SCORE TOTAL: {len(editais_com_score)} editais em {t_total:.1f}s "
              f"({len(relevant)} scored, {len(filtered)} pre-filtered) ===")

        return {
            "success": True,
            "editais_com_score": editais_com_score,
            "total_produtos": len(produtos)
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def _buscar_edital_pncp_por_numero(numero_edital: str, orgao: str = None) -> Dict[str, Any]:
    """
    Busca dados completos de um edital no PNCP pelo número.
    Retorna dict com dados ou None se não encontrar.
    Otimizado: máx 2 páginas, timeout 15s, para assim que encontrar.
    """
    import re
    from datetime import datetime, timedelta
    from config import PNCP_BASE_URL

    print(f"[PNCP] Buscando edital {numero_edital} no PNCP...")

    # Extrair número e ano do edital (ex: "90039/2025" -> numero=90039, ano=2025)
    match = re.search(r'(\d+)[/-](\d{4})', numero_edital)
    if not match:
        print(f"[PNCP] Não conseguiu extrair número/ano de {numero_edital}")
        return None

    numero = match.group(1)
    ano = match.group(2)

    try:
        # Restringir janela de data ao ano do edital (muito mais eficiente)
        ano_int = int(ano)
        data_inicial = datetime(ano_int, 1, 1)
        data_final = min(datetime(ano_int, 12, 31), datetime.now())

        params = {
            "dataInicial": data_inicial.strftime("%Y%m%d"),
            "dataFinal": data_final.strftime("%Y%m%d"),
            "codigoModalidadeContratacao": 6,  # Pregão Eletrônico
            "tamanhoPagina": 50,
            "pagina": 1
        }

        # Buscar no máximo 2 páginas (100 editais), timeout reduzido
        all_items = []
        for pagina in range(1, 3):  # Máx 2 páginas (era 5)
            params["pagina"] = pagina
            response = requests.get(
                f"{PNCP_BASE_URL}/contratacoes/publicacao",
                params=params,
                headers={"Accept": "application/json"},
                timeout=15  # Reduzido de 30s para 15s
            )

            if response.status_code != 200:
                print(f"[PNCP] Erro na API página {pagina}: {response.status_code}")
                break

            data = response.json()
            items = data.get('data', [])
            if not items:
                break
            all_items.extend(items)

            # Verificar se já encontrou o edital nesta página — para imediatamente
            for item in items:
                numero_compra = str(item.get('numeroCompra', ''))
                seq_compra = str(item.get('sequencialCompra', ''))
                if numero in numero_compra or numero in seq_compra or numero_compra == numero:
                    print(f"[PNCP] Encontrado na página {pagina}!")
                    break
            else:
                continue
            break

        print(f"[PNCP] Buscando entre {len(all_items)} editais...")
        items = all_items

        # Procurar pelo número
        for item in items:
            numero_compra = str(item.get('numeroCompra', ''))
            seq_compra = str(item.get('sequencialCompra', ''))

            # Match por número ou sequencial
            if numero in numero_compra or numero in seq_compra or numero_compra == numero:
                orgao_data = item.get('orgaoEntidade', {}) or {}
                unidade_data = item.get('unidadeOrgao', {}) or {}
                cnpj = (orgao_data.get('cnpj') or '').replace('.', '').replace('/', '').replace('-', '')

                # Construir URL do PNCP
                ano_compra = item.get('anoCompra')
                seq = item.get('sequencialCompra')
                if cnpj and ano_compra and seq:
                    url_pncp = f"https://pncp.gov.br/app/editais/{cnpj}/{ano_compra}/{seq}"
                else:
                    url_pncp = item.get('linkSistemaOrigem', '')

                print(f"[PNCP] Encontrado! CNPJ: {cnpj}, Ano: {ano_compra}, Seq: {seq}")

                return {
                    'cnpj_orgao': cnpj,
                    'ano_compra': ano_compra,
                    'seq_compra': seq,
                    'numero_pncp': item.get('numeroControlePNCP'),
                    'objeto': item.get('objetoCompra'),
                    'valor_referencia': item.get('valorTotalEstimado'),
                    'data_abertura': item.get('dataAberturaProposta'),
                    'data_encerramento': item.get('dataEncerramentoProposta'),
                    'data_fim_vigencia': item.get('dataFimVigencia'),
                    'data_publicacao': item.get('dataPublicacaoPncp'),
                    'uf': unidade_data.get('ufSigla'),
                    'cidade': unidade_data.get('municipioNome'),
                    'orgao': orgao_data.get('razaoSocial'),
                    'url': url_pncp,
                    'srp': item.get('srp', False),
                    'situacao': item.get('situacaoCompraNome'),
                }

        print(f"[PNCP] Edital {numero_edital} não encontrado no PNCP")
        return None

    except Exception as e:
        print(f"[PNCP] Erro ao buscar: {e}")
        return None


def _buscar_itens_pncp(cnpj: str, ano: int, seq: int) -> List[Dict]:
    """
    Busca os itens de um edital no PNCP.
    Endpoint: GET /api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens

    Retorna lista de itens com: numero, descricao, quantidade, unidade, valor_unitario, valor_total
    """
    try:
        # URL correta da API PNCP
        url = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens"
        print(f"[PNCP] Buscando itens: {url}")

        response = requests.get(
            url,
            headers={"Accept": "application/json"},
            timeout=15
        )

        if response.status_code == 200:
            data = response.json()
            itens = []

            # A API retorna uma lista de itens diretamente ou em 'data'
            items_data = data if isinstance(data, list) else data.get('data', [])

            for item in items_data:
                itens.append({
                    "numero": item.get('numeroItem'),
                    "descricao": item.get('descricao', ''),
                    "quantidade": item.get('quantidade'),
                    "unidade": item.get('unidadeMedida', ''),
                    "valor_unitario": item.get('valorUnitarioEstimado'),
                    "valor_total": item.get('valorTotal'),
                    "criterio_julgamento": item.get('criterioJulgamentoNome'),
                    "situacao": item.get('situacaoCompraItemNome'),
                })

            print(f"[PNCP] Encontrados {len(itens)} itens")
            return itens
        else:
            print(f"[PNCP] Erro ao buscar itens: {response.status_code}")
            return []

    except Exception as e:
        print(f"[PNCP] Erro ao buscar itens: {e}")
        return []


def _buscar_arquivos_pncp(cnpj: str, ano: int, seq: int) -> List[Dict]:
    """
    Busca os arquivos (PDFs) de um edital no PNCP.
    Endpoint: GET /api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos

    Retorna lista de arquivos com: id, titulo, url
    """
    try:
        # URL correta da API PNCP
        url = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos"
        print(f"[PNCP] Buscando arquivos: {url}")

        response = requests.get(
            url,
            headers={"Accept": "application/json"},
            timeout=15
        )

        if response.status_code == 200:
            data = response.json()
            arquivos = []

            # A API retorna uma lista de arquivos
            items_data = data if isinstance(data, list) else data.get('data', [])

            for arq in items_data:
                # Construir URL para download do arquivo
                seq_arquivo = arq.get('sequencialDocumento') or arq.get('sequencialArquivo') or 1
                # URL correta para download
                download_url = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos/{seq_arquivo}"

                arquivos.append({
                    "id": seq_arquivo,
                    "titulo": arq.get('titulo', arq.get('nome', 'Documento')),
                    "tipo": arq.get('tipoDocumentoNome', 'Edital'),
                    "url": download_url,
                    "data_publicacao": arq.get('dataPublicacao'),
                })

            print(f"[PNCP] Encontrados {len(arquivos)} arquivos")
            return arquivos
        else:
            print(f"[PNCP] Erro ao buscar arquivos: {response.status_code}")
            return []

    except Exception as e:
        print(f"[PNCP] Erro ao buscar arquivos: {e}")
        return []


def _enriquecer_edital_pncp(edital_data: Dict) -> Dict:
    """
    Enriquece os dados de um edital do PNCP com itens e arquivos/PDF.
    Recebe um dict com cnpj_orgao, ano_compra, seq_compra e adiciona itens e pdf_url.
    """
    cnpj = edital_data.get('cnpj_orgao')
    ano = edital_data.get('ano_compra')
    seq = edital_data.get('seq_compra')

    if not all([cnpj, ano, seq]):
        print(f"[PNCP] Dados incompletos para enriquecer: cnpj={cnpj}, ano={ano}, seq={seq}")
        return edital_data

    # Buscar itens
    itens = _buscar_itens_pncp(cnpj, ano, seq)
    if itens:
        edital_data['itens'] = itens
        edital_data['total_itens'] = len(itens)

    # Buscar arquivos/PDF
    arquivos = _buscar_arquivos_pncp(cnpj, ano, seq)
    if arquivos:
        edital_data['arquivos'] = arquivos

        # Encontrar o PDF principal (edital)
        for arq in arquivos:
            titulo_lower = (arq.get('titulo', '') or '').lower()
            tipo_lower = (arq.get('tipo', '') or '').lower()
            if 'edital' in titulo_lower or 'edital' in tipo_lower:
                edital_data['pdf_url'] = arq.get('url')
                edital_data['pdf_titulo'] = arq.get('titulo')
                break

        # Se não encontrou um específico de "edital", pegar o primeiro
        if 'pdf_url' not in edital_data and arquivos:
            edital_data['pdf_url'] = arquivos[0].get('url')
            edital_data['pdf_titulo'] = arquivos[0].get('titulo')

    # Marcar fonte claramente
    edital_data['fonte'] = 'PNCP (API)'
    edital_data['fonte_tipo'] = 'api'
    edital_data['dados_completos'] = True

    return edital_data


# ==================== PARSERS PARA OUTRAS FONTES ====================

def _extrair_dados_pagina_edital(url: str) -> Dict[str, Any]:
    """
    Acessa a página do edital e extrai dados estruturados.
    Identifica a fonte pelo domínio e usa o parser apropriado.

    Returns:
        Dict com dados extraídos: numero, orgao, objeto, valor, data_abertura, pdf_url, fonte
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("[PARSER] BeautifulSoup não instalado. pip install beautifulsoup4")
        return {}

    try:
        print(f"[PARSER] Extraindo dados de: {url}")

        # Fazer request com User-Agent de navegador
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        url_lower = url.lower()

        # Identificar fonte e usar parser apropriado
        if 'comprasnet.gov.br' in url_lower or 'compras.gov.br' in url_lower:
            return _parse_comprasnet(soup, url)
        elif 'bec.sp.gov.br' in url_lower:
            return _parse_bec_sp(soup, url)
        elif 'licitacoes-e.com.br' in url_lower:
            return _parse_licitacoes_e(soup, url)
        elif 'compras.mg.gov.br' in url_lower:
            return _parse_compras_mg(soup, url)
        elif 'portaldecompraspublicas.com.br' in url_lower:
            return _parse_portal_compras_publicas(soup, url)
        elif 'siconv' in url_lower or 'plataformamaisbrasil' in url_lower or 'transferegov' in url_lower:
            return _parse_siconv(soup, url)
        else:
            # Parser genérico
            return _parse_generico(soup, url)

    except Exception as e:
        print(f"[PARSER] Erro ao extrair dados de {url}: {e}")
        return {}


def _parse_comprasnet(soup, url: str) -> Dict[str, Any]:
    """Parser para ComprasNet (gov.br/compras)"""
    dados = {
        'fonte': 'ComprasNet',
        'fonte_tipo': 'scraper',
        'url': url,
    }

    try:
        # Tentar extrair título/objeto
        for selector in ['h1', '.titulo-licitacao', '.objeto', '[data-objeto]', '.descricao-objeto']:
            elem = soup.select_one(selector)
            if elem and elem.text.strip():
                dados['objeto'] = elem.text.strip()[:500]
                break

        # Número da licitação
        for selector in ['.numero-licitacao', '.numero', '[data-numero]', 'span:contains("Nº")']:
            elem = soup.select_one(selector)
            if elem and elem.text.strip():
                match = re.search(r'(\d+[/-]\d{4})', elem.text)
                if match:
                    dados['numero'] = match.group(1)
                    break

        # Órgão
        for selector in ['.orgao', '.entidade', '[data-orgao]', '.nome-orgao']:
            elem = soup.select_one(selector)
            if elem and elem.text.strip():
                dados['orgao'] = elem.text.strip()[:200]
                break

        # Valor estimado
        for selector in ['.valor', '.valor-estimado', '[data-valor]']:
            elem = soup.select_one(selector)
            if elem and elem.text.strip():
                match = re.search(r'R\$\s*([\d.,]+)', elem.text)
                if match:
                    valor_str = match.group(1).replace('.', '').replace(',', '.')
                    try:
                        dados['valor_referencia'] = float(valor_str)
                    except:
                        pass
                    break

        # Data de abertura
        for selector in ['.data-abertura', '.data-sessao', '[data-abertura]']:
            elem = soup.select_one(selector)
            if elem and elem.text.strip():
                dados['data_abertura'] = elem.text.strip()
                break

        # Link do PDF/Edital
        for link in soup.find_all('a', href=True):
            href = link.get('href', '').lower()
            text = link.text.lower()
            if '.pdf' in href or 'edital' in text or 'documento' in text:
                pdf_href = link.get('href')
                if not pdf_href.startswith('http'):
                    from urllib.parse import urljoin
                    pdf_href = urljoin(url, pdf_href)
                dados['pdf_url'] = pdf_href
                dados['pdf_titulo'] = link.text.strip() or 'Edital'
                break

        print(f"[PARSER] ComprasNet extraiu: {dados.get('numero', 'sem numero')}")

    except Exception as e:
        print(f"[PARSER] Erro no parser ComprasNet: {e}")

    return dados


def _parse_bec_sp(soup, url: str) -> Dict[str, Any]:
    """Parser para BEC São Paulo"""
    dados = {
        'fonte': 'BEC-SP',
        'fonte_tipo': 'scraper',
        'url': url,
        'uf': 'SP',
    }

    try:
        # Número da OC/Pregão
        for selector in ['.numero-oc', '#numeroOC', 'span:contains("OC")', 'td:contains("Número")']:
            elem = soup.select_one(selector)
            if elem:
                text = elem.text.strip()
                match = re.search(r'(\d+[/-]?\d*)', text)
                if match:
                    dados['numero'] = match.group(1)
                    break

        # Objeto
        for selector in ['.objeto', '#objeto', '.descricao', 'td:contains("Objeto") + td']:
            elem = soup.select_one(selector)
            if elem and elem.text.strip():
                dados['objeto'] = elem.text.strip()[:500]
                break

        # Órgão
        for selector in ['.orgao', '#orgao', '.uge', 'td:contains("UGE") + td']:
            elem = soup.select_one(selector)
            if elem and elem.text.strip():
                dados['orgao'] = elem.text.strip()[:200]
                break

        # Valor
        for elem in soup.find_all(string=re.compile(r'R\$\s*[\d.,]+')):
            match = re.search(r'R\$\s*([\d.,]+)', elem)
            if match:
                valor_str = match.group(1).replace('.', '').replace(',', '.')
                try:
                    dados['valor_referencia'] = float(valor_str)
                    break
                except:
                    pass

        # PDF
        for link in soup.find_all('a', href=True):
            href = link.get('href', '').lower()
            if '.pdf' in href or 'edital' in href:
                pdf_href = link.get('href')
                if not pdf_href.startswith('http'):
                    from urllib.parse import urljoin
                    pdf_href = urljoin(url, pdf_href)
                dados['pdf_url'] = pdf_href
                break

        print(f"[PARSER] BEC-SP extraiu: {dados.get('numero', 'sem numero')}")

    except Exception as e:
        print(f"[PARSER] Erro no parser BEC-SP: {e}")

    return dados


def _parse_licitacoes_e(soup, url: str) -> Dict[str, Any]:
    """Parser para Licitações-e (Banco do Brasil)"""
    dados = {
        'fonte': 'Licitações-e',
        'fonte_tipo': 'scraper',
        'url': url,
    }

    try:
        # Número do pregão
        for elem in soup.find_all(['span', 'td', 'div']):
            text = elem.text.strip()
            if 'pregão' in text.lower() or 'edital' in text.lower():
                match = re.search(r'(\d+[/-]\d{4})', text)
                if match:
                    dados['numero'] = match.group(1)
                    break

        # Objeto
        obj_elem = soup.find(string=re.compile('objeto', re.I))
        if obj_elem:
            parent = obj_elem.find_parent()
            if parent:
                next_elem = parent.find_next_sibling()
                if next_elem:
                    dados['objeto'] = next_elem.text.strip()[:500]

        # Órgão
        for elem in soup.find_all(['h1', 'h2', '.entidade', '.comprador']):
            text = elem.text.strip()
            if len(text) > 10 and len(text) < 200:
                dados['orgao'] = text
                break

        # PDF
        for link in soup.find_all('a', href=True):
            href = link.get('href', '').lower()
            text = link.text.lower()
            if '.pdf' in href or 'edital' in text:
                pdf_href = link.get('href')
                if not pdf_href.startswith('http'):
                    from urllib.parse import urljoin
                    pdf_href = urljoin(url, pdf_href)
                dados['pdf_url'] = pdf_href
                break

        print(f"[PARSER] Licitações-e extraiu: {dados.get('numero', 'sem numero')}")

    except Exception as e:
        print(f"[PARSER] Erro no parser Licitações-e: {e}")

    return dados


def _parse_compras_mg(soup, url: str) -> Dict[str, Any]:
    """Parser para Portal de Compras de Minas Gerais"""
    dados = {
        'fonte': 'Compras MG',
        'fonte_tipo': 'scraper',
        'url': url,
        'uf': 'MG',
    }

    try:
        # Estrutura similar a outros portais
        for selector in ['h1', '.titulo', '#titulo']:
            elem = soup.select_one(selector)
            if elem and elem.text.strip():
                text = elem.text.strip()
                # Extrair número
                match = re.search(r'(\d+[/-]\d{4})', text)
                if match:
                    dados['numero'] = match.group(1)
                dados['objeto'] = text[:500]
                break

        # Órgão
        for selector in ['.orgao', '.entidade', '#orgao']:
            elem = soup.select_one(selector)
            if elem:
                dados['orgao'] = elem.text.strip()[:200]
                break

        # PDF
        for link in soup.find_all('a', href=True):
            href = link.get('href', '').lower()
            if '.pdf' in href:
                pdf_href = link.get('href')
                if not pdf_href.startswith('http'):
                    from urllib.parse import urljoin
                    pdf_href = urljoin(url, pdf_href)
                dados['pdf_url'] = pdf_href
                break

        print(f"[PARSER] Compras MG extraiu: {dados.get('numero', 'sem numero')}")

    except Exception as e:
        print(f"[PARSER] Erro no parser Compras MG: {e}")

    return dados


def _parse_portal_compras_publicas(soup, url: str) -> Dict[str, Any]:
    """Parser para Portal de Compras Públicas"""
    dados = {
        'fonte': 'Portal Compras Públicas',
        'fonte_tipo': 'scraper',
        'url': url,
    }

    try:
        # Número
        for elem in soup.find_all(['h1', 'h2', '.titulo', '.numero']):
            text = elem.text.strip()
            match = re.search(r'(\d+[/-]\d{4})', text)
            if match:
                dados['numero'] = match.group(1)
                break

        # Objeto
        for selector in ['.objeto', '.descricao', '#objeto', 'p.objeto']:
            elem = soup.select_one(selector)
            if elem:
                dados['objeto'] = elem.text.strip()[:500]
                break

        # Órgão
        for selector in ['.orgao', '.comprador', '.entidade']:
            elem = soup.select_one(selector)
            if elem:
                dados['orgao'] = elem.text.strip()[:200]
                break

        # PDF
        for link in soup.find_all('a', href=True):
            if '.pdf' in link.get('href', '').lower():
                pdf_href = link.get('href')
                if not pdf_href.startswith('http'):
                    from urllib.parse import urljoin
                    pdf_href = urljoin(url, pdf_href)
                dados['pdf_url'] = pdf_href
                break

        print(f"[PARSER] Portal Compras Públicas extraiu: {dados.get('numero', 'sem numero')}")

    except Exception as e:
        print(f"[PARSER] Erro no parser Portal Compras Públicas: {e}")

    return dados


def _parse_siconv(soup, url: str) -> Dict[str, Any]:
    """Parser para SICONV / Plataforma +Brasil (convênios e contratos de repasse)"""
    dados = {
        'fonte': 'SICONV',
        'fonte_tipo': 'scraper',
        'url': url,
    }

    try:
        # Número do convênio/contrato
        for elem in soup.find_all(['span', 'td', 'div', 'h1', 'h2']):
            text = elem.text.strip()
            match = re.search(r'(Conv[êe]nio|Contrato)\s*(?:n[ºo.]?\s*)?\s*(\d+[/-]?\d*)', text, re.I)
            if match:
                dados['numero'] = match.group(0).strip()[:100]
                break
            # Número SICONV padrão
            match2 = re.search(r'SICONV\s*[:\s]*(\d+)', text, re.I)
            if match2:
                dados['numero'] = f"SICONV {match2.group(1)}"
                break

        # Objeto
        for selector in ['.objeto', '#objeto', '.descricao', 'td:contains("Objeto")']:
            elem = soup.select_one(selector)
            if elem and elem.text.strip():
                dados['objeto'] = elem.text.strip()[:500]
                break
        if 'objeto' not in dados:
            # Tentar por texto próximo a "objeto"
            for elem in soup.find_all(string=re.compile(r'objeto', re.I)):
                parent = elem.find_parent()
                if parent:
                    next_elem = parent.find_next_sibling()
                    if next_elem and next_elem.text.strip():
                        dados['objeto'] = next_elem.text.strip()[:500]
                        break

        # Órgão / Proponente
        for selector in ['.proponente', '.orgao', '.concedente', '.entidade']:
            elem = soup.select_one(selector)
            if elem and elem.text.strip():
                dados['orgao'] = elem.text.strip()[:200]
                break

        # Valor
        for elem in soup.find_all(string=re.compile(r'R\$\s*[\d.,]+')):
            match = re.search(r'R\$\s*([\d.,]+)', elem)
            if match:
                valor_str = match.group(1).replace('.', '').replace(',', '.')
                try:
                    dados['valor_referencia'] = float(valor_str)
                    break
                except ValueError:
                    pass

        # PDF / Documentos
        for link in soup.find_all('a', href=True):
            href = link.get('href', '').lower()
            text = link.text.lower()
            if '.pdf' in href or 'edital' in text or 'documento' in text or 'plano de trabalho' in text:
                pdf_href = link.get('href')
                if not pdf_href.startswith('http'):
                    from urllib.parse import urljoin
                    pdf_href = urljoin(url, pdf_href)
                dados['pdf_url'] = pdf_href
                dados['pdf_titulo'] = link.text.strip() or 'Documento SICONV'
                break

        print(f"[PARSER] SICONV extraiu: {dados.get('numero', 'sem numero')}")

    except Exception as e:
        print(f"[PARSER] Erro no parser SICONV: {e}")

    return dados


def _parse_generico(soup, url: str) -> Dict[str, Any]:
    """Parser genérico para outras fontes"""
    dados = {
        'fonte': 'Web',
        'fonte_tipo': 'scraper',
        'url': url,
    }

    try:
        # Tentar extrair título da página
        title = soup.find('title')
        if title:
            titulo = title.text.strip()
            match = re.search(r'(\d+[/-]\d{4})', titulo)
            if match:
                dados['numero'] = match.group(1)
            if len(titulo) > 10:
                dados['objeto'] = titulo[:500]

        # Tentar h1
        h1 = soup.find('h1')
        if h1:
            text = h1.text.strip()
            if 'objeto' not in dados and len(text) > 10:
                dados['objeto'] = text[:500]
            if 'numero' not in dados:
                match = re.search(r'(\d+[/-]\d{4})', text)
                if match:
                    dados['numero'] = match.group(1)

        # Buscar valor R$
        for elem in soup.find_all(string=re.compile(r'R\$\s*[\d.,]+')):
            match = re.search(r'R\$\s*([\d.,]+)', elem)
            if match:
                valor_str = match.group(1).replace('.', '').replace(',', '.')
                try:
                    dados['valor_referencia'] = float(valor_str)
                    break
                except:
                    pass

        # Buscar PDF
        for link in soup.find_all('a', href=True):
            href = link.get('href', '').lower()
            if '.pdf' in href:
                pdf_href = link.get('href')
                if not pdf_href.startswith('http'):
                    from urllib.parse import urljoin
                    pdf_href = urljoin(url, pdf_href)
                dados['pdf_url'] = pdf_href
                break

        print(f"[PARSER] Genérico extraiu: {dados.get('numero', 'sem numero')}")

    except Exception as e:
        print(f"[PARSER] Erro no parser genérico: {e}")

    return dados


def tool_salvar_editais_selecionados(editais: List[Dict], user_id: str, empresa_id: str = None) -> Dict[str, Any]:
    """
    Salva editais selecionados no banco, verificando duplicatas.
    """
    db = get_db()
    try:
        salvos = []
        duplicados = []
        erros = []
        incompletos = []  # Editais salvos sem dados completos do PNCP

        for edital_data in editais:
            import re
            numero = edital_data.get('numero')
            orgao = edital_data.get('orgao')
            numero_pncp = edital_data.get('numero_pncp')

            # Validar numero - campo obrigatório
            if not numero:
                # Tentar extrair do título ou objeto
                titulo = edital_data.get('titulo', '') or ''
                objeto = edital_data.get('objeto', '') or ''
                texto_busca = f"{titulo} {objeto}"

                # Padrões de número de edital
                padroes_numero = [
                    r'(?:PE|Pregão|PREGÃO)\s*(?:Eletrônico\s*)?(?:N[ºo°]?\s*)?(\d+[/-]\d{4})',
                    r'(?:Edital|EDITAL)\s*(?:N[ºo°]?\s*)?(\d+[/-]\d{4})',
                    r'(\d{4,}[/-]\d{4})',  # 90004/2026
                    r'(\d{3,}[/-]\d{4})',  # 004/2026
                ]

                for padrao in padroes_numero:
                    match = re.search(padrao, texto_busca, re.IGNORECASE)
                    if match:
                        numero = match.group(1)
                        print(f"[SALVAR] Extraído número '{numero}' do título/objeto")
                        break

            # Se ainda não tem número, tentar extrair da URL
            if not numero:
                url = edital_data.get('url', '')
                if url:
                    match = re.search(r'/(\d+[-_/]\d+)/?', url)
                    if match:
                        numero = match.group(1).replace('/', '-').replace('_', '-')
                    else:
                        # Usar hash da URL como identificador
                        import hashlib
                        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
                        numero = f"SCR-{url_hash}"
                else:
                    # Gerar número único
                    numero = f"SCR-{str(uuid.uuid4())[:8]}"

            # Validar orgao - campo obrigatório
            if not orgao:
                orgao = edital_data.get('fonte', 'Não identificado')

            # Verificar se já existe
            existe = db.query(Edital).filter(
                Edital.empresa_id == empresa_id,
                Edital.numero == numero,
                Edital.orgao == orgao
            ).first()

            if existe:
                duplicados.append(numero)
                continue

            try:
                # Se edital veio do Scraper (sem dados PNCP), tentar buscar dados completos
                fonte_str = str(edital_data.get('fonte', '')).lower()
                if not edital_data.get('cnpj_orgao') and ('scraper' in fonte_str or 'gov.br' in fonte_str or 'compras' in fonte_str):
                    print(f"[SALVAR] Edital {numero} veio do Scraper, tentando enriquecer com PNCP...")
                    dados_pncp = _buscar_edital_pncp_por_numero(numero, edital_data.get('orgao'))
                    if dados_pncp:
                        print(f"[SALVAR] Dados PNCP encontrados para {numero}")
                        # Mesclar dados do PNCP com os existentes
                        edital_data.update({
                            'cnpj_orgao': dados_pncp.get('cnpj_orgao'),
                            'ano_compra': dados_pncp.get('ano_compra'),
                            'seq_compra': dados_pncp.get('seq_compra'),
                            'numero_pncp': dados_pncp.get('numero_pncp'),
                            'objeto': dados_pncp.get('objeto') or edital_data.get('objeto'),
                            'valor_referencia': dados_pncp.get('valor_referencia') or edital_data.get('valor_referencia'),
                            'data_abertura': dados_pncp.get('data_abertura') or edital_data.get('data_abertura'),
                            'data_publicacao': dados_pncp.get('data_publicacao') or edital_data.get('data_publicacao'),
                            'uf': dados_pncp.get('uf') or edital_data.get('uf'),
                            'cidade': dados_pncp.get('cidade') or edital_data.get('cidade'),
                            'url': dados_pncp.get('url') or edital_data.get('url'),
                            'srp': dados_pncp.get('srp', False),
                            'situacao': dados_pncp.get('situacao'),
                            'dados_completos': True
                        })
                    else:
                        print(f"[SALVAR] Não encontrou dados PNCP para {numero}")
                        # Tentar extrair dados da página HTML
                        url_edital = edital_data.get('url') or edital_data.get('link')
                        if url_edital:
                            print(f"[SALVAR] Tentando extrair dados da página: {url_edital}")
                            dados_pagina = _extrair_dados_pagina_edital(url_edital)
                            if dados_pagina:
                                # Mesclar dados extraídos
                                if dados_pagina.get('numero') and not numero.startswith('SCR-'):
                                    pass  # Manter o número já extraído
                                elif dados_pagina.get('numero'):
                                    numero = dados_pagina['numero']
                                if dados_pagina.get('orgao'):
                                    orgao = dados_pagina['orgao']
                                edital_data.update({
                                    'objeto': dados_pagina.get('objeto') or edital_data.get('objeto'),
                                    'valor_referencia': dados_pagina.get('valor_referencia') or edital_data.get('valor_referencia'),
                                    'data_abertura': dados_pagina.get('data_abertura') or edital_data.get('data_abertura'),
                                    'pdf_url': dados_pagina.get('pdf_url'),
                                    'pdf_titulo': dados_pagina.get('pdf_titulo'),
                                    'fonte': dados_pagina.get('fonte') or edital_data.get('fonte'),
                                    'fonte_tipo': 'scraper',
                                    'uf': dados_pagina.get('uf') or edital_data.get('uf'),
                                })
                                print(f"[SALVAR] Dados extraídos da página: numero={numero}, pdf={dados_pagina.get('pdf_url', 'não encontrado')}")
                        edital_data['dados_completos'] = False  # Marcar como incompleto

                # Validar modalidade - deve ser um dos valores do ENUM
                modalidades_validas = ['pregao_eletronico', 'pregao_presencial', 'concorrencia',
                                       'tomada_precos', 'convite', 'dispensa', 'inexigibilidade']
                modalidade = edital_data.get('modalidade', 'pregao_eletronico')
                if modalidade not in modalidades_validas:
                    modalidade = 'pregao_eletronico'  # Default para scraper

                # Validar data_abertura - não pode ser string como "Ver no portal"
                data_abertura = edital_data.get('data_abertura')
                if isinstance(data_abertura, str) and data_abertura and not data_abertura[0].isdigit():
                    data_abertura = None  # Limpar valores inválidos

                edital = Edital(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    numero=numero,
                    orgao=orgao,
                    orgao_tipo=edital_data.get('orgao_tipo', 'federal'),
                    uf=edital_data.get('uf'),
                    cidade=edital_data.get('cidade'),
                    objeto=edital_data.get('objeto', ''),
                    modalidade=modalidade,
                    valor_referencia=edital_data.get('valor_referencia'),
                    data_publicacao=edital_data.get('data_publicacao'),
                    data_abertura=data_abertura,
                    fonte=edital_data.get('fonte', 'PNCP'),
                    fonte_tipo=edital_data.get('fonte_tipo', 'api' if 'PNCP' in str(edital_data.get('fonte', '')) else 'scraper'),
                    url=edital_data.get('url'),
                    # Dados PNCP para buscar itens
                    numero_pncp=edital_data.get('numero_pncp'),
                    cnpj_orgao=edital_data.get('cnpj_orgao'),
                    ano_compra=edital_data.get('ano_compra'),
                    seq_compra=edital_data.get('seq_compra'),
                    srp=edital_data.get('srp', False),
                    situacao_pncp=edital_data.get('situacao'),
                    # Dados de PDF
                    pdf_url=edital_data.get('pdf_url'),
                    pdf_titulo=edital_data.get('pdf_titulo'),
                    dados_completos=edital_data.get('dados_completos', False),
                    status='novo'
                )
                db.add(edital)
                db.flush()  # Para obter o ID
                salvos.append(numero)

                # Marcar como incompleto se não tem dados PNCP
                if edital_data.get('dados_completos') == False:
                    incompletos.append(numero)

                # Buscar itens do edital no PNCP automaticamente
                if edital_data.get('cnpj_orgao') and edital_data.get('ano_compra') and edital_data.get('seq_compra'):
                    try:
                        resultado_itens = tool_buscar_itens_edital_pncp(
                            edital_id=edital.id,
                            cnpj=edital_data.get('cnpj_orgao'),
                            ano=edital_data.get('ano_compra'),
                            seq=edital_data.get('seq_compra'),
                            user_id=user_id
                        )
                        if resultado_itens.get('success'):
                            print(f"[SALVAR] {resultado_itens.get('total_itens', 0)} itens salvos para {numero}")
                    except Exception as e:
                        print(f"[SALVAR] Erro ao buscar itens de {numero}: {e}")

                    # Buscar arquivos/PDF do edital se ainda não tem pdf_url
                    if not edital.pdf_url:
                        try:
                            resultado_arquivos = tool_buscar_arquivos_edital_pncp(
                                edital_id=edital.id,
                                cnpj=edital_data.get('cnpj_orgao'),
                                ano=edital_data.get('ano_compra'),
                                seq=edital_data.get('seq_compra'),
                                user_id=user_id
                            )
                            if resultado_arquivos.get('success') and resultado_arquivos.get('arquivo_edital'):
                                arq_edital = resultado_arquivos.get('arquivo_edital')
                                edital.pdf_url = arq_edital.get('url_download') or arq_edital.get('url')
                                edital.pdf_titulo = arq_edital.get('titulo')
                                edital.dados_completos = True
                                print(f"[SALVAR] PDF encontrado para {numero}: {edital.pdf_titulo}")
                        except Exception as e:
                            print(f"[SALVAR] Erro ao buscar arquivos de {numero}: {e}")

                # Se tem score, salvar análise
                if edital_data.get('score_tecnico') is not None:
                    # Buscar primeiro produto aderente ou usar genérico
                    produtos_aderentes = edital_data.get('produtos_aderentes', [])
                    if produtos_aderentes:
                        produto_id = produtos_aderentes[0].get('produto_id')
                    else:
                        # Pegar primeiro produto do usuário
                        primeiro_produto = db.query(Produto).filter(Produto.empresa_id == empresa_id).first()
                        produto_id = primeiro_produto.id if primeiro_produto else None

                    if produto_id:
                        analise = Analise(
                            id=str(uuid.uuid4()),
                            edital_id=edital.id,
                            produto_id=produto_id,
                            user_id=user_id,
                            score_tecnico=edital_data.get('score_tecnico'),
                            recomendacao=edital_data.get('justificativa', '')[:5000]
                        )
                        db.add(analise)

            except Exception as e:
                erros.append(f"{numero}: {str(e)[:50]}")

        db.commit()

        return {
            "success": True,
            "salvos": salvos,
            "duplicados": duplicados,
            "erros": erros,
            "incompletos": incompletos,
            "total_salvos": len(salvos)
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# ==================== MINDSDB TOOL ====================

def tool_consulta_mindsdb(pergunta: str, user_id: str) -> Dict[str, Any]:
    """
    Envia uma pergunta em linguagem natural para o agente MindsDB (editais_database_searcher).
    O agente traduz para SQL, executa e retorna a resposta formatada.

    Args:
        pergunta: Pergunta em linguagem natural sobre editais/produtos
        user_id: ID do usuário (para contexto)

    Returns:
        Dict com resposta do MindsDB ou erro
    """
    import os

    # Configuração MindsDB
    MINDSDB_HOST = os.getenv("MINDSDB_HOST", "192.168.1.100")
    MINDSDB_PORT = os.getenv("MINDSDB_PORT", "47334")
    MINDSDB_USER = os.getenv("MINDSDB_USER", "mindsdb")
    MINDSDB_PASSWORD = os.getenv("MINDSDB_PASSWORD", "")

    try:
        # Método 1: Via API REST do MindsDB
        url = f"http://{MINDSDB_HOST}:{MINDSDB_PORT}/api/sql/query"

        # Query para o agente
        sql_query = f"""
        SELECT *
        FROM mindsdb.editais_database_searcher
        WHERE question = '{pergunta.replace("'", "''")}';
        """

        print(f"[MINDSDB] Enviando consulta: {pergunta[:100]}...")

        response = requests.post(
            url,
            json={"query": sql_query},
            headers={"Content-Type": "application/json"},
            timeout=120  # MindsDB pode demorar com consultas complexas
        )

        if response.status_code == 200:
            data = response.json()

            # Extrair resposta do agente
            if data.get("data") and len(data["data"]) > 0:
                row = data["data"][0]
                # A resposta pode estar em diferentes colunas dependendo da versão
                resposta = None
                if isinstance(row, dict):
                    resposta = row.get("answer") or row.get("response") or row.get("result")
                elif isinstance(row, list) and len(row) > 0:
                    resposta = row[0]

                if resposta:
                    print(f"[MINDSDB] Resposta recebida: {str(resposta)[:200]}...")
                    return {
                        "success": True,
                        "resposta": resposta,
                        "pergunta": pergunta
                    }
                else:
                    return {
                        "success": False,
                        "error": "Resposta vazia do agente MindsDB",
                        "raw_data": data
                    }
            else:
                return {
                    "success": False,
                    "error": "Sem dados retornados pelo MindsDB",
                    "raw_response": data
                }
        else:
            return {
                "success": False,
                "error": f"Erro HTTP {response.status_code}: {response.text[:500]}"
            }

    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "error": f"Não foi possível conectar ao MindsDB em {MINDSDB_HOST}:{MINDSDB_PORT}. Verifique se o serviço está rodando."
        }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "Timeout na consulta ao MindsDB (>120s). A consulta pode ser muito complexa."
        }
    except Exception as e:
        print(f"[MINDSDB] Erro: {e}")
        return {
            "success": False,
            "error": str(e)
        }


# ==================== SPRINT 1: REGISTRAR RESULTADO DE CERTAME ====================

PROMPT_EXTRAIR_RESULTADO = """Extraia os dados deste registro de resultado de licitação.

MENSAGEM DO USUÁRIO:
"{message}"

IMPORTANTE:
- Valores monetários: converta "365k" para 365000, "1.2M" para 1200000, "R$ 450.000,00" para 450000
- Se o usuário mencionar que "perdemos" ou "não ganhamos", o resultado é "derrota"
- Se mencionar "ganhamos" ou "vencemos", o resultado é "vitoria"
- Se mencionar "cancelado", "revogado" ou "deserto", use esses valores
- Identifique todos os participantes mencionados com suas posições
- O "motivo" só deve ser preenchido se for derrota

Retorne APENAS um JSON válido:
{{
    "edital": "número do edital (ex: PE-001/2026)",
    "resultado": "vitoria|derrota|cancelado|deserto|revogado",
    "nosso_preco": número ou null,
    "preco_vencedor": número ou null,
    "empresa_vencedora": "nome da empresa" ou null,
    "cnpj_vencedor": "cnpj" ou null,
    "motivo": "preco|tecnica|documentacao|prazo|outro" ou null,
    "outros_participantes": [
        {{"empresa": "nome", "preco": número, "posicao": número}}
    ]
}}"""


def tool_registrar_resultado(message: str, user_id: str, empresa_id: str = None, db=None) -> Dict[str, Any]:
    """
    Registra resultado de certame (vitória/derrota) e alimenta base de preços históricos.

    Args:
        message: Mensagem do usuário descrevendo o resultado
        user_id: ID do usuário
        db: Sessão do banco (opcional, será criada se não fornecida)

    Returns:
        Dict com sucesso/erro e dados registrados
    """
    from models import Edital, Concorrente, PrecoHistorico, ParticipacaoEdital

    close_db = False
    if db is None:
        db = get_db()
        close_db = True

    try:
        # 1. Extrair dados via LLM (usar deepseek-chat para extração de JSON)
        prompt = PROMPT_EXTRAIR_RESULTADO.format(message=message)
        resposta = call_deepseek(
            [{"role": "user", "content": prompt}],
            max_tokens=500,
            model_override="deepseek-chat"  # Chat é melhor para extração de JSON
        )

        # Extrair JSON da resposta
        json_match = re.search(r'\{[\s\S]*\}', resposta)
        if not json_match:
            return {"success": False, "error": "Não consegui extrair os dados. Tente um formato como: 'Perdemos o PE-001 para Empresa X com R$ 100.000'"}

        try:
            dados = json.loads(json_match.group())
        except json.JSONDecodeError:
            return {"success": False, "error": "Erro ao processar dados. Tente novamente com mais detalhes."}

        print(f"[TOOLS] Dados extraídos: {dados}")

        # 2. Buscar edital
        edital_numero = dados.get('edital', '')
        if not edital_numero:
            return {"success": False, "error": "Não identifiquei o número do edital. Informe o número (ex: PE-001/2026)"}

        print(f"[TOOLS] Buscando edital: '{edital_numero}'")

        # Busca exata primeiro
        edital = db.query(Edital).filter(
            Edital.numero.ilike(f"%{edital_numero}%"),
            Edital.empresa_id == empresa_id
        ).first()

        if not edital:
            # Tentar busca mais flexível, mas garantindo que match seja específico
            # Extrair partes: PE, 001, 2026 de "PE-001/2026"
            partes = re.findall(r'[A-Za-z]+|\d+', edital_numero)
            print(f"[TOOLS] Partes extraídas: {partes}")

            if len(partes) >= 2:
                # Buscar usando as partes mais relevantes (tipo + número)
                # Ex: PE e 001 para "PE-001/2026"
                tipo_edital = partes[0]  # PE, PP, CC, etc.
                num_edital = partes[1] if len(partes) > 1 else None

                # Buscar editais que contenham tanto o tipo quanto o número
                query = db.query(Edital).filter(
                    Edital.empresa_id == empresa_id
                )

                # Adicionar filtro por tipo se parece ser tipo de edital
                if tipo_edital.upper() in ['PE', 'PP', 'CC', 'TP', 'PREGAO', 'CONCORRENCIA']:
                    query = query.filter(Edital.numero.ilike(f"%{tipo_edital}%"))

                # Adicionar filtro por número
                if num_edital:
                    query = query.filter(Edital.numero.ilike(f"%{num_edital}%"))

                editais_encontrados = query.all()

                if len(editais_encontrados) == 1:
                    edital = editais_encontrados[0]
                elif len(editais_encontrados) > 1:
                    # Múltiplos encontrados - tentar match mais específico
                    # Ordenar por similaridade (o que contém mais partes)
                    for ed in editais_encontrados:
                        match_count = sum(1 for p in partes if p.lower() in ed.numero.lower())
                        if match_count >= len(partes) - 1:  # Match quase completo
                            edital = ed
                            break

                    if not edital:
                        numeros = [e.numero for e in editais_encontrados[:5]]
                        return {
                            "success": False,
                            "error": f"Encontrei múltiplos editais que podem corresponder a '{edital_numero}': {', '.join(numeros)}. Seja mais específico."
                        }

        if not edital:
            return {"success": False, "error": f"Edital '{edital_numero}' não encontrado no seu cadastro."}

        # 3. Registrar/atualizar concorrente vencedor
        concorrente_id = None
        empresa_vencedora = dados.get("empresa_vencedora")

        if empresa_vencedora and dados.get("resultado") != "vitoria":
            # Buscar concorrente existente
            concorrente = db.query(Concorrente).filter(
                Concorrente.nome.ilike(f"%{empresa_vencedora}%")
            ).first()

            if not concorrente:
                # Criar novo concorrente
                concorrente = Concorrente(
                    nome=empresa_vencedora,
                    cnpj=dados.get("cnpj_vencedor"),
                    editais_participados=0,
                    editais_ganhos=0
                )
                db.add(concorrente)
                db.flush()

            concorrente.editais_participados += 1
            concorrente.editais_ganhos += 1

            # Recalcular taxa de vitória
            if concorrente.editais_participados > 0:
                concorrente.taxa_vitoria = (concorrente.editais_ganhos / concorrente.editais_participados) * 100

            concorrente_id = concorrente.id

        # 4. Calcular desconto sobre referência
        desconto = None
        if edital.valor_referencia and dados.get("preco_vencedor"):
            preco_ref = float(edital.valor_referencia)
            preco_venc = float(dados["preco_vencedor"])
            if preco_ref > 0:
                desconto = ((preco_ref - preco_venc) / preco_ref) * 100

        # 5. Registrar preço histórico
        preco_hist = PrecoHistorico(
            edital_id=edital.id,
            user_id=user_id,
            preco_referencia=edital.valor_referencia,
            preco_vencedor=dados.get("preco_vencedor"),
            nosso_preco=dados.get("nosso_preco"),
            desconto_percentual=desconto,
            concorrente_id=concorrente_id,
            empresa_vencedora=empresa_vencedora,
            cnpj_vencedor=dados.get("cnpj_vencedor"),
            resultado=dados.get("resultado"),
            motivo_perda=dados.get("motivo"),
            data_homologacao=datetime.now().date(),
            fonte="manual"
        )
        db.add(preco_hist)

        # 6. Registrar participações
        # Vencedor (se não somos nós)
        if concorrente_id and dados.get("preco_vencedor"):
            part_vencedor = ParticipacaoEdital(
                edital_id=edital.id,
                concorrente_id=concorrente_id,
                preco_proposto=dados["preco_vencedor"],
                posicao_final=1,
                fonte="manual"
            )
            db.add(part_vencedor)

        # Nossa participação
        if dados.get("nosso_preco"):
            nossa_posicao = 1 if dados.get("resultado") == "vitoria" else 2
            part_nossa = ParticipacaoEdital(
                edital_id=edital.id,
                concorrente_id=None,  # Nós mesmos
                preco_proposto=dados["nosso_preco"],
                posicao_final=nossa_posicao,
                fonte="manual"
            )
            db.add(part_nossa)

        # Outros participantes
        for part in dados.get("outros_participantes", []):
            if part.get("empresa"):
                # Buscar ou criar concorrente
                conc = db.query(Concorrente).filter(
                    Concorrente.nome.ilike(f"%{part['empresa']}%")
                ).first()

                if not conc:
                    conc = Concorrente(nome=part["empresa"])
                    db.add(conc)
                    db.flush()

                conc.editais_participados += 1

                part_edital = ParticipacaoEdital(
                    edital_id=edital.id,
                    concorrente_id=conc.id,
                    preco_proposto=part.get("preco"),
                    posicao_final=part.get("posicao"),
                    fonte="manual"
                )
                db.add(part_edital)

        # 7. Atualizar status do edital
        resultado = dados.get("resultado")
        if resultado == "vitoria":
            edital.status = "vencedor"
        elif resultado == "derrota":
            edital.status = "perdedor"
        elif resultado in ["cancelado", "revogado", "deserto"]:
            edital.status = resultado

        db.commit()

        # Calcular diferença de preço
        diferenca = None
        diferenca_pct = None
        if dados.get("nosso_preco") and dados.get("preco_vencedor") and dados.get("resultado") == "derrota":
            diferenca = float(dados["nosso_preco"]) - float(dados["preco_vencedor"])
            if float(dados["nosso_preco"]) > 0:
                diferenca_pct = (diferenca / float(dados["nosso_preco"])) * 100

        return {
            "success": True,
            "edital_numero": edital.numero,
            "edital_id": edital.id,
            "orgao": edital.orgao,
            "resultado": resultado,
            "preco_vencedor": dados.get("preco_vencedor"),
            "nosso_preco": dados.get("nosso_preco"),
            "empresa_vencedora": empresa_vencedora,
            "desconto_percentual": round(desconto, 1) if desconto else None,
            "diferenca": diferenca,
            "diferenca_pct": round(diferenca_pct, 1) if diferenca_pct else None,
            "motivo": dados.get("motivo")
        }

    except Exception as e:
        db.rollback()
        print(f"[TOOLS] Erro ao registrar resultado: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        if close_db:
            db.close()


# ==================== EXTRAIR ATA DE SESSÃO ====================

PROMPT_EXTRAIR_ATA = """Analise este documento de licitação (pode ser Ata de Sessão ou Ata de Registro de Preços) e extraia TODOS os dados.

TEXTO DO DOCUMENTO:
{texto_ata}

EXTRAIA:

1. **Dados Gerais:**
   - Número do edital/pregão (ex: PE0013/2025, PE-001/2026)
   - Órgão licitante
   - Data da sessão ou assinatura
   - Objeto resumido

2. **Para CADA ITEM registrado:**
   - Número do item
   - Descrição do produto/serviço
   - Empresa vencedora/fornecedora (nome completo)
   - CNPJ (se disponível, mesmo parcialmente mascarado)
   - Valor unitário e/ou total
   - Outros participantes se houver

3. **Empresas Desclassificadas (se houver)**

IMPORTANTE:
- Valores monetários: converta para número (R$ 300,0000 → 300.00, 365.000,00 → 365000.00)
- Extraia TODOS os itens que encontrar
- Em Atas de Registro de Preços, os itens geralmente estão no final do documento
- Se encontrar tabela com itens, extraia cada linha

Retorne APENAS um JSON válido:
{{
    "edital": "número do pregão/edital",
    "orgao": "nome do órgão licitante",
    "data_sessao": "dd/mm/yyyy",
    "objeto": "descrição resumida do objeto",
    "itens": [
        {{
            "item": 1,
            "descricao": "descrição do objeto",
            "vencedor": "nome da empresa vencedora",
            "cnpj_vencedor": "XX.XXX.XXX/XXXX-XX ou null",
            "preco_vencedor": 123456.78,
            "participantes": [
                {{"empresa": "nome", "cnpj": "...", "lance_final": 123456.78, "posicao": 1}}
            ]
        }}
    ],
    "desclassificados": [
        {{"empresa": "nome", "motivo": "motivo da desclassificação"}}
    ]
}}"""


def tool_extrair_ata_pdf(texto_pdf: str, user_id: str, empresa_id: str = None, db=None) -> Dict[str, Any]:
    """
    Extrai resultados de uma ata de sessão de pregão eletrônico.

    Args:
        texto_pdf: Texto extraído do PDF da ata
        user_id: ID do usuário
        db: Sessão do banco (opcional)

    Returns:
        Dict com dados extraídos e status
    """
    close_db = False
    if db is None:
        db = get_db()
        close_db = True

    try:
        # Verificar se o texto parece uma ata
        texto_lower = texto_pdf.lower()
        palavras_ata = ["ata", "sessão", "pregão", "licitação", "vencedor", "lance", "adjudicado"]
        if not any(p in texto_lower for p in palavras_ata):
            return {
                "success": False,
                "error": "O documento não parece ser uma ata de sessão de pregão. Envie uma ata de licitação."
            }

        # Limitar texto mas pegar partes importantes (início e fim)
        # Atas de Registro de Preços têm os itens/preços no final do documento
        if len(texto_pdf) > 20000:
            # Pegar início (dados gerais) + fim (itens e preços)
            texto_truncado = texto_pdf[:8000] + "\n\n[...]\n\n" + texto_pdf[-12000:]
        else:
            texto_truncado = texto_pdf[:20000]

        # Enviar para LLM
        prompt = PROMPT_EXTRAIR_ATA.format(texto_ata=texto_truncado)
        print(f"[TOOLS] Extraindo dados da ata via LLM...")

        resposta = call_deepseek(
            [{"role": "user", "content": prompt}],
            max_tokens=4000,
            model_override="deepseek-chat"
        )

        # Extrair JSON da resposta
        json_match = re.search(r'\{[\s\S]*\}', resposta)
        if not json_match:
            return {"success": False, "error": "Não consegui extrair dados estruturados da ata."}

        dados = json.loads(json_match.group())
        print(f"[TOOLS] Dados extraídos: edital={dados.get('edital')}, itens={len(dados.get('itens', []))}")

        # Verificar se extraiu algum item
        if not dados.get("itens") or len(dados.get("itens", [])) == 0:
            # Tentar extrair informações mesmo sem itens estruturados
            return {
                "success": True,
                "edital": dados.get("edital"),
                "orgao": dados.get("orgao"),
                "data_sessao": dados.get("data_sessao"),
                "objeto": dados.get("objeto"),
                "itens": [],
                "desclassificados": dados.get("desclassificados", []),
                "concorrentes_novos": [],
                "concorrentes_atualizados": [],
                "edital_encontrado": None,
                "dados_salvos": False,
                "aviso": "Não foi possível extrair itens detalhados da ata. Verifique se o PDF contém o resultado do certame."
            }

        # Buscar edital correspondente no banco (opcional)
        edital = None
        if dados.get("edital"):
            edital = db.query(Edital).filter(
                Edital.numero.ilike(f"%{dados['edital']}%"),
                Edital.empresa_id == empresa_id
            ).first()

        itens_processados = []
        concorrentes_novos = []
        concorrentes_atualizados = []

        # Processar cada item
        for item in dados.get("itens", []):
            item_result = {
                "item": item.get("item"),
                "descricao": item.get("descricao"),
                "vencedor": item.get("vencedor"),
                "preco_vencedor": item.get("preco_vencedor"),
                "participantes_count": len(item.get("participantes", []))
            }

            # Registrar vencedor como concorrente
            if item.get("vencedor"):
                conc = db.query(Concorrente).filter(
                    Concorrente.nome.ilike(f"%{item['vencedor']}%")
                ).first()

                if not conc:
                    conc = Concorrente(
                        nome=item["vencedor"],
                        cnpj=item.get("cnpj_vencedor"),
                        editais_participados=1,
                        editais_ganhos=1
                    )
                    db.add(conc)
                    db.flush()
                    concorrentes_novos.append(item["vencedor"])
                else:
                    conc.editais_participados = (conc.editais_participados or 0) + 1
                    conc.editais_ganhos = (conc.editais_ganhos or 0) + 1
                    concorrentes_atualizados.append(item["vencedor"])

                # Se temos o edital, registrar preço histórico
                if edital and item.get("preco_vencedor"):
                    preco_hist = PrecoHistorico(
                        edital_id=edital.id,
                        user_id=user_id,
                        preco_referencia=edital.valor_referencia,
                        preco_vencedor=item["preco_vencedor"],
                        empresa_vencedora=item["vencedor"],
                        cnpj_vencedor=item.get("cnpj_vencedor"),
                        concorrente_id=conc.id,
                        resultado="derrota",  # Se estamos extraindo ata, provavelmente não ganhamos
                        data_homologacao=datetime.strptime(dados.get("data_sessao", ""), "%d/%m/%Y").date() if dados.get("data_sessao") else datetime.now().date(),
                        fonte="ata_pdf"
                    )
                    db.add(preco_hist)

            # Registrar participantes
            for part in item.get("participantes", []):
                if part.get("empresa") and part["empresa"] != item.get("vencedor"):
                    conc_part = db.query(Concorrente).filter(
                        Concorrente.nome.ilike(f"%{part['empresa']}%")
                    ).first()

                    if not conc_part:
                        conc_part = Concorrente(
                            nome=part["empresa"],
                            cnpj=part.get("cnpj"),
                            editais_participados=1,
                            editais_ganhos=0
                        )
                        db.add(conc_part)
                        db.flush()
                        concorrentes_novos.append(part["empresa"])
                    else:
                        conc_part.editais_participados = (conc_part.editais_participados or 0) + 1
                        concorrentes_atualizados.append(part["empresa"])

                    # Registrar participação
                    if edital:
                        part_edital = ParticipacaoEdital(
                            edital_id=edital.id,
                            concorrente_id=conc_part.id,
                            preco_proposto=part.get("lance_final"),
                            posicao_final=part.get("posicao"),
                            fonte="ata_pdf"
                        )
                        db.add(part_edital)

            itens_processados.append(item_result)

        # Atualizar status do edital se encontrado
        if edital:
            edital.status = "perdedor"

        db.commit()

        return {
            "success": True,
            "edital": dados.get("edital"),
            "orgao": dados.get("orgao"),
            "data_sessao": dados.get("data_sessao"),
            "objeto": dados.get("objeto"),
            "itens": itens_processados,
            "desclassificados": dados.get("desclassificados", []),
            "concorrentes_novos": concorrentes_novos,
            "concorrentes_atualizados": concorrentes_atualizados,
            "edital_encontrado": edital.numero if edital else None,
            "dados_salvos": edital is not None
        }

    except json.JSONDecodeError as e:
        print(f"[TOOLS] Erro ao parsear JSON da ata: {e}")
        return {"success": False, "error": f"Erro ao interpretar dados da ata: {str(e)}"}
    except Exception as e:
        db.rollback()
        print(f"[TOOLS] Erro ao extrair ata: {e}")
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        if close_db:
            db.close()


# ==================== BUSCAR ATAS NO PNCP ====================

def tool_buscar_atas_pncp(termo: str, user_id: str = None) -> Dict[str, Any]:
    """
    Busca atas de registro de preço no PNCP.

    Args:
        termo: Termo de busca (ex: "hematologia", "equipamento hospitalar")
        user_id: ID do usuário

    Returns:
        Dict com atas encontradas e URLs para download
    """
    print(f"[PNCP-ATAS] Buscando atas de '{termo}'...")

    # Método 1: Usar API de busca do PNCP
    try:
        url_search = f"https://pncp.gov.br/api/search/?q={termo}&tipos_documento=ata&pagina=1&tam_pagina=10"
        response = requests.get(url_search, timeout=30)

        if response.status_code == 200:
            data = response.json()
            atas = []

            for item in data.get("items", []):
                ata = {
                    "id": item.get("id"),
                    "titulo": item.get("title"),
                    "descricao": item.get("description"),
                    "orgao": item.get("orgao_nome"),
                    "cnpj_orgao": item.get("orgao_cnpj"),
                    "uf": item.get("uf"),
                    "municipio": item.get("municipio_nome"),
                    "modalidade": item.get("modalidade_licitacao_nome"),
                    "data_publicacao": item.get("data_publicacao_pncp"),
                    "data_assinatura": item.get("data_assinatura"),
                    "vigencia_inicio": item.get("data_inicio_vigencia"),
                    "vigencia_fim": item.get("data_fim_vigencia"),
                    "numero_controle": item.get("numero_controle_pncp"),
                    "url_pncp": f"https://pncp.gov.br{item.get('item_url', '')}",
                    "ano": item.get("ano"),
                    "sequencial": item.get("numero_sequencial"),
                }
                atas.append(ata)

            if atas:
                return {
                    "success": True,
                    "fonte": "pncp_api",
                    "termo": termo,
                    "total": data.get("total", len(atas)),
                    "atas": atas
                }
    except Exception as e:
        print(f"[PNCP-ATAS] Erro na API do PNCP: {e}")

    # Método 2: Fallback para busca web (DuckDuckGo/Serper/SerpAPI)
    try:
        search_query = f"site:pncp.gov.br ata registro preço {termo} filetype:pdf"
        print(f"[PNCP-ATAS] Buscando via scraper web: {search_query}")

        raw_results = _web_search(search_query, 10)

        atas = []
        for result in raw_results:
            titulo = result.get('title', '')
            link = result.get('link', '')
            snippet = result.get('snippet', '')

            # Verificar se é realmente uma ata
            if any(p in titulo.lower() or p in snippet.lower() for p in ['ata', 'registro de preço', 'homologação']):
                ata = {
                    "titulo": titulo,
                    "descricao": snippet,
                    "url": link,
                    "url_pncp": link,
                    "fonte": "scraper_web"
                }
                atas.append(ata)

        if atas:
            return {
                "success": True,
                "fonte": "scraper_web",
                "termo": termo,
                "total": len(atas),
                "atas": atas
            }

    except Exception as e:
        print(f"[PNCP-ATAS] Erro no Serper: {e}")

    return {
        "success": False,
        "error": f"Não foi possível buscar atas para '{termo}'",
        "termo": termo
    }


def tool_baixar_ata_pncp(url: str, user_id: str = None) -> Dict[str, Any]:
    """
    Baixa uma ata/documento do PNCP e extrai o texto.

    Args:
        url: URL do documento (página do PNCP ou PDF direto)
        user_id: ID do usuário

    Returns:
        Dict com texto extraído e caminho do arquivo
    """
    import tempfile

    print(f"[PNCP-ATAS] Baixando documento: {url}")

    try:
        # Se for URL da página do PNCP, tentar encontrar o PDF
        if 'pncp.gov.br' in url and not url.endswith('.pdf'):
            # Tentar obter link do PDF da página
            response = requests.get(url, timeout=30)
            if response.status_code == 200:
                # Procurar links de PDF na página
                import re
                pdf_links = re.findall(r'href=["\']([^"\']*\.pdf)["\']', response.text, re.IGNORECASE)
                if pdf_links:
                    url = pdf_links[0]
                    if not url.startswith('http'):
                        url = f"https://pncp.gov.br{url}"

        # Baixar o arquivo
        response = requests.get(url, timeout=60, stream=True)
        response.raise_for_status()

        # Salvar em arquivo temporário
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            for chunk in response.iter_content(chunk_size=8192):
                tmp_file.write(chunk)
            filepath = tmp_file.name

        # Extrair texto do PDF
        texto = ""
        try:
            doc = fitz.open(filepath)
            for page in doc:
                texto += page.get_text()
            doc.close()
        except Exception as e:
            return {
                "success": False,
                "error": f"Erro ao extrair texto do PDF: {e}"
            }

        if len(texto) < 100:
            return {
                "success": False,
                "error": "PDF vazio ou não foi possível extrair texto (pode ser imagem escaneada)"
            }

        return {
            "success": True,
            "url": url,
            "filepath": filepath,
            "texto": texto,
            "tamanho_texto": len(texto)
        }

    except requests.RequestException as e:
        return {
            "success": False,
            "error": f"Erro ao baixar documento: {e}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Erro inesperado: {e}"
        }


# ==================== BUSCAR ITENS DO EDITAL NO PNCP ====================

def tool_buscar_itens_edital_pncp(edital_id: str = None, cnpj: str = None, ano: int = None, seq: int = None, user_id: str = None) -> Dict[str, Any]:
    """
    Busca os itens/lotes de um edital na API do PNCP e salva no banco.

    Args:
        edital_id: ID do edital no banco (se já existe)
        cnpj: CNPJ do órgão (sem formatação)
        ano: Ano da compra
        seq: Sequencial da compra
        user_id: ID do usuário

    Returns:
        Dict com itens encontrados
    """
    db = get_db()
    try:
        edital = None

        # Se passou edital_id, buscar dados do PNCP do edital
        if edital_id:
            edital = db.query(Edital).filter(Edital.id == edital_id).first()
            if edital:
                cnpj = edital.cnpj_orgao
                ano = edital.ano_compra
                seq = edital.seq_compra

        if not cnpj or not ano or not seq:
            return {
                "success": False,
                "error": "Dados insuficientes para buscar itens (cnpj, ano, seq)"
            }

        print(f"[PNCP-ITENS] Buscando itens: CNPJ={cnpj}, Ano={ano}, Seq={seq}")

        # API de itens do PNCP
        # Formato correto: /api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens
        url_itens = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/itens"

        response = requests.get(
            url_itens,
            timeout=30,
            headers={"Accept": "application/json"}
        )

        if response.status_code == 404:
            return {
                "success": True,
                "itens": [],
                "message": "Nenhum item encontrado para este edital"
            }

        response.raise_for_status()
        itens_api = response.json()

        print(f"[PNCP-ITENS] Encontrados {len(itens_api)} itens")

        itens_processados = []
        for item in itens_api:
            item_data = {
                "numero_item": item.get('numeroItem'),
                "descricao": item.get('descricao'),
                "unidade_medida": item.get('unidadeMedida'),
                "quantidade": item.get('quantidade'),
                "valor_unitario_estimado": item.get('valorUnitarioEstimado'),
                "valor_total_estimado": item.get('valorTotal'),
                "codigo_item": item.get('codigoRegistroImobiliario') or item.get('materialServico'),
                "tipo_beneficio": item.get('tipoBeneficioNome'),
            }
            itens_processados.append(item_data)

            # Se tem edital, salvar no banco
            if edital:
                # Verificar se item já existe
                item_existente = db.query(EditalItem).filter(
                    EditalItem.edital_id == edital.id,
                    EditalItem.numero_item == item_data['numero_item']
                ).first()

                if not item_existente:
                    novo_item = EditalItem(
                        edital_id=edital.id,
                        numero_item=item_data['numero_item'],
                        descricao=item_data['descricao'],
                        unidade_medida=item_data['unidade_medida'],
                        quantidade=item_data['quantidade'],
                        valor_unitario_estimado=item_data['valor_unitario_estimado'],
                        valor_total_estimado=item_data['valor_total_estimado'],
                        codigo_item=item_data['codigo_item'],
                        tipo_beneficio=item_data['tipo_beneficio'],
                    )
                    db.add(novo_item)

        if edital:
            db.commit()
            print(f"[PNCP-ITENS] Itens salvos no banco para edital {edital.numero}")

        return {
            "success": True,
            "total_itens": len(itens_processados),
            "itens": itens_processados,
            "edital_id": edital.id if edital else None
        }

    except requests.exceptions.RequestException as e:
        print(f"[PNCP-ITENS] Erro na requisição: {e}")
        return {
            "success": False,
            "error": f"Erro ao buscar itens no PNCP: {str(e)}"
        }
    except Exception as e:
        print(f"[PNCP-ITENS] Erro: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": f"Erro: {str(e)}"
        }
    finally:
        db.close()


def tool_buscar_arquivos_edital_pncp(edital_id: str = None, cnpj: str = None, ano: int = None, seq: int = None, user_id: str = None) -> Dict[str, Any]:
    """
    Busca os arquivos/documentos de um edital na API do PNCP.

    Args:
        edital_id: ID do edital no banco (se já existe)
        cnpj: CNPJ do órgão (sem formatação)
        ano: Ano da compra
        seq: Sequencial da compra
        user_id: ID do usuário

    Returns:
        Dict com arquivos encontrados e URLs para download
    """
    db = get_db()
    try:
        edital = None

        # Se passou edital_id, buscar dados do PNCP do edital
        if edital_id:
            edital = db.query(Edital).filter(Edital.id == edital_id).first()
            if edital:
                cnpj = edital.cnpj_orgao
                ano = edital.ano_compra
                seq = edital.seq_compra

        if not cnpj or not ano or not seq:
            return {
                "success": False,
                "error": "Dados insuficientes para buscar arquivos (cnpj, ano, seq)"
            }

        print(f"[PNCP-ARQUIVOS] Buscando arquivos: CNPJ={cnpj}, Ano={ano}, Seq={seq}")

        # API de arquivos do PNCP
        # Formato: /api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos
        url_arquivos = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos"

        response = requests.get(
            url_arquivos,
            timeout=30,
            headers={"Accept": "application/json"}
        )

        if response.status_code == 404:
            return {
                "success": True,
                "arquivos": [],
                "message": "Nenhum arquivo encontrado para este edital"
            }

        response.raise_for_status()
        arquivos_api = response.json()

        print(f"[PNCP-ARQUIVOS] Encontrados {len(arquivos_api)} arquivos")

        arquivos_processados = []
        for arq in arquivos_api:
            # O campo correto é 'sequencialDocumento' (não 'sequencialArquivo')
            sequencial = arq.get('sequencialDocumento') or arq.get('sequencialArquivo') or 1

            # URL para download direto do arquivo
            url_download = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos/{sequencial}"

            arquivo_data = {
                "sequencial": sequencial,
                "titulo": arq.get('titulo', f'Documento {sequencial}'),
                "tipo": arq.get('tipoDocumentoNome', 'Documento'),
                "url": arq.get('uri', url_download),
                "url_download": url_download,
            }
            arquivos_processados.append(arquivo_data)

        # Identificar o arquivo principal do edital (geralmente o primeiro ou que contém "edital" no título)
        arquivo_edital = None
        for arq in arquivos_processados:
            titulo_lower = arq['titulo'].lower()
            tipo_lower = arq.get('tipo', '').lower()
            if any(termo in titulo_lower or termo in tipo_lower for termo in [
                'edital', 'pregão', 'pregao', 'pe ', 'termo de referência', 'termo de referencia',
                'tr ', 'instrumento convocatório', 'instrumento convocatorio',
            ]):
                arquivo_edital = arq
                break

        # Se não encontrou por título/tipo, tentar Termo de Referência antes do primeiro
        if not arquivo_edital and arquivos_processados:
            arquivo_edital = arquivos_processados[0]

        return {
            "success": True,
            "total_arquivos": len(arquivos_processados),
            "arquivos": arquivos_processados,
            "arquivo_edital": arquivo_edital,
            "edital_id": edital.id if edital else None
        }

    except requests.exceptions.RequestException as e:
        print(f"[PNCP-ARQUIVOS] Erro na requisição: {e}")
        return {
            "success": False,
            "error": f"Erro ao buscar arquivos no PNCP: {str(e)}"
        }
    except Exception as e:
        print(f"[PNCP-ARQUIVOS] Erro: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": f"Erro: {str(e)}"
        }
    finally:
        db.close()


def tool_baixar_pdf_pncp(cnpj: str, ano: int, seq: int, sequencial_arquivo: int = 1, user_id: str = None, edital_id: str = None) -> Dict[str, Any]:
    """
    Baixa um arquivo PDF específico do PNCP.

    Args:
        cnpj: CNPJ do órgão
        ano: Ano da compra
        seq: Sequencial da compra
        sequencial_arquivo: Número sequencial do arquivo (padrão: 1)
        user_id: ID do usuário (para salvar na pasta correta)
        edital_id: ID do edital no banco (opcional, para vincular)

    Returns:
        Dict com caminho do arquivo baixado
    """
    import os
    from config import UPLOAD_FOLDER

    try:
        # URL de download do PNCP
        url_download = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq}/arquivos/{sequencial_arquivo}"

        print(f"[PNCP-DOWNLOAD] Baixando: {url_download}")

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/pdf, application/octet-stream, */*'
        }

        response = requests.get(url_download, headers=headers, timeout=60, allow_redirects=True)
        response.raise_for_status()

        # Determinar nome do arquivo
        content_disp = response.headers.get('Content-Disposition', '')
        if 'filename=' in content_disp:
            filename = content_disp.split('filename=')[1].strip('"\'')
        else:
            filename = f"edital_{cnpj}_{ano}_{seq}.pdf"

        # Sanitizar nome do arquivo
        filename = re.sub(r'[^\w\-_\.]', '_', filename)

        # Criar diretório de destino
        if user_id:
            upload_dir = os.path.join(UPLOAD_FOLDER, user_id, 'editais')
        else:
            upload_dir = os.path.join(UPLOAD_FOLDER, 'editais')
        os.makedirs(upload_dir, exist_ok=True)

        # Salvar arquivo bruto temporariamente
        import zipfile, tempfile
        raw_path = os.path.join(upload_dir, filename)
        with open(raw_path, 'wb') as f:
            f.write(response.content)

        # Detectar se é ZIP e extrair PDF do edital de dentro
        if zipfile.is_zipfile(raw_path):
            print(f"[PNCP-DOWNLOAD] Arquivo é ZIP, extraindo PDF do edital...")
            all_pdfs = []  # lista de (path, size, name)

            with zipfile.ZipFile(raw_path, 'r') as zf:
                # Extrair PDFs diretos
                for name in zf.namelist():
                    if name.lower().endswith('.pdf'):
                        zf.extract(name, upload_dir)
                        fpath = os.path.join(upload_dir, name)
                        all_pdfs.append((fpath, os.path.getsize(fpath), os.path.basename(name).lower()))

                # Extrair ZIPs aninhados e buscar PDFs dentro
                for name in zf.namelist():
                    if name.lower().endswith('.zip'):
                        zf.extract(name, upload_dir)
                        nested_zip = os.path.join(upload_dir, name)
                        if zipfile.is_zipfile(nested_zip):
                            with zipfile.ZipFile(nested_zip, 'r') as zf2:
                                for name2 in zf2.namelist():
                                    if name2.lower().endswith('.pdf'):
                                        zf2.extract(name2, upload_dir)
                                        fpath2 = os.path.join(upload_dir, name2)
                                        all_pdfs.append((fpath2, os.path.getsize(fpath2), os.path.basename(name2).lower()))
                        try:
                            os.remove(nested_zip)
                        except OSError:
                            pass

            if all_pdfs:
                # Priorizar: arquivo com "edital" no nome > maior PDF
                edital_pdfs = [p for p in all_pdfs if 'edital' in p[2] and 'anexo' not in p[2] and 'termo' not in p[2] and 'minuta' not in p[2]]
                if edital_pdfs:
                    best = max(edital_pdfs, key=lambda x: x[1])
                else:
                    best = max(all_pdfs, key=lambda x: x[1])

                # Remover os outros PDFs extraídos
                for p in all_pdfs:
                    if p[0] != best[0]:
                        try:
                            os.remove(p[0])
                        except OSError:
                            pass

                # Mover para upload_dir raiz com nome limpo
                pdf_filename = re.sub(r'[^\w\-_\.]', '_', os.path.basename(best[0]))
                final_path = os.path.join(upload_dir, pdf_filename)
                if best[0] != final_path:
                    if os.path.exists(final_path):
                        os.remove(final_path)
                    os.rename(best[0], final_path)
                filepath = final_path
                filename = pdf_filename

                # Limpar subpastas criadas pela extração
                for p in all_pdfs:
                    parent = os.path.dirname(p[0])
                    if parent != upload_dir:
                        try:
                            os.removedirs(parent)
                        except OSError:
                            pass

                # Remover ZIP original
                try:
                    os.remove(raw_path)
                except OSError:
                    pass
                print(f"[PNCP-DOWNLOAD] PDF do edital extraído: {filepath} ({best[1]/1024:.1f} KB, de {len(all_pdfs)} PDFs encontrados)")
            else:
                filepath = raw_path
                print(f"[PNCP-DOWNLOAD] ZIP sem PDF dentro, mantendo ZIP: {filepath}")
        else:
            # Arquivo já é PDF (ou outro formato)
            if not filename.lower().endswith('.pdf'):
                filename += '.pdf'
                new_path = os.path.join(upload_dir, filename)
                os.rename(raw_path, new_path)
                filepath = new_path
            else:
                filepath = raw_path

        filesize = os.path.getsize(filepath)
        print(f"[PNCP-DOWNLOAD] Salvo: {filepath} ({filesize/1024:.1f} KB)")

        return {
            "success": True,
            "filepath": filepath,
            "filename": filename,
            "filesize": filesize,
            "url": url_download
        }

    except requests.exceptions.RequestException as e:
        print(f"[PNCP-DOWNLOAD] Erro ao baixar: {e}")
        return {
            "success": False,
            "error": f"Erro ao baixar arquivo do PNCP: {str(e)}"
        }
    except Exception as e:
        print(f"[PNCP-DOWNLOAD] Erro: {e}")
        return {
            "success": False,
            "error": f"Erro: {str(e)}"
        }


# ==================== SPRINT 1 - FUNCIONALIDADE 4: BUSCAR PREÇOS NO PNCP ====================

def tool_buscar_precos_pncp(termo: str, meses: int = 12, user_id: str = None) -> Dict[str, Any]:
    """
    Busca preços de contratos no PNCP para alimentar base de preços históricos.

    Args:
        termo: Termo de busca (ex: "hematologia", "analisador bioquímico")
        meses: Período de busca em meses (padrão: 12)
        user_id: ID do usuário

    Returns:
        Dict com contratos encontrados, preços e estatísticas
    """
    from datetime import datetime, timedelta

    print(f"[PNCP-PRECOS] Buscando preços de '{termo}' nos últimos {meses} meses...")

    data_inicio = (datetime.now() - timedelta(days=meses * 30)).strftime("%Y-%m-%d")
    data_fim = datetime.now().strftime("%Y-%m-%d")

    contratos = []
    precos = []

    # Método 1: Tentar API oficial do PNCP para contratos
    try:
        url_contratos = "https://pncp.gov.br/api/consulta/v1/contratos"
        params = {
            "q": termo,
            "dataInicial": data_inicio,
            "dataFinal": data_fim,
            "pagina": 1,
            "tamanhoPagina": 50
        }

        response = requests.get(url_contratos, params=params, timeout=30)

        if response.status_code == 200:
            data = response.json()

            for item in data.get("data", data.get("items", [])):
                valor = item.get("valorInicial") or item.get("valor") or item.get("valorContrato")
                if valor:
                    contrato = {
                        "id": item.get("id"),
                        "numero": item.get("numeroContrato") or item.get("numero"),
                        "objeto": item.get("objetoContrato") or item.get("objeto") or item.get("description"),
                        "orgao": item.get("nomeOrgao") or item.get("orgao_nome"),
                        "cnpj_orgao": item.get("cnpjOrgao") or item.get("orgao_cnpj"),
                        "fornecedor": item.get("nomeRazaoSocialFornecedor") or item.get("fornecedor_nome"),
                        "cnpj_fornecedor": item.get("cnpjCpfFornecedor") or item.get("fornecedor_cnpj"),
                        "valor": float(valor),
                        "data_assinatura": item.get("dataAssinatura") or item.get("data_assinatura"),
                        "data_publicacao": item.get("dataPublicacaoPncp") or item.get("data_publicacao"),
                        "uf": item.get("uf"),
                        "municipio": item.get("municipio_nome"),
                        "modalidade": item.get("modalidadeLicitacao") or item.get("modalidade"),
                        "url_pncp": f"https://pncp.gov.br/app/contratos/{item.get('id', '')}" if item.get('id') else None,
                        "fonte": "pncp_api"
                    }
                    contratos.append(contrato)
                    precos.append(float(valor))

            if contratos:
                print(f"[PNCP-PRECOS] API PNCP retornou {len(contratos)} contratos")

    except Exception as e:
        print(f"[PNCP-PRECOS] Erro na API do PNCP: {e}")

    # Método 2: Buscar via scraper web se API não retornou resultados
    if not contratos:
        try:
            search_query = f"site:pncp.gov.br contrato {termo} preço valor"
            print(f"[PNCP-PRECOS] Buscando via scraper web: {search_query}")

            raw_results = _web_search(search_query, 20)

            import re
            for result in raw_results:
                titulo = result.get('title', '')
                link = result.get('link', '')
                snippet = result.get('snippet', '')

                # Tentar extrair valor do snippet
                valores_encontrados = re.findall(r'R\$\s*([\d.,]+)', snippet)
                if valores_encontrados:
                    try:
                        valor_str = valores_encontrados[0].replace('.', '').replace(',', '.')
                        valor = float(valor_str)
                        if valor > 1000:  # Ignorar valores muito pequenos
                            contrato = {
                                "titulo": titulo,
                                "objeto": snippet[:200],
                                "valor": valor,
                                "url_pncp": link,
                                "fonte": "scraper_web"
                            }
                            contratos.append(contrato)
                            precos.append(valor)
                    except ValueError:
                        pass

            if contratos:
                print(f"[PNCP-PRECOS] Scraper web retornou {len(contratos)} resultados com preços")

        except Exception as e:
            print(f"[PNCP-PRECOS] Erro no scraper web: {e}")

    # Calcular estatísticas
    if not contratos:
        return {
            "success": False,
            "error": f"Não foram encontrados preços para '{termo}' no PNCP",
            "termo": termo,
            "periodo_meses": meses
        }

    # Estatísticas de preços
    preco_minimo = min(precos)
    preco_maximo = max(precos)
    preco_medio = sum(precos) / len(precos)
    preco_mediano = sorted(precos)[len(precos) // 2]

    # Agrupar por fornecedor
    fornecedores = {}
    for c in contratos:
        fornecedor = c.get("fornecedor") or c.get("titulo", "Desconhecido")
        if fornecedor not in fornecedores:
            fornecedores[fornecedor] = {"count": 0, "valores": []}
        fornecedores[fornecedor]["count"] += 1
        fornecedores[fornecedor]["valores"].append(c.get("valor", 0))

    # Top fornecedores
    top_fornecedores = sorted(
        [{"nome": k, "contratos": v["count"], "preco_medio": sum(v["valores"]) / len(v["valores"])}
         for k, v in fornecedores.items()],
        key=lambda x: x["contratos"],
        reverse=True
    )[:5]

    return {
        "success": True,
        "termo": termo,
        "periodo_meses": meses,
        "total_contratos": len(contratos),
        "contratos": contratos[:20],  # Limitar a 20 para resposta
        "estatisticas": {
            "preco_minimo": preco_minimo,
            "preco_maximo": preco_maximo,
            "preco_medio": preco_medio,
            "preco_mediano": preco_mediano
        },
        "top_fornecedores": top_fornecedores,
        "fonte": contratos[0].get("fonte", "pncp") if contratos else None
    }


# ==================== SPRINT 1 - FUNCIONALIDADE 5: HISTÓRICO DE PREÇOS ====================

def tool_historico_precos(termo: str = None, produto_id: int = None, user_id: str = None, empresa_id: str = None) -> Dict[str, Any]:
    """
    Consulta histórico de preços registrados no banco de dados local.

    Args:
        termo: Termo de busca (nome do produto/equipamento)
        produto_id: ID do produto específico
        user_id: ID do usuário

    Returns:
        Dict com histórico de preços, estatísticas e tendências
    """
    from database import SessionLocal
    from models import PrecoHistorico, Edital, Produto
    from sqlalchemy import func, desc

    db = SessionLocal()

    try:
        # Query base
        query = db.query(PrecoHistorico)

        if produto_id:
            query = query.filter(PrecoHistorico.produto_id == produto_id)

        if user_id:
            query = query.filter(PrecoHistorico.empresa_id == empresa_id)

        # Se tem termo, buscar por objeto do edital ou produto
        if termo:
            query = query.join(Edital, PrecoHistorico.edital_id == Edital.id, isouter=True)
            query = query.filter(
                (Edital.objeto.ilike(f"%{termo}%")) |
                (PrecoHistorico.empresa_vencedora.ilike(f"%{termo}%"))
            )

        # Ordenar por data
        query = query.order_by(desc(PrecoHistorico.data_homologacao))

        registros = query.limit(50).all()

        if not registros:
            return {
                "success": False,
                "error": f"Nenhum histórico de preços encontrado para '{termo or 'todos'}'",
                "termo": termo
            }

        # Processar dados
        precos = []
        historico = []

        for r in registros:
            preco = r.preco_vencedor or r.nosso_preco
            if preco:
                precos.append(float(preco))
                historico.append({
                    "id": r.id,
                    "edital_id": r.edital_id,
                    "preco_vencedor": float(r.preco_vencedor) if r.preco_vencedor else None,
                    "nosso_preco": float(r.nosso_preco) if r.nosso_preco else None,
                    "empresa_vencedora": r.empresa_vencedora,
                    "resultado": r.resultado,
                    "data": r.data_homologacao.isoformat() if r.data_homologacao else None,
                    "fonte": r.fonte
                })

        # Estatísticas
        if precos:
            stats = {
                "preco_minimo": min(precos),
                "preco_maximo": max(precos),
                "preco_medio": sum(precos) / len(precos),
                "preco_mediano": sorted(precos)[len(precos) // 2],
                "total_registros": len(precos)
            }
        else:
            stats = {}

        return {
            "success": True,
            "termo": termo,
            "total": len(historico),
            "historico": historico,
            "estatisticas": stats
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# ==================== SPRINT 1 - FUNCIONALIDADE 6: ANÁLISE DE CONCORRENTES ====================

def tool_listar_concorrentes(user_id: str = None) -> Dict[str, Any]:
    """
    Lista todos os concorrentes cadastrados no sistema.

    Returns:
        Dict com lista de concorrentes e estatísticas
    """
    from database import SessionLocal
    from models import Concorrente
    from sqlalchemy import desc

    db = SessionLocal()

    try:
        query = db.query(Concorrente).order_by(desc(Concorrente.editais_ganhos))
        concorrentes = query.all()

        if not concorrentes:
            return {
                "success": False,
                "error": "Nenhum concorrente cadastrado ainda",
                "dica": "Concorrentes são cadastrados automaticamente ao registrar resultados de editais"
            }

        lista = []
        for c in concorrentes:
            taxa = (c.editais_ganhos / c.editais_participados * 100) if c.editais_participados > 0 else 0
            lista.append({
                "id": c.id,
                "nome": c.nome,
                "cnpj": c.cnpj,
                "editais_participados": c.editais_participados,
                "editais_ganhos": c.editais_ganhos,
                "taxa_vitoria": round(taxa, 1),
                "preco_medio": float(c.preco_medio) if c.preco_medio else None
            })

        return {
            "success": True,
            "total": len(lista),
            "concorrentes": lista
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_analisar_concorrente(nome_concorrente: str, user_id: str = None) -> Dict[str, Any]:
    """
    Analisa um concorrente específico: histórico, taxa de vitória, preços.

    Args:
        nome_concorrente: Nome do concorrente
        user_id: ID do usuário

    Returns:
        Dict com análise detalhada do concorrente
    """
    from database import SessionLocal
    from models import Concorrente, ParticipacaoEdital, PrecoHistorico, Edital
    from sqlalchemy import desc

    db = SessionLocal()

    try:
        # Buscar concorrente
        concorrente = db.query(Concorrente).filter(
            Concorrente.nome.ilike(f"%{nome_concorrente}%")
        ).first()

        if not concorrente:
            return {
                "success": False,
                "error": f"Concorrente '{nome_concorrente}' não encontrado",
                "dica": "Use 'liste concorrentes' para ver os cadastrados"
            }

        # Buscar participações
        participacoes = db.query(ParticipacaoEdital).filter(
            ParticipacaoEdital.concorrente_id == concorrente.id
        ).order_by(desc(ParticipacaoEdital.created_at)).limit(20).all()

        historico = []
        precos = []
        vitorias = 0

        for p in participacoes:
            edital = db.query(Edital).filter(Edital.id == p.edital_id).first()
            if p.preco_proposto:
                precos.append(float(p.preco_proposto))
            if p.posicao_final == 1:
                vitorias += 1

            historico.append({
                "edital": edital.numero if edital else "N/A",
                "orgao": edital.orgao if edital else "N/A",
                "preco": float(p.preco_proposto) if p.preco_proposto else None,
                "posicao": p.posicao_final,
                "venceu": p.posicao_final == 1
            })

        taxa_vitoria = (concorrente.editais_ganhos / concorrente.editais_participados * 100) if concorrente.editais_participados > 0 else 0

        return {
            "success": True,
            "concorrente": {
                "id": concorrente.id,
                "nome": concorrente.nome,
                "cnpj": concorrente.cnpj,
                "editais_participados": concorrente.editais_participados,
                "editais_ganhos": concorrente.editais_ganhos,
                "taxa_vitoria": round(taxa_vitoria, 1)
            },
            "estatisticas_precos": {
                "preco_minimo": min(precos) if precos else None,
                "preco_maximo": max(precos) if precos else None,
                "preco_medio": sum(precos) / len(precos) if precos else None
            },
            "historico_participacoes": historico
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# ==================== SPRINT 1 - FUNCIONALIDADE 7: RECOMENDAÇÃO DE PREÇOS ====================

def tool_recomendar_preco(termo: str, edital_id: int = None, user_id: str = None) -> Dict[str, Any]:
    """
    Recomenda faixa de preço baseada em histórico e análise de concorrentes.

    Args:
        termo: Termo/produto para buscar referências
        edital_id: ID do edital específico (opcional)
        user_id: ID do usuário

    Returns:
        Dict com recomendação de preço e justificativa
    """
    from database import SessionLocal
    from models import PrecoHistorico, Concorrente, Edital
    from sqlalchemy import desc

    db = SessionLocal()

    try:
        # 1. Buscar histórico de preços similar
        query = db.query(PrecoHistorico).join(
            Edital, PrecoHistorico.edital_id == Edital.id, isouter=True
        ).filter(
            Edital.objeto.ilike(f"%{termo}%")
        ).order_by(desc(PrecoHistorico.data_homologacao)).limit(20)

        registros = query.all()

        precos_vencedores = []
        precos_nossos = []
        concorrentes_frequentes = {}

        for r in registros:
            if r.preco_vencedor:
                precos_vencedores.append(float(r.preco_vencedor))
            if r.nosso_preco:
                precos_nossos.append(float(r.nosso_preco))
            if r.empresa_vencedora:
                if r.empresa_vencedora not in concorrentes_frequentes:
                    concorrentes_frequentes[r.empresa_vencedora] = 0
                concorrentes_frequentes[r.empresa_vencedora] += 1

        if not precos_vencedores:
            # Tentar buscar no PNCP
            resultado_pncp = tool_buscar_precos_pncp(termo, meses=12, user_id=user_id)
            if resultado_pncp.get("success"):
                stats = resultado_pncp.get("estatisticas", {})
                return {
                    "success": True,
                    "termo": termo,
                    "fonte": "pncp",
                    "recomendacao": {
                        "preco_minimo_sugerido": stats.get("preco_minimo", 0) * 0.95,
                        "preco_ideal": stats.get("preco_medio", 0) * 0.97,
                        "preco_maximo_sugerido": stats.get("preco_medio", 0),
                    },
                    "justificativa": f"Baseado em {resultado_pncp.get('total_contratos', 0)} contratos do PNCP",
                    "estatisticas_mercado": stats
                }
            else:
                return {
                    "success": False,
                    "error": f"Não há dados suficientes para recomendar preço para '{termo}'",
                    "dica": "Registre mais resultados de editais ou busque preços no PNCP"
                }

        # Calcular recomendação
        preco_medio_mercado = sum(precos_vencedores) / len(precos_vencedores)
        preco_minimo_mercado = min(precos_vencedores)

        # Estratégia: preço competitivo = média - 3% a 5%
        preco_ideal = preco_medio_mercado * 0.97
        preco_agressivo = preco_medio_mercado * 0.95
        preco_conservador = preco_medio_mercado * 0.99

        # Principal concorrente
        principal_concorrente = max(concorrentes_frequentes.items(), key=lambda x: x[1])[0] if concorrentes_frequentes else None

        return {
            "success": True,
            "termo": termo,
            "fonte": "historico_local",
            "recomendacao": {
                "preco_agressivo": round(preco_agressivo, 2),
                "preco_ideal": round(preco_ideal, 2),
                "preco_conservador": round(preco_conservador, 2)
            },
            "estatisticas_historico": {
                "preco_medio_vencedor": round(preco_medio_mercado, 2),
                "preco_minimo_vencedor": round(preco_minimo_mercado, 2),
                "total_registros": len(precos_vencedores)
            },
            "analise_concorrencia": {
                "principal_concorrente": principal_concorrente,
                "total_concorrentes": len(concorrentes_frequentes)
            },
            "justificativa": f"Baseado em {len(precos_vencedores)} registros históricos. Preço médio vencedor: R$ {preco_medio_mercado:,.2f}"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# ==================== SPRINT 1 - FUNCIONALIDADE 8: CLASSIFICAÇÃO DE EDITAIS ====================

def tool_classificar_edital(edital_id: int = None, texto_edital: str = None, user_id: str = None) -> Dict[str, Any]:
    """
    Classifica um edital em categorias mutuamente exclusivas.

    CV13-10 (Arnaldo Sprint 2 V8): antes retornava 'aluguel_simples + comodato +
    aluguel_reagentes + venda' tudo junto porque as listas compartilhavam keywords
    genericas ('locacao', 'aluguel', 'equipamento'). Agora:

    1. Le tambem o texto completo do PDF (EditalDocumento.texto_extraido) — antes
       so olhava objeto+numero (~200 chars).
    2. Usa frases compostas como sinais fortes (vencem keywords soltas).
    3. Aplica regras hierarquicas de desempate: comodato > aluguel_reagentes >
       aluguel_simples > venda > consumo_* (do mais especifico ao mais generico).
    4. Threshold de confianca minimo — se nenhum sinal forte, devolve 'outros'.
    5. Retorna `categorias_secundarias` (com score > 30% da principal) para
       transparencia, mas a UI mostra so a principal.
    """
    from models import get_db, Edital, EditalDocumento
    import re as _re

    # Sinais FORTES (frases compostas) — peso 5 cada.
    SINAIS_FORTES = {
        "comodato": [
            "em comodato", "regime de comodato", "cessao de uso",
            "cessão de uso", "contrato de comodato", "sem onus", "sem ônus",
        ],
        "aluguel_reagentes": [
            "locacao de equipamento com fornecimento", "locação de equipamento com fornecimento",
            "aluguel de equipamento com fornecimento de reagentes",
            "fornecimento de reagentes e cessao", "fornecimento de reagentes e cessão",
            "kit reagente", "kits reagentes",
            "com fornecimento de reagentes", "com fornecimento dos reagentes",
            "fornecimento dos insumos e reagentes",
        ],
        "aluguel_simples": [
            "locacao de equipamento", "locação de equipamento",
            "aluguel de equipamento", "locacao de aparelho", "locação de aparelho",
        ],
        "venda": [
            "aquisicao de equipamento", "aquisição de equipamento",
            "aquisicao de bens", "aquisição de bens",
            "compra de equipamento", "fornecimento de equipamento",
        ],
        "consumo_reagentes": [
            "reagentes laboratoriais", "kits para diagnostico", "kits para diagnóstico",
            "tiras reagentes", "consumo de reagentes",
        ],
        "insumos_hospitalares": [
            "material medico hospitalar", "material médico hospitalar",
            "insumos hospitalares", "material descartavel hospitalar",
            "material descartável hospitalar",
        ],
        "insumos_laboratoriais": [
            "material laboratorial", "insumos laboratoriais",
            "vidraria de laboratorio", "vidraria de laboratório",
        ],
    }

    # Sinais FRACOS (keywords soltas) — peso 1. So contam quando nao ha sinal forte
    # ou no desempate dentro de categorias proximas.
    SINAIS_FRACOS = {
        "comodato": ["comodato", "cessao", "cessão"],
        "aluguel_reagentes": [],  # depende dos compostos pra nao confundir com aluguel_simples
        "aluguel_simples": ["locacao", "locação", "aluguel"],
        "venda": ["aquisicao", "aquisição", "compra"],
        "consumo_reagentes": ["reagentes", "kits", "testes"],
        "insumos_hospitalares": ["descartaveis", "descartáveis"],
        "insumos_laboratoriais": ["vidraria"],
    }

    # Hierarquia de desempate (mais especifico vence em caso de empate de score).
    # CV13-10: ordem de desempate quando os scores empatam. "consumo_reagentes"
    # vem antes de "venda" porque "aquisicao de reagentes" eh quase sempre
    # consumo, nao compra de bem permanente.
    PRIORIDADE = [
        "comodato", "aluguel_reagentes", "aluguel_simples",
        "consumo_reagentes", "insumos_hospitalares", "insumos_laboratoriais",
        "venda",
    ]

    # === Coleta de texto ===
    texto = ""
    edital_info = None

    if edital_id:
        db = get_db()
        try:
            edital = db.query(Edital).filter(Edital.id == edital_id).first()
            if edital:
                edital_info = {"id": edital.id, "numero": edital.numero, "objeto": edital.objeto}
                # 1) objeto + numero (sempre disponivel)
                texto = f"{edital.objeto or ''} {edital.numero or ''}"
                # 2) CV13-10 + CV13-9: ler tambem texto extraido do PDF se houver
                doc = db.query(EditalDocumento).filter(
                    EditalDocumento.edital_id == edital.id,
                    EditalDocumento.tipo == 'edital_principal',
                    EditalDocumento.texto_extraido != None,
                ).first()
                if doc and doc.texto_extraido:
                    # Limitar a 30k chars pra nao explodir tempo de regex
                    texto += " " + doc.texto_extraido[:30000]
        finally:
            db.close()

    if texto_edital:
        texto = texto_edital

    if not texto.strip():
        return {"success": False, "error": "Nenhum texto de edital fornecido"}

    texto_lower = texto.lower()
    # Normalizar espacos para casar frases compostas mesmo com quebra de linha
    texto_norm = _re.sub(r"\s+", " ", texto_lower)

    # === Scoring ===
    scores = {}
    for cat in SINAIS_FORTES.keys():
        s = 0
        for frase in SINAIS_FORTES[cat]:
            if frase in texto_norm:
                s += 5
        for kw in SINAIS_FRACOS.get(cat, []):
            # Word boundary pra nao casar substring (ex: 'venda' dentro de 'revenda')
            if _re.search(rf"\b{_re.escape(kw)}\b", texto_norm):
                s += 1
        if s > 0:
            scores[cat] = s

    if not scores:
        return {
            "success": True,
            "edital": edital_info,
            "categoria": "outros",
            "confianca": 0,
            "categorias_secundarias": [],
            "justificativa": "Nenhum sinal forte ou fraco identificado no texto.",
        }

    # === Desempate hierarquico ===
    # CV13-10: regras de DOMINANCIA — categoria mais especifica sequestra a mais
    # generica quando ambas tem sinal FORTE (>=5). Senao, aluguel_simples vence
    # aluguel_reagentes por causa do +1 dos sinais fracos genericos.
    DOMINANCIA = [
        ("aluguel_reagentes", "aluguel_simples"),  # se reagentes tem sinal forte, vence simples
        ("comodato", "aluguel_simples"),           # comodato eh especifico, simples eh generico
        ("comodato", "venda"),                     # comodato vence venda quando coexistem
        ("consumo_reagentes", "venda"),            # consumo eh subset de venda
    ]
    for especifica, generica in DOMINANCIA:
        if especifica in scores and generica in scores and scores[especifica] >= 5:
            # Anular o ganho fraco da generica para nao competir
            scores[generica] = min(scores[generica], scores[especifica] - 1)

    score_max = max(scores.values())
    empatados = [c for c, s in scores.items() if s == score_max]
    if len(empatados) > 1:
        categoria_principal = min(empatados, key=lambda c: PRIORIDADE.index(c) if c in PRIORIDADE else 999)
    else:
        categoria_principal = empatados[0]

    # === Confianca ===
    # Sinal forte (>= 5) = alta confianca. So sinais fracos = baixa.
    s_principal = scores[categoria_principal]
    if s_principal >= 5:
        confianca = min(60 + s_principal * 4, 100)
    else:
        confianca = min(s_principal * 15, 50)

    # === Secundarias (apenas as com score >= 30% da principal) ===
    threshold = s_principal * 0.3
    secundarias = [
        {"categoria": c, "score": s}
        for c, s in sorted(scores.items(), key=lambda x: -x[1])
        if c != categoria_principal and s >= threshold
    ]

    return {
        "success": True,
        "edital": edital_info,
        "categoria": categoria_principal,
        "confianca": round(confianca, 1),
        "score": s_principal,
        "todas_categorias": scores,
        "categorias_secundarias": secundarias,
        "justificativa": (
            f"Categoria '{categoria_principal}' identificada com score {s_principal} "
            f"(sinais fortes valem 5, fracos valem 1). Confianca {round(confianca,1)}%."
            + (f" Secundarias: {', '.join(s['categoria'] for s in secundarias)}." if secundarias else "")
        ),
    }


# ==================== SPRINT 1 - FUNCIONALIDADE 9: VERIFICAR COMPLETUDE DO PRODUTO ====================

def tool_verificar_completude_produto(produto_id: str = None, nome_produto: str = None, user_id: str = None) -> Dict[str, Any]:
    """
    Verifica completude do produto: dados básicos + especificações vs máscara da subclasse.

    Args:
        produto_id: ID do produto
        nome_produto: Nome do produto (busca por ILIKE)
        user_id: ID do usuário

    Returns:
        Dict com campos_basicos, mascara_check, percentuais e recomendações
    """
    from database import SessionLocal
    from models import Produto, ProdutoEspecificacao, SubclasseProduto
    import json

    db = SessionLocal()

    try:
        # Buscar produto
        if produto_id:
            produto = db.query(Produto).filter(Produto.id == produto_id).first()
        elif nome_produto:
            produto = db.query(Produto).filter(
                (Produto.nome.ilike(f"%{nome_produto}%")) |
                (Produto.modelo.ilike(f"%{nome_produto}%"))
            ).first()
        else:
            return {"success": False, "error": "Informe o ID ou nome do produto"}

        if not produto:
            return {"success": False, "error": f"Produto não encontrado: {nome_produto or produto_id}"}

        # Campos básicos
        campos_basicos = [
            {"campo": "Nome", "preenchido": bool(produto.nome), "valor": produto.nome or ""},
            {"campo": "Fabricante", "preenchido": bool(produto.fabricante), "valor": produto.fabricante or ""},
            {"campo": "Modelo", "preenchido": bool(produto.modelo), "valor": produto.modelo or ""},
            {"campo": "NCM", "preenchido": bool(produto.ncm and produto.ncm.strip()), "valor": produto.ncm or ""},
            {"campo": "SKU / Codigo Interno", "preenchido": bool(produto.codigo_interno), "valor": produto.codigo_interno or ""},
            {"campo": "Subclasse", "preenchido": bool(produto.subclasse_id), "valor": ""},
            {"campo": "Registro ANVISA", "preenchido": bool(produto.registro_anvisa), "valor": produto.registro_anvisa or ""},
        ]

        # Resolver nome da subclasse
        subclasse_nome = None
        mascara_check = []
        if produto.subclasse_id:
            sub = db.query(SubclasseProduto).filter(SubclasseProduto.id == produto.subclasse_id).first()
            if sub:
                subclasse_nome = sub.nome
                campos_basicos[5]["valor"] = sub.nome

                # Parse máscara
                mascara_raw = sub.campos_mascara
                mascara = []
                if mascara_raw:
                    try:
                        if isinstance(mascara_raw, str):
                            mascara_raw = json.loads(mascara_raw)
                        if isinstance(mascara_raw, str):
                            mascara_raw = json.loads(mascara_raw)
                        if isinstance(mascara_raw, list):
                            mascara = mascara_raw
                    except (json.JSONDecodeError, TypeError):
                        pass

                # Buscar specs do produto
                specs = db.query(ProdutoEspecificacao).filter(
                    ProdutoEspecificacao.produto_id == produto.id
                ).all()
                specs_map = {s.nome_especificacao.lower(): s.valor or "" for s in specs}

                # Comparar cada campo da máscara
                for m in mascara:
                    campo_nome = str(m.get("campo") or m.get("nome") or "")
                    if not campo_nome:
                        continue
                    valor = specs_map.get(campo_nome.lower(), "")
                    preenchido = bool(valor.strip()) and valor.strip() != "-"
                    mascara_check.append({
                        "campo": campo_nome,
                        "preenchido": preenchido,
                        "valor": valor,
                        "unidade": str(m.get("unidade", "") or ""),
                    })

        # Calcular percentuais
        basicos_preenchidos = sum(1 for c in campos_basicos if c["preenchido"])
        pct_basicos = round((basicos_preenchidos / len(campos_basicos)) * 100)

        mascara_preenchidos = sum(1 for c in mascara_check if c["preenchido"])
        # Sem mascara (produto sem subclasse ou subclasse sem campos_mascara):
        # especificacoes nao sao avaliaveis -> None (UI mostra "N/A"), nao 100% falso.
        mascara_avaliavel = bool(mascara_check)
        pct_mascara = round((mascara_preenchidos / len(mascara_check)) * 100) if mascara_avaliavel else None

        total = len(campos_basicos) + len(mascara_check)
        total_ok = basicos_preenchidos + mascara_preenchidos
        pct_geral = round((total_ok / total) * 100) if total > 0 else 0

        # Status
        if pct_geral >= 90:
            status = "completo"
        elif pct_geral >= 70:
            status = "quase_completo"
        elif pct_geral >= 40:
            status = "incompleto"
        else:
            status = "muito_incompleto"

        # Recomendações
        recomendacoes = []
        for c in campos_basicos:
            if not c["preenchido"]:
                recomendacoes.append(f"Preencha o campo '{c['campo']}'")
        faltantes_mascara = [c["campo"] for c in mascara_check if not c["preenchido"]]
        if faltantes_mascara:
            if len(faltantes_mascara) <= 5:
                for f in faltantes_mascara:
                    recomendacoes.append(f"Preencha especificacao '{f}'")
            else:
                recomendacoes.append(f"{len(faltantes_mascara)} especificacoes da mascara nao preenchidas")

        return {
            "success": True,
            "produto": {
                "id": produto.id,
                "nome": produto.nome,
                "fabricante": produto.fabricante,
                "modelo": produto.modelo,
                "categoria": produto.categoria,
                "subclasse_id": produto.subclasse_id,
            },
            "subclasse_nome": subclasse_nome,
            "campos_basicos": campos_basicos,
            "mascara_check": mascara_check,
            "completude": {
                "percentual_geral": pct_geral,
                "percentual_basicos": pct_basicos,
                "percentual_mascara": pct_mascara,
                "mascara_avaliavel": mascara_avaliavel,
                "status": status,
            },
            "recomendacoes": recomendacoes,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# ==================== SPRINT 2: ALERTAS E MONITORAMENTO ====================

from models import Alerta, Monitoramento, Notificacao, PreferenciasNotificacao
from datetime import timedelta


def formatar_tempo(minutos: int) -> str:
    """Converte minutos para texto legível."""
    if minutos >= 1440:
        dias = minutos // 1440
        return f"{dias} dia(s)" if dias > 1 else "1 dia"
    elif minutos >= 60:
        horas = minutos // 60
        return f"{horas} hora(s)" if horas > 1 else "1 hora"
    else:
        return f"{minutos} minutos"


def formatar_tempo_restante(delta: timedelta) -> str:
    """Formata timedelta para texto legível."""
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "Já passou"

    dias = total_seconds // 86400
    horas = (total_seconds % 86400) // 3600
    minutos = (total_seconds % 3600) // 60

    partes = []
    if dias > 0:
        partes.append(f"{dias}d")
    if horas > 0:
        partes.append(f"{horas}h")
    if minutos > 0 and dias == 0:
        partes.append(f"{minutos}min")

    return " ".join(partes) if partes else "menos de 1 minuto"


def tool_configurar_alertas(user_id: str, empresa_id: str = None, edital_numero: str = None, tempos_minutos: List[int] = None,
                            tipo: str = "abertura", canais: List[str] = None) -> Dict:
    """
    Configura alertas de prazo para um edital.

    Args:
        user_id: ID do usuário
        edital_numero: Número do edital (ex: PE-001/2026)
        tempos_minutos: Lista de tempos em minutos antes do evento [4320, 1440, 60, 15]
        tipo: Tipo de alerta (abertura, impugnacao, recursos, proposta)
        canais: Lista de canais ["email", "push"]
    """
    db = get_db()
    try:
        # Buscar edital
        edital = db.query(Edital).filter(
            Edital.numero.ilike(f"%{edital_numero}%"),
            Edital.empresa_id == empresa_id
        ).first()

        if not edital:
            return {"success": False, "error": f"Edital '{edital_numero}' não encontrado."}

        # Determinar data base conforme tipo
        if tipo == "abertura":
            data_evento = edital.data_abertura
        elif tipo == "impugnacao":
            data_evento = edital.data_limite_impugnacao
        elif tipo == "recursos":
            data_evento = edital.data_recursos
        elif tipo == "proposta":
            data_evento = edital.data_limite_proposta
        else:
            data_evento = edital.data_abertura

        if not data_evento:
            return {"success": False, "error": f"Edital não possui data de {tipo} cadastrada."}

        # Buscar preferências do usuário
        prefs = db.query(PreferenciasNotificacao).filter(
            PreferenciasNotificacao.user_id == user_id
        ).first()

        # Tempos padrão se não especificado
        if not tempos_minutos:
            tempos_minutos = prefs.alertas_padrao if prefs else [4320, 1440, 60, 15]

        # Canais padrão
        if not canais:
            canais = ["email", "push"]

        alertas_criados = []
        agora = datetime.now()

        for tempo in tempos_minutos:
            data_disparo = data_evento - timedelta(minutes=tempo)

            # Não criar alerta se já passou
            if data_disparo <= agora:
                continue

            # Verificar se já existe alerta similar
            existente = db.query(Alerta).filter(
                Alerta.empresa_id == empresa_id,
                Alerta.edital_id == edital.id,
                Alerta.tipo == tipo,
                Alerta.tempo_antes_minutos == tempo,
                Alerta.status == 'agendado'
            ).first()

            if existente:
                continue

            alerta = Alerta(
                user_id=user_id,
                edital_id=edital.id,
                tipo=tipo,
                data_disparo=data_disparo,
                tempo_antes_minutos=tempo,
                status='agendado',  # Explicitamente definir status
                canal_email="email" in canais,
                canal_push="push" in canais,
                titulo=f"⏰ {edital.numero} - {formatar_tempo(tempo)} para {tipo}",
                mensagem=f"O edital {edital.numero} - {edital.orgao} tem {tipo} em {formatar_tempo(tempo)}."
            )
            db.add(alerta)
            alertas_criados.append({
                "tempo_antes": tempo,
                "tempo_formatado": formatar_tempo(tempo),
                "data_disparo": data_disparo.isoformat(),
                "canais": canais
            })

        db.commit()

        return {
            "success": True,
            "edital": {
                "numero": edital.numero,
                "orgao": edital.orgao,
                "data_evento": data_evento.isoformat(),
                "tipo_evento": tipo
            },
            "alertas_criados": alertas_criados,
            "total_criados": len(alertas_criados)
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_listar_alertas(user_id: str, empresa_id: str = None, apenas_agendados: bool = True,
                        periodo_dias: int = 30) -> Dict:
    """
    Lista alertas do usuário.

    Args:
        user_id: ID do usuário
        apenas_agendados: Se True, lista apenas alertas agendados
        periodo_dias: Período em dias para buscar alertas
    """
    db = get_db()
    try:
        data_limite = datetime.now() + timedelta(days=periodo_dias)

        query = db.query(Alerta).filter(
            Alerta.empresa_id == empresa_id
        )

        if apenas_agendados:
            query = query.filter(
                Alerta.status == 'agendado',
                Alerta.data_disparo >= datetime.now(),
                Alerta.data_disparo <= data_limite
            )

        alertas = query.order_by(Alerta.data_disparo).all()

        # Agrupar por edital
        editais_alertas = {}
        for alerta in alertas:
            edital = db.query(Edital).filter(Edital.id == alerta.edital_id).first()
            if not edital:
                continue

            if edital.id not in editais_alertas:
                tempo_restante = edital.data_abertura - datetime.now() if edital.data_abertura else None
                editais_alertas[edital.id] = {
                    "edital": {
                        "id": edital.id,
                        "numero": edital.numero,
                        "orgao": edital.orgao,
                        "objeto": edital.objeto[:100] + "..." if edital.objeto and len(edital.objeto) > 100 else edital.objeto,
                        "data_abertura": edital.data_abertura.isoformat() if edital.data_abertura else None,
                        "tempo_restante": formatar_tempo_restante(tempo_restante) if tempo_restante else None,
                        "status": edital.status
                    },
                    "alertas": []
                }

            editais_alertas[edital.id]["alertas"].append({
                "id": alerta.id,
                "tipo": alerta.tipo,
                "tempo_antes": formatar_tempo(alerta.tempo_antes_minutos) if alerta.tempo_antes_minutos else None,
                "data_disparo": alerta.data_disparo.isoformat() if alerta.data_disparo else None,
                "status": alerta.status,
                "canais": {
                    "email": alerta.canal_email,
                    "push": alerta.canal_push
                }
            })

        return {
            "success": True,
            "total_alertas": len(alertas),
            "total_editais": len(editais_alertas),
            "editais": list(editais_alertas.values())
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_dashboard_prazos(user_id: str, empresa_id: str = None, dias: int = 30) -> Dict:
    """
    Retorna dashboard de prazos com editais próximos.

    Args:
        user_id: ID do usuário
        dias: Quantidade de dias para frente a considerar
    """
    db = get_db()
    try:
        agora = datetime.now()
        data_limite = agora + timedelta(days=dias)

        # Buscar editais com data de abertura no período
        editais = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.data_abertura != None,
            Edital.data_abertura >= agora,
            Edital.data_abertura <= data_limite,
            Edital.status.in_(['novo', 'analisando', 'participando', 'proposta_enviada'])
        ).order_by(Edital.data_abertura).all()

        resultado = []
        for edital in editais:
            tempo_restante = edital.data_abertura - agora

            # Buscar alertas configurados
            alertas = db.query(Alerta).filter(
                Alerta.edital_id == edital.id,
                Alerta.empresa_id == empresa_id,
                Alerta.status == 'agendado'
            ).all()

            # Determinar urgência
            dias_restantes = tempo_restante.days
            if dias_restantes <= 1:
                urgencia = "critico"
                emoji = "🔴"
            elif dias_restantes <= 3:
                urgencia = "alto"
                emoji = "🟠"
            elif dias_restantes <= 7:
                urgencia = "medio"
                emoji = "🟡"
            else:
                urgencia = "normal"
                emoji = "🟢"

            resultado.append({
                "edital": {
                    "id": edital.id,
                    "numero": edital.numero,
                    "orgao": edital.orgao,
                    "objeto": edital.objeto[:80] + "..." if edital.objeto and len(edital.objeto) > 80 else edital.objeto,
                    "valor_referencia": float(edital.valor_referencia) if edital.valor_referencia else None,
                    "status": edital.status
                },
                "datas": {
                    "abertura": edital.data_abertura.isoformat() if edital.data_abertura else None,
                    "abertura_formatada": edital.data_abertura.strftime("%d/%m/%Y %H:%M") if edital.data_abertura else None,
                    "impugnacao": edital.data_limite_impugnacao.strftime("%d/%m/%Y %H:%M") if edital.data_limite_impugnacao else None,
                    "proposta": edital.data_limite_proposta.strftime("%d/%m/%Y %H:%M") if edital.data_limite_proposta else None
                },
                "tempo_restante": {
                    "texto": formatar_tempo_restante(tempo_restante),
                    "dias": tempo_restante.days,
                    "horas": tempo_restante.seconds // 3600
                },
                "urgencia": urgencia,
                "emoji": emoji,
                "alertas_configurados": len(alertas),
                "alertas": [formatar_tempo(a.tempo_antes_minutos) for a in alertas if a.tempo_antes_minutos]
            })

        # Estatísticas
        stats = {
            "total": len(resultado),
            "criticos": len([e for e in resultado if e["urgencia"] == "critico"]),
            "altos": len([e for e in resultado if e["urgencia"] == "alto"]),
            "medios": len([e for e in resultado if e["urgencia"] == "medio"]),
            "normais": len([e for e in resultado if e["urgencia"] == "normal"])
        }

        return {
            "success": True,
            "periodo_dias": dias,
            "data_consulta": agora.isoformat(),
            "estatisticas": stats,
            "editais": resultado
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_calendario_editais(user_id: str, empresa_id: str = None, mes: int = None, ano: int = None) -> Dict:
    """
    Retorna calendário de editais do mês.

    Args:
        user_id: ID do usuário
        mes: Mês (1-12), padrão = mês atual
        ano: Ano, padrão = ano atual
    """
    db = get_db()
    try:
        agora = datetime.now()
        if not mes:
            mes = agora.month
        if not ano:
            ano = agora.year

        # Início e fim do mês
        inicio = datetime(ano, mes, 1)
        if mes == 12:
            fim = datetime(ano + 1, 1, 1)
        else:
            fim = datetime(ano, mes + 1, 1)

        # Buscar editais no período
        editais = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.data_abertura != None,
            Edital.data_abertura >= inicio,
            Edital.data_abertura < fim
        ).order_by(Edital.data_abertura).all()

        # Organizar por dia
        calendario = {}
        for edital in editais:
            dia = edital.data_abertura.day
            if dia not in calendario:
                calendario[dia] = []

            calendario[dia].append({
                "numero": edital.numero,
                "orgao": edital.orgao[:30] + "..." if len(edital.orgao) > 30 else edital.orgao,
                "horario": edital.data_abertura.strftime("%H:%M"),
                "status": edital.status,
                "valor": float(edital.valor_referencia) if edital.valor_referencia else None
            })

        # Nomes dos meses
        meses = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
                 "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

        return {
            "success": True,
            "mes": mes,
            "ano": ano,
            "mes_nome": meses[mes],
            "total_editais": len(editais),
            "dias_com_editais": len(calendario),
            "calendario": calendario
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_configurar_monitoramento(user_id: str, empresa_id: str = None, termo: str = None, fontes: List[str] = None,
                                   ufs: List[str] = None, frequencia_horas: int = 4,
                                   score_minimo: int = 70, valor_minimo: float = None,
                                   valor_maximo: float = None) -> Dict:
    """
    Configura monitoramento automático de editais.

    Args:
        user_id: ID do usuário
        termo: Termo de busca (ex: "hematologia", "equipamento laboratorial")
        fontes: Lista de fontes ["pncp", "comprasnet", "bec"]
        ufs: Lista de UFs ["SP", "RJ"] ou None para todas
        frequencia_horas: Frequência de busca em horas
        score_minimo: Score mínimo para alertar
        valor_minimo: Valor mínimo do edital
        valor_maximo: Valor máximo do edital
    """
    db = get_db()
    try:
        # Verificar se já existe monitoramento similar
        existente = db.query(Monitoramento).filter(
            Monitoramento.empresa_id == empresa_id,
            Monitoramento.termo == termo.lower(),
            Monitoramento.ativo == True
        ).first()

        if existente:
            return {"success": False, "error": f"Já existe monitoramento ativo para '{termo}'."}

        # Criar monitoramento
        monitoramento = Monitoramento(
            user_id=user_id,
            termo=termo.lower(),
            fontes=fontes or ["pncp"],
            ufs=ufs,
            valor_minimo=valor_minimo,
            valor_maximo=valor_maximo,
            frequencia_horas=frequencia_horas,
            score_minimo_alerta=score_minimo,
            proximo_check=datetime.now() + timedelta(hours=frequencia_horas),
            notificar_email=True,
            notificar_push=True,
            ativo=True
        )
        db.add(monitoramento)
        db.commit()

        return {
            "success": True,
            "monitoramento": {
                "id": monitoramento.id,
                "termo": termo,
                "fontes": fontes or ["pncp"],
                "ufs": ufs,
                "frequencia_horas": frequencia_horas,
                "score_minimo": score_minimo,
                "proximo_check": monitoramento.proximo_check.isoformat()
            }
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_listar_monitoramentos(user_id: str, empresa_id: str = None, apenas_ativos: bool = True) -> Dict:
    """
    Lista monitoramentos do usuário.

    Args:
        user_id: ID do usuário
        apenas_ativos: Se True, lista apenas monitoramentos ativos
    """
    db = get_db()
    try:
        query = db.query(Monitoramento).filter(
            Monitoramento.empresa_id == empresa_id
        )

        if apenas_ativos:
            query = query.filter(Monitoramento.ativo == True)

        monitoramentos = query.order_by(Monitoramento.created_at.desc()).all()

        resultado = []
        for m in monitoramentos:
            # Contar notificações geradas
            notifs = db.query(Notificacao).filter(
                Notificacao.monitoramento_id == m.id
            ).count()

            resultado.append({
                "id": m.id,
                "termo": m.termo,
                "fontes": m.fontes,
                "ufs": m.ufs,
                "frequencia_horas": m.frequencia_horas,
                "score_minimo": m.score_minimo_alerta,
                "ativo": m.ativo,
                "ultimo_check": m.ultimo_check.isoformat() if m.ultimo_check else None,
                "proximo_check": m.proximo_check.isoformat() if m.proximo_check else None,
                "notificacoes_geradas": notifs,
                "created_at": m.created_at.isoformat() if m.created_at else None
            })

        return {
            "success": True,
            "total": len(resultado),
            "monitoramentos": resultado
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_desativar_monitoramento(user_id: str, empresa_id: str = None, termo: str = None,
                                  monitoramento_id: str = None) -> Dict:
    """
    Desativa um monitoramento.

    Args:
        user_id: ID do usuário
        termo: Termo do monitoramento a desativar
        monitoramento_id: ID do monitoramento (alternativa ao termo)
    """
    db = get_db()
    try:
        query = db.query(Monitoramento).filter(
            Monitoramento.empresa_id == empresa_id,
            Monitoramento.ativo == True
        )

        if monitoramento_id:
            query = query.filter(Monitoramento.id == monitoramento_id)
        elif termo:
            query = query.filter(Monitoramento.termo.ilike(f"%{termo}%"))
        else:
            return {"success": False, "error": "Informe o termo ou ID do monitoramento."}

        monitoramento = query.first()
        if not monitoramento:
            return {"success": False, "error": "Monitoramento não encontrado."}

        monitoramento.ativo = False
        db.commit()

        return {
            "success": True,
            "mensagem": f"Monitoramento de '{monitoramento.termo}' desativado.",
            "monitoramento_id": monitoramento.id
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_configurar_preferencias_notificacao(user_id: str, email_habilitado: bool = None,
                                              push_habilitado: bool = None,
                                              email_notificacao: str = None,
                                              horario_inicio: str = None,
                                              horario_fim: str = None,
                                              alertas_padrao: List[int] = None) -> Dict:
    """
    Configura preferências de notificação do usuário.

    Args:
        user_id: ID do usuário
        email_habilitado: Habilitar notificações por email
        push_habilitado: Habilitar notificações push
        email_notificacao: Email alternativo para notificações
        horario_inicio: Horário início permitido (HH:MM)
        horario_fim: Horário fim permitido (HH:MM)
        alertas_padrao: Lista de minutos para alertas padrão
    """
    db = get_db()
    try:
        # Buscar ou criar preferências
        prefs = db.query(PreferenciasNotificacao).filter(
            PreferenciasNotificacao.user_id == user_id
        ).first()

        if not prefs:
            prefs = PreferenciasNotificacao(user_id=user_id)
            db.add(prefs)

        # Atualizar campos informados
        if email_habilitado is not None:
            prefs.email_habilitado = email_habilitado
        if push_habilitado is not None:
            prefs.push_habilitado = push_habilitado
        if email_notificacao:
            prefs.email_notificacao = email_notificacao
        if horario_inicio:
            prefs.horario_inicio = horario_inicio
        if horario_fim:
            prefs.horario_fim = horario_fim
        if alertas_padrao:
            prefs.alertas_padrao = alertas_padrao

        db.commit()

        return {
            "success": True,
            "preferencias": prefs.to_dict()
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_historico_notificacoes(user_id: str, empresa_id: str = None, limite: int = 50,
                                 apenas_nao_lidas: bool = False) -> Dict:
    """
    Retorna histórico de notificações do usuário.

    Args:
        user_id: ID do usuário
        limite: Quantidade máxima de notificações
        apenas_nao_lidas: Se True, retorna apenas não lidas
    """
    db = get_db()
    try:
        query = db.query(Notificacao).filter(
            Notificacao.empresa_id == empresa_id
        )

        if apenas_nao_lidas:
            query = query.filter(Notificacao.lida == False)

        notificacoes = query.order_by(Notificacao.created_at.desc()).limit(limite).all()

        # Contar não lidas
        nao_lidas = db.query(Notificacao).filter(
            Notificacao.empresa_id == empresa_id,
            Notificacao.lida == False
        ).count()

        resultado = []
        for n in notificacoes:
            edital = None
            if n.edital_id:
                ed = db.query(Edital).filter(Edital.id == n.edital_id).first()
                if ed:
                    edital = {"numero": ed.numero, "orgao": ed.orgao}

            resultado.append({
                "id": n.id,
                "tipo": n.tipo,
                "titulo": n.titulo,
                "mensagem": n.mensagem,
                "edital": edital,
                "lida": n.lida,
                "created_at": n.created_at.isoformat() if n.created_at else None
            })

        return {
            "success": True,
            "total": len(resultado),
            "nao_lidas": nao_lidas,
            "notificacoes": resultado
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_marcar_notificacao_lida(user_id: str, empresa_id: str = None, notificacao_id: str = None,
                                  marcar_todas: bool = False) -> Dict:
    """
    Marca notificação(ões) como lida(s).

    Args:
        user_id: ID do usuário
        notificacao_id: ID da notificação específica
        marcar_todas: Se True, marca todas como lidas
    """
    db = get_db()
    try:
        if marcar_todas:
            db.query(Notificacao).filter(
                Notificacao.empresa_id == empresa_id,
                Notificacao.lida == False
            ).update({"lida": True, "lida_em": datetime.now()})
            db.commit()
            return {"success": True, "mensagem": "Todas as notificações marcadas como lidas."}

        if notificacao_id:
            notif = db.query(Notificacao).filter(
                Notificacao.id == notificacao_id,
                Notificacao.empresa_id == empresa_id
            ).first()

            if not notif:
                return {"success": False, "error": "Notificação não encontrada."}

            notif.lida = True
            notif.lida_em = datetime.now()
            db.commit()
            return {"success": True, "mensagem": "Notificação marcada como lida."}

        return {"success": False, "error": "Informe o ID da notificação ou use marcar_todas=True."}

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_extrair_datas_edital(user_id: str, empresa_id: str = None, texto_edital: str = None,
                               edital_numero: str = None) -> Dict:
    """
    Extrai datas importantes de um edital usando IA.

    Args:
        user_id: ID do usuário
        texto_edital: Texto extraído do PDF do edital
        edital_numero: Número do edital para atualizar
    """
    db = get_db()
    try:
        if not texto_edital:
            return {"success": False, "error": "Texto do edital não fornecido."}

        # Prompt para extração de datas
        prompt = f"""Analise este edital de licitação e extraia TODAS as datas importantes.

TEXTO DO EDITAL:
{texto_edital[:8000]}

INSTRUÇÕES:
- Converta todas as datas para o formato dd/mm/yyyy HH:MM (se houver horário) ou dd/mm/yyyy (se só data)
- Horários geralmente estão em horário de Brasília
- A "sessão pública" ou "abertura" é a data mais importante
- Impugnação geralmente é 3 dias antes da abertura
- Recursos geralmente é até 3 dias após a sessão

Retorne APENAS um JSON válido:
{{
    "numero": "número do edital (ex: PE-001/2026)",
    "data_publicacao": "dd/mm/yyyy ou null",
    "data_abertura": "dd/mm/yyyy HH:MM ou null",
    "data_impugnacao": "dd/mm/yyyy HH:MM ou null",
    "data_proposta": "dd/mm/yyyy HH:MM ou null",
    "data_recursos": "dd/mm/yyyy HH:MM ou null",
    "fuso": "Brasília",
    "observacoes": "qualquer observação relevante"
}}"""

        resposta = call_deepseek([{"role": "user", "content": prompt}], max_tokens=500)

        # Extrair JSON da resposta
        json_match = re.search(r'\{[\s\S]*\}', resposta)
        if not json_match:
            return {"success": False, "error": "Não foi possível extrair datas do texto."}

        dados = json.loads(json_match.group())

        # Função para parsear datas
        def parse_data(data_str):
            if not data_str or data_str == "null":
                return None
            formatos = ["%d/%m/%Y %H:%M", "%d/%m/%Y"]
            for fmt in formatos:
                try:
                    return datetime.strptime(data_str, fmt)
                except:
                    continue
            return None

        # Se tiver número do edital, atualizar no banco
        edital = None
        if edital_numero or dados.get("numero"):
            numero = edital_numero or dados.get("numero")
            edital = db.query(Edital).filter(
                Edital.numero.ilike(f"%{numero}%"),
                Edital.empresa_id == empresa_id
            ).first()

            if edital:
                if dados.get("data_abertura"):
                    edital.data_abertura = parse_data(dados["data_abertura"])
                if dados.get("data_impugnacao"):
                    edital.data_limite_impugnacao = parse_data(dados["data_impugnacao"])
                if dados.get("data_proposta"):
                    edital.data_limite_proposta = parse_data(dados["data_proposta"])
                if dados.get("data_recursos"):
                    edital.data_recursos = parse_data(dados["data_recursos"])
                if dados.get("data_publicacao"):
                    dt = parse_data(dados["data_publicacao"])
                    if dt:
                        edital.data_publicacao = dt.date()

                db.commit()

        return {
            "success": True,
            "datas_extraidas": dados,
            "edital_atualizado": edital.numero if edital else None
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_cancelar_alerta(user_id: str, empresa_id: str = None, alerta_id: str = None,
                          edital_numero: str = None, cancelar_todos: bool = False) -> Dict:
    """
    Cancela alerta(s).

    Args:
        user_id: ID do usuário
        alerta_id: ID do alerta específico
        edital_numero: Cancelar todos alertas do edital
        cancelar_todos: Cancelar todos alertas agendados
    """
    db = get_db()
    try:
        if cancelar_todos:
            count = db.query(Alerta).filter(
                Alerta.empresa_id == empresa_id,
                Alerta.status == 'agendado'
            ).update({"status": "cancelado"})
            db.commit()
            return {"success": True, "mensagem": f"{count} alertas cancelados."}

        if alerta_id:
            alerta = db.query(Alerta).filter(
                Alerta.id == alerta_id,
                Alerta.empresa_id == empresa_id,
                Alerta.status == 'agendado'
            ).first()

            if not alerta:
                return {"success": False, "error": "Alerta não encontrado."}

            alerta.status = 'cancelado'
            db.commit()
            return {"success": True, "mensagem": "Alerta cancelado."}

        if edital_numero:
            edital = db.query(Edital).filter(
                Edital.numero.ilike(f"%{edital_numero}%"),
                Edital.empresa_id == empresa_id
            ).first()

            if not edital:
                return {"success": False, "error": "Edital não encontrado."}

            count = db.query(Alerta).filter(
                Alerta.edital_id == edital.id,
                Alerta.empresa_id == empresa_id,
                Alerta.status == 'agendado'
            ).update({"status": "cancelado"})
            db.commit()
            return {"success": True, "mensagem": f"{count} alertas do edital {edital.numero} cancelados."}

        return {"success": False, "error": "Informe alerta_id, edital_numero ou cancelar_todos."}

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# =============================================================================
# Onda 2 - T10: tool_calcular_scores_validacao (6 dimensões + GO/NO-GO)
# =============================================================================

PROMPT_SCORES_VALIDACAO = """Você é um especialista em licitações públicas brasileiras com profundo conhecimento técnico, jurídico, logístico e comercial.

Analise o edital abaixo e calcule 6 scores de validação (0 a 100) e dê uma decisão GO/NO-GO.

## EDITAL:
- Número: {numero}
- Órgão: {orgao}
- Objeto: {objeto}
- Valor Estimado: {valor}
- Modalidade: {modalidade}
- UF: {uf}
- Data Abertura: {data_abertura}

## PRODUTO/EMPRESA DO USUÁRIO:
{produto_info}

## DADOS DA EMPRESA:
{empresa_info}

## SCORES A CALCULAR (0-100):

1. **score_tecnico** (0-100): Aderência técnica do produto ao objeto do edital.
   - 90-100: Produto atende 100% dos requisitos técnicos
   - 70-89: Atende requisitos principais, pequenas adaptações
   - 50-69: Atende parcialmente, requer ajustes
   - 0-49: Baixa aderência técnica
   REGRA CRITICA: score_tecnico avalia se o PRODUTO da empresa atende ao OBJETO do edital. Se o edital solicita SERVIÇO (manutenção, reinstalação, calibração, locação, consultoria, profissional) e a empresa oferece PRODUTO (equipamento, insumo), o score_tecnico deve ser 0-20, independente de o nome do equipamento aparecer no texto do objeto. Da mesma forma, se as especificações técnicas (volume, tipo, modelo, tecnologia) do produto não são compatíveis com o que o edital exige, penalize proporcionalmente.

2. **score_documental** (0-100): Facilidade de cumprir os requisitos documentais.
   - 90-100: Documentação padrão, fácil de obter
   - 70-89: Maioria da documentação disponível
   - 50-69: Alguns documentos complexos ou demorados
   - 0-49: Documentação difícil ou impossível

3. **score_complexidade** (0-100): INVERSAMENTE proporcional à complexidade do edital.
   - 90-100: Edital simples, poucos requisitos
   - 70-89: Complexidade moderada
   - 50-69: Edital complexo, muitas exigências
   - 0-49: Extremamente complexo ou restritivo

4. **score_juridico** (0-100): Segurança jurídica e ausência de riscos legais.
   - 90-100: Sem restrições legais, edital bem elaborado
   - 70-89: Pequenas questões jurídicas, riscos baixos
   - 50-69: Alguns pontos questionáveis, possível impugnação
   - 0-49: Alto risco jurídico ou edital direcionado

5. **score_logistico** (0-100): Viabilidade logística (entrega, instalação, suporte).
   - 90-100: Entrega simples, local acessível
   - 70-89: Logística moderada, razoavelmente viável
   - 50-69: Logística desafiadora
   - 0-49: Logística inviável ou muito custosa

6. **score_comercial** (0-100): Atratividade comercial (margem, concorrência, volume).
   - 90-100: Alta margem esperada, baixa concorrência
   - 70-89: Boa oportunidade comercial
   - 50-69: Margem moderada, concorrência média
   - 0-49: Margem muito baixa ou alta concorrência

## REGRA DE PORTE/REGIME:
- Se a empresa for ME (Microempresa) ou EPP (Empresa de Pequeno Porte), ela tem benefícios na Lei 14.133/2021 (ex: licitações exclusivas ME/EPP, cota reservada).
- Se o edital for exclusivo para ME/EPP e a empresa for de porte "medio" ou "grande", o resultado deve ser NO-GO com justificativa.
- Se a empresa for ME/EPP e o edital for exclusivo para ME/EPP, aumente score_comercial em 10 pontos.
- Considere também o regime tributário (Simples Nacional, Lucro Presumido, Lucro Real) ao avaliar viabilidade comercial.

## DECISÃO:
Com base nos scores:
- **GO**: score_final >= {limiar_go} E score_tecnico >= {limiar_tecnico_go} E score_juridico >= {limiar_juridico_go}
- **NO-GO**: score_final < {limiar_nogo} OU score_tecnico < {limiar_tecnico_nogo} OU score_juridico < {limiar_juridico_nogo} OU incompatibilidade de porte
- **AVALIAR**: demais casos

## RESPONDA APENAS EM JSON:
{{
  "score_tecnico": <0-100>,
  "score_documental": <0-100>,
  "score_complexidade": <0-100>,
  "score_juridico": <0-100>,
  "score_logistico": <0-100>,
  "score_comercial": <0-100>,
  "score_final": <média ponderada>,
  "decisao": "GO" | "NO-GO" | "AVALIAR",
  "justificativa": "<2-3 frases explicando a decisão>",
  "pontos_positivos": ["<ponto 1>", "<ponto 2>"],
  "pontos_atencao": ["<risco 1>", "<risco 2>"],
  "compatibilidade_porte": true | false,
  "observacao_porte": "<se houver restrição de porte/regime, explique>"
}}

O score_final deve ser calculado com os pesos:
- técnico: {peso_tecnico_pct}%, documental: {peso_documental_pct}%, complexidade: {peso_complexidade_pct}%, jurídico: {peso_juridico_pct}%, logístico: {peso_logistico_pct}%, comercial: {peso_comercial_pct}%
"""


def _match_produto_edital(produtos, edital_objeto, db):
    """
    Matching hierárquico: produto exato → subclasse → classe → genérico.
    Retorna (melhor_produto, nivel_match, score_match).
    """
    import unicodedata

    def _norm(txt):
        if not txt:
            return ""
        txt = unicodedata.normalize('NFKD', txt).encode('ascii', 'ignore').decode('ascii')
        # Remover pontuação para evitar tokens como "(compressas)" ou "equipamentos,"
        import re as _re
        txt = _re.sub(r'[^\w\s]', ' ', txt)
        return txt.lower().strip()

    def _stem_pt(word):
        """Stemming simplificado para português — remove sufixos comuns de plural/gênero."""
        if len(word) <= 4:
            return word
        # Plurais: seringas→seringa, luvas→luva, materiais→material, equipamentos→equipamento
        if word.endswith('ais'):
            return word[:-3] + 'al'
        if word.endswith('eis'):
            return word[:-3] + 'el'
        if word.endswith('oes'):
            return word[:-3] + 'ao'
        if word.endswith('es') and not word.endswith('sse') and len(word) > 5:
            return word[:-2]
        if word.endswith('s') and not word.endswith('ss'):
            return word[:-1]
        return word

    objeto_norm = _norm(edital_objeto)
    objeto_tokens = set(_stem_pt(w) for w in objeto_norm.split() if len(w) > 2)

    if not objeto_tokens or not produtos:
        return None, "nenhum", 0

    candidatos = []  # (produto, nivel, score)

    # Tokens genéricos do objeto a ignorar na cobertura reversa
    STOP_OBJETO = {"aquisicao", "contratacao", "registro", "preco",
                    "futura", "eventual", "fornecimento", "servico",
                    "material", "equipamento", "compra", "pregao",
                    "eletronico", "para", "dos", "das", "com", "lote"}

    def _tokenize(campos):
        """Extrai tokens stemados de uma lista de campos."""
        tokens = set()
        for campo in campos:
            if campo:
                for w in _norm(campo).split():
                    if len(w) > 2:
                        tokens.add(_stem_pt(w))
        return tokens

    def _score_bidirecional(tokens_prod, intersecao):
        """Score bidirecional: max(cobertura_produto, cobertura_objeto_relevante)."""
        cob_prod = len(intersecao) / max(len(tokens_prod), 1)
        obj_rel = objeto_tokens - {_stem_pt(w) for w in STOP_OBJETO}
        cob_obj = len(intersecao) / max(len(obj_rel), 1) if obj_rel else cob_prod
        return max(cob_prod, cob_obj)

    for p in produtos:
        # Nível 1: Match exato (nome + fabricante/modelo)
        tokens_exato = _tokenize([p.nome, p.fabricante, p.modelo])

        if tokens_exato:
            intersecao = tokens_exato & objeto_tokens
            score_exato = _score_bidirecional(tokens_exato, intersecao)
            # Bonus: substring match do nome inteiro
            nome_norm = _norm(p.nome or "")
            if nome_norm and len(nome_norm) > 5 and nome_norm in objeto_norm:
                score_exato = max(score_exato, 0.7)
            # Bonus: fabricante exato no objeto
            fab_norm = _norm(p.fabricante or "")
            if fab_norm and len(fab_norm) > 2 and fab_norm in objeto_norm:
                score_exato += 0.15
            # Bonus: primeira palavra significativa do nome do produto no objeto
            nome_palavras = [_stem_pt(w) for w in _norm(p.nome or "").split() if len(w) > 3]
            if nome_palavras and nome_palavras[0] in objeto_tokens:
                score_exato = max(score_exato, 0.5)

            if score_exato >= 0.4:
                candidatos.append((p, "exato", score_exato))
                continue

        # Nível 2: Match por subclasse
        matched_subclasse = False
        if p.subclasse_id:
            irmaos = db.query(Produto).filter(
                Produto.subclasse_id == p.subclasse_id,
                Produto.user_id == p.user_id
            ).all()
            for irmao in irmaos:
                if irmao.id == p.id:
                    continue
                tokens_irmao = _tokenize([irmao.nome, irmao.fabricante, irmao.modelo])
                if tokens_irmao:
                    intersecao = tokens_irmao & objeto_tokens
                    score_irmao = _score_bidirecional(tokens_irmao, intersecao)
                    if score_irmao >= 0.3:
                        candidatos.append((p, "subclasse", score_irmao * 0.8))
                        matched_subclasse = True
                        break

            # Nível 3: Match por classe (via subclasse.classe)
            if not matched_subclasse:
                subclasse = db.query(SubclasseProduto).filter(
                    SubclasseProduto.id == p.subclasse_id
                ).first()
                if subclasse and subclasse.classe_id:
                    subs_classe = db.query(SubclasseProduto).filter(
                        SubclasseProduto.classe_id == subclasse.classe_id
                    ).all()
                    sub_ids = [s.id for s in subs_classe]
                    primos = db.query(Produto).filter(
                        Produto.subclasse_id.in_(sub_ids),
                        Produto.user_id == p.user_id,
                        Produto.id != p.id
                    ).all()
                    for primo in primos:
                        tokens_primo = _tokenize([primo.nome, primo.fabricante, primo.modelo])
                        if tokens_primo:
                            intersecao = tokens_primo & objeto_tokens
                            score_primo = _score_bidirecional(tokens_primo, intersecao)
                            if score_primo >= 0.3:
                                candidatos.append((p, "classe", score_primo * 0.6))
                                break

        # Nível 4: Match genérico (fallback por tokens incluindo termos_busca)
        termos_list = [t for t in (p.termos_busca or [])]
        tokens_all = _tokenize([p.nome, p.categoria, p.fabricante, p.modelo] + termos_list)

        if tokens_all:
            intersecao = tokens_all & objeto_tokens
            score_gen = _score_bidirecional(tokens_all, intersecao)
            if score_gen > 0.1:
                candidatos.append((p, "generico", score_gen * 0.4))

    if not candidatos:
        return None, "nenhum", 0

    candidatos.sort(key=lambda x: x[2], reverse=True)
    return candidatos[0]


def tool_calcular_scores_validacao(edital_id: str, user_id: str, empresa_id: str = None, produto_id: str = None) -> Dict[str, Any]:
    """
    Calcula 6 dimensões de score de validação para um edital:
    técnico, documental, complexidade, jurídico, logístico, comercial.
    Usa pesos e limiares de ParametroScore do banco.
    Retorna também decisão GO/NO-GO.

    Args:
        edital_id: ID do edital a analisar
        user_id: ID do usuário
        produto_id: (opcional) ID do produto específico para análise. Se None, matching hierárquico.

    Returns:
        Dict com scores, decisão GO/NO-GO e justificativa
    """
    db = get_db()
    try:
        # Buscar edital
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()

        if not edital:
            return {"success": False, "error": "Edital não encontrado"}

        # Carregar pesos e limiares do banco
        params = db.query(ParametroScore).filter(
            ParametroScore.empresa_id == empresa_id
        ).first()
        if not params:
            class _Defaults:
                peso_tecnico = Decimal('0.35'); peso_documental = Decimal('0.15')
                peso_complexidade = Decimal('0.15'); peso_juridico = Decimal('0.20')
                peso_logistico = Decimal('0.05'); peso_comercial = Decimal('0.10')
                limiar_go = Decimal('70.0'); limiar_nogo = Decimal('40.0')
                limiar_tecnico_go = Decimal('60.0'); limiar_tecnico_nogo = Decimal('30.0')
                limiar_juridico_go = Decimal('60.0'); limiar_juridico_nogo = Decimal('30.0')
                estados_atuacao = []
            params = _Defaults()

        # Buscar produto
        produto = None
        nivel_match = "nenhum"
        if produto_id:
            produto = db.query(Produto).filter(
                Produto.id == produto_id,
                Produto.empresa_id == empresa_id
            ).first()
            if produto:
                nivel_match = "exato"

        if not produto:
            # Matching hierárquico: exato → subclasse → classe → genérico
            todos_produtos = db.query(Produto).filter(
                Produto.empresa_id == empresa_id
            ).all()

            if todos_produtos:
                produto, nivel_match, match_score = _match_produto_edital(
                    todos_produtos, edital.objeto or "", db
                )
                if produto:
                    print(f"[SCORES_VALIDACAO] Match: '{produto.nome}' nivel={nivel_match} score={match_score:.2f} para '{(edital.objeto or '')[:60]}'")
                else:
                    produto = todos_produtos[0]
                    nivel_match = "generico"
                    print(f"[SCORES_VALIDACAO] Nenhum match — fallback para '{produto.nome}'")

        # Montar informação do produto para o prompt
        if produto:
            specs = db.query(ProdutoEspecificacao).filter(
                ProdutoEspecificacao.produto_id == produto.id
            ).limit(15).all()
            specs_texto = "; ".join([f"{s.nome_especificacao}: {s.valor}" for s in specs])
            produto_info = (
                f"Nome: {produto.nome}\n"
                f"Categoria: {produto.categoria}\n"
                f"Fabricante: {produto.fabricante or 'N/A'}\n"
                f"Modelo: {produto.modelo or 'N/A'}\n"
                f"Nível de Match: {nivel_match} (exato|subclasse|classe|generico)\n"
                f"Especificações: {specs_texto or 'Não disponível'}"
            )
        else:
            produto_info = "Produto não informado. Analise considerando um produto genérico da categoria do edital."

        # Carregar dados da empresa (porte, regime tributário)
        empresa_info = "Dados da empresa não disponíveis."
        try:
            empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first() if empresa_id else None
            if empresa:
                porte_map = {'me': 'Microempresa (ME)', 'epp': 'Empresa de Pequeno Porte (EPP)',
                             'medio': 'Médio Porte', 'grande': 'Grande Empresa'}
                regime_map = {'simples': 'Simples Nacional', 'lucro_presumido': 'Lucro Presumido',
                              'lucro_real': 'Lucro Real'}
                estados_atuacao_str = ", ".join(getattr(params, 'estados_atuacao', None) or []) or "Não configurados"
                empresa_info = (
                    f"Razão Social: {empresa.razao_social}\n"
                    f"CNPJ: {empresa.cnpj}\n"
                    f"Porte: {porte_map.get(empresa.porte, empresa.porte or 'Não informado')}\n"
                    f"Regime Tributário: {regime_map.get(empresa.regime_tributario, empresa.regime_tributario or 'Não informado')}\n"
                    f"UF: {empresa.uf or 'N/A'}\n"
                    f"Cidade: {empresa.cidade or 'N/A'}\n"
                    f"Estados de Atuação: {estados_atuacao_str}"
                )
        except Exception as e:
            print(f"[SCORES_VALIDACAO] Erro ao carregar empresa: {e}")

        valor_str = "Não informado"
        if edital.valor_referencia:
            v = float(edital.valor_referencia)
            valor_str = f"R$ {v:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

        # Calcular percentuais dos pesos para o prompt
        peso_tec = float(params.peso_tecnico or Decimal('0.35'))
        peso_doc = float(params.peso_documental or Decimal('0.15'))
        peso_com = float(params.peso_complexidade or Decimal('0.15'))
        peso_jur = float(params.peso_juridico or Decimal('0.20'))
        peso_log = float(params.peso_logistico or Decimal('0.05'))
        peso_cml = float(params.peso_comercial or Decimal('0.10'))

        lim_go = float(params.limiar_go or Decimal('70'))
        lim_nogo = float(params.limiar_nogo or Decimal('40'))
        lim_tec_go = float(params.limiar_tecnico_go or Decimal('60'))
        lim_tec_nogo = float(params.limiar_tecnico_nogo or Decimal('30'))
        lim_jur_go = float(params.limiar_juridico_go or Decimal('60'))
        lim_jur_nogo = float(params.limiar_juridico_nogo or Decimal('30'))

        prompt = PROMPT_SCORES_VALIDACAO.format(
            numero=edital.numero,
            orgao=edital.orgao,
            objeto=(edital.objeto or "")[:1000],
            valor=valor_str,
            modalidade=edital.modalidade or "pregao_eletronico",
            uf=edital.uf or "N/A",
            data_abertura=edital.data_abertura.strftime('%d/%m/%Y %H:%M') if edital.data_abertura else "N/A",
            produto_info=produto_info,
            empresa_info=empresa_info,
            peso_tecnico_pct=round(peso_tec * 100),
            peso_documental_pct=round(peso_doc * 100),
            peso_complexidade_pct=round(peso_com * 100),
            peso_juridico_pct=round(peso_jur * 100),
            peso_logistico_pct=round(peso_log * 100),
            peso_comercial_pct=round(peso_cml * 100),
            limiar_go=round(lim_go),
            limiar_nogo=round(lim_nogo),
            limiar_tecnico_go=round(lim_tec_go),
            limiar_tecnico_nogo=round(lim_tec_nogo),
            limiar_juridico_go=round(lim_jur_go),
            limiar_juridico_nogo=round(lim_jur_nogo),
        )

        print(f"[SCORES_VALIDACAO] Calculando para edital {edital.numero} (pesos: T={peso_tec} D={peso_doc} C={peso_com} J={peso_jur} L={peso_log} CM={peso_cml})...")
        resposta = call_deepseek(
            [{"role": "user", "content": prompt}],
            max_tokens=1500,
            temperature=0,
            model_override="deepseek-chat"
        )

        if not resposta or len(resposta.strip()) < 10:
            return {"success": False, "error": "Resposta vazia da IA"}

        # Extrair JSON
        json_match = re.search(r'\{[\s\S]*\}', resposta)
        if not json_match:
            return {"success": False, "error": "IA não retornou JSON válido"}

        raw_json = json_match.group().replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
        raw_json = re.sub(r'  +', ' ', raw_json)

        scores_data = json.loads(raw_json)

        # Recalcular score_final com pesos do banco (não confiar na IA)
        score_final_calc = round(
            (scores_data.get('score_tecnico', 0) or 0) * peso_tec +
            (scores_data.get('score_documental', 0) or 0) * peso_doc +
            (scores_data.get('score_complexidade', 0) or 0) * peso_com +
            (scores_data.get('score_juridico', 0) or 0) * peso_jur +
            (scores_data.get('score_logistico', 0) or 0) * peso_log +
            (scores_data.get('score_comercial', 0) or 0) * peso_cml,
            1
        )
        scores_data['score_final'] = score_final_calc

        # Decisão GO/NO-GO no backend com limiares do banco
        st = scores_data.get('score_tecnico', 0) or 0
        sj = scores_data.get('score_juridico', 0) or 0
        if score_final_calc < lim_nogo or st < lim_tec_nogo or sj < lim_jur_nogo:
            scores_data['decisao'] = 'NO-GO'
        elif score_final_calc >= lim_go and st >= lim_tec_go and sj >= lim_jur_go:
            scores_data['decisao'] = 'GO'
        else:
            scores_data['decisao'] = 'AVALIAR'

        # Salvar na análise existente ou criar nova
        analise = db.query(Analise).filter(
            Analise.edital_id == edital_id,
            Analise.empresa_id == empresa_id
        ).first()

        import json as _json
        recomendacao_json = _json.dumps({
            "decisao": scores_data.get('decisao', 'AVALIAR'),
            "justificativa": scores_data.get('justificativa', ''),
            "scores": {
                "tecnico": scores_data.get('score_tecnico') or 0,
                "documental": scores_data.get('score_documental') or 0,
                "complexidade": scores_data.get('score_complexidade') or 0,
                "juridico": scores_data.get('score_juridico') or 0,
                "logistico": scores_data.get('score_logistico') or 0,
                "comercial": scores_data.get('score_comercial') or 0,
            },
            "pontos_positivos": scores_data.get('pontos_positivos', []),
            "pontos_atencao": scores_data.get('pontos_atencao', []),
        }, ensure_ascii=False)

        if analise:
            analise.score_tecnico = scores_data.get('score_tecnico')
            analise.score_comercial = scores_data.get('score_comercial')
            analise.score_final = score_final_calc
            analise.recomendacao = recomendacao_json
        else:
            analise = Analise(
                edital_id=edital_id,
                produto_id=produto.id if produto else edital_id,
                user_id=user_id,
                score_tecnico=scores_data.get('score_tecnico'),
                score_comercial=scores_data.get('score_comercial'),
                score_final=score_final_calc,
                recomendacao=recomendacao_json,
            )
            db.add(analise)

        db.commit()

        print(f"[SCORES_VALIDACAO] {edital.numero}: score_final={score_final_calc} (recalc), decisao={scores_data.get('decisao')}, match={nivel_match}")

        scores_out = {
            "tecnico": scores_data.get('score_tecnico') or 0,
            "documental": scores_data.get('score_documental') or 0,
            "complexidade": scores_data.get('score_complexidade') or 0,
            "juridico": scores_data.get('score_juridico') or 0,
            "logistico": scores_data.get('score_logistico') or 0,
            "comercial": scores_data.get('score_comercial') or 0,
        }

        return {
            "success": True,
            "edital_id": edital_id,
            "edital_numero": edital.numero,
            "analise_id": analise.id,
            "scores": scores_out,
            "score_geral": score_final_calc,
            "decisao": scores_data.get('decisao', 'AVALIAR'),
            "decisao_ia": scores_data.get('decisao', 'AVALIAR').upper().replace("NOGO", "NO-GO"),
            "justificativa": scores_data.get('justificativa', ''),
            "justificativa_ia": scores_data.get('justificativa', ''),
            "pontos_positivos": scores_data.get('pontos_positivos', []),
            "pontos_atencao": scores_data.get('pontos_atencao', []),
            "nivel_match": nivel_match,
            "produto_match_id": produto.id if produto else None,
            "produto_match_nome": produto.nome if produto else None,
            "sub_scores_tecnicos": [
                {"label": "Aderencia Tecnica", "score": scores_out["tecnico"]},
                {"label": "Aderencia Documental", "score": scores_out["documental"]},
                {"label": "Complexidade Edital", "score": scores_out["complexidade"]},
                {"label": "Risco Juridico", "score": scores_out["juridico"]},
                {"label": "Viabilidade Logistica", "score": scores_out["logistico"]},
                {"label": "Atratividade Comercial", "score": scores_out["comercial"]},
            ],
            "potencial_ganho": (
                "elevado" if score_final_calc >= lim_go else
                "medio" if score_final_calc >= lim_nogo else
                "baixo"
            ),
        }

    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Erro ao parsear resposta da IA: {e}"}
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# =============================================================================
# Onda 2 - T11: tool_atualizar_status_proposta
# =============================================================================

def tool_atualizar_status_proposta(proposta_id: str, user_id: str, empresa_id: str = None, novo_status: str = None,
                                    observacao: str = None) -> Dict[str, Any]:
    """
    Atualiza o status de uma proposta seguindo workflow:
    rascunho -> revisao -> aprovada -> enviada -> aceita/rejeitada

    Args:
        proposta_id: ID da proposta
        user_id: ID do usuário
        novo_status: Novo status desejado
        observacao: Observação opcional sobre a mudança de status

    Returns:
        Dict com resultado da operação
    """
    # Status do modelo: rascunho, revisao, aprovada, enviada
    TRANSICOES_VALIDAS = {
        "rascunho": ["revisao"],
        "revisao": ["rascunho", "aprovada"],
        "aprovada": ["revisao", "enviada"],
        "enviada": ["aprovada", "rascunho"]
    }

    STATUS_VALIDOS = list(TRANSICOES_VALIDAS.keys())

    if novo_status not in STATUS_VALIDOS:
        return {
            "success": False,
            "error": f"Status inválido '{novo_status}'. Válidos: {', '.join(STATUS_VALIDOS)}"
        }

    db = get_db()
    try:
        proposta = db.query(Proposta).filter(
            Proposta.id == proposta_id,
            Proposta.empresa_id == empresa_id
        ).first()

        if not proposta:
            return {"success": False, "error": "Proposta não encontrada"}

        status_atual = proposta.status
        transicoes = TRANSICOES_VALIDAS.get(status_atual, [])

        if novo_status not in transicoes:
            return {
                "success": False,
                "error": f"Transição inválida: '{status_atual}' -> '{novo_status}'. Permitidas: {transicoes}"
            }

        proposta.status = novo_status
        proposta.updated_at = datetime.now()
        db.commit()

        return {
            "success": True,
            "proposta_id": proposta_id,
            "status_anterior": status_atual,
            "status_atual": novo_status,
            "mensagem": f"Proposta atualizada: {status_atual} → {novo_status}",
            "observacao": observacao
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# Registrar novas tools Onda 2 no TOOLS_MAP
TOOLS_MAP["calcular_scores_validacao"] = tool_calcular_scores_validacao
TOOLS_MAP["atualizar_status_proposta"] = tool_atualizar_status_proposta


# =============================================================================
# FASE 1 — PRECIFICAÇÃO (UC-P01 a UC-P10)
# =============================================================================

import math


# ─── Prompt para extração de lotes via IA ─────────────────────────────────────

PROMPT_EXTRAIR_LOTES = """Analise o texto do edital de licitação abaixo e extraia a estrutura de LOTES e ITENS.

REGRAS:
1. Se o edital organiza itens em lotes (Lote 01, Lote 02...), identifique cada lote e quais itens pertencem a ele.
2. Se o edital não tem lotes explícitos, agrupe itens por ESPECIALIDADE/CATEGORIA (ex: hematologia, coagulação, bioquímica, insumos).
3. Identifique o tipo de julgamento: "por_lote" (menor preço global do lote) ou "por_item" (menor preço por item).
4. Para cada lote, defina a especialidade.
5. Em itens_numeros, use o campo "numero_item" de cada item da lista abaixo. TODOS os itens devem ser alocados em algum lote.
6. Itens que não se encaixam em nenhuma especialidade vão num lote "Avulsos".

Os itens do edital já importados do PNCP são:
{itens_json}

Responda EXCLUSIVAMENTE com JSON válido, sem texto adicional:
{{
  "tipo_julgamento": "por_lote" ou "por_item",
  "lotes": [
    {{
      "numero_lote": 1,
      "nome": "Lote 01 — Reagentes Hematologia",
      "especialidade": "Hematologia",
      "itens_numeros": [1, 2, 3, 4, 5, 6, 7]
    }}
  ]
}}

TEXTO DO EDITAL:
{texto_edital}
"""


def _extrair_lotes_ia(texto_edital: str, itens_db: list) -> Dict[str, Any]:
    """Usa IA para extrair estrutura de lotes do texto do edital."""
    # Montar JSON dos itens para contexto (usar índice se numero_item é null)
    itens_info = []
    for idx, item in enumerate(itens_db, 1):
        itens_info.append({
            "numero_item": item.numero_item if item.numero_item is not None else idx,
            "descricao": (item.descricao or "")[:200],
            "quantidade": float(item.quantidade or 0),
            "valor_total": float(item.valor_total_estimado or 0),
        })

    # Limitar texto do edital para não estourar contexto
    texto_limitado = texto_edital[:30000] if texto_edital else ""

    prompt = PROMPT_EXTRAIR_LOTES.format(
        itens_json=json.dumps(itens_info, ensure_ascii=False, indent=2),
        texto_edital=texto_limitado
    )

    try:
        messages = [{"role": "user", "content": prompt}]
        resposta = call_deepseek(messages, max_tokens=2000, model_override="deepseek-chat")
        # Limpar resposta — extrair JSON
        texto_resp = resposta.strip()
        # Remover markdown code blocks se presentes
        if texto_resp.startswith("```"):
            texto_resp = texto_resp.split("```")[1]
            if texto_resp.startswith("json"):
                texto_resp = texto_resp[4:]
            texto_resp = texto_resp.strip()

        resultado = json.loads(texto_resp)
        return resultado
    except json.JSONDecodeError as e:
        print(f"[LOTES] Erro ao parsear resposta da IA: {e}")
        print(f"[LOTES] Resposta: {resposta[:500] if resposta else 'vazia'}")
        return None
    except Exception as e:
        print(f"[LOTES] Erro na chamada IA: {e}")
        return None


def tool_organizar_lotes(edital_id: str, user_id: str, empresa_id: str = None,
                         importar_pncp: bool = False, forcar: bool = False) -> Dict[str, Any]:
    """UC-P01: Organiza itens do edital em lotes.
    1. Importa itens do PNCP se necessário
    2. Lê o texto do PDF do edital (EditalDocumento)
    3. Usa IA para identificar lotes no texto
    4. Cria Lote + LoteItem no banco
    Se não há PDF ou a IA não consegue, cria lote único com todos os itens."""
    db = get_db()
    try:
        edital = db.query(Edital).filter(Edital.id == edital_id, Edital.empresa_id == empresa_id).first()
        if not edital:
            return {"success": False, "error": "Edital não encontrado"}

        # 1. Importar itens do PNCP se não existem
        itens_db = db.query(EditalItem).filter(EditalItem.edital_id == edital_id).all()
        if not itens_db and importar_pncp and edital.cnpj_orgao and edital.ano_compra and edital.seq_compra:
            result_itens = tool_buscar_itens_edital_pncp(
                edital_id=edital_id,
                cnpj=edital.cnpj_orgao,
                ano=edital.ano_compra,
                seq=edital.seq_compra,
                user_id=user_id
            )
            if not result_itens.get("success"):
                return {"success": False, "error": f"Erro ao importar itens PNCP: {result_itens.get('error')}"}
            itens_db = db.query(EditalItem).filter(EditalItem.edital_id == edital_id).all()

        if not itens_db:
            return {"success": False, "error": "Nenhum item encontrado no edital. Importe itens do PNCP primeiro."}

        # 2. Verificar se já existem lotes
        lotes_existentes = db.query(Lote).filter(Lote.edital_id == edital_id, Lote.empresa_id == empresa_id).all()
        if lotes_existentes and not forcar:
            # Retornar lotes existentes com seus itens
            lotes_resp = []
            for l in lotes_existentes:
                ld = l.to_dict()
                lote_itens = db.query(LoteItem).filter(LoteItem.lote_id == l.id).order_by(LoteItem.ordem).all()
                ld["itens"] = []
                for li in lote_itens:
                    ei = db.query(EditalItem).filter(EditalItem.id == li.edital_item_id).first()
                    if ei:
                        ld["itens"].append(ei.to_dict())
                lotes_resp.append(ld)
            return {
                "success": True,
                "mensagem": f"Edital já possui {len(lotes_existentes)} lote(s)",
                "lotes": lotes_resp,
                "total_itens": len(itens_db),
            }

        # Se forçar, deletar lotes existentes
        if forcar and lotes_existentes:
            for l in lotes_existentes:
                db.query(LoteItem).filter(LoteItem.lote_id == l.id).delete()
                db.delete(l)
            db.flush()

        # 3. Buscar texto do PDF do edital
        from models import EditalDocumento
        doc = db.query(EditalDocumento).filter(
            EditalDocumento.edital_id == edital_id,
            EditalDocumento.tipo == 'edital_principal'
        ).first()

        texto_edital = doc.texto_extraido if doc and doc.texto_extraido else None

        # 4. Extrair lotes via IA (se tem texto do PDF)
        lotes_ia = None
        tipo_julgamento = "por_item"
        if texto_edital and len(texto_edital) > 500:
            print(f"[LOTES] Extraindo lotes via IA do edital {edital.numero} ({len(texto_edital)} chars)...")
            lotes_ia = _extrair_lotes_ia(texto_edital, itens_db)
            if lotes_ia:
                tipo_julgamento = lotes_ia.get("tipo_julgamento", "por_item")
                print(f"[LOTES] IA detectou: tipo={tipo_julgamento}, {len(lotes_ia.get('lotes', []))} lote(s)")
        else:
            print(f"[LOTES] Sem texto do PDF — criando lotes por item")

        # Mapa numero_item → EditalItem (com fallback para índice)
        itens_por_numero = {}
        itens_por_indice = {}
        for idx, i in enumerate(itens_db, 1):
            if i.numero_item is not None:
                itens_por_numero[i.numero_item] = i
            itens_por_indice[idx] = i
            itens_por_indice[str(idx)] = i
            # Também mapear pelo ID
            itens_por_numero[i.id] = i

        def _resolver_item(ref):
            """Resolve referência de item (numero_item, índice ou id)."""
            if ref in itens_por_numero:
                return itens_por_numero[ref]
            if ref in itens_por_indice:
                return itens_por_indice[ref]
            try:
                return itens_por_indice.get(int(ref))
            except (ValueError, TypeError):
                return None

        # 5. Criar lotes no banco
        lotes_criados = []

        if lotes_ia and lotes_ia.get("lotes"):
            # Criar lotes conforme a IA detectou
            itens_alocados = set()
            for lote_info in lotes_ia["lotes"]:
                num = lote_info.get("numero_lote", len(lotes_criados) + 1)
                nome = lote_info.get("nome", f"Lote {num:02d}")
                especialidade = lote_info.get("especialidade")
                itens_numeros = lote_info.get("itens_numeros", [])

                # Calcular valor estimado do lote — resolver por numero, indice ou id
                itens_do_lote = [_resolver_item(n) for n in itens_numeros]
                itens_do_lote = [i for i in itens_do_lote if i is not None]
                valor_est = sum(float(i.valor_total_estimado or 0) for i in itens_do_lote)

                lote = Lote(
                    edital_id=edital_id,
                    user_id=user_id,
                    empresa_id=empresa_id,
                    numero_lote=num,
                    nome=nome,
                    especialidade=especialidade,
                    valor_estimado=valor_est,
                    status='rascunho'
                )
                db.add(lote)
                db.flush()

                # Vincular itens ao lote
                for ordem, item_ref in enumerate(itens_numeros, 1):
                    item = _resolver_item(item_ref)
                    if item:
                        li = LoteItem(lote_id=lote.id, edital_item_id=item.id, ordem=ordem)
                        db.add(li)
                        itens_alocados.add(item.id)

                ld = lote.to_dict()
                ld["itens"] = [i.to_dict() for i in itens_do_lote]
                lotes_criados.append(ld)

            # Itens não alocados pela IA → criar lote "Avulsos"
            nao_alocados = [i for i in itens_db if i.id not in itens_alocados]
            if nao_alocados:
                lote_avulso = Lote(
                    edital_id=edital_id,
                    user_id=user_id,
                    empresa_id=empresa_id,
                    numero_lote=len(lotes_criados) + 1,
                    nome=f"Lote {len(lotes_criados) + 1:02d} — Itens Avulsos",
                    valor_estimado=sum(float(i.valor_total_estimado or 0) for i in nao_alocados),
                    status='rascunho'
                )
                db.add(lote_avulso)
                db.flush()
                for ordem, item in enumerate(nao_alocados, 1):
                    li = LoteItem(lote_id=lote_avulso.id, edital_item_id=item.id, ordem=ordem)
                    db.add(li)
                ld = lote_avulso.to_dict()
                ld["itens"] = [i.to_dict() for i in nao_alocados]
                lotes_criados.append(ld)
        else:
            # Fallback: sem IA ou sem texto — lote único com todos os itens
            lote = Lote(
                edital_id=edital_id,
                user_id=user_id,
                empresa_id=empresa_id,
                numero_lote=1,
                nome=f"Lote 01 — {edital.objeto[:60] if edital.objeto else 'Geral'}",
                valor_estimado=sum(float(i.valor_total_estimado or 0) for i in itens_db),
                status='rascunho'
            )
            db.add(lote)
            db.flush()
            for idx, item in enumerate(itens_db):
                li = LoteItem(lote_id=lote.id, edital_item_id=item.id, ordem=idx + 1)
                db.add(li)
            ld = lote.to_dict()
            ld["itens"] = [i.to_dict() for i in itens_db]
            lotes_criados.append(ld)

        db.commit()

        return {
            "success": True,
            "tipo_julgamento": tipo_julgamento,
            "mensagem": f"{len(lotes_criados)} lote(s) criado(s) com {len(itens_db)} itens",
            "lotes": lotes_criados,
            "total_itens": len(itens_db),
            "fonte": "ia" if lotes_ia else "fallback",
        }

    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_selecao_portfolio(edital_item_id: str, user_id: str, empresa_id: str = None,
                           produto_id: str = None) -> Dict[str, Any]:
    """UC-P02: Seleção inteligente de produto do portfolio para um item do edital.
    Se produto_id fornecido, confirma a seleção. Senão, busca sugestões via IA."""
    db = get_db()
    try:
        item = db.query(EditalItem).filter(EditalItem.id == edital_item_id).first()
        if not item:
            return {"success": False, "error": "Item do edital não encontrado"}

        # Se produto_id fornecido, vincular diretamente
        if produto_id:
            produto = db.query(Produto).filter(Produto.id == produto_id, Produto.empresa_id == empresa_id).first()
            if not produto:
                return {"success": False, "error": "Produto não encontrado"}

            # Verificar vínculo existente
            vinculo = db.query(EditalItemProduto).filter(
                EditalItemProduto.edital_item_id == edital_item_id,
                EditalItemProduto.empresa_id == empresa_id
            ).first()

            if vinculo:
                vinculo.produto_id = produto_id
                vinculo.confirmado = True
                vinculo.updated_at = datetime.now()
            else:
                vinculo = EditalItemProduto(
                    edital_item_id=edital_item_id,
                    produto_id=produto_id,
                    user_id=user_id,
                    empresa_id=empresa_id,
                    confirmado=True
                )
                db.add(vinculo)

            db.commit()
            return {
                "success": True,
                "mensagem": f"Produto '{produto.nome}' vinculado ao item {item.numero_item}",
                "vinculo": vinculo.to_dict(),
            }

        # Buscar sugestões: produtos do portfolio que podem atender o item
        produtos = db.query(Produto).filter(Produto.empresa_id == empresa_id).all()
        if not produtos:
            return {"success": False, "error": "Nenhum produto cadastrado no portfolio"}

        # Matching simples por palavras-chave na descrição do item
        desc_item = (item.descricao or "").lower()
        sugestoes = []
        for p in produtos:
            score = 0
            nome_p = (p.nome or "").lower()
            desc_p = (p.descricao or "").lower()
            fab_p = (p.fabricante or "").lower()
            modelo_p = (p.modelo or "").lower()

            # Score por palavras comuns
            palavras_item = set(desc_item.split()) - STOPWORDS_PT
            palavras_produto = set(nome_p.split()) | set(desc_p.split())
            palavras_produto -= STOPWORDS_PT

            if palavras_item and palavras_produto:
                intersecao = palavras_item & palavras_produto
                score = len(intersecao) / max(len(palavras_item), 1) * 100

            # Bonus se fabricante ou modelo aparece na descrição do item
            if fab_p and fab_p in desc_item:
                score += 20
            if modelo_p and modelo_p in desc_item:
                score += 20

            if score > 10:
                sugestoes.append({
                    "produto_id": p.id,
                    "nome": p.nome,
                    "fabricante": p.fabricante,
                    "modelo": p.modelo,
                    "ncm": p.ncm,
                    "match_score": min(round(score, 1), 100),
                    "preco_referencia": float(p.preco_referencia) if p.preco_referencia else None,
                })

        sugestoes.sort(key=lambda x: x["match_score"], reverse=True)

        # Auto-vincular o melhor match se score > 20
        if sugestoes and sugestoes[0]["match_score"] > 20:
            melhor = sugestoes[0]
            vinculo = db.query(EditalItemProduto).filter(
                EditalItemProduto.edital_item_id == edital_item_id,
                EditalItemProduto.empresa_id == empresa_id
            ).first()
            if vinculo:
                vinculo.produto_id = melhor["produto_id"]
                vinculo.match_score = melhor["match_score"]
                vinculo.confirmado = True
            else:
                vinculo = EditalItemProduto(
                    edital_item_id=edital_item_id,
                    produto_id=melhor["produto_id"],
                    user_id=user_id,
                    empresa_id=empresa_id,
                    match_score=melhor["match_score"],
                    confirmado=True,
                )
                db.add(vinculo)
            db.commit()
            return {
                "success": True,
                "auto_vinculado": True,
                "produto_nome": melhor["nome"],
                "match_score": melhor["match_score"],
                "justificativa": f"Melhor match: {melhor['nome']} ({melhor['match_score']}%)",
                "sugestoes": sugestoes[:5],
            }

        return {
            "success": len(sugestoes) > 0,
            "auto_vinculado": False,
            "error": "Nenhum produto com match suficiente" if not sugestoes else None,
            "sugestoes": sugestoes[:10],
            "total_produtos": len(produtos),
            "mensagem": f"{len(sugestoes)} produto(s) encontrado(s) com match para o item",
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_calcular_volumetria(edital_item_produto_id: str, user_id: str, empresa_id: str = None,
                              volume_edital: float = None,
                              rendimento_produto: float = None,
                              repeticoes_amostras: int = 0,
                              repeticoes_calibradores: int = 0,
                              repeticoes_controles: int = 0) -> Dict[str, Any]:
    """UC-P03: Calcula volumetria técnica (kits necessários)."""
    db = get_db()
    try:
        vinculo = db.query(EditalItemProduto).filter(
            EditalItemProduto.id == edital_item_produto_id,
            EditalItemProduto.empresa_id == empresa_id
        ).first()
        if not vinculo:
            return {"success": False, "error": "Vínculo item-produto não encontrado"}

        # Usar valores fornecidos ou existentes
        vol = volume_edital or float(vinculo.volume_edital or 0)
        rend = rendimento_produto or float(vinculo.rendimento_produto or 0)
        rep_a = repeticoes_amostras or vinculo.repeticoes_amostras or 0
        rep_c = repeticoes_calibradores or vinculo.repeticoes_calibradores or 0
        rep_ctrl = repeticoes_controles or vinculo.repeticoes_controles or 0

        if rend <= 0:
            return {"success": False, "error": "Rendimento do produto deve ser > 0"}

        # Cálculo: Volume Real Ajustado = Volume + repetições
        volume_ajustado = vol + rep_a + rep_c + rep_ctrl
        quantidade_kits = math.ceil(volume_ajustado / rend)
        formula = f"({vol} + {rep_a} + {rep_c} + {rep_ctrl}) / {rend} = {volume_ajustado/rend:.3f} → {quantidade_kits}"

        # Atualizar no banco
        vinculo.volume_edital = vol
        vinculo.rendimento_produto = rend
        vinculo.repeticoes_amostras = rep_a
        vinculo.repeticoes_calibradores = rep_c
        vinculo.repeticoes_controles = rep_ctrl
        vinculo.volume_real_ajustado = volume_ajustado
        vinculo.quantidade_kits = quantidade_kits
        vinculo.formula_calculo = formula
        vinculo.updated_at = datetime.now()
        db.commit()

        return {
            "success": True,
            "mensagem": f"Volumetria calculada: {quantidade_kits} kits necessários",
            "volume_edital": vol,
            "rendimento_produto": rend,
            "repeticoes": {"amostras": rep_a, "calibradores": rep_c, "controles": rep_ctrl},
            "volume_real_ajustado": volume_ajustado,
            "quantidade_kits": quantidade_kits,
            "formula": formula,
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_configurar_custos(edital_item_produto_id: str, user_id: str,
                            custo_unitario: float = None,
                            custo_fonte: str = 'manual',
                            icms: float = None, ipi: float = None,
                            pis_cofins: float = None,
                            empresa_id: str = None) -> Dict[str, Any]:
    """UC-P04: Configura base de custos (Camada A) com inteligência tributária NCM."""
    db = get_db()
    try:
        vinculo = db.query(EditalItemProduto).filter(
            EditalItemProduto.id == edital_item_produto_id,
            EditalItemProduto.empresa_id == empresa_id
        ).first()
        if not vinculo:
            return {"success": False, "error": "Vínculo item-produto não encontrado"}

        produto = db.query(Produto).filter(Produto.id == vinculo.produto_id).first()
        ncm = produto.ncm if produto else None

        # 1) Tentar buscar benefício fiscal cadastrado na tabela beneficios_fiscais_ncm
        beneficio = None
        if ncm:
            ncm_limpo = ncm.replace(".", "")
            # Busca exata primeiro, depois por prefixo (mais específico ganha)
            candidatos = db.query(BeneficioFiscalNcm).filter(
                BeneficioFiscalNcm.ativo == True
            ).all()
            melhor = None
            melhor_len = 0
            for c in candidatos:
                prefixo_limpo = c.ncm.replace(".", "")
                if ncm_limpo.startswith(prefixo_limpo) and len(prefixo_limpo) > melhor_len:
                    melhor = c
                    melhor_len = len(prefixo_limpo)
            beneficio = melhor

        # 2) Carregar parâmetros da empresa (fallback)
        params = db.query(ParametroScore).filter(ParametroScore.empresa_id == empresa_id).first()

        # 3) Determinar valores tributários: parâmetro explícito > tabela NCM > params empresa > default
        if beneficio:
            isencao_icms = beneficio.isencao_icms
            _icms = 0.0 if isencao_icms else (icms if icms is not None else float(beneficio.icms or 0))
            _ipi = ipi if ipi is not None else float(beneficio.ipi or 0)
            _pis = pis_cofins if pis_cofins is not None else float(beneficio.pis or 0) + float(beneficio.cofins or 0)
        else:
            # Fallback: lógica original com parâmetros da empresa
            ncm_isencoes = (params.ncm_isencao_icms or ["3822"]) if params else ["3822"]
            isencao_icms = False
            if ncm:
                for prefixo in ncm_isencoes:
                    if ncm.replace(".", "").startswith(prefixo.replace(".", "")):
                        isencao_icms = True
                        break
            _icms = 0.0 if isencao_icms else (icms if icms is not None else float(params.icms_padrao or 18) if params else 18.0)
            _ipi = ipi if ipi is not None else float(params.ipi_padrao or 0) if params else 0.0
            _pis = pis_cofins if pis_cofins is not None else float(params.pis_cofins or 9.25) if params else 9.25
        _custo = custo_unitario or float(produto.preco_referencia or 0) if produto else 0

        # Custo base final = custo * (1 + impostos/100) — simplificado
        custo_base_final = _custo  # Impostos são informacionais, não somam ao custo base

        # Buscar ou criar PrecoCamada
        camada = db.query(PrecoCamada).filter(
            PrecoCamada.edital_item_produto_id == edital_item_produto_id,
            PrecoCamada.empresa_id == empresa_id
        ).first()

        if not camada:
            camada = PrecoCamada(
                edital_item_produto_id=edital_item_produto_id,
                user_id=user_id,
                empresa_id=empresa_id
            )
            db.add(camada)

        camada.custo_unitario = _custo
        camada.custo_fonte = custo_fonte
        camada.ncm = ncm
        camada.icms = _icms
        camada.ipi = _ipi
        camada.pis_cofins = _pis
        camada.isencao_icms = isencao_icms
        camada.custo_base_final = custo_base_final
        camada.status = 'parcial'
        camada.updated_at = datetime.now()
        db.commit()

        fonte_tributaria = "beneficio_fiscal_ncm" if beneficio else "parametros_empresa"
        msg_extra = ""
        if beneficio:
            msg_extra = f" (via tabela benefícios fiscais NCM"
            if beneficio.base_legal:
                msg_extra += f" — {beneficio.base_legal}"
            msg_extra += ")"
        elif isencao_icms:
            msg_extra = f" (ICMS isento — NCM {ncm})"

        return {
            "success": True,
            "mensagem": f"Base de custos configurada: R$ {custo_base_final:.2f}" + msg_extra,
            "camada_id": camada.id,
            "custo_unitario": _custo,
            "ncm": ncm,
            "isencao_icms": isencao_icms,
            "icms": _icms,
            "ipi": _ipi,
            "pis_cofins": _pis,
            "custo_base_final": custo_base_final,
            "fonte_tributaria": fonte_tributaria,
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_montar_preco_base(edital_item_produto_id: str, user_id: str, empresa_id: str = None,
                            modo: str = 'manual',
                            preco_base: float = None,
                            markup_percentual: float = None,
                            reutilizar: bool = False) -> Dict[str, Any]:
    """UC-P05: Monta preço base (Camada B) — Manual, Markup sobre custo, ou Upload."""
    db = get_db()
    try:
        camada = db.query(PrecoCamada).filter(
            PrecoCamada.edital_item_produto_id == edital_item_produto_id,
            PrecoCamada.empresa_id == empresa_id
        ).first()
        if not camada:
            return {"success": False, "error": "Configure a base de custos (Camada A) primeiro"}

        custo = float(camada.custo_base_final or 0)

        if modo == 'markup':
            if markup_percentual is None:
                return {"success": False, "error": "Informe o markup percentual"}
            preco_calc = custo * (1 + markup_percentual / 100)
            camada.modo_preco_base = 'markup'
            camada.markup_percentual = markup_percentual
            camada.preco_base = preco_calc
        elif modo == 'manual':
            if preco_base is None:
                return {"success": False, "error": "Informe o preço base manualmente"}
            camada.modo_preco_base = 'manual'
            camada.preco_base = preco_base
            if custo > 0:
                camada.markup_percentual = ((preco_base - custo) / custo) * 100
        elif modo == 'upload':
            camada.modo_preco_base = 'upload'
            if preco_base:
                camada.preco_base = preco_base
        else:
            return {"success": False, "error": f"Modo inválido: {modo}"}

        camada.reutilizar_preco_base = reutilizar
        camada.updated_at = datetime.now()
        db.commit()

        return {
            "success": True,
            "mensagem": f"Preço base definido: R$ {float(camada.preco_base):.2f} (modo: {modo})",
            "preco_base": float(camada.preco_base),
            "custo_base": custo,
            "markup_percentual": float(camada.markup_percentual) if camada.markup_percentual else None,
            "reutilizar": reutilizar,
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_definir_referencia(edital_item_produto_id: str, user_id: str, empresa_id: str = None,
                             valor_referencia: float = None,
                             percentual_sobre_base: float = None) -> Dict[str, Any]:
    """UC-P06: Define valor de referência/target (Camada C)."""
    db = get_db()
    try:
        camada = db.query(PrecoCamada).filter(
            PrecoCamada.edital_item_produto_id == edital_item_produto_id,
            PrecoCamada.empresa_id == empresa_id
        ).first()
        if not camada:
            return {"success": False, "error": "Configure preço base (Camada B) primeiro"}

        custo = float(camada.custo_base_final or 0)
        preco_base = float(camada.preco_base or 0)

        # Tentar importar valor referência do edital
        vinculo = db.query(EditalItemProduto).filter(EditalItemProduto.id == edital_item_produto_id).first()
        if vinculo:
            item = db.query(EditalItem).filter(EditalItem.id == vinculo.edital_item_id).first()
            if item and item.valor_unitario_estimado and not valor_referencia:
                valor_referencia = float(item.valor_unitario_estimado)
                camada.valor_referencia_disponivel = True

        if valor_referencia:
            camada.valor_referencia_edital = valor_referencia
            camada.target_referencia = valor_referencia
            camada.valor_referencia_disponivel = True
        elif percentual_sobre_base and preco_base > 0:
            target = preco_base * (percentual_sobre_base / 100)
            camada.percentual_sobre_base = percentual_sobre_base
            camada.target_referencia = target
            camada.valor_referencia_disponivel = False
        else:
            return {"success": False, "error": "Informe valor_referencia ou percentual_sobre_base"}

        target = float(camada.target_referencia or 0)
        if custo > 0:
            camada.margem_sobre_custo = ((target - custo) / custo) * 100

        camada.updated_at = datetime.now()
        db.commit()

        return {
            "success": True,
            "mensagem": f"Target definido: R$ {target:.2f}",
            "comparativo": {
                "custo_base_A": custo,
                "preco_base_B": preco_base,
                "target_C": target,
            },
            "margem_sobre_custo": float(camada.margem_sobre_custo) if camada.margem_sobre_custo else None,
            "valor_referencia_disponivel": camada.valor_referencia_disponivel,
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_estruturar_lances(edital_item_produto_id: str, user_id: str, empresa_id: str = None,
                            lance_inicial: float = None,
                            lance_minimo: float = None,
                            modo_inicial: str = 'absoluto',
                            modo_minimo: str = 'absoluto',
                            desconto_maximo_pct: float = None) -> Dict[str, Any]:
    """UC-P07: Estrutura lances — Camadas D (inicial) e E (mínimo) com validações."""
    db = get_db()
    try:
        camada = db.query(PrecoCamada).filter(
            PrecoCamada.edital_item_produto_id == edital_item_produto_id,
            PrecoCamada.empresa_id == empresa_id
        ).first()
        if not camada:
            return {"success": False, "error": "Configure camadas A-C primeiro"}

        custo = float(camada.custo_base_final or 0)
        target = float(camada.target_referencia or camada.preco_base or 0)
        warnings = []

        # Camada D — Valor Inicial
        if modo_inicial == 'absoluto' and lance_inicial:
            camada.lance_inicial = lance_inicial
        elif modo_inicial == 'percentual_referencia' and target > 0:
            camada.lance_inicial = target  # Usar target como inicial
        camada.modo_lance_inicial = modo_inicial

        # Camada E — Valor Mínimo
        if modo_minimo == 'absoluto' and lance_minimo:
            camada.lance_minimo = lance_minimo
        elif modo_minimo == 'percentual_desconto' and desconto_maximo_pct and target > 0:
            lance_minimo = target * (1 - desconto_maximo_pct / 100)
            camada.lance_minimo = lance_minimo
            camada.desconto_maximo_percentual = desconto_maximo_pct
        camada.modo_lance_minimo = modo_minimo

        val_inicial = float(camada.lance_inicial or 0)
        val_minimo = float(camada.lance_minimo or 0)

        # Validações
        if val_minimo > val_inicial and val_inicial > 0:
            warnings.append("⚠️ Valor mínimo deve ser menor que o valor inicial")
        if val_minimo < custo and custo > 0:
            warnings.append("⚠️ Lance mínimo está abaixo do custo!")
        if custo > 0:
            camada.margem_minima = ((val_minimo - custo) / custo) * 100

        camada.status = 'parcial' if warnings else 'completo'
        camada.updated_at = datetime.now()
        db.commit()

        return {
            "success": True,
            "mensagem": f"Lances estruturados: Inicial R$ {val_inicial:.2f} → Mínimo R$ {val_minimo:.2f}",
            "lance_inicial": val_inicial,
            "lance_minimo": val_minimo,
            "custo_base": custo,
            "target": target,
            "margem_minima": float(camada.margem_minima) if camada.margem_minima else None,
            "faixa_disputa": f"R$ {val_minimo:.2f} — R$ {val_inicial:.2f}",
            "warnings": warnings,
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_estrategia_competitiva(edital_id: str, user_id: str,
                                 perfil: str = 'quero_ganhar',
                                 empresa_id: str = None) -> Dict[str, Any]:
    """UC-P08: Define e simula estratégia competitiva."""
    db = get_db()
    try:
        # Buscar ou criar estratégia
        estrategia = db.query(EstrategiaEdital).filter(
            EstrategiaEdital.edital_id == edital_id,
            EstrategiaEdital.empresa_id == empresa_id
        ).first()

        if not estrategia:
            estrategia = EstrategiaEdital(
                edital_id=edital_id,
                user_id=user_id,
                empresa_id=empresa_id,
            )
            db.add(estrategia)

        estrategia.perfil_competitivo = perfil
        estrategia.updated_at = datetime.now()

        # Buscar camadas do edital para simulação
        vinculos = db.query(EditalItemProduto).filter(
            EditalItemProduto.empresa_id == empresa_id
        ).join(EditalItem).filter(EditalItem.edital_id == edital_id).all()

        cenarios = []
        for v in vinculos:
            camada = db.query(PrecoCamada).filter(
                PrecoCamada.edital_item_produto_id == v.id
            ).first()
            if not camada:
                continue

            custo = float(camada.custo_base_final or 0)
            target = float(camada.target_referencia or camada.preco_base or 0)
            minimo = float(camada.lance_minimo or custo)

            if perfil == 'quero_ganhar':
                # 3 cenários agressivos
                cenarios.append({
                    "item": v.edital_item_id,
                    "cenario_1": {"valor": target, "margem": ((target - custo) / custo * 100) if custo else 0, "label": "Target"},
                    "cenario_2": {"valor": (target + minimo) / 2, "margem": (((target + minimo) / 2 - custo) / custo * 100) if custo else 0, "label": "Médio"},
                    "cenario_3": {"valor": minimo * 1.05, "margem": ((minimo * 1.05 - custo) / custo * 100) if custo else 0, "label": "Agressivo"},
                })
            else:
                # "não ganhei no mínimo" — reposicionar
                cenarios.append({
                    "item": v.edital_item_id,
                    "cenario_1": {"valor": minimo, "margem": ((minimo - custo) / custo * 100) if custo else 0, "label": "Mínimo"},
                    "cenario_2": {"valor": custo * 1.05, "margem": 5.0, "label": "Custo + 5%"},
                    "cenario_3": {"valor": custo, "margem": 0.0, "label": "Break-even"},
                })

        estrategia.cenarios_simulados = cenarios
        db.commit()

        return {
            "success": True,
            "mensagem": f"Estratégia '{perfil}' simulada com {len(cenarios)} item(ns)",
            "perfil": perfil,
            "cenarios": cenarios,
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_simular_lance(edital_item_produto_id: str, user_id: str, empresa_id: str = None,
                       num_rodadas: int = 10, tipo_decremento: str = 'fixo_reais',
                       valor_decremento: float = 10.0, num_concorrentes: int = 3,
                       perfil: str = 'quero_ganhar') -> Dict[str, Any]:
    """UC-LA01: Simulação determinística de lances rodada-a-rodada."""
    db = get_db()
    try:
        vinculo = db.query(EditalItemProduto).filter(
            EditalItemProduto.id == edital_item_produto_id,
            EditalItemProduto.empresa_id == empresa_id
        ).first()
        if not vinculo:
            return {"success": False, "error": "Vínculo item-produto não encontrado"}

        camada = db.query(PrecoCamada).filter(
            PrecoCamada.edital_item_produto_id == edital_item_produto_id
        ).first()
        if not camada:
            return {"success": False, "error": "Camadas A-E não configuradas (RN-098)"}

        custo = float(camada.custo_base_final or 0)
        lance_inicial = float(camada.lance_inicial or 0)
        lance_minimo = float(camada.lance_minimo or custo)

        if not lance_inicial or not custo:
            return {"success": False, "error": "lance_inicial e custo_base são obrigatórios (RN-098)"}
        if lance_minimo >= lance_inicial:
            return {"success": False, "error": "lance_minimo deve ser < lance_inicial (RN-099)"}

        import random
        random.seed(42)
        num_rodadas = max(3, min(num_rodadas, 30))

        concorrentes_iniciais = [lance_inicial * random.uniform(0.92, 1.02) for _ in range(num_concorrentes)]
        nosso_valor = lance_inicial
        rodadas = []

        for r in range(1, num_rodadas + 1):
            for i in range(num_concorrentes):
                if tipo_decremento == 'fixo_reais':
                    dec = valor_decremento * random.uniform(0.7, 1.3)
                else:
                    dec = concorrentes_iniciais[i] * (valor_decremento / 100) * random.uniform(0.7, 1.3)
                concorrentes_iniciais[i] = max(concorrentes_iniciais[i] - dec, custo * 0.95)

            lider = min(concorrentes_iniciais)
            if perfil == 'quero_ganhar':
                nosso_dec = valor_decremento if tipo_decremento == 'fixo_reais' else nosso_valor * (valor_decremento / 100)
                nosso_valor = max(lider - nosso_dec * 0.5, lance_minimo)
            else:
                nosso_valor = max(lider + valor_decremento * 0.3, lance_minimo)

            todos = sorted(concorrentes_iniciais + [nosso_valor])
            posicao = todos.index(nosso_valor) + 1
            margem = ((nosso_valor - custo) / custo * 100) if custo > 0 else 0

            rodadas.append({
                "rodada": r,
                "valor_nosso": round(nosso_valor, 4),
                "valores_concorrentes": [round(v, 4) for v in concorrentes_iniciais],
                "lider": round(min(concorrentes_iniciais), 4),
                "posicao": posicao,
                "margem": round(margem, 2),
                "abaixo_minimo": nosso_valor <= lance_minimo,
                "abaixo_custo": nosso_valor < custo,
            })

            if nosso_valor <= lance_minimo:
                break

        return {
            "success": True,
            "tipo": "simulacao_deterministica",
            "parametros": {
                "num_rodadas": len(rodadas),
                "tipo_decremento": tipo_decremento,
                "valor_decremento": valor_decremento,
                "num_concorrentes": num_concorrentes,
                "perfil": perfil,
            },
            "camadas": {
                "custo_base": custo,
                "lance_inicial": lance_inicial,
                "lance_minimo": lance_minimo,
            },
            "rodadas": rodadas,
            "resultado": {
                "posicao_final": rodadas[-1]["posicao"],
                "lance_final": rodadas[-1]["valor_nosso"],
                "margem_final": rodadas[-1]["margem"],
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_sugerir_lance(sessao_pregao_id: str, user_id: str, empresa_id: str = None,
                       lance_lider: float = 0, nosso_ultimo: float = 0,
                       custo_base: float = 0, lance_minimo: float = 0,
                       lance_inicial: float = 0, target: float = 0,
                       perfil: str = 'quero_ganhar', decremento_medio: float = 10.0) -> Dict[str, Any]:
    """UC-LA02: Sugestão inteligente de lance em tempo real."""
    if custo_base <= 0:
        return {"success": False, "error": "custo_base deve ser > 0 (RN-102)"}
    if lance_minimo >= lance_inicial:
        return {"success": False, "error": "lance_minimo deve ser < lance_inicial (RN-099)"}

    if perfil == 'quero_ganhar':
        lance_sugerido = lance_lider - decremento_medio
    else:
        lance_sugerido = lance_lider - (decremento_medio * 0.3)

    lance_sugerido = max(lance_sugerido, lance_minimo)

    if nosso_ultimo > 0 and lance_sugerido >= nosso_ultimo:
        lance_sugerido = nosso_ultimo - 1.0

    lance_sugerido = max(lance_sugerido, lance_minimo)

    margem = ((lance_sugerido - custo_base) / custo_base * 100)
    abaixo_custo = lance_sugerido < custo_base
    no_minimo = abs(lance_sugerido - lance_minimo) < 0.01

    if lance_lider <= 0:
        confianca = "baixa"
        justificativa = "Sem dados do líder — sugestão baseada em custo * 1.10 (RN-101)"
        lance_sugerido = custo_base * 1.10
        margem = 10.0
    elif abaixo_custo:
        confianca = "baixa"
        justificativa = "Lance abaixo do custo! Prejuízo potencial (RN-100)"
    elif no_minimo:
        confianca = "media"
        justificativa = "Lance no mínimo (Camada E). Último lance seguro"
    elif margem > 20:
        confianca = "alta"
        justificativa = f"Margem confortável de {margem:.1f}%"
    else:
        confianca = "media"
        justificativa = f"Margem de {margem:.1f}% — zona de atenção"

    posicao_estimada = 1 if lance_sugerido < lance_lider else 2

    return {
        "success": True,
        "lance_sugerido": round(lance_sugerido, 4),
        "margem_sobre_custo": round(margem, 2),
        "posicao_estimada": posicao_estimada,
        "confianca": confianca,
        "justificativa": justificativa,
        "abaixo_custo": abaixo_custo,
        "no_minimo": no_minimo,
        "perfil": perfil,
    }


def tool_score_competitividade(edital_id: str, user_id: str, empresa_id: str = None) -> Dict[str, Any]:
    """UC-SC01: Score de Competitividade 360° (0-100, 4 fatores ponderados)."""
    db = get_db()
    try:
        from sqlalchemy import func
        edital = db.query(Edital).filter(Edital.id == edital_id, Edital.empresa_id == empresa_id).first()
        if not edital:
            return {"success": False, "error": "Edital não encontrado"}

        # Fator 1 — Histórico similar (30%): editais ganhos/perdidos nos últimos 24m
        limite_24m = datetime.now() - timedelta(days=730)
        historicos = db.query(PrecoHistorico).join(Edital, PrecoHistorico.edital_id == Edital.id).filter(
            Edital.empresa_id == empresa_id,
            PrecoHistorico.data_registro >= limite_24m,
            PrecoHistorico.resultado.in_(['vitoria', 'derrota']),
        ).all()

        vitorias = sum(1 for h in historicos if h.resultado == 'vitoria')
        total_hist = len(historicos)
        bootstrap_pncp = total_hist < 5

        if total_hist > 0:
            fator_historico = (vitorias / total_hist) * 100
        else:
            fator_historico = 50.0

        # Fator 2 — Posição de preço (30%): percentil do nosso preço vs homologados
        vinculos = db.query(EditalItemProduto).filter(
            EditalItemProduto.empresa_id == empresa_id
        ).join(EditalItem).filter(EditalItem.edital_id == edital_id).all()

        if vinculos:
            camada = db.query(PrecoCamada).filter(
                PrecoCamada.edital_item_produto_id == vinculos[0].id
            ).first()
            if camada and camada.lance_inicial and camada.target_referencia:
                ratio = float(camada.lance_inicial) / float(camada.target_referencia)
                fator_preco = max(0, min(100, (1.2 - ratio) * 200))
            else:
                fator_preco = 50.0
        else:
            fator_preco = 50.0

        # Fator 3 — Concorrência (20%): taxa média de vitória dos concorrentes conhecidos (RN-074)
        concorrentes = db.query(Concorrente).all()
        if concorrentes:
            taxa_media = sum(float(c.taxa_vitoria or 0) for c in concorrentes) / len(concorrentes)
            fator_concorrencia = max(0, 100 - taxa_media)
        else:
            fator_concorrencia = 50.0

        # Fator 4 — Perfil órgão (20%): histórico com este órgão
        orgao = edital.orgao or ""
        hist_orgao = [h for h in historicos if db.query(Edital).filter(
            Edital.id == h.edital_id, Edital.orgao == orgao
        ).first()]
        if hist_orgao:
            vit_orgao = sum(1 for h in hist_orgao if h.resultado == 'vitoria')
            fator_orgao = (vit_orgao / len(hist_orgao)) * 100
        else:
            fator_orgao = 50.0

        score = round(
            fator_historico * 0.30 +
            fator_preco * 0.30 +
            fator_concorrencia * 0.20 +
            fator_orgao * 0.20,
            1
        )

        return {
            "success": True,
            "score": score,
            "fatores": [
                {"nome": "Histórico Similar", "peso": 30, "valor": round(fator_historico, 1)},
                {"nome": "Posição de Preço", "peso": 30, "valor": round(fator_preco, 1)},
                {"nome": "Concorrência", "peso": 20, "valor": round(fator_concorrencia, 1)},
                {"nome": "Perfil Órgão", "peso": 20, "valor": round(fator_orgao, 1)},
            ],
            "confianca": "alta" if total_hist >= 10 else ("media" if total_hist >= 5 else "baixa"),
            "bootstrap_pncp": bootstrap_pncp,
            "historicos_analisados": total_hist,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_score_qualidade_concorrente(concorrente_id: str = None, empresa_id: str = None) -> Dict[str, Any]:
    """UC-SC02: Score de Qualidade do Concorrente (RN-NEW-16)."""
    db = get_db()
    try:
        if concorrente_id:
            conc = db.query(Concorrente).filter(Concorrente.id == concorrente_id).first()
            if not conc:
                return {"success": False, "error": "Concorrente não encontrado"}

            participados = int(conc.editais_participados or 0)
            desclassificacoes = db.query(ParticipacaoEdital).filter(
                ParticipacaoEdital.concorrente_id == concorrente_id,
                ParticipacaoEdital.desclassificado == True,
            ).count()
            impugnacoes = 0

            score = 100 - ((desclassificacoes + impugnacoes) / max(participados, 1)) * 100
            score = max(0, min(100, round(score, 1)))

            if score >= 70:
                badge = "Alta"
            elif score >= 40:
                badge = "Media"
            else:
                badge = "Baixa"

            return {
                "success": True,
                "concorrente_id": concorrente_id,
                "nome": conc.nome,
                "score": score,
                "badge": badge,
                "editais_participados": participados,
                "desclassificacoes": desclassificacoes,
                "impugnacoes": impugnacoes,
            }
        else:
            return {"success": False, "error": "concorrente_id obrigatório"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_score_recurso(edital_id: str, user_id: str, empresa_id: str = None) -> Dict[str, Any]:
    """UC-SC03: Score Numérico de Recurso (0-100, 4 fatores, RN-NEW-17)."""
    db = get_db()
    try:
        edital = db.query(Edital).filter(Edital.id == edital_id, Edital.empresa_id == empresa_id).first()
        if not edital:
            return {"success": False, "error": "Edital não encontrado"}

        # Fator 1 — Desvios técnicos (40%): conta recursos com desvios
        recursos = db.query(Recurso).filter(
            Recurso.edital_id == edital_id,
            Recurso.empresa_id == empresa_id,
        ).all()
        desvios = sum(1 for r in recursos if r.tipo in ('analise_proposta', 'impugnacao'))
        fator_desvios = min(100, desvios * 25)

        # Fator 2 — Histórico empresa (20%): taxa de provimento
        todos_recursos = db.query(Recurso).filter(Recurso.empresa_id == empresa_id).all()
        providos = sum(1 for r in todos_recursos if r.status == 'provido')
        total_rec = len(todos_recursos)
        fator_hist_empresa = (providos / max(total_rec, 1)) * 100

        # Fator 3 — Histórico órgão (25%): taxa de provimento no órgão
        orgao = edital.orgao or ""
        rec_orgao = db.query(Recurso).join(Edital, Recurso.edital_id == Edital.id).filter(
            Edital.orgao == orgao,
            Recurso.empresa_id == empresa_id,
        ).all()
        providos_orgao = sum(1 for r in rec_orgao if r.status == 'provido')
        fator_hist_orgao = (providos_orgao / max(len(rec_orgao), 1)) * 100

        # Fator 4 — Fundamento legal (15%): gravidade (simplificado)
        fator_legal = min(100, len(recursos) * 20)

        score = round(
            fator_desvios * 0.40 +
            fator_hist_empresa * 0.20 +
            fator_hist_orgao * 0.25 +
            fator_legal * 0.15,
            1
        )

        if score >= 70:
            recomendacao = "Recurso recomendado"
        elif score >= 30:
            recomendacao = "Inconclusivo"
        else:
            recomendacao = "Não recomendado"

        return {
            "success": True,
            "score": score,
            "recomendacao": recomendacao,
            "fatores": [
                {"nome": "Desvios Técnicos", "peso": 40, "valor": round(fator_desvios, 1)},
                {"nome": "Histórico Empresa", "peso": 20, "valor": round(fator_hist_empresa, 1)},
                {"nome": "Histórico Órgão", "peso": 25, "valor": round(fator_hist_orgao, 1)},
                {"nome": "Fundamento Legal", "peso": 15, "valor": round(fator_legal, 1)},
            ],
            "recursos_encontrados": len(recursos),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_dre_contrato(contrato_id: str = None, edital_id: str = None,
                      user_id: str = None, empresa_id: str = None) -> Dict[str, Any]:
    """UC-SC05: DRE simplificado por contrato ou simulação (RN-NEW-18)."""
    db = get_db()
    try:
        if contrato_id:
            contrato = db.query(Contrato).filter(
                Contrato.id == contrato_id, Contrato.empresa_id == empresa_id
            ).first()
            if not contrato:
                return {"success": False, "error": "Contrato não encontrado"}

            valor_total = float(contrato.valor_total or 0)
            eid = contrato.edital_id
        elif edital_id:
            eid = edital_id
            vinculos = db.query(EditalItemProduto).filter(
                EditalItemProduto.empresa_id == empresa_id
            ).join(EditalItem).filter(EditalItem.edital_id == edital_id).all()
            valor_total = 0
            for v in vinculos:
                c = db.query(PrecoCamada).filter(PrecoCamada.edital_item_produto_id == v.id).first()
                if c and c.lance_inicial:
                    valor_total += float(c.lance_inicial)
        else:
            return {"success": False, "error": "contrato_id ou edital_id obrigatório"}

        vinculos = db.query(EditalItemProduto).filter(
            EditalItemProduto.empresa_id == empresa_id
        ).join(EditalItem).filter(EditalItem.edital_id == eid).all()

        custo_total = 0
        impostos_total = 0
        for v in vinculos:
            camada = db.query(PrecoCamada).filter(PrecoCamada.edital_item_produto_id == v.id).first()
            if camada:
                custo_total += float(camada.custo_base_final or 0)
                icms = float(camada.icms or 0) / 100.0
                ipi = float(camada.ipi or 0) / 100.0
                pis_cofins = float(getattr(camada, 'pis_cofins', 0) or 0) / 100.0
                impostos_total += valor_total * (icms + ipi + pis_cofins) / max(len(vinculos), 1)

        receita_bruta = valor_total
        receita_liquida = receita_bruta - impostos_total
        resultado_operacional = receita_liquida - custo_total
        margem = (resultado_operacional / receita_bruta * 100) if receita_bruta > 0 else 0

        if margem > 20:
            badge = "verde"
        elif margem >= 10:
            badge = "amarelo"
        else:
            badge = "vermelho"

        return {
            "success": True,
            "tipo": "realizado" if contrato_id else "simulado",
            "linhas": [
                {"descricao": "Receita Bruta", "valor": round(receita_bruta, 2)},
                {"descricao": "(-) Impostos", "valor": round(-impostos_total, 2)},
                {"descricao": "= Receita Líquida", "valor": round(receita_liquida, 2)},
                {"descricao": "(-) Custos (Camada A)", "valor": round(-custo_total, 2)},
                {"descricao": "= Resultado Operacional", "valor": round(resultado_operacional, 2)},
            ],
            "margem_percentual": round(margem, 2),
            "badge": badge,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_historico_precos_camada_f(edital_item_produto_id: str, user_id: str, empresa_id: str = None,
                                    termo: str = None) -> Dict[str, Any]:
    """UC-P09: Consulta histórico de preços e preenche Camada F."""
    db = get_db()
    try:
        vinculo = db.query(EditalItemProduto).filter(
            EditalItemProduto.id == edital_item_produto_id,
            EditalItemProduto.empresa_id == empresa_id
        ).first()

        produto = db.query(Produto).filter(Produto.id == vinculo.produto_id).first() if vinculo else None
        termo_busca = termo or (produto.nome if produto else None)

        if not termo_busca:
            return {"success": False, "error": "Informe um termo de busca"}

        # Buscar no PNCP
        resultado_pncp = tool_buscar_precos_pncp(termo=termo_busca, meses=24, user_id=user_id)

        # Buscar histórico interno
        historico_db = db.query(PrecoHistorico).filter(
            PrecoHistorico.empresa_id == empresa_id
        ).order_by(PrecoHistorico.created_at.desc()).limit(50).all()

        # Calcular estatísticas
        precos = []
        if resultado_pncp.get("success") and resultado_pncp.get("resultados"):
            for r in resultado_pncp["resultados"]:
                val = r.get("valor_unitario") or r.get("preco_unitario")
                if val:
                    precos.append(float(val))

        for h in historico_db:
            if h.valor_unitario:
                precos.append(float(h.valor_unitario))

        preco_medio = sum(precos) / len(precos) if precos else None
        preco_min = min(precos) if precos else None
        preco_max = max(precos) if precos else None

        # Atualizar Camada F na PrecoCamada
        if vinculo:
            camada = db.query(PrecoCamada).filter(
                PrecoCamada.edital_item_produto_id == edital_item_produto_id,
                PrecoCamada.empresa_id == empresa_id
            ).first()

            if camada:
                camada.preco_medio_historico = preco_medio
                camada.preco_min_historico = preco_min
                camada.preco_max_historico = preco_max
                camada.qtd_registros_historico = len(precos)
                camada.updated_at = datetime.now()
                db.commit()

        return {
            "success": True,
            "mensagem": f"Histórico: {len(precos)} registros encontrados",
            "termo": termo_busca,
            "preco_medio": round(preco_medio, 2) if preco_medio else None,
            "preco_min": round(preco_min, 2) if preco_min else None,
            "preco_max": round(preco_max, 2) if preco_max else None,
            "qtd_registros": len(precos),
            "resultados_pncp": resultado_pncp.get("resultados", [])[:20],
            "historico_interno": [h.to_dict() for h in historico_db[:20]] if historico_db else [],
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_gestao_comodato(edital_id: str, user_id: str,
                          nome_equipamento: str = None,
                          valor_equipamento: float = None,
                          duracao_meses: int = None,
                          custo_manutencao_mensal: float = None,
                          custo_instalacao: float = None,
                          condicoes_especiais: str = None,
                          produto_equipamento_id: str = None,
                          empresa_id: str = None,
                          comodato_id: str = None) -> Dict[str, Any]:
    """UC-P10: Gestão de comodato — cadastra/atualiza equipamento em comodato."""
    db = get_db()
    try:
        if comodato_id:
            comodato = db.query(Comodato).filter(
                Comodato.id == comodato_id, Comodato.empresa_id == empresa_id
            ).first()
            if not comodato:
                return {"success": False, "error": "Comodato não encontrado"}
        else:
            comodato = Comodato(
                edital_id=edital_id,
                user_id=user_id,
                empresa_id=empresa_id,
                nome_equipamento=nome_equipamento or "Equipamento",
            )
            db.add(comodato)

        if nome_equipamento:
            comodato.nome_equipamento = nome_equipamento
        if valor_equipamento is not None:
            comodato.valor_equipamento = valor_equipamento
        if duracao_meses is not None:
            comodato.duracao_meses = duracao_meses
        if custo_manutencao_mensal is not None:
            comodato.custo_manutencao_mensal = custo_manutencao_mensal
        if custo_instalacao is not None:
            comodato.custo_instalacao = custo_instalacao
        if condicoes_especiais is not None:
            comodato.condicoes_especiais = condicoes_especiais
        if produto_equipamento_id:
            comodato.produto_equipamento_id = produto_equipamento_id

        # Calcular amortização
        valor = float(comodato.valor_equipamento or 0)
        meses = comodato.duracao_meses or 0
        if valor > 0 and meses > 0:
            comodato.valor_mensal_amortizacao = valor / meses

        comodato.updated_at = datetime.now()
        db.commit()

        return {
            "success": True,
            "mensagem": f"Comodato '{comodato.nome_equipamento}' salvo",
            "comodato": comodato.to_dict(),
            "amortizacao_mensal": float(comodato.valor_mensal_amortizacao) if comodato.valor_mensal_amortizacao else None,
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# Registrar tools FASE 1 no TOOLS_MAP
TOOLS_MAP["organizar_lotes"] = tool_organizar_lotes
TOOLS_MAP["selecao_portfolio"] = tool_selecao_portfolio
TOOLS_MAP["calcular_volumetria"] = tool_calcular_volumetria
TOOLS_MAP["configurar_custos"] = tool_configurar_custos
TOOLS_MAP["montar_preco_base"] = tool_montar_preco_base
TOOLS_MAP["definir_referencia"] = tool_definir_referencia
TOOLS_MAP["estruturar_lances"] = tool_estruturar_lances
TOOLS_MAP["estrategia_competitiva"] = tool_estrategia_competitiva
TOOLS_MAP["historico_precos_camada_f"] = tool_historico_precos_camada_f
TOOLS_MAP["gestao_comodato"] = tool_gestao_comodato

# Sprint 9 tools
TOOLS_MAP["simular_lance"] = tool_simular_lance
TOOLS_MAP["sugerir_lance"] = tool_sugerir_lance
TOOLS_MAP["score_competitividade"] = tool_score_competitividade
TOOLS_MAP["score_qualidade_concorrente"] = tool_score_qualidade_concorrente
TOOLS_MAP["score_recurso"] = tool_score_recurso
TOOLS_MAP["dre_contrato"] = tool_dre_contrato


def tool_extrair_vencedores_atas(atas: list, user_id: str, empresa_id: str = None, edital_id: str = None) -> Dict[str, Any]:
    """Extrai vencedores e preços de atas PNCP e salva em precos_historicos + concorrentes."""
    import requests as req
    import re as _re
    db = get_db()
    try:
        empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first() if empresa_id else None
        resultados = []
        precos_extraidos = []

        for ata in atas[:5]:
            cnpj = ata.get("cnpj_orgao") or ""
            ano = ata.get("ano")
            seq_compra = None
            url_pncp = ata.get("url_pncp") or ""
            match_url = _re.search(r'/atas/\d+/\d+/(\d+)/\d+', url_pncp)
            if match_url:
                seq_compra = int(match_url.group(1))
            else:
                nc = ata.get("numero_controle") or ""
                match_nc = _re.search(r'\d{14}-\d+-(\d+)/\d+-\d+', nc)
                if match_nc:
                    seq_compra = int(match_nc.group(1))
            if not cnpj or not ano or not seq_compra:
                continue
            try:
                url_itens = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq_compra}/itens"
                resp = req.get(url_itens, timeout=15, headers={"Accept": "application/json"})
                if resp.status_code != 200:
                    continue
                itens = resp.json()
                if not isinstance(itens, list):
                    continue
                vencedores_ata = []
                for it in itens[:10]:
                    num_item = it.get("numeroItem")
                    if not num_item:
                        continue
                    try:
                        url_r = f"https://pncp.gov.br/api/pncp/v1/orgaos/{cnpj}/compras/{ano}/{seq_compra}/itens/{num_item}/resultados"
                        resp_r = req.get(url_r, timeout=10, headers={"Accept": "application/json"})
                        if resp_r.status_code == 200:
                            res_item = resp_r.json()
                            if isinstance(res_item, list) and res_item:
                                r = res_item[0]
                                v_data = {
                                    "item": num_item,
                                    "descricao": str(it.get("descricao", ""))[:80],
                                    "quantidade": it.get("quantidade"),
                                    "valor_estimado": it.get("valorUnitarioEstimado"),
                                    "vencedor": r.get("nomeRazaoSocialFornecedor"),
                                    "cnpj_vencedor": r.get("niFornecedor"),
                                    "valor_homologado": r.get("valorUnitarioHomologado"),
                                    "qtd_homologada": r.get("quantidadeHomologada"),
                                    "valor_total_homologado": r.get("valorTotalHomologado"),
                                }
                                vencedores_ata.append(v_data)
                                if v_data["valor_homologado"]:
                                    precos_extraidos.append(float(v_data["valor_homologado"]))
                    except Exception:
                        pass
                if vencedores_ata:
                    resultados.append({
                        "ata_titulo": ata.get("titulo") or f"Ata {ano}/{seq_compra}",
                        "orgao": ata.get("orgao"),
                        "vencedores": vencedores_ata,
                    })
            except Exception:
                pass

        # Salvar no banco
        salvos_c = 0
        salvos_p = 0
        cnpjs_cache = {}
        for res_ata in resultados:
            for v in res_ata.get("vencedores", []):
                cnpj_v = (v.get("cnpj_vencedor") or "").replace(".", "").replace("/", "").replace("-", "")
                nome_v = v.get("vencedor")
                if not nome_v:
                    continue
                conc = cnpjs_cache.get(cnpj_v) if cnpj_v else None
                if not conc and cnpj_v:
                    conc = db.query(Concorrente).filter(Concorrente.cnpj == cnpj_v).first()
                if not conc and nome_v:
                    conc = db.query(Concorrente).filter(Concorrente.nome.ilike(f"%{nome_v[:20]}%")).first()
                if not conc:
                    conc = Concorrente(id=str(uuid.uuid4()), nome=nome_v, cnpj=cnpj_v or None, editais_participados=1, editais_ganhos=1)
                    db.add(conc)
                    db.flush()
                    salvos_c += 1
                else:
                    conc.editais_participados = (conc.editais_participados or 0) + 1
                    conc.editais_ganhos = (conc.editais_ganhos or 0) + 1
                if cnpj_v:
                    cnpjs_cache[cnpj_v] = conc
                try:
                    ph = PrecoHistorico(
                        id=str(uuid.uuid4()), edital_id=edital_id, user_id=user_id,
                        empresa_id=empresa_id, concorrente_id=conc.id,
                        preco_referencia=v.get("valor_estimado"), preco_vencedor=v.get("valor_homologado"),
                        empresa_vencedora=nome_v, cnpj_vencedor=cnpj_v or None,
                        resultado="derrota", fonte="pncp", data_registro=datetime.now(),
                    )
                    if v.get("valor_estimado") and v.get("valor_homologado") and v["valor_estimado"] > 0:
                        ph.desconto_percentual = round((1 - v["valor_homologado"] / v["valor_estimado"]) * 100, 2)
                    db.add(ph)
                    salvos_p += 1
                except Exception:
                    pass
        try:
            db.commit()
        except Exception:
            db.rollback()

        # Stats dos preços extraídos
        stats = {}
        if precos_extraidos:
            stats = {
                "qtd_registros": len(precos_extraidos),
                "preco_min": round(min(precos_extraidos), 2),
                "preco_medio": round(sum(precos_extraidos) / len(precos_extraidos), 2),
                "preco_max": round(max(precos_extraidos), 2),
            }
        return {
            "success": len(resultados) > 0,
            "resultados": resultados,
            "total_atas": len(resultados),
            "precos_extraidos": precos_extraidos,
            "stats": stats,
            "salvos": {"concorrentes": salvos_c, "precos_historicos": salvos_p},
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


TOOLS_MAP["extrair_vencedores_atas"] = tool_extrair_vencedores_atas


def tool_insights_precificacao(eip_id: str, user_id: str, empresa_id: str = None) -> Dict[str, Any]:
    """Pipeline completo: histórico local → buscar atas PNCP → extrair preços → sugerir valores."""
    import re, unicodedata
    db = get_db()
    try:
        vinculo = db.query(EditalItemProduto).filter(
            EditalItemProduto.id == eip_id, EditalItemProduto.empresa_id == empresa_id
        ).first()
        if not vinculo:
            return {"success": False, "error": "Vínculo não encontrado"}

        produto = db.query(Produto).filter(Produto.id == vinculo.produto_id).first()
        item = db.query(EditalItem).filter(EditalItem.id == vinculo.edital_item_id).first()
        edital = db.query(Edital).filter(Edital.id == item.edital_id).first() if item else None
        edital_id = edital.id if edital else None

        # Construir termos de busca progressivos
        nome_prod = produto.nome if produto else ""
        desc_item = item.descricao if item else ""
        paren = re.search(r'\(([^)]{2,30})\)', desc_item)
        tipo_analise = re.search(r'tipo de an[aá]lise:\s*([^,]{3,60})', desc_item, re.I)
        nome_curto = paren.group(1) if paren else (tipo_analise.group(1).strip() if tipo_analise else "")
        stop = {"kit", "para", "de", "do", "da", "com", "tipo", "reagente", "diagnostico", "clinico"}
        def _norm(s):
            return unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode()
        palavras_prod = [w for w in _norm(nome_prod).split() if len(w) > 2 and w not in stop]

        termos_busca = []
        if nome_curto:
            termos_busca.append(nome_curto)
        if palavras_prod:
            termos_busca.append(" ".join(palavras_prod[:3]))
        if nome_prod and nome_prod not in termos_busca:
            termos_busca.append(nome_prod)
        if not termos_busca:
            termos_busca = [desc_item[:60] if desc_item else ""]

        historico = {"qtd_registros": 0, "preco_min": None, "preco_medio": None, "preco_max": None}
        atas_encontradas = []
        atas_detalhes = []  # lista de atas com metadata
        vencedores_detalhes = []  # lista de resultados com vencedores por ata
        etapa = "inicio"
        termo_usado = ""

        # === ETAPA 1: Histórico local ===
        for termo in termos_busca:
            if not termo.strip():
                continue
            etapa = f"historico_local:{termo}"
            hist_result = tool_historico_precos(termo=termo, user_id=user_id)
            if hist_result.get("success") and hist_result.get("estatisticas", {}).get("total_registros", 0) > 0:
                stats = hist_result["estatisticas"]
                historico = {
                    "qtd_registros": stats["total_registros"],
                    "preco_min": stats.get("preco_minimo"),
                    "preco_medio": stats.get("preco_medio"),
                    "preco_max": stats.get("preco_maximo"),
                }
                termo_usado = termo
                etapa = "historico_local_ok"
                break

        # === ETAPA 2: Se não tem local → buscar atas PNCP + extrair vencedores ===
        if historico["qtd_registros"] == 0:
            for termo in termos_busca:
                if not termo.strip():
                    continue
                etapa = f"busca_atas:{termo}"
                atas_result = tool_buscar_atas_pncp(termo=termo, user_id=user_id)
                if atas_result.get("success") and atas_result.get("atas"):
                    atas_encontradas = atas_result["atas"][:5]
                    etapa = f"extraindo_vencedores:{len(atas_encontradas)}_atas"
                    # Extrair vencedores e salvar no banco
                    ext_result = tool_extrair_vencedores_atas(
                        atas=atas_encontradas, user_id=user_id, edital_id=edital_id
                    )
                    if ext_result.get("success") and ext_result.get("stats"):
                        historico = ext_result["stats"]
                        vencedores_detalhes = ext_result.get("resultados", [])
                        atas_detalhes = [{
                            "titulo": a.get("titulo", ""),
                            "orgao": a.get("orgao", ""),
                            "uf": a.get("uf", ""),
                            "url_pncp": a.get("url_pncp", ""),
                            "data_publicacao": a.get("data_publicacao", ""),
                        } for a in atas_encontradas]
                        termo_usado = termo
                        etapa = "atas_extraidas_ok"
                        break

        # === ETAPA 3: Se não tem atas → buscar contratos PNCP ===
        if historico["qtd_registros"] == 0:
            for termo in termos_busca:
                if not termo.strip():
                    continue
                etapa = f"busca_contratos:{termo}"
                pncp_result = tool_buscar_precos_pncp(termo=termo, meses=24, user_id=user_id)
                if pncp_result.get("success") and pncp_result.get("estatisticas"):
                    stats = pncp_result["estatisticas"]
                    if stats.get("preco_medio"):
                        historico = {
                            "qtd_registros": pncp_result.get("total_contratos", 0),
                            "preco_min": stats.get("preco_minimo"),
                            "preco_medio": stats.get("preco_medio"),
                            "preco_max": stats.get("preco_maximo"),
                        }
                        termo_usado = termo
                        etapa = "contratos_pncp_ok"
                        break

        # === Concorrentes — extrair dos vencedores das atas (não global) ===
        concorrentes: list = []
        if vencedores_detalhes:
            conc_map: Dict[str, Dict[str, Any]] = {}
            for res in vencedores_detalhes:
                for v in (res.get("vencedores") or []):
                    nome_v = v.get("vencedor") or ""
                    if not nome_v:
                        continue
                    if nome_v not in conc_map:
                        conc_map[nome_v] = {"nome": nome_v, "vitorias": 0, "precos": []}
                    conc_map[nome_v]["vitorias"] += 1
                    if v.get("valor_homologado"):
                        conc_map[nome_v]["precos"].append(float(v["valor_homologado"]))
            for c in sorted(conc_map.values(), key=lambda x: x["vitorias"], reverse=True)[:5]:
                preco_m = round(sum(c["precos"]) / len(c["precos"]), 2) if c["precos"] else 0
                concorrentes.append({
                    "nome": c["nome"],
                    "taxa_vitoria": 0,
                    "preco_medio": preco_m,
                    "editais_ganhos": c["vitorias"],
                })
        if not concorrentes:
            try:
                concs = db.query(Concorrente).order_by(Concorrente.editais_ganhos.desc()).limit(5).all()
                for c in concs:
                    concorrentes.append({
                        "nome": c.nome,
                        "taxa_vitoria": float(c.taxa_vitoria) if c.taxa_vitoria else 0,
                        "preco_medio": float(c.preco_medio) if c.preco_medio else 0,
                        "editais_ganhos": c.editais_ganhos or 0,
                    })
            except Exception:
                pass

        # === ETAPA 4: Calcular sugestões com os dados disponíveis ===
        recomendacao = {
            "custo_sugerido": None, "markup_sugerido": None,
            "preco_base_sugerido": None, "referencia_sugerida": None,
            "lance_inicial_sugerido": None, "lance_minimo_sugerido": None,
            "faixa": {"agressivo": None, "ideal": None, "conservador": None},
            "justificativa": "Sem dados suficientes para recomendação.",
            "fonte": None,
        }
        ref_edital = float(item.valor_unitario_estimado) if item and item.valor_unitario_estimado else None

        if historico["qtd_registros"] > 0 and historico["preco_medio"]:
            p_min = float(historico["preco_min"] or historico["preco_medio"])
            p_med = float(historico["preco_medio"])
            p_max = float(historico["preco_max"] or historico["preco_medio"])

            # Usar mediana dos preços para sugestão (mais robusto que mínimo)
            # Se variação > 5x entre min e max, provável diferença de unidade de medida
            variacao_alta = (p_max / p_min) > 5 if p_min > 0 else False
            # Custo: usar percentil 25 (entre mínimo e média) se variação alta
            p_custo_ref = round((p_min + p_med) / 2, 2) if variacao_alta else p_min
            custo_sug = round(p_custo_ref * 0.85, 2)
            preco_base_sug = round(p_med * 0.97, 2)  # ideal
            ref_sug = ref_edital or round(p_med * 0.99, 2)  # conservador
            lance_ini_sug = preco_base_sug
            lance_min_sug = round(custo_sug * 1.10, 2)  # margem mínima 10%
            markup_sug = round(((preco_base_sug / custo_sug) - 1) * 100, 1) if custo_sug > 0 else None

            # Gerar justificativa detalhada via IA
            justificativa_ia = ""
            try:
                # Montar contexto para a IA
                venc_resumo = ""
                for res in vencedores_detalhes[:3]:
                    for v in (res.get("vencedores") or [])[:5]:
                        venc_resumo += f"- {v.get('descricao','')}: vencedor {v.get('vencedor','')}, estimado R$ {v.get('valor_estimado','?')}, homologado R$ {v.get('valor_homologado','?')}\n"
                conc_resumo = ", ".join([f"{c['nome']} (preço médio: R$ {c['preco_medio']:.2f})" for c in concorrentes[:3]]) if concorrentes else "Sem dados"
                alerta_unidade = ""
                if variacao_alta:
                    alerta_unidade = f"\n⚠️ ATENÇÃO: Alta variação de preços (R$ {p_min:.2f} a R$ {p_max:.2f}, ratio {p_max/p_min:.1f}x). Provável diferença de unidade de medida entre as atas (preço por teste vs por kit/caixa). Analise os itens individuais para verificar."

                # Informações do item do edital
                qtd_edital = item.quantidade if item else None
                unidade_edital = getattr(item, 'unidade_medida', None) if item else None
                rendimento_kit = curVinculo_rend = vinculo.rendimento_produto if vinculo else None

                prompt_just = f"""Analise os dados de preços históricos de licitações para o produto "{nome_prod}" e justifique as sugestões de preço.

PRODUTO: {nome_prod}
ITEM DO EDITAL: {desc_item[:150] if desc_item else 'N/A'}
QUANTIDADE DO EDITAL: {int(float(qtd_edital)) if qtd_edital else 'N/A'} unidades
RENDIMENTO POR KIT/EMBALAGEM: {int(float(rendimento_kit)) if rendimento_kit else 'N/A'} testes/kit

DADOS DO MERCADO:
- {historico['qtd_registros']} registros de atas extraídas do PNCP
- Preço mínimo homologado: R$ {p_min:.2f}
- Preço médio homologado: R$ {p_med:.2f}
- Preço máximo homologado: R$ {p_max:.2f}
- Valor de referência do edital: {f'R$ {ref_edital:.2f}' if ref_edital else 'Não disponível'}{alerta_unidade}

VENCEDORES RECENTES (das atas do PNCP):
{venc_resumo or 'Sem detalhes disponíveis'}

CONCORRENTES IDENTIFICADOS: {conc_resumo}

SUGESTÕES CALCULADAS:
- Custo sugerido (A): R$ {custo_sug:.2f} {'(média entre mínimo e médio × 85%, devido à alta variação)' if variacao_alta else '(85% do preço mínimo)'}
- Preço base (B): R$ {preco_base_sug:.2f} (97% da média = preço competitivo)
- Referência/Target (C): R$ {ref_sug:.2f}
- Lance inicial (D): R$ {lance_ini_sug:.2f}
- Lance mínimo (E): R$ {lance_min_sug:.2f} (custo + 10% margem)

REGRAS IMPORTANTES PARA SUA ANÁLISE:
- NÃO invente números nem multiplique quantidades. Use exatamente os valores informados acima.
- Quando a ata tem múltiplos itens com preços diferentes (ex: item 1 = R$ 2,70, item 4 = R$ 28,00), são REAGENTES DIFERENTES (ex: TTPA, TP, Fibrinogênio), NÃO o mesmo produto em unidades diferentes.
- Cada item da ata é um reagente/exame diferente. A variação de preço reflete a complexidade de cada exame, não diferença de embalagem.

Escreva uma justificativa técnica em 4-6 parágrafos curtos explicando:
1. De onde vieram os dados (atas do PNCP) e qual a confiabilidade
2. Análise dos preços: identifique qual(is) item(ns) da ata correspondem ao produto "{nome_curto or nome_prod}" e use esses preços como referência principal
3. Por que cada preço sugerido foi calculado dessa forma
4. Concorrentes identificados e seus padrões de preço
5. Riscos e oportunidades considerando o mercado
6. Recomendação final (se deve ser agressivo ou conservador)

Responda em português, direto ao ponto, sem enrolação."""

                justificativa_ia = call_deepseek(
                    [{"role": "user", "content": prompt_just}],
                    max_tokens=1000,
                    model_override="deepseek-chat"
                )
            except Exception as e:
                justificativa_ia = f"Baseado em {historico['qtd_registros']} registros. Preço médio: R$ {p_med:,.2f}, mínimo: R$ {p_min:,.2f}. (Erro ao gerar análise detalhada: {e})"

            recomendacao = {
                "custo_sugerido": custo_sug,
                "markup_sugerido": markup_sug,
                "preco_base_sugerido": preco_base_sug,
                "referencia_sugerida": ref_sug,
                "lance_inicial_sugerido": lance_ini_sug,
                "lance_minimo_sugerido": lance_min_sug,
                "faixa": {
                    "agressivo": round(p_med * 0.95, 2),
                    "ideal": round(p_med * 0.97, 2),
                    "conservador": round(p_med * 0.99, 2),
                },
                "justificativa": justificativa_ia,
                "fonte": etapa.split(":")[0] if ":" in etapa else etapa,
            }

        tem_dados = (historico["qtd_registros"] > 0 or ref_edital is not None)

        resultado = {
            "success": True,
            "tem_dados": tem_dados,
            "termo_usado": termo_usado,
            "termos_tentados": termos_busca,
            "etapa": etapa,
            "historico": historico,
            "recomendacao": recomendacao,
            "concorrentes": concorrentes,
            "referencia_edital": ref_edital,
            "atas_encontradas": len(atas_encontradas),
            "atas_detalhes": atas_detalhes,
            "vencedores_detalhes": vencedores_detalhes,
        }

        # Persistir análise IA na PrecoCamada
        try:
            import json as _json
            camada = db.query(PrecoCamada).filter(
                PrecoCamada.edital_item_produto_id == eip_id,
                PrecoCamada.empresa_id == empresa_id
            ).first()
            if camada:
                camada.analise_ia_json = _json.dumps(resultado, ensure_ascii=False, default=str)
                camada.analise_ia_data = datetime.now()
                camada.analise_ia_termo = termo_usado
                db.commit()
        except Exception:
            pass  # Não falhar por causa da persistência

        return resultado
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


TOOLS_MAP["insights_precificacao"] = tool_insights_precificacao


# =============================================================================
# FASE 2 — PROPOSTA: Novas tools (UC-R01 a UC-R07)
# =============================================================================

def tool_verificar_anvisa_proposta(proposta_id: str, user_id: str, empresa_id: str = None) -> Dict[str, Any]:
    """
    Verifica status ANVISA do produto vinculado à proposta.
    Calcula semáforo: valido (verde), atencao (amarelo <6 meses), vencido (vermelho), sem_registro.
    Salva registro AnvisaValidacao.
    """
    db = get_db()
    try:
        proposta = db.query(Proposta).filter(
            Proposta.id == proposta_id,
            Proposta.empresa_id == empresa_id
        ).first()
        if not proposta:
            return {"success": False, "error": "Proposta não encontrada"}

        produto = db.query(Produto).filter(Produto.id == proposta.produto_id).first()
        if not produto:
            return {"success": False, "error": "Produto não encontrado"}

        # Determinar status baseado nos campos do produto
        registro = produto.registro_anvisa
        anvisa_status_produto = produto.anvisa_status  # ativo, em_analise, cancelado, null

        status = 'sem_registro'
        log_lines = []
        validade_date = None

        if not registro:
            status = 'sem_registro'
            log_lines.append("Produto sem registro ANVISA cadastrado.")
        elif anvisa_status_produto == 'cancelado':
            status = 'vencido'
            log_lines.append(f"Registro ANVISA {registro} com status CANCELADO.")
        elif anvisa_status_produto == 'em_analise':
            status = 'atencao'
            log_lines.append(f"Registro ANVISA {registro} em análise/renovação.")
        elif anvisa_status_produto == 'ativo':
            status = 'valido'
            log_lines.append(f"Registro ANVISA {registro} ATIVO.")
        else:
            # Status desconhecido — tratar como atenção
            status = 'atencao'
            log_lines.append(f"Registro ANVISA {registro} com status indefinido ({anvisa_status_produto}).")

        log_texto = "\n".join(log_lines)

        # Salvar/atualizar AnvisaValidacao
        validacao = db.query(AnvisaValidacao).filter(
            AnvisaValidacao.proposta_id == proposta_id,
            AnvisaValidacao.produto_id == produto.id
        ).first()

        if validacao:
            validacao.registro = registro
            validacao.validade = validade_date
            validacao.status = status
            validacao.data_verificacao = datetime.now()
            validacao.log_texto = log_texto
        else:
            validacao = AnvisaValidacao(
                proposta_id=proposta_id,
                produto_id=produto.id,
                registro=registro,
                validade=validade_date,
                status=status,
                log_texto=log_texto,
            )
            db.add(validacao)

        db.commit()

        return {
            "success": True,
            "proposta_id": proposta_id,
            "produto_id": produto.id,
            "produto_nome": produto.nome,
            "registro_anvisa": registro,
            "status": status,
            "log": log_texto,
            "validacao_id": validacao.id,
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


TOOLS_MAP["verificar_anvisa_proposta"] = tool_verificar_anvisa_proposta


def tool_auditoria_documental(proposta_id: str, user_id: str, empresa_id: str = None) -> Dict[str, Any]:
    """
    Audita documentos necessários para a proposta.
    Compara documentos exigidos (DocumentoNecessario) com documentos disponíveis do produto e empresa.
    Verifica tamanho de arquivos (limite 25MB).
    Retorna checklist com status por documento.
    """
    db = get_db()
    try:
        proposta = db.query(Proposta).filter(
            Proposta.id == proposta_id,
            Proposta.empresa_id == empresa_id
        ).first()
        if not proposta:
            return {"success": False, "error": "Proposta não encontrada"}

        produto = db.query(Produto).filter(Produto.id == proposta.produto_id).first()
        empresa = db.query(Empresa).filter(Empresa.id == proposta.empresa_id).first() if proposta.empresa_id else None

        # Buscar documentos necessários ativos
        docs_necessarios = db.query(DocumentoNecessario).filter(
            DocumentoNecessario.ativo == True
        ).order_by(DocumentoNecessario.ordem).all()

        # Buscar documentos do produto
        docs_produto = db.query(ProdutoDocumento).filter(
            ProdutoDocumento.produto_id == proposta.produto_id
        ).all() if produto else []

        # Buscar documentos da empresa
        docs_empresa = db.query(EmpresaDocumento).filter(
            EmpresaDocumento.empresa_id == proposta.empresa_id
        ).all() if empresa else []

        # Mapear documentos disponíveis por tipo
        docs_disponiveis = {}
        for d in docs_produto:
            docs_disponiveis[d.tipo] = {
                "nome": d.nome_arquivo,
                "path": d.path_arquivo,
                "fonte": "produto",
            }
        for d in docs_empresa:
            docs_disponiveis[d.tipo] = {
                "nome": d.nome_arquivo,
                "path": d.path_arquivo,
                "fonte": "empresa",
            }

        # Montar checklist
        checklist = []
        MAX_SIZE_MB = 25
        total_ok = 0
        total_faltando = 0
        total_alerta = 0

        for doc_req in docs_necessarios:
            item = {
                "documento": doc_req.nome,
                "tipo_chave": doc_req.tipo_chave,
                "obrigatorio": doc_req.obrigatorio,
                "status": "faltando",
                "arquivo": None,
                "tamanho_mb": None,
                "alerta_tamanho": False,
            }

            # Tentar encontrar documento correspondente
            doc_encontrado = docs_disponiveis.get(doc_req.tipo_chave)
            if doc_encontrado:
                item["status"] = "ok"
                item["arquivo"] = doc_encontrado["nome"]
                # Verificar tamanho do arquivo
                path = doc_encontrado["path"]
                if path and os.path.exists(path):
                    size_mb = os.path.getsize(path) / (1024 * 1024)
                    item["tamanho_mb"] = round(size_mb, 2)
                    if size_mb > MAX_SIZE_MB:
                        item["alerta_tamanho"] = True
                        item["status"] = "alerta"
                        total_alerta += 1
                    else:
                        total_ok += 1
                else:
                    total_ok += 1
            else:
                total_faltando += 1

            checklist.append(item)

        return {
            "success": True,
            "proposta_id": proposta_id,
            "produto": produto.nome if produto else None,
            "empresa": empresa.razao_social if empresa else None,
            "checklist": checklist,
            "resumo": {
                "total": len(checklist),
                "ok": total_ok,
                "faltando": total_faltando,
                "alerta_tamanho": total_alerta,
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


TOOLS_MAP["auditoria_documental"] = tool_auditoria_documental


def tool_smart_split_pdf(file_path: str, max_size_mb: float = 25) -> Dict[str, Any]:
    """
    Divide um PDF em partes menores que max_size_mb.
    Usa PyPDF2 para leitura e escrita de páginas.
    Retorna lista de caminhos dos arquivos gerados.
    """
    try:
        if not os.path.exists(file_path):
            return {"success": False, "error": f"Arquivo não encontrado: {file_path}"}

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb <= max_size_mb:
            return {
                "success": True,
                "message": f"Arquivo já está dentro do limite ({file_size_mb:.2f} MB <= {max_size_mb} MB)",
                "arquivos": [file_path],
                "dividido": False,
            }

        try:
            from PyPDF2 import PdfReader, PdfWriter
        except ImportError:
            return {"success": False, "error": "PyPDF2 não instalado. Execute: pip install PyPDF2"}

        reader = PdfReader(file_path)
        total_pages = len(reader.pages)

        if total_pages <= 1:
            return {
                "success": False,
                "error": f"PDF tem apenas 1 página ({file_size_mb:.2f} MB). Não é possível dividir."
            }

        # Estimar páginas por parte baseado no tamanho
        pages_per_part = max(1, int(total_pages * max_size_mb / file_size_mb))

        base_name = os.path.splitext(file_path)[0]
        ext = os.path.splitext(file_path)[1]
        arquivos_gerados = []
        part_num = 1
        page_idx = 0

        while page_idx < total_pages:
            writer = PdfWriter()
            end_idx = min(page_idx + pages_per_part, total_pages)
            for i in range(page_idx, end_idx):
                writer.add_page(reader.pages[i])

            part_path = f"{base_name}_parte{part_num}{ext}"
            with open(part_path, 'wb') as f:
                writer.write(f)

            part_size = os.path.getsize(part_path) / (1024 * 1024)
            arquivos_gerados.append({
                "path": part_path,
                "tamanho_mb": round(part_size, 2),
                "paginas": f"{page_idx + 1}-{end_idx}",
            })

            page_idx = end_idx
            part_num += 1

        return {
            "success": True,
            "dividido": True,
            "arquivo_original": file_path,
            "tamanho_original_mb": round(file_size_mb, 2),
            "total_partes": len(arquivos_gerados),
            "arquivos": arquivos_gerados,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


TOOLS_MAP["smart_split_pdf"] = tool_smart_split_pdf


# =============================================================================
# SPRINT 4 — RECURSOS E IMPUGNAÇÕES: Novas tools (UC-I01 a UC-RE05)
# =============================================================================

def tool_validacao_legal_edital(edital_id: str, user_id: str, empresa_id: str = None) -> Dict[str, Any]:
    """
    UC-I01: Validação legal do edital.
    Lê o texto do PDF do edital, envia ao DeepSeek para identificar inconsistências
    com a Lei 14.133/2021, decretos e normas aplicáveis.
    Retorna lista de inconsistências com {trecho, lei_violada, gravidade, sugestao_tipo}.
    Salva registro ValidacaoLegal.
    """
    from models import get_db, Edital, EditalDocumento, ValidacaoLegal
    db = get_db()
    try:
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()
        if not edital:
            return {"success": False, "error": "Edital não encontrado"}

        # Buscar texto do PDF do edital
        doc = db.query(EditalDocumento).filter(
            EditalDocumento.edital_id == edital_id,
            EditalDocumento.texto_extraido != None
        ).first()

        if not doc or not doc.texto_extraido or len(doc.texto_extraido) < 200:
            return {
                "success": False,
                "error": "Edital não possui PDF com texto extraído. Baixe o PDF primeiro.",
                "sem_pdf": True,
            }

        texto_edital = doc.texto_extraido[:15000]  # Limitar para caber no contexto

        prompt_validacao = f"""Você é um especialista em licitações públicas brasileiras.
Analise o texto do edital abaixo e identifique INCONSISTÊNCIAS LEGAIS comparando com:
- Lei 14.133/2021 (Nova Lei de Licitações)
- Lei 8.666/1993 (se aplicável por transição)
- Decretos regulamentadores (Decreto 11.462/2023, etc.)
- IN SEGES/ME nº 73/2022
- Jurisprudência do TCU

Para cada inconsistência encontrada, retorne um JSON com a estrutura:
[
  {{
    "trecho": "Trecho do edital com o problema (citação direta)",
    "lei_violada": "Lei/Artigo/Inciso violado",
    "gravidade": "alta|media|baixa",
    "sugestao_tipo": "impugnacao|esclarecimento",
    "fundamentacao": "Explicação jurídica detalhada do porquê é inconsistente",
    "sugestao_correcao": "Como deveria estar redigido"
  }}
]

Se não encontrar inconsistências, retorne um array vazio [].
Foque em: cláusulas restritivas de competição, prazos inadequados, exigências desproporcionais,
falta de fundamentação legal, critérios de julgamento irregulares, qualificação técnica excessiva.

TEXTO DO EDITAL:
{texto_edital}

Responda APENAS com o JSON, sem texto adicional."""

        resposta_ia = call_deepseek(
            [{"role": "user", "content": prompt_validacao}],
            max_tokens=4000,
            model_override="deepseek-chat"
        )

        # Parsear resposta
        inconsistencias = []
        analise_texto = resposta_ia
        try:
            # Tentar extrair JSON da resposta
            json_match = re.search(r'\[.*\]', resposta_ia, re.DOTALL)
            if json_match:
                inconsistencias = json.loads(json_match.group())
        except (json.JSONDecodeError, AttributeError):
            print(f"[VALIDACAO-LEGAL] Não conseguiu parsear JSON da IA: {resposta_ia[:200]}")

        # Salvar registro ValidacaoLegal
        validacao = ValidacaoLegal(
            edital_id=edital_id,
            user_id=user_id,
            inconsistencias_json=json.dumps(inconsistencias, ensure_ascii=False),
            analise_ia=analise_texto,
        )
        db.add(validacao)
        db.commit()

        return {
            "success": True,
            "edital_id": edital_id,
            "validacao_id": validacao.id,
            "total_inconsistencias": len(inconsistencias),
            "inconsistencias": inconsistencias,
            "edital_numero": edital.numero,
            "edital_orgao": edital.orgao,
        }
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


TOOLS_MAP["validacao_legal_edital"] = tool_validacao_legal_edital


def tool_gerar_peticao_impugnacao(edital_id: str, user_id: str, empresa_id: str = None, inconsistencias: list = None,
                                   template_id: str = None, tipo: str = 'impugnacao') -> Dict[str, Any]:
    """
    UC-I02/I03: Gera petição de impugnação ou pedido de esclarecimento.
    Utiliza inconsistências detectadas (ou fornecidas) para gerar texto jurídico.
    Cria registro Impugnacao.
    """
    from models import get_db, Edital, EditalDocumento, Impugnacao, RecursoTemplate, ValidacaoLegal, Empresa
    db = get_db()
    try:
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()
        if not edital:
            return {"success": False, "error": "Edital não encontrado"}

        # Se não foram fornecidas inconsistências, buscar da última validação legal
        if not inconsistencias:
            validacao = db.query(ValidacaoLegal).filter(
                ValidacaoLegal.edital_id == edital_id
            ).order_by(ValidacaoLegal.created_at.desc()).first()
            if validacao and validacao.inconsistencias_json:
                try:
                    inconsistencias = json.loads(validacao.inconsistencias_json)
                except json.JSONDecodeError:
                    inconsistencias = []

        if not inconsistencias:
            return {"success": False, "error": "Nenhuma inconsistência encontrada. Execute a validação legal primeiro."}

        # Buscar template se fornecido
        template_conteudo = None
        if template_id:
            template = db.query(RecursoTemplate).filter(
                RecursoTemplate.id == template_id,
                RecursoTemplate.ativo == True
            ).first()
            if template:
                template_conteudo = template.conteudo_md

        # Buscar dados da empresa
        empresa = None
        if edital.empresa_id:
            empresa = db.query(Empresa).filter(Empresa.id == edital.empresa_id).first()

        empresa_info = ""
        if empresa:
            empresa_info = f"""
DADOS DA IMPUGNANTE:
- Razão Social: {empresa.razao_social}
- CNPJ: {empresa.cnpj}
- Endereço: {empresa.endereco or 'N/I'}
- Cidade/UF: {empresa.cidade or 'N/I'}/{empresa.uf or 'N/I'}
"""

        inconsistencias_texto = json.dumps(inconsistencias, ensure_ascii=False, indent=2)

        tipo_label = "IMPUGNAÇÃO AO EDITAL" if tipo == 'impugnacao' else "PEDIDO DE ESCLARECIMENTO"

        prompt_peticao = f"""Você é um advogado especialista em licitações públicas.
Gere uma petição formal de {tipo_label} com base nas inconsistências identificadas.

DADOS DO EDITAL:
- Número: {edital.numero}
- Órgão: {edital.orgao}
- Objeto: {edital.objeto[:500] if edital.objeto else 'N/I'}
- Data de Abertura: {edital.data_abertura.strftime('%d/%m/%Y') if edital.data_abertura else 'N/I'}
{empresa_info}

INCONSISTÊNCIAS IDENTIFICADAS:
{inconsistencias_texto}

{f'USE ESTE TEMPLATE COMO BASE:{chr(10)}{template_conteudo}' if template_conteudo else ''}

A petição deve conter:
1. **ENDEREÇAMENTO** ao pregoeiro/comissão de licitação
2. **QUALIFICAÇÃO** da empresa impugnante
3. **DOS FATOS** — descrição do edital e contexto
4. **DAS INCONSISTÊNCIAS** — detalhamento de cada ponto com citação do trecho do edital
5. **DO DIREITO** — fundamentação legal (Lei 14.133/2021, jurisprudência TCU)
6. **DO PEDIDO** — solicitação específica (alteração do edital, suspensão, esclarecimento)
7. **FECHO** — local, data e assinatura

DIRETRIZES DE PROFUNDIDADE (obrigatorias):
- Escreva no minimo 2500 palavras com argumentacao densa e fundamentada.
- Cite artigos especificos da Lei 14.133/2021 (mencione numero do art./inciso/alinea).
- Cite acordaos do TCU (numero/ano) e da jurisprudencia do STJ quando relevante.
- Mencione principios da Administracao Publica: legalidade, isonomia, competitividade, vinculacao ao instrumento convocatorio.
- Cada inconsistencia detalhada deve ter: descricao, base legal violada, citacao do trecho do edital, impacto na competicao e pedido de correcao especifico.
- Use linguagem juridica formal e tecnica precisa. Sem placeholders. Sem "[Nome]" — use os dados ja fornecidos.
- Formate em Markdown com cabecalhos de secao."""

        texto_peticao = call_deepseek(
            [{"role": "user", "content": prompt_peticao}],
            max_tokens=12000,
            model_override="deepseek-chat"
        )

        # Calcular prazo limite (3 dias úteis antes da abertura)
        prazo_limite = None
        if edital.data_abertura:
            from datetime import timedelta
            prazo = edital.data_abertura
            dias_uteis = 0
            while dias_uteis < 3:
                prazo -= timedelta(days=1)
                if prazo.weekday() < 5:  # Seg-Sex
                    dias_uteis += 1
            prazo_limite = prazo

        # Criar registro Impugnacao
        impugnacao = Impugnacao(
            edital_id=edital_id,
            user_id=user_id,
            empresa_id=edital.empresa_id,
            tipo=tipo,
            status='rascunho',
            texto=texto_peticao,
            inconsistencias_json=json.dumps(inconsistencias, ensure_ascii=False),
            prazo_limite=prazo_limite,
            template_id=template_id,
        )
        db.add(impugnacao)
        db.commit()

        return {
            "success": True,
            "impugnacao_id": impugnacao.id,
            "tipo": tipo,
            "texto": texto_peticao,
            "prazo_limite": prazo_limite.isoformat() if prazo_limite else None,
            "total_inconsistencias": len(inconsistencias),
            "edital_numero": edital.numero,
        }
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


TOOLS_MAP["gerar_peticao_impugnacao"] = tool_gerar_peticao_impugnacao


def tool_analisar_proposta_vencedora(edital_id: str, user_id: str, empresa_id: str = None,
                                      proposta_vencedora_texto: str = None) -> Dict[str, Any]:
    """
    UC-RE02: Analisa proposta vencedora contra requisitos do edital e leis.
    Retorna lista de inconsistências + motivações sugeridas para recurso.
    """
    from models import get_db, Edital, EditalDocumento, EditalRequisito
    db = get_db()
    try:
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()
        if not edital:
            return {"success": False, "error": "Edital não encontrado"}

        # Buscar requisitos do edital
        requisitos = db.query(EditalRequisito).filter(
            EditalRequisito.edital_id == edital_id
        ).all()
        requisitos_texto = "\n".join([
            f"- [{r.tipo}] {r.descricao}" for r in requisitos
        ]) if requisitos else "Nenhum requisito extraído do edital."

        # Buscar texto do edital para contexto
        doc = db.query(EditalDocumento).filter(
            EditalDocumento.edital_id == edital_id,
            EditalDocumento.texto_extraido != None
        ).first()
        contexto_edital = ""
        if doc and doc.texto_extraido:
            contexto_edital = doc.texto_extraido[:8000]

        if not proposta_vencedora_texto:
            proposta_vencedora_texto = "(Texto da proposta vencedora não fornecido — analise baseada nos requisitos do edital)"

        prompt_analise = f"""Você é um especialista em licitações públicas brasileiras.
Analise a proposta vencedora comparando com os requisitos do edital e a legislação vigente.

DADOS DO EDITAL:
- Número: {edital.numero}
- Órgão: {edital.orgao}
- Objeto: {edital.objeto[:500] if edital.objeto else 'N/I'}

REQUISITOS DO EDITAL:
{requisitos_texto}

CONTEXTO DO EDITAL:
{contexto_edital[:5000]}

PROPOSTA VENCEDORA:
{proposta_vencedora_texto[:5000]}

Identifique:
1. Inconsistências da proposta vencedora com os requisitos do edital
2. Possíveis violações legais (Lei 14.133/2021)
3. Pontos que podem ser questionados via recurso

Retorne um JSON com a estrutura:
{{
  "inconsistencias": [
    {{
      "descricao": "Descrição da inconsistência",
      "requisito_violado": "Requisito do edital não atendido",
      "base_legal": "Lei/artigo aplicável",
      "gravidade": "alta|media|baixa",
      "tipo": "tecnico|documental|juridico"
    }}
  ],
  "motivacoes_recurso": [
    {{
      "titulo": "Título da motivação",
      "fundamentacao": "Fundamentação jurídica detalhada",
      "tipo": "administrativo|tecnico"
    }}
  ],
  "parecer_geral": "Resumo da análise e recomendação"
}}

Responda APENAS com o JSON."""

        resposta_ia = call_deepseek(
            [{"role": "user", "content": prompt_analise}],
            max_tokens=4000,
            model_override="deepseek-chat"
        )

        # Parsear resposta
        resultado = {"inconsistencias": [], "motivacoes_recurso": [], "parecer_geral": ""}
        try:
            json_match = re.search(r'\{.*\}', resposta_ia, re.DOTALL)
            if json_match:
                resultado = json.loads(json_match.group())
        except (json.JSONDecodeError, AttributeError):
            resultado["parecer_geral"] = resposta_ia

        return {
            "success": True,
            "edital_id": edital_id,
            "edital_numero": edital.numero,
            "inconsistencias": resultado.get("inconsistencias", []),
            "motivacoes_recurso": resultado.get("motivacoes_recurso", []),
            "parecer_geral": resultado.get("parecer_geral", ""),
            "total_inconsistencias": len(resultado.get("inconsistencias", [])),
            "total_motivacoes": len(resultado.get("motivacoes_recurso", [])),
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


TOOLS_MAP["analisar_proposta_vencedora"] = tool_analisar_proposta_vencedora


def tool_gerar_laudo_recurso(edital_id: str, user_id: str, empresa_id: str = None, tipo: str = 'recurso',
                              inconsistencias: list = None, template_id: str = None,
                              empresa_alvo: str = None) -> Dict[str, Any]:
    """
    UC-RE04/RE05: Gera laudo de recurso ou contra-razão.
    Laudo com seções: JURÍDICA + TÉCNICA (e DEFESA + ATAQUE para contra-razão).
    Cria registro RecursoDetalhado.
    """
    from models import get_db, Edital, EditalDocumento, RecursoDetalhado, RecursoTemplate, Empresa
    db = get_db()
    try:
        edital = db.query(Edital).filter(
            Edital.id == edital_id,
            Edital.empresa_id == empresa_id
        ).first()
        if not edital:
            return {"success": False, "error": "Edital não encontrado"}

        # Buscar template se fornecido
        template_conteudo = None
        if template_id:
            template = db.query(RecursoTemplate).filter(
                RecursoTemplate.id == template_id,
                RecursoTemplate.ativo == True
            ).first()
            if template:
                template_conteudo = template.conteudo_md

        # Buscar dados da empresa
        empresa = None
        if edital.empresa_id:
            empresa = db.query(Empresa).filter(Empresa.id == edital.empresa_id).first()

        empresa_info = ""
        if empresa:
            empresa_info = f"""
DADOS DA RECORRENTE:
- Razão Social: {empresa.razao_social}
- CNPJ: {empresa.cnpj}
"""

        # Buscar texto do edital
        doc = db.query(EditalDocumento).filter(
            EditalDocumento.edital_id == edital_id,
            EditalDocumento.texto_extraido != None
        ).first()
        contexto_edital = ""
        if doc and doc.texto_extraido:
            contexto_edital = doc.texto_extraido[:8000]

        inconsistencias_texto = ""
        if inconsistencias:
            inconsistencias_texto = json.dumps(inconsistencias, ensure_ascii=False, indent=2)

        tipo_label = "RECURSO ADMINISTRATIVO" if tipo == 'recurso' else "CONTRA-RAZÕES AO RECURSO"

        secoes_contra_razao = ""
        if tipo == 'contra_razao':
            secoes_contra_razao = f"""
5. **SEÇÃO DE DEFESA** — Argumentos defendendo a decisão original
6. **SEÇÃO DE ATAQUE** — Contra-argumentos às razões do recorrente ({empresa_alvo or 'empresa recorrente'})
"""

        prompt_laudo = f"""Você é um advogado e perito técnico especialista em licitações públicas.
Gere um laudo completo de {tipo_label} com seções JURÍDICA e TÉCNICA.

DADOS DO EDITAL:
- Número: {edital.numero}
- Órgão: {edital.orgao}
- Objeto: {edital.objeto[:500] if edital.objeto else 'N/I'}
{empresa_info}

{f'EMPRESA ALVO (recorrente):{chr(10)}{empresa_alvo}' if empresa_alvo else ''}

CONTEXTO DO EDITAL:
{contexto_edital[:5000]}

{f'INCONSISTÊNCIAS IDENTIFICADAS:{chr(10)}{inconsistencias_texto}' if inconsistencias_texto else ''}

{f'USE ESTE TEMPLATE COMO BASE:{chr(10)}{template_conteudo}' if template_conteudo else ''}

O laudo DEVE conter as seguintes seções:

1. **ENDEREÇAMENTO** — ao pregoeiro/comissão de licitação
2. **QUALIFICAÇÃO** — identificação da empresa recorrente
3. **SEÇÃO JURÍDICA** — fundamentação legal completa:
   - Artigos da Lei 14.133/2021
   - Decretos regulamentadores
   - Jurisprudência do TCU (Acórdãos relevantes)
   - Jurisprudência do STJ se aplicável
4. **SEÇÃO TÉCNICA** — análise técnica detalhada:
   - Comparação técnica com requisitos do edital
   - Laudo técnico sobre atendimento/não atendimento
   - Evidências técnicas
{secoes_contra_razao}
5. **DO PEDIDO** — requerimento específico
6. **FECHO** — local, data e assinatura

DIRETRIZES DE PROFUNDIDADE (obrigatorias):
- Escreva no minimo 3500 palavras, com argumentacao densa nas secoes JURIDICA e TECNICA.
- Cite artigos especificos da Lei 14.133/2021 (numero do art./inciso) e Lei 8.666/1993 quando aplicavel.
- Cite acordaos do TCU (numero/ano), Sumulas (TCU, STJ, STF) e decisoes da Justica Federal.
- Mencione expressamente principios: legalidade, isonomia, competitividade, eficiencia, vinculacao ao instrumento convocatorio, motivacao, publicidade, julgamento objetivo.
- Inclua precedentes administrativos especificos e doutrina (Marcal Justen Filho, Joel de Menezes Niebuhr, Carlos Pinto Coelho Motta).
- A SECAO TECNICA deve incluir comparativo objetivo dos requisitos do edital com a especificacao do produto/servico, com normas tecnicas (ABNT NBR, ANVISA RDC) quando cabivel.
- Sem placeholders. Sem "[inserir]". Use dados reais ja fornecidos.
- Use linguagem juridica formal e tecnica precisa. Formate em Markdown.
Separe claramente a seção JURÍDICA da seção TÉCNICA com delimitadores."""

        resposta_ia = call_deepseek(
            [{"role": "user", "content": prompt_laudo}],
            max_tokens=14000,
            model_override="deepseek-chat"
        )

        # Separar seções jurídica e técnica
        texto_juridico = resposta_ia
        texto_tecnico = ""

        # Tentar separar seções
        secao_tecnica_markers = ["## SEÇÃO TÉCNICA", "## 4.", "**SEÇÃO TÉCNICA**", "# SEÇÃO TÉCNICA"]
        for marker in secao_tecnica_markers:
            idx = resposta_ia.upper().find(marker.upper())
            if idx > 0:
                texto_juridico = resposta_ia[:idx].strip()
                texto_tecnico = resposta_ia[idx:].strip()
                break

        # Criar registro RecursoDetalhado
        recurso = RecursoDetalhado(
            edital_id=edital_id,
            user_id=user_id,
            empresa_id=edital.empresa_id,
            tipo=tipo,
            subtipo='administrativo',
            status='rascunho',
            texto_juridico=texto_juridico,
            texto_tecnico=texto_tecnico,
            inconsistencias_json=json.dumps(inconsistencias or [], ensure_ascii=False),
            empresa_alvo=empresa_alvo,
            template_id=template_id,
        )
        db.add(recurso)
        db.commit()

        return {
            "success": True,
            "recurso_id": recurso.id,
            "tipo": tipo,
            "texto_juridico": texto_juridico,
            "texto_tecnico": texto_tecnico,
            "texto_completo": resposta_ia,
            "edital_numero": edital.numero,
        }
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


TOOLS_MAP["gerar_laudo_recurso"] = tool_gerar_laudo_recurso


# ==================== SPRINT 5 — PÓS-LICITAÇÃO ====================


def tool_calcular_score_logistico(edital_id, user_id, empresa_id=None, db=None):
    """Calcula score logístico de viabilidade para um edital (RF-011)"""
    close_db = False
    if db is None:
        db = get_db()
        close_db = True
    try:
        edital = db.query(Edital).filter_by(id=edital_id, empresa_id=empresa_id).first()
        if not edital:
            return {"erro": "Edital não encontrado"}

        empresa = db.query(Empresa).filter_by(id=empresa_id).first() if empresa_id else None
        origem_uf = empresa.uf if empresa and hasattr(empresa, 'uf') and empresa.uf else 'SP'
        destino_uf = edital.uf if hasattr(edital, 'uf') and edital.uf else ''

        regioes = {
            'Norte': ['AC', 'AM', 'AP', 'PA', 'RO', 'RR', 'TO'],
            'Nordeste': ['AL', 'BA', 'CE', 'MA', 'PB', 'PE', 'PI', 'RN', 'SE'],
            'Centro-Oeste': ['DF', 'GO', 'MS', 'MT'],
            'Sudeste': ['ES', 'MG', 'RJ', 'SP'],
            'Sul': ['PR', 'RS', 'SC']
        }

        def get_regiao(uf):
            for r, ufs in regioes.items():
                if uf in ufs:
                    return r
            return None

        # Dimensão 1: Distância (30%)
        if origem_uf == destino_uf:
            distance_score = 100
        elif get_regiao(origem_uf) == get_regiao(destino_uf):
            distance_score = 65
        else:
            distance_score = 35

        # Dimensão 2: Histórico de entregas (25%)
        entregas_count = db.query(ContratoEntrega).join(Contrato).filter(
            Contrato.empresa_id == empresa_id,
            ContratoEntrega.status == 'entregue'
        ).count()
        if entregas_count > 10:
            history_score = 100
        elif entregas_count > 3:
            history_score = 75
        elif entregas_count > 0:
            history_score = 50
        else:
            history_score = 20

        # Dimensão 3: Custo de frete estimado (25%)
        if origem_uf == destino_uf:
            freight_score = 90
        elif get_regiao(origem_uf) == get_regiao(destino_uf):
            freight_score = 60
        else:
            freight_score = 30

        # Dimensão 4: Prazo disponível (20%)
        if hasattr(edital, 'data_abertura') and edital.data_abertura:
            dias = (edital.data_abertura - datetime.now()).days
            if dias > 60:
                timeline_score = 100
            elif dias > 30:
                timeline_score = 80
            elif dias > 15:
                timeline_score = 60
            else:
                timeline_score = 40
        else:
            timeline_score = 60

        score = round(distance_score * 0.30 + history_score * 0.25 + freight_score * 0.25 + timeline_score * 0.20)

        if score >= 70:
            recomendacao = "VIAVEL"
        elif score >= 40:
            recomendacao = "PARCIAL"
        else:
            recomendacao = "INVIAVEL"

        return {
            "score": score,
            "recomendacao": recomendacao,
            "dimensoes": [
                {"nome": "Distância", "peso": 30, "score": distance_score, "contribuicao": round(distance_score * 0.30)},
                {"nome": "Histórico Entregas", "peso": 25, "score": history_score, "contribuicao": round(history_score * 0.25)},
                {"nome": "Custo Frete", "peso": 25, "score": freight_score, "contribuicao": round(freight_score * 0.25)},
                {"nome": "Prazo Disponível", "peso": 20, "score": timeline_score, "contribuicao": round(timeline_score * 0.20)}
            ],
            "detalhes": {
                "origem_uf": origem_uf,
                "destino_uf": destino_uf,
                "entregas_anteriores": entregas_count
            }
        }
    except Exception as e:
        return {"erro": str(e)}
    finally:
        if close_db and db:
            db.close()


TOOLS_MAP["calcular_score_logistico"] = tool_calcular_score_logistico


def tool_registrar_resultado_api(data, user_id, empresa_id=None, db=None):
    """Registra resultado de licitação via API direta — vitória/derrota/cancelado (RF-017)"""
    close_db = False
    if db is None:
        db = get_db()
        close_db = True
    try:
        edital_id = data.get('edital_id')
        tipo = data.get('tipo', '').lower()  # vitoria, derrota, cancelado
        valor_final = data.get('valor_final')
        vencedor = data.get('vencedor', '')
        motivo_derrota = data.get('motivo_derrota', '')
        observacoes = data.get('observacoes', '')

        edital = db.query(Edital).filter_by(id=edital_id, empresa_id=empresa_id).first()
        if not edital:
            return {"success": False, "error": "Edital não encontrado"}

        contrato_id = None

        if tipo == 'vitoria':
            edital.status = 'ganho'
            # Auto-gerar número do contrato
            ano = datetime.now().year
            count = db.query(Contrato).filter_by(empresa_id=empresa_id).count() + 1
            numero_contrato = f"CT-{ano}/{count:03d}"

            contrato = Contrato(
                user_id=user_id,
                edital_id=edital.id,
                numero_contrato=numero_contrato,
                orgao=edital.orgao if hasattr(edital, 'orgao') else '',
                objeto=edital.objeto if hasattr(edital, 'objeto') else '',
                valor_total=float(valor_final) if valor_final else 0,
                status='vigente',
                data_assinatura=datetime.now(),
                data_inicio=datetime.now(),
            )
            if hasattr(edital, 'proposta_id'):
                contrato.proposta_id = edital.proposta_id
            db.add(contrato)
            db.flush()
            contrato_id = contrato.id

            # Salvar no histórico de preços
            if valor_final:
                preco = PrecoHistorico(
                    user_id=user_id,
                    edital_id=edital.id,
                    valor=float(valor_final),
                    fonte='manual',
                    descricao=f"Resultado licitação - Vitória {edital.numero if hasattr(edital, 'numero') else ''}",
                )
                db.add(preco)

        elif tipo == 'derrota':
            edital.status = 'perdido'
            if vencedor:
                concorrente = Concorrente(
                    user_id=user_id,
                    edital_id=edital.id,
                    nome=vencedor,
                    valor_proposta=float(valor_final) if valor_final else None,
                    resultado='vencedor',
                    observacoes=f"Motivo derrota: {motivo_derrota}",
                )
                db.add(concorrente)
            if valor_final:
                preco = PrecoHistorico(
                    user_id=user_id,
                    edital_id=edital.id,
                    valor=float(valor_final),
                    fonte='manual',
                    descricao=f"Resultado licitação - Derrota {edital.numero if hasattr(edital, 'numero') else ''} - Vencedor: {vencedor}",
                )
                db.add(preco)

        elif tipo == 'cancelado':
            edital.status = 'cancelado'

        if observacoes:
            edital.observacoes = (edital.observacoes or '') + f"\n[Resultado] {observacoes}"

        db.commit()
        return {
            "success": True,
            "tipo": tipo,
            "edital_id": edital_id,
            "contrato_id": contrato_id,
            "message": f"Resultado '{tipo}' registrado com sucesso"
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        if close_db and db:
            db.close()


TOOLS_MAP["registrar_resultado_api"] = tool_registrar_resultado_api


def tool_dashboard_contratado_realizado(user_id, empresa_id=None, db=None, periodo='6m', produto_id=None, orgao=None):
    """Agrega dados de contratado vs realizado para dashboard (RF-051)"""
    from datetime import date as _date
    hoje = _date.today()
    hoje_dt = datetime.combine(hoje, datetime.min.time())
    close_db = False
    if db is None:
        db = get_db()
        close_db = True
    try:
        query = db.query(Contrato).filter_by(empresa_id=empresa_id)

        # Filtro período
        if periodo and periodo != 'tudo':
            meses = {'1m': 1, '3m': 3, '6m': 6, '12m': 12}
            m = meses.get(periodo, 6)
            data_inicio = datetime.now() - timedelta(days=m * 30)
            query = query.filter(Contrato.created_at >= data_inicio)

        if orgao:
            query = query.filter(Contrato.orgao.ilike(f'%{orgao}%'))

        contratos = query.all()

        contratos_data = []
        total_contratado = 0
        total_realizado = 0
        atrasos = []

        for c in contratos:
            valor_contratado = float(c.valor_total) if c.valor_total else 0
            total_contratado += valor_contratado

            entregas = db.query(ContratoEntrega).filter_by(contrato_id=c.id).all()
            valor_realizado = sum(
                float(e.valor_total) if e.valor_total else 0
                for e in entregas if e.status == 'entregue'
            )
            total_realizado += valor_realizado

            variacao = round(((valor_realizado - valor_contratado) / valor_contratado) * 100, 2) if valor_contratado > 0 else 0

            contratos_data.append({
                "contrato_id": c.id,
                "numero": c.numero_contrato,
                "orgao": c.orgao,
                "objeto": c.objeto[:80] if c.objeto else '',
                "valor_contratado": valor_contratado,
                "valor_realizado": valor_realizado,
                "variacao_pct": variacao,
                "status": c.status,
                "data_fim": c.data_fim.isoformat() if c.data_fim else None,
            })

            # Identificar atrasos
            for e in entregas:
                if e.data_prevista and e.status != 'entregue' and e.data_prevista < hoje:
                    dias_atraso = (hoje - e.data_prevista).days
                    if dias_atraso > 30:
                        severidade = 'HIGH'
                    elif dias_atraso > 15:
                        severidade = 'MEDIUM'
                    else:
                        severidade = 'LOW'
                    atrasos.append({
                        "contrato_id": c.id,
                        "contrato_numero": c.numero_contrato,
                        "orgao": c.orgao,
                        "entrega": e.descricao,
                        "data_prevista": e.data_prevista.isoformat(),
                        "dias_atraso": dias_atraso,
                        "severidade": severidade,
                        "valor": float(e.valor_total) if e.valor_total else 0,
                    })

        # Próximos vencimentos (contratos com data_fim nos próximos 90 dias)
        data_limite_dt = hoje_dt + timedelta(days=90)
        vencimentos = db.query(Contrato).filter(
            Contrato.empresa_id == empresa_id,
            Contrato.data_fim != None,
            Contrato.data_fim <= data_limite_dt,
            Contrato.data_fim >= hoje_dt,
            Contrato.status == 'vigente'
        ).all()

        proximos_vencimentos = [{
            "contrato_id": v.id,
            "numero": v.numero_contrato,
            "orgao": v.orgao,
            "data_fim": v.data_fim.isoformat(),
            "dias_restantes": ((v.data_fim.date() if hasattr(v.data_fim, 'date') else v.data_fim) - hoje).days,
            "valor": float(v.valor_total) if v.valor_total else 0,
        } for v in vencimentos]

        variacao_global = round(((total_realizado - total_contratado) / total_contratado) * 100, 2) if total_contratado > 0 else 0
        avg_var = sum(abs(c['variacao_pct']) for c in contratos_data) / len(contratos_data) if contratos_data else 0

        if avg_var < 5:
            saude = 'saudavel'
        elif avg_var < 10:
            saude = 'atencao'
        else:
            saude = 'critico'

        return {
            "totais": {
                "contratado": total_contratado,
                "realizado": total_realizado,
                "variacao_pct": variacao_global,
                "contratos_ativos": len([c for c in contratos if c.status == 'vigente']),
            },
            "contratos": contratos_data,
            "atrasos": sorted(atrasos, key=lambda x: x['dias_atraso'], reverse=True),
            "proximos_vencimentos": sorted(proximos_vencimentos, key=lambda x: x['dias_restantes']),
            "saude_portfolio": saude,
        }
    except Exception as e:
        return {"erro": str(e)}
    finally:
        if close_db and db:
            db.close()


TOOLS_MAP["dashboard_contratado_realizado"] = tool_dashboard_contratado_realizado


def tool_alertas_vencimento_multi_tier(user_id, empresa_id=None, db=None):
    """Consolida vencimentos de contratos, atas e entregas com urgência multi-tier (RF-052-EXT-01)"""
    close_db = False
    if db is None:
        db = get_db()
        close_db = True
    try:
        from datetime import date as _date
        vencimentos = []
        hoje = _date.today()
        agora = datetime.combine(hoje, datetime.min.time())
        limite_90d_dt = agora + timedelta(days=90)
        limite_30d = hoje + timedelta(days=30)
        limite_90d = hoje + timedelta(days=90)

        # Contratos com vencimento próximo (Contrato.data_fim = DateTime)
        contratos = db.query(Contrato).filter(
            Contrato.empresa_id == empresa_id,
            Contrato.data_fim != None,
            Contrato.data_fim <= limite_90d_dt,
            Contrato.data_fim >= agora,
            Contrato.status == 'vigente'
        ).all()
        for c in contratos:
            data_fim_d = c.data_fim.date() if hasattr(c.data_fim, 'date') else c.data_fim
            dias = (data_fim_d - hoje).days
            vencimentos.append({
                "tipo_entidade": "contrato",
                "nome": f"{c.numero_contrato} — {c.orgao}",
                "data_vencimento": c.data_fim.isoformat(),
                "dias_restantes": dias,
                "valor": float(c.valor_total) if c.valor_total else 0,
                "entity_id": c.id,
            })

        # Atas com vigência próxima do fim (AtaConsultada.data_vigencia_fim = Date)
        # AtaConsultada não tem empresa_id direto — filtra via UsuarioEmpresa
        from models import UsuarioEmpresa as _UE
        user_ids_empresa = [ue.user_id for ue in db.query(_UE).filter(_UE.empresa_id == empresa_id).all()]
        atas = db.query(AtaConsultada).filter(
            AtaConsultada.user_id.in_(user_ids_empresa) if user_ids_empresa else False,
            AtaConsultada.data_vigencia_fim != None,
            AtaConsultada.data_vigencia_fim <= limite_90d,
            AtaConsultada.data_vigencia_fim >= hoje,
        ).all() if user_ids_empresa else []
        for a in atas:
            dias = (a.data_vigencia_fim - hoje).days
            vencimentos.append({
                "tipo_entidade": "arp",
                "nome": f"{a.titulo} — {a.orgao}",
                "data_vencimento": a.data_vigencia_fim.isoformat(),
                "dias_restantes": dias,
                "valor": None,
                "entity_id": a.id,
            })

        # Entregas pendentes (ContratoEntrega.data_prevista = Date)
        entregas = db.query(ContratoEntrega).join(Contrato).filter(
            Contrato.empresa_id == empresa_id,
            ContratoEntrega.status == 'pendente',
            ContratoEntrega.data_prevista != None,
            ContratoEntrega.data_prevista <= limite_30d,
            ContratoEntrega.data_prevista >= hoje,
        ).all()
        for e in entregas:
            dias = (e.data_prevista - hoje).days
            vencimentos.append({
                "tipo_entidade": "entrega",
                "nome": f"{e.descricao}",
                "data_vencimento": e.data_prevista.isoformat(),
                "dias_restantes": dias,
                "valor": float(e.valor_total) if e.valor_total else 0,
                "entity_id": e.id,
            })

        # Atribuir urgência
        for v in vencimentos:
            dias = v['dias_restantes']
            if dias <= 7:
                v['urgencia'] = 'vermelho'
            elif dias <= 15:
                v['urgencia'] = 'laranja'
            elif dias <= 30:
                v['urgencia'] = 'amarelo'
            else:
                v['urgencia'] = 'verde'

        vencimentos.sort(key=lambda x: x['dias_restantes'])

        resumo = {
            "total": len(vencimentos),
            "vermelho": len([v for v in vencimentos if v['urgencia'] == 'vermelho']),
            "laranja": len([v for v in vencimentos if v['urgencia'] == 'laranja']),
            "amarelo": len([v for v in vencimentos if v['urgencia'] == 'amarelo']),
            "verde": len([v for v in vencimentos if v['urgencia'] == 'verde']),
        }

        return {
            "vencimentos": vencimentos,
            "resumo": resumo,
        }
    except Exception as e:
        return {"erro": str(e)}
    finally:
        if close_db and db:
            db.close()


TOOLS_MAP["alertas_vencimento_multi_tier"] = tool_alertas_vencimento_multi_tier


# =============================================================================
# SPRINT 6 — Tools novas
# =============================================================================

def tool_analisar_documentos_empresa(user_id: str, empresa_id: str = None) -> Dict[str, Any]:
    """UC-MO03: Analisa documentos e certidões da empresa, retorna pendências."""
    from models import get_db, Empresa, EmpresaDocumento, EmpresaCertidao, EmpresaResponsavel
    from rn_audit import audited_tool
    db = get_db()
    try:
        empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
        if not empresa:
            return {"success": False, "error": "Empresa não encontrada"}

        docs = db.query(EmpresaDocumento).filter(EmpresaDocumento.empresa_id == empresa_id).all()
        certs = db.query(EmpresaCertidao).filter(EmpresaCertidao.empresa_id == empresa_id).all()
        resps = db.query(EmpresaResponsavel).filter(EmpresaResponsavel.empresa_id == empresa_id).all()

        pendencias = []
        categorias_existentes = {d.categoria for d in docs if d.categoria}
        categorias_esperadas = {"contrato_social", "procuracao", "balanco", "certidao_negativa", "alvara"}
        for cat in categorias_esperadas - categorias_existentes:
            pendencias.append({"tipo": "documento_ausente", "descricao": f"Documento '{cat}' não cadastrado"})

        from datetime import datetime, timedelta
        hoje = datetime.now().date()
        for cert in certs:
            if cert.data_vencimento:
                venc = cert.data_vencimento if isinstance(cert.data_vencimento, type(hoje)) else cert.data_vencimento.date() if hasattr(cert.data_vencimento, 'date') else cert.data_vencimento
                if venc < hoje:
                    pendencias.append({"tipo": "certidao_vencida", "descricao": f"Certidão '{cert.tipo}' vencida em {venc}"})
                elif venc <= hoje + timedelta(days=15):
                    pendencias.append({"tipo": "certidao_vencendo", "descricao": f"Certidão '{cert.tipo}' vence em {venc} (≤15 dias)"})

        for resp in resps:
            if not resp.cpf:
                pendencias.append({"tipo": "responsavel_sem_cpf", "descricao": f"Responsável '{resp.nome}' sem CPF cadastrado"})

        return {
            "success": True,
            "empresa": empresa.razao_social,
            "total_documentos": len(docs),
            "total_certidoes": len(certs),
            "total_responsaveis": len(resps),
            "pendencias": pendencias,
            "total_pendencias": len(pendencias),
            "status": "ok" if not pendencias else "pendencias_encontradas",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_verificar_pendencias_pncp(user_id: str, empresa_id: str = None, cnpj: str = None) -> Dict[str, Any]:
    """UC-MO04: Consulta API PNCP para verificar pendências do fornecedor."""
    from models import get_db, Empresa
    import requests
    db = get_db()
    try:
        empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
        if not empresa:
            return {"success": False, "error": "Empresa não encontrada"}
        cnpj_limpo = (cnpj or empresa.cnpj or "").replace(".", "").replace("-", "").replace("/", "")
        if not cnpj_limpo or len(cnpj_limpo) < 14:
            return {"success": False, "error": "CNPJ inválido ou não informado"}

        pendencias = []
        pncp_ok = False
        try:
            url = f"https://pncp.gov.br/api/consulta/v1/fornecedores/{cnpj_limpo}"
            resp = requests.get(url, timeout=15, headers={"Accept": "application/json"})
            if resp.status_code == 200:
                data = resp.json()
                pncp_ok = True
                pncp_nome = data.get("nomeRazaoSocial", "")
                if pncp_nome and pncp_nome.upper() != empresa.razao_social.upper():
                    pendencias.append({
                        "tipo": "razao_social_divergente",
                        "descricao": f"PNCP: '{pncp_nome}' / Local: '{empresa.razao_social}'",
                    })
                if data.get("situacaoCadastral") and data["situacaoCadastral"] != "ATIVA":
                    pendencias.append({
                        "tipo": "situacao_cadastral",
                        "descricao": f"Situação no PNCP: {data['situacaoCadastral']}",
                    })
            elif resp.status_code == 404:
                pendencias.append({"tipo": "nao_cadastrado_pncp", "descricao": "Fornecedor não encontrado no PNCP"})
            else:
                pendencias.append({"tipo": "erro_consulta", "descricao": f"PNCP retornou status {resp.status_code}"})
        except requests.RequestException as e:
            pendencias.append({"tipo": "erro_rede", "descricao": f"Falha ao consultar PNCP: {e}"})

        return {
            "success": True,
            "cnpj": cnpj_limpo,
            "empresa": empresa.razao_social,
            "pncp_acessivel": pncp_ok,
            "pendencias": pendencias,
            "total_pendencias": len(pendencias),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_consultar_auditoria(user_id: str, empresa_id: str = None,
                             termo_natural: str = None, entidade: str = None,
                             periodo_dias: int = 7) -> Dict[str, Any]:
    """UC-AU01: Consulta auditoria por termos naturais ou filtros."""
    from models import get_db, AuditoriaLog
    from datetime import timedelta
    db = get_db()
    try:
        desde = datetime.now() - timedelta(days=periodo_dias)
        query = db.query(AuditoriaLog).filter(AuditoriaLog.created_at >= desde)

        if entidade:
            query = query.filter(AuditoriaLog.entidade == entidade)
        if termo_natural:
            termo = f"%{termo_natural}%"
            query = query.filter(
                (AuditoriaLog.entidade.like(termo)) |
                (AuditoriaLog.acao.like(termo)) |
                (AuditoriaLog.user_email.like(termo))
            )

        registros = query.order_by(AuditoriaLog.created_at.desc()).limit(100).all()

        items = []
        for r in registros:
            items.append({
                "id": r.id,
                "data": r.created_at.strftime("%d/%m/%Y %H:%M") if r.created_at else "—",
                "usuario": r.user_email or "—",
                "acao": r.acao,
                "entidade": r.entidade,
                "entidade_id": r.entidade_id,
                "ip": r.ip_address,
            })

        return {
            "success": True,
            "total": len(items),
            "periodo_dias": periodo_dias,
            "filtro_entidade": entidade,
            "filtro_termo": termo_natural,
            "registros": items,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_exportar_auditoria_compliance(user_id: str, empresa_id: str = None,
                                       inicio: str = None, fim: str = None,
                                       mascarar_pii: bool = True) -> Dict[str, Any]:
    """UC-AU03: Exporta auditoria para compliance com mascaramento PII."""
    from models import get_db, AuditoriaLog
    import csv
    import io
    db = get_db()
    try:
        query = db.query(AuditoriaLog)
        if inicio:
            query = query.filter(AuditoriaLog.created_at >= datetime.strptime(inicio, "%Y-%m-%d"))
        if fim:
            query = query.filter(AuditoriaLog.created_at <= datetime.strptime(fim + " 23:59:59", "%Y-%m-%d %H:%M:%S"))

        registros = query.order_by(AuditoriaLog.created_at).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Data", "Usuário", "Ação", "Entidade", "ID Entidade", "IP"])

        for r in registros:
            email = r.user_email or "—"
            ip = r.ip_address or "—"
            if mascarar_pii:
                if "@" in email:
                    parts = email.split("@")
                    email = f"***@{parts[1][:3]}***"
                if ip != "—" and "." in ip:
                    octets = ip.split(".")
                    ip = f"{octets[0]}.{octets[1]}.*.*"

            writer.writerow([
                r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "—",
                email,
                r.acao,
                r.entidade,
                r.entidade_id or "—",
                ip,
            ])

        csv_content = output.getvalue()
        return {
            "success": True,
            "total_registros": len(registros),
            "csv_content": csv_content,
            "mascaramento_pii": mascarar_pii,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_testar_smtp(user_id: str, empresa_id: str = None,
                     destinatario_teste: str = None) -> Dict[str, Any]:
    """UC-SM01: Testa configuração SMTP enviando email de teste."""
    if not destinatario_teste:
        return {"success": False, "error": "destinatario_teste obrigatório"}
    from smtp_service import SMTPService
    svc = SMTPService()
    ok, msg = svc.test_config(destinatario_teste, empresa_id=empresa_id)
    return {"success": ok, "message": msg}


# Sprint 6 — registrar tools existentes (Flags/Monitoria) + novas no TOOLS_MAP
TOOLS_MAP["configurar_alertas"] = tool_configurar_alertas
TOOLS_MAP["listar_alertas"] = tool_listar_alertas
TOOLS_MAP["cancelar_alerta"] = tool_cancelar_alerta
TOOLS_MAP["configurar_monitoramento"] = tool_configurar_monitoramento
TOOLS_MAP["listar_monitoramentos"] = tool_listar_monitoramentos
TOOLS_MAP["desativar_monitoramento"] = tool_desativar_monitoramento
TOOLS_MAP["analisar_documentos_empresa"] = tool_analisar_documentos_empresa
TOOLS_MAP["verificar_pendencias_pncp"] = tool_verificar_pendencias_pncp
TOOLS_MAP["consultar_auditoria"] = tool_consultar_auditoria
TOOLS_MAP["exportar_auditoria_compliance"] = tool_exportar_auditoria_compliance
TOOLS_MAP["testar_smtp"] = tool_testar_smtp


# ==================== SPRINT 7 — INTELIGENCIA DE MERCADO E APRENDIZADO ====================

def tool_calcular_tam_sam_som(user_id: str = None, empresa_id: str = None,
                               segmento: str = None, periodo_meses: int = 12) -> Dict[str, Any]:
    """
    Calcula dimensionamento TAM/SAM/SOM do mercado de licitacoes.
    TAM = total mercado (todos editais). SAM = filtrado UFs+NCMs da empresa.
    SOM = SAM * taxa_vitoria * fator_capacidade.

    Args:
        user_id: ID do usuario
        empresa_id: ID da empresa
        segmento: Filtro por segmento (Hematologia, Bioquimica, etc.)
        periodo_meses: Periodo em meses para analise

    Returns:
        Dict com funil TAM/SAM/SOM, tendencias e recomendacoes
    """
    from database import SessionLocal
    from models import Edital, Empresa, Produto, Contrato
    from sqlalchemy import func
    from decimal import Decimal

    db = SessionLocal()
    try:
        data_inicio = datetime.now() - timedelta(days=periodo_meses * 30)

        # TAM — todos os editais no periodo
        q_tam = db.query(
            func.count(Edital.id).label('total'),
            func.coalesce(func.sum(Edital.valor_referencia), 0).label('valor')
        ).filter(Edital.created_at >= data_inicio)
        tam = q_tam.first()
        tam_total = tam.total or 0
        tam_valor = float(tam.valor or 0)

        # SAM — editais na regiao e segmento da empresa
        empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first() if empresa_id else None
        ufs_empresa = []
        ncms_empresa = []

        if empresa:
            # UFs dos editais que a empresa ja participou
            ufs_result = db.query(Edital.uf).filter(
                Edital.empresa_id == empresa_id,
                Edital.uf.isnot(None)
            ).distinct().all()
            ufs_empresa = [r[0] for r in ufs_result if r[0]]

            # NCMs do portfolio
            prods = db.query(Produto.ncm).filter(
                Produto.empresa_id == empresa_id,
                Produto.ncm.isnot(None)
            ).distinct().all()
            ncms_empresa = [r[0] for r in prods if r[0]]

        q_sam = db.query(
            func.count(Edital.id).label('total'),
            func.coalesce(func.sum(Edital.valor_referencia), 0).label('valor')
        ).filter(Edital.created_at >= data_inicio)

        if ufs_empresa:
            q_sam = q_sam.filter(Edital.uf.in_(ufs_empresa))
        if segmento:
            q_sam = q_sam.filter(Edital.objeto.ilike(f"%{segmento}%"))

        sam = q_sam.first()
        sam_total = sam.total or 0
        sam_valor = float(sam.valor or 0)

        # SOM — participados e ganhos
        q_part = db.query(func.count(Edital.id)).filter(
            Edital.empresa_id == empresa_id,
            Edital.created_at >= data_inicio,
            Edital.pipeline_stage.in_(['proposta_submetida', 'espera_resultado',
                                        'ganho_provisorio', 'resultado_definitivo'])
        )
        participados = q_part.scalar() or 0

        q_ganhos = db.query(func.count(Edital.id)).filter(
            Edital.empresa_id == empresa_id,
            Edital.created_at >= data_inicio,
            Edital.pipeline_stage == 'resultado_definitivo'
        )
        ganhos = q_ganhos.scalar() or 0

        taxa_vitoria = (ganhos / participados * 100) if participados > 0 else 0
        fator_capacidade = min(1.0, participados / max(sam_total, 1) * 3)
        som_valor = sam_valor * (taxa_vitoria / 100) * fator_capacidade
        som_total = int(sam_total * (taxa_vitoria / 100) * fator_capacidade)

        # Tendencias por mes
        from sqlalchemy import extract
        tendencias = []
        for i in range(min(periodo_meses, 12)):
            mes_dt = datetime.now() - timedelta(days=i * 30)
            mes_inicio = mes_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if mes_inicio.month == 12:
                mes_fim = mes_inicio.replace(year=mes_inicio.year + 1, month=1)
            else:
                mes_fim = mes_inicio.replace(month=mes_inicio.month + 1)

            cnt = db.query(func.count(Edital.id)).filter(
                Edital.created_at >= mes_inicio,
                Edital.created_at < mes_fim
            ).scalar() or 0

            tendencias.append({
                "mes": mes_inicio.strftime("%Y-%m"),
                "editais": cnt
            })

        tendencias.reverse()

        # Prompt DeepSeek para recomendacoes
        prompt = f"""Analise de mercado TAM/SAM/SOM para empresa de licitacoes:
- TAM: {tam_total} editais, R$ {tam_valor:,.2f}
- SAM: {sam_total} editais, R$ {sam_valor:,.2f} ({sam_total/max(tam_total,1)*100:.1f}% do TAM)
- SOM: {som_total} editais estimados, R$ {som_valor:,.2f}
- Taxa vitoria: {taxa_vitoria:.1f}%
- UFs atuacao: {', '.join(ufs_empresa[:10]) if ufs_empresa else 'N/A'}
- Segmentos NCM: {len(ncms_empresa)} distintos
- Periodo: {periodo_meses} meses

Gere 3 recomendacoes estrategicas curtas para expandir o SOM. Responda em JSON:
{{"recomendacoes": ["rec1", "rec2", "rec3"], "oportunidade_principal": "texto curto"}}"""

        recomendacoes = []
        oportunidade = "Expandir atuacao em novas UFs"
        try:
            resp = call_deepseek(prompt, max_tokens=500)
            import json as json_mod
            parsed = json_mod.loads(resp)
            recomendacoes = parsed.get("recomendacoes", [])
            oportunidade = parsed.get("oportunidade_principal", oportunidade)
        except Exception:
            recomendacoes = [
                "Expandir atuacao para UFs adjacentes com demanda identificada",
                "Aumentar taxa de participacao em editais SAM para melhorar SOM",
                "Diversificar portfolio NCM para cobrir mais segmentos do mercado"
            ]

        return {
            "success": True,
            "funil": {
                "tam": {"editais": tam_total, "valor": tam_valor, "label": "Total Addressable Market"},
                "sam": {"editais": sam_total, "valor": sam_valor,
                        "percentual_tam": round(sam_total / max(tam_total, 1) * 100, 1),
                        "label": "Serviceable Available Market"},
                "som": {"editais": som_total, "valor": round(som_valor, 2),
                        "percentual_sam": round(som_total / max(sam_total, 1) * 100, 1),
                        "label": "Serviceable Obtainable Market"},
            },
            "metricas": {
                "taxa_vitoria": round(taxa_vitoria, 1),
                "fator_capacidade": round(fator_capacidade, 3),
                "participados": participados,
                "ganhos": ganhos,
                "ufs_atuacao": len(ufs_empresa),
                "ncms_portfolio": len(ncms_empresa),
            },
            "tendencias": tendencias,
            "recomendacoes": recomendacoes,
            "oportunidade_principal": oportunidade,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_detectar_itens_intrusos(edital_id: str, user_id: str = None,
                                  empresa_id: str = None) -> Dict[str, Any]:
    """
    Detecta itens de um edital que estao fora do portfolio da empresa.
    Compara NCMs dos itens do edital com NCMs dos produtos cadastrados.

    Args:
        edital_id: ID do edital a analisar
        user_id: ID do usuario
        empresa_id: ID da empresa

    Returns:
        Dict com itens intrusos detectados e classificacao de criticidade
    """
    from database import SessionLocal
    from models import Edital, EditalItem, Produto, ItemIntruso
    from sqlalchemy import func

    db = SessionLocal()
    try:
        edital = db.query(Edital).filter(Edital.id == edital_id).first()
        if not edital:
            return {"success": False, "error": "Edital nao encontrado"}

        # NCMs do portfolio da empresa
        ncms_portfolio = set()
        if empresa_id:
            prods = db.query(Produto.ncm).filter(
                Produto.empresa_id == empresa_id,
                Produto.ncm.isnot(None)
            ).distinct().all()
            ncms_portfolio = {r[0] for r in prods if r[0]}

        # Itens do edital
        itens_edital = db.query(EditalItem).filter(
            EditalItem.edital_id == edital_id
        ).all()

        if not itens_edital:
            return {"success": True, "intrusos": [], "total": 0,
                    "mensagem": "Edital sem itens cadastrados"}

        # Valor total do edital para calcular percentual
        valor_total_edital = sum(
            float(it.valor_unitario or 0) * float(it.quantidade or 1)
            for it in itens_edital
        ) or 1.0

        intrusos = []
        prompt_itens = []

        for item in itens_edital:
            ncm_item = (item.ncm or "").strip()
            desc_item = item.descricao or item.nome or ""
            valor_item = float(item.valor_unitario or 0) * float(item.quantidade or 1)
            pct = (valor_item / valor_total_edital) * 100

            is_intruso = False
            if ncm_item and ncms_portfolio:
                # Comparar NCM: se primeiros 4 digitos nao batem com nenhum do portfolio
                prefixo_item = ncm_item[:4]
                match = any(ncm.startswith(prefixo_item) for ncm in ncms_portfolio)
                if not match:
                    is_intruso = True
            elif not ncm_item and ncms_portfolio:
                prompt_itens.append(desc_item)

            if is_intruso:
                if pct > 10:
                    criticidade = 'critico'
                elif pct > 5:
                    criticidade = 'medio'
                else:
                    criticidade = 'informativo'

                intruso = ItemIntruso(
                    user_id=user_id,
                    empresa_id=empresa_id,
                    edital_id=edital_id,
                    descricao_item=desc_item[:500],
                    ncm=ncm_item,
                    valor=Decimal(str(round(valor_item, 2))),
                    percentual_edital=Decimal(str(round(pct, 2))),
                    criticidade=criticidade,
                    acao_sugerida=f"Item fora do portfolio (NCM {ncm_item}). "
                                  f"{'ALTO RISCO - representa {:.1f}% do edital'.format(pct) if criticidade == 'critico' else 'Avaliar impacto'}"
                )
                db.add(intruso)
                intrusos.append({
                    "descricao": desc_item[:200],
                    "ncm": ncm_item,
                    "valor": round(valor_item, 2),
                    "percentual_edital": round(pct, 2),
                    "criticidade": criticidade,
                    "acao_sugerida": intruso.acao_sugerida,
                })

        # Se tem itens sem NCM, usar DeepSeek para classificar
        if prompt_itens and ncms_portfolio:
            prompt = f"""Analise estes itens de licitacao e identifique quais NAO pertencem ao portfolio de uma empresa com NCMs: {', '.join(list(ncms_portfolio)[:20])}.

Itens a analisar:
{chr(10).join(f'- {it}' for it in prompt_itens[:15])}

Responda em JSON: {{"intrusos_indices": [0, 2], "motivos": ["motivo1", "motivo2"]}}
Retorne indices (0-based) dos itens que parecem fora do portfolio."""

            try:
                resp = call_deepseek(prompt, max_tokens=300)
                import json as json_mod
                parsed = json_mod.loads(resp)
                for idx in parsed.get("intrusos_indices", []):
                    if 0 <= idx < len(prompt_itens):
                        intrusos.append({
                            "descricao": prompt_itens[idx][:200],
                            "ncm": None,
                            "valor": 0,
                            "percentual_edital": 0,
                            "criticidade": "informativo",
                            "acao_sugerida": "Item detectado por IA como potencialmente fora do portfolio",
                        })
            except Exception:
                pass

        db.commit()

        return {
            "success": True,
            "edital": {"id": edital_id, "numero": edital.numero, "orgao": edital.orgao},
            "intrusos": intrusos,
            "total": len(intrusos),
            "criticos": sum(1 for i in intrusos if i["criticidade"] == "critico"),
            "valor_risco": sum(i["valor"] for i in intrusos),
            "ncms_portfolio": len(ncms_portfolio),
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_gerar_sugestao_aprendizado(user_id: str = None, empresa_id: str = None,
                                     tipo: str = None) -> Dict[str, Any]:
    """
    Analisa feedbacks registrados e gera sugestoes de ajuste para parametros,
    margens, scores ou estrategias.

    Args:
        user_id: ID do usuario
        empresa_id: ID da empresa
        tipo: Tipo de sugestao (parametro, margem, score, estrategia) ou None para todos

    Returns:
        Dict com sugestoes geradas
    """
    from database import SessionLocal
    from models import AprendizadoFeedback, SugestaoIA
    from sqlalchemy import desc

    db = SessionLocal()
    try:
        # Buscar feedbacks recentes
        q = db.query(AprendizadoFeedback).filter(
            AprendizadoFeedback.user_id == user_id
        )
        if empresa_id:
            q = q.filter(AprendizadoFeedback.empresa_id == empresa_id)
        q = q.order_by(desc(AprendizadoFeedback.created_at)).limit(50)
        feedbacks = q.all()

        if len(feedbacks) < 3:
            return {"success": False, "error": "Minimo de 3 feedbacks necessarios para gerar sugestoes",
                    "feedbacks_disponiveis": len(feedbacks)}

        # Montar resumo dos feedbacks por tipo
        por_tipo = {}
        for fb in feedbacks:
            t = fb.tipo_evento or 'outro'
            if t not in por_tipo:
                por_tipo[t] = []
            por_tipo[t].append({
                "entidade": fb.entidade_tipo,
                "delta": fb.valor_delta,
                "descricao": (fb.descricao or "")[:100],
                "aplicado": fb.aplicado,
            })

        prompt = f"""Analise estes feedbacks de uma empresa de licitacoes e gere sugestoes de melhoria:

Feedbacks por tipo:
{json.dumps(por_tipo, ensure_ascii=False, indent=2, default=str)[:2000]}

Total feedbacks: {len(feedbacks)}
Aplicados: {sum(1 for f in feedbacks if f.aplicado)}

Gere 3-5 sugestoes concretas. Responda em JSON:
{{"sugestoes": [
  {{"tipo": "parametro|margem|score|estrategia",
    "titulo": "titulo curto",
    "descricao": "descricao detalhada da sugestao",
    "confianca": 75,
    "acao_sugerida": "acao concreta a tomar"}}
]}}"""

        sugestoes_geradas = []
        try:
            resp = call_deepseek(prompt, max_tokens=1000)
            import json as json_mod
            parsed = json_mod.loads(resp)

            for sug in parsed.get("sugestoes", [])[:5]:
                nova = SugestaoIA(
                    user_id=user_id,
                    empresa_id=empresa_id,
                    tipo=sug.get("tipo", "estrategia"),
                    titulo=sug.get("titulo", "Sugestao")[:255],
                    descricao=sug.get("descricao", "")[:2000],
                    confianca=Decimal(str(min(100, max(0, sug.get("confianca", 50))))),
                    base_dados_count=len(feedbacks),
                    acao_sugerida=sug.get("acao_sugerida", "")[:2000],
                    status='pendente',
                )
                db.add(nova)
                sugestoes_geradas.append({
                    "tipo": nova.tipo,
                    "titulo": nova.titulo,
                    "descricao": nova.descricao,
                    "confianca": float(nova.confianca),
                    "acao_sugerida": nova.acao_sugerida,
                })

        except Exception as e:
            # Fallback — sugestoes genericas
            fallback = [
                {"tipo": "parametro", "titulo": "Ajustar pesos do score tecnico",
                 "descricao": f"Com base em {len(feedbacks)} feedbacks, os pesos do score podem ser otimizados.",
                 "confianca": 60, "acao_sugerida": "Revisar ParametroScore e recalibrar"},
                {"tipo": "margem", "titulo": "Revisar margens em segmentos com alta perda",
                 "descricao": "Feedbacks indicam perdas recorrentes por preco. Considerar reducao de margem.",
                 "confianca": 55, "acao_sugerida": "Analisar gap de preco nos editais perdidos"},
            ]
            for sug in fallback:
                nova = SugestaoIA(
                    user_id=user_id, empresa_id=empresa_id,
                    tipo=sug["tipo"], titulo=sug["titulo"],
                    descricao=sug["descricao"],
                    confianca=Decimal(str(sug["confianca"])),
                    base_dados_count=len(feedbacks),
                    acao_sugerida=sug["acao_sugerida"],
                    status='pendente',
                )
                db.add(nova)
                sugestoes_geradas.append(sug)

        db.commit()

        return {
            "success": True,
            "sugestoes": sugestoes_geradas,
            "total_geradas": len(sugestoes_geradas),
            "base_feedbacks": len(feedbacks),
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def tool_analisar_padroes(user_id: str = None, empresa_id: str = None) -> Dict[str, Any]:
    """
    Detecta padroes nos dados da empresa: sazonalidade, correlacoes,
    tendencias de preco, comportamento de orgaos, gargalos no pipeline.

    Args:
        user_id: ID do usuario
        empresa_id: ID da empresa

    Returns:
        Dict com padroes detectados e niveis de confianca
    """
    from database import SessionLocal
    from models import (Edital, AprendizadoFeedback, PrecoHistorico,
                        PadraoDetectado, Contrato)
    from sqlalchemy import func, desc
    from collections import Counter

    db = SessionLocal()
    try:
        data_6m = datetime.now() - timedelta(days=180)

        # Coletar dados para analise
        editais = db.query(Edital).filter(
            Edital.empresa_id == empresa_id,
            Edital.created_at >= data_6m
        ).all()

        precos = db.query(PrecoHistorico).filter(
            PrecoHistorico.user_id == user_id,
            PrecoHistorico.created_at >= data_6m
        ).all()

        feedbacks = db.query(AprendizadoFeedback).filter(
            AprendizadoFeedback.user_id == user_id,
            AprendizadoFeedback.created_at >= data_6m
        ).all()

        if len(editais) < 5:
            return {"success": False, "error": "Minimo de 5 editais nos ultimos 6 meses para detectar padroes",
                    "editais_disponiveis": len(editais)}

        # Dados para o prompt
        meses_editais = Counter()
        ufs_editais = Counter()
        stages_editais = Counter()
        for e in editais:
            if e.created_at:
                meses_editais[e.created_at.strftime("%m")] += 1
            if e.uf:
                ufs_editais[e.uf] += 1
            if e.pipeline_stage:
                stages_editais[e.pipeline_stage] += 1

        gaps_preco = []
        for p in precos:
            if p.nosso_preco and p.preco_vencedor:
                gap = float(p.nosso_preco - p.preco_vencedor) / float(p.preco_vencedor) * 100
                gaps_preco.append(round(gap, 1))

        prompt = f"""Analise estes dados de licitacoes e detecte padroes:

Editais por mes (ultimos 6m): {dict(meses_editais)}
Editais por UF: {dict(ufs_editais.most_common(10))}
Pipeline stages: {dict(stages_editais)}
Total editais: {len(editais)}
Total precos: {len(precos)}
Gaps de preco (%): {gaps_preco[:20]}
Feedbacks: {len(feedbacks)}

Detecte padroes de: sazonalidade, correlacao, tendencia_preco, comportamento_orgao, gargalo_pipeline.
Responda em JSON:
{{"padroes": [
  {{"tipo": "sazonalidade|correlacao|tendencia_preco|comportamento_orgao|gargalo_pipeline",
    "titulo": "titulo descritivo",
    "descricao": "descricao do padrao encontrado",
    "confianca": 85,
    "dados": {{"chave": "valor"}}
  }}
]}}"""

        padroes_detectados = []
        try:
            resp = call_deepseek(prompt, max_tokens=1500)
            import json as json_mod
            parsed = json_mod.loads(resp)

            for pad in parsed.get("padroes", [])[:6]:
                tipo = pad.get("tipo", "correlacao")
                tipos_validos = ['sazonalidade', 'correlacao', 'tendencia_preco',
                                 'comportamento_orgao', 'gargalo_pipeline']
                if tipo not in tipos_validos:
                    tipo = 'correlacao'

                # Desativar padroes antigos do mesmo tipo
                db.query(PadraoDetectado).filter(
                    PadraoDetectado.user_id == user_id,
                    PadraoDetectado.empresa_id == empresa_id,
                    PadraoDetectado.tipo == tipo,
                    PadraoDetectado.ativo == True
                ).update({"ativo": False, "updated_at": datetime.now()})

                novo = PadraoDetectado(
                    user_id=user_id,
                    empresa_id=empresa_id,
                    tipo=tipo,
                    titulo=pad.get("titulo", "Padrao")[:255],
                    descricao=pad.get("descricao", "")[:2000],
                    confianca=Decimal(str(min(100, max(0, pad.get("confianca", 50))))),
                    base_dados_count=len(editais) + len(precos) + len(feedbacks),
                    dados_json=pad.get("dados"),
                    ativo=True,
                )
                db.add(novo)
                padroes_detectados.append({
                    "tipo": novo.tipo,
                    "titulo": novo.titulo,
                    "descricao": novo.descricao,
                    "confianca": float(novo.confianca),
                    "dados": novo.dados_json,
                })

        except Exception:
            # Fallback — padroes baseados em heuristica
            if meses_editais:
                meses_ordenados = sorted(meses_editais.items(), key=lambda x: x[1], reverse=True)
                novo = PadraoDetectado(
                    user_id=user_id, empresa_id=empresa_id,
                    tipo='sazonalidade',
                    titulo=f"Pico de editais no mes {meses_ordenados[0][0]}",
                    descricao=f"Concentracao de {meses_ordenados[0][1]} editais no mes {meses_ordenados[0][0]}.",
                    confianca=Decimal('65'),
                    base_dados_count=len(editais),
                    dados_json=dict(meses_editais),
                    ativo=True,
                )
                db.add(novo)
                padroes_detectados.append({
                    "tipo": "sazonalidade", "titulo": novo.titulo,
                    "descricao": novo.descricao, "confianca": 65,
                })

            # Gargalo pipeline
            if stages_editais:
                gargalo = max(stages_editais.items(), key=lambda x: x[1])
                novo = PadraoDetectado(
                    user_id=user_id, empresa_id=empresa_id,
                    tipo='gargalo_pipeline',
                    titulo=f"Acumulo em {gargalo[0]}",
                    descricao=f"{gargalo[1]} editais acumulados no stage {gargalo[0]}.",
                    confianca=Decimal('60'),
                    base_dados_count=len(editais),
                    dados_json=dict(stages_editais),
                    ativo=True,
                )
                db.add(novo)
                padroes_detectados.append({
                    "tipo": "gargalo_pipeline", "titulo": novo.titulo,
                    "descricao": novo.descricao, "confianca": 60,
                })

        db.commit()

        return {
            "success": True,
            "padroes": padroes_detectados,
            "total_detectados": len(padroes_detectados),
            "base_dados": {
                "editais": len(editais),
                "precos": len(precos),
                "feedbacks": len(feedbacks),
            },
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


# Sprint 7 — registrar tools no TOOLS_MAP
TOOLS_MAP["calcular_tam_sam_som"] = tool_calcular_tam_sam_som
TOOLS_MAP["detectar_itens_intrusos"] = tool_detectar_itens_intrusos
TOOLS_MAP["gerar_sugestao_aprendizado"] = tool_gerar_sugestao_aprendizado
TOOLS_MAP["analisar_padroes"] = tool_analisar_padroes


# =============================================================================
# Sprint 8 — Máscara de descrição de produto
# =============================================================================

def tool_aplicar_mascara_descricao(
    descricao: str,
    ncm: str = None,
    campos_mascara: list = None,
    nome_produto: str = None,
    user_id: str = None,
    empresa_id: str = None,
) -> Dict[str, Any]:
    """
    Normaliza a descrição de um produto usando a máscara da subclasse via DeepSeek.
    Retorna descrição padronizada, variantes, sinônimos e score estimado antes/depois.
    """
    try:
        campos_str = ""
        if campos_mascara and isinstance(campos_mascara, list) and len(campos_mascara) > 0:
            linhas = []
            for c in campos_mascara:
                nome = c.get("campo") or c.get("nome") or ""
                tipo = c.get("tipo", "texto")
                unidade = c.get("unidade", "")
                obrig = " (OBRIGATÓRIO)" if c.get("obrigatorio") else ""
                desc = f'- "{nome}" [{tipo}]'
                if unidade:
                    desc += f" (unidade: {unidade})"
                desc += obrig
                linhas.append(desc)
            campos_str = "\nCampos da máscara que DEVEM aparecer na descrição normalizada:\n" + "\n".join(linhas)

        prompt = f"""Você é um especialista em padronização de descrições de produtos para licitações públicas brasileiras.

Produto: {nome_produto or 'N/A'}
Descrição original: {descricao}
NCM: {ncm or 'N/A'}
{campos_str}

Gere uma descrição normalizada que:
1. Seja clara, técnica e padronizada para uso em licitações
2. Inclua todas as especificações relevantes de forma estruturada
3. Use terminologia padrão de editais públicos
4. Incorpore os campos da máscara (se fornecidos) de forma natural

Retorne APENAS um JSON válido com esta estrutura:
{{
  "descricao_normalizada": "Descrição completa normalizada...",
  "variantes": ["variante1", "variante2", "variante3"],
  "sinonimos": ["sinonimo1", "sinonimo2"],
  "score_antes": 45,
  "score_depois": 82,
  "justificativa": "Breve explicação das melhorias"
}}

Onde score_antes é uma estimativa de 0-100 de quão aderente a descrição original seria em editais,
e score_depois é a estimativa após normalização."""

        resposta = call_deepseek(
            [{"role": "user", "content": prompt}],
            max_tokens=2000,
            model_override="deepseek-chat"
        )

        texto = resposta if isinstance(resposta, str) else str(resposta)

        import json as json_mod
        import re as re_mod
        json_match = re_mod.search(r'\{[\s\S]*\}', texto)
        if not json_match:
            return {
                "success": True,
                "descricao_normalizada": texto.strip()[:500],
                "variantes": [],
                "sinonimos": [],
                "score_antes": None,
                "score_depois": None,
            }

        try:
            dados = json_mod.loads(json_match.group(0))
        except json_mod.JSONDecodeError:
            return {
                "success": True,
                "descricao_normalizada": texto.strip()[:500],
                "variantes": [],
                "sinonimos": [],
                "score_antes": None,
                "score_depois": None,
            }

        return {
            "success": True,
            "descricao_normalizada": dados.get("descricao_normalizada", ""),
            "variantes": dados.get("variantes", []),
            "sinonimos": dados.get("sinonimos", []),
            "score_antes": dados.get("score_antes"),
            "score_depois": dados.get("score_depois"),
            "justificativa": dados.get("justificativa", ""),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


TOOLS_MAP["aplicar_mascara_descricao"] = tool_aplicar_mascara_descricao


# =============================================================================
# CV13-9 (Arnaldo Sprint 2 V8) — auto-download de PDF do edital em background
# =============================================================================
def download_pdf_edital_bg(edital_id: str, user_id: str) -> Dict[str, Any]:
    """
    Roda em thread daemon: busca arquivos no PNCP, baixa o PDF principal,
    extrai texto com PyPDF2 e salva em EditalDocumento.texto_extraido.

    Idempotente: se ja existe EditalDocumento com tipo='edital_principal'
    para esse edital, nao faz nada. Engole exceptions (background nao
    pode derrubar o request).
    """
    from datetime import datetime as _dt
    db = get_db()
    try:
        edital = db.query(Edital).filter(Edital.id == edital_id).first()
        if not edital:
            return {"success": False, "error": "edital_nao_encontrado"}

        # Idempotencia: ja tem doc principal?
        ja_tem = db.query(EditalDocumento).filter(
            EditalDocumento.edital_id == edital_id,
            EditalDocumento.tipo == 'edital_principal'
        ).first()
        if ja_tem and ja_tem.texto_extraido and len(ja_tem.texto_extraido) > 500:
            print(f"[CV13-9] Edital {edital.numero} ja tem PDF baixado (skip)")
            return {"success": True, "skipped": True}

        # Precisa de cnpj/ano/seq do PNCP
        if not (edital.cnpj_orgao and edital.ano_compra and edital.seq_compra):
            return {"success": False, "error": "sem_dados_pncp"}

        print(f"[CV13-9] Auto-download iniciado: edital={edital.numero} cnpj={edital.cnpj_orgao}")

        arquivos_result = tool_buscar_arquivos_edital_pncp(
            cnpj=edital.cnpj_orgao, ano=edital.ano_compra, seq=edital.seq_compra
        )
        if not arquivos_result.get('success') or not arquivos_result.get('arquivos'):
            print(f"[CV13-9] Sem arquivos no PNCP para {edital.numero}")
            return {"success": False, "error": "sem_arquivos_pncp"}

        arquivo_edital = arquivos_result.get('arquivo_edital') or arquivos_result['arquivos'][0]
        download_result = tool_baixar_pdf_pncp(
            cnpj=edital.cnpj_orgao,
            ano=edital.ano_compra,
            seq=edital.seq_compra,
            sequencial_arquivo=arquivo_edital['sequencial'],
            user_id=user_id,
            edital_id=edital.id
        )
        if not download_result.get('success'):
            print(f"[CV13-9] Falha no download: {download_result.get('error')}")
            return download_result

        filepath = download_result['filepath']
        filename = download_result['filename']

        # Extrair texto. PDF pode estar dentro de ZIP — reusar helper de app.py
        # nao eh trivial aqui (importacao circular). Usamos PyPDF2 direto;
        # se vier ZIP, o usuario pode pedir reextract manual via /api/editais/<id>/pdf.
        texto_extraido = ""
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(filepath)
            for page in reader.pages:
                try:
                    texto_extraido += page.extract_text() or ""
                except Exception:
                    pass
        except Exception as ex:
            print(f"[CV13-9] Erro PyPDF2 ({filename}): {ex}")
            # Mesmo sem texto, registra o doc para nao re-tentar download.

        novo_doc = EditalDocumento(
            id=str(uuid.uuid4()),
            edital_id=edital.id,
            tipo='edital_principal',
            nome_arquivo=filename,
            path_arquivo=filepath,
            texto_extraido=texto_extraido[:100000] if texto_extraido else None,
            processado=bool(texto_extraido),
            created_at=_dt.now()
        )
        db.add(novo_doc)

        # Atualizar referencias no edital
        edital.pdf_path = filepath
        edital.pdf_url = download_result.get('url') or edital.pdf_url
        edital.pdf_titulo = arquivo_edital.get('titulo')

        db.commit()
        print(f"[CV13-9] OK {edital.numero}: {len(texto_extraido):,} chars salvos")
        return {"success": True, "chars": len(texto_extraido)}

    except Exception as e:
        db.rollback()
        print(f"[CV13-9] Erro inesperado: {type(e).__name__}: {e}")
        return {"success": False, "error": str(e)}
    finally:
        db.close()


TOOLS_MAP["download_pdf_edital_bg"] = download_pdf_edital_bg



# =============================================================================
# FASE 2 — INTELIGÊNCIA COMERCIAL: SCORE GO/NO-GO (RF-SCO-002/003)
# =============================================================================

def tool_score_comercial(user_id: str, empresa_id: str = None,
                         edital_numero: str = None) -> Dict[str, Any]:
    """
    Calcula o score de aderência comercial de um edital para a empresa
    (logística, porte x valor LC 123/2006, histórico de vitórias, prazo)
    e emite recomendação GO / AVALIAR / NO_GO.

    Motor compartilhado com a rota REST /api/inteligencia/.../score-comercial
    (backend/inteligencia_comercial.py).
    """
    from models import get_db, Edital, Empresa
    from inteligencia_comercial import avaliar_score_comercial

    if not edital_numero:
        return {"success": False,
                "error": "Informe o número do edital (ex: PE-001/2026)."}

    db = get_db()
    try:
        q = db.query(Edital).filter(Edital.numero.ilike(f"%{edital_numero}%"))
        if empresa_id:
            q = q.filter(Edital.empresa_id == empresa_id)
        edital = q.first()
        if not edital:
            return {"success": False,
                    "error": f"Edital '{edital_numero}' não encontrado."}

        empresa = db.query(Empresa).filter(
            Empresa.id == empresa_id).first() if empresa_id else None

        resultado = avaliar_score_comercial(db, edital, empresa, empresa_id)
        resultado.update({
            "success": True,
            "edital_id": edital.id,
            "edital_numero": edital.numero,
            "orgao": edital.orgao,
            "uf": edital.uf,
        })
        return resultado
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        db.close()


TOOLS_MAP["score_comercial"] = tool_score_comercial
