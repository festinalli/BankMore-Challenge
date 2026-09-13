"""Three repeatable synthetic scenarios; never writes to banking tables."""
from datetime import datetime, timedelta, timezone


def seed(service):
    at = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)

    def event(tx, cpf, amount, when, reasons=None, score=0.96):
        rejected = bool(reasons and any("BURST" in r for r in reasons))
        return {"id": tx, "cpfOrigem": cpf, "valor": str(amount), "tipo": "TED",
                "timestamp": when.isoformat(), "decididoEm": when.isoformat(),
                "decisao": "REJEITADA" if rejected else "APROVADA", "motivos": reasons or [],
                "scoreFraude": score, "modeloVersao": "synthetic-fixture-v1"}

    for index in range(3):
        service.ingest(event(f"demo-burst-history-{index}", "00000000001", 900,
            at-timedelta(seconds=50-index*10)), "transferencia.aprovada", synthetic=True)
    burst = service.ingest(event("demo-suspeita", "00000000001", 900, at, ["BURST_4_EM_60s"]),
        "transferencia.rejeitada", synthetic=True)
    for index in range(5):
        service.ingest(event(f"demo-context-history-{index}", "00000000002", 15000,
            at-timedelta(hours=index+1)), "transferencia.aprovada", synthetic=True)
    context = service.ingest(event("demo-contexto-legitimo", "00000000002", 15000, at, [], 0.83),
        "fraude.alerta", synthetic=True)
    missing = service.ingest(event("demo-inconclusivo", "00000000003", 20000, at, [], None),
        "fraude.alerta", synthetic=True)
    return {"suspeita": burst, "contexto": context, "inconclusivo": missing}
