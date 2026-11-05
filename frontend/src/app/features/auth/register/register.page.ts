import { Component } from '@angular/core';
import { Router } from '@angular/router';
import { AlertController, LoadingController } from '@ionic/angular';
import { AuthService } from '../../../core/services/auth.service';

@Component({
  selector: 'app-register',
  templateUrl: './register.page.html',
  styleUrls: ['./register.page.scss'],
  standalone: false,
})
export class RegisterPage {
  email = '';
  password = '';

  constructor(
    private auth: AuthService,
    private router: Router,
    private loadingCtrl: LoadingController,
    private alertCtrl: AlertController
  ) {}

  async onRegister() {
    if (!this.email || !this.password) {
      this.showAlert('Faltan datos', 'Por favor, ingresa tu correo y contraseña.');
      return;
    }

    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(this.email)) {
      this.showAlert('Correo inválido', 'Por favor, ingresa un correo electrónico válido.');
      return;
    }

    if (this.password.length < 6) {
      this.showAlert('Contraseña débil', 'La contraseña debe tener al menos 6 caracteres.');
      return;
    }

    const loading = await this.loadingCtrl.create({ message: 'Creando cuenta...' });
    await loading.present();

    this.auth.register(this.email, this.password).subscribe({
      next: async () => {
        // Login automático tras registro exitoso
        this.auth.login(this.email, this.password).subscribe({
          next: async () => {
            await loading.dismiss();
            this.router.navigate(['/onboarding']);
          },
          error: async () => {
            await loading.dismiss();
            this.router.navigate(['/login']);
          }
        });
      },
      error: async (err: any) => {
        await loading.dismiss();
        const msg = err.status === 409 ? 'El correo ya está registrado.' : 'Error al crear la cuenta.';
        const alert = await this.alertCtrl.create({
          header: 'Error',
          message: msg,
          buttons: ['OK']
        });
        await alert.present();
      }
    });
  }

  private async showAlert(header: string, message: string) {
    const alert = await this.alertCtrl.create({
      header,
      message,
      buttons: ['OK']
    });
    await alert.present();
  }
}
