import { Component } from '@angular/core';
import { Router } from '@angular/router';
import { ToastController } from '@ionic/angular';
import { INTEREST_CATALOG } from '../../core/models';
import { ApiService } from '../../core/services/api.service';
import { UserStateService } from '../../core/user-state.service';
import { catchError, switchMap, throwError } from 'rxjs';

interface QuestionnaireQuestion {
  id: string;
  label: string;
  type: string;
  required: boolean;
  min: number;
  max: number;
}
interface QuestionnaireAnswer { question_id: string; value: number; }

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
  questions: QuestionnaireQuestion[] = [];
  questionnaireVersion = '';
  answers: Record<string, number> = {};
  questionnaireLoading = false;
  questionnaireError = '';

  get answeredCount(): number {
    return this.questions.filter(q => Number.isInteger(this.answers[q.id])).length;
  }

  questionLabel(label: string): string {
    const characteristic = label.match(/\[([^\]]+)\]\s*$/);
    return characteristic ? characteristic[1] : label.replace(/^\s*\d+\.\s*/, '');
  }

  get characteristicHeading(): string {
    const question = this.questions.find(q => /\[[^\]]+\]\s*$/.test(q.label));
    return question ? question.label.replace(/^\s*\d+\.\s*/, '').replace(/\s*\[[^\]]+\]\s*$/, '') : '';
  }

  isCharacteristic(label: string): boolean {
    return /\[[^\]]+\]\s*$/.test(label);
  }

  profile: { first_name: string; gender: string; birth_date: string; age: number | null; city: string } = {
    first_name: '',
    gender: '',
    birth_date: '',
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
    this.api.get<{ data: any }>('/profile').subscribe({
      next: ({ data }) => {
        this.profile.first_name = data.first_name;
        this.profile.gender = data.gender;
        this.profile.birth_date = data.birth_date;
        this.profile.city = data.city || '';
        if (!this.interests.length && typeof data.bio === 'string' && data.bio.startsWith('Intereses: ')) {
          this.interests = data.bio.slice('Intereses: '.length).split(', ').filter((interest: string) => this.catalog.includes(interest));
        }
        if (Array.isArray(data.photos) && data.photos.length > 0) {
          const primary = data.photos.find((p: any) => p.is_primary) || data.photos[0];
          if (primary?.url) this.photoPreview = primary.url;
        }
        this.updateAge();
        this.api.get<{ data: { interested_in_genders: string[]; target_relationship_type: string | null } }>('/profile/discovery-preferences').subscribe({
          next: ({ data: preferences }) => {
            if (preferences.interested_in_genders?.length === 1 && ['masculino', 'femenino'].includes(preferences.interested_in_genders[0])) {
              this.interestedIn = preferences.interested_in_genders[0];
            }
            if (preferences.target_relationship_type && this.goals.some(goal => goal.value === preferences.target_relationship_type)) {
              this.analytics.target = preferences.target_relationship_type;
            }
          },
          error: () => {}
        });
      },
      error: () => {}
    });
  }

  updateAge() {
    const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(this.profile.birth_date);
    if (!parts) { this.profile.age = null; return; }
    const today = new Date();
    const year = Number(parts[1]), month = Number(parts[2]), day = Number(parts[3]);
    const date = new Date(year, month - 1, day);
    if (date.getFullYear() !== year || date.getMonth() !== month - 1 || date.getDate() !== day) {
      this.profile.age = null; return;
    }
    this.profile.age = today.getFullYear() - year - (today.getMonth() + 1 < month || (today.getMonth() + 1 === month && today.getDate() < day) ? 1 : 0);
  }

  get canContinue(): boolean {
    if (this.currentStep === 1) return !!this.profile.first_name.trim() && !!this.profile.gender && this.profile.age !== null && this.profile.age >= 18 && this.profile.age <= 120 && !!this.profile.city.trim() && (!!this.selectedFile || !!this.photoPreview);
    if (this.currentStep === 2) return this.interests.length >= 3;
    return !!this.analytics.target && !this.loading && !this.questionnaireLoading && !this.questionnaireError &&
      !!this.questionnaireVersion && this.questions.length > 0 && this.questions.every(q =>
        !q.required || (Number.isInteger(this.answers[q.id]) && this.answers[q.id] >= q.min && this.answers[q.id] <= q.max));
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
      if (this.currentStep === 3 && !this.questionnaireVersion) this.loadQuestionnaire();
    }
  }

  loadQuestionnaire() {
    if (this.questionnaireLoading) return;
    this.questionnaireLoading = true;
    this.questionnaireError = '';
    this.api.get<{ data: { version: string; questions: QuestionnaireQuestion[] } }>('/questionnaire').pipe(
      switchMap(catalog => this.api.get<{ data: { version: string; answers: QuestionnaireAnswer[] } }>('/questionnaire/answers').pipe(
        switchMap(saved => {
          if (!catalog.data?.version || !Array.isArray(catalog.data.questions) || !catalog.data.questions.length ||
              catalog.data.questions.some(q => q.type !== 'scale_1_5' || q.min !== 1 || q.max !== 5) ||
              saved.data?.version !== catalog.data.version || !Array.isArray(saved.data.answers)) {
            return throwError(() => new Error('El cuestionario recibido no es compatible.'));
          }
          return [ { catalog: catalog.data, saved: saved.data } ];
        })
      ))
    ).subscribe({
      next: ({ catalog, saved }) => {
        this.questions = catalog.questions;
        this.questionnaireVersion = catalog.version;
        for (const answer of saved.answers) {
          const question = this.questions.find(q => q.id === answer.question_id);
          if (question && this.answers[question.id] === undefined && Number.isInteger(answer.value) &&
              answer.value >= question.min && answer.value <= question.max) this.answers[question.id] = answer.value;
        }
        this.questionnaireLoading = false;
      },
      error: () => {
        this.questionnaireLoading = false;
        this.questionnaireError = 'No se pudo cargar el cuestionario y sus respuestas. Intenta nuevamente.';
      }
    });
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
    const answers = this.questions
      .filter(q => Number.isInteger(this.answers[q.id]))
      .map(q => ({ question_id: q.id, value: this.answers[q.id] }));
    this.api.put<{ data: { version: string; saved_count: number } }>('/questionnaire/answers', {
      version: this.questionnaireVersion, answers
    }).subscribe({
      next: ({ data }) => {
        if (!data || data.version !== this.questionnaireVersion || data.saved_count !== answers.length) {
          this.loading = false;
          this.showToast('No se pudo confirmar el guardado del cuestionario. Intenta nuevamente.', 'danger');
          return;
        }
        this.saveProfile();
      },
      error: (err) => {
        this.loading = false;
        this.showToast(err.error?.error?.message || 'No se pudieron guardar las respuestas. Intenta nuevamente.', 'danger');
      }
    });
  }

  private saveProfile() {

    let mappedGender = 'otro';
    const gLower = this.profile.gender.toLowerCase();
    if (gLower.includes('masculino')) mappedGender = 'masculino';
    else if (gLower.includes('femenino')) mappedGender = 'femenino';

    const profilePayload = {
      first_name: this.profile.first_name.trim(),
      birth_date: this.profile.birth_date,
      gender: mappedGender,
      city: this.profile.city.trim(),
      bio: `Intereses: ${this.interests.join(', ')}`,
    };

    // 1. Guardar perfil real en la base de datos
    this.api.post<{ data: any }>('/profile', profilePayload).pipe(
      catchError(err => err.status === 409
        ? this.api.put<{ data: any }>('/profile', profilePayload)
        : throwError(() => err))
    ).subscribe({
      next: ({ data: savedProfile }) => {
        // 2. Guardar preferencias de búsqueda según lo elegido
        let interestedGenders = ['masculino', 'femenino', 'otro'];
        if (this.interestedIn === 'masculino') interestedGenders = ['masculino'];
        else if (this.interestedIn === 'femenino') interestedGenders = ['femenino'];

        const prefPayload = {
          interested_in_genders: interestedGenders,
          min_age: Math.max(18, this.profile.age! - 5),
          max_age: Math.min(120, this.profile.age! + 10),
          target_relationship_type: this.analytics.target || 'amistad',
        };

        const uploadAndFinish = () => {
          Object.assign(this.user.profile, {
            first_name: savedProfile.first_name, gender: savedProfile.gender,
            age: savedProfile.age, city: savedProfile.city || '', bio: savedProfile.bio || '',
            interests: this.interests
          });
          Object.assign(this.user.analytics, this.analytics);
          this.user.save();

          const finish = () => {
            this.api.get<{ data: { email_verified: boolean; onboarding_complete: boolean; status: string } }>('/auth/me').subscribe({
              next: ({ data }) => {
                this.loading = false;
                if (!data.email_verified) {
                  this.showToast('Perfil guardado. Verifica tu correo para descubrir personas.');
                  this.router.navigate(['/verify-email']);
                } else if (!data.onboarding_complete) {
                  this.showToast('Perfil guardado. Revisa que tu foto principal esté aprobada para descubrir personas.');
                  this.router.navigate(['/dashboard']);
                } else {
                  this.showToast('¡Perfil configurado con éxito!');
                  this.router.navigate(['/dashboard']);
                }
              },
              error: () => {
                this.loading = false;
                this.showToast('Perfil guardado, pero no pudimos comprobar el estado de tu cuenta. Intenta nuevamente.', 'danger');
              }
            });
          };

          if (this.selectedFile) {
            const fd = new FormData();
            fd.append('file', this.selectedFile);
            fd.append('is_primary', 'true');
            this.api.post('/profile/photos', fd).subscribe({
              next: () => {
                finish();
              },
              error: (err) => {
                this.loading = false;
                this.showToast(err.error?.error?.message || 'No se pudo guardar la foto. Intenta nuevamente.', 'danger');
              }
            });
          } else {
            finish();
          }
        };

        this.api.put('/profile/discovery-preferences', prefPayload).subscribe({
          next: () => {
            uploadAndFinish();
          },
          error: (err) => {
            this.loading = false;
            this.showToast(err.error?.error?.message || 'No se pudieron guardar las preferencias. Intenta nuevamente.', 'danger');
          }
        });
      },
      error: async (err) => {
        this.loading = false;
        const msg = err.error?.error?.message || 'Error al guardar el perfil. Intenta nuevamente.';
        await this.showToast(msg, 'danger');
      }
    });
  }
}
