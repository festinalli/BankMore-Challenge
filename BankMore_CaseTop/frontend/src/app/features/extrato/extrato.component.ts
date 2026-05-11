import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { AuthService, User } from '../../core/services/auth.service';
import { ContaService, Movimento } from '../../core/services/conta.service';
import { ButtonComponent } from '../../shared/components/button/button.component';
import { CurrencyBrlPipe } from '../../shared/pipes/currency-brl.pipe';
import { DateBrPipe } from '../../shared/pipes/date-br.pipe';

@Component({
  selector: 'app-extrato',
  standalone: true,
  imports: [
    CommonModule,
    ButtonComponent,
    CurrencyBrlPipe,
    DateBrPipe
  ],
  template: `
    <div class="extrato-container">
      <nav class="navbar">
        <div class="navbar-brand">
          <h1>BankMore</h1>
        </div>
        <div class="navbar-menu">
          <button class="btn-back" (click)="voltar()">← Voltar</button>
          <button class="btn-logout" (click)="logout()">Sair</button>
        </div>
      </nav>

      <div class="extrato-content">
        <div class="card">
          <h2>Extrato Bancário</h2>
          <p class="conta-info">Conta: {{ currentUser?.numeroConta }}</p>

          <div *ngIf="isLoading" class="loading">
            Carregando extrato...
          </div>

          <div *ngIf="errorMessage" class="alert alert-danger">
            {{ errorMessage }}
          </div>

          <div *ngIf="!isLoading && movimentos.length === 0" class="empty-state">
            <p>Nenhuma movimentação encontrada</p>
          </div>

          <div *ngIf="!isLoading && movimentos.length > 0" class="table-responsive">
            <table class="table">
              <thead>
                <tr>
                  <th>Data</th>
                  <th>Tipo</th>
                  <th>Valor</th>
                </tr>
              </thead>
              <tbody>
                <tr *ngFor="let movimento of movimentos" [ngClass]="'tipo-' + movimento.tipomovimento.toLowerCase()">
                  <td>{{ movimento.datamovimento | dateBr }}</td>
                  <td>{{ movimento.tipomovimento }}</td>
                  <td [ngClass]="movimento.tipomovimento === 'Crédito' ? 'positivo' : 'negativo'">
                    {{ movimento.tipomovimento === 'Crédito' ? '+' : '-' }} {{ movimento.valor | currencyBrl }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [`
    .extrato-container {
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

    .extrato-content {
      padding: 40px;
      max-width: 900px;
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
      margin-bottom: 10px;
    }

    .conta-info {
      color: #999;
      margin: 0 0 20px 0;
      font-size: 14px;
    }

    .loading {
      text-align: center;
      padding: 40px;
      color: #999;
    }

    .empty-state {
      text-align: center;
      padding: 40px;
      color: #999;
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

    .table-responsive {
      overflow-x: auto;
    }

    .table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 20px;
    }

    .table thead {
      background-color: #f5f5f5;
      border-bottom: 2px solid #ddd;
    }

    .table th {
      padding: 12px;
      text-align: left;
      font-weight: 600;
      color: #333;
    }

    .table td {
      padding: 12px;
      border-bottom: 1px solid #ddd;
    }

    .table tbody tr:hover {
      background-color: #f9f9f9;
    }

    .positivo {
      color: #28a745;
      font-weight: 600;
    }

    .negativo {
      color: #dc3545;
      font-weight: 600;
    }

    .tipo-crédito {
      background-color: rgba(40, 167, 69, 0.05);
    }

    .tipo-débito {
      background-color: rgba(220, 53, 69, 0.05);
    }
  `]
})
export class ExtratoComponent implements OnInit, OnDestroy {
  currentUser: User | null = null;
  movimentos: Movimento[] = [];
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

    this.loadExtrato();
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
  }

  loadExtrato(): void {
    if (!this.currentUser) return;

    this.contaService.obterExtrato()
      .pipe(takeUntil(this.destroy$))
      .subscribe({
        next: (response) => {
          this.movimentos = response.movimentos || [];
          this.isLoading = false;
        },
        error: (error) => {
          this.errorMessage = 'Erro ao carregar extrato';
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
