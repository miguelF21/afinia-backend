import { Component } from '@angular/core';
import { Router } from '@angular/router';
import { AlertController, LoadingController } from '@ionic/angular';
import { AuthService } from '../../../core/services/auth.service';

@Component({
  selector: 'app-login',
  templateUrl: './login.page.html',
  styleUrls: ['./login.page.scss'],
})
export class LoginPage {
  email = '';
  password = '';

  constructor(
    private auth: AuthService,
    private router: Router,
    private loadingCtrl: LoadingController,
    private alertCtrl: AlertController
  ) {}

  async onLogin() {
    if (!this.email || !this.password) return;

    const loading = await this.loadingCtrl.create({ message: 'Iniciando sesión...' });
    await loading.present();

    this.auth.login(this.email, this.password).subscribe({
      next: async () => {
        await loading.dismiss();
        this.router.navigate(['/dashboard']);
      },
      error: async () => {
        await loading.dismiss();
        const alert = await this.alertCtrl.create({
          header: 'Error',
          message: 'Credenciales incorrectas.',
          buttons: ['OK']
        });
        await alert.present();
      }
    });
  }
}
