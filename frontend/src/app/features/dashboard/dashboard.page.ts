import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { ToastController } from '@ionic/angular';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';

interface Candidate {
  user_id: string;
  first_name: string;
  age: number;
  city: string;
  bio: string;
  affinityScore?: number;
}

@Component({
  selector: 'app-dashboard',
  templateUrl: './dashboard.page.html',
  styleUrls: ['./dashboard.page.scss'],
})
export class DashboardPage implements OnInit {
  profiles: Candidate[] = [];
  currentProfile: Candidate | null = null;
  loading = false;

  constructor(
    private api: ApiService,
    private auth: AuthService,
    private router: Router,
    private toastCtrl: ToastController
  ) {}

  ngOnInit() {
    this.loadPotentialMatches();
  }

  loadPotentialMatches() {
    this.loading = true;
    this.api.get<Candidate[]>('/match/potential').subscribe({
      next: (data: Candidate[]) => {
        this.profiles = data;
        this.nextProfile();
        this.loading = false;
      },
      error: () => {
        this.loading = false;
      }
    });
  }

  nextProfile() {
    this.currentProfile = this.profiles.shift() ?? null;
    // Si se agotaron, recargar del backend
    if (!this.currentProfile && !this.loading) {
      this.loadPotentialMatches();
    }
  }

  onLike() {
    if (!this.currentProfile) return;
    this.swipe(this.currentProfile.user_id, 'LIKE');
  }

  onPass() {
    if (!this.currentProfile) return;
    this.swipe(this.currentProfile.user_id, 'PASS');
  }

  private swipe(targetUserId: string, action: 'LIKE' | 'PASS') {
    this.api.post<{ match: boolean }>('/match/swipe', { target_user_id: targetUserId, action }).subscribe({
      next: async (res: { match: boolean }) => {
        if (res.match) {
          const toast = await this.toastCtrl.create({
            message: `¡Es un match con ${this.currentProfile?.first_name}! 🎉`,
            duration: 3000,
            color: 'success',
            position: 'top'
          });
          await toast.present();
        }
        this.nextProfile();
      },
      error: () => {
        // En caso de error (ej. 409 duplicado), simplemente avanzar
        this.nextProfile();
      }
    });
  }

  logout() {
    this.auth.logout();
    this.router.navigate(['/login']);
  }
}
