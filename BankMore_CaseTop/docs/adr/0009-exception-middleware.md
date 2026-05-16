# ADR 0009 — Global exception middleware nas APIs .NET

- **Data:** 2026-05-16
- **Status:** Aceita

## Contexto

Controllers tinham `try/catch` repetitivo em cada action mapeando exceções de
domínio pra `BadRequest`/`Conflict`/`InternalServerError`:

```csharp
try { var r = await mediator.Send(command); return Ok(r); }
catch (ArgumentException ex) { return BadRequest(new { mensagem = ex.Message }); }
catch (InvalidOperationException ex) { return Conflict(new { mensagem = ex.Message }); }
catch (Exception ex) { logger.LogError(ex, "..."); return StatusCode(500, ...); }
```

Anti-pattern:
- **Cross-cutting concern** (tratamento de erro) misturado com lógica de orquestração.
- Catch genérico `Exception` engole tudo — esconde bugs.
- Payload de erro inconsistente entre actions.
- Difícil adicionar contexto (correlationId, código semântico).

## Decisão

`ExceptionMiddleware` global em [`ContaCorrente.Api/Middleware/`](../../src/BankMore.ContaCorrente.Api/Middleware/ExceptionMiddleware.cs)
e [`Transferencia.Api/Middleware/`](../../src/BankMore.Transferencia.Api/Middleware/ExceptionMiddleware.cs).

Mapeamento canônico:

| Exception | HTTP | Código |
|---|---|---|
| `ArgumentException` | 400 | `VALIDACAO` |
| `InvalidOperationException` | 409 | `ESTADO_INVALIDO` |
| `UnauthorizedAccessException` | 401 | `NAO_AUTORIZADO` |
| `KeyNotFoundException` | 404 | `NAO_ENCONTRADO` |
| Outras | 500 | `ERRO_INTERNO` (log estruturado) |

Payload padronizado:

```json
{
  "mensagem": "CPF inválido",
  "codigo": "VALIDACAO",
  "correlationId": "0HNLJEV7RHRCE:00000001"
}
```

## Consequências

- ✅ Controllers focam em orquestrar (`return Ok(await mediator.Send(command));`).
- ✅ Cliente recebe payload uniforme com `codigo` semântico (fácil de tratar no front).
- ✅ `correlationId` em todo erro — `grep` único nos logs encontra o trace inteiro.
- ✅ Logger só dispara em 5xx (não polui em validation errors).
- ⚠️ Exceções de domínio (`InvalidOperationException`) carregam mensagem em
  português — OK por enquanto, no futuro: enum `CodigoErro` + i18n por header.
