import { Injectable } from '@angular/core';
import { ApiService } from './services/api.service';
import { AuthService } from './services/auth.service';
import { ChatMessage, Person } from './models';

@Injectable({ providedIn: 'root' })
export class DemoDataService {
  query = '';
  minAffinity = 0;
  onlyOnline = false;

  queue: Person[] = [];
  matches: Person[] = [];
  favorites = new Set<string>();
  likesSent = 0;
  unread: Record<string, number> = {};
  threads: Record<string, ChatMessage[]> = {};

  loadingQueue = false;
  loadingMatches = false;
  discoveryError: string | null = null;

  constructor(private api: ApiService, private auth: AuthService) {
    this.refreshAll();
  }

  refreshAll() {
    if (this.auth.isAuthenticated()) {
      this.loadPotentialQueue();
      this.loadMatches();
    }
  }

  loadPotentialQueue() {
    if (!this.auth.isAuthenticated() || this.loadingQueue) return;
    this.loadingQueue = true;
    this.api.get<{ data: { items: any[] } }>('/match/potential').subscribe({
      next: (res) => {
        this.loadingQueue = false;
        this.discoveryError = null;
        if (res?.data?.items && Array.isArray(res.data.items)) {
          const token = this.auth.getToken();
          this.queue = res.data.items.map((item, index) => {
            const toneIdx = index % 6;
            let photoUrl: string | undefined;
            if (Array.isArray(item.photos) && item.photos.length) {
              const primary = item.photos.find((p: any) => p.is_primary) || item.photos[0];
              if (primary?.url) {
                photoUrl = token ? (primary.url.includes('?') ? `${primary.url}&token=${token}` : `${primary.url}?token=${token}`) : primary.url;
              }
            }
            return {
              id: item.user_id || item.target_user_id || item.id,
              name: item.first_name || 'Usuario',
              age: item.age || 22,
              gender: item.gender,
              relationshipGoal: item.relationship_goal,
              city: item.city || 'Villavicencio, Meta',
              affinity: Math.round(item.compatibility_score ? item.compatibility_score * 100 : (item.affinity || 85)),
              online: item.online ?? true,
              tone: toneIdx,
              likesYou: !!item.likes_you,
              bio: item.bio || 'Conectando afinidades en Afinia.',
              interests: Array.isArray(item.interests) && item.interests.length ? item.interests : ['Viajes', 'Música', 'Naturaleza'],
              photoUrl,
            };
          });
        } else {
          this.queue = [];
        }
      },
      error: (err) => {
        this.loadingQueue = false;
        if (err?.status === 403) {
          this.discoveryError = err.error?.error?.message || 'Tu perfil requiere completar información para acceder a descubrimiento.';
        } else {
          this.discoveryError = null;
        }
      }
    });
  }

  loadMatches() {
    if (!this.auth.isAuthenticated() || this.loadingMatches) return;
    this.loadingMatches = true;
    this.api.get<{ data: any[] }>('/match/my-matches').subscribe({
      next: (res) => {
        this.loadingMatches = false;
        if (res?.data) {
          const items = Array.isArray(res.data) ? res.data : (res.data as any).items || [];
          this.matches = items.map((m: any, idx: number) => {
            const partner = m.partner_profile || m.user || m;
            const matchId = m.id || m.match_id || partner.id;
            if (m.last_message) {
              const myId = this.auth.getUser()?.id;
              this.threads[matchId] = [{
                id: m.last_message.id || 'msg-' + Date.now(),
                fromMe: m.last_message.sender_user_id === myId,
                text: m.last_message.text || '',
                at: m.last_message.sent_at || new Date().toISOString(),
                read: !!m.last_message.read_at,
              }];
            }
            if (m.unread_count) {
              this.unread[matchId] = m.unread_count;
            }
            const token = this.auth.getToken();
            let partnerPhotoUrl: string | undefined;
            if (Array.isArray(partner.photos) && partner.photos.length) {
              const pPhoto = partner.photos.find((p: any) => p.is_primary) || partner.photos[0];
              if (pPhoto?.url) {
                partnerPhotoUrl = token ? (pPhoto.url.includes('?') ? `${pPhoto.url}&token=${token}` : `${pPhoto.url}?token=${token}`) : pPhoto.url;
              }
            }
            return {
              id: matchId,
              name: partner.first_name || 'Match',
              age: partner.age || 23,
              gender: partner.gender,
              relationshipGoal: partner.relationship_goal,
              city: partner.city || 'Villavicencio, Meta',
              affinity: Math.round(partner.compatibility_score ? partner.compatibility_score * 100 : 88),
              online: partner.online ?? true,
              tone: idx % 6,
              bio: partner.bio || '',
              interests: partner.interests || ['Fotografía', 'Cine'],
              photoUrl: partnerPhotoUrl,
            };
          });
        }
      },
      error: () => {
        this.loadingMatches = false;
      }
    });
  }

  // ───── Descubrir ─────
  get filteredQueue(): Person[] {
    const q = this.query.trim().toLowerCase();
    return this.queue.filter(p =>
      p.affinity >= this.minAffinity &&
      (!this.onlyOnline || p.online) &&
      (!q || [p.name, p.city, ...p.interests].some(t => t.toLowerCase().includes(q))));
  }

  like(p: Person): Person | null {
    this.removeFromQueue(p);
    this.likesSent++;

    let matchedPerson: Person | null = null;
    this.api.post<{ data: { is_match: boolean; match_id?: string } }>('/match/swipe', {
      target_user_id: p.id,
      action: 'LIKE',
    }).subscribe({
      next: (res) => {
        if (res?.data?.is_match) {
          const matchId = res.data.match_id || ('m-' + p.id);
          const m: Person = { ...p, id: matchId };
          this.matches.unshift(m);
          this.threads[matchId] = [{
            id: 'n' + Date.now(),
            fromMe: false,
            text: '¡Es un match! 🎉 Ya pueden comenzar a conversar.',
            at: new Date().toISOString(),
          }];
          this.unread[matchId] = 1;
        }
      },
      error: () => {}
    });

    if (p.likesYou) {
      const m: Person = { ...p, id: 'm-' + p.id };
      this.matches.unshift(m);
      this.threads[m.id] = [{
        id: 'n' + Date.now(),
        fromMe: false,
        text: '¡Hola! 👋 ¿Cómo estás?',
        at: new Date().toISOString(),
      }];
      this.unread[m.id] = 1;
      return m;
    }
    return null;
  }

  pass(p: Person) {
    this.removeFromQueue(p);
    this.api.post('/match/swipe', {
      target_user_id: p.id,
      action: 'PASS',
    }).subscribe({
      error: () => {}
    });
  }

  toggleFavorite(p: Person) {
    this.favorites.has(p.id) ? this.favorites.delete(p.id) : this.favorites.add(p.id);
  }

  private removeFromQueue(p: Person) {
    this.queue = this.queue.filter(x => x.id !== p.id);
  }

  // ───── Matches / Chat ─────
  get filteredMatches(): Person[] {
    const q = this.query.trim().toLowerCase();
    return this.matches.filter(p => !q || [p.name, p.city, ...p.interests].some(t => t.toLowerCase().includes(q)));
  }

  person(id: string): Person | undefined {
    return this.matches.find(m => m.id === id);
  }

  messages(id: string): ChatMessage[] {
    return this.threads[id] ?? [];
  }

  lastMessage(id: string): ChatMessage | undefined {
    const t = this.messages(id);
    return t[t.length - 1];
  }

  get conversations(): Person[] {
    return this.matches
      .filter(m => this.messages(m.id).length)
      .sort((a, b) => {
        const atA = this.lastMessage(a.id)?.at || '';
        const atB = this.lastMessage(b.id)?.at || '';
        return atB.localeCompare(atA);
      });
  }

  get unreadTotal(): number {
    return Object.values(this.unread).reduce((a, b) => a + b, 0);
  }

  loadMessages(matchId: string) {
    if (!this.auth.isAuthenticated()) return;
    this.api.get<{ data: { items: any[] } }>(`/match/${matchId}/messages`).subscribe({
      next: (res) => {
        if (res?.data?.items) {
          const myId = this.auth.getUser()?.id;
          this.threads[matchId] = res.data.items.map((m: any) => ({
            id: m.id,
            fromMe: m.sender_user_id === myId,
            text: m.text,
            at: m.sent_at,
            read: !!m.read_at,
          }));
        }
      },
      error: () => {}
    });
  }

  send(id: string, text: string) {
    const t = text.trim();
    if (!t) return;
    const msg: ChatMessage = {
      id: 'u' + Date.now(),
      fromMe: true,
      text: t,
      at: new Date().toISOString(),
      read: false,
    };
    (this.threads[id] ??= []).push(msg);

    this.api.post<{ data: { id: string } }>(`/match/${id}/messages`, { text: t }).subscribe({
      next: (res) => {
        if (res?.data?.id) {
          msg.id = res.data.id;
        }
      },
      error: () => {}
    });
  }

  markRead(id: string) {
    delete this.unread[id];
    this.api.post(`/match/${id}/read`, {}).subscribe({
      error: () => {}
    });
  }

  get averageAffinity(): number {
    const all = [...this.matches, ...this.queue];
    return all.length ? Math.round(all.reduce((s, p) => s + p.affinity, 0) / all.length) : 0;
  }

  // ───── Utilidades de presentación ─────
  timeLabel(iso: string): string {
    const d = new Date(iso);
    const now = new Date();
    const days = Math.floor((new Date(now.toDateString()).getTime() - new Date(d.toDateString()).getTime()) / 864e5);
    if (isNaN(days)) return '';
    if (days <= 0) return d.toLocaleTimeString('es-CO', { hour: 'numeric', minute: '2-digit' });
    if (days === 1) return 'Ayer';
    if (days < 7) return d.toLocaleDateString('es-CO', { weekday: 'short' }).replace('.', '').replace(/^./, c => c.toUpperCase());
    return d.toLocaleDateString('es-CO', { day: 'numeric', month: 'short' });
  }
}
