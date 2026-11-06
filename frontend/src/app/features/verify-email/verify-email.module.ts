import { NgModule } from '@angular/core';

import { SharedModule } from '../../shared/shared.module';
import { VerifyEmailPageRoutingModule } from './verify-email-routing.module';
import { VerifyEmailPage } from './verify-email.page';

@NgModule({
  imports: [SharedModule, VerifyEmailPageRoutingModule],
  declarations: [VerifyEmailPage]
})
export class VerifyEmailPageModule {}
