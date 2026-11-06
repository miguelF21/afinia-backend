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

  get emailOk(): boolean {
    return /^\S+@\S+\.\S+$/.test((this.email || '').trim());
  }

  get checkLength(): boolean {
    return (this.password || '').length >= 8;
  }

  get checkCases(): boolean {
    const p = this.password || '';
    return /[A-Z]/.test(p) && /[a-z]/.test(p);
  }

  get checkNumber(): boolean {
    return /\d/.test(this.password || '');
  }

  get strength(): number {
    let s = 0;
    if (this.checkLength) s++;
    if (this.checkCases) s++;
    if (this.checkNumber) s++;
    return s;
  }

  get valid(): boolean {
    return !!this.name.trim() && this.emailOk && this.strength === 3 && this.acceptTerms && !this.loading;
  }

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
    if (this.loading) return;

    if (!this.name.trim()) {
      this.showError('Por favor, ingresa tu nombre completo.');
      return;
    }
    if (!this.emailOk) {
      this.showError('Por favor, ingresa un correo electrónico válido.');
      return;
    }
    if (!this.checkLength) {
      this.showError('La contraseña debe tener al menos 8 caracteres.');
      return;
    }
    if (!this.checkCases) {
      this.showError('La contraseña debe incluir mayúsculas y minúsculas.');
      return;
    }
    if (!this.checkNumber) {
      this.showError('La contraseña debe incluir al menos un número.');
      return;
    }
    if (!this.acceptTerms) {
      this.showError('Debes aceptar los Términos de servicio y la Política de privacidad.');
      return;
    }

    this.loading = true;

    this.auth.register(this.email.trim(), this.password).subscribe({
      next: () => {
        this.loading = false;
        this.user.profile.first_name = this.name.trim().split(' ')[0];
        this.user.profile.email = this.email.trim();
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
