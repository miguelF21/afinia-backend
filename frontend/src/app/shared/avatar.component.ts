import { Component, Input } from '@angular/core';

const TONES: [string, string][] = [
  ['#f8c9d6', '#e58aa8'], ['#e0d3f5', '#a98bd9'], ['#ffdcc8', '#f0a58a'],
  ['#cfe8e1', '#86bfb0'], ['#f9d3e6', '#d78ab5'], ['#d3e3f8', '#8fb0e0'],
];

@Component({
  selector: 'app-avatar',
  standalone: false,
  template: `
    <span class="av" [style.--s.px]="size" [style.background]="bg">
      <img *ngIf="src" [src]="src" [alt]="name" />
      <b *ngIf="!src">{{ initial }}</b>
      <i class="dot" *ngIf="online"></i>
    </span>`,
  styles: [`
    :host { display: inline-block; flex: none; }
    .av { --s: 44px; position: relative; width: var(--s); height: var(--s); border-radius: 50%; display: grid; place-items: center;
      color: #fff; box-shadow: 0 0 0 2px #fff, 0 2px 8px rgba(120,40,90,.15); }
    img { width: 100%; height: 100%; border-radius: 50%; object-fit: cover; }
    b { font-size: calc(var(--s) * .4); font-weight: 800; text-shadow: 0 1px 4px rgba(0,0,0,.15); }
    .dot { position: absolute; right: -1px; bottom: -1px; width: calc(var(--s) * .27); height: calc(var(--s) * .27); min-width: 9px; min-height: 9px;
      border-radius: 50%; background: #2fc46f; box-shadow: 0 0 0 2px #fff; }
  `],
})
export class AvatarComponent {
  @Input() name = '';
  @Input() tone = 0;
  @Input() size = 44;
  @Input() online = false;
  @Input() src?: string;
  get initial() { return (this.name || '?').trim().charAt(0).toUpperCase(); }
  get bg() { const t = TONES[this.tone % TONES.length]; return `linear-gradient(145deg, ${t[0]}, ${t[1]})`; }
}
