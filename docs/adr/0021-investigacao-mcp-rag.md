# ADR 0021 — Investigação de fraude com MCP e RAG

Status: implementado como MVP local; conector Kafka/PostgreSQL/API validado em containers isolados.
Fluxo completo da stack bancária (.NET/PyFlink/PIX) permanece fora dessa validação.

## Contexto

O detector existente emite decisões e alertas. A operação precisa reunir evidências,
consultar procedimentos e registrar o desfecho. Eventos não contêm todas as features
do scoring; consultas tardias ao Redis não reconstruiriam o contexto original.

## Decisão

Adicionar serviço Python em `investigation/`, banco próprio e consumidor Kafka de saída
do PyFlink. A geração é solicitada pelo painel/MCP; a ingestão não depende do LLM.
Manter o fluxo de liquidação e as regras existentes sem alterações.

O snapshot congela evento e agregados parciais observados, com hash e limitações.
CPF é pseudonimizado por HMAC; não se concede acesso ao ledger à aplicação de IA.
O cliente MCP stdio expõe seis ferramentas sobre API autenticada. O orquestrador usa
uma sequência fixa, sem execução livre de comandos ou pagamentos.

RAG filtra documentos por fila/vigência, combina busca lexical e embeddings via RRF,
e persiste os trechos usados. PostgreSQL usa pgvector para ranking vetorial; SQLite
é uma alternativa explícita de demonstração. A configuração sem Ollama usa template
rotulado, não simula uma chamada ao modelo.

Pareceres são versionados e revisados separadamente. A identidade do assistente não
tem escopo de revisão. Estado e versão são verificados atomicamente; revisão exige
o parecer mais recente vinculado ao mesmo snapshot. Não há retreinamento automático.

## Consequências

- LLM indisponível não perde alertas; resposta inválida resulta em abstenção.
- Referências e schema são verificáveis; veracidade de texto gerado ainda exige revisão.
- Histórico parcial e eventos atrasados limitam explicações; snapshot não é reconstrução das features.
- Corpus e cenários sintéticos demonstram integração, não eficácia antifraude.
- SSO/OAuth MCP remoto, dados reais, avaliações independentes, retenção e trilha
  WORM exigem trabalho adicional antes de uso produtivo.

Execução e testes: [investigation/README.md](../../investigation/README.md).
