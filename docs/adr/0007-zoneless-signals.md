# ADR 0007 — Angular zoneless + signals (não Zone.js)

- **Data:** 2026-05-16
- **Status:** Aceita
- **Decisores:** time backend (case)

## Contexto

Angular 21 mudou o default: bootstrap standalone não traz mais Zone.js automaticamente.
Componentes que usam propriedades simples (`this.saldo = 100`) ficam com DOM
**congelado** — change detection nunca dispara. Manifestou-se como bug real: HTTP
respondia 200 e `saldoAtual` ficava 511999 na state do componente, mas a UI seguia
em `R$ 0,00 / Carregando...` (validado via DevTools eval).

## Alternativas avaliadas

1. **Voltar pra Zone.js** (decisão original, revisada). Adicionar `npm i zone.js` +
   `polyfills: ["zone.js"]` + `provideZoneChangeDetection({ eventCoalescing: true })`.
   - Pró: 1 linha resolve. Não exige refator dos componentes.
   - Contra: +80kB no bundle. Monkey-patch de `Promise/setTimeout/addEventListener` polui
     globais. **Em descontinuação** pelo time Angular — débito imediato.

2. **Zoneless + Signals** (escolhida). `provideZonelessChangeDetection()` no
   `app.config.ts`; componentes usam `signal()` / `computed()` ao invés de
   propriedades; `(click)` handlers nativamente disparam change detection
   sob OnPush.
   - Pró: bundle menor, change detection previsível, roadmap oficial,
     templates passam a usar `()` (explícito).
   - Contra: refator dos 6 componentes (Login, Register, Dashboard, Transferência,
     Extrato, FraudeOps). `EventSource.onmessage` precisa setar signal
     (já não precisa de `NgZone.run()`).

3. **Zoneless sem signals** (`markForCheck()` manual). Pior dos mundos.

## Decisão

Adotar **Zoneless + Signals**. Todos os componentes refatorados:
- State (`isLoading`, `errorMessage`, `saldoAtual`, etc) → `signal<T>(initial)`.
- Derivados (lista filtrada, contadores) → `computed(() => …)`.
- `ChangeDetectionStrategy.OnPush` em todos os componentes standalone.
- ReactiveForms continuam via `FormBuilder` — `valueChanges` exposto como signal via `toSignal()` quando precisa reatividade (ex: `senhasDiferem` no Register).

## Consequências

- ✅ Bundle 80kB menor; código mais explícito sobre o que muda.
- ✅ FraudeOpsComponent não precisa mais `NgZone.run()` no `onmessage` do SSE
  — `signal.update()` dispara change detection direto.
- ⚠️ Code style: precisamos lembrar de `()` em templates (`{{ saldo() }}`).
  Compilador AOT pega `{{ saldo }}` sem chamada — vira erro de tipo.
- ❌ Bibliotecas third-party que dependem de Zone.js (algumas libs de animação)
  podem precisar adapt. Não temos nenhuma dependência assim hoje.

## Histórico

Decisão original (mesma sessão) foi adicionar Zone.js como fix rápido. **Revisada**
ainda na mesma sessão para o padrão oficial Angular 21. Lição: pressão de "fazer
funcionar agora" levou ao débito imediato; o user explicitamente pediu correção.
