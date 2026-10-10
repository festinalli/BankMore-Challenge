"""Monta o estado enviado ao Jev.

O Jev não é calculadora: compara mal números e datas (documentação da TypeSafe,
"model jaggedness" do jev-1.13). Por isso o código traduz os números do Pix em
fatos categóricos ("chave cadastrada há menos de 7 dias") e o Jev só lê o
significado. Pelo mesmo motivo, e por minimização (LGPD, art. 6º, III), o campo
de valor vai em faixa, não exato. Valores que o cliente digitar no texto livre
seguem como estão.

O estado estruturado não tem CPF, nome nem chave Pix. No texto livre, o
mascaramento troca e-mail, @perfil, chave aleatória (EVP), CPF, CNPJ (inclusive
o alfanumérico), telefone, cartão, CEP e conta com dígito por marcadores. Nomes
próprios e números ou e-mails escritos por extenso NÃO são detectados.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

MAX_TEXTO = 280
_ENTRADA_MAX = MAX_TEXTO * 4  # corte antes das máscaras: o custo das regex fica limitado

_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]+(?:\.[\w-]+)+")
_PERFIL = re.compile(r"(?<![\w.])@[\w.]{2,30}")
_EVP = re.compile(r"\b[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}\b")
# CNPJ numérico ou alfanumérico (IN RFB 2.229/2024): 12 posições [0-9A-Z] e DV numérico.
_CNPJ = re.compile(r"\b[0-9A-Z]{2}\.?[0-9A-Z]{3}\.?[0-9A-Z]{3}/?[0-9A-Z]{4}-?\d{2}\b")
_CPF = re.compile(r"\b\d{3}[.,_/*\s-]?\d{3}[.,_/*\s-]?\d{3}[.,_/*\s-]?\d{2}\b")
_CONTA = re.compile(r"(?<![\d.])\d{3,12}-[\dxX]\b")  # 12345-6 (não pega o fim de um RG 12.345.678-9)
# Oito dígitos ou mais, com ou sem separadores: telefone, cartão, CEP, RG, conta sem dígito.
_NUMERO_LONGO = re.compile(r"\+?\(?\d(?:[\s().-]*\d){7,}")
# Traços que o NFKC não converte: hífen e hífen inseparável, figure dash, meia-risca, travessão, menos.
_TRACOS = re.compile(r"[‐-―−﹘﹣]")


def _cnpj(achado: re.Match) -> str:
    raiz = re.sub(r"[./-]", "", achado.group(0))[:12]
    # Exige dígitos na raiz, para não mascarar palavras em maiúsculas.
    return "[número]" if sum(c.isdigit() for c in raiz) >= 2 else achado.group(0)


# Ordem importa: os padrões mais específicos vêm antes do genérico.
_MASCARAS = (
    (_EMAIL, "[email]"),
    (_PERFIL, "[perfil]"),
    (_EVP, "[chave]"),
    (_CNPJ, _cnpj),
    (_CPF, "[número]"),
    (_CONTA, "[conta]"),
    (_NUMERO_LONGO, "[número]"),
)

_FAIXAS_ABSOLUTAS = (
    (Decimal("200"), "até R$ 200"),
    (Decimal("1000"), "de R$ 200 a R$ 1 mil"),
    (Decimal("5000"), "de R$ 1 mil a R$ 5 mil"),
    (Decimal("20000"), "de R$ 5 mil a R$ 20 mil"),
)


@dataclass(frozen=True)
class Pix:
    """Um Pix em análise, com as features que o BankMore já calcula."""

    valor: Decimal
    hora_local: int  # 0-23, America/Sao_Paulo (mesma regra do FraudeClient)
    tipo_iniciacao: str  # TipoIniciacao do domínio Pix: MANUAL, QRCODE_ESTATICO...
    count_tx_1h: int  # count_tx_cpf_1h do feature store
    valor_habitual: Decimal  # valor_p95_cpf_30d do feature store
    primeiro_pix_para_destino: bool
    chave_destino_idade_dias: int
    dispositivo_novo: bool
    motivo_informado: str = ""  # texto livre que o cliente digita ao pagar um destino novo
    historico: str = ""  # resumo do comportamento do cliente, gerado pelo banco
    valor_medio_24h: Decimal | None = None  # valor_medio_cpf_24h; só o XGBoost usa

    def __post_init__(self):
        if not 0 <= self.hora_local <= 23:
            raise ValueError("hora_local deve estar entre 0 e 23")
        if self.valor <= 0 or self.valor_habitual < 0:
            raise ValueError("valores devem ser positivos")
        if self.valor_medio_24h is not None and self.valor_medio_24h < 0:
            raise ValueError("valores devem ser positivos")
        if self.count_tx_1h < 0 or self.chave_destino_idade_dias < 0:
            raise ValueError("contagens não podem ser negativas")


def mascarar(texto: str) -> str:
    """Limpa o texto livre, troca dados pessoais por marcadores e limita o tamanho."""
    # Controle, formatação (inclui inversão bidi) e surrogate solto viram espaço;
    # NFKC transforma dígitos de largura total em ASCII, e os traços Unicode
    # viram hífen, para "98765–4321" não escapar da máscara.
    texto = texto[:_ENTRADA_MAX]
    texto = "".join(" " if unicodedata.category(c).startswith("C") else c for c in texto)
    texto = unicodedata.normalize("NFKC", texto)
    texto = _TRACOS.sub("-", texto).replace("·", ".")
    for padrao, marcador in _MASCARAS:
        texto = padrao.sub(marcador, texto)
    texto = " ".join(texto.split())
    return texto[:MAX_TEXTO]


def periodo(hora: int) -> str:
    if hora < 6:
        return "madrugada"
    if hora < 12:
        return "manhã"
    if hora < 18:
        return "tarde"
    return "noite"


def faixa_absoluta(valor: Decimal) -> str:
    for limite, rotulo in _FAIXAS_ABSOLUTAS:
        if valor <= limite:
            return rotulo
    return "acima de R$ 20 mil"


def faixa_de_valor(valor: Decimal, habitual: Decimal) -> str:
    if habitual <= 0:
        return "cliente sem histórico de valores"
    if valor <= habitual:
        return "dentro do habitual do cliente"
    if valor <= habitual * 3:
        return "acima do habitual do cliente"
    return "muito acima do habitual do cliente"


def idade_da_chave(dias: int) -> str:
    if dias < 7:
        return "cadastrada há menos de 7 dias"
    if dias < 90:
        return "cadastrada nos últimos 3 meses"
    return "cadastrada há mais de 3 meses"


def montar_estado(pix: Pix) -> dict:
    """Estado do Jev: fatos calculados pelo código e o texto do cliente, mascarado."""
    return {
        "pagamento": {
            "valor": faixa_absoluta(pix.valor),
            "valor_em_relacao_ao_cliente": faixa_de_valor(pix.valor, pix.valor_habitual),
            "periodo_do_dia": periodo(pix.hora_local),
            "iniciacao": pix.tipo_iniciacao,
            "destinatario": (
                "primeiro Pix deste cliente para este destinatário"
                if pix.primeiro_pix_para_destino
                else "destinatário que já recebeu Pix deste cliente"
            ),
            "chave_do_destinatario": idade_da_chave(pix.chave_destino_idade_dias),
            "dispositivo": "aparelho novo" if pix.dispositivo_novo else "aparelho habitual",
        },
        "motivo_informado_pelo_cliente": mascarar(pix.motivo_informado) or "(não informado)",
        "historico_do_cliente": mascarar(pix.historico) or "(sem histórico)",
    }
