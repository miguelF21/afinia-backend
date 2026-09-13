# UI DESIGN SYSTEM - AFINIA

Este documento define la base visual de Afinia (Mobile-First en Ionic/Angular).

## 1. Identidad
Afinia tiene un tono de investigación pero debe sentirse juvenil, moderna e intuitiva, alejándose de los patrones estéticos exactos de Tinder (Rojo/Fuego) o Bumble (Amarillo/Panal).

## 2. Paleta de Colores
- **Primary Color:** `#5B37B7` (Púrpura vibrante) - Botones principales, acentos.
- **Secondary Color:** `#00C49A` (Verde menta) - Éxito, matches.
- **Tertiary Color / Action:** `#FF5E7E` (Rosa coral) - Acciones secundarias o negativas (PASS).
- **Background:** `#F7F9FC` (Gris muy claro) - Fondos de vistas.
- **Surface:** `#FFFFFF` (Blanco) - Tarjetas, modales.
- **Text Primary:** `#2C3E50` (Azul oscuro profundo).
- **Text Secondary:** `#7F8C8D` (Gris frío).

## 3. Tipografía
- **Fuente Principal:** `Inter` o `Roboto` (San-Serif geométrica, alta legibilidad).
- **Títulos (H1, H2):** Bold (700).
- **Cuerpo:** Regular (400) o Medium (500).

## 4. Botones
- **Solid Button:** Fondo Primary, texto blanco. Esquinas redondeadas (`border-radius: 25px` o píldora).
- **Outline Button:** Borde Primary, fondo transparente, texto Primary.
- **Ghost Button:** Sin borde, sin fondo, texto Primary (para "Omitir" o acciones terciarias).

## 5. Tarjetas (Cards)
- **Profile Card (Swipe):** 
  - Ocupa el 85% de la altura de la pantalla (en móvil).
  - Esquinas redondeadas (`20px`).
  - Sombra sutil: `box-shadow: 0 10px 20px rgba(0,0,0,0.1)`.
  - La información (Nombre, Edad, Bio corta) superpuesta con gradiente inferior oscuro para asegurar contraste.

## 6. Feedback Visual
- **Loading:** Skeleton screens preferidos sobre spinners para el contenido principal del perfil. Spinners sutiles para peticiones de red pequeñas (botones).
- **Match State:** Modal a pantalla completa o bottom sheet, confetti sutil, colores vibrantes (Primary + Secondary).
- **Empty States:** Ilustraciones vectoriales minimalistas acompañadas de un mensaje amigable (ej. "No hay más perfiles por ahora, ajusta tus filtros").

## 7. Navegación
- **Tabs (Inferiores):**
  1. Perfil (Gestión de configuración).
  2. Descubrir (Cards).
  3. Matches (Lista de coincidencias).
