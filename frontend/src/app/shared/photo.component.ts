import { Component, Input } from '@angular/core';

const TONES: [string, string][] = [
  ['#f8c9d6', '#e58aa8'], ['#e0d3f5', '#a98bd9'], ['#ffdcc8', '#f0a58a'],
  ['#cfe8e1', '#86bfb0'], ['#f9d3e6', '#d78ab5'], ['#d3e3f8', '#8fb0e0'],
];

/**
 * Imagen de relleno para perfiles (el backend sirve fotos en /profile/photos/media/{id};
 * cuando exista la URL real basta con pasarla en [src]).
 */
@Component({
  selector: 'app-photo',
  standalone: false,
  template: `
    <div class="ph" [style.background]="bg">
      <img *ngIf="src" [src]="src" [alt]="name" />
      <ng-container *ngIf="!src">
        <span class="blob b1"></span><span class="blob b2"></span>
        <svg viewBox="0 0 200 240" preserveAspectRatio="xMidYMax slice" aria-hidden="true">
          <path *ngIf="long" d="M54 124c-8-54 12-88 46-88s54 34 46 88c-2 24 6 42 14 56H40c8-14 16-32 14-56z" [attr.fill]="dark" opacity=".4" />
          <g fill="#fff" opacity=".74">
            <path d="M18 250c0-50 36-80 82-80s82 30 82 80z" />
            <rect x="86" y="132" width="28" height="48" rx="14" />
            <ellipse cx="100" cy="100" rx="34" ry="40" />
          </g>
          <path *ngIf="!long" d="M64 96c-5-34 14-56 38-56 26 0 42 22 34 56-6-18-18-26-36-26s-30 8-36 26z" [attr.fill]="dark" opacity=".5" />
        </svg>
      </ng-container>
      <ng-content></ng-content>
    </div>`,
  styles: [`
    :host { display: block; width: 100%; height: 100%; }
    .ph { position: relative; width: 100%; height: 100%; overflow: hidden; }
    img { width: 100%; height: 100%; object-fit: cover; display: block; }
    svg { position: absolute; inset: 0; width: 100%; height: 100%; }
    .blob { position: absolute; border-radius: 50%; background: rgba(255,255,255,.35); filter: blur(24px); }
    .b1 { width: 60%; aspect-ratio: 1; top: -12%; left: -14%; }
    .b2 { width: 50%; aspect-ratio: 1; bottom: 10%; right: -16%; }
  `],
})
export class PhotoComponent {
  @Input() tone = 0;
  @Input() name = '';
  @Input() src?: string;
  get bg() { const t = TONES[this.tone % TONES.length]; return `linear-gradient(160deg, ${t[0]}, ${t[1]})`; }
  get long() { return this.tone % 2 === 0 || this.tone === 1; }
  get dark() { return TONES[this.tone % TONES.length][1]; }
}
