import { Injectable } from '@angular/core';
import { AppSettings, MyAnalytics, MyProfile } from './models';

const KEY = 'afinia.ui.state.v1';

/**
 * Estado local de la interfaz (registro, onboarding, ajustes).
 * Solo vive en este dispositivo: todavía NO está conectado al backend.
 * Las llamadas reales (/auth, /profile, /analytics) se integrarán sobre estos mismos puntos.
 */
@Injectable({ providedIn: 'root' })
export class UserStateService {
  profile: MyProfile = {
    first_name: '', gender: '', age: null, city: '', bio: '', interests: [], email: '',
  };
  analytics: MyAnalytics = { intro_extro: 3, hobbies: 3, target: '' };
  settings: AppSettings = {
    notifyMessages: true, notifyMatches: true, notifyNews: false,
    showOnline: true, showCity: true, visible: true,
    ageMin: 20, ageMax: 32, distanceKm: 40,
  };

  constructor() {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) {
        const s = JSON.parse(raw);
        Object.assign(this.profile, s.profile);
        Object.assign(this.analytics, s.analytics);
        Object.assign(this.settings, s.settings);
      }
    } catch { /* almacenamiento no disponible */ }
  }

  save() {
    try {
      localStorage.setItem(KEY, JSON.stringify({
        profile: this.profile, analytics: this.analytics, settings: this.settings,
      }));
    } catch { /* ignorar */ }
  }

  clear() {
    try { localStorage.removeItem(KEY); } catch { /* ignorar */ }
    this.profile = { first_name: '', gender: '', age: null, city: '', bio: '', interests: [], email: '' };
    this.analytics = { intro_extro: 3, hobbies: 3, target: '' };
  }

  get displayName(): string {
    return this.profile.first_name?.trim().split(' ')[0] || 'Tú';
  }
  get handle(): string {
    const base = this.profile.email?.split('@')[0] || 'usuario';
    return '@' + base.toLowerCase().replace(/[^a-z0-9._]/g, '');
  }
}
