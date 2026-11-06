import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable, tap } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface AuthUser {
  id: string;
  email: string;
  email_verified: boolean;
  onboarding_complete?: boolean;
  status: string;
}

export interface LoginResponse {
  data: {
    access_token: string;
    refresh_token: string;
    expires_in: number;
    token_type: string;
    user: AuthUser;
  };
}

export interface RegisterResponse {
  data: {
    user: AuthUser;
    message?: string;
  };
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly TOKEN_KEY = 'afinia_token';
  private readonly REFRESH_KEY = 'afinia_refresh_token';
  private readonly USER_KEY = 'afinia_user';

  constructor(private http: HttpClient) {}

  register(email: string, password: string): Observable<RegisterResponse> {
    const payload = {
      email,
      password,
      accept_terms_version: environment.legalTermsVersion,
      accept_privacy_version: environment.legalPrivacyVersion,
    };
    return this.http.post<RegisterResponse>(`${environment.apiUrl}/auth/register`, payload);
  }

  login(email: string, password: string): Observable<LoginResponse> {
    const headers = new HttpHeaders({
      'Content-Type': 'application/json',
      'X-Client-Platform': 'mobile',
    });
    return this.http.post<LoginResponse>(
      `${environment.apiUrl}/auth/login`,
      { email, password },
      { headers }
    ).pipe(
      tap((res) => {
        if (res && res.data) {
          if (res.data.access_token) {
            localStorage.setItem(this.TOKEN_KEY, res.data.access_token);
          }
          if (res.data.refresh_token) {
            localStorage.setItem(this.REFRESH_KEY, res.data.refresh_token);
          }
          if (res.data.user) {
            localStorage.setItem(this.USER_KEY, JSON.stringify(res.data.user));
          }
        }
      })
    );
  }

  verifyEmail(token: string): Observable<any> {
    return this.http.post(`${environment.apiUrl}/auth/verify-email`, { token });
  }

  resendVerification(email: string): Observable<any> {
    return this.http.post(`${environment.apiUrl}/auth/resend-verification`, { email });
  }

  logout(): void {
    const token = this.getToken();
    if (token) {
      const headers = new HttpHeaders({
        Authorization: `Bearer ${token}`,
      });
      this.http.post(`${environment.apiUrl}/auth/logout`, {}, { headers }).subscribe({
        error: () => {},
      });
    }
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.REFRESH_KEY);
    localStorage.removeItem(this.USER_KEY);
  }

  getToken(): string | null {
    return localStorage.getItem(this.TOKEN_KEY);
  }

  getUser(): AuthUser | null {
    const raw = localStorage.getItem(this.USER_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  isAuthenticated(): boolean {
    return !!this.getToken();
  }
}
