import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { AuthService, User } from '../../core/services/auth.service';
import { ContaService } from '../../core/services/conta.service';
import { ButtonComponent } from '../../shared/components/button/button.component';
import { CurrencyBrlPipe } from '../../shared/pipes/currency-brl.pipe';
import { DateBrPipe } from '../../shared/pipes/date-br.pipe';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    ButtonComponent,
    CurrencyBrlPipe,
    DateBrPipe
  ],
  template: `
    <div class="dashboard-container">
      <nav class="navbar">
        <div class="navbar-brand">
          <h1>BankMore</h1>
        </div>
        <div class="navbar-menu">
          <span class="user-info">Bem-vindo, {{ currentUser?.nomeTitular }}</span>
          <button class="btn-logout" (click)="logout()">Sair</button>
        </div>
      </nav>

      <div class="dashboard-content">
        <div class="card card-saldo">
          <h2>Saldo</h2>
          <div class="saldo-value">
            {{ saldo | currencyBrl }}
          </div>
          <p class="conta-info">Conta: {{ currentUser?.numeroConta }}</p>
        </div>

        <div class="card card-operacoes">
          <h2>Operações</h2>
          <div class="operacoes-buttons">
            <button class="btn btn-primary" (click)="navigateTo('/transferencia')">
              Transferência
            </button>
            <button class="btn btn-secondary" (click)="navigateTo('/extrato')">
              Ver Extrato
            </button>
          </div>
        </div>

        <div *ngIf="errorMessage" class="alert alert-danger">
          {{ errorMessage }}
        </div>

        <div *ngIf="isLoading" class="loading">
          Carregando...
        </div>
      </div>
    </div>
  `,
  styles: [`
    .dashboard-container {
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

    .user-info {
      font-size: 14px;
    }

    .btn-logout {
      background-color: rgba(255, 255, 255, 0.2);
      color: white;
      border: 1px solid white;
      padding: 8px 16px;
      border-radius: 4px;
      cursor: pointer;
      font-size: 14px;
      transition: all 0.3s ease;
    }

    .btn-logout:hover {
      background-color: rgba(255, 255, 255, 0.3);
    }

    .dashboard-content {
      padding: 40px;
      max-width: 1200px;
      margin: 0 auto;
    }

    .card {
      background: white;
      border-radius: 8px;
      padding: 30px;
      margin-bottom: 20px;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    }

    .card h2 {
      margin-top: 0;
      color: #333;
      margin-bottom: 20px;
    }

    .card-saldo {
      text-align: center;
    }

    .saldo-value {
      font-size: 48px;
      font-weight: bold;
      color: #667eea;
      margin: 20px 0;
    }

    .conta-info {
      color: #999;
      margin: 0;
      font-size: 14px;
    }

    .operacoes-buttons {
      display: flex;
      gap: 20px;
      flex-wrap: wrap;
    }

    .btn {
      padding: 12px 24px;
      border: none;
      border-radius: 4px;
      cursor: pointer;
      font-size: 16px;
      font-weight: 600;
      transition: all 0.3s ease;
    }

    .btn-primary {
      background-color: #667eea;
      color: white;
    }

    .btn-primary:hover {
      background-color: #5568d3;
    }

    .btn-secondary {
      background-color: #6c757d;
      color: white;
    }

    .btn-secondary:hover {
      background-color: #545b62;
    }

    .alert {
      padding: 16px;
      border-radius: 4px;
      margin-bottom: 20px;
    }

    .alert-danger {
      background-color: #f8d7da;
      color: #721c24;
      border: 1px solid #f5c6cb;
    }

    .loading {
      text-align: center;
      padding: 40px;
      color: #999;
    }
  `]
})
export class DashboardComponent implements OnInit, OnDestroy {
  currentUser: User | null = null;
  saldo: number = 0;
  errorMessage = '';
  isLoading = true;
  private destroy$ = new Subject<void>();

  constructor(
    private authService: AuthService,
    private contaService: ContaService,
    private router: Router
  ) {}

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
          this.isLoading = false;
        },
        error: (error) => {
          this.errorMessage = 'Erro ao carregar saldo';
          this.isLoading = false;
        }
      });
  }

  navigateTo(route: string): void {
    this.router.navigate([route]);
  }

  logout(): void {
    this.authService.logout();
    this.router.navigate(['/login']);
  }
}
