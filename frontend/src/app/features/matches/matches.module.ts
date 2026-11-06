import { NgModule } from '@angular/core';

import { SharedModule } from '../../shared/shared.module';
import { MatchesPageRoutingModule } from './matches-routing.module';
import { MatchesPage } from './matches.page';

@NgModule({
  imports: [SharedModule, MatchesPageRoutingModule],
  declarations: [MatchesPage]
})
export class MatchesPageModule {}
