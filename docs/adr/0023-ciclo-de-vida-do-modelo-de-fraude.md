# ADR 0023 — Ciclo de vida do modelo de fraude: registro, sombra, drift e portão de promoção

**Status:** Aceita (implementada em `ml/`); o critério de promoção v2 está em aberto · **Data:** 2026-10-13

## Contexto

O `fraud-ml` ([ADR 0004](0004-ml-fail-open.md), [ADR 0018](0018-sprint9-antifraude-inline-pix.md)) treina um XGBoost no build da imagem e serve o modelo embutido. Trocar de modelo significava rebuild e redeploy. Faltavam quatro peças:

- um registro de versões;
- uma regra para decidir se um modelo novo pode substituir o atual;
- um jeito de ver o modelo novo no tráfego antes de ele decidir;
- monitoramento de drift.

Quem barra o Pix não é o `fraud-ml`. O Pix API (`PixLiquidacaoService`, `FRAUDE_THRESHOLD`) e o PyFlink (`ML_REJEITAR_THRESHOLD`) chamam o `/predict` e barram com `score >= 0,95`. O `decisao_recomendada` da resposta usa outro limiar, o da ficha do modelo, e hoje ninguém o consome.

Os dados continuam **sintéticos**. O AUC de treino perto de 1 diz que os padrões sintéticos são fáceis, não que o modelo é bom.

## Decisão

1. **Registro de modelos em arquivos** (`ml/registro.py`):
   - versão imutável, com nome validado;
   - estados candidato → sombra → produção → arquivado, com histórico de cada transição e motivo;
   - `reverter()` para voltar à versão anterior;
   - escrita atômica do índice;
   - uma **ficha** por versão com:
     - hash dos dados e do código de treino;
     - hash da régua de promoção;
     - versões das bibliotecas e plataforma;
     - métricas, limiar e referência de drift;
     - o comando que refaz o treino.

   A escolha por arquivos, e não MLflow, é deliberada: zero dependência nova, cabe no container e basta para um modelo. Vale migrar quando houver vários modelos ou vários times.

2. **Retreino reproduzível** (`ml/retreinar.py`):
   - o mesmo comando gera os mesmos dados (mesmo hash, com números arredondados a 6 casas para o hash valer no Windows e no Linux) e as mesmas métricas;
   - o retreino gera sempre um **candidato**, nunca produção;
   - o cenário `base` com seed 42 reproduz o dataset do `train.py` anterior, conferido byte a byte no Windows contra o código antigo.

3. **Portão de promoção** (`ml/portao.py` + `ml/criterio_promocao.json`):
   - **Métrica:** recall com taxa fixa de falso positivo, 1% das transações legítimas (Pix, TED e TEF).
   - **Avaliação:** dois conjuntos, `base` e `nova_fraude`, gerados num fluxo aleatório separado (`spawn_key` próprio) que nenhuma seed de treino reproduz.
   - **Regra v1:** o candidato não pode ser pior que a produção em nenhum conjunto.
   - **Laudo:** a promoção exige um laudo aprovado, emitido contra a produção atual e com a mesma régua da ficha do candidato.
   - **Informação extra no laudo:** o IC95 da diferença (bootstrap pareado), o recall com 0,1% e 0,3% de falso positivo, e os números no limiar de cada modelo e no 0,95 dos consumidores.

   A métrica é recall com FPR fixa, e não AUC, porque no antifraude o custo está no ponto de operação: quantos clientes legítimos o banco aceita barrar.

4. **Modo sombra** (`ml/app.py`):
   - a versão em sombra pontua a mesma transação, na mesma requisição, **depois** da decisão; ela é síncrona e soma um predict à latência;
   - nunca decide;
   - falhas dela, ao carregar ou ao pontuar, não afetam a produção nem a subida do serviço;
   - as discordâncias são contadas no limiar de cada modelo e no 0,95 dos consumidores (`ml_sombra_discordancias_total{limiar}`);
   - as discordâncias também vão para `registro/sombra/<versao>.jsonl`, sem `cpfOrigem`, com valores arredondados, hora ao minuto e no máximo 5 MB por versão.

   A sombra é recomendada, não obrigatória: o registro aceita promover um candidato que não passou por ela.

5. **Drift por PSI** (`ml/drift.py`):
   - a referência fica na ficha: decis para as features contínuas e proporção por valor para as discretas (hora, dia, contagem, flags) e categóricas;
   - features que vieram de placeholder (sem feature store) ficam fora do cálculo, para o PSI não medir o placeholder;
   - o cálculo exige no mínimo 1.000 transações na janela; com 200, o próprio ruído passava de 0,10;
   - há alertas no Prometheus (`infra/prometheus/alerts/ml.yml`) pela regra de bolso do mercado: 0,10 moderado, 0,25 alto.

6. **Troca sem redeploy:** o serviço confere o registro a cada 5 s. Promover e reverter pela CLI chegam ao `/predict` sozinhos. Uma recarga que falha mantém o modelo anterior e conta em `ml_recarga_falhas_total`.

7. **Um processo:** o Gunicorn passa de 2 workers para 1 processo com 4 threads. Assim, os contadores, a janela de drift e o estado da sombra são do serviço todo, e os alertas sobre contadores funcionam. O predict do XGBoost com árvores é thread-safe.

8. **CI** (`.github/workflows/ml.yml`):
   - roda os testes e o ciclo completo (`scripts/demo_ciclo.py --rapido`), que falha se algum passo não acontecer;
   - constrói a imagem e confere se ela sobe e responde;
   - valida as regras de alerta com o `promtool`.

## O que o portão garante e o que não garante

- **Garante:** o laudo usa a régua vigente quando o candidato foi treinado. A régua cobre o critério, o gerador da avaliação e o código do portão. Se ela mudar, o portão se recusa a avaliar candidatos antigos, e toda troca aparece como versão nova, retreino e laudo novo.
- **Não garante:** que ninguém escolha a régua depois de ver resultados. Retreinar a mesma receita leva segundos, e a demo faz exatamente isso, de propósito, com um critério v2 hipotético. Isso é governança (quem aprova o critério, com que dados), não código.
- **O git também não prova a ordem:** critério, código e resultados entraram juntos neste trabalho. O conteúdo da regra v1 (1% de FPR, tolerância zero, dois cenários) foi fixado antes do primeiro candidato. Depois disso, o cenário `nova_fraude` foi reforçado (valores maiores, para o drift aparecer) e a avaliação ganhou o fluxo aleatório separado.
- **O laudo não é assinado:** a exigência de laudo é de processo (a CLI), não criptográfica.

## O que os experimentos mostraram (dados sintéticos)

**Drift** (`python scripts/demo_ciclo.py`, 100 mil transações por treino):

- No tráfego habitual, o PSI máximo foi 0,009. Com a população nova, subiu para 0,54 (média de 24h), 0,50 (p95 de 30 dias), 0,22 (valor) e 0,12 (tipo).
- A v1 barrou 36 de 40 fraudes antes da mudança e 20 de 40 depois.

**Candidatos contra a v1** (`python scripts/experimento_seeds.py`): variação de recall com 1% de falso positivo; a produção é a v1 (base, seed 42, 100 mil).

| Receita | Seeds | n | Padrão antigo | Cenário novo | Critério v1 |
|---|---|---|---|---|---|
| **Controle:** a receita da v1, outra seed | 1 a 8 | 100 mil | −0,9 a 0,0 ponto | −3,7 a −1,7 pontos | reprova 8 de 8 |
| Só dados novos | 7, 8, 9 | 100 mil | −4,9 a −3,6 pontos | +32 a +33 pontos | reprova 3 de 3 |
| Antigos + novos | 11 a 18 | 100 mil | −2,9 a −1,4 pontos | +29 a +32 pontos | reprova 8 de 8 |
| Antigos + novos | 11, 13, 15 | 200 mil | −1,6 a −0,9 ponto | +32 pontos | reprova 3 de 3 |
| Antigos + novos | 11, 13 | 400 mil | −0,9 ponto | +33 pontos | reprova 2 de 2 |

Leitura:

- **A tolerância zero do critério v1 é mais rígida que o ruído.** Ela reprova até a própria receita da produção quando só a seed muda. Com 800 fraudes por conjunto, uma fraude vale 0,125 ponto. A v1 (seed 42) também saiu melhor que as outras 8 seeds no cenário novo, um efeito de seleção. Um critério sério precisa partir desse piso de ruído.
- **A perda das misturas no padrão antigo é real, não ruído.** Na v3 (seed 11), o IC95 fica entre −3,2 e −0,9 ponto. Mais dados reduzem a perda, mas não a eliminam: ela fica perto de 1 ponto com 400 mil transações, no limite do que 800 fraudes conseguem medir.
- **Perto do ponto de operação, a troca é maior.** Com a v4 da demo (mistura, seed 13), nos conjuntos de avaliação:

| Ponto de comparação | Padrão antigo (v1 → v4) | Cenário novo (v1 → v4) |
|---|---|---|
| 1% de falso positivo | 99,0% → 97,0% (−2,0) | 62,1% → 94,3% (+32,2) |
| 0,1% de falso positivo | 91,9% → 85,4% (−6,5) | 52,5% → 67,2% (+14,7) |
| Limiar de 0,95 dos consumidores | 90,2% → 84,8% (−5,4), FP 0,069% → 0,087% | 55,5% → 77,1% (+21,6), FP 0,19% → 0,23% |

Em resumo, com o critério de 1% a v4 parece custar 2 pontos no padrão antigo. No ponto em que o sistema barra de fato, custa 5 a 6,5 pontos, e o ganho no cenário novo cai para 15 a 22 pontos.

## Decisões em aberto (de quem responde pelo antifraude)

- **Critério v2.** Três escolhas que só quem responde pelo antifraude pode fazer:
  - aceitar ou não a troca entre o padrão antigo e o golpe novo;
  - com que tolerância, de preferência sobre o limite inferior do IC, que o portão já suporta com `regra_estatistica`, e acima do piso de ruído;
  - em qual ponto de falso positivo medir.

  A demo usa um critério v2 **hipotético** (até 3 pontos de perda com 1% de FPR, ganho mínimo de 20), escolhido depois de ver a v3, só para mostrar o mecanismo. O critério do repositório continua o v1.
- **Uma fonte para o ponto de operação.** Os consumidores barram com 0,95 fixo. O `decisao_recomendada` usa o limiar da ficha. Há dois caminhos:
  - os consumidores passam a usar o `decisao_recomendada`, e o limiar troca junto com o modelo;
  - o critério passa a medir no 0,95.

  Hoje, promover um modelo sem redeploy muda a distribuição de score por baixo de um corte fixo. O laudo mostra isso, mas não decide por isso.

## Consequências

- ✅ Toda versão é rastreável: dados, código, régua, bibliotecas, plataforma e comando para refazer.
- ✅ Nenhum modelo entra em produção pela CLI sem laudo coerente com a ficha, e toda troca de régua fica visível.
- ✅ O candidato pode rodar no tráfego antes de decidir; promover e reverter levam segundos e não exigem deploy.
- ✅ O drift vira métrica e alerta, inclusive em features discretas.
- ⚠ **Registro em arquivo, sem trava entre processos:** uma CLI por vez. No container, as promoções sobrevivem a restart, mas recriar o container volta ao estado da imagem. Em produção, o registro iria para um volume ou storage de objetos.
- ⚠ **Sombra síncrona:** soma um `predict_proba` por requisição enquanto há sombra, medido em `ml_sombra_duration_seconds`.
- ⚠ **Placeholders do feature store:** sem histórico no Redis, `valor_medio_cpf_24h` e `valor_p95_cpf_30d` vêm de placeholder. O PSI dessas features só usa valores reais, e o uso de placeholder é contado em `ml_feature_placeholder_total`.
- ⚠ **Rótulos chegam com atraso:** em produção, o recall depende de fraude confirmada (MED, contestação), que chega com dias ou semanas de atraso. O portão rodaria sobre uma janela rotulada, não sobre o tráfego do dia.
- ⚠ **Retreino sem agendamento:** ele é manual ou roda no CI. Agendar só faz sentido com dado real.
- ⚠ **Dados sintéticos:** os números mostram o mecanismo e as trocas, não a eficácia de um antifraude real.
