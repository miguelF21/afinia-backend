import '@angular/compiler';
import { of, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { OnboardingPage } from './onboarding.page';

const questions = [
  { id: 'importance_personality', label: 'Pregunta del servidor 1', type: 'scale_1_5', required: true, min: 1, max: 5 },
  { id: 'importance_values', label: 'Pregunta del servidor 2', type: 'scale_1_5', required: true, min: 1, max: 5 },
];

function setup(putQuestionnaire: any = of({ data: { version: 'draft-1', saved_count: 2 } })) {
  const persisted = [{ question_id: questions[0].id, value: 2 }, { question_id: questions[1].id, value: 4 }];
  const api = {
    get: vi.fn((path: string) => path === '/questionnaire' ? of({ data: { version: 'draft-1', questions } }) :
      path === '/questionnaire/answers' ? of({ data: { version: 'draft-1', answers: persisted } }) :
      path === '/auth/me' ? of({ data: { email_verified: true, onboarding_complete: true, status: 'active' } }) : throwError(() => ({ status: 404 }))),
    put: vi.fn((path: string) => path === '/questionnaire/answers' ? putQuestionnaire : of({ data: {} })),
    post: vi.fn(() => of({ data: { first_name: 'Test', gender: 'otro', age: 30 } })),
  };
  const router = { navigate: vi.fn() };
  const user = { profile: { first_name: '', city: '' }, analytics: {}, save: vi.fn() };
  const toast = { create: vi.fn(async () => ({ present: vi.fn() })) };
  const page = new OnboardingPage(router as any, user as any, api as any, toast as any);
  page.profile = { first_name: 'Test', gender: 'Otro', birth_date: '1990-01-01', age: 30, city: 'Test' };
  page.currentStep = 3;
  return { page, api, router, toast };
}

describe('questionnaire persistence', () => {
  it('loads the server catalog and saved answers into a fresh component', () => {
    const { page, api } = setup();
    page.loadQuestionnaire();
    expect(api.get.mock.calls.map(call => call[0])).toEqual(['/profile', '/questionnaire', '/questionnaire/answers']);
    expect(page.questions).toEqual(questions);
    expect(page.answers).toEqual({ importance_personality: 2, importance_values: 4 });
    expect(page.canContinue).toBe(true);
  });

  it('sends the version and selected answers before saving the profile', () => {
    const { page, api, router } = setup();
    page.loadQuestionnaire();
    page.answers.importance_values = 5;
    page.finishOnboarding();
    expect(api.put.mock.calls[0]).toEqual(['/questionnaire/answers', { version: 'draft-1', answers: [
      { question_id: 'importance_personality', value: 2 }, { question_id: 'importance_values', value: 5 }
    ] }]);
    expect(api.post).toHaveBeenCalledTimes(1);
    expect(router.navigate).toHaveBeenCalledWith(['/dashboard']);
  });

  it('preserves answers and stays on the page when the save fails', () => {
    const { page, api, router, toast } = setup(throwError(() => ({ status: 500 })));
    page.loadQuestionnaire();
    page.answers.importance_values = 5;
    page.finishOnboarding();
    expect(page.answers.importance_values).toBe(5);
    expect(page.loading).toBe(false);
    expect(api.post).not.toHaveBeenCalled();
    expect(router.navigate).not.toHaveBeenCalled();
    expect(toast.create).toHaveBeenCalled();
  });

  it('does not proceed if the backend does not confirm all answers', () => {
    const { page, api, router } = setup(of({ data: { version: 'draft-1', saved_count: 1 } }));
    page.loadQuestionnaire();
    page.finishOnboarding();
    expect(api.post).not.toHaveBeenCalled();
    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('directs an unverified user to email verification after saving', () => {
    const { page, api, router } = setup();
    page.loadQuestionnaire();
    api.get.mockImplementation((path: string) => path === '/auth/me'
      ? of({ data: { email_verified: false, onboarding_complete: false, status: 'pending_profile' } })
      : throwError(() => ({ status: 404 })));
    page.finishOnboarding();
    expect(router.navigate).toHaveBeenCalledWith(['/verify-email']);
  });
});
