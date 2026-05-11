import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, throwError } from 'rxjs';
import { tap, catchError } from 'rxjs/operators';

export interface LoginRequest {
  cpf: string;
  senha: string;
}

export interface LoginResponse {
  token: string;
  nomeTitular: string;
  numeroConta: number;
}

export interface User {
  cpf: string;
  nomeTitular: string;
  numeroConta: number;
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
    return this.http.post<LoginResponse>(`${this.apiUrl}/login`, credentials)
      .pipe(
        tap(response => {
          // Salvar token no localStorage
          localStorage.setItem('token', response.token);
          
          // Atualizar o usuário atual
          const user: User = {
            cpf: credentials.cpf,
            nomeTitular: response.nomeTitular,
            numeroConta: response.numeroConta
          };
          localStorage.setItem('user', JSON.stringify(user));
          this.currentUserSubject.next(user);
          this.isAuthenticatedSubject.next(true);
        }),
        catchError(error => {
          console.error('Erro ao fazer login:', error);
          return throwError(() => new Error(error.error?.mensagem || 'Erro ao fazer login'));
        })
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
