import { Component } from '@angular/core';
import { Router } from '@angular/router';
import { ToastController } from '@ionic/angular';
import { INTEREST_CATALOG } from '../../core/models';
import { ApiService } from '../../core/services/api.service';
import { UserStateService } from '../../core/user-state.service';

@Component({
  selector: 'app-onboarding',
  templateUrl: './onboarding.page.html',
  styleUrls: ['./onboarding.page.scss'],
  standalone: false,
})
export class OnboardingPage {
  currentStep = 1;
  totalSteps = 3;
  steps = ['Sobre ti', 'Intereses', 'Personalidad'];

  genders = ['Masculino', 'Femenino', 'Otro'];
  interestedIn = 'todos';
  interestedOptions = [
    { value: 'masculino', label: 'Hombres' },
    { value: 'femenino', label: 'Mujeres' },
    { value: 'todos', label: 'Todos' },
  ];
  selectedFile: File | null = null;
  photoPreview: string | null = null;

  catalog = INTEREST_CATALOG;
  interests: string[] = [];
  loading = false;

  goals = [
    { value: 'seria', label: 'Relación seria y estable', icon: 'heart' },
    { value: 'casual', label: 'Algo casual', icon: 'sparkles' },
    { value: 'amistad', label: 'Amistad primero', icon: 'happy' },
  ];
  scale = [1, 2, 3, 4, 5];

  profile: { first_name: string; gender: string; age: number | null; city: string } = {
    first_name: '',
    gender: '',
    age: null,
    city: ''
  };

  analytics = {
    intro_extro: 3,
    hobbies: 3,
    target: 'amistad'
  };

  constructor(
    private router: Router,
    private user: UserStateService,
    private api: ApiService,
    private toastController: ToastController
  ) {
    this.profile.first_name = user.profile.first_name;
    this.profile.city = user.profile.city;
  }

  get canContinue(): boolean {
    if (this.currentStep === 1) return !!this.profile.first_name.trim() && !!this.profile.gender && !!this.profile.age && this.profile.age >= 18 && !!this.profile.city.trim();
    if (this.currentStep === 2) return this.interests.length >= 3;
    return !!this.analytics.target && !this.loading;
  }

  toggleInterest(t: string) {
    this.interests = this.interests.includes(t) ? this.interests.filter(x => x !== t) : [...this.interests, t].slice(0, 8);
  }

  onFileSelected(event: any) {
    const file = event.target?.files?.[0];
    if (file) {
      this.selectedFile = file;
      const reader = new FileReader();
      reader.onload = () => {
        this.photoPreview = reader.result as string;
      };
      reader.readAsDataURL(file);
    }
  }

  nextStep() {
    if (this.currentStep < this.totalSteps && this.canContinue) {
      this.currentStep++;
    }
  }

  prevStep() {
    if (this.currentStep > 1) {
      this.currentStep--;
    }
  }

  async showToast(message: string, color: 'success' | 'danger' = 'success') {
    const toast = await this.toastController.create({
      message,
      duration: 3500,
      color,
      position: 'bottom',
    });
    await toast.present();
  }

  finishOnboarding() {
    if (!this.canContinue || this.loading) return;
    this.loading = true;

    const currentYear = new Date().getFullYear();
    const birthYear = currentYear - (this.profile.age || 22);
    const birthDate = `${birthYear}-06-15`;

    let mappedGender = 'otro';
    const gLower = this.profile.gender.toLowerCase();
    if (gLower.includes('masculino')) mappedGender = 'masculino';
    else if (gLower.includes('femenino')) mappedGender = 'femenino';

    const profilePayload = {
      first_name: this.profile.first_name.trim(),
      birth_date: birthDate,
      gender: mappedGender,
      city: this.profile.city.trim(),
      bio: `Intereses: ${this.interests.join(', ')}`,
    };

    // 1. Guardar perfil real en la base de datos
    this.api.post('/profile', profilePayload).subscribe({
      next: () => {
        // 2. Guardar preferencias de búsqueda según lo elegido
        let interestedGenders = ['masculino', 'femenino', 'otro'];
        if (this.interestedIn === 'masculino') interestedGenders = ['masculino'];
        else if (this.interestedIn === 'femenino') interestedGenders = ['femenino'];

        const prefPayload = {
          interested_in_genders: interestedGenders,
          min_age: Math.max(18, (this.profile.age || 22) - 5),
          max_age: Math.min(80, (this.profile.age || 22) + 10),
          target_relationship_type: this.analytics.target || 'amistad',
        };

        const uploadAndFinish = () => {
          Object.assign(this.user.profile, this.profile, { interests: this.interests });
          Object.assign(this.user.analytics, this.analytics);
          this.user.save();

          if (this.selectedFile) {
            const fd = new FormData();
            fd.append('file', this.selectedFile);
            fd.append('is_primary', 'true');
            this.api.post('/profile/photos', fd).subscribe({
              next: () => {
                this.loading = false;
                this.showToast('¡Perfil y foto configurados con éxito!');
                this.router.navigate(['/dashboard']);
              },
              error: () => {
                this.loading = false;
                this.showToast('Perfil guardado. Podrás gestionar tu foto más tarde.');
                this.router.navigate(['/dashboard']);
              }
            });
          } else {
            this.loading = false;
            this.showToast('¡Perfil configurado con éxito!');
            this.router.navigate(['/dashboard']);
          }
        };

        this.api.put('/profile/discovery-preferences', prefPayload).subscribe({
          next: () => {
            uploadAndFinish();
          },
          error: () => {
            uploadAndFinish();
          }
        });
      },
      error: async (err) => {
        this.loading = false;
        if (err.status === 409) {
          this.router.navigate(['/dashboard']);
          return;
        }
        const msg = err.error?.error?.message || 'Error al guardar el perfil. Intenta nuevamente.';
        await this.showToast(msg, 'danger');
      }
    });
  }
}
