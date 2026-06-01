import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators, AbstractControl } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService, normalizarCpf, validarCpf } from '../../core/services/auth.service';
import { toSignal } from '@angular/core/rxjs-interop';
import { startWith } from 'rxjs/operators';

@Component({
  selector: 'app-register',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="login-container">
      <div class="login-card">
        <h1>BankMore</h1>
        <p class="subtitle">Abra sua conta em segundos</p>

        <form [formGroup]="form" (ngSubmit)="onSubmit()">
          <div class="form-group">
            <label for="nome">Nome completo</label>
            <input id="nome" type="text" formControlName="nome"
                   placeholder="Como aparece no documento" class="form-control" />
            <small *ngIf="invalid('nome')" class="error-text">Nome obrigatório (mín. 3 letras)</small>
          </div>

          <div class="form-group">
            <label for="cpf">CPF</label>
            <input id="cpf" type="text" formControlName="cpf"
                   placeholder="000.000.000-00" maxlength="14"
                   (input)="formatarCpf($event)" class="form-control" />
            <small *ngIf="invalid('cpf')" class="error-text">CPF inválido (dígitos verificadores não conferem)</small>
          </div>

          <div class="form-group">
            <label for="senha">Senha</label>
            <input id="senha" type="password" formControlName="senha"
                   placeholder="Mínimo 6 caracteres" class="form-control" />
            <small *ngIf="invalid('senha')" class="error-text">Senha deve ter no mínimo 6 caracteres</small>
          </div>

          <div class="form-group">
            <label for="senhaConfirmacao">Confirmar senha</label>
            <input id="senhaConfirmacao" type="password" formControlName="senhaConfirmacao"
                   placeholder="Digite novamente" class="form-control" />
            <small *ngIf="senhasDiferem()" class="error-text">As senhas não coincidem</small>
          </div>

          <div class="form-group">
            <label for="saldoInicial">Saldo inicial (R$)</label>
            <input id="saldoInicial" type="number" formControlName="saldoInicial"
                   min="0" step="0.01" placeholder="0,00" class="form-control" />
            <small class="hint">Apenas para teste — em produção seria zero.</small>
          </div>

          <div *ngIf="errorMessage()" class="alert alert-danger">{{ errorMessage() }}</div>

          <button type="submit" [disabled]="form.invalid || senhasDiferem() || isLoading()"
                  class="btn btn-primary btn-block">
            {{ isLoading() ? 'Criando conta...' : 'Criar minha conta' }}
          </button>
        </form>

        <p class="register-link">
          Já tem conta? <a routerLink="/login">Entrar</a>
        </p>
      </div>
    </div>
  `,
  styles: [`
    .login-container { display:flex; justify-content:center; align-items:center; min-height:100vh;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px 0; }
    .login-card { background:white; padding:40px; border-radius:8px;
      box-shadow:0 10px 25px rgba(0,0,0,0.2); width:100%; max-width:420px; }
    h1 { text-align:center; color:#333; margin-bottom:8px; font-size:32px; }
    .subtitle { text-align:center; color:#999; margin-bottom:30px; font-size:14px; }
    .form-group { margin-bottom:16px; display:flex; flex-direction:column; }
    label { margin-bottom:6px; font-weight:600; color:#333; font-size:14px; }
    .form-control { padding:12px; border:1px solid #ddd; border-radius:4px; font-size:14px; }
    .form-control:focus { outline:none; border-color:#667eea; box-shadow:0 0 0 3px rgba(102,126,234,0.1); }
    .error-text { color:#dc3545; margin-top:4px; font-size:12px; }
    .hint { color:#999; margin-top:4px; font-size:11px; }
    .alert { padding:12px; border-radius:4px; margin-bottom:20px; font-size:14px; }
    .alert-danger { background:#f8d7da; color:#721c24; border:1px solid #f5c6cb; }
    .btn { padding:12px; border:none; border-radius:4px; cursor:pointer; font-size:16px;
      font-weight:600; width:100%; margin-top:8px; }
    .btn-primary { background:#667eea; color:white; }
    .btn-primary:hover:not(:disabled) { background:#5568d3; }
    .btn:disabled { opacity:0.6; cursor:not-allowed; }
    .register-link { text-align:center; margin-top:20px; color:#666; font-size:14px; }
    .register-link a { color:#667eea; text-decoration:none; font-weight:600; cursor:pointer; }
    .register-link a:hover { text-decoration:underline; }
  `]
})
export class RegisterComponent {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly isLoading = signal(false);
  readonly errorMessage = signal('');

  readonly form: FormGroup = this.fb.group({
    nome: ['', [Validators.required, Validators.minLength(3)]],
    cpf: ['', [Validators.required, this.cpfValidator]],
    senha: ['', [Validators.required, Validators.minLength(6)]],
    senhaConfirmacao: ['', [Validators.required]],
    saldoInicial: [0, [Validators.min(0)]]
  });

  // Signal derivado do valueChanges do form pra senhasDiferem ser reativo sob OnPush.
  private readonly formValue = toSignal(
    this.form.valueChanges.pipe(startWith(this.form.value)),
    { initialValue: this.form.value }
  );

  readonly senhasDiferem = computed(() => {
    const v = this.formValue();
    return !!v.senhaConfirmacao && v.senha !== v.senhaConfirmacao;
  });

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
    this.form.get('cpf')?.setValue(out, { emitEvent: true });
  }

  onSubmit(): void {
    if (this.form.invalid || this.senhasDiferem()) return;
    this.isLoading.set(true);
    this.errorMessage.set('');

    const v = this.form.value;
    this.auth.register({
      nome: v.nome,
      cpf: v.cpf,
      senha: v.senha,
      saldoInicial: Number(v.saldoInicial) || 0
    }).subscribe({
      next: () => this.router.navigate(['/dashboard']),
      error: err => {
        this.errorMessage.set(err.message || 'Erro ao criar conta.');
        this.isLoading.set(false);
      }
    });
  }
}
