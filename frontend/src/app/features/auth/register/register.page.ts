import { Component } from '@angular/core';
import { Router } from '@angular/router';

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

  constructor(private router: Router) { }

  onRegister() {
    console.log('Register attempt', this.name, this.email);
    // TODO: integracion con backend /api/v1/auth/register
    this.router.navigate(['/onboarding']);
  }
}
