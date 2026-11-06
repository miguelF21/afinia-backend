import { Component, HostListener } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { filter } from 'rxjs';
import { DemoDataService } from '../core/demo-data.service';
import { AuthService } from '../core/services/auth.service';
import { UserStateService } from '../core/user-state.service';

interface NavItem { path: string; label: string; icon: string; badge?: () => number; }

@Component({
  selector: 'app-shell',
  templateUrl: './shell.component.html',
  styleUrls: ['./shell.component.scss'],
  standalone: false,
  host: { class: 'ion-page' },
})
export class ShellComponent {
  menuOpen = false;
  url = '';

  nav: NavItem[] = [
    { path: '/dashboard', label: 'Descubrir', icon: 'home' },
    { path: '/matches', label: 'Mis Matches', icon: 'heart' },
    { path: '/messages', label: 'Mensajes', icon: 'chatbubble', badge: () => this.data.unreadTotal },
    { path: '/profile', label: 'Mi Perfil', icon: 'person' },
    { path: '/settings', label: 'Configuración', icon: 'settings' },
  ];

  constructor(
    public data: DemoDataService,
    public user: UserStateService,
    private auth: AuthService,
    private router: Router
  ) {
    this.url = router.url;
    router.events.pipe(filter(e => e instanceof NavigationEnd)).subscribe(() => {
      this.url = router.url; this.menuOpen = false;
    });
  }

  get showPanel(): boolean { return this.url.startsWith('/dashboard'); }
  get showSearch(): boolean { return /^\/(dashboard|matches|messages)/.test(this.url); }
  get inChat(): boolean { return /^\/messages\/.+/.test(this.url); }
  get panelChats() { return this.data.conversations.slice(0, 4); }

  logout() {
    this.auth.logout();
    this.user.clear();
    this.router.navigate(['/login']);
  }

  @HostListener('document:click', ['$event'])
  closeMenu(e: Event) {
    if (this.menuOpen && !(e.target as HTMLElement).closest('.me')) this.menuOpen = false;
  }
}
