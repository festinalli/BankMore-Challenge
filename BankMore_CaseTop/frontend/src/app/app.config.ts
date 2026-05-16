import { ApplicationConfig, provideBrowserGlobalErrorListeners, provideZonelessChangeDetection } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient, withInterceptorsFromDi, HTTP_INTERCEPTORS } from '@angular/common/http';
import { routes } from './app.routes';
import { JwtInterceptor } from './core/interceptors/jwt.interceptor';
import { AuthService } from './core/services/auth.service';
import { ContaService } from './core/services/conta.service';
import { AuthGuard } from './core/guards/auth.guard';

// Zoneless change detection (Angular 21+). Componentes usam `signal()` para reatividade.
// Reasons:
//  - Bundle menor (sem Zone.js ~80kB)
//  - Sem monkey-patching de globais (Promise/setTimeout/addEventListener)
//  - Change detection explícita e previsível
//  - Roadmap oficial do time Angular
export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideZonelessChangeDetection(),
    provideRouter(routes),
    provideHttpClient(withInterceptorsFromDi()),
    AuthService,
    ContaService,
    AuthGuard,
    {
      provide: HTTP_INTERCEPTORS,
      useClass: JwtInterceptor,
      multi: true
    }
  ]
};
