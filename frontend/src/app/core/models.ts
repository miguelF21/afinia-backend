export interface Person {
  id: string;
  name: string;
  age: number;
  city: string;
  bio: string;
  interests: string[];
  affinity: number;
  online: boolean;
  /** Índice de paleta para el avatar/foto de relleno (0-5). */
  tone: number;
  /** Solo para la demostración visual del "¡Es un match!". */
  likesYou?: boolean;
}

export interface ChatMessage {
  id: string;
  fromMe: boolean;
  text: string;
  at: string; // ISO
  read?: boolean;
}

export interface MyProfile {
  first_name: string;
  gender: string;
  age: number | null;
  city: string;
  bio: string;
  interests: string[];
  email: string;
}

export interface MyAnalytics {
  intro_extro: number;
  hobbies: number;
  target: string;
}

export interface AppSettings {
  notifyMessages: boolean;
  notifyMatches: boolean;
  notifyNews: boolean;
  showOnline: boolean;
  showCity: boolean;
  visible: boolean;
  ageMin: number;
  ageMax: number;
  distanceKm: number;
}

export const INTEREST_CATALOG = [
  'Viajes', 'Música', 'Naturaleza', 'Cine', 'Deportes', 'Fotografía', 'Café', 'Lectura',
  'Baile', 'Cocina', 'Mascotas', 'Tecnología', 'Arte', 'Yoga', 'Videojuegos', 'Ciclismo',
];
