import { Component, OnDestroy } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { ToastController } from '@ionic/angular';
import { AuthService } from '../../core/services/auth.service';
import { UserStateService } from '../../core/user-state.service';

@Component({
  selector: 'app-verify-email',
  templateUrl: './verify-email.page.html',
  styleUrls: ['./verify-email.page.scss'],
  standalone: false,
})
export class VerifyEmailPage implements OnDestroy {
  token = '';
  cooldown = 0;
  resent = false;
  loading = false;
  private timer?: ReturnType<typeof setInterval>;

  constructor(
    private router: Router,
    route: ActivatedRoute,
    public user: UserStateService,
    private auth: AuthService,
    private toastController: ToastController
  ) {
    this.token = new URLSearchParams(route.snapshot.fragment ?? '').get('token') ?? route.snapshot.queryParamMap.get('token') ?? '';
    if (this.token) {
      this.onVerify();
    }
  }

  get email(): string { return this.user.profile.email || 'tu correo'; }

  async showToast(message: string, color: 'success' | 'danger' = 'success') {
    const toast = await this.toastController.create({
      message,
      duration: 3500,
      color,
      position: 'bottom',
    });
    await toast.present();
  }

  onVerify() {
    if (!this.token.trim() || this.loading) return;
    this.loading = true;

    this.auth.verifyEmail(this.token.trim()).subscribe({
      next: () => {
        this.loading = false;
        this.showToast('¡Correo verificado correctamente!');
        this.router.navigate(['/onboarding']);
      },
      error: async (err) => {
        this.loading = false;
        const msg = err.error?.error?.message || 'Token de verificación inválido o expirado.';
        await this.showToast(msg, 'danger');
      },
    });
  }

  resend() {
    if (this.cooldown > 0 || !this.user.profile.email) return;

    this.auth.resendVerification(this.user.profile.email).subscribe({
      next: () => {
        this.resent = true;
        this.cooldown = 60;
        this.showToast('Se ha enviado un nuevo código a tu correo.');
        this.timer = setInterval(() => {
          if (--this.cooldown <= 0) clearInterval(this.timer);
        }, 1000);
      },
      error: async (err) => {
        const msg = err.error?.error?.message || 'Error al reenviar el correo. Espera un momento.';
        await this.showToast(msg, 'danger');
      },
    });
  }

  ngOnDestroy() { clearInterval(this.timer); }
}
