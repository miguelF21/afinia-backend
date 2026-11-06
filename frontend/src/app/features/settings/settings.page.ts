import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { UserStateService } from '../../core/user-state.service';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';

interface Toggle { key: 'notifyMessages' | 'notifyMatches' | 'notifyNews' | 'showOnline' | 'showCity' | 'visible'; title: string; desc: string; icon: string; }

@Component({
  selector: 'app-settings',
  templateUrl: './settings.page.html',
  styleUrls: ['./settings.page.scss'],
  standalone: false,
})
export class SettingsPage implements OnInit {
  saved = false;
  private timer?: ReturnType<typeof setTimeout>;

  interestedIn = 'todos';
  interestedOptions = [
    { value: 'masculino', label: 'Hombres' },
    { value: 'femenino', label: 'Mujeres' },
    { value: 'todos', label: 'Todos' },
  ];

  notifications: Toggle[] = [
    { key: 'notifyMessages', title: 'Mensajes nuevos', desc: 'Avísame cuando alguien me escriba', icon: 'chatbubble-outline' },
    { key: 'notifyMatches', title: 'Nuevos matches', desc: 'Cuando el interés sea mutuo', icon: 'heart-outline' },
    { key: 'notifyNews', title: 'Novedades de AFINIA', desc: 'Consejos y mejoras de la app', icon: 'megaphone-outline' },
  ];
  privacy: Toggle[] = [
    { key: 'visible', title: 'Perfil visible', desc: 'Aparece en el descubrimiento de otras personas', icon: 'eye-outline' },
    { key: 'showOnline', title: 'Mostrar “En línea”', desc: 'Otras personas ven cuando estás activo', icon: 'radio-button-on-outline' },
    { key: 'showCity', title: 'Mostrar mi ciudad', desc: 'Visible en tu tarjeta de perfil', icon: 'location-outline' },
  ];
  faq = [
    { q: '¿Cómo se calcula la afinidad?', a: 'AFINIA compara tus intereses, tus respuestas del test de personalidad y lo que buscas, para estimar qué tan compatibles son dos perfiles.' },
    { q: '¿Qué pasa cuando hay un match?', a: 'Cuando ambos se dan “me gusta” se abre un chat para que empiecen a conocerse.' },
    { q: '¿Cómo cuido mi privacidad?', a: 'Puedes ocultar tu ciudad y tu estado en línea, o desactivar la visibilidad de tu perfil desde esta pantalla.' },
  ];
  openFaq = -1;

  constructor(
    public user: UserStateService,
    private router: Router,
    private api: ApiService,
    private auth: AuthService
  ) {}

  ngOnInit() {
    if (this.auth.isAuthenticated()) {
      this.api.get<{ data: any }>('/profile/discovery-preferences').subscribe({
        next: (res) => {
          if (res?.data) {
            const genders = res.data.interested_in_genders || [];
            if (genders.length === 1 && genders[0] === 'masculino') this.interestedIn = 'masculino';
            else if (genders.length === 1 && genders[0] === 'femenino') this.interestedIn = 'femenino';
            else this.interestedIn = 'todos';
            if (res.data.min_age) this.s.ageMin = res.data.min_age;
            if (res.data.max_age) this.s.ageMax = res.data.max_age;
          }
        },
        error: () => {}
      });
    }
  }

  get s() { return this.user.settings; }

  setInterestedIn(val: string) {
    this.interestedIn = val;
    this.change();
  }

  change() {
    this.user.save();
    this.saved = true;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => (this.saved = false), 1800);

    if (this.auth.isAuthenticated()) {
      let genders = ['masculino', 'femenino', 'otro'];
      if (this.interestedIn === 'masculino') genders = ['masculino'];
      else if (this.interestedIn === 'femenino') genders = ['femenino'];

      this.api.put('/profile/discovery-preferences', {
        interested_in_genders: genders,
        min_age: this.s.ageMin,
        max_age: this.s.ageMax,
      }).subscribe({
        next: () => {},
        error: () => {}
      });
    }
  }
  setAge(ev: any) { const v = ev.detail.value; if (v && typeof v === 'object') { this.s.ageMin = v.lower; this.s.ageMax = v.upper; this.change(); } }
  setDistance(ev: any) { this.s.distanceKm = ev.detail.value; this.change(); }
  logout() { this.user.clear(); this.router.navigate(['/login']); }
}
