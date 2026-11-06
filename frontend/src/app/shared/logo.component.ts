import { Component, Input } from '@angular/core';

let uid = 0;

/** Marca AFINIA: infinito-corazón + nombre. */
@Component({
  selector: 'app-logo',
  standalone: false,
  template: `
    <span class="logo" [class.stack]="stacked" [class.light]="light" [style.--s.px]="size">
      <svg class="mark" viewBox="0 0 64 40" aria-hidden="true">
        <defs>
          <linearGradient [attr.id]="gid" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" [attr.stop-color]="light ? '#ffd0e0' : '#ff8fb1'" />
            <stop offset="1" [attr.stop-color]="light ? '#ff7fa6' : '#d81f57'" />
          </linearGradient>
        </defs>
        <path d="M32 20C26 10 18 6 12 6 5 6 2 12 2 20s3 14 10 14c6 0 14-4 20-14s14-14 20-14c7 0 10 6 10 14s-3 14-10 14c-6 0-14-4-20-14z"
              fill="none" [attr.stroke]="'url(#' + gid + ')'" stroke-width="7" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      <span class="word" *ngIf="!markOnly">AFINIA</span>
    </span>`,
  styles: [`
    :host { display: inline-block; }
    .logo { --s: 34px; display: inline-flex; align-items: center; gap: calc(var(--s) * .3); color: var(--af-raspberry); line-height: 1; }
    .logo.stack { flex-direction: column; gap: calc(var(--s) * .12); }
    .logo.light { color: #fff; }
    .mark { width: calc(var(--s) * 1.55); height: auto; flex: none; filter: drop-shadow(0 4px 8px rgba(216,31,87,.25)); }
    .word { font-weight: 800; font-size: calc(var(--s) * .78); letter-spacing: calc(var(--s) * .02); }
    .stack .mark { width: calc(var(--s) * 2.1); }
    .stack .word { font-size: calc(var(--s) * 1.05); }
  `],
})
export class LogoComponent {
  @Input() size = 34;
  @Input() stacked = false;
  @Input() light = false;
  @Input() markOnly = false;
  gid = 'af-lg-' + uid++;
}
