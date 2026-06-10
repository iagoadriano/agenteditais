"""
Testes unitários dos motores puros de Inteligência Comercial (Fase 2).
Rodam sem banco: cobrem RF-CLA (classificação), RF-SCO (score comercial)
e RF-PRE (recomendação de preço).

Execução: cd backend && python -m pytest tests/test_inteligencia_comercial.py -v
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inteligencia_comercial import (
    classificar_edital_texto,
    calcular_score_logistico,
    calcular_score_porte,
    calcular_score_historico,
    calcular_score_prazo,
    calcular_score_comercial,
    recomendar_preco,
)


# ══════════════════════════════════════════════════════════════════════════════
# RF-CLA — Classificação
# ══════════════════════════════════════════════════════════════════════════════

class TestClassificacao:
    def test_comodato_detectado(self):
        r = classificar_edital_texto(
            "Contratação de empresa para fornecimento de analisador hematológico "
            "em regime de comodato com fornecimento de reagentes")
        assert r["categoria"] == "comodato"
        assert r["aplicavel"] is True
        assert "comodato" in r["sinais"]

    def test_comodato_prevalece_sobre_locacao(self):
        r = classificar_edital_texto(
            "Locação de equipamento mediante comodato e cessao de uso")
        assert r["categoria"] == "comodato"

    def test_locacao_com_consumo_combina_sinais(self):
        r = classificar_edital_texto(
            "Locação de equipamento de bioquímica com fornecimento de reagente "
            "e calibrador, pagamento por teste realizado")
        assert r["categoria"] == "aluguel_com_consumo"

    def test_locacao_pura(self):
        r = classificar_edital_texto(
            "Locação de equipamento multifuncional para o setor administrativo")
        assert r["categoria"] == "aluguel_sem_consumo"

    def test_venda_equipamento(self):
        r = classificar_edital_texto(
            "Aquisição de equipamento médico hospitalar para a UTI neonatal")
        assert r["categoria"] == "venda_equipamento"

    def test_informatica(self):
        r = classificar_edital_texto(
            "Aquisição de equipamento de informatica: notebook, desktop e impressora")
        assert r["categoria"] == "informatica"

    def test_redes(self):
        r = classificar_edital_texto(
            "Contratação de infraestrutura de rede com switch, roteador e "
            "cabeamento estruturado")
        assert r["categoria"] == "redes"

    def test_mobiliario(self):
        r = classificar_edital_texto(
            "Aquisição de mobiliario escolar: carteira escolar e cadeira")
        assert r["categoria"] == "mobiliario"

    def test_servicos(self):
        r = classificar_edital_texto(
            "Prestação de serviço de manutencao preventiva e corretiva em elevadores")
        assert r["categoria"] == "servicos"

    def test_sem_sinais_retorna_outro(self):
        r = classificar_edital_texto("Objeto genérico sem nenhuma palavra-chave")
        assert r["categoria"] == "outro"
        assert r["aplicavel"] is False
        assert r["confianca"] == 0.0

    def test_acentos_normalizados(self):
        # objeto com acentos casa com keywords sem acento
        r = classificar_edital_texto("Aquisição de equipamento de informática")
        assert r["categoria"] == "informatica"

    def test_usa_textos_complementares(self):
        r = classificar_edital_texto(
            "Registro de preços conforme anexo",
            textos_complementares=["Item 1: reagente para hemograma",
                                   "Item 2: kit diagnostico de dengue"])
        assert r["categoria"] == "consumo_reagentes"

    def test_objeto_vazio(self):
        r = classificar_edital_texto(None)
        assert r["categoria"] == "outro"

    def test_confianca_entre_0_e_1(self):
        r = classificar_edital_texto(
            "Comodato de analisador com reagentes, insumos, manutencao preventiva")
        assert 0.0 <= r["confianca"] <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# RF-SCO — Score comercial
# ══════════════════════════════════════════════════════════════════════════════

class TestScoreLogistico:
    def test_mesma_cidade(self):
        r = calcular_score_logistico("SP", "SP", "Campinas", "Campinas")
        assert r["score"] == 100

    def test_mesma_uf_cidades_diferentes(self):
        r = calcular_score_logistico("SP", "SP", "Campinas", "Santos")
        assert r["score"] == 85

    def test_mesma_regiao(self):
        r = calcular_score_logistico("SP", "MG")
        assert r["score"] == 60

    def test_regioes_diferentes(self):
        r = calcular_score_logistico("SP", "AM")
        assert r["score"] == 30

    def test_sem_uf(self):
        r = calcular_score_logistico(None, "SP")
        assert r["score"] == 50

    def test_case_insensitive(self):
        r = calcular_score_logistico("sp", "SP")
        assert r["score"] == 85


class TestScorePorte:
    def test_me_em_exclusivo(self):
        r = calcular_score_porte("me", 50000)
        assert r["score"] == 100
        assert r["exclusivo_me_epp"] is True

    def test_grande_em_exclusivo_penalizada(self):
        r = calcular_score_porte("grande", 50000)
        assert r["score"] == 10
        assert r["exclusivo_me_epp"] is True

    def test_me_valor_muito_alto(self):
        r = calcular_score_porte("epp", 10_000_000)
        assert r["score"] == 40

    def test_grande_valor_alto(self):
        r = calcular_score_porte("grande", 2_000_000)
        assert r["score"] == 85

    def test_sem_valor_referencia(self):
        r = calcular_score_porte("me", None)
        assert r["score"] == 50

    def test_limiar_80k_exato(self):
        assert calcular_score_porte("me", 80000)["exclusivo_me_epp"] is True
        assert calcular_score_porte("me", 80000.01)["exclusivo_me_epp"] is False


class TestScoreHistorico:
    def test_sem_historico_neutro(self):
        r = calcular_score_historico(0, 0)
        assert r["score"] == 50
        assert r["taxa_geral"] is None

    def test_taxa_geral(self):
        r = calcular_score_historico(10, 4)
        assert r["score"] == 40
        assert r["taxa_geral"] == 0.4

    def test_similares_pesam_mais(self):
        # geral 40%, similar 80% => 0.7*0.8 + 0.3*0.4 = 0.68
        r = calcular_score_historico(10, 4, 5, 4)
        assert r["score"] == 68
        assert r["taxa_similar"] == 0.8


class TestScorePrazo:
    def test_prazo_confortavel(self):
        assert calcular_score_prazo(30)["score"] == 100

    def test_prazo_adequado(self):
        assert calcular_score_prazo(10)["score"] == 75

    def test_prazo_apertado(self):
        assert calcular_score_prazo(4)["score"] == 45

    def test_prazo_critico(self):
        assert calcular_score_prazo(1)["score"] == 20

    def test_ja_aberto(self):
        assert calcular_score_prazo(-2)["score"] == 0

    def test_sem_data(self):
        assert calcular_score_prazo(None)["score"] == 50


class TestScoreComercialFinal:
    def _componente(self, score):
        return {"score": score, "motivo": "teste"}

    def test_tudo_alto_da_go(self):
        r = calcular_score_comercial(
            self._componente(100), self._componente(100),
            self._componente(80), self._componente(100))
        assert r["recomendacao"] == "GO"
        assert r["score_final"] == 93.0

    def test_tudo_baixo_da_no_go(self):
        r = calcular_score_comercial(
            self._componente(30), self._componente(10),
            self._componente(20), self._componente(20))
        assert r["recomendacao"] == "NO_GO"

    def test_meio_termo_da_avaliar(self):
        r = calcular_score_comercial(
            self._componente(60), self._componente(50),
            self._componente(50), self._componente(50))
        assert r["recomendacao"] == "AVALIAR"

    def test_ponderacao_correta(self):
        # 100*0.30 + 0*0.20 + 0*0.35 + 0*0.15 = 30
        r = calcular_score_comercial(
            self._componente(100), self._componente(0),
            self._componente(0), self._componente(0))
        assert r["score_final"] == 30.0


# ══════════════════════════════════════════════════════════════════════════════
# RF-PRE — Recomendação de preço
# ══════════════════════════════════════════════════════════════════════════════

def _hist(ref, venc):
    return {"preco_referencia": ref, "preco_vencedor": venc, "resultado": "derrota"}


class TestRecomendacaoPreco:
    def test_sem_valor_referencia_falha(self):
        r = recomendar_preco(None, [])
        assert r["success"] is False

    def test_amostra_insuficiente_usa_fallback(self):
        r = recomendar_preco(100000, [_hist(100000, 90000)])
        assert r["success"] is True
        assert r["amostra_suficiente"] is False
        assert r["aviso"] is not None
        # fallback: equilibrado = 10% de desconto
        assert r["cenarios"]["equilibrado"]["preco_sugerido"] == 90000.0

    def test_amostra_suficiente_calcula_percentis(self):
        historicos = [
            _hist(100000, 95000),   # 5% desconto
            _hist(100000, 90000),   # 10%
            _hist(100000, 85000),   # 15%
            _hist(100000, 80000),   # 20%
            _hist(100000, 75000),   # 25%
        ]
        r = recomendar_preco(200000, historicos)
        assert r["success"] is True
        assert r["amostra"] == 5
        assert r["amostra_suficiente"] is True
        assert r["desconto_medio_mercado"] == 15.0
        # equilibrado = mediana (15%) sobre 200k = 170k
        assert r["cenarios"]["equilibrado"]["preco_sugerido"] == 170000.0
        # competitivo desconta mais que o conservador
        assert r["cenarios"]["competitivo"]["preco_sugerido"] < \
            r["cenarios"]["conservador"]["preco_sugerido"]

    def test_curva_probabilidade_monotonica(self):
        historicos = [_hist(100000, 95000), _hist(100000, 88000),
                      _hist(100000, 82000), _hist(100000, 70000)]
        r = recomendar_preco(100000, historicos)
        probs = [p["probabilidade_vitoria"] for p in r["curva_probabilidade"]]
        assert probs == sorted(probs)  # mais desconto nunca reduz a probabilidade
        assert probs[0] == 0.0  # desconto 0% não vence ninguém da amostra
        assert probs[-1] == 1.0  # desconto 40% vence todos da amostra

    def test_ignora_registros_invalidos(self):
        historicos = [
            _hist(None, 90000),       # sem referência
            _hist(100000, None),      # sem vencedor
            _hist(100000, 120000),    # vencedor acima da referência (inconsistente)
            _hist(0, 0),              # zeros
        ]
        r = recomendar_preco(100000, historicos)
        assert r["amostra"] == 0
        assert r["amostra_suficiente"] is False
