import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { AuthService } from './auth.service';

@Injectable({ providedIn: 'root' })
export class ApiService {
  constructor(private http: HttpClient, private auth: AuthService) {}

  private getHeaders(isFormData: boolean = false): HttpHeaders {
    let headers = new HttpHeaders();
    if (!isFormData) {
      headers = headers.set('Content-Type', 'application/json');
    }
    const token = this.auth.getToken();
    if (token) {
      headers = headers.set('Authorization', `Bearer ${token}`);
    }
    return headers;
  }

  get<T>(path: string, params?: { [param: string]: string | number | boolean }): Observable<T> {
    let httpParams = new HttpParams();
    if (params) {
      Object.keys(params).forEach((key) => {
        if (params[key] !== undefined && params[key] !== null) {
          httpParams = httpParams.set(key, params[key].toString());
        }
      });
    }
    return this.http.get<T>(`${environment.apiUrl}${path}`, {
      headers: this.getHeaders(),
      params: httpParams,
    });
  }

  post<T>(path: string, body: any = {}): Observable<T> {
    const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
    return this.http.post<T>(`${environment.apiUrl}${path}`, body, {
      headers: this.getHeaders(isFormData),
    });
  }

  put<T>(path: string, body: any = {}): Observable<T> {
    const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
    return this.http.put<T>(`${environment.apiUrl}${path}`, body, {
      headers: this.getHeaders(isFormData),
    });
  }

  delete<T>(path: string): Observable<T> {
    return this.http.delete<T>(`${environment.apiUrl}${path}`, {
      headers: this.getHeaders(),
    });
  }
}
