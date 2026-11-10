import { Injectable } from '@angular/core';
import {
  HttpEvent,
  HttpHandler,
  HttpInterceptor,
  HttpRequest,
  HttpErrorResponse,
  HttpContextToken,
} from '@angular/common/http';
import { Observable, throwError, BehaviorSubject } from 'rxjs';
import { catchError, filter, switchMap, take } from 'rxjs/operators';
import { AuthService } from '../services/auth.service';
import { Router } from '@angular/router';

export const IS_AUTH_RETRY = new HttpContextToken<boolean>(() => false);

@Injectable()
export class AuthInterceptor implements HttpInterceptor {
  private isRefreshing = false;
  private refreshTokenSubject = new BehaviorSubject<string | null>(null);

  constructor(private auth: AuthService, private router: Router) {}

  intercept(req: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
    return next.handle(req).pipe(
      catchError((error: HttpErrorResponse) => {
        if (error.status === 401 && !this.isAuthUrl(req.url)) {
          return this.handle401Error(req, next);
        }
        return throwError(() => error);
      })
    );
  }

  private isAuthUrl(url: string): boolean {
    return (
      url.includes('/auth/login') ||
      url.includes('/auth/register') ||
      url.includes('/auth/refresh') ||
      url.includes('/auth/logout') ||
      url.includes('/auth/verify-email')
    );
  }

  private handle401Error(req: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
    // Si ya se intentó una renovación para esta petición y volvió a fallar 401, no reintentar de nuevo
    if (req.context.get(IS_AUTH_RETRY)) {
      this.auth.logout();
      this.router.navigate(['/login']);
      return throwError(() => new Error('Sesión no autorizada tras reintento de renovación.'));
    }

    const refreshToken = this.auth.getRefreshToken();
    if (!refreshToken) {
      this.auth.logout();
      this.router.navigate(['/login']);
      return throwError(() => new Error('Sesión expirada sin token de renovación.'));
    }

    if (!this.isRefreshing) {
      this.isRefreshing = true;
      this.refreshTokenSubject.next(null);

      return this.auth.refreshToken().pipe(
        switchMap((res) => {
          this.isRefreshing = false;
          const newToken = res?.data?.access_token;
          if (newToken) {
            this.refreshTokenSubject.next(newToken);
            return next.handle(this.addToken(req, newToken));
          }
          this.auth.logout();
          this.router.navigate(['/login']);
          return throwError(() => new Error('No se pudo obtener nuevo token de acceso.'));
        }),
        catchError((refreshErr) => {
          this.isRefreshing = false;
          this.refreshTokenSubject.next(null);
          this.auth.logout();
          this.router.navigate(['/login']);
          return throwError(() => refreshErr);
        })
      );
    } else {
      // Si ya hay una renovación en progreso, esperar a que emita el nuevo token y reintentar
      return this.refreshTokenSubject.pipe(
        filter((token) => token !== null),
        take(1),
        switchMap((token) => next.handle(this.addToken(req, token!)))
      );
    }
  }

  private addToken(req: HttpRequest<any>, token: string): HttpRequest<any> {
    req.context.set(IS_AUTH_RETRY, true);
    return req.clone({
      setHeaders: {
        Authorization: `Bearer ${token}`,
      },
    });
  }
}

