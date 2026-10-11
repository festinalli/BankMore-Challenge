"""API HTTP local da tela do Jev no BankMore (frontend: /ops/jev).

Só biblioteca padrão, no mesmo padrão do módulo investigation/: o Angular chama
esta API direto do navegador. Cuidados, porque a chave do Jev está no processo:
- escuta só em 127.0.0.1;
- CORS só para as origens de JEV_ORIGINS (padrão: o ng serve em :4200);
- confere o Host (contra DNS rebinding) e exige JSON no POST, para uma página de
  outro site não conseguir disparar chamadas ao Jev com a sua chave;
- limita o tamanho do corpo e nunca devolve a chave nem detalhes de erro interno.
"""
from __future__ import annotations

import json
import logging
import math
import os
import sys
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .client import DEFAULT_MODEL, JevClient, urllib_transport
from .demo import (
    ConfiguracaoInvalida,
    avaliar_pix,
    carregar_cenarios,
    criar_cliente,
    pix_do_cenario,
    resposta_offline,
    score_do_fraud_ml,
)
from .questions import perguntas
from .state import Pix

PORTA_PADRAO = 5011
ORIGENS_PADRAO = "http://localhost:4200,http://127.0.0.1:4200"
CORPO_MAXIMO = 16 * 1024
TEXTO_MAXIMO = 2000

log = logging.getLogger("bankmore_jev")


class ErroDeEntrada(ValueError):
    """Pedido inválido: a mensagem vai para a tela."""


class Aplicacao:
    """O que a tela pode fazer: ver o status, listar cenários e avaliar um Pix."""

    def __init__(self, cliente: JevClient | None, *, ml_url: str | None = None, nenhum_primeiro: bool = False, modelo: str = DEFAULT_MODEL):
        self.cliente = cliente
        self.ml_url = ml_url
        self.nenhum_primeiro = nenhum_primeiro
        self.modelo = modelo
        self.questions = perguntas(nenhum_primeiro=nenhum_primeiro)
        self.cenarios = {c["id"]: c for c in carregar_cenarios()}

    def status(self) -> dict:
        return {
            "modo": "simulado" if self.cliente is None else "ao_vivo",
            "modelo": "simulado" if self.cliente is None else self.modelo,
            "xgboost": f"fraud-ml em {self.ml_url}" if self.ml_url else "score de exemplo",
            "ordem_das_opcoes": "nenhum primeiro" if self.nenhum_primeiro else "golpes primeiro",
        }

    def listar(self) -> list[dict]:
        return [
            {
                "id": c["id"],
                "titulo": c["titulo"],
                "categoria": c["categoria"],
                "score_xgboost_exemplo": c["score_xgboost_exemplo"],
                "pix": _pix_para_tela(pix_do_cenario(c)),
            }
            for c in self.cenarios.values()
        ]

    def avaliar(self, corpo: dict) -> dict:
        if not isinstance(corpo, dict):
            raise ErroDeEntrada("O corpo deve ser um objeto JSON.")
        if "cenario_id" in corpo:
            return self._avaliar_cenario(corpo["cenario_id"])
        if "pix" in corpo:
            return self._avaliar_personalizado(corpo["pix"], corpo.get("score_xgboost"))
        raise ErroDeEntrada("Informe cenario_id ou pix.")

    def _avaliar_cenario(self, cenario_id) -> dict:
        if isinstance(cenario_id, bool) or not isinstance(cenario_id, int) or cenario_id not in self.cenarios:
            raise ErroDeEntrada("Cenário inexistente.")
        cenario = self.cenarios[cenario_id]
        pix = pix_do_cenario(cenario)
        if self.ml_url:
            score, fonte = score_do_fraud_ml(self.ml_url, pix), "fraud-ml"
        else:
            score, fonte = cenario["score_xgboost_exemplo"], "exemplo"
        simulada = resposta_offline(cenario) if self.cliente is None else None
        avaliacao = avaliar_pix(pix, score, self.cliente, self.questions, simulada=simulada, rotulo_log=f"cenário {cenario_id}")
        return {
            "cenario": {"id": cenario["id"], "titulo": cenario["titulo"], "categoria": cenario["categoria"]},
            "pix": _pix_para_tela(pix),
            "fonte_score": fonte,
            "simulado": self.cliente is None,
            **avaliacao,
        }

    def _avaliar_personalizado(self, dados, score_informado) -> dict:
        pix = _pix_personalizado(dados)
        if self.ml_url:
            score, fonte = score_do_fraud_ml(self.ml_url, pix), "fraud-ml"
        elif score_informado is None:
            score, fonte = None, "nenhum"
        else:
            score, fonte = _numero(score_informado, "score_xgboost", 0, 1), "informado"
        avaliacao = avaliar_pix(pix, score, self.cliente, self.questions, rotulo_log="Pix personalizado")
        return {
            "cenario": None,
            "pix": _pix_para_tela(pix),
            "fonte_score": fonte,
            "simulado": self.cliente is None,
            **avaliacao,
        }


def _pix_para_tela(pix: Pix) -> dict:
    """Os dados do Pix como o banco os vê (ficam na tela; não vão para o Jev)."""
    return {
        "valor": str(pix.valor),
        "hora_local": pix.hora_local,
        "tipo_iniciacao": pix.tipo_iniciacao,
        "count_tx_1h": pix.count_tx_1h,
        "valor_habitual": str(pix.valor_habitual),
        "primeiro_pix_para_destino": pix.primeiro_pix_para_destino,
        "chave_destino_idade_dias": pix.chave_destino_idade_dias,
        "dispositivo_novo": pix.dispositivo_novo,
        "motivo_informado": pix.motivo_informado,
        "historico": pix.historico,
    }


def _numero(valor, nome: str, minimo: float, maximo: float, *, inteiro: bool = False):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or (inteiro and not isinstance(valor, int)):
        raise ErroDeEntrada(f"{nome} deve ser {'um inteiro' if inteiro else 'um número'}.")
    # Inteiro do JSON pode ter centenas de dígitos: compara sem converter para float.
    dentro = minimo <= valor <= maximo if isinstance(valor, int) else math.isfinite(valor) and minimo <= valor <= maximo
    if not dentro:
        raise ErroDeEntrada(f"{nome} deve estar entre {minimo:g} e {maximo:g}.")
    return valor


def _decimal(valor, nome: str, minimo: Decimal, maximo: Decimal) -> Decimal:
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
        raise ErroDeEntrada(f"{nome} deve ser um número.")
    try:
        numero = Decimal(str(valor).strip().replace(",", "."))
    except InvalidOperation:
        raise ErroDeEntrada(f"{nome} deve ser um número.") from None
    if not numero.is_finite() or not minimo <= numero <= maximo:
        raise ErroDeEntrada(f"{nome} deve estar entre {minimo} e {maximo}.")
    return numero.quantize(Decimal("0.01"))


def _texto(valor, nome: str) -> str:
    if valor is None:
        return ""
    if not isinstance(valor, str):
        raise ErroDeEntrada(f"{nome} deve ser texto.")
    if len(valor) > TEXTO_MAXIMO:
        raise ErroDeEntrada(f"{nome} deve ter até {TEXTO_MAXIMO} caracteres.")
    if any(0xD800 <= ord(c) <= 0xDFFF for c in valor):  # surrogate solto: recusa antes de chamar o Jev
        raise ErroDeEntrada(f"{nome} tem caracteres inválidos.")
    return valor


def _booleano(valor, nome: str) -> bool:
    if not isinstance(valor, bool):
        raise ErroDeEntrada(f"{nome} deve ser verdadeiro ou falso.")
    return valor


def _pix_personalizado(dados) -> Pix:
    if not isinstance(dados, dict):
        raise ErroDeEntrada("pix deve ser um objeto.")
    try:
        return Pix(
            valor=_decimal(dados.get("valor"), "valor", Decimal("0.01"), Decimal("10000000")),
            hora_local=_numero(dados.get("hora_local"), "hora_local", 0, 23, inteiro=True),
            tipo_iniciacao="MANUAL",
            count_tx_1h=_numero(dados.get("count_tx_1h", 0), "count_tx_1h", 0, 1000, inteiro=True),
            valor_habitual=_decimal(dados.get("valor_habitual", 0), "valor_habitual", Decimal("0"), Decimal("10000000")),
            primeiro_pix_para_destino=_booleano(dados.get("primeiro_pix_para_destino"), "primeiro_pix_para_destino"),
            chave_destino_idade_dias=_numero(dados.get("chave_destino_idade_dias"), "chave_destino_idade_dias", 0, 36500, inteiro=True),
            dispositivo_novo=_booleano(dados.get("dispositivo_novo", False), "dispositivo_novo"),
            motivo_informado=_texto(dados.get("motivo_informado"), "motivo_informado"),
            historico=_texto(dados.get("historico"), "historico"),
        )
    except ErroDeEntrada:
        raise
    except ValueError as falha:  # validação do próprio Pix
        raise ErroDeEntrada(str(falha)) from None


class _Atendente(BaseHTTPRequestHandler):
    server: "ServidorJev"
    server_version = "BankMoreJev"
    sys_version = ""

    def do_OPTIONS(self):
        if not self._host_valido() or not self._origem_permitida():
            return self._json(403, {"erro": "Origem não permitida."})
        self.send_response(204)
        self._cabecalhos_cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._pode_atender():
            return
        rotas = {"/api/status": self.server.app.status, "/api/cenarios": self.server.app.listar}
        if self.path not in rotas:
            return self._json(404, {"erro": "Rota inexistente."})
        self._json(200, rotas[self.path]())

    def do_POST(self):
        if not self._pode_atender():
            return
        if self.path != "/api/avaliar":
            return self._json(404, {"erro": "Rota inexistente."})
        if self.headers.get_content_type() != "application/json":
            return self._json(415, {"erro": "Envie JSON (Content-Type: application/json)."})
        try:
            tamanho = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._json(411, {"erro": "Informe o Content-Length."})
        if not 0 < tamanho <= CORPO_MAXIMO:
            return self._json(413, {"erro": f"O corpo deve ter até {CORPO_MAXIMO} bytes."})
        try:
            corpo = json.loads(self.rfile.read(tamanho))
        except (ValueError, RecursionError):
            return self._json(400, {"erro": "JSON inválido."})
        try:
            self._json(200, self.server.app.avaliar(corpo))
        except ErroDeEntrada as falha:
            self._json(400, {"erro": str(falha)})
        except Exception:
            log.exception("Falha interna ao avaliar o Pix")
            self._json(500, {"erro": "Falha interna. Veja o terminal da API."})

    def _pode_atender(self) -> bool:
        if not self._host_valido():
            self._json(421, {"erro": "Host não permitido."})
            return False
        if "Origin" in self.headers and not self._origem_permitida():
            self._json(403, {"erro": "Origem não permitida."})
            return False
        return True

    def _host_valido(self) -> bool:
        porta = self.server.server_address[1]
        return self.headers.get("Host", "") in {f"127.0.0.1:{porta}", f"localhost:{porta}"}

    def _origem_permitida(self) -> bool:
        return self.headers.get("Origin", "") in self.server.origens

    def _cabecalhos_cors(self):
        origem = self.headers.get("Origin", "")
        if origem in self.server.origens:
            self.send_header("Access-Control-Allow-Origin", origem)
            self.send_header("Vary", "Origin")

    def _json(self, status: int, dados) -> None:
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cabecalhos_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, formato, *args):
        log.info("%s %s", self.address_string(), formato % args)


class ServidorJev(ThreadingHTTPServer):
    daemon_threads = True
    # No Windows, SO_REUSEADDR deixa uma segunda API abrir a mesma porta sem erro, e a
    # tela continua falando com a antiga. Sem ele, a segunda falha e avisa.
    allow_reuse_address = os.name != "nt"

    def __init__(self, app: Aplicacao, porta: int = PORTA_PADRAO, origens: str = ORIGENS_PADRAO):
        self.app = app
        self.origens = {o.strip() for o in origens.split(",") if o.strip()}
        super().__init__(("127.0.0.1", porta), _Atendente)


def servir(args, env=os.environ, transport=urllib_transport, err=None) -> int:
    """`python -m bankmore_jev --api`: sobe a API para a tela /ops/jev do frontend."""
    err = err or sys.stderr
    cliente = None
    if not args.offline:
        try:
            cliente = criar_cliente(env, transport)
        except ConfiguracaoInvalida as falha:
            print(str(falha), file=err)
            return 2
    app = Aplicacao(
        cliente,
        ml_url=args.ml_url,
        nenhum_primeiro=getattr(args, "nenhum_primeiro", False),
        modelo=env.get("TYPESAFE_MODEL") or DEFAULT_MODEL,
    )
    try:
        servidor = ServidorJev(app, args.porta, env.get("JEV_ORIGINS") or ORIGENS_PADRAO)
    except (OSError, OverflowError) as falha:
        detalhe = getattr(falha, "strerror", None) or falha
        print(f"Não foi possível abrir a porta {args.porta} (já está em uso por outra API?): {detalhe}", file=err)
        return 2
    modo = "respostas SIMULADAS (--offline)" if cliente is None else f"Jev ao vivo ({app.modelo})"
    print(f"API do Jev em http://127.0.0.1:{servidor.server_address[1]} · {modo}", file=err)
    print("Tela: suba o frontend (cd frontend; npm start) e abra http://localhost:4200/ops/jev", file=err)
    print("Ctrl+C para parar.", file=err)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
    return 0
