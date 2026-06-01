# ADR 0002 — CQRS + MediatR

- **Data:** 2026-05-10
- **Status:** Aceita

## Contexto

Controllers acumulavam lógica de aplicação misturada com HTTP. Difícil testar
sem subir Kestrel; difícil reuse entre Api e Worker.

## Decisão

**CQRS-light via MediatR**: cada operação é um `Command` ou `Query` (record)
+ um `Handler` (`IRequestHandler<TIn, TOut>`). Controllers ficam thin:

```csharp
[HttpPost("criar")]
public Task<IActionResult> Cadastrar([FromBody] CadastrarContaCommand cmd)
    => Ok(await mediator.Send(cmd));
```

## Estrutura

```
Application/
  Handlers/
    CadastrarContaHandler.cs         ← record CadastrarContaCommand + class Handler
    LoginHandler.cs
    ObterSaldoHandler.cs
    ObterExtratoHandler.cs
    EfetuarMovimentacaoHandler.cs
  Services/
    IPasswordHasher.cs                ← interface
    PasswordHasher.cs                 ← PBKDF2 (ver ADR-0008)
    CpfValidator.cs                   ← validador estático
```

## Consequências

- ✅ Cada handler é unit-testável com mock do repository (`IContaCorrenteRepository`).
- ✅ Worker e Api compartilham handlers (DI registration igual).
- ✅ Cross-cutting (logging, validation) vira `IPipelineBehavior<,>` do MediatR.
- ⚠️ MediatR cobra licença comercial pra orgs > 1M USD revenue (mudança em 2024).
  Pra produção real considerar `Mediator` (Martin Othamar) ou implementação
  in-house de 20 linhas (basicamente `IServiceProvider.GetService<Handler>`).
- ⚠️ Não é "CQRS puro" (sem read store separado nem event sourcing) — é
  separação Command/Query no application layer, que é suficiente pro escopo.
