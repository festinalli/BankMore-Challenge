import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { AuthService, User } from '../../core/services/auth.service';
import { ContaService, MovimentoExtrato } from '../../core/services/conta.service';

interface MovimentoView extends MovimentoExtrato {
  diaLabel?: string;
}

@Component({
  selector: 'app-extrato',
  standalone: true,
  imports: [CommonModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="app-shell">
      <header class="topbar">
        <div class="topbar-inner">
          <button class="back-btn" (click)="voltar()">← Voltar</button>
          <div class="brand">
            <div class="brand-mark">B</div>
            <span class="brand-name">Extrato</span>
          </div>
          <button class="icon-btn" (click)="logout()" title="Sair">↪</button>
        </div>
      </header>

      <main class="app-main">
        <section class="resumo">
          <div class="resumo-label">Saldo atual</div>
          <div class="resumo-valor">R$ {{ formatarBrl(saldoAtual()) }}</div>
          <div class="resumo-info">Conta {{ currentUser()?.numeroConta || '—' }} · {{ movimentos().length }} movimento(s)</div>
        </section>

        <div *ngIf="isLoading()" class="empty">Carregando extrato…</div>
        <div *ngIf="errorMessage()" class="alert alert-danger">{{ errorMessage() }}</div>

        <section *ngIf="!isLoading() && movimentos().length === 0 && !errorMessage()" class="empty">
          Nenhuma movimentação ainda.
        </section>

        <section *ngIf="!isLoading() && movimentos().length > 0" class="timeline">
          <ng-container *ngFor="let m of movimentosAgrupados()">
            <div *ngIf="m.diaLabel" class="dia-divider">{{ m.diaLabel }}</div>
            <div class="mov-item">
              <div class="mov-icone" [class.credito]="m.tipo === 'Crédito'" [class.debito]="m.tipo !== 'Crédito'">
                {{ m.tipo === 'Crédito' ? '⬇' : '⬆' }}
              </div>
              <div class="mov-info">
                <div class="mov-titulo">{{ m.descricao || m.tipo }}</div>
                <div class="mov-data">{{ formatarHora(m.data) }}</div>
              </div>
              <div class="mov-valor"
                   [class.credito]="m.tipo === 'Crédito'"
                   [class.debito]="m.tipo !== 'Crédito'">
                {{ m.tipo === 'Crédito' ? '+' : '-' }}R$ {{ formatarBrl(m.valor) }}
              </div>
            </div>
          </ng-container>
        </section>
      </main>
    </div>
  `,
  styles: [`
    :host { display: block; }
    * { box-sizing: border-box; }
    .app-shell { min-height: 100vh; background: #f5f7fb;
      font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif; color: #1a1a1a; }
    .topbar { background: white; border-bottom: 1px solid #ececf0; position: sticky; top: 0; z-index: 10; }
    .topbar-inner { max-width: 720px; margin: 0 auto; padding: 14px 20px;
      display: flex; align-items: center; justify-content: space-between; gap: 10px; }
    .back-btn { background: transparent; border: none; color: #4338ca; font-weight: 600;
      cursor: pointer; padding: 6px 10px; border-radius: 6px; font-size: 14px; }
    .back-btn:hover { background: #f0f4ff; }
    .brand { display: flex; align-items: center; gap: 10px; }
    .brand-mark { width: 32px; height: 32px; border-radius: 8px;
      background: linear-gradient(135deg, #667eea, #764ba2); color: white;
      display: flex; align-items: center; justify-content: center; font-weight: 700; }
    .brand-name { font-weight: 700; font-size: 16px; }
    .icon-btn { background: transparent; border: none; cursor: pointer; font-size: 18px;
      width: 36px; height: 36px; border-radius: 50%; color: #666; }
    .icon-btn:hover { background: #f5f5f5; }
    .app-main { max-width: 720px; margin: 0 auto; padding: 24px 20px 60px;
      display: flex; flex-direction: column; gap: 20px; }
    .resumo { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white; border-radius: 18px; padding: 24px;
      box-shadow: 0 10px 30px rgba(102, 126, 234, 0.25); }
    .resumo-label { font-size: 12px; opacity: 0.85; text-transform: uppercase; letter-spacing: 0.6px; }
    .resumo-valor { font-size: 32px; font-weight: 700; margin-top: 6px; letter-spacing: -0.5px;
      font-variant-numeric: tabular-nums; }
    .resumo-info { font-size: 12px; opacity: 0.8; margin-top: 6px; }
    .dia-divider { font-size: 12px; font-weight: 600; color: #6b7280; text-transform: uppercase;
      letter-spacing: 0.6px; margin: 8px 4px 4px; }
    .timeline { display: flex; flex-direction: column; gap: 2px; }
    .mov-item { background: white; border: 1px solid #ececf0; border-radius: 12px;
      padding: 14px 16px; display: flex; align-items: center; gap: 12px; min-width: 0; }
    .mov-item:hover { border-color: #c7d2fe; }
    .mov-icone { width: 40px; height: 40px; border-radius: 12px;
      display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }
    .mov-icone.credito { background: #d1fae5; color: #047857; }
    .mov-icone.debito { background: #fee2e2; color: #b91c1c; }
    .mov-info { flex: 1; min-width: 0; }
    .mov-titulo { font-size: 14px; font-weight: 500; color: #1a1a1a;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .mov-data { font-size: 12px; color: #9ca3af; margin-top: 2px; }
    .mov-valor { font-size: 14px; font-weight: 700; font-variant-numeric: tabular-nums;
      white-space: nowrap; flex-shrink: 0; text-align: right; }
    .mov-valor.credito { color: #047857; }
    .mov-valor.debito { color: #b91c1c; }
    .empty { padding: 28px; text-align: center; color: #9ca3af; font-size: 14px;
      background: white; border-radius: 14px; border: 1px dashed #e5e7eb; }
    .alert { padding: 12px 16px; border-radius: 8px; font-size: 14px; }
    .alert-danger { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }
  `]
})
export class ExtratoComponent implements OnInit, OnDestroy {
  private readonly authService = inject(AuthService);
  private readonly contaService = inject(ContaService);
  private readonly router = inject(Router);

  readonly currentUser = signal<User | null>(null);
  readonly movimentos = signal<MovimentoExtrato[]>([]);
  readonly saldoAtual = signal(0);
  readonly errorMessage = signal('');
  readonly isLoading = signal(true);

  readonly movimentosAgrupados = computed<MovimentoView[]>(() => {
    let ultimoDia = '';
    return this.movimentos().map(m => {
      const dia = this.formatarDia(m.data);
      const view: MovimentoView = { ...m };
      if (dia !== ultimoDia) {
        view.diaLabel = dia;
        ultimoDia = dia;
      }
      return view;
    });
  });

  private readonly destroy$ = new Subject<void>();

  ngOnInit(): void {
    const user = this.authService.getCurrentUser();
    if (!user) { this.router.navigate(['/login']); return; }
    this.currentUser.set(user);
    this.loadExtrato();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  loadExtrato(): void {
    this.contaService.obterExtrato()
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: r => {
          this.saldoAtual.set(r.saldoAtual ?? 0);
          this.movimentos.set(r.movimentos ?? []);
          this.isLoading.set(false);
        },
        error: () => {
          this.errorMessage.set('Erro ao carregar extrato');
          this.isLoading.set(false);
        }
      });
  }

  voltar(): void { this.router.navigate(['/dashboard']); }
  logout(): void { this.authService.logout(); this.router.navigate(['/login']); }

  formatarBrl(v: number): string {
    return new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v || 0);
  }

  formatarDia(s: string | undefined): string {
    if (!s) return '';
    const iso = s.includes('T') ? s : s.replace(' ', 'T') + 'Z';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return s;
    const hoje = new Date();
    const ontem = new Date(); ontem.setDate(ontem.getDate() - 1);
    const sameDay = (a: Date, b: Date) =>
      a.getDate() === b.getDate() && a.getMonth() === b.getMonth() && a.getFullYear() === b.getFullYear();
    if (sameDay(d, hoje)) return 'Hoje';
    if (sameDay(d, ontem)) return 'Ontem';
    return d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'long', year: 'numeric' });
  }

  formatarHora(s: string | undefined): string {
    if (!s) return '';
    const iso = s.includes('T') ? s : s.replace(' ', 'T') + 'Z';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return s;
    return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  }
}
