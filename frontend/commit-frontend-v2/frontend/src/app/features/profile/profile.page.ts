import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { ToastController } from '@ionic/angular';
import { DemoDataService } from '../../core/demo-data.service';
import { INTEREST_CATALOG } from '../../core/models';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { UserStateService } from '../../core/user-state.service';

@Component({
  selector: 'app-profile',
  templateUrl: './profile.page.html',
  styleUrls: ['./profile.page.scss'],
  standalone: false,
})
export class ProfilePage implements OnInit {
  editing = false;
  catalog = INTEREST_CATALOG;
  draftBio = '';
  draftInterests: string[] = [];
  private birthDate = '';
  readonly goals = [
    'Una relación seria y estable', 'Algo casual', 'Amistad primero y ver qué pasa',
  ];

  constructor(
    public user: UserStateService,
    public data: DemoDataService,
    private api: ApiService,
    private auth: AuthService,
    private router: Router,
    private toastController: ToastController
  ) {}

  ngOnInit() {
    this.loadProfile();
  }

  ionViewWillEnter() {
    this.loadProfile();
  }

  loadProfile() {
    if (!this.auth.isAuthenticated()) return;
    this.api.get<{ data: any }>('/profile').subscribe({
      next: (res) => {
        if (res?.data) {
          const d = res.data;
          this.birthDate = d.birth_date;
          this.user.profile.first_name = d.first_name || this.user.profile.first_name;
          this.user.profile.city = d.city || this.user.profile.city;
          this.user.profile.bio = d.bio || this.user.profile.bio;
          this.user.profile.gender = d.gender || this.user.profile.gender;
          this.user.profile.age = d.age || this.user.profile.age;
          if (Array.isArray(d.interests) && d.interests.length) {
            this.user.profile.interests = d.interests;
          }
          if (Array.isArray(d.photos) && d.photos.length) {
            const token = this.auth.getToken();
            const primary = d.photos.find((ph: any) => ph.is_primary) || d.photos[0];
            if (primary?.url) {
              this.user.profile.photoUrl = token ? (primary.url.includes('?') ? `${primary.url}&token=${token}` : `${primary.url}?token=${token}`) : primary.url;
            }
          }
          this.user.save();
        }
      },
      error: () => {}
    });
  }

  get p() { return this.user.profile; }
  get a() { return this.user.analytics; }
  get interests() { return this.p.interests.length ? this.p.interests : ['Viajes', 'Música', 'Naturaleza']; }
  get completion(): number {
    const f = [this.p.first_name, this.p.gender, this.p.age, this.p.city, this.p.bio, this.p.interests.length, this.a.target];
    return Math.round(f.filter(Boolean).length / f.length * 100);
  }
  get affinityMsg(): string { const v = this.data.averageAffinity; if (v === null) return 'El servidor aún no entrega un porcentaje de afinidad para tus perfiles.'; return v >= 80 ? 'Tienes un gran perfil en AFINIA' : 'Completa tu perfil para mejorar tus coincidencias'; }

  edit() { this.draftBio = this.p.bio; this.draftInterests = [...this.p.interests]; this.editing = true; }
  cancel() { this.editing = false; }

  async showToast(msg: string) {
    const toast = await this.toastController.create({
      message: msg,
      duration: 3000,
      position: 'bottom'
    });
    await toast.present();
  }

  save() {
    if (!this.birthDate) {
      this.showToast('No se pudo recuperar tu perfil. Intenta nuevamente.');
      return;
    }
    this.p.bio = this.draftBio.trim();
    this.p.interests = this.draftInterests;
    this.user.save();
    this.editing = false;

    if (this.auth.isAuthenticated()) {
      const payload = {
        first_name: this.p.first_name,
        birth_date: this.birthDate,
        gender: this.p.gender.toLowerCase() || 'otro',
        city: this.p.city || 'Villavicencio',
        bio: this.p.bio,
      };
      this.api.put('/profile', payload).subscribe({
        next: () => {
          this.showToast('Perfil actualizado correctamente');
        },
        error: () => {
          this.showToast('Cambios guardados localmente');
        }
      });
    }
  }

  toggle(t: string) {
    this.draftInterests = this.draftInterests.includes(t) ? this.draftInterests.filter(x => x !== t) : [...this.draftInterests, t].slice(0, 8);
  }

  uploadProfilePhoto(event: any) {
    const file = event.target?.files?.[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    fd.append('is_primary', 'true');
    this.api.post<{ data: any }>('/profile/photos', fd).subscribe({
      next: (res) => {
        const token = this.auth.getToken();
        const url = res?.data?.url;
        if (url) {
          this.user.profile.photoUrl = token ? (url.includes('?') ? `${url}&token=${token}` : `${url}?token=${token}`) : url;
          this.user.save();
        }
        this.showToast('¡Foto de perfil actualizada con éxito!');
        this.loadProfile();
      },
      error: (err) => {
        const msg = err.error?.error?.message || 'Error al subir la fotografía.';
        this.showToast(msg);
      }
    });
  }

  logout() {
    this.auth.logout();
    this.user.clear();
    this.router.navigate(['/login']);
  }
}
