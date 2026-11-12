import { AfterViewChecked, Component, ElementRef, ViewChild } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { DemoDataService } from '../../core/demo-data.service';
import { Person } from '../../core/models';

@Component({
  selector: 'app-messages',
  templateUrl: './messages.page.html',
  styleUrls: ['./messages.page.scss'],
  standalone: false,
})
export class MessagesPage implements AfterViewChecked {
  @ViewChild('scroller') scroller?: ElementRef<HTMLElement>;
  draft = '';
  routeId: string | null = null;
  private lastCount = -1;
  private lastId = '';

  constructor(public data: DemoDataService, route: ActivatedRoute, private router: Router) {
    route.paramMap.subscribe((p) => {
      this.routeId = p.get('id');
      if (this.routeId) {
        this.data.loadMessages(this.routeId);
        this.data.markRead(this.routeId);
      }
    });
  }

  ionViewWillEnter() {
    this.data.loadMatches();
    if (this.routeId) {
      this.data.loadMessages(this.routeId);
    }
  }

  /** En escritorio se muestra siempre una conversación; en móvil solo si hay :id. */
  get activeId(): string | null {
    if (this.routeId) return this.routeId;
    return null;
  }
  get desktopId(): string | null { return this.routeId ?? this.data.conversations[0]?.id ?? null; }
  get active(): Person | undefined { return this.desktopId ? this.data.person(this.desktopId) : undefined; }
  get thread() { return this.desktopId ? this.data.messages(this.desktopId) : []; }
  get list(): Person[] {
    const q = this.data.query.trim().toLowerCase();
    const withChat = this.data.conversations;
    const noChat = this.data.matches.filter(m => !this.data.messages(m.id).length);
    return [...withChat, ...noChat].filter(p => !q || p.name.toLowerCase().includes(q));
  }
  get icebreakers(): string[] {
    const p = this.active;
    if (!p) return [];
    // Solo frases genéricas: no se inventan intereses que el servidor no entrega.
    return [`¡Hola ${p.name}! 👋`, `¿Qué te gusta hacer en tu tiempo libre?`, `Cuéntame un poco más sobre ti 😊`];
  }

  select(p: Person) { this.router.navigate(['/messages', p.id]); }
  back() { this.router.navigate(['/messages']); }

  send(text = this.draft) {
    const id = this.desktopId;
    if (!id || !text.trim()) return;
    this.data.send(id, text);
    this.draft = '';
    this.data.markRead(id);
  }

  dayLabel(iso: string) { return this.data.timeLabel(iso); }

  ngAfterViewChecked() {
    const el = this.scroller?.nativeElement;
    if (!el) return;
    const n = this.thread.length, id = this.desktopId ?? '';
    if (n !== this.lastCount || id !== this.lastId) { el.scrollTop = el.scrollHeight; this.lastCount = n; this.lastId = id; }
  }
}
