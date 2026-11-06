import { Component } from '@angular/core';
import { Router } from '@angular/router';
import { ToastController } from '@ionic/angular';
import { AuthService } from '../../../core/services/auth.service';
import { UserStateService } from '../../../core/user-state.service';

@Component({
  selector: 'app-login',
  templateUrl: './login.page.html',
  styleUrls: ['./login.page.scss'],
  standalone: false,
})
export class LoginPage {
  email = '';
  password = '';
  showPassword = false;
  loading = false;
  errorMessage = '';

  constructor(
    private router: Router,
    private user: UserStateService,
    private auth: AuthService,
    private toastController: ToastController
  ) { }

  get valid(): boolean { return /^\S+@\S+\.\S+$/.test(this.email) && this.password.length > 0; }

  async showError(message: string) {
    const toast = await this.toastController.create({
      message,
      duration: 3500,
      color: 'danger',
      position: 'bottom',
    });
    await toast.present();
  }

  onLogin() {
    if (!this.valid || this.loading) return;
    this.loading = true;
    this.errorMessage = '';

    this.auth.login(this.email, this.password).subscribe({
      next: (res) => {
        this.loading = false;
        this.user.profile.email = this.email;
        this.user.save();

        if (res.data?.user?.onboarding_complete === false) {
          this.router.navigate(['/onboarding']);
        } else {
          this.router.navigate(['/dashboard']);
        }
      },
      error: async (err) => {
        this.loading = false;
        const msg = err.error?.error?.message || 'Error al iniciar sesión. Verifica tus credenciales.';
        this.errorMessage = msg;
        await this.showError(msg);
      },
    });
  }
}
