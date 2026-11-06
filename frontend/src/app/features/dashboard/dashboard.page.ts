import { Component, OnInit } from '@angular/core';
import { Router } from '@angular/router';
import { DemoDataService } from '../../core/demo-data.service';
import { Person } from '../../core/models';
import { UserStateService } from '../../core/user-state.service';

@Component({
  selector: 'app-dashboard',
  templateUrl: './dashboard.page.html',
  styleUrls: ['./dashboard.page.scss'],
  standalone: false,
})
export class DashboardPage implements OnInit {
  leaving: 'like' | 'pass' | null = null;
  expanded = false;
  filtersOpen = false;
  matched: Person | null = null;
  readonly thresholds = [0, 70, 80, 90];

  constructor(public data: DemoDataService, public user: UserStateService, private router: Router) {}

  ngOnInit() {
    this.data.loadPotentialQueue();
  }

  ionViewWillEnter() {
    this.data.loadPotentialQueue();
  }

  get profiles(): Person[] { return this.data.filteredQueue; }
  get currentProfile(): Person | null { return this.profiles[0] ?? null; }
  get nextProfile(): Person | null { return this.profiles[1] ?? null; }
  get remaining(): number { return this.profiles.length; }
  get dots(): number[] { return Array.from({ length: Math.min(this.remaining, 3) }, (_, i) => i); }
  get filtersActive(): boolean { return this.data.minAffinity > 0 || this.data.onlyOnline; }

  onLike() { this.act('like'); }
  onPass() { this.act('pass'); }

  onFavorite() {
    if (this.currentProfile) this.data.toggleFavorite(this.currentProfile);
  }

  private act(kind: 'like' | 'pass') {
    const p = this.currentProfile;
    if (!p || this.leaving) return;
    this.leaving = kind;
    this.expanded = false;

    setTimeout(() => {
      if (kind === 'like') {
        const m = this.data.like(p);
        this.matched = m ? p : null;
      } else {
        this.data.pass(p);
      }
      this.leaving = null;
    }, 380);
  }

  goChat() {
    const id = this.matched ? 'm-' + this.matched.id : null;
    this.matched = null;
    if (id) this.router.navigate(['/messages', id]);
  }

  setMin(v: number) { this.data.minAffinity = v; }
  resetFilters() { this.data.minAffinity = 0; this.data.onlyOnline = false; this.data.query = ''; }
}
