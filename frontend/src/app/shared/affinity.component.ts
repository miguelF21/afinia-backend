import { Component, Input } from '@angular/core';

let uid = 0;

/** Anillo de porcentaje de afinidad. */
@Component({
  selector: 'app-affinity-ring',
  standalone: false,
  template: `
    <div class="ring" [style.--s.px]="size">
      <svg viewBox="0 0 44 44" aria-hidden="true">
        <defs>
          <linearGradient [attr.id]="gid" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#ff8fb1" /><stop offset="1" stop-color="#d81f57" />
          </linearGradient>
        </defs>
        <circle cx="22" cy="22" r="18" fill="none" [attr.stroke]="track" stroke-width="5" />
        <circle cx="22" cy="22" r="18" fill="none" [attr.stroke]="'url(#' + gid + ')'" stroke-width="5" stroke-linecap="round"
                [attr.stroke-dasharray]="circ" [attr.stroke-dashoffset]="circ * (1 - value / 100)" transform="rotate(-90 22 22)"
                class="arc" />
      </svg>
      <span class="num"><b>{{ value }}%</b><small *ngIf="label">{{ label }}</small></span>
    </div>`,
  styles: [`
    :host { display: inline-block; }
    .ring { --s: 80px; position: relative; width: var(--s); height: var(--s); }
    svg { width: 100%; height: 100%; }
    .arc { transition: stroke-dashoffset 1s var(--af-ease); }
    .num { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; line-height: 1.05; }
    b { font-size: calc(var(--s) * .24); font-weight: 800; color: inherit; }
    small { font-size: calc(var(--s) * .12); font-weight: 600; opacity: .75; }
  `],
})
export class AffinityRingComponent {
  @Input() value = 0;
  @Input() size = 80;
  @Input() label = '';
  @Input() track = 'rgba(216,31,87,.14)';
  circ = 2 * Math.PI * 18;
  gid = 'af-ring-' + uid++;
}

/** Píldora destacada "92% afinidad". */
@Component({
  selector: 'app-affinity-badge',
  standalone: false,
  template: `<span class="pill" [class.lg]="large"><ion-icon name="heart"></ion-icon><b>{{ value }}%</b><span>afinidad</span></span>`,
  styles: [`
    :host { display: inline-block; }
    .pill { display: inline-flex; align-items: center; gap: 6px; padding: 7px 13px 7px 10px; border-radius: 999px; background: #fff;
      color: var(--af-ink); font-size: 12.5px; box-shadow: 0 6px 18px rgba(120,30,80,.18); }
    ion-icon { color: var(--af-raspberry); font-size: 15px; }
    b { font-weight: 800; font-size: 14px; }
    span span, .pill > span { color: var(--af-muted); font-weight: 600; }
    .lg { padding: 9px 16px 9px 12px; font-size: 14px; ion-icon { font-size: 18px; } b { font-size: 18px; } }
  `],
})
export class AffinityBadgeComponent {
  @Input() value = 0;
  @Input() large = false;
}
