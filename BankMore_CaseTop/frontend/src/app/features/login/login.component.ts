import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { AuthService, normalizarCpf } from '../../core/services/auth.service';

@Component({
  selector: 'app-login',
  standalone: true,
  imports: [CommonModule, FormsModule, ReactiveFormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="login-container">
      <div class="login-card">
        <h1>BankMore</h1>
        <p class="subtitle">Sistema Bancário</p>

        <form [formGroup]="loginForm" (ngSubmit)="onSubmit()">
          <div class="form-group">
            <label for="cpf">CPF</label>
            <input id="cpf" type="text" placeholder="000.000.000-00"
                   maxlength="14" formControlName="cpf"
                   (input)="formatarCpf($event)" class="form-control" />
            <small *ngIf="loginForm.get('cpf')?.invalid && loginForm.get('cpf')?.touched" class="error-text">
              CPF é obrigatório
            </small>
          </div>

          <div class="form-group">
            <label for="senha">Senha</label>
            <input id="senha" type="password" placeholder="Digite sua senha"
                   formControlName="senha" class="form-control" />
            <small *ngIf="loginForm.get('senha')?.invalid && loginForm.get('senha')?.touched" class="error-text">
              Senha é obrigatória
            </small>
          </div>

          <div *ngIf="errorMessage()" class="alert alert-danger">{{ errorMessage() }}</div>

          <button type="submit" [disabled]="loginForm.invalid || isLoading()"
                  class="btn btn-primary btn-block">
            {{ isLoading() ? 'Autenticando...' : 'Entrar' }}
          </button>
        </form>

        <p class="register-link">
          Não tem conta? <a routerLink="/register">Cadastre-se aqui</a>
        </p>
        <p class="hint-seed">
          Demo: <code>111.111.111-11</code> / <code>senha123</code> (Alice, R$ 500.000)
        </p>
      </div>
    </div>
  `,
  styles: [`
    .login-container { display: flex; justify-content: center; align-items: center;
      min-height: 100vh; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }
    .login-card { background: white; padding: 40px; border-radius: 8px;
      box-shadow: 0 10px 25px rgba(0,0,0,0.2); width: 100%; max-width: 400px; }
    h1 { text-align: center; color: #333; margin-bottom: 8px; font-size: 32px; }
    .subtitle { text-align: center; color: #999; margin-bottom: 30px; font-size: 14px; }
    .form-group { margin-bottom: 20px; display: flex; flex-direction: column; }
    label { margin-bottom: 8px; font-weight: 600; color: #333; }
    .form-control { padding: 12px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px; }
    .form-control:focus { outline: none; border-color: #667eea; box-shadow: 0 0 0 3px rgba(102,126,234,0.1); }
    .error-text { color: #dc3545; margin-top: 4px; font-size: 12px; }
    .alert { padding: 12px; border-radius: 4px; margin-bottom: 20px; font-size: 14px; }
    .alert-danger { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
    .btn { padding: 12px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px;
      font-weight: 600; width: 100%; }
    .btn-primary { background: #667eea; color: white; }
    .btn-primary:hover:not(:disabled) { background: #5568d3; }
    .btn:disabled { opacity: 0.6; cursor: not-allowed; }
    .register-link { text-align: center; margin-top: 20px; color: #666; font-size: 14px; }
    .register-link a { color: #667eea; text-decoration: none; font-weight: 600; cursor: pointer; }
    .register-link a:hover { text-decoration: underline; }
    .hint-seed { text-align: center; margin-top: 8px; color: #aaa; font-size: 12px; }
    .hint-seed code { background: #f5f5f5; padding: 1px 6px; border-radius: 3px; color: #555; }
  `]
})
export class LoginComponent {
  private readonly fb = inject(FormBuilder);
  private readonly authService = inject(AuthService);
  private readonly router = inject(Router);

  readonly isLoading = signal(false);
  readonly errorMessage = signal('');

  readonly loginForm: FormGroup = this.fb.group({
    cpf: ['', [Validators.required]],
    senha: ['', [Validators.required, Validators.minLength(6)]]
  });

  formatarCpf(event: Event) {
    const input = event.target as HTMLInputElement;
    const digits = normalizarCpf(input.value).slice(0, 11);
    let out = digits;
    if (digits.length > 3)  out = digits.slice(0, 3) + '.' + digits.slice(3);
    if (digits.length > 6)  out = digits.slice(0, 3) + '.' + digits.slice(3, 6) + '.' + digits.slice(6);
    if (digits.length > 9)  out = digits.slice(0, 3) + '.' + digits.slice(3, 6) + '.' + digits.slice(6, 9) + '-' + digits.slice(9);
    input.value = out;
    this.loginForm.get('cpf')?.setValue(out, { emitEvent: false });
  }

  onSubmit(): void {
    if (this.loginForm.invalid) return;
    this.isLoading.set(true);
    this.errorMessage.set('');

    const credentials = this.loginForm.value;
    this.authService.login(credentials).subscribe({
      next: () => this.router.navigate(['/dashboard']),
      error: (error) => {
        this.errorMessage.set(error.message || 'Erro ao fazer login. Verifique suas credenciais.');
        this.isLoading.set(false);
      }
    });
  }
}
