import { Injectable } from '@angular/core';
import {
  HttpRequest,
  HttpHandler,
  HttpEvent,
  HttpInterceptor,
  HttpErrorResponse
} from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { AuthService } from '../services/auth.service';
import { Router } from '@angular/router';

@Injectable()
export class JwtInterceptor implements HttpInterceptor {
  constructor(
    private authService: AuthService,
    private router: Router
  ) {}

  intercept(request: HttpRequest<unknown>, next: HttpHandler): Observable<HttpEvent<unknown>> {
    // Obter o token do AuthService
    const token = this.authService.getToken();

    // Se existe um token, adicionar ao cabeçalho Authorization
    if (token) {
      request = request.clone({
        setHeaders: {
          Authorization: `Bearer ${token}`
        }
      });
    }

    // Adicionar Content-Type se não estiver presente
    if (!request.headers.has('Content-Type')) {
      request = request.clone({
        setHeaders: {
          'Content-Type': 'application/json'
        }
      });
    }

    return next.handle(request).pipe(
      catchError((error: HttpErrorResponse) => {
        // Se receber 401 (Unauthorized), fazer logout
        if (error.status === 401) {
          this.authService.logout();
          this.router.navigate(['/login']);
        }

        // Se receber 403 (Forbidden), redirecionar para home
        if (error.status === 403) {
          this.router.navigate(['/']);
        }

        return throwError(() => error);
      })
    );
  }
}
