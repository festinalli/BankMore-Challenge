# ADR 0022 — Jev como segunda camada do antifraude Pix

**Status:** Proposta (demonstração implementada em `jev/`, integração .NET pendente) · **Data:** 2026-10-10

## Contexto

O antifraude inline do Pix ([ADR 0018](0018-sprint9-antifraude-inline-pix.md)) chama o `fraud-ml` (XGBoost) com features numéricas: valor, hora, dia da semana, Pix na última hora e valores habituais. Ele detecta bem anomalias de número, como valor alto de madrugada ou rajada de pagamentos.

Golpes de engenharia social são outra história: falso parente, falsa central de segurança, falso vendedor. Nesses golpes, quem paga é o dono da conta, no aparelho de sempre, e o valor e o horário costumam ser normais. Com as features atuais, o XGBoost tem pouco a dizer sobre eles.

Parte do sinal está no destinatário: primeiro Pix para ele, chave recém-criada, marcações de fraude do DICT, que a Res. BCB 403/2024 manda usar. Essa parte deve virar feature tabular. O resto do sinal está no contexto do pagamento, e não cabe num número.

## Decisão

Adicionar o Jev (TypeSafe AI) como **segunda camada** do antifraude Pix. O Jev é um modelo de decisão que devolve escolhas tipadas com probabilidade e confiança.

1. **O código monta o estado.** Os números viram fatos, como "chave cadastrada há menos de 7 dias" ou "valor acima do habitual", e até o valor vai em faixa. O motivo: segundo a própria TypeSafe, o Jev compara mal números e datas.
   - Não entram CPF, nome nem chave Pix.
   - O texto livre passa por mascaramento: e-mail, @perfil, chave aleatória (EVP), CPF, CNPJ (inclusive o alfanumérico), telefone, cartão, CEP e conta. Depois disso, ele é limitado a 280 caracteres.
   - Nomes próprios e valores digitados no texto livre não são mascarados.
2. **Uma chamada, três perguntas:** tipo de golpe (Choice, com confiança, incluindo `outro_golpe`), pressão de terceiro (Noul) e pagamento instruído por terceiro (Noul).
3. **A política fica no código** (`jev/bankmore_jev/policy.py`):
   - Score do XGBoost ≥ 0,95: RECUSAR, como hoje.
   - Golpe com confiança ≥ 0,85: RETER PARA ANÁLISE. O BankMore, como PSP do pagador, segura o Pix antes de enviar o pacs.008 ao SPI e aciona análise humana. Não confundir com o bloqueio cautelar da Res. BCB 147/2021, que é do PSP recebedor.
   - Golpe com confiança entre 0,6 e 0,85 e sinal de terceiro ≥ 0,8: também RETER. Confirmar com o cliente é um controle fraco quando o golpista orienta a vítima.
   - Golpe com confiança entre 0,6 e 0,85 sem sinal, sinal sem golpe ou confiança < 0,6: CONFIRMAR COM CLIENTE.
4. **O Jev só aumenta a cautela.** A decisão final é a mais restritiva entre a do XGBoost e a do Jev. O texto lido pelo Jev pode ter sido ditado pelo golpista, e conteúdo manipulado pode mudar a resposta.
5. **Fail-open, como o ADR 0004.** Vale só a decisão do XGBoost quando:
   - há erro de rede ou HTTP;
   - o prazo total de 2 s estoura;
   - a resposta vem fora do contrato.

   Uma resposta parcial é aproveitada no que veio. O fail-open tem a mesma contrapartida do ADR 0004:
   - log de aviso e contador `jev_failures_total{reason=timeout|rede|http_401|http_429|http_4xx|http_5xx|contrato}`;
   - alerta P1 quando a taxa passar de 1% em 5 min.

   Além disso, entra um circuit breaker com meia-abertura, que o ADR 0004 não tem.

   Também entra uma cota por cliente para a chamada ao Jev, para que o volume de um cliente não esgote o rate limit do banco e desligue a camada para todos.
6. **Versão fixa do modelo** (`jev-1.13.0`, não `jev-latest`). A versão é gravada junto com a decisão, como `ModeloVersao` no ADR 0018. Trocar de versão exige recalibrar os limiares.

### Integração prevista no `PixLiquidacaoService`

Chamar o Jev em paralelo com o `fraud-ml`, dentro do orçamento de 2 s do ADR 0018. O prazo é total: usar um `CancellationToken` com timeout, e não só o timeout de socket.

```csharp
var xgbTask = _fraude.Avaliar(cpfOrigem, valor, "PIX", countRecente, ct);
var jevTask = _jev.Avaliar(EstadoJev.De(pgto, contexto), ct);   // fail-open: null em falha
await Task.WhenAll(xgbTask, jevTask);

var decisao = PoliticaAntifraude.Decidir(xgbTask.Result, jevTask.Result);
// RECUSAR → REJEITADO; RETER → novo status RETIDO_ANALISE; CONFIRMAR → novo status AGUARDANDO_CONFIRMACAO
```

A integração exige:

- dois novos estados em `StatusPagamento`;
- a tela de confirmação no app;
- dados que o fluxo ainda não tem:
  - a data de criação da chave no DICT (o `DictResolucao` atual não devolve);
  - o histórico de Pix para o destino;
  - a identificação de aparelho novo;
  - um campo de motivo na API.

Ficam pendentes também três pontos:

- o prazo máximo da retenção e o desfecho padrão quando ele estoura;
- a notificação de infração no DICT quando a análise confirmar fraude;
- a base regulatória da retenção pelo PSP pagador.

Tudo isso fica para uma sprint própria. Este ADR entrega a política, o contrato e a demonstração.

## Consequências

- ✅ Cobre parte do que as features numéricas não veem: golpes com valor e horário normais.
- ✅ Política testável e auditável em código; o modelo só classifica.
- ✅ Nenhuma decisão do XGBoost é afrouxada. Se o texto for manipulado, o pior caso é deixar de acrescentar cautela, nunca liberar o que foi barrado.
- ⚠ Mais uma chamada de rede no caminho do Pix. A TypeSafe informa 70 a 500 ms ponta a ponta, medidos a partir da Costa Oeste dos EUA, onde o serviço está hospedado ([post de lançamento](https://typesafe.ai/blog/introducing-system-one-models-and-jev)). Medir a partir do Brasil.
- ⚠ Dado do cliente vai para um terceiro no exterior. Antes de produção é preciso cobrir:
  - contrato de operador e transferência internacional (LGPD);
  - sigilo bancário (LC 105/2001);
  - os requisitos da Res. CMN 4.893/2021 para processamento de dados por terceiro no exterior;
  - anonimização de nomes, que a demonstração não faz.
- ⚠ O "motivo informado" supõe que o app pergunte o motivo ao pagar um destino novo. O Pix só tem o campo de mensagem ao recebedor.
- ⚠ É preciso calibrar com Pix rotulados:
  - os limiares;
  - as instruções, que estão em inglês com estado em português (o português é tratado "não igualmente bem");
  - o viés do Jev pela primeira opção da Choice.

  Os cenários da demonstração são sintéticos e não medem eficácia.
- ⚠ O Jev está em acesso antecipado. A dependência de fornecedor exige plano de saída; o `JevClient` isola o contrato.
