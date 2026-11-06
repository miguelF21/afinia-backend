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
          this.user.profile.first_name = d.first_name || this.user.profile.first_name;
          this.user.profile.city = d.city || this.user.profile.city;
          this.user.profile.bio = d.bio || this.user.profile.bio;
          this.user.profile.gender = d.gender || this.user.profile.gender;
          this.user.profile.age = d.age || this.user.profile.age;
          if (Array.isArray(d.interests) && d.interests.length) {
            this.user.profile.interests = d.interests;
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
  get affinityMsg(): string { const v = this.data.averageAffinity; return v >= 80 ? 'Tienes un gran perfil en AFINIA' : 'Completa tu perfil para mejorar tus coincidencias'; }

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
    this.p.bio = this.draftBio.trim();
    this.p.interests = this.draftInterests;
    this.user.save();
    this.editing = false;

    if (this.auth.isAuthenticated()) {
      const currentYear = new Date().getFullYear();
      const birthYear = currentYear - (this.p.age || 22);
      const payload = {
        first_name: this.p.first_name,
        birth_date: `${birthYear}-06-15`,
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

  logout() {
    this.auth.logout();
    this.user.clear();
    this.router.navigate(['/login']);
  }
}
