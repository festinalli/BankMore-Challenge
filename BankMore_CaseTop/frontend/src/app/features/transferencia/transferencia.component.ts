import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule, ReactiveFormsModule, FormBuilder, FormGroup, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { AuthService, User } from '../../core/services/auth.service';
import { ContaService } from '../../core/services/conta.service';
import { TransferenciaService } from '../../core/services/transferencia.service';
import { ButtonComponent } from '../../shared/components/button/button.component';
import { InputComponent } from '../../shared/components/input/input.component';
import { CurrencyBrlPipe } from '../../shared/pipes/currency-brl.pipe';

@Component({
  selector: 'app-transferencia',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    ButtonComponent,
    InputComponent,
    CurrencyBrlPipe
  ],
  template: `
    <div class="transferencia-container">
      <nav class="navbar">
        <div class="navbar-brand">
          <h1>BankMore</h1>
        </div>
        <div class="navbar-menu">
          <button class="btn-back" (click)="voltar()">← Voltar</button>
          <button class="btn-logout" (click)="logout()">Sair</button>
        </div>
      </nav>

      <div class="transferencia-content">
        <div class="card">
          <h2>Realizar Transferência</h2>
          
          <div class="saldo-info">
            <p>Saldo disponível: {{ saldo | currencyBrl }}</p>
          </div>

          <form [formGroup]="transferenciaForm" (ngSubmit)="onSubmit()">
            <div class="form-group">
              <label for="cpf-destino">CPF do Destinatário</label>
              <input
                id="cpf-destino"
                type="text"
                placeholder="000.000.000-00"
                formControlName="cpfDestino"
                class="form-control"
              />
              <small *ngIf="transferenciaForm.get('cpfDestino')?.invalid && transferenciaForm.get('cpfDestino')?.touched" class="error-text">
                CPF é obrigatório
              </small>
            </div>

            <div class="form-group">
              <label for="valor">Valor</label>
              <input
                id="valor"
                type="number"
                placeholder="0,00"
                formControlName="valor"
                class="form-control"
              />
              <small *ngIf="transferenciaForm.get('valor')?.invalid && transferenciaForm.get('valor')?.touched" class="error-text">
                Valor deve ser maior que 0
              </small>
            </div>

            <div class="form-group">
              <label for="tipo">Tipo de Transferência</label>
              <select formControlName="tipo" class="form-control">
                <option value="">Selecione...</option>
                <option value="PIX">PIX (sem tarifa)</option>
                <option value="TED">TED (tarifa R$ 4,00)</option>
                <option value="TEF">TEF (tarifa R$ 1,00)</option>
              </select>
              <small *ngIf="transferenciaForm.get('tipo')?.invalid && transferenciaForm.get('tipo')?.touched" class="error-text">
                Tipo é obrigatório
              </small>
            </div>

            <div *ngIf="errorMessage" class="alert alert-danger">
              {{ errorMessage }}
            </div>

            <div *ngIf="successMessage" class="alert alert-success">
              {{ successMessage }}
            </div>

            <button
              type="submit"
              [disabled]="transferenciaForm.invalid || isLoading"
              class="btn btn-primary btn-block"
            >
              {{ isLoading ? 'Processando...' : 'Transferir' }}
            </button>
          </form>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .transferencia-container {
      min-height: 100vh;
      background-color: #f5f5f5;
    }

    .navbar {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      padding: 20px 40px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
    }

    .navbar-brand h1 {
      margin: 0;
      font-size: 24px;
    }

    .navbar-menu {
      display: flex;
      align-items: center;
      gap: 20px;
    }

    .btn-back, .btn-logout {
      background-color: rgba(255, 255, 255, 0.2);
      color: white;
      border: 1px solid white;
      padding: 8px 16px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
      transition: all 0.3s ease;
    }

    .btn-back:hover, .btn-logout:hover {
      background-color: rgba(255, 255, 255, 0.3);
    }

    .transferencia-content {
      padding: 40px;
      max-width: 600px;
      margin: 0 auto;
    }

    .card {
      background: white;
      border-radius: 8px;
      padding: 30px;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    }

    .card h2 {
      margin-top: 0;
      color: #333;
      margin-bottom: 20px;
    }

    .saldo-info {
      background-color: #f0f7ff;
      padding: 16px;
      border-radius: 4px;
      margin-bottom: 20px;
      border-left: 4px solid #667eea;
    }

    .saldo-info p {
      margin: 0;
      color: #333;
      font-weight: 600;
    }

    .form-group {
      margin-bottom: 20px;
      display: flex;
      flex-direction: column;
    }

    label {
      margin-bottom: 8px;
      font-weight: 600;
      color: #333;
    }

    .form-control {
      padding: 12px;
      border: 1px solid #ddd;
      border-radius: 4px;
      font-size: 14px;
      transition: border-color 0.3s ease;
    }

    .form-control:focus {
      outline: none;
      border-color: #667eea;
      box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
    }

    .error-text {
      color: #dc3545;
      margin-top: 4px;
      font-size: 12px;
    }

    .alert {
      padding: 12px;
      border-radius: 4px;
      margin-bottom: 20px;
      font-size: 14px;
    }

    .alert-danger {
      background-color: #f8d7da;
      color: #721c24;
      border: 1px solid #f5c6cb;
    }

    .alert-success {
      background-color: #d4edda;
      color: #155724;
      border: 1px solid #c3e6cb;
    }

    .btn {
      padding: 12px;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 16px;
      font-weight: 600;
      transition: all 0.3s ease;
      width: 100%;
    }

    .btn-primary {
      background-color: #667eea;
      color: white;
    }

    .btn-primary:hover:not(:disabled) {
      background-color: #5568d3;
    }

    .btn:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }

    .btn-block {
      width: 100%;
    }
  `]
})
export class TransferenciaComponent implements OnInit, OnDestroy {
  transferenciaForm: FormGroup;
  currentUser: User | null = null;
  saldo: number = 0;
  errorMessage = '';
  successMessage = '';
  isLoading = false;
  private destroy$ = new Subject<void>();

  constructor(
    private formBuilder: FormBuilder,
    private authService: AuthService,
    private contaService: ContaService,
    private transferenciaService: TransferenciaService,
    private router: Router
  ) {
    this.transferenciaForm = this.formBuilder.group({
      cpfDestino: ['', [Validators.required]],
      valor: ['', [Validators.required, Validators.min(0.01)]],
      tipo: ['', [Validators.required]]
    });
  }

  ngOnInit(): void {
    this.currentUser = this.authService.getCurrentUser();
    if (!this.currentUser) {
      this.router.navigate(['/login']);
      return;
    }

    this.loadSaldo();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  loadSaldo(): void {
    if (!this.currentUser) return;

    this.contaService.obterSaldo()
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (response) => {
          this.saldo = response.saldo;
        },
        error: (error) => {
          this.errorMessage = 'Erro ao carregar saldo';
        }
      });
  }

  onSubmit(): void {
    if (this.transferenciaForm.invalid) {
      return;
    }

    this.isLoading = true;
    this.errorMessage = '';
    this.successMessage = '';

    const formValue = this.transferenciaForm.value;
    // CPF origem NÃO vai mais no body — backend pega do JWT.
    const payload = {
      cpfDestino: formValue.cpfDestino,
      tipo: formValue.tipo as 'PIX' | 'TED' | 'TEF',
      valor: parseFloat(formValue.valor)
    };

    this.transferenciaService.efetuar(payload)
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (response) => {
          this.successMessage = `Transferência aceita — protocolo ${response.id.slice(0, 8)}. Análise de fraude em andamento.`;
          this.transferenciaForm.reset();
          // O saldo só atualiza quando o Worker efetivar (após PyFlink aprovar)
          setTimeout(() => this.loadSaldo(), 2000);
          this.isLoading = false;

          setTimeout(() => this.router.navigate(['/dashboard']), 3000);
        },
        error: (error) => {
          this.errorMessage = error.message || 'Erro ao realizar transferência';
          this.isLoading = false;
        }
      });
  }

  voltar(): void {
    this.router.navigate(['/dashboard']);
  }

  logout(): void {
    this.authService.logout();
    this.router.navigate(['/login']);
  }
}
