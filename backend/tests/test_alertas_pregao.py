"""
Testes unitários dos motores puros de Alertas de Pregão (RF-ALE-001/002).
Rodam sem banco.

Execução: cd backend && python -m pytest tests/test_alertas_pregao.py -v
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alertas_pregao import (
    montar_contagem,
    montar_agenda,
    calcular_disparos,
    gerar_ics,
)

AGORA = datetime(2026, 6, 10, 9, 0, 0)


def _edital(numero="PE-001/2026", **datas):
    base = {
        "id": f"id-{numero}",
        "numero": numero,
        "orgao": "Prefeitura de Campinas",
        "uf": "SP",
        "data_abertura": None,
        "data_limite_proposta": None,
        "data_limite_impugnacao": None,
        "data_recursos": None,
    }
    base.update(datas)
    return base


# ══════════════════════════════════════════════════════════════════════════════
# Contagem regressiva
# ══════════════════════════════════════════════════════════════════════════════

class TestContagem:
    def test_dias_e_horas(self):
        c = montar_contagem(AGORA + timedelta(days=5, hours=3), AGORA)
        assert c["dias"] == 5 and c["horas"] == 3
        assert c["texto"] == "5d 3h"
        assert c["urgencia"] == "confortavel"

    def test_menos_de_24h_critico(self):
        c = montar_contagem(AGORA + timedelta(hours=5, minutes=30), AGORA)
        assert c["texto"] == "5h 30min"
        assert c["urgencia"] == "critico"

    def test_entre_24h_e_72h_atencao(self):
        c = montar_contagem(AGORA + timedelta(hours=48), AGORA)
        assert c["urgencia"] == "atencao"

    def test_so_minutos(self):
        c = montar_contagem(AGORA + timedelta(minutes=45), AGORA)
        assert c["texto"] == "45min"
        assert c["urgencia"] == "critico"

    def test_evento_passado(self):
        c = montar_contagem(AGORA - timedelta(hours=1), AGORA)
        assert c["urgencia"] == "encerrado"


# ══════════════════════════════════════════════════════════════════════════════
# Agenda
# ══════════════════════════════════════════════════════════════════════════════

class TestAgenda:
    def test_ordena_por_proximidade(self):
        editais = [
            _edital("PE-002", data_abertura=AGORA + timedelta(days=5)),
            _edital("PE-001", data_abertura=AGORA + timedelta(days=1)),
        ]
        eventos = montar_agenda(editais, AGORA)
        assert [ev["edital_numero"] for ev in eventos] == ["PE-001", "PE-002"]

    def test_multiplos_prazos_do_mesmo_edital(self):
        editais = [_edital(
            "PE-003",
            data_limite_impugnacao=AGORA + timedelta(days=2),
            data_limite_proposta=AGORA + timedelta(days=4),
            data_abertura=AGORA + timedelta(days=5),
        )]
        eventos = montar_agenda(editais, AGORA)
        assert [ev["tipo"] for ev in eventos] == \
            ["impugnacao", "proposta", "abertura"]

    def test_ignora_passado_e_fora_do_horizonte(self):
        editais = [
            _edital("PE-PASSADO", data_abertura=AGORA - timedelta(days=1)),
            _edital("PE-LONGE", data_abertura=AGORA + timedelta(days=60)),
            _edital("PE-OK", data_abertura=AGORA + timedelta(days=10)),
        ]
        eventos = montar_agenda(editais, AGORA, dias_horizonte=30)
        assert [ev["edital_numero"] for ev in eventos] == ["PE-OK"]

    def test_edital_sem_datas_nao_gera_eventos(self):
        assert montar_agenda([_edital("PE-VAZIO")], AGORA) == []

    def test_evento_carrega_contagem_e_label(self):
        eventos = montar_agenda(
            [_edital("PE-004", data_abertura=AGORA + timedelta(hours=10))], AGORA)
        assert eventos[0]["label"] == "Abertura do Pregão"
        assert eventos[0]["contagem"]["urgencia"] == "critico"


# ══════════════════════════════════════════════════════════════════════════════
# Disparos
# ══════════════════════════════════════════════════════════════════════════════

class TestDisparos:
    def test_descarta_disparos_no_passado(self):
        # evento em 2h: alertas de 3 dias e 24h já passaram; 60min e 15min valem
        evento = AGORA + timedelta(hours=2)
        disparos = calcular_disparos(evento, [4320, 1440, 60, 15], AGORA)
        assert [d["tempo_antes_minutos"] for d in disparos] == [60, 15]

    def test_todos_futuros(self):
        evento = AGORA + timedelta(days=10)
        disparos = calcular_disparos(evento, [4320, 1440, 60, 15], AGORA)
        assert len(disparos) == 4
        assert disparos[0]["data_disparo"] == evento - timedelta(minutes=4320)

    def test_remove_duplicados(self):
        evento = AGORA + timedelta(days=1)
        disparos = calcular_disparos(evento, [60, 60, 15], AGORA)
        assert [d["tempo_antes_minutos"] for d in disparos] == [60, 15]

    def test_lista_vazia(self):
        assert calcular_disparos(AGORA + timedelta(days=1), [], AGORA) == []


# ══════════════════════════════════════════════════════════════════════════════
# ICS
# ══════════════════════════════════════════════════════════════════════════════

class TestICS:
    def _eventos(self):
        return montar_agenda(
            [_edital("PE-005/2026, lote 1",
                     data_abertura=AGORA + timedelta(days=3))], AGORA)

    def test_estrutura_basica(self):
        ics = gerar_ics(self._eventos(), AGORA)
        assert ics.startswith("BEGIN:VCALENDAR")
        assert ics.rstrip().endswith("END:VCALENDAR")
        assert ics.count("BEGIN:VEVENT") == 1
        assert ics.count("END:VEVENT") == 1
        assert "BEGIN:VALARM" in ics  # lembrete de 1h embutido

    def test_campos_do_evento(self):
        ics = gerar_ics(self._eventos(), AGORA)
        assert "DTSTART;TZID=America/Sao_Paulo:20260613T090000" in ics
        assert "UID:id-PE-005/2026\\, lote 1-abertura@facilicita.ia" in ics

    def test_escapa_virgulas_e_pontos_e_virgulas(self):
        ics = gerar_ics(self._eventos(), AGORA)
        # vírgula do número do edital deve estar escapada no SUMMARY
        assert "SUMMARY:Abertura do Pregão — PE-005/2026\\, lote 1" in ics

    def test_calendario_vazio_valido(self):
        ics = gerar_ics([], AGORA)
        assert "BEGIN:VCALENDAR" in ics and "END:VCALENDAR" in ics
        assert "BEGIN:VEVENT" not in ics

    def test_quebras_de_linha_crlf(self):
        ics = gerar_ics(self._eventos(), AGORA)
        assert "\r\n" in ics
