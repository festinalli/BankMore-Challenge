"""Cliente HTTP mínimo da API do Jev, só com a biblioteca padrão.

Contrato (docs.typesafe.ai/api): POST /v1/systemone com `Authorization: Bearer`,
corpo {model, state, questions}; resposta {model, answers, usage}. Choice traz
choice, probabilities e confidence; Noul traz noul, a probabilidade do "sim".

Cuidados:
- a chave vem de TYPESAFE_API_KEY e não aparece em mensagens de erro nem em repr;
- redirects são recusados, para o Authorization nunca seguir para outro host;
- o prazo é TOTAL: o timeout do urllib vale por operação de socket, então a
  chamada roda numa thread daemon e o cliente desiste quando o prazo acaba
  (uma chamada lenta não segura as próximas nem o fim do processo);
- qualquer falha vira JevError, e quem chama decide o fallback (fail-open).
"""
from __future__ import annotations

import json
import math
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

API_URL = "https://api.typesafe.ai/v1/systemone"
# Versão fixa: o alias "jev-latest" anda a cada release, e a confiança muda junto,
# mexendo no efeito dos limiares da política. Troque só depois de recalibrar.
DEFAULT_MODEL = "jev-1.13.0"
PRAZO_MAXIMO_S = 30.0
_DETALHE_MAX = 200
_JANELA_DE_ERRO = 65536

# (url, headers, corpo, timeout) -> (status HTTP, corpo da resposta)
Transport = Callable[[str, dict, bytes, float], tuple[int, bytes]]


class JevError(Exception):
    """O Jev não respondeu algo utilizável. Quem chama decide o fallback."""


@dataclass(frozen=True)
class ChoiceAnswer:
    choice: str
    confidence: float
    probabilities: dict


@dataclass(frozen=True)
class JevResult:
    choices: dict  # id da pergunta -> ChoiceAnswer
    nouls: dict  # id da pergunta -> probabilidade do "sim"
    model: str
    latency_ms: float


class _SemRedirect(urllib.request.HTTPRedirectHandler):
    """Um redirect reenviaria o Authorization para outro host: vira erro HTTP."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _Segredo(str):
    """Valor de header com repr mascarado, para não aparecer em tracebacks com variáveis locais."""

    def __repr__(self) -> str:
        return "'***'"


_OPENER = urllib.request.build_opener(_SemRedirect)


class _PrazoEsgotado(Exception):
    pass


def _com_prazo(funcao: Callable, prazo_s: float, *args):
    """Roda `funcao` numa thread daemon e desiste dela quando o prazo acaba."""
    caixa: queue.Queue = queue.Queue(maxsize=1)

    def alvo():
        try:
            caixa.put((True, funcao(*args)))
        except BaseException as erro:  # devolvido a quem chama, que converte em JevError
            caixa.put((False, erro))

    threading.Thread(target=alvo, name="jev", daemon=True).start()
    try:
        ok, valor = caixa.get(timeout=prazo_s)
    except queue.Empty:
        raise _PrazoEsgotado from None
    if ok:
        return valor
    raise valor


def urllib_transport(url: str, headers: dict, body: bytes, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


class JevClient:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        url: str = API_URL,
        timeout_s: float = 2.0,
        transport: Transport = urllib_transport,
        clock: Callable[[], float] = time.perf_counter,
    ):
        api_key = (api_key or "").strip()
        if not api_key or not api_key.isascii() or not api_key.isprintable() or " " in api_key:
            raise ValueError("TYPESAFE_API_KEY vazia ou com caracteres inválidos")
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ValueError("A URL do Jev precisa ser https")
        if not (math.isfinite(timeout_s) and 0 < timeout_s <= PRAZO_MAXIMO_S):
            raise ValueError(f"O prazo do Jev precisa estar entre 0 e {PRAZO_MAXIMO_S:g} s")
        self._api_key = api_key
        self._model = model
        self._url = url
        self._timeout_s = timeout_s
        self._transport = transport
        self._clock = clock

    def __repr__(self) -> str:
        return f"JevClient(model={self._model!r}, url={self._url!r}, api_key='***')"

    def ask(self, state: dict, questions: dict) -> JevResult:
        try:
            body = json.dumps(
                {"model": self._model, "state": state, "questions": questions},
                ensure_ascii=False,
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError):
            raise JevError("Estado ou perguntas não serializáveis") from None
        headers = {
            "Authorization": _Segredo(f"Bearer {self._api_key}"),
            "Content-Type": "application/json",
        }

        start = self._clock()
        try:
            status, raw = _com_prazo(self._transport, self._timeout_s, self._url, headers, body, self._timeout_s)
        except _PrazoEsgotado:
            raise JevError(f"Jev não respondeu em {self._timeout_s:g} s") from None
        except Exception as error:  # DNS, conexão recusada ou cortada, protocolo, transporte quebrado
            raise JevError(f"Jev inacessível ({type(error).__name__})") from None
        latency_ms = (self._clock() - start) * 1000

        if status != 200:
            raise JevError(f"Jev respondeu HTTP {status}: {self._detalhe(status, raw)}")
        return parse_response(raw, latency_ms)

    def _detalhe(self, status: int, raw: bytes) -> str:
        """Começo do corpo do erro (a API diz qual campo falhou num 422), sem a chave."""
        if status in (401, 403):
            return "(corpo omitido)"  # erro de autenticação: nada a diagnosticar no corpo
        texto = raw[:_JANELA_DE_ERRO].decode("utf-8", "replace")
        for forma in (self._api_key, self._api_key.replace("/", "\\/")):
            texto = texto.replace(forma, "***")  # antes de cortar, para não sobrar pedaço da chave
        texto = "".join(c if c.isprintable() else " " for c in texto)
        return " ".join(texto.split())[:_DETALHE_MAX] or "(sem corpo)"


def parse_response(raw: bytes, latency_ms: float) -> JevResult:
    try:
        data = json.loads(raw)
        choices, nouls = {}, {}
        for question_id, answer in data["answers"].items():
            if answer["type"] == "choice":
                choice = answer["choice"]
                if not isinstance(choice, str):
                    raise TypeError("choice não é texto")
                choices[question_id] = ChoiceAnswer(
                    choice=choice,
                    confidence=_probability(answer["confidence"]),
                    probabilities=_probabilities(answer.get("probabilities")),
                )
            elif answer["type"] == "noul":
                nouls[question_id] = _probability(answer["noul"])
        return JevResult(choices=choices, nouls=nouls, model=str(data.get("model", "")), latency_ms=latency_ms)
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, RecursionError):
        raise JevError("Resposta do Jev fora do contrato") from None


def _probability(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("probabilidade não numérica")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError("probabilidade fora de [0, 1]")
    return number


def _probabilities(values) -> dict:
    """Só informativas (a política não usa): entradas inválidas são descartadas."""
    if not isinstance(values, dict):
        return {}
    validas = {}
    for opcao, valor in values.items():
        try:
            validas[str(opcao)] = _probability(valor)
        except (TypeError, ValueError, OverflowError):
            continue
    return validas
