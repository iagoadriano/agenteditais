"""
Inteligência Comercial — Fase 2 (RF-CLA, RF-SCO-002/003, RF-PRE)

Três motores que se encadeiam no fluxo GO/NO-GO:
1. RF-CLA  — Classificação automática de editais (preenche Edital.categoria)
2. RF-SCO  — Score de aderência comercial (logística, porte, histórico, prazo)
3. RF-PRE  — Recomendação de preços a partir do histórico de vencedores

Os motores são funções puras (sem ORM) para permitir teste unitário sem banco.
As rotas do blueprint fazem o fetch via SQLAlchemy e delegam aos motores.

IMPORTANTE: este módulo é ADVISORY — não altera propostas, lances nem valores
finais (zona protegida). Apenas sugere; a decisão é sempre do usuário.
"""
import unicodedata
from datetime import datetime
from statistics import median

from flask import Blueprint, request, jsonify

from models import get_db, Edital, Empresa, PrecoHistorico
from crm_routes import require_auth

intel_bp = Blueprint('inteligencia', __name__)


# ══════════════════════════════════════════════════════════════════════════════
# RF-CLA — Classificação automática de editais
# ══════════════════════════════════════════════════════════════════════════════

# Palavras-chave por categoria (valores do enum Edital.categoria).
# Pesos: 3 = termo decisivo, 2 = termo forte, 1 = termo de apoio.
CATEGORIA_KEYWORDS = {
    "comodato": [
        ("comodato", 3), ("cessao de uso", 3), ("emprestimo de equipamento", 3),
        ("equipamento em regime de comodato", 3), ("cessao gratuita", 2),
    ],
    "venda_equipamento": [
        # peso 2 (não 3): "aquisição de equipamento" é genérico e não pode
        # vencer categorias específicas (informatica, redes) em empate
        ("aquisicao de equipamento", 2), ("compra de equipamento", 3),
        ("fornecimento de equipamento", 2), ("aquisicao de aparelho", 2),
        ("equipamento medico", 1), ("equipamento hospitalar", 1),
        ("equipamento laboratorial", 1), ("aquisicao de maquina", 2),
    ],
    "aluguel_com_consumo": [
        ("locacao com fornecimento", 3), ("aluguel com insumos", 3),
        ("locacao de equipamento com reagentes", 3),
        ("locacao de equipamento com insumos", 3),
        ("locacao com consumo", 3), ("franquia de exames", 2),
        ("custo por exame", 2), ("pagamento por teste", 2),
    ],
    "aluguel_sem_consumo": [
        ("locacao de equipamento", 2), ("aluguel de equipamento", 2),
        ("locacao de aparelho", 2), ("locacao de maquina", 2),
        ("locacao mensal", 1),
    ],
    "consumo_reagentes": [
        ("reagente", 3), ("kit de analise", 2), ("kit diagnostico", 3),
        ("calibrador", 2), ("solucao padrao", 1), ("meio de cultura", 2),
        ("teste rapido", 2), ("hemograma", 1), ("bioquimica", 1),
        ("imunologia", 1), ("sorologia", 1),
    ],
    "consumo_insumos": [
        ("insumo", 2), ("material de consumo", 3), ("descartavel", 2),
        ("material hospitalar", 2), ("material de laboratorio", 2),
        ("luva", 1), ("seringa", 1), ("agulha", 1), ("gaze", 1),
        ("material medico hospitalar", 3),
    ],
    "servicos": [
        ("prestacao de servico", 3), ("servicos de manutencao", 3),
        ("manutencao preventiva", 2), ("manutencao corretiva", 2),
        ("servicos continuados", 2), ("mao de obra", 2),
        ("servicos de limpeza", 2), ("servicos de vigilancia", 2),
        ("contratacao de empresa especializada", 1),
    ],
    "informatica": [
        ("computador", 2), ("notebook", 2), ("microcomputador", 2),
        ("software", 2), ("licenca de uso de software", 3), ("servidor de dados", 2),
        ("impressora", 2), ("monitor de video", 1), ("equipamento de informatica", 3),
        ("solucao de tecnologia da informacao", 2), ("desktop", 2),
    ],
    "redes": [
        ("switch", 3), ("roteador", 3), ("cabeamento estruturado", 3),
        ("fibra optica", 2), ("rede logica", 2), ("access point", 2),
        ("rack de rede", 2), ("infraestrutura de rede", 3), ("wi-fi", 1),
    ],
    "mobiliario": [
        ("mobiliario", 3), ("mesa de escritorio", 2), ("cadeira", 2),
        ("armario", 2), ("estante", 2), ("longarina", 2), ("arquivo de aco", 2),
        ("mobiliario escolar", 3), ("carteira escolar", 2),
    ],
}

# Confiança mínima (score absoluto) para considerar a classificação aplicável
CONFIANCA_MINIMA_SCORE = 2


def _normalizar(texto):
    """minúsculas + remove acentos para casamento de keywords"""
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def classificar_edital_texto(objeto, textos_complementares=None):
    """
    RF-CLA: classifica o edital pelo objeto + textos dos itens/requisitos.
    Retorna dict com categoria sugerida, confiança (0-1), sinais encontrados
    e o placar completo por categoria.
    """
    partes = [objeto or ""]
    for t in (textos_complementares or []):
        if t:
            partes.append(t)
    texto = _normalizar(" \n ".join(partes))

    scores = {}
    sinais = {}
    for categoria, keywords in CATEGORIA_KEYWORDS.items():
        total = 0
        encontrados = []
        for kw, peso in keywords:
            if kw in texto:
                total += peso
                encontrados.append(kw)
        if total > 0:
            scores[categoria] = total
            sinais[categoria] = encontrados

    # Regras de desempate de domínio:
    # comodato é juridicamente específico — se presente, prevalece sobre locação
    if "comodato" in scores and "aluguel_sem_consumo" in scores:
        scores["aluguel_sem_consumo"] = 0
    # locação + sinais de consumo => aluguel_com_consumo
    if "aluguel_sem_consumo" in scores and scores.get("aluguel_sem_consumo", 0) > 0 \
            and ("consumo_reagentes" in scores or "consumo_insumos" in scores):
        bonus = max(scores.get("consumo_reagentes", 0), scores.get("consumo_insumos", 0))
        scores["aluguel_com_consumo"] = scores.get("aluguel_com_consumo", 0) \
            + scores["aluguel_sem_consumo"] + bonus
        sinais.setdefault("aluguel_com_consumo", []).extend(
            sinais.get("aluguel_sem_consumo", []))
        scores["aluguel_sem_consumo"] = 0

    scores = {c: s for c, s in scores.items() if s > 0}
    if not scores:
        return {
            "categoria": "outro",
            "confianca": 0.0,
            "sinais": [],
            "scores": {},
            "aplicavel": False,
        }

    melhor = max(scores, key=lambda c: scores[c])
    melhor_score = scores[melhor]
    total_geral = sum(scores.values())
    # confiança = dominância do vencedor sobre o placar total, saturada pelo
    # score absoluto (1 keyword fraca isolada nunca dá confiança alta)
    dominancia = melhor_score / total_geral
    saturacao = min(melhor_score / 6.0, 1.0)
    confianca = round(dominancia * saturacao, 2)

    return {
        "categoria": melhor,
        "confianca": confianca,
        "sinais": sinais.get(melhor, []),
        "scores": scores,
        "aplicavel": melhor_score >= CONFIANCA_MINIMA_SCORE,
    }


# ══════════════════════════════════════════════════════════════════════════════
# RF-SCO-002/003 — Score de aderência comercial
# ══════════════════════════════════════════════════════════════════════════════

REGIOES_UF = {
    "AC": "norte", "AP": "norte", "AM": "norte", "PA": "norte",
    "RO": "norte", "RR": "norte", "TO": "norte",
    "AL": "nordeste", "BA": "nordeste", "CE": "nordeste", "MA": "nordeste",
    "PB": "nordeste", "PE": "nordeste", "PI": "nordeste", "RN": "nordeste",
    "SE": "nordeste",
    "DF": "centro_oeste", "GO": "centro_oeste", "MT": "centro_oeste",
    "MS": "centro_oeste",
    "ES": "sudeste", "MG": "sudeste", "RJ": "sudeste", "SP": "sudeste",
    "PR": "sul", "RS": "sul", "SC": "sul",
}

# LC 123/2006, art. 48, I: itens até R$ 80 mil tendem a ser exclusivos ME/EPP
LIMITE_EXCLUSIVIDADE_ME_EPP = 80000.0

PESOS_SCORE_COMERCIAL = {
    "logistico": 0.30,
    "porte": 0.20,
    "historico": 0.35,
    "prazo": 0.15,
}


def calcular_score_logistico(uf_empresa, uf_edital, cidade_empresa=None, cidade_edital=None):
    """Proximidade logística empresa x órgão: mesma cidade > mesma UF > mesma região."""
    if not uf_empresa or not uf_edital:
        return {"score": 50, "motivo": "UF da empresa ou do edital não informada"}
    uf_empresa, uf_edital = uf_empresa.upper(), uf_edital.upper()
    if uf_empresa == uf_edital:
        if cidade_empresa and cidade_edital and \
                _normalizar(cidade_empresa) == _normalizar(cidade_edital):
            return {"score": 100, "motivo": f"Mesma cidade ({cidade_edital}/{uf_edital})"}
        return {"score": 85, "motivo": f"Mesma UF ({uf_edital})"}
    if REGIOES_UF.get(uf_empresa) == REGIOES_UF.get(uf_edital):
        return {"score": 60, "motivo":
                f"Mesma região ({REGIOES_UF.get(uf_edital, '?')}: {uf_empresa} → {uf_edital})"}
    return {"score": 30, "motivo": f"Regiões diferentes ({uf_empresa} → {uf_edital})"}


def calcular_score_porte(porte_empresa, valor_referencia):
    """Compatibilidade porte da empresa x valor do edital (LC 123/2006)."""
    if not valor_referencia:
        return {"score": 50, "motivo": "Valor de referência não informado",
                "exclusivo_me_epp": False}
    valor = float(valor_referencia)
    exclusivo = valor <= LIMITE_EXCLUSIVIDADE_ME_EPP
    if not porte_empresa:
        return {"score": 50, "motivo": "Porte da empresa não cadastrado",
                "exclusivo_me_epp": exclusivo}
    if porte_empresa in ("me", "epp"):
        if exclusivo:
            return {"score": 100, "exclusivo_me_epp": True, "motivo":
                    "Item até R$ 80 mil: possível exclusividade ME/EPP (LC 123/2006 art. 48) — vantagem competitiva"}
        if valor > 5_000_000:
            return {"score": 40, "exclusivo_me_epp": False, "motivo":
                    "Valor alto para porte ME/EPP — avaliar capacidade de entrega e capital de giro"}
        return {"score": 75, "exclusivo_me_epp": False,
                "motivo": "Valor compatível com porte ME/EPP"}
    # médio / grande
    if exclusivo:
        return {"score": 10, "exclusivo_me_epp": True, "motivo":
                "Item até R$ 80 mil: provável exclusividade ME/EPP — empresa de porte médio/grande pode estar impedida"}
    return {"score": 85, "exclusivo_me_epp": False,
            "motivo": "Sem restrição de porte identificada"}


def calcular_score_historico(participacoes, vitorias, participacoes_similares=0,
                             vitorias_similares=0):
    """
    Histórico de desempenho da empresa. 'Similares' = mesmo órgão, mesma UF ou
    mesma categoria do edital avaliado (o subset pesa mais que o geral).
    """
    if participacoes == 0:
        return {"score": 50, "taxa_geral": None, "taxa_similar": None,
                "motivo": "Sem histórico de participações registrado — score neutro"}
    taxa_geral = vitorias / participacoes
    if participacoes_similares > 0:
        taxa_similar = vitorias_similares / participacoes_similares
        taxa_ponderada = 0.7 * taxa_similar + 0.3 * taxa_geral
        motivo = (f"Taxa de vitória em editais similares: {taxa_similar:.0%} "
                  f"({vitorias_similares}/{participacoes_similares}); geral: {taxa_geral:.0%}")
    else:
        taxa_similar = None
        taxa_ponderada = taxa_geral
        motivo = f"Taxa de vitória geral: {taxa_geral:.0%} ({vitorias}/{participacoes})"
    return {
        "score": round(taxa_ponderada * 100),
        "taxa_geral": round(taxa_geral, 2),
        "taxa_similar": round(taxa_similar, 2) if taxa_similar is not None else None,
        "motivo": motivo,
    }


def calcular_score_prazo(dias_ate_abertura):
    """Tempo disponível para preparar documentação e proposta."""
    if dias_ate_abertura is None:
        return {"score": 50, "motivo": "Data de abertura não informada"}
    if dias_ate_abertura < 0:
        return {"score": 0, "motivo": "Edital já aberto/encerrado"}
    if dias_ate_abertura >= 15:
        return {"score": 100, "motivo": f"{dias_ate_abertura} dias até a abertura — prazo confortável"}
    if dias_ate_abertura >= 7:
        return {"score": 75, "motivo": f"{dias_ate_abertura} dias até a abertura — prazo adequado"}
    if dias_ate_abertura >= 3:
        return {"score": 45, "motivo": f"{dias_ate_abertura} dias até a abertura — prazo apertado"}
    return {"score": 20, "motivo": f"{dias_ate_abertura} dia(s) até a abertura — prazo crítico"}


def calcular_score_comercial(logistico, porte, historico, prazo):
    """Pondera os 4 componentes e emite recomendação GO / AVALIAR / NO_GO."""
    final = (
        logistico["score"] * PESOS_SCORE_COMERCIAL["logistico"]
        + porte["score"] * PESOS_SCORE_COMERCIAL["porte"]
        + historico["score"] * PESOS_SCORE_COMERCIAL["historico"]
        + prazo["score"] * PESOS_SCORE_COMERCIAL["prazo"]
    )
    final = round(final, 1)
    if final >= 70:
        recomendacao = "GO"
    elif final >= 45:
        recomendacao = "AVALIAR"
    else:
        recomendacao = "NO_GO"
    return {
        "score_final": final,
        "recomendacao": recomendacao,
        "pesos": PESOS_SCORE_COMERCIAL,
        "componentes": {
            "logistico": logistico,
            "porte": porte,
            "historico": historico,
            "prazo": prazo,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# RF-PRE — Recomendação de preços por histórico
# ══════════════════════════════════════════════════════════════════════════════

# Descontos default quando a amostra histórica é insuficiente (< 3 registros)
DESCONTOS_FALLBACK = {"conservador": 0.05, "equilibrado": 0.10, "competitivo": 0.18}
AMOSTRA_MINIMA = 3


def _percentil(valores, p):
    """Percentil por interpolação linear (sem numpy)."""
    if not valores:
        return None
    v = sorted(valores)
    if len(v) == 1:
        return v[0]
    k = (len(v) - 1) * p
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def recomendar_preco(valor_referencia, historicos):
    """
    RF-PRE: recomenda faixa de preço para o edital a partir do histórico de
    preços vencedores (lista de dicts com preco_referencia, preco_vencedor,
    resultado). Retorna 3 cenários + curva de probabilidade de vitória por
    faixa de desconto.
    """
    if not valor_referencia or float(valor_referencia) <= 0:
        return {"success": False,
                "error": "Edital sem valor de referência — impossível recomendar preço"}
    valor_ref = float(valor_referencia)

    descontos = []
    for h in historicos or []:
        ref = h.get("preco_referencia")
        venc = h.get("preco_vencedor")
        if ref and venc and float(ref) > 0 and 0 < float(venc) <= float(ref):
            descontos.append((float(ref) - float(venc)) / float(ref))

    amostra_suficiente = len(descontos) >= AMOSTRA_MINIMA

    if amostra_suficiente:
        cenarios_desc = {
            # conservador: desconto baixo (p25) — protege margem
            "conservador": _percentil(descontos, 0.25),
            # equilibrado: desconto mediano do mercado
            "equilibrado": median(descontos),
            # competitivo: desconto alto (p75) — maximiza chance de vitória
            "competitivo": _percentil(descontos, 0.75),
        }
    else:
        cenarios_desc = dict(DESCONTOS_FALLBACK)

    cenarios = {
        nome: {
            "desconto_percentual": round(d * 100, 2),
            "preco_sugerido": round(valor_ref * (1 - d), 2),
        }
        for nome, d in cenarios_desc.items()
    }

    # Curva: a cada faixa de desconto d, fração dos certames históricos em que
    # um lance com desconto d teria igualado/superado o vencedor real
    curva = []
    if amostra_suficiente:
        for d_pct in range(0, 45, 5):
            d = d_pct / 100.0
            vence = sum(1 for hist_d in descontos if d >= hist_d)
            curva.append({
                "desconto_percentual": d_pct,
                "preco": round(valor_ref * (1 - d), 2),
                "probabilidade_vitoria": round(vence / len(descontos), 2),
            })

    return {
        "success": True,
        "valor_referencia": valor_ref,
        "amostra": len(descontos),
        "amostra_suficiente": amostra_suficiente,
        "desconto_medio_mercado": round(sum(descontos) / len(descontos) * 100, 2)
        if descontos else None,
        "cenarios": cenarios,
        "curva_probabilidade": curva,
        "aviso": None if amostra_suficiente else
        f"Histórico insuficiente ({len(descontos)} registro(s) com preço de referência e vencedor). "
        "Cenários usam descontos padrão de mercado — alimente a base de preços históricos "
        "(atas PNCP, painel de preços) para recomendações calibradas.",
    }


# ══════════════════════════════════════════════════════════════════════════════
# Helpers de rota
# ══════════════════════════════════════════════════════════════════════════════

def _get_edital_escopado(db, edital_id):
    q = db.query(Edital).filter(Edital.id == edital_id)
    if not request.is_super and request.empresa_id:
        q = q.filter(Edital.empresa_id == request.empresa_id)
    return q.first()


def _get_empresa(db):
    if not request.empresa_id:
        return None
    return db.query(Empresa).filter(Empresa.id == request.empresa_id).first()


def _classificar_e_aplicar(db, edital, aplicar):
    textos = [i.descricao for i in edital.itens if i.descricao]
    textos += [r.descricao for r in edital.requisitos if r.descricao]
    resultado = classificar_edital_texto(edital.objeto, textos)
    aplicada = False
    if aplicar and resultado["aplicavel"]:
        edital.categoria = resultado["categoria"]
        edital.updated_at = datetime.now()
        aplicada = True
    return resultado, aplicada


# ══════════════════════════════════════════════════════════════════════════════
# Rotas
# ══════════════════════════════════════════════════════════════════════════════

@intel_bp.route('/api/inteligencia/editais/<edital_id>/classificar', methods=['POST'])
@require_auth
def classificar_edital(edital_id):
    """RF-CLA: classifica 1 edital. Body: {"aplicar": bool} (default true)."""
    body = request.get_json(silent=True) or {}
    aplicar = body.get("aplicar", True)
    db = get_db()
    try:
        edital = _get_edital_escopado(db, edital_id)
        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404
        categoria_anterior = edital.categoria
        resultado, aplicada = _classificar_e_aplicar(db, edital, aplicar)
        if aplicada:
            db.commit()
        return jsonify({
            "success": True,
            "edital_id": edital.id,
            "categoria_anterior": categoria_anterior,
            "classificacao": resultado,
            "aplicada": aplicada,
        })
    finally:
        db.close()


@intel_bp.route('/api/inteligencia/editais/classificar-lote', methods=['POST'])
@require_auth
def classificar_lote():
    """RF-CLA: classifica em lote. Body: {"apenas_sem_categoria": bool, "aplicar": bool}."""
    body = request.get_json(silent=True) or {}
    apenas_sem = body.get("apenas_sem_categoria", True)
    aplicar = body.get("aplicar", True)
    db = get_db()
    try:
        q = db.query(Edital)
        if not request.is_super and request.empresa_id:
            q = q.filter(Edital.empresa_id == request.empresa_id)
        if apenas_sem:
            q = q.filter(Edital.categoria.is_(None))
        editais = q.all()
        resultados = []
        aplicadas = 0
        for edital in editais:
            resultado, aplicada = _classificar_e_aplicar(db, edital, aplicar)
            if aplicada:
                aplicadas += 1
            resultados.append({
                "edital_id": edital.id,
                "numero": edital.numero,
                "categoria": resultado["categoria"],
                "confianca": resultado["confianca"],
                "aplicada": aplicada,
            })
        if aplicadas:
            db.commit()
        return jsonify({
            "success": True,
            "total_processados": len(resultados),
            "total_aplicadas": aplicadas,
            "resultados": resultados,
        })
    finally:
        db.close()


@intel_bp.route('/api/inteligencia/editais/<edital_id>/score-comercial', methods=['GET'])
@require_auth
def score_comercial(edital_id):
    """RF-SCO-002/003: score comercial do edital para a empresa logada."""
    db = get_db()
    try:
        edital = _get_edital_escopado(db, edital_id)
        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404
        empresa = _get_empresa(db)

        logistico = calcular_score_logistico(
            empresa.uf if empresa else None, edital.uf,
            empresa.cidade if empresa else None, edital.cidade,
        )
        porte = calcular_score_porte(
            empresa.porte if empresa else None, edital.valor_referencia)

        # Histórico: PrecoHistorico da empresa com resultado conhecido
        hist_q = db.query(PrecoHistorico).filter(
            PrecoHistorico.resultado.in_(["vitoria", "derrota"]))
        if not request.is_super and request.empresa_id:
            hist_q = hist_q.filter(PrecoHistorico.empresa_id == request.empresa_id)
        registros = hist_q.all()
        participacoes = len(registros)
        vitorias = sum(1 for r in registros if r.resultado == "vitoria")

        # Subconjunto similar: mesmo órgão ou mesma UF do edital avaliado
        similares = []
        for r in registros:
            e = db.query(Edital).filter(Edital.id == r.edital_id).first() \
                if r.edital_id else None
            if e and (e.orgao == edital.orgao or (e.uf and e.uf == edital.uf)):
                similares.append(r)
        historico = calcular_score_historico(
            participacoes, vitorias,
            len(similares), sum(1 for r in similares if r.resultado == "vitoria"))

        dias = None
        if edital.data_abertura:
            dias = (edital.data_abertura - datetime.now()).days
        prazo = calcular_score_prazo(dias)

        resultado = calcular_score_comercial(logistico, porte, historico, prazo)
        resultado.update({
            "success": True,
            "edital_id": edital.id,
            "edital_numero": edital.numero,
            "empresa_id": empresa.id if empresa else None,
        })
        return jsonify(resultado)
    finally:
        db.close()


@intel_bp.route('/api/inteligencia/editais/<edital_id>/recomendacao-preco', methods=['GET'])
@require_auth
def recomendacao_preco(edital_id):
    """RF-PRE: recomendação de preço baseada no histórico de vencedores."""
    db = get_db()
    try:
        edital = _get_edital_escopado(db, edital_id)
        if not edital:
            return jsonify({"error": "Edital não encontrado"}), 404

        hist_q = db.query(PrecoHistorico).filter(
            PrecoHistorico.preco_referencia.isnot(None),
            PrecoHistorico.preco_vencedor.isnot(None),
        )
        if not request.is_super and request.empresa_id:
            hist_q = hist_q.filter(PrecoHistorico.empresa_id == request.empresa_id)
        registros = hist_q.all()

        # Prefere histórico da mesma categoria/UF se houver amostra suficiente
        contexto = "geral"
        if edital.categoria or edital.uf:
            filtrados = []
            for r in registros:
                e = db.query(Edital).filter(Edital.id == r.edital_id).first() \
                    if r.edital_id else None
                if not e:
                    continue
                if (edital.categoria and e.categoria == edital.categoria) or \
                        (edital.uf and e.uf == edital.uf):
                    filtrados.append(r)
            if len(filtrados) >= AMOSTRA_MINIMA:
                registros = filtrados
                contexto = "mesma_categoria_ou_uf"

        historicos = [r.to_dict() for r in registros]
        resultado = recomendar_preco(edital.valor_referencia, historicos)
        if not resultado.get("success"):
            return jsonify(resultado), 422
        resultado.update({
            "edital_id": edital.id,
            "edital_numero": edital.numero,
            "contexto_amostra": contexto,
        })
        return jsonify(resultado)
    finally:
        db.close()
