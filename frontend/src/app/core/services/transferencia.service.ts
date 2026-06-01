import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';

export interface TransferenciaRequest {
  cpfDestino: string;
  valor: number;
  tipo: 'PIX' | 'TED' | 'TEF';
}

export interface TransferenciaResponse {
  id: string;
  correlationId: string;
  status: string;
  tipo: string;
  mensagem: string;
}

@Injectable({ providedIn: 'root' })
export class TransferenciaService {
  private readonly apiUrl = 'http://localhost:5001/api/transferencia';

  constructor(private http: HttpClient) {}

  efetuar(payload: TransferenciaRequest): Observable<TransferenciaResponse> {
    return this.http.post<TransferenciaResponse>(`${this.apiUrl}/efetuar`, payload).pipe(
      catchError(error => {
        console.error('Erro ao efetuar transferência:', error);
        return throwError(() => new Error(error.error?.mensagem || 'Erro ao efetuar transferência'));
      })
    );
  }
}
