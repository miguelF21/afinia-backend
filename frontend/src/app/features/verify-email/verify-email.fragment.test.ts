import '@angular/compiler';
import { of } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { VerifyEmailPage } from './verify-email.page';

describe('email verification link', () => {
  it('reads the token from the link fragment and verifies it', () => {
    const auth = { verifyEmail: vi.fn(() => of(null)) };
    const router = { navigate: vi.fn() };
    const route = { snapshot: { fragment: 'token=synthetic', queryParamMap: { get: () => null } } };
    const toast = { create: vi.fn(async () => ({ present: vi.fn() })) };
    new VerifyEmailPage(router as any, route as any, {} as any, auth as any, toast as any);
    expect(auth.verifyEmail).toHaveBeenCalledWith('synthetic');
    expect(router.navigate).toHaveBeenCalledWith(['/onboarding']);
  });
});
