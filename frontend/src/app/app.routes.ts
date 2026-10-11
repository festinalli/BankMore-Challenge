import { Routes } from '@angular/router';
import { LoginComponent } from './features/login/login.component';
import { RegisterComponent } from './features/register/register.component';
import { DashboardComponent } from './features/dashboard/dashboard.component';
import { TransferenciaComponent } from './features/transferencia/transferencia.component';
import { ExtratoComponent } from './features/extrato/extrato.component';
import { FraudeOpsComponent } from './features/ops/fraude.component';
import { AuthGuard } from './core/guards/auth.guard';

export const routes: Routes = [
  {
    path: '',
    redirectTo: '/dashboard',
    pathMatch: 'full'
  },
  {
    path: 'login',
    component: LoginComponent
  },
  {
    path: 'register',
    component: RegisterComponent
  },
  {
    path: 'dashboard',
    component: DashboardComponent,
    canActivate: [AuthGuard]
  },
  {
    path: 'transferencia',
    component: TransferenciaComponent,
    canActivate: [AuthGuard]
  },
  {
    path: 'extrato',
    component: ExtratoComponent,
    canActivate: [AuthGuard]
  },
  {
    path: 'ops/investigacao',
    loadComponent: () => import('./features/ops/investigation.component').then(m => m.InvestigationComponent)
  },
  {
    path: 'ops/jev',
    title: 'Antifraude Pix com Jev · BankMore',
    loadComponent: () => import('./features/ops/jev.component').then(m => m.JevComponent)
  },
  {
    path: 'ops/fraude',
    component: FraudeOpsComponent
  },
  {
    path: '**',
    redirectTo: '/dashboard'
  }
];
