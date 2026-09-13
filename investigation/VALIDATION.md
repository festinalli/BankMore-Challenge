# Validação local — 13/09/2026

**Validação posterior:** o fluxo de transferências .NET → Kafka → PyFlink/XGBoost → PostgreSQL → MCP/Ollama também passou. Veja [resultados e reprodução](LIVE_VALIDATION.md). As seções abaixo preservam o escopo das verificações iniciais.

Branch: `codex/fraud-intelligence-mvp`.

| Verificação | Resultado |
|---|---|
| Suíte Python/API/MCP/PostgreSQL | 13 passaram; nenhum teste ignorado com banco de teste configurado |
| MCP real | Inicialização stdio, descoberta e execução das seis ferramentas contra HTTP autenticado |
| Build Angular de produção | Passou; aviso de tamanho no CSS do dashboard preexistente |
| Compose standalone e overlay | `config --quiet` passou em ambos |
| UI no navegador | Login local, seleção, parecer, valores pt-BR e encerramento sintético como inconclusivo verificados |
| Geração + embeddings reais | Ollama `qwen3:4b` + `nomic-embed-text:latest`, prompt `investigation-v2`, três cenários sem fallback |
| PostgreSQL/pgvector | PostgreSQL 16.14 + pgvector 0.8.6: distância vetorial SQL, persistência, isolamento de schema e deduplicação passaram |
| Kafka → consumidor → PostgreSQL → API em Linux | Passou com broker Apache Kafka 3.9.1 privado e imagem Docker da aplicação |

Amostra de integração Ollama com geração sem pensamento e schema com IDs restritos:

| Cenário sintético | Recomendação retornada | Tempo observado |
|---|---|---|
| Suspeita / burst | INVESTIGAR | 8,8 s |
| Contexto para possível falso positivo | REVISAR_CONTEXTO | 7,3 s |
| Histórico insuficiente | COLETAR_EVIDENCIAS | 7,0 s |

Tempos são de uma execução local, não benchmark ou SLA. A recuperação foi `hybrid-rrf`
em SQLite com embeddings reais. Em seguida, o caminho SQL de distância vetorial em
PostgreSQL foi executado pelo teste dedicado, com vetores controlados. Esta execução
separada não equivale a um benchmark conjunto de Ollama + PostgreSQL.

Após o Docker ser iniciado pelo usuário, a imagem Linux da aplicação foi construída.
O download das imagens pgvector e Kafka pelo Docker Hub falhou com EOF. O PostgreSQL
foi construído a partir da imagem oficial já disponível e do pacote PGDG
`postgresql-16-pgvector`; o broker de teste foi construído a partir do arquivo oficial
Apache Kafka 3.9.1, com SHA-512 verificado. Essas alternativas são reproduzíveis em
`investigation/docker/` e mantêm os demais serviços Docker existentes intactos.

O teste `scripts/check_kafka.py` verificou entrega confirmada pelo broker, snapshot
PostgreSQL, deduplicação, offsets confirmados, quarentena durável de evento inválido e
de conteúdo divergente, reinício do consumidor e geração de parecer via API autenticada.
A tentativa de revisão com credencial do assistente retornou 403. O banco aleatório
exclusivo do teste é removido ao final. O teste não executa o fluxo bancário completo
(.NET/PyFlink/PIX), nem substitui homologação na versão Kafka da stack principal.

Tentativas iniciais com outro modelo local produziram interpretações incorretas apesar
de referências válidas; geração com pensamento também produziu JSON inválido e acionou
abstenção. A configuração final passou no smoke test dos três casos, mas texto livre
ainda exige revisão. Não foi construído um conjunto independente de avaliação de
qualidade nem estimado ganho de precisão, recall, falsos positivos ou produtividade.

Nenhuma alteração foi aplicada às regras do detector ou ao ledger. As verificações
acima foram realizadas antes da publicação do código no GitHub. Publicar o código
não representa deploy da aplicação: nenhum deploy público ou transação bancária
foi realizado nesta validação.
