import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';

export interface SaldoResponse {
  numeroConta: number;
  nomeTitular: string;
  dataHora: string;
  saldo: number;
}

export interface MovimentoExtrato {
  data: string;
  tipo: string;        // "Crédito" | "Débito"
  valor: number;
  descricao: string;
}

export interface ExtratoResponse {
  nomeTitular: string;
  saldoAtual: number;
  movimentos: MovimentoExtrato[];
}

export interface MovimentacaoRequest {
  /** "C" para crédito (depósito), "D" para débito (saque). NÃO é tipo de transferência. */
  tipo: 'C' | 'D';
  valor: number;
  requestId?: string;
}

@Injectable({ providedIn: 'root' })
export class ContaService {
  private readonly apiUrl = 'http://localhost:5000/api/contacorrente';

  constructor(private http: HttpClient) {}

  /** Saldo do usuário autenticado — CPF vem do JWT, não da URL. */
  obterSaldo(): Observable<SaldoResponse> {
    return this.http.get<SaldoResponse>(`${this.apiUrl}/saldo`).pipe(
      catchError(error => {
        console.error('Erro ao obter saldo:', error);
        return throwError(() => new Error(error.error?.mensagem || 'Erro ao obter saldo'));
      })
    );
  }

  /** Extrato do usuário autenticado. */
  obterExtrato(): Observable<ExtratoResponse> {
    return this.http.get<ExtratoResponse>(`${this.apiUrl}/extrato`).pipe(
      catchError(error => {
        console.error('Erro ao obter extrato:', error);
        return throwError(() => new Error(error.error?.mensagem || 'Erro ao obter extrato'));
      })
    );
  }

  /** Depósito ('C') ou saque ('D'). Para TRANSFERIR, usar TransferenciaService. */
  movimentar(movimentacao: MovimentacaoRequest): Observable<void> {
    return this.http.post<void>(`${this.apiUrl}/movimentar`, movimentacao).pipe(
      catchError(error => {
        console.error('Erro ao movimentar:', error);
        return throwError(() => new Error(error.error?.mensagem || 'Erro ao realizar movimentação'));
      })
    );
  }
}
