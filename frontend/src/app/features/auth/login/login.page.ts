import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';

@Component({
  selector: 'app-login',
  templateUrl: './login.page.html',
  styleUrls: ['./login.page.scss'],
})
export class LoginPage implements OnInit {
  email = '';
  password = '';

  constructor(private router: Router) { }

  ngOnInit() {
  }

  onLogin() {
    // TODO: Integrar con backend endpoint /api/v1/auth/login
    console.log('Login attempt', this.email);
    // Simular éxito y redirigir
    this.router.navigate(['/dashboard']);
  }
}
