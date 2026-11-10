import '@angular/compiler';
import { describe, expect, it, vi } from 'vitest';
import { of, throwError } from 'rxjs';
import { OnboardingPage } from './onboarding.page';

describe('onboarding profile persistence', () => {
  it('updates an existing profile after a conflict and uses the server response', () => {
    const persisted = { first_name: 'Saved', gender: 'otro', birth_date: '1990-01-01', age: 36, city: 'Saved city', bio: 'Saved bio' };
    const api = {
      get: vi.fn((path: string) => path === '/auth/me' ? of({ data: { email_verified: true, onboarding_complete: true, status: 'active' } }) : throwError(() => ({ status: 404 }))),
      post: vi.fn(() => throwError(() => ({ status: 409 }))),
      put: vi.fn((path: string) => of(path === '/profile' ? { data: persisted } : path === '/questionnaire/answers' ? { data: { version: 'draft-1', saved_count: 1 } } : { data: {} })),
    };
    const user = { profile: { first_name: '', city: '' }, analytics: {}, save: vi.fn() };
    const router = { navigate: vi.fn() };
    const toast = { create: vi.fn(async () => ({ present: vi.fn() })) };
    const page = new OnboardingPage(router as any, user as any, api as any, toast as any);
    page.profile = { first_name: 'Synthetic', gender: 'Otro', birth_date: '1990-01-01', age: 36, city: 'Test' };
    page.interests = ['A', 'B', 'C'];
    page.currentStep = 3;
    page.questionnaireVersion = 'draft-1';
    page.questions = [{ id: 'importance_values', label: 'Valores', type: 'scale_1_5', required: true, min: 1, max: 5 }];
    page.answers = { importance_values: 4 };
    page.finishOnboarding();

    expect(api.post.mock.calls[0][0]).toBe('/profile');
    expect(api.put.mock.calls[1][0]).toBe('/profile');
    expect((api.put.mock.calls[1] as any)[1].birth_date).toBe('1990-01-01');
    expect(user.profile.first_name).toBe(persisted.first_name);
    expect(user.profile.city).toBe(persisted.city);
    expect(router.navigate).toHaveBeenCalledWith(['/dashboard']);
  });

  it('does not navigate when preferences fail', () => {
    const api = {
      get: vi.fn(() => throwError(() => ({ status: 404 }))),
      post: vi.fn(() => of({ data: { first_name: 'Synthetic', gender: 'otro', age: 30 } })),
      put: vi.fn((path: string) => path === '/questionnaire/answers' ? of({ data: { version: 'draft-1', saved_count: 1 } }) : throwError(() => ({ status: 422 }))),
    };
    const user = { profile: { first_name: '', city: '' }, analytics: {}, save: vi.fn() };
    const router = { navigate: vi.fn() };
    const toast = { create: vi.fn(async () => ({ present: vi.fn() })) };
    const page = new OnboardingPage(router as any, user as any, api as any, toast as any);
    page.profile = { first_name: 'Synthetic', gender: 'Otro', birth_date: '1995-01-01', age: 30, city: 'Test' };
    page.currentStep = 3;
    page.questionnaireVersion = 'draft-1';
    page.questions = [{ id: 'importance_values', label: 'Valores', type: 'scale_1_5', required: true, min: 1, max: 5 }];
    page.answers = { importance_values: 4 };
    page.finishOnboarding();
    expect(router.navigate).not.toHaveBeenCalled();
    expect(user.save).not.toHaveBeenCalled();
    expect(page.loading).toBe(false);
  });
});
