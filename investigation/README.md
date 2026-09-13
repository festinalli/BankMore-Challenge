# BankMore Fraud Intelligence — MVP

**Fluxo integrado validado:** [transferência .NET → Kafka → PyFlink/XGBoost → PostgreSQL → MCP → Ollama](LIVE_VALIDATION.md), incluindo controle efetivado e rejeição sem débito. O ambiente é local, com contas fictícias e score calculado em execução.

Investigação assistida sobre **transferências**, fora do fluxo de liquidação. O consumidor recebe eventos do detector, persiste um dossiê e o analista (ou cliente MCP) solicita a análise. O parecer reúne fatos estruturados, procedimentos versionados e hipóteses; a revisão humana encerra o caso. Nenhuma ferramenta altera pagamentos, regras de risco ou o ledger.

## Executar a demonstração local (Windows / PowerShell)

Na raiz do repositório, com Python 3.12 e Node compatível com o Angular 21:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r investigation/requirements.txt
$env:PYTHONPATH = 'investigation'
.venv/Scripts/python.exe -m bankmore_intelligence setup-demo
.venv/Scripts/python.exe -m bankmore_intelligence seed-demo
.venv/Scripts/python.exe -m bankmore_intelligence serve
```

Em outro terminal:

```powershell
cd frontend
npm ci
npm start
```

Abra **http://localhost:4200/ops/investigacao**. Copie a credencial `INTELLIGENCE_REVIEW_TOKEN` de `investigation/.env.local` no campo de acesso. Ela permite investigar e registrar o desfecho. `INTELLIGENCE_MCP_TOKEN` permite apenas consulta e geração de parecer. O arquivo contém segredos locais, está ignorado pelo Git e não deve ser compartilhado. `setup-demo` preserva uma configuração existente.

A API escuta em `127.0.0.1:5010`. A página usa este endereço fixo de desenvolvimento. A credencial fica somente em memória e é removida ao sair/recarregar. Para publicar em outro ambiente, configurar origem/URL, HTTPS e identidade corporativa antes de expor o serviço.

**Modo demo:** SQLite persistente em `intelligence.db`, recuperação lexical e parecer por template explicitamente identificado. Não usa LLM, não mede eficácia antifraude e não representa inferência semântica.

Os três casos são sintéticos: burst suspeito; movimentação com histórico para discutir possível falso positivo; ausência de histórico. As recomendações não são rótulos de fraude confirmada. Apenas os registros de revisão humana são elegíveis como casos revisados.

## MCP real por stdio

O servidor usa o SDK oficial Python `mcp` 1.30 (linha v1 fixada explicitamente). Configure seu cliente com:

```json
{
  "mcpServers": {
    "bankmore-intelligence": {
      "command": "CAMINHO_ABSOLUTO/.venv/Scripts/python.exe",
      "args": ["-m", "bankmore_intelligence.mcp_server"],
      "env": {
        "PYTHONPATH": "CAMINHO_ABSOLUTO/investigation",
        "INTELLIGENCE_API_URL": "http://127.0.0.1:5010",
        "INTELLIGENCE_MCP_TOKEN": "COPIAR_TOKEN_DO_ASSISTENTE_DO_ARQUIVO_LOCAL"
      }
    }
  }
}
```

Ferramentas: `listar_alertas`, `obter_evidencias_caso`, `obter_resumo_comportamental`, `buscar_procedimentos`, `buscar_casos_revisados`, `registrar_parecer`. A última gera o parecer no servidor e exige `expected_version` do caso; não aceita texto arbitrário para gravar como resultado validado. Não há ferramenta MCP de revisão humana. A API também verifica o escopo, portanto chamar diretamente o endpoint não contorna a permissão.

O adaptador MCP delega à mesma API usada pelo painel. O orquestrador interno executa uma sequência fixa de consultas e uma chamada ao modelo; não é um agente com execução livre de ferramentas. O transporte stdio fica local, e a API remota exige HTTPS no adaptador. Não implementa servidor MCP HTTP remoto/OAuth neste MVP.

## IA local e recuperação híbrida

É possível usar modelos Ollama já instalados; os nomes abaixo são exemplos configuráveis. Não é necessário usar um provedor externo.

```powershell
# Inicie Ollama; baixe os modelos abaixo apenas se quiser usá-los.
ollama pull qwen3:4b
ollama pull embeddinggemma
$env:INTELLIGENCE_MODE = 'ollama'
$env:OLLAMA_CHAT_MODEL = 'qwen3:4b'
$env:OLLAMA_EMBED_MODEL = 'embeddinggemma'
$env:PYTHONPATH = 'investigation'
.venv/Scripts/python.exe -m bankmore_intelligence index-knowledge
.venv/Scripts/python.exe -m bankmore_intelligence serve
```

Faça o seed em modo demo antes de mudar para Ollama, caso deseje investigar os casos sintéticos. `OLLAMA_URL` tem default `http://localhost:11434`. Nenhuma requisição envia CPF bruto. O modo Ollama usa `/api/embed` e `/api/chat` com schema JSON. Falhas ou referências inválidas produzem parecer degradado, sem decisão financeira.

Recuperação: documentos filtrados pela fila e vigência no instante da decisão; ranking lexical por termos normalizados + ranking vetorial combinado por RRF. PostgreSQL executa distância cosseno com pgvector. SQLite usa a mesma combinação com cosseno em Python para a demonstração/testes. Corpus limitado a 500 documentos; não há índice ANN nem reranker neste MVP. A busca lexical não usa ainda o full-text nativo do PostgreSQL. Troca de modelo/dimensão exige reindexação. A versão/modelo de embeddings fica registrada por documento.

O corpus em `knowledge/procedures.json` contém **procedimentos fictícios do case**, não políticas oficiais. Cada documento tem ID versionado, fila, vigência e hash. Alterações de conteúdo exigem novo ID. Os pareceres persistem os trechos recuperados e seus hashes. Referências válidas não provam que uma hipótese é semanticamente correta: a revisão humana continua necessária.

## PostgreSQL + pgvector em banco separado

Após `setup-demo`, na raiz do repositório:

```powershell
docker compose --env-file investigation/.env.local -f investigation/compose.yml up -d --build
docker compose --env-file investigation/.env.local -f investigation/compose.yml exec intelligence-api python -m bankmore_intelligence seed-demo
```

Pare a API local antes para liberar a porta 5010. Banco próprio em `localhost:5544`, sem credenciais/tabelas bancárias. O volume persiste dados. O bootstrap de schema é aditivo (`CREATE IF NOT EXISTS`), com lock de migração no PostgreSQL; mudanças futuras de schema exigirão migrações versionadas. O papel de bootstrap é proprietário do banco do MVP; separação de papéis de migração/runtime fica para implantação produtiva.

Para Ollama no container, altere `INTELLIGENCE_MODE`/modelos no arquivo local, recrie a API e execute `index-knowledge` nela. O endereço do Ollama usado no compose é `host.docker.internal`.

## Integrar ao Kafka existente

Use o mesmo nome de projeto Compose e `.env` da stack bancária, acrescentando o overlay:

```powershell
docker compose --env-file .env --env-file investigation/.env.local -f infra/compose/docker-compose.yml -f infra/compose/intelligence.yml up -d --build intelligence-api intelligence-consumer
docker compose --env-file .env --env-file investigation/.env.local -f infra/compose/docker-compose.yml -f infra/compose/intelligence.yml exec intelligence-api python -m bankmore_intelligence index-knowledge
```

Não execute simultaneamente o compose standalone na mesma porta. O overlay usa a rede `bankmore` do projeto existente e Kafka interno `kafka:29092`. O grupo `bankmore-investigation-v1` lê `transferencia.aprovada`, `transferencia.rejeitada`, `fraude.alerta`. Consome o JSON de saída do PyFlink, não o Avro de `transferencia.solicitada`. PIX pelo bounded context próprio e alertas somente em logs não fazem parte deste primeiro conector.

O consumidor **persiste** alertas continuamente; a geração do parecer é iniciada pelo painel/MCP. Não depende de LLM para confirmar o offset Kafka. Commit síncrono ocorre somente depois da transação local ou quarentena durável. Falha de banco encerra o processo e permite replay; chave fila+tópico+transação deduplica reentregas. Conteúdo divergente com mesma chave vai para quarentena e não substitui evidências. Eventos inválidos armazenam apenas hash, motivo e coordenadas Kafka, sem payload com CPF. Reprocessamento da quarentena é uma operação futura; o Kafka precisa manter o evento original para inspeção autorizada.

## Evidências e limites

- CPF de origem vira HMAC com segredo estável. Destinatário e campos não previstos são descartados. Isso é pseudonimização, não anonimização.
- Snapshot contém o evento, versão do detector, motivos e score quando existentes. As features exatas de inferência não estão no contrato atual e isso é explicitado no painel.
- Histórico corresponde apenas a eventos já recebidos com timestamp anterior/igual à decisão, deduplicados por transação. Eventos atrasados não reescrevem snapshots. A projeção pode estar incompleta, inclusive por ordem de entrega entre tópicos/partições.
- Fatos e valores são produzidos pelo backend; o LLM só retorna hipóteses, limitações, recomendação e referências. Hipóteses não são prova causal nem confirmação de fraude.
- API limita paginação e consulta. Autorização por escopo e fila. Credencial de análise não encerra caso. O desfecho exige parecer vigente e versão atual, com controle otimista de concorrência.
- Documentos são dados não confiáveis; o LLM não dispõe de execução de código ou ações financeiras. O schema e as referências são validados; não há promessa de eliminar toda alucinação ou prompt injection.
- Auditoria registra sujeito, operação, hash do snapshot, modelo, versão do prompt, tokens quando disponíveis e latência. `/api/metrics` resume fila por status. Auditoria é persistida, mas não WORM/assinada. Retenção, exportação Prometheus, SSO, rate limiting e gestão de chaves são trabalhos posteriores.
- Casos revisados são recuperados por tipo e proximidade de valor, com corte temporal. Não há embeddings de casos nem retreinamento automático. Contexto semelhante não determina o mesmo desfecho.

## Verificação

```powershell
.venv/Scripts/python.exe -m pytest investigation/tests -q
cd frontend
npm run build
```

O teste de protocolo inicia API em porta efêmera, conecta cliente MCP real por stdio e chama as seis ferramentas. Testes de aplicação cobrem deduplicação, persistência, autorização, isolamento de fila, corte temporal, abstenção e referências inválidas.

PostgreSQL/pgvector (opcional; use banco de teste, pois cria/remove um schema aleatório exclusivo):

```powershell
$env:INTELLIGENCE_TEST_POSTGRES_URL = 'postgresql+psycopg://USUARIO:SENHA@localhost:5544/intelligence'
.venv/Scripts/python.exe -m pytest investigation/tests/test_postgres.py -q
```

Inferência local real nos três cenários, usando os modelos configurados:

```powershell
.venv/Scripts/python.exe investigation/scripts/evaluate_local.py
```

O script usa banco temporário e falha se algum cenário depender de fallback. É smoke test de integração, não avaliação de eficácia. Não há conjunto independente rotulado suficiente para afirmar ganho de precisão/recall, redução de falsos positivos ou economia de tempo do analista.

## Teste integrado Kafka/PostgreSQL/API em Docker

O arquivo `compose.integration.yml` acrescenta um broker **privado de teste**, sem portas Kafka no host. Não usa nem altera brokers de outros projetos. O teste cria um banco com nome aleatório, inicia o consumidor real e uma API no próprio container, verifica entrega/offsets, deduplicação, quarentena, reinício e permissões, e remove somente esse banco ao terminar.

Na raiz do repositório, depois de `setup-demo`:

```powershell
docker compose --env-file investigation/.env.local -f investigation/compose.yml build intelligence-api
docker compose --env-file investigation/.env.local -f investigation/compose.yml -f investigation/compose.integration.yml up -d --build --wait intelligence-db intelligence-kafka
docker compose --env-file investigation/.env.local -f investigation/compose.yml -f investigation/compose.integration.yml run --rm intelligence-integration-test
docker compose --env-file investigation/.env.local -f investigation/compose.yml -f investigation/compose.integration.yml stop intelligence-kafka
```

O broker de teste usa a distribuição Apache Kafka 3.9.1 com SHA-512 conferido e uma JVM própria no container. É um teste do conector e da API; não sobe .NET/PyFlink nem certifica os fluxos PIX ou toda a stack principal.

Se o Docker Hub falhar ao baixar pgvector, existe uma alternativa usando a imagem PostgreSQL oficial e o pacote PGDG:

```powershell
docker build -f investigation/docker/pgvector.Dockerfile -t bankmore-pgvector:pg16 investigation/docker
$env:INTELLIGENCE_POSTGRES_IMAGE = 'bankmore-pgvector:pg16'
# Repita os comandos Compose acima no mesmo terminal.
```

O override é opcional; o padrão continua sendo a imagem `pgvector/pgvector:pg16`. A versão da extensão instalada pelo pacote depende do repositório PGDG; veja `VALIDATION.md` para as versões efetivamente verificadas. O teste usa a imagem da aplicação construída no primeiro comando e exige credenciais locais com os escopos de assistente gerados por `setup-demo`.
