import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { AuthService, User } from '../../core/services/auth.service';
import { ContaService, MovimentoExtrato } from '../../core/services/conta.service';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="app-shell">
      <header class="topbar">
        <div class="topbar-inner">
          <div class="brand">
            <div class="brand-mark">B</div>
            <span class="brand-name">BankMore</span>
          </div>
          <div class="topbar-actions">
            <button class="chip" (click)="navigateTo('/ops/fraude')" title="Painel ops">
              <span class="dot"></span> Ops
            </button>
            <div class="avatar" [title]="currentUser()?.nomeTitular || ''">
              {{ iniciais() }}
            </div>
            <button class="icon-btn" (click)="logout()" title="Sair">↪</button>
          </div>
        </div>
      </header>

      <main class="app-main">
        <section class="saldo-card">
          <div class="saldo-card-header">
            <div>
              <div class="greeting">Olá, {{ primeiroNome() }} 👋</div>
              <div class="saldo-label">
                Saldo disponível
                <button class="eye-btn" (click)="toggleSaldo()" aria-label="Mostrar/ocultar saldo">
                  {{ saldoVisivel() ? '👁' : '👁‍🗨' }}
                </button>
              </div>
            </div>
          </div>
          <div class="saldo-valor" [class.blurred]="!saldoVisivel()">
            <span class="moeda">R$</span>
            <span class="numero">{{ saldoVisivel() ? formatarBrl(saldoAtual()) : '••••••' }}</span>
          </div>
          <div class="saldo-footer">
            <span>Agência 0001 · Conta {{ currentUser()?.numeroConta || '—' }}</span>
          </div>
        </section>

        <section class="quick-actions">
          <h2 class="section-title">Ações rápidas</h2>
          <div class="actions-grid">
            <button class="action" (click)="navigateTo('/transferencia')">
              <div class="action-icon icon-transfer">↗</div>
              <div class="action-label">Transferir</div>
            </button>
            <button class="action" (click)="navigateTo('/extrato')">
              <div class="action-icon icon-extrato">📋</div>
              <div class="action-label">Extrato</div>
            </button>
            <button class="action" (click)="depositoRapido()">
              <div class="action-icon icon-deposito">+</div>
              <div class="action-label">Depósito</div>
            </button>
            <button class="action" (click)="navigateTo('/ops/fraude')">
              <div class="action-icon icon-ops">🛡️</div>
              <div class="action-label">Ops/Fraude</div>
            </button>
          </div>
        </section>

        <section class="atividade">
          <div class="atividade-header">
            <h2 class="section-title">Atividade recente</h2>
            <a class="link" (click)="navigateTo('/extrato')">Ver tudo</a>
          </div>

          <div *ngIf="loadingExtrato()" class="empty">Carregando…</div>

          <div *ngIf="!loadingExtrato() && movimentos().length === 0" class="empty">
            Nenhum movimento ainda. Faça sua primeira transferência!
          </div>

          <ul *ngIf="!loadingExtrato() && movimentos().length > 0" class="atividade-lista">
            <li *ngFor="let m of movimentosRecentes()" class="atividade-item">
              <div class="atividade-icone" [class.credito]="m.tipo === 'Crédito'" [class.debito]="m.tipo !== 'Crédito'">
                {{ m.tipo === 'Crédito' ? '⬇' : '⬆' }}
              </div>
              <div class="atividade-info">
                <div class="atividade-titulo">{{ m.descricao || (m.tipo === 'Crédito' ? 'Crédito' : 'Débito') }}</div>
                <div class="atividade-data">{{ formatarData(m.data) }}</div>
              </div>
              <div class="atividade-valor"
                   [class.credito]="m.tipo === 'Crédito'"
                   [class.debito]="m.tipo !== 'Crédito'">
                {{ m.tipo === 'Crédito' ? '+' : '-' }}{{ formatarBrl(m.valor) }}
              </div>
            </li>
          </ul>
        </section>

        <div *ngIf="errorMessage()" class="alert alert-danger">{{ errorMessage() }}</div>
      </main>
    </div>
  `,
  styles: [`
    :host { display:block; }
    * { box-sizing: border-box; }
    .app-shell { min-height: 100vh; background: #f5f7fb;
      font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif; color: #1a1a1a; }
    .topbar { background: white; border-bottom: 1px solid #ececf0; position: sticky; top: 0; z-index: 10; }
    .topbar-inner { max-width: 720px; margin: 0 auto; padding: 14px 20px;
      display: flex; align-items: center; justify-content: space-between; }
    .brand { display: flex; align-items: center; gap: 10px; }
    .brand-mark { width: 32px; height: 32px; border-radius: 8px;
      background: linear-gradient(135deg, #667eea, #764ba2); color: white;
      display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 18px; }
    .brand-name { font-weight: 700; font-size: 16px; color: #1a1a1a; }
    .topbar-actions { display: flex; align-items: center; gap: 10px; }
    .chip { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px;
      background: #f0f4ff; color: #4338ca; border: none; border-radius: 999px;
      font-size: 12px; font-weight: 600; cursor: pointer; }
    .chip:hover { background: #e0e7ff; }
    .chip .dot { width: 6px; height: 6px; border-radius: 50%; background: #22c55e; }
    .avatar { width: 36px; height: 36px; border-radius: 50%;
      background: linear-gradient(135deg, #667eea, #764ba2); color: white;
      display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 13px; }
    .icon-btn { background: transparent; border: none; cursor: pointer; font-size: 18px;
      width: 36px; height: 36px; border-radius: 50%; color: #666; }
    .icon-btn:hover { background: #f5f5f5; }
    .app-main { max-width: 720px; margin: 0 auto; padding: 24px 20px 60px; display: flex; flex-direction: column; gap: 28px; }
    .saldo-card { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white; border-radius: 20px; padding: 28px 24px;
      box-shadow: 0 10px 30px rgba(102, 126, 234, 0.25); position: relative; overflow: hidden; }
    .saldo-card::after { content: ''; position: absolute; right: -40px; top: -40px;
      width: 180px; height: 180px; background: rgba(255,255,255,0.08); border-radius: 50%; }
    .saldo-card-header { position: relative; z-index: 1; }
    .greeting { font-size: 14px; opacity: 0.85; margin-bottom: 18px; }
    .saldo-label { font-size: 12px; opacity: 0.7; text-transform: uppercase; letter-spacing: 0.6px;
      display: flex; align-items: center; gap: 8px; }
    .eye-btn { background: transparent; border: none; color: white; opacity: 0.7;
      cursor: pointer; padding: 2px; font-size: 14px; }
    .eye-btn:hover { opacity: 1; }
    .saldo-valor { display: flex; align-items: baseline; gap: 8px; margin-top: 8px;
      position: relative; z-index: 1; transition: filter 0.2s; }
    .saldo-valor.blurred .numero { letter-spacing: 4px; }
    .moeda { font-size: 18px; opacity: 0.85; }
    .numero { font-size: 38px; font-weight: 700; letter-spacing: -0.5px; }
    .saldo-footer { font-size: 12px; opacity: 0.75; margin-top: 16px; position: relative; z-index: 1; }
    .section-title { margin: 0 0 14px; font-size: 14px; font-weight: 600; color: #6b7280;
      text-transform: uppercase; letter-spacing: 0.6px; }
    .actions-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
    .action { background: white; border: 1px solid #ececf0; border-radius: 14px; padding: 16px 8px;
      cursor: pointer; display: flex; flex-direction: column; align-items: center; gap: 10px;
      transition: all 0.15s; font: inherit; color: inherit; }
    .action:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(0,0,0,0.05); border-color: #667eea; }
    .action-icon { width: 44px; height: 44px; border-radius: 12px;
      display: flex; align-items: center; justify-content: center; font-size: 20px;
      background: #f0f4ff; color: #4338ca; }
    .action-icon.icon-deposito { background: #d1fae5; color: #047857; font-weight: 700; font-size: 24px; }
    .action-icon.icon-ops { background: #fee2e2; color: #b91c1c; }
    .action-icon.icon-extrato { background: #fef3c7; color: #92400e; }
    .action-label { font-size: 12px; font-weight: 600; color: #374151; }
    .atividade-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; }
    .atividade-header .section-title { margin: 0; }
    .link { color: #4338ca; font-size: 13px; font-weight: 600; cursor: pointer; }
    .link:hover { text-decoration: underline; }
    .atividade-lista { list-style: none; margin: 0; padding: 0;
      background: white; border-radius: 14px; border: 1px solid #ececf0; overflow: hidden; }
    .atividade-item { display: flex; align-items: center; gap: 14px; padding: 14px 18px;
      border-bottom: 1px solid #f3f4f6; }
    .atividade-item:last-child { border-bottom: none; }
    .atividade-icone { width: 40px; height: 40px; border-radius: 12px;
      display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }
    .atividade-icone.credito { background: #d1fae5; color: #047857; }
    .atividade-icone.debito { background: #fee2e2; color: #b91c1c; }
    .atividade-info { flex: 1; min-width: 0; }
    .atividade-titulo { font-size: 14px; font-weight: 500; color: #1a1a1a;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .atividade-data { font-size: 12px; color: #9ca3af; margin-top: 2px; }
    .atividade-valor { font-size: 14px; font-weight: 700; font-variant-numeric: tabular-nums;
      white-space: nowrap; flex-shrink: 0; }
    .atividade-valor.credito { color: #047857; }
    .atividade-valor.debito { color: #b91c1c; }
    .empty { padding: 32px; text-align: center; color: #9ca3af; font-size: 14px;
      background: white; border-radius: 14px; border: 1px dashed #e5e7eb; }
    .alert { padding: 12px 16px; border-radius: 8px; font-size: 14px; }
    .alert-danger { background: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }
    @media (max-width: 480px) { .numero { font-size: 30px; } .saldo-card { padding: 22px 18px; } }
  `]
})
export class DashboardComponent implements OnInit, OnDestroy {
  private readonly authService = inject(AuthService);
  private readonly contaService = inject(ContaService);
  private readonly router = inject(Router);

  readonly currentUser = signal<User | null>(null);
  readonly saldoAtual = signal(0);
  readonly movimentos = signal<MovimentoExtrato[]>([]);
  readonly saldoVisivel = signal(true);
  readonly loadingExtrato = signal(true);
  readonly errorMessage = signal('');

  readonly movimentosRecentes = computed(() => this.movimentos().slice(0, 5));
  readonly iniciais = computed(() => this.calcIniciais(this.currentUser()?.nomeTitular));
  readonly primeiroNome = computed(() => (this.currentUser()?.nomeTitular || 'cliente').trim().split(/\s+/)[0]);

  private readonly destroy$ = new Subject<void>();

  ngOnInit(): void {
    const user = this.authService.getCurrentUser();
    if (!user) { this.router.navigate(['/login']); return; }
    this.currentUser.set(user);
    this.carregar();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  carregar(): void {
    this.contaService.obterExtrato()
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: r => {
          this.saldoAtual.set(r.saldoAtual ?? 0);
          this.movimentos.set(r.movimentos ?? []);
          this.loadingExtrato.set(false);
        },
        error: () => {
          this.loadingExtrato.set(false);
          this.contaService.obterSaldo().subscribe({
            next: r => this.saldoAtual.set(r.saldo),
            error: () => this.errorMessage.set('Não foi possível carregar a conta.')
          });
        }
      });
  }

  depositoRapido(): void {
    const valorStr = prompt('Valor do depósito (R$):', '100');
    if (!valorStr) return;
    const valor = Number(valorStr.replace(',', '.'));
    if (!Number.isFinite(valor) || valor <= 0) {
      this.errorMessage.set('Valor inválido.');
      return;
    }
    this.contaService.movimentar({ tipo: 'C', valor }).subscribe({
      next: () => this.carregar(),
      error: err => this.errorMessage.set(err.message || 'Erro no depósito.')
    });
  }

  toggleSaldo(): void { this.saldoVisivel.update(v => !v); }
  navigateTo(route: string): void { this.router.navigate([route]); }
  logout(): void { this.authService.logout(); this.router.navigate(['/login']); }

  private calcIniciais(nome: string | null | undefined): string {
    if (!nome) return '?';
    const partes = nome.trim().split(/\s+/);
    return partes.length === 1
      ? partes[0].charAt(0).toUpperCase()
      : (partes[0].charAt(0) + partes[partes.length - 1].charAt(0)).toUpperCase();
  }

  formatarBrl(v: number | null | undefined): string {
    if (v == null) return '0,00';
    return new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v);
  }

  formatarData(s: string | undefined): string {
    if (!s) return '';
    const iso = s.includes('T') ? s : s.replace(' ', 'T') + 'Z';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return s;
    return d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  }
}
