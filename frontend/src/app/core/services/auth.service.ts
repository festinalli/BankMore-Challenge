import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, throwError } from 'rxjs';
import { tap, catchError, switchMap } from 'rxjs/operators';

export interface LoginRequest {
  cpf: string;
  senha: string;
}

export interface LoginResponse {
  token: string;
  nomeTitular: string;
  numeroConta: number;
}

export interface RegisterRequest {
  nome: string;
  cpf: string;
  senha: string;
  saldoInicial: number;
}

export interface RegisterResponse {
  idContaCorrente: string;
  numeroConta: number;
  nomeTitular: string;
  cpf: string;
}

export interface User {
  cpf: string;
  nomeTitular: string;
  numeroConta: number;
}

/** Remove tudo que não é dígito — backend espera CPF puro de 11 chars. */
export function normalizarCpf(cpf: string): string {
  return (cpf || '').replace(/\D/g, '');
}

/**
 * Valida CPF brasileiro com os 2 dígitos verificadores.
 * Rejeita: tamanho != 11, todos iguais (000…, 111…), DV incorreto.
 * Algoritmo oficial da Receita Federal.
 */
export function validarCpf(cpf: string | null | undefined): boolean {
  const c = normalizarCpf(cpf || '');
  if (c.length !== 11) return false;
  if (/^(\d)\1{10}$/.test(c)) return false;

  const calcDigit = (slice: string, factor: number): number => {
    let sum = 0;
    for (let i = 0; i < slice.length; i++) sum += parseInt(slice[i], 10) * (factor - i);
    const rest = (sum * 10) % 11;
    return rest === 10 ? 0 : rest;
  };

  const d1 = calcDigit(c.slice(0, 9), 10);
  if (d1 !== parseInt(c[9], 10)) return false;
  const d2 = calcDigit(c.slice(0, 10), 11);
  return d2 === parseInt(c[10], 10);
}

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private apiUrl = 'http://localhost:5000/api/contacorrente';
  private currentUserSubject = new BehaviorSubject<User | null>(null);
  public currentUser$ = this.currentUserSubject.asObservable();

  private isAuthenticatedSubject = new BehaviorSubject<boolean>(false);
  public isAuthenticated$ = this.isAuthenticatedSubject.asObservable();

  constructor(private http: HttpClient) {
    this.loadUserFromLocalStorage();
  }

  /**
   * Realiza o login do usuário
   * @param credentials Credenciais de login (CPF e senha)
   * @returns Observable com os dados do usuário e token
   */
  login(credentials: LoginRequest): Observable<LoginResponse> {
    const cpf = normalizarCpf(credentials.cpf);
    return this.http.post<LoginResponse>(`${this.apiUrl}/login`, { cpf, senha: credentials.senha })
      .pipe(
        tap(response => {
          // Salvar token no localStorage
          localStorage.setItem('token', response.token);

          // Atualizar o usuário atual
          const user: User = {
            cpf,
            nomeTitular: response.nomeTitular,
            numeroConta: response.numeroConta
          };
          localStorage.setItem('user', JSON.stringify(user));
          this.currentUserSubject.next(user);
          this.isAuthenticatedSubject.next(true);
        }),
        catchError(error => {
          console.error('Erro ao fazer login:', error);
          const msg = error.error?.mensagem || (error.status === 401
            ? 'CPF ou senha incorretos.'
            : 'Erro ao fazer login.');
          return throwError(() => new Error(msg));
        })
      );
  }

  /**
   * Cadastra uma conta nova e, no sucesso, executa login automático.
   * Backend: POST /api/contacorrente/criar → /login.
   */
  register(data: RegisterRequest): Observable<LoginResponse> {
    const cpf = normalizarCpf(data.cpf);
    const payload = {
      nome: data.nome.trim(),
      cpf,
      senha: data.senha,
      saldoInicial: Math.max(0, data.saldoInicial || 0)
    };
    return this.http.post<RegisterResponse>(`${this.apiUrl}/criar`, payload).pipe(
      catchError(error => {
        const msg = error.error?.mensagem ||
          (error.status === 409 ? 'CPF já cadastrado.' : 'Erro ao cadastrar conta.');
        return throwError(() => new Error(msg));
      }),
      switchMap(() => this.login({ cpf, senha: data.senha }))
    );
  }

  /**
   * Realiza o logout do usuário
   */
  logout(): void {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    this.currentUserSubject.next(null);
    this.isAuthenticatedSubject.next(false);
  }

  /**
   * Obtém o token JWT armazenado
   * @returns Token JWT ou null
   */
  getToken(): string | null {
    return localStorage.getItem('token');
  }

  /**
   * Verifica se o usuário está autenticado
   * @returns true se autenticado, false caso contrário
   */
  isAuthenticated(): boolean {
    return !!this.getToken();
  }

  /**
   * Obtém o usuário atual
   * @returns Usuário atual ou null
   */
  getCurrentUser(): User | null {
    return this.currentUserSubject.value;
  }

  /**
   * Carrega o usuário do localStorage ao inicializar o serviço
   */
  private loadUserFromLocalStorage(): void {
    const token = localStorage.getItem('token');
    const userJson = localStorage.getItem('user');

    if (token && userJson) {
      try {
        const user: User = JSON.parse(userJson);
        this.currentUserSubject.next(user);
        this.isAuthenticatedSubject.next(true);
      } catch (error) {
        console.error('Erro ao carregar usuário do localStorage:', error);
        this.logout();
      }
    }
  }
}
