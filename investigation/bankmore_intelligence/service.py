import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .db import audit, cases, events, now, reports, reviews
from .models import AlertEvent, Proposal
from .rag import Ollama, PROMPT_VERSION, search

ALERT_TOPICS = {"fraude.alerta", "transferencia.rejeitada"}
TOPICS = ALERT_TOPICS | {"transferencia.aprovada"}


class Conflict(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def record(conn, subject, action, case_id=None, **details):
    conn.execute(audit.insert().values(id=uuid.uuid4().hex, subject=subject, action=action,
        case_id=case_id, details=details, created_at=now()))


class Investigation:
    def __init__(self, engine, settings, provider=None):
        self.engine = engine
        self.settings = settings
        self.provider = provider if provider is not None else (Ollama(settings) if settings.mode == "ollama" else None)

    def ingest(self, raw, topic, queue="operacoes", synthetic=False):
        if topic not in TOPICS:
            raise ValueError("Tópico fora do escopo do MVP de transferências")
        event = AlertEvent.model_validate(raw)
        if topic == "transferencia.rejeitada" and event.decisao != "REJEITADA":
            raise ValueError("Decisão incompatível com tópico")
        if topic != "transferencia.rejeitada" and event.decisao != "APROVADA":
            raise ValueError("Decisão incompatível com tópico")
        customer = hmac.new(self.settings.pseudonym_key.encode(), event.cpfOrigem.encode(), hashlib.sha256).hexdigest()
        payload = event.model_dump(mode="json", exclude={"cpfOrigem"})
        payload["valor"] = str(event.valor.quantize(Decimal("0.01")))
        payload["timestamp"] = event.timestamp.astimezone(timezone.utc).isoformat()
        payload["decididoEm"] = event.decididoEm.astimezone(timezone.utc).isoformat()
        payload["customer"] = customer
        payload["synthetic"] = synthetic
        key = digest([queue, topic, event.id])
        fingerprint = digest(payload)
        try:
            with self.engine.begin() as conn:
                existing = conn.execute(select(events).where(events.c.event_key == key)).mappings().first()
                if existing:
                    if existing["digest"] != fingerprint:
                        raise Conflict("Evento repetido com conteúdo diferente; snapshot preservado")
                    return key
                # Include only facts already observed and occurring no later than the decision.
                upper = event.decididoEm.timestamp() * 1000
                lower = (event.decididoEm - timedelta(hours=24)).timestamp() * 1000
                history = select(events.c.transaction_id, events.c.amount).where(
                    events.c.queue == queue, events.c.customer == customer,
                    events.c.occurred_ms >= lower, events.c.occurred_ms <= upper,
                    events.c.transaction_id != event.id).distinct().subquery()
                aggregates = conn.execute(select(func.count(), func.avg(history.c.amount), func.sum(history.c.amount))
                    .select_from(history)).one()
                summary = {"previous_count_24h": aggregates[0],
                    "previous_mean_24h": str(Decimal(str(aggregates[1])).quantize(Decimal("0.01"))) if aggregates[1] is not None else None,
                    "previous_total_24h": str(aggregates[2] or Decimal("0.00")),
                    "as_of": payload["decididoEm"], "coverage": "Projeção parcial dos eventos recebidos; não é extrato bancário completo."}
                conn.execute(events.insert().values(event_key=key, digest=fingerprint, queue=queue,
                    transaction_id=event.id, customer=customer, topic=topic, occurred_ms=event.timestamp.timestamp()*1000,
                    amount=event.valor, payload=payload, received_at=now()))
                if topic in ALERT_TOPICS:
                    snapshot = {"event": payload, "topic": topic, "summary": summary,
                        "limitations": ["Features exatas usadas pelo detector não constam no evento.",
                            "Dispositivo, geolocalização e confirmação do cliente não estão disponíveis.",
                            summary["coverage"]]}
                    conn.execute(cases.insert().values(id=key, queue=queue, status="ABERTO", version=1,
                        snapshot=snapshot, created_at=now()))
                    record(conn, "consumer", "case.created", key, snapshot_hash=digest(snapshot))
            return key
        except IntegrityError:
            # Another consumer may commit the same event before this transaction.
            with self.engine.connect() as conn:
                old = conn.execute(select(events.c.digest).where(events.c.event_key == key)).scalar_one_or_none()
                if old == fingerprint:
                    return key
            raise

    def get_case(self, conn, case_id, identity):
        row = conn.execute(select(cases).where(cases.c.id == case_id, cases.c.queue == identity["queue"])).mappings().first()
        if not row:
            raise LookupError("Caso não encontrado")
        return dict(row)

    def list_cases(self, identity, limit=20, offset=0, status=None):
        if not 1 <= limit <= 50 or not 0 <= offset <= 10000:
            raise ValueError("Paginação fora do limite")
        query = select(cases).where(cases.c.queue == identity["queue"])
        if status:
            if status not in {"ABERTO", "EM_REVISAO", "ENCERRADO"}:
                raise ValueError("Status inválido")
            query = query.where(cases.c.status == status)
        with self.engine.begin() as conn:
            rows = conn.execute(query.order_by(cases.c.created_at.desc(), cases.c.id).limit(limit).offset(offset)).mappings()
            result = [{"id": r["id"], "status": r["status"], "version": r["version"], "created_at": r["created_at"],
                       "event": r["snapshot"]["event"]} for r in rows]
            record(conn, identity["subject"], "cases.list", limit=limit, offset=offset)
            return result

    def evidence(self, case_id, identity):
        with self.engine.begin() as conn:
            case = self.get_case(conn, case_id, identity)
            case["snapshot_hash"] = digest(case["snapshot"])
            case["reports"] = [dict(r) for r in conn.execute(select(reports).where(reports.c.case_id == case_id)
                .order_by(reports.c.created_at.desc()).limit(20)).mappings()]
            case["reviews"] = [dict(r) for r in conn.execute(select(reviews).where(reviews.c.case_id == case_id)).mappings()]
            case["timeline"] = [dict(r) for r in conn.execute(select(audit).where(audit.c.case_id == case_id)
                .order_by(audit.c.created_at).limit(100)).mappings()]
            record(conn, identity["subject"], "case.read", case_id)
            return case

    def summary(self, case_id, identity):
        with self.engine.begin() as conn:
            case = self.get_case(conn, case_id, identity)
            record(conn, identity["subject"], "summary.read", case_id)
            return case["snapshot"]["summary"]

    def procedures(self, case_id, query, identity, limit=3):
        with self.engine.begin() as conn:
            case = self.get_case(conn, case_id, identity)
            record(conn, identity["subject"], "procedures.search", case_id, query_hash=digest(query))
        return search(self.engine, self.settings, query, case["snapshot"]["event"]["decididoEm"], identity["queue"], limit, self.provider)

    def similar(self, case_id, identity, limit=3):
        if not 1 <= limit <= 5:
            raise ValueError("Limite deve estar entre 1 e 5")
        with self.engine.begin() as conn:
            case = self.get_case(conn, case_id, identity)
            # Only human-reviewed cases, already closed by the current case's creation time.
            candidates = conn.execute(select(cases.c.id, cases.c.snapshot, reviews.c.outcome)
                .join(reviews, reviews.c.case_id == cases.c.id).where(cases.c.queue == identity["queue"],
                    cases.c.id != case_id, reviews.c.created_at < case["created_at"])
                .order_by(reviews.c.created_at.desc()).limit(100)).mappings()
            current = case["snapshot"]["event"]
            ranked = sorted(candidates, key=lambda r: (
                r["snapshot"]["event"]["tipo"] != current["tipo"],
                abs(Decimal(r["snapshot"]["event"]["valor"]) - Decimal(current["valor"]))))[:limit]
            record(conn, identity["subject"], "reviewed_cases.search", case_id)
            return {"method": "mesmo tipo, proximidade de valor; não implica mesma causa",
                    "cases": [{"id": r["id"], "outcome": r["outcome"], "event": r["snapshot"]["event"]} for r in ranked]}

    def draft(self, case_id, version, identity):
        start = time.monotonic()
        with self.engine.connect() as conn:
            case = self.get_case(conn, case_id, identity)
        if case["version"] != version or case["status"] == "ENCERRADO":
            raise Conflict("Caso alterado ou encerrado; atualize a tela")
        snapshot = case["snapshot"]
        event, summary = snapshot["event"], snapshot["summary"]
        facts = [
            {"id": "E1", "label": "Evento do detector", "data": event},
            {"id": "E2", "label": "Histórico parcial anterior à decisão", "data": summary}]
        query = "evidências insuficientes histórico" if not summary["previous_count_24h"] else (
            "burst pagamentos sequenciais" if any("BURST" in r for r in event["motivos"]) else "contexto possível falso positivo valor histórico")
        degraded = None
        try:
            retrieval = self.procedures(case_id, query, identity)
        except (httpx.HTTPError, ValueError, KeyError):
            # Still create a useful, explicitly degraded dossier; never discard the alert.
            degraded = "Busca semântica indisponível; recuperação lexical utilizada."
            retrieval = search(self.engine, self.settings, query, event["decididoEm"], identity["queue"])
        previous = self.similar(case_id, identity)
        context = {"facts": facts, "procedures": retrieval["documents"], "reviewed_cases": previous,
                   "limitations": snapshot["limitations"]}
        generation = {"mode": "demo-template", "model": None, "prompt_version": PROMPT_VERSION,
                      "input_tokens": None, "output_tokens": None}
        try:
            if self.provider:
                proposal, usage = self.provider.propose(context)
                self.validate_proposal(proposal, retrieval)
                generation.update(usage, mode="ollama")
            else:
                proposal = self.demo_proposal(snapshot, retrieval)
        except (httpx.HTTPError, ValueError, KeyError):
            proposal = Proposal(hipoteses=[{"texto": "Análise generativa indisponível ou inválida; evidências exigem revisão humana.", "evidencias": ["E1"]}],
                recomendacao="COLETAR_EVIDENCIAS", limitacoes=["Não foi possível validar a resposta do modelo."], procedimentos=[])
            generation["mode"] = "degraded"
        if degraded:
            proposal.limitacoes.append(degraded)
        self.validate_proposal(proposal, retrieval)
        report_id = uuid.uuid4().hex
        content = {"facts": facts, "proposal": proposal.model_dump(), "retrieval": retrieval,
            "reviewed_cases": previous, "limitations": snapshot["limitations"], "generation": generation,
            "requires_human_review": True, "latency_ms": round((time.monotonic()-start)*1000)}
        with self.engine.begin() as conn:
            changed = conn.execute(cases.update().where(cases.c.id == case_id, cases.c.queue == identity["queue"],
                cases.c.version == version, cases.c.status != "ENCERRADO").values(status="EM_REVISAO", version=version+1))
            if changed.rowcount != 1:
                raise Conflict("Caso alterado durante análise; atualize e tente novamente")
            conn.execute(reports.insert().values(id=report_id, case_id=case_id, snapshot_hash=digest(snapshot),
                content=content, created_at=now()))
            record(conn, identity["subject"], "report.created", case_id, report_id=report_id,
                   snapshot_hash=digest(snapshot), generation=generation, latency_ms=content["latency_ms"])
        return {"id": report_id, "case_id": case_id, "version": version+1, "content": content}

    @staticmethod
    def validate_proposal(proposal, retrieval):
        allowed = {d["id"] for d in retrieval["documents"]}
        if not set(proposal.procedimentos) <= allowed:
            raise ValueError("Referência documental inventada")
        if any(not set(h.evidencias) <= {"E1", "E2"} for h in proposal.hipoteses):
            raise ValueError("Referência factual inventada")

    @staticmethod
    def demo_proposal(snapshot, retrieval):
        event, summary = snapshot["event"], snapshot["summary"]
        if not summary["previous_count_24h"]:
            recommendation, hypothesis = "COLETAR_EVIDENCIAS", "Histórico insuficiente nesta projeção; não é possível contextualizar o alerta."
        elif any("BURST" in reason for reason in event["motivos"]):
            recommendation, hypothesis = "INVESTIGAR", "O código de burst sinaliza concentração que merece investigação; não confirma fraude."
        else:
            recommendation, hypothesis = "REVISAR_CONTEXTO", "Há movimentações anteriores disponíveis; compare o contexto para avaliar possível falso positivo."
        return Proposal(hipoteses=[{"texto": hypothesis, "evidencias": ["E1", "E2"]}],
            recomendacao=recommendation, limitacoes=["Modo demonstrativo por template, sem inferência de LLM."],
            procedimentos=[d["id"] for d in retrieval["documents"]])

    def review(self, case_id, request, identity):
        with self.engine.begin() as conn:
            case = self.get_case(conn, case_id, identity)
            report = conn.execute(select(reports).where(reports.c.id == request.report_id,
                reports.c.case_id == case_id)).mappings().first()
            latest = conn.execute(select(reports.c.id).where(reports.c.case_id == case_id)
                .order_by(reports.c.created_at.desc()).limit(1)).scalar_one_or_none()
            if not report or latest != request.report_id or report["snapshot_hash"] != digest(case["snapshot"]):
                raise Conflict("Parecer não corresponde ao snapshot atual")
            changed = conn.execute(cases.update().where(cases.c.id == case_id, cases.c.version == request.expected_version,
                cases.c.status == "EM_REVISAO").values(status="ENCERRADO", version=request.expected_version+1))
            if changed.rowcount != 1:
                raise Conflict("Caso alterado ou já encerrado")
            conn.execute(reviews.insert().values(id=uuid.uuid4().hex, case_id=case_id, report_id=request.report_id,
                subject=identity["subject"], outcome=request.outcome, rationale=request.rationale, created_at=now()))
            record(conn, identity["subject"], "case.reviewed", case_id, outcome=request.outcome, report_id=request.report_id)
        return {"status": "ENCERRADO", "version": request.expected_version+1}
