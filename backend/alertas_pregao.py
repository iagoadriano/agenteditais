"""
Alertas de Pregão — Fase 2 (RF-ALE-001/002)

Completa o módulo de alertas existente (scheduler.py dispara, tools.py
configura via chat) com o que faltava do PLANO_FASE2.md:

- RF-ALE-001: agenda de contagem regressiva — todos os prazos futuros
  (abertura, proposta, impugnação, recursos) dos editais da empresa
- RF-ALE-002: exportação iCalendar (.ics) para Google Calendar / Outlook
- Agendamento automático em massa: aplica os tempos padrão do usuário
  (PreferenciasNotificacao.alertas_padrao) a todos os prazos futuros que
  ainda não têm alerta, de forma idempotente

Funções de cálculo e geração de ICS são puras (testáveis sem banco).
"""
import uuid
from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify, Response

from models import get_db, Edital, Alerta, PreferenciasNotificacao
from crm_routes import require_auth

alertas_bp = Blueprint('alertas_pregao', __name__)

# (tipo de alerta, campo de data no Edital, label humano)
TIPOS_EVENTO = [
    ("abertura", "data_abertura", "Abertura do Pregão"),
    ("proposta", "data_limite_proposta", "Limite para Proposta"),
    ("impugnacao", "data_limite_impugnacao", "Limite para Impugnação"),
    ("recursos", "data_recursos", "Prazo de Recursos"),
]

# Tempos padrão (minutos antes) quando o usuário não tem preferências salvas
ALERTAS_PADRAO_DEFAULT = [4320, 1440, 60, 15]  # 3 dias, 24h, 1h, 15min


# ══════════════════════════════════════════════════════════════════════════════
# Motores puros
# ══════════════════════════════════════════════════════════════════════════════

def montar_contagem(data_evento, agora):
    """Contagem regressiva até o evento, com nível de urgência para a UI."""
    delta = data_evento - agora
    segundos = delta.total_seconds()
    if segundos <= 0:
        return {"dias": 0, "horas": 0, "minutos": 0,
                "texto": "encerrado", "urgencia": "encerrado"}
    dias = int(segundos // 86400)
    horas = int((segundos % 86400) // 3600)
    minutos = int((segundos % 3600) // 60)
    if dias > 0:
        texto = f"{dias}d {horas}h"
    elif horas > 0:
        texto = f"{horas}h {minutos}min"
    else:
        texto = f"{minutos}min"
    if segundos < 24 * 3600:
        urgencia = "critico"
    elif segundos < 72 * 3600:
        urgencia = "atencao"
    else:
        urgencia = "confortavel"
    return {"dias": dias, "horas": horas, "minutos": minutos,
            "texto": texto, "urgencia": urgencia}


def montar_agenda(editais, agora, dias_horizonte=30):
    """
    RF-ALE-001: lista de eventos futuros (até dias_horizonte) a partir dos
    editais. `editais` = iterável de objetos/dicts com numero, orgao, uf e os
    4 campos de data. Retorna eventos ordenados por proximidade.
    """
    limite = agora + timedelta(days=dias_horizonte)
    eventos = []
    for e in editais:
        get = (lambda campo, obj=e: obj.get(campo)) if isinstance(e, dict) \
            else (lambda campo, obj=e: getattr(obj, campo, None))
        for tipo, campo, label in TIPOS_EVENTO:
            data_evento = get(campo)
            if not data_evento or not (agora < data_evento <= limite):
                continue
            eventos.append({
                "edital_id": get("id"),
                "edital_numero": get("numero"),
                "orgao": get("orgao"),
                "uf": get("uf"),
                "tipo": tipo,
                "label": label,
                "data_evento": data_evento.isoformat(),
                "contagem": montar_contagem(data_evento, agora),
            })
    eventos.sort(key=lambda ev: ev["data_evento"])
    return eventos


def calcular_disparos(data_evento, tempos_minutos, agora):
    """Momentos de disparo futuros para um evento (descarta os já passados)."""
    disparos = []
    for minutos in sorted(set(tempos_minutos or []), reverse=True):
        momento = data_evento - timedelta(minutes=minutos)
        if momento > agora:
            disparos.append({"tempo_antes_minutos": minutos, "data_disparo": momento})
    return disparos


def _escape_ics(texto):
    return (str(texto or "")
            .replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\n", "\\n"))


def gerar_ics(eventos, agora, fuso="America/Sao_Paulo"):
    """
    RF-ALE-002: gera calendário iCalendar (RFC 5545) com os eventos da agenda.
    Cada evento leva um VALARM de 1h antes; importável em Google Calendar,
    Outlook e Apple Calendar. Datas em horário local flutuante (TZID).
    """
    stamp = agora.strftime("%Y%m%dT%H%M%S")
    linhas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Facilicita.IA//Alertas de Pregao//PT-BR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Pregões — Facilicita.IA",
    ]
    for ev in eventos:
        data_evento = datetime.fromisoformat(ev["data_evento"])
        dtstart = data_evento.strftime("%Y%m%dT%H%M%S")
        uid = f"{ev['edital_id']}-{ev['tipo']}@facilicita.ia"
        resumo = f"{ev['label']} — {ev['edital_numero']}"
        descricao = f"Órgão: {ev['orgao']}" + (f" ({ev['uf']})" if ev.get("uf") else "")
        linhas += [
            "BEGIN:VEVENT",
            f"UID:{_escape_ics(uid)}",
            f"DTSTAMP:{stamp}",
            f"DTSTART;TZID={fuso}:{dtstart}",
            f"SUMMARY:{_escape_ics(resumo)}",
            f"DESCRIPTION:{_escape_ics(descricao)}",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_escape_ics(resumo)}",
            "TRIGGER:-PT1H",
            "END:VALARM",
            "END:VEVENT",
        ]
    linhas.append("END:VCALENDAR")
    return "\r\n".join(linhas) + "\r\n"


# ══════════════════════════════════════════════════════════════════════════════
# Rotas
# ══════════════════════════════════════════════════════════════════════════════

def _editais_da_empresa(db):
    q = db.query(Edital)
    if not request.is_super and request.empresa_id:
        q = q.filter(Edital.empresa_id == request.empresa_id)
    return q.all()


@alertas_bp.route('/api/alertas/agenda', methods=['GET'])
@require_auth
def agenda_pregoes():
    """RF-ALE-001: agenda de contagem regressiva dos prazos futuros."""
    try:
        dias = min(int(request.args.get("dias", 30)), 365)
    except ValueError:
        dias = 30
    agora = datetime.now()
    db = get_db()
    try:
        eventos = montar_agenda(_editais_da_empresa(db), agora, dias)

        # Anota quantos alertas agendados cada evento já tem
        edital_ids = list({ev["edital_id"] for ev in eventos})
        contagem_alertas = {}
        if edital_ids:
            alertas = db.query(Alerta).filter(
                Alerta.edital_id.in_(edital_ids),
                Alerta.status == 'agendado',
            ).all()
            for a in alertas:
                contagem_alertas[(a.edital_id, a.tipo)] = \
                    contagem_alertas.get((a.edital_id, a.tipo), 0) + 1
        for ev in eventos:
            ev["alertas_agendados"] = contagem_alertas.get(
                (ev["edital_id"], ev["tipo"]), 0)

        return jsonify({
            "success": True,
            "agora": agora.isoformat(),
            "dias_horizonte": dias,
            "total": len(eventos),
            "eventos": eventos,
        })
    finally:
        db.close()


@alertas_bp.route('/api/alertas/agendar-automatico', methods=['POST'])
@require_auth
def agendar_automatico():
    """
    Sistema de Alertas (RF-ALE): cria alertas com os tempos padrão do usuário
    para todos os prazos futuros sem alerta agendado. Idempotente — eventos
    que já têm alerta agendado são pulados.
    """
    body = request.get_json(silent=True) or {}
    try:
        dias = min(int(body.get("dias", 30)), 365)
    except (TypeError, ValueError):
        dias = 30
    agora = datetime.now()
    db = get_db()
    try:
        prefs = db.query(PreferenciasNotificacao).filter(
            PreferenciasNotificacao.user_id == request.user_id).first()
        tempos = (prefs.alertas_padrao if prefs and prefs.alertas_padrao
                  else ALERTAS_PADRAO_DEFAULT)

        eventos = montar_agenda(_editais_da_empresa(db), agora, dias)
        criados = 0
        eventos_cobertos = 0
        for ev in eventos:
            ja_tem = db.query(Alerta).filter(
                Alerta.edital_id == ev["edital_id"],
                Alerta.tipo == ev["tipo"],
                Alerta.status == 'agendado',
            ).count()
            if ja_tem:
                continue
            data_evento = datetime.fromisoformat(ev["data_evento"])
            disparos = calcular_disparos(data_evento, tempos, agora)
            if not disparos:
                continue
            for d in disparos:
                db.add(Alerta(
                    id=str(uuid.uuid4()),
                    user_id=request.user_id,
                    empresa_id=request.empresa_id,
                    edital_id=ev["edital_id"],
                    tipo=ev["tipo"],
                    data_disparo=d["data_disparo"],
                    tempo_antes_minutos=d["tempo_antes_minutos"],
                    status='agendado',
                    titulo=f"{ev['label']} — {ev['edital_numero']}",
                ))
                criados += 1
            eventos_cobertos += 1
        if criados:
            db.commit()
        return jsonify({
            "success": True,
            "tempos_padrao_minutos": tempos,
            "eventos_no_horizonte": len(eventos),
            "eventos_cobertos_agora": eventos_cobertos,
            "alertas_criados": criados,
        })
    finally:
        db.close()


@alertas_bp.route('/api/alertas/agenda/ics', methods=['GET'])
@require_auth
def exportar_ics():
    """RF-ALE-002: exporta a agenda como arquivo .ics (Google/Outlook/Apple)."""
    try:
        dias = min(int(request.args.get("dias", 30)), 365)
    except ValueError:
        dias = 30
    agora = datetime.now()
    db = get_db()
    try:
        eventos = montar_agenda(_editais_da_empresa(db), agora, dias)
        conteudo = gerar_ics(eventos, agora)
        return Response(
            conteudo,
            mimetype="text/calendar",
            headers={"Content-Disposition":
                     "attachment; filename=pregoes_facilicita.ics"},
        )
    finally:
        db.close()
