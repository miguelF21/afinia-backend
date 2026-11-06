import { Component, Input } from '@angular/core';

/** Estructura común de las pantallas de acceso: panel de marca + contenido. */
@Component({
  selector: 'app-auth-layout',
  standalone: false,
  template: `
    <div class="auth">
      <aside class="brand">
        <span class="orb o1"></span><span class="orb o2"></span><span class="orb o3"></span>
        <ion-icon class="fh h1" name="heart"></ion-icon><ion-icon class="fh h2" name="heart"></ion-icon><ion-icon class="fh h3" name="heart"></ion-icon>
        <div class="brand-in">
          <app-logo [size]="46" [stacked]="true" [light]="true"></app-logo>
          <p class="tag">Conecta, comparte<br />y encuentra tu afinidad</p>
          <span class="swoosh"></span>
          <ul class="feats">
            <li><ion-icon name="heart-outline"></ion-icon><span>Descubre perfiles compatibles</span></li>
            <li><ion-icon name="chatbubble-ellipses-outline"></ion-icon><span>Chatea sin límites</span></li>
            <li><ion-icon name="shield-checkmark-outline"></ion-icon><span>Conoce con confianza</span></li>
          </ul>
          <p class="script">Tu mejor conexión está aquí</p>
        </div>
      </aside>

      <main class="panel">
        <div class="mobile-brand"><app-logo [size]="30"></app-logo></div>
        <div class="sheet" [style.max-width.px]="width"><ng-content></ng-content></div>
        <p class="legal">AFINIA · Conecta. Encuentra. Disfruta.</p>
      </main>
    </div>`,
  styles: [`
    :host { display: block; min-height: 100%; }
    .auth { display: grid; grid-template-columns: minmax(380px, 44%) 1fr; min-height: 100vh; background: #fff; }

    .brand { position: relative; overflow: hidden; color: #fff; display: grid; place-items: center; padding: 48px;
      background: radial-gradient(120% 90% at 0% 0%, #f0507f 0%, rgba(240,80,127,0) 55%),
                  radial-gradient(90% 80% at 100% 100%, #9c1146 0%, rgba(156,17,70,0) 60%),
                  linear-gradient(160deg, #e0275f, #c31650 55%, #a50f43); }
    .orb { position: absolute; border-radius: 50%; background: rgba(255,255,255,.10); }
    .o1 { width: 420px; height: 420px; top: -140px; right: -150px; }
    .o2 { width: 300px; height: 300px; bottom: -90px; left: -90px; background: rgba(255,214,228,.12); }
    .o3 { width: 140px; height: 140px; top: 46%; right: 8%; background: rgba(255,255,255,.07); }
    .fh { position: absolute; color: rgba(255,255,255,.18); animation: af-float 7s ease-in-out infinite; }
    .h1 { font-size: 64px; top: 9%; left: 10%; --r: -12deg; }
    .h2 { font-size: 38px; top: 20%; right: 14%; --r: 14deg; animation-delay: -2s; }
    .h3 { font-size: 90px; bottom: 7%; right: 9%; --r: 10deg; animation-delay: -4s; color: rgba(255,255,255,.12); }
    .brand-in { position: relative; text-align: center; max-width: 380px; }
    .tag { font-size: 26px; font-weight: 700; line-height: 1.25; margin: 26px 0 8px; letter-spacing: -.3px; }
    .swoosh { display: block; width: 110px; height: 4px; border-radius: 4px; margin: 0 auto 34px; background: linear-gradient(90deg, transparent, #ffc2d5, transparent); }
    .feats { list-style: none; padding: 0; margin: 0 auto; display: grid; gap: 14px; text-align: left; width: max-content; max-width: 100%; }
    .feats li { display: flex; align-items: center; gap: 14px; font-weight: 600; font-size: 16px; }
    .feats ion-icon { font-size: 22px; padding: 10px; border-radius: 14px; background: rgba(255,255,255,.16); backdrop-filter: blur(6px); }
    .script { font-family: var(--af-font-script); font-size: 32px; margin: 40px 0 0; color: #ffe3ec; transform: rotate(-3deg); }

    .panel { position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 40px 24px;
      background: radial-gradient(70% 50% at 100% 0%, #fff0f5 0%, rgba(255,240,245,0) 70%), radial-gradient(60% 50% at 0% 100%, #f5eefd 0%, rgba(245,238,253,0) 70%), #fff; }
    .sheet { width: 100%; max-width: 440px; animation: af-rise .55s var(--af-ease) both; }
    .mobile-brand { display: none; margin-bottom: 22px; }
    .legal { margin: 28px 0 0; font-size: 12.5px; color: var(--af-muted); font-weight: 600; }

    @media (max-width: 900px) {
      .auth { grid-template-columns: 1fr; }
      .brand { display: none; }
      .mobile-brand { display: block; }
      .panel { justify-content: flex-start; padding-top: calc(36px + env(safe-area-inset-top)); min-height: 100vh; }
    }
  `],
})
export class AuthLayoutComponent {
  @Input() width = 440;
}
