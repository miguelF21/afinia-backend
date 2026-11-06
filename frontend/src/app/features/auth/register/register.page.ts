import { Component } from '@angular/core';
import { Router } from '@angular/router';
import { ToastController } from '@ionic/angular';
import { AuthService } from '../../../core/services/auth.service';
import { UserStateService } from '../../../core/user-state.service';

@Component({
  selector: 'app-register',
  templateUrl: './register.page.html',
  styleUrls: ['./register.page.scss'],
  standalone: false,
})
export class RegisterPage {
  name = '';
  email = '';
  password = '';
  acceptTerms = false;
  showPassword = false;
  loading = false;

  constructor(
    private router: Router,
    private user: UserStateService,
    private auth: AuthService,
    private toastController: ToastController
  ) { }

  get emailOk(): boolean { return /^\S+@\S+\.\S+$/.test(this.email); }
  get checks() {
    return [
      { ok: this.password.length >= 8, label: '8 caracteres' },
      { ok: /[A-Z]/.test(this.password) && /[a-z]/.test(this.password), label: 'Mayúscula y minúscula' },
      { ok: /\d/.test(this.password), label: 'Un número' },
    ];
  }
  get strength(): number { return this.checks.filter(c => c.ok).length; }
  get valid(): boolean { return !!this.name.trim() && this.emailOk && this.strength === 3 && this.acceptTerms && !this.loading; }

  async showError(message: string) {
    const toast = await this.toastController.create({
      message,
      duration: 3500,
      color: 'danger',
      position: 'bottom',
    });
    await toast.present();
  }

  async showSuccess(message: string) {
    const toast = await this.toastController.create({
      message,
      duration: 3000,
      color: 'success',
      position: 'bottom',
    });
    await toast.present();
  }

  onRegister() {
    if (!this.valid || this.loading) return;
    this.loading = true;

    this.auth.register(this.email, this.password).subscribe({
      next: (res) => {
        this.loading = false;
        this.user.profile.first_name = this.name.trim().split(' ')[0];
        this.user.profile.email = this.email;
        this.user.save();
        this.showSuccess('Cuenta creada exitosamente. Revisa tu correo.');
        this.router.navigate(['/verify-email']);
      },
      error: async (err) => {
        this.loading = false;
        const msg = err.error?.error?.message || 'Error al registrar la cuenta. Intenta nuevamente.';
        await this.showError(msg);
      },
    });
  }
}
