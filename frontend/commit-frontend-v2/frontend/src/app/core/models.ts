export interface Person {
  id: string;
  name: string;
  /** null cuando el servidor no entrega el dato (no se inventa). */
  age: number | null;
  city: string | null;
  bio: string;
  interests: string[];
  /** Porcentaje 0-100 calculado por el servidor; null si el servidor no lo entrega (0 es un valor válido). */
  affinity: number | null;
  /** true solo si el servidor lo informa; por defecto false. */
  online: boolean;
  /** Índice de paleta para el avatar/foto de relleno (0-5). */
  tone: number;
  /** Solo para la demostración visual del "¡Es un match!". */
  likesYou?: boolean;
  photoUrl?: string;
  photos?: string[];
  gender?: string;
  relationshipGoal?: string;
}

export interface ChatMessage {
  id: string;
  fromMe: boolean;
  text: string;
  at: string; // ISO
  read?: boolean;
  /** 'sending' y 'failed' solo existen en el navegador; un mensaje sin estado viene confirmado por el servidor. */
  status?: 'sending' | 'failed';
}

export interface MyProfile {
  first_name: string;
  gender: string;
  age: number | null;
  city: string;
  bio: string;
  interests: string[];
  email: string;
  photoUrl?: string;
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
