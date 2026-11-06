import { NgModule } from '@angular/core';
import { PreloadAllModules, RouterModule, Routes } from '@angular/router';
import { ShellComponent } from './layout/shell.component';

const routes: Routes = [
  {
    path: '',
    redirectTo: 'login',
    pathMatch: 'full'
  },
  {
    path: 'login',
    loadChildren: () => import('./features/auth/login/login.module').then( m => m.LoginPageModule)
  },
  {
    path: 'register',
    loadChildren: () => import('./features/auth/register/register.module').then( m => m.RegisterPageModule)
  },
  {
    path: 'verify-email',
    loadChildren: () => import('./features/verify-email/verify-email.module').then( m => m.VerifyEmailPageModule)
  },
  {
    path: 'onboarding',
    loadChildren: () => import('./features/onboarding/onboarding.module').then( m => m.OnboardingPageModule)
  },
  // Pantallas internas: comparten la estructura (barra lateral, buscador, panel de mensajes)
  {
    path: '',
    component: ShellComponent,
    children: [
      {
        path: 'dashboard',
        loadChildren: () => import('./features/dashboard/dashboard.module').then( m => m.DashboardPageModule)
      },
      {
        path: 'matches',
        loadChildren: () => import('./features/matches/matches.module').then( m => m.MatchesPageModule)
      },
      {
        path: 'messages',
        loadChildren: () => import('./features/messages/messages.module').then( m => m.MessagesPageModule)
      },
      {
        path: 'profile',
        loadChildren: () => import('./features/profile/profile.module').then( m => m.ProfilePageModule)
      },
      {
        path: 'settings',
        loadChildren: () => import('./features/settings/settings.module').then( m => m.SettingsPageModule)
      },
    ]
  },
  { path: '**', redirectTo: 'login' },
];

@NgModule({
  imports: [
    RouterModule.forRoot(routes, { preloadingStrategy: PreloadAllModules })
  ],
  exports: [RouterModule]
})
export class AppRoutingModule { }
