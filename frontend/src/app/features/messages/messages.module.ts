import { NgModule } from '@angular/core';

import { SharedModule } from '../../shared/shared.module';
import { MessagesPageRoutingModule } from './messages-routing.module';
import { MessagesPage } from './messages.page';

@NgModule({
  imports: [SharedModule, MessagesPageRoutingModule],
  declarations: [MessagesPage]
})
export class MessagesPageModule {}
