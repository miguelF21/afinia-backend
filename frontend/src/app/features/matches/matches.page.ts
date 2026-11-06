import { Component, OnInit } from '@angular/core';
import { DemoDataService } from '../../core/demo-data.service';
import { Person } from '../../core/models';

type Tab = 'all' | 'new' | 'online';

@Component({
  selector: 'app-matches',
  templateUrl: './matches.page.html',
  styleUrls: ['./matches.page.scss'],
  standalone: false,
})
export class MatchesPage implements OnInit {
  tab: Tab = 'all';

  constructor(public data: DemoDataService) {}

  ngOnInit() {
    this.data.loadMatches();
  }

  ionViewWillEnter() {
    this.data.loadMatches();
  }

  get list(): Person[] {
    const base = this.data.filteredMatches;
    if (this.tab === 'online') return base.filter(p => p.online);
    if (this.tab === 'new') return base.filter(p => this.data.messages(p.id).length <= 1 || this.data.unread[p.id]);
    return base;
  }
  get tabs() {
    const all = this.data.filteredMatches;
    return [
      { id: 'all' as Tab, label: 'Todos', n: all.length },
      { id: 'new' as Tab, label: 'Nuevos', n: all.filter(p => this.data.messages(p.id).length <= 1 || this.data.unread[p.id]).length },
      { id: 'online' as Tab, label: 'En línea', n: all.filter(p => p.online).length },
    ];
  }
  isNew(p: Person) { return (this.data.messages(p.id).length <= 1 && !!this.data.unread[p.id]) || !this.data.messages(p.id).length; }
}
