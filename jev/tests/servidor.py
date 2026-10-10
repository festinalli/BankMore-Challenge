"""Servidor HTTP local que devolve bytes crus, para testar o transporte real sem rede externa."""
from __future__ import annotations

import json
import socketserver
import threading
import time


def resposta_http(status: str, corpo: bytes = b"", cabecalhos: dict | None = None) -> bytes:
    linhas = [f"HTTP/1.1 {status}", f"Content-Length: {len(corpo)}", "Connection: close"]
    linhas += [f"{nome}: {valor}" for nome, valor in (cabecalhos or {}).items()]
    return ("\r\n".join(linhas) + "\r\n\r\n").encode() + corpo


def resposta_json(dados) -> bytes:
    return resposta_http("200 OK", json.dumps(dados).encode(), {"Content-Type": "application/json"})


class Requisicao:
    def __init__(self, bruto: bytes):
        cabecalho, _, self.corpo = bruto.partition(b"\r\n\r\n")
        linhas = cabecalho.decode("latin-1").split("\r\n")
        self.linha = linhas[0]
        self.cabecalhos = {}
        for linha in linhas[1:]:
            nome, _, valor = linha.partition(":")
            self.cabecalhos[nome.strip().lower()] = valor.strip()

    def json(self):
        return json.loads(self.corpo)


class ServidorCru(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, resposta: bytes, intervalo_s: float = 0.0):
        self.resposta = resposta
        self.intervalo_s = intervalo_s  # > 0: manda um byte por vez, devagar
        self.requisicoes: list[Requisicao] = []
        self.parar = threading.Event()
        super().__init__(("127.0.0.1", 0), _Atendente)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.parar.set()
        self.shutdown()
        self.server_close()


class _Atendente(socketserver.BaseRequestHandler):
    def handle(self):
        servidor: ServidorCru = self.server
        try:
            servidor.requisicoes.append(Requisicao(_ler(self.request)))
            if not servidor.intervalo_s:
                self.request.sendall(servidor.resposta)
                return
            for byte in servidor.resposta:
                if servidor.parar.is_set():
                    return
                self.request.sendall(bytes([byte]))
                time.sleep(servidor.intervalo_s)
        except OSError:
            pass  # o cliente desistiu e fechou a conexão


def _ler(sock) -> bytes:
    dados = b""
    while b"\r\n\r\n" not in dados:
        parte = sock.recv(65536)
        if not parte:
            return dados
        dados += parte
    cabecalho, _, corpo = dados.partition(b"\r\n\r\n")
    tamanho = 0
    for linha in cabecalho.split(b"\r\n"):
        if linha.lower().startswith(b"content-length:"):
            tamanho = int(linha.split(b":", 1)[1])
    while len(corpo) < tamanho:
        parte = sock.recv(65536)
        if not parte:
            break
        corpo += parte
    return cabecalho + b"\r\n\r\n" + corpo
