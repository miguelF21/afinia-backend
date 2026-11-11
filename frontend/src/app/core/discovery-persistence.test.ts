import '@angular/compiler';
import { of, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';
import { DemoDataService } from './demo-data.service';

const person = { id: 'candidate', name: 'Test', age: 25, city: 'Test', bio: '', interests: [], affinity: 50, online: true, tone: 0 };

describe('real swipe and match responses', () => {
  it('uses the match id returned by the server', () => {
    const api = { post: vi.fn(() => of({ data: { is_match: true, match_id: 'server-match-id' } })) };
    const auth = { isAuthenticated: () => false };
    const service = new DemoDataService(api as any, auth as any);
    service.queue = [person];
    let result: any;
    service.like(person).subscribe(value => result = value);
    expect(result.id).toBe('server-match-id');
    expect(service.matches[0].id).toBe('server-match-id');
    expect(service.queue).toHaveLength(0);
  });

  it('keeps the candidate when saving a swipe fails', () => {
    const api = { post: vi.fn(() => throwError(() => new Error('network'))) };
    const service = new DemoDataService(api as any, { isAuthenticated: () => false } as any);
    service.queue = [person];
    service.like(person).subscribe({ error: () => {} });
    expect(service.queue).toEqual([person]);
    expect(service.matches).toHaveLength(0);
  });

  it('reads the other_user object from the match list', () => {
    const api = { get: vi.fn(() => of({ data: { items: [{ id: 'match-id', other_user: { first_name: 'Synthetic', age: 25 } }] } })) };
    const auth = { isAuthenticated: () => false, getToken: () => null };
    const service = new DemoDataService(api as any, auth as any);
    auth.isAuthenticated = () => true;
    service.loadMatches();
    expect(service.matches[0].id).toBe('match-id');
    expect(service.matches[0].name).toBe('Synthetic');
  });
});
