import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators, AbstractControl } from '@angular/forms';
import { Router } from '@angular/router';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { AuthService, User, normalizarCpf, validarCpf } from '../../core/services/auth.service';
import { ContaService } from '../../core/services/conta.service';
import { TransferenciaService } from '../../core/services/transferencia.service';

@Component({
  selector: 'app-transferencia',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="app-shell">
      <header class="topbar">
        <div class="topbar-inner">
          <button class="back-btn" (click)="voltar()">← Voltar</button>
          <div class="brand">
            <div class="brand-mark">B</div>
            <span class="brand-name">Transferir</span>
          </div>
          <button class="icon-btn" (click)="logout()" title="Sair">↪</button>
        </div>
      </header>

      <main class="app-main">
        <div class="saldo-pill">
          <span class="saldo-label">Saldo disponível</span>
          <span class="saldo-valor">R$ {{ formatarBrl(saldo()) }}</span>
        </div>

        <form class="card" [formGroup]="form" (ngSubmit)="onSubmit()">
          <h1 class="card-title">Nova transferência</h1>

          <div class="form-group">
            <label>Tipo</label>
            <div class="tipo-grid">
              <label class="tipo-option" [class.selected]="form.get('tipo')?.value === 'PIX'">
                <input type="radio" formControlName="tipo" value="PIX" />
                <div class="tipo-icon">⚡</div>
                <div class="tipo-name">PIX</div>
                <div class="tipo-fee">grátis</div>
              </label>
              <label class="tipo-option" [class.selected]="form.get('tipo')?.value === 'TED'">
                <input type="radio" formControlName="tipo" value="TED" />
                <div class="tipo-icon">🏦</div>
                <div class="tipo-name">TED</div>
                <div class="tipo-fee">R$ 4,00</div>
              </label>
              <label class="tipo-option" [class.selected]="form.get('tipo')?.value === 'TEF'">
                <input type="radio" formControlName="tipo" value="TEF" />
                <div class="tipo-icon">💳</div>
                <div class="tipo-name">TEF</div>
                <div class="tipo-fee">R$ 1,00</div>
              </label>
            </div>
            <small *ngIf="invalid('tipo')" class="error-text">Escolha um tipo</small>
          </div>

          <div class="form-group">
            <label for="cpf-destino">CPF do destinatário</label>
            <input id="cpf-destino" type="text" placeholder="000.000.000-00"
                   maxlength="14" formControlName="cpfDestino"
                   (input)="formatarCpf($event)" class="form-control" />
            <small *ngIf="invalid('cpfDestino')" class="error-text">CPF inválido (dígitos verificadores)</small>
          </div>

          <div class="form-group">
            <label for="valor">Valor (R$)</label>
            <input id="valor" type="number" step="0.01" min="0.01" placeholder="0,00"
                   formControlName="valor" class="form-control form-control-big" />
            <small *ngIf="invalid('valor')" class="error-text">Valor deve ser maior que 0</small>
          </div>

          <div *ngIf="errorMessage()" class="alert alert-danger">{{ errorMessage() }}</div>
          <div *ngIf="successMessage()" class="alert alert-success">{{ successMessage() }}</div>

          <button type="submit" [disabled]="form.invalid || isLoading()" class="btn btn-primary">
            {{ isLoading() ? 'Enviando…' : 'Transferir' }}
          </button>

          <p class="hint">
            Toda transferência passa pelo motor antifraude em tempo real.<br>
            Apenas saiu da sua conta após aprovação — você verá em <em>Atividade recente</em>.
          </p>
        </form>
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
    .app-main { max-width: 560px; margin: 0 auto; padding: 24px 20px 60px;
      display: flex; flex-direction: column; gap: 18px; }
    .saldo-pill { background: white; padding: 14px 18px; border-radius: 14px;
      border: 1px solid #ececf0; display: flex; justify-content: space-between; align-items: center; }
    .saldo-label { color: #6b7280; font-size: 12px; text-transform: uppercase; letter-spacing: 0.6px; }
    .saldo-valor { font-weight: 700; font-variant-numeric: tabular-nums; font-size: 16px; }
    .card { background: white; border-radius: 18px; padding: 28px 24px;
      box-shadow: 0 4px 18px rgba(0,0,0,0.04); display: flex; flex-direction: column; gap: 20px; }
    .card-title { margin: 0; font-size: 20px; font-weight: 700; }
    .form-group { display: flex; flex-direction: column; gap: 8px; }
    label { font-weight: 600; color: #374151; font-size: 13px; }
    .form-control { padding: 12px 14px; border: 1px solid #e5e7eb; border-radius: 10px;
      font-size: 14px; font-family: inherit; transition: border-color 0.2s; }
    .form-control:focus { outline: none; border-color: #667eea; box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.12); }
    .form-control-big { font-size: 22px; font-weight: 700; padding: 14px; font-variant-numeric: tabular-nums; }
    .error-text { color: #dc2626; font-size: 12px; }
    .tipo-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
    .tipo-option { position: relative; border: 1.5px solid #e5e7eb; border-radius: 12px;
      padding: 14px 8px; text-align: center; cursor: pointer; transition: all 0.15s; }
    .tipo-option input { position: absolute; opacity: 0; pointer-events: none; }
    .tipo-option:hover { border-color: #c7d2fe; }
    .tipo-option.selected { border-color: #667eea; background: #f0f4ff; }
    .tipo-icon { font-size: 22px; margin-bottom: 4px; }
    .tipo-name { font-weight: 700; font-size: 13px; }
    .tipo-fee { font-size: 11px; color: #9ca3af; margin-top: 2px; }
    .tipo-option.selected .tipo-fee { color: #4338ca; }
    .btn { padding: 14px; border: none; border-radius: 10px; cursor: pointer;
      font-size: 15px; font-weight: 700; transition: all 0.2s; }
    .btn-primary { background: linear-gradient(135deg, #667eea, #764ba2); color: white; }
    .btn-primary:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 8px 16px rgba(102,126,234,0.3); }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .alert { padding: 12px 16px; border-radius: 10px; font-size: 13px; }
    .alert-danger { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }
    .alert-success { background: #f0fdf4; color: #166534; border: 1px solid #bbf7d0; }
    .hint { margin: 0; color: #9ca3af; font-size: 12px; line-height: 1.5; text-align: center; }
  `]
})
export class TransferenciaComponent implements OnInit, OnDestroy {
  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  private readonly contaService = inject(ContaService);
  private readonly transferenciaService = inject(TransferenciaService);
  private readonly router = inject(Router);

  readonly currentUser = signal<User | null>(null);
  readonly saldo = signal(0);
  readonly errorMessage = signal('');
  readonly successMessage = signal('');
  readonly isLoading = signal(false);

  readonly form: FormGroup = this.fb.group({
    cpfDestino: ['', [Validators.required, this.cpfValidator]],
    valor: ['', [Validators.required, Validators.min(0.01)]],
    tipo: ['PIX', [Validators.required]]
  });

  private readonly destroy$ = new Subject<void>();

  ngOnInit(): void {
    const user = this.authService.getCurrentUser();
    if (!user) { this.router.navigate(['/login']); return; }
    this.currentUser.set(user);
    this.loadSaldo();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  cpfValidator(control: AbstractControl) {
    return validarCpf(control.value) ? null : { cpfInvalido: true };
  }

  invalid(name: string): boolean {
    const c = this.form.get(name);
    return !!(c && c.invalid && (c.touched || c.dirty));
  }

  formatarCpf(event: Event) {
    const input = event.target as HTMLInputElement;
    const digits = normalizarCpf(input.value).slice(0, 11);
    let out = digits;
    if (digits.length > 3)  out = digits.slice(0, 3) + '.' + digits.slice(3);
    if (digits.length > 6)  out = digits.slice(0, 3) + '.' + digits.slice(3, 6) + '.' + digits.slice(6);
    if (digits.length > 9)  out = digits.slice(0, 3) + '.' + digits.slice(3, 6) + '.' + digits.slice(6, 9) + '-' + digits.slice(9);
    input.value = out;
    this.form.get('cpfDestino')?.setValue(out, { emitEvent: true });
  }

  loadSaldo(): void {
    this.contaService.obterSaldo()
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: r => this.saldo.set(r.saldo),
        error: () => this.errorMessage.set('Erro ao carregar saldo')
      });
  }

  onSubmit(): void {
    if (this.form.invalid) return;
    this.isLoading.set(true);
    this.errorMessage.set('');
    this.successMessage.set('');

    const v = this.form.value;
    const payload = {
      cpfDestino: normalizarCpf(v.cpfDestino),
      tipo: v.tipo as 'PIX' | 'TED' | 'TEF',
      valor: parseFloat(v.valor)
    };

    this.transferenciaService.efetuar(payload)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: response => {
          this.successMessage.set(`Transferência aceita — protocolo ${response.id.slice(0, 8)}. Análise antifraude em andamento.`);
          this.form.reset({ tipo: 'PIX', valor: '', cpfDestino: '' });
          setTimeout(() => this.loadSaldo(), 2000);
          this.isLoading.set(false);
          setTimeout(() => this.router.navigate(['/dashboard']), 2800);
        },
        error: err => {
          this.errorMessage.set(err.message || 'Erro ao realizar transferência');
          this.isLoading.set(false);
        }
      });
  }

  voltar(): void { this.router.navigate(['/dashboard']); }
  logout(): void { this.authService.logout(); this.router.navigate(['/login']); }

  formatarBrl(v: number): string {
    return new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v || 0);
  }
}
