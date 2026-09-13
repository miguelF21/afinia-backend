import { Component, OnInit } from '@angular/core';

interface Profile {
  id: string;
  first_name: string;
  age: number;
  city: string;
  bio: string;
  affinityScore?: number;
}

@Component({
  selector: 'app-dashboard',
  templateUrl: './dashboard.page.html',
  styleUrls: ['./dashboard.page.scss'],
})
export class DashboardPage implements OnInit {
  
  profiles: Profile[] = [];
  currentProfile: Profile | null = null;

  constructor() { }

  ngOnInit() {
    this.loadMockProfiles();
    this.nextProfile();
  }

  loadMockProfiles() {
    // Estos datos normalmente vendrían del backend /api/v1/discovery
    // y cruzados por el modelo de ML
    this.profiles = [
      {
        id: '1',
        first_name: 'Ana',
        age: 24,
        city: 'Bogotá',
        bio: 'Me encanta leer, el café por la mañana y salir a caminar con mi perro.',
        affinityScore: 87
      },
      {
        id: '2',
        first_name: 'Carlos',
        age: 27,
        city: 'Medellín',
        bio: 'Desarrollador de software y aficionado a la fotografía. Buscando algo serio.',
        affinityScore: 65
      },
      {
        id: '3',
        first_name: 'Laura',
        age: 22,
        city: 'Cali',
        bio: 'Estudiante universitaria, amo bailar salsa y conocer gente nueva.',
        affinityScore: 92
      }
    ];
  }

  nextProfile() {
    if (this.profiles.length > 0) {
      this.currentProfile = this.profiles.shift() || null;
    } else {
      this.currentProfile = null;
    }
  }

  onLike() {
    if (!this.currentProfile) return;
    console.log(`Liked profile: ${this.currentProfile.id}`);
    // TODO: Llamada al backend POST /api/v1/interaction (LIKE)
    this.nextProfile();
  }

  onPass() {
    if (!this.currentProfile) return;
    console.log(`Passed profile: ${this.currentProfile.id}`);
    // TODO: Llamada al backend POST /api/v1/interaction (PASS)
    this.nextProfile();
  }
}
