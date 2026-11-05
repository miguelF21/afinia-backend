import { Component } from '@angular/core';
import { Router } from '@angular/router';
import { AlertController, LoadingController } from '@ionic/angular';
import { ApiService } from '../../core/services/api.service';

@Component({
  selector: 'app-onboarding',
  templateUrl: './onboarding.page.html',
  styleUrls: ['./onboarding.page.scss'],
})
export class OnboardingPage {
  currentStep = 1;
  totalSteps = 2;

  profile = {
    first_name: '',
    birth_date: '',
    gender: '',
    city: ''
  };

  analytics = {
    intro_extro: 3,
    hobbies: 3,
    target: ''
  };

  constructor(
    private api: ApiService,
    private router: Router,
    private loadingCtrl: LoadingController,
    private alertCtrl: AlertController
  ) {}

  nextStep() {
    if (this.currentStep < this.totalSteps) {
      this.currentStep++;
    }
  }

  prevStep() {
    if (this.currentStep > 1) {
      this.currentStep--;
    }
  }

  async finishOnboarding() {
    if (!this.profile.first_name || !this.profile.birth_date || !this.profile.gender) {
      const alert = await this.alertCtrl.create({
        header: 'Faltan datos',
        message: 'Completa nombre, fecha de nacimiento y género.',
        buttons: ['OK']
      });
      await alert.present();
      return;
    }

    const birthDate = new Date(this.profile.birth_date);
    const today = new Date();
    let age = today.getFullYear() - birthDate.getFullYear();
    const m = today.getMonth() - birthDate.getMonth();
    if (m < 0 || (m === 0 && today.getDate() < birthDate.getDate())) {
      age--;
    }

    if (age < 18) {
      const alert = await this.alertCtrl.create({
        header: 'Acceso denegado',
        message: 'Debes ser mayor de 18 años para usar Afinia.',
        buttons: ['OK']
      });
      await alert.present();
      return;
    }

    const loading = await this.loadingCtrl.create({ message: 'Guardando perfil...' });
    await loading.present();

    this.api.post('/profile/', this.profile).subscribe({
      next: () => {
        this.api.post('/analytics/answers', this.analytics).subscribe({
          next: async () => {
            await loading.dismiss();
            this.router.navigate(['/dashboard']);
          },
          error: async () => {
            // Las respuestas analíticas son opcionales; ir al dashboard de todos modos
            await loading.dismiss();
            this.router.navigate(['/dashboard']);
          }
        });
      },
      error: async () => {
        await loading.dismiss();
        const alert = await this.alertCtrl.create({
          header: 'Error',
          message: 'No se pudo guardar el perfil. Intenta de nuevo.',
          buttons: ['OK']
        });
        await alert.present();
      }
    });
  }
}
