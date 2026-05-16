import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

interface FraudeEvento {
  evento: 'ALERTA' | 'REJEITADA';
  topico: string;
  recebidoEm: string;
  id: string;
  cpfOrigem?: string;
  cpfDestino?: string;
  valor?: number;
  tipo?: string;
  taxa?: number;
  motivos?: string[];
  decisao?: string;
  decididoEm?: number;
  latenciaMs?: number;
  modeloVersao?: string;
  scoreFraude?: number;
  canal?: string;
}

@Component({
  selector: 'app-fraude-ops',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="ops-container">
      <nav class="navbar">
        <div class="navbar-brand">
          <h1>BankMore — Ops/Fraude</h1>
          <span class="badge" [class.online]="conectado()" [class.offline]="!conectado()">
            {{ conectado() ? '● ao vivo' : '○ desconectado' }}
          </span>
        </div>
        <div class="navbar-menu">
          <label>
            <input type="checkbox" [checked]="filtroAlerta()" (change)="filtroAlerta.set(!!$any($event.target).checked)" /> Alertas
          </label>
          <label>
            <input type="checkbox" [checked]="filtroRejeitada()" (change)="filtroRejeitada.set(!!$any($event.target).checked)" /> Rejeitadas
          </label>
          <button class="btn-clear" (click)="limpar()">Limpar</button>
        </div>
      </nav>

      <div class="content">
        <div class="stats">
          <div class="stat-card">
            <span class="stat-label">Alertas</span>
            <span class="stat-value alerta">{{ contadores().alerta }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">Rejeições</span>
            <span class="stat-value rejeitada">{{ contadores().rejeitada }}</span>
          </div>
          <div class="stat-card">
            <span class="stat-label">Total recebido</span>
            <span class="stat-value">{{ eventos().length }}</span>
          </div>
        </div>

        <div *ngIf="eventosFiltrados().length === 0" class="empty">
          Aguardando eventos no stream. Dispare uma transferência suspeita pra ver chegar.
        </div>

        <div class="lista">
          <div *ngFor="let e of eventosFiltrados()" class="card"
               [class.card-rejeitada]="e.evento === 'REJEITADA'"
               [class.card-alerta]="e.evento === 'ALERTA'">
            <div class="card-header">
              <span class="tag">{{ e.evento }}</span>
              <span class="tag tipo">{{ e.tipo || '—' }}</span>
              <span class="id" [title]="e.id">{{ shortId(e.id) }}</span>
              <span class="hora">{{ formatarHora(e.recebidoEm) }}</span>
            </div>
            <div class="card-body">
              <div class="row">
                <span class="label">Origem</span>
                <span class="value">{{ mascararCpf(e.cpfOrigem) }}</span>
              </div>
              <div class="row">
                <span class="label">Destino</span>
                <span class="value">{{ mascararCpf(e.cpfDestino) }}</span>
              </div>
              <div class="row">
                <span class="label">Valor</span>
                <span class="value valor">{{ formatarBrl(e.valor) }}</span>
              </div>
              <div class="row" *ngIf="e.scoreFraude != null">
                <span class="label">Score</span>
                <span class="value score"
                      [class.score-alto]="(e.scoreFraude || 0) >= 0.95">
                  {{ formatarScore(e.scoreFraude) }}
                </span>
              </div>
              <div class="row" *ngIf="e.modeloVersao">
                <span class="label">Modelo</span>
                <span class="value">{{ e.modeloVersao }}</span>
              </div>
              <div class="row" *ngIf="e.latenciaMs != null">
                <span class="label">Latência</span>
                <span class="value">{{ e.latenciaMs }} ms</span>
              </div>
              <div class="motivos" *ngIf="e.motivos?.length">
                <span *ngFor="let m of e.motivos" class="motivo">{{ m }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .ops-container { min-height: 100vh; background: #0f172a; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, sans-serif; }
    .navbar { background: linear-gradient(135deg, #1e293b 0%, #334155 100%); padding: 16px 32px;
              display: flex; justify-content: space-between; align-items: center;
              box-shadow: 0 2px 8px rgba(0,0,0,0.4); position: sticky; top: 0; z-index: 10; }
    .navbar-brand { display: flex; align-items: center; gap: 16px; }
    .navbar-brand h1 { margin: 0; font-size: 20px; color: #f1f5f9; }
    .badge { padding: 4px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; }
    .badge.online { background: #064e3b; color: #34d399; }
    .badge.offline { background: #7f1d1d; color: #fca5a5; }
    .navbar-menu { display: flex; align-items: center; gap: 16px; font-size: 14px; }
    .navbar-menu label { cursor: pointer; display: flex; align-items: center; gap: 6px; }
    .btn-clear { background: rgba(255,255,255,0.1); color: #e2e8f0; border: 1px solid #475569;
                 padding: 6px 14px; border-radius: 4px; cursor: pointer; font-size: 13px; }
    .btn-clear:hover { background: rgba(255,255,255,0.2); }
    .content { padding: 24px 32px; max-width: 1400px; margin: 0 auto; }
    .stats { display: flex; gap: 16px; margin-bottom: 24px; }
    .stat-card { background: #1e293b; padding: 16px 24px; border-radius: 8px; flex: 1;
                 display: flex; flex-direction: column; gap: 4px; }
    .stat-label { font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }
    .stat-value { font-size: 28px; font-weight: 700; color: #f1f5f9; }
    .stat-value.alerta { color: #fbbf24; }
    .stat-value.rejeitada { color: #f87171; }
    .empty { text-align: center; padding: 60px; color: #64748b; background: #1e293b;
             border-radius: 8px; border: 1px dashed #334155; }
    .lista { display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 16px; }
    .card { background: #1e293b; border-radius: 8px; padding: 16px; border-left: 4px solid #475569;
            box-shadow: 0 1px 3px rgba(0,0,0,0.3); transition: transform 0.15s; }
    .card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.5); }
    .card-alerta { border-left-color: #fbbf24; }
    .card-rejeitada { border-left-color: #f87171; }
    .card-header { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
    .tag { font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 4px;
           text-transform: uppercase; letter-spacing: 0.5px; background: #334155; color: #cbd5e1; }
    .card-alerta .tag:first-child { background: #78350f; color: #fbbf24; }
    .card-rejeitada .tag:first-child { background: #7f1d1d; color: #fca5a5; }
    .tag.tipo { background: #1e3a8a; color: #93c5fd; }
    .id { font-family: ui-monospace, monospace; font-size: 12px; color: #94a3b8; }
    .hora { margin-left: auto; font-size: 12px; color: #64748b; }
    .card-body { display: flex; flex-direction: column; gap: 6px; }
    .row { display: flex; justify-content: space-between; font-size: 13px; }
    .label { color: #94a3b8; }
    .value { font-family: ui-monospace, monospace; color: #e2e8f0; }
    .value.valor { font-weight: 700; color: #f1f5f9; }
    .value.score { color: #fbbf24; }
    .value.score.score-alto { color: #f87171; font-weight: 700; }
    .motivos { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .motivo { font-size: 11px; padding: 2px 8px; background: #334155; color: #fca5a5;
              border-radius: 3px; font-family: ui-monospace, monospace; }
  `]
})
export class FraudeOpsComponent implements OnInit, OnDestroy {
  // Sob zoneless, EventSource handlers atualizam signals diretamente — change detection
  // dispara automaticamente sem precisar de NgZone.run().
  readonly eventos = signal<FraudeEvento[]>([]);
  readonly conectado = signal(false);
  readonly filtroAlerta = signal(true);
  readonly filtroRejeitada = signal(true);

  readonly eventosFiltrados = computed(() =>
    this.eventos().filter(e =>
      (e.evento === 'ALERTA' && this.filtroAlerta()) ||
      (e.evento === 'REJEITADA' && this.filtroRejeitada())
    )
  );

  readonly contadores = computed(() => {
    let alerta = 0, rejeitada = 0;
    for (const e of this.eventos()) {
      if (e.evento === 'ALERTA') alerta++;
      else if (e.evento === 'REJEITADA') rejeitada++;
    }
    return { alerta, rejeitada };
  });

  private es?: EventSource;
  private readonly maxEventos = 50;
  private readonly streamUrl = 'http://localhost:5000/api/admin/fraude/stream';

  ngOnInit(): void { this.conectar(); }
  ngOnDestroy(): void { this.es?.close(); }

  private conectar(): void {
    this.es = new EventSource(this.streamUrl);
    this.es.onopen = () => this.conectado.set(true);
    this.es.onerror = () => this.conectado.set(false);
    this.es.onmessage = (msg) => {
      try {
        const evt = JSON.parse(msg.data) as FraudeEvento;
        this.eventos.update(list => [evt, ...list].slice(0, this.maxEventos));
      } catch { /* payload malformado — ignora */ }
    };
  }

  limpar(): void { this.eventos.set([]); }

  shortId(id: string | undefined): string {
    return id ? id.slice(0, 8) : '—';
  }

  mascararCpf(cpf: string | undefined): string {
    if (!cpf || cpf.length < 11) return '—';
    return `${cpf.slice(0, 3)}.***.***-${cpf.slice(-2)}`;
  }

  formatarBrl(valor: number | undefined): string {
    if (valor == null) return '—';
    return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(valor);
  }

  formatarScore(score: number | undefined): string {
    return score == null ? '—' : score.toFixed(3);
  }

  formatarHora(iso: string | undefined): string {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
}
