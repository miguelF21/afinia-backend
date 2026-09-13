import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';

@Component({
  selector: 'app-onboarding',
  templateUrl: './onboarding.page.html',
  styleUrls: ['./onboarding.page.scss'],
})
export class OnboardingPage implements OnInit {
  currentStep = 1;
  totalSteps = 2;

  profile = {
    first_name: '',
    gender: '',
    age: null,
    city: ''
  };

  analytics = {
    intro_extro: 3,
    hobbies: 3,
    target: ''
  };

  constructor(private router: Router) { }

  ngOnInit() {
  }

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

  finishOnboarding() {
    // TODO: POST /api/v1/profile y POST /api/v1/analytics/answers
    console.log('Perfil guardado:', this.profile);
    console.log('Analítica guardada:', this.analytics);
    this.router.navigate(['/features/dashboard']);
  }
}
