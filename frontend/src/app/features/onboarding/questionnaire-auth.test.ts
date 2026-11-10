import '@angular/compiler';
import { HttpErrorResponse, HttpRequest, HttpResponse } from '@angular/common/http';
import { firstValueFrom, of, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { AuthInterceptor } from '../../core/interceptors/auth.interceptor';

describe('questionnaire requests with the existing auth interceptor', () => {
  it.each(['GET', 'PUT'])('retries %s after a successful refresh', async (method) => {
    const auth = { getRefreshToken: () => 'synthetic', refreshToken: vi.fn(() => of({ data: { access_token: 'new-synthetic' } })), logout: vi.fn() };
    const router = { navigate: vi.fn() };
    const interceptor = new AuthInterceptor(auth as any, router as any);
    const handle = vi.fn()
      .mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 401 })))
      .mockReturnValueOnce(of(new HttpResponse({ status: 200 })));
    const req = new HttpRequest(method, '/api/v1/questionnaire/answers', method === 'PUT' ? { answers: [] } : null);
    await firstValueFrom(interceptor.intercept(req, { handle }));
    expect(auth.refreshToken).toHaveBeenCalledTimes(1);
    expect(handle).toHaveBeenCalledTimes(2);
    expect(handle.mock.calls[1][0].headers.get('Authorization')).toBe('Bearer new-synthetic');
    expect(handle.mock.calls[1][0].body).toEqual(req.body);
  });

  it('reports refresh failure without pretending the save succeeded', async () => {
    const auth = { getRefreshToken: () => 'synthetic', refreshToken: () => throwError(() => new Error('failed')), logout: vi.fn() };
    const router = { navigate: vi.fn() };
    const interceptor = new AuthInterceptor(auth as any, router as any);
    const handle = vi.fn(() => throwError(() => new HttpErrorResponse({ status: 401 })));
    await expect(firstValueFrom(interceptor.intercept(new HttpRequest('PUT', '/api/v1/questionnaire/answers', {}), { handle }))).rejects.toThrow('failed');
    expect(auth.logout).toHaveBeenCalled();
    expect(router.navigate).toHaveBeenCalledWith(['/login']);
  });
});
