import { ChangeDetectionStrategy, Component, DestroyRef, LOCALE_ID, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule, registerLocaleData } from '@angular/common';
import localePt from '@angular/common/locales/pt';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

registerLocaleData(localePt);

type Acao = 'APROVAR' | 'CONFIRMAR_COM_CLIENTE' | 'RETER_PARA_ANALISE' | 'RECUSAR';
type Categoria = 'golpe' | 'legitimo' | 'anomalia';

interface PixTela {
  valor: string; hora_local: number; tipo_iniciacao: string; count_tx_1h: number; valor_habitual: string;
  primeiro_pix_para_destino: boolean; chave_destino_idade_dias: number; dispositivo_novo: boolean;
  motivo_informado: string; historico: string;
}
interface Cenario { id: number; titulo: string; categoria: Categoria; score_xgboost_exemplo: number; pix: PixTela; }
interface Status { modo: 'ao_vivo' | 'simulado'; modelo: string; xgboost: string; ordem_das_opcoes: string; }
interface RespostaJev {
  modelo: string; golpe: string | null; confianca: number | null;
  probabilidades: Record<string, number>; sinais: Record<string, number | null>; latencia_ms: number;
}
interface EstadoEnviado {
  pagamento: Record<string, string>; motivo_informado_pelo_cliente: string; historico_do_cliente: string;
}
interface Avaliacao {
  cenario: { id: number; titulo: string; categoria: Categoria } | null;
  pix: PixTela; fonte_score: string; simulado: boolean; score_xgboost: number | null; so_xgboost: Acao;
  estado_enviado: EstadoEnviado; jev: RespostaJev | null; erro_jev: string | null; decisao: Acao; motivos: string[];
}
interface Trecho { texto: string; mascara: boolean; }

const API = 'http://127.0.0.1:5011/api';
const PRAZO_MS = 35000; // acima do prazo máximo do Jev na API (30 s): quem desiste primeiro é a API, com fail-open
const DICA = 'A API do Jev não respondeu. Em outro terminal: cd jev; python -m bankmore_jev --api (com TYPESAFE_API_KEY; sem chave, acrescente --offline).';
const OPCOES = ['falso_parente', 'falsa_central', 'falso_vendedor', 'outro_golpe', 'nenhum'];
const SINAIS = ['pressao_de_terceiro', 'instruido_por_terceiro'];
const MASCARAS = /(\[(?:número|email|perfil|chave|conta)\])/;

const ROTULO_ACAO: Record<Acao, string> = {
  APROVAR: 'Aprovar',
  CONFIRMAR_COM_CLIENTE: 'Confirmar com o cliente',
  RETER_PARA_ANALISE: 'Reter para análise',
  RECUSAR: 'Recusar',
};
const ROTULO_GOLPE: Record<string, string> = {
  falso_parente: 'Falso parente',
  falsa_central: 'Falsa central',
  falso_vendedor: 'Falso vendedor',
  outro_golpe: 'Outro golpe',
  nenhum: 'Nenhum golpe',
};
const ROTULO_SINAL: Record<string, string> = {
  pressao_de_terceiro: 'Pressão de terceiro',
  instruido_por_terceiro: 'Instruído por terceiro',
};
const ROTULO_MOTIVO: Record<string, string> = {
  XGBOOST_SCORE_ALTO: 'Score do XGBoost ≥ 0,95',
  XGBOOST_INDISPONIVEL: 'XGBoost indisponível',
  JEV_INDISPONIVEL: 'Jev indisponível: vale o XGBoost',
  JEV_RESPOSTA_INCOMPLETA: 'Resposta incompleta do Jev',
  JEV_ESCOLHA_DESCONHECIDA: 'Rótulo desconhecido',
  JEV_INCERTO: 'Jev em dúvida (confiança < 60%)',
  SINAL_PRESSAO_DE_TERCEIRO: 'Pressão de terceiro',
  SINAL_INSTRUIDO_POR_TERCEIRO: 'Instruído por terceiro',
};
const ROTULO_CATEGORIA: Record<Categoria, string> = { golpe: 'Golpe', legitimo: 'Legítimo', anomalia: 'Anomalia' };
const ROTULO_CAMPO: Record<string, string> = {
  valor: 'Valor',
  valor_em_relacao_ao_cliente: 'Em relação ao cliente',
  periodo_do_dia: 'Período',
  iniciacao: 'Iniciação',
  destinatario: 'Destinatário',
  chave_do_destinatario: 'Chave do destinatário',
  dispositivo: 'Dispositivo',
};

interface Exemplo { titulo: string; motivo: string; }
const EXEMPLOS: Exemplo[] = [
  { titulo: 'Falso parente', motivo: 'Oi mãe, troquei de número. Preciso pagar um boleto hoje, faz esse Pix pra mim que amanhã te devolvo. Não conta pro pai.' },
  { titulo: 'Falsa central', motivo: 'O gerente do banco ligou dizendo que minha conta foi invadida e pediu para transferir tudo para uma conta segura agora.' },
  { titulo: 'Investimento', motivo: 'Plataforma que rende 5% ao dia. O consultor do grupo pediu o depósito hoje para garantir a vaga.' },
  { titulo: 'Pagamento comum', motivo: 'Mensalidade da escola de inglês do meu filho, mesmo valor de todo mês.' },
];

const espera = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

@Component({
  selector: 'app-jev', standalone: true, imports: [CommonModule, FormsModule, RouterLink],
  providers: [{ provide: LOCALE_ID, useValue: 'pt-BR' }],
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './jev.component.html', styleUrls: ['./jev.component.css', './jev.lote.css']
})
export class JevComponent implements OnInit {
  readonly status = signal<Status | null>(null);
  readonly cenarios = signal<Cenario[]>([]);
  readonly selecionado = signal<number | 'personalizado' | null>(null);
  readonly resultado = signal<Avaliacao | null>(null);
  readonly etapa = signal(0);
  readonly ocupado = signal(false);
  readonly erro = signal('');
  readonly lote = signal<Avaliacao[]>([]);
  readonly emLote = signal(false);
  readonly verJson = signal(false);

  private readonly cancelamento = new AbortController();

  readonly opcoes = OPCOES;
  readonly sinais = SINAIS;
  readonly exemplos = EXEMPLOS;
  readonly horas = Array.from({ length: 24 }, (_, h) => h);

  personalizado = {
    valor: 1500, hora_local: 14, valor_habitual: 2000, count_tx_1h: 0,
    primeiro_pix_para_destino: true, chave_destino_idade_dias: 1, dispositivo_novo: false,
    motivo_informado: '', historico: 'Aposentada. Paga contas e faz Pix para os filhos, sempre para as mesmas chaves.',
    score_xgboost: 0.06,
  };

  readonly cenarioAtual = computed(() => {
    const id = this.selecionado();
    return typeof id === 'number' ? this.cenarios().find(c => c.id === id) ?? null : null;
  });

  readonly resumo = computed(() => {
    const itens = this.lote();
    const golpes = itens.filter(r => r.cenario?.categoria === 'golpe');
    const passariam = golpes.filter(r => r.so_xgboost === 'APROVAR');
    const legitimos = itens.filter(r => r.cenario?.categoria === 'legitimo');
    const latencias = itens.filter(r => r.jev && !r.simulado).map(r => r.jev!.latencia_ms).sort((a, b) => a - b);
    const meio = Math.floor(latencias.length / 2);
    return {
      golpes: golpes.length,
      passariam: passariam.length,
      segurados: passariam.filter(r => r.decisao !== 'APROVAR').length,
      legitimos: legitimos.length,
      atrito: legitimos.filter(r => r.decisao !== r.so_xgboost).length,
      mudou: itens.filter(r => r.decisao !== r.so_xgboost).length,
      mediana: latencias.length ? (latencias.length % 2 ? latencias[meio] : (latencias[meio - 1] + latencias[meio]) / 2) : null,
      falhas: itens.filter(r => r.erro_jev && !r.simulado).length,
    };
  });

  constructor() {
    inject(DestroyRef).onDestroy(() => this.cancelamento.abort());
  }

  async ngOnInit(): Promise<void> {
    await this.conectar();
  }

  async conectar(): Promise<void> {
    this.erro.set('');
    try {
      const [status, cenarios] = await Promise.all([this.pedir<Status>('/status'), this.pedir<Cenario[]>('/cenarios')]);
      this.status.set(status);
      this.cenarios.set(cenarios);
      if (this.selecionado() === null && cenarios.length) this.selecionado.set(cenarios[0].id);
    } catch (falha) {
      if (this.cancelado()) return;
      this.status.set(null);
      this.erro.set(falha instanceof Error ? falha.message : DICA);
    }
  }

  escolher(id: number | 'personalizado'): void {
    if (this.ocupado()) return;
    this.selecionado.set(id);
    this.resultado.set(null);
    this.etapa.set(0);
    this.emLote.set(false);
    this.erro.set('');
    this.rolarParaInicio();
  }

  usarExemplo(exemplo: Exemplo): void {
    this.personalizado = { ...this.personalizado, motivo_informado: exemplo.motivo };
  }

  async avaliar(): Promise<void> {
    if (this.ocupado()) return;
    const alvo = this.selecionado();
    if (alvo === null) return;
    const corpo = alvo === 'personalizado'
      ? { pix: this.pixPersonalizado(), score_xgboost: Number(this.personalizado.score_xgboost) }
      : { cenario_id: alvo };
    this.ocupado.set(true); this.erro.set(''); this.resultado.set(null); this.etapa.set(0); this.verJson.set(false);
    try {
      const avaliacao = await this.pedir<Avaliacao>('/avaliar', corpo);
      this.resultado.set(avaliacao);
      await espera(60);
      this.mostrar('.pipeline');
      for (const passo of [1, 2, 3]) {
        this.etapa.set(passo);
        await espera(380);
      }
    } catch (falha) {
      if (!this.cancelado()) this.erro.set(falha instanceof Error ? falha.message : 'Não foi possível avaliar.');
    } finally {
      this.ocupado.set(false);
      this.devolverFoco('avaliar');
    }
  }

  async rodarTodos(): Promise<void> {
    if (this.ocupado() || !this.cenarios().length) return;
    this.ocupado.set(true); this.emLote.set(true); this.erro.set(''); this.lote.set([]); this.resultado.set(null);
    this.rolarParaInicio();
    try {
      for (const cenario of this.cenarios()) {
        if (this.cancelado()) return;
        this.selecionado.set(cenario.id);
        const avaliacao = await this.pedir<Avaliacao>('/avaliar', { cenario_id: cenario.id });
        this.lote.update(itens => [...itens, avaliacao]);
        await espera(250);
      }
    } catch (falha) {
      if (!this.cancelado()) this.erro.set(falha instanceof Error ? falha.message : 'Não foi possível concluir os cenários.');
    } finally {
      this.ocupado.set(false);
      this.devolverFoco('rodar-todos');
    }
  }

  rotuloAcao(acao: Acao): string { return ROTULO_ACAO[acao] ?? acao; }
  rotuloGolpe(golpe: string | null): string { return golpe ? ROTULO_GOLPE[golpe] ?? golpe : 'Resposta incompleta'; }
  rotuloSinal(sinal: string): string { return ROTULO_SINAL[sinal] ?? sinal; }
  rotuloCategoria(categoria: Categoria): string { return ROTULO_CATEGORIA[categoria] ?? categoria; }
  rotuloCampo(campo: string): string { return ROTULO_CAMPO[campo] ?? campo; }
  rotuloMotivo(motivo: string): string {
    if (motivo.startsWith('GOLPE_')) return 'Golpe: ' + this.rotuloGolpe(motivo.slice(6).toLowerCase()).toLowerCase();
    return ROTULO_MOTIVO[motivo] ?? motivo;
  }
  classeAcao(acao: Acao): string { return 'acao-' + acao.toLowerCase().replace(/_/g, '-'); }
  porcento(valor: number | null | undefined): number { return Math.round((valor ?? 0) * 100); }
  camposPagamento(estado: EstadoEnviado): [string, string][] { return Object.entries(estado.pagamento); }
  trechos(texto: string): Trecho[] {
    return texto.split(MASCARAS).filter(Boolean).map(parte => ({ texto: parte, mascara: MASCARAS.test(parte) }));
  }
  json(valor: unknown): string { return JSON.stringify(valor, null, 2); }
  temProbabilidades(jev: RespostaJev): boolean { return Object.keys(jev.probabilidades ?? {}).length > 0; }

  private mostrar(seletor: string): void {
    if (typeof document !== 'undefined') document.querySelector(seletor)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  /** No celular a lista fica acima do resultado: rola até o painel; no desktop, até o topo. */
  private rolarParaInicio(): void {
    if (typeof window === 'undefined') return;
    if (window.innerWidth <= 950) this.mostrar('article');
    else window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  /** O botão fica desabilitado durante a chamada e perde o foco; devolve para quem usa teclado. */
  private devolverFoco(id: string): void {
    setTimeout(() => {
      if (typeof document !== 'undefined' && document.activeElement === document.body) {
        document.getElementById(id)?.focus({ preventScroll: true });
      }
    });
  }

  private cancelado(): boolean { return this.cancelamento.signal.aborted; }

  private pixPersonalizado() {
    const p = this.personalizado;
    return {
      valor: Number(p.valor), hora_local: Number(p.hora_local), valor_habitual: Number(p.valor_habitual),
      count_tx_1h: Number(p.count_tx_1h), primeiro_pix_para_destino: !!p.primeiro_pix_para_destino,
      chave_destino_idade_dias: Number(p.chave_destino_idade_dias), dispositivo_novo: !!p.dispositivo_novo,
      motivo_informado: p.motivo_informado, historico: p.historico,
    };
  }

  private async pedir<T>(caminho: string, corpo?: unknown): Promise<T> {
    let resposta: Response;
    try {
      resposta = await fetch(API + caminho, {
        method: corpo === undefined ? 'GET' : 'POST',
        headers: corpo === undefined ? {} : { 'Content-Type': 'application/json' },
        body: corpo === undefined ? undefined : JSON.stringify(corpo),
        signal: AbortSignal.any([this.cancelamento.signal, AbortSignal.timeout(PRAZO_MS)]),
      });
    } catch (falha) {
      if (this.cancelado()) throw falha;
      if (falha instanceof DOMException && falha.name === 'TimeoutError') {
        throw new Error('A API do Jev demorou demais para responder. Tente de novo.');
      }
      this.status.set(null); // rede: mostra "API desconectada" e o botão de tentar de novo
      throw new Error(DICA);
    }
    if (!resposta.ok) {
      const dados = await resposta.json().catch(() => ({}));
      throw new Error(typeof dados.erro === 'string' ? dados.erro : `A API respondeu ${resposta.status}.`);
    }
    return resposta.json() as Promise<T>;
  }
}
